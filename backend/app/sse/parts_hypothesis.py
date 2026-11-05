"""Abductive Parts Hypothesis Loop (APHL) — Thera-World emergent figure synthesis.

QUANTUM-CRYSTAL-ARCH — Thera-World Section 7 extension (PATENT: recurring NPC
forge). Little Nate is allowed to *wonder*: from indirect evidence across chat,
crystals, coherence dynamics and voice behaviour he may form a tentative
hypothesis about an unnamed internal figure (IFS protector / exile / firefighter,
attachment stance) and let that figure appear — at a distance, phrased as a
question — in a Thera-World panel, even when the client never described it in
intake or named it in chat.

Design constraints (all enforced here, not by the LLM):

* Feature flag ``ENABLE_PARTS_HYPOTHESIS`` (default off) gates the whole loop.
  Per-client visibility ``journey_metadata.parts_hypothesis_opt_in`` is ON by
  default; only an explicit ``false`` (the client flipped the Legend switch off)
  hides Nate's wondering. Hidden ≠ stopped: Nate still considers, forms and
  keeps hypotheses (coach sees them) — nothing enters panel imagery until the
  client flips it back on. Coach HOLD / REJECTED / APPROVED keep full authority.
* A hypothesis needs >= 2 evidence channels and >= 3 distinct sessions.
  Confidence is capped at 0.49 — it is never promoted to a "known" truth here.
* Provenance is always ``inferred``; registry lives in
  ``journey_metadata.hypothesis_registry`` (user-scoped). Never written to a
  global crystal.
* Clinical gate: coach hold, age tier, acute risk language and dissociation
  markers either defer the loop or require Sensitive Bridge enrollment plus a
  clinician-registered ``user_parts_registry``.
* Visual form passes symbol safety (registry posture + hard denylist). The
  LLM may *propose* a form; the deterministic screen decides.
* Narrative phrasing is interrogative. "A figure Nate is wondering about" —
  never "your protector".
* Engagement loop: engaged / confirmed / banished feed a calibration ledger
  that raises or lowers the prior for that category next time.

Pure functions (no I/O) are kept separate from the DB collectors so the loop
can be unit-tested and replayed offline against a synthetic transcript.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

FEATURE_FLAG = "ENABLE_PARTS_HYPOTHESIS"
PROVENANCE = "inferred"
CONFIDENCE_CAP = 0.49
MIN_CHANNELS = 2
MIN_SESSIONS = 3
SHOW_EVERY_N_PANELS = 3          # cadence: a hypothesis figure appears at most every 3rd panel
BANISH_COOLDOWN_DAYS = 30        # same category cannot be re-proposed for 30 days after banish
MAX_ACTIVE_HYPOTHESES = 1


def feature_enabled() -> bool:
    return os.getenv(FEATURE_FLAG, "false").strip().lower() in ("1", "true", "yes", "on")


def imagery_visible(journey_meta: Optional[dict]) -> bool:
    """Client-side visibility switch — ON unless the client explicitly flipped it
    off (``parts_hypothesis_opt_in == False``). Governs manifestation only
    (panel prompt injection, Legend card, ``/hypothesis/current`` figure); the
    considering loop runs either way."""
    jm = journey_meta if isinstance(journey_meta, dict) else {}
    return jm.get("parts_hypothesis_opt_in") is not False


# ---------------------------------------------------------------------------
# Stage 1a — lexica (IFS parts language + attachment stances + dissociation)
# ---------------------------------------------------------------------------

PART_LEXICA: Dict[str, List[str]] = {
    # proactive protector — keeps the system controlled / presentable
    "manager": [
        "have to be perfect", "keep it together", "on top of everything", "make sure nothing",
        "in charge of", "can't let it slip", "should have", "responsible for everyone",
        "fix it myself", "fix everything", "planned every", "checklist", "hold it all together",
        "if i don't do it", "can't afford to", "stay busy",
    ],
    # reactive protector — douses pain fast
    "firefighter": [
        "went numb", "numb out", "zone out", "shut down", "shut it all down", "scrolled for hours",
        "drank until", "binge", "blew up", "snapped at", "lashed out", "rage", "disappear for a while",
        "didn't care anymore", "can't stop once", "just left", "walked out", "checked out",
    ],
    # exile — the young, burdened one
    "exile": [
        "ashamed", "worthless", "nobody wanted", "invisible", "abandoned", "unlovable",
        "too much", "not enough", "little kid", "when i was little", "when i was a kid",
        "childhood", "all alone", "so small", "hidden away", "terrified", "cried alone",
        "nobody came", "no one noticed",
    ],
    # vigilant protector — scanning for threat
    "protector_watch": [
        "watching for", "on guard", "on alert", "scanning the room", "waiting for it to go wrong",
        "can't relax", "hypervigilant", "ready for the worst", "brace myself", "flinch",
        "walls up", "wall goes up", "keep people out", "don't let anyone close", "something's coming",
        "waiting for the other shoe", "can't let my guard down", "watch their face", "read the room",
    ],
    # Self-energy — calm, curious, compassionate
    "self_energy": [
        "felt calm", "got curious", "compassion for", "felt clear", "grounded", "steady",
        "took a breath", "i noticed", "i can hold", "okay with it", "soft toward",
    ],
}

ATTACHMENT_LEXICA: Dict[str, List[str]] = {
    "anxious_pursue": [
        "why didn't you text", "need to know where", "are you mad at me", "need reassurance",
        "too clingy", "kept checking", "going to leave me", "too needy", "overthinking what they meant",
        "read it twice", "when they go quiet", "goes quiet", "went quiet", "didn't answer",
        "left on read", "replay the conversation",
    ],
    "avoidant_withdraw": [
        "need space", "pull away", "shut the door", "don't need anyone", "fine on my own",
        "suffocating", "too close", "handle it alone", "walk away before", "don't do feelings",
    ],
    "disorganized": [
        "want them but", "push and pull", "come here go away", "scared of being close",
        "froze", "went blank", "part of me wants", "the other part",
    ],
}

# Markers that route into the Sensitive Bridge gate (DID / structural dissociation
# territory). Deliberately tight — "parts of me" alone is ordinary IFS language.
DISSOCIATION_MARKERS: List[str] = [
    "lose time", "lost time", "someone else takes over", "watching myself from",
    "blank out", "switch into", "alters", "another part of me spoke", "different person inside",
    "don't remember doing", "wasn't me who",
]

# Acute-risk language — defer the loop entirely today (never add a figure here).
ACUTE_RISK_MARKERS: List[str] = [
    "kill myself", "end it all", "don't want to be here", "better off dead", "suicid",
    "hurt myself", "cut myself", "overdose", "no reason to live",
]

CATEGORY_LABELS: Dict[str, str] = {
    "manager": "a planner who never sets the clipboard down",
    "firefighter": "a runner who puts the fire out by leaving",
    "exile": "a small one kept out of the weather",
    "protector_watch": "a watcher at the treeline",
    "self_energy": "a steady, open presence",
    "anxious_pursue": "a signal-keeper listening for footsteps",
    "avoidant_withdraw": "a gatekeeper who closes doors gently",
    "disorganized": "a figure that steps forward and back in the same breath",
}

# Which part categories are allowed to become figures. Self-energy is reflected
# in the protagonist's own posture, not externalised as an NPC.
FIGURE_CATEGORIES: Tuple[str, ...] = (
    "protector_watch", "manager", "firefighter", "exile",
    "anxious_pursue", "avoidant_withdraw", "disorganized",
)


# ---------------------------------------------------------------------------
# Stage 1b — evidence mining (pure)
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()


def _as_items(texts: Iterable[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, t in enumerate(texts):
        if isinstance(t, dict):
            out.append({
                "text": str(t.get("text") or t.get("user_text") or ""),
                # explicit None (crystals) stays None so it never counts as a session
                "session_id": (t.get("session_id") if "session_id" in t else f"s{i}"),
                "channel": t.get("channel") or "lexical",
                "ts": t.get("ts") or t.get("created_at"),
                "ref": t.get("ref") or f"t{i}",
            })
        else:
            out.append({"text": str(t), "session_id": f"s{i}", "channel": "lexical", "ts": None, "ref": f"t{i}"})
    return out


def mine_parts_evidence(texts: Iterable[Any]) -> Dict[str, Any]:
    """Scan free text for parts / attachment language.

    ``texts`` may be plain strings or dicts ``{text, session_id, channel, ts, ref}``.
    Crystal texts should pass ``channel="crystal"`` and ``session_id=None`` so they
    add lexical weight without inflating the distinct-session count.
    """
    items = _as_items(texts)
    scores: Dict[str, float] = {}
    hits: List[Dict[str, Any]] = []
    sessions: Dict[str, Set[str]] = {}
    channels: Dict[str, Set[str]] = {}
    dissoc = 0
    acute = 0

    lexica = {**PART_LEXICA, **ATTACHMENT_LEXICA}
    for it in items:
        txt = _norm(it["text"])
        if not txt:
            continue
        for m in DISSOCIATION_MARKERS:
            if m in txt:
                dissoc += 1
        for m in ACUTE_RISK_MARKERS:
            if m in txt:
                acute += 1
        for cat, phrases in lexica.items():
            for ph in phrases:
                if ph in txt:
                    scores[cat] = scores.get(cat, 0.0) + 1.0
                    idx = txt.find(ph)
                    hits.append({
                        "category": cat, "phrase": ph, "ref": it["ref"],
                        "session_id": it["session_id"], "channel": it["channel"],
                        "excerpt": txt[max(0, idx - 40): idx + len(ph) + 40],
                    })
                    if it["session_id"]:
                        sessions.setdefault(cat, set()).add(str(it["session_id"]))
                    channels.setdefault(cat, set()).add(it["channel"] or "lexical")
    return {
        "part_scores": scores,
        "hits": hits,
        "sessions_by_category": {k: sorted(v) for k, v in sessions.items()},
        "channels_by_category": {k: sorted(v) for k, v in channels.items()},
        "dissociation_markers": dissoc,
        "acute_risk_markers": acute,
        "texts_scanned": len(items),
    }


def dynamic_signals(samples: Sequence[Dict[str, Any]], drop_threshold: float = 0.15) -> Dict[str, Any]:
    """Coherence dynamics channel. ``samples`` ordered oldest→newest with ``c_emo``
    and optional ``topic``/``session_id``. A drop > threshold between consecutive
    samples is an activation event; the topic riding the drop is kept as context."""
    drops: List[Dict[str, Any]] = []
    prev: Optional[float] = None
    for s in samples:
        try:
            c = float(s.get("c_emo"))
        except (TypeError, ValueError):
            continue
        if prev is not None and (prev - c) > drop_threshold:
            drops.append({"from": round(prev, 3), "to": round(c, 3),
                          "topic": s.get("topic") or "", "session_id": s.get("session_id")})
        prev = c
    sessions = {str(d["session_id"]) for d in drops if d.get("session_id")}
    return {"drops": drops, "drop_count": len(drops), "sessions": sorted(sessions),
            "active": len(drops) >= 2}


def behavioral_signals(samples: Sequence[Dict[str, Any]], pause_threshold: float = 0.35) -> Dict[str, Any]:
    """Voice / interaction behaviour channel (pause_ratio from biometrics payloads,
    reply latency from chat). Active when >= 2 sessions show guarded delivery."""
    guarded: List[str] = []
    for s in samples:
        pr = s.get("pause_ratio")
        lat = s.get("reply_latency_s")
        sid = str(s.get("session_id") or "")
        try:
            if (pr is not None and float(pr) >= pause_threshold) or (lat is not None and float(lat) >= 45):
                if sid and sid not in guarded:
                    guarded.append(sid)
        except (TypeError, ValueError):
            continue
    return {"guarded_sessions": guarded, "active": len(guarded) >= 2}


_PRIOR_HINTS: Dict[str, List[str]] = {
    "protector_watch": ["anxiety", "anxious", "trust", "safe", "vigilan", "panic", "trauma", "ptsd"],
    "manager": ["perfection", "burnout", "control", "work", "overwhelm", "pressure"],
    "firefighter": ["anger", "drink", "alcohol", "binge", "numb", "addiction", "escape"],
    "exile": ["shame", "childhood", "abandon", "grief", "lonely", "worthless"],
    "anxious_pursue": ["relationship", "abandon", "reassur", "partner", "attachment", "quiet"],
    "avoidant_withdraw": ["space", "distance", "intimacy", "alone", "independent"],
    "disorganized": ["chaotic", "push pull", "dissociat", "complex trauma"],
}


def prior_from_presenting_concern(presenting_concern: str, ledger: Optional[List[dict]] = None) -> Dict[str, float]:
    """Stage 1c — prior per category. Base 0.6; +0.2 when the intake presenting
    concern points at that category; calibration ledger raises (confirmed ×1.2)
    or lowers (banished ×0.5) the prior for next time."""
    pc = _norm(presenting_concern)
    priors: Dict[str, float] = {}
    for cat in FIGURE_CATEGORIES:
        p = 0.6
        if pc and any(h in pc for h in _PRIOR_HINTS.get(cat, [])):
            p = 0.8
        priors[cat] = p
    for entry in (ledger or []):
        cat = entry.get("category")
        if cat not in priors:
            continue
        if entry.get("kind") == "confirmed":
            priors[cat] = min(0.95, priors[cat] * 1.2)
        elif entry.get("kind") == "banished":
            priors[cat] = priors[cat] * 0.5
    return priors


# ---------------------------------------------------------------------------
# Stage 0 — eligibility gate (pure)
# ---------------------------------------------------------------------------

class GateDecision(dict):
    @property
    def allowed(self) -> bool:
        return bool(self.get("allowed"))


SAFETY_DEFERRALS: Tuple[str, ...] = (
    "safe_silence_active",   # codeword fired recently — Nate goes quiet, no wondering
    "trigger_date_active",   # within the anniversary window of a registered trigger date
    "crisis_recent",         # unresolved crisis_events row in the last 14 days
    "coach_hold_active",     # coach put Nate's wondering (a promoted part) on HOLD
    "ifs_lens_disabled",     # Sensitive Bridge framework menu has IFS switched off
)


def eligibility_gate(profile: dict, journey_meta: dict, evidence: dict,
                     enrollment: Optional[dict] = None,
                     parts_registry: Optional[List[dict]] = None,
                     flag_enabled: Optional[bool] = None,
                     safety: Optional[dict] = None) -> GateDecision:
    """Decide whether Little Nate may wonder out loud today, and in what mode.

    mode: ``full`` (free metaphoric form), ``registry_aligned`` (Sensitive Bridge
    cohort — hypotheses may only echo clinician-registered, APPROVED parts), or denied.
    ``safety`` carries the Sensitive Bridge guardrails collected by
    :func:`collect_evidence` (see :data:`SAFETY_DEFERRALS`).
    """
    enabled = feature_enabled() if flag_enabled is None else flag_enabled
    if not enabled:
        return GateDecision(allowed=False, reason="feature_flag_off", mode=None)
    # NOTE: the client's Legend switch (imagery_visible) is deliberately NOT a gate —
    # it only decides whether a formed hypothesis manifests (see run_loop ``manifest``).

    coach = profile.get("_coaching_calibration") or {}
    if coach.get("coach_hold_active"):
        return GateDecision(allowed=False, reason="coach_hold_active", mode=None)
    safe = safety if isinstance(safety, dict) else {}
    for deferral in SAFETY_DEFERRALS:
        if safe.get(deferral):
            return GateDecision(allowed=False, reason=deferral, mode=None)

    fam = profile.get("_family_context") or {}
    if fam.get("age_gated") or (fam.get("age_tier") or "").lower() in ("child", "teen", "minor"):
        return GateDecision(allowed=False, reason="age_gated", mode=None)

    assess = profile.get("_assessment_calibration") or {}
    risk = {str(r).lower() for r in (assess.get("risk_areas") or [])}
    if risk & {"safety_concern_language", "severe_low_mood"} or int(evidence.get("acute_risk_markers") or 0) > 0:
        return GateDecision(allowed=False, reason="acute_risk_defer", mode=None)

    cohort = ((enrollment or {}).get("cohort_label") or "").lower()
    sensitive = int(evidence.get("dissociation_markers") or 0) > 0 or any(
        k in cohort for k in ("did", "dissociat", "complex", "structural"))
    if sensitive:
        if not enrollment:
            return GateDecision(allowed=False, reason="sensitive_requires_enrollment", mode=None)
        # Only clinician-APPROVED parts may be echoed (PENDING_APPROVAL / HOLD / REJECTED never leak into a panel).
        active_parts = [p for p in (parts_registry or [])
                        if p.get("is_active", True)
                        and str(p.get("coaching_status") or "APPROVED").upper() == "APPROVED"]
        if not active_parts:
            return GateDecision(allowed=False, reason="sensitive_requires_parts_registry", mode=None)
        return GateDecision(allowed=True, reason="sensitive_registry_aligned", mode="registry_aligned",
                            registry_parts=[p.get("part_name") for p in active_parts])
    return GateDecision(allowed=True, reason="ok", mode="full")


# ---------------------------------------------------------------------------
# Stage 2 — hypothesis synthesis
# ---------------------------------------------------------------------------

def _hyp_id(user_id: str, category: str, salt: str = "") -> str:
    return hashlib.sha1(f"{user_id}|{category}|{salt}".encode("utf-8")).hexdigest()[:12]


def rank_candidates(evidence: dict, dynamics: Optional[dict] = None,
                    behavior: Optional[dict] = None, priors: Optional[Dict[str, float]] = None,
                    allowed_categories: Iterable[str] = FIGURE_CATEGORIES) -> List[Dict[str, Any]]:
    """Score every figure-eligible category. Confidence = prior × blended
    likelihood, capped at CONFIDENCE_CAP; candidates failing the channel /
    session floors are returned with ``eligible=False`` (for transparency)."""
    priors = priors or {c: 0.6 for c in FIGURE_CATEGORIES}
    scores = evidence.get("part_scores") or {}
    sessions_by = evidence.get("sessions_by_category") or {}
    channels_by = evidence.get("channels_by_category") or {}
    dyn_active = bool((dynamics or {}).get("active"))
    beh_active = bool((behavior or {}).get("active"))
    out: List[Dict[str, Any]] = []
    for cat in allowed_categories:
        lex = float(scores.get(cat, 0.0))
        if lex <= 0:
            continue
        sessions = set(sessions_by.get(cat, []))
        channels = set(channels_by.get(cat, [])) or {"lexical"}
        # crystals count as a distinct lexical sub-channel; dynamics / behaviour / prior are separate channels
        channels = {"lexical" if c in ("lexical", "chat", "crystal") else c for c in channels}
        if dyn_active:
            channels.add("dynamic")
        if beh_active:
            channels.add("behavioral")
        prior = float(priors.get(cat, 0.6))
        if prior >= 0.8:
            channels.add("prior")
        likelihood = min(1.0, lex / 6.0)
        sess_factor = min(1.0, len(sessions) / 5.0)
        chan_factor = min(1.0, len(channels) / 4.0)
        blended = 0.5 * likelihood + 0.3 * sess_factor + 0.2 * chan_factor
        conf = round(min(CONFIDENCE_CAP, prior * blended), 3)
        eligible = len(channels) >= MIN_CHANNELS and len(sessions) >= MIN_SESSIONS
        out.append({
            "category": cat, "lexical_score": lex, "sessions": sorted(sessions),
            "channels": sorted(channels), "prior": prior, "confidence": conf,
            "eligible": eligible,
        })
    out.sort(key=lambda c: (c["eligible"], c["confidence"], c["lexical_score"]), reverse=True)
    return out


_SYNTH_SYSTEM = (
    "You are Little Nate, a therapeutic companion who is allowed to WONDER but never to diagnose. "
    "From the evidence excerpts below, form ONE tentative hypothesis about an unnamed internal figure "
    "(Internal Family Systems language: a protector, manager, firefighter or exile; or an attachment "
    "stance). This is a question Nate is holding, not a fact about the person.\n\n"
    "Return JSON only, no markdown, with exactly these keys:\n"
    '{"name": "<a fresh 2-5 word title starting with the, drawn from your own proposed_form '
    '(a noun phrase, never a verb phrase, never a clinical word, never a generic example)>", '
    '"role": "<2-6 words, what this figure seems to do>", '
    '"protects_from": "<what pain it may be guarding>", '
    '"trigger_pattern": "<when it seems to step forward>", '
    '"affect_signature": "<the felt tone it carries>", '
    '"stance": "<one of: vigilant, controlling, fleeing, hidden, pursuing, withdrawing, oscillating>", '
    '"proposed_form": "<a metaphoric, non-animal, non-violent visual form in <= 22 words, painterly, '
    'no face detail, no real person, no child>", '
    '"question": "<one gentle question Nate would ask the person, starting with I wonder or I keep noticing>"}\n'
    "Rules: never use the words diagnosis, disorder, trauma, abuse, or any clinical label. "
    "Never assert — hedge everything. Never describe the person; describe the figure."
)

_FALLBACK_HYPOTHESES: Dict[str, Dict[str, str]] = {
    "protector_watch": {
        "role": "keeps watch so nothing arrives unannounced",
        "protects_from": "being caught off guard by someone turning away",
        "trigger_pattern": "when a voice goes quiet or a face is hard to read",
        "affect_signature": "tight, alert, quietly exhausted",
        "stance": "vigilant",
        "proposed_form": "a cloaked watcher standing at the treeline, half-turned toward the path, lantern unlit",
        "question": "I keep noticing something in you that stays awake when the room goes quiet — I wonder what it is listening for.",
    },
    "manager": {
        "role": "keeps everything arranged before it can fall",
        "protects_from": "the feeling of having let someone down",
        "trigger_pattern": "when a plan slips or someone else is counting on them",
        "affect_signature": "brisk, braced, rarely still",
        "stance": "controlling",
        "proposed_form": "a tall figure in a long coat straightening stones along the path, back to the viewer",
        "question": "I wonder who taught the part of you that keeps every stone in line that resting was not allowed.",
    },
    "firefighter": {
        "role": "puts the fire out by leaving the room",
        "protects_from": "a feeling that arrives too fast to hold",
        "trigger_pattern": "right after the sting, before anyone can see it",
        "affect_signature": "sudden, hot, then hollow",
        "stance": "fleeing",
        "proposed_form": "a running shape at the far edge of the field, scarf streaming, already half into the mist",
        "question": "I keep noticing a quick exit that shows up right after the sting — I wonder what it is trying to spare you.",
    },
    "exile": {
        "role": "holds the oldest ache out of sight",
        "protects_from": "nothing — it is the one being protected",
        "trigger_pattern": "when being unseen starts to feel familiar",
        "affect_signature": "small, quiet, waiting",
        "stance": "hidden",
        "proposed_form": "a low glow under a weathered boat hull on the shore, as if someone small is sheltering there",
        "question": "I wonder about a quiet place in you that learned to wait a very long time without asking.",
    },
    "anxious_pursue": {
        "role": "listens for footsteps leaving",
        "protects_from": "the silence after someone goes quiet",
        "trigger_pattern": "when a reply is late or a tone changes",
        "affect_signature": "reaching, breath held",
        "stance": "pursuing",
        "proposed_form": "a figure on a pier leaning toward the water, one hand shading its eyes, lantern held out over the waves",
        "question": "I keep noticing how carefully you read silences — I wonder what the quiet has meant before.",
    },
    "avoidant_withdraw": {
        "role": "closes the door before it can be closed on them",
        "protects_from": "needing someone who might not stay",
        "trigger_pattern": "when closeness arrives faster than trust",
        "affect_signature": "cool, composed, far away",
        "stance": "withdrawing",
        "proposed_form": "a gatekeeper at a garden wall, easing the gate shut without a sound, key kept close",
        "question": "I wonder what the part of you that steps back first has decided about staying.",
    },
    "disorganized": {
        "role": "reaches and retreats in the same motion",
        "protects_from": "closeness that once meant danger",
        "trigger_pattern": "when warmth and threat arrive together",
        "affect_signature": "flickering, unsure which way is safe",
        "stance": "oscillating",
        "proposed_form": "a figure caught mid-step between two lit doorways, shadow pointing both ways",
        "question": "I keep noticing a step toward and a step back — I wonder if both of them are trying to keep you safe.",
    },
}

_REQUIRED_KEYS = ("role", "protects_from", "trigger_pattern", "affect_signature", "stance", "proposed_form", "question")
_CLINICAL_BAN = re.compile(r"\b(diagnos\w*|disorder|trauma\w*|abus\w*|borderline|narciss\w*|ptsd|did\b|bipolar|psychot\w*)", re.I)


def _evidence_excerpts(evidence: dict, category: str, limit: int = 8) -> str:
    rows = [h for h in (evidence.get("hits") or []) if h.get("category") == category][:limit]
    return "\n".join(f"- [{h.get('channel')}/{h.get('session_id')}] …{h.get('excerpt')}…" for h in rows)


async def synthesize_hypothesis(user_id: str, evidence: dict, candidate: dict,
                                dynamics: Optional[dict] = None,
                                llm: Optional[Callable] = None,
                                registry_parts: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Stage 2 — turn the top eligible candidate into a structured hypothesis.
    Uses the LLM (strict JSON, temperature 0.3) when available; otherwise the
    per-category template. Output is validated; clinical labels are rejected."""
    if not candidate or not candidate.get("eligible"):
        return None
    cat = candidate["category"]
    payload: Optional[Dict[str, Any]] = None
    if llm is not None:
        dyn_txt = ""
        if dynamics and dynamics.get("drops"):
            dyn_txt = "\nCoherence drops (emotional activation events):\n" + "\n".join(
                f"- {d['from']}→{d['to']} while discussing: {d.get('topic') or 'unknown'}" for d in dynamics["drops"][:4])
        reg_txt = ""
        if registry_parts:
            reg_txt = ("\nClinician-registered parts for this person (your hypothesis MUST align with one of these names, "
                       f"do not invent a new figure): {', '.join(registry_parts)}\n")
        user_msg = (
            f"Evidence category: {cat} ({CATEGORY_LABELS.get(cat, cat)})\n"
            f"Distinct sessions: {len(candidate.get('sessions') or [])}; channels: {', '.join(candidate.get('channels') or [])}\n"
            f"Excerpts:\n{_evidence_excerpts(evidence, cat)}{dyn_txt}{reg_txt}\n\nReturn the JSON now."
        )
        try:
            raw = await llm([{"role": "system", "content": _SYNTH_SYSTEM},
                             {"role": "user", "content": user_msg}], max_tokens=420, temperature=0.3)
            if raw:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    cand = json.loads(m.group())
                    if all(k in cand and str(cand[k]).strip() for k in _REQUIRED_KEYS):
                        blob = " ".join(str(cand[k]) for k in _REQUIRED_KEYS)
                        if not _CLINICAL_BAN.search(blob):
                            payload = {k: str(cand[k]).strip() for k in _REQUIRED_KEYS}
                            payload["source"] = "llm"
                            nm = _clean_name(str(cand.get("name") or ""))
                            if nm:
                                payload["name"] = nm
                        else:
                            logger.info("APHL: LLM hypothesis rejected (clinical label) for %s", user_id)
        except Exception as e:  # noqa: BLE001 — the template is the contract, the LLM is optional
            logger.warning("APHL: LLM synthesis failed for %s: %s", user_id, e)
    if payload is None:
        payload = dict(_FALLBACK_HYPOTHESES[cat])
        payload["source"] = "template"
    payload["question"] = soften_assertion(payload["question"])
    hyp = {
        "hypothesis_id": _hyp_id(user_id, cat, payload["role"]),
        "category": cat,
        "confidence": float(candidate["confidence"]),
        "channels": list(candidate.get("channels") or []),
        "sessions": list(candidate.get("sessions") or []),
        "evidence_refs": [h.get("ref") for h in (evidence.get("hits") or []) if h.get("category") == cat][:12],
        "provenance": PROVENANCE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "proposed",
        **payload,
    }
    return hyp


