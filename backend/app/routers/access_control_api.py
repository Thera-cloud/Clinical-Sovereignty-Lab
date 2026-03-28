"""
Access Control API — Admin-only user data management.
Search, view, and edit all user fields (clients, coaches, corporations).
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import json
import logging
import hashlib
import secrets

from app.services.api_server import require_admin

logger = logging.getLogger("nate.access_control")

router = APIRouter(
    prefix="/api/admin/access-control",
    tags=["access-control"],
    dependencies=[Depends(require_admin)],
)


class UserUpdateRequest(BaseModel):
    fields: Dict[str, Any]


class PasswordResetRequest(BaseModel):
    new_password: str


class CorporationUpdateRequest(BaseModel):
    fields: Dict[str, Any]


# Fields that live as real columns on the users table (not in profile_data JSONB)
_COLUMN_FIELDS = {
    "name", "email", "tier", "subscription_status", "token_balance",
    "phone", "dob", "family_id", "company_id", "consent_version",
    "specialties", "coaching_style",
}

# Fields that must never be editable through this API
_PROTECTED_FIELDS = {
    "id", "password_hash", "hardware_id", "created_at",
    "webauthn_credentials", "webauthn_challenge", "webauthn_challenge_issued_at",
    "webauthn_auth_challenge", "webauthn_auth_challenge_issued_at",
    "totp_secret", "password_reset_token", "password_reset_expires",
}


def _safe_profile(profile_data) -> dict:
    """Parse profile_data that may arrive as string or dict."""
    if not profile_data:
        return {}
    if isinstance(profile_data, str):
        try:
            return json.loads(profile_data)
        except Exception:
            return {}
    return dict(profile_data)


def _build_user_response(row) -> dict:
    """Convert a DB row to a comprehensive user response dict."""
    profile = _safe_profile(row.get("profile_data"))
    return {
        "id": str(row.get("id", "")),
        "username": row.get("username", ""),
        "name": row.get("name", "") or profile.get("name", ""),
        "email": row.get("email", "") or profile.get("email", ""),
        "phone": row.get("phone", "") or profile.get("phone", ""),
        "role": row.get("role", ""),
        "tier": row.get("tier", "") or profile.get("tier", ""),
        "dob": str(row.get("dob", "") or profile.get("dob", "")),
        "hardware_id": row.get("hardware_id", "") or profile.get("hardware_id", ""),
        "family_id": str(row.get("family_id", "") or profile.get("family_id", "")),
        "family_role": row.get("family_role", "") or profile.get("family_role", ""),
        "company_id": str(row.get("company_id", "") or profile.get("company_id", "")),
        "company_name": profile.get("company_name", ""),
        "subscription_status": row.get("subscription_status", "") or profile.get("subscription_status", ""),
        "subscription_plan": profile.get("subscription_plan", ""),
        "stripe_customer_id": row.get("stripe_customer_id", "") or profile.get("stripe_customer_id", ""),
        "token_balance": row.get("token_balance") if row.get("token_balance") is not None else profile.get("token_balance", 0),
        "consent_version": row.get("consent_version", "") or profile.get("consent_version", ""),
        "last_login": str(row.get("last_login", "") or profile.get("last_login", "")),
        "login_count": row.get("login_count", 0) or profile.get("login_count", 0),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
        "is_founding_member": row.get("is_founding_member", False) or profile.get("is_founding_member", False),
        "founding_member_number": row.get("founding_member_number") or profile.get("founding_member_number"),
        "coach_id": profile.get("coach_id", ""),
        "assigned_coach": profile.get("assigned_coach", ""),
        "assigned_coach_id": profile.get("assigned_coach_id", ""),
        "emergency_contact": profile.get("emergency_contact", ""),
        "preferred_contact": profile.get("preferred_contact", ""),
        "timezone": profile.get("timezone", ""),
        "social_handle": profile.get("social_handle", ""),
        "social_platform": profile.get("social_platform", ""),
        "onboarding_completed": profile.get("onboarding_completed", False),
        "profile_photo_url": profile.get("profile_photo_url", ""),
        "account_status": profile.get("account_status", ""),
        "coach_fields": _extract_coach_fields(profile, row) if row.get("role") == "COACH" else None,
        "profile_data_raw": profile,
    }


def _extract_coach_fields(profile: dict, row: dict) -> dict:
    return {
        "certification_status": profile.get("certification_status", ""),
        "coach_verified": profile.get("coach_verified", False),
        "master_coach_approved": profile.get("master_coach_approved", False),
        "approval_notes": profile.get("approval_notes", ""),
        "approved_at": profile.get("approved_at", ""),
        "coach_ethics_version": profile.get("coach_ethics_version", ""),
        "coach_ethics_accepted_at": profile.get("coach_ethics_accepted_at", ""),
        "coaching_fee": profile.get("coaching_fee", 0),
        "hourly_rate": profile.get("hourly_rate", 0),
        "platform_fee_pct": profile.get("platform_fee_pct", 30),
        "payment_mode": profile.get("payment_mode", ""),
        "zoom_link": profile.get("zoom_link", ""),
        "specializations": profile.get("specializations", []),
        "selected_dojos": profile.get("selected_dojos", []),
        "dojo_subscriptions": profile.get("dojo_subscriptions", []),
        "w9_submitted": profile.get("w9_submitted", False),
        "w9_data": profile.get("w9_data", {}),
        "tin_doc_uploaded": profile.get("tin_doc_uploaded", False),
        "tin_match_status": profile.get("tin_match_status", ""),
        "tin_verification_method": profile.get("tin_verification_method", ""),
        "requires_1099": profile.get("requires_1099", False),
        "address_verified": profile.get("address_verified", False),
        "standardized_address": profile.get("standardized_address", {}),
        "total_earnings_ytd": profile.get("total_earnings_ytd", 0),
        "total_platform_fees_ytd": profile.get("total_platform_fees_ytd", 0),
        "total_sessions_conducted": profile.get("total_sessions_conducted", 0),
        "total_sessions_billable": profile.get("total_sessions_billable", 0),
        "assigned_clients": profile.get("assigned_clients", []),
        "judge_nate_bar_id": profile.get("judge_nate_bar_id", ""),
        "beta_user": profile.get("beta_user", False),
    }


@router.get("/health")
async def health():
    return {"status": "ok", "service": "access_control"}


@router.get("/search")
async def search_users(request: Request, q: str = "", role: str = "all", limit: int = 100):
    """Search users by username, name, email, phone, or hardware_id."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    q_lower = q.strip().lower()

    async with db_pool.acquire() as conn:
        if q_lower:
            base_sql = """
                SELECT id, username, name, email, phone, role, tier, hardware_id,
                       family_id, company_id, subscription_status, token_balance,
                       profile_data, last_login, created_at
                FROM users
                WHERE (
                    LOWER(username) LIKE $1
                    OR LOWER(name) LIKE $1
                    OR LOWER(COALESCE(email, '')) LIKE $1
                    OR LOWER(COALESCE(phone, '')) LIKE $1
                    OR LOWER(COALESCE(hardware_id, '')) LIKE $1
                    OR LOWER(COALESCE(profile_data->>'name', '')) LIKE $1
                    OR LOWER(COALESCE(profile_data->>'email', '')) LIKE $1
                )
            """
            params = [f"%{q_lower}%"]
            idx = 2
        else:
            base_sql = """
                SELECT id, username, name, email, phone, role, tier, hardware_id,
                       family_id, company_id, subscription_status, token_balance,
                       profile_data, last_login, created_at
                FROM users WHERE 1=1
            """
            params = []
            idx = 1

        if role != "all":
            base_sql += f" AND role = ${idx}"
            params.append(role.upper())
            idx += 1

        base_sql += f" ORDER BY name ASC, username ASC LIMIT ${idx}"
        params.append(limit)

        rows = await conn.fetch(base_sql, *params)

    results = []
    for row in rows:
        profile = _safe_profile(row.get("profile_data"))
        results.append({
            "id": str(row["id"]),
            "username": row["username"],
            "name": row.get("name", "") or profile.get("name", ""),
            "email": row.get("email", "") or profile.get("email", ""),
            "phone": row.get("phone", "") or profile.get("phone", ""),
            "role": row["role"],
            "tier": row.get("tier", "") or profile.get("tier", ""),
            "hardware_id": row.get("hardware_id", ""),
            "family_id": str(row.get("family_id", "") or ""),
            "company_id": str(row.get("company_id", "") or ""),
            "subscription_status": row.get("subscription_status", "") or profile.get("subscription_status", ""),
            "token_balance": row.get("token_balance", 0) or 0,
            "last_login": str(row.get("last_login", "") or profile.get("last_login", "")),
            "created_at": str(row.get("created_at", "")),
        })

    return {"users": results, "count": len(results)}


