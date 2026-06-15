# Annual Scenario Analysis

Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)

## What This Report Answers

This report asks which kinds of prediction-market contracts produced the strongest retained cross-venue arbitrage evidence. It shows profitable examples directly in Markdown. You do not need to inspect the JSON files to understand the conclusions.

A category without a displayed profitable trade says `No profitable example found.` The category section also explains whether that means a complete negative screen, unavailable synchronized history, or no recovered strict equivalent pair.

## Evidence Quality

There are two international evidence layers. They answer different questions:

| Layer | Plain-English meaning | What it can prove |
|---|---|---|
| Annual official API proxy | Historical Kalshi and international Polymarket prices across the requested rolling year | Whether a price gap survives modeled fees and `1`, `2`, or `5` cents of assumed pair slippage. It cannot prove historical displayed depth. |
| PMXT archive inventory | `410` synchronized raw archive hours were discovered and verified | Which hours are eligible for executable replay. Inventory alone is not a profit result. |
| PMXT archived L2 replay | Stored multi-level order books for `1` replayed hours in this result file | Whether both visible books supported a requested order size after walking deeper prices. This is stronger executable evidence. |

The requested annual window is `2025-05-31T00:00:00Z` through `2026-05-31T00:00:00Z`. The oldest Kalshi close time reached so far is `2025-05-29T18:03:18.736056+00:00`. Full requested Kalshi history reached: `True`.

## Completeness Disclosure

The annual Kalshi historical cursor traversal and the combined two-venue profitability study are different things. The Kalshi historical traversal can be complete even when a public catalog endpoint on either venue still contains more rows than the configured retained-page cap.

- Combined international catalog scope: `all_reached_public_catalog_slices_complete`.
- Explicitly capped catalog slices: `none recorded`.
- Annual price-proxy scan scope: `all_retained_strict_pairs`.

When a slice is capped, the report describes the retained screen honestly. It does not claim that every possible cross-venue pair or profitable signal from that slice was exhaustively tested.

## Essential Terms

- **Prediction market**: a market where a contract pays `$1.00` if a stated event happens and `$0.00` otherwise.
- **Cross-venue arbitrage**: buying opposite outcomes on two exchanges when their combined cost is below the eventual `$1.00` payout.
- **Latency arbitrage**: a cross-venue opportunity caused by one exchange updating more slowly than another after new information arrives.
- **Gross edge**: `$1.00 - YES price - NO price`, before fees and slippage.
- **Net edge**: gross edge after subtracting exchange fees and slippage.
- **Slippage**: the added cost of filling deeper book prices when the best price does not have enough quantity.
- **L2**: a multi-level order book showing the best price and additional price levels behind it.
- **VWAP**: volume-weighted average price, meaning the average paid after accounting for how many contracts fill at each price level.
- **Parquet**: a compressed table-file format. PMXT stores archived order-book rows in Parquet files; it is a storage format, not a trading strategy.
- **Opportunity window**: a continuous period when the pair remains profitable after costs.
- **Pregame**: the period before a scheduled sporting event begins.
- **In-play**: the period after a scheduled sporting event begins but before its final result. The annual study does not simulate new entries after final resolution.
- **Sports event start unavailable**: the retained public metadata did not expose the scheduled start. The scanner inspects the final 24 hours before close but does not mislabel those observations as in-play.
- **Lifecycle bucket**: a time-to-resolution group for a market without a live contest. For example, an oil-price deadline is grouped by how many days or hours remain before its cutoff.
- **Modeled 100-contract order**: a hypothetical simultaneous purchase of 100 YES contracts and 100 matching NO contracts. In the annual proxy layer this is a sensitivity estimate, not proof of historical displayed quantity.
- **Reclassified non-sports sample window**: a historical sample that was initially given sports-style timing because of an acronym collision, then relabeled after taxonomy cleanup. It remains a price observation, but it is not in-play sports evidence.
- **ROI**: net profit divided by the cash used to buy the pair.

