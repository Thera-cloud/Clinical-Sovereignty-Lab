"""
LITTLE NATE — Response API
Public endpoint for quiz submissions. Triggers insight pipeline.
"""

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
import json

router = APIRouter(prefix="/api/responses", tags=["responses"])


# =============================================================================
# MODELS
# =============================================================================

class QuizSubmission(BaseModel):
    token: str                               # Prospect access token (email-based or UUID)
    quiz_id: str
    responses: List[dict]                    # Array of {question_id, answer, type}
    started_at: Optional[str] = None
    duration_seconds: Optional[int] = None


# =============================================================================
# QUIZ RESPONSE SUBMISSION
# =============================================================================

@router.post("")
async def submit_quiz_response(
    request: Request,
    body: QuizSubmission,
    background_tasks: BackgroundTasks
):
    """
    Public endpoint: Submit quiz responses.
    Token = prospect email or prospect_id.
    Triggers insight generation in background.
    """
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Resolve prospect from token (try by ID first, then by email)
        prospect = await conn.fetchrow(
            "SELECT * FROM prospects WHERE id::text = $1 OR email = $1",
            body.token
        )
        if not prospect:
            raise HTTPException(status_code=404, detail="Invalid token — prospect not found")

        if prospect["status"] == "unsubscribed":
            raise HTTPException(status_code=403, detail="Prospect has unsubscribed")

        # Verify quiz exists
        quiz = await conn.fetchrow(
            "SELECT * FROM quizzes WHERE id = $1", body.quiz_id
        )
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        # Check if already responded to this quiz
        existing = await conn.fetchrow(
            "SELECT id FROM quiz_responses WHERE prospect_id = $1 AND quiz_id = $2",
            prospect["id"], body.quiz_id
        )
        if existing:
            raise HTTPException(status_code=409, detail="Already submitted responses for this quiz")

        # Parse started_at
        started_at = None
        if body.started_at:
            try:
                started_at = datetime.fromisoformat(body.started_at.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Store response
        response_row = await conn.fetchrow(
            """INSERT INTO quiz_responses
               (prospect_id, quiz_id, campaign_id, responses, started_at, duration_seconds)
               VALUES ($1, $2, $3, $4::jsonb, $5, $6)
               RETURNING *""",
            prospect["id"], body.quiz_id, prospect["current_campaign_id"],
            json.dumps(body.responses), started_at, body.duration_seconds
        )

        # Update prospect story store progress
        await conn.execute(
            """UPDATE prospect_story_store
               SET last_quiz_completed = GREATEST(last_quiz_completed, $2),
                   quizzes_completed = quizzes_completed + 1
               WHERE prospect_id = $1""",
            prospect["id"], quiz["quiz_order"]
        )

        # If this is the final quiz, update prospect status
        if quiz["is_final"]:
            await conn.execute(
                """UPDATE prospects
                   SET status = 'quiz_complete', journey_completed_at = NOW()
                   WHERE id = $1""",
                prospect["id"]
            )

        # Trigger insight generation in background
        background_tasks.add_task(
            _generate_insight_background,
            request.app.state.db_pool,
            str(prospect["id"]),
            str(body.quiz_id),
            quiz["is_final"]
        )

        return {
            "status": "submitted",
            "response_id": str(response_row["id"]),
            "quiz_order": quiz["quiz_order"],
            "is_final": quiz["is_final"],
            "message": "Your responses have been received. Little Nate is preparing your insight..."
        }


async def _generate_insight_background(db_pool, prospect_id: str, quiz_id: str, is_final: bool):
    """Background task to generate insight after quiz submission."""
    try:
        from app.services.insight_engine import InsightEngine
        engine = InsightEngine(db_pool)
        await engine.generate_insight(prospect_id, quiz_id)

        if is_final:
            await engine.generate_coaching_assessment(prospect_id)
    except Exception as e:
        print(f">>> [INSIGHT] Error generating insight for {prospect_id}: {e}")


# =============================================================================
# RESPONSE RETRIEVAL (Admin)
# =============================================================================

@router.get("/prospect/{prospect_id}")
async def get_prospect_responses(request: Request, prospect_id: str):
    """Get all quiz responses for a prospect."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT qr.*, q.title as quiz_title, q.quiz_order
               FROM quiz_responses qr
               JOIN quizzes q ON q.id = qr.quiz_id
               WHERE qr.prospect_id = $1
               ORDER BY q.quiz_order""",
            prospect_id
        )
        return [dict(r) for r in rows]


@router.get("/quiz/{quiz_id}")
async def get_quiz_responses(request: Request, quiz_id: str, page: int = 1, per_page: int = 50):
    """Get all responses for a specific quiz."""
    pool = request.app.state.db_pool
    offset = (page - 1) * per_page
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM quiz_responses WHERE quiz_id = $1", quiz_id
        )
        rows = await conn.fetch(
            """SELECT qr.*, p.email, p.first_name
               FROM quiz_responses qr
               JOIN prospects p ON p.id = qr.prospect_id
               WHERE qr.quiz_id = $1
               ORDER BY qr.completed_at DESC
               LIMIT $2 OFFSET $3""",
            quiz_id, per_page, offset
        )
        return {
            "responses": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page
        }
