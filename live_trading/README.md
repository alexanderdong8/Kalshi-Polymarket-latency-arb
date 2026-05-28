# Live Matched-Market Scanner

Read-only live infrastructure for comparing active Kalshi and Polymarket US markets, maintaining hot order books, and surfacing executable cross-market arbitrage candidates.

This package does not place, cancel, or modify orders. It discovers markets, streams books, computes opportunities, renders a terminal dashboard, and records observations to SQLite for later replay.

## Setup

```powershell
cd live_trading
python -m pip install -e .[test]
```

Create a `.env` file in the repo root or in `live_trading/`:

```text
KALSHI_API_KEY_ID=
KALSHI_PRIVATE_KEY_PATH=
POLYMARKET_US_KEY_ID=
POLYMARKET_US_SECRET_KEY=
```

Kalshi market discovery can work without credentials, but Kalshi order book WebSockets and Polymarket US authenticated market WebSockets need API credentials.

## Run

```powershell
python -m live_trading run --categories sports,politics --max-matches 100
```

Useful read-only commands:

```powershell
python -m live_trading discover --categories sports --max-matches 25
python -m live_trading sample-tui
```

## Design Notes

- REST is used for discovery, initial book hydration, and recovery.
- WebSocket streams keep live prices updated without repeatedly polling venue APIs.
- Matching intentionally favors precision over recall. Candidates with rule or date warnings are shown, but marked as review-only.
- Fees and arbitrage math use `Decimal`.