## Ranked Retained Results

This table ranks categories by the best positive retained net edge. A larger edge means more locked profit per paired contract. Counts are evidence rows, not a promise that every row could be captured live.

| Rank | Category | Annual positive proxy rows | PMXT positive 100-contract windows | Best retained net profit per contract |
|---:|---|---:|---:|---:|

## Official Category Ranking

The `blended score` is not dollars. First, each category is ranked by annual modeled portfolio profit and converted to a percentile from `0` to `100`. The same is done for executable PMXT portfolio profit. The final score is `0.70 × annual percentile + 0.30 × PMXT percentile`. A category absent from PMXT receives a neutral PMXT percentile of `50` and is labeled unvalidated.

| Rank | Category | Blended score | Annual percentile | Annual profit | Annual ROI | PMXT percentile | PMXT profit | Validation |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `golf` | 85.00 | 100.00 | $1341.983974 | 26.84% | 50.00 | $0.000000 | Not L2 validated |
| 2 | `f1` | 71.00 | 80.00 | $598.874083 | 11.98% | 50.00 | $0.000000 | Not L2 validated |
| 3 | `elections` | 58.00 | 40.00 | $8.060508 | 0.16% | 100.00 | $78.304350 | L2 validated |
| 4 | `mlb` | 57.00 | 60.00 | $255.559971 | 5.11% | 50.00 | $0.000000 | Not L2 validated |
| 5 | `esports` | 29.00 | 20.00 | $3.382675 | 0.07% | 50.00 | $0.000000 | Not L2 validated |
| 6 | `nba` | 15.00 | 0.00 | $2.656553 | 0.05% | 50.00 | $0.000000 | Not L2 validated |

## Detailed Subscenario Ranking

Each row combines category, competition stage, tournament or session level when applicable, market type, and entry timing. This is where NBA playoffs can be compared directly with NBA regular season, ATP Grand Slams, MLB postseason markets, and other specific situations.

