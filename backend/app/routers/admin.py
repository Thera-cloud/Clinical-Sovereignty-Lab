"""
Analytics & Admin API Routes
Platform-wide analytics, crisis monitoring, and admin functions
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import os
import json
import logging
import re
import secrets
import hashlib
import time
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("nate.admin")

from app.services.blob_storage import upload_bytes
from app.services.api_server import require_admin
from app.services.pg_data_helpers import (
    load_registry_pg, find_user_pg, find_user_by_username_pg,
    load_sessions_pg, load_metrics_pg, get_subscription_pg,
    get_transactions_pg, update_user_field_pg,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

from app.config import settings as _settings
DATA_DIR = Path(_settings.DATA_DIR)
VAULT_ROOT = DATA_DIR / "Vaults"

# Models
class AssignCoachRequest(BaseModel):
    client_id: str
    coach_id: str

class ApproveCoachRequest(BaseModel):
    coach_id: str
    approved: bool
    notes: str = ""

class ApproveCorpAdminRequest(BaseModel):
    admin_id: str
    approved: bool
    notes: str = ""

class MultiCoachAssignRequest(BaseModel):
    coach_ids: list
    entity_type: str
    entity_id: str

class UnassignCoachRequest(BaseModel):
    coach_id: str
    entity_type: str
    entity_id: str

class CoachHierarchyRequest(BaseModel):
    master_coach_id: str
    assistant_coach_ids: list

class RemoveHierarchyRequest(BaseModel):
    master_coach_id: str
    assistant_coach_id: str

class ResolveCrisisRequest(BaseModel):
    crisis_id: int
    resolution_notes: str
    resolved_by: str

class ResetPasswordRequest(BaseModel):
    user_id: str
    new_password: str

class ResetBiometricsRequest(BaseModel):
    user_id: str

class BanUserRequest(BaseModel):
    user_id: str
    reason: str = ""

class WipeMemoryRequest(BaseModel):
    user_id: str

# Helpers
def load_json(filepath: Path, default=None):
    if default is None: default = {}
    if not filepath.exists(): return default
    try:
        with open(filepath, 'r') as f: return json.load(f)
    except Exception as e:
        logger.warning("load_json(%s) failed: %s", filepath.name, e)
        return default

def save_json(filepath: Path, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f: json.dump(data, f, indent=2, default=str)


def _load_json_any(path: Path, default: Any):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("_load_json_any(%s) failed: %s", path.name, e)
        return default


def _find_sanctuary_file() -> Path:
    """
    Best-effort: sanctuary data is written by the websocket/bridge service.
    In most deployments it sits in DATA_DIR/family_sanctuaries.json.
    """
    candidates = [
        DATA_DIR / "family_sanctuaries.json",
        # fallback for local repo runs
        (Path(__file__).resolve().parents[1] / "websocket" / "data" / "family_sanctuaries.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _get_sanctuary_record(sanctuary_id: str) -> Dict[str, Any]:
    p = _find_sanctuary_file()
    data = _load_json_any(p, {"active_sanctuaries": {}, "completed_sanctuaries": {}}) or {}
    active = (data.get("active_sanctuaries") or {}) if isinstance(data, dict) else {}
    comp = (data.get("completed_sanctuaries") or {}) if isinstance(data, dict) else {}
    s = (active.get(sanctuary_id) or comp.get(sanctuary_id) or {}) if isinstance(active, dict) and isinstance(comp, dict) else {}
    if not isinstance(s, dict) or not s:
        raise HTTPException(404, "Sanctuary not found")
    return s


def _load_events(limit: int = 5000) -> list:
    analytics = _load_json_any(DATA_DIR / "analytics.json", {}) or {}
    events = (analytics.get("events") or []) if isinstance(analytics, dict) else []
    if not isinstance(events, list):
        events = []
    if limit > 0:
        return events[-limit:]
    return events


def _load_transactions(limit: int = 10000) -> list:
    tx = _load_json_any(DATA_DIR / "transactions.json", []) or []
    if not isinstance(tx, list):
        tx = []
    if limit > 0:
        return tx[-limit:]
    return tx


async def _load_transactions_pg(pool, limit: int = 10000) -> list:
    """Load transactions from PG first, JSON fallback."""
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, username, amount, currency, status, description,
                              metadata, created_at
                       FROM payment_history
                       ORDER BY created_at DESC
                       LIMIT $1""",
                    limit,
                )
                if rows:
                    result = []
                    for r in rows:
                        md = r.get("metadata") or {}
                        if isinstance(md, str):
                            try:
                                md = json.loads(md)
                            except Exception:
                                md = {}
                        result.append({
                            "id": str(r["id"]),
                            "user_id": r.get("username", ""),
                            "amount": float(r["amount"]) / 100 if r.get("amount") else 0,
                            "currency": r.get("currency", "usd"),
                            "status": r.get("status", ""),
                            "description": r.get("description", ""),
                            "metadata": md,
                            "timestamp": r["created_at"].isoformat() if r.get("created_at") else "",
                        })
                    return result
        except Exception as e:
            logger.warning("_load_transactions_pg: PG read failed: %s", e)
    return _load_transactions(limit)

# Dashboard Stats
@router.get("/dashboard")
async def get_dashboard_stats(request: Request):
    """Get admin dashboard statistics — reads from PostgreSQL."""
    pool = getattr(request.app.state, "db_pool", None)

    if pool:
        try:
            async with pool.acquire() as conn:
                now = datetime.now(timezone.utc)
                today = now.date()
                week_ago = now - timedelta(days=7)

                role_counts = await conn.fetch(
                    "SELECT role, COUNT(*) as cnt FROM users WHERE deleted_at IS NULL GROUP BY role"
                )
                role_map = {r["role"]: r["cnt"] for r in role_counts}
                clients = role_map.get("CLIENT", 0)
                coaches = role_map.get("COACH", 0)
                admins_count = role_map.get("ADMIN", 0)
                total_users = sum(role_map.values())

                active_users = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE last_login >= $1 AND deleted_at IS NULL", week_ago
                ) or 0

                new_this_week = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE created_at >= $1 AND deleted_at IS NULL", week_ago
                ) or 0

                live_sessions = await conn.fetchval(
                    "SELECT COUNT(*) FROM sessions WHERE status = 'active'"
                ) or 0

                completed_today = await conn.fetchval(
                    "SELECT COUNT(*) FROM sessions WHERE status = 'completed' AND ended_at::date = $1", today
                ) or 0

                total_sessions = await conn.fetchval("SELECT COUNT(*) FROM sessions") or 0

                daily = await conn.fetchrow(
                    "SELECT logins, registrations, messages_sent, tokens_used FROM daily_analytics WHERE date = $1", today
                )

                active_crises = await conn.fetchval(
                    "SELECT COUNT(*) FROM crisis_events WHERE resolved = FALSE"
                ) or 0
                if active_crises == 0:
                    active_crises = await conn.fetchval(
                        "SELECT COUNT(*) FROM crisis_watchlist WHERE resolved = FALSE"
                    ) or 0

                pending_approvals = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE subscription_status = 'PENDING_VERIFICATION' AND deleted_at IS NULL"
                ) or 0

                platform = await conn.fetchrow(
                    "SELECT total_sessions, total_messages, total_tokens_used FROM platform_totals WHERE id = 1"
                )

            return {
                "users": {
                    "total": total_users,
                    "clients": clients,
                    "coaches": coaches,
                    "admins": admins_count,
                    "active_7d": active_users,
                    "new_this_week": new_this_week,
                },
                "sessions": {
                    "live": live_sessions,
                    "completed_today": completed_today,
                    "total": total_sessions,
                },
                "today": {
                    "logins": daily["logins"] if daily else 0,
                    "registrations": daily["registrations"] if daily else 0,
                    "messages": daily["messages_sent"] if daily else 0,
                    "tokens_used": daily["tokens_used"] if daily else 0,
                },
                "alerts": {
                    "active_crises": active_crises,
                    "pending_coach_approvals": pending_approvals,
                },
                "platform": {
                    "total_sessions": platform["total_sessions"] if platform else 0,
                    "total_messages": platform["total_messages"] if platform else 0,
                    "total_tokens_used": platform["total_tokens_used"] if platform else 0,
                },
            }
        except Exception as pg_err:
            logger.warning("get_dashboard_stats: PG read failed, falling back to JSON: %s", pg_err)

    # JSON fallback (legacy)
    registry = load_json(DATA_DIR / "user_registry.json")
    sessions = load_json(DATA_DIR / "sessions.json", [])
    analytics = load_json(DATA_DIR / "analytics.json")
    now = datetime.now()
    today = str(now.date())
    week_ago = now - timedelta(days=7)
    clients = coaches = admins_count = active_users = new_this_week = 0
    for k, v in registry.items():
        p = v.get("profile", {})
        role = p.get("role", "CLIENT")
        if role == "CLIENT": clients += 1
        elif role == "COACH": coaches += 1
        elif role == "ADMIN": admins_count += 1
        last_login = p.get("last_login", "")
        if last_login:
            try:
                if datetime.fromisoformat(last_login.split(".")[0]) >= week_ago:
                    active_users += 1
            except Exception: pass
        joined = p.get("joined_date", "")
        if joined:
            try:
                if datetime.fromisoformat(joined) >= week_ago.date():
                    new_this_week += 1
            except Exception: pass
    live_sessions = len([s for s in sessions if s.get("status") == "active"])
    completed_today = len([s for s in sessions if s.get("status") == "completed" and s.get("actual_end", "").startswith(today)])
    today_stats = analytics.get("daily_stats", {}).get(today, {})
    crisis_log = load_json(DATA_DIR / "crisis_log.json", [])
    active_crises = len([c for c in crisis_log if not c.get("resolved", False)])
    return {
        "users": {"total": len(registry), "clients": clients, "coaches": coaches, "admins": admins_count, "active_7d": active_users, "new_this_week": new_this_week},
        "sessions": {"live": live_sessions, "completed_today": completed_today, "total": len(sessions)},
        "today": {"logins": today_stats.get("logins", 0), "registrations": today_stats.get("registrations", 0), "messages": today_stats.get("messages_sent", 0), "tokens_used": today_stats.get("tokens_used", 0)},
        "alerts": {"active_crises": active_crises, "pending_coach_approvals": len([v for v in registry.values() if v.get("profile", {}).get("subscription_status") == "PENDING_VERIFICATION"])},
        "platform": analytics.get("platform_totals", {}),
    }

# User Management
@router.get("/users")
async def get_all_users(request: Request, role: str = None, status: str = None, limit: int = 100):
    """Get all users with optional filters — PostgreSQL primary, JSON fallback."""
    pool = getattr(request.app.state, "db_pool", None)

    if pool:
        try:
            async with pool.acquire() as conn:
                conditions = ["deleted_at IS NULL"]
                params = []
                idx = 1
                if role:
                    conditions.append(f"role = ${idx}")
                    params.append(role)
                    idx += 1
                if status:
                    conditions.append(f"subscription_status = ${idx}")
                    params.append(status)
                    idx += 1

                where = " AND ".join(conditions)
                rows = await conn.fetch(f"""
                    SELECT id, hardware_id, name, email, role, tier,
                           subscription_status,
                           created_at, last_login, token_balance, profile_data
                    FROM users WHERE {where}
                    ORDER BY created_at DESC NULLS LAST
                    LIMIT {limit}
                """, *params)

                total_count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM users WHERE {where}", *params
                )

            users_list = []
            for r in rows:
                pd = r["profile_data"] or {}
                if isinstance(pd, str):
                    pd = json.loads(pd)
                users_list.append({
                    "id": str(r["id"]),
                    "user_id": str(r["id"]),
                    "hardware_id": r["hardware_id"] or pd.get("hardware_id", ""),
                    "name": r["name"] or pd.get("name", ""),
                    "username": pd.get("username", ""),
                    "email": r["email"] or pd.get("email", ""),
                    "role": r["role"] or pd.get("role", "CLIENT"),
                    "tier": r["tier"] or pd.get("tier", ""),
                    "subscription_status": r["subscription_status"] or pd.get("subscription_status", ""),
                    "subscription_plan": pd.get("subscription_plan", r.get("tier", "")),
                    "joined_date": r["created_at"].isoformat() if r["created_at"] else pd.get("joined_date", ""),
                    "last_login": r["last_login"].isoformat() if r["last_login"] else pd.get("last_login", ""),
                    "total_sessions": pd.get("total_sessions_count", 0),
                    "token_balance": r["token_balance"] or pd.get("token_balance", 0),
                    "assigned_coach": pd.get("assigned_coach_id", ""),
                    "family_id": str(r.get("family_id", "")) if r.get("family_id") else pd.get("family_id", ""),
                    "client_count": pd.get("client_count", 0),
                    "retention_rate": pd.get("retention_rate", 0),
                    "avg_c_emo": pd.get("avg_c_emo", 0),
                    "cee_rate": pd.get("cee_rate", 0),
                    "ai_collab_score": pd.get("ai_collab_score", 0),
                    "ytd_earnings": pd.get("ytd_earnings", 0),
                    "specialty": pd.get("specialty", ""),
                })

            return {"users": users_list, "total": total_count or len(users_list)}
        except Exception as e:
            logger.warning("get_all_users: PG read failed, falling back to JSON: %s", e)

    # JSON fallback (legacy)
    registry = load_json(DATA_DIR / "user_registry.json")
    users = []
    for k, v in registry.items():
        p = v.get("profile", {})
        if role and p.get("role") != role:
            continue
        if status and p.get("subscription_status") != status:
            continue
        users.append({
            "id": k, "hardware_id": p.get("hardware_id"), "name": p.get("name"),
            "email": p.get("email"), "role": p.get("role"), "tier": p.get("tier"),
            "subscription_status": p.get("subscription_status"),
            "subscription_plan": p.get("subscription_plan"),
            "joined_date": p.get("joined_date"), "last_login": p.get("last_login"),
            "total_sessions": p.get("total_sessions_count", 0),
            "token_balance": p.get("token_balance", 0),
            "assigned_coach": p.get("assigned_coach_id", ""),
        })
    users.sort(key=lambda x: x.get("joined_date", ""), reverse=True)
    return {"users": users[:limit], "total": len(users)}

@router.get("/user/{user_id}")
async def get_user_details(user_id: str, request: Request):
    """Get detailed user information"""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: find user
    p = None
    v = {}
    if pool:
        try:
            user_profile = await find_user_pg(pool, user_id)
            if user_profile:
                p = user_profile
                v = {"profile": p}
        except Exception as e:
            logger.warning("get_user_details: PG user lookup failed: %s", e)

    if p is None:
        registry = load_json(DATA_DIR / "user_registry.json")
        for k, val in registry.items():
            prof = val.get("profile", {})
            if prof.get("hardware_id") == user_id or k == user_id:
                p = prof
                v = val
                break

    if p is None:
        raise HTTPException(404, "User not found")

    hw_id = p.get("hardware_id", user_id)

    # PG-first: load metrics
    metrics = {}
    if pool:
        try:
            pg_metrics = await load_metrics_pg(pool, hw_id)
            if pg_metrics:
                metrics = pg_metrics
        except Exception as e:
            logger.warning("get_user_details: PG metrics load failed: %s", e)
    if not metrics:
        metrics_file = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
        metrics = load_json(metrics_file, {})

    # Load memory summary (file-only — no PG table for conversation memory)
    memory_file = VAULT_ROOT / "Clients" / hw_id / "memory.json"
    memories = load_json(memory_file, [])

    # PG-first: load sessions
    user_sessions = []
    if pool:
        try:
            pg_sessions = await load_sessions_pg(pool, client_id=hw_id)
            if pg_sessions:
                user_sessions = pg_sessions
        except Exception as e:
            logger.warning("get_user_details: PG sessions load failed: %s", e)
    if not user_sessions:
        sessions = load_json(DATA_DIR / "sessions.json", [])
        user_sessions = [s for s in sessions if s.get("client_id") == hw_id]

    ns = metrics.get("nevedal_state", {})

    _admin_cee = ns.get("cee_experiences", [])
    _admin_drift = ns.get("drift_periods", [])
    _admin_rt = ns.get("reply_therapy", {})
    _admin_pmb = ns.get("pmb", {}) if isinstance(ns.get("pmb"), dict) else {}
    _admin_legacy = _admin_pmb.get("legacy_patterns", []) if isinstance(_admin_pmb.get("legacy_patterns"), list) else []

    _admin_rt_summary = {}
    if isinstance(_admin_rt, dict):
        _admin_rt_summary = {
            "active_theme": _admin_rt.get("active_reply_theme"),
            "completed_count": len(_admin_rt.get("completed_replies", [])),
            "completed_replies": _admin_rt.get("completed_replies", [])[-5:],
            "themes": {
                t: {
                    "mismatch": td.get("mismatch_count", 0),
                    "reconsolidation": td.get("reconsolidation_count", 0),
                    "evocative": td.get("evocative_recall_count", 0),
                    "threshold_met": td.get("threshold_met", False),
                    "reply_completed": td.get("reply_completed", False),
                }
                for t, td in _admin_rt.get("themes", {}).items()
                if isinstance(td, dict)
            },
        }

    return {
        "profile": p,
        "credentials": {"username": v.get("credentials", {}).get("username")},
        "metrics": ns,
        "metrics_history": metrics.get("history", [])[-20:],
        "conversation_count": len(memories),
        "recent_topics": _extract_topics(memories[-20:]),
        "sessions": {
            "total": len(user_sessions),
            "completed": len([s for s in user_sessions if s.get("status") == "completed"]),
            "recent": user_sessions[-5:]
        },
        "cee_experiences": [
            {
                "timestamp": ce.get("timestamp", ""),
                "c_emo_before": ce.get("c_emo_before", 0),
                "c_emo_after": ce.get("c_emo_after", 0),
                "delta": ce.get("delta", 0),
                "mood_before": ce.get("mood_before", ""),
                "mood_after": ce.get("mood_after", ""),
            }
            for ce in (_admin_cee[-20:] if isinstance(_admin_cee, list) else [])
            if isinstance(ce, dict)
        ],
        "drift_periods": [
            {
                "left_at": dp.get("left_at", ""),
                "returned_at": dp.get("returned_at", ""),
                "gap_days": dp.get("gap_days", 0),
                "explored": dp.get("explored", False),
            }
            for dp in (_admin_drift if isinstance(_admin_drift, list) else [])
            if isinstance(dp, dict)
        ],
        "reply_therapy": _admin_rt_summary,
        "legacy_healing": [
            {
                "pattern": lp.get("pattern", ""),
                "source": lp.get("source", ""),
                "corrective_count": lp.get("corrective_experience_count", 0),
                "last_corrective_at": lp.get("last_corrective_at"),
                "reflected_in_client": lp.get("reflected_in_client", False),
            }
            for lp in _admin_legacy
            if isinstance(lp, dict) and lp.get("corrective_experience_count", 0) > 0
        ],
    }

    raise HTTPException(404, "User not found")


# =============================================================================
# ADMIN IDENTITY RESOLUTION — Password, Biometrics, Ban, Memory Wipe
# =============================================================================

def _hash_password(password: str) -> str:
    """Hash password with PBKDF2 (matches bridge_server and api_server)."""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}:{hashed.hex()}"


def _audit_log_append(action: str, **kwargs):
    """Append an entry to the audit log (JSON only — use _audit_log_append_pg for PG+JSON)."""
    audit_path = DATA_DIR / "audit_log.json"
    audit = load_json(audit_path, [])
    if not isinstance(audit, list):
        audit = []
    audit.append({"action": action, "timestamp": str(datetime.now()), **kwargs})
    save_json(audit_path, audit)


