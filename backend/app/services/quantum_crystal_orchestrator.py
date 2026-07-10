from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.crystal_constants import PROMOTION_CAP, PROMOTION_INCREMENT
from app.services.time_crystal_forge import TimeCrystalForge

logger = logging.getLogger(__name__)


class CrystalSignal(str, Enum):
    NOISE = "NOISE"
    PROVISIONAL = "PROVISIONAL"
    PROMOTED = "PROMOTED"
    LOCKED = "LOCKED"
    SOVEREIGN = "SOVEREIGN"
    TENSION = "TENSION"
    DEEP_TENSION = "DEEP_TENSION"


@dataclass
class FiveDMemoryCrystal:
    """Contract shape for crystal ranking/filtering in recall."""

    id: Optional[int] = None
    content_hash: str = ""
    content: str = ""
    domain: str = "general"
    confidence: float = 0.60
    signal: CrystalSignal = CrystalSignal.PROVISIONAL
    recall_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_recalled: Optional[datetime] = None

    @property
    def staleness_factor(self) -> float:
        now = datetime.now(timezone.utc)
        anchor = self.last_recalled or self.created_at
        days = max(0.0, (now - anchor).days)
        return max(0.3, 1.0 - (days / 2000.0))

    @property
    def is_cacheable(self) -> bool:
        return self.signal in (CrystalSignal.LOCKED, CrystalSignal.SOVEREIGN) and self.recall_count >= 8

    def reinforce(self, increment: int = 1) -> "FiveDMemoryCrystal":
        self.recall_count += increment
        self.last_recalled = datetime.now(timezone.utc)
        self.confidence = min(PROMOTION_CAP, self.confidence + (PROMOTION_INCREMENT * increment))
        self.signal = self._classify_signal()
        return self

    def _classify_signal(self) -> CrystalSignal:
        if self.confidence >= 0.95:
            return CrystalSignal.SOVEREIGN
        if self.confidence >= 0.85:
            return CrystalSignal.LOCKED
        if self.confidence >= 0.75:
            return CrystalSignal.PROMOTED
        if self.confidence >= 0.60:
            return CrystalSignal.PROVISIONAL
        return CrystalSignal.NOISE


