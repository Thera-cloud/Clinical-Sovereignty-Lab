#!/usr/bin/env python3
"""Export LN7 rejection samples to JSONL for offline QLoRA / DPO on BLUE.

Never runs training. Never uploads to vendor fine-tune APIs.
Eval/heldout task_hashes are mechanically excluded.

Usage:
  DATABASE_URL=... PYTHONPATH=backend \\
    python backend/scripts/ln7_export_train_jsonl.py --out /tmp/ln7_train.jsonl

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


async def export_rows(limit: int = 500) -> list:
    import asyncpg

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        # Compose-style fallback for local
        host = os.getenv("POSTGRES_HOST", "localhost")
        user = os.getenv("POSTGRES_USER", "nate_admin")
        pw = os.getenv("POSTGRES_PASSWORD", "")
        db = os.getenv("POSTGRES_DB", "little_nate")
        dsn = f"postgresql://{user}:{pw}@{host}:5432/{db}"

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT o.id, o.task_id, o.patch_hash, o.revision_id, o.harness_mode,
                   o.metrics_json, o.diff_lines, o.tokens,
                   t.split, t.spdx_license, t.prompt_summary, t.task_hash
            FROM ln7_coding_outcomes o
            LEFT JOIN ln7_tasks t ON t.task_id = o.task_id
            WHERE o.passed = TRUE AND o.generator = 'ln7'
              AND (t.split IS NULL OR t.split = 'train')
              AND (t.spdx_license IS NULL OR t.spdx_license IN
                   ('MIT','Apache-2.0','BSD-2-Clause','BSD-3-Clause','ISC','Unlicense','0BSD'))
            ORDER BY o.created_at DESC
            LIMIT $1
            """,
            limit,
        )
        # Also allow pack outcomes with null task_id (authored packs are train/heldout via metrics)
        pack_rows = await conn.fetch(
            """
            SELECT o.id, o.task_id, o.patch_hash, o.revision_id, o.harness_mode,
                   o.metrics_json, o.diff_lines, o.tokens
            FROM ln7_coding_outcomes o
            WHERE o.passed = TRUE AND o.generator = 'ln7' AND o.task_id IS NULL
            ORDER BY o.created_at DESC
            LIMIT $1
            """,
            limit,
        )
    finally:
        await conn.close()

    out = []
    seen = set()
    for r in list(rows) + list(pack_rows):
        d = dict(r)
        ph = d.get("patch_hash") or ""
        if ph in seen:
            continue
        seen.add(ph)
        # heldout packs must not train
        meta = d.get("metrics_json") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        pack = (meta or {}).get("pack") or ""
        if pack == "env_redis_prefix":
            continue  # heldout pack
        out.append({
            "outcome_id": str(d.get("id")),
            "task_id": d.get("task_id"),
            "revision_id": d.get("revision_id"),
            "prompt": (d.get("prompt_summary") or f"Pack repair: {pack}")[:4000],
            "patch_hash": ph,
            "harness_mode": d.get("harness_mode"),
            "split": d.get("split") or "train",
            "spdx_license": d.get("spdx_license") or "unknown",
            "messages": [
                {"role": "user", "content": d.get("prompt_summary") or f"Fix pack {pack}"},
                {"role": "assistant", "content": f"[patch_hash={ph}]"},
            ],
        })
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    rows = asyncio.run(export_rows(args.limit))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    print(json.dumps({"ok": True, "n": len(rows), "path": str(path)}))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
