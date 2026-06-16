from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv


def _load_env_files() -> None:
    logging.getLogger("dotenv.main").setLevel(logging.ERROR)
    cwd = Path.cwd()
    for path in (
        cwd / ".env",
        cwd.parent / ".env",
        cwd / "historical_testing" / ".env",
        cwd.parent / "historical_testing" / ".env",
    ):
        if path.exists():
            load_dotenv(path, override=False)


def _env_any(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _decimal_env(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None or value == "" else int(value)


@dataclass(frozen=True)
class Settings:
    kalshi_api_base: str
    kalshi_ws_url: str
    kalshi_api_key_id: str | None
    kalshi_private_key_path: str | None
    kalshi_private_key_pem: str | None
    polymarket_gateway_base: str
    polymarket_api_base: str
    polymarket_ws_url: str
    polymarket_key_id: str | None
    polymarket_secret_key: str | None
    oddpool_api_base: str
    oddpool_api_key: str | None
    discovery_refresh_seconds: int
    stale_after_seconds: Decimal
    max_matches: int
    min_match_confidence: Decimal
    min_gross_edge: Decimal
    slippage_buffer_per_pair: Decimal
    trade_size: int
    kalshi_fee_mode: str
    polymarket_taker_theta: Decimal
    live_data_dir: str
    live_data_quota_bytes: int
    live_data_low_watermark_bytes: int
    snapshot_interval_seconds: Decimal
    routine_queue_maxsize: int
    tui_refresh_seconds: Decimal
    metrics_write_seconds: Decimal
    runtime_architecture: str
    strategy_worker_count: int

    @classmethod
    def from_env(cls) -> "Settings":
        _load_env_files()
        return cls(
            kalshi_api_base=os.getenv("KALSHI_API_BASE", "https://external-api.kalshi.com/trade-api/v2"),
            kalshi_ws_url=os.getenv("KALSHI_WS_URL", "wss://api.elections.kalshi.com/trade-api/ws/v2"),
            kalshi_api_key_id=_env_any("KALSHI_API_KEY_ID", "KALSHI_ACCESS_KEY", "kalshi-api-key-id"),
            kalshi_private_key_path=_env_any("KALSHI_PRIVATE_KEY_PATH", "kalshi-private-key-path"),
            kalshi_private_key_pem=_env_any("KALSHI_PRIVATE_KEY_PEM", "kalshi-secret-key"),
            polymarket_gateway_base=os.getenv("POLYMARKET_US_GATEWAY_BASE", "https://gateway.polymarket.us"),
            polymarket_api_base=os.getenv("POLYMARKET_US_API_BASE", "https://api.polymarket.us"),
            polymarket_ws_url=os.getenv("POLYMARKET_US_WS_URL", "wss://api.polymarket.us/v1/ws/markets"),
            polymarket_key_id=_env_any("POLYMARKET_US_KEY_ID", "POLYMARKET_KEY_ID", "pm-key-id"),
            polymarket_secret_key=_env_any("POLYMARKET_US_SECRET_KEY", "POLYMARKET_SECRET_KEY", "pm-secret-key"),
            oddpool_api_base=os.getenv("ODDPOOL_API_BASE", "https://api.oddpool.com"),
            oddpool_api_key=_env_any("ODDPOOL_API_KEY", "oddpool-api-key"),
            discovery_refresh_seconds=_int_env("DISCOVERY_REFRESH_SECONDS", 600),
            stale_after_seconds=_decimal_env("STALE_AFTER_SECONDS", "5"),
            max_matches=_int_env("MAX_MATCHES", 100),
            min_match_confidence=_decimal_env("MIN_MATCH_CONFIDENCE", "0.74"),
            min_gross_edge=_decimal_env("MIN_GROSS_EDGE", "0"),
            slippage_buffer_per_pair=_decimal_env("SLIPPAGE_BUFFER_PER_PAIR", "0.01"),
            trade_size=_int_env("TRADE_SIZE", 100),
            kalshi_fee_mode=os.getenv("KALSHI_FEE_MODE", "taker"),
            polymarket_taker_theta=_decimal_env("POLYMARKET_TAKER_THETA", "0.05"),
            live_data_dir=os.getenv("LIVE_TRADING_DATA_DIR", "live_trading/data"),
            live_data_quota_bytes=_int_env("LIVE_DATA_QUOTA_BYTES", 3 * 1024**3),
            live_data_low_watermark_bytes=_int_env("LIVE_DATA_LOW_WATERMARK_BYTES", 2_700 * 1024**2),
            snapshot_interval_seconds=_decimal_env("SNAPSHOT_INTERVAL_SECONDS", "30"),
            routine_queue_maxsize=_int_env("ROUTINE_QUEUE_MAXSIZE", 20_000),
            tui_refresh_seconds=_decimal_env("TUI_REFRESH_SECONDS", "0.25"),
            metrics_write_seconds=_decimal_env("METRICS_WRITE_SECONDS", "10"),
            runtime_architecture=os.getenv("RUNTIME_ARCHITECTURE", "pooled").strip().lower(),
            strategy_worker_count=max(1, _int_env("STRATEGY_WORKER_COUNT", 2)),
        )
