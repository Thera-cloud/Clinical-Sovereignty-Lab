"""
Backfill script: encrypt all existing plaintext rows with pgcrypto AES-256.

Reads PII_ENCRYPTION_KEY from env (or DATABASE_URL for connection).
For each table, runs batched UPDATEs that fire the existing triggers.

Usage:
    PII_ENCRYPTION_KEY="your-key" python3 backend/scripts/backfill_pgcrypto_encryption.py

Options:
    --dry-run         Print row counts only, no writes
    --table TABLE     Process only the specified table
    --batch-size N    Rows per UPDATE batch (default 500)
"""
import argparse
import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_pgcrypto")

TABLES = [
    {
        "name": "users",
        "pk": "id",
        "pk_type": "UUID",
        "columns": ["email", "name", "dob"],
        "enc_columns": ["email_enc", "name_enc", "dob_enc"],
        "where_missing": "email_enc IS NULL AND (email IS NOT NULL OR name IS NOT NULL OR dob IS NOT NULL)",
        "update_sql": "UPDATE users SET email = email, name = name, dob = dob WHERE id = ANY($1::uuid[])",
    },
    {
        "name": "conversation_history",
        "pk": "id",
        "pk_type": "BIGINT",
        "columns": ["user_text", "ai_text"],
        "enc_columns": ["user_text_enc", "ai_text_enc"],
        "where_missing": "user_text_enc IS NULL AND user_text IS NOT NULL",
        "update_sql": "UPDATE conversation_history SET user_text = user_text, ai_text = ai_text WHERE id = ANY($1::bigint[])",
    },
    {
        "name": "nevedal_metrics",
        "pk": "id",
        "pk_type": "BIGINT",
        "columns": ["biometrics"],
        "enc_columns": ["biometrics_enc"],
        "where_missing": "biometrics_enc IS NULL AND biometrics IS NOT NULL AND biometrics::text != '{}'",
        "update_sql": "UPDATE nevedal_metrics SET biometrics = biometrics WHERE id = ANY($1::bigint[])",
    },
    {
        "name": "coaching_sessions",
        "pk": "session_id",
        "pk_type": "TEXT",
        "columns": ["notes", "coach_notes", "nate_summary"],
        "enc_columns": ["session_notes_enc", "coach_notes_enc", "nate_summary_enc"],
        "where_missing": "session_notes_enc IS NULL AND (notes IS NOT NULL OR coach_notes IS NOT NULL OR nate_summary IS NOT NULL)",
        "update_sql": "UPDATE coaching_sessions SET notes = notes, coach_notes = coach_notes, nate_summary = nate_summary WHERE session_id = ANY($1::text[])",
    },
    {
        "name": "crisis_watchlist",
        "pk": "id",
        "pk_type": "UUID",
        "columns": ["trigger_context", "trigger_keyword"],
        "enc_columns": ["trigger_context_enc", "trigger_keyword_enc"],
        "where_missing": "trigger_context_enc IS NULL AND (trigger_context IS NOT NULL OR trigger_keyword IS NOT NULL)",
        "update_sql": "UPDATE crisis_watchlist SET trigger_context = trigger_context, trigger_keyword = trigger_keyword WHERE id = ANY($1::uuid[])",
    },
    {
        "name": "vault_items",
        "pk": "id",
        "pk_type": "UUID",
        "columns": ["extracted_text_preview"],
        "enc_columns": ["content_enc"],
        "where_missing": "content_enc IS NULL AND extracted_text_preview IS NOT NULL",
        "update_sql": "UPDATE vault_items SET extracted_text_preview = extracted_text_preview WHERE id = ANY($1::uuid[])",
    },
    {
        "name": "login_attempts",
        "pk": "id",
        "pk_type": "BIGINT",
        "columns": ["identifier"],
        "enc_columns": ["identifier_enc"],
        "where_missing": "identifier_enc IS NULL AND identifier IS NOT NULL",
        "update_sql": "UPDATE login_attempts SET identifier = identifier WHERE id = ANY($1::bigint[])",
    },
]


async def backfill_table(pool, table: dict, key: str, batch_size: int, dry_run: bool):
    name = table["name"]
    pk = table["pk"]
    where = table["where_missing"]

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM {name} WHERE {where}"
        )
        log.info("[%s] %d rows need encryption", name, total)
        if dry_run or total == 0:
            return total

    processed = 0
    while True:
        async with pool.acquire() as conn:
            # Set the encryption key for this session
            await conn.execute(f"SET LOCAL app.pii_key = '{key}'")

            rows = await conn.fetch(
                f"SELECT {pk} FROM {name} WHERE {where} LIMIT {batch_size}"
            )
            if not rows:
                break
            ids = [r[pk] for r in rows]
            await conn.execute(table["update_sql"], ids)
            processed += len(ids)
            log.info("[%s] Encrypted %d / %d rows", name, processed, total)

    log.info("[%s] Backfill complete — %d rows encrypted", name, processed)
    return processed


async def main(args):
    try:
        import asyncpg
    except ImportError:
        log.error("asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    key = os.environ.get("PII_ENCRYPTION_KEY") or os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        log.error("PII_ENCRYPTION_KEY environment variable is required.")
        log.error("Generate with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        sys.exit(1)

    db_url = os.environ.get("DATABASE_URL", "postgresql://nate_admin@localhost/little_nate")
    log.info("Connecting to database...")
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

    tables = TABLES
    if args.table:
        tables = [t for t in TABLES if t["name"] == args.table]
        if not tables:
            log.error("Unknown table: %s", args.table)
            sys.exit(1)

    total_encrypted = 0
    for table in tables:
        count = await backfill_table(pool, table, key, args.batch_size, args.dry_run)
        total_encrypted += count

    await pool.close()

    if args.dry_run:
        log.info("DRY RUN complete — %d total rows would be encrypted", total_encrypted)
    else:
        log.info("Backfill complete — %d total rows encrypted across %d tables",
                 total_encrypted, len(tables))
        log.info("Run this SQL to verify coverage:")
        log.info("  SELECT * FROM encryption_coverage ORDER BY table_name, field_name;")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill pgcrypto encryption for existing rows")
    parser.add_argument("--dry-run", action="store_true", help="Count rows only, no writes")
    parser.add_argument("--table", help="Process only this table")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per batch (default 500)")
    args = parser.parse_args()
    asyncio.run(main(args))
