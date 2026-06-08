from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from ..books import BookStore
from ..depth import walk_book
from ..fees import FeeConfig, venue_taker_fee_total
from ..models import Venue
from .models import Order, OrderResult, RestingOrderUpdate

ZERO = Decimal("0")


class OrderClient(Protocol):
    """The minimal interface the executor needs from an order venue.

    Real LiveOrderClient implementations would send signed REST/WS orders to
    Kalshi or Polymarket US. SimulatedOrderClient walks the local book and
    deducts from an internal balance.
    """

    async def submit_ioc(self, order: Order) -> OrderResult: ...
    async def get_balance(self, venue: Venue) -> Decimal: ...
    async def get_total_balance(self) -> Decimal: ...
    async def submit_limit_postonly(self, order: Order) -> OrderResult: ...
    async def poll_resting_orders(self) -> list[RestingOrderUpdate]: ...
    async def cancel_limit(self, order_id: str) -> None: ...


@dataclass
class _RestingOrder:
    """Server-side bookkeeping for a resting limit in the simulator."""
    order_id: str
    venue: Venue
    outcome_name: str
    market_key: str
    side: str          # "buy" | "sell"
    requested_size: Decimal
    limit_price: Decimal
    submit_ts: datetime
    filled_size: Decimal = ZERO
    fees_paid: Decimal = ZERO
    final_state: str = "resting"


