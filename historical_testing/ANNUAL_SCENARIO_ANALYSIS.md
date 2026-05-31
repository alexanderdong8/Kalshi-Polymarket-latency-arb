# Kalshi / Polymarket Scenario Analysis

## Executive Summary

This study now has two evidence layers:

1. An official-API proxy screen for the reachable subset inside the requested window from `2025-05-30T00:00:00Z` through `2026-05-30T00:00:00Z`.
2. An executable PMXT order-book replay covering `2026-05-23T07:00:00Z` through `2026-05-23T08:00:00Z`.

The layers answer different questions. Official APIs provide broad historical price screening, but not synchronized cross-exchange order-book depth. PMXT replay provides executable bid/ask and quoted-depth evidence, but the currently indexed overlap is much shorter.

The reachable official-API screen found:

- `6,125` Kalshi events screened.
- `12,771` Polymarket markets screened.
- `45` conservative catalog pairs after semantic filtering.
- All `45` audited pairs scanned across pre-event and near-resolution windows.
- `3,548` aligned official-price snapshots.
- `609` estimated fee/slippage-positive proxy signals.
- `235` net-positive proxy windows.

The accepted sample was concentrated in April and May 2026: `44` election markets and `1` entertainment market. It is useful evidence for election-market behavior, but it is not a completed 12-month result or a valid basketball-versus-tennis leaderboard.

The executable one-hour replay found:

- `1,494` matched markets.
- `3,255` fee/slippage-positive executable windows.
- Median net-positive window duration: `0.352` seconds.
- Best estimated net edge: `13.098` cents per contract, from a pair that still needs manual rule review.
- Best clean non-sports example: `4.4905` cents estimated net edge.
- Best clean sports example: `2.4992` cents estimated net edge.

## What The Terms Mean

- **Gross edge**: `$1.00 - total entry cost`. If opposite outcomes cost `$0.94`, gross edge is `$0.06`.
- **Estimated net edge**: gross edge minus modeled fees and the configured slippage buffer. It is estimated profit per `$1.00` payout pair.
- **Proxy signal**: an aligned official-price snapshot that remains positive after fees and slippage. It is a screening signal, not proof that both legs were fillable.
- **Executable window**: a consecutive PMXT order-book period with positive modeled edge and nonzero quoted top-of-book size on both legs.
- **Signal share**: positive official-price directions divided by all aligned directions tested in a report bucket.
- **Quoted-depth eligible**: the PMXT top of book displayed enough contracts for the requested size. This is not the same as an observed fill.

## Annual Official-API Screen

### Coverage Limits

The catalog crawl is deliberately checkpointed and capped. Most Polymarket monthly slices reached the configured `1,000`-market cap, the Kalshi event crawl reached its configured page cap, and only `600` shortlisted Kalshi events were expanded. The deeper Kalshi historical cursor audit crawled `63,000` archived contracts but only reached `2026-03-28T12:00:00Z`, well short of the requested `2025-05-30T00:00:00Z` start. The script can continue with higher caps, but this generated report is a reachable-subset screen, not an exhaustive census.

The coverage audit is:

[reports/monthly_12m_coverage.md](reports/monthly_12m_coverage.md)

The generated report is:

[reports/annual_official_proxy_12m.md](reports/annual_official_proxy_12m.md)

### Scenario Results

| Scenario | Markets | Markets with aligned prices | Markets with positive signals | Signal share | Mean positive net edge | Maximum net edge |
|---|---:|---:|---:|---:|---:|---:|
| Politics: elections | 44 | 35 | 10 | 7.59% | 2.402 cents | 37.831 cents |
| Other: entertainment | 1 | 1 | 1 | 30.32% | 5.229 cents | 24.932 cents |

The entertainment row is only one Lady Gaga Met Gala market, so it should not be generalized into an entertainment strategy.

Election signals were more frequent near resolution but larger on average in the pre-event window:

| Election timing regime | Signal share | Mean positive net edge | Net-positive windows |
|---|---:|---:|---:|
| Seven days to six hours before close | 4.76% | 2.621 cents | 54 |
| Six hours before close through one hour after | 10.93% | 1.855 cents | 146 |

