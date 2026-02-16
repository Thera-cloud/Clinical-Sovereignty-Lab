"""
Cold-Start Nevedal Calibration Service
Establishes baseline Nevedal parameters for a new member using
minimal initial data (text exchanges, optional voice sample).

Operational Specifications §1.2 — Cold Start Calibration.
"""

import asyncio
import logging
import math
from datetime import datetime
from typing import Any, Dict, Optional

from app.models.onboarding import NevedalColdStart

logger = logging.getLogger("onboarding.cold_start")


# =============================================================================
# COLD-START ESTIMATION HEURISTICS
# =============================================================================

# Text-based sentiment → p_ent estimation
SENTIMENT_TO_P_ENT = {
    "very_negative": 0.25,
    "negative": 0.35,
    "neutral": 0.50,
    "positive": 0.65,
    "very_positive": 0.80,
}

# Text complexity → gamma_env estimation (higher complexity → lower gamma)
COMPLEXITY_TO_GAMMA = {
    "simple": 0.65,
    "moderate": 0.50,
    "complex": 0.35,
    "very_complex": 0.25,
}


class ColdStartNevedalService:
    """
    Bootstraps Nevedal parameters for a new member when no voice or
    biometric data is yet available. Uses text analysis as a proxy
    until real voice biometrics are collected.
    """

    def __init__(self, nevedal_engine=None):
        self._nevedal_engine = nevedal_engine

    async def initiate_calibration(self, user_id: str) -> NevedalColdStart:
        """Create a new cold-start calibration record."""
        record = NevedalColdStart(user_id=user_id)
        logger.info("Cold-start calibration initiated for user %s", user_id)
        return record

    async def process_text_exchange(
        self,
        record: NevedalColdStart,
        user_message: str,
        nate_response: str,
    ) -> NevedalColdStart:
        """
        Process a text exchange and update cold-start parameters.
        Each exchange refines the initial estimates.
        """
        record.text_exchanges += 1

        # Estimate sentiment from user message
        sentiment = self._estimate_sentiment(user_message)
        p_ent_estimate = SENTIMENT_TO_P_ENT.get(sentiment, 0.50)

        # Estimate text complexity → gamma proxy
        complexity = self._estimate_complexity(user_message)
        gamma_estimate = COMPLEXITY_TO_GAMMA.get(complexity, 0.50)

        # Running average with increasing confidence
        weight = min(record.text_exchanges / record.calibration_exchanges_needed, 1.0)
        record.computed_p_ent = (
            record.computed_p_ent * (1 - weight) + p_ent_estimate * weight
        )
        record.computed_gamma_env = (
            record.computed_gamma_env * (1 - weight) + gamma_estimate * weight
        )

        # Tunneling proxy: emotional vulnerability in text
        tunneling_proxy = self._estimate_tunneling(user_message)
        record.computed_t_tunnel = (
            record.computed_t_tunnel * (1 - weight) + tunneling_proxy * weight
        )

        # Compute cold-start C_emo
        record.cold_start_c_emo = self._compute_cold_c_emo(
            record.computed_p_ent,
            record.computed_gamma_env,
            record.computed_t_tunnel,
        )

        # Update confidence
        record.calibration_confidence = min(
            record.text_exchanges / record.calibration_exchanges_needed, 1.0
        )

        # Check if baseline is established
        if record.text_exchanges >= record.calibration_exchanges_needed:
            record.baseline_established = True
            logger.info(
                "Cold-start baseline established for user %s: "
                "p_ent=%.3f, gamma=%.3f, t_tunnel=%.3f, c_emo=%.3f",
                record.user_id,
                record.computed_p_ent,
                record.computed_gamma_env,
                record.computed_t_tunnel,
                record.cold_start_c_emo,
            )

        return record

    async def process_voice_sample(
        self,
        record: NevedalColdStart,
        audio_data: bytes,
    ) -> NevedalColdStart:
        """
        Process a voice sample to establish real biometric baseline.
        This replaces text-based estimates with actual measurements.
        """
        if self._nevedal_engine:
            try:
                biometrics = await self._nevedal_engine.extract_voice_biometrics(
                    audio_data
                )
                record.voice_sample_collected = True
                record.initial_pitch_mean = biometrics.get("pitch_mean")
                record.initial_pitch_variance = biometrics.get("pitch_variance")
                record.initial_energy = biometrics.get("energy")
                record.initial_speech_rate = biometrics.get("speech_rate")
                record.initial_pause_ratio = biometrics.get("pause_ratio")

                # Recalculate with real biometrics
                if record.initial_pitch_variance is not None:
                    record.computed_p_ent = min(
                        record.initial_pitch_variance * 2.0, 1.0
                    )
                if record.initial_energy is not None:
                    record.computed_gamma_env = max(
                        1.0 - record.initial_energy, 0.1
                    )
                if record.initial_pause_ratio is not None:
                    record.computed_t_tunnel = min(
                        record.initial_pause_ratio * 1.5, 1.0
                    )

                record.cold_start_c_emo = self._compute_cold_c_emo(
                    record.computed_p_ent,
                    record.computed_gamma_env,
                    record.computed_t_tunnel,
                )
                record.calibration_confidence = 0.85
                record.baseline_established = True

                logger.info(
                    "Voice-based calibration for user %s: c_emo=%.3f (confidence=%.2f)",
                    record.user_id,
                    record.cold_start_c_emo,
                    record.calibration_confidence,
                )
            except Exception as e:
                logger.warning("Voice biometric extraction failed: %s", e)

        return record

    # -------------------------------------------------------------------------
    # INTERNAL HELPERS
    # -------------------------------------------------------------------------

    def _estimate_sentiment(self, text: str) -> str:
        """Simple keyword-based sentiment estimation."""
        positive_words = {"happy", "good", "great", "wonderful", "hopeful", "excited", "grateful", "relieved", "better"}
        negative_words = {"sad", "hopeless", "depressed", "anxious", "scared", "angry", "frustrated", "empty", "hurt", "lost", "broken"}
        words = set(text.lower().split())
        pos_count = len(words & positive_words)
        neg_count = len(words & negative_words)
        if neg_count > 2:
            return "very_negative"
        if neg_count > 0:
            return "negative"
        if pos_count > 2:
            return "very_positive"
        if pos_count > 0:
            return "positive"
        return "neutral"

    def _estimate_complexity(self, text: str) -> str:
        """Estimate text complexity as a proxy for cognitive engagement."""
        words = text.split()
        avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
        sentence_count = max(text.count(".") + text.count("!") + text.count("?"), 1)
        words_per_sentence = len(words) / sentence_count

        if avg_word_len > 6 and words_per_sentence > 20:
            return "very_complex"
        if avg_word_len > 5 or words_per_sentence > 15:
            return "complex"
        if avg_word_len > 4 or words_per_sentence > 10:
            return "moderate"
        return "simple"

    def _estimate_tunneling(self, text: str) -> float:
        """Estimate emotional tunneling from text vulnerability markers."""
        vulnerability_markers = [
            "i feel", "it hurts", "i'm scared", "i don't know",
            "i can't", "help me", "i'm lost", "i'm afraid",
            "vulnerable", "open up", "trust", "honest",
        ]
        lower = text.lower()
        count = sum(1 for marker in vulnerability_markers if marker in lower)
        return min(count * 0.15, 1.0)

    def _compute_cold_c_emo(
        self, p_ent: float, gamma_env: float, t_tunnel: float
    ) -> float:
        """
        Simplified Nevedal formula for cold-start:
        C_emo_cold = (β · p_ent · T_tunnel) / (gamma_env + 0.1)
        Bounded to [0, 1].
        """
        beta = 1.0
        denominator = gamma_env + 0.1
        c_emo = (beta * p_ent * t_tunnel) / denominator
        return max(0.0, min(c_emo, 1.0))
