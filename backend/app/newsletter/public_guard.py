# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch public-route guards
"""Offline-safe helpers for Story Library + public newsletter endpoints."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request

_SLUG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,118}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-=]{16,128}$")
_UTM_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

ALLOWED_SOURCES = frozenset(
    {
        "web",
        "story_library",
        "library",
        "squarespace",
        "contact_form",
        "share",
        "cta",
        "account",
    }
)
ALLOWED_SHARE_CHANNELS = frozenset(
    {"x", "twitter", "facebook", "linkedin", "whatsapp", "email", "sms", "link"}
)
ALLOWED_HERO_HOSTS = frozenset(
    {
        "api.sovereignsanctuary.net",
        "app.sovereignsanctuary.net",
    }
)

_mem_hits: Dict[str, List[float]] = {}
_MEM_KEYS_MAX = 20000

HTML_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "img-src https: data:; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
}


def html_attr(value: Optional[str]) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def valid_slug(slug: str) -> bool:
    return bool(slug and _SLUG_RE.match(slug))


def valid_token(raw: str) -> bool:
    return bool(raw and _TOKEN_RE.match(raw))


def valid_uuid(raw: str) -> bool:
    return bool(raw and _UUID_RE.match(raw))


def sanitize_utm(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()[:64]
    if not v:
        return None
    return v if _UTM_RE.match(v) else None


def sanitize_source(value: Optional[str]) -> str:
    v = (value or "web").strip().lower()[:40]
    return v if v in ALLOWED_SOURCES else "web"


def sanitize_ref(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()[:120]
    if not v:
        return None
    return v if valid_slug(v) else None


def sanitize_share_channel(value: Optional[str]) -> str:
    v = (value or "link").strip().lower()[:32]
    return v if v in ALLOWED_SHARE_CHANNELS else "link"


def safe_http_url(url: Optional[str], *, require_known_host: bool = False) -> str:
    u = (url or "").strip()
    if not u or len(u) > 500:
        return ""
    if any(c in u for c in ('"', "'", "<", ">", "`", "\n", "\r", "\x00")):
        return ""
    try:
        parsed = urlparse(u)
    except Exception:
        return ""
    if parsed.scheme not in ("https", "http"):
        return ""
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        return ""
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    if require_known_host and host not in ALLOWED_HERO_HOSTS:
        return ""
    return u


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def public_client_ip(request: Request) -> str:
    """Prefer Cloudflare's connecting IP; do not trust arbitrary spoofed chains."""
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if is_ip(cf):
        return cf
    real = (request.headers.get("x-real-ip") or "").strip()
    if is_ip(real):
        return real
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if is_ip(xff):
        return xff
    return request.client.host if request.client else "unknown"


def memory_over_limit(key: str, limit: int, window_s: int) -> bool:
    """True when this hit exceeds the window (caller should 429)."""
    now = time.time()
    hits = [t for t in _mem_hits.get(key, []) if now - t < window_s]
    hits.append(now)
    _mem_hits[key] = hits
    if len(_mem_hits) > _MEM_KEYS_MAX:
        stale = [k for k, ts in _mem_hits.items() if not ts or ts[-1] < now - 3600]
        for k in stale[:4000]:
            _mem_hits.pop(k, None)
    return len(hits) > limit


def email_rate_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:24]


def honeypot_tripped(website: Optional[str]) -> bool:
    return bool((website or "").strip())


def unsubscribe_confirm_html(token: str, sid: Optional[str] = None) -> str:
    sid_input = ""
    if sid and valid_uuid(sid):
        sid_input = f'<input type="hidden" name="sid" value="{html_attr(sid)}">'
    t = html_attr(token if valid_token(token) else "")
    return (
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Unsubscribe</title></head>"
        "<body style=\"background:#050505;color:#E8D5A3;font-family:Georgia,serif;padding:40px;\">"
        "<h1>Unsubscribe</h1>"
        "<p>Confirm you want to leave Little Nate Dispatch.</p>"
        '<form method="POST" action="/api/newsletter/unsubscribe">'
        f'<input type="hidden" name="t" value="{t}">'
        f"{sid_input}"
        '<button type="submit" style="background:#C9A962;border:0;padding:12px 20px;">Unsubscribe</button>'
        "</form></body></html>"
    )


async def enforce_rate_limit(
    redis,
    *,
    redis_key: str,
    memory_key: str,
    limit: int,
    window_s: int,
) -> None:
    """Redis first; memory fallback if Redis is down. Never fail open."""
    if redis is not None:
        try:
            n = await redis.incr(redis_key)
            if n == 1:
                await redis.expire(redis_key, window_s)
            if n > limit:
                raise HTTPException(429, "Too many requests")
            return
        except HTTPException:
            raise
        except Exception:
            pass
    if memory_over_limit(memory_key, limit, window_s):
        raise HTTPException(429, "Too many requests")


async def confirm_cooldown_active(redis, email: str, window_s: int = 1800) -> bool:
    """True if a confirm mail was already sent inside the window."""
    ek = email_rate_key(email)
    rkey = f"newsletter:confirm_cd:{ek}"
    mkey = f"mem:confirm_cd:{ek}"
    if redis is not None:
        try:
            ok = await redis.set(rkey, "1", ex=window_s, nx=True)
            return not bool(ok)
        except Exception:
            pass
    if memory_over_limit(mkey, 1, window_s):
        return True
    return False
