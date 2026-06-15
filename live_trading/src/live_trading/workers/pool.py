from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..market_data.cache import CacheUpdate
from ..models import Venue
from .assignment import WorkerAssignment


Handler = Callable[[CacheUpdate], Awaitable[None]]


@dataclass
class _Session:
    session_id: str
    worker_id: int
    markets: set[tuple[Venue, str]]
    handler: Handler


class StrategyWorkerPool:
    """Bounded affected-event dispatch across stable worker shards."""

    def __init__(self, worker_count: int = 2, queue_size: int = 4096) -> None:
        self.assignment = WorkerAssignment(worker_count)
        self.queues = [asyncio.Queue[tuple[str, CacheUpdate]](queue_size) for _ in range(worker_count)]
        self.sessions: dict[str, _Session] = {}
        self.by_market: dict[tuple[Venue, str], set[str]] = defaultdict(set)
        self.tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self.tasks:
            return
        self.tasks = [
            asyncio.create_task(self._run_worker(index), name=f"strategy-worker-{index}")
            for index in range(len(self.queues))
        ]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    def register(
        self,
        session_id: str,
        event_id: str,
        mode: str,
        markets: set[tuple[Venue, str]],
        handler: Handler,
    ) -> int:
        self.unregister(session_id)
        worker_id = self.assignment.worker_for(event_id, mode)
        session = _Session(session_id, worker_id, set(markets), handler)
        self.sessions[session_id] = session
        for market in markets:
            self.by_market[market].add(session_id)
        return worker_id

    def unregister(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        for market in session.markets:
            consumers = self.by_market.get(market)
            if consumers:
                consumers.discard(session_id)
                if not consumers:
                    self.by_market.pop(market, None)

    def dispatch(self, update: CacheUpdate) -> None:
        market = (update.book.venue, update.book.market_key)
        for session_id in self.by_market.get(market, set()):
            session = self.sessions.get(session_id)
            if session is None:
                continue
            _coalesce_put(self.queues[session.worker_id], (session_id, update))

    async def _run_worker(self, worker_id: int) -> None:
        queue = self.queues[worker_id]
        while True:
            session_id, update = await queue.get()
            try:
                session = self.sessions.get(session_id)
                if session is not None:
                    await session.handler(update)
            finally:
                queue.task_done()


def _coalesce_put(
    queue: asyncio.Queue[tuple[str, CacheUpdate]],
    item: tuple[str, CacheUpdate],
) -> None:
    if queue.full():
        with suppress(asyncio.QueueEmpty):
            queue.get_nowait()
            queue.task_done()
    with suppress(asyncio.QueueFull):
        queue.put_nowait(item)
