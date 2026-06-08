from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp
import websockets

from ..auth import polymarket_us_headers
from ..books import BookStore
from ..books.polymarket_us import PolymarketUsBook
from ..jsonl import JsonlWriter
from ..models import Credentials, Endpoints, EventSpec
from ._reconnect import Backoff


async def run_polymarket_stream(
    event: EventSpec,
    creds: Credentials,
    endpoints: Endpoints,
    store: BookStore,
    jsonl: JsonlWriter,
) -> None:
    if not creds.has_polymarket:
        await jsonl.write_event(
            "error",
            "POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY required; Polymarket stream disabled.",
            kind="lifecycle",
        )
        return

    backoff = Backoff()
    while True:
        books = {
            o.polymarket_slug: PolymarketUsBook(market_slug=o.polymarket_slug, outcome_name=o.name)
            for o in event.outcomes
        }
        try:
            await _seed_from_rest(event, creds, endpoints, store, jsonl, books)
            await _run_one_session(event, creds, endpoints, store, jsonl, books, backoff)
        except Exception as exc:
            await jsonl.write_event(
                "error",
                {"reason": type(exc).__name__, "detail": str(exc)},
                kind="lifecycle",
            )
        backoff.mark_disconnected()
        await jsonl.write_event("info", "reconnecting after backoff", kind="lifecycle")
        await backoff.sleep()


async def _seed_from_rest(
    event: EventSpec,
    creds: Credentials,
    endpoints: Endpoints,
    store: BookStore,
    jsonl: JsonlWriter,
    books: dict[str, PolymarketUsBook],
) -> None:
    """REST-hydrate each outcome's book so the TUI shows depth before the first WS message."""
    async with aiohttp.ClientSession() as session:
        for slug, book in books.items():
            url = f"{endpoints.polymarket_gateway_base.rstrip('/')}/v1/markets/{slug}/book"
            path = urlparse(url).path
            headers = polymarket_us_headers(
                creds.polymarket_us_key_id, creds.polymarket_us_secret_key, "GET", path
            )
            try:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
            except Exception as exc:
                await jsonl.write_event(
                    "error",
                    {"reason": "seed_failed", "slug": slug, "detail": str(exc)},
                    kind="lifecycle",
                )
                continue
            await jsonl.write_event("in", {"slug": slug, "rest_book": payload}, kind="rest_seed")
            snap = book.apply_book_payload(payload, received_ts=datetime.now(timezone.utc))
            await store.set(snap)


async def _run_one_session(
    event: EventSpec,
    creds: Credentials,
    endpoints: Endpoints,
    store: BookStore,
    jsonl: JsonlWriter,
    books: dict[str, PolymarketUsBook],
    backoff: Backoff,
) -> None:
    path = urlparse(endpoints.polymarket_ws_url).path or "/"
    headers = polymarket_us_headers(
        creds.polymarket_us_key_id, creds.polymarket_us_secret_key, "GET", path
    )
    subscribe = {
        "subscribe": {
            "requestId": "trade-system",
            "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
            "marketSlugs": list(event.polymarket_slugs),
        }
    }
    await jsonl.write_event("info", {"endpoint": endpoints.polymarket_ws_url}, kind="lifecycle")
    async with websockets.connect(
        endpoints.polymarket_ws_url,
        additional_headers=headers,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
    ) as ws:
        backoff.mark_connected()
        await ws.send(json.dumps(subscribe))
        await jsonl.write_event("out", subscribe, kind="subscribe")
        async for raw in ws:
            received = datetime.now(timezone.utc)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await jsonl.write_event("in", {"raw": raw}, kind="invalid_json")
                continue
            await jsonl.write_event("in", payload)
            market_data = payload.get("marketData") or payload.get("market_data")
            if not isinstance(market_data, dict):
                continue
            slug = market_data.get("marketSlug") or market_data.get("market_slug")
            book = books.get(slug)
            if book is None:
                continue
            snap = book.apply_market_data(market_data, received_ts=received)
            await store.set(snap)
