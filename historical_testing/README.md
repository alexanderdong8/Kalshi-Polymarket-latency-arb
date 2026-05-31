# Kalshi / Polymarket Historical Arbitrage Study

This project tests whether the same prediction-market event traded at meaningfully different prices on Kalshi and Polymarket in historical data.

The core question is:

> If two markets resolve on the same event, could we have bought one side on one platform and the opposite side on the other platform for less than `$1.00` total?

Example:

- Kalshi YES is `$0.70`, so Kalshi NO might be around `$0.30`.
- Polymarket YES is `$0.50`.
- Buying Kalshi NO at `$0.30` plus Polymarket YES at `$0.50` costs `$0.80`.
- Since one of those two positions should pay `$1.00` if the markets are truly identical, the gross arbitrage edge is `$0.20`.

This tool looks for exactly that pattern in historical PMXT orderbook data.

## What It Does

- Discovers the wide PMXT Kalshi/Polymarket matched-cluster universe with checkpointed pagination.
- Filters for binary markets that appear to represent the same event.
- Reads historical PMXT hourly Parquet orderbook files.
- Reconstructs top-of-book bid/ask states from the historical orderbook events.
- Tests both executable combinations:
  - buy Polymarket YES + buy Kalshi NO
  - buy Kalshi YES + buy Polymarket NO
- Applies configurable fee and slippage assumptions.
- Requires nonzero top-of-book depth on both legs before reporting an opportunity.
- Emits JSON/CSV/Markdown reports with gross edge, fee-adjusted edge, duration, and partial-fill exposure proxies.
- Groups nearby positive ticks into edge windows with configurable gap tolerance.

This is research tooling, not a live trading bot. It is intended to answer whether enough historical opportunities exist before building execution infrastructure.

## What A PMXT Cluster Is

Kalshi and Polymarket each publish their own markets, but they do not provide a shared identifier for the same real-world question. PMXT adds that cross-exchange matching layer.

A **PMXT matched-market cluster** is a group of contracts that PMXT believes refer to the same event, or to closely related events, across one or more venues. For this study, the useful clusters contain at least one Kalshi market and one Polymarket market. The cluster lets the scanner quickly decide which orderbooks should be compared instead of comparing every Kalshi market with every Polymarket market.

Example:

| Venue | Contract |
|---|---|
| Kalshi | Will Portugal win the 2026 World Cup? |
| Polymarket | Will Portugal win the FIFA World Cup 2026? |

PMXT may place these contracts in one cluster so the scanner can compare their prices.

A PMXT cluster is a discovery shortcut, not a guarantee that a trade is safe. Before treating a pair as arbitrage, verify that both contracts have the same outcome meaning, event scope, cutoff date, settlement source, and resolution rule. A related pair such as "reach the Round of 32" versus "reach the Round of 16" must be rejected even if both contracts mention the same team and tournament.

## Live And Historical Orderbooks

An **orderbook** lists the resting buy and sell orders at each price and the quantity available at each level. **Level 2**, usually abbreviated **L2**, means the book includes multiple price levels and their sizes instead of only one displayed price or the best bid and ask.

Both official exchange APIs provide proper live orderbook data:

- Kalshi provides current orderbooks and live WebSocket orderbook updates. Kalshi returns YES and NO bids; the opposite asks are implied. For example, `Kalshi YES ask = 1 - best NO bid`.
- Polymarket provides current CLOB orderbooks and live WebSocket updates with bids, asks, and sizes for its outcome tokens.

The limitation applies to historical research. The official APIs provide useful historical prices, candlesticks, trades, and market metadata, but they do not expose a synchronized, long-range historical L2 replay for both exchanges that can answer exactly how much size was available on both legs at the same instant.

PMXT fills that research gap by archiving historical orderbook updates and exposing reconstructed L2 books through its archive/API. That is why this project uses:

- Official Kalshi and Polymarket APIs for catalog discovery, broad historical screening, and live-bot design.
- PMXT clusters to identify cross-exchange candidate pairs.
- PMXT historical orderbooks to test whether an apparent past arbitrage had executable bid/ask prices and nonzero depth on both legs.

