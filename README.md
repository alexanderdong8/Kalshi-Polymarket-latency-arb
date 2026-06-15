# Prediction-Market Arbitrage System

This repository is a local application for discovering, reviewing, paper
trading, live trading, and historically backtesting complete prediction-market
events across Kalshi and Polymarket.

This is the single authoritative README for operating and understanding the
current system. The original strategy description from the imported
`trade_system` project is preserved separately in
[`docs/strategy.md`](docs/strategy.md).

## Quick Start

From the repository root:

```powershell
.\start.ps1
```

This command:

1. Creates `.venv` if it does not exist.
2. Installs the Python packages when their project metadata changes.
3. Installs and builds the Next.js application when its package metadata
   changes.
4. Starts the FastAPI control service.
5. Starts the production Next.js server.
6. Waits for both health checks.
7. Opens `http://127.0.0.1:3000`.

Stop the complete application with:

```powershell
.\stop.ps1
```

The browser UI runs on port `3000`. The local-only FastAPI service runs on
port `8765`.

Recommended local versions:

- Python 3.10 or newer.
- Node.js 22 LTS.
- Windows PowerShell or PowerShell 7.

## The Architecture In One Sentence

`web/` is the frontend, `live_trading/src/live_trading/control/` is the API and
application control plane, `live_trading/src/live_trading/strategy/` is the
actual shared trading strategy, and `backtesting/` replays historical data
through that same Python strategy.

The frontend never reimplements trading decisions.

## High-Level Architecture

```text
Browser
  |
  | HTTP
  v
web/ - Next.js user interface
  |
  | typed REST requests, refreshed through TanStack Query
  v
live_trading/control/ - FastAPI control plane and WebSocket event hub
  |
  +--> scanner and event matching
  +--> SQLite control database
  +--> runtime supervisor
  +--> backtest job service
  |
  +-------------------------------+
  |                               |
  v                               v
live_trading runtime          backtesting package
  |                               |
  +----------+--------------------+
             |
             v
live_trading/strategy/ - shared Python strategy
             |
             v
Kalshi + Polymarket venue adapters
```

## Folder Responsibilities

```text
prediction_markets_arb/
  README.md
  start.ps1
  stop.ps1

  web/
    app/                    Next.js pages
    components/             reusable UI components
    lib/                    API helpers, types, generated OpenAPI types
    test/                   frontend safety tests

  live_trading/
    src/live_trading/
      control/              FastAPI, SQLite, scanner, workers, approvals
      strategy/             detector, depth, fees, sizing, execution, exits
      venues/               Kalshi and Polymarket US API adapters
      runtime.py            one event/mode trading runtime
      live_orders.py        authenticated live order client
      execution_persistence.py
      capture.py
    tests/

  backtesting/
    src/backtesting/        PMXT loading, validation, virtual-clock simulation
    tests/

  historical_testing/
    arb_study/              broader historical research pipeline
    reports/                generated research artifacts, ignored where large
    *.md                    research reports

  trade_system/
    src/trade_system/       original reference implementation
    tests/                  original script-style strategy checks

  docs/
    strategy.md             original trade_system README with provenance
```

### `web/`: frontend only

Everything a user sees in the browser lives in `web/`.

The Next.js application provides:

- Discover and scanner controls.
- Candidate ranking and event review.
- My Markets watchlist.
- Independent Paper, Live, and Backtests pages.
- Event-level basket charts.
- Per-outcome price and L2 order-book views.
- Orders, fills, positions, PnL, exposure, and stream-health displays.
- Credential-presence and connectivity diagnostics.
- Global emergency-stop controls.

The frontend can request actions and display results. It cannot:

- Decide that two events are equivalent.
- Approve an event by itself.
- Calculate a trading signal.
- Calculate order sizing.
- Simulate fills.
- Submit venue orders directly.

Those responsibilities remain in Python.

### `live_trading/src/live_trading/control/`: backend control plane

The FastAPI application is defined in:

```text
live_trading/src/live_trading/control/app.py
```

It exposes typed endpoints for:

