"""
Corporate Command API — CORP_ADMIN dashboard for managing corporate employees.
Prefix: /api/corp
Auth: CORP_ADMIN or ADMIN roles.
"""

import asyncio
import csv
import hashlib
import io
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    from app.services.api_server import get_current_user
except ImportError:
    from backend.app.services.api_server import get_current_user

logger = logging.getLogger("nate.corporate_command")


async def require_corp_admin(user: Dict = Depends(get_current_user)) -> Dict:
    """Require CORP_ADMIN or ADMIN role."""
    if user.get("role") not in ("CORP_ADMIN", "ADMIN"):
        raise HTTPException(403, "Corporate admin access required")
    return user


def _get_company_id(user: Dict) -> Optional[str]:
    """Extract and validate company_id. ADMIN with no company sees all companies."""
    company_id = user.get("company_id") or (user.get("profile_data") or {}).get("company_id")
    if not company_id and user.get("role") != "ADMIN":
        raise HTTPException(403, "No company association")
    return company_id if company_id else None


router = APIRouter(
    prefix="/api/corp",
    tags=["corporate-command"],
)


def _company_filter_sql(company_id: Optional[str], param_idx: int = 1, alias: str = "users") -> tuple[str, list]:
    """Build WHERE clause for company scope. Returns (clause, params)."""
    if company_id is None:
        return f" ({alias}.company_id IS NOT NULL OR ({alias}.profile_data->>'company_id') IS NOT NULL AND ({alias}.profile_data->>'company_id') != '')", []
    return (
        f" ({alias}.company_id = ${param_idx}::uuid OR {alias}.profile_data->>'company_id' = ${param_idx + 1})"
        ,
        [company_id, company_id],
    )


EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
MAX_HASH_WORKERS = 20
MAX_BULK_ROWS = 10_000
PLAN_TOKENS = {"TRIAL": 10_000, "STANDARD": 50_000, "TOP_TIER": 200_000, "COACH_ONLY": 0}
PLAN_TIERS = {
    "TRIAL": ("STANDARD", "TRIAL", "TRIAL_ACTIVE"),
    "STANDARD": ("STANDARD", "STANDARD", "ACTIVE"),
    "TOP_TIER": ("TOP", "TOP_TIER", "ACTIVE"),
    "COACH_ONLY": ("STANDARD", "COACH_ONLY", "ACTIVE"),
}
VALID_PLANS = set(PLAN_TOKENS.keys())


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}:{hashed.hex()}"


# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------


class CoachAssignmentCreate(BaseModel):
    coach_id: str


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "corporate_command"}


@router.get(
    "/roster",
)
async def get_roster(
    request: Request,
    user: Dict = Depends(require_corp_admin),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated list of employees for the company."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)

    clause, params = _company_filter_sql(company_id, 1)
    base = f"""
        SELECT username, role, COALESCE(name, profile_data->>'name') as name,
               COALESCE(email, profile_data->>'email') as email,
               subscription_status, COALESCE(token_balance, 0) as token_balance,
               COALESCE(last_login::text, profile_data->>'last_login') as last_login
        FROM users
        WHERE role = 'CLIENT' AND {clause.strip()}
    """
    count_sql = f"SELECT COUNT(*) FROM users WHERE role = 'CLIENT' AND {clause.strip()}"
    search_clause = ""
    if search and search.strip():
        search_clause = " AND (LOWER(username) LIKE $%d OR LOWER(COALESCE(name, profile_data->>'name')) LIKE $%d OR LOWER(COALESCE(email, profile_data->>'email')) LIKE $%d)" % (
            len(params) + 1, len(params) + 2, len(params) + 3
        )
        s = f"%{search.strip().lower()}%"
        params.extend([s, s, s])

    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(count_sql + search_clause, *params)
            rows = await conn.fetch(
                base + search_clause + " ORDER BY username LIMIT $%d OFFSET $%d"
                % (len(params) + 1, len(params) + 2),
                *(params + [limit, offset]),
            )
    except Exception as e:
        logger.warning("corp_roster: query failed: %s", e)
        raise HTTPException(500, "Database error")

    return {
        "items": [
            {
                "username": r["username"],
                "role": r["role"],
                "name": r["name"],
                "email": r["email"],
                "subscription_status": r["subscription_status"],
                "token_balance": r["token_balance"],
                "last_login": r["last_login"],
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/roster/{username}",
)
async def get_roster_detail(
    request: Request,
    username: str,
    user: Dict = Depends(require_corp_admin),
):
    """Single employee detail with usage stats."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)

    clause, params = _company_filter_sql(company_id, 2)
    params = [username] + params

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT username, role, COALESCE(name, profile_data->>'name') as name,
                       COALESCE(email, profile_data->>'email') as email,
                       subscription_status, COALESCE(token_balance, 0) as token_balance,
                       COALESCE(last_login::text, profile_data->>'last_login') as last_login,
                       COALESCE(login_count, 0) as login_count,
                       profile_data->>'department' as department,
                       id
                FROM users
                WHERE username = $1 AND role = 'CLIENT' AND {clause.strip()}
                """,
                *params,
            )
            if not row:
                raise HTTPException(404, "Employee not found")

            uid = row["id"]
            tokens_used = await conn.fetchval(
                """SELECT COALESCE(SUM(ABS(amount)), 0)::bigint FROM token_transactions
                   WHERE username = $1 AND action IN ('deduct', 'usage')""",
                username,
            )
            sessions_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE user_id = $1::uuid",
                str(uid),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("corp_roster_detail: query failed: %s", e)
        raise HTTPException(500, "Database error")

    return {
        "username": row["username"],
        "role": row["role"],
        "name": row["name"],
        "email": row["email"],
        "subscription_status": row["subscription_status"],
        "token_balance": row["token_balance"],
        "last_login": row["last_login"],
        "login_count": row["login_count"],
        "department": row["department"],
        "tokens_used": tokens_used or 0,
        "sessions_count": sessions_count or 0,
    }


@router.post(
    "/roster/deactivate/{username}",
)
async def deactivate_employee(
    request: Request,
    username: str,
    user: Dict = Depends(require_corp_admin),
):
    """Set subscription_status = SUSPENDED."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required for this action")

    clause, params = _company_filter_sql(company_id, 2)
    params = [username] + params

    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE users SET subscription_status = 'SUSPENDED'
                WHERE username = $1 AND role = 'CLIENT' AND {clause.strip()}
                """,
                *params,
            )
    except Exception as e:
        logger.warning("corp_deactivate: %s", e)
        raise HTTPException(500, "Database error")

    if result == "UPDATE 0":
        raise HTTPException(404, "Employee not found or not in your company")

    return {"status": "ok", "username": username, "subscription_status": "SUSPENDED"}


@router.post(
    "/roster/reactivate/{username}",
)
async def reactivate_employee(
    request: Request,
    username: str,
    user: Dict = Depends(require_corp_admin),
):
    """Set subscription_status = ACTIVE."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required for this action")

    clause, params = _company_filter_sql(company_id, 2)
    params = [username] + params

    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE users SET subscription_status = 'ACTIVE'
                WHERE username = $1 AND role = 'CLIENT' AND {clause.strip()}
                """,
                *params,
            )
    except Exception as e:
        logger.warning("corp_reactivate: %s", e)
        raise HTTPException(500, "Database error")

    if result == "UPDATE 0":
        raise HTTPException(404, "Employee not found or not in your company")

    return {"status": "ok", "username": username, "subscription_status": "ACTIVE"}


