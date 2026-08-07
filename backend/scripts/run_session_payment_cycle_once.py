#!/usr/bin/env python3
"""One-shot SessionPaymentAgent cycle (run inside nate_backend)."""
from __future__ import annotations

import asyncio
import os


async def main() -> None:
    import asyncpg
    from app.services.session_payment_agent import SessionPaymentAgent

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        agent = SessionPaymentAgent(db_pool=pool)
        await agent._run_one_cycle()
        print("cycle_done")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
