from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .scenario import classify_focus_scenario, classify_market_type


def _norm(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.+-]+", " ", ascii_value.lower())).strip()


MATCHUP_PATTERNS = (
    re.compile(r"^(.+?)\s+(?:at|@)\s+(.+?)(?:\s+winner)?[?]?$", re.I),
    re.compile(r"^(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:\s+winner)?[?]?$", re.I),
)


def _aliases(*groups: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in groups:
        canonical = _norm(group[0])
        for item in group:
            out[_norm(item)] = canonical
    return out


TEAM_ALIASES = _aliases(
    # NBA
    ("atlanta hawks", "atlanta", "hawks", "atl"),
    ("boston celtics", "boston", "celtics", "bos"),
    ("brooklyn nets", "brooklyn", "nets", "bkn"),
    ("charlotte hornets", "charlotte", "hornets", "cha"),
    ("chicago bulls", "chicago", "bulls", "chi"),
    ("cleveland cavaliers", "cleveland", "cavaliers", "cavs", "cle"),
    ("dallas mavericks", "dallas", "mavericks", "mavs", "dal"),
    ("denver nuggets", "denver", "nuggets", "den"),
    ("detroit pistons", "detroit", "pistons", "det"),
    ("golden state warriors", "golden state", "warriors", "gsw"),
    ("houston rockets", "houston", "rockets", "hou"),
    ("indiana pacers", "indiana", "pacers", "ind"),
    ("los angeles clippers", "la clippers", "l a clippers", "clippers", "lac"),
    ("los angeles lakers", "la lakers", "l a lakers", "lakers", "lal"),
    ("memphis grizzlies", "memphis", "grizzlies", "mem"),
    ("miami heat", "miami", "heat", "mia"),
    ("milwaukee bucks", "milwaukee", "bucks", "mil"),
    ("minnesota timberwolves", "minnesota", "timberwolves", "wolves", "min"),
    ("new orleans pelicans", "new orleans", "pelicans", "nop"),
    ("new york knicks", "new york", "knicks", "nyk"),
    ("oklahoma city thunder", "oklahoma city", "thunder", "okc"),
    ("orlando magic", "orlando", "magic", "orl"),
    ("philadelphia 76ers", "philadelphia", "76ers", "sixers", "phi"),
    ("phoenix suns", "phoenix", "suns", "phx"),
    ("portland trail blazers", "portland", "trail blazers", "blazers", "por"),
    ("sacramento kings", "sacramento", "kings", "sac"),
    ("san antonio spurs", "san antonio", "spurs", "sas"),
    ("toronto raptors", "toronto", "raptors", "tor"),
    ("utah jazz", "utah", "jazz", "uta"),
    ("washington wizards", "washington", "wizards", "was"),
    # MLB
    ("arizona diamondbacks", "arizona", "diamondbacks", "d backs", "ari"),
    ("atlanta braves", "braves"),
    ("baltimore orioles", "baltimore", "orioles", "bal"),
    ("boston red sox", "red sox"),
    ("chicago cubs", "cubs"),
    ("chicago white sox", "white sox", "cws"),
    ("cincinnati reds", "cincinnati", "reds", "cin"),
    ("cleveland guardians", "guardians"),
    ("colorado rockies", "colorado", "rockies", "col"),
    ("detroit tigers", "tigers"),
    ("houston astros", "astros"),
    ("kansas city royals", "kansas city", "royals", "kc", "kcr"),
    ("los angeles angels", "la angels", "angels", "laa"),
    ("los angeles dodgers", "la dodgers", "dodgers", "lad"),
    ("miami marlins", "marlins"),
    ("milwaukee brewers", "brewers"),
    ("minnesota twins", "twins"),
    ("new york mets", "ny mets", "mets", "nym"),
    ("new york yankees", "ny yankees", "new york y", "yankees", "nyy"),
    ("oakland athletics", "athletics", "oakland a s", "a s", "oak"),
    ("philadelphia phillies", "phillies"),
    ("pittsburgh pirates", "pittsburgh", "pirates", "pit"),
    ("san diego padres", "san diego", "padres", "sd", "sdp"),
    ("san francisco giants", "san francisco", "giants", "sf", "sfg"),
    ("seattle mariners", "seattle", "mariners", "sea"),
    ("st louis cardinals", "st. louis", "st louis", "cardinals", "stl"),
    ("tampa bay rays", "tampa bay", "rays", "tb", "tbr"),
    ("texas rangers", "texas", "rangers", "tex"),
    ("toronto blue jays", "blue jays"),
    ("washington nationals", "nationals", "wsh"),
    # NHL
    ("anaheim ducks", "anaheim", "ducks"),
    ("boston bruins", "bruins"),
    ("buffalo sabres", "buffalo", "sabres"),
    ("calgary flames", "calgary", "flames"),
    ("carolina hurricanes", "carolina", "hurricanes", "canes"),
    ("chicago blackhawks", "blackhawks"),
    ("colorado avalanche", "avalanche", "avs"),
    ("columbus blue jackets", "columbus", "blue jackets"),
    ("dallas stars", "stars"),
    ("detroit red wings", "red wings"),
    ("edmonton oilers", "edmonton", "oilers"),
    ("florida panthers", "florida", "panthers"),
    ("los angeles kings", "la kings"),
    ("minnesota wild", "wild"),
    ("montreal canadiens", "montreal", "canadiens", "habs"),
    ("nashville predators", "nashville", "predators", "preds"),
    ("new jersey devils", "new jersey", "devils"),
    ("new york islanders", "ny islanders", "islanders"),
    ("new york rangers", "ny rangers"),
    ("ottawa senators", "ottawa", "senators", "sens"),
    ("philadelphia flyers", "flyers"),
    ("pittsburgh penguins", "penguins"),
    ("san jose sharks", "san jose", "sharks"),
    ("seattle kraken", "kraken"),
    ("st louis blues", "st. louis blues", "blues"),
    ("tampa bay lightning", "lightning"),
    ("toronto maple leafs", "maple leafs", "leafs"),
    ("utah mammoth", "utah hockey club", "utah hc", "mammoth"),
    ("vancouver canucks", "vancouver", "canucks"),
    ("vegas golden knights", "vegas", "golden knights", "knights"),
    ("washington capitals", "capitals", "caps"),
    ("winnipeg jets", "winnipeg", "jets"),
    # WNBA
    ("atlanta dream", "dream"),
    ("chicago sky", "sky"),
    ("connecticut sun", "connecticut", "sun"),
    ("dallas wings", "wings"),
    ("golden state valkyries", "valkyries"),
    ("indiana fever", "fever"),
    ("las vegas aces", "aces"),
    ("los angeles sparks", "la sparks", "sparks"),
    ("minnesota lynx", "lynx"),
    ("new york liberty", "liberty"),
    ("phoenix mercury", "mercury"),
    ("seattle storm", "storm"),
    ("washington mystics", "mystics"),
)
NBA_TEAMS = {
    "atlanta hawks", "boston celtics", "brooklyn nets", "charlotte hornets", "chicago bulls",
    "cleveland cavaliers", "dallas mavericks", "denver nuggets", "detroit pistons",
    "golden state warriors", "houston rockets", "indiana pacers", "los angeles clippers",
    "los angeles lakers", "memphis grizzlies", "miami heat", "milwaukee bucks",
    "minnesota timberwolves", "new orleans pelicans", "new york knicks", "oklahoma city thunder",
    "orlando magic", "philadelphia 76ers", "phoenix suns", "portland trail blazers",
    "sacramento kings", "san antonio spurs", "toronto raptors", "utah jazz", "washington wizards",
}
MLB_TEAMS = {
    "arizona diamondbacks", "atlanta braves", "baltimore orioles", "boston red sox",
    "chicago cubs", "chicago white sox", "cincinnati reds", "cleveland guardians",
    "colorado rockies", "detroit tigers", "houston astros", "kansas city royals",
    "los angeles angels", "los angeles dodgers", "miami marlins", "milwaukee brewers",
    "minnesota twins", "new york mets", "new york yankees", "oakland athletics",
    "philadelphia phillies", "pittsburgh pirates", "san diego padres", "san francisco giants",
    "seattle mariners", "st louis cardinals", "tampa bay rays", "texas rangers",
    "toronto blue jays", "washington nationals",
}
NHL_TEAMS = {
    "anaheim ducks", "boston bruins", "buffalo sabres", "calgary flames", "carolina hurricanes",
    "chicago blackhawks", "colorado avalanche", "columbus blue jackets", "dallas stars",
    "detroit red wings", "edmonton oilers", "florida panthers", "los angeles kings",
    "minnesota wild", "montreal canadiens", "nashville predators", "new jersey devils",
    "new york islanders", "new york rangers", "ottawa senators", "philadelphia flyers",
    "pittsburgh penguins", "san jose sharks", "seattle kraken", "st louis blues",
    "tampa bay lightning", "toronto maple leafs", "utah mammoth", "vancouver canucks",
    "vegas golden knights", "washington capitals", "winnipeg jets",
}
WNBA_TEAMS = {
    "atlanta dream", "chicago sky", "connecticut sun", "dallas wings",
    "golden state valkyries", "indiana fever", "las vegas aces", "los angeles sparks",
    "minnesota lynx", "new york liberty", "phoenix mercury", "seattle storm",
    "washington mystics",
}
LEAGUE_ALIAS_OVERRIDES = {
    ("nba", "boston"): "boston celtics",
    ("nba", "new york"): "new york knicks",
    ("nba", "dallas"): "dallas mavericks",
    ("nba", "milwaukee"): "milwaukee bucks",
    ("mlb", "boston"): "boston red sox",
    ("mlb", "new york y"): "new york yankees",
    ("mlb", "new york"): "new york yankees",
    ("mlb", "seattle"): "seattle mariners",
    ("nhl", "boston"): "boston bruins",
    ("nhl", "new york"): "new york rangers",
    ("nhl", "rangers"): "new york rangers",
    ("nhl", "dallas"): "dallas stars",
    ("wnba", "new york"): "new york liberty",
    ("wnba", "dallas"): "dallas wings",
}


@dataclass(frozen=True)
class SportsIdentity:
    league: str
    participants: tuple[str, ...]
    outcome: str | None
    event_start: datetime | None
    market_type: str
    line: str | None
    period: str
    round_name: str | None

    @property
    def is_sports(self) -> bool:
        return self.league not in {
            "politics",
            "elections",
            "weather",
            "culture",
            "additional_discovered_scenario_coverage",
        }


def sports_identity(raw: dict[str, Any], venue: str) -> SportsIdentity:
    title = _title(raw, venue)
    league_hint = _league(raw, title, [])
    participants = _participants(raw, title, venue, league_hint)
    league = _league(raw, title, participants)
    if league != league_hint:
        participants = _participants(raw, title, venue, league)
    outcome = _canonical_participant(
        str(raw.get("yes_sub_title") or raw.get("groupItemTitle") or ""),
        league,
    )
    if not outcome and len(participants) == 1:
        outcome = participants[0]
    return SportsIdentity(
        league=league,
        participants=tuple(sorted(set(participants))),
        outcome=outcome,
        event_start=_event_start(raw, venue),
        market_type=_market_type(raw, title, participants),
        line=_line(title),
        period=_period(title),
        round_name=_round(title),
    )


def event_start_distance_hours(left: SportsIdentity, right: SportsIdentity) -> float | None:
    if not left.event_start or not right.event_start:
        return None
    return abs((left.event_start - right.event_start).total_seconds()) / 3600


def compatible_candidate(left: SportsIdentity, right: SportsIdentity) -> bool:
    if left.league != right.league:
        return False
    if left.market_type != right.market_type:
        return False
    if left.line != right.line and (left.line is not None or right.line is not None):
        return False
    if left.period != right.period:
        return False
    if left.round_name != right.round_name and left.round_name and right.round_name:
        return False
    if left.participants and right.participants:
        if len(left.participants) >= 2 and len(right.participants) >= 2:
            if set(left.participants) != set(right.participants):
                return False
        elif not set(left.participants) & set(right.participants):
            return False
    drift = event_start_distance_hours(left, right)
    tolerance = 36 if left.league in {"atp", "wta", "itf_men", "itf_women", "golf", "f1", "ufc"} else 8
    return drift is None or drift <= tolerance


def canonical_outcome(value: str, league: str | None = None) -> str:
    return _canonical_participant(value, league) or _norm(value)


def _title(raw: dict[str, Any], venue: str) -> str:
    keys = ["title", "yes_sub_title"] if venue == "kalshi" else [
        "question",
        "groupItemTitle",
    ]
    return " ".join(str(raw.get(key) or "") for key in keys).strip()


def _league(raw: dict[str, Any], title: str, participants: list[str]) -> str:
    ticker = " ".join(str(raw.get(key) or "") for key in ["ticker", "event_ticker"]).upper()
    hints = (
        ("KXWNBA", "wnba"), ("KXNBA", "nba"), ("KXMLB", "mlb"), ("KXNHL", "nhl"),
        ("KXMLS", "mls"), ("KXATP", "atp"), ("KXWTA", "wta"), ("KXITFM", "itf_men"),
        ("KXITFW", "itf_women"), ("KXUFC", "ufc"), ("KXF1", "f1"), ("KXIPL", "ipl"),
        ("KXPGA", "golf"), ("KXNFL", "nfl"),
    )
    for prefix, league in hints:
        if prefix in ticker:
            return league
    classified = classify_focus_scenario(
        " ".join([title, str(raw.get("category") or ""), str(raw.get("tags") or "")])
    )
    if classified != "additional_discovered_scenario_coverage":
        return classified
    normalized = _norm(title)
    nickname_groups = (
        ("nba", {"hawks", "celtics", "nets", "hornets", "bulls", "cavaliers", "mavericks", "bucks", "knicks"}),
        ("mlb", {"yankees", "mariners", "red sox", "cubs", "white sox", "dodgers", "phillies", "astros"}),
        ("nhl", {"bruins", "rangers", "sabres", "oilers", "canadiens", "penguins", "capitals", "maple leafs"}),
        ("wnba", {"dream", "sky", "fever", "aces", "sparks", "liberty", "mercury", "mystics"}),
    )
    for league, nicknames in nickname_groups:
        hits = sum(
            bool(re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", normalized))
            for name in nicknames
        )
        if hits >= 2:
            return league
    participant_set = set(participants)
    if len(participant_set) >= 2:
        for league, teams in (
            ("nba", NBA_TEAMS), ("mlb", MLB_TEAMS), ("nhl", NHL_TEAMS), ("wnba", WNBA_TEAMS)
        ):
            if len(participant_set & teams) >= 2:
                return league
    return classified


def _participants(raw: dict[str, Any], title: str, venue: str, league: str | None) -> list[str]:
    values: list[str] = []
    if venue == "polymarket":
        outcomes = _json_list(raw.get("outcomes"))
        if len(outcomes) == 2 and {str(item).lower() for item in outcomes} != {"yes", "no"}:
            values.extend(str(item) for item in outcomes)
    short_title = str(raw.get("title") or raw.get("question") or "")
    for pattern in MATCHUP_PATTERNS:
        match = pattern.search(_strip_market_suffix(short_title))
        if match:
            values.extend(match.groups())
            break
    values.extend(
        str(raw.get(key) or "")
        for key in ["yes_sub_title", "groupItemTitle"]
        if raw.get(key)
    )
    no_label = str(raw.get("no_sub_title") or "")
    if no_label and _norm(no_label) not in {"no", "other", "field"}:
        values.append(no_label)
    canonical = [_canonical_participant(value, league) for value in values]
    canonical = [item for item in canonical if item and item not in {"yes", "no"}]
    if canonical:
        return canonical
    # Individual sports usually use stable full names. Extract the two sides even
    # when they are not in the team alias table.
    for pattern in MATCHUP_PATTERNS:
        match = pattern.search(_strip_market_suffix(short_title))
        if match:
            return [_norm(item) for item in match.groups()]
    return []


def _canonical_participant(value: str, league: str | None = None) -> str | None:
    normalized = _norm(_strip_market_suffix(value))
    if not normalized:
        return None
    override = LEAGUE_ALIAS_OVERRIDES.get((str(league), normalized))
    if override:
        return override
    allowed = _league_teams(league)
    if normalized in TEAM_ALIASES and (not allowed or TEAM_ALIASES[normalized] in allowed):
        return TEAM_ALIASES[normalized]
    return normalized


def _league_teams(league: str | None) -> set[str]:
    return {
        "nba": NBA_TEAMS,
        "mlb": MLB_TEAMS,
        "nhl": NHL_TEAMS,
        "wnba": WNBA_TEAMS,
    }.get(str(league), set())


def _event_start(raw: dict[str, Any], venue: str) -> datetime | None:
    keys = (
        ["gameStartTime", "event_start", "start_time", "startDate"]
        if venue == "polymarket"
        else ["expected_expiration_time", "event_start", "start_time", "close_time"]
    )
    for key in keys:
        value = raw.get(key)
        if value:
            parsed = _parse_optional(str(value))
            if parsed:
                return parsed
    return None


def _line(value: str) -> str | None:
    normalized = _norm(value)
    patterns = (
        r"\b(?:over|under|above|below)\s*(-?\d+(?:\.\d+)?)\b",
        r"(?<!\d)([+-]\d+(?:\.\d+)?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1)
    return None


def _market_type(raw: dict[str, Any], title: str, participants: list[str]) -> str:
    classified = classify_market_type(
        " ".join(filter(None, [title, raw.get("rules_primary"), raw.get("description")])),
        raw.get("market_type"),
    )
    if len(set(participants)) >= 2 and classified == "future_or_winner":
        return "moneyline_or_binary"
    return classified


def _period(value: str) -> str:
    normalized = _norm(value)
    periods = (
        ("first_half", ("first half", "1st half")),
        ("second_half", ("second half", "2nd half")),
        ("first_quarter", ("first quarter", "1st quarter")),
        ("first_period", ("first period", "1st period")),
        ("first_inning", ("first inning", "1st inning")),
        ("first_five_innings", ("first five innings", "first 5 innings", "f5")),
        ("set_1", ("set 1", "first set")),
        ("map_1", ("map 1", "first map")),
        ("regulation", ("regulation only", "60 minutes", "90 minutes")),
    )
    for label, phrases in periods:
        if any(phrase in normalized for phrase in phrases):
            return label
    return "full_event"


def _round(value: str) -> str | None:
    normalized = _norm(value)
    for label, phrases in (
        ("final", ("final", "finals")),
        ("semifinal", ("semifinal", "semi final")),
        ("quarterfinal", ("quarterfinal", "quarter final")),
        ("round_of_16", ("round of 16",)),
        ("round_of_32", ("round of 32",)),
    ):
        if any(re.search(rf"\b{re.escape(phrase)}\b", normalized) for phrase in phrases):
            return label
    return None


def _strip_market_suffix(value: str) -> str:
    return re.sub(
        r"\s+(?:winner|moneyline|spread|total|game|match)(?:\s+winner)?[?]?$",
        "",
        value.strip(),
        flags=re.I,
    )


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_optional(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
