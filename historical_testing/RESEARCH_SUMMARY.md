# Prediction-Market Research Summary

This project separates evidence quality before comparing scenarios. A historical price gap is useful, but it is not the same thing as an executable fill with visible quantity.

Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)

## Evidence Map

| Layer | Coverage | What it can establish |
|---|---|---|
| International official APIs | `2025-05-31T00:00:00+00:00` to `2026-05-31T00:00:00+00:00` | Rolling-year price-proxy opportunities under stated slippage assumptions |
| International PMXT L2 | `2026-05-14T14` to `2026-06-10T07` | Displayed depth, VWAP slippage, short-lived windows, and safe paired early exits |
| Polymarket US public API | `15260` events | Scenario inventory and public-data limits, not retrospective arbitrage profit |

## Completion Status

- Full requested Kalshi historical cursor range reached: `True`.
- Oldest Kalshi close time reached: `2025-05-29T18:03:18.736056+00:00`.
- Kalshi rows fetched while traversing the cursor: `5139000`.
- Kalshi rows retained in the requested scenario index: `1071836`.
- Combined international catalog scope: `all_reached_public_catalog_slices_complete`.
- Explicitly capped catalog slices: `none recorded`.
- Annual price-proxy scan scope: `all_retained_strict_pairs`.
- Detailed retained-catalog funnel: [reports/annual_catalog_funnel.md](reports/annual_catalog_funnel.md).
- Verified PMXT synchronized archived hours: `410`.

## Profitable Examples

Only positive retained examples appear in the reader-facing reports. Categories without one say `No profitable example found.` The scenario analysis then states whether that is a complete negative screen, a missing synchronized-history result, or a matching-coverage limitation.

Detailed retained-catalog funnel: [reports/annual_catalog_funnel.md](reports/annual_catalog_funnel.md)

## Best Categories

The ordering uses a transparent blended score: `70%` annual two-cent-slippage profit percentile plus `30%` PMXT executable-profit percentile. Dollar profit remains visible beside the score.

| Rank | Category | Score | Annual net profit | PMXT net profit | PMXT evidence |
|---:|---|---:|---:|---:|---|
| 1 | `golf` | 85.00 | $1341.983974 | $0.000000 | Not L2 validated |
| 2 | `f1` | 71.00 | $598.874083 | $0.000000 | Not L2 validated |
| 3 | `elections` | 58.00 | $8.060508 | $78.304350 | L2 validated |
| 4 | `mlb` | 57.00 | $255.559971 | $0.000000 | Not L2 validated |
| 5 | `esports` | 29.00 | $3.382675 | $0.000000 | Not L2 validated |
| 6 | `nba` | 15.00 | $2.656553 | $0.000000 | Not L2 validated |

| Category | Contract | Locked net profit per paired contract | Evidence |
|---|---|---:|---|
| MLB | Athletics vs. Baltimore Orioles | $0.502075 | `official_api_price_history_proxy_without_historical_depth` |
| MLB | Athletics vs. Baltimore Orioles | $0.502075 | `official_api_price_history_proxy_without_historical_depth` |
| MLB | Pittsburgh Pirates vs. San Francisco Giants | $0.471975 | `official_api_price_history_proxy_without_historical_depth` |
| Golf | Will Michael Kim win the 2026 PGA Championship? | $0.465300 | `official_api_price_history_proxy_without_historical_depth` |
| Golf | Will Michael Brennan win the 2026 PGA Championship? | $0.464200 | `official_api_price_history_proxy_without_historical_depth` |

## Reading Order

1. Read the repository [README](../README.md) for the current system and historical-research context.
2. Read [ANNUAL_SCENARIO_ANALYSIS.md](ANNUAL_SCENARIO_ANALYSIS.md) for the international findings.
3. Read [POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md](POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md) for the separate US catalog study.
4. Read [ARBITRAGE_TRADE_EXAMPLES.md](ARBITRAGE_TRADE_EXAMPLES.md) for worked trade arithmetic.