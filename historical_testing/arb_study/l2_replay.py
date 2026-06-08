from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from .batch_bbo import load_kalshi_bbo_batch, load_polymarket_bbo_batch
from .fees import leg_fee
from .l2_analysis import locked_pair_metrics, sweep_book
from .models import BBOState, MatchedMarket
from .research_config import LATENCY_BUCKETS_SECONDS, ORDER_SIZE_LADDER, PAIRED_EXIT_MINIMUM_IMPROVEMENT
from .portfolio import simulate_portfolio
from .scenario import classify_lifecycle_phase, scenario_metadata
from .serde import read_json, write_json


def run_resumable_l2_replay(
    matches: list[MatchedMarket],
    hours: list[str],
    checkpoint_dir: str | Path,
    *,
    resume: bool = True,
    max_hours: int | None = None,
    order_sizes: list[int] | None = None,
    window_gap_seconds: float = 5.0,
    kalshi_fee_mode: str = "taker",
    polymarket_fallback_fee_rate: float = 0.05,
) -> dict[str, Any]:
    target = Path(checkpoint_dir)
    target.mkdir(parents=True, exist_ok=True)
    selected_hours = hours[:max_hours] if max_hours else hours
    hour_results = []
    for position, hour in enumerate(selected_hours, start=1):
        checkpoint = target / f"{hour}.json"
        result = read_json(checkpoint) if resume and checkpoint.exists() else None
        if result is None or result.get("error"):
            try:
                result = scan_l2_hour(
                    matches,
                    hour,
                    order_sizes=order_sizes,
                    window_gap_seconds=window_gap_seconds,
                    kalshi_fee_mode=kalshi_fee_mode,
                    polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
                )
            except Exception as exc:  # noqa: BLE001
                result = {
                    "hour": hour,
                    "error": str(exc),
                    "summary": {"aligned_points": 0, "net_positive_windows": 0},
                    "windows": [],
                    "exit_candidates": [],
                }
            write_json(checkpoint, result)
        hour_results.append(result)
        print(f"Checkpointed PMXT L2 replay {position}/{len(selected_hours)}: {hour}", flush=True)
    return aggregate_l2_checkpoints(hour_results, selected_hours, matches)


def scan_l2_hour(
    matches: list[MatchedMarket],
    hour: str,
    *,
    order_sizes: list[int] | None = None,
    window_gap_seconds: float = 5.0,
    kalshi_fee_mode: str = "taker",
    polymarket_fallback_fee_rate: float = 0.05,
) -> dict[str, Any]:
    sizes = order_sizes or ORDER_SIZE_LADDER
    poly_by_match = load_polymarket_bbo_batch(matches, hour)
    kalshi_by_match = load_kalshi_bbo_batch(matches, hour)
    records: list[dict[str, Any]] = []
    exit_candidates: list[dict[str, Any]] = []
    aligned_points = 0
    for match in matches:
        aligned = align_states(poly_by_match.get(match.match_id, []), kalshi_by_match.get(match.match_id, []))
        aligned_points += len(aligned)
        exit_candidates.extend(
            _exit_candidates(
                match,
                aligned,
                sizes,
                kalshi_fee_mode=kalshi_fee_mode,
                polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
            )
        )
        records.extend(
            evaluate_aligned_states(
                match,
                aligned,
                sizes,
                window_gap_seconds=window_gap_seconds,
                kalshi_fee_mode=kalshi_fee_mode,
                polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
            )
        )
    records.sort(key=lambda item: item["best_net_edge_per_contract"], reverse=True)
    return {
        "hour": hour,
        "parameters": {
            "order_sizes": sizes,
            "window_gap_seconds": window_gap_seconds,
            "paired_exit_minimum_improvement": PAIRED_EXIT_MINIMUM_IMPROVEMENT,
            "fee_assumption": (
                "Kalshi uses the configured maker/taker model. Polymarket uses the configured "
                "fallback rate when archive rows do not expose a usable fee rate."
            ),
        },
        "summary": _summarize_windows(records, aligned_points),
        "windows": records,
        "exit_candidates": exit_candidates,
        "examples": records[:50],
    }


