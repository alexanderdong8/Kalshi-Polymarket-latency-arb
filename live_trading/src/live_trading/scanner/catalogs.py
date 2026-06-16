from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from ..models import VenueMarket
from ..venues.kalshi import KalshiClient
from ..venues.polymarket_us import PolymarketUSClient


class CatalogService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def refresh(
        self,
        *,
        categories: list[str] | None,
        limit: int,
        lookback_days: int = 7,
        max_pages: int = 1,
        timeout_seconds: float = 8,
    ) -> tuple[list[VenueMarket], list[VenueMarket], list[str]]:
        recent_after = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        results = await asyncio.gather(
            KalshiClient(self.settings).list_active_markets(
                categories=categories,
                limit=limit,
                timeout_seconds=timeout_seconds,
                max_pages=max_pages,
                recent_after=recent_after,
            ),
            PolymarketUSClient(self.settings).list_active_markets(
                categories=categories,
                limit=limit,
                timeout_seconds=timeout_seconds,
                max_pages=max_pages,
                recent_after=recent_after,
            ),
            return_exceptions=True,
        )
        errors: list[str] = []
        kalshi = results[0] if isinstance(results[0], list) else []
        polymarket = results[1] if isinstance(results[1], list) else []
        if isinstance(results[0], Exception):
            errors.append(f"Kalshi catalog: {results[0]}")
        if isinstance(results[1], Exception):
            errors.append(f"Polymarket US catalog: {results[1]}")
        return kalshi, polymarket, errors


def market_payload(market: VenueMarket) -> dict[str, Any]:
    return {
        "venue": market.venue,
        "market_id": market.market_id,
        "ticker": market.ticker,
        "slug": market.slug,
        "title": market.title,
        "category": market.category,
        "market_type": market.market_type,
        "start_time": market.start_time.isoformat() if market.start_time else None,
        "close_time": market.close_time.isoformat() if market.close_time else None,
        "expiration_time": market.expiration_time.isoformat() if market.expiration_time else None,
        "yes_label": market.yes_label,
        "no_label": market.no_label,
        "description": market.description,
        "rules": market.rules,
        "raw": market.raw,
    }


def market_from_payload(payload: dict[str, Any]) -> VenueMarket:
    return VenueMarket(
        venue=payload["venue"],
        market_id=payload["market_id"],
        ticker=payload.get("ticker"),
        slug=payload.get("slug"),
        title=payload["title"],
        category=payload.get("category"),
        market_type=payload.get("market_type"),
        start_time=_parse_iso(payload.get("start_time")),
        close_time=_parse_iso(payload.get("close_time")),
        expiration_time=_parse_iso(payload.get("expiration_time")),
        yes_label=payload.get("yes_label") or "Yes",
        no_label=payload.get("no_label") or "No",
        description=payload.get("description"),
        rules=payload.get("rules"),
        raw=payload.get("raw") or {},
    )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
