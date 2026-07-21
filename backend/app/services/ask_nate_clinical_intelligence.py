"""
Ask Nate (Sovereign Command) — full clinical intelligence context pack.

Assembles client-scoped crystals, main-chat memory, lived wisdom, classroom
context, and Nevedal metrics for coach/admin Ask Nate turns. Returns a
prompt prefix for Cortex.process_interaction plus inspectable meta for the UI.

Future seams (flag-gated, no-op until Phase 5 / agentic flags flip):
  - ENABLE_ASK_NATE_SYMBOLIC → inject typed symbols from conversation metadata
  - ENABLE_ASK_NATE_AGENTIC  → advertise tool capabilities + agent slot envelope
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ask_nate_clinical_intelligence")

# Agentic tool surface contract (declared now; executors land with Phase 2+)
ASK_NATE_AGENT_CAPABILITIES: List[Dict[str, str]] = [
    {"id": "recall_crystals", "status": "live", "desc": "Client crystal field recall"},
    {"id": "recall_main_chat", "status": "live", "desc": "conversation_history turns"},
    {"id": "recall_lived_wisdom", "status": "live", "desc": "Classroom session analyses"},
    {"id": "recall_nevedal_metrics", "status": "live", "desc": "C_emo / GAP / risk snapshot"},
    {
        "id": "symbolic_verify",
        "status": "reserved",
        "desc": "Phase 5b consistency verifier (ENABLE_ASK_NATE_SYMBOLIC)",
    },
    {
        "id": "forward_reason",
        "status": "reserved",
        "desc": "Phase 5c forward constraints (ENABLE_ASK_NATE_SYMBOLIC)",
    },
    {
        "id": "agent_tools",
        "status": "reserved",
        "desc": "Phase 2 tool-use dispatch (ENABLE_ASK_NATE_AGENTIC)",
    },
]

_MAX_PROMPT_CHARS = 14000


def _env_on(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes")


def _capabilities_snapshot() -> List[Dict[str, str]]:
    """QUANTUM-CRYSTAL-ARCH: flip symbolic_verify to live when Ask Nate symbolic is on."""
    caps = [dict(c) for c in ASK_NATE_AGENT_CAPABILITIES]
    if _env_on("ENABLE_ASK_NATE_SYMBOLIC") or _env_on("ENABLE_SYMBOLIC_VERIFIER"):
        for c in caps:
            if c["id"] == "symbolic_verify":
                c["status"] = "live"
                c["desc"] = (
                    "Phase 5b: symbols in prompt + bridge process_interaction verifier"
                )
    return caps


def _ns_snapshot(nevedal_state: Optional[Dict[str, Any]]) -> str:
    ns = nevedal_state or {}
    if not isinstance(ns, dict):
        return ""
    c_emo = ns.get("C_emo")
    gap = ns.get("GAP")
    risk = ns.get("risk_level", "UNKNOWN")
    quantum = ns.get("Quantum")
    bits = []
    if isinstance(c_emo, (int, float)):
        bits.append(f"C_emo={c_emo:.2f}")
    if isinstance(gap, (int, float)):
        bits.append(f"GAP={gap:.2f}")
    if isinstance(quantum, (int, float)):
        bits.append(f"Quantum={quantum:.2f}")
    bits.append(f"risk={risk}")
    pmb = ns.get("pmb") if isinstance(ns.get("pmb"), dict) else {}
    ready = pmb.get("reconsolidation_readiness")
    if isinstance(ready, (int, float)):
        bits.append(f"reconsolidation_readiness={ready:.2f}")
    shame = ns.get("shame_profile") if isinstance(ns.get("shame_profile"), dict) else {}
    si = shame.get("shame_index")
    if isinstance(si, (int, float)):
        bits.append(f"shame_index={si:.2f}")
    return ", ".join(bits)


async def _load_crystals(db_pool, client_id: str, query: str) -> str:
    try:
        from app.websocket.crystal_recall_bridge import recall_crystals_for_context

        ctx = await recall_crystals_for_context(
            db_pool,
            client_id,
            max_results=8,
            source="ask_nate_command",
            query_text=(query or "")[:200],
        )
        return (ctx or "").strip()
    except Exception as e:
        logger.warning("ask_nate: crystal recall failed: %s", e)
        return ""


async def _load_main_chat(db_pool, client_id: str, limit: int = 15) -> str:
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_text, ai_text, created_at
                FROM conversation_history
                WHERE user_id = $1 OR user_id IN (
                    SELECT username FROM users
                    WHERE hardware_id = $1 OR username = $1
                    LIMIT 2
                )
                ORDER BY created_at DESC
                LIMIT $2
                """,
                client_id,
                limit,
            )
        if not rows:
            return ""
        lines: List[str] = []
        for r in reversed(list(rows)):
            ut = (r["user_text"] or "").strip()
            at = (r["ai_text"] or "").strip()
            if ut:
                lines.append(f"Client: {ut[:450]}")
            if at:
                lines.append(f"Nate: {at[:450]}")
        if not lines:
            return ""
        return "[MAIN CHAT MEMORY — recent Sanctuary chat]\n" + "\n".join(lines[-24:])
    except Exception as e:
        logger.warning("ask_nate: conversation_history failed: %s", e)
        return ""


