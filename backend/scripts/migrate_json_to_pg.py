#!/usr/bin/env python3
"""
LITTLE NATE — Migrate user_registry.json to PostgreSQL
=======================================================
One-time migration script that reads all users from the JSON registry
and inserts/upserts them into the PostgreSQL `users` table.

Usage:
    cd backend
    python -m scripts.migrate_json_to_pg

Or with explicit paths:
    python scripts/migrate_json_to_pg.py --json-path /path/to/user_registry.json

Requirements:
    - DATABASE_URL environment variable set (or .env file)
    - PostgreSQL running with migrations applied (at least 001 + 030)
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
    load_dotenv(project_root.parent / ".env")
except ImportError:
    pass


async def migrate(json_path: str, database_url: str, dry_run: bool = False):
    """Migrate users from JSON to PostgreSQL."""
    import asyncpg

    # Load JSON registry
    print(f"[*] Loading JSON registry from: {json_path}")
    with open(json_path, "r") as f:
        registry = json.load(f)

    if not isinstance(registry, dict):
        print("[!] Registry is not a dict. Aborting.")
        return

    # Filter to actual user entries
    user_entries = {}
    skipped = []
    for key, value in registry.items():
        if key.startswith("_"):
            skipped.append(key)
            continue
        if not isinstance(value, dict):
            skipped.append(key)
            continue
        if not value.get("credentials") and not value.get("profile"):
            skipped.append(key)
            continue
        user_entries[key] = value

    print(f"[*] Found {len(user_entries)} user entries ({len(skipped)} non-user keys skipped)")
    if skipped:
        print(f"    Skipped: {skipped}")

    if dry_run:
        print("\n[DRY RUN] Would insert/update these users:")
        for key, entry in user_entries.items():
            creds = entry.get("credentials", {})
            profile = entry.get("profile", {})
            username = creds.get("username", key)
            role = profile.get("role", entry.get("role", "?"))
            name = profile.get("name", "?")
            hw_id = profile.get("hardware_id", "?")
            print(f"    {key:30s} -> username={username}, role={role}, name={name}, hw_id={hw_id}")
        return

    # Connect to PostgreSQL
    print(f"[*] Connecting to PostgreSQL...")
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3, command_timeout=30)

    # Ensure profile_data column exists
    async with pool.acquire() as conn:
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'profile_data'
            )
        """)
        if not exists:
            await conn.execute("ALTER TABLE users ADD COLUMN profile_data JSONB DEFAULT '{}'::jsonb")
            print("[*] Added profile_data column")

    # Import UserStore for upsert logic
    sys.path.insert(0, str(project_root / "app" / "websocket"))
    from user_store import UserStore

    store = UserStore(pool)
    store._ready = True  # Force ready for migration

    # Upsert each user
    success = 0
    failed = 0
    for key, entry in user_entries.items():
        creds = entry.get("credentials", {})
        profile = entry.get("profile", {})

        # Handle legacy entries without proper credentials block
        if not creds.get("username"):
            # Legacy format: username at top level
            creds = {
                "username": entry.get("username", key),
                "password": entry.get("password_hash", ""),
            }
            entry["credentials"] = creds

        # Handle legacy entries without proper profile block
        if not profile.get("role") and entry.get("role"):
            profile["role"] = entry["role"]
            entry["profile"] = profile

        username = creds.get("username", key)
        try:
            ok = await store.upsert_user(key, entry)
            if ok:
                success += 1
                role = profile.get("role", "?")
                print(f"    [OK] {username:20s} (role={role})")
            else:
                failed += 1
                print(f"    [FAIL] {username:20s} - upsert returned False")
        except Exception as e:
            failed += 1
            print(f"    [FAIL] {username:20s} - {e}")

    print(f"\n[*] Migration complete: {success} succeeded, {failed} failed")

    # Verify
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL")
        print(f"[*] Total users in PostgreSQL: {count}")

    await pool.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate user_registry.json to PostgreSQL")
    parser.add_argument(
        "--json-path",
        default=None,
        help="Path to user_registry.json (auto-detected if not provided)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without writing to DB",
    )
    args = parser.parse_args()

    # Auto-detect JSON path
    json_path = args.json_path
    if not json_path:
        candidates = [
            project_root / "app" / "websocket" / "data" / "user_registry.json",
            Path("/app/data/user_registry.json"),
            project_root.parent / "data" / "bridge" / "user_registry.json",
        ]
        for c in candidates:
            if c.exists():
                json_path = str(c)
                break
        if not json_path:
            print("[!] Could not find user_registry.json. Use --json-path to specify.")
            sys.exit(1)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[!] DATABASE_URL not set. Set it in .env or environment.")
        sys.exit(1)

    asyncio.run(migrate(json_path, database_url, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
