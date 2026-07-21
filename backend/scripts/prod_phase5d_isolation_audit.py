#!/usr/bin/env python3
"""QUANTUM-CRYSTAL-ARCH: Phase 5d read-only crystal graph isolation audit.

Safe with ENABLE_CRYSTAL_GRAPH=false. Samples seed content_hashes and reports
scope-isolation violations for requester (default client1).

Usage on GREEN host:
  python3 /opt/clinical-sovereignty-lab/backend/scripts/prod_phase5d_isolation_audit.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

DB = os.getenv("PROD_TEST_DB", "little_nate")
REQUESTER = os.getenv("PROD_TEST_USER", "client1")
MAX_SEEDS = int(os.getenv("PROD_5D_SEEDS", "25"))
MAX_HOPS = int(os.getenv("PROD_5D_HOPS", "2"))


def _psql(sql: str) -> str:
    return subprocess.check_output(
        [
            "docker",
            "exec",
            "nate_postgres",
            "psql",
            "-U",
            "nate_admin",
            "-d",
            DB,
            "-tAc",
            sql,
        ],
        text=True,
    ).strip()


def main() -> int:
    flag = subprocess.check_output(
        ["docker", "exec", "nate_bridge", "printenv", "ENABLE_CRYSTAL_GRAPH"],
        text=True,
    ).strip()
    print(f"[*] bridge ENABLE_CRYSTAL_GRAPH={flag!r}")
    if flag.lower() == "true":
        print("WARN: graph already enabled — audit remains SELECT-only")

    u_esc = REQUESTER.replace("'", "''")
    uid = _psql(f"SELECT id::text FROM users WHERE username = '{u_esc}' LIMIT 1;")
    if not uid:
        print(f"FAIL: no users.id for {REQUESTER}")
        return 1
    print(f"[*] requester {REQUESTER} -> {uid}")

    seeds_raw = _psql(
        "SELECT content_hash FROM nate_intelligence_crystals "
        "WHERE scope IS DISTINCT FROM 'archived' "
        "AND content_hash IS NOT NULL AND content_hash != '' "
        f"ORDER BY created_at DESC NULLS LAST LIMIT {MAX_SEEDS};"
    )
    seeds = [s.strip() for s in seeds_raw.splitlines() if s.strip()]
    print(f"[*] seeds={len(seeds)}")
    print(f"[*] crystal_edges count={_psql('SELECT count(*)::text FROM crystal_edges;')}")

    runner = f"""
import asyncio, json, os
os.environ["ENABLE_CRYSTAL_GRAPH"] = "false"
import asyncpg
from app.services.crystal_graph_isolation import (
    audit_graph_traversal_isolation,
    crystal_graph_enabled,
)

SEEDS = {json.dumps(seeds)}
REQ = {json.dumps(uid)}
HOPS = {MAX_HOPS}

async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    report = await audit_graph_traversal_isolation(
        pool,
        seed_crystal_ids=SEEDS,
        requester_user_id=REQ,
        max_hops=HOPS,
    )
    report["flag_enabled"] = crystal_graph_enabled()
    await pool.close()
    print(json.dumps(report, default=str))

asyncio.run(main())
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(runner)
        path = tf.name

    try:
        subprocess.check_call(
            ["docker", "cp", path, "nate_backend:/tmp/phase5d_isolation_runner.py"]
        )
        out = subprocess.check_output(
            [
                "docker",
                "exec",
                "-e",
                "ENABLE_CRYSTAL_GRAPH=false",
                "-e",
                "PYTHONPATH=/app",
                "nate_backend",
                "python",
                "/tmp/phase5d_isolation_runner.py",
            ],
            text=True,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    print(out)
    try:
        report = json.loads(out.strip().splitlines()[-1])
    except Exception as e:
        print(f"FAIL: parse report: {e}")
        return 1

    n_viol = len(report.get("violations") or [])
    print(
        f"[=] visited={report.get('visited')} violations={n_viol} "
        f"flag_enabled={report.get('flag_enabled')}"
    )
    allow_on = os.getenv("PROD_5D_ALLOW_FLAG_ON", "").lower() in ("1", "true", "yes")
    if report.get("flag_enabled") and not allow_on:
        print("FAIL: flag_enabled must be false during 5d.1 audit")
        return 1
    if report.get("flag_enabled") and allow_on:
        print("OK: flag on allowed (post-flip soak); audit remains SELECT-only")
    if report.get("error"):
        print(f"FAIL: {report['error']}")
        return 1

    summary = "/tmp/phase5d_isolation_report.json"
    with open(summary, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[*] wrote {summary}")
    print("OK: read-only isolation audit complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
