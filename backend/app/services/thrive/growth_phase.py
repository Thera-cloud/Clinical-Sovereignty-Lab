"""Growth-phase taxonomy + cross-framework mapping — QUANTUM-CRYSTAL-ARCH.

One canonical phase per client. The phase tells Little Nate *which mind* to
bring to the conversation: the trauma-informed therapist's (past → present,
"what happened to you, how are you feeling") or the positive-psychology
coach's (present → future, "what do you want to build now, what can you
complete today"). The phase is reversible: a thriving client can ask to work
something through and LN shifts back for that arc, then forward again when
the healing cycle re-confirms.

Frameworks mapped onto the same five phases:
  EFT (Johnson) Stage 1 Steps 1-4 / Stage 2 Steps 5-7 / Stage 3 Steps 8-9
  EFIT (individual EFT)            same arc, self-with-self
  NICC                             Safe -> Attune -> Reflect -> Repair ->
                                   Reconsolidate -> Thrive -> Drive -> Express
  Gottman Sound Relationship House lower floors (love maps, fondness, turning
                                   toward, positive perspective, manage conflict)
                                   -> upper floors (make life dreams come true,
                                   create shared meaning)
  Attachment theory                insecure activation -> corrective
                                   experiences -> earned-secure
  EMDR / memory reconsolidation    preparation -> reprocessing (desensitize,
                                   install, body scan) -> closure/re-evaluation
                                   -> future template  (the future template IS
                                   the hand-off into coaching)
  Post-traumatic growth (Tedeschi & Calhoun) five domains live in thrive+
  Antifragile (Taleb)              hormesis / via negativa / optionality /
                                   barbell live in thrive+
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Phase taxonomy
# --------------------------------------------------------------------------

STABILIZE = "stabilize"
PROCESS = "process"
CONSOLIDATE = "consolidate"
THRIVE = "thrive"
GENERATIVE = "generative"

PHASES: Tuple[str, ...] = (STABILIZE, PROCESS, CONSOLIDATE, THRIVE, GENERATIVE)
PHASE_INDEX: Dict[str, int] = {p: i for i, p in enumerate(PHASES)}

# Sub-states (orthogonal to phase)
SUB_NONE = None
SUB_WORKING_THROUGH = "working_through"   # client asked to go back into something
SUB_CRISIS_HOLD = "crisis_hold"           # safety signal; phase frozen, LN stabilizes

COACHING_PHASES = frozenset({THRIVE, GENERATIVE})
THERAPY_PHASES = frozenset({STABILIZE, PROCESS})
BRIDGE_PHASES = frozenset({CONSOLIDATE})

DEFAULT_PHASE = PROCESS  # every existing client starts here until evidence says otherwise


def is_coaching_phase(phase: Optional[str], sub_state: Optional[str] = None) -> bool:
    """True when LN should lead with the coaching mind."""
    if sub_state in (SUB_WORKING_THROUGH, SUB_CRISIS_HOLD):
        return False
    return (phase or DEFAULT_PHASE) in COACHING_PHASES


def is_consolidating(phase: Optional[str], sub_state: Optional[str] = None) -> bool:
    if sub_state in (SUB_WORKING_THROUGH, SUB_CRISIS_HOLD):
        return False
    return (phase or DEFAULT_PHASE) == CONSOLIDATE


def effective_phase(phase: Optional[str], sub_state: Optional[str]) -> str:
    """Phase LN should actually operate in this turn."""
    p = phase if phase in PHASE_INDEX else DEFAULT_PHASE
    if sub_state == SUB_CRISIS_HOLD:
        return STABILIZE
    if sub_state == SUB_WORKING_THROUGH:
        # Working through from thrive is a *bounded* return to process — not a
        # demotion. The persisted phase is unchanged.
        return PROCESS if p in COACHING_PHASES or p == CONSOLIDATE else p
    return p


# --------------------------------------------------------------------------
# Framework mapping
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameworkMap:
    phase: str
    label: str
    eft: str
    efit: str
    nicc: str
    gottman: str
    attachment: str
    emdr: str
    ptg: str
    antifragile: str
    time_focus: str
    core_questions: Tuple[str, ...]
    ln_register: str
    coach_focus: str


FRAMEWORKS: Dict[str, FrameworkMap] = {
    STABILIZE: FrameworkMap(
        phase=STABILIZE,
        label="Stabilize",
        eft="Stage 1, Steps 1-2 — alliance, identify the negative cycle",
        efit="Alliance + safety; name the self-protective cycle",
        nicc="Safe -> Attune",
        gottman="Manage flooding; repair attempts; soften start-up",
        attachment="Co-regulation; secure base is LN + coach",
        emdr="Preparation — resourcing, calm place, container",
        ptg="n/a — safety first",
        antifragile="n/a — remove acute fragility only (via negativa: what to stop)",
        time_focus="present (regulation)",
        core_questions=(
            "What do you need right now to feel steadier?",
            "What is happening in your body as you say that?",
        ),
        ln_register="witness, anchor, slow",
        coach_focus="safety plan, regulation skills, session frequency",
    ),
    PROCESS: FrameworkMap(
        phase=PROCESS,
        label="Process",
        eft="Stage 1 Steps 3-4 (underlying emotions, reframe) -> Stage 2 Steps 5-7 (owning needs, acceptance, restructuring)",
        efit="Access primary emotion; encounter the wounded self; new response",
        nicc="Reflect -> Repair",
        gottman="Dreams-within-conflict dialogue; perpetual problems to dialogue",
        attachment="Corrective emotional experiences; protest -> reach",
        emdr="Reprocessing — desensitization, installation of adaptive belief",
        ptg="seismic event acknowledged; rumination shifts from intrusive to deliberate",
        antifragile="n/a — hormesis only in small, chosen doses",
        time_focus="past -> present",
        core_questions=(
            "What happened, and what did it mean about you?",
            "What are you feeling as you touch that?",
            "What did the younger you need that didn't come?",
        ),
        ln_register="companion into the wound, steady, unhurried",
        coach_focus="cycle map, reconsolidation targets, parts/exiles, EFT steps",
    ),
    CONSOLIDATE: FrameworkMap(
        phase=CONSOLIDATE,
        label="Consolidate",
        eft="Stage 3, Steps 8-9 — new solutions to old problems; consolidate new positions",
        efit="Integrate the new self-story; rehearse new responses",
        nicc="Reconsolidate -> Thrive (entry)",
        gottman="Positive perspective restored; friendship system repaired",
        attachment="Earned-secure emerging; self-soothing + reaching both available",
        emdr="Body scan, closure, re-evaluation, FUTURE TEMPLATE",
        ptg="growth noticed: 'I am stronger than I knew'",
        antifragile="Phoenix -> Hydra test: does a small stressor now leave you better?",
        time_focus="present (integration)",
        core_questions=(
            "What is different in how you meet this now?",
            "What did you learn about yourself that you want to keep?",
            "Where in your life do you want to practice the new response first?",
        ),
        ln_register="mirror the change, name the growth, invite the future",
        coach_focus="consolidation evidence, relapse-prevention plan, hand-off to goals",
    ),
    THRIVE: FrameworkMap(
        phase=THRIVE,
        label="Thrive",
        eft="Post-Stage 3 — relationship as secure base for exploration",
        efit="Secure self as base for exploration",
        nicc="Thrive -> Drive",
        gottman="Make life dreams come true; rituals of connection",
        attachment="Earned-secure; exploration system online",
        emdr="Future template lived out; new memories laid down",
        ptg="five domains actively built: new possibilities, relationships, personal strength, appreciation of life, spiritual/existential",
        antifragile="hormesis by design (chosen stretch), optionality (small bets, capped downside), barbell (very safe + very bold), via negativa (subtract what fragilizes)",
        time_focus="present -> future",
        core_questions=(
            "What do you want to build now?",
            "Which goal is live this week, and what can you complete today?",
            "What went well, and what did you do to make it happen?",
            "Which of your strengths did you use — and where could you use it in a new way?",
        ),
        ln_register="collaborator, champion, curious about the future, still unconditionally warm",
        coach_focus="goal ledger, focus-area cadence, PERMA trajectory, strengths, celebration",
    ),
    GENERATIVE: FrameworkMap(
        phase=GENERATIVE,
        label="Generative",
        eft="Secure attachment extended outward — mentoring, parenting, community",
        efit="Self-as-secure-base for others",
        nicc="Express",
        gottman="Create shared meaning — legacy, roles, rituals, symbols",
        attachment="Secure base for others",
        emdr="n/a",
        ptg="spiritual/existential growth + new life narrative shared with others",
        antifragile="skin in the game — build things that outlast you; Lindy",
        time_focus="future -> legacy",
        core_questions=(
            "Who gets to benefit from what you've learned?",
            "What do you want to leave behind, and what's the first move?",
            "Where is your story now medicine for someone else?",
        ),
        ln_register="peer, witness to legacy, playful and bold",
        coach_focus="mentoring, giving-back goals, legacy projects, meaning",
    ),
}


def framework_for(phase: Optional[str]) -> FrameworkMap:
    return FRAMEWORKS.get(phase or DEFAULT_PHASE, FRAMEWORKS[DEFAULT_PHASE])


# --------------------------------------------------------------------------
# Transition policy (evidence-driven; LN auto-promotes, coach is notified)
# --------------------------------------------------------------------------


@dataclass
class TransitionPolicy:
    """Thresholds the resolver uses. Tunable via env in phase_resolver."""

    # Sustained-evidence window for promotion
    promote_window_days: int = 14
    # Healing-cycle composite score needed (0..1) to promote one step
    promote_score: float = 0.62
    # Consecutive evaluations above threshold required
    promote_streak: int = 3
    # Min days in a phase before another promotion (prevents double jumps)
    min_days_in_phase: int = 10
    # Composite below which we suggest (not force) shifting back a step
    demote_score: float = 0.28
    # working_through auto-expires after this many hours without depth signals
    working_through_ttl_hours: int = 72
    # crisis_hold auto-expires after this many hours without crisis signals
    crisis_hold_ttl_hours: int = 48
    # Coach notification on every promotion
    notify_coach_on_promote: bool = True


DEFAULT_POLICY = TransitionPolicy()


def next_phase(phase: str) -> Optional[str]:
    i = PHASE_INDEX.get(phase)
    if i is None or i + 1 >= len(PHASES):
        return None
    return PHASES[i + 1]


def prev_phase(phase: str) -> Optional[str]:
    i = PHASE_INDEX.get(phase)
    if i is None or i == 0:
        return None
    return PHASES[i - 1]


# --------------------------------------------------------------------------
# Explicit-intent lexicons (client asks to go back / declares forward)
# --------------------------------------------------------------------------

# Client explicitly asks to work something through → SUB_WORKING_THROUGH.
WORK_THROUGH_REQUEST = (
    r"\b(i (want|need) to (work|talk|go) (through|back into|back to|about) (something|this|that|it|my|the|what))",
    r"\bcan we (go back|work through|talk about what happened|process)\b",
    r"\bsomething (came up|surfaced|got triggered|hit me)\b",
    r"\bi('m| am) (struggling|triggered|spiraling|not okay|not ok)\b",
    r"\bit('s| is) (coming back|back again|resurfacing)\b",
    r"\bi (relapsed|slipped|used again|drank again)\b",
)

# Client explicitly declares forward motion → evidence for promotion.
FORWARD_DECLARATION = (
    r"\bi('m| am) (ready|done|finished) (to move|with|processing|talking about the past)\b",
    r"\bi (have|'ve) (healed|forgiven|let (it|that|him|her|them) go|made peace)\b",
    r"\bi want to (focus on|build|work on|create|start) (my|the|a|something) (future|goals?|life|business|next)\b",
    r"\b(thriving|flourishing|excited about|looking forward to|proud of)\b",
    r"\bwhat('s| is) next\b",
    r"\b(celebrat\w+|breakthrough|milestone|i did it|we did it)\b",
)

# Celebration / retrospective wound language — a *thriving* client naming an
# old wound in the past tense is not a request to process it.
RETROSPECTIVE_WOUND = (
    r"\b(healed|healing|forgave|forgiven|released|let go of|made peace with|"
    r"worked through|moved past|closed the chapter on|no longer|used to)\b",
)

# Negations that flip HYPO lexicon hits ("I rarely go numb anymore").
NEGATED_HYPO = (
    r"\b(rarely|no longer|don't|do not|never|not|haven't|stopped|used to)\b[^.!?]{0,40}"
    r"\b(numb|flat|empty|shut down|dissociat\w*|floating|not really here)\b",
    r"\b(numb|flat|empty|shut down|dissociat\w*)\b[^.!?]{0,30}\b(anymore|any more|no longer|less and less|rarely)\b",
)
