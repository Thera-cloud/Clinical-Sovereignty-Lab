"""High-risk occupational crisis engine API — QUANTUM-CRYSTAL-ARCH.

Endpoints:
  Client: set population, confidentiality disclosure, family concern flag, family education
  Coach: list active risk windows for assigned clients
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import get_current_user, require_coach
from app.services.crisis_resource_registry import (
    confidentiality_disclosure_copy,
    get_crisis_resources,
)
from app.services.population_profile import (
    VALID_POPULATIONS,
    family_concern_consent,
    get_population,
    is_population_shielded,
    profile_data,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/high-risk-crisis", tags=["high_risk_crisis"])


class PopulationUpdate(BaseModel):
    population: str
    population_shielded: Optional[bool] = True
    family_concern_consent: Optional[bool] = None


class FamilyConcernBody(BaseModel):
    target_username: str
    relationship: str = "family"
    # Optional free text is accepted but NEVER persisted as content — only presence flag
    note: Optional[str] = Field(None, max_length=500)


class CriticalIncidentBody(BaseModel):
    client_username: str
    note: Optional[str] = Field(None, max_length=200)


def _pd(user: Dict) -> Dict[str, Any]:
    return profile_data(user)


@router.get("/health")
async def health():
    return {"status": "ok", "service": "high_risk_crisis"}


@router.get("/resources")
async def resources(user: Dict = Depends(get_current_user)):
    return {
        "population": get_population(user),
        "resources": get_crisis_resources(user),
    }


@router.get("/confidentiality")
async def confidentiality(user: Dict = Depends(get_current_user)):
    return confidentiality_disclosure_copy(user)


@router.get("/population")
async def get_my_population(user: Dict = Depends(get_current_user)):
    pd = _pd(user)
    return {
        "population": get_population(user),
        "population_shielded": is_population_shielded(user),
        "family_concern_consent": family_concern_consent(user),
        "lethal_means_guidance_ok": bool(pd.get("lethal_means_guidance_ok")),
    }


@router.put("/population")
async def set_population(
    body: PopulationUpdate,
    request: Request,
    user: Dict = Depends(get_current_user),
):
    pop = (body.population or "").strip().lower()
    if pop not in VALID_POPULATIONS:
        raise HTTPException(400, f"Invalid population. Allowed: {sorted(VALID_POPULATIONS)}")
    pool = request.app.state.db_pool
    if not pool:
        raise HTTPException(503, "Database unavailable")
    username = user.get("username") or ""
    if not username:
        raise HTTPException(400, "Username required")
    shielded = True if body.population_shielded is None else bool(body.population_shielded)
    if pop == "general":
        shielded = bool(body.population_shielded) if body.population_shielded is not None else False

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users SET profile_data = jsonb_set(
                jsonb_set(
                    COALESCE(profile_data, '{}'::jsonb),
                    '{population}',
                    to_jsonb($1::text)
                ),
                '{population_shielded}',
                to_jsonb($2::boolean)
            )
            WHERE username = $3
            """,
            pop,
            shielded,
            username,
        )
        if body.family_concern_consent is not None:
            await conn.execute(
                """
                UPDATE users SET profile_data = jsonb_set(
                    COALESCE(profile_data, '{}'::jsonb),
                    '{family_concern_consent}',
                    to_jsonb($1::boolean)
                )
                WHERE username = $2
                """,
                bool(body.family_concern_consent),
                username,
            )
    return {
        "status": "ok",
        "population": pop,
        "population_shielded": shielded,
        "family_concern_consent": body.family_concern_consent,
    }


@router.post("/family/concern-flag")
async def family_concern_flag(
    body: FamilyConcernBody,
    request: Request,
    user: Dict = Depends(get_current_user),
):
    """Family member flags concern — raises cadence, never shares content with Nate."""
    pool = request.app.state.db_pool
    if not pool:
        raise HTTPException(503, "Database unavailable")
    flagger = user.get("username") or ""
    target = (body.target_username or "").strip()
    if not flagger or not target:
        raise HTTPException(400, "flagger and target required")
    if flagger == target:
        raise HTTPException(400, "Cannot flag yourself")

    async with pool.acquire() as conn:
        # Same family_id required
        rows = await conn.fetch(
            """
            SELECT username, family_id, profile_data, role
              FROM users
             WHERE username = ANY($1::text[])
               AND deleted_at IS NULL
            """,
            [flagger, target],
        )
        by_u = {r["username"]: r for r in rows}
        if flagger not in by_u or target not in by_u:
            raise HTTPException(404, "User not found")
        f_fam = by_u[flagger]["family_id"]
        t_fam = by_u[target]["family_id"]
        if not f_fam or not t_fam or str(f_fam) != str(t_fam):
            raise HTTPException(403, "Must be in the same family")

        t_pd = by_u[target]["profile_data"] or {}
        if isinstance(t_pd, str):
            try:
                t_pd = json.loads(t_pd)
            except Exception:
                t_pd = {}
        consent = t_pd.get("family_concern_consent")
        if consent is not True and str(consent).lower() not in ("1", "true", "yes"):
            raise HTTPException(
                403,
                "Target has not consented to family concern flags",
            )

    from app.services.checkin_risk_windows import flag_family_concern

    result = await flag_family_concern(
        pool,
        target_username=target,
        flagger_username=flagger,
        relationship=body.relationship,
        note_redacted=body.note or "",
    )
    if result.get("status") != "ok":
        raise HTTPException(500, result.get("reason") or "flag failed")
    return result


