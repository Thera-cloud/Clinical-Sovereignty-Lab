"""
Voice Identity API — REST endpoints for enrollment, consent, and identity management.

Provides:
- Voice enrollment initiation and status
- Consent management (BIPA, COPPA/FERPA)
- Identity inference history
- Drift flag review
- Institutional tenant management
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("nate.voice_identity_api")

router = APIRouter(prefix="/api/voice-identity", tags=["voice-identity"])


class EnrollmentStartRequest(BaseModel):
    username: str
    tenant_id: str = "default"


class ConsentInitiateRequest(BaseModel):
    username: str
    tenant_id: str = "default"
    consent_type: str = "voice_enrollment"
    phone: str


class ParentalConsentRequest(BaseModel):
    minor_username: str
    parent_username: str
    tenant_id: str = "default"
    parent_phone: str


class VouchRequest(BaseModel):
    tenant_id: str
    user_ids: list


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok", "service": "voice-identity"}


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

@router.get("/enrollment/{username}")
async def get_enrollment_status(username: str, request: Request):
    """Get a user's voice enrollment profile status."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"enrolled": False, "reason": "no_db"}

    try:
        row = await db.fetchrow(
            """SELECT confidence_tier, session_count, last_calibrated
               FROM voice_enrollment_profiles
               WHERE user_id = $1""",
            username,
        )
        if row:
            return {
                "enrolled": True,
                "confidence_tier": row["confidence_tier"],
                "session_count": row["session_count"],
                "last_calibrated": str(row["last_calibrated"]) if row["last_calibrated"] else None,
            }
        return {"enrolled": False}
    except Exception as e:
        logger.warning("Enrollment status failed: %s", e)
        return {"enrolled": False, "error": str(e)}


@router.post("/enrollment/start")
async def start_enrollment(body: EnrollmentStartRequest, request: Request):
    """Initiate voice enrollment for a user."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    try:
        await db.execute(
            """INSERT INTO voice_enrollment_profiles (user_id, tenant_id, confidence_tier)
               VALUES ($1, $2, 'NONE')
               ON CONFLICT (user_id, tenant_id) DO NOTHING""",
            body.username, body.tenant_id,
        )
        return {"status": "enrollment_initiated", "username": body.username}
    except Exception as e:
        logger.warning("Enrollment start failed: %s", e)
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

@router.post("/consent/initiate")
async def initiate_consent(body: ConsentInitiateRequest, request: Request):
    """Send a consent SMS magic link to a user."""
    consent_mgr = getattr(request.app.state, "consent_privacy", None)
    if not consent_mgr:
        raise HTTPException(503, "Consent service unavailable")

    result = await consent_mgr.create_sms_magic_link(
        user_id=body.username,
        tenant_id=body.tenant_id,
        consent_type=body.consent_type,
        phone=body.phone,
    )
    if result:
        return result.to_dict()
    raise HTTPException(500, "Consent request failed")


@router.post("/consent/parental")
async def initiate_parental_consent(body: ParentalConsentRequest, request: Request):
    """Initiate parental consent for a minor (COPPA/FERPA)."""
    consent_mgr = getattr(request.app.state, "consent_privacy", None)
    if not consent_mgr:
        raise HTTPException(503, "Consent service unavailable")

    result = await consent_mgr.create_parental_consent(
        minor_user_id=body.minor_username,
        parent_user_id=body.parent_username,
        tenant_id=body.tenant_id,
        parent_phone=body.parent_phone,
    )
    if result:
        return result.to_dict()
    raise HTTPException(500, "Parental consent request failed")


@router.get("/consent/verify")
async def verify_consent_link(token: str, request: Request):
    """Verify a magic link consent token."""
    consent_mgr = getattr(request.app.state, "consent_privacy", None)
    if not consent_mgr:
        raise HTTPException(503, "Consent service unavailable")

    result = await consent_mgr.verify_magic_link(token)
    if result:
        return {"status": "consent_granted", "consent_type": result.consent_type}
    raise HTTPException(400, "Invalid or expired consent link")


@router.post("/consent/vouch")
async def vouch_enrollment(body: VouchRequest, request: Request):
    """Admin vouches for a cohort of users (institutional enrollment)."""
    consent_mgr = getattr(request.app.state, "consent_privacy", None)
    if not consent_mgr:
        raise HTTPException(503, "Consent service unavailable")

    user = getattr(request.state, "user", None)
    admin_id = user.get("username", "unknown") if isinstance(user, dict) else "unknown"

    count = await consent_mgr.vouch_enrollment(
        admin_user_id=admin_id,
        tenant_id=body.tenant_id,
        user_ids=body.user_ids,
    )
    return {"vouched": count, "total": len(body.user_ids)}


# ---------------------------------------------------------------------------
# Identity History
# ---------------------------------------------------------------------------

@router.get("/inference-history/{username}")
async def get_inference_history(username: str, request: Request, limit: int = 20):
    """Get identity inference history for a user."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"history": []}

    try:
        rows = await db.fetch(
            """SELECT call_sid, top_candidate, confidence, method,
                      voice_score, linguistic_score, narrative_score,
                      osd_penalty, liveness_ok, roleplay_excluded,
                      qos_degraded, inferred_at
               FROM identity_inference_log
               WHERE top_candidate = $1
               ORDER BY inferred_at DESC
               LIMIT $2""",
            username, limit,
        )
        return {"history": [dict(r) for r in rows]}
    except Exception as e:
        logger.warning("Inference history failed: %s", e)
        return {"history": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Drift Flags
# ---------------------------------------------------------------------------

@router.get("/drift-flags")
async def get_drift_flags(request: Request, reviewed: bool = False):
    """Get identity drift flags for review."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"flags": []}

    try:
        rows = await db.fetch(
            """SELECT id, user_id, call_sid, drift_magnitude,
                      flagged_at, reviewed, reviewed_by, review_notes
               FROM identity_drift_flags
               WHERE reviewed = $1
               ORDER BY flagged_at DESC
               LIMIT 50""",
            reviewed,
        )
        return {"flags": [dict(r) for r in rows]}
    except Exception as e:
        logger.warning("Drift flags failed: %s", e)
        return {"flags": [], "error": str(e)}
