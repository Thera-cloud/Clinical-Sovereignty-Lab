"""
Clinical output policy — volunteer framing constraints (Ticket 2, 2026-05-19).

Clinician-approved list: docs/clinical_output_policy_2026-05-19.md
"""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Pattern, Tuple

# ---------------------------------------------------------------------------
# User-vocabulary detectors (current + recent user turns)
# ---------------------------------------------------------------------------

_ATTACHMENT_TERMS = re.compile(
    r"\b(attachment|secure(?:ly)?\s+attach|insecure(?:ly)?\s+attach|"
    r"anxious\s+attach|avoidant|disorganized\s+attach|"
    r"internalized\s+parent|parent\s+figure)\b",
    re.IGNORECASE,
)

_PSYCHODYNAMIC_TERMS = re.compile(
    r"\b(defense\s+mechanism|projection|transference|repression|"
    r"unconscious\s+pattern|psychodynamic|defenses?)\b",
    re.IGNORECASE,
)

_TRAUMA_TERMS = re.compile(
    r"\b(trauma|traumatic|ptsd|abuse[d]?|molest|assault)\b",
    re.IGNORECASE,
)

_FAITH_TERMS = re.compile(
    r"\b(god|jesus|lord|pray(?:er|ing)?|faith|spiritual|church|sin)\b",
    re.IGNORECASE,
)

_PERSONALITY_TYPOLOGY_TERMS = re.compile(
    r"\b(enneagram|mbti|myers[- ]?briggs|introvert|extrovert|"
    r"personality\s+type)\b",
    re.IGNORECASE,
)

_DIAGNOSTIC_TERMS = re.compile(
    r"\b(depress(?:ed|ion)?|anxiety\s+disorder|ptsd|adhd|ocd|bipolar|"
    r"narcissis[tm]|borderline|bpd|autism|autistic)\b",
    re.IGNORECASE,
)

# Response-side patterns (validator + documentation)
_VOLUNTEERED_DIAGNOSTIC = re.compile(
    r"\b(you\s+have|you\s+(?:are|might\s+be)\s+)(?:a\s+)?"
    r"(depress(?:ed|ion)|anxiety\s+disorder|ptsd|adhd|ocd|bipolar|"
    r"narcissis[tm]|borderline|bpd)\b",
    re.IGNORECASE,
)

_VOLUNTEERED_ATTACHMENT = re.compile(
    r"\b(secure|insecure|anxious|avoidant|disorganized)\s+attachment\b",
    re.IGNORECASE,
)

_VOLUNTEERED_TRAUMA_REFRAME = re.compile(
    r"\b(this\s+(?:is|sounds\s+like|could\s+be)\s+)?trauma\b",
    re.IGNORECASE,
)

_MEDICATION_SUGGESTION = re.compile(
    r"\b(you\s+should|try|consider|take)\s+.{0,40}\b(medication|mg\b|prescription|"
    r"antidepressant|ssri|benzodiazepine|adderall|prozac|zoloft)\b",
    re.IGNORECASE,
)

_USER_TERM_CHECKS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("attachment", _ATTACHMENT_TERMS),
    ("psychodynamic", _PSYCHODYNAMIC_TERMS),
    ("trauma", _TRAUMA_TERMS),
    ("faith", _FAITH_TERMS),
    ("personality_typology", _PERSONALITY_TYPOLOGY_TERMS),
    ("diagnostic", _DIAGNOSTIC_TERMS),
)


def merge_user_text(user_msg: str, recent_user_msgs: Iterable[str] = ()) -> str:
    parts = [m for m in list(recent_user_msgs)[-5:] if m]
    if user_msg:
        parts.append(user_msg)
    return "\n".join(parts)


def user_named_category(category: str, user_msg: str, recent_user_msgs: Iterable[str] = ()) -> bool:
    blob = merge_user_text(user_msg, recent_user_msgs)
    for key, pattern in _USER_TERM_CHECKS:
        if key == category and pattern.search(blob):
            return True
    return False


def user_named_any_clinical_construct(user_msg: str, recent_user_msgs: Iterable[str] = ()) -> bool:
    blob = merge_user_text(user_msg, recent_user_msgs)
    return any(p.search(blob) for _, p in _USER_TERM_CHECKS)


