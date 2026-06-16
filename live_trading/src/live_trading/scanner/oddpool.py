from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import aiohttp

from ..config import Settings
from ..control.schemas import MarketSuggestion


class OddpoolClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(self.settings.oddpool_api_key)

    async def search_events(self, query: str, *, limit: int = 8) -> list[MarketSuggestion]:
        if not self.available:
            return []
        params = {
            "q": query,
            "status": "active",
            "sort_by": "volume",
            "limit": str(limit),
        }
        url = f"{self.settings.oddpool_api_base.rstrip('/')}/search/events"
        headers = {"X-API-Key": self.settings.oddpool_api_key or ""}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=6),
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        rows = _rows(payload)
        return [_suggestion(row) for row in rows[:limit]]


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("events", "results", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _suggestion(row: dict[str, Any]) -> MarketSuggestion:
    name = str(
        row.get("title")
        or row.get("event_title")
        or row.get("name")
        or row.get("event_id")
        or "Untitled event"
    )
    event_id = str(row.get("event_id") or row.get("id") or row.get("slug") or name)
    confidence = row.get("match_confidence") or row.get("confidence") or 0.9
    confidence_value = float(confidence)
    if confidence_value > 1:
        confidence_value = confidence_value / 100
    return MarketSuggestion(
        id=hashlib.sha1(f"oddpool:{event_id}".encode()).hexdigest()[:16],
        name=name,
        category=row.get("category"),
        close_time=_parse_time(
            row.get("close_time")
            or row.get("end_time")
            or row.get("expiration_time")
            or row.get("ends_at")
        ),
        outcome_count=int(row.get("outcome_count") or row.get("market_count") or 0),
        mapping_confidence=min(1.0, max(0.0, confidence_value)),
        kalshi_outcomes=_outcomes(row, "kalshi"),
        polymarket_outcomes=_outcomes(row, "polymarket"),
        warnings=["Oddpool cross-venue search result. Run scan/review before approval."],
        source="oddpool",
    )


def _outcomes(row: dict[str, Any], venue: str) -> list[str]:
    container = row.get(venue) or row.get(f"{venue}_markets") or row.get(f"{venue}_event")
    if isinstance(container, dict):
        markets = container.get("markets") or container.get("outcomes") or [container]
    elif isinstance(container, list):
        markets = container
    else:
        markets = []
    names: list[str] = []
    for item in markets:
        if not isinstance(item, dict):
            continue
        value = (
            item.get("outcome")
            or item.get("label")
            or item.get("title")
            or item.get("name")
            or item.get("ticker")
            or item.get("slug")
        )
        if value:
            names.append(str(value))
    if names:
        return names[:8]
    count = row.get(f"{venue}_market_count")
    return [f"{count} markets"] if count else []


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
