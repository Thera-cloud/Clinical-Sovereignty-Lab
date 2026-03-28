#!/usr/bin/env python3
"""
Lever 2: GitHub Mass Ingestion.

Fetches trending GitHub repos and distills architecture patterns into crystals.
Run manually or via cron: python3 backend/scripts/github_mass_ingest.py

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

    languages = os.getenv("GITHUB_LANGUAGES", "python,typescript,dart,rust").split(",")
    print(f"[Lever 2] Fetching GitHub trending for: {languages}")

    result = await ingestion.run_github_trending(languages=languages)
    print(f"[Lever 2] Complete: {result}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