## Current Findings

The current generated historical scan is:

[reports/batch_summary_2026-05-23T07.md](reports/batch_summary_2026-05-23T07.md)

The category/phase summary is:

[reports/scenario_analysis_2026-05-23T07.md](reports/scenario_analysis_2026-05-23T07.md)

The combined annual proxy and executable scenario research is:

[ANNUAL_SCENARIO_ANALYSIS.md](ANNUAL_SCENARIO_ANALYSIS.md)

The official-API price-history proxy sample is:

[reports/official_price_scan_2026-05-23T07_sample300.json](reports/official_price_scan_2026-05-23T07_sample300.json)

The reachable longer-window official-API proxy report is:

[reports/annual_official_proxy_12m.md](reports/annual_official_proxy_12m.md)

The 12-month official catalog coverage audit is:

[reports/monthly_12m_coverage.md](reports/monthly_12m_coverage.md)

The executable-window fillability proxy is:

[reports/fillability_analysis_2026-05-23T07.md](reports/fillability_analysis_2026-05-23T07.md)

It scans one historical hour:

- Time window: `2026-05-23T07:00:00Z` to `2026-05-23T08:00:00Z`
- Candidate matched pairs scanned: `1,494`
- Gross-positive quote ticks: `158,028`
- Fee/slippage-positive quote ticks: `33,800`
- Fee/slippage-positive opportunity windows: `3,255`
- Best gross edge found: `17.0 cents`
- Best estimated net edge found: `13.098 cents`

This means the scanner found many moments where the reconstructed historical orderbooks implied a cross-platform hedge could be entered for less than `$1.00`. However, not every row is automatically tradeable in real life. The most important extra checks are:

- Whether the PMXT match is truly the same event and resolution rule.
- Whether both legs could actually fill before either book moved.
- Whether the quoted top-of-book size is enough for the intended trade.
- Whether fees, slippage, funding constraints, and exchange latency erase the edge.

The initial category results from the executable orderbook replay were:

- Politics produced the most net-positive windows in this one-hour scan.
- Popular sports had many matched markets, but fewer fee-positive windows and smaller clean edges than politics/other categories.
- The best clean sports example was roughly `2.5 cents` estimated net edge.
- The strongest clean non-sports examples were around `3-4.5 cents` estimated net edge.
- Active-like/high-volatility sports did show opportunities, but they were short-lived and smaller.

The official API proxy scan over the first `300` matched scenarios found:

- `167` markets with aligned official Kalshi/Polymarket price-history points.
- `177` proxy gross-positive observations.
- Clean proxy examples in politics and sports, including a LeBron retirement market around `3.0 cents` estimated net edge.
- This proxy scan does not prove executable fillability because official historical APIs provide price/candlestick history, not synchronized historical orderbook depth.

The longer-window official proxy replay currently covers the strict recent matches that the checkpointed catalog crawl could reach:

- Strict catalog matches replayed: `45`
- Months with replayed strict matches: April and May 2026
- Aligned official price/candlestick points: `3,548`
- Fee/slippage-positive proxy snapshots: `609`
- Proxy windows: `235`
- Markets with proxy signals: `10`

This is **not** a completed 12-month arbitrage result. The coverage audit is the authoritative status for the year-scale crawl.

The bounded 12-month official-catalog screen covering `2025-05-30T00:00:00Z` through `2026-05-30T00:00:00Z` found:

- `6,125` Kalshi events and `12,771` Polymarket markets screened under explicit page caps.
- `45` conservative catalog pairs after semantic filtering.
- All `45` audited pairs scanned across pre-event and near-resolution windows.
- `609` fee/slippage-positive proxy signals.
- The audited annual sample is concentrated in election markets, so it cannot establish a 12-month sports ranking.

The detailed executable sports breakdown for the saved PMXT hour found fee-positive windows in baseball and active MMA/boxing. Basketball, tennis, and motorsport did not produce fee-positive windows in that one-hour replay. Treat that as a short-horizon result, not a universal sports ranking.

## Data Sources And What They Prove

There are two evidence levels in this project:

