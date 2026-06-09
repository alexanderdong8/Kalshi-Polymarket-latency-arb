# Live Multi-Outcome Trading Engine

This package contains the Kalshi / Polymarket US monitor, paper trader, and
capital-limited live engine. The earlier broad matched-market scanner remains
available through the discovery-oriented CLI flags.

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

Manifest-driven paper mode simulates orders without changing public books.
Live mode can place and cancel orders only after manifest review, balance and
position preview, a capital limit, and exact startup confirmation.

## Project Status At A Glance

This repository currently has two related packages:

| Package | Purpose | Status |
| --- | --- | --- |
| `historical_testing/` | Replay historical Kalshi / Polymarket data and estimate whether cross-venue dislocations existed in the past. | Research tooling already exists. |
| `live_trading/` | Monitor, paper trade, or explicitly enable live trading for a reviewed multi-outcome event. | Implemented with guarded live adapters. |
| `backtesting/` | Replay PMXT Kalshi and international Polymarket L2 with virtual time. | Implemented as a simulator, not an optimizer. |

The live package has working authenticated API connectivity to both venues, a local terminal UI, bounded data recording, and a synthetic benchmark harness. It does **not** yet execute trades or simulate order fills.

The immediate research question is:

> Are there enough correctly matched, sufficiently liquid, sufficiently long-lived cross-venue dislocations to justify building a real execution engine?

The scanner is intentionally structured so that an execution module can be added later without putting order-placement concerns inside market-data parsing or UI code.

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

## Trading Concept And Terminology

A binary prediction-market contract resolves to either `$1.00` or `$0.00`.

- A `YES` share pays `$1.00` if the event happens.
- A `NO` share pays `$1.00` if the event does not happen.
- If two contracts truly describe the same event, buying `YES` on one venue and `NO` on the other creates a complete payout basket: exactly one leg should pay `$1.00`.
- The position is only a true arbitrage when the contracts are semantically equivalent under their actual resolution rules.

The scanner always looks at **asks**, because asks represent the price at which a new buy order could attempt to enter. Bids, last-trade prices, UI percentages, and midpoint prices may look attractive but are not executable entry prices.

For each matched pair, the scanner evaluates:

| Direction | Entry cost |
| --- | --- |
| Buy Kalshi `NO` + buy Polymarket US `YES` | `kalshi.no_ask + polymarket.yes_ask` |
| Buy Kalshi `YES` + buy Polymarket US `NO` | `kalshi.yes_ask + polymarket.no_ask` |

An opportunity object contains:

- The two venues and directions.
- Each executable ask.
- Total entry cost.
- Gross edge before fees.
- Estimated fee cost per contract.
- Configured slippage buffer.
- Estimated net edge.
- Top-of-book depth limit.
- Receipt and detection timestamps.
- Any matching warnings.

Even a positive scanner result is not a guarantee of realized profit. A future execution engine must handle partial fills, queue priority, book movement between orders, venue outages, and contract-rule mistakes.

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

## High-Level Architecture

```text
                    periodic REST discovery
          +-----------------------------------------+
          |                                         |
          v                                         v
  +-------------------+                    +-----------------------+
  | Kalshi venue      |                    | Polymarket US venue   |
  | REST + WS shards  |                    | REST + WS shards      |
  +---------+---------+                    +-----------+-----------+
            |                                          |
            +------------------+-----------------------+
                               |
                               v
                     +--------------------+
                     | normalized books   |
                     | BookStore          |
                     +---------+----------+
                               |
               direct affected-pair lookup only
                               |
                               v
                     +--------------------+
                     | PairRegistry       |
                     | HotPathEngine      |
                     +---------+----------+
                               |
                 +-------------+-------------+
                 |                           |
                 v                           v
       +--------------------+      +--------------------+
       | OpportunityStore   |      | signal queue       |
       | TUI snapshot       |      | durable recorder   |
       +--------------------+      +--------------------+
```

The important design rule is that book parsing and pair evaluation remain fast and synchronous inside the event loop. Disk writes, metrics persistence, and terminal rendering are side paths. They must not delay arbitrage detection.

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

## Module Guide

### `main.py`

Defines the CLI and orchestrates the async runtime.

The live `run` command starts:

