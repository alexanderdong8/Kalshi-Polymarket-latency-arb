from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import Settings
from ..execution_persistence import ExecutionJournal
from ..live_orders import LiveOrderClient
from .backtests import BacktestService
from .db import ControlDatabase
from .hub import EventHub
from .manifests import write_manifest
from .scanner import MarketScanner
from .schemas import (
    ApprovalRequest,
    BasketAddRequest,
    BasketEntry,
    BacktestJob,
    BacktestRequest,
    Candidate,
    LiveActivationRequest,
    MarketSuggestion,
    ModeConfiguration,
    ScanJob,
    ScanRequest,
    SettingsStatus,
    StrategySettings,
    WorkerState,
)
from .supervisor import RuntimeSupervisor


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EmergencyRequest(BaseModel):
    active: bool


class SubscriptionRequest(BaseModel):
    subscribe: list[str] = Field(default_factory=lambda: ["*"])


def create_app(
    repository_root: Path | None = None,
    database_path: Path | None = None,
) -> FastAPI:
    root = (repository_root or Path.cwd()).resolve()
    data_root = root / "live_trading" / "data"
    control_root = data_root / "control"
    settings = Settings.from_env()
    db = ControlDatabase(database_path or control_root / "control.sqlite3")
    hub = EventHub()
    scanner = MarketScanner(db, hub, settings, root)
    supervisor = RuntimeSupervisor(db, hub, data_root, settings, root)
    backtests = BacktestService(db, hub)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.close_latest_offline_interval(utc_now())
        scanner.recover_abandoned_jobs()
        _install_presets(db)
        await supervisor.start()
        try:
            yield
        finally:
            await supervisor.shutdown()
            db.mark_offline_interval(utc_now())

    app = FastAPI(
        title="Prediction Market Trading Control API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.db = db
    app.state.hub = hub
    app.state.scanner = scanner
    app.state.supervisor = supervisor
    app.state.backtests = backtests
    app.state.settings = settings
    app.state.repository_root = root

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "time": utc_now(),
            "workers": len(supervisor.list_workers()),
            "emergency_stop": supervisor.global_emergency_path.exists(),
        }

    @app.post("/api/shutdown")
    async def shutdown() -> dict[str, Any]:
        await supervisor.shutdown()
        db.mark_offline_interval(utc_now())
        return {"status": "ready", "message": "Workers stopped; process may be terminated."}

    @app.post("/api/scans", response_model=ScanJob)
    async def create_scan(request: ScanRequest) -> ScanJob:
        return scanner.start(request)

    @app.get("/api/scans", response_model=list[ScanJob])
    async def list_scans() -> list[ScanJob]:
        return [ScanJob.model_validate(row) for row in db.list("scan_jobs")]

    @app.get("/api/scans/{scan_id}", response_model=ScanJob)
    async def get_scan(scan_id: str) -> ScanJob:
        return ScanJob.model_validate(_get_or_404(db, "scan_jobs", scan_id))

    @app.get("/api/catalogs")
    async def catalogs() -> list[dict[str, Any]]:
        return db.list("catalog_snapshots")

    @app.get("/api/market-suggestions", response_model=list[MarketSuggestion])
    async def market_suggestions(
        query: str = Query(min_length=2),
        limit: int = Query(default=8, ge=1, le=20),
        lookback_days: int = Query(default=7, ge=1, le=30),
    ) -> list[MarketSuggestion]:
        return await scanner.suggestions(
            query=query,
            limit=limit,
            lookback_days=lookback_days,
        )

    @app.get("/api/basket", response_model=list[BasketEntry])
    async def basket() -> list[BasketEntry]:
        return [BasketEntry.model_validate(row) for row in db.list("basket_entries")]

    @app.post("/api/basket", response_model=BasketEntry)
    async def add_basket_entry(request: BasketAddRequest) -> BasketEntry:
        suggestion = request.suggestion
        for payload in db.list("basket_entries"):
            existing = BasketEntry.model_validate(payload)
            if existing.suggestion_id == suggestion.id:
                return existing
        timestamp = datetime.now(timezone.utc)
        entry = BasketEntry(
            id=uuid_like("basket", suggestion.id),
            suggestion_id=suggestion.id,
            name=suggestion.name,
            category=suggestion.category,
            close_time=suggestion.close_time,
            outcome_count=suggestion.outcome_count,
            mapping_confidence=suggestion.mapping_confidence,
            kalshi_outcomes=suggestion.kalshi_outcomes,
            polymarket_outcomes=suggestion.polymarket_outcomes,
            warnings=suggestion.warnings,
            source=suggestion.source,
            venues=suggestion.venues,
            provider_event_ids=suggestion.provider_event_ids,
            provider_series_ids=suggestion.provider_series_ids,
            primary_exchange=suggestion.primary_exchange,
            total_volume=suggestion.total_volume,
            total_liquidity=suggestion.total_liquidity,
            added_at=timestamp,
            updated_at=timestamp,
        )
        db.put("basket_entries", entry.id, entry.model_dump(mode="json"))
        db.append_event("basket.added", entry.model_dump(mode="json"))
        await hub.publish("basket.updated", entry.model_dump(mode="json"))
        return entry

    @app.delete("/api/basket/{basket_id}")
    async def remove_basket_entry(basket_id: str) -> dict[str, str]:
        _get_or_404(db, "basket_entries", basket_id)
        db.delete("basket_entries", basket_id)
        await hub.publish("basket.removed", {"id": basket_id})
        return {"status": "removed"}

    @app.post("/api/basket/{basket_id}/prepare-review", response_model=BasketEntry)
    async def prepare_basket_entry(basket_id: str) -> BasketEntry:
        entry = BasketEntry.model_validate(_get_or_404(db, "basket_entries", basket_id))
        return await scanner.prepare_basket_entry(entry)

    @app.post("/api/basket/prepare-review", response_model=list[BasketEntry])
    async def prepare_basket_entries() -> list[BasketEntry]:
        entries = [BasketEntry.model_validate(row) for row in db.list("basket_entries")]
        result = []
        for entry in entries:
            result.append(await scanner.prepare_basket_entry(entry))
        return result

    @app.get("/api/candidates", response_model=list[Candidate])
    async def candidates(
        query: str = "",
        category: str | None = None,
        status: str | None = None,
    ) -> list[Candidate]:
        needle = query.casefold().strip()
        rows = []
        for payload in db.list("candidates"):
            candidate = Candidate.model_validate(payload)
            if needle and needle not in (
                f"{candidate.name} {candidate.description or ''} "
                + " ".join(
                    f"{row.kalshi_ticker} {row.polymarket_us_slug}"
                    for row in candidate.mappings
                )
            ).casefold():
                continue
            if category and candidate.category != category:
                continue
            if status and candidate.status != status:
                continue
            rows.append(candidate)
        return sorted(rows, key=lambda row: row.ranking.total_score, reverse=True)

    @app.get("/api/candidates/{candidate_id}", response_model=Candidate)
    async def candidate(candidate_id: str) -> Candidate:
        return Candidate.model_validate(_get_or_404(db, "candidates", candidate_id))

    @app.post("/api/candidates/{candidate_id}/approve")
    async def approve(candidate_id: str, request: ApprovalRequest) -> dict[str, Any]:
        payload = _get_or_404(db, "candidates", candidate_id)
        item = Candidate.model_validate(payload)
        failed_checks = [key for key, passed in item.deterministic_checks.items() if not passed]
        if failed_checks:
            raise HTTPException(409, f"Deterministic checks failed: {', '.join(failed_checks)}")
        if not item.exhaustive or not request.exhaustive or not request.settlement_reviewed:
            raise HTTPException(409, "Complete, mutually exclusive, exhaustive outcomes must be reviewed.")
        if item.llm_status != "passed":
            raise HTTPException(409, f"LLM settlement review must pass; current status is {item.llm_status}.")
        manifest_path, approval_version = write_manifest(
            control_root / "approved_events", item.model_dump(mode="json")
        )
        slug = _slug(item.name)
        watch = {
            **item.model_dump(mode="json"),
            "id": item.id,
            "slug": slug,
            "status": "approved",
            "approval_version": approval_version,
            "manifest_path": str(manifest_path),
            "approved_at": utc_now(),
            "active_modes": [],
        }
        db.put("watchlist", item.id, watch)
        payload.update({"status": "approved"})
        db.put("candidates", item.id, payload)
        db.append_event("event.approved", watch)
        await hub.publish("event.approved", watch)
        return watch

    @app.get("/api/events")
    async def events() -> list[dict[str, Any]]:
        workers = supervisor.list_workers()
        result = []
        for event in db.list("watchlist"):
            active = sorted(
                {
                    row.mode
                    for row in workers
                    if row.event_id == event["id"] and row.status in {"starting", "running"}
                }
            )
            result.append({**event, "active_modes": active})
        return result

    @app.get("/api/events/{event_id}")
    async def event(event_id: str) -> dict[str, Any]:
        payload = _get_or_404(db, "watchlist", event_id)
        workers = [
            row.model_dump(mode="json")
            for row in supervisor.list_workers()
            if row.event_id == event_id
        ]
        return {
            **payload,
            "workers": workers,
            "configurations": [
                row for row in db.list("configurations") if row["event_id"] == event_id
            ],
            "offline_intervals": db.offline_intervals(),
        }

    @app.delete("/api/events/{event_id}")
    async def remove_event(event_id: str) -> dict[str, str]:
        active = [
            row
            for row in supervisor.list_workers()
            if row.event_id == event_id and row.status in {"starting", "running"}
        ]
        if active:
            raise HTTPException(409, "Pause all paper and live sessions before removing this event.")
        db.delete("watchlist", event_id)
        return {"status": "removed"}

    @app.get("/api/workers", response_model=list[WorkerState])
    async def workers(mode: str | None = None) -> list[WorkerState]:
        rows = supervisor.list_workers()
        return [row for row in rows if not mode or row.mode == mode]

    @app.get("/api/workers/{worker_id}", response_model=WorkerState)
    async def worker(worker_id: str) -> WorkerState:
        item = supervisor.worker(worker_id)
        if item is None:
            raise HTTPException(404, "Worker not found.")
        return item

    @app.post("/api/events/{event_id}/paper/start", response_model=WorkerState)
    async def start_paper(event_id: str, request: ModeConfiguration) -> WorkerState:
        if request.event_id != event_id or request.mode != "paper":
            raise HTTPException(422, "Request must target this event in paper mode.")
        event_payload = _get_or_404(db, "watchlist", event_id)
        return await supervisor.start_worker(
            request,
            manifest_path=Path(event_payload["manifest_path"]),
            confirmed=False,
        )

    @app.post("/api/events/{event_id}/live/preview")
    async def live_preview(event_id: str, budget: float = Query(gt=0)) -> dict[str, Any]:
        try:
            return await supervisor.live_preview(event_id, budget)
        except KeyError:
            raise HTTPException(404, "Event not found.") from None
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/events/{event_id}/live/start", response_model=WorkerState)
    async def start_live(event_id: str, request: LiveActivationRequest) -> WorkerState:
        if request.event_id != event_id or request.mode != "live":
            raise HTTPException(422, "Request must target this event in live mode.")
        if request.confirmation.strip() != "LIVE":
            raise HTTPException(409, 'Type "LIVE" exactly to activate real-money trading.')
        event_payload = _get_or_404(db, "watchlist", event_id)
        try:
            preview = await supervisor.live_preview(event_id, request.budget)
            worker = await supervisor.start_worker(
                request,
                manifest_path=Path(event_payload["manifest_path"]),
                confirmed=True,
            )
            worker.state["startup_preview"] = preview
            db.put("workers", worker.id, worker.model_dump(mode="json"))
            return worker
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/workers/{worker_id}/stop", response_model=WorkerState)
    async def stop_worker(worker_id: str) -> WorkerState:
        try:
            return await supervisor.stop_worker(worker_id)
        except KeyError:
            raise HTTPException(404, "Worker not found.") from None

    @app.post("/api/emergency-stop")
    async def emergency_stop(request: EmergencyRequest) -> dict[str, Any]:
        return await supervisor.emergency_stop(request.active)

    @app.get("/api/backtests", response_model=list[BacktestJob])
    async def list_backtests() -> list[BacktestJob]:
        return [BacktestJob.model_validate(row) for row in db.list("backtests")]

    @app.post("/api/backtests", response_model=BacktestJob)
    async def create_backtest(request: BacktestRequest) -> BacktestJob:
        try:
            return backtests.start(request)
        except KeyError:
            raise HTTPException(404, "Approved event not found.") from None

    @app.get("/api/backtests/{job_id}", response_model=BacktestJob)
    async def get_backtest(job_id: str) -> BacktestJob:
        return BacktestJob.model_validate(_get_or_404(db, "backtests", job_id))

    @app.get("/api/presets")
    async def presets() -> list[dict[str, Any]]:
        return db.list("presets")

    @app.put("/api/presets/{name}")
    async def put_preset(name: str, settings_payload: StrategySettings) -> dict[str, Any]:
        payload = {"id": name, "name": name, **settings_payload.model_dump(mode="json")}
        db.put("presets", name, payload)
        return payload

    @app.get("/api/settings", response_model=SettingsStatus)
    async def settings_status() -> SettingsStatus:
        credentials = {
            "kalshi": bool(
                settings.kalshi_api_key_id
                and (settings.kalshi_private_key_path or settings.kalshi_private_key_pem)
            ),
            "polymarket_us": bool(
                settings.polymarket_key_id and settings.polymarket_secret_key
            ),
        }
        return SettingsStatus(
            credentials=credentials,
            connections={
                "kalshi": {"status": "not_tested", "base_url": settings.kalshi_api_base},
                "polymarket_us": {
                    "status": "not_tested",
                    "base_url": settings.polymarket_gateway_base,
                },
            },
            openai_available=bool(os.getenv("OPENAI_API_KEY")),
            storage={
                "control_database": str(db.path),
                "execution_data": str(data_root),
                "approved_manifests": str(control_root / "approved_events"),
            },
            workers=supervisor.list_workers(),
            emergency_stop=supervisor.global_emergency_path.exists(),
        )

    @app.get("/api/balances")
    async def balances() -> dict[str, Any]:
        journal = ExecutionJournal(control_root / "balances.sqlite3")
        client = LiveOrderClient(settings, journal)

        async def read(label: str, venue: str) -> tuple[str, str | None, str | None]:
            try:
                return label, str(await client.get_balance(venue)), None
            except Exception as exc:
                return label, None, str(exc)

        rows = await asyncio.gather(
            read("kalshi", "kalshi"),
            read("polymarket_us", "polymarket_us"),
        )
        payload: dict[str, Any] = {
            "kalshi_balance": None,
            "polymarket_us_balance": None,
            "errors": [],
        }
        for label, value, error in rows:
            payload[f"{label}_balance"] = value
            if error:
                payload["errors"].append(f"{label}: {error}")
        return payload

    @app.post("/api/settings/diagnostics")
    async def diagnostics() -> dict[str, Any]:
        async def run(label: str, awaitable: Any) -> tuple[str, dict[str, Any]]:
            try:
                result = await asyncio.wait_for(awaitable, timeout=12)
                return label, {"status": "connected", "detail": result}
            except Exception as exc:
                return label, {"status": "failed", "detail": str(exc)}

        from ..venues.kalshi import KalshiClient
        from ..venues.polymarket_us import PolymarketUSClient

        checks = await asyncio.gather(
            run("kalshi_market_data", KalshiClient(settings).list_active_markets(limit=1)),
            run(
                "polymarket_us_market_data",
                PolymarketUSClient(settings).list_active_markets(limit=1),
            ),
        )
        result = {
            key: {**value, "detail": _diagnostic_detail(value["detail"])}
            for key, value in checks
        }
        if any(
            (
                settings.kalshi_api_key_id,
                settings.polymarket_key_id,
            )
        ):
            journal = ExecutionJournal(control_root / "diagnostics.sqlite3")
            _, balances = await run("balances", LiveOrderClient(settings, journal).reconcile())
            result["accounts"] = {
                **balances,
                "detail": _diagnostic_detail(balances["detail"]),
            }
        return result

    @app.get("/api/activity")
    async def activity(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        return db.recent_events(limit)

    @app.websocket("/ws")
    async def websocket(socket: WebSocket) -> None:
        queue = await hub.connect(socket)

        async def sender() -> None:
            while True:
                await socket.send_json(await queue.get())
                queue.task_done()

        sender_task = asyncio.create_task(sender())
        try:
            await socket.send_json({"topic": "connected", "payload": {"time": utc_now()}})
            while True:
                request = SubscriptionRequest.model_validate(await socket.receive_json())
                hub.subscribe(socket, request.subscribe)
        except WebSocketDisconnect:
            pass
        finally:
            sender_task.cancel()
            with suppress(asyncio.CancelledError):
                await sender_task
            await hub.disconnect(socket)

    return app


def _get_or_404(db: ControlDatabase, table: str, key: str) -> dict[str, Any]:
    payload = db.get(table, key)
    if payload is None:
        raise HTTPException(404, f"{table.rstrip('s').replace('_', ' ')} not found.")
    return payload


def uuid_like(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode()).hexdigest()[:16]}"


