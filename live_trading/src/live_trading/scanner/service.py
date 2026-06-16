from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings
from ..control.db import ControlDatabase
from ..control.hub import EventHub
from ..control.llm_matcher import LLMEventMatcher
from ..control.schemas import (
    Candidate,
    MarketSuggestion,
    OutcomeMapping,
    RankingBreakdown,
    ScanJob,
    ScanRequest,
)
from ..models import MatchedMarket
from ..venues.kalshi import KalshiClient
from ..venues.polymarket_us import PolymarketUSClient
from .candidate_generation import generate_event_pairs
from .catalogs import CatalogService, market_from_payload, market_payload
from .historical import HistoricalEvidenceProvider
from .market_state import (
    build_strategy_books,
    classify_event_state,
    evaluate_size_curve,
    event_spec,
)
from .models import EventPair, HistoricalEvidence, SizePoint
from .normalization import token_set
from .ranking import rank_opportunity
from .repository import ScannerRepository


def now() -> datetime:
    return datetime.now(timezone.utc)


class ScannerService:
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
        self.catalogs = CatalogService(settings)
        self.repository = ScannerRepository(db)
        self.history = HistoricalEvidenceProvider(repository_root)
        self.llm = LLMEventMatcher()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._suggestion_lock = asyncio.Lock()

    def start(self, request: ScanRequest) -> ScanJob:
        job = ScanJob(
            id=uuid.uuid4().hex,
            status="queued",
            message="Queued",
            started_at=now(),
        )
        self.repository.put_job(job.id, job.model_dump(mode="json"))
        self._tasks[job.id] = asyncio.create_task(
            self._run(job, request), name=f"market-scan-{job.id}"
        )
        return job

    async def _run(self, job: ScanJob, request: ScanRequest) -> None:
        try:
            await self._update(
                job,
                status="refreshing",
                progress=0.05,
                message=f"Refreshing recent tradable venue catalogs from the last {request.lookback_days} days",
            )
            kalshi, polymarket, errors = await self.catalogs.refresh(
                categories=request.categories or None,
                limit=request.max_markets,
                lookback_days=request.lookback_days,
            )
            self.repository.put_catalog(
                job.id,
                {
                    "id": job.id,
                    "kind": "recent_tradable",
                    "lookback_days": request.lookback_days,
                    "fetched_at": now().isoformat(),
                    "kalshi": [market_payload(row) for row in kalshi],
                    "polymarket_us": [market_payload(row) for row in polymarket],
                    "errors": errors,
                },
            )
            if not kalshi or not polymarket:
                raise RuntimeError("; ".join(errors) or "One or both venue catalogs were empty.")

            await self._update(
                job,
                status="matching",
                progress=0.30,
                message="Generating event-level matches and assigning outcomes",
                errors=errors,
            )
            pairs = generate_event_pairs(kalshi, polymarket)
            if request.query:
                wanted = token_set(request.query)
                pairs = [
                    pair
                    for pair in pairs
                    if wanted
                    & token_set(
                        f"{pair.kalshi.title} {pair.polymarket.title} "
                        + " ".join(
                            f"{match.kalshi.stream_key} {match.polymarket_us.stream_key}"
                            for match in pair.outcome_matches
                        )
                    )
                ]
            pairs = sorted(pairs, key=lambda pair: pair.confidence, reverse=True)[
                : self.settings.max_matches
            ]
            candidates = [self._candidate(pair) for pair in pairs]

            await self._update(
                job,
                status="reviewing",
                progress=0.55,
                message="Reviewing settlement rules and executable L2 profit",
                candidate_count=len(candidates),
                errors=errors,
            )
            for index, (candidate, pair) in enumerate(zip(candidates, pairs)):
                await self._review(candidate)
                try:
                    await self._hydrate_market_quality(candidate, pair)
                except Exception as exc:
                    candidate.warnings.append(f"Executable L2 snapshot unavailable: {exc}")
                    candidate.ranking.exclusion_reasons.append(
                        "Current complete L2 data is unavailable."
                    )
                candidate.status = "needs_review"
                self.repository.put_candidate(
                    candidate.id, candidate.model_dump(mode="json")
                )
                await self.hub.publish(
                    "candidate.updated", candidate.model_dump(mode="json")
                )
                await self._update(
                    job,
                    progress=0.55 + 0.40 * ((index + 1) / max(len(candidates), 1)),
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

    async def suggestions(
        self,
        *,
        query: str,
        limit: int = 8,
        lookback_days: int = 7,
    ) -> list[MarketSuggestion]:
        if len(query.strip()) < 2:
            return []
        catalog = self.repository.latest_recent_catalog(
            max_age_seconds=self.settings.discovery_refresh_seconds
        )
        if catalog is None:
            async with self._suggestion_lock:
                catalog = self.repository.latest_recent_catalog(
                    max_age_seconds=self.settings.discovery_refresh_seconds
                )
                if catalog is None:
                    kalshi, polymarket, errors = await self.catalogs.refresh(
                        categories=None,
                        limit=250,
                        lookback_days=lookback_days,
                        max_pages=1,
                        timeout_seconds=6,
                    )
                    catalog = {
                        "id": f"suggestions-{uuid.uuid4().hex}",
                        "kind": "recent_tradable",
                        "lookback_days": lookback_days,
                        "fetched_at": now().isoformat(),
                        "kalshi": [market_payload(row) for row in kalshi],
                        "polymarket_us": [market_payload(row) for row in polymarket],
                        "errors": errors,
                    }
                    self.repository.put_catalog(catalog["id"], catalog)
        kalshi = [market_from_payload(row) for row in catalog.get("kalshi", [])]
        polymarket = [
            market_from_payload(row) for row in catalog.get("polymarket_us", [])
        ]
        wanted = token_set(query)
        pairs = []
        for pair in generate_event_pairs(kalshi, polymarket):
            haystack = token_set(
                f"{pair.kalshi.title} {pair.polymarket.title} "
                f"{pair.kalshi.category or ''} {pair.polymarket.category or ''} "
                + " ".join(
                    f"{match.kalshi.stream_key} {match.polymarket_us.stream_key} "
                    f"{match.kalshi.yes_label} {match.polymarket_us.yes_label}"
                    for match in pair.outcome_matches
                )
            )
            if wanted & haystack:
                pairs.append(pair)
        pairs.sort(key=lambda pair: pair.confidence, reverse=True)
        return [_suggestion(pair) for pair in pairs[:limit]]

    def _candidate(self, pair: EventPair) -> Candidate:
        mappings = [_mapping(match) for match in pair.outcome_matches]
        unique_kalshi = len({row.kalshi_ticker for row in mappings}) == len(mappings)
        unique_poly = len(
            {(row.polymarket_us_slug, row.polymarket_side) for row in mappings}
        ) == len(mappings)
        complete_kalshi = len(mappings) == len(pair.kalshi.markets)
        complete_poly = len(mappings) == len(pair.polymarket.markets)
        exhaustive = (
            len(mappings) >= 2
            and unique_kalshi
            and unique_poly
            and complete_kalshi
            and complete_poly
        )
        warnings = list(pair.warnings)
        if not complete_kalshi:
            warnings.append(
                f"Matched {len(mappings)} of {len(pair.kalshi.markets)} Kalshi outcomes."
            )
        if not complete_poly:
            warnings.append(
                f"Matched {len(mappings)} of {len(pair.polymarket.markets)} Polymarket US outcomes."
            )
        candidate_id = hashlib.sha1(
            f"{pair.kalshi.key}|{pair.polymarket.key}".encode()
        ).hexdigest()[:16]
        return Candidate(
            id=candidate_id,
            name=pair.kalshi.title or pair.polymarket.title,
            description=pair.kalshi.markets[0].description
            or pair.polymarket.markets[0].description,
            category=pair.kalshi.category or pair.polymarket.category,
            mappings=mappings,
            exhaustive=exhaustive,
            deterministic_checks={
                "event_pair_plausible": float(pair.confidence) >= 0.34,
                "at_least_two_outcomes": len(mappings) >= 2,
                "unique_kalshi_contracts": unique_kalshi,
                "unique_polymarket_contracts": unique_poly,
                "all_kalshi_event_contracts_mapped": complete_kalshi,
                "all_polymarket_event_contracts_mapped": complete_poly,
                "no_known_rule_conflicts": not any(
                    "rule mismatch" in warning.casefold()
                    or "date conflict" in warning.casefold()
                    for warning in warnings
                ),
            },
            warnings=list(dict.fromkeys(warnings)),
            ranking=RankingBreakdown(mapping_confidence=float(pair.confidence)),
            close_time=pair.kalshi.close_time or pair.polymarket.close_time,
            updated_at=now(),
        )

    async def _review(self, candidate: Candidate) -> None:
        if not self.llm.available:
            candidate.llm_status = "unavailable"
            candidate.warnings.append("OpenAI matching is unavailable; approval is blocked.")
            return
        try:
            review = await self.llm.review(candidate.model_dump(mode="json"))
            candidate.llm_status = "passed" if review.equivalent_event else "failed"
            candidate.llm_confidence = review.confidence
            candidate.llm_reasoning = review.reasoning
            candidate.warnings.extend(review.warnings)
            if not review.exhaustive_outcomes:
                candidate.exhaustive = False
            candidate.ranking.mapping_confidence = review.confidence
        except Exception as exc:
            candidate.llm_status = "failed"
            candidate.warnings.append(f"LLM review failed: {exc}")

    async def _hydrate_market_quality(
        self, candidate: Candidate, pair: EventPair
    ) -> None:
        event = event_spec(candidate.name, candidate.mappings)
        kalshi = KalshiClient(self.settings)
        polymarket = PolymarketUSClient(self.settings)
        requests = []
        seen_requests: set[tuple[str, str]] = set()
        for mapping in candidate.mappings:
            kalshi_key = ("kalshi", mapping.kalshi_ticker)
            if kalshi_key not in seen_requests:
                seen_requests.add(kalshi_key)
                requests.append(kalshi.fetch_book(mapping.kalshi_ticker))
            polymarket_key = ("polymarket_us", mapping.polymarket_us_slug)
            if polymarket_key not in seen_requests:
                seen_requests.add(polymarket_key)
                requests.append(polymarket.fetch_book(mapping.polymarket_us_slug))
        snapshots = await asyncio.gather(*requests, return_exceptions=True)
        failures = [str(row) for row in snapshots if isinstance(row, Exception)]
        if failures:
            raise RuntimeError("; ".join(failures[:3]))
        books = await build_strategy_books(event, list(snapshots))
        points = evaluate_size_curve(
            event,
            books,
            self.settings,
            maximum_size=max(250, int(self.settings.trade_size)),
        )
        state = classify_event_state(
            pair.kalshi.start_time or pair.polymarket.start_time,
            pair.kalshi.close_time or pair.polymarket.close_time,
        )
        history = self.history.for_event(
            candidate.name,
            candidate.category,
            state,
            pair.kalshi.market_type or pair.polymarket.market_type,
        )
        freshness = _freshness(points, self.settings)
        ranking = rank_opportunity(
            points,
            mapping_confidence=candidate.ranking.mapping_confidence,
            freshness_score=freshness,
            outcome_count=len(candidate.mappings),
            event_state=state,
            history=history,
        )
        _apply_ranking(candidate.ranking, points, ranking, history, freshness, state)

    async def _update(self, job: ScanJob, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        payload = job.model_dump(mode="json")
        self.repository.put_job(job.id, payload)
        await self.hub.publish("scan.updated", payload)


def _mapping(match: MatchedMarket) -> OutcomeMapping:
    name = _outcome_name(match)
    return OutcomeMapping(
        name=name,
        kalshi_ticker=match.kalshi.stream_key,
        polymarket_us_slug=match.polymarket_us.stream_key,
        polymarket_side=str(
            match.polymarket_us.raw.get("outcome_side") or "long"
        ),
        kalshi_title=match.kalshi.title,
        polymarket_title=match.polymarket_us.title,
        kalshi_rules=match.kalshi.rules,
        polymarket_rules=match.polymarket_us.rules,
    )


def _outcome_name(match: MatchedMarket) -> str:
    for value in (
        match.kalshi.yes_label,
        match.polymarket_us.yes_label,
        match.kalshi.raw.get("yes_sub_title"),
    ):
        text = str(value or "").strip()
        if text and text.casefold() not in {"yes", "true"}:
            return text
    return match.kalshi.title


def _suggestion(pair: EventPair) -> MarketSuggestion:
    candidate_id = hashlib.sha1(
        f"{pair.kalshi.key}|{pair.polymarket.key}".encode()
    ).hexdigest()[:16]
    return MarketSuggestion(
        id=candidate_id,
        name=pair.kalshi.title or pair.polymarket.title,
        category=pair.kalshi.category or pair.polymarket.category,
        close_time=pair.kalshi.close_time or pair.polymarket.close_time,
        outcome_count=len(pair.outcome_matches),
        mapping_confidence=float(pair.confidence),
        kalshi_outcomes=[match.kalshi.yes_label for match in pair.outcome_matches],
        polymarket_outcomes=[
            f"{match.polymarket_us.yes_label} ({match.polymarket_us.raw.get('outcome_side') or 'long'})"
            for match in pair.outcome_matches
        ],
        warnings=list(pair.warnings),
    )


def _freshness(points: list[SizePoint], settings: Settings) -> float:
    if not points:
        return 0
    valid = sum(point.fresh for point in points)
    return valid / len(points)


def _apply_ranking(
    target: RankingBreakdown,
    points: list[SizePoint],
    ranking,
    history: HistoricalEvidence,
    freshness: float,
    state: str,
) -> None:
    selected = ranking.selected
    target.historical_suitability = history.suitability
    target.annual_profit_percentile = history.annual_percentile
    target.pmxt_profit_percentile = history.pmxt_percentile
    target.evidence_label = history.label
    target.historical_multiplier = history.multiplier
    target.historical_evidence_quality = history.quality
    target.historical_sample_size = history.sample_size
    target.event_state = state
    target.freshness_score = freshness
    target.completion_probability = ranking.completion_probability
    target.expected_deployable_profit = ranking.expected_deployable_profit
    target.exclusion_reasons = list(ranking.exclusion_reasons)
    target.ranking_components = ranking.components
    target.size_curve = [
        {
            "requested_size": float(point.requested_size),
            "achievable_size": float(point.achievable_size),
            "net_edge_per_share": float(point.net_edge_per_share),
            "executable_profit": float(point.executable_profit),
            "max_slippage_per_share": float(point.max_slippage_per_share),
            "eligible": bool(
                point.executable_profit > 0
                and point.fresh
                and point.complete_books
                and point.price_bounds_ok
            ),
        }
        for point in points
    ]
    if selected is None:
        target.total_score = 0
        return
    target.executable_net_edge = float(selected.net_edge_per_share)
    target.fillable_depth = float(selected.achievable_size)
    target.selected_size = float(selected.achievable_size)
    target.executable_profit = float(selected.executable_profit)
    target.max_slippage_per_share = float(selected.max_slippage_per_share)
    target.total_score = ranking.expected_deployable_profit
