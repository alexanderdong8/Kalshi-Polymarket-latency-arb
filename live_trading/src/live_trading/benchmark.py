from __future__ import annotations

import asyncio
import json
import random
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .books import BookStore
from .engine import HotPathEngine
from .metrics import MetricsCollector, monitor_event_loop_lag
from .models import BookState, MatchedMarket, VenueMarket
from .registry import PairRegistry
from .storage import SegmentedRecorder


async def run_benchmarks(
    pair_counts: list[int],
    duration_seconds: float,
    output_path: str,
    profiles: list[str] | None = None,
) -> dict[str, Any]:
    selected_profiles = profiles or ["steady", "burst", "stress"]
    results = []
    for pair_count in pair_counts:
        for profile in selected_profiles:
            results.append(await _run_case(pair_count, duration_seconds, profile))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds_per_case": duration_seconds,
        "profiles": selected_profiles,
        "results": results,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


async def _run_case(pair_count: int, duration_seconds: float, profile: str) -> dict[str, Any]:
    randomizer = random.Random(42 + pair_count)
    matches = synthetic_matches(pair_count)
    registry = PairRegistry.from_matches(matches)
    books = BookStore(stale_after_seconds=Decimal("5"))
    metrics = MetricsCollector()
    with tempfile.TemporaryDirectory(prefix=f"live-trading-benchmark-{pair_count}-") as temp_dir:
        recorder = SegmentedRecorder(
            temp_dir,
            quota_bytes=64 * 1024**2,
            low_watermark_bytes=56 * 1024**2,
            snapshot_interval_seconds=0.25,
            routine_queue_maxsize=max(1_000, pair_count * 4),
        )
        await recorder.start()
        engine = HotPathEngine(
            registry,
            books,
            metrics,
            trade_size=100,
            slippage_buffer_per_pair=Decimal("0.01"),
            kalshi_fee_mode="taker",
            polymarket_theta=Decimal("0.05"),
            min_gross_edge=Decimal("0"),
            recorder=recorder,
        )
        _prime_books(books, matches)
        signal_task = asyncio.create_task(engine.pump_signals(), name="benchmark-signal-pump")
        lag_task = asyncio.create_task(monitor_event_loop_lag(metrics, 0.01), name="benchmark-loop-lag")
        started = time.perf_counter()
        sequence = 0
        try:
            while time.perf_counter() - started < duration_seconds:
                burst_size, pause_seconds = _profile_load(profile)
                for _ in range(burst_size):
                    pair_index = sequence % pair_count
                    venue = "kalshi" if sequence % 2 == 0 else "polymarket_us"
                    opportunity_tick = sequence % 250 == 0
                    engine.process_book(
                        synthetic_book(
                            venue,
                            pair_index,
                            sequence,
                            opportunity_tick=opportunity_tick,
                            randomizer=randomizer,
                        )
                    )
                    sequence += 1
                await asyncio.sleep(0)
                if pause_seconds:
                    await asyncio.sleep(pause_seconds)
        finally:
            await engine.signal_queue.join()
            signal_task.cancel()
            lag_task.cancel()
            await asyncio.gather(signal_task, lag_task, return_exceptions=True)
            await recorder.close()
        metrics.update_recorder(recorder.metrics())
        summary = metrics.summary()
        summary["pair_count"] = pair_count
        summary["profile"] = profile
        summary["acceptance"] = {
            "receipt_to_eval_p99_under_10ms": _under(summary["receipt_to_eval_ms"]["p99"], 10),
            "event_loop_lag_p99_under_20ms": _under(summary["event_loop_lag_ms"]["p99"], 20),
            "process_rss_under_1gb": (summary["process_rss_bytes"] or 0) < 1024**3,
            "no_dropped_opportunities": summary["dropped_opportunities"] == 0,
        }
        return summary


def synthetic_matches(pair_count: int) -> list[MatchedMarket]:
    matches = []
    for index in range(pair_count):
        kalshi = VenueMarket(
            "kalshi",
            f"KXSYNTH-{index}",
            f"KXSYNTH-{index}",
            f"KXSYNTH-{index}",
            f"Synthetic event {index}",
            "sports",
            "binary",
            None,
            None,
            None,
        )
        poly = VenueMarket(
            "polymarket_us",
            f"pm-synth-{index}",
            None,
            f"pm-synth-{index}",
            f"Synthetic event {index}",
            "sports",
            "binary",
            None,
            None,
            None,
        )
        matches.append(MatchedMarket(f"KXSYNTH-{index}::pm-synth-{index}", kalshi, poly, Decimal("1"), "identity"))
    return matches


def synthetic_book(
    venue: str,
    pair_index: int,
    sequence: int,
    *,
    opportunity_tick: bool,
    randomizer: random.Random,
) -> BookState:
    jitter = Decimal(randomizer.choice(["0", "0.001", "0.002"]))
    if venue == "kalshi":
        yes_ask = Decimal("0.50") + jitter
        no_ask = Decimal("0.48") if opportunity_tick else Decimal("0.51") + jitter
        key = f"KXSYNTH-{pair_index}"
    else:
        yes_ask = Decimal("0.48") if opportunity_tick else Decimal("0.51") + jitter
        no_ask = Decimal("0.50") + jitter
        key = f"pm-synth-{pair_index}"
    return BookState(
        venue=venue,  # type: ignore[arg-type]
        market_key=key,
        yes_bid=Decimal("1") - no_ask,
        yes_ask=yes_ask,
        no_bid=Decimal("1") - yes_ask,
        no_ask=no_ask,
        yes_bid_size=Decimal("100"),
        yes_ask_size=Decimal("100"),
        no_bid_size=Decimal("100"),
        no_ask_size=Decimal("100"),
        received_ts=datetime.now(timezone.utc),
        sequence=sequence,
    )


def _prime_books(books: BookStore, matches: list[MatchedMarket]) -> None:
    randomizer = random.Random(1)
    for index, _ in enumerate(matches):
        books.set(synthetic_book("kalshi", index, 0, opportunity_tick=False, randomizer=randomizer))
        books.set(synthetic_book("polymarket_us", index, 0, opportunity_tick=False, randomizer=randomizer))


def print_benchmark_report(report: dict[str, Any], output_path: str) -> None:
    print(f"benchmark_report={output_path}")
    for result in report["results"]:
        print(
            "profile={profile} pairs={pair_count} updates={updates_processed} updates_per_second={updates_per_second:.1f} "
            "receipt_p99_ms={receipt} eval_p99_ms={evaluation} loop_lag_p99_ms={lag} "
            "cpu={cpu:.1f}% rss_mb={rss:.1f} dropped_snapshots={dropped}".format(
                profile=result["profile"],
                pair_count=result["pair_count"],
                updates_processed=result["updates_processed"],
                updates_per_second=result["updates_per_second"],
                receipt=_fmt(result["receipt_to_eval_ms"]["p99"]),
                evaluation=_fmt(result["evaluation_ms"]["p99"]),
                lag=_fmt(result["event_loop_lag_ms"]["p99"]),
                cpu=result["process_cpu_percent"] or 0,
                rss=(result["process_rss_bytes"] or 0) / 1024**2,
                dropped=result["recorder"]["dropped_routine_snapshots"],
            )
        )


def _profile_load(profile: str) -> tuple[int, float]:
    if profile == "steady":
        return 10, 0.002
    if profile == "burst":
        return 100, 0.01
    if profile == "stress":
        return 100, 0.0
    raise ValueError(f"Unknown benchmark profile: {profile}")


def _under(value: float | None, limit: float) -> bool:
    return value is not None and value < limit


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"
