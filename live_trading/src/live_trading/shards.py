from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import suppress
from typing import TypeVar


T = TypeVar("T")
K = TypeVar("K")


def shard_items(items: Iterable[K], size: int = 100) -> list[list[K]]:
    if size <= 0:
        raise ValueError("Shard size must be positive.")
    values = list(dict.fromkeys(items))
    return [values[index : index + size] for index in range(0, len(values), size)]


async def merge_sharded_streams(
    shards: list[K],
    worker: Callable[[K, int], AsyncIterator[T]],
    *,
    on_reconnect: Callable[[str], None] | None = None,
    queue_maxsize: int = 10_000,
) -> AsyncIterator[T]:
    if not shards:
        return

    queue: asyncio.Queue[T] = asyncio.Queue(maxsize=queue_maxsize)
    tasks = [
        asyncio.create_task(
            _run_shard(shard, shard_id, worker, queue, on_reconnect),
            name=f"market-data-shard-{shard_id}",
        )
        for shard_id, shard in enumerate(shards)
    ]
    try:
        while True:
            yield await queue.get()
            queue.task_done()
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


async def _run_shard(
    shard: K,
    shard_id: int,
    worker: Callable[[K, int], AsyncIterator[T]],
    queue: asyncio.Queue[T],
    on_reconnect: Callable[[str], None] | None,
) -> None:
    failures = 0
    while True:
        try:
            async for item in worker(shard, shard_id):
                failures = 0
                await queue.put(item)
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            if on_reconnect:
                on_reconnect(f"shard-{shard_id}")
            await asyncio.sleep(min(30.0, 0.5 * (2 ** min(failures, 6))))


async def cancel_tasks(tasks: Iterable[Awaitable[object]]) -> None:
    running = [task for task in tasks if isinstance(task, asyncio.Task)]
    for task in running:
        task.cancel()
    for task in running:
        with suppress(asyncio.CancelledError):
            await task
