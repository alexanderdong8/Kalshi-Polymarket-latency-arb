"""Exit layer: monitor open baskets and either post resting limit orders to
sell back when conditions are right (path A), or let positions ride to
settlement (path B, the no-op default).

The four filters that gate path A, in order:
  A. Each leg's best bid in [min_leg_bid, max_leg_bid].
  B. Sum of per-share best bids across legs ≥ $1 − coupling_tolerance.
  C. Each leg's best bid has been stable (|Δ| ≤ threshold) for the last K ticks.
  D. cost_basis + entry_fees + projected_exit_fees + margin < projected_proceeds.

All filters must pass on the same tick to post limits. The posted order is always
a pure maker: a sell limit one tick inside the spread (best_bid + tick), strictly
below best_ask. We never cross on the normal path.

Sizing — uniform balanced sub-baskets (mirror of the entry share cap)
---------------------------------------------------------------------
We don't dump the whole position into a thin book. Each cycle sells at most
`depth_fraction × min over legs of (bid depth within bid_depth_ticks of the touch)`
contracts, sold in EQUAL size across every leg. Selling equal amounts keeps the
held remainder a complete (risk-free) basket, so we walk the position down while
staying hedged the whole way.

Re-pegging — follow the touch so the order fills before price drifts
--------------------------------------------------------------------
A resting maker sell can get stranded above the touch if the bid drifts down.
Each tick, if the bid dropped, we cancel and repost at the new best_bid + tick —
but only while the basket still clears the required margin at the new price. This
keeps the order at the front of the book without ever chasing into a loss.

Safety — balanced, not flat (the dangerous case is IMBALANCE)
-------------------------------------------------------------
Because `remaining_to_sell[leg]` is the net held position, "balanced/hedged" ⟺
all legs' remaining are equal. Holding a smaller *balanced* basket is still
risk-free. The dangerous state is selling legs in UNEQUAL amounts (from uneven
fills) → directional exposure. So:

  1. On imbalance, start a short clock (partial_exit_deadline_seconds).
  2. When it expires → RE-BALANCE: cross-sell only the excess of over-held legs
     down to the least-held level (taker; the one place we cross).
  3. If an over-held leg has no bid (can't sell down) → REVERT: buy the
     under-held legs back up to match, then hold to settlement (path B).

This is the exit-side analog of the entry-side unhedged-loss kill switch.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from ..books import BookStore
from ..fees import FeeConfig, venue_taker_fee_total
from ..models import Venue
from .client import OrderClient
from .executor import ExitConfig
from .models import (
    ExitAttempt,
    ExitLimitOrder,
    OpenBasket,
    Order,
)
from .positions import PositionStore

ZERO = Decimal("0")


# Reason codes used in ExitAttempt.blocked_by. Kept as constants so journal
# consumers can pattern-match on a stable vocabulary.
BLOCKED_NO_BOOK = "no_book"
BLOCKED_LEG_BID_RANGE = "leg_bid_out_of_range"
BLOCKED_COUPLING = "coupling_below_tolerance"
BLOCKED_UNSTABLE = "leg_bids_unstable"
BLOCKED_UNPROFITABLE = "unprofitable"
BLOCKED_CANT_POST_INSIDE = "cannot_post_inside_spread"
BLOCKED_THIN_DEPTH = "bid_depth_too_thin"


def _floor_contracts(x: Decimal) -> Decimal:
    """Round down to whole contracts; venues don't accept fractional sizes."""
    return x.to_integral_value(rounding="ROUND_FLOOR")


@dataclass
class LegBidTracker:
    """Per-leg rolling history of best YES bid. Used by Filter C (stability).

    Mirrors MomentumTracker from the detector but operates on best-bid level.
    A leg is "stable" iff every consecutive-pair |Δbest_bid| over the last
    `window` ticks is ≤ threshold. Soft check — small drift OK, big jumps
    reset the streak.
    """
    venue: Venue
    outcome_name: str
    last_bids: deque[Decimal] = field(default_factory=lambda: deque(maxlen=8))

    def configure_window(self, window_ticks: int) -> None:
        # +1 because we need (window+1) samples to measure `window` consecutive deltas.
        maxlen = window_ticks + 1
        if self.last_bids.maxlen != maxlen:
            self.last_bids = deque(self.last_bids, maxlen=maxlen)

    def push(self, best_bid: Decimal) -> None:
        self.last_bids.append(best_bid)

    def is_stable(self, threshold: Decimal, window: int) -> bool:
        if len(self.last_bids) < window + 1:
            return False
        recent = list(self.last_bids)[-(window + 1):]
        return all(abs(recent[i + 1] - recent[i]) <= threshold for i in range(window))


