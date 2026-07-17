"""Sensitive Clinical Bridge — Telemetry agent admin REST router.

Two endpoints, both ADMIN-only, both surface the Plan v1.3 Note 1 safeguards:

    POST /api/admin/sensitive-bridge/auto-disable/{gap_flag}/cancel
        Admin override during the 30-min countdown. Cancels an armed
        auto-disable before commit_after fires. Idempotent: cancelling an
        already-cancelled or never-armed flag returns the current state
        without raising.

    POST /api/admin/sensitive-bridge/feature-flag
        Admin re-enables (or disables) a global gap flag. Re-enabling a
        flag that the telemetry agent auto-disabled REQUIRES fresh
        clinician-reviewed telemetry showing the FP rate is back under
        threshold (Plan v1.3 Note 1 safeguard #3). The gate function
        ``assert_reenable_telemetry_resolved`` lives in
        ``sensitive_bridge_telemetry_agent`` so it can be unit-tested
        without spinning up FastAPI.

Design notes
------------
- ``require_admin`` provides the auth boundary. Per
  ``webauthn-yubikey-security.mdc`` the admin's WebAuthn YubiKey posture is
  enforced globally by the trust enforcer; we don't re-check it here.
- Every mutation writes ONE row to ``sensitive_bridge_log`` with the canonical
  event type (``auto_disable_cancelled`` or ``auto_disable_reenabled``) so
  the auditor can reconstruct the lifecycle.
- Failure to write the audit row is a hard error — the lifecycle event must
  not advance silently.
- Router import is wrapped in main.py's try/except so a missing dependency
  never crashes the backend.

QUANTUM-CRYSTAL-ARCH — Sovereign Standard clinical RED gate.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, validator

from app.services.api_server import require_admin
from app.services.sensitive_bridge_telemetry_agent import (
    ReenableTelemetryUnresolved,
    _AUTO_DISABLEABLE_FLAGS,
    assert_reenable_telemetry_resolved,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sole-clinician promotion gate (migration 214)
# ---------------------------------------------------------------------------
# Reflection delay between the actor's most recent
# `shadow_mode_decision_reviewed` event and the promotion attempt. Enforced
# server-side so a clinician cannot collapse the wait by spoofing client time.
# Required only when the actor's clinician_authorization_type is 'sole_lead'.
# Multi-clinician deployments don't need this delay because the second
# clinician's review acts as the natural reflection gap.
SOLE_CLINICIAN_REFLECTION_DELAY_HOURS = 48

router = APIRouter(
    prefix="/api/admin/sensitive-bridge",
    tags=["sensitive-bridge-admin"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _lookup_authorization_type(conn, actor_username: str) -> str:
    """Return the actor's ``coach_profiles.clinician_authorization_type``.

    Defaults to ``'multi_clinician_team'`` if the row, the column, or the
    table is missing — the safe default forces the strict gate. Migration
    214 owns the schema.
    """
    if not actor_username:
        return "multi_clinician_team"
    try:
        val = await conn.fetchval(
            """
            SELECT clinician_authorization_type
              FROM coach_profiles
             WHERE username = $1
             LIMIT 1
            """,
            actor_username,
        )
    except Exception as e:  # pragma: no cover - defense in depth
        logger.warning(
            "sensitive_bridge_telemetry_api: clinician_authorization_type "
            "lookup failed for actor=%s: %s — defaulting to multi_clinician_team",
            actor_username,
            e,
        )
        return "multi_clinician_team"
    if val == "sole_lead":
        return "sole_lead"
    return "multi_clinician_team"


def _validate_flag(gap_flag: str) -> None:
    if gap_flag not in _AUTO_DISABLEABLE_FLAGS:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "unknown_gap_flag",
                "gap_flag": gap_flag,
                "known_flags_count": len(_AUTO_DISABLEABLE_FLAGS),
            },
        )


async def _log_event(
    conn, *, event_type: str, severity: str, payload: Dict[str, Any], actor: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO sensitive_bridge_log (
            user_id, event_type, event_severity, payload_json,
            recorded_by, access_classification, pii_screened_at
        ) VALUES (
            'system', $1, $2, $3::jsonb, $4, 'admin_only_redacted', NOW()
        )
        """,
        event_type, severity, json.dumps(payload), actor,
    )


