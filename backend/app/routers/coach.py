"""
Coach Portal API Routes
Pre-session briefs, client management, and coach-specific features
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List

from app.auth import get_current_user_id
from datetime import datetime, timedelta
import logging
import os
import json
import re
from pathlib import Path

from app.services.pg_data_helpers import (
    load_registry_pg, find_user_pg, load_sessions_pg, load_metrics_pg,
)

_logger = logging.getLogger("coach_router")

router = APIRouter(
    prefix="/api/coach",
    tags=["coach"],
    dependencies=[Depends(get_current_user_id)],
)


def _is_external_coach_consultation_row(s: dict) -> bool:
    """External consultee sessions — excluded from coach roster stats / billing views."""
    if not isinstance(s, dict):
        return False
    st = str(s.get("session_type") or "").strip().lower()
    if st == "consultation":
        return True
    if str(s.get("booked_by") or "").strip() == "COACH_CONSULTATION":
        return True
    return str(s.get("client_id") or "").startswith("consultation_")


def _get_coach_shield(request: Request):
    """Retrieve CoachIntegrityShield from app state (non-blocking on failure)."""
    try:
        hive_v4 = getattr(request.app.state, "hive_v4", None)
        if hive_v4:
            return hive_v4.get("coach_integrity_shield")
    except Exception:
        pass
    return None

from app.config import settings as _settings
DATA_DIR = Path(_settings.DATA_DIR)
VAULT_ROOT = DATA_DIR / "Vaults"

# Models
class CoachNoteRequest(BaseModel):
    client_id: str
    note: str
    note_type: str = "general"  # general, session, homework, alert

class HomeworkRequest(BaseModel):
    client_id: str
    homework: str
    due_date: Optional[str] = None

class MatchmakerRequest(BaseModel):
    client_id: str
    top_n: int = 3

# Helpers
def load_json(filepath: Path, default=None):
    if default is None: default = {}
    if not filepath.exists(): return default
    try:
        with open(filepath, 'r') as f: return json.load(f)
    except: return default


async def _load_metrics_pg(hardware_id: str, db_pool) -> dict:
    """Load nevedal_state from PG client_metrics table. Returns None if unavailable."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT nevedal_state FROM client_metrics WHERE hardware_id = $1",
                hardware_id
            )
            if row and row["nevedal_state"]:
                ns = row["nevedal_state"]
                if isinstance(ns, str):
                    ns = json.loads(ns)
                return {"nevedal_state": ns}
    except Exception:
        pass
    return None