@router.post(
    "/roster/reset-password/{username}",
)
async def reset_employee_password(
    request: Request,
    username: str,
    user: Dict = Depends(require_corp_admin),
):
    """Generate new temp password and update password_hash."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required for this action")

    clause, params = _company_filter_sql(company_id, 2)
    params = [username] + params

    temp_password = secrets.token_urlsafe(12)
    pw_hash = _hash_password(temp_password)

    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE users SET password_hash = $1, updated_at = NOW()
                WHERE username = $2 AND role = 'CLIENT' AND {clause.strip()}
                """,
                pw_hash,
                *params,
            )
    except Exception as e:
        logger.warning("corp_reset_password: %s", e)
        raise HTTPException(500, "Database error")

    if result == "UPDATE 0":
        raise HTTPException(404, "Employee not found or not in your company")

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE users SET profile_data = jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb),
                       '{force_password_reset}', 'true'::jsonb
                   ) WHERE username = $1""",
                username,
            )
    except Exception:
        pass

    return {"status": "ok", "username": username, "message": "Password reset. User must set new password on next login."}


@router.get(
    "/template/download",
)
async def download_template(user: Dict = Depends(require_corp_admin)):
    """Return CSV template with headers."""
    headers = [
        "name",
        "email",
        "username",
        "password",
        "plan",
        "department",
        "coach_username",
        "phone",
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerow(["Example Name", "example@company.com", "example_user", "TempPass123!", "TRIAL", "Engineering", "CoachN", ""])
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=corporate_import_template.csv"},
    )


@router.post(
    "/bulk-import",
)
async def bulk_import(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Query(False),
    user: Dict = Depends(require_corp_admin),
):
    """Import employees from CSV. Set dry_run=true to validate only."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required for bulk import")

    pool = request.app.state.db_pool
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be a .csv")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV has no header row")

    required = {"name", "email", "username", "password"}
    headers = {h.strip().lower() for h in reader.fieldnames}
    missing = required - headers
    if missing:
        raise HTTPException(400, f"Missing required columns: {', '.join(sorted(missing))}")

    rows = []
    for i, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        row["_line"] = i
        rows.append(row)

    if not rows:
        raise HTTPException(400, "CSV is empty (no data rows)")

    if len(rows) > MAX_BULK_ROWS:
        raise HTTPException(400, f"Maximum {MAX_BULK_ROWS} rows per import. Got {len(rows):,}")

    errors = []
    for row in rows:
        line = row["_line"]
        name = row.get("name", "")
        email = row.get("email", "")
        username = row.get("username", "")
        password = row.get("password", "")
        plan = (row.get("plan", "") or "TRIAL").upper()

        if not name:
            errors.append({"line": line, "field": "name", "error": "Name is required"})
        if not email:
            errors.append({"line": line, "field": "email", "error": "Email is required"})
        elif not EMAIL_RE.match(email):
            errors.append({"line": line, "field": "email", "error": f"Invalid email: {email}"})
        if not username:
            errors.append({"line": line, "field": "username", "error": "Username is required"})
        if not password:
            errors.append({"line": line, "field": "password", "error": "Password is required"})
        elif len(password) < 6:
            errors.append({"line": line, "field": "password", "error": "Password must be at least 6 characters"})
        if plan not in VALID_PLANS:
            errors.append({"line": line, "field": "plan", "error": f"Invalid plan. Valid: {', '.join(sorted(VALID_PLANS))}"})

    if errors:
        return {
            "status": "validation_failed",
            "dry_run": dry_run,
            "total_rows": len(rows),
            "imported": 0,
            "errors": errors[:100],
        }

    batch_id = str(uuid.uuid4())
    sem = asyncio.Semaphore(MAX_HASH_WORKERS)

    async def _hash_one(pw: str) -> str:
        async with sem:
            return await asyncio.to_thread(_hash_password, pw)

    hashes = await asyncio.gather(*[_hash_one(row["password"]) for row in rows])

    coach_usernames = {r.get("coach_username", "").strip() for r in rows if r.get("coach_username", "").strip()}
    coach_hw_map = {}
    if coach_usernames:
        async with pool.acquire() as conn:
            coach_rows = await conn.fetch(
                "SELECT username, hardware_id FROM users WHERE role = 'COACH' AND username = ANY($1::text[])",
                list(coach_usernames),
            )
            coach_hw_map = {r["username"]: r["hardware_id"] for r in coach_rows}

    if dry_run:
        return {
            "status": "dry_run_passed",
            "batch_id": batch_id,
            "dry_run": True,
            "total_rows": len(rows),
            "imported": 0,
        }

    imported = 0
    insert_errors = []

    async with pool.acquire() as conn:
        for i, (row, pw_hash) in enumerate(zip(rows, hashes)):
            plan_key = (row.get("plan", "") or "TRIAL").upper()
            tier, plan_name, sub_status = PLAN_TIERS.get(plan_key, PLAN_TIERS["TRIAL"])
            tokens = PLAN_TOKENS.get(plan_key, 10_000)
            hw_id = f"CORP_{batch_id[:8]}_{i:05d}"

            coach_u = (row.get("coach_username", "") or "").strip() or "CoachN"
            coach_hw = coach_hw_map.get(coach_u, "COACH_COACHN_ID")
            now_str = datetime.now(timezone.utc).isoformat()

            profile = {
                "role": "CLIENT",
                "name": row["name"],
                "email": row["email"],
                "username": row["username"],
                "hardware_id": hw_id,
                "tier": tier,
                "subscription_plan": plan_name,
                "subscription_status": sub_status,
                "token_balance": tokens,
                "coach_id": coach_hw,
                "assigned_coach": coach_u,
                "assigned_coach_id": coach_hw,
                "company_id": company_id,
                "consent_version": "v13.0_2026",
                "joined_date": now_str,
                "created_at": now_str,
                "import_batch_id": batch_id,
                "import_source": "corp_bulk",
                "token_usage_today": 0,
                "token_usage_month": 0,
            }
            if row.get("department", "").strip():
                profile["department"] = row["department"].strip()
            if row.get("phone", "").strip():
                profile["phone"] = row["phone"].strip()

            try:
                await conn.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, role, tier, name, email,
                        hardware_id, consent_version, subscription_status,
                        profile_data, token_balance, company_id, updated_at
                    ) VALUES ($1, $2, 'CLIENT', $3, $4, $5, $6, 'v13.0_2026', $7, $8::jsonb, $9, $10::uuid, NOW())
                    """,
                    row["username"],
                    pw_hash,
                    tier,
                    row["name"],
                    row["email"],
                    hw_id,
                    sub_status,
                    json.dumps(profile, default=str),
                    tokens,
                    company_id,
                )
                imported += 1
            except Exception as e:
                insert_errors.append({"line": row["_line"], "username": row["username"], "error": str(e)[:200]})

    return {
        "status": "import_complete",
        "batch_id": batch_id,
        "dry_run": False,
        "total_rows": len(rows),
        "imported": imported,
        "errors": insert_errors[:100],
    }


@router.get(
    "/usage-dashboard",
)
async def usage_dashboard(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Aggregate stats: total_employees, active_users (30d), tokens_consumed, total_sessions."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)

    clause, params = _company_filter_sql(company_id, 1)
    cutover = datetime.now(timezone.utc) - timedelta(days=30)

    try:
        async with pool.acquire() as conn:
            total_employees = await conn.fetchval(
                f"SELECT COUNT(*) FROM users WHERE role = 'CLIENT' AND {clause.strip()}",
                *params,
            )
            active_users = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM users
                WHERE role = 'CLIENT' AND {clause.strip()}
                AND (profile_data->>'last_login')::timestamptz >= $%d::timestamptz
                """
                % (len(params) + 1,),
                *(params + [cutover]),
            )
            usernames = await conn.fetch(
                f"SELECT username FROM users WHERE role = 'CLIENT' AND {clause.strip()}",
                *params,
            )
    except Exception as e:
        logger.warning("corp_usage_dashboard: %s", e)
        raise HTTPException(500, "Database error")

    names = [r["username"] for r in usernames]
    if not names:
        return {
            "total_employees": 0,
            "active_users": 0,
            "total_tokens_consumed": 0,
            "total_sessions": 0,
        }

    try:
        async with pool.acquire() as conn:
            tokens_consumed = await conn.fetchval(
                """SELECT COALESCE(SUM(ABS(amount)), 0)::bigint FROM token_transactions
                   WHERE username = ANY($1::text[]) AND action IN ('deduct', 'usage')""",
                names,
            )
            total_sessions = await conn.fetchval(
                """SELECT COUNT(*) FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE u.username = ANY($1::text[])""",
                names,
            )
    except Exception as e:
        logger.warning("corp_usage_dashboard: %s", e)
        tokens_consumed = 0
        total_sessions = 0

    return {
        "total_employees": total_employees or 0,
        "active_users": active_users or 0,
        "total_tokens_consumed": tokens_consumed or 0,
        "total_sessions": total_sessions or 0,
    }