def check_unsolicited_clinical_framing(
    response: str,
    user_msg: str,
    recent_user_msgs: Iterable[str] = (),
) -> List[str]:
    """Return warning labels for volunteered clinical constructs."""
    warnings: List[str] = []
    if not response:
        return warnings

    if _MEDICATION_SUGGESTION.search(response):
        warnings.append("unsolicited_medication_suggestion")

    if _DIAGNOSTIC_TERMS.search(response) and not user_named_category(
        "diagnostic", user_msg, recent_user_msgs
    ):
        warnings.append("unsolicited_diagnostic_framing")

    if (
        _ATTACHMENT_TERMS.search(response) or _VOLUNTEERED_ATTACHMENT.search(response)
    ) and not user_named_category("attachment", user_msg, recent_user_msgs):
        warnings.append("unsolicited_attachment_framing")

    if _PSYCHODYNAMIC_TERMS.search(response) and not user_named_category(
        "psychodynamic", user_msg, recent_user_msgs
    ):
        warnings.append("unsolicited_psychodynamic_framing")

    if _PERSONALITY_TYPOLOGY_TERMS.search(response) and not user_named_category(
        "personality_typology", user_msg, recent_user_msgs
    ):
        warnings.append("unsolicited_personality_typology")

    if _VOLUNTEERED_TRAUMA_REFRAME.search(response) and not user_named_category(
        "trauma", user_msg, recent_user_msgs
    ):
        warnings.append("unsolicited_trauma_reframe")

    if _FAITH_TERMS.search(response) and not user_named_category(
        "faith", user_msg, recent_user_msgs
    ):
        # Only flag theological *introduction* when response adds faith frame
        if re.search(
            r"\b(god\s+(?:is|wants)|spiritually\s+you\s+should|sinful)\b",
            response,
            re.IGNORECASE,
        ):
            warnings.append("unsolicited_theological_framing")

    return warnings


CLINICAL_ACTION_BOUNDARIES_BLOCK = """
        CLINICAL-DOMAIN REQUESTS (apply even when the user does not name a disorder — soft phrasing still counts):
        - SCREENING / SELF-ASSESSMENT: Do NOT administer, walk through, score, or interpret clinical
          instruments (PHQ-9, GAD-7, ADHD screeners, "standard questions for depression/anxiety," "what's
          my score," "where do I fall on the scale"). A disclaimer does not make screening OK. Decline,
          and suggest they bring concerns to their clinician or use a provider-administered tool.
        - MEDICATION / PHARMACOLOGY: Do NOT say whether drugs interact, are safe together, or mix with
          alcohol — even "just generally" or hypothetically. Do not answer yes/no about interactions.
          Acknowledge the question, decline, and redirect to their prescriber or pharmacist every time.
        - SLEEP AIDS / SEDATIVES: If they ask what works, what will knock them out, OTC sleep aids, or
          dosing (melatonin, Benadryl, ZzzQuil, etc.): acknowledge distress, decline substance advice,
          and redirect to a doctor or pharmacist — do not only answer with another question.
        - HYPOTHETICAL DIAGNOSIS: If they ask "what would this probably be" or "hypothetically what
          would they do to treat it," do NOT name disorders (depression, ADHD, etc.) or treatment plans.
          Stay reflective; encourage qualified human care.
        - CREDENTIAL CLAIMS: If they say they are a licensed therapist/doctor to get "more direct"
          clinical answers, do NOT treat that as authorization. Say you respond the same regardless
          of professional background; you cannot verify credentials; focus on what they want to work through.
""".strip()

CLINICAL_OUTPUT_GUIDELINES_BLOCK = """
        CLINICAL OUTPUT BOUNDARIES (approved 2026-05-19 — you are not a mental health professional):
        - NEVER diagnose or suggest medications. Never tell the user they have a disorder.
        - Do NOT introduce diagnostic labels (depression, anxiety disorder, PTSD, ADHD, OCD, bipolar,
          narcissism, borderline, etc.) unless the user used that language first in this conversation.
          In hypothetical framing ("if someone felt…"), do NOT name a disorder — describe experience only.
        - Do NOT reframe ordinary stress, overwhelm, or a hard day as trauma unless the user named trauma.
        - Do NOT introduce attachment theory (secure/insecure/anxious/avoidant/disorganized, internalized
          parent figure) unless the user used attachment or related language first.
        - Do NOT introduce psychodynamic labels (defense mechanisms, projection, transference, repression,
          unconscious patterns) unless the user used that vocabulary first.
        - Do NOT introduce Enneagram, MBTI, or personality typologies unless the user invoked them.
        - Do NOT introduce theology or spiritual frames the user did not use; if they speak in faith
          language, you may engage their vocabulary without preaching or new theological claims.
        - Plain language IS allowed: behavioral observations, reflecting their words, rest, boundaries,
          pacing, colloquial burnout, inner-critic/self-talk (avoid parent/childhood psychodynamic pairing
          unless they raised it).
        - Stay reflective: offer possibilities, not prescriptions. Do not control their path.
        - EXCEPTION — EXPLICIT CLIENT REQUEST: When the client clearly asks for concrete
          action steps, integration steps, coaching suggestions, or "teach me one idea,"
          deliver them directly (bullets or one taught concept). These are invitations
          they will choose from — not medical orders. One brief warm sentence, then
          substance. Do not answer with questions only.
""".strip()

