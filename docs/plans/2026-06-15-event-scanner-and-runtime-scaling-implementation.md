# Event Scanner And Runtime Scaling Implementation Plan

Date: 2026-06-15

Design: [2026-06-15-event-scanner-and-runtime-scaling-design.md](2026-06-15-event-scanner-and-runtime-scaling-design.md)

## Delivery Strategy

Deliver the scanner and runtime scaling work in two tracks:

1. Scanner extraction and expected deployable-profit ranking.
2. Shared market data, pooled strategy workers, and centralized live
   execution.

The scanner track ships first. The current per-event runtime remains available
until the pooled runtime passes parity, recovery, and performance tests.

## Phase 1: Establish Scanner Domain Models

Create `live_trading/src/live_trading/scanner/` and add typed models for:

- Normalized event identity and structured attributes.
- Candidate event pair.
- Outcome candidate and final assignment.
- Deterministic matching evidence.
- LLM judgment.
- Current market-state assessment.
- Historical evidence and evidence quality.
- Completion estimate and component values.
- Executable-profit curve by requested size.
- Final ranking and exclusion reasons.

Keep control API response compatibility by translating scanner models into the
existing `control.schemas.Candidate` shape initially.

Tests:

- Model validation and serialization.
- Monetary values preserve decimal precision.
- Missing evidence is represented as unknown or neutral, not zero.

## Phase 2: Extract Catalog And Scanner Orchestration

Move catalog refresh and scan-job orchestration from
`control/scanner.py` into:

- `scanner/catalogs.py`
- `scanner/service.py`
- `scanner/repository.py`

Retain a thin compatibility adapter in `control/scanner.py` until FastAPI is
updated to depend directly on `ScannerService`.

Catalog behavior:

- Fetch fresh venue catalogs before each explicit scan.
- Persist complete normalized snapshots and per-venue errors.
- Detect truncated or partial responses.
- Preserve raw venue fields needed for later structured matching.

Tests:

- Refresh-before-scan.
- One-venue failure.
- Partial and truncated catalog disclosure.
- Repository round trips.

## Phase 3: Event-Level Candidate Generation

Implement `scanner/candidate_generation.py`.

Create broad deterministic blocks using:

- Parent event identifiers.
- League and normalized category.
- Scheduled event date and settlement deadline.
- Market type.
- Participants and aliases.
- Structured thresholds, rounds, locations, offices, and tournament stages.

Add an alias registry for sports teams and common competition abbreviations.
Start with data represented in the research fixtures, including NBA city,
nickname, and abbreviation forms.

Do not globally deduplicate contracts during candidate generation. Retain the
top bounded set of plausible event pairs for later assignment.

Tests:

- Philadelphia/Dallas matches 76ers/Mavericks.
- Team abbreviations and city names.
- Same participants on different dates remain separate.
- Moneyline does not match spread or total.
- Regulation-only soccer does not silently match extra-time settlement.

## Phase 4: Event And Outcome Matching

Implement:

- `scanner/event_matching.py`
- `scanner/outcome_matching.py`

Flow:

1. Score structured event identity.
2. Reject deterministic hard conflicts.
3. Send only plausible bounded candidates to strict structured LLM review.
4. Build outcome-score matrices for accepted event pairs.
5. Solve one-to-one outcome assignment.
6. Verify all outcomes are represented exactly once.
7. Record rejected and unresolved assignments with reasons.

The existing manual approval requirement remains unchanged.

Tests:

- Binary events.
- Multi-outcome events with 2, 10, and 40 outcomes.
- Reordered outcomes.
- Duplicate labels.
- Missing outcomes.
- Non-exhaustive "other" handling.
- LLM unavailable, malformed, contradictory, and rejecting responses.

## Phase 5: Current L2 Market Assessment

Implement `scanner/market_state.py`.

For each complete candidate:

- Fetch or read one coherent current snapshot for every required book.
- Classify event state.
- Evaluate multiple configured basket sizes.
- Reuse the shared strategy detector and depth walker.
- Record net edge, executable contracts, executable dollars, slippage,
  freshness, selected venues, and binding legs.

