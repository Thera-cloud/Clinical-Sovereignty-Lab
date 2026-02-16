"""
SOVEREIGN SWARM — Couple Resonance Monitor (S10)
Detects oscillation peaks in couples' Quakete frequency coupling
to identify moments of relational approach within withdrawal patterns.

Applied Solution S10: Nevedal-Quakete Resonance Bridge in Couples Work.
"""

import asyncio
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.models.solutions import CoupleResonanceMonitor, OscillationPeak

logger = logging.getLogger("couple_resonance")


class CoupleResonanceService:
    """
    Monitors Quakete frequency coupling between couples.
    Detects oscillation peaks in the withdrawer's frequency that
    indicate moments of approach even during withdrawal patterns.
    """

    def __init__(self, nevedal_engine=None, trail_map=None):
        self._nevedal = nevedal_engine
        self._trail_map = trail_map
        self._active_monitors: Dict[str, CoupleResonanceMonitor] = {}

    async def start_monitoring(
        self,
        partner_a_id: str,
        partner_b_id: str,
        partner_a_role: str = "pursuer",
        partner_b_role: str = "withdrawer",
    ) -> CoupleResonanceMonitor:
        """Start monitoring a couple's Quakete frequency coupling."""
        monitor = CoupleResonanceMonitor(
            partner_a_id=partner_a_id,
            partner_b_id=partner_b_id,
            partner_a_role=partner_a_role,
            partner_b_role=partner_b_role,
        )
        self._active_monitors[monitor.monitor_id] = monitor
        logger.info(
            "Couple monitoring started: %s (pursuer=%s, withdrawer=%s)",
            monitor.monitor_id, partner_a_id, partner_b_id,
        )
        return monitor

    async def update_frequencies(
        self,
        monitor_id: str,
        freq_a: float,
        freq_b: float,
        message_text: Optional[str] = None,
    ) -> Optional[CoupleResonanceMonitor]:
        """
        Update frequency readings for both partners.
        Detect oscillation peaks in the withdrawer.
        """
        monitor = self._active_monitors.get(monitor_id)
        if not monitor:
            return None

        now = datetime.utcnow().isoformat()

        # Record frequencies
        monitor.frequency_history_a.append((now, freq_a))
        monitor.frequency_history_b.append((now, freq_b))

        # Keep history manageable
        if len(monitor.frequency_history_a) > 500:
            monitor.frequency_history_a = monitor.frequency_history_a[-500:]
        if len(monitor.frequency_history_b) > 500:
            monitor.frequency_history_b = monitor.frequency_history_b[-500:]

        # Compute coupling coefficient
        coupling = self._compute_coupling(monitor)
        monitor.coupling_history.append((now, coupling))
        if len(monitor.coupling_history) > 500:
            monitor.coupling_history = monitor.coupling_history[-500:]

        # Detect peaks in withdrawer's frequency
        peak = self._detect_peak(monitor, freq_b, message_text)
        if peak:
            monitor.detected_peaks.append(peak)

            # Generate insight
            monitor.coupling_insight = self._generate_coupling_insight(monitor, peak)

        return monitor

    def _compute_coupling(self, monitor: CoupleResonanceMonitor) -> float:
        """
        Compute the coupling coefficient between two partners.
        High coupling = frequencies moving together.
        """
        if len(monitor.frequency_history_a) < 5 or len(monitor.frequency_history_b) < 5:
            return 0.0

        recent_a = [f for _, f in monitor.frequency_history_a[-10:]]
        recent_b = [f for _, f in monitor.frequency_history_b[-10:]]

        n = min(len(recent_a), len(recent_b))
        if n < 2:
            return 0.0

        # Correlation-based coupling
        mean_a = sum(recent_a[:n]) / n
        mean_b = sum(recent_b[:n]) / n

        covariance = sum(
            (recent_a[i] - mean_a) * (recent_b[i] - mean_b) for i in range(n)
        ) / n

        std_a = math.sqrt(sum((a - mean_a) ** 2 for a in recent_a[:n]) / n)
        std_b = math.sqrt(sum((b - mean_b) ** 2 for b in recent_b[:n]) / n)

        if std_a < 0.001 or std_b < 0.001:
            return 0.0

        return max(-1.0, min(1.0, covariance / (std_a * std_b)))

    def _detect_peak(
        self,
        monitor: CoupleResonanceMonitor,
        current_freq_b: float,
        message_text: Optional[str] = None,
    ) -> Optional[OscillationPeak]:
        """
        Detect oscillation peaks in the withdrawer's frequency.
        A peak = sudden increase above the rolling average.
        """
        if len(monitor.frequency_history_b) < 10:
            return None

        recent = [f for _, f in monitor.frequency_history_b[-20:]]
        avg = sum(recent[:-1]) / len(recent[:-1])
        current = recent[-1]

        # Peak threshold: 1.5 standard deviations above average
        std = math.sqrt(sum((f - avg) ** 2 for f in recent[:-1]) / len(recent[:-1]))
        threshold = avg + 1.5 * std

        if current > threshold and std > 0.01:
            peak = OscillationPeak(
                peak_magnitude=current - avg,
                peak_duration_seconds=5.0,  # Approximate from frequency
                correlated_message=message_text,
            )

            # Characterize the message
            if message_text:
                peak.message_characteristics = self._characterize_message(message_text)

            logger.info(
                "Oscillation peak detected: monitor=%s magnitude=%.3f",
                monitor.monitor_id, peak.peak_magnitude,
            )
            return peak

        return None

    def _characterize_message(self, text: str) -> str:
        """Characterize the message that correlated with a frequency peak."""
        lower = text.lower()
        if any(w in lower for w in ["feel", "emotion", "heart", "inside"]):
            return "emotional_disclosure"
        if any(w in lower for w in ["sorry", "apologize", "wrong", "mistake"]):
            return "repair_attempt"
        if any(w in lower for w in ["miss", "need", "want", "wish"]):
            return "longing_expression"
        if any(w in lower for w in ["remember", "used to", "before"]):
            return "nostalgia"
        return "general"

    def _generate_coupling_insight(
        self, monitor: CoupleResonanceMonitor, peak: OscillationPeak
    ) -> str:
        """Generate a clinical insight from the coupling data."""
        if peak.message_characteristics == "emotional_disclosure":
            return (
                f"The withdrawer ({monitor.partner_b_role}) showed a frequency spike "
                f"during an emotional disclosure. This suggests approach behavior "
                f"within the withdrawal pattern — a critical therapeutic moment."
            )
        if peak.message_characteristics == "repair_attempt":
            return (
                f"Frequency coupling increased during a repair attempt. "
                f"The withdrawer is reaching — encourage the pursuer to soften."
            )
        if peak.message_characteristics == "longing_expression":
            return (
                f"The withdrawer expressed longing, with a corresponding frequency peak. "
                f"This is a window into the attachment need beneath the withdrawal."
            )
        return (
            f"Oscillation peak detected in the withdrawer's frequency. "
            f"Coupling coefficient: {monitor.coupling_history[-1][1]:.2f}. "
            f"This may indicate an approach moment."
        )

    async def stop_monitoring(self, monitor_id: str) -> Optional[CoupleResonanceMonitor]:
        """Stop monitoring and return the final monitor state."""
        return self._active_monitors.pop(monitor_id, None)

    def get_active_monitors(self) -> List[str]:
        """Get all active monitor IDs."""
        return list(self._active_monitors.keys())