| Rank | Subscenario | Score | Annual profit | PMXT profit | Validation |
|---:|---|---:|---:|---:|---|
| 1 | `golf | final_or_championship | future_or_winner | sports_pregame_slow` | 85.00 | $1294.393057 | $0.000000 | Not L2 validated |
| 2 | `f1 | regular_season_or_unspecified | race_or_f1_unspecified | moneyline_or_binary | sports_in_play` | 80.88 | $585.044760 | $0.000000 | Not L2 validated |
| 3 | `f1 | regular_season_or_unspecified | race_or_f1_unspecified | moneyline_or_binary | sports_pregame_slow` | 76.76 | $572.073380 | $0.000000 | Not L2 validated |
| 4 | `golf | final_or_championship | future_or_winner | sports_pregame_final_24h` | 72.65 | $433.098600 | $0.000000 | Not L2 validated |
| 5 | `mlb | regular_season_or_unspecified | future_or_winner | sports_in_play` | 68.53 | $250.106279 | $0.000000 | Not L2 validated |
| 6 | `f1 | regular_season_or_unspecified | race_or_f1_unspecified | moneyline_or_binary | sports_pregame_final_24h` | 64.41 | $231.861855 | $0.000000 | Not L2 validated |
| 7 | `f1 | regular_season_or_unspecified | race_or_f1_unspecified | future_or_winner | sports_in_play` | 60.29 | $197.481881 | $0.000000 | Not L2 validated |
| 8 | `golf | regular_season_or_unspecified | future_or_winner | sports_event_start_unavailable_final_24h` | 56.18 | $47.484771 | $0.000000 | Not L2 validated |
| 9 | `mlb | regular_season_or_unspecified | future_or_winner | sports_pregame_slow` | 52.06 | $31.491350 | $0.000000 | Not L2 validated |
| 10 | `f1 | regular_season_or_unspecified | race_or_f1_unspecified | future_or_winner | sports_pregame_slow` | 47.94 | $25.887103 | $0.000000 | Not L2 validated |
| 11 | `golf | final_or_championship | future_or_winner | sports_event_start_unavailable_final_24h` | 43.82 | $22.473412 | $0.000000 | Not L2 validated |
| 12 | `elections | regular_season_or_unspecified | moneyline_or_binary | lifecycle_final_24h` | 39.71 | $8.060508 | $0.000000 | Not L2 validated |
| 13 | `f1 | regular_season_or_unspecified | race_or_f1_unspecified | future_or_winner | sports_pregame_final_24h` | 35.59 | $3.712140 | $0.000000 | Not L2 validated |
| 14 | `esports | regular_season_or_unspecified | future_or_winner | sports_pregame_slow` | 31.47 | $3.382675 | $0.000000 | Not L2 validated |
| 15 | `elections | regular_season_or_unspecified | future_or_winner | lifecycle_more_than_30d` | 30.00 | $0.000000 | $78.304350 | L2 validated |
| 16 | `nba | regular_season_or_unspecified | future_or_winner | sports_in_play` | 27.35 | $2.656553 | $0.000000 | Not L2 validated |
| 17 | `golf | regular_season_or_unspecified | future_or_winner | sports_pregame_slow` | 23.24 | $2.028889 | $0.000000 | Not L2 validated |
| 18 | `f1 | regular_season_or_unspecified | race_or_f1_unspecified | future_or_winner | sports_event_start_unavailable_final_24h` | 19.12 | $0.913600 | $0.000000 | Not L2 validated |
| 1 | MLB | 780 | 0 | $0.512075 |
| 2 | Golf | 199 | 0 | $0.475300 |
| 3 | F1 | 632 | 0 | $0.466300 |
| 4 | Elections | 56 | 88 | $0.135475 |
| 5 | eSports | 8 | 0 | $0.016725 |
| 6 | NBA | 8 | 0 | $0.012651 |
| 7 | ATP | 0 | 0 | n/a |
| 8 | WTA | 0 | 0 | n/a |
| 9 | IPL | 0 | 0 | n/a |
| 10 | WNBA | 0 | 0 | n/a |
| 11 | NHL | 0 | 0 | n/a |
| 12 | ITF Men | 0 | 0 | n/a |
| 13 | ITF Women | 0 | 0 | n/a |
| 14 | UFC | 0 | 0 | n/a |
| 15 | FIFA World Cup | 0 | 0 | n/a |
| 16 | Politics | 0 | 0 | n/a |
| 17 | Weather | 0 | 0 | n/a |
| 18 | MLS | 0 | 0 | n/a |
| 19 | Culture | 0 | 0 | n/a |
| 20 | Additional Discovered Scenario Coverage | 0 | 0 | n/a |

## Broad Scenario Breakdown

The requested focus categories are useful for navigation, but the uncapped run also keeps markets outside that list. This table shows the broader classifications produced by the retained strict-pair scanner.

| Broad scenario | Strict pairs scanned | Pairs with synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `sports_baseball` | 14 | 12 | 780 | 409 | $0.512075 |
| `sports_golf` | 5 | 5 | 199 | 91 | $0.475300 |
| `sports_motorsport` | 13 | 13 | 632 | 256 | $0.466300 |
| `politics_elections` | 11 | 11 | 56 | 22 | $0.056411 |
| `sports_soccer` | 3 | 3 | 8 | 6 | $0.016725 |
| `sports_basketball` | 8 | 5 | 8 | 6 | $0.012651 |
| `other` | 10 | 0 | 0 | 0 | n/a |

## Current Comparison

`MLB` currently ranks first in the retained evidence because its best positive row has `$0.512075` of net profit per paired contract after the modeled costs. It contributes `780` annual proxy rows and `0` archived PMXT 100-contract windows.

A PMXT archived-L2 result is stronger than a proxy-only result because it includes visible order-book quantity. A proxy-only category can still be worth investigating, but it needs later depth validation before the report treats it as executable historical evidence.

