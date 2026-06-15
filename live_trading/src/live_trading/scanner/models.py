from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from ..models import MatchedMarket, VenueMarket


@dataclass(frozen=True)
class EventGroup:
    venue: str
    key: str
    title: str
    category: str | None
    market_type: str | None
    start_time: datetime | None
    close_time: datetime | None
    markets: tuple[VenueMarket, ...]


@dataclass(frozen=True)
class EventPair:
    kalshi: EventGroup
    polymarket: EventGroup
    confidence: Decimal
    outcome_matches: tuple[MatchedMarket, ...]
    warnings: tuple[str, ...] = ()
    reasoning: str = ""


@dataclass(frozen=True)
class HistoricalEvidence:
    scenario: str
    suitability: float = 50.0
    annual_percentile: float = 50.0
    pmxt_percentile: float = 50.0
    multiplier: float = 1.0
    quality: str = "none"
    sample_size: int = 0
    label: str = "Neutral prior: no applicable historical evidence"
    subscenario: str | None = None


@dataclass(frozen=True)
class SizePoint:
    requested_size: Decimal
    achievable_size: Decimal
    net_edge_per_share: Decimal
    executable_profit: Decimal
    max_slippage_per_share: Decimal
    fresh: bool
    complete_books: bool
    price_bounds_ok: bool
    chosen_venues: tuple[str | None, ...] = field(default_factory=tuple)
