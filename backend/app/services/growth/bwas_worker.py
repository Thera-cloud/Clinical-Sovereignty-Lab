"""Weekly BWAS rollup from lead_events × growth_config.bwas_stage_weights.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.services.growth import bwas_enabled

logger = logging.getLogger("nate.growth.bwas")

_DEFAULT_WEIGHTS = {
    "impression": 0.05,
    "engage": 0.10,
    "click": 0.15,
    "quiz_start": 0.20,
    "quiz_complete": 0.25,
    "signup": 0.40,
    "active_client": 1.0,
}

# M4 (Phase M, R6 mirror) — provenance weighting by verified stage.
# lead_events deliberately strips device_id/hardware_id/ip/email/phone from
# `meta` at write time (lead_events.py _PII_META_KEYS) — there is no
# per-user Sybil-resistance signal available on this table without
# reintroducing PII tracking, which the existing privacy architecture
# forbids. The one non-PII structural signal this schema does support:
# attribution_link_id. A row with a link_id is traceable to a specific
# campaign/provider touch (ensure_attribution_link() was called with real
# content_kind+content_id); a row with no link_id is an orphan beacon fire
# with no traceable source — the profile most consistent with bot/replay
# noise, not a claim that any specific orphan event IS fraudulent.
#
# _VERIFIED_STAGES are stages that cannot occur without a real backend
# side effect (signup creates a users row; active_client requires payment)
# — provenance discount does not apply to them regardless of attribution
# presence, since the stage itself is already the verification.
_VERIFIED_STAGES = frozenset({"signup", "active_client"})
_DEFAULT_ORPHAN_DISCOUNT = 0.5


async def _provenance_config(conn) -> Dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT value FROM growth_config WHERE key = 'bwas_provenance'"
    )
    cfg: Dict[str, Any] = {
        "orphan_discount": _DEFAULT_ORPHAN_DISCOUNT,
        "verified_stages": sorted(_VERIFIED_STAGES),
    }
    if row and isinstance(row["value"], dict):
        try:
            cfg["orphan_discount"] = max(
                0.0, min(1.0, float(row["value"].get("orphan_discount", _DEFAULT_ORPHAN_DISCOUNT)))
            )
        except (TypeError, ValueError):
            pass
        vs = row["value"].get("verified_stages")
        if isinstance(vs, list) and vs:
            cfg["verified_stages"] = [str(s) for s in vs]
    return cfg


def provenance_weighted_stage_score(
    stage: str,
    attributed_n: int,
    orphan_n: int,
    *,
    stage_weight: float,
    orphan_discount: float = _DEFAULT_ORPHAN_DISCOUNT,
    verified_stages: Optional[frozenset] = None,
) -> float:
    """Pure function (unit-testable without DB): a stage's BWAS contribution
    after provenance weighting. Verified stages count fully regardless of
    attribution (the stage IS the verification); non-verified stages
    discount their orphan (no attribution_link_id) count."""
    vs = verified_stages if verified_stages is not None else _VERIFIED_STAGES
    if stage in vs:
        return stage_weight * (attributed_n + orphan_n)
    return stage_weight * (attributed_n + orphan_n * orphan_discount)


class BwasWorker:
    def __init__(self, db_pool, *, interval_s: int = 3600):
        self.db_pool = db_pool
        self.interval_s = interval_s
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_run: Dict[str, Any] = {"status": "init"}

    async def start(self) -> None:
        if not bwas_enabled():
            logger.info("BwasWorker not started (ENABLE_BWAS=false)")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("BwasWorker started (interval=%ss)", self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                self.last_run = await self.tick()
            except Exception as e:
                logger.warning("BwasWorker tick failed: %s", e)
                self.last_run = {"status": "error", "error": str(e)[:200]}
            await asyncio.sleep(self.interval_s)

    async def _weights(self, conn) -> Dict[str, float]:
        row = await conn.fetchrow(
            "SELECT value FROM growth_config WHERE key = 'bwas_stage_weights'"
        )
        w = dict(_DEFAULT_WEIGHTS)
        if row and isinstance(row["value"], dict):
            for k, v in row["value"].items():
                try:
                    w[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass
        return w

    async def tick(self, *, weeks: int = 1) -> Dict[str, Any]:
        if not bwas_enabled():
            return {"skipped": True}
        now = datetime.now(timezone.utc).date()
        # Monday-start week bucket
        week_start = now - timedelta(days=now.weekday())
        buckets = [week_start - timedelta(days=7 * i) for i in range(max(1, weeks))]
        upserted = 0
        async with self.db_pool.acquire() as conn:
            weights = await self._weights(conn)
            prov_cfg = await _provenance_config(conn)
            orphan_discount = float(prov_cfg["orphan_discount"])
            verified_stages = frozenset(prov_cfg["verified_stages"])
            for bucket in buckets:
                bucket_end = bucket + timedelta(days=7)
                # M4: split attributed (has attribution_link_id) vs orphan
                # (no link_id) counts per stage, instead of a flat COUNT(*).
                rows = await conn.fetch(
                    """
                    SELECT
                        COALESCE(audience, 'general') AS audience,
                        COALESCE(content_kind, 'marketing') AS content_kind,
                        COALESCE(content_id, 0) AS content_id,
                        stage,
                        COUNT(*) FILTER (WHERE attribution_link_id IS NOT NULL)::int AS attributed_n,
                        COUNT(*) FILTER (WHERE attribution_link_id IS NULL)::int AS orphan_n
                    FROM lead_events
                    WHERE created_at >= $1::date
                      AND created_at < $2::date
                      AND content_id IS NOT NULL
                    GROUP BY 1, 2, 3, stage
                    """,
                    bucket,
                    bucket_end,
                )
                # group by audience/kind/id
                groups: Dict[tuple, Dict[str, Dict[str, int]]] = {}
                for r in rows:
                    key = (r["audience"], r["content_kind"], int(r["content_id"]))
                    groups.setdefault(key, {})[r["stage"]] = {
                        "attributed": int(r["attributed_n"]),
                        "orphan": int(r["orphan_n"]),
                    }
                for (audience, kind, cid), stage_counts in groups.items():
                    score = 0.0
                    counts: Dict[str, int] = {}
                    for stage, split in stage_counts.items():
                        n_total = split["attributed"] + split["orphan"]
                        counts[stage] = n_total
                        score += provenance_weighted_stage_score(
                            stage,
                            split["attributed"],
                            split["orphan"],
                            stage_weight=float(weights.get(stage, 0)),
                            orphan_discount=orphan_discount,
                            verified_stages=verified_stages,
                        )
                    await conn.execute(
                        """
                        INSERT INTO bwas_weekly (
                            week_bucket, audience, content_kind, content_id,
                            score, stage_counts, updated_at
                        ) VALUES ($1,$2,$3,$4,$5,$6::jsonb, NOW())
                        ON CONFLICT (week_bucket, audience, content_kind, content_id)
                        DO UPDATE SET
                            score = EXCLUDED.score,
                            stage_counts = EXCLUDED.stage_counts,
                            updated_at = NOW()
                        """,
                        bucket,
                        audience,
                        kind,
                        cid,
                        score,
                        json.dumps(counts),
                    )
                    upserted += 1
        result = {
            "status": "ok",
            "upserted": upserted,
            "week_bucket": week_start.isoformat(),
        }
        self.last_run = result
        return result


async def list_bwas(
    db_pool, *, weeks: int = 4, limit: int = 50
) -> List[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM bwas_weekly
            WHERE week_bucket >= (CURRENT_DATE - ($1::text || ' weeks')::interval)::date
            ORDER BY score DESC, week_bucket DESC
            LIMIT $2
            """,
            str(max(1, weeks)),
            min(max(limit, 1), 200),
        )
    out = []
    for r in rows:
        d = dict(r)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
            elif isinstance(v, date):
                d[k] = v.isoformat()
            elif hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        out.append(d)
    return out


async def funnel_ranked(db_pool, *, weeks: int = 4, limit: int = 40) -> List[Dict[str, Any]]:
    """Aggregate BWAS score across recent weeks per content."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT content_kind, content_id, audience,
                   SUM(score)::float AS total_score,
                   COUNT(*)::int AS week_count
            FROM bwas_weekly
            WHERE week_bucket >= (CURRENT_DATE - ($1::text || ' weeks')::interval)::date
            GROUP BY content_kind, content_id, audience
            ORDER BY total_score DESC
            LIMIT $2
            """,
            str(max(1, weeks)),
            min(max(limit, 1), 200),
        )
    return [dict(r) for r in rows]
