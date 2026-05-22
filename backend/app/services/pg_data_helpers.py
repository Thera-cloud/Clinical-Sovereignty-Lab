"""
PG Data Helpers — shared async functions for PG-first reads across all routers.

Every router that previously read from JSON files should import from here.
Pattern: PG first, JSON fallback. Dual-write on mutations.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry / Users helpers
# ---------------------------------------------------------------------------

async def load_registry_pg(db_pool) -> Dict[str, Any]:
    """Load user registry from PG users table. Returns dict keyed by 'role_username'."""
    if not db_pool:
        return {}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT username, role, name, email, hardware_id,
                          password_hash, tier, subscription_status,
                          consent_version, family_id, token_balance,
                          profile_data, login_count
                   FROM users WHERE deleted_at IS NULL"""
            )
            registry = {}
            for r in rows:
                key = f"{(r['role'] or 'CLIENT').lower()}_{r['username']}"
                profile = dict(r.get("profile_data") or {}) if r.get("profile_data") else {}
                if isinstance(profile, str):
                    try:
                        profile = json.loads(profile)
                    except Exception:
                        profile = {}
                profile.update({
                    "username": r["username"],
                    "name": r.get("name") or "",
                    "email": r.get("email") or "",
                    "hardware_id": r.get("hardware_id") or "",
                    "role": r.get("role") or "CLIENT",
                    "tier": r.get("tier") or "TRIAL",
                    "subscription_status": r.get("subscription_status") or "TRIAL_ACTIVE",
                    "consent_version": r.get("consent_version") or "",
                    "token_balance": r.get("token_balance") or 0,
                    "login_count": r.get("login_count") or 0,
                })
                if r.get("family_id"):
                    profile["family_id"] = str(r["family_id"])

                entry = {"profile": profile}
                if r.get("password_hash"):
                    entry["credentials"] = {"password": r["password_hash"]}
                registry[key] = entry
            return registry
    except Exception as e:
        logger.warning("load_registry_pg failed: %s", e)
        return {}


async def find_user_pg(db_pool, hardware_id: str) -> Optional[Dict]:
    """Find a single user by hardware_id. Returns profile dict or None."""
    if not db_pool or not hardware_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT username, role, name, email, hardware_id,
                          tier, subscription_status, token_balance,
                          profile_data, family_id
                   FROM users WHERE hardware_id = $1 AND deleted_at IS NULL
                   LIMIT 1""",
                hardware_id,
            )
            if not row:
                return None
            raw_pd = row.get("profile_data") or {}
            if isinstance(raw_pd, str):
                try:
                    raw_pd = json.loads(raw_pd)
                except Exception:
                    raw_pd = {}
            profile = dict(raw_pd) if isinstance(raw_pd, dict) else {}
            profile.update({
                "username": row["username"],
                "name": row.get("name") or "",
                "email": row.get("email") or "",
                "hardware_id": row.get("hardware_id") or "",
                "role": row.get("role") or "CLIENT",
                "tier": row.get("tier") or "TRIAL",
                "subscription_status": row.get("subscription_status") or "TRIAL_ACTIVE",
                "token_balance": row.get("token_balance") or 0,
            })
            if row.get("family_id"):
                profile["family_id"] = str(row["family_id"])
            return profile
    except Exception as e:
        logger.warning("find_user_pg(%s) failed: %s", hardware_id, e)
        return None


async def find_user_by_username_pg(db_pool, username: str) -> Optional[Dict]:
    """Find a single user by username."""
    if not db_pool or not username:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT username, role, name, email, hardware_id,
                          tier, subscription_status, token_balance,
                          profile_data, family_id
                   FROM users WHERE username = $1 AND deleted_at IS NULL
                   LIMIT 1""",
                username,
            )
            if not row:
                return None
            raw_pd = row.get("profile_data") or {}
            if isinstance(raw_pd, str):
                try:
                    raw_pd = json.loads(raw_pd)
                except Exception:
                    raw_pd = {}
            profile = dict(raw_pd) if isinstance(raw_pd, dict) else {}
            profile.update({
                "username": row["username"],
                "name": row.get("name") or "",
                "email": row.get("email") or "",
                "hardware_id": row.get("hardware_id") or "",
                "role": row.get("role") or "CLIENT",
                "tier": row.get("tier") or "TRIAL",
                "subscription_status": row.get("subscription_status") or "TRIAL_ACTIVE",
                "token_balance": row.get("token_balance") or 0,
            })
            if row.get("family_id"):
                profile["family_id"] = str(row["family_id"])
            return profile
    except Exception as e:
        logger.warning("find_user_by_username_pg(%s) failed: %s", username, e)
        return None


# ---------------------------------------------------------------------------
# Coaching Sessions helpers
# ---------------------------------------------------------------------------

