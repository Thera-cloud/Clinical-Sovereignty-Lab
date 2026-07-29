"""keyword_queue CRUD + priority formula (Phase 2b demand_prior from themes).

priority = (volume_norm*w_v + intent*w_i + audience_value*w_a + buyer_prior*w_b)
           * demand_prior
demand_prior from try_theme_weekly when auto_demand=True (bound 1.0–1.5).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.growth.keywords")

_DEFAULT_WEIGHTS = {
    "volume_norm": 0.30,
    "intent": 0.25,
    "audience_value": 0.25,
    "buyer_prior": 0.20,
    "demand_prior_min": 1.0,
    "demand_prior_max": 1.5,
}


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def compute_priority_score(
    *,
    volume_norm: float,
    intent: float,
    audience_value: float,
    buyer_prior: float,
    demand_prior: float = 1.0,
    weights: Optional[Dict[str, Any]] = None,
) -> float:
    w = dict(_DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = _f(v)
    base = (
        _f(volume_norm) * _f(w.get("volume_norm", 0.30))
        + _f(intent) * _f(w.get("intent", 0.25))
        + _f(audience_value) * _f(w.get("audience_value", 0.25))
        + _f(buyer_prior) * _f(w.get("buyer_prior", 0.20))
    )
    dmin = _f(w.get("demand_prior_min", 1.0))
    dmax = _f(w.get("demand_prior_max", 1.5))
    d = max(dmin, min(dmax, _f(demand_prior)))
    return round(base * d, 6)


class KeywordQueueService:
    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def _weights(self, conn) -> Dict[str, Any]:
        row = await conn.fetchrow(
            "SELECT value FROM growth_config WHERE key = 'keyword_priority_weights'"
        )
        if not row:
            return dict(_DEFAULT_WEIGHTS)
        val = row["value"]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                return dict(_DEFAULT_WEIGHTS)
        return dict(val) if isinstance(val, dict) else dict(_DEFAULT_WEIGHTS)

    async def upsert(
        self,
        *,
        keyword: str,
        audience: str = "general",
        cluster: Optional[str] = None,
        volume_norm: float = 0.0,
        intent: float = 0.0,
        audience_value: float = 0.0,
        buyer_prior: float = 0.0,
        demand_prior: Optional[float] = None,
        auto_demand: bool = True,
        notes: Optional[str] = None,
        status: str = "queued",
    ) -> Dict[str, Any]:
        keyword = (keyword or "").strip().lower()
        if not keyword:
            raise ValueError("keyword required")
        audience = (audience or "general").strip().lower() or "general"
        async with self.db_pool.acquire() as conn:
            weights = await self._weights(conn)
            # QUANTUM-CRYSTAL-ARCH — Phase 2b: theme-derived demand when auto
            if auto_demand or demand_prior is None:
                from app.services.growth.demand_prior import demand_prior_for_keyword

                demand_prior = await demand_prior_for_keyword(
                    self.db_pool, keyword, weights=weights
                )
            else:
                demand_prior = float(demand_prior)
            score = compute_priority_score(
                volume_norm=volume_norm,
                intent=intent,
                audience_value=audience_value,
                buyer_prior=buyer_prior,
                demand_prior=demand_prior,
                weights=weights,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO keyword_queue (
                    keyword, cluster, audience, volume_norm, intent,
                    audience_value, buyer_prior, demand_prior, priority_score,
                    status, notes
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (keyword, audience) DO UPDATE SET
                    cluster = COALESCE(EXCLUDED.cluster, keyword_queue.cluster),
                    volume_norm = EXCLUDED.volume_norm,
                    intent = EXCLUDED.intent,
                    audience_value = EXCLUDED.audience_value,
                    buyer_prior = EXCLUDED.buyer_prior,
                    demand_prior = EXCLUDED.demand_prior,
                    priority_score = EXCLUDED.priority_score,
                    status = CASE
                        WHEN keyword_queue.status = 'done' THEN keyword_queue.status
                        ELSE EXCLUDED.status
                    END,
                    notes = COALESCE(EXCLUDED.notes, keyword_queue.notes),
                    updated_at = NOW()
                RETURNING *
                """,
                keyword,
                cluster,
                audience,
                volume_norm,
                intent,
                audience_value,
                buyer_prior,
                demand_prior,
                score,
                status,
                notes,
            )
        return self._serialize(dict(row))

    async def list(
        self, *, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        clauses = ["TRUE"]
        args: List[Any] = []
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        args.append(min(max(limit, 1), 200))
        sql = f"""
            SELECT * FROM keyword_queue
            WHERE {' AND '.join(clauses)}
            ORDER BY priority_score DESC, updated_at DESC
            LIMIT ${len(args)}
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [self._serialize(dict(r)) for r in rows]

    async def refresh_demand_priors(self, *, limit: int = 200) -> Dict[str, Any]:
        """Recompute demand_prior + priority_score for queued/in_progress keywords."""
        from app.services.growth.demand_prior import (
            demand_prior_for_keyword,
            load_theme_totals,
        )

        themes = await load_theme_totals(self.db_pool)
        updated = 0
        async with self.db_pool.acquire() as conn:
            weights = await self._weights(conn)
            rows = await conn.fetch(
                """
                SELECT id, keyword, volume_norm, intent, audience_value, buyer_prior
                FROM keyword_queue
                WHERE status IN ('queued', 'in_progress')
                ORDER BY updated_at DESC
                LIMIT $1
                """,
                min(max(limit, 1), 500),
            )
            for r in rows:
                d = await demand_prior_for_keyword(
                    self.db_pool,
                    r["keyword"],
                    weights=weights,
                    themes=themes,
                )
                score = compute_priority_score(
                    volume_norm=_f(r["volume_norm"]),
                    intent=_f(r["intent"]),
                    audience_value=_f(r["audience_value"]),
                    buyer_prior=_f(r["buyer_prior"]),
                    demand_prior=d,
                    weights=weights,
                )
                await conn.execute(
                    """
                    UPDATE keyword_queue
                    SET demand_prior = $2, priority_score = $3, updated_at = NOW()
                    WHERE id = $1
                    """,
                    r["id"],
                    d,
                    score,
                )
                updated += 1
        return {"updated": updated, "themes_considered": len(themes)}

    async def claim_next(self, *, limit: int = 2) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE keyword_queue
                SET status = 'in_progress', updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM keyword_queue
                    WHERE status = 'queued'
                    ORDER BY priority_score DESC, id ASC
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """,
                min(max(limit, 1), 10),
            )
        return [self._serialize(dict(r)) for r in rows]

    async def mark(
        self,
        keyword_id: int,
        *,
        status: str,
        last_content_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE keyword_queue
                SET status = $2,
                    last_content_id = COALESCE($3, last_content_id),
                    notes = COALESCE($4, notes),
                    updated_at = NOW()
                WHERE id = $1
                """,
                int(keyword_id),
                status,
                last_content_id,
                notes,
            )

    @staticmethod
    def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for k, v in list(out.items()):
            if isinstance(v, Decimal):
                out[k] = float(v)
            elif hasattr(v, "isoformat"):
                out[k] = v.isoformat()
        return out
