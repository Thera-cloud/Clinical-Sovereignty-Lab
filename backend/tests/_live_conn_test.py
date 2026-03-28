"""DB connection release test - verify connections don't hold during Vectorize."""
import asyncio, os, sys, time
sys.path.insert(0, "/app")
import asyncpg

async def test():
    db_url = os.environ.get("DATABASE_URL", "")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)

    # Trigger 5 sequential recall operations and check connection count between each
    hashes = await pool.fetch(
        "SELECT content_hash FROM nate_intelligence_crystals "
        "WHERE recall_count = 0 LIMIT 5"
    )

    from app.services.quantum_knowledge_field import FederatedSearchCoordinator
    fsc = FederatedSearchCoordinator.__new__(FederatedSearchCoordinator)
    fsc._db_pool = pool

    for i, row in enumerate(hashes):
        h = row[0]
        fake_results = [{
            "id": None,
            "content_hash": h,
            "crystal_text": "test",
            "confidence": 0.58,
            "recall_count": 0,
            "domain": "general",
            "source": "nate_crystal",
        }]

        t0 = time.monotonic()
        await fsc._reinforce_recalls(fake_results)
        elapsed = time.monotonic() - t0

        stat = await pool.fetchrow(
            "SELECT count(*) FILTER (WHERE state = 'active') as active, "
            "count(*) FILTER (WHERE state = 'idle in transaction') as idle_tx "
            "FROM pg_stat_activity WHERE datname = 'little_nate'"
        )
        print(f"Recall {i+1}: {elapsed*1000:.0f}ms, "
              f"active={stat[0]}, idle_in_tx={stat[1]}", flush=True)

    # Final check after all operations
    await asyncio.sleep(1)
    stat = await pool.fetchrow(
        "SELECT count(*) as total, "
        "count(*) FILTER (WHERE state = 'active') as active, "
        "count(*) FILTER (WHERE state = 'idle in transaction') as idle_tx "
        "FROM pg_stat_activity WHERE datname = 'little_nate'"
    )
    print(f"\nFINAL: total={stat[0]}, active={stat[1]}, idle_in_tx={stat[2]}", flush=True)

    if stat[2] == 0:
        print("PASS: No connections stuck in transaction", flush=True)
    else:
        print(f"FAIL: {stat[2]} connections stuck idle-in-transaction", flush=True)

    await pool.close()

if __name__ == "__main__":
    asyncio.run(test())
