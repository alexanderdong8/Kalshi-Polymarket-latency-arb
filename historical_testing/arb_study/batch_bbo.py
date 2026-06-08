from __future__ import annotations

from collections import defaultdict

import pyarrow.parquet as pq

from .archive import https_filesystem, parquet_url, remote_exists
from .bbo import (
    _best_ask_from_levels,
    _best_bid_from_levels,
    _best_book_bid,
    _iter_struct_levels,
    _parse_levels,
    _asks_from_opposite_bids,
    _apply_level_update,
    _fee_rate_from_bps,
    _poly_book_side,
    _prefer_ladder_best,
    _timestamp,
    _to_float,
)
from .models import BBOState, MatchedMarket


def load_polymarket_bbo_batch(
    matches: list[MatchedMarket],
    hour: str,
) -> dict[str, list[BBOState]]:
    url = parquet_url("polymarket", hour)
    if not matches or not remote_exists(url):
        return {}

    contract_to_matches: dict[bytes, list[MatchedMarket]] = defaultdict(list)
    for match in matches:
        if match.polymarket.contract_address:
            contract_to_matches[match.polymarket.contract_address.encode()].append(match)
    if not contract_to_matches:
        return {}

    fs = https_filesystem()
    with fs.open(url, "rb") as handle:
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
                "best_bid",
                "best_ask",
                "fee_rate_bps",
            ],
            filters=[("market", "in", list(contract_to_matches.keys()))],
        )

    if table.num_rows == 0:
        return {}

    df = table.to_pandas().sort_values("timestamp_received")
    state_by_match: dict[str, dict[str, object]] = {}
    out: dict[str, list[BBOState]] = defaultdict(list)

    for row in df.itertuples(index=False):
        contract_matches = contract_to_matches.get(row.market)
        if not contract_matches:
            continue
        bid = _to_float(row.best_bid)
        ask = _to_float(row.best_ask)
        bid_size = ask_size = None
        parsed_bids = _parse_levels(row.bids)
        parsed_asks = _parse_levels(row.asks)
        price = _to_float(row.price)
        size = _to_float(row.size)
        book_side = _poly_book_side(row.side)
        fee_rate = _fee_rate_from_bps(row.fee_rate_bps)
        parsed_bid, bid_size = _best_bid_from_levels(parsed_bids)
        parsed_ask, ask_size = _best_ask_from_levels(parsed_asks)

        if bid is None or ask is None:
            bid = bid if bid is not None else parsed_bid
            ask = ask if ask is not None else parsed_ask

        for match in contract_matches:
            side = None
            if row.asset_id == match.polymarket.yes.outcome_id:
                side = "yes"
            elif row.asset_id == match.polymarket.no.outcome_id:
                side = "no"
            if side is None:
                continue

            state = state_by_match.setdefault(
                match.match_id,
                {
                    "yes_bid": None,
                    "yes_ask": None,
                    "no_bid": None,
                    "no_ask": None,
                    "yes_bid_size": None,
                    "yes_ask_size": None,
                    "no_bid_size": None,
                    "no_ask_size": None,
                    "yes_bids": (),
                    "yes_asks": (),
                    "no_bids": (),
                    "no_asks": (),
                    "polymarket_fee_rate": None,
                },
            )
            state[f"{side}_bids"] = tuple(parsed_bids) if parsed_bids else state[f"{side}_bids"]
            state[f"{side}_asks"] = tuple(parsed_asks) if parsed_asks else state[f"{side}_asks"]
            if book_side == "bids":
                state[f"{side}_bids"] = tuple(_apply_level_update(state[f"{side}_bids"], price, size))
            elif book_side == "asks":
                state[f"{side}_asks"] = tuple(_apply_level_update(state[f"{side}_asks"], price, size))
            ladder_bid, ladder_bid_size = _prefer_ladder_best(
                state[f"{side}_bids"], bid, bid_size, is_bid=True
            )
            ladder_ask, ladder_ask_size = _prefer_ladder_best(
                state[f"{side}_asks"], ask, ask_size, is_bid=False
            )
            bid = ladder_bid
            ask = ladder_ask
            bid_size = ladder_bid_size
            ask_size = ladder_ask_size
            state[f"{side}_bid"] = bid if bid is not None else state[f"{side}_bid"]
            state[f"{side}_ask"] = ask if ask is not None else state[f"{side}_ask"]
            state[f"{side}_bid_size"] = bid_size if bid_size is not None else state[f"{side}_bid_size"]
            state[f"{side}_ask_size"] = ask_size if ask_size is not None else state[f"{side}_ask_size"]
            state["polymarket_fee_rate"] = fee_rate if fee_rate is not None else state["polymarket_fee_rate"]

            if None not in (state["yes_bid"], state["yes_ask"], state["no_bid"], state["no_ask"]):
                out[match.match_id].append(
                    BBOState(
                        timestamp=_timestamp(row.timestamp_received),
                        yes_bid=state["yes_bid"],
                        yes_ask=state["yes_ask"],
                        no_bid=state["no_bid"],
                        no_ask=state["no_ask"],
                        yes_bid_size=state["yes_bid_size"],
                        yes_ask_size=state["yes_ask_size"],
                        no_bid_size=state["no_bid_size"],
                        no_ask_size=state["no_ask_size"],
                        yes_bids=state["yes_bids"],
                        yes_asks=state["yes_asks"],
                        no_bids=state["no_bids"],
                        no_asks=state["no_asks"],
                        polymarket_fee_rate=state["polymarket_fee_rate"],
                    )
                )
    return dict(out)


