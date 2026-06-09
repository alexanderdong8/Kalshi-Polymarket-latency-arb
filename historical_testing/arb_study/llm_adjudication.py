from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

from .config import load_dotenv
from .serde import read_json, write_json


MODEL = "gpt-4o-mini"
PROMPT_VERSION = 1
INPUT_USD_PER_MILLION = 0.15
OUTPUT_USD_PER_MILLION = 0.60
MAX_PARALLEL_REQUESTS = 4
RESERVED_USD_PER_BATCH = 0.01


@dataclass(frozen=True)
class Adjudication:
    decision: str
    confidence: float
    same_event: bool
    same_outcome: bool
    same_market_type: bool
    same_line: bool
    same_period: bool
    same_start_time: bool
    same_settlement: bool
    orientation: str
    reason: str
    source: str = "openai_structured_output"


class OpenAIAdjudicator:
    def __init__(
        self,
        cache_path: str | Path,
        *,
        budget_usd: float = 7.0,
        api_key: str | None = None,
        model: str = MODEL,
        timeout: int = 180,
        retries: int = 5,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.budget_usd = float(budget_usd)
        self.api_key = api_key or _api_key()
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.cache = (
            read_json(self.cache_path)
            if self.cache_path.exists()
            else {"version": 1, "spent_usd": 0.0, "items": {}, "calls": []}
        )

    @property
    def spent_usd(self) -> float:
        return float(self.cache.get("spent_usd") or 0)

    def adjudicate_many(self, candidates: list[dict[str, Any]], batch_size: int = 10) -> list[Adjudication]:
        results: dict[str, Adjudication] = {}
        missing: list[tuple[str, dict[str, Any]]] = []
        for candidate in candidates:
            key = _cache_key(candidate, self.model)
            cached = self.cache["items"].get(key)
            if cached:
                results[key] = Adjudication(**cached)
            else:
                missing.append((key, candidate))
        batches = [
            missing[offset : offset + batch_size]
            for offset in range(0, len(missing), batch_size)
        ]
        next_batch = 0
        while next_batch < len(batches):
            remaining_budget = self.budget_usd - self.spent_usd
            affordable = int(remaining_budget // RESERVED_USD_PER_BATCH)
            request_count = min(MAX_PARALLEL_REQUESTS, affordable, len(batches) - next_batch)
            if request_count <= 0:
                break
            group = batches[next_batch : next_batch + request_count]
            next_batch += request_count
            completed = []
            with ThreadPoolExecutor(max_workers=request_count) as executor:
                future_map = {
                    executor.submit(self._request, [candidate for _, candidate in batch]): batch
                    for batch in group
                }
                for future in as_completed(future_map):
                    returned, usage = future.result()
                    completed.append((future_map[future], returned, usage))
            group_cost = sum(_usage_cost(usage) for _, _, usage in completed)
            if self.spent_usd + group_cost > self.budget_usd + 1e-9:
                raise RuntimeError(
                    f"OpenAI adjudication would exceed ${self.budget_usd:.2f} hard cap."
                )
            for batch, returned, usage in completed:
                cost = _usage_cost(usage)
                self.cache["spent_usd"] = self.spent_usd + cost
                self.cache["calls"].append(
                    {"model": self.model, "items": len(batch), "usage": usage, "cost_usd": cost}
                )
                for (key, _), item in zip(batch, returned):
                    results[key] = item
                    self.cache["items"][key] = asdict(item)
                write_json(self.cache_path, self.cache)
        output = []
        for candidate in candidates:
            key = _cache_key(candidate, self.model)
            output.append(
                results.get(
                    key,
                    Adjudication(
                        decision="uncertain",
                        confidence=0.0,
                        same_event=False,
                        same_outcome=False,
                        same_market_type=False,
                        same_line=False,
                        same_period=False,
                        same_start_time=False,
                        same_settlement=False,
                        orientation="unknown",
                        reason="OpenAI budget exhausted before this candidate was reviewed.",
                        source="budget_exhausted",
                    ),
                )
            )
        return output

    def _request(self, candidates: list[dict[str, Any]]) -> tuple[list[Adjudication], dict[str, int]]:
        if not self.api_key:
            raise RuntimeError("Missing OpenAI API key. Add OPENAI_API_KEY or openai-api-key to .env.")
        request_json = {
                "model": self.model,
                "temperature": 0,
                "max_output_tokens": 5000,
                "input": [
                    {
                        "role": "system",
                        "content": (
                            "You compare Kalshi and Polymarket binary contracts. Accept exact_locked_pair only "
                            "when the real-world event, selected outcome, market type, numeric line, period, "
                            "event time, cancellation treatment, overtime treatment, and payout behavior are "
                            "compatible enough that buying opposite outcomes guarantees one $1 payout. "
                            "Use same_event_nonidentical_contract for the same contest with any payout-rule risk."
                        ),
                    },
                    {"role": "user", "content": json.dumps(candidates, sort_keys=True)},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "contract_adjudications",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["items"],
                            "properties": {
                                "items": {
                                    "type": "array",
                                    "minItems": len(candidates),
                                    "maxItems": len(candidates),
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": [
                                            "decision", "confidence", "same_event", "same_outcome",
                                            "same_market_type", "same_line", "same_period",
                                            "same_start_time", "same_settlement", "orientation", "reason",
                                        ],
                                        "properties": {
                                            "decision": {
                                                "type": "string",
                                                "enum": [
                                                    "exact_locked_pair",
                                                    "same_event_nonidentical_contract",
                                                    "uncertain",
                                                    "reject",
                                                ],
                                            },
                                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                            "same_event": {"type": "boolean"},
                                            "same_outcome": {"type": "boolean"},
                                            "same_market_type": {"type": "boolean"},
                                            "same_line": {"type": "boolean"},
                                            "same_period": {"type": "boolean"},
                                            "same_start_time": {"type": "boolean"},
                                            "same_settlement": {"type": "boolean"},
                                            "orientation": {"type": "string"},
                                            "reason": {"type": "string"},
                                        },
                                    },
                                }
                            },
                        },
                    }
                },
            }
        last_error: Exception | None = None
        response = None
        for attempt in range(self.retries):
            try:
                response = requests.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=request_json,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt == self.retries - 1:
                    raise
                time.sleep(min(30, 2 ** attempt))
        if response is None:
            raise RuntimeError(f"OpenAI request failed: {last_error}")
        payload = response.json()
        text = payload.get("output_text")
        if not text:
            text = next(
                (
                    content.get("text")
                    for output in payload.get("output", [])
                    for content in output.get("content", [])
                    if content.get("type") == "output_text"
                ),
                None,
            )
        parsed = json.loads(text)
        return [Adjudication(**item) for item in parsed["items"]], payload.get("usage") or {}


