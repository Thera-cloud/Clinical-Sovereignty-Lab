"""Thrive / Growth-Phase REST API. QUANTUM-CRYSTAL-ARCH.

Prefix ``/api/thrive``. Two audiences:

* **Client** (self only): phase, focus areas, practices, goals, trajectories,
  strengths, mark a practice done, open/update a goal.
* **Coach / Admin** (any client they can see): everything above plus phase
  override / release, adopt/retire a practice for the client, coaching brief.

Identity: ``username`` path param is the canonical ``users.username``; a
client may only address their own record (hardware_id or username both
accepted and resolved via ``_identity_resolver``).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import get_current_user, require_coach
from app.services.thrive import growth_phase as gp
from app.services.thrive import phase_resolver as pr
from app.services.thrive import practice_catalog as pc
from app.services.thrive import practice_tracker as pt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/thrive", tags=["thrive"])


# ── helpers ────────────────────────────────────────────────────────────────

async def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return pool


async def _canonical(pool, user_id: str) -> str:
    try:
        from app.services._identity_resolver import resolve_username
        return await resolve_username(pool, user_id) or user_id
    except Exception:
        return user_id


async def _authorize(pool, user: Dict[str, Any], target: str) -> str:
    """Return canonical target username, or 403."""
    role = (user.get("role") or "").upper()
    canon = await _canonical(pool, target)
    if role in ("ADMIN", "COACH") or user.get("is_audit"):
        return canon
    mine = await _canonical(pool, user.get("username") or user.get("hardware_id") or "")
    if canon != mine:
        raise HTTPException(status_code=403, detail="clients may only view their own growth record")
    return canon


def _iso(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if isinstance(v, datetime) else v


# ── models ─────────────────────────────────────────────────────────────────

class PhaseOverride(BaseModel):
    phase: str = Field(..., pattern="^(stabilize|process|consolidate|thrive|generative)$")
    reason: str = Field("coach_override", max_length=400)
    pin: bool = True
    sub_state: Optional[str] = Field(None, pattern="^(working_through|crisis_hold)$")


class AdoptPractice(BaseModel):
    practice_key: str
    cadence: Optional[str] = Field(None, pattern="^(daily|weekdays|3x_week|weekly|once)$")
    time_of_day: Optional[str] = Field(None, pattern="^(morning|midday|evening|late_night|any)$")
    notes: Optional[str] = Field(None, max_length=600)


class CompletePractice(BaseModel):
    practice_key: str
    harvest: Optional[str] = Field(None, max_length=4000)


class NewGoal(BaseModel):
    text: str = Field(..., min_length=3, max_length=500)
    focus_area: Optional[str] = Field(None, pattern="^(daily_happiness|future_direction|self_compassion_confidence|handling_stress)$")
    target_date: Optional[datetime] = None
    commitment_type: str = Field("practice_goal", pattern="^(practice_goal|milestone|custom)$")


class GoalProgress(BaseModel):
    progress_pct: Optional[float] = Field(None, ge=0, le=100)
    note: Optional[str] = Field(None, max_length=2000)


class StrengthsAnswers(BaseModel):
    tags_per_answer: List[List[str]]
    answers: Optional[List[str]] = None


# ── catalog (public to any authenticated user) ─────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok", "enabled": pr.ENABLE_GROWTH_PHASE, "phases": list(gp.PHASES)}


@router.get("/{username}/entry-greeting")
async def entry_greeting(
    username: str,
    request: Request,
    force: bool = False,
    user: Dict = Depends(get_current_user),
):
    """LN's app-open greeting: welcome (≤600) / prime (300–500) / direction (≤900).

    Cached per user for LN_ENTRY_GREETING_CACHE_HOURS (default 4) unless
    ``force=true``. Includes ``thera_panel`` (latest Thera-World panel) so the
    client can raise the "[SSE Panel:<id>]" ask-Nate flow with one tap.
    """
    from app.services.thrive import entry_greeting as eg

    pool = _pool(request)
    canon = await _canonical(pool, username)
    _authorize(pool, user, canon)
    try:
        g = await eg.build_entry_greeting(pool, canon, app_state=request.app.state, force=force)
    except Exception as e:
        logger.warning("thrive_api.entry_greeting %s: %s", canon, e)
        raise HTTPException(status_code=503, detail="entry greeting unavailable")
    return g.to_dict()


@router.post("/{username}/entry-greeting/opened")
async def entry_greeting_opened(username: str, request: Request, user: Dict = Depends(get_current_user)):
    from app.services.thrive import entry_greeting as eg

    pool = _pool(request)
    canon = await _canonical(pool, username)
    _authorize(pool, user, canon)
    await eg.mark_opened(pool, canon)
    return {"ok": True}


@router.get("/catalog")
async def catalog(_: Dict = Depends(get_current_user)):
    from dataclasses import asdict
    return {
        "focus_areas": {k: asdict(v) for k, v in pc.FOCUS_AREAS.items()},
        "practices": {k: asdict(v) for k, v in pc.PRACTICES.items()},
        "anchor_practices": {k: v.anchor_practice for k, v in pc.FOCUS_AREAS.items()},
        "strengths_interview": list(pc.STRENGTHS_INTERVIEW),
    }


@router.get("/frameworks")
async def frameworks(_: Dict = Depends(get_current_user)):
    return {p: gp.framework_for(p).__dict__ for p in gp.PHASES}


# ── per-client read surface ────────────────────────────────────────────────

@router.get("/{username}/phase")
async def get_phase(username: str, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    state = await pr.get_phase(pool, canon, use_cache=False)
    fw = gp.framework_for(state.phase)
    async with pool.acquire() as conn:
        hist = await conn.fetch(
            """
            SELECT from_phase, to_phase, from_sub_state, to_sub_state, reason, healing_score, set_by, created_at
            FROM client_growth_phase_history WHERE username = $1 ORDER BY created_at DESC LIMIT 20
            """,
            canon,
        )
    return {
        "username": canon,
        "state": state.to_dict(),
        "framework": fw.__dict__,
        "history": [dict(h, created_at=_iso(h["created_at"])) for h in hist],
    }


@router.get("/{username}/healing-signal")
async def healing_signal(username: str, request: Request, days: int = 14, user: Dict = Depends(require_coach)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    from app.services.thrive.healing_cycle import compute_healing_signal
    sig = await compute_healing_signal(pool, canon, days=max(3, min(days, 90)))
    return sig.to_dict() if hasattr(sig, "to_dict") else sig.__dict__


@router.get("/{username}/focus")
async def focus(username: str, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    return {"username": canon, **(await pt.focus_state(pool, canon))}


@router.get("/{username}/goals")
async def goals(username: str, request: Request, include_completed: bool = True, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    rows = await pt.goal_trajectories(pool, canon, include_completed=include_completed, limit=50)
    return {"username": canon, "goals": [g.to_dict() for g in rows]}


@router.get("/{username}/practice-log")
async def practice_log(username: str, request: Request, limit: int = 60, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, practice_key, focus_area, completed_at, source, harvest, metadata
            FROM client_practice_log WHERE username = $1 ORDER BY completed_at DESC LIMIT $2
            """,
            canon, max(1, min(limit, 500)),
        )
    return {"username": canon, "entries": [dict(r, completed_at=_iso(r["completed_at"])) for r in rows]}


