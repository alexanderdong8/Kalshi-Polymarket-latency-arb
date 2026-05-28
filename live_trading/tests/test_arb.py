from datetime import datetime, timezone
from decimal import Decimal

from live_trading.arb import evaluate_match
from live_trading.models import BookState, MatchedMarket, VenueMarket


def _market(venue: str, key: str) -> VenueMarket:
    return VenueMarket(
        venue=venue,  # type: ignore[arg-type]
        market_id=key,
        ticker=key if venue == "kalshi" else None,
        slug=key,
        title="Will Team A win?",
        category="sports",
        market_type="moneyline",
        start_time=None,
        close_time=None,
        expiration_time=None,
    )


def test_exact_example_reports_twenty_cent_gross_edge() -> None:
    match = MatchedMarket(
        match_id="KXTEST::poly-test",
        kalshi=_market("kalshi", "KXTEST"),
        polymarket_us=_market("polymarket_us", "poly-test"),
        confidence=Decimal("1"),
        relation="identity",
    )
    ts = datetime.now(timezone.utc)
    kalshi = BookState(
        venue="kalshi",
        market_key="KXTEST",
        yes_bid=Decimal("0.70"),
        yes_ask=Decimal("0.70"),
        no_bid=Decimal("0.30"),
        no_ask=Decimal("0.30"),
        no_ask_size=Decimal("100"),
        received_ts=ts,
    )
    poly = BookState(
        venue="polymarket_us",
        market_key="poly-test",
        yes_bid=Decimal("0.50"),
        yes_ask=Decimal("0.50"),
        no_bid=Decimal("0.50"),
        no_ask=Decimal("0.50"),
        yes_ask_size=Decimal("100"),
        received_ts=ts,
    )

    opportunities = evaluate_match(
        match,
        kalshi,
        poly,
        trade_size=100,
        slippage_buffer_per_pair=Decimal("0"),
        min_gross_edge=Decimal("0"),
    )

    target = next(item for item in opportunities if item.direction == "kalshi_no__polymarket_yes")
    assert target.entry_cost == Decimal("0.80")
    assert target.gross_edge_per_contract == Decimal("0.20")
    assert target.net_edge_per_contract < target.gross_edge_per_contract