def save_json(filepath: Path, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f: json.dump(data, f, indent=2, default=str)

# Endpoints

@router.get("/clients")
async def get_my_clients(request: Request, user_id: str = Depends(get_current_user_id)):
    """Return clients assigned to the authenticated coach.

    Convenience alias used by the Sovereign Command dashboard so the URL
    does not need to know the coach's hardware_id. Reuses the canonical
    /clients/{coach_id} logic with the caller's identity.
    """
    return await get_assigned_clients(user_id, request, user_id)


@router.get("/clients/{coach_id}")
async def get_assigned_clients(coach_id: str, request: Request, caller_hw_id: str = Depends(get_current_user_id)):
    """Get all clients assigned to this coach"""
    shield = _get_coach_shield(request)
    if shield:
        try:
            import asyncio
            asyncio.ensure_future(shield.detect_off_session_access(coach_id))
        except Exception as _e:
            _logger.debug("CoachIntegrityShield access check non-blocking: %s", _e)

    # IDOR guard: path coach_id must match authenticated caller hardware_id.
    # ADMIN bypass mirrors sessions.py (auditors + Sovereign Command use admin token).
    if str(coach_id) != str(caller_hw_id) and getattr(request.state, "user_role", "") != "ADMIN":
        raise HTTPException(status_code=403, detail="Cannot view another coach's clients")

    db_pool = getattr(request.app.state, "db_pool", None)

    # PG-first: load clients assigned to this coach
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                client_rows = await conn.fetch(
                    """SELECT hardware_id, name, tier, family_id,
                              created_at, last_login, token_balance, profile_data
                       FROM users
                       WHERE deleted_at IS NULL
                         AND (profile_data->>'assigned_coach_id' = $1
                              OR profile_data->>'coach_id' = $1
                              OR profile_data->>'assigned_coach' = $1)
                         AND role = 'CLIENT'""",
                    coach_id,
                )

            all_sessions = await load_sessions_pg(db_pool, coach_id=coach_id, status="scheduled")

            clients = []
            for r in client_rows:
                hw_id = r["hardware_id"] or ""
                pd = r.get("profile_data") or {}
                if isinstance(pd, str):
                    try: pd = json.loads(pd)
                    except Exception: pd = {}

                pg_metrics = await load_metrics_pg(db_pool, hw_id) if hw_id else None
                ns = (pg_metrics or {}).get("nevedal_state", {})
                if not ns:
                    metrics_file = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
                    ns = load_json(metrics_file, {}).get("nevedal_state", {})

                upcoming = [s for s in all_sessions if s.get("client_id") == hw_id]

                clients.append({
                    "id": hw_id,
                    "name": r.get("name") or pd.get("name", ""),
                    "tier": r.get("tier") or pd.get("tier", ""),
                    "family_id": str(r.get("family_id") or "") or pd.get("family_id", ""),
                    "joined_date": r["created_at"].isoformat() if r.get("created_at") else pd.get("joined_date", ""),
                    "last_login": r["last_login"].isoformat() if r.get("last_login") else pd.get("last_login", ""),
                    "total_sessions": pd.get("total_sessions_count", 0),
                    "metrics": {
                        "C_emo": ns.get("C_emo", 0.5),
                        "GAP": ns.get("GAP", 0.3),
                        "anxiety_level": ns.get("anxiety_level", 0),
                        "risk_level": ns.get("risk_level", "LOW"),
                        "mood_current": ns.get("mood_current", "neutral"),
                        "mood_trend": ns.get("mood_trend", "stable"),
                    },
                    "next_session": upcoming[0] if upcoming else None,
                })

            risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            clients.sort(key=lambda x: (risk_order.get(x["metrics"]["risk_level"], 4), x.get("last_login", "") or ""))
            return {"clients": clients, "count": len(clients)}
        except Exception as e:
            _logger.warning("get_assigned_clients: PG read failed: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    sessions = load_json(DATA_DIR / "sessions.json", [])

    clients = []
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("assigned_coach_id") == coach_id or p.get("coach_id") == coach_id:
            hw_id = p.get("hardware_id", "")
            metrics_file = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
            metrics = load_json(metrics_file, {})
            ns = metrics.get("nevedal_state", {})

            upcoming = [s for s in sessions
                       if s.get("client_id") == hw_id
                       and s.get("status") == "scheduled"]

            clients.append({
                "id": hw_id,
                "name": p.get("name"),
                "tier": p.get("tier"),
                "family_id": p.get("family_id"),
                "joined_date": p.get("joined_date"),
                "last_login": p.get("last_login"),
                "total_sessions": p.get("total_sessions_count", 0),
                "metrics": {
                    "C_emo": ns.get("C_emo", 0.5),
                    "GAP": ns.get("GAP", 0.3),
                    "anxiety_level": ns.get("anxiety_level", 0),
                    "risk_level": ns.get("risk_level", "LOW"),
                    "mood_current": ns.get("mood_current", "neutral"),
                    "mood_trend": ns.get("mood_trend", "stable"),
                },
                "next_session": upcoming[0] if upcoming else None,
            })

    risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    clients.sort(key=lambda x: (risk_order.get(x["metrics"]["risk_level"], 4), x.get("last_login", "") or ""))
    return {"clients": clients, "count": len(clients)}

@router.get("/presession-brief/{client_id}")
async def get_presession_brief(client_id: str, request: Request, user=Depends(get_current_user_id)):
    """Generate a comprehensive pre-session brief for a client"""
    shield = _get_coach_shield(request)
    if shield:
        try:
            coach_id = user.get("user_id", "") if isinstance(user, dict) else getattr(user, "user_id", "")
            if coach_id:
                import asyncio
                asyncio.ensure_future(shield.detect_off_session_access(coach_id))
        except Exception as _e:
            _logger.debug("CoachIntegrityShield access check non-blocking: %s", _e)

    db_pool = getattr(request.app.state, "db_pool", None)

    # PG-first: find client profile
    client_profile = await find_user_pg(db_pool, client_id)
    if not client_profile:
        registry = load_json(DATA_DIR / "user_registry.json")
        for k, v in registry.items():
            if v.get("profile", {}).get("hardware_id") == client_id:
                client_profile = v["profile"]
                break

    if not client_profile:
        raise HTTPException(404, "Client not found")

    pg_metrics = await load_metrics_pg(db_pool, client_id)
    if pg_metrics:
        metrics = pg_metrics
    else:
        metrics_file = VAULT_ROOT / "Clients" / client_id / "metrics.json"
        metrics = load_json(metrics_file, {})
    ns = metrics.get("nevedal_state", {})

    memory_file = VAULT_ROOT / "Clients" / client_id / "memory.json"
    memories = load_json(memory_file, [])

    # PG-first: sessions
    client_sessions = await load_sessions_pg(db_pool, client_id=client_id) if db_pool else []
    if not client_sessions:
        sessions = load_json(DATA_DIR / "sessions.json", [])
        client_sessions = [s for s in sessions if s.get("client_id") == client_id]
    completed_sessions = [s for s in client_sessions if s.get("status") == "completed"]

    # PG-first: family members
    family_members = []
    family_id = client_profile.get("family_id")
    if family_id and db_pool:
        try:
            async with db_pool.acquire() as conn:
                fam_rows = await conn.fetch(
                    """SELECT name, role FROM users
                       WHERE family_id = $1::uuid AND hardware_id != $2
                         AND deleted_at IS NULL AND role != 'ADMIN'""",
                    family_id if len(family_id) == 36 else None, client_id,
                )
                family_members = [{"name": r["name"], "role": r["role"], "relationship": "Family Member"} for r in fam_rows]
        except Exception:
            pass
    if not family_members and family_id:
        registry = load_json(DATA_DIR / "user_registry.json") if not client_profile else {}
        if not registry and db_pool:
            registry = await load_registry_pg(db_pool) or {}
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("family_id") == family_id and p.get("hardware_id") != client_id:
                family_members.append({
                    "name": p.get("name"),
                    "role": p.get("role"),
                    "relationship": "Family Member",
                })
    
    # Extract topics from recent conversations
    recent_topics = _extract_recent_topics(memories[-30:])
    
    # Extract breakthroughs
    breakthroughs = _extract_breakthroughs(memories[-50:])
    
    # Identify concerns (high anxiety, risk keywords, etc.)
    concerns = []
    if ns.get("anxiety_level", 0) > 0.5:
        concerns.append({
            "type": "anxiety",
            "severity": "moderate" if ns["anxiety_level"] < 0.7 else "high",
            "note": f"Anxiety level at {ns['anxiety_level']*100:.0f}%"
        })
    if ns.get("depression_indicators", 0) > 0.5:
        concerns.append({
            "type": "depression",
            "severity": "moderate" if ns["depression_indicators"] < 0.7 else "high",
            "note": "Elevated depression indicators detected"
        })
    if ns.get("sleep_issues_mentioned", 0) > 2:
        concerns.append({
            "type": "sleep",
            "severity": "moderate",
            "note": f"Sleep issues mentioned {ns['sleep_issues_mentioned']} times recently"
        })
    if ns.get("risk_level") in ["MEDIUM", "HIGH", "CRITICAL"]:
        concerns.append({
            "type": "risk",
            "severity": ns["risk_level"].lower(),
            "note": f"Risk level: {ns['risk_level']}"
        })
    
    # Get homework from last session
    last_session = completed_sessions[-1] if completed_sessions else None
    pending_homework = []
    if last_session:
        pending_homework = last_session.get("homework_assigned", [])
    
    # Generate Nate's suggestions
    nate_suggestions = _generate_suggestions(ns, recent_topics, breakthroughs, concerns)

    brief_payload = {
        "client": {
            "name": client_profile.get("name"),
            "id": client_id,
            "tier": client_profile.get("tier"),
            "joined_date": client_profile.get("joined_date"),
            "total_sessions": len(completed_sessions),
            "last_session": completed_sessions[-1] if completed_sessions else None
        },
        "metrics": {
            "coherence": f"{ns.get('C_emo', 0.5) * 100:.0f}%",
            "growth_potential": f"{ns.get('GAP', 0.3) * 100:.0f}%",
            "wellness_score": f"{ns.get('Quantum', 0.5) * 100:.0f}%",
            "anxiety": f"{ns.get('anxiety_level', 0) * 100:.0f}%",
            "current_mood": ns.get("mood_current", "neutral"),
            "mood_trend": ns.get("mood_trend", "stable"),
            "risk_level": ns.get("risk_level", "LOW")
        },
        "mood_history": ns.get("mood_history", [])[-7:],
        "recent_topics": recent_topics[:5],
        "recent_breakthroughs": breakthroughs[-3:],
        "concerns": concerns,
        "pending_homework": pending_homework,
        "family_context": {
            "family_id": family_id,
            "members": family_members
        },
        "recent_conversations": [
            {"timestamp": m["timestamp"], "preview": m["user"][:100]} 
            for m in memories[-5:]
        ],
        "nate_suggestions": nate_suggestions,
    }
    if db_pool:
        try:
            from app.services.zoom_learning_registry import enrich_presession_brief_zoom

            brief_payload = await enrich_presession_brief_zoom(
                db_pool, client_id, brief_payload
            )
        except Exception as _zle:
            _logger.debug("presession zoom learning enrich: %s", _zle)
        # QUANTUM-CRYSTAL-ARCH — Dual-COO insight_route → coach pre-session
        try:
            from app.services.rls_context import set_rls_admin

            set_rls_admin()
            async with db_pool.acquire() as conn:
                # Match hardware_id OR username OR users.id — briefs store any of these
                _id_row = await conn.fetchrow(
                    """
                    SELECT id::text AS uid, username, hardware_id
                    FROM users
                    WHERE hardware_id = $1 OR username = $1 OR id::text = $1
                    LIMIT 1
                    """,
                    client_id,
                )
                _match_ids = [client_id]
                if _id_row:
                    for _k in ("uid", "username", "hardware_id"):
                        _v = _id_row.get(_k)
                        if _v and str(_v) not in _match_ids:
                            _match_ids.append(str(_v))
                _ibriefs = await conn.fetch(
                    """
                    SELECT id, source, title, body, created_at, client_user_id
                    FROM coach_insight_briefs
                    WHERE status = 'queued'
                      AND (
                          client_user_id = 'broadcast'
                          OR client_user_id = ANY($1::text[])
                      )
                    ORDER BY created_at DESC
                    LIMIT 8
                    """,
                    _match_ids,
                )
                if _ibriefs:
                    brief_payload["dual_coo_insights"] = [
                        {
                            "id": r["id"],
                            "source": r["source"],
                            "title": r["title"],
                            "body": (r["body"] or "")[:800],
                            "created_at": r["created_at"].isoformat()
                            if r["created_at"] else None,
                        }
                        for r in _ibriefs
                    ]
                    # Client-targeted briefs: mark delivered. Broadcast stays queued
                    # so other coaches still see them (first-viewer must not consume).
                    _targeted = [
                        r["id"]
                        for r in _ibriefs
                        if str(r["client_user_id"] or "") != "broadcast"
                    ]
                    if _targeted:
                        await conn.execute(
                            """
                            UPDATE coach_insight_briefs
                            SET status = 'delivered', delivered_at = NOW()
                            WHERE id = ANY($1::bigint[])
                            """,
                            _targeted,
                        )
        except Exception as _ib_err:
            _logger.debug("presession dual_coo insights: %s", _ib_err)
    return brief_payload


def _extract_recent_topics(memories):
    """Extract topics from conversations"""
    topic_keywords = {
        "anxiety": ["anxious", "anxiety", "worried", "panic", "nervous"],
        "relationships": ["relationship", "partner", "marriage", "family", "friend"],
        "work_stress": ["work", "job", "boss", "career", "stressed"],
        "self_esteem": ["confidence", "worth", "value", "believe in myself"],
        "depression": ["depressed", "sad", "hopeless", "empty"],
        "sleep": ["sleep", "insomnia", "tired", "nightmares"],
        "boundaries": ["boundary", "boundaries", "saying no", "limit"],
        "trauma": ["trauma", "past", "childhood", "flashback"],
        "communication": ["communicate", "express", "tell them", "talk to"]
    }
    
    topic_counts = {}
    for mem in memories:
        text = (mem.get("user", "") + " " + mem.get("ai", "")).lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
    
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"topic": t[0], "mentions": t[1]} for t in sorted_topics]

