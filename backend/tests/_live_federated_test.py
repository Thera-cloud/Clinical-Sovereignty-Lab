"""Live FederatedSearch recall test - exercises _reinforce_recalls code path."""
import asyncio, os, sys

sys.path.insert(0, "/app")

import asyncpg

TARGET = "dcc45ca451102381e22f65c2adf17ece168789403237a6d5c0912e473ea80e64"

async def test():
    db_url = os.environ.get("DATABASE_URL", "")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    row = await pool.fetchrow(
        "SELECT confidence, recall_count, last_recalled_at "
        "FROM nate_intelligence_crystals WHERE content_hash = $1",
        TARGET,
    )
    print(f"BEFORE: confidence={row[0]}, recall_count={row[1]}", flush=True)

    from app.services.quantum_knowledge_field import FederatedSearchCoordinator
    fsc = FederatedSearchCoordinator.__new__(FederatedSearchCoordinator)
    fsc._db_pool = pool

    fake_results = [{
        "id": None,
        "content_hash": TARGET,
        "crystal_text": "test",
        "confidence": float(row[0]),
        "recall_count": int(row[1]),
        "domain": "clinical",
        "source": "nate_crystal",
    }]

    await fsc._reinforce_recalls(fake_results)

    row2 = await pool.fetchrow(
        "SELECT confidence, recall_count, last_recalled_at "
        "FROM nate_intelligence_crystals WHERE content_hash = $1",
        TARGET,
    )
    print(f"AFTER:  confidence={row2[0]}, recall_count={row2[1]}, "
          f"last_recalled_at={row2[2]}", flush=True)

    delta = float(row2[0]) - float(row[0])
    print(f"DELTA:  {delta:.6f} (expected ~0.03)", flush=True)
    
    if abs(delta - 0.03) < 0.001:
        print("PASS: FederatedSearch promotion works!", flush=True)
    else:
        print(f"FAIL: expected delta ~0.03, got {delta}", flush=True)

    await pool.close()

if __name__ == "__main__":
    asyncio.run(test())
