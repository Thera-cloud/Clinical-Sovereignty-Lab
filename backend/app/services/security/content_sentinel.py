"""
HIVE DEFENSE PROTOCOL — Content Sentinel (Phase 8B)
Two-stage payload inspection for all internal hive communications.

The Content Sentinel performs deep payload inspection AFTER identity verification
(Stage 1 = Coherence Gate identity checks; Stage 2 = Content Sentinel payload
inspection).  This ensures that even a perfectly authenticated entity cannot
inject malicious payloads into the hive.

Six Inspection Checks:
    1. Schema Validation      — Does the payload match the expected structure
                                for this entity type?
    2. Unexpected Fields      — Are there any fields that shouldn't exist?
    3. Value Range Validation — Are all values within expected bounds?
    4. Injection Detection    — Executable patterns, base64 blobs, serialized
                                objects, command injection, SQL injection?
    5. Statistical Anomaly    — Does the payload pattern match the entity's
                                historical profile?
    6. Size Anomaly           — Is the payload significantly larger/smaller
                                than the entity's normal payloads?

Five Verdict Levels:
    PASS_CLEAN           — All checks passed, no concerns.
    PASS_WITH_FLAG       — Minor anomalies noted, payload permitted.
    QUARANTINE_FOR_REVIEW — Suspicious enough to hold for human review.
    REJECT_AND_INVESTIGATE — Clear violation, payload rejected, investigation.
    REJECT_AND_ALARM     — Critical threat, payload rejected, ALARM triggered.

Severity Scoring:
    Each check returns a severity level (LOW, MEDIUM, HIGH, CRITICAL).
    Severities are combined using a weighted sum to produce the final verdict.

DEFCON-Adaptive:
    At DEFCON 3 (SUBSTANTIAL) or higher, ALL payloads are inspected
    regardless of source trust level — not just suspicious ones.

Patent-Pending — Claim 38
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    ContentSentinelResult,
    ContentVerdict,
    DefconLevel,
    DefconState,
)

logger = logging.getLogger("hive.content_sentinel")


# =============================================================================
# CONSTANTS & ENUMS
# =============================================================================

class CheckSeverity(str, Enum):
    """Severity level returned by each individual inspection check."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


#: Numeric weights for combining severities into a final score.
SEVERITY_WEIGHTS: Dict[CheckSeverity, float] = {
    CheckSeverity.NONE: 0.0,
    CheckSeverity.LOW: 1.0,
    CheckSeverity.MEDIUM: 3.0,
    CheckSeverity.HIGH: 7.0,
    CheckSeverity.CRITICAL: 15.0,
}

#: Verdict thresholds based on combined severity score.
#: The final score is the sum of all six check weights.
#: Maximum possible score: 6 × 15.0 = 90.0
VERDICT_THRESHOLDS: Dict[ContentVerdict, float] = {
    ContentVerdict.PASS_CLEAN: 0.0,          # score == 0
    ContentVerdict.PASS_WITH_FLAG: 2.0,      # score < 2
    ContentVerdict.QUARANTINE_FOR_REVIEW: 8.0,   # score < 8
    ContentVerdict.REJECT_AND_INVESTIGATE: 20.0,  # score < 20
    ContentVerdict.REJECT_AND_ALARM: 20.0,       # score >= 20
}

#: Known entity types and their expected payload schemas.
#: Keys are entity_type strings; values are sets of expected field names.
EXPECTED_SCHEMAS: Dict[str, Set[str]] = {
    "fibre_observation": {
        "observation_type", "target_entity_id", "data", "confidence",
        "timestamp", "source_fibre_id",
    },
    "trail_emission": {
        "entity_id", "journal_hash", "emission_type", "payload_hash",
        "sequence_number", "timestamp",
    },
    "quakete_transfer": {
        "from_entity_id", "to_entity_id", "energy_amount", "transfer_type",
        "conservation_proof", "timestamp",
    },
    "zefcp_fragment": {
        "fragment_id", "fragment_index", "total_fragments", "encrypted_data",
        "hmac", "timestamp",
    },
    "mesh_message": {
        "sender_id", "recipient_id", "message_type", "content",
        "timestamp",
    },
    "heartbeat_pulse": {
        "entity_id", "birth_coherence_hash", "originator_signature",
        "monotonic_counter", "pulse_data", "identity_chain_root",
    },
}

