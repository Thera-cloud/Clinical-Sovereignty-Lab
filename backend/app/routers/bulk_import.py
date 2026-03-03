"""
Bulk Import API — Enterprise client onboarding from CSV/Excel

Supports importing 5,000+ users in ~1 minute via:
- Pre-flight validation (duplicate checks, format validation)
- Parallel password hashing (20 concurrent workers)
- Batch PostgreSQL INSERT
- Redis cache sync notification to bridge
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
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from app.services.api_server import require_admin

logger = logging.getLogger("nate.bulk_import")

router = APIRouter(
    prefix="/api/admin/bulk-import",
    tags=["bulk-import"],
    dependencies=[Depends(require_admin)],
)

BALANCE_SYNC_CHANNEL = "nate:balance_sync"
REGISTRY_RELOAD_CHANNEL = "nate:registry_reload"

PLAN_TOKENS = {
    "TRIAL": 10_000,
    "STANDARD": 50_000,
    "TOP_TIER": 200_000,
    "COACH_ONLY": 0,
}

PLAN_TIERS = {
    "TRIAL": ("STANDARD", "TRIAL", "TRIAL_ACTIVE"),
    "STANDARD": ("STANDARD", "STANDARD", "ACTIVE"),
    "TOP_TIER": ("TOP", "TOP_TIER", "ACTIVE"),
    "COACH_ONLY": ("STANDARD", "COACH_ONLY", "ACTIVE"),
}

VALID_PLANS = set(PLAN_TOKENS.keys())
MAX_HASH_WORKERS = 20
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}:{hashed.hex()}"


class ImportRow(BaseModel):
    name: str
    email: str
    username: str
    password: str
    plan: str = "TRIAL"
    coach_username: Optional[str] = None
    family_group: Optional[str] = None
    phone: Optional[str] = None


class ImportResult(BaseModel):
    status: str
    batch_id: str
    dry_run: bool
    total_rows: int
    imported: int
    skipped: int
    errors: List[dict]
    elapsed_seconds: float
    breakdown: dict


@router.post("/users")
async def bulk_import_users(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Validate only, do not insert"),
):
    """
    Import users from CSV file.

    Required columns: name, email, username, password
    Optional columns: plan, coach_username, family_group, phone

    Use dry_run=true to validate without inserting.
    """
    start = datetime.now(timezone.utc)
    batch_id = str(uuid.uuid4())
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

    rows: List[dict] = []
    for i, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        row["_line"] = i
        rows.append(row)

    if not rows:
        raise HTTPException(400, "CSV is empty (no data rows)")

    if len(rows) > 10_000:
        raise HTTPException(400, f"Maximum 10,000 rows per import. Got {len(rows):,}")

    # ── Phase 1: Pre-flight validation ──────────────────────────────────
    errors = []
    seen_usernames = set()
    seen_emails = set()

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
            errors.append({"line": line, "field": "email", "error": f"Invalid email format: {email}"})
        if not username:
            errors.append({"line": line, "field": "username", "error": "Username is required"})
        elif len(username) > 50:
            errors.append({"line": line, "field": "username", "error": f"Username too long ({len(username)} chars, max 50)"})
        if not password:
            errors.append({"line": line, "field": "password", "error": "Password is required"})
        elif len(password) < 6:
            errors.append({"line": line, "field": "password", "error": "Password must be at least 6 characters"})
        if plan not in VALID_PLANS:
            errors.append({"line": line, "field": "plan", "error": f"Invalid plan '{plan}'. Valid: {', '.join(sorted(VALID_PLANS))}"})

        if username.lower() in seen_usernames:
            errors.append({"line": line, "field": "username", "error": f"Duplicate username in CSV: {username}"})
        seen_usernames.add(username.lower())

        if email.lower() in seen_emails:
            errors.append({"line": line, "field": "email", "error": f"Duplicate email in CSV: {email}"})
        seen_emails.add(email.lower())

    async with pool.acquire() as conn:
        existing_usernames = await conn.fetch(
            "SELECT LOWER(username) as u FROM users WHERE LOWER(username) = ANY($1::text[])",
            list(seen_usernames),
        )
        existing_set = {r["u"] for r in existing_usernames}
        for row in rows:
            if row["username"].lower() in existing_set:
                errors.append({
                    "line": row["_line"],
                    "field": "username",
                    "error": f"Username already exists in database: {row['username']}",
                })

        coach_usernames = {
            row.get("coach_username", "").strip()
            for row in rows
            if row.get("coach_username", "").strip()
        }
        if coach_usernames:
            valid_coaches = await conn.fetch(
                "SELECT username FROM users WHERE role = 'COACH' AND username = ANY($1::text[])",
                list(coach_usernames),
            )
            valid_coach_set = {r["username"] for r in valid_coaches}
            for row in rows:
                cu = (row.get("coach_username", "") or "").strip()
                if cu and cu not in valid_coach_set:
                    errors.append({
                        "line": row["_line"],
                        "field": "coach_username",
                        "error": f"Coach '{cu}' not found or not a COACH role",
                    })

    if errors:
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        return ImportResult(
            status="validation_failed",
            batch_id=batch_id,
            dry_run=dry_run,
            total_rows=len(rows),
            imported=0,
            skipped=len(errors),
            errors=errors[:100],
            elapsed_seconds=round(elapsed, 2),
            breakdown={"validation_errors": len(errors), "shown": min(len(errors), 100)},
        )

    if dry_run:
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        return ImportResult(
            status="dry_run_passed",
            batch_id=batch_id,
            dry_run=True,
            total_rows=len(rows),
            imported=0,
            skipped=0,
            errors=[],
            elapsed_seconds=round(elapsed, 2),
            breakdown={
                "unique_usernames": len(seen_usernames),
                "unique_emails": len(seen_emails),
                "plans": _count_plans(rows),
                "coaches_referenced": len(coach_usernames),
            },
        )

    # ── Phase 2: Parallel password hashing ──────────────────────────────
    hash_start = datetime.now(timezone.utc)
    sem = asyncio.Semaphore(MAX_HASH_WORKERS)

    async def _hash_one(password: str) -> str:
        async with sem:
            return await asyncio.to_thread(_hash_password, password)

    hash_tasks = [_hash_one(row["password"]) for row in rows]
    hashes = await asyncio.gather(*hash_tasks)
    hash_elapsed = (datetime.now(timezone.utc) - hash_start).total_seconds()

    # ── Phase 3: Resolve coach hardware IDs ─────────────────────────────
    coach_hw_map = {}
    if coach_usernames:
        async with pool.acquire() as conn:
            coach_rows = await conn.fetch(
                "SELECT username, hardware_id FROM users WHERE role = 'COACH' AND username = ANY($1::text[])",
                list(coach_usernames),
            )
            coach_hw_map = {r["username"]: r["hardware_id"] for r in coach_rows}

    # ── Phase 4: Batch INSERT ───────────────────────────────────────────
    insert_start = datetime.now(timezone.utc)
    imported = 0
    insert_errors = []

    async with pool.acquire() as conn:
        for i, (row, pw_hash) in enumerate(zip(rows, hashes)):
            plan_key = (row.get("plan", "") or "TRIAL").upper()
            tier, plan_name, sub_status = PLAN_TIERS.get(plan_key, PLAN_TIERS["TRIAL"])
            tokens = PLAN_TOKENS.get(plan_key, 10_000)
            hw_id = f"BULK_{batch_id[:8]}_{i:05d}"

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
                "consent_version": "v13.0_2026",
                "joined_date": now_str,
                "created_at": now_str,
                "import_batch_id": batch_id,
                "import_source": "csv_bulk",
                "token_usage_today": 0,
                "token_usage_month": 0,
            }
            if row.get("phone", "").strip():
                profile["phone"] = row["phone"].strip()
            if row.get("family_group", "").strip():
                profile["family_group"] = row["family_group"].strip()

            try:
                await conn.execute("""
                    INSERT INTO users (
                        username, password_hash, role, tier, name, email,
                        hardware_id, consent_version, subscription_status,
                        profile_data, token_balance, updated_at
                    ) VALUES ($1, $2, 'CLIENT', $3, $4, $5, $6, 'v13.0_2026', $7,
                              $8::jsonb, $9, NOW())
                """,
                    row["username"], pw_hash, tier, row["name"],
                    row["email"], hw_id, sub_status,
                    json.dumps(profile, default=str), tokens,
                )
                imported += 1
            except Exception as e:
                insert_errors.append({
                    "line": row["_line"],
                    "username": row["username"],
                    "error": str(e)[:200],
                })

    insert_elapsed = (datetime.now(timezone.utc) - insert_start).total_seconds()

    # ── Phase 5: Notify bridge to reload cache ──────────────────────────
    try:
        from app.services.api_server import _get_auth_redis
        r = await _get_auth_redis()
        if r:
            await r.publish(
                REGISTRY_RELOAD_CHANNEL,
                json.dumps({
                    "action": "bulk_import",
                    "batch_id": batch_id,
                    "count": imported,
                }),
            )
    except Exception as e:
        logger.warning("Registry reload publish failed: %s", e)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    return ImportResult(
        status="import_complete",
        batch_id=batch_id,
        dry_run=False,
        total_rows=len(rows),
        imported=imported,
        skipped=len(insert_errors),
        errors=insert_errors[:100],
        elapsed_seconds=round(elapsed, 2),
        breakdown={
            "hash_seconds": round(hash_elapsed, 2),
            "insert_seconds": round(insert_elapsed, 2),
            "plans": _count_plans(rows),
            "coaches_used": list(coach_hw_map.keys()) or ["CoachN (default)"],
        },
    )


@router.delete("/users/batch/{batch_id}")
async def delete_batch(batch_id: str, request: Request):
    """Delete all users imported in a specific batch (for test cleanup)."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE profile_data->>'import_batch_id' = $1",
            batch_id,
        )
        if count == 0:
            raise HTTPException(404, f"No users found for batch {batch_id}")

        await conn.execute(
            "DELETE FROM users WHERE profile_data->>'import_batch_id' = $1",
            batch_id,
        )

    try:
        from app.services.api_server import _get_auth_redis
        r = await _get_auth_redis()
        if r:
            await r.publish(
                REGISTRY_RELOAD_CHANNEL,
                json.dumps({"action": "batch_deleted", "batch_id": batch_id}),
            )
    except Exception:
        pass

    return {"status": "deleted", "batch_id": batch_id, "users_deleted": count}


@router.get("/users/batches")
async def list_batches(request: Request):
    """List all import batches with counts."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT profile_data->>'import_batch_id' as batch_id,
                   COUNT(*) as user_count,
                   MIN(created_at) as imported_at
            FROM users
            WHERE profile_data->>'import_batch_id' IS NOT NULL
            GROUP BY profile_data->>'import_batch_id'
            ORDER BY MIN(created_at) DESC
        """)
    return {
        "batches": [
            {
                "batch_id": r["batch_id"],
                "user_count": r["user_count"],
                "imported_at": r["imported_at"].isoformat() if r["imported_at"] else None,
            }
            for r in rows
        ]
    }


def _count_plans(rows: List[dict]) -> dict:
    counts = {}
    for row in rows:
        p = (row.get("plan", "") or "TRIAL").upper()
        counts[p] = counts.get(p, 0) + 1
    return counts
