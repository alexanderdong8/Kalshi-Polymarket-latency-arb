from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..models import BookSnapshot, Venue


@dataclass
class BookStore:
    """In-memory cache of the latest BookSnapshot per (venue, outcome_name).

    Writers call set(); readers call snapshot() to grab a consistent copy.
    """
    _books: dict[tuple[Venue, str], BookSnapshot] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def set(self, book: BookSnapshot) -> None:
        async with self._lock:
            self._books[(book.venue, book.outcome_name)] = book

    async def snapshot(self) -> dict[tuple[Venue, str], BookSnapshot]:
        async with self._lock:
            return dict(self._books)

    async def get(self, venue: Venue, outcome_name: str) -> BookSnapshot | None:
        async with self._lock:
            return self._books.get((venue, outcome_name))
