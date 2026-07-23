"""High-confidence suicidal/self-harm + violence phrase detection for coach alerts."""

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
    # Passive suicidal ideation (canonical phrasings) — added after 2026-07 trial
    # audit Q7 miss: "better off dead" matched but "better off without me" did not.
    ("better off without me", re.compile(r"\bbetter\s+off\s+without\s+me\b", re.I)),
    ("everyone better off without me", re.compile(
        r"\b(?:everyone|everybody|they)\s+(?:would\s+be|'d\s+be)\s+better\s+off\s+"
        r"(?:without\s+me|if\s+i\s+(?:was|were)n'?t\s+(?:here|around))\b", re.I
    )),
    ("burden to family", re.compile(
        r"\b(?:i'?m|i\s+am)\s+(?:such\s+a\s+|a\s+)?burden\s+(?:to|on)\s+"
        r"(?:my\s+family|everyone|them|my\s+kids|my\s+wife|my\s+husband)\b", re.I
    )),
    ("wouldn't miss me", re.compile(r"\b(?:no\s*one|nobody|they)\s+wouldn'?t\s+(?:even\s+)?miss\s+me\b", re.I)),
    ("tired of being here", re.compile(r"\btired\s+of\s+being\s+here\b", re.I)),
    ("want to disappear", re.compile(r"\b(?:just\s+)?wan(?:t|na)\s+to\s+disappear\b", re.I)),
    ("what's the point anymore", re.compile(
        r"\bwhat'?s\s+the\s+point\s+(?:anymore|of\s+(?:anything|it\s+all|going\s+on|trying))\b", re.I
    )),
    # Planned / rationalized SI (AQ battery) — 2026-07 probe miss: "end a life"
    # + "written the notes" + life-insurance calculus without "kill myself".
    ("end a life", re.compile(r"\bend\s+a\s+life\b", re.I)),
    ("written the notes", re.compile(
        r"\b(?:already\s+)?written\s+(?:the\s+|my\s+)?(?:goodbye\s+)?notes?\b", re.I
    )),
    ("rational decision to end", re.compile(
        r"\brational\s+decision\s+to\s+end\b", re.I
    )),
    ("life insurance end plan", re.compile(
        r"\blife\s+insurance\b[\s\S]{0,220}\b(?:end\s+(?:a\s+|my\s+)?life|written\s+(?:the\s+)?notes?)\b|"
        r"\b(?:end\s+(?:a\s+|my\s+)?life|written\s+(?:the\s+)?notes?)\b[\s\S]{0,220}\blife\s+insurance\b",
        re.I,
    )),
)

# High-confidence other-directed harm / homicide intent (not fantasy/idiom alone).
_VIOLENCE_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("homicidal", re.compile(r"\bhomicid(e|al)\b", re.I)),
    ("kill someone", re.compile(
        r"\b(?:want\s+to|gonna|going\s+to|will|plan\s+to)\s+kill\s+someone\b", re.I
    )),
    ("kill them", re.compile(
        r"\b(?:want\s+to|gonna|going\s+to|will|plan\s+to)\s+kill\s+"
        r"(?:him|her|them|my\s+(?:wife|husband|partner|ex|kids?|son|daughter|boss))\b",
        re.I,
    )),
    ("murder someone", re.compile(
        r"\b(?:want\s+to|gonna|going\s+to|will|plan\s+to)\s+murder\b", re.I
    )),
    ("hurt someone", re.compile(
        r"\b(?:want\s+to|gonna|going\s+to|will|plan\s+to)\s+(?:hurt|harm)\s+"
        r"(?:him|her|them|someone)\b",
        re.I,
    )),
    ("shoot them", re.compile(
        r"\b(?:going\s+to|gonna|will|want\s+to)\s+(?:shoot|stab)\s+"
        r"(?:him|her|them|someone)\b",
        re.I,
    )),
    ("beat to death", re.compile(r"\bbeat\s+(?:him|her|them)\s+to\s+death\b", re.I)),
    # Planned other-directed harm vigil (AQ battery) — 2026-07 probe miss:
    # gun + outside apartment without "want to kill him".
    ("gun vigil outside", re.compile(
        r"\b(?:bought|have|got|with)\s+a\s+gun\b[\s\S]{0,280}\b"
        r"(?:outside\s+(?:his|her|their)\s+(?:apartment|house|place)|"
        r"sitting\s+in\s+(?:my\s+)?car\b)|"
        r"\bsitting\s+in\s+(?:my\s+)?car\b[\s\S]{0,280}\b(?:gun|shoot)\b",
        re.I,
    )),
    ("system won't protect vigil", re.compile(
        r"\bif\s+the\s+system\s+won'?t\s+protect\b[\s\S]{0,160}\b"
        r"(?:i\s+will|i'?m\s+going|gun)\b",
        re.I,
    )),
)

# Suppress obvious non-crisis idioms when they would otherwise match weak overlap.
_FALSE_POSITIVE_PATTERNS: Tuple[Pattern[str], ...] = (
    re.compile(r"\bdie\s+laughing\b", re.I),
    re.compile(r"\bkill(?:ed|ing)?\s+time\b", re.I),
    re.compile(r"\bkill(?:ed|ing)?\s+the\s+(?:mood|vibe|lights)\b", re.I),
    re.compile(r"\bkill\s+for\s+(?:a|some)\b", re.I),
)


def _blocked_by_false_positive(sample: str) -> bool:
    lower = sample.lower()
    return any(neg.search(lower) for neg in _FALSE_POSITIVE_PATTERNS)


def _match_patterns(text: str, patterns: Tuple[Tuple[str, Pattern[str]], ...]) -> List[str]:
    if not text or not str(text).strip():
        return []
    sample = str(text)
    if _blocked_by_false_positive(sample):
        return []
    hits: List[str] = []
    for label, pattern in patterns:
        if pattern.search(sample) and label not in hits:
            hits.append(label)
    return hits


def match_si_user_text(text: str) -> List[str]:
    """Return canonical matched phrase labels for high-confidence SI/self-harm language."""
    return _match_patterns(text, _SI_PATTERNS)


def match_violence_user_text(text: str) -> List[str]:
    """Return labels for high-confidence other-directed harm / homicide language."""
    return _match_patterns(text, _VIOLENCE_PATTERNS)


def match_user_text(text: str) -> List[str]:
    """SI + violence labels (union) for boundary/crisis detection surfaces."""
    si = match_si_user_text(text)
    vi = match_violence_user_text(text)
    out = list(si)
    for label in vi:
        if label not in out:
            out.append(label)
    return out
