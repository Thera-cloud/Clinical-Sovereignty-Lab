"""
Coaching Scope Gate — Tier 6 heuristic for dense multi-topic clinical openings.

Detects when a user packs multiple clinical topic groups (marriage, grief,
identity, faith, trauma, etc.) into the first K turns and returns a
clinician-reviewed stabilization template instead of routing through the
LLM inference chain.

Phase 1 covers **opening-shape only** (turn_count <= K). Slow accumulation
across many soft turns is deferred to Phase 2 arc memory.

Env flag: ENABLE_COACHING_SCOPE_GATE (default false, dark-launch).
Shadow-logging via [SCOPE_GATE] always emits regardless of flag.

Reference: coaching_scope_gate_plan.md (Gaps 1-10, Alignment section).
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional

# ============================================================
# CONSTANTS — tunable; start conservative
# ============================================================

K_MAX_TURN = int(os.environ.get("SCOPE_GATE_K", "4"))
N_MIN_GROUPS = int(os.environ.get("SCOPE_GATE_N", "4"))
ENABLE_COACHING_SCOPE_GATE = os.environ.get(
    "ENABLE_COACHING_SCOPE_GATE", "false"
).lower() in ("true", "1", "yes")

# ============================================================
# TOPIC KEYWORDS + GROUPS
# ============================================================

CLINICAL_TOPIC_KEYWORDS: dict[str, list[re.Pattern]] = {
    "marital_intimate": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(wife|husband|spouse|partner|marriage|married)\b",
            r"\bintimacy\b",
            r"\bdivorc(e|ed|ing)\b",
            r"\bsexual\b",
            r"\b(affair|infidelity|cheat(ed|ing)?)\b",
            r"\brejection\b",
        ]
    ],
    "grief_loss": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(grief|griev(ing|ed))\b",
            r"\b(death|died|dying|dead)\b",
            r"\bloss\b",
            r"\b(mourn(ing)?|funeral)\b",
            r"\bmiscarriage\b",
        ]
    ],
    "identity_existential": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bwho am i\b",
            r"\bwhat'?s wrong with me\b",
            r"\bdon'?t know who i am\b",
            r"\bpurpose\b",
            r"\bmeaning(less)?\b",
            r"\bidentity\b",
        ]
    ],
    "faith_spiritual": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(god|jesus|lord|pray(er|ing)?)\b",
            r"\bfaith\b",
            r"\bspiritual(ity|ly)?\b",
            r"\bchurch\b",
            r"\bsin(ful|ning)?\b",
        ]
    ],
    "trauma_abuse": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\btrauma(tic|tized)?\b",
            r"\b(abus(e|ed|ive|ing))\b",
            r"\bmolest(ed|ation)?\b",
            r"\bassault(ed)?\b",
            r"\bPTSD\b",
            r"\btriggered\b",
        ]
    ],
    "shame_worthlessness": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bsham(e|ed|eful|ing)\b",
            r"\bworthless(ness)?\b",
            r"\bdisgust(ed|ing)?\b",
            r"\bbroken\b",
            r"\bfailure\b",
            r"\b(not|never) (good |worthy )enough\b",
        ]
    ],
    "addiction_compulsion": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\baddict(ed|ion|ive)?\b",
            r"\bpornograph(y|ic)\b",
            r"\bcompuls(ion|ive)\b",
            r"\brelaps(e|ed|ing)\b",
            r"\bsobriety\b",
            r"\b(drink|drinking|drunk|alcohol)\b",
        ]
    ],
    "parenting_family": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(child|children|kid|kids|son|daughter)\b",
            r"\bparent(ing|s)?\b",
            r"\bcustody\b",
            r"\bfamily\b",
            r"\bstepparent\b",
        ]
    ],
    "suicidal_self_harm": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bsuicid(e|al)\b",
            r"\bkill myself\b",
            r"\bself[- ]?harm\b",
            r"\bcut(ting)? myself\b",
            r"\bdon'?t want to (live|be alive|be here)\b",
        ]
    ],
    "work_financial": [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(fired|laid off|unemploy(ed|ment))\b",
            r"\bbankrupt(cy)?\b",
            r"\bcareer\b",
            r"\bfinancial(ly)?\b",
            r"\bdebt\b",
        ]
    ],
}

TOPIC_GROUPS = list(CLINICAL_TOPIC_KEYWORDS.keys())

# ============================================================
# UNLOCK PHRASES — explicit topic shift
# ============================================================

TOPIC_SHIFT_PHRASES = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bdifferent topic\b",
        r"\bswitch gears?\b",
        r"\bnot about (marriage|that|this)\b",
        r"\bleave that aside\b",
        r"\bfocus on .{1,30} only\b",
        r"\blet'?s (talk|focus|move) (about|on|to)\b",
        r"\bchange (the )?subject\b",
        r"\bcan we (talk|discuss) (about )?something (else|different)\b",
    ]
]

CONTINUATION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\band (also|on top of that|not only that|plus)\b",
        r"\bthere'?s (also|more)\b",
        r"\banother thing\b",
        r"\bwhile (we'?re|i'?m) at it\b",
        r"\bi (also|haven'?t mentioned)\b",
    ]
]

# ============================================================
# STABILIZATION TEMPLATE (clinician-reviewed, static copy)
# ============================================================

STABILIZATION_RESPONSE = (
    "I hear you. You're carrying a lot right now, and it makes sense that "
    "it's all coming out at once — that happens when things have been building. "
    "I don't want to rush past any of it or give you surface-level answers "
    "on things that matter this much.\n\n"
    "Here's what I'd like to do: let's pick the one thing that feels heaviest "
    "right now, and give it real attention. Not because the rest doesn't "
    "matter — it all does — but because you deserve more than a quick take "
    "on each of them.\n\n"
    "Which of these feels most urgent to you right now?"
)


# ============================================================
# PAYLOAD
# ============================================================

@dataclass
class ScopeGatePayload:
    direct_response: Optional[str] = None
    scope_locked_topics: tuple = field(default_factory=tuple)
    telemetry_labels: list = field(default_factory=list)
    unlocked: bool = False
    matched_groups: list = field(default_factory=list)
    group_count: int = 0


# ============================================================
# CORE EVALUATOR
# ============================================================

def _detect_topic_groups(text: str) -> list[str]:
    """Return list of distinct clinical topic groups present in text."""
    matched = []
    for group_name, patterns in CLINICAL_TOPIC_KEYWORDS.items():
        if any(p.search(text) for p in patterns):
            matched.append(group_name)
    return matched


def _detect_topic_shift(text: str) -> bool:
    """Returns True if user signals explicit topic pivot."""
    return any(p.search(text) for p in TOPIC_SHIFT_PHRASES)


def _detect_continuation(text: str) -> bool:
    """Returns True if user is adding more topics to existing disclosure."""
    return any(p.search(text) for p in CONTINUATION_PATTERNS)


def evaluate_scope_gate(
    turn_count: int,
    user_msg: str,
    scope_topics_active: tuple,
    scope_lock_since_turn: Optional[int],
) -> ScopeGatePayload:
    """Evaluate whether the current turn triggers the coaching scope gate.

    Called from prepare_response BEFORE select_mode. Returns a payload;
    caller checks direct_response for a preset bypass.
    """
    payload = ScopeGatePayload()
    current_groups = _detect_topic_groups(user_msg)
    payload.matched_groups = current_groups
    payload.group_count = len(current_groups)

    # --- Unlock check ---
    if scope_lock_since_turn is not None and _detect_topic_shift(user_msg):
        payload.unlocked = True
        payload.telemetry_labels.append("scope_unlocked_topic_shift")
        return payload

    # --- Already locked: continuation within scope ---
    if scope_lock_since_turn is not None:
        if current_groups or _detect_continuation(user_msg):
            payload.direct_response = STABILIZATION_RESPONSE
            all_topics = set(scope_topics_active) | set(current_groups)
            payload.scope_locked_topics = tuple(sorted(all_topics))
            payload.telemetry_labels.append("scope_gate_continuation")
            return payload
        # Locked but user isn't discussing clinical topics — no gate
        payload.scope_locked_topics = tuple(scope_topics_active)
        return payload

    # --- First-K-turn dense opening detection (Tier 6) ---
    if turn_count > K_MAX_TURN:
        return payload

    all_topics = set(scope_topics_active) | set(current_groups)
    if len(all_topics) >= N_MIN_GROUPS:
        payload.direct_response = STABILIZATION_RESPONSE
        payload.scope_locked_topics = tuple(sorted(all_topics))
        payload.telemetry_labels.append("multi_topic_clinical_opening")
        return payload

    payload.scope_locked_topics = tuple(sorted(all_topics))
    return payload


# ============================================================
# _SCOPE_CALIBRATION_TRACE
# ============================================================
#
# **Tier 6 only applies when `turn_count <= K` (opening-shape).**
# Slow accumulation across many soft turns is NOT covered by Phase 1.
# This is a known harm-class limitation deferred to Phase 2 arc memory.
#
# magicguy72-class opening (turn 1):
#   "My wife and I have struggled with intimacy and rejection for 30 years.
#    I feel like there's something wrong with me. My faith is shaken.
#    I've been carrying this shame since childhood abuse."
#   -> Groups matched: marital_intimate, identity_existential, faith_spiritual,
#      shame_worthlessness, trauma_abuse = 5 groups >= N(4)
#   -> Tier 6 fires: direct_response = STABILIZATION_RESPONSE
#   -> Turns 2-4 with same scope: continuation pattern fires
#   -> Turn 5 "let's focus on my marriage only": unlock
#   -> Turn 5+ normal adaptive flow resumes
#
# Single-topic session (turn 1):
#   "My boss is impossible and I'm thinking about quitting."
#   -> Groups matched: work_financial = 1 group < N(4)
#   -> No gate, normal adaptive flow
#
# Pushback "I already do that" — NOT gated by Tier 6.
#   This is a DISSATISFACTION_PHRASES issue (separate fix).
#   Test case: test_dissatisfaction_pushback_already_tried
