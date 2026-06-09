from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from arb_study.llm_adjudication import Adjudication, OpenAIAdjudicator
from arb_study.official_catalog import match_official_catalogs
from arb_study.portfolio import PortfolioRules, simulate_capped_portfolio
from arb_study.rankings import build_leaderboards
from arb_study.scenario import classify_competition_phase, classify_tournament_level
from arb_study.sports_identity import compatible_candidate, sports_identity


UTC = timezone.utc


def _kalshi(title: str, yes: str, ticker: str, close: str = "2026-01-02T03:00:00Z", **extra):
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "title": title,
        "yes_sub_title": yes,
        "no_sub_title": "Other",
        "close_time": close,
        "expected_expiration_time": close,
        "market_type": "binary",
        "rules_primary": title,
        **extra,
    }


def _poly(question: str, outcomes: list[str], market_id: str, start: str, end: str, **extra):
    return {
        "id": market_id,
        "conditionId": f"condition-{market_id}",
        "question": question,
        "slug": market_id,
        "description": question,
        "gameStartTime": start,
        "endDate": end,
        "outcomes": json.dumps(outcomes),
        "clobTokenIds": json.dumps([f"{market_id}-0", f"{market_id}-1"]),
        **extra,
    }


@pytest.mark.parametrize(
    ("kalshi_title", "yes", "ticker", "poly_title", "outcomes"),
    [
        ("Dallas at Milwaukee Winner?", "Milwaukee", "KXNBAGAME-DALMIL-MIL", "Mavericks vs. Bucks", ["Mavericks", "Bucks"]),
        ("New York Y at Seattle Winner?", "New York Y", "KXMLBGAME-NYYSEA-NYY", "Yankees vs. Mariners", ["Yankees", "Mariners"]),
        ("Boston at New York Winner?", "Boston", "KXNHLGAME-BOSNYR-BOS", "Bruins vs. Rangers", ["Bruins", "Rangers"]),
    ],
)
def test_gold_set_recovers_city_nickname_sports_pairs(
    kalshi_title: str,
    yes: str,
    ticker: str,
    poly_title: str,
    outcomes: list[str],
) -> None:
    matches, rejected = match_official_catalogs(
        [_kalshi(kalshi_title, yes, ticker)],
        [_poly(poly_title, outcomes, ticker.lower(), "2026-01-02T00:00:00Z", "2026-01-08T00:00:00Z")],
    )
    assert rejected == []
    assert len(matches) == 1
    assert matches[0].relation == "official_structured_identity_exact_pair"


def test_actual_start_time_overrides_misleading_polymarket_end_date() -> None:
    kalshi = _kalshi("Dallas at Milwaukee Winner?", "Milwaukee", "KXNBAGAME-DALMIL-MIL")
    poly = _poly(
        "Mavericks vs. Bucks",
        ["Mavericks", "Bucks"],
        "nba-game",
        "2026-01-02T00:00:00Z",
        "2026-01-31T00:00:00Z",
    )
    left = sports_identity(kalshi, "kalshi")
    right = sports_identity(poly, "polymarket")
    assert compatible_candidate(left, right)


def test_single_team_word_does_not_reclassify_non_sports_contract() -> None:
    mention = _kalshi(
        "What will Trump say during the announcement?",
        "Portland",
        "KXTRUMPMENTION-PORT",
    )
    identity = sports_identity(mention, "kalshi")
    assert not identity.is_sports


def test_two_team_aliases_can_infer_league_without_literal_league_name() -> None:
    matchup = _poly(
        "Trail Blazers vs. Lakers",
        ["Trail Blazers", "Lakers"],
        "por-lal",
        "2026-01-02T00:00:00Z",
        "2026-01-02T03:00:00Z",
    )
    identity = sports_identity(matchup, "polymarket")
    assert identity.league == "nba"
    assert set(identity.participants) == {
        "portland trail blazers",
        "los angeles lakers",
    }


def test_structured_gate_rejects_wrong_opponent_and_line() -> None:
    nba = sports_identity(
        _kalshi("Dallas at Milwaukee Winner?", "Milwaukee", "KXNBAGAME-DALMIL-MIL"),
        "kalshi",
    )
    wrong_team = sports_identity(
        _poly("Mavericks vs. Celtics", ["Mavericks", "Celtics"], "wrong", "2026-01-02T00:00:00Z", "2026-01-02T03:00:00Z"),
        "polymarket",
    )
    assert not compatible_candidate(nba, wrong_team)
    spread_left = sports_identity(
        _kalshi("Dallas at Milwaukee Milwaukee -3.5", "Milwaukee", "KXNBASPREAD-DALMIL-MIL"),
        "kalshi",
    )
    spread_right = sports_identity(
        _poly("Bucks -4.5 vs. Mavericks", ["Bucks", "Mavericks"], "spread", "2026-01-02T00:00:00Z", "2026-01-02T03:00:00Z"),
        "polymarket",
    )
    assert not compatible_candidate(spread_left, spread_right)


