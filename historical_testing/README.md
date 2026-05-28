# Kalshi / Polymarket Arbitrage Feasibility Study

Research tooling for finding and replaying historical cross-venue prediction-market arbitrage candidates between Kalshi and Polymarket using PMXT Router matches and PMXT hourly Parquet orderbook archives.

## What It Does

- Discovers identity-matched Kalshi/Polymarket markets through PMXT Router.
- Discovers the wide PMXT matched-cluster universe with checkpointed pagination.
- Reads only required columns from PMXT archive Parquet files.
- Reconstructs best bid/ask states for binary markets.
- Tests both executable combinations:
  - buy Polymarket YES + buy Kalshi NO
  - buy Kalshi YES + buy Polymarket NO
- Applies configurable fee and slippage assumptions.
- Emits JSON/CSV reports with gross edge, fee-adjusted edge, duration, and partial-fill exposure proxies.
- Groups nearby positive ticks into edge windows with configurable gap tolerance.

This is research tooling, not a live trading bot. It is intended to answer whether enough historical opportunities exist before building execution infrastructure.

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

Discover matched markets:

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

## Interpretation

The most important report fields are:

- `gross_edge_per_contract`: raw cents before fees and slippage.
- `clusters_fetched`: number of PMXT matched-market clusters fetched during discovery.
- `net_edge_per_contract`: fee/slippage-adjusted edge per $1 payout pair.
- `estimated_partial_fill_exposure`: absolute price movement needed to emergency hedge after one leg fills.
- `net_positive_windows`: contiguous positive-edge windows, not just quote-update ticks.
- `resolution_date_warning`: candidate should be manually reviewed before trusting the match.

Small positive gross edges are often not tradable. Kalshi fees are rounded up to the next cent, so trade size materially affects the effective per-contract fee.
