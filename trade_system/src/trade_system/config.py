from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .models import Credentials, Endpoints, EventSpec, OutcomeSpec


class ConfigError(ValueError):
    pass


def load_event(path: str | Path) -> EventSpec:
    path = Path(path).expanduser()
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "event" not in raw:
        raise ConfigError(f"Config {path} missing top-level 'event' key")
    event = raw["event"]
    if not isinstance(event, dict):
        raise ConfigError("'event' must be a mapping")
    name = event.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("'event.name' must be a non-empty string")
    outcomes_raw = event.get("outcomes") or []
    if not isinstance(outcomes_raw, list) or len(outcomes_raw) < 2:
        raise ConfigError("'event.outcomes' must list at least 2 outcomes")

    outcomes: list[OutcomeSpec] = []
    seen_kalshi: set[str] = set()
    seen_poly: set[str] = set()
    for index, item in enumerate(outcomes_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"outcome #{index} must be a mapping")
        try:
            outcome = OutcomeSpec(
                name=str(item["name"]).strip(),
                kalshi_ticker=str(item["kalshi_ticker"]).strip(),
                polymarket_slug=str(item["polymarket_slug"]).strip(),
            )
        except KeyError as exc:
            raise ConfigError(f"outcome #{index} missing required field: {exc.args[0]}") from None
        if not outcome.name or not outcome.kalshi_ticker or not outcome.polymarket_slug:
            raise ConfigError(f"outcome #{index} has empty field(s)")
        if outcome.kalshi_ticker in seen_kalshi:
            raise ConfigError(f"duplicate kalshi_ticker {outcome.kalshi_ticker!r}")
        if outcome.polymarket_slug in seen_poly:
            raise ConfigError(f"duplicate polymarket_slug {outcome.polymarket_slug!r}")
        seen_kalshi.add(outcome.kalshi_ticker)
        seen_poly.add(outcome.polymarket_slug)
        outcomes.append(outcome)

    return EventSpec(
        name=name.strip(),
        description=(event.get("description") or None),
        outcomes=tuple(outcomes),
    )


def _load_env_files() -> None:
    here = Path.cwd()
    for path in (here / ".env", here.parent / ".env"):
        if path.exists():
            load_dotenv(path, override=False)


def load_credentials() -> Credentials:
    _load_env_files()
    private_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    if private_key_pem:
        private_key_pem = private_key_pem.replace("\\n", "\n")
    elif key_path:
        try:
            private_key_pem = Path(key_path).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Cannot read KALSHI_PRIVATE_KEY_PATH={key_path}: {exc}") from exc
    return Credentials(
        kalshi_key_id=os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_ACCESS_KEY"),
        kalshi_private_key_pem=private_key_pem,
        polymarket_us_key_id=os.getenv("POLYMARKET_US_KEY_ID") or os.getenv("POLYMARKET_KEY_ID"),
        polymarket_us_secret_key=os.getenv("POLYMARKET_US_SECRET_KEY") or os.getenv("POLYMARKET_SECRET_KEY"),
    )


def load_endpoints() -> Endpoints:
    _load_env_files()
    return Endpoints(
        kalshi_ws_url=os.getenv("KALSHI_WS_URL", Endpoints.kalshi_ws_url),
        polymarket_ws_url=os.getenv("POLYMARKET_US_WS_URL", Endpoints.polymarket_ws_url),
        polymarket_gateway_base=os.getenv("POLYMARKET_US_GATEWAY_BASE", Endpoints.polymarket_gateway_base),
    )
