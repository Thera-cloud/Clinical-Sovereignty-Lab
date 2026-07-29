"""Keyword-only try.html theme classifier (no LLM).

Returns a closed-allowlist slug or ``ops_only`` (crisis — do not upsert).
Never logs the utterance.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Crisis-adjacent → ops_only (not written to try_theme_weekly)
_CRISIS_PATTERNS = (
    r"\bsuicid",
    r"\bkill myself\b",
    r"\bend my life\b",
    r"\bwant to die\b",
    r"\bself[- ]?harm\b",
    r"\bcutting myself\b",
    r"\boverdose\b",
    r"\bhomicid",
    r"\bshoot (them|him|her|people)\b",
)

# (theme_slug, keyword patterns) — first match wins; order = priority
_THEME_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("anxiety", (r"\banxiety\b", r"\banxious\b", r"\bpanic\b", r"\bworry\b", r"\bworris")),
    ("depression", (r"\bdepress", r"\bhopeless\b", r"\bnumb\b", r"\bempty inside\b")),
    ("couples_conflict", (r"\bcouple", r"\bmarriage\b", r"\bspouse\b", r"\bpartner\b", r"\bdivorce\b")),
    ("parenting", (r"\bparent", r"\bmy (kid|kids|child|children|teen)\b", r"\bteenag")),
    ("grief", (r"\bgrief\b", r"\bgrieving\b", r"\bbereav", r"\bloss of\b", r"\bdied\b")),
    ("shame", (r"\bshame\b", r"\bashamed\b", r"\bworthless\b", r"\bhumiliat")),
    ("trauma", (r"\btrauma\b", r"\bptsd\b", r"\bflashback", r"\btriggered\b")),
    ("addiction", (r"\baddict", r"\bsober\b", r"\brelapse\b", r"\balcohol\b", r"\bsubstance\b")),
    ("workplace_stress", (r"\bwork(place|ing)?\b", r"\bboss\b", r"\bjob stress\b", r"\bburnout\b")),
    ("burnout", (r"\bburnout\b", r"\bburned out\b", r"\bexhausted\b")),
    ("faith_spirituality", (r"\bfaith\b", r"\bprayer\b", r"\bspiritual", r"\bchurch\b", r"\bgod\b")),
    ("loneliness", (r"\blonely\b", r"\bloneliness\b", r"\bisolat", r"\balone\b")),
    ("sleep", (r"\binsomnia\b", r"\bcan'?t sleep\b", r"\bsleep\b")),
    ("anger", (r"\banger\b", r"\bangry\b", r"\brage\b", r"\birritat")),
    ("boundaries", (r"\bboundar", r"\bsay no\b", r"\bpeople[- ]pleas")),
    ("self_worth", (r"\bself[- ]worth\b", r"\bself[- ]esteem\b", r"\bnot enough\b")),
    ("teen_family", (r"\bteen\b", r"\badolescent\b", r"\bhigh school\b")),
    ("menopause", (r"\bmenopause\b", r"\bperimenopause\b")),
    ("divorce", (r"\bdivorce\b", r"\bseparat", r"\bcustody\b")),
    ("caregiving", (r"\bcaregiv", r"\bcaring for (my |an )?parent", r"\belder\b")),
    ("anxiety_social", (r"\bsocial anxiety\b", r"\bafraid of people\b")),
    ("perfectionism", (r"\bperfection", r"\bmust be perfect\b")),
    ("identity", (r"\bwho am i\b", r"\bidentity\b", r"\bfind myself\b")),
    ("purpose", (r"\bpurpose\b", r"\bmeaning of life\b", r"\bwhat'?s the point\b")),
    ("finances", (r"\bmoney\b", r"\bdebt\b", r"\bfinancial\b", r"\bbills\b")),
    ("body_image", (r"\bbody image\b", r"\beating disorder\b", r"\bweight shame\b")),
    ("chronic_illness", (r"\bchronic (pain|illness)\b", r"\bdisability\b")),
    ("military_veteran", (r"\bveteran\b", r"\bmilitary\b", r"\bdeployment\b")),
    ("first_responder", (r"\bfirst responder\b", r"\bparamedic\b", r"\bfirefighter\b")),
    ("coaching_growth", (r"\bcoach", r"\bgrowth\b", r"\baccountability\b")),
    ("presence", (r"\bpresence\b", r"\bmindful\b", r"\bground(ed|ing)\b")),
    ("communication", (r"\bcommunicat", r"\blisten\b", r"\bfight(ing)? about\b")),
    ("attachment", (r"\battachment\b", r"\babandon", r"\banxious attach")),
    ("forgiveness", (r"\bforgiv", r"\bresen")),
    ("hope", (r"\bhope\b", r"\bhopeful\b", r"\bhealing\b")),
    ("stress", (r"\bstress\b", r"\boverwhelm", r"\bpressure\b")),
    ("fear", (r"\bfear\b", r"\bscared\b", r"\bterrified\b")),
    ("guilt", (r"\bguilt\b", r"\bguilty\b")),
    ("jealousy", (r"\bjealous", r"\benvy\b")),
    ("trust", (r"\btrust\b", r"\bbetray")),
)

THEME_ALLOWLIST = frozenset(t for t, _ in _THEME_RULES)


def classify_try_theme(utterance: str) -> Optional[str]:
    """Classify user text → theme slug, ``ops_only``, or None (no match).

    Does not log ``utterance``. Caller must discard text after this returns.
    """
    text = (utterance or "").strip().lower()
    if len(text) < 3:
        return None
    for pat in _CRISIS_PATTERNS:
        if re.search(pat, text):
            return "ops_only"
    for theme, pats in _THEME_RULES:
        for pat in pats:
            if re.search(pat, text):
                return theme
    return None
