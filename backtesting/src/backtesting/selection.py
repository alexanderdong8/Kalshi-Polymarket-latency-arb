from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml


def query_to_filters(query: str) -> dict[str, Any]:
    if os.getenv("OPENAI_API_KEY"):
        return _llm_filters(query)
    count_match = re.search(r"\b(\d+)\b", query)
    word_counts = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "ten": 10,
    }
    count = int(count_match.group(1)) if count_match else next(
        (number for word, number in word_counts.items() if re.search(rf"\b{word}\b", query.lower())),
        10,
    )
    category = next(
        (name for name in ("nba", "nfl", "mlb", "nhl", "politics", "crypto") if name in query.lower()),
        None,
    )
    return {
        "category": category,
        "event_name_contains": query,
        "start_date": None,
        "end_date": date.today().isoformat(),
        "count": count,
        "parser": "deterministic_fallback",
    }


def resolve_catalog(filters: dict[str, Any], catalog_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    events = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(events, list):
        raise ValueError("Catalog must be a list or contain an events list.")
    category = str(filters.get("category") or "").lower()
    rows = [
        row
        for row in events
        if not category or category in str(row.get("category") or "").lower()
    ]
    rows.sort(key=lambda row: str(row.get("settled_at") or row.get("date") or ""), reverse=True)
    return rows[: int(filters.get("count") or 10)]


def write_selection_manifest(
    query: str,
    filters: dict[str, Any],
    events: list[dict[str, Any]],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "selection": {
            "query": query,
            "filters": filters,
            "events": events,
            "exclusions": [],
            "archive_coverage": "validated when each event is run",
            "settlement_warnings": [
                row.get("settlement_warning")
                for row in events
                if row.get("settlement_warning")
            ],
        },
        "review": {"approved": False},
    }
    output.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _llm_filters(query: str) -> dict[str, Any]:
    from openai import OpenAI

    schema = {
        "type": "object",
        "properties": {
            "category": {"type": ["string", "null"]},
            "event_name_contains": {"type": ["string", "null"]},
            "start_date": {"type": ["string", "null"]},
            "end_date": {"type": ["string", "null"]},
            "count": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "required": ["category", "event_name_contains", "start_date", "end_date", "count"],
        "additionalProperties": False,
    }
    response = OpenAI().responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        input=[
            {
                "role": "system",
                "content": (
                    "Convert the request into catalog filters only. Never calculate prices, "
                    "fills, PnL, or trading decisions."
                ),
            },
            {"role": "user", "content": query},
        ],
        text={"format": {"type": "json_schema", "name": "event_filters", "schema": schema, "strict": True}},
    )
    result = json.loads(response.output_text)
    result["parser"] = "openai_structured_output"
    return result
