"""Search all conversation_history for cross-user memory bleed indicators."""
import asyncio, asyncpg, os
from cryptography.fernet import Fernet

ENC_KEY = os.environ.get("STEK", "")
if len(ENC_KEY) % 4:
    ENC_KEY += "=" * (4 - len(ENC_KEY) % 4)
f = Fernet(ENC_KEY.encode())

KEYWORDS = [
    "alex", "curly", "boss", "breathing technique",
    "confidence in tough", "disagreement", "friend with curly",
    "boundary", "setting boundaries", "work stress",
    "close friend", "recent disagreement",
]

async def go():
    dsn = os.environ.get("DB_URL", "")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, user_text, ai_text, created_at, session_id "
            "FROM conversation_history "
            "ORDER BY created_at DESC"
        )
        print(f"Total conversation_history rows: {len(rows)}")
        
        user_ids_seen = set()
        matches = []
        
        for row in rows:
            user_ids_seen.add(row["user_id"])
            ut_raw = row["user_text"] or ""
            at_raw = row["ai_text"] or ""
            try:
                ut = f.decrypt(ut_raw.encode()).decode()
            except Exception:
                ut = ut_raw
            try:
                at = f.decrypt(at_raw.encode()).decode()
            except Exception:
                at = at_raw
            
            combined = (ut + " " + at).lower()
            for kw in KEYWORDS:
                if kw in combined:
                    matches.append({
                        "id": row["id"],
                        "user_id": row["user_id"],
                        "keyword": kw,
                        "user_text": ut[:300],
                        "ai_text": at[:400],
                        "created_at": str(row["created_at"]),
                        "session_id": row["session_id"] or "none"
                    })
        
        print(f"Unique user_ids in history: {len(user_ids_seen)}")
        print(f"User IDs: {sorted(user_ids_seen)}")
        print(f"\nKeyword matches found: {len(matches)}")
        
        seen_combos = set()
        for m in matches:
            combo = (m["user_id"], m["created_at"], m["keyword"])
            if combo in seen_combos:
                continue
            seen_combos.add(combo)
            print(f"\n{'='*70}")
            print(f"USER_ID: {m['user_id']}")
            print(f"TIME: {m['created_at']} | SESSION: {m['session_id']}")
            print(f"KEYWORD: '{m['keyword']}'")
            print(f"USER SAID: {m['user_text'][:200]}")
            print(f"NATE SAID: {m['ai_text'][:300]}")
    
    await pool.close()

asyncio.run(go())