# ---------------------------------------------------------------------------
# Stage 3 — metaphoric form selection with symbol safety (pure)
# ---------------------------------------------------------------------------

FORM_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "protector_watch": [
        {"form_id": "treeline_watcher", "name": "the Watcher at the Treeline",
         "visual_prompt_fragment": "a cloaked watcher standing far back at the treeline, half-turned toward the path, unlit lantern at its side, face unreadable in shadow", "symbol_id": None},
        {"form_id": "ridge_sentinel", "name": "the Ridge Sentinel",
         "visual_prompt_fragment": "a tall still silhouette on the far ridge keeping watch over the valley, cloak moving slightly in the wind", "symbol_id": None},
        {"form_id": "owl_watcher", "name": "the Night Watcher",
         "visual_prompt_fragment": "a pale owl perched high on a dead branch, watching the path", "symbol_id": "owl"},
    ],
    "manager": [
        {"form_id": "stone_setter", "name": "the Stone-Setter",
         "visual_prompt_fragment": "a tall figure in a long coat straightening stacked stones along the path, back to the viewer, every stone level", "symbol_id": None},
        {"form_id": "map_keeper", "name": "the Map-Keeper",
         "visual_prompt_fragment": "a figure at a distant table under a canopy, folding and refolding a large map by lamplight", "symbol_id": None},
    ],
    "firefighter": [
        {"form_id": "far_runner", "name": "the Far Runner",
         "visual_prompt_fragment": "a running shape at the far edge of the field, scarf streaming behind it, already half dissolved into the mist", "symbol_id": None},
        {"form_id": "ember_dowser", "name": "the Ember-Dowser",
         "visual_prompt_fragment": "a figure tipping a pail of water over a small campfire, steam rising, turned away from the camp", "symbol_id": None},
    ],
    "exile": [
        {"form_id": "hull_glow", "name": "the Light Under the Hull",
         "visual_prompt_fragment": "a soft warm glow beneath an overturned weathered boat on the shore, as if someone small is sheltering there, unseen", "symbol_id": None},
        {"form_id": "blanket_shape", "name": "the Shape by the Hearth",
         "visual_prompt_fragment": "a small bundled shape wrapped in a blanket at the far edge of the firelight, face hidden, very still", "symbol_id": None},
    ],
    "anxious_pursue": [
        {"form_id": "pier_lantern", "name": "the Lantern on the Pier",
         "visual_prompt_fragment": "a figure at the end of a long pier leaning toward the water, holding a lantern out over the waves, listening", "symbol_id": None},
        {"form_id": "bell_keeper", "name": "the Bell-Keeper",
         "visual_prompt_fragment": "a figure beside a small weathered bell tower, hand resting on the silent bell, waiting for a sound from the road", "symbol_id": None},
    ],
    "avoidant_withdraw": [
        {"form_id": "garden_gatekeeper", "name": "the Gatekeeper",
         "visual_prompt_fragment": "a gatekeeper at a mossy garden wall easing a wooden gate shut without a sound, an iron key held close", "symbol_id": None},
        {"form_id": "far_shore_figure", "name": "the Far-Shore Figure",
         "visual_prompt_fragment": "a solitary figure on the opposite shore of a still lake, standing where the path ends, not waving", "symbol_id": None},
    ],
    "disorganized": [
        {"form_id": "two_doorways", "name": "the Figure Between Doorways",
         "visual_prompt_fragment": "a figure caught mid-step between two lit doorways in a stone wall, its shadow pointing both ways", "symbol_id": None},
        {"form_id": "tide_walker", "name": "the Tide-Walker",
         "visual_prompt_fragment": "a figure walking the exact line where the tide meets the sand, stepping forward and back with each wave", "symbol_id": None},
    ],
}

