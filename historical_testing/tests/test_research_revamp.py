from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from arb_study.adaptive_sampling import adaptive_sampling_windows
from arb_study.annual_proxy import _scan_phase, _scan_phase_checkpointed, build_annual_opportunity_windows
from arb_study.archive import (
    archive_inventory,
    available_archive_hours,
    require_raw_historical_object,
)
from arb_study.l2_analysis import find_safe_paired_exit, locked_pair_metrics, sweep_book
from arb_study.l2_replay import _apply_cross_hour_exits, run_resumable_l2_replay
from arb_study.historical_monthly import (
    _catalog_scenario_counts,
    _compact_current_kalshi_slices,
    _fetch_kalshi_current_month,
    retain_kalshi_historical_market,
)
from arb_study.models import MatchedMarket, MarketRef, OutcomeRef
from arb_study.bbo import _apply_level_update
from arb_study.official_api import KalshiOfficialClient
from arb_study.official_price_scanner import _evaluate_proxy_state
from arb_study.official_catalog import _parse_iso
from arb_study.polymarket_us_catalog import collect_public_us_catalog, summarize_public_us_catalog, write_public_us_report
from arb_study.portfolio import PortfolioRules, simulate_portfolio
from arb_study.research_pipeline import (
    write_annual_catalog_funnel,
    write_manifest_markdown,
    write_scenario_analysis_report,
    write_trade_examples_report,
)
from arb_study.scenario import (
    classify_competition_phase,
    classify_focus_scenario,
    classify_lifecycle_phase,
    classify_market_type,
)
from arb_study.strict_matching import (
    strict_equivalence_rejection,
    strict_match_rejection,
    strict_outcome_label_rejection,
)
from arb_study.serde import write_json


UTC = timezone.utc


def _match() -> MatchedMarket:
    poly = MarketRef(
        venue="polymarket",
        market_id="poly",
        title="NBA Finals: Knicks vs Celtics",
        slug="poly",
        url=None,
        category="Sports",
        resolution_date="2026-06-01T00:00:00Z",
        contract_address="0xabc",
        yes=OutcomeRef("poly-yes", "Yes"),
        no=OutcomeRef("poly-no", "No"),
    )
    kalshi = MarketRef(
        venue="kalshi",
        market_id="kalshi",
        title="NBA Finals: Knicks vs Celtics",
        slug="KXNBA",
        url=None,
        category="Sports",
        resolution_date="2026-06-01T00:00:00Z",
        contract_address=None,
        yes=OutcomeRef("KXNBA", "Yes"),
        no=OutcomeRef("KXNBA-NO", "No"),
    )
    return MatchedMarket("poly::kalshi", poly, kalshi, "identity", 1.0, None, None)


def test_archive_listing_paginates_and_inventory_rejects_missing_raw_objects(monkeypatch) -> None:
    class Response:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, params: dict, timeout: int):
        page = int(params["page"])
        venue = "polymarket" if "Polymarket" in url else "kalshi"
        prefix = "polymarket" if venue == "polymarket" else "kalshi"
        hour = "2026-05-14T14" if page == 1 else "2026-05-14T15"
        return Response(f"Page {page} of 2 {prefix}_orderbook_{hour}.parquet")

    monkeypatch.setattr("arb_study.archive.requests.get", fake_get)
    monkeypatch.setattr(
        "arb_study.archive.remote_exists",
        lambda url, timeout=15: not url.endswith("2026-05-14T15.parquet"),
    )

    assert available_archive_hours("kalshi") == ["2026-05-14T14", "2026-05-14T15"]
    inventory = archive_inventory()
    assert inventory["overlap_hours"] == 2
    assert inventory["verified_overlap_hours"] == 1
    assert inventory["hours"] == ["2026-05-14T14"]


def test_archive_guardrail_rejects_hosted_current_book_fallback() -> None:
    with pytest.raises(ValueError, match="raw verified Parquet"):
        require_raw_historical_object("https://api.pmxt.dev/fetchOrderBook?timestamp=old")


