from __future__ import annotations

import base64
import time

from cryptography.hazmat.primitives.asymmetric import ed25519


def _timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def polymarket_us_headers(key_id: str, secret_key: str, method: str, path: str) -> dict[str, str]:
    timestamp = _timestamp_ms()
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret_key)[:32])
    message = f"{timestamp}{method.upper()}{path}".encode()
    signature = base64.b64encode(private_key.sign(message)).decode()
    return {
        "X-PM-Access-Key": key_id,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
        "Content-Type": "application/json",
    }
