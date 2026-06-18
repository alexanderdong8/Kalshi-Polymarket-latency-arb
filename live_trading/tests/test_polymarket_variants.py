from live_trading.venues.polymarket_us import (
    _event_outcome_markets,
    _event_title_score,
    _event_tokens,
    market_variants_from_api,
)


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


def test_polymarket_us_event_title_match_ignores_participant_order() -> None:
    wanted = _event_tokens("Japan vs Tunisia")

    assert _event_title_score(wanted, "Tunisia vs. Japan winner") >= 0.82


def test_polymarket_us_multi_outcome_sports_event_uses_real_outcome_labels() -> None:
    raw_event = {
        "markets": [
            {
                "id": "tun-market",
                "slug": "tunisia-japan-tun",
                "question": "Will Tunisia win against Japan?",
                "marketSides": [
                    {"id": "tun-yes", "long": True, "description": "Yes", "team": {"name": "Tunisia"}},
                    {"id": "tun-no", "long": False, "description": "No", "team": {"name": "Tunisia"}},
                ],
            },
            {
                "id": "draw-market",
                "slug": "tunisia-japan-draw",
                "question": "Will Tunisia vs Japan end in a draw?",
                "marketSides": [
                    {"id": "draw-yes", "long": True, "description": "Yes"},
                    {"id": "draw-no", "long": False, "description": "No"},
                ],
            },
            {
                "id": "jpn-market",
                "slug": "tunisia-japan-jpn",
                "question": "Will Japan win against Tunisia?",
                "marketSides": [
                    {"id": "jpn-yes", "long": True, "description": "Yes", "team": {"name": "Japan"}},
                    {"id": "jpn-no", "long": False, "description": "No", "team": {"name": "Japan"}},
                ],
            },
        ]
    }
    variants = [
        variant
        for market in raw_event["markets"]
        for variant in market_variants_from_api(market)
    ]

    outcomes = _event_outcome_markets(raw_event, variants)

    assert [row.yes_label for row in outcomes] == ["Tunisia", "Tie", "Japan"]
    assert {row.raw["outcome_side"] for row in outcomes} == {"long"}
