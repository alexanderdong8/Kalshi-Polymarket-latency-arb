from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal

from .models import Venue

ZERO = Decimal("0")
ONE = Decimal("1")
ONE_CENT = Decimal("0.01")


@dataclass(frozen=True)
class FeeConfig:
    """Per-venue fee parameters.

    Both venues use the same symmetric curve `theta * C * P * (1-P)` per contract
    trade, but with different thetas and different rounding rules. Maker fields
    are populated for use by future post-only execution code; the detector and
    current taker-only fire logic only consume the taker thetas.

    Kalshi (https://docs.kalshi.com/getting_started/fee_rounding,
            https://kalshi.com/docs/kalshi-fee-schedule.pdf):
      taker_fee = round_up_to_cent(0.07 * C * P * (1-P))
      maker_fee = round_up_to_cent(0.0175 * C * P * (1-P))

    Polymarket US (https://docs.polymarket.us/fees):
      taker_fee   = bankers_round_to_cent(0.05 * C * P * (1-P))
      maker_rebate = bankers_round_to_cent(0.0125 * C * P * (1-P))  # credit
    """
    kalshi_taker_theta: Decimal = Decimal("0.07")
    kalshi_maker_theta: Decimal = Decimal("0.0175")
    polymarket_us_taker_theta: Decimal = Decimal("0.05")
    polymarket_us_maker_rebate_theta: Decimal = Decimal("0.0125")
    # Rounding modes — Kalshi rounds up to cent; Polymarket uses banker's rounding
    # (round-half-to-even). Per their respective fee documentation pages.
    kalshi_rounding: str = ROUND_CEILING
    polymarket_us_rounding: str = ROUND_HALF_EVEN

    @classmethod
    def default(cls) -> "FeeConfig":
        return cls()

    # Backwards-compat property so any external callers reading the old name
    # still get the taker value.
    @property
    def kalshi_theta(self) -> Decimal:
        return self.kalshi_taker_theta

    @property
    def polymarket_us_theta(self) -> Decimal:
        return self.polymarket_us_taker_theta


def _round_to_cent(x: Decimal, mode: str) -> Decimal:
    return x.quantize(ONE_CENT, rounding=mode)


def kalshi_taker_fee_total(price: Decimal, contracts: Decimal, cfg: FeeConfig) -> Decimal:
    """Total Kalshi taker fee in dollars for filling `contracts` at `price`.
    Formula: ceil_cent(theta_taker * C * P * (1 - P))."""
    if contracts <= ZERO or price <= ZERO or price >= ONE:
        return ZERO
    raw = cfg.kalshi_taker_theta * contracts * price * (ONE - price)
    return _round_to_cent(raw, cfg.kalshi_rounding)


def kalshi_maker_fee_total(price: Decimal, contracts: Decimal, cfg: FeeConfig) -> Decimal:
    """Total Kalshi maker fee (charged on resting orders that get filled).
    Formula: ceil_cent(theta_maker * C * P * (1 - P)). ¼ of taker."""
    if contracts <= ZERO or price <= ZERO or price >= ONE:
        return ZERO
    raw = cfg.kalshi_maker_theta * contracts * price * (ONE - price)
    return _round_to_cent(raw, cfg.kalshi_rounding)


def polymarket_us_taker_fee_total(price: Decimal, contracts: Decimal, cfg: FeeConfig) -> Decimal:
    """Total Polymarket US taker fee in dollars for filling `contracts` at `price`.
    Formula: bankers_round_cent(theta_taker * C * P * (1 - P))."""
    if contracts <= ZERO or price <= ZERO or price >= ONE:
        return ZERO
    raw = cfg.polymarket_us_taker_theta * contracts * price * (ONE - price)
    return _round_to_cent(raw, cfg.polymarket_us_rounding)


def polymarket_us_maker_rebate_total(price: Decimal, contracts: Decimal, cfg: FeeConfig) -> Decimal:
    """Total Polymarket US maker rebate (credited to balance on fill).
    Formula: bankers_round_cent(theta_rebate * C * P * (1 - P)). 25% of taker."""
    if contracts <= ZERO or price <= ZERO or price >= ONE:
        return ZERO
    raw = cfg.polymarket_us_maker_rebate_theta * contracts * price * (ONE - price)
    return _round_to_cent(raw, cfg.polymarket_us_rounding)


def venue_taker_fee_total(
    venue: Venue, price: Decimal, contracts: Decimal, cfg: FeeConfig
) -> Decimal:
    if venue == "kalshi":
        return kalshi_taker_fee_total(price, contracts, cfg)
    if venue == "polymarket_us":
        return polymarket_us_taker_fee_total(price, contracts, cfg)
    raise ValueError(f"unknown venue: {venue!r}")


def fee_per_share(venue: Venue, price: Decimal, contracts: Decimal, cfg: FeeConfig) -> Decimal:
    """Per-share (per-contract) taker fee at the given price."""
    if contracts <= ZERO:
        return ZERO
    return venue_taker_fee_total(venue, price, contracts, cfg) / contracts
