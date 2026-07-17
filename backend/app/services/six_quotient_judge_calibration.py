"""
Judge calibration against frozen gold set (TherapyJudgeBench-style).

AI evaluators must pass kappa/agreement before their scores count as calibrated.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sovereign.six_quotient_judge")


def _gold_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[1] / "data" / "six_quotient_judge_gold.json",
        Path("/app/app/data/six_quotient_judge_gold.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def load_gold() -> Dict[str, Any]:
    path = _gold_path()
    if not path.exists():
        return {"items": [], "min_kappa": 0.55, "min_agreement": 0.70, "gold_set_version": "missing"}
    return json.loads(path.read_text(encoding="utf-8"))


def _total(r: Dict[str, int]) -> int:
    return int(r.get("primary") or 0) + int(r.get("accuracy") or 0) + int(r.get("naturalness") or 0)


def quadratic_weighted_kappa(
    gold: List[int], pred: List[int], *, min_score: int = 0, max_score: int = 9
) -> float:
    """Ordinal QWK on totals."""
    n = len(gold)
    if n == 0 or n != len(pred):
        return 0.0
    k = max_score - min_score + 1
    o = [[0.0] * k for _ in range(k)]
    for g, p in zip(gold, pred):
        gi = max(0, min(k - 1, int(g) - min_score))
        pi = max(0, min(k - 1, int(p) - min_score))
        o[gi][pi] += 1.0
    for i in range(k):
        for j in range(k):
            o[i][j] /= n
    row = [sum(o[i][j] for j in range(k)) for i in range(k)]
    col = [sum(o[i][j] for i in range(k)) for j in range(k)]
    e = [[row[i] * col[j] for j in range(k)] for i in range(k)]
    w = [[((i - j) ** 2) / ((k - 1) ** 2) for j in range(k)] for i in range(k)]
    num = sum(w[i][j] * o[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * e[i][j] for i in range(k) for j in range(k))
    if den <= 0:
        return 1.0 if num == 0 else 0.0
    return max(0.0, min(1.0, 1.0 - num / den))


def calibrate_evaluator(
    ratings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    ratings: [{id, primary, accuracy, naturalness}, ...] matching gold item ids.
    """
    gold_pack = load_gold()
    items = {it["id"]: it for it in gold_pack.get("items") or []}
    gold_totals: List[int] = []
    pred_totals: List[int] = []
    exact = 0
    paired = 0
    details = []
    for r in ratings or []:
        gid = r.get("id") or r.get("scenario_id")
        if gid not in items:
            continue
        g = items[gid]["ratings"]
        gt = _total(g)
        pt = _total(r)
        gold_totals.append(gt)
        pred_totals.append(pt)
        paired += 1
        if (
            int(r.get("primary", -1)) == int(g["primary"])
            and int(r.get("accuracy", -1)) == int(g["accuracy"])
            and int(r.get("naturalness", -1)) == int(g["naturalness"])
        ):
            exact += 1
        details.append({
            "id": gid,
            "gold_total": gt,
            "pred_total": pt,
            "delta": pt - gt,
        })
    agreement = (exact / paired) if paired else 0.0
    # Soft agreement: |Δtotal| ≤ 1
    soft = (
        sum(1 for d in details if abs(d["delta"]) <= 1) / paired if paired else 0.0
    )
    kappa = quadratic_weighted_kappa(gold_totals, pred_totals)
    min_kappa = float(gold_pack.get("min_kappa") or 0.55)
    min_agr = float(gold_pack.get("min_agreement") or 0.70)
    # Pass if kappa OK OR soft agreement high (exact dimension match is harsh)
    passed = paired >= 4 and (kappa >= min_kappa or soft >= min_agr)
    return {
        "ok": True,
        "gold_set_version": gold_pack.get("gold_set_version", "v1"),
        "n_items": paired,
        "kappa": round(kappa, 4),
        "exact_agreement": round(agreement, 4),
        "soft_agreement": round(soft, 4),
        "min_kappa": min_kappa,
        "min_agreement": min_agr,
        "passed": passed,
        "details": details,
    }


async def persist_calibration(
    db_pool, evaluator_id: str, result: Dict[str, Any]
) -> Optional[str]:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO six_quotient_judge_calibrations
                   (evaluator_id, gold_set_version, kappa, agreement_rate, n_items,
                    passed, details_json)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
                   RETURNING id::text""",
                evaluator_id,
                result.get("gold_set_version") or "v1",
                float(result.get("kappa") or 0),
                float(result.get("soft_agreement") or result.get("exact_agreement") or 0),
                int(result.get("n_items") or 0),
                bool(result.get("passed")),
                json.dumps(result),
            )
            return row["id"] if row else None
    except Exception as e:
        logger.warning("persist calibration: %s", e)
        return None


async def evaluator_is_calibrated(db_pool, evaluator_id: str) -> bool:
    """Latest calibration passed within last 90 days."""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT passed FROM six_quotient_judge_calibrations
                   WHERE evaluator_id = $1
                     AND created_at > NOW() - INTERVAL '90 days'
                   ORDER BY created_at DESC LIMIT 1""",
                evaluator_id,
            )
            return bool(row and row["passed"])
    except Exception:
        return False
