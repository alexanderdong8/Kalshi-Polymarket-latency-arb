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

### Suns vs. Celtics

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_in_play`.
- Profitable window: `2026-03-17T02:01:00+00:00` through `2026-03-17T02:01:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-03-17T02:01:00+00:00`.
- Polymarket contract: `Suns vs. Celtics`
- Kalshi contract: `Phoenix at Boston Winner?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.970000` and NO on `polymarket` at `$0.005000`.
- Pair cost per paired contract: `$0.975000`; total entry fees for the modeled order: `$0.234875`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.002651`.
- Locked net profit for the modeled order: `$0.265125`.
- ROI on entry capital: `0.27%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2026-03-16T23:30:00+00:00` through `2026-03-17T02:18:13+00:00` | every 1 minute | 163 |
| `sports_pregame_final_24h` | `2026-03-15T23:30:00+00:00` through `2026-03-16T23:30:00+00:00` | every 5 minutes | 282 |
| `sports_pregame_slow` | `2026-03-10T14:03:03.089610+00:00` through `2026-03-15T23:30:00+00:00` | hourly | 24 |

### Suns vs. Celtics

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_in_play`.
- Profitable window: `2026-03-17T02:01:00+00:00` through `2026-03-17T02:01:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-03-17T02:01:00+00:00`.
- Polymarket contract: `Suns vs. Celtics`
- Kalshi contract: `Phoenix at Boston Winner?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.005000` and NO on `kalshi` at `$0.970000`.
- Pair cost per paired contract: `$0.975000`; total entry fees for the modeled order: `$0.234875`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.002651`.
- Locked net profit for the modeled order: `$0.265125`.
- ROI on entry capital: `0.27%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2026-03-16T23:30:00+00:00` through `2026-03-17T02:18:13+00:00` | every 1 minute | 160 |
| `sports_pregame_final_24h` | `2026-03-15T23:30:00+00:00` through `2026-03-16T23:30:00+00:00` | every 5 minutes | 282 |
| `sports_pregame_slow` | `2026-03-10T14:03:03.089610+00:00` through `2026-03-15T23:30:00+00:00` | hourly | 25 |


## Mlb

