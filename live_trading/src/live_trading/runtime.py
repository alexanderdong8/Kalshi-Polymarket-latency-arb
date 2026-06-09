from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from .capture import L2Capture
from .config import Settings
from .execution_persistence import ExecutionJournal
from .live_orders import LiveOrderClient
from .models import BookState
from .strategy.books import BookStore
from .strategy.bridge import StrategyBookBridge
from .strategy.detector import BasketEvaluation, Detector
from .strategy.execution.client import SimulatedOrderClient
from .strategy.execution.executor import EntryExecutor, ExecConfig, ExitConfig
from .strategy.execution.exit_monitor import ExitMonitor
from .strategy.execution.models import BasketAttempt, ExitAttempt
from .strategy.execution.models import Fill, LegState, OpenBasket
from .strategy.execution.positions import (
    PositionStore,
    build_open_basket_from_attempt,
)
from .strategy.fees import FeeConfig
from .strategy.manifest import EventManifest, load_event_manifest
from .venues.kalshi import KalshiClient
from .venues.polymarket_us import PolymarketUSClient

RunMode = Literal["monitor", "paper", "live"]


@dataclass
class RuntimeOptions:
    mode: RunMode
    config: Path
    capital: Decimal
    dashboard: bool = True
    dashboard_port: int = 8080
    data_dir: Path = Path("live_trading/data")


class RuntimeState:
    """Bounded, lossy UI side channel. Trading never awaits dashboard rendering."""

    def __init__(self, path: Path, max_queue: int = 4) -> None:
        self.path = path
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._writer(), name="dashboard-state-writer")

    def publish(self, payload: dict[str, Any]) -> None:
        if self.queue.full():
            with suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
                self.queue.task_done()
        with suppress(asyncio.QueueFull):
            self.queue.put_nowait(payload)

    async def close(self) -> None:
        if self._task is None:
            return
        await self.queue.put({"_stop": True})
        await self._task
        self._task = None

    async def _writer(self) -> None:
        while True:
            payload = await self.queue.get()
            try:
                if payload.get("_stop"):
                    return
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(payload, default=_json_default), encoding="utf-8")
                os.replace(temporary, self.path)
            finally:
                self.queue.task_done()