async def _audit_log_append_pg(pool, action: str, **kwargs):
    """Write audit entry to PG first, then JSON backup."""
    if pool:
        try:
            description = kwargs.pop("description", "") or f"{action}: {json.dumps(kwargs, default=str)[:500]}"
            target_id = kwargs.pop("user_id", None) or kwargs.pop("target_id", None) or ""
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO audit_log (action_type, target_type, target_id, description)
                       VALUES ($1, $2, $3, $4)""",
                    action[:30], "user", str(target_id)[:255], description[:2000],
                )
        except Exception as e:
            logger.warning("_audit_log_append_pg: PG write failed: %s", e)
    _audit_log_append(action, **kwargs)


@router.post("/reset-password")
async def admin_reset_password(req: ResetPasswordRequest, request: Request):
    """Reset a user's password. Audit-logged."""
    if len(req.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    pool = getattr(request.app.state, "db_pool", None)
    new_hash = _hash_password(req.new_password)

    # PG-first: update password directly
    if pool:
        try:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE users SET password_hash = $1, updated_at = NOW() WHERE hardware_id = $2 AND deleted_at IS NULL",
                    new_hash, req.user_id,
                )
                if result and result.split()[-1] != "0":
                    user_name_row = await conn.fetchrow(
                        "SELECT name FROM users WHERE hardware_id = $1", req.user_id
                    )
                    user_name = user_name_row["name"] if user_name_row else ""
                    await _audit_log_append_pg(pool, "ADMIN_RESET_PASSW", user_id=req.user_id,
                                               description=f"Password reset for {user_name or req.user_id}")
                    return {"status": "password_reset", "user_id": req.user_id, "message": "Password updated. User must log in with new credentials."}
        except Exception as e:
            logger.warning("admin_reset_password: PG update failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.user_id or k == req.user_id:
            creds = v.get("credentials", {}) or {}
            creds["password"] = new_hash
            v["credentials"] = creds
            save_json(DATA_DIR / "user_registry.json", registry)
            _audit_log_append("ADMIN_RESET_PASSWORD", user_id=req.user_id, user_name=p.get("name", ""))
            return {"status": "password_reset", "user_id": req.user_id, "message": "Password updated. User must log in with new credentials."}

    raise HTTPException(404, "User not found")


@router.post("/reset-biometrics")
async def admin_reset_biometrics(req: ResetBiometricsRequest, request: Request):
    """Reset a user's voice biometric baselines. Audit-logged."""
    pool = getattr(request.app.state, "db_pool", None)

    found = False
    hw_id = ""
    user_name = ""

    # PG-first: find user
    if pool:
        try:
            user_profile = await find_user_pg(pool, req.user_id)
            if user_profile:
                hw_id = user_profile.get("hardware_id", req.user_id)
                user_name = user_profile.get("name", "")
                found = True
        except Exception as e:
            logger.warning("admin_reset_biometrics: PG user lookup failed: %s", e)

    if not found:
        registry = load_json(DATA_DIR / "user_registry.json")
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("hardware_id") == req.user_id or k == req.user_id:
                hw_id = p.get("hardware_id", req.user_id)
                user_name = p.get("name", "")
                found = True
                break

    if not found:
        raise HTTPException(404, "User not found")

    # Clear biometric baselines from user metrics
    metrics_file = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
    if metrics_file.exists():
        metrics = load_json(metrics_file, {})
        ns = metrics.get("nevedal_state", {})
        # Remove voice biometric baseline fields
        for field in ["voice_baseline", "voice_signature", "pitch_baseline", "energy_baseline",
                       "speech_rate_baseline", "pause_ratio_baseline", "baseline_established",
                       "biometric_enrolled"]:
            ns.pop(field, None)
        metrics["nevedal_state"] = ns
        save_json(metrics_file, metrics)

    # Also clear from user profile (PG-first)
    if pool:
        try:
            for field in ["voice_enrolled", "biometric_enrolled", "voice_baseline_date"]:
                await update_user_field_pg(pool, hw_id, {field: None})
        except Exception as e:
            logger.warning("admin_reset_biometrics: PG profile clear failed: %s", e)
    else:
        registry = load_json(DATA_DIR / "user_registry.json")
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("hardware_id") == hw_id:
                for field in ["voice_enrolled", "biometric_enrolled", "voice_baseline_date"]:
                    p.pop(field, None)
                save_json(DATA_DIR / "user_registry.json", registry)
                break

    _audit_log_append("ADMIN_RESET_BIOMETRICS", user_id=req.user_id, user_name=user_name)
    return {"status": "biometrics_reset", "user_id": req.user_id, "message": "Biometrics cleared. User must re-enroll."}


@router.post("/ban-user")
async def admin_ban_user(req: BanUserRequest, request: Request):
    """Ban a user account (sets status to BANNED). Audit-logged."""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: ban user directly
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT name, subscription_status FROM users WHERE hardware_id = $1 AND deleted_at IS NULL",
                    req.user_id,
                )
                if row:
                    old_status = row["subscription_status"] or ""
                    user_name = row["name"] or ""
                    ban_data = json.dumps({
                        "ban_reason": req.reason,
                        "banned_at": str(datetime.now()),
                    })
                    await conn.execute(
                        """UPDATE users SET subscription_status = 'ACTIVE',
                           profile_data = profile_data || $1::jsonb, updated_at = NOW()
                           WHERE hardware_id = $2""",
                        ban_data, req.user_id,
                    )
                    await _audit_log_append_pg(pool, "ADMIN_BAN_USER", user_id=req.user_id,
                                               description=f"Banned {user_name}. Reason: {req.reason}. Old status: {old_status}")
                    return {"status": "banned", "user_id": req.user_id, "message": f"User banned. Reason: {req.reason or 'No reason provided.'}"}
        except Exception as e:
            logger.warning("admin_ban_user: PG update failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.user_id or k == req.user_id:
            old_status = p.get("subscription_status", "")
            p["subscription_status"] = "BANNED"
            p["ban_reason"] = req.reason
            p["banned_at"] = str(datetime.now())
            save_json(DATA_DIR / "user_registry.json", registry)
            _audit_log_append(
                "ADMIN_BAN_USER",
                user_id=req.user_id,
                user_name=p.get("name", ""),
                reason=req.reason,
                old_status=old_status,
            )
            return {"status": "banned", "user_id": req.user_id, "message": f"User banned. Reason: {req.reason or 'No reason provided.'}"}

    raise HTTPException(404, "User not found")


@router.post("/wipe-memory")
async def admin_wipe_memory(req: WipeMemoryRequest, request: Request):
    """Wipe all conversation memory and metrics history for a user. Audit-logged. IRREVERSIBLE."""
    pool = getattr(request.app.state, "db_pool", None)

    found = False
    hw_id = ""
    user_name = ""

    # PG-first: find user
    if pool:
        try:
            user_profile = await find_user_pg(pool, req.user_id)
            if user_profile:
                hw_id = user_profile.get("hardware_id", req.user_id)
                user_name = user_profile.get("name", "")
                found = True
        except Exception as e:
            logger.warning("admin_wipe_memory: PG user lookup failed: %s", e)

    if not found:
        registry = load_json(DATA_DIR / "user_registry.json")
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("hardware_id") == req.user_id or k == req.user_id:
                hw_id = p.get("hardware_id", req.user_id)
                user_name = p.get("name", "")
                found = True
                break

    if not found:
        raise HTTPException(404, "User not found")

    wiped = []

    # Wipe conversation memory
    memory_file = VAULT_ROOT / "Clients" / hw_id / "memory.json"
    if memory_file.exists():
        save_json(memory_file, [])
        wiped.append("conversation_memory")

    # Wipe metrics history (keep current nevedal_state but clear history)
    metrics_file = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
    if metrics_file.exists():
        metrics = load_json(metrics_file, {})
        metrics["history"] = []
        save_json(metrics_file, metrics)
        wiped.append("metrics_history")

    # Wipe session-specific memory files in vault
    vault_dir = VAULT_ROOT / "Clients" / hw_id
    if vault_dir.exists():
        for f in vault_dir.glob("session_*.json"):
            save_json(f, {})
            wiped.append(f"session:{f.stem}")

    _audit_log_append("ADMIN_WIPE_MEMORY", user_id=req.user_id, user_name=user_name, wiped=wiped)
    return {
        "status": "memory_wiped",
        "user_id": req.user_id,
        "wiped": wiped,
        "message": f"All memory wiped for {user_name or req.user_id}. {len(wiped)} data stores cleared.",
    }


class DeleteUserRequest(BaseModel):
    user_id: str
    reason: str = "Administrative action"


@router.post("/delete-user")
async def admin_delete_user(req: DeleteUserRequest, request: Request):
    """
    Permanently delete a user account (soft-delete + anonymization).
    Removes vault data, DB records, and sends notification email.
    Audit-logged. IRREVERSIBLE.
    """
    pool = getattr(request.app.state, "db_pool", None)

    target_key = None
    target_profile = None
    hw_id = req.user_id
    user_name = "Unknown"
    user_email = ""

    # PG-first: find user
    if pool:
        try:
            user_profile = await find_user_pg(pool, req.user_id)
            if user_profile:
                target_profile = user_profile
                target_key = f"{user_profile.get('role', 'CLIENT').lower()}_{user_profile.get('username', '')}"
                hw_id = user_profile.get("hardware_id", req.user_id)
                user_name = user_profile.get("name", "Unknown")
                user_email = user_profile.get("email", "")
        except Exception as e:
            logger.warning("admin_delete_user: PG user lookup failed: %s", e)

    if not target_profile:
        registry = load_json(DATA_DIR / "user_registry.json")
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("hardware_id") == req.user_id or k == req.user_id:
                target_key = k
                target_profile = p
                hw_id = p.get("hardware_id", req.user_id)
                user_name = p.get("name", "Unknown")
                user_email = p.get("email", "")
                break

    if not target_key or not target_profile:
        raise HTTPException(404, "User not found")

    if target_profile.get("role") == "ADMIN":
        raise HTTPException(403, "Cannot delete admin accounts via this endpoint")

    # DB soft-delete (PG-first)
    cleaned = []
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET deleted_at = NOW(), email = '', name = 'Deleted User', password_hash = '' WHERE hardware_id = $1",
                    hw_id,
                )
                cleaned.append("db_users")
        except Exception as e:
            logger.warning("admin_delete_user: PG soft-delete failed: %s", e)

    # JSON backup anonymization
    registry = load_json(DATA_DIR / "user_registry.json")
    if target_key and target_key in registry:
        rp = registry[target_key].get("profile", {})
        rp["name"] = "Deleted User"
        rp["email"] = ""
        rp["phone"] = ""
        rp["account_status"] = "DELETED"
        rp["deleted_at"] = datetime.utcnow().isoformat()
        rp["delete_reason"] = req.reason
        registry[target_key]["profile"] = rp
        if "password_hash" in registry[target_key]:
            registry[target_key]["password_hash"] = ""
        if "password_salt" in registry[target_key]:
            registry[target_key]["password_salt"] = ""
        save_json(DATA_DIR / "user_registry.json", registry)

    # Vault cleanup
    role = target_profile.get("role", "CLIENT")
    vault_subdir = "Coaches" if role == "COACH" else "Clients"
    vault_dir = VAULT_ROOT / vault_subdir / hw_id
    if vault_dir.exists():
        import shutil
        shutil.rmtree(vault_dir, ignore_errors=True)
        cleaned.append("vault_files")

    _audit_log_append(
        "ADMIN_DELETE_USER",
        user_id=req.user_id,
        user_name=user_name,
        reason=req.reason,
        cleaned=cleaned,
    )

    return {
        "status": "deleted",
        "user_id": req.user_id,
        "name": user_name,
        "cleaned": cleaned,
        "message": f"Account '{user_name}' permanently deleted. {len(cleaned)} data stores cleaned.",
    }


@router.get("/analytics/events")
async def get_event_stream(limit: int = 1000):
    """
    Return the last N analytics events (append-only stream).
    This is the source of truth for flow-tree timelines.
    """
    limit = max(0, min(int(limit or 1000), 20000))
    return {"events": _load_events(limit=limit)}


@router.get("/sanctuary/{sanctuary_id}/timeline")
async def get_sanctuary_timeline(sanctuary_id: str, limit_events: int = 2000, request: Request = None):
    """
    Return a per-sanctuary timeline: sanctuary record + ledger + matching events + matching transactions.
    """
    s = _get_sanctuary_record(sanctuary_id)
    family_id = (s.get("family_id") or "").strip()

    events = []
    for e in _load_events(limit=max(0, min(int(limit_events or 2000), 20000))):
        if not isinstance(e, dict):
            continue
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        if (data.get("sanctuary_id") == sanctuary_id) or (e.get("event_type") == "sanctuary_created" and data.get("sanctuary_id") == sanctuary_id):
            events.append(e)

    # PG-first for transactions
    pool = getattr(request.app.state, "db_pool", None) if request else None
    all_txns = await _load_transactions_pg(pool) if pool else _load_transactions()
    txns = []
    for t in all_txns:
        if not isinstance(t, dict):
            continue
        md = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        if md.get("sanctuary_id") == sanctuary_id:
            txns.append(t)

    ledger = ((s.get("billing") or {}).get("charges") or []) if isinstance(s.get("billing"), dict) else []
    if not isinstance(ledger, list):
        ledger = []

    return {
        "sanctuary_id": sanctuary_id,
        "family_id": family_id,
        "status": s.get("status"),
        "sanctuary": s,
        "billing_ledger": ledger[-200:],
        "events": events[-2000:],
        "transactions": txns[-2000:],
    }


@router.post("/sanctuary/{sanctuary_id}/export")
async def export_sanctuary_archive(sanctuary_id: str, upload: bool = False):
    """
    Create a compact archive JSON for a sanctuary (state + timeline slices).

    - Always writes to local `DATA_DIR/archives/...`.
    - If `upload=true` and Azure is configured, also uploads to blob storage.
    """
    payload = await get_sanctuary_timeline(sanctuary_id, limit_events=20000)
    blob_rel = f"sanctuaries/{sanctuary_id}/archive.json"
    content = json.dumps(payload, indent=2, default=str).encode("utf-8")

    # Always save locally (upload_bytes falls back to local anyway)
    if upload:
        kind, loc = upload_bytes(rel_path=blob_rel, content=content, content_type="application/json")
        return {"ok": True, "storage": kind, "location": loc, "bytes": len(content)}

    # local-only
    kind, loc = upload_bytes(rel_path=blob_rel, content=content, content_type="application/json")
    return {"ok": True, "storage": kind, "location": loc, "bytes": len(content)}


@router.post("/analytics/trim")
async def trim_analytics_events(keep: int = 5000):
    """
    Retention control: trims analytics.json `events[]` to last N entries.
    """
    keep = max(0, min(int(keep or 5000), 200000))
    path = DATA_DIR / "analytics.json"
    analytics = _load_json_any(path, {}) or {}
    if not isinstance(analytics, dict):
        analytics = {}
    events = analytics.get("events")
    if not isinstance(events, list):
        events = []
    if keep > 0:
        analytics["events"] = events[-keep:]
    else:
        analytics["events"] = []
    save_json(path, analytics)
    return {"ok": True, "kept": len(analytics["events"])}

def _extract_topics(memories):
    """Simple topic extraction from memories"""
    topics = {}
    keywords = {
        "anxiety": ["anxious", "anxiety", "worried", "panic"],
        "depression": ["depressed", "sad", "hopeless", "empty"],
        "relationships": ["relationship", "partner", "family", "friend"],
        "work": ["work", "job", "boss", "career"],
        "sleep": ["sleep", "insomnia", "tired", "rest"]
    }
    
    for mem in memories:
        text = (mem.get("user", "") + " " + mem.get("ai", "")).lower()
        for topic, words in keywords.items():
            if any(w in text for w in words):
                topics[topic] = topics.get(topic, 0) + 1
    
    return sorted(topics.items(), key=lambda x: x[1], reverse=True)

# Coach Management
@router.get("/coaches")
async def get_coaches(request: Request, status: str = None):
    """Get all coaches — PostgreSQL primary, JSON fallback."""
    pool = getattr(request.app.state, "db_pool", None)

    if pool:
        try:
            async with pool.acquire() as conn:
                conditions = ["role = 'COACH'", "deleted_at IS NULL"]
                params: list = []
                idx = 1
                if status:
                    conditions.append(f"subscription_status = ${idx}")
                    params.append(status)
                    idx += 1

                where = " AND ".join(conditions)
                rows = await conn.fetch(
                    f"SELECT id, hardware_id, name, email, subscription_status, "
                    f"profile_data, created_at FROM users WHERE {where} "
                    f"ORDER BY created_at DESC", *params
                )

                coaches = []
                for r in rows:
                    pd = r["profile_data"] or {}
                    hw_id = r["hardware_id"] or str(r["id"])
                    client_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM users WHERE deleted_at IS NULL "
                        "AND profile_data->>'assigned_coach_id' = $1", hw_id
                    )
                    coaches.append({
                        "id": hw_id,
                        "name": r["name"],
                        "email": r["email"],
                        "status": r["subscription_status"],
                        "certification_status": pd.get("certification_status", "PENDING"),
                        "specializations": pd.get("specializations", []),
                        "assigned_clients": client_count,
                        "total_sessions": pd.get("total_sessions_conducted", 0),
                        "rating": pd.get("average_client_rating", 0),
                        "joined_date": r["created_at"].isoformat() if r["created_at"] else None,
                    })
                return {"coaches": coaches}
        except Exception as e:
            logger.warning("get_coaches PG failed, falling back to JSON: %s", e)

    registry = load_json(DATA_DIR / "user_registry.json")
    coaches = []
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("role") != "COACH":
            continue
        if status and p.get("subscription_status") != status:
            continue
        client_count = len([u for u in registry.values()
                          if u.get("profile", {}).get("assigned_coach_id") == p.get("hardware_id")])
        coaches.append({
            "id": p.get("hardware_id"),
            "name": p.get("name"),
            "email": p.get("email"),
            "status": p.get("subscription_status"),
            "certification_status": p.get("certification_status", "PENDING"),
            "specializations": p.get("specializations", []),
            "assigned_clients": client_count,
            "total_sessions": p.get("total_sessions_conducted", 0),
            "rating": p.get("average_client_rating", 0),
            "joined_date": p.get("joined_date")
        })
    return {"coaches": coaches}

@router.post("/coaches/approve")
async def approve_coach(req: ApproveCoachRequest, request: Request):
    """Approve or reject a coach application"""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: update coach status
    if pool:
        try:
            new_status = "ACTIVE" if req.approved else "ACTIVE"
            cert_status = "VERIFIED" if req.approved else "REJECTED"
            sub_status = "ACTIVE" if req.approved else "ACTIVE"
            update_data = json.dumps({
                "certification_status": cert_status,
                "approval_notes": req.notes,
                "approved_at": str(datetime.now()),
            })
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT name, email, profile_data FROM users WHERE hardware_id = $1 AND deleted_at IS NULL",
                    req.coach_id,
                )
                if row:
                    await conn.execute(
                        """UPDATE users SET subscription_status = $1,
                           profile_data = profile_data || $2::jsonb, updated_at = NOW()
                           WHERE hardware_id = $3""",
                        sub_status, update_data, req.coach_id,
                    )
                    p = row["profile_data"] or {}
                    if isinstance(p, str):
                        p = json.loads(p)

                    if req.approved:
                        _c_email = row["email"] or p.get("email")
                        _c_phone = p.get("phone")
                        _c_name = row["name"] or p.get("name", "Coach")
                        try:
                            from app.websocket.bridge_server import notification_system as _ns
                            if _c_email and _ns:
                                import asyncio
                                asyncio.create_task(_ns._send_email(
                                    to_email=_c_email,
                                    subject="Your Coach Account Has Been Approved!",
                                    content=(
                                        f"Congratulations {_c_name}!\n\n"
                                        f"Your coach account on Sovereign Sanctuary has been verified and approved. "
                                        f"You can now sign in to the Coach Portal.\n\n"
                                        f"Sign in at: https://coach.sovereignsanctuary.net\n\n"
                                        f"Welcome to the team."
                                    ),
                                    notification_type="coach_approval"
                                ))
                            if _c_phone and _ns:
                                import asyncio
                                asyncio.create_task(_ns.send_sms(
                                    to_phone=_c_phone,
                                    body="Sovereign Sanctuary: Your coach account has been approved! Sign in at https://coach.sovereignsanctuary.net"
                                ))
                        except Exception as _n_err:
                            logger.warning("Coach approval notification error (non-fatal): %s", _n_err)

                    return {"message": "Coach status updated", "status": sub_status}
        except Exception as e:
            logger.warning("approve_coach: PG update failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.coach_id:
            if req.approved:
                p["subscription_status"] = "ACTIVE"
                p["certification_status"] = "VERIFIED"
            else:
                p["subscription_status"] = "REJECTED"
                p["certification_status"] = "REJECTED"
            
            p["approval_notes"] = req.notes
            p["approved_at"] = str(datetime.now())
            
            save_json(DATA_DIR / "user_registry.json", registry)

            if req.approved:
                _c_email = p.get("email") or v.get("credentials", {}).get("email")
                _c_phone = p.get("phone")
                _c_name = p.get("name", "Coach")
                try:
                    from app.websocket.bridge_server import notification_system as _ns
                    if _c_email and _ns:
                        import asyncio
                        asyncio.create_task(_ns._send_email(
                            to_email=_c_email,
                            subject="Your Coach Account Has Been Approved!",
                            content=(
                                f"Congratulations {_c_name}!\n\n"
                                f"Your coach account on Sovereign Sanctuary has been verified and approved. "
                                f"You can now sign in to the Coach Portal.\n\n"
                                f"Sign in at: https://coach.sovereignsanctuary.net\n\n"
                                f"Welcome to the team."
                            ),
                            notification_type="coach_approval"
                        ))
                    if _c_phone and _ns:
                        import asyncio
                        asyncio.create_task(_ns.send_sms(
                            to_phone=_c_phone,
                            body="Sovereign Sanctuary: Your coach account has been approved! Sign in at https://coach.sovereignsanctuary.net"
                        ))
                except Exception as _n_err:
                    logger.warning("Coach approval notification error (non-fatal): %s", _n_err)

            return {"message": "Coach status updated", "status": p["subscription_status"]}
    
    raise HTTPException(404, "Coach not found")

@router.post("/assign-coach")
async def assign_coach(req: AssignCoachRequest, request: Request):
    """Assign a coach to a client"""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: verify coach and update client
    if pool:
        try:
            async with pool.acquire() as conn:
                coach_row = await conn.fetchrow(
                    "SELECT username, hardware_id FROM users WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL",
                    req.coach_id,
                )
                if not coach_row:
                    raise HTTPException(404, "Coach not found")
                coach_username = coach_row["username"] or ""

                assign_data = json.dumps({
                    "assigned_coach_id": req.coach_id,
                    "assigned_coach": coach_username,
                    "coach_id": req.coach_id,
                    "coach_assigned_at": str(datetime.now()),
                })
                result = await conn.execute(
                    """UPDATE users SET profile_data = profile_data || $1::jsonb, updated_at = NOW()
                       WHERE hardware_id = $2 AND deleted_at IS NULL""",
                    assign_data, req.client_id,
                )
                if result and result.split()[-1] == "0":
                    raise HTTPException(404, "Client not found")
                return {"message": "Coach assigned", "client_id": req.client_id, "coach_id": req.coach_id}
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("assign_coach: PG update failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    coach_username = ""
    coach_exists = False
    for v in registry.values():
        cp = v.get("profile", {})
        if cp.get("hardware_id") == req.coach_id:
            coach_exists = True
            coach_username = v.get("credentials", {}).get("username", "")
            break
    
    if not coach_exists:
        raise HTTPException(404, "Coach not found")
    
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.client_id:
            p["assigned_coach_id"] = req.coach_id
            p["assigned_coach"] = coach_username
            p["coach_assigned_at"] = str(datetime.now())
            save_json(DATA_DIR / "user_registry.json", registry)
            return {"message": "Coach assigned", "client_id": req.client_id, "coach_id": req.coach_id}
    
    raise HTTPException(404, "Client not found")


# ==================== MULTI-COACH ASSIGNMENT ====================

@router.post("/assign-coaches")
async def assign_coaches(req: MultiCoachAssignRequest, request: Request):
    """Assign one or more coaches to an entity (client/family/group/company)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    if req.entity_type not in ("client", "family", "group", "company"):
        raise HTTPException(400, "entity_type must be client/family/group/company")
    if not req.coach_ids:
        raise HTTPException(400, "coach_ids required")

    admin_user = request.state.user if hasattr(request.state, "user") else {}
    admin_name = admin_user.get("username", "admin") if isinstance(admin_user, dict) else "admin"

    async with pool.acquire() as conn:
        for cid in req.coach_ids:
            coach_row = await conn.fetchrow(
                "SELECT username, hardware_id FROM users WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL",
                cid,
            )
            if not coach_row:
                raise HTTPException(404, f"Coach {cid} not found")

        has_primary = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM coach_assignments WHERE entity_type=$1 AND entity_id=$2 AND is_primary=TRUE)",
            req.entity_type, req.entity_id,
        )

        created = []
        for i, cid in enumerate(req.coach_ids):
            make_primary = (not has_primary and i == 0)
            try:
                await conn.execute(
                    """INSERT INTO coach_assignments (coach_id, entity_type, entity_id, is_primary, assigned_by)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (coach_id, entity_type, entity_id) DO NOTHING""",
                    cid, req.entity_type, req.entity_id, make_primary, admin_name,
                )
                created.append(cid)
                if make_primary:
                    has_primary = True
            except Exception as e:
                logger.warning("assign_coaches: insert failed for %s: %s", cid, e)

        if created and req.entity_type == "client":
            primary_cid = req.coach_ids[0]
            coach_row = await conn.fetchrow(
                "SELECT username FROM users WHERE hardware_id = $1", primary_cid,
            )
            coach_username = coach_row["username"] if coach_row else ""
            assign_data = json.dumps({
                "coach_id": primary_cid,
                "assigned_coach_id": primary_cid,
                "assigned_coach": coach_username,
            })
            await conn.execute(
                "UPDATE users SET profile_data = profile_data || $1::jsonb, updated_at = NOW() WHERE hardware_id = $2",
                assign_data, req.entity_id,
            )
        elif created and req.entity_type == "family":
            primary_cid = req.coach_ids[0]
            coach_row = await conn.fetchrow(
                "SELECT username FROM users WHERE hardware_id = $1", primary_cid,
            )
            coach_username = coach_row["username"] if coach_row else ""
            assign_data = json.dumps({
                "coach_id": primary_cid,
                "assigned_coach_id": primary_cid,
                "assigned_coach": coach_username,
            })
            await conn.execute(
                """UPDATE users SET profile_data = profile_data || $1::jsonb, updated_at = NOW()
                   WHERE family_id = (SELECT family_id FROM users WHERE hardware_id = $2 LIMIT 1)
                   AND role = 'CLIENT' AND deleted_at IS NULL""",
                assign_data, req.entity_id,
            )

    return {"message": f"{len(created)} coach(es) assigned", "coaches": created, "entity": req.entity_id}


@router.delete("/unassign-coach")
async def unassign_coach(req: UnassignCoachRequest, request: Request):
    """Remove a coach from an entity. Promotes next-oldest to primary if needed."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM coach_assignments WHERE coach_id=$1 AND entity_type=$2 AND entity_id=$3 RETURNING is_primary",
            req.coach_id, req.entity_type, req.entity_id,
        )
        if not row:
            raise HTTPException(404, "Assignment not found")

        new_primary = None
        if row["is_primary"]:
            next_row = await conn.fetchrow(
                """UPDATE coach_assignments SET is_primary = TRUE
                   WHERE id = (
                       SELECT id FROM coach_assignments
                       WHERE entity_type=$1 AND entity_id=$2
                       ORDER BY assigned_at ASC LIMIT 1
                   ) RETURNING coach_id""",
                req.entity_type, req.entity_id,
            )
            new_primary = next_row["coach_id"] if next_row else None

            if req.entity_type == "client":
                if new_primary:
                    coach_row = await conn.fetchrow(
                        "SELECT username FROM users WHERE hardware_id = $1", new_primary,
                    )
                    assign_data = json.dumps({
                        "coach_id": new_primary,
                        "assigned_coach_id": new_primary,
                        "assigned_coach": coach_row["username"] if coach_row else "",
                    })
                    await conn.execute(
                        "UPDATE users SET profile_data = profile_data || $1::jsonb, updated_at = NOW() WHERE hardware_id = $2",
                        assign_data, req.entity_id,
                    )
                else:
                    clear_data = json.dumps({"coach_id": None, "assigned_coach_id": None, "assigned_coach": None})
                    await conn.execute(
                        "UPDATE users SET profile_data = profile_data || $1::jsonb, updated_at = NOW() WHERE hardware_id = $2",
                        clear_data, req.entity_id,
                    )

    return {"message": "Coach unassigned", "new_primary": new_primary}


@router.get("/assignments")
async def list_assignments(
    request: Request,
    entity_type: str = None,
    entity_id: str = None,
    coach_id: str = None,
):
    """List coach assignments with optional filters."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    conditions = []
    params = []
    idx = 1
    if entity_type:
        conditions.append(f"ca.entity_type = ${idx}")
        params.append(entity_type)
        idx += 1
    if entity_id:
        conditions.append(f"ca.entity_id = ${idx}")
        params.append(entity_id)
        idx += 1
    if coach_id:
        conditions.append(f"ca.coach_id = ${idx}")
        params.append(coach_id)
        idx += 1

    where = " AND ".join(conditions)
    if where:
        where = "WHERE " + where

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT ca.id, ca.coach_id, ca.entity_type, ca.entity_id,
                       ca.is_primary, ca.assigned_at, ca.assigned_by,
                       u.username as coach_username,
                       u.profile_data->>'name' as coach_name
                FROM coach_assignments ca
                LEFT JOIN users u ON u.hardware_id = ca.coach_id AND u.role = 'COACH'
                {where}
                ORDER BY ca.entity_type, ca.entity_id, ca.assigned_at ASC""",
            *params,
        )

    return [
        {
            "id": str(r["id"]),
            "coach_id": r["coach_id"],
            "coach_username": r["coach_username"],
            "coach_name": r["coach_name"],
            "entity_type": r["entity_type"],
            "entity_id": r["entity_id"],
            "is_primary": r["is_primary"],
            "assigned_at": r["assigned_at"].isoformat() if r["assigned_at"] else None,
            "assigned_by": r["assigned_by"],
        }
        for r in rows
    ]


