"""Pseudonymize PII before sending to external model providers.

Slice 3 of the Bee HIV+ privacy plan. Replaces direct identifiers with
salted-hash tokens so a provider (Grok/Azure/Workers AI/Ollama) never
sees the raw email, phone, SSN, DOB, or address. Keeps an in-memory
reversible mapping per request so responses can be restored before the
user sees them.

Feature-flagged via ENABLE_PROVIDER_PSEUDONYMIZATION. Off by default —
zero behavior change until an operator flips the flag.

Legal grounding:
  • HIPAA §164.514(b)(2)(i)(A–R) — direct identifiers (subset).
  • BAA Section 8.7 / 6.6 — pseudonymization to model providers.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "PSEUDO_"

# HIPAA-aligned direct-identifier regexes. Order matters: SSN before generic
# digit-heavy patterns, DOB before addresses, etc.
_PATTERNS: List[tuple[str, "re.Pattern[str]"]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("PHONE", re.compile(
        r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?!\w)"
    )),
    ("DOB", re.compile(
        r"\b(?:\d{1,2}[\/-]\d{1,2}[\/-]\d{2,4}|\d{4}[\/-]\d{1,2}[\/-]\d{1,2})\b"
    )),
    ("ADDR", re.compile(
        r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s+"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|"
        r"Court|Ct|Place|Pl|Terrace|Ter|Highway|Hwy)\b"
    )),
]


def is_enabled() -> bool:
    """Return True when ENABLE_PROVIDER_PSEUDONYMIZATION is truthy."""
    raw = (os.environ.get("ENABLE_PROVIDER_PSEUDONYMIZATION") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _hash(value: str, salt: str) -> str:
    h = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return h[:12]


class PseudonymBook:
    """Reversible mapping for a single inference call.

    The salt is generated fresh per book (process-local, non-persistent) so
    a compromised process memory does not enable cross-session linkage of
    tokens back to identifiers.
    """

    __slots__ = ("salt", "forward", "reverse")

    def __init__(self):
        self.salt = secrets.token_hex(8)
        self.forward: Dict[str, str] = {}
        self.reverse: Dict[str, str] = {}

    def token_for(self, category: str, real_value: str) -> str:
        key = f"{category}:{real_value}"
        cached = self.forward.get(key)
        if cached:
            return cached
        token = f"{_TOKEN_PREFIX}{category}_{_hash(real_value, self.salt)}"
        self.forward[key] = token
        self.reverse[token] = real_value
        return token


def pseudonymize_text(
    text: str,
    book: PseudonymBook,
    known_names: Optional[List[str]] = None,
) -> str:
    """Replace PII in ``text`` with tokens allocated in ``book``.

    Regex-based direct identifiers are always processed. ``known_names``
    (typically the participant's own name from their profile) are matched
    whole-word, case-insensitive, and substituted with per-book NAME
    tokens. Falsy ``text`` is returned unchanged.
    """
    if not text:
        return text

    for category, pattern in _PATTERNS:
        def _sub(m: "re.Match[str]") -> str:
            return book.token_for(category, m.group(0))
        text = pattern.sub(_sub, text)

    if known_names:
        for name in known_names:
            name = (name or "").strip()
            if not name or len(name) < 2:
                continue
            token = book.token_for("NAME", name)
            text = re.sub(
                rf"\b{re.escape(name)}\b",
                token,
                text,
                flags=re.IGNORECASE,
            )
    return text


def pseudonymize_messages(
    messages: List[Dict],
    book: PseudonymBook,
    known_names: Optional[List[str]] = None,
) -> List[Dict]:
    """Return a new list of chat messages with PII replaced by tokens.

    Handles both string ``content`` and multimodal ``content`` lists
    (vision payloads) — non-text parts pass through untouched.
    """
    out: List[Dict] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            out.append({**m, "content": pseudonymize_text(content, book, known_names)})
        elif isinstance(content, list):
            new_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    new_parts.append({
                        **part,
                        "text": pseudonymize_text(part.get("text", ""), book, known_names),
                    })
                else:
                    new_parts.append(part)
            out.append({**m, "content": new_parts})
        else:
            out.append(m)
    return out


# --------------------------------------------------------------------------- #
# Restoration (reverse mapping on the way back)                               #
# --------------------------------------------------------------------------- #

# Any token: PSEUDO_<CATEGORY>_<12hex>. Cat may be extended so allow more.
_TOKEN_RE = re.compile(rf"{_TOKEN_PREFIX}[A-Z]+_[a-f0-9]{{8,16}}")


def restore_text(text: str, book: PseudonymBook) -> str:
    """Reverse-map tokens in ``text`` back to their original identifiers."""
    if not text or not book.reverse:
        return text

    def _un(m: "re.Match[str]") -> str:
        return book.reverse.get(m.group(0), m.group(0))

    return _TOKEN_RE.sub(_un, text)


class StreamRestorer:
    """Stateful restorer for streaming provider output.

    Buffers text chunks until any partial-token tail is either completed
    or clearly cannot become one, then emits the restored portion. Callers
    should ``feed`` each delta and ``flush`` once the stream ends.
    """

    __slots__ = ("_book", "_buffer")

    # Longest legal token today is: "PSEUDO_" (7) + up to 5 cat + "_" + 16 hex = 29
    _MAX_TOKEN_LEN = 40

    def __init__(self, book: PseudonymBook):
        self._book = book
        self._buffer = ""

    def feed(self, delta: str) -> str:
        if not delta:
            return ""
        self._buffer += delta
        return self._drain(final=False)

    def flush(self) -> str:
        return self._drain(final=True)

    def _drain(self, final: bool) -> str:
        if not self._book.reverse:
            out = self._buffer
            self._buffer = ""
            return out

        buf = self._buffer
        if final:
            self._buffer = ""
            return restore_text(buf, self._book)

        idx = buf.rfind(_TOKEN_PREFIX)
        if idx < 0:
            self._buffer = ""
            return restore_text(buf, self._book)

        safe = buf[:idx]
        tail = buf[idx:]

        m = _TOKEN_RE.match(tail)
        if m:
            end = m.end()
            emit = restore_text(safe + tail[:end], self._book)
            self._buffer = tail[end:]
            return emit

        # Tail can't become a valid token — flush it as literal.
        if len(tail) > self._MAX_TOKEN_LEN:
            self._buffer = ""
            return restore_text(safe + tail, self._book)

        self._buffer = tail
        return restore_text(safe, self._book)
