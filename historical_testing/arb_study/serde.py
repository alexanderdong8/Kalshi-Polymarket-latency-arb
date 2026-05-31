from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from .models import MatchedMarket, MarketRef, Opportunity, OutcomeRef

T = TypeVar("T")


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def write_json(path: str | Path, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(
        json.dumps(data, cls=EnhancedJSONEncoder, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for attempt in range(6):
        try:
            temporary.replace(target)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.25 * (attempt + 1))


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def matched_market_from_dict(raw: dict[str, Any]) -> MatchedMarket:
    return MatchedMarket(
        match_id=raw["match_id"],
        polymarket=_market_from_dict(raw["polymarket"]),
        kalshi=_market_from_dict(raw["kalshi"]),
        relation=raw["relation"],
        confidence=float(raw["confidence"]),
        price_difference=raw.get("price_difference"),
        reasoning=raw.get("reasoning"),
        resolution_date_warning=raw.get("resolution_date_warning"),
    )


def _market_from_dict(raw: dict[str, Any]) -> MarketRef:
    return MarketRef(
        venue=raw["venue"],
        market_id=raw["market_id"],
        title=raw["title"],
        slug=raw.get("slug"),
        url=raw.get("url"),
        category=raw.get("category"),
        resolution_date=raw.get("resolution_date"),
        contract_address=raw.get("contract_address"),
        yes=_outcome_from_dict(raw["yes"]),
        no=_outcome_from_dict(raw["no"]),
        raw=raw.get("raw", {}),
    )


def _outcome_from_dict(raw: dict[str, Any]) -> OutcomeRef:
    return OutcomeRef(
        outcome_id=raw["outcome_id"],
        label=raw["label"],
        best_bid=raw.get("best_bid"),
        best_ask=raw.get("best_ask"),
    )


def opportunity_from_dict(raw: dict[str, Any]) -> Opportunity:
    return Opportunity(**raw)
