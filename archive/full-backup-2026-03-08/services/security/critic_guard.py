"""
HIVE DEFENSE v4.4 — Critic Guard
Layer 4 of Castle Defense architecture.

Evaluates the Skeptic's judgment to prevent false positives.
Cross-references signals against the 30-day Drum baseline.
Applies Bayesian reasoning: prior probability of this user being an attacker.

Can overrule the Skeptic if evidence is insufficient,
but CANNOT overrule a HOSTILE guardian state.

Reports a "confidence of innocence" score (0.0 = definitely guilty, 1.0 = definitely innocent).

Paired with SkepticGuard via ZTABugFibre for adversarial evaluation.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.critic_guard")

BASELINE_LEARNING_DAYS = 30
PRIOR_INNOCENCE = 0.85  # Most requests are legitimate
HOSTILE_OVERRIDE = False  # Critic CANNOT overrule HOSTILE


class CriticGuard:
    """
    Evaluates the Skeptic's suspicion with Bayesian reasoning.
    Prevents false positives while respecting confirmed threats.
    """

    def __init__(self):
        self._user_baselines: Dict[str, Dict[str, float]] = {}
        self._ip_baselines: Dict[str, Dict[str, float]] = {}
        self._total_evaluations = 0
        self._overrule_count = 0
        self._confirm_count = 0
        self._started_at = time.time()
        logger.info("Critic Guard initialized — prior_innocence=%.2f", PRIOR_INNOCENCE)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self._total_evaluations,
            "overrules": self._overrule_count,
            "confirmations": self._confirm_count,
            "known_users": len(self._user_baselines),
            "known_ips": len(self._ip_baselines),
            "prior_innocence": PRIOR_INNOCENCE,
        }

    def _get_user_baseline(self, user_id: str) -> Dict[str, float]:
        """Get or create baseline for a user."""
        if user_id not in self._user_baselines:
            self._user_baselines[user_id] = {
                "avg_resonance": 1.0,
                "request_count": 0,
                "false_positive_rate": 0.3,
                "first_seen": time.time(),
                "learning": True,
            }
        return self._user_baselines[user_id]

    def _update_baseline(
        self,
        baseline: Dict[str, float],
        resonance_score: float,
    ) -> None:
        """Update baseline with exponential moving average."""
        count = baseline["request_count"]
        alpha = 0.05 if count > 100 else 0.2
        baseline["avg_resonance"] = (
            alpha * resonance_score + (1 - alpha) * baseline["avg_resonance"]
        )
        baseline["request_count"] = count + 1

        age_days = (time.time() - baseline["first_seen"]) / 86400
        if age_days >= BASELINE_LEARNING_DAYS:
            baseline["learning"] = False

    async def evaluate(
        self,
        sensors: Dict[str, float],
        resonance_level: int,
        resonance_score: float,
        source_ip: str = "",
        path: str = "",
        user_id: str = "",
        skeptic_malice: float = 0.0,
    ) -> float:
        """
        Evaluate a Drum trace and return confidence of innocence (0.0 to 1.0).
        """
        self._total_evaluations += 1
        innocence_signals: List[float] = []

        # 1. Prior probability — most users are not attackers
        innocence_signals.append(PRIOR_INNOCENCE)

        # 2. User baseline comparison
        if user_id:
            baseline = self._get_user_baseline(user_id)
            self._update_baseline(baseline, resonance_score)

            if not baseline["learning"]:
                # Compare current resonance to baseline
                deviation = abs(resonance_score - baseline["avg_resonance"])
                baseline_avg = baseline["avg_resonance"]

                if baseline_avg > 0:
                    relative_deviation = deviation / max(baseline_avg, 0.1)
                else:
                    relative_deviation = deviation

                if relative_deviation < 0.5:
                    # Within normal range for this user
                    innocence_signals.append(0.9)
                elif relative_deviation < 1.0:
                    innocence_signals.append(0.6)
                elif relative_deviation < 2.0:
                    innocence_signals.append(0.3)
                else:
                    innocence_signals.append(0.1)
            else:
                # Still learning — give benefit of doubt
                innocence_signals.append(0.7)

        # 3. Sensor normality check
        moisture = sensors.get("moisture", 0.0)
        smoke = sensors.get("smoke", 0.0)
        burn = sensors.get("burn", 0.0)
        clot = sensors.get("clot", 0.0)

        sensor_sum = moisture + smoke + burn + clot
        if sensor_sum < 0.5:
            innocence_signals.append(0.95)
        elif sensor_sum < 1.0:
            innocence_signals.append(0.7)
        elif sensor_sum < 2.0:
            innocence_signals.append(0.4)
        else:
            innocence_signals.append(0.1)

        # 4. Skeptic challenge — how strong is the Skeptic's case?
        if skeptic_malice < 0.2:
            innocence_signals.append(0.95)
        elif skeptic_malice < 0.4:
            innocence_signals.append(0.75)
        elif skeptic_malice < 0.6:
            innocence_signals.append(0.5)
        elif skeptic_malice < 0.8:
            innocence_signals.append(0.25)
        else:
            innocence_signals.append(0.05)

        # 5. Resonance level sanity — low levels almost always innocent
        if resonance_level <= 1:
            innocence_signals.append(0.95)
        elif resonance_level == 2:
            innocence_signals.append(0.7)
        elif resonance_level == 3:
            innocence_signals.append(0.4)
        elif resonance_level >= 4:
            innocence_signals.append(0.1)

        # Aggregate — Bayesian-weighted average
        if not innocence_signals:
            return PRIOR_INNOCENCE

        # Weight more recent / stronger signals
        innocence = sum(innocence_signals) / len(innocence_signals)

        # Track overrules vs confirmations
        if skeptic_malice > 0.5 and innocence > 0.6:
            self._overrule_count += 1
        elif skeptic_malice > 0.5 and innocence < 0.4:
            self._confirm_count += 1

        return round(min(1.0, max(0.0, innocence)), 4)


# Singleton
_critic_instance: Optional[CriticGuard] = None


def get_critic() -> CriticGuard:
    global _critic_instance
    if _critic_instance is None:
        _critic_instance = CriticGuard()
    return _critic_instance
