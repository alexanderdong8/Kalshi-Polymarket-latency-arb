# Prediction Market Cross-Venue Arbitrage Research

This repository investigates whether equivalent prediction-market contracts can trade at different prices on Kalshi and Polymarket, and whether those temporary price differences can support a practical cross-venue arbitrage strategy.

The project has two complementary parts:

1. **Historical research** asks whether these opportunities appeared in past order books often enough to justify further work.
2. **Live trading infrastructure** monitors manually reviewed Kalshi and Polymarket US events and supports read-only, paper, and explicitly confirmed live modes.
3. **Deterministic backtesting** replays PMXT Kalshi and international Polymarket L2 data through the shared multi-outcome strategy.

Live order code is present but remains guarded by reviewed manifests, a per-run capital limit, a startup preview, and an exact `LIVE` confirmation. Automated tests mock execution and never submit real orders.

## The Core Idea

Binary prediction-market shares resolve to either `$1.00` or `$0.00`.

- A `YES` share pays `$1.00` if the event happens.
- A `NO` share pays `$1.00` if the event does not happen.
- If a Kalshi contract and a Polymarket contract truly describe the same event, buying `YES` on one venue and `NO` on the other creates a complete payout basket: exactly one side should pay `$1.00`.

Example:

```text
Kalshi:
  YES ask = 0.70
  NO ask  = 0.30

Polymarket:
  YES ask = 0.50
  NO ask  = 0.50

Potential arbitrage basket:
  Buy Kalshi NO at 0.30
  Buy Polymarket YES at 0.50
  Total entry cost = 0.80
  Gross edge = 1.00 - 0.80 = 0.20 per complete pair
```

This is only a real arbitrage if both contracts are genuinely equivalent under their actual resolution rules. Similar titles are not enough. Differences in event scope, cutoff time, settlement source, cancellation rules, overtime treatment, or other contract language can create false positives.

The real-world strategy also has to account for:

- Trading fees and fee rounding.
- Available order-book depth.
- Slippage.
- Stale or delayed market data.
- Partial fills: one leg may fill before the hedge leg.
- Cross-venue funding and capital allocation.
- Venue availability, access rules, and API rate limits.

## Repository Structure

```text
prediction_markets_arb/
  README.md                  Repository-level orientation
  historical_testing/        Historical order-book research and reports
  live_trading/              Monitor, paper, and live multi-outcome engine
  backtesting/               PMXT virtual-clock strategy replay
  docs/                      Architecture and operating decisions
```

### `historical_testing/`

The historical research package studies past Kalshi / Polymarket order books and asks:

> When equivalent markets diverged, could both legs have been bought for less than `$1.00` using executable prices and visible depth?

It includes tooling for market-pair discovery, historical order-book reconstruction, fee and slippage assumptions, opportunity scanning, and summary reports.

This section of the repository will continue to evolve as the historical methodology and findings are refined.

Read next: [historical_testing/README.md](historical_testing/README.md)

### `live_trading/`

The live package retains the broad read-only scanner and adds a manifest-driven
multi-outcome application for monitor, paper, and live execution.

It:

- Pulls active Kalshi and Polymarket US market catalogs through REST APIs.
- Matches likely equivalent contracts across venues.
- Uses authenticated WebSocket streams to keep order books current without repeatedly polling for prices.
- Splits large subscription sets into concurrent shards of at most `100` markets.
- Normalizes venue-specific books into comparable `YES` and `NO` executable asks.
- Recalculates only the affected matched pair immediately after a book update.
- Applies fee estimates and a configurable slippage buffer.
- Displays the strongest current candidates in a terminal dashboard.
- Records sampled book snapshots, opportunity events, and metrics to bounded local SQLite storage.
- Includes synthetic benchmarks for `100`, `250`, and `500` matched pairs.

The live scanner is optimized for a local Windows PC and has been tested at `500` synthetic matched pairs without requiring one process per event.

Read next: [live_trading/README.md](live_trading/README.md)

## Current Status

Implemented:

- Historical arbitrage research tooling.
- Live Kalshi REST and authenticated WebSocket connectivity.
- Live Polymarket US REST and authenticated WebSocket connectivity.
- Cross-venue matching heuristics.
- Event-driven live opportunity detection.
- Concurrent WebSocket subscription sharding.
- Fee-aware edge calculations.
- Local terminal dashboard.
- Bounded local storage with a default `3 GB` generated-data quota.
- Local steady, burst, and stress benchmarks up to `500` matched pairs.
- Automated tests for live scanner behavior and historical research regressions.

Not implemented:

- Live order placement.
- Order cancellation.
- Automated hedge or unwind behavior.
- Partial-fill handling.
- Paper-trading fill simulation.
- Production deployment.

The current goal is to gather enough trustworthy live data to determine whether adding execution logic is justified.

## How The Live Scanner Fits Together

```text
REST market discovery
        |
        v
cross-venue market matcher
        |
        v
concurrent Kalshi and Polymarket US WebSocket shards
        |
        v
normalized in-memory order books
        |
        v
direct affected-pair lookup and immediate arbitrage evaluation
        |
        +--------------------+
        |                    |
        v                    v
terminal dashboard     bounded SQLite recording
```

The important performance decision is that incoming updates do not trigger a full scan of every matched pair. Each venue market key maps directly to its related matched pair, so one message causes only the relevant comparison to run.

## Quick Start

Install the live scanner:

```powershell
cd C:\Users\alexa\Documents\CompSci\prediction_markets_arb\live_trading
python -m pip install -e .[test]
```

Return to the repository root:

```powershell
cd C:\Users\alexa\Documents\CompSci\prediction_markets_arb
```

Validate configured API credentials without placing orders:

```powershell
python -m live_trading doctor --categories sports --timeout-seconds 6
```

Render a fake dashboard without live credentials:

```powershell
python -m live_trading sample-tui
```

Run the read-only live scanner:

```powershell
python -m live_trading run --categories sports,politics --max-matches 500 --metrics-out live_trading/data/metrics.json
```

Run local synthetic performance benchmarks:

```powershell
python -m live_trading benchmark --pairs 100,250,500 --profiles steady,burst,stress --duration-seconds 60 --out live_trading/data/benchmarks/local.json
```

For full setup, credential configuration, module details, storage policy, benchmark interpretation, and contributor guidance, see [live_trading/README.md](live_trading/README.md).

## Safety And Access Notes

- This repository is research and engineering tooling, not financial advice.
- The live package is deliberately read-only.
- Contract equivalence must be reviewed carefully before any future trading logic is enabled.
- From the United States, future automated execution should use legally available venue APIs such as Kalshi and Polymarket US.
- The international Polymarket CLOB should not be used to bypass geographic restrictions.
- API keys and private keys belong in ignored `.env` files and must never be committed.

## Recommended Reading Order

For a new contributor:

1. Read this file for the project purpose and repository map.
2. Read [live_trading/README.md](live_trading/README.md) for the live scanner architecture and operating guide.
3. Read [historical_testing/README.md](historical_testing/README.md) for the historical research methodology and findings.
4. Start in `live_trading/src/live_trading/main.py` to follow the live runtime orchestration.
5. Continue into `live_trading/src/live_trading/engine.py`, `registry.py`, and the venue adapters to understand the performance-sensitive path.

## Near-Term Roadmap

1. Improve structured market matching, especially for sports league/team/date fields.
2. Run longer local live-data soaks and analyze opportunity duration, depth, freshness, and reconnect behavior.
3. Improve historical analysis and document findings.
4. Add paper-trading fill simulation.
5. Design live execution separately, with strict risk controls, maximum unhedged exposure, kill switches, and careful legal/API review.
