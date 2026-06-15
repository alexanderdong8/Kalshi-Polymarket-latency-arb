from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def write_manifest(root: Path, candidate: dict[str, Any]) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for mapping in candidate["mappings"]:
        row = {
            "name": mapping["name"],
            "kalshi_ticker": mapping["kalshi_ticker"],
            "polymarket_us_slug": mapping["polymarket_us_slug"],
            "polymarket_side": mapping.get("polymarket_side", "long"),
        }
        for key in (
            "polymarket_contract_address",
            "polymarket_yes_token_id",
            "polymarket_no_token_id",
        ):
            if mapping.get(key):
                row[key] = mapping[key]
        outcomes.append(row)
    payload = {
        "event": {
            "name": candidate["name"],
            "description": candidate.get("description"),
            "outcomes": outcomes,
        },
        "review": {
            "approved": True,
            "exhaustive": True,
            "settlement_reviewed": True,
            "candidate_id": candidate["id"],
            "llm_confidence": candidate.get("llm_confidence"),
            "llm_reasoning": candidate.get("llm_reasoning"),
        },
    }
    historical = candidate.get("historical")
    if historical:
        payload["historical"] = historical
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    version = hashlib.sha256(encoded.encode()).hexdigest()[:16]
    path = root / f"{candidate['id']}-{version}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path, version
