"""
HIVE DEFENSE PROTOCOL v3.0 — Payload Entropy Analyzer (Phase 8C: Third Cord)
Shannon entropy profiling for every payload in the Sovereign Swarm.

Design rationale:
    Legitimate Trail Emissions have predictable entropy profiles:
        - Natural language text has entropy ~3.5-5.0 bits/byte
        - Numeric coherence data (JSON floats) has entropy ~4.0-5.5 bits/byte
        - Mixed NL + numeric payloads settle into a characteristic range

    Anomalous payloads have measurably different entropy:
        - Embedded binary data:       ~7.5-8.0 bits/byte (near-maximum)
        - Base64-encoded exfiltration: ~5.8-6.0 bits/byte
        - Encrypted data:             ~7.9-8.0 bits/byte
        - Encoded instructions:       ~6.0-7.0 bits/byte

    By computing Shannon entropy on every payload and tracking a per-entity
    baseline, the analyzer can detect payloads that deviate more than 2
    standard deviations from the entity's historical profile.  This catches:

        1. Data exfiltration (high-entropy encrypted/encoded payloads)
        2. Code injection (binary/instruction-like entropy patterns)
        3. Covert channels (entropy-modulated steganographic payloads)

    The key insight: an attacker CANNOT hide malicious payload content without
    either (a) changing the entropy profile or (b) compressing their data to
    match the expected entropy — which requires knowing the exact expected
    baseline, which only legitimate Fibres have.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    DefconLevel,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.payload_entropy")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Standard deviation multiplier for anomaly detection
ANOMALY_SIGMA: float = 2.0

#: Minimum observations needed before anomaly detection is active
MIN_BASELINE_OBSERVATIONS: int = 20

#: Maximum historical entropy values kept per entity
MAX_HISTORY_PER_ENTITY: int = 5000

#: Expected entropy ranges for known payload types (bits/byte)
KNOWN_ENTROPY_RANGES: Dict[str, Tuple[float, float]] = {
    "natural_language": (3.5, 5.0),
    "numeric_coherence": (4.0, 5.5),
    "mixed_nl_numeric": (3.8, 5.5),
    "json_structured": (4.0, 5.8),
}

#: High-entropy alert threshold (likely binary/encrypted data)
HIGH_ENTROPY_ALERT: float = 7.0

#: Near-zero entropy alert (likely null-padding or repeated data)
LOW_ENTROPY_ALERT: float = 0.5


# =============================================================================
# ENTROPY BASELINE
# =============================================================================

@dataclass
class EntropyBaseline:
    """
    Per-entity entropy baseline tracking.

    Attributes:
        entity_id:       UUID of the tracked entity.
        values:          Rolling history of entropy measurements.
        mean:            Running mean of entropy values.
        std_dev:         Running standard deviation.
        total_payloads:  Total payloads analyzed for this entity.
        anomaly_count:   Total anomalies detected.
        last_updated:    Timestamp of last measurement.
    """
    entity_id: UUID = field(default_factory=uuid4)
    values: List[float] = field(default_factory=list)
    mean: float = 0.0
    std_dev: float = 0.0
    total_payloads: int = 0
    anomaly_count: int = 0
    last_updated: Optional[datetime] = None

    def add_value(self, entropy: float) -> None:
        """
        Add a new entropy measurement and recompute statistics.

        Args:
            entropy: Shannon entropy value (bits/byte).
        """
        self.values.append(entropy)
        self.total_payloads += 1
        self.last_updated = datetime.utcnow()

        # Prune to max history
        if len(self.values) > MAX_HISTORY_PER_ENTITY:
            self.values = self.values[-MAX_HISTORY_PER_ENTITY:]

        # Recompute statistics
        if len(self.values) >= 2:
            self.mean = statistics.mean(self.values)
            self.std_dev = statistics.stdev(self.values)
        elif len(self.values) == 1:
            self.mean = self.values[0]
            self.std_dev = 0.0

    @property
    def has_sufficient_data(self) -> bool:
        """Whether enough observations exist for reliable anomaly detection."""
        return len(self.values) >= MIN_BASELINE_OBSERVATIONS

    def is_anomalous(self, entropy: float) -> bool:
        """
        Check if an entropy value is anomalous relative to this baseline.

        An observation is anomalous if it falls more than ``ANOMALY_SIGMA``
        standard deviations from the entity's historical mean.

        Args:
            entropy: Shannon entropy value to check.

        Returns:
            True if the value is anomalous (>2σ from mean).
        """
        if not self.has_sufficient_data:
            # With insufficient data, only flag extreme values
            return entropy >= HIGH_ENTROPY_ALERT or entropy <= LOW_ENTROPY_ALERT

        if self.std_dev < 0.001:
            # Near-zero std_dev — any significant deviation is anomalous
            return abs(entropy - self.mean) > 0.5

        deviation = abs(entropy - self.mean) / self.std_dev
        return deviation > ANOMALY_SIGMA


# =============================================================================
# PAYLOAD ENTROPY ANALYZER
# =============================================================================

class PayloadEntropyAnalyzer:
    """
    Shannon entropy profiling for payload anomaly detection.

    Computes the Shannon entropy of every payload and compares against
    per-entity baselines. Payloads that deviate more than 2 standard
    deviations from the entity's historical profile are flagged as
    anomalous and quarantined.

    Legitimate Trail Emissions have characteristic entropy profiles
    (natural language + numeric data). Malicious payloads — encrypted
    exfiltration, binary injections, encoded instructions — have
    measurably different entropy that cannot be hidden without knowing
    the exact expected baseline.

    Integration Points:
        - ContentSentinel    — provides payloads for analysis
        - PostBirthQuarantine — receives quarantine-worthy anomalies
        - DefconController   — escalation on severe anomalies
        - ForensicLogger     — logs all anomaly events

    Usage::

        analyzer = PayloadEntropyAnalyzer(db_pool=pool)

        # Analyze a payload
        score, is_anomalous = await analyzer.analyze_payload(
            entity_id, payload_bytes
        )

    Patent-Pending — Claims 30-56
    """

    def __init__(
        self,
        db_pool=None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        forensic_logger=None,
        defcon_controller=None,
    ) -> None:
        """
        Initialize the Payload Entropy Analyzer.

        Args:
            db_pool:            asyncpg connection pool for persistence.
            event_callback:     Async callback for hive event bus.
            forensic_logger:    ForensicLogger for evidence chain.
            defcon_controller:  DefconController for escalation.
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger
        self._defcon_controller = defcon_controller

        # Per-entity baselines: entity_id → EntropyBaseline
        self._baselines: Dict[UUID, EntropyBaseline] = {}

        # Statistics
        self._total_payloads_analyzed: int = 0
        self._total_anomalies: int = 0

        logger.info("PayloadEntropyAnalyzer initialized")

    # =========================================================================
    # SHANNON ENTROPY COMPUTATION
    # =========================================================================

    @staticmethod
    def compute_shannon_entropy(data: bytes) -> float:
        """
        Compute the Shannon entropy of a byte sequence.

        Shannon entropy measures the average information content per byte.
        For a uniform random distribution over 256 byte values, the maximum
        entropy is 8.0 bits/byte. For a single repeated byte, entropy is 0.0.

        Args:
            data: The byte sequence to analyze.

        Returns:
            Shannon entropy in bits per byte (0.0 – 8.0).
        """
        if not data:
            return 0.0

        length = len(data)
        if length == 0:
            return 0.0

        # Count byte frequencies
        freq: Dict[int, int] = {}
        for byte in data:
            freq[byte] = freq.get(byte, 0) + 1

        # Compute entropy: H = -Σ p(x) log₂ p(x)
        entropy = 0.0
        for count in freq.values():
            if count > 0:
                probability = count / length
                entropy -= probability * math.log2(probability)

        return entropy

    # =========================================================================
    # PAYLOAD ANALYSIS
    # =========================================================================

    async def analyze_payload(
        self,
        entity_id: UUID,
        payload_bytes: bytes,
    ) -> Tuple[float, bool]:
        """
        Analyze a payload's Shannon entropy and compare against the entity baseline.

        Computes the entropy, updates the entity's baseline profile, and
        determines whether the payload is anomalous (>2σ from historical mean).

        Args:
            entity_id:     UUID of the entity that produced the payload.
            payload_bytes: The raw payload bytes to analyze.

        Returns:
            Tuple of (entropy_score, is_anomalous):
                entropy_score: Shannon entropy in bits/byte (0.0-8.0).
                is_anomalous:  True if the entropy deviates >2σ from baseline.
        """
        entropy = self.compute_shannon_entropy(payload_bytes)

        # Get or create baseline
        if entity_id not in self._baselines:
            self._baselines[entity_id] = EntropyBaseline(entity_id=entity_id)

        baseline = self._baselines[entity_id]

        # Check for anomaly BEFORE adding to baseline (so baseline isn't polluted)
        is_anomalous = baseline.is_anomalous(entropy)

        # Update baseline (only with non-anomalous values to prevent poisoning)
        if not is_anomalous:
            baseline.add_value(entropy)
        else:
            baseline.anomaly_count += 1
            baseline.total_payloads += 1

        self._total_payloads_analyzed += 1

        if is_anomalous:
            self._total_anomalies += 1
            await self._handle_anomaly(entity_id, entropy, payload_bytes, baseline)

        logger.debug(
            "Payload entropy: entity=%s entropy=%.4f mean=%.4f "
            "std=%.4f anomalous=%s (payloads=%d)",
            entity_id, entropy, baseline.mean, baseline.std_dev,
            is_anomalous, baseline.total_payloads,
        )

        return entropy, is_anomalous

    # =========================================================================
    # ANOMALY HANDLING
    # =========================================================================

    async def _handle_anomaly(
        self,
        entity_id: UUID,
        entropy: float,
        payload_bytes: bytes,
        baseline: EntropyBaseline,
    ) -> None:
        """
        Handle an entropy anomaly detection.

        Args:
            entity_id:     UUID of the offending entity.
            entropy:       The anomalous entropy value.
            payload_bytes: The raw payload (for forensics — NOT logged in full).
            baseline:      The entity's current baseline.
        """
        deviation_sigma = 0.0
        if baseline.std_dev > 0.001:
            deviation_sigma = abs(entropy - baseline.mean) / baseline.std_dev

        # Classify the anomaly type
        anomaly_type = "unknown"
        if entropy >= 7.5:
            anomaly_type = "likely_encrypted_or_binary"
        elif entropy >= 6.5:
            anomaly_type = "likely_encoded_data"
        elif entropy >= 5.8:
            anomaly_type = "possible_base64_exfiltration"
        elif entropy <= LOW_ENTROPY_ALERT:
            anomaly_type = "suspicious_low_entropy"
        else:
            anomaly_type = "baseline_deviation"

        logger.warning(
            "⚠ ENTROPY ANOMALY: entity=%s entropy=%.4f mean=%.4f "
            "deviation=%.1fσ type=%s payload_size=%d",
            entity_id, entropy, baseline.mean,
            deviation_sigma, anomaly_type, len(payload_bytes),
        )

        # Log to forensic chain (payload hash, NOT full payload)
        if self._forensic_logger:
            import hashlib
            payload_hash = hashlib.sha256(payload_bytes).hexdigest()
            try:
                await self._forensic_logger.log_event(
                    event_type="payload_entropy_anomaly",
                    source_entity=str(entity_id),
                    evidence={
                        "entropy": entropy,
                        "baseline_mean": baseline.mean,
                        "baseline_std_dev": baseline.std_dev,
                        "deviation_sigma": deviation_sigma,
                        "anomaly_type": anomaly_type,
                        "payload_size": len(payload_bytes),
                        "payload_hash": payload_hash,
                        "entity_total_payloads": baseline.total_payloads,
                        "entity_anomaly_count": baseline.anomaly_count,
                    },
                )
            except Exception as exc:
                logger.error("Forensic log failed: %s", exc)

        # Escalate if entity has repeated anomalies
        if baseline.anomaly_count >= 3 and self._defcon_controller:
            try:
                await self._defcon_controller.escalate(
                    DefconLevel.SUBSTANTIAL,
                    f"Repeated entropy anomalies from entity {entity_id}: "
                    f"{baseline.anomaly_count} anomalies, latest={anomaly_type}",
                )
            except Exception as exc:
                logger.error("DEFCON escalation failed: %s", exc)

        # Broadcast event
        await self._broadcast_event(
            "hive.payload.entropy_anomaly",
            {
                "entity_id": str(entity_id),
                "entropy": entropy,
                "baseline_mean": baseline.mean,
                "deviation_sigma": deviation_sigma,
                "anomaly_type": anomaly_type,
                "payload_size": len(payload_bytes),
                "entity_anomaly_count": baseline.anomaly_count,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # =========================================================================
    # BASELINE QUERIES
    # =========================================================================

    async def get_entity_baseline(
        self,
        entity_id: UUID,
    ) -> Dict[str, Any]:
        """
        Return the entropy baseline profile for an entity.

        Args:
            entity_id: UUID of the entity.

        Returns:
            Baseline profile dict.
        """
        baseline = self._baselines.get(entity_id)
        if baseline is None:
            return {
                "entity_id": str(entity_id),
                "status": "no_data",
            }

        return {
            "entity_id": str(entity_id),
            "mean": round(baseline.mean, 4),
            "std_dev": round(baseline.std_dev, 4),
            "total_payloads": baseline.total_payloads,
            "anomaly_count": baseline.anomaly_count,
            "has_sufficient_data": baseline.has_sufficient_data,
            "observation_count": len(baseline.values),
            "last_updated": (
                baseline.last_updated.isoformat()
                if baseline.last_updated
                else None
            ),
            "anomaly_threshold_low": round(
                baseline.mean - ANOMALY_SIGMA * baseline.std_dev, 4,
            ) if baseline.has_sufficient_data else None,
            "anomaly_threshold_high": round(
                baseline.mean + ANOMALY_SIGMA * baseline.std_dev, 4,
            ) if baseline.has_sufficient_data else None,
        }

    # =========================================================================
    # ADMIN
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        entities_with_data = sum(
            1 for b in self._baselines.values() if b.has_sufficient_data
        )
        return {
            "total_payloads_analyzed": self._total_payloads_analyzed,
            "total_anomalies": self._total_anomalies,
            "anomaly_rate": (
                f"{self._total_anomalies / self._total_payloads_analyzed * 100:.2f}%"
                if self._total_payloads_analyzed > 0
                else "N/A"
            ),
            "entities_tracked": len(self._baselines),
            "entities_with_sufficient_data": entities_with_data,
            "anomaly_sigma": ANOMALY_SIGMA,
            "min_baseline_observations": MIN_BASELINE_OBSERVATIONS,
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def persist_baselines(self) -> int:
        """
        Persist all entity baselines to the database.

        Returns:
            Number of baselines persisted.
        """
        if not self._db_pool:
            return 0

        persisted = 0
        try:
            async with self._db_pool.acquire() as conn:
                for entity_id, baseline in self._baselines.items():
                    if not baseline.values:
                        continue
                    await conn.execute(
                        """
                        INSERT INTO entropy_baselines (
                            entity_id, mean_entropy, std_dev_entropy,
                            total_payloads, anomaly_count, last_updated
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (entity_id) DO UPDATE SET
                            mean_entropy = EXCLUDED.mean_entropy,
                            std_dev_entropy = EXCLUDED.std_dev_entropy,
                            total_payloads = EXCLUDED.total_payloads,
                            anomaly_count = EXCLUDED.anomaly_count,
                            last_updated = EXCLUDED.last_updated
                        """,
                        entity_id,
                        baseline.mean,
                        baseline.std_dev,
                        baseline.total_payloads,
                        baseline.anomaly_count,
                        baseline.last_updated,
                    )
                    persisted += 1

            logger.info("Persisted %d entropy baselines", persisted)
        except Exception as exc:
            logger.error("Failed to persist entropy baselines: %s", exc)

        return persisted

    async def load_from_db(self) -> int:
        """
        Load entity baselines from the database on startup.

        Note: Only aggregate statistics are restored; per-observation
        history is not persisted.

        Returns:
            Number of baselines loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT entity_id, mean_entropy, std_dev_entropy,
                           total_payloads, anomaly_count, last_updated
                    FROM entropy_baselines
                    """
                )

            loaded = 0
            for row in rows:
                entity_id = row["entity_id"]
                baseline = EntropyBaseline(
                    entity_id=entity_id,
                    mean=row["mean_entropy"] or 0.0,
                    std_dev=row["std_dev_entropy"] or 0.0,
                    total_payloads=row["total_payloads"] or 0,
                    anomaly_count=row["anomaly_count"] or 0,
                    last_updated=row["last_updated"],
                )
                self._baselines[entity_id] = baseline
                loaded += 1

            logger.info("Loaded %d entropy baselines from database", loaded)
            return loaded

        except Exception as exc:
            logger.error("Failed to load entropy baselines: %s", exc)
            return 0

    # =========================================================================
    # EVENT BUS
    # =========================================================================

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast an event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "Event callback failed for topic %s: %s", topic, exc,
                )
