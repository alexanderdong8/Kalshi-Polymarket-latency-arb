from datetime import datetime, timezone
from decimal import Decimal

from live_trading.models import BookState, MatchedMarket, VenueMarket
from live_trading.tui import Dashboard


def test_dashboard_renders_without_live_network() -> None:
    ts = datetime.now(timezone.utc)
    kalshi = VenueMarket("kalshi", "KX", "KX", "KX", "Will A happen?", "sports", "binary", None, None, None)
    poly = VenueMarket("polymarket_us", "PM", None, "pm", "Will A happen?", "sports", "binary", None, None, None)
    match = MatchedMarket("KX::PM", kalshi, poly, Decimal("1"), "identity")
    books = {
        ("kalshi", "KX"): BookState("kalshi", "KX", Decimal("0.7"), Decimal("0.7"), Decimal("0.3"), Decimal("0.3"), received_ts=ts),
        ("polymarket_us", "pm"): BookState(
            "polymarket_us",
            "pm",
            Decimal("0.5"),
            Decimal("0.5"),
            Decimal("0.5"),
            Decimal("0.5"),
            received_ts=ts,
        ),
    }

    renderable = Dashboard(Decimal("5")).render([match], books, [])

    assert renderable is not None

