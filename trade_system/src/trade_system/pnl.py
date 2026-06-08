"""Live PnL + position tracker.

Snapshots the operator's portfolio every `--pnl-interval-seconds` seconds:

  - For each OpenBasket held by the PositionStore: cost basis, mark-to-market
    (sum of legs' best-bid × remaining size), unrealized PnL.
  - Aggregate cumulative realized PnL across every closed BasketAttempt (the
    executor's unwinds, aborts, and the dead-on-arrival cases) and every
    closed ExitAttempt (path-A fills and reverts).

Surfaces in two places:

  - The Rich TUI grows a "Positions & PnL" panel via `DetectorState.latest_pnl`.
  - A new JSONL log `logs/pnl-<event_slug>-<ts>.jsonl` gets one record per tick
    for forensic replay.

The realized side is fed by hooking into the executor's `on_attempt` callback
and the exit monitor's `on_exit_attempt` callback, so the accumulator is always
in sync with what the journals just recorded.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .books import BookStore
from .execution.positions import PositionStore

ZERO = Decimal("0")


@dataclass(frozen=True)
class _LegPnL:
    """Per-leg breakdown inside a BasketPnL row."""
    outcome: str
    venue: str
    remaining_size: Decimal     # contracts still held on this leg (after any exit fills)
    best_bid: Decimal           # current best bid we'd mark to
    mark_to_market: Decimal     # remaining_size × best_bid (no exit fees in MTM)


@dataclass(frozen=True)
class BasketPnL:
    """Snapshot of one held basket at one point in time."""
    basket_id: str
    entered_ts: datetime
    target_basket_size: Decimal
    cost_basis_dollars: Decimal             # buy cost + entry fees (already paid)
    mark_to_market_dollars: Decimal         # Σ_leg (best_bid × remaining size)
    unrealized_pnl_dollars: Decimal         # mtm − cost_basis
    legs: tuple[_LegPnL, ...]


@dataclass(frozen=True)
class PnLSnapshot:
    """One full portfolio snapshot."""
    ts: datetime
    open_baskets: tuple[BasketPnL, ...]
    open_count: int
    total_cost_basis: Decimal               # sum of held baskets' cost basis
    total_mark_to_market: Decimal           # sum of held baskets' MTM
    total_unrealized_pnl: Decimal           # MTM − cost basis
    realized_pnl_dollars: Decimal           # cumulative across all closed events
    realized_count: int                     # closed-attempt count


class RealizedPnLAccumulator:
    """Accumulates closed-position PnL from executor and exit-monitor callbacks.

    Used as a single source of truth for the realized side. Both attempt
    journals (BasketAttempt + ExitAttempt) include their own fill records, so
    we compute realized = Σ sells − Σ buys − Σ fees on each closing event.
    Idempotent against duplicate notifications via a small dedup set keyed by
    `(kind, basket_id, ts)`.
    """

    def __init__(self) -> None:
        self._total = ZERO
        self._count = 0
        self._seen: set[tuple[str, str, str]] = set()
        self._lock = asyncio.Lock()

    @property
    def total(self) -> Decimal:
        return self._total

    @property
    def count(self) -> int:
        return self._count

    async def snapshot(self) -> tuple[Decimal, int]:
        async with self._lock:
            return self._total, self._count

    async def on_basket_attempt(self, attempt) -> None:
        """A BasketAttempt closed — the executor either fully unwound, the
        unhedged-loss kill switch fired, the operator aborted, or no orders
        ever filled. Any of these → realized = Σ sells − Σ buys − Σ fees over
        all legs' fills. A `complete` attempt does NOT credit realized PnL
        here — that's an open position; its realization happens when the
        position is exited."""
        outcome = getattr(attempt, "outcome", None)
        if outcome in (None, "complete"):
            return
        ts_key = attempt.ts.isoformat() if attempt.ts else ""
        dedup_key = ("basket", "_", ts_key)
        realized = _realized_from_legs(attempt.legs)
        await self.record_close(realized, dedup_key)

    async def record_close(self, dollars: Decimal, dedup_key: tuple) -> None:
        """Single entry point used by the cli wrapper for exit attempts.
        Idempotent via `dedup_key` — re-emissions of the same close are no-ops.
        Increments both the realized total and the closed-event counter."""
        async with self._lock:
            if dedup_key in self._seen:
                return
            self._seen.add(dedup_key)
            self._total += dollars
            self._count += 1


def _realized_from_legs(legs) -> Decimal:
    """Sum of sells − buys − fees across every fill on every leg.
    Used for BasketAttempts that close without a held position."""
    total = ZERO
    for leg in legs:
        for f in leg.fills:
            sign = Decimal("1") if f.side == "sell" else Decimal("-1")
            total += sign * f.size * f.price - f.fees
    return total


class PnLTracker:
    """Ticks every `interval_seconds`. Reads PositionStore + BookStore, computes
    a PnLSnapshot, fires the on_snapshot callback. Cancellation-safe."""

    def __init__(
        self,
        store: BookStore,
        position_store: PositionStore,
        accumulator: RealizedPnLAccumulator,
        interval_seconds: float = 5.0,
        on_snapshot=None,
    ) -> None:
        self.store = store
        self.position_store = position_store
        self.accumulator = accumulator
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.on_snapshot = on_snapshot
        self._last: PnLSnapshot | None = None

    @property
    def last(self) -> PnLSnapshot | None:
        return self._last

    async def compute_snapshot(self) -> PnLSnapshot:
        baskets = await self.position_store.snapshot()
        rows: list[BasketPnL] = []
        total_cost = ZERO
        total_mtm = ZERO
        for basket in baskets:
            cost_basis = (
                basket.cost_basis_per_share_total + basket.entry_fees_per_share_total
            ) * basket.target_basket_size
            leg_rows: list[_LegPnL] = []
            mtm_for_basket = ZERO
            for leg in basket.legs:
                for venue, size in leg.fills_by_venue("buy").items():
                    if size <= ZERO:
                        continue
                    book = await self.store.get(venue, leg.outcome_name)
                    bid = book.yes_bids[0].price if (book and book.yes_bids) else ZERO
                    leg_mtm = size * bid
                    mtm_for_basket += leg_mtm
                    leg_rows.append(_LegPnL(
                        outcome=leg.outcome_name, venue=venue,
                        remaining_size=size, best_bid=bid, mark_to_market=leg_mtm,
                    ))
            unreal = mtm_for_basket - cost_basis
            rows.append(BasketPnL(
                basket_id=basket.basket_id, entered_ts=basket.entered_ts,
                target_basket_size=basket.target_basket_size,
                cost_basis_dollars=cost_basis,
                mark_to_market_dollars=mtm_for_basket,
                unrealized_pnl_dollars=unreal,
                legs=tuple(leg_rows),
            ))
            total_cost += cost_basis
            total_mtm += mtm_for_basket

        realized_total, realized_count = await self.accumulator.snapshot()
        snap = PnLSnapshot(
            ts=datetime.now(timezone.utc),
            open_baskets=tuple(rows),
            open_count=len(rows),
            total_cost_basis=total_cost,
            total_mark_to_market=total_mtm,
            total_unrealized_pnl=total_mtm - total_cost,
            realized_pnl_dollars=realized_total,
            realized_count=realized_count,
        )
        self._last = snap
        return snap

    async def run(self) -> None:
        while True:
            try:
                snap = await self.compute_snapshot()
                if self.on_snapshot is not None:
                    try:
                        await self.on_snapshot(snap)
                    except Exception:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(self.interval_seconds)


def build_pnl_record_payload(snap: PnLSnapshot) -> dict[str, Any]:
    """JSONL payload — one record per tick of the PnLTracker."""
    return {
        "ts": snap.ts.isoformat(),
        "open_count": snap.open_count,
        "total_cost_basis_dollars": str(snap.total_cost_basis),
        "total_mark_to_market_dollars": str(snap.total_mark_to_market),
        "total_unrealized_pnl_dollars": str(snap.total_unrealized_pnl),
        "realized_pnl_dollars": str(snap.realized_pnl_dollars),
        "realized_count": snap.realized_count,
        "net_pnl_dollars": str(snap.realized_pnl_dollars + snap.total_unrealized_pnl),
        "open_baskets": [
            {
                "basket_id": b.basket_id,
                "entered_ts": b.entered_ts.isoformat(),
                "target_basket_size": str(b.target_basket_size),
                "cost_basis_dollars": str(b.cost_basis_dollars),
                "mark_to_market_dollars": str(b.mark_to_market_dollars),
                "unrealized_pnl_dollars": str(b.unrealized_pnl_dollars),
                "legs": [
                    {
                        "outcome": l.outcome, "venue": l.venue,
                        "remaining_size": str(l.remaining_size),
                        "best_bid": str(l.best_bid),
                        "mark_to_market_dollars": str(l.mark_to_market),
                    }
                    for l in b.legs
                ],
            }
            for b in snap.open_baskets
        ],
    }


class PnLJournal:
    """Writes one comprehensive PnLSnapshot to JSONL per tick."""

    def __init__(self, jsonl_writer) -> None:
        self._writer = jsonl_writer

    async def write(self, snap: PnLSnapshot) -> None:
        try:
            await self._writer.write_event(
                "info", build_pnl_record_payload(snap), kind="pnl",
            )
        except Exception:
            pass