def align_states(poly_states: list[BBOState], kalshi_states: list[BBOState]) -> list[tuple[BBOState, BBOState]]:
    aligned: list[tuple[BBOState, BBOState]] = []
    kalshi_index = 0
    current_kalshi: BBOState | None = None
    for poly in poly_states:
        while kalshi_index < len(kalshi_states) and kalshi_states[kalshi_index].timestamp <= poly.timestamp:
            current_kalshi = kalshi_states[kalshi_index]
            kalshi_index += 1
        if current_kalshi is not None:
            aligned.append((poly, current_kalshi))
    return aligned


def evaluate_aligned_states(
    match: MatchedMarket,
    aligned: list[tuple[BBOState, BBOState]],
    order_sizes: list[int],
    *,
    window_gap_seconds: float,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
) -> list[dict[str, Any]]:
    ticks: list[dict[str, Any]] = []
    for index, (poly, kalshi) in enumerate(aligned):
        for size in order_sizes:
            ticks.extend(
                _evaluate_state(
                    match,
                    index,
                    poly,
                    kalshi,
                    size,
                    kalshi_fee_mode=kalshi_fee_mode,
                    polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
                )
            )
    windows = _opportunity_windows(ticks, window_gap_seconds)
    for window in windows:
        exit_result = _safe_paired_exit(
            window,
            aligned,
            kalshi_fee_mode=kalshi_fee_mode,
            polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
        )
        window.update(exit_result)
        window.pop("_entry_index", None)
    return windows


def _evaluate_state(
    match: MatchedMarket,
    index: int,
    poly: BBOState,
    kalshi: BBOState,
    size: int,
    *,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
) -> list[dict[str, Any]]:
    directions = [
        ("poly_yes__kalshi_no", "polymarket", "kalshi", poly, "yes", kalshi, "no"),
        ("kalshi_yes__poly_no", "kalshi", "polymarket", kalshi, "yes", poly, "no"),
    ]
    out = []
    for direction, yes_venue, no_venue, yes_state, yes_side, no_state, no_side in directions:
        yes_asks = _levels(yes_state, yes_side, "asks")
        no_asks = _levels(no_state, no_side, "asks")
        yes_sweep = sweep_book(yes_asks, size)
        no_sweep = sweep_book(no_asks, size)
        if not yes_sweep.fully_filled or not no_sweep.fully_filled:
            continue
        yes_fee = leg_fee(
            yes_venue,
            float(yes_sweep.vwap),
            size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fee_rate=_fee_rate_for_leg(yes_venue, yes_state),
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        )
        no_fee = leg_fee(
            no_venue,
            float(no_sweep.vwap),
            size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fee_rate=_fee_rate_for_leg(no_venue, no_state),
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        )
        metrics = locked_pair_metrics(yes_asks, no_asks, size, total_fee=yes_fee + no_fee)
        if metrics.net_edge_per_contract is None or metrics.net_edge_per_contract <= 0:
            continue
        top_depth = min(_top_level_depth(yes_asks), _top_level_depth(no_asks))
        paired_capacity = min(_book_capacity(yes_asks), _book_capacity(no_asks))
        out.append(
            {
                "match_id": match.match_id,
                "polymarket_title": match.polymarket.title,
                "kalshi_title": match.kalshi.title,
                "timestamp": poly.timestamp.isoformat(),
                "direction": direction,
                "yes_venue": yes_venue,
                "no_venue": no_venue,
                "size_contracts": size,
                "entry_cost_per_contract": metrics.total_entry_cost_per_contract,
                "gross_edge_per_contract": metrics.gross_edge_per_contract,
                "net_edge_per_contract": metrics.net_edge_per_contract,
                "roi_on_entry_cost": metrics.net_edge_per_contract
                / (float(metrics.total_entry_cost_per_contract) + (float(metrics.total_fee) / size)),
                "entry_fee_total": metrics.total_fee,
                "polymarket_fee_rate": _fee_rate_for_leg(
                    "polymarket",
                    yes_state if yes_venue == "polymarket" else no_state,
                ),
                "polymarket_fee_source": (
                    "archive_fee_rate_bps"
                    if _fee_rate_for_leg(
                        "polymarket",
                        yes_state if yes_venue == "polymarket" else no_state,
                    )
                    is not None
                    else "documented_conservative_fallback"
                ),
                "yes_vwap": yes_sweep.vwap,
                "no_vwap": no_sweep.vwap,
                "yes_top_ask": yes_sweep.top_price,
                "no_top_ask": no_sweep.top_price,
                "book_slippage_per_contract": (
                    float(yes_sweep.book_slippage_per_contract or 0)
                    + float(no_sweep.book_slippage_per_contract or 0)
                ),
                "top_of_book_depth_contracts": top_depth,
                "paired_capacity_contracts": paired_capacity,
                "one_leg_partial_fill_exposure_contracts": size,
                "_entry_index": index,
            }
        )
    return out


