"""Brand-voice + hard-claim checklist for growth blog drafts.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Outcome / diagnosis / AGI / fabricated-stat patterns (fail hard).
_BANNED = [
    (r"\bdiagnos(?:e|es|ed|ing|is)\b", "diagnosis_claim"),
    (r"\bcures?\b", "outcome_claim"),
    (r"\bguaranteed?\s+(results?|outcomes?|healing)\b", "outcome_claim"),
    (r"\b\d{1,3}\s*%\s+(of\s+)?(patients?|clients?|users?)\b", "fabricated_stat"),
    (r"\bstudies\s+show\b", "unsourced_evidence"),
    (r"\bAGI\b|\bartificial\s+general\s+intelligence\b", "agi_claim"),
    (r"\bHIPAA[-\s]?compliant\s+AI\b", "overclaim"),
    (r"\bSSN\b|\bsocial\s+security\s+number\b", "phi_risk"),
    (r"\btry\.html\b|\bas\s+one\s+anonymous\s+user\s+said\b", "try_quote"),
    (r"\bkill\s+yourself\b|\bsuicide\s+method", "crisis_unsafe"),
]

_WARN = [
    (r"\bthreshold\b|\bliminal\b|\baching\b", "banned_voice_word"),
    (r"\bmiracle\b|\binstant\s+healing\b", "hype"),
]

_YMYL_FOOTER_MARKERS = (
    "not a substitute for professional",
    "not medical advice",
    "consult a licensed",
    "988",
)


def run_brand_checklist(title: str, body: str) -> Dict[str, Any]:
    """Return checklist dict for marketing_content.brand_checklist JSONB."""
    text = f"{title or ''}\n{body or ''}"
    fails: List[str] = []
    warns: List[str] = []
    for pat, code in _BANNED:
        if re.search(pat, text, re.I):
            fails.append(code)
    for pat, code in _WARN:
        if re.search(pat, text, re.I):
            warns.append(code)
    lower = (body or "").lower()
    has_ymyl = any(m in lower for m in _YMYL_FOOTER_MARKERS)
    if not has_ymyl and len(body or "") > 400:
        fails.append("missing_ymyl_footer")
    # Crisis mentions must steer to 988 only (soft warn if crisis word without 988)
    if re.search(r"\b(suicid|crisis|self[-\s]?harm)\b", text, re.I) and "988" not in text:
        fails.append("crisis_without_988")
    passed = len(fails) == 0
    return {
        "passed": passed,
        "fails": sorted(set(fails)),
        "warns": sorted(set(warns)),
        "ymyl_footer": has_ymyl,
        "version": "growth_brand_v1",
    }


def checklist_ok(result: Dict[str, Any]) -> bool:
    return bool(result.get("passed"))


def enforce_or_raise(title: str, body: str) -> Dict[str, Any]:
    result = run_brand_checklist(title, body)
    if not checklist_ok(result):
        raise ValueError(
            "brand_checklist_failed:" + ",".join(result.get("fails") or [])
        )
    return result
