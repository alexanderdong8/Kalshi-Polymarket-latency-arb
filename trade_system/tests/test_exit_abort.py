"""Verification for manual abort + exit logic.

Unit tests:
  1. LegBidTracker.is_stable
  2. Exit profitability formula (via ExitMonitor._evaluate_basket end-to-end)
  3. Coupling filter
  4. Abort flow → outcome aborted_by_user + unwind runs
End-to-end (mock-ish):
  5. Full exit cycle: complete entry → coupling tightens → limits posted → filled
"""
import asyncio
import sys
from datetime import datetime, timezone
from decimal import Decimal

import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trade_system.books import BookStore
from trade_system.detector import Detector, FireEvent
from trade_system.execution import (
    EntryExecutor, ExecConfig, ExitConfig, ExitMonitor, LegBidTracker,
    PositionStore, SimulatedOrderClient, build_open_basket_from_attempt,
)
from trade_system.execution.models import Fill, LegState
from trade_system.fees import FeeConfig
from trade_system.models import BookSnapshot, DepthLevel, EventSpec, OutcomeSpec

EVENT = EventSpec(name="x", description=None,
    outcomes=(OutcomeSpec("A", "K-A", "p-a"), OutcomeSpec("B", "K-B", "p-b")))


def mkbook(venue, outcome, key, bids, asks):
    return BookSnapshot(venue=venue, outcome_name=outcome, market_key=key,
        yes_bids=tuple(DepthLevel(p, s) for p, s in bids),
        yes_asks=tuple(DepthLevel(p, s) for p, s in asks),
        received_ts=datetime.now(timezone.utc))


PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}")


# ---------------------------------------------------------------- Test 1
def test_legbidtracker():
    print("=== Test 1: LegBidTracker.is_stable ===")
    t = LegBidTracker(venue="kalshi", outcome_name="A")
    t.configure_window(3)
    for b in [Decimal("0.40"), Decimal("0.401"), Decimal("0.4005"), Decimal("0.40")]:
        t.push(b)
    check("small drift within 0.005 over window 3 → stable",
          t.is_stable(Decimal("0.005"), 3) is True)

    t2 = LegBidTracker(venue="kalshi", outcome_name="A")
    t2.configure_window(3)
    for b in [Decimal("0.40"), Decimal("0.41"), Decimal("0.40"), Decimal("0.40")]:
        t2.push(b)
    check("a 0.01 jump (> 0.005) → unstable",
          t2.is_stable(Decimal("0.005"), 3) is False)

    t3 = LegBidTracker(venue="kalshi", outcome_name="A")
    t3.configure_window(3)
    t3.push(Decimal("0.40"))
    t3.push(Decimal("0.40"))
    check("insufficient history → unstable (False)",
          t3.is_stable(Decimal("0.005"), 3) is False)


# A client that fills BUY orders for leg "A" fully (at limit) but never fills
# leg "B" buys — so the basket can never complete and the retry loop runs,
# giving the pre-set abort_event a chance to fire. Sells (unwind) fill fully.
from trade_system.execution.models import Order, OrderResult


class PartialFillClient:
    def __init__(self, balance=Decimal("1000")):
        self._b = balance

    async def get_balance(self, venue):
        return self._b

    async def get_total_balance(self):
        return self._b * 2

    async def submit_ioc(self, order: Order) -> OrderResult:
        # Buys: fill leg A fully, leg B not at all. Sells (unwind): fill fully.
        if order.side == "sell" or order.outcome_name == "A":
            fees = Decimal("0.10")
            return OrderResult(order=order, filled_size=order.size,
                fill_vwap=order.limit_price, fees_paid=fees, accepted=True)
        return OrderResult(order=order, filled_size=Decimal("0"), fill_vwap=Decimal("0"),
            fees_paid=Decimal("0"), accepted=True, reject_reason="test: leg B no-fill")

    async def submit_limit_postonly(self, order): ...
    async def poll_resting_orders(self): return []
    async def cancel_limit(self, order_id): ...


