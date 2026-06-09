from decimal import Decimal

from live_trading.fees import bankers_round_cent, kalshi_fee, polymarket_us_fee, round_up_cent


def test_kalshi_taker_fee_rounds_up_to_cent() -> None:
    assert kalshi_fee(Decimal("0.50"), 100, "taker") == Decimal("1.75")
    assert kalshi_fee(Decimal("0.10"), 100, "taker") == Decimal("0.63")


def test_polymarket_us_taker_fee_uses_bankers_rounding() -> None:
    assert polymarket_us_fee(Decimal("0.50"), 100, Decimal("0.05")) == Decimal("1.25")
    assert bankers_round_cent(Decimal("0.025")) == Decimal("0.02")
    assert bankers_round_cent(Decimal("0.035")) == Decimal("0.04")
    assert round_up_cent(Decimal("0.021")) == Decimal("0.03")
