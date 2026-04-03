"""
Therapeutic Identity Inference Engine — Phase 1: Voice Enrollment Service.

Patent 11 Extension: Progressive voice calibration with greeting signature builder.
Calibration tiers: 10s=LOW, 30s=MEDIUM, 60s=HIGH confidence.
Fast-Path greeting signature for 4-second ID on subsequent calls.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("nate.voice_enrollment")

CALIBRATION_TIERS = {
    "LOW": 10.0,
    "MEDIUM": 30.0,
    "HIGH": 60.0,
}

GREETING_WINDOW_S = 4.0
ENROLLMENT_SAMPLE_RATE = 8000
MIN_GREETING_SAMPLES = 3


@dataclass
class GreetingSignature:
    """Fast-path 4-second voiceprint from opening greeting."""
    user_id: str
    pitch_contour: List[float] = field(default_factory=list)
    energy_contour: List[float] = field(default_factory=list)
    speaking_rate: float = 0.0
    duration_s: float = 0.0
    sample_count: int = 0
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "pitch_contour": self.pitch_contour[:20],
            "energy_contour": self.energy_contour[:20],
            "speaking_rate": self.speaking_rate,
            "duration_s": self.duration_s,
            "sample_count": self.sample_count,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GreetingSignature":
        return cls(
            user_id=d.get("user_id", ""),
            pitch_contour=d.get("pitch_contour", []),
            energy_contour=d.get("energy_contour", []),
            speaking_rate=d.get("speaking_rate", 0.0),
            duration_s=d.get("duration_s", 0.0),
            sample_count=d.get("sample_count", 0),
            confidence=d.get("confidence", 0.0),
        )


@dataclass
class EnrollmentProfile:
    """Accumulated voice enrollment data for one user."""
    user_id: str
    total_audio_s: float = 0.0
    calibration_tier: str = "NONE"
    greeting_signatures: List[GreetingSignature] = field(default_factory=list)
    mfcc_mean: Optional[List[float]] = None
    mfcc_covariance: Optional[List[List[float]]] = None
    pitch_baseline: float = 0.0
    pitch_variance: float = 0.0
    energy_baseline: float = 0.0
    jitter_baseline: float = 0.0
    shimmer_baseline: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_enrolled(self) -> bool:
        return self.calibration_tier in ("LOW", "MEDIUM", "HIGH")

    @property
    def pitch_mean(self) -> float:
        return self.pitch_baseline

    @property
    def energy_mean(self) -> float:
        return self.energy_baseline

    @property
    def speech_rate(self) -> float:
        return getattr(self, "_speech_rate", 0.0)

    @speech_rate.setter
    def speech_rate(self, value: float) -> None:
        self._speech_rate = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "total_audio_s": self.total_audio_s,
            "calibration_tier": self.calibration_tier,
            "greeting_signatures": [g.to_dict() for g in self.greeting_signatures],
            "mfcc_mean": self.mfcc_mean,
            "pitch_baseline": self.pitch_baseline,
            "pitch_variance": self.pitch_variance,
            "energy_baseline": self.energy_baseline,
            "jitter_baseline": self.jitter_baseline,
            "shimmer_baseline": self.shimmer_baseline,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EnrollmentProfile":
        p = cls(user_id=d.get("user_id", ""))
        p.total_audio_s = d.get("total_audio_s", 0.0)
        p.calibration_tier = d.get("calibration_tier", "NONE")
        p.greeting_signatures = [
            GreetingSignature.from_dict(g) for g in d.get("greeting_signatures", [])
        ]
        p.mfcc_mean = d.get("mfcc_mean")
        p.pitch_baseline = d.get("pitch_baseline", 0.0)
        p.pitch_variance = d.get("pitch_variance", 0.0)
        p.energy_baseline = d.get("energy_baseline", 0.0)
        p.jitter_baseline = d.get("jitter_baseline", 0.0)
        p.shimmer_baseline = d.get("shimmer_baseline", 0.0)
        p.created_at = d.get("created_at", 0.0)
        p.updated_at = d.get("updated_at", 0.0)
        return p


class VoiceEnrollmentService:
    """
    Progressive voice enrollment with greeting signature fast-path.

    Accumulates audio across sessions to build speaker-specific baselines.
    Three tiers: LOW (10s), MEDIUM (30s), HIGH (60s).
    Greeting signatures capture the first 4 seconds of each call for
    rapid re-identification without full biometric processing.
    """

    def __init__(self, db_pool=None, sample_rate: int = ENROLLMENT_SAMPLE_RATE):
        self._db = db_pool
        self._sr = sample_rate
        self._profiles: Dict[str, EnrollmentProfile] = {}
        self._active_sessions: Dict[str, _EnrollmentSession] = {}

    async def load_profile(self, user_id: str) -> EnrollmentProfile:
        if user_id in self._profiles:
            return self._profiles[user_id]

        profile = EnrollmentProfile(user_id=user_id)
        if self._db:
            try:
                row = await self._db.fetchrow(
                    """SELECT confidence_tier, pitch_mean, pitch_variance,
                              energy_mean, speech_rate, spectral_centroid,
                              pause_ratio, session_count, greeting_features,
                              last_calibrated
                       FROM voice_enrollment_profiles WHERE user_id = $1""",
                    user_id,
                )
                if row:
                    profile.calibration_tier = row["confidence_tier"] or "NONE"
                    profile.pitch_baseline = row["pitch_mean"] or 0.0
                    profile.pitch_variance = row["pitch_variance"] or 0.0
                    profile.energy_baseline = row["energy_mean"] or 0.0
                    profile.total_audio_s = float((row["session_count"] or 0) * 30)
                    import json
                    gf = row["greeting_features"]
                    if gf and isinstance(gf, str):
                        gf = json.loads(gf)
                    if isinstance(gf, dict):
                        sigs = gf.get("signatures", [])
                        profile.greeting_signatures = [
                            GreetingSignature.from_dict(s) for s in sigs
                        ]
            except Exception as e:
                logger.warning("VoiceEnrollment: load failed for %s: %s", user_id, e)

        self._profiles[user_id] = profile
        return profile

    def start_session(self, user_id: str, call_sid: str) -> None:
        self._active_sessions[call_sid] = _EnrollmentSession(
            user_id=user_id, call_sid=call_sid, sample_rate=self._sr,
        )

    def feed_audio(self, call_sid: str, pcm_bytes: bytes) -> None:
        session = self._active_sessions.get(call_sid)
        if not session:
            return
        session.accumulate(pcm_bytes)

    async def finalize_session(self, call_sid: str) -> Optional[EnrollmentProfile]:
        session = self._active_sessions.pop(call_sid, None)
        if not session:
            return None

        profile = await self.load_profile(session.user_id)
        greeting = session.build_greeting_signature()
        features = session.compute_aggregate_features()

        profile.total_audio_s += session.total_audio_s
        if greeting and greeting.duration_s >= 2.0:
            profile.greeting_signatures.append(greeting)
            if len(profile.greeting_signatures) > 10:
                profile.greeting_signatures = profile.greeting_signatures[-10:]
            greeting.confidence = min(
                1.0, len(profile.greeting_signatures) / MIN_GREETING_SAMPLES
            )

        if features:
            profile.pitch_baseline = features.get("pitch_mean", profile.pitch_baseline)
            profile.pitch_variance = features.get("pitch_variance", profile.pitch_variance)
            profile.energy_baseline = features.get("energy_mean", profile.energy_baseline)
            profile.jitter_baseline = features.get("jitter", profile.jitter_baseline)
            profile.shimmer_baseline = features.get("shimmer", profile.shimmer_baseline)

        for tier_name, threshold in sorted(CALIBRATION_TIERS.items(), key=lambda x: x[1], reverse=True):
            if profile.total_audio_s >= threshold:
                profile.calibration_tier = tier_name
                break

        profile.updated_at = time.time()
        self._profiles[session.user_id] = profile
        await self._persist(profile)
        return profile

    def match_greeting(
        self, call_sid: str, candidates: List[EnrollmentProfile],
    ) -> List[Dict[str, Any]]:
        """
        Compare first 4s of current call against greeting signatures of candidates.
        Returns ranked list of (user_id, confidence) pairs.
        """
        session = self._active_sessions.get(call_sid)
        if not session:
            return []

        current = session.build_greeting_signature()
        if not current or current.duration_s < 1.5:
            return []

        scores = []
        for candidate in candidates:
            if not candidate.greeting_signatures:
                continue
            best_score = 0.0
            for sig in candidate.greeting_signatures:
                score = _compare_greeting_signatures(current, sig)
                best_score = max(best_score, score)
            if best_score > 0.3:
                scores.append({
                    "user_id": candidate.user_id,
                    "confidence": round(best_score, 3),
                    "tier": candidate.calibration_tier,
                })

        scores.sort(key=lambda x: x["confidence"], reverse=True)
        return scores

    async def _persist(self, profile: EnrollmentProfile) -> None:
        if not self._db:
            return
        try:
            import json
            greeting_json = json.dumps({
                "signatures": [g.to_dict() for g in profile.greeting_signatures[-10:]]
            })
            await self._db.execute(
                """INSERT INTO voice_enrollment_profiles
                       (user_id, confidence_tier, pitch_mean, pitch_variance,
                        energy_mean, speech_rate, session_count,
                        greeting_features, last_calibrated, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW(), NOW())
                   ON CONFLICT (user_id, tenant_id) DO UPDATE SET
                     confidence_tier = EXCLUDED.confidence_tier,
                     pitch_mean = EXCLUDED.pitch_mean,
                     pitch_variance = EXCLUDED.pitch_variance,
                     energy_mean = EXCLUDED.energy_mean,
                     speech_rate = EXCLUDED.speech_rate,
                     session_count = voice_enrollment_profiles.session_count + 1,
                     greeting_features = EXCLUDED.greeting_features,
                     last_calibrated = NOW(),
                     updated_at = NOW()""",
                profile.user_id, profile.calibration_tier,
                profile.pitch_baseline, profile.pitch_variance,
                profile.energy_baseline, 0.0,
                1, greeting_json,
            )
        except Exception as e:
            logger.warning("VoiceEnrollment: persist failed for %s: %s", profile.user_id, e)


class _EnrollmentSession:
    """In-memory accumulator for a single call's enrollment data."""

    def __init__(self, user_id: str, call_sid: str, sample_rate: int):
        self.user_id = user_id
        self.call_sid = call_sid
        self._sr = sample_rate
        self._greeting_chunks: List[bytes] = []
        self._greeting_done = False
        self._greeting_bytes = 0
        self._greeting_limit = int(GREETING_WINDOW_S * sample_rate * 2)
        self._all_chunks: List[bytes] = []
        self._total_bytes = 0

    @property
    def total_audio_s(self) -> float:
        return self._total_bytes / max(self._sr * 2, 1)

    def accumulate(self, pcm_bytes: bytes) -> None:
        self._all_chunks.append(pcm_bytes)
        self._total_bytes += len(pcm_bytes)
        if not self._greeting_done:
            self._greeting_chunks.append(pcm_bytes)
            self._greeting_bytes += len(pcm_bytes)
            if self._greeting_bytes >= self._greeting_limit:
                self._greeting_done = True

    def build_greeting_signature(self) -> Optional[GreetingSignature]:
        if not self._greeting_chunks:
            return None

        pcm = b"".join(self._greeting_chunks)
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) < self._sr:
            return None

        frame_len = int(0.02 * self._sr)
        n_frames = len(samples) // frame_len
        if n_frames < 5:
            return None

        pitch_contour = []
        energy_contour = []
        for i in range(min(n_frames, 200)):
            frame = samples[i * frame_len : (i + 1) * frame_len]
            energy_contour.append(float(np.sqrt(np.mean(frame ** 2))))
            corr = np.correlate(frame, frame, mode="full")
            corr = corr[len(corr) // 2:]
            peak_idx = np.argmax(corr[20:]) + 20 if len(corr) > 20 else 1
            pitch_contour.append(float(self._sr / max(peak_idx, 1)))

        sig = GreetingSignature(
            user_id=self.user_id,
            pitch_contour=pitch_contour,
            energy_contour=energy_contour,
            speaking_rate=float(np.mean(energy_contour) * 100),
            duration_s=self._greeting_bytes / max(self._sr * 2, 1),
        )
        return sig

    def compute_aggregate_features(self) -> Optional[Dict[str, float]]:
        if not self._all_chunks:
            return None
        pcm = b"".join(self._all_chunks)
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) < self._sr * 2:
            return None

        frame_len = int(0.02 * self._sr)
        pitches = []
        energies = []
        for i in range(len(samples) // frame_len):
            frame = samples[i * frame_len : (i + 1) * frame_len]
            e = float(np.sqrt(np.mean(frame ** 2)))
            energies.append(e)
            if e > 0.01:
                corr = np.correlate(frame, frame, mode="full")
                corr = corr[len(corr) // 2:]
                peak_idx = np.argmax(corr[20:]) + 20 if len(corr) > 20 else 1
                pitches.append(float(self._sr / max(peak_idx, 1)))

        if not pitches:
            return None

        return {
            "pitch_mean": float(np.mean(pitches)),
            "pitch_variance": float(np.var(pitches)),
            "energy_mean": float(np.mean(energies)),
            "jitter": float(np.mean(np.abs(np.diff(pitches))) / max(np.mean(pitches), 1)),
            "shimmer": float(np.mean(np.abs(np.diff(energies))) / max(np.mean(energies), 1e-6)),
        }


def _compare_greeting_signatures(a: GreetingSignature, b: GreetingSignature) -> float:
    """Compare two greeting signatures using pitch + energy contour correlation."""
    if not a.pitch_contour or not b.pitch_contour:
        return 0.0

    min_len = min(len(a.pitch_contour), len(b.pitch_contour), 100)
    if min_len < 5:
        return 0.0

    pa = np.array(a.pitch_contour[:min_len])
    pb = np.array(b.pitch_contour[:min_len])
    ea = np.array(a.energy_contour[:min_len]) if a.energy_contour else np.ones(min_len)
    eb = np.array(b.energy_contour[:min_len]) if b.energy_contour else np.ones(min_len)

    pitch_corr = _safe_corr(pa, pb)
    energy_corr = _safe_corr(ea, eb)
    rate_sim = 1.0 - min(abs(a.speaking_rate - b.speaking_rate) / max(a.speaking_rate, 1e-6), 1.0)

    return float(pitch_corr * 0.5 + energy_corr * 0.3 + rate_sim * 0.2)


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2 or np.std(a) < 1e-8 or np.std(b) < 1e-8:
        return 0.0
    return float(np.clip(np.corrcoef(a, b)[0, 1], 0.0, 1.0))
