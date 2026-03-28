"""Live recall test - run inside nate_backend container."""
import asyncio, os, sys
import asyncpg

TARGET = "02a3c6dac57b15e215a38eb9b413ee93ddd0040c30f91037ec4f0257832864a6"

async def test():
    db_url = os.environ.get("DATABASE_URL", "")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    print(f"Pool created", flush=True)

    row = await pool.fetchrow(
        "SELECT confidence, recall_count, last_recalled_at "
        "FROM nate_intelligence_crystals WHERE content_hash = $1",
        TARGET,
    )
    print(f"BEFORE: confidence={row[0]}, recall_count={row[1]}, "
          f"last_recalled_at={row[2]}", flush=True)

    PROMOTION_CAP = 0.95
    PROMOTION_INCREMENT = 0.03
    print(f"Constants: CAP={PROMOTION_CAP}, INC={PROMOTION_INCREMENT}", flush=True)

    result = await pool.fetchrow(
        f"UPDATE nate_intelligence_crystals "
        f"SET confidence = LEAST(confidence + {PROMOTION_INCREMENT}, {PROMOTION_CAP}), "
        f"    recall_count = recall_count + 1, "
        f"    last_recalled_at = NOW() "
        f"WHERE content_hash = $1 "
        f"RETURNING confidence, recall_count, last_recalled_at",
        TARGET,
    )
    if result:
        print(f"AFTER:  confidence={result[0]}, recall_count={result[1]}, "
              f"last_recalled_at={result[2]}", flush=True)
    else:
        print("ERROR: No rows updated!", flush=True)

    await pool.close()

if __name__ == "__main__":
    asyncio.run(test())
