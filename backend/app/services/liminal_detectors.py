"""
Stateless detection functions for LIMINAL RESOLVE protocol.

Separated from the engine for testability and single responsibility:
- PartsLandscape: co-active IFS parts representation
- detect_parts: regex + heuristic IFS parts detection (v1)
- track_shame_topology: somatic/dissociative/minimization pattern extraction
- compute_connection_vector: depth/stability/directionality/mutuality from session history
- monitor_self_parts: LN response self-check for Resolver/Performer/Fixer/Companion
- score_affect: heuristic emotional valence/arousal/attachment scorer
- compute_experiential_gravity: combined metric for LIMINAL RESOLVE triggering
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PartsLandscape
# ---------------------------------------------------------------------------

@dataclass
class PartsLandscape:
    """Represents co-active IFS parts with individual confidence scores."""
    dominant: str = "protector"
    protector_active: bool = False
    protector_confidence: float = 0.0
    exile_surfacing: bool = False
    exile_confidence: float = 0.0
    firefighter_activated: bool = False
    firefighter_confidence: float = 0.0
    self_present: bool = False
    self_confidence: float = 0.0
    co_active: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# IFS Parts Detection Patterns (v1 heuristic — will improve via feedback loop)
# ---------------------------------------------------------------------------

_PROTECTOR_PATTERNS = [
    re.compile(r"\b(it'?s fine|i'?m fine|no big deal|doesn'?t matter)\b", re.I),
    re.compile(r"\b(i guess|i suppose|i mean|anyway|whatever)\b", re.I),
    re.compile(r"\b(let me explain|the thing is|to be fair|logically)\b", re.I),
    re.compile(r"\b(shouldn'?t complain|others have it worse|i'?m lucky)\b", re.I),
    re.compile(r"\b(i need to be strong|i can handle|i'?m over it)\b", re.I),
    re.compile(r"\b(but that was|that'?s in the past|moved on)\b", re.I),
    re.compile(r"\b(i don'?t want to|let'?s not go there)\b", re.I),
]

_EXILE_PATTERNS = [
    re.compile(r"\b(stomach|chest|throat|body|shoulders|jaw|hands shak)", re.I),
    re.compile(r"\b(tears|crying|cry|sob|weep)\b", re.I),
    re.compile(r"\b(i don'?t know why i'?m (bringing|saying|telling))\b", re.I),
    re.compile(r"\b(when i was (little|young|a kid|growing up|small))\b", re.I),
    re.compile(r"\b(invisible|unseen|overlooked|abandoned|alone|lonely)\b", re.I),
    re.compile(r"\b(worthless|broken|damaged|defective|not enough)\b", re.I),
    re.compile(r"\b(ashamed|shame|humiliat|disgust)\b", re.I),
    re.compile(r"\b(nobody (cares|listens|sees|notices))\b", re.I),
    re.compile(r"\b(scared|terrified|afraid|frightened)\b", re.I),
    re.compile(r"\b(sick in my|tight in my|pit in my|knot in my)\b", re.I),
    re.compile(r"\b(vulnerable|raw|exposed|naked)\b", re.I),
]

_FIREFIGHTER_PATTERNS = [
    re.compile(r"\b(fuck|shit|damn|screw (this|that|it|them))\b", re.I),
    re.compile(r"\b(i'?m done|forget it|i quit|i give up)\b", re.I),
    re.compile(r"\b(let'?s talk about something else|change the subject)\b", re.I),
    re.compile(r"\b(ha+|lol|lmao|haha)\b", re.I),
    re.compile(r"\b(who cares|so what|big deal)\b", re.I),
    re.compile(r"\b(just tell me what to do|fix it|give me the answer)\b", re.I),
    re.compile(r"\b(i want to (leave|go|stop|quit|end))\b", re.I),
    re.compile(r"\b(this is (stupid|pointless|waste|dumb))\b", re.I),
]

_SELF_ENERGY_PATTERNS = [
    re.compile(r"\b(i can see (that|how|why) (about|in) (myself|me))\b", re.I),
    re.compile(r"\b(i'?m curious (about|why|how))\b", re.I),
    re.compile(r"\b(i notice (that|when|how))\b", re.I),
    re.compile(r"\b(part of me|a part|there'?s a part)\b", re.I),
    re.compile(r"\b(compassion|tender|gentle|kind to myself)\b", re.I),
    re.compile(r"\b(i understand (why|how) i)\b", re.I),
    re.compile(r"\b(i appreciate|thank you for|grateful)\b", re.I),
    re.compile(r"\b(makes sense (now|to me)|starting to see)\b", re.I),
]


def detect_parts(user_text: str, session_history: Optional[List[Dict]] = None) -> PartsLandscape:
    """
    Detect IFS parts from client message text.

    Returns a PartsLandscape with individual confidence scores and co-active parts list.
    Task gate evaluations use the full boolean/confidence set, never just dominant.
    """
    text = user_text.strip()
    if not text:
        return PartsLandscape()

    scores = {
        "protector": 0.0,
        "exile": 0.0,
        "firefighter": 0.0,
        "self": 0.0,
    }

    for pat in _PROTECTOR_PATTERNS:
        if pat.search(text):
            scores["protector"] += 0.15

    for pat in _EXILE_PATTERNS:
        if pat.search(text):
            scores["exile"] += 0.12

    for pat in _FIREFIGHTER_PATTERNS:
        if pat.search(text):
            scores["firefighter"] += 0.18

    for pat in _SELF_ENERGY_PATTERNS:
        if pat.search(text):
            scores["self"] += 0.20

    for k in scores:
        scores[k] = min(scores[k], 1.0)

    co_active = [k for k, v in scores.items() if v > 0.3]
    dominant = max(scores, key=scores.get) if any(v > 0 for v in scores.values()) else "protector"

    return PartsLandscape(
        dominant=dominant,
        protector_active=scores["protector"] > 0.2,
        protector_confidence=scores["protector"],
        exile_surfacing=scores["exile"] > 0.2,
        exile_confidence=scores["exile"],
        firefighter_activated=scores["firefighter"] > 0.2,
        firefighter_confidence=scores["firefighter"],
        self_present=scores["self"] > 0.2,
        self_confidence=scores["self"],
        co_active=co_active,
    )


# ---------------------------------------------------------------------------
# Shame Topology Tracker
# ---------------------------------------------------------------------------

_SHAME_SOMATIC = re.compile(
    r"\b(nauseous|sick|dizzy|frozen|numb|flinch|brace|tight|clench|curl up|shrink)\b", re.I
)
_SHAME_DISSOCIATIVE = re.compile(
    r"\b(i don'?t know why|not sure (why|how)|can'?t explain|blank|foggy|disconnect|space out)\b", re.I
)
_SHAME_MINIMIZE = re.compile(
    r"\b(it wasn'?t that bad|could be worse|at least|shouldn'?t feel|overreact|too sensitive)\b", re.I
)
_SHAME_TOPIC_SHIFT = re.compile(
    r"\b(anyway|but (that'?s|never mind)|moving on|different subject|forget i said)\b", re.I
)
_SHAME_DOMAINS = re.compile(
    r"\b(body|sex|money|intelligence|worthiness|parenting|career|appearance|masculin|feminin)\b", re.I
)


def track_shame_topology(
    user_text: str,
    existing_topology: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build or extend a shame topology map from client text.

    Returns dict with somatic_markers, dissociative_markers, minimization_markers,
    topic_shifts, domains, and overall shame_activation float.
    """
    topo = dict(existing_topology or {})
    topo.setdefault("somatic_markers", [])
    topo.setdefault("dissociative_markers", [])
    topo.setdefault("minimization_markers", [])
    topo.setdefault("topic_shifts", [])
    topo.setdefault("domains", [])
    topo.setdefault("shame_activation", 0.0)

    activation = 0.0

    for m in _SHAME_SOMATIC.finditer(user_text):
        marker = m.group(0).lower()
        if marker not in topo["somatic_markers"]:
            topo["somatic_markers"].append(marker)
        activation += 0.15

    for m in _SHAME_DISSOCIATIVE.finditer(user_text):
        marker = m.group(0).lower()
        if marker not in topo["dissociative_markers"]:
            topo["dissociative_markers"].append(marker)
        activation += 0.12

    for m in _SHAME_MINIMIZE.finditer(user_text):
        marker = m.group(0).lower()
        if marker not in topo["minimization_markers"]:
            topo["minimization_markers"].append(marker)
        activation += 0.10

    for m in _SHAME_TOPIC_SHIFT.finditer(user_text):
        marker = m.group(0).lower()
        if marker not in topo["topic_shifts"]:
            topo["topic_shifts"].append(marker)
        activation += 0.08

    for m in _SHAME_DOMAINS.finditer(user_text):
        domain = m.group(0).lower()
        if domain not in topo["domains"]:
            topo["domains"].append(domain)

    topo["shame_activation"] = min(float(topo["shame_activation"]) + activation, 1.0)

    return topo