async def run_manifest_runtime(options: RuntimeOptions) -> None:
    manifest = load_event_manifest(options.config, require_approved=True)
    settings = Settings.from_env()
    if options.mode in {"paper", "live"} and options.capital <= 0:
        raise ValueError("--capital must be greater than zero in paper and live modes.")

    data_dir = options.data_dir / manifest.event.slug
    data_dir.mkdir(parents=True, exist_ok=True)
    journal = ExecutionJournal(data_dir / "execution.sqlite3")
    strategy_store = BookStore()
    bridge = StrategyBookBridge(manifest.event, strategy_store)
    position_store = PositionStore()
    for payload in journal.open_positions():
        await position_store.add(_open_basket_from_payload(payload))
    fee_cfg = FeeConfig.default()
    abort_event = asyncio.Event()

    if options.mode == "live":
        order_client = LiveOrderClient(settings, journal)
        await _confirm_live_start(manifest, options.capital, order_client)
    else:
        # Capital is split into venue wallets. The executor's aggregate cap remains
        # the user-specified amount, so no basket may commit more than that limit.
        order_client = SimulatedOrderClient(
            strategy_store,
            fee_cfg=fee_cfg,
            initial_balance=options.capital / Decimal("2") if options.capital > 0 else Decimal("0"),
            mutate_books=False,
        )

    detector = Detector(
        event=manifest.event,
        target_size=Decimal(str(settings.trade_size)),
        fee_cfg=fee_cfg,
        staleness_ms=float(settings.stale_after_seconds * Decimal("1000")),
    )
    latest_evaluation: BasketEvaluation | None = None
    attempts: list[BasketAttempt] = []
    exits: list[ExitAttempt] = []

    async def on_attempt(attempt: BasketAttempt) -> None:
        attempts.append(attempt)
        journal.append("basket_attempt", attempt, status=attempt.outcome)
        if attempt.outcome == "complete":
            basket = build_open_basket_from_attempt(
                basket_id=f"{manifest.event.slug}-{attempt.ts.isoformat()}",
                entered_ts=attempt.ts,
                target_basket_size=attempt.target_basket_size,
                legs=attempt.legs,
            )
            await position_store.add(basket)
            journal.append("position_opened", basket, status="open")

    async def on_exit(attempt: ExitAttempt) -> None:
        exits.append(attempt)
        journal.append("exit_attempt", attempt, status=attempt.kind)
        if attempt.all_legs_filled:
            journal.append(
                "position_closed",
                {"basket_id": attempt.basket_id, "realized_net_per_share": attempt.realized_net_per_share},
                status="closed",
            )

    executor = EntryExecutor(
        event=manifest.event,
        store=strategy_store,
        order_client=order_client,
        fee_cfg=fee_cfg,
        exec_cfg=ExecConfig(
            max_capital_per_trade=options.capital,
            min_capital_per_trade=min(Decimal("10"), options.capital),
        ),
        entry_threshold=detector.entry_threshold,
        slippage_buffer_per_share=detector.slippage_buffer_per_share,
        depth_haircut=detector.depth_haircut,
        on_attempt=on_attempt,
        abort_event=abort_event,
    )
    exit_monitor = ExitMonitor(
        store=strategy_store,
        order_client=order_client,
        position_store=position_store,
        fee_cfg=fee_cfg,
        cfg=ExitConfig(),
        on_exit_attempt=on_exit,
    )

    capture = L2Capture(data_dir / "capture", manifest.event.slug)
    state_path = data_dir / "dashboard_state.json"
    emergency_path = data_dir / "EMERGENCY_STOP"
    state_channel = RuntimeState(state_path)
    await capture.start()
    await state_channel.start()
    dashboard_process = _launch_dashboard(state_path, emergency_path, options) if options.dashboard else None

    sequence_by_market: dict[tuple[str, str], int] = {}
    stream_health = {
        "kalshi_updates": 0,
        "polymarket_us_updates": 0,
        "sequence_gaps": 0,
        "reconnects": 0,
    }

    async def consume(book: BookState) -> None:
        key = (book.venue, book.market_key)
        previous = sequence_by_market.get(key)
        if book.sequence is not None:
            if previous is not None and book.sequence > previous + 1:
                stream_health["sequence_gaps"] += 1
                capture.invalidate(f"sequence_gap:{book.venue}:{book.market_key}:{previous}->{book.sequence}")
            sequence_by_market[key] = book.sequence
        stream_health[f"{book.venue}_updates"] += 1
        capture.record(book)
        await bridge.apply(book)

    def on_reconnect() -> None:
        stream_health["reconnects"] += 1
        capture.invalidate("stream_reconnect")

    async def consume_kalshi() -> None:
        async for book in KalshiClient(settings).stream_orderbooks(
            list(manifest.event.kalshi_tickers), on_reconnect=on_reconnect
        ):
            await consume(book)

    async def consume_polymarket() -> None:
        async for book in PolymarketUSClient(settings).stream_orderbooks(
            list(manifest.event.polymarket_slugs), on_reconnect=on_reconnect
        ):
            await consume(book)

    async def strategy_loop() -> None:
        nonlocal latest_evaluation
        while True:
            if emergency_path.exists():
                abort_event.set()
                await _cancel_resting_orders(order_client)
                await asyncio.sleep(0.1)
                continue
            books = await strategy_store.snapshot()
            latest_evaluation, fire = detector.tick(books)
            if fire is not None and options.mode != "monitor":
                asyncio.create_task(executor.on_fire(fire), name="basket-entry")
            await asyncio.sleep(0.1)

    async def publish_state() -> None:
        while True:
            books = await strategy_store.snapshot()
            positions = await position_store.snapshot()
            accounting = _accounting_payload(attempts, exits, positions)
            state_channel.publish(
                {
                    "mode": options.mode,
                    "event": manifest.event.name,
                    "capital_limit": str(options.capital),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "emergency_stop": emergency_path.exists(),
                    "stream_health": stream_health,
                    "evaluation": _evaluation_payload(latest_evaluation),
                    "books": {
                        f"{venue}:{outcome}": {
                            "venue": venue,
                            "outcome": outcome,
                            "age_ms": book.age_seconds() * 1000,
                            "bids": [[str(level.price), str(level.size)] for level in book.yes_bids],
                            "asks": [[str(level.price), str(level.size)] for level in book.yes_asks],
                        }
                        for (venue, outcome), book in books.items()
                    },
                    "attempts": [_json_default(row) for row in attempts[-100:]],
                    "exits": [_json_default(row) for row in exits[-100:]],
                    "positions": [_json_default(row) for row in positions],
                    **accounting,
                }
            )
            await asyncio.sleep(0.25)

    tasks = [
        asyncio.create_task(consume_kalshi(), name="kalshi-event-stream"),
        asyncio.create_task(consume_polymarket(), name="polymarket-us-event-stream"),
        asyncio.create_task(strategy_loop(), name="strategy-loop"),
        asyncio.create_task(publish_state(), name="dashboard-state"),
    ]
    if options.mode != "monitor":
        tasks.append(asyncio.create_task(exit_monitor.run(), name="exit-monitor"))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _cancel_resting_orders(order_client)
        await capture.close()
        await state_channel.close()
        if dashboard_process is not None:
            dashboard_process.terminate()


