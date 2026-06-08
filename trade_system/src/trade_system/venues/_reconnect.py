from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass


@dataclass
class Backoff:
    """Exponential backoff with full jitter and self-reset on long-lived connections."""
    initial: float = 1.0
    cap: float = 30.0
    reset_after_seconds: float = 60.0
    _current: float = 1.0
    _connect_started: float = 0.0

    def mark_connected(self) -> None:
        self._connect_started = time.monotonic()

    def mark_disconnected(self) -> None:
        if self._connect_started and time.monotonic() - self._connect_started >= self.reset_after_seconds:
            self._current = self.initial

    async def sleep(self) -> float:
        delay = random.uniform(0, self._current)
        await asyncio.sleep(delay)
        self._current = min(self.cap, max(self.initial, self._current * 2))
        return delay
