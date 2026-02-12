"""
LITTLE NATE — Prospect API
Prospect management, journey tracking, subscription, and CSV export.
"""

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timedelta
import secrets
import csv
import io
import json

from app.config import settings

router = APIRouter(prefix="/api/prospects", tags=["prospects"])


# =============================================================================
# MODELS
# =============================================================================

class ProspectSubscribe(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    source: str = "website"

class ProspectUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    sms_opt_out: Optional[bool] = None
    email_opt_out: Optional[bool] = None


# =============================================================================
# PUBLIC ENDPOINT: Subscribe
# =============================================================================

@router.post("/subscribe")
async def subscribe_prospect(request: Request, body: ProspectSubscribe):
    """
    Public endpoint for prospect subscription.
    Creates prospect, links to active campaign, triggers first drip.
    """
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Check if already subscribed
        existing = await conn.fetchrow(
            "SELECT id, status FROM prospects WHERE email = $1",
            body.email
        )
        if existing:
            if existing["status"] == "unsubscribed":
                # Re-subscribe
                row = await conn.fetchrow(
                    """UPDATE prospects
                       SET status = 'subscribed', first_name = COALESCE($2, first_name),
                           last_name = COALESCE($3, last_name), phone = COALESCE($4, phone),
                           email_opt_out = FALSE
                       WHERE id = $1
                       RETURNING *""",
                    existing["id"], body.first_name, body.last_name, body.phone
                )
                return {"status": "resubscribed", "prospect": dict(row)}
            return {"status": "already_subscribed", "prospect_id": str(existing["id"])}

        # Find the active campaign to assign
        active_campaign = await conn.fetchrow(
            "SELECT id FROM campaigns WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )

        campaign_id = active_campaign["id"] if active_campaign else None
        now = datetime.utcnow()
        next_email = now  # First email sends immediately

        row = await conn.fetchrow(
            """INSERT INTO prospects
               (email, first_name, last_name, phone, source, status,
                current_campaign_id, current_step, next_email_at, journey_started_at)
               VALUES ($1, $2, $3, $4, $5, 'active_journey', $6, 1, $7, $7)
               RETURNING *""",
            body.email, body.first_name, body.last_name, body.phone,
            body.source, campaign_id, now
        )

        # Initialize the story store
        await conn.execute(
            "INSERT INTO prospect_story_store (prospect_id) VALUES ($1)",
            row["id"]
        )

        return {"status": "subscribed", "prospect": dict(row)}


# =============================================================================
# PROSPECT MANAGEMENT
# =============================================================================

@router.get("")
async def list_prospects(
    request: Request,
    status: Optional[str] = None,
    search: Optional[str] = None,
    campaign_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """List prospects with filtering, search, and pagination."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        conditions = []
        params = []
        param_idx = 1

        if status:
            conditions.append(f"p.status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if campaign_id:
            conditions.append(f"p.current_campaign_id = ${param_idx}")
            params.append(campaign_id)
            param_idx += 1

        if search:
            conditions.append(
                f"(p.email ILIKE ${param_idx} OR p.first_name ILIKE ${param_idx} OR p.last_name ILIKE ${param_idx})"
            )
            params.append(f"%{search}%")
            param_idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * per_page

        # Get total count
        count_query = f"SELECT COUNT(*) FROM prospects p {where}"
        total = await conn.fetchval(count_query, *params)

        # Get page
        params.extend([per_page, offset])
        rows = await conn.fetch(
            f"""SELECT p.*, ss.last_quiz_completed, ss.quizzes_completed,
                       c.name as campaign_name
                FROM prospects p
                LEFT JOIN prospect_story_store ss ON ss.prospect_id = p.id
                LEFT JOIN campaigns c ON c.id = p.current_campaign_id
                {where}
                ORDER BY p.created_at DESC
                LIMIT ${param_idx} OFFSET ${param_idx + 1}""",
            *params
        )

        return {
            "prospects": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        }


@router.get("/export")
async def export_prospects_csv(request: Request, status: Optional[str] = None):
    """Export prospects as CSV download."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                """SELECT email, first_name, last_name, phone, source, status,
                          current_step, journey_started_at, journey_completed_at,
                          golden_ticket_issued_at, converted_at, created_at
                   FROM prospects WHERE status = $1
                   ORDER BY created_at DESC""",
                status
            )
        else:
            rows = await conn.fetch(
                """SELECT email, first_name, last_name, phone, source, status,
                          current_step, journey_started_at, journey_completed_at,
                          golden_ticket_issued_at, converted_at, created_at
                   FROM prospects ORDER BY created_at DESC"""
            )

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "email", "first_name", "last_name", "phone", "source", "status",
            "current_step", "journey_started_at", "journey_completed_at",
            "golden_ticket_issued_at", "converted_at", "created_at"
        ])
        writer.writeheader()
        for r in rows:
            writer.writerow({k: str(v) if v else "" for k, v in dict(r).items()})

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=prospects.csv"}
        )


@router.get("/{prospect_id}")
async def get_prospect(request: Request, prospect_id: str):
    """Get full prospect profile with story, insights, and journey data."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        prospect = await conn.fetchrow(
            """SELECT p.*, c.name as campaign_name
               FROM prospects p
               LEFT JOIN campaigns c ON c.id = p.current_campaign_id
               WHERE p.id = $1""",
            prospect_id
        )
        if not prospect:
            raise HTTPException(status_code=404, detail="Prospect not found")

        # Get story store
        story = await conn.fetchrow(
            "SELECT * FROM prospect_story_store WHERE prospect_id = $1",
            prospect_id
        )

        # Get insights
        insights = await conn.fetch(
            """SELECT * FROM nate_insights
               WHERE prospect_id = $1
               ORDER BY created_at""",
            prospect_id
        )

        # Get quiz responses
        responses = await conn.fetch(
            """SELECT qr.*, q.title as quiz_title
               FROM quiz_responses qr
               JOIN quizzes q ON q.id = qr.quiz_id
               WHERE qr.prospect_id = $1
               ORDER BY qr.completed_at""",
            prospect_id
        )

        # Get delivery log
        deliveries = await conn.fetch(
            """SELECT * FROM delivery_log
               WHERE prospect_id = $1
               ORDER BY sent_at DESC LIMIT 20""",
            prospect_id
        )

        # Get assessment if exists
        assessment = await conn.fetchrow(
            "SELECT * FROM coaching_assessments WHERE prospect_id = $1",
            prospect_id
        )

        result = dict(prospect)
        result["story"] = dict(story) if story else None
        result["insights"] = [dict(i) for i in insights]
        result["quiz_responses"] = [dict(r) for r in responses]
        result["deliveries"] = [dict(d) for d in deliveries]
        result["assessment"] = dict(assessment) if assessment else None
        return result


@router.get("/{prospect_id}/insights")
async def get_prospect_insights(request: Request, prospect_id: str):
    """Get all insights for a prospect."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ni.*, q.title as quiz_title
               FROM nate_insights ni
               JOIN quizzes q ON q.id = ni.quiz_id
               WHERE ni.prospect_id = $1
               ORDER BY ni.created_at""",
            prospect_id
        )
        return [dict(r) for r in rows]


@router.get("/{prospect_id}/story")
async def get_prospect_story(request: Request, prospect_id: str):
    """Get the cumulative story store for a prospect."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM prospect_story_store WHERE prospect_id = $1",
            prospect_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Story not found")
        return dict(row)


@router.put("/{prospect_id}")
async def update_prospect(request: Request, prospect_id: str, body: ProspectUpdate):
    """Update prospect details."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        updates = body.dict(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        set_clauses = []
        params = []
        for i, (key, val) in enumerate(updates.items(), start=1):
            set_clauses.append(f"{key} = ${i}")
            params.append(val)
        params.append(prospect_id)

        row = await conn.fetchrow(
            f"""UPDATE prospects SET {', '.join(set_clauses)}
                WHERE id = ${len(params)}
                RETURNING *""",
            *params
        )
        if not row:
            raise HTTPException(status_code=404, detail="Prospect not found")
        return dict(row)


# =============================================================================
# BULK SUBSCRIBE (for imports)
# =============================================================================

class BulkSubscribeRequest(BaseModel):
    prospects: List[ProspectSubscribe]

@router.post("/subscribe/bulk")
async def bulk_subscribe(request: Request, body: BulkSubscribeRequest):
    """Bulk subscribe multiple prospects."""
    pool = request.app.state.db_pool
    results = {"subscribed": 0, "already_exists": 0, "errors": []}

    active_campaign = None
    async with pool.acquire() as conn:
        active_campaign = await conn.fetchrow(
            "SELECT id FROM campaigns WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )

    campaign_id = active_campaign["id"] if active_campaign else None
    now = datetime.utcnow()

    async with pool.acquire() as conn:
        for p in body.prospects:
            try:
                existing = await conn.fetchval(
                    "SELECT 1 FROM prospects WHERE email = $1", p.email
                )
                if existing:
                    results["already_exists"] += 1
                    continue

                await conn.execute(
                    """INSERT INTO prospects
                       (email, first_name, last_name, phone, source, status,
                        current_campaign_id, current_step, next_email_at, journey_started_at)
                       VALUES ($1, $2, $3, $4, $5, 'active_journey', $6, 1, $7, $7)""",
                    p.email, p.first_name, p.last_name, p.phone,
                    p.source, campaign_id, now
                )

                # Init story store
                pid = await conn.fetchval(
                    "SELECT id FROM prospects WHERE email = $1", p.email
                )
                await conn.execute(
                    "INSERT INTO prospect_story_store (prospect_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    pid
                )

                results["subscribed"] += 1
            except Exception as e:
                results["errors"].append({"email": p.email, "error": str(e)})

    return results