async def _confirm_live_start(
    manifest: EventManifest,
    capital: Decimal,
    client: LiveOrderClient,
) -> None:
    preview = await client.reconcile()
    print("\nLIVE MONEY STARTUP PREVIEW")
    print(f"Event: {manifest.event.name}")
    print(f"Outcomes: {', '.join(outcome.name for outcome in manifest.event.outcomes)}")
    print(f"Capital limit: ${capital}")
    print(f"Kalshi balance: {preview['kalshi_balance']}")
    print(f"Polymarket US balance: {preview['polymarket_us_balance']}")
    print(f"Unresolved local orders: {len(preview['unresolved_local_orders'])}")
    print(f"Locally journaled open baskets: {len(preview['local_open_positions'])}")
    print(f"Kalshi reported positions: {len(preview['kalshi_positions'])}")
    print(f"Polymarket US reported positions: {len(preview['polymarket_us_positions'])}")
    confirmation = await asyncio.to_thread(input, 'Type "LIVE" to enable real orders: ')
    if confirmation.strip() != "LIVE":
        raise RuntimeError("Live startup cancelled; confirmation did not match LIVE.")


async def _cancel_resting_orders(order_client: Any) -> None:
    resting = getattr(order_client, "_resting", {})
    for order_id in list(resting):
        with suppress(Exception):
            await order_client.cancel_limit(order_id)


