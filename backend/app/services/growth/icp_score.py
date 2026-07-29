"""Deterministic ICP scoring for buyer_leads (no LLM).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


_DEFAULT_WEIGHTS = {
    "title_match": 0.35,
    "specialty_match": 0.35,
    "state_match": 0.15,
    "has_npi": 0.15,
}

_DEFAULT_TITLES = [
    "ceo",
    "coo",
    "director",
    "owner",
    "founder",
    "practice manager",
    "clinical director",
]

_DEFAULT_SPECIALTIES = [
    "therapy",
    "counseling",
    "behavioral",
    "psychiatry",
    "coaching",
    "mental health",
]


def _hit(text: str, keywords: List[str]) -> bool:
    t = (text or "").lower()
    return any(k in t for k in keywords if k)


def score_lead(
    *,
    title: str = "",
    specialty: str = "",
    state: str = "",
    npi: str = "",
    preferred_states: Optional[List[str]] = None,
    weights: Optional[Dict[str, Any]] = None,
    title_keywords: Optional[List[str]] = None,
    specialty_keywords: Optional[List[str]] = None,
) -> float:
    w = dict(_DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)
    titles = [x.lower() for x in (title_keywords or _DEFAULT_TITLES)]
    specs = [x.lower() for x in (specialty_keywords or _DEFAULT_SPECIALTIES)]
    states = [s.upper() for s in (preferred_states or []) if s]

    total = 0.0
    if _hit(title, titles):
        total += w["title_match"]
    if _hit(specialty, specs):
        total += w["specialty_match"]
    if states and (state or "").upper() in states:
        total += w["state_match"]
    elif not states and (state or "").strip():
        total += w["state_match"] * 0.5
    if (npi or "").strip():
        total += w["has_npi"]
    return round(min(1.0, total), 4)