@router.post("/assign-coach-hierarchy")
async def assign_coach_hierarchy(req: CoachHierarchyRequest, request: Request):
    """Create master/assistant coach hierarchy links (admin bypass — no invite needed)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    if not req.assistant_coach_ids:
        raise HTTPException(400, "assistant_coach_ids required")

    async with pool.acquire() as conn:
        master = await conn.fetchrow(
            "SELECT username FROM users WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL",
            req.master_coach_id,
        )
        if not master:
            raise HTTPException(404, "Master coach not found")

        # Admin bypass: auto-approve master coach status
        await conn.execute(
            """UPDATE users SET profile_data = jsonb_set(
                   jsonb_set(profile_data, '{master_coach_approved}', 'true'::jsonb),
                   '{master_coach_requested}', 'false'::jsonb
               )
               WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL""",
            req.master_coach_id,
        )

        created = []
        for aid in req.assistant_coach_ids:
            asst = await conn.fetchrow(
                "SELECT username FROM users WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL", aid,
            )
            if not asst:
                continue
            try:
                await conn.execute(
                    """INSERT INTO coach_hierarchy (master_coach_id, assistant_id, status, accepted_at, created_at)
                       VALUES ($1, $2, 'active', NOW(), NOW())
                       ON CONFLICT (master_coach_id, assistant_id) DO NOTHING""",
                    req.master_coach_id, aid,
                )
                created.append({"assistant_id": aid, "assistant_name": asst["username"]})
            except Exception as e:
                logger.warning("assign_coach_hierarchy: %s", e)

    return {"message": f"{len(created)} hierarchy link(s) created", "master": req.master_coach_id, "assistants": created}


@router.delete("/remove-coach-hierarchy")
async def remove_coach_hierarchy(req: RemoveHierarchyRequest, request: Request):
    """Revoke a master/assistant coach hierarchy link."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE coach_hierarchy SET status = 'revoked', revoked_at = NOW()
               WHERE master_coach_id = $1 AND assistant_id = $2 AND status = 'active'""",
            req.master_coach_id, req.assistant_coach_id,
        )
        if result and result.split()[-1] == "0":
            raise HTTPException(404, "Hierarchy link not found or already revoked")

    return {"message": "Hierarchy link revoked"}


@router.get("/coach-hierarchy")
async def get_coach_hierarchy(request: Request):
    """Get all active coach hierarchy relationships."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ch.id, ch.master_coach_id, ch.assistant_id, ch.status, ch.created_at,
                      m.username as master_username, m.profile_data->>'name' as master_name,
                      a.username as assistant_username, a.profile_data->>'name' as assistant_name
               FROM coach_hierarchy ch
               LEFT JOIN users m ON m.hardware_id = ch.master_coach_id AND m.role = 'COACH'
               LEFT JOIN users a ON a.hardware_id = ch.assistant_id AND a.role = 'COACH'
               WHERE ch.status = 'active'
               ORDER BY ch.created_at DESC"""
        )

    return [
        {
            "id": str(r["id"]),
            "master_coach_id": r["master_coach_id"],
            "master_username": r["master_username"],
            "master_name": r["master_name"],
            "assistant_coach_id": r["assistant_id"],
            "assistant_username": r["assistant_username"],
            "assistant_name": r["assistant_name"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


# ── Master Coach Approval ──────────────────────────────────────

@router.get("/pending-master-requests")
async def get_pending_master_requests(request: Request):
    """List coaches who have requested master coach status."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT username, hardware_id, profile_data->>'name' as name,
                      profile_data->>'email' as email,
                      profile_data->>'coach_verified' as coach_verified,
                      profile_data->>'specializations' as specializations
               FROM users
               WHERE role = 'COACH' AND deleted_at IS NULL
                 AND profile_data->>'master_coach_requested' = 'true'
                 AND (profile_data->>'master_coach_approved' IS NULL
                      OR profile_data->>'master_coach_approved' != 'true')
               ORDER BY updated_at DESC"""
        )

    return [
        {
            "username": r["username"],
            "hardware_id": r["hardware_id"],
            "name": r["name"],
            "email": r["email"],
            "coach_verified": r["coach_verified"] == "true" if r["coach_verified"] else False,
            "specializations": r["specializations"],
        }
        for r in rows
    ]


@router.post("/approve-master-coach")
async def approve_master_coach(request: Request):
    """Approve a coach as a master coach."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    body = await request.json()
    hw_id = body.get("hardware_id", "")
    if not hw_id:
        raise HTTPException(400, "hardware_id required")

    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE users SET profile_data = jsonb_set(
                   jsonb_set(profile_data, '{master_coach_approved}', 'true'::jsonb),
                   '{master_coach_requested}', 'false'::jsonb
               )
               WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL""",
            hw_id,
        )
        if result and result.split()[-1] == "0":
            raise HTTPException(404, "Coach not found")

    return {"message": "Master coach approved", "hardware_id": hw_id}


@router.post("/reject-master-coach")
async def reject_master_coach(request: Request):
    """Reject a master coach request."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    body = await request.json()
    hw_id = body.get("hardware_id", "")
    if not hw_id:
        raise HTTPException(400, "hardware_id required")

    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE users SET profile_data = jsonb_set(
                   profile_data, '{master_coach_requested}', 'false'::jsonb
               )
               WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL""",
            hw_id,
        )
        if result and result.split()[-1] == "0":
            raise HTTPException(404, "Coach not found")

    return {"message": "Master coach request rejected", "hardware_id": hw_id}


# ── Hierarchy Invitation Approval ──────────────────────────────

@router.get("/pending-hierarchy-invitations")
async def get_pending_hierarchy_invitations(request: Request):
    """List assistant invitations awaiting admin approval."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ch.id, ch.master_coach_id, ch.assistant_id, ch.invited_at,
                      m.username as master_username, m.profile_data->>'name' as master_name,
                      a.username as assistant_username, a.profile_data->>'name' as assistant_name
               FROM coach_hierarchy ch
               LEFT JOIN users m ON m.hardware_id = ch.master_coach_id AND m.role = 'COACH'
               LEFT JOIN users a ON a.hardware_id = ch.assistant_id AND a.role = 'COACH'
               WHERE ch.status = 'pending_admin'
               ORDER BY ch.invited_at DESC"""
        )

    return [
        {
            "id": str(r["id"]),
            "master_coach_id": r["master_coach_id"],
            "master_username": r["master_username"],
            "master_name": r["master_name"],
            "assistant_id": r["assistant_id"],
            "assistant_username": r["assistant_username"],
            "assistant_name": r["assistant_name"],
            "invited_at": r["invited_at"].isoformat() if r["invited_at"] else None,
        }
        for r in rows
    ]


@router.post("/approve-hierarchy-invitation")
async def approve_hierarchy_invitation(request: Request):
    """Approve a pending_admin hierarchy invitation → becomes 'pending' for assistant to accept."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    body = await request.json()
    hierarchy_id = body.get("hierarchy_id", "")
    if not hierarchy_id:
        raise HTTPException(400, "hierarchy_id required")

    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE coach_hierarchy SET status = 'pending'
               WHERE id = $1::int AND status = 'pending_admin'""",
            int(hierarchy_id),
        )
        if result and result.split()[-1] == "0":
            raise HTTPException(404, "Invitation not found or already processed")

    return {"message": "Hierarchy invitation approved — assistant can now accept"}


@router.post("/reject-hierarchy-invitation")
async def reject_hierarchy_invitation(request: Request):
    """Reject a pending_admin hierarchy invitation."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    body = await request.json()
    hierarchy_id = body.get("hierarchy_id", "")
    if not hierarchy_id:
        raise HTTPException(400, "hierarchy_id required")

    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE coach_hierarchy SET status = 'rejected'
               WHERE id = $1::int AND status = 'pending_admin'""",
            int(hierarchy_id),
        )
        if result and result.split()[-1] == "0":
            raise HTTPException(404, "Invitation not found or already processed")

    return {"message": "Hierarchy invitation rejected"}


# Crisis Management
@router.get("/crisis-watchlist")
async def get_crisis_watchlist(request: Request):
    """Get users with elevated risk levels — PostgreSQL primary."""
    pool = getattr(request.app.state, "db_pool", None)

    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT cw.user_id, u.name, u.hardware_id,
                           cw.severity as risk_level, cw.trigger_type, cw.trigger_keyword,
                           cw.trigger_context, cw.last_activity, cw.silence_days,
                           cw.assigned_coach_id, cw.created_at,
                           u.last_login, u.profile_data
                    FROM crisis_watchlist cw
                    JOIN users u ON cw.user_id = u.id
                    WHERE cw.resolved = FALSE
                    ORDER BY CASE cw.severity
                        WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1
                        WHEN 'MEDIUM' THEN 2 ELSE 3 END
                """)

                watchlist = []
                for r in rows:
                    pd = r["profile_data"] or {}
                    if isinstance(pd, str):
                        pd = json.loads(pd)
                    watchlist.append({
                        "user_id": r["hardware_id"] or str(r["user_id"]),
                        "user_name": r["name"] or pd.get("name", ""),
                        "name": r["name"] or pd.get("name", ""),
                        "risk_level": r["risk_level"] or "MEDIUM",
                        "reason": r["trigger_context"] or r["trigger_type"] or "",
                        "keywords": [r["trigger_keyword"]] if r["trigger_keyword"] else [],
                        "assigned_coach": str(r["assigned_coach_id"]) if r["assigned_coach_id"] else "",
                        "last_login": r["last_login"].isoformat() if r["last_login"] else "",
                        "timestamp": r["created_at"].isoformat() if r["created_at"] else "",
                    })

                return {"watchlist": watchlist, "count": len(watchlist)}
        except Exception as e:
            logger.warning("get_crisis_watchlist: PG read failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    watchlist = []
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("role") != "CLIENT":
            continue
        metrics_file = VAULT_ROOT / "Clients" / p.get("hardware_id") / "metrics.json"
        metrics = load_json(metrics_file, {})
        ns = metrics.get("nevedal_state", {})
        risk = ns.get("risk_level", "LOW")
        if risk in ["MEDIUM", "HIGH", "CRITICAL"]:
            watchlist.append({
                "user_id": p.get("hardware_id"), "name": p.get("name"),
                "risk_level": risk, "anxiety": ns.get("anxiety_level", 0),
                "depression": ns.get("depression_indicators", 0),
                "crisis_count": ns.get("crisis_count", 0),
                "assigned_coach": p.get("assigned_coach_id", ""),
                "last_login": p.get("last_login", ""),
            })
    risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
    watchlist.sort(key=lambda x: risk_order.get(x["risk_level"], 3))
    return {"watchlist": watchlist, "count": len(watchlist)}

@router.get("/crisis-log")
async def get_crisis_log(request: Request, resolved: bool = None, limit: int = 50):
    """Get crisis event log — PostgreSQL primary."""
    pool = getattr(request.app.state, "db_pool", None)

    if pool:
        try:
            async with pool.acquire() as conn:
                if resolved is not None:
                    rows = await conn.fetch("""
                        SELECT id, user_name, hardware_id, risk_level, reason,
                               keywords, session_id, family_id, resolved,
                               resolved_at, resolved_by, resolution_notes, timestamp
                        FROM crisis_events WHERE resolved = $1
                        ORDER BY timestamp DESC LIMIT $2
                    """, resolved, limit)
                    total = await conn.fetchval(
                        "SELECT COUNT(*) FROM crisis_events WHERE resolved = $1", resolved
                    )
                else:
                    rows = await conn.fetch("""
                        SELECT id, user_name, hardware_id, risk_level, reason,
                               keywords, session_id, family_id, resolved,
                               resolved_at, resolved_by, resolution_notes, timestamp
                        FROM crisis_events ORDER BY timestamp DESC LIMIT $1
                    """, limit)
                    total = await conn.fetchval("SELECT COUNT(*) FROM crisis_events")

                events = []
                for r in rows:
                    events.append({
                        "id": r["id"],
                        "user_id": r["hardware_id"] or "",
                        "user_name": r["user_name"] or "",
                        "risk_level": r["risk_level"] or "medium",
                        "reason": r["reason"] or "",
                        "keywords": list(r["keywords"]) if r["keywords"] else [],
                        "session_id": r["session_id"] or "",
                        "family_id": r["family_id"] or "",
                        "resolved": r["resolved"],
                        "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
                        "resolved_by": r["resolved_by"],
                        "resolution_notes": r["resolution_notes"],
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else "",
                    })
                return {"crises": events, "events": events, "total": total or 0}
        except Exception as e:
            logger.warning("get_crisis_log: PG read failed, falling back to JSON: %s", e)

    # JSON fallback
    crisis_log = load_json(DATA_DIR / "crisis_log.json", [])
    if resolved is not None:
        crisis_log = [c for c in crisis_log if c.get("resolved", False) == resolved]
    crisis_log.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"crises": crisis_log[:limit], "events": crisis_log[:limit], "total": len(crisis_log)}

@router.post("/crisis/resolve")
async def resolve_crisis(req: ResolveCrisisRequest, request: Request):
    """Mark a crisis as resolved"""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: resolve by ID in crisis_events table
    if pool:
        try:
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """UPDATE crisis_events SET resolved = TRUE, resolved_by = $1,
                       resolution_notes = $2, resolved_at = NOW()
                       WHERE id = $3
                       RETURNING id, user_name, risk_level, reason, resolved, resolved_at""",
                    req.resolved_by, req.resolution_notes, req.crisis_id,
                )
                if result:
                    return {"message": "Crisis resolved", "crisis": {
                        "id": result["id"],
                        "user_name": result["user_name"],
                        "risk_level": result["risk_level"],
                        "reason": result["reason"],
                        "resolved": result["resolved"],
                        "resolved_at": result["resolved_at"].isoformat() if result["resolved_at"] else None,
                        "resolved_by": req.resolved_by,
                        "resolution_notes": req.resolution_notes,
                    }}
        except Exception as e:
            logger.warning("resolve_crisis: PG update failed, falling back to JSON: %s", e)

    # JSON fallback
    crisis_log = load_json(DATA_DIR / "crisis_log.json", [])
    if req.crisis_id >= len(crisis_log):
        raise HTTPException(404, "Crisis not found")
    
    crisis_log[req.crisis_id]["resolved"] = True
    crisis_log[req.crisis_id]["resolved_by"] = req.resolved_by
    crisis_log[req.crisis_id]["resolution_notes"] = req.resolution_notes
    crisis_log[req.crisis_id]["resolved_at"] = str(datetime.now())
    
    save_json(DATA_DIR / "crisis_log.json", crisis_log)
    return {"message": "Crisis resolved", "crisis": crisis_log[req.crisis_id]}

# Night School / Learning
@router.get("/night-school/status")
async def get_night_school_status():
    """Get Night School learning status"""
    wisdom_file = VAULT_ROOT / "Admin" / "little_nate_wisdom.json"
    learnings_file = VAULT_ROOT / "Admin" / "learning_history.json"
    
    wisdom = load_json(wisdom_file, {})
    learnings = load_json(learnings_file, [])
    
    # Group by source
    by_source = {}
    for l in learnings:
        source = l.get("source", "unknown")
        by_source[source] = by_source.get(source, 0) + 1
    
    return {
        "total_learnings": len(learnings),
        "last_synthesis": wisdom.get("last_synthesis", "Never"),
        "categories": wisdom.get("categories", []),
        "by_source": by_source,
        "recent_learnings": learnings[-10:]
    }

@router.post("/night-school/add-learning")
async def add_learning(content: str, category: str = "admin", source: str = "ADMIN_MANUAL"):
    """Manually add a learning to Night School"""
    import secrets
    import hashlib
    
    learnings_file = VAULT_ROOT / "Admin" / "learning_history.json"
    learnings = load_json(learnings_file, [])
    
    content_hash = hashlib.md5(content.encode()).hexdigest()
    
    # Check for duplicates
    for l in learnings:
        if l.get("content_hash") == content_hash:
            raise HTTPException(409, "Duplicate learning")
    
    entry = {
        "id": secrets.token_hex(8),
        "content": content,
        "content_hash": content_hash,
        "source": source,
        "category": category,
        "timestamp": str(datetime.now()),
        "times_applied": 0,
        "deprecated": False
    }
    
    learnings.append(entry)
    save_json(learnings_file, learnings[-1000:])
    
    return {"message": "Learning added", "entry": entry}

