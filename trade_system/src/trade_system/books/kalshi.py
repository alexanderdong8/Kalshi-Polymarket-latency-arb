from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..models import BookSnapshot, DepthLevel
from ._common import ONE, ZERO, level_from_raw, parse_ts, sorted_asks, sorted_bids, to_decimal


class SequenceGap(RuntimeError):
    """Raised when an orderbook delta arrives out of order, signalling a need to resubscribe."""


@dataclass
class KalshiOrderBook:
    """Local order book reconstructed from Kalshi orderbook_snapshot + orderbook_delta messages.

    Kalshi quotes are in cents/dollars on each side (yes_bids vs no_bids); the YES ask side
    is synthesized from the best NO bid via the 1 - p complement (yes_ask = 1 - best_no_bid).
    """
    market_ticker: str
    outcome_name: str
    yes_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    no_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    sequence: int | None = None
    last_trade_price: Decimal | None = None

    def apply_snapshot(self, message: dict[str, Any], received_ts: datetime | None = None) -> BookSnapshot:
        msg = message.get("msg") or {}
        self.sequence = message.get("seq", self.sequence)
        self.yes_bids = {
            lvl.price: lvl.size
            for lvl in (level_from_raw(item) for item in msg.get("yes") or msg.get("yes_dollars_fp") or [])
            if lvl.size > ZERO
        }
        self.no_bids = {
            lvl.price: lvl.size
            for lvl in (level_from_raw(item) for item in msg.get("no") or msg.get("no_dollars_fp") or [])
            if lvl.size > ZERO
        }
        return self.snapshot(received_ts=received_ts, venue_ts=parse_ts(msg.get("ts")))

    def apply_delta(self, message: dict[str, Any], received_ts: datetime | None = None) -> BookSnapshot:
        msg = message.get("msg") or {}
        incoming_seq = message.get("seq")
        if incoming_seq is not None and self.sequence is not None and incoming_seq <= self.sequence:
            raise SequenceGap(
                f"stale/duplicate seq for {self.market_ticker}: got {incoming_seq}, have {self.sequence}"
            )
        if incoming_seq is not None and self.sequence is not None and incoming_seq != self.sequence + 1:
            raise SequenceGap(
                f"gap for {self.market_ticker}: expected {self.sequence + 1}, got {incoming_seq}"
            )
        self.sequence = incoming_seq if incoming_seq is not None else self.sequence
        side = str(msg.get("side") or "").lower()
        price = to_decimal(msg.get("price"), None)
        delta = to_decimal(msg.get("delta"))
        book = self.yes_bids if side == "yes" else self.no_bids
        new_size = book.get(price, ZERO) + delta
        if new_size <= ZERO:
            book.pop(price, None)
        else:
            book[price] = new_size
        return self.snapshot(received_ts=received_ts, venue_ts=parse_ts(msg.get("ts")))

    def apply_trade(self, message: dict[str, Any]) -> Decimal | None:
        msg = message.get("msg") or {}
        # Kalshi `trade` channel carries `yes_price` (in cents). Convert to dollars.
        raw = msg.get("yes_price") or msg.get("price")
        if raw is None:
            return self.last_trade_price
        price = to_decimal(raw)
        if price > ONE:
            price = price / Decimal("100")
        self.last_trade_price = price
        return price

    def snapshot(
        self,
        received_ts: datetime | None = None,
        venue_ts: datetime | None = None,
    ) -> BookSnapshot:
        yes_bids = self._yes_bids_normalized()
        yes_asks = self._yes_asks_from_no_bids()
        return BookSnapshot(
            venue="kalshi",
            outcome_name=self.outcome_name,
            market_key=self.market_ticker,
            yes_bids=yes_bids,
            yes_asks=yes_asks,
            last_trade_price=self.last_trade_price,
            venue_ts=venue_ts,
            received_ts=received_ts or datetime.now(timezone.utc),
            sequence=self.sequence,
        )

    def reset(self) -> None:
        self.yes_bids.clear()
        self.no_bids.clear()
        self.sequence = None

    # Kalshi stores prices in cents (1..99). Normalize to dollars (0.01..0.99) so they line
    # up with Polymarket prices in [0, 1].
    def _yes_bids_normalized(self) -> tuple[DepthLevel, ...]:
        return tuple(
            DepthLevel(self._normalize_price(level.price), level.size)
            for level in sorted_bids(self.yes_bids)
        )

    def _yes_asks_from_no_bids(self) -> tuple[DepthLevel, ...]:
        # NO bid at p (cents) → YES ask at 1 - p/100 (dollars).
        return tuple(
            DepthLevel(ONE - self._normalize_price(level.price), level.size)
            for level in sorted_bids(self.no_bids)
        )

    @staticmethod
    def _normalize_price(price: Decimal) -> Decimal:
        return price / Decimal("100") if price > ONE else price
