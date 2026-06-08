from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import websockets

from ..auth import kalshi_headers
from ..books import BookStore
from ..books.kalshi import KalshiOrderBook, SequenceGap
from ..jsonl import JsonlWriter
from ..models import Credentials, Endpoints, EventSpec
from ._reconnect import Backoff


async def run_kalshi_stream(
    event: EventSpec,
    creds: Credentials,
    endpoints: Endpoints,
    store: BookStore,
    jsonl: JsonlWriter,
) -> None:
    if not creds.has_kalshi:
        await jsonl.write_event(
            "error",
            "KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_{PATH|PEM} required; Kalshi stream disabled.",
            kind="lifecycle",
        )
        return

    backoff = Backoff()
    while True:
        books = {
            o.kalshi_ticker: KalshiOrderBook(market_ticker=o.kalshi_ticker, outcome_name=o.name)
            for o in event.outcomes
        }
        try:
            await _run_one_session(event, creds, endpoints, store, jsonl, books, backoff)
        except SequenceGap as exc:
            await jsonl.write_event("error", {"reason": "sequence_gap", "detail": str(exc)}, kind="lifecycle")
        except Exception as exc:  # network error, ws closed, json decode, etc.
            await jsonl.write_event(
                "error",
                {"reason": type(exc).__name__, "detail": str(exc)},
                kind="lifecycle",
            )
        backoff.mark_disconnected()
        await jsonl.write_event("info", "reconnecting after backoff", kind="lifecycle")
        await backoff.sleep()


async def _run_one_session(
    event: EventSpec,
    creds: Credentials,
    endpoints: Endpoints,
    store: BookStore,
    jsonl: JsonlWriter,
    books: dict[str, KalshiOrderBook],
    backoff: Backoff,
) -> None:
    path = urlparse(endpoints.kalshi_ws_url).path or "/"
    headers = kalshi_headers(creds.kalshi_key_id, creds.kalshi_private_key_pem, "GET", path)
    subscribe = {
        "id": 1,
        "cmd": "subscribe",
        "params": {
            "channels": ["orderbook_delta", "ticker", "trade"],
            "market_tickers": list(event.kalshi_tickers),
        },
    }
    await jsonl.write_event("info", {"endpoint": endpoints.kalshi_ws_url}, kind="lifecycle")
    async with websockets.connect(
        endpoints.kalshi_ws_url,
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
            msg = payload.get("msg") or {}
            ticker = msg.get("market_ticker") or msg.get("ticker")
            book = books.get(ticker)
            msg_type = payload.get("type")
            if not book or not msg_type:
                continue
            if msg_type == "orderbook_snapshot":
                snap = book.apply_snapshot(payload, received_ts=received)
                await store.set(snap)
            elif msg_type == "orderbook_delta":
                snap = book.apply_delta(payload, received_ts=received)
                await store.set(snap)
            elif msg_type == "trade":
                book.apply_trade(payload)
                await store.set(book.snapshot(received_ts=received))
            elif msg_type == "ticker":
                # No book change; just refresh received_ts so the UI shows the venue is alive.
                await store.set(book.snapshot(received_ts=received))
