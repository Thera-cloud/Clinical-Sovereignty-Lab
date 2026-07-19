"""72h post-send learning → symbolic memory + growth.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("nate.newsletter_learning")


async def run_learning_for_due_issues(db_pool) -> Dict[str, Any]:
    if not db_pool:
        return {"processed": 0}
    processed = 0
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.id, i.slug, i.topic, i.draft_body, i.final_body, i.body_md
            FROM newsletter_issues i
            WHERE i.status = 'sent'
              AND i.sent_at IS NOT NULL
              AND i.sent_at <= NOW() - INTERVAL '72 hours'
              AND i.sent_at > NOW() - INTERVAL '96 hours'
            """
        )
        for issue in rows:
            # Aggregate feedback
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
            content = (
                f"Issue {issue['slug']} topic={issue['topic']}: "
                f"avg_helpful={float(stats['avg_helpful'] or 0):.2f} "
                f"ratings={stats['ratings']} likes={stats['likes']} opens={opens}"
            )
            conf = 0.55
            if (stats["avg_helpful"] or 0) >= 4 and (stats["ratings"] or 0) >= 5:
                conf = 0.75
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
            # Editor style_note from draft vs final diff
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
            # Decay low-confidence stale rules
            await conn.execute(
                """
                UPDATE newsletter_symbolic_memory
                SET scope = 'archived', updated_at = NOW()
                WHERE scope = 'active'
                  AND confidence < 0.5
                  AND created_at < NOW() - INTERVAL '90 days'
                """
            )
            processed += 1
    return {"processed": processed}
