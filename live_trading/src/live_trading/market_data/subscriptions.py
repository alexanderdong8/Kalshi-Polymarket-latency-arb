from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..models import Venue


MarketKey = tuple[Venue, str]


@dataclass
class SubscriptionRegistry:
    _by_consumer: dict[str, set[MarketKey]] = field(default_factory=dict)
    _counts: Counter[MarketKey] = field(default_factory=Counter)
    revision: int = 0

    def replace(self, consumer_id: str, markets: set[MarketKey]) -> bool:
        previous = self._by_consumer.get(consumer_id, set())
        if previous == markets:
            return False
        for market in previous:
            self._counts[market] -= 1
            if self._counts[market] <= 0:
                del self._counts[market]
        if markets:
            self._by_consumer[consumer_id] = set(markets)
            self._counts.update(markets)
        else:
            self._by_consumer.pop(consumer_id, None)
        self.revision += 1
        return True

    def remove(self, consumer_id: str) -> bool:
        return self.replace(consumer_id, set())

    def active(self, venue: Venue | None = None) -> set[MarketKey]:
        if venue is None:
            return set(self._counts)
        return {market for market in self._counts if market[0] == venue}

    def consumers_for(self, market: MarketKey) -> set[str]:
        return {
            consumer
            for consumer, markets in self._by_consumer.items()
            if market in markets
        }

    def consumer_markets(self, consumer_id: str) -> set[MarketKey]:
        return set(self._by_consumer.get(consumer_id, set()))
