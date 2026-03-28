"""
Voice Assistant Fulfillment — Alexa Skills + Google Actions.

Provides fulfillment endpoints for:
  - Amazon Alexa Custom Skill (POST /api/voice/alexa)
  - Google Assistant Actions (POST /api/voice/google)

Both route through the NateSummonService pipeline for AI responses.
"""

import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("nate.voice_assistant")

router = APIRouter(prefix="/api/voice", tags=["voice-assistant"])


# ── Alexa Skill ─────────────────────────────────────────────────────

@router.post("/alexa")
async def alexa_fulfillment(request: Request):
    """Handle Amazon Alexa skill requests."""
    try:
        body = await request.json()
    except Exception:
        return _alexa_response("I couldn't understand that request.", end=True)

    request_type = body.get("request", {}).get("type", "")

    if request_type == "LaunchRequest":
        return _alexa_response(
            "Hey there! I'm Little Nate, your AI companion from Sovereign Sanctuary. "
            "Ask me anything — just say 'ask Little Nate' followed by your question.",
            end=False,
            reprompt="What would you like to ask me?",
        )

    if request_type == "SessionEndedRequest":
        return _alexa_response("", end=True)

    if request_type == "IntentRequest":
        intent = body["request"].get("intent", {})
        intent_name = intent.get("name", "")

        if intent_name in ("AMAZON.HelpIntent",):
            return _alexa_response(
                "You can ask me any question. For example: "
                "'Ask Little Nate how to manage stress' or "
                "'Ask Little Nate about emotional coherence'. "
                "What would you like to know?",
                end=False,
            )

        if intent_name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
            return _alexa_response("Take care. I'm always here when you need me.", end=True)

        if intent_name == "AskNateIntent":
            question = _extract_alexa_slot(intent, "question")
            if not question:
                return _alexa_response(
                    "I didn't catch your question. Could you ask again?",
                    end=False,
                    reprompt="What would you like to ask?",
                )

            summon = getattr(request.app.state, "nate_summon_service", None)
            if not summon:
                return _alexa_response(
                    "I'm warming up right now. Please try again in a moment.", end=True
                )

            user_id = body.get("session", {}).get("user", {}).get("userId", "")
            fp = hashlib.sha256(f"alexa:{user_id}".encode()).hexdigest()

            db_pool = getattr(request.app.state, "db_pool", None)
            user = await _lookup_linked_user(db_pool, "alexa_id", user_id)

            try:
                result = await summon.process_summon(
                    message=question,
                    channel="alexa",
                    user=user,
                    device_fingerprint=fp,
                    context={"platform": "alexa"},
                )
                speech = result.response[:8000]
                if result.powered_by and not user:
                    speech += f" {result.powered_by}"
                return _alexa_response(speech, end=True)
            except Exception as e:
                logger.warning("Alexa summon error: %s", e)
                return _alexa_response(
                    "Something went sideways. Please try again.", end=True
                )

        if intent_name == "LinkAccountIntent":
            username = _extract_alexa_slot(intent, "username")
            if username:
                db_pool = getattr(request.app.state, "db_pool", None)
                user_id = body.get("session", {}).get("user", {}).get("userId", "")
                linked = await _link_user(db_pool, "alexa_id", user_id, username)
                if linked:
                    return _alexa_response(
                        f"Linked to account {username}. You now have full access.", end=True
                    )
                return _alexa_response(
                    f"I couldn't find the username {username}. Please check the spelling.", end=True
                )
            return _alexa_response(
                "Please say: link my account to, followed by your username.", end=False
            )

    return _alexa_response("I'm not sure how to handle that. Try asking me a question.", end=False)


# ── Google Actions ──────────────────────────────────────────────────

