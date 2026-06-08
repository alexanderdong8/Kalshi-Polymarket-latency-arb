# Kalshi / Polymarket Annual Scenario Research

This folder contains a resumable research pipeline for studying cross-venue prediction-market arbitrage. It compares Kalshi with international Polymarket, and it describes the separate Polymarket US public catalog without making unsupported historical-profit claims.

The central trade pattern is:

```text
buy YES on one venue + buy NO on the other venue < $1.00
```

If both contracts settle on exactly the same binary outcome, one leg pays `$1.00`. A pair bought for `$0.94` has a `$0.06` gross edge before fees and slippage.

This is not a claim that every visible price difference can be traded. The script separates broad historical screening from stronger archived-order-book evidence so the reports say what the data can and cannot prove.

Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)

## Evidence Layers

The study keeps three evidence layers separate:

| Layer | Requested coverage | What it can establish |
|---|---|---|
| International official APIs | `2025-05-31T00:00:00Z` to `2026-05-31T00:00:00Z` | Historical price-proxy signals under modeled pair slippage |
| PMXT public raw archive | Dynamically discovered synchronized hours | Archived L2 depth, VWAP slippage, short-lived windows, and conservative paired exits |
| Polymarket US public gateway | Retained public catalog metadata | Scenario inventory only, not historical profitability |

The live archive inventory verified on `2026-05-31` contains `259` synchronized raw-Parquet hours from `2026-05-14T14` through `2026-05-25T08`. The PMXT replay is resumable because the raw overlap is large.

## Current Completeness Status

The full Kalshi historical cursor traversal has been run for the requested annual window. It fetched `5,139,000` historical rows across `5,139` pages and reached `2025-05-29T18:03:18.736056+00:00`, which is older than the requested `2025-05-31T00:00:00Z` start.

That does **not** mean the complete two-venue profitability study is exhaustive. The international Polymarket Gamma public catalog still exceeded an explicit `100,000`-row retained cap in each month from `2026-01` through `2026-05`. The current Kalshi May catalog slice also exceeded its explicit cap. Those capped slices are listed in [reports/annual_official_catalog_coverage.md](reports/annual_official_catalog_coverage.md).

In plain English: the script walked the full requested Kalshi historical range, but public catalog scale still limits the combined Kalshi-versus-Polymarket match screen. The Markdown reports must describe capped results as retained screens, not as proof that every possible profitable pair was tested.

## Run The Research

From `historical_testing/`:

```powershell
python -m arb_study.cli run-research --start 2025-05-31T00:00:00Z --end 2026-05-31T00:00:00Z --resume
```

The CLI resumes by default. Use `--fresh` only when intentionally discarding checkpoints. The main command:

- Crawls the international Polymarket Gamma catalog and CLOB price history.
- Crawls Kalshi historical markets and candlesticks until pagination finishes or a visible page budget is reached.
- Discovers PMXT archive pages dynamically, validates raw Parquet objects, and checkpoints each replayed hour.
- Crawls Polymarket US events, flat markets, sports configuration, and selected terminal summaries with page checkpoints.
- Writes JSON, CSV, Markdown reports, and a shared coverage manifest.

By default, the annual price-history stage uses a stratified cap of `25` strict candidate pairs per month. “Stratified” means it rotates through scenario groups rather than taking only the first titles returned by an API. This keeps the broad screen practical while preserving variety. Use `--annual-proxy-markets-per-month 0` only when intentionally scanning every retained strict pair; capped public catalog slices still mean that such a run is exhaustive over the retained match index, not exhaustive over every market that may exist upstream.

To run the intentionally broad retained-catalog study requested for the final annual report:

```powershell
python -m arb_study.cli normalize-annual-cache --cache data/annual_official_catalog_cache.json --out data/annual_official_matches_strict.json --start 2025-05-31T00:00:00Z --end 2026-05-31T00:00:00Z
python -m arb_study.cli annual-proxy-report --matches data/annual_official_matches_strict.json --start 2025-05-31T00:00:00Z --end 2026-05-31T00:00:00Z --checkpoint-dir reports/annual_proxy_checkpoints --max-markets-per-month 0 --workers 6
python -m arb_study.cli render-research-reports
```

The first command rebuilds the strict retained-pair index and its category census. The second command resumes completed phase requests from `reports/annual_proxy_checkpoints/`. The third command rewrites the reader-facing Markdown and CSV files from the persisted results.

