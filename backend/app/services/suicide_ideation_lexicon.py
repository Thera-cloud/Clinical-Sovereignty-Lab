"""High-confidence suicidal/self-harm phrase detection for universal coach alerts."""

from __future__ import annotations

import re
from typing import List, Pattern, Tuple

# Strong SI/self-harm signals only — excludes loose tokens (standalone "die", "no point", "plan").
_SI_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("suicidal", re.compile(r"\bsuicid(e|al)\b", re.I)),
    ("kill myself", re.compile(r"\bkill\s+myself\b", re.I)),
    ("end my life", re.compile(r"\bend\s+my\s+life\b", re.I)),
    ("want to die", re.compile(r"\bwant\s+to\s+die\b", re.I)),
    ("better off dead", re.compile(r"\bbetter\s+off\s+dead\b", re.I)),
    ("don't want to live", re.compile(r"\bdon'?t\s+want\s+to\s+live\b", re.I)),
    ("don't want to be alive", re.compile(r"\bdon'?t\s+want\s+to\s+(?:be\s+alive|be\s+here)\b", re.I)),
    ("don't want to exist", re.compile(r"\bdon'?t\s+want\s+to\s+exist\b", re.I)),
    ("wouldn't mind dying", re.compile(r"\bwouldn'?t\s+mind\s+dying\b", re.I)),
    ("passive death wish", re.compile(r"\bpassive\s+death\s+wish\b", re.I)),
    ("hurt myself", re.compile(r"\bhurt\s+myself\b", re.I)),
    ("hurting myself", re.compile(r"\bhurting\s+myself\b", re.I)),
    ("self-harm", re.compile(r"\bself[- ]?harm\b", re.I)),
    ("self-injury", re.compile(r"\bself[- ]?injury\b", re.I)),
    ("cut myself", re.compile(r"\bcut(?:ting)?\s+myself\b", re.I)),
    ("kill myself plan", re.compile(r"\bi\s+have\s+(?:a\s+)?(?:plan|gun|pills|rope)\b", re.I)),
    ("going to kill myself", re.compile(
        r"\bi'?(?:m|ve)\s+(?:going\s+to|gonna)\s+(?:kill|end)\s+(?:myself|it|my\s+life)\b", re.I
    )),
)

# Suppress obvious non-crisis idioms when they would otherwise match weak overlap.
_FALSE_POSITIVE_PATTERNS: Tuple[Pattern[str], ...] = (
    re.compile(r"\bdie\s+laughing\b", re.I),
    re.compile(r"\bkill(?:ed|ing)?\s+time\b", re.I),
    re.compile(r"\bkill(?:ed|ing)?\s+the\s+(?:mood|vibe|lights)\b", re.I),
)


def match_user_text(text: str) -> List[str]:
    """Return canonical matched phrase labels for high-confidence SI/self-harm language."""
    if not text or not str(text).strip():
        return []
    sample = str(text)
    lower = sample.lower()
    for neg in _FALSE_POSITIVE_PATTERNS:
        if neg.search(lower):
            return []
    hits: List[str] = []
    for label, pattern in _SI_PATTERNS:
        if pattern.search(sample) and label not in hits:
            hits.append(label)
    return hits
