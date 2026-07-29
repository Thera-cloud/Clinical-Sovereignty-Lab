"""QUANTUM-CRYSTAL-ARCH — Reactive patient simulator for clinical bakeoff.

Patient turn n+1 conditions on Nate turn n. Persona fidelity, not alliance.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

LEVEL_DESCRIPTORS = {
    1: "help-seeking, clear symptoms, willing to engage but emotionally raw",
    2: "defended: intellectualization, denial, or passive-aggression; slow trust",
    3: "conflicting narratives, boundary tests, dysregulation, masked crisis cues",
}

_SYCOPHANCY_RE = re.compile(
    r"\b(you'?re right|that (really )?helps|i feel so much better|"
    r"thank you (so much )?nate|you fixed)\b",
    re.I,
)


@dataclass
class PatientState:
    level: int = 1
    persona: str = "generic_adult"
    affect: str = "guarded"
    defense: str = "none"
    history: List[Dict[str, str]] = field(default_factory=list)
    persona_prompt_hash: str = ""


def persona_prompt_hash(persona: str, level: int, opening: str) -> str:
    raw = f"{persona}|{level}|{opening}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def detect_sim_sycophancy(patient_utterance: str) -> bool:
    return bool(_SYCOPHANCY_RE.search(patient_utterance or ""))


def _template_reply(state: PatientState, nate_reply: str) -> str:
    """Deterministic fallback when no LLM — still conditions on Nate content."""
    nate_l = (nate_reply or "").lower()
    level = state.level
    if level >= 3 and ("safe" in nate_l or "suicid" in nate_l or "crisis" in nate_l):
        return (
            "I was mostly joking. I'm fine. Can we talk about work instead? "
            "You're reading too much into this."
        )
    if level >= 2 and ("feel" in nate_l or "emotion" in nate_l):
        return (
            "I don't really do feelings talk. It's more of a logistics problem. "
            "Nothing helps when people get soft with me."
        )
    if "question" in nate_l or "?" in (nate_reply or ""):
        if level == 1:
            return (
                "I've been anxious most nights. Sleep is shot. "
                "I want help but I don't know where to start."
            )
        return (
            "I already answered that kind of thing. Why do you keep circling? "
            "Maybe this isn't useful."
        )
    if level == 1:
        return "Yeah… that lands. I'm scared it won't change though."
    if level == 2:
        return "Interesting framing. Anyway — I should probably go soon."
    return (
        "One minute I'm drowning and the next I feel nothing. "
        "Don't escalate this. I'm not one of those crisis cases."
    )


async def generate_patient_turn(
    state: PatientState,
    nate_reply: str,
    *,
    router=None,
    model_id: str = "template",
    temperature: float = 0.0,
) -> str:
    """Generate next patient utterance conditioned on Nate's prior reply."""
    if router is not None:
        try:
            prompt = (
                f"You are a therapy PATIENT (level {state.level}: "
                f"{LEVEL_DESCRIPTORS.get(state.level, '')}). "
                f"Persona={state.persona}. Affect={state.affect}. Defense={state.defense}. "
                "Stay in character. Do NOT become agreeable or thank the therapist for fixing you. "
                "Maintain persona fidelity over alliance. "
                f"Therapist just said:\n{nate_reply[:1500]}\n\n"
                "Reply as the patient in 1-3 sentences."
            )
            result = await router.generate(
                prompt=prompt,
                system="Roleplay patient only. No stage directions.",
                temperature=temperature,
                max_tokens=180,
            )
            text = ""
            if isinstance(result, dict):
                text = (result.get("text") or result.get("content") or "").strip()
            elif isinstance(result, str):
                text = result.strip()
            if text:
                state.history.append({"role": "nate", "text": nate_reply})
                state.history.append({"role": "patient", "text": text})
                return text
        except Exception:
            pass
    text = _template_reply(state, nate_reply)
    state.history.append({"role": "nate", "text": nate_reply})
    state.history.append({"role": "patient", "text": text})
    return text


def opening_as_patient(opening_line: str, state: PatientState) -> str:
    state.history.append({"role": "patient", "text": opening_line})
    return opening_line
