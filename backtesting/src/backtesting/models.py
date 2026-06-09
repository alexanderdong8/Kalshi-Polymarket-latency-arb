from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from live_trading.strategy.models import BookSnapshot


@dataclass(frozen=True)
class ReplayUpdate:
    timestamp_received: datetime
    book: BookSnapshot
    fee_rate_bps: Decimal | None = None


@dataclass(frozen=True)
class FillRecord:
    timestamp: datetime
    outcome: str
    venue: str
    side: str
    size: Decimal
    price: Decimal
    fee: Decimal
    fill_model: str


@dataclass(frozen=True)
class SimulationResult:
    delay_ms: int
    fill_model: str
    starting_cash: Decimal
    ending_cash: Decimal
    total_money_gained: Decimal
    entries: int
    completed_baskets: int
    rejected_entries: int
    fills: tuple[FillRecord, ...]
    fee_source: str
