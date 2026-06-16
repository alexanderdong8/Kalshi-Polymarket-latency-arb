from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from ..config import Settings
from ..control.db import ControlDatabase
from ..control.hub import EventHub
from ..control.llm_matcher import LLMEventMatcher
from ..control.schemas import (
    BasketEntry,
    Candidate,
    MarketSuggestion,
    OutcomeMapping,
    RankingBreakdown,
    ScanJob,
    ScanRequest,
)
from ..models import MatchedMarket, VenueMarket
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
from .oddpool import OddpoolClient, OddpoolRateLimitError
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
        self.oddpool = OddpoolClient(settings)
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

    def recover_abandoned_jobs(self) -> None:
        active = {"queued", "refreshing", "matching", "reviewing"}
        for payload in self.db.list("scan_jobs"):
            if payload.get("status") not in active:
                continue
            job = ScanJob.model_validate(payload)
            job.status = "failed"
            job.progress = 1
            job.message = (
                "Scan worker was interrupted by an application restart. "
                "Start a new scan if you still want a broad market scan."
            )
            job.errors = [*job.errors, "Scan worker was interrupted by restart."]
            job.completed_at = now()
            self.repository.put_job(job.id, job.model_dump(mode="json"))

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
                missing = []
                if not kalshi:
                    missing.append("Kalshi")
                if not polymarket:
                    missing.append("Polymarket US")
                await self._update(
                    job,
                    status="complete",
                    progress=1,
                    message=(
                        "No review-ready matches found because "
                        + " and ".join(missing)
                        + " returned no recent tradable catalog rows."
                    ),
                    candidate_count=0,
                    errors=errors,
                    completed_at=now(),
                )
                return

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
        if self.oddpool.available:
            try:
                suggestions = await self.oddpool.search_events(query, limit=limit)
                if suggestions:
                    return suggestions
            except Exception:
                pass
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

    async def prepare_basket_entry(self, entry: BasketEntry) -> BasketEntry:
        entry.status = "preparing"
        entry.status_reason = "Resolving selected event markets."
        entry.updated_at = now()
        self.db.put("basket_entries", entry.id, entry.model_dump(mode="json"))
        await self.hub.publish("basket.updated", entry.model_dump(mode="json"))
        try:
            candidate = await (
                self._prepare_oddpool_entry(entry)
                if entry.source == "oddpool"
                else self._prepare_native_entry(entry)
            )
            if candidate is None:
                if entry.status == "preparing":
                    entry.status = "no_tradable_match_found"
                    entry.status_reason = "No complete Kalshi/Polymarket event match was found."
                entry.candidate_id = None
            else:
                entry.candidate_id = candidate.id
                entry.last_reviewed_at = now()
                if candidate.llm_status != "passed":
                    entry.status = "llm_review_failed"
                    entry.status_reason = (
                        candidate.warnings[-1]
                        if candidate.warnings
                        else f"LLM settlement review status is {candidate.llm_status}."
                    )
                else:
                    entry.status = "review_ready"
                    entry.status_reason = "Complete matched event is ready for user review."
            entry.updated_at = now()
            self.db.put("basket_entries", entry.id, entry.model_dump(mode="json"))
            await self.hub.publish("basket.updated", entry.model_dump(mode="json"))
            return entry
        except OddpoolRateLimitError as exc:
            return await self._block_basket_entry(entry, "rate_limited", str(exc))
        except Exception as exc:
            return await self._block_basket_entry(entry, "failed", str(exc))

    async def _prepare_oddpool_entry(self, entry: BasketEntry) -> Candidate | None:
        markets = await self._direct_markets_for_entry(entry)
        if not markets and not entry.provider_event_ids and self.oddpool.available:
            rows = await self._oddpool_rows_for_entry(entry)
            markets = [_oddpool_market(row) for row in rows if _supported_exchange(row)]
        kalshi = [row for row in markets if row.venue == "kalshi"]
        polymarket = [row for row in markets if row.venue == "polymarket_us"]
        if not kalshi or not polymarket:
            await self._block_basket_entry(
                entry,
                "needs_opposite_venue",
                "Selected event did not resolve to both Kalshi and Polymarket markets.",
            )
            return None
        kalshi, polymarket, timing_warning = _relax_targeted_event_times(
            kalshi, polymarket
        )
        pairs = sorted(
            generate_event_pairs(kalshi, polymarket),
            key=lambda pair: pair.confidence,
            reverse=True,
        )
        if not pairs:
            return None
        pair = pairs[0]
        candidate = self._candidate(pair)
        if timing_warning:
            candidate.warnings.append(timing_warning)
        if any(
            market.raw.get("venue_source") == "polymarket_international_gamma"
            for market in polymarket
        ):
            candidate.warnings.append(
                "This matched Polymarket international Gamma data, not Polymarket US. "
                "Live Polymarket US trading requires a corresponding Polymarket US market."
            )
        if not candidate.exhaustive:
            await self._block_basket_entry(
                entry,
                "incomplete_outcomes",
                "; ".join(candidate.warnings)
                or "Outcome matching did not cover every market on both venues.",
            )
            return None
        await self._review(candidate)
        try:
            await self._hydrate_market_quality(candidate, pair)
        except Exception as exc:
            candidate.warnings.append(f"Executable L2 snapshot unavailable: {exc}")
            candidate.ranking.exclusion_reasons.append("Current complete L2 data is unavailable.")
        candidate.status = "needs_review"
        self.repository.put_candidate(candidate.id, candidate.model_dump(mode="json"))
        await self.hub.publish("candidate.updated", candidate.model_dump(mode="json"))
        return candidate

    async def _direct_markets_for_entry(self, entry: BasketEntry) -> list[VenueMarket]:
        requests = []
        kalshi_id = entry.provider_event_ids.get("kalshi")
        if kalshi_id:
            requests.append(KalshiClient(self.settings).fetch_event_markets(kalshi_id))
        poly_us_id = (
            entry.provider_event_ids.get("polymarket_us")
            or entry.provider_event_ids.get("polymarket-us")
        )
        if poly_us_id:
            requests.append(
                PolymarketUSClient(self.settings).fetch_event_markets(
                    poly_us_id,
                    title=entry.name,
                )
            )
        poly_id = entry.provider_event_ids.get("polymarket")
        if poly_id:
            requests.append(_fetch_polymarket_gamma_event_markets(poly_id))
        if not requests:
            return []
        results = await asyncio.gather(*requests, return_exceptions=True)
        markets: list[VenueMarket] = []
        errors = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
                continue
            markets.extend(result)
        if errors:
            entry.warnings.extend(f"Direct venue fetch warning: {error}" for error in errors)
        return markets

    async def _prepare_native_entry(self, entry: BasketEntry) -> Candidate | None:
        payload = self.db.get("candidates", entry.suggestion_id) or self.db.get(
            "candidates", entry.id
        )
        if payload:
            return Candidate.model_validate(payload)
        catalog = self.repository.latest_recent_catalog(
            max_age_seconds=self.settings.discovery_refresh_seconds
        )
        if catalog is None:
            await self._block_basket_entry(
                entry,
                "no_tradable_match_found",
                "Native suggestion catalog expired. Search again or use Oddpool-backed results.",
            )
            return None
        pairs = generate_event_pairs(
            [market_from_payload(row) for row in catalog.get("kalshi", [])],
            [market_from_payload(row) for row in catalog.get("polymarket_us", [])],
        )
        for pair in pairs:
            candidate = self._candidate(pair)
            if candidate.id != entry.suggestion_id:
                continue
            if not candidate.exhaustive:
                await self._block_basket_entry(
                    entry,
                    "incomplete_outcomes",
                    "; ".join(candidate.warnings)
                    or "Outcome matching did not cover every market on both venues.",
                )
                return None
            await self._review(candidate)
            try:
                await self._hydrate_market_quality(candidate, pair)
            except Exception as exc:
                candidate.warnings.append(f"Executable L2 snapshot unavailable: {exc}")
            candidate.status = "needs_review"
            self.repository.put_candidate(candidate.id, candidate.model_dump(mode="json"))
            await self.hub.publish("candidate.updated", candidate.model_dump(mode="json"))
            return candidate
        return None

    async def _oddpool_rows_for_entry(self, entry: BasketEntry) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event_id in dict.fromkeys(entry.provider_event_ids.values()):
            rows.extend(await self.oddpool.event_markets(event_id))
        found = {_oddpool_exchange(row) for row in rows}
        missing = {"kalshi", "polymarket"} - found
        for exchange in missing:
            series_id = entry.provider_series_ids.get(exchange)
            rows.extend(
                await self.oddpool.search_markets(
                    query=None if series_id else entry.name,
                    exchange=exchange,
                    series_id=series_id,
                    limit=100,
                )
            )
        if {"kalshi", "polymarket"} <= {_oddpool_exchange(row) for row in rows}:
            return rows
        for exchange in missing:
            rows.extend(
                await self.oddpool.search_markets(
                    query=entry.name,
                    exchange=exchange,
                    limit=100,
                )
            )
        return _narrow_oddpool_rows(rows, entry.name)

    async def _block_basket_entry(
        self,
        entry: BasketEntry,
        status: str,
        reason: str,
    ) -> BasketEntry:
        entry.status = status  # type: ignore[assignment]
        entry.status_reason = reason
        entry.last_reviewed_at = now()
        entry.updated_at = now()
        self.db.put("basket_entries", entry.id, entry.model_dump(mode="json"))
        await self.hub.publish("basket.updated", entry.model_dump(mode="json"))
        return entry

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
        source="native",
        venues=["kalshi", "polymarket_us"],
    )