def _opportunity_windows(ticks: list[dict[str, Any]], gap_seconds: float) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for tick in ticks:
        grouped[(tick["match_id"], tick["direction"], tick["size_contracts"])].append(tick)
    windows: list[dict[str, Any]] = []
    for items in grouped.values():
        items.sort(key=lambda item: item["timestamp"])
        current = _new_window(items[0])
        for item in items[1:]:
            timestamp = _parse(item["timestamp"])
            if (timestamp - current["_last_ts"]).total_seconds() > gap_seconds:
                windows.append(_finish_window(current))
                current = _new_window(item)
                continue
            current["_last_ts"] = timestamp
            current["end"] = item["timestamp"]
            current["ticks"] += 1
            current["best_net_edge_per_contract"] = max(current["best_net_edge_per_contract"], item["net_edge_per_contract"])
            current["best_gross_edge_per_contract"] = max(current["best_gross_edge_per_contract"], item["gross_edge_per_contract"])
            current["best_roi_on_entry_cost"] = max(current["best_roi_on_entry_cost"], item["roi_on_entry_cost"])
            current["max_top_of_book_depth_contracts"] = max(
                current["max_top_of_book_depth_contracts"],
                item["top_of_book_depth_contracts"],
            )
            current["max_paired_capacity_contracts"] = max(
                current["max_paired_capacity_contracts"],
                item["paired_capacity_contracts"],
            )
        windows.append(_finish_window(current))
    return windows


def _new_window(item: dict[str, Any]) -> dict[str, Any]:
    timestamp = _parse(item["timestamp"])
    return {
        **item,
        "start": item["timestamp"],
        "end": item["timestamp"],
        "ticks": 1,
        "best_net_edge_per_contract": item["net_edge_per_contract"],
        "locked_hold_profit_per_contract": item["net_edge_per_contract"],
        "best_gross_edge_per_contract": item["gross_edge_per_contract"],
        "best_roi_on_entry_cost": item["roi_on_entry_cost"],
        "max_top_of_book_depth_contracts": item["top_of_book_depth_contracts"],
        "max_paired_capacity_contracts": item["paired_capacity_contracts"],
        "_start_ts": timestamp,
        "_last_ts": timestamp,
    }


def _finish_window(window: dict[str, Any]) -> dict[str, Any]:
    duration = (window["_last_ts"] - window["_start_ts"]).total_seconds()
    out = {
        key: value
        for key, value in window.items()
        if key not in {"_start_ts", "_last_ts", "timestamp", "net_edge_per_contract", "gross_edge_per_contract"}
    }
    out["duration_seconds"] = duration
    out["latency_coverage"] = {str(bucket): duration >= bucket for bucket in LATENCY_BUCKETS_SECONDS}
    return out