async def _load_lived_wisdom(db_pool, coach_hw: str, client_id: Optional[str]) -> str:
    if not coach_hw:
        return ""
    try:
        from app.services.pg_data_helpers import get_classroom_lived_wisdom_pg

        return (
            await get_classroom_lived_wisdom_pg(
                db_pool, coach_hw, client_id=client_id or None, limit=5
            )
            or ""
        ).strip()
    except Exception as e:
        logger.warning("ask_nate: lived wisdom failed: %s", e)
        return ""


async def _load_classroom(db_pool, client_id: str) -> str:
    try:
        from app.services.pg_data_helpers import get_classroom_context_for_client_pg

        return (await get_classroom_context_for_client_pg(db_pool, client_id, limit=2) or "").strip()
    except Exception as e:
        logger.debug("ask_nate: classroom context: %s", e)
        return ""


async def _load_metrics(db_pool, client_id: str) -> str:
    try:
        from app.services.pg_data_helpers import load_metrics_pg

        metrics = await load_metrics_pg(db_pool, client_id)
        if not metrics:
            return ""
        snap = _ns_snapshot(metrics.get("nevedal_state"))
        if not snap:
            return ""
        return f"[NEVEDAL METRICS SNAPSHOT]\n{snap}"
    except Exception as e:
        logger.debug("ask_nate: metrics: %s", e)
        return ""


