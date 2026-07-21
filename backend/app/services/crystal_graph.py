"""
Crystal Graph — Relationship Mapping, Constellation Retrieval & Meta-Crystals.

Phase 2 (5,000–10,000 crystals): Graph clustering identifies constellations
of related crystals.  A query retrieves not just the closest crystal but its
entire neighbourhood, giving Nate contextual depth on every topic.

Phase 3 (25,000–50,000 crystals): Meta-crystals are second-order syntheses
— crystals *about* crystal relationships.  They capture recurring structural
patterns across domains (e.g., "retry-with-backoff appears in networking,
queue processing, and API resilience — this is a universal fault-tolerance
pattern").

Architecture:
  - ``CrystalGraph`` holds an in-memory adjacency structure rebuilt from
    PostgreSQL (or SQLite in BLUE mode) on startup and refreshed every
    ``REBUILD_INTERVAL_HOURS``.
  - Edges are weighted by keyword overlap (Jaccard on extracted terms)
    and confidence product.  Edges below ``EDGE_THRESHOLD`` are pruned.
  - ``retrieve_constellation()`` returns a target crystal plus its N-hop
    neighbourhood, ordered by combined edge weight × confidence.
  - ``synthesize_meta_crystals()`` finds dense sub-graphs (>= 3 nodes,
    each pair connected) and synthesises a meta-crystal summarising the
    structural relationship.
"""

import asyncio
import hashlib
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

EDGE_THRESHOLD = 0.12
REBUILD_INTERVAL_HOURS = 4
META_MIN_CLUSTER_SIZE = 3
META_MAX_PER_CYCLE = 10
META_CONFIDENCE = 0.70


def _extract_terms(text: str) -> Set[str]:
    """Pull meaningful terms (3+ chars, alphanumeric) from crystal text."""
    return {
        w.lower()
        for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
        if w.lower() not in _STOP_WORDS
    }


_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "are",
    "was", "were", "been", "have", "has", "had", "not", "but",
    "can", "will", "just", "more", "also", "when", "than",
    "should", "would", "could", "each", "which", "their",
    "into", "about", "other", "some", "such", "only", "then",
    "them", "these", "those", "does", "used", "using", "after",
    "before", "between", "through", "during", "while",
    "none", "true", "false", "self", "return", "import",
    "def", "class", "async", "await", "try", "except",
})


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


class CrystalNode:
    # QUANTUM-CRYSTAL-ARCH: scope + user_id required for live traversal isolation
    __slots__ = ("id", "content_hash", "domain", "confidence", "text", "terms", "recall_count", "scope", "user_id")

    def __init__(self, row: Dict):
        self.id = row.get("id")
        self.content_hash = row.get("content_hash", "")
        self.domain = row.get("domain", "general")
        self.confidence = float(row.get("confidence", 0.5))
        self.text = row.get("crystal_text", "")[:1500]
        self.terms = _extract_terms(self.text)
        self.recall_count = int(row.get("recall_count") or 0)
        self.scope = row.get("scope") or "global"
        self.user_id = row.get("user_id")


