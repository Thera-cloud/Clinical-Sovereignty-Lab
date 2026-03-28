"""
Coach Sign-Up Code API — Revenue sharing system.

Admin-managed codes, Stripe-integrated billing splits, hierarchy-aware DOJO sharing.
"""

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import get_current_user, require_admin, require_coach

logger = logging.getLogger("nate.signup_code_api")

router = APIRouter(
    prefix="/api/billing/signup-codes",
    tags=["signup-codes"],
)

MINIMUM_ENROLLMENT_MONTHS = 6
FREEZE_DURATION_DAYS = 90


class CreateCodeRequest(BaseModel):
    coach_id: str
    code: str
    sharing_pct: int
    max_linked_entities: Optional[int] = None
    monthly_sharing_cap_cents: Optional[int] = None


class AdjustCodeRequest(BaseModel):
    sharing_pct: int
    reason: Optional[str] = None


class ApplyCodeRequest(BaseModel):
    code: str
    entity_type: str
    entity_id: str


# ============================================================
# Admin-only endpoints
# ============================================================

@router.post("", dependencies=[Depends(require_admin)])
async def create_code(req: CreateCodeRequest, request: Request, user: Dict = Depends(require_admin)):
    """Admin creates a Sign-Up code for a coach."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    if req.sharing_pct < 1 or req.sharing_pct > 30:
        raise HTTPException(400, "Sharing percentage must be between 1 and 30")

    async with db.acquire() as conn:
        coach = await conn.fetchrow(
            "SELECT username, profile_data FROM users WHERE hardware_id = $1 AND role = 'COACH'",
            req.coach_id,
        )
        if not coach:
            raise HTTPException(404, "Coach not found")

        profile = coach["profile_data"]
        if isinstance(profile, str):
            import json
            profile = json.loads(profile)

        # Loophole #13: require Stripe Connected Account
        if not profile.get("stripe_connect_id"):
            raise HTTPException(400, "Coach must have a Stripe Connected Account before creating a Sign-Up code")

        existing = await conn.fetchrow(
            "SELECT id FROM coach_signup_codes WHERE coach_id = $1", req.coach_id
        )
        if existing:
            raise HTTPException(400, "Coach already has a Sign-Up code")

        row = await conn.fetchrow(
            """INSERT INTO coach_signup_codes (coach_id, code, sharing_pct, created_by,
                  max_linked_entities, monthly_sharing_cap_cents)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id, code, sharing_pct, status""",
            req.coach_id, req.code.upper(), req.sharing_pct,
            user.get("hardware_id", "admin"),
            req.max_linked_entities, req.monthly_sharing_cap_cents,
        )

        await conn.execute(
            """INSERT INTO signup_code_audit_log (code_id, admin_id, action, new_value, reason)
               VALUES ($1, $2, 'create', $3, 'Initial creation')""",
            row["id"], user.get("hardware_id", "admin"),
            f"pct={req.sharing_pct}, cap={req.monthly_sharing_cap_cents}",
        )

    return {"id": str(row["id"]), "code": row["code"], "sharing_pct": row["sharing_pct"], "status": row["status"]}


@router.get("", dependencies=[Depends(require_admin)])
async def list_codes(request: Request, user: Dict = Depends(require_admin)):
    """List all Sign-Up codes (admin only)."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"codes": [], "count": 0}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.id, c.coach_id, c.code, c.sharing_pct, c.status, c.created_at,
                      c.frozen_at, c.freeze_ends_at, c.max_linked_entities, c.monthly_sharing_cap_cents,
                      u.profile_data->>'name' as coach_name,
                      (SELECT COUNT(*) FROM signup_code_links l WHERE l.code_id = c.id AND l.status = 'active') as linked_count,
                      (SELECT COALESCE(SUM(s.shared_amount_cents), 0) FROM signup_sharing_ledger s
                       WHERE s.code_id = c.id AND s.status = 'completed'
                       AND s.billing_period_start >= date_trunc('month', NOW())) as monthly_sharing_cents
               FROM coach_signup_codes c
               LEFT JOIN users u ON u.hardware_id = c.coach_id AND u.role = 'COACH'
               ORDER BY c.created_at DESC"""
        )

    codes = []
    for r in rows:
        codes.append({
            "id": str(r["id"]),
            "coach_id": r["coach_id"],
            "coach_name": r["coach_name"],
            "code": r["code"],
            "sharing_pct": r["sharing_pct"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "frozen_at": r["frozen_at"].isoformat() if r["frozen_at"] else None,
            "freeze_ends_at": r["freeze_ends_at"].isoformat() if r["freeze_ends_at"] else None,
            "linked_count": r["linked_count"],
            "monthly_sharing_cents": r["monthly_sharing_cents"],
            "max_linked_entities": r["max_linked_entities"],
            "monthly_sharing_cap_cents": r["monthly_sharing_cap_cents"],
        })

    return {"codes": codes, "count": len(codes)}


@router.get("/{coach_id_or_code}")
async def get_code(coach_id_or_code: str, request: Request, user: Dict = Depends(require_coach)):
    """Get a coach's Sign-Up code (coach or admin)."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, coach_id, code, sharing_pct, status, created_at,
                      frozen_at, freeze_ends_at, max_linked_entities, monthly_sharing_cap_cents
               FROM coach_signup_codes
               WHERE coach_id = $1 OR code = $1""",
            coach_id_or_code,
        )

    if not row:
        raise HTTPException(404, "Sign-Up code not found")

    return {
        "id": str(row["id"]),
        "coach_id": row["coach_id"],
        "code": row["code"],
        "sharing_pct": row["sharing_pct"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "frozen_at": row["frozen_at"].isoformat() if row["frozen_at"] else None,
        "freeze_ends_at": row["freeze_ends_at"].isoformat() if row["freeze_ends_at"] else None,
    }


@router.put("/{code_id}", dependencies=[Depends(require_admin)])
async def adjust_code(code_id: str, req: AdjustCodeRequest, request: Request, user: Dict = Depends(require_admin)):
    """Adjust sharing percentage (admin only). Loophole #9: prospective only."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    if req.sharing_pct < 1 or req.sharing_pct > 30:
        raise HTTPException(400, "Sharing percentage must be between 1 and 30")

    async with db.acquire() as conn:
        old = await conn.fetchrow(
            "SELECT sharing_pct FROM coach_signup_codes WHERE id = $1::uuid", code_id
        )
        if not old:
            raise HTTPException(404, "Code not found")

        await conn.execute(
            "UPDATE coach_signup_codes SET sharing_pct = $1, updated_at = NOW() WHERE id = $2::uuid",
            req.sharing_pct, code_id,
        )

        await conn.execute(
            """INSERT INTO signup_code_audit_log (code_id, admin_id, action, old_value, new_value, reason)
               VALUES ($1::uuid, $2, 'adjust_pct', $3, $4, $5)""",
            code_id, user.get("hardware_id", "admin"),
            str(old["sharing_pct"]), str(req.sharing_pct), req.reason or "Admin adjustment",
        )

    return {"status": "updated", "old_pct": old["sharing_pct"], "new_pct": req.sharing_pct}


