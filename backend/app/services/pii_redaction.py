"""PII redaction for Sensitive Bridge v1.4+ crisis / coach alert payloads."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Union

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)",
)
_DATE_ISO_RE = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})\b",
)
_DATE_US_RE = re.compile(
    r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
)


def _normalize_hotlines(hotline_numbers: Optional[Iterable[str]]) -> Set[str]:
    out: Set[str] = set()
    if not hotline_numbers:
        return out
    for raw in hotline_numbers:
        if not raw:
            continue
        digits = re.sub(r"\D+", "", str(raw))
        if digits:
            out.add(digits)
        out.add(str(raw).strip())
    return out


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s)


def _generalize_recent_dates(text: str, now: datetime) -> str:
    cutoff = now - timedelta(days=30)

    def repl_iso(m: re.Match) -> str:
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return m.group(0)
        if d >= cutoff.replace(tzinfo=None):
            return "[approximate date]"
        return m.group(0)

    def repl_us(m: re.Match) -> str:
        try:
            mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
            d = datetime(yr, mo, dy, tzinfo=timezone.utc)
        except ValueError:
            return m.group(0)
        if d >= cutoff.replace(tzinfo=None):
            return "[approximate date]"
        return m.group(0)

    text = _DATE_ISO_RE.sub(repl_iso, text)
    text = _DATE_US_RE.sub(repl_us, text)
    return text


def _redact_string(
    s: str,
    *,
    preserve_names: Set[str],
    hotline_digits: Set[str],
    coach_username: str,
    client_username: str,
) -> str:
    if not s:
        return s

    preserve_lower = {x.lower() for x in preserve_names if x}

    def phone_repl(m: re.Match) -> str:
        frag = m.group(0)
        d = _digits_only(frag)
        if any(d == hd or d.endswith(hd) or hd.endswith(d) for hd in hotline_digits if hd):
            return frag
        if len(d) < 7:
            return frag
        return "[phone]"

    out = _PHONE_RE.sub(phone_repl, s)

    def email_repl(m: re.Match) -> str:
        em = m.group(0).lower()
        for safe in preserve_lower:
            if safe and "@" in safe and em == safe:
                return m.group(0)
        return "[email]"

    out = _EMAIL_RE.sub(email_repl, out)

    # NER-light: Title Case / ALLCAPS tokens >= 3 chars (skip coach/client first names if matched alone — heuristic)
    def name_repl(m: re.Match) -> str:
        word = m.group(0)
        low = word.lower()
        if low in preserve_lower:
            return word
        if len(word) < 3:
            return word
        return "[name]"

    out = re.sub(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b", name_repl, out)

    # Rough street address (number + street)
    out = re.sub(
        r"\b\d{1,5}\s+[A-Za-z0-9.]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd)\b",
        "[address]",
        out,
        flags=re.IGNORECASE,
    )

    out = _generalize_recent_dates(out, datetime.now(timezone.utc))
    return out


def _walk_redact(
    obj: Any,
    *,
    preserve_names: Set[str],
    hotline_digits: Set[str],
    coach_username: str,
    client_username: str,
) -> Any:
    if isinstance(obj, str):
        return _redact_string(
            obj,
            preserve_names=preserve_names,
            hotline_digits=hotline_digits,
            coach_username=coach_username,
            client_username=client_username,
        )
    if isinstance(obj, list):
        return [
            _walk_redact(
                x,
                preserve_names=preserve_names,
                hotline_digits=hotline_digits,
                coach_username=coach_username,
                client_username=client_username,
            )
            for x in obj
        ]
    if isinstance(obj, dict):
        return {
            k: _walk_redact(
                v,
                preserve_names=preserve_names,
                hotline_digits=hotline_digits,
                coach_username=coach_username,
                client_username=client_username,
            )
            for k, v in obj.items()
        }
    return obj


def redact_pii(
    turns: List[Dict[str, Any]],
    hotline_numbers: Optional[Iterable[str]] = None,
    coach_username: str = "",
    client_username: str = "",
) -> List[Dict[str, Any]]:
    """Redact third-party PII from structured conversation turns for coach-visible alerts.

    URLs are preserved by avoiding blanket URL stripping; phone regex skips known hotlines.
    """
    hot_set = _normalize_hotlines(hotline_numbers)
    preserve: Set[str] = set()
    if coach_username:
        preserve.add(coach_username)
        for part in coach_username.replace("_", " ").split():
            preserve.add(part)
    if client_username:
        preserve.add(client_username)
        for part in client_username.replace("_", " ").split():
            preserve.add(part)

    cloned: Union[List[Dict[str, Any]], Any] = copy.deepcopy(turns)
    return _walk_redact(
        cloned,
        preserve_names=preserve,
        hotline_digits=hot_set,
        coach_username=coach_username,
        client_username=client_username,
    )


def redact_pii_json_payload(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Redact values inside a dict by round-tripping through JSON string scan."""
    raw = json.dumps(payload, default=str)
    hot_set = _normalize_hotlines(kwargs.get("hotline_numbers"))
    preserve: Set[str] = set()
    cu = kwargs.get("coach_username") or ""
    cl = kwargs.get("client_username") or ""
    if cu:
        preserve.add(cu)
    if cl:
        preserve.add(cl)
    red = _redact_string(
        raw,
        preserve_names=preserve,
        hotline_digits=hot_set,
        coach_username=cu,
        client_username=cl,
    )
    try:
        return json.loads(red)
    except json.JSONDecodeError:
        return {"redacted_text": red}
