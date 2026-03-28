"""
Backchannel Engine + Multi-Signal Turn Detector for voice therapy pipelines.

Patent 8, Claim 1: Backchannel Engine
Patent 11: Neural Mirror integration (register_bias from NeuralMirror Phase 5)

CRITICAL ISOLATION RULE:
Backchannel clips are injected DIRECTLY to the Twilio WebSocket media stream.
They are NEVER sent through Grok's audio input or any inference provider's audio
channel. The inference provider must be completely unaware that backchannels are
occurring.
"""

from __future__ import annotations

import base64
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nate.backchannel")

_CLIPS_DIR = Path(
    os.getenv(
        "BACKCHANNEL_CLIPS_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "assets" / "backchannel_clips"),
    )
)

REGISTERS = ("neutral", "warm", "empathic", "validating")

MIN_INTERVAL_S = 6.0
MAX_INTERVAL_S = 12.0


@dataclass
class BackchannelClip:
    register: str
    name: str
    audio_b64: str
    duration_ms: int


class BackchannelEngine:
    """Fires pre-rendered mulaw clips during continuous client speech.

    Register selection is based on audio energy + pitch by default.
    When Neural Mirror Phase 5 is active, the mirror overrides via ``register_bias``.
    """

    def __init__(self, clips_dir: Optional[Path] = None):
        self._clips: Dict[str, List[BackchannelClip]] = {r: [] for r in REGISTERS}
        self._enabled = False
        self._last_fire: float = 0.0
        self._next_interval: float = self._random_interval()
        self._register_bias: Optional[str] = None
        self._load_clips(clips_dir or _CLIPS_DIR)

    @staticmethod
    def _strip_wav_header(data: bytes) -> bytes:
        """Strip RIFF/WAV header to get raw audio payload for Twilio."""
        if len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            offset = 12
            while offset + 8 <= len(data):
                chunk_id = data[offset : offset + 4]
                chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
                if chunk_id == b"data":
                    return data[offset + 8 : offset + 8 + chunk_size]
                offset += 8 + chunk_size
            return data[44:]
        return data

    def _load_clips(self, clips_dir: Path) -> None:
        if not clips_dir.is_dir():
            logger.warning("Backchannel clips dir not found: %s", clips_dir)
            return
        loaded = 0
        for register in REGISTERS:
            reg_dir = clips_dir / register
            if not reg_dir.is_dir():
                continue
            for wav_path in sorted(reg_dir.glob("*.wav")):
                try:
                    raw = self._strip_wav_header(wav_path.read_bytes())
                    audio_b64 = base64.b64encode(raw).decode("ascii")
                    size = len(raw)
                    duration_ms = max(1, (size * 1000) // 8000)
                    clip = BackchannelClip(
                        register=register,
                        name=wav_path.stem,
                        audio_b64=audio_b64,
                        duration_ms=duration_ms,
                    )
                    self._clips[register].append(clip)
                    loaded += 1
                except Exception as e:
                    logger.warning("Failed to load backchannel clip %s: %s", wav_path, e)
        logger.info("BackchannelEngine: loaded %d clips across %d registers", loaded, len(REGISTERS))

    @staticmethod
    def _random_interval() -> float:
        return random.uniform(MIN_INTERVAL_S, MAX_INTERVAL_S)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def reset(self) -> None:
        self._last_fire = 0.0
        self._next_interval = self._random_interval()
        self._register_bias = None

    def set_register_bias(self, register: Optional[str]) -> None:
        """Override from Neural Mirror Phase 5."""
        if register and register in REGISTERS:
            self._register_bias = register

    def _select_register(
        self, energy: float = 0.0, pitch_hz: float = 0.0
    ) -> str:
        if self._register_bias:
            return self._register_bias
        if energy < 0.3 and pitch_hz < 150:
            return "empathic"
        if energy > 0.7 or pitch_hz > 250:
            return "validating"
        if energy > 0.4:
            return "neutral"
        return "warm"

    def get_backchannel(
        self,
        energy: float = 0.0,
        pitch_hz: float = 0.0,
    ) -> Optional[BackchannelClip]:
        """Return a clip if it's time to inject one, else None."""
        if not self._enabled:
            return None

        now = time.monotonic()
        if now - self._last_fire < self._next_interval:
            return None

        register = self._select_register(energy, pitch_hz)
        candidates = self._clips.get(register) or []
        if not candidates:
            for fallback_reg in REGISTERS:
                candidates = self._clips.get(fallback_reg) or []
                if candidates:
                    break
        if not candidates:
            return None

        clip = random.choice(candidates)
        self._last_fire = now
        self._next_interval = self._random_interval()
        return clip


@dataclass
class TurnSignals:
    """Accumulated signals for multi-signal turn detection."""
    vad_silence_ms: float = 0.0
    energy_peak: float = 0.0
    energy_current: float = 0.0
    speech_duration_ms: float = 0.0
    backchannel_active: bool = False
    last_speech_time: float = 0.0


class MultiSignalTurnDetector:
    """Combines 4 signals before committing to a response.
    Patent 8: Voice therapy turn detection.

    This is the REAL silence gate (1500ms). The native VAD (Fix 1) fires at
    800ms as an early candidate trigger; this detector holds until all signals
    confirm a genuine turn end.

    Signals:
    1. VAD silence >= 1500ms threshold
    2. Backchannel engine confirms client not in continuous speech
    3. Energy trajectory declining (below 30% of peak)
    4. Client spoke for at least 1.0 second (filters "mmhmm" acknowledgments)
    """

    SILENCE_THRESHOLD_MS = 1500.0
    MIN_SPEECH_DURATION_MS = 1000.0
    ENERGY_DECLINE_RATIO = 0.30

    def __init__(self):
        self._signals = TurnSignals()
        self._candidate_start: Optional[float] = None

    def on_audio_frame(
        self,
        energy: float,
        is_speech: bool,
        timestamp_ms: float,
    ) -> None:
        """Feed each audio frame into the detector."""
        if is_speech:
            self._signals.speech_duration_ms += 20.0
            if energy > self._signals.energy_peak:
                self._signals.energy_peak = energy
            self._signals.energy_current = energy
            self._signals.last_speech_time = timestamp_ms
            self._signals.vad_silence_ms = 0.0
            self._candidate_start = None
        else:
            self._signals.vad_silence_ms += 20.0
            self._signals.energy_current = energy

    def on_vad_speech_stopped(self) -> None:
        """Called when native VAD fires speech_stopped (at 800ms).
        Starts the candidate timer -- the detector will confirm or reject."""
        if self._candidate_start is None:
            self._candidate_start = time.monotonic()

    def set_backchannel_active(self, active: bool) -> None:
        self._signals.backchannel_active = active

    def should_trigger_response(self) -> Tuple[bool, float]:
        """Returns (should_end_turn, confidence_score).
        Confidence is 0.0 to 1.0 based on how many signals agree."""
        score = 0.0
        checks = 0

        silence_ok = self._signals.vad_silence_ms >= self.SILENCE_THRESHOLD_MS
        if silence_ok:
            score += 0.35
        checks += 1

        not_speaking = not self._signals.backchannel_active
        if not_speaking:
            score += 0.15
        checks += 1

        energy_declining = (
            self._signals.energy_peak > 0
            and self._signals.energy_current
            <= self._signals.energy_peak * self.ENERGY_DECLINE_RATIO
        )
        if energy_declining:
            score += 0.25
        checks += 1

        spoke_enough = (
            self._signals.speech_duration_ms >= self.MIN_SPEECH_DURATION_MS
        )
        if spoke_enough:
            score += 0.25
        checks += 1

        should_trigger = silence_ok and spoke_enough and (energy_declining or not_speaking)
        return should_trigger, score

    def reset(self) -> None:
        self._signals = TurnSignals()
        self._candidate_start = None
