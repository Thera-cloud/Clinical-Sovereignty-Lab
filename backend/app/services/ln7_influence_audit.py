"""R6: provenance-weighted influence / Gini concentration for promote evidence.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence


def gini(weights: Sequence[float]) -> float:
    """Gini coefficient in [0,1]. Empty → 0."""
    vals = [float(w) for w in weights if float(w) > 0]
    if not vals:
        return 0.0
    vals = sorted(vals)
    n = len(vals)
    total = sum(vals)
    if total <= 0:
        return 0.0
    cum = 0.0
    for i, v in enumerate(vals, start=1):
        cum += i * v
    return max(0.0, min(1.0, (2.0 * cum) / (n * total) - (n + 1.0) / n))


def influence_audit(
    evidence_sources: List[Dict[str, Any]],
    *,
    yellow_gini: float = 0.72,
) -> Dict[str, Any]:
    """Return hold=True (YELLOW stricter bar) when evidence is concentrated."""
    weights = []
    for src in evidence_sources or []:
        w = float(src.get("weight") or src.get("count") or 0)
        prov = float(src.get("provenance_score") or 1.0)
        weights.append(max(0.0, w * max(0.05, min(1.0, prov))))
    g = gini(weights)
    return {
        "gini": g,
        "n_sources": len(weights),
        "yellow_hold": g >= yellow_gini and len(weights) >= 2,
        "threshold": yellow_gini,
    }
