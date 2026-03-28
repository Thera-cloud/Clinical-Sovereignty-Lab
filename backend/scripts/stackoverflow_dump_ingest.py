#!/usr/bin/env python3
"""
Lever 3: StackOverflow Full Dump Ingestion.

Fetches top-voted StackOverflow answers for the tech stack and crystallizes
solution patterns. Run via cron: python3 backend/scripts/stackoverflow_dump_ingest.py

Requires DATABASE_URL env var.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()


async def main():
    import asyncpg
    db_url = os.getenv("DATABASE_URL", "postgresql://nate_admin:@localhost:5432/little_nate")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)

    from app.services.bulk_crystal_ingestion import BulkCrystalIngestion

    ingestion = BulkCrystalIngestion(db_pool=pool, app_state=None)

    tags = os.getenv("SO_TAGS", "python,fastapi,flutter,postgresql,redis,asyncio,websocket").split(",")
    print(f"[Lever 3] Fetching StackOverflow top answers for: {tags}")

    result = await ingestion.run_stackoverflow(tags=tags)
    print(f"[Lever 3] Complete: {result}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
