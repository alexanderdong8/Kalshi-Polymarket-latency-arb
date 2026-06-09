# Operations

## Live and Paper

Install the package in editable mode, populate venue credentials, and review an
event manifest. The application refuses manifests whose three review flags are
not all true.

```text
python -m live_trading run --mode monitor --config live_trading/events/event.yaml
python -m live_trading run --mode paper --capital 100 --config live_trading/events/event.yaml
python -m live_trading run --mode live --capital 100 --config live_trading/events/event.yaml
```

Use `--no-dashboard` for a headless process. The dashboard defaults to
`http://127.0.0.1:8080`. Deleting the event data directory's
`EMERGENCY_STOP` file is a deliberate manual reset after the process has been
inspected.

## Historical Replay

Catalog selection:

```text
python -m backtesting select --query "the last ten NBA games" --catalog backtesting/data/catalog.json
```

The catalog contains deterministic event records whose `manifest` field points
to reviewed event YAML. Approve the printed selection, then run and view it:

```text
python -m backtesting run --manifest backtesting/runs/selection.yaml
python -m backtesting view --run backtesting/runs/<run-id>
```

`view` starts a NiceGUI playback dashboard on port `8081`; use
`--no-dashboard` to print results only. The fill timeline can be scrubbed while
the final delay/model table remains visible.

## Performance Check

```text
python -m live_trading strategy-benchmark --iterations 10000
```

This reports detector evaluations separately from dashboard-state
serialization so UI cost is not confused with market-processing latency.

An event manifest may use `historical.archive.hours` for raw PMXT Parquet or
`historical.archive.fixture` for deterministic local JSONL. Replay refuses
missing outcomes, non-overlapping books, unapproved manifests, and absent
international Polymarket fee metadata.