1. **Official Kalshi/Polymarket API price history**
   - Kalshi provides official historical markets, trades, and candlesticks.
   - Polymarket provides official CLOB price-history endpoints.
   - These are useful for broad screening across many categories and longer date windows.
   - They do not fully prove an executable arbitrage because historical top-of-book depth is not synchronized across both platforms.

2. **PMXT historical orderbook archive**
   - PMXT stores hourly orderbook replay data for Kalshi and Polymarket.
   - This is what we use for executable examples with bid/ask and top-of-book depth.
   - This is the stronger evidence for “could I have entered both legs at those prices?”
   - The currently indexed overlap audit found `50` Kalshi/Polymarket v2 hours, from `2026-05-23T07` through `2026-05-25T08`. That is enough for an executable-depth study over those hours, but not enough to claim a 12-month executable replay.

### Current 12-Month Coverage Limit

The official Kalshi historical-market endpoint is cursor-paginated and does not expose close-time range filtering. Short-duration contracts dominate the archive.

The resumable crawl currently records:

- Kalshi historical pages crawled: `63`
- Kalshi archived contracts crawled: `63,000`
- Oldest Kalshi close time reached: `2026-03-28T12:00:00Z`
- Requested start date: `2025-05-30T00:00:00Z`

So the crawler is implemented and resumable, but it has not reached the oldest requested months yet. Older monthly rows in the coverage report are intentionally marked incomplete instead of being filled with invented statistics.

Official docs referenced:

- Polymarket API overview: https://docs.polymarket.com/api-reference/introduction
- Polymarket Gamma catalog overview: https://docs.polymarket.com/developers/gamma-markets-api/overview
- Polymarket price history: https://docs.polymarket.com/api-reference/markets/get-prices-history
- Polymarket batch price history: https://docs.polymarket.com/api-reference/markets/get-batch-prices-history
- Kalshi historical data overview: https://docs.kalshi.com/getting_started/historical_data
- Kalshi historical markets: https://kalshi-b198743e.mintlify.app/api-reference/historical/get-historical-markets
- Kalshi historical candlesticks: https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks
- Kalshi trades: https://kalshi-b198743e.mintlify.app/api-reference/market/get-trades

## Specific Historical Examples

These examples come from reconstructed PMXT historical orderbooks, not just current catalog prices.

### Clean Example: US Nuclear Reactor Approval

Timestamp: `2026-05-23T07:28:04.823000Z`

Market:

- Polymarket: `US grants license for new nuclear reactor in 2026?`
- Kalshi: `Will a new nuclear reactor be approved by Dec 31, 2026?`
- Match warning: `None`

Position:

- Buy YES on Kalshi at `$0.213`
- Buy NO on Polymarket at `$0.710`
- Total cost: `$0.923`

Other prices visible at the same timestamp:

- Kalshi YES bid/ask: `$0.212 / $0.213`
- Kalshi NO bid/ask: `$0.787 / $0.788`
- Polymarket YES bid/ask: `$0.290 / $0.360`
- Polymarket NO bid/ask: `$0.640 / $0.710`

Interpretation:

- If the event happens, the Kalshi YES should pay `$1.00`.
- If the event does not happen, the Polymarket NO should pay `$1.00`.
- Total entry cost was `$0.923`, so the raw locked-in spread was `$1.00 - $0.923 = $0.077`.
- Polymarket's NO ask of `$0.710` implies a YES price of about `$0.290`, while Kalshi YES was askable at `$0.213`.
- That means Kalshi YES was about `7.7 cents` cheaper than Polymarket's implied YES.
- Gross edge: `7.7 cents`
- Estimated net edge after default fees/slippage: `4.4905 cents`
- Top-of-book depth: `31` contracts

This is one of the cleaner examples because the match warning is `None`.

Within the scanned hour, this gap did not close. From `07:28:04Z` through the last aligned quote at `07:59:53Z`, the executable combination stayed essentially the same:

- Kalshi YES ask stayed around `$0.213`.
- Polymarket NO ask stayed around `$0.710`.
- Total entry cost stayed around `$0.923`.
- Gross edge stayed around `7.7 cents`.

