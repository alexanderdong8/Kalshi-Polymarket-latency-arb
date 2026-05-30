from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any


POPULAR_SPORTS = {
    "nba",
    "nfl",
    "mlb",
    "nhl",
    "fifa",
    "world cup",
    "soccer",
    "football",
    "basketball",
    "baseball",
    "hockey",
    "ufc",
    "tennis",
    "formula 1",
    "f1",
}

SPORTS_WORDS = POPULAR_SPORTS | {
    "golf",
    "cricket",
    "rugby",
    "chess",
    "cycling",
    "nascar",
    "mma",
    "boxing",
    "wnba",
}

POLITICS_WORDS = {
    "election",
    "president",
    "senate",
    "governor",
    "nominee",
    "primary",
    "congress",
    "mayor",
    "minister",
    "party",
    "leader",
}

ECON_WORDS = {
    "fed",
    "rate",
    "cpi",
    "inflation",
    "gdp",
    "recession",
    "unemployment",
    "earnings",
    "ipo",
    "stock",
    "bitcoin",
    "crypto",
}


def classify_domain(title: str, category: str | None = None, tags: list[str] | None = None) -> str:
    haystack = _norm(" ".join([title, category or "", " ".join(tags or [])]))
    if any(word in haystack for word in SPORTS_WORDS):
        if any(word in haystack for word in POPULAR_SPORTS):
            return "sports_popular"
        return "sports_other"
    if any(word in haystack for word in POLITICS_WORDS):
        return "politics"
    if any(word in haystack for word in ECON_WORDS):
        return "economics_crypto"
    if any(word in haystack for word in ["movie", "album", "oscars", "avengers", "tv", "music"]):
        return "entertainment"
    return "other"


def classify_phase(
    title: str,
    scan_start: str,
    resolution_date: str | None,
    aligned_state_count: int,
    best_gross_edge: float | None,
    median_window_seconds: float | None,
) -> str:
    start_dt = _parse_hour(scan_start)
    resolution_dt = _parse_iso(resolution_date) if resolution_date else None
    hours_to_resolution = None
    if resolution_dt:
        hours_to_resolution = (resolution_dt - start_dt).total_seconds() / 3600

    haystack = _norm(title)
    game_like = any(word in haystack for word in [" game ", " at ", "match", "round", "finals", "winner"])
    high_activity = aligned_state_count >= 600
    fast_windows = median_window_seconds is not None and median_window_seconds <= 1.0
    large_intra_hour_gap = best_gross_edge is not None and best_gross_edge >= 0.05

    if hours_to_resolution is not None and 0 <= hours_to_resolution <= 8:
        return "near_resolution_or_in_play"
    if game_like and (high_activity or fast_windows or large_intra_hour_gap):
        return "active_like_high_volatility"
    if hours_to_resolution is not None and hours_to_resolution > 24:
        return "pre_event_or_slow"
    return "unknown_phase"


def summarize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["domain"], record["phase"])].append(record)

    summaries = []
    for (domain, phase), items in grouped.items():
        net_markets = [item for item in items if item.get("net_positive_windows", 0) > 0]
        best_net_values = [item["best_net_edge_per_contract"] for item in items if item.get("best_net_edge_per_contract") is not None]
        summaries.append(
            {
                "domain": domain,
                "phase": phase,
                "markets": len(items),
                "markets_with_net_positive_windows": len(net_markets),
                "net_positive_windows": sum(item.get("net_positive_windows", 0) for item in items),
                "gross_positive_windows": sum(item.get("gross_positive_windows", 0) for item in items),
                "median_best_net_edge": median(best_net_values) if best_net_values else None,
                "mean_best_net_edge": mean(best_net_values) if best_net_values else None,
                "max_best_net_edge": max(best_net_values) if best_net_values else None,
            }
        )
    return sorted(
        summaries,
        key=lambda item: (item["net_positive_windows"], item["max_best_net_edge"] or -999),
        reverse=True,
    )


def _norm(value: str) -> str:
    return " " + re.sub(r"\s+", " ", value.lower()) + " "


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_hour(value: str) -> datetime:
    if len(value) == 13:
        value = f"{value}:00:00+00:00"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
