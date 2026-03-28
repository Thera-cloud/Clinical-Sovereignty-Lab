#!/usr/bin/env python3
"""
Lever 1: Bulk Codebase Crystallization.

Scans the project directory and crystallizes per-file architecture patterns.
Run manually or via cron: python3 backend/scripts/bulk_crystallize_codebase.py

Requires DATABASE_URL env var pointing to the PostgreSQL instance.
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

    root = os.getenv("CODEBASE_ROOT", os.path.join(os.path.dirname(__file__), "..", "app"))
    print(f"[Lever 1] Scanning codebase at: {os.path.abspath(root)}")

    result = await ingestion.run_codebase_scan(root=root)
    print(f"[Lever 1] Complete: {result}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
