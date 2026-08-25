"""Cohort enrollment API.

Users redeem a code to opt into a privacy-tightened cohort (e.g. ``bee_hiv_plus``).
Redemption stamps ``users.program_id`` which downstream policies consume:

- ``cohort_scoped`` retention (30-day override) — see ``retention_policy``.
- Cohort-aware MFA freshness window — see ``mfa_gate``.
- Crystal program isolation — the DB trigger from migration 414 auto-stamps
  ``nate_intelligence_crystals.program_id`` on insert once the user is in a cohort.
- Coach observation write-side tenancy check — see ``crystal_recall_bridge``.

Endpoints
---------
- ``POST /api/enrollment/redeem``     — authenticated user redeems a code.
- ``GET  /api/enrollment/status``     — authenticated user reads their cohort.
- ``POST /api/enrollment/codes``      — admin mints a code.
- ``GET  /api/enrollment/codes``      — admin lists codes + usage.
- ``POST /api/enrollment/codes/{id}/revoke`` — admin revokes a code.

Feature flag
------------
``ENABLE_ENROLLMENT_API`` (default false during rollout). When off, all
endpoints return 503 so the surface can be shipped dark and turned on per
environment. Turning the flag on is safe because the migration (420) is
additive and the DB tables sit idle until a code is minted.

Fail-closed rules
-----------------
- Unknown ``program_id`` on a code ⇒ 500 misconfiguration (caught at mint time
  too, so this should only fire if the STRICT_COHORT_PROGRAM_IDS set shrinks
  after codes were minted).
- User already in a cohort ⇒ 409 conflict. Cohort transitions must go through
  an admin path (not part of this slice; see roadmap).
- Code revoked / expired / exhausted ⇒ 410 gone.
- Duplicate redemption by the same user ⇒ 409 conflict (relies on the
  ``enrollment_redemptions_unique (code_id, user_id)`` constraint).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import get_current_user, require_admin
from app.services.cohort import is_known_cohort, normalize_program_id

logger = logging.getLogger("nate.enrollment_api")

router = APIRouter(prefix="/api/enrollment", tags=["enrollment"])

_ENV_FLAG = "ENABLE_ENROLLMENT_API"

# --------------------------------------------------------------------------- #
# Rate limiting (in-memory, per-process)                                      #
# --------------------------------------------------------------------------- #
# Redemption is a code-guessing-adjacent surface even though the caller is
# authenticated: a compromised low-privilege account could still try to
# brute-force cohort codes. Cap redemption attempts per-IP.
#
# In-memory only (per bridge/backend process). This is a "reasonable minimum"
# — a determined attacker with a botnet defeats it, but the codes are also
# limited by ``max_uses`` and ``expires_at`` on ``enrollment_codes``.
_redeem_hits: Dict[str, List[float]] = {}
_REDEEM_RATE_WINDOW_S = 60
_REDEEM_RATE_MAX = 5  # attempts per window per key


def _redeem_rate_limited(key: str) -> bool:
    """Return True if the caller has exceeded the redeem rate budget.

    Uses a rolling window; entries older than ``_REDEEM_RATE_WINDOW_S`` are
    dropped on each call.
    """
    now = time.time()
    hits = [t for t in _redeem_hits.get(key, []) if now - t < _REDEEM_RATE_WINDOW_S]
    hits.append(now)
    _redeem_hits[key] = hits
    return len(hits) > _REDEEM_RATE_MAX


def _redeem_rate_key(request: Request, username: str) -> str:
    """Compose the rate-limit key.

    Prefer IP+username so a shared NAT egress doesn't lock out unrelated users,
    but if IP is unavailable fall back to username-only.
    """
    ip = "unknown"
    try:
        if request.client and request.client.host:
            ip = request.client.host
    except Exception:
        pass
    return f"{ip}|{username}"


def _redeem_rate_reset_for_tests() -> None:
    """Test hook: clear the in-memory rate state between test runs."""
    _redeem_hits.clear()


def _is_enabled() -> bool:
    """Return True iff the API is enabled for this deploy."""
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _require_enabled() -> None:
    if not _is_enabled():
        raise HTTPException(503, "Enrollment API disabled")


def _require_db(request: Request):
    db = getattr(request.app.state, "db_pool", None)
    if db is None:
        raise HTTPException(503, "Database unavailable")
    return db


# --------------------------------------------------------------------------- #
# Request / response models                                                   #
# --------------------------------------------------------------------------- #


class RedeemRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=128)


class CreateCodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=128)
    program_id: str = Field(..., min_length=1, max_length=64)
    max_uses: Optional[int] = Field(default=None, gt=0)
    expires_at: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- #
# User-facing endpoints                                                       #
# --------------------------------------------------------------------------- #


@router.get("/status")
async def enrollment_status(request: Request, user: Dict = Depends(get_current_user)):
    """Return the caller's current cohort membership (or ``None``)."""
    _require_enabled()
    db = _require_db(request)
    username = user.get("username")
    if not username:
        raise HTTPException(400, "username missing from principal")

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT program_id FROM users WHERE username = $1", username
        )
    program_id = row["program_id"] if row else None
    return {"username": username, "program_id": program_id}


