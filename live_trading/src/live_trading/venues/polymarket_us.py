from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode, urlparse

import aiohttp
import websockets

from ..auth import polymarket_us_headers
from ..books import parse_ts, polymarket_us_book_state, polymarket_us_lite_book_state
from ..config import Settings
from ..models import BookState, VenueMarket
from ..shards import merge_sharded_streams, shard_items


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
        timeout_seconds: float = 30,
        max_pages: int | None = None,
    ) -> list[VenueMarket]:
        params: dict[str, Any] = {"active": "true", "closed": "false", "limit": min(limit, 500), "offset": 0}
        if categories:
            params["categories"] = ",".join(categories)
        markets: list[VenueMarket] = []
        pages_seen = 0
        async with aiohttp.ClientSession() as session:
            while len(markets) < limit:
                pages_seen += 1
                url = f"{self.settings.polymarket_gateway_base.rstrip('/')}/v1/markets?{urlencode(params)}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as resp:
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
                if len(rows) < int(params["limit"]) or (max_pages is not None and pages_seen >= max_pages):
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

    async def stream_orderbooks(
        self,
        slugs: list[str],
        batch_size: int = 100,
        *,
        lite_slugs: list[str] | None = None,
        on_reconnect=None,
    ) -> AsyncIterator[BookState]:
        lite_slugs = lite_slugs or []
        full_slugs = [slug for slug in slugs if slug not in set(lite_slugs)]
        subscription_shards = [
            ("SUBSCRIPTION_TYPE_MARKET_DATA", shard)
            for shard in shard_items(full_slugs, min(batch_size, 100))
        ] + [
            ("SUBSCRIPTION_TYPE_MARKET_DATA_LITE", shard)
            for shard in shard_items(lite_slugs, min(batch_size, 100))
        ]
        if not subscription_shards:
            return
        headers = self._ws_headers()

        async def worker(shard: tuple[str, list[str]], shard_id: int) -> AsyncIterator[BookState]:
            subscription_type, batch = shard
            async for state in self._stream_batch(batch, headers, subscription_type, shard_id):
                yield state

        async for state in merge_sharded_streams(subscription_shards, worker, on_reconnect=on_reconnect):
            yield state

    async def _stream_batch(
        self,
        slugs: list[str],
        headers: dict[str, str],
        subscription_type: str = "SUBSCRIPTION_TYPE_MARKET_DATA",
        shard_id: int = 0,
    ) -> AsyncIterator[BookState]:
        request_id = f"live-trading-market-data-{shard_id}"
        subscribe = {
            "subscribe": {
                "requestId": request_id,
                "subscriptionType": subscription_type,
                "marketSlugs": slugs,
                "responsesDebounced": False,
            }
        }
        async with websockets.connect(self.settings.polymarket_ws_url, additional_headers=headers) as ws:
            await ws.send(json.dumps(subscribe))
            async for raw_message in ws:
                received = datetime.now(timezone.utc)
                received_monotonic_ns = time.perf_counter_ns()
                payload = json.loads(raw_message)
                market_data = payload.get("marketData") or payload.get("market_data")
                if market_data:
                    yield polymarket_us_book_state(
                        str(market_data.get("marketSlug") or ""),
                        market_data,
                        received,
                        received_monotonic_ns,
                    )
                market_data_lite = payload.get("marketDataLite") or payload.get("market_data_lite")
                if market_data_lite:
                    yield polymarket_us_lite_book_state(
                        str(market_data_lite.get("marketSlug") or ""),
                        market_data_lite,
                        received,
                        received_monotonic_ns,
                    )

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