## Exactly What The Script Does

1. It asks the official Kalshi historical endpoint for market contracts page by page until the requested date range is reached. Kalshi's public historical-market endpoint uses a cursor, which is similar to a bookmark for the next page. It does not provide a close-date filter for skipping directly to a month.
2. It retains the requested scenario universe and recognizable additional sports or public-event coverage. It excludes only repetitive high-frequency crypto and intraday index threshold families from the retained research index. The coverage report separately records rows fetched, rows retained, and rows deliberately excluded.
3. It asks international Polymarket for historical market metadata and price histories. Metadata is descriptive information such as a market title, identifier, and close date.
4. It compares Kalshi and Polymarket contract wording conservatively. A candidate is rejected when the event, line, threshold, date, round, district, cancellation treatment, payout behavior, or settlement wording appears different.
5. For the rolling-year layer, it checks whether historical prices suggest a positive profit after fees and modeled pair slippage of `1`, `2`, or `5` cents. This is called a **price-history proxy** because historical Polymarket book depth is not publicly available from the official API.
6. For the PMXT layer, it discovers synchronized archived hours, verifies the raw archive files, rebuilds multi-level order books, and calculates whether both legs had enough visible quantity for orders of `1`, `5`, `10`, `25`, `50`, `100`, and `250` contracts.
7. It searches for an optional early sale of both legs. The sale is used only when it safely beats the locked hold-to-settlement result by at least `$0.0075` per contract after costs.
8. It writes reader-facing Markdown reports plus inspectable JSON and CSV artifacts. The Markdown reports show profitable examples directly; a category without a positive retained result says `No profitable example found.`

## What “Every Retained Market” Means

The broad run has two stages:

1. **Catalog audit and matching.** Every retained market row enters the catalog index. The script compares Kalshi and international Polymarket metadata to recover pairs that appear to describe the same real-world binary outcome.
2. **Historical price scan.** Every recovered strict pair enters the uncapped historical-price scanner. A Kalshi-only market or Polymarket-only market cannot produce cross-venue arbitrage arithmetic because the opposite venue has no equivalent contract to pair with it.

This distinction matters. “No strict equivalent pair recovered” does not mean a category was proven unprofitable. It means the retained public catalogs did not provide a sufficiently clear Kalshi-versus-Polymarket pair for the scanner to evaluate.

The annual report uses a coverage funnel for each category:

| Funnel stage | Plain-English meaning |
|---|---|
| Retained catalog rows | Market records kept after the documented high-frequency-series exclusions |
| Strict equivalent pairs | Kalshi and Polymarket contracts that appear to describe the same event and settlement meaning |
| Selected pairs | Strict pairs sent into the price scanner; this equals all retained strict pairs in an uncapped run |
| Pairs with aligned snapshots | Pairs where both venues supplied historical prices that could be compared at the same timestamp |
| Positive proxy windows | Consecutive timestamp ranges where estimated profit remained above zero after modeled costs |

Useful bounded runs:

```powershell
python -m arb_study.cli archive-hours --out reports/pmxt_archive_inventory.json
python -m arb_study.cli l2-replay --matches data/cluster_matches.json --checkpoint-dir reports/pmxt_l2_checkpoints --out reports/pmxt_l2_replay.json --max-hours 1
python -m arb_study.cli public-us-catalog --cache data/polymarket_us_public_catalog.json --out-json reports/polymarket_us_public_catalog_summary.json --out-md POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md --max-pages 1
pytest -q
```

## Scenario Coverage

The reports give full sections to:

`NBA`, `MLB`, `golf`, `ATP`, `WTA`, `eSports`, `IPL`, `WNBA`, `NHL`, `ITF men`, `ITF women`, `UFC`, `FIFA World Cup`, `politics`, `weather`, `MLS`, `elections`, `culture`, and `F1`.

Markets outside that list appear under **Additional Discovered Scenario Coverage**. This catches meaningful categories such as NFL, college basketball, EPL, UCL, and other soccer leagues instead of silently dropping them.

Applicable sports are split by pregame versus in-play timing when retained public metadata exposes a scheduled start, then compared by competition phase, participant or team, and market type. Non-sports use lifecycle buckets based on time remaining until resolution.

