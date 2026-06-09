from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ExecutionJournal:
    """Durable order/fill/event journal used for restart reconciliation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def append(
        self,
        kind: str,
        payload: Any,
        *,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
        venue: str | None = None,
        status: str | None = None,
    ) -> None:
        encoded = json.dumps(payload, default=_json_default, separators=(",", ":"))
        with self._lock, sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO execution_events
                    (ts, kind, venue, client_order_id, exchange_order_id, status, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    kind,
                    venue,
                    client_order_id,
                    exchange_order_id,
                    status,
                    encoded,
                ),
            )
            conn.commit()

    def unresolved_orders(self) -> list[dict[str, Any]]:
        terminal = {"filled", "cancelled", "rejected", "expired"}
        latest: dict[str, dict[str, Any]] = {}
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM execution_events
                WHERE client_order_id IS NOT NULL
                ORDER BY id
                """
            ).fetchall()
        for row in rows:
            latest[row["client_order_id"]] = dict(row)
        return [row for row in latest.values() if (row.get("status") or "") not in terminal]

    def open_positions(self) -> list[dict[str, Any]]:
        opened: dict[str, dict[str, Any]] = {}
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT kind, payload FROM execution_events
                WHERE kind IN ('position_opened', 'position_closed')
                ORDER BY id
                """
            ).fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            basket_id = str(payload.get("basket_id") or "")
            if not basket_id:
                continue
            if row["kind"] == "position_opened":
                opened[basket_id] = payload
            else:
                opened.pop(basket_id, None)
        return list(opened.values())

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    venue TEXT,
                    client_order_id TEXT,
                    exchange_order_id TEXT,
                    status TEXT,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_client_order "
                "ON execution_events(client_order_id, id)"
            )
            conn.commit()


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