Recommended initial size grid:

```text
1, 5, 10, 25, 50, 100, 250, configured maximum
```

Select the size with the highest positive executable dollar profit that stays
within configured scanner and venue constraints.

Tests:

- Deeper size can earn more dollars despite lower per-contract edge.
- Thin headline edge does not outrank a deeper deployable opportunity.
- Fees and buffer can make a gross opportunity ineligible.
- Missing or stale leg excludes the candidate.
- Multi-level L2 is walked correctly.

## Phase 6: Historical Evidence Resolver

Implement `scanner/historical.py`.

Read structured report artifacts rather than parsing reader-facing Markdown.
Normalize evidence into:

- Category.
- League or competition.
- Market type.
- Competition phase.
- Timing or lifecycle phase.
- Outcome-count range.
- Evidence source.
- Sample size.
- Positive-window duration where available.
- Executable profit and completion statistics where available.

Use evidence-quality shrinkage:

- Strong PMXT or captured L2 evidence may adjust completion materially.
- Proxy-only evidence receives a small bounded adjustment.
- Small samples shrink toward neutral.
- Missing scenarios remain neutral.

Correct the research pipeline if required so generated structured artifacts
carry the same scenario metadata shown in the updated Markdown reports.

Tests:

- NBA research resolves to NBA rather than a generic fallback.
- In-play and pregame evidence remain distinct.
- Proxy-only F1, golf, and MLB evidence is labeled unvalidated.
- Elections PMXT evidence is recognized as L2 validated.
- Zero recovered pairs means insufficient matching coverage, not zero return.

## Phase 7: Expected Deployable-Profit Ranking

Implement `scanner/ranking.py`.

Calculate:

```text
executable_profit = selected_size * net_edge_per_basket

completion_estimate = bounded_product_or_logit(
    mapping_quality,
    freshness,
    balanced_depth,
    slippage_quality,
    leg_count_factor,
    event_state_factor,
    historical_execution_factor
)

expected_deployable_profit =
    executable_profit
    * completion_estimate
    * historical_quality_multiplier
```

Requirements:

- A non-positive executable profit cannot rank as profitable.
- Historical multipliers are bounded.
- Mapping confidence cannot compensate for missing books.
- Every component is returned to the UI.
- Sort primarily by expected deployable dollars.

Calibrate constants from deterministic fixtures first. Do not train or claim a
predictive model without sufficient labeled execution data.

Tests:

- Ranking order across edge, size, and completion tradeoffs.
- Missing history stays neutral.
- High proxy-only category score cannot overpower current L2.
- More outcomes apply a conservative completion penalty.
- Identical economics rank by fresher and better-balanced books.

## Phase 8: Control API And UI Integration

Update FastAPI scan routes to use `ScannerService`.

Expose:

- Expected deployable profit.
- Selected size.
- Net edge per basket.
- Completion estimate.
- Historical multiplier.
- Evidence quality and sample size.
- Event-state classification.
- Exclusion reasons.
- Full ranking component breakdown.

Update Discover UI labels to avoid presenting estimates as guaranteed profit.
Keep approval separate from ranking.

Tests:

- API contract tests.
- Scan progress and partial failure.
- Candidate detail rendering.
- Sorting and filtering by deployable profit.
- Incomplete candidates remain reviewable but cannot be approved.

## Phase 9: Shared Market-Data Gateway

Create a market-data subsystem with:

```text
live_trading/src/live_trading/market_data/
  gateway.py
  subscriptions.py
  cache.py
  protocol.py
  process.py
```

Responsibilities:

- Deduplicate subscriptions across event and mode consumers.
- Shard venue subscriptions according to venue limits.
- Normalize snapshots and deltas.
- Maintain current coherent books.
- Track sequence integrity and reconnects.
- Publish bounded affected-market notifications.
- Provide snapshot access for scanners and strategy workers.

The first implementation may use local IPC. Define the protocol independently
so transport can change without changing strategy code.

Tests:

