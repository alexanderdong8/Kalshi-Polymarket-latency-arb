from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..models import BookState, Venue
from ..venues.kalshi import KalshiClient
from ..venues.polymarket_us import PolymarketUSClient
from .cache import CacheUpdate, SharedBookCache
from .subscriptions import MarketKey, SubscriptionRegistry


@dataclass
class _Consumer:
    markets: set[MarketKey]
    queue: asyncio.Queue[CacheUpdate]


class SharedMarketDataGateway:
    """One logical feed per venue with deduplicated consumer subscriptions."""

    def __init__(
        self,
        settings: Settings,
        *,
        queue_size: int = 512,
    ) -> None:
        self.settings = settings
        self.queue_size = queue_size
        self.registry = SubscriptionRegistry()
        self.cache = SharedBookCache()
        self._consumers: dict[str, _Consumer] = {}
        self._venue_tasks: dict[Venue, asyncio.Task[None]] = {}
        self._active_keys: dict[Venue, tuple[str, ...]] = {
            "kalshi": (),
            "polymarket_us": (),
        }
        self._revision_event = asyncio.Event()
        self._supervisor: asyncio.Task[None] | None = None
        self._listeners: list[Any] = []
        self.health: dict[str, Any] = {
            "kalshi_updates": 0,
            "polymarket_us_updates": 0,
            "sequence_gaps": 0,
            "reconnects": 0,
            "subscription_restarts": 0,
        }

    async def start(self) -> None:
        if self._supervisor is None:
            self._supervisor = asyncio.create_task(
                self._run_supervisor(), name="shared-market-data-supervisor"
            )

    async def stop(self) -> None:
        if self._supervisor is not None:
            self._supervisor.cancel()
        for task in self._venue_tasks.values():
            task.cancel()
        await asyncio.gather(
            *self._venue_tasks.values(),
            *([self._supervisor] if self._supervisor else []),
            return_exceptions=True,
        )
        self._venue_tasks.clear()
        self._supervisor = None

    def subscribe(
        self, consumer_id: str, markets: set[MarketKey]
    ) -> asyncio.Queue[CacheUpdate]:
        consumer = self._consumers.get(consumer_id)
        if consumer is None:
            consumer = _Consumer(markets=set(), queue=asyncio.Queue(self.queue_size))
            self._consumers[consumer_id] = consumer
        consumer.markets = set(markets)
        if self.registry.replace(consumer_id, markets):
            self._revision_event.set()
        return consumer.queue

    def add_listener(self, listener: Any) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, consumer_id: str) -> None:
        self._consumers.pop(consumer_id, None)
        if self.registry.remove(consumer_id):
            self._revision_event.set()

    async def _run_supervisor(self) -> None:
        while True:
            await self._revision_event.wait()
            self._revision_event.clear()
            await self._restart_changed_venues()

    async def _restart_changed_venues(self) -> None:
        for venue in ("kalshi", "polymarket_us"):
            typed_venue: Venue = venue
            desired = sorted(key for _, key in self.registry.active(typed_venue))
            desired_tuple = tuple(desired)
            if self._active_keys[typed_venue] == desired_tuple:
                continue
            task = self._venue_tasks.pop(typed_venue, None)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await self.cache.invalidate_venue(typed_venue)
            if desired:
                self.health["subscription_restarts"] += 1
                self._venue_tasks[typed_venue] = asyncio.create_task(
                    self._run_venue(typed_venue, desired),
                    name=f"shared-{typed_venue}-stream",
                )
            self._active_keys[typed_venue] = desired_tuple

    async def _run_venue(self, venue: Venue, keys: list[str]) -> None:
        def on_reconnect(_: str = "") -> None:
            self.health["reconnects"] += 1

        if venue == "kalshi":
            stream = KalshiClient(self.settings).stream_orderbooks(
                keys, on_reconnect=on_reconnect
            )
        else:
            stream = PolymarketUSClient(self.settings).stream_orderbooks(
                keys, on_reconnect=on_reconnect
            )
        async for book in stream:
            await self.publish(book)

    async def publish(self, book: BookState) -> None:
        update = await self.cache.apply(book)
        self.health[f"{book.venue}_updates"] += 1
        if update.gap:
            self.health["sequence_gaps"] += 1
        market = (book.venue, book.market_key)
        for consumer_id in self.registry.consumers_for(market):
            consumer = self._consumers.get(consumer_id)
            if consumer is None:
                continue
            _put_latest(consumer.queue, update)
        for listener in self._listeners:
            listener(update)


def _put_latest(queue: asyncio.Queue[CacheUpdate], update: CacheUpdate) -> None:
    if queue.full():
        with suppress(asyncio.QueueEmpty):
            queue.get_nowait()
            queue.task_done()
    with suppress(asyncio.QueueFull):
        queue.put_nowait(update)
