from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher

from ..models import MatchedMarket, VenueMarket
from .models import EventGroup, EventPair
from .normalization import (
    comparable_time,
    event_title,
    market_signature,
    normalize_text,
    outcome_tokens,
    token_set,
)


def group_events(markets: list[VenueMarket]) -> list[EventGroup]:
    grouped: dict[str, list[VenueMarket]] = defaultdict(list)
    for market in markets:
        grouped[_event_key(market)].append(market)
    return [_to_group(key, rows) for key, rows in grouped.items()]


def generate_event_pairs(
    kalshi_markets: list[VenueMarket],
    polymarket_markets: list[VenueMarket],
    *,
    min_event_confidence: Decimal = Decimal("0.34"),
    min_outcome_confidence: Decimal = Decimal("0.22"),
    max_candidates_per_event: int = 8,
) -> list[EventPair]:
    kalshi_groups = group_events(kalshi_markets)
    poly_groups = group_events(polymarket_markets)
    result: list[EventPair] = []
    for kalshi in kalshi_groups:
        candidates: list[EventPair] = []
        for poly in poly_groups:
            confidence, warnings, reasoning = _event_score(kalshi, poly)
            if confidence < min_event_confidence:
                continue
            outcome_matches = _assign_outcomes(
                kalshi.markets, poly.markets, min_outcome_confidence
            )
            if not outcome_matches:
                continue
            coverage = Decimal(len(outcome_matches)) / Decimal(
                max(len(kalshi.markets), len(poly.markets), 1)
            )
            combined = min(Decimal("1"), confidence * Decimal("0.7") + coverage * Decimal("0.3"))
            candidates.append(
                EventPair(
                    kalshi=kalshi,
                    polymarket=poly,
                    confidence=combined.quantize(Decimal("0.0001")),
                    outcome_matches=tuple(outcome_matches),
                    warnings=tuple(warnings),
                    reasoning=f"{reasoning}; outcome_coverage={coverage:.3f}",
                )
            )
        candidates.sort(key=lambda row: row.confidence, reverse=True)
        result.extend(candidates[:max_candidates_per_event])
    return result


def _event_key(market: VenueMarket) -> str:
    raw = market.raw
    keys = (
        "event_ticker", "series_ticker", "event_id", "eventId", "eventSlug",
        "event_slug", "parentEventId", "parent_event_id",
    )
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict):
            value = value.get("id") or value.get("slug")
        if value:
            return f"{market.venue}:{value}:{_type_family(market.market_type)}"
    title = normalize_text(event_title(market))
    title = re.sub(r"\b(yes|no|will|winner|win)\b", " ", title)
    date = comparable_time(market)
    return f"{market.venue}:fallback:{date.date() if date else 'none'}:{title}"


def _to_group(key: str, markets: list[VenueMarket]) -> EventGroup:
    first = markets[0]
    return EventGroup(
        venue=first.venue,
        key=key,
        title=event_title(first),
        category=first.category,
        market_type=first.market_type,
        start_time=first.start_time,
        close_time=first.close_time or first.expiration_time,
        markets=tuple(markets),
    )


def _event_score(left: EventGroup, right: EventGroup) -> tuple[Decimal, list[str], str]:
    left_text = normalize_text(left.title)
    right_text = normalize_text(right.title)
    left_tokens = token_set(left_text)
    right_tokens = token_set(right_text)
    union = left_tokens | right_tokens
    jaccard = Decimal(len(left_tokens & right_tokens)) / Decimal(len(union) or 1)
    sequence = Decimal(str(SequenceMatcher(None, left_text, right_text).ratio()))
    participant_overlap = _participant_overlap(left, right)
    time_score, time_warning = _time_score(left, right)
    left_time = left.start_time or left.close_time
    right_time = right.start_time or right.close_time
    if (
        left_time
        and right_time
        and abs((left_time - right_time).total_seconds()) > 172800
    ):
        return Decimal("0"), [time_warning or "Event dates conflict."], "hard_date_conflict"
    category = Decimal("0.05") if _same(left.category, right.category) else Decimal("0")
    market_type = Decimal("0.05") if _compatible_type(left.market_type, right.market_type) else Decimal("0")
    confidence = (
        jaccard * Decimal("0.25")
        + sequence * Decimal("0.15")
        + participant_overlap * Decimal("0.35")
        + time_score
        + category
        + market_type
    )
    warnings = [time_warning] if time_warning else []
    return min(Decimal("1"), confidence), warnings, (
        f"event_tokens={jaccard:.3f}; text={sequence:.3f}; "
        f"participants={participant_overlap:.3f}; time={time_score:.3f}"
    )