#: Injection detection patterns — compiled regexes for performance.
_INJECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("sql_injection", re.compile(
        r"(?i)(\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|EXEC|UNION)\b.*"
        r"\b(FROM|INTO|TABLE|SET|WHERE|ALL)\b)",
        re.IGNORECASE | re.DOTALL,
    )),
    ("command_injection", re.compile(
        r"[;&|`$]\s*(cat|ls|rm|wget|curl|nc|bash|sh|python|perl|ruby|eval)\b",
        re.IGNORECASE,
    )),
    ("executable_pattern", re.compile(
        r"(exec\s*\(|eval\s*\(|__import__\s*\(|subprocess|os\.system|"
        r"os\.popen|compile\s*\(|globals\s*\(\)|locals\s*\(\))",
        re.IGNORECASE,
    )),
    ("serialized_object", re.compile(
        r"(pickle\.|marshal\.|shelve\.|yaml\.unsafe_load|"
        r"__reduce__|__getstate__|__setstate__)",
        re.IGNORECASE,
    )),
    ("path_traversal", re.compile(
        r"(\.\./|\.\.\\|%2e%2e%2f|%2e%2e/|\.%2e/|%2e\./)",
        re.IGNORECASE,
    )),
    ("script_injection", re.compile(
        r"(<script|javascript:|on\w+\s*=|<iframe|<object|<embed)",
        re.IGNORECASE,
    )),
]

#: Base64 detection pattern — matches strings that look like base64 blobs
#: (minimum 40 characters of base64 alphabet with optional padding).
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

#: Maximum payload history entries per entity for statistical comparison.
MAX_PAYLOAD_HISTORY: int = 200


# =============================================================================
# CHECK RESULT
# =============================================================================

@dataclass
class CheckResult:
    """
    Result of a single inspection check.

    Attributes:
        check_name: Name of the check (e.g. "schema_validation").
        severity:   Assessed severity level.
        detail:     Human-readable description of the finding.
        passed:     Whether the check was considered a pass.
    """
    check_name: str
    severity: CheckSeverity = CheckSeverity.NONE
    detail: str = "OK"
    passed: bool = True

    def to_dict(self) -> Dict[str, str]:
        """Serialize for API responses."""
        return {
            "severity": self.severity.value,
            "detail": self.detail,
            "passed": str(self.passed).lower(),
        }


# =============================================================================
# ENTITY PAYLOAD PROFILE
# =============================================================================

@dataclass
class EntityPayloadProfile:
    """
    Historical payload profile for an entity, used for statistical comparison.

    Tracks payload sizes, field counts, and structural fingerprints so the
    Content Sentinel can detect anomalous payloads relative to the entity's
    established baseline.
    """
    entity_id: UUID = field(default_factory=uuid4)
    payload_sizes: List[int] = field(default_factory=list)
    field_counts: List[int] = field(default_factory=list)
    payload_hashes: List[str] = field(default_factory=list)
    entity_types_seen: Set[str] = field(default_factory=set)
    total_inspections: int = 0
    last_inspected: Optional[datetime] = None

    @property
    def avg_payload_size(self) -> float:
        """Average payload size in bytes."""
        return statistics.mean(self.payload_sizes) if self.payload_sizes else 0.0

    @property
    def std_payload_size(self) -> float:
        """Standard deviation of payload size."""
        if len(self.payload_sizes) < 2:
            return 0.0
        return statistics.stdev(self.payload_sizes)

    @property
    def avg_field_count(self) -> float:
        """Average number of fields per payload."""
        return statistics.mean(self.field_counts) if self.field_counts else 0.0

    def record_payload(self, payload_json: str, field_count: int) -> None:
        """
        Record a payload observation.

        Args:
            payload_json: JSON-serialized payload string.
            field_count:  Number of top-level fields in the payload.
        """
        size = len(payload_json.encode("utf-8"))
        self.payload_sizes.append(size)
        self.field_counts.append(field_count)
        self.payload_hashes.append(
            hashlib.sha256(payload_json.encode()).hexdigest()[:16]
        )
        self.total_inspections += 1
        self.last_inspected = datetime.utcnow()

        # Trim to max history
        if len(self.payload_sizes) > MAX_PAYLOAD_HISTORY:
            self.payload_sizes = self.payload_sizes[-MAX_PAYLOAD_HISTORY:]
            self.field_counts = self.field_counts[-MAX_PAYLOAD_HISTORY:]
            self.payload_hashes = self.payload_hashes[-MAX_PAYLOAD_HISTORY:]


