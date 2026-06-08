# Arbitrage Trade Examples

Coverage manifest: [reports/coverage_manifest.md](reports/coverage_manifest.md)

This report is the reader-facing example book. It intentionally shows profitable retained examples only. A category with no positive retained result says `No profitable example found.` instead of showing a near miss.

## The Trade In Plain English

A prediction-market contract pays `$1.00` if its stated outcome happens and `$0.00` otherwise. A locked pair buys `YES` on one venue and `NO` on the other venue for the same real-world question. If the wording and settlement rules truly match, exactly one side pays `$1.00`. Buying both sides for less than `$1.00`, after costs, creates a locked profit.

Example: buying `YES` for `$0.42` and `NO` for `$0.51` costs `$0.93`. Before fees, the locked profit is `$1.00 - $0.93 = $0.07` per paired contract.

## Terms Used Below

- **Venue**: the exchange where a contract is traded, such as Kalshi or international Polymarket.
- **Pair cost**: the combined amount paid for the `YES` and `NO` legs.
- **Fee**: an exchange charge paid when entering or exiting a trade.
- **Slippage**: the extra cost caused by the best displayed price not having enough contracts for the full order.
- **Order book**: the visible list of prices and quantities offered by other traders.
- **L2 order book**: a multi-level order book. It includes the best price and deeper prices behind it.
- **VWAP**: volume-weighted average price. If 50 contracts cost `$0.40` and the next 50 cost `$0.42`, the VWAP for 100 contracts is `$0.41`.
- **Displayed depth**: how many contracts were visibly available at the best price on the thinner side of the pair.
- **Paired capacity**: the largest number of contracts both visible books could support at that moment.
- **Partial-fill exposure**: the number of contracts that could be left unhedged if one side fills and the other does not.
- **Locked profit**: profit retained by holding both opposite legs until settlement.
- **ROI**: return on investment. It is locked profit divided by the cash paid to enter the pair.
- **Proxy**: an estimate based on historical prices. A proxy does not prove that enough contracts were actually available.
- **Capital recycling**: selling both legs early when doing so safely earns more than waiting for settlement.
- **Pregame**: the period before a scheduled sporting event starts.
- **In-play**: the period after a scheduled sporting event starts but before its final result. The annual scanner does not enter new trades after final resolution.
- **Sports event start unavailable**: the retained public metadata did not expose the scheduled start. The scanner can still inspect the final 24 hours before close, but it does not call those observations in-play.
- **Modeled order size**: a hypothetical simultaneous two-leg order used for arithmetic. In the annual proxy layer, it is not a claim that the historical books visibly contained that quantity.

## Evidence Labels

- **PMXT archived L2**: stronger historical evidence. The replay walked the stored multi-level books and enforced visible capacity.
- **Official API price-history proxy**: broader annual screening. Historical Polymarket depth was unavailable, so slippage is modeled.

## How Examples Are Selected

The scanner evaluates many aligned historical timestamps for each matched pair. It groups consecutive profitable timestamps into an opportunity window, then presents up to three distinct profitable markets per category. The `best timestamp` is the most profitable snapshot inside the displayed window; it is not the only timestamp checked.

For an annual proxy example, `100 paired contracts` means the model asks what would happen if `100` YES contracts and `100` matching NO contracts were purchased together at that snapshot. The official annual APIs do not preserve historical Polymarket order-book quantities, so the model applies the stated conservative slippage allowance. For a PMXT archived-L2 example, the stored multi-level book is walked to calculate the average price and visible capacity.

Only positive-profit rows are shown. Rows are strict research candidates selected for inspectability. Each row still requires manual resolution-rule review before live trading.

## Nba

No profitable example found.

## Mlb

No profitable example found.

## Golf

