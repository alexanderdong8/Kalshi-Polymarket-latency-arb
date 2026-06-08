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
| PMXT archive inventory | `259` synchronized raw archive hours were discovered and verified | Which hours are eligible for executable replay. Inventory alone is not a profit result. |
| PMXT archived L2 replay | Stored multi-level order books for `1` replayed hours in this result file | Whether both visible books supported a requested order size after walking deeper prices. This is stronger executable evidence. |

The requested annual window is `2025-05-31T00:00:00Z` through `2026-05-31T00:00:00Z`. The oldest Kalshi close time reached so far is `2025-05-29T18:03:18.736056+00:00`. Full requested Kalshi history reached: `True`.

## Completeness Disclosure

The annual Kalshi historical cursor traversal and the combined two-venue profitability study are different things. The Kalshi historical traversal can be complete even when a public catalog endpoint on either venue still contains more rows than the configured retained-page cap.

- Combined international catalog scope: `bounded_retained_screen_due_explicit_public_catalog_caps`.
- Explicitly capped catalog slices: `2026-01: Polymarket; 2026-02: Polymarket; 2026-03: Polymarket; 2026-04: Polymarket; 2026-05: Kalshi and Polymarket`.
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
| 1 | Culture | 1192 | 0 | $0.664211 |
| 2 | Golf | 100014 | 0 | $0.654530 |
| 3 | Politics | 2328 | 0 | $0.567300 |
| 4 | Elections | 1149 | 88 | $0.534281 |
| 5 | Additional Discovered Scenario Coverage | 926 | 0 | $0.461801 |
| 6 | NBA | 0 | 0 | n/a |
| 7 | MLB | 0 | 0 | n/a |
| 8 | ATP | 0 | 0 | n/a |
| 9 | WTA | 0 | 0 | n/a |
| 10 | eSports | 0 | 0 | n/a |
| 11 | IPL | 0 | 0 | n/a |
| 12 | WNBA | 0 | 0 | n/a |
| 13 | NHL | 0 | 0 | n/a |
| 14 | ITF Men | 0 | 0 | n/a |
| 15 | ITF Women | 0 | 0 | n/a |
| 16 | UFC | 0 | 0 | n/a |
| 17 | FIFA World Cup | 0 | 0 | n/a |
| 18 | Weather | 0 | 0 | n/a |
| 19 | MLS | 0 | 0 | n/a |
| 20 | F1 | 0 | 0 | n/a |

## Broad Scenario Breakdown

The requested focus categories are useful for navigation, but the uncapped run also keeps markets outside that list. This table shows the broader classifications produced by the retained strict-pair scanner.

| Broad scenario | Strict pairs scanned | Pairs with synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `entertainment` | 75 | 65 | 1192 | 417 | $0.664211 |
| `sports_golf` | 768 | 767 | 100014 | 26046 | $0.654530 |
| `politics_other` | 13 | 11 | 2328 | 635 | $0.567300 |
| `politics_elections` | 115 | 103 | 1149 | 490 | $0.534281 |
| `other` | 45 | 12 | 675 | 157 | $0.461801 |
| `sports_chess` | 3 | 3 | 251 | 90 | $0.424100 |

## Current Comparison

`Culture` currently ranks first in the retained evidence because its best positive row has `$0.664211` of net profit per paired contract after the modeled costs. It contributes `1192` annual proxy rows and `0` archived PMXT 100-contract windows.

A PMXT archived-L2 result is stronger than a proxy-only result because it includes visible order-book quantity. A proxy-only category can still be worth investigating, but it needs later depth validation before the report treats it as executable historical evidence.

`Golf` ranks next with a best retained net profit of `$0.654530` per paired contract.

## How To Interpret Differences

Fast-moving markets can be attractive because prices need frequent updates. A score, point, injury, weather reading, or breaking political development may reach one exchange before the other. That creates a temporary disagreement. The same speed can also make the opportunity difficult to capture: a profitable window may disappear before both orders fill.