def _supported_exchange(row: dict[str, Any]) -> bool:
    return _oddpool_exchange(row) in {"kalshi", "polymarket"}


def _oddpool_exchange(row: dict[str, Any]) -> str:
    return str(row.get("exchange") or row.get("venue") or "").casefold()


def _oddpool_market(row: dict[str, Any]) -> VenueMarket:
    exchange = _oddpool_exchange(row)
    venue = "kalshi" if exchange == "kalshi" else "polymarket_us"
    event_id = str(row.get("event_id") or row.get("eventId") or "")
    event_title = str(
        row.get("event_title")
        or row.get("title")
        or row.get("event_name")
        or row.get("question")
        or event_id
    )
    market_id = str(row.get("market_id") or row.get("id") or row.get("slug") or event_title)
    question = str(row.get("question") or row.get("title") or event_title)
    yes_label = _oddpool_outcome_label(row)
    return VenueMarket(
        venue=venue,  # type: ignore[arg-type]
        market_id=market_id,
        ticker=market_id if venue == "kalshi" else None,
        slug=str(row.get("slug") or market_id) if venue == "polymarket_us" else None,
        title=event_title,
        category=row.get("category"),
        market_type=str(row.get("market_type") or row.get("sports_market_type") or "binary"),
        start_time=_parse_oddpool_time(
            row.get("start_time") or row.get("game_start_time") or row.get("starts_at")
        ),
        close_time=_parse_oddpool_time(
            row.get("close_time") or row.get("end_time") or row.get("expiration_time")
        ),
        expiration_time=_parse_oddpool_time(
            row.get("expiration_time") or row.get("end_time") or row.get("close_time")
        ),
        yes_label=yes_label,
        no_label=str(row.get("no_label") or "No"),
        description=question,
        rules=str(row.get("rules") or row.get("settlement_rules") or question),
        raw={
            **row,
            "event_id": event_id,
            "event_title": event_title,
            "outcome_side": row.get("outcome_side") or "long",
        },
    )


