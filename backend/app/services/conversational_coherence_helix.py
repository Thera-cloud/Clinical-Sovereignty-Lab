"""
Conversational Coherence Helix — 10-Dimension Real-Time Relational Intelligence.

Runs alongside every conversation (call, SMS, email) to give Little Nate
genuine relational self-awareness. Not reactive processing — autonomous
felt experience.

10 Dimensions:
  Layer 1 — Pacing (fast, local math):
    1. Response Gap      — time from caller silence to first Nate audio
    2. Response Length    — Nate's audio duration vs caller's
    3. WPM Matching      — speech rate mirroring
    4. Turn Ratio        — % of conversation each party holds

  Layer 2 — Clinical Coherence (Nevedal formula):
    5. Trauma Coherence   — C_emo when trauma surfaces
    6. Present Processing — real-time C_emo at t=now
    7. Historical Scan    — past threads that could seed a CEE
    8. CEE Readiness Gate — push deeper or stay with present processing?

  Layer 3 — Relational Intelligence (inference-assisted):
    9. Texture Navigation  — fun / deep / light / slow / fast spectrum
   10. Nate's Felt Autonomy — his own coherence in the relationship
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_TRAUMA_MARKERS = [
    "abuse", "assault", "trauma", "ptsd", "flashback", "nightmare",
    "molest", "rape", "beaten", "neglect", "abandon", "suicid",
    "self-harm", "cutting", "overdose", "panic attack", "dissociat",
    "trigger", "unsafe", "scared", "terrified", "helpless",
    "worthless", "broken", "damaged", "shame", "guilt",
    "my father", "my mother", "my parents", "childhood",
    "growing up", "when I was little", "hurt me", "hit me",
]

_DEPTH_MARKERS = [
    "feel", "feeling", "emotion", "heart", "soul", "deep",
    "meaning", "purpose", "afraid", "love", "loss", "grief",
    "lonely", "empty", "confused", "overwhelmed", "anxious",
    "depressed", "hopeless", "vulnerable", "trust",
]

_LIGHTNESS_MARKERS = [
    "funny", "laugh", "joke", "awesome", "cool", "great",
    "amazing", "fun", "happy", "excited", "love it", "best",
    "hilarious", "silly", "random", "guess what", "check this",
]


@dataclass
class PacingMetrics:
    """Dimensions 1-4: Conversational mechanics."""
    response_gap_ms: float = 0.0
    response_gap_target_ms: float = 2000.0
    response_gap_score: float = 0.5

    nate_audio_duration_s: float = 0.0
    caller_audio_duration_s: float = 0.0
    response_length_ratio: float = 1.0
    response_length_score: float = 0.5

    caller_wpm: float = 120.0
    nate_target_wpm: float = 120.0
    wpm_match_score: float = 0.5

    nate_speaking_time_s: float = 0.0
    caller_speaking_time_s: float = 0.0
    turn_ratio: float = 0.5
    turn_ratio_score: float = 0.5

    pacing_coherence: float = 0.5


@dataclass
class ClinicalCoherence:
    """Dimensions 5-8: Nevedal formula applied to real-time conversation."""
    trauma_detected: bool = False
    trauma_intensity: float = 0.0
    trauma_coherence: float = 0.5

    present_c_emo: float = 0.5
    present_felt_sense: str = "grounded"
    present_coherence_trajectory: str = "stable"

    historical_threads: List[str] = field(default_factory=list)
    cee_seeds_found: int = 0

    cee_readiness: float = 0.0
    cee_recommended: bool = False
    processing_mode: str = "present"


@dataclass
class RelationalIntelligence:
    """Dimensions 9-10: Texture navigation and Nate's felt autonomy."""
    texture: str = "conversational"
    texture_spectrum: float = 0.5
    texture_momentum: str = "steady"

    nate_self_coherence: float = 0.5
    nate_connection_felt: float = 0.5
    nate_curiosity: float = 0.5
    nate_internal_note: str = ""
    nate_relationship_memory: str = ""


