from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from .books import BookStore
from .depth import WalkResult, walk_book
from .fees import FeeConfig, venue_taker_fee_total
from .models import BookSnapshot, EventSpec, Venue

ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_ENTRY_THRESHOLD = Decimal("0.98")
DEFAULT_MIN_LEG_BID = Decimal("0.02")
DEFAULT_MAX_LEG_BID = Decimal("0.98")
DEFAULT_SLIPPAGE_BUFFER = Decimal("0.005")     # dollars per share, added to entry cost
DEFAULT_DEPTH_HAIRCUT = Decimal("0.7")         # fraction of displayed depth treated as real
# Velocity threshold below which a tick counts as "non-widening" (i.e. negative, flat,
# or barely-positive noise). Units: dollars-per-share per second of basket edge change.
# At 10 Hz, 0.01/sec = ~0.1¢/share/tick — tight; tolerates only sub-cent drift,
# rejects real per-tick widening (a 1¢ ask flick = ~10x this).
DEFAULT_NEAR_ZERO_THRESHOLD = Decimal("0.01")


@dataclass(frozen=True)
class LegEvaluation:
    outcome_name: str
    chosen_venue: Venue | None
    vwap: Decimal
    fee_total: Decimal
    fee_per_share: Decimal
    filled: Decimal
    target: Decimal
    fully_filled: bool
    levels_consumed: int
    # Top-of-book best ask on the chosen venue (what we'd pay if size fits at top).
    chosen_top_ask: Decimal | None
    # vwap - chosen_top_ask: zero when target fits entirely at best level, positive when walked deeper.
    slippage_per_share: Decimal
    # True iff filling target_size required consuming more than the best level.
    depth_walked: bool
    # Best yes-bid visible across venues, used for the extreme-price filter.
    best_bid_across_venues: Decimal | None
    bid_in_range: bool
    kalshi_top_ask: Decimal | None
    polymarket_top_ask: Decimal | None
    kalshi_book_age_ms: float | None
    polymarket_book_age_ms: float | None


@dataclass(frozen=True)
class BasketEvaluation:
    ts: datetime
    target_size: Decimal
    achievable_size: Decimal
    legs: tuple[LegEvaluation, ...]
    basket_cost_per_share: Decimal       # sum of leg vwaps
    total_fees_per_share: Decimal        # sum of leg fee/share
    entry_cost_per_share: Decimal        # basket_cost + total_fees
    edge_per_share: Decimal              # entry_threshold - entry_cost (positive = profitable)
    entry_threshold: Decimal
    slippage_buffer_per_share: Decimal
    depth_haircut: Decimal
    any_empty: bool
    any_stale: bool
    any_extreme_price: bool       # any leg's bid > max_leg_bid or < min_leg_bid
    any_depth_walked: bool        # any leg consumed > 1 level to fill target
    max_slippage_per_share: Decimal
    max_book_age_ms: float

    @property
    def basket_cost_total(self) -> Decimal:
        return self.basket_cost_per_share * self.achievable_size

    @property
    def entry_cost_total(self) -> Decimal:
        return self.entry_cost_per_share * self.achievable_size

    @property
    def edge_total(self) -> Decimal:
        return self.edge_per_share * self.achievable_size


@dataclass(frozen=True)
class FireEvent:
    ts: datetime
    evaluation: BasketEvaluation
    velocity_per_share_per_sec: Decimal
    consecutive_non_widening_ticks: int
    gap_window_opened_ts: datetime | None = None
    gap_window_age_ms_at_fire: float | None = None


def _age_ms(book: BookSnapshot | None, now: datetime) -> float | None:
    if book is None:
        return None
    return book.age_seconds(now) * 1000.0


def _top_ask(book: BookSnapshot | None) -> Decimal | None:
    if book is None or not book.yes_asks:
        return None
    return book.yes_asks[0].price


