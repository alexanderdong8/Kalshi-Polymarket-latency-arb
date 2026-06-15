from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..models import BookState, Venue


@dataclass(frozen=True)
class CacheUpdate:
    book: BookState
    valid: bool
    gap: str | None = None


@dataclass
class SharedBookCache:
    _books: dict[tuple[Venue, str], BookState] = field(default_factory=dict)
    _valid: dict[tuple[Venue, str], bool] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def apply(self, book: BookState) -> CacheUpdate:
        key = (book.venue, book.market_key)
        gap = None
        async with self._lock:
            previous = self._books.get(key)
            if (
                previous is not None
                and previous.sequence is not None
                and book.sequence is not None
                and book.sequence > previous.sequence + 1
            ):
                gap = f"{previous.sequence}->{book.sequence}"
                self._valid[key] = False
            if book.state in {"snapshot", "subscribed"} or previous is None:
                self._valid[key] = True
            self._books[key] = book
            valid = self._valid.get(key, True)
        return CacheUpdate(book=book, valid=valid, gap=gap)

    async def get(self, venue: Venue, market_key: str) -> BookState | None:
        async with self._lock:
            book = self._books.get((venue, market_key))
            return book if self._valid.get((venue, market_key), True) else None

    async def snapshot(
        self, markets: set[tuple[Venue, str]] | None = None
    ) -> dict[tuple[Venue, str], BookState]:
        async with self._lock:
            keys = markets or set(self._books)
            return {
                key: self._books[key]
                for key in keys
                if key in self._books and self._valid.get(key, True)
            }

    async def invalidate_venue(self, venue: Venue) -> None:
        async with self._lock:
            for key in [key for key in self._books if key[0] == venue]:
                self._books.pop(key, None)
                self._valid.pop(key, None)