A slower market can still be attractive when venues disagree for longer. Longer windows are easier to act on, but sparse trading can make the displayed quantity too small. This is why the PMXT L2 layer checks book depth and VWAP rather than looking only at one price.

## Category Detail

### NBA

**What this category means:** NBA basketball.

**Subcategories checked:** regular season, playoffs, finals, team, market type, pregame, and in-play.

**Why it could outperform:** Frequent scoring and injury updates can create fast venue-to-venue repricing gaps.

**Why it could underperform:** In-play windows can vanish quickly, and popular games may be efficiently priced.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `131901` Kalshi retained catalog rows and `38211` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### MLB

**What this category means:** Major League Baseball.

**Subcategories checked:** regular season, postseason, team, market type, pregame, and in-play.

**Why it could outperform:** Pitch-by-pitch changes and a large game schedule create many possible observations.

**Why it could underperform:** Props can have thin books, and superficially similar run-line or inning rules may not match.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `133099` Kalshi retained catalog rows and `8709` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### Golf

**What this category means:** golf.

**Subcategories checked:** tournament, round, participant, placement, pre-event, and in-play.

**Why it could outperform:** A multi-day tournament creates many leaderboard changes and long observation windows.

**Why it could underperform:** Round, cut, tie, and dead-heat wording can differ across venues.

**Retained profitable evidence:** `100014` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `26124` Kalshi retained catalog rows and `4554` international Polymarket retained catalog rows were classified here; `769` strict equivalent pairs recovered; `769` pairs selected for the annual scanner; `767` pairs produced synchronized historical price snapshots; `417183` synchronized snapshots aligned; `710` matched pairs produced a positive proxy window.

**Best retained example:** `Will Justin Rose win the 2025 FedEx St. Jude Championship?` with `$0.654530` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: sports_pregame_slow` | 69734 |
| `annual proxy phase: sports_event_start_unavailable_final_24h` | 30280 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `sports_event_start_unavailable_final_24h` | 763 | 218937 | 30280 | 15356 | $0.654530 |
| `sports_pregame_slow` | 758 | 198246 | 69734 | 10690 | $0.467800 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 768 | 417183 | 100014 | 26046 | $0.654530 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `final_or_championship` | 382 | 208563 | 48040 | 10670 | $0.654530 |
| `regular_season_or_unspecified` | 386 | 208620 | 51974 | 15376 | $0.466800 |

**Profitable examples:**

- `2025-08-10T22:55:00+00:00`: buy YES on `polymarket` at `$0.314000` and NO on `kalshi` at `$0.010000` for `100` paired contracts. Pair cost per contract `$0.324000`; total entry fees for the order `$1.147020`; locked net profit `$0.654530` per paired contract; ROI `189.46%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2025-08-10T22:55:00+00:00`: buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.358500` for `100` paired contracts. Pair cost per contract `$0.368500`; total entry fees for the order `$1.219889`; locked net profit `$0.609301` per paired contract; ROI `155.95%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2025-08-03T02:55:00+00:00`: buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.498500` for `100` paired contracts. Pair cost per contract `$0.508500`; total entry fees for the order `$1.319989`; locked net profit `$0.468300` per paired contract; ROI `88.08%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### ATP

**What this category means:** ATP men's tennis.

**Subcategories checked:** tournament level, participant, match, set, pregame, and in-play.

**Why it could outperform:** Point-by-point tennis scoring creates frequent fair-value updates.

**Why it could underperform:** Trading suspensions and thin books can make a visible gap difficult to capture.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `23649` Kalshi retained catalog rows and `27824` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### WTA

**What this category means:** WTA women's tennis.

**Subcategories checked:** tournament level, participant, match, set, pregame, and in-play.

**Why it could outperform:** Point-by-point tennis scoring creates frequent fair-value updates.

