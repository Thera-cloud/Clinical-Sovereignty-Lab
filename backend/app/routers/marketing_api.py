"""
LITTLE NATE — Marketing Brain API
Endpoints for the marketing playbook, funnel stats, actions, growth, and quiz factory.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.services.api_server import require_admin

router = APIRouter(prefix="/api/marketing", tags=["marketing"], dependencies=[Depends(require_admin)])

# Public HMAC-signed preview (no admin auth) — QUANTUM-CRYSTAL-ARCH
public_router = APIRouter(prefix="/api/marketing", tags=["marketing-public"])


# =============================================================================
# REQUEST MODELS
# =============================================================================

class PlaybookUpdate(BaseModel):
    content_pillars: Optional[list] = None
    target_audiences: Optional[dict] = None
    content_mix: Optional[dict] = None
    posting_schedule: Optional[dict] = None
    regional_focus: Optional[dict] = None
    collaboration_targets: Optional[list] = None


class CampaignProposal(BaseModel):
    target_audience: str
    objective: str
    platform: str = "all"


class ActionDecision(BaseModel):
    decision: str  # approved, rejected, deferred
    reason: Optional[str] = None


class QuizGenRequest(BaseModel):
    audience: str  # individual, coach, family, custom
    topic: str
    question_count: int = 8
    objective: Optional[str] = None


class ShowcaseRequest(BaseModel):
    scenario: str  # session, coach_demo, family, platform_overview
    format: str = "html"  # html, data


class GrowthContentCreate(BaseModel):
    content_type: str = Field(..., description="blog|email_drip|outreach|directory_page")
    title: str
    draft_body: str = ""
    platform: Optional[str] = None
    audience: str = "general"
    slug: Optional[str] = None
    keyword_cluster: Optional[str] = None
    generation_meta: Optional[Dict[str, Any]] = None
    submit_for_review: bool = False


class GrowthConfigUpdate(BaseModel):
    key: str
    value: Dict[str, Any]


class GrowthDecide(BaseModel):
    decision: str  # APPROVE|REJECT|REWRITE|DELAY|RETRACT
    note: Optional[str] = None
    scheduled_at: Optional[str] = None


class KeywordUpsert(BaseModel):
    keyword: str
    audience: str = "general"
    cluster: Optional[str] = None
    volume_norm: float = 0.0
    intent: float = 0.0
    audience_value: float = 0.0
    buyer_prior: float = 0.0
    demand_prior: float = 1.0
    notes: Optional[str] = None
    status: str = "queued"


class LeadUpsert(BaseModel):
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    npi: Optional[str] = None
    specialty: Optional[str] = None
    state: Optional[str] = None
    source: str = "manual"
    run_enrichment: bool = False


class NpiBatchIngest(BaseModel):
    rows: list = Field(default_factory=list)


class GdprErase(BaseModel):
    email: str


class ReplyEnqueue(BaseModel):
    email: str
    body: str
    lead_id: Optional[int] = None


class LandingCaptureBody(BaseModel):
    landing: str
    email: str
    name: Optional[str] = None
    org: Optional[str] = None
    website: Optional[str] = None  # honeypot
    meta: Optional[Dict[str, Any]] = None


# =============================================================================
# PLAYBOOK ENDPOINTS
# =============================================================================

@router.get("/playbook")
async def get_playbook(request: Request):
    """Get the current marketing playbook."""
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(request.app.state.db_pool)
    return await brain.get_playbook()


@router.put("/playbook")
async def update_playbook(updates: PlaybookUpdate, request: Request):
    """Update the marketing playbook."""
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(request.app.state.db_pool)
    data = {k: v for k, v in updates.dict().items() if v is not None}
    success = await brain.update_playbook(data)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update playbook")
    return {"status": "updated"}


@router.post("/playbook/review")
async def review_playbook(request: Request):
    """Run a full strategy review (AI-powered)."""
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(request.app.state.db_pool)
    return await brain.review_playbook()


# =============================================================================
# PERFORMANCE & ANALYTICS
# =============================================================================

@router.get("/results")
async def get_results(request: Request):
    """Get performance evaluation across all channels."""
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(request.app.state.db_pool)
    return await brain.evaluate_results()


@router.get("/funnel-stats")
async def get_funnel_stats(request: Request, days: int = Query(default=7, ge=1, le=90)):
    """Get funnel conversion statistics."""
    from app.services.funnel_router import FunnelRouter
    router_svc = FunnelRouter(request.app.state.db_pool)
    return await router_svc.get_funnel_stats(days=days)


@router.get("/growth")
async def get_growth_snapshots(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    snapshot_type: str = Query(default="daily")
):
    """Get growth snapshots for trend analysis."""
    try:
        async with request.app.state.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM growth_snapshots
                WHERE snapshot_type = $1
                  AND snapshot_date > CURRENT_DATE - $2
                ORDER BY snapshot_date DESC
            """, snapshot_type, days)
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ACTION MANAGEMENT (Command Protocol)
# =============================================================================