`Golf` ranks next with a best retained net profit of `$0.475300` per paired contract.

## How To Interpret Differences

Fast-moving markets can be attractive because prices need frequent updates. A score, point, injury, weather reading, or breaking political development may reach one exchange before the other. That creates a temporary disagreement. The same speed can also make the opportunity difficult to capture: a profitable window may disappear before both orders fill.

A slower market can still be attractive when venues disagree for longer. Longer windows are easier to act on, but sparse trading can make the displayed quantity too small. This is why the PMXT L2 layer checks book depth and VWAP rather than looking only at one price.

## Category Detail

### NBA

**What this category means:** NBA basketball.

**Subcategories checked:** regular season, playoffs, finals, team, market type, pregame, and in-play.

**Why it could outperform:** Frequent scoring and injury updates can create fast venue-to-venue repricing gaps.

**Why it could underperform:** In-play windows can vanish quickly, and popular games may be efficiently priced.

**Retained profitable evidence:** `8` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `136175` Kalshi retained catalog rows and `53466` international Polymarket retained catalog rows were classified here; `10` strict equivalent pairs recovered; `10` pairs selected for the annual scanner; `5` pairs produced synchronized historical price snapshots; `6765` synchronized snapshots aligned; `4` matched pairs produced a positive proxy window.

**Best retained example:** `Suns vs. Celtics` with `$0.002651` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: sports_in_play` | 8 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `sports_in_play` | 5 | 2259 | 8 | 6 | $0.012651 |
| `sports_pregame_final_24h` | 8 | 4107 | 0 | 0 | n/a |
| `sports_pregame_slow` | 8 | 399 | 0 | 0 | n/a |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 8 | 6765 | 8 | 6 | $0.012651 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 8 | 6765 | 8 | 6 | $0.012651 |

**Profitable examples:**

- `2026-03-17T02:01:00+00:00`: buy YES on `kalshi` at `$0.970000` and NO on `polymarket` at `$0.005000` for `100` paired contracts. Pair cost per contract `$0.975000`; total entry fees for the order `$0.234875`; locked net profit `$0.002651` per paired contract; ROI `0.27%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-03-17T02:01:00+00:00`: buy YES on `polymarket` at `$0.005000` and NO on `kalshi` at `$0.970000` for `100` paired contracts. Pair cost per contract `$0.975000`; total entry fees for the order `$0.234875`; locked net profit `$0.002651` per paired contract; ROI `0.27%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### MLB

**What this category means:** Major League Baseball.

**Subcategories checked:** regular season, postseason, team, market type, pregame, and in-play.

**Why it could outperform:** Pitch-by-pitch changes and a large game schedule create many possible observations.

**Why it could underperform:** Props can have thin books, and superficially similar run-line or inning rules may not match.

**Retained profitable evidence:** `780` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `158572` Kalshi retained catalog rows and `18768` international Polymarket retained catalog rows were classified here; `14` strict equivalent pairs recovered; `14` pairs selected for the annual scanner; `12` pairs produced synchronized historical price snapshots; `13434` synchronized snapshots aligned; `10` matched pairs produced a positive proxy window.

**Best retained example:** `Athletics vs. Baltimore Orioles` with `$0.502075` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: sports_in_play` | 759 |
| `annual proxy phase: sports_pregame_slow` | 21 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `sports_in_play` | 12 | 4920 | 759 | 401 | $0.512075 |
| `sports_pregame_final_24h` | 14 | 7344 | 0 | 0 | n/a |
| `sports_pregame_slow` | 14 | 1170 | 21 | 8 | $0.050245 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 14 | 13434 | 780 | 409 | $0.512075 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 14 | 13434 | 780 | 409 | $0.512075 |

**Profitable examples:**

- `2026-05-09T01:53:00+00:00`: buy YES on `polymarket` at `$0.000500` and NO on `kalshi` at `$0.460000` for `100` paired contracts. Pair cost per contract `$0.460500`; total entry fees for the order `$1.742499`; locked net profit `$0.502075` per paired contract; ROI `100.83%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-05-09T01:53:00+00:00`: buy YES on `kalshi` at `$0.460000` and NO on `polymarket` at `$0.000500` for `100` paired contracts. Pair cost per contract `$0.460500`; total entry fees for the order `$1.742499`; locked net profit `$0.502075` per paired contract; ROI `100.83%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-05-10T03:31:00+00:00`: buy YES on `kalshi` at `$0.490000` and NO on `polymarket` at `$0.000500` for `100` paired contracts. Pair cost per contract `$0.490500`; total entry fees for the order `$1.752499`; locked net profit `$0.471975` per paired contract; ROI `89.38%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### Golf

