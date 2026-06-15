# Local Application Architecture

## Purpose

The local application makes event selection, review, paper trading, live trading,
and historical replay available from one browser interface. Python remains the
only owner of trading decisions and execution behavior.

## Design Decisions

### Next.js is the presentation layer

The existing NiceGUI dashboard was useful for runtime inspection, but it made
discovery, approval, and multi-mode workflows difficult to organize. Next.js
provides a durable application shell, typed components, responsive tables, and
client-side query caching. It never calculates fills, prices, or strategy
decisions.

Consequence: Node.js is required locally and `start.ps1` builds the web
application when its package metadata changes.

### FastAPI is the control plane

FastAPI wraps the existing scanner, strategy runtime, execution journals, and
backtester. Pydantic models define requests and responses, and the generated
OpenAPI document is available at `/openapi.json`.

Consequence: UI and trading failures remain isolated. Closing the browser does
not stop workers.

### SQLite stores control state

`live_trading/data/control/control.sqlite3` stores catalogs, scan jobs,
candidates, approvals, mode configurations, worker state, presets, offline
intervals, and backtest metadata. Existing execution SQLite journals remain
authoritative for orders, fills, positions, and reconciliation.

Consequence: no database server is required. Monetary execution records retain
the existing decimal-string representation.

### Approved events are versioned manifests

Automatic matching combines deterministic identifier, date, outcome-count, and
rule checks with strict LLM settlement review. The LLM may pass or reject a
mapping but cannot approve it. A user must confirm complete, mutually exclusive,
and exhaustive coverage plus settlement review.

Approval writes an immutable YAML snapshot under
`live_trading/data/control/approved_events/`. Runtime workers consume that
snapshot through the existing manifest loader.

Consequence: rule or mapping changes create a new approval version instead of
silently altering a running event.

### One worker owns one event and mode

The supervisor launches an isolated Python process for each `event + mode`.
Paper and live sessions therefore cannot share balances, positions, or order
state. The same approved event may run in both modes.

Consequence: process startup costs are accepted in exchange for fault and state
isolation. Shared market-data subscriptions can be added later behind the
existing runtime boundary.

### Live recovery is conservative

Live activation requires an exact `LIVE` confirmation and a read-only
reconciliation preview. Explicit user stops disable auto-resume. Application
shutdown preserves active live configuration so startup may attempt recovery,
but the runtime still reconciles venue balances, positions, and local journals
before trading.

Consequence: missing credentials or failed reconciliation leave activation
blocked instead of creating an uncertain live state.

### UI traffic is lossy by design

The runtime writes bounded snapshots and the FastAPI WebSocket uses bounded
per-client queues. When a UI client is slow, old display updates are discarded.
Market processing and order submission never await browser rendering.

Consequence: charts show the latest coherent state rather than every tick.
Execution journals and L2 captures remain the audit source.

### International and US Polymarket remain separate

Live and paper workers use Polymarket US. Historical replay uses PMXT Kalshi and
international Polymarket because that is the currently available L2 archive.
Backtests reject missing contract IDs, fee fields, or overlapping coverage and
never substitute US assumptions.

Consequence: historical results are evidence for the strategy mechanics, not a
venue-faithful claim about Polymarket US fills.

## Local Lifecycle

Run:

```powershell
.\start.ps1
```

The script creates `.venv`, installs editable Python packages, installs and
builds the Next.js app when needed, starts FastAPI and Next.js, waits for health
checks, records process IDs under `.app/`, and opens
`http://127.0.0.1:3000`.

The browser app listens on port `3000`; the local-only control API listens on
port `8765`.

Node 22 LTS is the preferred web runtime. Node 21 currently builds the
application but is outside the supported engine range of several development
dependencies.

Stop:

```powershell
.\stop.ps1
```

The stop path asks FastAPI to stop workers, cancel known resting orders, stop
paper sessions, and persist the offline boundary before terminating any
remaining recorded process after a timeout.

## Safety Boundaries

- CI and automated tests never use production order endpoints.
- Missing OpenAI access blocks new event approvals.
- Missing or incomplete L2 history blocks a backtest with explicit reasons.
- Paper sessions do not resume after application shutdown.
- A persistent global emergency stop blocks new live workers.
- The UI never displays secret values from `.env`.
