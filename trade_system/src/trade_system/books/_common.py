from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ..models import DepthLevel

ONE = Decimal("1")
ZERO = Decimal("0")


def to_decimal(value: Any, default: Decimal | None = ZERO) -> Decimal:
    if value is None or value == "":
        if default is None:
            raise ValueError("missing decimal value")
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        if default is None:
            raise ValueError(f"cannot parse decimal: {value!r}") from exc
        return default


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000
        return datetime.fromtimestamp(raw, timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def level_from_raw(raw: Any) -> DepthLevel:
    if isinstance(raw, dict):
        price = raw.get("price") or raw.get("px") or raw.get("p")
        size = raw.get("size") or raw.get("qty") or raw.get("quantity")
        if isinstance(price, dict):
            price = price.get("value")
        if isinstance(size, dict):
            size = size.get("value")
        return DepthLevel(to_decimal(price, None), to_decimal(size))
    return DepthLevel(to_decimal(raw[0], None), to_decimal(raw[1]))


def sorted_bids(levels: dict[Decimal, Decimal]) -> tuple[DepthLevel, ...]:
    return tuple(
        DepthLevel(price, size)
        for price, size in sorted(levels.items(), key=lambda kv: kv[0], reverse=True)
        if size > ZERO
    )


def sorted_asks(levels: dict[Decimal, Decimal]) -> tuple[DepthLevel, ...]:
    return tuple(
        DepthLevel(price, size)
        for price, size in sorted(levels.items(), key=lambda kv: kv[0])
        if size > ZERO
    )
