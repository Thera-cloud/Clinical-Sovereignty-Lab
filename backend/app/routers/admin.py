"""
Analytics & Admin API Routes
Platform-wide analytics, crisis monitoring, and admin functions
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import os
import json
import secrets
import hashlib
from pathlib import Path
from typing import Any, Dict

from app.services.blob_storage import upload_bytes
from app.services.api_server import require_admin

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
    except: return default

def save_json(filepath: Path, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f: json.dump(data, f, indent=2, default=str)


def _load_json_any(path: Path, default: Any):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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

# Dashboard Stats
@router.get("/dashboard")
async def get_dashboard_stats():
    """Get admin dashboard statistics"""
    registry = load_json(DATA_DIR / "user_registry.json")
    sessions = load_json(DATA_DIR / "sessions.json", [])
    analytics = load_json(DATA_DIR / "analytics.json")
    
    now = datetime.now()
    today = str(now.date())
    week_ago = now - timedelta(days=7)
    
    # Count users by role
    clients = coaches = admins = 0
    active_users = 0
    new_this_week = 0
    
    for k, v in registry.items():
        p = v.get("profile", {})
        role = p.get("role", "CLIENT")
        if role == "CLIENT": clients += 1
        elif role == "COACH": coaches += 1
        elif role == "ADMIN": admins += 1
        
        # Active in last 7 days
        last_login = p.get("last_login", "")
        if last_login:
            try:
                login_dt = datetime.fromisoformat(last_login.split(".")[0])
                if login_dt >= week_ago:
                    active_users += 1
            except Exception:
                pass  # malformed date — skip silently
        
        # New this week
        joined = p.get("joined_date", "")
        if joined:
            try:
                joined_dt = datetime.fromisoformat(joined)
                if joined_dt >= week_ago.date():
                    new_this_week += 1
            except Exception:
                pass  # malformed date — skip silently
    
    # Session stats
    live_sessions = len([s for s in sessions if s.get("status") == "active"])
    completed_today = len([s for s in sessions 
                          if s.get("status") == "completed" 
                          and s.get("actual_end", "").startswith(today)])
    
    # Today's analytics
    today_stats = analytics.get("daily_stats", {}).get(today, {})
    
    # Token usage
    total_tokens_today = today_stats.get("tokens_used", 0)
    
    # Crisis count
    crisis_log = load_json(DATA_DIR / "crisis_log.json", [])
    active_crises = len([c for c in crisis_log if not c.get("resolved", False)])
    
    return {
        "users": {
            "total": len(registry),
            "clients": clients,
            "coaches": coaches,
            "admins": admins,
            "active_7d": active_users,
            "new_this_week": new_this_week
        },
        "sessions": {
            "live": live_sessions,
            "completed_today": completed_today,
            "total": len(sessions)
        },
        "today": {
            "logins": today_stats.get("logins", 0),
            "registrations": today_stats.get("registrations", 0),
            "messages": today_stats.get("messages_sent", 0),
            "tokens_used": total_tokens_today
        },
        "alerts": {
            "active_crises": active_crises,
            "pending_coach_approvals": len([v for v in registry.values() 
                                           if v.get("profile", {}).get("subscription_status") == "PENDING_VERIFICATION"])
        },
        "platform": analytics.get("platform_totals", {})
    }

# User Management
@router.get("/users")
async def get_all_users(role: str = None, status: str = None, limit: int = 100):
    """Get all users with optional filters"""
    registry = load_json(DATA_DIR / "user_registry.json")
    
    users = []
    for k, v in registry.items():
        p = v.get("profile", {})
        
        if role and p.get("role") != role:
            continue
        if status and p.get("subscription_status") != status:
            continue
        
        users.append({
            "id": k,
            "hardware_id": p.get("hardware_id"),
            "name": p.get("name"),
            "email": p.get("email"),
            "role": p.get("role"),
            "tier": p.get("tier"),
            "subscription_status": p.get("subscription_status"),
            "subscription_plan": p.get("subscription_plan"),
            "joined_date": p.get("joined_date"),
            "last_login": p.get("last_login"),
            "total_sessions": p.get("total_sessions_count", 0),
            "token_balance": p.get("token_balance", 0),
            "assigned_coach": p.get("assigned_coach_id", "")
        })
    
    users.sort(key=lambda x: x.get("joined_date", ""), reverse=True)
    return {"users": users[:limit], "total": len(users)}

@router.get("/user/{user_id}")
async def get_user_details(user_id: str):
    """Get detailed user information"""
    registry = load_json(DATA_DIR / "user_registry.json")
    
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == user_id or k == user_id:
            # Load metrics
            metrics_file = VAULT_ROOT / "Clients" / p.get("hardware_id") / "metrics.json"
            metrics = load_json(metrics_file, {})
            
            # Load memory summary
            memory_file = VAULT_ROOT / "Clients" / p.get("hardware_id") / "memory.json"
            memories = load_json(memory_file, [])
            
            # Get sessions
            sessions = load_json(DATA_DIR / "sessions.json", [])
            user_sessions = [s for s in sessions if s.get("client_id") == p.get("hardware_id")]
            
            return {
                "profile": p,
                "credentials": {"username": v.get("credentials", {}).get("username")},
                "metrics": metrics.get("nevedal_state", {}),
                "metrics_history": metrics.get("history", [])[-20:],
                "conversation_count": len(memories),
                "recent_topics": _extract_topics(memories[-20:]),
                "sessions": {
                    "total": len(user_sessions),
                    "completed": len([s for s in user_sessions if s.get("status") == "completed"]),
                    "recent": user_sessions[-5:]
                }
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
    """Append an entry to the audit log."""
    audit_path = DATA_DIR / "audit_log.json"
    audit = load_json(audit_path, [])
    if not isinstance(audit, list):
        audit = []
    audit.append({"action": action, "timestamp": str(datetime.now()), **kwargs})
    save_json(audit_path, audit)


@router.post("/reset-password")
async def admin_reset_password(req: ResetPasswordRequest):
    """Reset a user's password. Audit-logged."""
    if len(req.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    registry = load_json(DATA_DIR / "user_registry.json")

    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.user_id or k == req.user_id:
            creds = v.get("credentials", {}) or {}
            creds["password"] = _hash_password(req.new_password)
            v["credentials"] = creds
            save_json(DATA_DIR / "user_registry.json", registry)
            _audit_log_append("ADMIN_RESET_PASSWORD", user_id=req.user_id, user_name=p.get("name", ""))
            return {"status": "password_reset", "user_id": req.user_id, "message": "Password updated. User must log in with new credentials."}

    raise HTTPException(404, "User not found")


@router.post("/reset-biometrics")
async def admin_reset_biometrics(req: ResetBiometricsRequest):
    """Reset a user's voice biometric baselines. Audit-logged."""
    registry = load_json(DATA_DIR / "user_registry.json")

    found = False
    hw_id = ""
    user_name = ""
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

    # Also clear from user profile
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
async def admin_ban_user(req: BanUserRequest):
    """Ban a user account (sets status to BANNED). Audit-logged."""
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
async def admin_wipe_memory(req: WipeMemoryRequest):
    """Wipe all conversation memory and metrics history for a user. Audit-logged. IRREVERSIBLE."""
    registry = load_json(DATA_DIR / "user_registry.json")

    found = False
    hw_id = ""
    user_name = ""
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


@router.get("/analytics/events")
async def get_event_stream(limit: int = 1000):
    """
    Return the last N analytics events (append-only stream).
    This is the source of truth for flow-tree timelines.
    """
    limit = max(0, min(int(limit or 1000), 20000))
    return {"events": _load_events(limit=limit)}


@router.get("/sanctuary/{sanctuary_id}/timeline")
async def get_sanctuary_timeline(sanctuary_id: str, limit_events: int = 2000):
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

    txns = []
    for t in _load_transactions():
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
async def get_coaches(status: str = None):
    """Get all coaches"""
    registry = load_json(DATA_DIR / "user_registry.json")
    
    coaches = []
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("role") != "COACH":
            continue
        if status and p.get("subscription_status") != status:
            continue
        
        # Count assigned clients
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
async def approve_coach(req: ApproveCoachRequest):
    """Approve or reject a coach application"""
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
            return {"message": "Coach status updated", "status": p["subscription_status"]}
    
    raise HTTPException(404, "Coach not found")

@router.post("/assign-coach")
async def assign_coach(req: AssignCoachRequest):
    """Assign a coach to a client"""
    registry = load_json(DATA_DIR / "user_registry.json")
    
    # Verify coach exists
    coach_exists = False
    for v in registry.values():
        if v.get("profile", {}).get("hardware_id") == req.coach_id:
            coach_exists = True
            break
    
    if not coach_exists:
        raise HTTPException(404, "Coach not found")
    
    # Update client
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.client_id:
            p["assigned_coach_id"] = req.coach_id
            p["coach_assigned_at"] = str(datetime.now())
            save_json(DATA_DIR / "user_registry.json", registry)
            return {"message": "Coach assigned", "client_id": req.client_id, "coach_id": req.coach_id}
    
    raise HTTPException(404, "Client not found")

# Crisis Management
@router.get("/crisis-watchlist")
async def get_crisis_watchlist():
    """Get users with elevated risk levels"""
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
                "user_id": p.get("hardware_id"),
                "name": p.get("name"),
                "risk_level": risk,
                "anxiety": ns.get("anxiety_level", 0),
                "depression": ns.get("depression_indicators", 0),
                "last_assessment": ns.get("last_risk_assessment", ""),
                "crisis_count": ns.get("crisis_count", 0),
                "assigned_coach": p.get("assigned_coach_id", ""),
                "last_login": p.get("last_login", "")
            })
    
    # Sort by risk level
    risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
    watchlist.sort(key=lambda x: risk_order.get(x["risk_level"], 3))
    
    return {"watchlist": watchlist, "count": len(watchlist)}