- Subscription reference counting.
- Paper/live consumers share one public subscription.
- Snapshot recovery after sequence gaps.
- Bounded queue coalescing.
- Durable integrity messages are never silently dropped.

## Phase 10: Strategy Worker Pool

Create:

```text
live_trading/src/live_trading/workers/
  pool.py
  worker.py
  assignment.py
  protocol.py
```

Run two bounded worker shards by default and make the count configurable.
The implemented shards are asyncio workers rather than OS processes because
the 40-event benchmark remained below 1 millisecond p99 for affected-event
evaluation. Keep the assignment and queue boundaries transport-independent so
process isolation can be introduced later if profiling justifies it.

Each worker:

- Owns assigned event/mode strategy state.
- Reads shared normalized book updates.
- Reconstructs per-event strategy books.
- Reevaluates only events affected by the changed market.
- Maintains independent detector, momentum, budget, position, and exit state.
- Emits paper actions locally and live order intents centrally.

Use stable hash-based assignment with explicit migration support.

Tests:

- Deterministic assignment.
- Worker restart and reassignment.
- No cross-event detector state.
- Paper/live isolation.
- Only affected events reevaluate.

## Phase 11: Central Live Execution And Risk Service

Create:

```text
live_trading/src/live_trading/execution_service/
  service.py
  risk.py
  reconciliation.py
  protocol.py
  process.py
```

Move authenticated live account operations behind this boundary.

Before accepting an intent:

- Verify approved mapping and strategy versions.
- Verify worker ownership.
- Verify global and event emergency states.
- Verify per-event remaining budget.
- Verify venue balances and aggregate reserved funds.
- Assign or validate idempotent client order IDs.

Route fills and order state back to the owning worker and persist them before
acknowledging completion.

Tests:

- Concurrent events cannot overspend the account.
- Duplicate intents remain idempotent.
- Emergency stop rejects new entries and cancels resting orders.
- Restart reconciliation.
- Journal divergence pauses affected live events.

## Phase 12: Supervisor Migration

Extend `RuntimeSupervisor` to manage:

- Market-data gateway processes.
- Strategy worker pool.
- Live execution service.
- Scanner health.

Add a feature flag:

```text
RUNTIME_ARCHITECTURE=legacy|pooled
```

Keep `legacy` available until pooled parity is established. New paper sessions
canary on pooled mode before live sessions.

Tests:

- Graceful startup and shutdown ordering.
- Child health and heartbeat reporting.
- Gateway failure pauses dependent entries.
- Worker failure preserves execution service and other workers.
- Browser closure has no effect on workers.

## Phase 13: Performance And Parity Gates

Extend the benchmark to model:

- 40 events.
- 2 to 40 outcomes.
- Shared feeds.
- Bursty updates.
- Simultaneous paper and live modes.
- Full current detector calculations.

Required gates:

- Receipt-to-evaluation p99 under 10 ms.
- Signal-to-order-intent p99 under 25 ms.
- No dropped durable messages.
- Bounded memory.
- No duplicate venue subscriptions.

Run deterministic legacy-versus-pooled parity fixtures. Given identical
ordered books, both paths must produce the same basket evaluations and fire
decisions.

## Phase 14: Default Cutover

After paper soak testing and mocked-live reconciliation tests:

1. Make pooled mode the default.
2. Retain legacy mode for one release or migration interval.
3. Remove per-event venue subscriptions only after operational parity.
4. Update `docs/architecture.md` and the root `README.md`.
5. Record benchmark results and known capacity limits.

## Suggested Commit Sequence

1. Add scanner models and compatibility adapter.
2. Extract catalogs and scanner service.
3. Add event-level candidate generation.
4. Add complete outcome assignment and LLM review.
5. Add current L2 size-curve assessment.
6. Add historical evidence resolver.
7. Add expected deployable-profit ranking.
8. Integrate scanner API and UI.
9. Add shared market-data gateway.
10. Add pooled strategy workers.
11. Add centralized live execution and risk.
12. Add supervisor feature flag and parity tests.
13. Add 40-event benchmark and cutover documentation.
