"""
Fix T — Trafficking disclosure recalibration (SHADOW ONLY).

Parallel shadow classifier; never mutates live handoff tiers.
Shadow fields append to disclosure_evaluated payload_json only.

Env: ENABLE_TRAFFICKING_RECAL (default false — shadow only, never live flip)
"""
# QUANTUM-CRYSTAL-ARCH — Sensitive Bridge turn fix T (shadow)

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

ENABLE_TRAFFICKING_RECAL: bool = os.getenv(
    "ENABLE_TRAFFICKING_RECAL", "false"
).lower() in ("true", "1", "yes")

SHADOW_TIER_TRAFFICKING = "trafficking_disclosure"
SHADOW_TIER_NONE = "none"

_IFS_PART_RX = re.compile(
    r"\b(silencer|scolded girl|lonely girl|exile|manager|firefighter|"
    r"protector|inner critic|self[- ]?part|parts?\s+(?:named|called))\b",
    re.IGNORECASE,
)
_HISTORICAL_TRAUMA_RX = re.compile(
    r"\b(when i was|as a child|as a kid|grandfather|grandmother|"
    r"remembered|childhood|years ago|back then|when i was little)\b",
    re.IGNORECASE,
)
_THEOLOGICAL_RX = re.compile(
    r"\b(conviction|repentance|sabbath|tormented friends|god|prayer|"
    r"faith|scripture|theological|spiritual warfare)\b",
    re.IGNORECASE,
)
_PRESENT_EXPLOITATION_RX = re.compile(
    r"\b("
    r"sells me|rents me out|books appointments for me|takes the money i make|"
    r"took my passport|has my id|won't give me my documents|kept my papers|"
    r"can't leave|won't let me leave|debt to work off|working off the debt|"
    r"made me work|forced me to|traffick"
    r")\b",
    re.IGNORECASE,
)
_SEXUAL_TRAUMA_DISCLOSURE_RX = re.compile(
    r"\b("
    r"rape|assault|abuse|molest|sexual trauma|sexually|violated|"
    r"grand jury|testimony|victim|trauma|hurt me|touched me"
    r")\b",
    re.IGNORECASE,
)
_FIRST_PERSON_RX = re.compile(r"\b(i|my|me|i'm|i've)\b", re.IGNORECASE)


@dataclass
class ShadowResult:
    live_tier: Optional[str]
    shadow_tier: str
    agree: bool
    shadow_acuity: float
    reason: str
    audit_fields: Dict[str, Any]


def compute_sexual_trauma_acuity(message: str) -> float:
    text = (message or "").strip()
    if not text:
        return 0.0
    score = 0.0
    if _SEXUAL_TRAUMA_DISCLOSURE_RX.search(text):
        score += 0.45
    if _FIRST_PERSON_RX.search(text) and _HISTORICAL_TRAUMA_RX.search(text):
        score += 0.25
    if _THEOLOGICAL_RX.search(text):
        score -= 0.20
    if _IFS_PART_RX.search(text):
        score -= 0.15
    if len(text) > 400:
        score += 0.05
    return max(0.0, min(1.0, score))


def _has_positive_trafficking_indicators(message: str) -> bool:
    return bool(_PRESENT_EXPLOITATION_RX.search(message or ""))


def _is_historical_trauma_only(message: str) -> bool:
    text = message or ""
    if _IFS_PART_RX.search(text):
        return True
    if _HISTORICAL_TRAUMA_RX.search(text) and not _PRESENT_EXPLOITATION_RX.search(text):
        return True
    if _THEOLOGICAL_RX.search(text) and not _PRESENT_EXPLOITATION_RX.search(text):
        return True
    return False


def _eval_blocks_trafficking(trafficking_label: Optional[str]) -> bool:
    label = (trafficking_label or "no_disclosure").lower()
    return label in ("no_disclosure", "unclassified", "none", "")


def _compute_shadow_tier(
    *,
    message: str,
    live_tier: Optional[str],
    trafficking_label: Optional[str],
) -> tuple[str, str]:
    if _eval_blocks_trafficking(trafficking_label):
        if live_tier in (SHADOW_TIER_TRAFFICKING, "recruiter_holding"):
            return SHADOW_TIER_NONE, "eval_authoritative_no_disclosure"
        return SHADOW_TIER_NONE, "eval_no_disclosure"

    if _has_positive_trafficking_indicators(message):
        return SHADOW_TIER_TRAFFICKING, "positive_exploitation_markers"

    if _is_historical_trauma_only(message):
        return SHADOW_TIER_NONE, "historical_trauma_only"

    if live_tier in (SHADOW_TIER_TRAFFICKING, "recruiter_holding"):
        return SHADOW_TIER_NONE, "live_tier_downranked_no_exploitation_markers"

    return SHADOW_TIER_NONE, "no_trafficking_signal"


def run_shadow(
    *,
    message: str,
    live_tier: Optional[str],
    trafficking_label: Optional[str],
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> Optional[ShadowResult]:
    if not ENABLE_TRAFFICKING_RECAL:
        return None

    shadow_tier, reason = _compute_shadow_tier(
        message=message,
        live_tier=live_tier,
        trafficking_label=trafficking_label,
    )
    acuity = compute_sexual_trauma_acuity(message)
    live_display = live_tier or "none"
    agree = (
        (live_display in (SHADOW_TIER_TRAFFICKING, "recruiter_holding"))
        == (shadow_tier == SHADOW_TIER_TRAFFICKING)
    )
    if _eval_blocks_trafficking(trafficking_label) and live_display in (
        SHADOW_TIER_TRAFFICKING,
        "recruiter_holding",
    ):
        agree = False

    turn_ref = turn_id or session_id or "unknown"
    print(
        f">>> [TRAFFICKING_SHADOW] live={live_display} shadow={shadow_tier} "
        f"agree={agree} turn={turn_ref}"
    )

    audit_fields = {
        "trafficking_shadow_tier": shadow_tier,
        "trafficking_shadow_agree": agree,
        "trafficking_shadow_acuity": round(acuity, 4),
        "trafficking_shadow_reason": reason,
    }
    return ShadowResult(
        live_tier=live_tier,
        shadow_tier=shadow_tier,
        agree=agree,
        shadow_acuity=acuity,
        reason=reason,
        audit_fields=audit_fields,
    )
