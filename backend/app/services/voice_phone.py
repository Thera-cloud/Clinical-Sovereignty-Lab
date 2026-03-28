"""
E.164 / digit normalization for Twilio inbound caller → users.profile_data.phone lookup.

Uses the same digit-stripping rule as migration 153 index:
  regexp_replace(COALESCE(profile_data->>'phone', ''), '[^0-9]', '', 'g')
"""

from __future__ import annotations

import re
from typing import List


def phone_digits_only(raw: str) -> str:
    """Keep digits only (empty if none)."""
    return re.sub(r"\D", "", raw or "")


def twilio_lookup_digit_variants(from_field: str) -> List[str]:
    """
    Build candidate digit strings to match against normalized profile phones.

    Twilio ``From`` is typically E.164 (e.g. +14155551234). Profiles may store
    10-digit NANP, +1..., or formatted strings. We try last-10 and full digits
    so index-friendly equality matches work.
    """
    d = phone_digits_only(from_field)
    if not d:
        return []

    candidates: List[str] = []
    if len(d) >= 10:
        candidates.append(d[-10:])
    if len(d) > 10:
        candidates.append(d)
    if len(d) < 10:
        candidates.append(d)

    seen = set()
    uniq: List[str] = []
    for x in candidates:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq
