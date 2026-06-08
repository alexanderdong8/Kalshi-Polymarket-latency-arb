from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .scenario import classify_focus_scenario, scenario_metadata
from .serde import read_json, write_json


POLYMARKET_US_GATEWAY = "https://gateway.polymarket.us"


class PolymarketUSPublicClient:
    def __init__(self, base_url: str = POLYMARKET_US_GATEWAY, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def page(self, path: str, *, limit: int, offset: int, **params: Any) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.base_url}{path}",
            params={"limit": limit, "offset": offset, **params},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        key = "events" if path == "/v1/events" else "markets"
        return list(payload.get(key) or [])

    def sports(self) -> list[dict[str, Any]]:
        response = self.session.get(f"{self.base_url}/v1/sports", timeout=self.timeout)
        response.raise_for_status()
        return list(response.json().get("sports") or [])

    def book(self, slug: str) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/v1/markets/{slug}/book", timeout=self.timeout)
        response.raise_for_status()
        return dict(response.json().get("marketData") or {})

    def settlement(self, slug: str) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/v1/markets/{slug}/settlement", timeout=self.timeout)
        response.raise_for_status()
        return dict(response.json())


def collect_public_us_catalog(
    cache_path: str | Path,
    *,
    resume: bool = True,
    page_size: int = 250,
    max_pages: int | None = None,
    terminal_summary_limit: int = 0,
    client: PolymarketUSPublicClient | None = None,
) -> dict[str, Any]:
    target = Path(cache_path)
    cache = read_json(target) if resume and target.exists() else {"version": 1}
    api = client or PolymarketUSPublicClient()
    cache.setdefault("sports", api.sports())
    crawl = cache.setdefault("crawl", {})
    cache["events"] = _crawl_resume(
        cache,
        crawl,
        "events",
        api,
        "/v1/events",
        page_size,
        max_pages,
        target,
    )
    cache["open_markets"] = _crawl_resume(
        cache,
        crawl,
        "open_markets",
        api,
        "/v1/markets",
        page_size,
        max_pages,
        target,
        closed="false",
        includeHidden="true",
    )
    cache["closed_markets"] = _crawl_resume(
        cache,
        crawl,
        "closed_markets",
        api,
        "/v1/markets",
        page_size,
        max_pages,
        target,
        closed="true",
        includeHidden="true",
    )
    cache.setdefault("terminal_summaries", {})
    if terminal_summary_limit > 0:
        retained_since_checkpoint = 0
        for market in cache["closed_markets"][:terminal_summary_limit]:
            slug = str(market.get("slug") or "")
            if not slug or slug in cache["terminal_summaries"]:
                continue
            try:
                cache["terminal_summaries"][slug] = {
                    "book": api.book(slug),
                    "settlement": api.settlement(slug),
                }
            except Exception as exc:  # noqa: BLE001
                cache["terminal_summaries"][slug] = {"error": str(exc)}
            retained_since_checkpoint += 1
            if retained_since_checkpoint >= 10:
                write_json(target, cache)
                retained_since_checkpoint = 0
    cache["collected_at"] = datetime.now(timezone.utc).isoformat()
    write_json(target, cache)
    return cache


def summarize_public_us_catalog(cache: dict[str, Any]) -> dict[str, Any]:
    events = list(cache.get("events") or [])
    embedded_markets = [market for event in events for market in event.get("markets") or []]
    unique_markets = {str(market.get("slug") or market.get("id")): market for market in embedded_markets}
    scenario_events = Counter(classify_focus_scenario(_event_text(event), event.get("category")) for event in events)
    scenario_markets = Counter(
        classify_focus_scenario(_market_text(market), market.get("category"))
        for market in unique_markets.values()
    )
    type_counts = Counter(
        str(market.get("sportsMarketTypeV2") or market.get("sportsMarketType") or market.get("marketType") or "unspecified")
        for market in unique_markets.values()
    )
    scenarios = []
    for scenario in sorted(set(scenario_events) | set(scenario_markets)):
        scenarios.append(
            {
                "scenario": scenario,
                "events": scenario_events[scenario],
                "markets": scenario_markets[scenario],
            }
        )
    return {
        "source": "polymarket_us_public_gateway",
        "collected_at": cache.get("collected_at"),
        "events": len(events),
        "embedded_markets": len(embedded_markets),
        "unique_embedded_markets": len(unique_markets),
        "open_flat_markets": len(cache.get("open_markets") or []),
        "closed_flat_markets": len(cache.get("closed_markets") or []),
        "sports_configurations": len(cache.get("sports") or []),
        "terminal_summaries_collected": len(cache.get("terminal_summaries") or {}),
        "crawl_status": cache.get("crawl", {}),
        "event_categories": dict(Counter(str(event.get("category") or "unspecified") for event in events)),
        "market_types": dict(type_counts),
        "scenarios": scenarios,
        "earliest_event_created_at": _date_bound(events, "createdAt", min),
        "latest_event_created_at": _date_bound(events, "createdAt", max),
        "limitations": [
            "The public Polymarket US gateway exposes catalog metadata, current books, BBO, settlement, and terminal summaries.",
            "It does not expose public historical quote-by-quote BBO, historical L2 depth, or public historical candles.",
            "This report is descriptive catalog research. It must not be read as a retrospective arbitrage-profit report.",
        ],
    }