@router.get("/user/{identifier}")
async def get_user_detail(request: Request, identifier: str):
    """Get full user detail by username, hardware_id, or UUID."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM users
               WHERE username = $1
                  OR hardware_id = $1
                  OR id::text = $1""",
            identifier,
        )

    if not row:
        raise HTTPException(404, f"User not found: {identifier}")

    return _build_user_response(dict(row))


@router.put("/user/{identifier}")
async def update_user(request: Request, identifier: str, body: UserUpdateRequest):
    """Update user fields. Handles both column and profile_data JSONB fields."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    blocked = [k for k in body.fields if k in _PROTECTED_FIELDS]
    if blocked:
        raise HTTPException(400, f"Cannot modify protected fields: {blocked}")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, username, hardware_id FROM users
               WHERE username = $1 OR hardware_id = $1 OR id::text = $1""",
            identifier,
        )
        if not row:
            raise HTTPException(404, f"User not found: {identifier}")

        user_id = row["id"]
        username = row["username"]

        column_updates = {}
        profile_updates = {}

        for k, v in body.fields.items():
            if k in _COLUMN_FIELDS:
                column_updates[k] = v
            else:
                profile_updates[k] = v

        if column_updates:
            sets = []
            params = []
            idx = 1
            for col, val in column_updates.items():
                sets.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
            params.append(user_id)
            await conn.execute(
                f"UPDATE users SET {', '.join(sets)}, updated_at = NOW() WHERE id = ${idx}",
                *params,
            )

        for key, val in profile_updates.items():
            await conn.execute(
                """UPDATE users SET profile_data = jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb), $1::text[], $2::jsonb
                   ), updated_at = NOW()
                   WHERE id = $3""",
                [key],
                json.dumps(val),
                user_id,
            )

        logger.info("Access Control: updated user %s — fields: %s", username, list(body.fields.keys()))

    return {"status": "updated", "username": username, "fields_updated": list(body.fields.keys())}


