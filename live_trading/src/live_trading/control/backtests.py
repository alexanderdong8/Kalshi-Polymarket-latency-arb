from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from backtesting.pmxt import load_updates, validate_coverage
from backtesting.simulator import result_payload, run_delay_matrix
from live_trading.strategy.manifest import load_event_manifest

from .db import ControlDatabase
from .hub import EventHub
from .schemas import BacktestJob, BacktestRequest


def now() -> datetime:
    return datetime.now(timezone.utc)


class BacktestService:
    def __init__(self, db: ControlDatabase, hub: EventHub) -> None:
        self.db = db
        self.hub = hub
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, request: BacktestRequest) -> BacktestJob:
        event = self.db.get("watchlist", request.event_id)
        if not event:
            raise KeyError(request.event_id)
        job = BacktestJob(
            id=uuid.uuid4().hex,
            event_id=request.event_id,
            event_name=event["name"],
            status="queued",
            starting_cash=request.starting_cash,
            created_at=now(),
        )
        self.db.put("backtests", job.id, job.model_dump(mode="json"))
        self._tasks[job.id] = asyncio.create_task(
            self._run(job, event, request), name=f"backtest-{job.id}"
        )
        return job

    async def _run(
        self,
        job: BacktestJob,
        event: dict[str, Any],
        request: BacktestRequest,
    ) -> None:
        try:
            await self._update(job, status="validating", progress=0.1)
            manifest_path = Path(event["manifest_path"])
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            historical = raw.get("historical") or {}
            archive = historical.get("archive") or {}
            reasons = _availability_reasons(event, archive)
            if reasons:
                await self._update(
                    job,
                    status="unavailable",
                    progress=1,
                    unavailable_reasons=reasons,
                    completed_at=now(),
                )
                return
            manifest = load_event_manifest(manifest_path, require_approved=True)
            updates = await asyncio.to_thread(load_updates, manifest, archive)
            coverage = validate_coverage(manifest, updates)
            if not coverage["valid"]:
                reasons = [
                    *[f"Missing book: {name}" for name in coverage["missing_books"]],
                    *(["Updates are out of timestamp order."] if coverage["out_of_order"] else []),
                    *(
                        ["Outcome books do not have overlapping L2 coverage."]
                        if not coverage["overlap_start"]
                        else []
                    ),
                ]
                await self._update(
                    job,
                    status="unavailable",
                    progress=1,
                    unavailable_reasons=reasons,
                    completed_at=now(),
                )
                return
            await self._update(job, status="running", progress=0.35)
            results = await asyncio.to_thread(
                run_delay_matrix,
                manifest,
                updates,
                target_size=Decimal(str(historical.get("target_size") or 100)),
            )
            base = Decimal("1000")
            scale = Decimal(str(request.starting_cash)) / base
            result_rows = []
            for result in results:
                row = result_payload(result)
                row["starting_cash"] = str(request.starting_cash)
                row["ending_cash"] = str(Decimal(row["ending_cash"]) * scale)
                row["total_money_gained"] = str(Decimal(row["total_money_gained"]) * scale)
                row["roi"] = str(
                    Decimal(row["total_money_gained"]) / Decimal(str(request.starting_cash))
                )
                row["max_drawdown"] = "0"
                result_rows.append(row)
            result = {
                "coverage": coverage,
                "venue_split": "PMXT Kalshi + international Polymarket",
                "results": result_rows,
            }
            await self._update(
                job,
                status="complete",
                progress=1,
                result=result,
                completed_at=now(),
            )
        except Exception as exc:
            await self._update(
                job,
                status="failed",
                progress=1,
                unavailable_reasons=[str(exc)],
                completed_at=now(),
            )

    async def _update(self, job: BacktestJob, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        payload = job.model_dump(mode="json")
        self.db.put("backtests", job.id, payload)
        await self.hub.publish("backtest.updated", payload)


def _availability_reasons(event: dict[str, Any], archive: dict[str, Any]) -> list[str]:
    reasons = []
    mappings = event.get("mappings") or []
    for mapping in mappings:
        if not mapping.get("polymarket_contract_address"):
            reasons.append(f"{mapping['name']}: missing international Polymarket contract address.")
        if not mapping.get("polymarket_yes_token_id"):
            reasons.append(f"{mapping['name']}: missing international Polymarket YES token ID.")
    if not archive.get("hours") and not archive.get("fixture"):
        reasons.append("No PMXT archive hours or deterministic replay fixture are configured.")
    return reasons
