"""Bridge-local Guardian Fibre and Pipeline Drum.

The backend hive dict is not in this process. These are the taps the bridge
already calls. A score is recorded and is not used to reject a login.
The drum does not write the backend baseline tables. # SOVEREIGN-VOICE
"""
from __future__ import annotations

_guardian = None
_drum = None
_tapped = False


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


async def bridge_login_allowed(db_pool, username, role, ip_address, user_agent):
    """Lock from login_attempts after the latest success. An empty name or a check error allows the password check."""
    ident = (username or "").strip()
    if not ident or db_pool is None:
        return {"allowed": True, "reason": "skip", "lockout_remaining_sec": 0, "remaining_attempts": 5}
    try:
        row = await db_pool.fetchrow(
            """SELECT COUNT(*) AS fail_count, MAX(created_at) AS last_attempt
               FROM login_attempts
               WHERE identifier = $1
                 AND success = FALSE
                 AND created_at > NOW() - INTERVAL '3 minutes'
                 AND created_at > COALESCE(
                       (SELECT MAX(created_at) FROM login_attempts
                        WHERE identifier = $1 AND success = TRUE),
                       '-infinity'::timestamptz)""",
            ident,
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