def _top_bid(book: BookSnapshot | None) -> Decimal | None:
    if book is None or not book.yes_bids:
        return None
    return book.yes_bids[0].price


def _walk_or_none(
    book: BookSnapshot | None,
    size: Decimal,
    size_multiplier: Decimal,
) -> WalkResult | None:
    if book is None or not book.yes_asks:
        return None
    return walk_book(book.yes_asks, size, side="ask", size_multiplier=size_multiplier)


@dataclass
class GapWindowTracker:
    """Tracks open/close transitions of the basket edge crossing zero.

    Used to measure how long a profitable window persists in wall-clock time.
    Each FireEvent carries the current window-opened timestamp so the trade
    journal can compute gap_window_age_ms_at_fire and (after the attempt
    completes) how long the window survived past fire.
    """
    current_window_opened_ts: datetime | None = None
    last_closed_window_opened_ts: datetime | None = None
    last_closed_window_closed_ts: datetime | None = None
    last_closed_window_duration_ms: float | None = None

    def update(self, edge_per_share: Decimal, ts: datetime) -> None:
        if edge_per_share > ZERO:
            if self.current_window_opened_ts is None:
                self.current_window_opened_ts = ts
        else:
            if self.current_window_opened_ts is not None:
                self.last_closed_window_opened_ts = self.current_window_opened_ts
                self.last_closed_window_closed_ts = ts
                self.last_closed_window_duration_ms = (
                    (ts - self.current_window_opened_ts).total_seconds() * 1000.0
                )
                self.current_window_opened_ts = None


@dataclass
class MomentumTracker:
    """Tracks consecutive-pair velocity of basket edge_per_share between detector ticks.

    `edge_per_share` is the basket-level signal — entry_threshold minus
    (basket_cost + total_fees) where basket_cost is the sum of cheapest-VWAP
    per leg across both venues. So the velocity here is the rate of change of
    the cross-venue gap itself, not any single market's price.

    Each push computes velocity = (edge_now - edge_prev) / (t_now - t_prev) — the
    instantaneous slope between this sample and the immediately preceding one.
    A tick counts as "non-widening" if `velocity <= near_zero_threshold`:
      - strictly negative → gap actively closing
      - exactly zero → gap flat
      - small positive (≤ threshold) → near-zero noise treated as flat
    Anything above the threshold (gap genuinely widening) resets the streak.

    The previous sample is discarded if it's older than
    `max_velocity_age_seconds` (e.g. after a long gap from a stale-book period);
    in that case we wait for a fresh pair before counting.
    """
    max_velocity_age_seconds: float = 0.5
    near_zero_threshold: Decimal = ZERO
    _last_sample: tuple[float, Decimal] | None = None
    _last_velocity: Decimal | None = None
    _non_widening_streak: int = 0

    def push(self, edge_per_share: Decimal, now_mono: float | None = None) -> None:
        now_mono = time.monotonic() if now_mono is None else now_mono
        prev = self._last_sample
        self._last_sample = (now_mono, edge_per_share)
        if prev is None:
            self._non_widening_streak = 0
            self._last_velocity = None
            return
        dt = now_mono - prev[0]
        if dt <= 0 or dt > self.max_velocity_age_seconds:
            self._non_widening_streak = 0
            self._last_velocity = None
            return
        vel = (edge_per_share - prev[1]) / Decimal(str(dt))
        self._last_velocity = vel
        if vel <= self.near_zero_threshold:
            self._non_widening_streak += 1
        else:
            self._non_widening_streak = 0

    def velocity(self) -> Decimal | None:
        """Last computed sample-to-sample velocity. None until two valid samples
        have been pushed within `max_velocity_age_seconds` of each other."""
        return self._last_velocity

    def consecutive_non_widening(self) -> int:
        return self._non_widening_streak

    def reset(self) -> None:
        self._last_sample = None
        self._last_velocity = None
        self._non_widening_streak = 0


