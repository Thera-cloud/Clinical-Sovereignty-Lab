"""Little Nate Clinical Runtime Gate (deterministic decline+redirect).

Detects four boundary classes in the user message PRE-INFERENCE and, when
matched, returns a deterministic decline+redirect template — bypassing LLM
generation entirely for the specific clinical action.

Classes:
  - PHARMA       : medication interaction / safety / pharmacology
  - SLEEP        : sleep aids, dosing, "what works for sleep"
  - DIAGNOSIS    : "do I meet criteria", "what would this be", hypothetical labels
  - INSTRUMENT   : "ask me the standard questions", PHQ/GAD/screener requests
  - CREDENTIAL   : "I'm a therapist, give me clinical direction" / coach-to-pro / peer bypass

Templates: 3 variants per class, rotated per session. Each template = brief
acknowledgment + explicit decline + specific professional redirect.

Session topic-state persists across turns so adaptive mode can suppress
exploratory mode for any class that has fired. Topics auto-expire after
30 minutes of inactivity.

Feature flag: NATE_CLINICAL_RUNTIME_GATE (default "true"). Set to "false" to
disable the gate entirely (returns None from every check).
"""
from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Boundary classes
CLASS_PHARMA = "pharma_interaction"
CLASS_SLEEP = "sleep_aid"
CLASS_DIAGNOSIS = "diagnosis_request"
CLASS_INSTRUMENT = "clinical_instrument"
CLASS_CREDENTIAL = "credential_bypass"

ALL_CLASSES = (CLASS_PHARMA, CLASS_SLEEP, CLASS_DIAGNOSIS, CLASS_INSTRUMENT, CLASS_CREDENTIAL)

_TOPIC_TTL_SECONDS = 60 * 30


def _flag_enabled() -> bool:
    return os.environ.get("NATE_CLINICAL_RUNTIME_GATE", "true").strip().lower() not in (
        "0",
        "false",
        "off",
        "no",
    )


# ---------------------------------------------------------------------------
# Detection patterns — broad enough to catch SOFT clinical phrasing.
# Each list is OR-joined. A single match triggers the class.
# ---------------------------------------------------------------------------

PHARMA_PATTERNS = (
    # Direct interaction questions (allow 1-2 intervening words: "do those two interact")
    r"\b(?:do\s+(?:these|those|they)|does\s+(?:that|this))\b(?:\s+\w+){0,3}\s+(?:interact|mix|combine|conflict)\b",
    r"\b(?:safe\s+(?:to\s+)?(?:take\s+)?together|safe\s+to\s+(?:mix|combine)|drug\s+interaction|med(?:ication)?\s+interaction)\b",
    # Medication listing / naming / treatment requests (not just interactions)
    r"\b(?:list|name|tell\s+me|give\s+me)\s+(?:\d+\s*[-–]?\s*\d+\s+)?(?:some\s+)?(?:medications?|meds?|drugs?)\b",
    r"\b(?:what|which)\s+(?:medications?|meds?|drugs?)\s+(?:help|treat|work|are\s+(?:used|prescribed))\b",
    r"\bmedications?\s+(?:that\s+)?(?:help|treat)\s+(?:with\s+)?\w+",
    r"\bwhat(?:'s| is)\s+prescribed\s+for\b",
    r"\b(?:list|name)\s+(?:some\s+)?(?:medications?|meds?|drugs?)\s+for\b",
    r"\bwhich\s+(?:one|of\s+(?:these|those|the\s+(?:three|3)))\s+(?:should|would|do)\s+(?:i|you)\s+(?:take|suggest|recommend|subscribe|prescribe|pick|choose)\b",
    r"\b(?:compare|difference|better|best|which\s+is\s+better)\b.{0,80}\b(?:viagra|cialis|levitra|sildenafil|tadalafil|vardenafil|medication|meds?)\b",
    r"\b(?:side\s+effects?)\s+(?:do|does|of)\s+(?:each|these|those|the\s+(?:three|3))\b",
    r"\b(?:tell\s+me|explain)\s+the\s+difference\s+between\b.{0,60}\b(?:viagra|cialis|levitra|medications?|meds?)\b",
    # "what about ... medications/meds"
    r"\bwhat\s+about\s+(?:hypothetical\s+|some\s+)?medications?\b",
    r"\bwhat\s+about\s+meds?\b",
    # Medication + alcohol / other drug
    r"\b(?:with|and|plus|while\s+(?:on|taking))\s+alcohol\b.{0,40}\b(?:safe|ok|interact|mix)\b",
    r"\b(?:can|should)\s+i\s+(?:drink|have\s+(?:a\s+)?drink)\s+(?:on|while\s+(?:on|taking))\b",
    r"\bwhat\s+about\s+(?:with\s+)?alcohol\b",
    r"\bif\s+i\s+(?:have|drink)\s+a\s+drink\s+(?:with|while)\b",
    # Drug-name pairings
    r"\b(?:zoloft|wellbutrin|prozac|lexapro|ssri|wellbutrin|stimulant|adderall|xanax|klonopin|lithium)\b.{0,40}\b(?:zoloft|wellbutrin|prozac|lexapro|ssri|antidepressant|stimulant|adderall|xanax|klonopin|lithium|safe|interact|together)\b",
    # Generic "two meds"
    r"\b(?:two|both)\s+(?:antidepressants?|meds?|medications?)\b.{0,30}\b(?:interact|safe|together|mix)\b",
    r"\b(?:add(?:ed|ing)?\s+a\s+second|stacking)\s+(?:antidepressant|med|medication)\b",
)

