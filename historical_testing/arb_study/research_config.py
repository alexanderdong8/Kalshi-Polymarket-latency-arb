from __future__ import annotations


FOCUS_SCENARIOS = [
    "nba",
    "mlb",
    "golf",
    "atp",
    "wta",
    "esports",
    "ipl",
    "wnba",
    "nhl",
    "itf_men",
    "itf_women",
    "ufc",
    "fifa_world_cup",
    "politics",
    "weather",
    "mls",
    "elections",
    "culture",
    "f1",
]

ADDITIONAL_DISCOVERED_SECTION = "additional_discovered_scenario_coverage"
ORDER_SIZE_LADDER = [1, 5, 10, 25, 50, 100, 250]
HEADLINE_ORDER_SIZE = 100
ANNUAL_PAIR_SLIPPAGE_CASES = [0.01, 0.02, 0.05]
PAIRED_EXIT_MINIMUM_IMPROVEMENT = 0.0075
PORTFOLIO_STARTING_BANKROLL = 10_000.0
PORTFOLIO_POSITION_CAP_SHARE = 0.10
LATENCY_BUCKETS_SECONDS = [0.1, 0.5, 1.0, 2.0, 5.0]

