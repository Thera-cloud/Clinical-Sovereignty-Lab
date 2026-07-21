"""
Battery item quarantine — prevent test contamination of crystal memory.

QUANTUM-CRYSTAL-ARCH — Tier-1 D.14b (Claude review Priority 2)
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

# Surfaces that must never forge crystals from battery turns
BATTERY_ORIGIN_SURFACES = frozenset({
    "six_quotient_battery",
    "six_quotient_nightly",
    "six_quotient_transfer",
    "six_quotient_weekly",
    "six_quotient_smoke",
})

_BATTERY_MARKERS = (
    "[SIX_QUOTIENT_BATTERY]",
    "six_quotient_battery",
    "grok-judge-v1",
    "rubric_focus:",
)

# Scenario-bank fingerprints often appear as short clinical stems in dry-runs
_SCENARIO_ID_RE = re.compile(r"\b(?:AQ|EQ|IQ|MQ|SQ|CQ)-\d+\b", re.I)


def quarantine_enabled() -> bool:
    v = (os.getenv("SIX_QUOTIENT_BATTERY_QUARANTINE") or "true").strip().lower()
    return v not in ("0", "false", "no", "off")


def is_battery_origin(origin_surface: str = "") -> bool:
    return (origin_surface or "").strip().lower() in BATTERY_ORIGIN_SURFACES


def text_looks_like_battery(user_text: str = "", nate_response: str = "") -> bool:
    blob = f"{user_text or ''}\n{nate_response or ''}"
    if not blob.strip():
        return False
    low = blob.lower()
    for m in _BATTERY_MARKERS:
        if m.lower() in low:
            return True
    # High-signal: explicit battery scenario ids in both sides of exchange
    if _SCENARIO_ID_RE.search(blob) and "scenario" in low:
        return True
    return False


def should_block_crystallize(
    *,
    origin_surface: str = "",
    user_text: str = "",
    nate_response: str = "",
) -> bool:
    if not quarantine_enabled():
        return False
    if is_battery_origin(origin_surface):
        return True
    return text_looks_like_battery(user_text, nate_response)


def crystal_row_is_battery_contaminated(row: Any) -> bool:
    """True if a crystal dict/record should be excluded from recall."""
    if not quarantine_enabled():
        return False
    text = ""
    meta = None
    if isinstance(row, dict):
        text = str(row.get("crystal_text") or row.get("text") or "")
        meta = row.get("metadata") or row.get("meta")
    else:
        text = str(getattr(row, "crystal_text", None) or "")
        meta = getattr(row, "metadata", None)
    if isinstance(meta, str):
        if "six_quotient_battery" in meta.lower():
            return True
    elif isinstance(meta, dict):
        if meta.get("origin_surface") in BATTERY_ORIGIN_SURFACES:
            return True
        if meta.get("six_quotient_battery"):
            return True
    return text_looks_like_battery(text, "")


def filter_crystals(rows: Optional[list]) -> list:
    if not rows:
        return []
    return [r for r in rows if not crystal_row_is_battery_contaminated(r)]