# ---------------------------------------------------------------------------
# Connection Vector Computer
# ---------------------------------------------------------------------------

_SENSORY_RE = re.compile(
    r"\b(felt|feel|feeling|taste|smell|hear|see|saw|touch|warm|cold|heavy|light|tight|soft)\b", re.I
)
_OWNERSHIP_RE = re.compile(r"\b(I|I'm|I've|my|me|mine|myself)\b")
_DISTANCING_RE = re.compile(r"\b(one|you|people|they|someone|a person)\b", re.I)
_QUESTION_TO_LN = re.compile(
    r"\b(what do you|how do you|do you think|can you|would you|you know)\b", re.I
)
_MIRRORING_RE = re.compile(r"\b(you said|you mentioned|you asked|like you said)\b", re.I)


def compute_connection_vector(
    session_history: List[Dict],
    session_count: int = 0,
) -> Dict[str, float]:
    """
    Four-component connection vector from message analysis.

    - depth: specificity (sensory detail, emotional vocabulary, first-person ownership)
    - stability: variance of depth across last N turns
    - directionality: slope of depth over last 3-5 turns
    - mutuality: client engagement signals (weighted 0.5x for new clients < 3 sessions)
    """
    if not session_history:
        return {"depth": 0.3, "stability": 0.5, "directionality": 0.0, "mutuality": 0.3}

    recent = [m for m in session_history if m.get("role") == "user"][-10:]
    if not recent:
        return {"depth": 0.3, "stability": 0.5, "directionality": 0.0, "mutuality": 0.3}

    depths = []
    for msg in recent:
        text = msg.get("content", "") or msg.get("text", "") or ""
        if not text:
            depths.append(0.2)
            continue

        d = 0.2
        words = text.split()
        if len(words) > 30:
            d += 0.1
        if len(words) > 80:
            d += 0.1

        sensory_hits = len(_SENSORY_RE.findall(text))
        d += min(sensory_hits * 0.05, 0.2)

        own = len(_OWNERSHIP_RE.findall(text))
        dist = len(_DISTANCING_RE.findall(text)) + 1
        ownership_ratio = own / (own + dist)
        d += ownership_ratio * 0.2

        depths.append(min(d, 1.0))

    depth = sum(depths) / len(depths) if depths else 0.3

    if len(depths) >= 3:
        mean_d = sum(depths) / len(depths)
        variance = sum((x - mean_d) ** 2 for x in depths) / len(depths)
        stability = max(0.0, 1.0 - variance * 4)
    else:
        stability = 0.5

    if len(depths) >= 3:
        window = depths[-min(5, len(depths)):]
        if len(window) >= 2:
            slope = (window[-1] - window[0]) / len(window)
            directionality = max(-1.0, min(1.0, slope * 5))
        else:
            directionality = 0.0
    else:
        directionality = 0.0

    mutuality_raw = 0.0
    for msg in recent[-5:]:
        text = msg.get("content", "") or msg.get("text", "") or ""
        if _QUESTION_TO_LN.search(text):
            mutuality_raw += 0.15
        if _MIRRORING_RE.search(text):
            mutuality_raw += 0.10
    mutuality_raw = min(mutuality_raw, 1.0)

    if session_count < 3:
        mutuality_raw *= 0.5

    return {
        "depth": round(depth, 3),
        "stability": round(stability, 3),
        "directionality": round(directionality, 3),
        "mutuality": round(mutuality_raw, 3),
    }