@router.post("/{code_id}/freeze", dependencies=[Depends(require_admin)])
async def freeze_code(code_id: str, request: Request, user: Dict = Depends(require_admin)):
    """Initiate 90-day freeze when coach switches to 'I Collect Payment'. Loophole #11."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        code = await conn.fetchrow(
            "SELECT id, status, created_at FROM coach_signup_codes WHERE id = $1::uuid", code_id
        )
        if not code:
            raise HTTPException(404, "Code not found")
        if code["status"] == "frozen":
            raise HTTPException(400, "Code is already frozen")

        enrollment_duration = (datetime.now(timezone.utc) - code["created_at"]).days
        if enrollment_duration < MINIMUM_ENROLLMENT_MONTHS * 30:
            raise HTTPException(
                400,
                f"Coach must be enrolled for at least {MINIMUM_ENROLLMENT_MONTHS} months before switching. "
                f"Current enrollment: {enrollment_duration} days."
            )

        now = datetime.now(timezone.utc)
        freeze_ends = now + timedelta(days=FREEZE_DURATION_DAYS)

        await conn.execute(
            """UPDATE coach_signup_codes
               SET status = 'frozen', frozen_at = $1, freeze_ends_at = $2, updated_at = NOW()
               WHERE id = $3::uuid""",
            now, freeze_ends, code_id,
        )

        await conn.execute(
            """INSERT INTO signup_code_audit_log (code_id, admin_id, action, old_value, new_value, reason)
               VALUES ($1::uuid, $2, 'freeze', 'active', 'frozen', 'Payment mode switch initiated')""",
            code_id, user.get("hardware_id", "admin"),
        )

    return {"status": "frozen", "frozen_at": now.isoformat(), "freeze_ends_at": freeze_ends.isoformat()}


@router.post("/{code_id}/unfreeze", dependencies=[Depends(require_admin)])
async def unfreeze_code(code_id: str, request: Request, user: Dict = Depends(require_admin)):
    """Re-enable code after 90-day freeze."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        code = await conn.fetchrow(
            "SELECT id, status, freeze_ends_at FROM coach_signup_codes WHERE id = $1::uuid", code_id
        )
        if not code:
            raise HTTPException(404, "Code not found")
        if code["status"] != "frozen":
            raise HTTPException(400, "Code is not frozen")

        if code["freeze_ends_at"] and datetime.now(timezone.utc) < code["freeze_ends_at"]:
            days_remaining = (code["freeze_ends_at"] - datetime.now(timezone.utc)).days
            raise HTTPException(400, f"Freeze period not yet complete. {days_remaining} days remaining.")

        await conn.execute(
            """UPDATE coach_signup_codes
               SET status = 'active', frozen_at = NULL, freeze_ends_at = NULL, updated_at = NOW()
               WHERE id = $1::uuid""",
            code_id,
        )

        await conn.execute(
            """INSERT INTO signup_code_audit_log (code_id, admin_id, action, old_value, new_value, reason)
               VALUES ($1::uuid, $2, 'unfreeze', 'frozen', 'active', 'Freeze period complete')""",
            code_id, user.get("hardware_id", "admin"),
        )

    return {"status": "active"}


