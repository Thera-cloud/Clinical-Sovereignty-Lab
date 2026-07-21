"""
Battery item quarantine — prevent test contamination of crystal memory.

Also quarantines human-gold worksheet stems so gold cannot leak into harvest.

QUANTUM-CRYSTAL-ARCH — Tier-1 D.14b (Claude review Priority 2 / Fable provenance)
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

# Surfaces that must never forge crystals from battery turns
BATTERY_ORIGIN_SURFACES = frozenset({
    "six_quotient_battery",
    "six_quotient_nightly",
    "six_quotient_transfer",
    "six_quotient_weekly",
    "six_quotient_smoke",
    "six_quotient_human_gold",
})

_BATTERY_MARKERS = (
    "[SIX_QUOTIENT_BATTERY]",
    "six_quotient_battery",
    "grok-judge-v1",
    "rubric_focus:",
    "battery-validated weakness",
    "battery_validated_weakness",
    "[SIX_QUOTIENT_HUMAN_GOLD]",
    "gold_admin_run:",
    "six_quotient_gold_admin",
)

# Scenario-bank fingerprints often appear as short clinical stems in dry-runs
_SCENARIO_ID_RE = re.compile(r"\b(?:AQ|EQ|IQ|MQ|SQ|CQ)-(?:G?\d+|\d+)\b", re.I)
_GOLD_RUN_RE = re.compile(r"\bgold[_-]?admin[_-]?run[_:=]\s*([A-Za-z0-9_-]{6,})\b", re.I)


@lru_cache(maxsize=1)
def _gold_stem_fingerprints() -> frozenset[str]:
    """Stem + distractor response fingerprints — gold that leaks stops being gold."""
    data_dirs = (
        Path(__file__).resolve().parents[1] / "data",
        Path("/app/app/data"),
        Path("/app/data"),
    )
    out: set[str] = set()
    for base in data_dirs:
        stems_p = base / "six_quotient_human_gold_stems_v1.json"
        if stems_p.is_file():
            try:
                data = json.loads(stems_p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            for s in data.get("stems") or []:
                text = str(s.get("client_says") or "").strip()
                if len(text) >= 40:
                    out.add(text[:80].lower())
            break
    for base in data_dirs:
        deg_p = base / "six_quotient_gold_degraded_distractors_v1.json"
        if deg_p.is_file():
            try:
                data = json.loads(deg_p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            for d in data.get("distractors") or []:
                text = str(d.get("nate_response") or "").strip()
                if len(text) >= 40:
                    out.add(text[:80].lower())
            break
    return frozenset(out)


def text_matches_gold_stem(user_text: str = "", nate_response: str = "") -> bool:
    blob = f"{user_text or ''}\n{nate_response or ''}".lower()
    if len(blob.strip()) < 40:
        return False
    for fp in _gold_stem_fingerprints():
        if fp and fp in blob:
            return True
    return False


def mentions_gold_admin_run(
    user_text: str = "",
    nate_response: str = "",
    *,
    gold_admin_run_id: str = "",
    session_id: str = "",
) -> bool:
    """Quarantine by gold administration run/session id — not stem text alone."""
    if (gold_admin_run_id or "").strip():
        return True
    sid = (session_id or "").strip().lower()
    if sid.startswith("gold_") or "gold_admin" in sid:
        return True
    blob = f"{user_text or ''}\n{nate_response or ''}"
    return bool(_GOLD_RUN_RE.search(blob))


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
    gold_admin_run_id: str = "",
    session_id: str = "",
) -> bool:
    if not quarantine_enabled():
        return False
    if is_battery_origin(origin_surface):
        return True
    if mentions_gold_admin_run(
        user_text,
        nate_response,
        gold_admin_run_id=gold_admin_run_id,
        session_id=session_id,
    ):
        return True
    if text_matches_gold_stem(user_text, nate_response):
        return True
    return text_looks_like_battery(user_text, nate_response)


def _meta_dict(meta: Any) -> dict:
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str):
        low = meta.lower()
        if any(s in low for s in BATTERY_ORIGIN_SURFACES):
            return {"source": "six_quotient_battery"}
        if "six_quotient_battery" in low:
            return {"source": "six_quotient_battery"}
        return {}
    return {}


def crystal_row_is_battery_contaminated(row: Any) -> bool:
    """True if a crystal dict/record should be excluded from recall."""
    if not quarantine_enabled():
        return False
    text = ""
    meta = None
    origin = ""
    if isinstance(row, dict):
        text = str(row.get("crystal_text") or row.get("text") or "")
        meta = row.get("metadata") or row.get("meta")
        origin = str(row.get("origin_surface") or "")
    else:
        text = str(getattr(row, "crystal_text", None) or "")
        meta = getattr(row, "metadata", None)
        origin = str(getattr(row, "origin_surface", None) or "")

    if is_battery_origin(origin):
        return True

    md = _meta_dict(meta)
    if md:
        if md.get("origin_surface") in BATTERY_ORIGIN_SURFACES:
            return True
        if md.get("six_quotient_battery"):
            return True
        if md.get("gold_admin_run_id") or md.get("six_quotient_gold_admin"):
            return True
        src = str(md.get("source") or "").strip().lower()
        if src in BATTERY_ORIGIN_SURFACES or src == "six_quotient_battery":
            return True
        if "gold_admin" in src:
            return True
    elif isinstance(meta, str) and (
        "six_quotient_battery" in meta.lower() or "gold_admin_run" in meta.lower()
    ):
        return True

    if mentions_gold_admin_run(text, ""):
        return True
    if text_matches_gold_stem(text, ""):
        return True
    return text_looks_like_battery(text, "")


def filter_crystals(rows: Optional[list]) -> list:
    if not rows:
        return []
    return [r for r in rows if not crystal_row_is_battery_contaminated(r)]
