from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .models import DepthLevel

ZERO = Decimal("0")


@dataclass(frozen=True)
class WalkResult:
    """Result of walking a sorted level stack to fill a target size.

    `vwap` is the volume-weighted average price across `filled` contracts only —
    i.e. the average price you'd actually pay (or receive) for the contracts
    that did fill. If the book was too thin, `filled < target_size` and
    `short_by > 0`; `fully_filled` is False.
    """
    vwap: Decimal
    filled: Decimal
    target: Decimal
    short_by: Decimal
    levels_consumed: int
    fully_filled: bool

    @property
    def empty(self) -> bool:
        return self.filled <= ZERO


def walk_book(
    levels: tuple[DepthLevel, ...],
    target_size: Decimal,
    *,
    side: Literal["ask", "bid"] = "ask",
    size_multiplier: Decimal = Decimal("1"),
) -> WalkResult:
    """Walk a pre-sorted depth stack until target_size contracts are filled.

    `levels` must be sorted in the direction of consumption:
      side="ask" → ascending by price (lowest ask first)
      side="bid" → descending by price (highest bid first)
    BookSnapshot.yes_asks / .yes_bids are already in those orders.

    `target_size` is in CONTRACTS (units of the book's size column), not dollars.
    The caller is responsible for converting any dollar budget into a contract
    target before calling.

    `size_multiplier` ("depth haircut") models the fraction of each displayed
    level's size that's actually reachable. Default 1.0 = take displayed depth
    at face value. 0.7 = treat each level as 70% of its displayed size, which
    accounts for maker cancellations / queue jumping when aggressive flow hits.
    Must satisfy 0 < size_multiplier <= 1.
    """
    del side  # only used to communicate intent; both orderings are already correct in the input
    if size_multiplier <= ZERO or size_multiplier > Decimal("1"):
        raise ValueError(
            f"size_multiplier must be in (0, 1], got {size_multiplier!r}"
        )
    if target_size <= ZERO or not levels:
        return WalkResult(
            vwap=ZERO,
            filled=ZERO,
            target=target_size if target_size > ZERO else ZERO,
            short_by=target_size if target_size > ZERO else ZERO,
            levels_consumed=0,
            fully_filled=False,
        )

    remaining = target_size
    total_cost = ZERO
    levels_used = 0
    for level in levels:
        if remaining <= ZERO:
            break
        if level.size <= ZERO:
            continue
        effective = level.size * size_multiplier
        if effective <= ZERO:
            continue
        take = effective if effective < remaining else remaining
        total_cost += take * level.price
        remaining -= take
        levels_used += 1

    filled = target_size - remaining
    short_by = remaining if remaining > ZERO else ZERO
    if filled <= ZERO:
        return WalkResult(
            vwap=ZERO,
            filled=ZERO,
            target=target_size,
            short_by=target_size,
            levels_consumed=0,
            fully_filled=False,
        )
    return WalkResult(
        vwap=total_cost / filled,
        filled=filled,
        target=target_size,
        short_by=short_by,
        levels_consumed=levels_used,
        fully_filled=short_by == ZERO,
    )


def total_depth(levels: tuple[DepthLevel, ...]) -> Decimal:
    """Sum of size across all displayed levels (max possible fill)."""
    return sum((lvl.size for lvl in levels if lvl.size > ZERO), ZERO)
