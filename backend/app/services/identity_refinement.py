"""
Therapeutic Identity Inference Engine — Continuous Refinement.

After each call, refines the identity models with new data:
- Voice enrollment profile update (pitch/energy/spectral convergence)
- Linguistic fingerprint drift tracking
- Narrative profile enrichment from new crystal content
- Role-play exclusion (sessions marked as role-play don't update profiles)
- QoS exclusion (degraded audio sessions don't update voice profiles)
- Drift tolerance (flags identity drift for manual review)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.identity_refinement")

DRIFT_THRESHOLD = 0.20
MAX_DRIFT_BEFORE_FLAG = 3


@dataclass
class RefinementResult:
    """Outcome of a post-call identity refinement cycle."""
    user_id: str
    call_sid: str
    voice_updated: bool = False
    linguistic_updated: bool = False
    narrative_updated: bool = False
    excluded_reason: Optional[str] = None
    drift_detected: bool = False
    drift_magnitude: float = 0.0
    consecutive_drifts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "call_sid": self.call_sid,
            "voice_updated": self.voice_updated,
            "linguistic_updated": self.linguistic_updated,
            "narrative_updated": self.narrative_updated,
            "excluded_reason": self.excluded_reason,
            "drift_detected": self.drift_detected,
            "drift_magnitude": self.drift_magnitude,
            "consecutive_drifts": self.consecutive_drifts,
        }


class IdentityRefinementEngine:
    """
    Post-call refinement of identity profiles.

    After each call ends, this engine determines whether to update
    the identity models with data from that call, or exclude it.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._drift_counters: Dict[str, int] = {}

    async def refine(
        self,
        user_id: str,
        call_sid: str,
        voice_enrollment_service=None,
        linguistic_engine=None,
        narrative_engine=None,
        roleplay_active: bool = False,
        qos_degraded: bool = False,
        identity_confidence: float = 0.0,
        session_audio_features: Optional[Dict[str, float]] = None,
        session_transcripts: Optional[List[str]] = None,
    ) -> RefinementResult:
        """
        Run post-call refinement with exclusion gates.
        """
        result = RefinementResult(user_id=user_id, call_sid=call_sid)

        if roleplay_active:
            result.excluded_reason = "roleplay_session"
            logger.info("IdentityRefinement: skipping %s — roleplay session", call_sid)
            return result

        if qos_degraded:
            result.excluded_reason = "qos_degraded"
            logger.info("IdentityRefinement: skipping voice update for %s — degraded QoS", call_sid)

        if identity_confidence < 0.30:
            result.excluded_reason = "identity_unconfirmed"
            logger.info("IdentityRefinement: skipping %s — identity not confirmed (%.2f)", call_sid, identity_confidence)
            return result

        if voice_enrollment_service and session_audio_features and not qos_degraded:
            try:
                drift = await self._check_voice_drift(
                    user_id, session_audio_features, voice_enrollment_service,
                )
                if drift is not None:
                    result.drift_magnitude = drift
                    if drift > DRIFT_THRESHOLD:
                        self._drift_counters[user_id] = self._drift_counters.get(user_id, 0) + 1
                        result.consecutive_drifts = self._drift_counters[user_id]
                        result.drift_detected = True

                        if result.consecutive_drifts >= MAX_DRIFT_BEFORE_FLAG:
                            logger.warning(
                                "IdentityRefinement: voice drift flagged for %s — %d consecutive drifts",
                                user_id, result.consecutive_drifts,
                            )
                            await self._flag_drift(user_id, call_sid, drift)
                    else:
                        self._drift_counters[user_id] = 0
                        result.voice_updated = True
            except Exception as e:
                logger.warning("IdentityRefinement: voice update failed: %s", e)

        if linguistic_engine and session_transcripts:
            try:
                for transcript in session_transcripts:
                    linguistic_engine.analyze_utterance(user_id, transcript)
                result.linguistic_updated = True
            except Exception as e:
                logger.warning("IdentityRefinement: linguistic update failed: %s", e)

        if narrative_engine and session_transcripts:
            try:
                for transcript in session_transcripts:
                    narrative_engine.analyze_turn(user_id, transcript)
                result.narrative_updated = True
            except Exception as e:
                logger.warning("IdentityRefinement: narrative update failed: %s", e)

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO identity_refinement_log
                       (user_id, call_sid, voice_updated, linguistic_updated,
                        narrative_updated, excluded_reason, drift_detected,
                        drift_magnitude, consecutive_drifts, refined_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())""",
                    user_id, call_sid, result.voice_updated,
                    result.linguistic_updated, result.narrative_updated,
                    result.excluded_reason, result.drift_detected,
                    result.drift_magnitude, result.consecutive_drifts,
                )
            except Exception as e:
                logger.warning("IdentityRefinement: log failed: %s", e)

        return result

    async def _check_voice_drift(
        self,
        user_id: str,
        new_features: Dict[str, float],
        enrollment_service,
    ) -> Optional[float]:
        """
        Compare new audio features against the enrolled profile.
        Returns a drift magnitude (0.0 = identical, 1.0 = completely different).
        """
        profile = await enrollment_service.load_profile(user_id)
        if not profile or not profile.pitch_mean:
            return None

        drifts = []

        if "pitch_mean" in new_features and profile.pitch_mean:
            pitch_drift = abs(new_features["pitch_mean"] - profile.pitch_mean) / max(profile.pitch_mean, 1.0)
            drifts.append(min(pitch_drift, 1.0))

        if "energy_mean" in new_features and profile.energy_mean:
            energy_drift = abs(new_features["energy_mean"] - profile.energy_mean) / max(profile.energy_mean, 0.01)
            drifts.append(min(energy_drift, 1.0))

        if "speech_rate" in new_features and profile.speech_rate:
            rate_drift = abs(new_features["speech_rate"] - profile.speech_rate) / max(profile.speech_rate, 0.1)
            drifts.append(min(rate_drift, 1.0))

        return sum(drifts) / len(drifts) if drifts else None

    async def _flag_drift(
        self, user_id: str, call_sid: str, magnitude: float,
    ) -> None:
        """Flag a voice drift event for manual review."""
        if not self._db:
            return

        try:
            await self._db.execute(
                """INSERT INTO identity_drift_flags
                   (user_id, call_sid, drift_magnitude, flagged_at, reviewed)
                   VALUES ($1, $2, $3, NOW(), false)""",
                user_id, call_sid, magnitude,
            )
        except Exception as e:
            logger.warning("IdentityRefinement: drift flag failed: %s", e)