@dataclass
class Detector:
    """Pure-ish detector: evaluate(books) → BasketEvaluation; fire condition is then
    `edge > 0` AND `momentum.velocity ≤ 0` AND a small consecutive-tick filter.

    The fire condition mirrors the strategy spec:
      enter_cost = basket_vwap_sum + entry_fees_sum
      fire if enter_cost < entry_threshold (default $0.98)
            AND the gap is not still widening (velocity ≤ 0 for ≥ K ticks)
    No exit-side math is included by design.
    """
    event: EventSpec
    target_size: Decimal
    fee_cfg: FeeConfig = field(default_factory=FeeConfig.default)
    entry_threshold: Decimal = DEFAULT_ENTRY_THRESHOLD
    slippage_buffer_per_share: Decimal = DEFAULT_SLIPPAGE_BUFFER
    depth_haircut: Decimal = DEFAULT_DEPTH_HAIRCUT
    staleness_ms: float = 2000.0
    momentum_window_seconds: float = 0.5
    min_non_widening_ticks: int = 2
    near_zero_threshold: Decimal = DEFAULT_NEAR_ZERO_THRESHOLD
    min_leg_bid: Decimal = DEFAULT_MIN_LEG_BID
    max_leg_bid: Decimal = DEFAULT_MAX_LEG_BID
    momentum: MomentumTracker = field(init=False)
    gap_tracker: GapWindowTracker = field(init=False)

    def __post_init__(self) -> None:
        if self.slippage_buffer_per_share < ZERO:
            raise ValueError(
                f"slippage_buffer_per_share must be >= 0, got {self.slippage_buffer_per_share!r}"
            )
        if self.depth_haircut <= ZERO or self.depth_haircut > ONE:
            raise ValueError(
                f"depth_haircut must be in (0, 1], got {self.depth_haircut!r}"
            )
        self.momentum = MomentumTracker(
            max_velocity_age_seconds=self.momentum_window_seconds,
            near_zero_threshold=self.near_zero_threshold,
        )
        self.gap_tracker = GapWindowTracker()

    def evaluate(
        self,
        books: dict[tuple[Venue, str], BookSnapshot],
        now: datetime | None = None,
    ) -> BasketEvaluation:
        now = now or datetime.now(timezone.utc)
        leg_evals: list[LegEvaluation] = []
        max_age = 0.0
        any_stale = False
        any_empty = False
        any_extreme_price = False
        any_depth_walked = False
        max_slippage = ZERO

        per_leg_max_fill: list[Decimal] = []

        for outcome in self.event.outcomes:
            k_book = books.get(("kalshi", outcome.name))
            p_book = books.get(("polymarket_us", outcome.name))
            k_walk = _walk_or_none(k_book, self.target_size, self.depth_haircut)
            p_walk = _walk_or_none(p_book, self.target_size, self.depth_haircut)

            k_age = _age_ms(k_book, now)
            p_age = _age_ms(p_book, now)
            for age in (k_age, p_age):
                if age is None:
                    continue
                if age > max_age:
                    max_age = age
                if age > self.staleness_ms:
                    any_stale = True

            # Per-leg best bid across venues, used for the extreme-price filter.
            k_bid = _top_bid(k_book)
            p_bid = _top_bid(p_book)
            visible_bids = [b for b in (k_bid, p_bid) if b is not None]
            best_bid = max(visible_bids) if visible_bids else None
            bid_in_range = (
                best_bid is not None
                and self.min_leg_bid <= best_bid <= self.max_leg_bid
            )
            if best_bid is None or not bid_in_range:
                any_extreme_price = True

            candidates: list[tuple[Venue, WalkResult, BookSnapshot]] = []
            if k_walk and not k_walk.empty and k_book is not None:
                candidates.append(("kalshi", k_walk, k_book))
            if p_walk and not p_walk.empty and p_book is not None:
                candidates.append(("polymarket_us", p_walk, p_book))

            if not candidates:
                any_empty = True
                leg_evals.append(LegEvaluation(
                    outcome_name=outcome.name,
                    chosen_venue=None,
                    vwap=ZERO, fee_total=ZERO, fee_per_share=ZERO,
                    filled=ZERO, target=self.target_size, fully_filled=False,
                    levels_consumed=0,
                    chosen_top_ask=None,
                    slippage_per_share=ZERO,
                    depth_walked=False,
                    best_bid_across_venues=best_bid,
                    bid_in_range=bid_in_range,
                    kalshi_top_ask=_top_ask(k_book),
                    polymarket_top_ask=_top_ask(p_book),
                    kalshi_book_age_ms=k_age,
                    polymarket_book_age_ms=p_age,
                ))
                per_leg_max_fill.append(ZERO)
                continue

            chosen_venue, chosen_walk, chosen_book = min(candidates, key=lambda c: c[1].vwap)
            per_leg_max_fill.append(max(c[1].filled for c in candidates))
            chosen_top = _top_ask(chosen_book)
            slippage = (
                chosen_walk.vwap - chosen_top
                if chosen_top is not None and chosen_walk.vwap > chosen_top
                else ZERO
            )
            depth_walked = chosen_walk.levels_consumed > 1
            if depth_walked:
                any_depth_walked = True
            if slippage > max_slippage:
                max_slippage = slippage

            fee_total = venue_taker_fee_total(
                chosen_venue, chosen_walk.vwap, chosen_walk.filled, self.fee_cfg
            )
            fee_per_share = fee_total / chosen_walk.filled if chosen_walk.filled > 0 else ZERO
            leg_evals.append(LegEvaluation(
                outcome_name=outcome.name,
                chosen_venue=chosen_venue,
                vwap=chosen_walk.vwap,
                fee_total=fee_total,
                fee_per_share=fee_per_share,
                filled=chosen_walk.filled,
                target=self.target_size,
                fully_filled=chosen_walk.fully_filled,
                levels_consumed=chosen_walk.levels_consumed,
                chosen_top_ask=chosen_top,
                slippage_per_share=slippage,
                depth_walked=depth_walked,
                best_bid_across_venues=best_bid,
                bid_in_range=bid_in_range,
                kalshi_top_ask=_top_ask(k_book),
                polymarket_top_ask=_top_ask(p_book),
                kalshi_book_age_ms=k_age,
                polymarket_book_age_ms=p_age,
            ))

        achievable = min(per_leg_max_fill) if per_leg_max_fill else ZERO
        basket_cost = sum((leg.vwap for leg in leg_evals if leg.chosen_venue), ZERO)
        total_fees = sum((leg.fee_per_share for leg in leg_evals if leg.chosen_venue), ZERO)
        entry_cost = basket_cost + total_fees + self.slippage_buffer_per_share
        edge = self.entry_threshold - entry_cost

        return BasketEvaluation(
            ts=now,
            target_size=self.target_size,
            achievable_size=achievable,
            legs=tuple(leg_evals),
            basket_cost_per_share=basket_cost,
            total_fees_per_share=total_fees,
            entry_cost_per_share=entry_cost,
            edge_per_share=edge,
            entry_threshold=self.entry_threshold,
            slippage_buffer_per_share=self.slippage_buffer_per_share,
            depth_haircut=self.depth_haircut,
            any_empty=any_empty,
            any_stale=any_stale,
            any_extreme_price=any_extreme_price,
            any_depth_walked=any_depth_walked,
            max_slippage_per_share=max_slippage,
            max_book_age_ms=max_age,
        )

    def tick(
        self,
        books: dict[tuple[Venue, str], BookSnapshot],
        now: datetime | None = None,
    ) -> tuple[BasketEvaluation, FireEvent | None]:
        """Evaluate once + update the momentum tracker. Returns a FireEvent if
        all entry conditions are satisfied on this tick."""
        ev = self.evaluate(books, now)
        # Only feed momentum samples when the basket is fully tradable;
        # empty/stale/extreme-price legs would inject noise into the velocity estimate.
        if not (ev.any_empty or ev.any_stale or ev.any_extreme_price):
            self.momentum.push(ev.edge_per_share, ev.ts.timestamp())
            self.gap_tracker.update(ev.edge_per_share, ev.ts)
        else:
            self.momentum.reset()

        fire: FireEvent | None = None
        if (
            not ev.any_empty
            and not ev.any_stale
            and not ev.any_extreme_price
            and ev.achievable_size > ZERO
            and ev.edge_per_share > ZERO
            and self.momentum.consecutive_non_widening() >= self.min_non_widening_ticks
        ):
            vel = self.momentum.velocity() or ZERO
            gap_opened = self.gap_tracker.current_window_opened_ts
            gap_age_ms: float | None = None
            if gap_opened is not None:
                gap_age_ms = (ev.ts - gap_opened).total_seconds() * 1000.0
            fire = FireEvent(
                ts=ev.ts,
                evaluation=ev,
                velocity_per_share_per_sec=vel,
                consecutive_non_widening_ticks=self.momentum.consecutive_non_widening(),
                gap_window_opened_ts=gap_opened,
                gap_window_age_ms_at_fire=gap_age_ms,
            )
        return ev, fire