def _launch_dashboard(
    state_path: Path,
    emergency_path: Path,
    options: RuntimeOptions,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "live_trading.dashboard",
            "--state",
            str(state_path),
            "--emergency-stop",
            str(emergency_path),
            "--port",
            str(options.dashboard_port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _evaluation_payload(evaluation: BasketEvaluation | None) -> dict[str, Any] | None:
    if evaluation is None:
        return None
    return {
        "ts": evaluation.ts.isoformat(),
        "basket_cost": str(evaluation.basket_cost_per_share),
        "fees": str(evaluation.total_fees_per_share),
        "entry_cost": str(evaluation.entry_cost_per_share),
        "threshold": str(evaluation.entry_threshold),
        "edge": str(evaluation.edge_per_share),
        "achievable_size": str(evaluation.achievable_size),
        "max_book_age_ms": evaluation.max_book_age_ms,
        "blocked": {
            "empty": evaluation.any_empty,
            "stale": evaluation.any_stale,
            "extreme_price": evaluation.any_extreme_price,
        },
        "legs": [
            {
                "outcome": leg.outcome_name,
                "venue": leg.chosen_venue,
                "vwap": str(leg.vwap),
                "fee": str(leg.fee_total),
                "kalshi_ask": str(leg.kalshi_top_ask) if leg.kalshi_top_ask is not None else None,
                "polymarket_ask": str(leg.polymarket_top_ask)
                if leg.polymarket_top_ask is not None
                else None,
            }
            for leg in evaluation.legs
        ],
    }


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_default(item) for key, item in asdict(value).items()}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_default(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_default(item) for item in value]
    return value


def _open_basket_from_payload(payload: dict[str, Any]) -> OpenBasket:
    legs = []
    for raw_leg in payload.get("legs") or []:
        fills = [
            Fill(
                venue=raw["venue"],
                side=raw["side"],
                size=Decimal(str(raw["size"])),
                price=Decimal(str(raw["price"])),
                fees=Decimal(str(raw["fees"])),
                ts=datetime.fromisoformat(str(raw["ts"]).replace("Z", "+00:00")),
            )
            for raw in raw_leg.get("fills") or []
        ]
        legs.append(
            LegState(
                outcome_name=str(raw_leg["outcome_name"]),
                target_size=Decimal(str(raw_leg["target_size"])),
                fills=fills,
            )
        )
    return OpenBasket(
        basket_id=str(payload["basket_id"]),
        entered_ts=datetime.fromisoformat(str(payload["entered_ts"]).replace("Z", "+00:00")),
        target_basket_size=Decimal(str(payload["target_basket_size"])),
        legs=tuple(legs),
        cost_basis_per_share_total=Decimal(str(payload["cost_basis_per_share_total"])),
        entry_fees_per_share_total=Decimal(str(payload["entry_fees_per_share_total"])),
    )


def _accounting_payload(
    attempts: list[BasketAttempt],
    exits: list[ExitAttempt],
    positions: tuple[OpenBasket, ...],
) -> dict[str, Any]:
    orders = []
    fills = []
    total_fees = Decimal("0")
    realized_pnl = Decimal("0")
    for attempt in attempts:
        for round_record in (*attempt.rounds, *((attempt.unwind_round,) if attempt.unwind_round else ())):
            for order in round_record.orders:
                orders.append(
                    {
                        "ts": order.submit_ts.isoformat(),
                        "outcome": order.leg_outcome,
                        "venue": order.venue,
                        "side": order.side,
                        "requested": str(order.requested_size),
                        "filled": str(order.filled_size),
                        "price": str(order.actual_vwap),
                        "fees": str(order.actual_fees),
                        "reject_reason": order.reject_reason,
                    }
                )
        buys = Decimal("0")
        sells = Decimal("0")
        attempt_fees = Decimal("0")
        for leg in attempt.legs:
            for fill in leg.fills:
                fills.append(
                    {
                        "ts": fill.ts.isoformat(),
                        "outcome": leg.outcome_name,
                        "venue": fill.venue,
                        "side": fill.side,
                        "size": str(fill.size),
                        "price": str(fill.price),
                        "fees": str(fill.fees),
                    }
                )
                attempt_fees += fill.fees
                if fill.side == "buy":
                    buys += fill.size * fill.price
                else:
                    sells += fill.size * fill.price
        total_fees += attempt_fees
        if attempt.outcome != "complete":
            realized_pnl += sells - buys - attempt_fees
    exposure: dict[str, Decimal] = {}
    for basket in positions:
        for leg in basket.legs:
            for venue, size in leg.fills_by_venue().items():
                key = f"{venue}:{leg.outcome_name}"
                exposure[key] = exposure.get(key, Decimal("0")) + size
    for exit_attempt in exits:
        if exit_attempt.all_legs_filled:
            target = next(
                (
                    attempt.target_basket_size
                    for attempt in attempts
                    if attempt.outcome == "complete"
                    and attempt.ts.isoformat() in exit_attempt.basket_id
                ),
                Decimal("0"),
            )
            total_fees += exit_attempt.realized_exit_fees_per_share * target
            realized_pnl += (
                exit_attempt.realized_net_per_share
                * target
            )
    return {
        "orders": orders[-500:],
        "fills": fills[-500:],
        "accounting": {
            "total_fees": str(total_fees),
            "realized_pnl": str(realized_pnl),
            "exposure": {key: str(value) for key, value in exposure.items()},
        },
    }
