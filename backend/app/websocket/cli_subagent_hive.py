"""
CLI Queen / Worker-ant hive helpers.

Queens = CLI-Cloud / CLI-Mac (Grok). Workers = Workers AI subagents.
Pure helpers + provider resolution — no heavy imports at module load.
"""
# QUANTUM-CRYSTAL-ARCH — Workers AI subagent hive (Queen review pattern)

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.cli_subagent_hive")

CLI_MAX_SUBAGENTS_PER_TURN = int(os.getenv("CLI_MAX_SUBAGENTS_PER_TURN", "4"))
CLI_MAX_SUBAGENTS_PER_RUN = int(os.getenv("CLI_MAX_SUBAGENTS_PER_RUN", "8"))
CLI_WORKER_ESCALATE = os.getenv("CLI_WORKER_ESCALATE", "true").strip().lower() in (
    "1", "true", "yes", "on",
)

# Gap 1 — profile → default provider (Queen keeps full on Grok)
PROFILE_PROVIDER: Dict[str, str] = {
    "explore": "workers_ai",
    "test_fix": "workers_ai",
    "full": "grok",
}

_WRITE_PROFILES = frozenset({"test_fix", "full"})


def workers_ai_configured() -> bool:
    return bool(os.getenv("WORKERS_AI_URL", "").strip()) and bool(
        os.getenv("WORKERS_AI_TOKEN", "").strip()
        or os.getenv("WORKERS_AI_API_TOKEN", "").strip()
    )


def resolve_subagent_provider(profile: str, override: str = "") -> str:
    """Gap 1: Workers AI for explore/test_fix; Grok for full. Fallback if unconfigured."""
    ov = (override or "").strip().lower()
    if ov in ("workers_ai", "grok", "azure"):
        if ov == "workers_ai" and not workers_ai_configured():
            return "grok"
        return ov
    prof = profile if profile in PROFILE_PROVIDER else "explore"
    default = PROFILE_PROVIDER[prof]
    if default == "workers_ai" and not workers_ai_configured():
        return "grok"
    return default


def worker_must_sandbox(provider: str, profile: str) -> bool:
    """Q3 / Gap 7: lesser-model writes never hit live trees."""
    return provider == "workers_ai" and profile in _WRITE_PROFILES


def parse_tool_arguments(raw: Any) -> Tuple[Dict[str, Any], bool, Optional[str]]:
    """
    Gap 6: parse tool args; one repair pass for common Workers AI JSON glitches.
    Returns (args, repaired, error_or_none).
    """
    if isinstance(raw, dict):
        return raw, False, None
    text = (raw if isinstance(raw, str) else str(raw or "")).strip()
    if not text:
        return {}, False, None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, False, None
        return {"value": parsed}, True, None
    except (json.JSONDecodeError, TypeError):
        pass

    repaired_text = text
    # trailing commas
    repaired_text = re.sub(r",\s*}", "}", repaired_text)
    repaired_text = re.sub(r",\s*]", "]", repaired_text)
    # single quotes → double (naive)
    if "'" in repaired_text and '"' not in repaired_text:
        repaired_text = repaired_text.replace("'", '"')
    # wrap bare key:value blobs
    if not repaired_text.startswith("{") and ":" in repaired_text:
        repaired_text = "{" + repaired_text + "}"
    try:
        parsed = json.loads(repaired_text)
        if isinstance(parsed, dict):
            return parsed, True, None
        return {"value": parsed}, True, None
    except (json.JSONDecodeError, TypeError) as e:
        return {}, False, f"malformed tool arguments: {e}"


def child_needs_escalation(result: Dict[str, Any]) -> bool:
    """Gap 2 / Q4: escalate Workers AI failures / empty / budget-exhausted to Grok once."""
    if not CLI_WORKER_ESCALATE:
        return False
    if not isinstance(result, dict):
        return True
    if result.get("status") == "error":
        return True
    if result.get("autonomy", {}).get("budget_exhausted"):
        return True
    text = (result.get("response_text") or "").strip()
    if not text and not (result.get("tool_calls") or []):
        return True
    if result.get("status") == "cancelled":
        return True
    return False


def build_worker_brief(
    task: str,
    *,
    profile: str,
    plan_id: str = "",
    session_key: str = "",
    parent_files: Optional[List[Any]] = None,
) -> str:
    """Gap 5: self-contained brief — task + todos + shared facts + file hints."""
    parts = [
        f"[WORKER ANT — profile={profile}]",
        "You are a scoped subagent. Do the assigned task. Cite file:line evidence.",
        "Do NOT claim parent/queen capabilities. Nesting spawn_subagent is forbidden.",
        "",
        "TASK:",
        (task or "").strip(),
    ]
    try:
        from app.websocket.cli_tools import format_open_todos_prompt

        todos = format_open_todos_prompt(plan_id or None)
        if todos:
            parts.extend(["", todos])
    except Exception:
        pass
    try:
        from app.websocket.cli_symbol_store import (
            cli_symbolic_enabled,
            format_symbols_block,
        )

        if cli_symbolic_enabled() and session_key:
            sym = format_symbols_block(session_key)
            if sym:
                parts.extend(["", "[SHARED FACTS — Mac↔Cloud]", sym[:2500]])
    except Exception:
        pass
    hints: List[str] = []
    for f in (parent_files or [])[:12]:
        if isinstance(f, dict) and f.get("path"):
            hints.append(str(f["path"]))
        elif isinstance(f, str) and f.strip():
            hints.append(f.strip())
    if hints:
        parts.extend(["", "PARENT FILES TOUCHED (context):", ", ".join(hints)])
    parts.extend([
        "",
        "OUTPUT CONTRACT: End with a short summary. Prefer path:line citations from tools you ran.",
        "If unsure, say so — Queen will review.",
    ])
    return "\n".join(parts)