**What this category means:** golf.

**Subcategories checked:** tournament, round, participant, placement, pre-event, and in-play.

**Why it could outperform:** A multi-day tournament creates many leaderboard changes and long observation windows.

**Why it could underperform:** Round, cut, tie, and dead-heat wording can differ across venues.

**Retained profitable evidence:** `199` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `27270` Kalshi retained catalog rows and `5666` international Polymarket retained catalog rows were classified here; `10` strict equivalent pairs recovered; `10` pairs selected for the annual scanner; `5` pairs produced synchronized historical price snapshots; `1860` synchronized snapshots aligned; `5` matched pairs produced a positive proxy window.

**Best retained example:** `Will Michael Kim win the 2026 PGA Championship?` with `$0.465300` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: sports_event_start_unavailable_final_24h` | 110 |
| `annual proxy phase: sports_pregame_slow` | 86 |
| `annual proxy phase: sports_pregame_final_24h` | 3 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `sports_event_start_unavailable_final_24h` | 3 | 1248 | 110 | 63 | $0.219925 |
| `sports_pregame_final_24h` | 2 | 3 | 3 | 3 | $0.474200 |
| `sports_pregame_slow` | 5 | 609 | 86 | 25 | $0.475300 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 5 | 1860 | 199 | 91 | $0.475300 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `final_or_championship` | 3 | 1119 | 72 | 40 | $0.475300 |
| `regular_season_or_unspecified` | 2 | 741 | 127 | 51 | $0.219925 |

**Profitable examples:**

- `2026-05-11T17:00:00+00:00`: buy YES on `kalshi` at `$0.002000` and NO on `polymarket` at `$0.500000` for `100` paired contracts. Pair cost per contract `$0.502000`; total entry fees for the order `$1.270000`; locked net profit `$0.465300` per paired contract; ROI `87.02%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-05-11T17:00:00+00:00`: buy YES on `kalshi` at `$0.003000` and NO on `polymarket` at `$0.500000` for `100` paired contracts. Pair cost per contract `$0.503000`; total entry fees for the order `$1.280000`; locked net profit `$0.464200` per paired contract; ROI `86.64%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-05-12T02:00:00+00:00`: buy YES on `kalshi` at `$0.002000` and NO on `polymarket` at `$0.505000` for `100` paired contracts. Pair cost per contract `$0.507000`; total entry fees for the order `$1.269875`; locked net profit `$0.460301` per paired contract; ROI `85.29%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### ATP

**What this category means:** ATP men's tennis.

**Subcategories checked:** tournament level, participant, match, set, pregame, and in-play.

**Why it could outperform:** Point-by-point tennis scoring creates frequent fair-value updates.

**Why it could underperform:** Trading suspensions and thin books can make a visible gap difficult to capture.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `24349` Kalshi retained catalog rows and `41387` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### WTA

**What this category means:** WTA women's tennis.

**Subcategories checked:** tournament level, participant, match, set, pregame, and in-play.

**Why it could outperform:** Point-by-point tennis scoring creates frequent fair-value updates.

**Why it could underperform:** Trading suspensions and thin books can make a visible gap difficult to capture.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `9840` Kalshi retained catalog rows and `23873` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### eSports

**What this category means:** eSports.

