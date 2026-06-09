# Trading and Backtesting Architecture

## Scope

`live_trading` is the production application and owns the shared strategy core.
`trade_system` remains reference code and is not imported at runtime.
`backtesting` imports the strategy types and detector from `live_trading`.

Live and paper execution use Kalshi and Polymarket US. Historical replay uses
PMXT Kalshi and international Polymarket data. Results always label that venue
split because historical international behavior is not proof of Polymarket US
fill behavior.

## Decisions

### Reviewed event manifests

Every event is represented as two or more mutually exclusive, collectively
exhaustive outcomes. Trading requires `approved`, `exhaustive`, and
`settlement_reviewed` to be true. Manual manifests were chosen over automatic
matching because a title match cannot prove equal settlement rules.

### One shared strategy core

The multi-outcome detector, depth walker, fees, sizing, retry/unwind behavior,
position accounting, early maker exit, and settlement PnL were copied into
`live_trading.strategy`. Copying once avoids making production code depend on
the reference package while allowing replay to import exactly the live types.

### Full L2 and per-outcome venue choice

For each outcome, the detector walks the full YES ask ladder on both venues and
chooses the lower executable VWAP. It rejects incomplete, stale, extreme-price,
or unstable baskets. Top-of-book comparison was rejected because it
overstates fillable size and understates slippage.

### Execution isolation

Monitor mode has no order client activity. Paper mode uses the execution engine
against immutable public books; simulated fills update only private cash and
position state. Live mode swaps in authenticated venue adapters. The execution
journal stores client IDs and order transitions in SQLite for restart
reconciliation.

### Capital and confirmation

The CLI capital value is the maximum aggregate commitment for a basket. Live
startup displays the event, balances, capital limit, and unresolved local
orders, then requires the exact phrase `LIVE`. This makes a mode typo
insufficient to place real orders.

### Capture validity

Selected Polymarket US and Kalshi books are appended to JSONL. Queue overflow,
sequence gaps, or reconnects mark the dataset invalid. Retaining a visibly
invalid capture was chosen over silently presenting partial data as backtest
quality.

### Deterministic historical time

PMXT rows are merged by `timestamp_received`. The detector runs every 100 ms
against a virtual clock. The shared momentum tracker accepts the evaluation
timestamp, so results do not depend on workstation speed.

### Fill assumptions

Each run reports 50, 250, 500, and 1,000 ms order-arrival delays. The main
`maker` estimate consumes displayed executable depth at arrival. The stricter
`price_passes` estimate also requires the market to move through the signaled
price. These are estimates, not queue-position reconstruction.

PMXT `fee_rate_bps` is required for international Polymarket replay. The
backtester refuses missing fee metadata rather than substituting Polymarket US
fees. Every simulation starts with `$1,000`; money gained is `ending cash -
$1,000`.

### Dashboard isolation

The NiceGUI process reads a bounded, lossy JSON state channel. Market-data and
order tasks never await Plotly rendering. The dashboard includes an emergency
stop file watched by the runtime; activation blocks entries and cancels known
resting orders.

## Consequences and Limits

- Venue funding is separate in reality; paper mode divides starting capital
  evenly and can reject an otherwise affordable basket when one venue wallet
  is short.
- REST polling backs live resting-order reconciliation. Private fill streams
  should be added before increasing live size.
- PMXT replay can validate the strategy against international Polymarket, but
  only newly captured Polymarket US L2 can provide venue-faithful US replay.
- Event discovery and parameter optimization remain out of scope.
