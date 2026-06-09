from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .annual_proxy import scan_annual_official_proxy
from .archive import archive_inventory
from .historical_monthly import collect_monthly_cache, normalize_monthly_cache, write_coverage_report
from .l2_replay import run_resumable_l2_replay
from .polymarket_us_catalog import collect_public_us_catalog, summarize_public_us_catalog, write_public_us_report
from .rankings import build_leaderboards
from .serde import matched_market_from_dict, read_json, write_json
from .research_config import ADDITIONAL_DISCOVERED_SECTION, FOCUS_SCENARIOS, HEADLINE_ORDER_SIZE
from .scenario import classify_focus_scenario
from .strict_matching import strict_match_rejection


SCENARIO_DETAILS = {
    "nba": ("NBA basketball", "regular season, playoffs, finals, team, market type, pregame, and in-play"),
    "mlb": ("Major League Baseball", "regular season, postseason, team, market type, pregame, and in-play"),
    "golf": ("golf", "tournament, round, participant, placement, pre-event, and in-play"),
    "atp": ("ATP men's tennis", "tournament level, participant, match, set, pregame, and in-play"),
    "wta": ("WTA women's tennis", "tournament level, participant, match, set, pregame, and in-play"),
    "esports": ("eSports", "game title, tournament, participant, map or match market, pregame, and in-play"),
    "ipl": ("Indian Premier League cricket", "regular stage, playoffs, team, pregame, and in-play"),
    "wnba": ("WNBA basketball", "regular season, playoffs, finals, team, market type, pregame, and in-play"),
    "nhl": ("National Hockey League", "regular season, playoffs, finals, team, market type, pregame, and in-play"),
    "itf_men": ("ITF men's tennis", "tournament, participant, match, pregame, and in-play"),
    "itf_women": ("ITF women's tennis", "tournament, participant, match, pregame, and in-play"),
    "ufc": ("UFC mixed martial arts", "card, fighter, bout winner, prop, pre-event, and in-play where listed"),
    "fifa_world_cup": ("FIFA World Cup", "qualification, group, knockout round, team, winner, pre-event, and in-play"),
    "politics": ("politics", "candidate, office, cutoff date, and time remaining before settlement"),
    "weather": ("weather", "location, threshold, measurement window, and time remaining before settlement"),
    "mls": ("Major League Soccer", "regular season, playoffs, club, market type, pregame, and in-play"),
    "elections": ("elections", "district, party, nominee, winner, cutoff date, and time remaining before settlement"),
    "culture": ("culture and entertainment", "topic, event, cutoff date, and time remaining before settlement"),
    "f1": ("Formula One", "race, qualifying, driver, constructor, placement, pre-event, and in-play"),
    ADDITIONAL_DISCOVERED_SECTION: (
        "additional discovered markets",
        "recognizable markets outside the requested list, including other sports and public-event binaries",
    ),
}
SCENARIO_INTERPRETATIONS = {
    "nba": ("Frequent scoring and injury updates can create fast venue-to-venue repricing gaps.", "In-play windows can vanish quickly, and popular games may be efficiently priced."),
    "mlb": ("Pitch-by-pitch changes and a large game schedule create many possible observations.", "Props can have thin books, and superficially similar run-line or inning rules may not match."),
    "golf": ("A multi-day tournament creates many leaderboard changes and long observation windows.", "Round, cut, tie, and dead-heat wording can differ across venues."),
    "atp": ("Point-by-point tennis scoring creates frequent fair-value updates.", "Trading suspensions and thin books can make a visible gap difficult to capture."),
    "wta": ("Point-by-point tennis scoring creates frequent fair-value updates.", "Trading suspensions and thin books can make a visible gap difficult to capture."),
    "esports": ("Map and match state can update rapidly across many competitions.", "Different map, series, and overtime rules can make apparently similar contracts non-equivalent."),
    "ipl": ("Live cricket contains frequent state changes and popular matches can attract attention.", "Match, innings, and weather-abandonment rules need especially careful comparison."),
    "wnba": ("Live scoring can create the same repricing pattern as NBA games.", "The smaller catalog and thinner books can reduce the number of executable opportunities."),
    "nhl": ("Goals have a large immediate effect on win probability, creating sharp repricing moments.", "Goal props and regulation-versus-overtime wording can differ across venues."),
    "itf_men": ("Lower-tier tennis can reprice frequently while receiving less cross-venue attention.", "Books may be very thin, and point-level suspensions can increase execution risk."),
    "itf_women": ("Lower-tier tennis can reprice frequently while receiving less cross-venue attention.", "Books may be very thin, and point-level suspensions can increase execution risk."),
    "ufc": ("Fight outcomes can reprice sharply after visible momentum changes.", "Bout listings are less frequent, and cancellation or method-of-victory rules can differ."),
    "fifa_world_cup": ("Major matches and tournament developments can generate large attention-driven repricing.", "Qualification, group, knockout, overtime, and tournament-winner wording must match exactly."),
    "politics": ("Breaking news can produce longer-lived disagreement between venues.", "Office, candidate, cutoff date, and settlement-source wording often differ subtly."),
    "weather": ("Forecast updates and measured thresholds can create repeatable repricing over a known lifecycle.", "Station, measurement source, threshold, and time window must be identical."),
    "mls": ("Live goals and match events can produce sharp repricing moments.", "Draw handling and regulation-versus-extra-time wording can make pairs non-equivalent."),
    "elections": ("News, endorsements, polls, and long lifecycles can leave venues disagreeing for longer.", "District, nominee, cutoff date, and official settlement source require manual review."),
    "culture": ("Less standardized news-driven questions can receive uneven attention across venues.", "Sparse liquidity and wording differences can make a large proxy edge less executable."),
    "f1": ("Qualifying, race incidents, and long event windows create repeated state changes.", "Placement, constructor, tie, and race-classification rules can differ."),
    ADDITIONAL_DISCOVERED_SECTION: (
        "The broad discovery bucket can reveal useful markets outside the requested list.",
        "Because it combines different market families, each standout needs its own interpretation.",
    ),
}
SCENARIO_LABELS = {
    "nba": "NBA",
    "mlb": "MLB",
    "atp": "ATP",
    "wta": "WTA",
    "esports": "eSports",
    "ipl": "IPL",
    "wnba": "WNBA",
    "nhl": "NHL",
    "itf_men": "ITF Men",
    "itf_women": "ITF Women",
    "ufc": "UFC",
    "fifa_world_cup": "FIFA World Cup",
    "mls": "MLS",
    "f1": "F1",
    ADDITIONAL_DISCOVERED_SECTION: "Additional Discovered Scenario Coverage",
}


