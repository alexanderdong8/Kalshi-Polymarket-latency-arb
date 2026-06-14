from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path
from statistics import mean, median
from typing import Any

from .models import MatchedMarket
from .adaptive_sampling import adaptive_sampling_windows
from .official_api import KalshiOfficialClient, PolymarketOfficialClient
from .official_catalog import (
    _kalshi_record,
    _parse_iso as _parse_catalog_iso,
    _poly_record,
    _sports_contract_rejection,
)
from .official_price_scanner import _align_official_series, _evaluate_proxy_state
from .scenario import classify_domain, classify_scenario, scenario_metadata
from .serde import read_json, write_json
from .strict_matching import strict_market_rejection
from .research_config import ADDITIONAL_DISCOVERED_SECTION, ANNUAL_PAIR_SLIPPAGE_CASES, FOCUS_SCENARIOS
from .portfolio import simulate_portfolio
from .research_config import ORDER_SIZE_LADDER


def scan_annual_official_proxy(
    matches: list[MatchedMarket],
    start: str,
    end: str,
    out_json: str | Path,
    out_md: str | Path,
    max_markets_per_month: int = 0,
    workers: int = 6,
    trade_size: int = 100,
    slippage_buffer: float = 0.005,
    kalshi_fee_mode: str = "taker",
    polymarket_fallback_fee_rate: float = 0.05,
    catalog_meta: dict[str, Any] | None = None,
    pair_slippage_cases: list[float] | None = None,
    checkpoint_dir: str | Path | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    eligible_matches, strict_title_rejections = _strict_title_equivalent_matches(matches)
    selected, selection = _select_stratified(eligible_matches, start_dt, end_dt, max_markets_per_month)
    slippage_cases = pair_slippage_cases or ANNUAL_PAIR_SLIPPAGE_CASES
    tasks = [
        (match, phase, window_start, window_end, interval)
        for match in selected
        for phase, window_start, window_end, interval in _phase_windows(match, start_dt)
    ]
    phase_records = []
    opportunities = []
    errors = []
    checkpoint_root = Path(checkpoint_dir) if checkpoint_dir else None
    if checkpoint_root:
        checkpoint_root.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(
                _scan_phase_checkpointed,
                match,
                phase,
                window_start,
                window_end,
                interval,
                slippage_cases,
                trade_size,
                slippage_buffer,
                kalshi_fee_mode,
                polymarket_fallback_fee_rate,
                checkpoint_root,
                resume,
            ): (match.match_id, phase)
            for match, phase, window_start, window_end, interval in tasks
        }
        for completed, future in enumerate(as_completed(future_map), start=1):
            match_id, phase = future_map[future]
            try:
                records, phase_opportunities = future.result()
                phase_records.extend(records)
                opportunities.extend(phase_opportunities)
            except Exception as exc:  # noqa: BLE001
                errors.append({"match_id": match_id, "phase": phase, "error": str(exc)})
            if completed % 10 == 0 or completed == len(future_map):
                print(
                    f"Completed annual proxy phase scans {completed}/{len(future_map)}; "
                    f"errors={len(errors)}"
                )

    phase_records.sort(key=lambda item: (item["month"], item["domain"], item["phase"], item["match_id"]))
    opportunities = [_dict_item(item) for item in opportunities]
    opportunities.sort(key=lambda item: item["net_edge_per_contract"], reverse=True)
    opportunity_windows = build_annual_opportunity_windows(opportunities)
    result = {
        "parameters": {
            "source": "official_api_price_history_proxy",
            "catalog_start": start_dt.isoformat(),
            "catalog_end": end_dt.isoformat(),
            "selected_markets": len(selected),
            "strict_title_rejections": strict_title_rejections,
            "max_markets_per_month": max_markets_per_month,
            "trade_size": trade_size,
            "slippage_buffer": slippage_buffer,
            "pair_slippage_cases": slippage_cases,
            "catalog_meta": catalog_meta or {},
            "eligible_strict_pairs": len(eligible_matches),
            "phase_scan_tasks": len(tasks),
            "phase_scan_checkpoints": str(checkpoint_root) if checkpoint_root else None,
            "resume_enabled": resume,
            "timing_windows": {
                "sports_pregame_slow": "available sports history until 24 hours before scheduled play, sampled hourly",
                "sports_pregame_final_24h": "final 24 hours before scheduled play, sampled each five minutes",
                "sports_in_play": "scheduled sports start through close, sampled each minute",
                "sports_event_start_unavailable_final_24h": "final 24 hours for a sports market whose retained public metadata did not expose the scheduled start, sampled each five minutes and not labeled in-play",
                "lifecycle_more_than_30d": "non-sports history more than 30 days before close, sampled daily",
                "lifecycle_30d_to_24h": "non-sports history from 30 days to 24 hours before close, sampled hourly",
                "lifecycle_final_24h": "final 24 hours for non-sports, sampled each five minutes",
            },
            "note": (
                "This is an official price/candlestick proxy screen over matches reached inside the requested "
                "12-month catalog window. Catalog coverage may still be incomplete. It does not contain "
                "synchronized historical bid/ask depth and cannot prove fillability. Use PMXT "
                "orderbook replay for executable examples where archive overlap exists."
            ),
        },
        "selection_by_month": selection,
        "summary_by_month": _summarize(phase_records, ["month"]),
        "summary_by_domain": _summarize(phase_records, ["domain"]),
        "summary_by_scenario": _summarize(phase_records, ["scenario"]),
        "summary_by_focus_scenario": _summarize(phase_records, ["focus_scenario"]),
        "summary_by_scenario_phase": _summarize(phase_records, ["scenario", "phase"]),
        "summary_by_focus_market_type": _summarize(phase_records, ["focus_scenario", "market_type"]),
        "summary_by_focus_competition_phase": _summarize(phase_records, ["focus_scenario", "competition_phase"]),
        "summary_by_slippage": _summarize(phase_records, ["pair_slippage_assumption"]),
        "phase_records": phase_records,
        "opportunity_windows": opportunity_windows,
        "coverage_by_focus_scenario": build_focus_coverage(
            eligible_matches,
            selected,
            phase_records,
            opportunities,
            errors,
            catalog_meta or {},
        ),
        "opportunities": opportunities,
        "portfolio_appendix": _proxy_portfolio_appendix(opportunities, matches, trade_size, slippage_cases),
        "errors": errors,
    }
    result = normalize_annual_proxy_result_metadata(result, matches)
    write_json(out_json, result)
    target = Path(out_md)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_markdown(result), encoding="utf-8")
    return result


