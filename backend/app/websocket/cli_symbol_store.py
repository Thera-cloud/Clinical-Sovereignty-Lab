"""
CLI neuro-symbolic fact store (Redis) — Phase 5b/c equivalents for code.

Per-session typed facts: path→hash, test→status, flag→value, tool→summary.
symbolic_verify rejects claims that contradict the store.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FACT_TTL_S = int(os.getenv("CLI_SYMBOL_TTL", "86400"))


def cli_symbolic_enabled() -> bool:
    return os.getenv("ENABLE_ASK_NATE_SYMBOLIC", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def forward_reasoning_cli_enabled() -> bool:
    return os.getenv("ENABLE_FORWARD_REASONING", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env() -> str:
    return os.getenv("ENVIRONMENT", "production")


def _prefix() -> str:
    return os.getenv("REDIS_KEY_PREFIX", "nate")


def symbols_key(session_key: str) -> str:
    return f"{_prefix()}:{_env()}:cli:symbols:{session_key}"


def _redis():
    if os.getenv("REDIS_URL", "__unset__") == "":
        return None
    try:
        import redis as sync_redis

        url = os.getenv("REDIS_URL", "")
        if not url:
            return None
        return sync_redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=0.5,
        )
    except Exception:
        return None


def load_facts(session_key: str) -> List[Dict[str, Any]]:
    c = _redis()
    if not c or not session_key:
        return []
    try:
        raw = c.get(symbols_key(session_key))
        if not raw:
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug("cli_symbol_store load: %s", e)
        return []


def save_facts(session_key: str, facts: List[Dict[str, Any]]) -> None:
    c = _redis()
    if not c or not session_key:
        return
    try:
        # Cap store size
        trimmed = facts[-200:]
        c.setex(symbols_key(session_key), FACT_TTL_S, json.dumps(trimmed, default=str))
    except Exception as e:
        logger.debug("cli_symbol_store save: %s", e)


def assert_fact(
    session_key: str,
    *,
    kind: str,
    key: str,
    value: Any,
    source: str = "",
) -> Dict[str, Any]:
    """Upsert a typed fact. kind ∈ {path_hash, test_status, flag_value, tool_result, premise}."""
    if not cli_symbolic_enabled():
        return {"status": "skipped", "reason": "ENABLE_ASK_NATE_SYMBOLIC off"}
    facts = load_facts(session_key)
    key_n = (key or "").strip()
    kind_n = (kind or "premise").strip()
    replaced = False
    for f in facts:
        if f.get("kind") == kind_n and f.get("key") == key_n:
            f["value"] = value
            f["source"] = source
            f["updated_at"] = time.time()
            replaced = True
            break
    if not replaced:
        facts.append({
            "kind": kind_n,
            "key": key_n,
            "value": value,
            "source": source,
            "created_at": time.time(),
            "updated_at": time.time(),
        })
    save_facts(session_key, facts)
    return {"status": "ok", "kind": kind_n, "key": key_n, "value": value}


def format_symbols_block(session_key: str, extra: Optional[List[Any]] = None) -> str:
    facts = load_facts(session_key)
    if extra:
        facts = list(facts) + [
            {"kind": "session_meta", "key": f"extra_{i}", "value": x}
            for i, x in enumerate(extra[:20])
        ]
    if not facts:
        return ""
    return (
        "[CLI SYMBOLIC LAYER — typed facts; do not contradict these]\n"
        + json.dumps(facts[:40], default=str)[:3000]
    )


def auto_assert_from_tool(
    session_key: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Any,
) -> None:
    """Derive facts from tool results (best-effort)."""
    if not cli_symbolic_enabled() or not session_key:
        return
    status = "ok"
    content = ""
    if isinstance(result, dict):
        status = str(result.get("status") or "ok")
        content = str(
            result.get("content")
            or result.get("result")
            or result.get("output")
            or ""
        )[:2000]
    else:
        content = str(result or "")[:2000]

    path = (
        (tool_args or {}).get("path")
        or (tool_args or {}).get("file_path")
        or (tool_args or {}).get("target_file")
        or ""
    )
    if path and tool_name in ("read_file", "write_file", "str_replace", "delete_file"):
        h = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
        assert_fact(
            session_key, kind="path_hash", key=str(path), value=h, source=tool_name,
        )
    if tool_name in ("shell",) and ("pytest" in content.lower() or "passed" in content.lower()):
        passed = "failed" not in content.lower()[:500] or "passed" in content.lower()
        assert_fact(
            session_key,
            kind="test_status",
            key="last_pytest",
            value="pass" if passed and status == "ok" else "fail",
            source="shell",
        )
    if tool_name == "self_capabilities" and content:
        # Capture key flags as facts
        for flag in (
            "ENABLE_ASK_NATE_SYMBOLIC",
            "ENABLE_FORWARD_REASONING",
            "mac_cloud_ln_fab_partnership",
            "wired_into_cli_loop",
            "shared_task_bus",
        ):
            m = re.search(rf'"{flag}"\s*:\s*(true|false)', content, re.I)
            if m:
                assert_fact(
                    session_key,
                    kind="flag_value",
                    key=flag,
                    value=m.group(1).lower() == "true",
                    source="self_capabilities",
                )
    assert_fact(
        session_key,
        kind="tool_result",
        key=f"{tool_name}:{int(time.time())}",
        value={"status": status, "excerpt": content[:240]},
        source=tool_name,
    )


_FALSE_CLAIM_PATTERNS = [
    (
        re.compile(r"(?i)\b(workers\s*ai)\b.{0,40}\b(cli|primary|wired)\b"),
        "workers_ai_in_cli_loop",
        False,
    ),
    (
        re.compile(r"(?i)\bmac.?cloud\b.{0,40}\b(partner|partnership)\b.{0,20}\b(active|enabled|true|can)\b"),
        "mac_cloud_ln_fab_partnership",
        False,
    ),
    (
        re.compile(r"(?i)\bwired_into_cli_loop\b.{0,10}\btrue\b"),
        "wired_into_cli_loop",
        None,  # check against store
    ),
]


def symbolic_verify(
    draft: str,
    session_key: str,
    *,
    tool_call_log: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Consistency / contradiction checks over draft output vs fact store + tool evidence.
    Returns {ok, violations[], premises[]}.
    """
    draft = draft or ""
    facts = load_facts(session_key)
    by_flag = {
        f["key"]: f["value"]
        for f in facts
        if f.get("kind") == "flag_value"
    }
    violations: List[Dict[str, str]] = []
    premises: List[str] = []

    # Flag contradictions from store
    for pat, flag_key, expected in _FALSE_CLAIM_PATTERNS:
        if not pat.search(draft):
            continue
        stored = by_flag.get(flag_key)
        if expected is False and (stored is False or stored is None):
            # Claiming partnership/workers when store says false / unknown
            if stored is False or (
                flag_key in ("mac_cloud_ln_fab_partnership", "workers_ai_in_cli_loop")
                and "true" in draft.lower()
            ):
                violations.append({
                    "type": "symbol_contradiction",
                    "detail": f"Draft claims {flag_key} active but fact store has {stored!r}",
                })
        if expected is None and stored is False:
            violations.append({
                "type": "symbol_contradiction",
                "detail": f"Draft claims {flag_key}=true but fact store is false",
            })

    # Explicit false-flag claims when store says false
    for flag_key, val in by_flag.items():
        if val is False:
            # "X is true/enabled/active" near the flag name
            if re.search(
                rf"(?i){re.escape(flag_key)}.{{0,30}}\b(true|enabled|active|on)\b",
                draft,
            ):
                violations.append({
                    "type": "symbol_contradiction",
                    "detail": f"Draft asserts {flag_key} on; fact store value is false",
                })

    # Test status: claim "all tests pass" when last_pytest is fail
    test_facts = [f for f in facts if f.get("kind") == "test_status"]
    for tf in test_facts:
        if tf.get("value") == "fail" and re.search(
            r"(?i)\b(all tests? pass|tests? (are )?green|pytest.*pass)\b", draft,
        ):
            violations.append({
                "type": "symbol_contradiction",
                "detail": "Draft claims tests pass but fact store last_pytest=fail",
            })

    # Tool evidence: if log empty but draft cites [VERIFIED tool=...]
    log = tool_call_log or []
    tools = {str(t.get("name") or "") for t in log}
    for m in re.finditer(r"\[VERIFIED\s+tool=([a-zA-Z0-9_]+)\]", draft, re.I):
        tname = m.group(1)
        if tname not in tools:
            violations.append({
                "type": "symbol_missing_premise",
                "detail": f"[VERIFIED tool={tname}] but tool not in this turn's log",
            })
        else:
            premises.append(f"tool:{tname}")

    for f in facts[-12:]:
        premises.append(f"{f.get('kind')}:{f.get('key')}={f.get('value')!r}"[:120])

    return {
        "status": "ok",
        "ok": len(violations) == 0,
        "violations": violations[:16],
        "premises": premises[:24],
        "fact_count": len(facts),
    }


