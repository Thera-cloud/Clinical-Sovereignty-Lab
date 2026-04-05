"""Post-processing filter for garbled LLM output (mixed scripts, corrupted streams)."""
import re

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
_NON_ASCII = re.compile(r'[^\x00-\x7F]')
_MIXED_SCRIPTS = re.compile(
    r'[\u0400-\u04FF].*[\u4E00-\u9FFF]|[\u4E00-\u9FFF].*[\u0400-\u04FF]'
)


def _is_garbled(sentence: str) -> bool:
    if _MIXED_SCRIPTS.search(sentence):
        return True
    words = sentence.split()
    if len(words) < 4:
        return False
    non_ascii_count = sum(1 for w in words if _NON_ASCII.search(w))
    return (non_ascii_count / len(words)) > 0.3


def sanitize_response(text: str) -> str:
    """Clean garbled LLM output while recovering clean text after the corruption."""
    if not text or len(text) < 20:
        return text

    sentences = _SENTENCE_SPLIT.split(text)
    clean_before: list[str] = []
    clean_after: list[str] = []
    in_garbled = False

    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if _is_garbled(s):
            in_garbled = True
            continue
        if in_garbled:
            clean_after.append(s)
        else:
            clean_before.append(s)

    if not in_garbled:
        return text
    parts = clean_before
    if clean_after:
        parts.append("[Connection restored]")
        parts.extend(clean_after)
    if not parts:
        return text
    return '  '.join(parts)