# ---------------------------------------------------------------- Test 4
async def test_abort_flow():
    print("=== Test 4: manual abort flow ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    # Healthy books at fire/size time so sizing passes; the PartialFillClient is
    # what prevents completion (leg B never fills), forcing the retry loop.
    await store.set(mkbook("kalshi", "A", "K-A", [(Decimal("0.39"), Decimal("500"))],
        [(Decimal("0.40"), Decimal("500"))]))
    await store.set(mkbook("polymarket_us", "A", "p-a", [(Decimal("0.39"), Decimal("500"))],
        [(Decimal("0.41"), Decimal("500"))]))
    await store.set(mkbook("kalshi", "B", "K-B", [(Decimal("0.49"), Decimal("500"))],
        [(Decimal("0.50"), Decimal("500"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b", [(Decimal("0.49"), Decimal("500"))],
        [(Decimal("0.50"), Decimal("500"))]))

    detector = Detector(event=EVENT, target_size=Decimal("100"), fee_cfg=fee_cfg,
        entry_threshold=Decimal("0.98"), slippage_buffer_per_share=Decimal("0.005"),
        depth_haircut=Decimal("1.0"))
    ev = detector.evaluate(await store.snapshot())
    fire = FireEvent(ts=ev.ts, evaluation=ev,
        velocity_per_share_per_sec=Decimal("0"), consecutive_non_widening_ticks=2)

    abort_event = asyncio.Event()
    abort_event.set()  # pre-set → first retry iteration aborts

    client = PartialFillClient(balance=Decimal("1000"))
    exec_cfg = ExecConfig(max_capital_per_trade=Decimal("50"), min_capital_per_trade=Decimal("1"),
        profitable_depth_fraction=Decimal("0.5"), retry_seconds=2.0, retry_poll_seconds=0.05,
        max_unhedged_loss_pct=Decimal("0.99"))
    ex = EntryExecutor(event=EVENT, store=store, order_client=client, fee_cfg=fee_cfg,
        exec_cfg=exec_cfg, entry_threshold=Decimal("0.98"),
        slippage_buffer_per_share=Decimal("0.005"), depth_haircut=Decimal("1.0"),
        abort_event=abort_event)
    await ex.on_fire(fire)
    a = ex.last_attempt
    print(f"  outcome={a.outcome} note={a.note} unwind_orders={a.unwind_orders_sent}")
    check("outcome is aborted_by_user", a.outcome == "aborted_by_user")
    check("note mentions manual abort", "manual abort" in (a.note or "").lower())
    check("abort_event cleared after consume", not abort_event.is_set())
    check("unwind sold the filled leg A portion", a.unwind_orders_sent >= 1)


# ---------------------------------------------------------------- helpers for exit tests
def make_open_basket(store_size=Decimal("100"), buy_price=Decimal("0.45")):
    """Build an OpenBasket: 2 legs, each bought `store_size` contracts at buy_price.
    Leg A on kalshi, Leg B on polymarket_us. cost basis = 0.45+0.45 = 0.90/share."""
    now = datetime.now(timezone.utc)
    legA = LegState(outcome_name="A", target_size=store_size)
    legA.fills.append(Fill(venue="kalshi", side="buy", size=store_size,
        price=buy_price, fees=Decimal("0"), ts=now))
    legB = LegState(outcome_name="B", target_size=store_size)
    legB.fills.append(Fill(venue="polymarket_us", side="buy", size=store_size,
        price=buy_price, fees=Decimal("0"), ts=now))
    return build_open_basket_from_attempt(
        basket_id="test-basket", entered_ts=now,
        target_basket_size=store_size, legs=(legA, legB))


# ---------------------------------------------------------------- Test 3
async def test_coupling_filter():
    print("=== Test 3: coupling filter ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    # Coupling now sums LIMIT prices (best_bid + tick), not raw bids.
    # bids 0.48 / 0.485 + tick 0.01 → limit sum = 0.49 + 0.495 = 0.985.
    # Below $0.99 → blocked at tol 0.01.
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.48"), Decimal("500"))], [(Decimal("0.60"), Decimal("500"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.485"), Decimal("500"))], [(Decimal("0.60"), Decimal("500"))]))

    ps = PositionStore()
    await ps.add(make_open_basket())

    captured = []
    async def cap(a): captured.append(a)

    cfg = ExitConfig(coupling_tolerance=Decimal("0.01"), bid_stability_window_ticks=1,
        bid_stability_threshold=Decimal("1"), required_margin_per_share=Decimal("0.005"))
    mon = ExitMonitor(store=store, order_client=SimulatedOrderClient(store=store, fee_cfg=fee_cfg),
        position_store=ps, fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)
    # Push twice so stability has history (window 1 needs 2 samples).
    await mon._tick()
    await mon._tick()
    last = captured[-1]
    print(f"  bidsum={last.coupling_basket_bid_sum} blocked_by={last.blocked_by}")
    check("0.985 sum blocked by coupling (tol 0.01)", last.blocked_by == "coupling_below_tolerance")

    # Raise tolerance to 0.02 → 0.985 >= 0.98 passes coupling. (Stability window=1.)
    cfg2 = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=1,
        bid_stability_threshold=Decimal("1"), required_margin_per_share=Decimal("0.005"))
    captured2 = []
    async def cap2(a): captured2.append(a)
    mon2 = ExitMonitor(store=store, order_client=SimulatedOrderClient(store=store, fee_cfg=fee_cfg),
        position_store=ps, fee_cfg=fee_cfg, cfg=cfg2, on_exit_attempt=cap2)
    await mon2._tick()
    await mon2._tick()
    last2 = captured2[-1]
    print(f"  at tol 0.02: blocked_by={last2.blocked_by}")
    check("0.985 passes coupling at tol 0.02 (not blocked by coupling)",
          last2.blocked_by != "coupling_below_tolerance")


