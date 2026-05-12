#!/usr/bin/env python3
"""
Rebuild vault memory.json files from PostgreSQL conversation_history.

Coach / Sovereign Command surfaces read hippocampus.recall_full() → Vaults/{Clients|Coaches|Admin}/<hardware_id>/memory.json.
This script repopulates those files from PG without modifying bridge code or conversation_history.

Run inside nate_bridge (DATABASE_URL + /app/data/Vaults mount):
  docker cp scripts/rebuild_memory_from_pg.py nate_bridge:/tmp/rebuild_memory_from_pg.py
  docker exec nate_bridge python3 /tmp/rebuild_memory_from_pg.py --dry-run
  docker exec nate_bridge python3 /tmp/rebuild_memory_from_pg.py \\
    --hardware-id CLIENT_HW_ID --limit 8000 --decrypt-conversation

Do NOT use nate_backend for vault paths — backend mounts data/backend, not data/bridge.

Atomic write: memory.json.tmp.<pid> → rename to memory.json after JSON validate.
Backup: copy existing memory.json to memory.json.pre_rebuild_<UTC> before replace (live mode only).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import asyncpg

log = logging.getLogger("rebuild_memory_from_pg")

ROLE_FOLDER = {
    "CLIENT": "Clients",
    "COACH": "Coaches",
    "ADMIN": "Admin",
}


def _fmt_ts(dt: datetime) -> str:
    """Match legacy memory.json: naive UTC microsecond string."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _resolve_pii_key_script() -> Optional[str]:
    """Mirror backend/db_encryption_middleware.py priority for decrypt_pii(bytea)."""
    k = os.environ.get("PII_ENCRYPTION_KEY", "").strip()
    if k:
        return k
    k = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
    if k:
        return k
    jwt = os.environ.get("JWT_SECRET", "").strip()
    if jwt:
        return hashlib.sha256(f"pii-pgcrypto:{jwt}".encode()).hexdigest()
    return None


