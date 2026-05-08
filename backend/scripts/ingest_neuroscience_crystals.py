#!/usr/bin/env python3
"""One-shot ingestion of neuroscience foundations crystals.

Run inside the backend container (DATABASE_URL is provided by docker-compose):
    docker compose -f docker-compose.prod.yml exec -T backend \
        python /app/scripts/ingest_neuroscience_crystals.py

Idempotent: safe to re-run. Skips entries whose content_hash already exists.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()


async def main() -> int:
    import asyncpg
    db_url = os.getenv("DATABASE_URL", "postgresql://nate_admin:@localhost:5432/little_nate")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        from app.sse.neuroscience_ingestion import ingest_neuroscience_crystals
        result = await ingest_neuroscience_crystals(pool)
        print("[Neuroscience Ingestion]", result)
        if result.get("error"):
            return 1
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
