from live_trading.venues.polymarket_us import market_variants_from_api


def test_polymarket_catalog_exposes_long_and_short_outcomes() -> None:
    variants = market_variants_from_api(
        {
            "id": "market-1",
            "slug": "team-a-vs-team-b",
            "question": "Team A vs Team B",
            "active": True,
            "closed": False,
            "eventId": "event-1",
            "marketSides": [
                {"id": "long-token", "long": True, "description": "Team A"},
                {"id": "short-token", "long": False, "description": "Team B"},
            ],
        }
    )

    assert [row.yes_label for row in variants] == ["Team A", "Team B"]
    assert [row.raw["outcome_side"] for row in variants] == ["long", "short"]
    assert variants[0].slug == variants[1].slug
