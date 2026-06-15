from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config import Settings
from ..matching import MatchConfig, match_markets, normalize_text, tokens
from ..models import MatchedMarket, VenueMarket
from ..strategy.books import BookStore
from ..strategy.bridge import StrategyBookBridge
from ..strategy.detector import Detector
from ..strategy.fees import FeeConfig
from ..strategy.models import EventSpec, OutcomeSpec
from ..venues.kalshi import KalshiClient
from ..venues.polymarket_us import PolymarketUSClient
from .db import ControlDatabase
from .history import HistoricalPriorProvider
from .hub import EventHub
from .llm_matcher import LLMEventMatcher
from .schemas import Candidate, OutcomeMapping, RankingBreakdown, ScanJob, ScanRequest


def now() -> datetime:
    return datetime.now(timezone.utc)


class MarketScanner:
    def __init__(
        self,
        db: ControlDatabase,
        hub: EventHub,
        settings: Settings,
        repository_root: Path,
    ) -> None:
        self.db = db
        self.hub = hub
        self.settings = settings
        self.history = HistoricalPriorProvider(repository_root)
        self.llm = LLMEventMatcher()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, request: ScanRequest) -> ScanJob:
        job = ScanJob(
            id=uuid.uuid4().hex,
            status="queued",
            message="Queued",
            started_at=now(),
        )
        self.db.put("scan_jobs", job.id, job.model_dump(mode="json"))
        self._tasks[job.id] = asyncio.create_task(
            self._run(job, request), name=f"market-scan-{job.id}"
        )
        return job

    async def _run(self, job: ScanJob, request: ScanRequest) -> None:
        try:
            await self._update(job, status="refreshing", progress=0.05, message="Refreshing venue catalogs")
            categories = request.categories or None
            kalshi_task = KalshiClient(self.settings).list_active_markets(
                categories=categories,
                limit=request.max_markets,
                timeout_seconds=20,
            )
            poly_task = PolymarketUSClient(self.settings).list_active_markets(
                categories=categories,
                limit=request.max_markets,
                timeout_seconds=20,
            )
            results = await asyncio.gather(kalshi_task, poly_task, return_exceptions=True)
            errors: list[str] = []
            kalshi = results[0] if isinstance(results[0], list) else []
            polymarket = results[1] if isinstance(results[1], list) else []
            if isinstance(results[0], Exception):
                errors.append(f"Kalshi catalog: {results[0]}")
            if isinstance(results[1], Exception):
                errors.append(f"Polymarket US catalog: {results[1]}")
            snapshot = {
                "id": job.id,
                "fetched_at": now().isoformat(),
                "kalshi": [_market_payload(row) for row in kalshi],
                "polymarket_us": [_market_payload(row) for row in polymarket],
                "errors": errors,
            }
            self.db.put("catalog_snapshots", job.id, snapshot)
            if not kalshi or not polymarket:
                raise RuntimeError("; ".join(errors) or "One or both venue catalogs were empty.")

            await self._update(job, status="matching", progress=0.35, message="Matching contracts into events", errors=errors)
            matches = match_markets(
                kalshi,
                polymarket,
                MatchConfig(min_confidence=self.settings.min_match_confidence),
            )
            if request.query:
                query_tokens = tokens(request.query)
                matches = [
                    row
                    for row in matches
                    if query_tokens
                    & tokens(
                        f"{row.kalshi.title} {row.polymarket_us.title} "
                        f"{row.kalshi.ticker or ''} {row.polymarket_us.slug or ''}"
                    )
                ]
            candidates = self._assemble(matches, kalshi)

            await self._update(
                job,
                status="reviewing",
                progress=0.6,
                message="Running settlement and outcome review",
                candidate_count=len(candidates),
                errors=errors,
            )
            for index, candidate in enumerate(candidates):
                try:
                    await self._hydrate_live_quality(candidate)
                except Exception as exc:
                    candidate.warnings.append(f"Executable L2 snapshot unavailable: {exc}")
                if self.llm.available:
                    try:
                        review = await self.llm.review(candidate.model_dump(mode="json"))
                        candidate.llm_status = "passed" if review.equivalent_event else "failed"
                        candidate.llm_confidence = review.confidence
                        candidate.llm_reasoning = review.reasoning
                        candidate.warnings.extend(review.warnings)
                        if not review.exhaustive_outcomes:
                            candidate.exhaustive = False
                    except Exception as exc:
                        candidate.llm_status = "failed"
                        candidate.warnings.append(f"LLM review failed: {exc}")
                else:
                    candidate.llm_status = "unavailable"
                    candidate.warnings.append("OpenAI matching is unavailable; approval is blocked.")
                candidate.status = "needs_review"
                candidate.ranking.mapping_confidence = candidate.llm_confidence or candidate.ranking.mapping_confidence
                candidate.ranking.total_score = _total_score(candidate.ranking)
                self.db.put("candidates", candidate.id, candidate.model_dump(mode="json"))
                await self.hub.publish("candidate.updated", candidate.model_dump(mode="json"))
                await self._update(
                    job,
                    progress=0.6 + 0.35 * ((index + 1) / max(len(candidates), 1)),
                    candidate_count=len(candidates),
                )
            await self._update(
                job,
                status="complete",
                progress=1,
                message="Scan complete",
                candidate_count=len(candidates),
                errors=errors,
                completed_at=now(),
            )
        except Exception as exc:
            await self._update(
                job,
                status="failed",
                progress=1,
                message=str(exc),
                errors=[*job.errors, str(exc)],
                completed_at=now(),
            )

    def _assemble(
        self,
        matches: list[MatchedMarket],
        kalshi_catalog: list[VenueMarket] | None = None,
    ) -> list[Candidate]:
        grouped: dict[str, list[MatchedMarket]] = defaultdict(list)
        for match in matches:
            grouped[_group_key(match)].append(match)
        expected_by_event: dict[str, int] = defaultdict(int)
        for market in kalshi_catalog or []:
            event_key = _kalshi_event_key(market)
            if event_key:
                expected_by_event[event_key] += 1
        candidates = []
        for group in grouped.values():
            mappings = []
            seen = set()
            warnings = []
            for match in sorted(group, key=lambda row: row.confidence, reverse=True):
                outcome_name = _outcome_name(match)
                if outcome_name.lower() in seen:
                    continue
                seen.add(outcome_name.lower())
                mappings.append(
                    OutcomeMapping(
                        name=outcome_name,
                        kalshi_ticker=match.kalshi.stream_key,
                        polymarket_us_slug=match.polymarket_us.stream_key,
                        kalshi_title=match.kalshi.title,
                        polymarket_title=match.polymarket_us.title,
                        kalshi_rules=match.kalshi.rules,
                        polymarket_rules=match.polymarket_us.rules,
                    )
                )
                warnings.extend(match.warnings)
            primary = group[0]
            unique_kalshi = len({row.kalshi_ticker for row in mappings}) == len(mappings)
            unique_poly = len({row.polymarket_us_slug for row in mappings}) == len(mappings)
            event_key = _kalshi_event_key(primary.kalshi)
            expected_outcomes = expected_by_event.get(event_key or "", len(mappings))
            all_kalshi_outcomes_mapped = len(mappings) == expected_outcomes
            exhaustive = (
                len(mappings) >= 2
                and unique_kalshi
                and unique_poly
                and all_kalshi_outcomes_mapped
            )
            if not all_kalshi_outcomes_mapped:
                warnings.append(
                    f"Matched {len(mappings)} of {expected_outcomes} active Kalshi outcomes."
                )
            historical = self.history.for_event(
                primary.kalshi.title,
                primary.kalshi.category or primary.polymarket_us.category,
            )
            confidence = sum(float(row.confidence) for row in group) / len(group)
            ranking = RankingBreakdown(
                historical_suitability=historical["historical_suitability"],
                annual_profit_percentile=historical["annual_profit_percentile"],
                pmxt_profit_percentile=historical["pmxt_profit_percentile"],
                mapping_confidence=confidence,
                evidence_label=historical["evidence_label"],
            )
            ranking.total_score = _total_score(ranking)
            candidate_id = hashlib.sha1(
                "|".join(sorted(f"{row.kalshi.market_id}:{row.polymarket_us.market_id}" for row in group)).encode()
            ).hexdigest()[:16]
            candidates.append(
                Candidate(
                    id=candidate_id,
                    name=_event_name(primary),
                    description=primary.kalshi.description or primary.polymarket_us.description,
                    category=primary.kalshi.category or primary.polymarket_us.category,
                    mappings=mappings,
                    exhaustive=exhaustive,
                    deterministic_checks={
                        "at_least_two_outcomes": len(mappings) >= 2,
                        "unique_kalshi_contracts": unique_kalshi,
                        "unique_polymarket_contracts": unique_poly,
                        "all_kalshi_event_contracts_mapped": all_kalshi_outcomes_mapped,
                        "no_known_rule_conflicts": not warnings,
                    },
                    warnings=list(dict.fromkeys(warnings)),
                    ranking=ranking,
                    close_time=primary.kalshi.close_time or primary.polymarket_us.close_time,
                    updated_at=now(),
                )
            )
        return sorted(candidates, key=lambda row: row.ranking.total_score, reverse=True)

    async def _hydrate_live_quality(self, candidate: Candidate) -> None:
        event = EventSpec(
            name=candidate.name,
            description=candidate.description,
            outcomes=tuple(
                OutcomeSpec(
                    name=mapping.name,
                    kalshi_ticker=mapping.kalshi_ticker,
                    polymarket_slug=mapping.polymarket_us_slug,
                )
                for mapping in candidate.mappings
            ),
        )
        kalshi = KalshiClient(self.settings)
        polymarket = PolymarketUSClient(self.settings)
        requests = []
        for mapping in candidate.mappings:
            requests.extend(
                (
                    kalshi.fetch_book(mapping.kalshi_ticker),
                    polymarket.fetch_book(mapping.polymarket_us_slug),
                )
            )
        snapshots = await asyncio.gather(*requests, return_exceptions=True)
        failures = [str(row) for row in snapshots if isinstance(row, Exception)]
        if failures:
            raise RuntimeError("; ".join(failures[:3]))
        store = BookStore()
        bridge = StrategyBookBridge(event, store)
        for snapshot in snapshots:
            await bridge.apply(snapshot)
        detector = Detector(
            event=event,
            target_size=Decimal(str(self.settings.trade_size)),
            fee_cfg=FeeConfig.default(),
            staleness_ms=float(self.settings.stale_after_seconds * Decimal("1000")),
        )
        evaluation = detector.evaluate(await store.snapshot())
        candidate.ranking.executable_net_edge = float(evaluation.edge_per_share)
        candidate.ranking.fillable_depth = float(evaluation.achievable_size)
        stale_limit = float(self.settings.stale_after_seconds * Decimal("1000"))
        candidate.ranking.freshness_score = max(
            0.0,
            min(1.0, 1.0 - evaluation.max_book_age_ms / max(stale_limit, 1)),
        )
        candidate.ranking.total_score = _total_score(candidate.ranking)

    async def _update(self, job: ScanJob, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        payload = job.model_dump(mode="json")
        self.db.put("scan_jobs", job.id, payload)
        await self.hub.publish("scan.updated", payload)


def _market_payload(market: VenueMarket) -> dict[str, Any]:
    return {
        "venue": market.venue,
        "market_id": market.market_id,
        "ticker": market.ticker,
        "slug": market.slug,
        "title": market.title,
        "category": market.category,
        "market_type": market.market_type,
        "start_time": market.start_time.isoformat() if market.start_time else None,
        "close_time": market.close_time.isoformat() if market.close_time else None,
        "expiration_time": market.expiration_time.isoformat() if market.expiration_time else None,
        "yes_label": market.yes_label,
        "no_label": market.no_label,
        "description": market.description,
        "rules": market.rules,
    }


def _group_key(match: MatchedMarket) -> str:
    raw = match.kalshi.raw
    explicit = raw.get("event_ticker") or raw.get("series_ticker") or raw.get("event_id")
    if explicit:
        return f"explicit:{explicit}"
    title = normalize_text(match.kalshi.description or match.kalshi.title)
    title = re.sub(r"\b(yes|no|will|win|winner)\b", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    day = (match.kalshi.close_time or match.polymarket_us.close_time)
    return f"{match.kalshi.category}:{day.date().isoformat() if day else 'none'}:{' '.join(sorted(tokens(title))[:8])}"


def _kalshi_event_key(market: VenueMarket) -> str | None:
    raw = market.raw
    value = raw.get("event_ticker") or raw.get("series_ticker") or raw.get("event_id")
    return str(value) if value else None


def _outcome_name(match: MatchedMarket) -> str:
    for value in (
        match.kalshi.yes_label,
        match.polymarket_us.yes_label,
        match.kalshi.raw.get("yes_sub_title"),
    ):
        text = str(value or "").strip()
        if text and text.lower() not in {"yes", "true"}:
            return text
    return match.kalshi.title


def _event_name(match: MatchedMarket) -> str:
    raw = match.kalshi.raw
    return str(raw.get("event_title") or raw.get("series_title") or match.kalshi.description or match.kalshi.title)


def _total_score(row: RankingBreakdown) -> float:
    edge = max(0.0, min(1.0, (row.executable_net_edge or 0) / 0.1))
    depth = max(0.0, min(1.0, (row.fillable_depth or 0) / 500))
    quality = 0.6 * row.mapping_confidence + 0.2 * row.freshness_score + 0.2 * row.stability_score
    return round(
        100 * (0.5 * edge + 0.2 * (row.historical_suitability / 100) + 0.15 * depth + 0.15 * quality),
        2,
    )