def run_research_pipeline(
    *,
    start: str,
    end: str,
    root_dir: str | Path = ".",
    resume: bool = True,
    collect_international: bool = True,
    run_annual_proxy: bool = True,
    run_pmxt_replay: bool = True,
    collect_us_catalog: bool = True,
    kalshi_historical_pages: int = 500,
    polymarket_pages_per_month: int = 100,
    annual_proxy_markets_per_month: int = 25,
    max_pmxt_hours: int | None = None,
    max_us_pages: int | None = None,
    terminal_summary_limit: int = 100,
    openai_budget_usd: float = 7.0,
) -> dict[str, Any]:
    root = Path(root_dir)
    data = root / "data"
    reports = root / "reports"
    data.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    manifest_path = reports / "coverage_manifest.json"
    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_status": "pipeline_run_in_progress_or_completed_per_layer",
        "requested_window": {"start": start, "end": end},
        "evidence_layers": {},
        "limitations": [
            "Official international APIs provide historical price proxies, not historical Polymarket L2 depth.",
            "PMXT L2 results apply only to raw Parquet hours verified in both public venue archives.",
            "Public Polymarket US APIs do not expose retrospective quote-by-quote profitability data.",
        ],
    }

    inventory = archive_inventory()
    manifest["evidence_layers"]["international_pmxt_l2"] = inventory
    write_json(data / "pmxt_archive_inventory.json", inventory)
    write_json(manifest_path, manifest)

    us_summary = None
    if collect_us_catalog:
        us_cache = collect_public_us_catalog(
            data / "polymarket_us_public_catalog.json",
            resume=resume,
            max_pages=max_us_pages,
            terminal_summary_limit=terminal_summary_limit,
        )
        us_summary = summarize_public_us_catalog(us_cache)
        us_summary["crawl_scope"] = (
            "full_public_catalog_crawl_complete"
            if all(state.get("complete") for state in us_summary.get("crawl_status", {}).values())
            else "checkpointed_public_catalog_crawl_incomplete"
        )
        manifest["evidence_layers"]["polymarket_us_public_catalog"] = us_summary
        write_json(reports / "polymarket_us_public_catalog_summary.json", us_summary)
        _write_csv(reports / "polymarket_us_scenarios.csv", us_summary["scenarios"])
        write_public_us_report(us_summary, root / "POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md", "reports/coverage_manifest.md")
        write_json(manifest_path, manifest)

    annual_result = None
    official_matches_path = data / "annual_official_matches.json"
    if collect_international:
        cache_path = data / "annual_official_catalog_cache.json"
        collect_monthly_cache(
            cache_path,
            start,
            end,
            kalshi_historical_pages=kalshi_historical_pages,
            polymarket_pages_per_month=polymarket_pages_per_month,
            resume=resume,
            retry_truncated=True,
        )
        coverage = write_coverage_report(cache_path, reports / "annual_official_catalog_coverage.md")
        matches_payload = normalize_monthly_cache(
            cache_path,
            official_matches_path,
            start,
            end,
            openai_budget_usd=openai_budget_usd,
            adjudication_cache_path=data / "openai_match_adjudications.json",
        )
        capped_catalog = any(
            row.get("kalshi_truncated") or row.get("polymarket_truncated")
            for row in coverage.get("months", [])
        )
        manifest["evidence_layers"]["international_official_api"] = {
            **coverage,
            **matches_payload.get("meta", {}),
            "evidence_label": "historical_price_proxy_without_historical_polymarket_l2",
            "combined_catalog_scope": (
                "bounded_retained_screen_due_explicit_public_catalog_caps"
                if capped_catalog
                else "all_reached_public_catalog_slices_complete"
            ),
        }
        write_json(manifest_path, manifest)

    if run_annual_proxy and official_matches_path.exists():
        payload = read_json(official_matches_path)
        matches = [matched_market_from_dict(item) for item in payload.get("matches", [])]
        annual_result = scan_annual_official_proxy(
            matches,
            start,
            end,
            reports / "annual_official_proxy.json",
            reports / "annual_official_proxy.md",
            max_markets_per_month=annual_proxy_markets_per_month,
            catalog_meta=payload.get("meta", {}),
            checkpoint_dir=reports / "annual_proxy_checkpoints",
            resume=resume,
        )
        official_layer = manifest["evidence_layers"].setdefault(
            "international_official_api",
            {"evidence_label": "historical_price_proxy_without_historical_polymarket_l2"},
        )
        official_layer["proxy_report"] = {
            "selected_markets": annual_result["parameters"]["selected_markets"],
            "eligible_strict_pairs": annual_result["parameters"]["eligible_strict_pairs"],
            "phase_scan_tasks": annual_result["parameters"]["phase_scan_tasks"],
            "opportunities": len(annual_result["opportunities"]),
            "opportunity_windows": len(annual_result["opportunity_windows"]),
            "errors": len(annual_result["errors"]),
        }
        official_layer["proxy_scan_scope"] = (
            "all_retained_strict_pairs"
            if annual_proxy_markets_per_month == 0
            else f"bounded_stratified_screen_max_{annual_proxy_markets_per_month}_markets_per_month"
        )
        _write_csv(reports / "annual_official_proxy_opportunities.csv", annual_result["opportunities"])
        _write_csv(reports / "annual_official_proxy_windows.csv", annual_result["opportunity_windows"])
        _write_csv(reports / "annual_focus_category_coverage.csv", annual_result["coverage_by_focus_scenario"])
        _write_csv(reports / "annual_official_proxy_portfolio.csv", annual_result["portfolio_appendix"])
        write_annual_catalog_funnel(annual_result, reports / "annual_catalog_funnel.md")
        write_json(manifest_path, manifest)

    l2_result = None
    cluster_matches_path = data / "cluster_matches.json"
    l2_matches_path = official_matches_path if official_matches_path.exists() else cluster_matches_path
    if run_pmxt_replay and l2_matches_path.exists():
        payload = read_json(l2_matches_path)
        matches = [matched_market_from_dict(item) for item in payload.get("matches", [])]
        l2_result = run_resumable_l2_replay(
            matches,
            inventory["hours"],
            reports / "pmxt_l2_checkpoints",
            resume=resume,
            max_hours=max_pmxt_hours,
        )
        write_json(reports / "pmxt_l2_replay.json", l2_result)
        _write_csv(reports / "pmxt_l2_windows.csv", l2_result["windows"])
        _write_csv(reports / "pmxt_l2_portfolio.csv", l2_result["portfolio_appendix"])
        manifest["evidence_layers"]["international_pmxt_l2"]["replay"] = l2_result["summary"]
        manifest["evidence_layers"]["international_pmxt_l2"]["replay_status"] = (
            f"completed_{l2_result['parameters']['hours_completed']}_checkpointed_hours"
        )
        write_json(manifest_path, manifest)

    write_manifest_markdown(manifest, reports / "coverage_manifest.md")
    _write_csv(reports / "coverage_manifest.csv", _manifest_csv_rows(manifest))
    leaderboards = build_leaderboards(annual_result, l2_result)
    write_json(reports / "scenario_leaderboards.json", leaderboards)
    _write_csv(reports / "category_leaderboard.csv", leaderboards["category_leaderboard"])
    _write_csv(reports / "subscenario_leaderboard.csv", leaderboards["subscenario_leaderboard"])
    trade_examples = _trade_examples(l2_result, annual_result)
    write_json(reports / "arbitrage_trade_examples.json", trade_examples)
    _write_csv(reports / "arbitrage_trade_examples.csv", trade_examples["examples"])
    write_trade_examples_report(trade_examples, root / "ARBITRAGE_TRADE_EXAMPLES.md")
    write_matching_audit(
        read_json(official_matches_path) if official_matches_path.exists() else {},
        reports / "MATCHING_AUDIT.md",
    )
    write_scenario_analysis_report(
        manifest,
        trade_examples,
        l2_result,
        annual_result,
        root / "ANNUAL_SCENARIO_ANALYSIS.md",
        leaderboards=leaderboards,
    )
    write_research_summary(
        manifest,
        trade_examples,
        root / "RESEARCH_SUMMARY.md",
        leaderboards=leaderboards,
    )
    return {
        "manifest": manifest,
        "annual_proxy": annual_result,
        "pmxt_l2": l2_result,
        "polymarket_us": us_summary,
        "leaderboards": leaderboards,
    }


def render_existing_research_reports(root_dir: str | Path = ".") -> dict[str, Any]:
    root = Path(root_dir)
    reports = root / "reports"
    manifest_path = reports / "coverage_manifest.json"
    annual_path = reports / "annual_official_proxy.json"
    manifest = read_json(manifest_path)
    annual_result = read_json(annual_path)
    l2_result = None
    for candidate in [reports / "pmxt_l2_replay.json", reports / "smoke_l2_active_replay_final.json"]:
        if candidate.exists():
            l2_result = read_json(candidate)
            break
    official_layer = manifest["evidence_layers"].setdefault(
        "international_official_api",
        {"evidence_label": "historical_price_proxy_without_historical_polymarket_l2"},
    )
    official_layer.update(annual_result.get("parameters", {}).get("catalog_meta") or {})
    official_layer["proxy_report"] = {
        "selected_markets": annual_result["parameters"]["selected_markets"],
        "eligible_strict_pairs": annual_result["parameters"].get("eligible_strict_pairs"),
        "phase_scan_tasks": annual_result["parameters"].get("phase_scan_tasks"),
        "opportunities": len(annual_result.get("opportunities") or []),
        "opportunity_windows": len(annual_result.get("opportunity_windows") or []),
        "errors": len(annual_result.get("errors") or []),
    }
    official_layer["proxy_scan_scope"] = (
        "all_retained_strict_pairs"
        if int(annual_result["parameters"].get("max_markets_per_month") or 0) == 0
        else f"bounded_stratified_screen_max_{annual_result['parameters']['max_markets_per_month']}_markets_per_month"
    )
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["run_status"] = "retained_catalog_strict_pair_proxy_scan_complete_pmxt_full_replay_incomplete"
    manifest["limitations"] = [
        item
        for item in manifest.get("limitations", [])
        if not item.startswith("The annual price-history proxy is a stratified screen")
        and not item.startswith("The annual official-API price proxy scanned every retained strict pair")
    ]
    manifest["limitations"].append(
        "The annual official-API price proxy scanned every retained strict pair after the semantic gate. "
        f"It recorded {len(annual_result.get('errors') or [])} API timing-window errors and does not prove "
        "historical fillability because official Polymarket history omits L2 depth."
    )
    write_json(manifest_path, manifest)
    write_manifest_markdown(manifest, reports / "coverage_manifest.md")
    _write_csv(reports / "coverage_manifest.csv", _manifest_csv_rows(manifest))
    _write_csv(reports / "annual_official_proxy_opportunities.csv", annual_result.get("opportunities") or [])
    _write_csv(reports / "annual_official_proxy_windows.csv", annual_result.get("opportunity_windows") or [])
    _write_csv(reports / "annual_focus_category_coverage.csv", annual_result.get("coverage_by_focus_scenario") or [])
    _write_csv(reports / "annual_official_proxy_portfolio.csv", annual_result.get("portfolio_appendix") or [])
    write_annual_catalog_funnel(annual_result, reports / "annual_catalog_funnel.md")
    leaderboards = build_leaderboards(annual_result, l2_result)
    write_json(reports / "scenario_leaderboards.json", leaderboards)
    _write_csv(reports / "category_leaderboard.csv", leaderboards["category_leaderboard"])
    _write_csv(reports / "subscenario_leaderboard.csv", leaderboards["subscenario_leaderboard"])
    trade_examples = _trade_examples(l2_result, annual_result)
    write_json(reports / "arbitrage_trade_examples.json", trade_examples)
    _write_csv(reports / "arbitrage_trade_examples.csv", trade_examples["examples"])
    write_trade_examples_report(trade_examples, root / "ARBITRAGE_TRADE_EXAMPLES.md")
    official_matches_path = root / "data" / "annual_official_matches.json"
    write_matching_audit(
        read_json(official_matches_path) if official_matches_path.exists() else {},
        reports / "MATCHING_AUDIT.md",
    )
    write_scenario_analysis_report(
        manifest,
        trade_examples,
        l2_result,
        annual_result,
        root / "ANNUAL_SCENARIO_ANALYSIS.md",
        leaderboards=leaderboards,
    )
    write_research_summary(
        manifest,
        trade_examples,
        root / "RESEARCH_SUMMARY.md",
        leaderboards=leaderboards,
    )
    return {
        "manifest": manifest,
        "annual_proxy": annual_result,
        "pmxt_l2": l2_result,
        "trade_examples": trade_examples,
        "leaderboards": leaderboards,
    }