def _oddpool_outcome_label(row: dict[str, Any]) -> str:
    for key in (
        "outcome",
        "outcome_name",
        "outcome_title",
        "yes_label",
        "subtitle",
        "short_title",
    ):
        value = row.get(key)
        if value:
            return str(value)
    question = str(row.get("question") or "")
    event_title = str(row.get("event_title") or "")
    if event_title and question.casefold().startswith(event_title.casefold()):
        question = question[len(event_title) :].strip(" :-")
    return question or event_title or str(row.get("market_id") or "Yes")


def _relax_targeted_event_times(
    kalshi: list[VenueMarket],
    polymarket: list[VenueMarket],
) -> tuple[list[VenueMarket], list[VenueMarket], str | None]:
    if not kalshi or not polymarket:
        return kalshi, polymarket, None
    kalshi_time = kalshi[0].start_time or kalshi[0].close_time
    poly_time = polymarket[0].start_time or polymarket[0].close_time
    if not kalshi_time or not poly_time:
        return kalshi, polymarket, None
    drift_days = abs((kalshi_time - poly_time).total_seconds()) / 86400
    if drift_days <= 2:
        return kalshi, polymarket, None
    warning = (
        f"Venue timestamps differ by {drift_days:.1f} days. "
        "The event was selected from exact provider identifiers, so matching continued, "
        "but settlement timing must be reviewed before approval."
    )
    relaxed_kalshi = [
        replace(row, start_time=None, close_time=None, expiration_time=None)
        for row in kalshi
    ]
    relaxed_poly = [
        replace(row, start_time=None, close_time=None, expiration_time=None)
        for row in polymarket
    ]
    return relaxed_kalshi, relaxed_poly, warning