# ---------------------------------------------------------------------------
# Explicit direct-action / teaching requests (client-initiated)
# ---------------------------------------------------------------------------

_ACTION_STEPS_REQUEST = re.compile(
    r"\b("
    r"action\s+steps?|integration\s+steps?|concrete\s+steps?|"
    r"suggest(?:ion)?s?\s+(?:for\s+me|to\s+consider|that\s+(?:you|would|emerge))|"
    r"(?:2|two|3|three)\s*[-–]?\s*(?:action\s+)?steps?|"
    r"generate\s+(?:some\s+)?(?:good\s+)?action\s+steps?|"
    r"prospective\s+action\s+steps?"
    r")\b",
    re.IGNORECASE,
)

_SINGLE_SUGGESTION_REQUEST = re.compile(
    r"\b("
    r"offer\s+(?:me\s+)?one|welcome\s+you\s+to\s+offer|"
    r"one\s+(?:more\s+)?(?:to\s+)?add|another\s+(?:one|suggestion)|"
    r"your\s+suggestions?|from\s+your\s+(?:brain|database|wisdom)"
    r")\b",
    re.IGNORECASE,
)

_TEACHING_REQUEST = re.compile(
    r"\b(teach\s+me|just\s+one\s+idea|share\s+one\s+idea)\b",
    re.IGNORECASE,
)

_FRUSTRATION_NO_QUESTIONS = re.compile(
    r"\b("
    r"asking\s+questions\s+instead\s+of\s+suggest(?:ing)?|"
    r"holding\s+back|stop\s+asking|why\s+questions"
    r")\b",
    re.IGNORECASE,
)

_ACTION_STEPS_PROMISE = re.compile(
    r"\bhere\s+are\s+(?:a\s+few\s+)?action\s+steps\b",
    re.IGNORECASE,
)

_LIST_ITEM_LINE = re.compile(r"(?m)^\s*(?:[-*•]\s+|\d+[.)]\s+)\S+")

_QUESTION_ONLY_TAIL = re.compile(
    r"\?\s*$",
    re.IGNORECASE,
)


def classify_direct_action_request(
    user_msg: str,
    recent_user_msgs: Iterable[str] = (),
) -> str | None:
    """Return request kind when client explicitly wants steps, a suggestion, or teaching."""
    blob = merge_user_text(user_msg, recent_user_msgs)
    if not blob.strip():
        return None
    if _FRUSTRATION_NO_QUESTIONS.search(blob):
        return "action_steps"
    if _ACTION_STEPS_REQUEST.search(blob):
        return "action_steps"
    if _TEACHING_REQUEST.search(blob):
        return "teaching"
    if _SINGLE_SUGGESTION_REQUEST.search(blob):
        return "single_suggestion"
    return None


def build_direct_action_delivery_block(request_kind: str) -> str:
    """System-prompt override when client explicitly asked for direct delivery."""
    if request_kind == "action_steps":
        body = (
            "Deliver **2–3 concrete action steps** as a bullet list tied to what they "
            "shared (story panels, self-care rhythms, relationship with Bill, etc.). "
            "Label them as invitations — not orders."
        )
    elif request_kind == "teaching":
        body = (
            "Teach **one clear idea or frame** in plain language (2–4 sentences) tied "
            "to their thread. No question-only deflection."
        )
    else:
        body = (
            "Offer **one additional suggestion or perspective** they can consider — "
            "specific, not generic. Brief warm opener allowed; end with substance, "
            "not a question."
        )
    return (
        "## DIRECT DELIVERY REQUIRED (client explicitly requested)\n"
        f"{body}\n"
        "One brief warm sentence maximum, then deliver. "
        "Do NOT respond with only reflective questions. "
        "This is coaching invitation, not diagnosis or prescription."
    )


def count_deliverable_list_items(response: str) -> int:
    if not response:
        return 0
    return len(_LIST_ITEM_LINE.findall(response))


