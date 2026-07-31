"""Attempt 5 — decoupled bakeoff: generate/freeze once, score offline forever.

Phase A (paid GPU): generate completions → freeze rows → destroy droplet.
Phase B (free): anchor gate → 5-row smoke → full score → bakeoff_verdict.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("ln7_decoupled_bakeoff")

ANCHOR_ARM = "__anchor_ground_truth__"
REQUIRED_FREEZE_KEYS = frozenset({
    "burst_id", "prompt_hash", "pack_id", "task_id",
    "arm_revision_id", "raw_text",
})


class BakeoffContractError(Exception):
    """Fail-fast seam contract violation (no silent null metrics)."""


@dataclass
class FrozenCompletion:
    burst_id: str
    prompt_hash: str
    pack_id: str
    task_id: str
    arm_revision_id: str
    adapter_sha: str = ""
    raw_text: Optional[str] = None
    gen_error: Optional[str] = None
    gen_latency_ms: Optional[int] = None
    is_anchor: bool = False

    def validate(self) -> None:
        missing = [k for k in ("burst_id", "prompt_hash", "pack_id", "arm_revision_id") if not getattr(self, k)]
        if missing:
            raise BakeoffContractError(f"frozen row missing keys: {missing}")
        text = (self.raw_text or "").strip()
        err = (self.gen_error or "").strip()
        if not text and not err:
            raise BakeoffContractError(
                f"silent_empty banned: pack={self.pack_id} arm={self.arm_revision_id}"
            )
        if self.is_anchor and not text:
            raise BakeoffContractError("anchor row must have raw_text")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def prompt_hash_for(pack_id: str, task_id: str = "") -> str:
    h = hashlib.sha256(f"{pack_id}\0{task_id}".encode("utf-8"))
    return h.hexdigest()[:32]


def load_frozen_set(path: Path) -> List[FrozenCompletion]:
    """Load JSONL or JSON array of frozen completions."""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise BakeoffContractError(f"empty frozen set: {path}")
    rows: List[Dict[str, Any]]
    if path.suffix == ".jsonl" or raw.startswith("{"):
        rows = []
        for i, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise BakeoffContractError(f"jsonl line {i}: {e}") from e
    else:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise BakeoffContractError("frozen JSON must be a list")
        rows = data
    out: List[FrozenCompletion] = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise BakeoffContractError(f"row {i} not object")
        fc = FrozenCompletion(
            burst_id=str(r.get("burst_id") or ""),
            prompt_hash=str(r.get("prompt_hash") or ""),
            pack_id=str(r.get("pack_id") or ""),
            task_id=str(r.get("task_id") or ""),
            arm_revision_id=str(r.get("arm_revision_id") or ""),
            adapter_sha=str(r.get("adapter_sha") or ""),
            raw_text=r.get("raw_text"),
            gen_error=r.get("gen_error"),
            gen_latency_ms=r.get("gen_latency_ms"),
            is_anchor=bool(r.get("is_anchor")),
        )
        fc.validate()
        out.append(fc)
    return out


def verify_frozen_completeness(
    rows: Sequence[FrozenCompletion],
    *,
    packs: Sequence[str],
    arms: Sequence[str],
    tasks_per_pack: int = 1,
) -> None:
    """row count == packs × tasks × arms (+ anchors optional extra)."""
    expected = len(packs) * tasks_per_pack * len(arms)
    real = [r for r in rows if not r.is_anchor]
    if len(real) != expected:
        raise BakeoffContractError(
            f"frozen completeness: got {len(real)} real rows, want {expected} "
            f"(packs={len(packs)} tasks={tasks_per_pack} arms={len(arms)})"
        )
    seen = {(r.arm_revision_id, r.pack_id, r.task_id) for r in real}
    for arm in arms:
        for pack in packs:
            for t in range(tasks_per_pack):
                tid = "" if tasks_per_pack == 1 else str(t)
                if (arm, pack, tid) not in seen and (arm, pack, "") not in seen:
                    # allow empty task_id when tasks_per_pack==1
                    if tasks_per_pack == 1 and (arm, pack, "") in seen:
                        continue
                    raise BakeoffContractError(
                        f"missing frozen cell arm={arm} pack={pack} task={tid}"
                    )


def build_anchor_rows(
    burst_id: str,
    packs: Sequence[str],
    *,
    golden_loader=None,
) -> List[FrozenCompletion]:
    """Synthetic arm: ground-truth golden.patch per pack."""
    from app.services.ln_sandbox_engineering_ci import materialize_pack

    loader = golden_loader
    rows: List[FrozenCompletion] = []
    for pack in packs:
        if loader:
            body = loader(pack)
        else:
            workdir, _meta, err = materialize_pack(pack)
            if not workdir:
                raise BakeoffContractError(f"anchor materialize {pack}: {err}")
            gpath = workdir / "golden.patch"
            if not gpath.is_file():
                raise BakeoffContractError(f"anchor missing golden: {pack}")
            body = gpath.read_text(encoding="utf-8")
        rows.append(
            FrozenCompletion(
                burst_id=burst_id,
                prompt_hash=prompt_hash_for(pack),
                pack_id=pack,
                task_id="",
                arm_revision_id=ANCHOR_ARM,
                adapter_sha="anchor",
                raw_text=body,
                gen_latency_ms=0,
                is_anchor=True,
            )
        )
    return rows


def score_one_row(row: FrozenCompletion) -> Dict[str, Any]:
    """diff → sandbox apply/test → numeric score. Fail-fast on bad shape."""
    if row.gen_error and not (row.raw_text or "").strip():
        return {
            "pack_id": row.pack_id,
            "arm_revision_id": row.arm_revision_id,
            "score": 0.0,
            "passed": False,
            "error": row.gen_error,
            "oracle": "gen_error",
        }
    text = (row.raw_text or "").strip()
    if not text:
        raise BakeoffContractError(f"empty raw_text at score time: {row.pack_id}")
    if "@@" not in text and "---" not in text:
        raise BakeoffContractError(
            f"raw_text not a unified diff: pack={row.pack_id} arm={row.arm_revision_id}"
        )

    from app.services.ln_sandbox_engineering_ci import (
        apply_unified_diff,
        materialize_pack,
        run_pytest,
        score_from_pytest,
    )

    workdir, meta, err = materialize_pack(row.pack_id)
    if not workdir or not meta:
        raise BakeoffContractError(f"materialize failed: {row.pack_id}: {err}")
    ok_apply, apply_msg = apply_unified_diff(workdir, text)
    if not ok_apply:
        return {
            "pack_id": row.pack_id,
            "arm_revision_id": row.arm_revision_id,
            "score": 0.0,
            "passed": False,
            "error": apply_msg,
            "oracle": "ci_pack",
        }
    test_path = meta.get("test_path") or "tests/test_fix.py"
    pytest_res = run_pytest(workdir, test_path)
    scored = score_from_pytest(pytest_res)
    passed = bool(scored.get("passed") or pytest_res.get("ok"))
    # Prefer explicit numeric score; else 1.0/0.0
    raw_score = scored.get("score")
    if raw_score is None:
        score = 1.0 if passed else 0.0
    else:
        try:
            score = float(raw_score)
        except (TypeError, ValueError) as e:
            raise BakeoffContractError(f"non-numeric score: {raw_score!r}") from e
    if math.isnan(score) or math.isinf(score):
        raise BakeoffContractError(f"NaN/Inf score forbidden: {score}")
    return {
        "pack_id": row.pack_id,
        "arm_revision_id": row.arm_revision_id,
        "score": score,
        "passed": passed,
        "oracle": "ci_pack",
        "is_anchor": row.is_anchor,
    }


def score_anchor(rows: Sequence[FrozenCompletion], *, min_score: float = 0.99) -> Dict[str, Any]:
    anchors = [r for r in rows if r.is_anchor or r.arm_revision_id == ANCHOR_ARM]
    if not anchors:
        raise BakeoffContractError("no anchor rows in frozen set")
    results = [score_one_row(r) for r in anchors]
    scores = [float(r["score"]) for r in results]
    mean = statistics.mean(scores) if scores else float("nan")
    if mean != mean or mean < min_score:  # NaN check
        raise BakeoffContractError(
            f"anchor gate failed: mean={mean} want>={min_score} detail={results}"
        )
    return {"ok": True, "mean": mean, "n": len(scores), "results": results}


def smoke_score(
    rows: Sequence[FrozenCompletion],
    *,
    n: int = 5,
) -> Dict[str, Any]:
    """Score n non-anchor rows; require valid numeric scores in ledger shape."""
    real = [r for r in rows if not r.is_anchor and r.arm_revision_id != ANCHOR_ARM]
    if len(real) < n:
        raise BakeoffContractError(f"smoke needs {n} real rows, have {len(real)}")
    sample = list(real[:n])
    results = []
    for r in sample:
        out = score_one_row(r)
        if out.get("score") is None or isinstance(out.get("score"), float) and math.isnan(out["score"]):
            raise BakeoffContractError(f"smoke null/NaN score: {out}")
        results.append(out)
    return {"ok": True, "n": len(results), "results": results}


def full_score(rows: Sequence[FrozenCompletion]) -> Dict[str, Any]:
    real = [r for r in rows if not r.is_anchor and r.arm_revision_id != ANCHOR_ARM]
    by_arm: Dict[str, List[float]] = {}
    results: List[Dict[str, Any]] = []
    for r in real:
        out = score_one_row(r)
        results.append(out)
        by_arm.setdefault(r.arm_revision_id, []).append(float(out["score"]))
    arms = sorted(by_arm.keys())
    if len(arms) < 2:
        raise BakeoffContractError(f"need ≥2 arms for verdict, got {arms}")
    stats: Dict[str, Dict[str, float]] = {}
    for arm, xs in by_arm.items():
        if not xs:
            raise BakeoffContractError(f"empty scores for arm {arm}")
        stats[arm] = {
            "mean": statistics.mean(xs),
            "lo": min(xs),
            "hi": max(xs),
            "n": float(len(xs)),
        }
    a, b = arms[0], arms[1]
    winner = a if stats[a]["mean"] >= stats[b]["mean"] else b
    return {
        "ok": True,
        "arms": arms,
        "stats": stats,
        "winner": winner,
        "results": results,
    }


def run_phase_b(
    rows: Sequence[FrozenCompletion],
    *,
    smoke_n: int = 5,
    anchor_min: float = 0.99,
) -> Dict[str, Any]:
    """Anchor → smoke → full → verdict payload (no DB required)."""
    if not rows:
        raise BakeoffContractError("empty frozen set")
    burst_ids = {r.burst_id for r in rows}
    if len(burst_ids) != 1:
        raise BakeoffContractError(f"frozen set must be one burst_id, got {burst_ids}")
    burst_id = next(iter(burst_ids))

    anchor = score_anchor(rows, min_score=anchor_min)
    smoke = smoke_score(rows, n=smoke_n)
    full = full_score(rows)
    arms = full["arms"]
    sa, sb = full["stats"][arms[0]], full["stats"][arms[1]]
    verdict = {
        "burst_id": burst_id,
        "rev_a": arms[0],
        "rev_b": arms[1],
        "winner": full["winner"],
        "mean_a": sa["mean"],
        "mean_b": sb["mean"],
        "lo_a": sa["lo"],
        "hi_a": sa["hi"],
        "lo_b": sb["lo"],
        "hi_b": sb["hi"],
        "n_a": int(sa["n"]),
        "n_b": int(sb["n"]),
        "anchor_score": anchor["mean"],
        "smoke_ok": True,
        "bakeoff_verdict": True,
    }
    return {
        "ok": True,
        "anchor": anchor,
        "smoke": smoke,
        "full": {"winner": full["winner"], "stats": full["stats"], "n_results": len(full["results"])},
        "verdict": verdict,
    }


async def persist_frozen_rows(db_pool, rows: Sequence[FrozenCompletion]) -> int:
    if not db_pool:
        return 0
    n = 0
    async with db_pool.acquire() as conn:
        for r in rows:
            r.validate()
            await conn.execute(
                """
                INSERT INTO ln7_bakeoff_frozen_completions (
                    burst_id, prompt_hash, pack_id, task_id, arm_revision_id,
                    adapter_sha, raw_text, gen_error, gen_latency_ms, is_anchor
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (burst_id, arm_revision_id, pack_id, task_id) DO UPDATE SET
                    raw_text = EXCLUDED.raw_text,
                    gen_error = EXCLUDED.gen_error,
                    gen_latency_ms = EXCLUDED.gen_latency_ms,
                    is_anchor = EXCLUDED.is_anchor,
                    adapter_sha = EXCLUDED.adapter_sha
                """,
                r.burst_id,
                r.prompt_hash,
                r.pack_id,
                r.task_id,
                r.arm_revision_id,
                r.adapter_sha,
                r.raw_text,
                r.gen_error,
                r.gen_latency_ms,
                r.is_anchor,
            )
            n += 1
    return n


async def persist_verdict(db_pool, verdict: Dict[str, Any]) -> bool:
    if not db_pool:
        return False
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ln7_bakeoff_verdicts (
                burst_id, rev_a, rev_b, winner,
                mean_a, mean_b, lo_a, hi_a, lo_b, hi_b, n_a, n_b,
                anchor_score, smoke_ok, payload_json
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb
            )
            ON CONFLICT (burst_id) DO UPDATE SET
                winner = EXCLUDED.winner,
                mean_a = EXCLUDED.mean_a,
                mean_b = EXCLUDED.mean_b,
                payload_json = EXCLUDED.payload_json,
                anchor_score = EXCLUDED.anchor_score,
                smoke_ok = EXCLUDED.smoke_ok
            """,
            verdict["burst_id"],
            verdict["rev_a"],
            verdict["rev_b"],
            verdict.get("winner"),
            verdict.get("mean_a"),
            verdict.get("mean_b"),
            verdict.get("lo_a"),
            verdict.get("hi_a"),
            verdict.get("lo_b"),
            verdict.get("hi_b"),
            int(verdict.get("n_a") or 0),
            int(verdict.get("n_b") or 0),
            verdict.get("anchor_score"),
            bool(verdict.get("smoke_ok")),
            json.dumps(verdict),
        )
    return True


def write_frozen_jsonl(path: Path, rows: Sequence[FrozenCompletion]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            r.validate()
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
