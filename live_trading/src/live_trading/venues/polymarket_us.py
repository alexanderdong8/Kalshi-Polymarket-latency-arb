from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode, urlparse

import aiohttp
import websockets

from ..auth import polymarket_us_headers
from ..books import parse_ts, polymarket_us_book_state
from ..config import Settings
from ..models import BookState, VenueMarket


def market_from_api(raw: dict[str, Any]) -> VenueMarket:
    slug = str(raw.get("slug") or raw.get("marketSlug") or "")
    sides = raw.get("marketSides") or []
    long_side = next((side for side in sides if side.get("long") is True), None) or (sides[0] if sides else {})
    short_side = next((side for side in sides if side.get("long") is False), None) or (sides[1] if len(sides) > 1 else {})
    return VenueMarket(
        venue="polymarket_us",
        market_id=str(raw.get("id") or slug),
        ticker=None,
        slug=slug,
        title=str(raw.get("question") or raw.get("title") or slug),
        category=raw.get("category"),
        market_type=raw.get("marketType") or raw.get("sportsMarketType"),
        start_time=parse_ts(raw.get("gameStartTime") or raw.get("startDate")),
        close_time=parse_ts(raw.get("endDate") or raw.get("closeTime")),
        expiration_time=parse_ts(raw.get("endDate") or raw.get("expirationTime")),
        yes_label=str(long_side.get("description") or "Yes"),
        no_label=str(short_side.get("description") or "No"),
        yes_symbol=str(long_side.get("id") or slug),
        no_symbol=str(short_side.get("id") or f"{slug}:NO"),
        description=raw.get("description"),
        rules=raw.get("resolutionSource") or raw.get("description"),
        active=bool(raw.get("active", True)) and not bool(raw.get("closed", False)),
        raw=raw,
    )


class PolymarketUSClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def list_active_markets(
        self,
        categories: list[str] | None = None,
        limit: int = 1000,
    ) -> list[VenueMarket]:
        params: dict[str, Any] = {"active": "true", "closed": "false", "limit": min(limit, 500), "offset": 0}
        if categories:
            params["categories"] = ",".join(categories)
        markets: list[VenueMarket] = []
        async with aiohttp.ClientSession() as session:
            while len(markets) < limit:
                url = f"{self.settings.polymarket_gateway_base.rstrip('/')}/v1/markets?{urlencode(params)}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
                rows = payload.get("markets") if isinstance(payload, dict) else payload
                rows = rows or []
                if not rows:
                    break
                for raw in rows:
                    market = market_from_api(raw)
                    if market.active and _category_allowed(market.category, categories):
                        markets.append(market)
                if len(rows) < int(params["limit"]):
                    break
                params["offset"] = int(params["offset"]) + int(params["limit"])
        return markets[:limit]

    async def fetch_book(self, slug: str) -> BookState:
        url = f"{self.settings.polymarket_gateway_base.rstrip('/')}/v1/markets/{slug}/book"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        return polymarket_us_book_state(slug, payload.get("marketData") or payload)

    async def stream_orderbooks(self, slugs: list[str], batch_size: int = 100) -> AsyncIterator[BookState]:
        if not slugs:
            return
        headers = self._ws_headers()
        while True:
            try:
                for batch in _chunks(slugs, batch_size):
                    async for state in self._stream_batch(batch, headers):
                        yield state
            except Exception:
                await asyncio.sleep(2)

    async def _stream_batch(self, slugs: list[str], headers: dict[str, str]) -> AsyncIterator[BookState]:
        request_id = "live-trading-market-data"
        subscribe = {
            "subscribe": {
                "requestId": request_id,
                "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
                "marketSlugs": slugs,
            }
        }
        async with websockets.connect(self.settings.polymarket_ws_url, additional_headers=headers) as ws:
            await ws.send(json.dumps(subscribe))
            async for raw_message in ws:
                received = datetime.now(timezone.utc)
                payload = json.loads(raw_message)
                market_data = payload.get("marketData") or payload.get("market_data")
                if market_data:
                    yield polymarket_us_book_state(str(market_data.get("marketSlug") or ""), market_data, received)

    def _ws_headers(self) -> dict[str, str]:
        if not self.settings.polymarket_key_id or not self.settings.polymarket_secret_key:
            raise RuntimeError("Polymarket US WebSocket requires POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY.")
        path = urlparse(self.settings.polymarket_ws_url).path
        return polymarket_us_headers(self.settings.polymarket_key_id, self.settings.polymarket_secret_key, "GET", path)


def _category_allowed(category: str | None, categories: list[str] | None) -> bool:
    if not categories:
        return True
    if not category:
        return False
    wanted = {item.strip().lower() for item in categories}
    return category.lower() in wanted


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]