@router.post("/google")
async def google_actions_fulfillment(request: Request):
    """Handle Google Assistant / Actions on Google webhook."""
    try:
        body = await request.json()
    except Exception:
        return _google_response("I couldn't understand that request.", expect_input=False)

    handler = body.get("handler", {}).get("name", "")
    intent = body.get("intent", {}).get("name", "")
    query = body.get("intent", {}).get("query", "")

    session_id = body.get("session", {}).get("id", "")
    user_storage = body.get("user", {}).get("params", {})

    if intent == "actions.intent.MAIN" or handler == "welcome":
        return _google_response(
            "Hey! I'm Little Nate, your AI companion from Sovereign Sanctuary. "
            "Ask me anything.",
            expect_input=True,
            suggestions=["How do I manage anxiety?", "What is emotional coherence?"],
        )

    if handler == "ask_nate" or intent == "AskNateIntent":
        question = query or body.get("scene", {}).get("slots", {}).get("question", {}).get("value", "")
        if not question:
            return _google_response(
                "What would you like to ask?", expect_input=True
            )

        summon = getattr(request.app.state, "nate_summon_service", None)
        if not summon:
            return _google_response(
                "I'm warming up. Try again in a moment.", expect_input=False
            )

        fp = hashlib.sha256(f"google:{session_id}".encode()).hexdigest()
        db_pool = getattr(request.app.state, "db_pool", None)
        linked_google_id = user_storage.get("linked_user_id", "")
        user = await _lookup_linked_user(db_pool, "google_id", linked_google_id) if linked_google_id else None

        try:
            result = await summon.process_summon(
                message=question,
                channel="google_assistant",
                user=user,
                device_fingerprint=fp,
                context={"platform": "google_assistant"},
            )
            speech = result.response[:640]
            if result.powered_by and not user:
                speech += f" {result.powered_by}"
            return _google_response(speech, expect_input=True)
        except Exception as e:
            logger.warning("Google Actions summon error: %s", e)
            return _google_response("Something went wrong. Try again.", expect_input=False)

    if handler == "link_account":
        username = body.get("scene", {}).get("slots", {}).get("username", {}).get("value", "")
        if username:
            google_id = body.get("user", {}).get("accountLinkingToken", session_id)
            db_pool = getattr(request.app.state, "db_pool", None)
            linked = await _link_user(db_pool, "google_id", google_id, username)
            if linked:
                return _google_response(
                    f"Linked to {username}. Full access activated.", expect_input=True
                )
            return _google_response(f"Username {username} not found.", expect_input=True)

    if handler in ("fallback", "") and query:
        summon = getattr(request.app.state, "nate_summon_service", None)
        if summon:
            fp = hashlib.sha256(f"google:{session_id}".encode()).hexdigest()
            try:
                result = await summon.process_summon(
                    message=query, channel="google_assistant",
                    device_fingerprint=fp,
                    context={"platform": "google_assistant"},
                )
                return _google_response(result.response[:640], expect_input=True)
            except Exception:
                pass

    return _google_response(
        "I didn't catch that. Could you rephrase?", expect_input=True
    )


# ── Helpers ─────────────────────────────────────────────────────────

def _alexa_response(speech: str, end: bool, reprompt: str = None) -> dict:
    resp = {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": speech},
            "shouldEndSession": end,
        },
    }
    if reprompt:
        resp["response"]["reprompt"] = {
            "outputSpeech": {"type": "PlainText", "text": reprompt}
        }
    return resp


def _google_response(speech: str, expect_input: bool, suggestions: list = None) -> dict:
    resp = {
        "prompt": {
            "firstSimple": {"speech": speech, "text": speech},
        },
        "session": {"params": {}},
    }
    if suggestions:
        resp["prompt"]["suggestions"] = [{"title": s} for s in suggestions]
    if not expect_input:
        resp["scene"] = {"next": {"name": "actions.scene.END_CONVERSATION"}}
    return resp


def _extract_alexa_slot(intent: dict, slot_name: str) -> Optional[str]:
    slots = intent.get("slots", {})
    slot = slots.get(slot_name, {})
    return slot.get("value")


async def _lookup_linked_user(db_pool, id_field: str, platform_id: str) -> Optional[dict]:
    if not db_pool or not platform_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""SELECT username, role, profile_data->>'tier' AS tier
                    FROM users
                    WHERE profile_data->>'{id_field}' = $1""",
                str(platform_id),
            )
            return dict(row) if row else None
    except Exception:
        return None


async def _link_user(db_pool, id_field: str, platform_id: str, username: str) -> bool:
    if not db_pool or not platform_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                f"""UPDATE users SET profile_data = jsonb_set(
                        COALESCE(profile_data, '{{}}'::jsonb),
                        '{{{id_field}}}', $1::jsonb
                    )
                    WHERE username = $2""",
                f'"{platform_id}"', username,
            )
            return result == "UPDATE 1"
    except Exception:
        return False


@router.get("/health")
async def voice_health(request: Request):
    summon = getattr(request.app.state, "nate_summon_service", None)
    return {
        "status": "ok",
        "alexa_ready": summon is not None,
        "google_ready": summon is not None,
    }