For sports, **pregame** means before the scheduled contest starts. **In-play** means after the scheduled start while the contest remains active. The annual analysis does not open new positions after the final result.

Some sports records expose a close time but do not expose a scheduled contest start. The scanner still inspects their final `24` hours at five-minute intervals, labels that period `sports_event_start_unavailable_final_24h`, and does not pretend those observations are definitely pregame or in-play.

Markets such as an oil-price deadline do not have a game-like live period. They use lifecycle buckets instead: more than `30` days remaining, `30` days to `24` hours remaining, and the final `24` hours.

## Strict Matching

A cross-venue pair is only a candidate when the contracts agree on event, outcome meaning, line, threshold, date, cutoff, payout behavior, and settlement treatment. The matcher rejects mismatched spreads, totals, competition rounds, districts, explicit dates, cancellation treatment, and split payouts.

Automatic matches remain **strict candidates**, not trading authorization. Resolution-rule review is still required before a row is promoted to a trade example.

The strict gate also rejects deceptively similar winner markets. A contract for `LIV Golf Andalucia` is not equivalent to a contract for `LIV Golf DC`, even if the same golfer appears in both titles. Likewise, a `Nick Taylor` winner contract cannot be paired with a `Nick Hardy` winner contract. These lookalikes are excluded before any profit is counted.

## Plain-English Glossary

- **Prediction market**: a market for a statement about the future. A `YES` contract pays `$1.00` when the statement is true and `$0.00` when it is false. A `NO` contract does the opposite.
- **Venue**: an exchange where contracts are traded. This study compares Kalshi with international Polymarket. Polymarket US is described separately because its public historical data is different.
- **Cross-venue arbitrage**: buying `YES` on one venue and `NO` on another venue when the combined cost is below the eventual `$1.00` payout. The contracts must represent the same real-world outcome.
- **Latency arbitrage**: a short-lived arbitrage opportunity caused by one venue updating its prices more slowly than the other venue after new information arrives.
- **Pair cost**: the combined amount paid for the `YES` and `NO` legs. If `YES` costs `$0.42` and `NO` costs `$0.51`, the pair cost is `$0.93`.
- **Gross edge**: the locked amount before trading costs. It is `$1.00 - pair cost`. A `$0.93` pair has a `$0.07` gross edge.
- **Fee**: an amount charged by an exchange when a trade is entered or exited.
- **Slippage**: extra cost caused by limited availability at the best displayed price. If only 50 contracts are available at `$0.40` and the next 50 cost `$0.42`, buying 100 contracts costs more than the first quoted price suggests.
- **Net edge**: gross edge after subtracting fees and slippage. This is the profit measure used for ranking retained examples.
- **Order book**: the visible list of offers from other traders, including prices and quantities.
- **CLOB**: central limit order book. This is the order-book system used by international Polymarket.
- **BBO**: best bid and offer. It is a short summary containing only the best visible buy price and best visible sell price.
- **Top of book**: the single best visible price.
- **Top-of-book depth**: the quantity visible at the best price on the thinner side of a two-leg trade.
- **L2 order book**: a multi-level order book. It includes the top of book and deeper prices behind it.
- **VWAP**: volume-weighted average price. Suppose 50 contracts cost `$0.40` and the next 50 cost `$0.42`. The VWAP for a 100-contract order is `$0.41`.
- **Parquet**: a compressed table-file format. PMXT stores archived order-book rows in Parquet files. Parquet is a storage format, not a finance term or a strategy.
- **Raw archive object**: the original stored PMXT Parquet file for a venue and hour. The replay verifies these files before treating them as historical evidence.
- **Candle or candlestick**: a compact historical price summary for a time interval. It usually records values such as the opening, highest, lowest, and closing price during that interval.
- **Settlement**: the final determination of whether a contract pays `$1.00` or `$0.00`.
- **Price-history proxy**: an estimate based on historical prices when historical book depth is unavailable. It is useful for screening, but it does not prove that both orders could have filled.
- **Opportunity window**: a continuous period when the pair remains profitable after costs.
- **Window persistence**: the length of an opportunity window.
- **Synchronized snapshot**: one timestamp where both venues supplied historical prices that can be compared. A single event may produce many synchronized snapshots.
- **Pregame**: the period before a scheduled sporting event starts.
- **In-play**: the period after a scheduled sporting event starts but before the final result.
- **Sports event start unavailable**: the retained public metadata contains a sports-market close time but no scheduled contest start. The scanner can inspect the final `24` hours but does not label those observations in-play.
- **Lifecycle bucket**: a time-to-resolution group used for a market without a game-like live period.
- **Modeled order size**: a hypothetical simultaneous two-leg order used for arithmetic. In the annual proxy layer, `100 paired contracts` means the model prices `100` YES contracts and `100` matching NO contracts together under a stated slippage assumption. It does not prove that the historical books visibly held that quantity.
- **Reclassified non-sports sample window**: a historical sample that was initially assigned sports-style timing because of an acronym collision, then relabeled after taxonomy cleanup. It remains a useful price observation, but it must not be read as in-play sports evidence.
- **Partial-fill exposure**: the risk that one leg fills but the opposite leg does not, leaving a temporary unhedged position.
- **ROI**: return on investment. It is net profit divided by the cash used to buy the pair.
- **Capital recycling**: selling both locked legs early when a safe paired sale earns more than holding until settlement.
- **Bankroll**: the cash available for trading.
- **No leverage**: the simulation does not borrow money to increase position size.

