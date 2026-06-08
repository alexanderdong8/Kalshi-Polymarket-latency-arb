from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from .books import BookStore
from .books.kalshi import KalshiOrderBook
from .books.polymarket_us import PolymarketUsBook
from .jsonl import JsonlWriter
from .models import EventSpec, OutcomeSpec


def _seed_yes_prices(outcomes: Iterable[OutcomeSpec]) -> dict[str, Decimal]:
    """Draw plausible YES prices that sum to ~1 (so the basket sanity-checks out)."""
    raw = [random.uniform(0.05, 0.5) for _ in outcomes]
    total = sum(raw)
    return {o.name: Decimal(str(round(r / total, 3))) for o, r in zip(outcomes, raw)}


def _build_kalshi_message(ticker: str, yes_price_dollars: Decimal, seq: int) -> dict:
    """Synthesize a Kalshi orderbook_snapshot in cents."""
    yes_c = max(1, int(yes_price_dollars * 100))
    no_c = max(1, 100 - yes_c)
    return {
        "type": "orderbook_snapshot",
        "seq": seq,
        "msg": {
            "market_ticker": ticker,
            "yes_dollars_fp": [
                [yes_c, random.randint(50, 300)],
                [max(1, yes_c - 1), random.randint(100, 400)],
                [max(1, yes_c - 2), random.randint(200, 600)],
            ],
            "no_dollars_fp": [
                [no_c, random.randint(50, 300)],
                [max(1, no_c - 1), random.randint(100, 400)],
                [max(1, no_c - 2), random.randint(200, 600)],
            ],
        },
    }


def _build_polymarket_payload(slug: str, yes_price: Decimal) -> dict:
    """Synthesize a Polymarket US marketData payload (native bids/asks in dollars)."""
    bid = max(Decimal("0.01"), yes_price - Decimal("0.01"))
    ask = min(Decimal("0.99"), yes_price + Decimal("0.01"))
    return {
        "marketData": {
            "marketSlug": slug,
            "bids": [
                {"price": str(bid), "size": str(random.randint(100, 500))},
                {"price": str(max(Decimal("0.01"), bid - Decimal("0.01"))), "size": str(random.randint(200, 800))},
            ],
            "offers": [
                {"price": str(ask), "size": str(random.randint(100, 500))},
                {"price": str(min(Decimal("0.99"), ask + Decimal("0.01"))), "size": str(random.randint(200, 800))},
            ],
            "lastTradePrice": str(yes_price),
            "transactTime": datetime.now(timezone.utc).isoformat(),
            "state": "OPEN",
        }
    }


async def run_kalshi_mock(
    event: EventSpec, store: BookStore, jsonl: JsonlWriter, *, interval: float = 0.4
) -> None:
    prices = _seed_yes_prices(event.outcomes)
    books = {
        o.kalshi_ticker: KalshiOrderBook(market_ticker=o.kalshi_ticker, outcome_name=o.name)
        for o in event.outcomes
    }
    seq = 0
    await jsonl.write_event("info", {"mode": "mock", "endpoint": "synthetic"}, kind="lifecycle")
    while True:
        for outcome in event.outcomes:
            seq += 1
            # Random walk on price, clamped
            drift = Decimal(str(round(random.uniform(-0.015, 0.015), 3)))
            prices[outcome.name] = max(Decimal("0.02"), min(Decimal("0.98"), prices[outcome.name] + drift))
            msg = _build_kalshi_message(outcome.kalshi_ticker, prices[outcome.name], seq)
            await jsonl.write_event("in", msg)
            snap = books[outcome.kalshi_ticker].apply_snapshot(msg, received_ts=datetime.now(timezone.utc))
            await store.set(snap)
        await asyncio.sleep(interval)


async def run_polymarket_mock(
    event: EventSpec, store: BookStore, jsonl: JsonlWriter, *, interval: float = 0.5
) -> None:
    prices = _seed_yes_prices(event.outcomes)
    books = {
        o.polymarket_slug: PolymarketUsBook(market_slug=o.polymarket_slug, outcome_name=o.name)
        for o in event.outcomes
    }
    await jsonl.write_event("info", {"mode": "mock", "endpoint": "synthetic"}, kind="lifecycle")
    while True:
        for outcome in event.outcomes:
            drift = Decimal(str(round(random.uniform(-0.015, 0.015), 3)))
            prices[outcome.name] = max(Decimal("0.02"), min(Decimal("0.98"), prices[outcome.name] + drift))
            payload = _build_polymarket_payload(outcome.polymarket_slug, prices[outcome.name])
            await jsonl.write_event("in", payload)
            snap = books[outcome.polymarket_slug].apply_market_data(
                payload["marketData"], received_ts=datetime.now(timezone.utc)
            )
            await store.set(snap)
        await asyncio.sleep(interval)
