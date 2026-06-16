from __future__ import annotations

from datetime import datetime, timezone
from types import MethodType

from fastapi.testclient import TestClient

from live_trading.control.app import create_app
from live_trading.control.schemas import Candidate, OutcomeMapping, RankingBreakdown, WorkerState


def test_health_and_settings_do_not_expose_secrets(tmp_path):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        payload = client.get("/api/settings").json()
        assert set(payload["credentials"]) == {"kalshi", "polymarket_us"}
        assert "secret" not in str(payload).lower()


def test_approval_requires_human_review_and_passing_llm(tmp_path):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")
    candidate = Candidate(
        id="complete-event",
        name="Complete Event",
        mappings=[
            OutcomeMapping(
                name="A",
                kalshi_ticker="K-A",
                polymarket_us_slug="p-a",
            ),
            OutcomeMapping(
                name="B",
                kalshi_ticker="K-B",
                polymarket_us_slug="p-b",
            ),
        ],
        exhaustive=True,
        deterministic_checks={
            "at_least_two_outcomes": True,
            "unique_kalshi_contracts": True,
            "unique_polymarket_contracts": True,
            "no_known_rule_conflicts": True,
        },
        llm_status="passed",
        llm_confidence=0.98,
        llm_reasoning="Equivalent event and settlement scope.",
        ranking=RankingBreakdown(mapping_confidence=0.98),
        updated_at=datetime.now(timezone.utc),
    )
    app.state.db.put("candidates", candidate.id, candidate.model_dump(mode="json"))
    with TestClient(app) as client:
        rejected = client.post(
            f"/api/candidates/{candidate.id}/approve",
            json={"exhaustive": False, "settlement_reviewed": True},
        )
        assert rejected.status_code == 409
        approved = client.post(
            f"/api/candidates/{candidate.id}/approve",
            json={"exhaustive": True, "settlement_reviewed": True},
        )
        assert approved.status_code == 200
        assert approved.json()["approval_version"]
        assert client.get("/api/events").json()[0]["id"] == candidate.id


def test_live_activation_requires_exact_confirmation(tmp_path):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")
    app.state.db.put(
        "watchlist",
        "event",
        {
            "id": "event",
            "name": "Event",
            "slug": "event",
            "manifest_path": str(tmp_path / "missing.yaml"),
        },
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/events/event/live/start",
            json={
                "event_id": "event",
                "mode": "live",
                "budget": 100,
                "strategy": {},
                "confirmation": "live",
            },
        )
        assert response.status_code == 409


def test_approved_event_can_enter_modes_without_real_live_orders(tmp_path):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")
    candidate = Candidate(
        id="flow-event",
        name="Flow Event",
        mappings=[
            OutcomeMapping(name="A", kalshi_ticker="K-A", polymarket_us_slug="p-a"),
            OutcomeMapping(name="B", kalshi_ticker="K-B", polymarket_us_slug="p-b"),
        ],
        exhaustive=True,
        deterministic_checks={
            "at_least_two_outcomes": True,
            "unique_kalshi_contracts": True,
            "unique_polymarket_contracts": True,
            "no_known_rule_conflicts": True,
        },
        llm_status="passed",
        llm_confidence=0.98,
        llm_reasoning="Equivalent event and settlement scope.",
        ranking=RankingBreakdown(mapping_confidence=0.98),
        updated_at=datetime.now(timezone.utc),
    )
    app.state.db.put("candidates", candidate.id, candidate.model_dump(mode="json"))

    async def fake_start_worker(self, configuration, *, manifest_path, confirmed, auto_resume=False):
        state = WorkerState(
            id=f"{configuration.event_id}-{configuration.mode}",
            event_id=configuration.event_id,
            event_name="Flow Event",
            mode=configuration.mode,
            budget=configuration.budget,
            status="running",
            started_at=datetime.now(timezone.utc),
            heartbeat_at=datetime.now(timezone.utc),
            state={"manifest_path": str(manifest_path), "confirmed": confirmed},
        )
        self.db.put("workers", state.id, state.model_dump(mode="json"))
        return state

    async def fake_live_preview(self, event_id, budget):
        return {
            "event": app.state.db.get("watchlist", event_id),
            "budget": budget,
            "maximum_new_exposure": budget,
            "reconciliation": {
                "kalshi_balance": "1000",
                "polymarket_us_balance": "500",
                "unresolved_local_orders": [],
                "local_open_positions": [],
                "kalshi_positions": [],
                "polymarket_us_positions": [],
            },
            "warnings": [],
        }

    app.state.supervisor.start_worker = MethodType(fake_start_worker, app.state.supervisor)
    app.state.supervisor.live_preview = MethodType(fake_live_preview, app.state.supervisor)

    with TestClient(app) as client:
        approved = client.post(
            f"/api/candidates/{candidate.id}/approve",
            json={"exhaustive": True, "settlement_reviewed": True},
        )
        assert approved.status_code == 200
        assert client.get("/api/events").json()[0]["id"] == candidate.id

        paper = client.post(
            f"/api/events/{candidate.id}/paper/start",
            json={"event_id": candidate.id, "mode": "paper", "budget": 105, "strategy": {}},
        )
        assert paper.status_code == 200
        assert paper.json()["mode"] == "paper"

        preview = client.post(f"/api/events/{candidate.id}/live/preview?budget=100")
        assert preview.status_code == 200
        assert preview.json()["reconciliation"]["kalshi_balance"] == "1000"

        rejected_live = client.post(
            f"/api/events/{candidate.id}/live/start",
            json={
                "event_id": candidate.id,
                "mode": "live",
                "budget": 100,
                "strategy": {},
                "confirmation": "live",
            },
        )
        assert rejected_live.status_code == 409

        accepted_live = client.post(
            f"/api/events/{candidate.id}/live/start",
            json={
                "event_id": candidate.id,
                "mode": "live",
                "budget": 100,
                "strategy": {},
                "confirmation": "LIVE",
            },
        )
        assert accepted_live.status_code == 200
        assert accepted_live.json()["mode"] == "live"

        backtest = client.post(
            "/api/backtests",
            json={"event_id": candidate.id, "starting_cash": 1000},
        )
        assert backtest.status_code == 200
        assert backtest.json()["status"] == "queued"