# Analytics History
@router.get("/analytics/daily")
async def get_daily_analytics(request: Request, days: int = 30):
    """Get daily analytics for the past N days"""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: read from daily_analytics table
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT date, logins, registrations, messages_sent, sessions_started,
                              tokens_used, active_users
                       FROM daily_analytics
                       WHERE date >= (CURRENT_DATE - $1::int)
                       ORDER BY date ASC""",
                    days,
                )
                if rows:
                    result = []
                    for r in rows:
                        unique = r.get("active_users")
                        if isinstance(unique, list):
                            unique_count = len(unique)
                        elif isinstance(unique, int):
                            unique_count = unique
                        else:
                            unique_count = 0
                        result.append({
                            "date": str(r["date"]),
                            "logins": r.get("logins") or 0,
                            "registrations": r.get("registrations") or 0,
                            "messages": r.get("messages_sent") or 0,
                            "sessions": r.get("sessions_started") or 0,
                            "tokens": r.get("tokens_used") or 0,
                            "unique_users": unique_count,
                        })
                    return {"analytics": result}
        except Exception as e:
            logger.warning("get_daily_analytics: PG read failed, falling back to JSON: %s", e)

    # JSON fallback
    analytics = load_json(DATA_DIR / "analytics.json")
    daily = analytics.get("daily_stats", {})
    result = []
    for i in range(days):
        date = str((datetime.now() - timedelta(days=i)).date())
        stats = daily.get(date, {})
        result.append({
            "date": date,
            "logins": stats.get("logins", 0),
            "registrations": stats.get("registrations", 0),
            "messages": stats.get("messages_sent", 0),
            "sessions": stats.get("sessions_started", 0),
            "tokens": stats.get("tokens_used", 0),
            "unique_users": len(stats.get("unique_users", []))
        })
    result.reverse()
    return {"analytics": result}

@router.get("/analytics/metrics-distribution")
async def get_metrics_distribution(request: Request):
    """Get distribution of client metrics"""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: aggregate from client_metrics table
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT cm.nevedal_state, cm.c_emo, cm.risk_level
                       FROM client_metrics cm
                       JOIN users u ON cm.hardware_id = u.hardware_id
                       WHERE u.role = 'CLIENT' AND u.deleted_at IS NULL"""
                )
                if rows:
                    gap_scores = []
                    anxiety_levels = []
                    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
                    for r in rows:
                        ns = r.get("nevedal_state") or {}
                        if isinstance(ns, str):
                            ns = json.loads(ns)
                        gap = ns.get("GAP", 0.5) if isinstance(ns, dict) else 0.5
                        anxiety = ns.get("anxiety_level", 0) if isinstance(ns, dict) else 0
                        risk = (r.get("risk_level") or "LOW").upper()
                        gap_scores.append(gap)
                        anxiety_levels.append(anxiety)
                        if risk in risk_counts:
                            risk_counts[risk] += 1
                    return {
                        "gap_scores": {
                            "average": sum(gap_scores) / len(gap_scores) if gap_scores else 0,
                            "min": min(gap_scores) if gap_scores else 0,
                            "max": max(gap_scores) if gap_scores else 0,
                        },
                        "anxiety_levels": {
                            "average": sum(anxiety_levels) / len(anxiety_levels) if anxiety_levels else 0,
                            "high_count": len([a for a in anxiety_levels if a > 0.5]),
                        },
                        "risk_distribution": risk_counts,
                        "total_clients": len(gap_scores),
                    }
        except Exception as e:
            logger.warning("get_metrics_distribution: PG read failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    gap_scores = []
    anxiety_levels = []
    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("role") != "CLIENT":
            continue
        metrics_file = VAULT_ROOT / "Clients" / p.get("hardware_id") / "metrics.json"
        metrics = load_json(metrics_file, {})
        ns = metrics.get("nevedal_state", {})
        gap = ns.get("GAP", 0.5)
        anxiety = ns.get("anxiety_level", 0)
        risk = ns.get("risk_level", "LOW")
        gap_scores.append(gap)
        anxiety_levels.append(anxiety)
        if risk in risk_counts:
            risk_counts[risk] += 1
    return {
        "gap_scores": {
            "average": sum(gap_scores) / len(gap_scores) if gap_scores else 0,
            "min": min(gap_scores) if gap_scores else 0,
            "max": max(gap_scores) if gap_scores else 0
        },
        "anxiety_levels": {
            "average": sum(anxiety_levels) / len(anxiety_levels) if anxiety_levels else 0,
            "high_count": len([a for a in anxiety_levels if a > 0.5])
        },
        "risk_distribution": risk_counts,
        "total_clients": len(gap_scores)
    }


# =============================================================================
# LIVE SESSIONS — Active sessions from LIVE_SESSION_TRACKER
# =============================================================================

@router.get("/live-sessions")
async def get_live_sessions():
    """Return all currently active sessions."""
    try:
        from app.websocket.bridge_server import LIVE_SESSION_TRACKER
        live = []
        for sid, sess in LIVE_SESSION_TRACKER.items():
            live.append({
                "session_id": sid,
                "client_id": sess.get("client_id", ""),
                "started_at": sess.get("started_at", ""),
                "session_type": sess.get("session_type", "ai"),
                "mood": sess.get("mood_at_start", ""),
            })
        return {"sessions": live, "count": len(live)}
    except ImportError:
        return {"sessions": [], "count": 0, "note": "Bridge server not loaded in this process"}


# =============================================================================
# COMMUNITY HEALTH — Aggregate coherence metrics
# =============================================================================

@router.get("/community-health")
async def get_community_health(request: Request):
    """Aggregate community-wide coherence metrics — PostgreSQL primary."""
    pool = getattr(request.app.state, "db_pool", None)

    if pool:
        try:
            async with pool.acquire() as conn:
                total_clients = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE role = 'CLIENT' AND deleted_at IS NULL"
                ) or 0

                agg = await conn.fetchrow("""
                    SELECT AVG(c_emo) as avg_c_emo,
                           MIN(c_emo) as min_c_emo,
                           MAX(c_emo) as max_c_emo,
                           COUNT(*) as with_data
                    FROM client_metrics WHERE c_emo > 0
                """)

                risk_rows = await conn.fetch("""
                    SELECT risk_level, COUNT(*) as cnt
                    FROM client_metrics GROUP BY risk_level
                """)
                risk_dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
                for r in risk_rows:
                    key = (r["risk_level"] or "LOW").upper()
                    if key in risk_dist:
                        risk_dist[key] = r["cnt"]

            return {
                "total_clients": total_clients,
                "total_participants": total_clients,
                "avg_c_emo": round(float(agg["avg_c_emo"] or 0), 4) if agg else 0,
                "c_emo_range": {
                    "min": round(float(agg["min_c_emo"] or 0), 4) if agg else 0,
                    "max": round(float(agg["max_c_emo"] or 0), 4) if agg else 0,
                },
                "risk_distribution": risk_dist,
                "active_cee_windows": 0,
                "clients_with_data": int(agg["with_data"] or 0) if agg else 0,
            }
        except Exception as e:
            logger.warning("get_community_health: PG read failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = load_json(DATA_DIR / "user_registry.json")
    total_clients = 0
    c_emo_values = []
    risk_distribution = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    cee_count = 0
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("role") != "CLIENT":
            continue
        total_clients += 1
        metrics_file = VAULT_ROOT / "Clients" / p.get("hardware_id") / "metrics.json"
        metrics = load_json(metrics_file, {})
        ns = metrics.get("nevedal_state", {})
        c_emo = ns.get("c_emo", 0)
        if c_emo:
            c_emo_values.append(c_emo)
        risk = ns.get("risk_level", "LOW")
        if risk in risk_distribution:
            risk_distribution[risk] += 1
        if ns.get("cee_window"):
            cee_count += 1
    avg_c_emo = sum(c_emo_values) / len(c_emo_values) if c_emo_values else 0
    return {
        "total_clients": total_clients, "avg_c_emo": round(avg_c_emo, 4),
        "c_emo_range": {"min": round(min(c_emo_values), 4) if c_emo_values else 0, "max": round(max(c_emo_values), 4) if c_emo_values else 0},
        "risk_distribution": risk_distribution, "active_cee_windows": cee_count, "clients_with_data": len(c_emo_values),
    }


# =============================================================================
# ACTIVITY FEED — Recent system events from audit_log
# =============================================================================

@router.get("/activity-feed")
async def get_activity_feed(limit: int = 50):
    """Return recent activity from daily analytics and audit events."""
    analytics_dir = DATA_DIR / "analytics"
    events = []

    if analytics_dir.exists():
        # Gather from most recent daily stats files
        stat_files = sorted(analytics_dir.glob("daily_*.json"), reverse=True)[:7]
        for sf in stat_files:
            stats = load_json(sf, {})
            date_str = sf.stem.replace("daily_", "")
            if stats.get("sessions_started"):
                events.append({
                    "type": "sessions",
                    "date": date_str,
                    "message": f"{stats['sessions_started']} sessions started",
                    "detail": stats,
                })
            if stats.get("new_users"):
                events.append({
                    "type": "new_users",
                    "date": date_str,
                    "message": f"{stats['new_users']} new users registered",
                })

    # Also pull from recent notifications log
    notifications_file = DATA_DIR / "notifications.json"
    if notifications_file.exists():
        try:
            all_notifs = load_json(notifications_file, [])
            if isinstance(all_notifs, list):
                for n in all_notifs[-limit:]:
                    events.append({
                        "type": "notification",
                        "date": n.get("created_at", ""),
                        "message": n.get("message", ""),
                        "priority": n.get("priority", "NORMAL"),
                    })
        except Exception as e:
            logger.warning("get_activity_feed: notifications parse failed: %s", e)

    # Sort by date descending, limit
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    return {"events": events[:limit], "count": len(events[:limit])}


# =============================================================================
# TOKEN ECONOMICS — Azure OpenAI usage tracking
# =============================================================================

@router.get("/token-economics")
async def get_token_economics():
    """Return token usage and cost estimates from daily analytics."""
    analytics_dir = DATA_DIR / "analytics"
    daily_usage = []
    total_tokens = 0

    if analytics_dir.exists():
        stat_files = sorted(analytics_dir.glob("daily_*.json"), reverse=True)[:30]
        for sf in stat_files:
            stats = load_json(sf, {})
            tokens = stats.get("tokens_used", 0)
            total_tokens += tokens
            daily_usage.append({
                "date": sf.stem.replace("daily_", ""),
                "tokens": tokens,
                "sessions": stats.get("sessions_started", 0),
            })

    # Cost estimation (GPT-4o pricing approximation)
    # Input: $2.50/1M tokens, Output: $10/1M tokens, blended ~$6/1M
    estimated_cost_usd = round(total_tokens * 6 / 1_000_000, 2)

    return {
        "total_tokens_30d": total_tokens,
        "estimated_cost_30d_usd": estimated_cost_usd,
        "daily_usage": daily_usage,
        "pricing_note": "Estimated at ~$6/1M tokens blended GPT-4o rate",
    }


# =============================================================================
# BILLING — Revenue Analytics & Subscription Management
# =============================================================================

# Stripe SDK (optional)
try:
    import stripe as _stripe
    _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    _STRIPE_AVAILABLE = bool(_stripe.api_key)
except ImportError:
    _STRIPE_AVAILABLE = False

PLAN_PRICES = {
    "STANDARD": 49,
    "INNER_CHAMBER": 49,
    "TOP_TIER": 149,
    "SOVEREIGN_CIRCLE": 149,
}

PLAN_LABELS = {
    "COACH_ONLY": "Coach Only",
    "TRIAL": "Threshold (Trial)",
    "STANDARD": "Inner Chamber",
    "INNER_CHAMBER": "Inner Chamber",
    "TOP_TIER": "Sovereign Circle",
    "SOVEREIGN_CIRCLE": "Sovereign Circle",
}


TIER_FEATURES = {
    "TOP_TIER": {"voice": True, "vision": True, "me2me": True, "family": True, "secure_search": True, "night_school": True},
    "STANDARD": {"voice": True, "vision": True, "me2me": False, "family": True, "secure_search": False, "night_school": False},
    "TRIAL": {"voice": True, "vision": False, "me2me": False, "family": False, "secure_search": False, "night_school": False},
    "COACH_ONLY": {"voice": False, "vision": False, "me2me": False, "family": False, "secure_search": False, "night_school": False},
}


@router.get("/billing/tier-config")
async def get_tier_config(request: Request):
    """Return canonical tier definitions — prices, labels, feature gates."""
    registry = await _load_registry_async(request)
    tier_counts: Dict[str, int] = {}
    for entry in registry.values():
        plan = (entry.get("profile", {}).get("subscription_plan") or "TRIAL").upper()
        tier_counts[plan] = tier_counts.get(plan, 0) + 1

    tiers = []
    for key in ("TOP_TIER", "STANDARD", "TRIAL", "COACH_ONLY"):
        tiers.append({
            "key": key,
            "label": PLAN_LABELS.get(key, key),
            "price": PLAN_PRICES.get(key, 0),
            "price_display": f"${PLAN_PRICES[key]}/mo" if key in PLAN_PRICES else "Free" if key == "COACH_ONLY" else "Free — 14 days",
            "features": TIER_FEATURES.get(key, {}),
            "subscriber_count": tier_counts.get(key, 0),
        })
    return {"tiers": tiers}


class OverridePlanRequest(BaseModel):
    user_id: str
    new_plan: str
    admin_note: str = ""


class RefundRequest(BaseModel):
    user_id: str
    amount: float
    reason: str = ""


class CouponRequest(BaseModel):
    code: str
    discount: float
    type: str = "percent"  # "percent" or "fixed"


_ADMIN_CODE_PATTERN = re.compile(r'^[A-Z0-9_\-]{2,40}$')
_VALID_DISCOUNT_TYPES = {"percent", "amount"}
_VALID_DURATIONS = {"once", "repeating", "forever"}
_VALID_TIERS = {"COACH_ONLY", "TRIAL", "STANDARD", "TOP_TIER", "INNER_CHAMBER", "SOVEREIGN_CIRCLE"}


class CreatePromoRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=2, max_length=40)
    discount_type: str = "percent"
    discount_value: int = Field(..., ge=1)
    coach_id: Optional[str] = Field(None, min_length=1, max_length=128)
    applicable_tiers: List[str] = []
    starts_at: Optional[str] = None
    ends_at: str
    max_redemptions: Optional[int] = Field(None, ge=1, le=1000000)
    duration: str = "once"
    duration_in_months: Optional[int] = Field(None, ge=1, le=36)


class CreateSchoolCodeRequest(BaseModel):
    school_name: str = Field(..., min_length=1, max_length=200)
    school_code: str = Field(..., min_length=2, max_length=40)
    discount_percent: int = Field(10, ge=1, le=100)
    max_students: Optional[int] = Field(None, ge=1, le=100000)


class CreateCorporateRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    sponsor_code: str = Field(..., min_length=2, max_length=40)
    discount_type: str = "percent"
    discount_value: int = Field(0, ge=0)
    pays_full: bool = False
    max_employees: Optional[int] = Field(None, ge=1, le=100000)
    billing_contact_email: Optional[str] = Field(None, max_length=255)


class UpdateSettingsRequest(BaseModel):
    key: str
    value: str


class RetryPaymentRequest(BaseModel):
    payment_id: str


def _load_registry():
    return load_json(DATA_DIR / "user_registry.json")


async def _load_registry_async(request=None):
    """Load registry from PG first, JSON fallback."""
    pool = getattr(request.app.state, "db_pool", None) if request else None
    if pool:
        try:
            registry = await load_registry_pg(pool)
            if registry:
                return registry
        except Exception as e:
            logger.warning("_load_registry_async: PG read failed: %s", e)
    return load_json(DATA_DIR / "user_registry.json")


async def _save_registry_async(reg, request=None):
    """Save registry to JSON and sync to PostgreSQL if pool is available."""
    # Always write JSON
    with open(DATA_DIR / "user_registry.json", "w") as f:
        json.dump(reg, f, indent=2, default=str)
    # Also sync to PostgreSQL if available (so the bridge's in-memory cache stays current)
    if request and hasattr(request.app.state, "db_pool") and request.app.state.db_pool:
        try:
            from app.websocket.user_store import UserStore
            store = UserStore(request.app.state.db_pool)
            store._ready = True
            await store.save_all(reg)
        except Exception as e:
            print(f"[admin] PG sync after registry save failed: {e}")


def _save_registry(reg):
    """Save registry to JSON (sync fallback when request object is unavailable)."""
    with open(DATA_DIR / "user_registry.json", "w") as f:
        json.dump(reg, f, indent=2, default=str)


@router.get("/billing/revenue")
async def get_revenue_metrics(request: Request):
    """Aggregated revenue metrics: MRR, coaching revenue, churn, conversion."""
    registry = await _load_registry_async(request)
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: load coaching revenue from payment_history
    billing = {}
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT COALESCE(SUM(amount_cents), 0) as total
                       FROM payment_history
                       WHERE status = 'succeeded'
                         AND event_type ILIKE '%coaching%'"""
                )
                if rows:
                    billing = {"_pg_coaching_revenue": float(rows[0]["total"]) / 100}
        except Exception as e:
            logger.warning("get_revenue_metrics: PG billing read failed: %s", e)

    if not billing:
        billing = load_json(DATA_DIR / "billing.json")

    # Count subscribers by tier
    tier_counts: Dict[str, int] = {}
    active_paid = 0
    trial_count = 0
    cancelled_count = 0
    conversions = 0
    total_trials = 0

    for _key, entry in registry.items():
        profile = entry.get("profile", {})
        plan = (profile.get("subscription_plan") or "TRIAL").upper()
        status = (profile.get("subscription_status") or "").upper()

        tier_counts[plan] = tier_counts.get(plan, 0) + 1

        if plan in ("TRIAL", "THRESHOLD", ""):
            trial_count += 1
            total_trials += 1
        elif status in ("ACTIVE",) and plan in PLAN_PRICES:
            active_paid += 1

        if status in ("CANCELLED", "EXPIRED"):
            cancelled_count += 1

        if profile.get("_trial_converted"):
            conversions += 1
            total_trials += 1

    # MRR: sum of active paid subscriptions * their monthly price
    mrr = 0
    tier_revenue: Dict[str, Dict[str, Any]] = {}
    for tier, count in tier_counts.items():
        price = PLAN_PRICES.get(tier, 0)
        # Only count "active" users for MRR
        active_in_tier = 0
        for _k, e in registry.items():
            p = e.get("profile", {})
            if (p.get("subscription_plan") or "").upper() == tier and \
               (p.get("subscription_status") or "").upper() in ("ACTIVE", "TRIAL_ACTIVE", ""):
                if tier in PLAN_PRICES:
                    active_in_tier += 1
        tier_mrr = active_in_tier * price
        mrr += tier_mrr
        tier_revenue[tier] = {"count": count, "revenue": tier_mrr}

    # Coaching revenue: PG-first, then billing.json fallback
    coaching_revenue = billing.get("_pg_coaching_revenue", 0)
    if not coaching_revenue:
        for txn in billing.get("transactions", []):
            if txn.get("type") in ("coaching_pack", "coaching_session"):
                coaching_revenue += txn.get("amount", 0)

    # Churn rate
    total_ever = active_paid + cancelled_count
    churn_rate = cancelled_count / total_ever if total_ever > 0 else 0

    # Trial conversion rate
    conversion_rate = conversions / total_trials if total_trials > 0 else 0

    return {
        "mrr": mrr,
        "total_revenue": mrr * 12,  # Annualized estimate
        "coaching_revenue": coaching_revenue,
        "churn_rate": round(churn_rate, 4),
        "trial_conversion_rate": round(conversion_rate, 4),
        "active_paid": active_paid,
        "trial_count": trial_count,
        "cancelled_count": cancelled_count,
        "conversions": conversions,
    }


@router.get("/billing/subscriptions")
async def get_subscription_analytics(request: Request):
    """Subscription analytics: counts by tier, subscriber list."""
    registry = await _load_registry_async(request)

    by_tier: Dict[str, Dict[str, Any]] = {}
    subscribers = []
    active_count = 0
    trial_count = 0

    for _key, entry in registry.items():
        profile = entry.get("profile", {})
        plan = (profile.get("subscription_plan") or "TRIAL").upper()
        status = (profile.get("subscription_status") or "").upper()
        role = (profile.get("role") or "").upper()

        if role == "COACH":
            continue  # Only count clients

        price = PLAN_PRICES.get(plan, 0)

        if plan not in by_tier:
            by_tier[plan] = {"count": 0, "revenue": 0}
        by_tier[plan]["count"] += 1
        if status in ("ACTIVE", "TRIAL_ACTIVE", ""):
            by_tier[plan]["revenue"] += price

        if plan in PLAN_PRICES and status in ("ACTIVE",):
            active_count += 1
        if plan in ("TRIAL", "THRESHOLD"):
            trial_count += 1

        subscribers.append({
            "id": _key,
            "hardware_id": profile.get("hardware_id", ""),
            "name": profile.get("name") or profile.get("display_name") or "",
            "email": profile.get("email", ""),
            "subscription_plan": plan,
            "subscription_status": status,
            "created_at": profile.get("created_at") or profile.get("trial_start_date", ""),
        })

    return {
        "by_tier": by_tier,
        "active_count": active_count,
        "trial_count": trial_count,
        "total_subscribers": len(subscribers),
        "subscribers": subscribers,
    }


@router.get("/billing/failed-payments")
async def get_failed_payments(request: Request):
    """List failed payment attempts."""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: check payment_history table for failed payments
    pg_failed = []
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, username, amount, type, status, description, created_at
                       FROM payment_history
                       WHERE status = 'failed' OR type = 'payment_failed'
                       ORDER BY created_at DESC LIMIT 50"""
                )
                for r in rows:
                    pg_failed.append({
                        "id": str(r["id"]),
                        "user_id": r.get("username") or "",
                        "user_name": "",
                        "amount": float(r["amount"]) / 100 if r.get("amount") else 0,
                        "failure_reason": r.get("description") or "Unknown",
                        "created_at": r["created_at"].isoformat() if r.get("created_at") else "",
                    })
        except Exception as e:
            logger.warning("get_failed_payments: PG read failed: %s", e)

    billing = load_json(DATA_DIR / "billing.json")
    failed = [
        t for t in billing.get("transactions", [])
        if t.get("status") == "failed" or t.get("type") == "payment_failed"
    ]

    # Also check Stripe if available
    stripe_failed = []
    if _STRIPE_AVAILABLE:
        try:
            charges = _stripe.Charge.list(limit=50)
            for ch in charges.auto_paging_iter():
                if ch.status == "failed":
                    stripe_failed.append({
                        "id": ch.id,
                        "user_id": ch.metadata.get("user_id", ""),
                        "user_name": ch.metadata.get("user_name", ch.billing_details.name or ""),
                        "amount": ch.amount / 100,
                        "failure_reason": ch.failure_message or ch.outcome.get("reason", "Unknown") if ch.outcome else "Unknown",
                        "created_at": datetime.fromtimestamp(ch.created).isoformat(),
                    })
                if len(stripe_failed) >= 50:
                    break
        except Exception as e:
            logger.warning("get_failed_payments: Stripe query failed: %s", e)

    combined = pg_failed + stripe_failed + [
        {
            "id": f.get("id", ""),
            "user_id": f.get("user_id", ""),
            "user_name": f.get("user_name", ""),
            "amount": f.get("amount", 0),
            "failure_reason": f.get("reason", "Unknown"),
            "created_at": f.get("timestamp", ""),
        }
        for f in failed
    ]

    return {"payments": combined, "count": len(combined)}


@router.post("/billing/refund")
async def process_refund(req: RefundRequest, request: Request):
    """Process a refund via Stripe or local billing."""
    pool = getattr(request.app.state, "db_pool", None)

    # PG-first: find user
    user_name = ""
    stripe_customer = None
    if pool:
        try:
            user_profile = await find_user_pg(pool, req.user_id)
            if user_profile:
                user_name = user_profile.get("name", "")
                stripe_customer = user_profile.get("stripe_customer_id")
        except Exception as e:
            logger.warning("process_refund: PG user lookup failed: %s", e)

    if not user_name:
        registry = await _load_registry_async(request)
        for _k, entry in registry.items():
            p = entry.get("profile", {})
            if p.get("hardware_id") == req.user_id:
                user_name = p.get("name", "")
                stripe_customer = p.get("stripe_customer_id")
                break

    billing = load_json(DATA_DIR / "billing.json")

    refund_record = {
        "id": f"refund_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "user_id": req.user_id,
        "user_name": user_name,
        "amount": req.amount,
        "reason": req.reason,
        "type": "refund",
        "timestamp": str(datetime.now()),
        "stripe_refund": False,
    }

    # Try Stripe refund
    if _STRIPE_AVAILABLE and stripe_customer:
        try:
            # Find the most recent charge for this customer
            charges = _stripe.Charge.list(customer=stripe_customer, limit=1)
            if charges.data:
                _stripe.Refund.create(
                    charge=charges.data[0].id,
                    amount=int(req.amount * 100),
                    reason="requested_by_customer",
                )
                refund_record["stripe_refund"] = True
        except Exception as e:
            refund_record["stripe_error"] = str(e)

    # PG-first: write refund to payment_history
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO payment_history
                       (username, amount, currency, status, description, metadata, created_at)
                       VALUES ($1, $2, 'usd', 'refunded', $3, $4::jsonb, NOW())""",
                    req.user_id,
                    int(req.amount * 100),
                    f"Admin refund: {req.reason}",
                    json.dumps(refund_record, default=str),
                )
        except Exception as e:
            logger.warning("process_refund: PG write failed: %s", e)

    # JSON backup
    billing.setdefault("transactions", []).append(refund_record)
    save_json(DATA_DIR / "billing.json", billing)

    # PG-first audit log, then JSON backup
    await _audit_log_append_pg(pool, "ADMIN_REFUND", user_id=req.user_id,
                                description=f"Refund ${req.amount} for {user_name}. Reason: {req.reason}")

    return {"status": "refunded", "refund": refund_record}


@router.post("/billing/override-plan")
async def override_user_plan(req: OverridePlanRequest, request: Request):
    """Manually set a user's subscription plan. Audit-logged."""
    valid_plans = ("COACH_ONLY", "TRIAL", "STANDARD", "TOP_TIER")
    if req.new_plan not in valid_plans:
        raise HTTPException(400, f"Invalid plan. Must be one of: {valid_plans}")

    pool = getattr(request.app.state, "db_pool", None)
    token_map = {"COACH_ONLY": 0, "TRIAL": 10000, "STANDARD": 50000, "TOP_TIER": 200000}
    new_status = "ACTIVE" if req.new_plan not in ("TRIAL",) else "TRIAL_ACTIVE"
    found = False
    old_plan = ""

    # PG-first: update tier directly
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT tier, profile_data FROM users WHERE hardware_id = $1 AND deleted_at IS NULL",
                    req.user_id,
                )
                if row:
                    pd = row["profile_data"] or {}
                    if isinstance(pd, str):
                        pd = json.loads(pd)
                    old_plan = row["tier"] or pd.get("subscription_plan", "TRIAL")
                    plan_data = json.dumps({
                        "subscription_plan": req.new_plan,
                        "token_balance": token_map.get(req.new_plan, 0),
                    })
                    await conn.execute(
                        """UPDATE users SET tier = $1, subscription_status = $2,
                           token_balance = $3, profile_data = profile_data || $4::jsonb,
                           updated_at = NOW()
                           WHERE hardware_id = $5""",
                        req.new_plan, new_status, token_map.get(req.new_plan, 0),
                        plan_data, req.user_id,
                    )
                    found = True
        except Exception as e:
            logger.warning("override_user_plan: PG update failed, falling back to JSON: %s", e)

    if not found:
        registry = await _load_registry_async(request)
        for _k, entry in registry.items():
            p = entry.get("profile", {})
            if p.get("hardware_id") == req.user_id:
                old_plan = p.get("subscription_plan", "TRIAL")
                p["subscription_plan"] = req.new_plan
                p["subscription_status"] = new_status
                p["token_balance"] = token_map.get(req.new_plan, 0)
                found = True
                break
        if not found:
            raise HTTPException(404, "User not found")
        await _save_registry_async(registry, request)

    # PG-first audit log
    if pool:
        await _audit_log_append_pg(pool, "MODIFY", user_id=req.user_id,
                                    description=f"Plan override: {old_plan} -> {req.new_plan}. Note: {req.admin_note}")
    else:
        _audit_log_append("ADMIN_PLAN_OVERRIDE", user_id=req.user_id, old_plan=old_plan,
                          new_plan=req.new_plan, admin_note=req.admin_note)

    return {
        "status": "overridden",
        "user_id": req.user_id,
        "old_plan": old_plan,
        "new_plan": req.new_plan,
    }


