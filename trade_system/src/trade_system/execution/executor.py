from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from ..books import BookStore
from ..depth import walk_book
from ..detector import FireEvent
from ..fees import FeeConfig, venue_taker_fee_total
from ..models import BookSnapshot, EventSpec, Venue
from .client import OrderClient
from .models import (
    BasketAttempt,
    Fill,
    FireContext,
    LegState,
    Order,
    OrderRecord,
    OrderResult,
    RoundRecord,
    Side,
)

ZERO = Decimal("0")
ONE = Decimal("1")


def _floor_contracts(x: Decimal) -> Decimal:
    """Round down to whole contracts; venues don't accept fractional sizes."""
    return x.to_integral_value(rounding="ROUND_FLOOR")


@dataclass
class ExecConfig:
    max_capital_per_trade: Decimal = Decimal("50")
    min_capital_per_trade: Decimal = Decimal("10")
    profitable_depth_fraction: Decimal = Decimal("0.5")
    retry_seconds: float = 2.0
    retry_poll_seconds: float = 0.1
    max_unhedged_loss_pct: Decimal = Decimal("0.05")


@dataclass
class ExitConfig:
    """Tunables for the exit monitor (path A vs. path B)."""
    coupling_tolerance: Decimal = Decimal("0.01")        # basket bid sum ≥ 1 − this
    bid_stability_window_ticks: int = 2                  # K consecutive ticks
    bid_stability_threshold: Decimal = Decimal("0.01")   # per-tick |Δbest_bid| ≤ this
    required_margin_per_share: Decimal = Decimal("0.01")
    # Per-tick sell-size cap (mirror of the entry share cap). Each cycle sells a
    # uniform sub-basket of at most `depth_fraction × min over legs of
    # (bid depth within bid_depth_ticks of the touch)`, so we never dump the whole
    # position into a thin book. The sub-basket is sold in equal size across legs
    # so the held remainder stays balanced (hedged).
    depth_fraction: Decimal = Decimal("0.5")
    bid_depth_ticks: int = 3            # count bid size at prices ≥ best_bid − N·tick
    # Re-peg resting maker limits to follow the touch (best_bid + tick) when the
    # bid drifts down, so the order stays at the front of the book and fills
    # before price runs away. Only chases down while the basket still clears the
    # required margin at the new price.
    repeg_enabled: bool = True
    limit_timeout_seconds: float = 30.0
    # Once an exit is partially filled (some legs sold, some not) the basket is
    # directionally exposed. This is a *shorter* clock than limit_timeout_seconds:
    # if the position stays partially unhedged longer than this, force completion
    # by crossing the spread on the unsold legs (and, failing that, reverting).
    partial_exit_deadline_seconds: float = 5.0
    min_leg_bid: Decimal = Decimal("0.02")
    max_leg_bid: Decimal = Decimal("0.98")
    kalshi_tick_size: Decimal = Decimal("0.01")
    polymarket_us_tick_size: Decimal = Decimal("0.01")
    monitor_hz: float = 0.5   # 0.5 Hz = one tick every 2 seconds


@dataclass
class _ResidualPlan:
    """Per-leg result of re-walking the current book at residual size for a retry."""
    outcome_name: str
    venue: Venue
    book: BookSnapshot
    vwap: Decimal
    deepest_price: Decimal
    fillable_size: Decimal
    projected_fees: Decimal


@dataclass(frozen=True)
class _LegDepthCap:
    """Per-leg profitable-depth analysis."""
    outcome_name: str
    chosen_venue: Venue | None
    max_profitable_price: Decimal       # highest leg price at which the basket stays profitable
    profitable_depth_contracts: Decimal # sum of displayed sizes at price ≤ max_profitable_price


