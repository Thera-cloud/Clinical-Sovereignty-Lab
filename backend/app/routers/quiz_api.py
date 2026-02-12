"""
LITTLE NATE — Quiz API
CRUD operations for quizzes and quiz questions.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
import json

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])


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
