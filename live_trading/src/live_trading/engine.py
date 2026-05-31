from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from .arb import evaluate_match
from .books import BookStore
from .metrics import MetricsCollector
from .models import ArbOpportunity, BookState
from .registry import PairRegistry


@dataclass
class OpportunityStore:
    _by_match: dict[str, tuple[ArbOpportunity, ...]] = field(default_factory=dict)

    def replace_for_match(self, match_id: str, opportunities: list[ArbOpportunity]) -> None:
        if opportunities:
            self._by_match[match_id] = tuple(opportunities)
        else:
            self._by_match.pop(match_id, None)

    def snapshot(self) -> list[ArbOpportunity]:
        opportunities = [opportunity for values in self._by_match.values() for opportunity in values]
        opportunities.sort(key=lambda item: item.net_edge_per_contract, reverse=True)
        return opportunities

    def retain(self, match_ids: set[str]) -> None:
        self._by_match = {
            match_id: opportunities
            for match_id, opportunities in self._by_match.items()
            if match_id in match_ids
        }


class HotPathEngine:
    def __init__(
        self,
        registry: PairRegistry,
        books: BookStore,
        metrics: MetricsCollector,
        *,
        trade_size: int,
        slippage_buffer_per_pair: Decimal,
        kalshi_fee_mode: str,
        polymarket_theta: Decimal,
        min_gross_edge: Decimal,
        recorder=None,
    ) -> None:
        self.registry = registry
        self.books = books
        self.metrics = metrics
        self.trade_size = trade_size
        self.slippage_buffer_per_pair = slippage_buffer_per_pair
        self.kalshi_fee_mode = kalshi_fee_mode
        self.polymarket_theta = polymarket_theta
        self.min_gross_edge = min_gross_edge
        self.recorder = recorder
        self.opportunities = OpportunityStore()
        self.signal_queue: asyncio.PriorityQueue[tuple[Decimal, int, ArbOpportunity]] = asyncio.PriorityQueue()
        self._signal_counter = itertools.count()

    def process_book(self, book: BookState) -> list[ArbOpportunity]:
        started = time.perf_counter()
        self.books.set(book)
        self.metrics.increment("updates_processed")
        if self.recorder:
            self.recorder.try_record_book(book)

        emitted: list[ArbOpportunity] = []
        for match in self.registry.for_market(book.venue, book.market_key):
            self.metrics.increment("pair_evaluations")
            opportunities = evaluate_match(
                match,
                self.books.get("kalshi", match.kalshi.stream_key),
                self.books.get("polymarket_us", match.polymarket_us.stream_key),
                trade_size=self.trade_size,
                slippage_buffer_per_pair=self.slippage_buffer_per_pair,
                kalshi_fee_mode=self.kalshi_fee_mode,
                polymarket_theta=self.polymarket_theta,
                min_gross_edge=self.min_gross_edge,
            )
            self.opportunities.replace_for_match(match.match_id, opportunities)
            for opportunity in opportunities:
                self.signal_queue.put_nowait(
                    (-opportunity.net_edge_per_contract, next(self._signal_counter), opportunity)
                )
                self.metrics.set_gauge("signal_queue_depth", float(self.signal_queue.qsize()))
                self.metrics.increment("opportunities_emitted")
                emitted.append(opportunity)

        finished = time.perf_counter()
        receipt_to_eval_ms = max(0.0, (time.perf_counter_ns() - book.received_monotonic_ns) / 1_000_000)
        self.metrics.record_evaluation(receipt_to_eval_ms, (finished - started) * 1000)
        return emitted

    async def pump_signals(self) -> None:
        while True:
            _, _, opportunity = await self.signal_queue.get()
            self.metrics.set_gauge("signal_queue_depth", float(self.signal_queue.qsize()))
            try:
                if self.recorder:
                    self.recorder.try_record_opportunity(opportunity)
            finally:
                self.signal_queue.task_done()
