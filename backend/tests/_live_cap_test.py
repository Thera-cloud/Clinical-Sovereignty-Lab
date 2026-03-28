"""Live cap enforcement test - verify PROMOTION_CAP = 0.95 holds."""
import asyncio, os, sys

sys.path.insert(0, "/app")

import asyncpg

TARGET = "45183e517152eb86c4c7212c1ea2fa29b621cb9c258f9883af83dba076abee87"
PROMOTION_CAP = 0.95
PROMOTION_INCREMENT = 0.03

async def test():
    db_url = os.environ.get("DATABASE_URL", "")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    # Save original state for later restoration
    orig = await pool.fetchrow(
        "SELECT confidence, recall_count FROM nate_intelligence_crystals "
        "WHERE content_hash = $1", TARGET,
    )
    print(f"ORIGINAL: confidence={orig[0]}, recall_count={orig[1]}", flush=True)

    # Temporarily set confidence to 0.94
    await pool.execute(
        "UPDATE nate_intelligence_crystals "
        "SET confidence = 0.94, recall_count = 15 WHERE content_hash = $1",
        TARGET,
    )
    print("SET: confidence=0.94, recall_count=15", flush=True)

    # Now exercise the FederatedSearch _reinforce_recalls path
    from app.services.quantum_knowledge_field import FederatedSearchCoordinator
    fsc = FederatedSearchCoordinator.__new__(FederatedSearchCoordinator)
    fsc._db_pool = pool

    fake_results = [{
        "id": None,
        "content_hash": TARGET,
        "crystal_text": "test",
        "confidence": 0.94,
        "recall_count": 15,
        "domain": "coding",
        "source": "nate_crystal",
    }]

    await fsc._reinforce_recalls(fake_results)

    row = await pool.fetchrow(
        "SELECT confidence, recall_count FROM nate_intelligence_crystals "
        "WHERE content_hash = $1", TARGET,
    )
    print(f"AFTER RECALL: confidence={row[0]}, recall_count={row[1]}", flush=True)

    if float(row[0]) <= 0.951:
        print(f"PASS: Cap held at {row[0]} (expected <=0.95)", flush=True)
    else:
        print(f"FAIL: Cap breached! confidence={row[0]} > 0.95", flush=True)

    # Also test the direct record_recall path
    from app.services.nate_memory_crystallizer import NateMemoryCrystallizer
    c = NateMemoryCrystallizer.__new__(NateMemoryCrystallizer)
    c.db_pool = pool
    c.mode = "GREEN"
    c._local_store = None

    # Reset to 0.94 for second test
    await pool.execute(
        "UPDATE nate_intelligence_crystals "
        "SET confidence = 0.94, recall_count = 15 WHERE content_hash = $1",
        TARGET,
    )
    print("\nSET: confidence=0.94 (for record_recall test)", flush=True)

    await c.record_recall(TARGET, signal="LOCKED")

    row2 = await pool.fetchrow(
        "SELECT confidence, recall_count FROM nate_intelligence_crystals "
        "WHERE content_hash = $1", TARGET,
    )
    print(f"AFTER record_recall(LOCKED): confidence={row2[0]}, recall_count={row2[1]}", flush=True)

    if float(row2[0]) <= 0.951:
        print(f"PASS: Cap held at {row2[0]} via record_recall path", flush=True)
    else:
        print(f"FAIL: Cap breached via record_recall! confidence={row2[0]}", flush=True)

    # Restore original state
    await pool.execute(
        "UPDATE nate_intelligence_crystals "
        "SET confidence = $1, recall_count = $2 WHERE content_hash = $3",
        float(orig[0]), int(orig[1]), TARGET,
    )
    print(f"\nRESTORED: confidence={orig[0]}, recall_count={orig[1]}", flush=True)

    await pool.close()

if __name__ == "__main__":
    asyncio.run(test())
