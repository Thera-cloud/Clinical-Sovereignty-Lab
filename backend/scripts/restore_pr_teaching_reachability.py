#!/usr/bin/env python3
"""Unique-tag PR crystals + restore library pointers + scrub RP-quote contamination.

Run on GREEN (inside nate_backend or with DATABASE_URL):
  python /app/scripts/restore_pr_teaching_reachability.py
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys


async def main() -> int:
    import asyncpg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.crystal_text, l.id AS lib_id
                FROM nate_intelligence_crystals c
                JOIN principal_review_library l
                  ON l.promoted_crystal_id = c.id::text
                 AND l.source_kind = 'gold_scored'
                WHERE c.origin_surface = 'principal_review'
                """
            )
            tagged = 0
            for r in rows:
                text = r["crystal_text"] or ""
                if " · lib:" in text[:160]:
                    continue
                tag = str(r["lib_id"]).replace("-", "")[:12]
                new = re.sub(
                    r"^(\[Principal-Review · [^\]]+)\]",
                    rf"\1 · lib:{tag}]",
                    text,
                    count=1,
                )
                if new == text:
                    new = f"[Principal-Review · clinical · lib:{tag}]\n{text}"
                h = hashlib.sha256(new.encode()).hexdigest()
                clash = await conn.fetchval(
                    "SELECT id FROM nate_intelligence_crystals "
                    "WHERE content_hash=$1 AND id<>$2",
                    h,
                    r["id"],
                )
                if clash:
                    new = f"{new}\n(lib:{tag})"
                    h = hashlib.sha256(new.encode()).hexdigest()
                await conn.execute(
                    """
                    UPDATE nate_intelligence_crystals
                       SET crystal_text=$2, content_hash=$3, updated_at=NOW()
                     WHERE id=$1
                    """,
                    r["id"],
                    new[:8000],
                    h,
                )
                tagged += 1

            restored = await conn.execute(
                """
                UPDATE nate_intelligence_crystals c
                   SET scope = 'global',
                       superseded_by = NULL,
                       updated_at = NOW()
                  FROM principal_review_library l
                 WHERE l.promoted_crystal_id = c.id::text
                   AND l.source_kind = 'gold_scored'
                   AND l.status = 'promoted'
                   AND c.origin_surface = 'principal_review'
                   AND (c.scope = 'archived' OR c.superseded_by IS NOT NULL)
                """
            )
            scrubbed = await conn.execute(
                """
                UPDATE nate_intelligence_crystals
                   SET crystal_text = regexp_replace(
                         crystal_text,
                         'Failed move \\(blind Nate\\):[^\\n]+',
                         'Failed class (do not reproduce): third_person_rp_narration',
                         'gi'
                       ),
                       updated_at = NOW()
                 WHERE origin_surface = 'principal_review'
                   AND crystal_text ILIKE '%Failed move%Nate%'
                """
            )
            active = await conn.fetchval(
                """
                SELECT COUNT(*) FROM principal_review_library l
                JOIN nate_intelligence_crystals c
                  ON l.promoted_crystal_id = c.id::text
                WHERE l.source_kind = 'gold_scored' AND l.status = 'promoted'
                  AND c.origin_surface = 'principal_review'
                  AND c.scope = 'global' AND c.superseded_by IS NULL
                """
            )
            collapsed = await conn.fetchval(
                """
                SELECT COUNT(*) FROM principal_review_library l
                JOIN nate_intelligence_crystals c
                  ON l.promoted_crystal_id = c.id::text
                WHERE l.source_kind = 'gold_scored' AND l.status = 'promoted'
                  AND c.origin_surface = 'principal_review'
                  AND (c.scope = 'archived' OR c.superseded_by IS NOT NULL)
                """
            )
            safety = await conn.fetchval(
                """
                SELECT COUNT(*) FROM principal_review_library l
                JOIN nate_intelligence_crystals c
                  ON l.promoted_crystal_id = c.id::text
                WHERE l.source_kind = 'gold_scored' AND l.status = 'promoted'
                  AND l.response_class = 'escalate_or_safety'
                  AND c.origin_surface = 'principal_review'
                  AND c.scope = 'global' AND c.superseded_by IS NULL
                """
            )
        print(
            f"tagged={tagged} restored={restored} scrubbed={scrubbed} "
            f"active={active} collapsed={collapsed} safety_active={safety}"
        )
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
