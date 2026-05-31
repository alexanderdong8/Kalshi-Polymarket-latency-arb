from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from .serde import read_json, write_json


DEFAULT_ORDER_SIZES = [1, 5, 10, 25, 50, 100, 250]
DEFAULT_LATENCIES_SECONDS = [0.1, 0.5, 1.0, 2.0, 5.0]


def analyze_fillability(
    scan_path: str | Path,
    out_json: str | Path,
    out_md: str | Path,
    order_sizes: list[int] | None = None,
    latencies_seconds: list[float] | None = None,
    window_gap_seconds: float | None = None,
) -> dict[str, Any]:
    scan = read_json(scan_path)
    sizes = order_sizes or DEFAULT_ORDER_SIZES
    latencies = latencies_seconds or DEFAULT_LATENCIES_SECONDS
    gap = window_gap_seconds or float(scan.get("parameters", {}).get("window_gap_seconds") or 5.0)
    opportunities = [
        item for item in scan.get("opportunities", [])
        if (item.get("net_edge_per_contract") or 0) > 0
        and (item.get("depth_limited_contracts") or 0) > 0
    ]
    windows = _build_windows(opportunities, gap)
    size_rows = []
    for size in sizes:
        eligible = [window for window in windows if window["max_depth_contracts"] >= size]
        size_rows.append(
            {
                "order_size_contracts": size,
                "eligible_windows": len(eligible),
                "share_of_net_positive_windows": _ratio(len(eligible), len(windows)),
                "median_window_seconds": median([window["duration_seconds"] for window in eligible]) if eligible else None,
                "median_best_net_edge_per_contract": median([window["best_net_edge_per_contract"] for window in eligible]) if eligible else None,
                "latency_coverage": {
                    str(latency): {
                        "windows": sum(window["duration_seconds"] >= latency for window in eligible),
                        "share_of_size_eligible_windows": _ratio(
                            sum(window["duration_seconds"] >= latency for window in eligible),
                            len(eligible),
                        ),
                    }
                    for latency in latencies
                },
            }
        )

    result = {
        "source_scan": str(scan_path),
        "definition": (
            "This is a quoted-depth and window-duration proxy, not an observed fill probability. "
            "It assumes top-of-book liquidity remains available and does not model queue position, "
            "network delay, competing bots, adverse selection, or partial fills."
        ),
        "net_positive_windows": len(windows),
        "median_net_window_seconds": median([window["duration_seconds"] for window in windows]) if windows else None,
        "order_size_rows": size_rows,
        "example_windows": sorted(
            windows,
            key=lambda item: (item["best_net_edge_per_contract"], item["max_depth_contracts"]),
            reverse=True,
        )[:20],
    }
    write_json(out_json, result)
    target = Path(out_md)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_markdown(result), encoding="utf-8")
    return result


def _build_windows(opportunities: list[dict[str, Any]], gap_seconds: float) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in opportunities:
        grouped[(item["match_id"], item["direction"])].append(item)

    windows = []
    for (match_id, direction), items in grouped.items():
        items.sort(key=lambda item: item["timestamp"])
        current: dict[str, Any] | None = None
        for item in items:
            ts = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
            if current is None or (ts - current["last_ts"]).total_seconds() > gap_seconds:
                if current is not None:
                    windows.append(_finalize(current))
                current = {
                    "match_id": match_id,
                    "direction": direction,
                    "start_ts": ts,
                    "last_ts": ts,
                    "ticks": 1,
                    "max_depth_contracts": float(item["depth_limited_contracts"]),
                    "best_net_edge_per_contract": float(item["net_edge_per_contract"]),
                    "best_gross_edge_per_contract": float(item["gross_edge_per_contract"]),
                    "yes_venue": item["yes_venue"],
                    "no_venue": item["no_venue"],
                    "yes_ask": float(item["yes_ask"]),
                    "no_ask": float(item["no_ask"]),
                }
                continue
            current["last_ts"] = ts
            current["ticks"] += 1
            current["max_depth_contracts"] = max(current["max_depth_contracts"], float(item["depth_limited_contracts"]))
            if float(item["net_edge_per_contract"]) > current["best_net_edge_per_contract"]:
                current["best_net_edge_per_contract"] = float(item["net_edge_per_contract"])
                current["best_gross_edge_per_contract"] = float(item["gross_edge_per_contract"])
                current["yes_venue"] = item["yes_venue"]
                current["no_venue"] = item["no_venue"]
                current["yes_ask"] = float(item["yes_ask"])
                current["no_ask"] = float(item["no_ask"])
        if current is not None:
            windows.append(_finalize(current))
    return windows


def _finalize(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": window["match_id"],
        "direction": window["direction"],
        "start": window["start_ts"].isoformat(),
        "end": window["last_ts"].isoformat(),
        "duration_seconds": (window["last_ts"] - window["start_ts"]).total_seconds(),
        "ticks": window["ticks"],
        "max_depth_contracts": window["max_depth_contracts"],
        "best_net_edge_per_contract": window["best_net_edge_per_contract"],
        "best_gross_edge_per_contract": window["best_gross_edge_per_contract"],
        "yes_venue": window["yes_venue"],
        "no_venue": window["no_venue"],
        "yes_ask": window["yes_ask"],
        "no_ask": window["no_ask"],
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Fillability Proxy Analysis",
        "",
        result["definition"],
        "",
        f"- Net-positive windows: `{result['net_positive_windows']}`",
        f"- Median net window seconds: `{_fmt(result['median_net_window_seconds'])}`",
        "",
        "## Order Size Coverage",
        "",
        "| Contracts | Depth-eligible windows | Share of net windows | Median duration (s) | Median best net edge | >=0.1s | >=0.5s | >=1s | >=2s | >=5s |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["order_size_rows"]:
        latency = row["latency_coverage"]
        lines.append(
            f"| {row['order_size_contracts']} "
            f"| {row['eligible_windows']} "
            f"| {_pct(row['share_of_net_positive_windows'])} "
            f"| {_fmt(row['median_window_seconds'])} "
            f"| {_fmt(row['median_best_net_edge_per_contract'])} "
            f"| {_pct(latency['0.1']['share_of_size_eligible_windows'])} "
            f"| {_pct(latency['0.5']['share_of_size_eligible_windows'])} "
            f"| {_pct(latency['1.0']['share_of_size_eligible_windows'])} "
            f"| {_pct(latency['2.0']['share_of_size_eligible_windows'])} "
            f"| {_pct(latency['5.0']['share_of_size_eligible_windows'])} |"
        )
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.6f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"