In the later saved PMXT live snapshot, the same market looked much closer:

- Kalshi YES ask: `$0.226`
- Polymarket NO ask: `$0.780`, implying Polymarket YES near `$0.220`
- The cross-market gap was then roughly `0.6 cents`, and the direct arbitrage was gone.

So for this example, the exchanges did not converge inside the one-hour historical window, but they did appear much closer in the later saved market snapshot.

### Clean Example: Venezuela Leader End Of 2026

Timestamp: `2026-05-23T07:37:52.010000Z`

Market:

- Polymarket: `Will Maria Corina Machado be the leader of Venezuela end of 2026?`
- Kalshi: `Will Maria Corina Machado be the head of state of Venezuela on Dec 31, 2026?`
- Match warning: `None`

Position:

- Buy YES on Polymarket at `$0.060`
- Buy NO on Kalshi at `$0.880`
- Total cost: `$0.940`

Interpretation:

- Gross edge: `$1.00 - $0.940 = $0.060`
- Estimated net edge after default fees/slippage: `3.978 cents`
- Top-of-book depth: `390` contracts

This is a strong clean example because it had much more quoted depth than several other opportunities.

### Clean Example: Poilievre Conservative Leader

Timestamp: `2026-05-23T07:03:29.184000Z`

Market:

- Polymarket: `Poilievre out as leader of Conservatives by December 31, 2026?`
- Kalshi: `Will Pierre Poilievre resign as the conservative party leader before Jan 1, 2027?`
- Match warning: `None`

Position:

- Buy YES on Polymarket at `$0.140`
- Buy NO on Kalshi at `$0.800`
- Total cost: `$0.940`

Interpretation:

- Gross edge: `6.0 cents`
- Estimated net edge after default fees/slippage: `3.278 cents`
- Top-of-book depth: `7.52` contracts

This example has a clean match, but the available depth is small.

### Larger Edge But Needs Manual Review: Javier Milei Argentina Election

Timestamp: `2026-05-23T07:15:48.744000Z`

Market:

- Polymarket: `Will Javier Milei win the 2027 Argentina presidential election?`
- Kalshi: `Who will win the next Argentine presidential election?`
- Match warning: `Resolution dates differ by 373 days; manually review before trading.`

Position:

- Buy YES on Polymarket at `$0.440`
- Buy NO on Kalshi at `$0.390`
- Total cost: `$0.830`

Interpretation:

- Gross edge: `$1.00 - $0.830 = $0.170`
- Estimated net edge after default fees/slippage: `13.098 cents`
- Top-of-book depth: `45.26` contracts

This is a large apparent arbitrage, but the resolution-date warning means it should not be treated as a confirmed executable trade without checking both rulebooks manually.

### Known Smoke-Test Example: Brian Armstrong On UpOnly

Timestamp: `2026-05-23T07:15:07.130000Z`

Market:

- Polymarket: `Will Brian Armstrong appear on the UpOnly podcast by December 31?`
- Kalshi: `Will Brian Armstrong be on UpOnly Podcast before Jan 2027?`
- Match warning: `None`

Position:

- Buy YES on Polymarket at `$0.170`
- Buy NO on Kalshi at `$0.780`
- Total cost: `$0.950`

Interpretation:

- Gross edge: `5.0 cents`
- Estimated net edge after default fees/slippage: `2.0845 cents`
- Top-of-book depth: `10` contracts

This is a good simple example of the exact pattern the project is searching for.

## Setup

The existing `.env` can use any of these key names:

```text
PMXT_API_KEY=pmxt_live_...
pmxt=pmxt_live_...
pmxt-key=pmxt_live_...
```

Install dependencies if needed:

```powershell
pip install -r requirements.txt
```

## Usage

Discover a small live-difference sample:

```powershell
python -m arb_study.cli discover --categories Sports Politics Crypto Economics --limit 50 --out data/matches.json
```

Discover the wide Kalshi/Polymarket cluster universe:

```powershell
python -m arb_study.cli discover-clusters --out data/cluster_matches.json --checkpoint data/cluster_pages_checkpoint.json
```