- Health and shutdown.
- Catalog scans and scan progress.
- Candidate search and details.
- Event approval.
- Watchlist management.
- Paper and live activation.
- Worker state and stopping.
- Global emergency stop.
- Backtest creation and results.
- Strategy presets.
- Settings and read-only diagnostics.

The control package also contains:

| Module | Responsibility |
| --- | --- |
| `db.py` | SQLite control-plane persistence |
| `scanner.py` | catalog refresh, matching, event assembly, L2 ranking |
| `llm_matcher.py` | strict structured settlement-rule review |
| `manifests.py` | immutable versioned approved-event YAML |
| `supervisor.py` | isolated event/mode worker processes |
| `backtests.py` | historical validation and background jobs |
| `hub.py` | bounded WebSocket updates for the UI |
| `schemas.py` | Pydantic API contracts |

The generated TypeScript OpenAPI declarations are stored at:

```text
web/lib/openapi.d.ts
```

Regenerate them while the API is running with:

```powershell
cd web
npm run generate:api
```

### `live_trading/src/live_trading/strategy/`: shared trading logic

This is the strategy implementation used by both live/paper trading and
historical replay.

The strategy was ported from the original `trade_system` project so the
current application does not depend on that reference package at runtime.

It owns:

- Multi-outcome event definitions.
- Full L2 depth walking.
- Per-outcome venue selection.
- Fee calculation and fee rounding.
- Basket evaluation.
- Momentum and opportunity-stability filters.
- Capital and depth-aware sizing.
- Parallel entry execution.
- Partial-fill retries.
- Unhedged-loss checks.
- Forced unwind.
- Position tracking.
- Maker exit attempts.
- Re-pegging and exit depth limits.
- Exit-side rebalance or revert-to-complete-basket behavior.
- Hold-to-settlement position state.
- PnL calculations.

The original source description is retained in
[`docs/strategy.md`](docs/strategy.md). Current behavior should always be
verified against `live_trading/src/live_trading/strategy/` and its tests
because the original document contains historical implementation-status
statements.

### `live_trading/runtime.py`: one trading session

A runtime represents one approved event in one mode.

The runtime:

1. Loads the immutable approved event manifest.
2. Creates a normalized strategy book store.
3. Connects to the Kalshi and Polymarket US feeds.
4. Maps venue-specific books to the approved outcomes.
5. Records selected L2 data.
6. Evaluates the complete basket every 100 milliseconds.
7. Sends fire events to the shared executor in paper or live mode.
8. Tracks entries, exits, positions, and accounting.
9. Writes a bounded display snapshot for the control service.

The modes are:

| Mode | Market data | Orders |
| --- | --- | --- |
| Monitor | live Kalshi + Polymarket US | none |
| Paper | live Kalshi + Polymarket US | locally simulated |
| Live | live Kalshi + Polymarket US | authenticated venue APIs |

Paper fills do not mutate the public market-data books.

### `live_trading/venues/`: venue boundary

Venue adapters translate exchange-specific APIs into common internal models.

- `kalshi.py` handles market discovery, REST order-book snapshots, and
  authenticated WebSocket books.
- `polymarket_us.py` handles Polymarket US discovery, snapshots, and
  authenticated WebSocket books.
- `live_orders.py` handles live order submission, cancellation, balances,
  positions, and reconciliation.
- `auth.py` owns venue request signing.

This boundary keeps venue payload formats and authentication details out of the
strategy.

### `backtesting/`: historical strategy replay

The backtester imports the shared strategy models and detector from
`live_trading`. It does not contain a separate TypeScript or Python rewrite of
the strategy.

Historical replay currently uses:

- PMXT Kalshi L2.
- PMXT international Polymarket L2.

Live and paper trading use:

- Kalshi.
- Polymarket US.

This distinction is important. International Polymarket historical fills are
useful strategy evidence, but they are not proof of how Polymarket US would
have filled.

The backtester:

