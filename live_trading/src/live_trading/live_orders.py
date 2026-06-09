from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .auth import kalshi_headers, polymarket_us_headers, read_private_key
from .config import Settings
from .execution_persistence import ExecutionJournal
from .strategy.execution.models import Order, OrderResult, RestingOrderUpdate
from .strategy.models import Venue

ZERO = Decimal("0")


@dataclass
class LiveOrderClient:
    settings: Settings
    journal: ExecutionJournal

    def __post_init__(self) -> None:
        self._kalshi_key = read_private_key(
            self.settings.kalshi_private_key_path,
            self.settings.kalshi_private_key_pem,
        )
        self._resting: dict[str, tuple[str, Order]] = {}
        self._reported_fills: dict[str, Decimal] = {}
        self._reported_fees: dict[str, Decimal] = {}

    async def submit_ioc(self, order: Order) -> OrderResult:
        return await (
            self._submit_kalshi(order, post_only=False)
            if order.venue == "kalshi"
            else self._submit_polymarket(order, post_only=False)
        )

    async def submit_limit_postonly(self, order: Order) -> OrderResult:
        result = await (
            self._submit_kalshi(order, post_only=True)
            if order.venue == "kalshi"
            else self._submit_polymarket(order, post_only=True)
        )
        if result.accepted and result.order_id:
            self._resting[result.order_id] = (order.venue, order)
        return result

    async def get_balance(self, venue: Venue) -> Decimal:
        if venue == "kalshi":
            payload = await self._request_kalshi("GET", "/portfolio/balance")
            raw = payload.get("balance_dollars") or payload.get("balance") or 0
            value = Decimal(str(raw))
            return value / Decimal("100") if value > Decimal("10000") else value
        payload = await self._request_polymarket("GET", "/v1/account/balances")
        balances = payload.get("balances") or []
        usd = next((row for row in balances if row.get("currency") == "USD"), {})
        return Decimal(str(usd.get("buyingPower") or usd.get("currentBalance") or 0))

    async def get_total_balance(self) -> Decimal:
        left, right = await asyncio.gather(
            self.get_balance("kalshi"),
            self.get_balance("polymarket_us"),
        )
        return left + right

    async def poll_resting_orders(self) -> list[RestingOrderUpdate]:
        updates: list[RestingOrderUpdate] = []
        for order_id, (venue, order) in list(self._resting.items()):
            payload = await (
                self._request_kalshi("GET", f"/portfolio/orders/{order_id}")
                if venue == "kalshi"
                else self._request_polymarket("GET", f"/v1/order/{order_id}")
            )
            normalized = _order_payload(payload)
            cumulative = Decimal(str(normalized.get("filled") or 0))
            cumulative_fees = Decimal(str(normalized.get("fees") or 0))
            fill_delta = max(ZERO, cumulative - self._reported_fills.get(order_id, ZERO))
            fee_delta = max(ZERO, cumulative_fees - self._reported_fees.get(order_id, ZERO))
            requested = order.size
            state = str(normalized.get("state") or "resting").lower()
            if fill_delta > ZERO or state in {"filled", "cancelled", "canceled", "rejected", "expired"}:
                updates.append(
                    RestingOrderUpdate(
                        order_id=order_id,
                        venue=venue,  # type: ignore[arg-type]
                        outcome_name=order.outcome_name,
                        side=order.side,
                        limit_price=order.limit_price,
                        filled_size_delta=fill_delta,
                        fill_vwap=Decimal(str(normalized.get("avg_price") or order.limit_price)),
                        fees_delta=fee_delta,
                        cumulative_filled=cumulative,
                        requested_size=requested,
                        final_state="filled" if cumulative >= requested else state,
                        ts=datetime.now(timezone.utc),
                    )
                )
                self._reported_fills[order_id] = cumulative
                self._reported_fees[order_id] = cumulative_fees
            if state in {"filled", "cancelled", "canceled", "rejected", "expired"}:
                self._resting.pop(order_id, None)
        return updates

    async def cancel_limit(self, order_id: str) -> None:
        venue_order = self._resting.get(order_id)
        if venue_order is None:
            return
        venue, order = venue_order
        if venue == "kalshi":
            await self._request_kalshi("DELETE", f"/portfolio/events/orders/{order_id}")
        else:
            await self._request_polymarket(
                "POST",
                f"/v1/order/{order_id}/cancel",
                {"marketSlug": order.market_key},
            )
        self._resting.pop(order_id, None)
        self.journal.append(
            "order_cancelled",
            {"order_id": order_id},
            exchange_order_id=order_id,
            venue=venue,
            status="cancelled",
        )

    async def reconcile(self) -> dict[str, Any]:
        unresolved = self.journal.unresolved_orders()
        balances = await asyncio.gather(
            self.get_balance("kalshi"),
            self.get_balance("polymarket_us"),
            return_exceptions=True,
        )
        positions = await asyncio.gather(
            self._request_kalshi("GET", "/portfolio/positions"),
            self._request_polymarket("GET", "/v1/portfolio/positions"),
            return_exceptions=True,
        )
        return {
            "unresolved_local_orders": unresolved,
            "local_open_positions": self.journal.open_positions(),
            "kalshi_balance": str(balances[0]) if not isinstance(balances[0], Exception) else None,
            "polymarket_us_balance": str(balances[1]) if not isinstance(balances[1], Exception) else None,
            "kalshi_positions": (
                positions[0].get("market_positions", positions[0])
                if isinstance(positions[0], dict)
                else []
            ),
            "polymarket_us_positions": (
                positions[1].get("positions", positions[1])
                if isinstance(positions[1], dict)
                else []
            ),
        }

    async def _submit_kalshi(self, order: Order, *, post_only: bool) -> OrderResult:
        client_order_id = str(uuid.uuid4())
        body = {
            "ticker": order.market_key,
            "client_order_id": client_order_id,
            "side": "bid" if order.side == "buy" else "ask",
            "count": str(order.size),
            "price": str(order.limit_price),
            "time_in_force": "good_till_canceled" if post_only else "immediate_or_cancel",
            "post_only": post_only,
            "self_trade_prevention_type": "taker_at_cross",
        }
        self.journal.append(
            "order_submitting",
            body,
            client_order_id=client_order_id,
            venue="kalshi",
            status="submitting",
        )
        try:
            payload = await self._request_kalshi("POST", "/portfolio/events/orders", body)
        except Exception as exc:
            return OrderResult(order, ZERO, ZERO, ZERO, False, str(exc))
        order_id = str(payload.get("order_id") or "")
        filled = Decimal(str(payload.get("fill_count") or 0))
        vwap = Decimal(str(payload.get("average_fill_price") or order.limit_price)) if filled > ZERO else ZERO
        average_fee = Decimal(str(payload.get("average_fee_paid") or 0))
        fees = average_fee * filled
        self.journal.append(
            "order_accepted",
            payload,
            client_order_id=client_order_id,
            exchange_order_id=order_id,
            venue="kalshi",
            status="filled" if filled >= order.size else "resting" if post_only else "cancelled",
        )
        return OrderResult(
            order=order,
            filled_size=filled,
            fill_vwap=vwap,
            fees_paid=fees,
            accepted=True,
            order_id=order_id or None,
        )

    async def _submit_polymarket(self, order: Order, *, post_only: bool) -> OrderResult:
        client_order_id = str(uuid.uuid4())
        body = {
            "marketSlug": order.market_key,
            "type": "ORDER_TYPE_LIMIT",
            "price": {"value": str(order.limit_price), "currency": "USD"},
            "quantity": float(order.size),
            "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL" if post_only else "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
            "participateDontInitiate": post_only,
            "intent": "ORDER_INTENT_BUY_LONG" if order.side == "buy" else "ORDER_INTENT_SELL_LONG",
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
            "synchronousExecution": not post_only,
            "maxBlockTime": "5",
        }
        self.journal.append(
            "order_submitting",
            body,
            client_order_id=client_order_id,
            venue="polymarket_us",
            status="submitting",
        )
        try:
            payload = await self._request_polymarket("POST", "/v1/orders", body)
        except Exception as exc:
            return OrderResult(order, ZERO, ZERO, ZERO, False, str(exc))
        executions = payload.get("executions") or []
        filled = sum((Decimal(str(row.get("lastShares") or 0)) for row in executions), ZERO)
        value = sum(
            (
                Decimal(str((row.get("lastPx") or {}).get("value") or 0))
                * Decimal(str(row.get("lastShares") or 0))
                for row in executions
            ),
            ZERO,
        )
        vwap = value / filled if filled > ZERO else ZERO
        fees = sum(
            (
                Decimal(str((row.get("commissionNotionalCollected") or {}).get("value") or 0))
                for row in executions
            ),
            ZERO,
        )
        order_id = str(payload.get("id") or "")
        self.journal.append(
            "order_accepted",
            payload,
            client_order_id=client_order_id,
            exchange_order_id=order_id,
            venue="polymarket_us",
            status="filled" if filled >= order.size else "resting" if post_only else "cancelled",
        )
        return OrderResult(order, filled, vwap, fees, True, order_id=order_id or None)

    async def _request_kalshi(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.kalshi_api_key_id or not self._kalshi_key:
            raise RuntimeError("Kalshi live credentials are missing.")
        base_path = urlparse(self.settings.kalshi_api_base).path.rstrip("/")
        signed_path = f"{base_path}{path}"
        headers = kalshi_headers(
            self.settings.kalshi_api_key_id,
            self._kalshi_key,
            method,
            signed_path,
        )
        url = f"{self.settings.kalshi_api_base.rstrip('/')}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=body) as response:
                response.raise_for_status()
                return await response.json()

    async def _request_polymarket(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.polymarket_key_id or not self.settings.polymarket_secret_key:
            raise RuntimeError("Polymarket US live credentials are missing.")
        headers = polymarket_us_headers(
            self.settings.polymarket_key_id,
            self.settings.polymarket_secret_key,
            method,
            path,
        )
        url = f"{self.settings.polymarket_api_base.rstrip('/')}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=body) as response:
                response.raise_for_status()
                return await response.json()


def _order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    row = payload.get("order") if isinstance(payload.get("order"), dict) else payload
    return {
        "filled": row.get("fill_count")
        or row.get("cumQuantity")
        or row.get("cum_quantity")
        or 0,
        "state": row.get("status") or row.get("state") or "resting",
        "avg_price": row.get("avg_price")
        or (row.get("avgPx") or {}).get("value")
        or row.get("price"),
        "fees": row.get("fees") or 0,
    }
