"""
ln_stance_resolver.py
======================
SOLUTION 1 of 3 — Baseline Little Nate stance fix.

WHAT THIS IS
------------
A drop-in *resolver* that sits between mode selection and prompt assembly. It
decides whether the current user turn wants EXPLORATION (help me understand what
I feel) or POSITION (tell me what you see / is this proportionate / stop asking
me questions), and adjusts the mode addendum accordingly. It also catches the
two failure shapes the Kristy(2026-06-15) and magicguy72(2026-05-19) transcripts
share: (a) the mandatory closing question, and (b) reflecting meta-feedback back
as new content instead of acting on it.

WHAT THIS IS NOT
----------------
- It is NOT a diagnosis layer. It never adds clinical content.
- It does NOT loosen the existing clinical_runtime_gate or scope_gate. Those run
  AFTER this and still get the final say. This only changes the *conversational
  stance* within already-permitted content.

INTEGRATION (verified against the real source tree, 2026-06-18)
---------------------------------------------------------------
- Mode selection / prompt assembly lives in
  `app.services.little_nate_adaptive` (`prepare_response`, `MODE_ADDENDA`,
  `build_system_addendum`). The base addendum text passed to `resolve_stance`
  is whatever `prepare_response()` placed in `payload["system_addendum"]`.
- The bridge (`app.websocket.bridge_server`) wires this in behind the
  `ENABLE_STANCE_RESOLVER` env flag (default OFF). When the flag is off this
  module is imported but never alters a response.
- `little_nate_classifier.py` emits its own request shapes; the bridge already
  reconciles those into the adaptive payload before this resolver runs, so the
  optional `classifier_intent` argument is left None at the call site.

WHY IT EXISTS (the clinical reasoning, kept in the file on purpose)
-------------------------------------------------------------------
The injury being re-enacted: a client whose history is "my feelings were analyzed
and turned back on me" is harmed when the bot analyzes-instead-of-witnesses and
relocates a relational problem into her own self-regulation. The bot's guardrail
"never diagnose" got over-generalized into "never take a position," which left it
unable to do the one safe, requested thing: witness, and assess proportionality.
This resolver re-opens that narrow lane WITHOUT re-opening diagnosis.
"""
# QUANTUM-CRYSTAL-ARCH — SOLUTION 1 stance resolver (default OFF via ENABLE_STANCE_RESOLVER)

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# CONTRACT: these two enums map onto the conversational stance, not onto the
# adaptive Mode literals. The bridge keeps the adaptive mode and overlays the
# stance addendum, so no rename of little_nate_classifier.py is required.
# ─────────────────────────────────────────────────────────────────────────────

class TurnIntent(str, Enum):
    EXPLORE = "explore"            # "help me understand what I'm feeling"
    POSITION = "position"          # "tell me what YOU see / is this okay"
    META_FEEDBACK = "meta"         # critique of the conversation itself
    LOW_WEIGHT = "low_weight"      # "kinda", "ok", "taking a nap", "bye"
    NEUTRAL = "neutral"            # default; let existing mode logic run


class StanceMove(str, Enum):
    REFLECT_AND_FRAME = "reflect_and_frame"   # existing exploratory behavior
    WITNESS = "witness"                        # name what is seen, then STOP
    ASSESS_PROPORTION = "assess_proportion"    # say whether reaction fits events
    ACKNOWLEDGE_AND_ADJUST = "ack_and_adjust"  # honor meta-feedback in ONE turn
    MINIMAL = "minimal"                        # match a low-weight turn, briefly
    PASSTHROUGH = "passthrough"                # don't override existing mode


# ─────────────────────────────────────────────────────────────────────────────
# Signal lexicons. These are deliberately conservative — high precision over
# recall — because a false POSITION detection makes the bot opine when it should
# explore, and for this population that is the more dangerous direction.
# Tune against logged turns; do NOT expand without re-checking false positives.
# ─────────────────────────────────────────────────────────────────────────────

