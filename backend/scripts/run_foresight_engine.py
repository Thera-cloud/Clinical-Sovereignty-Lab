#!/usr/bin/env python3
"""
C_emo Foresight Engine — Manual Trigger.

Runs a single CodeForesightEngine cycle:
  - Fetches coherence log samples
  - Computes C_emo growth trajectory
  - Detects stalls
  - Triggers acceleration burst if needed

Run via cron (recommended every 4h) or manually:
  python3 backend/scripts/run_foresight_engine.py

Requires DATABASE_URL env var.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()


async def main():
    import asyncpg
    db_url = os.getenv("DATABASE_URL", "postgresql://nate_admin:@localhost:5432/little_nate")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)

    from app.services.code_foresight_engine import CodeForesightEngine

    engine = CodeForesightEngine(db_pool=pool, app_state=None)

    print("[Foresight] Running C_emo trajectory analysis...")
    await engine._cycle()

    forecast = engine._last_forecast
    if forecast:
        print(f"[Foresight] Results:")
        print(f"  Current C_emo:     {forecast['current_c_emo']:.4f}")
        print(f"  Growth:            {forecast['growth_pct']:.1f}%")
        print(f"  Slope:             {forecast['slope']:.6f}")
        print(f"  7-day forecast:    {forecast['forecast_7d_c_emo']:.4f}")
        print(f"  Crystals/day:      {forecast['crystals_per_day']:.0f}")
        print(f"  Stall detected:    {'YES' if forecast['stall_detected'] else 'no'}")
    else:
        print("[Foresight] Insufficient data for forecast")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
