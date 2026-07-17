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
8. Honest citations only: [VERIFIED tool=name] / [VERIFIED path:line] must match a tool you actually called and content present in that tool's output. Dishonest citations are rejected by a post-response auditor.
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
            "auto-inject self_capabilities on capability questions (server-side)",
            "post-response citation audit vs tool evidence (server-side)",
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


# [VERIFIED path:line] or [VERIFIED tool=name] or [VERIFIED path]
_VERIFIED_CITATION_RE = re.compile(
    r"\[VERIFIED\s+([^\]]+)\]",
    re.I,
)

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "this", "that", "these", "those", "it", "its", "as", "with", "from", "by",
    "not", "no", "only", "also", "via", "per", "than", "then", "when", "where",
    "which", "who", "what", "how", "can", "we", "i", "you", "our", "their",
    "true", "false", "null", "none", "ok", "status",
})

# Claims that contradict known-false facts in self_capabilities evidence
_MANIFEST_CONTRADICTIONS = (
    (
        re.compile(r"(?i)\b(workers[\s_-]?ai).{0,40}(cli|command terminal|coding loop)|"
                   r"(cli|command terminal).{0,40}workers[\s_-]?ai",
                   re.I),
        re.compile(r'"workers_ai_in_cli_loop"\s*:\s*false', re.I),
        "claims Workers AI on CLI path but self_capabilities says workers_ai_in_cli_loop=false",
    ),
    (
        re.compile(r"(?i)(mac.{0,20}cloud|cloud.{0,20}mac).{0,60}"
                   r"(partner|partnership|collaborat|enhance each)|"
                   r"dual[- ]agent.{0,40}(ln[- ]?fab|cli)",
                   re.I),
        re.compile(r'"mac_cloud_ln_fab_partnership"\s*:\s*false', re.I),
        "claims Mac↔Cloud LN-FAB partnership but self_capabilities says false",
    ),
    (
        re.compile(r"(?i)neuro[- ]?symbolic.{0,40}(wired|active|enabled|in (the )?cli)|"
                   r"(cli|command terminal).{0,40}neuro[- ]?symbolic.{0,20}"
                   r"(layer|engine|active)",
                   re.I),
        re.compile(r'"wired_into_cli_loop"\s*:\s*false', re.I),
        "claims clinical neuro-symbolic wired into CLI but self_capabilities says false",
    ),
    (
        re.compile(r"(?i)ENABLE_ASK_NATE_SYMBOLIC.{0,30}(true|on|enabled|active)|"
                   r"symbolic (layer|seam).{0,30}(enabled|active|on)",
                   re.I),
        re.compile(r'"ENABLE_ASK_NATE_SYMBOLIC"\s*:\s*false', re.I),
        "claims ENABLE_ASK_NATE_SYMBOLIC on but self_capabilities says false",
    ),
)


