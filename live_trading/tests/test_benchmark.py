import asyncio

from live_trading.benchmark import run_benchmarks
from live_trading.strategy_benchmark import benchmark_multi_event_strategy


def test_short_benchmark_writes_report(tmp_path) -> None:
    target = tmp_path / "benchmark.json"
    report = asyncio.run(run_benchmarks([10], 0.05, str(target), profiles=["steady"]))

    assert target.exists()
    assert report["results"][0]["pair_count"] == 10
    assert report["results"][0]["updates_processed"] > 0


def test_multi_event_benchmark_covers_target_shape() -> None:
    result = benchmark_multi_event_strategy(
        event_count=40, max_outcomes=40, updates=80
    )

    assert result["event_count"] == 40
    assert result["maximum_outcomes"] == 40
    assert result["evaluation_ms"]["p99"] >= 0