# ---------------------------------------------------------------- Test 2
async def test_profitability():
    print("=== Test 2: exit profitability ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    ps = PositionStore()
    # Cost basis 0.90/share (0.45 each leg), entry fees 0. Use a tick of 0.01.
    # Make bids high enough to couple and to clear margin.
    # Want limit prices to sum/share so net > margin. Use 0-fee approximation by
    # tiny sizes? No — use real fees. Pick bids such that limit = bid+0.01 and
    # ample spread to ask. A bid 0.495, B bid 0.495 → sum 0.99 (couples).
    # limit A=0.505, B=0.505 → proceeds/sh = (0.505*100 + 0.505*100)/100 = 1.01.
    # exit fees small. cost 0.90 + 0 + fees + 0.005 < 1.01 → should PASS.
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.495"), Decimal("500"))], [(Decimal("0.70"), Decimal("500"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.495"), Decimal("500"))], [(Decimal("0.70"), Decimal("500"))]))
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=1,
        bid_stability_threshold=Decimal("1"), required_margin_per_share=Decimal("0.005"))
    mon = ExitMonitor(store=store, order_client=SimulatedOrderClient(store=store, fee_cfg=fee_cfg),
        position_store=ps, fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)
    await mon._tick(); await mon._tick()
    posted = [c for c in captured if c.kind == "posted"]
    print(f"  posted={len(posted)}  last_kind={captured[-1].kind} blocked={captured[-1].blocked_by}")
    if posted:
        p = posted[0]
        print(f"  proceeds/sh={p.projected_proceeds_per_share} net/sh={p.projected_net_per_share}")
    check("profitable basket posts limits", len(posted) >= 1)

    # Now make it unprofitable: cost basis 0.99/share (buy 0.495 each).
    store2 = BookStore()
    await store2.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.495"), Decimal("500"))], [(Decimal("0.70"), Decimal("500"))]))
    await store2.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.495"), Decimal("500"))], [(Decimal("0.70"), Decimal("500"))]))
    ps2 = PositionStore()
    await ps2.add(make_open_basket(buy_price=Decimal("0.495")))  # cost 0.99/sh
    captured2 = []
    async def cap2(a): captured2.append(a)
    mon2 = ExitMonitor(store=store2, order_client=SimulatedOrderClient(store=store2, fee_cfg=fee_cfg),
        position_store=ps2, fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap2)
    await mon2._tick(); await mon2._tick()
    print(f"  high-cost-basket last_kind={captured2[-1].kind} blocked={captured2[-1].blocked_by}")
    # proceeds 1.01, cost 0.99 + exit_fees + 0.005 margin. exit fees ~ 0.025/sh
    # → 0.99 + 0.025 + 0.005 = 1.02 > 1.01 → unprofitable.
    check("high cost basis blocked by unprofitable",
          captured2[-1].blocked_by == "unprofitable")


