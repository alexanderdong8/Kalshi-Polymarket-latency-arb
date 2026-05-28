from arb_study.fees import bankers_round_cent, kalshi_fee, polymarket_fee, round_up_cent


def test_kalshi_taker_fee_uses_round_up_cent() -> None:
    assert kalshi_fee(price=0.5, contracts=100, mode="taker") == 1.75
    assert kalshi_fee(price=0.1, contracts=100, mode="taker") == 0.63


def test_kalshi_maker_fee() -> None:
    assert kalshi_fee(price=0.5, contracts=100, mode="maker") == 0.44


def test_polymarket_fallback_fee() -> None:
    assert polymarket_fee(price=0.5, contracts=100, fallback_rate=0.05) == 1.25


def test_rounding_helpers() -> None:
    assert round_up_cent(0.021) == 0.03
    assert bankers_round_cent(0.025) == 0.02
    assert bankers_round_cent(0.035) == 0.04

