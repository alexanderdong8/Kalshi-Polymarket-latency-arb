from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import HistoricalEvidence


SCENARIOS = (
    ("nba", ("nba", "basketball", "76ers", "mavericks", "celtics", "suns")),
    ("wnba", ("wnba",)),
    ("mlb", ("mlb", "baseball", "world series")),
    ("nhl", ("nhl", "hockey", "stanley cup")),
    ("golf", ("golf", "pga", "masters")),
    ("f1", ("formula 1", "formula one", "grand prix", " f1 ")),
    ("esports", ("esports", "counter-strike", "league of legends", "valorant")),
    ("atp", ("atp", "men's tennis")),
    ("wta", ("wta", "women's tennis")),
    ("ufc", ("ufc", "mma")),
    ("elections", ("election", "primary", "ballot", "nominee")),
    ("politics", ("president", "senate", "governor", "congress")),
    ("weather", ("weather", "temperature", "rainfall", "snowfall")),
    ("culture", ("oscars", "grammy", "movie", "album", "emmy")),
)


class HistoricalEvidenceProvider:
    def __init__(self, repository_root: Path) -> None:
        self.path = repository_root / "historical_testing" / "reports" / "scenario_leaderboards.json"
        self._payload = self._load()

    def for_event(
        self,
        title: str,
        category: str | None,
        event_state: str,
        market_type: str | None = None,
    ) -> HistoricalEvidence:
        scenario = classify_scenario(title, category)
        category_row = next(
            (
                row
                for row in self._payload.get("category_leaderboard", [])
                if str(row.get("focus_scenario")) == scenario
            ),
            None,
        )
        subscenario = self._best_subscenario(scenario, event_state, market_type)
        row = subscenario or category_row
        if row is None:
            return HistoricalEvidence(scenario=scenario)
        annual_positions = int(row.get("annual_positions") or 0)
        pmxt_positions = int(row.get("pmxt_positions") or 0)
        sample_size = annual_positions + pmxt_positions
        l2_validated = pmxt_positions > 0 or str(row.get("pmxt_validation", "")).casefold() == "l2 validated"
        quality = "l2" if l2_validated else "proxy"
        suitability = float(row.get("blended_score", 50))
        signal = max(-1.0, min(1.0, (suitability - 50.0) / 50.0))
        shrinkage = min(1.0, sample_size / (4.0 if l2_validated else 12.0))
        maximum_adjustment = 0.12 if l2_validated else 0.04
        multiplier = 1.0 + signal * shrinkage * maximum_adjustment
        label = (
            f"L2-validated historical evidence ({sample_size} portfolio positions)"
            if l2_validated
            else f"Proxy-only historical evidence ({sample_size} portfolio positions)"
        )
        return HistoricalEvidence(
            scenario=scenario,
            suitability=suitability,
            annual_percentile=float(row.get("annual_profit_percentile", 50)),
            pmxt_percentile=float(row.get("pmxt_profit_percentile", 50)),
            multiplier=round(max(0.88, min(1.12, multiplier)), 4),
            quality=quality,
            sample_size=sample_size,
            label=label,
            subscenario=str(row.get("subscenario")) if row.get("subscenario") else None,
        )

    def _best_subscenario(
        self, scenario: str, event_state: str, market_type: str | None
    ) -> dict[str, Any] | None:
        candidates = []
        market_type = (market_type or "").casefold()
        for row in self._payload.get("subscenario_leaderboard", []):
            label = str(row.get("subscenario") or "")
            parts = [part.strip().casefold() for part in label.split("|")]
            if not parts or parts[0] != scenario:
                continue
            score = 1
            if event_state == "in_play" and "sports_in_play" in parts:
                score += 4
            elif event_state == "pregame" and any("pregame" in part for part in parts):
                score += 3
            elif event_state == "near_settlement" and any("final_24h" in part for part in parts):
                score += 3
            elif event_state == "long_duration" and any("more_than_30d" in part for part in parts):
                score += 3
            if market_type and any(market_type in part for part in parts):
                score += 2
            candidates.append((score, float(row.get("blended_score", 0)), row))
        return max(candidates, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]

    @lru_cache(maxsize=1)
    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}


def classify_scenario(title: str, category: str | None) -> str:
    normalized = " " + re.sub(r"\s+", " ", f"{title} {category or ''}".casefold()) + " "
    for label, patterns in SCENARIOS:
        if any(pattern in normalized for pattern in patterns):
            return label
    return "additional_discovered_scenario_coverage"
