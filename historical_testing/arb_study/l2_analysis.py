from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable

from .research_config import PAIRED_EXIT_MINIMUM_IMPROVEMENT


Level = tuple[float, float]


@dataclass(frozen=True)
class BookSweep:
    requested_contracts: float
    filled_contracts: float
    vwap: float | None
    top_price: float | None
    total_value: float
    book_slippage_per_contract: float | None

    @property
    def fully_filled(self) -> bool:
        return self.filled_contracts + 1e-9 >= self.requested_contracts


@dataclass(frozen=True)
class LockedPairMetrics:
    size_contracts: float
    yes_entry: BookSweep
    no_entry: BookSweep
    total_entry_cost_per_contract: float | None
    gross_edge_per_contract: float | None
    total_fee: float | None
    net_edge_per_contract: float | None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PairedExit:
    qualifies: bool
    timestamp: str | None
    net_exit_profit_per_contract: float | None
    locked_hold_profit_per_contract: float
    improvement_per_contract: float | None
    seconds_to_exit: float | None


def sweep_book(levels: Iterable[Level], contracts: float, *, is_bid: bool = False) -> BookSweep:
    wanted = float(contracts)
    live = [(float(price), float(size)) for price, size in levels if float(size) > 0]
    ordered = sorted(live, key=lambda item: item[0], reverse=is_bid)
    remaining = wanted
    value = 0.0
    filled = 0.0
    for price, size in ordered:
        take = min(remaining, size)
        value += take * price
        filled += take
        remaining -= take
        if remaining <= 1e-9:
            break
    vwap = value / filled if filled else None
    top = ordered[0][0] if ordered else None
    slippage = None if vwap is None or top is None else ((top - vwap) if is_bid else (vwap - top))
    return BookSweep(wanted, filled, vwap, top, value, slippage)


def locked_pair_metrics(
    yes_asks: Iterable[Level],
    no_asks: Iterable[Level],
    size_contracts: float,
    *,
    total_fee: float = 0.0,
) -> LockedPairMetrics:
    yes_entry = sweep_book(yes_asks, size_contracts)
    no_entry = sweep_book(no_asks, size_contracts)
    if not yes_entry.fully_filled or not no_entry.fully_filled:
        return LockedPairMetrics(size_contracts, yes_entry, no_entry, None, None, None, None)
    total_cost = float(yes_entry.vwap) + float(no_entry.vwap)
    gross = 1.0 - total_cost
    return LockedPairMetrics(
        size_contracts,
        yes_entry,
        no_entry,
        total_cost,
        gross,
        total_fee,
        gross - (total_fee / size_contracts),
    )


def find_safe_paired_exit(
    *,
    entry_time: datetime,
    locked_hold_profit_per_contract: float,
    size_contracts: float,
    later_books: Iterable[tuple[datetime, Iterable[Level], Iterable[Level], float]],
    minimum_improvement: float = PAIRED_EXIT_MINIMUM_IMPROVEMENT,
) -> PairedExit:
    """Sell both locked legs only when the early unwind beats the guaranteed fallback."""
    for timestamp, yes_bids, no_bids, total_exit_fee in later_books:
        yes_exit = sweep_book(yes_bids, size_contracts, is_bid=True)
        no_exit = sweep_book(no_bids, size_contracts, is_bid=True)
        if not yes_exit.fully_filled or not no_exit.fully_filled:
            continue
        proceeds = float(yes_exit.vwap) + float(no_exit.vwap)
        exit_profit = proceeds - 1.0 - (total_exit_fee / size_contracts) + locked_hold_profit_per_contract
        improvement = exit_profit - locked_hold_profit_per_contract
        if improvement + 1e-12 >= minimum_improvement:
            return PairedExit(
                True,
                timestamp.isoformat(),
                exit_profit,
                locked_hold_profit_per_contract,
                improvement,
                (timestamp - entry_time).total_seconds(),
            )
    return PairedExit(False, None, None, locked_hold_profit_per_contract, None, None)

