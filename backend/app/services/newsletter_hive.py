"""Queen/Worker consumers for Dispatch CLI task kinds.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
Hive runs local patrol AND enqueues kinds onto the CLI task bus so Dual-COO
Queens (cli_task_bus_consumer) can claim and execute the same handlers.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger("nate.newsletter_hive")


def hive_enabled() -> bool:
    """On when explicitly true, or when agent is on and hive not explicitly off."""
    raw = os.getenv("ENABLE_NEWSLETTER_HIVE", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return os.getenv("ENABLE_NEWSLETTER_AGENT", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


async def run_hive_patrol(db_pool) -> Dict[str, Any]:
    """Enqueue CLI bus kinds (preferred) or run locally when bus is off."""
    if not hive_enabled() or not db_pool:
        return {"ok": False, "skipped": True}

    enqueued = enqueue_hive_tasks()
    try:
        from app.websocket.cli_task_bus import NEWSLETTER_TASK_KINDS, task_bus_enabled
    except Exception:
        NEWSLETTER_TASK_KINDS = frozenset()
        task_bus_enabled = lambda: False  # noqa: E731

    # Dual-COO Queens claim bus tasks — avoid double-running the same kinds
    if task_bus_enabled() and enqueued.get("ok"):
        return {"ok": True, "enqueued": enqueued, "local": "deferred_to_cli"}

    results: List[Dict[str, Any]] = []
    for kind in sorted(NEWSLETTER_TASK_KINDS):
        try:
            out = await execute_newsletter_kind(db_pool, kind)
            results.append({"kind": kind, **out})
        except Exception as e:
            logger.warning("hive kind %s failed: %s", kind, e)
            results.append({"kind": kind, "ok": False, "error": str(e)[:200]})
    return {"ok": True, "enqueued": enqueued, "results": results}


def enqueue_hive_tasks() -> Dict[str, Any]:
    """Publish each newsletter kind onto CLI bus once per UTC day (deduped)."""
    try:
        from app.websocket.cli_task_bus import (
            NEWSLETTER_TASK_KINDS,
            publish_task,
            task_bus_enabled,
            _redis,
            _prefix,
            _env,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    if not task_bus_enabled():
        return {"ok": False, "skipped": "bus_off"}
    c = _redis()
    if not c:
        return {"ok": False, "skipped": "redis"}
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    published = 0
    skipped = 0
    for kind in sorted(NEWSLETTER_TASK_KINDS):
        dkey = f"{_prefix()}:{_env()}:newsletter:hive_enq:{day}:{kind}"
        try:
            if c.set(dkey, "1", nx=True, ex=22 * 3600) is None:
                skipped += 1
                continue
            r = publish_task(
                origin="cloud",
                kind=kind,
                notes=f"Dispatch hive patrol {day}",
                status="queued",
            )
            if r.get("status") == "ok":
                published += 1
            else:
                skipped += 1
                try:
                    c.delete(dkey)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("enqueue %s: %s", kind, e)
            skipped += 1
    return {"ok": True, "published": published, "skipped": skipped}


async def execute_newsletter_kind(db_pool, kind: str) -> Dict[str, Any]:
    """Shared handler for local hive + CLI consumer."""
    return await _dispatch_kind(db_pool, kind)


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
    if kind == "newsletter_trend_pairing":
        return await _trend_pairing(db_pool)
    if kind == "newsletter_growth_attribution":
        return await _growth_attribution(db_pool)
    if kind == "newsletter_chat_learn":
        return await _chat_learn(db_pool)
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
    """Promote high-confidence outcomes to active rules (marketing scope)."""
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


async def _trend_pairing(db_pool) -> Dict[str, Any]:
    from app.services.newsletter_trend_pairing import run_trend_cycle

    out = await run_trend_cycle(db_pool)
    return {"ok": True, "trend": out if isinstance(out, dict) else {"result": out}}


async def _growth_attribution(db_pool) -> Dict[str, Any]:
    """Fold 7d growth ledger into a symbolic tip for topic engine."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT channel,
                   SUM(subscribers_gained)::int AS gained,
                   SUM(conversions)::int AS conv
            FROM newsletter_growth_ledger
            WHERE day >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY channel
            ORDER BY SUM(subscribers_gained) DESC
            LIMIT 5
            """
        )
        if not rows:
            return {"ok": True, "action": "noop"}
        parts = [
            f"{r['channel']}: +{r['gained'] or 0} subs / {r['conv'] or 0} conv"
            for r in rows
        ]
        content = "GROWTH_7D: " + "; ".join(parts)
        await conn.execute(
            """
            INSERT INTO newsletter_symbolic_memory (kind, content, confidence)
            VALUES ('outcome', $1, 0.65)
            """,
            content[:500],
        )
    return {"ok": True, "channels": len(rows)}


async def _chat_learn(db_pool) -> Dict[str, Any]:
    """Promote Story Library chat references into theme signals + forecast."""
    from app.services.newsletter_signals import record_theme_signal, upsert_topic_forecast

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.topic, s.slug, s.chat_reference_count
            FROM newsletter_library_stats s
            JOIN newsletter_issues i ON i.slug = s.slug
            WHERE s.chat_reference_count > 0
              AND i.status = 'sent'
              AND i.topic IS NOT NULL
            ORDER BY s.chat_reference_count DESC
            LIMIT 8
            """
        )
    themes = []
    for r in rows:
        topic = r["topic"]
        await record_theme_signal(db_pool, topic, source="chat_learn")
        await upsert_topic_forecast(
            db_pool,
            topic[:64].lower().replace(" ", "_"),
            seasonal_label="chat_learn",
            foresight_score=min(0.85, 0.35 + min(0.4, (r["chat_reference_count"] or 0) * 0.05)),
            news_velocity=0.05,
        )
        themes.append(topic)
    return {"ok": True, "themes": themes}
