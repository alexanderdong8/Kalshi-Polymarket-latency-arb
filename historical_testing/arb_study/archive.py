from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
import time
from typing import Any, Iterator

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


def require_raw_historical_object(url: str) -> str:
    allowed_prefixes = ("https://r2v2.pmxt.dev/", "https://r2kalshi.pmxt.dev/")
    if not url.startswith(allowed_prefixes) or not url.endswith(".parquet"):
        raise ValueError("Historical PMXT replay accepts only raw verified Parquet archive objects.")
    return url


def https_filesystem():
    return fsspec.filesystem("https")


def available_archive_hours(venue: str, max_pages: int = 100) -> list[str]:
    if venue == "polymarket":
        page = "https://archive.pmxt.dev/Polymarket/v2"
        pattern = r"polymarket_orderbook_(\d{4}-\d{2}-\d{2}T\d{2})\.parquet"
    elif venue == "kalshi":
        page = "https://archive.pmxt.dev/Kalshi"
        pattern = r"kalshi_orderbook_(\d{4}-\d{2}-\d{2}T\d{2})\.parquet"
    else:
        raise ValueError(f"Unsupported archive venue: {venue}")

    found: set[str] = set()
    empty_pages = 0
    advertised_pages = max_pages
    for page_number in range(1, max_pages + 1):
        resp = _get_archive_page(page, page_number)
        resp.raise_for_status()
        page_count = re.search(r"Page\s+\d+\s+of\s+(\d+)", resp.text, flags=re.IGNORECASE)
        if page_count:
            advertised_pages = min(max_pages, int(page_count.group(1)))
        hours = set(re.findall(pattern, resp.text))
        if not hours:
            empty_pages += 1
            if empty_pages >= 2:
                break
            continue
        empty_pages = 0
        before = len(found)
        found.update(hours)
        if len(found) == before and page_number > 1:
            break
        if page_number >= advertised_pages:
            break
    return sorted(found)


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


def archive_inventory(verify_objects: bool = True) -> dict[str, Any]:
    """Return the public PMXT v2 overlap and validate every claimed shared object."""
    listing_errors = []
    try:
        poly = available_archive_hours("polymarket")
    except requests.RequestException as exc:
        poly = []
        listing_errors.append({"venue": "polymarket", "error": str(exc)})
    try:
        kalshi = available_archive_hours("kalshi")
    except requests.RequestException as exc:
        kalshi = []
        listing_errors.append({"venue": "kalshi", "error": str(exc)})
    overlap = sorted(set(poly) & set(kalshi))
    if verify_objects:
        with ThreadPoolExecutor(max_workers=16) as executor:
            verified = [
                hour
                for hour, exists in zip(overlap, executor.map(_raw_hour_exists, overlap))
                if exists
            ]
    else:
        verified = overlap
    return {
        "source": "public_pmxt_archive_parquet_inventory",
        "polymarket_v2_hours": len(poly),
        "polymarket_v2_first": poly[0] if poly else None,
        "polymarket_v2_last": poly[-1] if poly else None,
        "kalshi_hours": len(kalshi),
        "kalshi_first": kalshi[0] if kalshi else None,
        "kalshi_last": kalshi[-1] if kalshi else None,
        "overlap_hours": len(overlap),
        "verified_overlap_hours": len(verified),
        "overlap_first": verified[0] if verified else None,
        "overlap_last": verified[-1] if verified else None,
        "hours": verified,
        "listing_complete": not listing_errors,
        "listing_errors": listing_errors,
        "historical_guardrail": (
            "Only raw Parquet objects verified in both venue archives count as historical L2. "
            "Do not treat a hosted current-book fallback as historical data."
        ),
    }


def _raw_hour_exists(hour: str) -> bool:
    return remote_exists(
        require_raw_historical_object(parquet_url("polymarket", hour)),
        timeout=10,
    ) and remote_exists(
        require_raw_historical_object(parquet_url("kalshi", hour)),
        timeout=10,
    )


def _get_archive_page(url: str, page_number: int, retries: int = 4):
    last_error: requests.RequestException | None = None
    for attempt in range(retries):
        try:
            return requests.get(url, params={"page": page_number}, timeout=30)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(0.75 * (attempt + 1))
    assert last_error is not None
    raise last_error
