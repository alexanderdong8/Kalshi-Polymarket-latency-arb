from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from live_trading.execution_service.service import LiveExecutionCoordinator
from live_trading.strategy.execution.models import Order, OrderResult


class FakeLiveClient:
    def __init__(self) -> None:
        self.orders = []
        self._resting = {}

    async def reconcile(self):
        return {"status": "reconciled"}

    async def submit_ioc(self, order):
        self.orders.append(order)
        return OrderResult(
            order=order,
            filled_size=order.size,
            fill_vwap=order.limit_price,
            fees_paid=Decimal("0"),
            accepted=True,
            ts=datetime.now(timezone.utc),
        )

    async def submit_limit_postonly(self, order):
        return await self.submit_ioc(order)

    async def get_balance(self, venue):
        return Decimal("100")

    async def get_total_balance(self):
        return Decimal("200")

    async def poll_resting_orders(self):
        return []

    async def cancel_limit(self, order_id):
        self._resting.pop(order_id, None)


def test_execution_coordinator_blocks_orders_after_emergency(tmp_path) -> None:
    async def run() -> None:
        coordinator = LiveExecutionCoordinator(None, tmp_path / "STOP")  # type: ignore[arg-type]
        client = FakeLiveClient()
        wrapped, reconciliation = await coordinator.activate(
            session_id="session",
            event_id="event",
            budget=Decimal("100"),
            client=client,  # type: ignore[arg-type]
        )
        assert reconciliation["status"] == "reconciled"
        order = Order(
            venue="kalshi",
            outcome_name="A",
            market_key="K-A",
            side="buy",
            size=Decimal("1"),
            limit_price=Decimal("0.40"),
        )
        await wrapped.submit_ioc(order)
        client._resting["resting-order"] = ("polymarket_us", order)
        await wrapped.cancel_all_resting()
        assert client._resting == {}
        await coordinator.emergency_stop()
        with pytest.raises(RuntimeError, match="emergency"):
            await wrapped.submit_ioc(order)

    asyncio.run(run())


def test_execution_coordinator_reports_aggregate_allocations(tmp_path) -> None:
    async def run() -> None:
        coordinator = LiveExecutionCoordinator(None, tmp_path / "STOP")  # type: ignore[arg-type]
        await coordinator.activate(
            session_id="one",
            event_id="event-1",
            budget=Decimal("75"),
            client=FakeLiveClient(),  # type: ignore[arg-type]
        )
        await coordinator.activate(
            session_id="two",
            event_id="event-2",
            budget=Decimal("125"),
            client=FakeLiveClient(),  # type: ignore[arg-type]
        )

        assert coordinator.allocation_summary()["total_allocated"] == "200"

    asyncio.run(run())
