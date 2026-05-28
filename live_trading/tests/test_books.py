from decimal import Decimal

from live_trading.books import KalshiOrderBook, polymarket_us_book_state


def test_kalshi_snapshot_computes_complement_asks() -> None:
    book = KalshiOrderBook("KXTEST")
    state = book.apply_snapshot(
        {
            "type": "orderbook_snapshot",
            "seq": 1,
            "msg": {
                "market_ticker": "KXTEST",
                "yes_dollars_fp": [["0.7000", "25.00"]],
                "no_dollars_fp": [["0.3000", "40.00"]],
            },
        }
    )

    assert state.yes_bid == Decimal("0.7000")
    assert state.no_bid == Decimal("0.3000")
    assert state.yes_ask == Decimal("0.7000")
    assert state.no_ask == Decimal("0.3000")
    assert state.yes_ask_size == Decimal("40.00")
    assert state.no_ask_size == Decimal("25.00")


def test_kalshi_delta_updates_price_level() -> None:
    book = KalshiOrderBook("KXTEST")
    book.apply_snapshot({"msg": {"market_ticker": "KXTEST", "yes_dollars_fp": [], "no_dollars_fp": []}})
    state = book.apply_delta(
        {
            "type": "orderbook_delta",
            "seq": 2,
            "msg": {"market_ticker": "KXTEST", "side": "yes", "price_dollars": "0.4100", "delta_fp": "3.00"},
        }
    )

    assert state.yes_bid == Decimal("0.4100")
    assert state.no_ask == Decimal("0.5900")


def test_polymarket_snapshot_computes_short_complements() -> None:
    state = polymarket_us_book_state(
        "poly-test",
        {
            "marketSlug": "poly-test",
            "bids": [{"px": {"value": "0.49", "currency": "USD"}, "qty": "12"}],
            "offers": [{"px": {"value": "0.50", "currency": "USD"}, "qty": "8"}],
            "state": "MARKET_STATE_OPEN",
        },
    )

    assert state.yes_bid == Decimal("0.49")
    assert state.yes_ask == Decimal("0.50")
    assert state.no_bid == Decimal("0.50")
    assert state.no_ask == Decimal("0.51")

