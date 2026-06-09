from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtesting.models import ReplayUpdate
from backtesting.pmxt import validate_coverage
from backtesting.simulator import run_delay_matrix, simulate
from live_trading.strategy.manifest import EventManifest
from live_trading.strategy.models import BookSnapshot, DepthLevel, EventSpec, OutcomeSpec


def _manifest(tmp_path):
    event = EventSpec(
        "Replay Event",
        None,
        (OutcomeSpec("A", "K-A", "P-A"), OutcomeSpec("B", "K-B", "P-B")),
    )
    return EventManifest(event, True, True, True, {}, tmp_path / "event.yaml")


def _updates():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for offset in range(6):
        timestamp = start + timedelta(milliseconds=100 * offset)
        for outcome in ("A", "B"):
            for venue, ask in (("kalshi", Decimal("0.40")), ("polymarket_us", Decimal("0.42"))):
                rows.append(
                    ReplayUpdate(
                        timestamp,
                        BookSnapshot(
                            venue=venue,
                            outcome_name=outcome,
                            market_key=f"{venue}-{outcome}",
                            yes_bids=(DepthLevel(Decimal("0.35"), Decimal("1000")),),
                            yes_asks=(DepthLevel(ask, Decimal("1000")),),
                            received_ts=timestamp,
                        ),
                        fee_rate_bps=Decimal("500"),
                    )
                )
    return rows


def test_replay_reports_each_delay_and_both_fill_models(tmp_path):
    results = run_delay_matrix(
        _manifest(tmp_path),
        _updates(),
        target_size=Decimal("10"),
    )
    assert {(row.delay_ms, row.fill_model) for row in results} == {
        (delay, model)
        for delay in (50, 250, 500, 1000)
        for model in ("maker", "price_passes")
    }
    assert all(row.starting_cash == Decimal("1000") for row in results)
    assert all(row.total_money_gained == row.ending_cash - Decimal("1000") for row in results)


def test_coverage_rejects_missing_outcome_book(tmp_path):
    updates = [
        row
        for row in _updates()
        if not (row.book.venue == "polymarket_us" and row.book.outcome_name == "B")
    ]
    coverage = validate_coverage(_manifest(tmp_path), updates)
    assert coverage["valid"] is False
    assert "polymarket_us:B" in coverage["missing_books"]


def test_replay_refuses_missing_polymarket_fee_metadata(tmp_path):
    updates = [
        ReplayUpdate(row.timestamp_received, row.book, None)
        for row in _updates()
    ]
    with pytest.raises(ValueError, match="fee_rate_bps"):
        run_delay_matrix(_manifest(tmp_path), updates, target_size=Decimal("10"))


def test_replay_releases_cash_after_profitable_maker_exit(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    updates = []
    for offset in range(8):
        timestamp = start + timedelta(milliseconds=100 * offset)
        bid = Decimal("0.35")
        ask = Decimal("0.40")
        if offset == 5:
            bid, ask = Decimal("0.55"), Decimal("0.70")
        elif offset >= 6:
            bid, ask = Decimal("0.57"), Decimal("0.70")
        for outcome in ("A", "B"):
            for venue in ("kalshi", "polymarket_us"):
                updates.append(
                    ReplayUpdate(
                        timestamp,
                        BookSnapshot(
                            venue=venue,
                            outcome_name=outcome,
                            market_key=f"{venue}-{outcome}",
                            yes_bids=(DepthLevel(bid, Decimal("1000")),),
                            yes_asks=(DepthLevel(ask, Decimal("1000")),),
                            received_ts=timestamp,
                        ),
                        fee_rate_bps=Decimal("500"),
                    )
                )
    result = simulate(
        _manifest(tmp_path),
        updates,
        delay_ms=50,
        fill_model="maker",
        target_size=Decimal("10"),
    )
    assert any(fill.side == "sell" for fill in result.fills)
    assert result.ending_cash > Decimal("1000")
