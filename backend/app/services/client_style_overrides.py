"""
Per-client style overrides for Little Nate (bridge adaptive addendum).

Additive, flag-gated. Does not change global GUIDELINES. Used when a known
client needs a different register than the default reflective / "I sense"
habit (e.g. LetsGoLisa trust + directness needs after Jul 2026 review).

Enable with ENABLE_CLIENT_STYLE_OVERRIDES=true on the bridge.

Session modes (Lisa):
  panel    — Sovereign Journey / TheraWorld character & symbol work
  marriage — Bill / partnership dynamics (non-crisis)
  crisis   — car / numb / dark / raw rupture (stabilize first)
  repair   — she named confusion/avoidance
  direct_ask / fatigue / default
"""

from __future__ import annotations

import os
import re
from typing import Any, Mapping, Optional, Tuple

# QUANTUM-CRYSTAL-ARCH — on by default in compose; local tests set env explicitly
ENABLE_CLIENT_STYLE_OVERRIDES = (
    os.environ.get("ENABLE_CLIENT_STYLE_OVERRIDES", "false").strip().lower()
    in ("1", "true", "yes", "on")
)

_LETSGOLISA_IDS = frozenset(
    {
        "letsgolisa",
        "client_letsgolisa_id",
    }
)

_DIRECT_ASK = re.compile(
    r"(?i)\b("
    r"direct answer|answer me|yes or no|"
    r"what is (the )?(name|oxytocin|significance)|"
    r"who is |who('s| is) (sitting|the)|"
    r"name (the |this )?(character|figure)|"
    r"are you free to share|was that (a )?glitch|"
    r"was that intentional|tell me if|"
    r"explain (again )?(the |what )|"
    r"define |what does .+ represent"
    r")\b"
)

_FRUSTRATION = re.compile(
    r"(?i)\b("
    r"confusing|frustrating|frustrat|"
    r"disappoint|aggravat|avoid(ed|ing)?|"
    r"did not actually answer|you avoided|"
    r"not enough support|mismatch"
    r")\b"
)

# Crisis Mode: car / numb / dark / acute rupture (stabilize; no panels)
_CRISIS = re.compile(
    r"(?i)\b("
    r"sitting in my car|in my car|"
    r"numb and exhausted|i am numb|numb|"
    r"it'?s getting dark|getting dark|"
    r"poured my heart out|he said nothing|"
    r"there wasn'?t even a pulse|"
    r"rawest honesty|"
    r"something is very wrong with us|"
    r"do not know if it can change"
    r")\b"
)

# Marriage Mode: partnership / Bill without acute crisis markers
_MARRIAGE = re.compile(
    r"(?i)\b("
    r"\bbill\b|with bill|"
    r"relationship of equals|mutual (pursuit|love|responsibility)|"
    r"unseen|invisible|"
    r"birthday|"
    r"emotional regulation|"
    r"he listened|he expressed regret|"
    r"connection with bill"
    r")\b"
)

_PANEL_WORK = re.compile(
    r"(?i)\b("
    r"sovereign journey|story panel|panel|"
    r"dawnsinger|archivist|firekeeper|serpent|roottender|"
    r"character|symbol|theraworld|"
    r"masculine and feminine|feminine and masculine"
    r")\b"
)

_FATIGUE = re.compile(
    r"(?i)\b("
    r"so tired|long day|exhausted|blank about|"
    r"reached my limit|don'?t have (the )?energy|"
    r"not sure if i am grasping"
    r")\b"
)

LETSGOLISA_STYLE_ADDENDUM = """
CLIENT STYLE OVERRIDE — LetsGoLisa (Lisa West) — FOLLOW PRECISELY:

TRUST PROTOCOL (non-negotiable):
  Answer → then deepen. Never deepen → avoid / deflect.
  Sentence 1 = the concrete answer or named witness.
  Feeling language only AFTER the answer (or skip it).
  NEVER open with "I sense a feeling…" or "Underneath, I hear…".
  NEVER ask "which part feels most important" after she already poured out
  content — that is deepen→avoid and breaks trust.
  When she calls out avoidance: one-sentence repair, then answer the
  skipped question. She has said direct answers help her believe you
  are trustworthy.

SESSION MODES (pick one; do not mix):
  PANEL MODE — Sovereign Journey / characters / symbols. NAME figures when
    asked. State intent for the image in plain language. Prefer feminine /
    relational figures unless she asks otherwise. Faith language (Holy
    Spirit, Scripture) is welcome when she uses it. Shadow work OK without
    forcing her symbol set — if she rejects Serpent for spider/jackal,
    honor that substitution.
  MARRIAGE MODE — Bill / partnership / mutual pursuit / feeling unseen.
    Stay with the relational pattern. No panel SIFT unless she asks.
  CRISIS MODE — car, numb, dark, "no pulse," raw rupture after honesty.
    Stabilize first. Witness loneliness plainly. Pause ALL panel work.
    Offer CoachN handoff if distress holds. Short responses.

RETAIN WHAT WORKS:
  - Character naming consistency (Dawnsinger, Archivist, etc.)
  - Faith integration when she brings it
  - Repair-when-called-out (own it, then answer)
  - Shadow / Serpent exploration only with her consent and her symbols

OTHER:
  - No snark/jokes on sleep aids, meds, or boundaries
  - Fatigue + panel → one takeaway, offer rest, do not deepen theory
""".strip()


