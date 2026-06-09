from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from live_trading.strategy.manifest import load_event_manifest

from .pmxt import load_updates, validate_coverage
from .selection import query_to_filters, resolve_catalog, write_selection_manifest
from .simulator import result_payload, run_delay_matrix


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic PMXT strategy replay")
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select", help="Resolve a natural-language request against an event catalog")
    select.add_argument("--query", required=True)
    select.add_argument("--catalog", default="backtesting/data/catalog.json")
    select.add_argument("--out", default="backtesting/runs/selection.yaml")
    select.add_argument("--approve", action="store_true")
    run = sub.add_parser("run", help="Run an approved selection or event manifest")
    run.add_argument("--manifest", required=True)
    run.add_argument("--out-dir", default="backtesting/runs")
    view = sub.add_parser("view", help="Display a completed run summary")
    view.add_argument("--run", required=True)
    view.add_argument("--dashboard", action=argparse.BooleanOptionalAction, default=True)
    view.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    if args.command == "select":
        _select(args)
    elif args.command == "run":
        _run(args)
    else:
        _view(args)


def _select(args: argparse.Namespace) -> None:
    filters = query_to_filters(args.query)
    events = resolve_catalog(filters, Path(args.catalog))
    output = Path(args.out)
    write_selection_manifest(args.query, filters, events, output)
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    print(yaml.safe_dump(payload, sort_keys=False))
    approved = args.approve
    if sys.stdin.isatty() and not approved:
        approved = input("Approve exactly these events for backtesting? [y/N] ").strip().lower() == "y"
    if approved:
        payload["review"]["approved"] = True
        output.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    print(f"selection_manifest={output} approved={approved}")


def _run(args: argparse.Namespace) -> None:
    path = Path(args.manifest).resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "selection" in raw:
        if not raw.get("review", {}).get("approved"):
            raise ValueError("Selection manifest is not approved.")
        event_paths = [Path(path.parent, row["manifest"]).resolve() for row in raw["selection"]["events"]]
    else:
        event_paths = [path]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    all_results = []
    for event_path in event_paths:
        event_raw = yaml.safe_load(event_path.read_text(encoding="utf-8"))
        manifest = load_event_manifest(event_path, require_approved=True)
        historical = event_raw.get("historical") or {}
        updates = load_updates(manifest, historical.get("archive") or {})
        coverage = validate_coverage(manifest, updates)
        if not coverage["valid"]:
            raise ValueError(f"Incomplete or invalid L2 overlap for {manifest.event.name}: {coverage}")
        results = run_delay_matrix(
            manifest,
            updates,
            target_size=Decimal(str(historical.get("target_size") or 100)),
        )
        all_results.append(
            {
                "event": manifest.event.name,
                "venue_split": "PMXT Kalshi plus PMXT international Polymarket",
                "coverage": coverage,
                "results": [result_payload(result) for result in results],
            }
        )
    payload = {
        "run_id": run_id,
        "starting_cash_per_simulation": "1000",
        "total_money_gained_definition": "ending_cash - 1000",
        "events": all_results,
    }
    (run_dir / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_html(run_dir / "index.html", payload)
    print(json.dumps(payload, indent=2))
    print(f"run_dir={run_dir}")


def _view(args: argparse.Namespace) -> None:
    run_dir = Path(args.run)
    payload = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    print(json.dumps(payload, indent=2))
    print(f"html={(run_dir / 'index.html').resolve()}")
    if args.dashboard:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "backtesting.dashboard",
                "--run",
                str(run_dir),
                "--port",
                str(args.port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"dashboard=http://127.0.0.1:{args.port}")


def _write_html(path: Path, payload: dict[str, Any]) -> None:
    rows = []
    for event in payload["events"]:
        for result in event["results"]:
            rows.append(
                "<tr>"
                f"<td>{event['event']}</td><td>{result['delay_ms']} ms</td>"
                f"<td>{result['fill_model']}</td><td>${result['ending_cash']}</td>"
                f"<td>${result['total_money_gained']}</td><td>{result['completed_baskets']}</td>"
                "</tr>"
            )
    path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Backtest Results</title>"
        "<style>body{font-family:system-ui;margin:2rem}table{border-collapse:collapse;width:100%}"
        "th,td{padding:.6rem;border:1px solid #ddd;text-align:left}th{background:#173f35;color:white}"
        "</style></head><body><h1>Backtest Results</h1>"
        "<p>Historical venues: Kalshi + international Polymarket via PMXT. "
        "Each simulation starts with $1,000.</p><table><thead><tr>"
        "<th>Event</th><th>Delay</th><th>Fill model</th><th>Ending cash</th>"
        "<th>Money gained</th><th>Baskets</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
