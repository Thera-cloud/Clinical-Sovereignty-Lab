"""R4 prompt injection: data envelopes + honeytoken tripwires.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, FrozenSet, Optional

logger = logging.getLogger("ln7_injection_firewall")

# Task-type allowlist for tool dispatch (extend per loop)
DEFAULT_TOOL_ALLOWLIST: FrozenSet[str] = frozenset({
    "hive_burst",
    "ln7_shadow_fork",
    "growth_policy_cross_review",
    "growth_weekly_digest",
    "newsletter_topic_patrol",
})

HONEYTOKENS = (
    "FAKE_WELD_PATH_/opt/ln7/frozen-config/SECRET_DO_NOT_TOUCH",
    "sk-honeytoken-ln7-not-a-real-key",
)

# R4 layer 2 hardening (2026-08-02): scan_honeytokens() only ever checked
# literal tokens plus one narrow "ignore previous instructions" regex. A
# much broader, already-tested instruction-injection pattern bank exists at
# app.services.vault.content_sentinel_file.FileContentSentinel (B6, ~30
# patterns: role hijack, jailbreak, admin-mode, delimiter escape, extraction
# attempts, unicode obfuscation). Rather than growing a second, divergent
# regex lexicon here — exactly the kind of split-source-of-truth drift that
# produced the escalation-axis false-positive bug documented in
# docs/ln7/TRUST_LEDGER.md Entry 2 — this module reuses that scanner via a
# lazy import (see _scan_instruction_shapes below). Import is lazy, not
# module-level, because app.services.vault requires importing the
# app.services package first, which pulls in nevedal_engine's numpy import
# and SIGFPEs on some macOS dev hosts (see backend/scripts/run_ci_tests.sh
# comment); this mirrors the existing lazy-import pattern already used by
# tripwire_check() below for flywheel_anomaly.


# Pattern names to trust from FileContentSentinel for THIS module's threat
# model (instructions-to-the-agent shapes only). Deliberately excludes
# credential_probe, sql_injection, base64_blob, and redact_marker: those are
# real B6 vault-upload concerns but have heavy legitimate false-positive
# surface in ordinary cli_task_bus notes, which routinely name env vars
# ("rotate AZURE_API_KEY"), contain pasted diffs/hashes, or reference other
# tools' redaction markers. A generic risk_level>=high cutoff would silently
# redact that ordinary engineering language every time it ran through
# sanitize_notes() — the same over-broad-lexicon failure mode as the
# escalation-axis bug in docs/ln7/TRUST_LEDGER.md Entry 2, just on the
# injection side instead of the verifier side.
_TRUSTED_INSTRUCTION_PATTERNS = frozenset({
    "instruction_override", "instruction_inject", "role_hijack", "admin_mode",
    "safety_bypass", "jailbreak", "restriction_removal", "llm_delimiter",
    "delimiter_escape", "extraction_attempt", "echo_extraction",
    "embedded_role_override", "embedded_admin_role", "json_structure_escape",
    "unicode_obfuscation",
})


def _scan_instruction_shapes(text: str) -> Optional[str]:
    """Lazy wrapper around FileContentSentinel.scan(), filtered to the
    instruction-injection pattern names in _TRUSTED_INSTRUCTION_PATTERNS.
    Returns the first matching pattern name, or None. Never raises: any
    import or scan failure degrades to "no hit" rather than blocking the
    caller (this is a defense-in-depth layer on top of the literal-token
    checks in scan_honeytokens, not the only one).
    """
    try:
        from app.services.vault.content_sentinel_file import FileContentSentinel

        result = FileContentSentinel.scan(text)
        for pattern_name in result.patterns_found:
            if pattern_name in _TRUSTED_INSTRUCTION_PATTERNS:
                return pattern_name
    except Exception as e:  # pragma: no cover - defense-in-depth only
        logger.warning("instruction-shape scan unavailable, degrading to literal-only: %s", e)
    return None


def wrap_external_content(text: str, *, source: str = "external") -> Dict[str, Any]:
    """Ingestion quarantine envelope — not executable instructions."""
    return {
        "envelope": "data",
        "source": source,
        "content": text or "",
        "instruction": None,
        "tools_allowed": [],
    }


def validate_tool_dispatch(task_kind: str, allowlist: Optional[FrozenSet[str]] = None) -> bool:
    allow = allowlist or DEFAULT_TOOL_ALLOWLIST
    return (task_kind or "") in allow


def scan_honeytokens(text: str) -> Optional[str]:
    blob = text or ""
    if not blob:
        return None
    for tok in HONEYTOKENS:
        if tok in blob:
            return tok
    # Obvious instruction-injection shapes from dirty readers
    if re.search(r"(?i)ignore\s+(all\s+)?previous\s+instructions", blob):
        return "instruction_override"
    # Broader instruction-shape bank (role hijack, jailbreak, admin-mode,
    # delimiter escape, extraction attempts) — see _scan_instruction_shapes
    # docstring for why this is a lazy-imported reuse, not a new lexicon.
    return _scan_instruction_shapes(blob)


def sanitize_notes(text: str) -> Dict[str, Any]:
    """R4 layer 2: privilege asymmetry / serialization boundary.

    Every publish_task() call — regardless of which loop, and regardless of
    how privileged or unprivileged its source data was (external RSS-derived
    summaries, user-controlled DB fields like client usernames, merged-patch
    diffs) — flows through the shared cli_task_bus before any Queen (including
    repo-writing ones) can read it. Rather than trusting each of the ~15 call
    sites to remember to scan its own inputs before building `notes=`, this
    function is wired as the mandatory floor inside publish_task() itself: a
    lower-privilege producer's raw text never reaches a higher-privilege
    consumer's context in unscanned form.

    Sync by design (scan_honeytokens has no I/O) so it can run inside the
    synchronous publish_task() without an event loop. Callers that already
    do their own async tripwire_check() pre-redaction (ln7_shadow_fork,
    ln7_flywheel_pipeline) are unaffected — this is a second, cheap floor
    check on the already-redacted text, not a replacement for judgment-heavy
    per-field scanning where it exists.
    """
    blob = text or ""
    hit = scan_honeytokens(blob)
    if not hit:
        return {"notes": blob, "tripped": False, "token": None}
    return {
        "notes": f"[REDACTED_BY_R4_FIREWALL: pattern={hit}]",
        "tripped": True,
        "token": hit,
    }


async def tripwire_check(
    text: str,
    *,
    db_pool=None,
    agent: str = "unknown",
) -> Dict[str, Any]:
    hit = scan_honeytokens(text)
    if not hit:
        return {"tripped": False}
    try:
        from app.services.flywheel_anomaly import notify_flywheel_anomaly

        await notify_flywheel_anomaly(
            "honeytoken",
            {"token": hit, "agent": agent},
            db_pool=db_pool,
        )
    except Exception as e:
        logger.warning("honeytoken notify failed: %s", e)
    return {"tripped": True, "token": hit}
