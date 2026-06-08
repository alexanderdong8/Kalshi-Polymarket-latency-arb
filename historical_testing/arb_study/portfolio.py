from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import heapq
from typing import Any

from .research_config import PORTFOLIO_POSITION_CAP_SHARE, PORTFOLIO_STARTING_BANKROLL


@dataclass(frozen=True)
class PortfolioRules:
    starting_bankroll: float = PORTFOLIO_STARTING_BANKROLL
    position_cap_share: float = PORTFOLIO_POSITION_CAP_SHARE


def simulate_portfolio(
    opportunities: list[dict[str, Any]],
    *,
    contracts: int,
    rules: PortfolioRules | None = None,
    enforce_depth: bool,
) -> dict[str, Any]:
    """Take chronological, non-overlapping locked pairs with no leverage."""
    cfg = rules or PortfolioRules()
    cash = cfg.starting_bankroll
    realized_profit = 0.0
    active_until: dict[str, datetime] = {}
    releases: list[tuple[datetime, float]] = []
    accepted: list[dict[str, Any]] = []
    rejected = {"cash": 0, "depth": 0, "already_active": 0, "non_positive": 0}
    cap = cfg.starting_bankroll * cfg.position_cap_share

    for item in sorted(opportunities, key=lambda row: row["start"]):
        start = _parse(item["start"])
        while releases and releases[0][0] <= start:
            _, released_cash = heapq.heappop(releases)
            cash += released_cash
        match_id = str(item["match_id"])
        if match_id in active_until and active_until[match_id] > start:
            rejected["already_active"] += 1
            continue
        profit_per_contract = float(item.get("net_profit_per_contract") or 0)
        entry_cost_per_contract = float(item.get("entry_cost_per_contract") or 0)
        if profit_per_contract <= 0 or entry_cost_per_contract <= 0:
            rejected["non_positive"] += 1
            continue
        if enforce_depth and float(item.get("depth_contracts") or 0) + 1e-9 < contracts:
            rejected["depth"] += 1
            continue
        entry_cost = entry_cost_per_contract * contracts
        if entry_cost > cash + 1e-9 or entry_cost > cap + 1e-9:
            rejected["cash"] += 1
            continue
        exit_at = _parse(item.get("paired_exit_at") or item["settlement_at"])
        profit = profit_per_contract * contracts
        cash -= entry_cost
        realized_profit += profit
        active_until[match_id] = exit_at
        heapq.heappush(releases, (exit_at, entry_cost + profit))
        accepted.append({**item, "contracts": contracts, "realized_profit": profit})

    while releases:
        _, released_cash = heapq.heappop(releases)
        cash += released_cash
    return {
        "starting_bankroll": cfg.starting_bankroll,
        "ending_bankroll": cash,
        "realized_profit": realized_profit,
        "position_cap": cap,
        "contracts": contracts,
        "accepted_positions": len(accepted),
        "rejected": rejected,
        "positions": accepted,
        "warning": (
            "This is a chronological model, not an observed execution log. "
            "Annual proxy simulations do not know historical displayed depth."
        ),
    }


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
