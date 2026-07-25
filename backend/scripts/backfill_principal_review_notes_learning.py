#!/usr/bin/env python3
"""One-shot: gold notes → Principal Guide → principal_review crystals (adapt-not-recite)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys

import asyncpg

ANTI = (
    "TEACHING RULE: Absorb principles, stance, safety moves, and clinical intent "
    "from Principal Guide. Never recite Guide text verbatim in client replies — "
    "paraphrase naturally for the live moment. Verbatim reuse lowers naturalness "
    "and other scores."
)
MIN_NOTES = 80


def crystal_text(section, topic, client, principal, nate) -> str:
    parts = [
        f"[Principal-Review · {section} · {topic}]",
        ANTI,
        f"Client: {(client or '')[:1200]}",
        "Principal Guide (3/3/3 corrective underwriting — adapt, do not recite):\n"
        f"{(principal or '')[:2500]}",
    ]
    if (nate or "").strip():
        parts.append(
            "Blind Nate draft (contrast — do not imitate failures):\n"
            f"{(nate or '')[:1200]}"
        )
    return "\n".join(parts)


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    out = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT scenario_id, notes, nate_response, section, client_says
               FROM six_quotient_human_gold
               WHERE human_scored = true
                 AND NULLIF(BTRIM(notes), '') IS NOT NULL
                 AND LENGTH(BTRIM(notes)) >= $1""",
            MIN_NOTES,
        )
        print(f"scored_with_notes={len(rows)}", flush=True)
        for g in rows:
            notes = (g["notes"] or "").strip()[:8000]
            lib_id = await conn.fetchval(
                """SELECT id FROM principal_review_library
                   WHERE source_kind = 'gold_scored' AND source_ref = $1""",
                g["scenario_id"],
            )
            meta = json.dumps({"notes_as_principal_guide": True, "backfill": True})
            if lib_id:
                await conn.execute(
                    """UPDATE principal_review_library SET
                         topic = $1, principal_response = $2, nate_response = $3,
                         metadata = COALESCE(metadata, '{}'::jsonb) || $4::jsonb,
                         status = 'draft', updated_at = NOW()
                       WHERE id = $5::uuid""",
                    g["scenario_id"],
                    notes,
                    g["nate_response"] or "",
                    meta,
                    lib_id,
                )
            else:
                lib_id = await conn.fetchval(
                    """INSERT INTO principal_review_library
                       (topic, section, client_says, principal_response, nate_response,
                        source_kind, source_ref, status, created_by, metadata)
                       VALUES ($1,$2,$3,$4,$5,'gold_scored',$1,'draft','DrNevedal1',$6::jsonb)
                       RETURNING id""",
                    g["scenario_id"],
                    g["section"] or "clinical",
                    g["client_says"] or "",
                    notes,
                    g["nate_response"] or "",
                    meta,
                )
            ct = crystal_text(
                g["section"] or "clinical",
                g["scenario_id"],
                g["client_says"],
                notes,
                g["nate_response"],
            )
            ch = hashlib.sha256(ct.encode()).hexdigest()
            cid = await conn.fetchval(
                """INSERT INTO nate_intelligence_crystals
                   (crystal_text, domain, scope, topics, source_count,
                    confidence, content_hash, origin_surface)
                   VALUES ($1, 'clinical', 'global', $2, 1, 0.72, $3, 'principal_review')
                   ON CONFLICT (content_hash) DO NOTHING
                   RETURNING id""",
                ct[:8000],
                ["principal_review", str(g["section"] or "clinical")[:40]],
                ch,
            )
            if not cid:
                cid = await conn.fetchval(
                    """SELECT id FROM nate_intelligence_crystals
                       WHERE content_hash = $1 LIMIT 1""",
                    ch,
                )
            await conn.execute(
                """UPDATE principal_review_library
                   SET status = 'promoted',
                       promoted_crystal_id = $2,
                       updated_at = NOW()
                   WHERE id = $1::uuid""",
                lib_id,
                str(cid) if cid is not None else None,
            )
            out.append(
                {
                    "scenario_id": g["scenario_id"],
                    "library_id": str(lib_id),
                    "crystal_id": str(cid) if cid is not None else None,
                }
            )
    await pool.close()
    print(json.dumps({"status": "ok", "backfilled": len(out), "items": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
