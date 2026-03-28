"""
Zoom webhook verification + url_validation support.

Zoom signature verification (recommended):
- Header: x-zm-request-timestamp
- Header: x-zm-signature (format: v0=<hmac_sha256>)
- Message: "v0:{timestamp}:{raw_body}"
- HMAC key: ZOOM_WEBHOOK_SECRET_TOKEN

URL validation event:
- event: "endpoint.url_validation"
- payload.plainToken -> respond with { plainToken, encryptedToken }
- encryptedToken = HMAC_SHA256(plainToken, secret_token)
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ZoomWebhookConfig:
    secret_token: str


def compute_signature(secret_token: str, timestamp: str, raw_body: bytes) -> str:
    msg = f"v0:{timestamp}:".encode("utf-8") + raw_body
    digest = hmac.new(secret_token.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def verify_signature(secret_token: str, timestamp: str, signature_header: str, raw_body: bytes) -> bool:
    if not secret_token or not timestamp or not signature_header:
        return False
    expected = compute_signature(secret_token, timestamp, raw_body)
    # constant-time compare
    return hmac.compare_digest(expected, signature_header)


def url_validation_response(secret_token: str, plain_token: str) -> Tuple[str, str]:
    """
    Returns (plainToken, encryptedToken)
    encryptedToken = HMAC_SHA256(plainToken, secret_token)
    """
    digest = hmac.new(secret_token.encode("utf-8"), plain_token.encode("utf-8"), hashlib.sha256).hexdigest()
    return plain_token, digest

