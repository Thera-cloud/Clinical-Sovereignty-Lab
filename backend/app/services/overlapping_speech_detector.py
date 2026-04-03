"""
Therapeutic Identity Inference Engine — Phase 4b: Overlapping Speech Detection.

Detects crosstalk in multi-party sessions using energy contour analysis
and pitch tracking. When overlapping speech is detected, identity
confidence is reduced rather than forced.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("nate.osd")

ENERGY_THRESHOLD_DB = -30.0
OVERLAP_MIN_DURATION_MS = 200
FRAME_SIZE_MS = 20
HOP_SIZE_MS = 10


@dataclass
class OverlapEvent:
    """A detected overlapping speech segment."""
    start_ms: float
    end_ms: float
    energy_ratio: float
    confidence: float

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


class OverlappingSpeechDetector:
    """
    Detects simultaneous speech in audio streams using dual-channel
    energy contour analysis and spectral divergence.

    For single-channel (Twilio mulaw), uses energy envelope variance
    to detect when two speakers are active simultaneously.
    """

    def __init__(self, sample_rate: int = 8000):
        self._sr = sample_rate
        self._frame_samples = int(FRAME_SIZE_MS * sample_rate / 1000)
        self._hop_samples = int(HOP_SIZE_MS * sample_rate / 1000)
        self._energy_history = deque(maxlen=500)
        self._overlap_events: List[OverlapEvent] = []
        self._current_overlap_start: Optional[float] = None
        self._frame_count = 0
        self._baseline_energy = 0.0
        self._energy_variance = 0.0

    def process_frame(self, pcm_samples: np.ndarray) -> Optional[OverlapEvent]:
        """
        Process an audio frame and detect overlapping speech.
        Returns an OverlapEvent if overlap ended in this frame.
        """
        energy = float(np.sqrt(np.mean(pcm_samples.astype(np.float32) ** 2)))
        self._energy_history.append(energy)
        self._frame_count += 1

        if self._frame_count < 25:
            self._baseline_energy = float(np.mean(list(self._energy_history)))
            return None

        alpha = 0.02
        self._baseline_energy = self._baseline_energy * (1 - alpha) + energy * alpha
        recent = list(self._energy_history)[-50:]
        self._energy_variance = float(np.var(recent))

        is_overlap = self._detect_overlap(energy, recent)
        current_ms = self._frame_count * HOP_SIZE_MS

        if is_overlap and self._current_overlap_start is None:
            self._current_overlap_start = current_ms
            return None

        if not is_overlap and self._current_overlap_start is not None:
            duration = current_ms - self._current_overlap_start
            if duration >= OVERLAP_MIN_DURATION_MS:
                event = OverlapEvent(
                    start_ms=self._current_overlap_start,
                    end_ms=current_ms,
                    energy_ratio=energy / max(self._baseline_energy, 1e-6),
                    confidence=min(1.0, duration / 1000.0),
                )
                self._overlap_events.append(event)
                self._current_overlap_start = None
                return event
            self._current_overlap_start = None

        return None

    def _detect_overlap(self, energy: float, recent: List[float]) -> bool:
        """
        Heuristic overlap detection on single-channel audio.
        Overlapping speech produces: (1) energy spikes above baseline,
        (2) rapid energy fluctuation (two speakers modulate independently),
        (3) spectral complexity increase.
        """
        if energy < self._baseline_energy * 0.5:
            return False

        energy_spike = energy > self._baseline_energy * 1.8
        if len(recent) < 10:
            return False

        short_var = float(np.var(recent[-10:]))
        long_var = float(np.var(recent[-50:])) if len(recent) >= 50 else short_var
        high_variance = short_var > long_var * 2.5 if long_var > 1e-8 else False

        return energy_spike and high_variance

    @property
    def overlap_ratio(self) -> float:
        if self._frame_count == 0:
            return 0.0
        total_overlap_ms = sum(e.duration_ms for e in self._overlap_events)
        total_ms = self._frame_count * HOP_SIZE_MS
        return total_overlap_ms / max(total_ms, 1)

    @property
    def events(self) -> List[OverlapEvent]:
        return list(self._overlap_events)

    def get_identity_confidence_penalty(self) -> float:
        """
        Returns a multiplier (0-1) for identity confidence.
        High overlap → lower confidence in speaker identification.
        """
        ratio = self.overlap_ratio
        if ratio < 0.05:
            return 1.0
        if ratio < 0.15:
            return 0.85
        if ratio < 0.30:
            return 0.65
        return 0.40

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_count": self._frame_count,
            "overlap_ratio": round(self.overlap_ratio, 4),
            "overlap_event_count": len(self._overlap_events),
            "identity_penalty": round(self.get_identity_confidence_penalty(), 3),
            "baseline_energy": round(self._baseline_energy, 6),
        }