@router.get("/{code_id}/links", dependencies=[Depends(require_coach)])
async def get_links(code_id: str, request: Request, user: Dict = Depends(require_coach)):
    """List linked entities for a code."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"links": [], "count": 0}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT l.id, l.entity_type, l.entity_id, l.linked_at, l.unlinked_at, l.status,
                      u.profile_data->>'name' as entity_name,
                      u.tier as subscription_tier
               FROM signup_code_links l
               LEFT JOIN users u ON u.username = l.entity_id
               WHERE l.code_id = $1::uuid
               ORDER BY l.status ASC, l.linked_at DESC""",
            code_id,
        )

    links = []
    for r in rows:
        links.append({
            "id": str(r["id"]),
            "entity_type": r["entity_type"],
            "entity_id": r["entity_id"],
            "entity_name": r["entity_name"],
            "subscription_tier": r["subscription_tier"],
            "linked_at": r["linked_at"].isoformat() if r["linked_at"] else None,
            "unlinked_at": r["unlinked_at"].isoformat() if r["unlinked_at"] else None,
            "status": r["status"],
        })

    return {"links": links, "count": len(links)}


# ============================================================
# Public (authenticated) endpoints — for registration flow
# ============================================================

@router.post("/verify/{code}")
async def verify_code(code: str, request: Request, user: Dict = Depends(get_current_user)):
    """Verify a Sign-Up code during registration."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT c.id, c.coach_id, c.code, c.sharing_pct, c.status,
                      u.profile_data->>'name' as coach_name, u.username as coach_username
               FROM coach_signup_codes c
               LEFT JOIN users u ON u.hardware_id = c.coach_id AND u.role = 'COACH'
               WHERE c.code = $1""",
            code.upper(),
        )

    if not row:
        raise HTTPException(404, "Invalid Sign-Up code")

    if row["status"] != "active":
        raise HTTPException(400, f"This code is currently {row['status']}")

    return {
        "valid": True,
        "code": row["code"],
        "coach_id": row["coach_id"],
        "coach_name": row["coach_name"],
        "coach_username": row["coach_username"],
    }


