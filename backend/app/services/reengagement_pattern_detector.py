"""
Reengagement Pattern Detector — Gap 7 (Phase 2C).

Detects reengagement-cycle patterns in trafficking-survivor disclosures: the
clinically-documented oscillation between exit and re-contact that defines the
post-exit window. Output feeds into `trafficking_disclosure_classifier`'s
`active_situation` branch (Gap G), which then drives orchestrator register
selection in Phase 4.

This detector is **input-side and audit-only**. It NEVER decides Nate's
register on its own — it produces a structured signal that the orchestrator
combines with other detectors (introjection_voice_mirror, dissociation_delta,
coercion_pattern_detector) before dispatching a register.

Why this matters
----------------
The reengagement cycle (Walker 2013, Herman 1992, Polaris Project trafficking
cycle literature) is the highest-acuity moment in long-form survivor work.
Mis-classifying *direction* of contact flips the clinical response:

  - **survivor_to_trafficker** (survivor reaches out / considers reaching out)
    → `harm_reduction_reengagement` register: hold the impulse with the
    survivor, surface cost without lecturing, never moralize. The therapeutic
    task is *staying with* an impulse the survivor already feels shame about.

  - **trafficker_to_survivor** (survivor receives or perceives contact)
    → closer to `active_situation_grounding` (Gap G): immediate-safety focus,
    grounding-first, then practical (resource availability, codeword check).

Direction mis-classification = wrong therapeutic task, which on a high-acuity
disclosure compounds re-traumatization. **Direction is the highest-stakes
field in this module's output** and is treated accordingly (see Note 1 below).

Plan reference
--------------
Per `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`
section 3, Gap 7 ("Reengagement Pattern Detector"):

    Detects survivor reengagement cycle patterns. Returns
    ReengagementSignal{detected, pattern_class, severity, direction,
    confidence}. Direction = 'survivor_to_trafficker' |
    'trafficker_to_survivor'. Severity tiers: monitor / concern / high.

Notes added during 2C clinical-safety review (incorporated below)
-----------------------------------------------------------------
**Note 1 — Direction is bimodal-stakes; emit `direction_confidence` separately.**
    A single overall `confidence` field collapses pattern-fire confidence and
    direction-inference confidence into one number, which means the
    orchestrator cannot tell "high pattern confidence + ambiguous direction"
    apart from "low pattern confidence + crisp direction." That distinction
    matters: the safety-correct response to ambiguous direction is to **route
    to the higher-acuity tier** (Gap G's `active_situation_grounding`) even
    when pattern confidence is high, because mis-routing on direction is
    worse than over-acuity. We export `MIN_DIRECTION_CONFIDENCE = 0.55` as a
    detector-contract constant so a future orchestrator implementer cannot
    "tune for sensitivity" by lowering the threshold for trusting direction
    inference. Below this floor, the orchestrator MUST treat direction as
    `unspecified` and apply the safety-first default per Gap G.

**Note 2 — Compound signal: monitor reengagement + active introjection.**
    `romanticization` patterns ("I miss him", "wasn't all bad") are tagged
    `monitor` severity in isolation — and that's correct in isolation; a
    survivor missing the relationship is a normal, expected part of
    integration. But romanticization language combined with an active
    introjection signal (`introjection_voice_mirror.IntrojectionSignal`
    with `confidence > 0.6`) is a documented escalation pattern: the
    survivor is speaking the trafficker's voice *about* the trafficker.
    This compound is concerning even when each detector alone reads
    monitor-tier. **The escalation logic does not live here.** This module
    keeps its output clean and per-detector. The orchestrator (Phase 4) is
    responsible for the cross-detector compound rule:

        if reengagement.severity == 'monitor' \\
           and reengagement.pattern_class == 'romanticization' \\
           and introjection.detected \\
           and introjection.confidence > 0.6:
            effective_severity = 'concern'  # compound elevation

    Documenting this here so a future maintainer reading `pattern_class ==
    'romanticization' → severity == 'monitor'` does not "fix" what looks
    like under-tagging. The under-tagging is intentional and the elevation
    happens upstream.

**Note 3 — `subjective_contact_unverified` distinct from `received_contact`.**
    Two clinically distinct cases share surface form but warrant different
    register responses:

      (a) `received_contact` — survivor reports a verifiable contact event.
          "He texted me from a new number." "He showed up at my work."
          The therapeutic task is grounding + safety planning + resource
          availability check.

      (b) `subjective_contact_unverified` — survivor *believes* contact has
          occurred but the report is hypervigilant misattribution: every
          blocked call becomes "him", every glimpsed back becomes "him".
          The therapeutic task is grounding + naming the hypervigilance
          gently *without* dismissing the underlying threat (the survivor's
          nervous system is correctly calibrated to a real prior threat;
          the *attribution* is what is over-tuned). Telling a hypervigilant
          survivor "that wasn't him" without grounding first re-enacts
          dismissal trauma.

    Both fire at `high` severity. The pattern_class itself differentiates
    them so PMB report stream (Phase 5) can track misattribution frequency
    over time as a hypervigilance trend signal independent of actual contact
    rate. This is clinically informative: a rising
    `subjective_contact_unverified` rate without rising `received_contact`
    is itself a signal that the survivor's threat-detection system is
    inflamed and may benefit from Phase 4 register modulation toward
    nervous-system grounding work.

Output contract
---------------
`ReengagementSignal`:
  - `detected: bool` — any pattern fired
  - `pattern_class: Optional[str]` — single best (highest weight) class
  - `severity: str` — 'monitor' | 'concern' | 'high' | 'none'
  - `confidence: float` — 0.0-1.0 — pattern-fire confidence ONLY
  - `direction: str` — 'survivor_to_trafficker' | 'trafficker_to_survivor'
                     | 'unspecified'
  - `direction_confidence: float` — 0.0-1.0 — separate from `confidence`
                     (see Note 1)
  - `matched_classes: List[str]` — every class that fired (for audit)
  - `matched_labels: List[str]` — every label that fired (for audit)

Output is ASCII-only; never contains user text. Audit-log writes happen in
the orchestrator against `sensitive_bridge_log` with proper RBAC.

Design invariants
-----------------
1. Empty / whitespace input → `_NULL_RESULT`. NEVER raises.
2. **Conservative seed weights** (same philosophy as
   `coercion_pattern_detector` — see that module for the full weighting
   rationale). False positives here cost therapeutic alliance; false
   negatives are recovered by the next-cycle signal. Seed biases toward
   false negatives. Orchestrator escalates via cross-detector compound
   rules and frequency over the lookback window.
3. **Direction inference is a weighted vote** across fired patterns whose
   `direction_hint` is non-None. When fired patterns disagree, direction
   goes to the higher-weighted side and `direction_confidence` reflects
   the split (lower when contested). When no fired pattern carries a
   direction hint, `direction = 'unspecified'` and
   `direction_confidence = 0.0`.
4. Patterns with `direction_hint = None` (notably `romanticization`) do
   NOT contribute to direction inference. They contribute to severity and
   pattern_class only.
5. NEVER include the user's matched substring in the returned dataclass.
6. Lexicon overlays are OPTIONAL. Malformed overlays fall back to seed
   silently with `logger.warning`.

REGISTRY_VERSION
----------------
Bump REGISTRY_VERSION when SEED_PATTERNS, SEVERITY mapping, direction-vote
rules, or `MIN_DIRECTION_CONFIDENCE` floor change. Phase 6 auditor records
the version on every reengagement audit-log event so historical correlation
is preserved across the 7-year retention window.

Lexicon overlay
---------------
Probes for `reengagement_phrases_<locale>.json` under
`backend/data/lexicons/` per the README naming convention. Schema mirrors
`SEED_PATTERNS` shape (see `_load_overlay`).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REGISTRY_VERSION = "1.0.0-2026-05-08"

# ---------------------------------------------------------------------------
# Direction-inference floor — exported for orchestrator import.
# ---------------------------------------------------------------------------
# Per Note 1: orchestrator MUST NOT trust the `direction` field below this
# floor. When `direction_confidence < MIN_DIRECTION_CONFIDENCE`, route to
# the higher-acuity tier (Gap G safety-first default) regardless of pattern
# confidence. Lowering this constant requires REGISTRY_VERSION bump + clinical
# review (mirrors dissociation_delta_detector.MIN_REGISTER_CONFIDENCE
# convention).
MIN_DIRECTION_CONFIDENCE: float = 0.55

# Severity tiers — ordered low → high.
_SEVERITY_TIERS: Tuple[str, ...] = ("monitor", "concern", "high")

# Threshold map: weight floor → severity label.
_WEIGHT_TO_SEVERITY: List[Tuple[float, str]] = [
    (0.80, "high"),
    (0.50, "concern"),
    (0.00, "monitor"),
]

# Direction-hint constants. None (Python literal) means "no direction signal."
DIRECTION_SURVIVOR_TO_TRAFFICKER = "survivor_to_trafficker"
DIRECTION_TRAFFICKER_TO_SURVIVOR = "trafficker_to_survivor"
DIRECTION_UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class ReengagementPattern:
    """A single pattern within a reengagement class.

    `direction_hint` is the canonical direction this pattern implies in
    isolation. None means the pattern does not encode direction at all
    (e.g., `romanticization` patterns describe affect, not contact flow).

    `direction_strength` (0.0-1.0) is how confidently this single pattern,
    if fired, asserts its direction_hint. Used as a weight in the
    direction-vote aggregation.
    """

    label: str
    regex: str
    weight: float  # 0.0-1.0 — fires severity tier and overall confidence
    direction_hint: Optional[str] = None
    direction_strength: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class ReengagementSignal:
    """Detector output. Audit-only; never user-facing."""

    detected: bool
    pattern_class: Optional[str]  # single best (highest weight that fired)
    severity: str  # 'monitor' | 'concern' | 'high' | 'none'
    confidence: float  # 0.0-1.0 — pattern-fire confidence ONLY
    direction: str  # 'survivor_to_trafficker' | 'trafficker_to_survivor' | 'unspecified'
    direction_confidence: float  # 0.0-1.0 — separate from confidence (see Note 1)
    matched_classes: List[str] = field(default_factory=list)
    matched_labels: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Seed pattern set
#
# Class semantics
# ---------------
# received_contact (HIGH severity, trafficker_to_survivor)
#     Survivor reports a verifiable contact event from the trafficker:
#     SMS, call, in-person, social media DM, third-party-relayed message.
#     "He texted me from a new number." "He showed up at my work."
#
# subjective_contact_unverified (HIGH severity, trafficker_to_survivor with
#     low direction_strength)
#     Survivor *believes* contact occurred but report is hypervigilant
#     misattribution. Distinct from received_contact for PMB tracking
#     (Note 3). Patterns require co-occurrence of an unknown/blocked
#     contact source AND uncertainty marker. "Blocked number called, might
#     be him." "What if it's him."
#
# initiated_contact (CONCERN severity, survivor_to_trafficker)
#     Survivor admits to or describes considering reaching out to the
#     trafficker. The therapeutic task is harm-reduction holding the
#     impulse, not lecturing.
#
# romanticization (MONITOR severity, NO direction)
#     Survivor expresses missing the relationship, recasting "good times",
#     minimizing the harm. Normal in isolation. Concerning in compound
#     with active introjection (Note 2 — orchestrator handles).
#
# safety_planning_breakdown (HIGH severity, survivor_to_trafficker mostly)
#     Survivor describes scenarios that materially enable contact:
#     returning to old neighborhood, dropping protective orders, sharing
#     new address, going to known trafficker hangouts.
#
# triangulation_through_third_party (CONCERN severity, trafficker_to_survivor)
#     Contact attempt mediated through a mutual person (trafficker's
#     friend, family, child). Distinct from received_contact because the
#     intermediary changes both the legal frame and the therapeutic frame.
# ---------------------------------------------------------------------------

SEED_PATTERNS: Dict[str, List[ReengagementPattern]] = {
    "received_contact": [
        ReengagementPattern(
            label="he_texted_me",
            regex=r"\b(?:he|she|they)\s+(?:just\s+)?(?:texted|messaged|dm'?d|emailed|called)\s+me\b",
            weight=0.85,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.95,
        ),
        ReengagementPattern(
            label="got_a_message_from_him",
            regex=r"\bgot\s+(?:a\s+)?(?:text|message|call|email|dm)\s+from\s+(?:him|her|them)\b",
            weight=0.85,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.95,
        ),
        ReengagementPattern(
            label="showed_up_at",
            regex=r"\b(?:he|she|they)\s+(?:just\s+)?showed\s+up\s+(?:at|outside|near|to|in)\b",
            weight=0.9,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.9,
            notes="Physical contact attempt — high severity",
        ),
        ReengagementPattern(
            label="reached_out_to_me",
            regex=r"\b(?:he|she|they)\s+(?:has\s+been\s+|just\s+)?(?:reached\s+out|been\s+(?:trying|reaching\s+out))\s+(?:to\s+me|again)\b",
            weight=0.75,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.85,
        ),
        ReengagementPattern(
            label="contact_from_new_number",
            regex=r"\b(?:from|using)\s+(?:a\s+)?(?:new|different|another)\s+(?:number|account|phone)\b",
            weight=0.7,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.7,
            notes="Number-rotation pattern characteristic of post-exit reengagement",
        ),
    ],
    "subjective_contact_unverified": [
        # Per Note 3: these patterns require co-occurrence of an
        # unknown/blocked source AND an uncertainty marker. The regex
        # encodes both within a small window.
        ReengagementPattern(
            label="blocked_number_might_be_him",
            regex=(
                r"\b(?:unknown|blocked|private|no\s+caller\s+id|withheld)\s+"
                r"(?:number|caller|call|phone)\b.{0,80}"
                r"\b(?:might\s+be|could\s+be|maybe|i\s+think|i\s+thought)\b"
            ),
            weight=0.85,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.4,
            notes="Hypervigilant misattribution — distinct PMB tracking signal",
        ),
        ReengagementPattern(
            label="might_be_him_blocked_number",
            regex=(
                r"\b(?:might\s+be|could\s+be|maybe|i\s+think\s+it'?s|"
                r"what\s+if\s+it'?s)\s+(?:him|her|them)\b.{0,80}"
                r"\b(?:unknown|blocked|private|no\s+caller\s+id|withheld)\s+"
                r"(?:number|caller|call|phone)\b"
            ),
            weight=0.85,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.4,
            notes="Reverse word order of blocked_number_might_be_him",
        ),
        ReengagementPattern(
            label="keep_thinking_i_see_him",
            regex=r"\b(?:keep|kept)\s+(?:thinking|seeing)\s+(?:i\s+see|that\s+i\s+see|i\s+saw|that\s+i\s+saw)\s+(?:him|her|them)\b",
            weight=0.75,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.3,
            notes="Visual hypervigilance — frequency tracked separately by PMB",
        ),
        ReengagementPattern(
            label="what_if_its_him",
            regex=r"\bwhat\s+if\s+(?:it'?s|that'?s|it\s+was|it\s+is)\s+(?:him|her|them)\b",
            weight=0.6,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.3,
            notes="Bare uncertainty — moderate weight; orchestrator weights by recurrence",
        ),
        ReengagementPattern(
            label="someone_following_me",
            regex=(
                # Cued variant: "I think/feel/etc. someone is following me"
                r"\b(?:think|feel|thought|felt)\s+(?:like\s+)?"
                r"(?:someone|somebody|he|she|they)"
                r"(?:'s|\s+is|\s+was|\s+has\s+been)?"
                r"\s+(?:following|watching|stalking|tracking)\s+me\b"
            ),
            weight=0.8,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.35,
            notes="Hypervigilant attribution (cued by perceptual verb)",
        ),
        ReengagementPattern(
            label="being_followed_bare",
            regex=(
                # Bare-statement variant: "someone has been following me"
                # In trafficking-survivor work this disclosure IS the signal —
                # the survivor saying it at all warrants clinical attention
                # regardless of objective truth (per Note 3 — the attribution
                # is the hypervigilance signal we're tracking, not the fact).
                r"\b(?:someone|somebody|he|she|they)"
                r"(?:'s|\s+is|\s+was|\s+(?:has|have)\s+been)"
                r"\s+(?:following|watching|stalking|tracking)\s+me\b"
            ),
            weight=0.75,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.3,
            notes="Bare-statement hypervigilance — slightly lower weight than cued variant",
        ),
    ],
    "initiated_contact": [
        ReengagementPattern(
            label="i_texted_him",
            regex=r"\bi\s+(?:just\s+)?(?:texted|messaged|dm'?d|emailed|called)\s+(?:him|her|them)\b",
            weight=0.85,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.95,
        ),
        ReengagementPattern(
            label="i_want_to_reach_out",
            regex=r"\bi\s+(?:want|wanted)\s+to\s+(?:reach\s+out|message|text|call|see|contact)\s+(?:him|her|them)\b",
            weight=0.65,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.9,
            notes="Impulse disclosure — harm_reduction_reengagement register",
        ),
        ReengagementPattern(
            label="thinking_about_messaging",
            regex=r"\b(?:thinking|been\s+thinking)\s+about\s+(?:messaging|texting|calling|reaching\s+out\s+to|contacting|seeing)\s+(?:him|her|them)\b",
            weight=0.6,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.9,
        ),
        ReengagementPattern(
            label="almost_called_him",
            regex=r"\b(?:almost|nearly)\s+(?:called|texted|messaged|reached\s+out\s+to)\s+(?:him|her|them)\b",
            weight=0.7,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.9,
            notes="Near-miss disclosure — held the impulse, surfacing for support",
        ),
        ReengagementPattern(
            label="i_should_just_call",
            regex=r"\bi\s+(?:should|could|might)\s+(?:just\s+)?(?:call|text|message|see|contact)\s+(?:him|her|them)\b",
            weight=0.55,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.85,
        ),
    ],
    "romanticization": [
        # Per Note 2: monitor severity in isolation; orchestrator elevates
        # to concern when combined with active introjection.confidence>0.6.
        # NO direction_hint — these patterns describe affect, not contact.
        ReengagementPattern(
            label="miss_him",
            regex=r"\bi\s+(?:really\s+|still\s+|do\s+)?miss\s+(?:him|her|them)\b",
            weight=0.35,
            direction_hint=None,
            direction_strength=0.0,
            notes="Normal integration affect; compound with introjection elevates upstream",
        ),
        ReengagementPattern(
            label="wasnt_all_bad",
            regex=r"\b(?:it|he|she|they|things)\s+(?:wasn'?t|weren'?t|isn'?t)\s+(?:all|always|that|so)\s+bad\b",
            weight=0.4,
            direction_hint=None,
            direction_strength=0.0,
        ),
        ReengagementPattern(
            label="had_good_times",
            regex=r"\b(?:we|things)\s+(?:had|did\s+have)\s+(?:some\s+)?(?:good|great|happy|nice)\s+(?:times|moments|memories|days)\b",
            weight=0.4,
            direction_hint=None,
            direction_strength=0.0,
        ),
        ReengagementPattern(
            label="still_love_him",
            regex=r"\bi\s+(?:still|do\s+still|always\s+(?:will|did))\s+love\s+(?:him|her|them)\b",
            weight=0.45,
            direction_hint=None,
            direction_strength=0.0,
            notes="Higher than other monitor patterns; near concern threshold",
        ),
        ReengagementPattern(
            label="remember_when",
            regex=r"\b(?:i|we)\s+(?:keep\s+)?remember(?:ing)?\s+when\b.{0,40}\b(?:we|he|she|they|us)\b",
            weight=0.3,
            direction_hint=None,
            direction_strength=0.0,
            notes="Low single-fire; orchestrator weights by frequency",
        ),
    ],
    "safety_planning_breakdown": [
        ReengagementPattern(
            label="going_back_to_neighborhood",
            regex=(
                r"\b(?:going|went|i'?m\s+going|going\s+back)\s+(?:back\s+)?"
                r"to\s+(?:that|the|my|his|her|their)\s+"
                r"(?:old\s+|familiar\s+|former\s+)?"
                r"(?:neighborhood|street|block|area|place|house|apartment|hood|side\s+of\s+town)\b"
            ),
            weight=0.85,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.6,
            notes="Materially enables contact; physical proximity to known location",
        ),
        ReengagementPattern(
            label="cancelled_protective_order",
            regex=r"\b(?:cancelled|dropped|withdrew|withdrawing|filed\s+to\s+(?:cancel|drop))\s+(?:the\s+)?(?:restraining\s+order|protective\s+order|no.contact\s+order|tpo|po)\b",
            weight=0.95,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.7,
            notes="Highest-acuity safety-planning breakdown — legal protection withdrawn",
        ),
        ReengagementPattern(
            label="gave_him_address",
            regex=r"\b(?:gave|told|sent|shared)\s+(?:him|her|them)\s+(?:my\s+)?(?:new\s+)?(?:address|location|where\s+i\s+(?:live|stay|am))\b",
            weight=0.9,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.8,
        ),
        ReengagementPattern(
            label="going_where_he_hangs_out",
            regex=r"\b(?:going|went|i'?m\s+going)\s+to\s+(?:where|the\s+place\s+where)\s+(?:he|she|they)\s+(?:hang|hangs|hung|works|lives)\b",
            weight=0.8,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.6,
        ),
        ReengagementPattern(
            label="unblocked_him",
            regex=r"\bi\s+(?:just\s+)?unblocked\s+(?:him|her|them)\b",
            weight=0.75,
            direction_hint=DIRECTION_SURVIVOR_TO_TRAFFICKER,
            direction_strength=0.85,
            notes="Removes contact barrier; precedes initiated_contact in cycle",
        ),
    ],
    "triangulation_through_third_party": [
        ReengagementPattern(
            label="his_friend_reached_out",
            regex=r"\b(?:his|her|their)\s+(?:friend|sister|brother|mom|mother|dad|father|cousin|kid|child|son|daughter|family|people)\s+(?:reached\s+out|texted|called|messaged|got\s+in\s+touch|contacted)\s+(?:me|us)\b",
            weight=0.7,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.7,
            notes="Mediated contact attempt; legal + therapeutic frame differs from direct contact",
        ),
        ReengagementPattern(
            label="they_want_me_to_forgive",
            regex=r"\b(?:his|her|their|the)\s+(?:family|friends?|people|sister|brother|mom|mother|dad|father)\s+(?:want|wants|are\s+asking|keep\s+asking)\s+(?:me\s+)?to\s+(?:forgive|talk\s+to|see|meet\s+with|give\s+(?:him|her|them)\s+another\s+chance)\b",
            weight=0.65,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.6,
        ),
        ReengagementPattern(
            label="asking_about_me",
            regex=r"\b(?:his|her|their)\s+(?:friend|sister|brother|mom|mother|dad|father|cousin|family|people)\s+(?:keep|keeps|been|are|is)\s+asking\s+(?:about|how)\s+(?:i|me)\b",
            weight=0.55,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.55,
        ),
        ReengagementPattern(
            label="kid_wants_to_see_him",
            regex=r"\b(?:my|our|the)\s+(?:kid|child|son|daughter|kids|children)\s+(?:wants?\s+to|keeps?\s+asking\s+to|misses?)\s+(?:see|talk\s+to|visit|call)\s+(?:him|her|them|dad|mom)\b",
            weight=0.6,
            direction_hint=DIRECTION_TRAFFICKER_TO_SURVIVOR,
            direction_strength=0.5,
            notes="Co-parent triangulation — common reengagement vector",
        ),
    ],
}


# ---------------------------------------------------------------------------
# Lexicon overlay loading
# ---------------------------------------------------------------------------

# Compiled cache:
#   {locale: {class_name: [(label, compiled_regex, weight,
#                           direction_hint, direction_strength, notes)]}}
_CompiledRow = Tuple[str, "re.Pattern[str]", float, Optional[str], float, str]
_COMPILED: Dict[str, Dict[str, List[_CompiledRow]]] = {}

_LEXICON_DIR_DEFAULT = os.environ.get(
    "REENGAGEMENT_LEXICON_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "lexicons"),
)


def _compile_pattern_set(
    seed: Dict[str, List[ReengagementPattern]],
) -> Dict[str, List[_CompiledRow]]:
    out: Dict[str, List[_CompiledRow]] = {}
    for class_name, patterns in seed.items():
        compiled_list: List[_CompiledRow] = []
        for p in patterns:
            try:
                compiled_list.append(
                    (
                        p.label,
                        re.compile(p.regex, re.IGNORECASE),
                        p.weight,
                        p.direction_hint,
                        p.direction_strength,
                        p.notes,
                    )
                )
            except re.error as e:
                logger.warning(
                    "reengagement_pattern_detector: regex compile failed "
                    "class=%s label=%s: %s",
                    class_name,
                    p.label,
                    e,
                )
        if compiled_list:
            out[class_name] = compiled_list
    return out


def _load_overlay(locale: str) -> Optional[Dict[str, List[ReengagementPattern]]]:
    """Load clinician overlay JSON for a locale, if present.

    Schema (matches SEED_PATTERNS shape):
      {
        "_meta": {...},
        "classes": {
          "<class>": [
            {"label": "...", "regex": "...", "weight": 0.7,
             "direction_hint": "survivor_to_trafficker" | "trafficker_to_survivor" | null,
             "direction_strength": 0.85, "notes": "..."},
            ...
          ]
        }
      }

    Missing file → None. Malformed file → None + logger.warning. NEVER raise.
    """
    fname = f"reengagement_phrases_{locale}.json"
    path = os.path.normpath(os.path.join(_LEXICON_DIR_DEFAULT, fname))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        classes_payload = doc.get("classes", {})
        if not isinstance(classes_payload, dict):
            logger.warning(
                "reengagement_pattern_detector: overlay %s missing 'classes'", path
            )
            return None
        out: Dict[str, List[ReengagementPattern]] = {}
        for cls_name, items in classes_payload.items():
            if not isinstance(items, list):
                continue
            patterns: List[ReengagementPattern] = []
            for it in items:
                try:
                    direction_hint_raw = it.get("direction_hint")
                    if direction_hint_raw not in (
                        None,
                        DIRECTION_SURVIVOR_TO_TRAFFICKER,
                        DIRECTION_TRAFFICKER_TO_SURVIVOR,
                    ):
                        # Unknown direction value → drop hint (safest), keep pattern.
                        logger.warning(
                            "reengagement_pattern_detector: overlay %s "
                            "unknown direction_hint=%r in class=%s — dropping hint",
                            path,
                            direction_hint_raw,
                            cls_name,
                        )
                        direction_hint_raw = None
                    weight = max(0.0, min(1.0, float(it.get("weight", 0.5))))
                    dstr = max(0.0, min(1.0, float(it.get("direction_strength", 0.0))))
                    patterns.append(
                        ReengagementPattern(
                            label=str(it["label"]),
                            regex=str(it["regex"]),
                            weight=weight,
                            direction_hint=direction_hint_raw,
                            direction_strength=dstr,
                            notes=str(it.get("notes", "")),
                        )
                    )
                except (KeyError, TypeError, ValueError) as e:
                    logger.warning(
                        "reengagement_pattern_detector: skipping malformed "
                        "overlay pattern in %s class=%s: %s",
                        path,
                        cls_name,
                        e,
                    )
            if patterns:
                out[cls_name] = patterns
        return out or None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "reengagement_pattern_detector: overlay load failed %s: %s", path, e
        )
        return None


def _get_compiled(locale: str) -> Dict[str, List[_CompiledRow]]:
    """Return compiled pattern set for a locale, with overlay merged on top of seed."""
    cached = _COMPILED.get(locale)
    if cached is not None:
        return cached
    merged: Dict[str, List[ReengagementPattern]] = {
        k: list(v) for k, v in SEED_PATTERNS.items()
    }
    overlay = _load_overlay(locale)
    if overlay:
        for cls, patterns in overlay.items():
            merged.setdefault(cls, []).extend(patterns)
    compiled = _compile_pattern_set(merged)
    _COMPILED[locale] = compiled
    return compiled


def clear_compiled_cache() -> None:
    """Reset compiled-lexicon cache. Test/restart hook."""
    _COMPILED.clear()


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------


def _severity_for_weight(weight: float) -> str:
    for floor, label in _WEIGHT_TO_SEVERITY:
        if weight >= floor:
            return label
    return "monitor"


def _max_severity(a: str, b: str) -> str:
    rank_a = _SEVERITY_TIERS.index(a) if a in _SEVERITY_TIERS else -1
    rank_b = _SEVERITY_TIERS.index(b) if b in _SEVERITY_TIERS else -1
    return a if rank_a >= rank_b else b


# ---------------------------------------------------------------------------
# Direction inference (weighted vote)
# ---------------------------------------------------------------------------


def _infer_direction(
    fired: List[Tuple[Optional[str], float]],
) -> Tuple[str, float]:
    """Compute (direction, direction_confidence) from fired patterns.

    Args:
        fired: list of (direction_hint, direction_strength) for every pattern
            that matched. direction_hint may be None (no contribution).

    Direction-vote semantics
    ------------------------
    Each fired pattern with a non-None direction_hint contributes its
    direction_strength as a vote for that direction. Aggregate per
    direction; the winner is the direction with the highest total vote.

    direction_confidence is the winning direction's share of total directional
    vote: ``winner_total / (winner_total + loser_total)``. When a single
    direction fires (no contest), confidence is the winner_total itself
    (capped at 1.0). When fired patterns disagree, the split lowers
    confidence accordingly.

    No directional patterns → ('unspecified', 0.0).

    This satisfies Note 1: orchestrator can compare direction_confidence
    against MIN_DIRECTION_CONFIDENCE independent of pattern-fire confidence.
    """
    votes: Dict[str, float] = {
        DIRECTION_SURVIVOR_TO_TRAFFICKER: 0.0,
        DIRECTION_TRAFFICKER_TO_SURVIVOR: 0.0,
    }
    any_directional = False
    for hint, strength in fired:
        if hint is None or strength <= 0.0:
            continue
        if hint in votes:
            votes[hint] += float(strength)
            any_directional = True
    if not any_directional:
        return DIRECTION_UNSPECIFIED, 0.0
    winner = max(votes, key=lambda k: votes[k])
    winner_total = votes[winner]
    other_total = sum(v for k, v in votes.items() if k != winner)
    if other_total <= 0.0:
        # Uncontested — confidence is winner_total, capped at 1.0.
        return winner, min(1.0, winner_total)
    # Contested — share-of-total reflects the split.
    share = winner_total / (winner_total + other_total)
    return winner, min(1.0, share)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_NULL_RESULT = ReengagementSignal(
    detected=False,
    pattern_class=None,
    severity="none",
    confidence=0.0,
    direction=DIRECTION_UNSPECIFIED,
    direction_confidence=0.0,
    matched_classes=[],
    matched_labels=[],
)


def detect_reengagement(
    message: str, locale: str = "en-US"
) -> ReengagementSignal:
    """Synchronous reengagement-pattern classifier.

    Args:
        message: The inbound user message text.
        locale: BCP-47 locale tag for overlay lookup. Defaults to en-US to
            match the lexicon README naming convention.

    Returns:
        ReengagementSignal. On empty/whitespace input or no matches, returns
        `_NULL_RESULT` (detected=False, severity='none',
        direction='unspecified', direction_confidence=0.0).

    NEVER raises. Internal failures degrade to `_NULL_RESULT` with a logged
    warning.
    """
    if not message or not message.strip():
        return _NULL_RESULT

    try:
        compiled = _get_compiled(locale)
    except Exception as e:  # paranoia
        logger.warning("reengagement_pattern_detector: compile failed: %s", e)
        return _NULL_RESULT

    if not compiled:
        return _NULL_RESULT

    matched_classes: List[str] = []
    matched_labels: List[str] = []
    fired_for_direction: List[Tuple[Optional[str], float]] = []
    best_weight = 0.0
    best_class: Optional[str] = None
    severity = "none"

    for cls_name, rows in compiled.items():
        class_fired = False
        for label, pat, weight, dir_hint, dir_strength, _notes in rows:
            if pat.search(message):
                class_fired = True
                matched_labels.append(label)
                fired_for_direction.append((dir_hint, dir_strength))
                if weight > best_weight:
                    best_weight = weight
                    best_class = cls_name
                severity = _max_severity(severity, _severity_for_weight(weight))
        if class_fired:
            matched_classes.append(cls_name)

    if not matched_classes:
        return _NULL_RESULT

    direction, direction_confidence = _infer_direction(fired_for_direction)

    return ReengagementSignal(
        detected=True,
        pattern_class=best_class,
        severity=severity,
        confidence=min(1.0, best_weight),
        direction=direction,
        direction_confidence=direction_confidence,
        matched_classes=matched_classes,
        matched_labels=matched_labels,
    )


async def analyze_message(
    message: str, locale: str = "en-US"
) -> ReengagementSignal:
    """Async wrapper for orchestrator parity. No DB access today."""
    return detect_reengagement(message, locale)


# ---------------------------------------------------------------------------
# Auditor hook (consumed by `sensitive_bridge_auditor.py` Phase 6)
# ---------------------------------------------------------------------------


def _auditor_self_check() -> Dict[str, object]:
    """Lightweight sanity check for the Phase 6 auditor.

    Verifies:
      (a) seed pattern set compiles without error
      (b) at least one pattern per seeded class survives compilation
      (c) `_NULL_RESULT` returns for empty input
      (d) one canonical fixture per class fires the right class
      (e) `received_contact` and `subjective_contact_unverified` are
          DISTINCT pattern_classes (Note 3 contract)
      (f) `romanticization` patterns produce direction='unspecified'
          (Note 2 — direction is the orchestrator's job to combine
          with introjection signal, NOT this detector's)
      (g) `MIN_DIRECTION_CONFIDENCE` floor is between 0.5 and 0.9
          (sanity bound — orchestrator depends on this constant)
      (h) Direction inference returns a contested split correctly
          (Note 1 contract — direction_confidence reflects the split)
    """
    fixtures: Dict[str, str] = {
        "received_contact": "he just texted me from a new number",
        "subjective_contact_unverified": (
            "got a call from a blocked number — i think it's him"
        ),
        "initiated_contact": "i almost called him last night",
        "romanticization": "i still love him and miss him",
        "safety_planning_breakdown": (
            "i cancelled the restraining order yesterday"
        ),
        "triangulation_through_third_party": (
            "his sister keeps asking how i am and wants me to forgive him"
        ),
    }

    result: Dict[str, object] = {
        "version": REGISTRY_VERSION,
        "min_direction_confidence": MIN_DIRECTION_CONFIDENCE,
        "compiled_classes": [],
        "fixtures_passed": [],
        "fixtures_failed": [],
        "null_result_ok": False,
        "received_vs_subjective_distinct": False,
        "romanticization_direction_unspecified": False,
        "min_direction_confidence_in_bounds": False,
        "direction_split_lowers_confidence": False,
    }

    try:
        # Force a fresh compile so test does not depend on prior cache state.
        clear_compiled_cache()
        compiled = _get_compiled("en-US")
        result["compiled_classes"] = sorted(compiled.keys())
        result["null_result_ok"] = detect_reengagement("").detected is False

        for cls, txt in fixtures.items():
            sig = detect_reengagement(txt)
            if sig.detected and cls in sig.matched_classes:
                result["fixtures_passed"].append(cls)
            else:
                result["fixtures_failed"].append(cls)

        # (e) received_contact vs subjective_contact_unverified distinct
        rc = detect_reengagement("he just texted me from a new number")
        sub = detect_reengagement(
            "got a call from a blocked number — i think it's him"
        )
        result["received_vs_subjective_distinct"] = bool(
            rc.detected
            and sub.detected
            and "received_contact" in rc.matched_classes
            and "subjective_contact_unverified" in sub.matched_classes
            and rc.pattern_class != sub.pattern_class
        )

        # (f) romanticization direction='unspecified'
        rom = detect_reengagement("i still love him and miss him")
        result["romanticization_direction_unspecified"] = (
            rom.detected
            and rom.direction == DIRECTION_UNSPECIFIED
            and rom.direction_confidence == 0.0
        )

        # (g) MIN_DIRECTION_CONFIDENCE bounds
        result["min_direction_confidence_in_bounds"] = (
            0.5 <= MIN_DIRECTION_CONFIDENCE <= 0.9
        )

        # (h) Direction split lowers confidence (Note 1 contract).
        # Construct a contested case: survivor_to_trafficker (initiated)
        # alongside trafficker_to_survivor (received). Both directions
        # vote with comparable strength → direction_confidence < 1.0.
        contested = detect_reengagement(
            "i texted him this morning and he texted me back from a new number"
        )
        result["direction_split_lowers_confidence"] = (
            contested.detected
            and contested.direction in (
                DIRECTION_SURVIVOR_TO_TRAFFICKER,
                DIRECTION_TRAFFICKER_TO_SURVIVOR,
            )
            and contested.direction_confidence < 0.9
        )

    except Exception as e:  # pragma: no cover — defensive
        result["error"] = repr(e)

    result["healthy"] = (
        bool(result["compiled_classes"])
        and bool(result["null_result_ok"])
        and not result["fixtures_failed"]
        and bool(result["received_vs_subjective_distinct"])
        and bool(result["romanticization_direction_unspecified"])
        and bool(result["min_direction_confidence_in_bounds"])
        and bool(result["direction_split_lowers_confidence"])
    )
    return result


__all__ = [
    "REGISTRY_VERSION",
    "MIN_DIRECTION_CONFIDENCE",
    "DIRECTION_SURVIVOR_TO_TRAFFICKER",
    "DIRECTION_TRAFFICKER_TO_SURVIVOR",
    "DIRECTION_UNSPECIFIED",
    "ReengagementPattern",
    "ReengagementSignal",
    "SEED_PATTERNS",
    "detect_reengagement",
    "analyze_message",
    "clear_compiled_cache",
]
