"""
LITTLE NATE — Quiz API
CRUD operations for quizzes and quiz questions.
Client-facing quiz submission and completion tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.api_server import get_current_user as _require_auth
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
import json
import logging
import uuid as _uuid

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"], dependencies=[Depends(_require_auth)])

_CLIENT_SUBMISSIONS_TABLE_ENSURED = False

async def _ensure_submissions_table(pool):
    global _CLIENT_SUBMISSIONS_TABLE_ENSURED
    if _CLIENT_SUBMISSIONS_TABLE_ENSURED:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS quiz_client_submissions (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    user_id TEXT NOT NULL,
                    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
                    answers JSONB NOT NULL DEFAULT '{}',
                    score NUMERIC,
                    insights TEXT,
                    completed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, quiz_id)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_quiz_client_sub_user
                ON quiz_client_submissions(user_id, completed_at DESC)
            """)
        _CLIENT_SUBMISSIONS_TABLE_ENSURED = True
    except Exception as e:
        _log.warning("quiz_client_submissions table ensure failed: %s", e)


# =============================================================================
# MODELS
# =============================================================================

class QuizCreate(BaseModel):
    title: str
    description: Optional[str] = None
    theme: Optional[str] = None
    dimension: Optional[str] = None
    quiz_order: int
    is_final: bool = False

class QuizUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    theme: Optional[str] = None
    dimension: Optional[str] = None
    quiz_order: Optional[int] = None
    is_final: Optional[bool] = None

class QuestionCreate(BaseModel):
    question_order: int
    question_text: str
    question_type: str  # scale, multiple_choice, multi_select, ranking, open_text
    options: Optional[List[Any]] = []
    scale_min: int = 1
    scale_max: int = 10
    scale_min_label: Optional[str] = None
    scale_max_label: Optional[str] = None
    dimension_tag: Optional[str] = None

class QuestionUpdate(BaseModel):
    question_order: Optional[int] = None
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    options: Optional[List[Any]] = None
    scale_min: Optional[int] = None
    scale_max: Optional[int] = None
    scale_min_label: Optional[str] = None
    scale_max_label: Optional[str] = None
    dimension_tag: Optional[str] = None

class QuestionReorder(BaseModel):
    question_ids: List[str]  # Ordered list of question UUIDs


# =============================================================================
# QUIZ CRUD
# =============================================================================

@router.get("")
async def list_quizzes(request: Request):
    """List all quizzes in order."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT q.*,
                      (SELECT COUNT(*) FROM quiz_questions qq WHERE qq.quiz_id = q.id) as question_count
               FROM quizzes q
               ORDER BY q.quiz_order"""
        )
        return [dict(r) for r in rows]


@router.get("/health")
async def quiz_health(request: Request):
    """Health check for quiz subsystem."""
    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM quizzes")
        return {"status": "ok", "quiz_count": count}
    except Exception as e:
        _log.warning("quiz_health: %s", e)
        return {"status": "degraded", "error": str(e)}


@router.get("/completions/{user_id}")
async def get_completions(request: Request, user_id: str):
    """Return list of quiz IDs this user has completed with dimension scores."""
    pool = request.app.state.db_pool
    await _ensure_submissions_table(pool)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT s.quiz_id::text, s.score, s.insights, s.answers, s.completed_at,
                      q.title as quiz_title, q.dimension
               FROM quiz_client_submissions s
               JOIN quizzes q ON q.id = s.quiz_id
               WHERE s.user_id = $1 ORDER BY s.completed_at DESC""",
            user_id,
        )
    results = []
    for r in rows:
        answers = r["answers"]
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except Exception:
                answers = {}
        dim_scores = answers.get("_dimension_scores", {}) if isinstance(answers, dict) else {}
        results.append({
            "quiz_id": r["quiz_id"],
            "quiz_title": r["quiz_title"],
            "dimension": r["dimension"],
            "score": float(r["score"]) if r["score"] is not None else None,
            "dimension_scores": dim_scores,
            "insights": r["insights"],
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
        })
    return results


@router.get("/assessment-context/{user_id}")
async def get_assessment_context(request: Request, user_id: str):
    """Return assessment summary for AI conversation context injection."""
    pool = request.app.state.db_pool
    await _ensure_submissions_table(pool)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT s.score, s.insights, s.answers, s.completed_at,
                      q.title as quiz_title, q.dimension
               FROM quiz_client_submissions s
               JOIN quizzes q ON q.id = s.quiz_id
               WHERE s.user_id = $1 ORDER BY s.completed_at DESC
               LIMIT 10""",
            user_id,
        )

    if not rows:
        return {"has_assessments": False, "context": ""}

    parts = []
    for r in rows:
        answers = r["answers"]
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except Exception:
                answers = {}
        dim_scores = answers.get("_dimension_scores", {}) if isinstance(answers, dict) else {}
        score = float(r["score"]) if r["score"] is not None else None
        title = r["quiz_title"] or "Assessment"
        completed = r["completed_at"].strftime("%b %d, %Y") if r["completed_at"] else "Unknown date"

        dim_parts = []
        for dim, val in dim_scores.items():
            dim_parts.append(f"{dim.replace('_', ' ').title()}: {val}%")

        line = f"- {title} (completed {completed}): Overall {score}%"
        if dim_parts:
            line += f" | Dimensions: {', '.join(dim_parts)}"
        if r["insights"]:
            line += f" | Insights: {r['insights']}"
        parts.append(line)

    return {
        "has_assessments": True,
        "assessment_count": len(rows),
        "context": "\n".join(parts),
    }


