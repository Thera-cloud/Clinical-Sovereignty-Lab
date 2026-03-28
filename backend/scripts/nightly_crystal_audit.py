#!/usr/bin/env python3
"""
Nightly Crystal Quality Audit.

Runs the CrystalQualityAuditor's validation cycle:
  - Syntax validation on Python-containing crystals
  - Staleness detection for deprecated API patterns
  - C_emo-aware confidence pruning

Run via cron (recommended 3am UTC):
  python3 backend/scripts/nightly_crystal_audit.py

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

    from app.services.crystal_quality_auditor import CrystalQualityAuditor

    auditor = CrystalQualityAuditor(db_pool=pool, app_state=None)

    print("[Crystal Audit] Running nightly quality audit...")
    await auditor._cycle()

    report = auditor._last_audit
    if report:
        print(f"[Crystal Audit] Complete:")
        print(f"  Total audited:     {report['total_audited']}")
        print(f"  Syntax failures:   {report['syntax_failures']}")
        print(f"  Staleness flags:   {report['staleness_flags']}")
        print(f"  Pruned below floor: {report['pruned_below_floor']}")
    else:
        print("[Crystal Audit] No report generated (possibly no crystals)")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