@router.get("/crisis-log")
async def get_crisis_log(resolved: bool = None, limit: int = 50):
    """Get crisis event log"""
    crisis_log = load_json(DATA_DIR / "crisis_log.json", [])
    
    if resolved is not None:
        crisis_log = [c for c in crisis_log if c.get("resolved", False) == resolved]
    
    crisis_log.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"crises": crisis_log[:limit], "total": len(crisis_log)}

@router.post("/crisis/resolve")
async def resolve_crisis(req: ResolveCrisisRequest):
    """Mark a crisis as resolved"""
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
async def get_daily_analytics(days: int = 30):
    """Get daily analytics for the past N days"""
    analytics = load_json(DATA_DIR / "analytics.json")
    daily = analytics.get("daily_stats", {})
    
    # Get last N days
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
async def get_metrics_distribution():
    """Get distribution of client metrics"""
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
async def get_community_health():
    """Aggregate community-wide coherence metrics from nevedal_metrics."""
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
        "total_clients": total_clients,
        "avg_c_emo": round(avg_c_emo, 4),
        "c_emo_range": {
            "min": round(min(c_emo_values), 4) if c_emo_values else 0,
            "max": round(max(c_emo_values), 4) if c_emo_values else 0,
        },
        "risk_distribution": risk_distribution,
        "active_cee_windows": cee_count,
        "clients_with_data": len(c_emo_values),
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
        except Exception:
            pass

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


