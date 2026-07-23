"""Inject sandbox practice candidates into LN context (never as authority).

Live sessions may pull quality client_prep / promoted clinical drafts.
Sandbox drafts are labeled CANDIDATE — restraints always listed first.
Failure lessons and low-score drafts are never injected.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.ln_sandbox_context")

# QUANTUM-CRYSTAL-ARCH — live inject quality gate
_LIVE_KINDS = ("success_pattern", "client_prep", "technique_pattern")
_MIN_DRAFT_SCORE = 0.67


async def get_sandbox_candidates_for_user(
    db_pool,
    username: str,
    *,
    max_items: int = 4,
) -> str:
    """Return a context block for session prep / chat injection."""
    if not db_pool or not username:
        return ""
    try:
        async with db_pool.acquire() as conn:
            # Match drafts keyed by username or hardware_id
            hw = await conn.fetchval(
                """SELECT COALESCE(hardware_id, profile_data->>'hardware_id')
                   FROM users
                   WHERE username = $1 OR hardware_id = $1
                      OR profile_data->>'hardware_id' = $1
                   LIMIT 1""",
                username,
            )
            restraints = await conn.fetch(
                """SELECT title, body FROM ln_sandbox_practice_corpus
                   WHERE track = 'restraint_ref' AND status = 'promoted'
                   ORDER BY created_at ASC LIMIT 3"""
            )
            # User-scoped quality drafts only (never failure_lesson / score-0)
            drafts = await conn.fetch(
                """SELECT title, body, kind, score, status, track
                   FROM ln_sandbox_practice_corpus
                   WHERE target_user_id IN ($1, $2)
                     AND track IN ('client_prep', 'clinical_strategy')
                     AND kind = ANY($3::text[])
                     AND kind != 'failure_lesson'
                     AND (
                       status IN ('queued', 'promoted')
                       OR (status = 'draft' AND COALESCE(score, 0) >= $4)
                     )
                   ORDER BY
                     CASE status WHEN 'promoted' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                     COALESCE(score, 0) DESC,
                     created_at DESC
                   LIMIT $5""",
                username,
                hw or username,
                list(_LIVE_KINDS),
                _MIN_DRAFT_SCORE,
                max(1, min(int(max_items), 6)),
            )
            # Promoted clinical successes (no target) — candidate-only, never as facts
            clinical_promoted = await conn.fetch(
                """SELECT title, body, kind, score, status, track
                   FROM ln_sandbox_practice_corpus
                   WHERE track = 'clinical_strategy'
                     AND status = 'promoted'
                     AND kind = 'success_pattern'
                     AND COALESCE(score, 0) >= 0.85
                     AND COALESCE(target_user_id, '') = ''
                   ORDER BY created_at DESC
                   LIMIT 1"""
            )
    except Exception as e:
        logger.warning("get_sandbox_candidates_for_user: %s", e)
        return ""

    rows = list(drafts or []) + list(clinical_promoted or [])
    if not restraints and not rows:
        return ""

    parts: List[str] = [
        "[LN_SANDBOX PRACTICE — CANDIDATES ONLY]",
        "These are practice drafts. Restraints and live safety gates always win.",
        "Do not treat unsanctioned drafts as facts about the client.",
    ]
    if restraints:
        parts.append("RESTRAINTS (binding):")
        for r in restraints:
            parts.append(f"- {r['title']}: {(r['body'] or '')[:280]}")
    if rows:
        parts.append("CANDIDATE APPROACHES (sandbox):")
        for d in rows[: max_items]:
            score = d["score"]
            score_s = f" score={score:.2f}" if score is not None else ""
            parts.append(
                f"- [{d['status']}/{d['kind']}{score_s}] {d['title']}: "
                f"{(d['body'] or '')[:320]}"
            )
    return "\n".join(parts)


async def get_sandbox_stats(db_pool) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    try:
        async with db_pool.acquire() as conn:
            by_track = await conn.fetch(
                """SELECT track, status, COUNT(*)::int AS n
                   FROM ln_sandbox_practice_corpus
                   GROUP BY 1, 2 ORDER BY 1, 2"""
            )
            pending = await conn.fetchval(
                """SELECT COUNT(*)::int FROM ln_sandbox_promotion_queue
                   WHERE decision = 'pending'"""
            )
            sessions = await conn.fetchval(
                """SELECT COUNT(*)::int FROM ln_sandbox_sessions
                   WHERE started_at > NOW() - INTERVAL '24 hours'"""
            )
            queued = await conn.fetchval(
                """SELECT COUNT(*)::int FROM ln_sandbox_practice_corpus
                   WHERE status = 'queued'"""
            )
        return {
            "ok": True,
            "by_track_status": [dict(r) for r in by_track],
            "promotion_pending": pending or 0,
            "corpus_queued": queued or 0,
            "sessions_24h": sessions or 0,
        }
    except Exception as e:
        logger.warning("get_sandbox_stats: %s", e)
        return {"ok": False, "error": str(e)[:200]}
