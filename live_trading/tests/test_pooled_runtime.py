from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from live_trading.market_data.cache import CacheUpdate, SharedBookCache
from live_trading.market_data.subscriptions import SubscriptionRegistry
from live_trading.models import BookState
from live_trading.workers.assignment import WorkerAssignment
from live_trading.workers.pool import StrategyWorkerPool


def _book(key: str, sequence: int) -> BookState:
    return BookState(
        venue="kalshi",
        market_key=key,
        yes_bid=Decimal("0.40"),
        yes_ask=Decimal("0.41"),
        no_bid=Decimal("0.59"),
        no_ask=Decimal("0.60"),
        received_ts=datetime.now(timezone.utc),
        sequence=sequence,
    )


def test_subscription_registry_deduplicates_paper_and_live() -> None:
    registry = SubscriptionRegistry()
    market = ("kalshi", "KX-EVENT")

    registry.replace("event:paper", {market})
    registry.replace("event:live", {market})

    assert registry.active() == {market}
    assert registry.consumers_for(market) == {"event:paper", "event:live"}
    registry.remove("event:paper")
    assert registry.active() == {market}
    registry.remove("event:live")
    assert registry.active() == set()


def test_shared_cache_rejects_updates_after_sequence_gap_until_snapshot() -> None:
    async def run() -> None:
        cache = SharedBookCache()
        assert (await cache.apply(_book("KX", 1))).valid
        gap = await cache.apply(_book("KX", 3))
        assert gap.gap == "1->3"
        assert not gap.valid
        assert await cache.get("kalshi", "KX") is None
        snapshot = _book("KX", 10)
        object.__setattr__(snapshot, "state", "snapshot")
        assert (await cache.apply(snapshot)).valid
        assert await cache.get("kalshi", "KX") is not None

    asyncio.run(run())


def test_worker_assignment_is_stable() -> None:
    first = WorkerAssignment(4)
    second = WorkerAssignment(4)

    assert first.worker_for("event-1", "paper") == second.worker_for("event-1", "paper")
    assert 0 <= first.worker_for("event-1", "live") < 4


def test_worker_pool_routes_only_affected_sessions_and_isolates_modes() -> None:
    async def run() -> None:
        pool = StrategyWorkerPool(worker_count=2, queue_size=8)
        received: dict[str, list[int]] = {"paper": [], "live": [], "other": []}

        async def paper(update: CacheUpdate) -> None:
            received["paper"].append(update.book.sequence or 0)

        async def live(update: CacheUpdate) -> None:
            received["live"].append(update.book.sequence or 0)

        async def other(update: CacheUpdate) -> None:
            received["other"].append(update.book.sequence or 0)

        pool.register("event:paper", "event", "paper", {("kalshi", "KX")}, paper)
        pool.register("event:live", "event", "live", {("kalshi", "KX")}, live)
        pool.register("other:paper", "other", "paper", {("kalshi", "OTHER")}, other)
        await pool.start()
        pool.dispatch(CacheUpdate(_book("KX", 1), valid=True))
        await asyncio.gather(*(queue.join() for queue in pool.queues))
        await pool.stop()

        assert received == {"paper": [1], "live": [1], "other": []}

    asyncio.run(run())