class CrystalGraph:
    """In-memory adjacency graph over the active crystal corpus."""

    def __init__(self, db_pool=None, local_store=None, app_state=None):
        self._db_pool = db_pool
        self._local_store = local_store
        self._app_state = app_state
        self._nodes: Dict[Any, CrystalNode] = {}
        self._adj: Dict[Any, Dict[Any, float]] = defaultdict(dict)
        self._last_rebuild = datetime.min.replace(tzinfo=timezone.utc)
        self._edge_count = 0

    # ── Build / Rebuild ──

    async def rebuild(self):
        """Rebuild the crystal graph.

        Strategy:
        1. Try Vectorize-backed rebuild (O(n·k) where k=top_k neighbors).
           Each crystal queries Vectorize for its nearest neighbors in ~10ms.
        2. Fall back to inverted-term-index rebuild if Vectorize unavailable.
        """
        try:
            from app.services.vectorize_service import semantic_search_all, is_vectorize_configured
            if is_vectorize_configured():
                await self._rebuild_vectorize()
                return
        except ImportError:
            pass
        await self._rebuild_term_index()

    async def _rebuild_vectorize(self):
        """Build edges via Vectorize nearest-neighbor queries (primary method).

        For each crystal, query Vectorize for its top-10 semantic neighbors.
        This is O(n) Vectorize calls at ~10ms each, not O(n^2) comparisons.
        At 474K crystals with batching and throttling, completes in ~80 min
        as a background task without blocking the event loop.
        """
        from app.services.vectorize_service import semantic_search_all

        if not self._db_pool:
            return

        self._nodes.clear()
        self._adj.clear()
        self._edge_count = 0

        hash_to_node: Dict[str, Any] = {}
        _page_size = 500
        _offset = 0

        while True:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, crystal_text, domain, confidence, content_hash, scope, user_id
                    FROM nate_intelligence_crystals
                    WHERE scope != 'archived' AND superseded_by IS NULL
                    ORDER BY created_at ASC
                    LIMIT $1 OFFSET $2
                """, _page_size, _offset)
            if not rows:
                break
            for r in rows:
                # QUANTUM-CRYSTAL-ARCH: use CrystalNode(dict(r)), not _CrystalNode
                node = CrystalNode(dict(r))
                self._nodes[node.id] = node
                hash_to_node[node.content_hash] = node
            _offset += _page_size

        _processed = 0
        _batch_size = 50
        node_list = list(self._nodes.values())

        for i in range(0, len(node_list), _batch_size):
            batch = node_list[i:i + _batch_size]
            for node in batch:
                try:
                    results = await semantic_search_all(
                        node.text[:200],
                        user_id="",
                        top_k=10,
                        index_subset=["wisdom"],
                    )
                    flat = []
                    if isinstance(results, dict):
                        for v in results.values():
                            flat.extend(v if isinstance(v, list) else [])
                    elif isinstance(results, list):
                        flat = results

                    for r in flat:
                        score = r.get("score", 0)
                        if score < 0.55:
                            continue
                        meta = r.get("metadata") or {}
                        wid = meta.get("wisdom_id", "")
                        n_hash = wid.replace("crystal_", "", 1) if wid.startswith("crystal_") else ""
                        if not n_hash:
                            continue
                        neighbor = None
                        for nh, nn in hash_to_node.items():
                            if nh.startswith(n_hash) or n_hash.startswith(nh[:16]):
                                neighbor = nn
                                break
                        if not neighbor or neighbor.id == node.id:
                            continue
                        edge_weight = score * ((node.confidence * neighbor.confidence) ** 0.5)
                        if edge_weight >= EDGE_THRESHOLD:
                            self._adj[node.id][neighbor.id] = max(
                                self._adj.get(node.id, {}).get(neighbor.id, 0), edge_weight
                            )
                            self._adj[neighbor.id][node.id] = max(
                                self._adj.get(neighbor.id, {}).get(node.id, 0), edge_weight
                            )
                            self._edge_count += 1
                except Exception as e:
                    logger.debug("Vectorize edge query failed for node %s: %s", node.id, e)
                _processed += 1

            if i > 0 and i % 500 == 0:
                logger.info("CrystalGraph Vectorize rebuild: %d/%d nodes processed, %d edges",
                            _processed, len(node_list), self._edge_count)
            await asyncio.sleep(0.5)

        self._last_rebuild = datetime.now(timezone.utc)
        logger.info(
            "CrystalGraph rebuilt (Vectorize): %d nodes, %d edges",
            len(self._nodes), self._edge_count,
        )
        await self._persist_edges()

    async def _rebuild_term_index(self):
        """Fallback: build edges via inverted term index (no Vectorize).

        Uses keyword Jaccard similarity. O(n·k) where k = nodes sharing terms.
        """
        nodes = await self._load_all_nodes()
        self._nodes.clear()
        self._adj.clear()
        self._edge_count = 0

        for n in nodes:
            self._nodes[n.id] = n

        term_index: Dict[str, List[Any]] = defaultdict(list)
        for n in self._nodes.values():
            for term in n.terms:
                term_index[term].append(n.id)

        candidate_pairs: set = set()
        for node_ids in term_index.values():
            if len(node_ids) > 500:
                continue
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    a_id, b_id = node_ids[i], node_ids[j]
                    pair = (min(a_id, b_id), max(a_id, b_id))
                    candidate_pairs.add(pair)

        for a_id, b_id in candidate_pairs:
            a, b = self._nodes.get(a_id), self._nodes.get(b_id)
            if not a or not b:
                continue
            sim = _jaccard(a.terms, b.terms)
            conf_weight = (a.confidence * b.confidence) ** 0.5
            edge_weight = sim * conf_weight
            if edge_weight >= EDGE_THRESHOLD:
                self._adj[a.id][b.id] = edge_weight
                self._adj[b.id][a.id] = edge_weight
                self._edge_count += 1

        self._last_rebuild = datetime.now(timezone.utc)
        logger.info(
            "CrystalGraph rebuilt (term-index fallback): %d nodes, %d edges (from %d candidate pairs)",
            len(self._nodes), self._edge_count, len(candidate_pairs),
        )
        await self._persist_edges()

    async def _persist_edges(self):
        """Write edges to crystal_edges table atomically for cross-restart persistence."""
        if not self._db_pool:
            return
        try:
            edges_batch = []
            for a_id, neighbors in self._adj.items():
                a_node = self._nodes.get(a_id)
                if not a_node:
                    continue
                for b_id, weight in neighbors.items():
                    b_node = self._nodes.get(b_id)
                    if not b_node:
                        continue
                    # QUANTUM-CRYSTAL-ARCH: persist 16-char prefixes (matches live crystal_edges)
                    if a_node.content_hash < b_node.content_hash:
                        edges_batch.append((
                            a_node.content_hash[:16],
                            b_node.content_hash[:16],
                            weight,
                        ))

            if not edges_batch:
                return

            async with self._db_pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("DELETE FROM crystal_edges WHERE edge_type = 'semantic_neighbor'")
                    batch_size = 500
                    for i in range(0, min(len(edges_batch), 50000), batch_size):
                        chunk = edges_batch[i:i + batch_size]
                        await conn.executemany("""
                            INSERT INTO crystal_edges (crystal_a_hash, crystal_b_hash, similarity, edge_type)
                            VALUES ($1, $2, $3, 'semantic_neighbor')
                            ON CONFLICT (crystal_a_hash, crystal_b_hash) DO UPDATE SET similarity = $3
                        """, chunk)
            logger.info("CrystalGraph persisted %d edges to crystal_edges table", len(edges_batch))
        except Exception as e:
            logger.warning("CrystalGraph edge persistence failed: %s", e)

    async def maybe_rebuild(self):
        """Rebuild if stale (> REBUILD_INTERVAL_HOURS since last)."""
        age_hours = (datetime.now(timezone.utc) - self._last_rebuild).total_seconds() / 3600
        if age_hours >= REBUILD_INTERVAL_HOURS or not self._nodes:
            await self.rebuild()

    async def _load_all_nodes(self) -> List[CrystalNode]:
        """Load active crystals from PG or SQLite."""
        # GREEN mode
        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT id, crystal_text, domain, confidence,
                               content_hash, recall_count, scope, user_id
                        FROM nate_intelligence_crystals
                        WHERE superseded_by IS NULL
                          AND scope != 'archived'
                        ORDER BY confidence DESC
                        LIMIT 20000
                    """)
                return [CrystalNode(dict(r)) for r in rows]
            except Exception as e:
                logger.warning("CrystalGraph: PG load failed: %s", e)
                return []

        # BLUE mode
        if self._local_store:
            try:
                rows = self._local_store._conn.execute("""
                    SELECT rowid as id, crystal_text, domain, confidence,
                           content_hash, recall_count
                    FROM crystals
                    WHERE scope != 'archived'
                      AND superseded_by IS NULL
                    ORDER BY confidence DESC
                    LIMIT 20000
                """).fetchall()
                return [CrystalNode(dict(r)) for r in rows]
            except Exception as e:
                logger.warning("CrystalGraph: SQLite load failed: %s", e)
                return []

        return []

    # ── Constellation Retrieval (Phase 2) ──

    def _node_allowed_for(self, node: Optional[CrystalNode], requester_user_id: Optional[str]) -> bool:
        # QUANTUM-CRYSTAL-ARCH: live constellation must use isolation helper
        if not node:
            return False
        from app.services.crystal_graph_isolation import enforce_traversal_scope
        return enforce_traversal_scope(
            {"scope": getattr(node, "scope", "global"), "user_id": getattr(node, "user_id", None)},
            requester_user_id,
        )

    async def retrieve_constellation(
        self,
        query: str,
        max_depth: int = 2,
        max_results: int = 15,
        requester_user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Given a query, find the most relevant crystal and return
        its neighbourhood (1- or 2-hop), ordered by combined relevance.
        """
        await self.maybe_rebuild()
        if not self._nodes:
            return []

        query_terms = _extract_terms(query)
        if not query_terms:
            return []

        best_id = None
        best_score = -1.0
        for nid, node in self._nodes.items():
            if not self._node_allowed_for(node, requester_user_id):
                continue
            score = _jaccard(query_terms, node.terms) * node.confidence
            if score > best_score:
                best_score = score
                best_id = nid

        if best_id is None or best_score < 0.05:
            return []

        visited: Dict[Any, float] = {best_id: best_score}
        frontier = [best_id]

        for depth in range(max_depth):
            next_frontier = []
            for nid in frontier:
                for neighbour_id, edge_w in self._adj.get(nid, {}).items():
                    if neighbour_id in visited:
                        continue
                    neighbour = self._nodes.get(neighbour_id)
                    if not self._node_allowed_for(neighbour, requester_user_id):
                        continue
                    combined = edge_w * neighbour.confidence
                    visited[neighbour_id] = combined
                    next_frontier.append(neighbour_id)
            frontier = next_frontier

        ranked = sorted(visited.items(), key=lambda x: x[1], reverse=True)[:max_results]

        results = []
        for nid, score in ranked:
            node = self._nodes.get(nid)
            if node and self._node_allowed_for(node, requester_user_id):
                results.append({
                    "crystal_text": node.text,
                    "domain": node.domain,
                    "confidence": node.confidence,
                    "recall_count": node.recall_count,
                    "content_hash": node.content_hash,
                    "scope": getattr(node, "scope", "global"),
                    "user_id": getattr(node, "user_id", None),
                    "graph_score": round(score, 4),
                    "source": "constellation",
                })
        return results

    # ── Dense Sub-Graph Detection ──

    def _find_dense_clusters(self, min_size: int = META_MIN_CLUSTER_SIZE) -> List[List[Any]]:
        """Find cliques (fully connected sub-graphs) of size >= min_size.

        Uses a greedy seed-and-expand approach: for each node, try to
        grow a clique from its neighbourhood.  Not optimal for huge
        graphs, but fine for <20k nodes with sparse edges.
        """
        clusters: List[List[Any]] = []
        used: Set[Any] = set()

        for seed in sorted(self._adj.keys(), key=lambda x: len(self._adj[x]), reverse=True):
            if seed in used:
                continue
            neighbours = set(self._adj[seed].keys())
            clique = {seed}

            for candidate in sorted(neighbours, key=lambda c: self._adj[seed].get(c, 0), reverse=True):
                if candidate in used:
                    continue
                if all(candidate in self._adj.get(m, {}) for m in clique):
                    clique.add(candidate)

            if len(clique) >= min_size:
                clusters.append(sorted(clique))
                used.update(clique)

        return clusters[:META_MAX_PER_CYCLE * 2]

    # ── Meta-Crystal Synthesis (Phase 3) ──

    async def synthesize_meta_crystals(self, max_meta: int = META_MAX_PER_CYCLE) -> Dict[str, Any]:
        """Find dense sub-graphs and synthesise meta-crystals with LLM depth.

        A meta-crystal captures the *structural relationship* between
        crystals, not just their content.  Uses LLM when available for
        deep second-order reasoning; falls back to template otherwise.
        """
        await self.maybe_rebuild()
        dense = self._find_dense_clusters()
        if not dense:
            return {"created": 0, "clusters_found": 0}

        crystallizer = getattr(self._app_state, "crystallizer", None) if self._app_state else None
        inference = getattr(self._app_state, "inference_router", None) if self._app_state else None
        created = 0

        for cluster_ids in dense[:max_meta]:
            nodes = [self._nodes[nid] for nid in cluster_ids if nid in self._nodes]
            if len(nodes) < META_MIN_CLUSTER_SIZE:
                continue

            domains = sorted({n.domain for n in nodes})
            shared_terms = set.intersection(*(n.terms for n in nodes)) if nodes else set()

            content_parts = []
            for n in nodes:
                content_parts.append(f"  [{n.domain}] {n.text[:300]}")
            constituent_summary = "\n".join(content_parts)

            meta_text = None
            if inference:
                try:
                    _prompt = (
                        f"These {len(nodes)} crystals from {len(domains)} domain(s) "
                        f"({', '.join(domains)}) are densely connected by shared concepts: "
                        f"{', '.join(sorted(shared_terms)[:10]) or 'overlapping themes'}.\n\n"
                        f"Constituent crystals:\n{constituent_summary}\n\n"
                        f"Synthesize a META-CRYSTAL — a second-order insight about the "
                        f"RELATIONSHIP between these crystals. What unifying principle, "
                        f"mechanism, or pattern connects them that none states individually? "
                        f"State it as a standalone actionable truth."
                    )
                    _sys = (
                        "You are a meta-cognition engine. You find structural patterns "
                        "across knowledge crystals — the principle that connects them, "
                        "not a summary of their contents."
                    )
                    _result = await inference.generate(
                        prompt=_prompt, system=_sys, temperature=0.6, max_tokens=400,
                    )
                    meta_text = (_result.get("text", "").strip() if isinstance(_result, dict)
                                 else str(_result).strip())
                    if meta_text and len(meta_text) > 30:
                        meta_text = f"[META-CRYSTAL] {meta_text}"
                except Exception as _llm_err:
                    logger.warning("Meta-crystal LLM synthesis failed, using template: %s", _llm_err)

            if not meta_text or len(meta_text) < 30:
                meta_text = (
                    f"[META-CRYSTAL] Cross-domain relationship ({', '.join(domains)})\n"
                    f"Shared concepts: {', '.join(sorted(shared_terms)[:15])}\n"
                    f"Constituent crystals ({len(nodes)}):\n{constituent_summary}\n\n"
                    f"Structural insight: These {len(nodes)} crystals from "
                    f"{len(domains)} domain(s) share a common pattern around "
                    f"{', '.join(sorted(shared_terms)[:5]) or 'overlapping concepts'}."
                )

            content_hash = hashlib.sha256(meta_text.encode()).hexdigest()

            stored = False
            if self._db_pool:
                try:
                    async with self._db_pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO nate_intelligence_crystals
                            (crystal_text, domain, scope, topics, source_count,
                             generation, confidence, content_hash, face_path,
                             metadata)
                            VALUES ($1, $2, 'global', $3, $4, 1, $5, $6, 'graph:meta',
                                    $7::jsonb)
                            ON CONFLICT (content_hash) DO NOTHING
                        """,
                            meta_text,
                            domains[0] if len(domains) == 1 else "general",
                            sorted(shared_terms)[:6],
                            len(nodes),
                            META_CONFIDENCE,
                            content_hash,
                            '{"is_meta_crystal": true}',
                        )
                    try:
                        from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                        if is_vectorize_configured():
                            await index_wisdom(
                                user_id="nate_crystal",
                                wisdom_id=f"crystal_{content_hash[:16]}",
                                insight_type="crystal_meta",
                                content=meta_text,
                                source="meta_synthesis",
                                domain=domains[0] if len(domains) == 1 else "general",
                            )
                    except Exception as _vz_err:
                        logger.warning("Meta-crystal Vectorize index failed: %s", _vz_err)
                    created += 1
                    stored = True
                except Exception as _db_err:
                    logger.warning("Meta-crystal DB store failed: %s", _db_err)

            if not stored and crystallizer:
                crystallizer._harvest_buffer.append({
                    "text": meta_text,
                    "source": f"meta_crystal:{content_hash[:12]}",
                    "domain": domains[0] if len(domains) == 1 else "general",
                    "scope": "global",
                    "topics": sorted(shared_terms)[:6],
                    "created_at": datetime.now(timezone.utc),
                    "face_path": "graph:meta",
                    "is_meta": True,
                })
                created += 1

        logger.info(
            "CrystalGraph: synthesized %d meta-crystals from %d dense clusters",
            created, len(dense),
        )
        return {"created": created, "clusters_found": len(dense)}

    # ── Stats ──

    def get_stats(self) -> Dict[str, Any]:
        domain_counts: Dict[str, int] = defaultdict(int)
        for n in self._nodes.values():
            domain_counts[n.domain] += 1
        return {
            "total_nodes": len(self._nodes),
            "total_edges": self._edge_count,
            "domains": dict(domain_counts),
            "last_rebuild": self._last_rebuild.isoformat(),
            "avg_degree": round(
                sum(len(adj) for adj in self._adj.values()) / max(1, len(self._nodes)), 2
            ),
        }
