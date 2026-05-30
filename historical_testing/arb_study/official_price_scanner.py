from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .fees import leg_fee
from .models import MatchedMarket
from .official_api import KalshiOfficialClient, PolymarketOfficialClient
from .scenario import classify_domain, classify_phase, summarize_records


@dataclass
class OfficialProxyOpportunity:
    match_id: str
    timestamp: str
    direction: str
    yes_venue: str
    no_venue: str
    yes_price: float
    no_price: float
    total_cost: float
    gross_edge_per_contract: float
    net_edge_per_contract: float
    total_fee: float
    domain: str
    phase: str
    polymarket_title: str
    kalshi_title: str
    warning: str | None


def scan_official_price_histories(
    matches: list[MatchedMarket],
    start: str,
    end: str,
    max_markets: int | None = None,
    trade_size: int = 100,
    slippage_buffer: float = 0.005,
    kalshi_fee_mode: str = "taker",
    polymarket_fallback_fee_rate: float = 0.05,
) -> dict[str, Any]:
    start_ts = _to_unix(start)
    end_ts = _to_unix(end)
    poly = PolymarketOfficialClient()
    kalshi = KalshiOfficialClient()
    selected = matches[:max_markets] if max_markets else matches
    market_records: list[dict[str, Any]] = []
    opportunities: list[OfficialProxyOpportunity] = []
    errors: list[dict[str, str]] = []

    for match in selected:
        title = f"{match.polymarket.title} {match.kalshi.title}"
        category = match.polymarket.category or match.kalshi.category
        tags = list(match.polymarket.raw.get("tags") or []) + list(match.kalshi.raw.get("tags") or [])
        domain = classify_domain(title, category, tags)
        try:
            kalshi_rows = kalshi.market_candlesticks(match.kalshi.slug or match.kalshi.yes.outcome_id, start_ts, end_ts, 1)
            poly_yes = poly.prices_history(match.polymarket.yes.outcome_id, start_ts, end_ts, 1)
            poly_no = poly.prices_history(match.polymarket.no.outcome_id, start_ts, end_ts, 1)
            states = _align_official_series(kalshi_rows, poly_yes, poly_no)
        except Exception as exc:  # noqa: BLE001
            errors.append({"match_id": match.match_id, "error": str(exc)})
            continue

        best_opp: OfficialProxyOpportunity | None = None
        gross_positive = 0
        net_positive = 0
        for state in states:
            phase = classify_phase(
                title,
                start,
                match.polymarket.resolution_date or match.kalshi.resolution_date,
                aligned_state_count=len(states),
                best_gross_edge=None,
                median_window_seconds=None,
            )
            state_opps = _evaluate_proxy_state(
                match,
                state,
                domain,
                phase,
                trade_size,
                slippage_buffer,
                kalshi_fee_mode,
                polymarket_fallback_fee_rate,
            )
            for opp in state_opps:
                gross_positive += int(opp.gross_edge_per_contract > 0)
                net_positive += int(opp.net_edge_per_contract > 0)
                if opp.net_edge_per_contract > 0:
                    opportunities.append(opp)
                if best_opp is None or opp.net_edge_per_contract > best_opp.net_edge_per_contract:
                    best_opp = opp

        best_gross = best_opp.gross_edge_per_contract if best_opp else None
        phase = classify_phase(
            title,
            start,
            match.polymarket.resolution_date or match.kalshi.resolution_date,
            aligned_state_count=len(states),
            best_gross_edge=best_gross,
            median_window_seconds=None,
        )
        market_records.append(
            {
                "match_id": match.match_id,
                "domain": domain,
                "phase": phase,
                "polymarket_title": match.polymarket.title,
                "kalshi_title": match.kalshi.title,
                "aligned_points": len(states),
                "gross_positive_points": gross_positive,
                "net_positive_points": net_positive,
                "net_positive_windows": 1 if net_positive else 0,
                "gross_positive_windows": 1 if gross_positive else 0,
                "best_net_edge_per_contract": best_opp.net_edge_per_contract if best_opp else None,
                "best_gross_edge_per_contract": best_opp.gross_edge_per_contract if best_opp else None,
                "warning": match.resolution_date_warning,
            }
        )

    opportunities.sort(key=lambda item: item.net_edge_per_contract, reverse=True)
    return {
        "parameters": {
            "source": "official_api_price_history_proxy",
            "start": start,
            "end": end,
            "markets_scanned": len(selected),
            "trade_size": trade_size,
            "slippage_buffer": slippage_buffer,
            "note": "Official APIs provide price/candlestick histories, not synchronized historical orderbook depth. Treat results as price-history proxy signals, not executable proof.",
        },
        "summary_by_bucket": summarize_records(market_records),
        "markets": market_records,
        "opportunities": [asdict(item) for item in opportunities],
        "errors": errors,
    }