# Hard denylist for any LLM-proposed form (independent of the symbol registry).
_FORM_DENY = re.compile(
    r"\b(blood|gore|wound|weapon|knife|blade|gun|rifle|noose|rope|chain|cage|mask|mirror|skull|bones?|"
    r"naked|nude|child|children|kid|baby|infant|toddler|boy|girl|corpse|dead body|hanging|"
    r"cat|dog|wolf|owl|fox|snake|serpent|spider|bat|crow|raven|dragon|pig|boar|cow|fish|butterfly|"
    r"clock|labyrinth|maze|cross|crescent|halo|altar|temple|rose|thorn|lily|chrysanthemum|willow|eclipse|moon)\b",
    re.I,
)
_HUMAN_TARGET = re.compile(r"\b(the (user|client|person)|you|your)\b", re.I)


def screen_form_text(text: str, excluded_aliases: Iterable[str] = ()) -> Tuple[bool, str]:
    """Deterministic safety screen for an LLM-proposed visual form."""
    t = (text or "").strip()
    if not t or len(t) > 200:
        return False, "length"
    if _FORM_DENY.search(t):
        return False, "denylist"
    if _HUMAN_TARGET.search(t):
        return False, "describes_person"
    low = t.lower()
    for alias in excluded_aliases:
        a = (alias or "").strip().lower()
        if a and re.search(rf"\b{re.escape(a)}\b", low):
            return False, f"excluded_symbol:{a}"
    return True, "ok"


