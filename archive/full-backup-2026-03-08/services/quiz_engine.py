"""
SOVEREIGN SWARM — Coherence Quiz Engine

Patent Claim 16: Quiz-to-Golden-Ticket pipeline. Generates personalized coherence
assessment quizzes that feed into the marketing funnel and therapeutic intake.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog

logger = structlog.get_logger(__name__)

# Coherence dimensions for question mapping
DIMENSIONS = ["emotional", "relational", "cultural", "spiritual", "somatic"]

# Default question bank templates (simplified; in production would come from DB)
DEFAULT_QUIZ_BANK = [
    {"dimension": "emotional", "text": "How often do you feel in tune with your emotions?", "options": [
        {"id": "a", "score": 4, "text": "Almost always"},
        {"id": "b", "score": 3, "text": "Often"},
        {"id": "c", "score": 2, "text": "Sometimes"},
        {"id": "d", "score": 1, "text": "Rarely"},
    ]},
    {"dimension": "emotional", "text": "How easily do you name what you're feeling?", "options": [
        {"id": "a", "score": 4, "text": "Very easily"},
        {"id": "b", "score": 3, "text": "Fairly easily"},
        {"id": "c", "score": 2, "text": "With difficulty"},
        {"id": "d", "score": 1, "text": "Rarely can"},
    ]},
    {"dimension": "relational", "text": "How connected do you feel to important people in your life?", "options": [
        {"id": "a", "score": 4, "text": "Deeply connected"},
        {"id": "b", "score": 3, "text": "Reasonably connected"},
        {"id": "c", "score": 2, "text": "Somewhat disconnected"},
        {"id": "d", "score": 1, "text": "Very disconnected"},
    ]},
    {"dimension": "relational", "text": "How well do you express your needs in relationships?", "options": [
        {"id": "a", "score": 4, "text": "Very well"},
        {"id": "b", "score": 3, "text": "Adequately"},
        {"id": "c", "score": 2, "text": "Struggle sometimes"},
        {"id": "d", "score": 1, "text": "Rarely"},
    ]},
    {"dimension": "cultural", "text": "How aligned do you feel with your cultural roots?", "options": [
        {"id": "a", "score": 4, "text": "Very aligned"},
        {"id": "b", "score": 3, "text": "Mostly aligned"},
        {"id": "c", "score": 2, "text": "Some tension"},
        {"id": "d", "score": 1, "text": "Significant disconnect"},
    ]},
    {"dimension": "cultural", "text": "How comfortable are you bridging different cultural contexts?", "options": [
        {"id": "a", "score": 4, "text": "Very comfortable"},
        {"id": "b", "score": 3, "text": "Fairly comfortable"},
        {"id": "c", "score": 2, "text": "Sometimes uneasy"},
        {"id": "d", "score": 1, "text": "Often uncomfortable"},
    ]},
    {"dimension": "spiritual", "text": "How connected do you feel to something larger than yourself?", "options": [
        {"id": "a", "score": 4, "text": "Deeply connected"},
        {"id": "b", "score": 3, "text": "Moderately connected"},
        {"id": "c", "score": 2, "text": "Occasionally"},
        {"id": "d", "score": 1, "text": "Rarely or never"},
    ]},
    {"dimension": "spiritual", "text": "How often do you experience meaning or purpose in daily life?", "options": [
        {"id": "a", "score": 4, "text": "Most days"},
        {"id": "b", "score": 3, "text": "Often"},
        {"id": "c", "score": 2, "text": "Sometimes"},
        {"id": "d", "score": 1, "text": "Rarely"},
    ]},
    {"dimension": "somatic", "text": "How aware are you of sensations in your body?", "options": [
        {"id": "a", "score": 4, "text": "Very aware"},
        {"id": "b", "score": 3, "text": "Aware"},
        {"id": "c", "score": 2, "text": "Sometimes"},
        {"id": "d", "score": 1, "text": "Rarely notice"},
    ]},
    {"dimension": "somatic", "text": "How well does your body signal when something is off?", "options": [
        {"id": "a", "score": 4, "text": "Very clearly"},
        {"id": "b", "score": 3, "text": "Fairly clearly"},
        {"id": "c", "score": 2, "text": "Sometimes"},
        {"id": "d", "score": 1, "text": "Rarely or not at all"},
    ]},
]


class CoherenceQuizEngine:
    """
    Patent Claim 16: Quiz-to-Golden-Ticket pipeline. Generates personalized
    coherence assessment quizzes that feed into the marketing funnel and
    therapeutic intake.
    """

    GOLDEN_TICKET_THRESHOLD = 60

    def __init__(self, db_pool: Optional[Any] = None) -> None:
        """
        Initialize CoherenceQuizEngine.

        Args:
            db_pool: Optional asyncpg pool for persisting quizzes and responses.
        """
        self._db = db_pool
        self._quiz_cache: Dict[str, List[Dict[str, Any]]] = {}  # quiz_id -> questions for scoring

    async def get_quiz_bank(self) -> List[Dict[str, Any]]:
        """
        Return available quiz templates.

        Returns:
            List of question templates with dimension, text, options.
        """
        if self._db:
            try:
                async with self._db.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT id, dimension_tag as dimension, question_text as text, options
                        FROM quiz_questions
                        ORDER BY quiz_id, question_order
                        LIMIT 50
                    """)
                    if rows:
                        result = []
                        for r in rows:
                            opts = r.get("options") or []
                            if isinstance(opts, str):
                                opts = json.loads(opts) if opts else []
                            mapped = []
                            for i, o in enumerate(opts):
                                val = o.get("value", o.get("id", str(i)))
                                label = o.get("label", o.get("text", ""))
                                mapped.append({"id": val, "text": label, "score": min(4, max(1, i + 1))})
                            result.append({
                                "id": str(r["id"]),
                                "dimension": r.get("dimension") or "emotional",
                                "text": r.get("text") or "",
                                "options": mapped or [{"id": "a", "text": "-", "score": 2}],
                            })
                        return result
            except Exception as e:
                logger.debug("quiz_bank_db_failed", error=str(e))

        return DEFAULT_QUIZ_BANK

    async def generate_quiz(
        self,
        prospect_id: Optional[str] = None,
        quiz_type: str = "coherence_baseline",
    ) -> Dict[str, Any]:
        """
        Generate a coherence assessment quiz.

        Args:
            prospect_id: Optional prospect identifier.
            quiz_type: Quiz type. Default "coherence_baseline".

        Returns:
            Dict with quiz_id, questions, metadata.
        """
        bank = await self.get_quiz_bank()
        n = min(15, max(10, len(bank)))
        selected = random.sample(bank, min(n, len(bank)))
        questions = []
        for i, q in enumerate(selected):
            options = q.get("options", [])
            questions.append({
                "id": str(uuid4()),
                "text": q.get("text", ""),
                "dimension": q.get("dimension", "emotional"),
                "options": [
                    {"id": o.get("id"), "text": o.get("text"), "score": o.get("score", 1)}
                    for o in options
                ],
            })

        quiz_id = str(uuid4())
        metadata = {
            "prospect_id": prospect_id,
            "quiz_type": quiz_type,
            "dimensions": list(set(q["dimension"] for q in questions)),
            "generated_at": datetime.utcnow().isoformat(),
        }

        self._quiz_cache[quiz_id] = questions

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO coherence_quiz_sessions (id, prospect_id, quiz_type, questions, metadata, created_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                    """, quiz_id, prospect_id, quiz_type, json.dumps(questions), json.dumps(metadata))
            except Exception as e:
                logger.debug("quiz_generate_persist_failed", quiz_id=quiz_id, error=str(e))

        logger.info("quiz_generated", quiz_id=quiz_id, question_count=len(questions))
        return {
            "quiz_id": quiz_id,
            "questions": questions,
            "metadata": metadata,
        }

    def _generate_golden_ticket(self, scores: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generate Golden Ticket if composite score indicates readiness.

        Args:
            scores: Dict with composite_score and possibly dimension scores.

        Returns:
            Ticket dict with ticket_id, tier_recommendation, valid_until, discount_code,
            or None if not eligible.
        """
        composite = scores.get("composite_score", 0)
        if composite < self.GOLDEN_TICKET_THRESHOLD:
            return None

        tier = "inner_chamber"
        if composite >= 80:
            tier = "sovereign_circle"
        elif composite >= 70:
            tier = "inner_chamber"

        ticket_id = str(uuid4())
        valid_until = (datetime.utcnow() + timedelta(days=14)).isoformat()
        discount_code = f"GT-{ticket_id[:8].upper()}"

        return {
            "ticket_id": ticket_id,
            "tier_recommendation": tier,
            "valid_until": valid_until,
            "discount_code": discount_code,
        }

    async def score_quiz(
        self,
        quiz_id: str,
        answers: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Score quiz answers and optionally generate Golden Ticket.

        Args:
            quiz_id: Quiz identifier.
            answers: Dict mapping question_id -> option_id.

        Returns:
            Dict with quiz_id, scores_by_dimension, composite_score,
            golden_ticket, recommendations.
        """
        questions_raw = self._quiz_cache.get(quiz_id)
        if not questions_raw and self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT questions FROM coherence_quiz_sessions WHERE id = $1",
                        quiz_id,
                    )
                    if row:
                        questions_raw = row.get("questions")
            except Exception as e:
                logger.debug("quiz_score_load_failed", quiz_id=quiz_id, error=str(e))

        if not questions_raw:
            questions_raw = DEFAULT_QUIZ_BANK

        if isinstance(questions_raw, str):
            questions_raw = json.loads(questions_raw)

        dimension_scores: Dict[str, List[float]] = {d: [] for d in DIMENSIONS}
        for q in questions_raw:
            qid = q.get("id")
            dim = q.get("dimension", "emotional")
            opt_id = answers.get(qid)
            if not opt_id:
                continue
            for opt in q.get("options", []):
                if str(opt.get("id")) == str(opt_id):
                    dimension_scores.setdefault(dim, []).append(float(opt.get("score", 1)))
                    break

        scores_by_dimension: Dict[str, float] = {}
        all_scores: List[float] = []
        for dim, vals in dimension_scores.items():
            if vals:
                avg = sum(vals) / len(vals)
                scores_by_dimension[dim] = round(avg * 25, 1)  # scale 1-4 -> 25-100
                all_scores.extend(vals)

        composite = 0.0
        if all_scores:
            mean = sum(all_scores) / len(all_scores)
            composite = round(mean * 25, 1)

        scores = {
            "scores_by_dimension": scores_by_dimension,
            "composite_score": composite,
        }
        golden_ticket = self._generate_golden_ticket(scores)

        recommendations = []
        for dim, score in scores_by_dimension.items():
            if score < 50:
                recommendations.append(f"Consider focusing on {dim} coherence practices.")
        if composite >= self.GOLDEN_TICKET_THRESHOLD:
            recommendations.append("Your coherence baseline suggests readiness for deeper engagement.")
        if not recommendations:
            recommendations.append("Continue your current coherence practices.")

        result = {
            "quiz_id": quiz_id,
            "scores_by_dimension": scores_by_dimension,
            "composite_score": composite,
            "golden_ticket": golden_ticket,
            "recommendations": recommendations,
        }

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO coherence_quiz_responses (quiz_id, answers, scores, golden_ticket, created_at)
                        VALUES ($1, $2, $3, $4, NOW())
                    """, quiz_id, json.dumps(answers), json.dumps(scores_by_dimension), json.dumps(golden_ticket) if golden_ticket else None)
            except Exception as e:
                logger.debug("quiz_score_persist_failed", quiz_id=quiz_id, error=str(e))

        logger.info("quiz_scored", quiz_id=quiz_id, composite=composite, golden_ticket=bool(golden_ticket))
        return result