# ---------------------------------------------------------------- Test 5
async def test_full_exit_cycle():
    print("=== Test 5: full exit cycle (post → fill) ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    # Coupled, stable, profitable. Sizes large so limits fully fill.
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))  # cost 0.90/sh
    sim = SimulatedOrderClient(store=store, fee_cfg=fee_cfg, initial_balance=Decimal("0"))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=2,
        bid_stability_threshold=Decimal("0.005"), required_margin_per_share=Decimal("0.005"),
        limit_timeout_seconds=30.0)
    mon = ExitMonitor(store=store, order_client=sim, position_store=ps,
        fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)

    # Tick a few times: build stability history, post limits.
    for _ in range(4):
        await mon._tick()
    posted = [c for c in captured if c.kind == "posted"]
    check("limits posted after stability accrues", len(posted) >= 1)

    # Now move best bid UP to cross our resting sell limit (limit = 0.50+0.01=0.51).
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.52"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.52"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    # Poll → fills.
    await mon._tick()
    fills = [c for c in captured if c.kind == "fill"]
    print(f"  posted={len(posted)} fills={len(fills)} open_now={await ps.size()}")
    check("exit filled and basket removed", len(fills) >= 1 and await ps.size() == 0)
    if fills:
        f = fills[-1]
        print(f"  realized_net/sh={f.realized_net_per_share} all_filled={f.all_legs_filled}")
        check("realized net positive (~0.51-0.90.. wait proceeds 0.51*2=1.02 - 0.90 - fees)",
              f.realized_net_per_share > Decimal("0"))


# ---------------------------------------------------------------- Test 6
async def test_partial_escalation():
    print("=== Test 6: partial fill → escalate to crossing → flat ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))  # cost 0.90/sh
    sim = SimulatedOrderClient(store=store, fee_cfg=fee_cfg, initial_balance=Decimal("0"))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=2,
        bid_stability_threshold=Decimal("0.005"), required_margin_per_share=Decimal("0.005"),
        limit_timeout_seconds=30.0, partial_exit_deadline_seconds=0.0)  # escalate next tick
    mon = ExitMonitor(store=store, order_client=sim, position_store=ps,
        fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)

    for _ in range(4):
        await mon._tick()
    check("limits posted (test6)", any(c.kind == "posted" for c in captured))

    # Cross ONLY leg A's resting sell limit (0.50+0.01=0.51) by lifting its bid;
    # leg B's bid stays at 0.50 (< its 0.51 limit) so B does not passively fill.
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.52"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await mon._tick()  # poll fills leg A → partial; partial_since set
    await mon._tick()  # partial deadline (0s) elapsed → escalate sells leg B by crossing
    escalated = [c for c in captured if c.kind == "escalated"]
    print(f"  escalated={len(escalated)} open_now={await ps.size()}")
    check("escalation occurred", len(escalated) >= 1)
    check("position fully flat (basket removed)", await ps.size() == 0)


