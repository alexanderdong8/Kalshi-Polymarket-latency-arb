from __future__ import annotations

import re
import unicodedata
from datetime import datetime


ROUND_MARKERS = (
    "round of 16",
    "round of 32",
    "quarterfinal",
    "semifinal",
    "final",
    "knockout stages",
    "qualify from group",
)
PAYOUT_MARKERS = (
    "split payout",
    "split payouts",
    "divided by the number",
    "last fair market",
    "50 50",
)
CANCELLATION_MARKERS = (
    "canceled",
    "cancelled",
    "postponed",
    "rescheduled",
)
PARTY_MARKERS = (
    "democratic",
    "republican",
    "libertarian",
    "green party",
    "independent",
)
OUTCOME_STAGE_MARKERS = (
    "shortlist",
)


def strict_equivalence_rejection(left: str, right: str) -> str | None:
    """Return a reason when two rule descriptions cannot be locked complements."""
    left_norm = normalize(left)
    right_norm = normalize(right)

    reason = _exclusive_marker_rejection(left_norm, right_norm, ROUND_MARKERS, "competition round")
    if reason:
        return reason
    reason = _exclusive_marker_rejection(left_norm, right_norm, PARTY_MARKERS, "party orientation")
    if reason:
        return reason
    reason = _exclusive_marker_rejection(left_norm, right_norm, OUTCOME_STAGE_MARKERS, "outcome stage")
    if reason:
        return reason
    if ("make the cut" in left_norm) != ("make the cut" in right_norm):
        return "golf cut-versus-winner mismatch"
    left_stage = _sports_stage_markers(left_norm)
    right_stage = _sports_stage_markers(right_norm)
    if (left_stage or right_stage) and left_stage != right_stage:
        return "competition stage mismatch"

    left_districts = set(re.findall(r"\b[a-z]{2}\s*\d{1,2}\b", left_norm))
    right_districts = set(re.findall(r"\b[a-z]{2}\s*\d{1,2}\b", right_norm))
    if (left_districts or right_districts) and left_districts != right_districts:
        return "district mismatch"

    left_lines = _extract_lines(left_norm)
    right_lines = _extract_lines(right_norm)
    if (left_lines or right_lines) and left_lines != right_lines:
        return "spread, total, or threshold mismatch"

    left_dates = set(_extract_dates(left_norm))
    right_dates = set(_extract_dates(right_norm))
    if left_dates and right_dates and left_dates != right_dates:
        return "explicit date mismatch"

    reason = _one_sided_marker_rejection(left_norm, right_norm, PAYOUT_MARKERS, "payout treatment")
    if reason:
        return reason
    reason = _one_sided_marker_rejection(left_norm, right_norm, CANCELLATION_MARKERS, "cancellation treatment")
    if reason:
        return reason
    return None


def strict_outcome_label_rejection(polymarket_title: str, kalshi_yes_label: str) -> str | None:
    quoted = re.findall(r'"([^"]+)"', polymarket_title)
    if not quoted:
        return None
    poly_terms = _semantic_term_set(" ".join(quoted))
    kalshi_terms = _semantic_term_set(kalshi_yes_label)
    if poly_terms and kalshi_terms and poly_terms != kalshi_terms:
        return "quoted outcome label mismatch"
    return None


def strict_match_rejection(
    left: str,
    right: str,
    left_resolution: str | None = None,
    right_resolution: str | None = None,
    *,
    max_resolution_drift_days: float = 3.0,
) -> str | None:
    reason = strict_equivalence_rejection(left, right)
    if reason:
        return reason
    left_winner = _winner_contract_parts(normalize(left))
    right_winner = _winner_contract_parts(normalize(right))
    if left_winner and right_winner:
        if left_winner["subject"] != right_winner["subject"]:
            return "outcome subject mismatch"
        if left_winner["target_tokens"] != right_winner["target_tokens"]:
            return "event identity mismatch"
    left_date = _parse_optional_iso(left_resolution)
    right_date = _parse_optional_iso(right_resolution)
    if left_date and right_date:
        drift_days = abs((left_date - right_date).total_seconds()) / 86_400
        if drift_days > max_resolution_drift_days:
            return "resolution date drift exceeds strict limit"
    return None


def strict_market_rejection(match) -> str | None:
    reason = strict_match_rejection(
        match.polymarket.title,
        match.kalshi.title,
        match.polymarket.resolution_date,
        match.kalshi.resolution_date,
    )
    if reason:
        return reason
    return strict_outcome_label_rejection(match.polymarket.title, match.kalshi.yes.label)


def normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.+-]+", " ", ascii_value.lower())).strip()


def _extract_lines(value: str) -> set[str]:
    patterns = [
        r"\b(?:over|under|above|below|more than|less than)\s+(-?\d+(?:\.\d+)?)\b",
        r"(?<!\d)([+-]\d+(?:\.\d+)?)\b",
    ]
    return {
        match.group(0).replace(" ", "")
        for pattern in patterns
        for match in re.finditer(pattern, value)
    }


def _extract_dates(value: str) -> list[str]:
    return re.findall(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\s+\d{1,2}(?:\s+\d{4})?\b",
        value,
    )


def _exclusive_marker_rejection(left: str, right: str, markers: tuple[str, ...], label: str) -> str | None:
    left_found = {marker for marker in markers if marker in left}
    right_found = {marker for marker in markers if marker in right}
    if left_found != right_found and (left_found or right_found):
        return f"{label} mismatch"
    return None


def _one_sided_marker_rejection(left: str, right: str, markers: tuple[str, ...], label: str) -> str | None:
    left_found = any(marker in left for marker in markers)
    right_found = any(marker in right for marker in markers)
    if left_found != right_found:
        return f"{label} requires manual review"
    return None


def _sports_stage_markers(value: str) -> set[str]:
    markers = set()
    if re.search(r"\bchampionships?\b", value):
        markers.add("championship")
    if re.search(r"\bplayoffs?\b", value):
        markers.add("playoffs")
    return markers


def _winner_contract_parts(value: str) -> dict[str, str | frozenset[str]] | None:
    match = re.match(
        r"^will (.+?) (?:win|make the cut|reach|finish 1st|finish first) (.+?)[?]?$",
        value,
    )
    if not match:
        return None
    subject, target = match.groups()
    target_tokens = frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", target)
        if token not in {"the", "a", "an", "in", "at", "of", "to", "tournament"}
        and not re.fullmatch(r"20\d{2}", token)
    )
    return {"subject": subject.strip(), "target_tokens": target_tokens}


def _parse_optional_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _semantic_term_set(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", normalize(value))
        if token not in {"or", "and", "the", "a", "an"}
    )