**Subcategories checked:** game title, tournament, participant, map or match market, pregame, and in-play.

**Why it could outperform:** Map and match state can update rapidly across many competitions.

**Why it could underperform:** Different map, series, and overtime rules can make apparently similar contracts non-equivalent.

**Retained profitable evidence:** `8` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `10005` Kalshi retained catalog rows and `65743` international Polymarket retained catalog rows were classified here; `3` strict equivalent pairs recovered; `3` pairs selected for the annual scanner; `3` pairs produced synchronized historical price snapshots; `1977` synchronized snapshots aligned; `2` matched pairs produced a positive proxy window.

**Best retained example:** `Will Alireza Firouzja win the 2025 Chess Esports World Cup?` with `$0.006725` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: sports_pregame_slow` | 8 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `sports_event_start_unavailable_final_24h` | 3 | 603 | 0 | 0 | n/a |
| `sports_pregame_slow` | 3 | 1374 | 8 | 6 | $0.016725 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 3 | 1977 | 8 | 6 | $0.016725 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 3 | 1977 | 8 | 6 | $0.016725 |

**Profitable examples:**

- `2025-07-29T18:00:00+00:00`: buy YES on `kalshi` at `$0.110000` and NO on `polymarket` at `$0.850000` for `100` paired contracts. Pair cost per contract `$0.960000`; total entry fees for the order `$1.327500`; locked net profit `$0.006725` per paired contract; ROI `0.68%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### IPL

**What this category means:** Indian Premier League cricket.

**Subcategories checked:** regular stage, playoffs, team, pregame, and in-play.

**Why it could outperform:** Live cricket contains frequent state changes and popular matches can attract attention.

**Why it could underperform:** Match, innings, and weather-abandonment rules need especially careful comparison.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `1931` Kalshi retained catalog rows and `22935` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### WNBA

**What this category means:** WNBA basketball.

**Subcategories checked:** regular season, playoffs, finals, team, market type, pregame, and in-play.

**Why it could outperform:** Live scoring can create the same repricing pattern as NBA games.

**Why it could underperform:** The smaller catalog and thinner books can reduce the number of executable opportunities.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `3824` Kalshi retained catalog rows and `847` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### NHL

**What this category means:** National Hockey League.

**Subcategories checked:** regular season, playoffs, finals, team, market type, pregame, and in-play.

**Why it could outperform:** Goals have a large immediate effect on win probability, creating sharp repricing moments.

**Why it could underperform:** Goal props and regulation-versus-overtime wording can differ across venues.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `126281` Kalshi retained catalog rows and `7406` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### ITF Men

**What this category means:** ITF men's tennis.

**Subcategories checked:** tournament, participant, match, pregame, and in-play.

**Why it could outperform:** Lower-tier tennis can reprice frequently while receiving less cross-venue attention.

**Why it could underperform:** Books may be very thin, and point-level suspensions can increase execution risk.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `7896` Kalshi retained catalog rows and `937` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### ITF Women

**What this category means:** ITF women's tennis.

**Subcategories checked:** tournament, participant, match, pregame, and in-play.

**Why it could outperform:** Lower-tier tennis can reprice frequently while receiving less cross-venue attention.

**Why it could underperform:** Books may be very thin, and point-level suspensions can increase execution risk.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `7406` Kalshi retained catalog rows and `1084` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### UFC

**What this category means:** UFC mixed martial arts.

**Subcategories checked:** card, fighter, bout winner, prop, pre-event, and in-play where listed.

**Why it could outperform:** Fight outcomes can reprice sharply after visible momentum changes.

**Why it could underperform:** Bout listings are less frequent, and cancellation or method-of-victory rules can differ.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `5638` Kalshi retained catalog rows and `5531` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### FIFA World Cup

**What this category means:** FIFA World Cup.

**Subcategories checked:** qualification, group, knockout round, team, winner, pre-event, and in-play.

**Why it could outperform:** Major matches and tournament developments can generate large attention-driven repricing.

