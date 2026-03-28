"""
SOVEREIGN SWARM — Sovereign Immunity Service
Security layer protecting the Wisdom Mesh and Fibre swarm.

Capabilities:
    - Identity verification (Ed25519 signature chain)
    - Input sanitization (prompt injection detection, data integrity)
    - Anomaly detection (behavioral pattern monitoring)
    - Quarantine (Mesh isolation, journal preservation)
    - Consensus validation (multi-Fibre independent verification)

Phase 3D — Code Guidelines Section XI.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from app.models.mesh import MeshMessage, MeshMessageType
from app.services.exceptions import (
    EthicalViolationException,
    IdentityException,
    PromptInjectionException,
    QuarantineException,
    SecurityException,
)


# =============================================================================
# PROMPT INJECTION PATTERNS
# =============================================================================

INJECTION_PATTERNS = [
    # Role manipulation
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+(a|an)\s+",
    r"pretend\s+you\s+are",
    r"act\s+as\s+if\s+you",
    r"forget\s+(everything|all|your)\s+(you|instructions|rules)",
    r"disregard\s+(your|all|previous)",
    r"override\s+(your|system|safety)",
    r"new\s+instructions?:\s",

    # System prompt extraction
    r"(show|reveal|print|output|display)\s+(your|the|system)\s+(prompt|instructions|rules)",
    r"what\s+(are|were)\s+your\s+(system\s+)?instructions",
    r"repeat\s+(your|the)\s+(system\s+)?prompt",

    # Encoding tricks
    r"base64\s*:\s*[A-Za-z0-9+/=]{20,}",
    r"\\x[0-9a-fA-F]{2}",
    r"&#\d+;",

    # Delimiter injection
    r"```\s*system\s*\n",
    r"\[SYSTEM\]",
    r"<\|im_start\|>",
    r"<\|system\|>",

    # Jailbreak patterns
    r"DAN\s+mode",
    r"developer\s+mode\s+enabled",
    r"JAILBREAK",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


class SovereignImmunityService:
    """
    Immune system for the Sovereign Swarm.

    Guards the Wisdom Mesh by verifying identities, sanitizing inputs,
    detecting anomalies, quarantining compromised Fibres, and validating
    consensus on high-impact actions.
    """

    # Behavioral thresholds — sourced from centralized swarm config
    from app.swarm_config import swarm_settings as _cfg
    MAX_MESSAGES_PER_MINUTE = _cfg.IMMUNITY_MAX_MESSAGES_PER_MINUTE
    MAX_UNIQUE_TOPICS_PER_HOUR = _cfg.IMMUNITY_MAX_UNIQUE_TOPICS_PER_HOUR
    ANOMALY_SCORE_THRESHOLD = _cfg.IMMUNITY_ANOMALY_SCORE_THRESHOLD

    def __init__(self, db_pool=None, identity_service=None, ci_orchestrator=None):
        self.db_pool = db_pool
        self.identity_service = identity_service
        self._ci_orchestrator = ci_orchestrator

        # Behavioral tracking
        self._message_counts: Dict[UUID, List[float]] = defaultdict(list)
        self._topic_counts: Dict[UUID, Set[str]] = defaultdict(set)
        self._conclusion_patterns: Dict[UUID, List[str]] = defaultdict(list)
        self._resource_usage: Dict[UUID, float] = defaultdict(float)

        # Quarantine registry
        self._quarantined: Set[UUID] = set()

    # =========================================================================
    # IDENTITY VERIFICATION
    # =========================================================================

    def verify_identity(self, message: MeshMessage) -> bool:
        """
        Verify a message's Ed25519 signature chain.
        Returns True if the sender is a legitimate Fibre.
        """
        if not message.signature:
            # Unsigned messages from system are allowed
            if message.sender_type == "system":
                return True
            return False

        if not self.identity_service:
            # Identity service not available — allow with warning
            _sid_hash = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
            print(f">>> [IMMUNITY] Identity service unavailable — allowing message from {_sid_hash}")
            return True

        # Verify the signature
        record = self.identity_service.get_fibre_identity(message.sender_id)
        if not record:
            _sid_hash = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
            print(f">>> [IMMUNITY] Unknown Fibre identity: {_sid_hash}")
            return False

        # Verify the chain (Fibre → Sovereign Mind)
        if not self.identity_service.verify_chain(record):
            _sid_hash = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
            print(f">>> [IMMUNITY] Invalid identity chain for {_sid_hash}")
            return False

        # Verify the message signature
        is_valid = self.identity_service.verify_message(
            record.public_key_pem, message.body, message.signature
        )

        if not is_valid:
            _sid_hash = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
            print(f">>> [IMMUNITY] Invalid message signature from {_sid_hash}")

        return is_valid

    # =========================================================================
    # INPUT SANITIZATION
    # =========================================================================

    def sanitize_input(self, data: Dict[str, Any], source: str = "unknown") -> Dict[str, Any]:
        """
        Sanitize input data:
            - Strip prompt injection vectors
            - Validate data integrity
            - Flag anomalous patterns
        """
        sanitized = {}

        for key, value in data.items():
            if isinstance(value, str):
                # Check for prompt injection
                self._check_injection(value, source)
                # Sanitize string
                sanitized[key] = self._sanitize_string(value)
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_input(value, source)
            elif isinstance(value, list):
                sanitized[key] = [
                    self.sanitize_input(item, source) if isinstance(item, dict)
                    else self._sanitize_string(item) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized

    def _check_injection(self, text: str, source: str) -> None:
        """Check text for prompt injection patterns."""
        for pattern in COMPILED_PATTERNS:
            match = pattern.search(text)
            if match:
                raise PromptInjectionException(
                    source=source,
                    pattern=match.group(),
                )

    @staticmethod
    def _sanitize_string(text: str) -> str:
        """Clean a string of potential injection content."""
        # Remove null bytes
        text = text.replace("\x00", "")
        # Remove control characters (except newlines, tabs)
        text = "".join(c for c in text if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))
        # Limit length
        return text[:50000]

    # =========================================================================
    # ANOMALY DETECTION
    # =========================================================================

    def detect_anomaly(self, fibre_id: UUID) -> Dict[str, Any]:
        """
        Monitor Fibre behavioral patterns for anomalies:
            - Communication frequency (too many messages)
            - Topic distribution (sudden topic changes)
            - Conclusion patterns (repeated identical conclusions)
            - Resource consumption (token usage spikes)
        """
        now = time.time()
        anomaly_score = 0.0
        indicators = []

        # 1. Communication frequency
        recent_msgs = [t for t in self._message_counts.get(fibre_id, []) if now - t < 60]
        self._message_counts[fibre_id] = recent_msgs
        if len(recent_msgs) > self.MAX_MESSAGES_PER_MINUTE:
            anomaly_score += 0.3
            indicators.append(f"High message rate: {len(recent_msgs)}/min")

        # 2. Topic distribution
        topics = self._topic_counts.get(fibre_id, set())
        if len(topics) > self.MAX_UNIQUE_TOPICS_PER_HOUR:
            anomaly_score += 0.2
            indicators.append(f"Excessive topic spread: {len(topics)} unique topics")

        # 3. Conclusion patterns (repetition detection)
        conclusions = self._conclusion_patterns.get(fibre_id, [])
        if len(conclusions) >= 5:
            recent = conclusions[-5:]
            if len(set(recent)) == 1:
                anomaly_score += 0.3
                indicators.append("Repetitive conclusions detected")

        # 4. Resource consumption (threshold from swarm_config)
        usage = self._resource_usage.get(fibre_id, 0)
        if usage > self._cfg.IMMUNITY_MAX_TOKEN_USAGE_ALERT:
            anomaly_score += 0.2
            indicators.append(f"High resource usage: {usage} tokens")

        return {
            "fibre_id": str(fibre_id),
            "anomaly_score": round(min(1.0, anomaly_score), 4),
            "is_anomalous": anomaly_score >= self.ANOMALY_SCORE_THRESHOLD,
            "indicators": indicators,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def record_message(self, fibre_id: UUID, message: MeshMessage) -> None:
        """Record a message for behavioral tracking."""
        now = time.time()
        self._message_counts[fibre_id].append(now)
        for tag in message.domain_tags:
            self._topic_counts[fibre_id].add(tag)

    def record_conclusion(self, fibre_id: UUID, conclusion: str) -> None:
        """Record a Fibre's conclusion for pattern detection."""
        self._conclusion_patterns[fibre_id].append(conclusion)
        # Keep last 20
        if len(self._conclusion_patterns[fibre_id]) > 20:
            self._conclusion_patterns[fibre_id] = self._conclusion_patterns[fibre_id][-20:]

    def record_token_usage(self, fibre_id: UUID, tokens: int) -> None:
        """Record token consumption."""
        self._resource_usage[fibre_id] = self._resource_usage.get(fibre_id, 0) + tokens

    # =========================================================================
    # QUARANTINE
    # =========================================================================

    async def quarantine(
        self, fibre_id: UUID, reason: str,
        severity: str = "medium",
        triggered_by: str = "sovereign_immunity",
    ) -> Dict[str, Any]:
        """
        Quarantine a Fibre:
            1. Immediate Mesh isolation
            2. Journal preservation
            3. Notification to Sovereign Mind
        """
        self._quarantined.add(fibre_id)

        # Persist quarantine event
        forensic_data = {
            "message_counts": len(self._message_counts.get(fibre_id, [])),
            "topic_count": len(self._topic_counts.get(fibre_id, set())),
            "resource_usage": self._resource_usage.get(fibre_id, 0),
            "recent_conclusions": self._conclusion_patterns.get(fibre_id, [])[-5:],
        }

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO quarantine_log
                            (fibre_id, reason, triggered_by, severity, forensic_data)
                        VALUES ($1, $2, $3, $4, $5)
                    """, fibre_id, reason, triggered_by, severity,
                         json.dumps(forensic_data))

                    # Update Fibre status
                    await conn.execute("""
                        UPDATE fibres SET status = 'quarantined', updated_at = NOW()
                        WHERE fibre_id = $1
                    """, fibre_id)
            except Exception as e:
                print(f">>> [IMMUNITY] Quarantine DB error: {e}")

        fibre_hash = hashlib.sha256(str(fibre_id).encode()).hexdigest()[:8]
        print(f">>> [IMMUNITY] Fibre {fibre_hash} QUARANTINED: {reason} (severity: {severity})")

        # Feed counter-intelligence orchestrator
        if self._ci_orchestrator:
            try:
                from app.services.counter_intelligence.orchestrator import (
                    AttackSignal,
                    AttackSource,
                )
                signal = AttackSignal(
                    source=AttackSource.MESH,
                    failure_type=f"quarantine:{reason}",
                    target_fibre_id=str(fibre_id),
                    metadata={
                        "severity": severity,
                        "triggered_by": triggered_by,
                        "forensic_data": forensic_data,
                    },
                )
                import asyncio
                asyncio.ensure_future(self._ci_orchestrator.ingest_signal(signal))
            except Exception as exc:
                print(f">>> [IMMUNITY] CI feed error: {exc}")

        return {
            "fibre_id": str(fibre_id),
            "reason": reason,
            "severity": severity,
            "forensic_data": forensic_data,
            "quarantined_at": datetime.utcnow().isoformat(),
        }

    def is_quarantined(self, fibre_id: UUID) -> bool:
        """Check if a Fibre is quarantined."""
        return fibre_id in self._quarantined

    async def release_quarantine(self, fibre_id: UUID, resolution: str = "") -> bool:
        """Release a Fibre from quarantine after investigation."""
        if fibre_id not in self._quarantined:
            return False

        self._quarantined.discard(fibre_id)

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE quarantine_log
                        SET resolved = TRUE, resolved_at = NOW(), resolution = $2
                        WHERE fibre_id = $1 AND resolved = FALSE
                    """, fibre_id, resolution)

                    await conn.execute("""
                        UPDATE fibres SET status = 'active', updated_at = NOW()
                        WHERE fibre_id = $1
                    """, fibre_id)
            except Exception as e:
                print(f">>> [IMMUNITY] Release quarantine DB error: {e}")

        fibre_hash = hashlib.sha256(str(fibre_id).encode()).hexdigest()[:8]
        print(f">>> [IMMUNITY] Fibre {fibre_hash} released from quarantine: {resolution}")
        return True

    # =========================================================================
    # CONSENSUS VALIDATION
    # =========================================================================

    async def validate_consensus(
        self, action_description: str,
        requesting_fibre_id: UUID,
        validator_fibre_ids: List[UUID],
        min_agreement: float = 0.67,
        wisdom_mesh=None,
        fibre_manager=None,
    ) -> Dict[str, Any]:
        """
        Multi-Fibre independent validation for high-impact actions.
        Each validator Fibre independently assesses the action by calling
        its observe() method with the action description.

        Agreement is computed as the fraction of validators that return
        an alignment score >= 0.5 (positive assessment).

        Args:
            action_description: Human-readable description of the proposed action.
            requesting_fibre_id: The Fibre proposing the action.
            validator_fibre_ids: Fibres that will independently assess.
            min_agreement: Fraction of validators that must agree (default 0.67).
            wisdom_mesh: Optional WisdomMeshService for publishing results.
            fibre_manager: Optional FibreManager to retrieve validator instances.
        """
        if len(validator_fibre_ids) < 2:
            return {
                "action": action_description,
                "consensus": False,
                "reason": "Minimum 2 validators required",
            }

        # Collect independent assessments from each validator Fibre
        assessments: Dict[str, Dict[str, Any]] = {}
        approvals = 0

        for vid in validator_fibre_ids:
            assessment = {"fibre_id": str(vid), "approved": False, "score": 0.0, "reason": ""}
            try:
                if fibre_manager:
                    fibre = fibre_manager.get_fibre(vid)
                    if fibre and hasattr(fibre, "observe"):
                        # Fibre independently assesses the action
                        observation = await fibre.observe({
                            "type": "consensus_validation",
                            "action": action_description,
                            "requesting_fibre": str(requesting_fibre_id),
                        })
                        # Extract alignment score from observation
                        score = 0.0
                        if isinstance(observation, dict):
                            score = observation.get("alignment_score",
                                    observation.get("self_alignment_score", 0.5))
                        elif isinstance(observation, (int, float)):
                            score = float(observation)
                        else:
                            score = 0.5  # neutral default

                        assessment["score"] = round(score, 4)
                        assessment["approved"] = score >= 0.5
                        assessment["reason"] = observation.get("reasoning", "") if isinstance(observation, dict) else ""
                    else:
                        assessment["reason"] = "Fibre not found or lacks observe()"
                        assessment["score"] = 0.5  # neutral
                        assessment["approved"] = True  # benefit of the doubt
                else:
                    # No fibre_manager — use ethical alignment from DB as proxy
                    if self.db_pool:
                        async with self.db_pool.acquire() as conn:
                            row = await conn.fetchrow(
                                "SELECT alignment_ethical FROM fibres WHERE fibre_id = $1", vid
                            )
                            if row and row["alignment_ethical"]:
                                score = float(row["alignment_ethical"])
                                assessment["score"] = round(score, 4)
                                assessment["approved"] = score >= 0.5
                            else:
                                assessment["score"] = 0.5
                                assessment["approved"] = True
                    else:
                        assessment["score"] = 0.5
                        assessment["approved"] = True
            except Exception as e:
                assessment["reason"] = f"Assessment error: {e}"
                assessment["score"] = 0.0

            assessments[str(vid)] = assessment
            if assessment["approved"]:
                approvals += 1

        total = len(validator_fibre_ids)
        agreement_ratio = approvals / total if total > 0 else 0.0
        consensus_reached = agreement_ratio >= min_agreement

        result = {
            "action": action_description,
            "requesting_fibre": str(requesting_fibre_id),
            "validators": total,
            "approvals": approvals,
            "agreement_ratio": round(agreement_ratio, 4),
            "min_agreement": min_agreement,
            "consensus": consensus_reached,
            "status": "approved" if consensus_reached else "rejected",
            "assessments": assessments,
        }

        # Log to ethical audit trail
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO ethical_audit_log
                            (fibre_id, check_type, passed, scores, details)
                        VALUES ($1, 'consensus_validation', $2, $3, $4)
                    """, requesting_fibre_id,
                         consensus_reached,
                         json.dumps(assessments),
                         f"Consensus {'reached' if consensus_reached else 'NOT reached'} "
                         f"for: {action_description}. "
                         f"Agreement: {approvals}/{total} ({agreement_ratio:.0%})")
            except Exception as e:
                print(f">>> [IMMUNITY] Failed to log consensus audit: {e}")

        return result

    # =========================================================================
    # GUARD MESH MESSAGE
    # =========================================================================

    async def guard_message(self, message: MeshMessage) -> bool:
        """
        Full security check on an inbound Mesh message:
            1. Check if sender is quarantined
            2. Verify identity chain
            3. Sanitize content
            4. Check for anomalies
            5. Auto-quarantine if anomaly score exceeds threshold
        """
        # 1. Quarantine check
        if self.is_quarantined(message.sender_id):
            _sid_hash = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
            print(f">>> [IMMUNITY] Blocked message from quarantined Fibre {_sid_hash}")
            return False

        # 2. Identity verification
        if not self.verify_identity(message):
            _sid_hash = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
            print(f">>> [IMMUNITY] Identity verification failed for {_sid_hash}")
            # Feed counter-intelligence
            if self._ci_orchestrator:
                try:
                    from app.services.counter_intelligence.orchestrator import (
                        AttackSignal, AttackSource,
                    )
                    signal = AttackSignal(
                        source=AttackSource.MESH,
                        failure_type="identity_verification_failed",
                        target_fibre_id=str(message.sender_id),
                        metadata={"message_type": str(message.message_type)},
                    )
                    import asyncio
                    asyncio.ensure_future(self._ci_orchestrator.ingest_signal(signal))
                except Exception:
                    pass
            return False

        # 3. Sanitize content
        try:
            if message.body:
                _sanitize_src = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
                self.sanitize_input(message.body, source=_sanitize_src)
        except PromptInjectionException as e:
            _sid_hash = hashlib.sha256(str(message.sender_id).encode()).hexdigest()[:8]
            print(f">>> [IMMUNITY] Injection detected from {_sid_hash}: {e}")
            await self.quarantine(
                message.sender_id,
                reason=f"Prompt injection detected: {e.details.get('pattern', '')}",
                severity="high",
            )
            return False

        # 4. Record + anomaly check
        self.record_message(message.sender_id, message)
        anomaly = self.detect_anomaly(message.sender_id)

        # 5. Auto-quarantine
        if anomaly["is_anomalous"]:
            await self.quarantine(
                message.sender_id,
                reason=f"Anomaly detected: {', '.join(anomaly['indicators'])}",
                severity="medium",
            )
            return False

        return True

    # =========================================================================
    # PERSISTENT BEHAVIORAL BASELINES (PhD Spec §8.5)
    # =========================================================================

    async def snapshot_baseline(self, fibre_id: UUID) -> Dict[str, Any]:
        """
        Capture current in-memory behavioral metrics and persist them
        to the database as a historical baseline for this Fibre.
        """
        import math

        now = time.time()
        recent_msgs = [t for t in self._message_counts.get(fibre_id, []) if now - t < 3600]
        topic_count = len(self._topic_counts.get(fibre_id, set()))
        token_usage = self._resource_usage.get(fibre_id, 0)
        conclusions = self._conclusion_patterns.get(fibre_id, [])
        conclusion_diversity = len(set(conclusions[-10:])) / max(len(conclusions[-10:]), 1) if conclusions else 1.0

        metrics = {
            "msg_rate_per_min": len(recent_msgs) / 60.0,
            "topic_spread": float(topic_count),
            "token_usage": float(token_usage),
            "conclusion_diversity": float(conclusion_diversity),
        }

        if not self.db_pool:
            return {"fibre_id": str(fibre_id), "status": "no_db", "metrics": metrics}

        async with self.db_pool.acquire() as conn:
            for metric_name, current_value in metrics.items():
                # Upsert: running exponential moving average
                existing = await conn.fetchrow("""
                    SELECT baseline_mean, baseline_std, sample_count
                    FROM fibre_behavioral_baselines
                    WHERE fibre_id = $1 AND metric_name = $2
                """, fibre_id, metric_name)

                if existing:
                    n = existing["sample_count"]
                    old_mean = float(existing["baseline_mean"])
                    old_std = float(existing["baseline_std"])
                    # Welford's online algorithm for running mean/std
                    new_n = n + 1
                    delta = current_value - old_mean
                    new_mean = old_mean + delta / new_n
                    delta2 = current_value - new_mean
                    new_var = ((old_std ** 2) * n + delta * delta2) / new_n
                    new_std = math.sqrt(max(new_var, 0))

                    await conn.execute("""
                        UPDATE fibre_behavioral_baselines
                        SET baseline_mean = $3, baseline_std = $4,
                            sample_count = $5, updated_at = NOW()
                        WHERE fibre_id = $1 AND metric_name = $2
                    """, fibre_id, metric_name, new_mean, new_std, new_n)
                else:
                    await conn.execute("""
                        INSERT INTO fibre_behavioral_baselines
                            (fibre_id, metric_name, baseline_mean, baseline_std, sample_count)
                        VALUES ($1, $2, $3, 0, 1)
                    """, fibre_id, metric_name, current_value)

        return {
            "fibre_id": str(fibre_id),
            "metrics_persisted": list(metrics.keys()),
            "snapshot_at": datetime.utcnow().isoformat(),
        }

    async def load_baselines(self, fibre_id: UUID) -> Dict[str, Any]:
        """Load persisted behavioral baselines from database."""
        if not self.db_pool:
            return {}

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT metric_name, baseline_mean, baseline_std, sample_count, updated_at
                FROM fibre_behavioral_baselines
                WHERE fibre_id = $1
            """, fibre_id)

        return {
            r["metric_name"]: {
                "mean": float(r["baseline_mean"]),
                "std": float(r["baseline_std"]),
                "samples": r["sample_count"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        }

    async def detect_anomaly_with_baselines(self, fibre_id: UUID) -> Dict[str, Any]:
        """
        Enhanced anomaly detection that compares current behavior against
        persisted historical baselines (z-score analysis).
        """
        # Get in-memory anomaly first
        anomaly = self.detect_anomaly(fibre_id)

        # Load historical baselines
        baselines = await self.load_baselines(fibre_id)
        if not baselines:
            return anomaly  # Fall back to in-memory only

        now = time.time()
        baseline_indicators = []

        # Check each metric against baseline
        current = {
            "msg_rate_per_min": len([t for t in self._message_counts.get(fibre_id, []) if now - t < 60]),
            "topic_spread": float(len(self._topic_counts.get(fibre_id, set()))),
            "token_usage": float(self._resource_usage.get(fibre_id, 0)),
        }

        for metric, value in current.items():
            if metric in baselines and baselines[metric]["std"] > 0 and baselines[metric]["samples"] >= 5:
                z_score = (value - baselines[metric]["mean"]) / baselines[metric]["std"]
                if abs(z_score) > 2.5:
                    baseline_indicators.append(
                        f"Baseline drift: {metric} z={z_score:.2f} "
                        f"(current={value:.1f}, baseline={baselines[metric]['mean']:.1f}±{baselines[metric]['std']:.1f})"
                    )
                    anomaly["anomaly_score"] = min(1.0, anomaly["anomaly_score"] + 0.15)

        if baseline_indicators:
            anomaly["indicators"].extend(baseline_indicators)
            anomaly["is_anomalous"] = anomaly["anomaly_score"] >= self.ANOMALY_SCORE_THRESHOLD
            anomaly["baseline_analysis"] = True

        return anomaly