def _venue_tick_fallback(cfg: ExitConfig, venue: Venue) -> Decimal:
    """Per-venue CLI default. Used when the book is too shallow to infer
    a tick. See `_observed_tick`."""
    if venue == "kalshi":
        return cfg.kalshi_tick_size
    return cfg.polymarket_us_tick_size


def _observed_tick(book, fallback: Decimal) -> Decimal:
    """Smallest nonzero gap between adjacent same-side levels in the live book.

    The venue's *current* tick = the smallest price gap actually quoted. This
    follows the venue automatically (no REST round-trip, no schema changes) and
    handles markets where the tick changes (e.g. half-cent on certain Kalshi
    series). Falls back to the configured default only when the book is shallow
    enough that no gap can be observed."""
    gaps: list[Decimal] = []
    for side in (book.yes_bids, book.yes_asks):
        for i in range(len(side) - 1):
            g = abs(side[i].price - side[i + 1].price)
            if g > ZERO:
                gaps.append(g)
    return min(gaps) if gaps else fallback


@dataclass
class _BasketState:
    """In-memory tracking attached to one OpenBasket while it's being monitored.

    Source of truth for how much of each leg is left to sell. `remaining_to_sell`
    and `sold` are keyed by (venue, outcome_name) because a leg may be held on
    both venues (entry rerouting), and each portion is sold on the venue it sits
    on. They're updated whenever a fill is observed — from a resting-limit poll
    OR from a crossing IOC.
    """
    remaining_to_sell: dict[tuple[Venue, str], Decimal] = field(default_factory=dict)
    sold: dict[tuple[Venue, str], Decimal] = field(default_factory=dict)
    market_keys: dict[tuple[Venue, str], str] = field(default_factory=dict)
    posted_limits: dict[str, ExitLimitOrder] = field(default_factory=dict)  # order_id → ExitLimitOrder
    posted_at_ts: datetime | None = None
    # When the basket first became partially unhedged (some sold, some remaining).
    partial_since_ts: datetime | None = None
    # Realized accounting accumulators.
    realized_proceeds: Decimal = ZERO       # sum(size × price) over sells
    realized_exit_fees: Decimal = ZERO      # sum of sell fees
    realized_buyback_cost: Decimal = ZERO   # cost (incl. fees) of any revert buy-backs
    # Once we've reverted (or otherwise given up on path A), hold to settlement.
    hold_to_settlement: bool = False

    def remaining_total(self) -> Decimal:
        return sum(self.remaining_to_sell.values(), ZERO)

    def sold_total(self) -> Decimal:
        return sum(self.sold.values(), ZERO)

    def balanced_level(self) -> Decimal:
        """The least-held leg — the level all legs share when balanced."""
        return min(self.remaining_to_sell.values(), default=ZERO)

    def max_remaining(self) -> Decimal:
        return max(self.remaining_to_sell.values(), default=ZERO)

    def is_imbalanced(self) -> bool:
        """True when legs are held in unequal amounts → directional exposure."""
        return (self.max_remaining() - self.balanced_level()) > ZERO

    def has_resting(self) -> bool:
        return any(e.final_state == "resting" for e in self.posted_limits.values())


