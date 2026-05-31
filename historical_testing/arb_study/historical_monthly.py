from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .official_api import KalshiOfficialClient, PolymarketGammaClient
from .official_catalog import (
    _dedupe,
    _fetch_polymarket_month,
    _month_slices,
    _parse_iso,
    _trim_kalshi_market,
    match_official_catalogs_monthly,
)
from .serde import read_json, write_json


def collect_monthly_cache(
    cache_path: str | Path,
    start: str,
    end: str,
    kalshi_historical_pages: int = 100,
    kalshi_current_pages_per_month: int = 2,
    polymarket_pages_per_month: int = 5,
) -> dict[str, Any]:
    target = Path(cache_path)
    cache = read_json(target) if target.exists() else {"version": 1, "kalshi_months": {}, "polymarket_months": {}}
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    kalshi = KalshiOfficialClient()
    polymarket = PolymarketGammaClient()
    historical_cutoff = _parse_iso(kalshi.historical_cutoff()["market_settled_ts"])
    _crawl_kalshi_historical(cache, target, kalshi, start_dt, kalshi_historical_pages)
    for month_start, month_end in _month_slices(start_dt, end_dt):
        key = month_start.strftime("%Y-%m")
        if key not in cache["polymarket_months"]:
            cache["polymarket_months"][key] = {
                "start": month_start.isoformat(),
                "end": month_end.isoformat(),
                **_fetch_polymarket_month(polymarket, month_start, month_end, polymarket_pages_per_month),
            }
            write_json(target, cache)
            print(f"Checkpointed monthly Polymarket catalog {key}", flush=True)
        if month_start < historical_cutoff or key not in cache["kalshi_months"]:
            cache["kalshi_months"][key] = {
                "start": month_start.isoformat(),
                "end": month_end.isoformat(),
                **_kalshi_month(
                    cache,
                    kalshi,
                    month_start,
                    month_end,
                    historical_cutoff,
                    kalshi_current_pages_per_month,
                ),
            }
            write_json(target, cache)
            print(f"Checkpointed monthly Kalshi catalog {key}", flush=True)
    return cache


def write_coverage_report(cache_path: str | Path, out_path: str | Path) -> dict[str, Any]:
    cache = read_json(cache_path)
    crawl = cache.get("kalshi_historical_crawl", {})
    rows = []
    for month in sorted(set(cache.get("polymarket_months", {})) | set(cache.get("kalshi_months", {}))):
        poly = cache.get("polymarket_months", {}).get(month, {})
        kalshi = cache.get("kalshi_months", {}).get(month, {})
        rows.append(
            {
                "month": month,
                "kalshi_markets": len(kalshi.get("markets", [])),
                "kalshi_truncated": kalshi.get("truncated"),
                "polymarket_markets": len(poly.get("markets", [])),
                "polymarket_truncated": poly.get("truncated"),
            }
        )
    result = {
        "kalshi_historical_pages": crawl.get("pages", 0),
        "kalshi_historical_markets": len(crawl.get("markets", [])),
        "kalshi_oldest_close_time_reached": crawl.get("oldest_close_time"),
        "kalshi_historical_complete": crawl.get("complete", False),
        "months": rows,
    }
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 12-Month Official Catalog Coverage Audit",
        "",
        "This audit records actual API coverage reached by the resumable monthly collector. "
        "It is not an arbitrage-result report.",
        "",
        f"- Kalshi historical pages crawled: `{result['kalshi_historical_pages']}`",
        f"- Kalshi historical markets crawled: `{result['kalshi_historical_markets']}`",
        f"- Oldest Kalshi close time reached: `{result['kalshi_oldest_close_time_reached']}`",
        f"- Full requested Kalshi history reached: `{result['kalshi_historical_complete']}`",
        "",
        "| Month | Kalshi markets currently indexed | Kalshi incomplete | Polymarket markets currently indexed | Polymarket page-capped |",
        "|---|---:|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['month']} | {row['kalshi_markets']} | {row['kalshi_truncated']} "
            f"| {row['polymarket_markets']} | {row['polymarket_truncated']} |"
        )
    target.write_text("\n".join(lines), encoding="utf-8")
    return result


def normalize_monthly_cache(
    cache_path: str | Path,
    out_path: str | Path,
    start: str,
    end: str,
    min_score: float = 0.78,
) -> dict[str, Any]:
    cache = read_json(cache_path)
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    historical_months = cache.get("kalshi_months") or cache.get("kalshi_historical_months", {})
    raw_poly = _dedupe(
        [
            market
            for month in cache.get("polymarket_months", {}).values()
            for market in month.get("markets", [])
        ],
        "id",
    )
    raw_kalshi = _dedupe(
        [
            market
            for month in historical_months.values()
            for market in month.get("markets", [])
        ],
        "ticker",
    )
    matches, rejected = match_official_catalogs_monthly(raw_kalshi, raw_poly, min_score=min_score)
    result = {
        "meta": {
            "source": "official_kalshi_historical_months_and_recent_events_with_polymarket_gamma_catalog",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "kalshi_catalog_markets": len(raw_kalshi),
            "polymarket_catalog_markets": len(raw_poly),
            "matched_pairs": len(matches),
            "rejected_candidates": len(rejected),
            "min_score": min_score,
            "kalshi_historical_months": {
                key: {
                    "kalshi_markets": len(month.get("markets", [])),
                    "kalshi_truncated": month.get("truncated", False),
                }
                for key, month in sorted(historical_months.items())
            },
            "polymarket_months": {
                key: {
                    "polymarket_markets": len(month.get("markets", [])),
                    "polymarket_truncated": month.get("truncated", False),
                }
                for key, month in sorted(cache.get("polymarket_months", {}).items())
            },
            "note": (
                "This is a capped, checkpointed official-catalog screen. Catalog title matching is "
                "conservative but still requires manual resolution-rule review before trading."
            ),
        },
        "matches": [asdict(match) for match in matches],
        "rejected": rejected,
    }
    write_json(out_path, result)
    return result


