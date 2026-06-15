from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import HistoricalEvidence, SizePoint


@dataclass(frozen=True)
class DeployableProfitRanking:
    selected: SizePoint | None
    completion_probability: float
    expected_deployable_profit: float
    historical_multiplier: float
    components: dict[str, float]
    exclusion_reasons: tuple[str, ...]


def rank_opportunity(
    points: list[SizePoint],
    *,
    mapping_confidence: float,
    freshness_score: float,
    outcome_count: int,
    event_state: str,
    history: HistoricalEvidence,
) -> DeployableProfitRanking:
    eligible = [
        point
        for point in points
        if point.executable_profit > 0
        and point.achievable_size > 0
        and point.fresh
        and point.complete_books
        and point.price_bounds_ok
    ]
    selected = max(eligible, key=lambda point: point.executable_profit, default=None)
    exclusions = []
    if not points:
        exclusions.append("No L2 size evaluations were available.")
    elif not any(point.complete_books for point in points):
        exclusions.append("One or more outcome books are missing.")
    elif not any(point.fresh for point in points):
        exclusions.append("One or more outcome books are stale.")
    elif not any(point.price_bounds_ok for point in points):
        exclusions.append("One or more outcome prices are outside strategy bounds.")
    elif not any(point.net_edge_per_share > 0 for point in points):
        exclusions.append("No basket size is profitable after fees and buffer.")
    if selected is None:
        return DeployableProfitRanking(
            selected=None,
            completion_probability=0,
            expected_deployable_profit=0,
            historical_multiplier=history.multiplier,
            components={},
            exclusion_reasons=tuple(exclusions),
        )

    mapping = 0.65 + 0.35 * _clamp(mapping_confidence)
    freshness = 0.5 + 0.5 * _clamp(freshness_score)
    depth_balance = _clamp(float(selected.achievable_size / selected.requested_size))
    slippage = _clamp(1.0 - float(selected.max_slippage_per_share / Decimal("0.05")))
    leg_count = max(0.70, 1.0 - max(0, outcome_count - 2) * 0.008)
    state = {
        "in_play": 0.88,
        "pregame": 0.98,
        "near_settlement": 0.94,
        "long_duration": 1.0,
        "lifecycle": 0.98,
    }.get(event_state, 0.95)
    completion = _clamp(mapping * freshness * depth_balance * slippage * leg_count * state)
    expected = float(selected.executable_profit) * completion * history.multiplier
    components = {
        "mapping_quality": round(mapping, 4),
        "freshness": round(freshness, 4),
        "balanced_depth": round(depth_balance, 4),
        "slippage_quality": round(slippage, 4),
        "leg_count_factor": round(leg_count, 4),
        "event_state_factor": round(state, 4),
    }
    return DeployableProfitRanking(
        selected=selected,
        completion_probability=round(completion, 4),
        expected_deployable_profit=round(expected, 6),
        historical_multiplier=history.multiplier,
        components=components,
        exclusion_reasons=tuple(exclusions),
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
