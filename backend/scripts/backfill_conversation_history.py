#!/usr/bin/env python3
"""
One-time migration: backfill conversation_history from memory.json files.
Reads Vaults/{Clients,Coaches,Admin}/*/memory.json and inserts into PostgreSQL.
"""

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Optional

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
    load_dotenv(project_root.parent / ".env")
except ImportError:
    pass

STANDARD_KEYS = {"timestamp", "session_id", "user", "ai", "word_count_user", "word_count_ai"}


def parse_timestamp(ts) -> Optional[datetime.datetime]:
    if ts is None:
        return None
    s = str(ts)
    fmts = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in fmts:
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        from dateutil.parser import parse as dateutil_parse
        return dateutil_parse(s)
    except ImportError:
        pass
    return None


def build_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "nate_admin")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    db = os.environ.get("POSTGRES_DB", "little_nate")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def collect_memory_files(vault_root: Path) -> list[tuple[Path, str]]:
    out = []
    for subdir in ("Clients", "Coaches", "Admin"):
        base = vault_root / subdir
        if not base.exists():
            continue
        for d in base.iterdir():
            if d.is_dir():
                mf = d / "memory.json"
                if mf.exists():
                    out.append((mf, d.name))
    return out


def parse_entry(entry: dict, user_id: str) -> Optional[dict]:
    user_text = entry.get("user")
    ai_text = entry.get("ai")
    if user_text is None and ai_text is None:
        return None
    user_text = "" if user_text is None else str(user_text)
    ai_text = "" if ai_text is None else str(ai_text)
    ts = parse_timestamp(entry.get("timestamp"))
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc)
    elif ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    session_id = entry.get("session_id") or ""
    wc_user = entry.get("word_count_user")
    wc_ai = entry.get("word_count_ai")
    if wc_user is None:
        wc_user = len(user_text.split())
    if wc_ai is None:
        wc_ai = len(ai_text.split())
    metadata = {k: v for k, v in entry.items() if k not in STANDARD_KEYS}
    return {
        "user_id": user_id,
        "session_id": session_id,
        "user_text": user_text,
        "ai_text": ai_text,
        "word_count_user": int(wc_user),
        "word_count_ai": int(wc_ai),
        "metadata": metadata,
        "created_at": ts,
    }


async def backfill(dry_run: bool) -> dict:
    import asyncpg

    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    vault_root = data_dir / "Vaults"
    if not vault_root.exists():
        return {"error": f"Vault root not found: {vault_root}"}

    database_url = build_database_url()
    if not os.environ.get("POSTGRES_PASSWORD") and "DATABASE_URL" not in os.environ:
        return {"error": "POSTGRES_PASSWORD or DATABASE_URL required"}

    files = collect_memory_files(vault_root)
    total_inserted = 0
    total_entries = 0
    errors = []

    if dry_run:
        for path, user_id in files:
            try:
                with open(path) as f:
                    entries = json.load(f)
                if not isinstance(entries, list):
                    errors.append(f"{path}: not a JSON array")
                    continue
                valid = sum(1 for e in entries if isinstance(e, dict) and parse_entry(e, user_id))
                total_entries += valid
                print(f"Processing {path}: {len(entries)} entries")
            except Exception as e:
                errors.append(f"{path}: {e}")
        return {
            "files_processed": len(files),
            "total_entries": total_entries,
            "total_inserted": 0,
            "errors": errors,
            "dry_run": True,
        }

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3, command_timeout=60)

    async with pool.acquire() as conn:
        for path, user_id in files:
            try:
                with open(path) as f:
                    raw = json.load(f)
                if not isinstance(raw, list):
                    errors.append(f"{path}: not a JSON array")
                    continue
                entries = [parse_entry(e, user_id) for e in raw if isinstance(e, dict)]
                entries = [e for e in entries if e is not None]
                print(f"Processing {path}: {len(entries)} entries")
                total_entries += len(entries)
                inserted = 0
                for e in entries:
                    r = await conn.execute(
                        """
                        INSERT INTO conversation_history
                            (user_id, session_id, user_text, ai_text,
                             word_count_user, word_count_ai, metadata, created_at)
                        SELECT $1, $2, $3, $4, $5, $6, $7::jsonb, $8::timestamptz
                        WHERE NOT EXISTS (
                            SELECT 1 FROM conversation_history
                            WHERE user_id = $1 AND created_at = $8 AND user_text = $3
                        )
                        """,
                        e["user_id"],
                        e["session_id"],
                        e["user_text"],
                        e["ai_text"],
                        e["word_count_user"],
                        e["word_count_ai"],
                        json.dumps(e["metadata"]),
                        e["created_at"],
                    )
                    if r == "INSERT 0 1":
                        inserted += 1
                total_inserted += inserted
                print(f"Inserted {inserted} new rows for {user_id}")
            except Exception as e:
                errors.append(f"{path}: {e}")
                print(f"Error processing {path}: {e}")

    await pool.close()
    return {
        "files_processed": len(files),
        "total_entries": total_entries,
        "total_inserted": total_inserted,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Backfill conversation_history from memory.json")
    parser.add_argument("--dry-run", action="store_true", help="Count entries without inserting")
    args = parser.parse_args()

    result = asyncio.run(backfill(dry_run=args.dry_run))

    if "error" in result:
        print(f"Fatal: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print("\n--- Summary ---")
    print(f"Files processed: {result['files_processed']}")
    print(f"Total entries: {result['total_entries']}")
    print(f"Total inserted: {result['total_inserted']}")
    if result.get("dry_run"):
        print("(dry run — no rows inserted)")
    if result.get("errors"):
        print("\nErrors:")
        for e in result["errors"]:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