def _safe_paired_exit(
    window: dict[str, Any],
    aligned: list[tuple[BBOState, BBOState]],
    *,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
) -> dict[str, Any]:
    size = int(window["size_contracts"])
    for poly, kalshi in aligned[int(window["_entry_index"]) + 1 :]:
        if poly.timestamp <= _parse(window["start"]):
            continue
        yes_state = poly if window["yes_venue"] == "polymarket" else kalshi
        no_state = poly if window["no_venue"] == "polymarket" else kalshi
        yes_exit = sweep_book(_levels(yes_state, "yes", "bids"), size, is_bid=True)
        no_exit = sweep_book(_levels(no_state, "no", "bids"), size, is_bid=True)
        if not yes_exit.fully_filled or not no_exit.fully_filled:
            continue
        exit_fee = leg_fee(
            window["yes_venue"],
            float(yes_exit.vwap),
            size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fee_rate=_fee_rate_for_leg(window["yes_venue"], yes_state),
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        ) + leg_fee(
            window["no_venue"],
            float(no_exit.vwap),
            size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fee_rate=_fee_rate_for_leg(window["no_venue"], no_state),
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        )
        early_profit = (
            float(yes_exit.vwap)
            + float(no_exit.vwap)
            - float(window["entry_cost_per_contract"])
            - (float(window["entry_fee_total"]) / size)
            - (exit_fee / size)
        )
        improvement = early_profit - float(window["locked_hold_profit_per_contract"])
        if improvement + 1e-12 >= PAIRED_EXIT_MINIMUM_IMPROVEMENT:
            return {
                "paired_exit_qualifies": True,
                "paired_exit_at": poly.timestamp.isoformat(),
                "paired_exit_net_profit_per_contract": early_profit,
                "paired_exit_improvement_per_contract": improvement,
                "paired_exit_seconds": (poly.timestamp - _parse(window["start"])).total_seconds(),
            }
    return {
        "paired_exit_qualifies": False,
        "paired_exit_at": None,
        "paired_exit_net_profit_per_contract": None,
        "paired_exit_improvement_per_contract": None,
        "paired_exit_seconds": None,
    }


def _levels(state: BBOState, side: str, book_side: str) -> tuple[tuple[float, float], ...]:
    levels = getattr(state, f"{side}_{book_side}")
    if levels:
        return levels
    price = getattr(state, f"{side}_{'bid' if book_side == 'bids' else 'ask'}")
    size = getattr(state, f"{side}_{'bid_size' if book_side == 'bids' else 'ask_size'}")
    return ((float(price), float(size)),) if price is not None and size is not None else ()


def _fee_rate_for_leg(venue: str, state: BBOState) -> float | None:
    return state.polymarket_fee_rate if venue == "polymarket" else None


def _top_level_depth(levels: tuple[tuple[float, float], ...]) -> float:
    return min(levels, key=lambda item: item[0])[1]


def _book_capacity(levels: tuple[tuple[float, float], ...]) -> float:
    return sum(size for _, size in levels if size > 0)