def forward_reason(
    session_key: str,
    *,
    goal: str = "",
    tool_call_log: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Constraint chain: premises from tool outputs → derived assertions only.
    Does not invent facts outside the premise set.
    """
    if not forward_reasoning_cli_enabled() and not cli_symbolic_enabled():
        return {
            "status": "error",
            "error": "ENABLE_FORWARD_REASONING / ENABLE_ASK_NATE_SYMBOLIC off",
        }
    facts = load_facts(session_key)
    log = tool_call_log or []
    premises: List[Dict[str, Any]] = []
    for t in log:
        name = t.get("name")
        excerpt = (t.get("evidence_excerpt") or "")[:400]
        premises.append({
            "type": "tool_output",
            "tool": name,
            "excerpt": excerpt,
            "status": t.get("status"),
        })
    for f in facts:
        if f.get("kind") in ("path_hash", "test_status", "flag_value", "premise"):
            premises.append({
                "type": "stored_fact",
                "kind": f.get("kind"),
                "key": f.get("key"),
                "value": f.get("value"),
            })

    derived: List[Dict[str, Any]] = []
    # Deterministic derivations only
    flag_vals = {
        p["key"]: p["value"]
        for p in premises
        if p.get("type") == "stored_fact" and p.get("kind") == "flag_value"
    }
    if flag_vals.get("shared_task_bus") and flag_vals.get("cross_cli_review_loop"):
        derived.append({
            "assertion": "mac_cloud_ln_fab_partnership_eligible",
            "from": ["shared_task_bus", "cross_cli_review_loop"],
            "instruction": "Partnership may be stated as active only if both bus probes are true.",
        })
    elif "shared_task_bus" in flag_vals or any(
        p.get("key") == "shared_task_bus" for p in premises if p.get("type") == "stored_fact"
    ):
        if flag_vals.get("shared_task_bus") is False:
            derived.append({
                "assertion": "no_partnership",
                "from": ["shared_task_bus=false"],
                "instruction": "Label Mac↔Cloud partnership [NOT IMPLEMENTED].",
            })

    test_fail = any(
        p.get("kind") == "test_status" and p.get("value") == "fail"
        for p in premises if p.get("type") == "stored_fact"
    )
    if test_fail:
        derived.append({
            "assertion": "tests_not_green",
            "from": ["last_pytest=fail"],
            "instruction": "Do not claim completion; keep retry-until-green.",
        })

    if goal:
        derived.append({
            "assertion": "goal_scoped",
            "from": ["user_goal"],
            "instruction": f"Only derive claims that support: {goal[:200]}",
        })

    # Persist derived as premises for later verify
    for d in derived:
        assert_fact(
            session_key,
            kind="premise",
            key=str(d.get("assertion")),
            value=d.get("instruction"),
            source="forward_reason",
        )

    block = "[FORWARD REASONING — derived assertions only; do not invent beyond premises]\n"
    block += json.dumps({"premises": premises[:30], "derived": derived}, default=str)[:3500]
    return {
        "status": "ok",
        "result": block,
        "premise_count": len(premises),
        "derived": derived,
    }


def probe_wired_into_cli_loop(tool_names: Optional[List[str]] = None) -> bool:
    """True only when flag on AND symbolic_verify tool is registered."""
    if not cli_symbolic_enabled():
        return False
    names = set(tool_names or [])
    return "symbolic_verify" in names
