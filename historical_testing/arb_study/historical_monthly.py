from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .official_api import KalshiOfficialClient, PolymarketGammaClient
from .official_catalog import (
    MATCHING_GATE_VERSION,
    _dedupe,
    _fetch_polymarket_month,
    _month_slices,
    _parse_iso,
    _trim_kalshi_market,
    _trim_poly_market,
    match_official_catalogs_monthly,
)
from .llm_adjudication import OpenAIAdjudicator
from .serde import read_json, write_json


EXCLUDED_HIGH_FREQUENCY_KALSHI_SERIES = {
    "KXBNB",
    "KXBNB15M",
    "KXBNBD",
    "KXBTC",
    "KXBTC15M",
    "KXBTCD",
    "KXDOGE",
    "KXDOGE15M",
    "KXDOGED",
    "KXETH",
    "KXETH15M",
    "KXETHD",
    "KXHYPE",
    "KXHYPE15M",
    "KXHYPED",
    "KXINXU",
    "KXNASDAQ100U",
    "KXSOL15M",
    "KXSOLD",
    "KXSOLE",
    "KXXRP",
    "KXXRP15M",
    "KXXRPD",
}
KALSHI_RETENTION_POLICY = (
    "Retain the requested scenario universe and recognizable additional coverage while excluding "
    "only repetitive high-frequency crypto and intraday index threshold series. The official "
    "cursor is still paginated across every returned market row."
)
KALSHI_CRAWL_CHECKPOINT_PAGES = 100
CATALOG_TICKER_HINTS = [
    ("KXWNBA", "wnba"),
    ("KXNBA", "nba"),
    ("KXMLB", "mlb"),
    ("KXNHL", "nhl"),
    ("KXMLS", "mls"),
    ("KXATP", "atp"),
    ("KXWTA", "wta"),
    ("KXITFM", "itf men"),
    ("KXITFW", "itf women"),
    ("KXUFC", "ufc"),
    ("KXF1", "f1"),
    ("KXIPL", "ipl"),
    ("KXFIFA", "fifa world cup"),
    ("KXPGA", "golf"),
]
CATALOG_FOCUS_HINTS = [
    ("fifa world cup", "fifa_world_cup"),
    ("world cup", "fifa_world_cup"),
    ("itf women", "itf_women"),
    ("itf men", "itf_men"),
    ("wnba", "wnba"),
    ("nba", "nba"),
    ("mlb", "mlb"),
    ("nhl", "nhl"),
    ("atp", "atp"),
    ("wta", "wta"),
    ("golf", "golf"),
    ("masters", "golf"),
    ("ipl", "ipl"),
    ("indian premier league", "ipl"),
    ("ufc", "ufc"),
    ("mma", "ufc"),
    ("mls", "mls"),
    ("major league soccer", "mls"),
    ("formula 1", "f1"),
    ("formula one", "f1"),
    ("grand prix", "f1"),
    ("esports", "esports"),
    ("e sports", "esports"),
    ("league of legends", "esports"),
    ("valorant", "esports"),
    ("counter strike", "esports"),
]


