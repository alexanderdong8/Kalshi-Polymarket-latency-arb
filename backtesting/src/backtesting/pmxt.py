from __future__ import annotations

import ast
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from live_trading.strategy.manifest import EventManifest
from live_trading.strategy.models import BookSnapshot, DepthLevel

from .models import ReplayUpdate

POLY_BASE = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
KALSHI_BASE = "https://r2kalshi.pmxt.dev/kalshi_orderbook_{hour}.parquet"


def load_updates(
    manifest: EventManifest,
    archive: dict[str, Any],
) -> list[ReplayUpdate]:
    fixture = archive.get("fixture")
    if fixture:
        return load_jsonl_fixture(Path(manifest.source_path.parent, fixture).resolve())
    hours = archive.get("hours")
    if not isinstance(hours, list) or not hours:
        raise ValueError("historical.archive.hours or historical.archive.fixture is required.")
    updates: list[ReplayUpdate] = []
    for hour in hours:
        updates.extend(_load_kalshi_hour(manifest, str(hour)))
        updates.extend(_load_polymarket_hour(manifest, str(hour)))
    updates.sort(key=lambda row: row.timestamp_received)
    return updates


def load_jsonl_fixture(path: Path) -> list[ReplayUpdate]:
    updates: list[ReplayUpdate] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        try:
            timestamp = _timestamp(raw["timestamp_received"])
            book = BookSnapshot(
                venue=raw["venue"],
                outcome_name=raw["outcome"],
                market_key=raw.get("market_key") or raw["outcome"],
                yes_bids=_levels(raw.get("yes_bids"), reverse=True),
                yes_asks=_levels(raw.get("yes_asks"), reverse=False),
                received_ts=timestamp,
                venue_ts=_timestamp(raw["venue_ts"]) if raw.get("venue_ts") else None,
                sequence=raw.get("sequence"),
                state=raw.get("state"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid replay fixture row {line_number}: {exc}") from exc
        updates.append(
            ReplayUpdate(
                timestamp_received=timestamp,
                book=book,
                fee_rate_bps=_decimal(raw.get("fee_rate_bps")),
            )
        )
    updates.sort(key=lambda row: row.timestamp_received)
    return updates


def validate_coverage(manifest: EventManifest, updates: Iterable[ReplayUpdate]) -> dict[str, Any]:
    seen: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    previous: datetime | None = None
    out_of_order = False
    for update in updates:
        if previous is not None and update.timestamp_received < previous:
            out_of_order = True
        previous = update.timestamp_received
        seen[(update.book.venue, update.book.outcome_name)].append(update.timestamp_received)
    missing = [
        f"{venue}:{outcome.name}"
        for outcome in manifest.event.outcomes
        for venue in ("kalshi", "polymarket_us")
        if not seen[(venue, outcome.name)]
    ]
    starts = [rows[0] for rows in seen.values() if rows]
    ends = [rows[-1] for rows in seen.values() if rows]
    overlap_start = max(starts) if starts else None
    overlap_end = min(ends) if ends else None
    valid = not missing and not out_of_order and overlap_start is not None and overlap_end is not None and overlap_start <= overlap_end
    return {
        "valid": valid,
        "missing_books": missing,
        "out_of_order": out_of_order,
        "overlap_start": overlap_start.isoformat() if overlap_start else None,
        "overlap_end": overlap_end.isoformat() if overlap_end else None,
        "updates": sum(len(rows) for rows in seen.values()),
    }


def _load_kalshi_hour(manifest: EventManifest, hour: str) -> list[ReplayUpdate]:
    import fsspec
    import pyarrow.parquet as pq

    tickers = list(manifest.event.kalshi_tickers)
    with fsspec.filesystem("https").open(KALSHI_BASE.format(hour=hour), "rb") as handle:
        table = pq.read_table(
            handle,
            columns=[
                "timestamp_received",
                "market_ticker",
                "event_type",
                "yes_bids",
                "no_bids",
                "price",
                "delta",
                "side",
            ],
            filters=[("market_ticker", "in", tickers)],
        )
    yes_books: dict[str, dict[Decimal, Decimal]] = defaultdict(dict)
    no_books: dict[str, dict[Decimal, Decimal]] = defaultdict(dict)
    have_snapshot: set[str] = set()
    outcome_by_ticker = {row.kalshi_ticker: row.name for row in manifest.event.outcomes}
    updates: list[ReplayUpdate] = []
    for row in table.to_pylist():
        ticker = _text(row["market_ticker"])
        if row["event_type"] == "orderbook_snapshot":
            yes_books[ticker] = dict(_struct_levels(row.get("yes_bids")))
            no_books[ticker] = dict(_struct_levels(row.get("no_bids")))
            have_snapshot.add(ticker)
        elif row["event_type"] == "orderbook_delta" and ticker in have_snapshot:
            target = yes_books[ticker] if str(row.get("side")).lower() == "yes" else no_books[ticker]
            price = _decimal(row.get("price"))
            delta = _decimal(row.get("delta"))
            if price is not None and delta is not None:
                target[price] = target.get(price, Decimal("0")) + delta
                if target[price] <= 0:
                    target.pop(price, None)
        if ticker not in have_snapshot or not yes_books[ticker] or not no_books[ticker]:
            continue
        timestamp = _timestamp(row["timestamp_received"])
        updates.append(
            ReplayUpdate(
                timestamp,
                BookSnapshot(
                    venue="kalshi",
                    outcome_name=outcome_by_ticker[ticker],
                    market_key=ticker,
                    yes_bids=tuple(
                        DepthLevel(price, size)
                        for price, size in sorted(yes_books[ticker].items(), reverse=True)
                    ),
                    yes_asks=tuple(
                        DepthLevel(Decimal("1") - price, size)
                        for price, size in sorted(no_books[ticker].items(), reverse=True)
                    ),
                    received_ts=timestamp,
                ),
            )
        )
    return updates


def _load_polymarket_hour(manifest: EventManifest, hour: str) -> list[ReplayUpdate]:
    import fsspec
    import pyarrow.parquet as pq

    contract_to_outcome = {
        item.polymarket_contract_address.encode(): outcome
        for outcome, item in manifest.historical.items()
        if item.polymarket_contract_address and item.polymarket_yes_token_id
    }
    token_to_outcome = {
        item.polymarket_yes_token_id: outcome
        for outcome, item in manifest.historical.items()
        if item.polymarket_yes_token_id
    }
    if len(token_to_outcome) != len(manifest.event.outcomes):
        raise ValueError("Every outcome requires polymarket_contract_address and polymarket_yes_token_id.")
    with fsspec.filesystem("https").open(POLY_BASE.format(hour=hour), "rb") as handle:
        table = pq.read_table(
            handle,
            columns=[
                "timestamp_received",
                "market",
                "event_type",
                "asset_id",
                "bids",
                "asks",
                "price",
                "size",
                "side",
                "fee_rate_bps",
            ],
            filters=[("market", "in", list(contract_to_outcome))],
        )
    books: dict[str, dict[str, dict[Decimal, Decimal]]] = defaultdict(
        lambda: {"bids": {}, "asks": {}}
    )
    updates: list[ReplayUpdate] = []
    for row in table.to_pylist():
        asset_id = _text(row.get("asset_id"))
        outcome = token_to_outcome.get(asset_id)
        if outcome is None:
            continue
        parsed_bids = dict(_struct_levels(row.get("bids")))
        parsed_asks = dict(_struct_levels(row.get("asks")))
        if parsed_bids:
            books[outcome]["bids"] = parsed_bids
        if parsed_asks:
            books[outcome]["asks"] = parsed_asks
        side = str(row.get("side") or "").lower()
        price = _decimal(row.get("price"))
        size = _decimal(row.get("size"))
        if side in {"buy", "bid", "bids"}:
            _set_level(books[outcome]["bids"], price, size)
        elif side in {"sell", "ask", "asks"}:
            _set_level(books[outcome]["asks"], price, size)
        if not books[outcome]["bids"] or not books[outcome]["asks"]:
            continue
        timestamp = _timestamp(row["timestamp_received"])
        updates.append(
            ReplayUpdate(
                timestamp,
                BookSnapshot(
                    venue="polymarket_us",
                    outcome_name=outcome,
                    market_key=asset_id,
                    yes_bids=tuple(
                        DepthLevel(price, size)
                        for price, size in sorted(books[outcome]["bids"].items(), reverse=True)
                    ),
                    yes_asks=tuple(
                        DepthLevel(price, size)
                        for price, size in sorted(books[outcome]["asks"].items())
                    ),
                    received_ts=timestamp,
                ),
                fee_rate_bps=_decimal(row.get("fee_rate_bps")),
            )
        )
    return updates


def _levels(raw: Any, *, reverse: bool) -> tuple[DepthLevel, ...]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raw = []
        else:
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                raw = ast.literal_eval(text)
    rows = []
    for level in raw or []:
        if isinstance(level, (list, tuple)):
            raw_price, raw_size = level[0], level[1]
        else:
            raw_price = level.get("price") or level.get("1") or level.get(1)
            raw_size = level.get("size") or level.get("2") or level.get(2)
        price = _decimal(raw_price)
        size = _decimal(raw_size)
        if price is not None and size is not None and size > 0:
            rows.append(DepthLevel(price, size))
    return tuple(sorted(rows, key=lambda level: level.price, reverse=reverse))


def _struct_levels(raw: Any) -> list[tuple[Decimal, Decimal]]:
    return [(level.price, level.size) for level in _levels(raw, reverse=False)]


def _set_level(book: dict[Decimal, Decimal], price: Decimal | None, size: Decimal | None) -> None:
    if price is None or size is None:
        return
    if size <= 0:
        book.pop(price, None)
    else:
        book[price] = size


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value or "")
