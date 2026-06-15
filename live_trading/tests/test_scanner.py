from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from live_trading.models import VenueMarket
from live_trading.scanner.candidate_generation import generate_event_pairs, group_events
from live_trading.scanner.historical import HistoricalEvidenceProvider
from live_trading.scanner.models import HistoricalEvidence, SizePoint
from live_trading.scanner.ranking import rank_opportunity
from live_trading.venues.polymarket_us import market_variants_from_api


NOW = datetime.now(timezone.utc)


def _market(
    venue: str,
    market_id: str,
    title: str,
    yes_label: str,
    *,
    event_id: str,
    start: datetime = NOW + timedelta(days=1),
) -> VenueMarket:
    raw_key = "event_ticker" if venue == "kalshi" else "eventId"
    return VenueMarket(
        venue=venue,  # type: ignore[arg-type]
        market_id=market_id,
        ticker=market_id if venue == "kalshi" else None,
        slug=market_id if venue == "polymarket_us" else None,
        title=title,
        category="sports",
        market_type="moneyline",
        start_time=start,
        close_time=start + timedelta(hours=3),
        expiration_time=start + timedelta(hours=3),
        yes_label=yes_label,
        description=title,
        raw={raw_key: event_id, "event_title": title},
    )


def test_event_matcher_understands_nba_city_and_team_aliases() -> None:
    kalshi = [
        _market(
            "kalshi",
            "KX-PHI",
            "Philadelphia vs Dallas Winner?",
            "Philadelphia",
            event_id="KX-NBA-PHI-DAL",
        ),
        _market(
            "kalshi",
            "KX-DAL",
            "Philadelphia vs Dallas Winner?",
            "Dallas",
            event_id="KX-NBA-PHI-DAL",
        ),
    ]
    polymarket = [
        _market(
            "polymarket_us",
            "nba-phi-dal-phi",
            "76ers vs. Mavericks",
            "76ers",
            event_id="nba-phi-dal",
        ),
        _market(
            "polymarket_us",
            "nba-phi-dal-dal",
            "76ers vs. Mavericks",
            "Mavericks",
            event_id="nba-phi-dal",
        ),
    ]

    pairs = generate_event_pairs(kalshi, polymarket)

    assert len(pairs) == 1
    assert len(pairs[0].outcome_matches) == 2
    mapping = {
        match.kalshi.yes_label: match.polymarket_us.yes_label
        for match in pairs[0].outcome_matches
    }
    assert mapping == {"Philadelphia": "76ers", "Dallas": "Mavericks"}


def test_event_matcher_maps_both_sides_of_one_polymarket_market() -> None:
    kalshi = [
        _market(
            "kalshi",
            "KX-PHI",
            "Philadelphia vs Dallas Winner?",
            "Philadelphia",
            event_id="KX-NBA-PHI-DAL",
        ),
        _market(
            "kalshi",
            "KX-DAL",
            "Philadelphia vs Dallas Winner?",
            "Dallas",
            event_id="KX-NBA-PHI-DAL",
        ),
    ]
    polymarket = market_variants_from_api(
        {
            "id": "nba-phi-dal",
            "slug": "nba-phi-dal",
            "question": "76ers vs. Mavericks",
            "category": "sports",
            "sportsMarketType": "moneyline",
            "gameStartTime": (NOW + timedelta(days=1)).isoformat(),
            "active": True,
            "closed": False,
            "eventId": "nba-phi-dal-event",
            "marketSides": [
                {"id": "phi", "long": True, "description": "76ers"},
                {"id": "dal", "long": False, "description": "Mavericks"},
            ],
        }
    )

    pair = generate_event_pairs(kalshi, polymarket)[0]

    assert len(pair.outcome_matches) == 2
    assert {row.polymarket_us.raw["outcome_side"] for row in pair.outcome_matches} == {
        "long",
        "short",
    }