def write_public_us_report(summary: dict[str, Any], out_path: str | Path, manifest_path: str) -> None:
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Polymarket US Public Catalog Analysis",
        "",
        "This report describes the Polymarket US data that is publicly reachable without institutional report credentials. "
        "It intentionally does not claim historical arbitrage profitability.",
        "",
        f"Coverage manifest: [{manifest_path}]({manifest_path})",
        "",
        "## What This Report Is For",
        "",
        "Polymarket US exposes a public catalog that is useful for understanding which categories and contract types exist. "
        "The public gateway does not provide the historical quote-by-quote order books needed to replay old trades. "
        "For that reason, this file is a catalog census, not a profit ranking.",
        "",
        "## Terms",
        "",
        "- **Event**: the real-world question or sporting contest that groups one or more tradable contracts.",
        "- **Embedded market**: a tradable contract included inside an event response. One event can contain several embedded markets.",
        "- **Flat market**: the same kind of tradable contract returned directly from the markets endpoint instead of nested inside an event.",
        "- **Open market**: a market currently available for trading.",
        "- **Closed market**: a market no longer open for new trading.",
        "- **Sports configuration**: public metadata describing supported sports structures and market types.",
        "- **Terminal summary**: a retained public end-state summary for a market. It is not a historical timeline of earlier prices.",
        "- **Crawl checkpoint**: a saved progress marker. It allows the script to resume catalog collection instead of starting over.",
        "",
        "## Public Coverage",
        "",
        f"- Events: `{summary['events']}`",
        f"- Unique embedded markets: `{summary['unique_embedded_markets']}`",
        f"- Currently open flat markets: `{summary['open_flat_markets']}`",
        f"- Retained closed flat markets: `{summary['closed_flat_markets']}`",
        f"- Sports configurations: `{summary['sports_configurations']}`",
        f"- Terminal summaries collected in this run: `{summary['terminal_summaries_collected']}`",
        f"- Earliest retained event creation timestamp: `{summary['earliest_event_created_at']}`",
        "",
        "## Crawl Checkpoints",
        "",
        "| Collection | Pages retained | Next offset | Complete | Truncated in last run | Errors |",
        "|---|---:|---:|---|---|---:|",
    ]
    for key, state in sorted(summary.get("crawl_status", {}).items()):
        lines.append(
            f"| `{key}` | {state.get('pages', 0)} | {state.get('next_offset', 0)} "
            f"| {state.get('complete', False)} | {state.get('truncated_for_this_run', False)} "
            f"| {len(state.get('errors') or [])} |"
        )
    lines.extend(
        [
        "",
        "## Scenario Inventory",
        "",
        "| Scenario | Events | Embedded markets |",
        "|---|---:|---:|",
        ]
    )
    for row in sorted(summary["scenarios"], key=lambda item: item["markets"], reverse=True):
        lines.append(f"| `{row['scenario']}` | {row['events']} | {row['markets']} |")
    lines.extend(["", "## Market Types", "", "| Type | Markets |", "|---|---:|"])
    for market_type, count in sorted(summary["market_types"].items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| `{market_type}` | {count} |")
    lines.extend(
        [
            "",
            "The sports-market labels mean:",
            "",
            "- **Moneyline**: which team or participant wins.",
            "- **Total**: whether a combined score is above or below a stated number.",
            "- **Spread**: whether a team wins after applying a stated points or goals handicap.",
            "- **Future**: a longer-horizon result, such as a tournament winner.",
            "- **Prop**: a narrower outcome, such as a player statistic.",
            "- **Drawable outcome**: a contract where a tie or draw is a possible result.",
            "- **Unspecified**: the public metadata did not provide a more precise sports-market type.",
        ]
    )
    lines.extend(["", "## Evidence Limits", ""])
    lines.extend(f"- {item}" for item in summary["limitations"])
    target.write_text("\n".join(lines), encoding="utf-8")


def enrich_public_us_market(market: dict[str, Any]) -> dict[str, Any]:
    return {**market, "scenario": scenario_metadata(_market_text(market), market.get("category"), market_type=market.get("marketType"))}


def _crawl_resume(
    cache: dict[str, Any],
    crawl: dict[str, Any],
    key: str,
    client: PolymarketUSPublicClient,
    path: str,
    page_size: int,
    max_pages: int | None,
    target: Path,
    **params: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = list(cache.get(key) or [])
    state = crawl.setdefault(
        key,
        {
            "pages": len(rows) // page_size,
            "next_offset": len(rows),
            "complete": False,
            "errors": [],
        },
    )
    pages_this_run = 0
    while not state.get("complete") and (max_pages is None or pages_this_run < max_pages):
        try:
            batch = client.page(path, limit=page_size, offset=int(state["next_offset"]), **params)
        except Exception as exc:  # noqa: BLE001
            state.setdefault("errors", []).append(
                {
                    "offset": state.get("next_offset"),
                    "error": str(exc),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            write_json(target, cache)
            break
        if not batch:
            state["complete"] = True
            break
        rows.extend(batch)
        state["pages"] = int(state.get("pages") or 0) + 1
        state["next_offset"] = int(state.get("next_offset") or 0) + len(batch)
        cache[key] = rows
        pages_this_run += 1
        if len(batch) < page_size:
            state["complete"] = True
            write_json(target, cache)
            break
        write_json(target, cache)
    state["truncated_for_this_run"] = bool(not state.get("complete"))
    cache[key] = rows
    return rows


def _event_text(event: dict[str, Any]) -> str:
    return " ".join(str(event.get(key) or "") for key in ["title", "description", "seriesSlug", "ticker"])


def _market_text(market: dict[str, Any]) -> str:
    return " ".join(str(market.get(key) or "") for key in ["question", "title", "description", "slug"])


def _date_bound(rows: list[dict[str, Any]], key: str, fn) -> str | None:
    values = [str(row.get(key)) for row in rows if row.get(key)]
    return fn(values) if values else None
