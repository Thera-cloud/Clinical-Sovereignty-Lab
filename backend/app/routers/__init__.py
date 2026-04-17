# Little Nate API Routers
# Real implementations live in individual router files (admin.py, billing.py, etc.).
# This file provides lightweight routers for domains that don't yet have
# a dedicated file, keeping the app bootable.

from fastapi import APIRouter, Depends, Request, HTTPException
from uuid import UUID

# ─── Auth Router ─────────────────────────────────────────────────────────────
auth = APIRouter(prefix="/api/auth", tags=["auth"])


@auth.post("/login")
async def login(request: Request):
    """Authenticate a user and return a JWT token."""
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    if not username or not password:
        raise HTTPException(400, "username and password are required")

    db = request.app.state.db_pool
    row = await db.fetchrow(
        "SELECT id, password_hash, role, name FROM users WHERE username = $1",
        username,
    )
    if not row:
        raise HTTPException(401, "Invalid credentials")

    # Constant-time hash comparison — no plaintext fallback
    import hashlib, hmac as _hmac
    provided_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), username.encode(), 100_000
    ).hex()
    if not _hmac.compare_digest(provided_hash, row["password_hash"]):
        raise HTTPException(401, "Invalid credentials")

    return {
        "user_id": str(row["id"]),
        "role": row["role"],
        "name": row["name"],
        "token": f"placeholder-jwt-{row['id']}",  # real JWT issued by bridge
    }


@auth.post("/register")
async def register(request: Request):
    """Register a new user (Threshold / Trial tier)."""
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    name = body.get("name", "")
    email = body.get("email", "")
    if not username or not password:
        raise HTTPException(400, "username and password are required")

    db = request.app.state.db_pool
    exists = await db.fetchval(
        "SELECT 1 FROM users WHERE username = $1", username
    )
    if exists:
        raise HTTPException(409, "Username already taken")

    import hashlib, secrets as _secrets
    _salt = _secrets.token_hex(16)
    pw_hash = f"{_salt}:{hashlib.pbkdf2_hmac('sha256', password.encode(), _salt.encode(), 100_000).hex()}"

    user_id = await db.fetchval(
        """INSERT INTO users (username, password_hash, name, email, role, tier)
           VALUES ($1, $2, $3, $4, 'CLIENT', 'TRIAL')
           RETURNING id""",
        username, pw_hash, name or username, email or "",
    )

    return {"user_id": str(user_id), "tier": "TRIAL", "status": "registered"}


# ─── Users Router ────────────────────────────────────────────────────────────
users = APIRouter(prefix="/api/users", tags=["users"])


def _get_require_admin():
    from app.services.api_server import require_admin
    return require_admin


@users.get("/")
async def list_users(
    request: Request,
    current_user: dict = Depends(_get_require_admin()),
    role: str = None,
    limit: int = 50,
    offset: int = 0,
):
    """List users, optionally filtered by role. Admin only."""
    db = request.app.state.db_pool
    if role:
        rows = await db.fetch(
            "SELECT id, username, name, role, tier, created_at "
            "FROM users WHERE role = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            role.upper(), limit, offset,
        )
    else:
        rows = await db.fetch(
            "SELECT id, username, name, role, tier, created_at "
            "FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
    return {
        "users": [
            {
                "id": str(r["id"]),
                "username": r["username"],
                "name": r["name"],
                "role": r["role"],
                "tier": r["tier"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


def _get_current_user():
    from app.services.api_server import get_current_user
    return get_current_user


@users.get("/{user_id}")
async def get_user(
    user_id: UUID,
    request: Request,
    current_user: dict = Depends(_get_current_user()),
):
    """Get a single user by ID. Self-access or admin only."""
    caller_role = (current_user.get("role") or "").upper()
    caller_hw = current_user.get("hardware_id", "")
    db = request.app.state.db_pool
    row = await db.fetchrow(
        "SELECT id, username, name, role, tier, hardware_id, family_id, created_at, updated_at "
        "FROM users WHERE id = $1",
        user_id,
    )
    if not row:
        raise HTTPException(404, "User not found")
    if caller_role != "ADMIN" and caller_hw != (row["hardware_id"] or ""):
        raise HTTPException(403, "Access denied")
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "name": row["name"],
        "role": row["role"],
        "tier": row["tier"],
        "family_id": str(row["family_id"]) if row["family_id"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


# ─── Nevedal Status Router ──────────────────────────────────────────────────
nevedal = APIRouter(prefix="/api/nevedal", tags=["nevedal"])


@nevedal.get("/status")
async def nevedal_status(request: Request):
    """Platform-wide Nevedal coherence status summary."""
    db = request.app.state.db_pool
    stats = await db.fetchrow(
        """SELECT
            COUNT(*) as total_measurements,
            AVG(c_emo) as avg_c_emo,
            MAX(c_emo) as max_c_emo,
            MIN(c_emo) as min_c_emo,
            SUM(CASE WHEN cee_window THEN 1 ELSE 0 END) as total_cees
           FROM nevedal_metrics
           WHERE recorded_at > NOW() - INTERVAL '24 hours'"""
    )
    return {
        "period": "last_24h",
        "total_measurements": stats["total_measurements"] or 0,
        "avg_c_emo": round(float(stats["avg_c_emo"] or 0), 4),
        "max_c_emo": round(float(stats["max_c_emo"] or 0), 4),
        "min_c_emo": round(float(stats["min_c_emo"] or 0), 4),
        "total_cees": stats["total_cees"] or 0,
    }


# ─── Night School Router (Version listing) ──────────────────────────────────
night_school = APIRouter(prefix="/api/night-school", tags=["night_school"])


@night_school.get("/versions")
async def night_school_versions(request: Request):
    """List Night School wisdom database versions / snapshots."""
    db = request.app.state.db_pool
    rows = await db.fetch(
        """SELECT id, source, category, content, created_at
           FROM wisdom_entries
           ORDER BY created_at DESC LIMIT 50"""
    )
    return {
        "entries": [
            {
                "id": r["id"],
                "source": r["source"],
                "category": r["category"],
                "content": r["content"][:200] if r["content"] else "",
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ─── Me-2-Me Platinum Router ──────────────────────────────────────────────
# (imported by main.py directly as me2me_api)

# Legacy stubs (sessions, admin, coach, billing) are handled by their
# dedicated router files: sessions.py, admin.py, coach.py, billing.py
# Those are imported directly in main.py and do NOT rely on this __init__.