- One discovery pass before connecting streams.
- A stream supervisor that starts the current Kalshi and Polymarket US shard tasks.
- A periodic discovery refresh loop.
- The opportunity signal recorder.
- Event-loop lag monitoring.
- Periodic metrics persistence.
- The terminal dashboard refresh loop.

If periodic discovery changes the matched set, the stream supervisors restart their WebSocket topology and obtain fresh book snapshots. The entire application does not restart.

### `models.py`

Contains the normalized domain objects shared across modules:

- `VenueMarket`: one venue-specific market and its metadata.
- `MatchedMarket`: one candidate Kalshi / Polymarket US identity pair.
- `PriceLevel`: normalized price and size.
- `BookState`: normalized top-of-book state plus timing fields.
- `ArbOpportunity`: calculated cross-venue basket economics.

`BookState` has both wall-clock receipt time and a monotonic receipt timestamp. The monotonic timestamp is used for sub-millisecond internal latency measurements.

### `venues/kalshi.py`

Implements Kalshi market discovery and authenticated WebSocket consumption.

- REST discovery reads open markets.
- WebSocket subscriptions request `orderbook_delta`.
- Markets are split into concurrent shards of at most `100` tickers.
- Each shard reconnects independently with exponential backoff.
- Subscriptions request `use_yes_price: true`.
- `subscription_update_message()` prepares Kalshi dynamic add/remove subscription messages for later direct topology updates.

The current stream supervisor refreshes topology by restarting affected stream supervisors when discovery changes. The message builder exists so a later iteration can optimize that into in-place Kalshi subscription mutation.

### `venues/polymarket_us.py`

Implements Polymarket US discovery, REST book recovery, and authenticated WebSocket market data.

- REST discovery reads active, non-closed markets.
- Full `SUBSCRIPTION_TYPE_MARKET_DATA` is used for tradeable candidates so depth is available.
- `SUBSCRIPTION_TYPE_MARKET_DATA_LITE` is used for warning-marked review candidates to reduce unnecessary payload volume.
- `responsesDebounced: false` requests non-debounced updates for the tradeable hot path.
- Markets are split into concurrent shards of at most `100` slugs.

### `books.py`

Normalizes venue-specific market data into the common `BookState` shape.

Kalshi exposes binary bid books. The opposite-side ask is derived by complement:

```text
YES ask = 1 - best NO bid
NO ask  = 1 - best YES bid
```

With Kalshi unified YES pricing, incoming `NO` levels are converted back into ordinary `NO` prices before best bids and executable asks are calculated.

Polymarket US full messages provide bid and offer levels for the long side. The scanner derives the short side by complement:

```text
NO bid = 1 - best YES ask
NO ask = 1 - best YES bid
```

Lite messages only contain best bid/ask and therefore do not provide top-of-book depth. They are used for review display, not execution planning.

### `matching.py`

Matches likely identical markets across venues.

Matching uses:

- Normalized text and token overlap.
- Text similarity.
- Category agreement.
- Market-type agreement.
- Comparable event or expiration timing.
- Known semantic conflict phrases.

The matcher intentionally favors precision over recall. A false match can create a fake arbitrage, which is much more dangerous than failing to display a valid but ambiguous pair.

### `registry.py` And `engine.py`

Implement the low-latency scanner hot path.

`PairRegistry` maps `(venue, market_key)` directly to the affected matched pair or pairs. When a WebSocket update arrives, `HotPathEngine.process_book()`:

1. Updates the in-memory `BookStore`.
2. Offers a sampled snapshot to the non-blocking recorder queue.
3. Looks up only the pair or pairs affected by that market.
4. Evaluates both arbitrage directions.
5. Replaces the current opportunity snapshot for the pair.
6. Pushes opportunity events into a priority queue for durable recording.
7. Records receipt-to-evaluation and calculation-only latency.

The terminal UI does not rescan all matched pairs every `250 ms`. It reads the already-computed `OpportunityStore`.

### `shards.py`

Provides WebSocket shard splitting, concurrent fan-in, and independent reconnect loops.

A process-per-event design was intentionally rejected. For hundreds of markets it would add unnecessary Python process memory, excessive sockets, inter-process communication delay, and operational complexity. One async process is simpler and benchmarked comfortably on the local PC.

### `storage.py`

Implements bounded local persistence.

