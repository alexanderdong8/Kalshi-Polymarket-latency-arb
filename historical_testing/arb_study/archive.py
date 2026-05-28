from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Iterator

import fsspec
import requests


POLY_BASE = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
KALSHI_BASE = "https://r2kalshi.pmxt.dev/kalshi_orderbook_{hour}.parquet"


def parse_hour(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    if len(normalized) == 13:
        normalized = f"{normalized}:00:00+00:00"
    if len(normalized) == 16:
        normalized = f"{normalized}:00+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def iter_hours(start: str, end: str) -> Iterator[str]:
    current = parse_hour(start)
    stop = parse_hour(end)
    while current < stop:
        yield current.strftime("%Y-%m-%dT%H")
        current += timedelta(hours=1)


def parquet_url(venue: str, hour: str) -> str:
    if venue == "polymarket":
        return POLY_BASE.format(hour=hour)
    if venue == "kalshi":
        return KALSHI_BASE.format(hour=hour)
    raise ValueError(f"Unsupported archive venue: {venue}")


def remote_exists(url: str, timeout: int = 15) -> bool:
    try:
        resp = requests.head(url, timeout=timeout)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def https_filesystem():
    return fsspec.filesystem("https")


def available_archive_hours(venue: str) -> list[str]:
    if venue == "polymarket":
        page = "https://archive.pmxt.dev/Polymarket/v2"
        pattern = r"polymarket_orderbook_(\d{4}-\d{2}-\d{2}T\d{2})\.parquet"
    elif venue == "kalshi":
        page = "https://archive.pmxt.dev/Kalshi"
        pattern = r"kalshi_orderbook_(\d{4}-\d{2}-\d{2}T\d{2})\.parquet"
    else:
        raise ValueError(f"Unsupported archive venue: {venue}")

    resp = requests.get(page, timeout=30)
    resp.raise_for_status()
    return sorted(set(re.findall(pattern, resp.text)))


def overlapping_archive_hours() -> list[str]:
    poly = set(available_archive_hours("polymarket"))
    kalshi = set(available_archive_hours("kalshi"))
    direct_overlap = poly & kalshi
    if direct_overlap:
        return sorted(direct_overlap)

    # The archive HTML pages expose only a rolling listing. Direct R2 URLs often
    # remain available beyond the visible index, so probe the Polymarket v2
    # hours against Kalshi before declaring there is no overlap.
    probed = [
        hour
        for hour in sorted(poly)
        if remote_exists(parquet_url("kalshi", hour), timeout=10)
    ]
    return probed
