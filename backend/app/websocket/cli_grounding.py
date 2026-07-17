"""
CLI truth-grounding: capability manifest + claim validation.

Keeps CLI-Mac / CLI-Cloud from inventing aspirational or false present-tense
capabilities. Machine facts come from code/flags; prose claims are scanned.
"""
# SOVEREIGN-VOICE — CLI evidence-gated accuracy

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Evidence tags the model must use (prompt contract)
VERIFIED_TAG = "[VERIFIED"
FLAG_OFF_TAG = "[FLAG-OFF]"
NOT_IMPLEMENTED_TAG = "[NOT IMPLEMENTED]"
PLANNED_TAG = "[PLANNED]"
DESIGN_PROPOSAL_TAG = "[DESIGN PROPOSAL]"
UNVERIFIED_TAG = "[UNVERIFIED]"

_EVIDENCE_TOOLS = frozenset({
    "self_capabilities",
    "read_file",
    "grep",
    "glob",
    "repo_map",
    "search_code",
    "list_directory",
    "shell",
    "read_lints",
    "provider_stats",
    "sandbox_diff",
    "build_status",
    "build_test",
})

_CAPABILITY_QUESTION_RE = re.compile(
    r"\b("
    r"what (can|are) you|"
    r"your (capabilities|features|state|status)|"
    r"neuro[- ]?symbolic|"
    r"phase\s*\d|"
    r"do you support|"
    r"are you (able|capable)|"
    r"partner(ship)? with|"
    r"cli[- ]?(mac|cloud).*(can|level|differ)|"
    r"current (state|level) of"
    r")\b",
    re.I,
)

_SPECULATIVE_QUESTION_RE = re.compile(
    r"\b("
    r"what would|"
    r"how (could|would|might)|"
    r"could you|"
    r"would it|"
    r"if we|"
    r"propose|"
    r"design|"
    r"roadmap|"
    r"future|"
    r"aspirational"
    r")\b",
    re.I,
)

# Present-tense capability / completion claims without evidence
_CAPABILITY_CLAIM_RE = re.compile(
    r"(?i)\b("
    r"i (can|am able to|support|have|provide)|"
    r"we (can|support|have|provide)|"
    r"is implemented|"
    r"are implemented|"
    r"currently (supports?|has|provides?)|"
    r"fully (agentic|implemented|wired)|"
    r"neuro[- ]?symbolic (layer|state|level)|"
    r"phase\s*[5abcd]\b|"
    r"partnership (is|exists|works)|"
    r"dual[- ]agent|"
    r"continuously enhance"
    r")\b",
)

_COMPLETION_CLAIM_RE = re.compile(
    r"(?i)\b("
    r"done|complete|completed|implemented|fixed|shipped|landed|merged|deployed|ready"
    r")\b",
)

_COMMIT_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
_UNCOMMITTED_RE = re.compile(r"(?i)\b(pending commit|uncommitted|not committed yet)\b")

ACCURACY_CONTRACT = """
YOUR ACCURACY RULES (MANDATORY — violation = falsehood):
1. Codebase facts: Before asserting what code does/contains, call read_file, grep, glob, or repo_map in this turn. Cite as [VERIFIED path:line] or [VERIFIED tool=name].
2. Self-capabilities: Answers about what you can do, your neuro-symbolic state, Phase N status, Mac vs Cloud differences, or partner APIs MUST call self_capabilities first and answer ONLY from that tool output. Never invent features from training memory.
3. Flag-gated seams: If a flag is false/off, say [FLAG-OFF]. Never describe flag-off code as active.
4. Missing features: Say [NOT IMPLEMENTED]. Planned-but-unbuilt work is [PLANNED], never present-tense "we have".
5. Speculative / design answers: Prefix with [DESIGN PROPOSAL]. Never describe proposals as current behavior.
6. Completion claims (done/fixed/deployed/implemented): Require a commit hash in the same answer OR say "pending commit (uncommitted)". Tool test exit codes count as evidence for "tests pass" only.
7. Untagged capability assertions are forbidden. If unsure, say "I don't have verified evidence" and call a tool.
""".strip()