@router.get(
    "/usage-dashboard/departments",
)
async def usage_dashboard_departments(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Group by department: user_count, active_count, tokens_consumed."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)

    clause, params = _company_filter_sql(company_id, 1)
    cutover = datetime.now(timezone.utc) - timedelta(days=30)
    base_param_count = len(params)
    params.append(cutover)

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT COALESCE(users.profile_data->>'department', 'Unassigned') as department,
                       COUNT(*) as user_count,
                       COUNT(*) FILTER (WHERE (profile_data->>'last_login')::timestamptz >= ${base_param_count + 1}::timestamptz) as active_count
                FROM users
                WHERE role = 'CLIENT' AND {clause.strip()}
                GROUP BY 1
                ORDER BY 1
                """,
                *params,
            )
            names_by_dept = await conn.fetch(
                f"""
                SELECT COALESCE(users.profile_data->>'department', 'Unassigned') as department,
                       array_agg(username) as usernames
                FROM users
                WHERE role = 'CLIENT' AND {clause.strip()}
                GROUP BY 1
                """,
                *params[:base_param_count],
            )
    except Exception as e:
        logger.warning("corp_usage_departments: %s", e)
        raise HTTPException(500, "Database error")

    dept_users = {r["department"]: r["usernames"] for r in names_by_dept}
    all_usernames = [u for users in dept_users.values() for u in users]
    tokens_by_user = {}
    if all_usernames:
        try:
            async with pool.acquire() as conn2:
                tx_rows = await conn2.fetch(
                    """SELECT username, COALESCE(SUM(ABS(amount)), 0)::bigint as total
                       FROM token_transactions
                       WHERE username = ANY($1::text[]) AND action IN ('deduct', 'usage')
                       GROUP BY username""",
                    all_usernames,
                )
                tokens_by_user = {r["username"]: r["total"] for r in tx_rows}
        except Exception as e:
            logger.warning("corp_usage_departments tokens: %s", e)

    result = []
    for r in rows:
        dept = r["department"]
        usernames = dept_users.get(dept, [])
        tokens = sum(tokens_by_user.get(u, 0) for u in usernames)
        result.append(
            {
                "department": dept,
                "user_count": r["user_count"],
                "active_count": r["active_count"],
                "tokens_consumed": tokens,
            }
        )

    return {"departments": result}


@router.get(
    "/coach-assignments",
)
async def get_coach_assignments(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """List coach assignments for the company."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, coach_id, entity_type, entity_id, is_primary, assigned_at, assigned_by
                   FROM coach_assignments
                   WHERE entity_type = 'company' AND entity_id = $1""",
                company_id,
            )
    except Exception as e:
        logger.warning("corp_coach_assignments: %s", e)
        raise HTTPException(500, "Database error")

    return {
        "assignments": [
            {
                "id": str(r["id"]),
                "coach_id": r["coach_id"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "is_primary": r["is_primary"],
                "assigned_at": r["assigned_at"].isoformat() if r["assigned_at"] else None,
                "assigned_by": r["assigned_by"],
            }
            for r in rows
        ]
    }


@router.post(
    "/coach-assignments",
)
async def create_coach_assignment(
    request: Request,
    body: CoachAssignmentCreate,
    user: Dict = Depends(require_corp_admin),
):
    """Assign a coach to the company."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    admin_name = user.get("username", "unknown")
    pool = request.app.state.db_pool

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO coach_assignments (coach_id, entity_type, entity_id, is_primary, assigned_by)
                   VALUES ($1, 'company', $2, FALSE, $3)""",
                body.coach_id,
                company_id,
                admin_name,
            )
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(409, "Coach already assigned to this company")
        logger.warning("corp_coach_assign_create: %s", e)
        raise HTTPException(500, "Database error")

    return {"status": "ok", "coach_id": body.coach_id, "entity_id": company_id}


@router.delete(
    "/coach-assignments/{assignment_id}",
)
async def delete_coach_assignment(
    request: Request,
    assignment_id: str,
    user: Dict = Depends(require_corp_admin),
):
    """Remove a coach assignment."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                """DELETE FROM coach_assignments
                   WHERE id = $1::uuid AND entity_type = 'company' AND entity_id = $2""",
                assignment_id,
                company_id,
            )
    except Exception as e:
        logger.warning("corp_coach_assign_delete: %s", e)
        raise HTTPException(500, "Database error")

    if result == "DELETE 0":
        raise HTTPException(404, "Assignment not found")

    return {"status": "ok", "assignment_id": assignment_id}


@router.get(
    "/billing/overview",
)
async def billing_overview(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Corporate sponsor billing overview."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, company_name, discount_type, discount_value, max_employees,
                          current_employees, stripe_customer_id
                   FROM corporate_sponsors WHERE id = $1::uuid AND active = TRUE""",
                company_id,
            )
    except Exception as e:
        logger.warning("corp_billing_overview: %s", e)
        raise HTTPException(500, "Database error")

    if not row:
        raise HTTPException(404, "Company not found or inactive")

    return {
        "company_name": row["company_name"],
        "discount_type": row["discount_type"],
        "discount_value": row["discount_value"],
        "max_employees": row["max_employees"],
        "current_employees": row["current_employees"],
        "stripe_customer_id": row["stripe_customer_id"],
    }