@router.post("/apply")
async def apply_code(req: ApplyCodeRequest, request: Request, user: Dict = Depends(get_current_user)):
    """Link a Sign-Up code to an entity at signup."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    # Loophole #5: coaches cannot be linked
    if req.entity_type == "coach":
        raise HTTPException(400, "Sign-Up codes cannot be applied to coach accounts")

    if req.entity_type not in ("client", "family", "group", "company"):
        raise HTTPException(400, "Invalid entity type")

    async with db.acquire() as conn:
        code_row = await conn.fetchrow(
            "SELECT id, coach_id, status, max_linked_entities FROM coach_signup_codes WHERE code = $1",
            req.code.upper(),
        )
        if not code_row:
            raise HTTPException(404, "Invalid Sign-Up code")
        if code_row["status"] != "active":
            raise HTTPException(400, f"Code is {code_row['status']}")

        # Loophole #12: entity cap
        if code_row["max_linked_entities"]:
            active_count = await conn.fetchval(
                "SELECT COUNT(*) FROM signup_code_links WHERE code_id = $1 AND status = 'active'",
                code_row["id"],
            )
            if active_count >= code_row["max_linked_entities"]:
                raise HTTPException(400, "This code has reached its maximum number of linked entities")

        # Loophole #8: deactivate old link atomically
        await conn.execute(
            """UPDATE signup_code_links
               SET status = 'inactive', unlinked_at = NOW()
               WHERE entity_type = $1 AND entity_id = $2 AND status = 'active'""",
            req.entity_type, req.entity_id,
        )

        row = await conn.fetchrow(
            """INSERT INTO signup_code_links (code_id, entity_type, entity_id)
               VALUES ($1, $2, $3)
               RETURNING id""",
            code_row["id"], req.entity_type, req.entity_id,
        )

    return {"status": "linked", "link_id": str(row["id"]), "coach_id": code_row["coach_id"]}


@router.get("/{code_id}/ledger", dependencies=[Depends(require_coach)])
async def get_ledger(code_id: str, request: Request, user: Dict = Depends(require_coach)):
    """Sharing transaction history for a code."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        return {"entries": [], "total_shared_cents": 0}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, entity_id, entity_type, source_type, gross_amount_cents,
                      sharing_pct, shared_amount_cents, billing_period_start, billing_period_end,
                      status, source_note, created_at
               FROM signup_sharing_ledger
               WHERE code_id = $1::uuid
               ORDER BY billing_period_start DESC""",
            code_id,
        )

    entries = []
    total = 0
    for r in rows:
        entries.append({
            "id": str(r["id"]),
            "entity_id": r["entity_id"],
            "entity_type": r["entity_type"],
            "source_type": r["source_type"],
            "gross_amount_cents": r["gross_amount_cents"],
            "sharing_pct": r["sharing_pct"],
            "shared_amount_cents": r["shared_amount_cents"],
            "billing_period": f"{r['billing_period_start']} to {r['billing_period_end']}",
            "status": r["status"],
            "source_note": r["source_note"],
        })
        if r["status"] == "completed":
            total += r["shared_amount_cents"]

    return {"entries": entries, "total_shared_cents": total, "count": len(entries)}
