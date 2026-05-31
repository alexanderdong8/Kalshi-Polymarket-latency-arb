from arb_study.official_catalog import match_official_catalogs
from arb_study.official_price_scanner import _align_official_series
from arb_study.scenario import classify_scenario


def _kalshi(title: str, ticker: str, yes_sub_title: str):
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "title": title,
        "yes_sub_title": yes_sub_title,
        "no_sub_title": yes_sub_title,
        "close_time": "2026-05-23T20:00:00Z",
        "expiration_time": "2026-05-23T20:00:00Z",
        "market_type": "binary",
        "rules_primary": title,
    }


def _poly(question: str, market_id: str, outcomes: list[str], tokens: list[str]):
    import json

    return {
        "id": market_id,
        "conditionId": f"condition-{market_id}",
        "question": question,
        "slug": market_id,
        "description": question,
        "endDate": "2026-05-23T20:00:00Z",
        "outcomes": json.dumps(outcomes),
        "clobTokenIds": json.dumps(tokens),
    }


def test_matches_standard_binary_catalog_pair() -> None:
    kalshi = [_kalshi("Will the Boston Celtics win the 2026 NBA Finals?", "KXNBA-BOS", "Boston Celtics")]
    poly = [_poly("Will the Boston Celtics win the 2026 NBA Finals?", "poly-bos", ["Yes", "No"], ["yes", "no"])]

    matches, rejected = match_official_catalogs(kalshi, poly)

    assert rejected == []
    assert len(matches) == 1
    assert matches[0].polymarket.yes.outcome_id == "yes"


def test_orients_two_team_polymarket_tokens_against_kalshi_yes_side() -> None:
    kalshi = [_kalshi("Boston Celtics vs New York Knicks Winner?", "KXGAME-BOS", "Boston Celtics")]
    poly = [_poly("Boston Celtics vs. New York Knicks", "poly-game", ["New York Knicks", "Boston Celtics"], ["nyk", "bos"])]

    matches, _ = match_official_catalogs(kalshi, poly)

    assert len(matches) == 1
    assert matches[0].polymarket.yes.outcome_id == "bos"
    assert matches[0].polymarket.no.outcome_id == "nyk"
    assert "outcome labels" in matches[0].resolution_date_warning


def test_rejects_semantically_different_world_cup_markets() -> None:
    kalshi = [_kalshi("Will the Denmark win the 2026 Men's World Cup?", "KXWC-DEN", "Denmark")]
    poly = [_poly("Will Denmark qualify for the 2026 FIFA World Cup?", "poly-den", ["Yes", "No"], ["yes", "no"])]

    matches, _ = match_official_catalogs(kalshi, poly)

    assert matches == []


def test_rejects_cricket_soccer_world_cup_collision() -> None:
    kalshi = [_kalshi("Will the Italy win the 2026 Men's World Cup?", "KXWC-ITA", "Italy")]
    poly = [_poly("Will Italy win the 2026 ICC Men's T20 World Cup?", "poly-ita", ["Yes", "No"], ["yes", "no"])]

    matches, _ = match_official_catalogs(kalshi, poly)

    assert matches == []


def test_rejects_different_nominee_districts_and_names() -> None:
    kalshi = [_kalshi("Will Michael Curran be the Republican nominee for TX-09?", "KXTX09-CURRAN", "Michael Curran")]
    poly = [_poly("Will Michael Pratt be the Republican Nominee for TX-38?", "poly-pratt", ["Yes", "No"], ["yes", "no"])]

    matches, _ = match_official_catalogs(kalshi, poly)

    assert matches == []


def test_rejects_threshold_market_against_winner_market() -> None:
    kalshi = [_kalshi("Will the Freedom Movement win above 18 seats in the 2026 Slovenian parliamentary election?", "KXSI-18", "Freedom Movement")]
    poly = [_poly("Will the Freedom Movement (GS) win the most seats in the 2026 Slovenian parliamentary election?", "poly-gs", ["Yes", "No"], ["yes", "no"])]

    matches, _ = match_official_catalogs(kalshi, poly)

    assert matches == []


def test_aligns_historical_kalshi_candlestick_shape() -> None:
    states = _align_official_series(
        [{"end_period_ts": 120, "yes_ask": {"close": "0.3000"}, "yes_bid": {"close": "0.2900"}}],
        [{"t": 120, "p": 0.31}],
        [{"t": 120, "p": 0.69}],
    )

    assert states == [
        {
            "timestamp": "1970-01-01T00:02:00+00:00",
            "kalshi_yes_ask": 0.3,
            "kalshi_no_ask": 0.71,
            "poly_yes_price": 0.31,
            "poly_no_price": 0.69,
        }
    ]


def test_classifies_detailed_sports_scenarios() -> None:
    assert classify_scenario("Boston Celtics vs New York Knicks NBA game") == "sports_basketball"
    assert classify_scenario("Formula 1 Monaco Grand Prix winner") == "sports_motorsport"
    assert classify_scenario("Wimbledon tennis champion") == "sports_tennis"
