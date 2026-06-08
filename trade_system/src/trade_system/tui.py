from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .books import BookStore
from .models import BookSnapshot, EventSpec, Venue

if TYPE_CHECKING:
    from .detector import BasketEvaluation, FireEvent

STALE_SECONDS = 5.0

DetectorView = tuple["BasketEvaluation | None", "FireEvent | None", int, int]


def _fmt_px(p: Decimal | None) -> str:
    return f"{p:.3f}" if p is not None else "—"


def _fmt_sz(s: Decimal | None) -> str:
    return f"{s:,.0f}" if s is not None else "—"


def _fmt_age(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds/60:.1f}m"


def _venue_table(
    venue: Venue,
    title: str,
    event: EventSpec,
    snapshot: dict[tuple[Venue, str], BookSnapshot],
    now: datetime,
) -> Table:
    table = Table(title=title, expand=True, header_style="bold cyan")
    table.add_column("Outcome", overflow="fold")
    table.add_column("Bid", justify="right")
    table.add_column("BidSz", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("AskSz", justify="right")
    table.add_column("Last", justify="right")
    table.add_column("Age", justify="right")
    for outcome in event.outcomes:
        book = snapshot.get((venue, outcome.name))
        if book is None:
            table.add_row(outcome.name, "—", "—", "—", "—", "—", Text("no data", style="dim"))
            continue
        bid = book.best_yes_bid
        ask = book.best_yes_ask
        age = book.age_seconds(now)
        age_text = Text(_fmt_age(age), style="red" if age > STALE_SECONDS else "green")
        table.add_row(
            outcome.name,
            _fmt_px(bid.price if bid else None),
            _fmt_sz(bid.size if bid else None),
            _fmt_px(ask.price if ask else None),
            _fmt_sz(ask.size if ask else None),
            _fmt_px(book.last_trade_price),
            age_text,
        )
    return table


def _basket_footer(event: EventSpec, snapshot: dict[tuple[Venue, str], BookSnapshot]) -> Text:
    total = Decimal("0")
    any_missing = False
    for outcome in event.outcomes:
        kalshi = snapshot.get(("kalshi", outcome.name))
        poly = snapshot.get(("polymarket_us", outcome.name))
        candidates: list[Decimal] = []
        if kalshi and kalshi.best_yes_ask:
            candidates.append(kalshi.best_yes_ask.price)
        if poly and poly.best_yes_ask:
            candidates.append(poly.best_yes_ask.price)
        if not candidates:
            any_missing = True
            continue
        total += min(candidates)
    if any_missing and total == 0:
        return Text("Top-of-book basket: — (waiting for data)", style="dim")
    label = "Top-of-book basket (cheapest YES ask per outcome, pre-fee): "
    style = "bold green" if total > 0 and total < Decimal("1") else "bold"
    marker = "  ←  below $1!" if total > 0 and total < Decimal("1") else ""
    suffix = " (partial)" if any_missing else ""
    return Text(f"{label}${total:.4f}{suffix}{marker}", style=style)


def _detector_footer(view: DetectorView | None) -> Text | None:
    if view is None:
        return None
    ev, last_fire, fire_count, tick_count = view
    if ev is None:
        return Text(f"Detector: warming up  (ticks={tick_count})", style="dim")

    cost = ev.basket_cost_per_share
    fees = ev.total_fees_per_share
    entry = ev.entry_cost_per_share
    edge = ev.edge_per_share
    thresh = ev.entry_threshold
    achievable = ev.achievable_size
    target = ev.target_size

    edge_style = "bold green" if edge > 0 else ("yellow" if edge > Decimal("-0.01") else "red")
    edge_marker = "  ←  ARB"  if edge > 0 else ""
    flags = []
    if ev.any_empty:
        flags.append("[empty]")
    if ev.any_stale:
        flags.append(f"[stale {ev.max_book_age_ms:.0f}ms]")
    if ev.any_extreme_price:
        flags.append("[extreme-bid]")
    if achievable < target:
        flags.append(f"[depth-capped {achievable}/{target}]")
    if ev.any_depth_walked:
        flags.append(f"[depth-walked slip≤{ev.max_slippage_per_share:.4f}]")
    flags_text = (" " + " ".join(flags)) if flags else ""

    buf = ev.slippage_buffer_per_share
    hcut = ev.depth_haircut
    line_parts = [
        f"Depth-walked basket @ size={target} (hcut={hcut:.2f}): "
        f"cost=${cost:.4f}  fees=${fees:.4f}  buf=${buf:.4f}  entry=${entry:.4f}  "
        f"edge_vs_${thresh:.2f}=${edge:+.4f}{edge_marker}{flags_text}"
    ]
    if last_fire is not None:
        lf = last_fire.evaluation
        age = (datetime.now(timezone.utc) - lf.ts).total_seconds()
        line_parts.append(
            f"\nLast FIRE {age:.1f}s ago — edge=${lf.edge_per_share:+.4f} "
            f"size={lf.achievable_size} velocity={last_fire.velocity_per_share_per_sec:+.5f}/s "
            f"(fires this run: {fire_count}, ticks: {tick_count})"
        )
    else:
        line_parts.append(f"\nNo fires yet  (ticks={tick_count}, fires={fire_count})")
    return Text("".join(line_parts), style=edge_style)


def _execution_footer(state) -> Text | None:
    """Footer line summarizing the executor's state and last attempt."""
    if state is None or getattr(state, "attempt_count", 0) == 0 and not getattr(state, "executor_busy", False):
        return None
    busy_text = "BUSY" if getattr(state, "executor_busy", False) else "idle"
    aborted = getattr(state, "aborted_count", 0)
    user_aborted = getattr(state, "user_aborted_count", 0)
    aborted_text = f"aborted={aborted}"
    if user_aborted:
        aborted_text += f" (user={user_aborted})"
    parts = [
        f"Executor: {busy_text}  "
        f"attempts={getattr(state, 'attempt_count', 0)}  "
        f"complete={getattr(state, 'completed_count', 0)}  "
        f"unwound={getattr(state, 'unwound_count', 0)}  "
        f"{aborted_text}  "
        f"[abort: press 'a' or kill -USR1]"
    ]
    open_pos = getattr(state, "open_positions", 0)
    exit_fills = getattr(state, "exit_fills", 0)
    if open_pos or exit_fills:
        parts.append(
            f"\nExit monitor: open_positions={open_pos}  exit_fills={exit_fills}"
        )
        last_exit = getattr(state, "last_exit", None)
        if last_exit is not None:
            kind = getattr(last_exit, "kind", "?")
            blocked = getattr(last_exit, "blocked_by", None)
            blocked_part = f" blocked_by={blocked}" if blocked else ""
            net = getattr(last_exit, "projected_net_per_share", None)
            net_part = f" proj_net=${net:+.4f}" if net is not None and kind != "fill" else ""
            if kind == "fill":
                rnet = getattr(last_exit, "realized_net_per_share", None)
                net_part = f" realized_net=${rnet:+.4f}" if rnet is not None else ""
            parts.append(f"  last_exit={kind}{blocked_part}{net_part}")
    last = getattr(state, "last_attempt", None)
    if last is not None:
        ts = getattr(last, "ts", None)
        age = (datetime.now(timezone.utc) - ts).total_seconds() if ts else 0
        size = getattr(last, "target_basket_size", "?")
        outcome = getattr(last, "outcome", "?")
        note = getattr(last, "note", None)
        rounds = getattr(last, "submission_rounds", 0)
        unwind_n = getattr(last, "unwind_orders_sent", 0)
        note_part = f" ({note})" if note else ""

        # Realized slippage and total attempt latency, if the rich record is populated.
        realized_slip = Decimal("0")
        attempt_ms = None
        rounds_list = getattr(last, "rounds", ())
        for r in rounds_list:
            for o in getattr(r, "orders", ()):
                if getattr(o, "filled_size", Decimal("0")) > Decimal("0"):
                    realized_slip += o.filled_size * o.slippage_per_share
        started = getattr(last, "entry_started_ts", None)
        completed = getattr(last, "entry_complete_ts", None)
        if started and completed:
            attempt_ms = (completed - started).total_seconds() * 1000.0
        latency_part = f" duration={attempt_ms:.0f}ms" if attempt_ms is not None else ""
        slip_part = f" realized_slip=${realized_slip:+.4f}" if rounds_list else ""

        parts.append(
            f"\nLast attempt {age:.1f}s ago: outcome={outcome} size={size} "
            f"rounds={rounds} unwind_orders={unwind_n}{latency_part}{slip_part}{note_part}"
        )
    style = "magenta" if getattr(state, "executor_busy", False) else "white"
    return Text("".join(parts), style=style)


def _pnl_panel(state):
    """Rich panel showing held positions + cumulative PnL. Reads
    `detector_state.latest_pnl` (a PnLSnapshot). Returns None when no
    snapshot has been computed yet (e.g. PnL tracker not running)."""
    snap = getattr(state, "latest_pnl", None) if state is not None else None
    if snap is None:
        return None

    realized = snap.realized_pnl_dollars
    unreal = snap.total_unrealized_pnl
    net = realized + unreal
    header_style = "bold green" if net >= 0 else "bold red"
    header = Text(
        f"open={snap.open_count}  realized=${realized:+.4f} (n={snap.realized_count})  "
        f"unrealized=${unreal:+.4f}  net=${net:+.4f}",
        style=header_style,
    )

    table = Table(expand=True, header_style="bold cyan", show_lines=False)
    table.add_column("basket_id", overflow="fold")
    table.add_column("size", justify="right")
    table.add_column("cost", justify="right")
    table.add_column("mtm", justify="right")
    table.add_column("unreal", justify="right")
    table.add_column("age", justify="right")
    now = datetime.now(timezone.utc)
    for b in snap.open_baskets:
        age = (now - b.entered_ts).total_seconds()
        unreal_b = b.unrealized_pnl_dollars
        row_style = "green" if unreal_b >= 0 else "red"
        table.add_row(
            b.basket_id,
            f"{b.target_basket_size:.0f}",
            f"${b.cost_basis_dollars:.2f}",
            f"${b.mark_to_market_dollars:.2f}",
            Text(f"${unreal_b:+.2f}", style=row_style),
            _fmt_age(age),
        )

    body = Group(header, table) if snap.open_baskets else header
    return Panel(body, title="Positions & PnL", border_style="bright_magenta")


def render(
    event: EventSpec,
    snapshot: dict[tuple[Venue, str], BookSnapshot],
    *,
    detector_view: DetectorView | None = None,
    detector_state=None,
) -> Panel:
    now = datetime.now(timezone.utc)
    layout = Layout()
    layout.split_row(
        Layout(_venue_table("kalshi", "KALSHI", event, snapshot, now), name="left"),
        Layout(_venue_table("polymarket_us", "POLYMARKET US", event, snapshot, now), name="right"),
    )
    children: list = [layout, _basket_footer(event, snapshot)]
    det = _detector_footer(detector_view)
    if det is not None:
        children.append(det)
    execf = _execution_footer(detector_state)
    if execf is not None:
        children.append(execf)
    pnlp = _pnl_panel(detector_state)
    if pnlp is not None:
        children.append(pnlp)
    body = Group(*children)
    title = event.name
    if event.description:
        title = f"{event.name}  —  {event.description}"
    return Panel(body, title=title, border_style="bright_blue")


async def run_tui(
    event: EventSpec,
    store: BookStore,
    refresh_hz: float = 4.0,
    detector_state=None,
) -> None:
    interval = 1.0 / max(refresh_hz, 0.5)
    snapshot: dict[tuple[Venue, str], BookSnapshot] = {}
    with Live(render(event, snapshot), refresh_per_second=refresh_hz, screen=False) as live:
        while True:
            snapshot = await store.snapshot()
            det_view: DetectorView | None = None
            if detector_state is not None:
                async with detector_state._lock:
                    det_view = (
                        detector_state.latest,
                        detector_state.last_fire,
                        detector_state.fire_count,
                        detector_state.tick_count,
                    )
            live.update(render(event, snapshot, detector_view=det_view, detector_state=detector_state))
            await asyncio.sleep(interval)
