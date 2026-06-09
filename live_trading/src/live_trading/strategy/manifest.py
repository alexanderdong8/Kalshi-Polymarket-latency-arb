from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import EventSpec, OutcomeSpec


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class HistoricalOutcome:
    polymarket_contract_address: str | None = None
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


@dataclass(frozen=True)
class EventManifest:
    event: EventSpec
    approved: bool
    exhaustive: bool
    settlement_reviewed: bool
    historical: dict[str, HistoricalOutcome]
    source_path: Path

    @property
    def tradeable(self) -> bool:
        return self.approved and self.exhaustive and self.settlement_reviewed

    def require_tradeable(self) -> None:
        missing = []
        if not self.approved:
            missing.append("approved")
        if not self.exhaustive:
            missing.append("exhaustive")
        if not self.settlement_reviewed:
            missing.append("settlement_reviewed")
        if missing:
            raise ManifestError(
                "Event manifest is not authorized for trading; set and review: "
                + ", ".join(missing)
            )


def load_event_manifest(path: str | Path, *, require_approved: bool = False) -> EventManifest:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise ManifestError(f"Manifest not found: {target}")
    raw: Any = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("event"), dict):
        raise ManifestError("Manifest must contain an event mapping.")
    event_raw = raw["event"]
    name = str(event_raw.get("name") or "").strip()
    rows = event_raw.get("outcomes")
    if not name or not isinstance(rows, list) or len(rows) < 2:
        raise ManifestError("event.name and at least two event.outcomes are required.")

    outcomes: list[OutcomeSpec] = []
    historical: dict[str, HistoricalOutcome] = {}
    seen_names: set[str] = set()
    seen_kalshi: set[str] = set()
    seen_poly: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ManifestError(f"Outcome #{index + 1} must be a mapping.")
        outcome = OutcomeSpec(
            name=str(row.get("name") or "").strip(),
            kalshi_ticker=str(row.get("kalshi_ticker") or "").strip(),
            polymarket_slug=str(
                row.get("polymarket_us_slug") or row.get("polymarket_slug") or ""
            ).strip(),
        )
        if not all((outcome.name, outcome.kalshi_ticker, outcome.polymarket_slug)):
            raise ManifestError(f"Outcome #{index + 1} is missing a required identifier.")
        if outcome.name in seen_names:
            raise ManifestError(f"Duplicate outcome name: {outcome.name}")
        if outcome.kalshi_ticker in seen_kalshi:
            raise ManifestError(f"Duplicate Kalshi ticker: {outcome.kalshi_ticker}")
        if outcome.polymarket_slug in seen_poly:
            raise ManifestError(f"Duplicate Polymarket identifier: {outcome.polymarket_slug}")
        seen_names.add(outcome.name)
        seen_kalshi.add(outcome.kalshi_ticker)
        seen_poly.add(outcome.polymarket_slug)
        outcomes.append(outcome)
        historical[outcome.name] = HistoricalOutcome(
            polymarket_contract_address=_optional(row.get("polymarket_contract_address")),
            polymarket_yes_token_id=_optional(row.get("polymarket_yes_token_id")),
            polymarket_no_token_id=_optional(row.get("polymarket_no_token_id")),
        )

    review = raw.get("review") if isinstance(raw.get("review"), dict) else {}
    manifest = EventManifest(
        event=EventSpec(
            name=name,
            description=_optional(event_raw.get("description")),
            outcomes=tuple(outcomes),
        ),
        approved=bool(review.get("approved", False)),
        exhaustive=bool(review.get("exhaustive", False)),
        settlement_reviewed=bool(review.get("settlement_reviewed", False)),
        historical=historical,
        source_path=target,
    )
    if require_approved:
        manifest.require_tradeable()
    return manifest


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