# ---------------------------------------------------------------- Test 7
async def test_revert_when_unsellable():
    print("=== Test 7: partial, a leg has no bid → revert (buy back) → hold ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))
    sim = SimulatedOrderClient(store=store, fee_cfg=fee_cfg, initial_balance=Decimal("100"))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=2,
        bid_stability_threshold=Decimal("0.005"), required_margin_per_share=Decimal("0.005"),
        limit_timeout_seconds=30.0, partial_exit_deadline_seconds=0.0)
    mon = ExitMonitor(store=store, order_client=sim, position_store=ps,
        fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)

    for _ in range(4):
        await mon._tick()
    check("limits posted (test7)", any(c.kind == "posted" for c in captured))

    # Fill leg A, then WIPE leg B's bids (no bid → can't sell even by crossing).
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.52"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [], [(Decimal("0.70"), Decimal("1000"))]))  # no bids on B
    await mon._tick()  # leg A fills → partial
    await mon._tick()  # escalate: B has no bid → revert buys back A

    reverted = [c for c in captured if c.kind == "reverted"]
    print(f"  reverted={len(reverted)} open_now={await ps.size()}")
    check("revert occurred", len(reverted) >= 1)
    check("basket held (not removed) after revert", await ps.size() == 1)
    n_before = len(captured)
    await mon._tick(); await mon._tick()
    new_kinds = [c.kind for c in captured[n_before:]]
    print(f"  post-revert emissions: {new_kinds}")
    check("no further exit activity after revert (held)", len(new_kinds) == 0)


# ---------------------------------------------------------------- Test 8
async def test_depth_cap_sizes_subbasket():
    print("=== Test 8: depth cap sizes a uniform sub-basket ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    # Leg A near-touch bid depth = 40, leg B = 1000. cap = floor(0.5 × 40) = 20.
    # Held = 100/leg → Q = min(100, 20) = 20. Posted size per leg should be 20.
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("40"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))  # cost 0.90/sh
    sim = SimulatedOrderClient(store=store, fee_cfg=fee_cfg, initial_balance=Decimal("0"))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=2,
        bid_stability_threshold=Decimal("0.005"), required_margin_per_share=Decimal("0.01"),
        depth_fraction=Decimal("0.5"), bid_depth_ticks=3)
    mon = ExitMonitor(store=store, order_client=sim, position_store=ps,
        fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)
    for _ in range(4):
        await mon._tick()
    posted = [c for c in captured if c.kind == "posted"]
    check("posted a sub-basket", len(posted) >= 1)
    if posted:
        sizes = [e.size for e in posted[0].per_leg_limits]
        print(f"  per-leg posted sizes: {sizes}")
        check("each leg posted Q=20 (capped, not full 100)", all(s == Decimal("20") for s in sizes))


# ---------------------------------------------------------------- Test 9
async def test_repeg_follows_touch():
    print("=== Test 9: re-peg follows the touch down (margin-bounded) ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))  # cost 0.90/sh
    sim = SimulatedOrderClient(store=store, fee_cfg=fee_cfg, initial_balance=Decimal("0"))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=2,
        bid_stability_threshold=Decimal("0.01"), required_margin_per_share=Decimal("0.01"),
        depth_fraction=Decimal("0.5"), bid_depth_ticks=3, repeg_enabled=True)
    mon = ExitMonitor(store=store, order_client=sim, position_store=ps,
        fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)
    for _ in range(4):
        await mon._tick()
    posted = [c for c in captured if c.kind == "posted"]
    check("initial post at best_bid+tick=0.51", posted and
          all(e.limit_price == Decimal("0.51") for e in posted[0].per_leg_limits))

    # Bid drifts DOWN one tick (0.50 → 0.49); the resting 0.51 sell is now stranded.
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.49"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.49"), Decimal("1000"))], [(Decimal("0.70"), Decimal("1000"))]))
    await mon._tick()
    reposted = [c for c in captured if c.kind == "reposted"]
    print(f"  reposted={len(reposted)}")
    check("re-pegged after bid dropped", len(reposted) >= 1)
    if reposted:
        prices = [e.limit_price for e in reposted[-1].per_leg_limits]
        print(f"  reposted prices: {prices}")
        check("reposted at new touch 0.50", all(p == Decimal("0.50") for p in prices))