@dataclass
class SimulatedOrderClient:
    """Simulates IOC fills against the local BookStore.

    Walks the book starting from the best price toward the IOC limit; whatever
    portion can fill at or below the limit fills, the rest is canceled. Deducts
    cost (or credits proceeds) from a per-venue balance. Useful for paper
    trading and forensic replay without touching real venue APIs.
    """
    store: BookStore
    fee_cfg: FeeConfig = field(default_factory=FeeConfig.default)
    initial_balance: Decimal = Decimal("1000")
    _balance: dict[Venue, Decimal] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Resting limit orders awaiting fill — keyed by order_id. Mutated by
    # submit_limit_postonly, poll_resting_orders, and cancel_limit.
    _resting: dict[str, "_RestingOrder"] = field(default_factory=dict)
    _resting_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Pending updates waiting for the next poll_resting_orders call.
    _pending_updates: list[RestingOrderUpdate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self._balance:
            self._balance = {
                "kalshi": self.initial_balance,
                "polymarket_us": self.initial_balance,
            }

    async def get_balance(self, venue: Venue) -> Decimal:
        async with self._lock:
            return self._balance.get(venue, ZERO)

    async def get_total_balance(self) -> Decimal:
        async with self._lock:
            return sum(self._balance.values(), ZERO)

    async def submit_ioc(self, order: Order) -> OrderResult:
        # Read book state at submit time.
        book = await self.store.get(order.venue, order.outcome_name)
        if book is None:
            return OrderResult(
                order=order, filled_size=ZERO, fill_vwap=ZERO, fees_paid=ZERO,
                accepted=False, reject_reason="no book",
            )

        # Choose side: buys consume asks (≤ limit), sells consume bids (≥ limit).
        if order.side == "buy":
            levels = tuple(lvl for lvl in book.yes_asks if lvl.price <= order.limit_price)
            walked = walk_book(levels, order.size, side="ask")
        else:
            levels = tuple(lvl for lvl in book.yes_bids if lvl.price >= order.limit_price)
            walked = walk_book(levels, order.size, side="bid")

        if walked.filled <= ZERO:
            return OrderResult(
                order=order, filled_size=ZERO, fill_vwap=ZERO, fees_paid=ZERO,
                accepted=True, reject_reason="no fillable depth at limit",
            )

        fees = venue_taker_fee_total(order.venue, walked.vwap, walked.filled, self.fee_cfg)

        async with self._lock:
            if order.side == "buy":
                cost = walked.filled * walked.vwap + fees
                if self._balance.get(order.venue, ZERO) < cost:
                    return OrderResult(
                        order=order, filled_size=ZERO, fill_vwap=ZERO, fees_paid=ZERO,
                        accepted=False, reject_reason=f"insufficient balance ({self._balance.get(order.venue, ZERO)} < {cost})",
                    )
                self._balance[order.venue] = self._balance.get(order.venue, ZERO) - cost
            else:
                proceeds = walked.filled * walked.vwap - fees
                self._balance[order.venue] = self._balance.get(order.venue, ZERO) + proceeds

        # Deplete the consumed depth from the book so subsequent IOCs see realistic state.
        # (Real venues do this automatically when their matching engine fills resting orders.)
        await self._deplete_book(order, walked.filled)

        return OrderResult(
            order=order, filled_size=walked.filled, fill_vwap=walked.vwap,
            fees_paid=fees, accepted=True,
        )

    async def _deplete_book(self, order: Order, consumed_size: Decimal) -> None:
        """Subtract consumed_size from the side of the book the order ate into."""
        from ..models import BookSnapshot as _BS, DepthLevel as _DL
        book = await self.store.get(order.venue, order.outcome_name)
        if book is None:
            return
        if order.side == "buy":
            original = book.yes_asks
            limit_ok = lambda lvl: lvl.price <= order.limit_price
        else:
            original = book.yes_bids
            limit_ok = lambda lvl: lvl.price >= order.limit_price

        remaining = consumed_size
        new_levels: list[_DL] = []
        for lvl in original:
            if remaining <= ZERO or not limit_ok(lvl):
                new_levels.append(lvl)
                continue
            take = lvl.size if lvl.size <= remaining else remaining
            leftover = lvl.size - take
            remaining -= take
            if leftover > ZERO:
                new_levels.append(_DL(price=lvl.price, size=leftover))

        depleted = _BS(
            venue=book.venue,
            outcome_name=book.outcome_name,
            market_key=book.market_key,
            yes_bids=tuple(new_levels) if order.side == "sell" else book.yes_bids,
            yes_asks=tuple(new_levels) if order.side == "buy" else book.yes_asks,
            last_trade_price=book.last_trade_price,
            venue_ts=book.venue_ts,
            received_ts=book.received_ts,
            sequence=book.sequence,
            state=book.state,
        )
        await self.store.set(depleted)

    async def submit_limit_postonly(self, order: Order) -> OrderResult:
        """Post a resting limit. Returns immediately with filled_size=0 and a
        client-side order_id. Fills surface via poll_resting_orders.

        The simulator treats the limit as resting on the book at its limit_price.
        Each call to poll_resting_orders re-walks the relevant book and checks
        whether the opposing top-of-book has crossed it. If so, fill the entire
        remaining size at the *limit price* (we joined the queue at our price,
        so the taker that hits us pays our price).
        """
        order_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        resting = _RestingOrder(
            order_id=order_id,
            venue=order.venue,
            outcome_name=order.outcome_name,
            market_key=order.market_key,
            side=order.side,
            requested_size=order.size,
            limit_price=order.limit_price,
            submit_ts=now,
        )
        async with self._resting_lock:
            self._resting[order_id] = resting
        return OrderResult(
            order=order,
            filled_size=ZERO,
            fill_vwap=ZERO,
            fees_paid=ZERO,
            accepted=True,
            ts=now,
            order_id=order_id,
        )

    async def poll_resting_orders(self) -> list[RestingOrderUpdate]:
        """Re-walk books for each resting limit. Surface any new fills or
        previously-recorded cancels as RestingOrderUpdates. Drain the pending
        list each call."""
        updates: list[RestingOrderUpdate] = []
        async with self._resting_lock:
            # Drain previously-recorded updates (cancels happen synchronously
            # in cancel_limit but the update is queued here).
            updates.extend(self._pending_updates)
            self._pending_updates.clear()

            for order_id, ro in list(self._resting.items()):
                if ro.final_state != "resting":
                    continue
                book = await self.store.get(ro.venue, ro.outcome_name)
                if book is None:
                    continue
                # For a SELL limit, we get filled when the best bid crosses our
                # limit_price (a buyer arrives willing to pay ≥ limit). For a
                # BUY limit, we get filled when best ask <= limit_price.
                if ro.side == "sell":
                    best_bid = book.yes_bids[0].price if book.yes_bids else None
                    crossed = best_bid is not None and best_bid >= ro.limit_price
                else:
                    best_ask = book.yes_asks[0].price if book.yes_asks else None
                    crossed = best_ask is not None and best_ask <= ro.limit_price
                if not crossed:
                    continue

                remaining = ro.requested_size - ro.filled_size
                if remaining <= ZERO:
                    continue
                fill_price = ro.limit_price
                fill_fees = venue_taker_fee_total(
                    ro.venue, fill_price, remaining, self.fee_cfg,
                )
                ro.filled_size += remaining
                ro.fees_paid += fill_fees
                ro.final_state = "filled"

                # Balance bookkeeping for sells (we credit proceeds).
                if ro.side == "sell":
                    proceeds = remaining * fill_price - fill_fees
                    self._balance[ro.venue] = self._balance.get(ro.venue, ZERO) + proceeds
                else:
                    cost = remaining * fill_price + fill_fees
                    self._balance[ro.venue] = self._balance.get(ro.venue, ZERO) - cost

                # Deplete the book on the opposing side, mirroring an IOC.
                synthetic_order = Order(
                    venue=ro.venue, outcome_name=ro.outcome_name,
                    market_key=ro.market_key, side=ro.side,  # type: ignore[arg-type]
                    size=remaining, limit_price=ro.limit_price,
                )
                # Release the lock briefly for the book-store await — no other
                # callers can race because poll_resting_orders is single-task.
                # (BookStore has its own internal locking.)
                await self._deplete_book(synthetic_order, remaining)

                updates.append(RestingOrderUpdate(
                    order_id=order_id,
                    venue=ro.venue,
                    outcome_name=ro.outcome_name,
                    side=ro.side,  # type: ignore[arg-type]
                    limit_price=ro.limit_price,
                    filled_size_delta=remaining,
                    fill_vwap=fill_price,
                    fees_delta=fill_fees,
                    cumulative_filled=ro.filled_size,
                    requested_size=ro.requested_size,
                    final_state=ro.final_state,
                    ts=datetime.now(timezone.utc),
                ))
        return updates

    async def cancel_limit(self, order_id: str) -> None:
        """Best-effort cancel. Idempotent: cancelling an already-filled or
        already-cancelled order is a no-op."""
        async with self._resting_lock:
            ro = self._resting.get(order_id)
            if ro is None or ro.final_state != "resting":
                return
            ro.final_state = "cancelled"
            self._pending_updates.append(RestingOrderUpdate(
                order_id=order_id,
                venue=ro.venue,
                outcome_name=ro.outcome_name,
                side=ro.side,  # type: ignore[arg-type]
                limit_price=ro.limit_price,
                filled_size_delta=ZERO,
                fill_vwap=ZERO,
                fees_delta=ZERO,
                cumulative_filled=ro.filled_size,
                requested_size=ro.requested_size,
                final_state="cancelled",
                ts=datetime.now(timezone.utc),
            ))