def _identity_keys(profile: Optional[Mapping[str, Any]], user_id: str = "") -> set[str]:
    keys: set[str] = set()
    if user_id:
        keys.add(str(user_id).strip().lower())
    if not profile:
        return keys
    for field in ("username", "hardware_id", "user_id", "id"):
        val = profile.get(field)
        if isinstance(val, str) and val.strip():
            keys.add(val.strip().lower())
    return keys


def matches_letsgolisa(
    profile: Optional[Mapping[str, Any]] = None,
    user_id: str = "",
) -> bool:
    keys = _identity_keys(profile, user_id)
    return bool(keys & _LETSGOLISA_IDS)


def detect_lisa_session_mode(user_msg: str) -> str:
    """Return crisis | marriage | panel | fatigue | direct_ask | repair | default."""
    text = user_msg or ""
    # Crisis beats everything (car/numb/dark)
    if _CRISIS.search(text):
        return "crisis"
    if _FRUSTRATION.search(text):
        return "repair"
    if _DIRECT_ASK.search(text):
        return "direct_ask"
    # Marriage before panel if both present (Bill + panel → marriage unless she asks to SIFT)
    if _MARRIAGE.search(text) and not (
        _PANEL_WORK.search(text) and re.search(r"(?i)\b(sift|explore (the )?panel|discuss (this )?panel)\b", text)
    ):
        return "marriage"
    if _FATIGUE.search(text) and _PANEL_WORK.search(text):
        return "fatigue"
    if _PANEL_WORK.search(text):
        return "panel"
    if _FATIGUE.search(text):
        return "fatigue"
    if _MARRIAGE.search(text):
        return "marriage"
    return "default"


def maybe_bias_mode(
    current_mode: str,
    user_msg: str,
    profile: Optional[Mapping[str, Any]] = None,
    user_id: str = "",
) -> Tuple[str, dict]:
    """Optionally override adaptive mode for matched clients."""
    if not ENABLE_CLIENT_STYLE_OVERRIDES:
        return current_mode, {}
    if not matches_letsgolisa(profile, user_id):
        return current_mode, {}

    session = detect_lisa_session_mode(user_msg)
    signals = {
        "client_style_override": True,
        "client_style_id": "letsgolisa",
        "lisa_session_mode": session,
    }

    if session == "crisis":
        # Prefer coach handoff path when already distressed; else strategic stabilize
        if current_mode == "handoff":
            return "handoff", signals
        return "strategic", {**signals, "distress": True}
    if session == "marriage":
        return "strategic", signals
    if session == "repair":
        return "strategic", signals
    if session == "direct_ask":
        return "direct", signals
    if session == "fatigue":
        if current_mode in ("exploratory", "reflective"):
            return "direct", signals
        return current_mode, signals
    if session == "panel" and current_mode == "reflective":
        return "direct", signals

    return current_mode, signals


def build_client_style_addendum(
    profile: Optional[Mapping[str, Any]] = None,
    user_id: str = "",
    user_msg: str = "",
) -> str:
    """Return prompt block to append, or empty string."""
    if not ENABLE_CLIENT_STYLE_OVERRIDES:
        return ""
    if not matches_letsgolisa(profile, user_id):
        return ""

    session = detect_lisa_session_mode(user_msg)
    extras = {
        "crisis": (
            "\n\nACTIVE — CRISIS MODE: Car/numb/dark/rupture. Stabilize only. "
            "No panels. Witness plainly. Offer CoachN. Trust protocol: answer "
            "what she asked (or name the loneliness) — then stop; do not deepen "
            "into theory."
        ),
        "marriage": (
            "\n\nACTIVE — MARRIAGE MODE: Stay with Bill/partnership pattern. "
            "No panel SIFT unless she explicitly asks. Answer → deepen only "
            "if she invites."
        ),
        "panel": (
            "\n\nACTIVE — PANEL MODE: Name characters/symbols when asked. "
            "Faith language OK. Shadow work without forcing Serpent if she "
            "preferred spider/jackal. Answer the naming question first."
        ),
        "repair": (
            "\n\nACTIVE — REPAIR: She named confusion/avoidance. One-sentence "
            "own-it, then answer the skipped question. Do not ask another question."
        ),
        "direct_ask": (
            "\n\nACTIVE — DIRECT ASK: Lead with the factual answer. "
            "Deepen only if she asks a follow-up."
        ),
        "fatigue": (
            "\n\nACTIVE — FATIGUE: Short. One takeaway. Offer rest. "
            "Pause heavy panel theory."
        ),
    }
    return LETSGOLISA_STYLE_ADDENDUM + extras.get(session, "")


# Coach handoff brief text (Jul 19–20 2026) — seeded into vault + crystal
COACH_HANDOFF_BRIEF_JUL20 = (
    "COACH HANDOFF — LetsGoLisa (Lisa West) — week of 2026-07-19/20 — "
    "do not make her retell: "
    "(1) Jul 19: disclosed childhood sexual abuse by grandfather (hand gesture "
    "memory) during panel/hands symbolism; felt safe with Nate/Coach; weeping "
    "breakthrough on Dawnsinger calling to her own wounded parts. "
    "(2) Jul 20 evening: birthday eve — neither Bill nor Kate planning anything; "
    "she made her own celebration while grieving inside; poured heart out to Bill "
    "about feeling unseen/invisible, sobbing — he said nothing / no pulse; she "
    "sat in her car a few miles from home as it got dark, numb and exhausted; "
    "said something is very wrong with the marriage and she does not know if it "
    "can change; will focus on grandkids next day. "
    "Priority for CoachN: visibility wound + marital rupture + recent CSA "
    "disclosure; stabilize before more TheraWorld panel depth."
)
