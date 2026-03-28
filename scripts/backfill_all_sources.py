"""
Comprehensive backfill: crystallize from ALL data sources for ALL real clients.

Sources:
  1. conversation_history (PostgreSQL) — already handled for Kristy/Lisa, now all clients
  2. Vault memory.json files — Jaime (44 entries), Bill (28 entries), others
  3. Family Sanctuary messages — Bill/Lisa 51 msgs, John/Kristy 37 msgs
  4. Sanctuary history files — archived sessions

Runs INSIDE nate_bridge container.
"""
import asyncio
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, "/app")

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
    (re.compile(r"\b(divorce|custody|separated|separation)\b", re.I), "clinical", 2),
    (re.compile(r"\b(pray|prayer|faith|god|spiritual|church|ministry)\b", re.I), "clinical", 1),
    (re.compile(r"\b(niece|nephew|daughter|son|grandchild|raised)\b", re.I), "clinical", 1),
    (re.compile(r"\b(struggle|struggling|wrestl|torn|conflicted)\b", re.I), "clinical", 2),
    (re.compile(r"\b(dream|vision|hope|aspir|purpose)\b", re.I), "clinical", 1),
    (re.compile(r"\b(attachment|anxious attach|avoidant|secure attach)\b", re.I), "clinical", 3),
    (re.compile(r"\b(identity|who am i|self[- ]discover|authentic)\b", re.I), "clinical", 2),
]

NOISE_PATTERNS = [
    re.compile(r"Charlie Kirk", re.I),
    re.compile(r"Quick live scan", re.I),
    re.compile(r"conspiracy theor", re.I),
    re.compile(r"nasa is lying", re.I),
    re.compile(r"^\d{1,2}:\d{2,3}\s", re.I),
    re.compile(r"•all LTE", re.I),
    re.compile(r"stitched single-page", re.I),
    re.compile(r"copied and pasted this conversation from a tick tock", re.I),
]


def is_noise(text):
    for pat in NOISE_PATTERNS:
        if pat.search(text[:200]):
            return True
    return False


def score_text(text):
    if is_noise(text):
        return 0, "clinical"
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


async def insert_crystal(conn, user_uuid, name, text, origin_surface, min_score=3):
    if len(text) < MIN_TEXT_LEN:
        return "short"
    score, domain = score_text(text)
    if score < min_score:
        return "low_score"
    crystal_text = f'{name} expressed: "{text}"'
    content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()
    try:
        result = await conn.execute(
            """INSERT INTO nate_intelligence_crystals
                (crystal_text, domain, scope, topics, source_count,
                 generation, confidence, content_hash, user_id, origin_surface)
            VALUES ($1, $2, 'user', '{}'::text[], 1, 0, 0.50, $3, $4, $5)
            ON CONFLICT (content_hash) DO NOTHING""",
            crystal_text, domain, content_hash, user_uuid, origin_surface,
        )
        return "created" if "INSERT 0 1" in result else "dup"
    except Exception as e:
        print(f"  [ERR] {e}")
        return "error"


