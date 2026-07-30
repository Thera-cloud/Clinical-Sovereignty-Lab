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

# Permissive SPDX allowlist for training / shipped checkpoints.
# FIRST-PARTY is a sentinel (not a real SPDX id) for code mined/authored/mutated
# from this repo's own tree — we hold full rights, no third-party license applies.
PERMISSIVE_SPDX = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "0BSD",
    "FIRST-PARTY",
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


def peft_serve_url_default() -> str:
    """ORANGE PEFT OpenAI-compat base (WireGuard). Empty = disabled."""
    return (os.getenv("LN7_PEFT_URL") or "").rstrip("/")


def serve_target_from_revision(
    revision: Optional[Dict[str, Any]],
    *,
    tier: str = "mid",
) -> Dict[str, str]:
    """Resolve inference URL + model for a revision (PEFT when wired).

    Returns keys: url, model, mode (peft|ollama).
    # QUANTUM-CRYSTAL-ARCH
    """
    hc: Dict[str, Any] = {}
    if revision:
        raw = revision.get("harness_config_json") or revision.get("harness_config") or {}
        if isinstance(raw, str):
            try:
                import json
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if isinstance(raw, dict):
            hc = raw
    peft_url = (hc.get("peft_url") or peft_serve_url_default() or "").rstrip("/")
    peft_model = str(hc.get("peft_model") or os.getenv("LN7_PEFT_MODEL_ID") or "ln7-peft")
    ollama_tag = str(
        hc.get("ollama_tag")
        or (revision or {}).get("serve_checkpoint")
        or ""
    ).strip()
    # Prefer explicit PEFT serve when adapter was trained (nf4_qlora / peft path)
    quant = str((revision or {}).get("quantization") or hc.get("quantization") or "")
    method = str(hc.get("method") or "")
    wants_peft = bool(peft_url) and (
        "qlora" in quant.lower()
        or "peft" in method.lower()
        or bool(hc.get("adapter_dir") or hc.get("durable_store"))
        or bool(hc.get("force_peft"))
    )
    t = (tier or "mid").strip().lower()
    if t in ("mid", "max"):
        t = "deep"
    # QUANTUM-CRYSTAL-ARCH — fast coding → PEFT :11435; deep/max → Ollama 32B
    if wants_peft and peft_url:
        return {"url": peft_url, "model": peft_model, "mode": "peft"}
    if t == "fast":
        peft_fallback = peft_url or peft_serve_url_default()
        if peft_fallback:
            return {"url": peft_fallback, "model": peft_model, "mode": "peft"}
    if ollama_tag and t != "fast":
        base = (
            (os.getenv("LN7_INFERENCE_URL") or "").rstrip("/")
            or (os.getenv("SOVEREIGN_INFERENCE_URL") or "").rstrip("/")
        )
        return {"url": base, "model": ollama_tag, "mode": "ollama"}
    base = (
        (os.getenv("LN7_INFERENCE_URL") or "").rstrip("/")
        or (os.getenv("SOVEREIGN_INFERENCE_URL") or "").rstrip("/")
    )
    return {"url": base, "model": coder_model(t if t in ("fast", "deep") else "deep"), "mode": "ollama"}