@router.get(
    "/billing/invoices",
)
async def billing_invoices(
    request: Request,
    user: Dict = Depends(require_corp_admin),
    limit: int = Query(20, ge=1, le=100),
):
    """List Stripe invoices for the corporate customer."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT stripe_customer_id FROM corporate_sponsors WHERE id = $1::uuid",
                company_id,
            )
    except Exception as e:
        logger.warning("corp_billing_invoices: %s", e)
        raise HTTPException(500, "Database error")

    stripe_customer_id = row["stripe_customer_id"] if row else None
    if not stripe_customer_id:
        return {"invoices": [], "message": "No Stripe customer linked to this company"}

    try:
        import stripe

        stripe.api_key = __import__("os").environ.get("STRIPE_SECRET_KEY")
        if not stripe.api_key:
            return {"invoices": [], "message": "Stripe not configured"}

        invoices = stripe.Invoice.list(customer=stripe_customer_id, limit=limit)
        return {
            "invoices": [
                {
                    "id": inv.id,
                    "amount_due": inv.get("amount_due", 0),
                    "status": inv.get("status"),
                    "created": inv.get("created"),
                    "due_date": inv.get("due_date"),
                }
                for inv in invoices.get("data", [])
            ],
        }
    except Exception as e:
        logger.warning("corp_billing_invoices stripe: %s", e)
        return {"invoices": [], "message": str(e)}


@router.get(
    "/engagement-report",
)
async def engagement_report(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """CSV export: username, name, email, department, last_login, login_count, sessions_count, tokens_used."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)

    clause, params = _company_filter_sql(company_id, 1, alias="u")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT u.username,
                       u.profile_data->>'name' as name,
                       u.profile_data->>'email' as email,
                       u.profile_data->>'department' as department,
                       u.profile_data->>'last_login' as last_login,
                       COALESCE((u.profile_data->>'login_count')::int, 0) as login_count
                FROM users u
                WHERE u.role = 'CLIENT' AND {clause.strip()}
                ORDER BY u.username
                """,
                *params,
            )
    except Exception as e:
        logger.warning("corp_engagement_report: %s", e)
        raise HTTPException(500, "Database error")

    usernames = [r["username"] for r in rows]
    sessions_map = {}
    tokens_map = {}
    if usernames:
        async with pool.acquire() as conn:
            sess_rows = await conn.fetch(
                """SELECT u.username, COUNT(s.id)::int as cnt
                   FROM users u LEFT JOIN sessions s ON s.user_id = u.id
                   WHERE u.username = ANY($1::text[])
                   GROUP BY u.username""",
                usernames,
            )
            sessions_map = {r["username"]: r["cnt"] for r in sess_rows}

            tx_rows = await conn.fetch(
                """SELECT username, COALESCE(SUM(ABS(amount)), 0)::bigint as total
                   FROM token_transactions WHERE username = ANY($1::text[])
                   AND action IN ('deduct', 'usage') GROUP BY username""",
                usernames,
            )
            tokens_map = {r["username"]: r["total"] for r in tx_rows}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["username", "name", "email", "department", "last_login", "login_count", "sessions_count", "tokens_used"])
    for r in rows:
        w.writerow([
            r["username"],
            r["name"] or "",
            r["email"] or "",
            r["department"] or "",
            r["last_login"] or "",
            r["login_count"] or 0,
            sessions_map.get(r["username"], 0),
            tokens_map.get(r["username"], 0),
        ])
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=corporate_engagement_report.csv"},
    )


# =============================================================================
# ANALYTICS — Company-Wide Wellness
# =============================================================================

PERIOD_INTERVALS = {
    "30d": "30 days",
    "60d": "60 days",
    "90d": "90 days",
    "6m": "180 days",
    "12m": "365 days",
}


@router.get("/analytics/wellness")
async def analytics_wellness(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Aggregate wellness metrics across all company employees (no individual data)."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)
    clause, params = _company_filter_sql(company_id, 1)

    try:
        async with pool.acquire() as conn:
            employee_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM users WHERE role = 'CLIENT' AND {clause.strip()}",
                *params,
            )
            emp_ids = await conn.fetch(
                f"SELECT id, hardware_id FROM users WHERE role = 'CLIENT' AND {clause.strip()}",
                *params,
            )

            if not emp_ids:
                return {
                    "employee_count": 0,
                    "employees_with_data": 0,
                    "coherence": {"avg": 0, "trend": "neutral"},
                    "gap": {"avg": 0},
                    "quantum": {"avg": 0},
                    "anxiety": {"avg": 0},
                    "stress": {"avg": 0},
                    "engagement": {"avg": 0},
                    "mood_distribution": {},
                    "risk_distribution": {},
                }

            uid_list = [r["id"] for r in emp_ids]
            hw_list = [r["hardware_id"] for r in emp_ids]

            metrics = await conn.fetchrow(
                """SELECT
                    AVG(cm.c_emo) as avg_coherence,
                    AVG(COALESCE((cm.nevedal_state->>'gap')::float, 0)) as avg_gap,
                    AVG(COALESCE((cm.nevedal_state->>'quantum')::float, 0)) as avg_quantum,
                    AVG(COALESCE(cm.anxiety_level, 0)) as avg_anxiety,
                    AVG(COALESCE(cm.stress_level, 0)) as avg_stress,
                    AVG(COALESCE(cm.engagement, 0)) as avg_engagement,
                    COUNT(DISTINCT cm.hardware_id) as with_data
                FROM client_metrics cm
                WHERE cm.hardware_id = ANY($1::text[])""",
                hw_list,
            )

            mood_rows = await conn.fetch(
                """SELECT COALESCE(cm.mood_current, 'unknown') as mood, COUNT(*) as cnt
                FROM client_metrics cm
                WHERE cm.hardware_id = ANY($1::text[])
                GROUP BY 1""",
                hw_list,
            )

            risk_rows = await conn.fetch(
                """SELECT
                    CASE
                        WHEN COALESCE(cm.anxiety_level, 0) > 0.7 OR COALESCE(cm.stress_level, 0) > 0.7 THEN 'high'
                        WHEN COALESCE(cm.anxiety_level, 0) > 0.4 OR COALESCE(cm.stress_level, 0) > 0.4 THEN 'medium'
                        ELSE 'low'
                    END as risk_level,
                    COUNT(*) as cnt
                FROM client_metrics cm
                WHERE cm.hardware_id = ANY($1::text[])
                GROUP BY 1""",
                hw_list,
            )

            prev_coherence = await conn.fetchval(
                """SELECT AVG(nm.c_emo)
                FROM nevedal_metrics nm
                WHERE nm.user_id = ANY($1::uuid[])
                  AND nm.recorded_at >= NOW() - INTERVAL '60 days'
                  AND nm.recorded_at < NOW() - INTERVAL '30 days'""",
                uid_list,
            )

            session_outcomes = await conn.fetch(
                """SELECT cs.coach_id,
                          COUNT(*) as sessions,
                          AVG(COALESCE((cs.session_data->>'avg_c_emo')::float, 0)) as avg_coherence,
                          COUNT(CASE WHEN cs.nate_summary IS NOT NULL AND cs.nate_summary != '' THEN 1 END) as summarized
                   FROM coaching_sessions cs
                   WHERE cs.client_id = ANY($1::text[])
                     AND cs.created_at > NOW() - INTERVAL '30 days'
                     AND lower(coalesce(cs.session_type, '')) != 'consultation'
                     AND cs.client_id NOT LIKE 'consultation_%'
                   GROUP BY cs.coach_id""",
                hw_list,
            )
    except Exception as e:
        logger.warning("analytics_wellness: %s", e)
        raise HTTPException(500, "Database error")

    avg_coh = float(metrics["avg_coherence"] or 0) if metrics else 0
    prev_coh = float(prev_coherence or 0)
    trend = "improving" if avg_coh > prev_coh + 0.02 else ("declining" if avg_coh < prev_coh - 0.02 else "stable")

    coaching_summary = {
        "total_sessions_30d": sum(r["sessions"] for r in session_outcomes),
        "sessions_with_summary": sum(r["summarized"] for r in session_outcomes),
        "avg_session_coherence": round(
            sum(float(r["avg_coherence"] or 0) * r["sessions"] for r in session_outcomes)
            / max(sum(r["sessions"] for r in session_outcomes), 1),
            3,
        ),
        "by_coach": [
            {
                "coach_id": r["coach_id"],
                "sessions": r["sessions"],
                "avg_coherence": round(float(r["avg_coherence"] or 0), 3),
                "summarized": r["summarized"],
            }
            for r in session_outcomes
        ],
    }

    return {
        "employee_count": employee_count or 0,
        "employees_with_data": int(metrics["with_data"] or 0) if metrics else 0,
        "coherence": {"avg": round(avg_coh, 3), "trend": trend},
        "gap": {"avg": round(float(metrics["avg_gap"] or 0), 3) if metrics else 0},
        "quantum": {"avg": round(float(metrics["avg_quantum"] or 0), 3) if metrics else 0},
        "anxiety": {"avg": round(float(metrics["avg_anxiety"] or 0), 3) if metrics else 0},
        "stress": {"avg": round(float(metrics["avg_stress"] or 0), 3) if metrics else 0},
        "engagement": {"avg": round(float(metrics["avg_engagement"] or 0), 3) if metrics else 0},
        "mood_distribution": {r["mood"]: r["cnt"] for r in mood_rows},
        "risk_distribution": {r["risk_level"]: r["cnt"] for r in risk_rows},
        "coaching_sessions": coaching_summary,
    }


# =============================================================================
# ANALYTICS — Trend Data (time-series for Chart.js)
# =============================================================================

@router.get("/analytics/trends")
async def analytics_trends(
    request: Request,
    user: Dict = Depends(require_corp_admin),
    period: str = Query("30d", regex="^(30d|60d|90d|6m|12m)$"),
):
    """Time-series trend data with three lines: Nate<>Employees, Coaches<>Employees, Nate<>Coaches."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)
    clause, params = _company_filter_sql(company_id, 1)
    interval_str = PERIOD_INTERVALS.get(period, "30 days")
    bucket = "day" if period in ("30d", "60d", "90d") else "week"

    try:
        async with pool.acquire() as conn:
            emp_ids = await conn.fetch(
                f"SELECT id FROM users WHERE role = 'CLIENT' AND {clause.strip()}",
                *params,
            )
            coach_ids = await conn.fetch(
                f"""SELECT DISTINCT u2.id FROM coach_assignments ca
                    JOIN users u2 ON u2.hardware_id = ca.coach_id
                    WHERE ca.entity_type = 'company' AND ca.entity_id = $1""",
                company_id or "00000000-0000-0000-0000-000000000000",
            )

            emp_uids = [r["id"] for r in emp_ids]
            coach_uids = [r["id"] for r in coach_ids]

            if not emp_uids:
                return {"period": period, "bucket": bucket, "nate_employees": [], "coaches_employees": [], "nate_coaches": []}

            nate_emp = await conn.fetch(
                f"""SELECT DATE_TRUNC('{bucket}', nm.recorded_at) as bucket_date,
                           AVG(nm.c_emo) as avg_coherence,
                           COUNT(DISTINCT nm.user_id) as active_users,
                           COUNT(CASE WHEN nm.cee_window THEN 1 END) as cee_events
                    FROM nevedal_metrics nm
                    WHERE nm.user_id = ANY($1::uuid[])
                      AND nm.recorded_at >= NOW() - $2::interval
                    GROUP BY 1 ORDER BY 1""",
                emp_uids, timedelta(days=int(interval_str.split()[0])),
            )

            coach_emp_rows = []
            if coach_uids:
                coach_emp_rows = await conn.fetch(
                    f"""SELECT DATE_TRUNC('{bucket}', s.started_at) as bucket_date,
                               COUNT(DISTINCT s.id) as session_count,
                               AVG(nm.c_emo) as avg_coherence
                        FROM sessions s
                        JOIN nevedal_metrics nm ON nm.session_id = s.id
                        WHERE s.user_id = ANY($1::uuid[])
                          AND s.coach_id = ANY($2::uuid[])
                          AND s.started_at >= NOW() - $3::interval
                        GROUP BY 1 ORDER BY 1""",
                    emp_uids, coach_uids,
                    timedelta(days=int(interval_str.split()[0])),
                )

            nate_coach_rows = []
            if coach_uids:
                nate_coach_rows = await conn.fetch(
                    f"""SELECT DATE_TRUNC('{bucket}', nm.recorded_at) as bucket_date,
                               AVG(nm.c_emo) as avg_coherence,
                               COUNT(DISTINCT nm.user_id) as active_coaches
                        FROM nevedal_metrics nm
                        WHERE nm.user_id = ANY($1::uuid[])
                          AND nm.recorded_at >= NOW() - $2::interval
                        GROUP BY 1 ORDER BY 1""",
                    coach_uids, timedelta(days=int(interval_str.split()[0])),
                )
    except Exception as e:
        logger.warning("analytics_trends: %s", e)
        raise HTTPException(500, "Database error")

    def _fmt(rows, extra_keys=None):
        result = []
        for r in rows:
            entry = {"date": r["bucket_date"].isoformat() if r["bucket_date"] else None}
            for k in (extra_keys or ["avg_coherence"]):
                val = r.get(k)
                entry[k] = round(float(val), 3) if val is not None else 0
            if "active_users" in dict(r):
                entry["active_users"] = int(r["active_users"] or 0)
            if "active_coaches" in dict(r):
                entry["active_coaches"] = int(r["active_coaches"] or 0)
            if "session_count" in dict(r):
                entry["session_count"] = int(r["session_count"] or 0)
            if "cee_events" in dict(r):
                entry["cee_events"] = int(r["cee_events"] or 0)
            result.append(entry)
        return result

    return {
        "period": period,
        "bucket": bucket,
        "nate_employees": _fmt(nate_emp, ["avg_coherence"]),
        "coaches_employees": _fmt(coach_emp_rows, ["avg_coherence"]),
        "nate_coaches": _fmt(nate_coach_rows, ["avg_coherence"]),
    }


