from __future__ import annotations

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
