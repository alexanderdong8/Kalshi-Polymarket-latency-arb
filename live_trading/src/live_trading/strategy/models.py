from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

Venue = Literal["kalshi", "polymarket_us"]


@dataclass(frozen=True)
class OutcomeSpec:
    """One outcome of a multi-outcome event, with a stream key on each venue."""
    name: str
    kalshi_ticker: str
    polymarket_slug: str


@dataclass(frozen=True)
class EventSpec:
    name: str
    description: str | None
    outcomes: tuple[OutcomeSpec, ...]

    @property
    def slug(self) -> str:
        safe = "".join(c if c.isalnum() else "-" for c in self.name.lower())
        return "-".join(part for part in safe.split("-") if part) or "event"

    @property
    def kalshi_tickers(self) -> tuple[str, ...]:
        return tuple(o.kalshi_ticker for o in self.outcomes)

    @property
    def polymarket_slugs(self) -> tuple[str, ...]:
        return tuple(o.polymarket_slug for o in self.outcomes)

    def outcome_by_kalshi_ticker(self, ticker: str) -> OutcomeSpec | None:
        return next((o for o in self.outcomes if o.kalshi_ticker == ticker), None)

    def outcome_by_polymarket_slug(self, slug: str) -> OutcomeSpec | None:
        return next((o for o in self.outcomes if o.polymarket_slug == slug), None)


@dataclass(frozen=True)
class DepthLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class BookSnapshot:
    """Latest known state of one outcome's order book on one venue.

    For Kalshi, asks are synthesized from the opposite side (no_bid → yes_ask via 1 - p).
    For Polymarket US, asks are native.
    """
    venue: Venue
    outcome_name: str
    market_key: str
    yes_bids: tuple[DepthLevel, ...]
    yes_asks: tuple[DepthLevel, ...]
    last_trade_price: Decimal | None = None
    venue_ts: datetime | None = None
    received_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sequence: int | None = None
    state: str | None = None

    @property
    def best_yes_bid(self) -> DepthLevel | None:
        return self.yes_bids[0] if self.yes_bids else None

    @property
    def best_yes_ask(self) -> DepthLevel | None:
        return self.yes_asks[0] if self.yes_asks else None

    def age_seconds(self, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        return (current - self.received_ts).total_seconds()


@dataclass(frozen=True)
class Credentials:
    kalshi_key_id: str | None
    kalshi_private_key_pem: str | None
    polymarket_us_key_id: str | None
    polymarket_us_secret_key: str | None

    @property
    def has_kalshi(self) -> bool:
        return bool(self.kalshi_key_id and self.kalshi_private_key_pem)

    @property
    def has_polymarket(self) -> bool:
        return bool(self.polymarket_us_key_id and self.polymarket_us_secret_key)


@dataclass(frozen=True)
class Endpoints:
    kalshi_ws_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    polymarket_ws_url: str = "wss://api.polymarket.us/v1/ws/markets"
    polymarket_gateway_base: str = "https://gateway.polymarket.us"


def _safe_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}
