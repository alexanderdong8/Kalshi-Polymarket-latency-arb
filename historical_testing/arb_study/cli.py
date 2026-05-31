from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from .annual_proxy import scan_annual_official_proxy
from .archive import overlapping_archive_hours
from .clusters import fetch_cluster_universe, matches_payload, normalize_clusters
from .config import get_pmxt_api_key
from .fillability import analyze_fillability
from .official_catalog import discover_official_history
from .pmxt_client import PMXTClient, dedupe_matches, normalize_pair
from .report import markdown_summary, write_opportunities_csv
from .scenario_report import analyze_batch_scan
from .scanner import scan_matches, scan_matches_batch
from .serde import matched_market_from_dict, read_json, write_json
from .official_price_scanner import scan_official_price_histories


DEFAULT_CATEGORIES = ["Sports", "Politics", "Crypto", "Economics"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Kalshi/Polymarket arbitrage feasibility tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="Discover identity-matched Kalshi/Polymarket markets")
    discover.add_argument("--categories", nargs="*", default=DEFAULT_CATEGORIES)
    discover.add_argument("--limit", type=int, default=50)
    discover.add_argument("--min-difference", type=float, default=0.0)
    discover.add_argument("--max-resolution-drift-days", type=int, default=14)
    discover.add_argument("--strict-resolution-dates", action="store_true")
    discover.add_argument("--out", default="data/matches.json")

    discover_clusters = sub.add_parser(
        "discover-clusters",
        help="Discover a wide Kalshi/Polymarket identity universe from PMXT matched-market clusters",
    )
    discover_clusters.add_argument("--out", default="data/cluster_matches.json")
    discover_clusters.add_argument("--checkpoint", default="data/cluster_pages_checkpoint.json")
    discover_clusters.add_argument("--page-limit", type=int, default=250)
    discover_clusters.add_argument("--max-clusters", type=int, default=None)
    discover_clusters.add_argument("--min-confidence", type=float, default=0.9)
    discover_clusters.add_argument("--max-resolution-drift-days", type=int, default=45)
    discover_clusters.add_argument("--fresh", action="store_true", help="Ignore any existing checkpoint")

    scan = sub.add_parser("scan", help="Scan PMXT archive orderbooks for matched markets")
    scan.add_argument("--matches", default="data/matches.json")
    scan.add_argument("--start", required=True, help="UTC hour, e.g. 2026-05-23T07")
    scan.add_argument("--end", required=True, help="Exclusive UTC hour, e.g. 2026-05-23T09")
    scan.add_argument("--out", default="reports/scan.json")
    scan.add_argument("--csv", default=None)
    scan.add_argument("--trade-size", type=int, default=100)
    scan.add_argument("--slippage-buffer", type=float, default=0.005)
    scan.add_argument("--kalshi-fee-mode", choices=["taker", "maker"], default="taker")
    scan.add_argument("--polymarket-fallback-fee-rate", type=float, default=0.05)
    scan.add_argument("--max-markets", type=int, default=None)
    scan.add_argument("--window-gap-seconds", type=float, default=5.0)

    scan_batch = sub.add_parser("scan-batch", help="Batch scan PMXT archive orderbooks for many matched markets")
    scan_batch.add_argument("--matches", default="data/cluster_matches.json")
    scan_batch.add_argument("--start", default=None, help="UTC hour, e.g. 2026-05-23T07")
    scan_batch.add_argument("--end", default=None, help="Exclusive UTC hour, e.g. 2026-05-23T09")
    scan_batch.add_argument("--auto-overlap", action="store_true", help="Use all currently indexed overlapping Kalshi/Polymarket v2 hours")
    scan_batch.add_argument("--out", default="reports/batch_scan.json")
    scan_batch.add_argument("--csv", default=None)
    scan_batch.add_argument("--trade-size", type=int, default=100)
    scan_batch.add_argument("--slippage-buffer", type=float, default=0.005)
    scan_batch.add_argument("--kalshi-fee-mode", choices=["taker", "maker"], default="taker")
    scan_batch.add_argument("--polymarket-fallback-fee-rate", type=float, default=0.05)
    scan_batch.add_argument("--max-markets", type=int, default=None)
    scan_batch.add_argument("--window-gap-seconds", type=float, default=5.0)

    report = sub.add_parser("report", help="Create a Markdown summary from a scan JSON")
    report.add_argument("--scan", default="reports/scan.json")
    report.add_argument("--out", default="reports/summary.md")

    scenario_report = sub.add_parser("scenario-report", help="Group an executable batch scan by domain and activity phase")
    scenario_report.add_argument("--scan", default="reports/batch_scan_2026-05-23T07.json")
    scenario_report.add_argument("--out-json", default="reports/scenario_analysis.json")
    scenario_report.add_argument("--out-md", default="reports/scenario_analysis.md")
    scenario_report.add_argument("--out-csv", default="reports/scenario_analysis.csv")

    official_scan = sub.add_parser("official-price-scan", help="Use official Kalshi/Polymarket historical price APIs for proxy analysis")
    official_scan.add_argument("--matches", default="data/cluster_matches.json")
    official_scan.add_argument("--start", required=True)
    official_scan.add_argument("--end", required=True)
    official_scan.add_argument("--out", default="reports/official_price_scan.json")
    official_scan.add_argument("--max-markets", type=int, default=100)
    official_scan.add_argument("--trade-size", type=int, default=100)
    official_scan.add_argument("--slippage-buffer", type=float, default=0.005)
    official_scan.add_argument("--kalshi-fee-mode", choices=["taker", "maker"], default="taker")
    official_scan.add_argument("--polymarket-fallback-fee-rate", type=float, default=0.05)

    official_history = sub.add_parser(
        "discover-official-history",
        help="Discover conservative Kalshi/Polymarket catalog matches across a longer official-API window",
    )
    official_history.add_argument("--start", required=True, help="UTC date/time, e.g. 2025-05-30T00:00:00Z")
    official_history.add_argument("--end", required=True, help="Exclusive UTC date/time")
    official_history.add_argument("--out", default="data/official_history_matches.json")
    official_history.add_argument("--cache", default="data/official_history_catalog_cache.json")
    official_history.add_argument("--kalshi-event-pages", type=int, default=100)
    official_history.add_argument("--polymarket-pages-per-month", type=int, default=30)
    official_history.add_argument("--max-expanded-events", type=int, default=3000)
    official_history.add_argument("--min-score", type=float, default=0.78)
    official_history.add_argument("--fresh", action="store_true")

    annual_proxy = sub.add_parser(
        "annual-proxy-report",
        help="Scan a stratified 12-month official-API catalog sample and write monthly proxy statistics",
    )
    annual_proxy.add_argument("--matches", default="data/official_history_matches.json")
    annual_proxy.add_argument("--start", required=True)
    annual_proxy.add_argument("--end", required=True)
    annual_proxy.add_argument("--out-json", default="reports/annual_official_proxy.json")
    annual_proxy.add_argument("--out-md", default="reports/annual_official_proxy.md")
    annual_proxy.add_argument("--max-markets-per-month", type=int, default=12)
    annual_proxy.add_argument("--workers", type=int, default=6)
    annual_proxy.add_argument("--trade-size", type=int, default=100)
    annual_proxy.add_argument("--slippage-buffer", type=float, default=0.005)
    annual_proxy.add_argument("--kalshi-fee-mode", choices=["taker", "maker"], default="taker")
    annual_proxy.add_argument("--polymarket-fallback-fee-rate", type=float, default=0.05)

    fillability = sub.add_parser("fillability-report", help="Estimate order-size and latency coverage from executable windows")
    fillability.add_argument("--scan", default="reports/batch_scan_2026-05-23T07.json")
    fillability.add_argument("--out-json", default="reports/fillability_analysis.json")
    fillability.add_argument("--out-md", default="reports/fillability_analysis.md")

    sample = sub.add_parser("sample", help="Run a small end-to-end sample")
    sample.add_argument("--out-dir", default="reports/sample")

    hours = sub.add_parser("archive-hours", help="Print currently overlapping PMXT archive hours")
    hours.add_argument("--out", default=None)

    args = parser.parse_args()
    if args.command == "discover":
        run_discover(args)
    elif args.command == "discover-clusters":
        run_discover_clusters(args)
    elif args.command == "scan":
        run_scan(args)
    elif args.command == "scan-batch":
        run_scan_batch(args)
    elif args.command == "report":
        run_report(args)
    elif args.command == "scenario-report":
        run_scenario_report(args)
    elif args.command == "official-price-scan":
        run_official_price_scan(args)
    elif args.command == "discover-official-history":
        run_discover_official_history(args)
    elif args.command == "annual-proxy-report":
        run_annual_proxy_report(args)
    elif args.command == "fillability-report":
        run_fillability_report(args)
    elif args.command == "sample":
        run_sample(args)
    elif args.command == "archive-hours":
        run_archive_hours(args)


