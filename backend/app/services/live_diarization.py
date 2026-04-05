"""
Therapeutic Identity Inference Engine — Phase 5: Live Diarization.

Wires voice enrollment, linguistic identity, narrative identity,
overlapping speech detection, liveness detection, role-play detection,
and gentle investigation into the Twilio media stream loop.

This module provides a LiveDiarizationSession that runs alongside each
voice call, processing audio and text to maintain real-time identity
confidence.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("nate.live_diarization")

try:
    from app.services.voice_enrollment_service import VoiceEnrollmentService
except ImportError:
    VoiceEnrollmentService = None

try:
    from app.services.linguistic_identity import LinguisticIdentityEngine
except ImportError:
    LinguisticIdentityEngine = None

try:
    from app.services.narrative_identity import NarrativeIdentityEngine
except ImportError:
    NarrativeIdentityEngine = None

try:
    from app.services.therapeutic_identity_inference import (
        TherapeuticIdentityInference,
        IdentityCandidate,
    )
except ImportError:
    TherapeuticIdentityInference = None
    IdentityCandidate = None

try:
    from app.services.overlapping_speech_detector import OverlappingSpeechDetector
except ImportError:
    OverlappingSpeechDetector = None

try:
    from app.services.liveness_detector import LivenessDetector
except ImportError:
    LivenessDetector = None

try:
    from app.services.roleplay_detector import RolePlayDetector
except ImportError:
    RolePlayDetector = None

try:
    from app.services.gentle_investigation import GentleInvestigationEngine
except ImportError:
    GentleInvestigationEngine = None

try:
    from app.services.age_appropriate_calibration import AgeAppropriateCalibrator
except ImportError:
    AgeAppropriateCalibrator = None


@dataclass
class DiarizationState:
    """Real-time identity state for a live call."""
    call_sid: str
    expected_user: Optional[str] = None
    identified_user: Optional[str] = None
    confidence: float = 0.0
    method: str = "none"
    voice_score: float = 0.0
    linguistic_score: float = 0.0
    narrative_score: float = 0.0
    liveness_ok: bool = True
    qos_degraded: bool = False
    roleplay_active: bool = False
    osd_penalty: float = 0.0
    investigation_pending: bool = False
    investigation_prompt: str = ""
    turn_count: int = 0
    audio_chunks_processed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_sid": self.call_sid,
            "expected_user": self.expected_user,
            "identified_user": self.identified_user,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "liveness_ok": self.liveness_ok,
            "qos_degraded": self.qos_degraded,
            "roleplay_active": self.roleplay_active,
            "turn_count": self.turn_count,
        }


class LiveDiarizationSession:
    """
    Per-call identity monitoring session.

    Lifecycle:
    1. Created at call start with expected_user from phone lookup
    2. Fed PCM audio chunks for voice analysis
    3. Fed text transcripts for linguistic/narrative analysis
    4. Queried for identity state at any point
    5. Finalized at call end for refinement
    """

    def __init__(
        self,
        call_sid: str,
        expected_user: Optional[str] = None,
        db_pool=None,
        deployment_context: str = "default",
        user_age: Optional[int] = None,
    ):
        self._state = DiarizationState(
            call_sid=call_sid,
            expected_user=expected_user,
        )
        self._db = db_pool
        self._deployment_context = deployment_context
        self._user_age = user_age

        self._enrollment = VoiceEnrollmentService(db_pool=db_pool) if VoiceEnrollmentService else None
        self._linguistic = LinguisticIdentityEngine(db_pool=db_pool) if LinguisticIdentityEngine else None
        self._narrative = NarrativeIdentityEngine(db_pool=db_pool) if NarrativeIdentityEngine else None
        self._inference = TherapeuticIdentityInference(db_pool=db_pool) if TherapeuticIdentityInference else None
        self._osd = OverlappingSpeechDetector() if OverlappingSpeechDetector else None
        self._liveness = LivenessDetector() if LivenessDetector else None
        self._roleplay = RolePlayDetector() if RolePlayDetector else None
        self._investigation = GentleInvestigationEngine() if GentleInvestigationEngine else None
        self._calibrator = AgeAppropriateCalibrator() if AgeAppropriateCalibrator else None

        self._greeting_checked = False
        self._audio_features_accumulated: List[Dict[str, float]] = []

        if self._inference:
            self._inference.set_environment(deployment_context)

    def process_audio_chunk(self, pcm_chunk: bytes) -> None:
        """Process a PCM audio chunk for voice identity signals."""
        self._state.audio_chunks_processed += 1

        samples = np.frombuffer(pcm_chunk, dtype=np.int16)

        if self._osd:
            self._osd.process_frame(samples)
            self._state.osd_penalty = self._osd.get_identity_confidence_penalty()

        if self._liveness:
            result = self._liveness.process_frame(samples)
            if result:
                self._state.liveness_ok = result.is_live
                self._state.qos_degraded = result.qos_degraded

        if self._enrollment and not self._greeting_checked and self._state.audio_chunks_processed <= 200:
            pass  # Deferred: early enrollment/greeting — requires ENABLE_VOICE_IDENTITY (Patent 11, item #6)

    async def process_greeting(self, pcm_audio_4s: bytes) -> None:
        """
        Fast-path greeting check using the first ~4 seconds of audio.
        Runs once at the beginning of the call.
        """
        if self._greeting_checked:
            return
        self._greeting_checked = True

        if not self._enrollment or not self._state.expected_user:
            return

        try:
            profile = await self._enrollment.load_profile(self._state.expected_user)
            if not profile or not profile.is_enrolled:
                return
            self._enrollment.start_session(self._state.expected_user, self._state.call_sid)
            self._enrollment.feed_audio(self._state.call_sid, pcm_audio_4s)

            matches = self._enrollment.match_greeting(
                self._state.call_sid, [profile],
            )
            if matches:
                best = matches[0]
                conf = best.get("confidence", 0.0)
                if conf > 0.6:
                    self._state.voice_score = conf
                    self._state.method = "greeting_fast_path"
                    self._state.identified_user = self._state.expected_user
                    self._state.confidence = conf
                    logger.info(
                        "LiveDiarization: greeting fast-path matched %s (%.2f)",
                        self._state.expected_user, conf,
                    )
        except Exception as e:
            logger.warning("LiveDiarization: greeting check failed: %s", e)

    def process_transcript(self, text: str, speaker: str = "caller") -> None:
        """Process a transcript turn for linguistic and narrative identity."""
        self._state.turn_count += 1

        if self._linguistic and self._state.expected_user:
            self._linguistic.analyze_utterance(self._state.expected_user, text)

        if self._narrative and self._state.expected_user:
            self._narrative.analyze_turn(self._state.expected_user, text)

        if self._roleplay:
            assessment = self._roleplay.analyze_turn(text)
            if assessment:
                self._state.roleplay_active = assessment.identity_inference_excluded

    async def update_identity(self) -> DiarizationState:
        """
        Run full identity fusion and return current state.
        Called periodically (e.g., every 5 turns or on demand).
        """
        if not self._inference or not self._state.expected_user or not IdentityCandidate:
            return self._state

        try:
            candidate = IdentityCandidate(
                user_id=self._state.expected_user,
                voice_score=self._state.voice_score,
            )

            if self._linguistic:
                fp = await self._linguistic.load_fingerprint(self._state.expected_user)
                if fp and fp.turn_count > 0:
                    candidate.linguistic_score = min(0.3 + fp.turn_count * 0.05, 0.9)

            if self._narrative:
                np_ = await self._narrative.load_profile(self._state.expected_user)
                if np_ and np_.session_count > 0:
                    candidate.narrative_score = min(0.3 + np_.session_count * 0.03, 0.9)

            osd_mult = 1.0 - self._state.osd_penalty
            candidate.voice_score *= osd_mult

            result = self._inference.fuse_scores(
                [candidate],
                qos_degraded=self._state.qos_degraded,
                adolescent_flag=(self._user_age is not None and self._user_age < 18),
            )
            if result:
                self._state.identified_user = result.identified_user
                self._state.confidence = result.confidence
                self._state.method = result.confidence_tier

        except Exception as e:
            logger.warning("LiveDiarization: identity update failed: %s", e)

        if self._investigation and self._state.confidence < 0.75:
            plan = self._investigation.evaluate(
                call_sid=self._state.call_sid,
                identity_confidence=self._state.confidence,
                identity_candidates=[],
                crisis_active=False,
                qos_degraded=self._state.qos_degraded,
                roleplay_active=self._state.roleplay_active,
                enrollment_tier="LOW",
                candidates_are_family=False,
                expected_user=self._state.expected_user,
            )
            if plan.should_investigate:
                self._state.investigation_pending = True
                self._state.investigation_prompt = self._investigation.format_investigation_prompt(plan)

        return self._state

    def get_system_prompt_overlay(self) -> str:
        """
        Get any system prompt additions needed for this call.
        Includes age calibration, corrections disclosure, investigation prompts.
        """
        parts = []

        if self._calibrator:
            overlay = self._calibrator.get_system_prompt_overlay(
                user_age=self._user_age,
                deployment_context=self._deployment_context,
            )
            if overlay:
                parts.append(overlay)

        if self._state.investigation_pending and self._state.investigation_prompt:
            parts.append(self._state.investigation_prompt)
            self._state.investigation_pending = False

        return "\n\n".join(parts)

    def get_voice_threshold_multiplier(self) -> float:
        """Get the age-adjusted voice identity threshold multiplier."""
        if self._calibrator:
            return self._calibrator.get_voice_identity_threshold_multiplier(self._user_age)
        return 1.0

    async def finalize(self) -> Dict[str, Any]:
        """
        Finalize the session — log identity inference result.
        Called at call end, before crystallization.
        """
        if self._enrollment:
            try:
                await self._enrollment.finalize_session(self._state.call_sid)
            except Exception as e:
                logger.warning("LiveDiarization: enrollment finalize failed: %s", e)

        if self._linguistic and self._state.expected_user:
            try:
                await self._linguistic.persist(self._state.expected_user)
            except Exception as e:
                logger.warning("LiveDiarization: linguistic persist failed: %s", e)

        if self._narrative and self._state.expected_user:
            try:
                await self._narrative.persist(self._state.expected_user)
            except Exception as e:
                logger.warning("LiveDiarization: narrative persist failed: %s", e)

        result = self._state.to_dict()

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO identity_inference_log
                       (call_sid, phone, tenant_id, top_candidate, confidence,
                        method, voice_score, linguistic_score, narrative_score,
                        osd_penalty, liveness_ok, roleplay_excluded, qos_degraded,
                        gentle_investigation, environment)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                               $12, $13, $14, $15)""",
                    self._state.call_sid, None, "default",
                    self._state.identified_user, self._state.confidence,
                    self._state.method, self._state.voice_score,
                    self._state.linguistic_score, self._state.narrative_score,
                    self._state.osd_penalty, self._state.liveness_ok,
                    self._state.roleplay_active, self._state.qos_degraded,
                    self._state.investigation_prompt != "",
                    self._deployment_context,
                )
            except Exception as e:
                logger.warning("LiveDiarization: finalize log failed: %s", e)

        return result