def collect_monthly_cache(
    cache_path: str | Path,
    start: str,
    end: str,
    kalshi_historical_pages: int = 100,
    kalshi_current_pages_per_month: int = 0,
    polymarket_pages_per_month: int = 0,
    resume: bool = True,
    retry_truncated: bool = False,
) -> dict[str, Any]:
    target = Path(cache_path)
    cache = (
        read_json(target)
        if resume and target.exists()
        else {"version": 1, "kalshi_months": {}, "polymarket_months": {}}
    )
    cache.setdefault("errors", [])
    partition_root = target.parent / f"{target.stem}_partitions"
    partition_index_path = partition_root / "index.json"
    partition_index = (
        read_json(partition_index_path)
        if resume and partition_index_path.exists()
        else {"version": 1, "polymarket_months": {}, "kalshi_months": {}}
    )
    _compact_kalshi_historical_crawl(cache, target)
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    kalshi = KalshiOfficialClient()
    polymarket = PolymarketGammaClient()
    try:
        historical_cutoff = _parse_iso(kalshi.historical_cutoff()["market_settled_ts"])
    except Exception as exc:  # noqa: BLE001
        cache["errors"].append({"layer": "kalshi_historical_cutoff", "error": str(exc)})
        write_json(target, cache)
        return cache
    _compact_monthly_kalshi_slices(cache, target, historical_cutoff)
    _compact_current_kalshi_slices(cache, target, historical_cutoff)
    _crawl_kalshi_historical(cache, target, kalshi, start_dt, kalshi_historical_pages)
    for month_start, month_end in _month_slices(start_dt, end_dt):
        key = month_start.strftime("%Y-%m")
        effective_poly = partition_index["polymarket_months"].get(
            key,
            cache["polymarket_months"].get(key, {}),
        )
        if (
            not effective_poly
            or effective_poly.get("error")
            or (retry_truncated and effective_poly.get("truncated"))
        ):
            try:
                month_payload = _fetch_polymarket_month_checkpointed(
                    polymarket,
                    month_start,
                    month_end,
                    polymarket_pages_per_month,
                    partition_root / f"polymarket_{key}.json",
                    resume=resume,
                )
            except Exception as exc:  # noqa: BLE001
                month_payload = {"markets": [], "truncated": True, "error": str(exc)}
                cache["errors"].append({"layer": "polymarket_gamma", "month": key, "error": str(exc)})
            partition_index["polymarket_months"][key] = {
                "start": month_start.isoformat(),
                "end": month_end.isoformat(),
                **month_payload,
            }
            write_json(partition_index_path, partition_index)
            print(f"Checkpointed monthly Polymarket catalog {key}", flush=True)
        effective_kalshi = partition_index["kalshi_months"].get(
            key,
            cache["kalshi_months"].get(key, {}),
        )
        if (
            not effective_kalshi
            or effective_kalshi.get("error")
            or (retry_truncated and effective_kalshi.get("truncated"))
            or (
                month_start < historical_cutoff
                and not cache.get("kalshi_historical_crawl", {}).get("complete", False)
            )
        ):
            try:
                month_payload = _kalshi_month(
                    cache,
                    kalshi,
                    month_start,
                    month_end,
                    historical_cutoff,
                    kalshi_current_pages_per_month,
                )
            except Exception as exc:  # noqa: BLE001
                month_payload = {"markets": [], "truncated": True, "error": str(exc)}
                cache["errors"].append({"layer": "kalshi_catalog", "month": key, "error": str(exc)})
            partition_index["kalshi_months"][key] = {
                "start": month_start.isoformat(),
                "end": month_end.isoformat(),
                **month_payload,
            }
            write_json(partition_index_path, partition_index)
            print(f"Checkpointed monthly Kalshi catalog {key}", flush=True)
    return cache


