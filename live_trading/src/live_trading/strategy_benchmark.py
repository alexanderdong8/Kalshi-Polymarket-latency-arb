from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .runtime import _evaluation_payload
from .strategy.detector import Detector
from .strategy.models import BookSnapshot, DepthLevel, EventSpec, OutcomeSpec


def benchmark_strategy_and_dashboard(iterations: int = 10_000) -> dict[str, Any]:
    event = EventSpec(
        "Benchmark Event",
        None,
        tuple(
            OutcomeSpec(f"Outcome {index}", f"K-{index}", f"P-{index}")
            for index in range(4)
        ),
    )
    now = datetime.now(timezone.utc)
    books = {
        (venue, outcome.name): BookSnapshot(
            venue=venue,
            outcome_name=outcome.name,
            market_key=f"{venue}-{outcome.name}",
            yes_bids=(DepthLevel(Decimal("0.20"), Decimal("1000")),),
            yes_asks=(DepthLevel(Decimal("0.24"), Decimal("1000")),),
            received_ts=now,
        )
        for outcome in event.outcomes
        for venue in ("kalshi", "polymarket_us")
    }
    detector = Detector(event, Decimal("100"))
    started = time.perf_counter()
    evaluation = None
    for _ in range(iterations):
        evaluation = detector.evaluate(books, now)
    strategy_seconds = time.perf_counter() - started

    payload = _evaluation_payload(evaluation)
    started = time.perf_counter()
    for _ in range(iterations):
        json.dumps(payload)
    dashboard_seconds = time.perf_counter() - started
    return {
        "iterations": iterations,
        "strategy": {
            "seconds": strategy_seconds,
            "evaluations_per_second": iterations / strategy_seconds,
            "microseconds_per_evaluation": strategy_seconds * 1_000_000 / iterations,
        },
        "dashboard_side_channel": {
            "seconds": dashboard_seconds,
            "serializations_per_second": iterations / dashboard_seconds,
            "microseconds_per_serialization": dashboard_seconds * 1_000_000 / iterations,
        },
    }