def _parse_ts(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def load_sessions_pg(db_pool, **filters) -> List[Dict]:
    """Load coaching sessions from PG. Supports filters: client_id, coach_id, status."""
    if not db_pool:
        return []
    try:
        conditions = []
        params = []
        idx = 1
        if filters.get("client_id"):
            conditions.append(f"client_id = ${idx}")
            params.append(filters["client_id"])
            idx += 1
        if filters.get("coach_id"):
            conditions.append(f"coach_id = ${idx}")
            params.append(filters["coach_id"])
            idx += 1
        if filters.get("status"):
            conditions.append(f"status = ${idx}")
            params.append(filters["status"])
            idx += 1

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""SELECT session_id, client_id, coach_id, family_id, client_name,
                           session_type, status, scheduled_start, scheduled_end,
                           actual_start, actual_end, duration_minutes, zoom_link,
                           zoom_meeting_id, zoom_host_url, notes, coach_notes,
                           topics_covered, homework_assigned, mood_at_start,
                           mood_at_end, nate_summary, recording_url, session_data,
                           payment_status, created_at, updated_at,
                           session_data->>'consultation_email' AS consultation_email,
                           session_data->>'consultation_name' AS consultation_name,
                           session_data->>'consultation_subject' AS consultation_subject
                    FROM coaching_sessions{where}
                    ORDER BY scheduled_start DESC NULLS LAST"""

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            sessions = []
            for r in rows:
                s = {
                    "session_id": r["session_id"],
                    "client_id": r["client_id"],
                    "coach_id": r["coach_id"],
                    "family_id": r.get("family_id") or "",
                    "client_name": r.get("client_name") or "",
                    "session_type": r.get("session_type") or "COACH",
                    "status": r.get("status") or "scheduled",
                    "scheduled_start": str(r["scheduled_start"]) if r.get("scheduled_start") else None,
                    "scheduled_end": str(r["scheduled_end"]) if r.get("scheduled_end") else None,
                    "actual_start": str(r["actual_start"]) if r.get("actual_start") else None,
                    "actual_end": str(r["actual_end"]) if r.get("actual_end") else None,
                    "duration_minutes": r.get("duration_minutes") or 0,
                    "zoom_link": r.get("zoom_link") or "",
                    "zoom_meeting_id": r.get("zoom_meeting_id") or "",
                    "zoom_host_url": r.get("zoom_host_url") or "",
                    "notes": r.get("notes") or "",
                    "coach_notes": r.get("coach_notes") or "",
                    "topics_covered": r.get("topics_covered") or [],
                    "homework_assigned": r.get("homework_assigned") or [],
                    "mood_at_start": r.get("mood_at_start") or "",
                    "mood_at_end": r.get("mood_at_end") or "",
                    "nate_summary": r.get("nate_summary") or "",
                    "recording_url": r.get("recording_url") or "",
                    "payment_status": r.get("payment_status") or "pending",
                    "created_at": str(r["created_at"]) if r.get("created_at") else "",
                    "consultation_email": r.get("consultation_email") or "",
                    "consultation_name": r.get("consultation_name") or "",
                    "consultation_subject": r.get("consultation_subject") or "",
                }
                extra = r.get("session_data")
                if extra and isinstance(extra, dict):
                    for k, v in extra.items():
                        if k not in s:
                            s[k] = v
                sessions.append(s)
            return sessions
    except Exception as e:
        logger.warning("load_sessions_pg failed: %s", e)
        return []


async def upsert_session_pg(db_pool, session: Dict) -> bool:
    """Upsert a single coaching session to PG. Returns True on success."""
    if not db_pool or not session.get("session_id"):
        return False
    try:
        known_keys = {
            "session_id", "client_id", "coach_id", "family_id", "client_name",
            "session_type", "status", "scheduled_start", "scheduled_end",
            "actual_start", "actual_end", "duration_minutes", "zoom_link",
            "zoom_meeting_id", "zoom_host_url", "notes", "coach_notes",
            "topics_covered", "homework_assigned", "mood_at_start", "mood_at_end",
            "nate_summary", "recording_url", "payment_status", "created_at",
            "intake_note",
        }
        extra = {k: v for k, v in session.items() if k not in known_keys and k != "updated_at"}
        for _consult_key in ("consultation_email", "consultation_name", "consultation_subject"):
            if session.get(_consult_key):
                extra[_consult_key] = session[_consult_key]
        payment_status = str(session.get("payment_status") or "pending")[:32]
        start_ts = _parse_ts(session.get("scheduled_start"))
        payment_due_at = start_ts - timedelta(hours=72) if start_ts else None
        cancellation_deadline = start_ts - timedelta(hours=24) if start_ts else None

        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO coaching_sessions
                    (session_id, client_id, coach_id, family_id, client_name,
                     session_type, status, scheduled_start, scheduled_end,
                     scheduled_at, payment_due_at, cancellation_deadline,
                     actual_start, actual_end, duration_minutes, zoom_link,
                     zoom_meeting_id, zoom_host_url, notes, coach_notes,
                     topics_covered, homework_assigned, mood_at_start,
                     mood_at_end, nate_summary, recording_url, payment_status,
                     intake_note, session_data, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30)
                   ON CONFLICT (session_id) DO UPDATE SET
                     client_id = EXCLUDED.client_id,
                     coach_id = EXCLUDED.coach_id,
                     family_id = EXCLUDED.family_id,
                     client_name = EXCLUDED.client_name,
                     session_type = EXCLUDED.session_type,
                     status = EXCLUDED.status,
                     scheduled_start = EXCLUDED.scheduled_start,
                     scheduled_end = EXCLUDED.scheduled_end,
                     scheduled_at = COALESCE(EXCLUDED.scheduled_start, EXCLUDED.scheduled_at),
                     payment_due_at = EXCLUDED.payment_due_at,
                     cancellation_deadline = EXCLUDED.cancellation_deadline,
                     actual_start = EXCLUDED.actual_start,
                     actual_end = EXCLUDED.actual_end,
                     duration_minutes = EXCLUDED.duration_minutes,
                     zoom_link = EXCLUDED.zoom_link,
                     zoom_meeting_id = EXCLUDED.zoom_meeting_id,
                     zoom_host_url = EXCLUDED.zoom_host_url,
                     notes = EXCLUDED.notes,
                     coach_notes = EXCLUDED.coach_notes,
                     topics_covered = EXCLUDED.topics_covered,
                     homework_assigned = EXCLUDED.homework_assigned,
                     mood_at_start = EXCLUDED.mood_at_start,
                     mood_at_end = EXCLUDED.mood_at_end,
                     nate_summary = EXCLUDED.nate_summary,
                     recording_url = EXCLUDED.recording_url,
                     payment_status = EXCLUDED.payment_status,
                     intake_note = EXCLUDED.intake_note,
                     session_data = COALESCE(coaching_sessions.session_data, '{}'::jsonb)
                                    || COALESCE(EXCLUDED.session_data, '{}'::jsonb)""",
                session.get("session_id"),
                session.get("client_id", ""),
                session.get("coach_id", ""),
                session.get("family_id", ""),
                session.get("client_name", ""),
                session.get("session_type", "COACH"),
                session.get("status", "scheduled"),
                start_ts,
                _parse_ts(session.get("scheduled_end")),
                start_ts,
                payment_due_at,
                cancellation_deadline,
                _parse_ts(session.get("actual_start")),
                _parse_ts(session.get("actual_end")),
                int(session.get("duration_minutes") or 0),
                session.get("zoom_link", ""),
                session.get("zoom_meeting_id", ""),
                session.get("zoom_host_url", ""),
                session.get("notes", ""),
                session.get("coach_notes", ""),
                json.dumps(session.get("topics_covered") or []),
                json.dumps(session.get("homework_assigned") or []),
                session.get("mood_at_start", ""),
                session.get("mood_at_end", ""),
                session.get("nate_summary", ""),
                session.get("recording_url", ""),
                payment_status,
                session.get("intake_note", ""),
                json.dumps(extra),
                _parse_ts(session.get("created_at")) or datetime.now(timezone.utc),
            )
        return True
    except Exception as e:
        logger.warning("upsert_session_pg(%s) failed: %s", session.get("session_id"), e)
        return False


