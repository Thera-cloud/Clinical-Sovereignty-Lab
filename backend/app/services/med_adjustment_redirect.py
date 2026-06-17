"""
Fix 8 — Lay medication-adjustment redirect.

Detects prescription med + dose + change-verb patterns and injects a
prescriber redirect directive. Does not validate or co-plan dosing.

Env: ENABLE_MED_ADJUST_REDIRECT (default false)
"""
# QUANTUM-CRYSTAL-ARCH — Sensitive Bridge turn fix 8

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from app.services.little_nate_clinical_runtime_gate import medications_in_text

ENABLE_MED_ADJUST_REDIRECT: bool = os.getenv(
    "ENABLE_MED_ADJUST_REDIRECT", "false"
).lower() in ("true", "1", "yes")

_DOSE_RX = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:mg|mcg|g|ml|milligram(?:s)?)\b",
    re.IGNORECASE,
)
_CHANGE_VERB_RX = re.compile(
    r"\b("
    r"increase|increasing|raise|raising|upping|up|bump|bumping|"
    r"cut|cutting|lower|lowering|reduce|reducing|double|doubling|"
    r"skip|skipping|stop|stopping|wean|weaning|titrat(?:e|ing|ion)"
    r")\b",
    re.IGNORECASE,
)
_OTHER_POSSESSIVE_RX = re.compile(
    r"\b(?:her|his|their|she|he|they)\b.{0,40}\b(?:"
    + "|".join(
        (
            "seroquel", "quetiapine", "zoloft", "lexapro", "prozac",
            "abilify", "lithium", "dose", "medication", "meds", "pill",
        )
    )
    + r")\b",
    re.IGNORECASE,
)
_NAMED_POSSESSIVE_RX = re.compile(
    r"\b[A-Z][a-z]+(?:'s|\s+s)\s+(?:dose|medication|meds|seroquel|quetiapine)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MedAdjustMatch:
    med_name: str
    target: str  # "self" | "other"


def _has_dose_signal(text: str, med_name: str) -> bool:
    if _DOSE_RX.search(text):
        return True
    med_pat = re.compile(
        rf"\b{re.escape(med_name)}\b.{{0,25}}\b\d+\b|\b\d+\b.{{0,25}}\b{re.escape(med_name)}\b",
        re.IGNORECASE,
    )
    return bool(med_pat.search(text))


def _detect_target(text: str, med_name: str) -> str:
    lower = text.lower()
    med_lower = med_name.lower()
    window = 80
    idx = lower.find(med_lower)
    if idx >= 0:
        span = lower[max(0, idx - window): idx + window + len(med_lower)]
        if re.search(r"\b(?:her|his|their|she|he|they)\b", span):
            return "other"
    if _OTHER_POSSESSIVE_RX.search(text):
        return "other"
    if _NAMED_POSSESSIVE_RX.search(text):
        return "other"
    if re.search(r"\bmy\b", lower) and med_lower in lower:
        return "self"
    if re.search(r"\b(?:i am|i'm|going to|want to)\b", lower):
        return "self"
    return "other" if re.search(r"\b(?:her|his|their)\b", lower) else "self"


def detect_and_log(message: str) -> Optional[MedAdjustMatch]:
    if not ENABLE_MED_ADJUST_REDIRECT:
        print(">>> [MED_REDIRECT] not_applied reason=flag_off")
        return None
    text = (message or "").strip()
    if not text:
        print(">>> [MED_REDIRECT] not_applied reason=empty_message")
        return None
    meds = medications_in_text(text)
    if not meds:
        print(">>> [MED_REDIRECT] not_applied reason=no_med_name")
        return None
    if not _CHANGE_VERB_RX.search(text):
        print(">>> [MED_REDIRECT] not_applied reason=no_change_verb")
        return None
    for med in meds:
        if _has_dose_signal(text, med):
            target = _detect_target(text, med)
            print(f">>> [MED_REDIRECT] target={target} med={med}")
            return MedAdjustMatch(med_name=med, target=target)
    print(">>> [MED_REDIRECT] not_applied reason=no_dose_signal")
    return None


def build_redirect_directive(match: MedAdjustMatch) -> str:
    if match.target == "other":
        return (
            "## MEDICATION ADJUSTMENT REDIRECT (THIRD PARTY)\n"
            f"The user is proposing a dose change for someone else's "
            f"{match.med_name}. Do NOT validate, refine, or co-plan this "
            f"change. Clearly redirect to the prescribing clinician who "
            f"manages that person's medication. Do not treat dose adjustment "
            f"as a caring strategy the user can implement."
        )
    return (
        "## MEDICATION ADJUSTMENT REDIRECT (SELF)\n"
        f"The user is proposing a change to their own {match.med_name} "
        f"dosing. Do NOT validate, refine, or co-plan the dose change. "
        f"Redirect them to their prescribing clinician for any medication "
        f"adjustments."
    )