def _exit_candidates(
    match: MatchedMarket,
    aligned: list[tuple[BBOState, BBOState]],
    sizes: list[int],
    *,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
) -> list[dict[str, Any]]:
    rows = []
    directions = [
        ("poly_yes__kalshi_no", "polymarket", "kalshi"),
        ("kalshi_yes__poly_no", "kalshi", "polymarket"),
    ]
    for poly, kalshi in aligned:
        for size in sizes:
            for direction, yes_venue, no_venue in directions:
                yes_state = poly if yes_venue == "polymarket" else kalshi
                no_state = poly if no_venue == "polymarket" else kalshi
                yes_exit = sweep_book(_levels(yes_state, "yes", "bids"), size, is_bid=True)
                no_exit = sweep_book(_levels(no_state, "no", "bids"), size, is_bid=True)
                if not yes_exit.fully_filled or not no_exit.fully_filled:
                    continue
                exit_fee = leg_fee(
                    yes_venue,
                    float(yes_exit.vwap),
                    size,
                    kalshi_mode=kalshi_fee_mode,
                    polymarket_fee_rate=_fee_rate_for_leg(yes_venue, yes_state),
                    polymarket_fallback_rate=polymarket_fallback_fee_rate,
                ) + leg_fee(
                    no_venue,
                    float(no_exit.vwap),
                    size,
                    kalshi_mode=kalshi_fee_mode,
                    polymarket_fee_rate=_fee_rate_for_leg(no_venue, no_state),
                    polymarket_fallback_rate=polymarket_fallback_fee_rate,
                )
                rows.append(
                    {
                        "match_id": match.match_id,
                        "timestamp": poly.timestamp.isoformat(),
                        "direction": direction,
                        "size_contracts": size,
                        "proceeds_per_contract": float(yes_exit.vwap) + float(no_exit.vwap),
                        "exit_fee_total": exit_fee,
                    }
                )
    return rows


def aggregate_l2_checkpoints(
    results: list[dict[str, Any]],
    hours: list[str],
    matches: list[MatchedMarket],
) -> dict[str, Any]:
    match_by_id = {match.match_id: match for match in matches}
    windows = [
        _enrich_window(window, match_by_id.get(window["match_id"]))
        for result in results
        for window in result.get("windows", [])
    ]
    exit_candidates = [
        item
        for result in results
        for item in result.get("exit_candidates", [])
    ]
    _apply_cross_hour_exits(windows, exit_candidates)
    examples = sorted(
        windows,
        key=lambda item: (
            int(item["size_contracts"]) == 100,
            item["best_net_edge_per_contract"],
        ),
        reverse=True,
    )[:200]
    return {
        "parameters": {
            "source": "pmxt_public_parquet_l2_replay",
            "hours_requested": len(hours),
            "hours_completed": len(results),
            "hour_errors": sum(bool(result.get("error")) for result in results),
            "matches_requested": len(matches),
            "order_sizes": ORDER_SIZE_LADDER,
            "paired_exit_minimum_improvement": PAIRED_EXIT_MINIMUM_IMPROVEMENT,
            "paired_exit_search_scope": "all_completed_pmxt_hour_checkpoints",
            "fallback_assumptions": [
                "Kalshi fees use the configured documented maker/taker model.",
                "Polymarket archive fee_rate_bps is used when present; otherwise the configured conservative fallback is recorded.",
            ],
        },
        "summary": _summarize_windows(windows, sum(result.get("summary", {}).get("aligned_points", 0) for result in results)),
        "summary_by_focus_scenario": _summarize_by(windows, "focus_scenario"),
        "summary_by_market_type": _summarize_by(windows, "market_type"),
        "summary_by_competition_phase": _summarize_by(windows, "competition_phase"),
        "summary_by_timing_phase": _summarize_by(windows, "timing_phase"),
        "summary_by_order_size": _summarize_by(windows, "size_contracts"),
        "portfolio_appendix": _l2_portfolio_appendix(windows),
        "windows": windows,
        "examples": examples,
    }


def _apply_cross_hour_exits(
    windows: list[dict[str, Any]],
    exit_candidates: list[dict[str, Any]],
) -> None:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for item in exit_candidates:
        grouped[(item["match_id"], item["direction"], int(item["size_contracts"]))].append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item["timestamp"])
    for window in windows:
        items = grouped.get((window["match_id"], window["direction"], int(window["size_contracts"])), [])
        for item in items:
            if _parse(item["timestamp"]) <= _parse(window["start"]):
                continue
            early_profit = (
                float(item["proceeds_per_contract"])
                - float(window["entry_cost_per_contract"])
                - (float(window["entry_fee_total"]) / int(window["size_contracts"]))
                - (float(item["exit_fee_total"]) / int(window["size_contracts"]))
            )
            improvement = early_profit - float(window["locked_hold_profit_per_contract"])
            if improvement + 1e-12 < PAIRED_EXIT_MINIMUM_IMPROVEMENT:
                continue
            window.update(
                {
                    "paired_exit_qualifies": True,
                    "paired_exit_at": item["timestamp"],
                    "paired_exit_net_profit_per_contract": early_profit,
                    "paired_exit_improvement_per_contract": improvement,
                    "paired_exit_seconds": (
                        _parse(item["timestamp"]) - _parse(window["start"])
                    ).total_seconds(),
                }
            )
            break