class RetryPaymentRequest(BaseModel):
    payment_id: str


def _load_registry():
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
async def get_revenue_metrics():
    """Aggregated revenue metrics: MRR, coaching revenue, churn, conversion."""
    registry = _load_registry()
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

    # Coaching revenue from billing.json
    coaching_revenue = 0
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
async def get_subscription_analytics():
    """Subscription analytics: counts by tier, subscriber list."""
    registry = _load_registry()

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
async def get_failed_payments():
    """List failed payment attempts."""
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
        except Exception:
            pass

    combined = stripe_failed + [
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
async def process_refund(req: RefundRequest):
    """Process a refund via Stripe or local billing."""
    registry = _load_registry()
    billing = load_json(DATA_DIR / "billing.json")

    # Find user
    user_name = ""
    stripe_customer = None
    for _k, entry in registry.items():
        p = entry.get("profile", {})
        if p.get("hardware_id") == req.user_id:
            user_name = p.get("name", "")
            stripe_customer = p.get("stripe_customer_id")
            break

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

    billing.setdefault("transactions", []).append(refund_record)
    save_json(DATA_DIR / "billing.json", billing)

    # Log in audit
    audit = load_json(DATA_DIR / "audit_log.json", [])
    if not isinstance(audit, list):
        audit = []
    audit.append({
        "action": "ADMIN_REFUND",
        "user_id": req.user_id,
        "amount": req.amount,
        "reason": req.reason,
        "timestamp": str(datetime.now()),
    })
    save_json(DATA_DIR / "audit_log.json", audit)

    return {"status": "refunded", "refund": refund_record}


@router.post("/billing/override-plan")
async def override_user_plan(req: OverridePlanRequest, request: Request):
    """Manually set a user's subscription plan. Audit-logged."""
    valid_plans = ("COACH_ONLY", "TRIAL", "STANDARD", "TOP_TIER")
    if req.new_plan not in valid_plans:
        raise HTTPException(400, f"Invalid plan. Must be one of: {valid_plans}")

    registry = _load_registry()
    found = False
    old_plan = ""

    for _k, entry in registry.items():
        p = entry.get("profile", {})
        if p.get("hardware_id") == req.user_id:
            old_plan = p.get("subscription_plan", "TRIAL")
            p["subscription_plan"] = req.new_plan
            p["subscription_status"] = "ACTIVE" if req.new_plan not in ("TRIAL",) else "TRIAL_ACTIVE"
            token_map = {"COACH_ONLY": 0, "TRIAL": 10000, "STANDARD": 50000, "TOP_TIER": 200000}
            p["token_balance"] = token_map.get(req.new_plan, 0)
            found = True
            break

    if not found:
        raise HTTPException(404, "User not found")

    await _save_registry_async(registry, request)

    # Audit log
    audit = load_json(DATA_DIR / "audit_log.json", [])
    if not isinstance(audit, list):
        audit = []
    audit.append({
        "action": "ADMIN_PLAN_OVERRIDE",
        "user_id": req.user_id,
        "old_plan": old_plan,
        "new_plan": req.new_plan,
        "admin_note": req.admin_note,
        "timestamp": str(datetime.now()),
    })
    save_json(DATA_DIR / "audit_log.json", audit)

    return {
        "status": "overridden",
        "user_id": req.user_id,
        "old_plan": old_plan,
        "new_plan": req.new_plan,
    }


@router.post("/billing/coupon")
async def create_coupon(req: CouponRequest):
    """Create a discount coupon. Stores locally and optionally in Stripe."""
    billing = load_json(DATA_DIR / "billing.json")

    coupon_record = {
        "code": req.code,
        "discount": req.discount,
        "type": req.type,
        "created_at": str(datetime.now()),
        "active": True,
        "stripe_coupon": False,
    }

    # Try creating in Stripe
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

    billing.setdefault("coupons", []).append(coupon_record)
    save_json(DATA_DIR / "billing.json", billing)

    return {"status": "created", "coupon": coupon_record}


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
async def emergency_purge(req: EmergencyPurgeRequest):
    """
    Emergency data purge for a user — removes selected data categories.
    More granular than wipe-memory. Audit-logged. IRREVERSIBLE.
    """
    registry = load_json(DATA_DIR / "user_registry.json")

    found = False
    hw_id = ""
    user_name = ""
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
