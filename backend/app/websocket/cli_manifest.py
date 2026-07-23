"""
Codebase manifest and workspace rules generator for CLI chat context injection.

Generates a compact but informative summary of the project structure and loads
relevant workspace rules (.mdc + .md) so the LLM starts each session with real
knowledge about what exists and what constraints govern the codebase.

truth_rules.md (.sovereign/rules/) is listed first in ASK, PLAN, LN-FAB, and DEBUG
modes — live in bridge `nate_cli_chat` via `_CLI_WORKSPACE_RULES`.

Rule file resolution: scans `.cursor/rules` then `.sovereign/rules`; the same
basename in both dirs uses the path from `.sovereign` (last write wins). The
total-char cap applies to concatenated rule *bodies* (### Rule blocks only), not
the header line — full `_cli_system` also adds manifest + tool XML.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default cap for assembled WORKSPACE RULES block (nate_cli_chat). Keep CI script in sync.
DEFAULT_CLI_RULES_MAX_CHARS = 64000

# Populated on every load_workspace_rules() call for bridge logging / tests / CI.
_LAST_RULES_LOAD_META: Optional[Dict[str, Any]] = None


def _project_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    if os.path.isfile(os.path.join(root, "backend", "app", "__init__.py")):
        return root
    return os.getcwd()


_PRIORITY_RULES = [
    "learned-integration-patterns.mdc",
    "deployment-safety.mdc",
    "service-health-124.mdc",
    "trust-regression-prevention.mdc",
    "old-code-hygiene.mdc",
    "bridge-postgres-connectivity.mdc",
    "registration-flow-integrity.mdc",
    "endpoint-websocket-sustainability.mdc",
]

_MODE_RULES: Dict[str, List[str]] = {
    "ln_fab": [
        "truth_rules.md",
        "ln_fab_operating_protocol.md",
        "deployment-safety.mdc",
        "service-health-124.mdc",
        "trust-regression-prevention.mdc",
        "old-code-hygiene.mdc",
        "registration-flow-integrity.mdc",
        "endpoint-websocket-sustainability.mdc",
        "learned-integration-patterns.mdc",
        "flutter-build-verification.mdc",
        "trust-enforcer-architecture.mdc",
        "skyeye-data-integrity.mdc",
    ],
    "debug": [
        "truth_rules.md",
        "learned-integration-patterns.mdc",
        "old-code-hygiene.mdc",
        "bridge-postgres-connectivity.mdc",
        "coach-login-diagnostics.mdc",
        "trust-regression-prevention.mdc",
        "safari-flutter-web-caching.mdc",
    ],
    "plan": [
        "truth_rules.md",
        "deployment-safety.mdc",
        "service-health-124.mdc",
        "trust-enforcer-architecture.mdc",
        "learned-integration-patterns.mdc",
        "trust-regression-prevention.mdc",
    ],
    "ask": [
        "truth_rules.md",
        "learned-integration-patterns.mdc",
    ],
}

_MAX_RULE_CHARS = 4000
_FULL_LOAD_RULES = {
    "truth_rules.md",
    "ln_fab_operating_protocol.md",
    "sovereign_ln_fab_protocol_45_rules.md",
}


def _load_rule_summary(rule_path: str) -> Tuple[str, bool]:
    """Load a rule file, truncated to _MAX_RULE_CHARS unless it's a full-load rule.

    Returns (text, True) if the per-file cap was applied.
    """
    try:
        with open(rule_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        fname = os.path.basename(rule_path)
        limit = len(content) + 1 if fname in _FULL_LOAD_RULES else _MAX_RULE_CHARS
        if len(content) <= limit:
            return content, False
        truncated = content[:limit]
        last_newline = truncated.rfind("\n")
        if last_newline > limit // 2:
            truncated = truncated[:last_newline]
        return truncated + "\n... (truncated — use read_file to see full rule)", True
    except Exception:
        return "", False


def get_last_workspace_rules_meta() -> Optional[Dict[str, Any]]:
    """Return metadata from the most recent load_workspace_rules() call."""
    return _LAST_RULES_LOAD_META


def audit_workspace_rules_budget(
    modes: Optional[Tuple[str, ...]] = None,
    root: Optional[str] = None,
    max_total_chars: int = DEFAULT_CLI_RULES_MAX_CHARS,
) -> List[str]:
    """Run budget checks for CLI modes. Returns human-readable errors (empty = OK)."""
    modes = modes or ("ask", "plan", "ln_fab", "debug")
    errors: List[str] = []
    for m in modes:
        _, meta = _load_workspace_rules_with_meta(m, root=root, max_total_chars=max_total_chars)
        if meta.get("output_contains_budget_exceeded"):
            errors.append(
                f"mode={m}: total assembly hit 'budget exceeded' (rule clipped mid-block); "
                f"output_chars={meta['output_chars']} max={max_total_chars}"
            )
        skipped = meta.get("skipped_rule_names") or []
        if skipped:
            errors.append(
                f"mode={m}: {len(skipped)} rule(s) omitted after cap — {skipped[:8]}"
                + (" ..." if len(skipped) > 8 else "")
            )
    return errors


def _load_workspace_rules_with_meta(
    mode: str = "ask",
    root: Optional[str] = None,
    max_total_chars: int = DEFAULT_CLI_RULES_MAX_CHARS,
) -> Tuple[str, Dict[str, Any]]:
    """Load workspace rules; return (text, metadata for logging and CI)."""
    global _LAST_RULES_LOAD_META
    root = root or _project_root()

    meta: Dict[str, Any] = {
        "mode": mode,
        "max_total_chars": max_total_chars,
        "output_chars": 0,
        "rules_included": 0,
        "rules_requested": 0,
        "skipped_rule_names": [],
        "budget_exceeded_rule": None,
        "output_contains_budget_exceeded": False,
        "per_file_truncated_4k": [],
    }

    rules_dirs = [
        os.path.join(root, ".cursor", "rules"),
        os.path.join(root, ".sovereign", "rules"),
    ]

    available_rules: Dict[str, str] = {}
    for rules_dir in rules_dirs:
        if not os.path.isdir(rules_dir):
            continue
        for f in os.listdir(rules_dir):
            if f.endswith(".mdc") or f.endswith(".md"):
                available_rules[f] = os.path.join(rules_dir, f)

    cursorrules_file = os.path.join(root, ".cursorrules")
    if os.path.isfile(cursorrules_file):
        available_rules[".cursorrules"] = cursorrules_file

    mode_rule_names = _MODE_RULES.get(mode, _MODE_RULES["ask"])
    ordered: List[Tuple[str, str]] = []
    seen = set()
    for name in mode_rule_names:
        if name in available_rules and name not in seen:
            ordered.append((name, available_rules[name]))
            seen.add(name)

    meta["rules_requested"] = len(ordered)

    if not ordered:
        _LAST_RULES_LOAD_META = meta
        return "", meta

    sections: List[str] = []
    total_body_chars = 0
    skipped: List[str] = []

    for idx, (name, path) in enumerate(ordered):
        if total_body_chars >= max_total_chars:
            skipped = [n for n, _ in ordered[idx:]]
            break

        summary, file_trunc = _load_rule_summary(path)
        if not summary:
            continue
        if file_trunc:
            meta["per_file_truncated_4k"].append(name)

        budget = max_total_chars - total_body_chars
        pre_assembly_len = len(summary)
        if len(summary) > budget:
            meta["budget_exceeded_rule"] = name
            meta["output_contains_budget_exceeded"] = True
            summary = summary[: max(0, budget - 50)] + "\n... (budget exceeded)"
            logger.warning(
                "CLI workspace rules: mode=%s rule=%s exceeded remaining budget "
                "(summary_len_before_clip=%d budget=%d max_total=%d)",
                mode,
                name,
                pre_assembly_len,
                budget,
                max_total_chars,
            )

        rule_block = f"### Rule: {name}\n{summary}"
        sections.append(rule_block)
        total_body_chars += len(rule_block)

        if meta["output_contains_budget_exceeded"]:
            rest = [n for n, _ in ordered[idx + 1 :]]
            skipped.extend(rest)
            break

    meta["skipped_rule_names"] = skipped
    if skipped:
        if meta.get("budget_exceeded_rule"):
            logger.warning(
                "CLI workspace rules: mode=%s after mid-rule budget clip — not loading %d further rule(s): %s",
                mode,
                len(skipped),
                skipped[:12],
            )
        else:
            logger.warning(
                "CLI workspace rules: mode=%s stopped at cap — skipped %d rule(s): %s",
                mode,
                len(skipped),
                skipped[:12],
            )

    if not sections:
        _LAST_RULES_LOAD_META = meta
        return "", meta

    meta["sections_chars"] = total_body_chars

    header = (
        f"\nWORKSPACE RULES ({len(sections)} rules loaded for {mode.upper()} mode):\n"
        "Truth rules (truth_rules.md) load first — PATH TRUTH and VERIFIED/INFERRED/ASSUMED apply to all tool use.\n"
        "Sovereign: read_file('.sovereign/rules/<name>.md') — Cursor: read_file('.cursor/rules/<name>.mdc')\n"
        "Plans: read_file('.cursor/plans/<name>.plan.md') — implementation plans and architecture docs\n"
        f"Sample keys: {', '.join(sorted(available_rules.keys())[:24])}\n"
    )

    body = "\n\n".join(sections)
    full = header + "\n" + body
    meta["rules_included"] = len(sections)
    meta["output_chars"] = len(full)
    if "budget exceeded" in full:
        meta["output_contains_budget_exceeded"] = True

    if (
        total_body_chars >= int(max_total_chars * 0.9)
        and not meta.get("skipped_rule_names")
        and not meta.get("budget_exceeded_rule")
    ):
        logger.info(
            "CLI workspace rules: mode=%s at %.0f%% of rule-body cap (%d/%d chars)",
            mode,
            100.0 * total_body_chars / max_total_chars,
            total_body_chars,
            max_total_chars,
        )

    _LAST_RULES_LOAD_META = meta
    return full, meta


def load_workspace_rules(
    mode: str = "ask",
    root: Optional[str] = None,
    max_total_chars: int = DEFAULT_CLI_RULES_MAX_CHARS,
) -> str:
    """Load workspace rules relevant to the current CLI mode.

    Prioritizes mode-specific rules, truncates each rule to ~4000 chars,
    and caps total output at max_total_chars to fit within context windows.
    """
    text, _meta = _load_workspace_rules_with_meta(mode, root=root, max_total_chars=max_total_chars)
    return text


_PLAN_PRIORITY_KEYWORDS = (
    "agi", "narrow", "sovereign_ide", "agentic", "tier1", "tier_1", "tier2",
    "neuro-symbolic", "phase_5", "ln-observer", "newsletter", "curriculum",
)


def generate_plan_index(
    root: Optional[str] = None,
    *,
    max_chars: int = 6000,
    query: str = "",
) -> str:
    """Compact index of .cursor/plans + AGI/agentic docs for CLI grounding.

    Prefer priority / query-matching plans so roadmap answers cite real files.
    """
    root = root or _project_root()
    lines: List[str] = []

    plans_dir = os.path.join(root, ".cursor", "plans")
    plan_files: List[str] = []
    if os.path.isdir(plans_dir):
        plan_files = sorted(
            f for f in os.listdir(plans_dir)
            if f.endswith(".plan.md") or f.endswith(".md")
        )

    q = (query or "").lower()
    q_tokens = [t for t in re.findall(r"[a-z0-9_]{3,}", q) if t not in ("the", "and", "for", "what", "next")]

    def _score(name: str) -> int:
        nl = name.lower()
        score = 0
        for kw in _PLAN_PRIORITY_KEYWORDS:
            if kw in nl:
                score += 10
        for tok in q_tokens:
            if tok in nl:
                score += 5
        # Prefer newer-looking sovereign/agi plans first when tied via name boost
        if "sovereign_ide" in nl or "narrow" in nl or "agi" in nl:
            score += 3
        return score

    ranked = sorted(plan_files, key=lambda n: (-_score(n), n))
    priority = [p for p in ranked if _score(p) > 0][:18]
    others = [p for p in ranked if p not in priority][:12]

    lines.append(
        f"IMPLEMENTATION PLANS: {len(plan_files)} files in .cursor/plans/\n"
        "  Read with: read_file('.cursor/plans/<name>.plan.md')\n"
        "  Use git_log / read_git_status for what landed in git (not plan todos alone)."
    )
    if priority:
        lines.append("  PRIORITY (AGI / IDE / agentic / tier — open these first):")
        for p in priority:
            lines.append(f"    - .cursor/plans/{p}")
    if others:
        lines.append(f"  Other sample plans ({len(others)} of {max(0, len(plan_files) - len(priority))}):")
        for p in others[:8]:
            lines.append(f"    - .cursor/plans/{p}")

    docs_dir = os.path.join(root, "docs")
    doc_hits: List[str] = []
    if os.path.isdir(docs_dir):
        for f in sorted(os.listdir(docs_dir)):
            if not f.endswith(".md"):
                continue
            fl = f.lower()
            if any(
                k in fl
                for k in (
                    "agentic", "agi", "tier1", "tier_1", "asi", "neuro",
                    "phase_5", "phase5",
                )
            ):
                doc_hits.append(f)
            elif q_tokens and any(t in fl for t in q_tokens):
                doc_hits.append(f)
    if doc_hits:
        lines.append("AGI / AGENTIC / TIER DOCS (read before inventing a roadmap):")
        for d in doc_hits[:16]:
            lines.append(f"  - docs/{d}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n... (truncated)"
    return text


def generate_manifest(root: Optional[str] = None, max_chars: int = 4000) -> str:
    root = root or _project_root()

    sections = []

    mig_dir = os.path.join(root, "backend", "migrations")
    if os.path.isdir(mig_dir):
        sqls = sorted(f for f in os.listdir(mig_dir) if f.endswith(".sql"))
        if sqls:
            nums = []
            for s in sqls:
                m = re.match(r"(\d+)", s)
                if m:
                    nums.append(int(m.group(1)))
            if nums:
                sections.append(
                    f"MIGRATIONS: {len(sqls)} files, range {min(nums):03d}–{max(nums):03d}\n"
                    f"  Latest: {', '.join(sqls[-5:])}\n"
                    f"  Next migration number: {max(nums)+1:03d}\n"
                    f"  Naming: NNN_description.sql (e.g., 150_new_feature.sql)"
                )

    schema_file = os.path.join(mig_dir, "001_schema.sql") if os.path.isdir(mig_dir) else ""
    if schema_file and os.path.isfile(schema_file):
        tables = []
        try:
            with open(schema_file, "r") as f:
                for line in f:
                    m = re.match(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)", line, re.I)
                    if m:
                        tables.append(m.group(1))
        except Exception:
            pass
        if tables:
            sections.append(
                f"CORE TABLES (from 001_schema.sql): {len(tables)} tables\n"
                f"  {', '.join(tables[:20])}"
                + (f"\n  ... and {len(tables)-20} more" if len(tables) > 20 else "")
            )

    all_tables = set()
    if os.path.isdir(mig_dir):
        for sql_file in sorted(os.listdir(mig_dir)):
            if not sql_file.endswith(".sql"):
                continue
            try:
                with open(os.path.join(mig_dir, sql_file), "r") as f:
                    for line in f:
                        m = re.match(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)", line, re.I)
                        if m:
                            all_tables.add(m.group(1))
            except Exception:
                pass
        if all_tables:
            sections.append(f"ALL TABLES (across all migrations): {len(all_tables)} total")

    svc_dir = os.path.join(root, "backend", "app", "services")
    if os.path.isdir(svc_dir):
        svcs = sorted(f for f in os.listdir(svc_dir) if f.endswith(".py") and f != "__init__.py")
        auditors = [s for s in svcs if "auditor" in s]
        sections.append(
            f"SERVICES: {len(svcs)} files in backend/app/services/\n"
            f"  Examples: {', '.join(svcs[:8])}\n"
            f"  Auditors: {len(auditors)} ({', '.join(auditors[:5])})"
        )

    rtr_dir = os.path.join(root, "backend", "app", "routers")
    if os.path.isdir(rtr_dir):
        rtrs = sorted(f for f in os.listdir(rtr_dir) if f.endswith(".py") and f != "__init__.py")
        sections.append(
            f"ROUTERS: {len(rtrs)} files in backend/app/routers/\n"
            f"  Examples: {', '.join(rtrs[:10])}"
        )

    dash_dir = os.path.join(root, "dashboard")
    if os.path.isdir(dash_dir):
        htmls = sorted(f for f in os.listdir(dash_dir) if f.endswith(".html"))
        sections.append(
            f"DASHBOARD: {len(htmls)} HTML pages in dashboard/\n"
            f"  Examples: {', '.join(htmls[:8])}"
        )

    mob_dir = os.path.join(root, "mobile", "lib")
    if os.path.isdir(mob_dir):
        dart_count = 0
        for dirpath, _, filenames in os.walk(mob_dir):
            dart_count += sum(1 for f in filenames if f.endswith(".dart"))
        screens_dir = os.path.join(mob_dir, "screens")
        screens = []
        if os.path.isdir(screens_dir):
            screens = sorted(f for f in os.listdir(screens_dir) if f.endswith(".dart"))
        sections.append(
            f"MOBILE: {dart_count} Dart files in mobile/lib/\n"
            f"  Screens: {len(screens)} ({', '.join(screens[:5])})"
        )

    wk_dir = os.path.join(root, "cloudflare", "workers")
    if os.path.isdir(wk_dir):
        workers = sorted(
            d for d in os.listdir(wk_dir)
            if os.path.isdir(os.path.join(wk_dir, d)) and not d.startswith(".")
        )
        sections.append(
            f"CLOUDFLARE WORKERS: {len(workers)}\n"
            f"  {', '.join(workers[:8])}"
        )

    bridge = os.path.join(root, "backend", "app", "websocket", "bridge_server.py")
    if os.path.isfile(bridge):
        try:
            line_count = sum(1 for _ in open(bridge))
        except Exception:
            line_count = 0
        sections.append(
            f"BRIDGE: backend/app/websocket/bridge_server.py ({line_count:,} lines)\n"
            f"  Too large to read in one call — use grep or read specific line ranges"
        )

    main_py = os.path.join(root, "backend", "app", "main.py")
    if os.path.isfile(main_py):
        try:
            line_count = sum(1 for _ in open(main_py))
        except Exception:
            line_count = 0
        sections.append(f"MAIN: backend/app/main.py ({line_count:,} lines) — FastAPI lifespan + 161 service checks")

    rules_dir = os.path.join(root, ".cursor", "rules")
    if os.path.isdir(rules_dir):
        rules = sorted(f for f in os.listdir(rules_dir) if f.endswith(".mdc"))
        sections.append(
            f"WORKSPACE RULES: {len(rules)} .mdc files in .cursor/rules/\n"
            f"  Read with: read_file('.cursor/rules/<name>.mdc')"
        )

    plan_idx = generate_plan_index(root=root, max_chars=1200)
    if plan_idx:
        sections.append(plan_idx)

    header = (
        "CODEBASE MANIFEST (auto-generated from file system):\n"
        "This is a MATURE codebase — do NOT create basic schema or starter services.\n"
        "Always check what exists before creating new files.\n"
        "Roadmap/AGI/Tier questions: read .cursor/plans/ + docs/AGENTIC* / *AGI* before answering.\n"
        "Clinical ENABLE_* flags ≠ Narrow AGI / Sovereign IDE phases.\n"
    )

    manifest = header + "\n" + "\n\n".join(sections)

    if len(manifest) > max_chars:
        manifest = manifest[:max_chars - 20] + "\n... (truncated)"

    return manifest


if __name__ == "__main__":
    print(generate_manifest())
    print("\n" + "=" * 60 + "\n")
    print(load_workspace_rules("ln_fab"))