class ExitMonitor:
    """Tick at `cfg.monitor_hz` Hz. On each tick:
        1. Poll resting orders (update fills, cancel timed-out).
        2. For each open basket without posted limits, evaluate filters; if
           all pass, post limits.
        3. When all of a basket's exit limits filled → write a fill ExitAttempt
           and remove the basket from PositionStore.
    """

    def __init__(
        self,
        store: BookStore,
        order_client: OrderClient,
        position_store: PositionStore,
        fee_cfg: FeeConfig,
        cfg: ExitConfig,
        on_exit_attempt=None,
    ) -> None:
        self.store = store
        self.client = order_client
        self.position_store = position_store
        self.fee_cfg = fee_cfg
        self.cfg = cfg
        self.on_exit_attempt = on_exit_attempt
        self._trackers: dict[tuple[Venue, str], LegBidTracker] = {}
        self._basket_state: dict[str, _BasketState] = {}

    def _tracker(self, venue: Venue, outcome_name: str) -> LegBidTracker:
        key = (venue, outcome_name)
        t = self._trackers.get(key)
        if t is None:
            t = LegBidTracker(venue=venue, outcome_name=outcome_name)
            t.configure_window(self.cfg.bid_stability_window_ticks)
            self._trackers[key] = t
        else:
            # Allow window reconfiguration mid-run if cfg is mutated; cheap.
            t.configure_window(self.cfg.bid_stability_window_ticks)
        return t

    def _tick_for(self, book) -> Decimal:
        """Tick size for this book: observed from its own grid, falling back to
        the venue-default CLI flag only if the book is too shallow."""
        return _observed_tick(book, _venue_tick_fallback(self.cfg, book.venue))

    async def run(self) -> None:
        """Main loop. Runs until cancelled."""
        interval = 1.0 / max(self.cfg.monitor_hz, 0.5)
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Don't let a single bad tick kill the monitor.
                pass
            await asyncio.sleep(interval)

    async def _tick(self) -> None:
        # 1. Poll for fills / cancellations on any resting limits, applying each
        #    to its owning basket's remaining-to-sell accounting.
        updates = await self.client.poll_resting_orders()
        for u in updates:
            await self._apply_update(u)

        # 2. Drive each open basket through its lifecycle.
        baskets = await self.position_store.snapshot()
        for basket in baskets:
            await self._handle_basket(basket)

    def _init_state(self, basket: OpenBasket) -> _BasketState:
        """Create per-basket tracking, seeding remaining_to_sell from holdings."""
        state = _BasketState()
        for leg in basket.legs:
            for venue, size in leg.fills_by_venue("buy").items():
                if size <= ZERO:
                    continue
                key = (venue, leg.outcome_name)
                state.remaining_to_sell[key] = state.remaining_to_sell.get(key, ZERO) + size
                state.sold[key] = ZERO
        self._basket_state[basket.basket_id] = state
        return state

    async def _push_trackers(self, state: _BasketState) -> None:
        """Feed the stability trackers every tick (even while limits are resting)
        so a later (re)post has continuous best-bid history to test."""
        for (venue, outcome) in list(state.remaining_to_sell.keys()):
            book = await self.store.get(venue, outcome)
            if book is not None and book.yes_bids:
                self._tracker(venue, outcome).push(book.yes_bids[0].price)

    async def _handle_basket(self, basket: OpenBasket) -> None:
        state = self._basket_state.get(basket.basket_id)
        if state is None:
            state = self._init_state(basket)

        await self._push_trackers(state)

        # Terminal: we reverted (or gave up) → hold to settlement, do nothing.
        if state.hold_to_settlement:
            return

        # Everything sold → finalize and remove.
        if state.remaining_total() <= ZERO:
            await self._finalize_filled(basket, state)
            return

        now = datetime.now(timezone.utc)

        # Dangerous state = IMBALANCE (legs held in unequal amounts). Holding a
        # balanced remainder is risk-free, so it's fine to keep some.
        if state.is_imbalanced():
            if state.partial_since_ts is None:
                state.partial_since_ts = now
            # Give resting limits a chance to even things out until the short clock
            # expires; just enforce the stale-limit timeout meanwhile.
            if state.has_resting() and (
                (now - state.partial_since_ts).total_seconds() < self.cfg.partial_exit_deadline_seconds
            ):
                await self._enforce_limit_timeout(state)
                return
            await self._rebalance(basket, state)
            return

        # Balanced from here on.
        state.partial_since_ts = None

        if state.has_resting():
            await self._manage_resting(basket, state)
            return

        # Balanced, nothing resting, still holding → try to sell the next sub-basket.
        await self._evaluate_and_post(basket, state)

    async def _enforce_limit_timeout(self, state: _BasketState) -> None:
        """Cancel any resting limit older than limit_timeout_seconds."""
        now = datetime.now(timezone.utc)
        for order_id, elo in list(state.posted_limits.items()):
            if elo.final_state != "resting":
                continue
            if (now - elo.submit_ts).total_seconds() >= self.cfg.limit_timeout_seconds:
                await self.client.cancel_limit(order_id)

    async def _manage_resting(self, basket: OpenBasket, state: _BasketState) -> None:
        """While balanced with limits resting: enforce the stale-limit timeout and,
        if enabled, re-peg down to follow the touch when the bid has drifted below
        our resting price (bounded by the margin floor)."""
        await self._enforce_limit_timeout(state)
        if not self.cfg.repeg_enabled:
            return

        # Has the touch dropped below any of our resting prices? (bid drifted down)
        bid_dropped = False
        for elo in state.posted_limits.values():
            if elo.final_state != "resting":
                continue
            book = await self.store.get(elo.venue, elo.outcome_name)
            if book is None or not book.yes_bids:
                continue
            desired = book.yes_bids[0].price + self._tick_for(book)
            if desired < elo.limit_price:
                bid_dropped = True
                break
        if not bid_dropped:
            return

        # Only chase down if reposting at the new touch still clears margin and
        # stays a maker (strictly inside the spread). Otherwise leave the existing
        # (higher-priced, still-profitable) order resting rather than cancel it.
        if not await self._repeg_clears_margin(basket, state):
            return

        # Cancel everything, drain fills, then repost fresh at the new touch.
        for order_id, elo in list(state.posted_limits.items()):
            if elo.final_state == "resting":
                await self.client.cancel_limit(order_id)
        for u in await self.client.poll_resting_orders():
            await self._apply_update(u)
        state.posted_limits = {}
        await self._evaluate_and_post(basket, state, kind="reposted")

    async def _repeg_clears_margin(self, basket: OpenBasket, state: _BasketState) -> bool:
        """Would reposting all balanced legs at the current best_bid+tick still
        clear the required margin (and stay a maker)?"""
        q = state.balanced_level()
        if q <= ZERO:
            return False
        proceeds_ps = ZERO
        fees_total = ZERO
        for (venue, outcome), remaining in state.remaining_to_sell.items():
            if remaining <= ZERO:
                continue
            book = await self.store.get(venue, outcome)
            if book is None or not book.yes_bids or not book.yes_asks:
                return False
            desired = book.yes_bids[0].price + self._tick_for(book)
            if desired >= book.yes_asks[0].price:   # would cross → not a maker
                return False
            proceeds_ps += desired
            fees_total += venue_taker_fee_total(venue, desired, q, self.fee_cfg)
        fees_ps = fees_total / q
        return (
            basket.cost_basis_per_share_total + basket.entry_fees_per_share_total
            + fees_ps + self.cfg.required_margin_per_share < proceeds_ps
        )

    def _bid_depth_within_ticks(self, book, tick: Decimal) -> Decimal:
        """Total bid size at prices ≥ best_bid − bid_depth_ticks × tick.
        Tick is supplied by the caller (observed from the same book)."""
        if not book.yes_bids:
            return ZERO
        floor_price = book.yes_bids[0].price - self.cfg.bid_depth_ticks * tick
        return sum((lvl.size for lvl in book.yes_bids if lvl.price >= floor_price), ZERO)

    async def _evaluate_and_post(
        self, basket: OpenBasket, state: _BasketState, kind: str = "posted",
    ) -> None:
        # Gather per-leg current book for the balanced legs we still hold.
        # per_leg tuple: (outcome, venue, best_bid, best_ask, tick, bid_depth, market_key)
        per_leg: list[tuple[str, Venue, Decimal, Decimal, Decimal, Decimal, str]] = []
        any_missing = False
        for (venue, outcome), remaining in state.remaining_to_sell.items():
            if remaining <= ZERO:
                continue
            book = await self.store.get(venue, outcome)
            if book is None or not book.yes_bids:
                any_missing = True
                continue
            best_bid = book.yes_bids[0].price
            tick = self._tick_for(book)  # observed-from-book, fallback per-venue
            best_ask = book.yes_asks[0].price if book.yes_asks else best_bid + Decimal("1")
            bid_depth = self._bid_depth_within_ticks(book, tick)
            state.market_keys[(venue, outcome)] = book.market_key
            per_leg.append((outcome, venue, best_bid, best_ask, tick, bid_depth, book.market_key))
        if any_missing or not per_leg:
            await self._record_blocked(basket, BLOCKED_NO_BOOK)
            return

        # ----- Filter A: leg price range (raw best bid; mirrors entry-side) -----
        if any(b < self.cfg.min_leg_bid or b > self.cfg.max_leg_bid for _, _, b, _, _, _, _ in per_leg):
            await self._record_blocked(basket, BLOCKED_LEG_BID_RANGE)
            return

        # ----- Filter B: coupling — Σ over legs of the LIMIT price we'd post at
        # (best_bid + observed tick), not the raw bid. This is the price the
        # basket would actually realize at, so it's the right thing to test
        # against the $1 settlement floor.
        per_share_limit_sum = sum((b + t for _, _, b, _, t, _, _ in per_leg), ZERO)
        if per_share_limit_sum < (Decimal("1") - self.cfg.coupling_tolerance):
            await self._record_blocked(basket, BLOCKED_COUPLING, coupling_sum=per_share_limit_sum)
            return

        # ----- Filter C: stability -----
        all_stable = all(
            self._tracker(v, o).is_stable(
                self.cfg.bid_stability_threshold, self.cfg.bid_stability_window_ticks,
            )
            for o, v, _, _, _, _, _ in per_leg
        )
        if not all_stable:
            await self._record_blocked(basket, BLOCKED_UNSTABLE, coupling_sum=per_share_limit_sum)
            return

        # ----- Maker pricing: one observed tick inside the spread, strictly below best_ask. -----
        leg_plans: list[tuple[str, Venue, Decimal, Decimal, str]] = []  # (outcome, venue, limit, bid_depth, mk)
        for outcome, venue, best_bid, best_ask, tick, bid_depth, market_key in per_leg:
            limit_price = best_bid + tick
            if limit_price >= best_ask:
                await self._record_blocked(
                    basket, BLOCKED_CANT_POST_INSIDE, coupling_sum=per_share_limit_sum,
                )
                return
            leg_plans.append((outcome, venue, limit_price, bid_depth, market_key))

        # ----- Sell-size cap (uniform balanced sub-basket) -----
        # Q = min(balanced holding, fraction × min over legs of bid depth within N ticks).
        min_bid_depth = min((d for _, _, _, d, _ in leg_plans), default=ZERO)
        depth_cap = _floor_contracts(self.cfg.depth_fraction * min_bid_depth)
        q = min(state.balanced_level(), depth_cap)
        if q < Decimal("1"):
            await self._record_blocked(basket, BLOCKED_THIN_DEPTH, coupling_sum=per_share_limit_sum)
            return

        # ----- Filter D: profitability at the maker price, per basket share -----
        # proceeds per basket share = Σ limit_i ; fees per basket share = Σ fee(limit_i, q) / q.
        proceeds_ps = sum((p for _, _, p, _, _ in leg_plans), ZERO)
        exit_fees_total = sum(
            (venue_taker_fee_total(v, p, q, self.fee_cfg) for _, v, p, _, _ in leg_plans), ZERO,
        )
        exit_fees_ps = exit_fees_total / q
        net_ps = (
            proceeds_ps - basket.cost_basis_per_share_total
            - basket.entry_fees_per_share_total - exit_fees_ps
        )
        required = self.cfg.required_margin_per_share
        if not (
            basket.cost_basis_per_share_total + basket.entry_fees_per_share_total
            + exit_fees_ps + required < proceeds_ps
        ):
            await self._record_blocked(
                basket, BLOCKED_UNPROFITABLE, coupling_sum=per_share_limit_sum,
                projected_proceeds_ps=proceeds_ps, projected_exit_fees_ps=exit_fees_ps,
                projected_net_ps=net_ps,
            )
            return

        # ----- All filters passed. Post the uniform sub-basket as maker limits. -----
        now = datetime.now(timezone.utc)
        orders = [
            Order(venue=venue, outcome_name=outcome, market_key=market_key,
                  side="sell", size=q, limit_price=limit_price)
            for outcome, venue, limit_price, _, market_key in leg_plans
        ]
        results = await asyncio.gather(*(self.client.submit_limit_postonly(o) for o in orders))
        posted: list[ExitLimitOrder] = []
        for order, result in zip(orders, results):
            if not result.accepted or result.order_id is None:
                continue
            elo = ExitLimitOrder(
                venue=order.venue, outcome_name=order.outcome_name,
                market_key=order.market_key, size=order.size,
                limit_price=order.limit_price, submit_ts=now, order_id=result.order_id,
            )
            state.posted_limits[result.order_id] = elo
            posted.append(elo)
        state.posted_at_ts = now

        await self._emit(ExitAttempt(
            basket_id=basket.basket_id, ts=now, kind=kind,
            coupling_basket_bid_sum=per_share_limit_sum, per_leg_limits=tuple(posted),
            projected_proceeds_per_share=proceeds_ps, projected_exit_fees_per_share=exit_fees_ps,
            projected_net_per_share=net_ps, required_margin_per_share=required,
        ))

    async def _rebalance(self, basket: OpenBasket, state: _BasketState) -> None:
        """Restore balance (hedge) by cross-selling only the EXCESS of over-held
        legs down to the least-held level. This is the one place we cross the
        spread (taker), and only to remove directional exposure — not to liquidate.
        If an over-held leg can't be sold (no bid), revert instead."""
        now = datetime.now(timezone.utc)
        # Cancel resting limits + drain fills so remaining is fresh.
        for order_id, elo in list(state.posted_limits.items()):
            if elo.final_state == "resting":
                await self.client.cancel_limit(order_id)
        for u in await self.client.poll_resting_orders():
            await self._apply_update(u)
        state.posted_limits = {}

        target_level = state.balanced_level()   # sell each over-held leg down to this
        crossed: list[ExitLimitOrder] = []
        a_leg_cant_sell = False
        for (venue, outcome), remaining in list(state.remaining_to_sell.items()):
            excess = remaining - target_level
            if excess <= ZERO:
                continue
            book = await self.store.get(venue, outcome)
            if book is None or not book.yes_bids:
                a_leg_cant_sell = True
                continue
            market_key = book.market_key
            state.market_keys[(venue, outcome)] = market_key
            # Sweep down to min_leg_bid to sell the excess if any depth exists.
            order = Order(venue=venue, outcome_name=outcome, market_key=market_key,
                          side="sell", size=excess, limit_price=self.cfg.min_leg_bid)
            res = await self.client.submit_ioc(order)
            filled = res.filled_size
            if filled > ZERO:
                state.sold[(venue, outcome)] = state.sold.get((venue, outcome), ZERO) + filled
                state.remaining_to_sell[(venue, outcome)] = remaining - filled
                state.realized_proceeds += filled * res.fill_vwap
                state.realized_exit_fees += res.fees_paid
            crossed.append(ExitLimitOrder(
                venue=venue, outcome_name=outcome, market_key=market_key,
                size=excess, limit_price=self.cfg.min_leg_bid, submit_ts=now,
                order_id=res.order_id or "ioc", filled_size=filled,
                fill_vwap=res.fill_vwap, fees_paid=res.fees_paid,
                final_state="filled" if filled >= excess else "partial",
            ))

        await self._emit(self._summary_attempt(basket, state, "escalated", crossed))

        if not state.is_imbalanced():
            # Re-balanced. Resume the normal flow next tick (keep holding the
            # balanced remainder and try to liquidate it as conditions allow).
            state.partial_since_ts = None
        elif a_leg_cant_sell:
            # An over-held leg has no bid — can't sell it down. Revert by buying
            # the under-held legs back up to match, then hold to settlement.
            await self._revert(basket, state)
        else:
            # Thin top-of-book left a residual excess; re-clock and retry next tick.
            state.partial_since_ts = now

    async def _revert(self, basket: OpenBasket, state: _BasketState) -> None:
        """Buy the under-held legs back UP to the most-held level to restore a
        complete (balanced, risk-free) basket, then hold to settlement (path B)."""
        now = datetime.now(timezone.utc)
        target_level = state.max_remaining()    # raise every leg up to this
        buys: list[ExitLimitOrder] = []
        for (venue, outcome), remaining in list(state.remaining_to_sell.items()):
            need = target_level - remaining
            if need <= ZERO:
                continue
            book = await self.store.get(venue, outcome)
            if book is None or not book.yes_asks:
                # Can't even buy back — log and hold; this leg stays short. Rare
                # tail case (no ask depth at all).
                continue
            market_key = book.market_key
            state.market_keys[(venue, outcome)] = market_key
            # Sweep up to max_leg_bid to re-acquire the needed quantity.
            order = Order(venue=venue, outcome_name=outcome, market_key=market_key,
                          side="buy", size=need, limit_price=self.cfg.max_leg_bid)
            res = await self.client.submit_ioc(order)
            filled = res.filled_size
            if filled > ZERO:
                state.sold[(venue, outcome)] = max(ZERO, state.sold.get((venue, outcome), ZERO) - filled)
                state.remaining_to_sell[(venue, outcome)] = remaining + filled
                state.realized_buyback_cost += filled * res.fill_vwap + res.fees_paid
            buys.append(ExitLimitOrder(
                venue=venue, outcome_name=outcome, market_key=market_key,
                size=need, limit_price=self.cfg.max_leg_bid, submit_ts=now,
                order_id=res.order_id or "ioc", filled_size=filled,
                fill_vwap=res.fill_vwap, fees_paid=res.fees_paid,
                final_state="filled" if filled >= need else "partial",
            ))

        state.hold_to_settlement = True
        state.posted_limits = {}
        await self._emit(self._summary_attempt(basket, state, "reverted", buys))

    async def _record_blocked(
        self,
        basket: OpenBasket,
        reason: str,
        coupling_sum: Decimal = ZERO,
        projected_proceeds_ps: Decimal = ZERO,
        projected_exit_fees_ps: Decimal = ZERO,
        projected_net_ps: Decimal = ZERO,
    ) -> None:
        await self._emit(ExitAttempt(
            basket_id=basket.basket_id,
            ts=datetime.now(timezone.utc),
            kind="blocked",
            coupling_basket_bid_sum=coupling_sum,
            per_leg_limits=(),
            projected_proceeds_per_share=projected_proceeds_ps,
            projected_exit_fees_per_share=projected_exit_fees_ps,
            projected_net_per_share=projected_net_ps,
            required_margin_per_share=self.cfg.required_margin_per_share,
            blocked_by=reason,
        ))

    async def _apply_update(self, update) -> None:
        """Apply a RestingOrderUpdate (fill or cancel) to its owning basket's
        accounting. Fills reduce remaining_to_sell and grow sold + realized."""
        for basket_id, state in list(self._basket_state.items()):
            elo = state.posted_limits.get(update.order_id)
            if elo is None:
                continue
            key = (update.venue, update.outcome_name)
            if update.filled_size_delta > ZERO:
                state.sold[key] = state.sold.get(key, ZERO) + update.filled_size_delta
                state.remaining_to_sell[key] = (
                    state.remaining_to_sell.get(key, ZERO) - update.filled_size_delta
                )
                state.realized_proceeds += update.filled_size_delta * update.fill_vwap
                state.realized_exit_fees += update.fees_delta
            state.posted_limits[update.order_id] = ExitLimitOrder(
                venue=elo.venue, outcome_name=elo.outcome_name, market_key=elo.market_key,
                size=elo.size, limit_price=elo.limit_price, submit_ts=elo.submit_ts,
                order_id=elo.order_id, filled_size=update.cumulative_filled,
                fill_vwap=update.fill_vwap if update.cumulative_filled > ZERO else ZERO,
                fees_paid=elo.fees_paid + update.fees_delta, final_state=update.final_state,
            )
            return

    def _summary_attempt(
        self, basket: OpenBasket, state: _BasketState, kind: str,
        legs: list[ExitLimitOrder],
    ) -> ExitAttempt:
        target = basket.target_basket_size if basket.target_basket_size > ZERO else Decimal("1")
        proceeds_ps = state.realized_proceeds / target
        fees_ps = state.realized_exit_fees / target
        buyback_ps = state.realized_buyback_cost / target
        net_ps = (
            proceeds_ps - buyback_ps
            - basket.cost_basis_per_share_total
            - basket.entry_fees_per_share_total - fees_ps
        )
        return ExitAttempt(
            basket_id=basket.basket_id, ts=datetime.now(timezone.utc), kind=kind,
            coupling_basket_bid_sum=ZERO, per_leg_limits=tuple(legs),
            projected_proceeds_per_share=ZERO, projected_exit_fees_per_share=ZERO,
            projected_net_per_share=ZERO,
            required_margin_per_share=self.cfg.required_margin_per_share,
            realized_proceeds_per_share=proceeds_ps, realized_exit_fees_per_share=fees_ps,
            realized_net_per_share=net_ps,
            all_legs_filled=(state.remaining_total() <= ZERO and not state.hold_to_settlement),
        )

    async def _finalize_filled(self, basket: OpenBasket, state: _BasketState) -> None:
        """The basket is fully sold. Emit the realized summary and remove it."""
        await self._emit(self._summary_attempt(basket, state, "fill", list(state.posted_limits.values())))
        await self.position_store.remove(basket.basket_id)
        self._basket_state.pop(basket.basket_id, None)

    async def _emit(self, attempt: ExitAttempt) -> None:
        if self.on_exit_attempt is None:
            return
        try:
            await self.on_exit_attempt(attempt)
        except Exception:
            pass
