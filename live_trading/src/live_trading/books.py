from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .fees import decimal
from .models import BookState, PriceLevel, Venue

ONE = Decimal("1")
ZERO = Decimal("0")


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000
        return datetime.fromtimestamp(raw, timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _level_pair(raw: Any) -> PriceLevel:
    if isinstance(raw, dict):
        price = raw.get("price") or raw.get("px") or raw.get("p")
        size = raw.get("size") or raw.get("qty") or raw.get("quantity")
        if isinstance(price, dict):
            price = price.get("value")
        if isinstance(size, dict):
            size = size.get("value")
        return PriceLevel(decimal(price), decimal(size, Decimal("0")))
    return PriceLevel(decimal(raw[0]), decimal(raw[1], Decimal("0")))


def _sorted_bids(levels: dict[Decimal, Decimal]) -> tuple[PriceLevel, ...]:
    return tuple(
        PriceLevel(price, size)
        for price, size in sorted(levels.items(), key=lambda item: item[0], reverse=True)
        if size > ZERO
    )


def _sorted_asks(levels: dict[Decimal, Decimal]) -> tuple[PriceLevel, ...]:
    return tuple(
        PriceLevel(price, size)
        for price, size in sorted(levels.items(), key=lambda item: item[0])
        if size > ZERO
    )


def _best(levels: tuple[PriceLevel, ...]) -> PriceLevel | None:
    return levels[0] if levels else None


@dataclass
class KalshiOrderBook:
    market_key: str
    yes_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    no_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    sequence: int | None = None

    def apply_snapshot(self, message: dict[str, Any], received_ts: datetime | None = None) -> BookState:
        msg = message.get("msg", message)
        self.market_key = str(msg.get("market_ticker") or msg.get("ticker") or self.market_key)
        self.sequence = message.get("seq", self.sequence)
        self.yes_bids = {
            level.price: level.size
            for level in map(_level_pair, msg.get("yes_dollars_fp") or msg.get("yes_dollars") or [])
            if level.size > ZERO
        }
        self.no_bids = {
            level.price: level.size
            for level in map(_level_pair, msg.get("no_dollars_fp") or msg.get("no_dollars") or [])
            if level.size > ZERO
        }
        return self.state(received_ts=received_ts, sequence=self.sequence)

    def apply_delta(self, message: dict[str, Any], received_ts: datetime | None = None) -> BookState:
        msg = message.get("msg", message)
        self.market_key = str(msg.get("market_ticker") or msg.get("ticker") or self.market_key)
        self.sequence = message.get("seq", self.sequence)
        side = str(msg.get("side") or "").lower()
        price = decimal(msg.get("price_dollars") or msg.get("price"))
        delta = decimal(msg.get("delta_fp") or msg.get("delta") or "0")
        book = self.yes_bids if side == "yes" else self.no_bids
        new_size = book.get(price, ZERO) + delta
        if new_size <= ZERO:
            book.pop(price, None)
        else:
            book[price] = new_size
        return self.state(
            received_ts=received_ts,
            venue_ts=parse_ts(msg.get("ts_ms") or msg.get("ts")),
            sequence=self.sequence,
        )

    def state(
        self,
        received_ts: datetime | None = None,
        venue_ts: datetime | None = None,
        sequence: int | None = None,
    ) -> BookState:
        yes_bids = _sorted_bids(self.yes_bids)
        no_bids = _sorted_bids(self.no_bids)
        best_yes_bid = _best(yes_bids)
        best_no_bid = _best(no_bids)
        yes_ask = ONE - best_no_bid.price if best_no_bid else None
        no_ask = ONE - best_yes_bid.price if best_yes_bid else None
        yes_asks = (PriceLevel(yes_ask, best_no_bid.size),) if yes_ask is not None and best_no_bid else ()
        return BookState(
            venue="kalshi",
            market_key=self.market_key,
            yes_bid=best_yes_bid.price if best_yes_bid else None,
            yes_ask=yes_ask,
            no_bid=best_no_bid.price if best_no_bid else None,
            no_ask=no_ask,
            yes_bid_size=best_yes_bid.size if best_yes_bid else None,
            yes_ask_size=best_no_bid.size if best_no_bid else None,
            no_bid_size=best_no_bid.size if best_no_bid else None,
            no_ask_size=best_yes_bid.size if best_yes_bid else None,
            raw_yes_bids=yes_bids,
            raw_yes_asks=yes_asks,
            venue_ts=venue_ts,
            received_ts=received_ts or datetime.now(timezone.utc),
            sequence=sequence,
        )


def polymarket_us_book_state(
    market_key: str,
    market_data: dict[str, Any],
    received_ts: datetime | None = None,
) -> BookState:
    bids = tuple(_level_pair(item) for item in market_data.get("bids") or [])
    asks = tuple(_level_pair(item) for item in market_data.get("offers") or market_data.get("asks") or [])
    yes_bids = _sorted_bids({level.price: level.size for level in bids if level.size > ZERO})
    yes_asks = _sorted_asks({level.price: level.size for level in asks if level.size > ZERO})
    best_yes_bid = _best(yes_bids)
    best_yes_ask = _best(yes_asks)
    no_bid = ONE - best_yes_ask.price if best_yes_ask else None
    no_ask = ONE - best_yes_bid.price if best_yes_bid else None
    return BookState(
        venue="polymarket_us",
        market_key=str(market_data.get("marketSlug") or market_data.get("market_slug") or market_key),
        yes_bid=best_yes_bid.price if best_yes_bid else None,
        yes_ask=best_yes_ask.price if best_yes_ask else None,
        no_bid=no_bid,
        no_ask=no_ask,
        yes_bid_size=best_yes_bid.size if best_yes_bid else None,
        yes_ask_size=best_yes_ask.size if best_yes_ask else None,
        no_bid_size=best_yes_ask.size if best_yes_ask else None,
        no_ask_size=best_yes_bid.size if best_yes_bid else None,
        raw_yes_bids=yes_bids,
        raw_yes_asks=yes_asks,
        venue_ts=parse_ts(market_data.get("transactTime")),
        received_ts=received_ts or datetime.now(timezone.utc),
        state=market_data.get("state"),
    )


@dataclass
class BookStore:
    stale_after_seconds: Decimal
    _books: dict[tuple[Venue, str], BookState] = field(default_factory=dict)

    def set(self, state: BookState) -> None:
        self._books[(state.venue, state.market_key)] = state

    def get(self, venue: Venue, market_key: str) -> BookState | None:
        return self._books.get((venue, market_key))

    def snapshot(self) -> dict[tuple[Venue, str], BookState]:
        return dict(self._books)

