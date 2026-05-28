from __future__ import annotations

from dataclasses import asdict
from statistics import median
from typing import Any

from .archive import iter_hours
from .batch_bbo import load_kalshi_bbo_batch, load_polymarket_bbo_batch
from .bbo import load_kalshi_bbo, load_polymarket_bbo
from .fees import leg_fee
from .models import BBOState, MatchedMarket, Opportunity


def scan_matches(
    matches: list[MatchedMarket],
    start: str,
    end: str,
    trade_size: int = 100,
    slippage_buffer: float = 0.005,
    kalshi_fee_mode: str = "taker",
    polymarket_fallback_fee_rate: float = 0.05,
    max_markets: int | None = None,
    window_gap_seconds: float = 5.0,
) -> dict[str, Any]:
    selected = matches[:max_markets] if max_markets else matches
    summaries: list[dict[str, Any]] = []
    all_opportunities: list[Opportunity] = []
    errors: list[dict[str, str]] = []

    for match in selected:
        match_opps: list[Opportunity] = []
        states_seen = 0
        hours_scanned = 0
        for hour in iter_hours(start, end):
            hours_scanned += 1
            try:
                poly_states = load_polymarket_bbo(match, hour)
                kalshi_states = load_kalshi_bbo(match, hour)
                states_seen += min(len(poly_states), len(kalshi_states))
                match_opps.extend(
                    find_opportunities(
                        match,
                        poly_states,
                        kalshi_states,
                        trade_size=trade_size,
                        slippage_buffer=slippage_buffer,
                        kalshi_fee_mode=kalshi_fee_mode,
                        polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"match_id": match.match_id, "hour": hour, "error": str(exc)})

        summaries.append(
            _summarize_match(
                match,
                match_opps,
                states_seen,
                hours_scanned,
                window_gap_seconds=window_gap_seconds,
            )
        )
        all_opportunities.extend(match_opps)

    all_opportunities.sort(key=lambda item: item.net_edge_per_contract, reverse=True)
    all_net_windows = _opportunity_windows(
        [item for item in all_opportunities if item.net_edge_per_contract > 0],
        window_gap_seconds=window_gap_seconds,
    )
    return {
        "parameters": {
            "start": start,
            "end": end,
            "trade_size": trade_size,
            "slippage_buffer": slippage_buffer,
            "kalshi_fee_mode": kalshi_fee_mode,
            "polymarket_fallback_fee_rate": polymarket_fallback_fee_rate,
            "window_gap_seconds": window_gap_seconds,
            "markets_requested": len(matches),
            "markets_scanned": len(selected),
        },
        "summary": {
            "matched_markets_scanned": len(selected),
            "opportunity_ticks_gross_positive": sum(1 for o in all_opportunities if o.gross_edge_per_contract > 0),
            "opportunity_ticks_net_positive": sum(1 for o in all_opportunities if o.net_edge_per_contract > 0),
            "best_gross_edge_per_contract": max((o.gross_edge_per_contract for o in all_opportunities), default=None),
            "best_net_edge_per_contract": max((o.net_edge_per_contract for o in all_opportunities), default=None),
            "net_positive_windows": len(all_net_windows),
            "median_net_window_seconds": median([w["duration_seconds"] for w in all_net_windows])
            if all_net_windows
            else None,
        },
        "markets": summaries,
        "opportunities": [asdict(item) for item in all_opportunities],
        "errors": errors,
    }


