"""
Trust Enforcer → Dual-COO bus: auditor flags become ops_fix tasks.

GREEN for remediable ops; YELLOW/RED escalate via classify_risk.
# QUANTUM-CRYSTAL-ARCH — Chief of Staff over trust auditors
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("auditor_bus_dispatch")

_RED_CATEGORIES = frozenset({"AI_UNREACHABLE", "PREFLIGHT_FAIL", "DEFENSE_DEGRADED"})
_YELLOW_CATEGORIES = frozenset({"AUTH_FAILURE", "GATE_BYPASS", "WS_TIMEOUT"})


def dispatch_enforcement_actions(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Publish ops_fix bus tasks for each enforcement action (best-effort)."""
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
    for action in actions[:40]:
        cat = str(action.get("category") or "ENDPOINT_DOWN")
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
            if cat in _RED_CATEGORIES:
                enqueue_ceo(
                    risk=RISK_RED,
                    title=f"Trust RED: {auditor} ({cat})",
                    detail=detail,
                    origin="cloud",
                    task_id=str((pub.get("task") or {}).get("task_id") or ""),
                    payload=action,
                )
            elif cat in _YELLOW_CATEGORIES:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title=f"Trust YELLOW: {auditor} ({cat})",
                    detail=detail,
                    origin="cloud",
                    task_id=str((pub.get("task") or {}).get("task_id") or ""),
                    payload=action,
                )
        except Exception as e:
            logger.warning("auditor_bus_dispatch: %s", e)

    return {"status": "ok", "published": published}
