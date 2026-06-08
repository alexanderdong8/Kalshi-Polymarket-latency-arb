from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import aiofiles


class JsonlWriter:
    """Append-only JSONL log of every WS message + lifecycle event.

    One file per venue, named `{venue}-{event_slug}-{YYYYMMDD-HHMMSS}.jsonl`. Writes are
    serialized through an asyncio.Lock so concurrent producers don't interleave.
    """

    def __init__(self, log_dir: Path, event_slug: str, venue: str) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        self.path = self.log_dir / f"{venue}-{event_slug}-{ts}.jsonl"
        self.venue = venue
        self._lock = asyncio.Lock()
        self._file = None  # aiofiles handle, set in open()

    async def open(self) -> None:
        self._file = await aiofiles.open(self.path, mode="a", encoding="utf-8")

    async def close(self) -> None:
        if self._file is not None:
            await self._file.close()
            self._file = None

    async def write_event(self, direction: str, payload: Any, *, kind: str = "message") -> None:
        if self._file is None:
            return
        record = {
            "ts_ns": time.time_ns(),
            "venue": self.venue,
            "kind": kind,
            "direction": direction,
            "payload": payload,
        }
        line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
        async with self._lock:
            await self._file.write(line)
            await self._file.flush()


@asynccontextmanager
async def jsonl_writer(log_dir: Path, event_slug: str, venue: str) -> AsyncIterator[JsonlWriter]:
    writer = JsonlWriter(log_dir, event_slug, venue)
    await writer.open()
    try:
        yield writer
    finally:
        await writer.close()
