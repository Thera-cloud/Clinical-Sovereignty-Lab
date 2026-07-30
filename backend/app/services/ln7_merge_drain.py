"""Stage 4 dare_ties merge drain with abort gate (Phase C).

Abort = authority: beat LN7-fast-baseline AND every contributor on held-out.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_merge_drain")

PINNED_MERGEKIT = "mergekit==0.0.5.1"  # pin; update only via weld


async def abort_gate(
    db_pool,
    *,
    merge_revision_id: str,
    contributor_ids: List[str],
    incumbent_id: str = "LN7-fast-baseline",
) -> Dict[str, Any]:
    """Return accept=True only if merge beats incumbent and all contributors."""
    if not db_pool:
        return {"accept": False, "reason": "no_db"}

    async def heldout_rate(rev: str) -> Optional[float]:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)::float AS n,
                    SUM(CASE WHEN o.passed THEN 1 ELSE 0 END)::float AS wins
                FROM ln7_coding_outcomes o
                JOIN ln7_tasks t ON t.task_id = o.task_id
                WHERE o.revision_id = $1 AND t.split = 'heldout'
                """,
                rev,
            )
        if not row or float(row["n"] or 0) < 1:
            return None
        return float(row["wins"] or 0) / float(row["n"])

    merge_rate = await heldout_rate(merge_revision_id)
    if merge_rate is None:
        return {"accept": False, "reason": "merge_no_heldout"}

    inc_rate = await heldout_rate(incumbent_id)
    if inc_rate is not None and merge_rate <= inc_rate:
        return {
            "accept": False,
            "reason": "below_incumbent",
            "merge_rate": merge_rate,
            "incumbent_rate": inc_rate,
        }

    for cid in contributor_ids:
        cr = await heldout_rate(cid)
        if cr is not None and merge_rate <= cr:
            return {
                "accept": False,
                "reason": "below_contributor",
                "contributor": cid,
                "merge_rate": merge_rate,
                "contributor_rate": cr,
            }

    return {
        "accept": True,
        "merge_rate": merge_rate,
        "incumbent_rate": inc_rate,
        "mergekit_pin": PINNED_MERGEKIT,
    }


def mergekit_yaml_dare_ties(
    contributors: List[Dict[str, Any]],
    *,
    density: float = 0.6,
) -> str:
    """Build dare_ties YAML. No target_model; do not relist base under models."""
    lines = [
        "merge_method: dare_ties",
        "base_model: Qwen/Qwen2.5-Coder-7B-Instruct",
        "parameters:",
        f"  density: {density}",
        "  weight: 1.0",
        "dtype: bfloat16",
        "models:",
    ]
    for c in contributors:
        path = c.get("path") or c.get("adapter_uri") or ""
        w = float(c.get("weight", 1.0))
        lines.append(f"  - model: {path}")
        lines.append("    parameters:")
        lines.append(f"      weight: {w}")
        lines.append(f"      density: {density}")
    return "\n".join(lines) + "\n"
