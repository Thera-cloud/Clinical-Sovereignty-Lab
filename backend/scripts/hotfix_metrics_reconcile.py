"""
Hot fix: reconcile vault metrics.json files with latest nevedal_metrics PG rows.

Cause: bridge restart at 2026-05-12 02:56:22 UTC re-initialized all 26 client
metrics.json files to defaults (C_emo=0.5, GAP=0.3, Quantum=0.5) because the
backend vault fallback was empty.

Strategy: for each user with rows in nevedal_metrics, take the latest c_emo +
t_tunnel and patch the vault file. GAP/Quantum are recomputed from the same
formulas the bridge uses (lines 4681 / 4693 of bridge_server.py) using neutral
defaults for the non-PG inputs (E_warmth=0.3, engagement=0.5, anxiety=0.0).

Users with zero PG rows are left untouched (they have no live data to restore).

Run inside nate_bridge container:
    docker cp hotfix_metrics_reconcile.py nate_bridge:/tmp/
    docker exec nate_bridge python3 /tmp/hotfix_metrics_reconcile.py
"""
import asyncio
import datetime
import json
import os
from pathlib import Path

import asyncpg

VAULT_ROOT = Path("/app/data/Vaults/Clients")
PG_HOST = os.environ.get("POSTGRES_HOST", "postgres")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
PG_USER = os.environ.get("POSTGRES_USER", "nate_admin")
PG_PASS = os.environ.get("POSTGRES_PASSWORD", "")
PG_DB = os.environ.get("POSTGRES_DB", "little_nate")


def compute_gap(c_emo: float, e_warmth: float = 0.3, engagement: float = 0.5) -> float:
    return round(c_emo * 0.4 + e_warmth * 0.3 + engagement * 0.3, 3)


def compute_quantum(c_emo: float, gap: float, engagement: float = 0.5, anxiety: float = 0.0) -> float:
    return round(0.3 * c_emo + 0.25 * gap + 0.25 * engagement + 0.2 * (1 - anxiety), 3)


async def main() -> None:
    pool = await asyncpg.create_pool(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database=PG_DB,
        min_size=1, max_size=2,
    )
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.username, u.hardware_id, u.role,
                       m.c_emo, m.t_tunnel, m.p_ent, m.gamma_env, m.recorded_at
                FROM (
                    SELECT DISTINCT ON (user_id) user_id, c_emo, t_tunnel, p_ent, gamma_env, recorded_at
                    FROM nevedal_metrics
                    WHERE recorded_at > NOW() - INTERVAL '30 days'
                    ORDER BY user_id, recorded_at DESC
                ) m
                JOIN users u ON u.id = m.user_id
                WHERE u.role IN ('CLIENT', 'COACH', 'ADMIN')
                """
            )
    finally:
        await pool.close()

    print(f">>> [HOTFIX] Found {len(rows)} users with recent PG metrics")

    patched = 0
    skipped_missing_file = 0
    skipped_error = 0
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for r in rows:
        hw_id = r["hardware_id"]
        username = r["username"]
        role = r["role"]
        c_emo = float(r["c_emo"])
        t_tunnel = float(r["t_tunnel"]) if r["t_tunnel"] is not None else 0.2
        recorded_at = r["recorded_at"].isoformat() if r["recorded_at"] else now_iso

        folder = "Clients" if role == "CLIENT" else ("Coaches" if role == "COACH" else "Admin")
        path = Path(f"/app/data/Vaults/{folder}") / hw_id / "metrics.json"

        if not path.exists():
            print(f"    SKIP missing-file {username} ({hw_id}) -> {path}")
            skipped_missing_file += 1
            continue

        try:
            with open(path, "r") as f:
                data = json.load(f)
            ns = data.get("nevedal_state") or {}

            # Pull existing engagement / anxiety / warmth so we don't blow away
            # any locally derived values (most are at defaults but be safe).
            e_warmth = float(ns.get("E_warmth", 0.3) or 0.3)
            engagement = float(ns.get("engagement", 0.5) or 0.5)
            anxiety = float(ns.get("anxiety_level", 0.0) or 0.0)

            gap = compute_gap(c_emo, e_warmth, engagement)
            quantum = compute_quantum(c_emo, gap, engagement, anxiety)

            ns["C_emo"] = round(c_emo, 3)
            ns["T_tunnel"] = round(t_tunnel, 3)
            ns["GAP"] = gap
            ns["Quantum"] = quantum
            ns["last_pg_recorded_at"] = recorded_at
            ns["hotfix_applied_at"] = now_iso

            data["nevedal_state"] = ns
            data["last_updated"] = now_iso

            with open(path, "w") as f:
                json.dump(data, f, indent=2)

            print(f"    OK   {username} ({hw_id}) C_emo={c_emo:.3f} GAP={gap} Quantum={quantum}")
            patched += 1
        except Exception as e:
            print(f"    ERR  {username} ({hw_id}): {e}")
            skipped_error += 1

    print(
        f">>> [HOTFIX] Done: patched={patched} "
        f"missing={skipped_missing_file} errors={skipped_error}"
    )


if __name__ == "__main__":
    asyncio.run(main())
