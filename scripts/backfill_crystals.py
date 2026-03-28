"""
One-shot backfill script: decrypt conversation_history and run
crystallize_from_conversation for users with rich content but few crystals.

Must run INSIDE nate_bridge container where PII_ENCRYPTION_KEY is available.
"""
import asyncio
import os
import sys
import hashlib
import re

sys.path.insert(0, "/app")

USERS = [
    ("CLIENT_SWEET2NOEND@YAHOO.COM_ID", "Kristy Moore", "bridge_chat"),
    ("CLIENT_LETSGOLISA_ID", "Lisa West", "bridge_chat"),
    ("CLIENT_LETSGOBILL_ID", "Bill West", "bridge_chat"),
    ("CLIENT_JAIMECARPENTER_ID", "Jaime Carpenter", "bridge_chat"),
]

MIN_TEXT_LEN = 40

_CRYSTAL_SIGNALS = [
    (re.compile(r"\b(i feel|i felt|feeling|i'm afraid|i'm scared)\b", re.I), "clinical", 2),
    (re.compile(r"\b(ashamed|shame|guilt|guilty|regret|embarrassed)\b", re.I), "clinical", 3),
    (re.compile(r"\b(boundary|boundaries|self[- ]care|burnout|overwhelmed)\b", re.I), "clinical", 2),
    (re.compile(r"\b(trigger|triggered|flashback|panic|anxiety|anxious)\b", re.I), "clinical", 2),
    (re.compile(r"\b(pattern|cycle|always do|keep doing|every time)\b", re.I), "clinical", 2),
    (re.compile(r"\b(relationship|partner|spouse|marriage|family)\b", re.I), "clinical", 1),
    (re.compile(r"\b(childhood|grew up|parents?|mother|father|mom|dad)\b", re.I), "clinical", 2),
    (re.compile(r"\b(trust|betray|abandon|reject|alone|lonely)\b", re.I), "clinical", 2),
    (re.compile(r"\b(heal|healing|growth|progress|breakthrough|reali[sz]e)\b", re.I), "clinical", 2),
    (re.compile(r"\b(trauma|traumatic|triggered|wounded|wound)\b", re.I), "clinical", 3),
    (re.compile(r"\b(manipulat|controlling|gaslight|toxic)\b", re.I), "clinical", 2),
    (re.compile(r"\b(sad|sadness|crying|tears|cry me|heartbroken)\b", re.I), "clinical", 2),
    (re.compile(r"\b(not happy|unhappy|miserable|depressed|hopeless)\b", re.I), "clinical", 2),
    (re.compile(r"\b(hurt|hurting|painful|pain|sting|stings)\b", re.I), "clinical", 2),
    (re.compile(r"\b(project|projecting|projection|deflect)\b", re.I), "clinical", 1),
    (re.compile(r"\b(empathy|empathize|compassion|understanding)\b", re.I), "clinical", 1),
    (re.compile(r"\b(forgive|forgiveness|letting go|move on|moving on)\b", re.I), "clinical", 2),
    (re.compile(r"\b(self[- ]worth|self[- ]esteem|confidence|insecure)\b", re.I), "clinical", 2),
    (re.compile(r"\b(cope|coping|mechanism|strategy|tool)\b", re.I), "coaching", 1),
    (re.compile(r"\b(goal|intention|commit|accountability|habit)\b", re.I), "coaching", 1),
    (re.compile(r"\b(angry|anger|rage|furious|resentment|resentful)\b", re.I), "clinical", 2),
    (re.compile(r"\b(fear|scared|terrified|worried|dread)\b", re.I), "clinical", 2),
    (re.compile(r"\b(love|loved|loving|beloved|care about)\b", re.I), "clinical", 1),
]


def score_text(text):
    score = 0
    domain = "clinical"
    for pat, d, w in _CRYSTAL_SIGNALS:
        if pat.search(text):
            score += w
            if w >= 2:
                domain = d
    if len(text) > 200 and re.search(r"\b(i |i'm |my |me )\b", text, re.I):
        score += 2
    return score, domain


async def main():
    import asyncpg

    pool = await asyncpg.create_pool(
        host="postgres",
        port=5432,
        user=os.getenv("POSTGRES_USER", "nate_admin"),
        password=os.getenv("POSTGRES_PASSWORD"),
        database=os.getenv("POSTGRES_DB", "little_nate"),
        min_size=1,
        max_size=2,
    )

    try:
        from app.services.pii_cipher import decrypt_pii
        can_decrypt = True
        print("[OK] pii_cipher available")
    except Exception as e:
        can_decrypt = False
        print(f"[WARN] pii_cipher not available: {e}")

    try:
        from cryptography.fernet import Fernet
        fernet_key = os.getenv("PII_ENCRYPTION_KEY") or os.getenv("DATA_ENCRYPTION_KEY") or os.getenv("FERNET_KEY")
        if fernet_key:
            fernet = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
            print("[OK] Fernet key available")
        else:
            fernet = None
            print("[WARN] No Fernet key found in env")
    except Exception as e:
        fernet = None
        print(f"[WARN] Fernet init failed: {e}")

    def try_decrypt(text):
        if not text:
            return text
        if not text.startswith("gAAAAAB"):
            return text
        if can_decrypt:
            try:
                return decrypt_pii(text)
            except Exception:
                pass
        if fernet:
            try:
                return fernet.decrypt(text.encode()).decode()
            except Exception:
                pass
        return None

    total_created = 0

    async with pool.acquire() as conn:
        for hw_id, name, origin in USERS:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", hw_id
            )
            if not user_uuid:
                print(f"\n[SKIP] {name} ({hw_id}) — user not found")
                continue

            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM nate_intelligence_crystals WHERE user_id = $1",
                user_uuid,
            )

            rows = await conn.fetch(
                "SELECT user_text, ai_text, created_at FROM conversation_history WHERE user_id = $1 ORDER BY created_at ASC",
                hw_id,
            )
            print(f"\n[{name}] {len(rows)} messages, {existing} existing crystals, UUID={user_uuid}")

            created = 0
            skipped_decrypt = 0
            skipped_short = 0
            skipped_score = 0
            skipped_dup = 0

            for row in rows:
                raw_ut = row["user_text"] or ""
                raw_at = row["ai_text"] or ""

                ut = try_decrypt(raw_ut)
                if ut is None:
                    skipped_decrypt += 1
                    continue

                if len(ut) < MIN_TEXT_LEN:
                    skipped_short += 1
                    continue

                score, domain = score_text(ut)
                min_score = 3
                if score < min_score:
                    skipped_score += 1
                    continue

                crystal_text = f'{name} expressed: "{ut}"'
                content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()

                try:
                    result = await conn.execute(
                        """INSERT INTO nate_intelligence_crystals
                            (crystal_text, domain, scope, topics, source_count,
                             generation, confidence, content_hash, user_id, origin_surface)
                        VALUES ($1, $2, 'user', '{}'::text[], 1, 0, 0.50, $3, $4, $5)
                        ON CONFLICT (content_hash) DO NOTHING""",
                        crystal_text,
                        domain,
                        content_hash,
                        user_uuid,
                        origin,
                    )
                    if "INSERT 0 1" in result:
                        created += 1
                    else:
                        skipped_dup += 1
                except Exception as e:
                    print(f"  [ERR] Insert failed: {e}")

            total_created += created
            print(
                f"  Created: {created}, Dups: {skipped_dup}, "
                f"Short: {skipped_short}, Low score: {skipped_score}, "
                f"Decrypt fail: {skipped_decrypt}"
            )

    print(f"\n=== TOTAL CRYSTALS CREATED: {total_created} ===")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