@router.get("/actions")
async def get_actions(
    request: Request,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100)
):
    """Get marketing actions with optional status filter."""
    try:
        async with request.app.state.db_pool.acquire() as conn:
            if status:
                rows = await conn.fetch("""
                    SELECT * FROM marketing_actions
                    WHERE status = $1
                    ORDER BY proposed_at DESC LIMIT $2
                """, status, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM marketing_actions
                    ORDER BY proposed_at DESC LIMIT $1
                """, limit)
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions/{action_id}/decide")
async def decide_action(action_id: int, decision: ActionDecision, request: Request):
    """Approve or reject a marketing action."""
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(request.app.state.db_pool)

    if decision.decision == "approved":
        result = await brain.approve_action(action_id)
        success = not result.get("error")
    elif decision.decision == "rejected":
        success = await brain.reject_action(action_id, reason=decision.reason or "")
    elif decision.decision == "deferred":
        try:
            async with request.app.state.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE marketing_actions SET status = 'proposed'
                    WHERE id = $1
                """, action_id)
            success = True
        except Exception:
            success = False
    else:
        raise HTTPException(status_code=400, detail="Invalid decision")

    if not success:
        raise HTTPException(status_code=400, detail="Action update failed")
    return {"status": decision.decision, "action_id": action_id}


@router.post("/actions/propose-campaign")
async def propose_campaign(proposal: CampaignProposal, request: Request):
    """Manually propose a new campaign."""
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(request.app.state.db_pool)
    return await brain.propose_campaign(
        target_audience=proposal.target_audience,
        objective=proposal.objective,
        platform=proposal.platform,
    )


# =============================================================================
# QUIZ FACTORY
# =============================================================================

@router.post("/quiz-factory/generate")
async def generate_quiz(gen_request: QuizGenRequest, request: Request):
    """Generate a new quiz using AI."""
    from app.services.quiz_factory import QuizFactory
    factory = QuizFactory(request.app.state.db_pool)
    return await factory.create_quiz(
        audience=gen_request.audience,
        topic=gen_request.topic,
        question_count=gen_request.question_count,
        objective=gen_request.objective,
    )


@router.post("/quiz-factory/clone/{quiz_id}")
async def clone_quiz(quiz_id: int, request: Request, audience: str = Query(...)):
    """Clone an existing quiz and adapt it for a new audience."""
    from app.services.quiz_factory import QuizFactory
    factory = QuizFactory(request.app.state.db_pool)
    return await factory.clone_and_adapt(quiz_id, audience)


@router.get("/quiz-factory/performance/{quiz_id}")
async def quiz_performance(quiz_id: int, request: Request):
    """Get quiz performance analytics."""
    from app.services.quiz_factory import QuizFactory
    factory = QuizFactory(request.app.state.db_pool)
    return await factory.analyze_quiz_performance(quiz_id)


# =============================================================================
# SHOWCASE GENERATOR
# =============================================================================

@router.post("/showcase/generate")
async def generate_showcase(showcase_req: ShowcaseRequest, request: Request):
    """Generate a demo showcase for platform marketing."""
    from app.services.showcase_generator import ShowcaseGenerator
    gen = ShowcaseGenerator(request.app.state.db_pool)

    if showcase_req.scenario == "session":
        return await gen.generate_session_showcase()
    elif showcase_req.scenario == "coach_demo":
        return await gen.generate_coach_demo()
    elif showcase_req.scenario == "family":
        return await gen.generate_family_showcase()
    elif showcase_req.scenario == "platform_overview":
        return await gen.generate_platform_overview()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {showcase_req.scenario}")