# =============================================================================
# ANALYTICS — Coach Team Performance
# =============================================================================

@router.get("/analytics/coach-team")
async def analytics_coach_team(
    request: Request,
    user: Dict = Depends(require_corp_admin),
    period: str = Query("30d", regex="^(30d|60d|90d|6m|12m)$"),
):
    """Aggregate coach team performance for all coaches assigned to the company."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)
    interval_str = PERIOD_INTERVALS.get(period, "30 days")

    if not company_id:
        return {"total_coaches": 0, "total_sessions": 0, "avg_client_coherence": 0, "total_cee_events": 0, "avg_client_engagement": 0}

    try:
        async with pool.acquire() as conn:
            interval_delta = timedelta(days=int(interval_str.split()[0]))

            coach_rows = await conn.fetch(
                """SELECT DISTINCT ca.coach_id, u.id as coach_uid,
                          COALESCE(u.name, u.profile_data->>'name') as coach_name
                   FROM coach_assignments ca
                   JOIN users u ON u.hardware_id = ca.coach_id
                   WHERE ca.entity_type = 'company' AND ca.entity_id = $1""",
                company_id,
            )

            if not coach_rows:
                return {"total_coaches": 0, "total_sessions": 0, "avg_client_coherence": 0, "total_cee_events": 0, "avg_client_engagement": 0}

            coach_uids = [r["coach_uid"] for r in coach_rows]

            agg = await conn.fetchrow(
                """SELECT
                    COUNT(DISTINCT s.id) as total_sessions,
                    AVG(nm.c_emo) as avg_coherence,
                    COUNT(CASE WHEN nm.cee_window THEN 1 END) as total_cee,
                    AVG(cm.engagement) as avg_engagement
                FROM sessions s
                LEFT JOIN nevedal_metrics nm ON nm.session_id = s.id
                LEFT JOIN client_metrics cm ON cm.hardware_id = (
                    SELECT hardware_id FROM users WHERE id = s.user_id LIMIT 1
                )
                WHERE s.coach_id = ANY($1::uuid[])
                  AND s.started_at >= NOW() - $2::interval""",
                coach_uids, interval_delta,
            )
    except Exception as e:
        logger.warning("analytics_coach_team: %s", e)
        raise HTTPException(500, "Database error")

    return {
        "total_coaches": len(coach_rows),
        "total_sessions": int(agg["total_sessions"] or 0) if agg else 0,
        "avg_client_coherence": round(float(agg["avg_coherence"] or 0), 3) if agg else 0,
        "total_cee_events": int(agg["total_cee"] or 0) if agg else 0,
        "avg_client_engagement": round(float(agg["avg_engagement"] or 0), 3) if agg else 0,
    }


# =============================================================================
# ANALYTICS — Coach ROI & Attunement
# =============================================================================

@router.get("/analytics/coach-roi")
async def analytics_coach_roi(
    request: Request,
    user: Dict = Depends(require_corp_admin),
    period: str = Query("30d", regex="^(30d|60d|90d|6m|12m)$"),
):
    """Per-coach ROI with attunement index. No employee-level data exposed."""
    pool = request.app.state.db_pool
    company_id = _get_company_id(user)
    interval_str = PERIOD_INTERVALS.get(period, "30 days")

    if not company_id:
        return {"coaches": []}

    try:
        async with pool.acquire() as conn:
            interval_delta = timedelta(days=int(interval_str.split()[0]))
            total_days = int(interval_str.split()[0])

            coach_rows = await conn.fetch(
                """SELECT DISTINCT ca.coach_id as hw_id, u.id as coach_uid,
                          COALESCE(u.name, u.profile_data->>'name') as coach_name
                   FROM coach_assignments ca
                   JOIN users u ON u.hardware_id = ca.coach_id
                   WHERE ca.entity_type = 'company' AND ca.entity_id = $1""",
                company_id,
            )

            if not coach_rows:
                return {"coaches": []}

            hierarchy = await conn.fetch(
                "SELECT master_coach_id, assistant_id FROM coach_hierarchy WHERE status = 'active'"
            )
            master_map = {}
            assistant_map = {}
            for h in hierarchy:
                assistant_map[h["assistant_id"]] = h["master_coach_id"]
                master_map.setdefault(h["master_coach_id"], []).append(h["assistant_id"])

            coaches_result = []
            for cr in coach_rows:
                cuid = cr["coach_uid"]
                hw = cr["hw_id"]

                stats = await conn.fetchrow(
                    """SELECT
                        COUNT(DISTINCT s.id) as sessions_count,
                        COUNT(DISTINCT s.user_id) as active_clients,
                        AVG(nm.c_emo) as avg_coherence,
                        COUNT(CASE WHEN nm.cee_window THEN 1 END) as cee_events
                    FROM sessions s
                    LEFT JOIN nevedal_metrics nm ON nm.session_id = s.id
                    WHERE s.coach_id = $1::uuid
                      AND s.started_at >= NOW() - $2::interval""",
                    cuid, interval_delta,
                )

                first_coherence = await conn.fetchval(
                    """SELECT AVG(nm.c_emo)
                    FROM nevedal_metrics nm
                    JOIN sessions s ON s.id = nm.session_id
                    WHERE s.coach_id = $1::uuid
                      AND s.started_at < NOW() - $2::interval
                      AND s.started_at >= NOW() - ($2::interval * 2)""",
                    cuid, interval_delta,
                )

                first_engagement = await conn.fetchval(
                    """SELECT AVG(cm.engagement)
                    FROM client_metrics cm
                    JOIN users u ON u.hardware_id = cm.hardware_id
                    JOIN sessions s ON s.user_id = u.id
                    WHERE s.coach_id = $1::uuid
                      AND s.started_at < NOW() - $2::interval
                      AND s.started_at >= NOW() - ($2::interval * 2)""",
                    cuid, interval_delta,
                )

                curr_engagement = await conn.fetchval(
                    """SELECT AVG(cm.engagement)
                    FROM client_metrics cm
                    JOIN users u ON u.hardware_id = cm.hardware_id
                    JOIN sessions s ON s.user_id = u.id
                    WHERE s.coach_id = $1::uuid
                      AND s.started_at >= NOW() - $2::interval""",
                    cuid, interval_delta,
                )

                nate_score = await conn.fetchval(
                    """SELECT AVG(average_score) FROM coach_nate_progress
                       WHERE coach_id = $1""",
                    hw,
                )

                sessions_count = int(stats["sessions_count"] or 0) if stats else 0
                active_clients = int(stats["active_clients"] or 0) if stats else 0
                avg_coh = float(stats["avg_coherence"] or 0) if stats else 0
                cee = int(stats["cee_events"] or 0) if stats else 0
                first_coh = float(first_coherence or 0)
                coherence_improvement = avg_coh - first_coh

                eng_now = float(curr_engagement or 0)
                eng_before = float(first_engagement or 0)
                engagement_delta = eng_now - eng_before

                cee_rate = (cee / sessions_count) if sessions_count > 0 else 0
                nate_obs = float(nate_score or 0)

                expected_sessions = max(1, (total_days / 7) * active_clients) if active_clients > 0 else max(1, total_days / 7)
                session_consistency = min(1.0, sessions_count / expected_sessions)

                def _norm(val, low=-0.5, high=0.5):
                    return max(0, min(1, (val - low) / (high - low))) if high != low else 0.5

                attunement_index = (
                    0.30 * _norm(coherence_improvement) +
                    0.25 * _norm(engagement_delta) +
                    0.20 * _norm(cee_rate, 0, 3) +
                    0.15 * min(1.0, nate_obs) +
                    0.10 * session_consistency
                )

                role_type = "master" if hw in master_map else ("assistant" if hw in assistant_map else "independent")
                assistants = []
                if hw in master_map:
                    for a_hw in master_map[hw]:
                        a_name = next((c["coach_name"] for c in coach_rows if c["hw_id"] == a_hw), a_hw)
                        assistants.append(a_name)

                coaches_result.append({
                    "coach_id": hw,
                    "coach_name": cr["coach_name"] or hw,
                    "role_type": role_type,
                    "assistants": assistants,
                    "sessions_count": sessions_count,
                    "active_clients": active_clients,
                    "avg_coherence_improvement": round(coherence_improvement, 3),
                    "avg_engagement_delta": round(engagement_delta, 3),
                    "cee_rate_per_session": round(cee_rate, 2),
                    "nate_observation_score": round(nate_obs, 2),
                    "attunement_index": round(attunement_index, 3),
                })

            coaches_result.sort(key=lambda c: c["attunement_index"], reverse=True)
    except Exception as e:
        logger.warning("analytics_coach_roi: %s", e)
        raise HTTPException(500, "Database error")

    return {"coaches": coaches_result}


# =============================================================================
# SETTINGS
# =============================================================================

@router.get("/settings")
async def get_corp_settings(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Get all corporate settings for the company."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT company_name, sponsor_code, discount_type, discount_value,
                       pays_full, max_employees, current_employees, active,
                       stripe_customer_id,
                       COALESCE(platform_tier, 'starter') as platform_tier,
                       COALESCE(platform_fee_cents, 29900) as platform_fee_cents,
                       COALESCE(max_seats, 25) as max_seats,
                       COALESCE(subsidy_percentage, 100) as subsidy_percentage,
                       COALESCE(allowed_employee_tier, 'STANDARD') as allowed_employee_tier,
                       COALESCE(auto_enroll, false) as auto_enroll,
                       COALESCE(settings, '{}'::jsonb) as settings,
                       require_domain, primary_contact_email, primary_contact_phone,
                       industry, logo_url, billing_cycle_day
                FROM corporate_sponsors WHERE id = $1::uuid AND active = TRUE
            """, company_id)
    except Exception as e:
        logger.warning("corp_get_settings: %s", e)
        raise HTTPException(500, "Database error")

    if not row:
        raise HTTPException(404, "Company not found")

    from app.services.stripe_integration import CORPORATE_TIERS, calculate_subsidized_rate

    tier_info = CORPORATE_TIERS.get(row["platform_tier"], CORPORATE_TIERS["starter"])
    subsidy = calculate_subsidized_rate(row["allowed_employee_tier"], row["subsidy_percentage"])

    return {
        "company_name": row["company_name"],
        "sponsor_code": row["sponsor_code"],
        "platform_tier": row["platform_tier"],
        "platform_fee_cents": row["platform_fee_cents"],
        "max_seats": row["max_seats"],
        "tier_features": tier_info.get("features", []),
        "subsidy_percentage": row["subsidy_percentage"],
        "allowed_employee_tier": row["allowed_employee_tier"],
        "subsidy_detail": subsidy,
        "pays_full": row["pays_full"],
        "auto_enroll": row["auto_enroll"],
        "max_employees": row["max_employees"],
        "current_employees": row["current_employees"],
        "stripe_customer_id": row["stripe_customer_id"],
        "require_domain": row["require_domain"],
        "primary_contact_email": row["primary_contact_email"],
        "primary_contact_phone": row["primary_contact_phone"],
        "industry": row["industry"],
        "logo_url": row["logo_url"],
        "billing_cycle_day": row["billing_cycle_day"],
        "settings": row["settings"] if isinstance(row["settings"], dict) else {},
        "discount_type": row["discount_type"],
        "discount_value": row["discount_value"],
    }


