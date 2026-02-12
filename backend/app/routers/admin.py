"""
Analytics & Admin API Routes
Platform-wide analytics, crisis monitoring, and admin functions
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import os
import json
from pathlib import Path
from typing import Any, Dict

from app.services.blob_storage import upload_bytes

router = APIRouter(prefix="/api/admin", tags=["admin"])

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
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
            except: pass
        
        # New this week
        joined = p.get("joined_date", "")
        if joined:
            try:
                joined_dt = datetime.fromisoformat(joined)
                if joined_dt >= week_ago.date():
                    new_this_week += 1
            except: pass
    
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
