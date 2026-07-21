#!/usr/bin/env python3
"""QUANTUM-CRYSTAL-ARCH — seed 3 global clinical precision crystals (Step 3).

Named-referent lock, no invented somatic claims, advice→witness/coach bridge.

Usage (GREEN):
  docker exec -e DATABASE_URL=... nate_backend \
    python /app/scripts/seed_clinical_precision_crystals.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys

CRYSTALS = [
    {
        "key": "clinical_precision_named_referent_v1",
        "topics": ["clinical_precision", "referent_lock", "kinship"],
        "text": (
            "NAMED REFERENT LOCK: When a client names a specific person "
            "(brother, sister, spouse, parent, child, partner), always keep that "
            "exact referent in the reply — 'your brother', 'your wife' — never "
            "collapse them to 'this person' or 'that person'. Vague third-person "
            "labels erase relational specificity and weaken clinical precision."
        ),
    },
    {
        "key": "clinical_precision_no_invented_somatic_v1",
        "topics": ["clinical_precision", "somatic", "no_invention"],
        "text": (
            "NO INVENTED SOMATIC STATE: Only name body sensations the client "
            "actually reported (chest, throat, gut, shoulders, breath, tightness). "
            "Never invent 'tightness in your chest' or 'I can feel the weight in "
            "your shoulders' when they did not say it. Ask what their body is "
            "doing; do not project sensation."
        ),
    },
    {
        "key": "clinical_precision_advice_witness_bridge_v1",
        "topics": ["clinical_precision", "advice", "coach_bridge", "witness"],
        "text": (
            "ADVICE BEFORE WITNESS IS A MISS: When a client asks 'what should I "
            "do?', stay with what is coming up first — witness the bind — then "
            "bridge to their coach for strategies if needed. Do not dump tip "
            "lists ('you should', numbered steps) without a witness sentence and "
            "a coach/session bridge. Presence before prescriptions."
        ),
    },
]


async def main() -> int:
    try:
        import asyncpg
    except ImportError:
        print("FAIL: asyncpg required", file=sys.stderr)
        return 2

    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not url:
        print("FAIL: set DATABASE_URL", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(url)
    try:
        for c in CRYSTALS:
            content_hash = hashlib.sha256(c["key"].encode()).hexdigest()
            row = await conn.fetchrow(
                """
                INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, origin_surface, metadata)
                VALUES (
                    $1, 'clinical', 'global', $2::text[],
                    2, 0, 0.88, $3, 'clinical_precision_seed',
                    $4::jsonb
                )
                ON CONFLICT (content_hash) DO UPDATE SET
                    crystal_text = EXCLUDED.crystal_text,
                    confidence = GREATEST(
                        nate_intelligence_crystals.confidence, EXCLUDED.confidence
                    ),
                    updated_at = NOW()
                RETURNING id::text
                """,
                c["text"],
                c["topics"],
                content_hash,
                json.dumps({"seed_key": c["key"], "step": "wiring_1_3"}),
            )
            print(f"OK: {c['key']} id={row['id'] if row else '?'}")
        print("DONE: 3 clinical precision crystals")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
