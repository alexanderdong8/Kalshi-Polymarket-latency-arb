from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from .fees import leg_fee
from .models import ArbOpportunity, BookState, MatchedMarket, Venue


def evaluate_match(
    match: MatchedMarket,
    kalshi_book: BookState | None,
    polymarket_book: BookState | None,
    trade_size: int,
    slippage_buffer_per_pair: Decimal,
    kalshi_fee_mode: str = "taker",
    polymarket_theta: Decimal = Decimal("0.05"),
    min_gross_edge: Decimal = Decimal("0"),
) -> list[ArbOpportunity]:
    if not kalshi_book or not polymarket_book:
        return []
    directions = [
        (
            "kalshi_no__polymarket_yes",
            "polymarket_us",
            "kalshi",
            polymarket_book.yes_ask,
            kalshi_book.no_ask,
            polymarket_book.yes_ask_size,
            kalshi_book.no_ask_size,
        ),
        (
            "kalshi_yes__polymarket_no",
            "kalshi",
            "polymarket_us",
            kalshi_book.yes_ask,
            polymarket_book.no_ask,
            kalshi_book.yes_ask_size,
            polymarket_book.no_ask_size,
        ),
    ]
    opportunities: list[ArbOpportunity] = []
    for direction, yes_venue, no_venue, yes_ask, no_ask, yes_size, no_size in directions:
        if yes_ask is None or no_ask is None:
            continue
        entry_cost = yes_ask + no_ask
        gross_edge = Decimal("1") - entry_cost
        if gross_edge < min_gross_edge:
            continue
        fees = (
            leg_fee(yes_venue, yes_ask, trade_size, kalshi_fee_mode, polymarket_theta)
            + leg_fee(no_venue, no_ask, trade_size, kalshi_fee_mode, polymarket_theta)
        ) / Decimal(trade_size)
        net_edge = gross_edge - fees - slippage_buffer_per_pair
        opportunities.append(
            ArbOpportunity(
                match_id=match.match_id,
                direction=direction,
                yes_venue=yes_venue,  # type: ignore[arg-type]
                no_venue=no_venue,  # type: ignore[arg-type]
                yes_ask=yes_ask,
                no_ask=no_ask,
                entry_cost=entry_cost,
                gross_edge_per_contract=gross_edge,
                net_edge_per_contract=net_edge,
                estimated_fees_per_contract=fees,
                slippage_buffer_per_pair=slippage_buffer_per_pair,
                depth_limited_contracts=_depth_limit(yes_size, no_size),
                kalshi_received_ts=kalshi_book.received_ts,
                polymarket_received_ts=polymarket_book.received_ts,
                detected_ts=datetime.now(timezone.utc),
                warnings=match.warnings,
            )
        )
    opportunities.sort(key=lambda item: item.net_edge_per_contract, reverse=True)
    return opportunities


def evaluate_all(
    matches: list[MatchedMarket],
    books: dict[tuple[Venue, str], BookState],
    trade_size: int,
    slippage_buffer_per_pair: Decimal,
    kalshi_fee_mode: str,
    polymarket_theta: Decimal,
    min_gross_edge: Decimal,
) -> list[ArbOpportunity]:
    result: list[ArbOpportunity] = []
    for match in matches:
        kalshi_book = books.get(("kalshi", match.kalshi.stream_key))
        poly_book = books.get(("polymarket_us", match.polymarket_us.stream_key))
        result.extend(
            evaluate_match(
                match,
                kalshi_book,
                poly_book,
                trade_size=trade_size,
                slippage_buffer_per_pair=slippage_buffer_per_pair,
                kalshi_fee_mode=kalshi_fee_mode,
                polymarket_theta=polymarket_theta,
                min_gross_edge=min_gross_edge,
            )
        )
    result.sort(key=lambda item: item.net_edge_per_contract, reverse=True)
    return result


def _depth_limit(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return min(left, right)

