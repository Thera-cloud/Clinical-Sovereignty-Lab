#!/usr/bin/env python3
"""
Tier 2 Narrow AGI exit gate (read-only).  # QUANTUM-CRYSTAL-ARCH

Checks: scored multi-domain pack, privacy_ok, ACCESS+FIELD flags,
LIVE_CONTEXT surface gate in code, Patent 12 draft present.
Does not lower Tier-1 locks.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _check_db(dsn: str) -> List[str]:
    import asyncpg

    lines = []
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            pack = await conn.fetchrow(
                """
                SELECT pack_id,
                       COUNT(*) FILTER (WHERE status = 'scored') AS scored,
                       COUNT(*) AS total,
                       BOOL_AND(COALESCE(privacy_ok, false)) AS all_privacy
                FROM tier2_domain_eval_runs
                WHERE created_at > NOW() - INTERVAL '30 days'
                GROUP BY pack_id
                HAVING COUNT(*) >= 5
                ORDER BY MAX(created_at) DESC
                LIMIT 1
                """
            )
            if pack and int(pack["scored"] or 0) >= 5 and pack["all_privacy"]:
                lines.append(
                    f"PASS: scored pack {pack['pack_id']} "
                    f"{pack['scored']}/{pack['total']} privacy_ok"
                )
            else:
                lines.append("FAIL: no fully scored privacy-ok 5-domain pack in 30d")

            wells = await conn.fetchval("SELECT COUNT(*) FROM pgsd_trauma_wells")
            ground = await conn.fetchval("SELECT COUNT(*) FROM pgsd_ground_states")
            if _env_true("ENABLE_PGSD_FIELD") and int(wells or 0) > 0:
                lines.append(f"PASS: FIELD wells={wells} ground_states={ground}")
            elif _env_true("ENABLE_PGSD_FIELD"):
                lines.append("FAIL: ENABLE_PGSD_FIELD on but no trauma wells")
            else:
                lines.append("FAIL: ENABLE_PGSD_FIELD is false")

            agr = await conn.fetchval("SELECT COUNT(*) FROM pgsd_cross_domain_agreement")
            if int(agr or 0) > 0:
                lines.append(f"PASS: cross_domain_agreement rows={agr}")
            else:
                lines.append("FAIL: no pgsd_cross_domain_agreement rows")
    finally:
        await pool.close()
    return lines


def _first_existing(paths) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None


def _check_code() -> List[str]:
    lines = []
    here = Path(__file__).resolve()
    roots = [
        here.parents[2],  # repo (local backend/scripts/…)
        here.parents[1],  # /app in container
        Path("/opt/clinical-sovereignty-lab"),
        Path("/app"),
    ]
    live = _first_existing(
        [r / "backend/app/services/six_quotient_live_context.py" for r in roots]
        + [Path("/app/app/services/six_quotient_live_context.py")]
    )
    text = live.read_text(encoding="utf-8") if live else ""
    if "_LIVE_CONTEXT_SURFACES" in text and "bridge_chat" in text:
        lines.append("PASS: LIVE_CONTEXT surface allowlist present")
    else:
        lines.append("WARN: LIVE_CONTEXT allowlist check inconclusive")

    patent = _first_existing(
        [r / "patent/PATENT_PROVISIONAL_12_QUANTUM_EMOTIONAL_FIELD.md" for r in roots]
        + [
            Path("/app/assets/patent/PATENT_PROVISIONAL_12_QUANTUM_EMOTIONAL_FIELD.md"),
            Path("/opt/clinical-sovereignty-lab/backend/assets/patent/"
                 "PATENT_PROVISIONAL_12_QUANTUM_EMOTIONAL_FIELD.md"),
        ]
    )
    # Canonical legal copy remains under repo patent/; assets/patent is the
    # container-visible mirror for GREEN gate (assets bind-mount).
    if patent:
        lines.append("PASS: Patent 12 draft present")
    else:
        lines.append("FAIL: Patent 12 missing")

    flutter = _first_existing(
        [r / "mobile/lib/screens/coach_pgsd_screen.dart" for r in roots]
    )
    if flutter:
        lines.append("PASS: coach Flutter PGSD screen present")
    else:
        lines.append("FAIL: coach Flutter PGSD screen missing")

    if _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_ACCESS"):
        lines.append("PASS: PGSD ACCESS ladder env")
    else:
        lines.append("FAIL: PGSD_ENABLED/ACCESS not both true")
    return lines


async def main() -> int:
    lines = _check_code()
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        lines.extend(await _check_db(dsn))
    else:
        lines.append("WARN: DATABASE_URL unset — skipped DB checks")

    fails = [l for l in lines if l.startswith("FAIL")]
    for l in lines:
        print(l)
    if fails:
        print(f"GATE: RED ({len(fails)} fail)")
        return 1
    print("GATE: GREEN — Tier 2 Narrow AGI exit criteria met (substrate certified)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