def fire_to_jsonl_payload(fire: FireEvent) -> dict:
    ev = fire.evaluation
    return {
        "ts": ev.ts.isoformat(),
        "target_size": str(ev.target_size),
        "achievable_size": str(ev.achievable_size),
        "basket_cost_per_share": str(ev.basket_cost_per_share),
        "total_fees_per_share": str(ev.total_fees_per_share),
        "entry_cost_per_share": str(ev.entry_cost_per_share),
        "edge_per_share": str(ev.edge_per_share),
        "entry_threshold": str(ev.entry_threshold),
        "slippage_buffer_per_share": str(ev.slippage_buffer_per_share),
        "depth_haircut": str(ev.depth_haircut),
        "edge_total": str(ev.edge_total),
        "max_book_age_ms": ev.max_book_age_ms,
        "any_depth_walked": ev.any_depth_walked,
        "max_slippage_per_share": str(ev.max_slippage_per_share),
        "velocity_per_share_per_sec": str(fire.velocity_per_share_per_sec),
        "non_widening_ticks": fire.consecutive_non_widening_ticks,
        "gap_window_opened_ts": (
            fire.gap_window_opened_ts.isoformat() if fire.gap_window_opened_ts else None
        ),
        "gap_window_age_ms_at_fire": fire.gap_window_age_ms_at_fire,
        "legs": [
            {
                "outcome": leg.outcome_name,
                "venue": leg.chosen_venue,
                "vwap": str(leg.vwap),
                "chosen_top_ask": str(leg.chosen_top_ask) if leg.chosen_top_ask is not None else None,
                "slippage_per_share": str(leg.slippage_per_share),
                "depth_walked": leg.depth_walked,
                "filled": str(leg.filled),
                "target": str(leg.target),
                "fully_filled": leg.fully_filled,
                "levels_consumed": leg.levels_consumed,
                "fee_total": str(leg.fee_total),
                "fee_per_share": str(leg.fee_per_share),
                "best_bid_across_venues": (
                    str(leg.best_bid_across_venues)
                    if leg.best_bid_across_venues is not None
                    else None
                ),
                "bid_in_range": leg.bid_in_range,
                "kalshi_top_ask": str(leg.kalshi_top_ask) if leg.kalshi_top_ask is not None else None,
                "polymarket_top_ask": str(leg.polymarket_top_ask) if leg.polymarket_top_ask is not None else None,
                "kalshi_book_age_ms": leg.kalshi_book_age_ms,
                "polymarket_book_age_ms": leg.polymarket_book_age_ms,
            }
            for leg in ev.legs
        ],
    }