def write_manifest_markdown(manifest: dict[str, Any], out_path: str | Path) -> None:
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pmxt = manifest.get("evidence_layers", {}).get("international_pmxt_l2", {})
    official = manifest.get("evidence_layers", {}).get("international_official_api", {})
    us = manifest.get("evidence_layers", {}).get("polymarket_us_public_catalog", {})
    capped_months = _catalog_cap_summary(official)
    proxy = official.get("proxy_report") or {}
    lines = [
        "# Research Coverage Manifest",
        "",
        f"- Generated: `{manifest.get('generated_at')}`",
        f"- Run status: `{manifest.get('run_status', 'pipeline_run')}`",
        f"- Requested rolling-year window: `{manifest.get('requested_window', {}).get('start')}` to `{manifest.get('requested_window', {}).get('end')}`",
        "",
        "## International Official API",
        "",
        "- Evidence type: historical price proxy. This layer does not contain historical international Polymarket L2 depth.",
        f"- Matched pairs: `{official.get('matched_pairs', 'not run')}`",
        f"- Historical market rows fetched while traversing the official cursor: `{official.get('kalshi_historical_markets_fetched', 'not run')}`",
        f"- Historical market rows retained for the requested scenario study: `{official.get('kalshi_historical_markets_retained', 'not run')}`",
        f"- Repetitive high-frequency rows intentionally excluded from the retained index: `{official.get('kalshi_historical_markets_skipped_out_of_scope', 'not run')}`",
        f"- Oldest Kalshi close time reached: `{official.get('kalshi_oldest_close_time_reached', 'not run')}`",
        f"- Full requested Kalshi history reached: `{official.get('kalshi_historical_complete', 'not run')}`",
        f"- Combined international catalog completeness: `{official.get('combined_catalog_scope', 'not run')}`",
        f"- Explicitly capped international catalog slices: `{capped_months or 'none recorded'}`",
        f"- Annual price-proxy scan scope: `{official.get('proxy_scan_scope', 'not run')}`",
        f"- Eligible strict pairs sent to the annual proxy layer: `{proxy.get('eligible_strict_pairs', 'not run')}`",
        f"- Adaptive phase-scan tasks: `{proxy.get('phase_scan_tasks', 'not run')}`",
        f"- Retained positive proxy windows: `{proxy.get('opportunity_windows', 'not run')}`",
        "- Detailed annual funnel: [annual_catalog_funnel.md](annual_catalog_funnel.md)",
        f"- Persisted official crawl errors: `{len(official.get('errors') or [])}`",
        f"- Annual proxy timing-window errors after retries: `{proxy.get('errors', 'not run')}`",
        "",
        "## International PMXT L2",
        "",
        "- Evidence type: executable archived order-book replay.",
        f"- Verified synchronized hours: `{pmxt.get('verified_overlap_hours', 0)}`",
        f"- First synchronized hour: `{pmxt.get('overlap_first')}`",
        f"- Last synchronized hour: `{pmxt.get('overlap_last')}`",
        f"- PMXT listing complete: `{pmxt.get('listing_complete')}`",
        f"- PMXT listing errors: `{len(pmxt.get('listing_errors') or [])}`",
        f"- Replay status: `{pmxt.get('replay_status', 'not run')}`",
        "",
        "## Polymarket US Public Catalog",
        "",
        "- Evidence type: descriptive public catalog only. This layer must not be used as a retrospective profit report.",
        f"- Events: `{us.get('events', 'not run')}`",
        f"- Unique embedded markets: `{us.get('unique_embedded_markets', 'not run')}`",
        f"- Crawl checkpoints: `{len(us.get('crawl_status') or {})}`",
        f"- Catalog crawl scope: `{us.get('crawl_scope', 'not run')}`",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in manifest.get("limitations", []))
    target.write_text("\n".join(lines), encoding="utf-8")


def write_annual_catalog_funnel(annual_result: dict[str, Any], out_path: str | Path) -> dict[str, Any]:
    parameters = annual_result.get("parameters") or {}
    catalog = parameters.get("catalog_meta") or {}
    phase_records = annual_result.get("phase_records") or []
    opportunities = annual_result.get("opportunities") or []
    funnel = {
        "kalshi_retained_catalog_rows_indexed": catalog.get("kalshi_catalog_markets"),
        "polymarket_retained_catalog_rows_indexed": catalog.get("polymarket_catalog_markets"),
        "conservative_local_candidate_pairs": catalog.get("matched_pairs"),
        "strict_semantic_gate_rejections": len(parameters.get("strict_title_rejections") or []),
        "eligible_strict_pairs": parameters.get("eligible_strict_pairs"),
        "selected_pairs_for_proxy_scan": parameters.get("selected_markets"),
        "phase_scan_tasks": parameters.get("phase_scan_tasks"),
        "completed_phase_records": len(phase_records),
        "pairs_with_synchronized_snapshots": len(
            {item["match_id"] for item in phase_records if item.get("aligned_points")}
        ),
        "synchronized_snapshots": sum(int(item.get("aligned_points") or 0) for item in phase_records),
        "positive_proxy_snapshots": len(opportunities),
        "positive_proxy_windows": len(annual_result.get("opportunity_windows") or []),
        "api_errors": len(annual_result.get("errors") or []),
    }
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target.with_suffix(".json"), funnel)
    _write_csv(target.with_suffix(".csv"), [{"stage": key, "value": value} for key, value in funnel.items()])
    lines = [
        "# Annual Retained-Catalog Coverage Funnel",
        "",
        "Coverage manifest: [coverage_manifest.md](coverage_manifest.md)",
        "",
        "This funnel explains how the broad annual study narrows the retained public catalogs into comparable "
        "cross-venue price tests. A market that exists on only one venue is counted in the retained catalog but "
        "cannot enter two-venue arbitrage arithmetic.",
        "",
        "| Funnel stage | Count | Plain-English meaning |",
        "|---|---:|---|",
        f"| Kalshi retained catalog rows indexed | {funnel['kalshi_retained_catalog_rows_indexed']} | Kalshi market records kept for matching |",
        f"| Polymarket retained catalog rows indexed | {funnel['polymarket_retained_catalog_rows_indexed']} | International Polymarket market records kept for matching |",
        f"| Conservative local candidate pairs | {funnel['conservative_local_candidate_pairs']} | Lookalike cross-venue pairs recovered by the catalog matcher |",
        f"| Strict semantic-gate rejections | {funnel['strict_semantic_gate_rejections']} | Lookalikes removed because the event, named outcome, competition, or close timing did not match strictly enough |",
        f"| Eligible strict pairs | {funnel['eligible_strict_pairs']} | Cross-venue pairs allowed into the annual proxy analysis |",
        f"| Selected pairs for proxy scan | {funnel['selected_pairs_for_proxy_scan']} | Eligible pairs actually sent to the scanner; this equals all eligible retained pairs in an uncapped run |",
        f"| Phase scan tasks | {funnel['phase_scan_tasks']} | Adaptive time ranges requested from the historical APIs |",
        f"| Completed phase-and-slippage records | {funnel['completed_phase_records']} | Successful adaptive time-range results, repeated separately for the modeled 1, 2, and 5 cent slippage cases |",
        f"| Pairs with synchronized snapshots | {funnel['pairs_with_synchronized_snapshots']} | Pairs with at least one timestamp comparable across both venues |",
        f"| Synchronized snapshots | {funnel['synchronized_snapshots']} | Historical timestamps compared across both venues and slippage cases |",
        f"| Positive proxy snapshots | {funnel['positive_proxy_snapshots']} | Timestamp rows with estimated profit above zero after modeled costs |",
        f"| Positive proxy windows | {funnel['positive_proxy_windows']} | Consecutive profitable timestamp ranges |",
        f"| API errors | {funnel['api_errors']} | Historical range requests that failed after retries |",
    ]
    focus_keys = sorted(
        set(catalog.get("kalshi_catalog_focus_scenarios") or {})
        | set(catalog.get("polymarket_catalog_focus_scenarios") or {})
    )
    if focus_keys:
        lines.extend(
            [
                "",
                "## Retained Catalog Rows By Focus Category",
                "",
                "These counts are venue-specific market rows before cross-venue matching. They explain whether a category "
                "was present in the retained catalogs even when no strict equivalent pair was recovered.",
                "",
                "| Focus category | Kalshi retained rows | International Polymarket retained rows |",
                "|---|---:|---:|",
            ]
        )
        for scenario in focus_keys:
            lines.append(
                f"| `{scenario}` | {catalog.get('kalshi_catalog_focus_scenarios', {}).get(scenario, 0)} "
                f"| {catalog.get('polymarket_catalog_focus_scenarios', {}).get(scenario, 0)} |"
            )
    target.write_text("\n".join(lines), encoding="utf-8")
    return funnel


