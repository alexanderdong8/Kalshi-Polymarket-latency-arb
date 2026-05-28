from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import ArbOpportunity, BookState, MatchedMarket


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    return str(value)


class SQLiteRecorder:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS matched_markets (
                match_id TEXT PRIMARY KEY,
                kalshi_market_id TEXT NOT NULL,
                polymarket_market_id TEXT NOT NULL,
                confidence TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS book_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venue TEXT NOT NULL,
                market_key TEXT NOT NULL,
                received_ts TEXT NOT NULL,
                venue_ts TEXT,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                detected_ts TEXT NOT NULL,
                direction TEXT NOT NULL,
                gross_edge TEXT NOT NULL,
                net_edge TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._writer())

    async def close(self) -> None:
        if self._task:
            await self.queue.put(("close", None))
            await self._task
        self.conn.close()

    async def record_match(self, match: MatchedMarket) -> None:
        await self.queue.put(("match", match))

    async def record_book(self, book: BookState) -> None:
        await self.queue.put(("book", book))

    async def record_opportunity(self, opportunity: ArbOpportunity) -> None:
        await self.queue.put(("opportunity", opportunity))

    async def _writer(self) -> None:
        while True:
            kind, payload = await self.queue.get()
            if kind == "close":
                self.conn.commit()
                return
            if kind == "match":
                self._write_match(payload)
            elif kind == "book":
                self._write_book(payload)
            elif kind == "opportunity":
                self._write_opportunity(payload)
            self.conn.commit()

    def _write_match(self, match: MatchedMarket) -> None:
        now = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        self.conn.execute(
            """
            INSERT INTO matched_markets (
                match_id, kalshi_market_id, polymarket_market_id, confidence,
                warnings_json, payload_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                confidence=excluded.confidence,
                warnings_json=excluded.warnings_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                match.match_id,
                match.kalshi.market_id,
                match.polymarket_us.market_id,
                str(match.confidence),
                json.dumps(match.warnings),
                json.dumps(asdict(match), default=_json_default),
                now,
            ),
        )

    def _write_book(self, book: BookState) -> None:
        self.conn.execute(
            """
            INSERT INTO book_snapshots (venue, market_key, received_ts, venue_ts, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                book.venue,
                book.market_key,
                book.received_ts.isoformat(),
                book.venue_ts.isoformat() if book.venue_ts else None,
                json.dumps(asdict(book), default=_json_default),
            ),
        )

    def _write_opportunity(self, opportunity: ArbOpportunity) -> None:
        self.conn.execute(
            """
            INSERT INTO opportunities (
                match_id, detected_ts, direction, gross_edge, net_edge, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                opportunity.match_id,
                opportunity.detected_ts.isoformat(),
                opportunity.direction,
                str(opportunity.gross_edge_per_contract),
                str(opportunity.net_edge_per_contract),
                json.dumps(asdict(opportunity), default=_json_default),
            ),
        )

