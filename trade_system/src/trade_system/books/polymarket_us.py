from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..models import BookSnapshot
from ._common import ZERO, level_from_raw, parse_ts, sorted_asks, sorted_bids, to_decimal


@dataclass
class PolymarketUsBook:
    """Stateful order book for one Polymarket US market slug.

    Polymarket US sends full market_data payloads (not deltas), so each message
    replaces the book entirely. We keep the prior state so sparse messages that
    omit some fields fall back to the last known value.
    """
    market_slug: str
    outcome_name: str
    yes_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    yes_asks: dict[Decimal, Decimal] = field(default_factory=dict)
    last_trade_price: Decimal | None = None
    last_venue_ts: datetime | None = None
    last_state: str | None = None

    def apply_market_data(
        self,
        market_data: dict[str, Any],
        received_ts: datetime | None = None,
    ) -> BookSnapshot:
        bids = market_data.get("bids")
        asks = market_data.get("offers") or market_data.get("asks")
        if bids is not None:
            self.yes_bids = {
                lvl.price: lvl.size
                for lvl in (level_from_raw(item) for item in bids)
                if lvl.size > ZERO
            }
        if asks is not None:
            self.yes_asks = {
                lvl.price: lvl.size
                for lvl in (level_from_raw(item) for item in asks)
                if lvl.size > ZERO
            }
        last_trade = market_data.get("lastTradePrice") or market_data.get("last_trade_price")
        if last_trade is not None:
            self.last_trade_price = to_decimal(last_trade)
        self.last_venue_ts = parse_ts(market_data.get("transactTime")) or self.last_venue_ts
        state = market_data.get("state")
        if isinstance(state, str):
            self.last_state = state
        return self.snapshot(received_ts=received_ts)

    def apply_book_payload(
        self,
        payload: dict[str, Any],
        received_ts: datetime | None = None,
    ) -> BookSnapshot:
        """For REST seed: payload may be the raw book or wrap it under marketData."""
        market_data = payload.get("marketData") if isinstance(payload, dict) else None
        return self.apply_market_data(market_data if market_data is not None else (payload or {}), received_ts)

    def snapshot(self, received_ts: datetime | None = None) -> BookSnapshot:
        return BookSnapshot(
            venue="polymarket_us",
            outcome_name=self.outcome_name,
            market_key=self.market_slug,
            yes_bids=sorted_bids(self.yes_bids),
            yes_asks=sorted_asks(self.yes_asks),
            last_trade_price=self.last_trade_price,
            venue_ts=self.last_venue_ts,
            received_ts=received_ts or datetime.now(timezone.utc),
            state=self.last_state,
        )
