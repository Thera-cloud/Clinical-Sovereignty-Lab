"""Inject sandbox practice candidates into LN context (never as authority).

Live sessions may pull draft/queued/promoted client_prep + restraint refs.
Sandbox drafts are labeled CANDIDATE — restraints always listed first.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.ln_sandbox_context")


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
            restraints = await conn.fetch(
                """SELECT title, body FROM ln_sandbox_practice_corpus
                   WHERE track = 'restraint_ref' AND status = 'promoted'
                   ORDER BY created_at ASC LIMIT 3"""
            )
            drafts = await conn.fetch(
                """SELECT title, body, kind, score, status
                   FROM ln_sandbox_practice_corpus
                   WHERE target_user_id = $1
                     AND track IN ('client_prep', 'clinical_strategy')
                     AND status IN ('draft', 'queued', 'promoted')
                   ORDER BY
                     CASE status WHEN 'promoted' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                     created_at DESC
                   LIMIT $2""",
                username,
                max(1, min(int(max_items), 8)),
            )
    except Exception as e:
        logger.warning("get_sandbox_candidates_for_user: %s", e)
        return ""

    if not restraints and not drafts:
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
    if drafts:
        parts.append("CANDIDATE APPROACHES (sandbox):")
        for d in drafts:
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
            sessions = await conn.fetchval(
                """SELECT COUNT(*)::int FROM ln_sandbox_sessions
                   WHERE started_at > NOW() - INTERVAL '7 days'"""
            )
            pending = await conn.fetchval(
                """SELECT COUNT(*)::int FROM ln_sandbox_promotion_queue
                   WHERE decision = 'pending'"""
            )
        return {
            "ok": True,
            "sessions_7d": sessions or 0,
            "promotion_pending": pending or 0,
            "corpus": [
                {"track": r["track"], "status": r["status"], "count": r["n"]}
                for r in by_track
            ],
        }
    except Exception as e:
        logger.warning("get_sandbox_stats: %s", e)
        return {"ok": False, "error": str(e)[:200]}