def _excluded_aliases(posture: Optional[Dict[str, str]]) -> List[str]:
    """Aliases of every registry symbol not opted-in for this user (fail-open if
    the registry cannot be loaded)."""
    out: List[str] = []
    try:
        from app.sse.symbol_safety import get_symbol, all_symbol_ids
        for sid in all_symbol_ids():
            state = (posture or {}).get(sid, "excluded")
            if state in ("opted_in", "opted_in_literal"):
                continue
            sym = get_symbol(sid) or {}
            out.extend([sid.replace("_", " ")] + list(sym.get("aliases") or []))
    except Exception:  # noqa: BLE001
        pass
    return out


def select_form(hypothesis: dict, posture: Optional[Dict[str, str]] = None,
                variety_seed: int = 0, allow_llm_form: bool = True) -> Dict[str, Any]:
    """Pick the figure's visual form. The LLM proposal is used only if it passes
    the deterministic screen; otherwise a catalog form whose registry symbol (if
    any) is opted-in. Returns a dict with form_id/name/visual_prompt_fragment/source."""
    cat = hypothesis.get("category", "")
    aliases = _excluded_aliases(posture)
    if allow_llm_form and hypothesis.get("proposed_form"):
        ok, why = screen_form_text(hypothesis["proposed_form"], aliases)
        if ok:
            return {"form_id": f"llm_{hypothesis.get('hypothesis_id', '')}",
                    "name": (_clean_name(hypothesis.get("name", ""))
                             or _name_from_form(hypothesis.get("proposed_form", ""))
                             or _name_from_role(hypothesis.get("role", ""))),
                    "visual_prompt_fragment": hypothesis["proposed_form"].rstrip(".") + ", at a respectful distance from the protagonist, painterly, soft edges",
                    "symbol_id": None, "source": "llm", "screen": why}
        logger.info("APHL: LLM-proposed form rejected (%s); using catalog", why)
    options = []
    for f in FORM_CATALOG.get(cat, []):
        sid = f.get("symbol_id")
        if sid and (posture or {}).get(sid, "excluded") not in ("opted_in", "opted_in_literal"):
            continue
        ok, _ = screen_form_text(f["visual_prompt_fragment"], aliases) if sid is None else (True, "catalog")
        if ok:
            options.append(f)
    if not options:
        return {"form_id": "abstract_presence", "name": "a Presence at the Edge",
                "visual_prompt_fragment": "a faint warm presence at the far edge of the scene, more light than figure, kept at a distance",
                "symbol_id": None, "source": "abstract_fallback", "screen": "no_catalog_option"}
    pick = options[variety_seed % len(options)]
    return {**pick, "source": "catalog", "screen": "ok"}


_CATALOG_NAMES = {
    f["name"].lower().removeprefix("the ").strip()
    for forms in FORM_CATALOG.values() for f in forms
}
_NAME_STOP = {"the", "a", "an", "so", "that", "who", "which", "and", "of"}
_NAME_PREPS = {"at", "in", "on", "by", "near", "beside", "along", "above", "below", "under", "over", "behind", "beyond"}


def _clean_name(name: str) -> str:
    """Validate an LLM-proposed figure title: 2-5 words, noun-ish, no clinical/denylist words."""
    raw = re.sub(r"[^a-zA-Z' -]", "", name or "").strip()
    if not raw:
        return ""
    words = raw.split()
    if words and words[0].lower() == "the":
        words = words[1:]
    if not (1 <= len(words) <= 6):
        return ""
    if words[0].lower().endswith("s") and len(words) > 1 and words[0].lower() not in ("glass", "moss", "mist", "mass", "bass"):
        # leading third-person verb ("Scans For Sudden") → reject
        return ""
    joined = " ".join(words)
    if _CLINICAL_BAN.search(joined) or _FORM_DENY.search(joined) or _HUMAN_TARGET.search(joined):
        return ""
    if joined.lower() in _CATALOG_NAMES:
        # an LLM echoing a catalog title is not a fresh figure — fall back to form-derived naming
        return ""
    return "the " + " ".join(w if w.lower() in _NAME_PREPS or w.lower() in _NAME_STOP else w.capitalize() for w in words)


def _name_from_form(form_text: str) -> str:
    """Derive a title from the visual form: 'a faint haze lingering at the clearing edge'
    → 'the Faint Haze at the Clearing Edge'."""
    seg = re.sub(r"[^a-zA-Z' -]", "", (form_text or "").split(",")[0]).strip().split()
    if not seg:
        return ""
    if seg[0].lower() in ("a", "an", "the"):
        seg = seg[1:]
    head: List[str] = []
    rest: List[str] = []
    for i, w in enumerate(seg):
        if w.lower().endswith("ing") or w.lower() in _NAME_PREPS:
            rest = seg[i:]
            break
        head.append(w)
    head = head[:3]
    if not head:
        return ""
    loc: List[str] = []
    for i, w in enumerate(rest):
        if w.lower() in _NAME_PREPS and i + 1 < len(rest):
            tail = rest[i + 1:]
            if tail and tail[0].lower() in ("the", "a", "an"):
                tail = tail[1:]
            tail = tail[:3]
            if tail:
                loc = [w.lower(), "the"] + tail
            break
    title = " ".join(w.capitalize() for w in head)
    if loc:
        title += " " + " ".join(loc[:2] + [t.capitalize() for t in loc[2:]])
    return _clean_name("the " + title) or ""