def run_discover(args: argparse.Namespace) -> None:
    client = PMXTClient(get_pmxt_api_key())
    found = []
    for category in args.categories:
        raw_pairs = client.fetch_matched_markets(
            category=category,
            limit=args.limit,
            min_difference=args.min_difference,
        )
        for raw in raw_pairs:
            match = normalize_pair(raw, max_resolution_drift_days=args.max_resolution_drift_days)
            if not match:
                continue
            if args.strict_resolution_dates and match.resolution_date_warning:
                continue
            found.append(match)

    matches = dedupe_matches(found)
    payload = {
        "matches": [asdict(match) for match in matches],
        "meta": {
            "categories": args.categories,
            "limit": args.limit,
            "min_difference": args.min_difference,
            "count": len(matches),
        },
    }
    write_json(args.out, payload)
    print(f"Wrote {len(matches)} matches to {args.out}")


def run_scan(args: argparse.Namespace) -> None:
    payload = read_json(args.matches)
    matches = [matched_market_from_dict(item) for item in payload.get("matches", [])]
    result = scan_matches(
        matches=matches,
        start=args.start,
        end=args.end,
        trade_size=args.trade_size,
        slippage_buffer=args.slippage_buffer,
        kalshi_fee_mode=args.kalshi_fee_mode,
        polymarket_fallback_fee_rate=args.polymarket_fallback_fee_rate,
        max_markets=args.max_markets,
        window_gap_seconds=args.window_gap_seconds,
    )
    write_json(args.out, result)
    if args.csv:
        write_opportunities_csv(args.csv, result["opportunities"])
    print(
        "Scanned "
        f"{result['summary']['matched_markets_scanned']} markets; "
        f"net-positive ticks={result['summary']['opportunity_ticks_net_positive']}; "
        f"wrote {args.out}"
    )


