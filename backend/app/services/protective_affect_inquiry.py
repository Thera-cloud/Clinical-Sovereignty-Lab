"""Compassionate inquiry for fear and shame disclosures.

The protocol makes Little Nate curious about the protective dilemma and
underlying longing before offering solutions.  It deliberately forbids
covert persuasion, leading questions, and pressure to disclose.
"""

from __future__ import annotations

import re
from typing import List, Optional

_FEAR = re.compile(
    r"\b(?:afraid|fear(?:ful)?|scared|guarded|dread|terrified|"
    r"frightened|unsafe|old fear)\b",
    re.I,
)
_SHAME = re.compile(
    r"\b(?:shame|ashamed|humiliat(?:ed|ing)|disgusted with myself|"
    r"worthless|not good enough|want to hide|feel exposed)\b",
    re.I,
)
_DEPTH_INQUIRY = re.compile(
    r"(?:"
    r"\bwhat\b.{0,90}\b(?:protect|prevent|risk|cost|want|wish|need|long|hope)\b|"
    r"\bwhat\b.{0,90}\b(?:fear|shame)\b.{0,90}\b(?:say|believe|expect|guard)\b|"
    r"\bif\b.{0,90}\b(?:fear|shame)\b.{0,90}\bwhat\b|"
    r"\bwhat\b.{0,90}\btoo risky\b"
    r")",
    re.I | re.S,
)
_SOLUTION_TAKEOVER = re.compile(
    r"(?:"
    r"^\s*(?:\d+[\.\)]|[-*])\s+|"
    r"\b(?:you should|try to|start by|break (?:it|that|the action|the goal) down|"
    r"set a specific time|make (?:it|the experience) more enjoyable|"
    r"here are (?:a few|some)|one possibility is)\b"
    r")",
    re.I | re.M,
)


def classify_protective_affect(user_text: str) -> Optional[str]:
    """Return the affect kind when the client explicitly names fear or shame."""
    text = user_text or ""
    fear = bool(_FEAR.search(text))
    shame = bool(_SHAME.search(text))
    if fear and shame:
        return "fear_and_shame"
    if fear:
        return "fear"
    if shame:
        return "shame"
    return None


def build_inquiry_block(kind: Optional[str]) -> str:
    """Build a natural-language system directive for the detected affect."""
    if not kind:
        return ""
    label = kind.replace("_", " ")
    return (
        "## PROTECTIVE AFFECT INQUIRY — " + label.upper() + "\n"
        "Fear or shame is present. Before advice, goals, reframing, or a skill, "
        "stay with the feeling and become curious about its protective job, the "
        "dilemma it creates, and the longing it guards. Keep any existing goal "
        "in the background rather than using it as the agenda. Ask ONE natural, "
        "open question this turn: what the feeling expects would happen if it "
        "relaxed, what it is protecting from being seen, or what the person wants "
        "but experiences as too risky to want. Follow the client's language; do "
        "not announce this framework, recite a checklist, or expose internal "
        "analysis. Natural conversation is not permission to deceive: NEVER use "
        "covert persuasion, leading questions, false claims, attachment pressure, "
        "or tricks to force disclosure. Do not claim to know the hidden motive. "
        "When something emerges, reflect it tentatively and meet it with "
        "compassion, without minimizing harm or rushing it away. Let it remain "
        "in the shared conversational space without demanding action. If the "
        "client explicitly asks for an immediate tool or concrete steps, honor "
        "that request after one sentence of attunement."
    )


def response_violations(response_text: str, kind: Optional[str]) -> List[str]:
    """Check that an affect turn explores depth without interrogation or advice."""
    if not kind:
        return []
    text = response_text or ""
    violations: List[str] = []
    question_count = text.count("?")
    if question_count == 0:
        violations.append("protective_affect_inquiry_missing")
    elif question_count > 1:
        violations.append("protective_affect_interrogation")
    if not _DEPTH_INQUIRY.search(text):
        violations.append("protective_affect_depth_missing")
    if _SOLUTION_TAKEOVER.search(text):
        violations.append("protective_affect_solution_takeover")
    return violations


def compassionate_fallback(kind: Optional[str]) -> str:
    """Safe deterministic response when a generated inquiry misses the contract."""
    if kind == "shame":
        return (
            "We do not need to expose or argue with the shame. I want to stay "
            "beside it before we solve anything: what do you wish could be met "
            "with care if the shame did not have to keep it hidden? Whatever "
            "appears can stay here without being judged or rushed."
        )
    if kind == "fear_and_shame":
        return (
            "We can leave the next step in view without pushing toward it. I want "
            "to stay beside the fear and shame first: what are they protecting "
            "that also points toward something you deeply want? Whatever appears "
            "can stay here without being judged or rushed."
        )
    return (
        "We can leave the goal in view without making it the agenda. I want to "
        "stay close to the fear before we solve it: what might you be wanting "
        "that currently feels too risky to want? Whatever appears can stay here "
        "without being judged or rushed."
    )


__all__ = [
    "build_inquiry_block",
    "classify_protective_affect",
    "compassionate_fallback",
    "response_violations",
]
