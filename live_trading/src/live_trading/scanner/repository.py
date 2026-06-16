from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..control.db import ControlDatabase


class ScannerRepository:
    def __init__(self, database: ControlDatabase) -> None:
        self.database = database

    def put_job(self, job_id: str, payload: dict[str, Any]) -> None:
        self.database.put("scan_jobs", job_id, payload)

    def put_catalog(self, snapshot_id: str, payload: dict[str, Any]) -> None:
        self.database.put("catalog_snapshots", snapshot_id, payload)

    def put_candidate(self, candidate_id: str, payload: dict[str, Any]) -> None:
        self.database.put("candidates", candidate_id, payload)

    def latest_recent_catalog(self, *, max_age_seconds: int) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        for payload in self.database.list("catalog_snapshots"):
            if payload.get("kind") != "recent_tradable":
                continue
            fetched_at = _parse_iso(payload.get("fetched_at"))
            if fetched_at and (now - fetched_at).total_seconds() <= max_age_seconds:
                return payload
        return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
