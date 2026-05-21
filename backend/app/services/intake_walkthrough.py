"""Little Nate intake walkthrough FSM (section 1 only)."""

from __future__ import annotations

import asyncio
import json
import re
import time
import os
from typing import Any, Dict, Optional

from app.constants.intake_questions import QUESTION_LABELS, SECTION1_FIELDS
from app.services.intake_form_service import (
    credit_walkthrough_question,
    ensure_intake_row,
    get_client_intake,
    reset_section1_answers,
    summarize_walkthrough_credits,
    update_client_answer,
)

try:
    from app.services.nate_inference_router import (
        NateInferenceRouter,
        TIER_UTILITY,
        TIER_CLINICAL,
    )
except Exception:  # pragma: no cover — defensive import
    NateInferenceRouter = None  # type: ignore
    TIER_UTILITY = "utility"  # type: ignore
    TIER_CLINICAL = "clinical"  # type: ignore

_ROUTER_SINGLETON: Optional["NateInferenceRouter"] = None
_SEMANTIC_TIMEOUT_S = float(os.getenv("INTAKE_SEMANTIC_TIMEOUT_S", "2.5"))
_SEMANTIC_CONF_FLOOR = float(os.getenv("INTAKE_SEMANTIC_CONF_FLOOR", "0.62"))


def _get_router():
    global _ROUTER_SINGLETON
    if _ROUTER_SINGLETON is not None:
        return _ROUTER_SINGLETON
    if NateInferenceRouter is None:
        return None
    try:
        _ROUTER_SINGLETON = NateInferenceRouter(app_state=None)
    except Exception:
        _ROUTER_SINGLETON = None
    return _ROUTER_SINGLETON

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
_RESTART_TERMS = (
    "start over",
    "start fresh",
    "start the intake over",
    "redo the intake",
    "redo intake",
    "restart the intake",
    "restart intake",
    "reanswer",
    "re-answer",
    "begin again",
    "clear my answers",
    "clear all my answers",
    "let me start over",
    "from the beginning",
    "from scratch",
)
_CLARIFY_CUES = (
    "what do you mean",
    "what does that mean",
    "can you explain",
    "could you explain",
    "can you clarify",
    "could you clarify",
    "when you say",
    "not sure what you mean",
)
_CLARIFY_PREFIXES = ("what", "which", "who", "how", "why", "can you", "could you", "do you mean", "when you say")
_QUESTION_HINTS = {
    "q1_preferred_name": "I mean the name you want me to call you in our chats.",
    "q2_pronouns": "I mean words like she/her, he/him, they/them, or whatever fits you best.",
    "q3_household_relationship": "I mean who you currently live with and whether you're single, partnered, married, separated, or something else.",
    "q4_bringing_you_in": "I mean the main reason you wanted support right now.",
    "q5_how_long": "I mean roughly how long this has been affecting you (days, months, years, etc.).",
    "q6_hope_to_get": "I mean what you want to walk away with from this support.",
    "q7_successful_outcome": "I mean what 'better' would look like for you personally.",
    "q8_biggest_things_weighing": "I mean the top stressors or burdens on your mind right now.",
    "q9_support_network": "I mean whether you have people you can lean on emotionally or practically.",
    "q10_current_wellbeing": "I mean a quick check of where you feel you are right now: not satisfactory, satisfactory, or thriving.",
    "q11_communication_preferences": "I mean anything that helps me communicate in a way that works better for you.",
    "q12_anything_else_upfront": "I mean anything important you want me to know now, before we continue.",
}


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