Scan an hourly window:

```powershell
python -m arb_study.cli scan --matches data/matches.json --start 2026-05-23T07 --end 2026-05-23T08 --out reports/scan.json --csv reports/scan_opportunities.csv --max-markets 20
```

Batch scan many cluster-derived matches by reading each hourly archive once:

```powershell
python -m arb_study.cli scan-batch --matches data/cluster_matches.json --start 2026-05-23T07 --end 2026-05-23T08 --out reports/batch_scan.json --csv reports/batch_opportunities.csv
```

Create a scenario/category report from a batch orderbook scan:

```powershell
python -m arb_study.cli scenario-report --scan reports/batch_scan_2026-05-23T07.json --out-json reports/scenario_analysis_2026-05-23T07.json --out-md reports/scenario_analysis_2026-05-23T07.md --out-csv reports/scenario_analysis_2026-05-23T07.csv
```

Run an official Kalshi/Polymarket price-history proxy scan:

```powershell
python -m arb_study.cli official-price-scan --matches data/cluster_matches.json --start 2026-05-23T07 --end 2026-05-23T08 --max-markets 300 --out reports/official_price_scan_2026-05-23T07_sample300.json
```

Discover conservative official-catalog matches across the prior 12 months:

```powershell
python -m arb_study.cli discover-official-history --start 2025-05-30T00:00:00Z --end 2026-05-30T00:00:00Z --cache data/official_history_event_cache_12m.json --out data/official_history_matches_12m.json
```

Run the stratified 12-month official-API proxy report:

```powershell
python -m arb_study.cli annual-proxy-report --matches data/official_history_matches_12m.json --start 2025-05-30T00:00:00Z --end 2026-05-30T00:00:00Z --out-json reports/annual_official_proxy_12m.json --out-md reports/annual_official_proxy_12m.md
```

The annual report groups matched markets by month, scenario, and timing regime. Its default sample rotates across available scenario buckets within each month. Set `--max-markets-per-month 0` to scan every discovered match.

Continue the cursor-based official catalog crawl and refresh its coverage audit:

```powershell
python -m arb_study.historical_monthly --collect --coverage-only --coverage-md reports/monthly_12m_coverage.md --start 2025-05-30T00:00:00Z --end 2026-05-30T00:00:00Z --cache data/monthly_12m_cache.json --out data/monthly_12m_matches.json --kalshi-historical-pages 25 --kalshi-current-pages-per-month 2 --polymarket-pages-per-month 5
```

Each run advances another capped cursor batch and writes a checkpoint after every Kalshi historical page. Once the audit says the requested Kalshi history is complete, normalize the monthly cache:

```powershell
python -m arb_study.historical_monthly --coverage-md reports/monthly_12m_coverage.md --start 2025-05-30T00:00:00Z --end 2026-05-30T00:00:00Z --cache data/monthly_12m_cache.json --out data/monthly_12m_matches.json
```

Create the executable-window order-size report:

```powershell
python -m arb_study.cli fillability-report --scan reports/batch_scan_2026-05-23T07.json --out-json reports/fillability_analysis_2026-05-23T07.json --out-md reports/fillability_analysis_2026-05-23T07.md
```

Find currently indexed overlapping Kalshi/Polymarket v2 archive hours:

```powershell
python -m arb_study.cli archive-hours --out data/archive_hours.json
```

Create a Markdown summary:

```powershell
python -m arb_study.cli report --scan reports/scan.json --out reports/summary.md
```

Run the built-in sample, which targets the Portugal World Cup identity pair if discoverable:

```powershell
python -m arb_study.cli sample
```

## How To Read The Metrics

Each reported opportunity has a line like:

```text
Position: buy YES on kalshi at 0.130000 and buy NO on polymarket at 0.820000
Total entry cost: 0.950000
Gross edge: 0.050000
Net edge: 0.024620
Fees: 1.538000 on 100 contracts
Top-of-book depth: 9.000000 contracts
```

This means:

