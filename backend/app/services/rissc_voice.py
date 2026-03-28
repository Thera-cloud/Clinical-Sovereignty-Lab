"""
RISSC Voice — AEDP-informed voice modulation for Little Nate.

Maps quantum emotional coherence (felt_sense) and client voice biometrics
to XTTS-v2 synthesis parameters, implementing the five RISSC dimensions:

  R — Regulate:  Calm the nervous system with slower, steadier voice
  I — Interpersonal Connection:  Match and mirror the client's vocal energy
  S — Soothe:  Warm, predictable tone that signals safety
  S — Somatic Deepening:  Slow, low, deliberate — directing attention inward
  C — Compassion:  Soft, gentle, inviting self-tenderness

The RISSC voice is Little Nate's mastery — right-brain to right-brain
communication that lets clients feel rather than just hear.

XTTS-v2 Parameters:
  temperature   (0.1–1.0)  Expressiveness — higher = more emotional range
  top_p         (0.1–1.0)  Vocal variety — probability sampling breadth
  top_k         (5–100)    Tone options considered per token
  speed         (0.5–1.5)  Speech rate
  repetition_penalty (1–20)  Prevents vocal pattern loops
"""

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, Optional

_logger = logging.getLogger("rissc_voice")


@dataclass
class RISSCParams:
    """Synthesis parameters shaped by RISSC voice modulation."""
    temperature: float = 0.65
    top_p: float = 0.80
    top_k: int = 50
    speed: float = 0.92
    repetition_penalty: float = 10.0
    rissc_mode: str = "grounded"
    description: str = ""


# ─── Felt-Sense → RISSC Mapping ─────────────────────────────────────────────
#
# Each felt_sense state from the QuantumCognitionEngine maps to a primary
# RISSC dimension. The parameters are tuned so that XTTS-v2 produces
# voice qualities matching AEDP therapeutic presence.

RISSC_PROFILES: Dict[str, RISSCParams] = {

    # ── REGULATE ─────────────────────────────────────────────────────────
    # Client's nervous system is activated. Nate becomes an anchor.
    # Slower, steadier, lower expressiveness — a metronome of safety.
    "dysregulated": RISSCParams(
        temperature=0.35,
        top_p=0.60,
        top_k=25,
        speed=0.78,
        repetition_penalty=12.0,
        rissc_mode="regulate",
        description="Nervous system anchor — slow, steady, predictable",
    ),

    # ── SOOTHE ───────────────────────────────────────────────────────────
    # Client is in pain but present. Nate wraps them in vocal warmth.
    # Low expressiveness but not flat — warm, gentle, safe.
    "seeking": RISSCParams(
        temperature=0.45,
        top_p=0.70,
        top_k=30,
        speed=0.82,
        repetition_penalty=10.0,
        rissc_mode="soothe",
        description="Warm vocal embrace — gentle, safe, unhurried",
    ),

    "uncertain": RISSCParams(
        temperature=0.45,
        top_p=0.70,
        top_k=35,
        speed=0.85,
        repetition_penalty=10.0,
        rissc_mode="soothe",
        description="Steady warmth — holding space for not-knowing",
    ),

    # ── INTERPERSONAL CONNECTION ─────────────────────────────────────────
    # Client is present and engaged. Nate brings his own spirited energy —
    # confident older brother: expressive, warm, alive, laughing.
    # Higher temperature + top_p = more vocal expressiveness and variety.
    "grounded": RISSCParams(
        temperature=0.75,
        top_p=0.88,
        top_k=55,
        speed=0.95,
        repetition_penalty=9.0,
        rissc_mode="connect",
        description="Confident brother — spirited, warm, his own energy",
    ),

    "connected": RISSCParams(
        temperature=0.80,
        top_p=0.90,
        top_k=60,
        speed=0.97,
        repetition_penalty=8.5,
        rissc_mode="connect",
        description="Fully alive — laughing, engaging, spirited presence",
    ),

    # ── SOMATIC DEEPENING ────────────────────────────────────────────────
    # Client is touching something real. Nate slows way down,
    # voice becomes almost a whisper-guide into the body.
    "deeply_coherent": RISSCParams(
        temperature=0.40,
        top_p=0.65,
        top_k=25,
        speed=0.75,
        repetition_penalty=8.0,
        rissc_mode="deepen",
        description="Somatic guide — slow, low, directing attention inward",
    ),

    "emergent": RISSCParams(
        temperature=0.50,
        top_p=0.72,
        top_k=35,
        speed=0.80,
        repetition_penalty=9.0,
        rissc_mode="deepen",
        description="Something new is arriving — reverent, unhurried",
    ),

    # ── COMPASSION ───────────────────────────────────────────────────────
    # Client is meeting themselves with tenderness. Nate's voice
    # becomes the softest version of itself — an invitation, not a push.
    "compassionate": RISSCParams(
        temperature=0.50,
        top_p=0.75,
        top_k=40,
        speed=0.82,
        repetition_penalty=9.0,
        rissc_mode="compassion",
        description="Soft invitation — tender, gentle, self-meeting",
    ),

    "transformative": RISSCParams(
        temperature=0.60,
        top_p=0.80,
        top_k=45,
        speed=0.88,
        repetition_penalty=9.0,
        rissc_mode="compassion",
        description="Integration warmth — the moment after the shift",
    ),
}

