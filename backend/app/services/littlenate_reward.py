"""
LittleNate-1.X Nevedal Reward Loop.

Scores every inference response using the Nevedal formula and stores
high-quality (prompt, response) pairs for future SFT/LoRA training.

Scoring dimensions:
  - C_knowledge: crystal match quality (relevance × transfer × decay)
  - C_quantum_self: how coherent Nate felt producing the response
  - Combined reward: weighted average driving training pair selection

Thresholds:
  - reward >= 0.7 → SFT-quality training pair (stored)
  - reward < 0.3  → Night School review case
"""

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SFT_THRESHOLD = 0.7
REVIEW_THRESHOLD = 0.3
KNOWLEDGE_WEIGHT = 0.4
QUANTUM_WEIGHT = 0.6


class LittleNateReward:
    """Nevedal formula reward scoring and training pair harvesting."""

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._pairs_stored = 0
        self._reviews_flagged = 0
        self._total_scored = 0

    def set_db_pool(self, pool):
        self._db_pool = pool

    async def score_and_store(
        self,
        prompt: str,
        response: str,
        c_knowledge: float = 0.0,
        c_quantum_self: float = 0.0,
        felt_sense: str = "grounded",
        domain: str = "general",
        provider: str = "sovereign",
        tokens_used: int = 0,
        latency_ms: int = 0,
    ) -> Dict[str, Any]:
        """
        Score the response and store if quality exceeds SFT threshold.
        Returns the reward signal and storage decision.
        """
        reward = (KNOWLEDGE_WEIGHT * c_knowledge) + (QUANTUM_WEIGHT * c_quantum_self)
        self._total_scored += 1

        result = {
            "reward": round(reward, 4),
            "c_knowledge": round(c_knowledge, 4),
            "c_quantum_self": round(c_quantum_self, 4),
            "felt_sense": felt_sense,
            "sft_quality": reward >= SFT_THRESHOLD,
            "needs_review": reward < REVIEW_THRESHOLD,
            "stored": False,
        }

        if reward >= SFT_THRESHOLD and self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO littlenate_training_pairs
                           (prompt_text, response_text, c_knowledge, c_quantum_self,
                            felt_sense, domain, provider, tokens_used, latency_ms)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                        prompt[:5000], response[:10000],
                        c_knowledge, c_quantum_self,
                        felt_sense, domain, provider,
                        tokens_used, latency_ms,
                    )
                result["stored"] = True
                self._pairs_stored += 1
            except Exception as e:
                logger.warning("LittleNateReward: failed to store training pair: %s", e)

        if reward < REVIEW_THRESHOLD:
            self._reviews_flagged += 1
            logger.info(
                "LittleNateReward: low reward %.3f for domain=%s felt=%s — flagged for Night School",
                reward, domain, felt_sense,
            )

        return result

    async def get_training_pairs(
        self,
        limit: int = 100,
        domain: Optional[str] = None,
        min_score: float = 0.7,
        unused_only: bool = True,
    ) -> list:
        """Retrieve high-quality training pairs for SFT/LoRA."""
        if not self._db_pool:
            return []
        try:
            conditions = ["(c_knowledge + c_quantum_self) / 2.0 >= $1"]
            params = [min_score]
            idx = 2

            if domain:
                conditions.append(f"domain = ${idx}")
                params.append(domain)
                idx += 1

            if unused_only:
                conditions.append("used_for_training = FALSE")

            where = " AND ".join(conditions)

            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""SELECT id, prompt_text, response_text, c_knowledge,
                               c_quantum_self, felt_sense, domain, created_at
                        FROM littlenate_training_pairs
                        WHERE {where}
                        ORDER BY (c_knowledge + c_quantum_self) DESC
                        LIMIT {limit}""",
                    *params,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("LittleNateReward: failed to fetch training pairs: %s", e)
            return []

    async def mark_used(self, pair_ids: list):
        """Mark training pairs as consumed by a training run."""
        if not self._db_pool or not pair_ids:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE littlenate_training_pairs SET used_for_training = TRUE WHERE id = ANY($1::bigint[])",
                    pair_ids,
                )
        except Exception as e:
            logger.warning("LittleNateReward: failed to mark pairs used: %s", e)

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_scored": self._total_scored,
            "pairs_stored": self._pairs_stored,
            "reviews_flagged": self._reviews_flagged,
            "sft_threshold": SFT_THRESHOLD,
            "review_threshold": REVIEW_THRESHOLD,
        }