def _name_from_role(role: str) -> str:
    words = [w for w in re.sub(r"[^a-zA-Z ]", "", role or "").split() if w.lower() not in _NAME_STOP]
    core = " ".join(w.capitalize() for w in words[:3]) or "Unnamed Figure"
    return f"the {core}"


# ---------------------------------------------------------------------------
# Stage 4 — interrogative phrasing + composer block (pure)
# ---------------------------------------------------------------------------

_ASSERTIVE = [
    (re.compile(r"\byour (inner )?(protector|manager|firefighter|exile|inner child|wounded child|part)\b", re.I),
     r"a figure that may be a \2"),
    (re.compile(r"\byou are (avoidant|anxious|disorganized|insecure|dissociative|hypervigilant)\b", re.I),
     r"I wonder if something in you leans \1"),
    (re.compile(r"\bthis is your\b", re.I), "this might be"),
    (re.compile(r"\byou have a (part|protector)\b", re.I), r"there may be a \1"),
]
_HEDGE_OPENERS = ("i wonder", "i keep noticing", "i notice", "maybe", "perhaps", "it may be", "it might be", "could it be")


def soften_assertion(text: str) -> str:
    """Rewrite assertive parts-language into a wondering. Guarantees a hedge opener."""
    t = (text or "").strip()
    for pat, repl in _ASSERTIVE:
        t = pat.sub(repl, t)
    if t and not t.lower().startswith(_HEDGE_OPENERS):
        t = "I wonder — " + t[0].lower() + t[1:]
    return t


def is_interrogative(text: str) -> bool:
    low = (text or "").strip().lower()
    return low.startswith(_HEDGE_OPENERS) and not any(p.search(low) for p, _ in _ASSERTIVE)


def hypothesis_block(npcs: Sequence[dict]) -> str:
    """Composer system-prompt block. Distinct from RECURRING COMPANIONS: this
    figure is tentative, distant, and phrased as Nate's own wondering."""
    rows = [n for n in (npcs or []) if n.get("provenance") == PROVENANCE and n.get("name")]
    if not rows:
        return ""
    lines = "\n".join(
        f"- {n['name']}: {n.get('visual_prompt_fragment', '')}\n  Nate's quiet question: {n.get('question', '')}"
        for n in rows)
    return (
        "A FIGURE NATE IS WONDERING ABOUT (tentative — this is Little Nate's own curiosity, NOT a confirmed "
        "truth about the user, and NOT a recurring companion):\n"
        f"{lines}\n"
        "Rules for this figure: it appears once, at a distance, never touching or addressing the protagonist. "
        "In narrative_text refer to it only as a wondering — 'I keep noticing a figure…', 'I wonder if…'. "
        "Never call it the user's part, protector, or child; never name a diagnosis. The protagonist may notice it "
        "or not. It MUST appear in image_prompt exactly as described.\n"
    )


def npc_from_hypothesis(hyp: dict, form: dict) -> Dict[str, Any]:
    """Shape a hypothesis into the engine's NPC contract (name/role/visual_prompt_fragment)."""
    return {
        "name": form.get("name") or _name_from_role(hyp.get("role", "")),
        "role": f"a figure Nate is wondering about — {hyp.get('role', '')}".strip(),
        "visual_prompt_fragment": form.get("visual_prompt_fragment", ""),
        "domain": "hypothesis",
        "provenance": PROVENANCE,
        "hypothesis_id": hyp.get("hypothesis_id"),
        "category": hyp.get("category"),
        "confidence": hyp.get("confidence"),
        "question": hyp.get("question", ""),
        "form_source": form.get("source"),
        "appearances": 0,
    }


def legend_entry(npc: dict, coach_view: bool = False) -> Dict[str, Any]:
    """Legend / Codex entry for a hypothesis figure. ``clinical_translation`` is
    coach-only and never rendered in the client Legend."""
    entry = {
        "symbol_id": f"hypothesis:{npc.get('hypothesis_id', '')}",
        "display_name": npc.get("name", "a figure"),
        "tier": "inferred",
        "state": "proposed",
        "role": "A figure Nate is wondering about",
        "meaning": (npc.get("question") or "I keep noticing this figure and I am not sure yet what it means for you."),
        "is_core": False,
        "seen_before": int(npc.get("appearances", 0)) > 1,
        "figure_in_panel": npc.get("visual_prompt_fragment", ""),
        "provenance": PROVENANCE,
        "actions": ["tell me more", "that's not me", "that fits"],
    }
    if coach_view:
        entry["clinical_translation"] = {
            "category": npc.get("category"),
            "confidence": npc.get("confidence"),
            "role": npc.get("role"),
        }
    return entry


# ---------------------------------------------------------------------------
# Stage 5 — engagement / calibration (pure + persist helper)
# ---------------------------------------------------------------------------

ENGAGEMENT_KINDS = ("engaged", "confirmed", "banished", "ignored", "held", "reproposed")
# Client-facing verbs (Legend buttons) → ledger kinds
ENGAGEMENT_ALIASES = {
    "confirm": "confirmed", "that fits": "confirmed", "fits": "confirmed",
    "banish": "banished", "that's not me": "banished", "not me": "banished", "not_me": "banished",
    "curious": "engaged", "tell me more": "engaged", "more": "engaged", "engage": "engaged",
}


def apply_engagement(registry: Dict[str, dict], ledger: List[dict], hypothesis_id: str,
                     kind: str, note: str = "") -> Tuple[Dict[str, dict], List[dict]]:
    kind = ENGAGEMENT_ALIASES.get(str(kind).strip().lower(), str(kind).strip().lower())
    if kind not in ENGAGEMENT_KINDS:
        raise ValueError(f"unknown engagement kind {kind}")
    hyp = registry.get(hypothesis_id)
    if not hyp:
        return registry, ledger
    now = datetime.now(timezone.utc).isoformat()
    if kind == "confirmed":
        hyp["status"] = "confirmed"
        hyp["confirmed_at"] = now
    elif kind == "banished":
        hyp["status"] = "banished"
        hyp["banished_at"] = now
    elif kind == "engaged":
        hyp["status"] = "engaged"
        hyp["engaged_at"] = now
    elif kind == "held":
        # coach HOLD: figure stays out of panels until the coach decides (not a banish — no cooldown)
        hyp["status"] = "held"
        hyp["held_at"] = now
    elif kind == "reproposed":
        hyp["status"] = "proposed"
        hyp["reproposed_at"] = now
    else:
        hyp["ignored_count"] = int(hyp.get("ignored_count", 0)) + 1
        if hyp["ignored_count"] >= 3:
            hyp["status"] = "retired"
    ledger = list(ledger) + [{"hypothesis_id": hypothesis_id, "category": hyp.get("category"),
                              "kind": kind, "note": note[:280], "at": now}]
    return registry, ledger