async def delete_session_pg(db_pool, session_id: str) -> bool:
    """Hard-delete a session from PG."""
    if not db_pool or not session_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM coaching_sessions WHERE session_id = $1", session_id
            )
        return True
    except Exception as e:
        logger.warning("delete_session_pg(%s) failed: %s", session_id, e)
        return False


# ---------------------------------------------------------------------------
# Classroom lived wisdom (session analyses)
# ---------------------------------------------------------------------------

def normalize_classroom_analysis_for_pg(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize analyzer / vault-shaped dicts for upsert_classroom_analysis_pg."""
    from dataclasses import asdict, is_dataclass

    if not analysis:
        return {}
    d = dict(analysis)
    m = d.get("metrics")
    if m is None:
        d["metrics"] = {}
    elif isinstance(m, dict):
        pass
    elif is_dataclass(m):
        d["metrics"] = asdict(m)
    else:
        try:
            d["metrics"] = dict(m)
        except Exception:
            d["metrics"] = {}
    st = str(d.get("status") or "").strip().lower()
    if st == "analyzed":
        d["status"] = "completed"
    elif not st:
        if d.get("ai_analysis_pending") is True:
            d["status"] = "assessing"
        elif float(d.get("therapeutic_presence_score") or 0) > 0 or d.get("strengths"):
            d["status"] = "completed"
        else:
            d["status"] = "pending_dojo_selection"
    try:
        d["therapeutic_presence_score"] = float(d.get("therapeutic_presence_score") or 0)
    except Exception:
        d["therapeutic_presence_score"] = 0.0
    return d


async def upsert_classroom_analysis_pg(db_pool, analysis: Dict) -> bool:
    """
    Persist classroom session analysis to PG so lived wisdom is not lost.
    Called after ClassroomAnalyzer.analyze_transcript() from archive flow.
    """
    if not db_pool or not analysis or not analysis.get("session_id"):
        return False
    try:
        analysis = normalize_classroom_analysis_for_pg(analysis)
        session_id = analysis.get("session_id", "")
        coach_id = analysis.get("coach_id", "")
        client_id = analysis.get("client_id", "")
        client_name = (analysis.get("client_name") or "")[:256]
        family_id = (analysis.get("family_id") or "")[:128]
        status = analysis.get("status", "pending_dojo_selection")
        if status == "analyzed":
            status = "completed"
        if status not in ("pending_dojo_selection", "assessing", "completed"):
            status = "pending_dojo_selection"
        analyzed_at = analysis.get("analyzed_at")
        if not analyzed_at:
            analyzed_at = datetime.now(timezone.utc)
        elif isinstance(analyzed_at, str):
            try:
                analyzed_at = datetime.fromisoformat(analyzed_at.replace("Z", "+00:00"))
            except Exception:
                analyzed_at = datetime.now(timezone.utc)
        if analyzed_at and not getattr(analyzed_at, "tzinfo", None):
            analyzed_at = analyzed_at.replace(tzinfo=timezone.utc) if hasattr(analyzed_at, "replace") else datetime.now(timezone.utc)
        transcript_hash = (analysis.get("transcript_hash") or "")[:64]
        metrics = analysis.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        therapeutic_presence_score = float(analysis.get("therapeutic_presence_score") or 0)
        payload = {k: v for k, v in analysis.items() if k not in (
            "session_id", "coach_id", "client_id", "client_name", "family_id",
            "status", "analyzed_at", "transcript_hash", "metrics", "therapeutic_presence_score",
            "selected_dojos", "assessments", "final_assessment_doc_id", "completed_at", "cee_signals"
        )}
        try:
            payload_json = json.dumps(payload, default=str)
        except Exception:
            payload_json = "{}"
        selected_dojos = analysis.get("selected_dojos") or []
        assessments = analysis.get("assessments") or {}
        cee_signals = analysis.get("cee_signals") or []
        final_assessment_doc_id = (analysis.get("final_assessment_doc_id") or "")[:256]
        completed_at = analysis.get("completed_at")

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO classroom_session_analyses (
                    session_id, coach_id, client_id, client_name, family_id,
                    status, analyzed_at, transcript_hash, metrics, therapeutic_presence_score,
                    selected_dojos, assessments, cee_signals, final_assessment_doc_id, completed_at,
                    payload, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11::jsonb, $12::jsonb, $13::jsonb, $14, $15, $16::jsonb, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    coach_id = EXCLUDED.coach_id,
                    client_id = EXCLUDED.client_id,
                    client_name = EXCLUDED.client_name,
                    family_id = EXCLUDED.family_id,
                    status = EXCLUDED.status,
                    analyzed_at = EXCLUDED.analyzed_at,
                    transcript_hash = EXCLUDED.transcript_hash,
                    metrics = EXCLUDED.metrics,
                    therapeutic_presence_score = EXCLUDED.therapeutic_presence_score,
                    selected_dojos = EXCLUDED.selected_dojos,
                    assessments = EXCLUDED.assessments,
                    cee_signals = EXCLUDED.cee_signals,
                    final_assessment_doc_id = EXCLUDED.final_assessment_doc_id,
                    completed_at = EXCLUDED.completed_at,
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
            """,
                session_id, coach_id, client_id, client_name, family_id,
                status, analyzed_at, transcript_hash, json.dumps(metrics), therapeutic_presence_score,
                json.dumps(selected_dojos if isinstance(selected_dojos, list) else []),
                json.dumps(assessments if isinstance(assessments, dict) else {}),
                json.dumps(cee_signals if isinstance(cee_signals, list) else []),
                final_assessment_doc_id or None,
                completed_at,
                payload_json,
            )
        return True
    except Exception as e:
        logger.warning("upsert_classroom_analysis_pg failed: %s", e)
        return False