**Why it could underperform:** Qualification, group, knockout, overtime, and tournament-winner wording must match exactly.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `2604` Kalshi retained catalog rows and `5449` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### Politics

**What this category means:** politics.

**Subcategories checked:** candidate, office, cutoff date, and time remaining before settlement.

**Why it could outperform:** Breaking news can produce longer-lived disagreement between venues.

**Why it could underperform:** Office, candidate, cutoff date, and settlement-source wording often differ subtly.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `5239` Kalshi retained catalog rows and `5405` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### Weather

**What this category means:** weather.

**Subcategories checked:** location, threshold, measurement window, and time remaining before settlement.

**Why it could outperform:** Forecast updates and measured thresholds can create repeatable repricing over a known lifecycle.

**Why it could underperform:** Station, measurement source, threshold, and time window must be identical.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `50866` Kalshi retained catalog rows and `56636` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### MLS

**What this category means:** Major League Soccer.

**Subcategories checked:** regular season, playoffs, club, market type, pregame, and in-play.

**Why it could outperform:** Live goals and match events can produce sharp repricing moments.

**Why it could underperform:** Draw handling and regulation-versus-extra-time wording can make pairs non-equivalent.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `2864` Kalshi retained catalog rows and `7443` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### Elections

**What this category means:** elections.

**Subcategories checked:** district, party, nominee, winner, cutoff date, and time remaining before settlement.

**Why it could outperform:** News, endorsements, polls, and long lifecycles can leave venues disagreeing for longer.

**Why it could underperform:** District, nominee, cutoff date, and official settlement source require manual review.

**Retained profitable evidence:** `56` annual price-proxy rows and `88` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `3547` Kalshi retained catalog rows and `141914` international Polymarket retained catalog rows were classified here; `11` strict equivalent pairs recovered; `11` pairs selected for the annual scanner; `11` pairs produced synchronized historical price snapshots; `1563` synchronized snapshots aligned; `3` matched pairs produced a positive proxy window.

**Best retained example:** `Argentina Presidential Election Winner - Will Javier Milei win the 2027 Argentina presidential election?` with `$0.135475` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `PMXT timing phase: lifecycle_more_than_30d` | 88 |
| `PMXT market type: future_or_winner` | 88 |
| `PMXT competition phase: regular_season_or_unspecified` | 88 |
| `annual proxy phase: lifecycle_final_24h` | 56 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `lifecycle_final_24h` | 11 | 1563 | 56 | 22 | $0.056411 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `moneyline_or_binary` | 11 | 1563 | 56 | 22 | $0.056411 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 11 | 1563 | 56 | 22 | $0.056411 |

**Profitable examples:**

