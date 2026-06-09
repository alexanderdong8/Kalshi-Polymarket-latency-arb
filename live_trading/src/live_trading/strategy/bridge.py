from __future__ import annotations

from dataclasses import dataclass

from ..models import BookState
from .books import BookStore
from .models import BookSnapshot, DepthLevel, EventSpec


@dataclass
class StrategyBookBridge:
    event: EventSpec
    store: BookStore

    def __post_init__(self) -> None:
        self._outcome_by_key = {
            ("kalshi", outcome.kalshi_ticker): outcome.name
            for outcome in self.event.outcomes
        }
        self._outcome_by_key.update(
            {
                ("polymarket_us", outcome.polymarket_slug): outcome.name
                for outcome in self.event.outcomes
            }
        )

    async def apply(self, state: BookState) -> BookSnapshot | None:
        outcome_name = self._outcome_by_key.get((state.venue, state.market_key))
        if outcome_name is None:
            return None
        snapshot = BookSnapshot(
            venue=state.venue,
            outcome_name=outcome_name,
            market_key=state.market_key,
            yes_bids=tuple(DepthLevel(level.price, level.size) for level in state.raw_yes_bids),
            yes_asks=tuple(DepthLevel(level.price, level.size) for level in state.raw_yes_asks),
            venue_ts=state.venue_ts,
            received_ts=state.received_ts,
            sequence=state.sequence,
            state=state.state,
        )
        await self.store.set(snapshot)
        return snapshot
