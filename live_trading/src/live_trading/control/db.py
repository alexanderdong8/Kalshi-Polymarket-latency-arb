from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ControlDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def put(self, table: str, key: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), default=str)
        with self._lock, sqlite3.connect(self.path) as conn:
            conn.execute(
                f"""
                INSERT INTO {table} (id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (key, encoded, utc_now()),
            )
            conn.commit()

    def get(self, table: str, key: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(f"SELECT payload FROM {table} WHERE id = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, table: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM {table} ORDER BY updated_at DESC"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, table: str, key: str) -> None:
        with self._lock, sqlite3.connect(self.path) as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (key,))
            conn.commit()

    def append_event(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock, sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO control_events (ts, topic, payload) VALUES (?, ?, ?)",
                (utc_now(), topic, json.dumps(payload, separators=(",", ":"), default=str)),
            )
            conn.commit()

    def recent_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ts, topic, payload FROM control_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"ts": row["ts"], "topic": row["topic"], "payload": json.loads(row["payload"])}
            for row in rows
        ]

    def mark_offline_interval(self, started_at: str, ended_at: str | None = None) -> None:
        with self._lock, sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO offline_intervals (started_at, ended_at) VALUES (?, ?)",
                (started_at, ended_at),
            )
            conn.commit()

    def close_latest_offline_interval(self, ended_at: str) -> None:
        with self._lock, sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                UPDATE offline_intervals
                SET ended_at = ?
                WHERE id = (
                    SELECT id FROM offline_intervals
                    WHERE ended_at IS NULL
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (ended_at,),
            )
            conn.commit()

    def offline_intervals(self) -> list[dict[str, str | None]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT started_at, ended_at FROM offline_intervals ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def _initialize(self) -> None:
        tables = (
            "catalog_snapshots",
            "scan_jobs",
            "candidates",
            "watchlist",
            "configurations",
            "workers",
            "backtests",
            "presets",
        )
        with sqlite3.connect(self.path) as conn:
            for table in tables:
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS control_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_intervals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT
                )
                """
            )
            conn.commit()
