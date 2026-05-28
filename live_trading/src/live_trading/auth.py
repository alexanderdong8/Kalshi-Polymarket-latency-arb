from __future__ import annotations

import base64
import time
from pathlib import Path


def _timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def kalshi_headers(
    key_id: str,
    private_key_pem: str,
    method: str,
    path: str,
) -> dict[str, str]:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    timestamp = _timestamp_ms()
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    message = f"{timestamp}{method.upper()}{path}".encode()
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "Content-Type": "application/json",
    }


def polymarket_us_headers(
    key_id: str,
    secret_key: str,
    method: str,
    path: str,
) -> dict[str, str]:
    from cryptography.hazmat.primitives.asymmetric import ed25519

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


def read_private_key(path: str | None, inline_pem: str | None) -> str | None:
    if inline_pem:
        return inline_pem.replace("\\n", "\n")
    if path:
        return Path(path).expanduser().read_text(encoding="utf-8")
    return None