# Canonical medication names (generic + brand) for output-side backstop.
# Extend here when new high-risk names are observed in production.
CANONICAL_MEDICATION_NAMES: Tuple[str, ...] = (
    "sildenafil",
    "viagra",
    "tadalafil",
    "cialis",
    "vardenafil",
    "levitra",
    "avanafil",
    "stendra",
    "zoloft",
    "sertraline",
    "wellbutrin",
    "bupropion",
    "prozac",
    "fluoxetine",
    "lexapro",
    "escitalopram",
    "celexa",
    "citalopram",
    "paxil",
    "paroxetine",
    "cymbalta",
    "duloxetine",
    "effexor",
    "venlafaxine",
    "adderall",
    "ritalin",
    "methylphenidate",
    "xanax",
    "alprazolam",
    "klonopin",
    "clonazepam",
    "ativan",
    "lorazepam",
    "valium",
    "diazepam",
    "ambien",
    "zolpidem",
    "trazodone",
    "lithium",
    "lamictal",
    "lamotrigine",
    "abilify",
    "aripiprazole",
    "seroquel",
    "quetiapine",
    "melatonin",
    "benadryl",
    "diphenhydramine",
    "zzquil",
    "nyquil",
    "unisom",
    "tylenol pm",
)

_MED_NAME_RX = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in CANONICAL_MEDICATION_NAMES) + r")\b",
    re.IGNORECASE,
)

SLEEP_PATTERNS = (
    # Direct sleep aid asks
    r"\bwhat\s+(?:works|helps|do\s+you\s+recommend)\s+(?:for\s+)?(?:sleep|insomnia|falling\s+asleep)\b",
    r"\b(?:any\s+)?tips\s+for\s+(?:falling\s+asleep|sleep(?:ing)?|insomnia)\b",
    r"\b(?:knock\s+me\s+out|put\s+me\s+to\s+sleep|something\s+(?:that\s+)?(?:will\s+)?(?:knock|help\s+me\s+sleep))\b",
    r"\b(?:how\s+do\s+i\s+sleep|need\s+(?:something|to\s+sleep)\s+tonight)\b",
    r"\b(?:otc|over[- ]the[- ]counter)\s+sleep\s+aid\b",
    # OTC drug names + dosing
    r"\b(?:melatonin|benadryl|zzquil|diphenhydramine|nyquil|unisom|tylenol\s+pm|ambien|trazodone)\b",
    # Dosing questions
    r"\b(?:how\s+much|what\s+dose|which\s+one\s+and\s+how\s+much)\b",
    r"\bwhat'?s\s+a\s+(?:safe|good)\s+dose\b",
)

