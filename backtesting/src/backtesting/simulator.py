from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from live_trading.strategy.depth import walk_book
from live_trading.strategy.detector import Detector
from live_trading.strategy.fees import FeeConfig, venue_taker_fee_total
from live_trading.strategy.manifest import EventManifest
from live_trading.strategy.models import BookSnapshot

from .models import FillRecord, ReplayUpdate, SimulationResult

ZERO = Decimal("0")
STARTING_CASH = Decimal("1000")


def run_delay_matrix(
    manifest: EventManifest,
    updates: list[ReplayUpdate],
    *,
    delays_ms: tuple[int, ...] = (50, 250, 500, 1000),
    target_size: Decimal = Decimal("100"),
    strict_models: tuple[str, ...] = ("maker", "price_passes"),
) -> list[SimulationResult]:
    return [
        simulate(
            manifest,
            updates,
            delay_ms=delay,
            fill_model=model,
            target_size=target_size,
        )
        for delay in delays_ms
        for model in strict_models
    ]


def simulate(
    manifest: EventManifest,
    updates: list[ReplayUpdate],
    *,
    delay_ms: int,
    fill_model: str,
    target_size: Decimal,
) -> SimulationResult:
    if fill_model not in {"maker", "price_passes"}:
        raise ValueError(f"Unknown fill model: {fill_model}")
    books: dict[tuple[str, str], BookSnapshot] = {}
    latest_poly_bps = next(
        (update.fee_rate_bps for update in updates if update.fee_rate_bps is not None),
        None,
    )
    if latest_poly_bps is None:
        raise ValueError(
            "PMXT replay contains no Polymarket fee_rate_bps. "
            "Refusing to substitute Polymarket US fee assumptions."
        )
    fee_source = "pmxt_fee_rate_bps"
    detector = Detector(
        manifest.event,
        target_size,
        fee_cfg=FeeConfig(
            polymarket_us_taker_theta=latest_poly_bps / Decimal("10000")
        ),
        staleness_ms=2000,
    )
    cash = STARTING_CASH
    fills: list[FillRecord] = []
    entries = 0
    completed = 0
    rejected = 0
    pending_fire: datetime | None = None
    pending_prices: dict[str, Decimal] = {}
    holding = False
    holding_fills: list[FillRecord] = []
    holding_entry_cost = ZERO
    exit_limits: dict[tuple[str, str], Decimal] | None = None

    if not updates:
        raise ValueError("Replay has no updates.")
    tick = updates[0].timestamp_received
    end = updates[-1].timestamp_received
    index = 0
    while tick <= end:
        while index < len(updates) and updates[index].timestamp_received <= tick:
            update = updates[index]
            books[(update.book.venue, update.book.outcome_name)] = update.book
            if update.fee_rate_bps is not None:
                latest_poly_bps = update.fee_rate_bps
                detector.fee_cfg = FeeConfig(
                    polymarket_us_taker_theta=latest_poly_bps / Decimal("10000")
                )
            index += 1

        evaluation, fire = detector.tick(books, tick)
        if fire is not None and not holding and pending_fire is None:
            entries += 1
            pending_fire = tick + timedelta(milliseconds=delay_ms)
            pending_prices = {
                leg.outcome_name: leg.chosen_top_ask or leg.vwap for leg in evaluation.legs
            }

        if pending_fire is not None and tick >= pending_fire:
            result = _execute_entry(
                manifest,
                books,
                target_size,
                cash,
                tick,
                fill_model,
                pending_prices,
                detector.fee_cfg,
            )
            pending_fire = None
            pending_prices = {}
            if result is None:
                rejected += 1
            else:
                cost, entry_fills = result
                cash -= cost
                fills.extend(entry_fills)
                holding_fills = entry_fills
                holding_entry_cost = cost
                holding = True
                completed += 1
        if holding:
            if exit_limits is None:
                exit_limits = _plan_early_exit(
                    books,
                    holding_fills,
                    holding_entry_cost,
                    target_size,
                    detector.fee_cfg,
                )
            elif _exit_limits_filled(books, exit_limits, fill_model):
                proceeds, exit_fills = _fill_early_exit(
                    books,
                    exit_limits,
                    target_size,
                    tick,
                    fill_model,
                    detector.fee_cfg,
                )
                cash += proceeds
                fills.extend(exit_fills)
                holding = False
                holding_fills = []
                holding_entry_cost = ZERO
                exit_limits = None
        tick += timedelta(milliseconds=100)

    # Complete baskets are exhaustive and settle for $1 per basket share.
    if holding:
        cash += target_size

    return SimulationResult(
        delay_ms=delay_ms,
        fill_model=fill_model,
        starting_cash=STARTING_CASH,
        ending_cash=cash,
        total_money_gained=cash - STARTING_CASH,
        entries=entries,
        completed_baskets=completed,
        rejected_entries=rejected,
        fills=tuple(fills),
        fee_source=fee_source,
    )


