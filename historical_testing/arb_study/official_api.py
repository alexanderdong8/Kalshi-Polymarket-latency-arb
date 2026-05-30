from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .config import load_dotenv


POLYMARKET_CLOB_BASE = "https://clob.polymarket.com"
KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"


@dataclass
class OfficialAPIConfig:
    kalshi_api_key_id: str | None = None
    kalshi_private_key_pem: str | None = None


def load_official_api_config(env_file: str = ".env") -> OfficialAPIConfig:
    values = load_dotenv(env_file)
    private_key = values.get("kalshi-secret-key") or values.get("KALSHI_PRIVATE_KEY")
    if private_key:
        private_key = private_key.replace("\\n", "\n")
    return OfficialAPIConfig(
        kalshi_api_key_id=values.get("kalshi-api-key-id") or values.get("KALSHI_API_KEY_ID"),
        kalshi_private_key_pem=private_key,
    )


class PolymarketOfficialClient:
    def __init__(self, base_url: str = POLYMARKET_CLOB_BASE, retries: int = 3) -> None:
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.session = requests.Session()

    def prices_history(
        self,
        token_id: str,
        start_ts: int,
        end_ts: int,
        fidelity: int = 1,
    ) -> list[dict[str, Any]]:
        data = self._get(
            "/prices-history",
            {
                "market": token_id,
                "startTs": start_ts,
                "endTs": end_ts,
                "fidelity": fidelity,
            },
        )
        return list(data.get("history") or [])

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(1.5 * (attempt + 1))
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Polymarket official API failed: {last_error}") from last_error


class KalshiOfficialClient:
    def __init__(
        self,
        config: OfficialAPIConfig | None = None,
        base_url: str = KALSHI_BASE,
        retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.session = requests.Session()
        self.config = config or OfficialAPIConfig()
        self._private_key = None
        if self.config.kalshi_private_key_pem:
            self._private_key = serialization.load_pem_private_key(
                self.config.kalshi_private_key_pem.encode("utf-8"),
                password=None,
            )

    def market_candlesticks(
        self,
        market_ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
    ) -> list[dict[str, Any]]:
        series_ticker = series_from_market_ticker(market_ticker)
        data = self._get(
            f"/series/{series_ticker}/markets/{market_ticker}/candlesticks",
            {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "period_interval": period_interval,
            },
        )
        return list(data.get("candlesticks") or [])

    def historical_markets(
        self,
        limit: int = 1000,
        cursor: str | None = None,
        series_ticker: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._get("/historical/markets", params)

    def trades(
        self,
        ticker: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets/trades", params)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=self._headers("GET", urlparse(url).path),
                    timeout=30,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(1.5 * (attempt + 1))
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Kalshi official API failed for {path}: {last_error}") from last_error

    def _headers(self, method: str, path: str) -> dict[str, str]:
        if not self.config.kalshi_api_key_id or self._private_key is None:
            return {}
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{path}".encode("utf-8")
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.config.kalshi_api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
        }


def series_from_market_ticker(market_ticker: str) -> str:
    return market_ticker.split("-", 1)[0]
