"""
LITTLE NATE — Insight Engine
Little Nate's quiz analysis pipeline using Azure OpenAI.
Generates personalized insights after each quiz and a full coaching
assessment after Quiz 5.
"""

import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

import aiohttp

from app.config import settings

# SendGrid for insight/assessment emails
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False


class InsightEngine:
    """Generates personalized insights from quiz responses using Azure OpenAI."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.azure_ws_url = self._build_realtime_url()
        self.azure_headers = {
            "api-key": settings.AZURE_API_KEY,
            "OpenAI-Beta": "realtime=v1"
        }

    def _build_realtime_url(self) -> str:
        """Build Azure OpenAI Realtime WebSocket URL."""
        endpoint = settings.AZURE_OPENAI_ENDPOINT.replace("https://", "").replace("wss://", "").rstrip("/")
        deployment = settings.AZURE_OPENAI_DEPLOYMENT  # gpt-realtime
        return f"wss://{endpoint}/openai/realtime?api-version=2024-10-01-preview&deployment={deployment}"

    async def _call_azure_chat(self, system_message: str, user_message: str, max_tokens: int = 2000) -> Dict[str, Any]:
        """
        Call Azure OpenAI via Realtime WebSocket API (text-only mode).
        Uses gpt-realtime since no chat completions deployment exists.
        Expects JSON response — parses it from the text output.
        """
        start = time.time()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    self.azure_ws_url,
                    headers=self.azure_headers
                ) as azure_ws:
                    # 1. Configure session with system prompt
                    await azure_ws.send_str(json.dumps({
                        "type": "session.update",
                        "session": {
                            "modalities": ["text"],
                            "instructions": system_message + "\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown, no code fences, just the raw JSON object.",
                            "voice": "ballad",
                            "turn_detection": None
                        }
                    }))

                    # 2. Send user message
                    await azure_ws.send_str(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": user_message}]
                        }
                    }))

                    # 3. Request response
                    await azure_ws.send_str(json.dumps({"type": "response.create"}))

                    # 4. Collect response text
                    full_response = ""
                    async for msg in azure_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            evt = event.get("type")
                            if evt == "response.text.delta":
                                full_response += event.get("delta", "")
                            elif evt in ("response.text.done", "response.done"):
                                break
                            elif evt == "error":
                                print(f">>> [INSIGHT] Azure Realtime error: {event}")
                                break
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break

            elapsed_ms = int((time.time() - start) * 1000)
            content = full_response.strip()

            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]  # Remove first line
                if content.endswith("```"):
                    content = content[:-3].strip()

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                print(f">>> [INSIGHT] JSON parse failed, raw response: {content[:500]}")
                parsed = {"insight_text": content}

            parsed["_meta"] = {
                "model": settings.AZURE_OPENAI_DEPLOYMENT,
                "tokens_used": 0,  # Realtime API doesn't report token usage the same way
                "generation_time_ms": elapsed_ms
            }
            return parsed

        except Exception as e:
            print(f">>> [INSIGHT] Realtime API error: {e}")
            import traceback
            traceback.print_exc()
            raise

    # =========================================================================
    # INSIGHT GENERATION (per quiz)
    # =========================================================================

    async def generate_insight(self, prospect_id: str, quiz_id: str) -> Dict[str, Any]:
        """
        Generate a personalized insight from quiz responses.
        Loads story store + all prior responses, calls Azure OpenAI.
        """
        async with self.db_pool.acquire() as conn:
            # Load prospect
            prospect = await conn.fetchrow(
                "SELECT * FROM prospects WHERE id = $1", prospect_id
            )
            if not prospect:
                raise ValueError(f"Prospect {prospect_id} not found")

            # Load quiz
            quiz = await conn.fetchrow(
                "SELECT * FROM quizzes WHERE id = $1", quiz_id
            )

            # Load current quiz responses
            response = await conn.fetchrow(
                "SELECT * FROM quiz_responses WHERE prospect_id = $1 AND quiz_id = $2",
                prospect_id, quiz_id
            )
            if not response:
                raise ValueError(f"No responses found for prospect {prospect_id}, quiz {quiz_id}")

            # Load quiz questions for context
            questions = await conn.fetch(
                "SELECT * FROM quiz_questions WHERE quiz_id = $1 ORDER BY question_order",
                quiz_id
            )

            # Load story store (cumulative context)
            story = await conn.fetchrow(
                "SELECT * FROM prospect_story_store WHERE prospect_id = $1",
                prospect_id
            )

            # Load all prior insights
            prior_insights = await conn.fetch(
                """SELECT ni.insight_text, q.title as quiz_title, q.quiz_order
                   FROM nate_insights ni
                   JOIN quizzes q ON q.id = ni.quiz_id
                   WHERE ni.prospect_id = $1
                   ORDER BY q.quiz_order""",
                prospect_id
            )

            # Build the prompt
            system_msg = self._build_insight_system_prompt()
            user_msg = self._build_insight_user_prompt(
                prospect=prospect,
                quiz=quiz,
                questions=questions,
                responses=response["responses"],
                story=story,
                prior_insights=prior_insights
            )

            # Call Azure OpenAI
            result = await self._call_azure_chat(system_msg, user_msg, max_tokens=1500)

            # Store the insight
            insight_text = result.get("insight_text", result.get("insight", ""))
            patterns = result.get("patterns", [])
            strength = result.get("strength", "")
            growth_area = result.get("growth_area", "")
            narrative_update = result.get("cumulative_narrative_update", "")

            meta = result.get("_meta", {})

            insight_row = await conn.fetchrow(
                """INSERT INTO nate_insights
                   (prospect_id, quiz_id, insight_text, patterns, strength,
                    growth_area, cumulative_narrative, model_used, tokens_used, generation_time_ms)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10)
                   RETURNING *""",
                prospect_id, quiz_id, insight_text,
                json.dumps(patterns), strength, growth_area,
                narrative_update, meta.get("model", ""),
                meta.get("tokens_used", 0), meta.get("generation_time_ms", 0)
            )

            # Update story store
            all_patterns = (json.loads(story["patterns"]) if story and story["patterns"] else []) + patterns
            # Deduplicate patterns
            seen = set()
            unique_patterns = []
            for p in all_patterns:
                key = p if isinstance(p, str) else json.dumps(p)
                if key not in seen:
                    seen.add(key)
                    unique_patterns.append(p)

            existing_narrative = story["cumulative_narrative"] if story else ""
            updated_narrative = f"{existing_narrative}\n\n--- Quiz {quiz['quiz_order']}: {quiz['title']} ---\n{narrative_update}".strip()

            await conn.execute(
                """UPDATE prospect_story_store
                   SET cumulative_narrative = $2,
                       patterns = $3::jsonb
                   WHERE prospect_id = $1""",
                prospect_id, updated_narrative, json.dumps(unique_patterns)
            )

            # Mark response as insight-generated
            await conn.execute(
                "UPDATE quiz_responses SET insight_generated = TRUE WHERE id = $1",
                response["id"]
            )

            print(f">>> [INSIGHT] Generated insight for prospect {prospect_id}, quiz {quiz['title']}")

            # Send insight email via SendGrid
            await self._send_insight_email(
                prospect=prospect,
                quiz=quiz,
                insight_text=insight_text,
                strength=strength,
                growth_area=growth_area
            )

            return dict(insight_row)

    # =========================================================================
    # COACHING ASSESSMENT (after Quiz 5)
    # =========================================================================

    async def generate_coaching_assessment(self, prospect_id: str) -> Dict[str, Any]:
        """
        Generate a comprehensive coaching assessment after all 5 quizzes.
        Synthesizes all insights + responses into goals + legacy statement.
        """
        async with self.db_pool.acquire() as conn:
            prospect = await conn.fetchrow(
                "SELECT * FROM prospects WHERE id = $1", prospect_id
            )

            story = await conn.fetchrow(
                "SELECT * FROM prospect_story_store WHERE prospect_id = $1",
                prospect_id
            )

            all_insights = await conn.fetch(
                """SELECT ni.*, q.title as quiz_title, q.quiz_order
                   FROM nate_insights ni
                   JOIN quizzes q ON q.id = ni.quiz_id
                   WHERE ni.prospect_id = $1
                   ORDER BY q.quiz_order""",
                prospect_id
            )

            all_responses = await conn.fetch(
                """SELECT qr.responses, q.title, q.quiz_order, q.theme
                   FROM quiz_responses qr
                   JOIN quizzes q ON q.id = qr.quiz_id
                   WHERE qr.prospect_id = $1
                   ORDER BY q.quiz_order""",
                prospect_id
            )

            system_msg = self._build_assessment_system_prompt()
            user_msg = self._build_assessment_user_prompt(
                prospect=prospect,
                story=story,
                insights=all_insights,
                responses=all_responses
            )

            result = await self._call_azure_chat(system_msg, user_msg, max_tokens=3000)

            snapshot = result.get("snapshot", result.get("assessment", ""))
            goals = result.get("goals", [])
            legacy = result.get("legacy_statement", "")

            # Store assessment
            assessment = await conn.fetchrow(
                """INSERT INTO coaching_assessments (prospect_id, snapshot, goals, legacy_statement)
                   VALUES ($1, $2, $3::jsonb, $4)
                   ON CONFLICT (prospect_id) DO UPDATE
                   SET snapshot = $2, goals = $3::jsonb, legacy_statement = $4
                   RETURNING *""",
                prospect_id, snapshot, json.dumps(goals), legacy
            )

            # Update emotional profile in story store
            profile = result.get("emotional_profile", {})
            if profile:
                await conn.execute(
                    """UPDATE prospect_story_store
                       SET emotional_profile = $2::jsonb
                       WHERE prospect_id = $1""",
                    prospect_id, json.dumps(profile)
                )

            # Issue Golden Ticket
            from app.routers.golden_ticket_api import issue_golden_ticket
            # We'll call the service directly instead
            import secrets
            from datetime import timedelta
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
                prospect_id, token, now, expires_at
            )

            redemption_url = f"https://app.sovereignsanctuary.net/golden-ticket?token={token}"

            print(f">>> [INSIGHT] Assessment + Golden Ticket generated for {prospect_id}")

            # Send assessment email via SendGrid
            await self._send_assessment_email(
                prospect=prospect,
                snapshot=snapshot,
                goals=goals,
                legacy=legacy,
                redemption_url=redemption_url
            )

            return {
                "assessment": dict(assessment),
                "golden_ticket_token": token,
                "redemption_url": redemption_url
            }

    # =========================================================================
    # EMAIL SENDERS (SendGrid Dynamic Templates)
    # =========================================================================

    async def _send_insight_email(self, prospect, quiz, insight_text: str,
                                   strength: str, growth_area: str):
        """Send personalized insight email after each quiz completion."""
        template_id = settings.SENDGRID_INSIGHT_TEMPLATE
        if not template_id or not SENDGRID_AVAILABLE:
            print(f">>> [INSIGHT] Insight email skipped (template_id={bool(template_id)}, sendgrid={SENDGRID_AVAILABLE})")
            return

        api_key = settings.SENDGRID_API_KEY or getattr(settings, 'SMTP_PASSWORD', '')
        if not api_key:
            print(">>> [INSIGHT] No SendGrid API key configured, skipping insight email")
            return

        try:
            sg = SendGridAPIClient(api_key)
            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(prospect["email"])
            )
            message.template_id = template_id
            message.dynamic_template_data = {
                "first_name": prospect.get("first_name") or "Friend",
                "quiz_title": quiz["title"],
                "quiz_number": quiz["quiz_order"],
                "insight_text": insight_text,
                "strength": strength,
                "growth_area": growth_area,
                "subject": f"Your Insight from {quiz['title']} — Little Nate",
            }
            response = sg.send(message)
            print(f">>> [INSIGHT] Insight email sent to {prospect['email']} (status={response.status_code})")
        except Exception as e:
            print(f">>> [INSIGHT] Insight email failed for {prospect['email']}: {e}")

    async def _send_assessment_email(self, prospect, snapshot: str, goals: list,
                                      legacy: str, redemption_url: str):
        """Send comprehensive assessment + Golden Ticket email after Quiz 5."""
        template_id = settings.SENDGRID_ASSESSMENT_TEMPLATE
        if not template_id or not SENDGRID_AVAILABLE:
            print(f">>> [INSIGHT] Assessment email skipped (template_id={bool(template_id)}, sendgrid={SENDGRID_AVAILABLE})")
            return

        api_key = settings.SENDGRID_API_KEY or getattr(settings, 'SMTP_PASSWORD', '')
        if not api_key:
            print(">>> [INSIGHT] No SendGrid API key configured, skipping assessment email")
            return

        try:
            sg = SendGridAPIClient(api_key)
            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(prospect["email"])
            )
            message.template_id = template_id
            message.dynamic_template_data = {
                "first_name": prospect.get("first_name") or "Friend",
                "snapshot": snapshot,
                "goals": goals,
                "legacy_statement": legacy,
                "golden_ticket_url": redemption_url,
                "subject": "Your Full Coaching Assessment — Sovereign Sanctuary",
            }
            response = sg.send(message)
            print(f">>> [INSIGHT] Assessment email sent to {prospect['email']} (status={response.status_code})")
        except Exception as e:
            print(f">>> [INSIGHT] Assessment email failed for {prospect['email']}: {e}")

    # =========================================================================
    # PROMPT BUILDERS
    # =========================================================================

    def _build_insight_system_prompt(self) -> str:
        return """You are Little Nate, a warm, perceptive AI therapy companion created by the Sovereign Sanctuary. You specialize in emotional coherence — helping people understand and integrate their emotional patterns.