def test_event_matcher_keeps_same_teams_on_different_dates_separate() -> None:
    kalshi = [
        _market("kalshi", "K1-A", "Boston vs Phoenix", "Boston", event_id="K1"),
        _market("kalshi", "K1-B", "Boston vs Phoenix", "Phoenix", event_id="K1"),
    ]
    polymarket = [
        _market(
            "polymarket_us",
            "P2-A",
            "Celtics vs Suns",
            "Celtics",
            event_id="P2",
            start=NOW + timedelta(days=8),
        ),
        _market(
            "polymarket_us",
            "P2-B",
            "Celtics vs Suns",
            "Suns",
            event_id="P2",
            start=NOW + timedelta(days=8),
        ),
    ]

    assert generate_event_pairs(kalshi, polymarket) == []


def test_parent_event_is_split_by_market_type() -> None:
    markets = [
        _market(
            "polymarket_us",
            "moneyline",
            "Team A vs Team B",
            "Team A",
            event_id="shared-parent",
        ),
        _market(
            "polymarket_us",
            "spread",
            "Team A -3.5",
            "Team A",
            event_id="shared-parent",
        ),
    ]
    markets[1] = replace(markets[1], market_type="spread")

    groups = group_events(markets)

    assert len(groups) == 2


def test_missing_history_is_neutral(tmp_path) -> None:
    provider = HistoricalEvidenceProvider(tmp_path)

    evidence = provider.for_event("Unknown event", "unknown", "lifecycle")

    assert evidence.multiplier == 1
    assert evidence.quality == "none"
    assert evidence.suitability == 50


def test_proxy_history_adjustment_is_bounded(tmp_path) -> None:
    reports = tmp_path / "historical_testing" / "reports"
    reports.mkdir(parents=True)
    (reports / "scenario_leaderboards.json").write_text(
        json.dumps(
            {
                "category_leaderboard": [
                    {
                        "focus_scenario": "golf",
                        "blended_score": 100,
                        "annual_profit_percentile": 100,
                        "pmxt_profit_percentile": 50,
                        "annual_positions": 100,
                        "pmxt_positions": 0,
                        "pmxt_validation": "Not L2 validated",
                    }
                ],
                "subscenario_leaderboard": [],
            }
        ),
        encoding="utf-8",
    )

    evidence = HistoricalEvidenceProvider(tmp_path).for_event(
        "PGA Championship winner", "golf", "pregame"
    )

    assert evidence.quality == "proxy"
    assert evidence.multiplier == 1.04


def _point(size: str, edge: str, profit: str, slippage: str = "0") -> SizePoint:
    value = Decimal(size)
    return SizePoint(
        requested_size=value,
        achievable_size=value,
        net_edge_per_share=Decimal(edge),
        executable_profit=Decimal(profit),
        max_slippage_per_share=Decimal(slippage),
        fresh=True,
        complete_books=True,
        price_bounds_ok=True,
    )


def test_ranking_prefers_more_deployable_dollars_over_raw_edge() -> None:
    ranking = rank_opportunity(
        [_point("5", "0.20", "1.00"), _point("100", "0.03", "3.00")],
        mapping_confidence=0.95,
        freshness_score=1,
        outcome_count=2,
        event_state="pregame",
        history=HistoricalEvidence(scenario="nba"),
    )

    assert ranking.selected is not None
    assert ranking.selected.requested_size == Decimal("100")
    assert ranking.expected_deployable_profit > 0


def test_unprofitable_current_books_cannot_be_rescued_by_history() -> None:
    ranking = rank_opportunity(
        [_point("100", "-0.01", "0")],
        mapping_confidence=1,
        freshness_score=1,
        outcome_count=2,
        event_state="long_duration",
        history=HistoricalEvidence(
            scenario="golf", multiplier=1.12, quality="l2", suitability=100
        ),
    )

    assert ranking.selected is None
    assert ranking.expected_deployable_profit == 0
