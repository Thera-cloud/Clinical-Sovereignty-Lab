"""Sovereign Studio invariants — code-level, not prompt-level. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

LN_COHOST_LABEL = "AI co-host and knowledge companion"
LIVE_TIER_CLEAN_EPISODES = 1
SCREENER_TOKEN_TTL_S = 60
VERTICALS = (
    "life_coaching",
    "grief",
    "relationships_intimacy",
    "trauma_modalities",
    "neuroscience_education",
)

INV6_BLOCKED = re.compile(
    r"\b(clinical|therapy|diagnose|treatment|prescribe|assess your case)\b",
    re.IGNORECASE,
)

STYLE_KEYS = frozenset(
    {
        "tone",
        "cadence",
        "topics",
        "phrases",
        "word_patterns",
        "preface_style",
        "introduction_style",
        "body_style",
        "climax_style",
        "conclusion_style",
        "presence_style",
        "stance",
        "assistant_stance",
        "toss_phrases",
        "signature_frameworks",
        "segment_structure",
        "do_not_say",
        "pacing",
    }
)

WALL_TABLES = (
    "nate_intelligence_crystals",
    "crystal_recall_log",
    "nevedal_metrics",
    "virtual_eeg_traces",
    "user_safety_codewords",
    "user_trigger_dates",
    "user_polyvictimization_layers",
    "user_legal_status",
    "user_parts_registry",
    "addiction_status_history",
    "cross_addiction_transfer_events",
    "sensitive_bridge_log",
    "sensitive_bridge_enrollment",
    "conversation_history",
)

THERAPEUTIC_IMPORT_BAN = (
    "crystal_recall_bridge",
    "therapeutic_controller",
    "sensitive_clinical_bridge",
    "nevedal_engine",
    "neural_mirror",
)


def studio_flag_on() -> bool:
    return os.getenv("ENABLE_SOVEREIGN_STUDIO", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def inv6_blocks(text: str) -> bool:
    return bool(INV6_BLOCKED.search(text or ""))


def guest_video_allowed(role: str, video_track_key: Optional[str]) -> bool:
    if (role or "") != "guest":
        return True
    return video_track_key is None


def show_mode_ok(show_mode: Any) -> bool:
    return show_mode is True


def filter_style_layer(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    rejected: List[str] = []
    cleaned: Dict[str, Any] = {}
    for key, val in (payload or {}).items():
        k = str(key)
        if k.startswith("_guardrail_") or k.startswith("_vertical_"):
            rejected.append(k)
            continue
        if k not in STYLE_KEYS:
            rejected.append(k)
            continue
        cleaned[k] = val
    return cleaned, rejected


def clone_context_allowed(context: str) -> bool:
    return (context or "").strip() != "ln_broadcast"


def override_requires_admin(severity: str) -> bool:
    return (severity or "").strip().lower() == "high"


def live_tier_unlocked(clean_published: int) -> bool:
    return int(clean_published or 0) >= LIVE_TIER_CLEAN_EPISODES


def episode_can_approve(state: str, open_high_or_open_flags: int) -> bool:
    return (state or "") == "in_review" and int(open_high_or_open_flags or 0) == 0


def episode_can_publish(state: str) -> bool:
    return (state or "") == "approved"


def banned_imports_in(text: str) -> List[str]:
    hits = []
    for name in THERAPEUTIC_IMPORT_BAN:
        if name in (text or ""):
            hits.append(name)
    return hits


def wall_table_list() -> Iterable[str]:
    return WALL_TABLES