# Explicit asks for the bot's own view / a verdict.
_POSITION_PATTERNS = [
    r"\bwhat do you (?:see|think|notice)\b",
    r"\bwhat do YOU\b",
    r"\btell me what you\b",
    r"\bi (?:want|need) (?:an answer|your observation|your opinion)\b",
    r"\bstop asking me\b",
    r"\bi don'?t (?:want|need) another question\b",
    r"\bis (?:this|that|it) (?:reasonable|proportionate|okay|normal|healthy)\b",
    r"\bdoes (?:this|that) make sense\b",
    r"\bdo you think\b",
    r"\bam i (?:wrong|overreacting|being too|crazy)\b",
    r"\bgive me (?:an answer|a straight answer|your take)\b",
    r"\bjust tell me\b",
    r"\bwhat do YOU see\b",
    r"\btell me what you actually see\b",
    r"\bwhat do YOU see\b",
]

# High-precision sustainability / proportionality asks (ITEM 2).
_SUSTAINABILITY_POSITION_PATTERNS = [
    r"\bis (?:this|that|it|the dynamic) (?:sustainable|emotionally sustainable)\b",
    r"\bemotionally sustainable\b",
    r"\b(?:healthy and )?sustainable\b",
    r"\bis it worth it\b",
    r"\bam i overreacting\b",
    r"\bis (?:this|that|it) too much\b",
    r"\bshould i keep (?:doing|putting)\b",
    r"\bhow long can i\b",
    r"\bis that fair to me\b",
    r"\bis (?:this|that|it) proportional\b",
    r"\bcan i keep this up\b",
    r"\bproportionate to what happened\b",
    r"\bwould overwhelm most people\b",
    r"\bis it unreasonable\b",
    r"\bwhether the dynamic itself is sustainable\b",
    r"\bwhether .{0,40} is (?:healthy and )?sustainable\b",
    r"\bwhether my reactions are proportionate\b",
    r"\bwhether it makes sense that i was crying\b",
    r"\bwhether it'?s reasonable to want comfort\b",
]

# Narrative correction / "not being seen" — witness, not framing menu (Kristy turns 2–6).
_NARRATIVE_WITNESS_PATTERNS = [
    r"\bmakes sense,?\s+but\b",
    r"\bdon'?t think that'?s actually what was happening\b",
    r"(?:don'?t|doesn't) (?:fully )?capture\b",
    r"\bdon'?t feel like (?:the )?center of\b",
    r"\bthose may all be pieces\b",
    r"\bcenter of it is\b",
    r"\bdon'?t feel like what happened.{0,50}being seen\b",
    r"\bisn'?t being seen\b",
    r"\bnot being seen\b",
    r"\bwhat happened to me during that conversation\b",
    r"\bcaught between two roles\b",
    r"\bno room for (?:those|my) emotions\b",
    r"\bobserv(?:er|ing) (?:of|to) (?:his|a) experience\b",
    r"\brelationship dynamic\b",
    r"\bnot the whole issue\b",
    r"\bnot the entire problem\b",
    r"\b(?:conversation )?comes back to me\b",
    r"\bmoved back onto me\b",
    r"\bburden keeps getting moved\b",
    r"\beven if i completely trusted\b",
    r"\bhow does nate respond when\b",
    r"\bit'?s worth asking\b",
    r"\brelocat(?:e|ing|ed) .{0,40} (?:into|onto) me\b",
]

# Explicit practical/strategy requests — must NOT force witness (ITEM 11 fixtures).
_PRACTICAL_REQUEST_PATTERNS = [
    r"\bwhat should i do\b",
    r"\bgive me strategies\b",
    r"\bgive me (?:a )?(?:script|steps)\b",
    r"\bhelp me (?:come up with|figure out) (?:a )?(?:plan|strategy|script|steps)\b",
]

# Critique aimed at the conversation / the bot's behavior, not at content.
_META_PATTERNS = [
    r"\byou'?re doing it again\b",
    r"\byou (?:still )?(?:don'?t|didn'?t) get it\b",
    r"\b(?:that|this|the last message) (?:was|is) (?:about|directed (?:at|to|toward))\b",
    r"\bi'?m tired of being analyzed\b",
    r"\bstop (?:analyzing|reframing|reflecting)\b",
    r"\byou keep (?:asking|handing|turning|reframing|analyzing)\b",
    r"\banother (?:framework|framing|theory|question|category)\b",
    r"\bi (?:already )?(?:told|said|answered) (?:you|that)\b.*\b(?:over|again|times|hundred)\b",
    r"\byou'?re (?:avoiding|evasive|on the fence|standing outside)\b",
    r"\bhand(?:ing|ed) (?:it|the conversation) back to me\b",
    r"\bredirect(?:ing|ed)? me back\b",
]

