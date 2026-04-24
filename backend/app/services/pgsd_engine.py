"""
Planetary Galactic Scale Detector (PGSD) Computation Engine
============================================================

A NEW measurement system, separate from the Nevedal Coherence Engine,
based on:
  - Trans-Dimensional Unified Field Theory (TDUFT)  — Ducas's framework
  - Timescape model                                  — Wiltshire's inhomogeneous cosmology
  - Quantum Trace mechanics                          — density operators / partial traces / Lindblad
  - 5D Spatio-Temporal modeling                      — therapeutic landscape geometry

The PGSD unifies these into a single per-user state ("emotional GPS pin")
that complements (but does not replace) C_emo / GAP / Quantum metrics from
the Nevedal engine.

This module is intentionally SELF-CONTAINED: it does NOT import or depend
on any other CSL service module. It only depends on the Python stdlib
(plus an optional asyncpg-style db_pool passed in at construction time).

Located in: backend/app/services/pgsd_engine.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1 — TDUFT CORE FORMULAS
# ═══════════════════════════════════════════════════════════════════════


class TDUFTComputer:
    """
    Trans-Dimensional Unified Field Theory calculations.

    Maps therapeutic dimensions to Ducas's framework where
    D = dimensions, T = time, V = velocity:

        M    = D³T²        (therapeutic mass)
        G    = 1/T⁴        (pattern gravity)
        E    = D⁵ = MC²    (therapeutic energy)
        V    = D/T         (therapeutic velocity)
        ρ_T  = T²          (time density)
        Noah Factor: Δt_ext / Δτ = D^(1/4)
    """

    def compute_therapeutic_mass(
        self,
        active_dimensions: int,
        time_density_days: float,
    ) -> float:
        """
        M = D³T²

        active_dimensions:    count of crystal domains with active crystals
                              (clinical, coaching, shame_resilience,
                              connection, activation, grounding, identity,
                              attachment, etc.)
        time_density_days:    weighted average age of crystals in active
                              domains (days since oldest crystal per
                              domain, averaged)
        """
        D3 = active_dimensions ** 3
        T2 = (time_density_days / 30.0) ** 2  # normalize to months
        return round(D3 * T2, 2)

    def compute_pattern_gravity(self, therapeutic_time_months: float) -> float:
        """
        G = 1/T⁴

        therapeutic_time_months: months of active work on this specific
                                 pattern. Returns a 0-1 clamped gravity
                                 pull (newer patterns have stronger pull).
        """
        if therapeutic_time_months <= 0:
            return 1.0
        T4 = therapeutic_time_months ** 4
        G = 1.0 / T4
        return round(min(1.0, G), 4)

    def compute_therapeutic_energy(self, active_dimensions: int) -> float:
        """
        E = D⁵

        Total transformative potential available to the client given the
        breadth of dimensions currently in motion.
        """
        return round(active_dimensions ** 5, 2)

    def compute_velocity(
        self,
        dimensional_change: float,
        time_period_days: float,
    ) -> float:
        """
        V = D/T

        dimensional_change: net change in active dimensions or crystal
                            count over the period
        time_period_days:   the time period measured
        """
        if time_period_days <= 0:
            return 0.0
        return round(dimensional_change / (time_period_days / 30.0), 3)

    def compute_time_density(
        self,
        session_engagement: float,
        crystal_yield: int,
        incongruence_count: int,
        voice_emotion_variety: int,
    ) -> float:
        """
        ρ_T = T² (enhanced with multi-modal data)

        Measures how therapeutically dense a single session was.
        Returns a 0-10 scale.
        """
        base = session_engagement * 3.0  # 0-3
        crystal_bonus = min(3.0, crystal_yield * 0.75)
        incongruence_bonus = min(2.0, incongruence_count * 0.5)
        voice_bonus = min(2.0, voice_emotion_variety * 0.4)
        raw = base + crystal_bonus + incongruence_bonus + voice_bonus
        return round(min(10.0, raw), 2)

    def compute_noah_factor(
        self,
        temporal_span_years: float,
        session_duration_minutes: float,
    ) -> float:
        """
        Noah Factor: Δt_ext / Δτ = D^(1/4)

        temporal_span_years:      span of history accessed in this session
                                  (from crystal temporal references)
        session_duration_minutes: actual session length
        """
        if session_duration_minutes <= 0:
            return 0.0
        ext_minutes = temporal_span_years * 525600  # years to minutes
        ratio = ext_minutes / session_duration_minutes
        return round(ratio ** 0.25, 3)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2 — TIMESCAPE MODEL
# ═══════════════════════════════════════════════════════════════════════


class TimescapeComputer:
    """
    Therapeutic Timescape: an inhomogeneous emotional cosmology.

    Dense emotional regions (active trauma) experience slower therapeutic
    time flow than void regions (resolved, growth territory).

    Based on Wiltshire's Timescape model where ~35% time dilation occurs
    in dense galactic structures.
    """

    TIME_DILATION_FACTOR = 0.35  # ~35% slower in dense regions

    def compute_void_fraction(
        self,
        total_domains: int,
        resolved_domains: int,
    ) -> float:
        """
        f_v = resolved / total

        Void fraction: what percentage of the therapeutic landscape is
        "open" (resolved, growth territory) vs "dense" (active wounds).

        resolved_domains: domains where avg crystal confidence > 0.7 AND
                          no shame/crisis flags in the last 30 days
        total_domains:    all domains with any crystal
        """
        if total_domains <= 0:
            return 0.0
        return round(resolved_domains / total_domains, 3)

    def compute_time_dilation(self, void_fraction: float) -> float:
        """
        δ_T = 1 - (TIME_DILATION_FACTOR * (1 - f_v))

        When void_fraction = 0 (all dense): δ_T = 0.65 (35% slower)
        When void_fraction = 1 (all void):  δ_T = 1.00 (no dilation)

        Returns the effective time-flow rate, clamped to [0.65, 1.0].
        """
        dense_fraction = 1.0 - void_fraction
        dilation = 1.0 - (self.TIME_DILATION_FACTOR * dense_fraction)
        return round(max(0.65, min(1.0, dilation)), 3)

    def compute_effective_therapeutic_time(
        self,
        clock_time_minutes: float,
        time_dilation: float,
    ) -> float:
        """
        How many "effective therapeutic minutes" were experienced in the
        given clock time, after applying time dilation.
        """
        return round(clock_time_minutes * time_dilation, 1)

    def classify_session_region(
        self,
        time_density: float,
        engagement: float,
        crystal_yield: int,
    ) -> str:
        """
        Was this session in a dense region or a void region?

        Returns one of: "void", "transition", "dense".
        """
        density_score = (
            (time_density / 10.0) * 0.4
            + engagement * 0.4
            + min(1.0, crystal_yield / 3.0) * 0.2
        )

        if density_score > 0.7:
            return "void"        # productive, fast-moving
        elif density_score > 0.4:
            return "transition"  # between dense and void
        else:
            return "dense"       # slow, heavy processing


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3 — QUANTUM TRACE MODEL
# ═══════════════════════════════════════════════════════════════════════


class QuantumTraceComputer:
    """
    Quantum Trace mechanics for emotional state representation, partial
    traces, and Lindblad evolution tracking.

    The density operator ρ represents the full emotional state as a
    matrix. Partial traces separate the individual from the environment
    (family, system, culture).
    """

    DIMENSIONS = [
        "shame", "attachment", "grief", "trust",
        "identity", "resilience", "connection",
        "activation", "grounding", "integration",
    ]

    # Knowledge-domain → emotional-dimension routing for the additive
    # crystal-mass contribution. Crystal domains are KNOWLEDGE categories
    # (clinical, coaching, crisis, …); emotional dimensions are STATES.
    # The mapping is best-effort; weights are tuned so knowledge tilts the
    # population vector but never dominates the direct state signal.
    _CRYSTAL_DOMAIN_MAP = {
        "clinical": ("identity", 0.10),
        "coaching": ("activation", 0.10),
        "crisis": ("grounding", 0.20),
        "liminal_resolve": ("integration", 0.10),
        "ln_self_curiosity": ("identity", 0.05),
        "research": ("integration", 0.05),
        "culture": ("connection", 0.05),
        "marketing": ("connection", 0.03),
        "defense": ("trust", 0.05),
        "general": ("integration", 0.03),
    }

    def compute_density_matrix(
        self,
        crystal_domains: Dict[str, float],
        c_emo: float,
        gap: float,
        quantum: float,
        voice_emotion: Optional[Dict] = None,
        facial_summary: Optional[Dict] = None,
        metrics: Optional[Dict] = None,
    ) -> Dict:
        """
        Build the density operator ρ from all available multi-modal data.

        Returns a simplified representation (not a full matrix — we store
        diagonal elements + a scalar coherence summary of the off-diagonal
        coherences).

        crystal_domains: {domain: avg_confidence} — knowledge categories
        voice_emotion:   {emotion: proportion} or {"dominant_emotion": ...}
        facial_summary:  {avg_engagement, gaze_aversion_ratio}
        metrics:         client_metrics row dict (anxiety, stress, depression,
                         shame_profile, engagement) — required for non-zero
                         emotional populations. Without it, populations fall
                         back to the legacy crystal-domain key match (which
                         almost never matches and yields all zeros).
        """
        populations = self._derive_emotional_populations(
            metrics or {}, voice_emotion, facial_summary,
            c_emo, gap, quantum,
        )

        # Additive knowledge contribution from crystal domains (small).
        if crystal_domains:
            for dom, conf in crystal_domains.items():
                mapping = self._CRYSTAL_DOMAIN_MAP.get(str(dom).lower())
                if mapping:
                    target_dim, weight = mapping
                    bump = float(conf or 0.0) * weight
                    populations[target_dim] = min(
                        1.0, populations.get(target_dim, 0.0) + bump
                    )

        coherence = self._compute_coherence(
            c_emo, gap, quantum, voice_emotion, facial_summary
        )

        # Trace must equal 1 — normalize the diagonal.
        total = sum(populations.values())
        if total > 0:
            for k in populations:
                populations[k] = round(populations[k] / total, 4)
        else:
            # Truly no signal at all — uniform prior so the heatmap renders
            # something interpretable rather than blank black squares.
            uniform = round(1.0 / len(self.DIMENSIONS), 4)
            populations = {dim: uniform for dim in self.DIMENSIONS}

        return {
            "populations": populations,
            "coherence": coherence,
            "trace": round(sum(populations.values()), 4),
            "purity": self._compute_purity(populations, coherence),
            "timestamp": None,  # set by caller
        }

    def _derive_emotional_populations(
        self,
        metrics: Dict,
        voice: Optional[Dict],
        facial: Optional[Dict],
        c_emo: float,
        gap: float,
        quantum: float,
    ) -> Dict[str, float]:
        """Map real client state signals to the 10 emotional dimensions.

        anxiety / stress / depression in client_metrics are 0–10 scales;
        c_emo / gap / quantum / engagement are 0–1. We normalize everything
        to 0–1 before populating the diagonal.
        """
        anx = max(0.0, min(1.0, float(metrics.get("anxiety", 0.0)) / 10.0))
        stress = max(0.0, min(1.0, float(metrics.get("stress", 0.0)) / 10.0))
        depr = max(0.0, min(1.0, float(metrics.get("depression", 0.0)) / 10.0))
        engage = max(0.0, min(1.0, float(metrics.get("avg_engagement", 0.5))))
        shame_profile = metrics.get("shame_profile") or {}
        shame_idx = float(shame_profile.get("shame_index", 0.0)) if isinstance(shame_profile, dict) else 0.0
        shame = max(0.0, min(1.0, shame_idx if shame_idx > 0 else stress * 0.5))

        # Voice incongruence widens grief; facial gaze aversion widens shame.
        voice_negative = 0.0
        if voice:
            for k in ("sad", "angry", "anxious", "fearful"):
                voice_negative += float(voice.get(k, 0.0) or 0.0)
            voice_negative = min(1.0, voice_negative)
        gaze_aversion = float((facial or {}).get("gaze_aversion_ratio", 0.0) or 0.0)

        return {
            "shame":       round(min(1.0, shame + 0.3 * gaze_aversion), 4),
            "attachment":  round(max(0.0, 1.0 - anx), 4),
            "grief":       round(min(1.0, depr + 0.3 * voice_negative), 4),
            "trust":       round(max(0.0, c_emo), 4),
            "identity":    round(max(0.0, quantum), 4),
            "resilience":  round(max(0.0, 1.0 - stress), 4),
            "connection":  round(engage, 4),
            "activation":  round(max(0.0, gap), 4),
            "grounding":   round(max(0.0, 1.0 - anx), 4),
            "integration": round(max(0.0, quantum * (1.0 - voice_negative * 0.5)), 4),
        }

    def _compute_coherence(
        self,
        c_emo: float,
        gap: float,
        quantum: float,
        voice: Optional[Dict],
        facial: Optional[Dict],
    ) -> float:
        """
        Multi-modal coherence: how aligned are all signals?

        High coherence = all modalities agree.
        Low coherence  = incongruence, mixed signals.
        """
        signals: List[float] = [float(c_emo), float(gap), float(quantum)]

        if voice and voice.get("dominant_emotion"):
            positive = ["happy", "engaged", "neutral"]
            voice_val = 0.7 if voice["dominant_emotion"] in positive else 0.3
            signals.append(voice_val)

        if facial:
            engagement = float(facial.get("avg_engagement", 0.5))
            aversion = float(facial.get("gaze_aversion_ratio", 0.5))
            facial_val = engagement * (1.0 - aversion)
            signals.append(facial_val)

        if not signals:
            return 0.5

        mean = sum(signals) / len(signals)
        variance = sum((s - mean) ** 2 for s in signals) / len(signals)
        return round(max(0.0, 1.0 - variance * 4), 3)

    def _compute_purity(
        self,
        populations: Dict[str, float],
        coherence: float,
    ) -> float:
        """
        Tr(ρ²) — purity of the quantum state.

        Pure state  = 1 (fully coherent)
        Mixed state < 1 (decoherent)
        """
        sum_sq = sum(p ** 2 for p in populations.values())
        purity = sum_sq * (0.5 + 0.5 * coherence)
        return round(min(1.0, purity), 4)

    def compute_partial_trace(
        self,
        full_density: Dict,
        family_density: Optional[Dict] = None,
    ) -> Dict:
        """
        Trace out the family / environment to get the individual's
        intrinsic state:

            ρ_individual = Tr_env(ρ_full)
        """
        if not family_density:
            return {
                "individual_state": full_density.get("populations", {}),
                "environmental_coupling": 0.0,
                "decoupled": True,
            }

        individual: Dict[str, float] = {}
        coupling = 0.0
        family_pops = family_density.get("populations", {})

        for dim, pop in full_density.get("populations", {}).items():
            family_pop = float(family_pops.get(dim, 0.0))
            # Individual component = what remains after removing family
            # correlation.
            correlation = min(float(pop), family_pop)
            individual[dim] = round(max(0.0, float(pop) - correlation * 0.5), 4)
            coupling += correlation

        total = sum(individual.values())
        if total > 0:
            for k in individual:
                individual[k] = round(individual[k] / total, 4)

        n_dims = len(full_density.get("populations", {}))
        coupling_normalized = coupling / max(1, n_dims)

        return {
            "individual_state": individual,
            "environmental_coupling": round(coupling_normalized, 3),
            "decoupled": coupling_normalized < 0.2,
        }

    def compute_lindblad_evolution(
        self,
        current_density: Dict,
        previous_density: Dict,
        decoherence_events: int,
        therapeutic_interventions: int,
    ) -> Dict:
        """
        Track coherent evolution vs decoherence:

            dρ/dt = -i[H, ρ] + Σ ( LρL† - ½{L†L, ρ} )

        Simplified: measure the ratio of coherent change (therapeutic)
        to decoherent change (environmental disruption).
        """
        if not previous_density:
            return {"evolution": "initial", "fidelity": 1.0}

        curr_pops = current_density.get("populations", {})
        prev_pops = previous_density.get("populations", {})

        total_change = 0.0
        positive_change = 0.0
        negative_change = 0.0

        for dim in self.DIMENSIONS:
            delta = float(curr_pops.get(dim, 0)) - float(prev_pops.get(dim, 0))
            total_change += abs(delta)
            if delta > 0:
                positive_change += delta
            else:
                negative_change += abs(delta)

        curr_coh = float(current_density.get("coherence", 0.5))
        prev_coh = float(previous_density.get("coherence", 0.5))
        coherence_delta = curr_coh - prev_coh

        coherent_signal = therapeutic_interventions + max(0.0, coherence_delta * 10)
        decoherent_signal = decoherence_events + max(0.0, -coherence_delta * 10)

        total_signal = coherent_signal + decoherent_signal
        fidelity = coherent_signal / max(1.0, total_signal)

        if fidelity > 0.6:
            evolution = "coherent"
        elif fidelity < 0.4:
            evolution = "decoherent"
        else:
            evolution = "mixed"

        return {
            "evolution": evolution,
            "fidelity": round(fidelity, 3),
            "coherence_delta": round(coherence_delta, 4),
            "population_change": round(total_change, 4),
            "positive_change": round(positive_change, 4),
            "negative_change": round(negative_change, 4),
            "decoherence_events": decoherence_events,
            "therapeutic_interventions": therapeutic_interventions,
        }

    def compute_zero_time_route(
        self,
        origin_coordinate: Dict,
        destination_coordinate: Dict,
    ) -> Dict:
        """
        Map the zero-time route between two emotional coordinates.

        This is the dimensional path consciousness traverses when
        accessing a memory or projected future state.
        """
        origin_pops = origin_coordinate.get("populations", {})
        dest_pops = destination_coordinate.get("populations", {})

        distance = 0.0
        route_dimensions: List[Dict] = []

        for dim in self.DIMENSIONS:
            o = float(origin_pops.get(dim, 0))
            d = float(dest_pops.get(dim, 0))
            delta = abs(d - o)
            distance += delta ** 2
            if delta > 0.05:  # significant movement
                route_dimensions.append({
                    "dimension": dim,
                    "origin": round(o, 3),
                    "destination": round(d, 3),
                    "traversal": round(delta, 3),
                    "direction": "deeper" if d > o else "resolving",
                })

        distance = distance ** 0.5

        obstacles = [
            r for r in route_dimensions
            if r["direction"] == "deeper" and r["traversal"] > 0.15
        ]

        if len(route_dimensions) <= 2:
            complexity = "direct"
        elif len(route_dimensions) <= 4:
            complexity = "multi_dimensional"
        else:
            complexity = "complex"

        return {
            "dimensional_distance": round(distance, 4),
            "route_dimensions": sorted(
                route_dimensions, key=lambda x: x["traversal"], reverse=True
            ),
            "gravitational_obstacles": len(obstacles),
            "estimated_sessions": max(1, int(distance * 10)),
            "route_complexity": complexity,
        }


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4 — 5D SPATIO-TEMPORAL MODEL
# ═══════════════════════════════════════════════════════════════════════


class SpatioTemporalComputer:
    """
    5D spatio-temporal modeling of the therapeutic landscape.

    Tracks how the emotional space itself evolves, not just the client's
    position within it.

        D¹ = emotional valence  (positive ↔ negative)
        D² = arousal            (activation ↔ deactivation)
        D³ = relational         (connection ↔ isolation)
        D⁴ = temporal depth     (present ↔ historical)
        D⁵ = integration        (fragmented ↔ coherent)
    """

    def compute_5d_coordinate(
        self,
        c_emo: float,
        gap: float,
        quantum: float,
        voice_emotion: Optional[Dict] = None,
        facial_summary: Optional[Dict] = None,
        family_coherence: Optional[float] = None,
        noah_factor: float = 0.0,
        incongruence_ratio: float = 0.0,
    ) -> Dict:
        """Compute the client's current position in 5D therapeutic space."""

        # D1 — Emotional valence (-1 to +1)
        d1 = (float(c_emo) - 0.5) * 2  # map 0-1 to -1..+1
        if voice_emotion:
            positive = (
                float(voice_emotion.get("happy", 0))
                + float(voice_emotion.get("neutral", 0))
            )
            negative = (
                float(voice_emotion.get("sad", 0))
                + float(voice_emotion.get("angry", 0))
                + float(voice_emotion.get("anxious", 0))
                + float(voice_emotion.get("fearful", 0))
            )
            voice_valence = positive - negative
            d1 = d1 * 0.6 + voice_valence * 0.4

        # D2 — Arousal (0 to 1)
        d2 = float(gap)  # GAP already measures activation
        if facial_summary:
            engagement = float(facial_summary.get("avg_engagement", 0.5))
            d2 = d2 * 0.6 + engagement * 0.4

        # D3 — Relational (-1 to +1)
        if family_coherence is not None:
            d3 = (float(family_coherence) - 0.5) * 2
        else:
            d3 = (float(gap) - 0.5) * 2  # proxy from GAP

        # D4 — Temporal depth (0 to 10+)
        d4 = float(noah_factor)

        # D5 — Integration (0 to 1)
        d5 = float(quantum) * (1.0 - float(incongruence_ratio))

        return {
            "d1_valence": round(d1, 3),
            "d2_arousal": round(d2, 3),
            "d3_relational": round(d3, 3),
            "d4_temporal_depth": round(d4, 3),
            "d5_integration": round(d5, 3),
            "magnitude": round(
                (d1 ** 2 + d2 ** 2 + d3 ** 2 + d4 ** 2 + d5 ** 2) ** 0.5, 3
            ),
        }

    def compute_latent_trajectory(
        self,
        coordinate_history: List[Dict],
        window: int = 10,
    ) -> Dict:
        """
        Reduce coordinate history to latent dynamics.

        Identifies the principal direction of movement and hidden patterns.
        """
        if len(coordinate_history) < 3:
            return {"trajectory": "insufficient_data"}

        recent = coordinate_history[-window:]

        dims = [
            "d1_valence", "d2_arousal", "d3_relational",
            "d4_temporal_depth", "d5_integration",
        ]
        velocities: Dict[str, float] = {}

        for dim in dims:
            values = [float(c.get(dim, 0)) for c in recent]
            if len(values) >= 2:
                velocity = (values[-1] - values[0]) / len(values)
                velocities[dim] = round(velocity, 4)

        if not velocities:
            return {"trajectory": "insufficient_data"}

        max_dim = max(velocities, key=lambda k: abs(velocities[k]))

        magnitudes = [float(c.get("magnitude", 0)) for c in recent]
        mean_mag = sum(magnitudes) / len(magnitudes)
        variance = sum((m - mean_mag) ** 2 for m in magnitudes) / len(magnitudes)

        return {
            "velocities": velocities,
            "dominant_dimension": max_dim,
            "dominant_velocity": velocities[max_dim],
            "direction": "positive" if velocities[max_dim] > 0 else "negative",
            "stability": round(1.0 - min(1.0, variance), 3),
            "predicted_next": self._predict_next(recent, velocities, dims),
        }

    def _predict_next(
        self,
        recent: List[Dict],
        velocities: Dict[str, float],
        dims: List[str],
    ) -> Dict[str, float]:
        """Simple linear prediction of the next coordinate."""
        last = recent[-1]
        predicted: Dict[str, float] = {}
        for dim in dims:
            current = float(last.get(dim, 0))
            vel = float(velocities.get(dim, 0))
            predicted[dim] = round(current + vel, 3)
        return predicted

    def compute_emotional_fingerprint(
        self,
        coordinate: Dict,
        density_matrix: Dict,
        mass: float,
        gravity: float,
        void_fraction: float,
        noah_factor: float,
    ) -> str:
        """
        Generate a unique emotional fingerprint hash from the full PGSD
        state. This is the "GPS pin" — unique to this individual at this
        moment.
        """
        fingerprint_data = {
            "coordinate": coordinate,
            "density_diagonal": density_matrix.get("populations", {}),
            "coherence": density_matrix.get("coherence", 0),
            "mass": mass,
            "gravity": gravity,
            "void_fraction": void_fraction,
            "noah_factor": noah_factor,
        }

        data_str = json.dumps(fingerprint_data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5 — UNIFIED PGSD CALCULATOR
# ═══════════════════════════════════════════════════════════════════════


class PGSDEngine:
    """
    Planetary Galactic Scale Detector.

    Unifies TDUFT, Timescape, Quantum Trace, and 5D Spatio-Temporal into
    a single per-user measurement.
    """

    def __init__(self, db_pool: Any = None):
        self.db = db_pool
        self.tduft = TDUFTComputer()
        self.timescape = TimescapeComputer()
        self.trace = QuantumTraceComputer()
        self.spatial = SpatioTemporalComputer()

    async def compute_full_pgsd(self, user_id: str) -> Dict:
        """
        Compute the complete PGSD state for a user.

        Pulls from all available data sources. Gracefully degrades when
        any data source (or the db pool itself) is unavailable.
        """
        crystals = await self._load_crystal_data(user_id)
        metrics = await self._load_metrics(user_id)
        sessions = await self._load_session_data(user_id)
        family = await self._load_family_data(user_id)
        multimodal = await self._load_multimodal(user_id)

        # ─── TDUFT ───────────────────────────────────────────────────
        active_dims = len(crystals.get("domains", {}))
        time_density_days = float(crystals.get("avg_age_days", 0) or 0)
        mass = self.tduft.compute_therapeutic_mass(active_dims, time_density_days)

        session_count = int(metrics.get("session_count", 0) or 0)
        months = session_count / 4.0  # ~4 sessions per month
        gravity = self.tduft.compute_pattern_gravity(months)
        energy = self.tduft.compute_therapeutic_energy(active_dims)

        crystal_rate = float(crystals.get("crystals_last_30d", 0) or 0)
        velocity = self.tduft.compute_velocity(crystal_rate, 30)

        session_engagement = float(metrics.get("avg_engagement", 0.5) or 0.5)
        crystal_yield = int(crystals.get("avg_crystals_per_session", 0) or 0)
        time_density = self.tduft.compute_time_density(
            session_engagement,
            crystal_yield,
            int(multimodal.get("incongruence_count", 0) or 0),
            int(multimodal.get("voice_variety", 0) or 0),
        )

        temporal_span = float(crystals.get("temporal_span_years", 0) or 0)
        session_duration = float(sessions.get("avg_duration_minutes", 50) or 50)
        noah = self.tduft.compute_noah_factor(temporal_span, session_duration)

        # ─── Timescape ───────────────────────────────────────────────
        total_domains = active_dims
        resolved = int(crystals.get("resolved_domains", 0) or 0)
        void_fraction = self.timescape.compute_void_fraction(total_domains, resolved)
        time_dilation = self.timescape.compute_time_dilation(void_fraction)
        session_region = self.timescape.classify_session_region(
            time_density, session_engagement, crystal_yield
        )

        # ─── Quantum Trace ───────────────────────────────────────────
        c_emo = float(metrics.get("C_emo", 0.5) or 0.5)
        gap = float(metrics.get("GAP", 0.3) or 0.3)
        quantum = float(metrics.get("Quantum", 0.5) or 0.5)
        voice = multimodal.get("voice_emotion", None)
        facial = multimodal.get("facial_summary", None)

        density = self.trace.compute_density_matrix(
            crystals.get("domains", {}),
            c_emo, gap, quantum, voice, facial,
            metrics=metrics,
        )

        family_density = None
        if family.get("has_family"):
            family_density = family.get("family_density")
        partial = self.trace.compute_partial_trace(density, family_density)

        # ─── 5D Coordinate ───────────────────────────────────────────
        family_coherence = family.get("coherence", None)
        incongruence_ratio = float(multimodal.get("incongruence_ratio", 0) or 0)

        coordinate = self.spatial.compute_5d_coordinate(
            c_emo, gap, quantum, voice, facial,
            family_coherence, noah, incongruence_ratio,
        )

        fingerprint = self.spatial.compute_emotional_fingerprint(
            coordinate, density, mass, gravity, void_fraction, noah
        )

        return {
            "user_id": user_id,
            "computed_at": None,  # set by caller with UTC timestamp

            "tduft": {
                "therapeutic_mass": mass,
                "pattern_gravity": gravity,
                "therapeutic_energy": energy,
                "velocity": velocity,
                "time_density": time_density,
                "noah_factor": noah,
                "active_dimensions": active_dims,
            },

            "timescape": {
                "void_fraction": void_fraction,
                "time_dilation": time_dilation,
                "session_region": session_region,
                "resolved_domains": resolved,
                "total_domains": total_domains,
            },

            "quantum_trace": {
                "density_matrix": density,
                "partial_trace": partial,
                "coherence": density.get("coherence", 0),
                "purity": density.get("purity", 0),
                # Always include a lindblad block. On the first snapshot
                # there is no previous density to diff against, so we
                # return the canonical "initial" state with fidelity 1.0
                # rather than letting the dashboard fall through to UNKNOWN.
                "lindblad": self.trace.compute_lindblad_evolution(
                    density, None, 0, 0
                ),
            },

            "coordinate_5d": coordinate,

            "emotional_fingerprint": fingerprint,

            "source_metrics": {
                "c_emo": c_emo,
                "gap": gap,
                "quantum": quantum,
                "session_count": session_count,
                "crystal_count": int(crystals.get("total_crystals", 0) or 0),
            },
        }

    # ─── Data loaders ────────────────────────────────────────────────
    #
    # All loaders return safe empty / default structures when the db pool
    # is missing or any query fails. The PGSD engine never raises on a
    # data-loading failure — it simply degrades to neutral inputs.

    async def _load_crystal_data(self, user_id: str) -> Dict:
        """Load crystal statistics for PGSD computation."""
        if not self.db:
            return {"domains": {}, "total_crystals": 0}

        try:
            rows = await self.db.fetch(
                """
                SELECT domain,
                       COUNT(*) AS count,
                       AVG(confidence) AS avg_conf,
                       MIN(created_at) AS oldest,
                       MAX(created_at) AS newest
                FROM nate_intelligence_crystals
                WHERE user_id = (
                    SELECT id FROM users
                    WHERE hardware_id = $1
                    LIMIT 1
                )
                  AND scope = 'user'
                  AND superseded_by IS NULL
                GROUP BY domain
                """,
                user_id,
            )

            domains: Dict[str, float] = {}
            total = 0
            oldest_days = 0
            resolved = 0

            now = datetime.now(timezone.utc)
            for r in rows:
                avg_conf = float(r["avg_conf"] or 0.0)
                domains[r["domain"]] = avg_conf
                total += int(r["count"] or 0)
                oldest_at = r["oldest"]
                if oldest_at is not None:
                    age = (now - oldest_at).days
                    oldest_days = max(oldest_days, age)
                if avg_conf > 0.7:
                    resolved += 1

            recent = await self.db.fetchval(
                """
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE user_id = (
                    SELECT id FROM users
                    WHERE hardware_id = $1 LIMIT 1
                )
                  AND created_at > NOW() - INTERVAL '30 days'
                """,
                user_id,
            ) or 0

            return {
                "domains": domains,
                "total_crystals": total,
                "avg_age_days": oldest_days,
                "crystals_last_30d": int(recent),
                "resolved_domains": resolved,
                "avg_crystals_per_session": 0,
                "temporal_span_years": oldest_days / 365.0,
            }
        except Exception:
            return {"domains": {}, "total_crystals": 0}

    async def _load_metrics(self, user_id: str) -> Dict:
        """Load Nevedal metrics + emotional state indicators for this user.

        IMPORTANT: client_metrics column is `quantum`, NOT `quantum_score`
        (see migration 052_data_consolidation.sql). The earlier query
        silently returned no row, defaulting all metrics to 0.5/0.3/0.5
        and producing a fake-looking coherence of 0.964 on every snapshot.
        """
        defaults = {
            "C_emo": 0.5, "GAP": 0.3, "Quantum": 0.5,
            "session_count": 0, "avg_engagement": 0.5,
            "anxiety": 0.0, "stress": 0.0, "depression": 0.0,
            "shame_profile": {},
        }
        if not self.db:
            return defaults
        try:
            row = await self.db.fetchrow(
                """
                SELECT c_emo, gap, quantum,
                       session_count, engagement,
                       anxiety_level, stress_level, depression_indicators,
                       shame_profile
                FROM client_metrics
                WHERE user_id = (
                    SELECT id FROM users WHERE hardware_id = $1 LIMIT 1
                )
                """,
                user_id,
            )
            if row:
                shame_raw = row["shame_profile"]
                if isinstance(shame_raw, str):
                    try:
                        shame_raw = json.loads(shame_raw)
                    except Exception:
                        shame_raw = {}
                return {
                    "C_emo": float(row["c_emo"] or 0.5),
                    "GAP": float(row["gap"] or 0.3),
                    "Quantum": float(row["quantum"] or 0.5),
                    "session_count": int(row["session_count"] or 0),
                    "avg_engagement": float(row["engagement"] or 0.5),
                    "anxiety": float(row["anxiety_level"] or 0.0),
                    "stress": float(row["stress_level"] or 0.0),
                    "depression": float(row["depression_indicators"] or 0.0),
                    "shame_profile": shame_raw if isinstance(shame_raw, dict) else {},
                }
            return defaults
        except Exception:
            return defaults

    async def _load_session_data(self, user_id: str) -> Dict:
        """Load session statistics."""
        if not self.db:
            return {}
        try:
            row = await self.db.fetchrow(
                """
                SELECT COUNT(*) AS total,
                       AVG(duration_minutes) AS avg_duration
                FROM coaching_sessions
                WHERE client_id = $1
                  AND status != 'CANCELLED'
                """,
                user_id,
            )
            if not row:
                return {}
            return {
                "total_sessions": int(row["total"] or 0),
                "avg_duration_minutes": float(row["avg_duration"] or 50),
            }
        except Exception:
            return {}

    async def _load_family_data(self, user_id: str) -> Dict:
        """Load family coherence data if applicable."""
        if not self.db:
            return {"has_family": False}
        try:
            family_id = await self.db.fetchval(
                """
                SELECT profile_data->>'family_id'
                FROM users WHERE hardware_id = $1
                """,
                user_id,
            )
            if not family_id:
                return {"has_family": False}
            return {
                "has_family": True,
                "family_id": family_id,
                "coherence": None,
                "family_density": None,
            }
        except Exception:
            return {"has_family": False}

    async def _load_multimodal(self, user_id: str) -> Dict:
        """Load latest multi-modal fusion data."""
        if not self.db:
            return {}
        try:
            row = await self.db.fetchrow(
                """
                SELECT session_data->>'multimodal_fusion' AS fusion
                FROM coaching_sessions
                WHERE client_id = $1
                  AND session_data->>'multimodal_fusion' IS NOT NULL
                ORDER BY scheduled_start DESC
                LIMIT 1
                """,
                user_id,
            )
            if row and row["fusion"]:
                fusion = json.loads(row["fusion"])
                return {
                    "voice_emotion": fusion.get("voice_emotion", {}),
                    "facial_summary": fusion.get("facial_summary", {}),
                    "incongruence_count": len(
                        fusion.get("incongruence_moments", []) or []
                    ),
                    "incongruence_ratio": 0,
                    "voice_variety": 0,
                }
            return {}
        except Exception:
            return {}


__all__ = [
    "TDUFTComputer",
    "TimescapeComputer",
    "QuantumTraceComputer",
    "SpatioTemporalComputer",
    "PGSDEngine",
]