# ---------------------------------------------------------------- Test 10
async def test_thin_depth_blocks():
    print("=== Test 10: bid depth too thin → blocked, nothing posted ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("1"))], [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.50"), Decimal("1"))], [(Decimal("0.70"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))
    sim = SimulatedOrderClient(store=store, fee_cfg=fee_cfg, initial_balance=Decimal("0"))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=2,
        bid_stability_threshold=Decimal("0.005"), required_margin_per_share=Decimal("0.01"),
        depth_fraction=Decimal("0.5"), bid_depth_ticks=3)
    mon = ExitMonitor(store=store, order_client=sim, position_store=ps,
        fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)
    for _ in range(4):
        await mon._tick()
    print(f"  last_kind={captured[-1].kind} blocked_by={captured[-1].blocked_by}")
    check("blocked by thin bid depth", captured[-1].blocked_by == "bid_depth_too_thin")
    check("nothing posted", not any(c.kind in ("posted", "reposted") for c in captured))


# ---------------------------------------------------------------- Test 11
def test_observed_tick():
    from trade_system.execution.exit_monitor import _observed_tick
    print("=== Test 11: _observed_tick infers grid from book, falls back if shallow ===")
    fb = Decimal("0.01")
    # Multi-level book with half-cent gaps.
    book = mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("100")), (Decimal("0.495"), Decimal("100")),
         (Decimal("0.49"), Decimal("100"))],
        [(Decimal("0.51"), Decimal("100"))])
    check("half-cent gap inferred", _observed_tick(book, fb) == Decimal("0.005"))
    # One level only → fallback.
    book2 = mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("100"))],
        [(Decimal("0.51"), Decimal("100"))])
    check("one-sided shallow book → fallback", _observed_tick(book2, fb) == fb)


