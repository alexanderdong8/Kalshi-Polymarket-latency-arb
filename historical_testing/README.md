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

## Current Findings

The current generated historical scan is:

[reports/batch_summary_2026-05-23T07.md](reports/batch_summary_2026-05-23T07.md)

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

Interpretation:

- If the event happens, the Kalshi YES should pay `$1.00`.
- If the event does not happen, the Polymarket NO should pay `$1.00`.
- Total entry cost was `$0.923`, so the raw locked-in spread was `$1.00 - $0.923 = $0.077`.
- Gross edge: `7.7 cents`
- Estimated net edge after default fees/slippage: `4.4905 cents`
- Top-of-book depth: `31` contracts

This is one of the cleaner examples because the match warning is `None`.

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

## Bottom Line

The historical test does show real-looking cross-platform dislocations. In the scanned hour, there were thousands of fee/slippage-positive windows across the matched universe. But feasibility depends on execution quality:

- The strongest clean examples were usually only a few cents of net edge.
- Some very large apparent edges came from matches that need manual rule review.
- Many windows were short, with median net-positive window duration under one second in this scan.
- Depth matters. A 5-cent edge with only 7 contracts available is less useful than a 3-cent edge with hundreds of contracts available.

The next research step is to run `scan-batch --auto-overlap` across all currently available overlapping archive hours and then manually review the top clean examples with `Match warning: None`.
