"""
LITTLE NATE — Campaign API
CRUD operations for drip campaigns and campaign steps.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.api_server import require_admin
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"], dependencies=[Depends(require_admin)])


# =============================================================================
# MODELS
# =============================================================================

class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    conversion_window_days: int = 7

class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    conversion_window_days: Optional[int] = None

class CampaignStepCreate(BaseModel):
    step_order: int
    delay_hours: int = 24
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    email_template_id: Optional[str] = None
    quiz_id: Optional[str] = None
    sms_enabled: bool = False
    sms_template: Optional[str] = None
    sms_fallback_delay_hours: int = 4

class CampaignStepUpdate(BaseModel):
    step_order: Optional[int] = None
    delay_hours: Optional[int] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    email_template_id: Optional[str] = None
    quiz_id: Optional[str] = None
    sms_enabled: Optional[bool] = None
    sms_template: Optional[str] = None
    sms_fallback_delay_hours: Optional[int] = None


# =============================================================================
# CAMPAIGN CRUD
# =============================================================================

@router.get("")
async def list_campaigns(request: Request, status: Optional[str] = None):
    """List all campaigns, optionally filtered by status."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                """SELECT * FROM v_campaign_overview
                   WHERE status = $1
                   ORDER BY created_at DESC""",
                status
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM v_campaign_overview ORDER BY created_at DESC"
            )
        return [dict(r) for r in rows]


@router.get("/{campaign_id}")
async def get_campaign(request: Request, campaign_id: str):
    """Get campaign details with steps."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        campaign = await conn.fetchrow(
            "SELECT * FROM campaigns WHERE id = $1", campaign_id
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        steps = await conn.fetch(
            """SELECT cs.*, q.title as quiz_title
               FROM campaign_steps cs
               LEFT JOIN quizzes q ON q.id = cs.quiz_id
               WHERE cs.campaign_id = $1
               ORDER BY cs.step_order""",
            campaign_id
        )

        result = dict(campaign)
        result["steps"] = [dict(s) for s in steps]
        return result


@router.post("")
async def create_campaign(request: Request, body: CampaignCreate):
    """Create a new campaign."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO campaigns (name, description, conversion_window_days)
               VALUES ($1, $2, $3)
               RETURNING *""",
            body.name, body.description, body.conversion_window_days
        )
        return dict(row)


@router.put("/{campaign_id}")
async def update_campaign(request: Request, campaign_id: str, body: CampaignUpdate):
    """Update campaign details."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM campaigns WHERE id = $1", campaign_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Campaign not found")

        updates = body.dict(exclude_unset=True)
        if not updates:
            return dict(existing)

        set_clauses = []
        params = []
        for i, (key, val) in enumerate(updates.items(), start=1):
            set_clauses.append(f"{key} = ${i}")
            params.append(val)
        params.append(campaign_id)

        row = await conn.fetchrow(
            f"""UPDATE campaigns SET {', '.join(set_clauses)}
                WHERE id = ${len(params)}
                RETURNING *""",
            *params
        )
        return dict(row)


@router.delete("/{campaign_id}")
async def delete_campaign(request: Request, campaign_id: str):
    """Delete a campaign (soft archive)."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE campaigns SET status = 'archived'
               WHERE id = $1 RETURNING *""",
            campaign_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return {"status": "archived", "id": campaign_id}


# =============================================================================
# CAMPAIGN LIFECYCLE
# =============================================================================

@router.post("/{campaign_id}/launch")
async def launch_campaign(request: Request, campaign_id: str):
    """Launch a campaign (set status to active)."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        campaign = await conn.fetchrow(
            "SELECT * FROM campaigns WHERE id = $1", campaign_id
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if campaign["status"] == "active":
            raise HTTPException(status_code=400, detail="Campaign is already active")

        # Verify campaign has at least one step
        step_count = await conn.fetchval(
            "SELECT COUNT(*) FROM campaign_steps WHERE campaign_id = $1",
            campaign_id
        )
        if step_count == 0:
            raise HTTPException(status_code=400, detail="Campaign must have at least one step")

        row = await conn.fetchrow(
            """UPDATE campaigns SET status = 'active'
               WHERE id = $1 RETURNING *""",
            campaign_id
        )
        return dict(row)


@router.post("/{campaign_id}/pause")
async def pause_campaign(request: Request, campaign_id: str):
    """Pause an active campaign."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE campaigns SET status = 'paused'
               WHERE id = $1 AND status = 'active'
               RETURNING *""",
            campaign_id
        )
        if not row:
            raise HTTPException(status_code=400, detail="Campaign is not active or not found")
        return dict(row)


@router.post("/{campaign_id}/archive")
async def archive_campaign(request: Request, campaign_id: str):
    """Archive a campaign."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE campaigns SET status = 'archived'
               WHERE id = $1 RETURNING *""",
            campaign_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return dict(row)


# =============================================================================
# CAMPAIGN STEPS
# =============================================================================

@router.get("/{campaign_id}/steps")
async def list_steps(request: Request, campaign_id: str):
    """List all steps for a campaign."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT cs.*, q.title as quiz_title
               FROM campaign_steps cs
               LEFT JOIN quizzes q ON q.id = cs.quiz_id
               WHERE cs.campaign_id = $1
               ORDER BY cs.step_order""",
            campaign_id
        )
        return [dict(r) for r in rows]


@router.post("/{campaign_id}/steps")
async def create_step(request: Request, campaign_id: str, body: CampaignStepCreate):
    """Add a step to a campaign."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Verify campaign exists
        exists = await conn.fetchval(
            "SELECT 1 FROM campaigns WHERE id = $1", campaign_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Campaign not found")

        row = await conn.fetchrow(
            """INSERT INTO campaign_steps
               (campaign_id, step_order, delay_hours, email_subject, email_body,
                email_template_id, quiz_id, sms_enabled, sms_template, sms_fallback_delay_hours)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING *""",
            campaign_id, body.step_order, body.delay_hours,
            body.email_subject, body.email_body, body.email_template_id,
            body.quiz_id, body.sms_enabled, body.sms_template,
            body.sms_fallback_delay_hours
        )
        return dict(row)


@router.put("/{campaign_id}/steps/{step_id}")
async def update_step(request: Request, campaign_id: str, step_id: str, body: CampaignStepUpdate):
    """Update a campaign step."""
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
        params.extend([step_id, campaign_id])

        row = await conn.fetchrow(
            f"""UPDATE campaign_steps SET {', '.join(set_clauses)}
                WHERE id = ${len(params) - 1} AND campaign_id = ${len(params)}
                RETURNING *""",
            *params
        )
        if not row:
            raise HTTPException(status_code=404, detail="Step not found")
        return dict(row)


@router.delete("/{campaign_id}/steps/{step_id}")
async def delete_step(request: Request, campaign_id: str, step_id: str):
    """Delete a campaign step."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM campaign_steps WHERE id = $1 AND campaign_id = $2",
            step_id, campaign_id
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Step not found")
        return {"status": "deleted", "id": step_id}


# =============================================================================
# CAMPAIGN ANALYTICS (Quick)
# =============================================================================

@router.get("/{campaign_id}/analytics")
async def get_campaign_analytics(
    request: Request,
    campaign_id: str,
    days: int = 30
):
    """Get analytics for a campaign over the last N days."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM campaign_analytics
               WHERE campaign_id = $1 AND date >= CURRENT_DATE - $2::INTEGER
               ORDER BY date DESC""",
            campaign_id, days
        )
        return [dict(r) for r in rows]