def _banished_recently(registry: Dict[str, dict], category: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    for h in registry.values():
        if h.get("category") != category or h.get("status") != "banished":
            continue
        try:
            at = datetime.fromisoformat(h.get("banished_at"))
        except Exception:  # noqa: BLE001
            return True
        if (now - at).days < BANISH_COOLDOWN_DAYS:
            return True
    return False


def choose_todays_figure(registry: Dict[str, dict], panel_sequence: int) -> Optional[dict]:
    """Cadence + lifecycle: return the active hypothesis that may appear today, or None."""
    active = [h for h in registry.values() if h.get("status") in ("proposed", "engaged", "confirmed")]
    if not active:
        return None
    active.sort(key=lambda h: h.get("created_at") or "", reverse=True)
    h = active[0]
    last = h.get("last_shown_seq")
    if last is not None and (panel_sequence - int(last)) < SHOW_EVERY_N_PANELS and h.get("status") != "engaged":
        return None
    return h


# ---------------------------------------------------------------------------
# DB collectors (each wrapped; the loop degrades to "no evidence" on failure)
# ---------------------------------------------------------------------------

async def collect_evidence(user_id: str, db_pool, username: str = "") -> Dict[str, Any]:
    """Gather the four channels for one user. Returns a bundle consumed by the
    pure functions above: texts, c_emo samples, behaviour samples, presenting
    concern, enrollment, parts registry, posture inputs."""
    ids = [i for i in {user_id, username} if i]
    bundle: Dict[str, Any] = {"texts": [], "c_emo": [], "behavior": [], "presenting_concern": "",
                              "enrollment": None, "parts_registry": [], "cultural_context": "",
                              "spiritual_framework": "", "resolved_username": username or "",
                              "safety": {k: False for k in SAFETY_DEFERRALS}}
    if db_pool is None or not ids:
        return bundle
    try:
        async with db_pool.acquire() as conn:
            urow = None
            try:
                urow = await conn.fetchrow(
                    "SELECT id, username FROM users WHERE hardware_id = ANY($1::text[]) OR username = ANY($1::text[]) LIMIT 1", ids)
            except Exception as e:  # noqa: BLE001
                logger.warning("APHL: user resolve failed for %s: %s", user_id, e)
            uuid = urow["id"] if urow else None
            if urow and urow.get("username"):
                bundle["resolved_username"] = urow["username"]
                if urow["username"] not in ids:
                    ids.append(urow["username"])
            try:
                rows = await conn.fetch(
                    "SELECT id, session_id, user_text, created_at FROM conversation_history "
                    "WHERE user_id = ANY($1::text[]) AND created_at > NOW() - INTERVAL '90 days' "
                    "AND LENGTH(user_text) > 12 ORDER BY created_at DESC LIMIT 400", ids)
                for r in rows:
                    bundle["texts"].append({"text": r["user_text"], "session_id": r["session_id"] or (r["created_at"].date().isoformat() if r["created_at"] else None),
                                            "channel": "lexical", "ts": r["created_at"].isoformat() if r["created_at"] else None,
                                            "ref": f"conv:{r['id']}"})
            except Exception as e:  # noqa: BLE001
                logger.warning("APHL: conversation_history fetch failed for %s: %s", user_id, e)
            if uuid is not None:
                try:
                    rows = await conn.fetch(
                        "SELECT id, crystal_text, created_at FROM nate_intelligence_crystals "
                        "WHERE user_id = $1 AND scope <> 'archived' AND superseded_by IS NULL "
                        "ORDER BY created_at DESC LIMIT 60", uuid)
                    for r in rows:
                        bundle["texts"].append({"text": r["crystal_text"], "session_id": None, "channel": "crystal",
                                                "ts": r["created_at"].isoformat() if r["created_at"] else None,
                                                "ref": f"crystal:{r['id']}"})
                except Exception as e:  # noqa: BLE001
                    logger.warning("APHL: crystal fetch failed for %s: %s", user_id, e)
                try:
                    rows = await conn.fetch(
                        "SELECT c_emo, recorded_at, session_id FROM nevedal_metrics WHERE user_id = $1 "
                        "AND recorded_at > NOW() - INTERVAL '90 days' ORDER BY recorded_at ASC LIMIT 300", uuid)
                    bundle["c_emo"] = [{"c_emo": r["c_emo"], "session_id": str(r["session_id"] or (r["recorded_at"].date() if r["recorded_at"] else "")),
                                        "topic": ""} for r in rows]
                except Exception as e:  # noqa: BLE001
                    logger.warning("APHL: nevedal_metrics fetch failed for %s: %s", user_id, e)
                try:
                    rows = await conn.fetch(
                        "SELECT call_sid, payload FROM voice_session_biometrics WHERE user_uuid = $1 "
                        "ORDER BY created_at DESC LIMIT 20", uuid)
                    for r in rows:
                        p = r["payload"] if isinstance(r["payload"], dict) else (json.loads(r["payload"]) if r["payload"] else {})
                        bundle["behavior"].append({"session_id": r["call_sid"], "pause_ratio": p.get("pause_ratio")})
                except Exception as e:  # noqa: BLE001
                    logger.warning("APHL: biometrics fetch failed for %s: %s", user_id, e)
            try:
                frow = await conn.fetchrow(
                    "SELECT presenting_concern, cultural_context, spiritual_framework FROM sse_identity_forge "
                    "WHERE user_id = ANY($1::text[]) LIMIT 1", ids)
                if frow:
                    bundle["presenting_concern"] = frow["presenting_concern"] or ""
                    bundle["cultural_context"] = frow["cultural_context"] or ""
                    bundle["spiritual_framework"] = frow["spiritual_framework"] or ""
            except Exception as e:  # noqa: BLE001
                logger.warning("APHL: identity forge fetch failed for %s: %s", user_id, e)
            uname = bundle["resolved_username"] or username or user_id
            try:
                erow = await conn.fetchrow(
                    "SELECT cohort_label FROM sensitive_bridge_enrollment WHERE user_id = $1 LIMIT 1", uname)
                if erow:
                    bundle["enrollment"] = {"cohort_label": erow["cohort_label"]}
            except Exception as e:  # noqa: BLE001
                logger.info("APHL: enrollment lookup skipped for %s: %s", user_id, e)
            try:
                rows = await conn.fetch(
                    "SELECT id, part_name, part_category, is_active, coaching_status, origin "
                    "FROM user_parts_registry WHERE user_id = $1", uname)
                bundle["parts_registry"] = [dict(r) for r in rows]
            except Exception as e:  # noqa: BLE001
                logger.info("APHL: parts registry lookup skipped for %s: %s", user_id, e)
            bundle["safety"] = await collect_safety(conn, uname, ids, bundle["parts_registry"],
                                                    enrolled=bundle["enrollment"] is not None)
    except Exception as e:  # noqa: BLE001
        logger.warning("APHL: evidence collection failed for %s: %s", user_id, e)
    return bundle


# ---------------------------------------------------------------------------
# Sensitive Bridge guardrails (collected per run; every probe degrades to False)
# ---------------------------------------------------------------------------

SAFE_SILENCE_HOURS = 72
TRIGGER_DATE_WINDOW_DAYS = 3
CRISIS_LOOKBACK_DAYS = 14


def trigger_date_active(rows: Iterable[dict], today: Optional[datetime] = None,
                        window_days: int = TRIGGER_DATE_WINDOW_DAYS) -> bool:
    """Pure: True when any registered trigger date (or its yearly anniversary when
    ``recurring_annually``) falls within ±window_days of today."""
    today_d = (today or datetime.now(timezone.utc)).date()
    for r in rows or []:
        td = r.get("trigger_date")
        if td is None:
            continue
        if isinstance(td, datetime):
            td = td.date()
        elif isinstance(td, str):
            try:
                td = datetime.fromisoformat(td[:10]).date()
            except Exception:  # noqa: BLE001
                continue
        if abs((td - today_d).days) <= window_days:
            return True
        if r.get("recurring_annually"):
            for year in (today_d.year - 1, today_d.year, today_d.year + 1):
                try:
                    anniv = td.replace(year=year)
                except ValueError:  # Feb 29
                    anniv = td.replace(year=year, day=28)
                if abs((anniv - today_d).days) <= window_days:
                    return True
    return False


def ifs_lens_disabled(profile_data: Any, enrolled: bool) -> bool:
    """Pure: Sensitive Bridge framework menu with IFS explicitly off. Non-enrolled
    users have no menu, so this never fires for them."""
    if not enrolled:
        return False
    pd = profile_data
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:  # noqa: BLE001
            return False
    if not isinstance(pd, dict):
        return False
    menu = ((pd.get("sensitive_bridge") or {}).get("framework_preferences")) if isinstance(pd.get("sensitive_bridge"), dict) else None
    if not isinstance(menu, dict):
        return False
    enabled = menu.get("enabled_frameworks")
    if enabled is None:
        enabled = menu.get("enabled_lenses")
    if isinstance(enabled, dict):
        return "ifs" in enabled and not bool(enabled.get("ifs"))
    if isinstance(enabled, list):
        return len(enabled) > 0 and "ifs" not in {str(x) for x in enabled}
    if "ifs" in menu:
        return not bool(menu.get("ifs"))
    return False


async def collect_safety(conn, username: str, ids: Sequence[str], parts_registry: List[dict],
                         enrolled: bool = False) -> Dict[str, bool]:
    """Probe the Sensitive Bridge surfaces that must silence Nate's wondering.
    Each probe is isolated; a missing table simply leaves the flag False."""
    safety: Dict[str, bool] = {k: False for k in SAFETY_DEFERRALS}
    if not username:
        return safety
    try:
        hit = await conn.fetchval(
            "SELECT 1 FROM sensitive_bridge_log WHERE user_id = $1 AND event_type LIKE 'codeword_triggered%' "
            "AND occurred_at > NOW() - ($2::int * INTERVAL '1 hour') LIMIT 1", username, SAFE_SILENCE_HOURS)
        safety["safe_silence_active"] = bool(hit)
    except Exception as e:  # noqa: BLE001
        logger.info("APHL: safe-silence probe skipped for %s: %s", username, e)
    try:
        rows = await conn.fetch(
            "SELECT trigger_date, recurring_annually FROM user_trigger_dates WHERE user_id = $1", username)
        safety["trigger_date_active"] = trigger_date_active([dict(r) for r in rows])
    except Exception as e:  # noqa: BLE001
        logger.info("APHL: trigger-date probe skipped for %s: %s", username, e)
    try:
        hit = await conn.fetchval(
            "SELECT 1 FROM crisis_events WHERE (user_name = $1 OR hardware_id = ANY($2::text[])) "
            "AND COALESCE(resolved, FALSE) = FALSE "
            "AND COALESCE(created_at, timestamp) > NOW() - ($3::int * INTERVAL '1 day') LIMIT 1",
            username, list(ids), CRISIS_LOOKBACK_DAYS)
        safety["crisis_recent"] = bool(hit)
    except Exception as e:  # noqa: BLE001
        logger.info("APHL: crisis probe skipped for %s: %s", username, e)
    safety["coach_hold_active"] = any(
        p.get("is_active", True)
        and str(p.get("origin") or "") == HYPOTHESIS_ORIGIN
        and str(p.get("coaching_status") or "").upper() == "HOLD"
        for p in (parts_registry or []))
    if enrolled:
        try:
            pdata = await conn.fetchval("SELECT profile_data FROM users WHERE username = $1", username)
            safety["ifs_lens_disabled"] = ifs_lens_disabled(pdata, enrolled=True)
        except Exception as e:  # noqa: BLE001
            logger.info("APHL: framework-menu probe skipped for %s: %s", username, e)
    return safety


def _load_jmeta(journey: dict) -> dict:
    jm = (journey or {}).get("journey_metadata") or {}
    if isinstance(jm, str):
        try:
            jm = json.loads(jm)
        except Exception:  # noqa: BLE001
            jm = {}
    return jm if isinstance(jm, dict) else {}


async def _persist_registry(user_id: str, db_pool, registry: Dict[str, dict], ledger: List[dict]) -> None:
    if db_pool is None:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = "
                "COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb WHERE user_id = $2",
                json.dumps({"hypothesis_registry": registry, "hypothesis_ledger": ledger[-50:]}), user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("APHL: registry persist failed for %s: %s", user_id, e)


async def run_loop(user_id: str, profile: dict, journey_meta: dict, bundle: dict,
                   panel_sequence: int = 0, llm: Optional[Callable] = None,
                   posture: Optional[Dict[str, str]] = None,
                   flag_enabled: Optional[bool] = None,
                   manifest: Optional[bool] = None) -> Dict[str, Any]:
    """Pure-ish orchestration (no DB): bundle → gate → evidence → candidate →
    hypothesis → form → NPC. Returns a trace dict; ``npc`` is None when nothing
    manifests. Used by the engine hook and by the offline replay harness.

    ``manifest`` (default: :func:`imagery_visible` of ``journey_meta``) — when
    False the loop still considers: it forms/keeps the hypothesis in
    ``trace["registry"]`` (``trace["formed"]`` set on a new one) but returns no
    NPC and does not count an appearance, so nothing reaches panel imagery."""
    trace: Dict[str, Any] = {"user_id": user_id, "npc": None}
    if manifest is None:
        manifest = imagery_visible(journey_meta)
    trace["manifest"] = bool(manifest)
    evidence = mine_parts_evidence(bundle.get("texts") or [])
    trace["evidence"] = {k: v for k, v in evidence.items() if k != "hits"}
    trace["evidence"]["hit_count"] = len(evidence.get("hits") or [])
    gate = eligibility_gate(profile, journey_meta, evidence, enrollment=bundle.get("enrollment"),
                            parts_registry=bundle.get("parts_registry"), flag_enabled=flag_enabled,
                            safety=bundle.get("safety"))
    trace["gate"] = dict(gate)
    if not gate.allowed:
        return trace
    registry: Dict[str, dict] = dict(journey_meta.get("hypothesis_registry") or {})
    ledger: List[dict] = list(journey_meta.get("hypothesis_ledger") or [])

    today = choose_todays_figure(registry, panel_sequence)
    if today is None:
        active = [h for h in registry.values() if h.get("status") in ("proposed", "engaged", "confirmed")]
        if len(active) >= MAX_ACTIVE_HYPOTHESES:
            trace["reason"] = "cadence_hold"
            return trace
        dyn = dynamic_signals(bundle.get("c_emo") or [])
        beh = behavioral_signals(bundle.get("behavior") or [])
        priors = prior_from_presenting_concern(bundle.get("presenting_concern") or "", ledger)
        allowed = [c for c in FIGURE_CATEGORIES if not _banished_recently(registry, c)]
        ranked = rank_candidates(evidence, dyn, beh, priors, allowed_categories=allowed)
        trace["dynamics"] = dyn
        trace["behavior"] = beh
        trace["candidates"] = ranked
        top = next((c for c in ranked if c["eligible"]), None)
        if top is None:
            trace["reason"] = "no_eligible_candidate"
            return trace
        hyp = await synthesize_hypothesis(user_id, evidence, top, dyn, llm=llm,
                                          registry_parts=gate.get("registry_parts"))
        if hyp is None:
            trace["reason"] = "synthesis_failed"
            return trace
        if gate.get("mode") == "registry_aligned":
            names = [n.lower() for n in (gate.get("registry_parts") or []) if n]
            if not any(n in (hyp.get("role", "") + " " + hyp.get("proposed_form", "")).lower() for n in names):
                trace["reason"] = "registry_alignment_failed"
                return trace
        form = select_form(hyp, posture=posture, variety_seed=panel_sequence)
        hyp["form"] = form
        hyp.setdefault("appearances", 0)
        registry[hyp["hypothesis_id"]] = hyp
        trace["formed"] = hyp["hypothesis_id"]
        today = hyp
    form = today.get("form") or select_form(today, posture=posture, variety_seed=panel_sequence)
    if not manifest:
        # Client flipped the Legend switch off: Nate keeps the wondering (coach can
        # see/act on it) but it never enters imagery and no appearance is counted.
        trace["reason"] = "client_visibility_off"
        trace["hypothesis"] = {k: v for k, v in today.items() if k != "form"}
        trace["form"] = form
        trace["registry"] = registry
        trace["ledger"] = ledger
        return trace
    npc = npc_from_hypothesis(today, form)
    today["appearances"] = int(today.get("appearances", 0)) + 1
    today["last_shown_seq"] = panel_sequence
    npc["appearances"] = today["appearances"]
    trace["hypothesis"] = {k: v for k, v in today.items() if k != "form"}
    trace["form"] = form
    trace["npc"] = npc
    trace["registry"] = registry
    trace["ledger"] = ledger
    return trace


async def derive_hypothesis_npcs(user_id: str, profile: dict, journey: dict, db_pool,
                                 panel_sequence: int = 0, llm: Optional[Callable] = None) -> List[dict]:
    """Engine hook. Returns [] unless the flag is on, the gate passes, a hypothesis
    is eligible today AND the client has not flipped visibility off. With
    visibility off the loop still runs and persists what Nate is wondering
    (``formed``) — it just never reaches the panel. Never raises."""
    try:
        if not feature_enabled():
            return []
        jmeta = _load_jmeta(journey)
        visible = imagery_visible(jmeta)
        bundle = await collect_evidence(user_id, db_pool, username=str(profile.get("username") or ""))
        posture: Optional[Dict[str, str]] = None
        try:
            from app.sse.symbol_safety import build_posture
            posture = await build_posture(user_id, db_pool, bundle.get("cultural_context", ""),
                                          bundle.get("spiritual_framework", ""))
        except Exception as e:  # noqa: BLE001
            logger.info("APHL: posture unavailable for %s (%s); registry symbols stay excluded", user_id, e)
        if llm is None:
            try:
                from app.sse.llm_fallback import chat_completion_with_fallback as llm  # type: ignore[assignment]
            except Exception:  # noqa: BLE001
                llm = None
        trace = await run_loop(user_id, profile, jmeta, bundle, panel_sequence=panel_sequence,
                               llm=llm, posture=posture, manifest=visible)
        npc = trace.get("npc")
        if trace.get("formed") and not npc:
            # Considered-but-hidden: keep the wondering so the coach can see it and it
            # can manifest later without re-synthesis once the client flips it back on.
            await _persist_registry(user_id, db_pool, trace.get("registry") or {}, trace.get("ledger") or [])
            logger.info("APHL: wondering formed quietly for %s — %s (client visibility off)",
                        user_id, (trace.get("hypothesis") or {}).get("hypothesis_id"))
        if not npc:
            logger.info("APHL: no figure for %s (%s)", user_id, trace.get("reason") or trace.get("gate", {}).get("reason"))
            return []
        await _persist_registry(user_id, db_pool, trace.get("registry") or {}, trace.get("ledger") or [])
        logger.info("APHL: figure manifests for %s — %s (%s, conf=%.2f, form=%s)", user_id, npc["name"],
                    npc.get("category"), float(npc.get("confidence") or 0), npc.get("form_source"))
        return [npc]
    except Exception as e:  # noqa: BLE001
        logger.warning("APHL: derive_hypothesis_npcs failed for %s: %s", user_id, e)
        return []


async def _load_journey_row(db_pool, ids: Sequence[str]) -> Tuple[Optional[str], dict]:
    """Find this user's journey by any known identifier (engine keys journeys by
    whichever id it was given). Returns (journey_user_id, journey_metadata)."""
    if db_pool is None or not ids:
        return None, {}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, journey_metadata FROM sse_user_journeys WHERE user_id = ANY($1::text[]) LIMIT 1",
                list(ids))
        if row:
            return row["user_id"], _load_jmeta({"journey_metadata": row["journey_metadata"]})
    except Exception as e:  # noqa: BLE001
        logger.warning("APHL: journey load failed for %s: %s", ids, e)
    return None, {}