- `buy YES on kalshi at 0.130000`: the historical Kalshi book had YES available at `$0.13`.
- `buy NO on polymarket at 0.820000`: the historical Polymarket book had NO available at `$0.82`.
- `Total entry cost`: the two prices added together. Here, `$0.13 + $0.82 = $0.95`.
- `Gross edge`: the pre-fee arbitrage spread. Here, `$1.00 - $0.95 = $0.05`.
- `Fees`: estimated total platform fees for the configured trade size, defaulting to `100` contracts.
- `Net edge`: estimated per-contract edge after fees and slippage buffer. Here, `0.024620` means about `2.462 cents` per contract after assumptions.
- `Top-of-book depth`: the smaller available size across the two legs. If this says `9`, the scanner only saw enough top-of-book liquidity for about `9` contracts at those exact prices.
- `Match warning`: whether the scanner noticed a possible rule/date mismatch. `None` is better. A warning means the opportunity may be a false positive unless the rulebooks are manually verified.

The most important report fields are:

- `gross_edge_per_contract`: raw cents before fees and slippage.
- `clusters_fetched`: number of PMXT matched-market clusters fetched during discovery.
- `net_edge_per_contract`: fee/slippage-adjusted edge per $1 payout pair.
- `estimated_partial_fill_exposure`: absolute price movement needed to emergency hedge after one leg fills.
- `net_positive_windows`: contiguous positive-edge windows, not just quote-update ticks.
- `resolution_date_warning`: candidate should be manually reviewed before trusting the match.

Small positive gross edges are often not tradable. Kalshi fees are rounded up to the next cent, so trade size materially affects the effective per-contract fee.

### Terminology And The Default 100-Contract Test

The scanner uses `100` paired contracts as its default target order size. One **paired contract** means buying one outcome on one venue and the opposite outcome on the other venue. If the markets are truly identical, that pair pays `$1.00` at resolution because exactly one leg wins.

The scanner tests a target size rather than assuming every visible edge is equally useful:

```text
executable top-of-book size =
    min(target size, available size on leg 1, available size on leg 2)
```

For example:

```text
Buy Kalshi NO at $0.30:       18 contracts available
Buy Polymarket YES at $0.50:  70 contracts available
Default target size:         100 paired contracts

Executable at those exact prices: min(100, 18, 70) = 18 paired contracts
Gross edge per paired contract:   $1.00 - $0.30 - $0.50 = $0.20
Gross profit at visible depth:    18 * $0.20 = $3.60 before fees
```

Important terms:

- `Ask`: the lowest price currently available to buy a leg.
- `Bid`: the highest price currently available to sell a leg.
- `Top of book`: the best currently available bid or ask.
- `Top-of-book depth`: how many paired contracts can be bought at the two displayed best ask prices. It is limited by the smaller leg.
- `Gross edge per contract`: `$1.00 - leg 1 ask - leg 2 ask`, before fees and slippage.
- `Net edge per contract`: gross edge minus estimated fees and the configured slippage allowance, expressed per paired contract.
- `Target order size`: the requested test size, defaulting to `100` paired contracts.
- `Executable size`: the amount supported by the visible orderbook. This can be smaller than the target order size.
- `Slippage`: the extra cost incurred when the best price lacks enough depth and the order must consume worse price levels.
- `L2 orderbook`: multiple price levels and sizes, which are needed to estimate slippage for larger orders.
- `Partial-fill risk`: the risk that one exchange fills while the hedge order on the other exchange does not.
- `Proxy signal`: an apparent edge based on aligned official historical prices. It is useful for screening but does not prove executable depth.
- `Executable opportunity`: an apparent edge reconstructed from historical orderbooks with nonzero ask depth on both legs. It is stronger evidence, but it still does not prove that a live bot would have won the race to fill both orders.

The reports should be read at multiple target sizes such as `1`, `5`, `10`, `25`, `50`, `100`, and `250` contracts. The `100`-contract default is a useful baseline, not a claim that every reported opportunity could fill `100` contracts at its displayed prices.

### What Median Net Window Means

A `net-positive window` is a contiguous period where the reconstructed executable order books continued to show an edge after default fees and slippage. Nearby quote updates are grouped into the same window when the gap between updates is no more than `5` seconds.

