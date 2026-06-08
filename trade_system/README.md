# Trade System

A cross-venue **latency-arbitrage bot for prediction markets**, targeting events
that are listed on both **Kalshi** and **Polymarket US**. The bot watches the
live order books on both venues, fires when the cheapest combination of every
outcome's YES contract across the two venues sums to less than $1 (minus a
slippage and margin buffer), and then either resells the basket as a passive
maker when the gap re-couples or holds the position to settlement (which pays
exactly $1 per basket because one outcome wins).

Today the order layer is fully **simulated** (`SimulatedOrderClient` paper
trades against a deplete-the-local-book model). The websocket data feeds, the
detector, the entry sizing, the partial-fill safety machinery, the exit
monitor, the live PnL tracker and the JSONL logs are real. The pieces
intentionally not yet built (live REST POSTs, settlement simulation, replay
tool, backtest harness) are listed at the bottom.

---

## Table of contents

1. [What this is — and why it's risk-free in theory](#1-what-this-is)
2. [Strategy overview](#2-strategy-overview)
3. [Architecture](#3-architecture)
4. [Install and first run](#4-install-and-first-run)
5. [CLI reference](#5-cli-reference)
6. [Configuration files](#6-configuration-files)
7. [Log files](#7-log-files-the-record-of-everything)
8. [How sizing works](#8-how-sizing-works)
9. [How partial fills are handled](#9-how-partial-fills-are-handled)
10. [Manual abort](#10-manual-abort)
11. [Tick size and adaptive maker pricing](#11-tick-size-and-adaptive-maker-pricing)
12. [Tests and verification](#12-tests-and-verification)
13. [What's simulated, and what live trading still needs](#13-whats-simulated)
14. [Known gaps and roadmap](#14-known-gaps-and-roadmap)

---

## 1. What this is

A binary-outcome event (e.g. "Who will win the 2026 NBA Finals?") has N
outcomes that are mutually exclusive and collectively exhaustive — exactly
one wins. A "basket" is one YES contract of each outcome, held simultaneously.
**At settlement the winning outcome's YES contract pays $1 and the others pay
$0, so the basket always pays out exactly $1.**

If you can assemble a complete basket for less than $1, you've locked in
positive PnL with zero directional risk — the only way you lose is if a venue
defaults. With two venues you can pick the cheaper side per outcome and
exploit short-lived pricing dislocations between Kalshi and Polymarket US:

```
total_basket_cost = Σ_outcome min(kalshi_ask_i, polymarket_ask_i)
```

When `total_basket_cost < $1 - (fees + slippage_buffer)`, fire. The bot does
this end-to-end:

- Real-time book reconstruction over websockets.
- A detector that watches the basket edge and fires only when it's not
  shrinking (momentum filter) and the books look stable.
- A capital-, depth-, and margin-aware sizer that picks how many contracts to
  buy without dumping into thin books.
- Parallel IOC entry orders, with retry-with-reprice on partials and an
  unhedged-loss kill switch.
- After entry, a maker-only exit monitor that posts limit sells one tick
  inside the spread when prices re-couple, with re-pegging to follow the
  market, a depth cap to never dump into a thin bid book, and a partial-fill
  safety machinery that re-balances by crossing only the excess (never leaves
  the position partially unhedged).
- Live PnL and position tracking on a 5-second tick.
- Manual abort via keypress or SIGUSR1.
- A comprehensive JSONL forensic record of every decision.

---

## 2. Strategy overview

### Entry

The detector ticks every 100 ms (`--detector-hz 10`). On each tick it
recomputes a `BasketEvaluation`:

```
basket_cost_per_share        = Σ_outcome cheapest VWAP (depth-haircut'd)
total_fees_per_share         = entry-side taker fees on the chosen legs
slippage_buffer_per_share    = --slippage-buffer-per-share (default 0.005)
entry_cost_per_share         = basket_cost + total_fees + slippage_buffer
edge_per_share               = entry_threshold − entry_cost_per_share
```

**All four conditions must hold to fire:**

1. `edge_per_share > 0` — basket entry cost is below `--entry-threshold`
   (default 0.98).
2. **Per-leg price range**: every leg's best YES bid is in
   `[--min-leg-bid, --max-leg-bid]` (default 0.02 / 0.98). Near 0¢ or 100¢
   the books are too thin and unreliable.
3. **Momentum filter**: for the last `--non-widening-ticks` ticks (default 2),
   basket-edge velocity ≤ `--near-zero-threshold` ($/share/sec, default 0.01).
   Translation: the gap is closing or flat — not actively widening — for at
   least 200ms.
4. **Books not stale**: every leg's book was updated within the staleness
   window.

On fire the executor sizes the basket (see §8), submits N parallel IOC orders
(one per leg, on whichever venue is cheaper), and either:

- **Completes**: all legs fully filled → basket becomes an open position held
  in the `PositionStore`.
- **Retries**: any leg partially filled → re-walk books, re-check
  profitability, re-submit residuals. Continues until either it completes,
  the `--retry-seconds` budget expires, or the unhedged loss on filled-
  but-not-complete legs exceeds `--max-unhedged-loss-pct`.
- **Unwinds**: timeout / kill-switch trips → sell back whatever filled at
  market on the venue it was bought on. Records `outcome=unwound_*`.

### Hold

A `complete` basket is risk-free as long as we hold every leg. The
`PositionStore` carries it indefinitely. The exit monitor (if enabled) wakes
every 2 seconds (`--exit-monitor-hz 0.5`) and looks for the chance to sell
back at a profit.

### Exit (path A: maker limits)

On every exit tick, for each open basket, all four of these must hold:

1. **Filter A — leg price range**: every leg's best bid ∈
   `[--exit-min-leg-bid, --exit-max-leg-bid]`. Same intent as the entry-side
   range filter.
2. **Filter B — coupling**: per-basket-share **limit-price sum** ≥
   `1 − --exit-coupling-tolerance` (default tol 0.01 → sum ≥ $0.99). The
   limit price is `best_bid + observed_tick` — i.e. the price we'd actually
   resell at — so the test reflects realized economics, not raw mid.
3. **Filter C — stability**: each leg's best bid has not moved by more than
   `--exit-bid-stability-threshold` per tick across the last
   `--exit-bid-stability-ticks` ticks. Lets us only post when the touch is
   calm enough that the limit can actually rest and get hit.
4. **Filter D — profitability**:
   `cost_basis + entry_fees + projected_exit_fees + --exit-required-margin-per-share
    < Σ_leg limit_price_i` per basket share.

If all four pass, the monitor posts **maker** sell limits at `best_bid +
observed_tick` on each leg's venue — one tick inside the spread, strictly
below the best ask (otherwise blocked as `cannot_post_inside_spread`). Sized
by the **depth cap** (see §8). The basket walks down as the limits fill;
re-pegs to follow the touch if the bid drifts and margin still clears.

### Exit (path B: hold to settlement)

Any basket that path A can't service stays in `PositionStore` until the
event resolves. At process exit the bot prints a reconciliation summary of
every still-held basket. Live-venue settlement integration is not yet built —
operators must reconcile manually for now.

---

## 3. Architecture

```
                 +------------------+
   Kalshi WS --> | books/kalshi     |
                 +--------+---------+
                          |
                          v
                  +---------------+              +---------------------+
                  |   BookStore   | <----------- | books/polymarket_us |
                  +-------+-------+              +----------+----------+
                          |                                 ^
                          |                                 |
                          v                       Polymarket WS
                  +---------------+
                  |   Detector    |  ticks @ --detector-hz
                  | (entry signal)|
                  +-------+-------+
                          | FireEvent
                          v
                  +---------------+      +-----------------+
                  | EntryExecutor |----->| SimulatedOrder  |
                  |  - sizing     |      |    Client       |
                  |  - retries    |<-----+-----------------+
                  |  - unwind     |
                  +-------+-------+
                          | BasketAttempt
            +-------------+--------------+
            |                            |
            v                            v
  +-------------------+        +-----------------+
  | PositionStore     |        | TradeJournal +  |
  | (held baskets)    |        | ExecutionJournal |
  +-------+-----------+        | (-> trades JSONL)|
          |                    +-----------------+
          v
  +-----------------+         +------------------+
  | ExitMonitor     |-------->| ExitJournal      |
  |  - filters      |         | (-> exits JSONL) |
  |  - depth cap    |         +------------------+
  |  - re-peg       |
  |  - rebalance    |
  +-------+---------+
          |
          v
  +-----------------+         +------------------+
  | PnLTracker      |-------->| PnLJournal       |
  | (5s snapshots)  |         | (-> pnl JSONL)   |
  +-------+---------+         +------------------+
          |
          v
  +-----------------+
  | TUI (Rich Live) |   <---- abort: 'a' key / SIGUSR1
  +-----------------+
```

All components are asyncio tasks under one `asyncio.gather`. The TUI reads
from a `DetectorState` snapshot the other tasks mutate.

---

## 4. Install and first run

### Prerequisites

- Python 3.9+
- A POSIX-like shell (for SIGUSR1; on Windows the bot still works but loses
  the signal-based abort).

### Setup

```sh
cd trade_system
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env                                # then fill in creds
cp config/example_event.yaml config/my_event.yaml   # then edit identifiers
```

### Required environment variables (`.env`)

| Name | What it is |
|---|---|
| `KALSHI_API_KEY_ID` | Your Kalshi API key ID |
| `KALSHI_PRIVATE_KEY_PATH` | Path to the RSA private key PEM file Kalshi issued |
| `POLYMARKET_US_KEY_ID` | Your Polymarket US API key ID |
| `POLYMARKET_US_SECRET_KEY` | Base64-encoded Ed25519 secret |

You don't need credentials to run with `--mock` (synthetic data).

### First run — fully synthetic

```sh
python -m trade_system --config config/my_event.yaml \
  --mock --target-size 100 \
  --enable-execution --enable-exit-monitor
```

You'll see the live TUI with side-by-side venue tables, the detector footer,
the executor footer, and the "Positions & PnL" panel updating every 5
seconds. Press `a` to manually abort the current entry attempt; press
`Ctrl-C` to stop.

### First live run, one venue at a time

```sh
python -m trade_system --config config/my_event.yaml --only kalshi
python -m trade_system --config config/my_event.yaml --only polymarket_us
```

Confirms each venue's WS auth + book reconstruction independently before
turning both on. The detector + executor remain off until you pass
`--target-size`, so this is a read-only sanity check.

### Live run with full stack

```sh
python -m trade_system --config config/my_event.yaml \
  --target-size 100 --detector-hz 10 \
  --entry-threshold 0.98 \
  --slippage-buffer-per-share 0.005 \
  --depth-haircut 0.7 \
  --enable-execution \
  --max-capital-per-trade 50 --min-capital-per-trade 10 \
  --profitable-depth-fraction 0.5 \
  --initial-balance 1000 \
  --retry-seconds 2.0 --retry-poll-ms 100 \
  --max-unhedged-loss-pct 0.05 \
  --enable-exit-monitor \
  --exit-coupling-tolerance 0.01 \
  --exit-required-margin-per-share 0.01 \
  --exit-depth-fraction 0.5 \
  --partial-exit-deadline-seconds 5 \
  --pnl-interval-seconds 5
```

(Reminder: even with credentials and `--enable-execution`, the order client
is still `SimulatedOrderClient`. No real orders are sent until a
`LiveOrderClient` is built.)

---

## 5. CLI reference

Every flag, by category. Defaults are in parentheses.

### Plumbing / run control
| Flag | Default | Meaning |
|---|---|---|
| `--config` | *(required)* | Path to the event YAML |
| `--log-dir` | `logs` | Directory for JSONL output files |
| `--only` | `both` | Restrict to `kalshi`, `polymarket_us`, or `both` |
| `--mock` | off | Use synthetic data, no creds |
| `--no-tui` | off | Disable the live TUI (logging continues) |
| `--refresh-hz` | 4 | TUI refresh rate |
| `--frames N` | — | Render N static frames to stdout instead of live mode |
| `--duration N` | — | Stop after N seconds (demos, tests) |

### Detector (entry signal)
| Flag | Default | Meaning |
|---|---|---|
| `--target-size N` | — | Basket size in contracts; **setting it enables the detector** |
| `--detector-hz` | 10 | Detector tick rate (must be ≥ 10) |
| `--entry-threshold` | 0.98 | Fire when basket entry cost/share is below this |
| `--slippage-buffer-per-share` | 0.005 | Per-share haircut added before testing the threshold |
| `--depth-haircut` | 0.7 | Fraction of each displayed level treated as reachable |
| `--momentum-window-ms` | 500 | Rolling window for velocity estimate |
| `--non-widening-ticks` | 2 | Consecutive non-widening ticks required to fire |
| `--near-zero-threshold` | 0.01 | Velocity ≤ this counts as non-widening ($/share/sec) |
| `--min-leg-bid` | 0.02 | Skip if any leg's best YES bid is below this |
| `--max-leg-bid` | 0.98 | Skip if any leg's best YES bid is above this |

### Fees
| Flag | Default | Meaning |
|---|---|---|
| `--kalshi-theta` | 0.07 | Kalshi taker fee theta |
| `--polymarket-theta` | 0.05 | Polymarket US taker fee theta |

### Entry executor (sizing + order placement)
| Flag | Default | Meaning |
|---|---|---|
| `--enable-execution` | off | Turn on the simulated order layer |
| `--initial-balance` | 1000 | Per-venue starting balance (sim) |
| `--max-capital-per-trade` | 50 | Max $ committed per fire |
| `--min-capital-per-trade` | 10 | Skip if basket $ value < this |
| `--profitable-depth-fraction` | 0.5 | Share cap = this × min over legs of profitable depth |
| `--retry-seconds` | 2.0 | Total budget to retry residual IOCs |
| `--retry-poll-ms` | 100 | Sleep between residual re-checks |
| `--max-unhedged-loss-pct` | 0.05 | Unwind early if unhedged MTM loss exceeds this fraction |

### Exit monitor (path A maker exit; path B = no-op)
| Flag | Default | Meaning |
|---|---|---|
| `--enable-exit-monitor` | off | Turn on the exit layer (requires `--enable-execution`) |
| `--exit-coupling-tolerance` | 0.01 | Path A fires only when limit-price sum ≥ $1 − this |
| `--exit-bid-stability-ticks` | 2 | Stable-bid ticks required before path A fires |
| `--exit-bid-stability-threshold` | 0.01 | Max per-tick bid drift that still counts as stable ($) |
| `--exit-required-margin-per-share` | 0.01 | Required net margin for path A profitability |
| `--exit-depth-fraction` | 0.5 | Per-cycle sell cap = this × min near-touch bid depth |
| `--exit-bid-depth-ticks` | 3 | How many ticks below best bid count as near-touch bid depth |
| `--exit-repeg` / `--no-exit-repeg` | on | Re-peg to follow best_bid + tick, margin-bounded |
| `--exit-limit-timeout-seconds` | 30 | Cancel an unfilled resting limit after this long |
| `--partial-exit-deadline-seconds` | 5 | Force-flatten a partially-unhedged basket after this long |
| `--exit-monitor-hz` | 0.5 | Exit monitor tick rate (one tick every 2s by default) |
| `--exit-min-leg-bid` | 0.02 | Path A skips if any leg's bid is below this |
| `--exit-max-leg-bid` | 0.98 | Path A skips if any leg's bid is above this |
| `--kalshi-tick-size` | 0.01 | Tick **fallback** when the book is too shallow to infer |
| `--polymarket-tick-size` | 0.01 | Tick **fallback** for Polymarket US |

### Live PnL
| Flag | Default | Meaning |
|---|---|---|
| `--pnl-interval-seconds` | 5 | Snapshot held positions + PnL every N seconds (≥ 1) |

### Manual abort

No flag. Press `a` in the TUI to abort the current entry attempt, or
`kill -USR1 <pid>` from another shell.

---

## 6. Configuration files

### `config/<event>.yaml`

```yaml
event:
  name: "2026 NBA Finals Winner"
  description: "Which team will win the 2026 NBA Finals"
  outcomes:
    - name: "Boston Celtics"
      kalshi_ticker: "KXNBAFINALS-26-BOS"
      polymarket_slug: "will-the-celtics-win-the-2026-nba-finals"
    - name: "Denver Nuggets"
      kalshi_ticker: "KXNBAFINALS-26-DEN"
      polymarket_slug: "will-the-nuggets-win-the-2026-nba-finals"
    # ... one entry per outcome
```

Loader validates: every outcome has both fields, tickers and slugs are unique
within the event.

### `.env`

See §4. `.env.example` is checked in as a template; `.env` is gitignored.

---

## 7. Log files (the record of everything)

All logs land in `--log-dir` (default `./logs`). One file per category per
run; filenames carry the event slug and a timestamp.

| File | One record per … | What it holds |
|---|---|---|
| `kalshi-<event>-<ts>.jsonl` | every Kalshi WS message in or out | Verbatim raw payload, direction, ts_ns |
| `polymarket_us-<event>-<ts>.jsonl` | every Polymarket WS message | Same shape, per venue |
| `fires-<event>-<ts>.jsonl` | detector fire | Full `BasketEvaluation` + momentum + chosen venue per leg |
| `execution-<event>-<ts>.jsonl` | basket attempt summary | High-level `BasketAttempt` (outcome, rounds, unwind count) |
| `trades-<event>-<ts>.jsonl` | basket attempt detail | Per-round projected-vs-actual VWAP, per-order timing, per-leg final cost basis + MTM, **sizing block** |
| `exits-<event>-<ts>.jsonl` | exit-monitor tick of interest | `blocked` (with `blocked_by` reason), `posted`, `reposted`, `fill`, `escalated`, `reverted` |
| `pnl-<event>-<ts>.jsonl` | every 5 seconds (`--pnl-interval-seconds`) | `total_cost_basis`, `total_mark_to_market`, `total_unrealized_pnl`, `realized_pnl_dollars`, `net_pnl_dollars`, per-basket breakdown |

Files are flushed line-by-line; a `kill -9` leaves a complete record of
everything received and decided so far.

---

## 8. How sizing works

### Entry sizing

The executor computes three caps and picks the smallest:

```
capital_size     = floor(min(--max-capital-per-trade, total_balance) / per_share_cost)
achievable_size  = the detector's walker-projected fill (already haircut)
share_cap        = floor(--profitable-depth-fraction × min over legs of [profitable depth])
                   where "profitable depth" for leg i = sum of ask sizes on the
                   chosen venue at prices ≤ (entry_threshold − Σ_{j≠i} vwap_j
                   − total_fees − slippage_buffer)
chosen_size      = min(capital_size, achievable_size, share_cap)
```

If `chosen_size × per_share_cost < --min-capital-per-trade`, the trade is
**aborted** (not fired). Each sizing decision is recorded in the `trades`
JSONL under the `sizing` block, with `binding_constraint` showing which cap
bound (`capital` / `achievable` / `share_cap` / `aborted`).

#### Worked example
- 3-leg event, `per_share_cost ≈ $0.79`, balance $2000, max-cap $50.
- `capital_size = floor($50 / $0.79) = 63`.
- Detector says achievable = 100.
- Profitable depth per leg: 637 / 796 / 788 → min = 637 → share cap = `floor(0.5 × 637) = 318`.
- `chosen_size = min(63, 100, 318) = 63` → capital binds. The basket is 63
  contracts on every leg, ~$49.50 deployed.

### Exit sizing (depth cap)

The exit monitor never tries to liquidate the whole position at once:

```
near_touch_bid_depth_i = Σ bid sizes at prices ≥ best_bid_i − bid_depth_ticks × tick_i
Q = min(balanced_holding, floor(--exit-depth-fraction × min_i near_touch_bid_depth_i))
```

`Q` contracts are sold uniformly from every leg in this cycle. Because we
sell the same `Q` from every leg, the held remainder is still a complete
balanced basket — risk-free. The position walks down in sub-baskets without
ever exposing us directionally.

#### Worked example
- Held basket: 100 contracts/leg.
- Near-touch bid depth: leg A 40, leg B 1000.
- `Q = min(100, floor(0.5 × 40)) = 20`. Posts 20 sell limits per leg this
  cycle. The next cycle (after these fill or get cancelled) repeats with the
  fresh `remaining_to_sell = 80`/leg.

---

## 9. How partial fills are handled

### Entry-side partials (retry, then unwind)

If the initial IOC round leaves any leg short:

1. **Retry loop**: while time remains in `--retry-seconds`, re-walk the books,
   re-check whether completing the residual is still profitable at the
   current prices (plus the slippage buffer), and submit fresh residual IOCs.
   Multiple rounds cascade until either all legs complete or time runs out.
2. **Kill switch**: each iteration computes `unhedged_mtm_loss / cost_basis`
   on the filled-but-incomplete portion. If it exceeds
   `--max-unhedged-loss-pct` (default 5%), unwind immediately.
3. **Unwind**: sell back every filled portion on the venue it was bought on,
   at market (IOC sweeping down to safety). Outcome recorded as
   `unwound_timeout` / `unwound_loss` / `unwound_no_residual_depth`.

### Exit-side partials (rebalance, then revert)

Because the exit monitor sells uniform sub-baskets, the safety model is
**balance, not flatness**: legs held in *equal* amounts are risk-free; legs
held in *unequal* amounts are directionally exposed.

`remaining_to_sell[(venue, outcome)]` is the per-leg net held position and
drives every decision.

1. **Imbalance detected** (max remaining > min remaining): start a clock
   (`--partial-exit-deadline-seconds`, default 5s — separate from and shorter
   than the 30s resting-limit timeout, because directional risk needs faster
   resolution).
2. **Clock expires** → **rebalance**: cancel any resting limits, then IOC-sell
   the **excess** of each over-held leg down to the minimum remaining
   (sweeping bid book down to `--exit-min-leg-bid`). This is the *only*
   place the exit path crosses the spread. Outcome recorded as `escalated`.
3. **An over-held leg has no bid at all** → **revert**: buy the under-held
   legs *up* to the most-held level (sweeping ask book up to
   `--exit-max-leg-bid`), restoring a complete balanced basket. Flag the
   basket `hold_to_settlement` and stop trying to exit it via path A.
   Outcome recorded as `reverted`.

Once flagged, the basket stays in `PositionStore` and rides to settlement.

---

## 10. Manual abort

A pair of triggers wakes the same `asyncio.Event`, which the executor's
retry loop checks at the top of each iteration:

- **Keypress `a`** in the TUI (cbreak-mode stdin listener; restores terminal
  on exit).
- **`kill -USR1 <pid>`** from any shell. (Works headless. The early
  startup window is guarded so a signal that arrives before the asyncio
  handler is wired doesn't terminate the process.)

When triggered:

- The *current* entry attempt aborts on its next retry iteration (≤
  `--retry-poll-ms`, default 100 ms).
- The existing unwind step runs to sell back any filled portion.
- Outcome is recorded as `aborted_by_user`.
- The detector keeps running; new fires can still fire new attempts.
- Open positions held from prior `complete` attempts are untouched — exit
  monitor and PnL tracker continue.

Aborting a *resting exit limit* via abort is not implemented yet; for that,
stop the process (`Ctrl-C`).

---

## 11. Tick size and adaptive maker pricing

A venue's **current tick** is the smallest nonzero gap between adjacent
levels on the live book. The exit monitor infers it directly from each
incoming `BookSnapshot` via `_observed_tick(book, fallback)`. This means:

- If Kalshi runs a market on half-cent ticks (some series do), the exit limit
  posts at `best_bid + $0.005`, not `$0.01`.
- If a future venue introduces a new tick grid, no code change is needed —
  the monitor follows automatically.
- When a book is too shallow to infer (one level only), the CLI fallbacks
  `--kalshi-tick-size` / `--polymarket-tick-size` (default 0.01) are used.

The exit limit is always **strictly inside the spread**:

```
limit_price = best_bid + observed_tick
must hold:   limit_price < best_ask    (otherwise blocked: cannot_post_inside_spread)
```

This makes the order a guaranteed maker (it never crosses on the normal
path), sitting as the new best ask at the front of the queue.

### Re-pegging (`--exit-repeg`, default on)

Each monitor tick, if the bid drifted down such that our resting price is no
longer `best_bid + tick`, the monitor cancels and reposts at the new touch —
**but only if the basket still clears the required margin at the new price**.
If chasing down would breach margin, the existing order is left in place
rather than cancelled, on the theory that a stale-but-profitable order can
still fill, but a fresh-but-unprofitable one is a guaranteed loss. To turn
this off entirely (post-once-and-wait): `--no-exit-repeg`.

---

## 12. Tests and verification

```sh
.venv/bin/python tests/test_exit_abort.py
```

Currently 40 checks across 14 test groups. Covered:

1. `LegBidTracker.is_stable` — the soft volatility filter
2. Manual abort flow → `aborted_by_user` outcome + unwind runs
3. Exit coupling filter at two tolerances (now testing the limit-price sum)
4. Exit profitability gate (posts when profitable, blocks when not)
5. Full exit cycle: post → cross → fill → basket removed
6. Partial exit → escalate by crossing → balanced
7. Partial exit, no-bid leg → revert by buyback → hold-to-settlement
8. Depth cap sizes a uniform sub-basket (`Q = 20` from 40-deep leg)
9. Re-peg follows the touch down (`0.51 → 0.50` after bid drop)
10. Thin-depth book → `blocked_by="bid_depth_too_thin"`
11. `_observed_tick` inference + shallow-book fallback
12. Half-cent observed tick → exit posts at `best_bid + 0.005`
13. `PnLTracker.compute_snapshot` math (cost / mtm / unrealized)
14. `RealizedPnLAccumulator` credits only on close + dedups

End-to-end smoke tests are baked into the same suite via the mock data
feeds; for a manual interactive smoke, run the live mock command in §4.

---

## 13. What's simulated

`SimulatedOrderClient` is the only `OrderClient` implementation today. It:

- Walks the local `BookStore` to compute IOC fills at displayed prices.
- Tracks resting `submit_limit_postonly` orders and fills them on the next
  `poll_resting_orders` call once the book crosses the limit price.
- Maintains per-venue cash balances.
- Depletes consumed depth so subsequent fills see realistic state.
- Charges venue-correct taker fees (Kalshi ceil-cent; Polymarket
  banker's-rounded).

A `LiveOrderClient` implementing the same `OrderClient` protocol against:

- **Kalshi**: REST `POST /portfolio/orders` with RSA-PSS signing (signing
  utilities already live under `src/trade_system/auth/kalshi.py`).
- **Polymarket US**: REST POST with Ed25519 signing
  (`src/trade_system/auth/polymarket_us.py`).

…would slot in without changes to the detector, executor, exit monitor, or
PnL tracker.

What's also not yet simulated:

- **Settlement**. Held positions persist in memory; manual reconciliation is
  required once the event resolves on each venue. A `--simulate-settlement
  <outcome>` flag would be straightforward to add.
- **Polymarket maker rebates**. Path-A exit fees are currently modelled at
  the taker rate, which is conservative. Wiring the rebate is a small
  change once `LiveOrderClient` lands.

---

## 14. Known gaps and roadmap

| Area | What's there | What's next |
|---|---|---|
| Data feeds | Live WS + book reconstruction on Kalshi + Polymarket US | Multi-event support |
| Detector | Full entry signal with momentum + bid-range + slippage | Configurable per-venue maker/taker pathway |
| Sizing | Capital / achievable / share-cap, depth-cap on exit | Per-level (vs aggregate) sub-basket cap |
| Execution | Parallel IOC, retry-with-reprice, unwind, kill switch | LiveOrderClient (Kalshi + Polymarket POST) |
| Exit monitor | Maker limits, re-peg, depth cap, rebalance/revert safety | Cancel resting exit limits via the abort trigger |
| Logging | 7 JSONL files: kalshi, poly, fires, execution, trades, exits, pnl | Replay tool that consumes captured JSONL |
| TUI | Live tables + detector / executor / PnL panels + abort hint | Optional historical-fire ribbon |
| Testing | 40 in-process unit + end-to-end checks | Replay-driven backtest harness |

---

## License

Private; do not redistribute.