def _make_fernet():
    """Fernet for TEXT columns starting with gAAAAA (app/services/pii_cipher.py)."""
    raw = os.environ.get("SKYEYE_TOKEN_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception as e:
        log.warning("Fernet init failed: %s", e)
        return None


async def _decrypt_chat_field(
    conn: asyncpg.Connection,
    text_col: Optional[str],
    bytea_col: Optional[bytes],
    fernet,
    *,
    sql_decrypt_ok: bool,
) -> str:
    """Undo migration 105 BYTEA + optional app-layer Fernet on TEXT."""
    text_col = text_col or ""
    if text_col.startswith("gAAAAA") and fernet is not None:
        try:
            return fernet.decrypt(text_col.encode()).decode()
        except Exception:
            log.debug("fernet decrypt failed on text column len=%s", len(text_col))
    if text_col and not text_col.startswith("gAAAAA"):
        return text_col

    mid: Optional[str] = None
    if bytea_col is not None and sql_decrypt_ok:
        mid = await conn.fetchval("SELECT decrypt_pii($1)", bytea_col)
    if mid:
        if mid.startswith("gAAAAA") and fernet is not None:
            try:
                return fernet.decrypt(mid.encode()).decode()
            except Exception:
                return "[encrypted — decrypt failed]"
        return mid
    if text_col.startswith("gAAAAA"):
        return "[encrypted — decrypt failed]"
    return ""


async def prepare_decrypt_session(conn: asyncpg.Connection, enable_sql: bool) -> bool:
    if not enable_sql:
        return False
    key = _resolve_pii_key_script()
    if not key:
        log.warning("SQL decrypt skipped — no PII_ENCRYPTION_KEY / FIELD_ENCRYPTION_KEY / JWT_SECRET")
        return False
    await conn.execute("SELECT set_config('app.pii_key', $1, false)", key)
    return True


async def plaintext_row_fields(
    conn: asyncpg.Connection,
    row: asyncpg.Record,
    *,
    decrypt: bool,
    fernet,
    sql_decrypt_ok: bool,
) -> tuple[str, str]:
    if not decrypt:
        return (row.get("user_text") or "", row.get("ai_text") or "")
    ut_enc = row.get("user_text_enc")
    ai_enc = row.get("ai_text_enc")
    ut = await _decrypt_chat_field(conn, row.get("user_text"), ut_enc, fernet, sql_decrypt_ok=sql_decrypt_ok)
    ai = await _decrypt_chat_field(conn, row.get("ai_text"), ai_enc, fernet, sql_decrypt_ok=sql_decrypt_ok)
    return (ut, ai)


def pg_row_to_entry(
    row: asyncpg.Record,
    *,
    utext: str,
    atext: str,
) -> Optional[Dict[str, Any]]:
    if row.get("content_encrypted"):
        ut = (utext or "").strip()
        at = (atext or "").strip()
        if not ut and not at:
            return None
    sid = (row.get("session_id") or "").strip()
    wu = row.get("word_count_user")
    wa = row.get("word_count_ai")
    if wu is None:
        wu = len(str(utext).split())
    if wa is None:
        wa = len(str(atext).split())
    return {
        "timestamp": _fmt_ts(row["created_at"]),
        "session_id": sid if sid else None,
        "user": utext,
        "ai": atext,
        "word_count_user": int(wu),
        "word_count_ai": int(wa),
    }


async def resolve_targets(
    conn: asyncpg.Connection, cutoff: datetime
) -> Dict[str, Dict[str, Any]]:
    """hardware_id -> {username, role, aliases:set}."""
    raw = await conn.fetch(
        """
        SELECT DISTINCT user_id
        FROM conversation_history
        WHERE created_at > $1::timestamptz
        """,
        cutoff,
    )
    targets: Dict[str, Dict[str, Any]] = {}
    for r in raw:
        uid = (r["user_id"] or "").strip()
        if not uid:
            continue
        urow = await conn.fetchrow(
            """
            SELECT username, hardware_id, role
            FROM users
            WHERE username = $1 OR hardware_id = $1
            ORDER BY CASE WHEN username = $1 THEN 0 ELSE 1 END
            LIMIT 1
            """,
            uid,
        )
        if not urow:
            log.warning("orphan user_id in conversation_history (no users row): %s", uid)
            continue
        hw = (urow["hardware_id"] or "").strip()
        role = (urow["role"] or "").strip().upper()
        uname = (urow["username"] or "").strip()
        if not hw:
            log.warning("user %s has empty hardware_id — skip", uid)
            continue
        if role not in ROLE_FOLDER:
            log.warning("skip user_id=%s role=%s (not CLIENT/COACH/ADMIN)", uid, role)
            continue
        bucket = targets.setdefault(
            hw,
            {"username": uname, "role": role, "aliases": set()},
        )
        bucket["aliases"].add(uid)
        bucket["aliases"].add(uname)
        bucket["aliases"].add(hw)
    return targets


async def resolve_single_hardware(
    conn: asyncpg.Connection, hardware_id: str
) -> Optional[Dict[str, Any]]:
    urow = await conn.fetchrow(
        """
        SELECT username, hardware_id, role
        FROM users
        WHERE hardware_id = $1
        LIMIT 1
        """,
        hardware_id.strip(),
    )
    if not urow:
        log.error("No users row for hardware_id=%s", hardware_id)
        return None
    role = (urow["role"] or "").strip().upper()
    uname = (urow["username"] or "").strip()
    hw = (urow["hardware_id"] or "").strip()
    if role not in ROLE_FOLDER:
        log.error("hardware_id=%s has unsupported role=%s", hardware_id, role)
        return None
    aliases = {uname, hw}
    aliases.discard("")
    return {"username": uname, "role": role, "aliases": aliases}


async def fetch_history_rows(
    conn: asyncpg.Connection,
    aliases: Set[str],
    limit: int,
    *,
    include_bytea: bool,
) -> List[asyncpg.Record]:
    alias_list = sorted(aliases)
    enc_cols = (
        ", user_text_enc, ai_text_enc"
        if include_bytea
        else ""
    )
    rows = await conn.fetch(
        f"""
        SELECT id, user_text, ai_text, session_id, created_at,
               word_count_user, word_count_ai,
               COALESCE(content_encrypted, false) AS content_encrypted
               {enc_cols}
        FROM conversation_history
        WHERE user_id = ANY($1::text[])
        ORDER BY created_at ASC, id ASC
        """,
        alias_list,
    )
    if len(rows) <= limit:
        return list(rows)
    return list(rows[-limit:])


def atomic_write_json(path: Path, data: Any, dry_run: bool) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    json.loads(payload)
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpp = tempfile.mkstemp(
        prefix=f"{path.name}.tmp.", dir=str(path.parent), text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as wf:
            wf.write(payload)
        tmp_path = Path(tmpp)
        os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            Path(tmpp).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _entries_consistent_with_disk(
    entries: List[Dict[str, Any]], disk: Any
) -> tuple[bool, str]:
    if not isinstance(disk, list):
        return False, "disk_memory_not_a_list"
    if len(entries) != len(disk):
        return False, f"length_mismatch_pg_{len(entries)}_disk_{len(disk)}"
    if not entries:
        return True, "both_empty"
    if disk[0].get("timestamp") != entries[0].get("timestamp"):
        return False, "first_ts_mismatch"
    if disk[-1].get("timestamp") != entries[-1].get("timestamp"):
        return False, "last_ts_mismatch"
    return True, "ok"


async def rebuild_one(
    conn: asyncpg.Connection,
    vault_root: Path,
    hardware_id: str,
    meta: Dict[str, Any],
    limit: int,
    dry_run: bool,
    backup_ts: str,
    verify_only: bool = False,
    *,
    decrypt_conversation: bool = False,
) -> Dict[str, Any]:
    role = meta["role"]
    aliases: Set[str] = meta["aliases"]
    folder = ROLE_FOLDER[role]
    target = vault_root / folder / hardware_id / "memory.json"

    # Post PG canonicalization: username-only fetch matches merged history.
    fetch_aliases: Set[str] = (
        {(meta.get("username") or "").strip()}
        if verify_only
        else aliases
    )
    fetch_aliases.discard("")
    include_bytea = bool(decrypt_conversation)
    fernet = _make_fernet() if decrypt_conversation else None
    sql_ok = await prepare_decrypt_session(conn, decrypt_conversation)
    rows = await fetch_history_rows(conn, fetch_aliases, limit, include_bytea=include_bytea)
    entries: List[Dict[str, Any]] = []
    skipped_enc = 0
    for row in rows:
        utext, atext = await plaintext_row_fields(
            conn,
            row,
            decrypt=decrypt_conversation,
            fernet=fernet,
            sql_decrypt_ok=sql_ok,
        )
        ent = pg_row_to_entry(row, utext=utext, atext=atext)
        if ent is None:
            skipped_enc += 1
            continue
        entries.append(ent)

    backup_path: Optional[str] = None
    if target.exists() and not dry_run and not verify_only:
        backup_path = str(target.parent / f"memory.json.pre_rebuild_{backup_ts}")
        shutil.copy2(target, backup_path)

    out: Dict[str, Any] = {
        "user_id_aliases": sorted(aliases),
        "hardware_id": hardware_id,
        "target_path": str(target),
        "pg_row_count": len(rows),
        "written_entry_count": len(entries),
        "skipped_encrypted_empty": skipped_enc,
        "decrypt_conversation": decrypt_conversation,
        "written": False,
        "backup_path": backup_path,
    }

    if verify_only:
        disk_raw: Any = None
        if target.exists():
            try:
                disk_raw = json.loads(target.read_text(encoding="utf-8"))
            except Exception as e:
                out["verify_pass"] = False
                out["verify_reason"] = f"disk_read_error:{e}"
                log.warning(
                    "[verify-only] FAIL hw=%s reason=%s",
                    hardware_id,
                    out["verify_reason"],
                )
                return out
        else:
            out["verify_pass"] = False
            out["verify_reason"] = "missing_memory_json"
            log.warning("[verify-only] FAIL hw=%s missing %s", hardware_id, target)
            return out
        ok, reason = _entries_consistent_with_disk(entries, disk_raw)
        out["verify_pass"] = ok
        out["verify_reason"] = reason
        out["fetch_aliases_verify"] = sorted(fetch_aliases)
        log.info(
            "[verify-only] hw=%s pass=%s reason=%s pg_entries=%s disk_entries=%s",
            hardware_id,
            ok,
            reason,
            len(entries),
            len(disk_raw) if isinstance(disk_raw, list) else "n/a",
        )
        return out

    if dry_run:
        log.info(
            "[dry-run] hw=%s path=%s pg_rows=%s entries=%s skipped_enc=%s backup=%s",
            hardware_id,
            target,
            len(rows),
            len(entries),
            skipped_enc,
            backup_path,
        )
        return out

    atomic_write_json(target, entries, dry_run=False)
    out["written"] = True
    log.info(
        "hw=%s path=%s pg_rows=%s entries=%s backup=%s",
        hardware_id,
        target,
        len(rows),
        len(entries),
        backup_path,
    )
    return out


async def async_main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--vault-root",
        default=os.environ.get("VAULT_ROOT", "/app/data/Vaults"),
        help="Vault root (bridge: /app/data/Vaults; host: .../data/bridge/Vaults)",
    )
    ap.add_argument(
        "--cutoff",
        default="2026-04-14T00:00:00+00:00",
        help="ISO cutoff — distinct user_ids with rows AFTER this are rebuild candidates",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Keep most recent N chronological turns per user (after merge by aliases)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="Compare memory.json on disk to PG rows fetched by username only (no writes)",
    )
    ap.add_argument(
        "--hardware-id",
        default="",
        help="Rebuild only this vault folder hardware_id (skips --cutoff target discovery)",
    )
    ap.add_argument(
        "--decrypt-conversation",
        action="store_true",
        help="Decrypt Fernet TEXT (SKYEYE_TOKEN_ENCRYPTION_KEY) + BYTEA decrypt_pii (PII_ENCRYPTION_KEY chain)",
    )
    args = ap.parse_args()
    if args.verify_only and args.dry_run:
        log.error("--verify-only and --dry-run are mutually exclusive")
        return 2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL is required")
        return 2

    cutoff = datetime.fromisoformat(args.cutoff.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)

    vault_root = Path(args.vault_root)
    backup_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    conn = await asyncpg.connect(dsn)
    try:
        if args.hardware_id.strip():
            meta = await resolve_single_hardware(conn, args.hardware_id.strip())
            if meta is None:
                return 2
            targets = {args.hardware_id.strip(): meta}
            log.info("Single-target rebuild hardware_id=%s", args.hardware_id.strip())
        else:
            targets = await resolve_targets(conn, cutoff)
        log.info("Rebuild targets (distinct hardware_id): %s", len(targets))
        results: List[Dict[str, Any]] = []
        for hw in sorted(targets.keys()):
            meta = targets[hw]
            r = await rebuild_one(
                conn,
                vault_root,
                hw,
                meta,
                args.limit,
                args.dry_run,
                backup_ts,
                verify_only=args.verify_only,
                decrypt_conversation=args.decrypt_conversation,
            )
            results.append(r)
        print(json.dumps(results, indent=2))
        if args.verify_only:
            bad = [x for x in results if not x.get("verify_pass")]
            return 0 if not bad else 3
        return 0
    finally:
        await conn.close()


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
