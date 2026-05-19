"""Post-processing filter for garbled LLM output (mixed scripts, corrupted streams)."""
from __future__ import annotations

import re
from typing import Optional

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
_NON_ASCII = re.compile(r'[^\x00-\x7F]')
_MIXED_SCRIPTS = re.compile(
    r'[\u0400-\u04FF\uAC00-\uD7A3].*[\u4E00-\u9FFF]'
    r'|[\u4E00-\u9FFF].*[\u0400-\u04FF\uAC00-\uD7A3]'
    r'|[\u0400-\u04FF].*[\uAC00-\uD7A3]'
    r'|[\uAC00-\uD7A3].*[\u0400-\u04FF]'
    r'|[\u0E00-\u0E7F].*[\u0041-\u007A\u0061-\u007A]'
    r'|[\u0041-\u007A\u0061-\u007A].*[\u0E00-\u0E7F]'
    r'|[\u0590-\u05FF].*[\u0041-\u007A\u0061-\u007A]'
    r'|[\u0041-\u007A\u0061-\u007A].*[\u0590-\u05FF]'
)
_CAMEL_CASE = re.compile(r'[a-z][A-Z][a-z]')
_PASCAL_CODE = re.compile(r'^[A-Z][a-z]+[A-Z]')
_UNDERSCORE_PREFIX = re.compile(r'^_[A-Z]')
# Non-Latin scripts seen in production garble (Lisa 2026-05-19: Thai)
_FOREIGN_SCRIPT_WORD = re.compile(
    r'[\u0E00-\u0E7F\u0590-\u05FF\u0900-\u097F\u4E00-\u9FFF'
    r'\uAC00-\uD7A3\u0400-\u04FF\u0600-\u06FF]+'
)
_GARBLE_TOKENS = frozenset({
    '_SENTINEL', '_HIDDEN', '_ACK', '_MPI', '_umfi', '_RS', '_bc',
    'BootApplication', 'FetchType', 'Snapdragon', 'Cylinder',
    'diferentecek', 'scroll(func', 'jsonb_set', 'asyncio',
    'RETURN/disc', 'panLab', 'ysRETURN', 'poss ridAff',
    'methodName', 'namedtuple', 'hmac_tracks', 'offsetHeight',
    'removeFromSuperview', 'WEBPACK', 'getOutputStream',
    'ExecutionContext', 'ExpandedRenderer', 'ContentView',
})


def _char_script_tag(cp: int) -> Optional[str]:
    if 0x0400 <= cp <= 0x04FF:
        return 'cyr'
    if 0x0900 <= cp <= 0x097F:
        return 'dev'
    if 0x4E00 <= cp <= 0x9FFF:
        return 'cjk'
    if 0xAC00 <= cp <= 0xD7A3:
        return 'kor'
    if 0x0600 <= cp <= 0x06FF:
        return 'ara'
    if 0x0E00 <= cp <= 0x0E7F:
        return 'tha'
    if 0x0590 <= cp <= 0x05FF:
        return 'heb'
    if 0x0041 <= cp <= 0x007A:
        return 'lat'
    return None


def _sentence_has_isolated_foreign_script(sentence: str) -> bool:
    """Latin-dominant sentence with one or more isolated non-Latin words (e.g. Thai token)."""
    if not _FOREIGN_SCRIPT_WORD.search(sentence):
        return False
    words = re.findall(r'\S+', sentence)
    if len(words) < 2:
        return True
    foreign_words = sum(1 for w in words if _FOREIGN_SCRIPT_WORD.search(w))
    if foreign_words < 1:
        return False
    latinish_words = sum(
        1 for w in words
        if sum(1 for c in w if c.isascii() and c.isalpha()) >= 1
        and not _FOREIGN_SCRIPT_WORD.fullmatch(w)
    )
    return latinish_words >= 2 and foreign_words / len(words) < 0.5


def _chunk_has_mixed_latin_foreign(chunk: str) -> bool:
    """Streaming buffer is mostly Latin but contains foreign-script letters."""
    if len(chunk) < 10:
        return False
    latin_letters = 0
    foreign_letters = 0
    for c in chunk:
        if not c.isalpha():
            continue
        tag = _char_script_tag(ord(c))
        if tag == 'lat':
            latin_letters += 1
        elif tag:
            foreign_letters += 1
    if foreign_letters < 1:
        return False
    total = latin_letters + foreign_letters
    return total > 0 and latin_letters / total >= 0.5


def _is_garbled(sentence: str) -> bool:
    if _sentence_has_isolated_foreign_script(sentence):
        return True
    if _MIXED_SCRIPTS.search(sentence):
        return True
    words = sentence.split()
    if len(words) < 4:
        return False
    non_ascii_count = sum(1 for w in words if _NON_ASCII.search(w))
    if (non_ascii_count / len(words)) > 0.3:
        return True
    code_words = sum(
        1 for w in words
        if _PASCAL_CODE.match(w) or _UNDERSCORE_PREFIX.match(w)
        or (_CAMEL_CASE.search(w) and len(w) > 10)
    )
    if code_words >= 2:
        return True
    consecutive_caps = 0
    for w in words:
        if (len(w) > 10 and sum(1 for c in w if c.isupper()) >= 3
                and _CAMEL_CASE.search(w)):
            consecutive_caps += 1
            if consecutive_caps >= 3:
                return True
        else:
            consecutive_caps = 0
    if any(tok in sentence for tok in _GARBLE_TOKENS):
        return True
    return False


def is_chunk_garbled(chunk: str) -> bool:
    """Real-time garble detection for streaming chunks before they reach the client."""
    if len(chunk) < 15:
        return False
    if _chunk_has_mixed_latin_foreign(chunk):
        return True
    words = chunk.split()
    if not words:
        return False

    score = 0

    code_tokens = sum(
        1 for w in words
        if (_CAMEL_CASE.search(w) and len(w) > 8) or ('_' in w and len(w) > 8)
    )
    if code_tokens >= 2:
        score += 2
    elif code_tokens == 1:
        score += 1

    non_ascii = sum(1 for c in chunk if ord(c) > 127)
    if non_ascii / max(len(chunk), 1) > 0.15:
        score += 2

    if any(tok in chunk for tok in _GARBLE_TOKENS):
        score += 3

    if any(len(w) > 25 and not w.startswith('http') for w in words):
        score += 1

    scripts: set[str] = set()
    for c in chunk:
        tag = _char_script_tag(ord(c))
        if tag:
            scripts.add(tag)
    if len(scripts) >= 3:
        score += 2
    if 'lat' in scripts and scripts - {'lat'}:
        score += 3

    return score >= 3


def garble_detection_reason(chunk: str) -> Optional[str]:
    """Telemetry helper: why a chunk was treated as garbled (for [GARBLE] logs)."""
    if not chunk:
        return None
    if _chunk_has_mixed_latin_foreign(chunk):
        return 'foreign_script'
    if is_chunk_garbled(chunk):
        return 'garble_score'
    return None


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
        parts.extend(clean_after)
    if not parts:
        return ""
    return '  '.join(parts)
