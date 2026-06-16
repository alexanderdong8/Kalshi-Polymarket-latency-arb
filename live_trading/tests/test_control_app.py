from __future__ import annotations

from datetime import datetime, timezone
from types import MethodType
from types import SimpleNamespace

from fastapi.testclient import TestClient

from live_trading.control.app import create_app
from live_trading.control.db import ControlDatabase
from live_trading.control.schemas import Candidate, OutcomeMapping, RankingBreakdown, WorkerState
from live_trading.models import VenueMarket


def test_health_and_settings_do_not_expose_secrets(tmp_path):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        payload = client.get("/api/settings").json()
        assert set(payload["credentials"]) == {"kalshi", "polymarket_us"}
        assert "secret" not in str(payload).lower()


def test_startup_marks_abandoned_scan_jobs_failed(tmp_path):
    db_path = tmp_path / "control.sqlite3"
    db = ControlDatabase(db_path)
    db.put(
        "scan_jobs",
        "abandoned",
        {
            "id": "abandoned",
            "status": "matching",
            "progress": 0.3,
            "message": "Generating event-level matches and assigning outcomes",
            "candidate_count": 0,
            "errors": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        },
    )
    app = create_app(tmp_path, db_path)

    with TestClient(app) as client:
        payload = client.get("/api/scans/abandoned").json()

    assert payload["status"] == "failed"
    assert "interrupted" in payload["message"]


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


