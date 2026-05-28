from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from decimal import Decimal
from pprint import pprint

from .arb import evaluate_all, evaluate_match
from .books import BookStore
from .config import Settings
from .matching import MatchConfig, match_markets
from .models import BookState, MatchedMarket
from .storage import SQLiteRecorder
from .tui import Dashboard
from .venues.kalshi import KalshiClient
from .venues.polymarket_us import PolymarketUSClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only live Kalshi / Polymarket US scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="Discover active matched markets")
    discover.add_argument("--categories", default="sports,politics,crypto,economics")
    discover.add_argument("--max-matches", type=int, default=None)

    run = sub.add_parser("run", help="Run live streaming dashboard")
    run.add_argument("--categories", default="sports,politics,crypto,economics")
    run.add_argument("--max-matches", type=int, default=None)

    doctor = sub.add_parser("doctor", help="Validate configured venue APIs without placing orders")
    doctor.add_argument("--categories", default="sports")
    doctor.add_argument("--timeout-seconds", type=float, default=8.0)

    sub.add_parser("sample-tui", help="Render a fake dashboard without credentials")

    args = parser.parse_args()
    if args.command == "discover":
        asyncio.run(run_discover(args))
    elif args.command == "run":
        asyncio.run(run_live(args))
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
    settings = Settings.from_env()
    categories = _parse_categories(args.categories)
    store = BookStore(stale_after_seconds=settings.stale_after_seconds)
    recorder = SQLiteRecorder(settings.sqlite_path)
    await recorder.start()
    matches = await discover_matches(settings, categories, args.max_matches or settings.max_matches)
    for match in matches:
        await recorder.record_match(match)

    kalshi_client = KalshiClient(settings)
    poly_client = PolymarketUSClient(settings)
    dashboard = Dashboard(stale_after_seconds=settings.stale_after_seconds)

    async def consume_kalshi() -> None:
        async for book in kalshi_client.stream_orderbooks([match.kalshi.stream_key for match in matches]):
            store.set(book)
            await recorder.record_book(book)

    async def consume_poly() -> None:
        async for book in poly_client.stream_orderbooks([match.polymarket_us.stream_key for match in matches]):
            store.set(book)
            await recorder.record_book(book)

    async def refresh_tui() -> None:
        seen: set[tuple[str, str, str]] = set()
        with dashboard.live(refresh_per_second=float(Decimal("1") / settings.tui_refresh_seconds)) as live:
            while True:
                opportunities = evaluate_all(
                    matches,
                    store.snapshot(),
                    trade_size=settings.trade_size,
                    slippage_buffer_per_pair=settings.slippage_buffer_per_pair,
                    kalshi_fee_mode=settings.kalshi_fee_mode,
                    polymarket_theta=settings.polymarket_taker_theta,
                    min_gross_edge=settings.min_gross_edge,
                )
                for opp in opportunities:
                    key = (opp.match_id, opp.direction, opp.detected_ts.isoformat(timespec="seconds"))
                    if key not in seen:
                        seen.add(key)
                        await recorder.record_opportunity(opp)
                live.update(dashboard.render(matches, store.snapshot(), opportunities))
                await asyncio.sleep(float(settings.tui_refresh_seconds))

    try:
        await asyncio.gather(consume_kalshi(), consume_poly(), refresh_tui())
    finally:
        await recorder.close()


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