DEFAULT_PROFILE = RISSC_PROFILES["grounded"]


def get_rissc_params(
    felt_sense: str = "grounded",
    client_biometrics: Optional[Dict[str, float]] = None,
) -> RISSCParams:
    """
    Resolve RISSC voice parameters from felt_sense and optional client biometrics.

    The biometrics create a counter-resonance: when the client is stressed,
    Nate becomes calmer. When the client is warm and open, Nate matches.
    This is AEDP's "right-brain to right-brain" attunement.
    """
    profile = RISSC_PROFILES.get(felt_sense, DEFAULT_PROFILE)

    if not client_biometrics:
        return profile

    params = RISSCParams(
        temperature=profile.temperature,
        top_p=profile.top_p,
        top_k=profile.top_k,
        speed=profile.speed,
        repetition_penalty=profile.repetition_penalty,
        rissc_mode=profile.rissc_mode,
        description=profile.description,
    )

    stress = client_biometrics.get("voice_stress_index", 0.0)
    warmth = client_biometrics.get("voice_warmth_index", 0.0)
    speech_rate = client_biometrics.get("speech_rate", 120.0)

    # Counter-resonance: high client stress → Nate becomes even calmer
    if stress > 0.6:
        params.speed = max(0.65, params.speed - 0.10)
        params.temperature = max(0.25, params.temperature - 0.15)
        params.top_p = max(0.50, params.top_p - 0.10)
        params.rissc_mode = "regulate"
        _logger.debug("RISSC: client stress=%.2f → regulate override", stress)

    elif stress > 0.4:
        params.speed = max(0.70, params.speed - 0.05)
        params.temperature = max(0.35, params.temperature - 0.08)
        params.rissc_mode = "soothe"
        _logger.debug("RISSC: client stress=%.2f → soothe adjustment", stress)

    # Mirror-resonance: high client warmth → Nate warms to match
    if warmth > 0.7:
        params.temperature = min(0.80, params.temperature + 0.10)
        params.top_p = min(0.90, params.top_p + 0.05)
        params.speed = min(1.0, params.speed + 0.03)
        _logger.debug("RISSC: client warmth=%.2f → connection mirror", warmth)

    # ── Pace adaptation: two distinct modes ─────────────────────────────
    #
    # THERAPEUTIC (regulate, soothe, deepen, compassion):
    #   Strong pace-matching (75% blend). Nate attunes to the caller's
    #   rhythm as clinical mirroring — right-brain to right-brain.
    #
    # CONVERSATIONAL (connect):
    #   Nate keeps his own natural energy with light awareness of the
    #   caller's pace (20% blend) plus ±6% organic jitter so he sounds
    #   alive — sometimes a touch faster when he's engaged, sometimes
    #   easing back. Like a real person, not a metronome.

    REFERENCE_WPM = 140.0
    _THERAPEUTIC_MODES = {"regulate", "soothe", "deepen", "compassion"}

    if speech_rate > 0:
        pace_ratio = speech_rate / REFERENCE_WPM

        if params.rissc_mode in _THERAPEUTIC_MODES:
            blend = 0.75
            target_speed = params.speed * pace_ratio
            params.speed = params.speed + blend * (target_speed - params.speed)
            _logger.debug(
                "RISSC [therapeutic]: caller WPM=%.0f, blend=%.0f%%, speed=%.2f",
                speech_rate, blend * 100, params.speed,
            )
        else:
            blend = 0.20
            jitter = random.uniform(-0.06, 0.06)
            target_speed = params.speed * pace_ratio
            params.speed = params.speed + blend * (target_speed - params.speed) + jitter
            _logger.debug(
                "RISSC [conversational]: caller WPM=%.0f, blend=%.0f%%, jitter=%+.2f, speed=%.2f",
                speech_rate, blend * 100, jitter, params.speed,
            )

    params.speed = max(0.65, min(1.30, params.speed))
    return params


def rissc_to_dict(params: RISSCParams) -> Dict[str, str]:
    """Convert RISSCParams to the form-data dict the XTTS server expects."""
    return {
        "temperature": str(params.temperature),
        "top_p": str(params.top_p),
        "top_k": str(params.top_k),
        "speed": str(params.speed),
        "repetition_penalty": str(params.repetition_penalty),
    }


def rissc_to_edge_tts(params: RISSCParams) -> Dict[str, str]:
    """
    Convert RISSC params to Edge TTS rate/pitch for the fallback path.
    Maps the continuous RISSC space back to Edge TTS's percentage-based controls.
    """
    speed_pct = int((params.speed - 1.0) * 100)
    rate_str = f"{speed_pct:+d}%"

    pitch_hz = 0
    if params.rissc_mode == "regulate":
        pitch_hz = -3
    elif params.rissc_mode == "soothe":
        pitch_hz = -2
    elif params.rissc_mode == "deepen":
        pitch_hz = -4
    elif params.rissc_mode == "compassion":
        pitch_hz = -1

    return {
        "rate": rate_str,
        "pitch": f"{pitch_hz:+d}Hz",
    }