def expected_serve_identity(revision: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the served weights must be for this revision to be scored honestly.

    kind='bare'    -> base model with no adapter attached (baseline arms)
    kind='adapter' -> PEFT server must report this exact revision_id
    # QUANTUM-CRYSTAL-ARCH
    """
    rev = revision or {}
    hc: Dict[str, Any] = {}
    raw = rev.get("harness_config_json") or rev.get("harness_config") or {}
    if isinstance(raw, str):
        try:
            import json
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if isinstance(raw, dict):
        hc = raw
    base = str(rev.get("base_checkpoint") or "").strip().lower()
    if base in ("bare_hf", "bare", "base") or bool(hc.get("bare_hf")) or bool(hc.get("bare")):
        return {"kind": "bare", "revision_id": None}
    return {"kind": "adapter", "revision_id": str(rev.get("revision_id") or "").strip()}


async def probe_serve_identity(
    target: Dict[str, str],
    revision: Optional[Dict[str, Any]],
    *,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Assert the endpoint is actually serving the requested revision.

    The PEFT server is single-adapter and boot-pinned: two revisions can resolve
    to the same {url, model} and silently score the *same* weights twice. This
    probes /health and compares the served identity to what was requested.

    Returns: {ok, reason, served, expected, detail}
    # QUANTUM-CRYSTAL-ARCH
    """
    expected = expected_serve_identity(revision)
    mode = str((target or {}).get("mode") or "").strip().lower()
    url = str((target or {}).get("url") or "").rstrip("/")
    if not url:
        return {"ok": False, "reason": "no_serve_url", "served": None, "expected": expected}
    if mode != "peft":
        # Ollama identity is carried by the model tag itself; nothing to cross-check.
        return {
            "ok": True,
            "reason": "ollama_tag_identity",
            "served": {"model": (target or {}).get("model")},
            "expected": expected,
        }

    health: Dict[str, Any] = {}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{url}/health")
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "reason": f"health_http_{resp.status_code}",
                    "served": None,
                    "expected": expected,
                }
            health = resp.json() or {}
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"serve_unreachable:{str(exc)[:120]}",
            "served": None,
            "expected": expected,
        }

    if not bool(health.get("loaded")):
        return {
            "ok": False,
            "reason": f"adapter_not_loaded:{str(health.get('error'))[:120]}",
            "served": health,
            "expected": expected,
        }

    served_bare = bool(health.get("bare"))
    served_rev = str(health.get("revision_id") or "").strip()

    if expected["kind"] == "bare":
        if served_bare:
            return {"ok": True, "reason": "bare_ok", "served": health, "expected": expected}
        return {
            "ok": False,
            "reason": f"serve_mismatch:expected=bare served_adapter={served_rev or 'unknown'}",
            "served": health,
            "expected": expected,
        }

    want = expected["revision_id"]
    if served_bare:
        return {
            "ok": False,
            "reason": f"serve_mismatch:expected={want} served=bare",
            "served": health,
            "expected": expected,
        }
    if want and served_rev != want:
        return {
            "ok": False,
            "reason": f"serve_mismatch:expected={want} served={served_rev or 'unknown'}",
            "served": health,
            "expected": expected,
        }
    return {"ok": True, "reason": "adapter_ok", "served": health, "expected": expected}


async def load_revision(db_pool, revision_id: str) -> Optional[Dict[str, Any]]:
    if not db_pool or not revision_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revision_id, revised_at, base_checkpoint, quantization,
                       harness_config_json, notes, active, status
                FROM ln7_revisions
                WHERE revision_id = $1
                LIMIT 1
                """,
                revision_id,
            )
        return dict(row) if row else None
    except Exception:
        return None


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


async def load_active_revision(
    db_pool,
    *,
    tier: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load the active LN7 revision for a serving tier (fast|deep).

    Milestone A: one active per harness_config.tier; deep default when unset.
    # QUANTUM-CRYSTAL-ARCH
    """
    if db_pool is None:
        return None
    want = (tier or "deep").strip().lower()
    if want in ("mid", "max"):
        want = "deep"
    if want not in ("fast", "deep"):
        want = "deep"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revision_id, revised_at, base_checkpoint, quantization,
                       harness_config_json, notes, active
                FROM ln7_revisions
                WHERE active = TRUE
                  AND COALESCE(NULLIF(TRIM(harness_config_json->>'tier'), ''), 'deep') = $1
                ORDER BY revised_at DESC
                LIMIT 1
                """,
                want,
            )
            if row is None and want == "deep":
                # Pre-migration rows: single global active without tier key
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


def default_incumbent_id(tier: str = "fast") -> str:
    """Promote gate incumbent — fast LoRA never compared to 32B deep baseline."""
    t = (tier or "fast").strip().lower()
    if t in ("deep", "mid", "max"):
        return os.getenv("LN7_DEEP_INCUMBENT_ID", "LN7-baseline")
    return os.getenv("LN7_FAST_INCUMBENT_ID", "LN7-fast-baseline")


def revision_serving_tier(revision: Optional[Dict[str, Any]]) -> str:
    """Extract harness tier from a revision row (default deep)."""
    if not revision:
        return "deep"
    raw = revision.get("harness_config_json") or revision.get("harness_config") or {}
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        return "deep"
    t = str(raw.get("tier") or "").strip().lower()
    if t == "fast":
        return "fast"
    rid = str(revision.get("revision_id") or "")
    if rid == "LN7-fast-baseline" or rid.startswith("LN7-fast"):
        return "fast"
    return "deep"
