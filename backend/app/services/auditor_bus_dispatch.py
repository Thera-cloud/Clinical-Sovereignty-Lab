"""
Trust Enforcer → Dual-COO bus: auditor flags become ops_fix tasks.

GREEN for remediable ops (incl. ENDPOINT_DOWN — COO bus only, no CEO inbox);
YELLOW/RED escalate via enqueue_ceo.
# QUANTUM-CRYSTAL-ARCH — Chief of Staff over trust auditors
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("auditor_bus_dispatch")

# All Trust Enforcer remediation categories must map — full Chief of Staff coverage
_RED_CATEGORIES = frozenset({
    "AI_UNREACHABLE",
    "PREFLIGHT_FAIL",
    "DEFENSE_DEGRADED",
})
# QUANTUM-CRYSTAL-ARCH — Nathan 2026-07-18: ENDPOINT_DOWN → GREEN (bus repair only).
# Repeated CEO APPROVE on Trust YELLOW ENDPOINT_DOWN (Token Lab, SkyEye, QB, etc.)
# confirmed these are COO remediable, not morning-inbox work.
_GREEN_CATEGORIES = frozenset({
    "ENDPOINT_DOWN",
})
_YELLOW_CATEGORIES = frozenset({
    "AUTH_FAILURE",
    "GATE_BYPASS",
    "WS_TIMEOUT",
    "DATA_PIPELINE",
    "L2_ISSUE",
})
_ALL_BUS_CATEGORIES = _RED_CATEGORIES | _YELLOW_CATEGORIES | _GREEN_CATEGORIES | frozenset({
    "DATA_PIPELINE",
    "L2_ISSUE",
    "AUTH_FAILURE",
    "GATE_BYPASS",
    "WS_TIMEOUT",
    "AI_UNREACHABLE",
    "PREFLIGHT_FAIL",
    "DEFENSE_DEGRADED",
})


def dispatch_enforcement_actions(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Publish ops_fix bus tasks for each enforcement action (best-effort).

    Covers all REMEDIATION_CATEGORIES from trust_enforcer — every auditor
    failure that becomes an enforcement_action is bus-dispatched.
    ENDPOINT_DOWN is GREEN: bus only (no CEO email/SMS).
    """
    if not actions:
        return {"status": "ok", "published": 0}
    try:
        from app.websocket.cli_task_bus import publish_task, task_bus_enabled
        from app.websocket.cli_dual_coo import (
            RISK_RED,
            RISK_YELLOW,
            enqueue_ceo,
        )
    except ImportError as e:
        return {"status": "error", "error": str(e)[:200]}

    if not task_bus_enabled():
        return {"status": "skipped", "reason": "bus_off"}

    published = 0
    ceo_escalated = 0
    green_only = 0
    for action in actions[:40]:
        cat = str(action.get("category") or "ENDPOINT_DOWN").upper()
        if cat not in _ALL_BUS_CATEGORIES:
            cat = "ENDPOINT_DOWN"
        auditor = str(action.get("auditor") or "unknown")
        detail = str(action.get("detail") or "")[:800]
        notes = f"auditor_ops_fix category={cat} auditor={auditor} {detail}"
        kind = "ops_fix"
        try:
            pub = publish_task(
                origin="cloud",
                files=[],
                status="queued",
                kind=kind,
                notes=notes,
                plan_id=f"trust_{cat.lower()}",
            )
            if pub.get("status") == "ok":
                published += 1
            auditor_slug = "".join(
                ch if ch.isalnum() or ch in "._-" else "_" for ch in auditor
            )[:64]
            task_id = f"trust:{cat}:{auditor_slug}"
            # QUANTUM-CRYSTAL-ARCH — English ask for CEO (ceo_inbox_notify expands further)
            ask = (
                f"Review {auditor} in Sovereign Command Trust: category {cat}. "
                f"Auditor said: {detail or 'no detail'}. "
                "Reply APPROVE to re-run that auditor (reprobe) + smoke/reflect; "
                "ACK/REJECT to clear without re-run. APPROVE does not auto-patch code."
            )
            enriched = dict(action) if isinstance(action, dict) else {"raw": action}
            enriched.setdefault("category", cat)
            enriched.setdefault("auditor", auditor)
            # QUANTUM-CRYSTAL-ARCH — Phase A: APPROVE → trust_reprobe
            enriched["kind"] = "trust_reprobe"
            enriched["ask_of_ceo"] = ask
            if cat in _GREEN_CATEGORIES:
                # Bus task only — digest via ops_fix GREEN path; no CEO inbox
                green_only += 1
                logger.info(
                    "auditor_bus_dispatch GREEN (no CEO): %s %s — %s",
                    auditor, cat, (detail or "")[:120],
                )
            elif cat in _RED_CATEGORIES:
                enqueue_ceo(
                    risk=RISK_RED,
                    title=f"Trust RED: {auditor} ({cat})",
                    detail=detail or ask,
                    origin="cloud",
                    task_id=task_id,
                    payload=enriched,
                    dedup_ttl_s=6 * 3600,
                )
                ceo_escalated += 1
            elif cat in _YELLOW_CATEGORIES:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title=f"Trust YELLOW: {auditor} ({cat})",
                    detail=detail or ask,
                    origin="cloud",
                    task_id=task_id,
                    payload=enriched,
                    dedup_ttl_s=6 * 3600,
                )
                ceo_escalated += 1
        except Exception as e:
            logger.warning("auditor_bus_dispatch: %s", e)

    return {
        "status": "ok",
        "published": published,
        "green_only": green_only,
        "ceo_escalated": ceo_escalated,
        "categories_covered": sorted(_ALL_BUS_CATEGORIES),
    }
