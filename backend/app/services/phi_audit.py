"""PHI read audit helper (Slice 6a of Bee HIV+ privacy plan).

Every read of Protected Health Information should call ``log_phi_read`` after
the response body is assembled so the audit row captures exactly which fields
the caller received. HIPAA §164.528 requires this accounting to be retained
for at least 6 years.

Design rules
------------
1. Fail-soft on infrastructure errors. An audit failure must NOT block a
   legitimate read — it logs a warning and returns False. Callers do not
   need to try/except this helper.
2. Fail-closed on the feature flag. When ``ENABLE_PHI_READ_LOG`` is off,
   the helper is a no-op returning False, so wiring endpoints early is
   safe.
3. Append-only. The DB has triggers that reject UPDATE/DELETE. To correct
   an entry, call ``log_correction`` which inserts a new row that points
   at the original via ``correction_of_id``.
4. No PHI in the log itself. ``fields`` is the *names* of fields the caller
   received (e.g. ``["trauma_history"]``), never their values.

The helper is dormant by default. Wiring into individual PHI endpoints
happens in a follow-up commit.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

_FLAG_ENV = "ENABLE_PHI_READ_LOG"
_VALID_ROLES = {"ADMIN", "COACH", "CLIENT", "SYSTEM"}


def is_enabled() -> bool:
    """Return True iff the PHI read log is turned on."""
    return os.getenv(_FLAG_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _coerce_fields(fields: Optional[Iterable[Any]]) -> list[str]:
    if not fields:
        return []
    out: list[str] = []
    for f in fields:
        if f is None:
            continue
        s = str(f).strip()
        if s:
            out.append(s)
    # Cap payload to avoid a runaway serializer inflating audit rows.
    return out[:64]


async def log_phi_read(
    db_pool: Any,
    *,
    actor_username: str,
    actor_role: str,
    resource: str,
    endpoint: str,
    subject_username: Optional[str] = None,
    subject_user_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    method: str = "GET",
    fields: Optional[Iterable[Any]] = None,
    request_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    mfa_verified: bool = False,
    program_id: Optional[str] = None,
) -> bool:
    """Write one PHI-read audit row. Returns True on success.

    All keyword arguments except ``actor_username``, ``actor_role``,
    ``resource``, and ``endpoint`` are optional. Missing subject fields are
    valid (e.g. a directory listing that doesn't target one person).
    """
    if not is_enabled():
        return False
    if db_pool is None:
        logger.warning("phi_audit: db_pool unavailable, skipping log for %s -> %s", actor_username, endpoint)
        return False
    if not actor_username or not actor_role or not resource or not endpoint:
        logger.warning("phi_audit: missing required field, skipping log")
        return False
    role = str(actor_role).upper().strip()
    if role not in _VALID_ROLES:
        logger.warning("phi_audit: unknown actor_role=%s, coercing to SYSTEM", role)
        role = "SYSTEM"

    fields_list = _coerce_fields(fields)

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO phi_read_log (
                    actor_user_id, actor_username, actor_role,
                    subject_user_id, subject_username,
                    resource, endpoint, method, fields,
                    request_id, ip_address, user_agent,
                    mfa_verified, program_id
                ) VALUES (
                    $1::uuid, $2, $3,
                    $4::uuid, $5,
                    $6, $7, $8, $9::jsonb,
                    $10, $11::inet, $12,
                    $13, $14
                )
                """,
                actor_user_id,
                actor_username,
                role,
                subject_user_id,
                subject_username,
                resource,
                endpoint,
                (method or "GET").upper(),
                _json_dumps(fields_list),
                request_id,
                ip_address,
                user_agent,
                bool(mfa_verified),
                program_id,
            )
        return True
    except Exception as exc:
        # Never block a legitimate read on an audit-side failure.
        logger.warning(
            "phi_audit: insert failed (actor=%s subject=%s resource=%s): %s",
            actor_username, subject_username, resource, exc,
        )
        return False


async def log_correction(
    db_pool: Any,
    *,
    original_id: int,
    actor_username: str,
    actor_role: str,
    note: str,
    resource: str,
    endpoint: str,
    subject_username: Optional[str] = None,
) -> bool:
    """Append a correction row that references an earlier phi_read_log row.

    Used when we discover an earlier audit row was wrong (e.g. wrong subject
    logged). The original row stays untouched — this is HIPAA-compliant
    corrections-via-addendum, not mutation.
    """
    if not is_enabled():
        return False
    if db_pool is None or not note or original_id is None:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO phi_read_log (
                    actor_username, actor_role, resource, endpoint,
                    subject_username, correction_of_id, correction_note
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                actor_username,
                (actor_role or "SYSTEM").upper(),
                resource,
                endpoint,
                subject_username,
                int(original_id),
                str(note)[:2000],
            )
        return True
    except Exception as exc:
        logger.warning("phi_audit: correction insert failed: %s", exc)
        return False


def _json_dumps(value: Any) -> str:
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "[]"
