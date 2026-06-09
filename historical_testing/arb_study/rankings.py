from __future__ import annotations

from collections import defaultdict
from typing import Any

from .portfolio import simulate_capped_portfolio


HEADLINE_SLIPPAGE = 0.02


def build_leaderboards(
    annual_result: dict[str, Any] | None,
    l2_result: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    annual_rows = _annual_rows(annual_result or {})
    l2_rows = _l2_rows(l2_result or {})
    return {
        "category_leaderboard": _rank(annual_rows, l2_rows, "focus_scenario"),
        "subscenario_leaderboard": _rank(annual_rows, l2_rows, "subscenario"),
    }


def _annual_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    phase_by_match: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in result.get("phase_records") or []:
        phase_by_match[record["match_id"]].append(record)
    rows = []
    for item in result.get("opportunities") or []:
        if abs(float(item.get("pair_slippage_assumption") or 0) - HEADLINE_SLIPPAGE) > 1e-9:
            continue
        metadata = _metadata(item)
        records = phase_by_match.get(item["match_id"], [])
        settlement = max(
            (record.get("window_end") for record in records if record.get("window_end")),
            default=item["timestamp"],
        )
        rows.append(
            {
                **metadata,
                "match_id": item["match_id"],
                "start": item["timestamp"],
                "settlement_at": settlement,
                "entry_cost_per_contract": (
                    float(item["total_cost"])
                    + float(item["total_fee"]) / float(result.get("parameters", {}).get("trade_size") or 100)
                    + HEADLINE_SLIPPAGE
                ),
                "net_profit_per_contract": float(item["net_edge_per_contract"]),
                "evidence_label": "annual_2_cent_price_history_proxy",
            }
        )
    return rows


def _l2_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result.get("windows") or []:
        if int(item.get("size_contracts") or 0) != 100:
            continue
        metadata = _metadata(item)
        rows.append(
            {
                **metadata,
                "match_id": item["match_id"],
                "start": item["start"],
                "settlement_at": item.get("settlement_at") or item["end"],
                "paired_exit_at": item.get("paired_exit_at"),
                "entry_cost_per_contract": (
                    float(item["entry_cost_per_contract"])
                    + float(item.get("entry_fee_total") or 0) / 100
                ),
                "net_profit_per_contract": float(
                    item.get("paired_exit_net_profit_per_contract")
                    if item.get("paired_exit_qualifies")
                    else item["locked_hold_profit_per_contract"]
                ),
                "depth_contracts": float(item.get("max_paired_capacity_contracts") or 0),
                "evidence_label": "pmxt_archived_l2",
            }
        )
    return rows


def _rank(
    annual_rows: list[dict[str, Any]],
    l2_rows: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    annual_grouped = _group(annual_rows, key)
    l2_grouped = _group(l2_rows, key)
    labels = sorted(set(annual_grouped) | set(l2_grouped))
    annual_results = {
        label: simulate_capped_portfolio(annual_grouped.get(label, []), enforce_depth=False)
        for label in labels
    }
    l2_results = {
        label: simulate_capped_portfolio(l2_grouped.get(label, []), enforce_depth=True)
        for label in labels
    }
    annual_percentiles = _percentiles(
        {label: result["realized_profit"] for label, result in annual_results.items()}
    )
    l2_observed = {
        label: result["realized_profit"]
        for label, result in l2_results.items()
        if l2_grouped.get(label)
    }
    l2_percentiles = _percentiles(l2_observed)
    rows = []
    for label in labels:
        annual = annual_results[label]
        l2 = l2_results[label]
        l2_validated = bool(l2_grouped.get(label))
        annual_pct = annual_percentiles.get(label, 0.0)
        l2_pct = l2_percentiles.get(label, 50.0) if l2_validated else 50.0
        rows.append(
            {
                key: label,
                "blended_score": 0.70 * annual_pct + 0.30 * l2_pct,
                "annual_profit_percentile": annual_pct,
                "pmxt_profit_percentile": l2_pct,
                "annual_net_profit": annual["realized_profit"],
                "annual_roi": annual["roi"],
                "annual_ending_bankroll": annual["ending_bankroll"],
                "annual_positions": annual["accepted_positions"],
                "pmxt_net_profit": l2["realized_profit"],
                "pmxt_roi": l2["roi"],
                "pmxt_ending_bankroll": l2["ending_bankroll"],
                "pmxt_positions": l2["accepted_positions"],
                "pmxt_validation": "L2 validated" if l2_validated else "Not L2 validated",
            }
        )
    rows.sort(
        key=lambda item: (
            item["blended_score"],
            item["annual_net_profit"],
            item["pmxt_net_profit"],
        ),
        reverse=True,
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unspecified")].append(row)
    return grouped


def _metadata(item: dict[str, Any]) -> dict[str, str]:
    category = str(item.get("focus_scenario") or "additional_discovered_scenario_coverage")
    competition = str(item.get("competition_phase") or "regular_season_or_unspecified")
    tournament = str(item.get("tournament_level") or "not_applicable_or_unspecified")
    market_type = str(item.get("market_type") or "moneyline_or_binary")
    timing = str(item.get("timing_phase") or item.get("phase") or "unspecified")
    components = [category, competition]
    if tournament != "not_applicable_or_unspecified":
        components.append(tournament)
    components.extend([market_type, timing])
    return {"focus_scenario": category, "subscenario": " | ".join(components)}


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    if len(ordered) == 1:
        return {ordered[0][0]: 100.0}
    return {
        label: 100.0 * index / (len(ordered) - 1)
        for index, (label, _) in enumerate(ordered)
    }