def _participant_overlap(left: EventGroup, right: EventGroup) -> Decimal:
    left_tokens = set().union(*(outcome_tokens(market) for market in left.markets))
    right_tokens = set().union(*(outcome_tokens(market) for market in right.markets))
    canonical_left = {token for token in left_tokens if "_" in token}
    canonical_right = {token for token in right_tokens if "_" in token}
    if canonical_left or canonical_right:
        return Decimal(len(canonical_left & canonical_right)) / Decimal(
            max(len(canonical_left), len(canonical_right), 1)
        )
    return Decimal(len(left_tokens & right_tokens)) / Decimal(
        max(len(left_tokens), len(right_tokens), 1)
    )


def _time_score(left: EventGroup, right: EventGroup) -> tuple[Decimal, str | None]:
    left_time = left.start_time or left.close_time
    right_time = right.start_time or right.close_time
    if not left_time or not right_time:
        return Decimal("0.03"), "Missing comparable event time."
    drift = abs((left_time - right_time).total_seconds())
    if drift <= 3600:
        return Decimal("0.15"), None
    if drift <= 86400:
        return Decimal("0.11"), None
    if drift <= 172800:
        return Decimal("0.04"), f"Event times differ by {drift / 86400:.1f} days."
    return Decimal("0"), f"Event times differ by {drift / 86400:.1f} days."


def _assign_outcomes(
    kalshi: tuple[VenueMarket, ...],
    poly: tuple[VenueMarket, ...],
    minimum: Decimal,
) -> list[MatchedMarket]:
    scores = [[_outcome_score(left, right) for right in poly] for left in kalshi]
    assignments = _maximum_weight_assignment(scores)
    result: list[MatchedMarket] = []
    for left_index, right_index in assignments:
        score = scores[left_index][right_index]
        if score < minimum:
            continue
        left = kalshi[left_index]
        right = poly[right_index]
        result.append(
            MatchedMarket(
                match_id=f"{left.market_id}::{right.market_id}",
                kalshi=left,
                polymarket_us=right,
                confidence=score.quantize(Decimal("0.0001")),
                relation="identity",
                reasoning=f"outcome_similarity={score:.3f}",
            )
        )
    return result


def _outcome_score(left: VenueMarket, right: VenueMarket) -> Decimal:
    left_tokens = outcome_tokens(left)
    right_tokens = outcome_tokens(right)
    overlap = Decimal(len(left_tokens & right_tokens)) / Decimal(
        max(len(left_tokens), len(right_tokens), 1)
    )
    sequence = Decimal(
        str(
            SequenceMatcher(
                None,
                normalize_text(left.yes_label or left.title),
                normalize_text(right.yes_label or right.title),
            ).ratio()
        )
    )
    signature_left = token_set(market_signature(left))
    signature_right = token_set(market_signature(right))
    signature = Decimal(len(signature_left & signature_right)) / Decimal(
        len(signature_left | signature_right) or 1
    )
    return min(Decimal("1"), overlap * Decimal("0.6") + sequence * Decimal("0.25") + signature * Decimal("0.15"))


def _maximum_weight_assignment(scores: list[list[Decimal]]) -> list[tuple[int, int]]:
    if not scores or not scores[0]:
        return []
    rows = len(scores)
    cols = len(scores[0])
    size = max(rows, cols)
    weights = [
        [float(scores[row][col]) if row < rows and col < cols else 0.0 for col in range(size)]
        for row in range(size)
    ]
    maximum = max(max(row) for row in weights)
    cost = [[maximum - value for value in row] for row in weights]
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for i in range(1, size + 1):
        p[0] = i
        minv = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        j0 = 0
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if current < minv[j]:
                    minv[j] = current
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return [
        (p[column] - 1, column - 1)
        for column in range(1, size + 1)
        if 0 < p[column] <= rows and column <= cols
    ]


def _same(left: str | None, right: str | None) -> bool:
    return bool(left and right and normalize_text(left) == normalize_text(right))


def _compatible_type(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    aliases = {
        "moneyline": {"moneyline", "game", "binary", "winner"},
        "future": {"future", "futures", "winner"},
        "spread": {"spread"},
        "total": {"total", "over under", "overunder"},
    }
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    return any(left_norm in values and right_norm in values for values in aliases.values()) or left_norm == right_norm


def _type_family(value: str | None) -> str:
    normalized = normalize_text(value)
    aliases = {
        "moneyline": {"moneyline", "game", "binary", "winner"},
        "future": {"future", "futures"},
        "spread": {"spread", "handicap"},
        "total": {"total", "over under", "overunder"},
    }
    for family, values in aliases.items():
        if normalized in values:
            return family
    return normalized or "unknown"