class ODPESignalRouter:
    """Lightweight anti-hallucination filter for crystal recall results."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    async def filter_recall_results(self, crystals: List[FiveDMemoryCrystal]) -> List[FiveDMemoryCrystal]:
        filtered: List[FiveDMemoryCrystal] = []
        for c in crystals:
            if c.signal in (CrystalSignal.NOISE, CrystalSignal.DEEP_TENSION):
                continue
            filtered.append(c)
        priority = {
            CrystalSignal.SOVEREIGN: 0,
            CrystalSignal.LOCKED: 1,
            CrystalSignal.PROMOTED: 2,
            CrystalSignal.PROVISIONAL: 3,
            CrystalSignal.TENSION: 4,
        }
        filtered.sort(key=lambda c: (priority.get(c.signal, 9), -c.confidence))
        return filtered


@dataclass
class CrystalEdge:
    source_hash: str
    target_hash: str
    edge_type: str = "semantic_neighbor"
    strength: float = 0.1
    source: str = "quantum_orchestrator"
    co_activation_count: int = 0
    last_co_activated_at: Optional[datetime] = None


class EntanglementGraph:
    """Typed edge reader/traverser over crystal_edges."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    async def get_neighbors(self, crystal_hash: str, max_depth: int = 2, limit: int = 40) -> List[Dict[str, Any]]:
        if not self.db_pool or not crystal_hash:
            return []
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH RECURSIVE walk AS (
                    SELECT crystal_a AS src, crystal_b AS dst, edge_type, COALESCE(strength, similarity, 0.1) AS strength, 1 AS depth
                    FROM crystal_edges
                    WHERE crystal_a = $1 OR crystal_b = $1
                    UNION ALL
                    SELECT w.src, e.crystal_b, e.edge_type, COALESCE(e.strength, e.similarity, 0.1), w.depth + 1
                    FROM walk w
                    JOIN crystal_edges e ON e.crystal_a = w.dst
                    WHERE w.depth < $2
                )
                SELECT src, dst, edge_type, strength, depth
                FROM walk
                ORDER BY strength DESC
                LIMIT $3
                """,
                crystal_hash[:16],
                max_depth,
                limit,
            )
        return [dict(r) for r in rows]


class NevedalWaveEngine:
    """Contract API for EC scoring using A, Aw, I, R components."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    async def compute_ec(self, user_id: str) -> Dict[str, float]:
        if not self.db_pool:
            return {
                "ec": 0.5,
                "awareness": 0.5,
                "awakeness": 0.5,
                "integration": 0.5,
                "resistance": 0.5,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        awareness = await self._awareness(user_id)
        awakeness = await self._awakeness(user_id)
        integration = await self._integration(user_id)
        resistance = await self._resistance(user_id)
        denom = max(resistance, 0.1)
        ec = max(0.0, min(1.0, (awareness * awakeness * integration) / denom))
        return {
            "ec": round(ec, 4),
            "awareness": round(awareness, 4),
            "awakeness": round(awakeness, 4),
            "integration": round(integration, 4),
            "resistance": round(resistance, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _awareness(self, user_id: str) -> float:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE temporal_confidence >= 0.70) AS strong,
                       AVG(temporal_confidence) AS avg_conf
                FROM coherence_time_crystals
                WHERE user_id = $1
                """,
                user_id,
            )
        total = int(row["total"] or 0)
        if total == 0:
            return 0.3
        strong = int(row["strong"] or 0)
        avg_conf = float(row["avg_conf"] or 0.5)
        return max(0.3, min(0.95, 0.3 + (0.65 * min(1.0, strong / 10.0) * avg_conf)))

    async def _awakeness(self, user_id: str) -> float:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT AVG(prediction_accuracy) AS avg_acc
                FROM coherence_time_crystals
                WHERE user_id = $1 AND total_predictions >= 3
                """,
                user_id,
            )
        return max(0.2, min(1.0, float(row["avg_acc"] or 0.4)))

    async def _integration(self, user_id: str) -> float:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH user_crystals AS (
                    SELECT content_hash FROM nate_intelligence_crystals
                    WHERE (user_id IS NULL AND scope = 'global')
                       OR (user_id::text = $1 AND scope != 'archived')
                )
                SELECT
                    COUNT(*) FILTER (WHERE (source = 'co_activation')) AS co_edges,
                    COUNT(*) AS total_edges
                FROM crystal_edges
                WHERE crystal_a IN (SELECT content_hash FROM user_crystals)
                   OR crystal_b IN (SELECT content_hash FROM user_crystals)
                """,
                user_id,
            )
        total_edges = int(row["total_edges"] or 0)
        if total_edges == 0:
            return 0.3
        co_edges = int(row["co_edges"] or 0)
        ratio = co_edges / float(max(total_edges, 1))
        return max(0.3, min(0.95, 0.3 + ratio * 0.65))

    async def _resistance(self, user_id: str) -> float:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE signal = 'NOISE') AS noise_cnt,
                    COUNT(*) FILTER (WHERE signal IN ('TENSION','DEEP_TENSION')) AS tension_cnt,
                    COUNT(*) AS total_cnt
                FROM nate_intelligence_crystals
                WHERE (user_id IS NULL AND scope = 'global')
                   OR (user_id::text = $1 AND scope != 'archived')
                """,
                user_id,
            )
        total = float(max(int(row["total_cnt"] or 0), 1))
        noise = float(row["noise_cnt"] or 0) / total
        tension = float(row["tension_cnt"] or 0) / total
        return max(0.1, min(1.0, 0.1 + noise * 0.3 + tension * 0.3))