**Why it could underperform:** Trading suspensions and thin books can make a visible gap difficult to capture.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `9195` Kalshi retained catalog rows and `17344` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### eSports

**What this category means:** eSports.

**Subcategories checked:** game title, tournament, participant, map or match market, pregame, and in-play.

**Why it could outperform:** Map and match state can update rapidly across many competitions.

**Why it could underperform:** Different map, series, and overtime rules can make apparently similar contracts non-equivalent.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `9155` Kalshi retained catalog rows and `32618` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### IPL

**What this category means:** Indian Premier League cricket.

**Subcategories checked:** regular stage, playoffs, team, pregame, and in-play.

**Why it could outperform:** Live cricket contains frequent state changes and popular matches can attract attention.

**Why it could underperform:** Match, innings, and weather-abandonment rules need especially careful comparison.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `1699` Kalshi retained catalog rows and `10280` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### WNBA

**What this category means:** WNBA basketball.

**Subcategories checked:** regular season, playoffs, finals, team, market type, pregame, and in-play.

**Why it could outperform:** Live scoring can create the same repricing pattern as NBA games.

**Why it could underperform:** The smaller catalog and thinner books can reduce the number of executable opportunities.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `3768` Kalshi retained catalog rows and `505` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### NHL

**What this category means:** National Hockey League.

**Subcategories checked:** regular season, playoffs, finals, team, market type, pregame, and in-play.

**Why it could outperform:** Goals have a large immediate effect on win probability, creating sharp repricing moments.

**Why it could underperform:** Goal props and regulation-versus-overtime wording can differ across venues.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `124244` Kalshi retained catalog rows and `6464` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### ITF Men

**What this category means:** ITF men's tennis.

**Subcategories checked:** tournament, participant, match, pregame, and in-play.

**Why it could outperform:** Lower-tier tennis can reprice frequently while receiving less cross-venue attention.

**Why it could underperform:** Books may be very thin, and point-level suspensions can increase execution risk.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `6462` Kalshi retained catalog rows and `0` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### ITF Women

**What this category means:** ITF women's tennis.

**Subcategories checked:** tournament, participant, match, pregame, and in-play.

**Why it could outperform:** Lower-tier tennis can reprice frequently while receiving less cross-venue attention.

**Why it could underperform:** Books may be very thin, and point-level suspensions can increase execution risk.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `5656` Kalshi retained catalog rows and `0` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### UFC

**What this category means:** UFC mixed martial arts.

**Subcategories checked:** card, fighter, bout winner, prop, pre-event, and in-play where listed.

**Why it could outperform:** Fight outcomes can reprice sharply after visible momentum changes.

**Why it could underperform:** Bout listings are less frequent, and cancellation or method-of-victory rules can differ.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `5238` Kalshi retained catalog rows and `4667` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### FIFA World Cup

**What this category means:** FIFA World Cup.

**Subcategories checked:** qualification, group, knockout round, team, winner, pre-event, and in-play.

**Why it could outperform:** Major matches and tournament developments can generate large attention-driven repricing.

**Why it could underperform:** Qualification, group, knockout, overtime, and tournament-winner wording must match exactly.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `2535` Kalshi retained catalog rows and `3034` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### Politics

**What this category means:** politics.

**Subcategories checked:** candidate, office, cutoff date, and time remaining before settlement.

**Why it could outperform:** Breaking news can produce longer-lived disagreement between venues.

**Why it could underperform:** Office, candidate, cutoff date, and settlement-source wording often differ subtly.

**Retained profitable evidence:** `2328` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `5073` Kalshi retained catalog rows and `3998` international Polymarket retained catalog rows were classified here; `16` strict equivalent pairs recovered; `16` pairs selected for the annual scanner; `11` pairs produced synchronized historical price snapshots; `5049` synchronized snapshots aligned; `11` matched pairs produced a positive proxy window.

