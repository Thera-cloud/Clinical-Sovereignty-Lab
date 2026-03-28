#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os

import asyncpg

from app.services.quantum_crystal_impact import QuantumCrystalImpactAnalyzer


async def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        analyzer = QuantumCrystalImpactAnalyzer(pool)
        brief = await analyzer.generate_capability_brief(days=14)
        print(brief)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