@router.post("/reset-password/{identifier}")
async def reset_password(request: Request, identifier: str, body: PasswordResetRequest):
    """Admin password reset for any user."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    if len(body.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256", body.new_password.encode(), salt.encode(), 100_000
    ).hex()
    stored_hash = f"{salt}:{pw_hash}"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, username FROM users
               WHERE username = $1 OR hardware_id = $1 OR id::text = $1""",
            identifier,
        )
        if not row:
            raise HTTPException(404, f"User not found: {identifier}")

        await conn.execute(
            """UPDATE users SET password_hash = $1, updated_at = NOW(),
                   profile_data = profile_data
                       - 'force_password_reset'
                       - 'password_reset_token'
                       - 'password_reset_expires'
               WHERE id = $2""",
            stored_hash, row["id"],
        )

        logger.info("Access Control: password reset for %s by admin", row["username"])

    return {"status": "password_reset", "username": row["username"]}


@router.post("/force-password-reset/{identifier}")
async def force_password_reset(request: Request, identifier: str):
    """Set force_password_reset flag — user must change password on next login."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, username FROM users
               WHERE username = $1 OR hardware_id = $1 OR id::text = $1""",
            identifier,
        )
        if not row:
            raise HTTPException(404, f"User not found: {identifier}")

        await conn.execute(
            """UPDATE users SET profile_data = jsonb_set(
                   COALESCE(profile_data, '{}'::jsonb),
                   '{force_password_reset}', 'true'::jsonb
               ), updated_at = NOW()
               WHERE id = $1""",
            row["id"],
        )

    return {"status": "force_reset_set", "username": row["username"]}


