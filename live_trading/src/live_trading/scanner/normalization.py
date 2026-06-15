from __future__ import annotations

import re
from datetime import datetime

from ..models import VenueMarket


STOPWORDS = {
    "a", "an", "at", "by", "for", "from", "in", "market", "no", "of",
    "on", "the", "to", "versus", "vs", "will", "win", "winner", "wins", "yes",
}

TEAM_ALIASES = {
    "atlanta hawks": "atlanta_hawks", "hawks": "atlanta_hawks", "atl": "atlanta_hawks",
    "boston celtics": "boston_celtics", "celtics": "boston_celtics", "bos": "boston_celtics",
    "brooklyn nets": "brooklyn_nets", "nets": "brooklyn_nets", "bkn": "brooklyn_nets",
    "charlotte hornets": "charlotte_hornets", "hornets": "charlotte_hornets", "cha": "charlotte_hornets",
    "chicago bulls": "chicago_bulls", "bulls": "chicago_bulls", "chi": "chicago_bulls",
    "cleveland cavaliers": "cleveland_cavaliers", "cavaliers": "cleveland_cavaliers", "cavs": "cleveland_cavaliers",
    "dallas mavericks": "dallas_mavericks", "mavericks": "dallas_mavericks", "mavs": "dallas_mavericks", "dal": "dallas_mavericks",
    "denver nuggets": "denver_nuggets", "nuggets": "denver_nuggets", "den": "denver_nuggets",
    "detroit pistons": "detroit_pistons", "pistons": "detroit_pistons", "det": "detroit_pistons",
    "golden state warriors": "golden_state_warriors", "warriors": "golden_state_warriors", "gsw": "golden_state_warriors",
    "houston rockets": "houston_rockets", "rockets": "houston_rockets", "hou": "houston_rockets",
    "indiana pacers": "indiana_pacers", "pacers": "indiana_pacers", "ind": "indiana_pacers",
    "los angeles clippers": "la_clippers", "la clippers": "la_clippers", "clippers": "la_clippers", "lac": "la_clippers",
    "los angeles lakers": "la_lakers", "la lakers": "la_lakers", "lakers": "la_lakers", "lal": "la_lakers",
    "memphis grizzlies": "memphis_grizzlies", "grizzlies": "memphis_grizzlies", "mem": "memphis_grizzlies",
    "miami heat": "miami_heat", "heat": "miami_heat", "mia": "miami_heat",
    "milwaukee bucks": "milwaukee_bucks", "bucks": "milwaukee_bucks", "mil": "milwaukee_bucks",
    "minnesota timberwolves": "minnesota_timberwolves", "timberwolves": "minnesota_timberwolves", "wolves": "minnesota_timberwolves", "min": "minnesota_timberwolves",
    "new orleans pelicans": "new_orleans_pelicans", "pelicans": "new_orleans_pelicans", "nop": "new_orleans_pelicans",
    "new york knicks": "new_york_knicks", "knicks": "new_york_knicks", "nyk": "new_york_knicks",
    "oklahoma city thunder": "oklahoma_city_thunder", "thunder": "oklahoma_city_thunder", "okc": "oklahoma_city_thunder",
    "orlando magic": "orlando_magic", "magic": "orlando_magic", "orl": "orlando_magic",
    "philadelphia 76ers": "philadelphia_76ers", "76ers": "philadelphia_76ers", "sixers": "philadelphia_76ers", "phi": "philadelphia_76ers",
    "phoenix suns": "phoenix_suns", "suns": "phoenix_suns", "phx": "phoenix_suns",
    "portland trail blazers": "portland_trail_blazers", "trail blazers": "portland_trail_blazers", "blazers": "portland_trail_blazers", "por": "portland_trail_blazers",
    "sacramento kings": "sacramento_kings", "kings": "sacramento_kings", "sac": "sacramento_kings",
    "san antonio spurs": "san_antonio_spurs", "spurs": "san_antonio_spurs", "sas": "san_antonio_spurs",
    "toronto raptors": "toronto_raptors", "raptors": "toronto_raptors", "tor": "toronto_raptors",
    "utah jazz": "utah_jazz", "jazz": "utah_jazz", "uta": "utah_jazz",
    "washington wizards": "washington_wizards", "wizards": "washington_wizards", "was": "washington_wizards",
    "philadelphia": "philadelphia_76ers",
    "dallas": "dallas_mavericks",
    "boston": "boston_celtics",
    "phoenix": "phoenix_suns",
}


def normalize_text(value: str | None) -> str:
    text = (value or "").casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s.:-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for alias in sorted(TEAM_ALIASES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(alias)}\b", TEAM_ALIASES[alias], text)
    return text


def token_set(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", normalize_text(value))
        if token not in STOPWORDS
    }


def market_signature(market: VenueMarket) -> str:
    return normalize_text(
        " ".join(
            filter(
                None,
                (
                    market.title,
                    market.description,
                    market.yes_label,
                    market.category,
                    market.market_type,
                    str(market.raw.get("event_title") or ""),
                    str(market.raw.get("series_title") or ""),
                ),
            )
        )
    )


def event_title(market: VenueMarket) -> str:
    raw = market.raw
    return str(
        raw.get("event_title")
        or raw.get("series_title")
        or raw.get("eventName")
        or raw.get("event_name")
        or market.description
        or market.title
    )


def comparable_time(market: VenueMarket) -> datetime | None:
    return market.start_time or market.close_time or market.expiration_time


def outcome_tokens(market: VenueMarket) -> set[str]:
    label = market.yes_label
    if label.casefold() in {"yes", "true", ""}:
        label = str(market.raw.get("yes_sub_title") or market.title)
    result = token_set(label)
    title_tokens = token_set(market.title)
    canonical_teams = {token for token in title_tokens if "_" in token}
    return result | canonical_teams
