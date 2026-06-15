from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .capture import L2Capture
from .config import Settings
from .execution_persistence import ExecutionJournal
from .live_orders import LiveOrderClient
from .market_data.cache import CacheUpdate
from .runtime import (
    RuntimeState,
    _accounting_payload,
    _cancel_resting_orders,
    _evaluation_payload,
    _json_default,
    _open_basket_from_payload,
)
from .strategy.books import BookStore
from .strategy.bridge import StrategyBookBridge
from .strategy.detector import BasketEvaluation, Detector
from .strategy.execution.client import SimulatedOrderClient
from .strategy.execution.executor import EntryExecutor, ExecConfig, ExitConfig
from .strategy.execution.exit_monitor import ExitMonitor
from .strategy.execution.models import BasketAttempt, ExitAttempt
from .strategy.execution.positions import PositionStore, build_open_basket_from_attempt
from .strategy.fees import FeeConfig
from .strategy.manifest import load_event_manifest


class PooledEventSession:
    """One event/mode strategy state consuming a shared public market-data feed."""

    def __init__(
        self,
        *,
        session_id: str,
        mode: str,
        manifest_path: Path,
        capital: Decimal,
        strategy: dict[str, Any],
        settings: Settings,
        data_root: Path,
    ) -> None:
        self.session_id = session_id
        self.mode = mode
        self.manifest_path = manifest_path
        self.capital = capital
        self.strategy = strategy
        self.settings = settings
        self.data_root = data_root
        self.tasks: list[asyncio.Task[Any]] = []
        self.latest_state: dict[str, Any] = {}
        self._dirty = asyncio.Event()
        self._closed = False

    async def start(self) -> set[tuple[str, str]]:
        manifest = load_event_manifest(self.manifest_path, require_approved=True)
        self.manifest = manifest
        data_dir = self.data_root / manifest.event.slug / self.mode
        data_dir.mkdir(parents=True, exist_ok=True)
        self.journal = ExecutionJournal(data_dir / "execution.sqlite3")
        self.store = BookStore()
        self.bridge = StrategyBookBridge(manifest.event, self.store)
        self.positions = PositionStore()
        for payload in self.journal.open_positions():
            await self.positions.add(_open_basket_from_payload(payload))
        self.fee_cfg = FeeConfig.default()
        self.abort_event = asyncio.Event()
        self.attempts: list[BasketAttempt] = []
        self.exits: list[ExitAttempt] = []
        self.stream_health = {
            "kalshi_updates": 0,
            "polymarket_us_updates": 0,
            "sequence_gaps": 0,
            "reconnects": 0,
        }
        self.detector = Detector(
            event=manifest.event,
            target_size=Decimal(str(self.strategy.get("trade_size", self.settings.trade_size))),
            fee_cfg=self.fee_cfg,
            entry_threshold=Decimal(str(self.strategy.get("entry_threshold", "0.98"))),
            slippage_buffer_per_share=Decimal(str(self.strategy.get("slippage_buffer", "0.005"))),
            depth_haircut=Decimal(str(self.strategy.get("depth_haircut", "0.7"))),
            staleness_ms=float(
                self.strategy.get(
                    "staleness_ms", self.settings.stale_after_seconds * Decimal("1000")
                )
            ),
            min_non_widening_ticks=int(self.strategy.get("min_non_widening_ticks", 2)),
            min_leg_bid=Decimal(str(self.strategy.get("min_leg_bid", "0.02"))),
            max_leg_bid=Decimal(str(self.strategy.get("max_leg_bid", "0.98"))),
        )
        if self.mode == "live":
            self.order_client = LiveOrderClient(self.settings, self.journal)
        else:
            self.order_client = SimulatedOrderClient(
                self.store,
                fee_cfg=self.fee_cfg,
                initial_balance=self.capital / Decimal("2"),
                mutate_books=False,
            )
        self.executor = EntryExecutor(
            event=manifest.event,
            store=self.store,
            order_client=self.order_client,
            fee_cfg=self.fee_cfg,
            exec_cfg=ExecConfig(
                max_capital_per_trade=self.capital,
                min_capital_per_trade=min(Decimal("10"), self.capital),
                retry_seconds=float(self.strategy.get("retry_seconds", 2)),
                max_unhedged_loss_pct=Decimal(
                    str(self.strategy.get("max_unhedged_loss_pct", "0.05"))
                ),
            ),
            entry_threshold=self.detector.entry_threshold,
            slippage_buffer_per_share=self.detector.slippage_buffer_per_share,
            depth_haircut=self.detector.depth_haircut,
            on_attempt=self._on_attempt,
            abort_event=self.abort_event,
        )
        self.exit_monitor = ExitMonitor(
            store=self.store,
            order_client=self.order_client,
            position_store=self.positions,
            fee_cfg=self.fee_cfg,
            cfg=ExitConfig(
                required_margin_per_share=Decimal(
                    str(self.strategy.get("exit_margin", "0.01"))
                ),
                min_leg_bid=Decimal(str(self.strategy.get("min_leg_bid", "0.02"))),
                max_leg_bid=Decimal(str(self.strategy.get("max_leg_bid", "0.98"))),
            ),
            on_exit_attempt=self._on_exit,
        )
        self.capture = L2Capture(data_dir / "capture", manifest.event.slug)
        self.state_channel = RuntimeState(data_dir / "dashboard_state.json")
        await self.capture.start()
        await self.state_channel.start()
        self.latest_evaluation: BasketEvaluation | None = None
        self.tasks = [
            asyncio.create_task(self._strategy_loop(), name=f"{self.session_id}-strategy"),
            asyncio.create_task(self._publish_state(), name=f"{self.session_id}-state"),
        ]
        if self.mode != "monitor":
            self.tasks.append(
                asyncio.create_task(
                    self.exit_monitor.run(), name=f"{self.session_id}-exit-monitor"
                )
            )
        return {
            *{("kalshi", ticker) for ticker in manifest.event.kalshi_tickers},
            *{
                ("polymarket_us", slug)
                for slug in manifest.event.polymarket_slugs
            },
        }

    async def on_market_update(self, update: CacheUpdate) -> None:
        if self._closed:
            return
        if not update.valid:
            self.stream_health["sequence_gaps"] += 1
            self.capture.invalidate(
                f"sequence_gap:{update.book.venue}:{update.book.market_key}:{update.gap}"
            )
            return
        self.stream_health[f"{update.book.venue}_updates"] += 1
        self.capture.record(update.book)
        applied = await self.bridge.apply(update.book)
        if applied is not None:
            self._dirty.set()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.abort_event.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await _cancel_resting_orders(self.order_client)
        await self.capture.close()
        await self.state_channel.close()

    def failure_reason(self) -> str | None:
        for task in self.tasks:
            if not task.done() or task.cancelled():
                continue
            try:
                error = task.exception()
            except asyncio.CancelledError:
                continue
            if error is not None:
                return f"{task.get_name()} failed: {error}"
        return None

    async def _strategy_loop(self) -> None:
        latest_evaluation_at = 0.0
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            elapsed = asyncio.get_running_loop().time() - latest_evaluation_at
            if elapsed < 0.1:
                await asyncio.sleep(0.1 - elapsed)
            books = await self.store.snapshot()
            self.latest_evaluation, fire = self.detector.tick(books)
            latest_evaluation_at = asyncio.get_running_loop().time()
            if fire is not None and self.mode != "monitor":
                asyncio.create_task(
                    self.executor.on_fire(fire), name=f"{self.session_id}-basket-entry"
                )

    async def _publish_state(self) -> None:
        while True:
            books = await self.store.snapshot()
            positions = await self.positions.snapshot()
            accounting = _accounting_payload(self.attempts, self.exits, positions)
            self.latest_state = {
                "mode": self.mode,
                "event": self.manifest.event.name,
                "capital_limit": str(self.capital),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stream_health": self.stream_health,
                "evaluation": _evaluation_payload(self.latest_evaluation),
                "books": {
                    f"{venue}:{outcome}": {
                        "venue": venue,
                        "outcome": outcome,
                        "age_ms": book.age_seconds() * 1000,
                        "bids": [[str(level.price), str(level.size)] for level in book.yes_bids],
                        "asks": [[str(level.price), str(level.size)] for level in book.yes_asks],
                    }
                    for (venue, outcome), book in books.items()
                },
                "attempts": [_json_default(row) for row in self.attempts[-100:]],
                "exits": [_json_default(row) for row in self.exits[-100:]],
                "positions": [_json_default(row) for row in positions],
                **accounting,
            }
            self.state_channel.publish(self.latest_state)
            await asyncio.sleep(0.25)

    async def _on_attempt(self, attempt: BasketAttempt) -> None:
        self.attempts.append(attempt)
        self.journal.append("basket_attempt", attempt, status=attempt.outcome)
        if attempt.outcome == "complete":
            basket = build_open_basket_from_attempt(
                basket_id=f"{self.manifest.event.slug}-{attempt.ts.isoformat()}",
                entered_ts=attempt.ts,
                target_basket_size=attempt.target_basket_size,
                legs=attempt.legs,
            )
            await self.positions.add(basket)
            self.journal.append("position_opened", basket, status="open")

    async def _on_exit(self, attempt: ExitAttempt) -> None:
        self.exits.append(attempt)
        self.journal.append("exit_attempt", attempt, status=attempt.kind)
        if attempt.all_legs_filled:
            self.journal.append(
                "position_closed",
                {
                    "basket_id": attempt.basket_id,
                    "realized_net_per_share": attempt.realized_net_per_share,
                },
                status="closed",
            )
