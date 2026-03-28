"""
SOVEREIGN SWARM — Cultural Incoherence Detector

Patent Claim 17: Bridges internal therapeutic coherence measurements with external
cultural signals from SkyEye to detect cultural coherence gaps.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class CulturalIncoherenceDetector:
    """
    Patent Claim 17: Bridges internal therapeutic coherence measurements
    with external cultural signals from SkyEye to detect cultural coherence gaps.
    """

    SEVERITY_ALIGNED = "aligned"
    SEVERITY_MINOR = "minor_gap"
    SEVERITY_SIGNIFICANT = "significant_gap"
    SEVERITY_CRITICAL = "critical_gap"

    def __init__(
        self,
        coherence_engine: Optional[Any] = None,
        skyeye_service: Optional[Any] = None,
    ) -> None:
        """
        Initialize CulturalIncoherenceDetector.

        Args:
            coherence_engine: CoherenceEngine for internal community coherence.
            skyeye_service: Service for external cultural signals (sentiment, discourse).
        """
        self._coherence = coherence_engine
        self._skyeye = skyeye_service

    def classify_gap_severity(self, gap: float) -> str:
        """
        Classify gap magnitude into severity bands.

        Args:
            gap: Absolute difference between internal and external coherence (0.0–1.0).

        Returns:
            Severity: "aligned" | "minor_gap" | "significant_gap" | "critical_gap"
        """
        gap = abs(gap)
        if gap < 0.1:
            return self.SEVERITY_ALIGNED
        if gap < 0.3:
            return self.SEVERITY_MINOR
        if gap < 0.5:
            return self.SEVERITY_SIGNIFICANT
        return self.SEVERITY_CRITICAL

    async def _get_internal_coherence(self, community_id: str) -> float:
        """Get internal coherence for community from coherence engine."""
        if not self._coherence:
            logger.debug("cultural_incoherence_no_engine", community_id=community_id)
            return 0.5  # neutral default

        try:
            measurement = await self._coherence.measure_community(community_id=community_id)
            return float(measurement.score)
        except Exception as e:
            logger.warning("cultural_incoherence_internal_failed", community_id=community_id, error=str(e))
            return 0.5

    async def _get_external_signal(self, community_id: str) -> float:
        """Get external cultural signal from SkyEye or fallback."""
        if self._skyeye:
            try:
                method = getattr(self._skyeye, "get_cultural_signal", None) or getattr(
                    self._skyeye, "get_external_sentiment", None
                )
                if method:
                    result = method(community_id)
                    if asyncio.iscoroutine(result):
                        result = await result
                    if isinstance(result, (int, float)):
                        return max(0.0, min(1.0, float(result)))
                    if isinstance(result, dict) and "score" in result:
                        return max(0.0, min(1.0, float(result["score"])))
            except Exception as e:
                logger.warning("cultural_incoherence_external_failed", community_id=community_id, error=str(e))

        # Fallback: query DB if coherence engine has db_pool
        if self._coherence and getattr(self._coherence, "db_pool", None):
            try:
                async with self._coherence.db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT COALESCE(AVG(
                            CASE
                                WHEN sentiment = 'positive' THEN 0.8
                                WHEN sentiment = 'neutral' THEN 0.5
                                WHEN sentiment = 'negative' THEN 0.2
                                ELSE 0.5
                            END
                        ), 0.5) AS score
                        FROM skyeye_activity
                        WHERE created_at > NOW() - INTERVAL '7 days'
                    """)
                    if row and row.get("score") is not None:
                        return max(0.0, min(1.0, float(row["score"])))
            except Exception as e:
                logger.debug("cultural_incoherence_db_fallback_failed", error=str(e))

        return 0.5  # neutral default

    def _build_recommendations(self, gap_severity: str, internal: float, external: float) -> List[str]:
        """Generate recommendations based on gap analysis."""
        recs: List[str] = []
        if gap_severity == self.SEVERITY_ALIGNED:
            recs.append("Internal and external coherence are well aligned; maintain current approach.")
        elif gap_severity == self.SEVERITY_MINOR:
            recs.append("Monitor cultural signals for emerging trends.")
            recs.append("Consider light-touch community outreach to bridge minor gap.")
        elif gap_severity == self.SEVERITY_SIGNIFICANT:
            recs.append("Significant gap detected. Review therapeutic messaging alignment.")
            recs.append("Engage SkyEye discourse analysis for targeted cultural insights.")
            recs.append("Consider community workshops or cultural bridge initiatives.")
        else:
            recs.append("Critical gap requires immediate attention.")
            recs.append("Convene cultural coherence review with Sovereign Mind.")
            recs.append("Audit therapeutic content for external cultural resonance.")
            if internal > external:
                recs.append("Internal coherence exceeds external—consider outreach to broaden cultural impact.")
            else:
                recs.append("External signals exceed internal—strengthen therapeutic coherence foundations.")
        return recs

    async def compute_cultural_gap(self, community_id: str) -> Dict[str, Any]:
        """
        Compute cultural coherence gap for a community.

        Args:
            community_id: Community identifier.

        Returns:
            Dict with community_id, internal_coherence, external_signal, gap,
            gap_severity, recommendations.
        """
        internal = await self._get_internal_coherence(community_id)
        external = await self._get_external_signal(community_id)
        gap = abs(internal - external)
        severity = self.classify_gap_severity(gap)
        recommendations = self._build_recommendations(severity, internal, external)

        result = {
            "community_id": community_id,
            "internal_coherence": round(internal, 4),
            "external_signal": round(external, 4),
            "gap": round(gap, 4),
            "gap_severity": severity,
            "recommendations": recommendations,
        }
        logger.info(
            "cultural_gap_computed",
            community_id=community_id,
            gap=gap,
            severity=severity,
        )
        return result

    async def scan_all_communities(self) -> List[Dict[str, Any]]:
        """
        Scan all communities and return cultural gap results.

        Returns:
            List of gap result dicts.
        """
        community_ids: List[str] = ["default"]

        if self._coherence and getattr(self._coherence, "db_pool", None):
            try:
                async with self._coherence.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT DISTINCT community_id
                        FROM coherence_measurements
                        WHERE community_id IS NOT NULL AND community_id != ''
                        ORDER BY community_id
                    """)
                    community_ids = [str(r["community_id"]) for r in rows if r.get("community_id")]
                    if not community_ids:
                        community_ids = ["default"]
            except Exception as e:
                logger.warning("cultural_scan_list_communities_failed", error=str(e))

        results: List[Dict[str, Any]] = []
        for cid in community_ids:
            try:
                gap_result = await self.compute_cultural_gap(cid)
                results.append(gap_result)
            except Exception as e:
                logger.warning("cultural_scan_community_failed", community_id=cid, error=str(e))
                results.append({
                    "community_id": cid,
                    "internal_coherence": 0.0,
                    "external_signal": 0.0,
                    "gap": 0.0,
                    "gap_severity": "unknown",
                    "recommendations": ["Scan failed; retry or investigate."],
                })

        return results