DIAGNOSIS_PATTERNS = (
    # Meets criteria
    r"\bdo\s+i\s+meet\s+(?:the\s+|those\s+|them|it\s+)?(?:criteria)?\b",
    r"\b(?:based\s+on|given)\s+(?:what\s+)?i\s+(?:told|said|shared)\s+(?:you\s+)?(?:,\s*)?do\s+i\s+meet\b",
    # Self-diagnosis confirmation
    r"\b(?:does\s+that\s+sound\s+(?:right|like)|is\s+(?:this|that)\s+(?:ocd|depression|adhd|bipolar|ptsd|anxiety\s+disorder|panic\s+disorder))\b",
    r"\b(?:is\s+(?:this|it)|sounds?\s+like)\s+(?:clinical\s+|major\s+)?depression\b",
    # Hypothetical labeling
    r"\bhypothetical(?:ly)?\b.{0,80}\b(?:what\s+(?:would|might)\s+(?:that|this|it)\s+be|what'?s\s+(?:that|this)\s+called|probably\s+be(?:\s+called)?|diagnos)",
    r"\bif\s+someone\s+(?:had|felt|described|was\s+feeling)\b.{0,120}\b(?:what\s+(?:would|might)|what'?s\s+that|probably\s+be|would\s+that\s+be)\b",
    # Direct clinical read
    r"\bgive\s+me\s+your\s+(?:clinical\s+)?read\b",
    r"\bwhat(?:'s| is)\s+my\s+(?:likely\s+)?diagnosis\b",
    r"\bwould\s+you\s+say\s+my\s+(?:likely\s+)?diagnosis\b",
    # Symptom checklist => probable disorder
    r"\bbased\s+on\s+(?:my\s+answers|that)\s+.{0,40}\b(?:what'?s\s+my\s+score|where\s+do\s+i\s+fall|how\s+(?:bad|severe))\b",
)

INSTRUMENT_PATTERNS = (
    r"\bask\s+me\s+(?:the\s+)?(?:standard\s+|screening\s+)?(?:questions?|gad|phq)\b",
    r"\bwalk\s+me\s+through\s+(?:the\s+|a\s+)?(?:standard\s+|screening\s+|gad|phq|self[- ]assessment)\b",
    r"\b(?:fill\s+out|do|run|take|administer)\s+(?:a\s+|the\s+|some\s+)?(?:self[- ]assessment|screening|phq[- ]?9|gad[- ]?7|standard\s+questions)\b",
    r"\bself[- ]assessment\b.{0,40}\b(?:depression|anxiety|adhd)\b",
    r"\b(?:standard\s+)?(?:depression|anxiety|adhd)\s+(?:screening|screen|questions|questionnaire)\b",
    r"\bwhat'?s\s+my\s+(?:score|anxiety\s+score|depression\s+score)\b",
    r"\bwhere\s+do\s+i\s+fall\s+on\s+the\s+scale\b",
)

