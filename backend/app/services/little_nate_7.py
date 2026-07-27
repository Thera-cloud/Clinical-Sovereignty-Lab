"""Little Nate 7 — sovereign coding identity (major fixed at 7; revisions are timestamps).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

PRODUCT_NAME = "Little Nate 7"
PRODUCT_MAJOR = 7  # immutable — never bump
PRODUCT_ID = "ln7"
LN7_NON_CLINICAL_CLAIM = True  # never cite LN7 scores as clinical Tier 2/3 evidence

# Broken Foundry aliases that must not be advertised as selectable
_BROKEN_FOUNDRY_ALIASES = frozenset({"grok-4.5", "grok4.5", "grok-4.5-reasoning"})

# Permissive SPDX allowlist for training / shipped checkpoints
PERMISSIVE_SPDX = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "0BSD",
})


def ln7_enabled() -> bool:
    return os.getenv("ENABLE_LN7", "true").strip().lower() in ("1", "true", "yes", "on")


def harness_enabled() -> bool:
    return ln7_enabled() and os.getenv("ENABLE_LN7_HARNESS", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def bakeoff_enabled() -> bool:
    return ln7_enabled() and os.getenv("ENABLE_LN7_BAKEOFF", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def code_generator_mode() -> str:
    """ln7 (default) | contestant — which path proposes code for CLI."""
    return (os.getenv("CLI_CODE_GENERATOR", "ln7") or "ln7").strip().lower()


def coder_model(tier: str = "deep") -> str:
    """Coder-class Ollama model ids — separate from clinical SOVEREIGN_MODEL_*."""
    t = (tier or "deep").strip().lower()
    if t == "fast":
        return os.getenv("LN7_CODE_MODEL_FAST", "qwen2.5-coder:7b-instruct")
    if t == "mid":
        return os.getenv("LN7_CODE_MODEL_MID", "qwen2.5-coder:14b-instruct-q5_K_M")
    return os.getenv("LN7_CODE_MODEL_DEEP", "qwen2.5-coder:32b-instruct-q5_K_M")


def quantization_floor() -> str:
    """Minimum accepted quant for deep tier (q4 is a regression floor, not a target)."""
    return os.getenv("LN7_QUANT_FLOOR", "q5_K_M")


def is_broken_foundry_alias(model_id: str) -> bool:
    mid = (model_id or "").strip().lower()
    return mid in _BROKEN_FOUNDRY_ALIASES


def contestant_reasoning_model() -> str:
    """Resolved contestant model for LN-FAB/DEBUG when not using LN7.

    Prefer a real Foundry id; reject known-broken grok-4.5 alias.
    """
    raw = (
        os.getenv("NATE_CLI_REASONING_MODEL")
        or os.getenv("NATE_CLI_CODE_MODEL")
        or os.getenv("NATE_CHAT_REASONING_MODEL")
        or ""
    ).strip()
    if is_broken_foundry_alias(raw):
        return (
            os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-reasoning")
            or "grok-4-1-fast-reasoning"
        )
    return raw or os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-reasoning")


def utc_revision_id(when: Optional[datetime] = None) -> str:
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def display_revision(revised_at: Optional[str] = None) -> str:
    ts = (revised_at or "").strip() or "baseline"
    return f"{PRODUCT_NAME}@{ts}"


def to_catalog_entry(
    revised_at: Optional[str] = None,
    revision_id: Optional[str] = None,
    *,
    harness_mode: str = "max",
) -> Dict[str, Any]:
    """Catalog row for the IDE picker (space=ln7)."""
    rid = revision_id or revised_at or "baseline"
    label = f"{PRODUCT_NAME} ({harness_mode})"
    if revised_at:
        label = f"{PRODUCT_NAME} · {revised_at}"
    return {
        "id": f"ln7:{rid}:{harness_mode}",
        "label": label,
        "space": "ln7",
        "provider": "ln7",
        "kind": "chat",
        "agent_eligible": True,
        "source": "ln7_identity",
        "revision_id": rid,
        "revised_at": revised_at or rid,
        "harness_mode": harness_mode,
        "product_major": PRODUCT_MAJOR,
    }


def ln7_catalog_entries(active_revision: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if not ln7_enabled():
        return []
    rev = active_revision or {}
    revised_at = rev.get("revised_at") or rev.get("revision_id") or "baseline"
    rid = rev.get("revision_id") or revised_at
    return [
        to_catalog_entry(revised_at=str(revised_at), revision_id=str(rid), harness_mode="fast"),
        to_catalog_entry(revised_at=str(revised_at), revision_id=str(rid), harness_mode="max"),
    ]


def identity_system_preamble() -> str:
    return (
        f"You are {PRODUCT_NAME} (Sovereign Sanctuary), a sovereign coding system. "
        "You are not Grok, Claude, Fable, Mythos, or any vendor model. "
        "Prefer minimal diffs, tests-first when needed, and never invent file paths."
    )


def model_card_path(revision_id: str) -> str:
    safe = (revision_id or "unknown").replace("/", "_").replace(" ", "_")
    return f"docs/ln7/LN7_{safe}.md"


async def load_active_revision(db_pool) -> Optional[Dict[str, Any]]:
    """Load the active LN7 revision from PG, or None if table/row missing."""
    if db_pool is None:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revision_id, revised_at, base_checkpoint, quantization,
                       harness_config_json, notes, active
                FROM ln7_revisions
                WHERE active = TRUE
                ORDER BY revised_at DESC
                LIMIT 1
                """
            )
        if not row:
            return None
        return dict(row)
    except Exception:
        return None
