"""
Batch re-index nate_intelligence_crystals from PostgreSQL into Cloudflare Vectorize.

Run inside the backend container:
  docker exec nate_backend python3 /app/reindex_crystals.py

Fetches 500 crystals per DB query, embeds via Workers AI (bge-small-en-v1.5, 384-dim),
upserts to the nate-wisdom Vectorize index, pauses 2s between batches.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "/app")

import asyncpg


async def main():
    from app.services.vectorize_service import (
        batch_embed_and_upsert,
        is_vectorize_configured,
        INDEX_NAMES,
    )

    if not is_vectorize_configured():
        print("ERROR: Vectorize not configured (missing CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID)")
        return

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pg_host = os.getenv("POSTGRES_HOST", "postgres")
        pg_port = os.getenv("POSTGRES_PORT", "5432")
        pg_user = os.getenv("POSTGRES_USER", "nate_admin")
        pg_pass = os.getenv("POSTGRES_PASSWORD", "")
        pg_db = os.getenv("POSTGRES_DB", "little_nate")
        db_url = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM nate_intelligence_crystals WHERE scope != 'archived' OR scope IS NULL"
        )
    print(f"Total active crystals to index: {total}", flush=True)

    BATCH_DB = 500
    PAUSE_SECONDS = 2
    offset = 0
    total_indexed = 0
    total_skipped = 0
    start = time.time()

    while offset < total:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, crystal_text, domain, user_id, confidence,
                       family_id, relationship_context, source_count
                FROM nate_intelligence_crystals
                WHERE scope != 'archived' OR scope IS NULL
                ORDER BY id
                OFFSET $1 LIMIT $2
            """, offset, BATCH_DB)

        if not rows:
            break

        items = []
        for r in rows:
            crystal_text = r["crystal_text"] or ""
            if len(crystal_text.strip()) < 10:
                total_skipped += 1
                continue
            domain = r["domain"] or "general"
            items.append({
                "id": f"wisdom_{r['id']}",
                "text": f"[{domain}] {crystal_text[:2000]}",
                "metadata": {
                    "user_id": str(r["user_id"]) if r["user_id"] else "",
                    "insight_type": "crystal",
                    "domain": domain,
                    "confidence": float(r["confidence"]) if r["confidence"] else 0.5,
                    "family_id": r["family_id"] or "",
                    "preview": crystal_text[:300],
                },
            })

        if items:
            count = await batch_embed_and_upsert(INDEX_NAMES["wisdom"], items)
            total_indexed += count

        offset += BATCH_DB
        elapsed = time.time() - start
        rate = total_indexed / elapsed if elapsed > 0 else 0
        pct = min(100, offset / total * 100)
        print(f"  [{pct:.0f}%] offset={offset} indexed={total_indexed} skipped={total_skipped} elapsed={elapsed:.0f}s rate={rate:.1f}/s", flush=True)

        if offset < total:
            await asyncio.sleep(PAUSE_SECONDS)

    await pool.close()

    elapsed = time.time() - start
    print(f"\nDONE: {total_indexed} crystals indexed into nate-wisdom in {elapsed:.0f}s (skipped {total_skipped} short/empty)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