def run_discover_clusters(args: argparse.Namespace) -> None:
    client = PMXTClient(get_pmxt_api_key(), timeout=90, retries=6)
    clusters = fetch_cluster_universe(
        client,
        checkpoint_path=args.checkpoint,
        page_limit=args.page_limit,
        max_clusters=args.max_clusters,
        resume=not args.fresh,
    )
    matches, rejected = normalize_clusters(
        clusters,
        min_confidence=args.min_confidence,
        max_resolution_drift_days=args.max_resolution_drift_days,
    )
    write_json(args.out, matches_payload(matches, rejected, clusters))
    print(
        f"Fetched {len(clusters)} clusters; "
        f"wrote {len(matches)} valid pairs to {args.out}; "
        f"rejected {len(rejected)} clusters"
    )


def run_scan_batch(args: argparse.Namespace) -> None:
    payload = read_json(args.matches)
    matches = [matched_market_from_dict(item) for item in payload.get("matches", [])]
    start = args.start
    end = args.end
    if args.auto_overlap:
        hours = overlapping_archive_hours()
        if not hours:
            raise RuntimeError("No overlapping PMXT archive hours found.")
        start = hours[0]
        end = _exclusive_end_hour(hours[-1])
    if not start or not end:
        raise RuntimeError("Provide --start/--end or use --auto-overlap.")

    result = scan_matches_batch(
        matches=matches,
        start=start,
        end=end,
        trade_size=args.trade_size,
        slippage_buffer=args.slippage_buffer,
        kalshi_fee_mode=args.kalshi_fee_mode,
        polymarket_fallback_fee_rate=args.polymarket_fallback_fee_rate,
        max_markets=args.max_markets,
        window_gap_seconds=args.window_gap_seconds,
    )
    write_json(args.out, result)
    if args.csv:
        write_opportunities_csv(args.csv, result["opportunities"])
    print(
        "Batch scanned "
        f"{result['summary']['matched_markets_scanned']} markets across "
        f"{result['summary']['hours_scanned']} hours; "
        f"net-positive windows={result['summary']['net_positive_windows']}; "
        f"wrote {args.out}"
    )


def run_report(args: argparse.Namespace) -> None:
    scan = read_json(args.scan)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown_summary(scan), encoding="utf-8")
    print(f"Wrote {args.out}")


