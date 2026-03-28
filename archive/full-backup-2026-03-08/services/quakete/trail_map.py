"""
SOVEREIGN SWARM — Swarm-Wide Health Aggregation & Silent Fibre Detection
Patent Claim 26.1b–c: Trail Map and Silent Fibre Detection.

Aggregates FibreTrailEmission data across the swarm and detects
Fibres that have stopped emitting (atrophic dissipation risk).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models.quakete import FibreTrailEmission, QuaketeMode

from .constants import (
    COMMUNICATION_HEALTH_THRESHOLD,
    CRITICAL_HEALTH_THRESHOLD,
    SILENT_TIMEOUT_SECONDS,
    SURPLUS_THRESHOLD,
)


# =============================================================================
# FIBRE TRAIL MAP (Patent Claim 26.1b–c)
# =============================================================================


class FibreTrailMap:
    """
    Swarm-wide aggregation of FibreTrailEmission data.
    Tracks latest trail per Fibre, history, and silent Fibres.
    """

    def __init__(self) -> None:
        self._trails: dict[str, FibreTrailEmission] = {}
        self._trail_history: dict[str, list[FibreTrailEmission]] = {}
        self._silent_fibres: set[str] = set()
        self._ring_fibres: dict[str, set[str]] = {}

    # -------------------------------------------------------------------------
    # UPDATE
    # -------------------------------------------------------------------------

    def update(self, trail: FibreTrailEmission) -> None:
        """Store latest trail, add to history, remove from silent set."""
        fibre_id = trail.fibre_id
        self._trails[fibre_id] = trail

        if fibre_id not in self._trail_history:
            self._trail_history[fibre_id] = []
        self._trail_history[fibre_id].append(trail)
        if len(self._trail_history[fibre_id]) > 100:
            self._trail_history[fibre_id].pop(0)

        self._silent_fibres.discard(fibre_id)

        if trail.ring_id and trail.ring_partners:
            if trail.ring_id not in self._ring_fibres:
                self._ring_fibres[trail.ring_id] = set()
            self._ring_fibres[trail.ring_id].add(fibre_id)
            for partner in trail.ring_partners:
                self._ring_fibres[trail.ring_id].add(partner)

    # -------------------------------------------------------------------------
    # SILENT DETECTION
    # -------------------------------------------------------------------------

    def detect_silent_fibres(self, timeout: int = SILENT_TIMEOUT_SECONDS) -> list[str]:
        """
        Compare last trail timestamp to now for all fibres.
        Return list of fibre_ids with no trail in timeout seconds.
        Add them to _silent_fibres set.
        """
        now = datetime.now(timezone.utc)
        silent: list[str] = []

        for fibre_id, trail in list(self._trails.items()):
            emitted_at = trail.emitted_at
            if emitted_at.tzinfo is None:
                emitted_at = emitted_at.replace(tzinfo=timezone.utc)
            elapsed = (now - emitted_at).total_seconds()
            if elapsed >= timeout:
                silent.append(fibre_id)
                self._silent_fibres.add(fibre_id)

        return silent

    # -------------------------------------------------------------------------
    # SWARM HEALTH
    # -------------------------------------------------------------------------

    def get_swarm_health(self) -> dict:
        """
        Returns aggregate health metrics:
        total_fibres, healthy, requesting, donating, critical, silent,
        avg_health, min_health
        """
        total = len(self._trails)
        if total == 0:
            return {
                "total_fibres": 0,
                "healthy": 0,
                "requesting": 0,
                "donating": 0,
                "critical": 0,
                "silent": len(self._silent_fibres),
                "avg_health": 1.0,
                "min_health": 1.0,
            }

        healthy = 0
        requesting = 0
        donating = 0
        critical = 0
        health_sum = 0.0
        min_health = 1.0

        for fibre_id, trail in self._trails.items():
            h = trail.communication_health
            health_sum += h
            min_health = min(min_health, h)

            if fibre_id in self._silent_fibres:
                continue

            if trail.quakete_mode == QuaketeMode.REQUESTING or (
                h < COMMUNICATION_HEALTH_THRESHOLD and h >= CRITICAL_HEALTH_THRESHOLD
            ):
                requesting += 1
            elif trail.quakete_mode == QuaketeMode.DONATING:
                donating += 1
            elif trail.quakete_mode == QuaketeMode.CRITICAL or h < CRITICAL_HEALTH_THRESHOLD:
                critical += 1
            elif trail.quakete_mode in (QuaketeMode.NOMINAL, QuaketeMode.SURPLUS) or h >= SURPLUS_THRESHOLD:
                healthy += 1
            else:
                healthy += 1

        silent_count = len(self._silent_fibres)

        return {
            "total_fibres": total,
            "healthy": healthy,
            "requesting": requesting,
            "donating": donating,
            "critical": critical,
            "silent": silent_count,
            "avg_health": health_sum / total if total else 1.0,
            "min_health": min_health,
        }

    def get_fibre_health(self, fibre_id: str) -> Optional[float]:
        """Return communication_health for a fibre, or None if unknown."""
        trail = self._trails.get(fibre_id)
        if trail is None:
            return None
        return trail.communication_health

    def get_fibre_trail(self, fibre_id: str) -> Optional[FibreTrailEmission]:
        """Return the latest trail for a fibre, or None if unknown."""
        return self._trails.get(fibre_id)

    def get_ring_health(self, ring_id: str) -> dict:
        """Aggregate health of all fibres in that ring."""
        fibre_ids = self._ring_fibres.get(ring_id, set())
        if not fibre_ids:
            return {
                "ring_id": ring_id,
                "fibre_count": 0,
                "avg_health": 0.0,
                "min_health": 0.0,
                "fibre_healths": {},
            }

        healths: dict[str, float] = {}
        total = 0.0
        min_h = 1.0
        for fid in fibre_ids:
            trail = self._trails.get(fid)
            if trail:
                h = trail.communication_health
                healths[fid] = h
                total += h
                min_h = min(min_h, h)

        n = len(healths)
        return {
            "ring_id": ring_id,
            "fibre_count": n,
            "avg_health": total / n if n else 0.0,
            "min_health": min_h if n else 0.0,
            "fibre_healths": healths,
        }

    # -------------------------------------------------------------------------
    # MEMBER HEALTH VIEWS (S1: Silent Crisis Detector integration)
    # -------------------------------------------------------------------------

    async def get_all_member_health_views(self) -> list:
        """
        Generate MemberHealthView objects for all tracked fibres.
        Used by SilentFibreDetector for sweep operations.
        """
        from app.models.solutions import MemberHealthView

        now = datetime.now(timezone.utc)
        views = []

        for fibre_id, trail in self._trails.items():
            emitted_at = trail.emitted_at
            if emitted_at.tzinfo is None:
                emitted_at = emitted_at.replace(tzinfo=timezone.utc)

            hours_since = (now - emitted_at).total_seconds() / 3600

            # Compute trajectory from history
            trajectory = "unknown"
            history = self._trail_history.get(fibre_id, [])
            if len(history) >= 2:
                recent = [t.communication_health for t in history[-5:]]
                if len(recent) >= 2:
                    delta = recent[-1] - recent[0]
                    if delta > 0.05:
                        trajectory = "rising"
                    elif delta < -0.05:
                        trajectory = "declining"
                    else:
                        trajectory = "stable"

            # Compute deviation from norm
            deviation = 0.0
            if len(history) >= 10:
                avg_interval = sum(
                    (history[i].emitted_at - history[i - 1].emitted_at).total_seconds()
                    for i in range(1, len(history))
                ) / (len(history) - 1)
                if avg_interval > 0:
                    current_interval = (now - emitted_at).total_seconds()
                    deviation = current_interval / avg_interval

            # Compute interaction frequency
            freq_7d = 0.0
            freq_30d = 0.0
            for h in history:
                h_emitted = h.emitted_at
                if h_emitted.tzinfo is None:
                    h_emitted = h_emitted.replace(tzinfo=timezone.utc)
                days_ago = (now - h_emitted).total_seconds() / 86400
                if days_ago <= 7:
                    freq_7d += 1
                if days_ago <= 30:
                    freq_30d += 1

            views.append(MemberHealthView(
                member_id=fibre_id,
                last_interaction=emitted_at,
                hours_since_interaction=hours_since,
                c_emo_at_last_interaction=trail.communication_health,
                c_emo_trajectory=trajectory,
                interaction_frequency_7d=freq_7d,
                interaction_frequency_30d=freq_30d,
                deviation_from_norm=deviation,
            ))

        return views

    @property
    def silent_fibres(self) -> set[str]:
        """Set of fibre_ids currently considered silent."""
        return self._silent_fibres.copy()
