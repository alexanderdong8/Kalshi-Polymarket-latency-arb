from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings
from ..execution_persistence import ExecutionJournal
from ..live_orders import LiveOrderClient
from .db import ControlDatabase
from .hub import EventHub
from .schemas import ModeConfiguration, WorkerState


def now() -> datetime:
    return datetime.now(timezone.utc)


class RuntimeSupervisor:
    def __init__(
        self,
        db: ControlDatabase,
        hub: EventHub,
        data_root: Path,
        settings: Settings,
        repository_root: Path,
    ) -> None:
        self.db = db
        self.hub = hub
        self.data_root = data_root
        self.settings = settings
        self.repository_root = repository_root
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._monitor_task: asyncio.Task[None] | None = None
        self.global_emergency_path = data_root / "GLOBAL_EMERGENCY_STOP"

    async def start(self) -> None:
        self._monitor_task = asyncio.create_task(self._monitor(), name="worker-monitor")
        for configuration in self.db.list("configurations"):
            if configuration.get("mode") == "live" and configuration.get("active"):
                with suppress(Exception):
                    await self.start_worker(
                        ModeConfiguration.model_validate(configuration),
                        manifest_path=Path(configuration["manifest_path"]),
                        confirmed=True,
                        auto_resume=True,
                    )

    async def shutdown(self) -> None:
        for worker_id in list(self._processes):
            await self.stop_worker(
                worker_id,
                reason="Application shutdown",
                preserve_live_configuration=True,
            )
        if self._monitor_task:
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)

    async def start_worker(
        self,
        configuration: ModeConfiguration,
        *,
        manifest_path: Path,
        confirmed: bool,
        auto_resume: bool = False,
    ) -> WorkerState:
        if configuration.mode == "live" and self.global_emergency_path.exists():
            raise RuntimeError("Global emergency stop is active.")
        existing = next(
            (
                row
                for row in self.list_workers()
                if row.event_id == configuration.event_id
                and row.mode == configuration.mode
                and row.status in {"starting", "running"}
            ),
            None,
        )
        if existing:
            return existing
        worker_id = uuid.uuid4().hex
        command = [
            sys.executable,
            "-m",
            "live_trading",
            "run",
            "--mode",
            configuration.mode,
            "--capital",
            str(configuration.budget),
            "--config",
            str(manifest_path),
            "--no-dashboard",
            "--strategy-json",
            configuration.strategy.model_dump_json(),
        ]
        if configuration.mode == "live" and confirmed:
            command.append("--confirmed-live")
        logs = self.data_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stdout = (logs / f"{worker_id}.log").open("a", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=str(self.repository_root),
            stdout=stdout,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._processes[worker_id] = process
        event = self.db.get("watchlist", configuration.event_id) or {}
        state = WorkerState(
            id=worker_id,
            event_id=configuration.event_id,
            event_name=event.get("name", configuration.event_id),
            mode=configuration.mode,
            budget=configuration.budget,
            status="starting",
            pid=process.pid,
            started_at=now(),
            heartbeat_at=now(),
            state={
                "manifest_path": str(manifest_path),
                "auto_resume": auto_resume,
                "offline_intervals": self.db.offline_intervals(),
            },
        )
        self.db.put("workers", worker_id, state.model_dump(mode="json"))
        config_payload = configuration.model_dump(mode="json")
        config_payload.update(
            {
                "id": f"{configuration.event_id}:{configuration.mode}",
                "manifest_path": str(manifest_path),
                "active": configuration.mode == "live",
            }
        )
        self.db.put("configurations", config_payload["id"], config_payload)
        await self.hub.publish("worker.updated", state.model_dump(mode="json"))
        return state

    async def stop_worker(
        self,
        worker_id: str,
        *,
        reason: str = "Stopped by user",
        preserve_live_configuration: bool = False,
    ) -> WorkerState:
        payload = self.db.get("workers", worker_id)
        if not payload:
            raise KeyError(worker_id)
        process = self._processes.pop(worker_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
        payload.update(
            {
                "status": "stopped",
                "heartbeat_at": now().isoformat(),
                "pause_reason": reason,
            }
        )
        self.db.put("workers", worker_id, payload)
        config_id = f"{payload['event_id']}:{payload['mode']}"
        configuration = self.db.get("configurations", config_id)
        if configuration and (
            payload["mode"] == "paper" or not preserve_live_configuration
        ):
            configuration["active"] = False
            self.db.put("configurations", config_id, configuration)
        await self.hub.publish("worker.updated", payload)
        return WorkerState.model_validate(payload)

    async def emergency_stop(self, active: bool) -> dict[str, Any]:
        if active:
            self.global_emergency_path.parent.mkdir(parents=True, exist_ok=True)
            self.global_emergency_path.write_text("Global live emergency stop.\n", encoding="utf-8")
            for worker in self.list_workers():
                if worker.mode == "live" and worker.status in {"starting", "running"}:
                    await self.stop_worker(worker.id, reason="Global emergency stop")
        else:
            self.global_emergency_path.unlink(missing_ok=True)
        payload = {"active": active, "updated_at": now().isoformat()}
        self.db.append_event("emergency_stop", payload)
        await self.hub.publish("emergency_stop", payload)
        return payload

    async def live_preview(self, event_id: str, budget: float) -> dict[str, Any]:
        event = self.db.get("watchlist", event_id)
        if not event:
            raise KeyError(event_id)
        journal = ExecutionJournal(self.data_root / event["slug"] / "execution.sqlite3")
        client = LiveOrderClient(self.settings, journal)
        reconciliation = await client.reconcile()
        return {
            "event": event,
            "budget": budget,
            "maximum_new_exposure": budget,
            "reconciliation": reconciliation,
            "warnings": event.get("warnings", []),
        }

    def list_workers(self) -> list[WorkerState]:
        return [WorkerState.model_validate(row) for row in self.db.list("workers")]

    def worker(self, worker_id: str) -> WorkerState | None:
        payload = self.db.get("workers", worker_id)
        return WorkerState.model_validate(payload) if payload else None

    async def _monitor(self) -> None:
        while True:
            for worker_id, process in list(self._processes.items()):
                payload = self.db.get("workers", worker_id)
                if not payload:
                    continue
                code = process.poll()
                state_path = self._state_path(payload)
                state = _read_json(state_path)
                if code is None:
                    payload["status"] = "running" if state else payload.get("status", "starting")
                    payload["heartbeat_at"] = now().isoformat()
                    if state:
                        payload["state"] = {
                            **payload.get("state", {}),
                            **state,
                            "offline_intervals": self.db.offline_intervals(),
                        }
                else:
                    payload["status"] = "failed" if code else "stopped"
                    payload["pause_reason"] = f"Worker exited with code {code}"
                    self._processes.pop(worker_id, None)
                self.db.put("workers", worker_id, payload)
                await self.hub.publish("worker.updated", payload)
            await asyncio.sleep(1)

    def _state_path(self, worker: dict[str, Any]) -> Path:
        event = self.db.get("watchlist", worker["event_id"]) or {}
        return self.data_root / event.get("slug", worker["event_id"]) / "dashboard_state.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return {}