@router.get("/{quiz_id}")
async def get_quiz(request: Request, quiz_id: str):
    """Get quiz with all questions."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        quiz = await conn.fetchrow(
            "SELECT * FROM quizzes WHERE id = $1", quiz_id
        )
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        questions = await conn.fetch(
            """SELECT * FROM quiz_questions
               WHERE quiz_id = $1
               ORDER BY question_order""",
            quiz_id
        )

        result = dict(quiz)
        result["questions"] = [dict(q) for q in questions]
        return result


@router.post("")
async def create_quiz(request: Request, body: QuizCreate):
    """Create a new quiz."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO quizzes (title, description, theme, dimension, quiz_order, is_final)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            body.title, body.description, body.theme, body.dimension,
            body.quiz_order, body.is_final
        )
        return dict(row)


@router.put("/{quiz_id}")
async def update_quiz(request: Request, quiz_id: str, body: QuizUpdate):
    """Update quiz details."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM quizzes WHERE id = $1", quiz_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Quiz not found")

        updates = body.dict(exclude_unset=True)
        if not updates:
            return dict(existing)

        set_clauses = []
        params = []
        for i, (key, val) in enumerate(updates.items(), start=1):
            set_clauses.append(f"{key} = ${i}")
            params.append(val)
        params.append(quiz_id)

        row = await conn.fetchrow(
            f"""UPDATE quizzes SET {', '.join(set_clauses)}
                WHERE id = ${len(params)}
                RETURNING *""",
            *params
        )
        return dict(row)


@router.delete("/{quiz_id}")
async def delete_quiz(request: Request, quiz_id: str):
    """Delete a quiz."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM quizzes WHERE id = $1", quiz_id
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Quiz not found")
        return {"status": "deleted", "id": quiz_id}


# =============================================================================
# CLIENT QUIZ SUBMISSION & COMPLETION
# =============================================================================

class QuizSubmitBody(BaseModel):
    quiz_id: str
    user_id: str
    answers: dict


@router.post("/{quiz_id}/submit")
async def submit_quiz(request: Request, quiz_id: str, body: QuizSubmitBody):
    """Submit client answers for a quiz and receive dimension-based scores."""
    pool = request.app.state.db_pool
    await _ensure_submissions_table(pool)

    async with pool.acquire() as conn:
        quiz = await conn.fetchrow("SELECT id, title, dimension FROM quizzes WHERE id = $1", quiz_id)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        questions = await conn.fetch(
            """SELECT id::text, question_order, question_type, dimension_tag,
                      scale_min, scale_max, options
               FROM quiz_questions WHERE quiz_id = $1 ORDER BY question_order""",
            quiz_id,
        )

        q_count = len(questions)
        answered = len(body.answers)
        dimension_scores: dict[str, list[float]] = {}
        q_map = {str(q["question_order"]): q for q in questions}

        for key, answer in body.answers.items():
            q = q_map.get(str(key))
            if not q:
                continue
            dim = q["dimension_tag"] or "general"
            qtype = q["question_type"] or "scale"

            if qtype == "scale" and answer is not None:
                try:
                    val = float(answer)
                    lo = q["scale_min"] or 1
                    hi = q["scale_max"] or 10
                    normalized = round(((val - lo) / max(hi - lo, 1)) * 100)
                    dimension_scores.setdefault(dim, []).append(normalized)
                except (ValueError, TypeError):
                    pass
            elif qtype in ("multiple_choice", "multi_select") and answer is not None:
                opts = q["options"]
                if isinstance(opts, str):
                    try:
                        opts = json.loads(opts)
                    except Exception:
                        opts = []
                if isinstance(opts, list) and opts:
                    n = len(opts)
                    ans_val = str(answer)
                    for idx, opt in enumerate(opts):
                        opt_key = str(opt.get("value") or opt.get("id") or opt.get("text") or "")
                        if opt_key == ans_val:
                            normalized = round(((idx + 1) / n) * 100)
                            dimension_scores.setdefault(dim, []).append(normalized)
                            break

        dim_averages = {}
        for dim, vals in dimension_scores.items():
            dim_averages[dim] = round(sum(vals) / len(vals)) if vals else 0

        overall_score = round(sum(dim_averages.values()) / max(len(dim_averages), 1)) if dim_averages else 0

        insight_parts = []
        for dim, avg in sorted(dim_averages.items(), key=lambda x: x[1]):
            label = dim.replace("_", " ").title()
            if avg >= 70:
                insight_parts.append(f"{label}: strong ({avg}%)")
            elif avg >= 40:
                insight_parts.append(f"{label}: developing ({avg}%)")
            else:
                insight_parts.append(f"{label}: area for growth ({avg}%)")
        insights_text = "; ".join(insight_parts) if insight_parts else f"Completed {answered}/{q_count} questions."

        sub_id = _uuid.uuid4()
        submission_data = json.dumps({
            **body.answers,
            "_dimension_scores": dim_averages,
            "_overall_score": overall_score,
        })
        await conn.execute(
            """INSERT INTO quiz_client_submissions (id, user_id, quiz_id, answers, score, insights)
               VALUES ($1, $2, $3, $4::jsonb, $5, $6)
               ON CONFLICT (user_id, quiz_id) DO UPDATE
               SET answers = EXCLUDED.answers, score = EXCLUDED.score,
                   insights = EXCLUDED.insights, completed_at = NOW()""",
            sub_id, body.user_id, quiz_id,
            submission_data, overall_score, insights_text,
        )

        try:
            await conn.execute(
                """INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                   VALUES ('assessment', 'assessment_completion', $1, 'info', NOW())""",
                f"Assessment: {quiz['title']} by {body.user_id} — score {overall_score}% ({answered}/{q_count} answered)",
            )
        except Exception:
            pass

    return {
        "status": "submitted",
        "score": overall_score,
        "dimension_scores": dim_averages,
        "insights": insights_text,
        "quiz_id": quiz_id,
        "answered": answered,
        "total_questions": q_count,
    }


