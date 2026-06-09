from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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
    "pga",
    "pga tour",
    "masters",
    "cricket",
    "rugby",
    "chess",
    "cycling",
    "nascar",
    "mma",
    "boxing",
    "wnba",
    "atp",
    "wta",
    "itf",
    "ipl",
    "esports",
    "e sports",
    "league of legends",
    "valorant",
    "counter strike",
    "cs2",
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

CULTURE_WORDS = {
    "culture",
    "oscars",
    "grammy",
    "grammys",
    "movie",
    "album",
    "film independent",
    "spirit awards",
    "emmy",
    "golden globe",
    "bafta",
    "music",
    "tv",
    "met gala",
    "eurovision",
    "streamer awards",
    "streamer of the year",
}

SPORT_SUBCATEGORY_WORDS = [
    ("sports_basketball", {"basketball", "nba", "wnba", "ncaa", "euroleague"}),
    ("sports_tennis", {"tennis", "atp", "wta", "wimbledon", "roland garros", "us open"}),
    ("sports_motorsport", {"formula 1", "formula one", "f1", "nascar", "indycar", "grand prix"}),
    ("sports_baseball", {"baseball", "mlb", "world series"}),
    ("sports_american_football", {"nfl", "super bowl", "american football"}),
    ("sports_soccer", {"soccer", "premier league", "champions league", "world cup", "uefa", "fifa"}),
    ("sports_hockey", {"hockey", "nhl", "stanley cup"}),
    ("sports_mma_boxing", {"ufc", "mma", "boxing"}),
    ("sports_golf", {"golf", "pga", "masters"}),
    ("sports_cricket", {"cricket"}),
    ("sports_chess", {"chess"}),
]

FOCUS_SCENARIO_WORDS = [
    ("wnba", {"wnba"}),
    ("nba", {"nba"}),
    ("mlb", {"mlb", "major league baseball"}),
    ("itf_men", {"itf men", "itfm"}),
    ("itf_women", {"itf women", "itfw"}),
    ("atp", {"atp"}),
    ("wta", {"wta"}),
    ("golf", {"golf", "pga", "masters"}),
    ("ipl", {"ipl", "indian premier league"}),
    ("nhl", {"nhl", "stanley cup"}),
    ("ufc", {"ufc", "mma"}),
    ("fifa_world_cup", {"fifa world cup", "men s world cup"}),
    ("mls", {"mls", "major league soccer"}),
    ("f1", {"formula 1", "formula one", "f1", "grand prix"}),
    ("esports", {"esports", "e sports", "league of legends", "valorant", "counter strike", "cs2", "dota", "call of duty"}),
]


def classify_domain(title: str, category: str | None = None, tags: list[str] | None = None) -> str:
    haystack = _norm(" ".join([title, category or "", " ".join(tags or [])]))
    if _contains_any(haystack, CULTURE_WORDS):
        return "entertainment"
    if _contains_any(haystack, SPORTS_WORDS):
        if _contains_any(haystack, POPULAR_SPORTS):
            return "sports_popular"
        return "sports_other"
    if _contains_any(haystack, POLITICS_WORDS):
        return "politics"
    if _contains_any(haystack, ECON_WORDS):
        return "economics_crypto"
    return "other"


def classify_scenario(title: str, category: str | None = None, tags: list[str] | None = None) -> str:
    haystack = _norm(" ".join([title, category or "", " ".join(tags or [])]))
    domain = classify_domain(title, category, tags)
    if domain.startswith("sports_"):
        for label, words in SPORT_SUBCATEGORY_WORDS:
            if _contains_any(haystack, words):
                return label
        return "sports_other"
    if domain == "politics":
        if _contains_any(haystack, ["election", "primary", "nominee", "president", "senate", "governor", "mayor"]):
            return "politics_elections"
        return "politics_other"
    if domain == "economics_crypto":
        if _contains_any(haystack, ["bitcoin", "crypto", "ethereum", "solana", "doge"]):
            return "crypto"
        if _contains_any(haystack, ["fed", "rate", "cpi", "inflation", "gdp", "unemployment", "jobs"]):
            return "economics_macro"
        return "economics_financial"
    return domain


def classify_focus_scenario(title: str, category: str | None = None, tags: list[str] | None = None) -> str:
    haystack = _norm(" ".join([title, category or "", " ".join(tags or [])]))
    if _contains_any(haystack, CULTURE_WORDS):
        return "culture"
    for label, words in FOCUS_SCENARIO_WORDS:
        if _contains_any(haystack, words):
            return label
    if _contains_any(haystack, ["election", "primary", "nominee", "midterm", "ballot"]):
        return "elections"
    if _contains_any(haystack, POLITICS_WORDS):
        return "politics"
    if _contains_any(haystack, ["weather", "temperature", "rain", "snow", "hurricane", "climate"]):
        return "weather"
    return "additional_discovered_scenario_coverage"