The largest annual proxy signal was the Everett Jackson TX-30 Republican nominee pair: `37.831` cents estimated net edge at `2026-05-23T07:00:00Z`. This is a strong screening candidate, but it still needs manual rulebook review and order-book replay before being treated as executable.

## Executable Replay Scenario Results

The detailed PMXT replay report is:

[reports/scenario_analysis_2026-05-23T07.md](reports/scenario_analysis_2026-05-23T07.md)

Within the scanned hour, politics generated the most net-positive executable windows. For sports, baseball and active MMA/boxing generated fee-positive windows:

| Sports scenario | Markets scanned | Markets with net-positive windows | Net-positive windows | Maximum estimated net edge |
|---|---:|---:|---:|---:|
| Baseball, slower markets | 169 | 11 | 715 | 2.150 cents |
| MMA/boxing, active-like | 3 | 2 | 67 | 2.499 cents |
| Baseball, active-like | 2 | 2 | 50 | 1.336 cents |
| American football | 51 | 0 | 0 | None positive |
| Soccer | 201 | 0 | 0 | None positive |
| Motorsport, including Formula One | 48 | 0 | 0 | None positive |
| Hockey | 36 | 0 | 0 | None positive |
| Basketball | 70 | 0 | 0 | None positive |
| Tennis | 1 | 0 | 0 | None positive |

This does not prove baseball is generally better than basketball or tennis. It says baseball and active MMA/boxing were the only sports groups with fee-positive windows in this specific executable hour. Tennis is especially under-sampled.

## Order Size And Fillability

The PMXT fillability report is:

[reports/fillability_analysis_2026-05-23T07.md](reports/fillability_analysis_2026-05-23T07.md)

For a `100`-contract target:

- `1,468 / 3,255`, or `45.10%`, of net-positive windows displayed at least `100` contracts of top-of-book depth on both legs.
- Among those depth-eligible windows, `36.10%` lasted at least one second.
- Among those depth-eligible windows, `13.22%` lasted at least five seconds.
- Median window duration for those depth-eligible windows was `0.149` seconds.

This does **not** mean `45` of every `100` submitted orders would fill. Historical top-of-book depth cannot show queue position, competing orders, network delay, adverse selection, or partial fills. A real fill-rate estimate needs paper trading or production execution logs.

## Practical Conclusions

1. Election markets deserve the next round of attention. They produced both frequent annual proxy signals and many executable windows in the PMXT replay.
2. Pre-event election dislocations were less frequent but larger on average than near-resolution election dislocations in the bounded annual sample.
3. Baseball and active MMA/boxing are the strongest sports candidates from the executable replay. Formula One, basketball, and tennis do not yet have positive evidence.
4. Quoted depth is a major filter. At `100` contracts, fewer than half of net-positive replay windows displayed enough top-of-book liquidity.
5. The next decisive experiment is paper execution: submit or simulate paired orders with realistic venue latency and record observed full fills, partial fills, emergency hedges, and realized P&L.

## Reproducing The Study

Run the bounded catalog screen:

```powershell
python -m arb_study.cli discover-official-history --start 2025-05-30T00:00:00Z --end 2026-05-30T00:00:00Z --cache data/official_history_event_cache_12m.json --out data/official_history_matches_12m.json --kalshi-event-pages 30 --polymarket-pages-per-month 10 --max-expanded-events 600
```

Run the annual official-price proxy report:

```powershell
python -m arb_study.cli annual-proxy-report --matches data/official_history_matches_12m.json --start 2025-05-30T00:00:00Z --end 2026-05-30T00:00:00Z --out-json reports/annual_official_proxy_12m.json --out-md reports/annual_official_proxy_12m.md --max-markets-per-month 0 --workers 2
```

For a deeper but slower contiguous Kalshi historical crawl, increase the page budget until `oldest_close_time` reaches the requested start:

```powershell
python -m arb_study.historical_monthly --collect --start 2025-05-30T00:00:00Z --end 2026-05-30T00:00:00Z --cache data/monthly_12m_cache.json --out data/monthly_12m_matches.json --kalshi-historical-pages 100 --polymarket-pages-per-month 5
```
