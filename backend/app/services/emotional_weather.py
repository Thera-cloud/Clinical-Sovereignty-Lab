"""
SOVEREIGN SWARM — Emotional Weather System (S2)
Real-time family session emotional topology: influence maps,
bridge member detection, CEE window detection, dyadic coherence.

Applied Solution S2: Family Sanctuary Emotional Weather System.
"""

import asyncio
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.models.solutions import (
    AttachmentActivation,
    CommunicationMode,
    DyadCoherence,
    EmotionalWeatherMap,
    MemberEmotionalState,
    WeatherInformedIntervention,
)

logger = logging.getLogger("emotional_weather")


class EmotionalWeatherService:
    """
    Computes real-time emotional topology for Family Sanctuary sessions.
    Updates every 5 seconds with fresh Nevedal data per member.
    """

    def __init__(self, nevedal_engine=None, sovereign_mind=None):
        self._nevedal = nevedal_engine
        self._sovereign_mind = sovereign_mind
        self._active_maps: Dict[str, EmotionalWeatherMap] = {}

    # -------------------------------------------------------------------------
    # MAP LIFECYCLE
    # -------------------------------------------------------------------------

    async def start_session_weather(
        self, sanctuary_id: str, family_id: str, member_ids: List[str]
    ) -> EmotionalWeatherMap:
        """Initialize a weather map for a new Family Sanctuary session."""
        weather = EmotionalWeatherMap(
            sanctuary_id=sanctuary_id,
            family_id=family_id,
        )
        for mid in member_ids:
            weather.member_states[mid] = MemberEmotionalState(member_id=mid)
        self._active_maps[sanctuary_id] = weather
        logger.info("Weather map started: sanctuary=%s family=%s members=%d",
                     sanctuary_id, family_id, len(member_ids))
        return weather

    async def end_session_weather(self, sanctuary_id: str) -> Optional[EmotionalWeatherMap]:
        """End and return the final weather map for a session."""
        return self._active_maps.pop(sanctuary_id, None)

    # -------------------------------------------------------------------------
    # REAL-TIME UPDATE
    # -------------------------------------------------------------------------

    async def update_member_state(
        self,
        sanctuary_id: str,
        member_id: str,
        c_emo: float = 0.0,
        gamma_env: float = 0.0,
        t_tunnel: float = 0.0,
        message_text: Optional[str] = None,
        voice_biometrics: Optional[Dict[str, float]] = None,
    ) -> Optional[EmotionalWeatherMap]:
        """
        Update a member's emotional state and recompute the weather map.
        Called on every message or at 5-second intervals.
        """
        weather = self._active_maps.get(sanctuary_id)
        if not weather:
            return None

        state = weather.member_states.get(member_id)
        if not state:
            state = MemberEmotionalState(member_id=member_id)
            weather.member_states[member_id] = state

        # Update Nevedal parameters
        prev_c_emo = state.current_c_emo
        state.current_c_emo = c_emo
        state.c_emo_velocity = c_emo - prev_c_emo
        state.decoherence_gamma = gamma_env
        state.tunneling_t = t_tunnel

        # Update message tracking
        if message_text:
            state.message_count += 1
            state.last_message_timestamp = datetime.utcnow()
            state.silence_duration = 0.0

            # Detect communication mode
            state.communication_mode = self._detect_communication_mode(message_text)

            # Detect attachment activation
            state.attachment_activation = self._detect_attachment_activation(
                c_emo, gamma_env, t_tunnel
            )

        # Recompute dyadic coherence for all pairs involving this member
        await self._recompute_dyadic_coherence(weather, member_id)

        # Recompute system-level metrics
        self._recompute_system_metrics(weather)

        # Check for CEE window
        self._check_cee_window(weather)

        # Detect influence map, bridge, and isolated members
        self._compute_influence_map(weather)

        weather.timestamp = datetime.utcnow()
        return weather

    # -------------------------------------------------------------------------
    # INTERVENTION GENERATION
    # -------------------------------------------------------------------------

    async def generate_intervention(
        self, sanctuary_id: str
    ) -> Optional[WeatherInformedIntervention]:
        """Generate a weather-informed intervention recommendation."""
        weather = self._active_maps.get(sanctuary_id)
        if not weather:
            return None

        intervention = WeatherInformedIntervention()

        # Crisis check: escalation risk
        if weather.escalation_risk > 0.8:
            intervention.intervention_type = "de_escalate"
            intervention.urgency = "immediate"
            intervention.tone = "calm"
            if weather.isolated_member:
                intervention.target_member = weather.isolated_member
                intervention.clinical_reasoning = (
                    "Escalation risk high. Isolated member needs direct engagement."
                )

        # CEE Window: capitalize on opportunity
        elif weather.cee_window_open and weather.cee_window_dyad:
            intervention.intervention_type = "deepen"
            intervention.urgency = "now"
            intervention.target_member = weather.cee_window_dyad[1]
            intervention.bridge_member = weather.cee_window_dyad[0]
            intervention.clinical_reasoning = (
                "CEE window open between dyad. "
                "Encourage emotional deepening."
            )

        # Bridge opportunity
        elif weather.bridge_member:
            intervention.intervention_type = "bridge"
            intervention.target_member = weather.bridge_member
            intervention.clinical_reasoning = (
                "Bridge member detected. Use their emotional stability "
                "to facilitate connection with isolated member."
            )

        # Low system coherence
        elif weather.system_coherence < 0.3:
            intervention.intervention_type = "reconnect"
            intervention.urgency = "next_pause"
            intervention.clinical_reasoning = (
                "System coherence is low. Consider a reconnection exercise."
            )

        return intervention

    # -------------------------------------------------------------------------
    # COMMUNICATION MODE DETECTION
    # -------------------------------------------------------------------------

    def _detect_communication_mode(self, text: str) -> CommunicationMode:
        """Detect communication mode from text content."""
        lower = text.lower()

        attacking_markers = ["you always", "you never", "your fault", "blame"]
        pursuing_markers = ["why won't you", "please talk to me", "i need you to"]
        withdrawing_markers = ["whatever", "fine", "i don't care", "leave me alone"]
        stonewalling_markers = ["...", ""]
        vulnerable_markers = ["i feel", "it hurts", "i'm scared", "i need"]
        reflective_markers = ["i understand", "i hear you", "that makes sense"]

        if any(m in lower for m in attacking_markers):
            return CommunicationMode.ATTACKING
        if any(m in lower for m in pursuing_markers):
            return CommunicationMode.PURSUING
        if any(m in lower for m in withdrawing_markers):
            return CommunicationMode.WITHDRAWING
        if any(m in lower for m in vulnerable_markers):
            return CommunicationMode.VULNERABLE
        if any(m in lower for m in reflective_markers):
            return CommunicationMode.REFLECTIVE
        if len(text.strip()) < 5:
            return CommunicationMode.STONEWALLING
        return CommunicationMode.REFLECTIVE

    def _detect_attachment_activation(
        self, c_emo: float, gamma: float, tunnel: float
    ) -> AttachmentActivation:
        """Infer attachment activation from Nevedal parameters."""
        if gamma < 0.3 and tunnel > 0.5:
            return AttachmentActivation.SECURE_BASE
        if gamma > 0.6 and tunnel < 0.2:
            return AttachmentActivation.AVOIDANT_WITHDRAWAL
        if gamma < 0.4 and tunnel < 0.3 and c_emo < 0.3:
            return AttachmentActivation.ANXIOUS_PROTEST
        if gamma > 0.7 and c_emo < 0.2:
            return AttachmentActivation.DISORGANIZED_FREEZE
        return AttachmentActivation.SECURE_BASE

    # -------------------------------------------------------------------------
    # DYADIC COHERENCE
    # -------------------------------------------------------------------------

    async def _recompute_dyadic_coherence(
        self, weather: EmotionalWeatherMap, updated_member: str
    ) -> None:
        """Recompute coherence between the updated member and all others."""
        for other_id, other_state in weather.member_states.items():
            if other_id == updated_member:
                continue
            updated_state = weather.member_states[updated_member]

            key = f"{min(updated_member, other_id)}-{max(updated_member, other_id)}"

            # Coherence: inverse of c_emo difference
            c_emo_diff = abs(updated_state.current_c_emo - other_state.current_c_emo)
            coherence = max(0.0, 1.0 - c_emo_diff)

            # Entanglement: product of tunneling values
            entanglement = updated_state.tunneling_t * other_state.tunneling_t

            # Cross-decoherence
            a_decoherence_when_b = updated_state.decoherence_gamma
            b_decoherence_when_a = other_state.decoherence_gamma

            dyad = DyadCoherence(
                member_a=updated_member,
                member_b=other_id,
                coherence_score=coherence,
                entanglement=entanglement,
                tunneling=min(updated_state.tunneling_t, other_state.tunneling_t),
                a_decoherence_when_b_speaks=a_decoherence_when_b,
                b_decoherence_when_a_speaks=b_decoherence_when_a,
            )

            # Detect repair attempts (communication mode transitions)
            existing = weather.dyad_coherence.get(key)
            if existing:
                if (
                    updated_state.communication_mode == CommunicationMode.VULNERABLE
                    and existing.coherence_score < coherence
                ):
                    dyad.repair_attempts = existing.repair_attempts + 1
                    dyad.repair_success_rate = (
                        dyad.repair_attempts / max(dyad.repair_attempts, 1)
                    )

            weather.dyad_coherence[key] = dyad

    # -------------------------------------------------------------------------
    # SYSTEM METRICS
    # -------------------------------------------------------------------------

    def _recompute_system_metrics(self, weather: EmotionalWeatherMap) -> None:
        """Recompute system-level coherence and volatility."""
        if not weather.dyad_coherence:
            weather.system_coherence = 0.0
            weather.system_volatility = 0.0
            return

        coherences = [d.coherence_score for d in weather.dyad_coherence.values()]
        weather.system_coherence = sum(coherences) / len(coherences) if coherences else 0.0

        # Volatility: std deviation of c_emo velocities
        velocities = [s.c_emo_velocity for s in weather.member_states.values()]
        if len(velocities) > 1:
            mean_v = sum(velocities) / len(velocities)
            variance = sum((v - mean_v) ** 2 for v in velocities) / len(velocities)
            weather.system_volatility = math.sqrt(variance)
        else:
            weather.system_volatility = 0.0

        # Escalation risk: based on attacking modes + volatility
        attacking_count = sum(
            1 for s in weather.member_states.values()
            if s.communication_mode == CommunicationMode.ATTACKING
        )
        weather.escalation_risk = min(
            1.0,
            (attacking_count * 0.3) + (weather.system_volatility * 2.0),
        )

    def _check_cee_window(self, weather: EmotionalWeatherMap) -> None:
        """Check if a CEE window is open in any dyad."""
        weather.cee_window_open = False
        weather.cee_window_dyad = None

        for key, dyad in weather.dyad_coherence.items():
            a = weather.member_states.get(dyad.member_a)
            b = weather.member_states.get(dyad.member_b)
            if not a or not b:
                continue

            # CEE window: high entanglement + vulnerable communication + low gamma
            if (
                dyad.entanglement > 0.4
                and dyad.coherence_score > 0.5
                and (a.communication_mode == CommunicationMode.VULNERABLE
                     or b.communication_mode == CommunicationMode.VULNERABLE)
                and min(a.decoherence_gamma, b.decoherence_gamma) < 0.35
            ):
                weather.cee_window_open = True
                weather.cee_window_dyad = (dyad.member_a, dyad.member_b)
                break

    def _compute_influence_map(self, weather: EmotionalWeatherMap) -> None:
        """Identify bridge member and isolated member."""
        influence: Dict[str, float] = {}
        for mid, state in weather.member_states.items():
            # Influence = avg coherence with all others
            relevant = [
                d.coherence_score for d in weather.dyad_coherence.values()
                if d.member_a == mid or d.member_b == mid
            ]
            influence[mid] = sum(relevant) / len(relevant) if relevant else 0.0

        weather.influence_map = {mid: {"influence": score} for mid, score in influence.items()}

        if influence:
            weather.bridge_member = max(influence, key=influence.get)
            weather.isolated_member = min(influence, key=influence.get)
            # Only set bridge/isolated if there's meaningful difference
            if influence[weather.bridge_member] - influence[weather.isolated_member] < 0.1:
                weather.bridge_member = None
                weather.isolated_member = None

    # -------------------------------------------------------------------------
    # ACCESSORS
    # -------------------------------------------------------------------------

    def get_weather_map(self, sanctuary_id: str) -> Optional[EmotionalWeatherMap]:
        """Get the current weather map for a session."""
        return self._active_maps.get(sanctuary_id)

    def get_active_sessions(self) -> List[str]:
        """Get all active sanctuary session IDs."""
        return list(self._active_maps.keys())
