from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ..config import Settings
from ..strategy.books import BookStore
from ..strategy.bridge import StrategyBookBridge
from ..strategy.detector import Detector
from ..strategy.fees import FeeConfig
from ..strategy.models import EventSpec, OutcomeSpec
from .models import SizePoint


SIZE_GRID = (1, 5, 10, 25, 50, 100, 250)


async def build_strategy_books(event: EventSpec, snapshots: list[object]) -> dict:
    store = BookStore()
    bridge = StrategyBookBridge(event, store)
    for snapshot in snapshots:
        await bridge.apply(snapshot)
    return await store.snapshot()


def event_spec(name: str, mappings: list[object]) -> EventSpec:
    return EventSpec(
        name=name,
        description=None,
        outcomes=tuple(
            OutcomeSpec(
                name=mapping.name,
                kalshi_ticker=mapping.kalshi_ticker,
                polymarket_slug=mapping.polymarket_us_slug,
                polymarket_side=mapping.polymarket_side,
            )
            for mapping in mappings
        ),
    )


def evaluate_size_curve(
    event: EventSpec,
    books: dict,
    settings: Settings,
    *,
    maximum_size: int | None = None,
) -> list[SizePoint]:
    maximum = max(1, maximum_size or int(settings.trade_size))
    sizes = sorted({size for size in (*SIZE_GRID, maximum) if size <= max(maximum, 250)})
    points = []
    for size in sizes:
        detector = Detector(
            event=event,
            target_size=Decimal(size),
            fee_cfg=FeeConfig.default(),
            staleness_ms=float(settings.stale_after_seconds * Decimal("1000")),
        )
        evaluation = detector.evaluate(books)
        executable_profit = max(Decimal("0"), evaluation.edge_per_share) * evaluation.achievable_size
        points.append(
            SizePoint(
                requested_size=Decimal(size),
                achievable_size=evaluation.achievable_size,
                net_edge_per_share=evaluation.edge_per_share,
                executable_profit=executable_profit,
                max_slippage_per_share=evaluation.max_slippage_per_share,
                fresh=not evaluation.any_stale,
                complete_books=not evaluation.any_empty,
                price_bounds_ok=not evaluation.any_extreme_price,
                chosen_venues=tuple(leg.chosen_venue for leg in evaluation.legs),
            )
        )
    return points


def classify_event_state(
    start_time: datetime | None,
    close_time: datetime | None,
    *,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    if start_time and start_time <= now and (not close_time or now < close_time):
        return "in_play"
    if start_time and now < start_time:
        return "pregame"
    if close_time:
        remaining = (close_time - now).total_seconds()
        if 0 < remaining <= 86400:
            return "near_settlement"
        if remaining > 30 * 86400:
            return "long_duration"
    return "lifecycle"
