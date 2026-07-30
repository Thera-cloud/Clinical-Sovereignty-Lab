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