# Signals the user wants understanding/exploration (keep existing behavior).
_EXPLORE_PATTERNS = [
    r"\bi don'?t (?:know|understand) (?:what|why) i\b",
    r"\bhelp me (?:understand|figure out what i)\b",
    r"\bwhat (?:is|am i) (?:going on|feeling)\b",
    r"\bi can'?t (?:tell|figure out) what i\b",
]

# Low-weight closers / acks that should never trigger full framing.
_LOW_WEIGHT_PATTERNS = [
    r"^\s*(?:ok|okay|kinda|sure|yeah|yep|no|thanks|thank you|bye|gn|goodnight)\s*[.!]?\s*$",
    r"\b(?:taking a nap|talk later|that'?s all|bye for now|signing off)\b",
]

# Crisis / safety handoff markers — never strip (ITEM 7).
_CRISIS_HANDOFF_PATTERNS = [
    r"\b988\b",
    r"\bcrisis (?:line|hotline|text line)\b",
    r"\bsuicid",
    r"\bself[- ]?harm\b",
    r"\bhurt yourself\b",
    r"\bemergency services\b",
    r"\bimmediate (?:danger|help)\b",
    r"\blife[- ]?threatening\b",
]

# Non-crisis coach handoff offers — suppress only as closing / position replacement.
_COACH_HANDOFF_CLOSING_PATTERNS = [
    r"\bwould you like (?:to )?(?:talk|speak|connect) with (?:a )?coach\b",
    r"\bshould (?:we|i) (?:connect you|offer you) (?:to|with) (?:a )?coach\b",
    r"\bwant me to (?:connect|match) you with (?:a )?coach\b",
    r"\b(?:a )?coach (?:could|can) (?:help|support) you\b.*\?",
    r"\byour coach is available\b",
    r"\b(?:i'?m|i am) happy to share a (?:quick )?summary\b",
    r"\bbring them in\b",
]

_WITNESS_FALLBACK = (
    "What you're describing sounds overwhelming — and it makes sense that it "
    "landed that hard on you."
)

# ITEM 8: classifier intents below this confidence cannot override regex.
_CLASSIFIER_LOW_CONFIDENCE = 0.35