# ---------------------------------------------------------------- Test 12
async def test_half_cent_exit_repeg():
    print("=== Test 12: half-cent observed tick → exit posts at best_bid + 0.005 ===")
    store = BookStore()
    fee_cfg = FeeConfig()
    # Multi-level grid reveals a 0.005 tick. Bids on leg A: 0.50/0.495/0.49.
    # Limit posts at 0.505 (not 0.51).
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("1000")), (Decimal("0.495"), Decimal("500")),
         (Decimal("0.49"), Decimal("500"))],
        [(Decimal("0.70"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.50"), Decimal("1000")), (Decimal("0.495"), Decimal("500")),
         (Decimal("0.49"), Decimal("500"))],
        [(Decimal("0.70"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))
    sim = SimulatedOrderClient(store=store, fee_cfg=fee_cfg, initial_balance=Decimal("0"))

    captured = []
    async def cap(a): captured.append(a)
    cfg = ExitConfig(coupling_tolerance=Decimal("0.02"), bid_stability_window_ticks=2,
        bid_stability_threshold=Decimal("0.01"), required_margin_per_share=Decimal("0.01"),
        depth_fraction=Decimal("0.5"), bid_depth_ticks=3)
    mon = ExitMonitor(store=store, order_client=sim, position_store=ps,
        fee_cfg=fee_cfg, cfg=cfg, on_exit_attempt=cap)
    for _ in range(4):
        await mon._tick()
    posted = [c for c in captured if c.kind == "posted"]
    check("posted with half-cent observed tick", len(posted) >= 1)
    if posted:
        prices = [e.limit_price for e in posted[0].per_leg_limits]
        print(f"  posted limit prices: {prices}")
        check("limit at best_bid + 0.005, not + 0.01",
              all(p == Decimal("0.505") for p in prices))


# ---------------------------------------------------------------- Test 13
async def test_pnl_snapshot_math():
    print("=== Test 13: PnLTracker snapshot computes cost_basis, MTM, unrealized ===")
    from trade_system.pnl import PnLTracker, RealizedPnLAccumulator
    store = BookStore()
    fee_cfg = FeeConfig()
    # Held basket: 100 contracts/leg @ 0.45 buy price → cost basis $0.90/sh × 100 = $90.
    await store.set(mkbook("kalshi", "A", "K-A",
        [(Decimal("0.50"), Decimal("1000"))], [(Decimal("0.60"), Decimal("1000"))]))
    await store.set(mkbook("polymarket_us", "B", "p-b",
        [(Decimal("0.48"), Decimal("1000"))], [(Decimal("0.60"), Decimal("1000"))]))
    ps = PositionStore()
    await ps.add(make_open_basket(buy_price=Decimal("0.45")))
    acc = RealizedPnLAccumulator()
    tracker = PnLTracker(store=store, position_store=ps, accumulator=acc,
        interval_seconds=1.0)
    snap = await tracker.compute_snapshot()
    print(f"  open={snap.open_count}  cost=${snap.total_cost_basis}  "
          f"mtm=${snap.total_mark_to_market}  unreal=${snap.total_unrealized_pnl}")
    # cost_basis = (0.45+0.45) × 100 = $90 (no entry fees in this test fixture).
    # mtm = (0.50×100) + (0.48×100) = $98.
    # unreal = $98 − $90 = $8.
    check("one open basket", snap.open_count == 1)
    check("cost basis = $90", snap.total_cost_basis == Decimal("90"))
    check("mtm = $98", snap.total_mark_to_market == Decimal("98"))
    check("unrealized = $8", snap.total_unrealized_pnl == Decimal("8"))


# ---------------------------------------------------------------- Test 14
async def test_realized_pnl_accumulator():
    print("=== Test 14: RealizedPnLAccumulator credits only on close, dedups ===")
    from trade_system.pnl import RealizedPnLAccumulator

    # Build a fake BasketAttempt with outcome=unwound_timeout, sells & buys.
    class FakeAttempt:
        outcome = "unwound_timeout"
        ts = datetime.now(timezone.utc)
        legs = (
            LegState(outcome_name="A", target_size=Decimal("10"), fills=[
                Fill(venue="kalshi", side="buy", size=Decimal("10"),
                     price=Decimal("0.40"), fees=Decimal("0.10"), ts=ts),
                Fill(venue="kalshi", side="sell", size=Decimal("10"),
                     price=Decimal("0.39"), fees=Decimal("0.10"), ts=ts),
            ]),
        )
    acc = RealizedPnLAccumulator()
    await acc.on_basket_attempt(FakeAttempt())
    # Realized = sells − buys − fees = (10×0.39) − (10×0.40) − (0.10+0.10) = −0.30.
    total, n = await acc.snapshot()
    check("counts 1 close", n == 1)
    check("realized = −0.30", total == Decimal("-0.30"))
    # Re-emit same attempt → no change (dedup).
    await acc.on_basket_attempt(FakeAttempt())
    total2, n2 = await acc.snapshot()
    check("dedup: re-emission no-ops", n2 == 1 and total2 == total)

    # `complete` attempts must NOT credit realized (those are still held).
    class CompleteAttempt:
        outcome = "complete"
        ts = datetime.now(timezone.utc)
        legs = ()
    await acc.on_basket_attempt(CompleteAttempt())
    total3, n3 = await acc.snapshot()
    check("complete does not credit", n3 == 1 and total3 == total)


async def main():
    test_legbidtracker()
    await test_abort_flow()
    await test_coupling_filter()
    await test_profitability()
    await test_full_exit_cycle()
    await test_partial_escalation()
    await test_revert_when_unsellable()
    await test_depth_cap_sizes_subbasket()
    await test_repeg_follows_touch()
    await test_thin_depth_blocks()
    test_observed_tick()
    await test_half_cent_exit_repeg()
    await test_pnl_snapshot_math()
    await test_realized_pnl_accumulator()
    print(f"\n==== {PASS} passed, {FAIL} failed ====")
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
