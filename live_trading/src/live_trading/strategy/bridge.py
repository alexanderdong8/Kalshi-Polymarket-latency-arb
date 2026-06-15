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
        self._polymarket_outcomes_by_key = {}
        for outcome in self.event.outcomes:
            self._polymarket_outcomes_by_key.setdefault(
                outcome.polymarket_slug, []
            ).append(outcome)

    async def apply(self, state: BookState) -> BookSnapshot | None:
        if state.venue == "polymarket_us":
            outcomes = self._polymarket_outcomes_by_key.get(state.market_key, [])
            snapshots = []
            for outcome in outcomes:
                snapshot = _polymarket_snapshot(state, outcome)
                await self.store.set(snapshot)
                snapshots.append(snapshot)
            return snapshots[0] if snapshots else None
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


def _polymarket_snapshot(state: BookState, outcome) -> BookSnapshot:
    if outcome.polymarket_side == "short":
        bids = tuple(
            DepthLevel(1 - level.price, level.size)
            for level in state.raw_yes_asks
        )
        asks = tuple(
            DepthLevel(1 - level.price, level.size)
            for level in state.raw_yes_bids
        )
        market_key = outcome.polymarket_market_key
    else:
        bids = tuple(DepthLevel(level.price, level.size) for level in state.raw_yes_bids)
        asks = tuple(DepthLevel(level.price, level.size) for level in state.raw_yes_asks)
        market_key = outcome.polymarket_market_key
    return BookSnapshot(
        venue=state.venue,
        outcome_name=outcome.name,
        market_key=market_key,
        yes_bids=bids,
        yes_asks=asks,
        venue_ts=state.venue_ts,
        received_ts=state.received_ts,
        sequence=state.sequence,
        state=state.state,
    )