@router.get("/corporations")
async def list_corporations(request: Request, q: str = ""):
    """List all corporations, optionally filtered by search."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'corporate_sponsors')"
        )
        if not exists:
            return {"corporations": [], "count": 0}

        if q.strip():
            rows = await conn.fetch(
                """SELECT * FROM corporate_sponsors
                   WHERE LOWER(company_name) LIKE $1 OR LOWER(sponsor_code) LIKE $1
                   ORDER BY company_name ASC""",
                f"%{q.strip().lower()}%",
            )
        else:
            rows = await conn.fetch("SELECT * FROM corporate_sponsors ORDER BY company_name ASC")

    corps = []
    for row in rows:
        r = dict(row)
        for k, v in r.items():
            if isinstance(v, (datetime,)):
                r[k] = str(v)
            elif hasattr(v, "__str__") and not isinstance(v, (str, int, float, bool, list, dict)):
                r[k] = str(v)
        corps.append(r)

    return {"corporations": corps, "count": len(corps)}


@router.get("/corporation/{corp_id}")
async def get_corporation(request: Request, corp_id: str):
    """Get full corporation detail."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM corporate_sponsors WHERE id::text = $1 OR sponsor_code = $1",
            corp_id,
        )

    if not row:
        raise HTTPException(404, f"Corporation not found: {corp_id}")

    r = dict(row)
    for k, v in r.items():
        if isinstance(v, (datetime,)):
            r[k] = str(v)
        elif hasattr(v, "__str__") and not isinstance(v, (str, int, float, bool, list, dict)):
            r[k] = str(v)

    employees = []
    async with db_pool.acquire() as conn:
        emp_rows = await conn.fetch(
            """SELECT id, username, name, email, role, tier, profile_data
               FROM users WHERE company_id::text = $1
               ORDER BY name ASC""",
            str(row["id"]),
        )
        for er in emp_rows:
            profile = _safe_profile(er.get("profile_data"))
            employees.append({
                "id": str(er["id"]),
                "username": er["username"],
                "name": er.get("name", "") or profile.get("name", ""),
                "email": er.get("email", "") or profile.get("email", ""),
                "role": er["role"],
                "tier": er.get("tier", ""),
            })

    r["employees"] = employees
    return r


@router.put("/corporation/{corp_id}")
async def update_corporation(request: Request, corp_id: str, body: CorporationUpdateRequest):
    """Update corporation fields."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, company_name FROM corporate_sponsors WHERE id::text = $1 OR sponsor_code = $1",
            corp_id,
        )
        if not row:
            raise HTTPException(404, f"Corporation not found: {corp_id}")

        jsonb_cols = {"settings", "corp_admin_permissions"}
        sets = []
        params = []
        idx = 1
        for col, val in body.fields.items():
            if col in ("id", "created_at"):
                continue
            if col in jsonb_cols:
                sets.append(f"{col} = ${idx}::jsonb")
                params.append(json.dumps(val))
            else:
                sets.append(f"{col} = ${idx}")
                params.append(val)
            idx += 1

        if not sets:
            return {"status": "no_changes"}

        params.append(row["id"])
        await conn.execute(
            f"UPDATE corporate_sponsors SET {', '.join(sets)} WHERE id = ${idx}",
            *params,
        )

        logger.info("Access Control: updated corporation %s — fields: %s",
                     row["company_name"], list(body.fields.keys()))

    return {"status": "updated", "company_name": row["company_name"], "fields_updated": list(body.fields.keys())}
