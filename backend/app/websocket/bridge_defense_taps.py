"""Bridge-local Guardian Fibre and Pipeline Drum.

The backend hive dict is not in this process. These are the taps the bridge
already calls. A score is recorded and is not used to reject a login.
The drum does not write the backend baseline tables. # SOVEREIGN-VOICE
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time

_guardian = None
_drum = None
_tapped = False
_login_redis = None
_login_client = None
_login_client_lock = threading.Lock()


def bridge_guardian(db_pool):
    """Fibre for this process. No pool means no observation and no login change."""
    global _guardian
    if db_pool is None:
        return None
    if _guardian is None:
        from app.services.guardian_fibre import GuardianFibre
        _guardian = GuardianFibre(db_pool)
        print(">>> [HIVE] Bridge guardian fibre ready", flush=True)
    return _guardian


async def bridge_drum():
    """In-process sensor for websocket frames. No shared baseline writes."""
    global _drum
    if _drum is None:
        from app.services.pipeline_drum import PipelineDrum
        drum = PipelineDrum(db_pool=None)
        await drum.start()
        _drum = drum
        print(">>> [HIVE] Bridge pipeline drum ready", flush=True)
    return _drum


def _login_subject(username, ip_address) -> str:
    """Typed names fold case. A blank name is counted by caller address only."""
    ident = (username or "").strip().lower()
    if ident:
        return ident
    ip = (ip_address or "").strip()
    if ip and ip != "unknown":
        return f"ip:{ip}"
    return ""


def _dedicated_login_client():
    """Redis client for the slow-failure counter. Not the token client."""
    global _login_client
    if _login_client is not None:
        return _login_client
    with _login_client_lock:
        if _login_client is None:
            import redis
            _login_client = redis.Redis(
                host=os.environ.get("REDIS_HOST", "redis"),
                port=int(os.environ.get("REDIS_PORT", "6379")),
                password=os.environ.get("REDIS_PASSWORD") or None,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=True,
            )
        return _login_client


def _login_counter_client():
    if _login_redis is False:
        return None
    if _login_redis is not None:
        return _login_redis
    if os.getenv("HIVE_LOGIN_FAILS_REDIS", "true").lower() not in ("1", "true", "yes"):
        return None
    return _dedicated_login_client()


def _login_keys(subject: str):
    prefix = os.environ.get("REDIS_KEY_PREFIX", "nate")
    env = os.environ.get("ENVIRONMENT", "prod")
    digest = hashlib.sha256(subject.encode()).hexdigest()[:32]
    base = f"{prefix}:{env}:hive:login_fails:{digest}"
    return base, base + ":lock"


def _login_redis_op(client, mode: str, fail_key: str, lock_key: str, now: float) -> int:
    """15-minute miss count. Five misses lock for 3 minutes, then the count starts over."""
    if mode == "clear":
        client.delete(fail_key, lock_key)
        return 0
    ttl = int(client.ttl(lock_key) or -1)
    if mode == "read":
        return ttl if ttl > 0 else 0
    pipe = client.pipeline()
    pipe.zadd(fail_key, {f"{now:.6f}-{time.monotonic_ns()}": now})
    pipe.zremrangebyscore(fail_key, 0, now - 900)
    pipe.zcard(fail_key)
    pipe.expire(fail_key, 960)
    count = int(pipe.execute()[2])
    if count >= 5:
        client.delete(fail_key)
        client.set(lock_key, "1", ex=180)
        return -180
    return count


async def _login_redis_call(subject: str, mode: str) -> int:
    client = _login_counter_client()
    if client is None or not subject:
        return 0
    fail_key, lock_key = _login_keys(subject)
    try:
        return await asyncio.to_thread(
            _login_redis_op, client, mode, fail_key, lock_key, time.time(),
        )
    except Exception as exc:
        print(f">>> [LoginGuardian] Redis counter skipped: {exc}", flush=True)
        return 0


async def note_login_failure(username, ip_address) -> None:
    """Remember one miss for 15 minutes. The password is not stored."""
    await _login_redis_call(_login_subject(username, ip_address), "add")


async def note_login_success(username, ip_address) -> None:
    """A correct password clears the slow miss count."""
    await _login_redis_call(_login_subject(username, ip_address), "clear")


async def bridge_login_allowed(db_pool, username, role, ip_address, user_agent):
    """Lock from login_attempts after the latest success. A check error allows the password check."""
    ident = (username or "").strip()
    subject = _login_subject(username, ip_address)
    if not subject:
        return {"allowed": True, "reason": "skip", "lockout_remaining_sec": 0, "remaining_attempts": 5}
    remain = await _login_redis_call(subject, "read")
    if remain > 0:
        return {
            "allowed": False, "reason": "account_locked",
            "lockout_remaining_sec": remain, "remaining_attempts": 0,
        }
    if db_pool is None:
        return {"allowed": True, "reason": "skip", "lockout_remaining_sec": 0, "remaining_attempts": 5}
    query_ident = ident or subject
    try:
        row = await db_pool.fetchrow(
            """SELECT COUNT(*) AS fail_count, MAX(created_at) AS last_attempt
               FROM login_attempts
               WHERE LOWER(identifier) = LOWER($1)
                 AND success = FALSE
                 AND created_at > NOW() - INTERVAL '3 minutes'
                 AND created_at > COALESCE(
                       (SELECT MAX(created_at) FROM login_attempts
                        WHERE LOWER(identifier) = LOWER($1) AND success = TRUE),
                       '-infinity'::timestamptz)""",
            query_ident,
        )
        fail_count = int(row["fail_count"] or 0) if row else 0
        last = row["last_attempt"] if row else None
        if fail_count < 5 or last is None:
            return {
                "allowed": True, "reason": "ok", "lockout_remaining_sec": 0,
                "remaining_attempts": max(0, 5 - fail_count),
            }
        from datetime import datetime, timedelta, timezone
        if getattr(last, "tzinfo", None) is None:
            last = last.replace(tzinfo=timezone.utc)
        minutes = 3 * min(max(1, fail_count // 5), 8)
        remain = int((last + timedelta(minutes=minutes) - datetime.now(timezone.utc)).total_seconds())
        if remain <= 0:
            return {"allowed": True, "reason": "ok", "lockout_remaining_sec": 0, "remaining_attempts": 5}
        return {
            "allowed": False, "reason": "account_locked",
            "lockout_remaining_sec": remain, "remaining_attempts": 0,
        }
    except Exception as exc:
        print(f">>> [LoginGuardian] Non-blocking check error: {exc}", flush=True)
        return {"allowed": True, "reason": "check_error", "lockout_remaining_sec": 0, "remaining_attempts": 5}


def note_drum_tap(drum, endpoint: str, payload: bytes) -> None:
    """Record one websocket frame. The body is not stored."""
    global _tapped
    drum.tap_request(
        endpoint=endpoint,
        method="WS",
        status_code=200,
        response_time_ms=0,
        payload=payload or b"",
    )
    if not _tapped:
        _tapped = True
        print(">>> [HIVE] Bridge pipeline drum tapped", flush=True)
