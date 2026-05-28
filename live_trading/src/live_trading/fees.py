from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN


CENT = Decimal("0.01")


def decimal(value: Decimal | int | float | str | None, default: Decimal | None = None) -> Decimal:
    if value is None:
        if default is None:
            raise ValueError("Cannot convert None to Decimal without a default")
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_up_cent(value: Decimal | int | float | str) -> Decimal:
    return decimal(value).quantize(CENT, rounding=ROUND_CEILING)


def bankers_round_cent(value: Decimal | int | float | str) -> Decimal:
    return decimal(value).quantize(CENT, rounding=ROUND_HALF_EVEN)


def kalshi_fee(price: Decimal, contracts: int, mode: str = "taker") -> Decimal:
    coefficient = Decimal("0.0175") if mode == "maker" else Decimal("0.07")
    fee = coefficient * Decimal(contracts) * price * (Decimal("1") - price)
    return round_up_cent(fee)


def polymarket_us_fee(price: Decimal, contracts: int, theta: Decimal = Decimal("0.05")) -> Decimal:
    fee = theta * Decimal(contracts) * price * (Decimal("1") - price)
    return bankers_round_cent(fee)


def leg_fee(venue: str, price: Decimal, contracts: int, kalshi_mode: str, polymarket_theta: Decimal) -> Decimal:
    if venue == "kalshi":
        return kalshi_fee(price, contracts, kalshi_mode)
    if venue == "polymarket_us":
        return polymarket_us_fee(price, contracts, polymarket_theta)
    raise ValueError(f"Unsupported venue: {venue}")