class CrystalRecallEngine:
    """9-step recall pipeline orchestrator facade."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self.odpe_router = ODPESignalRouter(db_pool)
        self.graph = EntanglementGraph(db_pool)
        self.nevedal = NevedalWaveEngine(db_pool)

    async def run(
        self,
        query: str,
        user_id: str,
        candidates: Sequence[Dict[str, Any]],
        max_results: int = 10,
    ) -> Dict[str, Any]:
        crystals = [self._to_crystal(c) for c in candidates]
        filtered = await self.odpe_router.filter_recall_results(crystals)
        ranked = sorted(
            filtered,
            key=lambda c: c.confidence * c.staleness_factor,
            reverse=True,
        )[:max_results]
        ec = await self.nevedal.compute_ec(user_id)
        return {"query": query, "ranked": ranked, "ec": ec}

    def _to_crystal(self, hit: Dict[str, Any]) -> FiveDMemoryCrystal:
        meta = hit.get("metadata", {}) if isinstance(hit, dict) else {}
        wid = str(meta.get("wisdom_id", ""))
        ch = wid.replace("crystal_", "", 1) if wid.startswith("crystal_") else str(hit.get("content_hash", ""))
        return FiveDMemoryCrystal(
            id=hit.get("id"),
            content_hash=ch,
            content=str(hit.get("text") or hit.get("crystal_text") or meta.get("text") or ""),
            domain=str(hit.get("domain") or meta.get("domain") or "general"),
            confidence=float(hit.get("confidence") or hit.get("score") or 0.6),
            recall_count=int(hit.get("recall_count") or 0),
        )


class QuantumCrystalOrchestrator:
    """Unified API for quantum crystal recall, reinforcement, and forging."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self.odpe_router = ODPESignalRouter(db_pool)
        self.nevedal_wave = NevedalWaveEngine(db_pool)
        self.time_forge = TimeCrystalForge(db_pool)
        self.entanglement_graph = EntanglementGraph(db_pool)
        self.recall_engine = CrystalRecallEngine(db_pool)
        self._forge_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_forge_window: Optional[str] = None

    async def recall(
        self,
        query: str,
        user_id: str,
        crystals: Sequence[Dict[str, Any]],
        source: str = "semantic",
        session_id: Optional[str] = None,
        call_sid: Optional[str] = None,
        odpe_signal: Optional[str] = None,
        max_results: int = 10,
    ) -> Dict[str, Any]:
        if not crystals:
            return {"crystals": [], "ec": await self.nevedal_wave.compute_ec(user_id), "time_crystals": []}
        recall_result = await self.recall_engine.run(query, user_id, crystals, max_results)
        ranked = recall_result["ranked"]
        neighbors = await self._expand_with_neighbors(ranked)
        ranked = (ranked + neighbors)[:max_results]
        await self.reinforce_and_log_recall_hits(
            ranked,
            user_id=user_id,
            source=source,
            session_id=session_id,
            call_sid=call_sid,
            odpe_signal=odpe_signal,
        )
        await self.record_co_activation_from_hits(
            ranked,
            source=source,
            session_id=session_id,
            call_sid=call_sid,
        )
        return {
            "crystals": [self._to_hit_dict(c) for c in ranked],
            "ec": recall_result["ec"],
            "time_crystals": await self.get_time_crystal_context(user_id),
        }

    async def _expand_with_neighbors(self, ranked: List[FiveDMemoryCrystal]) -> List[FiveDMemoryCrystal]:
        """Gap 3: Entanglement traversal — expand top crystals with graph neighbors."""
        if not ranked:
            return []
        seen = {c.content_hash for c in ranked}
        neighbors: List[FiveDMemoryCrystal] = []
        for c in ranked[:3]:
            if not c.content_hash:
                continue
            try:
                edges = await self.entanglement_graph.get_neighbors(c.content_hash[:16], max_depth=1, limit=5)
                for edge in edges:
                    dst = edge.get("dst", "")
                    if dst and dst not in seen:
                        seen.add(dst)
                        neighbors.append(FiveDMemoryCrystal(
                            content_hash=dst,
                            confidence=c.confidence * float(edge.get("strength", 0.3)),
                        ))
            except Exception:
                continue
        return neighbors

    async def reinforce_and_log_recall_hits(
        self,
        hits: Sequence[Any],
        user_id: str,
        source: str,
        session_id: Optional[str] = None,
        call_sid: Optional[str] = None,
        odpe_signal: Optional[str] = None,
    ) -> int:
        if not self.db_pool or not hits:
            return 0
        increment = 2 if odpe_signal == "LOCKED" else 1
        updated = 0
        async with self.db_pool.acquire() as conn:
            for h in hits:
                c = h if isinstance(h, FiveDMemoryCrystal) else self._to_crystal_obj(h)
                if not c.content_hash and not c.id:
                    continue
                if c.id:
                    await conn.execute(
                        f"""
                        UPDATE nate_intelligence_crystals
                        SET recall_count = COALESCE(recall_count, 0) + $2,
                            last_recalled_at = NOW(),
                            confidence = LEAST(COALESCE(confidence, 0.5) + $2 * {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        c.id,
                        increment,
                    )
                else:
                    await conn.execute(
                        f"""
                        UPDATE nate_intelligence_crystals
                        SET recall_count = COALESCE(recall_count, 0) + $2,
                            last_recalled_at = NOW(),
                            confidence = LEAST(COALESCE(confidence, 0.5) + $2 * {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                            updated_at = NOW()
                        WHERE LEFT(content_hash, 16) = $1
                        """,
                        c.content_hash[:16],
                        increment,
                    )
                await conn.execute(
                    """
                    INSERT INTO crystal_recall_log
                        (user_id, crystal_id, crystal_hash, source, session_id, call_sid, odpe_signal, recalled_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    """,
                    user_id,
                    c.id,
                    c.content_hash,
                    source,
                    session_id,
                    call_sid,
                    odpe_signal,
                )
                updated += 1
        return updated

    async def record_co_activation_from_hits(
        self,
        hits: Sequence[Any],
        source: str,
        session_id: Optional[str] = None,
        call_sid: Optional[str] = None,
    ) -> int:
        if not self.db_pool:
            return 0
        hashes = []
        for h in hits:
            c = h if isinstance(h, FiveDMemoryCrystal) else self._to_crystal_obj(h)
            if c.content_hash:
                hashes.append(c.content_hash[:16])
        hashes = sorted(set(hashes))
        if len(hashes) < 2:
            return 0
        now = datetime.now(timezone.utc)
        bucket = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
        updated = 0
        async with self.db_pool.acquire() as conn:
            for i, a in enumerate(hashes):
                for b in hashes[i + 1 :]:
                    await conn.execute(
                        """
                        INSERT INTO crystal_co_activation_events
                            (source, session_id, call_sid, crystal_a, crystal_b, time_bucket, event_count, last_seen_at, created_at)
                        VALUES
                            ($1, $2, $3, $4, $5, $6, 1, NOW(), NOW())
                        ON CONFLICT (source, COALESCE(session_id, ''), COALESCE(call_sid, ''), crystal_a, crystal_b, time_bucket)
                        DO UPDATE SET
                            event_count = crystal_co_activation_events.event_count + 1,
                            last_seen_at = NOW()
                        """,
                        source,
                        session_id,
                        call_sid,
                        a,
                        b,
                        bucket,
                    )
                    await conn.execute(
                        """
                        INSERT INTO crystal_edges
                            (crystal_a_hash, crystal_b_hash, similarity, edge_type, crystal_a, crystal_b,
                             strength, co_activation_count, last_co_activated_at, source, created_at)
                        VALUES
                            ($1, $2, 0.1, 'co_activation', $1, $2, 0.1, 1, NOW(), $3, NOW())
                        ON CONFLICT (crystal_a_hash, crystal_b_hash)
                        DO UPDATE SET
                            edge_type = 'co_activation',
                            source = EXCLUDED.source,
                            similarity = LEAST(1.0, COALESCE(crystal_edges.similarity, 0.0) + 0.01),
                            strength = LEAST(1.0, COALESCE(crystal_edges.strength, COALESCE(crystal_edges.similarity, 0.0)) + 0.01),
                            co_activation_count = COALESCE(crystal_edges.co_activation_count, 0) + 1,
                            last_co_activated_at = NOW()
                        """,
                        a,
                        b,
                        source,
                    )
                    updated += 1
        return updated

    async def get_time_crystal_context(self, user_id: str) -> List[Dict[str, Any]]:
        if not self.db_pool:
            return []
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, period_days, temporal_confidence, synthesized_meaning, therapeutic_implication, next_activation_at
                FROM coherence_time_crystals
                WHERE user_id = $1
                  AND temporal_confidence >= 0.60
                  AND next_activation_at BETWEEN NOW() AND NOW() + INTERVAL '7 days'
                ORDER BY next_activation_at ASC
                LIMIT 10
                """,
                user_id,
            )
        out = []
        for r in rows:
            next_at = r["next_activation_at"]
            days_until = 0.0
            if next_at:
                days_until = max(0.0, (next_at - datetime.now(timezone.utc)).total_seconds() / 86400.0)
            out.append(
                {
                    "id": int(r["id"]),
                    "period_days": float(r["period_days"] or 0.0),
                    "confidence": float(r["temporal_confidence"] or 0.0),
                    "meaning": r["synthesized_meaning"] or "",
                    "implication": r["therapeutic_implication"] or "",
                    "days_until": round(days_until, 2),
                }
            )
        return out

    async def start_forge_scheduler(self) -> None:
        if self._running:
            return
        self._running = True
        self._forge_task = asyncio.create_task(self._forge_loop())
        logger.info("QuantumCrystalOrchestrator forge scheduler started")

    async def stop_forge_scheduler(self) -> None:
        self._running = False
        if self._forge_task:
            self._forge_task.cancel()
            try:
                await self._forge_task
            except asyncio.CancelledError:
                pass
        self._forge_task = None

    async def _forge_loop(self) -> None:
        await asyncio.sleep(180)  # startup-safe stagger
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                iso_year, iso_week, _ = now.isocalendar()
                window_key = f"{iso_year}-W{iso_week}"
                if self._last_forge_window != window_key:
                    async with self.db_pool.acquire() as conn:
                        recall_count = await conn.fetchval(
                            "SELECT count(*) FROM crystal_recall_log WHERE recalled_at > NOW() - INTERVAL '7 days'"
                        )
                    if recall_count < 100:
                        logger.info("Forge skipped — insufficient data (%d recalls, need 100)", recall_count)
                        await asyncio.sleep(3600)
                        continue
                    result = await self.time_forge.forge_all_users()
                    self._last_forge_window = window_key
                    logger.info("Quantum forge window=%s users=%s forged=%s", window_key, result.get("users_processed"), result.get("time_crystals_forged"))
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Quantum forge scheduler cycle failed: %s", exc)
                await asyncio.sleep(300)

    def _to_crystal_obj(self, hit: Dict[str, Any]) -> FiveDMemoryCrystal:
        meta = hit.get("metadata", {}) if isinstance(hit, dict) else {}
        wid = ""
        if isinstance(meta, dict):
            wid = str(meta.get("wisdom_id", ""))
        hash_hint = ""
        if wid.startswith("crystal_"):
            hash_hint = wid.replace("crystal_", "", 1)
        content_hash = str(hit.get("content_hash") or hash_hint or "").strip()
        raw_signal = str(hit.get("signal") or meta.get("signal") or "PROVISIONAL")
        try:
            signal = CrystalSignal(raw_signal)
        except Exception:
            signal = CrystalSignal.PROVISIONAL
        created = hit.get("created_at")
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                created = None
        last_recalled = hit.get("last_recalled_at")
        if isinstance(last_recalled, str):
            try:
                last_recalled = datetime.fromisoformat(last_recalled.replace("Z", "+00:00"))
            except Exception:
                last_recalled = None
        return FiveDMemoryCrystal(
            id=hit.get("id") or hit.get("crystal_id"),
            content_hash=content_hash,
            content=str(hit.get("text") or hit.get("crystal_text") or meta.get("text") or ""),
            domain=str(hit.get("domain") or meta.get("domain") or "general"),
            confidence=float(hit.get("confidence") or hit.get("score") or 0.6),
            signal=signal,
            recall_count=int(hit.get("recall_count") or 0),
            created_at=created if isinstance(created, datetime) else datetime.now(timezone.utc),
            last_recalled=last_recalled if isinstance(last_recalled, datetime) else None,
        )

    def _rank_crystals(self, crystals: Sequence[FiveDMemoryCrystal], odpe_signal: Optional[str] = None) -> List[FiveDMemoryCrystal]:
        def _score(c: FiveDMemoryCrystal) -> float:
            base_relevance = c.confidence
            ec_weight = 1.0
            if odpe_signal == "LOCKED":
                ec_weight = 1.10
            elif odpe_signal in ("TENSION", "DEEP_TENSION"):
                ec_weight = 0.95
            return base_relevance * c.staleness_factor * ec_weight

        return sorted(crystals, key=_score, reverse=True)

    def _to_hit_dict(self, c: FiveDMemoryCrystal) -> Dict[str, Any]:
        return {
            "id": c.id,
            "content_hash": c.content_hash,
            "text": c.content,
            "domain": c.domain,
            "confidence": c.confidence,
            "signal": c.signal.value,
            "recall_count": c.recall_count,
            "staleness_factor": c.staleness_factor,
        }