def classify_market_type(title: str, market_type: str | None = None) -> str:
    haystack = _norm(" ".join([title, market_type or ""]))
    if " spread " in f" {haystack} " or " cover " in f" {haystack} " or re.search(
        r"(?<!\w)[+-]\d+(?:\.\d+)?(?!\w)", haystack
    ):
        return "spread"
    if any(word in haystack for word in [" total ", " over ", " under ", "above", "below"]):
        return "total_or_threshold"
    if any(word in haystack for word in [" prop ", "points", "rebounds", "assists", "goals", "home runs"]):
        return "prop"
    if any(word in haystack for word in ["future", "champion", "mvp", "win the", "winner"]):
        return "future_or_winner"
    return "moneyline_or_binary"


def classify_competition_phase(title: str) -> str:
    haystack = _norm(title)
    phase_markers = (
        ("world_series", ("world series",)),
        ("league_finals", ("nba finals", "wnba finals", "stanley cup final", "mls cup")),
        ("conference_final", ("conference final", "championship series", "alcs", "nlcs")),
        ("semifinal", ("semifinal", "semi final")),
        ("division_series", ("division series", "alds", "nlds")),
        ("quarterfinal", ("quarterfinal", "quarter final")),
        ("wild_card", ("wild card", "wildcard")),
        ("play_in", ("play in", "play-in")),
        ("first_round", ("first round", "round 1")),
        ("round_of_16", ("round of 16",)),
        ("round_of_32", ("round of 32",)),
        ("final_or_championship", (" final ", " finals ", "championship")),
        ("playoffs_or_knockout", ("playoff", "postseason", "knockout")),
    )
    padded = f" {haystack.strip()} "
    for label, markers in phase_markers:
        if any(marker in padded for marker in markers):
            return label
    if any(word in haystack for word in ["qualifier", "qualification", "group stage"]):
        return "qualification_or_group"
    return "regular_season_or_unspecified"


def classify_tournament_level(title: str) -> str:
    haystack = _norm(title)
    if any(item in haystack for item in ["australian open", "roland garros", "french open", "wimbledon", "us open"]):
        return "grand_slam"
    if any(item in haystack for item in ["atp finals", "wta finals"]):
        return "tour_finals"
    if re.search(r"\b(?:atp|wta)\s*1000\b", haystack) or "masters 1000" in haystack:
        return "masters_1000"
    if re.search(r"\b(?:atp|wta)\s*500\b", haystack):
        return "tour_500"
    if re.search(r"\b(?:atp|wta)\s*250\b", haystack):
        return "tour_250"
    if "itf" in haystack:
        return "itf"
    if "title fight" in haystack or "championship bout" in haystack:
        return "title_fight"
    if "main event" in haystack:
        return "main_event"
    if "main card" in haystack:
        return "main_card"
    if "prelim" in haystack:
        return "prelim"
    if "qualifying" in haystack:
        return "qualifying"
    if "sprint" in haystack:
        return "sprint"
    if "practice" in haystack:
        return "practice"
    if "grand prix" in haystack or re.search(r"\bf1\b", haystack):
        return "race_or_f1_unspecified"
    return "not_applicable_or_unspecified"


def scenario_metadata(
    title: str,
    category: str | None = None,
    tags: list[str] | None = None,
    market_type: str | None = None,
) -> dict[str, str]:
    return {
        "focus_scenario": classify_focus_scenario(title, category, tags),
        "broad_scenario": classify_scenario(title, category, tags),
        "domain": classify_domain(title, category, tags),
        "market_type": classify_market_type(title, market_type),
        "competition_phase": classify_competition_phase(title),
        "tournament_level": classify_tournament_level(title),
    }


def classify_lifecycle_phase(
    timestamp: datetime,
    resolution: datetime | None,
    *,
    is_sports: bool,
    event_start: datetime | None = None,
) -> str:
    current = timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    close = (
        resolution.astimezone(timezone.utc)
        if resolution and resolution.tzinfo
        else resolution.replace(tzinfo=timezone.utc) if resolution else None
    )
    start = (
        event_start.astimezone(timezone.utc)
        if event_start and event_start.tzinfo
        else event_start.replace(tzinfo=timezone.utc) if event_start else None
    )
    if is_sports:
        if start is not None:
            return "sports_in_play_or_post_start" if current >= start else "sports_pregame"
        if close is not None and timedelta(hours=0) <= close - current <= timedelta(hours=4):
            return "sports_near_close_in_play_proxy"
        return "sports_pregame_or_unspecified"
    if close is None:
        return "lifecycle_unspecified"
    remaining = close - current
    if remaining <= timedelta(hours=24):
        return "lifecycle_final_24h"
    if remaining <= timedelta(days=30):
        return "lifecycle_30d_to_24h"
    return "lifecycle_more_than_30d"


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


def _contains_any(haystack: str, phrases) -> bool:
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", haystack)
        for phrase in phrases
    )


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    fractional = re.match(r"^(.*?\.)(\d+)([+-]\d{2}:\d{2})?$", normalized)
    if fractional:
        prefix, digits, offset = fractional.groups()
        normalized = f"{prefix}{digits[:6].ljust(6, '0')}{offset or ''}"
    return datetime.fromisoformat(normalized)


def _parse_hour(value: str) -> datetime:
    if len(value) == 13:
        value = f"{value}:00:00+00:00"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
