from datetime import datetime, timezone

from arb_study.models import BBOState, MatchedMarket, MarketRef, OutcomeRef
from arb_study.scanner import find_opportunities


def _match() -> MatchedMarket:
    poly = MarketRef(
        venue="polymarket",
        market_id="poly",
        title="Test",
        slug="poly-test",
        url=None,
        category="Sports",
        resolution_date=None,
        contract_address="0xabc",
        yes=OutcomeRef("poly-yes", "Yes"),
        no=OutcomeRef("poly-no", "No"),
    )
    kalshi = MarketRef(
        venue="kalshi",
        market_id="kalshi",
        title="Test",
        slug="KXTEST",
        url=None,
        category="Sports",
        resolution_date=None,
        contract_address=None,
        yes=OutcomeRef("KXTEST", "Yes"),
        no=OutcomeRef("KXTEST-NO", "No"),
    )
    return MatchedMarket("poly::kalshi", poly, kalshi, "identity", 1.0, None, None)


def test_find_opportunities_reports_gross_even_when_fee_negative() -> None:
    ts = datetime(2026, 5, 23, 7, 0, tzinfo=timezone.utc)
    poly = [
        BBOState(
            ts,
            yes_bid=0.1,
            yes_ask=0.101,
            no_bid=0.898,
            no_ask=0.899,
            yes_ask_size=10,
            no_ask_size=10,
        )
    ]
    kalshi = [
        BBOState(
            ts,
            yes_bid=0.09,
            yes_ask=0.091,
            no_bid=0.908,
            no_ask=0.91,
            yes_ask_size=10,
            no_ask_size=10,
        )
    ]

    opps = find_opportunities(
        _match(),
        poly,
        kalshi,
        trade_size=100,
        slippage_buffer=0.005,
        kalshi_fee_mode="taker",
        polymarket_fallback_fee_rate=0.05,
    )

    assert any(item.direction == "kalshi_yes__poly_no" for item in opps)
    best = max(opps, key=lambda item: item.gross_edge_per_contract)
    assert best.gross_edge_per_contract > 0
    assert best.net_edge_per_contract < best.gross_edge_per_contract
