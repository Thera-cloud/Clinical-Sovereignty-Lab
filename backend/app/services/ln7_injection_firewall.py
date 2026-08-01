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
    for tok in HONEYTOKENS:
        if tok in blob:
            return tok
    # Obvious instruction-injection shapes from dirty readers
    if re.search(r"(?i)ignore\s+(all\s+)?previous\s+instructions", blob):
        return "instruction_override"
    return None


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