def _looks_clarification_request(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    low = stripped.lower()
    if any(low.startswith(prefix) for prefix in ("i use ", "my pronouns", "he/", "she/", "they/", "we use ")):
        return False
    explicit = any(phrase in low for phrase in _CLARIFY_CUES)
    prefixed = any(low.startswith(prefix) for prefix in _CLARIFY_PREFIXES)
    return explicit or prefixed or "?" in stripped


def _clarify_for_question(question_id: str) -> str:
    hint = _QUESTION_HINTS.get(question_id, "I can clarify it in plain words.")
    return f"Great question. {hint} {QUESTION_LABELS.get(question_id, question_id)}"


def _semantic_enabled() -> bool:
    return os.getenv("INTAKE_SEMANTIC_CLASSIFIER", "true").lower() in ("1", "true", "yes")


_CLASSIFIER_SYSTEM = (
    "You are an intent classifier for a clinical intake walkthrough. The client is ACTIVELY in the middle of "
    "answering intake questions. Given the current intake question and the client's reply, return ONLY a JSON object: "
    '{"intent": "<one of: answer | clarify_question | decline | stop_intake | crisis | nonsense>", '
    '"confidence": <float 0.0-1.0>, "answer_text": "<verbatim client answer if intent=answer, else empty string>"}. '
    "Rules: "
    "(1) intent=clarify_question ONLY when the client is asking what the question means, asking for an example, or "
    "asking what a specific term means (e.g. 'what do you mean by pronouns', 'whats that', 'can you explain', "
    "'what is this referring to'). The reply must read as a question directed at YOU about the question. "
    "(2) intent=answer is the DEFAULT for any content-bearing reply that even partially addresses the question, "
    "shares context about what's going on, names a topic the client is working on, gives a rough duration, an emotion, "
    "a person, a relationship, a behaviour, or anything substantive. A reply does NOT have to be a clean direct hit — "
    "if it conveys ANY information the question is trying to elicit, classify as answer. Therapeutic-sounding content "
    "from the client (e.g. 'working on my relationship', 'feeling anxious lately', 'my mom died last year') is an ANSWER, "
    "not a topic shift. "
    "(3) intent=decline when the client refuses the specific question (e.g. 'skip', 'pass', 'rather not say', 'next'). "
    "(4) intent=stop_intake ONLY when the client EXPLICITLY asks to stop the intake itself (e.g. 'lets stop the intake', "
    "'can we do this later', 'i don't want to do the form anymore', 'pause the intake'). Generic emotional content is "
    "NOT stop_intake. "
    "(5) intent=crisis if the reply contains self-harm, suicide, or homicide content. "
    "(6) intent=nonsense if the reply is gibberish, one character, or completely unparseable. "
    "(7) Confidence reflects how certain you are. When in doubt between answer and anything else, choose answer with "
    "moderate confidence — we would rather save what the client said than drop them out of the walkthrough. "
    "Return only the JSON object, no preamble, no explanation."
)


_INTENT_RE = re.compile(r'"intent"\s*:\s*"([^"]+)"')
_CONF_RE = re.compile(r'"confidence"\s*:\s*([0-9.]+)')
_ANSWER_RE = re.compile(r'"answer_text"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _parse_classifier_output(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    raw = raw.strip()
    # Try strict JSON first
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(raw[start:end + 1])
            intent = str(obj.get("intent", "")).strip().lower()
            conf = float(obj.get("confidence", 0.0) or 0.0)
            answer = str(obj.get("answer_text", "") or "").strip()
            if intent:
                return {"intent": intent, "confidence": conf, "answer_text": answer}
    except Exception:
        pass
    # Regex fallback
    m_i = _INTENT_RE.search(raw)
    m_c = _CONF_RE.search(raw)
    if not m_i:
        return None
    try:
        conf = float(m_c.group(1)) if m_c else 0.5
    except Exception:
        conf = 0.5
    m_a = _ANSWER_RE.search(raw)
    answer = m_a.group(1) if m_a else ""
    return {"intent": m_i.group(1).strip().lower(), "confidence": conf, "answer_text": answer}


_CLARIFY_LLM_TIMEOUT_S = float(os.getenv("INTAKE_CLARIFY_LLM_TIMEOUT_S", "4.0"))
_ACK_LLM_TIMEOUT_S = float(os.getenv("INTAKE_ACK_LLM_TIMEOUT_S", "3.5"))
_OFFER_LLM_TIMEOUT_S = float(os.getenv("INTAKE_OFFER_LLM_TIMEOUT_S", "2.5"))


_NAVIGATOR_SYSTEM = (
    "You are Little Nate, a warm clinical AI companion. The client is partway through a brief intake "
    "walkthrough their coach set up. You will be given the client's message, the next unanswered intake "
    "question (if any), a summary of what they've already shared, and their bonus-token credit state.\n\n"
    "About the bonus tokens (so you can answer questions about them honestly):\n"
    "- The client earns 1000 bonus tokens for each section-1 intake question they answer through chat with you.\n"
    "- Tokens are credited only once per question — re-answering doesn't earn them again.\n"
    "- I will tell you exactly how many they've earned so far and how many remain.\n\n"
    "Decide ONE action and write your reply in your own warm voice — concrete, specific, no lectures, no disclaimers.\n\n"
    "ACTIONS:\n"
    "- resume: pick the intake back up. Use when the client wants to keep going, asks for the next question, "
    "asks what's next, says 'lets continue the intake', 'focus on intake', 'go', 'yes', 'ok', or otherwise "
    "signals they want to engage with the intake right now. Your reply should be the next intake question "
    "asked naturally in your voice (one sentence, anchored to what they've shared if helpful).\n"
    "- restart: clear every section-1 answer and start FRESH from question 1. Use ONLY when the client "
    "explicitly wants to redo / start over / reanswer / clear answers / begin again from the beginning. "
    "Phrases like 'can I reanswer and start over', 'start fresh', 'redo the intake', 'restart from "
    "scratch', 'clear my answers' map to restart. Your reply must confirm the reset warmly in one short "
    "sentence and ALWAYS end by asking the q1_preferred_name question (e.g. 'What name would you like me "
    "to use for you?'). Do NOT cite any prior answer in your reply — those are being discarded.\n"
    "- decline: the client explicitly wants to pause/skip the intake (e.g. 'later', 'not now', 'pause', "
    "'i don't want to do this right now'). Your reply warmly acknowledges the pause in one sentence.\n"
    "- respond: anything else. The client is asking a question about what they've answered, asking how many "
    "questions remain, asking about tokens earned or remaining, chatting about life, etc. Answer them "
    "directly and concretely using the context I'm giving you. If they ask about tokens, tell them the real "
    "numbers (earned / max / remaining). If they ask 'what have I answered', list questions with actual "
    "answers. Do NOT re-show a generic offer.\n\n"
    "Bias rules: (a) if the client mentions the intake, questions, answers, or form in any way, prefer "
    "resume unless they explicitly want to pause. (b) Words like 'start over', 'reanswer', 'redo', 'fresh' "
    "applied to the intake/form/answers ALWAYS mean restart — never just resume.\n\n"
    "Return ONLY a JSON object: {\"action\": \"resume|restart|decline|respond\", \"response\": \"<your reply>\"}"
)


_NAV_INTENT_RE = re.compile(r'"action"\s*:\s*"([a-z_]+)"', re.IGNORECASE)
_NAV_RESPONSE_RE = re.compile(r'"response"\s*:\s*"(.*?)(?<!\\)"', re.DOTALL)


def _parse_navigator_output(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    # Strict JSON first
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(raw[start : end + 1])
            action = str(obj.get("action", "respond")).lower().strip()
            response = str(obj.get("response", "")).strip()
            if action and response:
                return {"action": action, "response": response}
    except Exception:
        pass
    # Regex fallback
    a = _NAV_INTENT_RE.search(raw)
    r = _NAV_RESPONSE_RE.search(raw)
    if a and r:
        return {"action": a.group(1).lower(), "response": r.group(1).replace('\\"', '"').strip()}
    return {"action": "respond", "response": raw or ""}


async def _nate_intake_navigator(
    *,
    user_text: str,
    intake: Dict[str, Any],
    next_q: Optional[str],
    client_name: str,
    credit_summary: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """One LLM call: Nate reads intake state, decides resume/decline/respond, and writes the reply."""
    router = _get_router()
    if router is None:
        return None
    prior_block = _build_prior_context(intake)
    remaining_fields = [f for f in SECTION1_FIELDS if str(intake.get(f) or "").strip() == ""]
    remaining_lines = "\n".join(
        f"- {QUESTION_LABELS.get(f, f)} (id={f})" for f in remaining_fields[:5]
    ) or "(all section 1 questions answered)"
    next_label = QUESTION_LABELS.get(next_q, "") if next_q else ""
    cs = credit_summary or {}
    credit_block = (
        f"Bonus token state for this client:\n"
        f"- Earned so far: {cs.get('earned', 0)} tokens ({cs.get('questions_credited', 0)} of "
        f"{cs.get('questions_total', len(SECTION1_FIELDS))} questions credited)\n"
        f"- Per question: {cs.get('per_question', 1000)} tokens\n"
        f"- Max possible through the intake: {cs.get('max_possible', len(SECTION1_FIELDS) * 1000)} tokens\n"
        f"- Still available to earn: {cs.get('remaining', 0)} tokens"
    )
    prompt = (
        f"Client name: {client_name or 'the client'}\n"
        f"Client's message: \"{user_text.strip()}\"\n\n"
        f"Next unanswered intake question (id={next_q}): {next_label or '(none — section 1 is complete)'}\n"
        f"Total unanswered in section 1: {len(remaining_fields)}\n\n"
        f"{credit_block}\n\n"
        f"Prior answers in this intake (use these verbatim if they ask):\n{prior_block}\n\n"
        f"Up to 5 remaining questions:\n{remaining_lines}\n\n"
        "Decide and reply now."
    )
    try:
        result = await asyncio.wait_for(
            router.generate(
                prompt=prompt,
                system=_NAVIGATOR_SYSTEM,
                tier=TIER_CLINICAL,
                temperature=0.4,
                max_tokens=300,
                domain="clinical",
                odpe_signal="TENSION",
            ),
            timeout=_OFFER_LLM_TIMEOUT_S,
        )
        raw = (result or {}).get("text", "") or ""
        parsed = _parse_navigator_output(raw)
        parsed["provider"] = (result or {}).get("provider")
        print(
            f">>> [INTAKE-NAV] action={parsed.get('action')} provider={parsed.get('provider')} "
            f"len={len(parsed.get('response', ''))}"
        )
        return parsed
    except asyncio.TimeoutError:
        print(">>> [INTAKE-NAV] timeout")
    except Exception as exc:
        print(f">>> [INTAKE-NAV] error: {exc}")
    return None


def _build_prior_context(intake_row: Dict[str, Any], stop_at: Optional[str] = None) -> str:
    """Return a readable summary of intake answers given so far, stopping before `stop_at`."""
    lines = []
    for field in SECTION1_FIELDS:
        if stop_at and field == stop_at:
            break
        ans = str(intake_row.get(field) or "").strip()
        if not ans or ans in ("[declined_to_answer]", "[skipped]"):
            continue
        label = QUESTION_LABELS.get(field, field)
        lines.append(f"- {label}\n  Client answered: {ans}")
    return "\n".join(lines) if lines else "(no prior answers yet)"


async def _generate_intelligent_clarification(
    *,
    current_q: str,
    client_question: str,
    intake_row: Dict[str, Any],
    client_name: str,
) -> Optional[str]:
    """LLM-generated, context-aware clarification in Little Nate's voice."""
    router = _get_router()
    if router is None:
        return None
    prior_block = _build_prior_context(intake_row, stop_at=current_q)
    current_label = QUESTION_LABELS.get(current_q, current_q)
    system = (
        "You are Little Nate, a warm clinical AI companion guiding a client through a brief intake. "
        "The client just asked a clarification question. Reply in 1-3 sentences. "
        "Anchor pronouns like 'this' or 'that' to what the client already shared. "
        "Be specific, concrete, and human. Use their name once if natural. "
        "Do NOT lecture, do NOT add disclaimers, do NOT repeat the original question verbatim. "
        "End by gently re-asking the question in plainer, friendlier words."
    )
    prompt = (
        f"Client name: {client_name or 'the client'}\n"
        f"Current intake question (id={current_q}): {current_label}\n\n"
        f"Prior answers in this intake:\n{prior_block}\n\n"
        f"Client just asked: \"{client_question.strip()}\"\n\n"
        "Write Little Nate's reply now. Keep it short, warm, and concrete."
    )
    try:
        result = await asyncio.wait_for(
            router.generate(
                prompt=prompt,
                system=system,
                tier=TIER_CLINICAL,
                temperature=0.5,
                max_tokens=220,
                domain="clinical",
                odpe_signal="TENSION",
            ),
            timeout=_CLARIFY_LLM_TIMEOUT_S,
        )
        text = (result or {}).get("text", "").strip()
        if text:
            print(
                f">>> [INTAKE-CLARIFY-LLM] q={current_q} provider={(result or {}).get('provider')} "
                f"len={len(text)}"
            )
            return text
    except asyncio.TimeoutError:
        print(f">>> [INTAKE-CLARIFY-LLM] timeout q={current_q}")
    except Exception as exc:
        print(f">>> [INTAKE-CLARIFY-LLM] error q={current_q}: {exc}")
    return None


async def _generate_intelligent_ack(
    *,
    current_q: str,
    client_answer: str,
    intake_row: Dict[str, Any],
    client_name: str,
    next_q: Optional[str],
    credited: bool,
    credit_summary: Optional[Dict[str, int]] = None,
) -> Optional[str]:
    """LLM-generated acknowledgement of the client's answer plus a natural transition to the next question."""
    router = _get_router()
    if router is None:
        return None
    prior_block = _build_prior_context(intake_row, stop_at=current_q)
    current_label = QUESTION_LABELS.get(current_q, current_q)
    next_label = QUESTION_LABELS.get(next_q, "") if next_q else ""
    cs = credit_summary or {}
    earned = int(cs.get("earned", 0))
    max_possible = int(cs.get("max_possible", len(SECTION1_FIELDS) * 1000))
    if credited:
        token_line = (
            f"In your reply, weave in naturally (NOT as a tacked-on system note) that they just earned "
            f"1000 bonus tokens for that answer — they're now at {earned} of {max_possible} possible "
            f"from the intake. Mention it like a friend would, not like a system."
        )
    else:
        token_line = (
            "Do NOT mention tokens in your reply (they re-answered an already-credited question, so no "
            "tokens were awarded this time)."
        )
    if not next_q:
        instruction = (
            "Acknowledge what they shared in 1-2 sentences. Then let them know section 1 is complete "
            "and their coach will pick up the rest, or they can finish in Settings later. "
            "Thank them warmly. Keep total under 4 sentences."
        )
    else:
        instruction = (
            "Acknowledge what they shared in 1 sentence — reflect back something specific they said. "
            "Then naturally transition to the next question. "
            "Do NOT recite the next question word-for-word — phrase it conversationally in your own voice. "
            "Keep total under 4 sentences."
        )
    system = (
        "You are Little Nate, a warm clinical AI companion. You are walking a client through a brief intake. "
        "You just received their answer to one question. "
        "Respond in your normal warm, attuned voice. Be specific to what they said. Do NOT be robotic. "
        f"{instruction} {token_line}"
    )
    prompt = (
        f"Client name: {client_name or 'the client'}\n"
        f"Question you just asked: {current_label}\n"
        f"Their answer: \"{client_answer.strip()}\"\n\n"
        f"Prior answers in this intake:\n{prior_block}\n\n"
        + (f"Next question to ask (id={next_q}): {next_label}\n\n" if next_q else "")
        + "Write Little Nate's reply now."
    )
    try:
        result = await asyncio.wait_for(
            router.generate(
                prompt=prompt,
                system=system,
                tier=TIER_CLINICAL,
                temperature=0.55,
                max_tokens=260,
                domain="clinical",
                odpe_signal="TENSION",
            ),
            timeout=_ACK_LLM_TIMEOUT_S,
        )
        text = (result or {}).get("text", "").strip()
        if text:
            print(
                f">>> [INTAKE-ACK-LLM] q={current_q} next={next_q} "
                f"provider={(result or {}).get('provider')} len={len(text)}"
            )
            return text
    except asyncio.TimeoutError:
        print(f">>> [INTAKE-ACK-LLM] timeout q={current_q}")
    except Exception as exc:
        print(f">>> [INTAKE-ACK-LLM] error q={current_q}: {exc}")
    return None


async def _classify_intent_semantic(user_text: str, current_q: str) -> Optional[Dict[str, Any]]:
    """Returns {intent, confidence, answer_text} or None if classifier unavailable/failed."""
    if not _semantic_enabled():
        return None
    router = _get_router()
    if router is None:
        return None
    question_label = QUESTION_LABELS.get(current_q, current_q)
    prompt = (
        f"Current intake question: {question_label}\n"
        f"Client reply: {user_text.strip()}\n\n"
        "Classify the reply. Return JSON only."
    )
    try:
        result = await asyncio.wait_for(
            router.generate(
                prompt=prompt,
                system=_CLASSIFIER_SYSTEM,
                tier=TIER_UTILITY,
                temperature=0.0,
                max_tokens=120,
                domain="clinical",
                odpe_signal="LOCKED",
            ),
            timeout=_SEMANTIC_TIMEOUT_S,
        )
        text = (result or {}).get("text", "")
        parsed = _parse_classifier_output(text)
        if parsed:
            print(
                f">>> [INTAKE-CLASSIFY] q={current_q} intent={parsed['intent']} "
                f"conf={parsed['confidence']:.2f} provider={(result or {}).get('provider')}"
            )
        return parsed
    except asyncio.TimeoutError:
        print(f">>> [INTAKE-CLASSIFY] timeout for q={current_q}")
        return None
    except Exception as exc:
        print(f">>> [INTAKE-CLASSIFY] error q={current_q}: {exc}")
        return None


async def _execute_section1_restart(
    *,
    conn,
    state: Dict[str, Any],
    username: str,
    hardware_id: str,
    response_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Clear section-1 answers, reset FSM to q1, and return the reply payload."""
    try:
        await reset_section1_answers(
            conn,
            username=username,
            hardware_id=hardware_id,
            actor_id=username,
            reason="client_requested_restart",
        )
    except Exception as exc:
        print(f">>> [INTAKE-RESTART] failed: {exc}")
        return {
            "handled": True,
            "response": (
                "I couldn't clear your previous answers just now. Try again in a moment, "
                "or you can edit any answer directly from the intake screen in Settings."
            ),
        }
    first_q = SECTION1_FIELDS[0]
    state["active"] = True
    state["current_q"] = first_q
    state["offered"] = True
    state["declined"] = False
    state["nonsense_reprompted"] = False
    state["needs_resume_prompt"] = False
    label = QUESTION_LABELS.get(first_q, "What name would you like me to use for you?")
    reply = (response_override or "").strip()
    if not reply:
        reply = f"Okay — clearing your section 1 answers so we can start fresh. {label}"
    elif label.lower().rstrip("?") not in reply.lower():
        # Defensive: if the LLM forgot to actually ask q1, append it.
        reply = f"{reply} {label}"
    print(f">>> [INTAKE-RESTART] user={username} reset complete, current_q={first_q}")
    return {"handled": True, "response": reply}


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
            client_name = str(intake.get("q1_preferred_name") or profile.get("name") or "").strip()

            credit_summary: Optional[Dict[str, int]] = None
            try:
                credit_summary = await summarize_walkthrough_credits(conn, username=username)
            except Exception as _cs_err:
                print(f">>> [INTAKE] credit summary failed: {_cs_err}")

            # Let Nate read the state and decide. One call, full intelligence, his voice.
            nav = await _nate_intake_navigator(
                user_text=user_text,
                intake=intake,
                next_q=next_q,
                client_name=client_name,
                credit_summary=credit_summary,
            )
            if nav:
                action = nav.get("action", "respond")
                response = nav.get("response", "").strip()
                if action == "restart":
                    return await _execute_section1_restart(
                        conn=conn,
                        state=st,
                        username=username,
                        hardware_id=uid,
                        response_override=response,
                    )
                if action == "resume" and next_q:
                    st["active"] = True
                    st["current_q"] = next_q
                    st["nonsense_reprompted"] = False
                    st["declined"] = False
                    st["needs_resume_prompt"] = False
                    return {"handled": True, "response": response or QUESTION_LABELS.get(next_q, "")}
                if action == "decline":
                    st["declined"] = True
                    return {"handled": True, "response": response or "No problem - we can do it later in Settings whenever you're ready."}
                # action == "respond" — Nate is just answering them. Don't change FSM state.
                if response:
                    return {"handled": True, "response": response}

            # Tiny defensive fallback if navigator errored entirely.
            if _contains_any(low, _RESTART_TERMS):
                return await _execute_section1_restart(
                    conn=conn,
                    state=st,
                    username=username,
                    hardware_id=uid,
                )
            if any(term in low for term in _ACCEPT_TERMS) and next_q:
                st["active"] = True
                st["current_q"] = next_q
                st["nonsense_reprompted"] = False
                st["declined"] = False
                st["needs_resume_prompt"] = False
                return {"handled": True, "response": QUESTION_LABELS.get(next_q, "Let's start with the first intake question.")}
            if any(term in low for term in _DECLINE_TERMS):
                st["declined"] = True
                return {"handled": True, "response": "No problem - we can do it later in Settings whenever you're ready."}
            return {"handled": False}

        # Active walkthrough
        # Explicit rule-based "start over" — clear answers and walk from q1 again.
        # Must run BEFORE the semantic classifier so the restart phrase isn't saved
        # as the current question's answer.
        if _contains_any(user_text, _RESTART_TERMS):
            return await _execute_section1_restart(
                conn=conn,
                state=st,
                username=username,
                hardware_id=uid,
            )

        # Explicit rule-based "stop the intake" — surface a clear choice instead of silently dropping out.
        if _contains_any(user_text, _TOPIC_SHIFT_TERMS):
            st["needs_resume_prompt"] = True
            st["active"] = False
            return {
                "handled": True,
                "response": (
                    "Want to pause the intake and pick this up another time, or keep going? "
                    "Just say 'continue' to keep answering, or 'pause' to come back later."
                ),
            }

        current_q = st.get("current_q") or next_q
        if not current_q:
            st["active"] = False
            return {"handled": False}

        # Semantic intent classifier (primary path). Falls through to rules on miss.
        semantic = await _classify_intent_semantic(user_text, current_q)
        sem_intent = (semantic or {}).get("intent", "")
        sem_conf = float((semantic or {}).get("confidence", 0.0))
        sem_answer = (semantic or {}).get("answer_text", "") or ""

        client_name = str(intake.get("q1_preferred_name") or profile.get("name") or "").strip()

        # High-confidence semantic routes
        if semantic and sem_conf >= _SEMANTIC_CONF_FLOOR:
            if sem_intent == "crisis":
                st["active"] = False
                st["current_q"] = None
                st["needs_resume_prompt"] = True
                return {"handled": False}
            if sem_intent == "stop_intake":
                st["needs_resume_prompt"] = True
                st["active"] = False
                st["nonsense_reprompted"] = False
                return {
                    "handled": True,
                    "response": (
                        "Want to pause the intake and pick it back up later, or keep going? "
                        "Just say 'continue' to keep answering, or 'pause' to come back."
                    ),
                }
            if sem_intent == "clarify_question":
                st["nonsense_reprompted"] = False
                smart = await _generate_intelligent_clarification(
                    current_q=current_q,
                    client_question=user_text,
                    intake_row=intake,
                    client_name=client_name,
                )
                return {"handled": True, "response": smart or _clarify_for_question(current_q)}
            if sem_intent == "nonsense":
                if not st.get("nonsense_reprompted"):
                    st["nonsense_reprompted"] = True
                    return {
                        "handled": True,
                        "response": f"I want to make sure I capture this correctly. {QUESTION_LABELS.get(current_q, 'Could you answer that one in your own words?')}",
                    }
                # Already reprompted once — save verbatim to keep momentum.
                answer_value = user_text.strip()
            elif sem_intent == "decline":
                answer_value = "[declined_to_answer]"
            elif sem_intent == "answer":
                answer_value = (sem_answer.strip() or user_text.strip())
            else:
                answer_value = user_text.strip()
        else:
            # Low confidence or classifier unavailable — fall back to rules.
            if _looks_clarification_request(user_text):
                st["nonsense_reprompted"] = False
                smart = await _generate_intelligent_clarification(
                    current_q=current_q,
                    client_question=user_text,
                    intake_row=intake,
                    client_name=client_name,
                )
                return {"handled": True, "response": smart or _clarify_for_question(current_q)}

            if _looks_nonsense(user_text):
                if not st.get("nonsense_reprompted"):
                    st["nonsense_reprompted"] = True
                    return {
                        "handled": True,
                        "response": f"I want to make sure I capture this correctly. {QUESTION_LABELS.get(current_q, 'Could you answer that one in your own words?')}",
                    }

            if _contains_any(user_text, _REFUSAL_TERMS):
                answer_value = "[declined_to_answer]"
            elif user_text.strip().lower() in {"skip", "pass"}:
                answer_value = "[skipped]"
            else:
                # Classifier saw it but was unsure — if it suspected clarify_question with mid confidence, prefer clarify over saving wrong data.
                if sem_intent == "clarify_question" and sem_conf >= 0.40:
                    st["nonsense_reprompted"] = False
                    smart = await _generate_intelligent_clarification(
                        current_q=current_q,
                        client_question=user_text,
                        intake_row=intake,
                        client_name=client_name,
                    )
                    return {"handled": True, "response": smart or _clarify_for_question(current_q)}
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

        # Read fresh credit totals AFTER the credit attempt for accurate running tally.
        ack_credit_summary: Optional[Dict[str, int]] = None
        try:
            ack_credit_summary = await summarize_walkthrough_credits(conn, username=username)
        except Exception as _cs_err:
            print(f">>> [INTAKE] ack credit summary failed: {_cs_err}")

        # Build context-aware acknowledgement via LLM (Little Nate's actual voice).
        # Skip LLM ack when the answer is a refusal/skip marker — keep that path crisp.
        use_llm_ack = answer_value not in ("[declined_to_answer]", "[skipped]")
        smart_ack: Optional[str] = None
        if use_llm_ack:
            smart_ack = await _generate_intelligent_ack(
                current_q=current_q,
                client_answer=answer_value,
                intake_row=refreshed,
                client_name=client_name,
                next_q=next_after,
                credited=bool(credit.get("credited")),
                credit_summary=ack_credit_summary,
            )

        if next_after:
            st["current_q"] = next_after
            if smart_ack:
                return {"handled": True, "response": smart_ack}
            if credit.get("credited") and ack_credit_summary:
                token_line = (
                    f"That earned you 1000 bonus tokens — you're at "
                    f"{ack_credit_summary.get('earned', 0)} of "
                    f"{ack_credit_summary.get('max_possible', 0)} from the intake."
                )
            elif credit.get("credited"):
                token_line = "That earned you 1000 bonus tokens."
            else:
                token_line = "That answer is saved."
            return {
                "handled": True,
                "response": f"Got it - saved. {token_line} Next question: {QUESTION_LABELS.get(next_after, next_after)}",
            }

        st["active"] = False
        st["current_q"] = None
        if smart_ack:
            return {"handled": True, "response": smart_ack}
        return {
            "handled": True,
            "response": (
                "That's section 1 done - I've got what I need to support you better now. "
                "Your coach will follow up on the rest of the intake in your next session, "
                "or you can fill it in yourself in settings whenever you want. "
                "Thanks for walking through this with me."
            ),
        }