def test_strict_matching_rejects_round_line_date_and_cancellation_mismatches() -> None:
    assert strict_equivalence_rejection("World Cup round of 16", "World Cup knockout stages")
    assert strict_equivalence_rejection("Knicks +3.5 on May 31", "Knicks +4.5 on May 31")
    assert strict_equivalence_rejection("before May 31 2026", "before June 1 2026")
    assert strict_equivalence_rejection("void if postponed", "Knicks win") == "cancellation treatment requires manual review"
    assert strict_equivalence_rejection("Will Neal Shipley win the tournament?", "Will Neal Shipley make the cut?")
    assert strict_equivalence_rejection("Will William Byron win the championship?", "Will William Byron win the playoffs?")
    assert strict_match_rejection(
        "Will Charles Howell III win the 2025 LIV Golf Andalucia tournament?",
        "Will Charles Howell III win the LIV Golf DC?",
    ) == "event identity mismatch"
    assert strict_match_rejection(
        "Will Nick Taylor win the 2025 RBC Canadian Open?",
        "Will Nick Hardy win the RBC Canadian Open?",
    ) == "outcome subject mismatch"
    assert strict_match_rejection(
        "Will Roy Cooper be the Democratic nominee for Senate in North Carolina?",
        "Will Roy Cooper be the Republican nominee for Senate in North Carolina?",
    ) == "party orientation mismatch"
    assert strict_match_rejection(
        "Will Maria be on the Time person of the year shortlist?",
        "Will Maria be Time person of the year?",
    ) == "outcome stage mismatch"
    assert strict_outcome_label_rejection('Will Zohran Mamdani say "Bus"?', "Free Bus") == "quoted outcome label mismatch"
    assert strict_outcome_label_rejection('Will Keir Starmer say "Immigrant" or "Immigration"?', "Immigrant / Immigration") is None
    assert strict_equivalence_rejection("Knicks +3.5 on May 31", "Knicks +3.5 on May 31") is None


def test_scenario_taxonomy_covers_focus_phase_and_market_type() -> None:
    assert classify_focus_scenario("NBA Finals: Knicks vs Celtics") == "nba"
    assert classify_focus_scenario("ATP Wimbledon men's winner") == "atp"
    assert classify_focus_scenario("Will it rain in New York tomorrow?") == "weather"
    assert classify_focus_scenario("Will Claudia Sheinbaum Pardo be Time Person of the Year?") != "nba"
    assert classify_focus_scenario("Will Neal Shipley win the Sony Open?") != "ipl"
    assert classify_focus_scenario('Will "F1 The Album" win Best Compilation Soundtrack at the Grammys?') == "culture"
    assert classify_focus_scenario("Will This Island win at the Film Independent Spirit Awards?") == "culture"
    assert classify_focus_scenario("Will Bulgaria win the televote for Eurovision 2026?") == "culture"
    assert classify_focus_scenario("Will Kai Cenat win Streamer of the Year at the 2025 Streamer Awards?") == "culture"
    assert classify_focus_scenario("Will Lando Norris win the F1 Monaco Grand Prix?") == "f1"
    assert classify_focus_scenario("2025 PGA TOUR FedEx St. Jude Championship") == "golf"
    assert classify_competition_phase("NBA playoff semifinal") == "semifinal"
    assert classify_market_type("Knicks -3.5 point spread") == "spread"
    assert classify_market_type("Will total points be over 214.5?") == "total_or_threshold"


def test_adaptive_sampling_uses_sports_and_non_sports_regimes() -> None:
    end = datetime(2026, 5, 31, tzinfo=UTC)
    sports = adaptive_sampling_windows(
        end - timedelta(days=10),
        end,
        is_sports=True,
        event_start=end - timedelta(hours=3),
    )
    assert [(item.label, item.interval_minutes) for item in sports] == [
        ("sports_pregame_slow", 60),
        ("sports_pregame_final_24h", 5),
        ("sports_in_play", 1),
    ]
    unknown_sports_start = adaptive_sampling_windows(
        end - timedelta(days=10),
        end,
        is_sports=True,
    )
    assert [(item.label, item.interval_minutes) for item in unknown_sports_start] == [
        ("sports_pregame_slow", 60),
        ("sports_event_start_unavailable_final_24h", 5),
    ]
    lifecycle = adaptive_sampling_windows(end - timedelta(days=90), end, is_sports=False)
    assert [item.interval_minutes for item in lifecycle] == [1440, 60, 5]
    assert classify_lifecycle_phase(
        end - timedelta(hours=1),
        end,
        is_sports=True,
    ) == "sports_near_close_in_play_proxy"
    assert classify_lifecycle_phase(
        end - timedelta(days=10),
        end,
        is_sports=False,
    ) == "lifecycle_30d_to_24h"