def normalize_annual_proxy_result_metadata(
    result: dict[str, Any],
    matches: list[MatchedMarket],
) -> dict[str, Any]:
    """Refresh taxonomy fields after loading checkpoints created by an older classifier."""
    cleaned = dict(result)
    parameters = cleaned["parameters"]
    start = _parse_iso(parameters["catalog_start"])
    end = _parse_iso(parameters["catalog_end"])
    eligible_matches, strict_title_rejections = _strict_title_equivalent_matches(matches)
    selected_matches, selection = _select_stratified(
        eligible_matches,
        start,
        end,
        int(parameters.get("max_markets_per_month") or 0),
    )
    matches_by_id = {match.match_id: match for match in selected_matches}
    cleaned["parameters"] = {
        **parameters,
        "strict_title_rejections": strict_title_rejections,
        "eligible_strict_pairs": len(eligible_matches),
        "selected_markets": len(selected_matches),
    }
    cleaned["selection_by_month"] = selection
    cleaned["phase_records"] = [
        _with_scenario_metadata(item, matches_by_id.get(item["match_id"]))
        for item in cleaned.get("phase_records", [])
    ]
    cleaned["opportunities"] = [
        _with_scenario_metadata(item, matches_by_id.get(item["match_id"]))
        for item in cleaned.get("opportunities", [])
    ]
    cleaned["opportunities"].sort(key=lambda item: item["net_edge_per_contract"], reverse=True)
    cleaned["opportunity_windows"] = build_annual_opportunity_windows(cleaned["opportunities"])
    cleaned["summary_by_month"] = _summarize(cleaned["phase_records"], ["month"])
    cleaned["summary_by_domain"] = _summarize(cleaned["phase_records"], ["domain"])
    cleaned["summary_by_scenario"] = _summarize(cleaned["phase_records"], ["scenario"])
    cleaned["summary_by_focus_scenario"] = _summarize(cleaned["phase_records"], ["focus_scenario"])
    cleaned["summary_by_scenario_phase"] = _summarize(cleaned["phase_records"], ["scenario", "phase"])
    cleaned["summary_by_focus_market_type"] = _summarize(cleaned["phase_records"], ["focus_scenario", "market_type"])
    cleaned["summary_by_focus_competition_phase"] = _summarize(
        cleaned["phase_records"], ["focus_scenario", "competition_phase"]
    )
    cleaned["summary_by_slippage"] = _summarize(cleaned["phase_records"], ["pair_slippage_assumption"])
    cleaned["coverage_by_focus_scenario"] = build_focus_coverage(
        eligible_matches,
        selected_matches,
        cleaned["phase_records"],
        cleaned["opportunities"],
        cleaned.get("errors") or [],
        parameters.get("catalog_meta") or {},
    )
    cleaned["portfolio_appendix"] = _proxy_portfolio_appendix(
        cleaned["opportunities"],
        matches,
        int(parameters["trade_size"]),
        list(parameters["pair_slippage_cases"]),
    )
    return cleaned


def _with_scenario_metadata(item: dict[str, Any], match: MatchedMarket | None) -> dict[str, Any]:
    title = (
        _scenario_text(match)
        if match
        else f"{item.get('polymarket_title', '')} {item.get('kalshi_title', '')}"
    )
    category = (match.polymarket.category or match.kalshi.category) if match else None
    metadata = scenario_metadata(title, category)
    return {
        **item,
        **metadata,
        "scenario": metadata["broad_scenario"],
        "phase": _reclassified_phase(item["phase"], metadata["domain"]),
    }


