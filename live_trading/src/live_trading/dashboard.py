from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from nicegui import ui
import plotly.graph_objects as go


def main() -> None:
    parser = argparse.ArgumentParser(description="Live trading NiceGUI dashboard")
    parser.add_argument("--state", required=True)
    parser.add_argument("--emergency-stop", required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    build_dashboard(Path(args.state), Path(args.emergency_stop))
    ui.run(port=args.port, title="Prediction Market Basket Trader", reload=False)


def build_dashboard(state_path: Path, emergency_path: Path) -> None:
    ui.colors(primary="#173f35", secondary="#d7b45a", negative="#b42318")
    mode_banner = ui.label("WAITING FOR RUNTIME").classes(
        "w-full text-center text-white text-xl font-bold py-3 bg-grey-7"
    )
    with ui.row().classes("w-full items-center justify-between px-4"):
        title = ui.label("Prediction Market Basket Trader").classes("text-2xl font-bold")
        event_label = ui.label("")
        ui.button(
            "EMERGENCY STOP",
            on_click=lambda: _activate_stop(emergency_path),
            color="negative",
        ).props("unelevated")

    with ui.tabs().classes("w-full") as tabs:
        live_tab = ui.tab("Event")
        outcome_tab = ui.tab("Outcome Detail")
        records_tab = ui.tab("Orders and Positions")
        health_tab = ui.tab("Stream Health")

    with ui.tab_panels(tabs, value=live_tab).classes("w-full"):
        with ui.tab_panel(live_tab):
            basket_plot = ui.plotly(_empty_figure("Basket Cost")).classes("w-full h-96")
            evaluation_table = ui.table(
                columns=[
                    {"name": "outcome", "label": "Outcome", "field": "outcome"},
                    {"name": "venue", "label": "Chosen Venue", "field": "venue"},
                    {"name": "vwap", "label": "VWAP", "field": "vwap"},
                    {"name": "fee", "label": "Fee", "field": "fee"},
                ],
                rows=[],
            ).classes("w-full")
        with ui.tab_panel(outcome_tab):
            outcome_select = ui.select([], label="Outcome").classes("w-96")
            outcome_plot = ui.plotly(_empty_figure("Outcome Prices and Depth")).classes("w-full h-96")
        with ui.tab_panel(records_tab):
            orders_table = ui.table(
                columns=[
                    {"name": "ts", "label": "Time", "field": "ts"},
                    {"name": "outcome", "label": "Outcome", "field": "outcome"},
                    {"name": "venue", "label": "Venue", "field": "venue"},
                    {"name": "side", "label": "Side", "field": "side"},
                    {"name": "requested", "label": "Requested", "field": "requested"},
                    {"name": "filled", "label": "Filled", "field": "filled"},
                    {"name": "price", "label": "Price", "field": "price"},
                ],
                rows=[],
            ).classes("w-full")
            fills_table = ui.table(
                columns=[
                    {"name": "ts", "label": "Time", "field": "ts"},
                    {"name": "outcome", "label": "Outcome", "field": "outcome"},
                    {"name": "venue", "label": "Venue", "field": "venue"},
                    {"name": "side", "label": "Side", "field": "side"},
                    {"name": "size", "label": "Size", "field": "size"},
                    {"name": "price", "label": "Price", "field": "price"},
                    {"name": "fees", "label": "Fees", "field": "fees"},
                ],
                rows=[],
            ).classes("w-full")
            positions_table = ui.table(
                columns=[
                    {"name": "basket_id", "label": "Basket", "field": "basket_id"},
                    {"name": "size", "label": "Size", "field": "size"},
                    {"name": "cost", "label": "Cost / Share", "field": "cost"},
                    {"name": "fees", "label": "Fees / Share", "field": "fees"},
                ],
                rows=[],
            ).classes("w-full")
            accounting_json = ui.json_editor({"content": {"json": {}}}).classes("w-full")
        with ui.tab_panel(health_tab):
            health_json = ui.json_editor({"content": {"json": {}}}).classes("w-full")

    history: dict[str, list[Any]] = {"ts": [], "cost": [], "threshold": [], "payout": []}

    def refresh() -> None:
        payload = _read_state(state_path)
        if not payload:
            return
        mode = str(payload.get("mode") or "monitor").upper()
        mode_banner.text = "LIVE MONEY" if mode == "LIVE" else mode
        mode_banner.classes(
            replace="w-full text-center text-white text-xl font-bold py-3 "
            + ("bg-red-8" if mode == "LIVE" else "bg-green-8")
        )
        title.text = "Prediction Market Basket Trader"
        event_label.text = f"{payload.get('event', '')} | Capital ${payload.get('capital_limit', '0')}"
        evaluation = payload.get("evaluation") or {}
        if evaluation:
            history["ts"].append(evaluation.get("ts"))
            history["cost"].append(float(evaluation.get("entry_cost") or 0))
            history["threshold"].append(float(evaluation.get("threshold") or 0.98))
            history["payout"].append(1.0)
            for key in history:
                history[key] = history[key][-1200:]
            basket_plot.figure = _basket_figure(
                history,
                mode,
                payload.get("attempts") or [],
                payload.get("exits") or [],
            )
            basket_plot.update()
            evaluation_table.rows = evaluation.get("legs") or []
            evaluation_table.update()

        books = payload.get("books") or {}
        outcomes = sorted({row.get("outcome") for row in books.values() if row.get("outcome")})
        outcome_select.options = outcomes
        if outcomes and outcome_select.value not in outcomes:
            outcome_select.value = outcomes[0]
        outcome_select.update()
        if outcome_select.value:
            outcome_plot.figure = _outcome_figure(
                books,
                str(outcome_select.value),
                mode,
                payload.get("fills") or [],
            )
            outcome_plot.update()

        orders_table.rows = payload.get("orders") or []
        orders_table.update()
        fills_table.rows = payload.get("fills") or []
        fills_table.update()
        positions_table.rows = [
            {
                "basket_id": row.get("basket_id"),
                "size": row.get("target_basket_size"),
                "cost": row.get("cost_basis_per_share_total"),
                "fees": row.get("entry_fees_per_share_total"),
            }
            for row in payload.get("positions") or []
        ]
        positions_table.update()
        accounting_json.properties["content"]["json"] = payload.get("accounting") or {}
        accounting_json.update()
        health_json.properties["content"]["json"] = {
            **(payload.get("stream_health") or {}),
            "emergency_stop": payload.get("emergency_stop"),
            "book_ages_ms": {key: row.get("age_ms") for key, row in books.items()},
        }
        health_json.update()

    ui.timer(0.25, refresh)


def _activate_stop(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Emergency stop activated from dashboard.\n", encoding="utf-8")
    ui.notify("Emergency stop active. New entries are disabled and resting orders are cancelling.", type="negative")


def _read_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return {}


def _empty_figure(title: str) -> go.Figure:
    figure = go.Figure()
    figure.update_layout(template="plotly_white", title=title)
    return figure


def _basket_figure(
    history: dict[str, list[Any]],
    mode: str,
    attempts: list[dict[str, Any]],
    exits: list[dict[str, Any]],
) -> go.Figure:
    figure = go.Figure()
    figure.add_scatter(x=history["ts"], y=history["cost"], name="Basket entry cost")
    figure.add_scatter(x=history["ts"], y=history["threshold"], name="Entry threshold")
    figure.add_scatter(x=history["ts"], y=history["payout"], name="$1 settlement payout")
    buy_rows = [row for row in attempts if row.get("outcome") == "complete"]
    figure.add_scatter(
        x=[row.get("ts") for row in buy_rows],
        y=[
            float((row.get("fire_context") or {}).get("projected_entry_cost_per_share") or 0)
            for row in buy_rows
        ],
        mode="markers",
        marker={"symbol": "triangle-up", "size": 12, "color": "#b42318"},
        name="Basket buy",
    )
    sell_rows = [row for row in exits if row.get("all_legs_filled")]
    figure.add_scatter(
        x=[row.get("ts") for row in sell_rows],
        y=[float(row.get("realized_proceeds_per_share") or 0) for row in sell_rows],
        mode="markers",
        marker={"symbol": "triangle-down", "size": 12, "color": "#027a48"},
        name="Basket sell",
    )
    figure.update_layout(
        template="plotly_white",
        yaxis_title="Dollars per complete basket share",
        annotations=[
            {
                "text": "LIVE MONEY" if mode == "LIVE" else mode,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "opacity": 0.12,
                "font": {"size": 56, "color": "red" if mode == "LIVE" else "green"},
            }
        ],
    )
    return figure


def _outcome_figure(
    books: dict[str, Any],
    outcome: str,
    mode: str,
    fills: list[dict[str, Any]],
) -> go.Figure:
    figure = go.Figure()
    for row in books.values():
        if row.get("outcome") != outcome:
            continue
        venue = row.get("venue")
        bids = row.get("bids") or []
        asks = row.get("asks") or []
        figure.add_bar(
            x=[float(level[0]) for level in bids],
            y=[float(level[1]) for level in bids],
            name=f"{venue} bids",
        )
        figure.add_bar(
            x=[float(level[0]) for level in asks],
            y=[-float(level[1]) for level in asks],
            name=f"{venue} asks",
        )
    outcome_fills = [row for row in fills if row.get("outcome") == outcome]
    figure.add_scatter(
        x=[float(row["price"]) for row in outcome_fills],
        y=[float(row["size"]) for row in outcome_fills],
        mode="markers",
        text=[f"{row['side']} {row['venue']}" for row in outcome_fills],
        name="Leg trades",
        marker={"size": 11, "color": "#d7b45a"},
    )
    figure.update_layout(
        template="plotly_white",
        title=f"{outcome} | {mode}",
        barmode="overlay",
        xaxis_title="YES price",
        yaxis_title="Displayed depth (asks below zero)",
    )
    return figure


if __name__ == "__main__":
    main()