1. Loads an approved event manifest.
2. Requires historical identifiers for every outcome.
3. Loads and verifies the PMXT updates.
4. Rejects missing books, missing fees, invalid archives, and non-overlapping
   coverage.
5. Orders updates by `timestamp_received`.
6. Advances a virtual clock.
7. Runs the detector every 100 milliseconds.
8. Simulates 50, 250, 500, and 1,000 millisecond order-arrival delays.
9. Reports the strategy's maker model and the stricter price-pass model
   separately.
10. Returns ending cash, money gained, ROI, fills, fees, and replay data.

The default bankroll is `$1,000`.

### `historical_testing/`: research, not application runtime

This folder contains the broader research pipeline used to study categories,
strict cross-venue pairs, annual price-history proxies, PMXT L2 evidence, and
scenario suitability.

The scanner can consume its historical leaderboard output as one ranking
component. The folder is not part of an event's live order path.

Research conclusions and generated reports remain in the specifically named
Markdown files under `historical_testing/`.

### `trade_system/`: reference only

`trade_system/` is the original strategy project supplied by the user's
collaborator.

It is intentionally retained for:

- Strategy provenance.
- Comparison against the ported implementation.
- Original tests and design examples.

The current application does not import it at runtime. The original README was
moved to [`docs/strategy.md`](docs/strategy.md).

## Complete User Flow

### 1. Discover markets

The user opens **Discover** and starts a scan.

The backend:

1. Fetches fresh active Kalshi and Polymarket US catalogs.
2. Stores an audit snapshot in SQLite.
3. Performs deterministic contract matching.
4. Groups matched contracts into complete events.
5. Checks for duplicate or missing outcome mappings.
6. Checks that all active Kalshi event contracts are represented.
7. Fetches read-only L2 snapshots.
8. Calculates executable edge, fillable depth, and freshness.
9. Adds the historical category prior.
10. Runs strict structured LLM settlement-rule review.

The LLM compares:

- Event identity.
- Outcome meaning.
- Settlement scope.
- Deadlines and cutoffs.
- Cancellation treatment.
- Resolution criteria.

The LLM does not calculate prices, fills, PnL, or trading decisions.

### 2. Review and approve an event

The review page displays:

- Every outcome.
- Kalshi ticker to Polymarket US slug mapping.
- Venue titles and settlement rules.
- Deterministic check results.
- LLM confidence, reasoning, and warnings.
- Completeness status.

Approval is blocked when:

- Fewer than two outcomes exist.
- Outcome identifiers are duplicated.
- Active outcomes are missing.
- Deterministic conflicts remain.
- The LLM is unavailable.
- The LLM rejects equivalence.
- The user has not confirmed completeness and settlement review.

Approval writes an immutable versioned manifest under:

```text
live_trading/data/control/approved_events/
```

Watchlist entries represent complete events, not individual contracts.

### 3. Assign modes

From **My Markets**, an approved event may independently be assigned to:

- Paper.
- Live.
- Backtest.
- Any combination of those modes.

Each event and mode has its own budget and configuration.

### 4. Run paper trading

Paper mode launches a local worker using live public L2 feeds and the Python
strategy.

- Orders and fills are simulated.
- Public books remain unchanged.
- No trades are invented while the application is offline.
- Paper sessions stop when the application shuts down.
- Complete held baskets remain identifiable for settlement accounting.

### 5. Run live trading

Live activation requires:

1. An approved unchanged mapping.
2. Present credentials.
3. Venue reconciliation.
4. A balance and position preview.
5. A positive event budget.
6. An exact typed `LIVE` confirmation.

The preview shows:

- Kalshi balance.
- Polymarket US balance.
- Existing positions.
- Unresolved local orders.
- Maximum new exposure.
- Event mappings and warnings.

The runtime uses the same detector and executor as paper mode, but swaps in the
authenticated `LiveOrderClient`.

### 6. Run a backtest

The user selects an approved event and a bankroll.

Before replay, the backend validates:

- Every outcome has historical identifiers.
- Both venues have complete L2.
- Coverage overlaps.
- Updates are valid and ordered.
- International Polymarket fee metadata exists.

