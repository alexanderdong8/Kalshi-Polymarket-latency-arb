from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .metrics import RecorderMetrics
from .models import ArbOpportunity, BookState, MatchedMarket


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    return str(value)


class SegmentedRecorder:
    def __init__(
        self,
        data_dir: str,
        *,
        quota_bytes: int = 3 * 1024**3,
        low_watermark_bytes: int = 2_700 * 1024**2,
        snapshot_interval_seconds: float = 30.0,
        routine_queue_maxsize: int = 20_000,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.snapshot_dir = self.data_dir / "snapshots"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.quota_bytes = quota_bytes
        self.low_watermark_bytes = min(low_watermark_bytes, quota_bytes)
        self.snapshot_interval_seconds = snapshot_interval_seconds
        self.routine_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=routine_queue_maxsize)
        self.durable_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._last_enqueued: dict[tuple[str, str], float] = {}
        self._task: asyncio.Task | None = None
        self._closing = False
        self._max_routine_queue_depth = 0
        self._dropped_routine_snapshots = 0
        self._sqlite_writes = 0
        self._started = time.monotonic()
        self._rotation_count = 0
        self._segment_key: str | None = None
        self._segment_conn: sqlite3.Connection | None = None
        self._durable_conn = sqlite3.connect(self.data_dir / "events.sqlite3")
        self._durable_conn.execute("PRAGMA journal_mode=WAL")
        self._init_durable_schema()

    def _init_durable_schema(self) -> None:
        self._durable_conn.executescript(
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
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                detected_ts TEXT NOT NULL,
                direction TEXT NOT NULL,
                gross_edge TEXT NOT NULL,
                net_edge TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_ts TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        self._durable_conn.commit()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._writer(), name="segmented-sqlite-recorder")

    async def close(self) -> None:
        self._closing = True
        if self._task:
            await self._task
        if self._segment_conn:
            self._segment_conn.commit()
            self._segment_conn.close()
        self._durable_conn.commit()
        self._durable_conn.close()

    def try_record_match(self, match: MatchedMarket) -> None:
        self.durable_queue.put_nowait(("match", match))

    def try_record_opportunity(self, opportunity: ArbOpportunity) -> None:
        self.durable_queue.put_nowait(("opportunity", opportunity))

    def try_record_metrics(self, payload: dict[str, Any]) -> None:
        self.durable_queue.put_nowait(("metrics", payload))

    def try_record_book(self, book: BookState) -> bool:
        key = (book.venue, book.market_key)
        now = time.monotonic()
        if now - self._last_enqueued.get(key, float("-inf")) < self.snapshot_interval_seconds:
            return False
        try:
            self.routine_queue.put_nowait(("book", book))
        except asyncio.QueueFull:
            self._dropped_routine_snapshots += 1
            return False
        self._last_enqueued[key] = now
        self._max_routine_queue_depth = max(self._max_routine_queue_depth, self.routine_queue.qsize())
        return True

    def metrics(self) -> RecorderMetrics:
        return RecorderMetrics(
            routine_queue_depth=self.routine_queue.qsize(),
            durable_queue_depth=self.durable_queue.qsize(),
            max_routine_queue_depth=self._max_routine_queue_depth,
            dropped_routine_snapshots=self._dropped_routine_snapshots,
            sqlite_writes=self._sqlite_writes,
            sqlite_writes_per_second=self._sqlite_writes / max(time.monotonic() - self._started, 1e-9),
            rotation_count=self._rotation_count,
            disk_usage_bytes=self.disk_usage_bytes(),
        )

    def disk_usage_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.data_dir.rglob("*") if path.is_file())

    def enforce_quota(self) -> None:
        if self.disk_usage_bytes() <= self.quota_bytes:
            return
        current = self._segment_path(self._segment_key) if self._segment_key else None
        candidates = sorted(self.snapshot_dir.glob("*.sqlite3"), key=lambda path: path.stat().st_mtime)
        for path in candidates:
            if current and path == current:
                continue
            path.unlink(missing_ok=True)
            self._rotation_count += 1
            if self.disk_usage_bytes() <= self.low_watermark_bytes:
                break
        if self.disk_usage_bytes() > self.quota_bytes:
            self._trim_durable()

    def _trim_durable(self) -> None:
        self._durable_conn.commit()
        for table in ("metrics", "opportunities"):
            while self.disk_usage_bytes() > self.low_watermark_bytes:
                cursor = self._durable_conn.execute(
                    f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} ORDER BY id ASC LIMIT 1000)"
                )
                self._durable_conn.commit()
                if cursor.rowcount == 0:
                    break
                self._durable_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._durable_conn.execute("VACUUM")

    async def _writer(self) -> None:
        writes_since_rotation = 0
        while not self._closing or not self.durable_queue.empty() or not self.routine_queue.empty():
            item = self._next_item()
            if item is None:
                await asyncio.sleep(0.01)
                continue
            kind, payload = item
            if kind == "book":
                self._write_book(payload)
                self.routine_queue.task_done()
            elif kind == "match":
                self._write_match(payload)
                self.durable_queue.task_done()
            elif kind == "opportunity":
                self._write_opportunity(payload)
                self.durable_queue.task_done()
            elif kind == "metrics":
                self._write_metrics(payload)
                self.durable_queue.task_done()
            self._sqlite_writes += 1
            writes_since_rotation += 1
            if writes_since_rotation >= 250:
                self._commit()
                self.enforce_quota()
                writes_since_rotation = 0
        self._commit()
        self.enforce_quota()

    def _next_item(self) -> tuple[str, Any] | None:
        try:
            return self.durable_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            return self.routine_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _write_match(self, match: MatchedMarket) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._durable_conn.execute(
            """
            INSERT INTO matched_markets (
                match_id, kalshi_market_id, polymarket_market_id, confidence,
                warnings_json, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
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

    def _write_opportunity(self, opportunity: ArbOpportunity) -> None:
        self._durable_conn.execute(
            """
            INSERT INTO opportunities (
                match_id, detected_ts, direction, gross_edge, net_edge, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
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

    def _write_metrics(self, payload: dict[str, Any]) -> None:
        self._durable_conn.execute(
            "INSERT INTO metrics (recorded_ts, payload_json) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), json.dumps(payload, default=_json_default)),
        )

    def _write_book(self, book: BookState) -> None:
        conn = self._segment_for(book.received_ts)
        conn.execute(
            """
            INSERT INTO bbo_snapshots (
                venue, market_key, received_ts, venue_ts, yes_bid, yes_ask, no_bid, no_ask,
                yes_bid_size, yes_ask_size, no_bid_size, no_ask_size, sequence, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book.venue,
                book.market_key,
                book.received_ts.isoformat(),
                book.venue_ts.isoformat() if book.venue_ts else None,
                _str_or_none(book.yes_bid),
                _str_or_none(book.yes_ask),
                _str_or_none(book.no_bid),
                _str_or_none(book.no_ask),
                _str_or_none(book.yes_bid_size),
                _str_or_none(book.yes_ask_size),
                _str_or_none(book.no_bid_size),
                _str_or_none(book.no_ask_size),
                book.sequence,
                book.state,
            ),
        )

    def _segment_for(self, timestamp: datetime) -> sqlite3.Connection:
        segment_key = timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H")
        if self._segment_conn and self._segment_key == segment_key:
            return self._segment_conn
        if self._segment_conn:
            self._segment_conn.commit()
            self._segment_conn.close()
        self._segment_key = segment_key
        self._segment_conn = sqlite3.connect(self._segment_path(segment_key))
        self._segment_conn.execute("PRAGMA journal_mode=WAL")
        self._segment_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bbo_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venue TEXT NOT NULL,
                market_key TEXT NOT NULL,
                received_ts TEXT NOT NULL,
                venue_ts TEXT,
                yes_bid TEXT,
                yes_ask TEXT,
                no_bid TEXT,
                no_ask TEXT,
                yes_bid_size TEXT,
                yes_ask_size TEXT,
                no_bid_size TEXT,
                no_ask_size TEXT,
                sequence INTEGER,
                state TEXT
            )
            """
        )
        return self._segment_conn

    def _segment_path(self, segment_key: str | None) -> Path:
        if not segment_key:
            raise ValueError("Segment key is required.")
        return self.snapshot_dir / f"{segment_key}.sqlite3"

    def _commit(self) -> None:
        self._durable_conn.commit()
        if self._segment_conn:
            self._segment_conn.commit()


# Compatibility alias for callers that used the first recorder name.
SQLiteRecorder = SegmentedRecorder


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)
