"""
Noetic Synthesis Stage 3 — Cross-domain knowledge emergence.

Background agent that synthesizes insights across all 7 crystal domains to discover
meta-patterns that no single domain agent would find on its own. Compares crystals
from domain pairs, detects overlapping concepts, and crystallizes emergent insights.

Runs every 4 hours. Can also be triggered on-demand via synthesize().
"""

import asyncio
import hashlib
import itertools
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CANONICAL_DOMAINS = [
    "clinical",
    "coaching",
    "marketing",
    "research",
    "culture",
    "defense",
    "general",
    "product",
    "coding",
    "operational",
]

OVERLAP_THRESHOLD = 0.3
LOOKBACK_DAYS = 7
LOOP_INTERVAL_SECONDS = 14400  # 4 hours
STAGGER_SECONDS = 120  # Unique stagger to avoid thundering herd

_SYNTHESIS_SYSTEM_PROMPT = (
    "You are a noetic synthesis engine within a sovereign AI therapeutic companion. "
    "Your role is to articulate emergent patterns across knowledge domains — insights that "
    "exist in neither source alone but arise from their intersection. "
    "Given two domains and their shared concepts, write a single clear sentence (2–4 clauses) "
    "that captures the meta-pattern. Be precise and clinically grounded. Never fabricate. "
    "If no genuine cross-domain insight exists, respond with exactly: No emergent pattern found."
)


def _extract_words(text: str) -> set:
    """Extract words of 3+ characters for similarity comparison."""
    if not text or not isinstance(text, str):
        return set()
    lower = text.lower()
    return set(re.findall(r"\b[a-zA-Z]{3,}\b", lower))


def _word_overlap_score(words_a: set, words_b: set) -> float:
    """Jaccard similarity: |intersection| / |union|."""
    if not words_a or not words_b:
        return 0.0
    inter = len(words_a & words_b)
    union = len(words_a | words_b)
    return inter / union if union > 0 else 0.0


def _content_hash(text: str, domain: str, scope: str, generation: int) -> str:
    payload = f"{text}|{domain}|{scope}|{generation}"
    return hashlib.sha256(payload.encode()).hexdigest()