@router.post("/billing/coupon")
async def create_coupon_legacy(req: CouponRequest, request: Request):
    """Legacy coupon endpoint — prefer /discounts/promo instead."""
    billing = load_json(DATA_DIR / "billing.json")  # billing.json used as backup only here
    coupon_record = {
        "code": req.code, "discount": req.discount, "type": req.type,
        "created_at": str(datetime.now()), "active": True, "stripe_coupon": False,
    }
    if _STRIPE_AVAILABLE:
        try:
            kwargs: Dict[str, Any] = {"id": req.code, "duration": "once"}
            if req.type == "percent":
                kwargs["percent_off"] = req.discount
            else:
                kwargs["amount_off"] = int(req.discount * 100)
                kwargs["currency"] = "usd"
            _stripe.Coupon.create(**kwargs)
            coupon_record["stripe_coupon"] = True
        except Exception as e:
            coupon_record["stripe_error"] = str(e)
    # PG-first: log coupon creation to payment_history
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO payment_history
                       (username, amount, currency, status, description, metadata, created_at)
                       VALUES ($1, $2, 'usd', 'coupon_created', $3, $4::jsonb, NOW())""",
                    "system", 0,
                    f"Coupon {req.code}: {req.discount} {req.type}",
                    json.dumps(coupon_record, default=str),
                )
        except Exception as e:
            logger.warning("create_coupon_legacy: PG write failed: %s", e)

    # JSON backup
    billing.setdefault("coupons", []).append(coupon_record)
    save_json(DATA_DIR / "billing.json", billing)
    return {"status": "created", "coupon": coupon_record}


# =============================================================================
# DISCOUNT MANAGEMENT — Promo Codes, School Codes, Corporate Sponsors
# =============================================================================


def _validate_admin_code(code: str) -> str:
    """Validate and normalize a discount code for admin creation."""
    cleaned = code.strip().upper()[:40]
    if not _ADMIN_CODE_PATTERN.match(cleaned):
        raise HTTPException(400, "Code must be 2-40 alphanumeric characters (A-Z, 0-9, _, -)")
    return cleaned


def _create_stripe_coupon(code: str, discount_type: str, discount_value: int,
                          duration: str = "once", duration_in_months: int = None,
                          max_redemptions: int = None, name: str = None):
    """Create a Stripe coupon + promotion code. Returns (coupon_id, promo_id, error)."""
    if not _STRIPE_AVAILABLE:
        return None, None, "Stripe not configured"
    try:
        kwargs: Dict[str, Any] = {"id": code, "duration": duration}
        if name:
            kwargs["name"] = name[:40]
        if discount_type == "percent":
            kwargs["percent_off"] = max(1, min(discount_value, 100))
        else:
            kwargs["amount_off"] = max(1, discount_value)
            kwargs["currency"] = "usd"
        if duration == "repeating" and duration_in_months:
            kwargs["duration_in_months"] = max(1, min(duration_in_months, 36))
        if max_redemptions:
            kwargs["max_redemptions"] = max(1, max_redemptions)
        try:
            coupon = _stripe.Coupon.create(**kwargs)
        except Exception as ce:
            if "already exists" in str(ce).lower():
                coupon = _stripe.Coupon.retrieve(code)
                logger.info("Reusing existing Stripe coupon %s", code)
            else:
                raise
        promo_kwargs = {"coupon": coupon.id, "code": code, "active": True}
        if max_redemptions:
            promo_kwargs["max_redemptions"] = max(1, max_redemptions)
        try:
            promo = _stripe.PromotionCode.create(**promo_kwargs)
        except Exception as pe:
            if "already been used" in str(pe).lower() or "already exists" in str(pe).lower():
                logger.info("Stripe promotion code %s already exists, using coupon ID", code)
                return coupon.id, None, None
            raise
        return coupon.id, promo.id, None
    except Exception as e:
        logger.warning("Stripe coupon creation failed for %s: %s", code, e)
        safe_msg = "Stripe sync failed"
        err_str = str(e).lower()
        if "already exists" in err_str:
            safe_msg = "Coupon code already exists in Stripe"
        elif "invalid" in err_str:
            safe_msg = "Invalid coupon parameters"
        return None, None, safe_msg


# ---- Promotional Specials (Promo Codes) ----

@router.get("/discounts/status")
async def discount_system_status(request: Request):
    """Overview of discount system: Stripe connection, table counts, plan pricing."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        promo_count = await conn.fetchval(
            "SELECT COUNT(*) FROM promotional_specials") or 0
        promo_active = await conn.fetchval(
            "SELECT COUNT(*) FROM promotional_specials WHERE active = true") or 0
        promo_stripe_synced = await conn.fetchval(
            "SELECT COUNT(*) FROM promotional_specials WHERE stripe_coupon_id IS NOT NULL AND stripe_coupon_id != ''") or 0
        school_count = await conn.fetchval(
            "SELECT COUNT(*) FROM school_codes") or 0
        school_active = await conn.fetchval(
            "SELECT COUNT(*) FROM school_codes WHERE active = true") or 0
        corp_count = await conn.fetchval(
            "SELECT COUNT(*) FROM corporate_sponsors") or 0
        corp_active = await conn.fetchval(
            "SELECT COUNT(*) FROM corporate_sponsors WHERE active = true") or 0
        corp_stripe_synced = await conn.fetchval(
            "SELECT COUNT(*) FROM corporate_sponsors WHERE stripe_coupon_id IS NOT NULL AND stripe_coupon_id != ''") or 0
        total_employees_sponsored = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE company_id IS NOT NULL") or 0

    return {
        "stripe_connected": _STRIPE_AVAILABLE,
        "plan_pricing": {k: f"${v}/mo" for k, v in PLAN_PRICES.items()},
        "tier_labels": PLAN_LABELS,
        "tier_features": TIER_FEATURES,
        "promo_codes": {"total": promo_count, "active": promo_active, "stripe_synced": promo_stripe_synced},
        "school_codes": {"total": school_count, "active": school_active},
        "corporate_sponsors": {"total": corp_count, "active": corp_active, "stripe_synced": corp_stripe_synced,
                               "total_employees": total_employees_sponsored},
    }


@router.post("/discounts/promo")
async def create_promo_code(req: CreatePromoRequest, request: Request):
    """Create a promo code in DB and Stripe."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    if req.discount_type not in _VALID_DISCOUNT_TYPES:
        raise HTTPException(400, "discount_type must be 'percent' or 'amount'")
    if req.discount_type == "percent" and not (1 <= req.discount_value <= 100):
        raise HTTPException(400, "Percent discount must be 1-100")
    if req.discount_type == "amount" and req.discount_value < 1:
        raise HTTPException(400, "Amount discount must be at least 1 cent")
    if req.duration not in _VALID_DURATIONS:
        raise HTTPException(400, "duration must be 'once', 'repeating', or 'forever'")
    if req.duration == "repeating" and not req.duration_in_months:
        raise HTTPException(400, "duration_in_months required when duration is 'repeating'")
    if req.discount_type == "percent" and req.discount_value == 100:
        if not req.max_redemptions:
            raise HTTPException(400, "100% promo codes require max_redemptions")
        if not req.ends_at:
            raise HTTPException(400, "100% promo codes require ends_at")
    for tier in req.applicable_tiers:
        if tier not in _VALID_TIERS:
            raise HTTPException(400, f"Invalid tier: {tier}")

    safe_code = _validate_admin_code(req.code)
    coach_id = req.coach_id.strip()[:128] if req.coach_id else None
    starts_dt = datetime.now(timezone.utc)
    if req.starts_at:
        try:
            starts_dt = datetime.fromisoformat(req.starts_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            starts_dt = datetime.now(timezone.utc)
    try:
        ends_dt = datetime.fromisoformat(req.ends_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid ends_at datetime format")
    coupon_id, promo_id, stripe_err = _create_stripe_coupon(
        code=safe_code,
        discount_type=req.discount_type,
        discount_value=req.discount_value,
        duration=req.duration,
        duration_in_months=req.duration_in_months,
        max_redemptions=req.max_redemptions,
        name=req.name[:200],
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO promotional_specials
                (name, discount_type, discount_value, coach_id, applicable_tiers,
                 starts_at, ends_at, promo_code, max_redemptions,
                 stripe_coupon_id, duration, duration_in_months, active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, TRUE)
            RETURNING id, name, promo_code, discount_type, discount_value,
                      coach_id,
                      starts_at, ends_at, max_redemptions, current_redemptions,
                      stripe_coupon_id, duration, duration_in_months, active, created_at
        """, req.name[:200], req.discount_type, req.discount_value, coach_id,
             req.applicable_tiers or [],
             starts_dt, ends_dt,
             safe_code, req.max_redemptions, coupon_id,
             req.duration, req.duration_in_months)

    result = {
        "id": str(row["id"]),
        "name": row["name"],
        "promo_code": row["promo_code"],
        "discount_type": row["discount_type"],
        "discount_value": row["discount_value"],
        "coach_id": row["coach_id"],
        "starts_at": row["starts_at"].isoformat() if row["starts_at"] else None,
        "ends_at": row["ends_at"].isoformat() if row["ends_at"] else None,
        "max_redemptions": row["max_redemptions"],
        "current_redemptions": row["current_redemptions"],
        "stripe_coupon_id": row["stripe_coupon_id"],
        "stripe_synced": coupon_id is not None,
        "duration": row["duration"],
        "duration_in_months": row["duration_in_months"],
        "active": row["active"],
    }
    if stripe_err:
        result["stripe_error"] = stripe_err
    return {"status": "created", "promo": result}


@router.get("/discounts/promos")
async def list_promo_codes(request: Request, coach_id: Optional[str] = None):
    """List all promo codes (active and expired)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"promos": []}
    coach_filter = coach_id.strip()[:128] if coach_id else None
    _cols = """id, name, discount_type, discount_value, coach_id, applicable_tiers,
               starts_at, ends_at, promo_code, max_redemptions, current_redemptions,
               stripe_coupon_id, duration, duration_in_months, active, created_at"""
    async with pool.acquire() as conn:
        if coach_filter:
            rows = await conn.fetch(f"""
                SELECT {_cols}
                FROM promotional_specials
                WHERE coach_id = $1
                ORDER BY created_at DESC
            """, coach_filter)
        else:
            rows = await conn.fetch(f"""
                SELECT {_cols}
                FROM promotional_specials ORDER BY created_at DESC
            """)

    def _dur(r):
        d = r["duration"] or "once"
        if d == "repeating" and r["duration_in_months"]:
            return f"repeating ({r['duration_in_months']} mo)"
        return d

    return {"promos": [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "promo_code": r["promo_code"],
            "discount_type": r["discount_type"],
            "discount_value": r["discount_value"],
            "coach_id": r["coach_id"],
            "applicable_tiers": r["applicable_tiers"] or [],
            "starts_at": r["starts_at"].isoformat() if r["starts_at"] else None,
            "ends_at": r["ends_at"].isoformat() if r["ends_at"] else None,
            "max_redemptions": r["max_redemptions"],
            "current_redemptions": r["current_redemptions"],
            "stripe_coupon_id": r["stripe_coupon_id"],
            "stripe_synced": bool(r["stripe_coupon_id"]),
            "duration": _dur(r),
            "duration_in_months": r["duration_in_months"],
            "active": r["active"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]}


@router.patch("/discounts/promo/{promo_id}")
async def toggle_promo_code(promo_id: str, request: Request):
    """Toggle a promo code active/inactive. Deactivates Stripe promotion code too."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active, stripe_coupon_id FROM promotional_specials WHERE id = $1::uuid",
            promo_id)
        if not row:
            raise HTTPException(404, "Promo code not found")
        new_active = not row["active"]
        await conn.execute(
            "UPDATE promotional_specials SET active = $1 WHERE id = $2::uuid",
            new_active, promo_id)

    if _STRIPE_AVAILABLE and row["stripe_coupon_id"]:
        try:
            promos = _stripe.PromotionCode.list(coupon=row["stripe_coupon_id"], limit=10)
            for p in promos.auto_paging_iter():
                _stripe.PromotionCode.modify(p.id, active=new_active)
        except Exception as e:
            logger.warning("Failed to toggle Stripe promo for %s: %s", promo_id, e)

    return {"status": "toggled", "id": promo_id, "active": new_active}


# ---- School Codes ----

@router.post("/discounts/school")
async def create_school_code(req: CreateSchoolCodeRequest, request: Request):
    """Create a school discount code in DB and Stripe."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    code_upper = _validate_admin_code(req.school_code)
    coupon_id, _, stripe_err = _create_stripe_coupon(
        code=f"SCHOOL_{code_upper}",
        discount_type="percent",
        discount_value=req.discount_percent,
        duration="repeating",
        duration_in_months=12,
        name=f"School: {req.school_name}",
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO school_codes
                (school_name, school_code, discount_percent, max_students, stripe_coupon_id, active)
            VALUES ($1, $2, $3, $4, $5, TRUE)
            RETURNING id, school_name, school_code, discount_percent,
                      max_students, current_students, stripe_coupon_id, active, created_at
        """, req.school_name[:200], code_upper, req.discount_percent,
             req.max_students, coupon_id)

    result = {
        "id": str(row["id"]),
        "school_name": row["school_name"],
        "school_code": row["school_code"],
        "discount_percent": row["discount_percent"],
        "max_students": row["max_students"],
        "current_students": row["current_students"],
        "stripe_coupon_id": row["stripe_coupon_id"],
        "stripe_synced": coupon_id is not None,
        "active": row["active"],
    }
    if stripe_err:
        result["stripe_error"] = stripe_err
    return {"status": "created", "school": result}


@router.get("/discounts/schools")
async def list_school_codes(request: Request):
    """List all school discount codes."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"schools": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, school_name, school_code, discount_percent,
                   max_students, current_students, stripe_coupon_id, active, created_at
            FROM school_codes ORDER BY created_at DESC
        """)
    return {"schools": [
        {
            "id": str(r["id"]),
            "school_name": r["school_name"],
            "school_code": r["school_code"],
            "discount_percent": r["discount_percent"],
            "max_students": r["max_students"],
            "current_students": r["current_students"],
            "stripe_coupon_id": r["stripe_coupon_id"],
            "stripe_synced": bool(r["stripe_coupon_id"]),
            "active": r["active"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]}


@router.patch("/discounts/school/{school_id}")
async def toggle_school_code(school_id: str, request: Request):
    """Toggle a school code active/inactive."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active FROM school_codes WHERE id = $1::uuid", school_id)
        if not row:
            raise HTTPException(404, "School code not found")
        new_active = not row["active"]
        await conn.execute(
            "UPDATE school_codes SET active = $1 WHERE id = $2::uuid",
            new_active, school_id)
    return {"status": "toggled", "id": school_id, "active": new_active}


# ---- Corporate Sponsors ----

@router.post("/discounts/corporate")
async def create_corporate_sponsor(req: CreateCorporateRequest, request: Request):
    """Create a corporate sponsor in DB and Stripe."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    if req.discount_type not in {"percent", "amount", "full"}:
        raise HTTPException(400, "discount_type must be 'percent', 'amount', or 'full'")
    if req.discount_type == "percent" and req.discount_value > 100:
        raise HTTPException(400, "Percent discount cannot exceed 100")
    if not req.pays_full and req.discount_value <= 0:
        raise HTTPException(
            400,
            "Enter a discount amount/percent greater than zero, or enable company pays full subscription.",
        )

    code_upper = _validate_admin_code(req.sponsor_code)
    coupon_id = None
    stripe_err = None

    if req.pays_full:
        coupon_id, _, stripe_err = _create_stripe_coupon(
            code=f"CORP_{code_upper}",
            discount_type="percent",
            discount_value=100,
            duration="repeating",
            duration_in_months=12,
            name=f"Corporate: {req.company_name} (Full)",
        )
    elif req.discount_value > 0:
        coupon_id, _, stripe_err = _create_stripe_coupon(
            code=f"CORP_{code_upper}",
            discount_type=req.discount_type,
            discount_value=req.discount_value,
            duration="repeating",
            duration_in_months=12,
            name=f"Corporate: {req.company_name}",
        )

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO corporate_sponsors
                (company_name, sponsor_code, discount_type, discount_value,
                 pays_full, max_employees, billing_contact_email, stripe_coupon_id, active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE)
            RETURNING id, company_name, sponsor_code, discount_type, discount_value,
                      pays_full, max_employees, current_employees,
                      billing_contact_email, stripe_coupon_id, active, created_at
        """, req.company_name[:200], code_upper, req.discount_type, req.discount_value,
             req.pays_full, req.max_employees,
             req.billing_contact_email[:255] if req.billing_contact_email else None,
             coupon_id)

    result = {
        "id": str(row["id"]),
        "company_name": row["company_name"],
        "sponsor_code": row["sponsor_code"],
        "discount_type": row["discount_type"],
        "discount_value": row["discount_value"],
        "pays_full": row["pays_full"],
        "max_employees": row["max_employees"],
        "current_employees": row["current_employees"],
        "billing_contact_email": row["billing_contact_email"],
        "stripe_coupon_id": row["stripe_coupon_id"],
        "stripe_synced": coupon_id is not None,
        "active": row["active"],
    }
    if stripe_err:
        result["stripe_error"] = stripe_err
    return {"status": "created", "corporate": result}


@router.get("/discounts/corporates")
async def list_corporate_sponsors(request: Request):
    """List all corporate sponsors."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"corporates": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, company_name, sponsor_code, discount_type, discount_value,
                   pays_full, max_employees, current_employees,
                   billing_contact_email, stripe_coupon_id, active, created_at
            FROM corporate_sponsors ORDER BY created_at DESC
        """)
    return {"corporates": [
        {
            "id": str(r["id"]),
            "company_name": r["company_name"],
            "sponsor_code": r["sponsor_code"],
            "discount_type": r["discount_type"],
            "discount_value": r["discount_value"],
            "pays_full": r["pays_full"],
            "max_employees": r["max_employees"],
            "current_employees": r["current_employees"],
            "billing_contact_email": r["billing_contact_email"],
            "stripe_coupon_id": r["stripe_coupon_id"],
            "stripe_synced": bool(r["stripe_coupon_id"]),
            "active": r["active"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]}


@router.patch("/discounts/corporate/{corp_id}")
async def toggle_corporate_sponsor(corp_id: str, request: Request):
    """Toggle a corporate sponsor active/inactive."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active FROM corporate_sponsors WHERE id = $1::uuid", corp_id)
        if not row:
            raise HTTPException(404, "Corporate sponsor not found")
        new_active = not row["active"]
        await conn.execute(
            "UPDATE corporate_sponsors SET active = $1 WHERE id = $2::uuid",
            new_active, corp_id)
    return {"status": "toggled", "id": corp_id, "active": new_active}


@router.post("/discounts/corporate/{corp_id}/sync-stripe")
async def sync_corporate_to_stripe(corp_id: str, request: Request):
    """Sync an existing corporate sponsor to Stripe (create coupon if missing)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT sponsor_code, company_name, discount_type, discount_value,
                      pays_full, stripe_coupon_id, max_employees
               FROM corporate_sponsors WHERE id = $1::uuid""", corp_id)
        if not row:
            raise HTTPException(404, "Corporate sponsor not found")
        if row["stripe_coupon_id"]:
            return {"status": "already_synced", "stripe_coupon_id": row["stripe_coupon_id"]}
        dv = row["discount_value"] or 0
        if not row["pays_full"] and dv <= 0:
            raise HTTPException(400, "Cannot sync a 0% discount to Stripe — set discount_value first")
        if row["pays_full"]:
            coupon_id, _, stripe_err = _create_stripe_coupon(
                code=f"CORP_{row['sponsor_code']}",
                discount_type="percent", discount_value=100,
                duration="repeating", duration_in_months=12,
                name=f"Corporate: {row['company_name']} (Full)")
        else:
            coupon_id, _, stripe_err = _create_stripe_coupon(
                code=f"CORP_{row['sponsor_code']}",
                discount_type=row["discount_type"], discount_value=dv,
                duration="repeating", duration_in_months=12,
                name=f"Corporate: {row['company_name']}")
        if not coupon_id:
            raise HTTPException(502, f"Stripe sync failed: {stripe_err}")
        await conn.execute(
            "UPDATE corporate_sponsors SET stripe_coupon_id = $1 WHERE id = $2::uuid",
            coupon_id, corp_id)
    return {"status": "synced", "stripe_coupon_id": coupon_id}


@router.post("/discounts/school/{school_id}/sync-stripe")
async def sync_school_to_stripe(school_id: str, request: Request):
    """Sync an existing school code to Stripe (create coupon if missing)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT school_code, school_name, discount_percent, stripe_coupon_id
               FROM school_codes WHERE id = $1::uuid""", school_id)
        if not row:
            raise HTTPException(404, "School code not found")
        if row["stripe_coupon_id"]:
            return {"status": "already_synced", "stripe_coupon_id": row["stripe_coupon_id"]}
        coupon_id, _, stripe_err = _create_stripe_coupon(
            code=f"SCHOOL_{row['school_code']}",
            discount_type="percent", discount_value=row["discount_percent"],
            duration="repeating", duration_in_months=12,
            name=f"School: {row['school_name']}")
        if not coupon_id:
            raise HTTPException(502, f"Stripe sync failed: {stripe_err}")
        await conn.execute(
            "UPDATE school_codes SET stripe_coupon_id = $1 WHERE id = $2::uuid",
            coupon_id, school_id)
    return {"status": "synced", "stripe_coupon_id": coupon_id}


@router.post("/discounts/promo/{promo_id}/sync-stripe")
async def sync_promo_to_stripe(promo_id: str, request: Request):
    """Sync an existing promo code to Stripe (create coupon if missing)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT promo_code, name, discount_type, discount_value,
                      max_redemptions, stripe_coupon_id, duration, duration_in_months
               FROM promotional_specials WHERE id = $1::uuid""", promo_id)
        if not row:
            raise HTTPException(404, "Promo code not found")
        if row["stripe_coupon_id"]:
            return {"status": "already_synced", "stripe_coupon_id": row["stripe_coupon_id"]}
        coupon_id, _, stripe_err = _create_stripe_coupon(
            code=row["promo_code"],
            discount_type=row["discount_type"],
            discount_value=row["discount_value"],
            duration=row["duration"] or "once",
            duration_in_months=row["duration_in_months"],
            max_redemptions=row["max_redemptions"],
            name=row["name"][:200] if row["name"] else None)
        if not coupon_id:
            raise HTTPException(502, f"Stripe sync failed: {stripe_err}")
        await conn.execute(
            "UPDATE promotional_specials SET stripe_coupon_id = $1 WHERE id = $2::uuid",
            coupon_id, promo_id)
    return {"status": "synced", "stripe_coupon_id": coupon_id}


@router.post("/billing/retry-payment")
async def retry_payment(req: RetryPaymentRequest):
    """Retry a failed Stripe payment."""
    if not _STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe is not configured")

    try:
        # If it's an invoice, retry collection
        if req.payment_id.startswith("in_"):
            invoice = _stripe.Invoice.retrieve(req.payment_id)
            _stripe.Invoice.pay(invoice.id)
            return {"status": "retried", "payment_id": req.payment_id}

        # If it's a payment intent, confirm
        if req.payment_id.startswith("pi_"):
            pi = _stripe.PaymentIntent.retrieve(req.payment_id)
            _stripe.PaymentIntent.confirm(pi.id)
            return {"status": "retried", "payment_id": req.payment_id}

        raise HTTPException(400, "Unsupported payment ID format")
    except Exception as e:
        raise HTTPException(400, f"Retry failed: {e}")


# =============================================================================
# ADMIN SETTINGS — Persistent configuration (Deadman Switch, Retention, etc.)
# =============================================================================

SETTINGS_FILE = DATA_DIR / "admin_settings.json"

VALID_SETTINGS = {
    "deadman_silence_threshold_days": {"type": int, "min": 1, "max": 7, "default": 3},
    "memory_retention_policy": {"type": str, "values": ["forever", "1_year", "6_months"], "default": "forever"},
}


@router.get("/settings")
async def get_admin_settings():
    """Get all admin-configurable settings."""
    saved = load_json(SETTINGS_FILE, {})
    result = {}
    for key, schema in VALID_SETTINGS.items():
        result[key] = saved.get(key, schema["default"])
    return {"settings": result}


@router.post("/settings")
async def update_admin_setting(req: UpdateSettingsRequest):
    """Update a single admin setting. Audit-logged."""
    if req.key not in VALID_SETTINGS:
        raise HTTPException(400, f"Unknown setting: {req.key}. Valid keys: {list(VALID_SETTINGS.keys())}")

    schema = VALID_SETTINGS[req.key]
    if schema["type"] == int:
        try:
            val = int(req.value)
        except (ValueError, TypeError):
            raise HTTPException(400, f"Setting {req.key} must be an integer")
        if val < schema.get("min", 0) or val > schema.get("max", 999):
            raise HTTPException(400, f"Value out of range [{schema['min']}, {schema['max']}]")
    elif schema["type"] == str:
        val = str(req.value)
        if "values" in schema and val not in schema["values"]:
            raise HTTPException(400, f"Invalid value. Allowed: {schema['values']}")
    else:
        val = req.value

    saved = load_json(SETTINGS_FILE, {})
    old_value = saved.get(req.key, schema["default"])
    saved[req.key] = val
    save_json(SETTINGS_FILE, saved)

    _audit_log_append("ADMIN_SETTING_CHANGED", key=req.key, old_value=old_value, new_value=val)
    return {"status": "updated", "key": req.key, "value": val}


# =============================================================================
# EMERGENCY PURGE — Crisis data purge for a specific user
# =============================================================================


class UpdateSettingsRequest(BaseModel):
    key: str
    value: Any


class EmergencyPurgeRequest(BaseModel):
    user_id: str
    reason: str
    purge_conversations: bool = True
    purge_metrics: bool = True
    purge_sessions: bool = True
    purge_biometrics: bool = True


@router.post("/emergency-purge")
async def emergency_purge(req: EmergencyPurgeRequest, request: Request):
    """
    Emergency data purge for a user — removes selected data categories.
    More granular than wipe-memory. Audit-logged. IRREVERSIBLE.
    """
    pool = getattr(request.app.state, "db_pool", None)

    found = False
    hw_id = ""
    user_name = ""

    # PG-first: find user
    if pool:
        try:
            user_profile = await find_user_pg(pool, req.user_id)
            if user_profile:
                hw_id = user_profile.get("hardware_id", req.user_id)
                user_name = user_profile.get("name", "")
                found = True
        except Exception as e:
            logger.warning("emergency_purge: PG user lookup failed: %s", e)

    if not found:
        registry = load_json(DATA_DIR / "user_registry.json")
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("hardware_id") == req.user_id or k == req.user_id:
                hw_id = p.get("hardware_id", req.user_id)
                user_name = p.get("name", "")
                found = True
                break

    if not found:
        raise HTTPException(404, "User not found")

    purged = []
    vault_dir = VAULT_ROOT / "Clients" / hw_id

    if req.purge_conversations:
        memory_file = vault_dir / "memory.json"
        if memory_file.exists():
            save_json(memory_file, [])
            purged.append("conversations")

    if req.purge_metrics:
        metrics_file = vault_dir / "metrics.json"
        if metrics_file.exists():
            metrics = load_json(metrics_file, {})
            metrics["history"] = []
            save_json(metrics_file, metrics)
            purged.append("metrics_history")

    if req.purge_sessions:
        if vault_dir.exists():
            for f in vault_dir.glob("session_*.json"):
                save_json(f, {})
                purged.append(f"session:{f.stem}")

    if req.purge_biometrics:
        metrics_file = vault_dir / "metrics.json"
        if metrics_file.exists():
            metrics = load_json(metrics_file, {})
            ns = metrics.get("nevedal_state", {})
            for field in ["voice_baseline", "voice_signature", "pitch_baseline", "energy_baseline",
                           "speech_rate_baseline", "pause_ratio_baseline", "baseline_established",
                           "biometric_enrolled"]:
                ns.pop(field, None)
            metrics["nevedal_state"] = ns
            save_json(metrics_file, metrics)
            purged.append("biometrics")

    _audit_log_append(
        "ADMIN_EMERGENCY_PURGE",
        user_id=req.user_id,
        user_name=user_name,
        reason=req.reason,
        purged=purged,
    )

    return {
        "status": "purged",
        "user_id": req.user_id,
        "purged": purged,
        "message": f"Emergency purge complete for {user_name or req.user_id}. {len(purged)} data categories cleared.",
    }


