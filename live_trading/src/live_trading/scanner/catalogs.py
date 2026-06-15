from __future__ import annotations

import asyncio
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
    ) -> tuple[list[VenueMarket], list[VenueMarket], list[str]]:
        results = await asyncio.gather(
            KalshiClient(self.settings).list_active_markets(
                categories=categories, limit=limit, timeout_seconds=20
            ),
            PolymarketUSClient(self.settings).list_active_markets(
                categories=categories, limit=limit, timeout_seconds=20
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
        if len(kalshi) >= limit:
            errors.append(f"Kalshi catalog reached the configured {limit}-market scan limit.")
        if len(polymarket) >= limit:
            errors.append(f"Polymarket US catalog reached the configured {limit}-market scan limit.")
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