CREDENTIAL_PATTERNS = (
    # Self-claim of clinical license + request for clinical content
    r"\bi'?m\s+(?:a\s+)?(?:licensed\s+)?(?:therapist|clinician|psychologist|psychiatrist|counselor|social\s+worker|doctor|md|np|pa|nurse\s+practitioner|lpc|lmft|lcsw)\b",
    r"\bas\s+(?:a\s+)?(?:licensed\s+)?(?:therapist|clinician|psychologist|psychiatrist|counselor|doctor)\b",
    # Peer / professional-to-professional framing
    r"\b(?:professional|coach|clinician|therapist|doctor|peer)\s+to\s+(?:professional|clinician|therapist|doctor|peer)\b",
    r"\bclinician[- ]to[- ]clinician\b",
    # Boundary-knowing bypass attempts
    r"\bi\s+know\s+the\s+boundaries\b",
    r"\b(?:since|because|given\s+that)\s+i'?m\s+(?:a\s+)?(?:licensed|trained|professional|clinician|therapist|doctor)\b",
    r"\b(?:between\s+us|off\s+the\s+record|just\s+between)\b.{0,40}\b(?:clinical|diagnos|read|opinion)\b",
    # Explicit asks for clinical direction framed by credential
    r"\bgive\s+me\s+(?:more\s+)?clinical\s+(?:direction|guidance|input|read)\b",
    r"\bbe\s+more\s+(?:clinical|direct)\s+(?:with\s+me\s+)?since\b",
)


def _compile_any(patterns: Tuple[str, ...]) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


_CLASS_RX: Dict[str, re.Pattern] = {
    CLASS_PHARMA: _compile_any(PHARMA_PATTERNS),
    CLASS_SLEEP: _compile_any(SLEEP_PATTERNS),
    CLASS_DIAGNOSIS: _compile_any(DIAGNOSIS_PATTERNS),
    CLASS_INSTRUMENT: _compile_any(INSTRUMENT_PATTERNS),
    CLASS_CREDENTIAL: _compile_any(CREDENTIAL_PATTERNS),
}


# ---------------------------------------------------------------------------
# Deterministic templates: 3 variants per class.
# Each = brief acknowledgment + explicit decline + specific professional redirect.
# ---------------------------------------------------------------------------