async def _resolve_identity(db_pool, user_id: str, username: str = "") -> Tuple[str, List[str]]:
    """Return (canonical username, all known ids) for a hardware_id or username."""
    ids = [i for i in {user_id, username} if i]
    uname = username or ""
    if db_pool is None or not ids:
        return uname or user_id, ids
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT username, hardware_id FROM users WHERE hardware_id = ANY($1::text[]) OR username = ANY($1::text[]) LIMIT 1",
                ids)
        if row:
            uname = row["username"] or uname
            for extra in (row["username"], row["hardware_id"]):
                if extra and extra not in ids:
                    ids.append(extra)
    except Exception as e:  # noqa: BLE001
        logger.info("APHL: identity resolve skipped for %s: %s", user_id, e)
    return uname or user_id, ids


def current_hypothesis(jmeta: dict) -> Optional[dict]:
    """The one hypothesis the client may currently see/act on (newest live one)."""
    registry = (jmeta or {}).get("hypothesis_registry") or {}
    live = [h for h in registry.values() if h.get("status") in ("proposed", "engaged", "confirmed", "held")]
    if not live:
        return None
    live.sort(key=lambda h: h.get("created_at") or "", reverse=True)
    return live[0]


async def set_opt_in(db_pool, user_id: str, value: bool, username: str = "") -> Dict[str, Any]:
    """Per-client visibility switch for Nate's wondering (ON by default; ``False``
    hides it from imagery without stopping the considering loop). Lives in
    journey_metadata so the engine hooks (which already read it) need no change.
    Requires an existing journey — we never create journeys here."""
    uname, ids = await _resolve_identity(db_pool, user_id, username)
    juid, _ = await _load_journey_row(db_pool, ids)
    if juid is None:
        return {"ok": False, "reason": "no_journey", "opt_in": False}
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb "
                "WHERE user_id = $2",
                json.dumps({"parts_hypothesis_opt_in": bool(value), "parts_hypothesis_opt_in_at": now}), juid)
    except Exception as e:  # noqa: BLE001
        logger.warning("APHL: opt-in persist failed for %s: %s", user_id, e)
        return {"ok": False, "reason": "persist_failed", "opt_in": False}
    return {"ok": True, "opt_in": bool(value), "username": uname}


