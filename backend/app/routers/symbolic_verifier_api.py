"""
QUANTUM-CRYSTAL-ARCH: Admin telemetry for Phase 5b symbolic verifier.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.services.api_server import require_admin

logger = logging.getLogger("nate.symbolic_verifier_api")

router = APIRouter(
    prefix="/api/admin/symbolic-verifier",
    tags=["symbolic-verifier"],
    dependencies=[Depends(require_admin)],
)


def _get_db(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    return pool


@router.get("/health")
async def symbolic_verifier_health(request: Request):
    import os

    return {
        "status": "ok",
        "ENABLE_SYMBOLIC_VERIFIER": os.getenv("ENABLE_SYMBOLIC_VERIFIER", "false"),
        "ENABLE_SYMBOLIC_EXTRACTION": os.getenv("ENABLE_SYMBOLIC_EXTRACTION", "false"),
        "ENABLE_FORWARD_REASONING": os.getenv("ENABLE_FORWARD_REASONING", "false"),
    }


@router.get("/actions")
async def list_symbolic_verifier_actions(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Recent skyeye_activity rows of type symbolic_verifier_action."""
    pool = _get_db(request)
    rows: List[Any] = []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, content, severity, created_at
                FROM skyeye_activity
                WHERE type = 'symbolic_verifier_action'
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
    except Exception as e:
        logger.warning("symbolic_verifier_api: actions query failed: %s", e)
        raise HTTPException(500, "Query failed") from e

    out = []
    for r in rows:
        content = r["content"]
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                pass
        out.append(
            {
                "id": r["id"],
                "content": content,
                "severity": r["severity"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return {"status": "ok", "count": len(out), "actions": out}


@router.get("/audit-stats")
async def symbolic_audit_stats(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Aggregate counts from sse_therapeutic_audit_log + symbolic_verifier_action."""
    pool = _get_db(request)
    try:
        async with pool.acquire() as conn:
            audit = await conn.fetchrow(
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE audit_passed)::int AS passed,
                       COUNT(*) FILTER (WHERE NOT audit_passed)::int AS failed
                FROM sse_therapeutic_audit_log
                WHERE created_at > NOW() - ($1::text || ' days')::interval
                """,
                str(days),
            )
            sky = await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM skyeye_activity
                WHERE type = 'symbolic_verifier_action'
                  AND created_at > NOW() - ($1::text || ' days')::interval
                """,
                str(days),
            )
    except Exception as e:
        logger.warning("symbolic_verifier_api: stats failed: %s", e)
        return {
            "status": "ok",
            "days": days,
            "therapeutic_audit": {"total": 0, "passed": 0, "failed": 0},
            "symbolic_verifier_actions": 0,
            "note": "tables unavailable or query failed",
        }
    return {
        "status": "ok",
        "days": days,
        "therapeutic_audit": {
            "total": int(audit["total"] or 0) if audit else 0,
            "passed": int(audit["passed"] or 0) if audit else 0,
            "failed": int(audit["failed"] or 0) if audit else 0,
        },
        "symbolic_verifier_actions": int(sky or 0),
    }
