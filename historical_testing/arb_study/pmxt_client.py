from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Iterable

import requests

from .models import MatchedMarket, MarketRef, OutcomeRef


PMXT_API_BASE = "https://api.pmxt.dev"


class PMXTClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = PMXT_API_BASE,
        timeout: int = 45,
        retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def call_router_method(self, method: str, args: dict[str, Any]) -> Any:
        url = f"{self.base_url}/api/router/{method}"
        body = {"args": [args]}
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.post(url, data=json.dumps(body), timeout=self.timeout)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(1.5 * (attempt + 1))
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
                if data.get("success") is False:
                    raise RuntimeError(data.get("error") or data)
                return data.get("data", data)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"PMXT {method} failed after retries: {last_error}") from last_error

    def fetch_matched_markets(
        self,
        category: str | None = None,
        limit: int = 50,
        min_difference: float = 0.0,
    ) -> list[dict[str, Any]]:
        args: dict[str, Any] = {"limit": limit, "minDifference": min_difference}
        if category:
            args["category"] = category
        return list(self.call_router_method("fetchMatchedMarkets", args))

    def fetch_market_matches(
        self,
        market_id: str,
        min_confidence: float = 0.9,
        relation: str = "identity",
        include_prices: bool = True,
    ) -> list[dict[str, Any]]:
        args = {
            "marketId": market_id,
            "minConfidence": min_confidence,
            "relation": relation,
            "includePrices": include_prices,
        }
        return list(self.call_router_method("fetchMarketMatches", args))

    def get_v0(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/v0/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(2.0 * (attempt + 1))
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return {"data": data}
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"PMXT /v0/{path} failed after retries: {last_error}") from last_error

    def fetch_matched_market_clusters(
        self,
        limit: int = 250,
        offset: int = 0,
        relation: str = "identity",
        venues: tuple[str, str] = ("polymarket", "kalshi"),
        min_venues: int = 2,
        sort: str = "volume",
        include_raw_matches: bool = True,
    ) -> list[dict[str, Any]]:
        data = self.get_v0(
            "matched-market-clusters",
            {
                "relation": relation,
                "venues": ",".join(venues),
                "minVenues": min_venues,
                "limit": limit,
                "offset": offset,
                "sort": sort,
                "includeRawMatches": str(include_raw_matches).lower(),
            },
        )
        return list(data.get("data") or [])


def _outcome_from_market(raw: dict[str, Any], side: str) -> OutcomeRef:
    outcome = raw.get(side) or {}
    if not outcome:
        for item in raw.get("outcomes") or []:
            label = str(item.get("label", "")).lower()
            if side == "yes" and label not in {"no", "not"} and not label.startswith("not "):
                outcome = item
                break
            if side == "no" and (label == "no" or label.startswith("not ")):
                outcome = item
                break
    return OutcomeRef(
        outcome_id=str(outcome.get("outcomeId") or ""),
        label=str(outcome.get("label") or side),
        best_bid=_float_or_none(outcome.get("bestBid")),
        best_ask=_float_or_none(outcome.get("bestAsk")),
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def market_ref(raw: dict[str, Any]) -> MarketRef:
    return MarketRef(
        venue=str(raw.get("sourceExchange") or raw.get("venue") or "").lower(),
        market_id=str(raw.get("marketId") or raw.get("id") or ""),
        title=str(raw.get("title") or ""),
        slug=raw.get("slug"),
        url=raw.get("url"),
        category=raw.get("category"),
        resolution_date=raw.get("resolutionDate"),
        contract_address=raw.get("contractAddress"),
        yes=_outcome_from_market(raw, "yes"),
        no=_outcome_from_market(raw, "no"),
        raw=raw,
    )


def normalize_pair(raw: dict[str, Any], max_resolution_drift_days: int = 14) -> MatchedMarket | None:
    relation = str(raw.get("relation") or "").lower()
    confidence = _float_or_none(raw.get("confidence")) or 0.0
    if relation and relation != "identity":
        return None
    if confidence < 0.9:
        return None

    a = market_ref(raw.get("marketA") or {})
    b = market_ref(raw.get("marketB") or {})
    venues = {a.venue, b.venue}
    if venues != {"polymarket", "kalshi"}:
        return None

    poly, kalshi = (a, b) if a.venue == "polymarket" else (b, a)
    if not _is_binary_candidate(poly) or not _is_binary_candidate(kalshi):
        return None
    if not poly.contract_address or not poly.yes.outcome_id or not poly.no.outcome_id:
        return None
    if not (kalshi.slug or kalshi.yes.outcome_id):
        return None

    warning = _resolution_warning(poly.resolution_date, kalshi.resolution_date, max_resolution_drift_days)
    return MatchedMarket(
        match_id=f"{poly.market_id}::{kalshi.market_id}",
        polymarket=poly,
        kalshi=kalshi,
        relation="identity",
        confidence=confidence,
        price_difference=_float_or_none(raw.get("priceDifference")),
        reasoning=raw.get("reasoning"),
        resolution_date_warning=warning,
    )


def _is_binary_candidate(market: MarketRef) -> bool:
    return bool(market.yes.outcome_id and market.no.outcome_id)


def _resolution_warning(left: str | None, right: str | None, max_days: int) -> str | None:
    if not left or not right:
        return None
    try:
        left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
    except ValueError:
        return "Could not parse one or both resolution dates."
    drift = abs((left_dt - right_dt).days)
    if drift > max_days:
        return f"Resolution dates differ by {drift} days; manually review before trading."
    return None


def dedupe_matches(matches: Iterable[MatchedMarket]) -> list[MatchedMarket]:
    seen: set[str] = set()
    result: list[MatchedMarket] = []
    for match in matches:
        if match.match_id in seen:
            continue
        seen.add(match.match_id)
        result.append(match)
    return result