- Routine normalized BBO snapshots use compact hourly SQLite segments.
- Matched markets, every opportunity event, and periodic metrics use `events.sqlite3`.
- Routine snapshots are sampled and use a bounded queue.
- Durable events use a separate queue.
- Oldest routine segments rotate first when the quota is exceeded.
- Metrics and then old opportunities trim only as a last resort.

The recorder stores normalized BBO values, not every raw venue payload.

### `metrics.py` And `benchmark.py`

`MetricsCollector` tracks:

- Updates processed and rate.
- Pair evaluations.
- Opportunity events.
- Receipt-to-evaluation latency.
- Calculation-only latency.
- Event-loop lag.
- Signal queue depth.
- Reconnects.
- Discovery refresh success/failure.
- Stale books.
- Process CPU and resident RAM.
- Recorder queues, dropped routine snapshots, writes/sec, disk use, and rotations.

The synthetic benchmark runs three profiles:

| Profile | Meaning |
| --- | --- |
| `steady` | Moderate continuous flow with sleeps between small batches. |
| `burst` | Larger batches with short pauses, intended as the practical headroom check. |
| `stress` | No intentional pause, intended to estimate local throughput ceiling. |

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

Generated data is ignored by git through `live_trading/data/`.

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

Synthetic benchmark latency measures scanner processing after a message has entered the Python process. It does not measure venue-to-home-network delivery time and does not predict future order-placement round trips.

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

## Runtime Data Flow In Detail

On startup:

1. `Settings.from_env()` loads credentials and scanner configuration.
2. The application creates `BookStore`, `SegmentedRecorder`, `MetricsCollector`, and venue clients.
3. REST discovery pulls active markets from both venues.
4. `match_markets()` creates the initial cross-venue identity candidates.
5. `PairRegistry` indexes those candidates by both venue market keys.
6. Stream supervisors split subscriptions into shards and connect WebSockets.

For each live book update:

1. The venue adapter receives JSON from its shard socket.
2. The adapter timestamps receipt immediately.
3. `books.py` parses the venue message into a normalized `BookState`.
4. `HotPathEngine.process_book()` updates in-memory state and evaluates only affected pairs.
5. The latest opportunities become visible to the TUI.
6. Opportunity events are queued for durable recording.
7. A sampled routine BBO snapshot may be queued if its market has not been recorded recently.

Every ten minutes by default:

1. REST discovery runs again.
2. Matching runs again.
3. The registry replaces its candidate set.
4. Removed opportunities disappear from the current UI snapshot.
5. If subscription topology changed, stream supervisors reconnect with the new market sets.

## Known Limitations

The following are expected limitations, not accidental omissions:

- **No live execution:** there is no order creation, cancellation, or hedge logic.
- **No fill simulation:** positive opportunities are quote-level candidates, not proof that both legs could fill.
- **Matcher recall is incomplete:** structured sports matching by league/team/date needs improvement.
- **Manual rule review remains necessary:** warning-free text matching is still not a legal guarantee of equivalent settlement.
- **Depth modeling is top-of-book only:** the scanner does not yet walk multi-level books for larger trade sizes.
- **Polymarket US lite candidates have no depth:** they are display-only review candidates.
- **Discovery topology refresh reconnects supervisors:** Kalshi in-place add/remove messages are prepared but not yet used by the supervisor.
- **Local SQLite is research storage:** it is not intended as a production event bus.
- **Synthetic benchmarks are local processing measurements:** network delivery and eventual order execution require separate measurement.

## Contribution Guide

When adding behavior:

1. Keep market-data adapters read-only unless execution work is explicitly scoped as a separate milestone.
2. Normalize venue payloads inside `books.py`; do not leak venue-specific message shapes into `engine.py`.
3. Keep disk access, terminal output, and network retries outside the calculation path.
4. Preserve `Decimal` for prices, fees, and edge calculations.
5. Add fixtures and tests for each new venue message shape.
6. Prefer precision over recall in `matching.py`.
7. Run the live tests, historical regression tests, and `doctor` before merging.

Recommended verification:

```powershell
python -m pytest live_trading\tests -q
$env:PYTHONPATH='historical_testing'
python -m pytest historical_testing\tests -q
python -m live_trading doctor --categories sports --timeout-seconds 6
```

For performance-sensitive changes, also run:

```powershell
python -m live_trading benchmark --pairs 100,250,500 --profiles steady,burst,stress --duration-seconds 60 --out live_trading/data/benchmarks/local.json
```

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
