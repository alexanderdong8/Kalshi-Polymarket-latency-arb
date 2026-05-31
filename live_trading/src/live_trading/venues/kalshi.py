from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode, urlparse

import aiohttp
import websockets

from ..auth import kalshi_headers, read_private_key
from ..books import KalshiOrderBook, parse_ts
from ..config import Settings
from ..models import BookState, VenueMarket
from ..shards import merge_sharded_streams, shard_items


def market_from_api(raw: dict[str, Any]) -> VenueMarket:
    ticker = str(raw.get("ticker") or "")
    rules = " ".join(
        str(raw.get(key) or "")
        for key in ("rules_primary", "rules_secondary", "settlement_sources")
        if raw.get(key)
    )
    return VenueMarket(
        venue="kalshi",
        market_id=ticker,
        ticker=ticker,
        slug=ticker,
        title=str(raw.get("title") or raw.get("yes_sub_title") or ticker),
        category=raw.get("category"),
        market_type=raw.get("market_type"),
        start_time=parse_ts(raw.get("open_time")),
        close_time=parse_ts(raw.get("close_time")),
        expiration_time=parse_ts(raw.get("expiration_time") or raw.get("latest_expiration_time")),
        yes_label=str(raw.get("yes_sub_title") or "Yes"),
        no_label=str(raw.get("no_sub_title") or "No"),
        yes_symbol=ticker,
        no_symbol=f"{ticker}:NO",
        description=raw.get("subtitle") or raw.get("title"),
        rules=rules or None,
        active=str(raw.get("status") or "").lower() in {"open", "active"},
        raw=raw,
    )


class KalshiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.private_key_pem = read_private_key(settings.kalshi_private_key_path, settings.kalshi_private_key_pem)

    async def list_active_markets(
        self,
        categories: list[str] | None = None,
        limit: int = 1000,
        timeout_seconds: float = 30,
        retries: int = 4,
        max_pages: int | None = None,
    ) -> list[VenueMarket]:
        page_limit = min(max(limit * 4, 100), 1000)
        params: dict[str, Any] = {"status": "open", "limit": page_limit}
        url = f"{self.settings.kalshi_api_base.rstrip('/')}/markets?{urlencode(params)}"
        markets: list[VenueMarket] = []
        pages_seen = 0
        async with aiohttp.ClientSession() as session:
            while url:
                pages_seen += 1
                payload = None
                for attempt in range(retries):
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as resp:
                        if resp.status == 429 and attempt < retries - 1:
                            await asyncio.sleep((1.5 * (attempt + 1)) + random.random())
                            continue
                        resp.raise_for_status()
                        payload = await resp.json()
                        break
                if payload is None:
                    break
                for raw in payload.get("markets") or []:
                    market = market_from_api(raw)
                    if _category_allowed(market.category, categories):
                        markets.append(market)
                cursor = payload.get("cursor")
                if not cursor or len(markets) >= limit or (max_pages is not None and pages_seen >= max_pages):
                    break
                url = f"{self.settings.kalshi_api_base.rstrip('/')}/markets?{urlencode(params | {'cursor': cursor})}"
        return markets[:limit]

    async def stream_orderbooks(
        self,
        tickers: list[str],
        batch_size: int = 100,
        on_reconnect=None,
    ) -> AsyncIterator[BookState]:
        if not tickers:
            return
        headers = self._ws_headers()
        shards = shard_items(tickers, min(batch_size, 100))

        async def worker(batch: list[str], shard_id: int) -> AsyncIterator[BookState]:
            books = {ticker: KalshiOrderBook(ticker, use_yes_price=True) for ticker in batch}
            async for state in self._stream_batch(batch, books, headers, shard_id):
                yield state

        async for state in merge_sharded_streams(shards, worker, on_reconnect=on_reconnect):
            yield state

    async def _stream_batch(
        self,
        tickers: list[str],
        books: dict[str, KalshiOrderBook],
        headers: dict[str, str],
        shard_id: int = 0,
    ) -> AsyncIterator[BookState]:
        subscribe = {
            "id": shard_id + 1,
            "cmd": "subscribe",
            "params": {"channels": ["orderbook_delta"], "market_tickers": tickers, "use_yes_price": True},
        }
        async with websockets.connect(self.settings.kalshi_ws_url, additional_headers=headers) as ws:
            await ws.send(json.dumps(subscribe))
            async for raw_message in ws:
                received = datetime.now(timezone.utc)
                received_monotonic_ns = time.perf_counter_ns()
                payload = json.loads(raw_message)
                msg = payload.get("msg") or {}
                ticker = msg.get("market_ticker")
                if not ticker:
                    continue
                book = books.setdefault(str(ticker), KalshiOrderBook(str(ticker)))
                if payload.get("type") == "orderbook_snapshot":
                    yield book.apply_snapshot(
                        payload,
                        received_ts=received,
                        received_monotonic_ns=received_monotonic_ns,
                    )
                elif payload.get("type") == "orderbook_delta":
                    yield book.apply_delta(
                        payload,
                        received_ts=received,
                        received_monotonic_ns=received_monotonic_ns,
                    )

    @staticmethod
    def subscription_update_message(sid: int, tickers: list[str], action: str, request_id: int = 1) -> dict[str, Any]:
        if action not in {"add_markets", "delete_markets", "get_snapshot"}:
            raise ValueError(f"Unsupported Kalshi subscription action: {action}")
        return {
            "id": request_id,
            "cmd": "update_subscription",
            "params": {"sid": sid, "market_tickers": tickers, "action": action},
        }

    def _ws_headers(self) -> dict[str, str]:
        if not self.settings.kalshi_api_key_id or not self.private_key_pem:
            raise RuntimeError("Kalshi WebSocket requires KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH or PEM.")
        path = urlparse(self.settings.kalshi_ws_url).path
        return kalshi_headers(self.settings.kalshi_api_key_id, self.private_key_pem, "GET", path)


def _category_allowed(category: str | None, categories: list[str] | None) -> bool:
    if not categories:
        return True
    if not category:
        return False
    wanted = {item.strip().lower() for item in categories}
    return category.lower() in wanted
