from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .models import MatchedMarket, MarketRef, OutcomeRef
from .official_api import KalshiOfficialClient, PolymarketGammaClient
from .scenario import classify_domain
from .serde import read_json, write_json


CACHE_VERSION = 2
STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "before",
    "by",
    "end",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "vs",
    "will",
    "win",
    "winner",
}
SEMANTIC_GROUPS = [
    {
        "sports_basketball": [r"\bbasketball\b", r"\bnba\b", r"\bwnba\b"],
        "sports_cricket": [r"\bcricket\b", r"\bicc\b"],
        "sports_soccer": [r"\bsoccer\b", r"\bfifa\b", r"\buefa\b", r"\bpremier league\b", r"\bmen s world cup\b"],
        "sports_baseball": [r"\bbaseball\b", r"\bmlb\b"],
        "sports_hockey": [r"\bhockey\b", r"\bnhl\b"],
        "sports_tennis": [r"\btennis\b", r"\batp\b", r"\bwta\b"],
        "sports_motorsport": [r"\bformula 1\b", r"\bformula one\b", r"\bf1\b", r"\bnascar\b"],
    },
    {
        "qualify": [r"\bqualif"],
        "win": [r"\bwin\b", r"\bwinner\b", r"\bchampion\b"],
        "launch_token": [r"\blaunch a token\b", r"\blaunch token\b"],
    },
]
STRICT_SEMANTIC_GROUPS = [
    {
        "round_of_16": [r"\bround of 16\b"],
        "quarterfinal": [r"\bquarterfinal"],
        "semifinal": [r"\bsemifinal"],
        "final": [r"\bfinal\b", r"\bfinals\b"],
    },
    {
        "finish_second": [r"\bfinish 2nd\b", r"\bfinish second\b"],
        "finish_third": [r"\bfinish 3rd\b", r"\bfinish third\b"],
        "gain_seats": [r"\bgain seats\b"],
        "above": [r"\babove\b", r"\bmore than\b", r"\bover\b"],
        "below": [r"\bbelow\b", r"\bless than\b", r"\bunder\b"],
    },
]


def discover_official_history(
    start: str,
    end: str,
    cache_path: str | Path,
    kalshi_event_pages: int = 100,
    polymarket_pages_per_month: int = 30,
    max_expanded_events: int = 3000,
    min_score: float = 0.78,
    fresh: bool = False,
) -> dict[str, Any]:
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    cache = _load_cache(cache_path) if not fresh else _new_cache()
    months = list(_month_slices(start_dt, end_dt))
    kalshi = KalshiOfficialClient()
    polymarket = PolymarketGammaClient()

    for month_start, month_end in months:
        key = month_start.strftime("%Y-%m")
        if key in cache["polymarket_months"]:
            continue
        cache["polymarket_months"][key] = {
            "start": month_start.isoformat(),
            "end": month_end.isoformat(),
            **_fetch_polymarket_month(polymarket, month_start, month_end, polymarket_pages_per_month),
        }
        write_json(cache_path, cache)
        print(f"Checkpointed Polymarket catalog month {key}")

    if "kalshi_events" not in cache:
        cache["kalshi_events"] = _fetch_kalshi_events(kalshi, start_dt, kalshi_event_pages)
        write_json(cache_path, cache)
        print(f"Checkpointed {len(cache['kalshi_events']['events'])} Kalshi events")

    raw_poly = _dedupe(
        [
            market
            for month in cache["polymarket_months"].values()
            for market in month.get("markets", [])
        ],
        "id",
    )
    candidate_events = _shortlist_events(cache["kalshi_events"]["events"], raw_poly)
    expanded_events = cache.setdefault("expanded_events", {})
    expansion_errors = cache.setdefault("expansion_errors", [])
    for index, event in enumerate(candidate_events[:max_expanded_events], start=1):
        ticker = str(event["event_ticker"])
        if ticker in expanded_events:
            continue
        try:
            expanded_events[ticker] = {
                "event": event,
                "markets": [_trim_kalshi_market(item) for item in kalshi.event(ticker).get("markets", [])],
            }
        except Exception as exc:  # noqa: BLE001
            expansion_errors.append({"event_ticker": ticker, "error": str(exc)})
        if index % 20 == 0:
            write_json(cache_path, cache)
            print(f"Expanded {index}/{min(len(candidate_events), max_expanded_events)} shortlisted Kalshi events")
    write_json(cache_path, cache)

    raw_kalshi = _dedupe(
        [
            market
            for event in expanded_events.values()
            for market in event.get("markets", [])
            if _market_in_range(market, start_dt, end_dt)
        ],
        "ticker",
    )
    matches, rejected = match_official_catalogs_monthly(raw_kalshi, raw_poly, min_score=min_score)
    return {
        "meta": {
            "source": "official_kalshi_event_catalog_and_polymarket_gamma_catalog",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "kalshi_events_fetched": len(cache["kalshi_events"]["events"]),
            "kalshi_events_truncated": cache["kalshi_events"]["truncated"],
            "kalshi_events_shortlisted": len(candidate_events),
            "kalshi_events_expanded": len(expanded_events),
            "kalshi_event_expansion_errors": len(expansion_errors),
            "kalshi_events_expansion_truncated": len(candidate_events) > max_expanded_events,
            "kalshi_candidate_markets": len(raw_kalshi),
            "polymarket_catalog_markets": len(raw_poly),
            "matched_pairs": len(matches),
            "rejected_candidates": len(rejected),
            "min_score": min_score,
            "polymarket_months": {
                key: {
                    "polymarket_markets": len(month.get("markets", [])),
                    "polymarket_truncated": month.get("truncated", False),
                }
                for key, month in sorted(cache["polymarket_months"].items())
            },
            "note": (
                "The catalog crawl is checkpointable and may be page-capped. Catalog title matching "
                "is conservative screening, not a trading authorization. Manually verify resolution "
                "rules before treating any pair as identical."
            ),
        },
        "matches": [asdict(match) for match in matches],
        "rejected": rejected,
    }


