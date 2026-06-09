import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from live_trading.strategy.books import BookStore
from live_trading.strategy.detector import Detector
from live_trading.strategy.execution.client import SimulatedOrderClient
from live_trading.strategy.execution.models import Order
from live_trading.strategy.models import BookSnapshot, DepthLevel, EventSpec, OutcomeSpec


def _book(venue, outcome, asks, bids=((Decimal("0.30"), Decimal("100")),)):
    return BookSnapshot(
        venue=venue,
        outcome_name=outcome,
        market_key=f"{venue}-{outcome}",
        yes_bids=tuple(DepthLevel(*row) for row in bids),
        yes_asks=tuple(DepthLevel(*row) for row in asks),
        received_ts=datetime.now(timezone.utc),
    )


def test_detector_chooses_cheapest_full_l2_vwap_per_outcome():
    event = EventSpec(
        "Event",
        None,
        (OutcomeSpec("A", "K-A", "P-A"), OutcomeSpec("B", "K-B", "P-B")),
    )
    detector = Detector(event, Decimal("10"), min_non_widening_ticks=0)
    books = {
        ("kalshi", "A"): _book(
            "kalshi",
            "A",
            ((Decimal("0.30"), Decimal("5")), (Decimal("0.50"), Decimal("10"))),
        ),
        ("polymarket_us", "A"): _book(
            "polymarket_us", "A", ((Decimal("0.45"), Decimal("20")),)
        ),
        ("kalshi", "B"): _book("kalshi", "B", ((Decimal("0.35"), Decimal("20")),)),
        ("polymarket_us", "B"): _book(
            "polymarket_us", "B", ((Decimal("0.45"), Decimal("20")),)
        ),
    }
    evaluation = detector.evaluate(books)
    assert evaluation.legs[0].chosen_venue == "kalshi"
    assert evaluation.legs[0].levels_consumed == 2
    assert evaluation.legs[1].chosen_venue == "kalshi"


def test_paper_ioc_does_not_mutate_public_market_book():
    async def run():
        store = BookStore()
        book = _book("kalshi", "A", ((Decimal("0.40"), Decimal("20")),))
        await store.set(book)
        client = SimulatedOrderClient(
            store, initial_balance=Decimal("100"), mutate_books=False
        )
        result = await client.submit_ioc(
            Order("kalshi", "A", book.market_key, "buy", Decimal("5"), Decimal("0.40"))
        )
        assert result.filled_size == Decimal("5")
        assert (await store.get("kalshi", "A")).yes_asks == book.yes_asks

    asyncio.run(run())


def test_paper_resting_fill_does_not_mutate_public_market_book():
    async def run():
        store = BookStore()
        book = _book(
            "kalshi",
            "A",
            ((Decimal("0.60"), Decimal("20")),),
            bids=((Decimal("0.50"), Decimal("20")),),
        )
        await store.set(book)
        client = SimulatedOrderClient(
            store, initial_balance=Decimal("100"), mutate_books=False
        )
        await client.submit_limit_postonly(
            Order("kalshi", "A", book.market_key, "sell", Decimal("5"), Decimal("0.50"))
        )
        updates = await client.poll_resting_orders()
        assert updates[0].filled_size_delta == Decimal("5")
        assert (await store.get("kalshi", "A")).yes_bids == book.yes_bids

    asyncio.run(run())
