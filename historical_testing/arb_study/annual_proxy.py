from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

from .models import MatchedMarket
from .official_api import KalshiOfficialClient, PolymarketOfficialClient
from .official_price_scanner import _align_official_series, _evaluate_proxy_state
from .scenario import classify_domain, classify_scenario
from .serde import write_json


def scan_annual_official_proxy(
    matches: list[MatchedMarket],
    start: str,
    end: str,
    out_json: str | Path,
    out_md: str | Path,
    max_markets_per_month: int = 12,
    workers: int = 6,
    trade_size: int = 100,
    slippage_buffer: float = 0.005,
    kalshi_fee_mode: str = "taker",
    polymarket_fallback_fee_rate: float = 0.05,
    catalog_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    selected, selection = _select_stratified(matches, start_dt, end_dt, max_markets_per_month)
    tasks = [
        (match, phase, window_start, window_end, interval)
        for match in selected
        for phase, window_start, window_end, interval in _phase_windows(match)
    ]
    phase_records = []
    opportunities = []
    errors = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(
                _scan_phase,
                match,
                phase,
                window_start,
                window_end,
                interval,
                trade_size,
                slippage_buffer,
                kalshi_fee_mode,
                polymarket_fallback_fee_rate,
            ): (match.match_id, phase)
            for match, phase, window_start, window_end, interval in tasks
        }
        for completed, future in enumerate(as_completed(future_map), start=1):
            match_id, phase = future_map[future]
            try:
                record, phase_opportunities = future.result()
                phase_records.append(record)
                opportunities.extend(phase_opportunities)
            except Exception as exc:  # noqa: BLE001
                errors.append({"match_id": match_id, "phase": phase, "error": str(exc)})
            if completed % 10 == 0 or completed == len(future_map):
                print(
                    f"Completed annual proxy phase scans {completed}/{len(future_map)}; "
                    f"errors={len(errors)}"
                )

    phase_records.sort(key=lambda item: (item["month"], item["domain"], item["phase"], item["match_id"]))
    opportunities.sort(key=lambda item: item.net_edge_per_contract, reverse=True)
    result = {
        "parameters": {
            "source": "official_api_price_history_proxy",
            "catalog_start": start_dt.isoformat(),
            "catalog_end": end_dt.isoformat(),
            "selected_markets": len(selected),
            "max_markets_per_month": max_markets_per_month,
            "trade_size": trade_size,
            "slippage_buffer": slippage_buffer,
            "catalog_meta": catalog_meta or {},
            "timing_windows": {
                "pre_event_proxy": "seven days before close through six hours before close, sampled hourly",
                "near_resolution_proxy": "six hours before close through one hour after close, sampled each minute",
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
        "summary_by_scenario_phase": _summarize(phase_records, ["scenario", "phase"]),
        "phase_records": phase_records,
        "opportunities": [asdict(item) for item in opportunities],
        "errors": errors,
    }
    write_json(out_json, result)
    target = Path(out_md)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_markdown(result), encoding="utf-8")
    return result


def _scan_phase(
    match: MatchedMarket,
    phase: str,
    start: datetime,
    end: datetime,
    interval_minutes: int,
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
    kalshi_rows = kalshi.market_candlesticks_auto(ticker, start_ts, end_ts, interval_minutes)
    poly_yes = poly.prices_history(match.polymarket.yes.outcome_id, start_ts, end_ts, interval_minutes)
    poly_no = poly.prices_history(match.polymarket.no.outcome_id, start_ts, end_ts, interval_minutes)
    bucket_seconds = interval_minutes * 60
    states = _align_official_series(kalshi_rows, poly_yes, poly_no, bucket_seconds=bucket_seconds)
    title = f"{match.polymarket.title} {match.kalshi.title}"
    domain = classify_domain(title, match.polymarket.category or match.kalshi.category)
    scenario = classify_scenario(title, match.polymarket.category or match.kalshi.category)
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
        )
        gross_positive += len(state_opps)
        opportunities.extend(item for item in state_opps if item.net_edge_per_contract > 0)
    windows = _proxy_windows([asdict(item) for item in opportunities], bucket_seconds)
    event_dt = _match_date(match)
    record = {
        "match_id": match.match_id,
        "month": event_dt.strftime("%Y-%m"),
        "domain": domain,
        "scenario": scenario,
        "phase": phase,
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
        "median_net_edge_on_positive_points": median(item.net_edge_per_contract for item in opportunities) if opportunities else None,
        "median_net_window_seconds": median([item["duration_seconds"] for item in windows]) if windows else None,
        "best_net_edge_per_contract": max((item.net_edge_per_contract for item in opportunities), default=None),
        "best_gross_edge_per_contract": max((item.gross_edge_per_contract for item in opportunities), default=None),
        "warning": match.resolution_date_warning,
    }
    return record, opportunities


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
        title = f"{match.polymarket.title} {match.kalshi.title}"
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


def _phase_windows(match: MatchedMarket):
    event_dt = _match_date(match)
    domain = classify_domain(
        f"{match.polymarket.title} {match.kalshi.title}",
        match.polymarket.category or match.kalshi.category,
    )
    near_label = "near_resolution_or_in_play_proxy" if domain.startswith("sports_") else "near_resolution_proxy"
    return [
        ("pre_event_proxy", event_dt - timedelta(days=7), event_dt - timedelta(hours=6), 60),
        (near_label, event_dt - timedelta(hours=6), event_dt + timedelta(hours=1), 1),
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


def _window(match_id: str, direction: str, start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "direction": direction,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_seconds": (end - start).total_seconds(),
    }


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
                f"- Phase: `{item['phase']}`",
                f"- Warning: {item['warning']}",
                "",
            ]
        )
    return "\n".join(lines)


def _count_domains(matches: list[MatchedMarket]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for match in matches:
        title = f"{match.polymarket.title} {match.kalshi.title}"
        out[classify_domain(title, match.polymarket.category or match.kalshi.category)] += 1
    return dict(sorted(out.items()))


def _count_scenarios(matches: list[MatchedMarket]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for match in matches:
        title = f"{match.polymarket.title} {match.kalshi.title}"
        out[classify_scenario(title, match.polymarket.category or match.kalshi.category)] += 1
    return dict(sorted(out.items()))


def _match_date(match: MatchedMarket) -> datetime:
    value = match.kalshi.resolution_date or match.polymarket.resolution_date
    if not value:
        raise ValueError(f"Missing resolution date for {match.match_id}")
    return _parse_iso(value)


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.6f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