## Annual Price Proxy

Official international APIs do not expose historical Polymarket L2 depth. The annual study therefore uses adaptive historical-price sampling:

| Scenario timing | Sampling interval |
|---|---:|
| Sports more than `24h` before start | `60m` |
| Sports final `24h` before start | `5m` |
| Sports scheduled start through close | `1m` |
| Non-sports more than `30d` before close | `1d` |
| Non-sports `30d` to `24h` before close | `60m` |
| Non-sports final `24h` | `5m` |

Annual results are sensitivity estimates under total pair-slippage assumptions of `1`, `2`, and `5` cents. They are not historical fill proofs.

## PMXT L2 Replay

The executable layer reconstructs archived full books and evaluates paired sizes of `1`, `5`, `10`, `25`, `50`, `100`, and `250` contracts. The headline comparison size is `100`.

Each replayed hour is checkpointed independently. Reports include:

- top-of-book depth;
- actual VWAP slippage;
- fees and explicit fallback assumptions;
- net edge;
- partial-fill capacity limits;
- opportunity-window duration;
- latency buckets of `>=0.1s`, `>=0.5s`, `>=1s`, `>=2s`, and `>=5s`.

Only verified raw Parquet archive objects count as historical L2. A hosted PMXT current-book fallback is rejected by code.

## Capital Recycling

Every locked pair keeps its guaranteed hold-to-settlement result. The replay searches later executable bids for a safe paired unwind. It sells both legs early only when the exit improves profit by at least `$0.0075` per contract after exit fees and VWAP slippage. Otherwise the model retains the guaranteed hold result.

## Portfolio Appendix

Opportunity windows remain the primary evidence. Secondary portfolio simulations use:

- `$10,000` starting bankroll;
- no leverage;
- at most `10%` of starting bankroll in one matched market;
- one active position per pair;
- chronological entries and paired exits;
- separate runs for every contract-size tier.

PMXT simulations enforce observed L2 capacity. Annual simulations do not depth-gate positions and are labeled modeled sensitivity estimates.

## Reports

- [RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md)
- [ANNUAL_SCENARIO_ANALYSIS.md](ANNUAL_SCENARIO_ANALYSIS.md)
- [POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md](POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md)
- [ARBITRAGE_TRADE_EXAMPLES.md](ARBITRAGE_TRADE_EXAMPLES.md)
- [reports/coverage_manifest.md](reports/coverage_manifest.md)
- [reports/annual_catalog_funnel.md](reports/annual_catalog_funnel.md)

Generated JSON and CSV artifacts live under `reports/`.

## Data Sources

- [Polymarket international price history](https://docs.polymarket.com/api-reference/markets/get-prices-history)
- [Kalshi candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)
- [Kalshi historical candlesticks](https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks)
- [PMXT archive](https://archive.pmxt.dev/)
- [PMXT historical books](https://www.pmxt.dev/docs/api-reference/fetch-order-book)
- [Polymarket US API introduction](https://docs.polymarket.us/api-reference/introduction)
- [Polymarket US markets](https://docs.polymarket.us/api-reference/markets/get-markets)
- [Polymarket US events](https://docs.polymarket.us/api-reference/events/get-events)
