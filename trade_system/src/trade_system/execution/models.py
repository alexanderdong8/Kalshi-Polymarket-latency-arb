from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from ..models import Venue

ZERO = Decimal("0")
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Order:
    """An IOC limit order ready to be submitted to a venue."""
    venue: Venue
    outcome_name: str
    market_key: str
    side: Side
    size: Decimal              # contracts
    limit_price: Decimal       # worst per-share price acceptable


@dataclass(frozen=True)
class OrderResult:
    """Reply from an order client after submission."""
    order: Order
    filled_size: Decimal       # contracts actually filled (may be < order.size on IOC)
    fill_vwap: Decimal         # average per-share price across filled levels
    fees_paid: Decimal         # total fees in dollars
    accepted: bool             # True if order reached venue (even if filled_size=0)
    reject_reason: str | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # For resting limit orders (submit_limit_postonly). None for IOC results.
    order_id: str | None = None

    @property
    def gross_cost(self) -> Decimal:
        """Dollars committed (positive for buy, positive for sell proceeds)."""
        return self.filled_size * self.fill_vwap


@dataclass(frozen=True)
class RestingOrderUpdate:
    """One change to a resting limit order, returned by poll_resting_orders."""
    order_id: str
    venue: Venue
    outcome_name: str
    side: Side
    limit_price: Decimal
    filled_size_delta: Decimal       # contracts filled since last poll (>= 0)
    fill_vwap: Decimal               # vwap of the new fill (== limit_price for sim)
    fees_delta: Decimal              # fees for the new fill
    cumulative_filled: Decimal       # total filled across all polls
    requested_size: Decimal          # original size at submit
    final_state: str                 # "resting" | "filled" | "partial" | "cancelled"
    ts: datetime


@dataclass(frozen=True)
class Fill:
    """One fill event from one venue, recorded into per-leg state."""
    venue: Venue
    side: Side
    size: Decimal
    price: Decimal            # per-share VWAP from this fill
    fees: Decimal             # dollars
    ts: datetime


@dataclass
class LegState:
    """Running state of one outcome leg while a basket entry is in progress.

    A leg may accumulate multiple fills across both venues (e.g. initial fill on
    Kalshi, residual on Polymarket if Polymarket re-prices cheaper). `fills_by_venue`
    is what the unwind path consumes to sell each portion back on the venue it was
    bought on.
    """
    outcome_name: str
    target_size: Decimal
    fills: list[Fill] = field(default_factory=list)

    @property
    def filled_size(self) -> Decimal:
        return sum((f.size for f in self.fills if f.side == "buy"), ZERO) \
             - sum((f.size for f in self.fills if f.side == "sell"), ZERO)

    @property
    def gross_filled_buy_size(self) -> Decimal:
        return sum((f.size for f in self.fills if f.side == "buy"), ZERO)

    @property
    def total_buy_cost_dollars(self) -> Decimal:
        """Sum of (size * price) for buys only — excludes fees."""
        return sum((f.size * f.price for f in self.fills if f.side == "buy"), ZERO)

    @property
    def total_buy_fees(self) -> Decimal:
        return sum((f.fees for f in self.fills if f.side == "buy"), ZERO)

    @property
    def avg_buy_price(self) -> Decimal:
        gross = self.gross_filled_buy_size
        if gross <= ZERO:
            return ZERO
        return self.total_buy_cost_dollars / gross

    @property
    def is_complete(self) -> bool:
        return self.filled_size >= self.target_size

    @property
    def residual(self) -> Decimal:
        return max(ZERO, self.target_size - self.filled_size)

    def fills_by_venue(self, side: Side = "buy") -> dict[Venue, Decimal]:
        out: dict[Venue, Decimal] = {}
        for f in self.fills:
            if f.side != side:
                continue
            out[f.venue] = out.get(f.venue, ZERO) + f.size
        return out


@dataclass(frozen=True)
class OrderRecord:
    """One IOC submission with everything we projected and everything we got back."""
    leg_outcome: str
    venue: Venue
    side: Side
    requested_size: Decimal
    limit_price: Decimal
    # Projections from the depth walker / fee model at submit time.
    projected_vwap: Decimal
    projected_fees: Decimal
    # Wall-clock timing of the submit→response round trip.
    submit_ts: datetime
    response_ts: datetime
    submission_latency_ms: float
    # Actual fill result.
    filled_size: Decimal
    actual_vwap: Decimal
    actual_fees: Decimal
    fully_filled: bool
    reject_reason: str | None = None

    @property
    def slippage_per_share(self) -> Decimal:
        """Positive number = filled worse than projected (a real cost)."""
        if self.filled_size <= ZERO:
            return ZERO
        return self.actual_vwap - self.projected_vwap

    @property
    def unfilled_size(self) -> Decimal:
        return self.requested_size - self.filled_size