# =============================================================================
# TEST: Admin Alert Protocol (SMS + Email)
# =============================================================================

@router.post("/test-alert")
async def test_admin_alert():
    """Fire a test SMS + email alert to the admin via the Defense Shield."""
    from app.services.security.admin_contact_shield import get_shield
    shield = get_shield()

    if not shield._alert_phone and not shield._alert_emails:
        return {
            "status": "error",
            "message": "No ADMIN_ALERT_PHONE or ADMIN_ALERT_EMAILS configured in .env",
        }

    results = {"sms": "skipped", "email": "skipped"}

    # Ensure notification system is wired
    if not shield._notification_system:
        try:
            from app.websocket.bridge_server import notification_system as ns
            shield.set_notification_system(ns)
        except Exception as e:
            logger.warning("test_defense_alert: notification_system import failed: %s", e)

    if shield._alert_phone:
        try:
            ns = shield._notification_system
            if ns and ns.twilio_enabled:
                sms_body = "[SANCTUARY DEFENSE] Test Alert\nThis is a test of the admin alert protocol. If you received this, SMS alerts are working."
                sent = await ns.send_sms(shield._alert_phone, sms_body)
                results["sms"] = "sent" if sent else "failed"
                results["sms_to"] = shield._alert_phone
            else:
                results["sms"] = "twilio_disabled"
        except Exception as e:
            results["sms"] = f"error: {e}"

    for email in shield._alert_emails:
        try:
            ns = shield._notification_system
            if ns:
                await ns._send_email(
                    to_email=email,
                    subject="[SANCTUARY DEFENSE] Test Alert",
                    content="""
                    <div style="font-family: 'DM Sans', sans-serif; background: #050505; color: #E8D5A3; padding: 24px;">
                        <h2 style="color: #C9A962; margin-top: 0;">Defense Alert — TEST</h2>
                        <p style="font-size: 18px; font-weight: bold;">This is a test of the admin alert protocol.</p>
                        <p style="color: #ccc;">If you received this email, the defense alert system (email) is working correctly.</p>
                        <hr style="border-color: #333;">
                        <p style="color: #666; font-size: 12px;">Sovereign Sanctuary Defense System</p>
                    </div>
                    """,
                    notification_type="defense_alert",
                )
                results["email"] = "sent"
                results["email_to"] = email
            else:
                results["email"] = "no_notification_system"
        except Exception as e:
            results["email"] = f"error: {e}"

    return {"status": "ok", "results": results}


# =============================================================================
# DEPENDENCY GUARDIAN
# =============================================================================

@router.get("/dependency-report")
async def get_dependency_report(request: Request):
    """Return the latest Dependency Guardian audit report."""
    guardian = getattr(request.app.state, "dependency_guardian", None)
    if guardian:
        report = guardian.get_latest_report()
        if report:
            return report
    # Fallback: read directly from disk
    from app.workers.dependency_guardian import REPORT_DIR
    reports = sorted(REPORT_DIR.glob("report_*.json"), reverse=True)
    if reports:
        return json.loads(reports[0].read_text())
    return {"timestamp": None, "summary": {"critical": 0, "warning": 0, "info": 0, "ok": 0, "total": 0}, "findings": []}


@router.post("/run-dependency-audit")
async def trigger_dependency_audit(request: Request):
    """Manually trigger a Dependency Guardian audit."""
    guardian = getattr(request.app.state, "dependency_guardian", None)
    if not guardian:
        raise HTTPException(status_code=503, detail="Dependency Guardian not initialized")
    report = await guardian.run_audit()
    return report


# =============================================================================
# PROMOTIONAL SPECIALS MANAGEMENT
# =============================================================================

class CreateSpecialRequest(BaseModel):
    name: str
    discount_type: str = "percent"
    discount_value: int = 10
    applicable_tiers: List[str] = []
    starts_at: Optional[str] = None
    ends_at: str
    max_redemptions: Optional[int] = None
    promo_code: Optional[str] = None


@router.post("/billing/special")
async def create_promotional_special(req: CreateSpecialRequest, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    starts = datetime.fromisoformat(req.starts_at) if req.starts_at else datetime.utcnow()
    ends = datetime.fromisoformat(req.ends_at)

    if ends <= starts:
        raise HTTPException(400, "ends_at must be after starts_at")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO promotional_specials
                (name, discount_type, discount_value, applicable_tiers,
                 starts_at, ends_at, max_redemptions, promo_code)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, name, created_at
        """, req.name, req.discount_type, req.discount_value,
            req.applicable_tiers or [], starts, ends,
            req.max_redemptions,
            req.promo_code.strip().upper() if req.promo_code else None)

    return {"special_id": str(row["id"]), "name": row["name"], "created": True}


@router.get("/billing/specials")
async def list_promotional_specials(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"specials": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, discount_type, discount_value, applicable_tiers,
                   starts_at, ends_at, max_redemptions, current_redemptions,
                   promo_code, active, created_at
            FROM promotional_specials
            ORDER BY created_at DESC
            LIMIT 50
        """)

    return {
        "specials": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "discount_type": r["discount_type"],
                "discount_value": r["discount_value"],
                "applicable_tiers": r["applicable_tiers"] or [],
                "starts_at": r["starts_at"].isoformat(),
                "ends_at": r["ends_at"].isoformat(),
                "max_redemptions": r["max_redemptions"],
                "current_redemptions": r["current_redemptions"],
                "promo_code": r["promo_code"],
                "active": r["active"],
                "is_live": bool(r["active"] and r["starts_at"] and r["ends_at"] and r["starts_at"] <= datetime.now(timezone.utc) < r["ends_at"]),
            }
            for r in rows
        ],
    }


@router.delete("/billing/special/{special_id}")
async def deactivate_special(special_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE promotional_specials SET active = FALSE WHERE id = $1",
            special_id,
        )

    return {"deactivated": True, "special_id": special_id}


# =============================================================================
# SCHOOL CODE MANAGEMENT
# =============================================================================

class CreateSchoolCodeRequest(BaseModel):
    school_name: str
    school_code: str
    discount_percent: int = 10
    max_students: Optional[int] = None


@router.post("/billing/school-codes")
async def create_school_code_legacy(req: CreateSchoolCodeRequest, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                INSERT INTO school_codes (school_name, school_code, discount_percent, max_students)
                VALUES ($1, $2, $3, $4)
                RETURNING id, school_name, school_code
            """, req.school_name, req.school_code.strip().upper(),
                req.discount_percent, req.max_students)
        except Exception as e:
            if "unique" in str(e).lower():
                raise HTTPException(400, "School code already exists")
            raise

    return {"school_code_id": str(row["id"]), "school_name": row["school_name"], "code": row["school_code"]}


@router.get("/billing/school-codes")
async def list_school_codes_legacy(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"school_codes": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, school_name, school_code, discount_percent,
                   max_students, current_students, active, created_at
            FROM school_codes ORDER BY created_at DESC
        """)

    return {
        "school_codes": [
            {
                "id": str(r["id"]),
                "school_name": r["school_name"],
                "school_code": r["school_code"],
                "discount_percent": r["discount_percent"],
                "max_students": r["max_students"],
                "current_students": r["current_students"],
                "active": r["active"],
            }
            for r in rows
        ],
    }


@router.delete("/billing/school-code/{code_id}")
async def deactivate_school_code(code_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        await conn.execute("UPDATE school_codes SET active = FALSE WHERE id = $1", code_id)

    return {"deactivated": True}


# =============================================================================
# CORPORATE SPONSOR MANAGEMENT
# =============================================================================

class CreateCorporateSponsorRequest(BaseModel):
    company_name: str
    sponsor_code: str
    discount_type: str = "percent"
    discount_value: int = 0
    pays_full: bool = False
    max_employees: Optional[int] = None
    billing_contact_email: Optional[str] = None


@router.post("/billing/corporate-sponsors")
async def create_corporate_sponsor_legacy(req: CreateCorporateSponsorRequest, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                INSERT INTO corporate_sponsors
                    (company_name, sponsor_code, discount_type, discount_value,
                     pays_full, max_employees, billing_contact_email)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, company_name, sponsor_code
            """, req.company_name, req.sponsor_code.strip().upper(),
                req.discount_type, req.discount_value, req.pays_full,
                req.max_employees, req.billing_contact_email)
        except Exception as e:
            if "unique" in str(e).lower():
                raise HTTPException(400, "Sponsor code already exists")
            raise

    return {
        "sponsor_id": str(row["id"]),
        "company_name": row["company_name"],
        "code": row["sponsor_code"],
    }


@router.get("/billing/corporate-sponsors")
async def list_corporate_sponsors_legacy(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"sponsors": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, company_name, sponsor_code, discount_type, discount_value,
                   pays_full, max_employees, current_employees, billing_contact_email,
                   active, created_at
            FROM corporate_sponsors ORDER BY created_at DESC
        """)

    return {
        "sponsors": [
            {
                "id": str(r["id"]),
                "company_name": r["company_name"],
                "sponsor_code": r["sponsor_code"],
                "discount_type": r["discount_type"],
                "discount_value": r["discount_value"],
                "pays_full": r["pays_full"],
                "max_employees": r["max_employees"],
                "current_employees": r["current_employees"],
                "billing_contact_email": r["billing_contact_email"],
                "active": r["active"],
            }
            for r in rows
        ],
    }


@router.delete("/billing/corporate-sponsor/{sponsor_id}")
async def deactivate_corporate_sponsor(sponsor_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        await conn.execute("UPDATE corporate_sponsors SET active = FALSE WHERE id = $1", sponsor_id)

    return {"deactivated": True}


# =============================================================================
# SCHOLARSHIP FUND OVERSIGHT
# =============================================================================

@router.get("/billing/scholarship-funds")
async def list_scholarship_funds(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"funds": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT sf.id, sf.fund_name, sf.balance_cents, sf.total_deposited,
                   sf.total_disbursed, sf.active, sf.created_at,
                   u.name as sponsor_name
            FROM scholarship_funds sf
            LEFT JOIN users u ON sf.sponsor_user_id = u.id
            ORDER BY sf.created_at DESC
        """)

        alloc_counts = await conn.fetch("""
            SELECT fund_id, COUNT(*) as cnt
            FROM scholarship_allocations WHERE active = TRUE
            GROUP BY fund_id
        """)
        alloc_map = {str(r["fund_id"]): r["cnt"] for r in alloc_counts}

    return {
        "funds": [
            {
                "id": str(r["id"]),
                "fund_name": r["fund_name"],
                "sponsor_name": r["sponsor_name"],
                "balance_cents": r["balance_cents"],
                "total_deposited": r["total_deposited"],
                "total_disbursed": r["total_disbursed"],
                "active_beneficiaries": alloc_map.get(str(r["id"]), 0),
                "active": r["active"],
            }
            for r in rows
        ],
    }


# =============================================================================
# HOH DECISION OBSERVATIONS — Admin insight into family dynamics
# =============================================================================

@router.get("/billing/hoh-observations/{family_id}")
async def get_hoh_observations(family_id: str, request: Request):
    """Return HoH decision observations for a family (admin-only, anonymized notes)."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"observations": []}

    async with pool.acquire() as conn:
        # Resolve to a UUID — input may be a UUID string or a hardware_id
        resolved_id = None
        try:
            import uuid as _uuid
            _uuid.UUID(family_id)
            resolved_id = family_id
        except ValueError:
            pass

        if resolved_id:
            rows = await conn.fetch("""
                SELECT o.id, o.charge_type, o.charge_amount, o.decision,
                       o.decline_reason, o.nate_classification, o.created_at,
                       u.name as hoh_name
                FROM hoh_decision_observations o
                LEFT JOIN users u ON o.hoh_user_id = u.id
                WHERE o.family_id = $1::uuid
                ORDER BY o.created_at DESC
                LIMIT 50
            """, resolved_id)
        else:
            rows = await conn.fetch("""
                SELECT o.id, o.charge_type, o.charge_amount, o.decision,
                       o.decline_reason, o.nate_classification, o.created_at,
                       u.name as hoh_name
                FROM hoh_decision_observations o
                LEFT JOIN users u ON o.hoh_user_id = u.id
                WHERE o.hoh_user_id = (SELECT id FROM users WHERE hardware_id = $1 LIMIT 1)
                ORDER BY o.created_at DESC
                LIMIT 50
            """, family_id)

    return {
        "family_id": family_id,
        "observations": [
            {
                "id": str(r["id"]),
                "charge_type": r["charge_type"],
                "amount": float(r["charge_amount"]),
                "decision": r["decision"],
                "decline_reason": r["decline_reason"],
                "classification": r["nate_classification"],
                "hoh_name": r["hoh_name"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/agent-digest/send")
async def trigger_agent_digest(request: Request):
    """Trigger an immediate Agent Status Digest email from the live app process."""
    digest = getattr(request.app.state, "agent_status_digest", None)
    if not digest:
        raise HTTPException(503, "AgentStatusDigest not running")
    now = datetime.now(timezone.utc)
    await digest._build_and_send(now)
    return {"status": "sent", "timestamp": now.isoformat()}


@router.post("/skyeye-audit/send")
async def trigger_skyeye_audit(request: Request):
    """Trigger an immediate SkyEye Tab Trust Scorecard email."""
    auditor = getattr(request.app.state, "skyeye_tab_auditor", None)
    if not auditor:
        raise HTTPException(503, "SkyEyeTabAuditor not running")
    now = datetime.now(timezone.utc)
    await auditor._build_and_send(now)
    return {"status": "sent", "timestamp": now.isoformat()}


@router.post("/command-audit/send")
async def trigger_command_audit(request: Request):
    """Trigger an immediate Sovereign Command Tab Trust Scorecard email."""
    auditor = getattr(request.app.state, "command_tab_auditor", None)
    if not auditor:
        raise HTTPException(503, "SovereignCommandAuditor not running")
    now = datetime.now(timezone.utc)
    await auditor._build_and_send(now)
    return {"status": "sent", "timestamp": now.isoformat()}


@router.post("/eye-audit/send")
async def trigger_eye_audit(request: Request):
    """Trigger an immediate The Eye Trust Scorecard email."""
    auditor = getattr(request.app.state, "the_eye_auditor", None)
    if not auditor:
        raise HTTPException(503, "TheEyeAuditor not running")
    now = datetime.now(timezone.utc)
    await auditor._build_and_send(now)
    return {"status": "sent", "timestamp": now.isoformat()}


@router.post("/login-audit/send")
async def trigger_login_audit(request: Request):
    """Trigger an immediate Login Trust Scorecard email."""
    auditor = getattr(request.app.state, "login_auditor", None)
    if not auditor:
        raise HTTPException(503, "LoginAuditor not running")
    now = datetime.now(timezone.utc)
    await auditor._build_and_send(now)
    return {"status": "sent", "timestamp": now.isoformat()}


@router.post("/client-audit/send")
async def trigger_client_audit(request: Request):
    """Trigger an immediate Client App Trust Scorecard email."""
    auditor = getattr(request.app.state, "client_app_auditor", None)
    if not auditor:
        raise HTTPException(503, "ClientAppAuditor not running")
    now = datetime.now(timezone.utc)
    await auditor._build_and_send(now)
    return {"status": "sent", "timestamp": now.isoformat()}


@router.post("/all-audits/send")
async def trigger_all_audits(request: Request):
    """Trigger ALL auditors sequentially (used to refresh trust scores on demand)."""
    now = datetime.now(timezone.utc)
    triggered = []
    auditor_attrs = [
        "skyeye_tab_auditor", "command_tab_auditor", "the_eye_auditor",
        "login_auditor", "client_app_auditor", "coach_dojo_auditor",
        "billing_auditor", "defense_auditor", "ai_pipeline_auditor",
        "ws_flow_auditor", "tier_gating_auditor", "nevedal_lab_auditor",
        "hw_security_auditor", "system_integrity_auditor",
        "dojo_session_auditor", "wisdom_pipeline_auditor", "settings_tab_auditor",
        "coach_hierarchy_auditor", "liminal_presence_auditor",
        "pmb_command_center_auditor", "data_uniformity_tracer",
    ]
    for attr in auditor_attrs:
        auditor = getattr(request.app.state, attr, None)
        if auditor and hasattr(auditor, "_build_and_send"):
            try:
                await auditor._build_and_send(now)
                triggered.append(attr)
            except Exception as e:
                triggered.append(f"{attr}:ERROR:{str(e)[:40]}")
    return {"status": "sent", "triggered": len(triggered), "auditors": triggered,
            "timestamp": now.isoformat()}


# =============================================================================
# CORP_ADMIN ACCOUNT CREATION (ADMIN-only)
# =============================================================================

class CreateCorpAdminRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_]+$')
    password: str = Field(..., min_length=8, max_length=128)
    email: str = Field(..., pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    company_id: str
    name: Optional[str] = Field(None, max_length=200)


@router.post("/create-corp-admin")
async def create_corp_admin(req: CreateCorpAdminRequest, request: Request, admin=Depends(require_admin)):
    """Create a CORP_ADMIN user linked to a corporate_sponsors entry."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    import secrets, hashlib

    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT username FROM users WHERE LOWER(username) = LOWER($1)", req.username
        )
        if existing:
            raise HTTPException(400, f"Username '{req.username}' already exists")

        sponsor = await conn.fetchrow(
            "SELECT id, company_name FROM corporate_sponsors WHERE id = $1::uuid",
            req.company_id,
        )
        if not sponsor:
            raise HTTPException(404, f"Corporate sponsor {req.company_id} not found")

        salt = secrets.token_hex(16)
        pw_hash = hashlib.pbkdf2_hmac("sha256", req.password.encode(), salt.encode(), 100000).hex()
        password_hash = f"{salt}:{pw_hash}"
        hw_id = f"CORP_ADMIN_{req.username.upper()}_ID"

        await conn.execute(
            """INSERT INTO users (username, hardware_id, role, subscription_status, tier,
                                  password_hash, company_id, name, profile_data)
               VALUES ($1, $2, 'CORP_ADMIN', 'PENDING_VERIFICATION', 'STANDARD', $3, $4::uuid, $5,
                       $6::jsonb)""",
            req.username,
            hw_id,
            password_hash,
            req.company_id,
            req.name or req.username,
            json.dumps({
                "name": req.name or req.username,
                "email": req.email,
                "company_id": req.company_id,
                "company_name": sponsor["company_name"],
                "role": "CORP_ADMIN",
                "certification_status": "PENDING",
            }),
        )

    try:
        from app.websocket.bridge_server import notification_system as _ns
        if _ns:
            import asyncio
            asyncio.create_task(_ns._send_email(
                to_email="admin_nevedalnj@sovereignsanctuary.net",
                subject=f"New Corporate Admin Awaiting Approval: {req.name or req.username} ({sponsor['company_name']})",
                content=(
                    f"A new corporate administrator has been created and requires your approval.\n\n"
                    f"Name: {req.name or req.username}\n"
                    f"Username: {req.username}\n"
                    f"Email: {req.email}\n"
                    f"Company: {sponsor['company_name']}\n\n"
                    f"Log in to Sovereign Command to approve:\n"
                    f"https://command.sovereignsanctuary.net"
                ),
                notification_type="corp_admin_pending"
            ))
    except Exception as _e:
        logger.warning("Corp admin creation notification failed (non-fatal): %s", _e)

    return {
        "status": "pending_approval",
        "username": req.username,
        "role": "CORP_ADMIN",
        "company": sponsor["company_name"],
        "message": "Account created. DrNevedal1 must approve before login is allowed.",
    }


# =============================================================================
# CORP_ADMIN APPROVAL (ADMIN-only, mirrors coach approval)
# =============================================================================

@router.get("/corp-admins")
async def list_corp_admins(request: Request, status: str = "PENDING_VERIFICATION", admin=Depends(require_admin)):
    """List CORP_ADMIN users filtered by subscription_status."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT username, hardware_id, name, email, company_id,
                      subscription_status, profile_data, created_at
               FROM users WHERE role = 'CORP_ADMIN' AND subscription_status = $1
                 AND deleted_at IS NULL
               ORDER BY created_at DESC""",
            status,
        )
        result = []
        for r in rows:
            pd = r["profile_data"] or {}
            if isinstance(pd, str):
                pd = json.loads(pd)
            result.append({
                "username": r["username"],
                "hardware_id": r["hardware_id"],
                "name": r["name"] or pd.get("name", ""),
                "email": r["email"] or pd.get("email", ""),
                "company_id": str(r["company_id"]) if r["company_id"] else pd.get("company_id", ""),
                "company_name": pd.get("company_name", ""),
                "status": r["subscription_status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
    return result


@router.post("/corp-admins/approve")
async def approve_corp_admin(req: ApproveCorpAdminRequest, request: Request, admin=Depends(require_admin)):
    """Approve or reject a pending CORP_ADMIN account."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT username, name, email, profile_data
               FROM users WHERE hardware_id = $1 AND role = 'CORP_ADMIN' AND deleted_at IS NULL""",
            req.admin_id,
        )
        if not row:
            raise HTTPException(404, "Corp admin not found")

        new_status = "ACTIVE" if req.approved else "ACTIVE"
        cert_status = "APPROVED" if req.approved else "REJECTED"
        sub_status = "ACTIVE" if req.approved else "REJECTED"

        update_data = json.dumps({
            "certification_status": cert_status,
            "approval_notes": req.notes,
            "approved_at": str(datetime.now()),
        })
        await conn.execute(
            """UPDATE users SET subscription_status = $1,
               profile_data = profile_data || $2::jsonb, updated_at = NOW()
               WHERE hardware_id = $3""",
            sub_status, update_data, req.admin_id,
        )

        pd = row["profile_data"] or {}
        if isinstance(pd, str):
            pd = json.loads(pd)

        ca_email = row["email"] or pd.get("email")
        ca_name = row["name"] or pd.get("name", "Corporate Admin")

        try:
            from app.websocket.bridge_server import notification_system as _ns
            if ca_email and _ns:
                import asyncio
                if req.approved:
                    asyncio.create_task(_ns._send_email(
                        to_email=ca_email,
                        subject="Your Corporate Admin Account Has Been Approved!",
                        content=(
                            f"Congratulations {ca_name}!\n\n"
                            f"Your corporate administrator account on Sovereign Sanctuary has been approved. "
                            f"You can now sign in to the Corporate Command Dashboard.\n\n"
                            f"Sign in at: https://command.sovereignsanctuary.net\n\n"
                            f"Welcome aboard."
                        ),
                        notification_type="corp_admin_approval"
                    ))
                else:
                    asyncio.create_task(_ns._send_email(
                        to_email=ca_email,
                        subject="Corporate Admin Application Update",
                        content=(
                            f"Dear {ca_name},\n\n"
                            f"Your corporate administrator application has been reviewed. "
                            f"Unfortunately, it has not been approved at this time.\n\n"
                            f"Notes: {req.notes or 'No additional notes.'}\n\n"
                            f"Please contact support@sovereignsanctuary.net for questions."
                        ),
                        notification_type="corp_admin_rejection"
                    ))
        except Exception as _n_err:
            logger.warning("Corp admin approval notification error (non-fatal): %s", _n_err)

    return {"message": "Corporate admin status updated", "status": sub_status}


# =============================================================================
# WEBAUTHN / YUBIKEY REGISTRATION (REST API — avoids WebSocket conflicts)
# =============================================================================

class WebAuthnRegisterCompleteRequest(BaseModel):
    credential: dict
    label: Optional[str] = "YubiKey"

@router.post("/webauthn/register-options")
async def webauthn_register_options(request: Request, user: dict = Depends(require_admin)):
    """Generate WebAuthn registration options for a physical security key."""
    try:
        from webauthn import generate_registration_options
        from webauthn.helpers.structs import (
            AuthenticatorAttachment,
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
        from webauthn.helpers import options_to_json
    except ImportError:
        raise HTTPException(503, "WebAuthn library not installed on server")

    pool = getattr(request.app.state, "db_pool", None)
    hw_id = user.get("hardware_id", "")

    existing_creds = []
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
                )
                if row and row["profile_data"]:
                    pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
                    existing_creds = pd.get("webauthn_credentials", [])
                    legacy = pd.get("webauthn_credential")
                    if legacy and not existing_creds:
                        existing_creds = [legacy]
        except Exception as e:
            logger.warning(f"WebAuthn: failed to load existing creds: {e}")

    exclude = []
    for ec in existing_creds:
        if ec.get("credential_id"):
            exclude.append(PublicKeyCredentialDescriptor(
                id=bytes.fromhex(ec["credential_id"])
            ))

    _webauthn_origin = os.environ.get("WEBAUTHN_ORIGIN", "https://command.sovereignsanctuary.net")

    options = generate_registration_options(
        rp_id="sovereignsanctuary.net",
        rp_name="Sovereign Sanctuary",
        user_id=hw_id.encode(),
        user_name=user.get("username", "admin"),
        user_display_name=user.get("name", "Admin"),
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.CROSS_PLATFORM,
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude,
    )

    challenge_hex = options.challenge.hex() if isinstance(options.challenge, bytes) else str(options.challenge)
    challenge_issued_at = str(datetime.now(timezone.utc))

    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE users SET profile_data = profile_data || $1::jsonb
                       WHERE hardware_id = $2""",
                    json.dumps({
                        "webauthn_challenge": challenge_hex,
                        "webauthn_challenge_issued_at": challenge_issued_at,
                    }),
                    hw_id,
                )
        except Exception as e:
            logger.warning(f"WebAuthn: failed to store challenge: {e}")

    return {
        "options": json.loads(options_to_json(options)),
        "existing_count": len(existing_creds),
    }


@router.post("/webauthn/register-complete")
async def webauthn_register_complete(
    body: WebAuthnRegisterCompleteRequest,
    request: Request,
    user: dict = Depends(require_admin),
):
    """Verify and store a WebAuthn credential from a physical security key."""
    try:
        from webauthn import verify_registration_response
        from webauthn.helpers.structs import (
            AuthenticatorAttestationResponse,
            RegistrationCredential,
        )
        from webauthn.helpers import base64url_to_bytes
    except ImportError:
        raise HTTPException(503, "WebAuthn library not installed on server")

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if not row or not row["profile_data"]:
            raise HTTPException(400, "Admin profile not found")

        pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
        challenge_hex = pd.get("webauthn_challenge", "")
        if not challenge_hex:
            raise HTTPException(400, "No pending registration challenge — call register-options first")

        issued_at_str = pd.get("webauthn_challenge_issued_at", "")
        if issued_at_str:
            try:
                issued_at = datetime.fromisoformat(issued_at_str.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - issued_at).total_seconds()
                if age_seconds > 120:
                    await conn.execute(
                        """UPDATE users SET profile_data = profile_data - 'webauthn_challenge' - 'webauthn_challenge_issued_at'
                           WHERE hardware_id = $1""", hw_id)
                    raise HTTPException(400, "Challenge expired (>120s). Request new registration options.")
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("webauthn_register_complete: challenge expiry check failed: %s", e)

        _webauthn_origin = os.environ.get("WEBAUTHN_ORIGIN", "https://command.sovereignsanctuary.net")

        try:
            cred_data = body.credential
            raw_response = cred_data.get("response", {})

            reg_credential = RegistrationCredential(
                id=cred_data["id"],
                raw_id=base64url_to_bytes(cred_data["rawId"]),
                response=AuthenticatorAttestationResponse(
                    client_data_json=base64url_to_bytes(raw_response["clientDataJSON"]),
                    attestation_object=base64url_to_bytes(raw_response["attestationObject"]),
                ),
                type="public-key",
            )

            verification = verify_registration_response(
                credential=reg_credential,
                expected_challenge=bytes.fromhex(challenge_hex),
                expected_rp_id="sovereignsanctuary.net",
                expected_origin=_webauthn_origin,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"WebAuthn verification failed: {e}")
            await conn.execute(
                """UPDATE users SET profile_data = profile_data - 'webauthn_challenge' - 'webauthn_challenge_issued_at'
                   WHERE hardware_id = $1""", hw_id)
            raise HTTPException(400, f"Registration verification failed: {e}")

        new_cred = {
            "credential_id": verification.credential_id.hex(),
            "public_key": verification.credential_public_key.hex(),
            "sign_count": verification.sign_count,
            "label": body.label,
            "registered_at": str(datetime.now(timezone.utc)),
        }

        existing_creds = pd.get("webauthn_credentials", [])
        legacy = pd.get("webauthn_credential")
        if not existing_creds and legacy:
            legacy.setdefault("label", "YubiKey 1")
            legacy.setdefault("registered_at", str(datetime.now(timezone.utc)))
            existing_creds = [legacy]

        existing_creds.append(new_cred)

        update_payload = {
            "webauthn_enabled": True,
            "webauthn_credentials": existing_creds,
            "webauthn_credential": new_cred,
        }

        await conn.execute(
            """UPDATE users SET profile_data = profile_data || $1::jsonb
               WHERE hardware_id = $2""",
            json.dumps(update_payload),
            hw_id,
        )

        await conn.execute(
            """UPDATE users SET profile_data = profile_data - 'webauthn_challenge' - 'webauthn_challenge_issued_at'
               WHERE hardware_id = $1""",
            hw_id,
        )

        logger.info(f"[WEBAUTHN] Key '{body.label}' registered for {hw_id[:16]} (total: {len(existing_creds)})")

    return {
        "success": True,
        "label": body.label,
        "total_keys": len(existing_creds),
    }


@router.get("/webauthn/keys")
async def webauthn_list_keys(request: Request, user: dict = Depends(require_admin)):
    """List registered WebAuthn security keys for the admin."""
    pool = getattr(request.app.state, "db_pool", None)
    hw_id = user.get("hardware_id", "")
    keys = []

    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
                )
                if row and row["profile_data"]:
                    pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
                    raw_keys = pd.get("webauthn_credentials", [])
                    for k in raw_keys:
                        keys.append({
                            "label": k.get("label", "Unknown"),
                            "credential_id_prefix": k.get("credential_id", "")[:16],
                            "registered_at": k.get("registered_at", ""),
                        })
        except Exception as e:
            logger.warning(f"WebAuthn: failed to list keys: {e}")

    return {
        "keys": keys,
        "webauthn_enabled": len(keys) > 0,
    }


class WebAuthnDeleteKeyRequest(BaseModel):
    credential_id_prefix: str = Field(min_length=8, max_length=64)


@router.post("/webauthn/delete-key")
async def webauthn_delete_key(
    body: WebAuthnDeleteKeyRequest,
    request: Request,
    user: dict = Depends(require_admin),
):
    """Remove a registered WebAuthn key by credential ID prefix. At least one key must remain."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if not row or not row["profile_data"]:
            raise HTTPException(400, "Profile not found")

        pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
        creds = pd.get("webauthn_credentials", [])

        matched_idx = None
        matched_label = "Unknown"
        for i, c in enumerate(creds):
            if c.get("credential_id", "").startswith(body.credential_id_prefix):
                matched_idx = i
                matched_label = c.get("label", "Unknown")
                break

        if matched_idx is None:
            raise HTTPException(404, "No key matches that credential ID prefix")

        if len(creds) <= 1:
            raise HTTPException(400, "Cannot delete last remaining key — register a replacement first")

        creds.pop(matched_idx)

        update = {"webauthn_credentials": creds}
        if len(creds) > 0:
            update["webauthn_credential"] = creds[0]

        await conn.execute(
            """UPDATE users SET profile_data = profile_data || $1::jsonb
               WHERE hardware_id = $2""",
            json.dumps(update), hw_id,
        )

    logger.info(f"[WEBAUTHN] Key '{matched_label}' deleted for {hw_id[:16]} (remaining: {len(creds)})")
    return {"success": True, "deleted_label": matched_label, "remaining_keys": len(creds)}


# =============================================================================
# TOTP AUTHENTICATOR SETUP
# =============================================================================

class TOTPVerifyRequest(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')

    @property
    def validated_code(self) -> str:
        c = self.code.strip()
        if not re.match(r'^\d{6}$', c):
            raise ValueError("TOTP code must be 6 digits")
        return c

class TOTPSetupRequest(BaseModel):
    current_code: str = ""


@router.post("/totp/setup")
async def totp_setup(request: Request, user: dict = Depends(require_admin),
                     body: TOTPSetupRequest = TOTPSetupRequest()):
    """Generate a TOTP secret and provisioning URI for authenticator apps."""
    import pyotp

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if row and row["profile_data"]:
            pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
            if pd.get("totp_enabled"):
                existing_secret = pd.get("totp_secret", "")
                if not body.current_code:
                    raise HTTPException(400, "TOTP is already enabled -- provide current_code to re-setup")
                if not existing_secret or not pyotp.TOTP(existing_secret).verify(body.current_code, valid_window=1):
                    raise HTTPException(400, "Invalid current TOTP code")

    secret = pyotp.random_base32()
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.get("username", "admin"),
        issuer_name="Sovereign Sanctuary",
    )

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE users SET profile_data = profile_data || $1::jsonb
               WHERE hardware_id = $2""",
            json.dumps({"totp_secret": secret, "totp_enabled": False}),
            hw_id,
        )

    qr_base64 = ""
    try:
        import qrcode
        import io
        import base64
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_base64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as qr_err:
        logger.warning(f"[TOTP] QR generation failed (non-fatal): {qr_err}")

    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri,
        "issuer": "Sovereign Sanctuary",
        "account": user.get("username", "admin"),
        "qr_code": qr_base64,
    }


@router.post("/totp/verify")
async def totp_verify(body: TOTPVerifyRequest, request: Request, user: dict = Depends(require_admin)):
    """Verify a TOTP code to confirm authenticator is set up correctly."""
    import pyotp

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if not row or not row["profile_data"]:
            raise HTTPException(400, "Profile not found")

        pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
        secret = pd.get("totp_secret", "")
        if not secret:
            raise HTTPException(400, "No TOTP secret configured -- call /totp/setup first")

        totp = pyotp.TOTP(secret)
        try:
            code = body.validated_code
        except ValueError as ve:
            raise HTTPException(400, str(ve))
        if not totp.verify(code, valid_window=1):
            raise HTTPException(400, "Invalid TOTP code")

        await conn.execute(
            """UPDATE users SET profile_data = profile_data || '{"totp_enabled": true}'::jsonb
               WHERE hardware_id = $1""",
            hw_id,
        )

    logger.info(f"[TOTP] Authenticator configured for {hw_id[:16]}")
    return {"success": True, "totp_enabled": True}


@router.get("/totp/status")
async def totp_status(request: Request, user: dict = Depends(require_admin)):
    """Check whether TOTP is configured for the admin."""
    pool = getattr(request.app.state, "db_pool", None)
    hw_id = user.get("hardware_id", "")
    enabled = False

    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
                )
                if row and row["profile_data"]:
                    pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
                    enabled = pd.get("totp_enabled", False)
        except Exception as e:
            logger.warning(f"TOTP status check failed: {e}")

    return {"totp_enabled": enabled}


# =============================================================================
# SMS VERIFICATION PHONE SETUP
# =============================================================================

class SMSSetPhoneRequest(BaseModel):
    phone: str

class SMSConfirmRequest(BaseModel):
    code: str = Field(pattern=r'^\d{4,8}$')

@router.post("/sms/set-phone")
async def sms_set_phone(body: SMSSetPhoneRequest, request: Request, user: dict = Depends(require_admin)):
    """Store the admin's phone number for SMS verification."""
    import re
    phone = re.sub(r'[^\d+]', '', body.phone.strip())
    if not phone.startswith('+'):
        phone = '+1' + phone
    phone = '+' + re.sub(r'[^0-9]', '', phone[1:])
    if not re.match(r'^\+[1-9]\d{6,14}$', phone):
        raise HTTPException(400, "Invalid phone number (E.164 format required)")

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE users SET profile_data = profile_data || $1::jsonb
               WHERE hardware_id = $2""",
            json.dumps({"phone": phone, "sms_verified": False}),
            hw_id,
        )

    return {"phone_set": True, "phone_masked": phone[:3] + "****" + phone[-4:]}


_sms_send_timestamps: dict = {}

@router.post("/sms/send-verify")
async def sms_send_verify(request: Request, user: dict = Depends(require_admin)):
    """Send an OTP to the admin's stored phone via Twilio Verify."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    now_ts = time.time()
    recent = [ts for ts in _sms_send_timestamps.get(hw_id, []) if now_ts - ts < 600]
    if len(recent) >= 3:
        raise HTTPException(429, "Rate limit: max 3 SMS per 10 minutes")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if not row or not row["profile_data"]:
            raise HTTPException(400, "Profile not found")
        pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
        phone = pd.get("phone", "")
        if not phone:
            raise HTTPException(400, "No phone number set -- call /sms/set-phone first")

    try:
        from twilio.rest import Client as TwilioClient
        twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        twilio_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        verify_sid = os.environ.get("TWILIO_VERIFY_SID", "")
        if not (twilio_sid and twilio_token and verify_sid):
            raise HTTPException(503, "Twilio not configured")

        client = TwilioClient(twilio_sid, twilio_token)
        verification = client.verify.v2.services(verify_sid).verifications.create(
            to=phone, channel="sms"
        )
        recent.append(now_ts)
        _sms_send_timestamps[hw_id] = recent
        logger.info(f"[SMS] Verification sent to {phone[:3]}****{phone[-4:]} status={verification.status}")
        return {"sent": True, "status": verification.status}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SMS] Failed to send verification: {e}")
        raise HTTPException(500, "SMS service temporarily unavailable")


@router.post("/sms/confirm")
async def sms_confirm(body: SMSConfirmRequest, request: Request, user: dict = Depends(require_admin)):
    """Verify the SMS OTP code and mark phone as verified."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if not row or not row["profile_data"]:
            raise HTTPException(400, "Profile not found")
        pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
        phone = pd.get("phone", "")
        if not phone:
            raise HTTPException(400, "No phone number set")

    try:
        from twilio.rest import Client as TwilioClient
        twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        twilio_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        verify_sid = os.environ.get("TWILIO_VERIFY_SID", "")

        client = TwilioClient(twilio_sid, twilio_token)
        check = client.verify.v2.services(verify_sid).verification_checks.create(
            to=phone, code=body.code
        )

        if check.status != "approved":
            raise HTTPException(400, "Invalid or expired code")

        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET profile_data = profile_data || '{"sms_verified": true}'::jsonb
                   WHERE hardware_id = $1""",
                hw_id,
            )

        logger.info(f"[SMS] Phone verified for {hw_id[:16]}")
        return {"success": True, "sms_verified": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SMS] Verification check failed: {e}")
        raise HTTPException(500, "SMS verification service unavailable")


