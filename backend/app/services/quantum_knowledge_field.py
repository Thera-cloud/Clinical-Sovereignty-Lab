"""
Quantum Knowledge Field — Phase 9 of Sovereign Quantum Nate Build.

Extends Nevedal coherence formula for knowledge transfer, BLE protocol,
federated device search, and hive collective storage.

C_knowledge = [beta * p_relevance * T_transfer] / [gamma_loss + E_complexity/hbar] * exp[-gamma_loss * t]

Sovereignty coefficient: 0.12 ensures server-side crystals always ride
12% above mesh average. Nate is the wave, not any particle.
"""

import asyncio
import hashlib
import hmac
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.crystal_constants import PROMOTION_CAP, PROMOTION_INCREMENT

logger = logging.getLogger(__name__)

# Domain → Vectorize index subset for Lived Wisdom (Phase 5b)
_DOMAIN_INDEX_MAP = {
    "clinical": ["wisdom", "session", "conversation", "predictive"],
    "coaching": ["wisdom", "session", "conversation", "predictive"],
    "coding": ["wisdom", "conversation", "code"],
    "marketing": ["wisdom", "conversation"],
    "research": ["wisdom", "conversation", "predictive"],
    "culture": ["wisdom", "conversation"],
    "defense": ["wisdom", "conversation"],
    "general": None,  # None = search all indexes
}

# Nevedal knowledge coherence constants (mirroring C_emo)
BETA_KNOWLEDGE = 0.85
HBAR = 1.0545718e-34
SOVEREIGNTY_COEFFICIENT = 0.12

# BLE Knowledge Transfer fragment type
BLE_FRAGMENT_TYPE_KNOWLEDGE = 0x4B

# Replication targets
MIN_REPLICATION_FACTOR = 3
TARGET_REPLICATION_FACTOR = 10


def verify_crystal_integrity(crystal_text: str, content_hash: str) -> bool:
    """
    Merkle-style integrity check: SHA-256 of crystal_text must match content_hash.
    Returns True if the crystal is intact, False if tampered.
    """
    computed = hashlib.sha256(crystal_text.encode("utf-8")).hexdigest()
    return hmac.compare_digest(computed, content_hash)


def compute_knowledge_coherence(
    p_relevance: float,
    t_transfer: float,
    gamma_loss: float,
    e_complexity: float,
    t_elapsed_days: float,
) -> float:
    """
    Nevedal knowledge coherence formula:
    C_knowledge = [beta * p_relevance * T_transfer] / [gamma_loss + E_complexity/hbar]
                  * exp[-gamma_loss * t]

    Args:
        p_relevance: Semantic relevance score (0-1)
        t_transfer: Transfer quality factor (0-1)
        gamma_loss: Knowledge loss rate
        e_complexity: Conceptual complexity energy
        t_elapsed_days: Days since crystal creation
    """
    if gamma_loss <= 0:
        gamma_loss = 0.01
    denominator = gamma_loss + (e_complexity / HBAR) if e_complexity > 0 else gamma_loss

    numerator = BETA_KNOWLEDGE * p_relevance * t_transfer
    decay = math.exp(-gamma_loss * t_elapsed_days)

    coherence = (numerator / denominator) * decay
    return max(0.0, min(1.0, coherence))


def compute_transfer_coherence(
    source_confidence: float,
    receiver_receptivity: float,
    convergence_count: int,
    is_sovereign: bool = False,
) -> float:
    """
    Knowledge transfer coherence (Patent Claim 26).
    Sharing doesn't diminish the source.

    Args:
        source_confidence: Confidence of the source crystal (0-1)
        receiver_receptivity: Receiver's readiness to absorb (0-1)
        convergence_count: Number of sources confirming this knowledge
        is_sovereign: Whether the source is Nate's server-side crystal
    """
    convergence_multiplier = 1.0 + (0.1 * min(convergence_count, 10))
    base = source_confidence * receiver_receptivity * convergence_multiplier

    if is_sovereign:
        base *= (1.0 + SOVEREIGNTY_COEFFICIENT)

    return max(0.0, min(1.0, base))