def _extract_breakthroughs(memories):
    """Find breakthrough moments"""
    breakthrough_phrases = [
        "i realize", "i understand now", "that makes sense",
        "i never thought of it", "aha", "breakthrough",
        "i finally see", "it clicked", "i get it"
    ]
    
    breakthroughs = []
    for mem in memories:
        text = mem.get("user", "").lower()
        if any(phrase in text for phrase in breakthrough_phrases):
            breakthroughs.append({
                "timestamp": mem.get("timestamp"),
                "text": mem.get("user", "")[:200],
                "session_id": mem.get("session_id", "")
            })
    
    return breakthroughs

def _generate_suggestions(metrics, topics, breakthroughs, concerns):
    """Generate coaching suggestions based on data"""
    suggestions = []
    
    # Based on concerns
    for concern in concerns:
        if concern["type"] == "anxiety":
            suggestions.append("Consider starting with a grounding exercise to help manage anxiety.")
        elif concern["type"] == "sleep":
            suggestions.append("Sleep issues have been recurring - explore sleep hygiene and nighttime routine.")
        elif concern["type"] == "depression":
            suggestions.append("Monitor for depressive symptoms. Consider behavioral activation strategies.")
        elif concern["type"] == "risk":
            suggestions.append("⚠️ Elevated risk level - conduct safety check early in session.")
    
    # Based on topics
    topic_names = [t["topic"] for t in topics[:3]]
    if "boundaries" in topic_names:
        suggestions.append("Boundary-setting has been a focus - check in on progress with boundary exercises.")
    if "relationships" in topic_names:
        suggestions.append("Relationships are top of mind - explore communication patterns and needs.")
    
    # Based on breakthroughs
    if breakthroughs:
        suggestions.append(f"Recent breakthrough detected - build on this momentum and reinforce the insight.")
    
    # Based on mood trend
    if metrics.get("mood_trend") == "declining":
        suggestions.append("Mood has been declining - explore what might be contributing to this shift.")
    elif metrics.get("mood_trend") == "improving":
        suggestions.append("Positive mood trend! Acknowledge progress and identify what's working.")
    
    return suggestions if suggestions else ["No specific suggestions - follow client's lead this session."]

