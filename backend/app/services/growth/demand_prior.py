"""Map try_theme_weekly aggregates → keyword demand_prior (1.0–1.5).

Phase 2b. Counts only — never utterances.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("nate.growth.demand_prior")

_DEFAULT_MIN = 1.0
_DEFAULT_MAX = 1.5


def compute_demand_prior_from_themes(
    keyword: str,
    themes: Sequence[Dict[str, Any]],
    *,
    dmin: float = _DEFAULT_MIN,
    dmax: float = _DEFAULT_MAX,
) -> float:
    """Bound demand_prior in [dmin, dmax] from anonymized theme totals."""
    dmin = float(dmin)
    dmax = float(dmax)
    if dmax < dmin:
        dmax = dmin
    kw = (keyword or "").strip().lower().replace("_", " ").replace("-", " ")
    kw = re.sub(r"\s+", " ", kw)
    if not kw or not themes:
        return dmin

    cleaned: List[Tuple[str, int]] = []
    for t in themes:
        slug = (t.get("theme") or "").strip().lower()
        if not slug or slug == "ops_only":
            continue
        total = int(t.get("total") or t.get("count_bucket") or 0)
        if total <= 0:
            continue
        cleaned.append((slug, total))
    if not cleaned:
        return dmin

    max_total = max(n for _, n in cleaned) or 1
    best = 0.0
    for slug, total in cleaned:
        label = slug.replace("_", " ")
        words = [w for w in label.split() if len(w) >= 4]
        hit = False
        if label in kw or kw in label:
            hit = True
        elif any(w in kw for w in words):
            hit = True
        elif any(w in label for w in kw.split() if len(w) >= 4):
            hit = True
        if hit:
            best = max(best, total / max_total)

    return round(dmin + (dmax - dmin) * best, 4)


async def load_theme_totals(db_pool, *, weeks: int = 4, limit: int = 40) -> List[Dict[str, Any]]:
    from app.services.growth.try_theme_emitter import list_try_themes

    if not db_pool:
        return []
    try:
        return await list_try_themes(db_pool, weeks=weeks, limit=limit)
    except Exception as e:
        logger.warning("demand_prior: list_try_themes failed: %s", e)
        return []


async def demand_prior_for_keyword(
    db_pool,
    keyword: str,
    *,
    weights: Optional[Dict[str, Any]] = None,
    themes: Optional[List[Dict[str, Any]]] = None,
) -> float:
    w = weights or {}
    dmin = float(w.get("demand_prior_min", _DEFAULT_MIN))
    dmax = float(w.get("demand_prior_max", _DEFAULT_MAX))
    if themes is None:
        themes = await load_theme_totals(db_pool)
    return compute_demand_prior_from_themes(keyword, themes, dmin=dmin, dmax=dmax)


async def top_demand_themes(db_pool, *, limit: int = 8, weeks: int = 4) -> List[str]:
    themes = await load_theme_totals(db_pool, weeks=weeks, limit=max(limit, 1))
    out: List[str] = []
    for t in themes:
        slug = (t.get("theme") or "").strip()
        if slug and slug != "ops_only":
            out.append(slug)
        if len(out) >= limit:
            break
    return out
