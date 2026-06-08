from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from rich.console import Console

from .books import BookStore
from .config import ConfigError, load_credentials, load_endpoints, load_event
from .detector import BasketEvaluation, Detector, FireEvent, fire_to_jsonl_payload
from .execution import (
    EntryExecutor,
    ExecConfig,
    ExitConfig,
    ExitJournal,
    ExitMonitor,
    PositionStore,
    SimulatedOrderClient,
    TradeJournal,
    basket_attempt_to_jsonl_payload,
    build_open_basket_from_attempt,
)
from .fees import FeeConfig
from .jsonl import jsonl_writer
from .keys import listen_for_abort_key
from .mock import run_kalshi_mock, run_polymarket_mock
from .pnl import PnLJournal, PnLTracker, RealizedPnLAccumulator, _realized_from_legs
from .tui import render, run_tui
from .venues import run_kalshi_stream, run_polymarket_stream


@dataclass
class DetectorState:
    """Shared snapshot of detector + executor output, read by the TUI footer."""
    latest: BasketEvaluation | None = None
    last_fire: FireEvent | None = None
    fire_count: int = 0
    tick_count: int = 0
    # execution-side
    last_attempt: object | None = None  # BasketAttempt; declared loosely to avoid import cycle in tui.py
    attempt_count: int = 0
    completed_count: int = 0
    unwound_count: int = 0
    aborted_count: int = 0
    user_aborted_count: int = 0
    executor_busy: bool = False
    # exit-side
    open_positions: int = 0
    exit_fills: int = 0
    last_exit: object | None = None  # ExitAttempt
    # pnl-side
    latest_pnl: object | None = None  # PnLSnapshot
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def update(self, ev: BasketEvaluation, fire: FireEvent | None) -> None:
        async with self._lock:
            self.latest = ev
            self.tick_count += 1
            if fire is not None:
                self.last_fire = fire
                self.fire_count += 1

    async def update_executor_busy(self, busy: bool) -> None:
        async with self._lock:
            self.executor_busy = busy

    async def record_attempt(self, attempt) -> None:
        async with self._lock:
            self.last_attempt = attempt
            self.attempt_count += 1
            if attempt.outcome == "complete":
                self.completed_count += 1
            elif attempt.outcome in ("unwound_timeout", "unwound_loss", "unwound_no_residual_depth"):
                self.unwound_count += 1
            elif attempt.outcome == "aborted_by_user":
                self.aborted_count += 1
                self.user_aborted_count += 1
            else:
                self.aborted_count += 1

    async def record_exit(self, attempt, open_positions: int) -> None:
        async with self._lock:
            self.last_exit = attempt
            self.open_positions = open_positions
            if getattr(attempt, "kind", None) == "fill" and getattr(attempt, "all_legs_filled", False):
                self.exit_fills += 1

    async def set_open_positions(self, n: int) -> None:
        async with self._lock:
            self.open_positions = n

    async def set_pnl(self, snap) -> None:
        async with self._lock:
            self.latest_pnl = snap
            self.open_positions = snap.open_count


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="trade-system",
        description="Stream live order books for one prediction-market event from Kalshi + Polymarket US.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to event YAML file (see config/example_event.yaml).",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("logs"),
        help="Directory for JSONL logs (default: ./logs).",
    )
    parser.add_argument(
        "--only",
        choices=["kalshi", "polymarket_us", "both"],
        default="both",
        help="Restrict to one venue (useful for debugging).",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Disable the live TUI (JSONL logging continues).",
    )
    parser.add_argument(
        "--refresh-hz",
        type=float,
        default=4.0,
        help="TUI refresh rate in Hz (default: 4).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Stream synthetic data instead of connecting to live venues (no creds needed).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after N seconds (useful for demos/tests).",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=None,
        help="Render N static TUI frames to stdout (no Live mode). Implies --mock-friendly output.",
    )
    parser.add_argument(
        "--target-size",
        type=Decimal,
        default=None,
        help="Basket target size in contracts. Enables the opportunity detector when set.",
    )
    parser.add_argument(
        "--detector-hz",
        type=float,
        default=10.0,
        help="Detector tick rate (Hz). Must be >= 10. Default 10.",
    )
    parser.add_argument(
        "--entry-threshold",
        type=Decimal,
        default=Decimal("0.98"),
        help="Fire when basket entry cost (cost + fees + slippage_buffer) per share is "
             "below this. Default 0.98.",
    )
    parser.add_argument(
        "--slippage-buffer-per-share",
        type=Decimal,
        default=Decimal("0.005"),
        help="Per-share dollar haircut added to the basket entry cost before testing "
             "against --entry-threshold. Models in-flight book movement during fill. "
             "Default 0.005 = 0.5¢/share. Set to 0 to disable.",
    )
    parser.add_argument(
        "--depth-haircut",
        type=Decimal,
        default=Decimal("0.7"),
        help="Fraction of each displayed depth level treated as reachable. The walker "
             "multiplies every level's size by this factor. Models maker cancellations "
             "and queue jumping on aggressive flow. Must be in (0, 1]. Default 0.7.",
    )
    parser.add_argument(
        "--momentum-window-ms",
        type=int,
        default=500,
        help="Rolling window for the momentum velocity estimate, milliseconds. Default 500.",
    )
    parser.add_argument(
        "--non-widening-ticks",
        type=int,
        default=2,
        help="Number of consecutive non-widening ticks required before firing. A tick is "
             "non-widening when basket-edge velocity <= --near-zero-threshold (negative, "
             "flat, or near-zero counts). Default 2.",
    )
    parser.add_argument(
        "--near-zero-threshold",
        type=Decimal,
        default=Decimal("0.01"),
        help="Velocity (in basket-edge dollars per share per second) at or below which a "
             "tick is treated as non-widening. 0 = strict (only flat or shrinking counts). "
             "Default 0.01 tolerates sub-cent drift (~0.1¢/share/tick at 10 Hz) and "
             "rejects real per-tick widening (a 1¢ flick is ~10× this).",
    )
    parser.add_argument(
        "--min-leg-bid",
        type=Decimal,
        default=Decimal("0.02"),
        help="Skip basket if any leg's best YES bid is below this. Default 0.02.",
    )
    parser.add_argument(
        "--max-leg-bid",
        type=Decimal,
        default=Decimal("0.98"),
        help="Skip basket if any leg's best YES bid is above this. Default 0.98.",
    )
    parser.add_argument(
        "--kalshi-theta",
        type=Decimal,
        default=Decimal("0.07"),
        help="Kalshi taker fee theta (default 0.07; per docs.kalshi.com).",
    )
    parser.add_argument(
        "--polymarket-theta",
        type=Decimal,
        default=Decimal("0.05"),
        help="Polymarket US taker fee theta (default 0.05; per docs.polymarket.us/fees).",
    )
    # Execution layer
    parser.add_argument(
        "--enable-execution",
        action="store_true",
        help="Enable the simulated order-placement layer. On every fire, builds N IOC orders "
             "in parallel, retries residuals with re-walked prices, and unwinds partial baskets "
             "on timeout or unhedged-loss kill switch. No real venue API calls — paper trading.",
    )
    parser.add_argument(
        "--max-capital-per-trade",
        type=Decimal,
        default=Decimal("50"),
        help="Max dollars to commit per fire. Actual capital = min(this, total balance). "
             "Default $50.",
    )
    parser.add_argument(
        "--min-capital-per-trade",
        type=Decimal,
        default=Decimal("10"),
        help="Skip the trade if the basket dollar value would be below this floor. "
             "Default $10.",
    )
    parser.add_argument(
        "--profitable-depth-fraction",
        type=Decimal,
        default=Decimal("0.5"),
        help="Cap on basket size in contracts: fraction × min over legs of "
             "(contracts available at price ≤ max-profitable-price). Models 'don't "
             "dominate the displayed profitable depth on any leg'. Default 0.5 (50%%).",
    )
    parser.add_argument(
        "--initial-balance",
        type=Decimal,
        default=Decimal("1000"),
        help="Per-venue starting balance for the simulated client. Default $1000.",
    )
    parser.add_argument(
        "--retry-seconds",
        type=float,
        default=2.0,
        help="Total wall-clock budget to retry residual IOC orders before unwinding. Default 2.",
    )
    parser.add_argument(
        "--retry-poll-ms",
        type=float,
        default=100.0,
        help="When residuals are not currently profitable, sleep this many ms between "
             "re-checks. Default 100.",
    )
    parser.add_argument(
        "--max-unhedged-loss-pct",
        type=Decimal,
        default=Decimal("0.05"),
        help="Unwind early if mark-to-market loss on filled-but-not-complete positions "
             "exceeds this fraction of their current mark. Default 0.05 (5%%).",
    )
    # Exit layer (path A limit-fill + path B hold-to-settlement)
    parser.add_argument(
        "--enable-exit-monitor",
        action="store_true",
        help="Enable the exit monitor. After a basket completes, watch for the chance to "
             "post easy-to-fill limit sells (path A) when the cross-venue prices re-couple, "
             "leg prices are sane, the round trip clears margin, and bids are stable. "
             "Otherwise hold to settlement (path B). Requires --enable-execution.",
    )
    parser.add_argument(
        "--exit-coupling-tolerance",
        type=Decimal,
        default=Decimal("0.01"),
        help="Path A fires only when the per-share sum of best YES bids across legs is "
             ">= $1 - this. Default 0.01 (i.e. basket bid sum >= $0.99).",
    )
    parser.add_argument(
        "--exit-bid-stability-ticks",
        type=int,
        default=2,
        help="Number of consecutive monitor ticks each leg's best bid must stay within "
             "--exit-bid-stability-threshold before path A fires. Default 2.",
    )
    parser.add_argument(
        "--exit-bid-stability-threshold",
        type=Decimal,
        default=Decimal("0.01"),
        help="Max per-tick move (dollars) in a leg's best bid for it to count as stable. "
             "Soft volatility filter, mirroring the entry momentum filter. Default 0.01.",
    )
    parser.add_argument(
        "--exit-required-margin-per-share",
        type=Decimal,
        default=Decimal("0.01"),
        help="Required per-share net margin for path A: avg_buy + entry_fees + exit_fees + "
             "margin < projected_exit_proceeds. Default 0.01.",
    )
    parser.add_argument(
        "--exit-depth-fraction",
        type=Decimal,
        default=Decimal("0.5"),
        help="Cap on the per-cycle exit sub-basket: fraction × min over legs of "
             "(bid depth within --exit-bid-depth-ticks of the touch). Sold uniformly "
             "across legs so the held remainder stays balanced. Mirrors "
             "--profitable-depth-fraction on entry. Default 0.5.",
    )
    parser.add_argument(
        "--exit-bid-depth-ticks",
        type=int,
        default=3,
        help="How many ticks below best bid to count as near-touch bid depth for the "
             "exit sell-size cap. Default 3.",
    )
    parser.add_argument(
        "--exit-repeg",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Re-peg resting maker exit limits to follow best_bid+tick when the bid "
             "drifts down (bounded by the margin floor), so orders fill before price "
             "runs away. Use --no-exit-repeg to post once and wait. Default on.",
    )
    parser.add_argument(
        "--exit-limit-timeout-seconds",
        type=float,
        default=30.0,
        help="Cancel a resting exit limit after this many seconds if it hasn't filled. "
             "Default 30.",
    )
    parser.add_argument(
        "--partial-exit-deadline-seconds",
        type=float,
        default=5.0,
        help="When an exit partially fills (some legs sold, some not), the basket is "
             "directionally exposed. If it stays partially unhedged longer than this, "
             "force completion by crossing the spread on the unsold legs (and, failing "
             "that, revert by buying back the sold legs and holding to settlement). "
             "Shorter than --exit-limit-timeout-seconds. Default 5.",
    )
    parser.add_argument(
        "--exit-monitor-hz",
        type=float,
        default=0.5,
        help="Exit monitor tick rate (Hz). Default 0.5 (one tick every 2 seconds).",
    )
    parser.add_argument(
        "--exit-min-leg-bid",
        type=Decimal,
        default=Decimal("0.02"),
        help="Path A skips if any leg's best bid is below this. Default 0.02.",
    )
    parser.add_argument(
        "--exit-max-leg-bid",
        type=Decimal,
        default=Decimal("0.98"),
        help="Path A skips if any leg's best bid is above this. Default 0.98.",
    )
    parser.add_argument(
        "--kalshi-tick-size",
        type=Decimal,
        default=Decimal("0.01"),
        help="Kalshi tick FALLBACK. The exit monitor normally infers the live tick "
             "from the observed book grid (smallest nonzero adjacent-level gap) so it "
             "follows the venue automatically. This default is used only when the book "
             "is too shallow to infer one. Default 0.01.",
    )
    parser.add_argument(
        "--polymarket-tick-size",
        type=Decimal,
        default=Decimal("0.01"),
        help="Polymarket US tick FALLBACK. See --kalshi-tick-size for semantics. "
             "Default 0.01.",
    )
    # Live PnL + position tracker (only when --enable-execution is on).
    parser.add_argument(
        "--pnl-interval-seconds",
        type=float,
        default=5.0,
        help="Snapshot held positions + PnL every N seconds. Surfaces in the TUI "
             "and as one record per tick in logs/pnl-<event>-<ts>.jsonl. Clamped "
             "to a 1s floor. Default 5.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    try:
        event = load_event(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    creds = load_credentials()
    endpoints = load_endpoints()
    store = BookStore()

    detector_state: DetectorState | None = None
    detector: Detector | None = None
    fee_cfg: FeeConfig | None = None
    if args.target_size is not None:
        if args.target_size <= 0:
            print("--target-size must be > 0", file=sys.stderr)
            return 2
        if args.detector_hz < 10:
            print("--detector-hz must be >= 10", file=sys.stderr)
            return 2
        fee_cfg = FeeConfig(
            kalshi_taker_theta=args.kalshi_theta,
            polymarket_us_taker_theta=args.polymarket_theta,
        )
        detector = Detector(
            event=event,
            target_size=args.target_size,
            fee_cfg=fee_cfg,
            entry_threshold=args.entry_threshold,
            slippage_buffer_per_share=args.slippage_buffer_per_share,
            depth_haircut=args.depth_haircut,
            momentum_window_seconds=args.momentum_window_ms / 1000.0,
            min_non_widening_ticks=args.non_widening_ticks,
            near_zero_threshold=args.near_zero_threshold,
            min_leg_bid=args.min_leg_bid,
            max_leg_bid=args.max_leg_bid,
        )
        detector_state = DetectorState()

    # Manual-abort signal: SIGUSR1 sets the event from any shell, the TUI 'a'
    # key sets it interactively. The executor consumes it on the next retry tick.
    abort_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGUSR1, abort_event.set)
    except (NotImplementedError, AttributeError):
        pass  # Windows / restricted env — keypress only.

    async with (
        jsonl_writer(args.log_dir, event.slug, "kalshi") as kalshi_log,
        jsonl_writer(args.log_dir, event.slug, "polymarket_us") as poly_log,
        jsonl_writer(args.log_dir, event.slug, "fires") as fires_log,
        jsonl_writer(args.log_dir, event.slug, "execution") as exec_log,
        jsonl_writer(args.log_dir, event.slug, "trades") as trades_log,
        jsonl_writer(args.log_dir, event.slug, "exits") as exits_log,
        jsonl_writer(args.log_dir, event.slug, "pnl") as pnl_log,
    ):
        executor: EntryExecutor | None = None
        position_store: PositionStore | None = None
        exit_monitor: ExitMonitor | None = None
        if args.enable_execution and detector is not None and fee_cfg is not None:
            sim_client = SimulatedOrderClient(
                store=store,
                fee_cfg=fee_cfg,
                initial_balance=args.initial_balance,
            )
            exec_cfg = ExecConfig(
                max_capital_per_trade=args.max_capital_per_trade,
                min_capital_per_trade=args.min_capital_per_trade,
                profitable_depth_fraction=args.profitable_depth_fraction,
                retry_seconds=args.retry_seconds,
                retry_poll_seconds=args.retry_poll_ms / 1000.0,
                max_unhedged_loss_pct=args.max_unhedged_loss_pct,
            )

            trade_journal = TradeJournal(trades_log)

            # PositionStore is needed whenever the executor runs — even without
            # the exit monitor — so the live PnL tracker has held positions to
            # mark-to-market. The exit monitor merely consumes the same store
            # when it's enabled.
            position_store = PositionStore()
            pnl_acc = RealizedPnLAccumulator()

            async def _on_attempt(attempt) -> None:
                try:
                    await exec_log.write_event(
                        "info",
                        basket_attempt_to_jsonl_payload(attempt),
                        kind="basket_attempt",
                    )
                except Exception:
                    pass
                # Comprehensive per-trade record (projected vs actual, timings, etc.).
                await trade_journal.write(attempt)
                if detector_state is not None:
                    await detector_state.record_attempt(attempt)
                # Realized PnL on every non-complete close (unwinds, aborts, etc.).
                await pnl_acc.on_basket_attempt(attempt)
                # Hand a completed basket to the position store for held tracking.
                if attempt.outcome == "complete":
                    basket = build_open_basket_from_attempt(
                        basket_id=f"{event.slug}-{attempt.ts.isoformat()}",
                        entered_ts=attempt.ts,
                        target_basket_size=attempt.target_basket_size,
                        legs=attempt.legs,
                    )
                    await position_store.add(basket)
                    if detector_state is not None:
                        await detector_state.set_open_positions(await position_store.size())

            executor = EntryExecutor(
                event=event,
                store=store,
                order_client=sim_client,
                fee_cfg=fee_cfg,
                exec_cfg=exec_cfg,
                entry_threshold=args.entry_threshold,
                slippage_buffer_per_share=args.slippage_buffer_per_share,
                depth_haircut=args.depth_haircut,
                on_attempt=_on_attempt,
                abort_event=abort_event,
            )

            if args.enable_exit_monitor:
                exit_journal = ExitJournal(exits_log)

                async def _on_exit_attempt(exit_attempt) -> None:
                    await exit_journal.write(exit_attempt)
                    if detector_state is not None and position_store is not None:
                        await detector_state.record_exit(
                            exit_attempt, await position_store.size()
                        )
                    # Realized PnL bookkeeping.
                    #   fill   → fully sold; entry cost basis is now realized.
                    #            dollars = realized_net_per_share × target
                    #   revert → some sells + buybacks; position still held with
                    #            the original cost basis. Only the round-trip
                    #            cash flow is realized (proceeds − buyback −
                    #            exit fees); the held position keeps its full
                    #            unrealized exposure.
                    kind = getattr(exit_attempt, "kind", None)
                    if kind not in ("fill", "reverted"):
                        return
                    baskets = await position_store.snapshot()
                    basket = next(
                        (b for b in baskets if b.basket_id == exit_attempt.basket_id),
                        None,
                    )
                    if basket is None or basket.target_basket_size <= 0:
                        return
                    target = basket.target_basket_size
                    if kind == "fill":
                        dollars = exit_attempt.realized_net_per_share * target
                    else:  # reverted: round-trip cash flow only
                        proceeds = exit_attempt.realized_proceeds_per_share * target
                        exit_fees = exit_attempt.realized_exit_fees_per_share * target
                        # buyback cost lives on the in-memory state, not the
                        # ExitAttempt; reconstruct it: round-trip net
                        # = realized_net_per_share + cost_basis + entry_fees +
                        #   exit_fees + buyback_per_share. Easier: just take
                        # `proceeds - exit_fees` for partially-closed flows
                        # where buyback offsets cost basis. For a clean revert
                        # back to original size, buyback ≈ proceeds, netting
                        # ≈ −exit_fees − spread. Use the recorded number to
                        # avoid duplicating the formula.
                        net_ps = exit_attempt.realized_net_per_share
                        # Strip the cost-basis component from net_ps so we only
                        # credit the round-trip portion. (cost_basis + entry_fees
                        # remain in unrealized on the held position.)
                        dollars = (
                            net_ps
                            + basket.cost_basis_per_share_total
                            + basket.entry_fees_per_share_total
                        ) * target
                    dedup_key = (
                        "exit", exit_attempt.basket_id,
                        exit_attempt.ts.isoformat() if exit_attempt.ts else "",
                    )
                    await pnl_acc.record_close(dollars, dedup_key)

                exit_cfg = ExitConfig(
                    coupling_tolerance=args.exit_coupling_tolerance,
                    bid_stability_window_ticks=args.exit_bid_stability_ticks,
                    bid_stability_threshold=args.exit_bid_stability_threshold,
                    required_margin_per_share=args.exit_required_margin_per_share,
                    depth_fraction=args.exit_depth_fraction,
                    bid_depth_ticks=args.exit_bid_depth_ticks,
                    repeg_enabled=args.exit_repeg,
                    limit_timeout_seconds=args.exit_limit_timeout_seconds,
                    partial_exit_deadline_seconds=args.partial_exit_deadline_seconds,
                    min_leg_bid=args.exit_min_leg_bid,
                    max_leg_bid=args.exit_max_leg_bid,
                    kalshi_tick_size=args.kalshi_tick_size,
                    polymarket_us_tick_size=args.polymarket_tick_size,
                    monitor_hz=args.exit_monitor_hz,
                )
                exit_monitor = ExitMonitor(
                    store=store,
                    order_client=sim_client,
                    position_store=position_store,
                    fee_cfg=fee_cfg,
                    cfg=exit_cfg,
                    on_exit_attempt=_on_exit_attempt,
                )

        tasks: list[asyncio.Task] = []
        if args.only in ("kalshi", "both"):
            stream = (
                run_kalshi_mock(event, store, kalshi_log)
                if args.mock
                else run_kalshi_stream(event, creds, endpoints, store, kalshi_log)
            )
            tasks.append(asyncio.create_task(stream, name="kalshi-stream"))
        if args.only in ("polymarket_us", "both"):
            stream = (
                run_polymarket_mock(event, store, poly_log)
                if args.mock
                else run_polymarket_stream(event, creds, endpoints, store, poly_log)
            )
            tasks.append(asyncio.create_task(stream, name="polymarket-stream"))

        if detector is not None and detector_state is not None:
            tasks.append(
                asyncio.create_task(
                    _run_detector_loop(
                        detector, store, detector_state, fires_log,
                        args.detector_hz, executor,
                    ),
                    name="detector",
                )
            )

        if exit_monitor is not None:
            tasks.append(asyncio.create_task(exit_monitor.run(), name="exit-monitor"))

        # Live PnL tracker — runs whenever execution is on (whether or not the
        # exit monitor is). Hands snapshots to the TUI via detector_state and
        # appends one record per tick to logs/pnl-*.jsonl.
        if (
            args.enable_execution and position_store is not None
            and args.pnl_interval_seconds > 0
        ):
            pnl_journal = PnLJournal(pnl_log)

            async def _on_pnl(snap) -> None:
                await pnl_journal.write(snap)
                if detector_state is not None:
                    await detector_state.set_pnl(snap)

            pnl_tracker = PnLTracker(
                store=store,
                position_store=position_store,
                accumulator=pnl_acc,
                interval_seconds=args.pnl_interval_seconds,
                on_snapshot=_on_pnl,
            )
            tasks.append(asyncio.create_task(pnl_tracker.run(), name="pnl-tracker"))

        # Manual-abort keypress listener (TUI mode only — needs a TTY).
        if not args.no_tui and args.frames is None:
            tasks.append(
                asyncio.create_task(
                    listen_for_abort_key(abort_event), name="abort-key-listener"
                )
            )

        if args.frames is not None:
            tasks.append(
                asyncio.create_task(
                    _render_frames(event, store, args.frames, args.refresh_hz, detector_state),
                    name="frame-renderer",
                )
            )
        elif not args.no_tui:
            tasks.append(
                asyncio.create_task(
                    run_tui(event, store, args.refresh_hz, detector_state),
                    name="tui",
                )
            )

        if not tasks:
            print("nothing to do: streams disabled and --no-tui passed", file=sys.stderr)
            return 1

        timeout_task: asyncio.Task | None = None
        if args.duration is not None:
            timeout_task = asyncio.create_task(asyncio.sleep(args.duration), name="duration-timer")
            tasks.append(timeout_task)

        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            # Propagate non-cancellation errors from whichever task finished first.
            for task in done:
                if task is timeout_task:
                    continue
                exc = task.exception()
                if exc and not isinstance(exc, asyncio.CancelledError):
                    raise exc
        except (KeyboardInterrupt, asyncio.CancelledError):
            for task in tasks:
                if not task.done():
                    task.cancel()
        finally:
            # Path B reconciliation: report any positions still held at exit.
            # These were never sold by path A and will ride to settlement —
            # they need manual reconciliation until live-venue settlement lands.
            if position_store is not None:
                await _print_open_positions_summary(position_store, store)
    return 0


async def _print_open_positions_summary(
    position_store: PositionStore, store: BookStore,
) -> None:
    baskets = await position_store.snapshot()
    if not baskets:
        return
    console = Console()
    console.rule("Open positions held at exit (path B — hold to settlement)")
    for b in baskets:
        # Current mark-to-market from best bids on the venue each leg sits on.
        mtm_ps = Decimal("0")
        for leg in b.legs:
            for venue, size in leg.fills_by_venue("buy").items():
                if size <= 0:
                    continue
                book = await store.get(venue, leg.outcome_name)
                if book is None or not book.yes_bids:
                    continue
                mtm_ps += (book.yes_bids[0].price * size) / b.target_basket_size
        cost_ps = b.cost_basis_per_share_total + b.entry_fees_per_share_total
        console.print(
            f"  {b.basket_id}: size={b.target_basket_size} "
            f"cost_basis=${cost_ps:.4f}/sh  current_bid_mtm=${mtm_ps:.4f}/sh  "
            f"(settles at $1.0000/sh)"
        )


async def _render_frames(
    event,
    store: BookStore,
    frames: int,
    refresh_hz: float,
    detector_state: DetectorState | None = None,
) -> None:
    """Print N static TUI frames to stdout (works in non-TTY contexts like logs/CI)."""
    import os
    width = int(os.environ.get("TRADE_SYSTEM_RENDER_WIDTH", "160"))
    console = Console(width=width, force_terminal=True)
    interval = 1.0 / max(refresh_hz, 0.5)
    for i in range(frames):
        await asyncio.sleep(interval)
        snapshot = await store.snapshot()
        det_view = None
        if detector_state is not None:
            async with detector_state._lock:
                det_view = (
                    detector_state.latest,
                    detector_state.last_fire,
                    detector_state.fire_count,
                    detector_state.tick_count,
                )
        console.rule(f"frame {i + 1}/{frames}")
        console.print(render(event, snapshot, detector_view=det_view, detector_state=detector_state))


async def _run_detector_loop(
    detector: Detector,
    store: BookStore,
    state: DetectorState,
    fires_log,
    hz: float,
    executor: EntryExecutor | None = None,
) -> None:
    """Run the detector at `hz` ticks/sec. Logs every fire to the fires JSONL.
    If `executor` is provided, dispatch each fire to it as a background task —
    the executor's own busy flag prevents overlapping entries."""
    interval = 1.0 / hz
    while True:
        books = await store.snapshot()
        ev, fire = detector.tick(books)
        await state.update(ev, fire)
        if executor is not None:
            await state.update_executor_busy(executor.busy)
        if fire is not None:
            try:
                await fires_log.write_event("info", fire_to_jsonl_payload(fire), kind="fire")
            except Exception:
                pass
            if executor is not None and not executor.busy:
                # Fire and forget: the executor guards itself with a busy lock,
                # so overlapping fires during execution are dropped.
                asyncio.create_task(executor.on_fire(fire))
        await asyncio.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # SIGUSR1's default disposition is to terminate the process. We use it as
    # the manual-abort trigger, but the asyncio handler isn't installed until
    # the event loop is running. Ignore the signal during the startup window so
    # an early `kill -USR1` (before there's anything to abort) can't kill us.
    try:
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    except (ValueError, AttributeError, OSError):
        pass  # not on main thread / not POSIX — fine.
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