@router.get("/family/education")
async def family_education(user: Dict = Depends(get_current_user)):
    """Kitchen-table PTSD/TBI education track content."""
    return {
        "title": "Understanding what shows up at home",
        "sections": [
            {
                "id": "ptsd_kitchen_table",
                "title": "What PTSD can look like at the kitchen table",
                "body": (
                    "It is not always flashbacks. Sometimes it is a short fuse after a loud "
                    "pan lid, checking the locks twice, sleeping light, or going quiet mid-conversation. "
                    "None of that means they do not love you. It often means their nervous system "
                    "is still scanning for threat."
                ),
            },
            {
                "id": "tbi_basics",
                "title": "TBI — plain language",
                "body": (
                    "A traumatic brain injury can change memory, patience, headaches, and how "
                    "someone filters noise or light. Irritability after a long day is not always "
                    "about you. Ask what helps — dimmer lights, fewer overlapping conversations, rest."
                ),
            },
            {
                "id": "trigger_vs_crisis",
                "title": "Trigger vs bad night vs crisis",
                "body": (
                    "Trigger: something (sound, date, smell) lights up an old alarm — rough, but "
                    "they can usually ride it with support. Bad night: nightmares, hypervigilance, "
                    "can't sleep — hard, not necessarily emergency. Crisis: clear intent to harm "
                    "themselves or someone else, or they say they are not safe — use crisis lines "
                    "and your coach/alert tools immediately."
                ),
            },
            {
                "id": "concern_flag",
                "title": "Raising concern without breaking trust",
                "body": (
                    "If you are worried, you can flag concern in the app. That tips Nate to check "
                    "in sooner. It does not share your conversation content or theirs. Your loved "
                    "one must have agreed to this option first."
                ),
            },
        ],
        "crisis_resources": get_crisis_resources(user),
    }


@router.get("/coach/risk-windows")
async def coach_risk_windows(
    request: Request,
    user: Dict = Depends(require_coach),
):
    """Active risk windows for clients assigned to this coach."""
    pool = request.app.state.db_pool
    if not pool:
        raise HTTPException(503, "Database unavailable")
    coach_hw = user.get("hardware_id") or ""
    coach_user = user.get("username") or ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT username, profile_data->>'name' AS name
              FROM users
             WHERE role = 'CLIENT'
               AND deleted_at IS NULL
               AND (
                 profile_data->>'coach_id' = $1
                 OR profile_data->>'assigned_coach_id' = $1
                 OR profile_data->>'assigned_coach' = $2
               )
            """,
            coach_hw,
            coach_user,
        )
    usernames = [r["username"] for r in rows]
    from app.services.checkin_risk_windows import list_active_windows_for_coach

    windows = await list_active_windows_for_coach(pool, client_usernames=usernames)
    name_by = {r["username"]: r["name"] for r in rows}
    for w in windows:
        w["client_name"] = name_by.get(w["username"])
        if w.get("opened_at"):
            w["opened_at"] = w["opened_at"].isoformat()
        if w.get("expires_at"):
            w["expires_at"] = w["expires_at"].isoformat()
    return {"windows": windows, "count": len(windows)}


@router.post("/coach/critical-incident")
async def coach_critical_incident(
    body: CriticalIncidentBody,
    request: Request,
    user: Dict = Depends(require_coach),
):
    """Coach opens a critical-incident risk window (e.g. after a bad call / LODD)."""
    pool = request.app.state.db_pool
    if not pool:
        raise HTTPException(503, "Database unavailable")
    from app.services.checkin_risk_windows import (
        REASON_CRITICAL_INCIDENT,
        open_risk_window,
    )

    wid = await open_risk_window(
        pool,
        username=body.client_username,
        reason=REASON_CRITICAL_INCIDENT,
        opened_by=f"coach:{user.get('username')}",
        metadata={"note_present": bool(body.note)},
    )
    if not wid:
        raise HTTPException(500, "Could not open window")
    return {"status": "ok", "window_id": wid}