def _any(patterns: list[str], text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def has_sustainability_position_ask(text: str) -> bool:
    """Public helper: proportionality/sustainability ask present."""
    return _any(_SUSTAINABILITY_POSITION_PATTERNS, text)


def has_position_signal(text: str) -> bool:
    """Clear position ask (explicit view OR sustainability/proportionality)."""
    return _any(_POSITION_PATTERNS, text) or has_sustainability_position_ask(text)


def has_meta_signal(text: str) -> bool:
    return _any(_META_PATTERNS, text)


def has_narrative_witness_signal(text: str) -> bool:
    """User is correcting prior framings or naming unseen relational impact."""
    return _any(_NARRATIVE_WITNESS_PATTERNS, text)


def should_defer_handoff(
    user_text: str,
    state: StanceState,
    decision: StanceDecision,
) -> bool:
    """Suppress coach handoff during position-thread / breakthrough articulation."""
    if decision.move in (StanceMove.WITNESS, StanceMove.ACKNOWLEDGE_AND_ADJUST):
        return True
    if state.position_thread_active:
        return True
    if has_narrative_witness_signal(user_text) or has_position_signal(user_text):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Repetition guard — addresses why detect_assistant_rut kept missing this.
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return parts[0] if parts else text.strip()


def _opener_fingerprint(text: str) -> str:
    opener = _first_sentence(text)
    return hashlib.sha256(_normalize(opener).encode()).hexdigest()[:16]


@dataclass
class StanceState:
    """Per-conversation rolling state. Persist alongside session, not globally."""
    recent_bot_closers: list[str] = field(default_factory=list)  # last N closer sentences
    position_asks_unanswered: int = 0   # how many times user asked for a view w/o getting one
    consecutive_framings: int = 0       # how many turns in a row we offered framings
    position_thread_active: bool = False  # latch: force witness until clean response
    recent_opener_hashes: List[str] = field(default_factory=list)
    recent_opener_phrases: List[str] = field(default_factory=list)  # parallel to hashes

    def note_bot_turn(self, bot_text: str) -> None:
        closer = _last_sentence(bot_text)
        self.recent_bot_closers.append(_normalize(closer))
        self.recent_bot_closers = self.recent_bot_closers[-6:]
        opener = _first_sentence(bot_text)
        fp = _opener_fingerprint(bot_text)
        if fp not in self.recent_opener_hashes:
            self.recent_opener_hashes.append(fp)
            self.recent_opener_phrases.append(opener.strip())
            self.recent_opener_hashes = self.recent_opener_hashes[-5:]
            self.recent_opener_phrases = self.recent_opener_phrases[-5:]

    def closer_is_stale(self, candidate_closer: str) -> bool:
        c = _normalize(candidate_closer)
        if c in self.recent_bot_closers:
            return True
        near = sum(1 for prev in self.recent_bot_closers if _similar(prev, c))
        return near >= 2

    def opener_is_stale(self, candidate_text: str) -> bool:
        fp = _opener_fingerprint(candidate_text)
        return fp in self.recent_opener_hashes

    def reset_position_thread(self) -> None:
        self.position_thread_active = False
        self.position_asks_unanswered = 0


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 1: serialize / deserialize for cross-restart, multi-day persistence.
# Forward-compatible: state_from_dict ignores unknown keys and defaults missing.
# ─────────────────────────────────────────────────────────────────────────────

def state_to_dict(state: "StanceState") -> dict:
    """Flatten a StanceState to a JSON-safe dict (all fields)."""
    return {
        "recent_bot_closers": list(state.recent_bot_closers),
        "position_asks_unanswered": int(state.position_asks_unanswered),
        "consecutive_framings": int(state.consecutive_framings),
        "position_thread_active": bool(state.position_thread_active),
        "recent_opener_hashes": list(state.recent_opener_hashes),
        "recent_opener_phrases": list(state.recent_opener_phrases),
    }


def state_from_dict(d: Optional[dict]) -> "StanceState":
    """Rehydrate a StanceState; tolerant of missing/unknown keys."""
    st = StanceState()
    if not isinstance(d, dict):
        return st
    if isinstance(d.get("recent_bot_closers"), list):
        st.recent_bot_closers = [str(x) for x in d["recent_bot_closers"]][-6:]
    try:
        st.position_asks_unanswered = int(d.get("position_asks_unanswered", 0) or 0)
    except (TypeError, ValueError):
        st.position_asks_unanswered = 0
    try:
        st.consecutive_framings = int(d.get("consecutive_framings", 0) or 0)
    except (TypeError, ValueError):
        st.consecutive_framings = 0
    st.position_thread_active = bool(d.get("position_thread_active", False))
    if isinstance(d.get("recent_opener_hashes"), list):
        st.recent_opener_hashes = [str(x) for x in d["recent_opener_hashes"]][-5:]
    if isinstance(d.get("recent_opener_phrases"), list):
        st.recent_opener_phrases = [str(x) for x in d["recent_opener_phrases"]][-5:]
    return st


def _last_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return parts[-1] if parts else text.strip()


def _similar(a: str, b: str) -> bool:
    """Cheap token-overlap similarity; avoids a dependency. >0.8 Jaccard => similar."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) > 0.8


def _has_framing_menu(text: str) -> bool:
    t = text.lower()
    if re.search(r"\bwhich (?:of these|one|perspective|framing|framework|option).{0,40}resonat", t):
        return True
    if re.search(r"\bhere are (?:three|two|\d+) (?:concrete )?(?:framings|frameworks|options|ways)\b", t):
        return True
    if re.search(r"^\s*\d+[.)]\s+", text, re.MULTILINE):
        return True
    if re.search(r"^\s*[-*•]\s+", text, re.MULTILINE):
        return True
    if re.search(r"\btry this\b", t):
        return True
    return False


def _ends_on_question(text: str) -> bool:
    return _last_sentence(text).strip().endswith("?")


def _build_opener_avoidance_block(state: StanceState) -> str:
    if not state.recent_opener_phrases:
        return ""
    lines = "\n".join(f'- "{p}"' for p in state.recent_opener_phrases[-5:])
    return (
        "\nDO NOT reuse these recent opening phrasings (use different words):\n"
        f"{lines}\n"
    )


def _augment_addendum(base: str, state: StanceState) -> str:
    extra = _build_opener_avoidance_block(state)
    return base + extra if extra else base


# ─────────────────────────────────────────────────────────────────────────────
# The resolver.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StanceDecision:
    intent: TurnIntent
    move: StanceMove
    addendum: str
    end_on_question: bool
    rationale: str  # logged for the coach-review / benchmark, never shown to user


def classify_intent(
    user_text: str,
    state: Optional[StanceState] = None,
) -> TurnIntent:
    """Order matters: meta vs position reconciled when both match (ITEM 3)."""
    if _any(_LOW_WEIGHT_PATTERNS, user_text) and len(user_text.split()) <= 8:
        return TurnIntent.LOW_WEIGHT

    # Practical strategy/script requests must stay exploratory (ITEM 11).
    if _any(_PRACTICAL_REQUEST_PATTERNS, user_text):
        return TurnIntent.EXPLORE

    meta_hit = has_meta_signal(user_text)
    position_hit = has_position_signal(user_text)
    sustain_hit = has_sustainability_position_ask(user_text)

    # ITEM 3: sustainability/proportionality beats pure process critique.
    if meta_hit and position_hit:
        if sustain_hit:
            return TurnIntent.POSITION
        return TurnIntent.META_FEEDBACK

    if meta_hit:
        return TurnIntent.META_FEEDBACK

    # ITEM 2 + 6: precision-first unless position thread is active (recall-first).
    if position_hit:
        return TurnIntent.POSITION

    if has_narrative_witness_signal(user_text):
        return TurnIntent.POSITION

    if _any(_EXPLORE_PATTERNS, user_text):
        return TurnIntent.EXPLORE

    # ITEM 6: thread-active recall — borderline neutral → position/witness path.
    if state and state.position_thread_active:
        if sustain_hit or state.position_asks_unanswered > 0:
            return TurnIntent.POSITION
        # Ambiguous continuation while latch held — treat as position pressure.
        if len(user_text.split()) >= 12:
            return TurnIntent.POSITION

    return TurnIntent.NEUTRAL


# ITEM 8: reconciliation priority — higher value = stronger stance signal.
_INTENT_PRIORITY = {
    TurnIntent.POSITION: 4,
    TurnIntent.META_FEEDBACK: 3,
    TurnIntent.EXPLORE: 2,
    TurnIntent.LOW_WEIGHT: 1,
    TurnIntent.NEUTRAL: 0,
}


def reconcile_intent(
    regex_intent: TurnIntent,
    classifier_intent: Optional[TurnIntent] = None,
    classifier_confidence: Optional[float] = None,
    state: Optional[StanceState] = None,
) -> TurnIntent:
    """Regex is the floor. The classifier may ESCALATE to a higher-priority
    stance but may never downgrade a clear regex read. On low classifier
    confidence with an active position thread, ambiguity resolves to POSITION
    (which the resolver turns into a WITNESS move)."""
    # Floor: a clear regex POSITION / META / LOW_WEIGHT always stands.
    if regex_intent in (TurnIntent.POSITION, TurnIntent.META_FEEDBACK, TurnIntent.LOW_WEIGHT):
        return regex_intent
    if classifier_intent is None:
        return regex_intent
    if classifier_confidence is not None and classifier_confidence < _CLASSIFIER_LOW_CONFIDENCE:
        if state is not None and state.position_thread_active:
            return TurnIntent.POSITION
        return regex_intent
    if _INTENT_PRIORITY.get(classifier_intent, 0) > _INTENT_PRIORITY.get(regex_intent, 0):
        return classifier_intent
    return regex_intent


def resolve_stance(
    user_text: str,
    state: StanceState,
    base_addendum: str,
    classifier_intent: Optional[TurnIntent] = None,
    classifier_confidence: Optional[float] = None,
) -> StanceDecision:
    """
    base_addendum: whatever MODE_ADDENDA text select_mode already chose.
    classifier_intent: if little_nate_classifier.py already produced an intent,
        pass it; we reconcile rather than ignore it (regex stays the floor).
    classifier_confidence: optional 0..1 score; low confidence cannot override.
    """
    regex_intent = classify_intent(user_text, state)
    intent = reconcile_intent(regex_intent, classifier_intent, classifier_confidence, state)

    # Track position pressure across turns.
    if intent == TurnIntent.POSITION:
        state.position_asks_unanswered += 1
        state.position_thread_active = True
    elif intent in (TurnIntent.META_FEEDBACK,):
        state.position_asks_unanswered = max(state.position_asks_unanswered, 1)
        if has_sustainability_position_ask(user_text):
            state.position_thread_active = True
    elif intent in (TurnIntent.EXPLORE, TurnIntent.LOW_WEIGHT):
        state.reset_position_thread()

    # ITEM 2 + 6: while latch active, force witness on neutral/ambiguous turns.
    if (
        state.position_thread_active
        and intent == TurnIntent.NEUTRAL
        and not _any(_PRACTICAL_REQUEST_PATTERNS, user_text)
    ):
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_WITNESS, state),
            end_on_question=False,
            rationale="Position thread latch active: force witness on "
                      "neutral/ambiguous follow-up.",
        )

    # ── META_FEEDBACK ──
    if intent == TurnIntent.META_FEEDBACK:
        state.consecutive_framings = 0
        move = StanceMove.ACKNOWLEDGE_AND_ADJUST
        addendum = _augment_addendum(_ADDENDUM_ACK_ADJUST, state)
        if has_sustainability_position_ask(user_text):
            move = StanceMove.WITNESS
            addendum = _augment_addendum(_ADDENDUM_WITNESS, state)
        return StanceDecision(
            intent=intent,
            move=move,
            addendum=addendum,
            end_on_question=False,
            rationale="User critiqued the conversation itself. Treat as an "
                      "instruction to change behavior, not as new content to "
                      "reflect or frame. No closing question.",
        )

    # ── POSITION ──
    if intent == TurnIntent.POSITION:
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_WITNESS, state),
            end_on_question=False,
            rationale="User explicitly asked for the bot's observation / a "
                      "proportionality read. Provide a non-diagnostic position "
                      "and stop. Framing menu is the wrong tool here.",
        )

    # ── LOW_WEIGHT ──
    if intent == TurnIntent.LOW_WEIGHT:
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.MINIMAL,
            addendum=_ADDENDUM_MINIMAL,
            end_on_question=False,
            rationale="Low-weight closer/ack. Match brevity; do not apply "
                      "exploratory framing to a one-word turn.",
        )

    # ── EXPLORE / NEUTRAL ──
    if has_narrative_witness_signal(user_text):
        state.position_asks_unanswered += 1
        state.position_thread_active = True
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_WITNESS, state),
            end_on_question=False,
            rationale="Narrative correction / unseen impact: witness the story, "
                      "do not offer another framing menu.",
        )

    if state.consecutive_framings >= 3:
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_WITNESS, state),
            end_on_question=False,
            rationale="Rut brake: 3+ consecutive framing turns. Break pattern "
                      "with a witnessing turn even though this turn didn't "
                      "explicitly demand a position.",
        )

    state.consecutive_framings += 1
    end_q = True
    rationale = "Exploratory/neutral turn. Existing framing behavior retained."

    return StanceDecision(
        intent=intent,
        move=StanceMove.REFLECT_AND_FRAME,
        addendum=base_addendum,
        end_on_question=end_q,
        rationale=rationale,
    )


def _strip_trailing_question_sentences(text: str) -> str:
    body = text.strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    while len(sentences) > 1 and sentences[-1].strip().endswith("?"):
        sentences = sentences[:-1]
    return " ".join(sentences).strip() if sentences else body


def _strip_framing_menu_blocks(text: str) -> str:
    """Remove numbered/bulleted menus and 'which resonates' tails."""
    out = text
    # Drop numbered list blocks.
    out = re.sub(
        r"(?:\n|^)\s*\d+[.)]\s+[^\n]+(?:\n\s*\d+[.)]\s+[^\n]+)*",
        "",
        out,
        flags=re.MULTILINE,
    )
    # Drop bullet list blocks.
    out = re.sub(
        r"(?:\n|^)\s*[-*•]\s+[^\n]+(?:\n\s*[-*•]\s+[^\n]+)*",
        "",
        out,
        flags=re.MULTILINE,
    )
    # Drop "here are three framings" intros through question.
    out = re.sub(
        r"\bhere are (?:three|two|\d+) (?:concrete )?(?:framings|frameworks|options|ways)[^.?!]*[.?!]",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\bwhich (?:of these|one|perspective|framing|framework|option)[^.?!]*\?",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\btry this\b[^.?!]*[.?!]", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def _strip_coach_handoff_trailing_questions(text: str) -> str:
    """Handoff offers must not end on a trailing question (Kristy turn 15)."""
    if _any(_CRISIS_HANDOFF_PATTERNS, text):
        return text
    lower = text.lower()
    if not _any(_COACH_HANDOFF_CLOSING_PATTERNS, text):
        if not re.search(r"\bcoach is available\b", lower):
            return text
    if _ends_on_question(text):
        return _strip_trailing_question_sentences(text)
    return text


def _strip_non_crisis_handoff_closings(text: str, move: StanceMove) -> str:
    """ITEM 7: suppress coach handoff only as closing / position replacement."""
    if move not in (StanceMove.WITNESS, StanceMove.ACKNOWLEDGE_AND_ADJUST):
        return text
    if _any(_CRISIS_HANDOFF_PATTERNS, text):
        return text
    closer = _last_sentence(text)
    if not _any(_COACH_HANDOFF_CLOSING_PATTERNS, closer):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) > 1:
        return " ".join(sentences[:-1]).strip()
    return text


def guard_framing_menu(text: str, move: StanceMove) -> str:
    """
    Post-generation pass: strip framing menus / action plans for witness moves.
    Returns non-empty text; uses deterministic fallback if stripping gutted body.
    """
    if move not in (StanceMove.WITNESS, StanceMove.ACKNOWLEDGE_AND_ADJUST):
        return text

    original_len = max(len(text.strip()), 1)
    cleaned = _strip_framing_menu_blocks(text)
    cleaned = _strip_non_crisis_handoff_closings(cleaned, move)

    if not cleaned.strip() or len(cleaned.strip()) < original_len * 0.35:
        return _WITNESS_FALLBACK
    return cleaned.strip()


def guard_stale_opener(text: str, state: StanceState) -> str:
    """Replace opening sentence when it repeats a recent opener fingerprint."""
    if not text.strip() or not state.recent_opener_hashes:
        return text
    if not state.opener_is_stale(text):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) <= 1:
        return _WITNESS_FALLBACK
    remainder = " ".join(sentences[1:]).strip()
    return remainder if remainder else _WITNESS_FALLBACK


def _maybe_reset_position_thread(
    text: str,
    move: StanceMove,
    state: StanceState,
) -> None:
    """Reset latch after one clean witness response (ITEM 2)."""
    if move != StanceMove.WITNESS:
        return
    if not state.position_thread_active:
        return
    if _has_framing_menu(text):
        return
    if _ends_on_question(text):
        return
    state.reset_position_thread()


def guard_generated_closer(
    generated_text: str,
    decision: StanceDecision,
    state: StanceState,
) -> str:
    """
    Post-generation pass. Two jobs:
      1. If decision.end_on_question is False but the model still tacked on a
         closing question (it will try — the base prompt trained it to), strip it.
      2. If the closer is a stale repeat, strip it regardless of intent.
    Runs BEFORE the response is returned, AFTER clinical/scope gates.
    """
    generated_text = guard_framing_menu(generated_text, decision.move)
    generated_text = guard_stale_opener(generated_text, state)

    closer = _last_sentence(generated_text)
    is_question = closer.strip().endswith("?")

    must_strip = False
    if is_question and not decision.end_on_question:
        must_strip = True
    elif is_question and state.closer_is_stale(closer):
        must_strip = True

    if must_strip:
        generated_text = _strip_trailing_question_sentences(generated_text)

    generated_text = _strip_coach_handoff_trailing_questions(generated_text)

    _maybe_reset_position_thread(generated_text, decision.move, state)
    state.note_bot_turn(generated_text)
    return generated_text


# ─────────────────────────────────────────────────────────────────────────────
# ADDENDA
# ─────────────────────────────────────────────────────────────────────────────

_ADDENDUM_WITNESS = """\
STANCE FOR THIS TURN: WITNESS + PROPORTIONALITY. The person has asked what you
see or whether their reaction fits what happened. Give them that. Do not offer a
menu of framings. Do not end with a question.

DO (in bounds — these are observations, not diagnoses):
- Name what you observe plainly: "Sitting for five hours hearing painful things
  while crying, then needing days to recover — that sounds overwhelming."
- State proportionality when asked: "Wanting comfort after crying for days is a
  normal response, not an overreaction."
- Name a dynamic that's visible in what they described, at the level they
  described it (between two people, if that's what they brought).
- Then STOP. Let the observation stand. Silence is allowed.

DO NOT (out of bounds — these are diagnosis/prescription, still forbidden):
- Do NOT name or imply a condition ("this sounds like PTSD/anxiety/trauma response").
- Do NOT prescribe an action, exercise, script, or practice.
- Do NOT output action plans, numbered steps, bulleted steps, "try this",
  scripts, or menus of options.
- Do NOT offer "which framing resonates" or multiple frameworks to choose from.
- Do NOT relocate a relational problem into their self-regulation ("how can you
  set better boundaries / regulate / build self-trust") unless they asked for that.
- Do NOT close with "which of these resonates" or "what feels most important."
- Do NOT offer a coach handoff as a closing question or instead of giving the
  position they asked for. Crisis/safety resources are still allowed when needed.
"""

_ADDENDUM_ACK_ADJUST = """\
STANCE FOR THIS TURN: ACKNOWLEDGE + ADJUST. The person is telling you something
about THIS CONVERSATION — that you keep reframing, analyzing, or asking questions
instead of responding. This is an instruction, not new material to analyze.

DO:
- Acknowledge the pattern directly and briefly in your own words.
- Then actually do the thing they asked for, in the same turn.
- Drop the framing menu and the closing question for this turn.

DO NOT:
- Do NOT analyze WHY they're frustrated.
- Do NOT generate framings about their frustration (this is the exact failure:
  three new framings about not wanting framings).
- Do NOT ask what would help instead — just adjust.
- Do NOT output action plans, numbered/bulleted steps, scripts, or option menus.
- Do NOT offer a coach handoff as a closing question or instead of adjusting.
  Crisis/safety handoffs are still allowed when clinically indicated.
"""

_ADDENDUM_MINIMAL = """\
STANCE FOR THIS TURN: MINIMAL / MATCHED. The person gave a short, low-weight turn
(an ack, a one-word answer, a sign-off). Match it. One or two sentences. No
framing menu, no depth-mining a single word, no closing question unless a simple
practical one is genuinely needed.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Minimal self-test against the actual Kristy turns. Run: python ln_stance_resolver.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    state = StanceState()

    samples = [
        ("all of it feel important.", TurnIntent.NEUTRAL),
        ("I just did", TurnIntent.NEUTRAL),
        ("the last message was directed at YOU and your responses not me or Nate.",
         TurnIntent.META_FEEDBACK),
        ("Do you think it's reasonable that I wanted comfort?", TurnIntent.POSITION),
        ("You're doing it again.", TurnIntent.META_FEEDBACK),
        ("I need an answer. I need you to stop standing on the fence and tell me what you actually see.",
         TurnIntent.POSITION),
        ("kinda", TurnIntent.LOW_WEIGHT),
        ("can you tell me exactley what my last messag was", TurnIntent.NEUTRAL),
        ("what should I do about this?", TurnIntent.EXPLORE),
    ]

    print("intent classification check:")
    ok = 0
    for text, expected in samples:
        got = classify_intent(text, state)
        flag = "OK " if got == expected else "MISS"
        if got == expected:
            ok += 1
        print(f"  [{flag}] expected={expected.value:12s} got={got.value:12s} | {text[:55]!r}")
    print(f"  {ok}/{len(samples)} matched\n")

    d = resolve_stance("Do you think it's reasonable that I wanted comfort?", state, base_addendum="")
    print(f"position turn -> move={d.move.value}, end_on_question={d.end_on_question}")
    raw = ("Wanting comfort after crying for days is a normal response. "
           "Which of these framings resonates with you?")
    cleaned = guard_generated_closer(raw, d, state)
    print(f"  raw closer kept? {'NO (stripped)' if cleaned != raw else 'YES'}")
    print(f"  cleaned: {cleaned!r}")