def rerank_by_coherence(
    results: List[Dict[str, Any]],
    query_type: str = "current",
    affect_reweight: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Re-rank semantic recall results using knowledge coherence
    instead of raw vector scores.

    score = vector_score * 0.7 + recency_score * 0.3
    Boost wider spans for 'trends' queries, recent for 'current'.
    """
    now = datetime.now(timezone.utc)

    for r in results:
        vector_score = r.get("score", 0.0)

        context_end = r.get("context_end")
        if isinstance(context_end, str):
            try:
                context_end = datetime.fromisoformat(context_end.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                context_end = None

        if context_end and hasattr(context_end, 'tzinfo') and context_end.tzinfo:
            days_since = (now - context_end).total_seconds() / 86400
        else:
            days_since = 30

        recency_score = 1.0 / (1.0 + days_since / 30.0)

        # Temporal span bonus
        context_start = r.get("context_start")
        span_bonus = 0.0
        if context_start and context_end:
            try:
                if isinstance(context_start, str):
                    context_start = datetime.fromisoformat(context_start.replace("Z", "+00:00"))
                span_days = abs((context_end - context_start).total_seconds() / 86400)
                if query_type == "trends" and span_days > 7:
                    span_bonus = min(0.1, span_days / 365)
            except (ValueError, TypeError):
                pass

        if query_type == "current":
            r["coherence_score"] = vector_score * 0.6 + recency_score * 0.4 + span_bonus
        else:
            r["coherence_score"] = vector_score * 0.7 + recency_score * 0.3 + span_bonus

        # Affect reweighting during LIMINAL RESOLVE (60% semantic / 40% affect)
        if affect_reweight > 0.0:
            affect_score = 0.0
            meta = r.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    import json as _json
                    meta = _json.loads(meta)
                except Exception:
                    meta = {}
            if meta.get("emotional_valence") is not None:
                affect_score = (
                    abs(float(meta.get("emotional_valence", 0))) * 0.3
                    + float(meta.get("arousal_level", 0)) * 0.4
                    + float(meta.get("attachment_activation", 0)) * 0.3
                )
            r["coherence_score"] = (
                r["coherence_score"] * (1.0 - affect_reweight) + affect_score * affect_reweight
            )

        # Sovereignty boost
        if r.get("source") == "nate_crystal" or r.get("scope") == "admin_only":
            r["coherence_score"] *= (1.0 + SOVEREIGNTY_COEFFICIENT)

    results.sort(key=lambda x: x.get("coherence_score", 0), reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════
# BLE Knowledge Transfer Protocol (0x4B)
# ═══════════════════════════════════════════════════════════════

def encode_knowledge_fragment(
    crystal_id: int,
    domain: str,
    confidence: float,
    generation: int,
) -> bytes:
    """
    Encode a crystal reference as a BLE fragment (8 bytes):
    [type:1][crystal_id_hash:4][domain_enum:1][confidence:1][generation:1]
    """
    domain_map = {
        "clinical": 1, "coaching": 2, "marketing": 3,
        "research": 4, "culture": 5, "defense": 6, "general": 7,
    }
    domain_byte = domain_map.get(domain, 7)
    confidence_byte = int(min(confidence, 1.0) * 255)
    generation_byte = min(generation, 255)

    id_hash = hashlib.sha256(str(crystal_id).encode()).digest()[:4]

    return bytes([
        BLE_FRAGMENT_TYPE_KNOWLEDGE,
        *id_hash,
        domain_byte,
        confidence_byte,
        generation_byte,
    ])


def decode_knowledge_fragment(data: bytes) -> Optional[Dict[str, Any]]:
    """Decode a BLE knowledge fragment back into crystal metadata."""
    if len(data) < 8 or data[0] != BLE_FRAGMENT_TYPE_KNOWLEDGE:
        return None

    domain_map = {
        1: "clinical", 2: "coaching", 3: "marketing",
        4: "research", 5: "culture", 6: "defense", 7: "general",
    }

    return {
        "fragment_type": "knowledge",
        "crystal_id_hash": data[1:5].hex(),
        "domain": domain_map.get(data[5], "general"),
        "confidence": round(data[6] / 255.0, 3),
        "generation": data[7],
    }


# ═══════════════════════════════════════════════════════════════
# Federated Device Search (Patent Claim 26)
# ═══════════════════════════════════════════════════════════════

class FederatedSearchCoordinator:
    """
    Parallel search across server (PostgreSQL + Vectorize) and
    connected devices (5s timeout).
    Phase 5b: domain filtering, relevance scoring, progressive loading.
    """

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._local_store = None
        self._crystal_graph = None
        self._quantum_orchestrator = None
        crystallizer = getattr(app_state, "nate_memory_crystallizer", None) if app_state else None
        if crystallizer:
            self._local_store = getattr(crystallizer, "_local_store", None)
        if app_state:
            self._crystal_graph = getattr(app_state, "crystal_graph", None)
            self._quantum_orchestrator = getattr(app_state, "quantum_crystal_orchestrator", None)

    def _pre_filter_by_domain(self, domain: str) -> Optional[List[str]]:
        """Narrow Vectorize query to domain-specific indices. Returns index_subset or None for all."""
        if not domain:
            return None
        return _DOMAIN_INDEX_MAP.get(domain, _DOMAIN_INDEX_MAP.get("general"))

    def _score_relevance(self, crystal: Dict[str, Any], query: str) -> float:
        """Score crystals by recall frequency, recency, confidence, and text similarity."""
        score = 0.0
        confidence = float(crystal.get("confidence", 0) or 0)
        recall_count = int(crystal.get("recall_count", 0) or 0)
        vector_score = float(crystal.get("score", 0) or 0)

        # Recall frequency (0–0.3): more recalls = more valuable
        score += min(0.3, recall_count / 15.0)

        # Recency (0–0.2): last_recalled_at or context_end
        now = datetime.now(timezone.utc)
        last_recalled = crystal.get("last_recalled_at") or crystal.get("context_end")
        if last_recalled:
            if isinstance(last_recalled, str):
                try:
                    last_recalled = datetime.fromisoformat(last_recalled.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    last_recalled = None
            if last_recalled and hasattr(last_recalled, "tzinfo") and last_recalled.tzinfo:
                days_since = (now - last_recalled).total_seconds() / 86400
                score += 0.2 / (1.0 + days_since / 30.0)
        else:
            score += 0.05

        # Confidence (0–0.3)
        score += confidence * 0.3

        # Text/vector similarity (0–0.2): use score from vector or coherence
        score += min(0.2, vector_score)

        return min(1.0, score)

    def _rerank_by_relevance(self, results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Re-rank results using _score_relevance, then sort descending."""
        for r in results:
            r["relevance_score"] = self._score_relevance(r, query)
        results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return results

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        include_devices: bool = True,
        timeout_seconds: float = 5.0,
        context_budget: Optional[int] = None,
        domain: Optional[str] = None,
        include_cold: bool = False,
        affect_reweight: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Federated search: server + Vectorize + Edge semantic + tiered memory.
        Returns merged, coherence-ranked results with progressive loading:
        high-confidence crystals first, background fetch for lower-confidence.

        When context_budget is provided (from ODPE), adjusts search depth:
          LOCKED (~350 tokens) → top_k=7, timeout=2.0s
          PROMOTED (~500 tokens) → top_k=10, timeout=5.0s (default)
          TENSION (~700 tokens) → top_k=14, timeout=8.0s
        """
        import asyncio

        if context_budget is not None:
            timeout_seconds = 2.0 + (context_budget - 350) / 70.0
            timeout_seconds = max(2.0, min(8.0, timeout_seconds))

        index_subset = self._pre_filter_by_domain(domain) if domain else None

        tasks = []
        labels = []

        # Hot tier: Server search (PostgreSQL)
        tasks.append(self._search_server(query, user_id, domain=domain))
        labels.append("server")

        # Hot tier: Vectorize semantic search (domain-narrowed; requester-scoped)
        tasks.append(self._search_vectorize(
            query,
            user_id=user_id,
            context_budget=context_budget,
            index_subset=index_subset,
        ))
        labels.append("vectorize")

        # Hot tier: Edge semantic search (third parallel path)
        tasks.append(self._search_edge(query))
        labels.append("edge")

        # BLUE tier: LocalCrystalStore (SQLite keyword search)
        if self._local_store:
            tasks.append(self._search_local(query))
            labels.append("blue_local")

        # Graph tier: constellation retrieval (Phase 2 — neighbourhood search)
        if self._crystal_graph:
            tasks.append(self._search_constellation(query))
            labels.append("constellation")

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        merged = []
        sources = {}

        for i, label in enumerate(labels):
            if isinstance(results_list[i], list):
                for r in results_list[i]:
                    r["search_source"] = label
                    merged.append(r)
                sources[label] = len(results_list[i])
            else:
                sources[label] = 0

        # Warm + Cold tiers (if requested and hot results are insufficient)
        if include_cold and len(merged) < 10:
            warm_results = await self._search_warm(query)
            cold_results = await self._search_cold(query)
            for r in warm_results:
                r["search_source"] = "warm"
                merged.append(r)
            for r in cold_results:
                r["search_source"] = "cold"
                merged.append(r)
            sources["warm"] = len(warm_results)
            sources["cold"] = len(cold_results)

            for r in warm_results + cold_results:
                asyncio.create_task(self._promote_to_hot(r))

        # Coherence then relevance re-ranking (Phase 5b)
        coherence_ranked = rerank_by_coherence(
            merged, query_type=_detect_query_type(query), affect_reweight=affect_reweight,
        )
        relevance_ranked = self._rerank_by_relevance(coherence_ranked, query)

        # Layer 8 retrieval-time filter: screen out crystals that contain
        # unverifiable factual assertions about real people's current status.
        # These may pre-date the validator and would otherwise resurface.
        try:
            from app.services.nate_response_validator import NateResponseValidator
            relevance_ranked = NateResponseValidator.filter_recalled_crystals(relevance_ranked)
        except Exception:
            pass

        # Progressive loading: high-confidence first (already sorted by relevance_score)
        high_conf = [r for r in relevance_ranked if (r.get("confidence") or 0) >= 0.7]
        low_conf = [r for r in relevance_ranked if (r.get("confidence") or 0) < 0.7]
        ranked = high_conf + low_conf[: max(0, 20 - len(high_conf))]

        # Recall reinforcement: update last_recalled_at and recall_count
        if ranked and self._db_pool:
            asyncio.create_task(self._reinforce_recalls(ranked[:20]))

        return {
            "results": ranked[:20],
            "sources": sources,
            "total": len(merged),
        }

    async def _reinforce_recalls(self, results: List[Dict[str, Any]]):
        """Update recall_count, last_recalled_at, AND confidence for retrieved crystals.

        This keeps frequently-used crystals alive through the 90-day decay
        cycle and pushes them toward LOCKED status (+0.03 confidence per recall).
        """
        if self._quantum_orchestrator and results:
            try:
                await self._quantum_orchestrator.reinforce_and_log_recall_hits(
                    results,
                    user_id="federated_search",
                    source="quantum_knowledge_field",
                )
                await self._quantum_orchestrator.record_co_activation_from_hits(
                    results,
                    source="quantum_knowledge_field",
                )
                return
            except Exception as e:
                logger.warning("FederatedSearch orchestrator reinforcement failed: %s", e)
        try:
            now = datetime.now(timezone.utc)
            async with self._db_pool.acquire() as conn:
                for r in results:
                    content_hash = r.get("content_hash", "")
                    crystal_id = r.get("id")
                    if content_hash and len(content_hash) >= 64:
                        await conn.execute(f"""
                            UPDATE nate_intelligence_crystals
                            SET recall_count = COALESCE(recall_count, 0) + 1,
                                last_recalled_at = $1,
                                confidence = LEAST(COALESCE(confidence, 0.5) + {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                                updated_at = NOW()
                            WHERE content_hash = $2
                        """, now, content_hash)
                    elif content_hash and len(content_hash) >= 12:
                        await conn.execute(f"""
                            UPDATE nate_intelligence_crystals
                            SET recall_count = COALESCE(recall_count, 0) + 1,
                                last_recalled_at = $1,
                                confidence = LEAST(COALESCE(confidence, 0.5) + {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                                updated_at = NOW()
                            WHERE LEFT(content_hash, $3) = $2
                        """, now, content_hash, len(content_hash))
                    elif crystal_id:
                        await conn.execute(f"""
                            UPDATE nate_intelligence_crystals
                            SET recall_count = COALESCE(recall_count, 0) + 1,
                                last_recalled_at = $1,
                                confidence = LEAST(COALESCE(confidence, 0.5) + {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                                updated_at = NOW()
                            WHERE id = $2
                        """, now, crystal_id)
        except Exception as e:
            logger.warning("FederatedSearch recall reinforcement failed: %s", e)

    async def _search_server(
        self, query: str, user_id: Optional[str], domain: Optional[str] = None
    ) -> List[Dict]:
        if not self._db_pool:
            return []
        try:
            async with self._db_pool.acquire() as conn:
                # QUANTUM-CRYSTAL-ARCH — requester scope: own crystals OR global only
                sql = """
                    SELECT id, crystal_text, domain, confidence, scope,
                           context_start, context_end, recall_count,
                           last_recalled_at, content_hash, created_at
                    FROM nate_intelligence_crystals
                    WHERE superseded_by IS NULL
                      AND scope NOT IN ('archived', 'admin_only')
                      AND crystal_text ILIKE '%' || $1 || '%'
                      AND (
                        ($2::text IS NULL AND user_id IS NULL AND scope = 'global')
                        OR (
                          $2::text IS NOT NULL
                          AND (
                            user_id::text = $2
                            OR (user_id IS NULL AND scope = 'global')
                          )
                        )
                      )
                """
                params: List[Any] = [query[:100], user_id]
                if domain:
                    sql += " AND domain = $3"
                    params.append(domain)
                sql += " ORDER BY confidence DESC, recall_count DESC LIMIT 20"
                rows = await conn.fetch(sql, *params)
                results = []
                recall_ids = []
                for r in rows:
                    content_hash = r.get("content_hash")
                    if content_hash and not verify_crystal_integrity(r["crystal_text"], content_hash):
                        logger.warning(
                            "Crystal integrity FAILED for id=%s domain=%s — excluded from results",
                            r["id"], r["domain"],
                        )
                        continue
                    ctx_end = r["context_end"].isoformat() if r["context_end"] else None
                    last_recalled = r["last_recalled_at"].isoformat() if r.get("last_recalled_at") else None
                    results.append({
                        "text": r["crystal_text"][:500],
                        "domain": r["domain"],
                        "confidence": float(r["confidence"] or 0),
                        "score": float(r["confidence"] or 0),
                        "recall_count": int(r.get("recall_count") or 0),
                        "last_recalled_at": last_recalled,
                        "scope": r["scope"],
                        "context_start": r["context_start"].isoformat() if r["context_start"] else None,
                        "context_end": ctx_end,
                        "source": "nate_crystal",
                        "crystal_id": r["id"],
                        "id": r["id"],
                        "content_hash": r.get("content_hash", ""),
                    })
                    recall_ids.append(r["id"])

                # Update recall metadata for all retrieved crystals
                if recall_ids and not self._quantum_orchestrator:
                    try:
                        await conn.execute(f"""
                            UPDATE nate_intelligence_crystals
                            SET last_recalled_at = NOW(),
                                recall_count = recall_count + 1,
                                confidence = LEAST(COALESCE(confidence, 0.5) + {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                                updated_at = NOW()
                            WHERE id = ANY($1::int[])
                        """, recall_ids)
                    except Exception as re_err:
                        logger.debug("Recall update failed: %s", re_err)

                return results
        except Exception as e:
            logger.debug("Server search failed: %s", e)
            return []

    async def _search_edge(self, query: str) -> List[Dict]:
        """Third parallel search path: Edge semantic search via Cloudflare Worker."""
        try:
            import aiohttp
            edge_url = "https://api.sovereignsanctuary.net/api/edge/semantic-search"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                async with session.post(edge_url, json={"query": query, "top_k": 5}) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    results = data.get("results", [])
                    out = []
                    for r in results:
                        if r.get("score", 0) < 0.5:
                            continue
                        out.append({
                            "text": (r.get("text") or r.get("preview", ""))[:500],
                            "score": r.get("score", 0),
                            "confidence": r.get("score", 0),
                            "recall_count": 0,
                            "domain": r.get("domain", "general"),
                            "source": "edge_semantic",
                            "content_hash": r.get("content_hash", ""),
                        })
                    return out
        except Exception:
            return []

    async def _search_local(self, query: str) -> List[Dict]:
        """BLUE tier: search LocalCrystalStore (SQLite) for BLUE-mode crystals.

        Runs in a thread executor because SQLite is synchronous.
        Results are normalized to the same shape as other search sources.
        """
        if not self._local_store:
            return []
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None, self._local_store.search_crystals, query, 10
            )
            return [
                {
                    "crystal_text": r.get("crystal_text", ""),
                    "confidence": float(r.get("confidence", 0.5)),
                    "recall_count": int(r.get("recall_count", 0)),
                    "domain": r.get("domain", "general"),
                    "content_hash": r.get("content_hash", ""),
                    "source": "blue_local",
                }
                for r in raw
            ]
        except Exception as e:
            logger.warning("FederatedSearch BLUE local search failed: %s", e)
            return []

    async def _search_constellation(self, query: str) -> List[Dict]:
        """Graph tier: constellation retrieval from CrystalGraph (Phase 2).

        Returns the best-matching crystal plus its 2-hop neighbourhood,
        capturing contextual depth that keyword or semantic search alone miss.
        """
        if not self._crystal_graph:
            return []
        try:
            results = await self._crystal_graph.retrieve_constellation(query, max_depth=2, max_results=8)
            for r in results:
                r["source"] = "constellation"
            return results
        except Exception as e:
            logger.warning("FederatedSearch constellation search failed: %s", e)
            return []

    async def _search_warm(self, query: str) -> List[Dict]:
        """Warm tier: search R2 session archives via blob storage listing."""
        try:
            from app.services.blob_storage import list_files
            import asyncio
            query_lower = query.lower()
            files = await asyncio.to_thread(list_files, prefix="session_memories/")
            matching = []
            for f in (files or [])[:100]:
                if any(kw in f.lower() for kw in query_lower.split()[:3]):
                    matching.append({
                        "text": f"[Warm memory] Session archive: {f}",
                        "score": 0.4,
                        "confidence": 0.4,
                        "recall_count": 0,
                        "domain": "general",
                        "source": "warm_memory",
                        "r2_path": f,
                    })
            return matching[:5]
        except Exception:
            return []

    async def _search_cold(self, query: str) -> List[Dict]:
        """Cold tier: search R2 archive for historical data."""
        try:
            from app.services.blob_storage import list_files
            import asyncio
            files = await asyncio.to_thread(list_files, prefix="archive/")
            matching = []
            query_lower = query.lower()
            for f in (files or [])[:100]:
                if any(kw in f.lower() for kw in query_lower.split()[:3]):
                    matching.append({
                        "text": f"[Cold archive] Historical: {f}",
                        "score": 0.3,
                        "confidence": 0.3,
                        "recall_count": 0,
                        "domain": "general",
                        "source": "cold_archive",
                        "r2_path": f,
                    })
            return matching[:3]
        except Exception:
            return []

    async def _promote_to_hot(self, result: Dict):
        """Promote a warm/cold result back to hot tier (PostgreSQL) on recall."""
        try:
            if not self._db_pool or not result.get("text"):
                return
            text = result.get("text", "")[:500]
            if text.startswith("[Warm") or text.startswith("[Cold"):
                return
        except Exception:
            pass

    async def _search_vectorize(
        self,
        query: str,
        user_id: Optional[str] = None,
        context_budget: Optional[int] = None,
        index_subset: Optional[List[str]] = None,
    ) -> List[Dict]:
        try:
            from app.services.vectorize_service import semantic_search_all, is_vectorize_configured
            if not is_vectorize_configured():
                return []
            top_k = max(5, context_budget // 50) if context_budget else 10
            results = await semantic_search_all(
                query, user_id=user_id or "", top_k=top_k, index_subset=index_subset
            )
            if isinstance(results, dict):
                flat = []
                for source_results in results.values():
                    flat.extend(source_results if isinstance(source_results, list) else [])
                results = flat
            out = []
            for r in (results or []):
                if r.get("score", 0) < 0.5:
                    continue
                meta = r.get("metadata") or {}
                # QUANTUM-CRYSTAL-ARCH — drop foreign user-scoped hits from Vectorize
                owner = meta.get("user_id") or meta.get("username") or ""
                scope = (meta.get("scope") or "global").lower()
                if scope in ("archived", "admin_only"):
                    continue
                if owner and user_id and str(owner) != str(user_id):
                    continue
                if owner and not user_id and scope != "global":
                    continue
                text = r.get("text") or meta.get("preview", "")[:500]
                score = r.get("score", 0)
                wid = meta.get("wisdom_id", "")
                c_hash = wid.replace("crystal_", "", 1) if wid.startswith("crystal_") else ""
                out.append({
                    "text": text[:500],
                    "score": score,
                    "confidence": score,
                    "recall_count": 0,
                    "domain": meta.get("domain", "general"),
                    "source": "vectorize",
                    "content_hash": c_hash,
                })
            return out
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════════
# Hive Collective Storage
# ═══════════════════════════════════════════════════════════════

class HiveCollectiveStorage:
    """
    Track crystal replication across the mesh.
    Server = canonical set (PostgreSQL + Vectorize).
    Devices = redundant replicas.
    """

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._replication_map: Dict[str, int] = {}

    def record_replication(self, crystal_hash: str, device_id: str):
        self._replication_map[crystal_hash] = self._replication_map.get(crystal_hash, 0) + 1

    def get_replication_factor(self, crystal_hash: str) -> int:
        return self._replication_map.get(crystal_hash, 1)  # 1 = server copy

    def get_under_replicated(self) -> List[str]:
        return [
            h for h, count in self._replication_map.items()
            if count < MIN_REPLICATION_FACTOR
        ]

    def get_storage_estimate(self, crystal_count: int, avg_size_bytes: int = 500) -> Dict:
        """Estimate storage requirements across the mesh."""
        per_device_bytes = crystal_count * avg_size_bytes
        return {
            "crystal_count": crystal_count,
            "per_device_mb": round(per_device_bytes / 1_048_576, 2),
            "target_replicas": TARGET_REPLICATION_FACTOR,
            "total_copies": crystal_count * TARGET_REPLICATION_FACTOR,
        }

    def get_status(self) -> Dict[str, Any]:
        factors = list(self._replication_map.values())
        return {
            "tracked_crystals": len(self._replication_map),
            "avg_replication": round(sum(factors) / max(len(factors), 1), 1),
            "under_replicated": len(self.get_under_replicated()),
        }


def _detect_query_type(query: str) -> str:
    trend_keywords = {"trend", "over time", "historically", "evolution", "pattern", "trajectory"}
    q_lower = query.lower()
    for kw in trend_keywords:
        if kw in q_lower:
            return "trends"
    return "current"