def match_official_catalogs(
    kalshi_markets: list[dict[str, Any]],
    polymarket_markets: list[dict[str, Any]],
    min_score: float = 0.78,
) -> tuple[list[MatchedMarket], list[dict[str, Any]]]:
    poly_records = [_poly_record(item) for item in polymarket_markets]
    poly_records = [item for item in poly_records if item]
    index: dict[str, set[int]] = defaultdict(set)
    for pos, item in enumerate(poly_records):
        for token in item["tokens"]:
            index[token].add(pos)

    matches: list[MatchedMarket] = []
    rejected: list[dict[str, Any]] = []
    for kalshi in kalshi_markets:
        kalshi_record = _kalshi_record(kalshi)
        if not kalshi_record:
            continue
        candidate_positions = _candidate_positions(kalshi_record["tokens"], index)
        scored = []
        for pos in candidate_positions:
            poly_record = poly_records[pos]
            scored_item = _score_pair(kalshi_record, poly_record)
            if scored_item:
                scored.append(scored_item)
        scored.sort(key=lambda item: item["score"], reverse=True)
        if not scored or scored[0]["score"] < min_score:
            continue
        if len(scored) > 1 and scored[1]["score"] >= min_score and scored[0]["score"] - scored[1]["score"] < 0.03:
            rejected.append(
                {
                    "kalshi_ticker": kalshi_record["raw"]["ticker"],
                    "reason": "ambiguous_top_candidates",
                    "top": [_candidate_summary(item) for item in scored[:3]],
                }
            )
            continue
        best = scored[0]
        match = _build_match(kalshi_record, best["poly"], best)
        if match:
            matches.append(match)

    matches.sort(key=lambda item: (item.kalshi.resolution_date or "", item.match_id))
    return matches, rejected


def match_official_catalogs_monthly(
    kalshi_markets: list[dict[str, Any]],
    polymarket_markets: list[dict[str, Any]],
    min_score: float = 0.78,
) -> tuple[list[MatchedMarket], list[dict[str, Any]]]:
    kalshi_by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for market in kalshi_markets:
        date = _parse_optional(market.get("close_time") or market.get("expiration_time"))
        if date:
            kalshi_by_month[date.strftime("%Y-%m")].append(market)

    matches = []
    rejected = []
    for month, monthly_kalshi in sorted(kalshi_by_month.items()):
        pivot = _parse_iso(f"{month}-15T00:00:00Z")
        nearby_poly = [
            market
            for market in polymarket_markets
            if _within_days(
                _parse_optional(market.get("endDate") or market.get("closedTime")),
                pivot,
                76,
            )
        ]
        monthly_matches, monthly_rejected = match_official_catalogs(
            monthly_kalshi,
            nearby_poly,
            min_score=min_score,
        )
        matches.extend(monthly_matches)
        rejected.extend(monthly_rejected)
        print(
            f"Matched official catalog month {month}: "
            f"kalshi={len(monthly_kalshi)} nearby_polymarket={len(nearby_poly)} pairs={len(monthly_matches)}"
        )
    deduped = {match.match_id: match for match in matches}
    return sorted(deduped.values(), key=lambda item: (item.kalshi.resolution_date or "", item.match_id)), rejected


