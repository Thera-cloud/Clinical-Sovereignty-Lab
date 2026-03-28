"""
Cross-Domain Synthesis Agent (Gap 8)

Periodically scans crystals across different domains and synthesizes
cross-domain insights that no single domain agent would discover.

Unlike domain agents that observe their own domain's data, this agent
specifically looks for patterns that BRIDGE domains — e.g., a clinical
observation that informs marketing strategy, or a defense pattern that
mirrors a coaching technique.

Cycle: every 4 hours
Temperature: 0.7 (balanced between precision and creativity)
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CYCLE_SECONDS = 14400  # 4 hours
MIN_CRYSTALS_PER_DOMAIN = 5
MAX_SYNTHESIS_PER_CYCLE = 5
CROSS_DOMAIN_PAIRS = [
    # Original domain pairs
    ("clinical", "coaching"),
    ("clinical", "research"),
    ("coaching", "marketing"),
    ("defense", "clinical"),
    ("culture", "marketing"),
    ("research", "defense"),
    ("coding", "defense"),
    ("coaching", "culture"),
    # Firehose domain pairs — real coaching scenarios where domains intersect
    ("legal", "clinical"),         # Lawyer burnout, litigation stress
    ("legal", "business"),         # Business law, contracts, liability
    ("legal", "accounting"),       # Tax law, financial compliance
    ("pmp", "business"),           # Project management in business context
    ("pmp", "machining"),          # Manufacturing project management
    ("pmp", "teaching"),           # Educational program management
    ("teaching", "clinical"),      # School counseling, student mental health
    ("business", "accounting"),    # Financial management, business operations
    ("business", "clinical"),      # Entrepreneurial stress, career transitions
    ("machining", "coding"),       # CNC programming, automation
    ("accounting", "clinical"),    # Financial stress, accountant burnout
    ("crisis", "legal"),           # Mandated reporting, duty to warn
    ("crisis", "teaching"),        # Student crisis intervention
]


class CrossDomainSynthesisAgent:
    """Background agent that discovers cross-domain crystal relationships."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("CrossDomainSynthesisAgent started (4h cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self):
        await asyncio.sleep(7200)  # start after 2h to let crystals accumulate
        while self._running:
            try:
                await self._cross_domain_cycle()
            except Exception as e:
                logger.warning("CrossDomainSynthesisAgent cycle error: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    async def _cross_domain_cycle(self):
        if not self._db_pool:
            return

        inference = (getattr(self._app_state, "inference_router", None)
                     if self._app_state else None)
        crystallizer = (getattr(self._app_state, "crystallizer", None)
                        if self._app_state else None)

        synthesized = 0

        for domain_a, domain_b in CROSS_DOMAIN_PAIRS:
            if synthesized >= MAX_SYNTHESIS_PER_CYCLE:
                break

            try:
                async with self._db_pool.acquire() as conn:
                    rows_a = await conn.fetch("""
                        SELECT crystal_text, domain, confidence, content_hash
                        FROM nate_intelligence_crystals
                        WHERE domain = $1 AND scope != 'archived'
                          AND superseded_by IS NULL AND confidence >= 0.5
                        ORDER BY confidence DESC, recall_count DESC
                        LIMIT 8
                    """, domain_a)

                    rows_b = await conn.fetch("""
                        SELECT crystal_text, domain, confidence, content_hash
                        FROM nate_intelligence_crystals
                        WHERE domain = $1 AND scope != 'archived'
                          AND superseded_by IS NULL AND confidence >= 0.5
                        ORDER BY confidence DESC, recall_count DESC
                        LIMIT 8
                    """, domain_b)

                if len(rows_a) < MIN_CRYSTALS_PER_DOMAIN or len(rows_b) < MIN_CRYSTALS_PER_DOMAIN:
                    continue

                cross_text = await self._synthesize_cross_domain(
                    rows_a, rows_b, domain_a, domain_b, inference,
                )
                if not cross_text or len(cross_text) < 40:
                    continue

                content_hash = hashlib.sha256(cross_text.encode()).hexdigest()

                async with self._db_pool.acquire() as conn:
                    result = await conn.execute("""
                        INSERT INTO nate_intelligence_crystals
                        (crystal_text, domain, scope, topics, source_count,
                         generation, confidence, content_hash, face_path,
                         metadata)
                        VALUES ($1, 'general', 'global', $2, $3, 1, 0.65, $4,
                                'agent:cross_domain',
                                $5::jsonb)
                        ON CONFLICT (content_hash) DO NOTHING
                    """,
                        cross_text,
                        [domain_a, domain_b],
                        len(rows_a) + len(rows_b),
                        content_hash,
                        f'{{"cross_domain": true, "domains": ["{domain_a}", "{domain_b}"]}}',
                    )
                    if result and "INSERT" in result:
                        synthesized += 1

                try:
                    from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                    if is_vectorize_configured():
                        await index_wisdom(
                            user_id="nate_crystal",
                            wisdom_id=f"crystal_{content_hash[:16]}",
                            insight_type=f"crystal_cross_{domain_a}_{domain_b}",
                            content=cross_text,
                            source="cross_domain_agent",
                            domain="general",
                        )
                except Exception as _vz_err:
                    logger.warning("Cross-domain Vectorize index failed: %s", _vz_err)

                if crystallizer:
                    crystallizer._harvest_buffer.append({
                        "text": cross_text,
                        "source": f"cross_domain:{domain_a}_{domain_b}",
                        "domain": "general",
                        "scope": "global",
                        "created_at": datetime.now(timezone.utc),
                        "face_path": "agent:cross_domain",
                    })

            except Exception as pair_err:
                logger.warning("Cross-domain pair %s/%s failed: %s",
                               domain_a, domain_b, pair_err)

        if synthesized:
            print(f"[CROSS-DOMAIN AGENT] Synthesized {synthesized} cross-domain crystals")
            logger.info("CrossDomainSynthesisAgent: %d cross-domain crystals created", synthesized)

    async def _synthesize_cross_domain(
        self,
        rows_a: list,
        rows_b: list,
        domain_a: str,
        domain_b: str,
        inference,
    ) -> Optional[str]:
        a_text = "\n---\n".join(r["crystal_text"][:300] for r in rows_a[:5])
        b_text = "\n---\n".join(r["crystal_text"][:300] for r in rows_b[:5])

        prompt = (
            f"You are examining crystals from two different domains:\n\n"
            f"== {domain_a.upper()} DOMAIN ==\n{a_text}\n\n"
            f"== {domain_b.upper()} DOMAIN ==\n{b_text}\n\n"
            f"Identify a CROSS-DOMAIN insight — a principle or mechanism that "
            f"connects these two domains in a way that neither domain states "
            f"independently. The insight should be actionable: someone working "
            f"in {domain_a} should gain something from the {domain_b} perspective, "
            f"or vice versa. State it as a standalone truth in 2-4 sentences."
        )

        sys_msg = (
            "You are a cross-domain intelligence synthesizer. Your purpose is "
            "to find the bridge between different knowledge domains — the "
            "non-obvious connection that creates compound insight."
        )

        if inference:
            try:
                result = await inference.generate(
                    prompt=prompt, system=sys_msg, temperature=0.7, max_tokens=400,
                )
                text = (result.get("text", "").strip() if isinstance(result, dict)
                        else str(result).strip())
                if text and len(text) > 30:
                    return f"[CROSS-DOMAIN: {domain_a} ↔ {domain_b}] {text}"
            except Exception as e:
                logger.warning("Cross-domain LLM synthesis failed: %s", e)

        return None
