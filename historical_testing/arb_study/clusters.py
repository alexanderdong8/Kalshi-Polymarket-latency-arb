from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import MatchedMarket
from .pmxt_client import PMXTClient, _float_or_none, _resolution_warning, market_ref
from .strict_matching import strict_equivalence_rejection


BAD_PAIR_PATTERNS = (
    ("round of 16", ("round of 32", "knockout stages", "qualify from group")),
    ("round of 32", ("round of 16",)),
    ("qualify from group", ("round of 16",)),
)


def fetch_cluster_universe(
    client: PMXTClient,
    checkpoint_path: str | Path,
    page_limit: int = 250,
    max_clusters: int | None = None,
    resume: bool = True,
) -> list[dict[str, Any]]:
    checkpoint = Path(checkpoint_path)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    pages = _load_checkpoint(checkpoint) if resume else {}
    offset = 0

    while True:
        if max_clusters is not None and offset >= max_clusters:
            break
        if str(offset) not in pages:
            rows = client.fetch_matched_market_clusters(limit=page_limit, offset=offset)
            pages[str(offset)] = rows
            _write_checkpoint(checkpoint, pages)
        rows = pages[str(offset)]
        if len(rows) < page_limit:
            break
        offset += page_limit

    clusters: list[dict[str, Any]] = []
    for key in sorted(pages, key=lambda item: int(item)):
        clusters.extend(pages[key])
    return clusters[:max_clusters] if max_clusters is not None else clusters


def normalize_clusters(
    clusters: list[dict[str, Any]],
    min_confidence: float = 0.9,
    max_resolution_drift_days: int = 45,
) -> tuple[list[MatchedMarket], list[dict[str, Any]]]:
    matches: list[MatchedMarket] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for cluster in clusters:
        cluster_matches = normalize_cluster(
            cluster,
            min_confidence=min_confidence,
            max_resolution_drift_days=max_resolution_drift_days,
        )
        if not cluster_matches:
            rejected.append(
                {
                    "cluster_id": cluster.get("clusterId"),
                    "canonical_title": cluster.get("canonicalTitle"),
                    "reason": "No safe binary Kalshi/Polymarket pair survived semantic checks.",
                }
            )
            continue
        for match in cluster_matches:
            if match.match_id in seen:
                continue
            seen.add(match.match_id)
            matches.append(match)
    return matches, rejected


def normalize_cluster(
    cluster: dict[str, Any],
    min_confidence: float = 0.9,
    max_resolution_drift_days: int = 45,
) -> list[MatchedMarket]:
    confidence = _float_or_none(cluster.get("confidence")) or 0.0
    if confidence < min_confidence:
        return []
    relations = {str(item).lower() for item in cluster.get("relations") or []}
    if relations and "identity" not in relations:
        return []

    markets = cluster.get("markets") or []
    polys = [market_ref(item) for item in markets if item.get("sourceExchange") == "polymarket"]
    kalshis = [market_ref(item) for item in markets if item.get("sourceExchange") == "kalshi"]
    raw_edges = cluster.get("rawMatches") or []
    edge_pairs = {
        tuple(sorted((str(edge.get("marketAId")), str(edge.get("marketBId"))))): edge
        for edge in raw_edges
        if str(edge.get("relation", "")).lower() == "identity"
        and (_float_or_none(edge.get("confidence")) or confidence) >= min_confidence
    }

    candidates: list[tuple[float, MatchedMarket]] = []
    for poly in polys:
        for kalshi in kalshis:
            if not _binary_and_addressable(poly, kalshi):
                continue
            if edge_pairs:
                edge = edge_pairs.get(tuple(sorted((poly.market_id, kalshi.market_id))))
                if not edge:
                    continue
                pair_confidence = _float_or_none(edge.get("confidence")) or confidence
            else:
                pair_confidence = confidence
            rejection = _semantic_rejection(poly.title, poly.raw.get("description"), kalshi.title, kalshi.raw.get("description"))
            if rejection:
                continue

            warning = _resolution_warning(
                poly.resolution_date,
                kalshi.resolution_date,
                max_resolution_drift_days,
            )
            score = _pair_score(cluster.get("canonicalTitle") or "", poly.title, kalshi.title)
            candidates.append(
                (
                    score,
                    MatchedMarket(
                        match_id=f"{poly.market_id}::{kalshi.market_id}",
                        polymarket=poly,
                        kalshi=kalshi,
                        relation="identity",
                        confidence=pair_confidence,
                        price_difference=None,
                        reasoning=f"cluster={cluster.get('clusterId')}",
                        resolution_date_warning=warning,
                    ),
                )
            )

    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return []
    best_score = candidates[0][0]
    if len(candidates) > 1:
        # Keep only clearly best pairs from ambiguous clusters. This preserves cases
        # like World Cup group-vs-round matching while avoiding Round-of-16 leakage.
        return [match for score, match in candidates if score >= best_score - 0.12]
    return [candidates[0][1]]