def scan_matches_batch(
    matches: list[MatchedMarket],
    start: str,
    end: str,
    trade_size: int = 100,
    slippage_buffer: float = 0.005,
    kalshi_fee_mode: str = "taker",
    polymarket_fallback_fee_rate: float = 0.05,
    max_markets: int | None = None,
    window_gap_seconds: float = 5.0,
) -> dict[str, Any]:
    selected = matches[:max_markets] if max_markets else matches
    match_lookup = {match.match_id: match for match in selected}
    per_match_opps: dict[str, list[Opportunity]] = {match.match_id: [] for match in selected}
    per_match_states: dict[str, int] = {match.match_id: 0 for match in selected}
    hours = list(iter_hours(start, end))
    errors: list[dict[str, str]] = []

    for hour in hours:
        try:
            poly_by_match = load_polymarket_bbo_batch(selected, hour)
            kalshi_by_match = load_kalshi_bbo_batch(selected, hour)
        except Exception as exc:  # noqa: BLE001
            errors.append({"hour": hour, "error": str(exc)})
            continue

        matched_ids = set(poly_by_match) & set(kalshi_by_match)
        for match_id in matched_ids:
            poly_states = poly_by_match[match_id]
            kalshi_states = kalshi_by_match[match_id]
            per_match_states[match_id] += min(len(poly_states), len(kalshi_states))
            per_match_opps[match_id].extend(
                find_opportunities(
                    match_lookup[match_id],
                    poly_states,
                    kalshi_states,
                    trade_size=trade_size,
                    slippage_buffer=slippage_buffer,
                    kalshi_fee_mode=kalshi_fee_mode,
                    polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
                )
            )

    summaries = [
        _summarize_match(
            match,
            per_match_opps[match.match_id],
            per_match_states[match.match_id],
            len(hours),
            window_gap_seconds=window_gap_seconds,
        )
        for match in selected
    ]
    all_opportunities = [opp for opps in per_match_opps.values() for opp in opps]
    all_opportunities.sort(key=lambda item: item.net_edge_per_contract, reverse=True)
    gross_windows = _opportunity_windows(
        [item for item in all_opportunities if item.gross_edge_per_contract > 0],
        window_gap_seconds=window_gap_seconds,
    )
    net_windows = _opportunity_windows(
        [item for item in all_opportunities if item.net_edge_per_contract > 0],
        window_gap_seconds=window_gap_seconds,
    )

    return {
        "parameters": {
            "start": start,
            "end": end,
            "trade_size": trade_size,
            "slippage_buffer": slippage_buffer,
            "kalshi_fee_mode": kalshi_fee_mode,
            "polymarket_fallback_fee_rate": polymarket_fallback_fee_rate,
            "window_gap_seconds": window_gap_seconds,
            "markets_requested": len(matches),
            "markets_scanned": len(selected),
            "hours_scanned": len(hours),
            "scanner": "batch",
        },
        "summary": {
            "matched_markets_scanned": len(selected),
            "hours_scanned": len(hours),
            "opportunity_ticks_gross_positive": sum(1 for o in all_opportunities if o.gross_edge_per_contract > 0),
            "opportunity_ticks_net_positive": sum(1 for o in all_opportunities if o.net_edge_per_contract > 0),
            "gross_positive_windows": len(gross_windows),
            "net_positive_windows": len(net_windows),
            "median_gross_window_seconds": median([w["duration_seconds"] for w in gross_windows])
            if gross_windows
            else None,
            "median_net_window_seconds": median([w["duration_seconds"] for w in net_windows])
            if net_windows
            else None,
            "best_gross_edge_per_contract": max((o.gross_edge_per_contract for o in all_opportunities), default=None),
            "best_net_edge_per_contract": max((o.net_edge_per_contract for o in all_opportunities), default=None),
        },
        "markets": summaries,
        "opportunity_windows": {
            "gross": gross_windows,
            "net": net_windows,
        },
        "opportunities": [asdict(item) for item in all_opportunities],
        "errors": errors,
    }


def find_opportunities(
    match: MatchedMarket,
    poly_states: list[BBOState],
    kalshi_states: list[BBOState],
    trade_size: int,
    slippage_buffer: float,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
) -> list[Opportunity]:
    if not poly_states or not kalshi_states:
        return []

    opportunities: list[Opportunity] = []
    kalshi_index = 0
    current_kalshi: BBOState | None = None
    for poly in poly_states:
        while kalshi_index < len(kalshi_states) and kalshi_states[kalshi_index].timestamp <= poly.timestamp:
            current_kalshi = kalshi_states[kalshi_index]
            kalshi_index += 1
        if current_kalshi is None:
            continue

        opportunities.extend(
            _evaluate_state(
                match=match,
                timestamp=poly.timestamp.isoformat(),
                poly=poly,
                kalshi=current_kalshi,
                trade_size=trade_size,
                slippage_buffer=slippage_buffer,
                kalshi_fee_mode=kalshi_fee_mode,
                polymarket_fallback_fee_rate=polymarket_fallback_fee_rate,
            )
        )
    return opportunities