def _execute_entry(
    manifest: EventManifest,
    books: dict[tuple[str, str], BookSnapshot],
    size: Decimal,
    cash: Decimal,
    timestamp: datetime,
    fill_model: str,
    signaled_prices: dict[str, Decimal],
    fee_cfg: FeeConfig,
) -> tuple[Decimal, list[FillRecord]] | None:
    plans: list[tuple[str, str, Decimal, Decimal, Decimal]] = []
    for outcome in manifest.event.outcomes:
        choices = []
        for venue in ("kalshi", "polymarket_us"):
            book = books.get((venue, outcome.name))
            if book is None:
                continue
            walk = walk_book(book.yes_asks, size, side="ask", size_multiplier=Decimal("0.7"))
            if not walk.fully_filled:
                continue
            if fill_model == "price_passes":
                signaled = signaled_prices.get(outcome.name)
                if signaled is None or not book.yes_asks or book.yes_asks[0].price >= signaled:
                    continue
            fee = venue_taker_fee_total(venue, walk.vwap, size, fee_cfg)
            choices.append((venue, walk.vwap, fee))
        if not choices:
            return None
        venue, price, fee = min(choices, key=lambda row: row[1] + row[2] / size)
        plans.append((outcome.name, venue, size, price, fee))
    total = sum((size * price + fee for _, _, size, price, fee in plans), ZERO)
    if total > cash or total >= size:
        return None
    return total, [
        FillRecord(timestamp, outcome, venue, "buy", size, price, fee, fill_model)
        for outcome, venue, size, price, fee in plans
    ]


def _plan_early_exit(
    books: dict[tuple[str, str], BookSnapshot],
    entry_fills: list[FillRecord],
    entry_cost: Decimal,
    size: Decimal,
    fee_cfg: FeeConfig,
) -> dict[tuple[str, str], Decimal] | None:
    limits: dict[tuple[str, str], Decimal] = {}
    proceeds = ZERO
    fees = ZERO
    for fill in entry_fills:
        book = books.get((fill.venue, fill.outcome))
        if book is None or not book.yes_bids or not book.yes_asks:
            return None
        tick = _observed_tick(book)
        limit = book.yes_bids[0].price + tick
        if limit >= book.yes_asks[0].price:
            return None
        limits[(fill.venue, fill.outcome)] = limit
        proceeds += limit * size
        fees += venue_taker_fee_total(fill.venue, limit, size, fee_cfg)
    if sum(limits.values(), ZERO) < Decimal("0.99"):
        return None
    if proceeds - fees - entry_cost <= Decimal("0.01") * size:
        return None
    return limits


def _exit_limits_filled(
    books: dict[tuple[str, str], BookSnapshot],
    limits: dict[tuple[str, str], Decimal],
    fill_model: str,
) -> bool:
    for key, limit in limits.items():
        book = books.get(key)
        if book is None or not book.yes_bids:
            return False
        best_bid = book.yes_bids[0].price
        if fill_model == "price_passes":
            if best_bid <= limit:
                return False
        elif best_bid < limit:
            return False
    return True


def _fill_early_exit(
    books: dict[tuple[str, str], BookSnapshot],
    limits: dict[tuple[str, str], Decimal],
    size: Decimal,
    timestamp: datetime,
    fill_model: str,
    fee_cfg: FeeConfig,
) -> tuple[Decimal, list[FillRecord]]:
    proceeds = ZERO
    fills = []
    for (venue, outcome), limit in limits.items():
        fee = venue_taker_fee_total(venue, limit, size, fee_cfg)
        proceeds += limit * size - fee
        fills.append(FillRecord(timestamp, outcome, venue, "sell", size, limit, fee, fill_model))
    return proceeds, fills


def _observed_tick(book: BookSnapshot) -> Decimal:
    gaps = []
    for levels in (book.yes_bids, book.yes_asks):
        prices = sorted({level.price for level in levels})
        gaps.extend(right - left for left, right in zip(prices, prices[1:]) if right > left)
    return min(gaps) if gaps else Decimal("0.01")


def result_payload(result: SimulationResult) -> dict[str, Any]:
    payload = asdict(result)
    return _stringify(payload)


def _stringify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify(item) for item in value]
    return value