def _scan_phase_checkpointed(
    match: MatchedMarket,
    phase: str,
    start: datetime,
    end: datetime,
    interval_minutes: int,
    pair_slippage_assumptions: list[float],
    trade_size: int,
    slippage_buffer: float,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
    checkpoint_dir: Path | None,
    resume: bool,
):
    checkpoint = (
        checkpoint_dir / f"{_phase_checkpoint_key(match.match_id, phase, start, end, interval_minutes)}.json"
        if checkpoint_dir
        else None
    )
    if checkpoint and resume and checkpoint.exists():
        payload = _read_checkpoint(checkpoint)
        if payload.get("complete"):
            return payload.get("phase_records", []), payload.get("opportunities", [])
    try:
        records, opportunities = _scan_phase(
            match,
            phase,
            start,
            end,
            interval_minutes,
            pair_slippage_assumptions,
            trade_size,
            slippage_buffer,
            kalshi_fee_mode,
            polymarket_fallback_fee_rate,
        )
    except Exception as exc:  # noqa: BLE001
        if checkpoint:
            write_json(
                checkpoint,
                {
                    "complete": False,
                    "match_id": match.match_id,
                    "phase": phase,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "interval_minutes": interval_minutes,
                    "error": str(exc),
                },
            )
        raise
    if checkpoint:
        write_json(
            checkpoint,
            {
                "complete": True,
                "match_id": match.match_id,
                "phase": phase,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "interval_minutes": interval_minutes,
                "phase_records": records,
                "opportunities": [_dict_item(item) for item in opportunities],
            },
        )
    return records, opportunities


def _scan_phase(
    match: MatchedMarket,
    phase: str,
    start: datetime,
    end: datetime,
    interval_minutes: int,
    pair_slippage_assumptions: list[float],
    trade_size: int,
    slippage_buffer: float,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
):
    poly = PolymarketOfficialClient()
    kalshi = KalshiOfficialClient()
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())
    ticker = match.kalshi.slug or match.kalshi.yes.outcome_id
    kalshi_interval = 1 if interval_minutes == 5 else interval_minutes
    kalshi_rows = kalshi.market_candlesticks_auto(ticker, start_ts, end_ts, kalshi_interval)
    poly_yes = poly.prices_history(match.polymarket.yes.outcome_id, start_ts, end_ts, interval_minutes)
    poly_no = poly.prices_history(match.polymarket.no.outcome_id, start_ts, end_ts, interval_minutes)
    bucket_seconds = interval_minutes * 60
    states = _align_official_series(kalshi_rows, poly_yes, poly_no, bucket_seconds=bucket_seconds)
    title = _scenario_text(match)
    domain = classify_domain(title, match.polymarket.category or match.kalshi.category)
    scenario = classify_scenario(title, match.polymarket.category or match.kalshi.category)
    metadata = scenario_metadata(title, match.polymarket.category or match.kalshi.category)
    event_dt = _match_date(match)
    records = []
    all_opportunities = []
    for pair_slippage_assumption in pair_slippage_assumptions:
        opportunities = []
        gross_positive = 0
        for state in states:
            state_opps = _evaluate_proxy_state(
                match,
                state,
                domain,
                phase,
                trade_size,
                slippage_buffer,
                kalshi_fee_mode,
                polymarket_fallback_fee_rate,
                pair_slippage_assumption=pair_slippage_assumption,
            )
            gross_positive += len(state_opps)
            opportunities.extend(item for item in state_opps if item.net_edge_per_contract > 0)
        windows = _proxy_windows([asdict(item) for item in opportunities], bucket_seconds)
        records.append(
            {
                "match_id": match.match_id,
                "month": event_dt.strftime("%Y-%m"),
                "domain": domain,
                "scenario": scenario,
                **metadata,
                "participant_or_team": _participant_or_team(match),
                "phase": phase,
                "pair_slippage_assumption": pair_slippage_assumption,
                "polymarket_title": match.polymarket.title,
                "kalshi_title": match.kalshi.title,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "aligned_points": len(states),
                "gross_positive_points": gross_positive,
                "net_positive_points": len(opportunities),
                "net_positive_windows": len(windows),
                "proxy_directions_tested": 2 * len(states),
                "mean_net_edge_on_positive_points": mean(item.net_edge_per_contract for item in opportunities) if opportunities else None,
                "mean_roi_on_positive_points": mean(item.roi_on_entry_cost for item in opportunities) if opportunities else None,
                "median_net_edge_on_positive_points": median(item.net_edge_per_contract for item in opportunities) if opportunities else None,
                "median_net_window_seconds": median([item["duration_seconds"] for item in windows]) if windows else None,
                "best_net_edge_per_contract": max((item.net_edge_per_contract for item in opportunities), default=None),
                "best_gross_edge_per_contract": max((item.gross_edge_per_contract for item in opportunities), default=None),
                "warning": match.resolution_date_warning,
            }
        )
        all_opportunities.extend(opportunities)
    return records, all_opportunities