@router.get("/sms/status")
async def sms_status(request: Request, user: dict = Depends(require_admin)):
    """Check whether SMS verification is configured."""
    pool = getattr(request.app.state, "db_pool", None)
    hw_id = user.get("hardware_id", "")
    verified = False
    phone_set = False

    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
                )
                if row and row["profile_data"]:
                    pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
                    verified = pd.get("sms_verified", False)
                    phone_set = bool(pd.get("phone", ""))
        except Exception as e:
            logger.warning(f"SMS status check failed: {e}")

    return {"sms_verified": verified, "phone_set": phone_set}


# =============================================================================
# YUBIKEY PRESENCE DETECTION
# =============================================================================

_webauthn_auth_options_last: dict = {}

@router.post("/webauthn/auth-options")
async def webauthn_auth_options(request: Request, user: dict = Depends(require_admin)):
    """Generate a WebAuthn authentication challenge to detect which key is present."""
    try:
        from webauthn import generate_authentication_options
        from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
        from webauthn.helpers import options_to_json
    except ImportError:
        raise HTTPException(503, "WebAuthn library not installed")

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    now_ts = datetime.now(timezone.utc).timestamp()
    last_ts = _webauthn_auth_options_last.get(hw_id, 0)
    if now_ts - last_ts < 5:
        raise HTTPException(429, "Too many challenge requests — wait a few seconds")
    _webauthn_auth_options_last[hw_id] = now_ts

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if not row or not row["profile_data"]:
            raise HTTPException(400, "No profile found")
        pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
        creds = pd.get("webauthn_credentials", [])
        if not creds:
            raise HTTPException(400, "No YubiKeys registered")

    allow = []
    for c in creds:
        if c.get("credential_id"):
            allow.append(PublicKeyCredentialDescriptor(
                id=bytes.fromhex(c["credential_id"])
            ))

    options = generate_authentication_options(
        rp_id="sovereignsanctuary.net",
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    challenge_hex = options.challenge.hex() if isinstance(options.challenge, bytes) else str(options.challenge)
    challenge_issued_at = str(datetime.now(timezone.utc))
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET profile_data = profile_data || $1::jsonb
                   WHERE hardware_id = $2""",
                json.dumps({
                    "webauthn_auth_challenge": challenge_hex,
                    "webauthn_auth_challenge_issued_at": challenge_issued_at,
                }),
                hw_id,
            )
    except Exception as e:
        logger.error(f"[WEBAUTHN] Challenge storage failed: {e}")
        raise HTTPException(503, "Failed to store auth challenge")

    return {"options": json.loads(options_to_json(options))}


class WebAuthnAuthVerifyRequest(BaseModel):
    credential: dict

@router.post("/webauthn/auth-verify")
async def webauthn_auth_verify(
    body: WebAuthnAuthVerifyRequest,
    request: Request,
    user: dict = Depends(require_admin),
):
    """Verify a WebAuthn assertion to confirm which key is present and upgrade Sentinel."""
    try:
        from webauthn import verify_authentication_response
        from webauthn.helpers.structs import AuthenticationCredential, AuthenticatorAssertionResponse
        from webauthn.helpers import base64url_to_bytes
    except ImportError:
        raise HTTPException(503, "WebAuthn library not installed")

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hw_id = user.get("hardware_id", "")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
        )
        if not row or not row["profile_data"]:
            raise HTTPException(400, "Profile not found")

        pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
        challenge_hex = pd.get("webauthn_auth_challenge", "")
        if not challenge_hex:
            raise HTTPException(400, "No pending auth challenge")

        issued_at_str = pd.get("webauthn_auth_challenge_issued_at", "")
        if issued_at_str:
            try:
                issued_at = datetime.fromisoformat(issued_at_str.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - issued_at).total_seconds()
                if age_seconds > 120:
                    await conn.execute(
                        """UPDATE users SET profile_data = profile_data - 'webauthn_auth_challenge' - 'webauthn_auth_challenge_issued_at'
                           WHERE hardware_id = $1""", hw_id)
                    raise HTTPException(400, "Auth challenge expired (>120s). Request a new one.")
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("webauthn_auth_verify: challenge expiry check failed: %s", e)

        _webauthn_origin = os.environ.get("WEBAUTHN_ORIGIN", "https://command.sovereignsanctuary.net")

        creds = pd.get("webauthn_credentials", [])
        cred_data = body.credential
        raw_resp = cred_data.get("response", {})

        matched_label = "Unknown"
        matched_cred = None

        try:
            required_fields = ["id", "rawId"]
            resp_fields = ["clientDataJSON", "authenticatorData", "signature"]
            if not all(cred_data.get(f) for f in required_fields):
                raise HTTPException(400, "Missing required credential fields")
            if not all(raw_resp.get(f) for f in resp_fields):
                raise HTTPException(400, "Missing required response fields")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Malformed credential payload")

        for c in creds:
            if not c.get("credential_id") or not c.get("public_key"):
                continue
            try:
                auth_credential = AuthenticationCredential(
                    id=cred_data["id"],
                    raw_id=base64url_to_bytes(cred_data["rawId"]),
                    response=AuthenticatorAssertionResponse(
                        client_data_json=base64url_to_bytes(raw_resp["clientDataJSON"]),
                        authenticator_data=base64url_to_bytes(raw_resp["authenticatorData"]),
                        signature=base64url_to_bytes(raw_resp["signature"]),
                    ),
                    type="public-key",
                )
                verification = verify_authentication_response(
                    credential=auth_credential,
                    expected_challenge=bytes.fromhex(challenge_hex),
                    expected_rp_id="sovereignsanctuary.net",
                    expected_origin=_webauthn_origin,
                    credential_public_key=bytes.fromhex(c["public_key"]),
                    credential_current_sign_count=c.get("sign_count", 0),
                )
                matched_cred = c
                matched_label = c.get("label", "Unknown")
                c["sign_count"] = verification.new_sign_count
                break
            except Exception as e:
                logger.debug("webauthn_auth_verify: credential %s did not match: %s", c.get("label", "?"), e)
                continue

        if not matched_cred:
            await conn.execute(
                """UPDATE users SET profile_data = profile_data - 'webauthn_auth_challenge' - 'webauthn_auth_challenge_issued_at'
                   WHERE hardware_id = $1""", hw_id)
            raise HTTPException(400, "No matching credential found")

        verified_at = str(datetime.now(timezone.utc))
        await conn.execute(
            """UPDATE users SET profile_data = profile_data || $1::jsonb
               WHERE hardware_id = $2""",
            json.dumps({
                "webauthn_last_verified": verified_at,
                "webauthn_active_key": matched_label,
                "sentinel_auth_method": "yubikey",
                "sentinel_frozen": False,
                "webauthn_credentials": creds,
            }),
            hw_id,
        )

        # Also clear in-memory Sentinel freeze if bridge is accessible
        bridge_sentinel = getattr(request.app.state, "sentinel", None)
        if bridge_sentinel and hasattr(bridge_sentinel, "unfreeze"):
            bridge_sentinel.unfreeze(hw_id)
            bridge_sentinel.set_auth_method(hw_id, "yubikey")

        await conn.execute(
            """UPDATE users SET profile_data = profile_data - 'webauthn_auth_challenge' - 'webauthn_auth_challenge_issued_at'
               WHERE hardware_id = $1""",
            hw_id,
        )

    logger.info(f"[WEBAUTHN] Key '{matched_label}' verified present for {hw_id[:16]} -- Sentinel upgraded to yubikey")
    return {
        "verified": True,
        "active_key": matched_label,
        "credential_id_prefix": matched_cred.get("credential_id", "")[:16],
        "verified_at": verified_at,
        "sentinel_upgraded": True,
    }


@router.get("/webauthn/presence")
async def webauthn_presence(request: Request, user: dict = Depends(require_admin)):
    """Check the last known key presence state."""
    pool = getattr(request.app.state, "db_pool", None)
    hw_id = user.get("hardware_id", "")

    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE hardware_id = $1", hw_id
                )
                if row and row["profile_data"]:
                    pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])
                    return {
                        "active_key": pd.get("webauthn_active_key"),
                        "last_verified": pd.get("webauthn_last_verified"),
                        "webauthn_enabled": pd.get("webauthn_enabled", False),
                        "key_count": len(pd.get("webauthn_credentials", [])),
                        "sentinel_frozen": pd.get("sentinel_frozen", False),
                        "sentinel_auth_method": pd.get("sentinel_auth_method", "password"),
                    }
        except Exception as e:
            logger.warning(f"Presence check failed: {e}")

    return {
        "active_key": None, "last_verified": None,
        "webauthn_enabled": False, "key_count": 0,
        "sentinel_frozen": False, "sentinel_auth_method": "password",
    }


# =============================================================================
# ADMIN DOJO ASSIGNMENT (bypass Stripe for manual DOJO grants)
# =============================================================================

@router.post("/billing/add-dojo")
async def admin_add_dojo(request: Request, user: dict = Depends(require_admin)):
    """Admin-only: Add a DOJO subscription to a coach's profile without requiring Stripe payment."""
    body = await request.json()
    coach_hw_id = body.get("coach_id", "").strip()
    dojo_key = body.get("dojo_key", "").strip().lower()

    if not coach_hw_id or not dojo_key:
        raise HTTPException(400, "coach_id and dojo_key are required")

    valid_dojos = {"therapist", "project_pm", "business", "cnc", "mcat", "teacher", "judge", "coach_nate"}
    if dojo_key not in valid_dojos:
        raise HTTPException(400, f"Invalid dojo_key: {dojo_key}. Must be one of {sorted(valid_dojos)}")

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT username, profile_data FROM users WHERE hardware_id = $1 AND role = 'COACH'",
                coach_hw_id,
            )
            if not row:
                raise HTTPException(404, f"Coach not found: {coach_hw_id}")

            pd = row["profile_data"]
            if isinstance(pd, str):
                pd = json.loads(pd)
            pd = pd or {}

            dojo_subs = pd.get("dojo_subscriptions", {})
            from datetime import datetime as _dt
            dojo_subs[dojo_key] = {
                "status": "active",
                "started_at": _dt.utcnow().isoformat(),
                "granted_by_admin": user.get("username", "admin"),
            }
            pd["dojo_subscriptions"] = dojo_subs

            await conn.execute(
                "UPDATE users SET profile_data = $1::jsonb WHERE hardware_id = $2",
                json.dumps(pd), coach_hw_id,
            )

        return {
            "status": "ok",
            "message": f"DOJO '{dojo_key}' activated for coach {row['username']}",
            "coach_username": row["username"],
            "dojo_key": dojo_key,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to add DOJO: {e}")


# ── SSE Story Generator endpoints ─────────────────────────────────────
from fastapi import UploadFile, File as FastFile
from app.services.api_server import get_current_user as _sse_auth

sse_router = APIRouter(prefix="/api/sse", tags=["sse"], dependencies=[Depends(require_admin)])
sse_client_router = APIRouter(prefix="/api/sse-client", tags=["sse-client"])

@sse_client_router.post("/intake/turn")
async def sse_client_intake_turn(request: Request, _user: dict = Depends(_sse_auth)):
    body = await request.json()
    from app.services.intake_session import process_intake_turn
    uid = body.get("user_id") or _user.get("hardware_id", "")
    return await process_intake_turn(uid, body.get("user_name", ""), body.get("turn", 1), body.get("user_message", ""), body.get("conversation_history", []), request.app.state.db_pool)

@sse_client_router.get("/intake/status/{user_id}")
async def sse_client_intake_status(user_id: str, request: Request, _user: dict = Depends(_sse_auth)):
    from app.services.intake_session import get_intake_status
    return await get_intake_status(user_id, request.app.state.db_pool)

@sse_client_router.get("/storyboard")
async def sse_client_storyboard(request: Request, _user: dict = Depends(_sse_auth)):
    pool = request.app.state.db_pool
    uid = _user.get("hardware_id", "")
    async with pool.acquire() as conn:
        enrollment = await conn.fetchrow(
            "SELECT storyboard_id FROM sse_enrolled_users WHERE user_id=$1 AND status='active'", uid)
        if not enrollment:
            return {"enrolled": False, "message": "Complete Identity Forge intake to begin your story"}
        sid = enrollment["storyboard_id"]
        prov = await conn.fetchrow(
            "SELECT story_plot_json FROM sse_ip_provenance "
            "WHERE story_plot_json->>'id' = $1 AND status='approved' LIMIT 1", sid)
        if not prov:
            return {"enrolled": True, "storyboard_id": sid, "panels": []}
        sp = prov["story_plot_json"] if isinstance(prov["story_plot_json"], dict) else json.loads(prov["story_plot_json"])
        panels = [{"phase_id": p.get("phase_id"), "r2_url": p.get("r2_url"),
                    "title": p.get("scene_description", "")[:80], "narrative": p.get("scene_description", ""),
                    "panel_tone": p.get("panel_tone")}
                   for p in sp.get("panels", []) if p.get("r2_url")]
    return {"enrolled": True, "storyboard_id": sid, "panels": panels}

@sse_client_router.get("/vault/{user_id}")
async def sse_client_vault(user_id: str, request: Request, _user: dict = Depends(_sse_auth)):
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT generation_type, generated_at, r2_url, storyboard_id "
            "FROM sse_delivery_generation_log WHERE user_id=$1 AND status='success' "
            "ORDER BY generated_at DESC LIMIT 50", user_id)
        if rows:
            return {"items": [{"type": r["generation_type"], "r2_url": r["r2_url"],
                               "delivered_at": str(r["generated_at"]), "storyboard_id": r["storyboard_id"]}
                              for r in rows]}
        enrollment = await conn.fetchrow(
            "SELECT storyboard_id FROM sse_enrolled_users WHERE user_id=$1 AND status='active'", user_id)
        if not enrollment:
            return {"items": []}
        prov = await conn.fetchrow(
            "SELECT story_plot_json FROM sse_ip_provenance "
            "WHERE story_plot_json->>'id' = $1 AND status='approved' LIMIT 1", enrollment["storyboard_id"])
        if not prov:
            return {"items": []}
        sp = prov["story_plot_json"] if isinstance(prov["story_plot_json"], dict) else json.loads(prov["story_plot_json"])
        return {"items": [{"type": "panel", "phase_id": p.get("phase_id"), "r2_url": p.get("r2_url"),
                           "title": p.get("scene_description", "")[:80]}
                          for p in sp.get("panels", []) if p.get("r2_url")]}