def _crawl_kalshi_historical(
    cache: dict[str, Any],
    target: Path,
    client: KalshiOfficialClient,
    start: datetime,
    max_pages: int,
) -> None:
    crawl = cache.setdefault(
        "kalshi_historical_crawl",
        {"markets": [], "cursor": None, "complete": False, "pages": 0, "oldest_close_time": None},
    )
    if crawl.get("complete"):
        return
    for _ in range(max_pages):
        data = client.historical_markets(limit=1000, cursor=crawl.get("cursor"))
        rows = list(data.get("markets") or [])
        crawl["markets"].extend(_trim_kalshi_market(item) for item in rows)
        crawl["cursor"] = data.get("cursor")
        crawl["pages"] = int(crawl.get("pages") or 0) + 1
        dates = [
            _parse_iso(item["close_time"])
            for item in crawl["markets"]
            if item.get("close_time")
        ]
        oldest = min(dates) if dates else None
        crawl["oldest_close_time"] = oldest.isoformat() if oldest else None
        crawl["complete"] = bool(not rows or not crawl["cursor"] or (oldest and oldest <= start))
        write_json(target, cache)
        print(
            f"Checkpointed Kalshi historical crawl page {crawl['pages']}; "
            f"markets={len(crawl['markets'])}; oldest={crawl['oldest_close_time']}",
            flush=True,
        )
        if crawl["complete"]:
            break


def _kalshi_month(
    cache: dict[str, Any],
    client: KalshiOfficialClient,
    start: datetime,
    end: datetime,
    historical_cutoff: datetime,
    max_pages: int,
) -> dict[str, Any]:
    if start < historical_cutoff:
        historical_end = min(end, historical_cutoff)
        crawl = cache.get("kalshi_historical_crawl", {})
        markets = [
            market
            for market in crawl.get("markets", [])
            if _in_range(market, start, historical_end)
        ]
        return {"markets": markets, "truncated": not crawl.get("complete", False)}
    return _fetch_kalshi_current_month(client, start, end, max_pages)


def _fetch_kalshi_current_month(
    client: KalshiOfficialClient,
    start: datetime,
    end: datetime,
    max_pages: int,
) -> dict[str, Any]:
    markets = []
    truncated = False
    cursor = None
    for page in range(max_pages):
        data = client.markets(
            limit=1000,
            cursor=cursor,
            min_close_ts=int(start.timestamp()),
            max_close_ts=int(end.timestamp()),
        )
        rows = list(data.get("markets") or [])
        markets.extend(_trim_kalshi_market(item) for item in rows)
        cursor = data.get("cursor")
        if not cursor or not rows:
            break
        if page == max_pages - 1:
            truncated = True
    return {"markets": markets, "truncated": truncated}


def _in_range(market: dict[str, Any], start: datetime, end: datetime) -> bool:
    value = market.get("close_time") or market.get("expiration_time")
    if not value:
        return False
    close = _parse_iso(value)
    return start <= close < end


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize a checkpointed official 12-month catalog cache")
    parser.add_argument("--cache", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--coverage-md", default=None)
    parser.add_argument("--coverage-only", action="store_true")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--min-score", type=float, default=0.78)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--kalshi-historical-pages", type=int, default=100)
    parser.add_argument("--kalshi-current-pages-per-month", type=int, default=2)
    parser.add_argument("--polymarket-pages-per-month", type=int, default=5)
    args = parser.parse_args()
    if args.collect:
        collect_monthly_cache(
            args.cache,
            args.start,
            args.end,
            kalshi_historical_pages=args.kalshi_historical_pages,
            kalshi_current_pages_per_month=args.kalshi_current_pages_per_month,
            polymarket_pages_per_month=args.polymarket_pages_per_month,
        )
    if args.coverage_md:
        write_coverage_report(args.cache, args.coverage_md)
    if args.coverage_only:
        return
    result = normalize_monthly_cache(args.cache, args.out, args.start, args.end, args.min_score)
    print(
        f"Normalized {result['meta']['kalshi_catalog_markets']} Kalshi and "
        f"{result['meta']['polymarket_catalog_markets']} Polymarket catalog markets into "
        f"{result['meta']['matched_pairs']} conservative pairs"
    )


if __name__ == "__main__":
    main()
