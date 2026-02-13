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

    # Behavioral thresholds
    MAX_MESSAGES_PER_MINUTE = 60
    MAX_UNIQUE_TOPICS_PER_HOUR = 50
    ANOMALY_SCORE_THRESHOLD = 0.7

    def __init__(self, db_pool=None, identity_service=None):
        self.db_pool = db_pool
        self.identity_service = identity_service

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
            print(f">>> [IMMUNITY] Identity service unavailable — allowing message from {message.sender_id}")
            return True

        # Verify the signature
        record = self.identity_service.get_fibre_identity(message.sender_id)
        if not record:
            print(f">>> [IMMUNITY] Unknown Fibre identity: {message.sender_id}")
            return False

        # Verify the chain (Fibre → Sovereign Mind)
        if not self.identity_service.verify_chain(record):
            print(f">>> [IMMUNITY] Invalid identity chain for {message.sender_id}")
            return False

        # Verify the message signature
        is_valid = self.identity_service.verify_message(
            record.public_key_pem, message.body, message.signature
        )

        if not is_valid:
            print(f">>> [IMMUNITY] Invalid message signature from {message.sender_id}")

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

        # 4. Resource consumption
        usage = self._resource_usage.get(fibre_id, 0)
        if usage > 50000:  # tokens
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

        print(f">>> [IMMUNITY] Fibre {fibre_id} QUARANTINED: {reason} (severity: {severity})")

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

        print(f">>> [IMMUNITY] Fibre {fibre_id} released from quarantine: {resolution}")
        return True

    # =========================================================================
    # CONSENSUS VALIDATION
    # =========================================================================

    async def validate_consensus(
        self, action_description: str,
        requesting_fibre_id: UUID,
        validator_fibre_ids: List[UUID],
        min_agreement: float = 0.67,
    ) -> Dict[str, Any]:
        """
        Multi-Fibre independent validation for high-impact actions.
        Each validator Fibre independently assesses the action.
        """
        if len(validator_fibre_ids) < 2:
            return {
                "action": action_description,
                "consensus": False,
                "reason": "Minimum 2 validators required",
            }

        # In production, this would dispatch to each validator Fibre
        # and collect independent assessments. For now, log the request.
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO ethical_audit_log
                            (fibre_id, check_type, passed, details)
                        VALUES ($1, 'consensus_request', FALSE, $2)
                    """, requesting_fibre_id,
                         f"Consensus requested for: {action_description}. "
                         f"Validators: {[str(v) for v in validator_fibre_ids]}")
            except Exception:
                pass

        return {
            "action": action_description,
            "requesting_fibre": str(requesting_fibre_id),
            "validators": [str(v) for v in validator_fibre_ids],
            "min_agreement": min_agreement,
            "status": "pending_validation",
        }

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
            print(f">>> [IMMUNITY] Blocked message from quarantined Fibre {message.sender_id}")
            return False

        # 2. Identity verification
        if not self.verify_identity(message):
            print(f">>> [IMMUNITY] Identity verification failed for {message.sender_id}")
            return False

        # 3. Sanitize content
        try:
            if message.body:
                self.sanitize_input(message.body, source=str(message.sender_id))
        except PromptInjectionException as e:
            print(f">>> [IMMUNITY] Injection detected from {message.sender_id}: {e}")
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
