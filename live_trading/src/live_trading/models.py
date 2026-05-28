from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal


Venue = Literal["kalshi", "polymarket_us"]


@dataclass(frozen=True)
class VenueMarket:
    venue: Venue
    market_id: str
    ticker: str | None
    slug: str | None
    title: str
    category: str | None
    market_type: str | None
    start_time: datetime | None
    close_time: datetime | None
    expiration_time: datetime | None
    yes_label: str = "Yes"
    no_label: str = "No"
    yes_symbol: str | None = None
    no_symbol: str | None = None
    description: str | None = None
    rules: str | None = None
    active: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def stream_key(self) -> str:
        return self.ticker or self.slug or self.market_id


@dataclass(frozen=True)
class MatchedMarket:
    match_id: str
    kalshi: VenueMarket
    polymarket_us: VenueMarket
    confidence: Decimal
    relation: str
    warnings: tuple[str, ...] = ()
    reasoning: str | None = None

    @property
    def is_tradeable_candidate(self) -> bool:
        return not self.warnings and self.relation == "identity"


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class BookState:
    venue: Venue
    market_key: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    no_bid: Decimal | None
    no_ask: Decimal | None
    yes_bid_size: Decimal | None = None
    yes_ask_size: Decimal | None = None
    no_bid_size: Decimal | None = None
    no_ask_size: Decimal | None = None
    raw_yes_bids: tuple[PriceLevel, ...] = ()
    raw_yes_asks: tuple[PriceLevel, ...] = ()
    venue_ts: datetime | None = None
    received_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sequence: int | None = None
    state: str | None = None

    def age_seconds(self, now: datetime | None = None) -> Decimal:
        current = now or datetime.now(timezone.utc)
        return Decimal(str((current - self.received_ts).total_seconds()))

    def is_stale(self, stale_after_seconds: Decimal, now: datetime | None = None) -> bool:
        return self.age_seconds(now) > stale_after_seconds


@dataclass(frozen=True)
class ArbOpportunity:
    match_id: str
    direction: str
    yes_venue: Venue
    no_venue: Venue
    yes_ask: Decimal
    no_ask: Decimal
    entry_cost: Decimal
    gross_edge_per_contract: Decimal
    net_edge_per_contract: Decimal
    estimated_fees_per_contract: Decimal
    slippage_buffer_per_pair: Decimal
    depth_limited_contracts: Decimal | None
    kalshi_received_ts: datetime
    polymarket_received_ts: datetime
    detected_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: tuple[str, ...] = ()

