import asyncio

from live_trading.shards import merge_sharded_streams, shard_items
from live_trading.venues.kalshi import KalshiClient


def test_shard_items_respects_hundred_market_cap() -> None:
    assert [len(shard) for shard in shard_items([f"market-{index}" for index in range(101)], 100)] == [100, 1]
    assert [len(shard) for shard in shard_items([f"market-{index}" for index in range(250)], 100)] == [100, 100, 50]
    assert [len(shard) for shard in shard_items([f"market-{index}" for index in range(500)], 100)] == [100, 100, 100, 100, 100]


def test_kalshi_dynamic_subscription_update_message() -> None:
    assert KalshiClient.subscription_update_message(7, ["KX-A", "KX-B"], "add_markets", request_id=3) == {
        "id": 3,
        "cmd": "update_subscription",
        "params": {"sid": 7, "market_tickers": ["KX-A", "KX-B"], "action": "add_markets"},
    }


def test_shard_failure_does_not_pause_other_shards() -> None:
    asyncio.run(_exercise_failure_isolation())


async def _exercise_failure_isolation() -> None:
    attempts = {}
    reconnects = []

    async def worker(shard: list[str], shard_id: int):
        attempts[shard_id] = attempts.get(shard_id, 0) + 1
        if shard_id == 0 and attempts[shard_id] == 1:
            raise RuntimeError("synthetic reconnect")
        yield f"{shard_id}:{shard[0]}"

    stream = merge_sharded_streams([["a"], ["b"]], worker, on_reconnect=reconnects.append)
    first = await asyncio.wait_for(anext(stream), timeout=1)
    await stream.aclose()

    assert first == "1:b"
    assert reconnects == ["shard-0"]