### Will Justin Rose win the 2025 FedEx St. Jude Championship?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_event_start_unavailable_final_24h`.
- Profitable window: `2025-08-10T22:55:00+00:00` through `2025-08-10T22:55:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-08-10T22:55:00+00:00`.
- Polymarket contract: `Will Justin Rose win the 2025 FedEx St. Jude Championship?`
- Kalshi contract: `Will Justin Rose win the FedEx St. Jude Championship?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.314000` and NO on `kalshi` at `$0.010000`.
- Pair cost per paired contract: `$0.324000`; total entry fees for the modeled order: `$1.147020`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.654530`.
- Locked net profit for the modeled order: `$65.452980`.
- ROI on entry capital: `189.46%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_event_start_unavailable_final_24h` | `2025-08-09T23:13:58.006165+00:00` through `2025-08-10T23:13:58.006165+00:00` | every 5 minutes | 248 |
| `sports_pregame_slow` | `2025-08-04T19:19:32.571062+00:00` through `2025-08-09T23:13:58.006165+00:00` | hourly | 114 |

### Will J.J. Spaun win the 2025 FedEx St. Jude Championship?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_event_start_unavailable_final_24h`.
- Profitable window: `2025-08-10T22:55:00+00:00` through `2025-08-10T22:55:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-08-10T22:55:00+00:00`.
- Polymarket contract: `Will J.J. Spaun win the 2025 FedEx St. Jude Championship?`
- Kalshi contract: `Will J.J. Spaun win the FedEx St. Jude Championship?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.358500`.
- Pair cost per paired contract: `$0.368500`; total entry fees for the modeled order: `$1.219889`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.609301`.
- Locked net profit for the modeled order: `$60.930111`.
- ROI on entry capital: `155.95%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_event_start_unavailable_final_24h` | `2025-08-09T23:13:58.006165+00:00` through `2025-08-10T23:13:58.006165+00:00` | every 5 minutes | 216 |
| `sports_pregame_slow` | `2025-08-04T19:19:09.387408+00:00` through `2025-08-09T23:13:58.006165+00:00` | hourly | 111 |

### Will Jackson Koivun win the 2025 Wyndham Championship?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_event_start_unavailable_final_24h`.
- Profitable window: `2025-08-03T02:55:00+00:00` through `2025-08-03T02:55:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-08-03T02:55:00+00:00`.
- Polymarket contract: `Will Jackson Koivun win the 2025 Wyndham Championship?`
- Kalshi contract: `Will Jackson Koivun win the Wyndham Championship?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.498500`.
- Pair cost per paired contract: `$0.508500`; total entry fees for the modeled order: `$1.319989`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.468300`.
- Locked net profit for the modeled order: `$46.830011`.
- ROI on entry capital: `88.08%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_event_start_unavailable_final_24h` | `2025-08-02T21:59:52.806605+00:00` through `2025-08-03T21:59:52.806605+00:00` | every 5 minutes | 60 |
| `sports_pregame_slow` | `2025-07-28T19:35:50.469103+00:00` through `2025-08-02T21:59:52.806605+00:00` | hourly | 102 |


## Atp

No profitable example found.

## Wta

No profitable example found.

## Esports

No profitable example found.

## Ipl

No profitable example found.

## Wnba

No profitable example found.

## Nhl

No profitable example found.

## Itf Men

No profitable example found.

## Itf Women

No profitable example found.

## Ufc

No profitable example found.

## Fifa World Cup

No profitable example found.

## Politics

### Will Keir Starmer say "Tax" at the next Prime Minister's Questions?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-01-14T12:05:00+00:00` through `2026-01-14T12:05:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-01-14T12:05:00+00:00`.
- Polymarket contract: `Will Keir Starmer say "Tax" at the next Prime Minister's Questions?`
- Kalshi contract: `Will Keir Starmer say Tax at Prime Minister's Questions on January 14th?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.400000` and NO on `kalshi` at `$0.010000`.
- Pair cost per paired contract: `$0.410000`; total entry fees for the modeled order: `$1.270000`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.567300`.
- Locked net profit for the modeled order: `$56.730000`.
- ROI on entry capital: `131.11%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_30d_to_24h` | `2026-01-12T18:57:50.882757+00:00` through `2026-01-13T20:17:07.232708+00:00` | hourly | 20 |
| `lifecycle_final_24h` | `2026-01-13T20:17:07.232708+00:00` through `2026-01-14T20:17:07.232708+00:00` | every 5 minutes | 149 |

### Will Keir Starmer say "Immigrant" or "Immigration" at the next Prime Minister's Questions?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-01-14T12:05:00+00:00` through `2026-01-14T12:05:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-01-14T12:05:00+00:00`.
- Polymarket contract: `Will Keir Starmer say "Immigrant" or "Immigration" at the next Prime Minister's Questions?`
- Kalshi contract: `Will Keir Starmer say Immigrant / Immigration at Prime Minister's Questions on January 14th?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.470000` and NO on `kalshi` at `$0.010000`.
- Pair cost per paired contract: `$0.480000`; total entry fees for the modeled order: `$1.315500`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.496845`.
- Locked net profit for the modeled order: `$49.684500`.
- ROI on entry capital: `98.75%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_30d_to_24h` | `2026-01-12T18:57:48.222717+00:00` through `2026-01-13T20:16:01.873315+00:00` | hourly | 21 |
| `lifecycle_final_24h` | `2026-01-13T20:16:01.873315+00:00` through `2026-01-14T20:16:01.873315+00:00` | every 5 minutes | 156 |

### Will Keir Starmer say "Ukraine" at the next Prime Minister's Questions?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-01-14T12:30:00+00:00` through `2026-01-14T12:30:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-01-14T12:30:00+00:00`.
- Polymarket contract: `Will Keir Starmer say "Ukraine" at the next Prime Minister's Questions?`
- Kalshi contract: `Will Keir Starmer say Ukraine at Prime Minister's Questions on January 14th?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.470000` and NO on `kalshi` at `$0.010000`.
- Pair cost per paired contract: `$0.480000`; total entry fees for the modeled order: `$1.315500`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.496845`.
- Locked net profit for the modeled order: `$49.684500`.
- ROI on entry capital: `98.75%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_30d_to_24h` | `2026-01-12T18:57:52.548510+00:00` through `2026-01-13T20:15:19.738563+00:00` | hourly | 23 |
| `lifecycle_final_24h` | `2026-01-13T20:15:19.738563+00:00` through `2026-01-14T20:15:19.738563+00:00` | every 5 minutes | 121 |


## Weather

No profitable example found.

## Mls

No profitable example found.

## Elections

### Argentina Presidential Election Winner - Will Javier Milei win the 2027 Argentina presidential election?

- Evidence: `pmxt_archived_l2_strict_candidate_pending_manual_rule_review`
- Timing phase: `lifecycle_more_than_30d`.
- Profitable window: `2026-05-23T07:15:48.744000+00:00` through `2026-05-23T07:15:49.602000+00:00`; duration `0.858` seconds; profitable snapshots `6`.
- Best timestamp inside that window: `2026-05-23T07:15:48.744000+00:00`.
- Polymarket contract: `Argentina Presidential Election Winner - Will Javier Milei win the 2027 Argentina presidential election?`
- Kalshi contract: `Who will win the next Argentine presidential election?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.445474` and NO on `kalshi` at `$0.390000`.
- Pair cost per paired contract: `$0.835474`; total entry fees for the modeled order: `$2.905135`; slippage detail per contract: `$0.005474`.
- Displayed depth: `45.26` contracts.
- Paired ladder capacity: `6325.0` contracts; one-leg exposure if pairing fails: `100` contracts.
- Locked net profit per contract: `$0.135475`.
- Locked net profit for the modeled order: `$13.547465`.
- ROI on entry capital: `15.67%`.
- Qualifying paired exit: `False`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

### Will Donna Miller be the Democratic Nominee for IL-02?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-03-18T00:00:00+00:00` through `2026-03-18T01:00:00+00:00`; duration `3600.0` seconds; profitable snapshots `13`.
- Best timestamp inside that window: `2026-03-18T00:25:00+00:00`.
- Polymarket contract: `Will Donna Miller be the Democratic Nominee for IL-02?`
- Kalshi contract: `Will Donna Miller be the Democratic nominee for IL-02?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.175000` and NO on `kalshi` at `$0.260000`.
- Pair cost per paired contract: `$0.435000`; total entry fees for the modeled order: `$2.071875`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.534281`.
- Locked net profit for the modeled order: `$53.428125`.
- ROI on entry capital: `114.72%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_final_24h` | `2026-03-17T13:38:54+00:00` through `2026-03-18T13:38:54+00:00` | every 5 minutes | 111 |

### Will Jesse Jackson Jr. be the Democratic Nominee for IL-02?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-03-18T00:25:00+00:00` through `2026-03-18T01:15:00+00:00`; duration `3000.0` seconds; profitable snapshots `11`.
- Best timestamp inside that window: `2026-03-18T00:25:00+00:00`.
- Polymarket contract: `Will Jesse Jackson Jr. be the Democratic Nominee for IL-02?`
- Kalshi contract: `Will Jesse Jackson Jr. be the Democratic nominee for IL-02?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.250000` and NO on `polymarket` at `$0.290000`.
- Pair cost per paired contract: `$0.540000`; total entry fees for the modeled order: `$2.349500`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.426505`.
- Locked net profit for the modeled order: `$42.650500`.
- ROI on entry capital: `74.37%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_final_24h` | `2026-03-17T13:38:54+00:00` through `2026-03-18T13:38:54+00:00` | every 5 minutes | 154 |


## Culture

### Will Bulgaria win the televote for Eurovision 2026?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-05-16T22:45:00+00:00` through `2026-05-16T22:55:00+00:00`; duration `600.0` seconds; profitable snapshots `3`.
- Best timestamp inside that window: `2026-05-16T22:55:00+00:00`.
- Polymarket contract: `Will Bulgaria win the televote for Eurovision 2026?`
- Kalshi contract: `Who will win the Televote in Eurovision 2026?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.304500` and NO on `kalshi` at `$0.010000`.
- Pair cost per paired contract: `$0.314500`; total entry fees for the modeled order: `$1.128899`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.664211`.
- Locked net profit for the modeled order: `$66.421101`.
- ROI on entry capital: `197.81%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_final_24h` | `2026-05-16T00:23:19+00:00` through `2026-05-17T00:23:19+00:00` | every 5 minutes | 170 |

### Will Kai Cenat win Streamer of the Year at the 2025 Streamer Awards?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2025-12-07T05:30:00+00:00` through `2025-12-07T05:40:00+00:00`; duration `600.0` seconds; profitable snapshots `3`.
- Best timestamp inside that window: `2025-12-07T05:40:00+00:00`.
- Polymarket contract: `Will Kai Cenat win Streamer of the Year at the 2025 Streamer Awards?`
- Kalshi contract: `Will Kai Cenat win Streamer of the Year at Streamer Awards 2025?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.450000`.
- Pair cost per paired contract: `$0.460000`; total entry fees for the modeled order: `$1.307500`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.516925`.
- Locked net profit for the modeled order: `$51.692500`.
- ROI on entry capital: `107.01%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_final_24h` | `2025-12-06T06:01:32.317470+00:00` through `2025-12-07T06:01:32.317470+00:00` | every 5 minutes | 273 |

### Will iShowSpeed win Streamer of the Year at the 2025 Streamer Awards?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2025-12-07T05:35:00+00:00` through `2025-12-07T05:40:00+00:00`; duration `300.0` seconds; profitable snapshots `2`.
- Best timestamp inside that window: `2025-12-07T05:40:00+00:00`.
- Polymarket contract: `Will iShowSpeed win Streamer of the Year at the 2025 Streamer Awards?`
- Kalshi contract: `Will IShowSpeed win Streamer of the Year at Streamer Awards 2025?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.495000` and NO on `kalshi` at `$0.010000`.
- Pair cost per paired contract: `$0.505000`; total entry fees for the modeled order: `$1.319875`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.471801`.
- Locked net profit for the modeled order: `$47.180125`.
- ROI on entry capital: `89.32%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_final_24h` | `2025-12-06T06:01:32.317470+00:00` through `2025-12-07T06:01:32.317470+00:00` | every 5 minutes | 262 |


## F1

No profitable example found.

## Additional Discovered Scenario Coverage

### Will Zohran Mamdani say "Grocery" during his victory/concession speech?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2025-11-05T04:30:00+00:00` through `2025-11-05T04:30:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-11-05T04:30:00+00:00`.
- Polymarket contract: `Will Zohran Mamdani say "Grocery" during his victory/concession speech?`
- Kalshi contract: `What will Zohran Mamdani say during victory / concession speech?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.505000` and NO on `kalshi` at `$0.010000`.
- Pair cost per paired contract: `$0.515000`; total entry fees for the modeled order: `$1.319875`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.461801`.
- Locked net profit for the modeled order: `$46.180125`.
- ROI on entry capital: `85.80%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_30d_to_24h` | `2025-11-04T02:22:28.027945+00:00` through `2025-11-04T14:45:43.507067+00:00` | hourly | 12 |
| `lifecycle_final_24h` | `2025-11-04T14:45:43.507067+00:00` through `2025-11-05T14:45:43.507067+00:00` | every 5 minutes | 183 |

### Will Fabiano Caruana win the 2025 Freestyle Chess Grand Slam Tour?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_pregame_slow`.
- Profitable window: `2025-12-02T23:00:00+00:00` through `2025-12-02T23:00:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-12-02T23:00:00+00:00`.
- Polymarket contract: `Will Fabiano Caruana win the 2025 Freestyle Chess Grand Slam Tour?`
- Kalshi contract: `Will Fabiano Caruana finish 1st in Freestyle Chess Grand Slam Tour 2025?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.050000` and NO on `polymarket` at `$0.500000`.
- Pair cost per paired contract: `$0.550000`; total entry fees for the modeled order: `$1.590000`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.424100`.
- Locked net profit for the modeled order: `$42.410000`.
- ROI on entry capital: `73.64%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_event_start_unavailable_final_24h` | `2025-12-08T18:16:38.024074+00:00` through `2025-12-09T18:16:38.024074+00:00` | every 5 minutes | 210 |
| `sports_pregame_slow` | `2025-12-02T22:28:06.744393+00:00` through `2025-12-08T18:16:38.024074+00:00` | hourly | 129 |

### Will Vincent Keymer win the 2025 Freestyle Chess Grand Slam Tour?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_pregame_slow`.
- Profitable window: `2025-12-02T23:00:00+00:00` through `2025-12-02T23:00:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-12-02T23:00:00+00:00`.
- Polymarket contract: `Will Vincent Keymer win the 2025 Freestyle Chess Grand Slam Tour?`
- Kalshi contract: `Will Vincent Keymer finish 1st in Freestyle Chess Grand Slam Tour 2025?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.050000` and NO on `polymarket` at `$0.500000`.
- Pair cost per paired contract: `$0.550000`; total entry fees for the modeled order: `$1.590000`; slippage detail per contract: `$0.010000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.424100`.
- Locked net profit for the modeled order: `$42.410000`.
- ROI on entry capital: `73.64%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `required_before_trade_presentation`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_event_start_unavailable_final_24h` | `2025-12-08T18:16:38.024074+00:00` through `2025-12-09T18:16:38.024074+00:00` | every 5 minutes | 111 |
| `sports_pregame_slow` | `2025-12-02T22:28:08.844918+00:00` through `2025-12-08T18:16:38.024074+00:00` | hourly | 125 |