The current one-hour PMXT replay has:

- `3,255` fee/slippage-positive windows.
- Median net window: `0.352 seconds`.

That means half of those windows lasted less than `0.352 seconds`, and half lasted longer. It does **not** mean an order has a `50%` fill chance in `0.352` seconds. Some windows have `0.000 seconds` duration because the edge appeared in only one reconstructed quote update.

### Order Size And Fillability Proxy

The fillability report asks a narrower question:

> For a target order size, how many historical net-positive windows quoted enough top-of-book liquidity on both legs, and how long did those windows remain visible?

Current one-hour executable replay:

| Order size | Windows with enough quoted depth | Share of net windows | Of eligible windows lasting at least 1 second |
|---:|---:|---:|---:|
| `1` contract | `3,208` | `98.56%` | `38.28%` |
| `5` contracts | `2,865` | `88.02%` | `37.24%` |
| `10` contracts | `2,412` | `74.10%` | `37.27%` |
| `25` contracts | `2,137` | `65.65%` | `35.61%` |
| `50` contracts | `1,773` | `54.47%` | `37.73%` |
| `100` contracts | `1,468` | `45.10%` | `36.10%` |
| `250` contracts | `1,078` | `33.12%` | `39.89%` |

These are optimistic coverage statistics, not realized fill probabilities. They do not model exchange queue position, network delay, competing bots, adverse selection, or the chance that only one hedge leg fills.

For example, the reactor opportunity quoted `31` contracts of limiting top-of-book depth. The reconstructed books support the claim that roughly `10` or `25` contracts were visible at the displayed prices. They do not support a claim that a `50`-contract trade could enter at the same prices, and they still do not prove that both legs would have filled before either quote moved.

The annual proxy report uses a separate vocabulary:

- `Proxy signal`: an aligned official-price snapshot where the opposite-outcome pair remains profitable after configured fees and slippage.
- `Signal share`: fee/slippage-positive directions divided by all aligned directions tested in that report bucket.
- `Net-positive window`: consecutive proxy-signal snapshots. In the executable PMXT replay, windows are quote-event windows. In the annual official-API report, they are candle/price-history proxy windows.
- `Mean net edge on positive points`: average estimated profit per `$1.00` payout pair among positive proxy snapshots only. It does not include periods with no signal.
- `Pre-event proxy`: the sampled period from seven days to six hours before the event closes.
- `Near-resolution or in-play proxy`: the sampled period from six hours before close through one hour after close. For sports, this may include in-play updates; the official APIs do not label each minute as live or pregame.

The annual official-catalog matcher is intentionally conservative, but title similarity is not enough to authorize a trade. Every candidate still needs a manual rulebook review.

The current longer-window report contains a useful screening example:

- At `2026-05-23T07:00:00Z`, the official price histories showed Polymarket YES on Everett Jackson winning the TX-30 Republican nomination at `$0.514` and Kalshi NO at `$0.080`.
- Proxy pair cost: `$0.594`
- Gross proxy edge: `40.6 cents`
- Estimated net proxy edge after defaults: `37.831 cents`

This is a reason to inspect the market manually. It is not executable proof because the official histories do not show synchronized depth, and the resolution rules still need manual verification.

## Bottom Line

The historical test does show real-looking cross-platform dislocations. In the scanned hour, there were thousands of fee/slippage-positive windows across the matched universe. But feasibility depends on execution quality:

- The strongest clean examples were usually only a few cents of net edge.
- Some very large apparent edges came from matches that need manual rule review.
- Many windows were short, with median net-positive window duration under one second in this scan.
- Depth matters. A 5-cent edge with only 7 contracts available is less useful than a 3-cent edge with hundreds of contracts available.

The next research step is to run `scan-batch --auto-overlap` across all currently available overlapping archive hours and then manually review the top clean examples with `Match warning: None`.

For multi-month or multi-year research, use the official price-history scan as a broad screen first, then use PMXT orderbook replay where historical orderbook files exist. The official APIs can cover more history, but the PMXT orderbooks are what establish executable depth.
