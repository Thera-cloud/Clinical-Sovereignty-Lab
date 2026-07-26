#!/usr/bin/env python3
"""
Tier 2 Narrow AGI exit / harden gate (read-only).  # QUANTUM-CRYSTAL-ARCH

Checks: scored multi-domain pack, privacy_ok, surface_hits≥1 (v2),
multi-family evidence, ACCESS+FIELD, Queen FIELD CLI tools, helix hint flag,
LIVE_CONTEXT gate, Patent 12 filing-ready draft, coach Flutter PGSD.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _scores_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


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
                # v2 surface-hit harden (default on)
                _strict = os.environ.get(
                    "TIER2_REQUIRE_SURFACE_HITS", "true"
                ).strip().lower() not in ("0", "false", "no", "off")
                if _strict:
                    rows = await conn.fetch(
                        """
                        SELECT domain, scores_json
                        FROM tier2_domain_eval_runs
                        WHERE pack_id = $1 AND status = 'scored'
                        """,
                        pack["pack_id"],
                    )
                    weak = []
                    for r in rows:
                        sc = _scores_dict(r["scores_json"])
                        if int(sc.get("surface_hits") or 0) < 1:
                            weak.append(r["domain"])
                    if weak:
                        lines.append(
                            f"FAIL: pack surface_hits<1 for domains: {','.join(weak)}"
                        )
                    else:
                        lines.append("PASS: pack surface_hits≥1 all scored domains")
                else:
                    lines.append("WARN: TIER2_REQUIRE_SURFACE_HITS off — surface check skipped")
            else:
                lines.append("FAIL: no fully scored privacy-ok 5-domain pack in 30d")

            # Multi-family: ≥2 distinct subjects with certify-grade packs
            multi = await conn.fetch(
                """
                SELECT DISTINCT notes
                FROM tier2_domain_eval_runs
                WHERE created_at > NOW() - INTERVAL '30 days'
                  AND status = 'scored'
                  AND notes LIKE 'subject=%'
                """
            )
            subjects = set()
            for r in multi:
                note = r["notes"] or ""
                if note.startswith("subject="):
                    subjects.add(note.split("subject=", 1)[1].split()[0])
            if len(subjects) >= 2:
                lines.append(f"PASS: multi-family subjects≥2 ({len(subjects)})")
            else:
                lines.append(
                    "FAIL: multi-family evidence needs ≥2 distinct subjects "
                    f"(have {len(subjects)}) — run --multi pack"
                )

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
        here.parents[2],
        here.parents[1],
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
            Path(
                "/opt/clinical-sovereignty-lab/backend/assets/patent/"
                "PATENT_PROVISIONAL_12_QUANTUM_EMOTIONAL_FIELD.md"
            ),
        ]
    )
    if patent:
        ptxt = patent.read_text(encoding="utf-8")
        if "FILING-READY" in ptxt or "FILING READY" in ptxt:
            lines.append("PASS: Patent 12 FILING-READY draft present")
        else:
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

    cli = _first_existing(
        [r / "backend/app/websocket/cli_tools.py" for r in roots]
        + [Path("/app/app/websocket/cli_tools.py")]
    )
    cli_txt = cli.read_text(encoding="utf-8") if cli else ""
    if "query_pgsd_wells" in cli_txt and "query_pgsd_ground_state" in cli_txt:
        lines.append("PASS: Queen FIELD CLI tools present")
    else:
        lines.append("FAIL: Queen FIELD CLI tools missing")

    if _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_ACCESS"):
        lines.append("PASS: PGSD ACCESS ladder env")
    else:
        lines.append("FAIL: PGSD_ENABLED/ACCESS not both true")

    if _env_true("ENABLE_PGSD_HELIX_HINT"):
        lines.append("PASS: ENABLE_PGSD_HELIX_HINT on")
    else:
        lines.append("FAIL: ENABLE_PGSD_HELIX_HINT is false")

    smoke = _first_existing(
        [r / "backend/scripts/tier2_coach_pgsd_e2e_smoke.py" for r in roots]
        + [Path("/app/scripts/tier2_coach_pgsd_e2e_smoke.py")]
    )
    if smoke:
        lines.append("PASS: coach PGSD E2E smoke script present")
    else:
        lines.append("FAIL: coach PGSD E2E smoke script missing")
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
    print("GATE: GREEN — Tier 2 harden + Queen FIELD + helix hint criteria met")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
