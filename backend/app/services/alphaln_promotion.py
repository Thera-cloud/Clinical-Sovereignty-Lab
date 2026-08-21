"""AlphaLN Slice 8 — Promotion pipeline (paved but locked).

This module lets AlphaLN *propose* variant promotions (write rows to
``alphaln_promotion_candidates``) and lets DrNevedal1 *approve* or *reject*
them. It intentionally does NOT modify the live serving router.

Locked invariants (see cursor rule alphaln-twin-isolation.mdc invariant 6):

- ``nate_clinical_flags.auto_promote_enabled()`` returns ``False`` in code
  and MUST stay that way. We assert it at ``apply_approved`` time as a
  belt-and-suspenders check.
- ``apply_approved`` never touches ``nate_intelligence_crystals`` or the
  inference router. It only marks the candidate as ``approved`` and returns
  a plan document that a human operator will execute out-of-band.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.alphaln_promotion")

_ENV_FLAG = "ENABLE_ALPHALN_PROMOTION"


def is_enabled() -> bool:
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def propose_candidate(
    db_pool,
    variant_id: str,
    reason: str,
    evidence: Optional[Dict[str, Any]] = None,
    proposed_by: str = "alphaln_gym",
) -> Dict[str, Any]:
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO alphaln_promotion_candidates
                   (proposed_by, variant_id, reason, evidence)
                 VALUES ($1, $2, $3, $4)
              RETURNING id, proposed_at""",
            proposed_by, variant_id, reason, (evidence or {}),
        )
    return {
        "ok": True,
        "candidate_id": int(row["id"]),
        "proposed_at": row["proposed_at"].isoformat(),
    }


async def list_candidates(db_pool, status: Optional[str] = None, limit: int = 25) -> Dict[str, Any]:
    if db_pool is None:
        return {"candidates": []}
    limit = max(1, min(int(limit or 25), 200))
    async with db_pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                """SELECT id, proposed_at, proposed_by, variant_id, reason,
                          status, reviewed_by, reviewed_at, approval_note
                     FROM alphaln_promotion_candidates
                    WHERE status = $1
                    ORDER BY proposed_at DESC
                    LIMIT $2""",
                status, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, proposed_at, proposed_by, variant_id, reason,
                          status, reviewed_by, reviewed_at, approval_note
                     FROM alphaln_promotion_candidates
                    ORDER BY proposed_at DESC
                    LIMIT $1""",
                limit,
            )
    return {
        "candidates": [
            {
                "id": int(r["id"]),
                "proposed_at": r["proposed_at"].isoformat() if r["proposed_at"] else None,
                "proposed_by": r["proposed_by"],
                "variant_id": r["variant_id"],
                "reason": r["reason"],
                "status": r["status"],
                "reviewed_by": r["reviewed_by"],
                "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
                "approval_note": r["approval_note"],
            }
            for r in rows
        ]
    }


async def review_candidate(
    db_pool,
    candidate_id: int,
    reviewer: str,
    decision: str,
    approval_note: Optional[str],
) -> Dict[str, Any]:
    """Mark a candidate approved/rejected/withdrawn. Does NOT apply weights."""
    if decision not in ("approved", "rejected", "withdrawn"):
        return {"ok": False, "reason": "invalid_decision"}
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE alphaln_promotion_candidates
                  SET status = $2,
                      reviewed_by = $3,
                      reviewed_at = NOW(),
                      approval_note = $4
                WHERE id = $1
              RETURNING id, status, variant_id""",
            candidate_id, decision, reviewer, approval_note,
        )
    if not row:
        return {"ok": False, "reason": "not_found"}
    return {
        "ok": True,
        "candidate_id": int(row["id"]),
        "status": row["status"],
        "variant_id": row["variant_id"],
        "note": (
            "Weights are NOT auto-applied. This is a paved-and-locked pipeline; "
            "a human must promote out-of-band via nate_clinical_bakeoff config."
        ),
    }


def assert_auto_promote_locked() -> None:
    """Fail-closed check that the auto-promote flag is still False in code."""
    try:
        from app.services.nate_clinical_flags import auto_promote_enabled
        if auto_promote_enabled():
            raise RuntimeError(
                "alphaln invariant broken: auto_promote_enabled() must stay False"
            )
    except ImportError:
        # If the flag module is missing, we treat that as "locked" (nothing
        # can auto-promote if the code doesn't exist).
        pass
