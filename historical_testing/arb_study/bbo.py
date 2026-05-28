from __future__ import annotations

import ast
import json
from collections import defaultdict
from datetime import datetime
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .archive import https_filesystem, parquet_url, remote_exists
from .models import BBOState, MatchedMarket


def load_polymarket_bbo(match: MatchedMarket, hour: str) -> list[BBOState]:
    url = parquet_url("polymarket", hour)
    if not remote_exists(url):
        return []

    market = (match.polymarket.contract_address or "").encode()
    yes_id = match.polymarket.yes.outcome_id
    no_id = match.polymarket.no.outcome_id
    fs = https_filesystem()
    with fs.open(url, "rb") as handle:
        table = pq.read_table(
            handle,
            columns=[
                "timestamp_received",
                "timestamp",
                "market",
                "event_type",
                "asset_id",
                "bids",
                "asks",
                "best_bid",
                "best_ask",
            ],
            filters=[
                ("market", "=", market),
                ("asset_id", "in", [yes_id, no_id]),
            ],
        )

    if table.num_rows == 0:
        return []

    df = table.to_pandas().sort_values("timestamp_received")
    yes_bid = yes_ask = no_bid = no_ask = None
    yes_bid_size = yes_ask_size = no_bid_size = no_ask_size = None
    states: list[BBOState] = []

    for row in df.itertuples(index=False):
        bid = _to_float(row.best_bid)
        ask = _to_float(row.best_ask)
        bid_size = ask_size = None

        if bid is None or ask is None:
            parsed_bid, bid_size = _best_bid_from_levels(row.bids)
            parsed_ask, ask_size = _best_ask_from_levels(row.asks)
            bid = bid if bid is not None else parsed_bid
            ask = ask if ask is not None else parsed_ask

        if row.asset_id == yes_id:
            yes_bid = bid if bid is not None else yes_bid
            yes_ask = ask if ask is not None else yes_ask
            yes_bid_size = bid_size if bid_size is not None else yes_bid_size
            yes_ask_size = ask_size if ask_size is not None else yes_ask_size
        elif row.asset_id == no_id:
            no_bid = bid if bid is not None else no_bid
            no_ask = ask if ask is not None else no_ask
            no_bid_size = bid_size if bid_size is not None else no_bid_size
            no_ask_size = ask_size if ask_size is not None else no_ask_size

        if None not in (yes_bid, yes_ask, no_bid, no_ask):
            states.append(
                BBOState(
                    timestamp=_timestamp(row.timestamp_received),
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                    yes_bid_size=yes_bid_size,
                    yes_ask_size=yes_ask_size,
                    no_bid_size=no_bid_size,
                    no_ask_size=no_ask_size,
                )
            )
    return states


def load_kalshi_bbo(match: MatchedMarket, hour: str) -> list[BBOState]:
    url = parquet_url("kalshi", hour)
    if not remote_exists(url):
        return []

    ticker = match.kalshi.slug or match.kalshi.yes.outcome_id
    fs = https_filesystem()
    with fs.open(url, "rb") as handle:
        table = pq.read_table(
            handle,
            columns=[
                "timestamp_received",
                "timestamp",
                "market_ticker",
                "event_type",
                "yes_bids",
                "no_bids",
                "price",
                "delta",
                "side",
            ],
            filters=[("market_ticker", "=", ticker)],
        )

    if table.num_rows == 0:
        return []

    df = table.to_pandas().sort_values("timestamp_received")
    yes_book: defaultdict[float, float] = defaultdict(float)
    no_book: defaultdict[float, float] = defaultdict(float)
    have_snapshot = False
    states: list[BBOState] = []

    for row in df.itertuples(index=False):
        if row.event_type == "orderbook_snapshot":
            yes_book = defaultdict(float)
            no_book = defaultdict(float)
            for price, size in _iter_struct_levels(row.yes_bids):
                yes_book[price] = size
            for price, size in _iter_struct_levels(row.no_bids):
                no_book[price] = size
            have_snapshot = True
        elif row.event_type == "orderbook_delta" and have_snapshot:
            price = _to_float(row.price)
            delta = _to_float(row.delta)
            if price is not None and delta is not None:
                book = yes_book if str(row.side).lower() == "yes" else no_book
                book[price] += delta
                if book[price] <= 1e-9:
                    book.pop(price, None)

        if not have_snapshot or not yes_book or not no_book:
            continue

        yes_bid, yes_bid_size = _best_book_bid(yes_book)
        no_bid, no_bid_size = _best_book_bid(no_book)
        if yes_bid is None or no_bid is None:
            continue

        states.append(
            BBOState(
                timestamp=_timestamp(row.timestamp_received),
                yes_bid=yes_bid,
                yes_ask=1.0 - no_bid,
                no_bid=no_bid,
                no_ask=1.0 - yes_bid,
                yes_bid_size=yes_bid_size,
                yes_ask_size=no_bid_size,
                no_bid_size=no_bid_size,
                no_ask_size=yes_bid_size,
            )
        )
    return states


def _timestamp(value: Any) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _best_book_bid(book: dict[float, float]) -> tuple[float | None, float | None]:
    live = [(price, size) for price, size in book.items() if size > 0]
    if not live:
        return None, None
    price, size = max(live, key=lambda item: item[0])
    return price, size


def _iter_struct_levels(levels: Any) -> list[tuple[float, float]]:
    if levels is None:
        return []
    try:
        if pd.isna(levels):
            return []
    except (TypeError, ValueError):
        pass
    parsed: list[tuple[float, float]] = []
    for item in list(levels):
        if isinstance(item, dict):
            price = _to_float(item.get("1") or item.get(1) or item.get("price"))
            size = _to_float(item.get("2") or item.get(2) or item.get("size"))
        else:
            price = _to_float(item[0])
            size = _to_float(item[1])
        if price is not None and size is not None and size > 0:
            parsed.append((price, size))
    return parsed


def _parse_levels(value: Any) -> list[tuple[float, float]]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        text = str(value).strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            try:
                raw = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return []
    return _iter_struct_levels(raw)


def _best_bid_from_levels(value: Any) -> tuple[float | None, float | None]:
    levels = _parse_levels(value)
    return max(levels, key=lambda item: item[0]) if levels else (None, None)


def _best_ask_from_levels(value: Any) -> tuple[float | None, float | None]:
    levels = _parse_levels(value)
    return min(levels, key=lambda item: item[0]) if levels else (None, None)