def write_research_summary(
    manifest: dict[str, Any],
    trade_examples: dict[str, Any],
    out_path: str | Path,
    *,
    leaderboards: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    target = Path(out_path)
    pmxt = manifest.get("evidence_layers", {}).get("international_pmxt_l2", {})
    official = manifest.get("evidence_layers", {}).get("international_official_api", {})
    us = manifest.get("evidence_layers", {}).get("polymarket_us_public_catalog", {})
    capped_months = _catalog_cap_summary(official)
    strongest = sorted(
        trade_examples.get("examples", []),
        key=lambda item: float(item.get("locked_profit_per_contract") or 0),
        reverse=True,
    )[:5]
    lines = [
        "# Prediction-Market Research Summary",
        "",
        "This project separates evidence quality before comparing scenarios. A historical price gap is useful, "
        "but it is not the same thing as an executable fill with visible quantity.",
        "",
        "Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)",
        "",
        "## Evidence Map",
        "",
        "| Layer | Coverage | What it can establish |",
        "|---|---|---|",
        f"| International official APIs | `{official.get('start', 'pending')}` to `{official.get('end', 'pending')}` | Rolling-year price-proxy opportunities under stated slippage assumptions |",
        f"| International PMXT L2 | `{pmxt.get('overlap_first')}` to `{pmxt.get('overlap_last')}` | Displayed depth, VWAP slippage, short-lived windows, and safe paired early exits |",
        f"| Polymarket US public API | `{us.get('events', 'pending')}` events | Scenario inventory and public-data limits, not retrospective arbitrage profit |",
        "",
        "## Completion Status",
        "",
        f"- Full requested Kalshi historical cursor range reached: `{official.get('kalshi_historical_complete', 'pending')}`.",
        f"- Oldest Kalshi close time reached: `{official.get('kalshi_oldest_close_time_reached', 'pending')}`.",
        f"- Kalshi rows fetched while traversing the cursor: `{official.get('kalshi_historical_markets_fetched', 'pending')}`.",
        f"- Kalshi rows retained in the requested scenario index: `{official.get('kalshi_historical_markets_retained', 'pending')}`.",
        f"- Combined international catalog scope: `{official.get('combined_catalog_scope', 'pending')}`.",
        f"- Explicitly capped catalog slices: `{capped_months or 'none recorded'}`.",
        f"- Annual price-proxy scan scope: `{official.get('proxy_scan_scope', 'pending')}`.",
        "- Detailed retained-catalog funnel: [reports/annual_catalog_funnel.md](reports/annual_catalog_funnel.md).",
        f"- Verified PMXT synchronized archived hours: `{pmxt.get('verified_overlap_hours', 0)}`.",
        "",
        "## Profitable Examples",
        "",
        "Only positive retained examples appear in the reader-facing reports. Categories without one say "
        "`No profitable example found.` The scenario analysis then states whether that is a complete negative screen, "
        "a missing synchronized-history result, or a matching-coverage limitation.",
        "",
        "Detailed retained-catalog funnel: [reports/annual_catalog_funnel.md](reports/annual_catalog_funnel.md)",
        "",
    ]
    category_rows = list((leaderboards or {}).get("category_leaderboard") or [])
    if category_rows:
        lines.extend(
            [
                "## Best Categories",
                "",
                "The ordering uses a transparent blended score: `70%` annual two-cent-slippage profit percentile "
                "plus `30%` PMXT executable-profit percentile. Dollar profit remains visible beside the score.",
                "",
                "| Rank | Category | Score | Annual net profit | PMXT net profit | PMXT evidence |",
                "|---:|---|---:|---:|---:|---|",
            ]
        )
        for row in category_rows:
            lines.append(
                f"| {row['rank']} | `{row['focus_scenario']}` | {row['blended_score']:.2f} "
                f"| {_money(row['annual_net_profit'])} | {_money(row['pmxt_net_profit'])} "
                f"| {row['pmxt_validation']} |"
            )
        lines.append("")
    if strongest:
        lines.extend(
            [
                "| Category | Contract | Locked net profit per paired contract | Evidence |",
                "|---|---|---:|---|",
            ]
        )
        for item in strongest:
            lines.append(
                f"| {_scenario_label(item['scenario'])} | {item['polymarket_title']} | "
                f"{_money(item['locked_profit_per_contract'])} | `{item['evidence_label']}` |"
            )
    else:
        lines.append("No profitable example found in the completed evidence layers.")
    lines.extend(
        [
        "",
        "## Reading Order",
        "",
        "1. Read [README.md](README.md) for the plain-language methodology.",
        "2. Read [ANNUAL_SCENARIO_ANALYSIS.md](ANNUAL_SCENARIO_ANALYSIS.md) for the international findings.",
        "3. Read [POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md](POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md) for the separate US catalog study.",
        "4. Read [ARBITRAGE_TRADE_EXAMPLES.md](ARBITRAGE_TRADE_EXAMPLES.md) for worked trade arithmetic.",
        ]
    )
    target.write_text("\n".join(lines), encoding="utf-8")


def write_matching_audit(payload: dict[str, Any], out_path: str | Path) -> None:
    target = Path(out_path)
    meta = payload.get("meta") or {}
    matches = payload.get("matches") or []
    rejected = payload.get("rejected") or []
    accepted_by_category = Counter()
    for item in matches:
        text = " ".join(
            [
                str(item.get("polymarket", {}).get("title") or ""),
                str(item.get("kalshi", {}).get("title") or ""),
                str(item.get("kalshi", {}).get("slug") or ""),
            ]
        )
        accepted_by_category[classify_focus_scenario(text)] += 1
    rejection_reasons = Counter(str(item.get("reason") or "unspecified") for item in rejected)
    lines = [
        "# Matching Audit",
        "",
        "Coverage manifest: [coverage_manifest.md](coverage_manifest.md)",
        "",
        "## Why The Matcher Was Rebuilt",
        "",
        "The earlier matcher required shared literal title words. That discarded valid sports pairs before "
        "their prices were compared. For example, `Dallas at Milwaukee` and `Mavericks vs. Bucks` describe "
        "the same NBA game but may share no useful team token.",
        "",
        "The rebuilt matcher first converts venue text into structured fields: league, canonical participants, "
        "selected outcome, actual scheduled start, market type, numeric line, period, and round. It then applies "
        "hard mismatch vetoes. Plausible finalists are reviewed through cached OpenAI Structured Outputs when "
        "the research run enables adjudication.",
        "",
        "## Current Funnel",
        "",
        f"- Kalshi retained rows: `{meta.get('kalshi_catalog_markets', 0)}`",
        f"- Polymarket retained rows: `{meta.get('polymarket_catalog_markets', 0)}`",
        f"- Exact accepted pairs: `{len(matches)}`",
        f"- Rejected finalists: `{len(rejected)}`",
        f"- Matching gate version: `{meta.get('matching_gate_version', 'unknown')}`",
        f"- OpenAI adjudication enabled: `{meta.get('openai_adjudication_enabled', False)}`",
        f"- Recorded OpenAI spend: `${float(meta.get('openai_adjudication_spent_usd') or 0):.6f}`",
        "",
        "## Accepted Pairs By Category",
        "",
        "| Category | Exact pairs |",
        "|---|---:|",
    ]
    for category, count in accepted_by_category.most_common():
        lines.append(f"| `{category}` | {count} |")
    lines.extend(
        [
            "",
            "## Most Common Rejection Reasons",
            "",
            "| Reason | Candidates |",
            "|---|---:|",
        ]
    )
    for reason, count in rejection_reasons.most_common(30):
        lines.append(f"| {reason} | {count} |")
    lines.extend(
        [
            "",
            "A rejected near-match is not included in profit totals. This includes same-game contracts with "
            "different overtime, cancellation, period, threshold, split-payout, or settlement treatment.",
        ]
    )
    target.write_text("\n".join(lines), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        target.write_text("", encoding="utf-8")
        return
    keys = sorted({key for row in rows for key in row})
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                    for key, value in row.items()
                }
            )


def _manifest_csv_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"layer": layer, "coverage": payload}
        for layer, payload in sorted(manifest.get("evidence_layers", {}).items())
    ]


