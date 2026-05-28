from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher

from .models import MatchedMarket, VenueMarket

STOPWORDS = {
    "will",
    "the",
    "a",
    "an",
    "to",
    "in",
    "of",
    "for",
    "from",
    "at",
    "by",
    "on",
    "yes",
    "no",
    "market",
    "winner",
    "win",
    "wins",
    "vs",
    "versus",
}

CONFLICTS = (
    ("round of 16", ("knockout stages", "qualify from group", "round of 32")),
    ("round of 32", ("round of 16",)),
    ("popular vote", ("electoral college",)),
    ("regular season", ("playoffs", "postseason")),
)


@dataclass(frozen=True)
class MatchConfig:
    min_confidence: Decimal = Decimal("0.74")
    max_resolution_drift_days: int = 45


def normalize_text(value: str | None) -> str:
    value = (value or "").lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9\s.:-]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def tokens(value: str | None) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]+", normalize_text(value)) if part not in STOPWORDS}


def market_signature(market: VenueMarket) -> str:
    pieces = [
        market.title,
        market.description or "",
        market.yes_label,
        market.no_label,
        market.category or "",
        market.market_type or "",
    ]
    return normalize_text(" ".join(pieces))


def match_markets(
    kalshi_markets: list[VenueMarket],
    polymarket_markets: list[VenueMarket],
    config: MatchConfig | None = None,
) -> list[MatchedMarket]:
    cfg = config or MatchConfig()
    candidates: list[MatchedMarket] = []
    for kalshi in kalshi_markets:
        for poly in polymarket_markets:
            match = score_pair(kalshi, poly, cfg)
            if match and match.confidence >= cfg.min_confidence:
                candidates.append(match)
    candidates.sort(key=lambda item: (item.confidence, item.is_tradeable_candidate), reverse=True)
    return _dedupe(candidates)


def score_pair(kalshi: VenueMarket, poly: VenueMarket, config: MatchConfig) -> MatchedMarket | None:
    warnings = list(_semantic_warnings(kalshi, poly))
    category_score = Decimal("0.08") if _same_category(kalshi.category, poly.category) else Decimal("0")
    type_score = Decimal("0.06") if _same_market_type(kalshi.market_type, poly.market_type) else Decimal("0")
    time_score, time_warning = _time_score(kalshi, poly, config.max_resolution_drift_days)
    if time_warning:
        warnings.append(time_warning)

    left = market_signature(kalshi)
    right = market_signature(poly)
    token_score = _token_similarity(left, right)
    text_score = Decimal(str(SequenceMatcher(None, left, right).ratio()))
    confidence = min(
        Decimal("1"),
        token_score * Decimal("0.58") + text_score * Decimal("0.22") + time_score + category_score + type_score,
    )
    if confidence < config.min_confidence:
        return None
    return MatchedMarket(
        match_id=f"{kalshi.market_id}::{poly.market_id}",
        kalshi=kalshi,
        polymarket_us=poly,
        confidence=confidence.quantize(Decimal("0.0001")),
        relation="identity",
        warnings=tuple(warnings),
        reasoning=f"token={token_score:.3f}; text={text_score:.3f}",
    )


def _token_similarity(left: str, right: str) -> Decimal:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return Decimal("0")
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return Decimal(overlap) / Decimal(union)


def _same_category(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return normalize_text(left) == normalize_text(right)


def _same_market_type(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    aliases = {
        "moneyline": {"moneyline", "game", "binary"},
        "spread": {"spread"},
        "total": {"total", "over under", "overunder"},
        "futures": {"future", "futures"},
    }
    for values in aliases.values():
        if left_norm in values and right_norm in values:
            return True
    return left_norm == right_norm


def _time_score(kalshi: VenueMarket, poly: VenueMarket, max_drift_days: int) -> tuple[Decimal, str | None]:
    left = kalshi.expiration_time or kalshi.close_time or kalshi.start_time
    right = poly.expiration_time or poly.close_time or poly.start_time
    if not left or not right:
        return Decimal("0"), "Missing comparable event or expiration time."
    drift_seconds = abs((left - right).total_seconds())
    drift_days = drift_seconds / 86_400
    if drift_days > max_drift_days:
        return Decimal("0"), f"Resolution or event times differ by {int(drift_days)} days; manually review."
    if drift_seconds <= 3600:
        return Decimal("0.12"), None
    if drift_days <= 1:
        return Decimal("0.09"), None
    return Decimal("0.04"), f"Resolution or event times differ by {drift_days:.1f} days."


def _semantic_warnings(kalshi: VenueMarket, poly: VenueMarket) -> tuple[str, ...]:
    left = market_signature(kalshi)
    right = market_signature(poly)
    warnings = []
    for anchor, conflicts in CONFLICTS:
        if anchor in left and any(conflict in right for conflict in conflicts):
            warnings.append(f"Possible rule mismatch: {anchor}.")
        if anchor in right and any(conflict in left for conflict in conflicts):
            warnings.append(f"Possible rule mismatch: {anchor}.")
    return tuple(warnings)


def _dedupe(matches: list[MatchedMarket]) -> list[MatchedMarket]:
    used_kalshi: set[str] = set()
    used_poly: set[str] = set()
    result: list[MatchedMarket] = []
    for match in matches:
        if match.kalshi.market_id in used_kalshi or match.polymarket_us.market_id in used_poly:
            continue
        used_kalshi.add(match.kalshi.market_id)
        used_poly.add(match.polymarket_us.market_id)
        result.append(match)
    return result