async def load_classroom_analyses_pg(db_pool, coach_id: Optional[str] = None, client_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Load classroom session analyses from PG for REST/INSIGHTS."""
    if not db_pool:
        return []
    try:
        conditions, params = [], []
        idx = 1
        if coach_id:
            conditions.append(f"coach_id = ${idx}")
            params.append(coach_id)
            idx += 1
        if client_id:
            conditions.append(f"client_id = ${idx}")
            params.append(client_id)
            idx += 1
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT session_id, coach_id, client_id, client_name, family_id, status,
                           analyzed_at, transcript_hash, therapeutic_presence_score,
                           selected_dojos, assessments, final_assessment_doc_id, completed_at,
                           payload, created_at
                    FROM classroom_session_analyses{where}
                    ORDER BY analyzed_at DESC NULLS LAST
                    LIMIT ${idx}""",
                *params
            )
            out = []
            for r in rows:
                rec = dict(r)
                for jk in ("payload", "assessments", "selected_dojos"):
                    if rec.get(jk) and isinstance(rec[jk], str):
                        try:
                            rec[jk] = json.loads(rec[jk])
                        except Exception:
                            pass
                if rec.get("payload") and isinstance(rec["payload"], dict):
                    rec.update(rec["payload"])
                out.append(rec)
            return out
    except Exception as e:
        logger.warning("load_classroom_analyses_pg failed: %s", e)
        return []


async def get_classroom_analysis_pg(db_pool, session_id: str) -> Optional[Dict]:
    """Load a single classroom session analysis by session_id."""
    if not db_pool or not session_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            r = await conn.fetchrow(
                """SELECT session_id, coach_id, client_id, client_name, family_id, status,
                          analyzed_at, transcript_hash, metrics, therapeutic_presence_score,
                          selected_dojos, assessments, final_assessment_doc_id, completed_at,
                          payload, created_at
                   FROM classroom_session_analyses WHERE session_id = $1""",
                session_id,
            )
            if not r:
                return None
            rec = dict(r)
            for jk in ("metrics", "payload", "assessments", "cee_signals", "selected_dojos"):
                if rec.get(jk) and isinstance(rec[jk], str):
                    try:
                        rec[jk] = json.loads(rec[jk])
                    except Exception:
                        pass
            if rec.get("payload") and isinstance(rec["payload"], dict):
                rec.update(rec["payload"])
            return rec
    except Exception as e:
        logger.warning("get_classroom_analysis_pg failed: %s", e)
        return None


