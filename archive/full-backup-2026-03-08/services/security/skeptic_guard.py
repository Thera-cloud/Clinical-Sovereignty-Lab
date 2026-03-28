"""
HIVE DEFENSE v4.4 — Skeptic Guard
Layer 4 of Castle Defense architecture.

Assumes every signal is potentially malicious until proven otherwise.
Applies 1.5x stricter thresholds than the standard GuardianFibre.
Specializes in detecting sophisticated attacks that mimic normal behavior.

Reports a "confidence of malice" score (0.0 = definitely safe, 1.0 = definitely malicious).

Paired with CriticGuard via ZTABugFibre for adversarial evaluation.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.skeptic_guard")

SENSITIVITY_MULTIPLIER = 1.5
RESONANCE_MALICE_MAP = {
    1: 0.05,   # OBSERVE
    2: 0.25,   # ALERT
    3: 0.55,   # INVESTIGATE
    4: 0.80,   # RESTRICT
    5: 0.95,   # LOCKDOWN
}

SUSPICIOUS_PATH_KEYWORDS = frozenset({
    "admin", "config", "env", "secret", "key", "token",
    "password", "credential", "dump", "export", "backup",
    "debug", "trace", "internal", "migration", "shell",
})

SUSPICIOUS_TIMING_WINDOW_SEC = 2.0  # Requests faster than this are suspicious
MAX_RAPID_REQUESTS = 5


class SkepticGuard:
    """
    Assumes malice. Every signal gets scrutinized with paranoid thresholds.
    """

    def __init__(self):
        self._ip_history: Dict[str, List[float]] = defaultdict(list)
        self._user_history: Dict[str, List[float]] = defaultdict(list)
        self._total_evaluations = 0
        self._high_malice_count = 0
        logger.info("Skeptic Guard initialized — sensitivity=%.1fx", SENSITIVITY_MULTIPLIER)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self._total_evaluations,
            "high_malice_detections": self._high_malice_count,
            "sensitivity_multiplier": SENSITIVITY_MULTIPLIER,
            "tracked_ips": len(self._ip_history),
        }

    async def evaluate(
        self,
        sensors: Dict[str, float],
        resonance_level: int,
        resonance_score: float,
        source_ip: str = "",
        path: str = "",
        user_id: str = "",
    ) -> float:
        """
        Evaluate a Drum trace and return confidence of malice (0.0 to 1.0).
        """
        self._total_evaluations += 1
        malice_signals: List[float] = []

        # 1. Resonance level mapping (with paranoid multiplier)
        base_malice = RESONANCE_MALICE_MAP.get(resonance_level, 0.0)
        malice_signals.append(min(1.0, base_malice * SENSITIVITY_MULTIPLIER))

        # 2. Sensor anomaly scoring
        moisture = sensors.get("moisture", 0.0)
        smoke = sensors.get("smoke", 0.0)
        burn = sensors.get("burn", 0.0)
        clot = sensors.get("clot", 0.0)

        if moisture > 0.5:
            malice_signals.append(min(1.0, moisture * SENSITIVITY_MULTIPLIER))
        if smoke > 0.3:
            malice_signals.append(min(1.0, smoke * SENSITIVITY_MULTIPLIER))
        if burn > 0.4:
            malice_signals.append(min(1.0, burn * 1.8))
        if clot > 0.3:
            malice_signals.append(min(1.0, clot * SENSITIVITY_MULTIPLIER))

        # 3. Path suspicion
        path_lower = path.lower()
        path_suspicion = sum(
            1 for kw in SUSPICIOUS_PATH_KEYWORDS if kw in path_lower
        )
        if path_suspicion > 0:
            malice_signals.append(min(1.0, path_suspicion * 0.2))

        # 4. Timing analysis — rapid-fire requests from same IP
        if source_ip:
            now = time.time()
            history = self._ip_history[source_ip]
            history.append(now)
            # Keep only last 30 seconds
            history[:] = [t for t in history if t > now - 30]
            rapid = sum(
                1 for i in range(1, len(history))
                if history[i] - history[i - 1] < SUSPICIOUS_TIMING_WINDOW_SEC
            )
            if rapid >= MAX_RAPID_REQUESTS:
                malice_signals.append(0.7)

        # 5. User behavioral consistency
        if user_id:
            now = time.time()
            u_history = self._user_history[user_id]
            u_history.append(now)
            u_history[:] = [t for t in u_history if t > now - 60]
            if len(u_history) > 30:
                malice_signals.append(0.4)

        # Aggregate — take the weighted max (paranoid: max matters most)
        if not malice_signals:
            return 0.0

        max_signal = max(malice_signals)
        avg_signal = sum(malice_signals) / len(malice_signals)
        # Skeptic weights max heavily
        malice = 0.7 * max_signal + 0.3 * avg_signal

        if malice > 0.6:
            self._high_malice_count += 1

        return round(min(1.0, malice), 4)


# Singleton
_skeptic_instance: Optional[SkepticGuard] = None


def get_skeptic() -> SkepticGuard:
    global _skeptic_instance
    if _skeptic_instance is None:
        _skeptic_instance = SkepticGuard()
    return _skeptic_instance
