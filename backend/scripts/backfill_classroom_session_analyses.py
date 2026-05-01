#!/usr/bin/env python3
"""One-shot backfill: vault session_memories + classroom_sessions.json → PG."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def _upsert_one(pool, row: Dict[str, Any], dry_run: bool) -> bool:
    from app.services.pg_data_helpers import upsert_classroom_analysis_pg

    if dry_run:
        print(f"[dry-run] would upsert session_id={row.get('session_id')}")
        return True
    return await upsert_classroom_analysis_pg(pool, row)


def _merge_memory_index(analysis: Dict[str, Any], idx: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(analysis)
    for k in ("session_id", "coach_id", "client_id", "client_name", "family_id"):
        if idx.get(k) and not out.get(k):
            out[k] = idx[k]
    return out


async def main_async(args: argparse.Namespace) -> None:
    import asyncpg

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL or --database-url required")
        sys.exit(1)

    vault_root = Path(args.vault_root).expanduser().resolve()
    cs_path = Path(args.classroom_sessions_file).expanduser().resolve()

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    total_ok = 0
    total_skip = 0

    if cs_path.exists():
        try:
            sessions = json.loads(cs_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] classroom_sessions.json unreadable: {e}")
            sessions = []
        if isinstance(sessions, list):
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                sid = s.get("session_id") or s.get("id")
                if not sid:
                    total_skip += 1
                    continue
                nested = s.get("analysis")
                if isinstance(nested, dict):
                    row = dict(nested)
                    for k, v in s.items():
                        if k != "analysis" and v is not None:
                            row.setdefault(k, v)
                else:
                    row = dict(s)
                row["session_id"] = sid
                if await _upsert_one(pool, row, args.dry_run):
                    total_ok += 1
                else:
                    total_skip += 1

    mem_root = vault_root / "session_memories"
    if mem_root.is_dir():
        for child in sorted(mem_root.iterdir()):
            if not child.is_dir() or child.name == "clients":
                continue
            ap = child / "analysis.json"
            if not ap.exists():
                continue
            try:
                analysis = json.loads(ap.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[WARN] skip {child.name}: {e}")
                total_skip += 1
                continue
            if not isinstance(analysis, dict):
                total_skip += 1
                continue
            idx_path = child / "memory_index.json"
            if idx_path.exists():
                try:
                    idx = json.loads(idx_path.read_text(encoding="utf-8"))
                    if isinstance(idx, dict):
                        analysis = _merge_memory_index(analysis, idx)
                except Exception:
                    pass
            analysis.setdefault("session_id", child.name)
            if await _upsert_one(pool, analysis, args.dry_run):
                total_ok += 1
            else:
                total_skip += 1

    await pool.close()
    print(f"Done: upserted_ok={total_ok} skipped_or_failed={total_skip}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Backfill classroom_session_analyses from vault + classroom_sessions.json."
    )
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    p.add_argument(
        "--vault-root",
        default=os.getenv("VAULT_ROOT", ""),
        help="Parent of session_memories/ (Night School vault root)",
    )
    p.add_argument(
        "--classroom-sessions-file",
        default=os.getenv(
            "CLASSROOM_SESSIONS_FILE",
            str(Path(os.getenv("DATA_DIR", "./data")) / "classroom_sessions.json"),
        ),
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not args.vault_root:
        print("--vault-root or VAULT_ROOT required for vault scan")
        sys.exit(1)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
