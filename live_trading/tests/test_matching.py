from datetime import datetime, timezone
from decimal import Decimal

from live_trading.matching import MatchConfig, match_markets
from live_trading.models import VenueMarket


def _market(venue: str, market_id: str, title: str, market_type: str = "moneyline") -> VenueMarket:
    ts = datetime(2026, 2, 8, 23, 0, tzinfo=timezone.utc)
    return VenueMarket(
        venue=venue,  # type: ignore[arg-type]
        market_id=market_id,
        ticker=market_id if venue == "kalshi" else None,
        slug=market_id.lower(),
        title=title,
        category="sports",
        market_type=market_type,
        start_time=ts,
        close_time=ts,
        expiration_time=ts,
        description=title,
    )


def test_matcher_pairs_similar_active_events() -> None:
    kalshi = [_market("kalshi", "KXKC", "Will Kansas City beat Buffalo?")]
    poly = [_market("polymarket_us", "pm-kc", "Kansas City vs Buffalo")]

    matches = match_markets(kalshi, poly, MatchConfig(min_confidence=Decimal("0.35")))

    assert len(matches) == 1
    assert matches[0].kalshi.market_id == "KXKC"


def test_matcher_warns_on_known_rule_conflict() -> None:
    kalshi = [_market("kalshi", "KXWC", "Will Austria qualify for World Cup Round of 16?")]
    poly = [_market("polymarket_us", "pm-wc", "Will Austria advance to the knockout stages?")]

    matches = match_markets(kalshi, poly, MatchConfig(min_confidence=Decimal("0.20")))

    assert matches
    assert matches[0].warnings

