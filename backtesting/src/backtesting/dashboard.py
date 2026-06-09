from __future__ import annotations

import argparse
import json
from pathlib import Path

from nicegui import ui
import plotly.graph_objects as go


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest playback dashboard")
    parser.add_argument("--run", required=True)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    build(Path(args.run))
    ui.run(port=args.port, title="Backtest Playback", reload=False)


def build(run_dir: Path) -> None:
    payload = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    ui.label("BACKTEST: PMXT KALSHI + INTERNATIONAL POLYMARKET").classes(
        "w-full bg-blue-9 text-white text-center text-xl font-bold py-3"
    )
    ui.label(f"Run {payload['run_id']} | Each simulation starts with $1,000").classes(
        "text-xl font-semibold"
    )
    simulations = [
        (event["event"], result)
        for event in payload["events"]
        for result in event["results"]
    ]
    labels = [
        f"{event} | {result['delay_ms']} ms | {result['fill_model']}"
        for event, result in simulations
    ]
    selector = ui.select(labels, value=labels[0] if labels else None, label="Simulation").classes("w-full")
    plot = ui.plotly(go.Figure()).classes("w-full h-96")
    timeline = ui.slider(min=0, max=0, value=0).classes("w-full")
    status = ui.label("")
    results_table = ui.table(
        columns=[
            {"name": "event", "label": "Event", "field": "event"},
            {"name": "delay", "label": "Delay", "field": "delay"},
            {"name": "model", "label": "Fill model", "field": "model"},
            {"name": "cash", "label": "Ending cash", "field": "cash"},
            {"name": "gain", "label": "Money gained", "field": "gain"},
        ],
        rows=[
            {
                "event": event,
                "delay": f"{result['delay_ms']} ms",
                "model": result["fill_model"],
                "cash": result["ending_cash"],
                "gain": result["total_money_gained"],
            }
            for event, result in simulations
        ],
    ).classes("w-full")

    def refresh() -> None:
        if not selector.value:
            return
        index = labels.index(selector.value)
        event, result = simulations[index]
        fills = result.get("fills") or []
        timeline.max = max(0, len(fills) - 1)
        visible = fills[: int(timeline.value) + 1] if fills else []
        figure = go.Figure()
        for side, color in (("buy", "#b42318"), ("sell", "#027a48")):
            rows = [row for row in visible if row["side"] == side]
            figure.add_scatter(
                x=[row["timestamp"] for row in rows],
                y=[float(row["price"]) for row in rows],
                mode="markers+lines",
                name=side.upper(),
                marker={"color": color, "size": 10},
                text=[f"{row['outcome']} @ {row['venue']}" for row in rows],
            )
        figure.update_layout(
            template="plotly_white",
            title=f"{event}: fill playback",
            yaxis_title="YES price",
        )
        plot.figure = figure
        plot.update()
        status.text = (
            f"Frame {int(timeline.value) + 1 if fills else 0}/{len(fills)} | "
            f"Ending cash ${result['ending_cash']} | Gained ${result['total_money_gained']}"
        )
        timeline.update()

    selector.on_value_change(lambda _: refresh())
    timeline.on_value_change(lambda _: refresh())
    ui.timer(0.25, refresh, once=True)


if __name__ == "__main__":
    main()