def _slug(value: str) -> str:
    return "-".join(
        part for part in "".join(ch if ch.isalnum() else "-" for ch in value.lower()).split("-") if part
    )


def _diagnostic_detail(value: Any) -> Any:
    if isinstance(value, list):
        return {"records": len(value)}
    if isinstance(value, dict):
        return {
            key: val
            for key, val in value.items()
            if key not in {"unresolved_local_orders", "kalshi_positions", "polymarket_us_positions"}
        }
    return value


def _install_presets(db: ControlDatabase) -> None:
    if db.list("presets"):
        return
    for name, settings in {
        "conservative": StrategySettings(
            preset="conservative", entry_threshold=0.97, trade_size=50, depth_haircut=0.5
        ),
        "balanced": StrategySettings(),
        "aggressive": StrategySettings(
            preset="aggressive", entry_threshold=0.99, trade_size=200, depth_haircut=0.8
        ),
    }.items():
        db.put("presets", name, {"id": name, "name": name, **settings.model_dump(mode="json")})


app = create_app()


def run() -> None:
    uvicorn.run(
        "live_trading.control.app:app",
        host=os.getenv("PREDICTION_MARKETS_API_HOST", "127.0.0.1"),
        port=int(os.getenv("PREDICTION_MARKETS_API_PORT", "8765")),
        reload=False,
    )