# =============================================================================
# QUIZ QUESTIONS
# =============================================================================

@router.get("/{quiz_id}/questions")
async def list_questions(request: Request, quiz_id: str):
    """List all questions for a quiz."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM quiz_questions
               WHERE quiz_id = $1
               ORDER BY question_order""",
            quiz_id
        )
        return [dict(r) for r in rows]


@router.post("/{quiz_id}/questions")
async def create_question(request: Request, quiz_id: str, body: QuestionCreate):
    """Add a question to a quiz."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Verify quiz exists
        exists = await conn.fetchval(
            "SELECT 1 FROM quizzes WHERE id = $1", quiz_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Quiz not found")

        row = await conn.fetchrow(
            """INSERT INTO quiz_questions
               (quiz_id, question_order, question_text, question_type,
                options, scale_min, scale_max, scale_min_label, scale_max_label, dimension_tag)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)
               RETURNING *""",
            quiz_id, body.question_order, body.question_text, body.question_type,
            json.dumps(body.options), body.scale_min, body.scale_max,
            body.scale_min_label, body.scale_max_label, body.dimension_tag
        )
        return dict(row)


@router.put("/{quiz_id}/questions/{question_id}")
async def update_question(request: Request, quiz_id: str, question_id: str, body: QuestionUpdate):
    """Update a quiz question."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        updates = body.dict(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        set_clauses = []
        params = []
        for i, (key, val) in enumerate(updates.items(), start=1):
            if key == "options":
                set_clauses.append(f"options = ${i}::jsonb")
                params.append(json.dumps(val))
            else:
                set_clauses.append(f"{key} = ${i}")
                params.append(val)
        params.extend([question_id, quiz_id])

        row = await conn.fetchrow(
            f"""UPDATE quiz_questions SET {', '.join(set_clauses)}
                WHERE id = ${len(params) - 1} AND quiz_id = ${len(params)}
                RETURNING *""",
            *params
        )
        if not row:
            raise HTTPException(status_code=404, detail="Question not found")
        return dict(row)


@router.delete("/{quiz_id}/questions/{question_id}")
async def delete_question(request: Request, quiz_id: str, question_id: str):
    """Delete a quiz question."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM quiz_questions WHERE id = $1 AND quiz_id = $2",
            question_id, quiz_id
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Question not found")
        return {"status": "deleted", "id": question_id}


@router.post("/{quiz_id}/questions/reorder")
async def reorder_questions(request: Request, quiz_id: str, body: QuestionReorder):
    """Reorder questions by providing ordered list of question IDs."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        async with conn.transaction():
            for order, qid in enumerate(body.question_ids, start=1):
                await conn.execute(
                    """UPDATE quiz_questions
                       SET question_order = $1
                       WHERE id = $2 AND quiz_id = $3""",
                    order, qid, quiz_id
                )
        return {"status": "reordered", "count": len(body.question_ids)}