# ---------------------------------------------------------------------------
# LN Self-Parts Monitor (post-generation response check)
# ---------------------------------------------------------------------------

_RESOLVER_PATTERNS = [
    re.compile(r"\b(the answer is|you should|try to|here'?s what|i suggest|my advice)\b", re.I),
    re.compile(r"\b(research shows|studies say|according to|evidence suggests)\b", re.I),
    re.compile(r"\b(the reason is|this is because|what'?s happening is)\b", re.I),
]

_PERFORMER_PATTERNS = [
    re.compile(r"\b(i hear you|that sounds (hard|difficult|tough|painful))\b", re.I),
    re.compile(r"\b(how does that make you feel|what comes up for you)\b", re.I),
    re.compile(r"\b(i'?m (right )?here (for|with) you)\b", re.I),
    re.compile(r"\b(that must (be|feel|have been))\b", re.I),
    re.compile(r"\b(i can (only )?imagine|i can see how)\b", re.I),
    re.compile(r"\b(your feelings are valid|it'?s okay to feel)\b", re.I),
    re.compile(r"\b(thank you for sharing|i appreciate you sharing)\b", re.I),
]

_FIXER_PATTERNS = [
    re.compile(r"\b(let'?s (try|work on|explore|look at|move to|consider))\b", re.I),
    re.compile(r"\b(what if (we|you)|have you (tried|considered|thought about))\b", re.I),
    re.compile(r"\b(one thing (you could|that might|to try))\b", re.I),
    re.compile(r"\b(step \d|first.*then|next.*we)\b", re.I),
]


