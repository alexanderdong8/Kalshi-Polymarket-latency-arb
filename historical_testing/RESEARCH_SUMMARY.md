# Prediction-Market Research Summary

This project separates evidence quality before comparing scenarios. A historical price gap is useful, but it is not the same thing as an executable fill with visible quantity.

Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)

## Evidence Map

| Layer | Coverage | What it can establish |
|---|---|---|
| International official APIs | `2025-05-31T00:00:00+00:00` to `2026-05-31T00:00:00+00:00` | Rolling-year price-proxy opportunities under stated slippage assumptions |
| International PMXT L2 | `2026-05-14T14` to `2026-05-25T08` | Displayed depth, VWAP slippage, short-lived windows, and safe paired early exits |
| Polymarket US public API | `15260` events | Scenario inventory and public-data limits, not retrospective arbitrage profit |

## Completion Status

- Full requested Kalshi historical cursor range reached: `True`.
- Oldest Kalshi close time reached: `2025-05-29T18:03:18.736056+00:00`.
- Kalshi rows fetched while traversing the cursor: `5139000`.
- Kalshi rows retained in the requested scenario index: `1071836`.
- Combined international catalog scope: `bounded_retained_screen_due_explicit_public_catalog_caps`.
- Explicitly capped catalog slices: `2026-01: Polymarket; 2026-02: Polymarket; 2026-03: Polymarket; 2026-04: Polymarket; 2026-05: Kalshi and Polymarket`.
- Annual price-proxy scan scope: `all_retained_strict_pairs`.
- Detailed retained-catalog funnel: [reports/annual_catalog_funnel.md](reports/annual_catalog_funnel.md).
- Verified PMXT synchronized archived hours: `259`.

## Profitable Examples

Only positive retained examples appear in the reader-facing reports. Categories without one say `No profitable example found.` The scenario analysis then states whether that is a complete negative screen, a missing synchronized-history result, or a matching-coverage limitation.

Detailed retained-catalog funnel: [reports/annual_catalog_funnel.md](reports/annual_catalog_funnel.md)

| Category | Contract | Locked net profit per paired contract | Evidence |
|---|---|---:|---|
| Culture | Will Bulgaria win the televote for Eurovision 2026? | $0.664211 | `official_api_price_history_proxy_without_historical_depth` |
| Golf | Will Justin Rose win the 2025 FedEx St. Jude Championship? | $0.654530 | `official_api_price_history_proxy_without_historical_depth` |
| Golf | Will J.J. Spaun win the 2025 FedEx St. Jude Championship? | $0.609301 | `official_api_price_history_proxy_without_historical_depth` |
| Politics | Will Keir Starmer say "Tax" at the next Prime Minister's Questions? | $0.567300 | `official_api_price_history_proxy_without_historical_depth` |
| Elections | Will Donna Miller be the Democratic Nominee for IL-02? | $0.534281 | `official_api_price_history_proxy_without_historical_depth` |

## Reading Order

1. Read the repository [README](../README.md) for the current system and
   historical-research context.
2. Read [ANNUAL_SCENARIO_ANALYSIS.md](ANNUAL_SCENARIO_ANALYSIS.md) for the international findings.
3. Read [POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md](POLYMARKET_US_PUBLIC_CATALOG_ANALYSIS.md) for the separate US catalog study.
4. Read [ARBITRAGE_TRADE_EXAMPLES.md](ARBITRAGE_TRADE_EXAMPLES.md) for worked trade arithmetic.