def candidate_payload(kalshi: dict[str, Any], polymarket: dict[str, Any], structured: dict[str, Any]) -> dict[str, Any]:
    return {
        "kalshi": {
            "title": kalshi.get("title"),
            "yes_label": kalshi.get("yes_sub_title"),
            "close_time": kalshi.get("close_time"),
            "expected_expiration_time": kalshi.get("expected_expiration_time"),
            "rules_primary": kalshi.get("rules_primary"),
            "rules_secondary": kalshi.get("rules_secondary"),
        },
        "polymarket": {
            "question": polymarket.get("question"),
            "group_item_title": polymarket.get("groupItemTitle"),
            "outcomes": polymarket.get("outcomes"),
            "game_start_time": polymarket.get("gameStartTime"),
            "end_date": polymarket.get("endDate"),
            "description": polymarket.get("description"),
            "resolution_source": polymarket.get("resolutionSource"),
        },
        "structured_identity": structured,
    }


def _cache_key(candidate: dict[str, Any], model: str) -> str:
    raw = json.dumps(
        {"candidate": candidate, "model": model, "prompt_version": PROMPT_VERSION},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _usage_cost(usage: dict[str, Any]) -> float:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return (
        input_tokens * INPUT_USD_PER_MILLION
        + output_tokens * OUTPUT_USD_PER_MILLION
    ) / 1_000_000


def _api_key() -> str | None:
    for name in ("OPENAI_API_KEY", "openai-api-key"):
        value = os.getenv(name)
        if value:
            return value
    for path in (Path(".env"), Path("historical_testing/.env")):
        values = load_dotenv(path)
        for name in ("OPENAI_API_KEY", "openai-api-key"):
            if values.get(name):
                return values[name]
    return None