### Athletics vs. Baltimore Orioles

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_in_play`.
- Profitable window: `2026-05-09T01:53:00+00:00` through `2026-05-09T02:11:00+00:00`; duration `1080.0` seconds; profitable snapshots `19`.
- Best timestamp inside that window: `2026-05-09T01:53:00+00:00`.
- Polymarket contract: `Athletics vs. Baltimore Orioles`
- Kalshi contract: `A's vs Baltimore Winner?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.000500` and NO on `kalshi` at `$0.460000`.
- Pair cost per paired contract: `$0.460500`; total entry fees for the modeled order: `$1.742499`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.502075`.
- Locked net profit for the modeled order: `$50.207501`.
- ROI on entry capital: `100.83%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2026-05-08T23:05:00+00:00` through `2026-05-09T23:04:37+00:00` | every 1 minute | 53 |
| `sports_pregame_final_24h` | `2026-05-07T23:05:00+00:00` through `2026-05-08T23:05:00+00:00` | every 5 minutes | 99 |
| `sports_pregame_slow` | `2026-05-02T13:04:10.173570+00:00` through `2026-05-07T23:05:00+00:00` | hourly | 25 |

### Athletics vs. Baltimore Orioles

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_in_play`.
- Profitable window: `2026-05-09T01:53:00+00:00` through `2026-05-09T01:53:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-05-09T01:53:00+00:00`.
- Polymarket contract: `Athletics vs. Baltimore Orioles`
- Kalshi contract: `A's vs Baltimore Winner?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.460000` and NO on `polymarket` at `$0.000500`.
- Pair cost per paired contract: `$0.460500`; total entry fees for the modeled order: `$1.742499`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.502075`.
- Locked net profit for the modeled order: `$50.207501`.
- ROI on entry capital: `100.83%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2026-05-08T23:05:00+00:00` through `2026-05-09T23:04:37+00:00` | every 1 minute | 52 |
| `sports_pregame_final_24h` | `2026-05-07T23:05:00+00:00` through `2026-05-08T23:05:00+00:00` | every 5 minutes | 125 |
| `sports_pregame_slow` | `2026-05-02T13:04:10.173570+00:00` through `2026-05-07T23:05:00+00:00` | hourly | 26 |

### Pittsburgh Pirates vs. San Francisco Giants

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_in_play`.
- Profitable window: `2026-05-10T03:29:00+00:00` through `2026-05-10T03:31:00+00:00`; duration `120.0` seconds; profitable snapshots `3`.
- Best timestamp inside that window: `2026-05-10T03:31:00+00:00`.
- Polymarket contract: `Pittsburgh Pirates vs. San Francisco Giants`
- Kalshi contract: `Pittsburgh vs San Francisco Winner?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.490000` and NO on `polymarket` at `$0.000500`.
- Pair cost per paired contract: `$0.490500`; total entry fees for the modeled order: `$1.752499`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.471975`.
- Locked net profit for the modeled order: `$47.197501`.
- ROI on entry capital: `89.38%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2026-05-10T01:05:00+00:00` through `2026-05-11T00:04:27+00:00` | every 1 minute | 146 |
| `sports_pregame_final_24h` | `2026-05-09T01:05:00+00:00` through `2026-05-10T01:05:00+00:00` | every 5 minutes | 147 |
| `sports_pregame_slow` | `2026-05-04T13:03:13.727150+00:00` through `2026-05-09T01:05:00+00:00` | hourly | 29 |


## Golf

### Will Michael Kim win the 2026 PGA Championship?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_pregame_slow`.
- Profitable window: `2026-05-11T17:00:00+00:00` through `2026-05-11T17:00:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-05-11T17:00:00+00:00`.
- Polymarket contract: `Will Michael Kim win the 2026 PGA Championship?`
- Kalshi contract: `Will Michael Kim win the PGA Championship?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.002000` and NO on `polymarket` at `$0.500000`.
- Pair cost per paired contract: `$0.502000`; total entry fees for the modeled order: `$1.270000`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.465300`.
- Locked net profit for the modeled order: `$46.530000`.
- ROI on entry capital: `87.02%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_pregame_final_24h` | `2026-05-13T00:00:00+00:00` through `2026-05-14T00:00:00+00:00` | every 5 minutes | 0 |
| `sports_pregame_slow` | `2026-05-11T16:30:03.380000+00:00` through `2026-05-13T00:00:00+00:00` | hourly | 2 |

### Will Michael Brennan win the 2026 PGA Championship?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_pregame_slow`.
- Profitable window: `2026-05-11T17:00:00+00:00` through `2026-05-11T17:00:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-05-11T17:00:00+00:00`.
- Polymarket contract: `Will Michael Brennan win the 2026 PGA Championship?`
- Kalshi contract: `Will Michael Brennan win the PGA Championship?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.003000` and NO on `polymarket` at `$0.500000`.
- Pair cost per paired contract: `$0.503000`; total entry fees for the modeled order: `$1.280000`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.464200`.
- Locked net profit for the modeled order: `$46.420000`.
- ROI on entry capital: `86.64%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_pregame_final_24h` | `2026-05-13T00:00:00+00:00` through `2026-05-14T00:00:00+00:00` | every 5 minutes | 1 |
| `sports_pregame_slow` | `2026-05-11T16:25:09.680000+00:00` through `2026-05-13T00:00:00+00:00` | hourly | 2 |

### Will Matti Schmid win the 2026 PGA Championship?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_pregame_slow`.
- Profitable window: `2026-05-12T02:00:00+00:00` through `2026-05-12T02:00:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-05-12T02:00:00+00:00`.
- Polymarket contract: `Will Matti Schmid win the 2026 PGA Championship?`
- Kalshi contract: `Will Matti Schmid win the PGA Championship?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.002000` and NO on `polymarket` at `$0.505000`.
- Pair cost per paired contract: `$0.507000`; total entry fees for the modeled order: `$1.269875`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.460301`.
- Locked net profit for the modeled order: `$46.030125`.
- ROI on entry capital: `85.29%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_event_start_unavailable_final_24h` | `2026-05-16T23:08:33+00:00` through `2026-05-17T23:08:33+00:00` | every 5 minutes | 277 |
| `sports_pregame_slow` | `2026-05-12T01:04:31.336330+00:00` through `2026-05-16T23:08:33+00:00` | hourly | 91 |


## Atp

No profitable example found.

## Wta

No profitable example found.

## Esports

### Will Alireza Firouzja win the 2025 Chess Esports World Cup?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_pregame_slow`.
- Profitable window: `2025-07-29T18:00:00+00:00` through `2025-07-29T18:00:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-07-29T18:00:00+00:00`.
- Polymarket contract: `Will Alireza Firouzja win the 2025 Chess Esports World Cup?`
- Kalshi contract: `Will Alireza Firouzja win the Chess – Esports World Cup?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.110000` and NO on `polymarket` at `$0.850000`.
- Pair cost per paired contract: `$0.960000`; total entry fees for the modeled order: `$1.327500`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.006725`.
- Locked net profit for the modeled order: `$0.672500`.
- ROI on entry capital: `0.68%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_event_start_unavailable_final_24h` | `2025-07-31T20:41:24.293856+00:00` through `2025-08-01T20:41:24.293856+00:00` | every 5 minutes | 201 |
| `sports_pregame_slow` | `2025-07-21T19:08:49.043750+00:00` through `2025-07-31T20:41:24.293856+00:00` | hourly | 171 |


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

No profitable example found.

## Weather

No profitable example found.

## Mls

No profitable example found.

## Elections

### Argentina Presidential Election Winner - Will Javier Milei win the 2027 Argentina presidential election?

- Evidence: `pmxt_archived_l2_exact_pair`
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
- Review status: `exact-pair gate passed; re-check venue rules before live trading`.

### Will Derek Merrin be the Republican nominee for OH-09?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-05-05T22:35:00+00:00` through `2026-05-05T23:05:00+00:00`; duration `1800.0` seconds; profitable snapshots `7`.
- Best timestamp inside that window: `2026-05-05T22:35:00+00:00`.
- Polymarket contract: `Will Derek Merrin be the Republican nominee for OH-09?`
- Kalshi contract: `Will Derek Merrin be the Republican nominee for OH-09?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.890000` and NO on `polymarket` at `$0.035000`.
- Pair cost per paired contract: `$0.925000`; total entry fees for the modeled order: `$0.858875`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.046411`.
- Locked net profit for the modeled order: `$4.641125`.
- ROI on entry capital: `4.87%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_final_24h` | `2026-05-05T15:10:18+00:00` through `2026-05-06T15:10:18+00:00` | every 5 minutes | 118 |

### Will Madison Sheahan be the Republican nominee for OH-09?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `lifecycle_final_24h`.
- Profitable window: `2026-05-05T16:10:00+00:00` through `2026-05-05T16:10:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-05-05T16:10:00+00:00`.
- Polymarket contract: `Will Madison Sheahan be the Republican nominee for OH-09?`
- Kalshi contract: `Will Madison Sheahan be the Republican nominee for OH-09?`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `polymarket` at `$0.019500` and NO on `kalshi` at `$0.950000`.
- Pair cost per paired contract: `$0.969500`; total entry fees for the modeled order: `$0.435599`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.006144`.
- Locked net profit for the modeled order: `$0.614401`.
- ROI on entry capital: `0.62%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `lifecycle_final_24h` | `2026-05-05T15:10:18+00:00` through `2026-05-06T15:10:18+00:00` | every 5 minutes | 62 |


## Culture

No profitable example found.

## F1

### Will Lewis Hamilton achieve the fastest lap at the 2025 F1 Qatar Grand Prix?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_in_play`.
- Profitable window: `2025-11-30T20:26:00+00:00` through `2025-11-30T20:26:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-11-30T20:26:00+00:00`.
- Polymarket contract: `Will Lewis Hamilton achieve the fastest lap at the 2025 F1 Qatar Grand Prix?`
- Kalshi contract: `Qatar Grand Prix: Fastest Lap`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.500500`.
- Pair cost per paired contract: `$0.510500`; total entry fees for the modeled order: `$1.319999`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.456300`.
- Locked net profit for the modeled order: `$45.630001`.
- ROI on entry capital: `83.92%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2025-11-30T16:00:00+00:00` through `2025-11-30T20:34:56.909478+00:00` | every 1 minute | 6 |
| `sports_pregame_final_24h` | `2025-11-29T16:00:00+00:00` through `2025-11-30T16:00:00+00:00` | every 5 minutes | 43 |
| `sports_pregame_slow` | `2025-11-24T13:33:54.687700+00:00` through `2025-11-29T16:00:00+00:00` | hourly | 57 |