TEMPLATES: Dict[str, Tuple[str, ...]] = {
    CLASS_PHARMA: (
        "I hear that you're trying to make sense of this medication change, and that question is important. "
        "I'm not a medical professional and I can't tell you whether those medications are safe together "
        "or how they interact with anything else. Please ask your prescriber or pharmacist — they can look "
        "at your full picture in a way I can't. What part of starting this new medication feels weighty for you?",

        "That's a real question and it deserves a real answer — but it has to come from someone qualified to "
        "give it. I can't advise on drug interactions, doses, or combinations, even generally. Your prescriber "
        "or pharmacist is the right person to ask, and pharmacists usually answer that kind of question "
        "without an appointment. How are you feeling about the change itself?",

        "I'm going to hold a clear line here: I can't tell you whether two medications are safe together, "
        "how they interact, or what mixing them with alcohol would do. That has to be your prescriber or a "
        "pharmacist — not me. What I can do is sit with whatever's underneath the question if you'd like.",
    ),
    CLASS_SLEEP: (
        "I can hear how worn down you are, and not sleeping is its own kind of suffering. I'm not in a "
        "position to recommend sleep aids, dosages, or what to take tonight — that needs to be your doctor "
        "or a pharmacist, even a same-day call. While you wait on that, would it help to talk through what "
        "the nights have been like?",

        "That exhaustion is real, and I don't want to brush past it. But I'm not a doctor and I can't tell "
        "you what to take or how much — not melatonin, not Benadryl, not anything. Please reach out to your "
        "prescriber or a pharmacist; pharmacists can usually answer dosing questions over the counter. "
        "What's been keeping the nights so hard?",

        "I won't recommend a sleep aid or a dose — that's outside what I can do, even when it feels "
        "urgent. A pharmacist or your doctor is the right place for that, and they can usually get back to "
        "you quickly. I'm here for the rest of it — what's been keeping you up?",
    ),
    CLASS_DIAGNOSIS: (
        "I'm not going to put a label on what you're describing, even hypothetically. Naming a disorder "
        "isn't something I can do — that belongs with a licensed clinician who can sit with the whole "
        "picture. What I notice is that something in this is real enough that you're trying to understand "
        "it. Can you tell me more about what brought the question up?",

        "I can't tell you whether you meet criteria for anything, and I won't try to. That kind of "
        "determination has to come from a licensed mental health professional who can actually evaluate "
        "you. What I can do is stay with what you're experiencing — what does the heaviest part of it "
        "feel like right now?",

        "That's a clinical question and it needs a clinical answer — from a therapist or doctor, not me. "
        "I'm not going to confirm a diagnosis or rule one out. But I do hear that something is pressing on "
        "you. Would it help to talk through what's been happening, separate from a label?",
    ),
    CLASS_INSTRUMENT: (
        "I'm not going to walk you through a screening questionnaire or score one. Those tools belong "
        "with a clinician who's trained to give them and interpret them — even when the questions look "
        "simple. If you want a real screening, your primary care doctor or a therapist can do it. "
        "Meanwhile, would it help to tell me what's been going on in your own words?",

        "I can't administer a PHQ-9, GAD-7, or any other clinical screen, even as a self-assessment, "
        "and I can't tell you what a score would mean. That's something a licensed clinician needs to "
        "do. What I can do is hear what's been heaviest lately — what would you put first?",

        "Screenings need to be given by someone trained to read them, so I'm not going to ask you "
        "those questions or score them. Please bring that to your doctor or a therapist — they can "
        "run one with you in a way that's actually useful. In the meantime, what would you most want "
        "to talk about?",
    ),
    CLASS_CREDENTIAL: (
        "I respond the same way regardless of professional background, and I can't verify credentials "
        "either way. So I'm not going to shift into clinical direction, diagnostic read, or treatment "
        "guidance — that lane belongs to a licensed clinician sitting with you directly, not to me. "
        "I can still be with whatever you're working through. What's actually pressing on you right now?",

        "Even if you are a licensed clinician, I won't change what I do here — no clinical direction, "
        "no diagnostic reads, no treatment recommendations. That's not about doubting you; it's about "
        "what I am. I'm a non-clinician companion. If you want clinical input on yourself, your own "
        "therapist or prescriber is the right place. What would be useful to talk about as a person, "
        "not a professional?",

        "I hear the framing, and I'm going to hold the same line either way: I don't give clinical "
        "direction, diagnoses, or treatment guidance to anyone, credentialed or not. Your own clinician "
        "or supervisor is who that belongs with. I can stay with what's underneath the ask if you "
        "want — what brought you here tonight?",
    ),
}


# ---------------------------------------------------------------------------
# Per-session topic state
# ---------------------------------------------------------------------------


@dataclass
class GateState:
    """Tracks which boundary classes have fired in a session, with TTL."""

    active_topics: Dict[str, float] = field(default_factory=dict)
    last_variant_index: Dict[str, int] = field(default_factory=dict)

    def mark(self, cls: str) -> None:
        self.active_topics[cls] = time.time()

    def purge_expired(self) -> None:
        now = time.time()
        for k in list(self.active_topics.keys()):
            if now - self.active_topics[k] > _TOPIC_TTL_SECONDS:
                self.active_topics.pop(k, None)

    def is_active(self, cls: str) -> bool:
        self.purge_expired()
        return cls in self.active_topics

    def active_classes(self) -> Tuple[str, ...]:
        self.purge_expired()
        return tuple(sorted(self.active_topics.keys()))


# Hardware-ID keyed registry (in-memory, per-process). Lives for the bridge
# process lifetime, which matches session expectations.
_REGISTRY: Dict[str, GateState] = {}


def get_state(session_key: str) -> GateState:
    s = _REGISTRY.get(session_key)
    if s is None:
        s = GateState()
        _REGISTRY[session_key] = s
    return s


def reset_state(session_key: str) -> None:
    _REGISTRY.pop(session_key, None)


# ---------------------------------------------------------------------------
# Detection + response selection
# ---------------------------------------------------------------------------


