"""
One-time migration: parse availability.json files into coach_availability PG table.

Run BEFORE switching bridge handlers to read from PG.
Usage: python3 backend/scripts/migrate_availability_json.py
"""

import asyncio
import json
import os
import sys
from datetime import time
from pathlib import Path

import asyncpg

VAULTS_DIR = os.environ.get(
    "VAULTS_DIR",
    "/opt/clinical-sovereignty-lab/data/bridge/Vaults/Coaches",
)

DAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


async def main():
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://nate_admin:{}@localhost:5432/little_nate".format(
            os.environ.get("POSTGRES_PASSWORD", "")
        ),
    )
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    vaults = Path(VAULTS_DIR)
    if not vaults.exists():
        print(f"Vaults directory not found: {vaults}")
        sys.exit(1)

    total_migrated = 0

    async with pool.acquire() as conn:
        for coach_dir in sorted(vaults.iterdir()):
            if not coach_dir.is_dir():
                continue
            hw_id = coach_dir.name
            avail_file = coach_dir / "availability.json"
            if not avail_file.exists():
                print(f"  {hw_id}: no availability.json — skipping")
                continue

            with open(avail_file) as f:
                data = json.load(f)

            slots = data.get("slots", [])
            if not slots:
                print(f"  {hw_id}: 0 slots — nothing to migrate")
                continue

            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", hw_id,
            )
            if not user_uuid:
                print(f"  {hw_id}: user not found in DB — skipping")
                continue

            count = 0
            for slot in slots:
                day = slot.get("day_of_week")
                if isinstance(day, str):
                    day = DAY_MAP.get(day.lower())
                if day is None:
                    continue

                start_str = slot.get("start_time", slot.get("start", ""))
                end_str = slot.get("end_time", slot.get("end", ""))
                if not start_str or not end_str:
                    continue

                try:
                    start_t = time.fromisoformat(start_str)
                    end_t = time.fromisoformat(end_str)
                except ValueError:
                    print(f"    bad time format: {start_str}-{end_str}")
                    continue

                recurring = slot.get("recurring", True)
                specific_date = slot.get("specific_date")

                await conn.execute(
                    """INSERT INTO coach_availability
                       (coach_id, day_of_week, start_time, end_time, is_available, recurring, specific_date)
                       VALUES ($1, $2, $3, $4, true, $5, $6::date)
                       ON CONFLICT DO NOTHING""",
                    user_uuid, day, start_t, end_t, recurring,
                    specific_date,
                )
                count += 1

            print(f"  {hw_id}: migrated {count} slots")
            total_migrated += count

    await pool.close()
    print(f"\nTotal: {total_migrated} slots migrated")


if __name__ == "__main__":
    asyncio.run(main())