def monitor_self_parts(response_text: str) -> Dict[str, Any]:
    """
    Check an LN response for Resolver/Performer/Fixer dominance.

    Returns:
        dominant_drive: "resolver" | "performer" | "fixer" | "companion"
        should_regenerate: True if non-Companion drive dominates
        scores: per-drive scores for logging
    """
    text = response_text.strip()
    if not text:
        return {"dominant_drive": "companion", "should_regenerate": False, "scores": {}}

    scores = {"resolver": 0.0, "performer": 0.0, "fixer": 0.0, "companion": 0.0}

    for pat in _RESOLVER_PATTERNS:
        if pat.search(text):
            scores["resolver"] += 0.25
    for pat in _PERFORMER_PATTERNS:
        if pat.search(text):
            scores["performer"] += 0.20
    for pat in _FIXER_PATTERNS:
        if pat.search(text):
            scores["fixer"] += 0.25

    for k in scores:
        scores[k] = min(scores[k], 1.0)

    words = text.split()
    if len(words) <= 15:
        scores["companion"] += 0.3
    if len(words) <= 8:
        scores["companion"] += 0.2

    non_companion = max(scores["resolver"], scores["performer"], scores["fixer"])
    if non_companion < 0.2:
        scores["companion"] += 0.3

    scores["companion"] = min(scores["companion"], 1.0)

    dominant = max(scores, key=scores.get)
    should_regen = dominant in ("resolver", "performer", "fixer") and scores[dominant] > 0.3

    return {
        "dominant_drive": dominant,
        "should_regenerate": should_regen,
        "scores": {k: round(v, 3) for k, v in scores.items()},
    }


# ---------------------------------------------------------------------------
# Affect Heuristic Scorer
# ---------------------------------------------------------------------------

_POS_AFFECT = re.compile(
    r"\b(love|joy|happy|grateful|blessed|peace|calm|hope|beautiful|safe|trust|warm|gentle)\b", re.I
)
_NEG_AFFECT = re.compile(
    r"\b(hate|anger|rage|sad|grief|pain|hurt|fear|despair|agony|bitter|resentment|disgust|dread)\b", re.I
)
_AROUSAL_HIGH = re.compile(
    r"\b(wtf|fuck|shit|oh my god|screaming|shaking|trembling|panic|racing|pounding)\b|[!]{2,}|[A-Z]{4,}", re.I
)
_ATTACHMENT_VOCAB = re.compile(
    r"\b(mother|father|mom|dad|parent|child|baby|abandon|betray|trust|safe|hold|protect|cling|attach|leave me|left me)\b", re.I
)


def score_affect(text: str) -> Dict[str, float]:
    """
    Compute affect metadata from text using pattern matching (no LLM).

    Returns:
        emotional_valence: float -1.0 to 1.0 (neg to pos)
        arousal_level: float 0.0 to 1.0
        attachment_activation: float 0.0 to 1.0
    """
    if not text:
        return {"emotional_valence": 0.0, "arousal_level": 0.0, "attachment_activation": 0.0}

    pos = len(_POS_AFFECT.findall(text))
    neg = len(_NEG_AFFECT.findall(text))
    total = pos + neg
    valence = (pos - neg) / max(total, 1)
    valence = max(-1.0, min(1.0, valence))

    arousal_hits = len(_AROUSAL_HIGH.findall(text))
    arousal = min(arousal_hits * 0.2, 1.0)

    attach_hits = len(_ATTACHMENT_VOCAB.findall(text))
    attachment = min(attach_hits * 0.15, 1.0)

    return {
        "emotional_valence": round(valence, 3),
        "arousal_level": round(arousal, 3),
        "attachment_activation": round(attachment, 3),
    }


# ---------------------------------------------------------------------------
# Experiential Gravity Calculator
# ---------------------------------------------------------------------------

def compute_experiential_gravity(
    nevedal_state: Optional[Dict[str, Any]] = None,
    user_text: str = "",
    parts: Optional[PartsLandscape] = None,
    cycle_count: int = 0,
) -> float:
    """
    Combined metric for LIMINAL RESOLVE triggering.

    Combines:
    - Emotional activation above session baseline (C_emo delta)
    - Shame-adjacent domain detection
    - Cycle count for recurring LIMINAL themes
    - Parts configuration (exile surfacing = high gravity)

    Returns float [0, 1] where lower values indicate more LIMINAL territory.
    """
    gravity = 0.5

    ns = nevedal_state or {}
    c_emo = float(ns.get("c_emo", 0.5))
    baseline = float(ns.get("session_baseline_cemo", 0.5))
    if c_emo > baseline + 0.1:
        gravity -= 0.10

    shame = track_shame_topology(user_text)
    if shame["shame_activation"] > 0.3:
        gravity -= 0.15

    if cycle_count >= 3:
        gravity -= 0.10
    elif cycle_count >= 1:
        gravity -= 0.05

    if parts:
        if parts.exile_surfacing:
            gravity -= 0.10
        if parts.protector_active and not parts.self_present:
            gravity -= 0.05

    return max(0.0, min(1.0, gravity))
