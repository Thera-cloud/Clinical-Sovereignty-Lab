"""Queen/Worker consumers for Dispatch CLI task kinds.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("nate.newsletter_hive")


def hive_enabled() -> bool:
    return os.getenv("ENABLE_NEWSLETTER_HIVE", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


async def run_hive_patrol(db_pool) -> Dict[str, Any]:
    """Process registered NEWSLETTER_TASK_KINDS once per agent cycle."""
    if not hive_enabled() or not db_pool:
        return {"ok": False, "skipped": True}
    results: List[Dict[str, Any]] = []
    try:
        from app.websocket.cli_task_bus import NEWSLETTER_TASK_KINDS
    except Exception:
        NEWSLETTER_TASK_KINDS = frozenset()

    for kind in sorted(NEWSLETTER_TASK_KINDS):
        try:
            out = await _dispatch_kind(db_pool, kind)
            results.append({"kind": kind, **out})
        except Exception as e:
            logger.warning("hive kind %s failed: %s", kind, e)
            results.append({"kind": kind, "ok": False, "error": str(e)[:200]})
    return {"ok": True, "results": results}


async def _dispatch_kind(db_pool, kind: str) -> Dict[str, Any]:
    if kind == "newsletter_topic_patrol":
        return await _topic_patrol(db_pool)
    if kind == "newsletter_research_verify":
        return await _research_verify(db_pool)
    if kind == "newsletter_draft_critique":
        return await _draft_critique_check(db_pool)
    if kind == "newsletter_growth_signal":
        return await _growth_signal(db_pool)
    if kind == "newsletter_symbolic_promote":
        return await _symbolic_promote(db_pool)
    return {"ok": False, "error": "unknown_kind"}


async def _topic_patrol(db_pool) -> Dict[str, Any]:
    from app.services.newsletter_signals import record_theme_signal, upsert_topic_forecast

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.topic AS topic, AVG(f.helpful_score)::float AS avg_h, COUNT(*)::int AS n
            FROM newsletter_feedback f
            JOIN newsletter_issues i ON i.id = f.issue_id
            WHERE f.helpful_score IS NOT NULL
              AND f.created_at > NOW() - INTERVAL '30 days'
              AND i.topic IS NOT NULL
            GROUP BY i.topic
            HAVING COUNT(*) >= 2
            ORDER BY AVG(f.helpful_score) DESC
            LIMIT 5
            """
        )
    if not rows:
        # Still refresh trend + pool even without ratings
        pool_out = {}
        try:
            from app.services.newsletter_topic_engine import refresh_topic_pool
            from app.services.newsletter_trend_pairing import run_trend_cycle

            pool_out = await refresh_topic_pool(db_pool)
            await run_trend_cycle(db_pool)
        except Exception as e:
            logger.warning("topic_patrol refresh: %s", e)
        return {"ok": True, "action": "noop", "refresh": pool_out}
    themes = []
    for row in rows:
        theme = row["topic"]
        await record_theme_signal(db_pool, theme, source="hive_patrol")
        await upsert_topic_forecast(
            db_pool,
            theme[:64].lower().replace(" ", "_"),
            seasonal_label="hive_patrol",
            foresight_score=min(0.9, 0.4 + (row["avg_h"] or 0) / 10),
            news_velocity=0.1,
        )
        themes.append({"theme": theme, "n": row["n"]})
    try:
        from app.services.newsletter_topic_engine import refresh_topic_pool
        from app.services.newsletter_trend_pairing import run_trend_cycle

        await refresh_topic_pool(db_pool)
        await run_trend_cycle(db_pool)
    except Exception as e:
        logger.warning("topic_patrol refresh: %s", e)
    return {"ok": True, "themes": themes}


async def _research_verify(db_pool) -> Dict[str, Any]:
    from app.services.newsletter_pipeline import build_research_bundle, select_topic

    topic = await select_topic(db_pool)
    bundle = await build_research_bundle(topic)
    n = len(bundle.get("citations") or [])
    return {"ok": n > 0, "citations": n}


async def _draft_critique_check(db_pool) -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM newsletter_issues
            WHERE status = 'in_review'
              AND created_at > NOW() - INTERVAL '14 days'
            """
        )
    return {"ok": True, "in_review": n or 0}


async def _growth_signal(db_pool) -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        pending = await conn.fetchval(
            "SELECT COUNT(*)::int FROM newsletter_warm_leads WHERE status = 'pending'"
        )
        active = await conn.fetchval(
            "SELECT COUNT(*)::int FROM newsletter_subscribers WHERE status = 'active'"
        )
    return {"ok": True, "warm_pending": pending or 0, "active_subs": active or 0}


async def _symbolic_promote(db_pool) -> Dict[str, Any]:
    """Promote high-confidence outcomes to active rules (marketing scope only)."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, confidence FROM newsletter_symbolic_memory
            WHERE scope = 'active' AND kind = 'outcome' AND confidence >= 0.75
              AND created_at > NOW() - INTERVAL '14 days'
            ORDER BY confidence DESC LIMIT 5
            """
        )
        promoted = 0
        for r in rows:
            exists = await conn.fetchval(
                """
                SELECT id FROM newsletter_symbolic_memory
                WHERE kind = 'rule' AND source_issue_id IS NULL
                  AND content = $1 AND scope = 'active'
                LIMIT 1
                """,
                f"RULE: {r['content'][:400]}",
            )
            if exists:
                continue
            await conn.execute(
                """
                INSERT INTO newsletter_symbolic_memory (kind, content, confidence)
                VALUES ('rule', $1, $2)
                """,
                f"RULE: {r['content'][:400]}",
                min(0.85, float(r["confidence"])),
            )
            promoted += 1
    return {"ok": True, "promoted": promoted}