@dataclass(frozen=True)
class _SizingDecision:
    """Snapshot of the sizing math at fire time. Carried into BasketAttempt
    for the trade journal so analysts can see exactly why a basket was sized
    the way it was."""
    total_balance_dollars: Decimal
    capital_cap_dollars: Decimal             # min(max_capital_per_trade, balance)
    min_capital_per_trade_dollars: Decimal
    profitable_depth_fraction: Decimal
    capital_size_contracts: Decimal          # floor(capital_cap / per_share_cost)
    achievable_size_contracts: Decimal       # detector's achievable size
    per_leg_depth: tuple[_LegDepthCap, ...]
    share_cap_contracts: Decimal             # fraction × min(profitable_depth across legs)
    chosen_size_contracts: Decimal           # min(capital_size, achievable, share_cap)
    chosen_size_dollars: Decimal             # = chosen_size × per_share_cost
    binding_constraint: str                  # which cap bound: "capital" | "achievable" | "share_cap"
    aborted: bool
    abort_reason: str | None


class EntryExecutor:
    """Drives a basket entry from fire to either complete or unwound.

    Lifecycle on fire:
      1. Compute basket size = min(target_size from detector, depth-achievable, contracts that fit the capital cap).
      2. Re-walk current book per leg (cheaper venue per leg) and submit N IOC orders in parallel.
      3. Process fill results. If any leg is short:
         a. Check unhedged-loss kill switch (current bids vs cost basis).
         b. Re-walk current books for residuals; pick the cheaper venue (may differ from initial).
         c. Check whether completing the basket at projected residual prices is still profitable.
         d. If yes → submit residual IOCs (loop).
         e. If no → sleep retry_poll_seconds and re-check, until retry_seconds budget expires.
      4. If after retry_seconds any leg is still short → unwind (sell back filled portions at market on the venue they were bought on).
      5. Emit a BasketAttempt summary to JSONL.
    """

    def __init__(
        self,
        event: EventSpec,
        store: BookStore,
        order_client: OrderClient,
        fee_cfg: FeeConfig,
        exec_cfg: ExecConfig,
        entry_threshold: Decimal,
        slippage_buffer_per_share: Decimal,
        depth_haircut: Decimal,
        on_attempt=None,  # async callback(BasketAttempt) for JSONL/state
        abort_event: asyncio.Event | None = None,
    ) -> None:
        self.event = event
        self.store = store
        self.client = order_client
        self.fee_cfg = fee_cfg
        self.exec_cfg = exec_cfg
        self.entry_threshold = entry_threshold
        self.slippage_buffer_per_share = slippage_buffer_per_share
        self.depth_haircut = depth_haircut
        self._busy = False
        self._busy_lock = asyncio.Lock()
        self.on_attempt = on_attempt
        self.attempts: list[BasketAttempt] = []
        self.last_attempt: BasketAttempt | None = None
        # Manual-abort wiring. When set, the retry loop sees it on the next
        # iteration, breaks out with outcome="aborted_by_user", and the existing
        # unwind step sells back whatever filled. The event is then cleared so
        # subsequent fires aren't aborted by stale flags.
        self.abort_event = abort_event

    @property
    def busy(self) -> bool:
        return self._busy

    async def on_fire(self, fire: FireEvent) -> None:
        async with self._busy_lock:
            if self._busy:
                return
            self._busy = True
        try:
            attempt = await self._execute(fire)
            if attempt is not None:
                self.last_attempt = attempt
                self.attempts.append(attempt)
                if self.on_attempt is not None:
                    try:
                        await self.on_attempt(attempt)
                    except Exception:
                        pass
        finally:
            self._busy = False

    # ------------------------------------------------------------- internals

    async def _execute(self, fire: FireEvent) -> BasketAttempt | None:
        ev = fire.evaluation
        entry_started_ts = datetime.now(timezone.utc)
        rounds = 0
        prof_checks = 0
        unwind_orders = 0
        round_records: list[RoundRecord] = []
        unwind_round_record: RoundRecord | None = None

        # 1. Compute target basket size.
        sizing = await self._compute_sizing(ev)
        if sizing.aborted:
            return BasketAttempt(
                ts=datetime.now(timezone.utc),
                target_basket_size=ZERO,
                legs=(),
                outcome="aborted",
                note=sizing.abort_reason,
                sizing_decision=sizing,
            )
        target_size = sizing.chosen_size_contracts
        per_share_cost = ev.entry_cost_per_share

        # 2. Build initial per-leg state, sized to the basket target.
        leg_states: dict[str, LegState] = {
            outcome.name: LegState(outcome_name=outcome.name, target_size=target_size)
            for outcome in self.event.outcomes
        }

        # 3. Initial parallel IOC round.
        record = await self._submit_residual_round(leg_states, len(round_records) + 1)
        if record is not None:
            round_records.append(record)
            rounds += 1

        # 4. Retry loop until either complete or time-up or kill-switch.
        deadline = time.monotonic() + self.exec_cfg.retry_seconds
        outcome = "complete"
        note: str | None = None

        while not self._all_legs_complete(leg_states):
            # 4a-pre. Manual abort: stop trying to fill the rest; the unwind
            # step below will sell back whatever's already filled.
            if self.abort_event is not None and self.abort_event.is_set():
                self.abort_event.clear()
                outcome = "aborted_by_user"
                note = "manual abort requested"
                break

            # 4a. Unhedged-loss kill switch.
            loss_pct = await self._compute_unhedged_loss_pct(leg_states)
            if loss_pct is not None and loss_pct > self.exec_cfg.max_unhedged_loss_pct:
                outcome = "unwound_loss"
                note = f"unhedged_loss_pct={loss_pct:.4f} > {self.exec_cfg.max_unhedged_loss_pct}"
                break

            # 4b. Re-walk and check profitability of completing residuals.
            residual_plans = await self._plan_residuals(leg_states)
            if residual_plans is None:
                # No depth available on at least one leg to complete. Wait briefly and retry,
                # in case books refresh. Don't fire orders this iteration.
                if time.monotonic() >= deadline:
                    outcome = "unwound_no_residual_depth"
                    note = "residual_depth_missing_at_deadline"
                    break
                await asyncio.sleep(self.exec_cfg.retry_poll_seconds)
                continue

            prof_checks += 1
            if self._completion_profitable(leg_states, residual_plans, target_size):
                # 4c. Submit fresh IOC orders for residuals at the newly walked limits.
                # If any of these IOCs partial-fill, the next iteration of this loop
                # will re-walk the (depleted) books, re-check profitability against the
                # remaining residuals, and submit again — as many rounds as needed
                # until either complete, deadline expires, or profitability flips.
                record = await self._submit_orders_from_plans(
                    leg_states, residual_plans, round_number=len(round_records) + 1
                )
                if record is not None:
                    round_records.append(record)
                    rounds += 1
                else:
                    # All planned residuals floored to < 1 contract — can't submit anything.
                    # Wait briefly in case more depth appears on the book.
                    if time.monotonic() >= deadline:
                        outcome = "unwound_no_residual_depth"
                        note = "no_integer_residual_at_deadline"
                        break
                    await asyncio.sleep(self.exec_cfg.retry_poll_seconds)
            else:
                # Not profitable right now; wait briefly and re-check until deadline.
                if time.monotonic() >= deadline:
                    outcome = "unwound_timeout"
                    note = f"completion_unprofitable_at_deadline"
                    break
                await asyncio.sleep(self.exec_cfg.retry_poll_seconds)

        # 5. Unwind if needed.
        if outcome != "complete":
            unwind_round_record = await self._unwind(leg_states, round_number=len(round_records) + 1)
            if unwind_round_record is not None:
                unwind_orders = len(unwind_round_record.orders)

        entry_complete_ts = datetime.now(timezone.utc)

        # Build fire context from FireEvent + detector inputs we have.
        fire_ctx = FireContext(
            fire_ts=fire.ts,
            gap_window_opened_ts=fire.gap_window_opened_ts,
            gap_window_age_ms_at_fire=fire.gap_window_age_ms_at_fire,
            projected_entry_cost_per_share=ev.entry_cost_per_share,
            projected_basket_cost_per_share=ev.basket_cost_per_share,
            projected_total_fees_per_share=ev.total_fees_per_share,
            slippage_buffer_per_share=ev.slippage_buffer_per_share,
            depth_haircut=ev.depth_haircut,
            entry_threshold=ev.entry_threshold,
            achievable_size_at_fire=ev.achievable_size,
            edge_per_share_at_fire=ev.edge_per_share,
            velocity_per_share_per_sec=fire.velocity_per_share_per_sec,
            non_widening_ticks=fire.consecutive_non_widening_ticks,
        )

        # End-of-attempt mark-to-market per leg, using current bids.
        mtm: dict[str, Decimal] = {}
        for state in leg_states.values():
            if state.gross_filled_buy_size <= ZERO:
                continue
            leg_value = ZERO
            for venue, size in state.fills_by_venue("buy").items():
                book = await self.store.get(venue, state.outcome_name)
                if book is None or not book.yes_bids:
                    continue
                walked = walk_book(
                    book.yes_bids, size, side="bid", size_multiplier=self.depth_haircut,
                )
                if walked.filled > ZERO:
                    leg_value += walked.filled * walked.vwap
            mtm[state.outcome_name] = leg_value

        return BasketAttempt(
            ts=entry_complete_ts,
            target_basket_size=target_size,
            legs=tuple(leg_states.values()),
            outcome=outcome,
            note=note,
            submission_rounds=rounds,
            profitability_checks=prof_checks,
            unwind_orders_sent=unwind_orders,
            fire_context=fire_ctx,
            entry_started_ts=entry_started_ts,
            entry_complete_ts=entry_complete_ts,
            rounds=tuple(round_records),
            unwind_round=unwind_round_record,
            mark_to_market_dollars_per_leg=mtm,
            sizing_decision=sizing,
        )

    async def _compute_sizing(self, ev) -> "_SizingDecision":
        """Compute the basket-size decision before any orders go out.

        Combines:
          - capital cap: min(--max-capital-per-trade, total balance) / per_share_cost
          - depth cap: detector's achievable_size (thinnest leg, walker-projected)
          - share cap: fraction × min over legs of (contracts at price ≤ max_profitable_price)
            where max_profitable_price = entry_threshold - sum_other_leg_vwaps
                                                        - total_fees - slippage_buffer
        Aborts if chosen size × per_share_cost < --min-capital-per-trade, or if any
        leg has zero profitable depth (basket isn't sustainable).
        """
        total_balance = await self.client.get_total_balance()
        capital_cap = min(self.exec_cfg.max_capital_per_trade, total_balance)
        per_share_cost = ev.entry_cost_per_share
        min_capital = self.exec_cfg.min_capital_per_trade
        fraction = self.exec_cfg.profitable_depth_fraction

        def abort(reason: str, depth: tuple = ()) -> _SizingDecision:
            return _SizingDecision(
                total_balance_dollars=total_balance,
                capital_cap_dollars=capital_cap,
                min_capital_per_trade_dollars=min_capital,
                profitable_depth_fraction=fraction,
                capital_size_contracts=ZERO,
                achievable_size_contracts=ev.achievable_size,
                per_leg_depth=depth,
                share_cap_contracts=ZERO,
                chosen_size_contracts=ZERO,
                chosen_size_dollars=ZERO,
                binding_constraint="aborted",
                aborted=True,
                abort_reason=reason,
            )

        if per_share_cost <= ZERO:
            return abort("per_share_cost is zero or negative")
        if capital_cap <= ZERO:
            return abort(f"no capital available (balance={total_balance})")
        if ev.achievable_size <= ZERO:
            return abort(f"no achievable depth from detector")

        capital_size = _floor_contracts(capital_cap / per_share_cost)
        achievable = _floor_contracts(ev.achievable_size)

        # Per-leg profitable depth.
        sum_all_vwaps = sum((leg.vwap for leg in ev.legs if leg.chosen_venue), ZERO)
        sum_all_fees = ev.total_fees_per_share
        slippage_buffer = ev.slippage_buffer_per_share
        entry_threshold = ev.entry_threshold

        per_leg_depth: list[_LegDepthCap] = []
        any_leg_zero_depth = False
        for leg in ev.legs:
            if leg.chosen_venue is None:
                # Should never happen on a fire (achievable > 0 implies all legs have a venue).
                any_leg_zero_depth = True
                per_leg_depth.append(_LegDepthCap(
                    outcome_name=leg.outcome_name, chosen_venue=None,
                    max_profitable_price=ZERO, profitable_depth_contracts=ZERO,
                ))
                continue
            other_legs_vwap = sum_all_vwaps - leg.vwap
            max_profitable_price = (
                entry_threshold - other_legs_vwap - sum_all_fees - slippage_buffer
            )
            if max_profitable_price <= ZERO:
                any_leg_zero_depth = True
                per_leg_depth.append(_LegDepthCap(
                    outcome_name=leg.outcome_name, chosen_venue=leg.chosen_venue,
                    max_profitable_price=max_profitable_price,
                    profitable_depth_contracts=ZERO,
                ))
                continue
            book = await self.store.get(leg.chosen_venue, leg.outcome_name)
            if book is None or not book.yes_asks:
                any_leg_zero_depth = True
                per_leg_depth.append(_LegDepthCap(
                    outcome_name=leg.outcome_name, chosen_venue=leg.chosen_venue,
                    max_profitable_price=max_profitable_price,
                    profitable_depth_contracts=ZERO,
                ))
                continue
            contracts = sum(
                (lvl.size for lvl in book.yes_asks if lvl.price <= max_profitable_price),
                ZERO,
            )
            if contracts <= ZERO:
                any_leg_zero_depth = True
            per_leg_depth.append(_LegDepthCap(
                outcome_name=leg.outcome_name,
                chosen_venue=leg.chosen_venue,
                max_profitable_price=max_profitable_price,
                profitable_depth_contracts=contracts,
            ))

        per_leg_tuple = tuple(per_leg_depth)
        if any_leg_zero_depth:
            return abort(
                "at least one leg has zero profitable depth at projected basket prices",
                depth=per_leg_tuple,
            )

        min_depth = min((d.profitable_depth_contracts for d in per_leg_depth), default=ZERO)
        share_cap = _floor_contracts(fraction * min_depth)

        chosen_size = _floor_contracts(min(capital_size, achievable, share_cap))
        if chosen_size <= ZERO:
            return abort(
                f"chosen_size resolved to 0 (capital={capital_size}, ach={achievable}, share_cap={share_cap})",
                depth=per_leg_tuple,
            )

        chosen_dollars = chosen_size * per_share_cost
        if chosen_dollars < min_capital:
            return abort(
                f"basket dollar value ${chosen_dollars} < min ${min_capital}",
                depth=per_leg_tuple,
            )

        if chosen_size == capital_size:
            binding = "capital"
        elif chosen_size == achievable:
            binding = "achievable"
        else:
            binding = "share_cap"

        return _SizingDecision(
            total_balance_dollars=total_balance,
            capital_cap_dollars=capital_cap,
            min_capital_per_trade_dollars=min_capital,
            profitable_depth_fraction=fraction,
            capital_size_contracts=capital_size,
            achievable_size_contracts=achievable,
            per_leg_depth=per_leg_tuple,
            share_cap_contracts=share_cap,
            chosen_size_contracts=chosen_size,
            chosen_size_dollars=chosen_dollars,
            binding_constraint=binding,
            aborted=False,
            abort_reason=None,
        )

    @staticmethod
    def _all_legs_complete(leg_states: dict[str, LegState]) -> bool:
        # Residual under 1 contract is treated as complete: no real venue can fill
        # a fractional contract anyway, so chasing sub-unit residuals is pointless.
        return all(s.residual < ONE for s in leg_states.values())

    async def _submit_residual_round(
        self, leg_states: dict[str, LegState], round_number: int,
    ) -> RoundRecord | None:
        """Returns a RoundRecord if at least one IOC order was issued, else None."""
        plans = await self._plan_residuals(leg_states)
        if plans is None:
            return None
        return await self._submit_orders_from_plans(leg_states, plans, round_number)

    async def _plan_residuals(self, leg_states: dict[str, LegState]) -> list[_ResidualPlan] | None:
        """Per leg with residual size, choose the cheaper venue and walk current book.

        Returns None if any leg with residual has no fillable depth at all on either venue
        — completion isn't possible right now.
        """
        plans: list[_ResidualPlan] = []
        for state in leg_states.values():
            if state.is_complete:
                continue
            residual = state.residual
            if residual <= ZERO:
                continue

            candidates: list[_ResidualPlan] = []
            for venue in ("kalshi", "polymarket_us"):
                book = await self.store.get(venue, state.outcome_name)
                if book is None or not book.yes_asks:
                    continue
                walked = walk_book(
                    book.yes_asks, residual,
                    side="ask", size_multiplier=self.depth_haircut,
                )
                # Skip venues that can't even fill one whole contract — submitting
                # an IOC of size 0 would be a no-op and cause the retry loop to spin.
                if _floor_contracts(walked.filled) < ONE:
                    continue
                deepest_price = book.yes_asks[walked.levels_consumed - 1].price
                projected_fees = venue_taker_fee_total(
                    venue, walked.vwap, walked.filled, self.fee_cfg
                )
                candidates.append(_ResidualPlan(
                    outcome_name=state.outcome_name,
                    venue=venue,
                    book=book,
                    vwap=walked.vwap,
                    deepest_price=deepest_price,
                    fillable_size=walked.filled,
                    projected_fees=projected_fees,
                ))

            if not candidates:
                return None
            plans.append(min(candidates, key=lambda c: c.vwap))
        return plans

    def _completion_profitable(
        self,
        leg_states: dict[str, LegState],
        plans: list[_ResidualPlan],
        target_size: Decimal,
    ) -> bool:
        """Is the total committed (realized + projected residual) under the threshold?

        Compares total committed dollars vs. (entry_threshold + slippage_buffer)
        scaled to the projected number of basket shares we'd end up with. We treat
        each leg's projected basket size as min(target, filled + residual_fillable);
        the basket capacity is the min of those across legs.
        """
        plans_by_leg = {p.outcome_name: p for p in plans}

        # Projected basket size = min over legs of (filled + planned residual fill).
        projected_sizes = []
        for state in leg_states.values():
            if state.is_complete:
                projected_sizes.append(state.filled_size)
                continue
            p = plans_by_leg.get(state.outcome_name)
            if p is None:
                return False
            projected_sizes.append(state.filled_size + min(p.fillable_size, state.residual))

        projected_basket = min(projected_sizes) if projected_sizes else ZERO
        if projected_basket <= ZERO:
            return False

        # Cap by target size — we don't want more than asked.
        projected_basket = min(projected_basket, target_size)

        # Sum committed dollars across legs (proportional to projected_basket fraction).
        total_committed = ZERO
        for state in leg_states.values():
            filled = state.filled_size
            buy_cost = state.total_buy_cost_dollars
            buy_fees = state.total_buy_fees

            if filled >= projected_basket:
                # Use a proportional share of the realized cost at the basket size we'll
                # actually end up with.
                if filled > 0:
                    leg_cost = (buy_cost + buy_fees) * (projected_basket / filled)
                else:
                    leg_cost = ZERO
            else:
                residual_needed = projected_basket - filled
                p = plans_by_leg.get(state.outcome_name)
                if p is None:
                    return False
                # Projected fee for the residual portion only (recompute at the actual
                # residual_needed in case it's smaller than the walker's fillable_size).
                residual_fees = (
                    p.projected_fees * (residual_needed / p.fillable_size)
                    if p.fillable_size > 0 else ZERO
                )
                leg_cost = buy_cost + buy_fees + residual_needed * p.vwap + residual_fees
            total_committed += leg_cost

        # Add slippage buffer (per basket share).
        total_committed += self.slippage_buffer_per_share * projected_basket

        cap = self.entry_threshold * projected_basket
        return total_committed < cap

    async def _submit_orders_from_plans(
        self,
        leg_states: dict[str, LegState],
        plans: list[_ResidualPlan],
        round_number: int,
    ) -> RoundRecord | None:
        """Build IOC orders for each leg's residual at the plan's deepest-level limit,
        submit them in parallel, and record any fills back into leg state.

        Returns a RoundRecord with the per-order projections-vs-actuals + timing,
        or None if no orders were sendable.

        The caller's retry loop will keep calling this method as long as legs remain
        incomplete and completion stays profitable — so partial fills naturally
        cascade into additional rounds."""
        # Build orders with projection metadata kept alongside each.
        prepared: list[tuple[Order, _ResidualPlan, Decimal, Decimal, Decimal]] = []
        # (Order, plan, projected_vwap, projected_fees_total, requested_size)
        for plan in plans:
            state = leg_states[plan.outcome_name]
            size = _floor_contracts(min(state.residual, plan.fillable_size))
            if size < ONE:
                continue
            # Projected fees scale proportionally to the actual size we'll submit
            # (vs plan.fillable_size which may be larger after haircut math).
            projected_fees = (
                plan.projected_fees * (size / plan.fillable_size)
                if plan.fillable_size > ZERO else ZERO
            )
            order = Order(
                venue=plan.venue,
                outcome_name=plan.outcome_name,
                market_key=plan.book.market_key,
                side="buy",
                size=size,
                limit_price=plan.deepest_price,
            )
            prepared.append((order, plan, plan.vwap, projected_fees, size))

        if not prepared:
            return None

        round_start = datetime.now(timezone.utc)
        per_order_submit_ts: list[datetime] = []
        coros = []
        for order, *_ in prepared:
            per_order_submit_ts.append(datetime.now(timezone.utc))
            coros.append(self.client.submit_ioc(order))
        results = await asyncio.gather(*coros)
        round_end = datetime.now(timezone.utc)

        order_records: list[OrderRecord] = []
        for (order, plan, projected_vwap, projected_fees, requested_size), submit_ts, result in zip(
            prepared, per_order_submit_ts, results
        ):
            response_ts = result.ts
            latency_ms = (response_ts - submit_ts).total_seconds() * 1000.0
            order_records.append(OrderRecord(
                leg_outcome=order.outcome_name,
                venue=order.venue,
                side=order.side,
                requested_size=requested_size,
                limit_price=order.limit_price,
                projected_vwap=projected_vwap,
                projected_fees=projected_fees,
                submit_ts=submit_ts,
                response_ts=response_ts,
                submission_latency_ms=latency_ms,
                filled_size=result.filled_size,
                actual_vwap=result.fill_vwap,
                actual_fees=result.fees_paid,
                fully_filled=result.filled_size >= requested_size,
                reject_reason=result.reject_reason,
            ))
            state = leg_states[order.outcome_name]
            if result.filled_size > ZERO:
                state.fills.append(Fill(
                    venue=order.venue,
                    side=order.side,
                    size=result.filled_size,
                    price=result.fill_vwap,
                    fees=result.fees_paid,
                    ts=result.ts,
                ))

        return RoundRecord(
            round_number=round_number,
            round_start_ts=round_start,
            round_end_ts=round_end,
            round_duration_ms=(round_end - round_start).total_seconds() * 1000.0,
            orders=tuple(order_records),
        )

    async def _compute_unhedged_loss_pct(self, leg_states: dict[str, LegState]) -> Decimal | None:
        """Mark-to-market loss on filled-but-not-yet-complete-basket positions,
        expressed as a fraction of *cost basis* (the dollars we sunk in to date).

        Cost basis = sum over buys of (size × buy_price + fees).
        Current mark = sum over buys of (size × walked-bid-vwap on the same venue).
        Returns (cost_basis - current_mark) / cost_basis. None when not measurable.
        """
        cost_basis = ZERO
        current_mark = ZERO

        any_filled = False
        any_mark = False
        for state in leg_states.values():
            if state.filled_size <= ZERO:
                continue
            any_filled = True
            cost_basis += state.total_buy_cost_dollars + state.total_buy_fees
            for venue, size in state.fills_by_venue("buy").items():
                book = await self.store.get(venue, state.outcome_name)
                if book is None or not book.yes_bids:
                    continue
                walked = walk_book(
                    book.yes_bids, size,
                    side="bid", size_multiplier=self.depth_haircut,
                )
                if walked.filled <= ZERO:
                    continue
                current_mark += walked.filled * walked.vwap
                any_mark = True

        if not any_filled or not any_mark or cost_basis <= ZERO:
            return None
        loss = cost_basis - current_mark
        return loss / cost_basis

    async def _unwind(
        self, leg_states: dict[str, LegState], round_number: int,
    ) -> RoundRecord | None:
        """Sell back each filled portion on the venue it was bought on.
        Returns a RoundRecord for the unwind, or None if nothing to unwind."""
        prepared: list[tuple[Order, Decimal, Decimal]] = []  # (Order, projected_vwap, projected_fees)
        for state in leg_states.values():
            for venue, size in state.fills_by_venue("buy").items():
                if size <= ZERO:
                    continue
                book = await self.store.get(venue, state.outcome_name)
                if book is None or not book.yes_bids:
                    continue
                walked = walk_book(
                    book.yes_bids, size,
                    side="bid", size_multiplier=self.depth_haircut,
                )
                sell_size = _floor_contracts(min(size, walked.filled))
                if sell_size < ONE:
                    continue
                deepest_bid = book.yes_bids[walked.levels_consumed - 1].price
                projected_vwap = walked.vwap
                projected_fees = venue_taker_fee_total(venue, walked.vwap, sell_size, self.fee_cfg)
                order = Order(
                    venue=venue,
                    outcome_name=state.outcome_name,
                    market_key=book.market_key,
                    side="sell",
                    size=sell_size,
                    limit_price=deepest_bid,
                )
                prepared.append((order, projected_vwap, projected_fees))

        if not prepared:
            return None

        round_start = datetime.now(timezone.utc)
        per_submit_ts: list[datetime] = []
        coros = []
        for order, *_ in prepared:
            per_submit_ts.append(datetime.now(timezone.utc))
            coros.append(self.client.submit_ioc(order))
        results = await asyncio.gather(*coros)
        round_end = datetime.now(timezone.utc)

        order_records: list[OrderRecord] = []
        for (order, projected_vwap, projected_fees), submit_ts, result in zip(
            prepared, per_submit_ts, results
        ):
            response_ts = result.ts
            latency_ms = (response_ts - submit_ts).total_seconds() * 1000.0
            order_records.append(OrderRecord(
                leg_outcome=order.outcome_name,
                venue=order.venue,
                side=order.side,
                requested_size=order.size,
                limit_price=order.limit_price,
                projected_vwap=projected_vwap,
                projected_fees=projected_fees,
                submit_ts=submit_ts,
                response_ts=response_ts,
                submission_latency_ms=latency_ms,
                filled_size=result.filled_size,
                actual_vwap=result.fill_vwap,
                actual_fees=result.fees_paid,
                fully_filled=result.filled_size >= order.size,
                reject_reason=result.reject_reason,
            ))
            state = leg_states[order.outcome_name]
            if result.filled_size > ZERO:
                state.fills.append(Fill(
                    venue=order.venue,
                    side="sell",
                    size=result.filled_size,
                    price=result.fill_vwap,
                    fees=result.fees_paid,
                    ts=result.ts,
                ))

        return RoundRecord(
            round_number=round_number,
            round_start_ts=round_start,
            round_end_ts=round_end,
            round_duration_ms=(round_end - round_start).total_seconds() * 1000.0,
            orders=tuple(order_records),
        )


def basket_attempt_to_jsonl_payload(attempt: BasketAttempt) -> dict:
    return {
        "ts": attempt.ts.isoformat(),
        "target_basket_size": str(attempt.target_basket_size),
        "outcome": attempt.outcome,
        "note": attempt.note,
        "submission_rounds": attempt.submission_rounds,
        "profitability_checks": attempt.profitability_checks,
        "unwind_orders_sent": attempt.unwind_orders_sent,
        "legs": [
            {
                "outcome": leg.outcome_name,
                "target_size": str(leg.target_size),
                "filled_size": str(leg.filled_size),
                "avg_buy_price": str(leg.avg_buy_price),
                "total_buy_cost": str(leg.total_buy_cost_dollars),
                "total_buy_fees": str(leg.total_buy_fees),
                "fills": [
                    {
                        "venue": f.venue,
                        "side": f.side,
                        "size": str(f.size),
                        "price": str(f.price),
                        "fees": str(f.fees),
                        "ts": f.ts.isoformat(),
                    }
                    for f in leg.fills
                ],
            }
            for leg in attempt.legs
        ],
    }
