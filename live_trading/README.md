# Live Matched-Market Scanner

This is the read-only live scanner for the Kalshi / Polymarket US arbitrage idea.

The goal is to find active markets on both venues that appear to resolve on the same event, keep their order books hot with streaming market data, and show when the executable YES/NO basket costs less than `$1.00`.

Example:

```text
Kalshi:
  YES ask = 0.70
  NO ask  = 0.30

Polymarket US:
  YES ask = 0.50
  NO ask  = 0.50

Arb basket:
  Buy Kalshi NO at 0.30
  Buy Polymarket US YES at 0.50
  Entry cost = 0.80
  Gross edge = 1.00 - 0.80 = 0.20 per complete pair
```

If the two contracts are truly identical, one leg should pay `$1.00` at resolution. The scanner reports that gross edge, then subtracts estimated fees and a slippage buffer to estimate a net edge.

This package does not place, cancel, or modify orders. It is designed to prove the data path, matching quality, and opportunity frequency before execution code is added.

## What The System Does

The live scanner has five jobs:

1. Discover active Kalshi and Polymarket US markets.
2. Match likely identical events across the two venues.
3. Subscribe to matched market order books using WebSockets.
4. Compute both arbitrage directions immediately whenever a book changes.
5. Show the best opportunities in a terminal dashboard and record observations to SQLite.

The two arbitrage directions are:

```text
buy Kalshi NO + buy Polymarket US YES
buy Kalshi YES + buy Polymarket US NO
```

The formula is:

```text
gross_edge = 1 - (yes_ask + no_ask)
net_edge = gross_edge - estimated_fees_per_contract - slippage_buffer_per_pair
```

The scanner uses executable asks, not midpoint prices.

## Current Safety Boundary

V1 is read-only.

It uses:

- Kalshi REST market discovery.
- Kalshi authenticated WebSocket order book data.
- Polymarket US REST market discovery and book recovery.
- Polymarket US authenticated WebSocket market data.
- Local SQLite recording.

It does not use:

- Order placement APIs.
- Cancel APIs.
- Balance transfers.
- Any endpoint whose purpose is to trade.

This matters because the first milestone is to verify whether the edge is frequent, fresh, and large enough after fees and slippage. Execution should only be added after the scanner has logged enough live data.

## Project Layout

```text
live_trading/
  src/live_trading/
    main.py                  CLI entrypoint
    config.py                Environment/config loading
    models.py                VenueMarket, MatchedMarket, BookState, ArbOpportunity
    matching.py              Cross-venue market matching
    books.py                 Normalized order book state and Kalshi/Polymarket parsers
    arb.py                   Arbitrage calculation
    fees.py                  Kalshi and Polymarket US fee estimates
    storage.py               SQLite recorder
    registry.py              Direct venue-market-to-pair lookup
    engine.py                Event-driven hot-path evaluation
    shards.py                Concurrent WebSocket subscription sharding
    metrics.py               Latency, queue, CPU, RAM, and recorder metrics
    benchmark.py             Synthetic steady/burst/stress load testing
    tui.py                   Terminal dashboard
    auth.py                  Kalshi and Polymarket US request signing
    venues/
      kalshi.py              Kalshi REST + WebSocket adapter
      polymarket_us.py       Polymarket US REST + WebSocket adapter
  tests/                     Unit and smoke tests
```

## Setup

From this folder:

```powershell
cd C:\Users\alexa\Documents\CompSci\prediction_markets_arb\live_trading
python -m pip install -e .[test]
```

The package is also runnable from the repo root once installed:

```powershell
cd C:\Users\alexa\Documents\CompSci\prediction_markets_arb
python -m live_trading sample-tui
```

## Credentials

Create a `.env` file in the repo root or in `live_trading/`:

```text
KALSHI_API_KEY_ID=
KALSHI_PRIVATE_KEY_PATH=
POLYMARKET_US_KEY_ID=
POLYMARKET_US_SECRET_KEY=
```