@router.put("/settings")
async def update_corp_settings(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Update corporate settings (partial update — only provided fields)."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    body = await request.json()

    ALLOWED_FIELDS = {
        "company_name": "company_name",
        "subsidy_percentage": "subsidy_percentage",
        "allowed_employee_tier": "allowed_employee_tier",
        "auto_enroll": "auto_enroll",
        "require_domain": "require_domain",
        "primary_contact_email": "primary_contact_email",
        "primary_contact_phone": "primary_contact_phone",
        "industry": "industry",
        "logo_url": "logo_url",
        "billing_cycle_day": "billing_cycle_day",
    }

    updates = []
    params = []
    idx = 2

    for key, col in ALLOWED_FIELDS.items():
        if key in body:
            val = body[key]
            if key == "subsidy_percentage":
                val = max(25, min(100, int(val)))
            if key == "allowed_employee_tier" and val not in ("STANDARD", "TOP_TIER"):
                raise HTTPException(400, "allowed_employee_tier must be STANDARD or TOP_TIER")
            if key == "billing_cycle_day":
                val = max(1, min(28, int(val)))
            updates.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1

    if "settings" in body and isinstance(body["settings"], dict):
        updates.append(f"settings = settings || ${idx}::jsonb")
        params.append(json.dumps(body["settings"]))
        idx += 1

    if not updates:
        raise HTTPException(400, "No valid fields to update")

    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE corporate_sponsors SET {', '.join(updates)} WHERE id = $1::uuid",
                company_id, *params,
            )
    except Exception as e:
        logger.warning("corp_update_settings: %s", e)
        raise HTTPException(500, "Database error")

    return {"status": "updated", "fields": list(body.keys())}