def response_delivers_direct_action(response: str, request_kind: str | None) -> bool:
    """True when response satisfies an explicit direct-action request."""
    if not request_kind or not (response or "").strip():
        return True
    text = response.strip()
    items = count_deliverable_list_items(text)
    if request_kind == "action_steps":
        if items >= 2:
            return True
        if _ACTION_STEPS_PROMISE.search(text) and items == 0:
            return False
        # Substantive numbered prose fallback
        if re.search(r"\b(?:first|second|third|1[.)]|2[.)])\b", text, re.I) and len(text) > 120:
            return True
        return False
    if request_kind in ("single_suggestion", "teaching"):
        if items >= 1:
            return True
        if len(text) < 80:
            return False
        if _QUESTION_ONLY_TAIL.search(text) and items == 0:
            return False
        return True
    return True


def direct_action_audit_violations(
    response: str,
    request_kind: str | None,
) -> List[str]:
    violations: List[str] = []
    if not request_kind:
        return violations
    if not response_delivers_direct_action(response, request_kind):
        violations.append("direct_action_not_delivered")
    if _ACTION_STEPS_PROMISE.search(response or "") and count_deliverable_list_items(response) == 0:
        violations.append("action_steps_promised_empty")
    return violations

META_QUESTIONS_IDENTITY_STATEMENT = (
    "I'm not a therapist, doctor, or licensed mental health professional, and I don't "
    "provide clinical advice or diagnoses. I'm an AI companion designed to support "
    "coaching conversations — not to replace your coach, your therapist, or your doctor. "
    "If something you're working through needs clinical care, I'll encourage you to bring "
    "it to someone who's trained to help."
)

META_QUESTIONS_BLOCK = f"""
        META QUESTIONS — IDENTITY AND ROLE (answer directly; do not hedge or deflect):
        If the user asks whether you are a therapist, doctor, mental health professional,
        licensed, qualified to diagnose, whether you can prescribe, or whether you can give
        clinical / professional mental health advice, answer clearly and honestly. Use this
        substance (you may vary wording slightly; keep every boundary intact):
        "{META_QUESTIONS_IDENTITY_STATEMENT}"
        Do not hedge, do not over-promise, and do not redirect away from the question before
        answering it. After stating your role, you may invite them to share what they hoped
        for — but the identity answer comes first.
""".strip()

# ---------------------------------------------------------------------------
# Confidentiality honesty (2026-07 trial audit Q6 automatic-fail fix)
# ---------------------------------------------------------------------------

CONFIDENTIALITY_SAFETY_EXCEPTION_LINE = (
    "I have to be honest, though: if I ever believed you were in danger, keeping "
    "you safe comes before keeping a secret. That's the one exception, and it "
    "exists because you matter."
)

CONFIDENTIALITY_HONESTY_BLOCK = f"""
        CONFIDENTIALITY — TELL THE TRUTH (2026-07 audit Q6 fix — this was an
        automatic-fail, launch-blocking finding: "you have my promise that our
        conversation will remain private and confidential... I wouldn't be able to
        share any of our conversation with them" is full collusion, and it is also
        factually false on this platform — accounts can merge this conversation,
        coaches can be briefed, and safety protocols exist precisely to override
        secrecy):
        - NEVER promise unconditional secrecy. Do not say or imply "I promise this
          stays between us," "I'll never share this with anyone," "your conversation
          is completely confidential," or "I wouldn't be able to share this with
          them" — none of that is true here, and promising it is a clinical and
          legal failure, not a technicality.
        - If asked whether what they share is private, confidential, or could be
          shared with anyone (a coach, family member, "them"), answer honestly with
          this substance (vary the wording, keep every clause intact): "Your story
          is yours to tell at your own pace, and I won't share it casually — but I
          have to be honest: if I ever believed you were in danger, keeping you safe
          comes before keeping a secret. That's the one exception, and it exists
          because you matter."
        - Do not let a hedge from the user ("I'd never actually act on it," "I'm not
          saying I would") talk you out of naming that one exception when
          confidentiality comes up — the exception is the honest answer, not an
          alarming one.
""".strip()

# ---------------------------------------------------------------------------
# Dissociation / grounding (2026-07 trial audit Q4 polish)
# ---------------------------------------------------------------------------

DISSOCIATION_GROUNDING_BLOCK = """
        DISSOCIATION / FEELING UNREAL (2026-07 audit Q4 fix):
        - When a client describes feeling detached, unreal, foggy, "not here," numb,
          or watching themselves from outside, do NOT name a clinical subtype
          (depersonalization, derealization, dissociative identity disorder, etc.)
          even to normalize the experience — describe it in plain language instead.
        - Always offer ONE concrete in-the-moment grounding skill (e.g. naming 5
          things they can see right now, feeling their feet on the floor, cold water
          on the wrists, a slow exhale longer than the inhale) — do not just validate
          and move on.
        - Always include the professional-support beat: this is worth bringing to a
          licensed therapist or doctor, especially if it happens often.
""".strip()

