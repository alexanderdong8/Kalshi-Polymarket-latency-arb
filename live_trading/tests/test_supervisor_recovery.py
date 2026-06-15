from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from live_trading.config import Settings
from live_trading.control.db import ControlDatabase
from live_trading.control.hub import EventHub
from live_trading.control.supervisor import RuntimeSupervisor


def test_restart_pauses_stale_workers_and_changed_live_mapping(tmp_path) -> None:
    async def run() -> None:
        db = ControlDatabase(tmp_path / "control.sqlite3")
        db.put(
            "workers",
            "stale-worker",
            {
                "id": "stale-worker",
                "event_id": "event",
                "event_name": "Event",
                "mode": "live",
                "budget": 100,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "state": {},
            },
        )
        db.put(
            "watchlist",
            "event",
            {
                "id": "event",
                "name": "Event",
                "manifest_path": str(tmp_path / "new.yaml"),
            },
        )
        db.put(
            "configurations",
            "event:live",
            {
                "id": "event:live",
                "event_id": "event",
                "mode": "live",
                "budget": 100,
                "strategy": {},
                "manifest_path": str(tmp_path / "old.yaml"),
                "active": True,
            },
        )
        supervisor = RuntimeSupervisor(
            db,
            EventHub(),
            tmp_path / "data",
            Settings.from_env(),
            tmp_path,
        )
        await supervisor.start()
        try:
            stale = db.get("workers", "stale-worker")
            config = db.get("configurations", "event:live")
            paused = [
                row
                for row in db.list("workers")
                if row["id"] != "stale-worker" and row["status"] == "paused"
            ]
            assert stale["status"] == "paused"
            assert config["active"] is False
            assert "Approval mapping changed" in paused[0]["pause_reason"]
        finally:
            await supervisor.shutdown()

    asyncio.run(run())
