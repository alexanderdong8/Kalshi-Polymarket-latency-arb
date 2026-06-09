"""Comprehensive per-trade journal.

Writes one structured TradeRecord per BasketAttempt to a dedicated JSONL log.
Each record contains:

- fire_context: what the detector projected at fire time (entry cost, fees,
  edge, gap-window timing, momentum)
- timing: wall-clock breakdown — entry_started/complete, total_attempt_ms,
  per-round latencies, per-order submission latency
- per-round: round duration, per-order projected vs actual VWAPs, fills,
  rejects, unfilled sizes (the unfilled partial orders)
- per-leg final state: target, filled, unfilled, cost basis, mark-to-market
  at attempt close, unrealized PnL → captures unhedged positions explicitly
- aggregates: projected_total_cost vs actual_total_cost, realized slippage
- outcome label + note (complete | unwound_* | aborted)
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import BasketAttempt, ExitAttempt, ExitLimitOrder, OrderRecord, RoundRecord

ZERO = Decimal("0")


def _ts(v) -> str | None:
    return v.isoformat() if v is not None else None


def _serialize_order(record: OrderRecord) -> dict[str, Any]:
    return {
        "leg_outcome": record.leg_outcome,
        "venue": record.venue,
        "side": record.side,
        "requested_size": str(record.requested_size),
        "limit_price": str(record.limit_price),
        "projected_vwap": str(record.projected_vwap),
        "projected_fees": str(record.projected_fees),
        "submit_ts": _ts(record.submit_ts),
        "response_ts": _ts(record.response_ts),
        "submission_latency_ms": record.submission_latency_ms,
        "filled_size": str(record.filled_size),
        "actual_vwap": str(record.actual_vwap),
        "actual_fees": str(record.actual_fees),
        "fully_filled": record.fully_filled,
        "reject_reason": record.reject_reason,
        # Derived fields the journal makes first-class for analysis.
        "slippage_per_share": str(record.slippage_per_share),
        "unfilled_size": str(record.unfilled_size),
    }


def _serialize_round(record: RoundRecord) -> dict[str, Any]:
    # Aggregate per-round projected vs actual cost (across orders that filled).
    projected_filled_cost = ZERO
    actual_filled_cost = ZERO
    total_filled = ZERO
    for o in record.orders:
        if o.filled_size > ZERO:
            projected_filled_cost += o.filled_size * o.projected_vwap
            actual_filled_cost += o.filled_size * o.actual_vwap
            total_filled += o.filled_size
    return {
        "round_number": record.round_number,
        "round_start_ts": _ts(record.round_start_ts),
        "round_end_ts": _ts(record.round_end_ts),
        "round_duration_ms": record.round_duration_ms,
        "total_filled_in_round": str(total_filled),
        "projected_filled_cost_dollars": str(projected_filled_cost),
        "actual_filled_cost_dollars": str(actual_filled_cost),
        "round_realized_slippage_dollars": str(actual_filled_cost - projected_filled_cost),
        "orders": [_serialize_order(o) for o in record.orders],
    }


def build_trade_record_payload(attempt: BasketAttempt) -> dict[str, Any]:
    """Convert a BasketAttempt into the comprehensive JSONL payload."""
    ev_started = attempt.entry_started_ts
    ev_complete = attempt.entry_complete_ts
    total_attempt_ms = (
        (ev_complete - ev_started).total_seconds() * 1000.0
        if (ev_started and ev_complete) else None
    )

    # Per-leg final state, including projected vs actual cost basis and
    # mark-to-market at attempt close.
    legs_final: list[dict[str, Any]] = []
    total_cost_basis = ZERO
    total_mark = ZERO
    total_unhedged_cost_basis = ZERO
    any_unhedged = False
    for leg in attempt.legs:
        filled = leg.filled_size  # net of any sells; for unwound attempts this drops back to 0
        gross_buy_size = leg.gross_filled_buy_size
        cost = leg.total_buy_cost_dollars + leg.total_buy_fees
        mark = attempt.mark_to_market_dollars_per_leg.get(leg.outcome_name)
        pnl = (mark - cost) if mark is not None else None
        unfilled = leg.target_size - gross_buy_size
        is_unhedged = (gross_buy_size > ZERO and unfilled > ZERO and attempt.outcome != "complete")
        # Track "unhedged" specifically as: filled-but-not-at-target during a non-complete outcome.
        # For complete fills, no leg is unhedged at end.
        if attempt.outcome != "complete" and gross_buy_size > ZERO and not leg.is_complete:
            any_unhedged = True
            total_unhedged_cost_basis += cost
        total_cost_basis += cost
        if mark is not None:
            total_mark += mark

        legs_final.append({
            "outcome": leg.outcome_name,
            "target_size": str(leg.target_size),
            "gross_filled_buy_size": str(gross_buy_size),
            "net_filled_size_after_unwind": str(filled),
            "unfilled_at_target": str(unfilled),
            "avg_buy_price": str(leg.avg_buy_price),
            "cost_basis_dollars": str(cost),
            "mark_to_market_dollars": str(mark) if mark is not None else None,
            "unrealized_pnl_dollars": str(pnl) if pnl is not None else None,
            "is_unhedged_at_attempt_close": is_unhedged,
            "fills_by_venue": {
                v: str(s) for v, s in leg.fills_by_venue("buy").items()
            },
            "sells_by_venue": {
                v: str(s) for v, s in leg.fills_by_venue("sell").items()
            },
            "all_fills": [
                {
                    "venue": f.venue,
                    "side": f.side,
                    "size": str(f.size),
                    "price": str(f.price),
                    "fees": str(f.fees),
                    "ts": _ts(f.ts),
                }
                for f in leg.fills
            ],
        })

    # Aggregate projected vs actual cost across all entry rounds.
    proj_cost_total = ZERO
    actual_cost_total = ZERO
    proj_fees_total = ZERO
    actual_fees_total = ZERO
    for r in attempt.rounds:
        for o in r.orders:
            if o.filled_size > ZERO:
                proj_cost_total += o.filled_size * o.projected_vwap
                actual_cost_total += o.filled_size * o.actual_vwap
                # Fees scale to actual filled vs requested.
                if o.requested_size > ZERO:
                    proj_fees_total += o.projected_fees * (o.filled_size / o.requested_size)
                actual_fees_total += o.actual_fees

    realized_slippage_dollars = actual_cost_total - proj_cost_total
    actual_basket_cost_per_share = (
        (actual_cost_total + actual_fees_total) / attempt.target_basket_size
        if attempt.target_basket_size > ZERO else ZERO
    )

    sizing = attempt.sizing_decision
    sizing_block = None
    if sizing is not None:
        sizing_block = {
            "total_balance_dollars": str(sizing.total_balance_dollars),
            "capital_cap_dollars": str(sizing.capital_cap_dollars),
            "min_capital_per_trade_dollars": str(sizing.min_capital_per_trade_dollars),
            "profitable_depth_fraction": str(sizing.profitable_depth_fraction),
            "capital_size_contracts": str(sizing.capital_size_contracts),
            "achievable_size_contracts": str(sizing.achievable_size_contracts),
            "share_cap_contracts": str(sizing.share_cap_contracts),
            "chosen_size_contracts": str(sizing.chosen_size_contracts),
            "chosen_size_dollars": str(sizing.chosen_size_dollars),
            "binding_constraint": sizing.binding_constraint,
            "aborted": sizing.aborted,
            "abort_reason": sizing.abort_reason,
            "per_leg_depth": [
                {
                    "outcome": d.outcome_name,
                    "chosen_venue": d.chosen_venue,
                    "max_profitable_price": str(d.max_profitable_price),
                    "profitable_depth_contracts": str(d.profitable_depth_contracts),
                }
                for d in sizing.per_leg_depth
            ],
        }

    fc = attempt.fire_context
    fire_block = {
        "fire_ts": _ts(fc.fire_ts),
        "gap_window_opened_ts": _ts(fc.gap_window_opened_ts),
        "gap_window_age_ms_at_fire": fc.gap_window_age_ms_at_fire,
        "projected_entry_cost_per_share": str(fc.projected_entry_cost_per_share),
        "projected_basket_cost_per_share": str(fc.projected_basket_cost_per_share),
        "projected_total_fees_per_share": str(fc.projected_total_fees_per_share),
        "slippage_buffer_per_share": str(fc.slippage_buffer_per_share),
        "depth_haircut": str(fc.depth_haircut),
        "entry_threshold": str(fc.entry_threshold),
        "achievable_size_at_fire": str(fc.achievable_size_at_fire),
        "edge_per_share_at_fire": str(fc.edge_per_share_at_fire),
        "velocity_per_share_per_sec": str(fc.velocity_per_share_per_sec),
        "non_widening_ticks": fc.non_widening_ticks,
    } if fc is not None else None

    timing_block = {
        "entry_started_ts": _ts(ev_started),
        "entry_complete_ts": _ts(ev_complete),
        "total_attempt_ms": total_attempt_ms,
        "fire_to_entry_ms": (
            (ev_started - fc.fire_ts).total_seconds() * 1000.0
            if (ev_started and fc) else None
        ),
        "gap_window_closed_after_fire_ts": _ts(attempt.gap_window_closed_after_fire_ts),
        "gap_window_alive_at_attempt_close": attempt.gap_window_closed_after_fire_ts is None,
    }

    cost_block = {
        "projected_filled_cost_dollars": str(proj_cost_total),
        "actual_filled_cost_dollars": str(actual_cost_total),
        "projected_total_fees_dollars": str(proj_fees_total),
        "actual_total_fees_dollars": str(actual_fees_total),
        "realized_slippage_dollars": str(realized_slippage_dollars),
        "realized_slippage_per_share": str(
            realized_slippage_dollars / attempt.target_basket_size
            if attempt.target_basket_size > ZERO else ZERO
        ),
        "actual_basket_cost_per_share": str(actual_basket_cost_per_share),
    }

    return {
        "ts": _ts(attempt.ts),
        "outcome": attempt.outcome,
        "note": attempt.note,
        "target_basket_size": str(attempt.target_basket_size),
        "submission_rounds": attempt.submission_rounds,
        "profitability_checks": attempt.profitability_checks,
        "unwind_orders_sent": attempt.unwind_orders_sent,
        "has_unhedged_legs_at_close": any_unhedged,
        "total_unhedged_cost_basis_dollars": str(total_unhedged_cost_basis),
        "total_cost_basis_dollars": str(total_cost_basis),
        "total_mark_to_market_dollars": str(total_mark),
        "fire_context": fire_block,
        "sizing": sizing_block,
        "timing": timing_block,
        "cost": cost_block,
        "rounds": [_serialize_round(r) for r in attempt.rounds],
        "unwind_round": _serialize_round(attempt.unwind_round) if attempt.unwind_round else None,
        "legs_final": legs_final,
    }


class TradeJournal:
    """Writes one comprehensive TradeRecord per BasketAttempt."""

    def __init__(self, jsonl_writer) -> None:
        self._writer = jsonl_writer

    async def write(self, attempt: BasketAttempt) -> None:
        try:
            await self._writer.write_event(
                "info",
                build_trade_record_payload(attempt),
                kind="trade",
            )
        except Exception:
            pass


def _serialize_exit_limit(elo: ExitLimitOrder) -> dict[str, Any]:
    return {
        "venue": elo.venue,
        "outcome": elo.outcome_name,
        "market_key": elo.market_key,
        "size": str(elo.size),
        "limit_price": str(elo.limit_price),
        "order_id": elo.order_id,
        "submit_ts": _ts(elo.submit_ts),
        "filled_size": str(elo.filled_size),
        "fill_vwap": str(elo.fill_vwap),
        "fees_paid": str(elo.fees_paid),
        "final_state": elo.final_state,
    }


def build_exit_record_payload(attempt: ExitAttempt) -> dict[str, Any]:
    """Convert an ExitAttempt into a JSONL payload. Covers blocked evaluations
    (with the blocking reason + metric values), posted limits, and terminal
    fill/cancel summaries."""
    return {
        "basket_id": attempt.basket_id,
        "ts": _ts(attempt.ts),
        "kind": attempt.kind,
        "blocked_by": attempt.blocked_by,
        "coupling_basket_bid_sum": str(attempt.coupling_basket_bid_sum),
        "projected_proceeds_per_share": str(attempt.projected_proceeds_per_share),
        "projected_exit_fees_per_share": str(attempt.projected_exit_fees_per_share),
        "projected_net_per_share": str(attempt.projected_net_per_share),
        "required_margin_per_share": str(attempt.required_margin_per_share),
        "realized_proceeds_per_share": str(attempt.realized_proceeds_per_share),
        "realized_exit_fees_per_share": str(attempt.realized_exit_fees_per_share),
        "realized_net_per_share": str(attempt.realized_net_per_share),
        "all_legs_filled": attempt.all_legs_filled,
        "per_leg_limits": [_serialize_exit_limit(e) for e in attempt.per_leg_limits],
    }


class ExitJournal:
    """Writes one record per ExitAttempt to a dedicated exits JSONL.

    Records blocked evaluations (so the operator can see *why* exit isn't
    firing), posted-limit events, and terminal fill/cancel summaries.
    """

    def __init__(self, jsonl_writer) -> None:
        self._writer = jsonl_writer

    async def write(self, attempt: ExitAttempt) -> None:
        try:
            await self._writer.write_event(
                "info",
                build_exit_record_payload(attempt),
                kind="exit",
            )
        except Exception:
            pass