_PATH_LINE_RE = re.compile(
    r"(?:^|[\s`])([A-Za-z0-9_./\-]+\.(?:py|dart|ts|tsx|js|jsx|md|yml|yaml|toml|sql|html|css))"
    r"(?::(\d+))?",
)


def extract_line_refs(text: str) -> List[str]:
    refs: List[str] = []
    for m in _PATH_LINE_RE.finditer(text or ""):
        path = m.group(1)
        line = m.group(2)
        refs.append(f"{path}:{line}" if line else path)
    # dedupe preserve order
    seen = set()
    out: List[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out[:40]


def structure_subagent_result(
    *,
    profile: str,
    provider: str,
    escalated: bool,
    result: Dict[str, Any],
    events: Optional[List[Dict[str, Any]]] = None,
    cite_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Gap 4 + 8: structured contract + provider attribution."""
    summary = (result.get("response_text") or "")[:4000]
    tool_calls = result.get("tool_calls") or []
    files = result.get("files") or []
    file_paths: List[str] = []
    for f in files:
        if isinstance(f, dict) and f.get("path"):
            file_paths.append(str(f["path"]))
        elif isinstance(f, str):
            file_paths.append(f)
    line_refs = extract_line_refs(summary)
    for tc in tool_calls:
        if isinstance(tc, dict):
            args = tc.get("args") or {}
            p = args.get("path") or args.get("file_path")
            if p and str(p) not in file_paths:
                file_paths.append(str(p))
    violations = list((cite_meta or {}).get("violations") or [])
    confidence = 0.85
    if violations:
        confidence = max(0.25, 0.85 - 0.1 * len(violations))
    if result.get("status") == "error":
        confidence = min(confidence, 0.2)
    if escalated:
        confidence = min(0.9, confidence + 0.05)

    claims: List[Dict[str, Any]] = []
    for line in (summary or "").splitlines():
        s = line.strip()
        if len(s) < 12:
            continue
        tag = "[INFERRED]" if violations else "[VERIFIED]"
        claims.append({"text": s[:300], "tag": tag})
        if len(claims) >= 12:
            break

    contract = {
        "files": file_paths[:40],
        "line_refs": line_refs,
        "claims": claims,
        "confidence": round(confidence, 2),
        "provider": provider,
        "escalated": escalated,
        "profile": profile,
        "cite_ok": not bool(violations),
        "violations": violations[:10],
    }
    status = "ok" if result.get("status") != "error" else "error"
    body = (
        f"[SUBAGENT {profile} provider={provider}"
        f"{' escalated=grok' if escalated else ''}]\n"
        f"turns={result.get('turn_count', 0)} tools={len(tool_calls)} "
        f"confidence={contract['confidence']}\n"
        f"{summary}"
    )
    return {
        "status": status,
        "result": body,
        "profile": profile,
        "provider": provider,
        "escalated": escalated,
        "turn_count": result.get("turn_count"),
        "tool_calls": tool_calls,
        "files": file_paths,
        "events": (events or [])[-20:],
        "structured": contract,
        "confidence": contract["confidence"],
        "line_refs": line_refs,
        "claims": claims,
    }


def tag_summary_for_queen(summary: str, cite_meta: Dict[str, Any]) -> str:
    """Gap 3: Queen must treat unverified child claims as [INFERRED]."""
    text = summary or ""
    if not cite_meta.get("violations"):
        if text and "[VERIFIED]" not in text and "[INFERRED]" not in text:
            return text + "\n\n[QUEEN NOTE: child citations checked — no violations]"
        return text
    note = (
        "\n\n[QUEEN REVIEW — child output has unverified citations; "
        "treat claims as [INFERRED] until re-verified with tools]\n"
    )
    for v in (cite_meta.get("violations") or [])[:5]:
        note += f"- {v}\n"
    return text + note


def queen_system_addon() -> str:
    try:
        from app.websocket.cli_dual_coo import dual_coo_system_addon

        coo = dual_coo_system_addon()
    except Exception:
        coo = ""
    return (
        "\nHIVE (Workers AI worker ants): spawn_subagent explore/test_fix runs on "
        "Workers AI ($0) by default; full stays on Grok. Workers cannot nest spawn. "
        "Worker writes are sandbox-only and auto-enqueued for bus review. "
        "Treat worker structured.claims tagged [INFERRED] as unverified until you "
        "re-check with tools. Budget: max "
        f"{CLI_MAX_SUBAGENTS_PER_TURN}/turn, {CLI_MAX_SUBAGENTS_PER_RUN}/run.\n"
        + coo
    )