def load_kalshi_bbo_batch(
    matches: list[MatchedMarket],
    hour: str,
) -> dict[str, list[BBOState]]:
    url = parquet_url("kalshi", hour)
    if not matches or not remote_exists(url):
        return {}

    ticker_to_matches: dict[str, list[MatchedMarket]] = defaultdict(list)
    for match in matches:
        ticker = match.kalshi.slug or match.kalshi.yes.outcome_id
        if ticker:
            ticker_to_matches[ticker].append(match)
    if not ticker_to_matches:
        return {}

    fs = https_filesystem()
    with fs.open(url, "rb") as handle:
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
            filters=[("market_ticker", "in", list(ticker_to_matches.keys()))],
        )

    if table.num_rows == 0:
        return {}

    df = table.to_pandas().sort_values("timestamp_received")
    yes_books: dict[str, defaultdict[float, float]] = defaultdict(lambda: defaultdict(float))
    no_books: dict[str, defaultdict[float, float]] = defaultdict(lambda: defaultdict(float))
    have_snapshot: set[str] = set()
    out: dict[str, list[BBOState]] = defaultdict(list)

    for row in df.itertuples(index=False):
        ticker = row.market_ticker
        if ticker not in ticker_to_matches:
            continue
        if row.event_type == "orderbook_snapshot":
            yes_books[ticker] = defaultdict(float)
            no_books[ticker] = defaultdict(float)
            for price, size in _iter_struct_levels(row.yes_bids):
                yes_books[ticker][price] = size
            for price, size in _iter_struct_levels(row.no_bids):
                no_books[ticker][price] = size
            have_snapshot.add(ticker)
        elif row.event_type == "orderbook_delta" and ticker in have_snapshot:
            price = _to_float(row.price)
            delta = _to_float(row.delta)
            if price is not None and delta is not None:
                book = yes_books[ticker] if str(row.side).lower() == "yes" else no_books[ticker]
                book[price] += delta
                if book[price] <= 1e-9:
                    book.pop(price, None)

        if ticker not in have_snapshot or not yes_books[ticker] or not no_books[ticker]:
            continue
        yes_bid, yes_bid_size = _best_book_bid(yes_books[ticker])
        no_bid, no_bid_size = _best_book_bid(no_books[ticker])
        if yes_bid is None or no_bid is None:
            continue

        state = BBOState(
            timestamp=_timestamp(row.timestamp_received),
            yes_bid=yes_bid,
            yes_ask=1.0 - no_bid,
            no_bid=no_bid,
            no_ask=1.0 - yes_bid,
            yes_bid_size=yes_bid_size,
            yes_ask_size=no_bid_size,
            no_bid_size=no_bid_size,
            no_ask_size=yes_bid_size,
            yes_bids=tuple(sorted(yes_books[ticker].items(), reverse=True)),
            yes_asks=_asks_from_opposite_bids(no_books[ticker]),
            no_bids=tuple(sorted(no_books[ticker].items(), reverse=True)),
            no_asks=_asks_from_opposite_bids(yes_books[ticker]),
        )
        for match in ticker_to_matches[ticker]:
            out[match.match_id].append(state)

    return dict(out)
