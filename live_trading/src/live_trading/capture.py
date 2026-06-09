from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import BookState


@dataclass
class L2Capture:
    root: Path
    event_slug: str
    max_queue: int = 50_000
    _queue: asyncio.Queue[dict] = field(init=False)
    _task: asyncio.Task | None = field(default=None, init=False)
    dropped: int = 0
    valid: bool = True
    invalid_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self._queue = asyncio.Queue(maxsize=self.max_queue)

    async def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._writer(), name="l2-capture-writer")

    def record(self, book: BookState) -> None:
        payload = {
            "type": "book",
            "venue": book.venue,
            "market_key": book.market_key,
            "venue_ts": book.venue_ts.isoformat() if book.venue_ts else None,
            "received_ts": book.received_ts.isoformat(),
            "sequence": book.sequence,
            "state": book.state,
            "yes_bids": [[str(level.price), str(level.size)] for level in book.raw_yes_bids],
            "yes_asks": [[str(level.price), str(level.size)] for level in book.raw_yes_asks],
        }
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.dropped += 1
            self.invalidate("capture_queue_overflow")

    def invalidate(self, reason: str) -> None:
        self.valid = False
        if reason not in self.invalid_reasons:
            self.invalid_reasons.append(reason)

    async def close(self) -> None:
        if self._task is None:
            return
        await self._queue.put({"type": "_stop"})
        await self._task
        self._task = None
        metadata = {
            "event": self.event_slug,
            "valid": self.valid,
            "invalid_reasons": self.invalid_reasons,
            "dropped": self.dropped,
        }
        (self.root / f"{self.event_slug}.metadata.json").write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )

    async def _writer(self) -> None:
        path = self.root / f"{self.event_slug}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            while True:
                payload = await self._queue.get()
                try:
                    if payload.get("type") == "_stop":
                        return
                    handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
                    handle.flush()
                finally:
                    self._queue.task_done()