def _align_official_series(
    kalshi_rows: list[dict[str, Any]],
    poly_yes_rows: list[dict[str, Any]],
    poly_no_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kalshi_series = {
        _minute_bucket(int(row["end_period_ts"])): {
            "kalshi_yes_ask": _nested_float(row, "yes_ask", "close_dollars"),
            "kalshi_yes_bid": _nested_float(row, "yes_bid", "close_dollars"),
        }
        for row in kalshi_rows
    }
    poly_yes = {_minute_bucket(int(row["t"])): float(row["p"]) for row in poly_yes_rows if row.get("p") is not None}
    poly_no = {_minute_bucket(int(row["t"])): float(row["p"]) for row in poly_no_rows if row.get("p") is not None}
    timestamps = sorted(set(kalshi_series) & set(poly_yes) & set(poly_no))
    states = []
    for ts in timestamps:
        k = kalshi_series[ts]
        if k["kalshi_yes_ask"] is None or k["kalshi_yes_bid"] is None:
            continue
        states.append(
            {
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "kalshi_yes_ask": k["kalshi_yes_ask"],
                "kalshi_no_ask": 1.0 - k["kalshi_yes_bid"],
                "poly_yes_price": poly_yes[ts],
                "poly_no_price": poly_no[ts],
            }
        )
    return states


def _evaluate_proxy_state(
    match: MatchedMarket,
    state: dict[str, Any],
    domain: str,
    phase: str,
    trade_size: int,
    slippage_buffer: float,
    kalshi_fee_mode: str,
    polymarket_fallback_fee_rate: float,
) -> list[OfficialProxyOpportunity]:
    directions = [
        ("kalshi_yes__poly_no_proxy", "kalshi", "polymarket", state["kalshi_yes_ask"], state["poly_no_price"]),
        ("poly_yes__kalshi_no_proxy", "polymarket", "kalshi", state["poly_yes_price"], state["kalshi_no_ask"]),
    ]
    out = []
    for direction, yes_venue, no_venue, yes_price, no_price in directions:
        gross = 1.0 - (yes_price + no_price)
        if gross <= 0:
            continue
        fees = leg_fee(
            yes_venue,
            yes_price,
            trade_size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        ) + leg_fee(
            no_venue,
            no_price,
            trade_size,
            kalshi_mode=kalshi_fee_mode,
            polymarket_fallback_rate=polymarket_fallback_fee_rate,
        )
        net = gross - (fees / trade_size) - (2 * slippage_buffer)
        out.append(
            OfficialProxyOpportunity(
                match_id=match.match_id,
                timestamp=state["timestamp"],
                direction=direction,
                yes_venue=yes_venue,
                no_venue=no_venue,
                yes_price=yes_price,
                no_price=no_price,
                total_cost=yes_price + no_price,
                gross_edge_per_contract=gross,
                net_edge_per_contract=net,
                total_fee=fees,
                domain=domain,
                phase=phase,
                polymarket_title=match.polymarket.title,
                kalshi_title=match.kalshi.title,
                warning=match.resolution_date_warning,
            )
        )
    return out


def _nested_float(row: dict[str, Any], key: str, child: str) -> float | None:
    value = (row.get(key) or {}).get(child)
    if value is None:
        return None
    return float(value)


def _minute_bucket(timestamp: int) -> int:
    return timestamp - (timestamp % 60)


def _to_unix(value: str) -> int:
    if len(value) == 13:
        value = f"{value}:00:00+00:00"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())