@sse_client_router.post("/quest/create")
async def sse_create_quest(request: Request, _user: dict = Depends(_sse_auth)):
    from app.sse.quest_mission_engine import create_quest
    body = await request.json()
    uid = _user.get("user_id") or _user.get("username", "")
    return await create_quest(uid, body.get("goal", ""), request.app.state.db_pool)

@sse_client_router.post("/mission/create")
async def sse_create_mission(request: Request, _user: dict = Depends(_sse_auth)):
    from app.sse.quest_mission_engine import create_mission
    body = await request.json()
    uid = _user.get("user_id") or _user.get("username", "")
    return await create_mission(uid, body.get("relationship_target", ""), body.get("relationship_type", ""), request.app.state.db_pool)

@sse_client_router.get("/quests")
async def sse_list_quests(request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM sse_quests WHERE user_id=$1 AND status='active' ORDER BY started_at DESC", uid)
    return {"quests": [dict(r) for r in rows]}

@sse_client_router.get("/missions")
async def sse_list_missions(request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM sse_missions WHERE user_id=$1 AND status='active' ORDER BY started_at DESC", uid)
    return {"missions": [dict(r) for r in rows]}

@sse_client_router.post("/quest/{quest_id}/complete")
async def sse_complete_quest(quest_id: str, request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sse_quests SET status='completed', completed_at=NOW() WHERE quest_id=$1 AND user_id=$2", quest_id, uid)
        await conn.execute("INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail) VALUES ($1, 'quest_completed', 'Quest Completed', $2)", uid, quest_id)
    return {"status": "completed", "quest_id": quest_id}

@sse_client_router.post("/quest/{quest_id}/pause")
async def sse_pause_quest(quest_id: str, request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute("UPDATE sse_quests SET status='paused' WHERE quest_id=$1 AND user_id=$2", quest_id, uid)
    return {"status": "paused", "quest_id": quest_id}

@sse_client_router.post("/mission/{mission_id}/complete")
async def sse_complete_mission(mission_id: str, request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sse_missions SET status='completed', completed_at=NOW() WHERE mission_id=$1 AND user_id=$2", mission_id, uid)
        await conn.execute("INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail) VALUES ($1, 'mission_completed', 'Mission Completed', $2)", uid, mission_id)
    return {"status": "completed", "mission_id": mission_id}

@sse_client_router.post("/mission/{mission_id}/pause")
async def sse_pause_mission(mission_id: str, request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute("UPDATE sse_missions SET status='paused' WHERE mission_id=$1 AND user_id=$2", mission_id, uid)
    return {"status": "paused", "mission_id": mission_id}

def _parse_json_col(val):
    if val is None: return {}
    return json.loads(val) if isinstance(val, str) else val

@sse_router.post("/pipeline/run")
async def sse_pipeline_run(request: Request, file: UploadFile = FastFile(...)):
    from app.sse.foundation import pipeline
    result = await pipeline.run_pipeline(await file.read(), file.content_type or "", file.filename or "upload", uploader_id="admin", db_pool=getattr(request.app.state, "db_pool", None))
    status = "failed" if "error" in result else "processing"
    return {"provenance_id": result.get("provenance_id"), "status": status}

@sse_router.get("/pipeline/status/{provenance_id}")
async def sse_pipeline_status(provenance_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"provenance_id": provenance_id, "status": "unknown", "story_plot_id": None}
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, story_plot_id FROM sse_ip_provenance WHERE provenance_id = $1", provenance_id)
    if not row: raise HTTPException(404, "Not found")
    return {"provenance_id": provenance_id, "status": row["status"], "story_plot_id": row["story_plot_id"]}

@sse_router.get("/pipeline/queue")
async def sse_pipeline_queue(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT provenance_id, filename, status, story_plot_id, source_hash, upload_timestamp FROM sse_ip_provenance ORDER BY upload_timestamp DESC LIMIT 50")
    return [dict(r) for r in rows]

@sse_router.get("/pipeline/result/{provenance_id}")
async def sse_pipeline_result(provenance_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "No database pool")
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM sse_ip_provenance WHERE provenance_id = $1", provenance_id)
    if not row: raise HTTPException(404, "Not found")
    result = dict(row)
    result["story_plot"] = _parse_json_col(result.pop("story_plot_json", None)) or None
    result["delivery_config"] = _parse_json_col(result.pop("delivery_config_json", None))
    result["estimated_cost"] = _parse_json_col(result.pop("estimated_cost_json", None))
    return result

@sse_router.get("/monitor/metrics")
async def sse_monitor_metrics(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    async with pool.acquire() as c:
        active = await c.fetchval("SELECT COUNT(*) FROM sse_cron_schedules WHERE enabled=true") or 0
        panels = await c.fetchval("SELECT COUNT(*) FROM sse_delivery_generation_log WHERE generation_type='daily_panel' AND generated_at::date=CURRENT_DATE") or 0
        cost = await c.fetchval("SELECT COALESCE(SUM(cost),0) FROM sse_delivery_generation_log WHERE generated_at::date=CURRENT_DATE") or 0
        breaker = await c.fetchval("SELECT status FROM sse_cost_circuit_breaker WHERE status='tripped' ORDER BY triggered_at DESC LIMIT 1")
        gaps = await c.fetchval("SELECT COUNT(*) FROM sse_delivery_heartbeat WHERE status='gaps_detected' AND checked_at > NOW()-INTERVAL '1 hour'") or 0
    return {"active_storyboards": active, "panels_today": panels, "cost_today": float(cost), "circuit_breaker_status": breaker or "clear", "gaps_detected": gaps}

@sse_router.get("/monitor/storyboards")
async def sse_monitor_storyboards(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT cs.storyboard_id, "
            "(SELECT COUNT(*) FROM sse_enrolled_users eu WHERE eu.storyboard_id=cs.storyboard_id AND eu.status='active') AS enrolled_users, "
            "(SELECT MAX(gl.generated_at) FROM sse_delivery_generation_log gl WHERE gl.storyboard_id=cs.storyboard_id AND gl.generation_type='daily_panel' AND gl.status='success') AS last_panel, "
            "(SELECT MAX(gl.generated_at) FROM sse_delivery_generation_log gl WHERE gl.storyboard_id=cs.storyboard_id AND gl.generation_type='weekly_clip' AND gl.status='success') AS last_clip, "
            "(SELECT MAX(gl.generated_at) FROM sse_delivery_generation_log gl WHERE gl.storyboard_id=cs.storyboard_id AND gl.generation_type='monthly_recap' AND gl.status='success') AS last_recap "
            "FROM sse_cron_schedules cs WHERE cs.enabled=true GROUP BY cs.storyboard_id")
    result = []
    for r in rows:
        gap = "on_schedule"
        if r["last_panel"]:
            from datetime import datetime, timezone
            hours = (datetime.now(timezone.utc) - r["last_panel"]).total_seconds() / 3600
            if hours > 25: gap = "gap"
            elif hours > 20: gap = "recovering"
        else:
            gap = "gap"
        result.append({**dict(r), "last_panel": str(r["last_panel"]) if r["last_panel"] else None, "last_clip": str(r["last_clip"]) if r["last_clip"] else None, "last_recap": str(r["last_recap"]) if r["last_recap"] else None, "gap_status": gap})
    return result

@sse_router.get("/monitor/generation-log")
async def sse_monitor_gen_log(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT log_id,storyboard_id,user_id,generation_type,generated_at,r2_url,score,cost,status,error_message FROM sse_delivery_generation_log ORDER BY generated_at DESC LIMIT 50")
    return [dict(r) for r in rows]

@sse_router.get("/monitor/circuit-breaker")
async def sse_monitor_breaker(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    async with pool.acquire() as c:
        daily = await c.fetchval("SELECT COALESCE(SUM(cost),0) FROM sse_delivery_generation_log WHERE generated_at::date=CURRENT_DATE") or 0
        monthly = await c.fetchval("SELECT COALESCE(SUM(cost),0) FROM sse_delivery_generation_log WHERE generated_at >= date_trunc('month',CURRENT_DATE)") or 0
        trips = await c.fetch("SELECT breaker_id,storyboard_id,triggered_at,daily_spend,resumed_at,status FROM sse_cost_circuit_breaker ORDER BY triggered_at DESC LIMIT 20")
    return {"daily_spend": float(daily), "monthly_spend": float(monthly), "trips": [dict(r) for r in trips]}

@sse_router.get("/monitor/heartbeat")
async def sse_monitor_heartbeat(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT heartbeat_id,checked_at,storyboards_checked,gaps_found,status,notes FROM sse_delivery_heartbeat ORDER BY checked_at DESC LIMIT 24")
    return [dict(r) for r in rows]

@sse_router.post("/monitor/force-run")
async def sse_monitor_force_run(request: Request):
    body = await request.json()
    sid, gtype = body.get("storyboard_id"), body.get("type")
    if not sid or gtype not in ("daily_panel", "weekly_clip", "monthly_recap"): raise HTTPException(422, "storyboard_id and type required")
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    from app.sse.foundation import delivery_runtime as dr
    fn = {"daily_panel": dr.generate_daily_panels, "weekly_clip": dr.generate_weekly_clips, "monthly_recap": dr.generate_monthly_recap}[gtype]
    return await fn(sid, pool)

@sse_router.post("/monitor/pause")
async def sse_monitor_pause(request: Request):
    body = await request.json()
    sid = body.get("storyboard_id")
    if not sid: raise HTTPException(422, "storyboard_id required")
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    async with pool.acquire() as c:
        await c.execute("UPDATE sse_cron_schedules SET enabled=false WHERE storyboard_id=$1", sid)
    return {"storyboard_id": sid, "status": "paused"}

@sse_router.post("/monitor/reset-breaker")
async def sse_monitor_reset_breaker(request: Request):
    body = await request.json()
    sid = body.get("storyboard_id", "")
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    async with pool.acquire() as c:
        if sid:
            await c.execute("UPDATE sse_cost_circuit_breaker SET status='reset',resumed_at=NOW() WHERE storyboard_id=$1 AND status='tripped'", sid)
        else:
            await c.execute("UPDATE sse_cost_circuit_breaker SET status='reset',resumed_at=NOW() WHERE status='tripped'")
    return {"storyboard_id": sid or "all", "status": "reset"}

@sse_router.post("/intake/turn")
async def sse_intake_turn(request: Request):
    body = await request.json()
    from app.services.intake_session import process_intake_turn
    db = request.app.state.db_pool
    return await process_intake_turn(body["user_id"], body.get("user_name", ""), body.get("turn", 1), body.get("user_message", ""), body.get("conversation_history", []), db)

@sse_router.get("/intake/status/{user_id}")
async def sse_intake_status(user_id: str, request: Request):
    from app.services.intake_session import get_intake_status
    return await get_intake_status(user_id, request.app.state.db_pool)

@sse_router.post("/imagery/generate")
async def sse_imagery_generate(request: Request):
    body = await request.json()
    story_plot = body.get("story_plot")
    if not story_plot: raise HTTPException(422, "story_plot required in body")
    from app.sse.layer6_imagination_engine import generate_story_imagery
    result = await generate_story_imagery(story_plot)
    pool = getattr(request.app.state, "db_pool", None)
    prov_id = body.get("provenance_id")
    if pool and prov_id and result.get("results"):
        import json as _json
        url_map = {r["phase_id"]: r["r2_url"] for r in result["results"] if r.get("r2_url")}
        if url_map:
            async with pool.acquire() as conn:
                row = await conn.fetchval("SELECT story_plot_json FROM sse_ip_provenance WHERE provenance_id = $1", prov_id)
                if row:
                    sp = _json.loads(row) if isinstance(row, str) else dict(row)
                    for p in sp.get("panels", []):
                        if p.get("phase_id") in url_map:
                            p["r2_url"] = url_map[p["phase_id"]]
                    await conn.execute("UPDATE sse_ip_provenance SET story_plot_json = $1 WHERE provenance_id = $2", _json.dumps(sp), prov_id)
    return result

@sse_router.post("/imagery/regenerate-panel")
async def sse_imagery_regenerate_panel(request: Request):
    body = await request.json()
    prov_id, phase_id, custom_prompt = body.get("provenance_id"), body.get("phase_id"), body.get("custom_prompt", "")
    if not prov_id or not phase_id or not custom_prompt:
        raise HTTPException(422, "provenance_id, phase_id, custom_prompt required")
    pool = request.app.state.db_pool
    import json as _json, hashlib
    async with pool.acquire() as conn:
        row = await conn.fetchval("SELECT story_plot_json FROM sse_ip_provenance WHERE provenance_id = $1", prov_id)
        if not row: raise HTTPException(404, "provenance not found")
        sp = _json.loads(row) if isinstance(row, str) else dict(row)
        panel = next((p for p in sp.get("panels", []) if p.get("phase_id") == phase_id), None)
        if not panel: raise HTTPException(404, f"panel {phase_id} not found")
        suffix = panel.get("core_character_suffix", "")
        full_prompt = custom_prompt + (" " + suffix if suffix else "") + " --no text, watermark, logo"
        from app.sse.infrastructure.grok_imagine_client import generate_image
        from app.sse.infrastructure.r2_storage import store_image
        image_bytes = await generate_image(full_prompt)
        content_hash = hashlib.sha256(image_bytes).hexdigest()[:12]
        storyboard_id = sp.get("id", "unknown")
        r2_key = f"sse/staging/{storyboard_id}/{phase_id}/{content_hash}.png"
        r2_url = await store_image(image_bytes, r2_key)
        panel["grok_imagine_prompt"] = custom_prompt
        panel["r2_url"] = r2_url
        await conn.execute("UPDATE sse_ip_provenance SET story_plot_json = $1 WHERE provenance_id = $2", _json.dumps(sp), prov_id)
    return {"phase_id": phase_id, "r2_url": r2_url, "prompt_used": full_prompt}

@sse_router.post("/pipeline/approve")
async def sse_pipeline_approve(request: Request):
    body = await request.json()
    prov_id = body.get("provenance_id")
    if not prov_id: raise HTTPException(422, "provenance_id required")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sse_ip_provenance SET status = 'approved' WHERE provenance_id = $1", prov_id)
        r = await conn.fetchrow("SELECT story_plot_json, delivery_config_json FROM sse_ip_provenance WHERE provenance_id = $1", prov_id)
        if not r: raise HTTPException(404, "provenance_id not found")
        import json as _json
        sp = _json.loads(r["story_plot_json"]) if isinstance(r["story_plot_json"], str) else dict(r["story_plot_json"] or {})
        dc = _json.loads(r["delivery_config_json"]) if isinstance(r["delivery_config_json"], str) else dict(r["delivery_config_json"] or {})
        storyboard_id = sp.get("id", "unknown")
        delivery = dc or sp.get("delivery_config", {})
        await conn.execute(
            "INSERT INTO sse_cron_schedules (schedule_id, storyboard_id, schedule_type, cron_expression, enabled) "
            "VALUES (gen_random_uuid(), $1, 'daily_panel', '0 3 * * *', true) "
            "ON CONFLICT (storyboard_id, schedule_type) DO UPDATE SET enabled = true",
            storyboard_id)
        if delivery.get("monthly_recap", False):
            await conn.execute(
                "INSERT INTO sse_cron_schedules (schedule_id, storyboard_id, schedule_type, cron_expression, enabled) "
                "VALUES (gen_random_uuid(), $1, 'monthly_recap', '0 4 1 * *', true) "
                "ON CONFLICT (storyboard_id, schedule_type) DO UPDATE SET enabled = true",
                storyboard_id)
        await conn.execute(
            "UPDATE sse_delivery_config SET status='replaced' WHERE storyboard_id=$1 AND status='active'",
            storyboard_id)
        await conn.execute(
            "INSERT INTO sse_delivery_config (config_id, storyboard_id, delivery_config) "
            "VALUES (gen_random_uuid(), $1, $2::jsonb)", storyboard_id, _json.dumps(delivery))
        await conn.execute(
            "INSERT INTO sse_cron_schedules (schedule_id, storyboard_id, schedule_type, cron_expression, enabled) "
            "VALUES (gen_random_uuid(), $1, 'weekly_clip', '0 3 * * 0', true) "
            "ON CONFLICT (storyboard_id, schedule_type) DO UPDATE SET enabled = true",
            storyboard_id)
    orch = getattr(request.app.state, "sse_orchestrator", None)
    if orch: await orch.reload()
    return {"status": "approved", "storyboard_id": storyboard_id}

@sse_router.get("/monitor/alerts")
async def sse_monitor_alerts(request: Request, acknowledged: str = "all"):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    q = "SELECT alert_id,user_id,alert_type,title,detail,metadata,acknowledged,created_at FROM sse_admin_alerts"
    if acknowledged == "false": q += " WHERE acknowledged = false"
    elif acknowledged == "true": q += " WHERE acknowledged = true"
    q += " ORDER BY created_at DESC LIMIT 100"
    async with pool.acquire() as conn:
        rows = await conn.fetch(q)
    return {"alerts": [dict(r) for r in rows]}

@sse_router.post("/monitor/alerts/acknowledge")
async def sse_monitor_alerts_ack(request: Request):
    body = await request.json()
    aid = body.get("alert_id")
    if not aid: raise HTTPException(422, "alert_id required")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sse_admin_alerts SET acknowledged = true WHERE alert_id = $1::uuid", aid)
    return {"status": "acknowledged"}

@sse_router.get("/monitor/user/{user_id}")
async def sse_monitor_user(user_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool: raise HTTPException(503, "no db")
    from app.sse.thera_world_engine import get_user_sse_status
    return await get_user_sse_status(user_id, pool)

@sse_router.post("/admin/assign-workbook")
async def sse_assign_workbook(request: Request):
    body = await request.json()
    uid, sid = body.get("user_id", ""), body.get("storyboard_id", "")
    if not uid or not sid: raise HTTPException(422, "user_id and storyboard_id required")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sse_enrolled_users (enrollment_id, user_id, storyboard_id, source) VALUES (gen_random_uuid(), $1, $2, 'coach_assigned') "
            "ON CONFLICT (user_id, storyboard_id) DO UPDATE SET source='coach_assigned', status='active'", uid, sid)
        await conn.execute("INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail) VALUES ($1, 'workbook_assigned', 'Workbook Assigned', $2)", uid, f"Storyboard: {sid}")
    return {"assigned": True, "user_id": uid, "storyboard_id": sid}

@sse_router.post("/admin/backfill-intake/{user_id}")
async def sse_backfill_intake(user_id: str, request: Request):
    pool = request.app.state.db_pool
    from app.sse.layer1_identity_forge import extract_intake_data
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT conversation_history FROM sse_identity_forge WHERE user_id=$1", user_id)
    if not row or not row["conversation_history"]: raise HTTPException(404, "no intake data")
    conv = json.loads(row["conversation_history"]) if isinstance(row["conversation_history"], str) else row["conversation_history"]
    result = await extract_intake_data(conv, pool, user_id)
    return {"user_id": user_id, "result": result}

@sse_router.post("/admin/backfill-intake-all")
async def sse_backfill_all(request: Request):
    pool = request.app.state.db_pool
    from app.sse.layer1_identity_forge import extract_intake_data
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, conversation_history FROM sse_identity_forge WHERE archetype_hint IS NULL AND conversation_history IS NOT NULL")
    processed, succeeded, failed = 0, 0, 0
    for r in rows:
        processed += 1
        try:
            conv = json.loads(r["conversation_history"]) if isinstance(r["conversation_history"], str) else r["conversation_history"]
            await extract_intake_data(conv, pool, r["user_id"])
            succeeded += 1
        except Exception:
            failed += 1
    return {"processed": processed, "succeeded": succeeded, "failed": failed}