**Best retained example:** `Will Keir Starmer say "Tax" at the next Prime Minister's Questions?` with `$0.567300` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: lifecycle_final_24h` | 1976 |
| `annual proxy phase: lifecycle_30d_to_24h` | 352 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `lifecycle_30d_to_24h` | 14 | 567 | 352 | 115 | $0.365111 |
| `lifecycle_final_24h` | 14 | 4482 | 1976 | 520 | $0.567300 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `moneyline_or_binary` | 14 | 5049 | 2328 | 635 | $0.567300 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 14 | 5049 | 2328 | 635 | $0.567300 |

**Profitable examples:**

- `2026-01-14T12:05:00+00:00`: buy YES on `polymarket` at `$0.400000` and NO on `kalshi` at `$0.010000` for `100` paired contracts. Pair cost per contract `$0.410000`; total entry fees for the order `$1.270000`; locked net profit `$0.567300` per paired contract; ROI `131.11%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-01-14T12:05:00+00:00`: buy YES on `polymarket` at `$0.470000` and NO on `kalshi` at `$0.010000` for `100` paired contracts. Pair cost per contract `$0.480000`; total entry fees for the order `$1.315500`; locked net profit `$0.496845` per paired contract; ROI `98.75%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-01-14T12:30:00+00:00`: buy YES on `polymarket` at `$0.470000` and NO on `kalshi` at `$0.010000` for `100` paired contracts. Pair cost per contract `$0.480000`; total entry fees for the order `$1.315500`; locked net profit `$0.496845` per paired contract; ROI `98.75%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### Weather

**What this category means:** weather.

**Subcategories checked:** location, threshold, measurement window, and time remaining before settlement.

**Why it could outperform:** Forecast updates and measured thresholds can create repeatable repricing over a known lifecycle.

**Why it could underperform:** Station, measurement source, threshold, and time window must be identical.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `45884` Kalshi retained catalog rows and `26673` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### MLS

**What this category means:** Major League Soccer.

**Subcategories checked:** regular season, playoffs, club, market type, pregame, and in-play.

**Why it could outperform:** Live goals and match events can produce sharp repricing moments.

**Why it could underperform:** Draw handling and regulation-versus-extra-time wording can make pairs non-equivalent.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `2684` Kalshi retained catalog rows and `4913` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### Elections

**What this category means:** elections.

**Subcategories checked:** district, party, nominee, winner, cutoff date, and time remaining before settlement.

**Why it could outperform:** News, endorsements, polls, and long lifecycles can leave venues disagreeing for longer.

**Why it could underperform:** District, nominee, cutoff date, and official settlement source require manual review.

**Retained profitable evidence:** `1149` annual price-proxy rows and `88` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `3367` Kalshi retained catalog rows and `90043` international Polymarket retained catalog rows were classified here; `114` strict equivalent pairs recovered; `114` pairs selected for the annual scanner; `103` pairs produced synchronized historical price snapshots; `21435` synchronized snapshots aligned; `35` matched pairs produced a positive proxy window.

**Best retained example:** `Will Donna Miller be the Democratic Nominee for IL-02?` with `$0.534281` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: lifecycle_final_24h` | 1149 |
| `PMXT timing phase: lifecycle_more_than_30d` | 88 |
| `PMXT market type: future_or_winner` | 88 |
| `PMXT competition phase: regular_season_or_unspecified` | 88 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `lifecycle_final_24h` | 114 | 21435 | 1149 | 490 | $0.534281 |
| `lifecycle_more_than_30d` | 2 | 0 | 0 | 0 | n/a |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 6 | 0 | 0 | 0 | n/a |
| `moneyline_or_binary` | 108 | 21435 | 1149 | 490 | $0.534281 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 114 | 21435 | 1149 | 490 | $0.534281 |

**Profitable examples:**

- `2026-05-23T07:15:48.744000+00:00`: buy YES on `polymarket` at `$0.445474` and NO on `kalshi` at `$0.390000` for `100` paired contracts. Pair cost per contract `$0.835474`; total entry fees for the order `$2.905135`; locked net profit `$0.135475` per paired contract; ROI `15.67%`. Evidence: `pmxt_archived_l2_strict_candidate_pending_manual_rule_review`.
- `2026-03-18T00:25:00+00:00`: buy YES on `polymarket` at `$0.175000` and NO on `kalshi` at `$0.260000` for `100` paired contracts. Pair cost per contract `$0.435000`; total entry fees for the order `$2.071875`; locked net profit `$0.534281` per paired contract; ROI `114.72%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2026-03-18T00:25:00+00:00`: buy YES on `kalshi` at `$0.250000` and NO on `polymarket` at `$0.290000` for `100` paired contracts. Pair cost per contract `$0.540000`; total entry fees for the order `$2.349500`; locked net profit `$0.426505` per paired contract; ROI `74.37%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### Culture