# =============================================================================
# A/B TESTING
# =============================================================================

@router.get("/ab-tests")
async def get_ab_tests(request: Request, status: str = Query(default="running")):
    """Get A/B tests."""
    try:
        async with request.app.state.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM content_ab_tests
                WHERE status = $1
                ORDER BY started_at DESC
            """, status)
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/post-analytics")
async def get_post_analytics(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    platform: str = Query(default=None),
):
    """Per-post performance metrics from the Notification Observer."""
    try:
        pool = request.app.state.db_pool
        async with pool.acquire() as conn:
            if platform:
                rows = await conn.fetch("""
                    SELECT platform, post_id, post_url, post_text,
                           likes, reposts, comments, impressions, captured_at
                    FROM skyeye_post_analytics
                    WHERE platform = $1
                      AND captured_at > NOW() - make_interval(days => $2)
                    ORDER BY captured_at DESC
                    LIMIT 100
                """, platform, days)
            else:
                rows = await conn.fetch("""
                    SELECT platform, post_id, post_url, post_text,
                           likes, reposts, comments, impressions, captured_at
                    FROM skyeye_post_analytics
                    WHERE captured_at > NOW() - make_interval(days => $1)
                    ORDER BY captured_at DESC
                    LIMIT 100
                """, days)
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications")
async def get_notifications(
    request: Request,
    limit: int = Query(default=50, le=200),
    processed: str = Query(default="all"),
):
    """Social engagement notifications detected by the Notification Observer."""
    try:
        pool = request.app.state.db_pool
        async with pool.acquire() as conn:
            if processed == "unprocessed":
                rows = await conn.fetch("""
                    SELECT id, platform, notification_type, post_id,
                           actor_handle, actor_id, actor_bio, actor_followers,
                           processed, created_at
                    FROM skyeye_notifications
                    WHERE processed = FALSE
                    ORDER BY created_at DESC LIMIT $1
                """, limit)
            elif processed == "processed":
                rows = await conn.fetch("""
                    SELECT id, platform, notification_type, post_id,
                           actor_handle, actor_id, actor_bio, actor_followers,
                           processed, created_at
                    FROM skyeye_notifications
                    WHERE processed = TRUE
                    ORDER BY created_at DESC LIMIT $1
                """, limit)
            else:
                rows = await conn.fetch("""
                    SELECT id, platform, notification_type, post_id,
                           actor_handle, actor_id, actor_bio, actor_followers,
                           processed, created_at
                    FROM skyeye_notifications
                    ORDER BY created_at DESC LIMIT $1
                """, limit)
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ADAPTIVE GROWTH ENGINE — QUANTUM-CRYSTAL-ARCH
# =============================================================================

def _growth_svc(request: Request):
    from app.services.growth.marketing_content_service import MarketingContentService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    return MarketingContentService(pool)


@router.get("/growth/health")
async def growth_health(request: Request):
    from app.services.growth import (
        content_factory_enabled,
        growth_engine_enabled,
        outreach_engine_enabled,
    )
    from app.services.growth.instantly_client import InstantlyClient
    from app.services.growth.sender_guard import validate_outreach_sender_domains
    from app.services.growth.studio_budget import factory_generation_mode

    ok_sender, sender_msg = validate_outreach_sender_domains(
        require_when_outreach_enabled=True
    )
    instantly = await InstantlyClient().health()
    studio = await factory_generation_mode(
        request.app.state.db_pool, getattr(request.app.state, "redis", None)
    )
    return {
        "status": "ok",
        "enable_growth_engine": growth_engine_enabled(),
        "enable_content_factory": content_factory_enabled(),
        "enable_outreach_engine": outreach_engine_enabled(),
        "sender_guard": {"ok": ok_sender, "message": sender_msg},
        "instantly": instantly,
        "studio": studio,
        "newsletter": {
            "note": "Dispatch owns newsletter — open newsletter_dispatch.html",
            "deep_link": "/newsletter_dispatch.html",
        },
    }


@router.get("/growth/content")
async def list_growth_content(
    request: Request,
    status: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    svc = _growth_svc(request)
    return {
        "status": "ok",
        "items": await svc.list(
            status=status, content_type=content_type, limit=limit
        ),
    }


@router.post("/growth/content")
async def create_growth_content(body: GrowthContentCreate, request: Request):
    svc = _growth_svc(request)
    try:
        item = await svc.create(
            content_type=body.content_type,
            title=body.title,
            draft_body=body.draft_body,
            platform=body.platform or "",
            audience=body.audience,
            slug=body.slug,
            keyword_cluster=body.keyword_cluster,
            generation_meta=body.generation_meta,
            created_by="admin",
            submit_for_review=body.submit_for_review,
        )
        return {"status": "ok", "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/growth/content/{content_id}")
async def get_growth_content(content_id: int, request: Request):
    svc = _growth_svc(request)
    item = await svc.get(content_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    return {"status": "ok", "item": item}


@router.post("/growth/content/{content_id}/submit")
async def submit_growth_content(content_id: int, request: Request):
    svc = _growth_svc(request)
    try:
        item = await svc.submit_for_review(content_id, actor="admin")
        return {"status": "ok", "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/growth/content/{content_id}/decide")
async def decide_growth_content(content_id: int, body: GrowthDecide, request: Request):
    from datetime import datetime, timezone

    svc = _growth_svc(request)
    scheduled = None
    if body.scheduled_at:
        try:
            scheduled = datetime.fromisoformat(body.scheduled_at.replace("Z", "+00:00"))
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid scheduled_at")
    try:
        item = await svc.apply_ceo_decision(
            content_id,
            decision=body.decision,
            actor="admin",
            note=body.note or "",
            scheduled_at=scheduled,
        )
        return {"status": "ok", "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/growth/config")
async def get_growth_config(request: Request):
    svc = _growth_svc(request)
    return {"status": "ok", "config": await svc.get_growth_config()}


@router.put("/growth/config")
async def put_growth_config(body: GrowthConfigUpdate, request: Request):
    svc = _growth_svc(request)
    result = await svc.set_growth_config(body.key, body.value, updated_by="admin")
    return {"status": "ok", **result}


@router.get("/growth/spend")
async def get_growth_spend(request: Request, month: Optional[str] = None):
    svc = _growth_svc(request)
    return {"status": "ok", **(await svc.spend_summary(month=month))}


@router.get("/growth/keywords")
async def list_growth_keywords(
    request: Request,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    from app.services.growth.keyword_queue import KeywordQueueService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    items = await KeywordQueueService(pool).list(status=status, limit=limit)
    return {"status": "ok", "items": items}


@router.post("/growth/keywords")
async def upsert_growth_keyword(body: KeywordUpsert, request: Request):
    from app.services.growth.keyword_queue import KeywordQueueService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    try:
        item = await KeywordQueueService(pool).upsert(**body.dict())
        return {"status": "ok", "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/growth/factory/tick")
async def growth_factory_tick(request: Request):
    """Manual factory tick (admin). Requires ENABLE_CONTENT_FACTORY=true."""
    from app.services.growth import content_factory_enabled
    from app.services.growth.content_factory_worker import ContentFactoryWorker

    if not content_factory_enabled():
        raise HTTPException(status_code=400, detail="ENABLE_CONTENT_FACTORY=false")
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    worker = getattr(request.app.state, "content_factory", None)
    if worker in (None, "disabled", "init_failed") or not hasattr(worker, "tick"):
        worker = ContentFactoryWorker(
            pool,
            redis=getattr(request.app.state, "redis", None),
            app_state=request.app.state,
        )
    result = await worker.tick()
    return {"status": "ok", **result}


# QUANTUM-CRYSTAL-ARCH — Phase 3 outbound
@router.get("/growth/leads")
async def list_growth_leads(
    request: Request,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    from app.services.growth.buyer_leads import BuyerLeadsService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    items = await BuyerLeadsService(pool).list(status=status, limit=limit)
    return {"status": "ok", "items": items}


@router.post("/growth/leads")
async def upsert_growth_lead(body: LeadUpsert, request: Request):
    from app.services.growth.buyer_leads import BuyerLeadsService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    try:
        item = await BuyerLeadsService(pool).upsert_lead(**body.dict())
        return {"status": "ok", "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/growth/leads/npi-batch")
async def ingest_npi_batch(body: NpiBatchIngest, request: Request):
    from app.services.growth.buyer_leads import BuyerLeadsService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    result = await BuyerLeadsService(pool).ingest_npi_batch(body.rows or [])
    return {"status": "ok", **result}


@router.post("/growth/leads/{lead_id}/enrich")
async def enrich_growth_lead(lead_id: int, request: Request):
    from app.services.growth.buyer_leads import BuyerLeadsService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    try:
        item = await BuyerLeadsService(pool).enrich(lead_id)
        return {"status": "ok", "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/growth/leads/gdpr-erase")
async def gdpr_erase_lead(body: GdprErase, request: Request):
    from app.services.growth.buyer_leads import BuyerLeadsService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    try:
        result = await BuyerLeadsService(pool).gdpr_erase(body.email, actor="admin")
        return {"status": "ok", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/growth/replies")
async def list_outreach_replies(
    request: Request,
    status: str = "pending",
    limit: int = Query(default=50, le=200),
):
    from app.services.growth.buyer_leads import BuyerLeadsService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    items = await BuyerLeadsService(pool).list_replies(status=status, limit=limit)
    return {"status": "ok", "items": items}


@router.post("/growth/replies")
async def enqueue_outreach_reply(body: ReplyEnqueue, request: Request):
    """Enqueue a reply for human review — never auto-sends."""
    from app.services.growth.buyer_leads import BuyerLeadsService

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    item = await BuyerLeadsService(pool).enqueue_reply(
        email=body.email, body=body.body, lead_id=body.lead_id
    )
    return {"status": "ok", "item": item}


@router.post("/growth/outreach/tick")
async def growth_outreach_tick(request: Request):
    from app.services.growth import outreach_engine_enabled
    from app.services.growth.outreach_worker import OutreachWorker

    if not outreach_engine_enabled():
        raise HTTPException(status_code=400, detail="ENABLE_OUTREACH_ENGINE=false")
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    worker = getattr(request.app.state, "outreach_worker", None)
    if worker in (None, "disabled", "init_failed") or not hasattr(worker, "tick"):
        worker = OutreachWorker(pool)
    result = await worker.tick()
    return {"status": "ok", **result}


@public_router.post("/landing/capture")
async def public_landing_capture(body: LandingCaptureBody, request: Request):
    """Public providers/enterprise capture → SendGrid product drip (not Instantly)."""
    from app.services.growth.landing_capture import capture_landing

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    try:
        result = await capture_landing(
            pool,
            landing=body.landing,
            email=body.email,
            name=body.name,
            org=body.org,
            meta=body.meta,
            honeypot=body.website or "",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@public_router.get("/content/{content_id}/preview", response_class=HTMLResponse)
async def public_content_preview(
    content_id: int,
    request: Request,
    exp: str = Query(...),
    sig: str = Query(...),
):
    """HMAC-signed read-only preview for CEO emails (72h TTL)."""
    from app.services.growth.blog_publisher import body_to_html
    from app.services.growth.preview_links import parse_and_verify

    ok, reason = parse_and_verify(content_id, exp, sig)
    if not ok:
        raise HTTPException(status_code=403, detail=reason)
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT title, draft_body, content_type, status FROM marketing_content WHERE id = $1",
            int(content_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    body = body_to_html(row["draft_body"] or "")
    title = (row["title"] or "Draft").replace("<", "&lt;")
    return HTMLResponse(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>{title} — preview</title>
<style>body{{font-family:system-ui;background:#111;color:#eee;max-width:720px;margin:40px auto;padding:0 16px}}
.badge{{color:#C9A962;font-size:.85rem}}</style></head>
<body><p class="badge">{row['content_type']} · {row['status']} · signed preview</p>
<h1>{title}</h1>{body}</body></html>"""
    )
