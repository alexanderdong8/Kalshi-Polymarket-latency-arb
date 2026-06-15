from __future__ import annotations

import json
import math
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
        "multi_event": benchmark_multi_event_strategy(
            event_count=40,
            max_outcomes=40,
            updates=max(1_000, iterations),
        ),
    }


def benchmark_multi_event_strategy(
    *,
    event_count: int = 40,
    max_outcomes: int = 40,
    updates: int = 10_000,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    detectors: list[Detector] = []
    books_by_event: list[dict] = []
    outcome_counts = []
    for event_index in range(event_count):
        outcome_count = 2 + (event_index % max(1, max_outcomes - 1))
        outcome_counts.append(outcome_count)
        event = EventSpec(
            f"Benchmark Event {event_index}",
            None,
            tuple(
                OutcomeSpec(
                    f"Outcome {event_index}-{index}",
                    f"K-{event_index}-{index}",
                    f"P-{event_index}-{index}",
                )
                for index in range(outcome_count)
            ),
        )
        price = Decimal("0.95") / Decimal(outcome_count)
        books = {
            (venue, outcome.name): BookSnapshot(
                venue=venue,
                outcome_name=outcome.name,
                market_key=f"{venue}-{outcome.name}",
                yes_bids=(DepthLevel(max(Decimal("0.02"), price - Decimal("0.01")), Decimal("1000")),),
                yes_asks=(DepthLevel(price, Decimal("1000")),),
                received_ts=now,
            )
            for outcome in event.outcomes
            for venue in ("kalshi", "polymarket_us")
        }
        detectors.append(Detector(event, Decimal("100"), min_non_widening_ticks=0))
        books_by_event.append(books)

    samples = []
    started = time.perf_counter()
    for update_index in range(updates):
        affected = update_index % event_count
        evaluation_started = time.perf_counter_ns()
        detectors[affected].evaluate(books_by_event[affected], now)
        samples.append((time.perf_counter_ns() - evaluation_started) / 1_000_000)
    elapsed = time.perf_counter() - started
    ordered = sorted(samples)

    def percentile(value: float) -> float:
        index = min(
            len(ordered) - 1,
            max(0, math.ceil((value / 100) * len(ordered)) - 1),
        )
        return ordered[index]

    return {
        "event_count": event_count,
        "minimum_outcomes": min(outcome_counts),
        "maximum_outcomes": max(outcome_counts),
        "updates": updates,
        "updates_per_second": updates / elapsed,
        "evaluation_ms": {
            "p50": percentile(50),
            "p95": percentile(95),
            "p99": percentile(99),
            "max": max(samples),
        },
        "acceptance": {
            "affected_event_evaluation_p99_under_10ms": percentile(99) < 10,
        },
    }
