"""
LITTLE NATE — Golden Ticket API
Issue, redeem, manage, and track Golden Tickets for prospect conversion.
"""

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import secrets

from app.config import settings

router = APIRouter(prefix="/api/golden-ticket", tags=["golden-ticket"])


# =============================================================================
# MODELS
# =============================================================================

class TicketIssueRequest(BaseModel):
    prospect_id: str
    custom_window_days: Optional[int] = None    # Override default conversion window

class TicketRedeemRequest(BaseModel):
    token: str
    password: Optional[str] = None              # If they want to set their own password

class TicketReminderRequest(BaseModel):
    prospect_id: str
    message_type: str = "reminder"              # 'reminder' or 'final_reminder'

class ManualTicketRequest(BaseModel):
    email: str
    first_name: Optional[str] = None
    custom_message: Optional[str] = None


# =============================================================================
# TICKET OPERATIONS
# =============================================================================

@router.post("/issue")
async def issue_golden_ticket(request: Request, body: TicketIssueRequest):
    """
    Issue a Golden Ticket to a prospect after Quiz 5 completion.
    Typically called automatically by the insight engine.
    """
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        prospect = await conn.fetchrow(
            "SELECT * FROM prospects WHERE id = $1", body.prospect_id
        )
        if not prospect:
            raise HTTPException(status_code=404, detail="Prospect not found")

        if prospect["golden_ticket_token"]:
            return {
                "status": "already_issued",
                "token": prospect["golden_ticket_token"],
                "expires_at": str(prospect["golden_ticket_expires_at"])
            }

        # Generate secure token
        token = secrets.token_urlsafe(32)
        window_days = body.custom_window_days or settings.GOLDEN_TICKET_DEFAULT_WINDOW_DAYS
        now = datetime.utcnow()
        expires_at = now + timedelta(days=window_days)

        row = await conn.fetchrow(
            """UPDATE prospects
               SET golden_ticket_token = $2,
                   golden_ticket_issued_at = $3,
                   golden_ticket_expires_at = $4,
                   status = 'golden_ticket_issued'
               WHERE id = $1
               RETURNING *""",
            body.prospect_id, token, now, expires_at
        )

        return {
            "status": "issued",
            "token": token,
            "prospect_id": body.prospect_id,
            "expires_at": str(expires_at),
            "redemption_url": f"https://app.sovereignsanctuary.net/golden-ticket?token={token}"
        }


