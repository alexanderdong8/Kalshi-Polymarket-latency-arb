import asyncio
from decimal import Decimal
from types import SimpleNamespace

from live_trading.execution_persistence import ExecutionJournal
from live_trading.live_orders import LiveOrderClient
from live_trading.strategy.execution.models import Order


class FakeLiveOrderClient(LiveOrderClient):
    async def _request_kalshi(self, method, path, body=None):
        assert method == "POST"
        assert path == "/portfolio/events/orders"
        assert body["time_in_force"] == "immediate_or_cancel"
        return {
            "order_id": "kalshi-order",
            "fill_count": "2",
            "average_fill_price": "0.40",
            "average_fee_paid": "0.01",
        }

    async def _request_polymarket(self, method, path, body=None):
        assert method == "POST"
        assert path == "/v1/orders"
        self.last_poly_body = body
        return {
            "id": "poly-order",
            "executions": [
                {
                    "lastShares": 2,
                    "lastPx": {"value": "0.39"},
                    "commissionNotionalCollected": {"value": "0.01"},
                }
            ],
        }


def _settings():
    return SimpleNamespace(
        kalshi_private_key_path=None,
        kalshi_private_key_pem=None,
        kalshi_api_key_id=None,
        kalshi_api_base="https://example.invalid/trade-api/v2",
        polymarket_key_id=None,
        polymarket_secret_key=None,
        polymarket_api_base="https://example.invalid",
    )


def test_live_order_adapters_are_mockable_and_normalize_fills(tmp_path):
    async def run():
        client = FakeLiveOrderClient(_settings(), ExecutionJournal(tmp_path / "journal.sqlite3"))
        kalshi = await client.submit_ioc(
            Order("kalshi", "A", "K-A", "buy", Decimal("2"), Decimal("0.40"))
        )
        poly = await client.submit_ioc(
            Order("polymarket_us", "A", "p-a", "buy", Decimal("2"), Decimal("0.40"))
        )
        assert kalshi.filled_size == Decimal("2")
        assert kalshi.fill_vwap == Decimal("0.40")
        assert kalshi.fees_paid == Decimal("0.02")
        assert poly.filled_size == Decimal("2")
        assert poly.fill_vwap == Decimal("0.39")
        assert client.last_poly_body["intent"] == "ORDER_INTENT_BUY_LONG"

    asyncio.run(run())


def test_polymarket_short_execution_key_uses_short_intent_and_real_slug(tmp_path):
    async def run():
        client = FakeLiveOrderClient(
            _settings(), ExecutionJournal(tmp_path / "journal.sqlite3")
        )
        await client.submit_ioc(
            Order(
                "polymarket_us",
                "B",
                "shared-market::short",
                "buy",
                Decimal("2"),
                Decimal("0.40"),
            )
        )

        assert client.last_poly_body["marketSlug"] == "shared-market"
        assert client.last_poly_body["intent"] == "ORDER_INTENT_BUY_SHORT"

    asyncio.run(run())