def _trade_examples(
    l2_result: dict[str, Any] | None,
    annual_result: dict[str, Any] | None,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    annual_windows = list((annual_result or {}).get("opportunity_windows") or [])
    annual_windows_by_key: dict[tuple[str, str, str | None, float], list[dict[str, Any]]] = defaultdict(list)
    for window in annual_windows:
        annual_windows_by_key[_annual_window_key(window)].append(window)
    phase_records_by_match: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in (annual_result or {}).get("phase_records") or []:
        phase_records_by_match[record["match_id"]].append(record)
    for item in sorted(
        list((l2_result or {}).get("windows") or []),
        key=lambda row: row["best_net_edge_per_contract"],
        reverse=True,
    ):
        if int(item["size_contracts"]) != HEADLINE_ORDER_SIZE:
            continue
        if float(item.get("locked_hold_profit_per_contract") or 0) <= 0:
            continue
        scenario = item.get("focus_scenario") or classify_focus_scenario(
            f"{item.get('polymarket_title', '')} {item.get('kalshi_title', '')}"
        )
        grouped[scenario].append(
            {
                "scenario": scenario,
                "evidence_label": "pmxt_archived_l2_exact_pair",
                "manual_review_status": "exact-pair gate passed; re-check venue rules before live trading",
                "match_id": item["match_id"],
                "timestamp": item["start"],
                "best_timestamp": item.get("best_timestamp") or item["start"],
                "profitable_window_start": item["start"],
                "profitable_window_end": item["end"],
                "profitable_window_duration_seconds": item.get("duration_seconds"),
                "profitable_snapshots": item.get("ticks"),
                "screened_periods": [],
                "timing_phase": item.get("timing_phase") or "archived_l2_window",
                "size_contracts": item["size_contracts"],
                "polymarket_title": item["polymarket_title"],
                "kalshi_title": item["kalshi_title"],
                "yes_venue": item["yes_venue"],
                "no_venue": item["no_venue"],
                "yes_price": item["yes_vwap"],
                "no_price": item["no_vwap"],
                "pair_cost": item["entry_cost_per_contract"],
                "fees_total": item["entry_fee_total"],
                "slippage": item["book_slippage_per_contract"],
                "depth_contracts": item["max_top_of_book_depth_contracts"],
                "paired_capacity_contracts": item["max_paired_capacity_contracts"],
                "one_leg_partial_fill_exposure_contracts": item["one_leg_partial_fill_exposure_contracts"],
                "locked_profit_per_contract": item["locked_hold_profit_per_contract"],
                "roi_on_entry_cost": item["best_roi_on_entry_cost"],
                "paired_exit_qualifies": item.get("paired_exit_qualifies"),
                "paired_exit_at": item.get("paired_exit_at"),
                "paired_exit_profit_per_contract": item.get("paired_exit_net_profit_per_contract"),
                "paired_exit_improvement_per_contract": item.get("paired_exit_improvement_per_contract"),
            }
        )
    selected_annual_match_ids: dict[str, set[str]] = defaultdict(set)
    for item in sorted(
        list((annual_result or {}).get("opportunities") or []),
        key=lambda row: row["net_edge_per_contract"],
        reverse=True,
    ):
        if float(item.get("net_edge_per_contract") or 0) <= 0:
            continue
        if abs(float(item.get("pair_slippage_assumption") or 0) - 0.02) > 1e-9:
            continue
        if strict_match_rejection(
            item.get("polymarket_title", ""),
            item.get("kalshi_title", ""),
        ):
            continue
        scenario = item.get("focus_scenario") or classify_focus_scenario(
            f"{item.get('polymarket_title', '')} {item.get('kalshi_title', '')}"
        )
        if len(selected_annual_match_ids[scenario]) >= 3 or item["match_id"] in selected_annual_match_ids[scenario]:
            continue
        selected_annual_match_ids[scenario].add(item["match_id"])
        context = _annual_example_context(item, annual_windows_by_key, phase_records_by_match)
        grouped[scenario].append(
            {
                "scenario": scenario,
                "evidence_label": "official_api_price_history_proxy_without_historical_depth",
                "manual_review_status": "exact-pair gate passed; annual depth remains modeled",
                "match_id": item["match_id"],
                "timestamp": item["timestamp"],
                "best_timestamp": item["timestamp"],
                **context,
                "size_contracts": (annual_result or {}).get("parameters", {}).get("trade_size", HEADLINE_ORDER_SIZE),
                "polymarket_title": item["polymarket_title"],
                "kalshi_title": item["kalshi_title"],
                "yes_venue": item["yes_venue"],
                "no_venue": item["no_venue"],
                "yes_price": item["yes_price"],
                "no_price": item["no_price"],
                "pair_cost": item["total_cost"],
                "fees_total": item["total_fee"],
                "slippage": item.get(
                    "pair_slippage_assumption",
                    (annual_result or {}).get("parameters", {}).get("slippage_buffer"),
                ),
                "depth_contracts": None,
                "paired_capacity_contracts": None,
                "one_leg_partial_fill_exposure_contracts": None,
                "locked_profit_per_contract": item["net_edge_per_contract"],
                "roi_on_entry_cost": item.get("roi_on_entry_cost")
                if item.get("roi_on_entry_cost") is not None
                else float(item["net_edge_per_contract"]) / float(item["total_cost"]),
                "paired_exit_qualifies": None,
                "paired_exit_at": None,
                "paired_exit_profit_per_contract": None,
                "paired_exit_improvement_per_contract": None,
            }
        )
    examples = []
    coverage = []
    for scenario in [*FOCUS_SCENARIOS, ADDITIONAL_DISCOVERED_SECTION]:
        selected = []
        seen = set()
        for item in grouped.get(scenario, []):
            if item["match_id"] in seen:
                continue
            seen.add(item["match_id"])
            selected.append(item)
            if len(selected) == 3:
                break
        examples.extend(selected)
        coverage.append({"scenario": scenario, "examples": len(selected)})
    return {
        "note": (
            "Only positive-profit rows are shown. Rows are strict research candidates selected for "
            "inspectability. Each row still requires manual resolution-rule review before live trading."
        ),
        "coverage": coverage,
        "examples": examples,
    }


def _annual_example_context(
    item: dict[str, Any],
    windows_by_key: dict[tuple[str, str, str | None, float], list[dict[str, Any]]],
    phase_records_by_match: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    matches = [
        window
        for window in windows_by_key.get(_annual_window_key(item), [])
        if window["window_start"] <= item["timestamp"] <= window["window_end"]
    ]
    selected = matches[0] if matches else {}
    periods = [
        {
            "phase": record["phase"],
            "window_start": record["window_start"],
            "window_end": record["window_end"],
            "sampling_interval": _sampling_interval_label(record["phase"]),
            "aligned_snapshots": record["aligned_points"],
        }
        for record in phase_records_by_match.get(item["match_id"], [])
        if float(record.get("pair_slippage_assumption") or 0)
        == float(item.get("pair_slippage_assumption") or 0)
    ]
    return {
        "profitable_window_start": selected.get("window_start"),
        "profitable_window_end": selected.get("window_end"),
        "profitable_window_duration_seconds": selected.get("duration_seconds"),
        "profitable_snapshots": selected.get("profitable_snapshots"),
        "screened_periods": periods,
        "timing_phase": item.get("phase") or "unspecified",
    }


def _annual_window_key(item: dict[str, Any]) -> tuple[str, str, str | None, float]:
    return (
        item["match_id"],
        item["direction"],
        item.get("phase"),
        float(item.get("pair_slippage_assumption") or 0),
    )


def _sampling_interval_label(phase: str) -> str:
    return {
        "sports_pregame_slow": "hourly",
        "sports_pregame_final_24h": "every 5 minutes",
        "sports_in_play": "every 1 minute",
        "sports_event_start_unavailable_final_24h": "every 5 minutes",
        "lifecycle_more_than_30d": "daily",
        "lifecycle_30d_to_24h": "hourly",
        "lifecycle_final_24h": "every 5 minutes",
    }.get(phase, "adaptive interval")


def write_trade_examples_report(payload: dict[str, Any], out_path: str | Path) -> None:
    target = Path(out_path)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload["examples"]:
        grouped[item["scenario"]].append(item)
    lines = [
        "# Arbitrage Trade Examples",
        "",
        "Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)",
        "",
        "This report is the reader-facing example book. It intentionally shows profitable retained examples only. "
        "A category with no positive retained result says `No profitable example found.` instead of showing a near miss.",
        "",
        "## The Trade In Plain English",
        "",
        "A prediction-market contract pays `$1.00` if its stated outcome happens and `$0.00` otherwise. "
        "A locked pair buys `YES` on one venue and `NO` on the other venue for the same real-world question. "
        "If the wording and settlement rules truly match, exactly one side pays `$1.00`. Buying both sides for less "
        "than `$1.00`, after costs, creates a locked profit.",
        "",
        "Example: buying `YES` for `$0.42` and `NO` for `$0.51` costs `$0.93`. Before fees, the locked profit is "
        "`$1.00 - $0.93 = $0.07` per paired contract.",
        "",
        "## Terms Used Below",
        "",
        "- **Venue**: the exchange where a contract is traded, such as Kalshi or international Polymarket.",
        "- **Pair cost**: the combined amount paid for the `YES` and `NO` legs.",
        "- **Fee**: an exchange charge paid when entering or exiting a trade.",
        "- **Slippage**: the extra cost caused by the best displayed price not having enough contracts for the full order.",
        "- **Order book**: the visible list of prices and quantities offered by other traders.",
        "- **L2 order book**: a multi-level order book. It includes the best price and deeper prices behind it.",
        "- **VWAP**: volume-weighted average price. If 50 contracts cost `$0.40` and the next 50 cost `$0.42`, "
        "the VWAP for 100 contracts is `$0.41`.",
        "- **Displayed depth**: how many contracts were visibly available at the best price on the thinner side of the pair.",
        "- **Paired capacity**: the largest number of contracts both visible books could support at that moment.",
        "- **Partial-fill exposure**: the number of contracts that could be left unhedged if one side fills and the other does not.",
        "- **Locked profit**: profit retained by holding both opposite legs until settlement.",
        "- **ROI**: return on investment. It is locked profit divided by the cash paid to enter the pair.",
        "- **Proxy**: an estimate based on historical prices. A proxy does not prove that enough contracts were actually available.",
        "- **Capital recycling**: selling both legs early when doing so safely earns more than waiting for settlement.",
        "- **Pregame**: the period before a scheduled sporting event starts.",
        "- **In-play**: the period after a scheduled sporting event starts but before its final result. The annual scanner does not enter new trades after final resolution.",
        "- **Sports event start unavailable**: the retained public metadata did not expose the scheduled start. The scanner can still inspect the final 24 hours before close, but it does not call those observations in-play.",
        "- **Modeled order size**: a hypothetical simultaneous two-leg order used for arithmetic. In the annual proxy layer, it is not a claim that the historical books visibly contained that quantity.",
        "",
        "## Evidence Labels",
        "",
        "- **PMXT archived L2**: stronger historical evidence. The replay walked the stored multi-level books and enforced visible capacity.",
        "- **Official API price-history proxy**: broader annual screening. Historical Polymarket depth was unavailable, so slippage is modeled.",
        "",
        "## How Examples Are Selected",
        "",
        "The scanner evaluates many aligned historical timestamps for each matched pair. It groups consecutive profitable "
        "timestamps into an opportunity window, then presents up to three distinct profitable markets per category. "
        "The `best timestamp` is the most profitable snapshot inside the displayed window; it is not the only timestamp checked.",
        "",
        "For an annual proxy example, `100 paired contracts` means the model asks what would happen if `100` YES contracts "
        "and `100` matching NO contracts were purchased together at that snapshot. The official annual APIs do not preserve "
        "historical Polymarket order-book quantities, so the model applies the stated conservative slippage allowance. "
        "For a PMXT archived-L2 example, the stored multi-level book is walked to calculate the average price and visible capacity.",
        "",
        payload["note"],
    ]
    for scenario in [*FOCUS_SCENARIOS, ADDITIONAL_DISCOVERED_SECTION]:
        lines.extend(["", f"## {scenario.replace('_', ' ').title()}", ""])
        examples = grouped.get(scenario, [])
        if not examples:
            lines.append("No profitable example found.")
            continue
        for item in examples:
            lines.extend(
                [
                    f"### {item['polymarket_title']}",
                    "",
                    f"- Evidence: `{item['evidence_label']}`",
                    f"- Timing phase: `{item.get('timing_phase', 'unspecified')}`.",
                    f"- Profitable window: `{item.get('profitable_window_start')}` through `{item.get('profitable_window_end')}`; duration `{item.get('profitable_window_duration_seconds')}` seconds; profitable snapshots `{item.get('profitable_snapshots')}`.",
                    f"- Best timestamp inside that window: `{item.get('best_timestamp') or item['timestamp']}`.",
                    f"- Polymarket contract: `{item['polymarket_title']}`",
                    f"- Kalshi contract: `{item['kalshi_title']}`",
                    f"- Order size used for the arithmetic: `{item['size_contracts']}` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.",
                    f"- Buy YES on `{item['yes_venue']}` at `{_money(item['yes_price'])}` and NO on `{item['no_venue']}` at `{_money(item['no_price'])}`.",
                    f"- Pair cost per paired contract: `{_money(item['pair_cost'])}`; total entry fees for the modeled order: `{_money(item['fees_total'])}`; slippage detail per contract: `{_money(item['slippage'])}`.",
                    f"- Displayed depth: `{item['depth_contracts'] if item['depth_contracts'] is not None else 'proxy only; unavailable'}` contracts.",
                    f"- Paired ladder capacity: `{item['paired_capacity_contracts'] if item['paired_capacity_contracts'] is not None else 'proxy only; unavailable'}` contracts; one-leg exposure if pairing fails: `{item['one_leg_partial_fill_exposure_contracts'] if item['one_leg_partial_fill_exposure_contracts'] is not None else 'proxy only; unavailable'}` contracts.",
                    f"- Locked net profit per contract: `{_money(item['locked_profit_per_contract'])}`.",
                    f"- Locked net profit for the modeled order: `{_money(float(item['locked_profit_per_contract']) * float(item['size_contracts']))}`.",
                    f"- ROI on entry capital: `{float(item['roi_on_entry_cost']):.2%}`.",
                    f"- Qualifying paired exit: `{item['paired_exit_qualifies']}`; exit time: `{item['paired_exit_at']}`; improvement: `{_money(item['paired_exit_improvement_per_contract'])}`.",
                    f"- Review status: `{item['manual_review_status']}`.",
                    "",
                ]
            )
            screened_periods = item.get("screened_periods") or []
            if screened_periods:
                lines.extend(
                    [
                        "Historical periods inspected for this matched pair:",
                        "",
                        "| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |",
                        "|---|---|---|---:|",
                    ]
                )
                for period in screened_periods:
                    lines.append(
                        f"| `{period['phase']}` | `{period['window_start']}` through `{period['window_end']}` "
                        f"| {period['sampling_interval']} | {period['aligned_snapshots']} |"
                    )
                lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")


def write_scenario_analysis_report(
    manifest: dict[str, Any],
    trade_examples: dict[str, Any],
    l2_result: dict[str, Any] | None,
    annual_result: dict[str, Any] | None,
    out_path: str | Path,
    *,
    leaderboards: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    target = Path(out_path)
    scenarios = [*FOCUS_SCENARIOS, ADDITIONAL_DISCOVERED_SECTION]
    examples_by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in trade_examples.get("examples", []):
        examples_by_scenario[item["scenario"]].append(item)
    annual_by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in (annual_result or {}).get("opportunities", []):
        if float(item.get("net_edge_per_contract") or 0) <= 0:
            continue
        if strict_match_rejection(
            item.get("polymarket_title", ""),
            item.get("kalshi_title", ""),
        ):
            continue
        scenario = item.get("focus_scenario") or classify_focus_scenario(
            f"{item.get('polymarket_title', '')} {item.get('kalshi_title', '')}"
        )
        annual_by_scenario[scenario].append(item)
    l2_by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in (l2_result or {}).get("windows", []):
        if int(item.get("size_contracts") or 0) != HEADLINE_ORDER_SIZE:
            continue
        if float(item.get("locked_hold_profit_per_contract") or 0) <= 0:
            continue
        scenario = item.get("focus_scenario") or classify_focus_scenario(
            f"{item.get('polymarket_title', '')} {item.get('kalshi_title', '')}"
        )
        l2_by_scenario[scenario].append(item)
    official = manifest.get("evidence_layers", {}).get("international_official_api", {})
    pmxt = manifest.get("evidence_layers", {}).get("international_pmxt_l2", {})
    coverage_by_scenario = {
        item["focus_scenario"]: item
        for item in (annual_result or {}).get("coverage_by_focus_scenario", [])
    }
    capped_months = _catalog_cap_summary(official)
    replay_hours = (l2_result or {}).get("parameters", {}).get("hours_completed", 0)
    ranked = []
    for scenario in scenarios:
        values = [
            *[float(item["net_edge_per_contract"]) for item in annual_by_scenario.get(scenario, [])],
            *[float(item["locked_hold_profit_per_contract"]) for item in l2_by_scenario.get(scenario, [])],
        ]
        ranked.append(
            {
                "scenario": scenario,
                "annual": len(annual_by_scenario.get(scenario, [])),
                "l2": len(l2_by_scenario.get(scenario, [])),
                "best": max(values) if values else None,
            }
        )
    ranked.sort(key=lambda item: (item["best"] is not None, item["best"] or -1, item["annual"] + item["l2"]), reverse=True)
    lines = [
        "# Annual Scenario Analysis",
        "",
        "Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)",
        "",
        "## What This Report Answers",
        "",
        "This report asks which kinds of prediction-market contracts produced the strongest retained cross-venue "
        "arbitrage evidence. It shows profitable examples directly in Markdown. You do not need to inspect the JSON files "
        "to understand the conclusions.",
        "",
        "A category without a displayed profitable trade says `No profitable example found.` The category section also explains "
        "whether that means a complete negative screen, unavailable synchronized history, or no recovered strict equivalent pair.",
        "",
        "## Evidence Quality",
        "",
        "There are two international evidence layers. They answer different questions:",
        "",
        "| Layer | Plain-English meaning | What it can prove |",
        "|---|---|---|",
        f"| Annual official API proxy | Historical Kalshi and international Polymarket prices across the requested rolling year | Whether a price gap survives modeled fees and `1`, `2`, or `5` cents of assumed pair slippage. It cannot prove historical displayed depth. |",
        f"| PMXT archive inventory | `{pmxt.get('verified_overlap_hours', 0)}` synchronized raw archive hours were discovered and verified | Which hours are eligible for executable replay. Inventory alone is not a profit result. |",
        f"| PMXT archived L2 replay | Stored multi-level order books for `{replay_hours}` replayed hours in this result file | Whether both visible books supported a requested order size after walking deeper prices. This is stronger executable evidence. |",
        "",
        f"The requested annual window is `{manifest.get('requested_window', {}).get('start')}` through "
        f"`{manifest.get('requested_window', {}).get('end')}`. The oldest Kalshi close time reached so far is "
        f"`{official.get('kalshi_oldest_close_time_reached', 'pending')}`. Full requested Kalshi history reached: "
        f"`{official.get('kalshi_historical_complete', 'pending')}`.",
        "",
        "## Completeness Disclosure",
        "",
        "The annual Kalshi historical cursor traversal and the combined two-venue profitability study are different things. "
        "The Kalshi historical traversal can be complete even when a public catalog endpoint on either venue still contains "
        "more rows than the configured retained-page cap.",
        "",
        f"- Combined international catalog scope: `{official.get('combined_catalog_scope', 'pending')}`.",
        f"- Explicitly capped catalog slices: `{capped_months or 'none recorded'}`.",
        f"- Annual price-proxy scan scope: `{official.get('proxy_scan_scope', 'pending')}`.",
        "",
        "When a slice is capped, the report describes the retained screen honestly. It does not claim that every possible "
        "cross-venue pair or profitable signal from that slice was exhaustively tested.",
        "",
        "## Essential Terms",
        "",
        "- **Prediction market**: a market where a contract pays `$1.00` if a stated event happens and `$0.00` otherwise.",
        "- **Cross-venue arbitrage**: buying opposite outcomes on two exchanges when their combined cost is below the eventual `$1.00` payout.",
        "- **Latency arbitrage**: a cross-venue opportunity caused by one exchange updating more slowly than another after new information arrives.",
        "- **Gross edge**: `$1.00 - YES price - NO price`, before fees and slippage.",
        "- **Net edge**: gross edge after subtracting exchange fees and slippage.",
        "- **Slippage**: the added cost of filling deeper book prices when the best price does not have enough quantity.",
        "- **L2**: a multi-level order book showing the best price and additional price levels behind it.",
        "- **VWAP**: volume-weighted average price, meaning the average paid after accounting for how many contracts fill at each price level.",
        "- **Parquet**: a compressed table-file format. PMXT stores archived order-book rows in Parquet files; it is a storage format, not a trading strategy.",
        "- **Opportunity window**: a continuous period when the pair remains profitable after costs.",
        "- **Pregame**: the period before a scheduled sporting event begins.",
        "- **In-play**: the period after a scheduled sporting event begins but before its final result. The annual study does not simulate new entries after final resolution.",
        "- **Sports event start unavailable**: the retained public metadata did not expose the scheduled start. The scanner inspects the final 24 hours before close but does not mislabel those observations as in-play.",
        "- **Lifecycle bucket**: a time-to-resolution group for a market without a live contest. For example, an oil-price deadline is grouped by how many days or hours remain before its cutoff.",
        "- **Modeled 100-contract order**: a hypothetical simultaneous purchase of 100 YES contracts and 100 matching NO contracts. In the annual proxy layer this is a sensitivity estimate, not proof of historical displayed quantity.",
        "- **Reclassified non-sports sample window**: a historical sample that was initially given sports-style timing because of an acronym collision, then relabeled after taxonomy cleanup. It remains a price observation, but it is not in-play sports evidence.",
        "- **ROI**: net profit divided by the cash used to buy the pair.",
        "",
        "## Ranked Retained Results",
        "",
        "This table ranks categories by the best positive retained net edge. A larger edge means more locked profit per paired contract. "
        "Counts are evidence rows, not a promise that every row could be captured live.",
        "",
        "| Rank | Category | Annual positive proxy rows | PMXT positive 100-contract windows | Best retained net profit per contract |",
        "|---:|---|---:|---:|---:|",
    ]
    category_rows = list((leaderboards or {}).get("category_leaderboard") or [])
    subscenario_rows = list((leaderboards or {}).get("subscenario_leaderboard") or [])
    if category_rows:
        lines.extend(
            [
                "",
                "## Official Category Ranking",
                "",
                "The `blended score` is not dollars. First, each category is ranked by annual modeled portfolio "
                "profit and converted to a percentile from `0` to `100`. The same is done for executable PMXT "
                "portfolio profit. The final score is `0.70 × annual percentile + 0.30 × PMXT percentile`. "
                "A category absent from PMXT receives a neutral PMXT percentile of `50` and is labeled unvalidated.",
                "",
                "| Rank | Category | Blended score | Annual percentile | Annual profit | Annual ROI | PMXT percentile | PMXT profit | Validation |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in category_rows:
            lines.append(
                f"| {row['rank']} | `{row['focus_scenario']}` | {row['blended_score']:.2f} "
                f"| {row['annual_profit_percentile']:.2f} | {_money(row['annual_net_profit'])} "
                f"| {row['annual_roi']:.2%} | {row['pmxt_profit_percentile']:.2f} "
                f"| {_money(row['pmxt_net_profit'])} | {row['pmxt_validation']} |"
            )
    if subscenario_rows:
        lines.extend(
            [
                "",
                "## Detailed Subscenario Ranking",
                "",
                "Each row combines category, competition stage, tournament or session level when applicable, "
                "market type, and entry timing. This is where NBA playoffs can be compared directly with NBA "
                "regular season, ATP Grand Slams, MLB postseason markets, and other specific situations.",
                "",
                "| Rank | Subscenario | Score | Annual profit | PMXT profit | Validation |",
                "|---:|---|---:|---:|---:|---|",
            ]
        )
        for row in subscenario_rows[:100]:
            lines.append(
                f"| {row['rank']} | `{row['subscenario']}` | {row['blended_score']:.2f} "
                f"| {_money(row['annual_net_profit'])} | {_money(row['pmxt_net_profit'])} "
                f"| {row['pmxt_validation']} |"
            )
    for index, item in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | {_scenario_label(item['scenario'])} | {item['annual']} | {item['l2']} | {_money(item['best'])} |"
        )
    lines.extend(
        [
            "",
            "## Broad Scenario Breakdown",
            "",
            "The requested focus categories are useful for navigation, but the uncapped run also keeps markets outside that list. "
            "This table shows the broader classifications produced by the retained strict-pair scanner.",
            "",
            "| Broad scenario | Strict pairs scanned | Pairs with synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(
        (annual_result or {}).get("summary_by_scenario") or [],
        key=lambda item: (
            item.get("max_net_edge_per_contract") is not None,
            item.get("max_net_edge_per_contract") or -1,
        ),
        reverse=True,
    ):
        lines.append(
            f"| `{row['scenario']}` | {row['markets']} | {row['markets_with_aligned_points']} "
            f"| {row['net_positive_points']} | {row['net_positive_windows']} "
            f"| {_money(row['max_net_edge_per_contract'])} |"
        )
    positive_ranked = [item for item in ranked if item["best"] is not None]
    if positive_ranked:
        leader = positive_ranked[0]
        lines.extend(
            [
                "",
                "## Current Comparison",
                "",
                f"`{_scenario_label(leader['scenario'])}` currently ranks first in the retained evidence because its best "
                f"positive row has `{_money(leader['best'])}` of net profit per paired contract after the modeled costs. "
                f"It contributes `{leader['annual']}` annual proxy rows and `{leader['l2']}` archived PMXT "
                f"100-contract windows.",
                "",
                "A PMXT archived-L2 result is stronger than a proxy-only result because it includes visible order-book quantity. "
                "A proxy-only category can still be worth investigating, but it needs later depth validation before the report "
                "treats it as executable historical evidence.",
            ]
        )
        if len(positive_ranked) > 1:
            runner_up = positive_ranked[1]
            lines.extend(
                [
                    "",
                    f"`{_scenario_label(runner_up['scenario'])}` ranks next with a best retained net profit of "
                    f"`{_money(runner_up['best'])}` per paired contract.",
                ]
            )
    lines.extend(
        [
            "",
            "## How To Interpret Differences",
            "",
            "Fast-moving markets can be attractive because prices need frequent updates. A score, point, injury, weather reading, "
            "or breaking political development may reach one exchange before the other. That creates a temporary disagreement. "
            "The same speed can also make the opportunity difficult to capture: a profitable window may disappear before both orders fill.",
            "",
            "A slower market can still be attractive when venues disagree for longer. Longer windows are easier to act on, but sparse trading "
            "can make the displayed quantity too small. This is why the PMXT L2 layer checks book depth and VWAP rather than looking only at one price.",
            "",
            "## Category Detail",
        ]
    )
    for scenario in scenarios:
        label = _scenario_label(scenario)
        meaning, subdivisions = SCENARIO_DETAILS[scenario]
        attractive, weaker = SCENARIO_INTERPRETATIONS[scenario]
        annual_rows = annual_by_scenario.get(scenario, [])
        l2_rows = l2_by_scenario.get(scenario, [])
        examples = examples_by_scenario.get(scenario, [])
        phase_breakdown = _annual_subcategory_breakdown(annual_result, scenario, "phase")
        market_type_breakdown = _annual_subcategory_breakdown(annual_result, scenario, "market_type")
        competition_breakdown = _annual_subcategory_breakdown(annual_result, scenario, "competition_phase")
        coverage = coverage_by_scenario.get(
            scenario,
            {
                "eligible_strict_pairs": 0,
                "kalshi_retained_catalog_rows": 0,
                "polymarket_retained_catalog_rows": 0,
                "selected_pairs": 0,
                "pairs_with_aligned_snapshots": 0,
                "aligned_snapshots": 0,
                "positive_pairs": 0,
                "positive_windows": 0,
                "status": "no_strict_equivalent_cross_venue_pair_recovered",
            },
        )
        positive_subcategories: Counter[str] = Counter()
        for item in annual_rows:
            positive_subcategories[f"annual proxy phase: {item.get('phase', 'unspecified')}"] += 1
        for item in l2_rows:
            positive_subcategories[f"PMXT timing phase: {item.get('timing_phase', 'unspecified')}"] += 1
            positive_subcategories[f"PMXT market type: {item.get('market_type', 'unspecified')}"] += 1
            positive_subcategories[f"PMXT competition phase: {item.get('competition_phase', 'unspecified')}"] += 1
        lines.extend(
            [
                "",
                f"### {label}",
                "",
                f"**What this category means:** {meaning}.",
                "",
                f"**Subcategories checked:** {subdivisions}.",
                "",
                f"**Why it could outperform:** {attractive}",
                "",
                f"**Why it could underperform:** {weaker}",
                "",
                f"**Retained profitable evidence:** `{len(annual_rows)}` annual price-proxy rows and "
                f"`{len(l2_rows)}` archived PMXT 100-contract opportunity windows.",
                "",
                f"**Annual coverage status:** `{coverage['status']}`.",
                "",
                f"**Coverage funnel:** `{coverage.get('kalshi_retained_catalog_rows', 0)}` Kalshi retained catalog rows and "
                f"`{coverage.get('polymarket_retained_catalog_rows', 0)}` international Polymarket retained catalog rows were classified here; "
                f"`{coverage['eligible_strict_pairs']}` strict equivalent pairs recovered; "
                f"`{coverage['selected_pairs']}` pairs selected for the annual scanner; "
                f"`{coverage['pairs_with_aligned_snapshots']}` pairs produced synchronized historical price snapshots; "
                f"`{coverage['aligned_snapshots']}` synchronized snapshots aligned; "
                f"`{coverage['positive_pairs']}` matched pairs produced a positive proxy window.",
                "",
            ]
        )
        if not examples:
            _append_subcategory_tables(lines, phase_breakdown, market_type_breakdown, competition_breakdown)
            lines.extend(
                [
                    "No profitable example found.",
                    "",
                    _plain_coverage_explanation(coverage["status"]),
                ]
            )
            continue
        best = max(examples, key=lambda item: float(item["locked_profit_per_contract"]))
        lines.extend(
            [
                f"**Best retained example:** `{best['polymarket_title']}` with "
                f"`{_money(best['locked_profit_per_contract'])}` locked net profit per paired contract.",
                "",
                "**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking "
                "cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: "
                "archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.",
                "",
            ]
        )
        if positive_subcategories:
            lines.extend(
                [
                    "**Observed positive subcategory counts:**",
                    "",
                    "| Positive subcategory label | Retained evidence rows |",
                    "|---|---:|",
                ]
            )
            for subcategory, count in positive_subcategories.most_common():
                lines.append(f"| `{subcategory}` | {count} |")
            lines.append("")
        _append_subcategory_tables(lines, phase_breakdown, market_type_breakdown, competition_breakdown)
        lines.extend(["**Profitable examples:**", ""])
        for item in examples:
            lines.extend(
                [
                    f"- `{item['timestamp']}`: buy YES on `{item['yes_venue']}` at `{_money(item['yes_price'])}` "
                    f"and NO on `{item['no_venue']}` at `{_money(item['no_price'])}` for `{item['size_contracts']}` paired contracts. "
                    f"Pair cost per contract `{_money(item['pair_cost'])}`; total entry fees for the order `{_money(item['fees_total'])}`; "
                    f"locked net profit `{_money(item['locked_profit_per_contract'])}` "
                    f"per paired contract; ROI `{float(item['roi_on_entry_cost']):.2%}`. Evidence: `{item['evidence_label']}`.",
                ]
            )
    lines.extend(
        [
            "",
            "## Important Limits",
            "",
            "- A price-history proxy is a screening result, not proof that both trades were fillable at the same instant.",
            "- Archived L2 replay enforces visible quantity, but it still cannot guarantee live queue position or network latency.",
            "- Automatically matched contracts still require a manual settlement-rule review before live trading.",
            "- Polymarket US public catalog data is analyzed separately and must not be treated as historical profit evidence.",
        ]
    )
    target.write_text("\n".join(lines), encoding="utf-8")


def _scenario_label(value: str) -> str:
    return SCENARIO_LABELS.get(value, value.replace("_", " ").title())


def _catalog_cap_summary(official: dict[str, Any]) -> str:
    capped = []
    for row in official.get("months") or []:
        venues = []
        if row.get("kalshi_truncated"):
            venues.append("Kalshi")
        if row.get("polymarket_truncated"):
            venues.append("Polymarket")
        if venues:
            capped.append(f"{row.get('month')}: {' and '.join(venues)}")
    return "; ".join(capped)


def _plain_coverage_explanation(status: str) -> str:
    return {
        "no_strict_equivalent_cross_venue_pair_recovered": (
            "This is not a claim that the category was unprofitable. The retained catalogs did not produce a "
            "strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run."
        ),
        "partially_scanned_due_configured_sampling_cap": (
            "This category was sampled but not exhaustively scanned. Treat the missing example as inconclusive."
        ),
        "strict_pairs_scanned_but_no_synchronized_price_snapshots_available": (
            "Equivalent-looking pairs reached the scanner, but the official histories did not produce prices aligned "
            "to the same timestamps on both venues. The missing example is a data-availability result, not proof of no opportunity."
        ),
        "fully_scanned_with_aligned_history_and_no_profitable_price_proxy_window_found": (
            "Every retained strict pair in this category reached the annual scanner and produced synchronized prices, "
            "but none survived the stated fee and slippage assumptions."
        ),
        "scan_completed_with_api_errors_and_no_profitable_price_proxy_window_found": (
            "The scan did not retain a profitable example and at least one API request failed. Treat the result as incomplete."
        ),
    }.get(status, "The status above records the evidence available for this category.")


def _annual_subcategory_breakdown(
    annual_result: dict[str, Any] | None,
    focus_scenario: str,
    key: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in (annual_result or {}).get("phase_records") or []:
        if item.get("focus_scenario") == focus_scenario:
            grouped[str(item.get(key) or "unspecified")].append(item)
    rows = []
    for label, items in sorted(grouped.items()):
        best = [
            float(item["best_net_edge_per_contract"])
            for item in items
            if item.get("best_net_edge_per_contract") is not None
        ]
        rows.append(
            {
                "label": label,
                "strict_pairs": len({item["match_id"] for item in items}),
                "aligned_snapshots": sum(int(item.get("aligned_points") or 0) for item in items),
                "positive_snapshots": sum(int(item.get("net_positive_points") or 0) for item in items),
                "positive_windows": sum(int(item.get("net_positive_windows") or 0) for item in items),
                "best_net_edge": max(best) if best else None,
            }
        )
    return rows


def _append_subcategory_tables(
    lines: list[str],
    phase_breakdown: list[dict[str, Any]],
    market_type_breakdown: list[dict[str, Any]],
    competition_breakdown: list[dict[str, Any]],
) -> None:
    for heading, rows in [
        ("Timing-phase comparison", phase_breakdown),
        ("Market-type comparison", market_type_breakdown),
        ("Competition-phase comparison", competition_breakdown),
    ]:
        if not rows:
            continue
        lines.extend(
            [
                f"**{heading}:**",
                "",
                "| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in rows:
            lines.append(
                f"| `{row['label']}` | {row['strict_pairs']} | {row['aligned_snapshots']} "
                f"| {row['positive_snapshots']} | {row['positive_windows']} | {_money(row['best_net_edge'])} |"
            )
        lines.append("")


def _money(value: Any) -> str:
    return "n/a" if value is None else f"${float(value):.6f}"
