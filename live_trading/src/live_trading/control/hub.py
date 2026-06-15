from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class EventHub:
    def __init__(self, queue_size: int = 128) -> None:
        self.queue_size = queue_size
        self._clients: dict[WebSocket, asyncio.Queue[dict[str, Any]]] = {}
        self._topics: dict[WebSocket, set[str]] = defaultdict(lambda: {"*"})
        self._lock = asyncio.Lock()

    async def connect(self, socket: WebSocket) -> asyncio.Queue[dict[str, Any]]:
        await socket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        async with self._lock:
            self._clients[socket] = queue
        return queue

    async def disconnect(self, socket: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(socket, None)
            self._topics.pop(socket, None)

    def subscribe(self, socket: WebSocket, topics: list[str]) -> None:
        self._topics[socket] = set(topics) or {"*"}

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        message = {"topic": topic, "payload": payload}
        async with self._lock:
            clients = list(self._clients.items())
        for socket, queue in clients:
            topics = self._topics.get(socket, {"*"})
            if "*" not in topics and topic not in topics:
                continue
            if queue.full():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass
