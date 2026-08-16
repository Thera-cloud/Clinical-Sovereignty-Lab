"""Fill spoken presence from stored coach-self interview. Run inside nate_backend."""

from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    coach_id = (sys.argv[1] if len(sys.argv) > 1 else "COACH_COACHN_ID").strip()
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL missing")
        return 1
    import asyncpg

    from app.services.coach_voice_profile_service import backfill_presence

    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        result = await backfill_presence(pool, coach_id)
        print(result)
        return 0 if result.get("ok") else 2
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
