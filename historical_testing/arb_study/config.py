from __future__ import annotations

import os
from pathlib import Path


PMXT_KEY_NAMES = (
    "PMXT_API_KEY",
    "pmxt",
    "PMXT",
    "pmxt-key",
    "PMXT_KEY",
)


def load_dotenv(path: str | Path = ".env") -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_pmxt_api_key(env_file: str | Path = ".env") -> str:
    for name in PMXT_KEY_NAMES:
        value = os.getenv(name)
        if value:
            return value

    values = load_dotenv(env_file)
    for name in PMXT_KEY_NAMES:
        value = values.get(name)
        if value:
            return value

    raise RuntimeError(
        "Missing PMXT API key. Add PMXT_API_KEY=... or pmxt-key=... to .env."
    )