### Will Carlos Sainz Jr. get pole position at the 2025 F1 Qatar Grand Prix?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_in_play`.
- Profitable window: `2025-11-29T20:20:00+00:00` through `2025-11-29T20:20:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2025-11-29T20:20:00+00:00`.
- Polymarket contract: `Will Carlos Sainz Jr. get pole position at the 2025 F1 Qatar Grand Prix?`
- Kalshi contract: `Qatar Grand Prix: Qualify in Pole Position`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.010000` and NO on `polymarket` at `$0.505500`.
- Pair cost per paired contract: `$0.515500`; total entry fees for the modeled order: `$1.319849`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.451302`.
- Locked net profit for the modeled order: `$45.130151`.
- ROI on entry capital: `82.25%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2025-11-29T18:00:00+00:00` through `2025-11-29T23:52:13.461447+00:00` | every 1 minute | 12 |
| `sports_pregame_final_24h` | `2025-11-28T18:00:00+00:00` through `2025-11-29T18:00:00+00:00` | every 5 minutes | 31 |
| `sports_pregame_slow` | `2025-11-24T13:33:38.555600+00:00` through `2025-11-28T18:00:00+00:00` | hourly | 28 |

### Will Oliver Bearman finish on the podium at the 2026 F1 Chinese Grand Prix?