# ---------------------------------------------------------------------------
# Endpoint 1 — admin cancel of armed auto-disable
# ---------------------------------------------------------------------------


class CancelAutoDisableBody(BaseModel):
    reason: str = Field(..., min_length=4, max_length=300)

    @validator("reason")
    def _strip(cls, v: str) -> str:  # noqa: N805
        return v.strip()


@router.post("/auto-disable/{gap_flag}/cancel")
async def cancel_auto_disable(
    gap_flag: str,
    body: CancelAutoDisableBody,
    request: Request,
    principal: Dict = Depends(require_admin),
):
    """Admin override: cancel an armed auto-disable before commit_after fires.

    Idempotent. Returns the current state regardless of whether a transition
    occurred. Always emits an audit row when an actual cancel happens.
    """
    _validate_flag(gap_flag)
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    actor = (principal or {}).get("username") or "unknown_admin"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT state, armed_at, commit_after, cancelled_at,
                   fp_snapshot_at_arming
            FROM detector_auto_disable_state
            WHERE gap_flag = $1
            """,
            gap_flag,
        )
        if not row:
            return {
                "gap_flag": gap_flag,
                "state": "idle",
                "cancelled": False,
                "reason": "no_auto_disable_state_for_flag",
            }
        if row["state"] != "armed":
            return {
                "gap_flag": gap_flag,
                "state": row["state"],
                "cancelled": False,
                "reason": f"flag_not_armed_current_state={row['state']}",
            }

        await conn.execute(
            """
            UPDATE detector_auto_disable_state
            SET state = 'idle',
                cancelled_at = NOW(),
                cancelled_by = $2,
                cancellation_reason = $3,
                last_observed_at = NOW()
            WHERE gap_flag = $1
            """,
            gap_flag, actor, body.reason,
        )
        await _log_event(
            conn,
            event_type="auto_disable_cancelled",
            severity="high",
            payload={
                "gap_flag": gap_flag,
                "actor": actor,
                "reason": body.reason,
                "armed_at_iso": row["armed_at"].isoformat() if row["armed_at"] else None,
                "would_have_committed_at_iso": (
                    row["commit_after"].isoformat() if row["commit_after"] else None
                ),
                "snapshot_at_arming": row["fp_snapshot_at_arming"] or {},
            },
            actor=actor,
        )

    return {
        "gap_flag": gap_flag,
        "state": "idle",
        "cancelled": True,
        "actor": actor,
    }


# ---------------------------------------------------------------------------
# Endpoint 2 — admin set feature flag (with resolved-telemetry gate)
# ---------------------------------------------------------------------------


class SetFeatureFlagBody(BaseModel):
    gap_flag: str
    enabled: bool
    reason: str = Field(..., min_length=4, max_length=300)

    @validator("reason")
    def _strip(cls, v: str) -> str:  # noqa: N805
        return v.strip()


@router.post("/feature-flag")
async def set_feature_flag(
    body: SetFeatureFlagBody,
    request: Request,
    principal: Dict = Depends(require_admin),
):
    """Admin sets a global gap flag.

    Re-enabling a flag (`enabled=True`) that was auto-disabled REQUIRES
    fresh telemetry showing the FP rate is back under threshold across a
    fresh clinician-reviewed sample (Plan v1.3 Note 1 safeguard #3).
    Failing the gate returns 409 with the snapshot so the admin can see
    exactly why re-enable is blocked.
    """
    _validate_flag(body.gap_flag)
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    actor = (principal or {}).get("username") or "unknown_admin"
    snapshot: Optional[Dict[str, Any]] = None
    sole_clinician_override = False
    actor_authorization_type = "multi_clinician_team"
    last_review_iso: Optional[str] = None

    if body.enabled:
        try:
            snapshot = await assert_reenable_telemetry_resolved(
                db_pool, body.gap_flag,
            )
        except ReenableTelemetryUnresolved as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "reenable_telemetry_unresolved",
                    "gap_flag": exc.gap_flag,
                    "explanation": exc.reason,
                    "snapshot": exc.snapshot,
                },
            )

        # Sole-clinician 48h reflection delay (migration 214). The check
        # runs AFTER the telemetry-resolved gate so a sole_lead actor still
        # has to clear the same FP-rate floor as everyone else. The single-
        # clinician sign-off is implicit: ``require_admin`` already gates
        # this endpoint to one actor; we just require their review→promote
        # window be at least 48h. Audited as
        # ``sole_clinician_reflection_delay_enforced``.
        async with db_pool.acquire() as conn_auth:
            actor_authorization_type = await _lookup_authorization_type(
                conn_auth, actor,
            )
            if actor_authorization_type == "sole_lead":
                last_review_dt = await conn_auth.fetchval(
                    """
                    SELECT MAX(created_at)
                      FROM skyeye_activity
                     WHERE type = 'shadow_mode_decision_reviewed'
                       AND (
                            content::jsonb->>'reviewed_by' = $1
                            OR content::jsonb->>'gap_flag' = $2
                       )
                    """,
                    actor, body.gap_flag,
                )
                if last_review_dt is None:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "reason": "sole_clinician_no_review_found",
                            "gap_flag": body.gap_flag,
                            "actor": actor,
                            "explanation": (
                                "sole_lead promotion requires a prior "
                                "shadow_mode_decision_reviewed event for "
                                "this gap before the 48h reflection delay "
                                "can begin"
                            ),
                        },
                    )
                # Server-side delta — never trust client clocks.
                now_dt = datetime.now(timezone.utc)
                if last_review_dt.tzinfo is None:
                    last_review_dt = last_review_dt.replace(tzinfo=timezone.utc)
                elapsed = now_dt - last_review_dt
                last_review_iso = last_review_dt.isoformat()
                if elapsed < timedelta(hours=SOLE_CLINICIAN_REFLECTION_DELAY_HOURS):
                    remaining = (
                        timedelta(hours=SOLE_CLINICIAN_REFLECTION_DELAY_HOURS) - elapsed
                    )
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "reason": "sole_clinician_reflection_delay_unmet",
                            "gap_flag": body.gap_flag,
                            "actor": actor,
                            "reviewed_at": last_review_iso,
                            "required_delay_hours": SOLE_CLINICIAN_REFLECTION_DELAY_HOURS,
                            "elapsed_hours": round(
                                elapsed.total_seconds() / 3600.0, 2,
                            ),
                            "remaining_hours": round(
                                remaining.total_seconds() / 3600.0, 2,
                            ),
                        },
                    )
                sole_clinician_override = True

    async with db_pool.acquire() as conn:
        # Patch app_settings.sensitive_bridge_global_gap_flags.{flag} = enabled.
        await conn.execute(
            """
            UPDATE app_settings
            SET setting_value = jsonb_set(
                    COALESCE(setting_value, '{}'::jsonb),
                    ARRAY[$1],
                    $2::jsonb,
                    true
                ),
                updated_at = NOW(),
                updated_by = $3
            WHERE setting_key = 'sensitive_bridge_global_gap_flags'
            """,
            body.gap_flag,
            json.dumps(bool(body.enabled)),
            f"admin:{actor}",
        )

        if body.enabled:
            # If state was 'disabled', transition to 'reenabled' with snapshot.
            await conn.execute(
                """
                UPDATE detector_auto_disable_state
                SET state = 'reenabled',
                    reenabled_at = NOW(),
                    reenabled_by = $2,
                    reenable_telemetry_snapshot = $3::jsonb,
                    last_observed_at = NOW()
                WHERE gap_flag = $1
                  AND state = 'disabled'
                """,
                body.gap_flag, actor, json.dumps(snapshot or {}),
            )
            await _log_event(
                conn,
                event_type="auto_disable_reenabled",
                severity="high",
                payload={
                    "gap_flag": body.gap_flag,
                    "actor": actor,
                    "reason": body.reason,
                    "telemetry_snapshot_satisfying_gate": snapshot or {},
                    "actor_authorization_type": actor_authorization_type,
                    "sole_clinician_override": bool(sole_clinician_override),
                    "reflection_delay_hours_required": (
                        SOLE_CLINICIAN_REFLECTION_DELAY_HOURS
                        if sole_clinician_override else None
                    ),
                    "reviewed_at": last_review_iso if sole_clinician_override else None,
                },
                actor=actor,
            )
        else:
            # Manual disable by admin (not via telemetry agent).
            await conn.execute(
                """
                INSERT INTO detector_auto_disable_state (
                    gap_flag, state, disabled_at, disabled_by, disabled_reason,
                    last_observed_at
                ) VALUES ($1, 'disabled', NOW(), $2, $3, NOW())
                ON CONFLICT (gap_flag) DO UPDATE
                SET state = 'disabled',
                    disabled_at = NOW(),
                    disabled_by = $2,
                    disabled_reason = $3,
                    last_observed_at = NOW()
                """,
                body.gap_flag, actor, f"admin_manual_disable: {body.reason}",
            )
            await _log_event(
                conn,
                event_type="gap_feature_auto_disabled",
                severity="high",
                payload={
                    "gap_flag": body.gap_flag,
                    "actor": actor,
                    "reason": body.reason,
                    "trigger": "admin_manual_disable",
                },
                actor=actor,
            )

    return {
        "gap_flag": body.gap_flag,
        "enabled": body.enabled,
        "actor": actor,
        "reenable_snapshot": snapshot if body.enabled else None,
        "actor_authorization_type": actor_authorization_type,
        "sole_clinician_override": bool(sole_clinician_override),
        "reviewed_at": last_review_iso if sole_clinician_override else None,
        "reflection_delay_hours_required": (
            SOLE_CLINICIAN_REFLECTION_DELAY_HOURS
            if sole_clinician_override else None
        ),
    }


# ---------------------------------------------------------------------------
# Read-only listing — useful for the admin UI / auditor cross-check
# ---------------------------------------------------------------------------


@router.get("/auto-disable")
async def list_auto_disable_state(
    request: Request,
    principal: Dict = Depends(require_admin),
):
    """Return the full lifecycle state of every gap flag's auto-disable row.

    Includes flags with no row yet (state='idle', no timestamps). Useful for
    the admin dashboard and for a cheap auditor cross-check.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT gap_flag, state, armed_at, commit_after, cancelled_at,
                   cancelled_by, disabled_at, disabled_by, reenabled_at,
                   reenabled_by, last_observed_at
            FROM detector_auto_disable_state
            ORDER BY gap_flag
            """,
        )

    seen = {r["gap_flag"]: dict(r) for r in rows}
    out = []
    for flag in _AUTO_DISABLEABLE_FLAGS:
        r = seen.get(flag)
        if r:
            out.append({
                "gap_flag": flag,
                "state": r["state"],
                "armed_at": r["armed_at"].isoformat() if r["armed_at"] else None,
                "commit_after": r["commit_after"].isoformat() if r["commit_after"] else None,
                "cancelled_at": r["cancelled_at"].isoformat() if r["cancelled_at"] else None,
                "cancelled_by": r["cancelled_by"],
                "disabled_at": r["disabled_at"].isoformat() if r["disabled_at"] else None,
                "disabled_by": r["disabled_by"],
                "reenabled_at": r["reenabled_at"].isoformat() if r["reenabled_at"] else None,
                "reenabled_by": r["reenabled_by"],
                "last_observed_at": (
                    r["last_observed_at"].isoformat() if r["last_observed_at"] else None
                ),
            })
        else:
            out.append({
                "gap_flag": flag,
                "state": "idle",
                "armed_at": None,
                "commit_after": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "disabled_at": None,
                "disabled_by": None,
                "reenabled_at": None,
                "reenabled_by": None,
                "last_observed_at": None,
            })
    return {"flags": out, "count": len(out)}


__all__ = ["router"]
