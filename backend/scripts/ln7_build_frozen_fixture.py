#!/usr/bin/env python3
"""Build Attempt 5 fixture frozen set (synthetic completions) for Phase B CI.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.services.ln7_decoupled_bakeoff import (  # noqa: E402
    ANCHOR_ARM,
    FrozenCompletion,
    build_anchor_rows,
    prompt_hash_for,
    write_frozen_jsonl,
)
from app.services.ln_sandbox_engineering_ci import materialize_pack  # noqa: E402

PACKS = ["asyncpg_cast", "catch_all_routes", "env_redis_prefix"]
BURST = "fixture_burst_attempt5"
ARM_A = "LN7-fixture-arm-A"
ARM_B = "LN7-fixture-arm-B"
OUT = REPO / "backend" / "tests" / "fixtures" / "ln7_frozen_bakeoff" / "fixture_burst.jsonl"


def _golden(pack: str) -> str:
    workdir, _m, err = materialize_pack(pack)
    if not workdir:
        raise SystemExit(f"materialize {pack}: {err}")
    return (workdir / "golden.patch").read_text(encoding="utf-8")


def _broken(pack: str) -> str:
    """Intentionally wrong diff — apply may fail or tests fail → score 0."""
    return (
        f"--- a/broken/__missing_{pack}.py\n"
        f"+++ b/broken/__missing_{pack}.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+# wrong file — should not pass pack tests\n"
        "+assert False\n"
    )


def main() -> None:
    rows = []
    rows.extend(build_anchor_rows(BURST, PACKS))
    for pack in PACKS:
        # Arm A: correct golden (high score)
        rows.append(
            FrozenCompletion(
                burst_id=BURST,
                prompt_hash=prompt_hash_for(pack),
                pack_id=pack,
                task_id="",
                arm_revision_id=ARM_A,
                adapter_sha="fixture-a",
                raw_text=_golden(pack),
                gen_latency_ms=12,
            )
        )
        # Arm B: broken (low score) — still non-empty raw_text
        rows.append(
            FrozenCompletion(
                burst_id=BURST,
                prompt_hash=prompt_hash_for(pack),
                pack_id=pack,
                task_id="",
                arm_revision_id=ARM_B,
                adapter_sha="fixture-b",
                raw_text=_broken(pack),
                gen_latency_ms=11,
            )
        )
    write_frozen_jsonl(OUT, rows)
    print(f"wrote {len(rows)} rows → {OUT}")
    print(f"anchors={[r.pack_id for r in rows if r.arm_revision_id == ANCHOR_ARM]}")


if __name__ == "__main__":
    main()