# =============================================================================
# CONTENT SENTINEL
# =============================================================================

class ContentSentinel:
    """
    Two-stage payload inspection engine for hive communications.

    Stage 1 (identity verification) is handled by the Coherence Gate.
    Stage 2 (payload inspection) is handled by this class.  All payloads
    that pass the Coherence Gate are forwarded here for deep inspection.

    At DEFCON 3 (SUBSTANTIAL) or higher, ALL payloads are inspected
    regardless of the entity's trust level.

    Integration points:
        - CoherenceGate   — forwards verified payloads for Stage 2 inspection
        - ForensicLogger  — verdicts persisted to immutable chain
        - CuriosityProtocol — QUARANTINE and REJECT verdicts escalate curiosity
        - DefconManager   — provides current DEFCON for adaptive behavior
        - Hive event bus  — publishes payload anomaly events

    Usage::

        sentinel = ContentSentinel(db_pool=pool)
        result = await sentinel.inspect_payload(
            entity_id=entity_id,
            payload={"observation_type": "mood", "data": {...}},
            entity_type="fibre_observation",
        )

    Patent-Pending — Claim 38.
    """

    def __init__(
        self,
        db_pool=None,
        forensic_logger=None,
        event_bus=None,
        defcon_state: Optional[DefconState] = None,
    ) -> None:
        """
        Initialize the Content Sentinel.

        Args:
            db_pool:         asyncpg connection pool for persistence.
            forensic_logger: ForensicLogger instance for immutable evidence chain.
            event_bus:       Hive event bus for publishing payload anomaly events.
            defcon_state:    Current DEFCON state.  At DEFCON 3+, all payloads
                             are inspected regardless of trust level.
        """
        self.db_pool = db_pool
        self._forensic_logger = forensic_logger
        self._event_bus = event_bus
        self._defcon_state: DefconState = defcon_state or DefconState()

        # Per-entity payload profiles for statistical comparison
        self._entity_profiles: Dict[UUID, EntityPayloadProfile] = {}

        # Custom schema overrides (loaded from DB or configured at runtime)
        self._custom_schemas: Dict[str, Set[str]] = {}

        logger.info(
            ">>> [SENTINEL] Content Sentinel initialized (DEFCON=%d)",
            self._defcon_state.level.value,
        )

    # =========================================================================
    # DEFCON
    # =========================================================================

    def update_defcon(self, defcon_state: DefconState) -> None:
        """
        Update the current DEFCON state.

        At DEFCON 3+, the Content Sentinel switches to inspecting ALL payloads.

        Args:
            defcon_state: The new DEFCON state.
        """
        self._defcon_state = defcon_state
        logger.info(
            ">>> [SENTINEL] DEFCON updated: level=%d (full_inspection=%s)",
            defcon_state.level.value,
            defcon_state.level.value <= DefconLevel.SUBSTANTIAL.value,
        )

    @property
    def full_inspection_mode(self) -> bool:
        """Whether all payloads should be inspected (DEFCON 3+)."""
        return self._defcon_state.level.value <= DefconLevel.SUBSTANTIAL.value

    # =========================================================================
    # PROFILE MANAGEMENT
    # =========================================================================

    def _get_profile(self, entity_id: UUID) -> EntityPayloadProfile:
        """Get or create an entity's payload profile."""
        if entity_id not in self._entity_profiles:
            self._entity_profiles[entity_id] = EntityPayloadProfile(
                entity_id=entity_id
            )
        return self._entity_profiles[entity_id]

    # =========================================================================
    # PRIMARY INSPECTION
    # =========================================================================

    async def inspect_payload(
        self,
        entity_id: UUID,
        payload: Dict[str, Any],
        entity_type: str,
    ) -> ContentSentinelResult:
        """
        Perform Stage 2 deep inspection on a payload.

        Runs all six inspection checks and combines the results into a
        final verdict.  The verdict and all check details are persisted
        for forensic audit.

        Args:
            entity_id:   UUID of the entity that sent the payload.
            payload:     The payload dictionary to inspect.
            entity_type: The expected entity/message type (e.g. "fibre_observation").

        Returns:
            ContentSentinelResult with the verdict and check details.
        """
        start_ns = time.monotonic_ns()
        signal_id = uuid4()
        profile = self._get_profile(entity_id)

        # Serialize payload for size/hash calculations
        try:
            payload_json = json.dumps(payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            payload_json = str(payload)

        # Run all six checks
        checks: List[CheckResult] = []

        # 1. Schema validation
        checks.append(self._check_schema(payload, entity_type))

        # 2. Unexpected fields
        checks.append(self._check_unexpected_fields(payload, entity_type))

        # 3. Value range validation
        checks.append(self._check_value_ranges(payload, entity_type))

        # 4. Injection detection
        checks.append(self._check_injection(payload_json))

        # 5. Statistical anomaly
        checks.append(self._check_statistical_anomaly(
            payload, payload_json, profile
        ))

        # 6. Size anomaly
        checks.append(self._check_size_anomaly(payload_json, profile))

        # Compute combined severity score
        total_score = sum(
            SEVERITY_WEIGHTS[c.severity] for c in checks
        )

        # Determine verdict from score
        verdict = self._score_to_verdict(total_score)

        # Compute entropy score (information density metric)
        entropy = self._compute_entropy(payload_json)

        # Detect if injection was found in any check
        injection_detected = any(
            c.check_name == "injection_detection" and not c.passed
            for c in checks
        )

        # Collect unexpected fields
        unexpected_fields = []
        for c in checks:
            if c.check_name == "unexpected_fields" and not c.passed:
                # Extract field names from detail
                unexpected_fields = [
                    f.strip()
                    for f in c.detail.replace("Unexpected fields: ", "").split(",")
                    if f.strip()
                ]

        # Schema validity
        schema_valid = all(
            c.passed for c in checks
            if c.check_name == "schema_validation"
        )

        # Build result
        result = ContentSentinelResult(
            signal_id=signal_id,
            verdict=verdict,
            checks={c.check_name: c.detail for c in checks},
            entropy_score=round(entropy, 4),
            schema_valid=schema_valid,
            unexpected_fields=unexpected_fields,
            injection_detected=injection_detected,
            timestamp=datetime.utcnow(),
        )

        # Record payload in profile for future statistical comparison
        profile.record_payload(payload_json, len(payload))
        profile.entity_types_seen.add(entity_type)

        elapsed_ns = time.monotonic_ns() - start_ns

        # Log based on verdict severity
        if verdict in (ContentVerdict.REJECT_AND_ALARM, ContentVerdict.REJECT_AND_INVESTIGATE):
            logger.warning(
                ">>> [SENTINEL] %s: entity=%s type=%s score=%.1f "
                "entropy=%.3f injection=%s (%d ns)",
                verdict.value.upper(), entity_id, entity_type,
                total_score, entropy, injection_detected, elapsed_ns,
            )
        elif verdict == ContentVerdict.QUARANTINE_FOR_REVIEW:
            logger.info(
                ">>> [SENTINEL] QUARANTINE: entity=%s type=%s score=%.1f (%d ns)",
                entity_id, entity_type, total_score, elapsed_ns,
            )
        else:
            logger.debug(
                ">>> [SENTINEL] %s: entity=%s type=%s (%d ns)",
                verdict.value, entity_id, entity_type, elapsed_ns,
            )

        # Persist verdict
        await self._persist_verdict(entity_id, entity_type, result, total_score)

        # Fire events for non-clean verdicts
        if verdict != ContentVerdict.PASS_CLEAN:
            await self._fire_events(entity_id, entity_type, result, total_score)

        return result

    # =========================================================================
    # INDIVIDUAL CHECKS
    # =========================================================================

    def _check_schema(
        self, payload: Dict[str, Any], entity_type: str
    ) -> CheckResult:
        """
        Check 1: Schema Validation.

        Verifies that the payload contains the expected fields for the
        given entity type.  Missing required fields are flagged.

        Args:
            payload:     The payload dictionary.
            entity_type: The expected entity type.

        Returns:
            CheckResult with severity based on number of missing fields.
        """
        expected = (
            self._custom_schemas.get(entity_type)
            or EXPECTED_SCHEMAS.get(entity_type)
        )
        if not expected:
            # Unknown entity type — can't validate schema
            return CheckResult(
                check_name="schema_validation",
                severity=CheckSeverity.LOW,
                detail=f"Unknown entity type '{entity_type}' — no schema available",
                passed=True,  # Pass with flag since we can't verify
            )

        payload_fields = set(payload.keys())
        missing = expected - payload_fields

        if not missing:
            return CheckResult(
                check_name="schema_validation",
                severity=CheckSeverity.NONE,
                detail="All expected fields present",
                passed=True,
            )

        missing_ratio = len(missing) / len(expected)
        if missing_ratio > 0.5:
            severity = CheckSeverity.HIGH
        elif missing_ratio > 0.25:
            severity = CheckSeverity.MEDIUM
        else:
            severity = CheckSeverity.LOW

        return CheckResult(
            check_name="schema_validation",
            severity=severity,
            detail=f"Missing fields: {', '.join(sorted(missing))}",
            passed=False,
        )

    def _check_unexpected_fields(
        self, payload: Dict[str, Any], entity_type: str
    ) -> CheckResult:
        """
        Check 2: Unexpected Fields.

        Detects fields in the payload that are NOT part of the expected
        schema.  Unexpected fields may indicate payload injection or
        data exfiltration attempts.

        Args:
            payload:     The payload dictionary.
            entity_type: The expected entity type.

        Returns:
            CheckResult with severity based on number and nature of extra fields.
        """
        expected = (
            self._custom_schemas.get(entity_type)
            or EXPECTED_SCHEMAS.get(entity_type)
        )
        if not expected:
            return CheckResult(
                check_name="unexpected_fields",
                severity=CheckSeverity.NONE,
                detail="No schema to compare against",
                passed=True,
            )

        payload_fields = set(payload.keys())
        unexpected = payload_fields - expected

        if not unexpected:
            return CheckResult(
                check_name="unexpected_fields",
                severity=CheckSeverity.NONE,
                detail="No unexpected fields",
                passed=True,
            )

        # Check for suspicious field names
        suspicious_names = {
            f for f in unexpected
            if any(kw in f.lower() for kw in (
                "exec", "eval", "system", "cmd", "shell", "admin",
                "password", "secret", "token", "key", "inject",
                "__", "script", "debug", "internal",
            ))
        }

        if suspicious_names:
            severity = CheckSeverity.HIGH
        elif len(unexpected) > 5:
            severity = CheckSeverity.MEDIUM
        else:
            severity = CheckSeverity.LOW

        return CheckResult(
            check_name="unexpected_fields",
            severity=severity,
            detail=f"Unexpected fields: {', '.join(sorted(unexpected))}",
            passed=False,
        )

    def _check_value_ranges(
        self, payload: Dict[str, Any], entity_type: str
    ) -> CheckResult:
        """
        Check 3: Value Range Validation.

        Verifies that numeric values, string lengths, and nested depths
        are within expected bounds.  Extreme values may indicate buffer
        overflow attempts, numeric injection, or data corruption.

        Args:
            payload:     The payload dictionary.
            entity_type: The expected entity type.

        Returns:
            CheckResult with severity based on range violations found.
        """
        violations: List[str] = []

        def check_value(key: str, value: Any, depth: int = 0) -> None:
            """Recursively check values for range violations."""
            if depth > 10:
                violations.append(f"Excessive nesting depth at '{key}' (>{depth})")
                return

            if isinstance(value, (int, float)):
                # Check for extreme numeric values
                if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                    violations.append(f"NaN/Inf value at '{key}'")
                elif abs(value) > 1e15:
                    violations.append(f"Extreme numeric value at '{key}': {value}")

            elif isinstance(value, str):
                # Check for extreme string lengths
                if len(value) > 100_000:
                    violations.append(
                        f"Extreme string length at '{key}': {len(value)} chars"
                    )
                # Check for null bytes
                if "\x00" in value:
                    violations.append(f"Null byte detected in '{key}'")

            elif isinstance(value, dict):
                if len(value) > 100:
                    violations.append(
                        f"Excessive dict size at '{key}': {len(value)} keys"
                    )
                for k, v in value.items():
                    check_value(f"{key}.{k}", v, depth + 1)

            elif isinstance(value, list):
                if len(value) > 1000:
                    violations.append(
                        f"Excessive list size at '{key}': {len(value)} items"
                    )
                for i, item in enumerate(value[:50]):  # Check first 50
                    check_value(f"{key}[{i}]", item, depth + 1)

        for key, value in payload.items():
            check_value(key, value)

        if not violations:
            return CheckResult(
                check_name="value_range",
                severity=CheckSeverity.NONE,
                detail="All values within expected ranges",
                passed=True,
            )

        if any("Null byte" in v or "NaN/Inf" in v for v in violations):
            severity = CheckSeverity.HIGH
        elif len(violations) > 3:
            severity = CheckSeverity.MEDIUM
        else:
            severity = CheckSeverity.LOW

        return CheckResult(
            check_name="value_range",
            severity=severity,
            detail=f"Range violations: {'; '.join(violations[:5])}",
            passed=False,
        )

    def _check_injection(self, payload_json: str) -> CheckResult:
        """
        Check 4: Injection Detection.

        Scans the serialized payload for executable patterns, base64 blobs,
        serialized objects, command injection, SQL injection, path traversal,
        and script injection.

        Args:
            payload_json: JSON-serialized payload string.

        Returns:
            CheckResult with severity based on injection patterns detected.
        """
        detections: List[Tuple[str, str]] = []

        # Check compiled regex patterns
        for pattern_name, pattern in _INJECTION_PATTERNS:
            match = pattern.search(payload_json)
            if match:
                # Capture a snippet around the match for forensic context
                start = max(0, match.start() - 20)
                end = min(len(payload_json), match.end() + 20)
                snippet = payload_json[start:end]
                detections.append((pattern_name, snippet))

        # Check for large base64 blobs (potential encoded payloads)
        base64_matches = _BASE64_PATTERN.findall(payload_json)
        for b64_match in base64_matches:
            # Try to decode — if it decodes to something suspicious, flag it
            try:
                decoded = base64.b64decode(b64_match)
                # Check if decoded content contains executable patterns
                decoded_str = decoded.decode("utf-8", errors="ignore")
                for pattern_name, pattern in _INJECTION_PATTERNS:
                    if pattern.search(decoded_str):
                        detections.append((
                            f"base64_encoded_{pattern_name}",
                            f"Base64-encoded {pattern_name} detected",
                        ))
                        break
            except Exception:
                pass  # Not valid base64, ignore

            # Flag large base64 blobs regardless
            if len(b64_match) > 200:
                detections.append((
                    "large_base64_blob",
                    f"Large base64 blob ({len(b64_match)} chars)",
                ))

        if not detections:
            return CheckResult(
                check_name="injection_detection",
                severity=CheckSeverity.NONE,
                detail="No injection patterns detected",
                passed=True,
            )

        # Severity based on type and count of detections
        critical_types = {
            "sql_injection", "command_injection", "executable_pattern",
            "serialized_object", "base64_encoded_executable_pattern",
            "base64_encoded_command_injection",
        }
        has_critical = any(d[0] in critical_types for d in detections)

        if has_critical:
            severity = CheckSeverity.CRITICAL
        elif len(detections) > 2:
            severity = CheckSeverity.HIGH
        else:
            severity = CheckSeverity.MEDIUM

        detection_summary = "; ".join(
            f"{d[0]}: {d[1][:60]}" for d in detections[:5]
        )

        return CheckResult(
            check_name="injection_detection",
            severity=severity,
            detail=f"Injection detected: {detection_summary}",
            passed=False,
        )

    def _check_statistical_anomaly(
        self,
        payload: Dict[str, Any],
        payload_json: str,
        profile: EntityPayloadProfile,
    ) -> CheckResult:
        """
        Check 5: Statistical Anomaly.

        Compares the payload's structural characteristics against the entity's
        historical profile.  Significant deviations from established patterns
        indicate potential compromise.

        Args:
            payload:      The payload dictionary.
            payload_json: JSON-serialized payload string.
            profile:      The entity's historical payload profile.

        Returns:
            CheckResult with severity based on statistical deviation.
        """
        # Need at least 10 historical observations for meaningful comparison
        if profile.total_inspections < 10:
            return CheckResult(
                check_name="statistical_anomaly",
                severity=CheckSeverity.NONE,
                detail=(
                    f"Insufficient history ({profile.total_inspections}/10 min) "
                    "— building baseline"
                ),
                passed=True,
            )

        anomalies: List[str] = []
        field_count = len(payload)

        # Check field count deviation
        avg_fields = profile.avg_field_count
        if avg_fields > 0:
            field_deviation = abs(field_count - avg_fields) / max(avg_fields, 1)
            if field_deviation > 2.0:
                anomalies.append(
                    f"Field count anomaly: {field_count} vs avg {avg_fields:.1f} "
                    f"({field_deviation:.1f}x deviation)"
                )

        # Check payload hash uniqueness — if this exact payload structure
        # has never been seen before, and the profile is mature, flag it
        current_hash = hashlib.sha256(payload_json.encode()).hexdigest()[:16]
        if (
            profile.total_inspections > 50
            and current_hash not in profile.payload_hashes
        ):
            # Novel payload structure from a well-profiled entity
            anomalies.append("Novel payload structure (hash not in history)")

        if not anomalies:
            return CheckResult(
                check_name="statistical_anomaly",
                severity=CheckSeverity.NONE,
                detail="Payload matches historical pattern",
                passed=True,
            )

        severity = (
            CheckSeverity.MEDIUM if len(anomalies) > 1
            else CheckSeverity.LOW
        )

        return CheckResult(
            check_name="statistical_anomaly",
            severity=severity,
            detail=f"Statistical anomalies: {'; '.join(anomalies)}",
            passed=False,
        )

    def _check_size_anomaly(
        self, payload_json: str, profile: EntityPayloadProfile
    ) -> CheckResult:
        """
        Check 6: Size Anomaly.

        Detects payloads that are significantly larger or smaller than the
        entity's normal payload size.  Extreme size deviations may indicate
        data exfiltration (unusually large) or probing (unusually small).

        Args:
            payload_json: JSON-serialized payload string.
            profile:      The entity's historical payload profile.

        Returns:
            CheckResult with severity based on size deviation.
        """
        current_size = len(payload_json.encode("utf-8"))

        # Absolute size limits regardless of history
        if current_size > 10_000_000:  # 10 MB
            return CheckResult(
                check_name="size_anomaly",
                severity=CheckSeverity.CRITICAL,
                detail=f"Extreme payload size: {current_size:,} bytes (>10MB)",
                passed=False,
            )

        if current_size > 1_000_000:  # 1 MB
            return CheckResult(
                check_name="size_anomaly",
                severity=CheckSeverity.HIGH,
                detail=f"Very large payload: {current_size:,} bytes (>1MB)",
                passed=False,
            )

        # Need history for relative comparison
        if len(profile.payload_sizes) < 5:
            return CheckResult(
                check_name="size_anomaly",
                severity=CheckSeverity.NONE,
                detail="Insufficient history for size comparison",
                passed=True,
            )

        avg_size = profile.avg_payload_size
        std_size = profile.std_payload_size

        if avg_size == 0:
            return CheckResult(
                check_name="size_anomaly",
                severity=CheckSeverity.NONE,
                detail="No meaningful size baseline",
                passed=True,
            )

        # Z-score-based deviation detection
        if std_size > 0:
            z_score = abs(current_size - avg_size) / std_size
        else:
            # No variance — any deviation is suspicious
            z_score = abs(current_size - avg_size) / max(avg_size, 1) * 10

        if z_score > 10:
            severity = CheckSeverity.HIGH
            detail = (
                f"Extreme size deviation: {current_size:,} bytes "
                f"(avg={avg_size:.0f}, z={z_score:.1f})"
            )
        elif z_score > 5:
            severity = CheckSeverity.MEDIUM
            detail = (
                f"Significant size deviation: {current_size:,} bytes "
                f"(avg={avg_size:.0f}, z={z_score:.1f})"
            )
        elif z_score > 3:
            severity = CheckSeverity.LOW
            detail = (
                f"Minor size deviation: {current_size:,} bytes "
                f"(avg={avg_size:.0f}, z={z_score:.1f})"
            )
        else:
            return CheckResult(
                check_name="size_anomaly",
                severity=CheckSeverity.NONE,
                detail=f"Size within normal range ({current_size:,} bytes, z={z_score:.1f})",
                passed=True,
            )

        return CheckResult(
            check_name="size_anomaly",
            severity=severity,
            detail=detail,
            passed=False,
        )

    # =========================================================================
    # SCORING & VERDICT
    # =========================================================================

    @staticmethod
    def _score_to_verdict(score: float) -> ContentVerdict:
        """
        Map a combined severity score to a ContentVerdict.

        Args:
            score: Combined severity score (sum of check weights).

        Returns:
            ContentVerdict corresponding to the score.
        """
        if score >= VERDICT_THRESHOLDS[ContentVerdict.REJECT_AND_ALARM]:
            return ContentVerdict.REJECT_AND_ALARM
        elif score >= VERDICT_THRESHOLDS[ContentVerdict.QUARANTINE_FOR_REVIEW]:
            return ContentVerdict.REJECT_AND_INVESTIGATE
        elif score >= VERDICT_THRESHOLDS[ContentVerdict.PASS_WITH_FLAG]:
            return ContentVerdict.QUARANTINE_FOR_REVIEW
        elif score > 0:
            return ContentVerdict.PASS_WITH_FLAG
        return ContentVerdict.PASS_CLEAN

    @staticmethod
    def _compute_entropy(data: str) -> float:
        """
        Compute Shannon entropy of a string.

        Higher entropy indicates more random / encrypted content.
        Extremely high entropy in a normal payload may indicate
        encrypted or obfuscated malicious content.

        Args:
            data: The string to compute entropy for.

        Returns:
            Shannon entropy in bits per character.
        """
        if not data:
            return 0.0

        freq: Dict[str, int] = defaultdict(int)
        for char in data:
            freq[char] += 1

        length = len(data)
        entropy = 0.0
        for count in freq.values():
            p = count / length
            if p > 0:
                entropy -= p * math.log2(p)

        return entropy

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_verdict(
        self,
        entity_id: UUID,
        entity_type: str,
        result: ContentSentinelResult,
        score: float,
    ) -> None:
        """
        Persist a Content Sentinel verdict to the database.

        Args:
            entity_id:   UUID of the inspected entity.
            entity_type: The entity/message type.
            result:      The ContentSentinelResult.
            score:       The combined severity score.
        """
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO content_sentinel_verdicts (
                        signal_id, entity_id, entity_type, verdict,
                        severity_score, entropy_score, schema_valid,
                        injection_detected, checks, unexpected_fields,
                        created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                """,
                    result.signal_id,
                    entity_id,
                    entity_type,
                    result.verdict.value,
                    score,
                    result.entropy_score,
                    result.schema_valid,
                    result.injection_detected,
                    json.dumps(result.checks),
                    result.unexpected_fields,
                )
        except Exception as exc:
            logger.error(
                ">>> [SENTINEL] Verdict persistence failed for %s: %s",
                entity_id, exc,
            )

    async def _fire_events(
        self,
        entity_id: UUID,
        entity_type: str,
        result: ContentSentinelResult,
        score: float,
    ) -> None:
        """
        Fire hive events and forensic logs for non-clean verdicts.

        Args:
            entity_id:   UUID of the inspected entity.
            entity_type: The entity/message type.
            result:      The ContentSentinelResult.
            score:       The combined severity score.
        """
        # Forensic logging
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type=f"content_sentinel_{result.verdict.value}",
                    source_entity=str(entity_id),
                    evidence={
                        "signal_id": str(result.signal_id),
                        "entity_type": entity_type,
                        "verdict": result.verdict.value,
                        "severity_score": score,
                        "entropy_score": result.entropy_score,
                        "injection_detected": result.injection_detected,
                        "checks": result.checks,
                    },
                )
            except Exception as exc:
                logger.error(">>> [SENTINEL] Forensic log failed: %s", exc)

        # Hive event bus
        if self._event_bus:
            topic = (
                "hive.payload.entropy_anomaly"
                if result.entropy_score > 6.0
                else "hive.payload.effect_anomaly"
            )
            try:
                await self._event_bus.publish(topic, {
                    "entity_id": str(entity_id),
                    "signal_id": str(result.signal_id),
                    "verdict": result.verdict.value,
                    "severity_score": score,
                    "timestamp": datetime.utcnow().isoformat(),
                })
            except Exception as exc:
                logger.error(">>> [SENTINEL] Event bus publish failed: %s", exc)

    # =========================================================================
    # CUSTOM SCHEMA MANAGEMENT
    # =========================================================================

    def register_schema(self, entity_type: str, expected_fields: Set[str]) -> None:
        """
        Register a custom payload schema for a new entity type.

        Args:
            entity_type:     The entity type identifier.
            expected_fields: Set of expected field names.
        """
        self._custom_schemas[entity_type] = expected_fields
        logger.info(
            ">>> [SENTINEL] Registered custom schema for '%s' (%d fields)",
            entity_type, len(expected_fields),
        )

    # =========================================================================
    # ADMIN / SUMMARY
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """
        Return a summary of Content Sentinel state.

        Designed for the SkyEye / admin dashboard.

        Returns:
            Dictionary with profile counts, schema info, and DEFCON state.
        """
        return {
            "total_entities_profiled": len(self._entity_profiles),
            "total_inspections": sum(
                p.total_inspections for p in self._entity_profiles.values()
            ),
            "known_entity_types": sorted(
                set(EXPECTED_SCHEMAS.keys()) | set(self._custom_schemas.keys())
            ),
            "custom_schemas": sorted(self._custom_schemas.keys()),
            "defcon_level": self._defcon_state.level.value,
            "full_inspection_mode": self.full_inspection_mode,
        }