Alternative inline Kalshi private key:

```text
KALSHI_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

For compatibility with the existing historical research setup, the live scanner also recognizes these aliases from `historical_testing/.env`:

```text
kalshi-api-key-id=
kalshi-secret-key=
pm-key-id=
pm-secret-key=
```

Secrets are never printed by the CLI. The `doctor` command only reports whether each expected credential is present.

## API Diagnostic

Run this first:

```powershell
python -m live_trading doctor --categories sports --timeout-seconds 6
```

This checks:

- Credential presence.
- Kalshi REST active-market discovery.
- Polymarket US REST active-market discovery.
- Polymarket US REST first order book.
- Kalshi authenticated WebSocket first order book message.
- Polymarket US authenticated WebSocket first market-data message.

Latest local result with the configured keys:

```text
Credential presence:
  Kalshi key id: present
  Kalshi private key: present
  Polymarket US key id: present
  Polymarket US secret key: present
Testing REST endpoints...
OK   Kalshi REST active markets
OK   Polymarket US REST active markets
  Kalshi markets fetched: 10
  Polymarket US markets fetched: 10
OK   Polymarket US REST first order book
  Candidate matches from fetched sample: 0
Testing WebSocket endpoints...
OK   Kalshi WebSocket first orderbook message
OK   Polymarket US WebSocket first market-data message
```

The sample fetched only ten markets from each venue, so `Candidate matches from fetched sample: 0` is not a failure. It just means the tiny diagnostic sample did not contain the same event on both venues.

## Commands

Render a fake no-credential dashboard:

```powershell
python -m live_trading sample-tui
```

Discover candidate matched markets:

```powershell
python -m live_trading discover --categories sports,politics --max-matches 25
```

Run the live dashboard:

```powershell
python -m live_trading run --categories sports,politics --max-matches 500 --metrics-out live_trading/data/metrics.json
```

The live dashboard:

- Refreshes the terminal several times per second.
- Shows matched market titles and confidence.
- Shows Kalshi and Polymarket US YES/NO asks.
- Shows gross and net arbitrage edge.
- Marks stale books.
- Marks matches with warnings as review-only.
- Shows receipt-to-evaluation latency, recorder queue depth, disk use, and snapshot rotation count.

## Fast Path And Scaling

The scanner is designed for up to `500` matched pairs on one local PC without creating one Python process per event.

- Each venue uses long-lived WebSocket connections rather than repeated price polling.
- Markets are split into concurrent WebSocket shards of at most `100` subscriptions.
- Incoming messages update an in-memory `BookStore`.
- A `PairRegistry` maps each venue market key directly to the affected matched pair.
- Only the changed pair is recalculated. The scanner does not rescan every pair on every UI refresh.
- Disk recording and terminal rendering happen outside the calculation path.
- Discovery refreshes every ten minutes by default. If the matched set changes, the stream supervisors refresh their subscription topology and receive new snapshots.

Warning-marked Polymarket US review candidates use lightweight market-data subscriptions. Tradable candidates request full non-debounced market data so executable depth is available.

Kalshi streams explicitly request unified YES pricing through `use_yes_price: true`, then normalize the book back into YES and NO executable asks.

## Configuration

Environment variables:

```text
DISCOVERY_REFRESH_SECONDS=600
STALE_AFTER_SECONDS=5
MAX_MATCHES=100
MIN_MATCH_CONFIDENCE=0.74
MIN_GROSS_EDGE=0
SLIPPAGE_BUFFER_PER_PAIR=0.01
TRADE_SIZE=100
KALSHI_FEE_MODE=taker
POLYMARKET_TAKER_THETA=0.05
LIVE_TRADING_DATA_DIR=live_trading/data
LIVE_DATA_QUOTA_BYTES=3221225472
LIVE_DATA_LOW_WATERMARK_BYTES=2831155200
SNAPSHOT_INTERVAL_SECONDS=30
ROUTINE_QUEUE_MAXSIZE=20000
TUI_REFRESH_SECONDS=0.25
METRICS_WRITE_SECONDS=10
```

Default fee assumptions:

- Kalshi taker fee: `round up(0.07 * contracts * p * (1 - p))`.
- Kalshi maker fee: `round up(0.0175 * contracts * p * (1 - p))`.
- Polymarket US taker fee: `bankers round(theta * contracts * p * (1 - p))`, default `theta = 0.05`.

The fee model is an estimate. Before live execution, fee rates and market-specific fee rules should be rechecked against venue docs and actual fills.

## Data Recording

The scanner uses bounded segmented SQLite recording:

- `live_trading/data/events.sqlite3`: matched markets, every detected opportunity, and periodic metrics.
- `live_trading/data/snapshots/YYYYMMDDTHH.sqlite3`: compact hourly normalized BBO snapshots.
- Routine books are sampled at most once per market every `30` seconds by default.
- Generated live data has a hard `3 GB` quota.
- If the quota is reached, the recorder deletes oldest routine snapshot segments first until usage falls below the `2.7 GB` low-water mark.
- Durable metrics and opportunities are trimmed only as a last resort if snapshots alone cannot satisfy the hard cap.

The recorder is deliberately isolated from the hot path. If its routine queue fills during a burst, sampled routine snapshots can be dropped without delaying price evaluation. Opportunity recording uses a separate durable queue.

## Local Benchmark

Run steady, burst, and max-throughput stress profiles:

```powershell
python -m live_trading benchmark --pairs 100,250,500 --profiles steady,burst,stress --duration-seconds 60 --out live_trading/data/benchmarks/local.json
```

Latest local five-second-per-profile result on the current Windows PC:

| Profile | Pairs | Updates/sec | Receipt-to-eval p99 | Event-loop lag p99 | CPU | RAM | Dropped snapshots |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Steady | 500 | 1,211 | 0.099 ms | 7.207 ms | 9.9% | 48.9 MB | 0 |
| Burst | 500 | 11,527 | 0.042 ms | 14.733 ms | 37.0% | 49.7 MB | 0 |
| Stress | 500 | 35,225 | 0.028 ms | 1.614 ms | 96.6% | 52.2 MB | 0 |

The stress profile intentionally drives CPU close to saturation to measure the ceiling. The burst profile is the more useful local headroom check.

## Matching Philosophy

Matching favors precision over recall.

That means it is acceptable to miss some valid pairs early on. It is much worse to mark two different contracts as identical and report a fake arbitrage.

The matcher looks at:

- Title similarity.
- Shared tokens after normalization.
- Category.
- Market type.
- Event/expiration timing.
- Known conflict phrases such as "round of 16" vs "knockout stages".

Matches with timing or rule warnings are still displayed, but they should be treated as review-only.

## Testing

Run the live package tests:

```powershell
python -m pytest live_trading\tests -q
```

Run the historical research tests from the repo root:

```powershell
$env:PYTHONPATH='historical_testing'
python -m pytest historical_testing\tests -q
```

The live tests cover:

- Kalshi fee rounding.
- Polymarket US fee rounding.
- Kalshi complement order book math.
- Polymarket YES/NO complement math.
- The exact `0.30 + 0.50 = 0.80` arbitrage example.
- Matching warnings.
- Dashboard rendering without credentials.
- Direct affected-pair lookup instead of full rescans.
- Concurrent shard splitting and shard failure isolation.
- Kalshi unified YES pricing.
- Polymarket US lightweight book normalization.
- Snapshot coalescing and quota rotation.
- Synthetic benchmark report generation.

## Next Milestones

1. Improve matching recall for sports markets by using league/team/date fields directly.
2. Run a local real-data soak and analyze opportunity duration, depth, stream freshness, and reconnect behavior.
3. Add paper-trading fill simulation.
4. Only after that, design a separate execution module with strict kill switches and max unhedged exposure.