def test_granular_sports_taxonomy() -> None:
    assert classify_competition_phase("NBA play-in game") == "play_in"
    assert classify_competition_phase("MLB ALDS game") == "division_series"
    assert classify_competition_phase("World Series game 3") == "world_series"
    assert classify_tournament_level("ATP Wimbledon men's match") == "grand_slam"
    assert classify_tournament_level("UFC title fight main event") == "title_fight"
    assert classify_tournament_level("F1 qualifying") == "qualifying"


def test_capped_portfolio_uses_first_chronological_signal_and_500_dollar_cap() -> None:
    rows = [
        {
            "match_id": "a",
            "start": "2026-01-01T00:00:00Z",
            "settlement_at": "2026-01-02T00:00:00Z",
            "entry_cost_per_contract": 0.90,
            "net_profit_per_contract": 0.02,
        },
        {
            "match_id": "a",
            "start": "2026-01-01T00:01:00Z",
            "settlement_at": "2026-01-02T00:00:00Z",
            "entry_cost_per_contract": 0.80,
            "net_profit_per_contract": 0.10,
        },
    ]
    result = simulate_capped_portfolio(
        rows,
        rules=PortfolioRules(starting_bankroll=5000, position_cap_share=0.10),
        enforce_depth=False,
    )
    assert result["accepted_positions"] == 1
    assert result["positions"][0]["start"] == rows[0]["start"]
    assert result["positions"][0]["contracts"] == 555


def test_blended_ranking_uses_70_30_formula_and_neutral_missing_l2() -> None:
    annual = {
        "parameters": {"trade_size": 100},
        "phase_records": [
            {"match_id": "nba", "window_end": "2026-01-02T00:00:00Z"},
            {"match_id": "mlb", "window_end": "2026-01-02T00:00:00Z"},
        ],
        "opportunities": [
            {
                "match_id": "nba", "timestamp": "2026-01-01T00:00:00Z",
                "pair_slippage_assumption": 0.02, "total_cost": 0.90, "total_fee": 0,
                "net_edge_per_contract": 0.08, "focus_scenario": "nba",
                "competition_phase": "regular_season_or_unspecified", "market_type": "moneyline_or_binary",
                "phase": "sports_pregame_final_24h",
            },
            {
                "match_id": "mlb", "timestamp": "2026-01-01T00:00:00Z",
                "pair_slippage_assumption": 0.02, "total_cost": 0.95, "total_fee": 0,
                "net_edge_per_contract": 0.03, "focus_scenario": "mlb",
                "competition_phase": "regular_season_or_unspecified", "market_type": "moneyline_or_binary",
                "phase": "sports_pregame_final_24h",
            },
        ],
    }
    rows = build_leaderboards(annual, None)["category_leaderboard"]
    assert rows[0]["focus_scenario"] == "nba"
    assert rows[0]["pmxt_profit_percentile"] == 50
    assert rows[0]["blended_score"] == pytest.approx(85)


def test_openai_adjudication_cache_avoids_repeat_request(tmp_path, monkeypatch) -> None:
    calls = []
    adjudicator = OpenAIAdjudicator(tmp_path / "cache.json", api_key="test", budget_usd=7)

    def fake_request(candidates):
        calls.append(candidates)
        return (
            [
                Adjudication(
                    "exact_locked_pair", 0.99, True, True, True, True, True,
                    True, True, "kalshi_yes_equals_polymarket_second_outcome", "same rules",
                )
            ],
            {"input_tokens": 100, "output_tokens": 50},
        )

    monkeypatch.setattr(adjudicator, "_request", fake_request)
    candidate = {"a": 1}
    assert adjudicator.adjudicate_many([candidate])[0].decision == "exact_locked_pair"
    assert adjudicator.adjudicate_many([candidate])[0].decision == "exact_locked_pair"
    assert len(calls) == 1
    assert adjudicator.spent_usd > 0


def test_openai_adjudication_parallel_batches_preserve_candidate_order(tmp_path, monkeypatch) -> None:
    adjudicator = OpenAIAdjudicator(tmp_path / "cache.json", api_key="test", budget_usd=7)

    def fake_request(candidates):
        return (
            [
                Adjudication(
                    "exact_locked_pair", 0.99, True, True, True, True, True,
                    True, True, str(candidate["id"]), "same rules",
                )
                for candidate in candidates
            ],
            {"input_tokens": 100 * len(candidates), "output_tokens": 50 * len(candidates)},
        )

    monkeypatch.setattr(adjudicator, "_request", fake_request)
    candidates = [{"id": index} for index in range(25)]
    results = adjudicator.adjudicate_many(candidates)
    assert [item.orientation for item in results] == [str(index) for index in range(25)]
    assert len(adjudicator.cache["calls"]) == 3


def test_openai_budget_exhaustion_returns_uncertain_without_request(tmp_path, monkeypatch) -> None:
    adjudicator = OpenAIAdjudicator(tmp_path / "cache.json", api_key="test", budget_usd=0.005)
    monkeypatch.setattr(
        adjudicator,
        "_request",
        lambda candidates: pytest.fail("request should not run when one reserved batch exceeds budget"),
    )
    result = adjudicator.adjudicate_many([{"id": 1}])[0]
    assert result.decision == "uncertain"
    assert result.source == "budget_exhausted"