def test_l2_sweep_reports_vwap_slippage_and_depth_shortage() -> None:
    sweep = sweep_book([(0.40, 5), (0.42, 10)], 10)
    assert sweep.fully_filled
    assert sweep.vwap == pytest.approx(0.41)
    assert sweep.book_slippage_per_contract == pytest.approx(0.01)
    short = locked_pair_metrics([(0.40, 3)], [(0.50, 10)], 5)
    assert short.net_edge_per_contract is None


def test_polymarket_delta_update_replaces_and_removes_ladder_levels() -> None:
    assert sorted(_apply_level_update([(0.40, 5)], 0.42, 8)) == [(0.40, 5), (0.42, 8)]
    assert _apply_level_update([(0.40, 5)], 0.40, 0) == []


def test_paired_exit_requires_threshold_and_falls_back_to_locked_profit() -> None:
    entry = datetime(2026, 5, 31, tzinfo=UTC)
    no_exit = find_safe_paired_exit(
        entry_time=entry,
        locked_hold_profit_per_contract=0.02,
        size_contracts=10,
        later_books=[(entry + timedelta(seconds=1), [(0.51, 10)], [(0.497, 10)], 0.0)],
    )
    assert not no_exit.qualifies
    assert no_exit.locked_hold_profit_per_contract == 0.02
    exit_result = find_safe_paired_exit(
        entry_time=entry,
        locked_hold_profit_per_contract=0.02,
        size_contracts=10,
        later_books=[(entry + timedelta(seconds=2), [(0.51, 10)], [(0.498, 10)], 0.0)],
    )
    assert exit_result.qualifies
    assert exit_result.improvement_per_contract == pytest.approx(0.008)


def test_cross_hour_exit_stitching_uses_later_checkpoint() -> None:
    windows = [
        {
            "match_id": "a",
            "direction": "poly_yes__kalshi_no",
            "size_contracts": 10,
            "start": "2026-05-31T00:59:59+00:00",
            "entry_cost_per_contract": 0.90,
            "entry_fee_total": 0.0,
            "locked_hold_profit_per_contract": 0.10,
            "paired_exit_qualifies": False,
        }
    ]
    exits = [
        {
            "match_id": "a",
            "direction": "poly_yes__kalshi_no",
            "size_contracts": 10,
            "timestamp": "2026-05-31T01:00:01+00:00",
            "proceeds_per_contract": 1.008,
            "exit_fee_total": 0.0,
        }
    ]
    _apply_cross_hour_exits(windows, exits)
    assert windows[0]["paired_exit_qualifies"]
    assert windows[0]["paired_exit_seconds"] == 2


def test_l2_resume_retries_errored_hour_checkpoint(tmp_path: Path, monkeypatch) -> None:
    checkpoint = tmp_path / "2026-05-31T00.json"
    write_json(checkpoint, {"hour": "2026-05-31T00", "error": "transient", "windows": []})
    calls = []

    def fake_scan(*args, **kwargs):
        calls.append(True)
        return {
            "hour": "2026-05-31T00",
            "summary": {"aligned_points": 0, "net_positive_windows": 0},
            "windows": [],
            "exit_candidates": [],
        }

    monkeypatch.setattr("arb_study.l2_replay.scan_l2_hour", fake_scan)
    result = run_resumable_l2_replay([], ["2026-05-31T00"], tmp_path, resume=True)
    assert calls == [True]
    assert result["parameters"]["hour_errors"] == 0


def test_annual_proxy_uses_pair_level_slippage_sensitivity() -> None:
    state = {
        "timestamp": "2026-05-31T00:00:00+00:00",
        "kalshi_yes_ask": 0.20,
        "kalshi_no_ask": 0.80,
        "poly_yes_price": 0.75,
        "poly_no_price": 0.70,
    }
    one_cent = _evaluate_proxy_state(_match(), state, "sports", "pregame", 100, 0.005, "taker", 0.05, 0.01)
    five_cents = _evaluate_proxy_state(_match(), state, "sports", "pregame", 100, 0.005, "taker", 0.05, 0.05)
    assert one_cent[0].net_edge_per_contract - five_cents[0].net_edge_per_contract == pytest.approx(0.04)