VERIFICATION_BEFORE_CLAIM = """
VERIFICATION-BEFORE-CLAIM:
- "Feature exists" → grep or read_file hit required.
- "Flag is on" → self_capabilities or env evidence required.
- "Deployed / on GREEN" → shell or verified hash evidence required; else "not verified on GREEN".
- "Tests pass" → pytest/build_test tool result with exit_code 0 in this conversation.
Where a tool can answer, you MUST use the tool; answering from memory alone is forbidden.
""".strip()

DESIGN_DISCIPLINE = """
SPECULATION DISCIPLINE:
- Questions with "what would / how could / propose / design / roadmap / future" → answer as [DESIGN PROPOSAL] only.
- Do not blend design proposals into present-tense capability lists.
- Temperature of confidence: never use "clearly/obviously/definitely" for unverified claims.
""".strip()


def is_capability_question(text: str) -> bool:
    return bool(text and _CAPABILITY_QUESTION_RE.search(text))


def is_speculative_question(text: str) -> bool:
    return bool(text and _SPECULATIVE_QUESTION_RE.search(text))


def _env_on(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _load_agentic_capabilities_safe() -> Dict[str, Any]:
    """Parse AGENTIC_CAPABILITIES from agents_api.py without importing the router."""
    try:
        from pathlib import Path

        api_path = Path(__file__).resolve().parents[1] / "routers" / "agents_api.py"
        src = api_path.read_text(encoding="utf-8")
        m = re.search(
            r"AGENTIC_CAPABILITIES\s*=\s*\{([^}]+)\}",
            src,
            re.S,
        )
        if not m:
            return {"_note": "AGENTIC_CAPABILITIES block not found"}
        caps: Dict[str, Any] = {}
        for km in re.finditer(r'["\'](\w+)["\']\s*:\s*(True|False)', m.group(1)):
            caps[km.group(1)] = km.group(2) == "True"
        caps["cli_truth_grounding"] = True
        return caps
    except Exception as e:
        return {"_note": f"agents_api capabilities unavailable: {e}", "cli_truth_grounding": True}


def build_capabilities_manifest(
    mode: str,
    cli_type: str,
    *,
    tool_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Machine-readable facts about this CLI session — source of truth for self-claims."""
    if tool_names is None:
        try:
            from app.websocket.cli_tools import get_tool_definitions

            tool_names = sorted(
                {
                    (t.get("function") or {}).get("name")
                    for t in get_tool_definitions(mode, cli_type)
                    if (t.get("function") or {}).get("name")
                }
            )
        except Exception as e:
            tool_names = []
            tool_err = str(e)
        else:
            tool_err = None
    else:
        tool_err = None

    # Prefer lightweight source parse — importing agents_api can pull heavy deps.
    agentic_caps: Dict[str, Any] = _load_agentic_capabilities_safe()

    clinical_symbolic = {
        "ENABLE_ASK_NATE_SYMBOLIC": _env_on("ENABLE_ASK_NATE_SYMBOLIC"),
        "ENABLE_FORWARD_REASONING": _env_on("ENABLE_FORWARD_REASONING"),
        "ENABLE_ASK_NATE_CLINICAL_INTEL": _env_on("ENABLE_ASK_NATE_CLINICAL_INTEL", "true"),
        "wired_into_cli_loop": False,
        "note": (
            "Clinical Ask Nate Phase 5a–d seams are separate from CLI. "
            "CLI does not call ask_nate_clinical_intelligence or nate_forward_reasoning."
        ),
    }

    cli_phase5_tools = {
        "meaning": "Cursor-parity coding tools (str_replace/grep/shell/etc), NOT neuro-symbolic Phase 5",
        "tools_present": [
            n for n in (tool_names or [])
            if n in ("str_replace", "grep", "glob", "shell", "read_lints", "delete_file")
        ],
    }

    providers = {
        "cli_stream_providers": ["grok", "azure"],
        "workers_ai_in_cli_loop": False,
        "sovereign_chat_client_in_cli_loop": False,
        "NATE_CHAT_URL_set": bool(os.getenv("NATE_CHAT_URL")),
        "CLI_REASONING_PREFER_AZURE": os.getenv("CLI_REASONING_PREFER_AZURE", "1"),
        "NATE_CLI_REASONING_MODEL_set": bool(
            os.getenv("NATE_CLI_REASONING_MODEL") or os.getenv("NATE_CHAT_REASONING_MODEL")
        ),
        "note": "CLI uses direct Grok/Azure streaming; Workers AI is not on this path.",
    }

    mac_cloud = {
        "same_agentic_loop": True,
        "cli_type": cli_type,
        "mode": mode,
        "mac_writes": "live workspace via Mac agent when online",
        "cloud_writes": "sandbox worktree when CLI_CLOUD_SANDBOX_WRITES=1 and mode=ln_fab",
        "mac_cloud_ln_fab_partnership": False,
        "shared_task_bus": False,
        "cross_cli_review_loop": False,
        "note": (
            "CLI-Mac and CLI-Cloud are the same run_agentic_loop with different tool "
            "surfaces. Dual LN-FAB partnership is NOT IMPLEMENTED."
        ),
    }

    return {
        "object": "cli.self_capabilities",
        "cli": cli_type,
        "mode": mode,
        "tools": tool_names or [],
        "tool_load_error": tool_err,
        "agentic_api_capabilities": agentic_caps,
        "clinical_neuro_symbolic": clinical_symbolic,
        "cli_phase5_tools": cli_phase5_tools,
        "providers": providers,
        "mac_vs_cloud": mac_cloud,
        "implemented": [
            "agentic tool loop (LLM + tools)",
            "todo_write / spawn_subagent (mode-gated)",
            "retry-until-green auto-pytest (ln_fab/debug)",
            "cloud sandbox writes + promote (admin/patch rules)",
            "self_capabilities evidence tool",
            "response claim grounding validator",
        ],
        "not_implemented": [
            "CLI neuro-symbolic formal logic / knowledge graph",
            "Mac↔Cloud dual LN-FAB partnership / shared backlog",
            "Workers AI as CLI primary provider",
            "SSE/webhook stream for partner agent runs",
        ],
        "label_rules": {
            "active_feature": "state as fact only if listed under implemented or tools",
            "flag_off": FLAG_OFF_TAG,
            "missing": NOT_IMPLEMENTED_TAG,
            "future": PLANNED_TAG,
            "design": DESIGN_PROPOSAL_TAG,
        },
    }


def tools_used_in_turn(tool_call_log: List[Dict[str, Any]]) -> Set[str]:
    return {str(t.get("name") or "") for t in (tool_call_log or []) if t.get("name")}


def validate_cli_response(
    text: str,
    tool_call_log: Optional[List[Dict[str, Any]]] = None,
    *,
    user_message: str = "",
) -> Dict[str, Any]:
    """
    Scan final assistant text for ungrounded claims.
    Returns {ok, violations[], rewritten_text, used_evidence_tools}.
    """
    text = text or ""
    used = tools_used_in_turn(tool_call_log or [])
    evidence_ok = bool(used & _EVIDENCE_TOOLS)
    self_caps_ok = "self_capabilities" in used
    violations: List[Dict[str, str]] = []

    # Capability questions without self_capabilities
    if is_capability_question(user_message) and not self_caps_ok:
        violations.append({
            "type": "capability_question_without_manifest",
            "detail": "User asked about capabilities/state but self_capabilities was not called",
        })

    # Speculative questions answered without DESIGN PROPOSAL tag
    if is_speculative_question(user_message) and DESIGN_PROPOSAL_TAG not in text:
        # Only flag if answer looks like present-tense capability prose
        if _CAPABILITY_CLAIM_RE.search(text) and DESIGN_PROPOSAL_TAG not in text:
            violations.append({
                "type": "speculation_unlabeled",
                "detail": "Speculative question answered with capability claims without [DESIGN PROPOSAL]",
            })

    # Present-tense claims without evidence tags or evidence tools
    for m in _CAPABILITY_CLAIM_RE.finditer(text):
        start = max(0, m.start() - 80)
        window = text[start: m.end() + 40]
        has_tag = any(
            tag in window
            for tag in (
                VERIFIED_TAG,
                FLAG_OFF_TAG,
                NOT_IMPLEMENTED_TAG,
                PLANNED_TAG,
                DESIGN_PROPOSAL_TAG,
                UNVERIFIED_TAG,
            )
        )
        if has_tag:
            continue
        if evidence_ok and self_caps_ok:
            # Manifest was loaded — still require tags near strong claims
            if "neuro" in m.group(0).lower() or "phase" in m.group(0).lower() or "partner" in m.group(0).lower():
                violations.append({
                    "type": "untagged_capability_claim",
                    "detail": m.group(0)[:80],
                })
            continue
        if not evidence_ok:
            violations.append({
                "type": "ungrounded_capability_claim",
                "detail": m.group(0)[:80],
            })

    # Completion claims without hash / uncommitted qualifier / test evidence.
    # Ignore verbs inside honesty tags like [NOT IMPLEMENTED] / [PLANNED].
    scrubbed = re.sub(
        r"\[(NOT IMPLEMENTED|PLANNED|FLAG-OFF|DESIGN PROPOSAL|UNVERIFIED|VERIFIED[^\]]*)\]",
        " ",
        text,
        flags=re.I,
    )
    has_hash = bool(_COMMIT_HASH_RE.search(text))
    has_pending = bool(_UNCOMMITTED_RE.search(text))
    test_evidence = any(
        t.get("name") in ("shell", "build_test") and (t.get("status") in ("ok", "success"))
        for t in (tool_call_log or [])
    )
    strong = re.search(
        r"(?i)\b(is|are|was|were|now)\s+(done|complete|implemented|fixed|shipped|deployed)\b"
        r"|\b(deployed|shipped|landed|merged)\b",
        scrubbed,
    )
    if strong and not (has_hash or has_pending or test_evidence):
        violations.append({
            "type": "completion_claim_no_hash",
            "detail": "Completion verb without commit hash, uncommitted qualifier, or test tool evidence",
        })

    rewritten = text
    if violations:
        banner = (
            f"{UNVERIFIED_TAG} Grounding check found {len(violations)} issue(s). "
            "Treat unmarked capability claims below as unverified; "
            "call self_capabilities / grep / read_file before restating as fact.\n\n"
        )
        if not rewritten.startswith(UNVERIFIED_TAG):
            rewritten = banner + rewritten

    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "rewritten_text": rewritten,
        "used_evidence_tools": sorted(used & _EVIDENCE_TOOLS),
        "self_capabilities_called": self_caps_ok,
    }


def capability_nudge_message(cli_type: str, mode: str) -> str:
    return (
        "[GROUNDING REQUIRED] The user asked about capabilities, neuro-symbolic state, "
        "Phase status, or Mac vs Cloud. Call self_capabilities NOW and answer ONLY from "
        f"its JSON (cli={cli_type}, mode={mode}). Mark missing items [{NOT_IMPLEMENTED_TAG}] "
        f"or [{PLANNED_TAG}]; mark design ideas [{DESIGN_PROPOSAL_TAG}]. "
        "Do not invent partnership or clinical Phase 5 wiring into the CLI loop."
    )


def speculative_nudge_message() -> str:
    return (
        f"[GROUNDING REQUIRED] Speculative/design question. Prefix the answer with "
        f"{DESIGN_PROPOSAL_TAG}. Do not describe proposals as current production behavior."
    )


def format_manifest_for_tool(manifest: Dict[str, Any]) -> str:
    import json

    return json.dumps(manifest, indent=2, default=str)


def apply_grounding_to_done(
    final_text: str,
    tool_call_log: List[Dict[str, Any]],
    user_message: str,
) -> Tuple[str, Dict[str, Any]]:
    report = validate_cli_response(
        final_text,
        tool_call_log,
        user_message=user_message,
    )
    out_text = report["rewritten_text"] if not report["ok"] else final_text
    grounding = {
        "ok": report["ok"],
        "violation_count": len(report["violations"]),
        "violations": report["violations"][:12],
        "self_capabilities_called": report["self_capabilities_called"],
        "used_evidence_tools": report["used_evidence_tools"],
    }
    return out_text, grounding