def _fetch_kalshi_events(
    client: KalshiOfficialClient,
    start: datetime,
    max_pages: int,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    truncated = False
    for status in ["settled", "closed"]:
        cursor = None
        for page in range(max_pages):
            data = client.events(
                limit=200,
                cursor=cursor,
                status=status,
                min_close_ts=int(start.timestamp()),
            )
            rows = list(data.get("events") or [])
            events.extend(_trim_kalshi_event(item) for item in rows)
            cursor = data.get("cursor")
            if not cursor or not rows:
                break
            if page == max_pages - 1:
                truncated = True
        print(f"Fetched Kalshi event status={status}; cumulative events={len(events)}")
    return {"events": _dedupe(events, "event_ticker"), "truncated": truncated}


def _fetch_polymarket_month(
    client: PolymarketGammaClient,
    start: datetime,
    end: datetime,
    max_pages: int,
) -> dict[str, Any]:
    markets: list[dict[str, Any]] = []
    cursor = None
    truncated = False
    for page in range(max_pages):
        data = client.market_page(start.isoformat(), end.isoformat(), cursor=cursor, limit=100)
        rows = list(data.get("markets") or [])
        markets.extend(_trim_poly_market(item) for item in rows)
        cursor = data.get("next_cursor")
        if not cursor or not rows:
            break
        if page == max_pages - 1:
            truncated = True
    return {"markets": markets, "truncated": truncated}


def _shortlist_events(
    kalshi_events: list[dict[str, Any]],
    polymarket_markets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    poly_records = [_poly_record(item) for item in polymarket_markets]
    poly_records = [item for item in poly_records if item]
    index: dict[str, set[int]] = defaultdict(set)
    for pos, item in enumerate(poly_records):
        for token in item["tokens"]:
            index[token].add(pos)

    shortlisted = []
    for event in kalshi_events:
        title = " ".join(
            str(item)
            for item in [
                event.get("title"),
                event.get("sub_title"),
                event.get("category"),
                event.get("product_metadata"),
            ]
            if item
        )
        tokens = _tokens(title)
        domain = classify_domain(title, event.get("category"))
        candidate_positions = _candidate_positions(tokens, index)
        for pos in candidate_positions:
            poly = poly_records[pos]
            if _is_sports(domain) != _is_sports(poly["domain"]):
                continue
            if len(tokens & poly["tokens"]) >= 2:
                shortlisted.append(event)
                break
    return _dedupe(shortlisted, "event_ticker")


def _kalshi_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("market_type") not in {None, "binary"}:
        return None
    title = " ".join(filter(None, [raw.get("title"), raw.get("yes_sub_title")]))
    return {
        "raw": raw,
        "title": title,
        "tokens": _tokens(title),
        "domain": classify_domain(title),
        "date": _parse_optional(raw.get("close_time") or raw.get("expiration_time")),
        "yes_label": raw.get("yes_sub_title") or raw.get("title") or "Yes",
    }


def _poly_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    outcomes = _json_list(raw.get("outcomes"))
    token_ids = _json_list(raw.get("clobTokenIds"))
    if len(outcomes) != 2 or len(token_ids) != 2:
        return None
    title = " ".join(filter(None, [raw.get("question"), raw.get("groupItemTitle")]))
    return {
        "raw": raw,
        "title": title,
        "tokens": _tokens(title),
        "domain": classify_domain(title),
        "date": _parse_optional(raw.get("endDate") or raw.get("closedTime")),
        "outcomes": [str(item) for item in outcomes],
        "token_ids": [str(item) for item in token_ids],
    }


def _score_pair(kalshi: dict[str, Any], poly: dict[str, Any]) -> dict[str, Any] | None:
    if not kalshi["tokens"] or not poly["tokens"]:
        return None
    if _is_sports(kalshi["domain"]) != _is_sports(poly["domain"]):
        return None
    if not _semantic_compatible(kalshi["title"], poly["title"]):
        return None
    if not _structured_compatible(kalshi["title"], poly["title"]):
        return None
    shared = kalshi["tokens"] & poly["tokens"]
    if len(shared) < 2:
        return None
    drift_days = _date_drift_days(kalshi["date"], poly["date"])
    if drift_days is not None and drift_days > 45:
        return None
    union = kalshi["tokens"] | poly["tokens"]
    jaccard = len(shared) / len(union)
    sequence = SequenceMatcher(None, _norm(kalshi["title"]), _norm(poly["title"])).ratio()
    oriented = _orient_poly_outcomes(poly, kalshi["yes_label"])
    if not oriented:
        return None
    label_bonus = oriented["label_score"]
    score = (0.50 * sequence) + (0.35 * jaccard) + (0.15 * label_bonus)
    return {
        "score": score,
        "sequence": sequence,
        "jaccard": jaccard,
        "label_score": label_bonus,
        "date_drift_days": drift_days,
        "poly": poly,
        "oriented": oriented,
    }


def _build_match(kalshi: dict[str, Any], poly: dict[str, Any], score: dict[str, Any]) -> MatchedMarket | None:
    oriented = score["oriented"]
    kalshi_raw = kalshi["raw"]
    poly_raw = poly["raw"]
    warnings = []
    drift = score.get("date_drift_days")
    if drift is not None and drift > 3:
        warnings.append(f"Resolution dates differ by {drift} days.")
    if oriented["nonstandard"]:
        warnings.append("Polymarket outcomes were oriented from outcome labels; manually verify the side mapping.")
    warnings.append("Official catalog title match; manually verify both resolution rulebooks before trading.")
    warning = " ".join(warnings)
    ticker = str(kalshi_raw["ticker"])
    poly_id = str(poly_raw.get("conditionId") or poly_raw.get("id"))
    return MatchedMarket(
        match_id=f"official::{poly_id}::{ticker}",
        polymarket=MarketRef(
            venue="polymarket",
            market_id=poly_id,
            title=str(poly_raw.get("question") or ""),
            slug=poly_raw.get("slug"),
            url=f"https://polymarket.com/event/{poly_raw.get('slug')}" if poly_raw.get("slug") else None,
            category=poly["domain"],
            resolution_date=poly_raw.get("endDate"),
            contract_address=poly_raw.get("conditionId"),
            yes=OutcomeRef(oriented["yes_token"], oriented["yes_label"]),
            no=OutcomeRef(oriented["no_token"], oriented["no_label"]),
            raw=poly_raw,
        ),
        kalshi=MarketRef(
            venue="kalshi",
            market_id=ticker,
            title=str(kalshi_raw.get("title") or ""),
            slug=ticker,
            url=f"https://kalshi.com/markets/{ticker}",
            category=kalshi["domain"],
            resolution_date=kalshi_raw.get("close_time") or kalshi_raw.get("expiration_time"),
            contract_address=None,
            yes=OutcomeRef(ticker, str(kalshi_raw.get("yes_sub_title") or "Yes")),
            no=OutcomeRef(f"{ticker}-NO", "No"),
            raw=kalshi_raw,
        ),
        relation="official_catalog_title_match",
        confidence=float(score["score"]),
        price_difference=None,
        reasoning=(
            f"local official catalog match: sequence={score['sequence']:.3f}, "
            f"jaccard={score['jaccard']:.3f}, label={score['label_score']:.3f}"
        ),
        resolution_date_warning=warning,
    )


def _orient_poly_outcomes(poly: dict[str, Any], kalshi_yes_label: str) -> dict[str, Any] | None:
    outcomes = poly["outcomes"]
    tokens = poly["token_ids"]
    lowered = [item.lower() for item in outcomes]
    if set(lowered) == {"yes", "no"}:
        yes_pos = lowered.index("yes")
        no_pos = lowered.index("no")
        return {
            "yes_token": tokens[yes_pos],
            "yes_label": outcomes[yes_pos],
            "no_token": tokens[no_pos],
            "no_label": outcomes[no_pos],
            "label_score": 1.0,
            "nonstandard": False,
        }
    scores = [SequenceMatcher(None, _norm(kalshi_yes_label), _norm(label)).ratio() for label in outcomes]
    yes_pos = max(range(2), key=lambda pos: scores[pos])
    no_pos = 1 - yes_pos
    if scores[yes_pos] < 0.55 or scores[yes_pos] - scores[no_pos] < 0.10:
        return None
    return {
        "yes_token": tokens[yes_pos],
        "yes_label": outcomes[yes_pos],
        "no_token": tokens[no_pos],
        "no_label": outcomes[no_pos],
        "label_score": scores[yes_pos],
        "nonstandard": True,
    }


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": candidate["score"],
        "polymarket_id": candidate["poly"]["raw"].get("id"),
        "polymarket_title": candidate["poly"]["raw"].get("question"),
    }


def _trim_kalshi_market(raw: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "ticker",
        "event_ticker",
        "title",
        "yes_sub_title",
        "no_sub_title",
        "close_time",
        "expiration_time",
        "expected_expiration_time",
        "market_type",
        "status",
        "result",
        "volume_fp",
    ]
    return {key: raw.get(key) for key in keys}


def _trim_kalshi_event(raw: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "event_ticker",
        "series_ticker",
        "title",
        "sub_title",
        "category",
        "product_metadata",
        "strike_date",
    ]
    return {key: raw.get(key) for key in keys}


def _trim_poly_market(raw: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "conditionId",
        "question",
        "slug",
        "groupItemTitle",
        "endDate",
        "closedTime",
        "outcomes",
        "clobTokenIds",
        "enableOrderBook",
        "active",
        "closed",
        "volume",
    ]
    return {key: raw.get(key) for key in keys}


def _load_cache(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return _new_cache()
    payload = read_json(target)
    return payload if payload.get("version") == CACHE_VERSION else _new_cache()


def _new_cache() -> dict[str, Any]:
    return {"version": CACHE_VERSION, "polymarket_months": {}}


def _dedupe(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen = {}
    for item in items:
        value = item.get(key)
        if value is not None:
            seen[str(value)] = item
    return list(seen.values())


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _tokens(value: str) -> set[str]:
    return {
        item
        for item in re.findall(r"[a-z0-9]+", _norm(value))
        if len(item) >= 3 and not item.isdigit() and item not in STOP_WORDS
    }


def _candidate_positions(tokens: set[str], index: dict[str, set[int]]) -> set[int]:
    buckets = sorted(
        (index[token] for token in tokens if token in index),
        key=len,
    )
    selective = [bucket for bucket in buckets if len(bucket) <= 1000][:12]
    chosen = selective or buckets[:3]
    counts: Counter[int] = Counter()
    for bucket in chosen:
        counts.update(bucket)
    overlapping = {pos for pos, count in counts.items() if count >= 2}
    return overlapping or (set(chosen[0]) if chosen else set())


def _semantic_compatible(left: str, right: str) -> bool:
    left_norm = _norm(left)
    right_norm = _norm(right)
    for group in SEMANTIC_GROUPS:
        left_markers = _markers(left_norm, group)
        right_markers = _markers(right_norm, group)
        if left_markers and right_markers and not left_markers & right_markers:
            return False
    for group in STRICT_SEMANTIC_GROUPS:
        left_markers = _markers(left_norm, group)
        right_markers = _markers(right_norm, group)
        if left_markers != right_markers:
            return False
    return True


def _structured_compatible(left: str, right: str) -> bool:
    left_norm = _norm(left)
    right_norm = _norm(right)
    left_districts = set(re.findall(r"\b[a-z]{2}\s\d{1,2}\b", left_norm))
    right_districts = set(re.findall(r"\b[a-z]{2}\s\d{1,2}\b", right_norm))
    if (left_districts or right_districts) and left_districts != right_districts:
        return False
    left_nominee = _nominee_last_name(left_norm)
    right_nominee = _nominee_last_name(right_norm)
    if left_nominee and right_nominee and left_nominee != right_nominee:
        return False
    return True


def _nominee_last_name(value: str) -> str | None:
    match = re.search(r"\bwill (.+?) be the (?:republican|democratic) nominee\b", value)
    if not match:
        return None
    parts = match.group(1).split()
    return parts[-1] if parts else None


def _markers(value: str, group: dict[str, list[str]]) -> set[str]:
    return {
        label
        for label, patterns in group.items()
        if any(re.search(pattern, value) for pattern in patterns)
    }


def _norm(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_value.lower())).strip()


def _month_slices(start: datetime, end: datetime):
    current = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    while current < end:
        if current.month == 12:
            following = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            following = datetime(current.year, current.month + 1, 1, tzinfo=timezone.utc)
        yield max(start, current), min(end, following)
        current = following


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_optional(value: str | None) -> datetime | None:
    return _parse_iso(value) if value else None


def _date_drift_days(left: datetime | None, right: datetime | None) -> int | None:
    if not left or not right:
        return None
    return abs((left - right).days)


def _is_sports(domain: str) -> bool:
    return domain.startswith("sports_")


def _market_in_range(market: dict[str, Any], start: datetime, end: datetime) -> bool:
    close_dt = _parse_optional(market.get("close_time") or market.get("expiration_time"))
    return bool(close_dt and start <= close_dt < end)


def _within_days(value: datetime | None, pivot: datetime, days: int) -> bool:
    return bool(value and abs((value - pivot).days) <= days)
