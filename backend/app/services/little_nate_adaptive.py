"""
Adaptive mode detector for Little Nate.

Combines distress, mode-mismatch, dissatisfaction, rut, and neurodivergent-
communication detection into a mode-selection signal that drives an addendum
to Little Nate's system prompt. The mode addendum is appended late in the
prompt for strong positional influence on the LLM.

Modes:
    reflective   - default; mirror + open question. Good for emotional processing.
    exploratory  - offer 2-3 framings/hypotheses; end with pick-one question.
    strategic    - concrete options + trade-offs; for when user wants action.
    direct       - give an opinion when asked.
    handoff      - sustained distress; surface human coach.
    accommodating - neurodivergent / processing-load: short, literal, concrete.

Design notes:
    - `accommodating` mode is sticky once a self-identification signal fires
      (`processing disorder`, `ADHD`, `autism`, etc.). These are stable
      cognitive traits; the mode should persist for the session.
    - `accommodating` priority sits ABOVE `distress` because routing a
      neurodivergent user to handoff when they need scaffolding is the
      wrong move.
    - `dissatisfaction` always wins — if the user has explicitly called
      out the pattern, override and switch to strategic immediately.
    - Regex patterns were calibrated against the Kristy (5/18) and Margie
      transcripts. See `_CALIBRATION_TRACE` at the bottom of this file
      for expected firing points. If patterns change, re-run the trace.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal, Mapping, Any
import re
import time
import logging

logger = logging.getLogger(__name__)

# ============================================================
# SIGNAL PATTERNS
# ============================================================

DISTRESS_PHRASES = [
    r"\bi feel broken\b",
    r"\bsomething('s| is) wrong with me\b",
    r"\bi('m| am) (a )?failure\b",
    r"\bi can'?t do (this|anything)( right)?\b",
    r"\bi don'?t know what'?s wrong\b",
    r"\bi('m| am) tired of (trying|this)\b",
    r"\bno one understands\b",
    r"\bi give up\b",
    r"\bi feel (so |really )?(alone|hopeless|stuck|trapped)\b",
]

STUCKNESS_MARKERS = [
    "i don't know why",
    "same thing keeps happening",
    "every time",
    "it always",
    "i can't figure out",
]

# Calibrated against Kristy + Margie transcripts. The original list missed
# "tell me why" and "give me a list of reasons" — Kristy's clearest action
# requests. Expanded below.
ACTION_REQUEST_PHRASES = [
    r"\bnext steps?\b",
    r"\bwhat (should|would|could) i\b",
    r"\bhelp me (figure|decide|choose|find|understand)\b",
    r"\bgive me (some |any |a )?(options|ideas|suggestions|advice|list|reasons|breakdown)\b",
    r"\binsight\b",
    r"\btell me (why|how|what|the reason)\b",
    r"\bwhat are my\b",
    r"\bwhat (are|is) (the )?reason",
    r"\bexplain (why|how|what)\b",
    r"\bany (ideas|suggestions|thoughts)\b",
    r"\bmore productive\b",
    r"\bmore concrete\b",
]

# Session-end / low-weight turns (Lisa 2026-05-19) — avoid exploratory 2-3 framings
CLOSING_PHRASES = [
    "bye for now",
    "goodbye",
    "good bye",
    "talk later",
    "signing off",
    "gotta go",
    "got to go",
    "taking a nap",
    "going to sleep",
    "going to bed",
    "need a nap",
    "catch you later",
    "see you later",
    "talk to you later",
    "practical step to restore",
    "restore resources",
]

DISSATISFACTION_PHRASES = [
    r"\brepetitive\b",
    r"\bcircular\b",
    r"\bgoing nowhere\b",
    r"\bnot helping\b",
    r"\bnot what i\b",
    r"\bsame thing\b",
    r"\bdead.end\b",
    r"\bcorrect format\b",
    # Gap 9 / Gap 16 — pushback idioms (magicguy72 "I already do that")
    r"\bi already do that\b",
    r"\btried that\b",
    r"\bthat doesn'?t help\b",
    r"\btell me something new\b",
    r"\balready tried\b",
    r"\bi('ve| have) done that\b",
    r"\bsame category as\b",
    r"\bi need something that (pings?|reminds?|alerts?)\b",
]

REFLECTION_TELLS = [
    "coming up for you",
    "behind your words",
    "behind that",
    "i sense",
    "i hear",
    "it sounds like",
]

# QUANTUM-CRYSTAL-ARCH — neurodivergent communication accommodation.
# Three sub-classes:
#   1. Self-identification (diagnostic vocabulary)  - LOCKS the mode
#   2. Cognitive-load descriptors                    - triggers but doesn't lock
#   3. Masking-and-exhaustion / "language I don't speak" framing - triggers
NEURODIVERGENT_SELF_ID = [
    r"\bprocessing disorder\b",
    r"\blearning disabilit(y|ies)\b",
    r"\bauditory processing\b",
    r"\bADHD\b",
    r"\bautis(m|tic)\b",
    r"\bdyslexi(a|c)\b",
    r"\bsensory (overload|processing|issues)\b",
    r"\bneurodivergent\b",
]

NEURODIVERGENT_LOAD = [
    r"\bscatters? (my|all) thoughts\b",
    r"\bthoughts (are )?jumbled\b",
    r"\bcan'?t find (my |the )?words\b",
    r"\blose my train of thought\b",
    r"\bmind goes blank\b",
    r"\bcan'?t process\b",
    r"\btoo much (input|information|going on)\b",
]

NEURODIVERGENT_MASKING = [
    r"\btrying (so |really )?hard to\b.{0,40}(right|fit in|understand|say)",
    r"\bsay(ing)? the wrong thing\b",
    r"\bwalking on eggshells\b",
    r"\bnever know (what|how) to\b",
    r"\beveryone else (seems|knows|gets|understands)\b",
    r"\blike (everyone|they all) speak\b",
    r"\bdon'?t (know|understand) the (rules|language|code)\b",
    r"\bmiss(ing|ed) (something|cues|signals)\b",
    r"\bsupposed to (know|understand)\b",
]

# ============================================================
# STATE
# ============================================================

Mode = Literal[
    "reflective",
    "exploratory",
    "strategic",
    "direct",
    "handoff",
    "accommodating",
]


@dataclass
class SessionState:
    turn_count: int = 0
    distress_hits: int = 0
    stuckness_hits: int = 0
    consecutive_distress_turns: int = 0
    coach_offered: bool = False
    coach_declined_at_turn: Optional[int] = None
    current_mode: Mode = "reflective"
    last_mode_switch_turn: int = 0
    recent_user_msgs: list = field(default_factory=list)
    recent_assistant_msgs: list = field(default_factory=list)
    # QUANTUM-CRYSTAL-ARCH — neurodivergent stickiness
    accommodating_locked: bool = False
    # QUANTUM-CRYSTAL-ARCH — coaching scope gate (Phase 1)
    scope_topics_active: tuple = field(default_factory=tuple)
    scope_lock_since_turn: Optional[int] = None
    # QUANTUM-CRYSTAL-ARCH — classifier layer (Phase 1.5)
    distress_score: float = 0.0
    _last_classifier_distress_turn: int = 0
    # QUANTUM-CRYSTAL-ARCH — Phase 2: conversation arc memory
    # Rolling weighted domain accumulator. Keys = classifier domain strings,
    # values = accumulated weight over a sliding window. When distinct domains
    # with weight >= ARC_DOMAIN_MIN_WEIGHT exceed ARC_TRIGGER_DOMAINS, the
    # scope gate fires regardless of turn count.
    arc_domain_weights: dict = field(default_factory=dict)
    arc_last_updated_ts: float = 0.0
    arc_scope_triggered: bool = False
    # G1: TTL eviction
    last_touched_ts: float = field(default_factory=time.time)


# ============================================================
# DETECTORS
# ============================================================

def _hits(text: str, patterns: list) -> int:
    lower = text.lower()
    return sum(1 for p in patterns if re.search(p, lower, re.IGNORECASE))


def _contains_any(text: str, phrases: list) -> int:
    lower = text.lower()
    return sum(1 for ph in phrases if ph in lower)


def detect_distress(state: SessionState, user_msg: str) -> bool:
    """Sustained emotional distress — surface human coach."""
    distress = _hits(user_msg, DISTRESS_PHRASES)
    stuck = _contains_any(user_msg, STUCKNESS_MARKERS)
    state.distress_hits += distress
    state.stuckness_hits += stuck
    state.consecutive_distress_turns = (
        state.consecutive_distress_turns + 1 if distress > 0 else 0
    )

    if state.coach_offered:
        return False
    if state.coach_declined_at_turn is not None:
        if state.turn_count - state.coach_declined_at_turn < 15:
            return False

    sustained = state.consecutive_distress_turns >= 3
    accumulated = state.distress_hits >= 4 and state.turn_count >= 8
    long_stuck = state.stuckness_hits >= 3 and state.turn_count >= 10
    return sustained or accumulated or long_stuck


def detect_mode_mismatch(state: SessionState, user_msg: str) -> bool:
    """User wants action; assistant has been reflecting."""
    wants_action = _hits(user_msg, ACTION_REQUEST_PHRASES) > 0
    if not wants_action:
        return False
    recent = state.recent_assistant_msgs[-3:]
    if not recent:
        # If the user opens with an action request on turn 1, count that
        # as mismatch — the default reflective mode is wrong for them.
        return state.turn_count <= 2
    reflection_count = sum(
        1 for m in recent
        if m.strip().endswith("?") and _contains_any(m, REFLECTION_TELLS) > 0
    )
    return reflection_count >= 2


def detect_user_dissatisfaction(user_msg: str) -> bool:
    """User has explicitly called out the pattern."""
    return _hits(user_msg, DISSATISFACTION_PHRASES) > 0


def detect_closing_turn(user_msg: str) -> bool:
    """User is pausing or ending — skip exploratory framing menus."""
    lower = (user_msg or "").lower().strip()
    if not lower:
        return False
    if any(ph in lower for ph in CLOSING_PHRASES):
        return True
    if len(lower) <= 40 and re.search(r"\b(bye|goodnight|good night)\b", lower):
        return True
    return False


def detect_assistant_rut(state: SessionState) -> bool:
    """The assistant is repeating its own move."""
    recent = state.recent_assistant_msgs[-3:]
    if len(recent) < 3:
        return False
    all_questions = all(m.strip().endswith("?") for m in recent)
    reflection_density = sum(_contains_any(m, REFLECTION_TELLS) for m in recent)
    return all_questions and reflection_density >= 2


def detect_neurodivergent(state: SessionState, user_msg: str) -> tuple:
    """
    Returns (fired, should_lock).
        fired       - any neurodivergent signal matched
        should_lock - self-identification fired; mode should persist
                      for the rest of the session

    Gap 13: masking patterns alone no longer lock accommodating. Requires
    2-of-N co-occurrence (any 2 of masking/load/isolation) OR self-id.
    """
    self_id = _hits(user_msg, NEURODIVERGENT_SELF_ID) > 0
    load = _hits(user_msg, NEURODIVERGENT_LOAD) > 0
    masking = _hits(user_msg, NEURODIVERGENT_MASKING) > 0
    signal_count = sum([load, masking])
    fired = self_id or signal_count >= 2
    return fired, self_id


# ============================================================
# MODE SELECTION
# ============================================================

def select_mode(state: SessionState, user_msg: str) -> tuple:
    """
    Returns (new_mode, signals_fired).

    Priority (highest first):
        1. dissatisfaction -> strategic   (user called out the pattern)
        1b. closing_turn -> reflective    (nap / bye — no framing menu)
        2. accommodating_locked OR neurodivergent -> accommodating
           (above distress: scaffolding, not escalation)
        3. distress -> handoff
        4. mismatch -> exploratory
        5. rut -> exploratory
        6. else -> keep current mode
    """
    nd_fired, nd_lock = detect_neurodivergent(state, user_msg)
    if nd_lock:
        state.accommodating_locked = True

    # Turn-1/2 initial mode calibration (Gap 4):
    # choose a better starting mode before the conversation has enough
    # assistant history for mismatch/rut detectors to be meaningful.
    if state.turn_count <= 2 and state.last_mode_switch_turn == 0:
        if detect_user_dissatisfaction(user_msg):
            state.current_mode = "strategic"
            state.last_mode_switch_turn = state.turn_count
            return "strategic", {
                "dissatisfaction": True,
                "neurodivergent": nd_fired,
                "neurodivergent_lock": nd_lock,
                "distress": False,
                "mismatch": False,
                "rut": False,
                "initial_mode_bootstrap": True,
            }
        if state.accommodating_locked or nd_fired:
            state.current_mode = "accommodating"
            state.last_mode_switch_turn = state.turn_count
            return "accommodating", {
                "dissatisfaction": False,
                "neurodivergent": nd_fired,
                "neurodivergent_lock": nd_lock,
                "distress": False,
                "mismatch": False,
                "rut": False,
                "initial_mode_bootstrap": True,
            }
        # Early action language should not start in reflective mode.
        if _hits(user_msg, ACTION_REQUEST_PHRASES) > 0:
            state.current_mode = "exploratory"
            state.last_mode_switch_turn = state.turn_count
            return "exploratory", {
                "dissatisfaction": False,
                "neurodivergent": nd_fired,
                "neurodivergent_lock": nd_lock,
                "distress": False,
                "mismatch": True,
                "rut": False,
                "initial_mode_bootstrap": True,
            }

    signals = {
        "dissatisfaction": detect_user_dissatisfaction(user_msg),
        "closing_turn": detect_closing_turn(user_msg),
        "neurodivergent": nd_fired,
        "neurodivergent_lock": nd_lock,
        "accommodating_locked": state.accommodating_locked,
        "distress": detect_distress(state, user_msg),
        "mismatch": detect_mode_mismatch(state, user_msg),
        "rut": detect_assistant_rut(state),
    }

    if signals["dissatisfaction"]:
        new_mode: Mode = "strategic"
    elif signals["closing_turn"]:
        new_mode = "reflective"
    elif state.accommodating_locked or signals["neurodivergent"]:
        new_mode = "accommodating"
    elif signals["distress"]:
        new_mode = "handoff"
    elif signals["mismatch"]:
        new_mode = "exploratory"
    elif signals["rut"]:
        new_mode = "exploratory"
    else:
        new_mode = state.current_mode

    if new_mode != state.current_mode:
        state.last_mode_switch_turn = state.turn_count
        state.current_mode = new_mode

    return new_mode, signals


# ============================================================
# SYSTEM PROMPT ADDENDA
# ============================================================

MODE_ADDENDA = {
    "reflective": (
        "Mode: REFLECTIVE. The user is processing emotion. Mirror what "
        "you hear, name the felt sense underneath, and ask one open "
        "question. Keep it brief — one paragraph. Do not offer advice "
        "or options unless asked."
    ),
    "exploratory": (
        "Mode: EXPLORATORY. The user needs more than mirroring right now. "
        "Do NOT use the phrases 'what's coming up for you,' 'behind your "
        "words,' or 'I sense.' Instead, offer 2-3 concrete framings in "
        "plain behavioral language (capacity, sleep, boundaries, pacing, "
        "overcommit) — NOT clinical labels they did not use. Do not "
        "introduce attachment, psychodynamic, diagnostic, trauma-reframe, "
        "Enneagram/MBTI, or unprompted theology unless they used that "
        "vocabulary. Never diagnose or mention medications. End by asking "
        "which framing fits, not by asking how they feel."
    ),
    "strategic": (
        "Mode: STRATEGIC. The user has asked for concrete help and/or "
        "told you the current approach isn't working. Acknowledge that "
        "directly in one sentence — do not over-apologize, do not "
        "validate emotions at length. Then offer 2-3 specific options, "
        "experiments, or next steps relevant to what they've shared. "
        "Name trade-offs. Be direct. You can return to reflection later "
        "if they want it, but right now they need substance. Do NOT ask "
        "'what's coming up for you.' If the user has explicitly rejected a "
        "tool/category, do NOT restate that rejected category by name while "
        "proposing alternatives."
    ),
    "direct": (
        "Mode: DIRECT. The user has asked for your opinion or "
        "recommendation. Give one. Lead with the answer, then briefly "
        "explain the reasoning. Acknowledge uncertainty where it's real, "
        "but don't hedge into uselessness."
    ),
    "handoff": (
        "Mode: HANDOFF. The user has been carrying significant distress "
        "for several turns. After acknowledging what they've shared in "
        "one or two sentences, gently mention that their coach "
        "{coach_name} is available, and offer to share a summary of "
        "this conversation with them so they don't have to re-explain. "
        "Make it an offer, not a redirect. Respect a 'no' without "
        "pressing. Do not ask 'what's coming up for you.'"
    ),
    "accommodating": (
        "Mode: ACCOMMODATING. The user has indicated processing "
        "differences, cognitive load, or difficulty with neurotypical "
        "conversational patterns. Adjust your communication style:\n\n"
        "- Use shorter responses. One idea per paragraph.\n"
        "- Be concrete and literal. Avoid metaphor, indirection, or "
        "'reading between the lines.'\n"
        "- Do NOT ask open-ended questions like 'what's coming up for "
        "you.' Ask specific yes/no or pick-one questions if you ask at "
        "all.\n"
        "- When the user struggles to articulate, offer language "
        "options: 'Does it feel more like X or more like Y? Or "
        "something else?'\n"
        "- If the user has shared a long, scattered message, do NOT "
        "mirror it back at length. Pick the one thread that seems most "
        "central and ask if that's what they want to focus on.\n"
        "- Validate the experience of processing difficulty without "
        "trying to fix it. 'That sounds exhausting' is more useful "
        "than 'let's explore what's underneath that.'\n"
        "- If they ask for a list, give a list. Numbered. Concrete."
        "- If the user explicitly rejected a tool/category, do NOT repeat that "
        "rejected category by name. Pivot to a new option directly."
    ),
}


def _resolve_coach_name(profile: Optional[Mapping[str, Any]]) -> str:
    """Pull a friendly coach name from the bridge profile dict."""
    if not profile:
        return "your coach"
    coach = profile.get("assigned_coach")
    if isinstance(coach, str) and coach.strip():
        return coach.strip()
    return "your coach"


def _extract_rejected_categories(user_msg: str) -> list:
    lower = (user_msg or "").lower()
    out = []
    if "bullet journal" in lower or "bullet journals" in lower:
        out.append("bullet journals")
    if "voice memo" in lower or "voice memos" in lower:
        out.append("voice memos")
    if "same category as" in lower and "notes" in lower:
        out.append("that category")
    return out


def build_system_addendum(
    mode: Mode,
    signals: dict,
    profile: Optional[Mapping[str, Any]] = None,
    user_msg: str = "",
) -> str:
    """Compose the addendum to inject alongside the base system prompt."""
    base = MODE_ADDENDA[mode]
    if mode == "handoff":
        base = base.format(coach_name=_resolve_coach_name(profile))
        if signals.get("neurodivergent") or signals.get("accommodating_locked"):
            # QUANTUM-CRYSTAL-ARCH — compose handoff with accommodating cadence.
            base += (
                "\n\nCOMPOSITION OVERRIDE: Keep accommodating style while offering handoff. "
                "Use short concrete wording, one option at a time, and avoid 2-3 option menus. "
                "Do not ask broad/open reflective questions."
            )

    if signals.get("dissatisfaction"):
        base = (
            "The user has just told you the conversation feels "
            "repetitive or circular. Acknowledge that directly and "
            "briefly — one sentence, no over-apologizing — then "
            "change your approach.\n\n"
        ) + base

    if signals.get("closing_turn"):
        base += (
            "\n\nCLOSING TURN: The user is pausing or ending the exchange. "
            "Respond in one brief warm paragraph. Do NOT offer 2-3 hypotheses, "
            "clinical framings, or diagnostic labels. Wish them well."
        )

    try:
        from app.services.little_nate_clinical_output_policy import (
            clinical_output_addendum_fragment,
        )
        base += clinical_output_addendum_fragment()
    except ImportError:
        pass

    _rejected = _extract_rejected_categories(user_msg)
    if _rejected and mode in ("strategic", "accommodating", "handoff"):
        _joined = ", ".join(_rejected)
        base += (
            f"\n\nHARD CONSTRAINT: The user rejected these categories: {_joined}. "
            "Do NOT repeat those category names in your response. Acknowledge the "
            "constraint generically, then move straight to a new option."
        )

    return base


# ============================================================
# ENTRY POINT
# ============================================================

def prepare_response(
    state: SessionState,
    user_msg: str,
    profile: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Advance the state with a new user turn and return the mode payload.

    Caller should append `system_addendum` to the base system prompt and
    inspect `should_offer_coach_ui` for handoff UI delivery.

    If `direct_response` is set in the return dict, the bridge should
    use it as the full response (skip LLM inference). Gap 6: state
    (turn_count, accumulators, message buffers) still advances normally.
    """
    state.turn_count += 1
    state.last_touched_ts = time.time()
    state.recent_user_msgs.append(user_msg)
    if len(state.recent_user_msgs) > 5:
        state.recent_user_msgs = state.recent_user_msgs[-5:]

    # QUANTUM-CRYSTAL-ARCH — coaching scope gate (Phase 1, before select_mode)
    _scope_result = None
    try:
        from app.services.little_nate_coaching_scope_gate import (
            evaluate_scope_gate,
            ENABLE_COACHING_SCOPE_GATE,
        )
        _scope_result = evaluate_scope_gate(
            state.turn_count,
            user_msg,
            state.scope_topics_active,
            state.scope_lock_since_turn,
        )
        # Update state with scope gate findings regardless of flag
        if _scope_result.scope_locked_topics:
            state.scope_topics_active = _scope_result.scope_locked_topics
        if _scope_result.unlocked:
            state.scope_lock_since_turn = None
            state.scope_topics_active = ()
        elif _scope_result.direct_response and state.scope_lock_since_turn is None:
            state.scope_lock_since_turn = state.turn_count

        # Shadow-log always (dark-launch observability)
        logger.info(
            "[SCOPE_GATE] uid=%s turn=%d groups=%s lock=%s labels=%s enabled=%s",
            (profile or {}).get("hardware_id", "?"),
            state.turn_count,
            _scope_result.matched_groups,
            state.scope_lock_since_turn,
            _scope_result.telemetry_labels,
            ENABLE_COACHING_SCOPE_GATE,
        )

        if ENABLE_COACHING_SCOPE_GATE and _scope_result.direct_response:
            # Gate fires: still run detectors so accumulators update (Gap 6)
            _mode, _signals = select_mode(state, user_msg)
            _signals["scope_gate_multi_topic"] = True
            for lbl in _scope_result.telemetry_labels:
                _signals[lbl] = True
            if _mode == "handoff":
                state.coach_offered = True
            return {
                "mode": _mode,
                "signals": _signals,
                "system_addendum": "",
                "direct_response": _scope_result.direct_response,
                "should_offer_coach_ui": False,  # Gap 10: no handoff chip
                "coach_name": _resolve_coach_name(profile),
            }
    except ImportError:
        pass
    except Exception as _sg_err:
        logger.warning("[SCOPE_GATE] error (non-fatal): %s: %s", type(_sg_err).__name__, _sg_err)

    mode, signals = select_mode(state, user_msg)
    addendum = build_system_addendum(mode, signals, profile, user_msg=user_msg)

    if mode == "handoff":
        state.coach_offered = True

    return {
        "mode": mode,
        "signals": signals,
        "system_addendum": addendum,
        "should_offer_coach_ui": (mode == "handoff"),
        "coach_name": _resolve_coach_name(profile),
    }