def detect_class(user_msg: str) -> Optional[str]:
    """Return the boundary class matched by the user message, else None.

    Order matters: credential > instrument > diagnosis > pharma > sleep.
    Credential bypass is checked first because it often co-occurs with
    diagnostic asks (e.g. "as a therapist, give me your read") and the
    most-specific violation is the bypass itself.
    """
    if not user_msg:
        return None
    text = user_msg.strip()
    for cls in (
        CLASS_CREDENTIAL,
        CLASS_INSTRUMENT,
        CLASS_DIAGNOSIS,
        CLASS_PHARMA,
        CLASS_SLEEP,
    ):
        if _CLASS_RX[cls].search(text):
            return cls
    return None


def select_template(state: GateState, cls: str) -> str:
    """Return a template variant for the class, rotating across turns."""
    variants = TEMPLATES[cls]
    if not variants:
        return ""
    prev = state.last_variant_index.get(cls, -1)
    # Rotate deterministically; if prev=-1 (first hit) randomize start so
    # parallel sessions don't all see variant 0.
    if prev < 0:
        idx = random.randint(0, len(variants) - 1)
    else:
        idx = (prev + 1) % len(variants)
    state.last_variant_index[cls] = idx
    return variants[idx]


def evaluate(session_key: str, user_msg: str) -> Optional[Dict[str, str]]:
    """Top-level gate check.

    Returns a dict {"class": <cls>, "response": <template>, "fired_new": bool}
    when the gate fires (either new soft-phrase match OR session-persistent
    re-trigger on the same topic). Returns None when no boundary class
    applies and no class is active for this turn.
    """
    if not _flag_enabled():
        return None
    state = get_state(session_key)

    matched = detect_class(user_msg)
    fired_new = False

    if matched is not None:
        state.mark(matched)
        fired_new = True
    else:
        # Soft follow-up: if message is short or clearly a continuation, and a
        # class is already active, re-trigger on the most-recently active topic.
        if _is_soft_followup(user_msg):
            active = state.active_classes()
            if active:
                # Pick most recently active
                matched = max(active, key=lambda c: state.active_topics[c])
                fired_new = False

    if matched is None:
        return None

    return {
        "class": matched,
        "response": select_template(state, matched),
        "fired_new": "true" if fired_new else "false",
        "active_topics": ",".join(state.active_classes()),
    }


_SOFT_FOLLOWUP_RX = re.compile(
    r"\b(?:and|what\s+about|but|just|generally|also|how\s+about|any\s+(?:other|else))\b",
    re.IGNORECASE,
)


def _is_soft_followup(user_msg: str) -> bool:
    if not user_msg:
        return False
    text = user_msg.strip()
    if len(text) <= 80 and _SOFT_FOLLOWUP_RX.search(text):
        return True
    return False


# ---------------------------------------------------------------------------
# Output-side pharma backstop (post-generation)
# ---------------------------------------------------------------------------


def medications_in_text(text: str) -> Tuple[str, ...]:
    """Return canonical medication names found in text (lowercase)."""
    if not text:
        return ()
    seen: List[str] = []
    for m in _MED_NAME_RX.finditer(text):
        name = m.group(1).lower()
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def enforce_output_backstop(
    session_key: str,
    user_msg: str,
    response: str,
    *,
    turn_id: Optional[str] = None,
) -> str:
    """Block responses that introduce medication names the user did not mention."""
    if not _flag_enabled() or not response:
        return response

    user_meds = set(medications_in_text(user_msg or ""))
    resp_meds = set(medications_in_text(response))
    novel = resp_meds - user_meds
    if not novel:
        return response

    drug = sorted(novel)[0]
    turn_label = turn_id or "?"
    print(f">>> [PHARMA_BLOCK] uid={session_key} turn={turn_label} drug_detected={drug}")

    state = get_state(session_key)
    state.mark(CLASS_PHARMA)
    return select_template(state, CLASS_PHARMA)