async def main():
    import asyncpg

    pool = await asyncpg.create_pool(
        host="postgres", port=5432,
        user=os.getenv("POSTGRES_USER", "nate_admin"),
        password=os.getenv("POSTGRES_PASSWORD"),
        database=os.getenv("POSTGRES_DB", "little_nate"),
        min_size=1, max_size=2,
    )

    try:
        from app.services.pii_cipher import decrypt_pii
        can_decrypt = True
    except Exception:
        can_decrypt = False

    def try_decrypt(text):
        if not text or not text.startswith("gAAAAAB"):
            return text
        if can_decrypt:
            try:
                return decrypt_pii(text)
            except Exception:
                pass
        return None

    # Build user map: hardware_id -> (uuid, name)
    async with pool.acquire() as conn:
        user_rows = await conn.fetch(
            "SELECT id, username, hardware_id, profile_data->>'name' as name FROM users WHERE role = 'CLIENT'"
        )
    user_map = {}
    for r in user_rows:
        hw = r["hardware_id"]
        user_map[hw] = (r["id"], r["name"] or r["username"])
        user_map[r["username"]] = (r["id"], r["name"] or r["username"])

    # Skip loadtest and audit accounts
    skip_prefixes = ("LOADTEST_", "audit_", "AUDIT_")

    total = {"created": 0, "dup": 0, "short": 0, "low_score": 0, "error": 0, "decrypt_fail": 0}

    async with pool.acquire() as conn:

        # === SOURCE 1: conversation_history (PostgreSQL) ===
        print("=" * 60)
        print("SOURCE 1: conversation_history (PostgreSQL)")
        print("=" * 60)

        ch_users = await conn.fetch(
            "SELECT DISTINCT user_id FROM conversation_history"
        )
        for row in ch_users:
            uid = row["user_id"]
            if any(uid.startswith(p) for p in skip_prefixes):
                continue
            if uid not in user_map:
                continue
            user_uuid, name = user_map[uid]

            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM nate_intelligence_crystals WHERE user_id = $1",
                user_uuid,
            )

            messages = await conn.fetch(
                "SELECT user_text FROM conversation_history WHERE user_id = $1 ORDER BY created_at",
                uid,
            )
            if not messages:
                continue

            counts = {"created": 0, "dup": 0, "short": 0, "low_score": 0, "error": 0, "decrypt_fail": 0}
            for m in messages:
                raw = m["user_text"] or ""
                text = try_decrypt(raw)
                if text is None:
                    counts["decrypt_fail"] += 1
                    continue
                result = await insert_crystal(conn, user_uuid, name, text, "bridge_chat")
                counts[result] += 1

            if counts["created"] > 0 or len(messages) > 5:
                print(f"  {name} ({uid}): {len(messages)} msgs, {existing} existing → +{counts['created']} new "
                      f"(dup={counts['dup']}, short={counts['short']}, low={counts['low_score']})")
            for k in total:
                total[k] += counts.get(k, 0)

        # === SOURCE 2: Vault memory.json files ===
        print()
        print("=" * 60)
        print("SOURCE 2: Vault memory.json files")
        print("=" * 60)

        vault_dir = "/app/data/Vaults/Clients"
        if os.path.exists(vault_dir):
            for hw_id_dir in sorted(os.listdir(vault_dir)):
                if any(hw_id_dir.startswith(p) for p in skip_prefixes):
                    continue
                if hw_id_dir not in user_map:
                    continue
                mem_path = os.path.join(vault_dir, hw_id_dir, "memory.json")
                if not os.path.exists(mem_path) or os.path.getsize(mem_path) < 100:
                    continue

                user_uuid, name = user_map[hw_id_dir]
                try:
                    with open(mem_path) as f:
                        entries = json.load(f)
                except Exception:
                    continue

                if not isinstance(entries, list):
                    continue

                counts = {"created": 0, "dup": 0, "short": 0, "low_score": 0, "error": 0}
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    text = entry.get("user", "")
                    if not text or len(text) < MIN_TEXT_LEN:
                        counts["short"] += 1
                        continue
                    result = await insert_crystal(conn, user_uuid, name, text, "bridge_chat")
                    counts[result] += 1

                if counts["created"] > 0 or len(entries) > 5:
                    print(f"  {name} ({hw_id_dir}): {len(entries)} vault entries → +{counts['created']} new "
                          f"(dup={counts['dup']}, short={counts['short']}, low={counts['low_score']})")
                for k in ("created", "dup", "short", "low_score", "error"):
                    total[k] += counts.get(k, 0)

        # === SOURCE 3: Live sanctuary messages ===
        print()
        print("=" * 60)
        print("SOURCE 3: Live Family Sanctuary messages")
        print("=" * 60)

        sanc_path = "/app/data/family_sanctuaries.json"
        if os.path.exists(sanc_path):
            with open(sanc_path) as f:
                sanc_data = json.load(f)

            for sid, sanc in sanc_data.get("active_sanctuaries", {}).items():
                msgs = sanc.get("messages", [])
                if not msgs:
                    continue

                counts = {"created": 0, "dup": 0, "short": 0, "low_score": 0, "error": 0}
                for m in msgs:
                    sender_id = m.get("sender_id", "")
                    if sender_id == "LITTLE_NATE":
                        continue
                    text = m.get("content", "")
                    if not text or sender_id not in user_map:
                        continue
                    user_uuid, name = user_map[sender_id]
                    result = await insert_crystal(conn, user_uuid, name, text, "family_sanctuary", min_score=3)
                    counts[result] += 1

                if counts["created"] > 0:
                    print(f"  {sid}: +{counts['created']} new (dup={counts['dup']}, short={counts['short']}, low={counts['low_score']})")
                for k in ("created", "dup", "short", "low_score", "error"):
                    total[k] += counts.get(k, 0)

        # === SOURCE 4: Sanctuary history files ===
        print()
        print("=" * 60)
        print("SOURCE 4: Sanctuary history files")
        print("=" * 60)

        hist_dir = "/app/data/sanctuary_history"
        if os.path.exists(hist_dir):
            for fn in sorted(os.listdir(hist_dir)):
                fp = os.path.join(hist_dir, fn)
                try:
                    with open(fp) as f:
                        d = json.load(f)
                except Exception:
                    continue

                msgs = d.get("messages", [])
                if not msgs:
                    continue

                counts = {"created": 0, "dup": 0, "short": 0, "low_score": 0, "error": 0}
                for m in msgs:
                    sender_id = m.get("sender_id", "")
                    if sender_id == "LITTLE_NATE":
                        continue
                    text = m.get("content", m.get("text", ""))
                    if not text or sender_id not in user_map:
                        continue
                    user_uuid, name = user_map[sender_id]
                    result = await insert_crystal(conn, user_uuid, name, text, "family_sanctuary", min_score=3)
                    counts[result] += 1

                # Also process coaching session responses
                cs = d.get("coaching_sessions", {})
                if isinstance(cs, dict):
                    for member_id, session in cs.items():
                        if not isinstance(session, dict):
                            continue
                        responses = session.get("responses", {})
                        if not isinstance(responses, dict):
                            continue
                        if member_id not in user_map:
                            continue
                        user_uuid, name = user_map[member_id]
                        for q_id, answer in responses.items():
                            if isinstance(answer, str) and len(answer) >= MIN_TEXT_LEN:
                                result = await insert_crystal(conn, user_uuid, name, answer, "coached_response", min_score=3)
                                counts[result] += 1

                if counts["created"] > 0:
                    print(f"  {fn}: +{counts['created']} new (dup={counts['dup']}, short={counts['short']}, low={counts['low_score']})")
                for k in ("created", "dup", "short", "low_score", "error"):
                    total[k] += counts.get(k, 0)

        # Also process live sanctuary coaching sessions
        print()
        print("=" * 60)
        print("SOURCE 5: Live sanctuary coaching sessions")
        print("=" * 60)

        if os.path.exists(sanc_path):
            for sid, sanc in sanc_data.get("active_sanctuaries", {}).items():
                cs = sanc.get("coaching_sessions", {})
                if not isinstance(cs, dict):
                    continue
                counts = {"created": 0, "dup": 0, "short": 0, "low_score": 0, "error": 0}
                for member_id, session in cs.items():
                    if not isinstance(session, dict):
                        continue
                    responses = session.get("responses", {})
                    if not isinstance(responses, dict):
                        continue
                    if member_id not in user_map:
                        continue
                    user_uuid, name = user_map[member_id]
                    for q_id, answer in responses.items():
                        if isinstance(answer, str) and len(answer) >= MIN_TEXT_LEN:
                            result = await insert_crystal(conn, user_uuid, name, answer, "coached_response", min_score=3)
                            counts[result] += 1

                if counts["created"] > 0:
                    print(f"  {sid}: +{counts['created']} new (dup={counts['dup']}, short={counts['short']}, low={counts['low_score']})")
                for k in ("created", "dup", "short", "low_score", "error"):
                    total[k] += counts.get(k, 0)

    print()
    print("=" * 60)
    print(f"TOTAL CRYSTALS CREATED: {total['created']}")
    print(f"  Duplicates: {total['dup']}")
    print(f"  Too short: {total['short']}")
    print(f"  Low score: {total['low_score']}")
    print(f"  Decrypt fail: {total.get('decrypt_fail', 0)}")
    print(f"  Errors: {total['error']}")
    print("=" * 60)

    # Final summary
    async with pool.acquire() as conn:
        summary = await conn.fetch("""
            SELECT u.profile_data->>'name' as name, COUNT(*) as crystals,
              string_agg(DISTINCT c.origin_surface, ', ') as surfaces
            FROM nate_intelligence_crystals c
            JOIN users u ON u.id = c.user_id
            WHERE c.scope = 'user'
            GROUP BY u.profile_data->>'name'
            ORDER BY crystals DESC
        """)
        print()
        print("CRYSTAL INVENTORY:")
        for r in summary:
            print(f"  {r['name']}: {r['crystals']} crystals (surfaces: {r['surfaces']})")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