async def update_classroom_analysis_pg(
    db_pool,
    session_id: str,
    *,
    status: Optional[str] = None,
    selected_dojos: Optional[List] = None,
    assessments: Optional[Dict] = None,
    therapeutic_presence_score: Optional[float] = None,
    final_assessment_doc_id: Optional[str] = None,
    completed_at: Optional[datetime] = None,
) -> bool:
    """Update fields on a classroom_session_analyses row."""
    if not db_pool or not session_id:
        return False
    try:
        updates, params = [], [session_id]
        idx = 2
        if status is not None:
            updates.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if selected_dojos is not None:
            updates.append(f"selected_dojos = ${idx}::jsonb")
            params.append(json.dumps(selected_dojos))
            idx += 1
        if assessments is not None:
            updates.append(f"assessments = ${idx}::jsonb")
            params.append(json.dumps(assessments))
            idx += 1
        if therapeutic_presence_score is not None:
            updates.append(f"therapeutic_presence_score = ${idx}")
            params.append(therapeutic_presence_score)
            idx += 1
        if final_assessment_doc_id is not None:
            updates.append(f"final_assessment_doc_id = ${idx}")
            params.append(final_assessment_doc_id[:256])
            idx += 1
        if completed_at is not None:
            updates.append(f"completed_at = ${idx}")
            params.append(completed_at)
            idx += 1
        if not updates:
            return True
        updates.append("updated_at = NOW()")
        q = f"UPDATE classroom_session_analyses SET {', '.join(updates)} WHERE session_id = $1"
        async with db_pool.acquire() as conn:
            await conn.execute(q, *params)
        return True
    except Exception as e:
        logger.warning("update_classroom_analysis_pg failed: %s", e)
        return False


async def get_master_for_assistant_pg(db_pool, assistant_id: str) -> Optional[str]:
    """Return master_coach_id for an assistant from coach_hierarchy (accepted/active only)."""
    if not db_pool or not assistant_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT master_coach_id FROM coach_hierarchy
                   WHERE assistant_id = $1 AND status IN ('accepted', 'active') AND revoked_at IS NULL
                   LIMIT 1""",
                assistant_id,
            )
            return row["master_coach_id"] if row else None
    except Exception as e:
        logger.warning("get_master_for_assistant_pg failed: %s", e)
        return None


async def get_classroom_progress_pg(db_pool, coach_id: str) -> Dict:
    """Compute YOUR PROGRESS stats from classroom_session_analyses + video analyses for a coach."""
    empty = {
        "total_sessions_reviewed": 0, "average_presence_score": 0.0,
        "pending": 0, "assessing": 0, "completed": 0, "sessions": [],
        "growth_trajectory": [], "quantum_trajectory": [], "gap_trajectory": [],
        "cee_summary": {"total_windows": 0, "avg_readiness": 0.0},
        "coherence_trend": "no_data", "session_clients": [],
    }
    if not db_pool or not coach_id:
        return empty
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT session_id, client_name, status, therapeutic_presence_score, selected_dojos, analyzed_at, completed_at
                   FROM classroom_session_analyses WHERE coach_id = $1 ORDER BY analyzed_at DESC LIMIT 100""",
                coach_id,
            )
        total = len(rows) if rows else 0
        pending = sum(1 for r in rows if r["status"] == "pending_dojo_selection") if rows else 0
        assessing = sum(1 for r in rows if r["status"] == "assessing") if rows else 0
        completed = sum(1 for r in rows if r["status"] == "completed") if rows else 0

        all_scores = []
        growth_trajectory = []
        session_clients = set()
        sessions_list = []

        for r in (rows or []):
            score = r["therapeutic_presence_score"] or 0
            client = r["client_name"] or ""
            if client:
                session_clients.add(client)
            if score and r["status"] == "completed":
                all_scores.append(score)
            dt = r["analyzed_at"].isoformat() if r["analyzed_at"] else None
            growth_trajectory.append({"date": dt, "score": float(score), "client": client})
            sessions_list.append({
                "session_id": r["session_id"],
                "client_name": client,
                "status": r["status"],
                "therapeutic_presence_score": score,
                "selected_dojos": r["selected_dojos"] if r["selected_dojos"] else [],
                "analyzed_at": dt,
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            })

        quantum_trajectory = []
        gap_trajectory = []
        cee_total = 0
        cee_readiness_values = []

        try:
            from pathlib import Path
            backend_sessions = {}
            bridge_sessions = {}
            for label, candidate in [
                ("backend", Path("/app/data/classroom_sessions.json")),
                ("bridge", Path("/app/bridge_data/classroom_sessions.json")),
            ]:
                if not candidate.exists():
                    continue
                try:
                    with open(candidate, 'r') as f:
                        raw = json.load(f)
                    target = backend_sessions if label == "backend" else bridge_sessions
                    for vs in raw:
                        sid = vs.get("session_id")
                        if sid:
                            target[sid] = vs
                except Exception:
                    continue

            merged_video = {}
            for sid, vs in backend_sessions.items():
                merged_video[sid] = vs
            for sid, vs in bridge_sessions.items():
                if vs.get("analysis"):
                    merged_video[sid] = vs
                elif sid not in merged_video:
                    merged_video[sid] = vs

            for vs in merged_video.values():
                if vs.get("coach_id") != coach_id:
                    continue
                analysis = vs.get("analysis", {})
                if not analysis or analysis.get("status") != "analyzed":
                    continue
                score = analysis.get("therapeutic_presence_score", 0)
                client = analysis.get("client_name", "")
                dt = analysis.get("analyzed_at", "")
                if client:
                    session_clients.add(client)
                if score:
                    all_scores.append(float(score))
                    total += 1
                    completed += 1
                growth_trajectory.append({"date": dt, "score": float(score or 0), "client": client})

                qca = analysis.get("quantum_coherence_assessment", {})
                if qca:
                    quantum_trajectory.append({
                        "date": dt,
                        "c_emo": qca.get("c_emo_estimate", 0),
                        "gap": qca.get("gap_score", 0),
                        "quantum": qca.get("quantum_score", 0),
                        "p_ent": qca.get("p_ent_estimate", 0),
                        "client": client,
                    })
                ga = analysis.get("gap_analysis", {})
                if ga:
                    gap_trajectory.append({
                        "date": dt,
                        "attunement": ga.get("attunement_level", "unknown"),
                        "velocity": ga.get("velocity", "stable"),
                        "client": client,
                    })
                cee = analysis.get("cee_assessment", {})
                if cee:
                    cee_total += (cee.get("cee_windows_identified") or 0)
                    r_val = cee.get("reconsolidation_readiness")
                    if r_val and isinstance(r_val, (int, float)):
                        cee_readiness_values.append(float(r_val))
        except Exception:
            pass

        # Compute coherence trend from quantum trajectory
        coherence_trend = "no_data"
        if len(quantum_trajectory) >= 2:
            half = len(quantum_trajectory) // 2
            avg_first = sum(q["c_emo"] for q in quantum_trajectory[:half]) / half
            avg_second = sum(q["c_emo"] for q in quantum_trajectory[half:]) / (len(quantum_trajectory) - half)
            if avg_second > avg_first + 0.05:
                coherence_trend = "improving"
            elif avg_second < avg_first - 0.05:
                coherence_trend = "declining"
            else:
                coherence_trend = "stable"

        avg_score = round(sum(all_scores) / max(len(all_scores), 1), 2) if all_scores else 0.0

        return {
            "total_sessions_reviewed": total,
            "average_presence_score": avg_score,
            "pending": pending,
            "assessing": assessing,
            "completed": completed,
            "sessions": sessions_list,
            "growth_trajectory": growth_trajectory,
            "quantum_trajectory": quantum_trajectory,
            "gap_trajectory": gap_trajectory,
            "cee_summary": {
                "total_windows": cee_total,
                "avg_readiness": round(sum(cee_readiness_values) / max(len(cee_readiness_values), 1), 3) if cee_readiness_values else 0.0,
            },
            "coherence_trend": coherence_trend,
            "session_clients": list(session_clients),
        }
    except Exception as e:
        logger.warning("get_classroom_progress_pg failed: %s", e)
        return empty


