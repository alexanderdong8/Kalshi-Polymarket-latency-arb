from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config import Settings
from ..execution_persistence import ExecutionJournal
from ..execution_service import LiveExecutionCoordinator
from ..live_orders import LiveOrderClient
from ..market_data import SharedMarketDataGateway
from ..pooled_session import PooledEventSession
from ..workers import StrategyWorkerPool
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
        self._pooled_sessions: dict[str, PooledEventSession] = {}
        self._monitor_task: asyncio.Task[None] | None = None
        self.global_emergency_path = data_root / "GLOBAL_EMERGENCY_STOP"
        self.runtime_architecture = (
            settings.runtime_architecture
            if settings.runtime_architecture in {"legacy", "pooled"}
            else "pooled"
        )
        self.market_data = SharedMarketDataGateway(settings)
        self.worker_pool = StrategyWorkerPool(settings.strategy_worker_count)
        self.market_data.add_listener(self.worker_pool.dispatch)
        self.live_execution = LiveExecutionCoordinator(settings, self.global_emergency_path)

    async def start(self) -> None:
        if self.runtime_architecture == "pooled":
            await self.worker_pool.start()
            await self.market_data.start()
        self._mark_stale_workers_paused()
        self._monitor_task = asyncio.create_task(self._monitor(), name="worker-monitor")
        for configuration in self.db.list("configurations"):
            if configuration.get("mode") == "live" and configuration.get("active"):
                event = self.db.get("watchlist", configuration.get("event_id", "")) or {}
                if event.get("manifest_path") != configuration.get("manifest_path"):
                    configuration["active"] = False
                    self.db.put(
                        "configurations",
                        str(configuration.get("id")),
                        configuration,
                    )
                    self._record_paused_recovery(
                        configuration,
                        "Approval mapping changed; review and confirm live activation again.",
                    )
                    continue
                try:
                    await self.start_worker(
                        ModeConfiguration.model_validate(configuration),
                        manifest_path=Path(configuration["manifest_path"]),
                        confirmed=True,
                        auto_resume=True,
                    )
                except Exception as exc:
                    configuration["active"] = False
                    self.db.put(
                        "configurations",
                        str(configuration.get("id")),
                        configuration,
                    )
                    self._record_paused_recovery(
                        configuration,
                        f"Live recovery reconciliation failed: {exc}",
                    )

    async def shutdown(self) -> None:
        for worker_id in list({*self._processes, *self._pooled_sessions}):
            await self.stop_worker(
                worker_id,
                reason="Application shutdown",
                preserve_live_configuration=True,
            )
        if self._monitor_task:
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)
        if self.runtime_architecture == "pooled":
            await self.market_data.stop()
            await self.worker_pool.stop()

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
                if row.id in self._processes or row.id in self._pooled_sessions
                if row.event_id == configuration.event_id
                and row.mode == configuration.mode
                and row.status in {"starting", "running"}
            ),
            None,
        )
        if existing:
            return existing
        if self.runtime_architecture == "pooled":
            return await self._start_pooled_worker(
                configuration,
                manifest_path=manifest_path,
                confirmed=confirmed,
                auto_resume=auto_resume,
            )
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

    async def _start_pooled_worker(
        self,
        configuration: ModeConfiguration,
        *,
        manifest_path: Path,
        confirmed: bool,
        auto_resume: bool,
    ) -> WorkerState:
        if configuration.mode == "live" and not confirmed:
            raise RuntimeError("Live pooled sessions require confirmed activation.")
        worker_id = uuid.uuid4().hex
        session = PooledEventSession(
            session_id=worker_id,
            mode=configuration.mode,
            manifest_path=manifest_path,
            capital=Decimal(str(configuration.budget)),
            strategy=configuration.strategy.model_dump(mode="json"),
            settings=self.settings,
            data_root=self.data_root,
        )
        markets = await session.start()
        try:
            if configuration.mode == "live":
                coordinated, reconciliation = await self.live_execution.activate(
                    session_id=worker_id,
                    event_id=configuration.event_id,
                    budget=Decimal(str(configuration.budget)),
                    client=session.order_client,
                )
                session.order_client = coordinated
                session.executor.client = coordinated
                session.exit_monitor.client = coordinated
            worker_shard = self.worker_pool.register(
                worker_id,
                configuration.event_id,
                configuration.mode,
                markets,
                session.on_market_update,
            )
            self.market_data.subscribe(worker_id, markets)
            self._pooled_sessions[worker_id] = session
        except Exception:
            self.worker_pool.unregister(worker_id)
            self.market_data.unsubscribe(worker_id)
            await self.live_execution.deactivate(worker_id)
            await session.close()
            raise
        event = self.db.get("watchlist", configuration.event_id) or {}
        state = WorkerState(
            id=worker_id,
            event_id=configuration.event_id,
            event_name=event.get("name", configuration.event_id),
            mode=configuration.mode,
            budget=configuration.budget,
            status="running",
            pid=os.getpid(),
            started_at=now(),
            heartbeat_at=now(),
            state={
                "manifest_path": str(manifest_path),
                "auto_resume": auto_resume,
                "runtime_architecture": "pooled",
                "worker_shard": worker_shard,
                "reconciliation": reconciliation
                if configuration.mode == "live"
                else None,
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
        session = self._pooled_sessions.pop(worker_id, None)
        if session is not None:
            self.worker_pool.unregister(worker_id)
            self.market_data.unsubscribe(worker_id)
            await session.close()
            await self.live_execution.deactivate(worker_id)
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
            await self.live_execution.emergency_stop()
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
        journal_path = (
            self.data_root / event["slug"] / "live" / "execution.sqlite3"
            if self.runtime_architecture == "pooled"
            else self.data_root / event["slug"] / "execution.sqlite3"
        )
        journal = ExecutionJournal(journal_path)
        preview = await self.live_execution.preview(
            journal=journal, budget=Decimal(str(budget))
        )
        return {
            "event": event,
            "budget": budget,
            "maximum_new_exposure": budget,
            **preview,
            "warnings": event.get("warnings", []),
        }

    def list_workers(self) -> list[WorkerState]:
        return [WorkerState.model_validate(row) for row in self.db.list("workers")]

    def worker(self, worker_id: str) -> WorkerState | None:
        payload = self.db.get("workers", worker_id)
        return WorkerState.model_validate(payload) if payload else None

    async def _monitor(self) -> None:
        while True:
            for worker_id, session in list(self._pooled_sessions.items()):
                payload = self.db.get("workers", worker_id)
                if not payload:
                    continue
                failure = session.failure_reason()
                payload["status"] = "failed" if failure else "running"
                payload["heartbeat_at"] = now().isoformat()
                if failure:
                    payload["pause_reason"] = failure
                payload["state"] = {
                    **payload.get("state", {}),
                    **session.latest_state,
                    "market_data_health": dict(self.market_data.health),
                    "offline_intervals": self.db.offline_intervals(),
                }
                self.db.put("workers", worker_id, payload)
                await self.hub.publish("worker.updated", payload)
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

    def _mark_stale_workers_paused(self) -> None:
        for payload in self.db.list("workers"):
            if payload.get("status") not in {"starting", "running"}:
                continue
            payload["status"] = "paused"
            payload["pause_reason"] = "Application restarted; recovery reconciliation pending."
            payload["heartbeat_at"] = now().isoformat()
            self.db.put("workers", str(payload["id"]), payload)

    def _record_paused_recovery(
        self, configuration: dict[str, Any], reason: str
    ) -> None:
        worker_id = uuid.uuid4().hex
        event_id = str(configuration.get("event_id") or "")
        event = self.db.get("watchlist", event_id) or {}
        state = WorkerState(
            id=worker_id,
            event_id=event_id,
            event_name=event.get("name", event_id),
            mode="live",
            budget=float(configuration.get("budget") or 0),
            status="paused",
            heartbeat_at=now(),
            pause_reason=reason,
            state={"runtime_architecture": self.runtime_architecture},
        )
        self.db.put("workers", worker_id, state.model_dump(mode="json"))

    def _state_path(self, worker: dict[str, Any]) -> Path:
        event = self.db.get("watchlist", worker["event_id"]) or {}
        return self.data_root / event.get("slug", worker["event_id"]) / "dashboard_state.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return {}
