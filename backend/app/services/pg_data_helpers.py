"""
PG Data Helpers — shared async functions for PG-first reads across all routers.

Every router that previously read from JSON files should import from here.
Pattern: PG first, JSON fallback. Dual-write on mutations.
"""

import json
import logging
from datetime import datetime, timezone
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
            profile = dict(row.get("profile_data") or {}) if row.get("profile_data") else {}
            if isinstance(profile, str):
                try:
                    profile = json.loads(profile)
                except Exception:
                    profile = {}
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
            profile = dict(row.get("profile_data") or {}) if row.get("profile_data") else {}
            if isinstance(profile, str):
                try:
                    profile = json.loads(profile)
                except Exception:
                    profile = {}
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
                           created_at, updated_at
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
                    "created_at": str(r["created_at"]) if r.get("created_at") else "",
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
            "nate_summary", "recording_url", "created_at",
        }
        extra = {k: v for k, v in session.items() if k not in known_keys and k != "updated_at"}

        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO coaching_sessions
                    (session_id, client_id, coach_id, family_id, client_name,
                     session_type, status, scheduled_start, scheduled_end,
                     actual_start, actual_end, duration_minutes, zoom_link,
                     zoom_meeting_id, zoom_host_url, notes, coach_notes,
                     topics_covered, homework_assigned, mood_at_start,
                     mood_at_end, nate_summary, recording_url, session_data, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25)
                   ON CONFLICT (session_id) DO UPDATE SET
                     client_id = EXCLUDED.client_id,
                     coach_id = EXCLUDED.coach_id,
                     family_id = EXCLUDED.family_id,
                     client_name = EXCLUDED.client_name,
                     session_type = EXCLUDED.session_type,
                     status = EXCLUDED.status,
                     scheduled_start = EXCLUDED.scheduled_start,
                     scheduled_end = EXCLUDED.scheduled_end,
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
                     session_data = EXCLUDED.session_data""",
                session.get("session_id"),
                session.get("client_id", ""),
                session.get("coach_id", ""),
                session.get("family_id", ""),
                session.get("client_name", ""),
                session.get("session_type", "COACH"),
                session.get("status", "scheduled"),
                _parse_ts(session.get("scheduled_start")),
                _parse_ts(session.get("scheduled_end")),
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
                """SELECT action, amount, before_balance, after_balance,
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
                    "before": r.get("before_balance"),
                    "after": r.get("after_balance"),
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
