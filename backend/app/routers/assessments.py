"""
LITTLE NATE — Dynamic Assessment REST API
Endpoints for generating, submitting, and reviewing AI-driven assessments.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.services.api_server import get_current_user as _require_auth

router = APIRouter(
    prefix="/api/assessments",
    tags=["assessments"],
    dependencies=[Depends(_require_auth)],
)


class SubmitAnswersRequest(BaseModel):
    answers: List[Dict[str, Any]]


class GenerateRequest(BaseModel):
    category: Optional[str] = None


def _get_engine(request: Request):
    engine = getattr(request.app.state, "assessment_engine", None)
    if not engine:
        raise HTTPException(503, "Assessment engine not available")
    return engine


@router.get("/available/{user_id}")
async def get_available_assessments(user_id: str, request: Request):
    """Get pending assessments and check if a new one should be generated."""
    engine = _get_engine(request)
    return await engine.get_available(user_id)


@router.get("/history/{user_id}")
async def get_assessment_history(user_id: str, request: Request, limit: int = 20):
    """Get completed assessment history for a client."""
    engine = _get_engine(request)
    return await engine.get_history(user_id, limit=limit)


@router.post("/generate/{user_id}")
async def generate_assessment(user_id: str, request: Request, body: GenerateRequest = None):
    """Generate a new personalized assessment for a client."""
    engine = _get_engine(request)
    category = body.category if body else None
    result = await engine.generate_assessment(user_id, category=category)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/submit/{assessment_id}")
async def submit_assessment(assessment_id: str, body: SubmitAnswersRequest, request: Request):
    """Submit answers for an assessment and receive AI analysis."""
    engine = _get_engine(request)
    result = await engine.submit_and_analyze(assessment_id, body.answers)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/growth/{user_id}")
async def get_growth_trajectory(user_id: str, request: Request):
    """Get growth trajectory across all completed assessments."""
    engine = _get_engine(request)
    return await engine.get_growth_trajectory(user_id)


@router.get("/triggers/{user_id}")
async def check_assessment_triggers(user_id: str, request: Request):
    """Check if a new assessment should be generated (milestones, time-based)."""
    engine = _get_engine(request)
    return await engine.check_triggers(user_id)


@router.get("/health")
async def assessment_health(request: Request):
    """Health check for Assessment Engine."""
    engine = getattr(request.app.state, "assessment_engine", None)
    pool = getattr(request.app.state, "db_pool", None)
    table_ok = False
    if pool:
        try:
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'dynamic_assessments'"
                )
                table_ok = count > 0
        except Exception:
            pass
    return {
        "status": "healthy" if engine and table_ok else "degraded",
        "engine_loaded": engine is not None,
        "table_exists": table_ok,
    }


@router.get("/{assessment_id}")
async def get_assessment_detail(assessment_id: str, request: Request):
    """Get full assessment detail including questions and responses."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        assessment = await conn.fetchrow("""
            SELECT id, user_id, category, title, questions, status, score,
                   insights, growth_markers, nate_reflection, completed_at, created_at
            FROM dynamic_assessments WHERE id = $1
        """, assessment_id)

        if not assessment:
            raise HTTPException(404, "Assessment not found")

        responses = await conn.fetch("""
            SELECT question_index, question_text, answer_text, answer_value, reflection
            FROM assessment_responses WHERE assessment_id = $1
            ORDER BY question_index
        """, assessment_id)

    import json
    questions = assessment["questions"]
    if isinstance(questions, str):
        questions = json.loads(questions)
    insights = assessment["insights"]
    if isinstance(insights, str):
        insights = json.loads(insights)
    growth = assessment["growth_markers"]
    if isinstance(growth, str):
        growth = json.loads(growth)

    return {
        "assessment_id": str(assessment["id"]),
        "user_id": str(assessment["user_id"]),
        "category": assessment["category"],
        "title": assessment["title"],
        "status": assessment["status"],
        "score": float(assessment["score"]) if assessment["score"] else None,
        "questions": questions,
        "responses": [
            {
                "question_index": r["question_index"],
                "question_text": r["question_text"],
                "answer_text": r["answer_text"],
                "answer_value": r["answer_value"],
                "reflection": r["reflection"],
            }
            for r in responses
        ],
        "insights": insights or {},
        "growth_markers": growth or [],
        "nate_reflection": assessment["nate_reflection"],
        "completed_at": assessment["completed_at"].isoformat() if assessment["completed_at"] else None,
        "created_at": assessment["created_at"].isoformat(),
    }