@dataclass(frozen=True)
class RoundRecord:
    """One round of N parallel IOC submissions."""
    round_number: int                # 1-indexed
    round_start_ts: datetime
    round_end_ts: datetime
    round_duration_ms: float
    orders: tuple[OrderRecord, ...]  # one per leg that had a residual this round


@dataclass(frozen=True)
class FireContext:
    """Snapshot of detector context at fire time, carried into the journal."""
    fire_ts: datetime
    gap_window_opened_ts: datetime | None
    gap_window_age_ms_at_fire: float | None
    projected_entry_cost_per_share: Decimal
    projected_basket_cost_per_share: Decimal
    projected_total_fees_per_share: Decimal
    slippage_buffer_per_share: Decimal
    depth_haircut: Decimal
    entry_threshold: Decimal
    achievable_size_at_fire: Decimal
    edge_per_share_at_fire: Decimal
    velocity_per_share_per_sec: Decimal
    non_widening_ticks: int


@dataclass(frozen=True)
class BasketAttempt:
    """Summary of one entry attempt for forensic logs."""
    ts: datetime
    target_basket_size: Decimal
    legs: tuple[LegState, ...]
    outcome: Literal[
        "complete",
        "unwound_timeout",
        "unwound_loss",
        "unwound_no_residual_depth",
        "aborted",
        "aborted_by_user",
    ]
    note: str | None = None
    submission_rounds: int = 0          # convenience count of len(rounds)
    profitability_checks: int = 0       # number of plan-and-recheck iterations
    unwind_orders_sent: int = 0         # number of sell IOCs issued in the unwind step
    fire_context: FireContext | None = None
    entry_started_ts: datetime | None = None
    entry_complete_ts: datetime | None = None
    rounds: tuple[RoundRecord, ...] = ()
    unwind_round: RoundRecord | None = None
    gap_window_closed_after_fire_ts: datetime | None = None
    # End-of-attempt mark-to-market per leg, computed from current bids at attempt close.
    mark_to_market_dollars_per_leg: dict[str, Decimal] = field(default_factory=dict)
    # Sizing decision — exact inputs/output of the basket-size math.
    # Typed loosely (Any) to avoid a circular import with the executor module.
    sizing_decision: Any = None


@dataclass(frozen=True)
class OpenBasket:
    """One filled basket held after a `complete` entry, awaiting exit or settlement.

    Carries an immutable snapshot of the entry fills so subsequent unwinds of
    *other* attempts don't perturb it. The exit monitor reads cost basis +
    entry fees from this struct.
    """
    basket_id: str                              # f"{event_slug}-{entered_ts.isoformat()}"
    entered_ts: datetime
    target_basket_size: Decimal                 # contracts per leg at entry
    legs: tuple[LegState, ...]                  # buy fills with per-venue breakdown
    cost_basis_per_share_total: Decimal         # sum_legs(total_buy_cost / target_size_i)
    entry_fees_per_share_total: Decimal         # sum_legs(total_buy_fees / target_size_i)


@dataclass(frozen=True)
class ExitLimitOrder:
    """One leg of an exit basket — a resting limit posted on the venue we bought on."""
    venue: Venue
    outcome_name: str
    market_key: str
    size: Decimal                                # contracts (sell)
    limit_price: Decimal                         # = best_bid + venue_tick_size
    submit_ts: datetime
    order_id: str                                # client-side id used to track + cancel
    # Updated as the limit gets hit. Set frozen=True is fine because these objects
    # are recreated when state changes; consumers use the latest instance.
    filled_size: Decimal = ZERO
    fill_vwap: Decimal = ZERO
    fees_paid: Decimal = ZERO
    final_state: str = "resting"                 # "resting" | "filled" | "partial" | "cancelled"


@dataclass(frozen=True)
class ExitAttempt:
    """One pass of the exit monitor — posted limits OR a blocked evaluation OR
    a fill/cancel update on previously-posted limits."""
    basket_id: str
    ts: datetime
    kind: Literal["blocked", "posted", "reposted", "fill", "cancelled", "escalated", "reverted"]
    coupling_basket_bid_sum: Decimal             # per-share basket bid sum at evaluation
    per_leg_limits: tuple[ExitLimitOrder, ...]
    projected_proceeds_per_share: Decimal
    projected_exit_fees_per_share: Decimal
    projected_net_per_share: Decimal             # proceeds − exit_fees − cost_basis − entry_fees
    required_margin_per_share: Decimal
    blocked_by: str | None = None                # one of the well-known reason codes
    # For `kind == "fill"` and `kind == "cancelled"`: realized aggregates so far.
    realized_proceeds_per_share: Decimal = ZERO
    realized_exit_fees_per_share: Decimal = ZERO
    realized_net_per_share: Decimal = ZERO
    all_legs_filled: bool = False