@router.post("/notes")
async def add_coach_note(req: CoachNoteRequest, request: Request, user=Depends(get_current_user_id)):
    """Add a note to a client's file"""
    db_pool = getattr(request.app.state, "db_pool", None)

    note_entry = {
        "note": req.note,
        "type": req.note_type,
        "timestamp": str(datetime.now()),
    }

    # PG-first: write to coach_notes table
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO coach_notes (client_id, note, note_type, created_at)
                       VALUES ($1, $2, $3, NOW()) RETURNING id""",
                    req.client_id, req.note, req.note_type,
                )
                if row:
                    note_entry["id"] = row["id"]
        except Exception as e:
            _logger.warning("add_coach_note: PG write failed: %s", e)

    # JSON dual-write
    notes_file = VAULT_ROOT / "Clients" / req.client_id / "coach_notes.json"
    notes = load_json(notes_file, [])
    if "id" not in note_entry:
        note_entry["id"] = len(notes) + 1
    notes.append(note_entry)
    save_json(notes_file, notes)

    shield = _get_coach_shield(request)
    if shield:
        try:
            coach_id = user.get("user_id", "") if isinstance(user, dict) else getattr(user, "user_id", "")
            if coach_id:
                import asyncio
                asyncio.ensure_future(shield.analyze_notes(coach_id))
        except Exception as _e:
            _logger.debug("CoachIntegrityShield note analysis non-blocking: %s", _e)

    return {"message": "Note added", "note": note_entry}

@router.get("/notes/{client_id}")
async def get_coach_notes(client_id: str, request: Request, note_type: str = None, limit: int = 20):
    """Get coach notes for a client"""
    db_pool = getattr(request.app.state, "db_pool", None)

    # PG-first
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                if note_type:
                    rows = await conn.fetch(
                        """SELECT id, note, note_type as type, created_at as timestamp
                           FROM coach_notes
                           WHERE client_id = $1 AND note_type = $2
                           ORDER BY created_at DESC LIMIT $3""",
                        client_id, note_type, limit,
                    )
                else:
                    rows = await conn.fetch(
                        """SELECT id, note, note_type as type, created_at as timestamp
                           FROM coach_notes
                           WHERE client_id = $1
                           ORDER BY created_at DESC LIMIT $2""",
                        client_id, limit,
                    )
                if rows:
                    return {"notes": [
                        {"id": r["id"], "note": r["note"], "type": r["type"],
                         "timestamp": str(r["timestamp"])}
                        for r in rows
                    ]}
        except Exception as e:
            _logger.warning("get_coach_notes: PG read failed: %s", e)

    # JSON fallback
    notes_file = VAULT_ROOT / "Clients" / client_id / "coach_notes.json"
    notes = load_json(notes_file, [])

    if note_type:
        notes = [n for n in notes if n.get("type") == note_type]

    return {"notes": notes[-limit:]}

@router.post("/homework")
async def assign_homework(req: HomeworkRequest):
    """Assign homework to a client"""
    homework_file = VAULT_ROOT / "Clients" / req.client_id / "homework.json"
    homework = load_json(homework_file, [])
    
    entry = {
        "id": len(homework) + 1,
        "assignment": req.homework,
        "assigned_at": str(datetime.now()),
        "due_date": req.due_date,
        "status": "pending",
        "completed_at": None,
        "notes": ""
    }
    
    homework.append(entry)
    save_json(homework_file, homework)
    
    return {"message": "Homework assigned", "homework": entry}

@router.get("/homework/{client_id}")
async def get_client_homework(client_id: str, status: str = None):
    """Get homework for a client"""
    homework_file = VAULT_ROOT / "Clients" / client_id / "homework.json"
    homework = load_json(homework_file, [])
    
    if status:
        homework = [h for h in homework if h.get("status") == status]
    
    return {"homework": homework}

@router.post("/homework/{homework_id}/complete")
async def mark_homework_complete(homework_id: int, client_id: str, notes: str = ""):
    """Mark homework as complete"""
    homework_file = VAULT_ROOT / "Clients" / client_id / "homework.json"
    homework = load_json(homework_file, [])
    
    for h in homework:
        if h.get("id") == homework_id:
            h["status"] = "completed"
            h["completed_at"] = str(datetime.now())
            h["notes"] = notes
            save_json(homework_file, homework)
            return {"message": "Homework marked complete", "homework": h}
    
    raise HTTPException(404, "Homework not found")

@router.get("/stats/{coach_id}")
async def get_coach_stats(coach_id: str, request: Request, caller_hw_id: str = Depends(get_current_user_id)):
    """Get statistics for a coach"""
    shield = _get_coach_shield(request)
    if shield:
        try:
            import asyncio
            asyncio.ensure_future(shield.track_attrition(coach_id))
        except Exception as _e:
            _logger.debug("CoachIntegrityShield attrition non-blocking: %s", _e)

    # IDOR guard: path coach_id must match authenticated caller hardware_id.
    # ADMIN bypass mirrors sessions.py (auditors + Sovereign Command use admin token).
    if str(coach_id) != str(caller_hw_id) and getattr(request.state, "user_role", "") != "ADMIN":
        raise HTTPException(status_code=403, detail="Cannot view another coach's clients")

    db_pool = getattr(request.app.state, "db_pool", None)

    # PG-first: get coach's clients
    client_profiles = []
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                client_rows = await conn.fetch(
                    """SELECT hardware_id, profile_data FROM users
                       WHERE deleted_at IS NULL AND role = 'CLIENT'
                         AND (profile_data->>'assigned_coach_id' = $1
                              OR profile_data->>'coach_id' = $1)""",
                    coach_id,
                )
                for r in client_rows:
                    pd = r.get("profile_data") or {}
                    if isinstance(pd, str):
                        try: pd = json.loads(pd)
                        except Exception: pd = {}
                    pd["hardware_id"] = r["hardware_id"] or ""
                    client_profiles.append(pd)
        except Exception as e:
            _logger.warning("get_coach_stats: PG client lookup failed: %s", e)

    if not client_profiles:
        registry = load_json(DATA_DIR / "user_registry.json")
        for v in registry.values():
            p = v.get("profile", {})
            if p.get("assigned_coach_id") == coach_id or p.get("coach_id") == coach_id:
                client_profiles.append(p)

    # PG-first: get sessions
    coach_sessions = await load_sessions_pg(db_pool, coach_id=coach_id) if db_pool else []
    if not coach_sessions:
        sessions = load_json(DATA_DIR / "sessions.json", [])
        coach_sessions = [s for s in sessions if s.get("coach_id") == coach_id]
    coach_sessions = [s for s in coach_sessions if not _is_external_coach_consultation_row(s)]
    completed = [s for s in coach_sessions if s.get("status") == "completed"]

    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0)
    this_month = [s for s in completed
                  if s.get("actual_end") and
                  datetime.fromisoformat(str(s["actual_end"]).split(".")[0]) >= month_start]

    total_gap = total_wellness = 0
    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}

    for p in client_profiles:
        hw_id = p.get("hardware_id", "")
        pg_metrics = await load_metrics_pg(db_pool, hw_id) if hw_id and db_pool else None
        if pg_metrics:
            ns = pg_metrics.get("nevedal_state", {})
        else:
            metrics_file = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
            ns = load_json(metrics_file, {}).get("nevedal_state", {})

        total_gap += ns.get("GAP", 0.5)
        total_wellness += ns.get("Quantum", 0.5)
        risk = ns.get("risk_level", "LOW")
        if risk in risk_counts:
            risk_counts[risk] += 1

    avg_gap = total_gap / len(client_profiles) if client_profiles else 0
    avg_wellness = total_wellness / len(client_profiles) if client_profiles else 0

    return {
        "clients": {
            "total": len(client_profiles),
            "risk_distribution": risk_counts,
        },
        "sessions": {
            "total": len(coach_sessions),
            "completed": len(completed),
            "this_month": len(this_month),
            "total_hours": sum(s.get("duration_minutes", 0) for s in completed) / 60,
        },
        "client_outcomes": {
            "average_gap": f"{avg_gap * 100:.0f}%",
            "average_wellness": f"{avg_wellness * 100:.0f}%",
        },
    }

@router.get("/ask-nate/{client_id}")
async def ask_nate_about_client(client_id: str, question: str, request: Request):
    """Ask Little Nate a question about a client (for coaching advice)"""
    db_pool = getattr(request.app.state, "db_pool", None)

    # PG-first: find client
    client_profile = await find_user_pg(db_pool, client_id)
    if not client_profile:
        registry = load_json(DATA_DIR / "user_registry.json")
        for v in registry.values():
            if v.get("profile", {}).get("hardware_id") == client_id:
                client_profile = v["profile"]
                break

    if not client_profile:
        raise HTTPException(404, "Client not found")

    pg_metrics = await load_metrics_pg(db_pool, client_id)
    if pg_metrics:
        metrics = pg_metrics
    else:
        metrics_file = VAULT_ROOT / "Clients" / client_id / "metrics.json"
        metrics = load_json(metrics_file, {})

    memory_file = VAULT_ROOT / "Clients" / client_id / "memory.json"
    memories = load_json(memory_file, [])
    
    # In production, this would call Azure OpenAI with the context
    # For now, return a structured response based on available data
    
    ns = metrics.get("nevedal_state", {})
    recent_topics = _extract_recent_topics(memories[-20:])
    
    response = {
        "question": question,
        "client_summary": {
            "name": client_profile.get("name"),
            "current_metrics": {
                "coherence": ns.get("C_emo", 0.5),
                "growth_potential": ns.get("GAP", 0.3),
                "risk_level": ns.get("risk_level", "LOW")
            },
            "recent_focus_areas": [t["topic"] for t in recent_topics[:3]],
            "conversation_count": len(memories)
        },
        "nate_response": f"Based on {client_profile.get('name')}'s data, their current focus areas include {', '.join([t['topic'] for t in recent_topics[:3]])}. Their emotional coherence is at {ns.get('C_emo', 0.5)*100:.0f}% with a GAP score of {ns.get('GAP', 0.3)*100:.0f}%. To answer your specific question about '{question}', I would need to analyze their full conversation history.",
        "note": "For full AI-powered coaching advice, this endpoint will integrate with Azure OpenAI."
    }
    
    return response


# =============================================================================
# MATCHMAKER PROTOCOL — AI Coach Matching
# =============================================================================


@router.post("/matchmaker")
async def run_matchmaker(req: MatchmakerRequest):
    """Run the matchmaker analysis for a client, returning top N coach matches."""
    from app.services.coach_matcher import CoachMatcher

    matcher = CoachMatcher(data_dir=DATA_DIR, vault_root=VAULT_ROOT)
    matches = await matcher.get_top_matches(req.client_id, n=req.top_n)

    if not matches:
        raise HTTPException(404, "No coaches available or client not found")

    return {"client_id": req.client_id, "matches": matches}


class _CoachChatMessage(BaseModel):
    message: str
    mode: Optional[str] = None
    context: Optional[dict] = None


def _resolve_coach_focus_client_id(ctx: dict, user_message: str = "") -> Optional[str]:
    """Resolve hardware_id / username for zoom learning + briefing injection."""
    msg = (user_message or "").lower()

    def _match_roster(message: str) -> Optional[str]:
        if not message:
            return None
        for entry in ctx.get("client_names") or []:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("id") or entry.get("hardware_id") or ""
            name = (entry.get("name") or "").lower()
            username = (entry.get("username") or "").lower()
            if not cid:
                continue
            if name and name in message:
                return str(cid)
            for part in name.split():
                if len(part) >= 3 and part in message:
                    return str(cid)
            if username and username in message:
                return str(cid)
            user_stem = re.sub(r"[0-9@._-]+", "", username)
            if len(user_stem) >= 3 and user_stem in message:
                return str(cid)
            if "zack" in message and "zachary" in name:
                return str(cid)
        return None

    from_msg = _match_roster(msg)
    if from_msg:
        return from_msg

    for key in ("client_id", "focused_client_id"):
        val = (ctx.get(key) or "").strip() if isinstance(ctx.get(key), str) else ctx.get(key)
        if val:
            return str(val)
    briefing = ctx.get("briefing_data") or {}
    if isinstance(briefing, dict):
        cid = briefing.get("client_id")
        client = briefing.get("client")
        if not cid and isinstance(client, dict):
            cid = client.get("id")
        if cid:
            return str(cid)
    return None


@router.post("/nate-chat")
async def coach_nate_chat(
    body: _CoachChatMessage,
    request: Request,
    caller_hw_id: str = Depends(get_current_user_id),
):
    """Coach-accessible Little Nate chat for coaching insights."""
    from app.services.skyeye_chat import SkyEyeChatService
    from app.services.api_server import get_current_user as _get_user

    # SECURITY: The is_master_coach flag and assistant_details previously
    # came from the Flutter client and were trusted. This server-side check
    # prevents privilege escalation by re-deriving master status from
    # coach_hierarchy. Future work: recompute assistant_details from DB
    # too, rather than just stripping.

    coach_username = "unknown_coach"
    try:
        user_profile = await _get_user(request)
        coach_username = user_profile.get("username", "unknown_coach")
    except Exception:
        pass

    db_pool = getattr(request.app.state, "db_pool", None)
    is_master_verified = False
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                is_master_verified = bool(
                    await conn.fetchval(
                        """SELECT 1 FROM coach_hierarchy
                           WHERE master_coach_id = $1 AND status IN ('active', 'accepted')
                           LIMIT 1""",
                        caller_hw_id,
                    )
                )
        except Exception:
            is_master_verified = False

    ctx = dict(body.context) if isinstance(body.context, dict) else {}
    ctx["is_master_coach"] = is_master_verified
    if not is_master_verified:
        ctx.pop("assistant_details", None)
        ctx.pop("focused_assistant", None)
        ctx.pop("focused_assistant_clients", None)

    _focus_client = _resolve_coach_focus_client_id(ctx, body.message)
    if _focus_client:
        ctx["client_id"] = _focus_client
        ctx["focused_client_id"] = _focus_client
    if db_pool and _focus_client and not ctx.get("zoom_session_learning"):
        try:
            from app.services.zoom_learning_registry import build_coach_nate_zoom_context

            _zl = await build_coach_nate_zoom_context(
                db_pool, str(_focus_client), coach_id=caller_hw_id
            )
            if _zl:
                ctx["zoom_session_learning"] = _zl
        except Exception as _znc:
            _logger.debug("coach nate zoom context: %s", _znc)

    service = SkyEyeChatService(db_pool)
    mode = body.mode if body.mode else "inquiry"
    return await service.send_coach_message(
        user_message=body.message,
        coach_username=coach_username,
        context=ctx,
        mode_override=mode,
    )


class ClientOverrideBody(BaseModel):
    client_user_id: str
    notes: Optional[str] = None
    focus_domain: Optional[str] = None
    pacing: Optional[str] = None
    clinical_hold: Optional[bool] = None
    override_reason: Optional[str] = None


@router.post("/client-override")
async def set_client_override_rest(
    body: ClientOverrideBody,
    request: Request,
    user=Depends(get_current_user_id),
):
    """REST write path for coach_client_overrides → Dual-COO coach-label loop.

    Complements WebSocket coach_set_client_override so labels can land without
    a live bridge session. Crystallizes notes into coach observation crystals.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "DATABASE_UNAVAILABLE")
    coach_ref = user if isinstance(user, str) else str(
        (user or {}).get("hardware_id")
        or (user or {}).get("username")
        or (user or {}).get("user_id")
        or ""
    )
    client_ref = (body.client_user_id or "").strip()
    if not coach_ref or not client_ref:
        raise HTTPException(400, "coach and client_user_id required")
    notes = (body.notes or "").strip() or None
    if notes:
        notes = notes[:8000]
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO coach_client_overrides (
                coach_user_id, client_user_id, focus_domain, pacing,
                clinical_hold, notes, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (coach_user_id, client_user_id) DO UPDATE SET
                focus_domain = COALESCE(EXCLUDED.focus_domain, coach_client_overrides.focus_domain),
                pacing = COALESCE(EXCLUDED.pacing, coach_client_overrides.pacing),
                clinical_hold = COALESCE(EXCLUDED.clinical_hold, coach_client_overrides.clinical_hold),
                notes = COALESCE(EXCLUDED.notes, coach_client_overrides.notes),
                updated_at = NOW()
            """,
            coach_ref,
            client_ref,
            body.focus_domain,
            body.pacing,
            body.clinical_hold,
            notes,
        )
    crystal_hash = None
    if notes and len(notes) > 8:
        try:
            from app.websocket.crystal_recall_bridge import crystallize_coach_observation

            crystal_hash = await crystallize_coach_observation(
                db_pool,
                coach_ref,
                client_ref,
                notes,
                domain="clinical",
                observation_type="coach_override",
            )
        except Exception as e:
            _logger.warning("client-override crystallize: %s", e)
    return {
        "status": "ok",
        "coach_user_id": coach_ref,
        "client_user_id": client_ref,
        "crystal_hash": crystal_hash,
        "reason": (body.override_reason or "")[:200],
    }