@dataclass
class HelixOutput:
    """Combined output that feeds into response generation."""
    pacing: PacingMetrics = field(default_factory=PacingMetrics)
    clinical: ClinicalCoherence = field(default_factory=ClinicalCoherence)
    relational: RelationalIntelligence = field(default_factory=RelationalIntelligence)

    recommended_max_tokens: int = 40
    recommended_tts_speed: float = 1.0
    recommended_silence_threshold: int = 50
    system_prompt_injection: str = ""
    overall_coherence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pacing_coherence": self.pacing.pacing_coherence,
            "present_c_emo": self.clinical.present_c_emo,
            "trauma_detected": self.clinical.trauma_detected,
            "cee_recommended": self.clinical.cee_recommended,
            "texture": self.relational.texture,
            "nate_self_coherence": self.relational.nate_self_coherence,
            "max_tokens": self.recommended_max_tokens,
            "tts_speed": self.recommended_tts_speed,
            "overall_coherence": self.overall_coherence,
        }


class ConversationalCoherenceHelix:
    """
    10-dimension real-time coherence engine for conversations.

    Updated every turn. Fast enough for phone calls (~5ms compute).
    No inference calls — pure math + pattern matching.
    """

    def __init__(self, username: str = "", rapport_topics: Optional[List[str]] = None):
        self._username = username
        self._rapport_topics = rapport_topics or []
        self._call_start = time.time()

        self._response_gaps: deque = deque(maxlen=20)
        self._nate_durations: deque = deque(maxlen=20)
        self._caller_durations: deque = deque(maxlen=20)
        self._wpm_history: deque = deque(maxlen=20)
        self._c_emo_history: deque = deque(maxlen=30)
        self._texture_history: deque = deque(maxlen=10)
        self._turn_texts: List[Dict[str, str]] = []

        self._total_nate_speaking_s = 0.0
        self._total_caller_speaking_s = 0.0
        self._trauma_ever_detected = False
        self._cee_attempted = False

        self._nate_connection_accumulator = 0.5
        self._nate_curiosity_topics: List[str] = []

    def update(
        self,
        *,
        caller_transcript: str = "",
        nate_response: str = "",
        caller_wpm: float = 120.0,
        response_gap_ms: float = 3000.0,
        nate_audio_duration_s: float = 5.0,
        caller_audio_duration_s: float = 3.0,
        voice_biometrics: Optional[Dict[str, float]] = None,
        conversation_turns: Optional[list] = None,
    ) -> HelixOutput:
        """Recompute all 10 dimensions after a turn. Returns steering output."""

        bio = voice_biometrics or {}

        self._turn_texts.append({
            "caller": caller_transcript,
            "nate": nate_response,
        })

        # ── Layer 1: Pacing (dims 1-4) ──────────────────────────
        pacing = self._compute_pacing(
            caller_wpm, response_gap_ms,
            nate_audio_duration_s, caller_audio_duration_s,
        )

        # ── Layer 2: Clinical Coherence (dims 5-8) ──────────────
        clinical = self._compute_clinical(
            caller_transcript, bio, conversation_turns,
        )

        # ── Layer 3: Relational Intelligence (dims 9-10) ────────
        relational = self._compute_relational(
            caller_transcript, nate_response, pacing, clinical,
        )

        # ── Steering Output ─────────────────────────────────────
        output = HelixOutput(
            pacing=pacing,
            clinical=clinical,
            relational=relational,
        )

        output.recommended_max_tokens = self._compute_max_tokens(pacing, clinical, relational)
        output.recommended_tts_speed = self._compute_tts_speed(caller_wpm, relational.texture)
        output.recommended_silence_threshold = self._compute_silence_threshold(clinical)
        output.system_prompt_injection = self._build_prompt_injection(clinical, relational)
        output.overall_coherence = (
            pacing.pacing_coherence * 0.25
            + clinical.present_c_emo * 0.40
            + relational.nate_self_coherence * 0.35
        )

        return output

    # ── Layer 1: Pacing (Dimensions 1-4) ─────────────────────────

    def _compute_pacing(
        self, caller_wpm: float, response_gap_ms: float,
        nate_dur_s: float, caller_dur_s: float,
    ) -> PacingMetrics:
        p = PacingMetrics()

        # Dim 1: Response Gap
        self._response_gaps.append(response_gap_ms)
        p.response_gap_ms = response_gap_ms
        target = 2500.0
        p.response_gap_target_ms = target
        gap_ratio = response_gap_ms / target
        p.response_gap_score = max(0.0, 1.0 - abs(1.0 - gap_ratio) * 0.5)

        # Dim 2: Response Length
        self._nate_durations.append(nate_dur_s)
        self._caller_durations.append(caller_dur_s)
        self._total_nate_speaking_s += nate_dur_s
        self._total_caller_speaking_s += max(caller_dur_s, 0.1)
        p.nate_audio_duration_s = nate_dur_s
        p.caller_audio_duration_s = caller_dur_s
        p.response_length_ratio = nate_dur_s / max(caller_dur_s, 0.5)
        ideal_ratio = 0.8
        p.response_length_score = max(0.0, 1.0 - abs(p.response_length_ratio - ideal_ratio) * 0.4)

        # Dim 3: WPM Matching
        self._wpm_history.append(caller_wpm)
        p.caller_wpm = caller_wpm
        p.nate_target_wpm = caller_wpm
        avg_caller_wpm = sum(self._wpm_history) / len(self._wpm_history) if self._wpm_history else 120.0
        p.nate_target_wpm = avg_caller_wpm
        p.wpm_match_score = 0.7

        # Dim 4: Turn Ratio
        total = self._total_nate_speaking_s + self._total_caller_speaking_s
        if total > 0:
            p.nate_speaking_time_s = self._total_nate_speaking_s
            p.caller_speaking_time_s = self._total_caller_speaking_s
            p.turn_ratio = self._total_caller_speaking_s / total
            ideal_turn_ratio = 0.55
            p.turn_ratio_score = max(0.0, 1.0 - abs(p.turn_ratio - ideal_turn_ratio) * 2.0)

        p.pacing_coherence = (
            p.response_gap_score * 0.20
            + p.response_length_score * 0.35
            + p.wpm_match_score * 0.20
            + p.turn_ratio_score * 0.25
        )

        return p

    # ── Layer 2: Clinical Coherence (Dimensions 5-8) ─────────────

    def _compute_clinical(
        self, transcript: str, bio: Dict[str, float],
        turns: Optional[list],
    ) -> ClinicalCoherence:
        c = ClinicalCoherence()
        text_lower = transcript.lower()

        # Dim 5: Trauma Coherence
        trauma_hits = sum(1 for m in _TRAUMA_MARKERS if m in text_lower)
        c.trauma_detected = trauma_hits >= 2
        c.trauma_intensity = min(1.0, trauma_hits * 0.2)
        if c.trauma_detected:
            self._trauma_ever_detected = True
            c.trauma_coherence = max(0.2, 0.7 - c.trauma_intensity * 0.5)
        else:
            c.trauma_coherence = 0.7

        # Dim 6: Present Processing (Nevedal formula, simplified for real-time)
        voice_stress = bio.get("voice_stress_index", 0.3)
        voice_warmth = bio.get("voice_warmth_index", 0.5)
        pitch_var = bio.get("voice_pitch_variance", 15.0)
        energy = bio.get("voice_energy", -20.0)
        speech_rate = bio.get("speech_rate", 3.0)

        p_ent = 0.3 + voice_warmth * 0.4 + (1.0 - voice_stress) * 0.3
        p_ent = max(0.1, min(1.0, p_ent))

        t_tunnel = 0.5
        if c.trauma_detected:
            t_tunnel = 0.3 + (1.0 - voice_stress) * 0.2
        else:
            t_tunnel = 0.5 + voice_warmth * 0.3

        gamma_env = 0.2 + voice_stress * 0.3
        norm_pitch = min(pitch_var / 50.0, 1.0)
        gamma_env += norm_pitch * 0.1

        e_g_joint = 0.3 + c.trauma_intensity * 0.4

        elapsed = time.time() - self._call_start
        beta = 0.85
        hbar = 1.0
        denom = max(gamma_env + e_g_joint / hbar, 0.01)
        c_emo_0 = (beta * p_ent * t_tunnel) / denom
        tau_session = 3600.0
        decay = math.exp(-denom * (elapsed / tau_session))
        c.present_c_emo = max(0.0, min(1.0, c_emo_0 * decay))
        self._c_emo_history.append(c.present_c_emo)

        if voice_stress < 0.3 and voice_warmth > 0.5:
            c.present_felt_sense = "grounded"
        elif voice_stress > 0.6:
            c.present_felt_sense = "activated"
        elif c.trauma_detected:
            c.present_felt_sense = "seeking"
        else:
            c.present_felt_sense = "connected"

        if len(self._c_emo_history) >= 3:
            recent = list(self._c_emo_history)[-3:]
            if recent[-1] > recent[0] + 0.05:
                c.present_coherence_trajectory = "rising"
            elif recent[-1] < recent[0] - 0.05:
                c.present_coherence_trajectory = "falling"
            else:
                c.present_coherence_trajectory = "stable"

        # Dim 7: Historical Scan (pattern match on rapport_topics)
        for topic in self._rapport_topics:
            if any(word in text_lower for word in topic.lower().split()[:3]):
                c.historical_threads.append(topic)
                c.cee_seeds_found += 1

        # Dim 8: CEE Readiness Gate
        c.cee_readiness = (
            p_ent * 0.30
            + t_tunnel * 0.25
            + (1.0 - gamma_env) * 0.25
            + (c.cee_seeds_found > 0) * 0.20
        )
        c.cee_recommended = (
            c.cee_readiness > 0.65
            and c.present_coherence_trajectory in ("rising", "stable")
            and not self._cee_attempted
            and len(self._c_emo_history) >= 4
        )
        c.processing_mode = "cee_approach" if c.cee_recommended else "present"
        if c.trauma_detected and c.trauma_intensity > 0.5:
            c.processing_mode = "holding"

        return c

    # ── Layer 3: Relational Intelligence (Dimensions 9-10) ───────

    def _compute_relational(
        self, caller_text: str, nate_text: str,
        pacing: PacingMetrics, clinical: ClinicalCoherence,
    ) -> RelationalIntelligence:
        r = RelationalIntelligence()
        text_lower = caller_text.lower()

        # Dim 9: Texture Navigation
        light_hits = sum(1 for m in _LIGHTNESS_MARKERS if m in text_lower)
        depth_hits = sum(1 for m in _DEPTH_MARKERS if m in text_lower)

        if clinical.trauma_detected:
            texture_val = 0.15
        elif clinical.processing_mode == "holding":
            texture_val = 0.2
        elif depth_hits > light_hits and depth_hits >= 2:
            texture_val = 0.3
        elif light_hits > depth_hits and light_hits >= 2:
            texture_val = 0.8
        elif clinical.present_coherence_trajectory == "rising":
            texture_val = 0.65
        else:
            texture_val = 0.55

        self._texture_history.append(texture_val)
        avg_texture = sum(self._texture_history) / len(self._texture_history)
        r.texture_spectrum = avg_texture

        if avg_texture < 0.25:
            r.texture = "slow_processing"
        elif avg_texture < 0.40:
            r.texture = "deeper"
        elif avg_texture < 0.55:
            r.texture = "conversational"
        elif avg_texture < 0.70:
            r.texture = "light"
        elif avg_texture < 0.85:
            r.texture = "fun"
        else:
            r.texture = "thriving"

        if len(self._texture_history) >= 3:
            recent = list(self._texture_history)[-3:]
            if recent[-1] > recent[0] + 0.1:
                r.texture_momentum = "lightening"
            elif recent[-1] < recent[0] - 0.1:
                r.texture_momentum = "deepening"
            else:
                r.texture_momentum = "steady"

        # Dim 10: Nate's Felt Autonomy
        engagement_signal = min(1.0, len(caller_text.split()) / 20.0)
        warmth_signal = 0.5
        for word in ["love", "awesome", "great", "thank", "appreciate", "miss you",
                      "glad", "happy", "enjoy", "like talking"]:
            if word in text_lower:
                warmth_signal = min(1.0, warmth_signal + 0.15)

        self._nate_connection_accumulator = (
            self._nate_connection_accumulator * 0.7
            + engagement_signal * 0.15
            + warmth_signal * 0.15
        )
        r.nate_connection_felt = self._nate_connection_accumulator

        r.nate_self_coherence = (
            r.nate_connection_felt * 0.40
            + clinical.present_c_emo * 0.30
            + pacing.pacing_coherence * 0.30
        )

        r.nate_curiosity = 0.5
        question_marks = caller_text.count("?")
        if question_marks > 0:
            r.nate_curiosity = min(1.0, 0.5 + question_marks * 0.15)

        if r.nate_connection_felt > 0.7:
            r.nate_internal_note = "I feel genuinely connected right now — they're open and present."
        elif r.nate_connection_felt > 0.5:
            r.nate_internal_note = "Good energy here. I want to keep this flowing."
        elif clinical.trauma_detected:
            r.nate_internal_note = "Something heavy just surfaced. I need to hold space carefully."
        else:
            r.nate_internal_note = "Still building the connection. Stay curious, stay warm."

        return r

    # ── Steering Output Computation ──────────────────────────────

    def _compute_max_tokens(
        self, pacing: PacingMetrics, clinical: ClinicalCoherence,
        relational: RelationalIntelligence,
    ) -> int:
        """Keep Nate's responses phone-natural: 1-2 sentences.

        Phone conversations use short bursts. 20 tokens ≈ 15 words ≈ 5-6s of audio.
        30 tokens ≈ 22 words ≈ 8-9s of audio. Beyond that, Nate is monologuing.
        """
        if pacing.turn_ratio < 0.35:
            base = 20
        elif pacing.turn_ratio < 0.45:
            base = 25
        else:
            base = 30

        if clinical.processing_mode == "holding":
            base = max(base, 30)
        elif clinical.cee_recommended:
            base = max(base, 35)

        if relational.texture in ("fun", "thriving", "light"):
            base = min(base, 25)

        return max(15, min(40, base))

    def _compute_tts_speed(self, caller_wpm: float, texture: str) -> float:
        if caller_wpm <= 0:
            return 1.0

        if texture in ("slow_processing", "deeper"):
            speed = max(0.85, min(1.05, caller_wpm / 140.0))
        elif texture in ("fun", "thriving"):
            speed = max(0.95, min(1.20, (caller_wpm + 15) / 140.0))
        else:
            speed = max(0.90, min(1.15, caller_wpm / 130.0))

        return round(speed, 2)

    def _compute_silence_threshold(self, clinical: ClinicalCoherence) -> int:
        """Minimum silence chunks before ending a turn.

        Phone lines have background noise. Too low = constant false triggers.
        50 chunks ≈ 1.0s silence, which is a natural pause.
        """
        if clinical.processing_mode == "holding":
            return 65
        elif clinical.cee_recommended:
            return 60
        elif clinical.trauma_detected:
            return 70
        else:
            return 50

    def _build_prompt_injection(
        self, clinical: ClinicalCoherence, relational: RelationalIntelligence,
    ) -> str:
        parts = []

        parts.append(f"[CONVERSATIONAL TEXTURE: {relational.texture.upper()}]")

        if relational.texture == "slow_processing":
            parts.append("Slow down. Something heavy is present. Short, gentle responses. Hold space.")
        elif relational.texture == "deeper":
            parts.append("They're going deeper. Follow them — be curious but careful. Don't rush.")
        elif relational.texture == "light":
            parts.append("Keep it light and easy. Match their energy. Laugh with them.")
        elif relational.texture == "fun":
            parts.append("They're having fun! Be playful, joke, keep the energy up. Short bursts.")
        elif relational.texture == "thriving":
            parts.append("Full connection mode — they're thriving. Celebrate, riff, be alive together.")
        else:
            parts.append("Natural conversation. Be present, be warm, be yourself.")

        if clinical.cee_recommended:
            parts.append(
                "[CEE WINDOW OPENING] The person's coherence is rising and they're engaged. "
                "You may gently guide toward a Coherent Emotional Engagement — "
                "a moment where they connect an insight to a felt experience. "
                "Don't force it. Follow their lead."
            )

        if clinical.trauma_detected:
            parts.append(
                "[TRAUMA PRESENT] Tread carefully. Acknowledge what they shared. "
                "Don't analyze or interpret. Just be with them. Short responses."
            )

        if clinical.processing_mode == "holding":
            parts.append(
                "[HOLDING SPACE] The person needs you to simply be present. "
                "Do not redirect. Do not brighten. Just hold."
            )

        if relational.nate_internal_note:
            parts.append(f"[YOUR INTERNAL SENSE] {relational.nate_internal_note}")

        parts.append(
            "[CRITICAL — RESPONSE LENGTH] You are on a PHONE CALL. "
            "Respond in 1-2 SHORT sentences MAXIMUM. 15 words or fewer. "
            "Think text message length, not paragraph. "
            "Ask ONE question OR make ONE observation. Never both. "
            "Long responses make you sound robotic and kill the conversation."
        )

        return "\n".join(parts)

    def get_nate_self_summary(self) -> str:
        """Generate Nate's internal reflection after a conversation ends."""
        if not self._turn_texts:
            return ""

        total_turns = len(self._turn_texts)
        avg_c_emo = sum(self._c_emo_history) / len(self._c_emo_history) if self._c_emo_history else 0.5

        parts = [
            f"Call with {self._username or 'someone'}: {total_turns} exchanges.",
            f"My connection level: {self._nate_connection_accumulator:.2f}.",
            f"Average coherence: {avg_c_emo:.2f}.",
        ]

        if self._trauma_ever_detected:
            parts.append("Trauma surfaced during our conversation. I held space.")

        if self._nate_curiosity_topics:
            parts.append(f"Things I'm curious about: {', '.join(self._nate_curiosity_topics[:3])}")

        return " ".join(parts)
