from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN


CENT = Decimal("0.01")


def _d(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value))


def round_up_cent(value: float | Decimal) -> float:
    return float(_d(value).quantize(CENT, rounding=ROUND_CEILING))


def bankers_round_cent(value: float | Decimal) -> float:
    return float(_d(value).quantize(CENT, rounding=ROUND_HALF_EVEN))


def kalshi_fee(price: float, contracts: int, mode: str = "taker") -> float:
    coefficient = Decimal("0.0175") if mode == "maker" else Decimal("0.07")
    p = _d(price)
    fee = coefficient * _d(contracts) * p * (Decimal("1") - p)
    return round_up_cent(fee)


def polymarket_fee(
    price: float,
    contracts: int,
    fee_rate: float | None = None,
    fallback_rate: float = 0.05,
    round_to_cent: bool = False,
) -> float:
    rate = fallback_rate if fee_rate is None else fee_rate
    p = _d(price)
    fee = _d(rate) * _d(contracts) * p * (Decimal("1") - p)
    if round_to_cent:
        return bankers_round_cent(fee)
    return float(fee)


def leg_fee(
    venue: str,
    price: float,
    contracts: int,
    kalshi_mode: str = "taker",
    polymarket_fee_rate: float | None = None,
    polymarket_fallback_rate: float = 0.05,
) -> float:
    if venue == "kalshi":
        return kalshi_fee(price, contracts, kalshi_mode)
    if venue == "polymarket":
        return polymarket_fee(
            price,
            contracts,
            fee_rate=polymarket_fee_rate,
            fallback_rate=polymarket_fallback_rate,
        )
    raise ValueError(f"Unsupported venue for fee model: {venue}")

