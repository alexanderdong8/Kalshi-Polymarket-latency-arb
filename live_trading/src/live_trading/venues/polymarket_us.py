from __future__ import annotations

import asyncio
import json
import re
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
    return market_variants_from_api(raw)[0]


def market_variants_from_api(raw: dict[str, Any]) -> list[VenueMarket]:
    slug = str(raw.get("slug") or raw.get("marketSlug") or "")
    sides = raw.get("marketSides") or []
    long_side = next((side for side in sides if side.get("long") is True), None) or (sides[0] if sides else {})
    short_side = next((side for side in sides if side.get("long") is False), None) or (sides[1] if len(sides) > 1 else {})
    base_id = str(raw.get("id") or slug)

    def variant(side: dict[str, Any], opposite: dict[str, Any], label: str) -> VenueMarket:
        enriched = {**raw, "outcome_side": label}
        yes_label = _side_outcome_label(raw, side, label)
        no_label = _side_outcome_label(raw, opposite, "short" if label == "long" else "long")
        return VenueMarket(
            venue="polymarket_us",
            market_id=f"{base_id}:{label}",
            ticker=None,
            slug=slug,
            title=str(raw.get("question") or raw.get("title") or slug),
            category=raw.get("category"),
            market_type=raw.get("marketType") or raw.get("sportsMarketType"),
            start_time=parse_ts(raw.get("gameStartTime") or raw.get("startDate")),
            close_time=parse_ts(raw.get("endDate") or raw.get("closeTime")),
            expiration_time=parse_ts(raw.get("endDate") or raw.get("expirationTime")),
            yes_label=yes_label,
            no_label=no_label,
            yes_symbol=str(side.get("id") or f"{slug}:{label}"),
            no_symbol=str(opposite.get("id") or f"{slug}:{'short' if label == 'long' else 'long'}"),
            description=raw.get("description"),
            rules=raw.get("resolutionSource") or raw.get("description"),
            active=bool(raw.get("active", True)) and not bool(raw.get("closed", False)),
            raw=enriched,
        )

    variants = [variant(long_side, short_side, "long")]
    if short_side and short_side != long_side:
        variants.append(variant(short_side, long_side, "short"))
    return variants


class PolymarketUSClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def list_active_markets(
        self,
        categories: list[str] | None = None,
        limit: int = 1000,
        timeout_seconds: float = 30,
        max_pages: int | None = None,
        recent_after: datetime | None = None,
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
                    for market in market_variants_from_api(raw):
                        if (
                            market.active
                            and _category_allowed(market.category, categories)
                            and _recent_enough(market, recent_after)
                        ):
                            markets.append(market)
                if len(rows) < int(params["limit"]) or (max_pages is not None and pages_seen >= max_pages):
                    break
                params["offset"] = int(params["offset"]) + int(params["limit"])
        return markets[:limit]

    async def fetch_event_markets(self, identifier: str, *, title: str | None = None) -> list[VenueMarket]:
        identifier = identifier.strip()
        if not identifier and not title:
            return []
        params: dict[str, Any] = {
            "active": "true",
            "closed": "false",
            "limit": 500,
            "offset": 0,
        }
        wanted = identifier.casefold()
        title_wanted = title or identifier
        normalized_title = _normalize_event_text(title_wanted)
        wanted_tokens = _event_tokens(title_wanted)
        best_fuzzy: tuple[float, list[VenueMarket]] | None = None
        async with aiohttp.ClientSession() as session:
            for _page in range(30):
                url = f"{self.settings.polymarket_gateway_base.rstrip('/')}/v1/events?{urlencode(params)}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
                rows = list(payload.get("events") or [])
                for raw in rows:
                    values = {
                        str(raw.get("id") or "").casefold(),
                        str(raw.get("ticker") or "").casefold(),
                        str(raw.get("slug") or "").casefold(),
                    }
                    event_title = str(raw.get("title") or raw.get("description") or "")
                    markets = [
                        variant
                        for market in raw.get("markets") or []
                        for variant in market_variants_from_api(market)
                    ]
                    if (
                        (wanted and wanted in values)
                        or (normalized_title and _normalize_event_text(event_title) == normalized_title)
                    ):
                        return _event_outcome_markets(raw, markets)
                    score = _event_title_score(wanted_tokens, event_title)
                    if score >= 0.82 and (best_fuzzy is None or score > best_fuzzy[0]):
                        best_fuzzy = (score, _event_outcome_markets(raw, markets))
                if len(rows) < int(params["limit"]):
                    break
                params["offset"] = int(params["offset"]) + int(params["limit"])
        if best_fuzzy is not None:
            return best_fuzzy[1]
        return []

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


def _recent_enough(market: VenueMarket, recent_after: datetime | None) -> bool:
    if recent_after is None:
        return True
    marker = _recent_marker(market)
    return marker is not None and marker >= recent_after


def _recent_marker(market: VenueMarket) -> datetime | None:
    for key in (
        "createdAt",
        "created_at",
        "createdDate",
        "openTime",
        "open_time",
        "startDate",
        "gameStartTime",
        "endDate",
    ):
        marker = parse_ts(market.raw.get(key))
        if marker is not None:
            return marker
    return market.start_time or market.close_time or market.expiration_time


def _event_outcome_markets(raw_event: dict[str, Any], markets: list[VenueMarket]) -> list[VenueMarket]:
    if len(raw_event.get("markets") or []) <= 1:
        return markets
    long_only = [row for row in markets if row.raw.get("outcome_side") == "long"]
    return long_only or markets


def _side_outcome_label(raw: dict[str, Any], side: dict[str, Any], label: str) -> str:
    description = str(side.get("description") or "").strip()
    if description and description.casefold() not in {"yes", "no"}:
        return description
    team = side.get("team") if isinstance(side.get("team"), dict) else {}
    team_name = str(team.get("name") or team.get("safeName") or "").strip()
    if team_name:
        return team_name
    if label == "long":
        question_label = _outcome_from_question(
            str(raw.get("question") or raw.get("title") or raw.get("slug") or "")
        )
        if question_label:
            return question_label
    return description or ("Yes" if label == "long" else "No")


def _outcome_from_question(question: str) -> str | None:
    lowered = question.casefold()
    if " end in a draw" in lowered or " end in draw" in lowered:
        return "Tie"
    match = re.search(r"will\s+(.+?)\s+win\b", question, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "game",
    "in",
    "market",
    "match",
    "of",
    "on",
    "or",
    "the",
    "to",
    "v",
    "versus",
    "vs",
    "will",
    "win",
    "winner",
}


def _normalize_event_text(value: str | None) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\bvs\.?\b|\bv\.?\b|\bversus\b", " vs ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _event_tokens(value: str | None) -> set[str]:
    return {
        token
        for token in _normalize_event_text(value).split()
        if token not in _TOKEN_STOPWORDS and len(token) >= 2
    }


def _event_title_score(wanted_tokens: set[str], event_title: str | None) -> float:
    if not wanted_tokens:
        return 0
    event_tokens = _event_tokens(event_title)
    if not event_tokens:
        return 0
    return len(wanted_tokens & event_tokens) / max(len(wanted_tokens), 1)
