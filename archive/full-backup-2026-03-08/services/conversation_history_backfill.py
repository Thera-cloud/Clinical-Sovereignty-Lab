"""
Conversation history backfill — reusable logic for script and admin API.
Reads Vaults/{Clients,Coaches,Admin}/*/memory.json and inserts into PostgreSQL.
"""

import datetime
import json
import os
from pathlib import Path
from typing import Optional

STANDARD_KEYS = {"timestamp", "session_id", "user", "ai", "word_count_user", "word_count_ai"}


def _parse_timestamp(ts) -> Optional[datetime.datetime]:
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


def collect_memory_files(vault_root: Path, hw_id_filter: Optional[str] = None) -> list[tuple[Path, str]]:
    out = []
    for subdir in ("Clients", "Coaches", "Admin"):
        base = vault_root / subdir
        if not base.exists():
            continue
        for d in base.iterdir():
            if d.is_dir():
                if hw_id_filter and d.name != hw_id_filter:
                    continue
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
    ts = _parse_timestamp(entry.get("timestamp"))
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


async def run_backfill(db_pool, hw_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """Run backfill using existing db_pool. Returns files_processed, total_entries, total_inserted, errors."""
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    vault_root = data_dir / "Vaults"
    if not vault_root.exists():
        return {"error": f"Vault root not found: {vault_root}", "files_processed": 0, "total_entries": 0, "total_inserted": 0, "errors": []}

    files = collect_memory_files(vault_root, hw_id_filter=hw_id)
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
            except Exception as e:
                errors.append(f"{path}: {e}")
        return {
            "files_processed": len(files),
            "total_entries": total_entries,
            "total_inserted": 0,
            "errors": errors,
            "dry_run": True,
        }

    async with db_pool.acquire() as conn:
        for path, user_id in files:
            try:
                with open(path) as f:
                    raw = json.load(f)
                if not isinstance(raw, list):
                    errors.append(f"{path}: not a JSON array")
                    continue
                entries = [parse_entry(e, user_id) for e in raw if isinstance(e, dict)]
                entries = [e for e in entries if e is not None]
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
            except Exception as e:
                errors.append(f"{path}: {e}")

    return {
        "files_processed": len(files),
        "total_entries": total_entries,
        "total_inserted": total_inserted,
        "errors": errors,
    }
