# Event Scanner And Runtime Scaling Design

Date: 2026-06-15

## Purpose

Build a scanner that finds equivalent complete events across Kalshi and
Polymarket US and ranks them by expected deployable dollar profit for the
existing multi-outcome basket strategy.

Support approximately 30 to 40 simultaneously monitored events without
opening a separate pair of venue market-data connections for every event and
mode.

## Design Decisions

### Scanner objective

The scanner optimizes expected deployable dollar profit, not raw edge, raw
ROI, or historical category rank.

For an eligible event:

```text
expected deployable profit
    = current executable profit
    * estimated completion probability
    * historical quality multiplier
```

Current executable profit is calculated from a single instantaneous L2
snapshot:

```text
current executable profit
    = profitable executable contracts
    * net edge per complete basket
```

The shared strategy code remains authoritative for full-depth walking, venue
selection, fees, slippage buffer, and achievable size.

### Instantaneous scan

A scan does not wait for a live observation period. It fetches current books
and returns results immediately after matching and validation.

Historical L2 and price-proxy evidence provide context about persistence and
execution quality. They do not replace current executable prices.

### Historical evidence

Historical evidence is matched to the closest available subscenario using
attributes such as:

- Category and league.
- Market type.
- Pregame, in-play, lifecycle, or near-settlement state.
- Competition or tournament phase.
- Number of outcomes.
- Typical displayed depth and profitable-window duration.

Evidence weights follow their quality:

1. Archived synchronized L2 replay.
2. Venue-faithful captured L2.
3. Official price-history proxy.
4. No applicable history.

Missing evidence is neutral. It is never interpreted as evidence that a
category or event has no opportunities. Proxy-only evidence has a bounded
effect and cannot override a currently unprofitable basket.

### Event matching

Matching happens at the event level before final outcome assignment.

Candidate generation uses broad deterministic blocking:

- Venue identifiers and parent-event identifiers.
- Event dates and settlement deadlines.
- Category, league, and market type.
- Normalized participants, teams, people, and aliases.
- Structured thresholds, rounds, offices, locations, and other available
  event attributes.

The matcher retains multiple plausible candidates rather than greedily
discarding all but the highest text-similarity pair.

Strict structured LLM review evaluates plausible event pairs and outcome
equivalence. Deterministic checks then require complete, mutually exclusive,
and exhaustive outcome coverage. The LLM may validate mappings but cannot
approve an event for trading.

### Candidate eligibility

An event is rankable only when:

- Both venue events are plausibly equivalent.
- Every required outcome is mapped exactly once.
- The event contains at least two outcomes.
- Current books exist for every mapped outcome.
- Books are sufficiently fresh.
- Settlement-rule review has no blocking conflict.

An event with incomplete data remains visible with an exact exclusion reason,
but it is not presented as a profitable candidate.

### Completion probability

The completion estimate is a conservative bounded value derived from:

- Mapping confidence.
- Book freshness.
- Balanced fillable quantity across all legs.
- Slippage required to reach the proposed size.
- Number of basket legs.
- Current event state.
- Historical L2 opportunity duration where available.
- Historical fill or completion evidence where available.

The estimate is an execution-quality ranking feature, not a claim of a known
statistical probability. The UI must display its components and evidence
quality.

### Live and in-play events

In-play markets are not automatically preferred or rejected. Their current
executable profit may be high, but completion probability is reduced when the
closest historical evidence shows short windows or poor paired execution.

Pregame and long-duration markets may receive a higher completion estimate
when their books are deep and their historical opportunities persisted
longer.

## Scanner Package

Create a distinct backend subsystem:

```text
live_trading/src/live_trading/scanner/
  __init__.py
  service.py
  catalogs.py
  candidate_generation.py
  event_matching.py
  outcome_matching.py
  market_state.py
  historical.py
  ranking.py
  models.py
  repository.py
```

Responsibilities:

| Module | Responsibility |
| --- | --- |
| `service.py` | Orchestrate scans and publish progress |
| `catalogs.py` | Fetch, cache, and normalize complete venue catalogs |
| `candidate_generation.py` | Produce broad plausible event pairs |
| `event_matching.py` | Deterministic and LLM event-level equivalence |
| `outcome_matching.py` | Assign and validate complete outcome mappings |
| `market_state.py` | Read current shared L2 snapshots and event state |
| `historical.py` | Resolve applicable historical subscenario evidence |
| `ranking.py` | Calculate executable and expected deployable profit |
| `models.py` | Scanner-specific typed domain models |
| `repository.py` | Persist jobs, evidence, candidates, and exclusions |

FastAPI routes remain in `control/` and delegate scanner work to
`ScannerService`. The scanner never places orders.

## Runtime Scaling

### Current limitation

The current supervisor starts one subprocess for every `event + mode`. Each
subprocess creates its own Kalshi and Polymarket US streams. At 40 events with
paper and live enabled, this can create 80 processes and many duplicate venue
subscriptions.

### Target process model

Use:

- One FastAPI control process.
- One scanner service.
- One shared Kalshi market-data gateway.
- One shared Polymarket US market-data gateway.
- Two to four strategy worker processes.
- One centralized live execution and account-risk coordinator.
- Independent paper execution state inside the assigned strategy worker.