def test_search_add_prepare_approve_flow_does_not_create_scan_jobs(tmp_path, monkeypatch):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")

    class FakeOddpool:
        available = True

        async def event_markets(self, _event_id):
            raise AssertionError("Prepare review should use direct venue fetch.")

        async def search_markets(self, **_kwargs):
            raise AssertionError("Prepare review should use direct venue fetch.")

    class DirectKalshi:
        def __init__(self, _settings):
            pass

        async def fetch_event_markets(self, _event_ticker):
            return [
                _venue_market("kalshi", "K-LAL", "Lakers vs Celtics winner", "Lakers", "K"),
                _venue_market("kalshi", "K-BOS", "Lakers vs Celtics winner", "Celtics", "K"),
            ]

    async def direct_gamma(_slug):
        return [
            _venue_market(
                "polymarket_us",
                "p-lal",
                "Lakers vs Celtics winner",
                "Lakers",
                "P",
                slug="lakers-win",
            ),
            _venue_market(
                "polymarket_us",
                "p-bos",
                "Lakers vs Celtics winner",
                "Celtics",
                "P",
                slug="celtics-win",
            ),
        ]

    class FakeLLM:
        available = True

        async def review(self, _payload):
            return SimpleNamespace(
                equivalent_event=True,
                exhaustive_outcomes=True,
                confidence=0.99,
                reasoning="Equivalent event and settlement scope.",
                warnings=[],
            )

    async def fake_hydrate(self, candidate, _pair):
        candidate.ranking.mapping_confidence = 0.99

    import live_trading.scanner.service as scanner_service

    monkeypatch.setattr(scanner_service, "KalshiClient", DirectKalshi)
    monkeypatch.setattr(scanner_service, "_fetch_polymarket_gamma_event_markets", direct_gamma)

    with TestClient(app) as client:
        app.state.scanner.oddpool = FakeOddpool()
        app.state.scanner.llm = FakeLLM()
        app.state.scanner._hydrate_market_quality = MethodType(
            fake_hydrate, app.state.scanner
        )

        suggestion = {
            "id": "oddpool-lakers-celtics",
            "name": "Lakers vs Celtics winner",
            "category": "sports",
            "outcome_count": 2,
            "mapping_confidence": 0.95,
            "kalshi_outcomes": ["Lakers", "Celtics"],
            "polymarket_outcomes": ["Lakers", "Celtics"],
            "warnings": [],
            "source": "oddpool",
            "venues": ["kalshi", "polymarket"],
            "provider_event_ids": {
                "kalshi": "kalshi-event",
                "polymarket": "polymarket-event",
            },
            "provider_series_ids": {},
            "primary_exchange": "kalshi",
            "total_volume": 1000,
            "total_liquidity": 500,
        }
        first = client.post("/api/basket", json={"suggestion": suggestion})
        second = client.post(
            "/api/basket",
            json={"suggestion": {**suggestion, "id": "oddpool-lakers-celtics-2"}},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert len(client.get("/api/basket").json()) == 2
        assert client.get("/api/scans").json() == []

        prepared = client.post(f"/api/basket/{first.json()['id']}/prepare-review")

        assert prepared.status_code == 200
        assert prepared.json()["status"] == "review_ready"
        candidate_id = prepared.json()["candidate_id"]
        assert candidate_id
        candidate = client.get(f"/api/candidates/{candidate_id}").json()
        assert candidate["exhaustive"] is True
        assert candidate["llm_status"] == "passed"

        approved = client.post(
            f"/api/candidates/{candidate_id}/approve",
            json={"exhaustive": True, "settlement_reviewed": True},
        )
        assert approved.status_code == 200
        assert client.get("/api/events").json()[0]["id"] == candidate_id


def test_prepare_review_blocks_incomplete_oddpool_match(tmp_path):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")

    class OneVenueOddpool:
        available = True

        async def event_markets(self, _event_id):
            return [
                {
                    "market_id": "kalshi-a",
                    "exchange": "kalshi",
                    "event_id": "kalshi-event",
                    "event_title": "Single venue event",
                    "question": "Single venue event",
                    "outcome": "Yes",
                }
            ]

        async def search_markets(self, **_kwargs):
            return []

    with TestClient(app) as client:
        app.state.scanner.oddpool = OneVenueOddpool()
        added = client.post(
            "/api/basket",
            json={
                "suggestion": {
                    "id": "one-venue",
                    "name": "Single venue event",
                    "outcome_count": 1,
                    "mapping_confidence": 0.5,
                    "source": "oddpool",
                    "venues": ["kalshi"],
                    "provider_event_ids": {"kalshi": "kalshi-event"},
                }
            },
        )

        prepared = client.post(f"/api/basket/{added.json()['id']}/prepare-review")

        assert prepared.status_code == 200
        assert prepared.json()["status"] == "needs_opposite_venue"
        assert prepared.json()["candidate_id"] is None


def test_prepare_review_prefers_direct_venue_fetch_over_oddpool(tmp_path, monkeypatch):
    app = create_app(tmp_path, tmp_path / "control.sqlite3")

    class FailingOddpool:
        available = True

        async def event_markets(self, _event_id):
            raise AssertionError("Oddpool event-markets should not be used for prepared entries.")

        async def search_markets(self, **_kwargs):
            raise AssertionError("Oddpool search-markets should not be used for prepared entries.")

    class DirectKalshi:
        def __init__(self, _settings):
            pass

        async def fetch_event_markets(self, _event_ticker):
            return [
                _venue_market("kalshi", "K-IRQ", "Iraq vs Norway Winner?", "Iraq", "K"),
                _venue_market("kalshi", "K-NOR", "Iraq vs Norway Winner?", "Norway", "K"),
                _venue_market("kalshi", "K-TIE", "Iraq vs Norway Winner?", "Tie", "K"),
            ]

    async def direct_gamma(_slug):
        return [
            _venue_market(
                "polymarket_us",
                "p-irq",
                "Iraq vs. Norway",
                "Iraq",
                "P",
                slug="iraq-win",
            ),
            _venue_market(
                "polymarket_us",
                "p-nor",
                "Iraq vs. Norway",
                "Norway",
                "P",
                slug="norway-win",
            ),
            _venue_market(
                "polymarket_us",
                "p-tie",
                "Iraq vs. Norway",
                "Tie",
                "P",
                slug="draw",
            ),
        ]

    class FakeLLM:
        available = True

        async def review(self, _payload):
            return SimpleNamespace(
                equivalent_event=True,
                exhaustive_outcomes=True,
                confidence=0.99,
                reasoning="Equivalent event and settlement scope.",
                warnings=[],
            )

    async def fake_hydrate(self, candidate, _pair):
        candidate.ranking.mapping_confidence = 0.99

    import live_trading.scanner.service as scanner_service

    monkeypatch.setattr(scanner_service, "KalshiClient", DirectKalshi)
    monkeypatch.setattr(scanner_service, "_fetch_polymarket_gamma_event_markets", direct_gamma)

    with TestClient(app) as client:
        app.state.scanner.oddpool = FailingOddpool()
        app.state.scanner.llm = FakeLLM()
        app.state.scanner._hydrate_market_quality = MethodType(
            fake_hydrate, app.state.scanner
        )
        added = client.post(
            "/api/basket",
            json={
                "suggestion": {
                    "id": "direct-iraq-norway",
                    "name": "Iraq vs Norway",
                    "outcome_count": 3,
                    "mapping_confidence": 0.95,
                    "source": "oddpool",
                    "venues": ["kalshi", "polymarket"],
                    "provider_event_ids": {
                        "kalshi": "KXWCGAME-26JUN16IRQNOR",
                        "polymarket": "fifwc-irq-nor-2026-06-16",
                    },
                }
            },
        )
        assert client.get("/api/scans").json() == []

        prepared = client.post(f"/api/basket/{added.json()['id']}/prepare-review")

        assert prepared.status_code == 200
        assert prepared.json()["status"] == "review_ready"
        candidate = client.get(f"/api/candidates/{prepared.json()['candidate_id']}").json()
        assert candidate["exhaustive"] is True
        assert len(candidate["mappings"]) == 3
        assert {row["name"] for row in candidate["mappings"]} == {"Iraq", "Norway", "Tie"}


def _venue_market(
    venue: str,
    market_id: str,
    title: str,
    yes_label: str,
    event_id: str,
    *,
    slug: str | None = None,
) -> VenueMarket:
    return VenueMarket(
        venue=venue,  # type: ignore[arg-type]
        market_id=market_id,
        ticker=market_id if venue == "kalshi" else None,
        slug=slug or market_id,
        title=title,
        category="sports",
        market_type="moneyline",
        start_time=datetime(2026, 6, 16, tzinfo=timezone.utc),
        close_time=datetime(2026, 6, 17, tzinfo=timezone.utc),
        expiration_time=datetime(2026, 6, 17, tzinfo=timezone.utc),
        yes_label=yes_label,
        no_label="No",
        description=title,
        rules=title,
        raw={
            "event_ticker" if venue == "kalshi" else "eventId": event_id,
            "event_title": title,
            "outcome_side": "long",
        },
    )
