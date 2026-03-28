"""
Attack Pattern Analyzer — Deterministic, ML-free pattern recognition.

Detects:
  - Brute-force: N failed signature attempts from same device within T minutes
  - Sweep: Sequential probing of signature space (incrementing values)
  - Replay: Fragments previously seen in a different context
  - Correlation: Multiple attack vectors from same attacker profile
  - Escalation: Attack intensity increasing over time
  - APT: Low-and-slow patterns over days/weeks
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set
from uuid import UUID

from app.services.counter_intelligence.orchestrator import (
    AttackType,
    ThreatAssessment,
    ThreatLevel,
)
from app.services.counter_intelligence.fingerprinter import AttackerProfile

logger = logging.getLogger("counter_intelligence.pattern_analyzer")


# =============================================================================
# THRESHOLDS
# =============================================================================

# Brute-force: N events within T seconds
BRUTE_FORCE_COUNT = 20
BRUTE_FORCE_WINDOW_SECONDS = 300  # 5 minutes

# Sweep: N sequential signature guesses
SWEEP_SEQUENTIAL_COUNT = 5

# Correlation: multiple distinct attack methods
CORRELATION_METHOD_COUNT = 3

# Escalation: cadence increase factor over time
ESCALATION_FACTOR = 3.0  # 3x increase in cadence
ESCALATION_WINDOW_SECONDS = 600  # 10 minutes

# APT: low-and-slow persistence
APT_MIN_DURATION_HOURS = 24
APT_MIN_EVENTS = 10
APT_MAX_CADENCE = 2.0  # ≤2 events/minute sustained


class AttackPatternAnalyzer:
    """
    Analyzes AttackerProfile behavioral data to detect attack patterns
    and produce ThreatAssessments.
    """

    def __init__(self, fingerprinter=None, threat_db=None) -> None:
        self._fingerprinter = fingerprinter
        self._threat_db = threat_db
        # Track replay signatures: observation_key → set of profile_ids
        self._observed_fragments: Dict[str, Set[UUID]] = defaultdict(set)

    async def assess(self, profile_id: UUID) -> Optional[ThreatAssessment]:
        """
        Analyze the given attacker profile and return a ThreatAssessment.
        Returns None if the profile is not found.
        """
        if not self._fingerprinter:
            return None

        profile = self._fingerprinter.get_profile_obj(profile_id)
        if not profile:
            return None

        # Run all detectors
        detections: List[tuple] = []  # (ThreatLevel, AttackType)

        if self._detect_brute_force(profile):
            detections.append((ThreatLevel.HIGH, AttackType.BRUTE_FORCE))

        if self._detect_sweep(profile):
            detections.append((ThreatLevel.HIGH, AttackType.SWEEP))

        if self._detect_replay(profile):
            detections.append((ThreatLevel.HIGH, AttackType.REPLAY))

        if self._detect_correlation(profile):
            detections.append((ThreatLevel.CRITICAL, AttackType.INJECTION))

        if self._detect_escalation(profile):
            detections.append((ThreatLevel.CRITICAL, AttackType.ESCALATION))

        if self._detect_apt(profile):
            detections.append((ThreatLevel.APT, AttackType.APT))

        if not detections:
            # No pattern detected — base assessment on event count
            if profile.total_events >= 5:
                return ThreatAssessment(
                    attacker_profile_id=profile_id,
                    threat_level=ThreatLevel.MEDIUM,
                    attack_type=AttackType.UNKNOWN,
                    target_fibres=list(profile.target_fibres),
                    estimated_sophistication=0.2,
                )
            return ThreatAssessment(
                attacker_profile_id=profile_id,
                threat_level=ThreatLevel.LOW,
                attack_type=AttackType.UNKNOWN,
                target_fibres=list(profile.target_fibres),
                estimated_sophistication=0.1,
            )

        # Use highest threat level detected
        detections.sort(key=lambda x: x[0], reverse=True)
        highest_level, primary_type = detections[0]

        # Sophistication estimate
        sophistication = min(1.0, len(detections) * 0.25 + 0.2)

        assessment = ThreatAssessment(
            attacker_profile_id=profile_id,
            threat_level=highest_level,
            attack_type=primary_type,
            target_fibres=list(profile.target_fibres),
            estimated_sophistication=sophistication,
        )

        logger.info(
            "Pattern detected for %s: level=%s type=%s sophistication=%.2f",
            profile_id, highest_level.name, primary_type.value, sophistication,
        )

        return assessment

    # ------------------------------------------------------------------
    # Detectors
    # ------------------------------------------------------------------

    def _detect_brute_force(self, profile: AttackerProfile) -> bool:
        """
        Brute-force: Many events within a short window.
        """
        now = time.time()
        recent = [
            t for t in profile.attack_cadence_history
            if now - t < BRUTE_FORCE_WINDOW_SECONDS
        ]
        return len(recent) >= BRUTE_FORCE_COUNT

    def _detect_sweep(self, profile: AttackerProfile) -> bool:
        """
        Sweep: Sequential signature guesses (incrementing or patterned).
        """
        guesses = profile.signature_guesses
        if len(guesses) < SWEEP_SEQUENTIAL_COUNT:
            return False

        # Check last N guesses for sequential pattern
        tail = guesses[-SWEEP_SEQUENTIAL_COUNT:]
        diffs = [tail[i + 1] - tail[i] for i in range(len(tail) - 1)]

        # All diffs equal (sequential with constant step)
        if len(set(diffs)) == 1 and diffs[0] != 0:
            return True

        # All diffs positive (monotonically increasing)
        if all(d > 0 for d in diffs):
            return True

        # All diffs negative (monotonically decreasing — reverse sweep)
        if all(d < 0 for d in diffs):
            return True

        return False

    def _detect_replay(self, profile: AttackerProfile) -> bool:
        """
        Replay: Fragments seen in a different context (observation ID reuse).
        Checks if any fragment keys from this profile also appeared from others.
        """
        replay_keys = profile.attack_methods & {"replay_detected", "observation_reuse"}
        return len(replay_keys) > 0

    def _detect_correlation(self, profile: AttackerProfile) -> bool:
        """
        Multi-vector: Attacker using multiple distinct attack methods.
        """
        return len(profile.attack_methods) >= CORRELATION_METHOD_COUNT

    def _detect_escalation(self, profile: AttackerProfile) -> bool:
        """
        Escalation: Attack intensity increasing over time.
        Compare cadence in first half vs second half of the window.
        """
        history = profile.attack_cadence_history
        if len(history) < 10:
            return False

        now = time.time()
        window_start = now - ESCALATION_WINDOW_SECONDS
        in_window = [t for t in history if t >= window_start]

        if len(in_window) < 6:
            return False

        mid = len(in_window) // 2
        first_half = in_window[:mid]
        second_half = in_window[mid:]

        if not first_half or not second_half:
            return False

        first_duration = first_half[-1] - first_half[0]
        second_duration = second_half[-1] - second_half[0]

        if first_duration <= 0 or second_duration <= 0:
            return False

        first_rate = len(first_half) / first_duration
        second_rate = len(second_half) / second_duration

        return second_rate >= first_rate * ESCALATION_FACTOR

    def _detect_apt(self, profile: AttackerProfile) -> bool:
        """
        APT: Low-and-slow over extended period.
        Must persist for 24+ hours with 10+ events but low cadence.
        """
        duration = (profile.last_seen - profile.first_seen).total_seconds()
        duration_hours = duration / 3600

        if duration_hours < APT_MIN_DURATION_HOURS:
            return False

        if profile.total_events < APT_MIN_EVENTS:
            return False

        # Check that cadence is consistently low (not a burst)
        cadence = profile.attack_cadence
        if cadence > APT_MAX_CADENCE:
            return False

        # Low cadence but many events over a long time = APT
        return True

    # ------------------------------------------------------------------
    # Replay Tracking
    # ------------------------------------------------------------------

    def register_fragment_observation(
        self, observation_key: str, profile_id: UUID,
    ) -> bool:
        """
        Track fragment observation keys across profiles.
        Returns True if this key was seen from a DIFFERENT profile (replay).
        """
        existing = self._observed_fragments[observation_key]
        is_replay = len(existing) > 0 and profile_id not in existing
        existing.add(profile_id)
        return is_replay