**What this category means:** culture and entertainment.

**Subcategories checked:** topic, event, cutoff date, and time remaining before settlement.

**Why it could outperform:** Less standardized news-driven questions can receive uneven attention across venues.

**Why it could underperform:** Sparse liquidity and wording differences can make a large proxy edge less executable.

**Retained profitable evidence:** `1192` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `9594` Kalshi retained catalog rows and `15130` international Polymarket retained catalog rows were classified here; `75` strict equivalent pairs recovered; `75` pairs selected for the annual scanner; `65` pairs produced synchronized historical price snapshots; `19923` synchronized snapshots aligned; `19` matched pairs produced a positive proxy window.

**Best retained example:** `Will Bulgaria win the televote for Eurovision 2026?` with `$0.664211` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: lifecycle_final_24h` | 1192 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `lifecycle_final_24h` | 75 | 19923 | 1192 | 417 | $0.664211 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 70 | 16527 | 140 | 94 | $0.664211 |
| `moneyline_or_binary` | 5 | 3396 | 1052 | 323 | $0.516925 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 75 | 19923 | 1192 | 417 | $0.664211 |

**Profitable examples:**

- `2026-05-16T22:55:00+00:00`: buy YES on `polymarket` at `$0.304500` and NO on `kalshi` at `$0.010000` for `100` paired contracts. Pair cost per contract `$0.314500`; total entry fees for the order `$1.128899`; locked net profit `$0.664211` per paired contract; ROI `197.81%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2025-12-07T05:40:00+00:00`: buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.450000` for `100` paired contracts. Pair cost per contract `$0.460000`; total entry fees for the order `$1.307500`; locked net profit `$0.516925` per paired contract; ROI `107.01%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2025-12-07T05:40:00+00:00`: buy YES on `polymarket` at `$0.495000` and NO on `kalshi` at `$0.010000` for `100` paired contracts. Pair cost per contract `$0.505000`; total entry fees for the order `$1.319875`; locked net profit `$0.471801` per paired contract; ROI `89.32%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

### F1

**What this category means:** Formula One.

**Subcategories checked:** race, qualifying, driver, constructor, placement, pre-event, and in-play.

**Why it could outperform:** Qualifying, race incidents, and long event windows create repeated state changes.

**Why it could underperform:** Placement, constructor, tie, and race-classification rules can differ.

**Retained profitable evidence:** `0` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `no_strict_equivalent_cross_venue_pair_recovered`.

**Coverage funnel:** `1807` Kalshi retained catalog rows and `3124` international Polymarket retained catalog rows were classified here; `0` strict equivalent pairs recovered; `0` pairs selected for the annual scanner; `0` pairs produced synchronized historical price snapshots; `0` synchronized snapshots aligned; `0` matched pairs produced a positive proxy window.

No profitable example found.

This is not a claim that the category was unprofitable. The retained catalogs did not produce a strictly equivalent Kalshi-versus-Polymarket contract pair, so the arbitrage arithmetic could not be run.

### Additional Discovered Scenario Coverage

**What this category means:** additional discovered markets.

**Subcategories checked:** recognizable markets outside the requested list, including other sports and public-event binaries.

**Why it could outperform:** The broad discovery bucket can reveal useful markets outside the requested list.

**Why it could underperform:** Because it combines different market families, each standout needs its own interpretation.

**Retained profitable evidence:** `926` annual price-proxy rows and `0` archived PMXT 100-contract opportunity windows.

**Annual coverage status:** `profitable_price_proxy_window_found`.

**Coverage funnel:** `745116` Kalshi retained catalog rows and `405263` international Polymarket retained catalog rows were classified here; `48` strict equivalent pairs recovered; `48` pairs selected for the annual scanner; `15` pairs produced synchronized historical price snapshots; `8025` synchronized snapshots aligned; `8` matched pairs produced a positive proxy window.

**Best retained example:** `Will Zohran Mamdani say "Grocery" during his victory/concession speech?` with `$0.461801` locked net profit per paired contract.

**Why this category may be useful:** the retained positive result shows that at least one equivalent-looking cross-venue pair survived the modeled costs. The strength of the conclusion depends on the evidence label below: archived PMXT L2 rows include visible book capacity, while annual proxy rows are broader screens that still need depth validation.

**Observed positive subcategory counts:**

| Positive subcategory label | Retained evidence rows |
|---|---:|
| `annual proxy phase: lifecycle_final_24h` | 664 |
| `annual proxy phase: sports_pregame_slow` | 247 |
| `annual proxy phase: lifecycle_30d_to_24h` | 11 |
| `annual proxy phase: sports_event_start_unavailable_final_24h` | 4 |

**Timing-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `lifecycle_30d_to_24h` | 3 | 36 | 11 | 5 | $0.066120 |
| `lifecycle_final_24h` | 45 | 5316 | 664 | 152 | $0.461801 |
| `sports_event_start_unavailable_final_24h` | 3 | 1584 | 4 | 3 | $0.018191 |
| `sports_pregame_slow` | 3 | 1089 | 247 | 87 | $0.424100 |

**Market-type comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `future_or_winner` | 12 | 6477 | 308 | 123 | $0.424100 |
| `moneyline_or_binary` | 36 | 1548 | 618 | 124 | $0.461801 |

**Competition-phase comparison:**

| Subcategory | Strict pairs | Synchronized snapshots | Positive proxy snapshots | Positive windows | Best net edge |
|---|---:|---:|---:|---:|---:|
| `regular_season_or_unspecified` | 48 | 8025 | 926 | 247 | $0.461801 |

**Profitable examples:**

- `2025-11-05T04:30:00+00:00`: buy YES on `polymarket` at `$0.505000` and NO on `kalshi` at `$0.010000` for `100` paired contracts. Pair cost per contract `$0.515000`; total entry fees for the order `$1.319875`; locked net profit `$0.461801` per paired contract; ROI `85.80%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2025-12-02T23:00:00+00:00`: buy YES on `kalshi` at `$0.050000` and NO on `polymarket` at `$0.500000` for `100` paired contracts. Pair cost per contract `$0.550000`; total entry fees for the order `$1.590000`; locked net profit `$0.424100` per paired contract; ROI `73.64%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.
- `2025-12-02T23:00:00+00:00`: buy YES on `kalshi` at `$0.050000` and NO on `polymarket` at `$0.500000` for `100` paired contracts. Pair cost per contract `$0.550000`; total entry fees for the order `$1.590000`; locked net profit `$0.424100` per paired contract; ROI `73.64%`. Evidence: `official_api_price_history_proxy_without_historical_depth`.

## Important Limits

- A price-history proxy is a screening result, not proof that both trades were fillable at the same instant.
- Archived L2 replay enforces visible quantity, but it still cannot guarantee live queue position or network latency.
- Automatically matched contracts still require a manual settlement-rule review before live trading.
- Polymarket US public catalog data is analyzed separately and must not be treated as historical profit evidence.