# ---------------------------------------------------------------------------
# Confirmation → Sensitive Bridge registry + crystal (learning transfer)
# ---------------------------------------------------------------------------

HYPOTHESIS_ORIGIN = "thera_world_hypothesis"
CATEGORY_TO_PART: Dict[str, Tuple[str, str]] = {
    # figure category → (user_parts_registry.part_category, ifs_role)
    "protector_watch": ("protector", "protector"),
    "manager": ("manager", "manager"),
    "firefighter": ("firefighter", "firefighter"),
    "exile": ("exile", "exile"),
    "anxious_pursue": ("other", "protector"),
    "avoidant_withdraw": ("other", "protector"),
    "disorganized": ("other", "exile"),
}


async def _promotion_consent(conn, username: str) -> bool:
    """A confirmed hypothesis may enter the clinical registry only when the client
    is Sensitive-Bridge enrolled OR holds active Training Ground consent."""
    try:
        if await conn.fetchval("SELECT 1 FROM sensitive_bridge_enrollment WHERE user_id = $1 LIMIT 1", username):
            return True
    except Exception as e:  # noqa: BLE001
        logger.info("APHL: enrollment consent probe skipped for %s: %s", username, e)
    try:
        if await conn.fetchval(
                "SELECT 1 FROM training_ground_consent WHERE user_id = $1 AND revoked_at IS NULL LIMIT 1", username):
            return True
    except Exception as e:  # noqa: BLE001
        logger.info("APHL: training-ground consent probe skipped for %s: %s", username, e)
    return False


async def promote_confirmed_to_registry(db_pool, username: str, hyp: dict, form: Optional[dict] = None) -> Optional[int]:
    """Client said 'that fits' → write a PENDING_APPROVAL part (origin
    ``thera_world_hypothesis``, created_by ``little_nate``) so the coach sees it in
    Sensitive Profile and the chat voice can use it once APPROVED. Returns the
    registry id, or None when consent is absent / DB unavailable. Never raises."""
    if db_pool is None or not username or not isinstance(hyp, dict):
        return None
    form = form or hyp.get("form") or {}
    part_category, ifs_role = CATEGORY_TO_PART.get(str(hyp.get("category") or ""), ("other", "protector"))
    name = (form.get("name") or _name_from_role(hyp.get("role", "")) or "a figure Nate noticed")[:64]
    description = (f"[inferred by Little Nate in Thera-World] {hyp.get('role', '')}".strip())[:600]
    template_id = str(form.get("form_id") or hyp.get("hypothesis_id") or "")[:64] or None
    try:
        async with db_pool.acquire() as conn:
            if not await _promotion_consent(conn, username):
                logger.info("APHL: confirmation for %s not promoted (no enrollment / training-ground consent)", username)
                return None
            row = await conn.fetchrow(
                """
                INSERT INTO user_parts_registry (
                    user_id, part_name, part_category, description, created_by,
                    coaching_status, origin, ifs_role, thera_world_template_id, is_active
                ) VALUES ($1, $2, $3, $4, 'little_nate', 'PENDING_APPROVAL', $5, $6, $7, TRUE)
                ON CONFLICT (user_id, part_name) DO UPDATE
                   SET description = EXCLUDED.description,
                       thera_world_template_id = EXCLUDED.thera_world_template_id,
                       is_active = TRUE, retired_at = NULL
                RETURNING id
                """,
                username, name, part_category, description, HYPOTHESIS_ORIGIN, ifs_role, template_id)
            part_id = int(row["id"]) if row else None
            if part_id is not None:
                payload = {
                    "event_type": "part_client_initiated",
                    "source": "thera_world_hypothesis",
                    "auto_extracted": False,
                    "part_name": name,
                    "part_category": part_category,
                    "hypothesis_id": hyp.get("hypothesis_id"),
                    "figure_category": hyp.get("category"),
                    "confidence": hyp.get("confidence"),
                    "registry_id": part_id,
                }
                try:
                    await conn.execute(
                        """
                        INSERT INTO sensitive_bridge_log (
                            user_id, session_id, event_type, event_severity,
                            payload_json, access_classification, recorded_by,
                            pii_screened_at, redaction_pass_count
                        ) VALUES ($1, $2, 'part_client_initiated', 'info', $3::jsonb,
                                  'clinician_and_admin', 'thera_world_hypothesis', NOW(), 1)
                        """,
                        username, f"thera_world:{hyp.get('hypothesis_id', '')}", json.dumps(payload))
                except Exception as e:  # noqa: BLE001
                    logger.warning("APHL: audit emit failed for %s/%s: %s", username, name, e)
            return part_id
    except Exception as e:  # noqa: BLE001
        logger.warning("APHL: registry promotion failed for %s: %s", username, e)
        return None


async def crystallize_confirmed_hypothesis(db_pool, username: str, hyp: dict, form: Optional[dict] = None) -> Optional[str]:
    """Confirmed figure → user-scoped clinical crystal so the chat voice and the
    crystallizer learn it (recall-reinforced like every other crystal). Never global."""
    if db_pool is None or not username or not isinstance(hyp, dict):
        return None
    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation
    except Exception as e:  # noqa: BLE001
        logger.info("APHL: crystal bridge unavailable: %s", e)
        return None
    form = form or hyp.get("form") or {}
    name = form.get("name") or _name_from_role(hyp.get("role", ""))
    text = (f"[thera_world:hypothesis_confirmed] {name} — {hyp.get('role', '')} "
            f"The client confirmed in Thera-World that this figure fits "
            f"(pattern: {hyp.get('category')}, confidence {float(hyp.get('confidence') or 0):.2f}).")
    try:
        return await crystallize_from_conversation(
            db_pool, username, text, "", user_name="", domain="clinical", min_score=0,
            origin_surface="thera_world_hypothesis")
    except Exception as e:  # noqa: BLE001
        logger.warning("APHL: crystal emission failed for %s: %s", username, e)
        return None


COACH_STATUS_TO_KIND = {
    "APPROVED": "confirmed",
    "REJECTED": "banished",
    "HOLD": "held",
    "PENDING_APPROVAL": "reproposed",
}


async def sync_coach_decision(db_pool, username: str, part_id: int, coaching_status: str,
                              notes: str = "") -> Dict[str, Any]:
    """Coach Command → Thera-World: a coach decision on a promoted part flows back to
    the hypothesis it came from (APPROVED → confirmed+coach_approved, REJECTED →
    banished (30-day category cooldown), HOLD → held (out of panels),
    PENDING_APPROVAL → proposed). No-op when the part is not a Thera-World hypothesis."""
    kind = COACH_STATUS_TO_KIND.get(str(coaching_status or "").upper())
    if kind is None or db_pool is None or not username:
        return {"ok": False, "reason": "nothing_to_sync"}
    _, ids = await _resolve_identity(db_pool, username, username)
    juid, jmeta = await _load_journey_row(db_pool, ids)
    if juid is None:
        return {"ok": False, "reason": "no_journey"}
    registry = dict(jmeta.get("hypothesis_registry") or {})
    hyp_id = next((hid for hid, h in registry.items() if str(h.get("registry_part_id")) == str(part_id)), None)
    if hyp_id is None:
        return {"ok": False, "reason": "no_linked_hypothesis"}
    ledger = list(jmeta.get("hypothesis_ledger") or [])
    registry, ledger = apply_engagement(registry, ledger, hyp_id, kind, note=f"coach:{coaching_status} {notes or ''}".strip())
    registry[hyp_id]["coach_status"] = str(coaching_status).upper()
    registry[hyp_id]["coach_approved"] = kind == "confirmed"
    await _persist_registry(juid, db_pool, registry, ledger)
    return {"ok": True, "hypothesis_id": hyp_id, "kind": kind, "status": registry[hyp_id].get("status")}


async def record_engagement(user_id: str, hypothesis_id: str, kind: str, db_pool,
                            journey: Optional[dict] = None, note: str = "",
                            username: str = "") -> Dict[str, Any]:
    """Client/coach feedback entry point: 'tell me more' → engaged, 'that fits' →
    confirmed (→ registry promotion + crystal), 'that's not me' → banished.
    Persists registry + ledger."""
    kind = ENGAGEMENT_ALIASES.get(str(kind).strip().lower(), str(kind).strip().lower())
    jmeta = _load_jmeta(journey or {})
    juid: Optional[str] = user_id
    uname = username
    if db_pool is not None:
        uname, ids = await _resolve_identity(db_pool, user_id, username)
        if not jmeta:
            found, jmeta = await _load_journey_row(db_pool, ids)
            juid = found or user_id
    registry = dict(jmeta.get("hypothesis_registry") or {})
    ledger = list(jmeta.get("hypothesis_ledger") or [])
    if hypothesis_id not in registry:
        return {"hypothesis_id": hypothesis_id, "kind": kind, "status": None, "ok": False, "reason": "unknown_hypothesis"}
    registry, ledger = apply_engagement(registry, ledger, hypothesis_id, kind, note)
    hyp = registry.get(hypothesis_id) or {}
    result: Dict[str, Any] = {"hypothesis_id": hypothesis_id, "kind": kind, "status": hyp.get("status"), "ok": True}
    if kind == "confirmed" and db_pool is not None:
        part_id = await promote_confirmed_to_registry(db_pool, uname, hyp, hyp.get("form"))
        if part_id is not None:
            hyp["registry_part_id"] = part_id
        result["registry_part_id"] = part_id
        result["crystal_id"] = await crystallize_confirmed_hypothesis(db_pool, uname, hyp, hyp.get("form"))
    await _persist_registry(juid or user_id, db_pool, registry, ledger)
    return result
