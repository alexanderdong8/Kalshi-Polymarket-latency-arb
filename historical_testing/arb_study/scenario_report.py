from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .scenario import classify_domain, classify_phase, summarize_records
from .serde import read_json, write_json


def analyze_batch_scan(
    scan_path: str | Path,
    out_json: str | Path,
    out_md: str | Path,
    out_csv: str | Path | None = None,
) -> dict[str, Any]:
    scan = read_json(scan_path)
    scan_start = scan.get("parameters", {}).get("start", "")
    records = []
    for market in scan.get("markets", []):
        title = f"{market.get('polymarket_title', '')} {market.get('kalshi_title', '')}"
        domain = classify_domain(title)
        phase = classify_phase(
            title=title,
            scan_start=scan_start,
            resolution_date=None,
            aligned_state_count=market.get("aligned_state_count_estimate") or 0,
            best_gross_edge=market.get("best_gross_edge_per_contract"),
            median_window_seconds=market.get("median_net_window_seconds"),
        )
        records.append({**market, "domain": domain, "phase": phase})

    bucket_summary = summarize_records(records)
    top_clean = [
        record
        for record in sorted(records, key=lambda item: item.get("best_net_edge_per_contract") or -999, reverse=True)
        if record.get("best_net_edge_per_contract") is not None and not record.get("resolution_date_warning")
    ][:20]
    top_sports = [
        record
        for record in sorted(records, key=lambda item: item.get("best_net_edge_per_contract") or -999, reverse=True)
        if record["domain"].startswith("sports") and record.get("best_net_edge_per_contract") is not None
    ][:20]
    result = {
        "source_scan": str(scan_path),
        "parameters": scan.get("parameters", {}),
        "overall_summary": scan.get("summary", {}),
        "bucket_summary": bucket_summary,
        "top_clean_markets": top_clean,
        "top_sports_markets": top_sports,
        "records": records,
    }
    write_json(out_json, result)
    Path(out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(out_md).write_text(_markdown(result), encoding="utf-8")
    if out_csv:
        _write_csv(out_csv, records)
    return result


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Scenario Analysis",
        "",
        "This report groups the executable PMXT orderbook replay by market type and volatility phase.",
        "",
        "## Overall",
        "",
    ]
    overall = result.get("overall_summary", {})
    for key in [
        "matched_markets_scanned",
        "hours_scanned",
        "opportunity_ticks_gross_positive",
        "opportunity_ticks_net_positive",
        "gross_positive_windows",
        "net_positive_windows",
        "best_gross_edge_per_contract",
        "best_net_edge_per_contract",
        "median_net_window_seconds",
    ]:
        lines.append(f"- {key}: `{overall.get(key)}`")

    lines.extend(["", "## Buckets", ""])
    for row in result.get("bucket_summary", []):
        lines.append(
            "- "
            f"{row['domain']} / {row['phase']}: "
            f"{row['markets']} markets, "
            f"{row['markets_with_net_positive_windows']} with net-positive windows, "
            f"{row['net_positive_windows']} net windows, "
            f"max net edge `{_fmt(row.get('max_best_net_edge'))}`"
        )

    lines.extend(["", "## Top Clean Markets", ""])
    for row in result.get("top_clean_markets", [])[:10]:
        lines.extend(_market_lines(row))

    lines.extend(["", "## Top Sports Markets", ""])
    for row in result.get("top_sports_markets", [])[:10]:
        lines.extend(_market_lines(row))
    return "\n".join(lines)


def _market_lines(row: dict[str, Any]) -> list[str]:
    return [
        f"### {row.get('polymarket_title')}",
        "",
        f"- Kalshi: {row.get('kalshi_title')}",
        f"- Domain: `{row.get('domain')}`",
        f"- Phase: `{row.get('phase')}`",
        f"- Net-positive windows: `{row.get('net_positive_windows')}`",
        f"- Best gross edge: `{_fmt(row.get('best_gross_edge_per_contract'))}`",
        f"- Best net edge: `{_fmt(row.get('best_net_edge_per_contract'))}`",
        f"- Median net window seconds: `{_fmt(row.get('median_net_window_seconds'))}`",
        f"- Warning: {row.get('resolution_date_warning') or 'None'}",
        "",
    ]


def _write_csv(path: str | Path, records: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "match_id",
        "domain",
        "phase",
        "polymarket_title",
        "kalshi_title",
        "gross_positive_windows",
        "net_positive_windows",
        "best_gross_edge_per_contract",
        "best_net_edge_per_contract",
        "median_net_window_seconds",
        "resolution_date_warning",
    ]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fields})


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.6f}"