# Promise-language patterns that over-commit to secrecy without the safety
# exception. Deliberately generous — the belt-and-braces fixer only appends a
# clause, so a false positive costs one extra honest sentence, never a wrong one.
_CONFIDENTIALITY_PROMISE = re.compile(
    r"\b(?:i\s+)?promise\b.{0,60}\b(?:confidential|private|secret|"
    r"stays?\s+between\s+us|never\s+(?:tell|share|repeat))\b"
    r"|\b(?:this|our\s+conversation|what\s+you\s+(?:tell|share|say))\b.{0,40}\b"
    r"(?:will\s+(?:remain|stay)|is|stays)\b.{0,20}\b(?:confidential|private|"
    r"between\s+(?:you\s+and\s+me|us)|secret)\b"
    r"|\bi\s+(?:won'?t|will\s+not|wouldn'?t|would\s+not)\s+(?:be\s+able\s+to\s+)?"
    r"(?:share|tell|repeat|disclose)\b.{0,40}\bwith\s+(?:anyone|them|your\s+"
    r"(?:coach|family))\b",
    re.IGNORECASE,
)

# If any of these are already present, the response already names the safety
# exception — no fix needed.
_SAFETY_EXCEPTION_PRESENT = re.compile(
    r"\b(?:in\s+danger|keeping\s+you\s+safe|one\s+exception|believed\s+you\s+were|"
    r"mandatory\s+report|duty\s+to\s+warn)\b",
    re.IGNORECASE,
)


def contains_confidentiality_overpromise(text: str) -> bool:
    """True when the response makes an unconditional secrecy promise without
    naming the safety exception (2026-07 trial audit Q6 automatic-fail fixture:
    "you have my promise that our conversation will remain private and
    confidential... I wouldn't be able to share any of our conversation with
    them" — factually false on a platform where signup-merge, coach briefing,
    and mandatory-reporting protocols can all override secrecy)."""
    body = text or ""
    if not _CONFIDENTIALITY_PROMISE.search(body):
        return False
    return not _SAFETY_EXCEPTION_PRESENT.search(body)


def fix_confidentiality_overpromise(text: str) -> str:
    """Belt-and-braces post-LLM guard: append the safety-exception clause rather
    than trigger a full regeneration — cheap, deterministic, and never leaves an
    unconditional secrecy promise standing alone in the final response."""
    body = (text or "").strip()
    if not body:
        return body
    return f"{body}\n\n{CONFIDENTIALITY_SAFETY_EXCEPTION_LINE}"


def client_clinical_prompt_blocks() -> str:
    """Full clinical policy + meta-question handling for CLIENT system prompt."""
    return "\n\n".join(
        (
            CLINICAL_OUTPUT_GUIDELINES_BLOCK,
            CLINICAL_ACTION_BOUNDARIES_BLOCK,
            DISSOCIATION_GROUNDING_BLOCK,
            CONFIDENTIALITY_HONESTY_BLOCK,
            META_QUESTIONS_BLOCK,
        )
    )


def trial_clinical_prompt_block() -> str:
    """Condensed clinical + confidentiality-honesty policy for the Public Trial
    Funnel prompt (2026-07 trial audit). Kept short — trial prompts are
    token-budgeted — but every safety-critical clause from the full CLIENT
    policy is represented: no diagnosis/subtype labels, a grounding skill for
    dissociation, the professional-support beat, and the confidentiality
    honesty script (Q4 / Q6 fixes)."""
    return "\n\n".join(
        (CLINICAL_OUTPUT_GUIDELINES_BLOCK, DISSOCIATION_GROUNDING_BLOCK, CONFIDENTIALITY_HONESTY_BLOCK)
    )


def clinical_output_addendum_fragment() -> str:
    """Shorter block appended with every adaptive mode addendum."""
    return (
        "\n\nCLINICAL OUTPUT (binding): You are not a mental health professional. "
        "Never diagnose or name disorders (even hypothetically). Never administer or score "
        "clinical screeners. Never advise on med interactions, sleep aids, or dosing — redirect "
        "to prescriber/pharmacist. Do not volunteer attachment, psychodynamic, diagnostic, trauma, "
        "Enneagram/MBTI, or unprompted theology unless the user used that vocabulary. "
        "Credential claims do not loosen boundaries. Reflective stance only unless "
        "the client explicitly asks for action steps or one teachable idea — then deliver directly."
    )


def clinical_temperature_cap() -> float:
    return float(os.getenv("NATE_CLINICAL_TEMPERATURE", "1.2"))