def test_annual_proxy_downloads_once_then_evaluates_each_slippage_case(monkeypatch) -> None:
    calls = {"kalshi": 0, "polymarket": 0}

    class Kalshi:
        def market_candlesticks_auto(self, *args):
            calls["kalshi"] += 1
            return []

    class Polymarket:
        def prices_history(self, *args):
            calls["polymarket"] += 1
            return []

    monkeypatch.setattr("arb_study.annual_proxy.KalshiOfficialClient", Kalshi)
    monkeypatch.setattr("arb_study.annual_proxy.PolymarketOfficialClient", Polymarket)
    start = datetime(2026, 5, 30, tzinfo=UTC)
    records, opportunities = _scan_phase(
        _match(),
        "sports_pregame_final_24h",
        start,
        start + timedelta(hours=1),
        5,
        [0.01, 0.02, 0.05],
        100,
        0.005,
        "taker",
        0.05,
    )
    assert calls == {"kalshi": 1, "polymarket": 2}
    assert [item["pair_slippage_assumption"] for item in records] == [0.01, 0.02, 0.05]
    assert opportunities == []


def test_annual_proxy_phase_checkpoint_resumes_completed_request(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_scan(*args, **kwargs):
        calls.append(True)
        return ([{"match_id": "poly::kalshi"}], [{"match_id": "poly::kalshi", "net_edge_per_contract": 0.01}])

    monkeypatch.setattr("arb_study.annual_proxy._scan_phase", fake_scan)
    arguments = (
        _match(),
        "sports_in_play",
        datetime(2026, 5, 31, tzinfo=UTC),
        datetime(2026, 5, 31, 1, tzinfo=UTC),
        1,
        [0.01],
        100,
        0.005,
        "taker",
        0.05,
        tmp_path,
        True,
    )
    assert _scan_phase_checkpointed(*arguments)[0] == [{"match_id": "poly::kalshi"}]
    assert _scan_phase_checkpointed(*arguments)[0] == [{"match_id": "poly::kalshi"}]
    assert calls == [True]


def test_annual_proxy_windows_preserve_range_and_best_timestamp() -> None:
    base = {
        "match_id": "a",
        "direction": "poly_yes__kalshi_no_proxy",
        "phase": "sports_in_play",
        "pair_slippage_assumption": 0.01,
        "gross_edge_per_contract": 0.05,
        "roi_on_entry_cost": 0.04,
        "polymarket_title": "NBA game",
        "kalshi_title": "NBA game",
        "yes_venue": "polymarket",
        "no_venue": "kalshi",
        "yes_price": 0.40,
        "no_price": 0.50,
        "total_cost": 0.90,
        "total_fee": 0.01,
    }
    windows = build_annual_opportunity_windows(
        [
            {**base, "timestamp": "2026-05-31T00:00:00+00:00", "net_edge_per_contract": 0.03},
            {**base, "timestamp": "2026-05-31T00:01:00+00:00", "net_edge_per_contract": 0.04},
            {**base, "timestamp": "2026-05-31T00:05:00+00:00", "net_edge_per_contract": 0.02},
        ]
    )
    assert len(windows) == 2
    assert windows[0]["window_start"] == "2026-05-31T00:00:00+00:00"
    assert windows[0]["window_end"] == "2026-05-31T00:01:00+00:00"
    assert windows[0]["best_timestamp"] == "2026-05-31T00:01:00+00:00"
    assert windows[0]["profitable_snapshots"] == 2


def test_kalshi_candlestick_auto_prefers_historical_route_for_old_window(monkeypatch) -> None:
    calls = []

    class Client(KalshiOfficialClient):
        def __init__(self):
            pass

        def historical_market_candlesticks(self, *args):
            calls.append("historical")
            return []

        def market_candlesticks(self, *args):
            calls.append("live")
            return []

    monkeypatch.setattr("arb_study.official_api.time.time", lambda: 2_000_000)
    Client().market_candlesticks_auto("KXNBA", 1_000_000, 1_500_000)
    assert calls == ["historical"]


def test_historical_catalog_retention_skips_only_repetitive_high_frequency_families() -> None:
    assert not retain_kalshi_historical_market({"ticker": "KXBTC-26JUN011230-T105000"})
    assert not retain_kalshi_historical_market({"event_ticker": "KXNASDAQ100U-26JUN0113"})
    assert retain_kalshi_historical_market({"ticker": "KXNBAGAME-26JUN01NYKBOS-NYK"})
    assert retain_kalshi_historical_market({"ticker": "KXTEMPNYCH-26JUN01-T80"})
    assert retain_kalshi_historical_market({"ticker": "KXFEDDECISION-26JUN"})


def test_catalog_audit_classifies_focus_category_from_ticker_when_title_is_sparse() -> None:
    counts = _catalog_scenario_counts(
        [{"ticker": "KXNBAGAME-26JUN01NYKBOS-NYK", "title": "New York at Boston"}]
    )
    assert counts["focus"]["nba"] == 1


def test_current_kalshi_month_uses_same_research_scope_retention() -> None:
    class Client:
        def markets(self, **kwargs):
            return {
                "markets": [
                    {"ticker": "KXBTC-26JUN011230-T105000"},
                    {"ticker": "KXNBAGAME-26JUN01NYKBOS-NYK"},
                ],
                "cursor": None,
            }

    payload = _fetch_kalshi_current_month(
        Client(),
        datetime(2026, 5, 1, tzinfo=UTC),
        datetime(2026, 6, 1, tzinfo=UTC),
        10,
    )
    assert payload["fetched_markets"] == 2
    assert payload["skipped_out_of_scope_markets"] == 1
    assert [item["ticker"] for item in payload["markets"]] == ["KXNBAGAME-26JUN01NYKBOS-NYK"]


def test_existing_current_kalshi_slice_compacts_before_resume(tmp_path: Path) -> None:
    cache = {
        "kalshi_months": {
            "2026-05": {
                "start": "2026-05-01T00:00:00Z",
                "markets": [
                    {"ticker": "KXBTC-26MAY011230-T105000"},
                    {"ticker": "KXNBAGAME-26MAY01NYKBOS-NYK"},
                ],
            }
        }
    }
    target = tmp_path / "cache.json"
    _compact_current_kalshi_slices(cache, target, datetime(2026, 4, 1, tzinfo=UTC))
    month = cache["kalshi_months"]["2026-05"]
    assert month["market_count"] == 1
    assert month["fetched_markets"] == 2
    assert month["skipped_out_of_scope_markets"] == 1


def test_official_catalog_parser_accepts_variable_fractional_second_precision() -> None:
    parsed = _parse_iso("2026-01-28T22:55:46.4096+00:00")
    assert parsed.microsecond == 409600


def test_official_catalog_parser_accepts_short_utc_offset() -> None:
    parsed = _parse_iso("2025-11-30 16:00:00+00")
    assert parsed.utcoffset().total_seconds() == 0


def test_portfolio_keeps_cash_locked_and_allows_only_one_active_position_per_pair() -> None:
    opportunities = [
        {
            "match_id": "a",
            "start": "2026-05-31T00:00:00+00:00",
            "settlement_at": "2026-05-31T01:00:00+00:00",
            "entry_cost_per_contract": 0.90,
            "net_profit_per_contract": 0.10,
            "depth_contracts": 1000,
        },
        {
            "match_id": "a",
            "start": "2026-05-31T00:01:00+00:00",
            "settlement_at": "2026-05-31T01:00:00+00:00",
            "entry_cost_per_contract": 0.90,
            "net_profit_per_contract": 0.10,
            "depth_contracts": 1000,
        },
        {
            "match_id": "b",
            "start": "2026-05-31T00:02:00+00:00",
            "settlement_at": "2026-05-31T01:00:00+00:00",
            "entry_cost_per_contract": 0.90,
            "net_profit_per_contract": 0.10,
            "depth_contracts": 1000,
        },
    ]
    result = simulate_portfolio(
        opportunities,
        contracts=1000,
        rules=PortfolioRules(starting_bankroll=1000, position_cap_share=1.0),
        enforce_depth=True,
    )
    assert result["accepted_positions"] == 1
    assert result["rejected"] == {"cash": 1, "depth": 0, "already_active": 1, "non_positive": 0}
    assert result["ending_bankroll"] == pytest.approx(1100)


def test_public_us_catalog_resume_and_disclosure(tmp_path: Path) -> None:
    class Client:
        def sports(self):
            return [{"id": "nba"}]

        def page(self, path: str, *, limit: int, offset: int, **params):
            rows = [{"id": str(index), "title": "NBA game", "markets": []} for index in range(offset, 3)]
            return rows[:limit]

        def book(self, slug: str):
            return {}

        def settlement(self, slug: str):
            return {}

    cache_path = tmp_path / "catalog.json"
    first = collect_public_us_catalog(cache_path, page_size=1, max_pages=1, client=Client())
    assert first["crawl"]["events"]["next_offset"] == 1
    second = collect_public_us_catalog(cache_path, page_size=1, max_pages=1, client=Client())
    assert second["crawl"]["events"]["next_offset"] == 2
    summary = summarize_public_us_catalog(second)
    assert any("must not be read" in item for item in summary["limitations"])


def test_reports_keep_evidence_labels_and_missing_data_disclosures(tmp_path: Path) -> None:
    manifest_path = tmp_path / "coverage.md"
    write_manifest_markdown(
        {
            "generated_at": "2026-05-31T00:00:00Z",
            "requested_window": {"start": "2025-05-31T00:00:00Z", "end": "2026-05-31T00:00:00Z"},
            "evidence_layers": {
                "international_official_api": {
                    "combined_catalog_scope": "bounded_retained_screen",
                    "proxy_scan_scope": "bounded_stratified_screen",
                    "months": [
                        {
                            "month": "2026-05",
                            "kalshi_truncated": True,
                            "polymarket_truncated": True,
                        }
                    ],
                }
            },
            "limitations": ["Public Polymarket US APIs do not expose retrospective quote-by-quote profitability data."],
        },
        manifest_path,
    )
    examples_path = tmp_path / "examples.md"
    write_trade_examples_report(
        {
            "note": "Strict candidates require manual review.",
            "examples": [],
        },
        examples_path,
    )
    assert "historical price proxy" in manifest_path.read_text(encoding="utf-8")
    assert "must not be used as a retrospective profit report" in manifest_path.read_text(encoding="utf-8")
    assert "2026-05: Kalshi and Polymarket" in manifest_path.read_text(encoding="utf-8")
    assert "No profitable example found." in examples_path.read_text(encoding="utf-8")


def test_reader_reports_define_jargon_and_omit_unprofitable_examples(tmp_path: Path) -> None:
    manifest = {
        "requested_window": {"start": "2025-05-31T00:00:00Z", "end": "2026-05-31T00:00:00Z"},
        "evidence_layers": {"international_pmxt_l2": {"verified_overlap_hours": 259}},
    }
    payload = {"note": "positive only", "examples": []}
    scenario_path = tmp_path / "scenario.md"
    write_scenario_analysis_report(manifest, payload, None, None, scenario_path)
    scenario_text = scenario_path.read_text(encoding="utf-8")
    assert "Parquet" in scenario_text
    assert "storage format, not a trading strategy" in scenario_text
    assert "No profitable example found." in scenario_text
    assert "Inventory alone is not a profit result." in scenario_text

    us_path = tmp_path / "us.md"
    write_public_us_report(
        {
            "events": 0,
            "unique_embedded_markets": 0,
            "open_flat_markets": 0,
            "closed_flat_markets": 0,
            "sports_configurations": 0,
            "terminal_summaries_collected": 0,
            "earliest_event_created_at": None,
            "crawl_status": {},
            "scenarios": [],
            "market_types": {},
            "limitations": ["No historical quote-by-quote order books."],
        },
        us_path,
        "reports/coverage_manifest.md",
    )
    us_text = us_path.read_text(encoding="utf-8")
    assert "catalog census, not a profit ranking" in us_text
    assert "**Terminal summary**" in us_text


def test_annual_catalog_funnel_explains_retained_rows_and_strict_pairs(tmp_path: Path) -> None:
    target = tmp_path / "funnel.md"
    funnel = write_annual_catalog_funnel(
        {
            "parameters": {
                "catalog_meta": {
                    "kalshi_catalog_markets": 10,
                    "polymarket_catalog_markets": 20,
                    "matched_pairs": 3,
                    "kalshi_catalog_focus_scenarios": {"nba": 4},
                    "polymarket_catalog_focus_scenarios": {"nba": 6},
                },
                "strict_title_rejections": [{"match_id": "bad"}],
                "eligible_strict_pairs": 2,
                "selected_markets": 2,
                "phase_scan_tasks": 4,
            },
            "phase_records": [{"match_id": "good", "aligned_points": 5}],
            "opportunities": [],
            "opportunity_windows": [],
            "errors": [],
        },
        target,
    )
    text = target.read_text(encoding="utf-8")
    assert funnel["eligible_strict_pairs"] == 2
    assert "Kalshi retained catalog rows indexed" in text
    assert "| `nba` | 4 | 6 |" in text
