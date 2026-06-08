from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class OutcomeRef:
    outcome_id: str
    label: str
    best_bid: float | None = None
    best_ask: float | None = None


@dataclass(frozen=True)
class MarketRef:
    venue: str
    market_id: str
    title: str
    slug: str | None
    url: str | None
    category: str | None
    resolution_date: str | None
    contract_address: str | None
    yes: OutcomeRef
    no: OutcomeRef
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_polymarket(self) -> bool:
        return self.venue == "polymarket"

    @property
    def is_kalshi(self) -> bool:
        return self.venue == "kalshi"


@dataclass(frozen=True)
class MatchedMarket:
    match_id: str
    polymarket: MarketRef
    kalshi: MarketRef
    relation: str
    confidence: float
    price_difference: float | None
    reasoning: str | None
    resolution_date_warning: str | None = None


@dataclass(frozen=True)
class BBOState:
    timestamp: datetime
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    yes_bid_size: float | None = None
    yes_ask_size: float | None = None
    no_bid_size: float | None = None
    no_ask_size: float | None = None
    yes_bids: tuple[tuple[float, float], ...] = ()
    yes_asks: tuple[tuple[float, float], ...] = ()
    no_bids: tuple[tuple[float, float], ...] = ()
    no_asks: tuple[tuple[float, float], ...] = ()
    polymarket_fee_rate: float | None = None


@dataclass(frozen=True)
class Opportunity:
    match_id: str
    timestamp: str
    direction: str
    yes_venue: str
    no_venue: str
    yes_ask: float
    no_ask: float
    gross_edge_per_contract: float
    net_edge_per_contract: float
    total_fee: float
    slippage_cost_per_contract: float
    trade_size: int
    estimated_partial_fill_exposure: float
    depth_limited_contracts: float | None