@router.get("/settings/payment-methods")
async def get_corp_payment_methods(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """List payment methods on the corporate Stripe customer."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT stripe_customer_id FROM corporate_sponsors WHERE id = $1::uuid AND active = TRUE",
            company_id,
        )

    if not row or not row["stripe_customer_id"]:
        return {"payment_methods": [], "has_customer": False}

    try:
        import stripe
        methods = stripe.PaymentMethod.list(customer=row["stripe_customer_id"], type="card")
        bank_methods = stripe.PaymentMethod.list(customer=row["stripe_customer_id"], type="us_bank_account")
        customer = stripe.Customer.retrieve(row["stripe_customer_id"])
        default_pm = None
        if customer.invoice_settings and customer.invoice_settings.default_payment_method:
            default_pm = customer.invoice_settings.default_payment_method

        result = []
        for pm in methods.data:
            result.append({
                "id": pm.id,
                "type": "card",
                "brand": pm.card.brand if pm.card else "unknown",
                "last4": pm.card.last4 if pm.card else "****",
                "exp_month": pm.card.exp_month if pm.card else None,
                "exp_year": pm.card.exp_year if pm.card else None,
                "is_default": pm.id == default_pm,
            })
        for pm in bank_methods.data:
            acct = pm.us_bank_account
            result.append({
                "id": pm.id,
                "type": "bank_account",
                "bank_name": acct.bank_name if acct else "Bank",
                "last4": acct.last4 if acct else "****",
                "account_type": acct.account_type if acct else None,
                "is_default": pm.id == default_pm,
            })

        return {"payment_methods": result, "has_customer": True, "default": default_pm}
    except Exception as e:
        logger.warning("corp_payment_methods: %s", e)
        return {"payment_methods": [], "has_customer": True, "error": str(e)}


@router.post("/settings/payment-methods/setup")
async def create_corp_setup_intent(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Create a Stripe SetupIntent for adding a new payment method."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    body = await request.json()
    pm_type = body.get("type", "card")

    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT stripe_customer_id, company_name FROM corporate_sponsors WHERE id = $1::uuid AND active = TRUE",
            company_id,
        )

    if not row:
        raise HTTPException(404, "Company not found")

    try:
        import stripe

        customer_id = row["stripe_customer_id"]
        if not customer_id:
            customer = stripe.Customer.create(
                name=row["company_name"],
                metadata={"company_id": company_id, "type": "corporate"},
            )
            customer_id = customer.id
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE corporate_sponsors SET stripe_customer_id = $1 WHERE id = $2::uuid",
                    customer_id, company_id,
                )

        payment_method_types = ["us_bank_account"] if pm_type == "bank" else ["card"]
        setup_params = {
            "customer": customer_id,
            "payment_method_types": payment_method_types,
        }
        if pm_type == "bank":
            setup_params["payment_method_options"] = {
                "us_bank_account": {
                    "financial_connections": {"permissions": ["payment_method"]},
                },
            }

        setup_intent = stripe.SetupIntent.create(**setup_params)
        return {
            "client_secret": setup_intent.client_secret,
            "setup_intent_id": setup_intent.id,
            "customer_id": customer_id,
        }
    except Exception as e:
        logger.warning("corp_setup_intent: %s", e)
        raise HTTPException(500, f"Stripe error: {e}")


@router.post("/settings/payment-methods/default")
async def set_corp_default_payment_method(
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Set the default payment method for the corporate customer."""
    company_id = _get_company_id(user)
    if not company_id:
        raise HTTPException(400, "Company scope required")

    body = await request.json()
    pm_id = body.get("payment_method_id")
    if not pm_id:
        raise HTTPException(400, "payment_method_id required")

    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT stripe_customer_id FROM corporate_sponsors WHERE id = $1::uuid AND active = TRUE",
            company_id,
        )

    if not row or not row["stripe_customer_id"]:
        raise HTTPException(404, "No Stripe customer")

    try:
        import stripe
        stripe.Customer.modify(
            row["stripe_customer_id"],
            invoice_settings={"default_payment_method": pm_id},
        )
        return {"status": "default_set", "payment_method_id": pm_id}
    except Exception as e:
        logger.warning("corp_set_default_pm: %s", e)
        raise HTTPException(500, f"Stripe error: {e}")


@router.delete("/settings/payment-methods/{pm_id}")
async def delete_corp_payment_method(
    pm_id: str,
    request: Request,
    user: Dict = Depends(require_corp_admin),
):
    """Detach a payment method from the corporate customer."""
    try:
        import stripe
        stripe.PaymentMethod.detach(pm_id)
        return {"status": "detached", "payment_method_id": pm_id}
    except Exception as e:
        logger.warning("corp_delete_pm: %s", e)
        raise HTTPException(500, f"Stripe error: {e}")
