from __future__ import annotations

from dataclasses import dataclass, field

from .models import MatchedMarket, Venue


@dataclass
class PairRegistry:
    matches: dict[str, MatchedMarket] = field(default_factory=dict)
    _by_market: dict[tuple[Venue, str], tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_matches(cls, matches: list[MatchedMarket]) -> "PairRegistry":
        registry = cls()
        registry.replace(matches)
        return registry

    def replace(self, matches: list[MatchedMarket]) -> None:
        by_market: dict[tuple[Venue, str], list[str]] = {}
        self.matches = {match.match_id: match for match in matches}
        for match in matches:
            by_market.setdefault(("kalshi", match.kalshi.stream_key), []).append(match.match_id)
            by_market.setdefault(("polymarket_us", match.polymarket_us.stream_key), []).append(match.match_id)
        self._by_market = {key: tuple(match_ids) for key, match_ids in by_market.items()}

    def for_market(self, venue: Venue, market_key: str) -> tuple[MatchedMarket, ...]:
        return tuple(self.matches[match_id] for match_id in self._by_market.get((venue, market_key), ()))

    def tradable_matches(self) -> list[MatchedMarket]:
        return [match for match in self.matches.values() if match.is_tradeable_candidate]

    def review_matches(self) -> list[MatchedMarket]:
        return [match for match in self.matches.values() if not match.is_tradeable_candidate]

