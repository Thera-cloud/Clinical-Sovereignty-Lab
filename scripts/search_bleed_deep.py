"""Deep search: crystals, conversation_history (all users), voice logs for Alex/curly bleed."""
import asyncio, asyncpg, os
from cryptography.fernet import Fernet

ENC_KEY = os.environ.get("STEK", "")
if len(ENC_KEY) % 4:
    ENC_KEY += "=" * (4 - len(ENC_KEY) % 4)
f = Fernet(ENC_KEY.encode())

CRITICAL_KEYWORDS = [
    "alex", "curly hair", "curly-hair", "close friend",
    "recent disagreement", "confidence in tough",
    "friend alex", "friend named alex",
]

async def go():
    dsn = os.environ.get("DB_URL", "")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
    async with pool.acquire() as conn:

        # 1. Check nate_intelligence_crystals for Alex/curly
        print("=" * 70)
        print("SECTION 1: INTELLIGENCE CRYSTALS")
        print("=" * 70)
        crystals = await conn.fetch(
            "SELECT id, domain, crystal_text, confidence, scope, created_at "
            "FROM nate_intelligence_crystals ORDER BY created_at DESC"
        )
        print(f"Total crystals: {len(crystals)}")
        crystal_hits = []
        for c in crystals:
            txt = (c["crystal_text"] or "").lower()
            for kw in CRITICAL_KEYWORDS:
                if kw in txt:
                    crystal_hits.append({
                        "id": str(c["id"]),
                        "domain": c["domain"],
                        "scope": c["scope"],
                        "confidence": float(c["confidence"]) if c["confidence"] else 0,
                        "created_at": str(c["created_at"]),
                        "keyword": kw,
                        "text": c["crystal_text"][:400]
                    })
        print(f"Crystal matches for Alex/curly/etc: {len(crystal_hits)}")
        for h in crystal_hits:
            print(f"\n  CRYSTAL ID: {h['id']}")
            print(f"  DOMAIN: {h['domain']} | SCOPE: {h['scope']}")
            print(f"  CONFIDENCE: {h['confidence']} | CREATED: {h['created_at']}")
            print(f"  KEYWORD: '{h['keyword']}'")
            print(f"  TEXT: {h['text']}")

        # 2. Check conversation_history for LOADTEST users with critical keywords
        print("\n" + "=" * 70)
        print("SECTION 2: LOAD TEST CONVERSATION HISTORY - CRITICAL KEYWORDS")
        print("=" * 70)
        loadtest_rows = await conn.fetch(
            "SELECT user_id, user_text, ai_text, created_at, session_id "
            "FROM conversation_history "
            "WHERE user_id LIKE 'LOADTEST_%' "
            "ORDER BY created_at DESC"
        )
        print(f"Total LOADTEST conversation rows: {len(loadtest_rows)}")
        lt_hits = []
        for row in loadtest_rows:
            ut_raw = row["user_text"] or ""
            at_raw = row["ai_text"] or ""
            try:
                ut = f.decrypt(ut_raw.encode()).decode()
            except:
                ut = ut_raw
            try:
                at = f.decrypt(at_raw.encode()).decode()
            except:
                at = at_raw
            combined = (ut + " " + at).lower()
            for kw in CRITICAL_KEYWORDS:
                if kw in combined:
                    lt_hits.append({
                        "user_id": row["user_id"],
                        "keyword": kw,
                        "user_text": ut[:300],
                        "ai_text": at[:400],
                        "created_at": str(row["created_at"]),
                        "session_id": row["session_id"] or "none"
                    })
        print(f"LOADTEST matches for Alex/curly/etc: {len(lt_hits)}")
        for h in lt_hits:
            print(f"\n  USER: {h['user_id']} | {h['created_at']}")
            print(f"  KEYWORD: '{h['keyword']}'")
            print(f"  USER SAID: {h['user_text'][:200]}")
            print(f"  NATE SAID: {h['ai_text'][:300]}")

        # 3. Check ALL real client histories for Alex/curly
        print("\n" + "=" * 70)
        print("SECTION 3: REAL CLIENT HISTORY - CRITICAL KEYWORDS ONLY")
        print("=" * 70)
        real_rows = await conn.fetch(
            "SELECT user_id, user_text, ai_text, created_at, session_id "
            "FROM conversation_history "
            "WHERE user_id NOT LIKE 'LOADTEST_%' "
            "ORDER BY created_at DESC"
        )
        print(f"Total real client conversation rows: {len(real_rows)}")
        real_hits = []
        for row in real_rows:
            ut_raw = row["user_text"] or ""
            at_raw = row["ai_text"] or ""
            try:
                ut = f.decrypt(ut_raw.encode()).decode()
            except:
                ut = ut_raw
            try:
                at = f.decrypt(at_raw.encode()).decode()
            except:
                at = at_raw
            combined = (ut + " " + at).lower()
            for kw in CRITICAL_KEYWORDS:
                if kw in combined:
                    real_hits.append({
                        "user_id": row["user_id"],
                        "keyword": kw,
                        "user_text": ut[:300],
                        "ai_text": at[:400],
                        "created_at": str(row["created_at"]),
                        "session_id": row["session_id"] or "none"
                    })
        print(f"Real client matches for Alex/curly/etc: {len(real_hits)}")
        for h in real_hits:
            print(f"\n  USER: {h['user_id']} | {h['created_at']}")
            print(f"  KEYWORD: '{h['keyword']}'")
            print(f"  USER SAID: {h['user_text'][:200]}")
            print(f"  NATE SAID: {h['ai_text'][:300]}")

        # 4. Check if any crystal is scoped to "global" but contains user-specific content
        print("\n" + "=" * 70)
        print("SECTION 4: GLOBAL CRYSTALS WITH PERSONAL NAMES/DETAILS")
        print("=" * 70)
        personal_keywords = ["john d", "kristy", "jane d", "dr nevedal", "drnevedal", 
                           "alex", "curly", "freeindeed", "wilsnaw", "sweet2noend", "lisa"]
        global_crystals = await conn.fetch(
            "SELECT id, domain, crystal_text, confidence, scope, created_at "
            "FROM nate_intelligence_crystals "
            "WHERE scope = 'global' "
            "ORDER BY created_at DESC"
        )
        print(f"Total global/unscoped crystals: {len(global_crystals)}")
        global_hits = []
        for c in global_crystals:
            txt = (c["crystal_text"] or "").lower()
            for kw in personal_keywords:
                if kw in txt:
                    global_hits.append({
                        "id": str(c["id"]),
                        "domain": c["domain"],
                        "scope": c["scope"],
                        "keyword": kw,
                        "text": c["crystal_text"][:400],
                        "created_at": str(c["created_at"])
                    })
        print(f"Global crystals containing personal names: {len(global_hits)}")
        for h in global_hits:
            print(f"\n  CRYSTAL ID: {h['id']}")
            print(f"  SCOPE: {h['scope']} | DOMAIN: {h['domain']}")
            print(f"  PERSONAL NAME: '{h['keyword']}'")
            print(f"  TEXT: {h['text']}")

    await pool.close()

asyncio.run(go())
