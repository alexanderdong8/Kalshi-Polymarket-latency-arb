from __future__ import annotations

import asyncio
import json
import math
import os
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


try:
    import psutil
except ImportError:  # pragma: no cover - optional fallback
    psutil = None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((percentile / 100) * len(ordered)) - 1))
    return ordered[index]


@dataclass(frozen=True)
class RecorderMetrics:
    routine_queue_depth: int = 0
    durable_queue_depth: int = 0
    max_routine_queue_depth: int = 0
    dropped_routine_snapshots: int = 0
    sqlite_writes: int = 0
    sqlite_writes_per_second: float = 0.0
    rotation_count: int = 0
    disk_usage_bytes: int = 0


@dataclass
class MetricsCollector:
    sample_limit: int = 100_000
    counters: Counter[str] = field(default_factory=Counter)
    gauges: dict[str, float] = field(default_factory=dict)
    receipt_to_eval_ms: deque[float] = field(init=False)
    evaluation_ms: deque[float] = field(init=False)
    event_loop_lag_ms: deque[float] = field(init=False)
    _started: float = field(default_factory=time.perf_counter)
    _process: Any = field(init=False, default=None)
    _recorder_metrics: RecorderMetrics = field(default_factory=RecorderMetrics)

    def __post_init__(self) -> None:
        self.receipt_to_eval_ms = deque(maxlen=self.sample_limit)
        self.evaluation_ms = deque(maxlen=self.sample_limit)
        self.event_loop_lag_ms = deque(maxlen=self.sample_limit)
        if psutil is not None:
            self._process = psutil.Process(os.getpid())
            self._process.cpu_percent(interval=None)

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def record_evaluation(self, receipt_to_eval_ms: float, evaluation_ms: float) -> None:
        self.receipt_to_eval_ms.append(receipt_to_eval_ms)
        self.evaluation_ms.append(evaluation_ms)

    def record_loop_lag(self, lag_ms: float) -> None:
        self.event_loop_lag_ms.append(max(0.0, lag_ms))

    def record_reconnect(self, _: str) -> None:
        self.increment("reconnects")

    def update_recorder(self, recorder_metrics: RecorderMetrics) -> None:
        self._recorder_metrics = recorder_metrics

    def summary(self) -> dict[str, Any]:
        duration = max(time.perf_counter() - self._started, 1e-9)
        receipt = list(self.receipt_to_eval_ms)
        evaluation = list(self.evaluation_ms)
        lag = list(self.event_loop_lag_ms)
        rss_bytes = self._process.memory_info().rss if self._process else None
        cpu_percent = self._process.cpu_percent(interval=None) if self._process else None
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration,
            "updates_processed": self.counters["updates_processed"],
            "updates_per_second": self.counters["updates_processed"] / duration,
            "pair_evaluations": self.counters["pair_evaluations"],
            "opportunities_emitted": self.counters["opportunities_emitted"],
            "dropped_opportunities": self.counters["dropped_opportunities"],
            "reconnects": self.counters["reconnects"],
            "subscription_topology_restarts": self.counters["subscription_topology_restarts"],
            "discovery_refreshes": self.counters["discovery_refreshes"],
            "discovery_refresh_failures": self.counters["discovery_refresh_failures"],
            "stale_books": self.counters["stale_books"],
            "signal_queue_depth": int(self.gauges.get("signal_queue_depth", 0)),
            "receipt_to_eval_ms": _latency_summary(receipt),
            "evaluation_ms": _latency_summary(evaluation),
            "event_loop_lag_ms": _latency_summary(lag),
            "process_rss_bytes": rss_bytes,
            "process_cpu_percent": cpu_percent,
            "recorder": asdict(self._recorder_metrics),
        }

    def write_json(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.summary(), indent=2, sort_keys=True), encoding="utf-8")


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": max(values) if values else None,
    }


async def monitor_event_loop_lag(metrics: MetricsCollector, interval_seconds: float = 0.1) -> None:
    expected = time.perf_counter() + interval_seconds
    while True:
        await asyncio.sleep(interval_seconds)
        now = time.perf_counter()
        metrics.record_loop_lag((now - expected) * 1000)
        expected = now + interval_seconds
