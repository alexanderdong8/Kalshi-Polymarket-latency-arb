import asyncio

from live_trading.benchmark import run_benchmarks


def test_short_benchmark_writes_report(tmp_path) -> None:
    target = tmp_path / "benchmark.json"
    report = asyncio.run(run_benchmarks([10], 0.05, str(target), profiles=["steady"]))

    assert target.exists()
    assert report["results"][0]["pair_count"] == 10
    assert report["results"][0]["updates_processed"] > 0
