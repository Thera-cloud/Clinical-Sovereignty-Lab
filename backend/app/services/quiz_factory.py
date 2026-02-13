"""
LITTLE NATE — Quiz Factory
Autonomous quiz creation, cloning, and A/B testing.
Little Nate can generate new quizzes targeting specific audiences,
clone existing quizzes for different demographics, and track performance.

All auto-generated quizzes enter status 'draft' and require Big Nate approval.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from app.config import settings

logger = logging.getLogger("marketing.quiz_factory")


QUIZ_GEN_PROMPT = """You are designing a self-discovery quiz for a therapeutic AI platform called Sovereign Sanctuary.
The quiz should feel warm, insightful, and safe — not clinical or cold.

REQUIREMENTS:
- Generate exactly {question_count} questions
- Each question should reveal something meaningful about the person
- Mix question types: scale (1-10), multiple_choice, and open_text
- Tone: warm, curious, non-judgmental — like a friend who really wants to know you
- Questions should build on each other, going deeper as the quiz progresses
- Final question should be reflective and forward-looking

TARGET AUDIENCE: {audience}
TOPIC: {topic}
OBJECTIVE: {objective}

OUTPUT FORMAT (JSON):
{{
    "title": "Quiz title (evocative, not clinical)",
    "slug": "kebab-case-slug",
    "description": "2-3 sentence description of what this quiz explores",
    "questions": [
        {{
            "question_text": "The question",
            "question_type": "scale|multiple_choice|open_text",
            "options": ["option1", "option2", ...],  // only for multiple_choice
            "scale_min_label": "label",  // only for scale
            "scale_max_label": "label",  // only for scale
            "order_index": 1
        }}
    ],
    "insight_prompt": "Template for generating personalized insight from responses",
    "tags": ["tag1", "tag2"]
}}

