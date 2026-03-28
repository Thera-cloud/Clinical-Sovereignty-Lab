#!/usr/bin/env python3
"""
Backfill existing PostgreSQL data into Cloudflare Vectorize indexes.

Indexes all 6 content types:
  1. conversation_history → nate-memory-search
  2. vault_items → nate-vault-search
  3. wisdom_extractions → nate-wisdom
  4. me2me_imprint_entries → nate-me2me
  5. session memories → nate-sessions (from local session_memories dir)
  6. vault_item_annotations → nate-annotations

Usage:
  python3 backfill_vectorize.py [--index all|conversation|vault|wisdom|me2me|session|annotation]
                                [--batch-size 50] [--limit 0]

Env vars required: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, DATABASE_URL
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_vectorize")


async def get_db_pool():
    import asyncpg
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "nate_admin")
        pw = os.getenv("POSTGRES_PASSWORD", "")
        db = os.getenv("POSTGRES_DB", "little_nate")
        db_url = f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    return await asyncpg.create_pool(db_url, min_size=1, max_size=3)


def _vec_id(source: str, record_id: str) -> str:
    raw = f"{source}:{record_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def backfill_conversations(db_pool, batch_size: int, limit: int):
    from app.services.vectorize_service import batch_embed_and_upsert, INDEX_NAMES

    logger.info("=== Backfilling conversation_history → %s ===", INDEX_NAMES["conversation"])

    async with db_pool.acquire() as conn:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        rows = await conn.fetch(f"""
            SELECT id, user_id, session_id, user_text, ai_text, created_at
            FROM conversation_history
            WHERE user_text IS NOT NULL AND ai_text IS NOT NULL
            ORDER BY created_at DESC
            {limit_clause}
        """)

    logger.info("Found %d conversation entries", len(rows))
    items = []
    for r in rows:
        u = r["user_text"] or ""
        a = r["ai_text"] or ""
        if not u and not a:
            continue
        ts = r["created_at"].isoformat() if r["created_at"] else ""
        items.append({
            "id": _vec_id("conv", str(r["id"])),
            "text": f"User: {u[:1000]}\nAI: {a[:1000]}",
            "metadata": {
                "user_id": r["user_id"],
                "session_id": r["session_id"] or "",
                "timestamp": ts,
                "source": "conversation",
                "preview": f"User: {u[:150]}... AI: {a[:150]}",
            },
        })

    total = await batch_embed_and_upsert(INDEX_NAMES["conversation"], items)
    logger.info("Upserted %d / %d conversation vectors", total, len(items))
    return total


async def backfill_vault_items(db_pool, batch_size: int, limit: int):
    from app.services.vectorize_service import batch_embed_and_upsert, INDEX_NAMES

    logger.info("=== Backfilling vault_items → %s ===", INDEX_NAMES["vault"])

    async with db_pool.acquire() as conn:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        rows = await conn.fetch(f"""
            SELECT id, member_id, filename, display_name, mime_type,
                   extracted_text_preview, themes, created_at
            FROM vault_items
            ORDER BY created_at DESC
            {limit_clause}
        """)

    logger.info("Found %d vault items", len(rows))
    items = []
    for r in rows:
        fname = r["display_name"] or r["filename"] or "unnamed"
        text_parts = [fname]
        if r["extracted_text_preview"]:
            text_parts.append(r["extracted_text_preview"])
        themes_str = ""
        if r["themes"]:
            try:
                tl = r["themes"] if isinstance(r["themes"], list) else json.loads(r["themes"])
                themes_str = ", ".join(str(t) for t in tl[:5])
                text_parts.append(f"Themes: {themes_str}")
            except Exception:
                pass
        ts = r["created_at"].isoformat() if r["created_at"] else ""
        items.append({
            "id": _vec_id("vault", str(r["id"])),
            "text": " ".join(text_parts),
            "metadata": {
                "user_id": r["member_id"],
                "item_id": str(r["id"]),
                "filename": fname,
                "mime_type": r["mime_type"] or "",
                "timestamp": ts,
                "source": "vault_item",
            },
        })

    total = await batch_embed_and_upsert(INDEX_NAMES["vault"], items)
    logger.info("Upserted %d / %d vault vectors", total, len(items))
    return total


async def backfill_wisdom(db_pool, batch_size: int, limit: int):
    from app.services.vectorize_service import batch_embed_and_upsert, INDEX_NAMES

    logger.info("=== Backfilling wisdom_extractions → %s ===", INDEX_NAMES["wisdom"])

    async with db_pool.acquire() as conn:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        rows = await conn.fetch(f"""
            SELECT id, user_id, family_id, session_id, insight_type,
                   content, source, extracted_at
            FROM wisdom_extractions
            ORDER BY extracted_at DESC
            {limit_clause}
        """)

    logger.info("Found %d wisdom extractions", len(rows))
    items = []
    for r in rows:
        content = r["content"] or ""
        if not content:
            continue
        ts = r["extracted_at"].isoformat() if r["extracted_at"] else ""
        items.append({
            "id": _vec_id("wisdom", str(r["id"])),
            "text": f"[{r['insight_type'] or ''}] {content[:1500]}",
            "metadata": {
                "user_id": r["user_id"],
                "family_id": r["family_id"] or "",
                "insight_type": r["insight_type"] or "",
                "session_id": r["session_id"] or "",
                "source": r["source"] or "",
                "timestamp": ts,
                "preview": content[:300],
            },
        })

    total = await batch_embed_and_upsert(INDEX_NAMES["wisdom"], items)
    logger.info("Upserted %d / %d wisdom vectors", total, len(items))
    return total


async def backfill_me2me(db_pool, batch_size: int, limit: int):
    from app.services.vectorize_service import batch_embed_and_upsert, INDEX_NAMES

    logger.info("=== Backfilling me2me_imprint_entries → %s ===", INDEX_NAMES["me2me"])

    async with db_pool.acquire() as conn:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        rows = await conn.fetch(f"""
            SELECT entry_id, user_id, source, content, themes, emotions, captured_at
            FROM me2me_imprint_entries
            ORDER BY captured_at DESC
            {limit_clause}
        """)

    logger.info("Found %d me2me entries", len(rows))
    items = []
    for r in rows:
        content = r["content"] or ""
        if not content:
            continue
        text_parts = [content[:1500]]
        if r["themes"]:
            text_parts.append(f"Themes: {r['themes']}")
        if r["emotions"]:
            text_parts.append(f"Emotions: {r['emotions']}")
        ts = r["captured_at"].isoformat() if r["captured_at"] else ""
        items.append({
            "id": _vec_id("me2me", r["entry_id"]),
            "text": " ".join(text_parts),
            "metadata": {
                "user_id": r["user_id"],
                "entry_id": r["entry_id"],
                "source": r["source"] or "",
                "timestamp": ts,
                "preview": content[:300],
            },
        })

    total = await batch_embed_and_upsert(INDEX_NAMES["me2me"], items)
    logger.info("Upserted %d / %d me2me vectors", total, len(items))
    return total


async def backfill_sessions(batch_size: int, limit: int):
    from app.services.vectorize_service import batch_embed_and_upsert, INDEX_NAMES

    logger.info("=== Backfilling session memories → %s ===", INDEX_NAMES["session"])

    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    memories_dir = data_dir / "session_memories"
    if not memories_dir.exists():
        logger.info("No session_memories directory found at %s", memories_dir)
        return 0

    items = []
    count = 0
    for session_dir in sorted(memories_dir.iterdir(), reverse=True):
        if limit > 0 and count >= limit:
            break
        if not session_dir.is_dir():
            continue

        index_file = session_dir / "memory_index.json"
        if not index_file.exists():
            continue

        try:
            record = json.loads(index_file.read_text())
        except Exception:
            continue

        session_id = record.get("session_id", session_dir.name)
        coach_id = record.get("coach_id", "")
        client_id = record.get("client_id", "")
        summary = record.get("summary", "")
        family_id = record.get("family_id", "")
        ts = record.get("created_at", "")

        transcript = ""
        transcript_file = session_dir / "transcript.vtt"
        if transcript_file.exists():
            try:
                transcript = transcript_file.read_text()[:1500]
            except Exception:
                pass

        text_parts = []
        if transcript:
            text_parts.append(transcript)
        if summary:
            text_parts.append(f"Analysis: {summary}")
        combined = " ".join(text_parts) or "coaching session"

        items.append({
            "id": _vec_id("session", session_id),
            "text": combined,
            "metadata": {
                "session_id": session_id,
                "coach_id": coach_id,
                "client_id": client_id,
                "user_id": client_id,
                "family_id": family_id,
                "timestamp": ts,
                "source": "session",
                "preview": combined[:300],
            },
        })
        count += 1

    logger.info("Found %d session memories", len(items))
    total = await batch_embed_and_upsert(INDEX_NAMES["session"], items)
    logger.info("Upserted %d / %d session vectors", total, len(items))
    return total


async def backfill_annotations(db_pool, batch_size: int, limit: int):
    from app.services.vectorize_service import batch_embed_and_upsert, INDEX_NAMES

    logger.info("=== Backfilling vault_item_annotations → %s ===", INDEX_NAMES["annotation"])

    async with db_pool.acquire() as conn:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        rows = await conn.fetch(f"""
            SELECT a.id, a.vault_item_id, a.user_id, a.annotation_type,
                   a.content, a.created_at,
                   vi.filename, vi.display_name
            FROM vault_item_annotations a
            LEFT JOIN vault_items vi ON a.vault_item_id = vi.id
            ORDER BY a.created_at DESC
            {limit_clause}
        """)

    logger.info("Found %d annotations", len(rows))
    items = []
    for r in rows:
        content = r["content"] or ""
        if not content:
            continue
        fname = r["display_name"] or r["filename"] or "photo"
        ts = r["created_at"].isoformat() if r["created_at"] else ""
        items.append({
            "id": _vec_id("annotation", str(r["id"])),
            "text": f"{fname}: [{r['annotation_type'] or ''}] {content[:1500]}",
            "metadata": {
                "user_id": r["user_id"],
                "vault_item_id": str(r["vault_item_id"]),
                "annotation_type": r["annotation_type"] or "",
                "filename": fname,
                "timestamp": ts,
                "source": "vault_annotation",
                "preview": content[:300],
            },
        })

    total = await batch_embed_and_upsert(INDEX_NAMES["annotation"], items)
    logger.info("Upserted %d / %d annotation vectors", total, len(items))
    return total


async def main():
    parser = argparse.ArgumentParser(description="Backfill Vectorize indexes")
    parser.add_argument("--index", default="all",
                        choices=["all", "conversation", "vault", "wisdom", "me2me", "session", "annotation"])
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = parser.parse_args()

    from app.services.vectorize_service import is_vectorize_configured
    if not is_vectorize_configured():
        logger.error("Vectorize not configured — set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")
        sys.exit(1)

    db_pool = await get_db_pool()
    total = 0

    try:
        if args.index in ("all", "conversation"):
            total += await backfill_conversations(db_pool, args.batch_size, args.limit)
        if args.index in ("all", "vault"):
            total += await backfill_vault_items(db_pool, args.batch_size, args.limit)
        if args.index in ("all", "wisdom"):
            total += await backfill_wisdom(db_pool, args.batch_size, args.limit)
        if args.index in ("all", "me2me"):
            total += await backfill_me2me(db_pool, args.batch_size, args.limit)
        if args.index in ("all", "session"):
            total += await backfill_sessions(args.batch_size, args.limit)
        if args.index in ("all", "annotation"):
            total += await backfill_annotations(db_pool, args.batch_size, args.limit)
    finally:
        await db_pool.close()
        from app.services.vectorize_service import close
        await close()

    logger.info("=== BACKFILL COMPLETE: %d vectors upserted ===", total)


if __name__ == "__main__":
    asyncio.run(main())
