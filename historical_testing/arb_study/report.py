from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def write_opportunities_csv(path: str | Path, opportunities: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "match_id",
        "timestamp",
        "direction",
        "yes_venue",
        "no_venue",
        "yes_ask",
        "no_ask",
        "gross_edge_per_contract",
        "net_edge_per_contract",
        "total_fee",
        "slippage_cost_per_contract",
        "trade_size",
        "estimated_partial_fill_exposure",
        "depth_limited_contracts",
    ]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in opportunities:
            writer.writerow({field: item.get(field) for field in fields})


def markdown_summary(scan: dict[str, Any]) -> str:
    params = scan.get("parameters", {})
    summary = scan.get("summary", {})
    markets = sorted(
        scan.get("markets", []),
        key=lambda item: item.get("best_net_edge_per_contract") or -999,
        reverse=True,
    )
    lines = [
        "# Kalshi/Polymarket Arbitrage Scan Summary",
        "",
        "## Parameters",
        "",
        f"- Window: `{params.get('start')}` to `{params.get('end')}`",
        f"- Trade size: `{params.get('trade_size')}` contracts",
        f"- Slippage buffer: `{params.get('slippage_buffer')}` per leg",
        f"- Kalshi fee mode: `{params.get('kalshi_fee_mode')}`",
        f"- Window gap: `{params.get('window_gap_seconds')}` seconds",
        "",
        "## Results",
        "",
        f"- Matched markets scanned: `{summary.get('matched_markets_scanned')}`",
        f"- Gross-positive ticks: `{summary.get('opportunity_ticks_gross_positive')}`",
        f"- Net-positive ticks: `{summary.get('opportunity_ticks_net_positive')}`",
        f"- Net-positive windows: `{summary.get('net_positive_windows')}`",
        f"- Median net-positive window: `{_fmt(summary.get('median_net_window_seconds'))}` seconds",
        f"- Best gross edge/contract: `{_fmt(summary.get('best_gross_edge_per_contract'))}`",
        f"- Best net edge/contract: `{_fmt(summary.get('best_net_edge_per_contract'))}`",
        "",
        "## Top Markets",
        "",
    ]
    for market in markets[:20]:
        lines.extend(
            [
                f"### {_short(market.get('polymarket_title'))}",
                "",
                f"- Kalshi: {_short(market.get('kalshi_title'))}",
                f"- Gross-positive ticks: `{market.get('gross_positive_ticks')}`",
                f"- Net-positive ticks: `{market.get('net_positive_ticks')}`",
                f"- Net-positive windows: `{market.get('net_positive_windows')}`",
                f"- Median net-positive window: `{_fmt(market.get('median_net_window_seconds'))}` seconds",
                f"- Best gross edge: `{_fmt(market.get('best_gross_edge_per_contract'))}`",
                f"- Best net edge: `{_fmt(market.get('best_net_edge_per_contract'))}`",
                f"- Partial-fill exposure median: `{_fmt(market.get('median_partial_fill_exposure'))}`",
                f"- Warning: {market.get('resolution_date_warning') or 'None'}",
                "",
            ]
        )
    examples = _top_unique_examples(scan, limit=20)
    if examples:
        lines.extend(["## Top Executable Examples", ""])
        for example in examples:
            total_cost = float(example["yes_ask"]) + float(example["no_ask"])
            lines.extend(
                [
                    f"### {_short(example['polymarket_title'])}",
                    "",
                    f"- Timestamp: `{example['timestamp']}`",
                    f"- Position: buy YES on `{example['yes_venue']}` at `{_fmt(example['yes_ask'])}` and buy NO on `{example['no_venue']}` at `{_fmt(example['no_ask'])}`",
                    f"- Total entry cost: `{total_cost:.6f}`",
                    f"- Gross edge: `{_fmt(example['gross_edge_per_contract'])}`",
                    f"- Net edge: `{_fmt(example['net_edge_per_contract'])}`",
                    f"- Fees: `{_fmt(example['total_fee'])}` on `{example['trade_size']}` contracts",
                    f"- Top-of-book depth: `{_fmt(example['depth_limited_contracts'])}` contracts",
                    f"- Kalshi: {_short(example['kalshi_title'])}",
                    f"- Match warning: {example.get('resolution_date_warning') or 'None'}",
                    "",
                ]
            )
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)


def _short(value: Any, limit: int = 140) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _top_unique_examples(scan: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    markets = {market["match_id"]: market for market in scan.get("markets", [])}
    examples: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for opportunity in sorted(
        scan.get("opportunities", []),
        key=lambda item: item.get("net_edge_per_contract") or -999,
        reverse=True,
    ):
        if (opportunity.get("net_edge_per_contract") or 0) <= 0:
            continue
        key = (
            opportunity.get("match_id"),
            opportunity.get("direction"),
            round(float(opportunity.get("yes_ask") or 0), 4),
            round(float(opportunity.get("no_ask") or 0), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        market = markets.get(opportunity.get("match_id"), {})
        examples.append(
            {
                **opportunity,
                "polymarket_title": market.get("polymarket_title", ""),
                "kalshi_title": market.get("kalshi_title", ""),
                "resolution_date_warning": market.get("resolution_date_warning"),
            }
        )
        if len(examples) >= limit:
            break
    return examples