async def place_assessment_in_folder_pg(db_pool, coach_id: str, client_id: str, client_name: str, doc_id: str, assessment_text: str) -> Optional[str]:
    """Place the PhD-level assessment document in the coach's FOLDER for the client."""
    if not db_pool or not coach_id or not client_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            folder = await conn.fetchrow(
                "SELECT id FROM coach_folders WHERE coach_id = $1 AND entity_id = $2 AND folder_type = 'client' LIMIT 1",
                coach_id, client_id,
            )
            if not folder:
                folder = await conn.fetchrow(
                    """INSERT INTO coach_folders (coach_id, folder_type, entity_id, entity_name)
                       VALUES ($1, 'client', $2, $3) RETURNING id""",
                    coach_id, client_id, client_name or client_id,
                )
            folder_id = folder["id"]
            filename = f"PhD_Assessment_{client_name or client_id}_{doc_id[-12:]}.md"
            row = await conn.fetchrow(
                """INSERT INTO coach_folder_files (folder_id, filename, file_type, storage_url, file_size_bytes, uploaded_by, metadata)
                   VALUES ($1, $2, 'assessment', $3, $4, 'Little Nate', $5::jsonb)
                   RETURNING id""",
                folder_id, filename, f"inline://{doc_id}", len(assessment_text.encode("utf-8")),
                json.dumps({"source": "classroom_assessment", "doc_id": doc_id, "content": assessment_text[:50000]}),
            )
            file_id = str(row["id"])
            return file_id
    except Exception as e:
        logger.warning("place_assessment_in_folder_pg failed: %s", e)
        return None


