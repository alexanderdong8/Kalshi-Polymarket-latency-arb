from __future__ import annotations

import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def kalshi_headers(key_id: str, private_key_pem: str, method: str, path: str) -> dict[str, str]:
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
