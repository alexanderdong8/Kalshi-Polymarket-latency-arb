from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


SCENARIO_PATTERNS = (
    ("nba", ("nba", "basketball")),
    ("wnba", ("wnba",)),
    ("mlb", ("mlb", "baseball")),
    ("nhl", ("nhl", "hockey", "stanley cup")),
    ("golf", ("golf", "pga", "masters")),
    ("atp", ("atp",)),
    ("wta", ("wta",)),
    ("ufc", ("ufc", "mma")),
    ("f1", ("formula 1", "grand prix", " f1 ")),
    ("elections", ("election", "primary", "ballot")),
    ("politics", ("president", "senate", "governor", "congress")),
    ("culture", ("oscars", "grammy", "movie", "album", "emmy")),
)


class HistoricalPriorProvider:
    def __init__(self, repository_root: Path) -> None:
        self.root = repository_root
        self._scores = self._load_scores()

    def for_event(self, title: str, category: str | None) -> dict[str, Any]:
        scenario = classify_scenario(title, category)
        row = self._scores.get(scenario)
        if row is None:
            return {
                "scenario": scenario,
                "historical_suitability": 50.0,
                "annual_profit_percentile": 50.0,
                "pmxt_profit_percentile": 50.0,
                "evidence_label": "Neutral prior: no matching historical leaderboard row",
            }
        return {
            "scenario": scenario,
            "historical_suitability": float(row["blended_score"]),
            "annual_profit_percentile": float(row["annual_profit_percentile"]),
            "pmxt_profit_percentile": float(row["pmxt_profit_percentile"]),
            "evidence_label": str(row["pmxt_validation"]),
        }

    @lru_cache(maxsize=1)
    def _load_scores(self) -> dict[str, dict[str, Any]]:
        annual = self.root / "historical_testing" / "reports" / "annual_official_proxy_12m.json"
        pmxt_candidates = (
            self.root / "historical_testing" / "reports" / "pmxt_l2_replay.json",
            self.root / "historical_testing" / "reports" / "smoke_l2_active_replay_final.json",
        )
        if not annual.exists():
            return {}
        historical_root = str(self.root / "historical_testing")
        if historical_root not in sys.path:
            sys.path.insert(0, historical_root)
        try:
            from arb_study.rankings import build_leaderboards

            annual_payload = json.loads(annual.read_text(encoding="utf-8"))
            pmxt_payload = next(
                (
                    json.loads(path.read_text(encoding="utf-8"))
                    for path in pmxt_candidates
                    if path.exists()
                ),
                None,
            )
            rows = build_leaderboards(annual_payload, pmxt_payload).get(
                "category_leaderboard", []
            )
            return {str(row["focus_scenario"]): row for row in rows}
        except Exception:
            return {}


def classify_scenario(title: str, category: str | None) -> str:
    normalized = " " + re.sub(r"\s+", " ", f"{title} {category or ''}".lower()) + " "
    for label, patterns in SCENARIO_PATTERNS:
        if any(pattern in normalized for pattern in patterns):
            return label
    return "additional_discovered_scenario_coverage"