@router.get("/validate/{token}")
async def validate_ticket(request: Request, token: str):
    """Validate a Golden Ticket token (public endpoint for redemption page)."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        prospect = await conn.fetchrow(
            """SELECT p.*, ca.snapshot, ca.goals, ca.legacy_statement
               FROM prospects p
               LEFT JOIN coaching_assessments ca ON ca.prospect_id = p.id
               WHERE p.golden_ticket_token = $1""",
            token
        )
        if not prospect:
            raise HTTPException(status_code=404, detail="Invalid ticket")

        now = datetime.utcnow()
        if prospect["golden_ticket_redeemed_at"]:
            return {"status": "already_redeemed", "valid": False}

        expired = (
            prospect["golden_ticket_expires_at"]
            and prospect["golden_ticket_expires_at"].replace(tzinfo=None) < now
        )

        return {
            "valid": not expired,
            "status": "expired" if expired else "valid",
            "first_name": prospect["first_name"],
            "email": prospect["email"],
            "assessment_preview": prospect["snapshot"][:300] if prospect["snapshot"] else None,
            "goals": prospect["goals"],
            "legacy_statement": prospect["legacy_statement"],
            "expires_at": str(prospect["golden_ticket_expires_at"]) if prospect["golden_ticket_expires_at"] else None
        }


@router.post("/redeem")
async def redeem_golden_ticket(
    request: Request,
    body: TicketRedeemRequest,
    background_tasks: BackgroundTasks
):
    """
    Redeem a Golden Ticket — create client account and migrate data.
    """
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        prospect = await conn.fetchrow(
            "SELECT * FROM prospects WHERE golden_ticket_token = $1",
            body.token
        )
        if not prospect:
            raise HTTPException(status_code=404, detail="Invalid ticket token")

        if prospect["golden_ticket_redeemed_at"]:
            raise HTTPException(status_code=400, detail="Ticket already redeemed")

        # Allow late redemption (after window), but note it
        now = datetime.utcnow()
        late_redemption = (
            prospect["golden_ticket_expires_at"]
            and prospect["golden_ticket_expires_at"].replace(tzinfo=None) < now
        )

        # Mark ticket as redeemed
        await conn.execute(
            """UPDATE prospects
               SET golden_ticket_redeemed_at = $2, status = 'redeemed'
               WHERE id = $1""",
            prospect["id"], now
        )

        # Trigger account creation + data migration in background
        background_tasks.add_task(
            _create_client_from_prospect,
            request.app.state.db_pool,
            str(prospect["id"]),
            body.password,
            late_redemption
        )

        return {
            "status": "redeemed",
            "prospect_id": str(prospect["id"]),
            "late_redemption": late_redemption,
            "message": "Welcome to the Sanctuary. Your account is being created..."
        }


async def _create_client_from_prospect(db_pool, prospect_id: str, password: str, late: bool):
    """Background task: create client account from prospect."""
    try:
        from app.services.ticket_service import TicketService
        service = TicketService(db_pool)
        await service.create_client_from_prospect(prospect_id, password, late)
    except Exception as e:
        print(f">>> [TICKET] Error creating client from prospect {prospect_id}: {e}")


# =============================================================================
# TICKET MANAGEMENT (Admin)
# =============================================================================

@router.get("/list")
async def list_tickets(
    request: Request,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 50
):
    """List all Golden Tickets with their status."""
    pool = request.app.state.db_pool
    offset = (page - 1) * per_page
    async with pool.acquire() as conn:
        conditions = ["p.golden_ticket_token IS NOT NULL"]
        params = []
        param_idx = 1

        if status == "pending":
            conditions.append("p.golden_ticket_redeemed_at IS NULL")
            conditions.append("p.golden_ticket_expires_at > NOW()")
        elif status == "redeemed":
            conditions.append("p.golden_ticket_redeemed_at IS NOT NULL")
        elif status == "expired":
            conditions.append("p.golden_ticket_redeemed_at IS NULL")
            conditions.append("p.golden_ticket_expires_at <= NOW()")

        where = f"WHERE {' AND '.join(conditions)}"

        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM prospects p {where}", *params
        )

        params.extend([per_page, offset])
        rows = await conn.fetch(
            f"""SELECT p.id, p.email, p.first_name, p.last_name,
                       p.golden_ticket_token, p.golden_ticket_issued_at,
                       p.golden_ticket_expires_at, p.golden_ticket_redeemed_at,
                       p.status, p.converted_to_client_id,
                       ca.snapshot IS NOT NULL as has_assessment
                FROM prospects p
                LEFT JOIN coaching_assessments ca ON ca.prospect_id = p.id
                {where}
                ORDER BY p.golden_ticket_issued_at DESC
                LIMIT ${param_idx} OFFSET ${param_idx + 1}""",
            *params
        )

        return {
            "tickets": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page
        }


@router.post("/{prospect_id}/remind")
async def send_ticket_reminder(
    request: Request,
    prospect_id: str,
    background_tasks: BackgroundTasks
):
    """Send a reminder about an unredeemed Golden Ticket."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        prospect = await conn.fetchrow(
            """SELECT * FROM prospects
               WHERE id = $1 AND golden_ticket_token IS NOT NULL
                 AND golden_ticket_redeemed_at IS NULL""",
            prospect_id
        )
        if not prospect:
            raise HTTPException(status_code=404, detail="No pending ticket for this prospect")

        # Log the reminder
        await conn.execute(
            """INSERT INTO delivery_log (prospect_id, channel, message_type, status)
               VALUES ($1, 'email', 'ticket_reminder', 'queued')""",
            prospect_id
        )

        return {"status": "reminder_queued", "prospect_id": prospect_id}


@router.post("/issue-manual")
async def issue_manual_ticket(request: Request, body: ManualTicketRequest):
    """Manually issue a Golden Ticket to a VIP (creates prospect if needed)."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Find or create prospect
        prospect = await conn.fetchrow(
            "SELECT * FROM prospects WHERE email = $1", body.email
        )

        if not prospect:
            prospect = await conn.fetchrow(
                """INSERT INTO prospects (email, first_name, source, status)
                   VALUES ($1, $2, 'vip_manual', 'quiz_complete')
                   RETURNING *""",
                body.email, body.first_name
            )
            # Init story store
            await conn.execute(
                "INSERT INTO prospect_story_store (prospect_id) VALUES ($1) ON CONFLICT DO NOTHING",
                prospect["id"]
            )

        # Issue the ticket
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        expires_at = now + timedelta(days=settings.GOLDEN_TICKET_DEFAULT_WINDOW_DAYS)

        await conn.execute(
            """UPDATE prospects
               SET golden_ticket_token = $2,
                   golden_ticket_issued_at = $3,
                   golden_ticket_expires_at = $4,
                   status = 'golden_ticket_issued'
               WHERE id = $1""",
            prospect["id"], token, now, expires_at
        )

        return {
            "status": "issued",
            "token": token,
            "prospect_id": str(prospect["id"]),
            "redemption_url": f"https://app.sovereignsanctuary.net/golden-ticket?token={token}"
        }
