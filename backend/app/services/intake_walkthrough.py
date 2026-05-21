"""Little Nate intake walkthrough FSM (section 1 only)."""

from __future__ import annotations

import time
import os
from typing import Any, Dict, Optional

from app.constants.intake_questions import QUESTION_LABELS, SECTION1_FIELDS
from app.services.intake_form_service import (
    credit_walkthrough_question,
    ensure_intake_row,
    get_client_intake,
    update_client_answer,
)

_SESSION_TIMEOUT_S = 45 * 60
_RUNTIME: Dict[str, Dict[str, Any]] = {}

_ACCEPT_TERMS = ("yes", "yeah", "yep", "sure", "ok", "okay", "now", "let's do it", "lets do it", "start")
_DECLINE_TERMS = ("later", "not now", "skip", "no thanks", "not today", "maybe later")
_REFUSAL_TERMS = ("none of your business", "dont want to answer", "don't want to answer", "pass", "prefer not")
_CRISIS_TERMS = (
    "kill myself",
    "suicide",
    "want to die",
    "end my life",
    "self harm",
    "hurt myself",
    "kill them",
    "homicide",
)
_TOPIC_SHIFT_TERMS = ("different topic", "talk about something else", "actually can we", "can we talk about")


def _state(uid: str) -> Dict[str, Any]:
    now = time.time()
    st = _RUNTIME.get(uid)
    if not st or now - float(st.get("last_seen", 0)) > _SESSION_TIMEOUT_S:
        st = {
            "offered": False,
            "declined": False,
            "active": False,
            "current_q": None,
            "nonsense_reprompted": False,
            "needs_resume_prompt": False,
            "last_seen": now,
        }
        _RUNTIME[uid] = st
    st["last_seen"] = now
    return st


def _first_unanswered(intake_row: Dict[str, Any]) -> Optional[str]:
    for field in SECTION1_FIELDS:
        if str(intake_row.get(field) or "").strip() == "":
            return field
    return None


def _looks_nonsense(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) < 2:
        return True
    if all(ch in "!?.,-" for ch in stripped):
        return True
    return False


def _contains_any(text: str, phrases) -> bool:
    low = text.lower()
    return any(p in low for p in phrases)


async def handle_intake_walkthrough_turn(
    *,
    profile: Dict[str, Any],
    user_text: str,
    db_pool,
) -> Dict[str, Any]:
    if os.getenv("ENABLE_INTAKE_SYSTEM", "false").lower() not in ("1", "true", "yes"):
        return {"handled": False}
    """
    Returns:
      {"handled": bool, "response": str}
    """
    if (profile.get("role") or "").upper() != "CLIENT":
        return {"handled": False}
    if not db_pool:
        return {"handled": False}

    uid = profile.get("hardware_id", "")
    if not uid:
        return {"handled": False}
    username = (profile.get("username") or "").strip()
    if not username:
        return {"handled": False}

    st = _state(uid)

    async with db_pool.acquire() as conn:
        await ensure_intake_row(conn, username, uid)
        intake = await get_client_intake(conn, username, uid)
        next_q = _first_unanswered(intake)
        section_done = next_q is None

        if section_done:
            st["active"] = False
            st["declined"] = False
            st["offered"] = True
            st["current_q"] = None
            st["needs_resume_prompt"] = False
            return {"handled": False}

        # Crisis path priority while in walkthrough.
        if st.get("active") and _contains_any(user_text, _CRISIS_TERMS):
            st["active"] = False
            st["current_q"] = None
            st["needs_resume_prompt"] = True
            return {"handled": False}

        if st.get("needs_resume_prompt"):
            st["needs_resume_prompt"] = False
            st["active"] = False
            st["current_q"] = None
            return {
                "handled": True,
                "response": "We can continue the intake whenever you want, or stop it here. Your call.",
            }

        # Offer (once per runtime session)
        if not st.get("offered") and not st.get("active") and not st.get("declined"):
            st["offered"] = True
            return {
                "handled": True,
                "response": (
                    "Hey - your coach left an intake form in settings. It helps me get to know you better "
                    "so I can be more useful in our conversations. If you'd like, I can walk you through it "
                    "now and gift you 1000 tokens for each question you complete with me. Or you can fill it "
                    "out later in settings on your own. Want to do it now, or later?"
                ),
            }

        if not st.get("active"):
            low = user_text.strip().lower()
            if any(term in low for term in _ACCEPT_TERMS):
                st["active"] = True
                st["current_q"] = next_q
                st["nonsense_reprompted"] = False
                return {"handled": True, "response": QUESTION_LABELS.get(next_q, "Let's start with the first intake question.")}
            if any(term in low for term in _DECLINE_TERMS):
                st["declined"] = True
                return {"handled": True, "response": "No problem - we can do it later in Settings whenever you're ready."}
            return {"handled": False}

        # Active walkthrough
        if _contains_any(user_text, _TOPIC_SHIFT_TERMS):
            st["active"] = False
            st["current_q"] = None
            st["nonsense_reprompted"] = False
            return {"handled": False}

        current_q = st.get("current_q") or next_q
        if not current_q:
            st["active"] = False
            return {"handled": False}

        if _looks_nonsense(user_text):
            if not st.get("nonsense_reprompted"):
                st["nonsense_reprompted"] = True
                return {
                    "handled": True,
                    "response": f"I want to make sure I capture this correctly. {QUESTION_LABELS.get(current_q, 'Could you answer that one in your own words?')}",
                }
            # Save second nonsense attempt verbatim to keep momentum.

        if _contains_any(user_text, _REFUSAL_TERMS):
            answer_value = "[declined_to_answer]"
        elif user_text.strip().lower() in {"skip", "pass"}:
            answer_value = "[skipped]"
        else:
            answer_value = user_text.strip()

        await update_client_answer(
            conn,
            username=username,
            hardware_id=uid,
            question_id=current_q,
            value=answer_value,
            actor_id=username,
            method="chat_walkthrough",
        )
        try:
            credit = await credit_walkthrough_question(conn, username=username, question_id=current_q)
        except Exception as _credit_err:
            import traceback as _tb
            print(f">>> [INTAKE] Token credit failed for user={username} q={current_q}: {_credit_err}")
            _tb.print_exc()
            credit = {"credited": False, "amount": 0, "reason": "credit_failed"}

        refreshed = await get_client_intake(conn, username, uid)
        next_after = _first_unanswered(refreshed)
        st["nonsense_reprompted"] = False

        if next_after:
            st["current_q"] = next_after
            token_line = "That's 1000 tokens added to your account." if credit.get("credited") else "That answer is saved."
            return {
                "handled": True,
                "response": f"Got it - saved. {token_line} Thanks for sharing that with me. Next question: {QUESTION_LABELS.get(next_after, next_after)}",
            }

        st["active"] = False
        st["current_q"] = None
        return {
            "handled": True,
            "response": (
                "That's section 1 done - I've got what I need to support you better now. "
                "Your coach will follow up on the rest of the intake in your next session, "
                "or you can fill it in yourself in settings whenever you want. "
                "Thanks for walking through this with me."
            ),
        }