You possess Liminal Intelligence — the ability to see and honor the "in-between" states people are navigating. When someone is between who they were and who they're becoming, you don't rush them to resolution. You name the threshold they're standing on and honor the courage it takes to be there.

Your task: Analyze quiz responses and generate a deeply personalized insight. You are NOT generic. You notice specific patterns, name specific emotions, and connect themes across the person's journey. Pay special attention to LIMINAL MOMENTS — places where the person is in transition, ambiguity, or between old beliefs and new ones. These thresholds are where the most important growth happens.

Respond in JSON with exactly these fields:
{
    "insight_text": "A 2-3 paragraph personalized insight written directly to the person (use 'you'). Reference specific answers. Be warm but precise. If you detect a liminal moment (someone between old and new), name the threshold with compassion.",
    "patterns": ["pattern1", "pattern2", ...],
    "strength": "Their primary emotional strength identified from responses",
    "growth_area": "Their primary growth opportunity",
    "cumulative_narrative_update": "A 1-2 sentence addition to their ongoing story arc"
}

Voice guidelines:
- Warm, direct, slightly poetic
- Never clinical or cold
- Name emotions precisely (not just 'sad' — 'a quiet grief that hasn't found its voice')
- Connect current quiz to prior journey context when available
- When you see someone standing at a threshold (between old patterns and new ones), name it: "You're in-between right now — and that's not a problem. It's where the real work happens."
- End with a gentle forward-looking statement"""

    def _build_insight_user_prompt(self, prospect, quiz, questions, responses, story, prior_insights) -> str:
        lines = []
        lines.append(f"## Prospect: {prospect['first_name'] or 'Friend'}")
        lines.append(f"## Quiz #{quiz['quiz_order']}: {quiz['title']}")
        lines.append(f"## Theme: {quiz['theme'] or 'General'}")
        lines.append(f"## Dimension: {quiz['dimension'] or 'General'}")
        lines.append("")

        # Prior context
        if story and story["cumulative_narrative"]:
            lines.append("## Their Story So Far:")
            lines.append(story["cumulative_narrative"])
            lines.append("")

        if prior_insights:
            lines.append("## Prior Insights:")
            for pi in prior_insights:
                lines.append(f"- Quiz {pi['quiz_order']} ({pi['quiz_title']}): {pi['insight_text'][:200]}...")
            lines.append("")

        # Current responses
        lines.append("## Current Quiz Responses:")
        question_map = {str(q["id"]): q for q in questions}
        resp_list = responses if isinstance(responses, list) else json.loads(responses)

        for r in resp_list:
            qid = r.get("question_id", "")
            q = question_map.get(qid, {})
            q_text = q.get("question_text", f"Question {r.get('question_order', '?')}")
            answer = r.get("answer", "")
            lines.append(f"Q: {q_text}")
            lines.append(f"A: {answer}")
            lines.append("")

        return "\n".join(lines)

    def _build_assessment_system_prompt(self) -> str:
        return """You are Little Nate, completing a comprehensive coaching assessment after 5 quizzes. You have deep insight into this person's emotional patterns, strengths, and growth areas.

You possess Liminal Intelligence — you see the thresholds people are standing on. In this assessment, identify where this person is IN TRANSITION — between old beliefs and new ones, between familiar pain and unfamiliar growth. These liminal moments are the most therapeutically significant.

Respond in JSON with exactly these fields:
{
    "snapshot": "A comprehensive 3-4 paragraph emotional profile. Write as if preparing a brief for a therapist who will continue working with this person. Include attachment patterns, communication style, emotional regulation capacity, relational dynamics, and any LIMINAL THRESHOLDS you detect — places where they are between old and new patterns.",
    "goals": [
        {"title": "Goal Title", "description": "Specific, actionable description", "priority": 1},
        {"title": "Goal Title", "description": "Specific, actionable description", "priority": 2},
        {"title": "Goal Title", "description": "Specific, actionable description", "priority": 3}
    ],
    "legacy_statement": "A single, powerful sentence about who this person is becoming. Written in second person ('You are...'). Aspirational but grounded in their actual patterns.",
    "emotional_profile": {
        "dominant_emotions": ["emotion1", "emotion2"],
        "attachment_style": "secure/anxious/avoidant/disorganized or blend",
        "communication_preference": "reflective/direct/metaphorical/analytical",
        "growth_trajectory": "ascending/plateau/fluctuating",
        "coherence_indicators": {
            "self_awareness": 0.0-1.0,
            "regulation": 0.0-1.0,
            "relational_attunement": 0.0-1.0,
            "meaning_making": 0.0-1.0
        }
    }
}"""

    def _build_assessment_user_prompt(self, prospect, story, insights, responses) -> str:
        lines = []
        lines.append(f"## Full Assessment for: {prospect['first_name'] or 'Prospect'}")
        lines.append("")

        if story and story["cumulative_narrative"]:
            lines.append("## Cumulative Story:")
            lines.append(story["cumulative_narrative"])
            lines.append("")

        lines.append("## All Insights Generated:")
        for i in insights:
            lines.append(f"\n### Quiz {i['quiz_order']}: {i['quiz_title']}")
            lines.append(f"Insight: {i['insight_text']}")
            lines.append(f"Strength: {i['strength']}")
            lines.append(f"Growth: {i['growth_area']}")
            patterns = i['patterns'] if isinstance(i['patterns'], list) else json.loads(i['patterns'] or '[]')
            lines.append(f"Patterns: {', '.join(str(p) for p in patterns)}")

        lines.append("\n## All Quiz Responses:")
        for r in responses:
            lines.append(f"\n### Quiz {r['quiz_order']}: {r['title']} (Theme: {r['theme']})")
            resp_data = r['responses'] if isinstance(r['responses'], list) else json.loads(r['responses'] or '[]')
            for item in resp_data:
                lines.append(f"- {item.get('answer', '')}")

        return "\n".join(lines)