Generate the quiz JSON now."""


class QuizFactory:
    """
    Creates quizzes autonomously using AI.
    All quizzes are created as drafts requiring Big Nate approval.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def create_quiz(self, audience: str, topic: str,
                          question_count: int = 8,
                          objective: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a new quiz using AI.
        Returns the created quiz (as draft) with questions.
        """
        if not objective:
            audience_objectives = {
                "individual": "Self-discovery and emotional awareness",
                "coach": "Professional growth and practice assessment",
                "family": "Family dynamics and connection patterns",
            }
            objective = audience_objectives.get(audience, "Personal growth exploration")

        prompt = QUIZ_GEN_PROMPT.format(
            question_count=question_count,
            audience=audience,
            topic=topic,
            objective=objective,
        )

        raw = await self._call_azure_openai(prompt)
        if not raw:
            return {"error": "AI generation failed", "status": "failed"}

        # Parse JSON from response
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                quiz_data = json.loads(raw[start:end])
            else:
                return {"error": "Could not parse quiz JSON", "raw": raw[:500]}
        except json.JSONDecodeError as e:
            return {"error": f"JSON parse error: {e}", "raw": raw[:500]}

        # Store quiz in database
        try:
            async with self.db_pool.acquire() as conn:
                # Create quiz record
                quiz_row = await conn.fetchrow("""
                    INSERT INTO quizzes
                        (title, description, theme, dimension, quiz_order, is_final, created_at)
                    VALUES ($1, $2, $3, $4, COALESCE((SELECT MAX(quiz_order) FROM quizzes), 0) + 1, FALSE, NOW())
                    RETURNING id
                """, quiz_data.get("title", f"Auto-generated: {topic}"),
                     quiz_data.get("description", ""),
                     audience,  # theme = audience type
                     topic[:100]  # dimension = topic
                )

                quiz_id = quiz_row["id"]

                # Create questions
                questions = quiz_data.get("questions", [])
                for i, q in enumerate(questions):
                    options = q.get("options")
                    if options and isinstance(options, list):
                        options_json = json.dumps(options)
                    else:
                        options_json = None

                    await conn.execute("""
                        INSERT INTO quiz_questions
                            (quiz_id, question_text, question_type, options,
                             scale_min_label, scale_max_label, order_index)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                    """, quiz_id, q.get("question_text", ""),
                         q.get("question_type", "open_text"),
                         options_json,
                         q.get("scale_min_label"),
                         q.get("scale_max_label"),
                         q.get("order_index", i + 1))

                # Log as marketing action
                await conn.execute("""
                    INSERT INTO marketing_actions
                        (proposed_by, action_type, title, description, parameters, status)
                    VALUES ('little_nate', 'create_quiz', $1, $2, $3::jsonb, 'proposed')
                """, f"New Quiz: {quiz_data.get('title', topic)}",
                     f"Auto-generated quiz for {audience} audience on topic: {topic}",
                     json.dumps({
                         "quiz_id": quiz_id,
                         "audience": audience,
                         "topic": topic,
                         "question_count": len(questions),
                         "tags": quiz_data.get("tags", []),
                     }))

                return {
                    "quiz_id": quiz_id,
                    "title": quiz_data.get("title"),
                    "slug": quiz_data.get("slug"),
                    "description": quiz_data.get("description"),
                    "question_count": len(questions),
                    "status": "draft",
                    "requires_approval": True,
                    "tags": quiz_data.get("tags", []),
                    "insight_prompt": quiz_data.get("insight_prompt", ""),
                }

        except Exception as e:
            logger.error(f"Failed to store generated quiz: {e}")
            return {"error": str(e), "quiz_data": quiz_data}

    async def clone_and_adapt(self, quiz_id: int, new_audience: str) -> Dict[str, Any]:
        """
        Clone an existing quiz and adapt it for a new audience using AI.
        """
        try:
            async with self.db_pool.acquire() as conn:
                # Get original quiz
                quiz = await conn.fetchrow(
                    "SELECT * FROM quizzes WHERE id = $1", quiz_id
                )
                if not quiz:
                    return {"error": f"Quiz {quiz_id} not found"}

                # Get original questions
                questions = await conn.fetch("""
                    SELECT * FROM quiz_questions
                    WHERE quiz_id = $1 ORDER BY order_index
                """, quiz_id)

                # Build adaptation prompt
                q_list = [
                    {
                        "text": q["question_text"],
                        "type": q["question_type"],
                        "options": json.loads(q["options"]) if q["options"] else None,
                    }
                    for q in questions
                ]

                prompt = (
                    f"Adapt this quiz for a {new_audience} audience.\n\n"
                    f"Original quiz: {quiz['title']}\n"
                    f"Original description: {quiz['description']}\n"
                    f"Original questions:\n{json.dumps(q_list, indent=2)}\n\n"
                    f"Create an adapted version that:\n"
                    f"- Keeps the same structure and question types\n"
                    f"- Adjusts language and framing for {new_audience}\n"
                    f"- Maintains the warmth and non-clinical tone\n"
                    f"- Uses relevant examples for the target audience\n\n"
                    f"Return JSON with: title, slug, description, questions (same format as input), tags"
                )

                raw = await self._call_azure_openai(prompt)
                if not raw:
                    return {"error": "AI adaptation failed"}

                # Parse and store (same as create_quiz)
                start = raw.find("{")
                end = raw.rfind("}") + 1
                adapted = json.loads(raw[start:end])

                # Create new quiz
                new_quiz = await conn.fetchrow("""
                    INSERT INTO quizzes
                        (title, description, theme, dimension,
                         quiz_order, is_final, created_at)
                    VALUES ($1, $2, $3, $4,
                            COALESCE((SELECT MAX(quiz_order) FROM quizzes), 0) + 1,
                            FALSE, NOW())
                    RETURNING id
                """, adapted.get("title", f"{quiz['title']} (for {new_audience})"),
                     adapted.get("description", quiz["description"]),
                     new_audience,
                     quiz.get("dimension", ""))

                new_id = new_quiz["id"]
                new_questions = adapted.get("questions", q_list)

                for i, q in enumerate(new_questions):
                    options = q.get("options")
                    await conn.execute("""
                        INSERT INTO quiz_questions
                            (quiz_id, question_text, question_type, options,
                             order_index)
                        VALUES ($1, $2, $3, $4::jsonb, $5)
                    """, new_id, q.get("text", q.get("question_text", "")),
                         q.get("type", q.get("question_type", "open_text")),
                         json.dumps(options) if options else None,
                         i + 1)

                return {
                    "quiz_id": new_id,
                    "cloned_from": quiz_id,
                    "title": adapted.get("title"),
                    "audience": new_audience,
                    "question_count": len(new_questions),
                    "status": "draft",
                }

        except Exception as e:
            logger.error(f"Failed to clone quiz: {e}")
            return {"error": str(e)}

    async def analyze_quiz_performance(self, quiz_id: int) -> Dict[str, Any]:
        """Analyze quiz completion rates and response patterns."""
        try:
            async with self.db_pool.acquire() as conn:
                quiz = await conn.fetchrow(
                    "SELECT title, slug FROM quizzes WHERE id = $1", quiz_id
                )
                if not quiz:
                    return {"error": f"Quiz {quiz_id} not found"}

                # Completion stats
                stats = await conn.fetchrow("""
                    SELECT
                        COUNT(DISTINCT prospect_id) as total_starts,
                        COUNT(*) as total_responses
                    FROM quiz_responses
                    WHERE quiz_id = $1
                """, quiz_id)

                # Question-level stats
                question_stats = await conn.fetch("""
                    SELECT
                        qq.question_text,
                        qq.question_type,
                        COUNT(qr.id) as response_count,
                        AVG(CASE WHEN qq.question_type = 'scale'
                            THEN CAST(qr.response_value AS FLOAT) END) as avg_scale_value
                    FROM quiz_questions qq
                    LEFT JOIN quiz_responses qr ON qr.question_id = qq.id
                    WHERE qq.quiz_id = $1
                    GROUP BY qq.id, qq.question_text, qq.question_type, qq.order_index
                    ORDER BY qq.order_index
                """, quiz_id)

                return {
                    "quiz_id": quiz_id,
                    "title": quiz["title"],
                    "total_starts": stats["total_starts"] if stats else 0,
                    "total_responses": stats["total_responses"] if stats else 0,
                    "questions": [
                        {
                            "text": q["question_text"],
                            "type": q["question_type"],
                            "responses": q["response_count"],
                            "avg_scale": float(q["avg_scale_value"]) if q["avg_scale_value"] else None,
                        }
                        for q in question_stats
                    ],
                }
        except Exception as e:
            logger.error(f"Failed to analyze quiz: {e}")
            return {"error": str(e)}

    async def _call_azure_openai(self, prompt: str) -> Optional[str]:
        """Call Azure OpenAI for quiz generation."""
        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "")
        api_key = getattr(settings, "AZURE_API_KEY", "")
        deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "")

        if not all([endpoint, api_key, deployment]):
            return None

        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"
        headers = {"Content-Type": "application/json", "api-key": api_key}
        payload = {
            "messages": [
                {"role": "system", "content": "You are a quiz designer for Sovereign Sanctuary, an AI therapy platform."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": 3000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=45)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "")
                    else:
                        error = await resp.text()
                        logger.error(f"Azure error ({resp.status}): {error[:200]}")
                        return None
        except Exception as e:
            logger.error(f"Azure call failed: {e}")
            return None
