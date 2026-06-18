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

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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
    r"\bis (?:this|that|it) (?:reasonable|proportionate|okay|normal|healthy|sustainable)\b",
    r"\bdoes (?:this|that) make sense\b",
    r"\bdo you think\b",
    r"\bam i (?:wrong|overreacting|being too|crazy)\b",
    r"\bgive me (?:an answer|a straight answer|your take)\b",
    r"\bjust tell me\b",
]

# Critique aimed at the conversation / the bot's behavior, not at content.
_META_PATTERNS = [
    r"\byou'?re doing it again\b",
    r"\byou (?:still )?(?:don'?t|didn'?t) get it\b",
    r"\b(?:that|this|the last message) (?:was|is) (?:about|directed (?:at|to|toward))\b",
    # ^ broadened after self-test miss: "the last message was directed at YOU
    #   and your responses" did not match the narrower original. This is a live
    #   example of lexical-matching brittleness — see LIMITATIONS in the spec.
    r"\bi'?m tired of being analyzed\b",
    r"\bstop (?:analyzing|reframing|reflecting)\b",
    r"\byou keep (?:asking|handing|turning|reframing|analyzing)\b",
    r"\banother (?:framework|framing|theory|question|category)\b",
    r"\bi (?:already )?(?:told|said|answered) (?:you|that)\b.*\b(?:over|again|times|hundred)\b",
    r"\byou'?re (?:avoiding|evasive|on the fence|standing outside)\b",
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


def _any(patterns: list[str], text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


# ─────────────────────────────────────────────────────────────────────────────
# Repetition guard — addresses why detect_assistant_rut kept missing this.
# The prior rut detector (per investigation notes) compared *reflection patterns*
# but was not weight-aware and did not track the literal fallback string. The
# Kristy log shows the identical sentence
#   "I want to think about that more carefully — can you tell me which part
#    of what you shared feels most important to you right now?"
# emitted 4+ times verbatim. That is the single strongest auto-detectable signal
# that the stance has stalled. We track exact + near-exact repeats of the bot's
# own recent closers.
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


@dataclass
class StanceState:
    """Per-conversation rolling state. Persist alongside session, not globally."""
    recent_bot_closers: list[str] = field(default_factory=list)  # last N closer sentences
    position_asks_unanswered: int = 0   # how many times user asked for a view w/o getting one
    consecutive_framings: int = 0       # how many turns in a row we offered framings

    def note_bot_turn(self, bot_text: str) -> None:
        closer = _last_sentence(bot_text)
        self.recent_bot_closers.append(_normalize(closer))
        self.recent_bot_closers = self.recent_bot_closers[-6:]

    def closer_is_stale(self, candidate_closer: str) -> bool:
        c = _normalize(candidate_closer)
        # exact repeat of any recent closer, or 2+ near-identical closers already
        if c in self.recent_bot_closers:
            return True
        near = sum(1 for prev in self.recent_bot_closers if _similar(prev, c))
        return near >= 2


def _last_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return parts[-1] if parts else text.strip()


def _similar(a: str, b: str) -> bool:
    """Cheap token-overlap similarity; avoids a dependency. >0.8 Jaccard => similar."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) > 0.8


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


def classify_intent(user_text: str) -> TurnIntent:
    """Order matters: meta-feedback and explicit position asks beat exploration,
    because those are the ones the current system gets wrong."""
    if _any(_LOW_WEIGHT_PATTERNS, user_text) and len(user_text.split()) <= 8:
        return TurnIntent.LOW_WEIGHT
    if _any(_META_PATTERNS, user_text):
        return TurnIntent.META_FEEDBACK
    if _any(_POSITION_PATTERNS, user_text):
        return TurnIntent.POSITION
    if _any(_EXPLORE_PATTERNS, user_text):
        return TurnIntent.EXPLORE
    return TurnIntent.NEUTRAL


def resolve_stance(
    user_text: str,
    state: StanceState,
    base_addendum: str,
    classifier_intent: Optional[TurnIntent] = None,
) -> StanceDecision:
    """
    base_addendum: whatever MODE_ADDENDA text select_mode already chose.
    classifier_intent: if little_nate_classifier.py already produced an intent,
        pass it; we reconcile rather than ignore it.
    """
    intent = classifier_intent or classify_intent(user_text)

    # Track position pressure across turns. Repeated unanswered "what do you see"
    # is the strongest signal that we are in the stall loop.
    if intent == TurnIntent.POSITION:
        state.position_asks_unanswered += 1
    elif intent in (TurnIntent.META_FEEDBACK,):
        # meta-feedback often *follows* an unanswered position ask
        state.position_asks_unanswered = max(state.position_asks_unanswered, 1)

    # ── META_FEEDBACK: acknowledge and change, in ONE turn. Do not analyze the
    #    feedback. Do not generate framings about why they're frustrated. ──
    if intent == TurnIntent.META_FEEDBACK:
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.ACKNOWLEDGE_AND_ADJUST,
            addendum=_ADDENDUM_ACK_ADJUST,
            end_on_question=False,
            rationale="User critiqued the conversation itself. Treat as an "
                      "instruction to change behavior, not as new content to "
                      "reflect or frame. No closing question.",
        )

    # ── POSITION: witness + assess proportionality. End on a statement. ──
    if intent == TurnIntent.POSITION:
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_ADDENDUM_WITNESS,
            end_on_question=False,
            rationale="User explicitly asked for the bot's observation / a "
                      "proportionality read. Provide a non-diagnostic position "
                      "and stop. Framing menu is the wrong tool here.",
        )

    # ── LOW_WEIGHT: brief, matched response. No framing, no depth-mining. ──
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

    # ── EXPLORE / NEUTRAL: keep existing behavior, but apply two safety brakes ──
    # Brake 1: if we've offered framings several turns running, force a witness
    #          turn to break the rut even absent an explicit position ask.
    if state.consecutive_framings >= 3:
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_ADDENDUM_WITNESS,
            end_on_question=False,
            rationale="Rut brake: 3+ consecutive framing turns. Break pattern "
                      "with a witnessing turn even though this turn didn't "
                      "explicitly demand a position.",
        )

    # Brake 2: never emit a closing question identical/near-identical to a recent
    #          one. The prompt assembler should consult end_on_question; if a
    #          framing turn would close with a stale question, suppress it.
    state.consecutive_framings += 1
    end_q = True
    rationale = "Exploratory/neutral turn. Existing framing behavior retained."
    # NOTE: the actual stale-closer check happens post-generation (see
    # guard_generated_closer below), because we don't know the closer text yet.

    return StanceDecision(
        intent=intent,
        move=StanceMove.REFLECT_AND_FRAME,
        addendum=base_addendum,  # unchanged existing exploratory addendum
        end_on_question=end_q,
        rationale=rationale,
    )


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
    closer = _last_sentence(generated_text)
    is_question = closer.strip().endswith("?")

    must_strip = False
    if is_question and not decision.end_on_question:
        must_strip = True
    elif is_question and state.closer_is_stale(closer):
        must_strip = True

    if must_strip:
        # Remove the trailing question sentence, keep everything before it.
        body = generated_text.strip()
        # split off the last sentence
        sentences = re.split(r"(?<=[.!?])\s+", body)
        if len(sentences) > 1:
            generated_text = " ".join(sentences[:-1]).strip()
        # else: response was ONLY a question; leave it but flag for review
        # (a position/meta turn that produced nothing but a question is a
        #  generation failure worth logging, not silently editing to empty)

    state.note_bot_turn(generated_text)
    return generated_text


# ─────────────────────────────────────────────────────────────────────────────
# ADDENDA. These REPLACE the mode addendum for the turn. They are written to be
# pasted into MODE_ADDENDA as new keys. The in-bounds / out-of-bounds examples
# are deliberately explicit because the whole risk is the bot mistaking
# "witness" for "diagnose."
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
- Do NOT relocate a relational problem into their self-regulation ("how can you
  set better boundaries / regulate / build self-trust") unless they asked for that.
- Do NOT close with "which of these resonates" or "what feels most important."
"""

_ADDENDUM_ACK_ADJUST = """\
STANCE FOR THIS TURN: ACKNOWLEDGE + ADJUST. The person is telling you something
about THIS CONVERSATION — that you keep reframing, analyzing, or asking questions
instead of responding. This is an instruction, not new material to analyze.

DO:
- Acknowledge the pattern directly and briefly: "You're right — I kept handing it
  back to you instead of saying what I see."
- Then actually do the thing they asked for, in the same turn.
- Drop the framing menu and the closing question for this turn.

DO NOT:
- Do NOT analyze WHY they're frustrated.
- Do NOT generate framings about their frustration (this is the exact failure:
  three new framings about not wanting framings).
- Do NOT ask what would help instead — just adjust.
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
    ]

    print("intent classification check:")
    ok = 0
    for text, expected in samples:
        got = classify_intent(text)
        flag = "OK " if got == expected else "MISS"
        if got == expected:
            ok += 1
        print(f"  [{flag}] expected={expected.value:12s} got={got.value:12s} | {text[:55]!r}")
    print(f"  {ok}/{len(samples)} matched\n")

    # closer-strip check
    d = resolve_stance("Do you think it's reasonable that I wanted comfort?", state, base_addendum="")
    print(f"position turn -> move={d.move.value}, end_on_question={d.end_on_question}")
    raw = ("Wanting comfort after crying for days is a normal response. "
           "Which of these framings resonates with you?")
    cleaned = guard_generated_closer(raw, d, state)
    print(f"  raw closer kept? {'NO (stripped)' if cleaned != raw else 'YES'}")
    print(f"  cleaned: {cleaned!r}")
