"""Post-send learning → symbolic memory + crystal reinforce + theme signals.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.newsletter_learning")


async def run_learning_for_due_issues(
    db_pool, *, force_issue_id: Any = None
) -> Dict[str, Any]:
    if not db_pool:
        return {"processed": 0}
    processed = 0
    async with db_pool.acquire() as conn:
        if force_issue_id:
            rows = await conn.fetch(
                """
                SELECT i.id, i.slug, i.topic, i.draft_body, i.final_body, i.body_md,
                       i.crystal_id
                FROM newsletter_issues i
                WHERE i.status = 'sent'
                  AND i.id = $1::uuid
                LIMIT 1
                """,
                force_issue_id,
            )
            if rows:
                await conn.execute(
                    """
                    UPDATE newsletter_issues
                    SET learned_at = NULL, updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    force_issue_id,
                )
        else:
            # 72h default; 24h when feedback exists so learning is not empty forever
            rows = await conn.fetch(
                """
                SELECT i.id, i.slug, i.topic, i.draft_body, i.final_body, i.body_md,
                       i.crystal_id
                FROM newsletter_issues i
                WHERE i.status = 'sent'
                  AND i.sent_at IS NOT NULL
                  AND i.learned_at IS NULL
                  AND (
                        i.sent_at <= NOW() - INTERVAL '72 hours'
                     OR (
                          i.sent_at <= NOW() - INTERVAL '24 hours'
                          AND EXISTS (
                            SELECT 1 FROM newsletter_feedback f
                            WHERE f.issue_id = i.id
                              AND (f.helpful_score IS NOT NULL OR f.liked IS TRUE)
                          )
                     )
                  )
                ORDER BY i.sent_at ASC
                LIMIT 20
                """
            )
        for issue in rows:
            claimed = await conn.fetchval(
                """
                UPDATE newsletter_issues
                SET learned_at = NOW(), updated_at = NOW()
                WHERE id = $1 AND learned_at IS NULL
                RETURNING id
                """,
                issue["id"],
            )
            if not claimed:
                continue

            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE helpful_score IS NOT NULL) AS ratings,
                    AVG(helpful_score) AS avg_helpful,
                    COUNT(*) FILTER (WHERE liked IS TRUE) AS likes
                FROM newsletter_feedback WHERE issue_id = $1
                """,
                issue["id"],
            )
            opens = await conn.fetchval(
                """
                SELECT COUNT(*) FROM newsletter_send_events
                WHERE issue_id = $1 AND event_type = 'open'
                """,
                issue["id"],
            )
            chat_refs = await conn.fetchval(
                """
                SELECT COALESCE(chat_reference_count, 0) FROM newsletter_library_stats
                WHERE slug = $1
                """,
                issue["slug"],
            )
            content = (
                f"Issue {issue['slug']} topic={issue['topic']}: "
                f"avg_helpful={float(stats['avg_helpful'] or 0):.2f} "
                f"ratings={stats['ratings']} likes={stats['likes']} "
                f"opens={opens} chat_refs={chat_refs or 0}"
            )
            conf = 0.55
            if (stats["avg_helpful"] or 0) >= 4 and (stats["ratings"] or 0) >= 5:
                conf = 0.75
            elif (chat_refs or 0) >= 3:
                conf = max(conf, 0.65)
            await conn.execute(
                """
                INSERT INTO newsletter_symbolic_memory
                    (kind, content, confidence, source_issue_id)
                VALUES ('outcome', $1, $2, $3)
                """,
                content,
                conf,
                issue["id"],
            )
            draft = issue.get("draft_body") or ""
            final = issue.get("final_body") or issue.get("body_md") or ""
            if draft and final and draft != final:
                await conn.execute(
                    """
                    INSERT INTO newsletter_symbolic_memory
                        (kind, content, confidence, source_issue_id)
                    VALUES ('style_note', $1, 0.6, $2)
                    """,
                    f"Editor revised {issue['slug']}: len_draft={len(draft)} len_final={len(final)}",
                    issue["id"],
                )
            await conn.execute(
                """
                UPDATE newsletter_symbolic_memory
                SET scope = 'archived', updated_at = NOW()
                WHERE scope = 'active'
                  AND confidence < 0.5
                  AND created_at < NOW() - INTERVAL '90 days'
                """
            )
            # Reinforce existing library crystal + stamp learning metadata
            crystal_id = issue.get("crystal_id")
            if crystal_id:
                try:
                    bump = 0.05 if conf < 0.7 else 0.08
                    await conn.execute(
                        """
                        UPDATE nate_intelligence_crystals
                        SET confidence = LEAST(0.95, COALESCE(confidence, 0.5) + $2::float),
                            recall_count = COALESCE(recall_count, 0) + 1,
                            last_recalled_at = NOW(),
                            metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb
                        WHERE id = $1
                        """,
                        crystal_id,
                        bump,
                        json.dumps({
                            "learning_outcome": content[:400],
                            "learning_confidence": conf,
                            "origin": "newsletter_library",
                        }),
                    )
                except Exception as e:
                    logger.warning("crystal reinforce %s: %s", issue["slug"], e)

            if issue.get("topic"):
                try:
                    from app.services.newsletter_signals import record_theme_signal

                    await record_theme_signal(
                        db_pool, issue["topic"], source="learning_outcome"
                    )
                except Exception:
                    pass
            processed += 1
    return {"processed": processed}