def run_scenario_report(args: argparse.Namespace) -> None:
    analyze_batch_scan(args.scan, args.out_json, args.out_md, args.out_csv)
    print(f"Wrote {args.out_md} and {args.out_json}")


def run_official_price_scan(args: argparse.Namespace) -> None:
    payload = read_json(args.matches)
    matches = [matched_market_from_dict(item) for item in payload.get("matches", [])]
    result = scan_official_price_histories(
        matches,
        start=args.start,
        end=args.end,
        max_markets=args.max_markets,
        trade_size=args.trade_size,
        slippage_buffer=args.slippage_buffer,
        kalshi_fee_mode=args.kalshi_fee_mode,
        polymarket_fallback_fee_rate=args.polymarket_fallback_fee_rate,
    )
    write_json(args.out, result)
    print(
        f"Official proxy scanned {result['parameters']['markets_scanned']} markets; "
        f"opportunities={len(result['opportunities'])}; wrote {args.out}"
    )


def run_discover_official_history(args: argparse.Namespace) -> None:
    result = discover_official_history(
        start=args.start,
        end=args.end,
        cache_path=args.cache,
        kalshi_event_pages=args.kalshi_event_pages,
        polymarket_pages_per_month=args.polymarket_pages_per_month,
        max_expanded_events=args.max_expanded_events,
        min_score=args.min_score,
        fresh=args.fresh,
    )
    write_json(args.out, result)
    print(
        f"Official catalog screened {result['meta']['kalshi_events_fetched']} Kalshi events and "
        f"{result['meta']['polymarket_catalog_markets']} Polymarket markets; "
        f"wrote {result['meta']['matched_pairs']} conservative pairs to {args.out}"
    )


def run_annual_proxy_report(args: argparse.Namespace) -> None:
    payload = read_json(args.matches)
    matches = [matched_market_from_dict(item) for item in payload.get("matches", [])]
    result = scan_annual_official_proxy(
        matches,
        start=args.start,
        end=args.end,
        out_json=args.out_json,
        out_md=args.out_md,
        max_markets_per_month=args.max_markets_per_month,
        workers=args.workers,
        trade_size=args.trade_size,
        slippage_buffer=args.slippage_buffer,
        kalshi_fee_mode=args.kalshi_fee_mode,
        polymarket_fallback_fee_rate=args.polymarket_fallback_fee_rate,
        catalog_meta=payload.get("meta", {}),
    )
    print(
        f"Annual proxy scanned {result['parameters']['selected_markets']} markets; "
        f"retained {len(result['opportunities'])} fee/slippage-positive proxy signals; "
        f"wrote {args.out_md}"
    )


def run_fillability_report(args: argparse.Namespace) -> None:
    result = analyze_fillability(args.scan, args.out_json, args.out_md)
    print(
        f"Analyzed {result['net_positive_windows']} net-positive windows; "
        f"wrote {args.out_md}"
    )


def run_sample(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    matches_path = out_dir / "matches.json"
    scan_path = out_dir / "scan.json"
    csv_path = out_dir / "opportunities.csv"
    summary_path = out_dir / "summary.md"

    discover_args = argparse.Namespace(
        categories=["Sports"],
        limit=20,
        min_difference=0.0,
        max_resolution_drift_days=14,
        strict_resolution_dates=False,
        out=str(matches_path),
    )
    run_discover(discover_args)
    scan_args = argparse.Namespace(
        matches=str(matches_path),
        start="2026-05-23T07",
        end="2026-05-23T08",
        out=str(scan_path),
        csv=str(csv_path),
        trade_size=100,
        slippage_buffer=0.005,
        kalshi_fee_mode="taker",
        polymarket_fallback_fee_rate=0.05,
        max_markets=10,
        window_gap_seconds=5.0,
    )
    run_scan(scan_args)
    report_args = argparse.Namespace(scan=str(scan_path), out=str(summary_path))
    run_report(report_args)


def run_archive_hours(args: argparse.Namespace) -> None:
    hours = overlapping_archive_hours()
    payload = {"count": len(hours), "hours": hours}
    if args.out:
        write_json(args.out, payload)
    print(f"overlapping_hours={len(hours)}")
    if hours:
        print(f"first={hours[0]} last={hours[-1]}")


def _exclusive_end_hour(hour: str) -> str:
    from datetime import timedelta

    from .archive import parse_hour

    return (parse_hour(hour) + timedelta(hours=1)).strftime("%Y-%m-%dT%H")


if __name__ == "__main__":
    main()