async def _load_symbols(db_pool, client_id: str) -> str:
    """Phase 5a seam — read typed symbols already persisted on chat metadata."""
    if not _env_on("ENABLE_ASK_NATE_SYMBOLIC"):
        return ""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT metadata
                FROM conversation_history
                WHERE (user_id = $1 OR user_id IN (
                    SELECT username FROM users
                    WHERE hardware_id = $1 OR username = $1 LIMIT 2
                ))
                AND metadata ? 'symbols'
                ORDER BY created_at DESC
                LIMIT 8
                """,
                client_id,
            )
        symbols: List[Any] = []
        for r in rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if isinstance(meta, dict) and meta.get("symbols"):
                symbols.extend(meta["symbols"] if isinstance(meta["symbols"], list) else [meta["symbols"]])
        if not symbols:
            return ""
        return "[SYMBOLIC LAYER — typed facts from prior turns]\n" + json.dumps(symbols[:20])[:2500]
    except Exception as e:
        logger.debug("ask_nate: symbols: %s", e)
        return ""


def _agentic_envelope(client_id: str, query: str) -> Dict[str, Any]:
    """Reserved agent slot — structure only until ENABLE_ASK_NATE_AGENTIC."""
    caps = _capabilities_snapshot()
    live = [c["id"] for c in caps if c["status"] == "live"]
    reserved = [c["id"] for c in caps if c["status"] == "reserved"]
    enabled = _env_on("ENABLE_ASK_NATE_AGENTIC")
    return {
        "surface": "sovereign_command_ask_nate",
        "agentic_enabled": enabled,
        "client_id": client_id or None,
        "query_preview": (query or "")[:120],
        "tools_live": live,
        "tools_reserved": reserved,
        "neuro_symbolic_ready": _env_on("ENABLE_ASK_NATE_SYMBOLIC"),
        "odpe_domain": "clinical",
        "inference_hint": "TENSION preferred for clinical depth when ODPE classifies tension",
    }


async def build_ask_nate_prompt_pack(
    db_pool,
    *,
    coach_profile: Dict[str, Any],
    client_id: str = "",
    query: str = "",
) -> Dict[str, Any]:
    """
    Build clinical intelligence prefix + UI/agent meta.

    Returns:
      {
        prompt_prefix: str,
        meta: {sources, memory_used, capabilities, agent_envelope, mode},
      }
    """
    coach_hw = (coach_profile or {}).get("hardware_id") or ""
    cid = (client_id or "").strip()
    sources: List[str] = []
    parts: List[str] = []

    header = (
        "[SOVEREIGN COMMAND — ASK LITTLE NATE · ADMIN ADVISORY]\n"
        "You are Little Nate in Sovereign Command (admin portal), advising the ADMIN "
        "(or master coach) — NOT doing therapy with them.\n"
        "Role: advanced Coach Command / operations intelligence — sharper than Insights "
        "or Briefings. Help with coaching strategy, case formulation for the clinician, "
        "population patterns, group/family dynamics, risk flags, session prep, and "
        "general platform or online topics when asked.\n"
        "HARD RULES:\n"
        "- Speak TO the admin as a peer advisor. Never run therapy on the admin "
        "(no 'what feels most important to you', no reflective stalling, no client-mode).\n"
        "- When they paste a client email/letter/transcript: analyze THAT person for "
        "the admin — themes, risks, coaching moves, what to say next, what to avoid.\n"
        "- Be concrete and actionable (bullets OK). Ground in injected memory layers; "
        "if a layer is empty, say so. Never invent sessions, crystals, or metrics.\n"
        "- Scope may be one client, a group/family, the full roster, or a topic — "
        "match the ask. Do not demand the admin pick a feeling before answering.\n"
        "- No banned sanctuary jargon (liminal, threshold, aching).\n"
    )
    parts.append(header)

    if cid:
        crystal = await _load_crystals(db_pool, cid, query)
        if crystal:
            parts.append(crystal)
            sources.append("crystals")

        chat = await _load_main_chat(db_pool, cid)
        if chat:
            parts.append(chat)
            sources.append("main_chat")

        metrics = await _load_metrics(db_pool, cid)
        if metrics:
            parts.append(metrics)
            sources.append("nevedal_metrics")

        classroom = await _load_classroom(db_pool, cid)
        if classroom:
            parts.append(classroom)
            sources.append("classroom")

        wisdom = await _load_lived_wisdom(db_pool, coach_hw, cid)
        if wisdom:
            parts.append(wisdom)
            sources.append("lived_wisdom")

        symbols = await _load_symbols(db_pool, cid)
        if symbols:
            parts.append(symbols)
            sources.append("symbolic_layer")
            # QUANTUM-CRYSTAL-ARCH — Phase 5b Ask Nate symbolic seam
            parts.append(
                "[SYMBOLIC VERIFY — advisory]\n"
                "Treat [SYMBOLIC LAYER] as typed prior facts. Do not contradict them "
                "without saying the memory layer is incomplete. Never invent crisis "
                "resources; if distress is present, cite 988 only when clinically warranted "
                "for the CLIENT (advise the admin — do not therapy the admin)."
            )

        parts.append(
            f"[FOCUS CLIENT ID]: {cid}\n"
            "Advise the admin on how to coach/support this client. "
            "Do not interview the admin as if they were the client."
        )
    else:
        # Cohort / all-clients mode — coach-scoped lived wisdom only (no cross-client PHI dump)
        wisdom = await _load_lived_wisdom(db_pool, coach_hw, None)
        if wisdom:
            parts.append(wisdom)
            sources.append("lived_wisdom_roster")
        parts.append(
            "[FOCUS]: Roster / population / open topic (no single client selected).\n"
            "You may discuss population patterns from lived wisdom, coaching strategy, "
            "or answer general/online topics. Do not invent individual client PHI. "
            "If a named person is required and unknown, say so and ask which client ID."
        )

    agent_envelope = _agentic_envelope(cid, query)
    if _env_on("ENABLE_ASK_NATE_AGENTIC"):
        parts.append(
            "[AGENTIC SLOT — reserved]\n"
            f"Capabilities live: {', '.join(agent_envelope['tools_live'])}. "
            "Tool dispatch is not active; answer from memory context only."
        )
        sources.append("agentic_envelope")

    prompt_prefix = "\n\n".join(p for p in parts if p).strip()
    if len(prompt_prefix) > _MAX_PROMPT_CHARS:
        prompt_prefix = prompt_prefix[:_MAX_PROMPT_CHARS] + "\n…[truncated for token budget]"

    if prompt_prefix and not prompt_prefix.endswith("\n"):
        prompt_prefix += "\n\n"

    return {
        "prompt_prefix": prompt_prefix,
        "meta": {
            "type": "ask_nate_intel_meta",
            "mode": "client" if cid else "roster",
            "client_id": cid or None,
            "sources": sources,
            "memory_used": bool(sources),
            "capabilities": _capabilities_snapshot(),
            "agent_envelope": agent_envelope,
            "flags": {
                "clinical_intel": True,
                "symbolic": _env_on("ENABLE_ASK_NATE_SYMBOLIC"),
                "agentic": _env_on("ENABLE_ASK_NATE_AGENTIC"),
                "symbolic_verifier": _env_on("ENABLE_SYMBOLIC_VERIFIER"),
            },
        },
    }