class NoeticSynthesisStage3:
    """Cross-domain knowledge emergence — background agent."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NoeticSynthesisStage3 started (4-hour cycle)")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NoeticSynthesisStage3 stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(STAGGER_SECONDS)
        while self._running:
            try:
                results = await self.synthesize()
                if results:
                    logger.info(
                        "NoeticSynthesisStage3 cycle %d: crystallized %d meta-patterns",
                        self._cycle_count,
                        len(results),
                    )
                self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("NoeticSynthesisStage3 cycle error: %s", e)
            await asyncio.sleep(LOOP_INTERVAL_SECONDS)

    async def synthesize(self) -> List[Dict[str, Any]]:
        """
        Main synthesis entry point. Fetches crystals per domain, finds cross-domain
        patterns, and crystallizes them. Returns list of created crystal dicts.
        """
        if not self._db_pool:
            logger.debug("NoeticSynthesisStage3: no db_pool, skipping")
            return []

        domain_crystals = await self._get_domain_crystals()
        total = sum(len(v) for v in domain_crystals.values())
        if total < 2:
            logger.debug("NoeticSynthesisStage3: insufficient crystals (%d), skipping", total)
            return []

        patterns = await self._find_cross_domain_patterns(domain_crystals)
        if not patterns:
            return []

        return await self._crystallize_meta_patterns(patterns)

    async def _get_domain_crystals(self) -> Dict[str, List[Dict]]:
        """Fetch recent crystals (last 7 days) grouped by domain."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        result: Dict[str, List[Dict]] = {d: [] for d in CANONICAL_DOMAINS}

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, crystal_text, domain, topics, scope, source_count,
                           confidence, created_at
                    FROM nate_intelligence_crystals
                    WHERE superseded_by IS NULL
                      AND scope != 'archived'
                      AND created_at > $1
                    ORDER BY created_at DESC
                    """,
                    cutoff,
                )
        except Exception as e:
            logger.warning("NoeticSynthesisStage3: _get_domain_crystals failed: %s", e)
            return result

        for r in rows:
            domain = (r.get("domain") or "general").lower()
            if domain in result:
                result[domain].append({
                    "id": r["id"],
                    "crystal_text": r["crystal_text"] or "",
                    "domain": domain,
                    "topics": r["topics"] or [],
                    "scope": r["scope"] or "global",
                    "source_count": r["source_count"] or 1,
                    "confidence": float(r["confidence"] or 0.5),
                    "created_at": r["created_at"],
                })

        return result

    async def _find_cross_domain_patterns(
        self, domain_crystals: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """Compare each domain pair; return patterns with overlap_score > 0.3."""
        patterns: List[Dict] = []
        pairs = list(itertools.combinations(CANONICAL_DOMAINS, 2))

        for d1, d2 in pairs:
            crystals_a = domain_crystals.get(d1, [])
            crystals_b = domain_crystals.get(d2, [])
            if not crystals_a or not crystals_b:
                continue

            # Aggregate words per domain (from all crystals in that domain)
            words_a = set()
            ids_a: List[int] = []
            for c in crystals_a[:20]:
                words_a |= _extract_words(c.get("crystal_text", ""))
                ids_a.append(c["id"])

            words_b = set()
            ids_b: List[int] = []
            for c in crystals_b[:20]:
                words_b |= _extract_words(c.get("crystal_text", ""))
                ids_b.append(c["id"])

            overlap_score = _word_overlap_score(words_a, words_b)
            if overlap_score <= OVERLAP_THRESHOLD:
                continue

            shared = words_a & words_b
            shared_concepts = sorted(shared)[:15]

            patterns.append({
                "domains": [d1, d2],
                "overlap_score": round(overlap_score, 3),
                "shared_concepts": shared_concepts,
                "crystal_ids": ids_a[:5] + ids_b[:5],
                "sample_text_a": (crystals_a[0].get("crystal_text") or "")[:300],
                "sample_text_b": (crystals_b[0].get("crystal_text") or "")[:300],
            })

        return patterns

    async def _crystallize_meta_patterns(self, patterns: List[Dict]) -> List[Dict]:
        """Store meta-patterns as new crystals. Uses crystallizer or direct INSERT."""
        created: List[Dict] = []
        crystallizer = (
            getattr(self._app_state, "nate_memory_crystallizer", None)
            if self._app_state
            else None
        )
        router = (
            getattr(self._app_state, "inference_router", None) if self._app_state else None
        )

        for pattern in patterns:
            synthesis_text = await self._generate_synthesis_text(pattern, router)
            if not synthesis_text or "no emergent pattern found" in synthesis_text.lower():
                continue

            crystal_data = {
                "crystal_text": synthesis_text,
                "domain": "general",
                "scope": "global",
                "source_count": 2,
                "confidence": min(0.95, 0.5 + pattern["overlap_score"]),
                "topics": pattern["shared_concepts"][:10],
                "source_ids": pattern["crystal_ids"],
            }

            if crystallizer and hasattr(crystallizer, "store_meta_crystal"):
                try:
                    await crystallizer.store_meta_crystal(crystal_data)
                    created.append(crystal_data)
                except Exception as e:
                    logger.warning(
                        "NoeticSynthesisStage3: crystallizer store failed: %s", e
                    )
            else:
                row = await self._insert_crystal_direct(crystal_data)
                if row:
                    created.append({**crystal_data, "id": row["id"]})

        return created

    async def _generate_synthesis_text(
        self, pattern: Dict, router: Optional[Any]
    ) -> str:
        """Use inference router to generate synthesis text from pattern."""
        d1, d2 = pattern["domains"]
        concepts = ", ".join(pattern["shared_concepts"][:8])
        prompt = (
            f"Domains: {d1} and {d2}. Shared concepts: {concepts}.\n"
            f"Sample from {d1}: {pattern['sample_text_a'][:150]}...\n"
            f"Sample from {d2}: {pattern['sample_text_b'][:150]}...\n"
            "Write a single sentence capturing the emergent meta-pattern."
        )

        if router:
            try:
                result = await router.generate(
                    prompt=prompt,
                    system=_SYNTHESIS_SYSTEM_PROMPT,
                    tier="analytical",
                    temperature=0.5,
                    max_tokens=200,
                    domain="research",
                    allow_deep=True,
                )
                text = (result.get("text") or "").strip()
                return text if len(text) >= 30 else ""
            except Exception as e:
                logger.warning(
                    "NoeticSynthesisStage3: inference failed for %s–%s: %s",
                    d1,
                    d2,
                    e,
                )
        return ""

    async def _insert_crystal_direct(self, data: Dict) -> Optional[Dict]:
        """Direct INSERT into nate_intelligence_crystals when crystallizer unavailable."""
        if not self._db_pool:
            return None

        text = data.get("crystal_text", "")
        domain = data.get("domain", "general")
        scope = data.get("scope", "global")
        topics = data.get("topics", [])
        source_count = data.get("source_count", 2)
        confidence = float(data.get("confidence", 0.6))
        source_ids = data.get("source_ids", [])

        content_hash = _content_hash(text, domain, scope, 1)
        now = datetime.now(timezone.utc)

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_ids, source_count,
                     generation, confidence, content_hash, context_start, context_end,
                     created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, 1, $7, $8, $9, $9)
                    RETURNING id, crystal_text, domain, confidence
                    """,
                    text,
                    domain,
                    scope,
                    topics,
                    source_ids[:10],
                    source_count,
                    confidence,
                    content_hash,
                    now,
                )
            # QUANTUM-CRYSTAL-ARCH: Vectorize embedding for semantic search
            if row:
                try:
                    from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                    if is_vectorize_configured():
                        await index_wisdom(
                            user_id="nate_crystal",
                            wisdom_id=f"crystal_{content_hash[:16]}",
                            insight_type=f"noetic_stage3_{domain}",
                            content=text,
                            source="noetic_stage3",
                            domain=domain,
                        )
                except Exception as _v:
                    logger.debug("NoeticStage3: vectorize non-fatal: %s", _v)
                return dict(row)
            return None
        except Exception as e:
            logger.warning("NoeticSynthesisStage3: direct INSERT failed: %s", e)
            return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "cycle_count": self._cycle_count,
            "running": self._running,
            "domains": CANONICAL_DOMAINS,
        }