Venue gateways may open multiple WebSocket shards when venue subscription
limits require them. A market is subscribed once per venue even when several
events or modes consume it.

### Shared market-data flow

```text
Kalshi WebSocket shards --------+
                                +--> normalized book cache
Polymarket WebSocket shards ----+             |
                                              v
                                  bounded update channels
                                              |
                              +---------------+---------------+
                              |                               |
                     strategy worker 1                strategy worker N
                              |                               |
                         event states                    event states
                              +---------------+---------------+
                                              |
                                  execution and risk service
```

Every normalized update contains a venue, market identifier, sequence,
exchange timestamp when available, receive timestamp, and coherent book
snapshot or delta.

Queues are bounded. Superseded display and book snapshots may be coalesced,
but order, fill, risk, sequence-gap, and emergency-stop messages are durable
or explicitly acknowledged.

### Worker isolation

Events are assigned to worker shards by a stable event identifier. Each
`event + mode` retains independent:

- Detector and momentum state.
- Budget.
- Position state.
- Orders and fills.
- Exit monitor.
- Journal identity.
- Emergency and pause state.

Paper and live modes may consume the same public books but never share
positions, balances, or fills.

### Centralized live execution and risk

Live venue credentials, account balances, resting-order reconciliation, and
aggregate exposure checks belong to a single execution boundary per account.

Strategy workers submit typed order intents. The live execution service:

- Rechecks emergency-stop and configuration versions.
- Enforces per-event budgets.
- Reports aggregate allocations and available venue balances.
- Assigns idempotent client order IDs.
- Submits and cancels venue orders.
- Routes fills and order transitions to the owning event and mode.
- Reconciles venue state after restart.

This prevents independent workers from racing against the same account
balance or global emergency state.

## Performance Position

Python remains the implementation language for the scanner, strategy workers,
venue gateways, and execution service.

### Implementation amendment

The implemented worker pool uses bounded asyncio shards in the FastAPI
process, while market-data subscriptions and every event/mode state remain
logically isolated. A local benchmark covering 40 events with 2 to 40
outcomes measured affected-event strategy evaluation below 1 millisecond p99
against the 10 millisecond target.

Separate OS strategy processes were therefore deferred. They would add IPC,
serialization, recovery, and order-routing complexity without addressing a
measured bottleneck. Reconsider process separation only if production
profiling exceeds the documented latency, CPU, or event-loop-lag limits.

Thirty to forty events are not enough to justify a C++ rewrite. Expected
bottlenecks are duplicate network subscriptions, venue limits, persistence,
and order coordination rather than arithmetic.

Native code should be considered only after profiling identifies a narrow
hotspot that cannot meet a measured latency target. A depth-walking kernel
could later be replaced behind the existing Python interface without
rewriting the application.

## Performance Requirements

Add a representative benchmark with:

- 40 events.
- Between 2 and 40 outcomes per event.
- Both venue feeds.
- Bursty L2 updates.
- Concurrent paper and live configurations.
- Current full-depth basket evaluation.

Initial local targets:

- Receipt-to-affected-event evaluation p99 below 10 milliseconds.
- Signal-to-live-order-intent dispatch p99 below 25 milliseconds.
- No dropped durable order, fill, risk, or sequence-gap messages.
- Market-data gaps explicitly invalidate affected state.
- Memory remains bounded during sustained burst traffic.

Only affected events should be reevaluated after a book update. The system
must not reevaluate all events on every market message.

## Failure Handling

- A venue sequence gap marks affected books invalid until a fresh snapshot is
  applied.
- A gateway reconnect pauses entries that depend on its books.
- A worker crash pauses its assigned live configurations until state is
  reconciled.
- An execution-service failure blocks new live entries globally.
- Scanner or historical-evidence failure cannot interrupt active trading.
- Slow UI clients cannot backpressure market processing.
- The global emergency stop is persisted and checked by both workers and the
  live execution service.

## Testing

Add tests for:

- Sports and non-sports alias-based event candidate generation.
- NBA event matching with city names, team names, and abbreviations.
- Event-level matching before outcome assignment.
- Multi-outcome completeness and duplicate detection.
- Missing historical evidence remaining neutral.
- Proxy-only evidence receiving bounded weight.
- Expected deployable-profit ranking.
- In-play completion penalties driven by evidence rather than category alone.
- Shared subscription deduplication.
- Worker shard assignment and restart.
- Paper/live state isolation with shared books.
- Central live budget and aggregate-balance enforcement.
- Sequence gaps, reconnects, queue pressure, and worker failure.
- Forty-event multi-outcome latency benchmarks.

## Migration

1. Extract the current scanner behavior into the new package without changing
   API contracts.
2. Replace greedy pair matching with event-level candidate generation and
   complete outcome assignment.
3. Add historical evidence resolution and expected deployable-profit ranking.
4. Introduce shared market-data gateways behind a snapshot/update interface.
5. Move event runtimes into a small worker pool.
6. Route live order intents through the centralized execution service.
7. Retire per-event venue connections after parity, recovery, and latency
   tests pass.

The existing per-event runtime remains available during migration so paper
and live workflows are not replaced in one unverified step.
