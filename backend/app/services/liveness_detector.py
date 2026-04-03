"""
Therapeutic Identity Inference Engine — Phase 4c: Liveness / Anti-Spoofing.

Detects replay attacks and synthetic speech by analyzing micro-temporal
features that are absent in recordings and difficult to replicate in TTS.
QoS-aware: degrades gracefully on prison/low-quality phone lines.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("nate.liveness")

LIVENESS_WINDOW_FRAMES = 100
MIN_FRAMES_FOR_DECISION = 30
SNR_DEGRADED_THRESHOLD_DB = 15.0


@dataclass
class LivenessResult:
    """Result of liveness analysis."""
    is_live: bool = True
    confidence: float = 0.5
    micro_variation_score: float = 0.0
    breath_detected: bool = False
    ambient_consistency: float = 0.0
    snr_estimate_db: float = 30.0
    qos_degraded: bool = False
    spoofing_indicators: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_live": self.is_live,
            "confidence": round(self.confidence, 3),
            "micro_variation": round(self.micro_variation_score, 4),
            "breath_detected": self.breath_detected,
            "ambient_consistency": round(self.ambient_consistency, 4),
            "snr_db": round(self.snr_estimate_db, 1),
            "qos_degraded": self.qos_degraded,
            "indicators": self.spoofing_indicators,
        }


class LivenessDetector:
    """
    Anti-spoofing detector using micro-temporal analysis.

    Live speech has: (1) micro-variation in pitch/energy between frames,
    (2) breath sounds between utterances, (3) consistent ambient noise
    from the physical environment.

    Synthetic speech lacks: micro-jitter, breath artifacts, and has
    unnaturally consistent inter-frame energy.
    """

    def __init__(self, sample_rate: int = 8000):
        self._sr = sample_rate
        self._frame_size = int(0.02 * sample_rate)
        self._energy_deltas = deque(maxlen=LIVENESS_WINDOW_FRAMES)
        self._pitch_deltas = deque(maxlen=LIVENESS_WINDOW_FRAMES)
        self._silence_energies = deque(maxlen=50)
        self._speech_energies = deque(maxlen=50)
        self._frame_count = 0
        self._breath_count = 0
        self._last_result = LivenessResult()

    def process_frame(self, pcm_samples: np.ndarray) -> Optional[LivenessResult]:
        """
        Analyze a PCM frame for liveness indicators.
        Returns a result every LIVENESS_WINDOW_FRAMES frames.
        """
        samples = pcm_samples.astype(np.float32) / 32768.0 if pcm_samples.dtype != np.float32 else pcm_samples
        energy = float(np.sqrt(np.mean(samples ** 2)))
        self._frame_count += 1

        is_speech = energy > 0.01
        if is_speech:
            self._speech_energies.append(energy)
        else:
            self._silence_energies.append(energy)

        if self._frame_count > 1:
            prev_e = self._speech_energies[-2] if len(self._speech_energies) >= 2 else energy
            self._energy_deltas.append(abs(energy - prev_e))

        if not is_speech and energy > 0.003 and energy < 0.01:
            self._breath_count += 1

        if self._frame_count % LIVENESS_WINDOW_FRAMES == 0 and self._frame_count >= MIN_FRAMES_FOR_DECISION:
            return self._evaluate()

        return None

    def _evaluate(self) -> LivenessResult:
        result = LivenessResult()

        if self._energy_deltas:
            micro_var = float(np.std(list(self._energy_deltas)))
            result.micro_variation_score = micro_var
        else:
            result.micro_variation_score = 0.0

        result.breath_detected = self._breath_count > 0

        if self._silence_energies:
            silence_arr = np.array(list(self._silence_energies))
            result.ambient_consistency = float(np.std(silence_arr))
        else:
            result.ambient_consistency = 0.0

        if self._speech_energies and self._silence_energies:
            speech_mean = float(np.mean(list(self._speech_energies)))
            silence_mean = float(np.mean(list(self._silence_energies)))
            if silence_mean > 1e-8:
                result.snr_estimate_db = 20.0 * np.log10(speech_mean / silence_mean)
            else:
                result.snr_estimate_db = 40.0

        result.qos_degraded = result.snr_estimate_db < SNR_DEGRADED_THRESHOLD_DB

        indicators = []
        if result.micro_variation_score < 0.0005 and not result.qos_degraded:
            indicators.append("unnaturally_smooth_energy")
        if not result.breath_detected and self._frame_count > 200:
            indicators.append("no_breath_artifacts")
        if result.ambient_consistency < 0.0001 and not result.qos_degraded:
            indicators.append("no_ambient_variation")

        result.spoofing_indicators = indicators

        if result.qos_degraded:
            result.is_live = True
            result.confidence = 0.5
        elif len(indicators) >= 2:
            result.is_live = False
            result.confidence = 0.8
        elif len(indicators) == 1:
            result.is_live = True
            result.confidence = 0.6
        else:
            result.is_live = True
            result.confidence = 0.9

        self._last_result = result
        return result

    @property
    def latest(self) -> LivenessResult:
        return self._last_result

    @property
    def qos_degraded(self) -> bool:
        return self._last_result.qos_degraded

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_count": self._frame_count,
            "breath_count": self._breath_count,
            **self._last_result.to_dict(),
        }
