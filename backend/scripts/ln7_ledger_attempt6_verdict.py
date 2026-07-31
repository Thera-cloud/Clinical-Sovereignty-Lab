#!/usr/bin/env python3
"""Attempt 6 post-bakeoff — R2 mirror + Postgres ledger with read-back.

Usage (from repo root, with .env R2 + DATABASE_URL or LN7_DATABASE_URL):

  PYTHONPATH=backend python3 backend/scripts/ln7_ledger_attempt6_verdict.py \\
    --frozen ~/.local/state/ln7_gpu_watch/frozen_Attempt6.jsonl \\
    --scorer-sha <git_sha>

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env = REPO / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


async def _main() -> int:
    _load_dotenv()
    sys.path.insert(0, str(REPO / "backend"))

    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", required=True, type=Path)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--scorer-sha", required=True)
    ap.add_argument("--burst-id", default="Attempt6")
    ap.add_argument(
        "--database-url",
        default=os.getenv("LN7_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    args = ap.parse_args()

    from app.services.ln7_decoupled_bakeoff import (
        load_frozen_set,
        persist_frozen_rows,
        persist_verdict,
        run_phase_b,
    )
    from app.services.r2_storage import is_r2_configured, upload_bytes

    frozen_path: Path = args.frozen.expanduser().resolve()
    if not frozen_path.is_file():
        print(f"FATAL missing frozen set: {frozen_path}", file=sys.stderr)
        return 2
    manifest_path = (
        args.manifest.expanduser().resolve()
        if args.manifest
        else frozen_path.with_suffix(".manifest.json")
    )

    if not is_r2_configured():
        print("FATAL R2 not configured", file=sys.stderr)
        return 3
    bucket = os.getenv("R2_COLD_BUCKET", "nate-cold-archive").strip() or "nate-cold-archive"
    key_jsonl = f"ln7/bakeoff/{args.burst_id}/frozen_{args.burst_id}.jsonl"
    key_manifest = f"ln7/bakeoff/{args.burst_id}/frozen_{args.burst_id}.manifest.json"

    kind, loc = upload_bytes(
        key=key_jsonl,
        content=frozen_path.read_bytes(),
        bucket=bucket,
        content_type="application/x-ndjson",
        metadata={"burst_id": args.burst_id, "artifact": "frozen_completions"},
    )
    frozen_uri = loc if str(loc).startswith("http") else f"r2://{bucket}/{key_jsonl}"
    print(f"R2_OK kind={kind} uri={frozen_uri}")

    if manifest_path.is_file():
        upload_bytes(
            key=key_manifest,
            content=manifest_path.read_bytes(),
            bucket=bucket,
            content_type="application/json",
            metadata={"burst_id": args.burst_id, "artifact": "manifest"},
        )
        print(f"R2_OK manifest=r2://{bucket}/{key_manifest}")

    rows = load_frozen_set(frozen_path)
    phase = run_phase_b(rows)
    if not phase.get("ok"):
        print("FATAL phase_b failed", file=sys.stderr)
        return 4
    verdict = dict(phase["verdict"])
    verdict["winner_adapter_id"] = verdict.get("winner")
    verdict["frozen_set_uri"] = frozen_uri
    verdict["scorer_sha"] = args.scorer_sha
    verdict["arm_a_rev"] = verdict.get("rev_a")
    verdict["arm_b_rev"] = verdict.get("rev_b")
    verdict["metrics"] = {
        "arm_a_mean": round(float(verdict.get("mean_a") or 0), 6),
        "arm_b_mean": round(float(verdict.get("mean_b") or 0), 6),
        "lo_a": verdict.get("lo_a"),
        "hi_a": verdict.get("hi_a"),
        "lo_b": verdict.get("lo_b"),
        "hi_b": verdict.get("hi_b"),
        "n_a": verdict.get("n_a"),
        "n_b": verdict.get("n_b"),
        "anchor_score": verdict.get("anchor_score"),
    }
    verdict["r2_bucket"] = bucket
    verdict["r2_key"] = key_jsonl

    db_url = (args.database_url or "").strip()
    if not db_url:
        print("FATAL no DATABASE_URL / LN7_DATABASE_URL", file=sys.stderr)
        return 5

    import asyncpg

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2, command_timeout=60)
    try:
        n = await persist_frozen_rows(pool, rows)
        ok = await persist_verdict(pool, verdict)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT burst_id, winner, mean_a, mean_b, rev_a, rev_b,
                       smoke_ok, payload_json
                FROM ln7_bakeoff_verdicts WHERE burst_id = $1
                """,
                args.burst_id,
            )
            frozen_n = await conn.fetchval(
                "SELECT COUNT(*) FROM ln7_bakeoff_frozen_completions WHERE burst_id = $1",
                args.burst_id,
            )
    finally:
        await pool.close()

    if not ok or row is None:
        print("FATAL ledger write/read-back failed", file=sys.stderr)
        return 6
    payload = row["payload_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    uri_rb = (payload or {}).get("frozen_set_uri")
    sha_rb = (payload or {}).get("scorer_sha")
    assert row["burst_id"] == args.burst_id
    assert row["winner"] == verdict["winner"]
    assert uri_rb == frozen_uri, f"uri mismatch {uri_rb!r} != {frozen_uri!r}"
    assert sha_rb == args.scorer_sha, f"scorer_sha mismatch"
    assert int(frozen_n or 0) >= 1

    out = {
        "ok": True,
        "read_back": True,
        "burst_id": row["burst_id"],
        "winner": row["winner"],
        "mean_a": float(row["mean_a"]),
        "mean_b": float(row["mean_b"]),
        "rev_a": row["rev_a"],
        "rev_b": row["rev_b"],
        "frozen_set_uri": uri_rb,
        "scorer_sha": sha_rb,
        "frozen_rows_persisted": n,
        "frozen_rows_db": int(frozen_n),
        "smoke_ok": bool(row["smoke_ok"]),
    }
    print(json.dumps(out, indent=2))
    print("LEDGER_READBACK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