- Evidence: `official_api_price_history_proxy_without_historical_depth`
- Timing phase: `sports_pregame_slow`.
- Profitable window: `2026-03-11T13:00:00+00:00` through `2026-03-11T13:00:00+00:00`; duration `0.0` seconds; profitable snapshots `1`.
- Best timestamp inside that window: `2026-03-11T13:00:00+00:00`.
- Polymarket contract: `Will Oliver Bearman finish on the podium at the 2026 F1 Chinese Grand Prix?`
- Kalshi contract: `Chinese Grand Prix: Podium Finishers`
- Order size used for the arithmetic: `100` paired contracts. This represents one simultaneous two-leg entry at the best timestamp shown above.
- Buy YES on `kalshi` at `$0.040000` and NO on `polymarket` at `$0.495000`.
- Pair cost per paired contract: `$0.535000`; total entry fees for the modeled order: `$1.519875`; slippage detail per contract: `$0.020000`.
- Displayed depth: `proxy only; unavailable` contracts.
- Paired ladder capacity: `proxy only; unavailable` contracts; one-leg exposure if pairing fails: `proxy only; unavailable` contracts.
- Locked net profit per contract: `$0.429801`.
- Locked net profit for the modeled order: `$42.980125`.
- ROI on entry capital: `75.38%`.
- Qualifying paired exit: `None`; exit time: `None`; improvement: `n/a`.
- Review status: `exact-pair gate passed; annual depth remains modeled`.

Historical periods inspected for this matched pair:

| Timing phase | Range inspected | Sampling interval | Synchronized price snapshots |
|---|---|---|---:|
| `sports_in_play` | `2026-03-15T07:00:00+00:00` through `2026-03-15T15:23:23+00:00` | every 1 minute | 26 |
| `sports_pregame_final_24h` | `2026-03-14T07:00:00+00:00` through `2026-03-15T07:00:00+00:00` | every 5 minutes | 117 |
| `sports_pregame_slow` | `2026-03-11T11:34:13.021230+00:00` through `2026-03-14T07:00:00+00:00` | hourly | 47 |


## Additional Discovered Scenario Coverage

No profitable example found.