@router.get("/{username}/reminders")
async def reminders(username: str, request: Request, limit: int = 40, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT reminder_type, practice_key, commitment_id::text AS commitment_id, channel, subject, sent_at
            FROM thrive_reminders WHERE username = $1 ORDER BY sent_at DESC LIMIT $2
            """,
            canon, max(1, min(limit, 300)),
        )
    return {"username": canon, "reminders": [dict(r, sent_at=_iso(r["sent_at"])) for r in rows]}


@router.get("/{username}/strengths")
async def strengths(username: str, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    return {"username": canon, "strengths": await pt.get_strengths(pool, canon), "interview": list(pc.STRENGTHS_INTERVIEW)}


@router.get("/{username}/brief")
async def coaching_brief(username: str, request: Request, user: Dict = Depends(require_coach)):
    """Coach-facing growth brief: phase + framework focus + goals + practices + last transitions."""
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    state = await pr.get_phase(pool, canon, use_cache=False)
    fw = gp.framework_for(state.phase)
    fs = await pt.focus_state(pool, canon)
    async with pool.acquire() as conn:
        last_tr = await conn.fetchrow(
            "SELECT to_phase, reason, healing_score, created_at FROM client_growth_phase_history WHERE username = $1 ORDER BY created_at DESC LIMIT 1",
            canon,
        )
        recent_harvest = await conn.fetch(
            "SELECT practice_key, harvest, completed_at FROM client_practice_log WHERE username = $1 AND harvest IS NOT NULL ORDER BY completed_at DESC LIMIT 5",
            canon,
        )
    return {
        "username": canon,
        "phase": state.to_dict(),
        "coach_focus": fw.coach_focus,
        "core_questions": list(fw.core_questions),
        "time_focus": fw.time_focus,
        "goals_active": fs["goals_active"],
        "goals_completed": fs["goals_completed"],
        "practices": fs["practices"],
        "best_streak": fs["best_streak"],
        "strengths": fs.get("strengths"),
        "last_transition": dict(last_tr, created_at=_iso(last_tr["created_at"])) if last_tr else None,
        "recent_harvest": [dict(r, completed_at=_iso(r["completed_at"])) for r in recent_harvest],
        "session_guidance": _session_guidance(state.phase, state.sub_state, fs),
    }


def _session_guidance(phase: str, sub_state: Optional[str], fs: Dict[str, Any]) -> List[str]:
    """Live-session prompts for the coach (Studio co-host + Coach Command panel share this)."""
    fw = gp.framework_for(phase)
    out: List[str] = []
    if sub_state == "crisis_hold":
        return ["Client is in crisis_hold: stabilize, safety plan, no goal talk this session."]
    if sub_state == "working_through":
        out.append("Client asked to go back into something — open with that; hold goals until they signal they're done.")
    out.append(f"Register: {fw.ln_register}.")
    if gp.is_coaching_phase(phase):
        out.append(f"Time focus {fw.time_focus}. Open with: “{fw.core_questions[0]}”")
        for g in fs.get("goals_active", [])[:2]:
            out.append(f"Goal check: {g['text']} — {g['progress_pct']:.0f}%" + (" (behind)" if g.get("on_track") is False else ""))
        if fs.get("due_now"):
            out.append("Practices due: " + ", ".join(pc.PRACTICES[k].label for k in fs["due_now"] if k in pc.PRACTICES))
        if fs.get("best_streak", 0) >= 7:
            out.append(f"Celebrate the {fs['best_streak']}-day streak before anything else.")
    else:
        out.append(f"EFT: {fw.eft}. Attachment: {fw.attachment}.")
        out.append(f"Watch for: {fw.emdr}.")
    return out


# ── client actions (self) ──────────────────────────────────────────────────

@router.post("/{username}/practices/complete")
async def complete_practice(username: str, body: CompletePractice, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    if body.practice_key not in pc.PRACTICES:
        raise HTTPException(status_code=422, detail="unknown practice_key")
    src = "coach" if (user.get("role") or "").upper() in ("COACH", "ADMIN") else "app"
    row = await pt.log_completion(pool, canon, body.practice_key, source=src, harvest=body.harvest)
    return {"ok": row is not None, "practice": row.to_dict() if row else None}


@router.post("/{username}/practices/adopt")
async def adopt(username: str, body: AdoptPractice, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    if body.practice_key not in pc.PRACTICES:
        raise HTTPException(status_code=422, detail="unknown practice_key")
    src = "coach" if (user.get("role") or "").upper() in ("COACH", "ADMIN") else "client"
    row = await pt.adopt_practice(pool, canon, body.practice_key, cadence=body.cadence, time_of_day=body.time_of_day, source=src, notes=body.notes)
    return {"ok": True, "practice": row.to_dict()}


@router.post("/{username}/practices/{practice_key}/retire")
async def retire(username: str, practice_key: str, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    return {"ok": await pt.retire_practice(pool, canon, practice_key)}


@router.post("/{username}/goals")
async def new_goal(username: str, body: NewGoal, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    state = await pr.get_phase(pool, canon)
    by = "coach" if (user.get("role") or "").upper() in ("COACH", "ADMIN") else "client"
    gid = await pt.open_goal(pool, canon, body.text, focus_area=body.focus_area, target_date=body.target_date,
                             growth_phase=state.phase, coached_by=by, commitment_type=body.commitment_type)
    if not gid:
        raise HTTPException(status_code=500, detail="goal not created")
    return {"ok": True, "goal_id": gid}


@router.post("/{username}/goals/{goal_id}/progress")
async def goal_progress(username: str, goal_id: str, body: GoalProgress, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    async with pool.acquire() as conn:
        owner = await conn.fetchval("SELECT user_id FROM nate_commitments WHERE id = $1::uuid", goal_id)
    if owner != canon:
        raise HTTPException(status_code=404, detail="goal not found for this client")
    ok = await pt.update_goal_progress(pool, goal_id, body.progress_pct, note=body.note)
    return {"ok": ok}


@router.post("/{username}/strengths")
async def save_strengths(username: str, body: StrengthsAnswers, request: Request, user: Dict = Depends(get_current_user)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    ranked = pc.strengths_from_answers(body.tags_per_answer)
    via_top = [k for k, _ in ranked[:5]]
    await pt.save_strengths(pool, canon, via_top=via_top,
                            answers={"answers": body.answers} if body.answers else None, method="app_interview")
    return {"ok": True, "via_top": via_top, "ranked": ranked}


# ── coach actions ──────────────────────────────────────────────────────────

@router.post("/{username}/phase/override")
async def override_phase(username: str, body: PhaseOverride, request: Request, user: Dict = Depends(require_coach)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    state = await pr.set_phase(pool, canon, body.phase, set_by=user.get("username") or "coach",
                               reason=body.reason, pin=body.pin, sub_state=body.sub_state)
    return {"ok": True, "state": state.to_dict()}


@router.post("/{username}/phase/release")
async def release_phase(username: str, request: Request, user: Dict = Depends(require_coach)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    state = await pr.release_override(pool, canon, set_by=user.get("username") or "coach")
    return {"ok": True, "state": state.to_dict()}


@router.post("/{username}/phase/evaluate")
async def evaluate_now(username: str, request: Request, user: Dict = Depends(require_coach)):
    pool = await _pool(request)
    canon = await _authorize(pool, user, username)
    state, transition, sig = await pr.evaluate(pool, canon)
    return {
        "ok": True,
        "state": state.to_dict(),
        "transition": transition.__dict__ if transition else None,
        "signal": sig.to_dict() if hasattr(sig, "to_dict") else getattr(sig, "__dict__", None),
    }


@router.get("/coach/{coach_username}/roster")
async def coach_roster(coach_username: str, request: Request, user: Dict = Depends(require_coach)):
    """Phase badge per client for Coach Command list views."""
    pool = await _pool(request)
    role = (user.get("role") or "").upper()
    if coach_username == "me":
        coach_username = user.get("username") or ""
    if role == "COACH" and (user.get("username") or "") != coach_username and not user.get("is_audit"):
        raise HTTPException(status_code=403, detail="coaches may only view their own roster")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.username, u.hardware_id, u.profile_data->>'name' AS name,
                   g.phase, g.sub_state, g.sub_state_until, g.phase_since, g.healing_score, g.coach_override,
                   (SELECT COUNT(*) FROM nate_commitments c WHERE c.user_id = u.username AND c.status = 'active' AND c.coached_by IS NOT NULL) AS goals_active,
                   (SELECT MAX(streak) FROM client_focus_areas f WHERE f.username = u.username AND f.active) AS best_streak
            FROM users u
            JOIN users c ON c.role = 'COACH' AND c.username = $1
            LEFT JOIN client_growth_phase g ON g.username = u.username
            WHERE u.role = 'CLIENT'
              AND (u.profile_data->>'coach_id' = c.hardware_id
                   OR u.profile_data->>'assigned_coach_id' = c.hardware_id
                   OR u.profile_data->>'assigned_coach' = c.username)
            ORDER BY u.profile_data->>'name'
            """,
            coach_username,
        )
    out = []
    for r in rows:
        d = dict(r)
        d["phase"] = d["phase"] or gp.DEFAULT_PHASE
        d["effective"] = gp.effective_phase(d["phase"], d["sub_state"])
        d["coaching"] = gp.is_coaching_phase(d["phase"], d["sub_state"])
        d["phase_since"] = _iso(d["phase_since"])
        d["sub_state_until"] = _iso(d["sub_state_until"])
        d["healing_score"] = float(d["healing_score"]) if d["healing_score"] is not None else None
        out.append(d)
    return {"coach": coach_username, "clients": out}
