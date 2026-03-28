from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional


@dataclass
class CoherenceTimeCrystal:
    """Temporal crystal used for predictive emotional cycle recall."""

    user_id: str
    crystal_ids: List[str] = field(default_factory=list)
    period_days: float = 7.0
    phase_offset_days: float = 0.0
    temporal_confidence: float = 0.60
    activation_count: int = 0
    total_predictions: int = 0
    prediction_accuracy: float = 0.0
    synthesized_meaning: str = ""
    therapeutic_implication: str = ""
    signal: str = "PROVISIONAL"
    next_activation_at: Optional[datetime] = None
    last_activation_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def predict_next_activation(self) -> datetime:
        now = datetime.now(timezone.utc)
        if self.last_activation_at:
            return self.last_activation_at + timedelta(days=self.period_days)
        return now + timedelta(days=max(0.0, self.period_days - self.phase_offset_days))

    def reinforce(self, activation_occurred: bool) -> "CoherenceTimeCrystal":
        self.total_predictions += 1
        if activation_occurred:
            self.activation_count += 1
            self.temporal_confidence = min(0.95, self.temporal_confidence + 0.03)
            self.last_activation_at = datetime.now(timezone.utc)
            self.next_activation_at = self.predict_next_activation()
        else:
            self.temporal_confidence = max(0.30, self.temporal_confidence - 0.02)

        if self.total_predictions > 0:
            self.prediction_accuracy = self.activation_count / float(self.total_predictions)
        self.signal = self._classify_signal()
        self.updated_at = datetime.now(timezone.utc)
        return self

    @property
    def is_active(self) -> bool:
        return self.temporal_confidence >= 0.50

    @property
    def days_until_activation(self) -> float:
        if not self.next_activation_at:
            return float("inf")
        delta = self.next_activation_at - datetime.now(timezone.utc)
        return max(0.0, delta.total_seconds() / 86400.0)

    @property
    def should_trigger_outreach(self) -> bool:
        return self.is_active and self.temporal_confidence >= 0.70 and self.days_until_activation <= 2.0

    def _classify_signal(self) -> str:
        if self.temporal_confidence >= 0.95:
            return "SOVEREIGN"
        if self.temporal_confidence >= 0.85:
            return "LOCKED"
        if self.temporal_confidence >= 0.75:
            return "PROMOTED"
        if self.temporal_confidence >= 0.60:
            return "PROVISIONAL"
        return "NOISE"