async def _fetch_polymarket_gamma_event_markets(slug: str) -> list[VenueMarket]:
    slug = slug.strip()
    if not slug:
        return []
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://gamma-api.polymarket.com/events",
            params={"slug": slug, "closed": "false"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status == 404:
                return []
            response.raise_for_status()
            payload = await response.json()
    events = payload if isinstance(payload, list) else payload.get("events") or []
    if not events:
        return []
    event = events[0]
    title = str(event.get("title") or event.get("slug") or slug)
    return [
        _gamma_market(row, event_title=title, event_slug=slug)
        for row in event.get("markets") or []
    ]


def _gamma_market(row: dict[str, Any], *, event_title: str, event_slug: str) -> VenueMarket:
    market_id = str(row.get("id") or row.get("slug") or row.get("conditionId") or "")
    slug = str(row.get("slug") or market_id)
    return VenueMarket(
        venue="polymarket_us",
        market_id=market_id,
        ticker=None,
        slug=slug,
        title=event_title,
        category=row.get("category"),
        market_type="moneyline",
        start_time=_parse_oddpool_time(row.get("gameStartTime") or row.get("startDate")),
        close_time=_parse_oddpool_time(row.get("endDate") or row.get("closeTime")),
        expiration_time=_parse_oddpool_time(row.get("endDate") or row.get("expirationTime")),
        yes_label=_gamma_yes_label(row, event_title),
        no_label="No",
        yes_symbol=_json_value(row.get("clobTokenIds"), 0) or row.get("conditionId"),
        no_symbol=_json_value(row.get("clobTokenIds"), 1),
        description=row.get("description") or row.get("question"),
        rules=row.get("resolutionSource") or row.get("description"),
        active=bool(row.get("active", True)) and not bool(row.get("closed", False)),
        raw={
            **row,
            "event_id": event_slug,
            "event_title": event_title,
            "venue_source": "polymarket_international_gamma",
            "outcome_side": "long",
        },
    )


def _gamma_yes_label(row: dict[str, Any], event_title: str) -> str:
    question = str(row.get("question") or "")
    lowered = question.casefold()
    if " end in a draw" in lowered or " end in draw" in lowered:
        return "Tie"
    match = re.search(r"will\s+(.+?)\s+win\b", question, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    if ":" in question:
        return question.split(":", 1)[-1].strip()
    return question.replace(event_title, "").strip(" ?:-") or question or event_title


def _json_value(value: Any, index: int) -> str | None:
    if isinstance(value, list):
        values = value
    elif not value:
        values = []
    else:
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            values = []
        else:
            values = parsed if isinstance(parsed, list) else []
    return str(values[index]) if len(values) > index else None


def _parse_oddpool_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _narrow_oddpool_rows(rows: list[dict[str, Any]], selected_name: str) -> list[dict[str, Any]]:
    by_exchange_event: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        exchange = _oddpool_exchange(row)
        event_id = str(row.get("event_id") or row.get("id") or "")
        if exchange and event_id:
            by_exchange_event[(exchange, event_id)].append(row)
    selected_tokens = token_set(selected_name)

    def score(group: list[dict[str, Any]]) -> tuple[int, float, int]:
        title = str(group[0].get("event_title") or group[0].get("title") or "")
        overlap = len(selected_tokens & token_set(title))
        liquidity = sum(float(row.get("liquidity") or row.get("total_liquidity") or 0) for row in group)
        return overlap, liquidity, len(group)

    selected: list[dict[str, Any]] = []
    for exchange in ("kalshi", "polymarket"):
        groups = [
            group
            for (group_exchange, _event_id), group in by_exchange_event.items()
            if group_exchange == exchange
        ]
        groups.sort(key=score, reverse=True)
        if groups:
            selected.extend(groups[0])
    return selected or rows


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