def write_coverage_report(cache_path: str | Path, out_path: str | Path) -> dict[str, Any]:
    cache = read_json(cache_path)
    partition_index = _partition_index(cache_path)
    poly_months = {**cache.get("polymarket_months", {}), **partition_index.get("polymarket_months", {})}
    kalshi_months = {**cache.get("kalshi_months", {}), **partition_index.get("kalshi_months", {})}
    crawl = cache.get("kalshi_historical_crawl", {})
    rows = []
    for month in sorted(set(poly_months) | set(kalshi_months)):
        poly = poly_months.get(month, {})
        kalshi = kalshi_months.get(month, {})
        rows.append(
            {
                "month": month,
                "kalshi_markets": kalshi.get("market_count", len(kalshi.get("markets", []))),
                "kalshi_truncated": kalshi.get("truncated"),
                "polymarket_markets": int(poly.get("market_count") or len(poly.get("markets", []))),
                "polymarket_truncated": poly.get("truncated"),
            }
        )
    result = {
        "kalshi_historical_pages": crawl.get("pages", 0),
        "kalshi_historical_markets_fetched": crawl.get("fetched_markets", len(crawl.get("markets", []))),
        "kalshi_historical_markets_retained": len(crawl.get("markets", [])),
        "kalshi_historical_markets_skipped_out_of_scope": crawl.get("skipped_out_of_scope_markets", 0),
        "kalshi_retention_policy": crawl.get("retention_policy", KALSHI_RETENTION_POLICY),
        "kalshi_oldest_close_time_reached": crawl.get("oldest_close_time"),
        "kalshi_historical_complete": crawl.get("complete", False),
        "errors": cache.get("errors", []),
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
        f"- Kalshi historical market rows fetched while traversing the official cursor: `{result['kalshi_historical_markets_fetched']}`",
        f"- Kalshi market rows retained for the requested scenario study: `{result['kalshi_historical_markets_retained']}`",
        f"- Repetitive high-frequency rows intentionally excluded from the retained research index: `{result['kalshi_historical_markets_skipped_out_of_scope']}`",
        f"- Retention policy: {result['kalshi_retention_policy']}",
        f"- Oldest Kalshi close time reached: `{result['kalshi_oldest_close_time_reached']}`",
        f"- Full requested Kalshi history reached: `{result['kalshi_historical_complete']}`",
        f"- Persisted crawl errors: `{len(result['errors'])}`",
        "",
        "## How To Read The Caps",
        "",
        "A `False` value means the collector reached the end of that retained public catalog slice. "
        "A `True` value means the public endpoint still had another page when the configured page budget ended. "
        "The retained rows are still useful for a broad screen, but that month is not an exhaustive two-venue catalog census.",
        "",
        "The complete Kalshi historical cursor result and the monthly cap table answer different questions. "
        "The cursor result confirms that the script walked far enough backward through Kalshi history. "
        "The cap table shows whether each retained monthly cross-venue catalog slice was exhaustive.",
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
    write_json(target.with_suffix(".json"), result)
    return result


def normalize_monthly_cache(
    cache_path: str | Path,
    out_path: str | Path,
    start: str,
    end: str,
    min_score: float = 0.78,
    *,
    openai_budget_usd: float = 0.0,
    adjudication_cache_path: str | Path | None = None,
) -> dict[str, Any]:
    cache = read_json(cache_path)
    partition_index = _partition_index(cache_path)
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    historical_months = {
        **(cache.get("kalshi_months") or cache.get("kalshi_historical_months", {})),
        **partition_index.get("kalshi_months", {}),
    }
    polymarket_months = {
        **cache.get("polymarket_months", {}),
        **partition_index.get("polymarket_months", {}),
    }
    raw_poly = _dedupe(
        [
            market
            for month in polymarket_months.values()
            for market in _polymarket_month_markets(month, Path(cache_path).parent)
        ],
        "id",
    )
    raw_kalshi = _dedupe(
        [
            *[
                market
                for market in cache.get("kalshi_historical_crawl", {}).get("markets", [])
                if _in_range(market, start_dt, end_dt)
            ],
            *[
                market
                for month in historical_months.values()
                for market in month.get("markets", [])
            ],
        ],
        "ticker",
    )
    adjudicator = (
        OpenAIAdjudicator(
            adjudication_cache_path or (Path(out_path).parent / "openai_match_adjudications.json"),
            budget_usd=openai_budget_usd,
        )
        if openai_budget_usd > 0
        else None
    )
    matches, rejected = match_official_catalogs_monthly(
        raw_kalshi,
        raw_poly,
        min_score=min_score,
        checkpoint_dir=Path(out_path).parent / "annual_match_checkpoints",
        adjudicator=adjudicator,
        poly_records_cache_path=Path(out_path).parent / "annual_poly_records_v5.pkl",
    )
    kalshi_scenarios = _catalog_scenario_counts(raw_kalshi)
    polymarket_scenarios = _catalog_scenario_counts(raw_poly)
    result = {
        "meta": {
            "source": "official_kalshi_historical_months_and_recent_events_with_polymarket_gamma_catalog",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "kalshi_catalog_markets": len(raw_kalshi),
            "polymarket_catalog_markets": len(raw_poly),
            "matched_pairs": len(matches),
            "rejected_candidates": len(rejected),
            "kalshi_catalog_focus_scenarios": kalshi_scenarios["focus"],
            "kalshi_catalog_broad_scenarios": kalshi_scenarios["broad"],
            "polymarket_catalog_focus_scenarios": polymarket_scenarios["focus"],
            "polymarket_catalog_broad_scenarios": polymarket_scenarios["broad"],
            "min_score": min_score,
            "matching_gate_version": MATCHING_GATE_VERSION,
            "openai_adjudication_enabled": bool(adjudicator),
            "openai_adjudication_spent_usd": adjudicator.spent_usd if adjudicator else 0.0,
            "kalshi_historical_months": {
                key: {
                    "kalshi_markets": month.get("market_count", len(month.get("markets", []))),
                    "kalshi_truncated": month.get("truncated", False),
                }
                for key, month in sorted(historical_months.items())
            },
            "polymarket_months": {
                key: {
                    "polymarket_markets": int(month.get("market_count") or len(month.get("markets", []))),
                    "polymarket_truncated": month.get("truncated", False),
                }
                for key, month in sorted(polymarket_months.items())
            },
            "note": (
                "This is a checkpointed official-catalog screen using structured event identities. "
                "Exact-pair acceptance uses deterministic mismatch vetoes and, when enabled, cached "
                "OpenAI structured adjudication of settlement compatibility."
            ),
        },
        "matches": [asdict(match) for match in matches],
        "rejected": rejected,
    }
    write_json(out_path, result)
    return result


def _catalog_scenario_counts(markets: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    focus: Counter[str] = Counter()
    broad: Counter[str] = Counter()
    for market in markets:
        ticker_text = " ".join(
            str(market.get(key) or "").upper()
            for key in ["ticker", "event_ticker"]
        )
        ticker_hints = " ".join(
            label for prefix, label in CATALOG_TICKER_HINTS if prefix in ticker_text
        )
        text = " ".join(
            [ticker_hints]
            + [
            str(market.get(key) or "")
            for key in [
                "question",
                "title",
                "slug",
                "description",
                "ticker",
                "event_ticker",
                "yes_sub_title",
                "rules_primary",
            ]
            ]
        )
        focus_scenario = _catalog_focus_scenario(text)
        focus[focus_scenario] += 1
        broad[_catalog_broad_scenario(text, focus_scenario)] += 1
    return {"focus": dict(sorted(focus.items())), "broad": dict(sorted(broad.items()))}


def _catalog_focus_scenario(text: str) -> str:
    normalized = text.lower()
    for phrase, scenario in CATALOG_FOCUS_HINTS:
        if phrase in normalized:
            return scenario
    if any(phrase in normalized for phrase in ["election", "primary", "nominee", "midterm", "ballot"]):
        return "elections"
    if any(phrase in normalized for phrase in ["president", "senate", "governor", "congress", "minister", "mayor"]):
        return "politics"
    if any(phrase in normalized for phrase in ["weather", "temperature", "rain", "snow", "hurricane", "climate"]):
        return "weather"
    if any(
        phrase in normalized
        for phrase in [
            "oscars",
            "grammy",
            "emmy",
            "film",
            "movie",
            "album",
            "music",
            "tv",
            "eurovision",
            "streamer awards",
            "streamer of the year",
        ]
    ):
        return "culture"
    return "additional_discovered_scenario_coverage"


def _catalog_broad_scenario(text: str, focus_scenario: str) -> str:
    if focus_scenario in {
        "nba", "mlb", "golf", "atp", "wta", "esports", "ipl", "wnba", "nhl",
        "itf_men", "itf_women", "ufc", "fifa_world_cup", "mls", "f1",
    }:
        return "sports"
    if focus_scenario in {"politics", "elections"}:
        return "politics"
    if focus_scenario == "weather":
        return "weather"
    if focus_scenario == "culture":
        return "culture"
    normalized = text.lower()
    if any(phrase in normalized for phrase in ["nfl", "football", "soccer", "basketball", "baseball", "hockey", "tennis", "cricket"]):
        return "sports_additional"
    if any(phrase in normalized for phrase in ["bitcoin", "crypto", "ethereum", "stock", "fed", "inflation", "gdp"]):
        return "economics_or_crypto"
    return "additional_discovered_scenario_coverage"


def _crawl_kalshi_historical(
    cache: dict[str, Any],
    target: Path,
    client: KalshiOfficialClient,
    start: datetime,
    max_pages: int,
) -> None:
    crawl = cache.setdefault(
        "kalshi_historical_crawl",
        {
            "markets": [],
            "cursor": None,
            "complete": False,
            "pages": 0,
            "oldest_close_time": None,
            "fetched_markets": 0,
            "skipped_out_of_scope_markets": 0,
            "retention_policy": KALSHI_RETENTION_POLICY,
        },
    )
    if crawl.get("complete"):
        return
    retained_since_checkpoint = 0
    for _ in range(max_pages):
        try:
            data = client.historical_markets(limit=1000, cursor=crawl.get("cursor"))
        except Exception as exc:  # noqa: BLE001
            crawl.setdefault("errors", []).append(
                {"cursor": crawl.get("cursor"), "error": str(exc)}
            )
            cache.setdefault("errors", []).append(
                {"layer": "kalshi_historical", "cursor": crawl.get("cursor"), "error": str(exc)}
            )
            write_json(target, cache)
            break
        rows = list(data.get("markets") or [])
        trimmed_rows = [_trim_kalshi_market(item) for item in rows]
        retained_rows = [item for item in trimmed_rows if retain_kalshi_historical_market(item)]
        crawl["markets"].extend(retained_rows)
        crawl["fetched_markets"] = int(crawl.get("fetched_markets") or 0) + len(trimmed_rows)
        crawl["skipped_out_of_scope_markets"] = (
            int(crawl.get("skipped_out_of_scope_markets") or 0) + len(trimmed_rows) - len(retained_rows)
        )
        crawl["retention_policy"] = KALSHI_RETENTION_POLICY
        crawl["cursor"] = data.get("cursor")
        crawl["pages"] = int(crawl.get("pages") or 0) + 1
        row_dates = [
            _parse_iso(item["close_time"])
            for item in trimmed_rows
            if item.get("close_time")
        ]
        prior_oldest = _parse_iso(crawl["oldest_close_time"]) if crawl.get("oldest_close_time") else None
        oldest = min([*row_dates, prior_oldest] if prior_oldest else row_dates, default=None)
        crawl["oldest_close_time"] = oldest.isoformat() if oldest else None
        crawl["complete"] = bool(not rows or not crawl["cursor"] or (oldest and oldest <= start))
        retained_since_checkpoint += 1
        if retained_since_checkpoint >= KALSHI_CRAWL_CHECKPOINT_PAGES or crawl["complete"]:
            write_json(target, cache)
            retained_since_checkpoint = 0
        print(
            f"Checkpointed Kalshi historical crawl page {crawl['pages']}; "
            f"fetched={crawl['fetched_markets']}; retained={len(crawl['markets'])}; "
            f"skipped={crawl['skipped_out_of_scope_markets']}; oldest={crawl['oldest_close_time']}",
            flush=True,
        )
        if crawl["complete"]:
            break
    if retained_since_checkpoint:
        write_json(target, cache)


def retain_kalshi_historical_market(market: dict[str, Any]) -> bool:
    prefixes = {
        str(market.get("event_ticker") or "").split("-", 1)[0],
        str(market.get("ticker") or "").split("-", 1)[0],
    }
    return not bool(prefixes & EXCLUDED_HIGH_FREQUENCY_KALSHI_SERIES)


def _compact_kalshi_historical_crawl(cache: dict[str, Any], target: Path) -> None:
    crawl = cache.get("kalshi_historical_crawl")
    if not crawl or crawl.get("retention_policy") == KALSHI_RETENTION_POLICY:
        return
    markets = list(crawl.get("markets") or [])
    retained = [market for market in markets if retain_kalshi_historical_market(market)]
    skipped_now = len(markets) - len(retained)
    crawl["markets"] = retained
    crawl["fetched_markets"] = int(crawl.get("fetched_markets") or len(markets))
    crawl["skipped_out_of_scope_markets"] = int(crawl.get("skipped_out_of_scope_markets") or 0) + skipped_now
    crawl["retention_policy"] = KALSHI_RETENTION_POLICY
    write_json(target, cache)
    print(
        "Compacted retained Kalshi historical research index; "
        f"fetched={crawl['fetched_markets']}; retained={len(retained)}; "
        f"skipped={crawl['skipped_out_of_scope_markets']}",
        flush=True,
    )


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
        return {
            "markets": [],
            "market_count": len(markets),
            "source": "kalshi_historical_crawl_index",
            "truncated": not crawl.get("complete", False),
        }
    return _fetch_kalshi_current_month(client, start, end, max_pages)


def _fetch_kalshi_current_month(
    client: KalshiOfficialClient,
    start: datetime,
    end: datetime,
    max_pages: int,
) -> dict[str, Any]:
    markets = []
    fetched_markets = 0
    skipped_out_of_scope_markets = 0
    truncated = False
    cursor = None
    page = 0
    while max_pages in {None, 0} or page < max_pages:
        data = client.markets(
            limit=1000,
            cursor=cursor,
            min_close_ts=int(start.timestamp()),
            max_close_ts=int(end.timestamp()),
        )
        rows = list(data.get("markets") or [])
        trimmed_rows = [_trim_kalshi_market(item) for item in rows]
        retained_rows = [item for item in trimmed_rows if retain_kalshi_historical_market(item)]
        fetched_markets += len(trimmed_rows)
        skipped_out_of_scope_markets += len(trimmed_rows) - len(retained_rows)
        markets.extend(retained_rows)
        cursor = data.get("cursor")
        if not cursor or not rows:
            break
        page += 1
        if max_pages not in {None, 0} and page == max_pages:
            truncated = True
    return {
        "markets": markets,
        "market_count": len(markets),
        "fetched_markets": fetched_markets,
        "skipped_out_of_scope_markets": skipped_out_of_scope_markets,
        "retention_policy": KALSHI_RETENTION_POLICY,
        "truncated": truncated,
    }


def _fetch_polymarket_month_checkpointed(
    client: PolymarketGammaClient,
    start: datetime,
    end: datetime,
    max_pages: int,
    checkpoint_path: Path,
    *,
    resume: bool,
) -> dict[str, Any]:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    state = (
        read_json(checkpoint_path)
        if resume and checkpoint_path.exists()
        else {
            "version": 1,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "cursor": None,
            "pages": 0,
            "markets": [],
            "complete": False,
        }
    )
    if state.get("complete"):
        return {
            "markets": [],
            "market_count": len(state.get("markets") or []),
            "pages": state.get("pages", 0),
            "truncated": False,
            "complete": True,
            "partition_path": str(checkpoint_path.resolve()),
        }
    pages_this_run = 0
    while max_pages in {0, None} or pages_this_run < max_pages:
        data = client.market_page(
            start.isoformat(),
            end.isoformat(),
            cursor=state.get("cursor"),
            limit=100,
        )
        rows = list(data.get("markets") or [])
        state["markets"].extend(_trim_poly_market(item) for item in rows)
        state["cursor"] = data.get("next_cursor")
        state["pages"] = int(state.get("pages") or 0) + 1
        pages_this_run += 1
        state["complete"] = bool(not rows or not state["cursor"])
        if state["pages"] % 100 == 0 or state["complete"]:
            write_json(checkpoint_path, state)
            print(
                f"Checkpointed Polymarket {start:%Y-%m} page {state['pages']}; "
                f"markets={len(state['markets'])}",
                flush=True,
            )
        if state["complete"]:
            break
    if not state["complete"]:
        write_json(checkpoint_path, state)
    return {
        "markets": [],
        "market_count": len(state["markets"]),
        "pages": state["pages"],
        "truncated": not state["complete"],
        "complete": state["complete"],
        "partition_path": str(checkpoint_path.resolve()),
    }


def _polymarket_month_markets(month: dict[str, Any], cache_parent: Path) -> list[dict[str, Any]]:
    if month.get("markets"):
        return list(month["markets"])
    partition = month.get("partition_path")
    if not partition:
        return []
    path = Path(partition)
    if not path.is_absolute():
        path = cache_parent / path
    return list((read_json(path).get("markets") or [])) if path.exists() else []


def _compact_monthly_kalshi_slices(
    cache: dict[str, Any],
    target: Path,
    historical_cutoff: datetime,
) -> None:
    changed = False
    for month in cache.get("kalshi_months", {}).values():
        if _parse_iso(month["start"]) >= historical_cutoff:
            continue
        markets = list(month.get("markets") or [])
        if not markets:
            continue
        month["market_count"] = len(markets)
        month["markets"] = []
        month["source"] = "kalshi_historical_crawl_index"
        changed = True
    if changed:
        print("Compacted duplicated historical Kalshi monthly row bodies in memory.", flush=True)


def _compact_current_kalshi_slices(
    cache: dict[str, Any],
    target: Path,
    historical_cutoff: datetime,
) -> None:
    changed = False
    for month in cache.get("kalshi_months", {}).values():
        if _parse_iso(month["start"]) < historical_cutoff or month.get("retention_policy"):
            continue
        markets = list(month.get("markets") or [])
        retained = [market for market in markets if retain_kalshi_historical_market(market)]
        month["markets"] = retained
        month["market_count"] = len(retained)
        month["fetched_markets"] = int(month.get("fetched_markets") or len(markets))
        month["skipped_out_of_scope_markets"] = (
            int(month.get("skipped_out_of_scope_markets") or 0) + len(markets) - len(retained)
        )
        month["retention_policy"] = KALSHI_RETENTION_POLICY
        changed = True
    if changed:
        print("Compacted current Kalshi monthly row bodies in memory.", flush=True)


def _partition_index(cache_path: str | Path) -> dict[str, Any]:
    target = Path(cache_path)
    path = target.parent / f"{target.stem}_partitions" / "index.json"
    return read_json(path) if path.exists() else {"polymarket_months": {}, "kalshi_months": {}}


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
    parser.add_argument("--retry-truncated", action="store_true")
    args = parser.parse_args()
    if args.collect:
        collect_monthly_cache(
            args.cache,
            args.start,
            args.end,
            kalshi_historical_pages=args.kalshi_historical_pages,
            kalshi_current_pages_per_month=args.kalshi_current_pages_per_month,
            polymarket_pages_per_month=args.polymarket_pages_per_month,
            retry_truncated=args.retry_truncated,
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