def _evaluate_state(
    match: MatchedMarket,
    timestamp: str,
    poly: BBOState,
    kalshi: BBOState,
    trade_size: int,
    slippage_buffer: float,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
) -> list[Opportunity]:
    directions = [
        (
            "poly_yes__kalshi_no",
            "polymarket",
            "kalshi",
            poly.yes_ask,
            kalshi.no_ask,
            poly.yes_ask_size,
            kalshi.no_ask_size,
        ),
        (
            "kalshi_yes__poly_no",
            "kalshi",
            "polymarket",
            kalshi.yes_ask,
            poly.no_ask,
            kalshi.yes_ask_size,
            poly.no_ask_size,
        ),
    ]
    result: list[Opportunity] = []
    for direction, yes_venue, no_venue, yes_ask, no_ask, yes_size, no_size in directions:
        if yes_ask is None or no_ask is None:
            continue
        depth = _depth_limit(yes_size, no_size)
        if depth is None or depth <= 0:
            continue

        gross_edge = 1.0 - (yes_ask + no_ask)
        yes_fee = leg_fee(
            yes_venue,
            yes_ask,
            trade_size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        )
        no_fee = leg_fee(
            no_venue,
            no_ask,
            trade_size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        )
        total_fee = yes_fee + no_fee
        slippage_cost = slippage_buffer * 2
        net_edge = gross_edge - (total_fee / trade_size) - slippage_cost
        if gross_edge <= 0 and net_edge <= 0:
            continue

        partial_fill_exposure = abs(yes_ask - (1.0 - no_ask))
        result.append(
            Opportunity(
                match_id=match.match_id,
                timestamp=timestamp,
                direction=direction,
                yes_venue=yes_venue,
                no_venue=no_venue,
                yes_ask=yes_ask,
                no_ask=no_ask,
                gross_edge_per_contract=gross_edge,
                net_edge_per_contract=net_edge,
                total_fee=total_fee,
                slippage_cost_per_contract=slippage_cost,
                trade_size=trade_size,
                estimated_partial_fill_exposure=partial_fill_exposure,
                depth_limited_contracts=depth,
            )
        )
    return result


def _depth_limit(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return min(left, right)


def _summarize_match(
    match: MatchedMarket,
    opportunities: list[Opportunity],
    states_seen: int,
    hours_scanned: int,
    window_gap_seconds: float,
) -> dict[str, Any]:
    net_positive = [o for o in opportunities if o.net_edge_per_contract > 0]
    gross_positive = [o for o in opportunities if o.gross_edge_per_contract > 0]
    gross_windows = _opportunity_windows(gross_positive, window_gap_seconds=window_gap_seconds)
    net_windows = _opportunity_windows(net_positive, window_gap_seconds=window_gap_seconds)
    return {
        "match_id": match.match_id,
        "polymarket_title": match.polymarket.title,
        "kalshi_title": match.kalshi.title,
        "confidence": match.confidence,
        "resolution_date_warning": match.resolution_date_warning,
        "hours_scanned": hours_scanned,
        "aligned_state_count_estimate": states_seen,
        "gross_positive_ticks": len(gross_positive),
        "net_positive_ticks": len(net_positive),
        "gross_positive_windows": len(gross_windows),
        "net_positive_windows": len(net_windows),
        "median_gross_window_seconds": median([w["duration_seconds"] for w in gross_windows])
        if gross_windows
        else None,
        "median_net_window_seconds": median([w["duration_seconds"] for w in net_windows])
        if net_windows
        else None,
        "best_gross_edge_per_contract": max((o.gross_edge_per_contract for o in opportunities), default=None),
        "best_net_edge_per_contract": max((o.net_edge_per_contract for o in opportunities), default=None),
        "median_partial_fill_exposure": median([o.estimated_partial_fill_exposure for o in opportunities])
        if opportunities
        else None,
    }


def _opportunity_windows(
    opportunities: list[Opportunity],
    window_gap_seconds: float,
) -> list[dict[str, Any]]:
    if not opportunities:
        return []

    sorted_opps = sorted(
        opportunities,
        key=lambda item: (item.match_id, item.direction, item.timestamp),
    )
    windows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for opp in sorted_opps:
        ts = _parse_iso_timestamp(opp.timestamp)
        key = (opp.match_id, opp.direction)
        if (
            current is None
            or current["key"] != key
            or (ts - current["last_ts"]).total_seconds() > window_gap_seconds
        ):
            if current is not None:
                windows.append(_finalize_window(current))
            current = {
                "key": key,
                "match_id": opp.match_id,
                "direction": opp.direction,
                "start_ts": ts,
                "last_ts": ts,
                "ticks": 1,
                "best_net_edge_per_contract": opp.net_edge_per_contract,
                "best_gross_edge_per_contract": opp.gross_edge_per_contract,
            }
            continue

        current["last_ts"] = ts
        current["ticks"] += 1
        current["best_net_edge_per_contract"] = max(
            current["best_net_edge_per_contract"],
            opp.net_edge_per_contract,
        )
        current["best_gross_edge_per_contract"] = max(
            current["best_gross_edge_per_contract"],
            opp.gross_edge_per_contract,
        )

    if current is not None:
        windows.append(_finalize_window(current))
    return windows


def _parse_iso_timestamp(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _finalize_window(window: dict[str, Any]) -> dict[str, Any]:
    duration = (window["last_ts"] - window["start_ts"]).total_seconds()
    return {
        "match_id": window["match_id"],
        "direction": window["direction"],
        "start": window["start_ts"].isoformat(),
        "end": window["last_ts"].isoformat(),
        "duration_seconds": duration,
        "ticks": window["ticks"],
        "best_net_edge_per_contract": window["best_net_edge_per_contract"],
        "best_gross_edge_per_contract": window["best_gross_edge_per_contract"],
    }