If any requirement is missing, the run is disabled with the exact reason. The
system never silently substitutes Polymarket US fees or fabricated depth.

## Trading Strategy Summary

For an event with `N >= 2` mutually exclusive and exhaustive outcomes, one YES
contract for every outcome forms a complete basket. Exactly one YES contract
should settle at `$1`; the others should settle at `$0`.

For each outcome, the detector:

1. Walks the Kalshi YES ask depth.
2. Walks the Polymarket US YES ask depth.
3. Applies the configured depth haircut.
4. Chooses the venue with the lower executable VWAP.

The basket is:

```text
basket cost = sum of the chosen executable YES VWAP for every outcome
```

The detector then adds fees and the configured buffer.

A trade can fire only when:

- The complete entry cost is below the threshold.
- Every outcome has a usable book.
- Books are fresh.
- Prices are within configured bounds.
- The requested size is executable through L2.
- The opportunity passes the momentum/stability requirements.

After a fire:

- All legs are submitted in parallel.
- Residual partial fills are retried while completion remains profitable.
- Excessive unhedged loss triggers an early unwind.
- A retry timeout forces an unwind of filled legs.
- Complete baskets enter position tracking.
- The exit monitor may place maker sells when the venues re-couple.
- Exit partials are rebalanced or reverted into a complete basket.
- Baskets that cannot exit safely remain held for settlement.

See [`docs/strategy.md`](docs/strategy.md) for the original detailed strategy
design.

## Process And Worker Model

FastAPI itself does not run the event strategy inside an HTTP request.

`RuntimeSupervisor` creates an isolated child process for each:

```text
approved event + mode
```

Examples:

```text
NBA Finals Winner + paper
NBA Finals Winner + live
Election Winner + paper
```

Paper and live state therefore remain separate even for the same event.

The browser may close without stopping those workers. Workers stop only when:

- The user explicitly stops the session.
- The application is shut down.
- A worker fails.
- The global emergency stop terminates live sessions.

## Persistence

### Control database

Stored at:

```text
live_trading/data/control/control.sqlite3
```

It contains:

- Catalog snapshots.
- Scan jobs.
- Candidate events.
- LLM judgments.
- Approved watchlist entries.
- Paper/live configurations.
- Worker state and heartbeats.
- Backtest jobs and result metadata.
- Presets.
- Activity records.
- Offline intervals.

### Execution journals

Each event runtime stores authoritative execution records beneath:

```text
live_trading/data/<event-slug>/
```

These records cover:

- Client order IDs.
- Order transitions.
- Fills.
- Open positions.
- Reconciliation state.
- Runtime display snapshots.
- Captured L2 data.

### Offline intervals

Application shutdown and startup boundaries are persisted. Charts should leave
those periods blank rather than connecting missing market data.

## UI Updates And Performance Isolation

The API provides one local WebSocket endpoint for scanner, worker, event,
balance, order, fill, PnL, alert, and backtest updates.

The current Next.js client uses TanStack Query to refresh REST resources every
three seconds. The WebSocket event hub is implemented on the backend but is not
yet wired into the React query cache.

Backend WebSocket queues and runtime display channels are bounded and lossy:

- Slow browser clients may miss intermediate display snapshots.
- The newest coherent state is retained.
- Market processing does not wait for React rendering.
- Order submission does not wait for WebSocket clients.

The execution journals and L2 captures remain the audit records.

## Safety Model

### Approval safety

- Automatic matching cannot authorize trading.
- LLM review cannot authorize trading.
- Human approval remains mandatory.
- A changed event mapping requires a new approval version.

### Live-order safety

- Live mode requires exact `LIVE` confirmation.
- The user sees balances, positions, orders, budget, and warnings first.
- Missing credentials block activation.
- Reconciliation failure blocks activation.
- A persistent emergency stop blocks new live workers.
- Explicit stop cancels known resting live orders through runtime shutdown.

### Data safety

