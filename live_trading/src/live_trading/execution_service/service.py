from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config import Settings
from ..execution_persistence import ExecutionJournal
from ..live_orders import LiveOrderClient
from ..strategy.execution.models import Order, OrderResult, RestingOrderUpdate
from ..strategy.models import Venue


@dataclass(frozen=True)
class LiveAllocation:
    session_id: str
    event_id: str
    budget: Decimal


class CoordinatedLiveOrderClient:
    def __init__(
        self,
        coordinator: "LiveExecutionCoordinator",
        session_id: str,
        delegate: LiveOrderClient,
    ) -> None:
        self.coordinator = coordinator
        self.session_id = session_id
        self.delegate = delegate

    @property
    def _resting(self) -> dict[str, Any]:
        return self.delegate._resting

    async def submit_ioc(self, order: Order) -> OrderResult:
        self.coordinator.assert_entry_allowed(self.session_id)
        return await self.delegate.submit_ioc(order)

    async def submit_limit_postonly(self, order: Order) -> OrderResult:
        self.coordinator.assert_entry_allowed(self.session_id)
        return await self.delegate.submit_limit_postonly(order)

    async def get_balance(self, venue: Venue) -> Decimal:
        return await self.delegate.get_balance(venue)

    async def get_total_balance(self) -> Decimal:
        return await self.delegate.get_total_balance()

    async def poll_resting_orders(self) -> list[RestingOrderUpdate]:
        return await self.delegate.poll_resting_orders()

    async def cancel_limit(self, order_id: str) -> None:
        await self.delegate.cancel_limit(order_id)

    async def cancel_all_resting(self) -> None:
        resting = getattr(self.delegate, "_resting", {})
        await asyncio.gather(
            *(self.delegate.cancel_limit(order_id) for order_id in list(resting)),
            return_exceptions=True,
        )


class LiveExecutionCoordinator:
    """Central live activation, reconciliation, allocation, and emergency guard."""

    def __init__(self, settings: Settings, emergency_path: Path) -> None:
        self.settings = settings
        self.emergency_path = emergency_path
        self._allocations: dict[str, LiveAllocation] = {}
        self._clients: dict[str, CoordinatedLiveOrderClient] = {}
        self._lock = asyncio.Lock()

    async def activate(
        self,
        *,
        session_id: str,
        event_id: str,
        budget: Decimal,
        client: LiveOrderClient,
    ) -> tuple[CoordinatedLiveOrderClient, dict[str, Any]]:
        async with self._lock:
            if self.emergency_path.exists():
                raise RuntimeError("Global emergency stop is active.")
            reconciliation = await client.reconcile()
            missing_balances = [
                venue
                for venue, key in (
                    ("Kalshi", "kalshi_balance"),
                    ("Polymarket US", "polymarket_us_balance"),
                )
                if key in reconciliation and reconciliation.get(key) is None
            ]
            if missing_balances:
                raise RuntimeError(
                    "Live reconciliation could not verify balances for: "
                    + ", ".join(missing_balances)
                )
            allocation = LiveAllocation(session_id, event_id, budget)
            wrapped = CoordinatedLiveOrderClient(self, session_id, client)
            self._allocations[session_id] = allocation
            self._clients[session_id] = wrapped
            return wrapped, reconciliation

    async def deactivate(self, session_id: str) -> None:
        async with self._lock:
            self._allocations.pop(session_id, None)
            self._clients.pop(session_id, None)

    async def preview(
        self,
        *,
        journal: ExecutionJournal,
        budget: Decimal,
    ) -> dict[str, Any]:
        client = LiveOrderClient(self.settings, journal)
        reconciliation = await client.reconcile()
        return {
            "reconciliation": reconciliation,
            "active_allocations": self.allocation_summary(),
        }

    async def emergency_stop(self) -> None:
        self.emergency_path.parent.mkdir(parents=True, exist_ok=True)
        self.emergency_path.write_text("Global live emergency stop.\n", encoding="utf-8")
        clients = list(self._clients.values())
        await asyncio.gather(
            *(client.cancel_all_resting() for client in clients),
            return_exceptions=True,
        )

    def assert_entry_allowed(self, session_id: str) -> None:
        if self.emergency_path.exists():
            raise RuntimeError("Global emergency stop blocks new live orders.")
        if session_id not in self._allocations:
            raise RuntimeError("Live session is not registered with execution coordination.")

    def allocation_summary(self) -> dict[str, Any]:
        allocations = [
            {
                "session_id": row.session_id,
                "event_id": row.event_id,
                "budget": str(row.budget),
            }
            for row in self._allocations.values()
        ]
        return {
            "allocations": allocations,
            "total_allocated": str(
                sum((row.budget for row in self._allocations.values()), Decimal("0"))
            ),
        }