@router.post("/redeem")
async def redeem_code(
    req: RedeemRequest, request: Request, user: Dict = Depends(get_current_user)
):
    """Redeem a cohort enrollment code.

    Atomic: verify code + insert redemption + increment uses + set
    ``users.program_id`` all inside one transaction. Concurrent redemptions
    on the same code are serialized by ``SELECT ... FOR UPDATE``.
    """
    _require_enabled()
    db = _require_db(request)
    username = user.get("username")
    if not username:
        raise HTTPException(400, "username missing from principal")

    code_str = req.code.strip()
    if not code_str:
        raise HTTPException(400, "code required")

    # Rate limit BEFORE any DB work so a flood can't drive contention on
    # ``enrollment_codes`` row locks. Log 429s so security can spot abuse.
    rl_key = _redeem_rate_key(request, username)
    if _redeem_rate_limited(rl_key):
        logger.warning(
            "enrollment.redeem rate-limited: key=%s username=%s", rl_key, username
        )
        raise HTTPException(429, "Too many enrollment attempts; try again shortly.")

    # Best-effort audit context (never fatal).
    src_ip: Optional[str] = None
    try:
        src_ip = request.client.host if request.client else None
    except Exception:
        src_ip = None
    ua = request.headers.get("user-agent")

    async with db.acquire() as conn:
        async with conn.transaction():
            code_row = await conn.fetchrow(
                """SELECT id, program_id, max_uses, uses, expires_at, revoked_at
                     FROM enrollment_codes
                    WHERE code = $1
                    FOR UPDATE""",
                code_str,
            )
            if not code_row:
                raise HTTPException(404, "Invalid enrollment code")

            program_id = normalize_program_id(code_row["program_id"])
            if program_id is None or not is_known_cohort(program_id):
                logger.error(
                    "enrollment: code %s references unknown program_id=%r",
                    code_str,
                    code_row["program_id"],
                )
                raise HTTPException(500, "Enrollment code misconfigured")

            now = datetime.now(timezone.utc)
            if code_row["revoked_at"] is not None:
                raise HTTPException(410, "Enrollment code has been revoked")
            if code_row["expires_at"] is not None and code_row["expires_at"] <= now:
                raise HTTPException(410, "Enrollment code has expired")
            if (
                code_row["max_uses"] is not None
                and code_row["uses"] >= code_row["max_uses"]
            ):
                raise HTTPException(410, "Enrollment code exhausted")

            user_row = await conn.fetchrow(
                "SELECT id, program_id FROM users WHERE username = $1", username
            )
            if not user_row:
                raise HTTPException(404, "User not found")
            if user_row["program_id"] is not None:
                # Cohort transitions are admin-only; not part of this slice.
                raise HTTPException(
                    409,
                    {
                        "code": "ALREADY_ENROLLED",
                        "current_program_id": user_row["program_id"],
                    },
                )

            try:
                await conn.execute(
                    """INSERT INTO enrollment_redemptions
                         (code_id, user_id, username, program_id, source_ip, user_agent)
                         VALUES ($1, $2, $3, $4, $5::inet, $6)""",
                    code_row["id"],
                    user_row["id"],
                    username,
                    program_id,
                    src_ip,
                    ua,
                )
            except Exception as exc:
                # Unique(code_id, user_id) violation = duplicate redemption.
                msg = str(exc).lower()
                if "enrollment_redemptions_unique" in msg or "unique" in msg:
                    raise HTTPException(409, "Code already redeemed by this user")
                raise

            await conn.execute(
                "UPDATE enrollment_codes SET uses = uses + 1 WHERE id = $1",
                code_row["id"],
            )
            await conn.execute(
                """UPDATE users SET
                     program_id = $1::text,
                     profile_data = jsonb_set(
                         COALESCE(profile_data, '{}'::jsonb),
                         '{program_id}',
                         to_jsonb($1::text)
                     )
                   WHERE id = $2""",
                program_id,
                user_row["id"],
            )

    try:
        from app.services.program_isolation import invalidate_user_cache
        invalidate_user_cache(username)
    except Exception:
        pass
    logger.info(
        "enrollment: %s redeemed code=%s into program=%s",
        username,
        code_str,
        program_id,
    )
    return {
        "status": "enrolled",
        "program_id": program_id,
        "redeemed_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- #
# Admin endpoints                                                             #
# --------------------------------------------------------------------------- #


@router.post("/codes", dependencies=[Depends(require_admin)])
async def create_code(
    req: CreateCodeRequest, request: Request, user: Dict = Depends(require_admin)
):
    """Mint a new enrollment code for a known cohort."""
    _require_enabled()
    db = _require_db(request)

    program_id = normalize_program_id(req.program_id)
    if program_id is None or not is_known_cohort(program_id):
        raise HTTPException(400, f"Unknown program_id: {req.program_id!r}")

    created_by = user.get("username") or user.get("hardware_id") or "admin"
    async with db.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO enrollment_codes
                     (code, program_id, max_uses, expires_at, created_by, notes)
                     VALUES ($1, $2, $3, $4, $5, $6)
                     RETURNING id, code, program_id, max_uses, expires_at, created_at""",
                req.code.strip(),
                program_id,
                req.max_uses,
                req.expires_at,
                created_by,
                req.notes,
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(409, "Code already exists")
            raise

    return {
        "id": str(row["id"]),
        "code": row["code"],
        "program_id": row["program_id"],
        "max_uses": row["max_uses"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "created_at": row["created_at"].isoformat(),
        "created_by": created_by,
    }


@router.get("/codes", dependencies=[Depends(require_admin)])
async def list_codes(
    request: Request, user: Dict = Depends(require_admin)
) -> Dict[str, Any]:
    """List all enrollment codes with usage counters."""
    _require_enabled()
    db = _require_db(request)
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, code, program_id, max_uses, uses, expires_at,
                      revoked_at, created_by, notes, created_at
                 FROM enrollment_codes
                 ORDER BY created_at DESC"""
        )

    codes: List[Dict[str, Any]] = []
    for r in rows:
        codes.append(
            {
                "id": str(r["id"]),
                "code": r["code"],
                "program_id": r["program_id"],
                "max_uses": r["max_uses"],
                "uses": r["uses"],
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None,
                "created_by": r["created_by"],
                "notes": r["notes"],
                "created_at": r["created_at"].isoformat(),
            }
        )
    return {"codes": codes, "count": len(codes)}


@router.post("/codes/{code_id}/revoke", dependencies=[Depends(require_admin)])
async def revoke_code(
    code_id: str, request: Request, user: Dict = Depends(require_admin)
):
    """Revoke an enrollment code. Existing redemptions are untouched."""
    _require_enabled()
    db = _require_db(request)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT revoked_at FROM enrollment_codes WHERE id = $1::uuid", code_id
        )
        if not row:
            raise HTTPException(404, "Code not found")
        if row["revoked_at"] is not None:
            raise HTTPException(409, "Code already revoked")
        await conn.execute(
            "UPDATE enrollment_codes SET revoked_at = NOW() WHERE id = $1::uuid",
            code_id,
        )
    return {"status": "revoked", "id": code_id}


__all__ = ["router", "_redeem_rate_reset_for_tests"]