- `2026-05-23T07:15:48.744000+00:00`: buy YES on `polymarket` at `$0.445474` and NO on `kalshi` at `$0.390000` for `100` paired contracts. Pair cost per contract `$0.835474`; total entry fees for the order `$2.905135`; locked net profit `$0.135475` per paired contract; ROI `15.67%`. Evidence: `pmxt_archived_l2_exact_pair`.
- `2026-05-05T22:35:00+00:00`: buy YES on `kalshi` at `$0.890000` and NO on `polymarket` at `$0.035000` for `100` paired contracts. Pair cost per contract `$0.925000`; total entry fees for the order `$0.858875`; locked net profit `$0.046411` per paired contract; ROI `4.87%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-05-05T16:10:00+00:00`: buy YES on `polymarket` at `$0.019500` and NO on `kalshi` at `$0.950000` for `100` paired contracts. Pair cost per contract `$0.969500`; total entry fees for the order `$0.435599`; locked net profit `$0.006144` per paired contract; ROI `0.62%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### Culture

**What this category means:** culture and entertainment.

**Subcategories checked:** topic, event, cutoff date, and time remaining before settlement.

**Why it could outperform:** Less standardized news-driven questions can receive uneven attention across venues.

**Why it could underperform:** Sparse liquidity and wording differences can make a large proxy edge less executable.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `10158` Kalshi retained catalog rows and `25326` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### F1

**What this category means:** Formula One.

**Subcategories checked:** race, qualifying, driver, constructor, placement, pre-event, and in-play.

**Why it could outperform:** Qualifying, race incidents, and long event windows create repeated state changes.

**Why it could underperform:** Placement, constructor, tie, and race-classification rules can differ.

**Retained profitable evidence:** `632` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `2018` Kalshi retained catalog rows and `3124` international Polymarket retained catalog rows were classified here; `13` strict equivalent pairs recovered; `13` pairs selected for the annual scanner; `13` pairs produced synchronized historical price snapshots; `7596` synchronized snapshots aligned; `11` matched pairs produced a positive proxy window.

**Best retained example:** `Will Lewis Hamilton achieve the fastest lap at the 2025 F1 Qatar Grand Prix?` with `$0.456300` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: sports_pregame_slow` | 388 |
| `annual proxy phase: sports_pregame_final_24h` | 132 |
| `annual proxy phase: sports_in_play` | 102 |
| `annual proxy phase: sports_event_start_unavailable_final_24h` | 10 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `sports_event_start_unavailable_final_24h` | 5 | 2217 | 10 | 9 | $0.011827 |
| `sports_in_play` | 8 | 657 | 102 | 72 | $0.466300 |
| `sports_pregame_final_24h` | 8 | 2781 | 132 | 62 | $0.324600 |
| `sports_pregame_slow` | 11 | 1941 | 388 | 113 | $0.439801 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 7 | 4689 | 117 | 33 | $0.293331 |
| `moneyline_or_binary` | 6 | 2907 | 515 | 223 | $0.466300 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 13 | 7596 | 632 | 256 | $0.466300 |

**Profitable examples:**

- `2025-11-30T20:26:00+00:00`: buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.500500` for `100` paired contracts. Pair cost per contract `$0.510500`; total entry fees for the order `$1.319999`; locked net profit `$0.456300` per paired contract; ROI `83.92%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2025-11-29T20:20:00+00:00`: buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.505500` for `100` paired contracts. Pair cost per contract `$0.515500`; total entry fees for the order `$1.319849`; locked net profit `$0.451302` per paired contract; ROI `82.25%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-03-11T13:00:00+00:00`: buy YES on `kalshi` at `$0.040000` and NO on `polymarket` at `$0.495000` for `100` paired contracts. Pair cost per contract `$0.535000`; total entry fees for the order `$1.519875`; locked net profit `$0.429801` per paired contract; ROI `75.38%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### Additional Discovered Scenario Coverage

**What this category means:** additional discovered markets.

**Subcategories checked:** recognizable markets outside the requested list, including other sports and public-event binaries.

**Why it could outperform:** The broad discovery bucket can reveal useful markets outside the requested list.

**Why it could underperform:** Because it combines different market families, each standout needs its own interpretation.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `strict_pairs_scanned_but_no_synchronized_price_snapshots_available`.

**Coverage funnel:** `756066` Kalshi retained catalog rows and `662079` international Polymarket retained catalog rows were classified here; `10` strict equivalent pairs recovered; `10` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `lifecycle_final_24h` | 10 | 0 | 0 | 0 | n/a |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `moneyline_or_binary` | 10 | 0 | 0 | 0 | n/a |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 10 | 0 | 0 | 0 | n/a |

No profitable example found.

Equivalent-looking pairs reached the scanner, but the official histories did not produce prices aligned to the same timestamps on both venues. The missing example is a data-availability result, not proof of no opportunity.

## Important Limits

- A price-history proxy is a screening result, not proof that both trades were fillable at the same instant.
- Archived L2 replay enforces visible quantity, but it still cannot guarantee live queue position or network latency.
- Automatically matched contracts still require a manual settlement-rule review before live trading.
- Polymarket US public catalog data is analyzed separately and must not be treated as historical profit evidence.