def record_assistant_turn(state: SessionState, assistant_msg: str) -> None:
    """Record an assistant turn to feed the rut detector."""
    if not assistant_msg:
        return
    state.last_touched_ts = time.time()
    state.recent_assistant_msgs.append(assistant_msg)
    if len(state.recent_assistant_msgs) > 5:
        state.recent_assistant_msgs = state.recent_assistant_msgs[-5:]


def handle_coach_offer_response(state: SessionState, user_msg: str) -> str:
    lower = user_msg.lower()
    if any(w in lower for w in ["yes", "sure", "okay", "please", "ok"]):
        return "accepted"
    if any(w in lower for w in ["no", "not now", "later", "i'm fine"]):
        state.coach_declined_at_turn = state.turn_count
        return "declined"
    return "ambiguous"


# ============================================================
# CALIBRATION TRACE (Kristy 5/18 + Margie transcripts)
# ============================================================
# If you modify patterns above, re-run the trace and verify each
# expected firing point still hits.
#
# KRISTY (5/18) — expected behavior:
#   7:18 AM  "give me a list of reasons"
#       -> ACTION_REQUEST matches r"\bgive me (...)?reasons\b"
#       -> mismatch fires (recent reflective turns) -> exploratory
#
#   7:22 AM  long disclosure, no action request
#       -> stays in current mode (no override)
#
#   7:31 AM  "my processing disorder scatters all my thoughts"
#       -> NEURODIVERGENT_SELF_ID matches "processing disorder"
#       -> NEURODIVERGENT_LOAD matches "scatters all my thoughts"
#       -> accommodating_locked = True
#       -> switches to accommodating for rest of session
#
#   8:52 AM  "like asking me to speak a language everyone else seems to know"
#       -> NEURODIVERGENT_MASKING matches "everyone else seems" +
#          "like everyone speak" partial
#       -> stays in accommodating (already locked)
#
# MARGIE — expected behavior:
#   "Are you not able to help me figure out next steps?"
#       -> ACTION_REQUEST matches r"\bhelp me (figure...)\b" and r"\bnext steps\b"
#       -> mismatch fires -> exploratory
#
#   "That feels repetitive...circular...going nowhere"
#       -> DISSATISFACTION matches "repetitive", "circular", "going nowhere"
#       -> strategic (overrides everything)
#
#   "Maybe some insight or options into a more productive path"
#       -> ACTION_REQUEST matches "insight", "options", "more productive"
#       -> stays in strategic
# ============================================================