async def get_classroom_context_for_client_pg(db_pool, client_id: str, limit: int = 3) -> str:
    """Build session context for Little Nate when talking to a client (E1)."""
    if not db_pool or not client_id:
        return ""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT session_id, client_name, analyzed_at, therapeutic_presence_score,
                          assessments, payload, metrics, status
                   FROM classroom_session_analyses
                   WHERE client_id = $1 AND status = 'completed'
                   ORDER BY analyzed_at DESC LIMIT $2""",
                client_id, limit,
            )
        if not rows:
            return ""
        parts = ["[SESSION COACHING INSIGHTS — What the coach worked on with this client]"]
        for r in rows:
            dt = r["analyzed_at"].strftime("%b %d, %Y") if r["analyzed_at"] else "recent"
            _p = r["payload"]
            if isinstance(_p, str):
                try:
                    _p = json.loads(_p)
                except Exception:
                    _p = {}
            payload = _p if isinstance(_p, dict) else {}
            strengths = payload.get("strengths", [])
            growth = payload.get("growth_areas", [])
            reflection = payload.get("reflection_questions", [])
            takeaways = []
            if strengths:
                takeaways.append(f"Strengths observed: {', '.join(strengths[:3])}")
            if growth:
                takeaways.append(f"Growth areas: {', '.join(growth[:3])}")
            if reflection:
                takeaways.append(f"Reflection: {reflection[0]}")
            parts.append(f"Session {dt}: {'; '.join(takeaways) if takeaways else 'Session analyzed.'}")
        parts.append("Use these insights to gently support the client. Reflect without contradicting the coach's approach. Do not share raw assessment details.")
        return "\n".join(parts)
    except Exception as e:
        logger.warning("get_classroom_context_for_client_pg failed: %s", e)
        return ""


async def get_classroom_lived_wisdom_pg(db_pool, coach_id: str, client_id: Optional[str] = None, limit: int = 5) -> str:
    """Build lived-wisdom context for INSIGHTS Q&A — coaches can ask Nate what was captured."""
    if not db_pool or not coach_id:
        return ""
    try:
        conds, params = ["coach_id = $1"], [coach_id]
        idx = 2
        if client_id:
            conds.append(f"client_id = ${idx}")
            params.append(client_id)
            idx += 1
        params.append(limit)
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT session_id, client_name, analyzed_at, status, therapeutic_presence_score,
                           metrics, assessments, payload, cee_signals, selected_dojos, completed_at
                    FROM classroom_session_analyses
                    WHERE {' AND '.join(conds)}
                    ORDER BY analyzed_at DESC LIMIT ${idx}""",
                *params,
            )
        if not rows:
            return ""
        parts = ["[LIVED WISDOM — What Little Nate captured from coaching sessions]"]
        for r in rows:
            dt = r["analyzed_at"].strftime("%b %d, %Y") if r["analyzed_at"] else "recent"
            name = r["client_name"] or r["session_id"]
            status = r["status"] or "unknown"
            score = r["therapeutic_presence_score"] or 0
            _raw_p = r["payload"]
            if isinstance(_raw_p, str):
                try:
                    _raw_p = json.loads(_raw_p)
                except Exception:
                    _raw_p = {}
            payload = _raw_p if isinstance(_raw_p, dict) else {}
            _raw_m = r["metrics"]
            if isinstance(_raw_m, str):
                try:
                    _raw_m = json.loads(_raw_m)
                except Exception:
                    _raw_m = {}
            metrics = _raw_m if isinstance(_raw_m, dict) else {}
            _raw_a = r["assessments"]
            if isinstance(_raw_a, str):
                try:
                    _raw_a = json.loads(_raw_a)
                except Exception:
                    _raw_a = {}
            assessments = _raw_a if isinstance(_raw_a, dict) else {}
            dojos = r["selected_dojos"] if isinstance(r["selected_dojos"], list) else []
            strengths = payload.get("strengths", [])
            growth = payload.get("growth_areas", [])
            cee = r["cee_signals"] if isinstance(r["cee_signals"], list) else []
            detail = [f"Client: {name}", f"Date: {dt}", f"Status: {status}"]
            if score:
                detail.append(f"Therapeutic presence: {score}/10")
            if dojos:
                detail.append(f"DOJOs assessed: {', '.join(dojos)}")
            if strengths:
                detail.append(f"Strengths: {', '.join(strengths[:3])}")
            if growth:
                detail.append(f"Growth areas: {', '.join(growth[:3])}")
            dur = metrics.get("total_duration_minutes")
            if dur:
                detail.append(f"Duration: {dur:.0f} min")
            if assessments:
                for dk, dv in assessments.items():
                    if isinstance(dv, dict) and dv.get("summary"):
                        detail.append(f"{dk} assessment: {dv['summary'][:120]}")
            if cee:
                detail.append(f"CEE signals detected: {len(cee)}")
            parts.append(f"--- Session {r['session_id']} ---\n" + "\n".join(detail))
        parts.append("\nUse this lived wisdom to coach the coach, support the client between sessions, and align with the coach's therapeutic approach.")
        return "\n".join(parts)
    except Exception as e:
        logger.warning("get_classroom_lived_wisdom_pg failed: %s", e)
        return ""