def _binary_and_addressable(poly, kalshi) -> bool:
    return bool(
        poly.contract_address
        and poly.yes.outcome_id
        and poly.no.outcome_id
        and (kalshi.slug or kalshi.yes.outcome_id)
        and kalshi.yes.outcome_id
        and kalshi.no.outcome_id
    )


def _semantic_rejection(
    poly_title: str,
    poly_description: str | None,
    kalshi_title: str,
    kalshi_description: str | None,
) -> str | None:
    left = _normalized_text(f"{poly_title} {poly_description or ''}")
    right = _normalized_text(f"{kalshi_title} {kalshi_description or ''}")
    for anchor, conflicts in BAD_PAIR_PATTERNS:
        if anchor in left and any(conflict in right for conflict in conflicts):
            return f"semantic mismatch: {anchor}"
        if anchor in right and any(conflict in left for conflict in conflicts):
            return f"semantic mismatch: {anchor}"
    return strict_equivalence_rejection(left, right)


def _pair_score(canonical: str, poly_title: str, kalshi_title: str) -> float:
    canonical_tokens = _tokens(canonical)
    poly_tokens = _tokens(poly_title)
    kalshi_tokens = _tokens(kalshi_title)
    if not poly_tokens or not kalshi_tokens:
        return 0.0
    pair_overlap = len(poly_tokens & kalshi_tokens) / len(poly_tokens | kalshi_tokens)
    canonical_overlap = 0.0
    if canonical_tokens:
        canonical_overlap = (
            len((poly_tokens & canonical_tokens) | (kalshi_tokens & canonical_tokens))
            / len(canonical_tokens)
        )
    return pair_overlap * 0.75 + canonical_overlap * 0.25


def _tokens(value: str) -> set[str]:
    stop = {
        "will",
        "the",
        "a",
        "an",
        "to",
        "in",
        "of",
        "for",
        "from",
        "at",
        "by",
        "on",
        "win",
        "winner",
        "market",
        "yes",
        "no",
        "not",
    }
    return {token for token in re.findall(r"[a-z0-9]+", _normalized_text(value)) if token not in stop}


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("knockout stage", "knockout stages")).strip()


def _load_checkpoint(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("pages", {})


def _write_checkpoint(path: Path, pages: dict[str, list[dict[str, Any]]]) -> None:
    payload = {
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "pages": pages,
        "page_count": len(pages),
        "cluster_count": sum(len(page) for page in pages.values()),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def matches_payload(matches: list[MatchedMarket], rejected: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "matches": [asdict(match) for match in matches],
        "meta": {
            "source": "pmxt_v0_matched_market_clusters",
            "clusters_fetched": len(clusters),
            "valid_pairs": len(matches),
            "rejected_clusters": len(rejected),
        },
        "rejected": rejected,
    }
