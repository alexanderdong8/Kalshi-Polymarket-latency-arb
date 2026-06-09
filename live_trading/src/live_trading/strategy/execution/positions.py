"""In-memory store of open baskets — positions held after a `complete` entry.

The executor populates this on every `complete` BasketAttempt via the
on_attempt callback in cli.py. The ExitMonitor watches it and triggers
path A (post resting exit limits) when conditions allow.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from .models import OpenBasket, LegState

ZERO = Decimal("0")


def build_open_basket_from_attempt(
    basket_id: str,
    entered_ts,
    target_basket_size: Decimal,
    legs: tuple[LegState, ...],
) -> OpenBasket:
    """Compute per-share cost basis + entry fees and snapshot the leg fills."""
    cost_basis_ps = ZERO
    entry_fees_ps = ZERO
    if target_basket_size > ZERO:
        for leg in legs:
            # Use *gross* buy info — the unwind path doesn't affect a `complete`
            # basket (no sells happened at attempt close).
            cost_basis_ps += leg.total_buy_cost_dollars / target_basket_size
            entry_fees_ps += leg.total_buy_fees / target_basket_size
    return OpenBasket(
        basket_id=basket_id,
        entered_ts=entered_ts,
        target_basket_size=target_basket_size,
        legs=legs,
        cost_basis_per_share_total=cost_basis_ps,
        entry_fees_per_share_total=entry_fees_ps,
    )


class PositionStore:
    """Holds OpenBaskets keyed by basket_id. Thread-safe via asyncio.Lock.

    Used by the ExitMonitor to iterate held positions and by cli.py's
    on_attempt callback to record new completed entries.
    """

    def __init__(self) -> None:
        self._baskets: dict[str, OpenBasket] = {}
        self._lock = asyncio.Lock()

    async def add(self, basket: OpenBasket) -> None:
        async with self._lock:
            self._baskets[basket.basket_id] = basket

    async def remove(self, basket_id: str) -> None:
        async with self._lock:
            self._baskets.pop(basket_id, None)

    async def snapshot(self) -> tuple[OpenBasket, ...]:
        async with self._lock:
            return tuple(self._baskets.values())

    async def size(self) -> int:
        async with self._lock:
            return len(self._baskets)