def build_annual_opportunity_windows(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for item in opportunities:
        grouped[
            (
                item["match_id"],
                item["direction"],
                item.get("phase") or "unspecified",
                float(item.get("pair_slippage_assumption") or 0),
            )
        ].append(item)
    windows = []
    for (match_id, direction, phase, pair_slippage), items in grouped.items():
        interval_seconds = _phase_interval_seconds(phase)
        sorted_items = sorted(items, key=lambda item: _parse_iso(item["timestamp"]))
        current = [sorted_items[0]]
        for item in sorted_items[1:]:
            prior = _parse_iso(current[-1]["timestamp"])
            timestamp = _parse_iso(item["timestamp"])
            if (timestamp - prior).total_seconds() > interval_seconds * 1.5:
                windows.append(_finalize_annual_window(match_id, direction, phase, pair_slippage, current))
                current = []
            current.append(item)
        windows.append(_finalize_annual_window(match_id, direction, phase, pair_slippage, current))
    return sorted(
        windows,
        key=lambda item: (item["best_net_edge_per_contract"], item["duration_seconds"]),
        reverse=True,
    )


def build_focus_coverage(
    eligible_matches: list[MatchedMarket],
    selected_matches: list[MatchedMarket],
    phase_records: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    catalog_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    eligible = _count_focus_matches(eligible_matches)
    selected = _count_focus_matches(selected_matches)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in phase_records:
        records[item.get("focus_scenario") or ADDITIONAL_DISCOVERED_SECTION].append(item)
    selected_scenario_by_match = {
        match.match_id: scenario_metadata(
            _scenario_text(match),
            match.polymarket.category or match.kalshi.category,
        )["focus_scenario"]
        for match in selected_matches
    }
    error_match_ids: dict[str, set[str]] = defaultdict(set)
    for item in errors:
        error_match_ids[selected_scenario_by_match.get(item["match_id"], ADDITIONAL_DISCOVERED_SECTION)].add(
            item["match_id"]
        )
    positive_match_ids: dict[str, set[str]] = defaultdict(set)
    for item in opportunities:
        positive_match_ids[selected_scenario_by_match.get(item["match_id"], ADDITIONAL_DISCOVERED_SECTION)].add(
            item["match_id"]
        )
    scenarios = [*FOCUS_SCENARIOS, ADDITIONAL_DISCOVERED_SECTION]
    return [
        _focus_coverage_row(
            scenario,
            eligible.get(scenario, 0),
            selected.get(scenario, 0),
            records.get(scenario, []),
            positive_match_ids.get(scenario, set()),
            error_match_ids.get(scenario, set()),
            (catalog_meta or {}).get("kalshi_catalog_focus_scenarios", {}).get(scenario, 0),
            (catalog_meta or {}).get("polymarket_catalog_focus_scenarios", {}).get(scenario, 0),
        )
        for scenario in scenarios
    ]


def _select_stratified(
    matches: list[MatchedMarket],
    start: datetime,
    end: datetime,
    max_per_month: int,
) -> tuple[list[MatchedMarket], dict[str, Any]]:
    grouped: dict[str, dict[str, list[MatchedMarket]]] = defaultdict(lambda: defaultdict(list))
    for match in matches:
        event_dt = _match_date(match)
        if not start <= event_dt < end:
            continue
        title = _scenario_text(match)
        scenario = classify_scenario(title, match.polymarket.category or match.kalshi.category)
        grouped[event_dt.strftime("%Y-%m")][scenario].append(match)

    selected = []
    selection = {}
    for month, buckets in sorted(grouped.items()):
        for items in buckets.values():
            items.sort(key=lambda item: item.confidence, reverse=True)
        month_selected = []
        target = max_per_month if max_per_month > 0 else sum(len(items) for items in buckets.values())
        while len(month_selected) < target and any(buckets.values()):
            for scenario in sorted(buckets):
                if buckets[scenario] and len(month_selected) < target:
                    month_selected.append(buckets[scenario].pop(0))
        selected.extend(month_selected)
        selection[month] = {
            "selected_markets": len(month_selected),
            "selected_by_domain": _count_domains(month_selected),
            "selected_by_scenario": _count_scenarios(month_selected),
        }
    return selected, selection


def _phase_windows(match: MatchedMarket, study_start: datetime):
    event_dt = _match_date(match)
    domain = classify_domain(
        _scenario_text(match),
        match.polymarket.category or match.kalshi.category,
    )
    is_sports = domain.startswith("sports_")
    raw = {**match.polymarket.raw, **match.kalshi.raw}
    event_start = _parse_optional(raw.get("gameStartTime") or raw.get("start_time") or raw.get("event_start"))
    history_start = max(study_start, _parse_optional(raw.get("startDate")) or event_dt - timedelta(days=90))
    return [
        (window.label, window.start, window.end, window.interval_minutes)
        for window in adaptive_sampling_windows(
            history_start,
            event_dt,
            is_sports=is_sports,
            event_start=event_start,
        )
    ]


def _proxy_windows(opportunities: list[dict[str, Any]], bucket_seconds: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in opportunities:
        grouped[(item["match_id"], item["direction"])].append(item)
    windows = []
    for (match_id, direction), items in grouped.items():
        timestamps = sorted(_parse_iso(item["timestamp"]) for item in items)
        current_start = timestamps[0]
        previous = timestamps[0]
        for timestamp in timestamps[1:]:
            if (timestamp - previous).total_seconds() > bucket_seconds * 1.5:
                windows.append(_window(match_id, direction, current_start, previous))
                current_start = timestamp
            previous = timestamp
        windows.append(_window(match_id, direction, current_start, previous))
    return windows


def _proxy_portfolio_appendix(
    opportunities,
    matches: list[MatchedMarket],
    fee_trade_size: int,
    slippage_cases: list[float],
) -> list[dict[str, Any]]:
    settlement_by_match = {
        match.match_id: match.polymarket.resolution_date or match.kalshi.resolution_date
        for match in matches
    }
    cases = []
    for slippage in slippage_cases:
        rows = [
            {
                "match_id": _item_value(item, "match_id"),
                "start": _item_value(item, "timestamp"),
                "settlement_at": settlement_by_match.get(_item_value(item, "match_id")) or _item_value(item, "timestamp"),
                "entry_cost_per_contract": (
                    _item_value(item, "total_cost")
                    + (_item_value(item, "total_fee") / fee_trade_size)
                    + float(_item_value(item, "pair_slippage_assumption") or 0)
                ),
                "net_profit_per_contract": _item_value(item, "net_edge_per_contract"),
            }
            for item in opportunities
            if _item_value(item, "pair_slippage_assumption") == slippage
            and _item_value(item, "net_edge_per_contract") > 0
        ]
        for contracts in ORDER_SIZE_LADDER:
            result = simulate_portfolio(rows, contracts=contracts, enforce_depth=False)
            cases.append(
                {
                    "pair_slippage_assumption": slippage,
                    "contracts": contracts,
                    "evidence_label": "modeled_sensitivity_without_historical_depth_gating",
                    **{key: result[key] for key in [
                        "starting_bankroll",
                        "ending_bankroll",
                        "realized_profit",
                        "accepted_positions",
                        "rejected",
                    ]},
                }
            )
    return cases


def filter_annual_proxy_result_for_strict_title_equivalence(
    result: dict[str, Any],
    matches: list[MatchedMarket],
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
) -> dict[str, Any]:
    _, strict_title_rejections = _strict_title_equivalent_matches(matches)
    rejected_ids = {item["match_id"] for item in strict_title_rejections}
    matches_by_id = {match.match_id: match for match in matches}
    cleaned = dict(result)
    base_note = result["parameters"]["note"].split(
        " Reader-facing summaries exclude ",
        1,
    )[0]
    cleaned["parameters"] = {
        **result["parameters"],
        "strict_title_rejections": strict_title_rejections,
        "note": (
            f"{base_note} "
            f"Reader-facing summaries exclude {len(rejected_ids)} title pairs rejected by the stricter "
            "post-scan semantic gate."
        ),
    }
    cleaned["phase_records"] = []
    for item in result.get("phase_records", []):
        if item["match_id"] in rejected_ids:
            continue
        match = matches_by_id.get(item["match_id"])
        title = _scenario_text(match) if match else f"{item.get('polymarket_title', '')} {item.get('kalshi_title', '')}"
        metadata = scenario_metadata(title)
        cleaned["phase_records"].append(
            {
                **item,
                **metadata,
                "scenario": metadata["broad_scenario"],
                "phase": _reclassified_phase(item["phase"], metadata["domain"]),
            }
        )
    cleaned["opportunities"] = []
    for item in result.get("opportunities", []):
        if item["match_id"] in rejected_ids:
            continue
        match = matches_by_id.get(item["match_id"])
        title = _scenario_text(match) if match else f"{item.get('polymarket_title', '')} {item.get('kalshi_title', '')}"
        metadata = scenario_metadata(title)
        cleaned["opportunities"].append(
            {
                **item,
                **metadata,
                "scenario": metadata["broad_scenario"],
                "phase": _reclassified_phase(item["phase"], metadata["domain"]),
            }
        )
    cleaned["summary_by_month"] = _summarize(cleaned["phase_records"], ["month"])
    cleaned["summary_by_domain"] = _summarize(cleaned["phase_records"], ["domain"])
    cleaned["summary_by_scenario"] = _summarize(cleaned["phase_records"], ["scenario"])
    cleaned["summary_by_focus_scenario"] = _summarize(cleaned["phase_records"], ["focus_scenario"])
    cleaned["summary_by_scenario_phase"] = _summarize(cleaned["phase_records"], ["scenario", "phase"])
    cleaned["summary_by_focus_market_type"] = _summarize(cleaned["phase_records"], ["focus_scenario", "market_type"])
    cleaned["summary_by_focus_competition_phase"] = _summarize(
        cleaned["phase_records"], ["focus_scenario", "competition_phase"]
    )
    cleaned["summary_by_slippage"] = _summarize(cleaned["phase_records"], ["pair_slippage_assumption"])
    cleaned["opportunity_windows"] = build_annual_opportunity_windows(cleaned["opportunities"])
    cleaned["portfolio_appendix"] = _proxy_portfolio_appendix(
        cleaned["opportunities"],
        matches,
        int(cleaned["parameters"]["trade_size"]),
        list(cleaned["parameters"]["pair_slippage_cases"]),
    )
    if out_json:
        write_json(out_json, cleaned)
    if out_md:
        target = Path(out_md)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_markdown(cleaned), encoding="utf-8")
    return cleaned


def _strict_title_equivalent_matches(
    matches: list[MatchedMarket],
) -> tuple[list[MatchedMarket], list[dict[str, str]]]:
    accepted = []
    rejected = []
    for match in matches:
        if match.relation == "official_structured_identity_exact_pair":
            kalshi_record = _kalshi_record(match.kalshi.raw)
            poly_record = _poly_record(match.polymarket.raw)
            reason = (
                _sports_contract_rejection(kalshi_record, poly_record)
                if kalshi_record
                and poly_record
                and (kalshi_record["identity"].is_sports or poly_record["identity"].is_sports)
                else None
            )
            if reason:
                rejected.append({"match_id": match.match_id, "reason": reason})
                continue
            accepted.append(match)
            continue
        reason = strict_market_rejection(match)
        if reason:
            rejected.append({"match_id": match.match_id, "reason": reason})
        else:
            accepted.append(match)
    return accepted, rejected


def _item_value(item, key: str):
    return item.get(key) if isinstance(item, dict) else getattr(item, key)


def _reclassified_phase(phase: str, domain: str) -> str:
    if phase.startswith("sports_") and not domain.startswith("sports_"):
        return "reclassified_non_sports_sample_window"
    return phase


def _window(match_id: str, direction: str, start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "direction": direction,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_seconds": (end - start).total_seconds(),
    }


def _finalize_annual_window(
    match_id: str,
    direction: str,
    phase: str,
    pair_slippage: float,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    best = max(items, key=lambda item: float(item["net_edge_per_contract"]))
    start = _parse_iso(items[0]["timestamp"])
    end = _parse_iso(items[-1]["timestamp"])
    return {
        "match_id": match_id,
        "direction": direction,
        "phase": phase,
        "pair_slippage_assumption": pair_slippage,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "duration_seconds": (end - start).total_seconds(),
        "profitable_snapshots": len(items),
        "best_timestamp": best["timestamp"],
        "best_net_edge_per_contract": best["net_edge_per_contract"],
        "best_gross_edge_per_contract": best["gross_edge_per_contract"],
        "best_roi_on_entry_cost": best["roi_on_entry_cost"],
        "polymarket_title": best["polymarket_title"],
        "kalshi_title": best["kalshi_title"],
        "yes_venue": best["yes_venue"],
        "no_venue": best["no_venue"],
        "yes_price": best["yes_price"],
        "no_price": best["no_price"],
        "pair_cost": best["total_cost"],
        "fees_total": best["total_fee"],
    }


def _focus_coverage_row(
    scenario: str,
    eligible_pairs: int,
    selected_pairs: int,
    records: list[dict[str, Any]],
    positive_match_ids: set[str],
    error_match_ids: set[str],
    kalshi_retained_catalog_rows: int,
    polymarket_retained_catalog_rows: int,
) -> dict[str, Any]:
    aligned_pairs = {item["match_id"] for item in records if item.get("aligned_points")}
    recorded_pairs = {item["match_id"] for item in records}
    errored_pairs = error_match_ids
    aligned_points = sum(int(item.get("aligned_points") or 0) for item in records)
    positive_windows = sum(int(item.get("net_positive_windows") or 0) for item in records)
    if eligible_pairs == 0:
        status = "no_strict_equivalent_cross_venue_pair_recovered"
    elif selected_pairs < eligible_pairs:
        status = "partially_scanned_due_configured_sampling_cap"
    elif not aligned_pairs:
        status = "strict_pairs_scanned_but_no_synchronized_price_snapshots_available"
    elif positive_match_ids:
        status = "profitable_price_proxy_window_found"
    elif errored_pairs:
        status = "scan_completed_with_api_errors_and_no_profitable_price_proxy_window_found"
    else:
        status = "fully_scanned_with_aligned_history_and_no_profitable_price_proxy_window_found"
    return {
        "focus_scenario": scenario,
        "kalshi_retained_catalog_rows": kalshi_retained_catalog_rows,
        "polymarket_retained_catalog_rows": polymarket_retained_catalog_rows,
        "eligible_strict_pairs": eligible_pairs,
        "selected_pairs": selected_pairs,
        "pairs_with_phase_records": len(recorded_pairs),
        "pairs_with_aligned_snapshots": len(aligned_pairs),
        "aligned_snapshots": aligned_points,
        "positive_pairs": len(positive_match_ids),
        "positive_windows": positive_windows,
        "pairs_with_api_errors": len(errored_pairs),
        "status": status,
    }


def _count_focus_matches(matches: list[MatchedMarket]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for match in matches:
        title = _scenario_text(match)
        counts[scenario_metadata(title, match.polymarket.category or match.kalshi.category)["focus_scenario"]] += 1
    return counts


def _phase_interval_seconds(phase: str) -> int:
    return {
        "sports_pregame_slow": 60 * 60,
        "sports_pregame_final_24h": 5 * 60,
        "sports_in_play": 60,
        "sports_event_start_unavailable_final_24h": 5 * 60,
        "lifecycle_more_than_30d": 24 * 60 * 60,
        "lifecycle_30d_to_24h": 60 * 60,
        "lifecycle_final_24h": 5 * 60,
        "reclassified_non_sports_sample_window": 5 * 60,
    }.get(phase, 60)


def _phase_checkpoint_key(
    match_id: str,
    phase: str,
    start: datetime,
    end: datetime,
    interval_minutes: int,
) -> str:
    raw = "|".join([match_id, phase, start.isoformat(), end.isoformat(), str(interval_minutes)])
    return sha1(raw.encode("utf-8")).hexdigest()


def _read_checkpoint(path: Path) -> dict[str, Any]:
    try:
        return read_json(path)
    except Exception:  # noqa: BLE001
        return {}


def _dict_item(item: Any) -> dict[str, Any]:
    return item if isinstance(item, dict) else asdict(item)


def _summarize(records: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[tuple(record[key] for key in keys)].append(record)
    out = []
    for values, items in grouped.items():
        medians = [item["median_net_window_seconds"] for item in items if item["median_net_window_seconds"] is not None]
        best_net = [item["best_net_edge_per_contract"] for item in items if item["best_net_edge_per_contract"] is not None]
        positive_edges = [
            item["mean_net_edge_on_positive_points"]
            for item in items
            if item["mean_net_edge_on_positive_points"] is not None
        ]
        aligned_points = sum(item["aligned_points"] for item in items)
        directions_tested = sum(item["proxy_directions_tested"] for item in items)
        net_points = sum(item["net_positive_points"] for item in items)
        row = {key: value for key, value in zip(keys, values)}
        row.update(
            {
                "phase_records": len(items),
                "markets": len({item["match_id"] for item in items}),
                "markets_with_aligned_points": len({item["match_id"] for item in items if item["aligned_points"]}),
                "markets_with_net_positive_points": len({item["match_id"] for item in items if item["net_positive_points"]}),
                "aligned_points": aligned_points,
                "proxy_directions_tested": directions_tested,
                "gross_positive_points": sum(item["gross_positive_points"] for item in items),
                "net_positive_points": net_points,
                "net_positive_direction_share": _ratio(net_points, directions_tested),
                "net_positive_windows": sum(item["net_positive_windows"] for item in items),
                "median_market_net_window_seconds": median(medians) if medians else None,
                "mean_market_net_edge_on_positive_points": mean(positive_edges) if positive_edges else None,
                "max_net_edge_per_contract": max(best_net) if best_net else None,
            }
        )
        out.append(row)
    return sorted(out, key=lambda item: tuple(str(item[key]) for key in keys))


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Official API Proxy Screen For Reachable Matches",
        "",
        result["parameters"]["note"],
        "",
        "## How To Read This Report",
        "",
        "- A `proxy signal` is a minute or hourly snapshot where official historical prices imply that buying opposite outcomes across the two exchanges cost less than `$1.00` after the configured fee and slippage assumptions.",
        "- A `net-positive window` is a consecutive run of proxy-signal snapshots. It is useful for comparing persistence, but it is not an observed fill.",
        "- `Mean net edge on positive points` is the average estimated profit per `$1.00` payout pair, considering only fee/slippage-positive snapshots.",
        "- `Signal share` divides fee/slippage-positive directions by all aligned cross-exchange directions tested. It measures frequency within the screened sample.",
        "- `reclassified_non_sports_sample_window` means an older sample was originally assigned sports-style timing because of an acronym collision, then relabeled after taxonomy cleanup. Retain it as a price observation, but do not interpret it as in-play sports evidence.",
        "- This report cannot measure order-book depth, queue position, or whether both legs would fill before prices move.",
        "",
        "## Coverage",
        "",
        f"- Conservative pairs discovered: `{result['parameters']['catalog_meta'].get('matched_pairs', 'n/a')}`",
        f"- Selected conservatively matched markets: `{result['parameters']['selected_markets']}`",
        f"- Proxy signals retained after default fees/slippage: `{len(result['opportunities'])}`",
        f"- API errors: `{len(result['errors'])}`",
        "",
        "## Monthly Summary",
        "",
        "| Month | Markets | Aligned points | Gross-positive points | Net-positive points | Net-positive windows | Max net edge |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["summary_by_month"]:
        lines.append(
            f"| {row['month']} | {row['markets']} | {row['aligned_points']} "
            f"| {row['gross_positive_points']} | {row['net_positive_points']} "
            f"| {row['net_positive_windows']} | {_fmt(row['max_net_edge_per_contract'])} |"
        )
    lines.extend(
        [
            "",
            "## Scenario Summary",
            "",
            "| Scenario | Markets | With aligned points | With net signals | Signal share | Net windows | Mean positive net edge | Max net edge |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(
        result["summary_by_scenario"],
        key=lambda item: (item["mean_market_net_edge_on_positive_points"] or -999, item["net_positive_windows"]),
        reverse=True,
    ):
        lines.append(
            f"| {row['scenario']} | {row['markets']} | {row['markets_with_aligned_points']} "
            f"| {row['markets_with_net_positive_points']} | {_pct(row['net_positive_direction_share'])} "
            f"| {row['net_positive_windows']} | {_fmt(row['mean_market_net_edge_on_positive_points'])} "
            f"| {_fmt(row['max_net_edge_per_contract'])} |"
        )
    focus_rows = {row["focus_scenario"]: row for row in result["summary_by_focus_scenario"]}
    focus_coverage = {row["focus_scenario"]: row for row in result["coverage_by_focus_scenario"]}
    lines.extend(
        [
            "",
            "## Focus Category Coverage",
            "",
            "| Focus category | Kalshi retained rows | Polymarket retained rows | Strict pairs | Scanned pairs | Pairs with aligned snapshots | Aligned snapshots | Net windows | Status |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for scenario in [*FOCUS_SCENARIOS, ADDITIONAL_DISCOVERED_SECTION]:
        row = focus_rows.get(scenario)
        coverage = focus_coverage[scenario]
        lines.append(
            f"| `{scenario}` | {coverage['kalshi_retained_catalog_rows']} "
            f"| {coverage['polymarket_retained_catalog_rows']} "
            f"| {coverage['eligible_strict_pairs']} | {coverage['selected_pairs']} "
            f"| {coverage['pairs_with_aligned_snapshots']} | {coverage['aligned_snapshots']} "
            f"| {(row or {}).get('net_positive_windows', 0)} | `{coverage['status']}` |"
        )
    lines.extend(
        [
            "",
        "## Scenario And Timing Summary",
            "",
            "| Scenario | Timing regime | Markets | Signal share | Net windows | Mean positive net edge | Median market window (s) |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result["summary_by_scenario_phase"]:
        lines.append(
            f"| {row['scenario']} | {row['phase']} | {row['markets']} "
            f"| {_pct(row['net_positive_direction_share'])} | {row['net_positive_windows']} "
            f"| {_fmt(row['mean_market_net_edge_on_positive_points'])} "
            f"| {_fmt(row['median_market_net_window_seconds'])} |"
        )
    lines.extend(
        [
            "",
            "## Conservative Pair-Slippage Sensitivity",
            "",
            "The official APIs do not expose historical Polymarket L2 depth. These annual values therefore use "
            "modeled total pair-slippage assumptions, not observed fills.",
            "",
            "| Pair slippage assumption | Markets | Net windows | Mean positive net edge | Max net edge |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result["summary_by_slippage"]:
        lines.append(
            f"| {_fmt(row['pair_slippage_assumption'])} | {row['markets']} "
            f"| {row['net_positive_windows']} | {_fmt(row['mean_market_net_edge_on_positive_points'])} "
            f"| {_fmt(row['max_net_edge_per_contract'])} |"
        )
    lines.extend(["", "## Top Proxy Signals", ""])
    for item in result["opportunities"][:20]:
        lines.extend(
            [
                f"### {item['polymarket_title']}",
                "",
                f"- Timestamp: `{item['timestamp']}`",
                f"- Kalshi: {item['kalshi_title']}",
                f"- Position: buy YES on `{item['yes_venue']}` at `{item['yes_price']:.6f}` and "
                f"buy NO on `{item['no_venue']}` at `{item['no_price']:.6f}`",
                f"- Total proxy entry cost: `{item['total_cost']:.6f}`",
                f"- Gross edge: `{item['gross_edge_per_contract']:.6f}`",
                f"- Estimated net edge: `{item['net_edge_per_contract']:.6f}`",
                f"- Estimated ROI on entry capital: `{item['roi_on_entry_cost']:.2%}`",
                f"- Modeled total pair slippage: `{item['pair_slippage_assumption']:.6f}`",
                f"- Phase: `{item['phase']}`",
                f"- Warning: {item['warning']}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## Modeled Portfolio Sensitivity",
            "",
            "These annual portfolio rows do not enforce historical displayed depth. They are modeled sensitivity estimates.",
            "",
            "| Pair slippage | Contracts | Accepted positions | Realized profit | Ending bankroll |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result["portfolio_appendix"]:
        lines.append(
            f"| {_fmt(row['pair_slippage_assumption'])} | {row['contracts']} "
            f"| {row['accepted_positions']} | {_fmt(row['realized_profit'])} | {_fmt(row['ending_bankroll'])} |"
        )
    return "\n".join(lines)


def _count_domains(matches: list[MatchedMarket]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for match in matches:
        title = _scenario_text(match)
        out[classify_domain(title, match.polymarket.category or match.kalshi.category)] += 1
    return dict(sorted(out.items()))


def _participant_or_team(match: MatchedMarket) -> str:
    raw = {**match.polymarket.raw, **match.kalshi.raw}
    return str(
        raw.get("groupItemTitle")
        or raw.get("yes_sub_title")
        or raw.get("event_ticker")
        or match.kalshi.title
    )


def _count_scenarios(matches: list[MatchedMarket]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for match in matches:
        title = _scenario_text(match)
        out[classify_scenario(title, match.polymarket.category or match.kalshi.category)] += 1
    return dict(sorted(out.items()))


def _match_date(match: MatchedMarket) -> datetime:
    value = match.kalshi.resolution_date or match.polymarket.resolution_date
    if not value:
        raise ValueError(f"Missing resolution date for {match.match_id}")
    return _parse_iso(value)


def _scenario_text(match: MatchedMarket) -> str:
    raw = {**match.polymarket.raw, **match.kalshi.raw}
    ticker = str(raw.get("event_ticker") or match.kalshi.slug or "")
    ticker_hints = " ".join(
        hint
        for prefix, hint in [
            ("KXPGA", "golf pga tour"),
            ("KXNBA", "nba basketball"),
            ("KXMLB", "mlb baseball"),
            ("KXNHL", "nhl hockey"),
            ("KXNFL", "nfl american football"),
            ("KXATP", "atp tennis"),
            ("KXWTA", "wta tennis"),
            ("KXUFC", "ufc mma"),
            ("KXMLS", "mls soccer"),
            ("KXF1", "f1 formula 1"),
        ]
        if ticker.upper().startswith(prefix)
    )
    return " ".join(
        str(value)
        for value in [
            match.polymarket.title,
            match.kalshi.title,
            match.polymarket.slug,
            match.kalshi.slug,
            raw.get("event_ticker"),
            ticker_hints,
        ]
        if value
    )


def _parse_iso(value: str) -> datetime:
    return _parse_catalog_iso(value)


def _parse_optional(value: str | None) -> datetime | None:
    return _parse_iso(value) if value else None


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.6f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
