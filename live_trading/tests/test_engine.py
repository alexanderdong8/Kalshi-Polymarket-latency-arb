from datetime import datetime, timezone
from decimal import Decimal

from live_trading.benchmark import synthetic_book, synthetic_matches
from live_trading.books import BookStore
from live_trading.engine import HotPathEngine
from live_trading.metrics import MetricsCollector
from live_trading.registry import PairRegistry


def test_update_evaluates_only_registered_pair() -> None:
    matches = synthetic_matches(3)
    registry = PairRegistry.from_matches(matches)
    books = BookStore(stale_after_seconds=Decimal("5"))
    metrics = MetricsCollector()
    engine = HotPathEngine(
        registry,
        books,
        metrics,
        trade_size=100,
        slippage_buffer_per_pair=Decimal("0"),
        kalshi_fee_mode="taker",
        polymarket_theta=Decimal("0.05"),
        min_gross_edge=Decimal("0"),
    )
    for pair_index in range(3):
        books.set(synthetic_book("kalshi", pair_index, 0, opportunity_tick=False, randomizer=__import__("random").Random(1)))
        books.set(synthetic_book("polymarket_us", pair_index, 0, opportunity_tick=False, randomizer=__import__("random").Random(1)))

    engine.process_book(
        synthetic_book("kalshi", 1, 1, opportunity_tick=True, randomizer=__import__("random").Random(1))
    )

    assert metrics.counters["updates_processed"] == 1
    assert metrics.counters["pair_evaluations"] == 1