- Secrets remain in ignored `.env` files.
- Secret values are never returned to the UI.
- Sequence gaps and reconnects invalidate captured datasets.
- Incomplete historical data cannot produce a backtest.
- Automated tests do not send real orders.

### Financial and venue caveats

- A theoretical complete basket removes event-direction risk, but operational
  risks remain: mismatched settlement rules, partial fills, venue failure,
  unavailable balances, API faults, fees, and queue position.
- International Polymarket backtests are not venue-faithful Polymarket US
  backtests.
- This software is engineering and research tooling, not financial advice.

## Configuration

Credentials belong in the repository root `.env`:

```text
KALSHI_API_KEY_ID=
KALSHI_PRIVATE_KEY_PATH=
KALSHI_PRIVATE_KEY_PEM=

POLYMARKET_US_KEY_ID=
POLYMARKET_US_SECRET_KEY=

OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
```

Use either `KALSHI_PRIVATE_KEY_PATH` or `KALSHI_PRIVATE_KEY_PEM`.

Important optional runtime settings:

```text
KALSHI_API_BASE=https://external-api.kalshi.com/trade-api/v2
KALSHI_WS_URL=wss://api.elections.kalshi.com/trade-api/ws/v2
POLYMARKET_US_GATEWAY_BASE=https://gateway.polymarket.us
POLYMARKET_US_API_BASE=https://api.polymarket.us
POLYMARKET_US_WS_URL=wss://api.polymarket.us/v1/ws/markets

DISCOVERY_REFRESH_SECONDS=600
STALE_AFTER_SECONDS=5
MAX_MATCHES=100
MIN_MATCH_CONFIDENCE=0.74
TRADE_SIZE=100
LIVE_TRADING_DATA_DIR=live_trading/data
```

Strategy presets and advanced settings can be managed from **Settings** in the
web application.

## Local Commands

### Start in the foreground

```powershell
.\start.ps1
```

The terminal remains attached. `Ctrl+C` runs the graceful stop path.

### Start detached

```powershell
.\start.ps1 -Detach
```

### Start without opening a browser

```powershell
.\start.ps1 -SkipBrowser
```

### Stop

```powershell
.\stop.ps1
```

### Direct Python diagnostics

```powershell
.\.venv\Scripts\python.exe -m live_trading doctor --categories sports --timeout-seconds 8
```

### Strategy benchmark

```powershell
.\.venv\Scripts\python.exe -m live_trading strategy-benchmark --iterations 10000
```

### Generate frontend API types

With the local application running:

```powershell
cd web
npm run generate:api
```

## Testing

Run Python tests:

```powershell
.\.venv\Scripts\python.exe -m pytest live_trading/tests backtesting/tests -q
```

Run the frontend safety tests:

```powershell
cd web
npm test
```

Build the production frontend:

```powershell
cd web
npm run build
```

Audit production dependencies:

```powershell
cd web
npm audit --omit=dev
```

Current verified baseline:

- 35 Python tests passing.
- Frontend live-activation safety test passing.
- Next.js production build passing.
- Production npm audit reporting zero vulnerabilities.
- Complete `start.ps1` and `stop.ps1` lifecycle passing.

## Current Limitations

- Automated event discovery requires working venue catalog APIs and OpenAI
  structured matching.
- The scanner's current-edge rank uses read-only L2 snapshots; continuous
  updates begin after an approved event has an active runtime.
- Live private fill handling currently includes REST reconciliation; richer
  private fill-stream integration should precede materially larger live size.
- Historical replay uses international Polymarket until enough complete
  Polymarket US L2 has been captured.
- Backtesting simulates the supplied strategy; it does not optimize parameters
  or select the best event automatically.
- Settlement retrieval remains dependent on available venue state and captured
  event records.

## Documentation Policy

`README.md` at the repository root is the only README and the authoritative
description of the current system.

Other Markdown files have narrower purposes:

- [`docs/strategy.md`](docs/strategy.md) preserves the original imported
  strategy design.
- `historical_testing/*.md` contains research results and methodology reports.

When architecture or operating behavior changes, update this README with the
code change so package-level documentation does not drift again.