def _summarize_windows(windows: list[dict[str, Any]], aligned_points: int) -> dict[str, Any]:
    durations = [float(item["duration_seconds"]) for item in windows]
    return {
        "aligned_points": aligned_points,
        "net_positive_windows": len(windows),
        "markets_with_windows": len({item["match_id"] for item in windows}),
        "median_window_seconds": median(durations) if durations else None,
        "best_net_edge_per_contract": max((item["best_net_edge_per_contract"] for item in windows), default=None),
        "paired_exit_windows": sum(bool(item.get("paired_exit_qualifies")) for item in windows),
        "polymarket_fee_fallback_windows": sum(
            item.get("polymarket_fee_source") == "documented_conservative_fallback"
            for item in windows
        ),
        "latency_buckets": {
            str(bucket): sum(float(item["duration_seconds"]) >= bucket for item in windows)
            for bucket in LATENCY_BUCKETS_SECONDS
        },
    }


def _enrich_window(window: dict[str, Any], match: MatchedMarket | None) -> dict[str, Any]:
    if match is None:
        return {**window, "settlement_at": window["end"]}
    title = f"{match.polymarket.title} {match.kalshi.title}"
    raw = {**match.polymarket.raw, **match.kalshi.raw}
    resolution = _parse_optional(match.polymarket.resolution_date or match.kalshi.resolution_date)
    event_start = _parse_optional(raw.get("gameStartTime") or raw.get("start_time") or raw.get("event_start"))
    metadata = scenario_metadata(title, match.polymarket.category or match.kalshi.category)
    return {
        **window,
        **metadata,
        "timing_phase": classify_lifecycle_phase(
            _parse(window["start"]),
            resolution,
            is_sports=metadata["domain"].startswith("sports_"),
            event_start=event_start,
        ),
        "participant_or_team": str(
            raw.get("groupItemTitle")
            or raw.get("yes_sub_title")
            or raw.get("event_ticker")
            or match.kalshi.title
        ),
        "settlement_at": match.polymarket.resolution_date or match.kalshi.resolution_date or window["end"],
    }


def _l2_portfolio_appendix(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for contracts in ORDER_SIZE_LADDER:
        rows = [
            {
                **item,
                "net_profit_per_contract": (
                    item["paired_exit_net_profit_per_contract"]
                    if item.get("paired_exit_qualifies")
                    else item["locked_hold_profit_per_contract"]
                ),
                "depth_contracts": item["max_top_of_book_depth_contracts"],
            }
            for item in windows
            if int(item["size_contracts"]) == contracts
        ]
        result = simulate_portfolio(rows, contracts=contracts, enforce_depth=True)
        cases.append(
            {
                "contracts": contracts,
                "evidence_label": "pmxt_archived_l2_capacity_enforced",
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


def _summarize_by(windows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in windows:
        grouped[str(item.get(key) or "unspecified")].append(item)
    return [
        {
            key: value,
            "windows": len(items),
            "markets": len({item["match_id"] for item in items}),
            "median_window_seconds": median(float(item["duration_seconds"]) for item in items),
            "max_net_edge_per_contract": max(float(item["best_net_edge_per_contract"]) for item in items),
        }
        for value, items in sorted(grouped.items())
    ]


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_optional(value: str | None) -> datetime | None:
    return _parse(value) if value else None
