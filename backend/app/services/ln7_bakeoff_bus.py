"""Queens task-bus handler for decoupled LN7 bakeoff (Attempt 6 proven flow).

Dry path (LN7_BAKEOFF_DRY=1): Phase B against Attempt 6 gold fixture, $0.
Live path: Phase A generate_freeze scripts then Phase B (requires ALLOW_PAID + PRE6).
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_bakeoff_bus")

REPO = Path(__file__).resolve().parents[3]
GOLD = REPO / "backend" / "tests" / "fixtures" / "attempt6_gold_standard.jsonl"


def _dry() -> bool:
    return os.getenv("LN7_BAKEOFF_DRY", "0").strip() in ("1", "true", "yes", "on")


def _allow_paid() -> bool:
    return os.getenv("LN7_BURST_ALLOW_PAID", "0").strip() == "1"


async def handle_ln7_bakeoff(
    pool,
    *,
    payload: Optional[Dict[str, Any]] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """Bus entrypoint — dry fixture score or live Phase A→B."""
    meta: Dict[str, Any] = dict(payload or {})
    if notes and notes.strip().startswith("{"):
        try:
            meta.update(json.loads(notes))
        except Exception:
            pass

    label = str(meta.get("attempt_label") or meta.get("label") or "AttemptBus")
    arm_a = str(meta.get("arm_a_rev") or "")
    arm_b = str(meta.get("arm_b_rev") or "")
    smoke_gate = bool(meta.get("human_smoke_gate", True))

    if _dry():
        return await _run_dry(label=label, smoke_gate=smoke_gate)

    if not _allow_paid():
        return {
            "ok": False,
            "error": "paid_gate_closed",
            "detail": "LN7_BURST_ALLOW_PAID must be 1 (and PRE6 ≥300 organic)",
        }

    # Live: shell Phase A then Phase B (blocking in thread)
    return await asyncio.to_thread(
        _run_live_shell,
        arm_a,
        arm_b,
        label,
        smoke_gate,
    )


async def _run_dry(*, label: str, smoke_gate: bool) -> Dict[str, Any]:
    from app.services.ln7_decoupled_bakeoff import load_frozen_set, run_phase_b, smoke_score

    if not GOLD.is_file():
        return {"ok": False, "error": "gold_fixture_missing", "path": str(GOLD)}
    rows = load_frozen_set(GOLD)
    if smoke_gate:
        smoke = smoke_score(rows, n=min(3, sum(1 for r in rows if not r.is_anchor)))
        # Human gate: surface 3 rows then continue in dry (no email wait in CI)
        preview = [
            {
                "pack_id": r.get("pack_id"),
                "arm": r.get("arm_revision_id"),
                "score": r.get("score"),
                "passed": r.get("passed"),
            }
            for r in smoke.get("results") or []
        ]
    else:
        preview = []
    out = run_phase_b(rows)
    v = out.get("verdict") or {}
    summary = {
        "mode": "dry",
        "label": label,
        "winner": v.get("winner"),
        "mean_a": v.get("mean_a"),
        "mean_b": v.get("mean_b"),
        "anchor_score": v.get("anchor_score"),
        "smoke_preview": preview,
        "bakeoff_verdict": bool(v.get("bakeoff_verdict")),
    }
    try:
        from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

        enqueue_ceo(
            risk=RISK_YELLOW,
            title=f"LN7 bakeoff dry verdict: {v.get('winner')}",
            detail=json.dumps(summary)[:800],
            origin="ln7_bakeoff_bus",
            dedup_ttl_s=3600,
        )
    except Exception:
        pass
    return {"ok": bool(out.get("ok")), **summary}


def _run_live_shell(
    arm_a: str, arm_b: str, label: str, smoke_gate: bool
) -> Dict[str, Any]:
    env = {**os.environ, "LN7_BURST_ID": label, "PYTHONPATH": str(REPO / "backend")}
    phase_a = REPO / "scripts" / "ln7_bakeoff_phase_a_generate.sh"
    if not phase_a.is_file():
        return {"ok": False, "error": "phase_a_script_missing"}
    cmd = ["bash", str(phase_a)]
    if arm_a and arm_b:
        cmd.extend([arm_a, arm_b])
    try:
        subprocess.check_call(cmd, cwd=str(REPO), env=env, timeout=7200)
    except Exception as e:
        return {"ok": False, "error": f"phase_a_failed:{e}"[:240]}

    frozen = Path.home() / ".local" / "state" / "ln7_gpu_watch" / f"frozen_{label}.jsonl"
    if not frozen.is_file():
        # Attempt6 naming convention fallback
        frozen = Path.home() / ".local" / "state" / "ln7_gpu_watch" / f"frozen_{label}.jsonl"
    phase_b = REPO / "scripts" / "ln7_bakeoff_phase_b_score.sh"
    try:
        out = subprocess.check_output(
            ["bash", str(phase_b), str(frozen)],
            cwd=str(REPO),
            env=env,
            timeout=1800,
            text=True,
        )
    except Exception as e:
        return {"ok": False, "error": f"phase_b_failed:{e}"[:240]}
    return {
        "ok": "PHASE_B_SCORE=PASS" in out,
        "mode": "live",
        "label": label,
        "frozen": str(frozen),
        "human_smoke_gate": smoke_gate,
        "stdout_tail": out[-800:],
    }
