# Polymarket US Public Catalog Analysis

This report describes the Polymarket US data that is publicly reachable without institutional report credentials. It intentionally does not claim historical arbitrage profitability.

Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)

## What This Report Is For

Polymarket US exposes a public catalog that is useful for understanding which categories and contract types exist. The public gateway does not provide the historical quote-by-quote order books needed to replay old trades. For that reason, this file is a catalog census, not a profit ranking.

## Terms

- **Event**: the real-world question or sporting contest that groups one or more tradable contracts.
- **Embedded market**: a tradable contract included inside an event response. One event can contain several embedded markets.
- **Flat market**: the same kind of tradable contract returned directly from the markets endpoint instead of nested inside an event.
- **Open market**: a market currently available for trading.
- **Closed market**: a market no longer open for new trading.
- **Sports configuration**: public metadata describing supported sports structures and market types.
- **Terminal summary**: a retained public end-state summary for a market. It is not a historical timeline of earlier prices.
- **Crawl checkpoint**: a saved progress marker. It allows the script to resume catalog collection instead of starting over.

## Public Coverage

- Events: `15260`
- Unique embedded markets: `43294`
- Currently open flat markets: `2324`
- Retained closed flat markets: `2499`
- Sports configurations: `42`
- Terminal summaries collected in this run: `100`
- Earliest retained event creation timestamp: `2025-11-08T17:08:59Z`

## Crawl Checkpoints

| Collection | Pages retained | Next offset | Complete | Truncated in last run | Errors |
|---|---:|---:|---|---|---:|
| `closed_markets` | 10 | 2499 | True | False | 0 |
| `events` | 62 | 15260 | True | False | 0 |
| `open_markets` | 10 | 2324 | True | False | 0 |

## Scenario Inventory

| Scenario | Events | Embedded markets |
|---|---:|---:|
| `mlb` | 990 | 17537 |
| `additional_discovered_scenario_coverage` | 5325 | 6336 |
| `golf` | 35 | 3913 |
| `nba` | 1245 | 3531 |
| `atp` | 2726 | 2812 |
| `nhl` | 987 | 2804 |
| `wta` | 1237 | 1329 |
| `weather` | 185 | 1097 |
| `itf_men` | 879 | 879 |
| `itf_women` | 759 | 759 |
| `mls` | 230 | 690 |
| `esports` | 199 | 410 |
| `fifa_world_cup` | 0 | 362 |
| `culture` | 26 | 338 |
| `ufc` | 295 | 291 |
| `wnba` | 73 | 73 |
| `ipl` | 52 | 52 |
| `elections` | 13 | 44 |
| `f1` | 2 | 33 |
| `politics` | 2 | 4 |

## Market Types

| Type | Markets |
|---|---:|
| `SPORTS_MARKET_TYPE_MONEYLINE` | 13963 |
| `SPORTS_MARKET_TYPE_TOTAL` | 8053 |
| `SPORTS_MARKET_TYPE_SPREAD` | 7221 |
| `SPORTS_MARKET_TYPE_FUTURE` | 6372 |
| `SPORTS_MARKET_TYPE_PROP` | 5415 |
| `SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME` | 1917 |
| `SPORTS_MARKET_TYPE_UNSPECIFIED` | 353 |

The sports-market labels mean:

- **Moneyline**: which team or participant wins.
- **Total**: whether a combined score is above or below a stated number.
- **Spread**: whether a team wins after applying a stated points or goals handicap.
- **Future**: a longer-horizon result, such as a tournament winner.
- **Prop**: a narrower outcome, such as a player statistic.
- **Drawable outcome**: a contract where a tie or draw is a possible result.
- **Unspecified**: the public metadata did not provide a more precise sports-market type.

## Evidence Limits

- The public Polymarket US gateway exposes catalog metadata, current books, BBO, settlement, and terminal summaries.
- It does not expose public historical quote-by-quote BBO, historical L2 depth, or public historical candles.
- This report is descriptive catalog research. It must not be read as a retrospective arbitrage-profit report.