def _evidence_corpus(tool_call_log: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for t in tool_call_log or []:
        parts.append(str(t.get("name") or ""))
        args = t.get("args") or {}
        if isinstance(args, dict):
            parts.append(json_dumps_safe(args))
        parts.append(str(t.get("evidence_excerpt") or ""))
    return "\n".join(parts).lower()


def json_dumps_safe(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def _significant_tokens(text: str) -> Set[str]:
    toks = re.findall(r"[a-zA-Z_][a-zA-Z0-9_./:-]{2,}", text or "")
    out: Set[str] = set()
    for t in toks:
        tl = t.lower().strip(".:/,")
        if tl in _STOPWORDS or len(tl) < 3:
            continue
        if tl.startswith("verified") or tl in ("flag-off", "implemented", "planned"):
            continue
        out.add(tl)
    return out


def _sentence_for_span(text: str, start: int, end: int) -> str:
    left = text.rfind(".", 0, start)
    left2 = text.rfind("\n", 0, start)
    cut_l = max(left, left2) + 1
    right = text.find(".", end)
    right2 = text.find("\n", end)
    candidates = [i for i in (right, right2) if i != -1]
    cut_r = min(candidates) if candidates else len(text)
    return text[cut_l:cut_r].strip()


def audit_verified_citations(
    text: str,
    tool_call_log: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Second-pass auditor: every [VERIFIED ...] tag must resolve to real tool evidence,
    and the surrounding claim must overlap that evidence (no dishonest citations).
    """
    text = text or ""
    log = tool_call_log or []
    violations: List[Dict[str, str]] = []
    checked = 0
    tools_by_name: Dict[str, List[Dict[str, Any]]] = {}
    for t in log:
        tools_by_name.setdefault(str(t.get("name") or ""), []).append(t)

    corpus = _evidence_corpus(log)

    for m in _VERIFIED_CITATION_RE.finditer(text):
        checked += 1
        inner = (m.group(1) or "").strip()
        sentence = _sentence_for_span(text, m.start(), m.end())
        claim_tokens = _significant_tokens(
            re.sub(r"\[VERIFIED[^\]]*\]", " ", sentence, flags=re.I)
        )

        tool_m = re.match(r"tool\s*=\s*([a-zA-Z0-9_]+)", inner, re.I)
        if not tool_m:
            # Bare / dotted tool citation: [VERIFIED self_capabilities] or
            # [VERIFIED self_capabilities.section_name]
            first_seg = re.split(r"[.\s:]", inner, 1)[0].strip()
            if first_seg in tools_by_name:
                tool_m = re.match(r"(\w+)", first_seg)
        if tool_m:
            tool_name = tool_m.group(1)
            entries = tools_by_name.get(tool_name) or []
            if not entries:
                violations.append({
                    "type": "citation_tool_missing",
                    "detail": f"[VERIFIED tool={tool_name}] but tool was not called",
                })
                continue
            if not any(e.get("status") in ("ok", "success", None) for e in entries):
                violations.append({
                    "type": "citation_tool_failed",
                    "detail": f"[VERIFIED tool={tool_name}] but tool status was not ok",
                })
                continue
            evidence = "\n".join(
                str(e.get("evidence_excerpt") or "") for e in entries
            ).lower()
            if claim_tokens and evidence:
                hits = sum(1 for tok in claim_tokens if tok in evidence or tok in corpus)
                # Require modest overlap for non-trivial claims
                if len(claim_tokens) >= 4 and hits < max(2, len(claim_tokens) // 4):
                    violations.append({
                        "type": "citation_claim_mismatch",
                        "detail": (
                            f"[VERIFIED tool={tool_name}] claim poorly supported by tool output "
                            f"(token overlap {hits}/{len(claim_tokens)})"
                        ),
                    })
            continue

        # Path / path:line form
        path_part = inner.split(":")[0].strip()
        line_part = None
        if ":" in inner and not inner.lower().startswith("tool"):
            bits = inner.split(":")
            path_part = bits[0].strip()
            if len(bits) > 1 and bits[1].strip().isdigit():
                line_part = bits[1].strip()

        if not path_part:
            violations.append({
                "type": "citation_malformed",
                "detail": f"[VERIFIED {inner}] could not parse path or tool",
            })
            continue

        path_norm = path_part.lstrip("./").lower()
        path_found = path_norm in corpus or any(
            path_norm in str((t.get("args") or {}).get("path") or "").lower()
            or path_norm in str((t.get("args") or {}).get("file_path") or "").lower()
            or path_norm in str((t.get("args") or {}).get("pattern") or "").lower()
            or path_norm in str(t.get("evidence_excerpt") or "").lower()
            for t in log
        )
        if not path_found:
            violations.append({
                "type": "citation_path_missing",
                "detail": f"[VERIFIED {inner}] path not present in tool evidence",
            })
            continue

        if claim_tokens and corpus:
            hits = sum(1 for tok in claim_tokens if tok in corpus)
            if len(claim_tokens) >= 4 and hits < max(2, len(claim_tokens) // 4):
                violations.append({
                    "type": "citation_claim_mismatch",
                    "detail": (
                        f"[VERIFIED {inner}] claim poorly supported by tool evidence "
                        f"(token overlap {hits}/{len(claim_tokens)})"
                    ),
                })

        if line_part and line_part not in corpus and f":{line_part}" not in corpus:
            # Soft warning — line may be paraphrased; only flag if no path content either
            pass

    # Known-false contradictions vs self_capabilities evidence
    caps_evidence = "\n".join(
        str(t.get("evidence_excerpt") or "")
        for t in log
        if t.get("name") == "self_capabilities"
    )
    if caps_evidence:
        for claim_re, evidence_re, detail in _MANIFEST_CONTRADICTIONS:
            if claim_re.search(text) and evidence_re.search(caps_evidence):
                violations.append({
                    "type": "manifest_contradiction",
                    "detail": detail,
                })

    return {
        "ok": len(violations) == 0,
        "checked": checked,
        "violations": violations,
    }


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
    cite = audit_verified_citations(final_text, tool_call_log)
    all_violations = list(report["violations"]) + list(cite["violations"])
    out_text = final_text or ""
    if all_violations:
        banner = (
            f"{UNVERIFIED_TAG} Grounding check found {len(all_violations)} issue(s). "
            "Treat unmarked or mismatched capability claims below as unverified; "
            "call self_capabilities / grep / read_file before restating as fact.\n\n"
        )
        # Prefer validate_cli_response rewrite when it already bannered; else wrap original.
        base = report["rewritten_text"] if not report["ok"] else final_text
        if base.startswith(UNVERIFIED_TAG):
            # Refresh count in banner if citation audit added more issues
            if cite["violations"]:
                rest = re.sub(
                    r"^\[UNVERIFIED\][^\n]*\n\n?",
                    "",
                    base,
                    count=1,
                )
                out_text = banner + rest
            else:
                out_text = base
        else:
            out_text = banner + (base or "")
    grounding = {
        "ok": len(all_violations) == 0,
        "violation_count": len(all_violations),
        "violations": all_violations[:16],
        "self_capabilities_called": report["self_capabilities_called"],
        "used_evidence_tools": report["used_evidence_tools"],
        "citations_checked": cite["checked"],
        "citation_audit": True,
    }
    return out_text, grounding
