# Prediction-Market Arbitrage System

Local application for discovering, reviewing, paper trading, live trading, and
backtesting complete prediction-market events across Kalshi and Polymarket.

## Start

```powershell
.\start.ps1
```

The application opens at:

```text
http://127.0.0.1:3000
```

Stop it cleanly with:

```powershell
.\stop.ps1
```

Node.js 22 LTS and Python 3.10 or newer are recommended.

## Documentation

- [System architecture](docs/architecture.md): the current implemented
  frontend, backend, scanner, runtime, strategy integration, persistence,
  backtesting, operations, and safety model.
- [Strategy reference](docs/strategy.md): the original README imported from
  `trade_system`, preserved separately with a source notice.

The short version of the architecture is:

```text
web/                                      Next.js frontend
    |
    v
live_trading/src/live_trading/control/    FastAPI control plane
    |
    +--> live_trading/scanner/            event matching and deployable-profit rank
    +--> live_trading/market_data/        shared venue subscriptions and books
    +--> live_trading/workers/            affected-event strategy shards
    +--> live_trading/pooled_session.py   independent event and mode state
    |        |
    |        v
    |    live_trading/src/live_trading/
    |      strategy/                      shared Python trading strategy
    |      runtime.py                     legacy per-event fallback
    |
    +--> backtesting/                     historical replay of that strategy

trade_system/                             original reference implementation
```

The frontend controls and visualizes the system. Trading decisions, sizing,
fills, execution, exits, and PnL remain owned by Python.