async def get_master_coherence_context_pg(db_pool, master_id: str, assistant_id: str, client_id: str) -> str:
    """Build master-only coherence context: client-coach, client-Nate, coach-client-Nate."""
    if not db_pool or not master_id:
        return ""
    try:
        async with db_pool.acquire() as conn:
            analyses = await conn.fetch(
                """SELECT session_id, client_name, therapeutic_presence_score, assessments, payload, analyzed_at
                   FROM classroom_session_analyses
                   WHERE coach_id = $1 AND client_id = $2 AND status = 'completed'
                   ORDER BY analyzed_at DESC LIMIT 5""",
                assistant_id, client_id,
            )
            # nevedal_metrics.user_id may be UUID; client_id may be a hardware_id string.
            # Resolve UUID from users table first if needed.
            nevedal = []
            try:
                uuid_row = await conn.fetchrow(
                    "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", client_id
                )
                uid_val = uuid_row["id"] if uuid_row else None
                if uid_val:
                    nevedal = await conn.fetch(
                        """SELECT c_emo, p_ent, gamma_env, cee_window, recorded_at
                           FROM nevedal_metrics
                           WHERE user_id = $1 ORDER BY recorded_at DESC LIMIT 5""",
                        uid_val,
                    )
            except Exception:
                nevedal = []
            client_name_row = await conn.fetchrow(
                "SELECT COALESCE(profile_data->>'name', name, username) as name FROM users WHERE hardware_id = $1",
                client_id,
            )
            coach_name_row = await conn.fetchrow(
                "SELECT COALESCE(profile_data->>'name', name, username) as name FROM users WHERE hardware_id = $1",
                assistant_id,
            )
        client_name = client_name_row["name"] if client_name_row else client_id
        coach_name = coach_name_row["name"] if coach_name_row else assistant_id
        parts = [f"[MASTER-ONLY COHERENCE — {coach_name} ↔ {client_name}]"]
        if analyses:
            scores = [a["therapeutic_presence_score"] for a in analyses if a["therapeutic_presence_score"]]
            avg_tp = sum(scores) / max(len(scores), 1) if scores else 0
            parts.append(f"Coach–Client coherence (therapeutic presence avg): {avg_tp:.1f}/10 over {len(analyses)} sessions")
        if nevedal:
            cemo_scores = [float(n["c_emo"]) for n in nevedal if n.get("c_emo") is not None]
            pent_scores = [float(n["p_ent"]) for n in nevedal if n.get("p_ent") is not None]
            cee_windows = [n for n in nevedal if n.get("cee_window")]
            if cemo_scores:
                parts.append(f"Client–Nate emotional coherence (C_emo avg): {sum(cemo_scores)/len(cemo_scores):.3f}")
            if pent_scores:
                parts.append(f"Client–Nate entanglement (p_ent avg): {sum(pent_scores)/len(pent_scores):.3f}")
            if cee_windows:
                parts.append(f"CEE windows detected: {len(cee_windows)} in last {len(nevedal)} measurements")
        if analyses and nevedal:
            parts.append("Coach + Client + Nate triad: All three pillars have data — therapeutic presence, emotional coherence, and engagement are tracked.")
        elif analyses:
            parts.append("Coach + Client + Nate triad: Session data present; client–Nate coherence data limited.")
        else:
            parts.append("Limited data — more sessions needed for reliable coherence metrics.")
        return "\n".join(parts)
    except Exception as e:
        logger.warning("get_master_coherence_context_pg failed: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

async def load_metrics_pg(db_pool, hardware_id: str) -> Optional[Dict]:
    """Load nevedal_state from PG client_metrics table."""
    if not db_pool or not hardware_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT crisis_perception, shame_profile, pmb,
                          c_emo, session_count, nevedal_state
                   FROM client_metrics WHERE hardware_id = $1""",
                hardware_id,
            )
            if not row:
                return None
            ns = row.get("nevedal_state")
            if isinstance(ns, str):
                ns = json.loads(ns)
            return {
                "nevedal_state": ns or {},
                "crisis_perception": row.get("crisis_perception"),
                "shame_profile": row.get("shame_profile"),
                "pmb": row.get("pmb"),
                "c_emo": row.get("c_emo"),
                "session_count": row.get("session_count"),
            }
    except Exception as e:
        logger.warning("load_metrics_pg(%s) failed: %s", hardware_id, e)
        return None


# ---------------------------------------------------------------------------
# Billing helpers
# ---------------------------------------------------------------------------

async def get_subscription_pg(db_pool, user_id: str) -> Optional[Dict]:
    """Get subscription info from PG users table."""
    if not db_pool or not user_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT tier, subscription_status, token_balance, profile_data
                   FROM users WHERE hardware_id = $1 AND deleted_at IS NULL
                   LIMIT 1""",
                user_id,
            )
            if not row:
                return None
            pd = row.get("profile_data") or {}
            if isinstance(pd, str):
                try:
                    pd = json.loads(pd)
                except Exception:
                    pd = {}
            plan = row.get("tier") or pd.get("subscription_plan") or "TRIAL"
            return {
                "user_id": user_id,
                "plan": plan,
                "status": row.get("subscription_status") or "TRIAL_ACTIVE",
                "token_balance": row.get("token_balance") or 0,
                "tokens_included": pd.get("tokens_included", 0),
                "start_date": pd.get("subscription_start_date", ""),
                "end_date": pd.get("subscription_end_date", ""),
            }
    except Exception as e:
        logger.warning("get_subscription_pg(%s) failed: %s", user_id, e)
        return None


async def get_transactions_pg(db_pool, user_id: str, limit: int = 20) -> List[Dict]:
    """Get token transactions from PG."""
    if not db_pool or not user_id:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT action, amount, balance_before, balance_after,
                          source, created_at
                   FROM token_transactions
                   WHERE username = $1
                   ORDER BY created_at DESC
                   LIMIT $2""",
                user_id, limit,
            )
            return [
                {
                    "action": r["action"],
                    "amount": r["amount"],
                    "before": r.get("balance_before"),
                    "after": r.get("balance_after"),
                    "source": r.get("source") or "unknown",
                    "timestamp": str(r["created_at"]),
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("get_transactions_pg(%s) failed: %s", user_id, e)
        return []


async def update_user_field_pg(db_pool, hardware_id: str, updates: Dict) -> bool:
    """Update specific fields on the users table for a given hardware_id."""
    if not db_pool or not hardware_id or not updates:
        return False
    try:
        profile_updates = {}
        column_updates = {}
        for k, v in updates.items():
            if k in ("tier", "subscription_status", "token_balance", "name", "email"):
                column_updates[k] = v
            else:
                profile_updates[k] = v

        async with db_pool.acquire() as conn:
            if column_updates:
                sets = []
                params = []
                idx = 1
                for col, val in column_updates.items():
                    sets.append(f"{col} = ${idx}")
                    params.append(val)
                    idx += 1
                params.append(hardware_id)
                await conn.execute(
                    f"UPDATE users SET {', '.join(sets)}, updated_at = NOW() WHERE hardware_id = ${idx}",
                    *params,
                )
            if profile_updates:
                for key, val in profile_updates.items():
                    await conn.execute(
                        """UPDATE users SET profile_data = jsonb_set(
                               COALESCE(profile_data, '{}'::jsonb), $1::text[], $2::jsonb
                           ), updated_at = NOW()
                           WHERE hardware_id = $3""",
                        [key],
                        json.dumps(val),
                        hardware_id,
                    )
        return True
    except Exception as e:
        logger.warning("update_user_field_pg(%s) failed: %s", hardware_id, e)
        return False
