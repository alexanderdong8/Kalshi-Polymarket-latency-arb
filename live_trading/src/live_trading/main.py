from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import suppress
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from pprint import pprint

from .arb import evaluate_match
from .benchmark import print_benchmark_report, run_benchmarks
from .books import BookStore
from .config import Settings
from .engine import HotPathEngine
from .matching import MatchConfig, match_markets
from .metrics import MetricsCollector, monitor_event_loop_lag
from .models import BookState, MatchedMarket
from .registry import PairRegistry
from .storage import SegmentedRecorder
from .tui import Dashboard
from .venues.kalshi import KalshiClient
from .venues.polymarket_us import PolymarketUSClient
from .runtime import RuntimeOptions, run_manifest_runtime
from .strategy_benchmark import benchmark_strategy_and_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only live Kalshi / Polymarket US scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="Discover active matched markets")
    discover.add_argument("--categories", default="sports,politics,crypto,economics")
    discover.add_argument("--max-matches", type=int, default=None)

    run = sub.add_parser("run", help="Run manifest-driven monitor, paper, or live trading")
    run.add_argument("--mode", choices=("monitor", "paper", "live"), default=None)
    run.add_argument("--config", default=None, help="Reviewed multi-outcome event YAML")
    run.add_argument("--capital", type=Decimal, default=Decimal("0"))
    run.add_argument("--dashboard", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--dashboard-port", type=int, default=8080)
    run.add_argument("--confirmed-live", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--strategy-json", default=None, help=argparse.SUPPRESS)
    run.add_argument("--categories", default="sports,politics,crypto,economics")
    run.add_argument("--max-matches", type=int, default=None)
    run.add_argument("--metrics-out", default=None)

    benchmark = sub.add_parser("benchmark", help="Benchmark event-driven scanner throughput with synthetic books")
    benchmark.add_argument("--pairs", default="100,250,500")
    benchmark.add_argument("--duration-seconds", type=float, default=60.0)
    benchmark.add_argument("--profiles", default="steady,burst,stress")
    benchmark.add_argument("--out", default="live_trading/data/benchmarks/latest.json")
    strategy_benchmark = sub.add_parser(
        "strategy-benchmark",
        help="Benchmark strategy evaluation separately from dashboard serialization",
    )
    strategy_benchmark.add_argument("--iterations", type=int, default=10_000)

    doctor = sub.add_parser("doctor", help="Validate configured venue APIs without placing orders")
    doctor.add_argument("--categories", default="sports")
    doctor.add_argument("--timeout-seconds", type=float, default=8.0)

    sub.add_parser("sample-tui", help="Render a fake dashboard without credentials")

    args = parser.parse_args()
    if args.command == "discover":
        asyncio.run(run_discover(args))
    elif args.command == "run":
        asyncio.run(run_live(args))
    elif args.command == "benchmark":
        asyncio.run(run_benchmark(args))
    elif args.command == "strategy-benchmark":
        pprint(benchmark_strategy_and_dashboard(args.iterations))
    elif args.command == "doctor":
        asyncio.run(run_doctor(args))
    elif args.command == "sample-tui":
        sample_tui()


async def run_discover(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    categories = _parse_categories(args.categories)
    matches = await discover_matches(settings, categories, args.max_matches or settings.max_matches)
    for match in matches:
        pprint(
            {
                "match_id": match.match_id,
                "confidence": str(match.confidence),
                "kalshi": match.kalshi.title,
                "polymarket_us": match.polymarket_us.title,
                "warnings": match.warnings,
            }
        )
    print(f"matched_markets={len(matches)}")


async def run_live(args: argparse.Namespace) -> None:
    if args.config:
        if args.mode is None:
            raise ValueError("--mode is required when --config is supplied.")
        await run_manifest_runtime(
            RuntimeOptions(
                mode=args.mode,
                config=Path(args.config),
                capital=args.capital,
                dashboard=args.dashboard,
                dashboard_port=args.dashboard_port,
                live_confirmed=args.confirmed_live,
                strategy_settings=json.loads(args.strategy_json) if args.strategy_json else None,
            )
        )
        return
    settings = Settings.from_env()
    categories = _parse_categories(args.categories)
    store = BookStore(stale_after_seconds=settings.stale_after_seconds)
    recorder = SegmentedRecorder(
        settings.live_data_dir,
        quota_bytes=settings.live_data_quota_bytes,
        low_watermark_bytes=settings.live_data_low_watermark_bytes,
        snapshot_interval_seconds=float(settings.snapshot_interval_seconds),
        routine_queue_maxsize=settings.routine_queue_maxsize,
    )
    await recorder.start()
    matches = await discover_matches(settings, categories, args.max_matches or settings.max_matches)
    for match in matches:
        recorder.try_record_match(match)

    kalshi_client = KalshiClient(settings)
    poly_client = PolymarketUSClient(settings)
    dashboard = Dashboard(stale_after_seconds=settings.stale_after_seconds)
    metrics = MetricsCollector()
    registry = PairRegistry.from_matches(matches)
    engine = HotPathEngine(
        registry,
        store,
        metrics,
        trade_size=settings.trade_size,
        slippage_buffer_per_pair=settings.slippage_buffer_per_pair,
        kalshi_fee_mode=settings.kalshi_fee_mode,
        polymarket_theta=settings.polymarket_taker_theta,
        min_gross_edge=settings.min_gross_edge,
        recorder=recorder,
    )

    async def consume_kalshi(active_matches: list[MatchedMarket]) -> None:
        async for book in kalshi_client.stream_orderbooks(
            [match.kalshi.stream_key for match in active_matches],
            on_reconnect=metrics.record_reconnect,
        ):
            engine.process_book(book)

    async def consume_poly(active_matches: list[MatchedMarket]) -> None:
        review_slugs = [
            match.polymarket_us.stream_key for match in active_matches if not match.is_tradeable_candidate
        ]
        async for book in poly_client.stream_orderbooks(
            [match.polymarket_us.stream_key for match in active_matches],
            lite_slugs=review_slugs,
            on_reconnect=metrics.record_reconnect,
        ):
            engine.process_book(book)

    async def supervise_streams() -> None:
        signature: tuple[tuple[str, str], ...] | None = None
        stream_tasks: list[asyncio.Task] = []
        try:
            while True:
                active_matches = list(registry.matches.values())
                next_signature = tuple(
                    sorted((match.kalshi.stream_key, match.polymarket_us.stream_key) for match in active_matches)
                )
                if next_signature != signature:
                    await _cancel_tasks(stream_tasks)
                    stream_tasks = []
                    if active_matches:
                        stream_tasks = [
                            asyncio.create_task(consume_kalshi(active_matches), name="kalshi-stream-supervisor"),
                            asyncio.create_task(consume_poly(active_matches), name="polymarket-stream-supervisor"),
                        ]
                    signature = next_signature
                    metrics.increment("subscription_topology_restarts")
                await asyncio.sleep(1)
        finally:
            await _cancel_tasks(stream_tasks)

    async def refresh_discovery() -> None:
        while True:
            await asyncio.sleep(settings.discovery_refresh_seconds)
            try:
                refreshed = await discover_matches(settings, categories, args.max_matches or settings.max_matches)
            except Exception:  # noqa: BLE001
                metrics.increment("discovery_refresh_failures")
                continue
            registry.replace(refreshed)
            engine.opportunities.retain(set(registry.matches))
            for match in refreshed:
                recorder.try_record_match(match)
            metrics.increment("discovery_refreshes")

    async def refresh_tui() -> None:
        with dashboard.live(refresh_per_second=float(Decimal("1") / settings.tui_refresh_seconds)) as live:
            while True:
                metrics.counters["stale_books"] = sum(
                    book.is_stale(settings.stale_after_seconds) for book in store.snapshot().values()
                )
                recorder_metrics = recorder.metrics()
                metrics.update_recorder(recorder_metrics)
                live.update(
                    dashboard.render(
                        list(registry.matches.values()),
                        store.snapshot(),
                        engine.opportunities.snapshot(),
                        metrics.summary(),
                        recorder_metrics,
                    )
                )
                await asyncio.sleep(float(settings.tui_refresh_seconds))

    async def write_metrics() -> None:
        while True:
            metrics.update_recorder(recorder.metrics())
            payload = metrics.summary()
            recorder.try_record_metrics(payload)
            if args.metrics_out:
                metrics.write_json(args.metrics_out)
            await asyncio.sleep(float(settings.metrics_write_seconds))

    try:
        await asyncio.gather(
            supervise_streams(),
            refresh_discovery(),
            engine.pump_signals(),
            monitor_event_loop_lag(metrics),
            write_metrics(),
            refresh_tui(),
        )
    finally:
        await recorder.close()


async def _cancel_tasks(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


async def run_benchmark(args: argparse.Namespace) -> None:
    pair_counts = [int(value.strip()) for value in args.pairs.split(",") if value.strip()]
    profiles = [value.strip() for value in args.profiles.split(",") if value.strip()]
    report = await run_benchmarks(pair_counts, args.duration_seconds, args.out, profiles=profiles)
    print_benchmark_report(report, args.out)


async def run_doctor(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    categories = _parse_categories(args.categories)
    kalshi_client = KalshiClient(settings)
    poly_client = PolymarketUSClient(settings)

    print("Credential presence:")
    print(f"  Kalshi key id: {'present' if settings.kalshi_api_key_id else 'missing'}")
    print(f"  Kalshi private key: {'present' if settings.kalshi_private_key_path or settings.kalshi_private_key_pem else 'missing'}")
    print(f"  Polymarket US key id: {'present' if settings.polymarket_key_id else 'missing'}")
    print(f"  Polymarket US secret key: {'present' if settings.polymarket_secret_key else 'missing'}")

    print("Testing REST endpoints...", flush=True)
    kalshi_markets = await _doctor_step(
        "Kalshi REST active markets",
        kalshi_client.list_active_markets(categories=None, limit=10, timeout_seconds=8, retries=2, max_pages=1),
    )
    poly_markets = await _doctor_step(
        "Polymarket US REST active markets",
        poly_client.list_active_markets(categories=categories, limit=10, timeout_seconds=8),
    )
    kalshi_markets = kalshi_markets or []
    poly_markets = poly_markets or []
    print(f"  Kalshi markets fetched: {len(kalshi_markets)}")
    print(f"  Polymarket US markets fetched: {len(poly_markets)}")

    if poly_markets:
        await _doctor_step("Polymarket US REST first order book", poly_client.fetch_book(poly_markets[0].stream_key))

    matches = match_markets(
        kalshi_markets,
        poly_markets,
        MatchConfig(min_confidence=settings.min_match_confidence),
    )[:5]
    print(f"  Candidate matches from fetched sample: {len(matches)}")
    for match in matches:
        print(f"    {match.confidence} | {match.kalshi.title[:48]} <> {match.polymarket_us.title[:48]}")

    print("Testing WebSocket endpoints...", flush=True)
    if kalshi_markets and settings.kalshi_api_key_id and (settings.kalshi_private_key_path or settings.kalshi_private_key_pem):
        await _doctor_stream_step(
            "Kalshi WebSocket first orderbook message",
            kalshi_client.stream_orderbooks([kalshi_markets[0].stream_key]),
            timeout_seconds=args.timeout_seconds,
        )
    else:
        print("SKIP Kalshi WebSocket first orderbook message: missing credentials or no market.")

    if poly_markets and settings.polymarket_key_id and settings.polymarket_secret_key:
        await _doctor_stream_step(
            "Polymarket US WebSocket first market-data message",
            poly_client.stream_orderbooks([poly_markets[0].stream_key]),
            timeout_seconds=args.timeout_seconds,
        )
    else:
        print("SKIP Polymarket US WebSocket first market-data message: missing credentials or no market.")


async def _doctor_step(label: str, awaitable):
    try:
        result = await awaitable
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {label}: {type(exc).__name__}: {exc}")
        return None
    print(f"OK   {label}")
    return result


async def _doctor_stream_step(label: str, stream, timeout_seconds: float) -> None:
    try:
        state = await asyncio.wait_for(anext(stream), timeout=timeout_seconds)
    except StopAsyncIteration:
        print(f"FAIL {label}: stream ended without data")
    except asyncio.TimeoutError:
        print(f"FAIL {label}: timed out after {timeout_seconds:.1f}s")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {label}: {type(exc).__name__}: {exc}")
    else:
        print(f"OK   {label}: {state.venue} {state.market_key}")
    finally:
        await stream.aclose()


async def discover_matches(settings: Settings, categories: list[str], max_matches: int) -> list[MatchedMarket]:
    kalshi_client = KalshiClient(settings)
    poly_client = PolymarketUSClient(settings)
    kalshi_markets, poly_markets = await asyncio.gather(
        kalshi_client.list_active_markets(categories=categories, limit=max_matches * 12),
        poly_client.list_active_markets(categories=categories, limit=max_matches * 12),
    )
    return match_markets(
        kalshi_markets,
        poly_markets,
        MatchConfig(min_confidence=settings.min_match_confidence),
    )[:max_matches]


def sample_tui() -> None:
    from datetime import datetime, timezone
    from .models import VenueMarket

    ts = datetime.now(timezone.utc)
    kalshi = VenueMarket(
        venue="kalshi",
        market_id="KXTEST",
        ticker="KXTEST",
        slug="KXTEST",
        title="Will Team A win?",
        category="sports",
        market_type="moneyline",
        start_time=ts,
        close_time=ts,
        expiration_time=ts,
    )
    poly = VenueMarket(
        venue="polymarket_us",
        market_id="poly-test",
        ticker=None,
        slug="poly-test",
        title="Team A vs Team B",
        category="sports",
        market_type="moneyline",
        start_time=ts,
        close_time=ts,
        expiration_time=ts,
    )
    match = MatchedMarket("KXTEST::poly-test", kalshi, poly, Decimal("0.95"), "identity")
    kalshi_book = BookState("kalshi", "KXTEST", Decimal("0.70"), Decimal("0.70"), Decimal("0.30"), Decimal("0.30"))
    poly_book = BookState("polymarket_us", "poly-test", Decimal("0.50"), Decimal("0.50"), Decimal("0.50"), Decimal("0.50"))
    opportunities = evaluate_match(
        match,
        kalshi_book,
        poly_book,
        trade_size=100,
        slippage_buffer_per_pair=Decimal("0.01"),
    )
    Dashboard(Decimal("5")).console.print(
        Dashboard(Decimal("5")).render(
            [match],
            {("kalshi", "KXTEST"): kalshi_book, ("polymarket_us", "poly-test"): poly_book},
            opportunities,
        )
    )


def _parse_categories(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    main()
