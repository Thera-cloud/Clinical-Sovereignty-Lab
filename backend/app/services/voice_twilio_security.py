"""
Twilio voice webhook security: signature validation + light IP rate limiting.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from starlette.requests import Request

logger = logging.getLogger("nate.voice_security")

# In-memory rate limit: client IP -> (count, window_start_ts)
_rate_buckets: Dict[str, Tuple[int, float]] = {}
_RATE_MAX = int(os.getenv("TWILIO_VOICE_RATE_LIMIT_PER_MIN", "120"))
_RATE_WINDOW = 60.0


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_voice_webhook_rate_limit(request: Request) -> bool:
    """Return True if under limit, False if should reject (429)."""
    ip = _client_ip(request)
    now = time.time()
    count, start = _rate_buckets.get(ip, (0, now))
    if now - start > _RATE_WINDOW:
        count, start = 0, now
    count += 1
    _rate_buckets[ip] = (count, start)
    if count > _RATE_MAX:
        logger.warning("Twilio voice rate limit exceeded ip=%s count=%s", ip, count)
        return False
    return True


def public_webhook_url_for_signature(request: Request, public_url: Optional[str]) -> str:
    """
    Twilio signs the full URL (including query string). Behind nginx/Cloudflare,
    str(request.url) may be http://127.0.0.1/... or wrong scheme — verification fails.

    Pass the exact public URL configured in Twilio (e.g. TWILIO_VOICE_WEBHOOK_URL);
    we append the incoming query string so dynamic params (e.g. user_id on twiml) still match.
    """
    pu = (public_url or "").strip()
    if not pu:
        return str(request.url)
    q = str(request.url.query or "").strip()
    if not q:
        return pu
    return f"{pu}?{q}" if "?" not in pu else f"{pu}&{q}"


def twilio_signature_valid(
    request: Request,
    form_data: Dict[str, Any],
    *,
    auth_token: str,
    request_url: Optional[str] = None,
) -> bool:
    """
    Validate X-Twilio-Signature using the full public URL Twilio posted to.

    Prefer request_url=... (or pass via public_webhook_url_for_signature) so validation
    matches Twilio regardless of reverse-proxy rewriting. Falls back to str(request.url).

    Set TWILIO_SKIP_SIGNATURE_VERIFY=true only in local dev behind broken tunnels.
    Must remain unset/false in production (DigitalOcean, compose prod, etc.).
    """
    if os.getenv("TWILIO_SKIP_SIGNATURE_VERIFY", "").lower() in ("1", "true", "yes"):
        logger.warning("Twilio signature verification SKIPPED (TWILIO_SKIP_SIGNATURE_VERIFY)")
        return True
    if not auth_token:
        logger.error("TWILIO_AUTH_TOKEN missing — cannot verify Twilio signature")
        return False
    try:
        from twilio.request_validator import RequestValidator
    except ImportError:
        logger.error("twilio package missing RequestValidator")
        return False

    validator = RequestValidator(auth_token)
    url = request_url if request_url else str(request.url)
    # Twilio signs the exact URL; normalize if needed
    signature = request.headers.get("X-Twilio-Signature") or request.headers.get("x-twilio-signature")
    if not signature:
        logger.warning("Missing X-Twilio-Signature header")
        return False
    ok = validator.validate(url, form_data, signature)
    if not ok:
        logger.warning("Twilio signature validation failed url=%s", url[:120])
    return bool(ok)
