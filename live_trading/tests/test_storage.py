import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal

from live_trading.models import BookState
from live_trading.storage import SegmentedRecorder


def test_recorder_coalesces_routine_snapshots(tmp_path) -> None:
    recorder = SegmentedRecorder(str(tmp_path), snapshot_interval_seconds=30)
    book = _book()

    assert recorder.try_record_book(book)
    assert not recorder.try_record_book(book)


def test_quota_rotation_removes_oldest_routine_segment_first(tmp_path) -> None:
    recorder = SegmentedRecorder(str(tmp_path), quota_bytes=1_000, low_watermark_bytes=900)
    first = recorder.snapshot_dir / "20260101T00.sqlite3"
    second = recorder.snapshot_dir / "20260101T01.sqlite3"
    first.write_bytes(b"a" * 100)
    second.write_bytes(b"b" * 100)
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))
    base_usage = recorder.disk_usage_bytes() - 200
    recorder.quota_bytes = base_usage + 150
    recorder.low_watermark_bytes = base_usage + 100

    recorder.enforce_quota()

    assert not first.exists()
    assert second.exists()
    assert recorder.metrics().rotation_count == 1


def test_recorder_writes_compact_segment(tmp_path) -> None:
    asyncio.run(_write_segment(tmp_path))


async def _write_segment(tmp_path) -> None:
    recorder = SegmentedRecorder(str(tmp_path), snapshot_interval_seconds=0)
    await recorder.start()
    recorder.try_record_book(_book())
    await recorder.close()

    assert list(recorder.snapshot_dir.glob("*.sqlite3"))


def _book() -> BookState:
    return BookState(
        venue="kalshi",
        market_key="KXTEST",
        yes_bid=Decimal("0.4"),
        yes_ask=Decimal("0.5"),
        no_bid=Decimal("0.5"),
        no_ask=Decimal("0.6"),
        received_ts=datetime.now(timezone.utc),
    )
