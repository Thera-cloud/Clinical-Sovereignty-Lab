"""
Neural Mirror System — Virtual EEG Fingerprinting & Emotional DNA.

Patent 11: Provisional Patent Application No. 11 — Neural Mirror Co-regulation.

Phases:
  1. VoiceFeatureExtractor (~90 features, librosa + parselmouth)
  2. EmotionalBaselineCapturer (rolling buffer, 10 emotions)
  3. VoiceEEGAutoencoder (PyTorch, 90 -> 32 latent, 8 structured bands)
  4. NeuralFingerprint (GMM clustering, deviation metrics)
  5. NeuralMirror co-regulation engine (technique weights, backchannel bias)
  6. VirtualEEGInterpreter (latent -> band energies -> Nevedal factors)
  7. Crystal EEG context integration
  8. Cross-session trajectory analysis + tunneling detection

Dependencies: librosa, parselmouth, numpy, torch (CPU-only), scikit-learn
System package: libsndfile1 (for librosa)
"""

from __future__ import annotations

import io
import logging
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nate.neural_mirror")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEATURE_DIM = 90
LATENT_DIM = 32
HIDDEN_DIM = 64
NUM_BANDS = 8
BAND_SIZE = LATENT_DIM // NUM_BANDS  # 4

BAND_NAMES = (
    "delta", "theta", "alpha", "beta",
    "gamma", "resistance", "coherence", "signature",
)

TARGET_EMOTIONS = (
    "grief", "anger", "joy", "contentment", "shame",
    "conviction", "fear", "curiosity", "dissociation", "integration",
)

MIN_TRAINING_SAMPLES = 1000
MIN_FINGERPRINT_SAMPLES = 50
BASELINE_COOLDOWN_S = 120.0
BASELINE_CONFIDENCE_THRESHOLD = 0.75

# Phase 8 tunneling thresholds (configurable)
TUNNEL_RESISTANCE_DROP = 0.5
TUNNEL_GAMMA_RISE = 0.4
TUNNEL_INTERMEDIATE_CAP = 0.3
TUNNEL_WINDOW_SECONDS = 30

# Prompt injection budget (tokens)
CRYSTAL_CONTEXT_BUDGET = 300
NEURAL_MIRROR_BUDGET = 200
HELIX_INJECTION_BUDGET = 200
USER_MEMORY_BUDGET = 200
TOTAL_INJECTION_BUDGET = 900

# Heuristic mode mappings
HEURISTIC_PITCH_FACTOR = 1.0
HEURISTIC_RATE_FACTOR = 1.3
HEURISTIC_ENERGY_FACTOR = 0.4
HEURISTIC_JITTER_FACTOR = 2.0
HEURISTIC_PAUSE_FACTOR = 1.5
HEURISTIC_PITCH_VAR_FACTOR = 2.0


# ---------------------------------------------------------------------------
# Phase 1: VoiceFeatureExtractor
# ---------------------------------------------------------------------------

@dataclass
class VoiceFeatureVector:
    """~90-dimensional feature vector from voice audio."""

    # Time-domain
    speech_rate: float = 0.0
    pause_ratio: float = 0.0
    energy_mean: float = 0.0
    energy_variance: float = 0.0
    energy_trajectory: float = 0.0
    zero_crossing_rate: float = 0.0
    voiced_ratio: float = 0.0
    articulation_rate: float = 0.0

    # Frequency-domain
    pitch_mean: float = 0.0
    pitch_variance: float = 0.0
    pitch_range: float = 0.0
    formant_f1: float = 0.0
    formant_f2: float = 0.0
    formant_f3: float = 0.0
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    spectral_rolloff: float = 0.0
    hnr: float = 0.0
    jitter: float = 0.0
    shimmer: float = 0.0

    # MFCCs (13 + 13 delta + 13 delta-delta = 39)
    mfccs: List[float] = field(default_factory=lambda: [0.0] * 39)

    # Time-frequency
    spectral_flux: float = 0.0
    chroma: List[float] = field(default_factory=lambda: [0.0] * 12)
    onset_strength: float = 0.0

    # Derived composites
    emotional_volatility: float = 0.0
    vocal_tension: float = 0.0
    prosodic_engagement: float = 0.0
    respiratory_pattern: float = 0.0

    def to_vector(self) -> np.ndarray:
        """Convert to ~90-dim float32 numpy array."""
        scalars = [
            self.speech_rate, self.pause_ratio, self.energy_mean,
            self.energy_variance, self.energy_trajectory, self.zero_crossing_rate,
            self.voiced_ratio, self.articulation_rate,
            self.pitch_mean, self.pitch_variance, self.pitch_range,
            self.formant_f1, self.formant_f2, self.formant_f3,
            self.spectral_centroid, self.spectral_bandwidth, self.spectral_rolloff,
            self.hnr, self.jitter, self.shimmer,
        ]
        scalars.extend(self.mfccs[:39])
        scalars.append(self.spectral_flux)
        scalars.extend(self.chroma[:12])
        scalars.append(self.onset_strength)
        scalars.extend([
            self.emotional_volatility, self.vocal_tension,
            self.prosodic_engagement, self.respiratory_pattern,
        ])
        vec = np.array(scalars, dtype=np.float32)
        if len(vec) < FEATURE_DIM:
            vec = np.pad(vec, (0, FEATURE_DIM - len(vec)))
        return vec[:FEATURE_DIM]


class VoiceFeatureExtractor:
    """Extracts ~90 voice features from raw audio.

    Requires librosa and parselmouth. Falls back to basic numpy extraction
    if either is unavailable.
    """

    def __init__(self, sample_rate: int = 8000):
        self._sr = sample_rate
        self._librosa = None
        self._parselmouth = None
        try:
            import librosa
            self._librosa = librosa
        except ImportError:
            logger.warning("librosa not available — using basic feature extraction")
        try:
            import parselmouth
            self._parselmouth = parselmouth
        except ImportError:
            logger.warning("parselmouth not available — pitch/formant analysis limited")

    def extract(self, audio_bytes: bytes, sample_rate: int = 0) -> VoiceFeatureVector:
        """Extract features from raw PCM audio bytes (16-bit mono)."""
        sr = sample_rate or self._sr
        features = VoiceFeatureVector()

        if len(audio_bytes) < 320:
            return features

        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        if len(samples) == 0:
            return features
        samples = samples / 32768.0  # normalize to [-1, 1]

        # Time-domain features
        features.energy_mean = float(np.mean(np.abs(samples)))
        features.energy_variance = float(np.var(np.abs(samples)))

        half = len(samples) // 2
        if half > 0:
            e1 = float(np.mean(np.abs(samples[:half])))
            e2 = float(np.mean(np.abs(samples[half:])))
            features.energy_trajectory = e2 - e1

        crossings = np.diff(np.sign(samples))
        features.zero_crossing_rate = float(np.sum(np.abs(crossings) > 0)) / max(len(samples), 1)

        threshold = 0.02
        voiced = np.abs(samples) > threshold
        features.voiced_ratio = float(np.mean(voiced))

        # Pause analysis
        frame_len = int(0.02 * sr)
        if frame_len > 0:
            n_frames = len(samples) // frame_len
            if n_frames > 0:
                pause_frames = 0
                for i in range(n_frames):
                    frame = samples[i * frame_len : (i + 1) * frame_len]
                    if np.mean(np.abs(frame)) < threshold:
                        pause_frames += 1
                features.pause_ratio = pause_frames / n_frames

        if self._librosa is not None:
            features = self._extract_librosa(samples, sr, features)

        if self._parselmouth is not None:
            features = self._extract_parselmouth(samples, sr, features)

        # Derived composites
        features.emotional_volatility = (
            features.pitch_variance * 0.4
            + features.energy_variance * 0.3
            + features.spectral_flux * 0.3
        )
        features.vocal_tension = (
            features.jitter * 0.35
            + features.shimmer * 0.35
            + max(0.0, 1.0 - features.hnr / 20.0) * 0.3
        )
        features.prosodic_engagement = (
            features.pitch_range * 0.3
            + features.energy_trajectory * 0.3
            + features.onset_strength * 0.4
        )
        features.respiratory_pattern = features.pause_ratio

        return features

    def _extract_librosa(
        self, samples: np.ndarray, sr: int, features: VoiceFeatureVector
    ) -> VoiceFeatureVector:
        lb = self._librosa
        if lb is None:
            return features

        try:
            mfccs = lb.feature.mfcc(y=samples, sr=sr, n_mfcc=13)
            mfcc_mean = np.mean(mfccs, axis=1).tolist()
            delta = lb.feature.delta(mfccs)
            delta_mean = np.mean(delta, axis=1).tolist()
            delta2 = lb.feature.delta(mfccs, order=2)
            delta2_mean = np.mean(delta2, axis=1).tolist()
            features.mfccs = mfcc_mean + delta_mean + delta2_mean
        except Exception:
            pass

        try:
            cent = lb.feature.spectral_centroid(y=samples, sr=sr)
            features.spectral_centroid = float(np.mean(cent))
        except Exception:
            pass

        try:
            bw = lb.feature.spectral_bandwidth(y=samples, sr=sr)
            features.spectral_bandwidth = float(np.mean(bw))
        except Exception:
            pass

        try:
            ro = lb.feature.spectral_rolloff(y=samples, sr=sr)
            features.spectral_rolloff = float(np.mean(ro))
        except Exception:
            pass

        try:
            S = np.abs(lb.stft(samples))
            flux = np.mean(np.diff(S, axis=1) ** 2)
            features.spectral_flux = float(flux)
        except Exception:
            pass

        try:
            chroma = lb.feature.chroma_stft(y=samples, sr=sr)
            features.chroma = np.mean(chroma, axis=1).tolist()[:12]
        except Exception:
            pass

        try:
            onset_env = lb.onset.onset_strength(y=samples, sr=sr)
            features.onset_strength = float(np.mean(onset_env))
        except Exception:
            pass

        return features

    def _extract_parselmouth(
        self, samples: np.ndarray, sr: int, features: VoiceFeatureVector
    ) -> VoiceFeatureVector:
        pm = self._parselmouth
        if pm is None:
            return features

        try:
            snd = pm.Sound(samples, sampling_frequency=sr)

            pitch = snd.to_pitch()
            pitch_values = pitch.selected_array["frequency"]
            voiced_pitches = pitch_values[pitch_values > 0]
            if len(voiced_pitches) > 0:
                features.pitch_mean = float(np.mean(voiced_pitches))
                features.pitch_variance = float(np.var(voiced_pitches))
                features.pitch_range = float(np.ptp(voiced_pitches))

            try:
                formants = snd.to_formant_burg()
                mid = formants.get_time_step() * formants.get_number_of_frames() / 2
                features.formant_f1 = float(formants.get_value_at_time(1, mid) or 0)
                features.formant_f2 = float(formants.get_value_at_time(2, mid) or 0)
                features.formant_f3 = float(formants.get_value_at_time(3, mid) or 0)
            except Exception:
                pass

            try:
                harmonicity = snd.to_harmonicity()
                hnr_vals = harmonicity.values[harmonicity.values != -200]
                if len(hnr_vals) > 0:
                    features.hnr = float(np.mean(hnr_vals))
            except Exception:
                pass

            try:
                point_process = pm.praat.call(snd, "To PointProcess (periodic, cc)...", 75, 600)
                features.jitter = float(pm.praat.call(
                    point_process, "Get jitter (local)...", 0, 0, 0.0001, 0.02, 1.3
                ) or 0)
                features.shimmer = float(pm.praat.call(
                    [snd, point_process], "Get shimmer (local)...", 0, 0, 0.0001, 0.02, 1.3, 1.6
                ) or 0)
            except Exception:
                pass

        except Exception as e:
            logger.debug("parselmouth extraction error: %s", e)

        return features


# ---------------------------------------------------------------------------
# Phase 2: EmotionalBaselineCapturer
# ---------------------------------------------------------------------------

class EmotionalBaselineCapturer:
    """Captures emotional baselines from voice audio with a 30-second rolling buffer.

    When the feature extractor detects a clear emotional state with
    confidence >= 0.75, captures the buffered audio as a baseline sample.
    """

    def __init__(self, buffer_seconds: float = 30.0, sample_rate: int = 8000):
        self._buffer_seconds = buffer_seconds
        self._sr = sample_rate
        max_chunks = int(buffer_seconds * sample_rate / 160)  # 20ms chunks
        self._audio_buffer: deque = deque(maxlen=max_chunks)
        self._baselines: Dict[str, Dict[str, Any]] = {}
        self._last_capture: Dict[str, float] = {}

    def add_audio(self, chunk: bytes) -> None:
        self._audio_buffer.append(chunk)

    def check_and_capture(
        self,
        features: VoiceFeatureVector,
        user_id: str,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Check if we should capture an emotional baseline.

        Returns capture dict with emotion, confidence, audio_data, feature_vector
        if a capture is triggered. Otherwise None.
        """
        emotion, confidence = self._classify_emotion(features)
        if not emotion or confidence < BASELINE_CONFIDENCE_THRESHOLD:
            return None

        now = time.monotonic()
        if emotion in self._last_capture:
            if now - self._last_capture[emotion] < BASELINE_COOLDOWN_S:
                return None

        existing = self._baselines.get(emotion)
        if existing and existing.get("confidence", 0) >= confidence:
            return None

        audio_data = b"".join(self._audio_buffer)
        if len(audio_data) < self._sr * 2:  # at least 2 seconds
            return None

        capture = {
            "baseline_id": str(uuid.uuid4()),
            "user_id": user_id,
            "emotion": emotion,
            "audio_data": audio_data,
            "feature_vector": features.to_vector().tolist(),
            "session_id": session_id,
            "confidence": confidence,
            "captured_at": time.time(),
        }

        self._baselines[emotion] = capture
        self._last_capture[emotion] = now
        logger.info(
            "Captured %s baseline for %s (confidence=%.2f, %d bytes audio)",
            emotion, user_id, confidence, len(audio_data),
        )
        return capture

    def _classify_emotion(self, f: VoiceFeatureVector) -> Tuple[str, float]:
        """Simple heuristic emotion classifier from voice features.

        Returns (emotion_name, confidence). Full ML classifier is a future
        enhancement; these heuristics provide day-1 functionality.
        """
        candidates: List[Tuple[str, float]] = []

        # Grief: low pitch, low energy, slow, high pause ratio
        if f.pitch_mean > 0 and f.pitch_mean < 150 and f.energy_mean < 0.15 and f.pause_ratio > 0.4:
            candidates.append(("grief", 0.6 + 0.2 * f.pause_ratio))

        # Anger: high energy, high pitch variance, high onset strength
        if f.energy_mean > 0.3 and f.pitch_variance > 1000 and f.onset_strength > 0.5:
            candidates.append(("anger", 0.5 + 0.3 * min(f.energy_mean, 1.0)))

        # Joy: high pitch, moderate energy, high prosodic engagement
        if f.pitch_mean > 200 and f.prosodic_engagement > 0.3:
            candidates.append(("joy", 0.5 + 0.3 * min(f.prosodic_engagement, 1.0)))

        # Contentment: moderate everything, low volatility
        if 0.05 < f.energy_mean < 0.25 and f.emotional_volatility < 0.1:
            candidates.append(("contentment", 0.5 + 0.3 * (1.0 - f.emotional_volatility)))

        # Shame: low pitch, low energy, high jitter, low voiced ratio
        if f.pitch_mean > 0 and f.pitch_mean < 160 and f.energy_mean < 0.1 and f.jitter > 0.02:
            candidates.append(("shame", 0.5 + 0.3 * min(f.jitter * 10, 1.0)))

        # Conviction: high energy, stable pitch, high HNR
        if f.energy_mean > 0.2 and f.hnr > 12 and f.pitch_variance < 500:
            candidates.append(("conviction", 0.5 + 0.2 * min(f.hnr / 20, 1.0)))

        # Fear: high pitch, high energy variance, high jitter
        if f.pitch_mean > 180 and f.energy_variance > 0.01 and f.jitter > 0.015:
            candidates.append(("fear", 0.5 + 0.2 * min(f.jitter * 15, 1.0)))

        # Curiosity: rising pitch (positive trajectory), moderate energy
        if f.energy_trajectory > 0.02 and f.pitch_range > 50:
            candidates.append(("curiosity", 0.5 + 0.2 * min(f.pitch_range / 100, 1.0)))

        # Dissociation: very low energy, low voiced ratio, monotone
        if f.energy_mean < 0.05 and f.voiced_ratio < 0.3 and f.pitch_variance < 100:
            candidates.append(("dissociation", 0.6 + 0.2 * (1.0 - f.voiced_ratio)))

        # Integration: balanced features, moderate coherence indicators
        if (0.1 < f.energy_mean < 0.3
                and 100 < f.pitch_mean < 250
                and f.hnr > 8
                and f.emotional_volatility < 0.15):
            candidates.append(("integration", 0.5 + 0.2 * min(f.hnr / 15, 1.0)))

        if not candidates:
            return ("", 0.0)

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0]


# ---------------------------------------------------------------------------
# Phase 3: VoiceEEGAutoencoder
# ---------------------------------------------------------------------------

class VoiceEEGAutoencoder:
    """PyTorch autoencoder: 90-dim voice features -> 32-dim latent (8 bands x 4).

    Latent space structured as 8 bands:
      delta(0:4), theta(4:8), alpha(8:12), beta(12:16),
      gamma(16:20), resistance(20:24), coherence(24:28), signature(28:32)

    Uses LayerNorm + GELU + Dropout(0.1) + Tanh output bounding.
    """

    def __init__(self):
        self._model = None
        self._trained = False
        self._torch = None
        try:
            import torch
            import torch.nn as nn
            self._torch = torch

            class Autoencoder(nn.Module):
                def __init__(self_inner):
                    super().__init__()
                    self_inner.encoder = nn.Sequential(
                        nn.Linear(FEATURE_DIM, HIDDEN_DIM),
                        nn.LayerNorm(HIDDEN_DIM),
                        nn.GELU(),
                        nn.Dropout(0.1),
                        nn.Linear(HIDDEN_DIM, LATENT_DIM),
                        nn.Tanh(),
                    )
                    self_inner.decoder = nn.Sequential(
                        nn.Linear(LATENT_DIM, HIDDEN_DIM),
                        nn.LayerNorm(HIDDEN_DIM),
                        nn.GELU(),
                        nn.Dropout(0.1),
                        nn.Linear(HIDDEN_DIM, FEATURE_DIM),
                    )

                def encode(self_inner, x):
                    return self_inner.encoder(x)

                def decode(self_inner, z):
                    return self_inner.decoder(z)

                def forward(self_inner, x):
                    z = self_inner.encode(x)
                    return self_inner.decode(z), z

            self._model = Autoencoder()
            self._model.eval()
            logger.info("VoiceEEGAutoencoder initialized (untrained)")
        except ImportError:
            logger.warning("torch not available — autoencoder disabled, heuristic mode only")

    @property
    def is_trained(self) -> bool:
        return self._trained

    def load_weights(self, weights_path: str) -> bool:
        """Load pre-trained weights from file."""
        if self._model is None or self._torch is None:
            return False
        try:
            state = self._torch.load(weights_path, map_location="cpu", weights_only=True)
            self._model.load_state_dict(state)
            self._model.eval()
            self._trained = True
            logger.info("Autoencoder weights loaded from %s", weights_path)
            return True
        except Exception as e:
            logger.warning("Failed to load autoencoder weights: %s", e)
            return False

    def load_weights_from_bytes(self, data: bytes) -> bool:
        """Load weights from bytes (e.g., from R2)."""
        if self._model is None or self._torch is None:
            return False
        try:
            buf = io.BytesIO(data)
            state = self._torch.load(buf, map_location="cpu", weights_only=True)
            self._model.load_state_dict(state)
            self._model.eval()
            self._trained = True
            return True
        except Exception as e:
            logger.warning("Failed to load autoencoder weights from bytes: %s", e)
            return False

    def encode(self, feature_vector: np.ndarray) -> Optional[np.ndarray]:
        """Encode a 90-dim feature vector to 32-dim latent space.

        Falls back to deterministic projection when the autoencoder
        hasn't been trained yet so the fingerprint / trajectory always
        accumulate samples from day one.
        """
        if self._model is not None and self._torch is not None and self._trained:
            try:
                with self._torch.no_grad():
                    x = self._torch.tensor(feature_vector, dtype=self._torch.float32).unsqueeze(0)
                    z = self._model.encode(x)
                    return z.squeeze(0).numpy()
            except Exception as e:
                logger.debug("Autoencoder encode failed: %s", e)

        # Deterministic projection fallback: average non-overlapping
        # windows of the 90-dim feature into LATENT_DIM (32) values so
        # that the fingerprint can accumulate from the first call.
        try:
            fv = np.asarray(feature_vector, dtype=np.float32)
            if fv.size < LATENT_DIM:
                fv = np.pad(fv, (0, LATENT_DIM - fv.size))
            stride = fv.size // LATENT_DIM
            latent = np.array(
                [fv[i * stride:(i + 1) * stride].mean() for i in range(LATENT_DIM)],
                dtype=np.float32,
            )
            return latent
        except Exception:
            return None

    def train_on_batch(
        self,
        feature_vectors: List[np.ndarray],
        epochs: int = 100,
        lr: float = 1e-3,
    ) -> float:
        """Train the autoencoder on accumulated feature vectors. Returns final loss."""
        if self._model is None or self._torch is None:
            return float("inf")

        self._model.train()
        data = self._torch.tensor(np.stack(feature_vectors), dtype=self._torch.float32)
        optimizer = self._torch.optim.Adam(self._model.parameters(), lr=lr)
        loss_fn = self._torch.nn.MSELoss()

        final_loss = float("inf")
        for epoch in range(epochs):
            optimizer.zero_grad()
            recon, _ = self._model(data)
            loss = loss_fn(recon, data)
            loss.backward()
            optimizer.step()
            final_loss = loss.item()

        self._model.eval()
        self._trained = True
        logger.info("Autoencoder trained: %d samples, %d epochs, loss=%.6f", len(feature_vectors), epochs, final_loss)
        return final_loss

    def bootstrap_heuristic(self, n_samples: int = 500, epochs: int = 50) -> float:
        """QUANTUM-CRYSTAL-ARCH: Pre-train with synthetic voice features.

        Generates samples spanning realistic voice parameter ranges so the
        autoencoder learns a meaningful latent manifold before any real data
        arrives.  Returns final reconstruction loss.
        """
        if self._model is None or self._torch is None:
            return float("inf")
        if self._trained:
            return 0.0

        rng = np.random.default_rng(42)
        synthetic = np.zeros((n_samples, FEATURE_DIM), dtype=np.float32)

        for i in range(n_samples):
            pitch_mean = rng.normal(180.0, 60.0)
            pitch_var = rng.exponential(500.0)
            energy = rng.uniform(0.05, 0.35)
            speech_rate = rng.normal(3.5, 1.0)
            pause_ratio = rng.uniform(0.1, 0.5)

            base = np.array([pitch_mean, pitch_var, energy, speech_rate, pause_ratio], dtype=np.float32)
            base_normed = (base - base.mean()) / (base.std() + 1e-8)

            vec = rng.normal(0, 0.3, FEATURE_DIM).astype(np.float32)
            vec[:len(base_normed)] = base_normed
            synthetic[i] = vec

        loss = self.train_on_batch([synthetic[i] for i in range(n_samples)], epochs=epochs, lr=1e-3)
        logger.info("VoiceEEGAutoencoder bootstrap: %d synthetic samples, loss=%.6f", n_samples, loss)
        return loss

    def save_weights(self) -> Optional[bytes]:
        """Save model weights to bytes."""
        if self._model is None or self._torch is None:
            return None
        try:
            buf = io.BytesIO()
            self._torch.save(self._model.state_dict(), buf)
            return buf.getvalue()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Phase 4: NeuralFingerprint
# ---------------------------------------------------------------------------

@dataclass
class DeviationResult:
    """Result of comparing a latent vector against a client's fingerprint."""
    mahalanobis_distance: float = 0.0
    cluster_id: int = -1
    band_deviations: Dict[str, float] = field(default_factory=dict)
    closest_emotion: str = ""
    nevedal_factors: Dict[str, float] = field(default_factory=dict)
    dominant_band: str = ""


class NeuralFingerprint:
    """Per-client statistical model of latent voice vectors.

    After 50+ samples: computes mean, covariance, fits GMM with 6 clusters.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._samples: List[np.ndarray] = []
        self._mean: Optional[np.ndarray] = None
        self._cov: Optional[np.ndarray] = None
        self._gmm = None
        self._calibrated = False
        self._emotional_baselines: Dict[str, np.ndarray] = {}

    @property
    def n_samples(self) -> int:
        return len(self._samples)

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    def add_sample(self, latent: np.ndarray) -> None:
        self._samples.append(latent.copy())
        if len(self._samples) >= MIN_FINGERPRINT_SAMPLES and not self._calibrated:
            self._recalibrate()

    def _recalibrate(self) -> None:
        data = np.stack(self._samples)
        self._mean = np.mean(data, axis=0)
        self._cov = np.cov(data.T)
        if np.linalg.matrix_rank(self._cov) < LATENT_DIM:
            self._cov += np.eye(LATENT_DIM) * 1e-6

        try:
            from sklearn.mixture import GaussianMixture
            n_components = min(6, len(self._samples) // 10)
            if n_components >= 2:
                self._gmm = GaussianMixture(
                    n_components=n_components,
                    covariance_type="full",
                    random_state=42,
                )
                self._gmm.fit(data)
        except ImportError:
            logger.warning("scikit-learn not available — GMM disabled")
        except Exception as e:
            logger.warning("GMM fitting failed: %s", e)

        self._calibrated = True
        logger.info("NeuralFingerprint calibrated for %s: %d samples", self.user_id, len(self._samples))

    def set_emotional_baseline(self, emotion: str, latent: np.ndarray) -> None:
        self._emotional_baselines[emotion] = latent.copy()

    def compute_deviation(self, latent: np.ndarray) -> DeviationResult:
        """Compute deviation from baseline fingerprint."""
        result = DeviationResult()

        if self._mean is None:
            return result

        diff = latent - self._mean

        # Band deviations
        for i, band_name in enumerate(BAND_NAMES):
            start = i * BAND_SIZE
            end = start + BAND_SIZE
            band_diff = diff[start:end]
            result.band_deviations[band_name] = float(np.mean(np.abs(band_diff)))

        # Dominant band
        if result.band_deviations:
            result.dominant_band = max(result.band_deviations, key=result.band_deviations.get)

        # Mahalanobis distance
        try:
            cov_inv = np.linalg.inv(self._cov)
            md = float(np.sqrt(diff @ cov_inv @ diff))
            result.mahalanobis_distance = md
        except Exception:
            result.mahalanobis_distance = float(np.linalg.norm(diff))

        # GMM cluster
        if self._gmm is not None:
            try:
                result.cluster_id = int(self._gmm.predict(latent.reshape(1, -1))[0])
            except Exception:
                pass

        # Closest emotion
        if self._emotional_baselines:
            min_dist = float("inf")
            for emotion, baseline in self._emotional_baselines.items():
                dist = float(np.linalg.norm(latent - baseline))
                if dist < min_dist:
                    min_dist = dist
                    result.closest_emotion = emotion

        # Nevedal factors from latent
        interp = VirtualEEGInterpreter()
        result.nevedal_factors = interp.compute_nevedal_factors(latent)

        return result

    def compare_sessions(
        self,
        session_a_latents: List[np.ndarray],
        session_b_latents: List[np.ndarray],
    ) -> Dict[str, Any]:
        """Compare two sessions' latent vectors."""
        if not session_a_latents or not session_b_latents:
            return {}

        mean_a = np.mean(np.stack(session_a_latents), axis=0)
        mean_b = np.mean(np.stack(session_b_latents), axis=0)
        diff = mean_b - mean_a

        band_changes = {}
        for i, band_name in enumerate(BAND_NAMES):
            start = i * BAND_SIZE
            end = start + BAND_SIZE
            band_changes[band_name] = float(np.mean(diff[start:end]))

        interp = VirtualEEGInterpreter()
        ec_a = interp.compute_nevedal_factors(mean_a).get("EC", 0.0)
        ec_b = interp.compute_nevedal_factors(mean_b).get("EC", 0.0)

        return {
            "overall_shift": float(np.linalg.norm(diff)),
            "band_changes": band_changes,
            "ec_change": ec_b - ec_a,
            "ec_a": ec_a,
            "ec_b": ec_b,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "n_samples": self.n_samples,
            "calibrated": self._calibrated,
            "mean_vector": self._mean.tolist() if self._mean is not None else None,
            "covariance": self._cov.tolist() if self._cov is not None else None,
            "emotional_baselines": {
                k: v.tolist() for k, v in self._emotional_baselines.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NeuralFingerprint":
        fp = cls(user_id=data.get("user_id", ""))
        if data.get("mean_vector"):
            fp._mean = np.array(data["mean_vector"], dtype=np.float32)
        if data.get("covariance"):
            fp._cov = np.array(data["covariance"], dtype=np.float32)
        fp._calibrated = data.get("calibrated", False)
        for emotion, vec in (data.get("emotional_baselines") or {}).items():
            fp._emotional_baselines[emotion] = np.array(vec, dtype=np.float32)
        return fp


# ---------------------------------------------------------------------------
# Phase 5: NeuralMirror (Co-regulation Engine)
# ---------------------------------------------------------------------------

@dataclass
class MirrorState:
    """Current co-regulation state output."""
    technique_weights: Dict[str, float] = field(default_factory=dict)
    backchannel_register: str = "warm"
    response_pacing: str = "normal"
    prompt_injection: str = ""
    heartbeat_interval_ms: int = 1000
    dominant_band: str = ""
    band_energies: Dict[str, float] = field(default_factory=dict)


class NeuralMirror:
    """Co-regulation engine: adjusts Little Nate's therapeutic approach
    based on the client's neural mirror (virtual EEG) state.

    Operates in two modes:
    - Heuristic mode: uses raw voice features for approximate EEG mapping (day-1)
    - Autoencoder mode: uses trained 32-dim latent for precise mapping
    """

    def __init__(self):
        self._current_state = MirrorState()
        self._autoencoder_trained = False
        self._last_features: Optional[VoiceFeatureVector] = None
        self._session_pitch_samples: List[float] = []
        self._session_rate_samples: List[float] = []
        self._session_energy_samples: List[float] = []
        self._session_jitter_samples: List[float] = []
        self._session_pause_samples: List[float] = []
        self._session_pitch_var_samples: List[float] = []

    def set_autoencoder_trained(self, trained: bool) -> None:
        self._autoencoder_trained = trained

    def update_from_features(self, features: VoiceFeatureVector) -> MirrorState:
        """Update mirror state from raw voice features (heuristic mode)."""
        self._last_features = features

        # Accumulate session statistics
        if features.pitch_mean > 0:
            self._session_pitch_samples.append(features.pitch_mean)
        if features.speech_rate > 0:
            self._session_rate_samples.append(features.speech_rate)
        self._session_energy_samples.append(features.energy_mean)
        self._session_jitter_samples.append(features.jitter)
        self._session_pause_samples.append(features.pause_ratio)
        self._session_pitch_var_samples.append(features.pitch_variance)

        if not self._autoencoder_trained:
            self._heuristic_mode(features)
        return self._current_state

    def update_from_deviation(self, deviation: DeviationResult) -> MirrorState:
        """Update mirror state from autoencoder-derived deviation metrics."""
        self._current_state.dominant_band = deviation.dominant_band
        self._current_state.band_energies = deviation.band_deviations

        self._compute_technique_weights(deviation.band_deviations)
        self._compute_backchannel_register(deviation.dominant_band)
        self._compute_response_pacing(deviation.dominant_band)
        self._compute_heartbeat(deviation.dominant_band)
        self._compute_prompt_injection(deviation)

        return self._current_state

    def _heuristic_mode(self, f: VoiceFeatureVector) -> None:
        """Approximate EEG bands from raw voice features."""
        bands: Dict[str, float] = {b: 0.0 for b in BAND_NAMES}

        # Pitch below session average -> elevated theta
        if self._session_pitch_samples:
            pitch_avg = np.mean(self._session_pitch_samples)
            if f.pitch_mean > 0 and f.pitch_mean < pitch_avg:
                bands["theta"] = min(1.0, (pitch_avg - f.pitch_mean) / max(pitch_avg, 1) * 2)

        # Speech rate acceleration -> elevated beta
        if self._session_rate_samples and len(self._session_rate_samples) > 2:
            rate_avg = np.mean(self._session_rate_samples)
            if f.speech_rate > rate_avg * HEURISTIC_RATE_FACTOR:
                bands["beta"] = min(1.0, (f.speech_rate / max(rate_avg, 0.1) - 1.0))

        # Energy drop -> elevated delta
        if self._session_energy_samples:
            energy_peak = max(self._session_energy_samples)
            if energy_peak > 0 and f.energy_mean < energy_peak * HEURISTIC_ENERGY_FACTOR:
                bands["delta"] = min(1.0, 1.0 - f.energy_mean / max(energy_peak, 0.01))

        # Jitter/shimmer spikes -> elevated resistance
        if self._session_jitter_samples and len(self._session_jitter_samples) > 2:
            jitter_avg = np.mean(self._session_jitter_samples[:-1])  # exclude current
            if jitter_avg > 0 and f.jitter > jitter_avg * HEURISTIC_JITTER_FACTOR:
                bands["resistance"] = min(1.0, f.jitter / max(jitter_avg, 0.001) - 1.0)

        # Pause ratio increase -> elevated alpha
        if self._session_pause_samples and len(self._session_pause_samples) > 2:
            pause_avg = np.mean(self._session_pause_samples[:-1])
            if pause_avg > 0 and f.pause_ratio > pause_avg * HEURISTIC_PAUSE_FACTOR:
                bands["alpha"] = min(1.0, f.pause_ratio / max(pause_avg, 0.01) - 1.0)

        # Pitch variance increase -> elevated gamma
        if self._session_pitch_var_samples and len(self._session_pitch_var_samples) > 2:
            pv_avg = np.mean(self._session_pitch_var_samples[:-1])
            if pv_avg > 0 and f.pitch_variance > pv_avg * HEURISTIC_PITCH_VAR_FACTOR:
                bands["gamma"] = min(1.0, f.pitch_variance / max(pv_avg, 0.1) - 1.0)

        bands["coherence"] = max(0.0, 1.0 - f.emotional_volatility * 5)
        bands["signature"] = f.voiced_ratio

        self._current_state.band_energies = bands
        dominant = max(bands, key=bands.get) if bands else "alpha"
        self._current_state.dominant_band = dominant

        self._compute_technique_weights(bands)
        self._compute_backchannel_register(dominant)
        self._compute_response_pacing(dominant)
        self._compute_heartbeat(dominant)
        self._compute_prompt_injection_heuristic(bands, dominant)

    def _compute_technique_weights(self, bands: Dict[str, float]) -> None:
        r = bands.get("resistance", 0.0)
        th = bands.get("theta", 0.0)
        d = bands.get("delta", 0.0)
        b = bands.get("beta", 0.0)

        self._current_state.technique_weights = {
            "IFS": min(1.0, r * 0.6 + 0.2),
            "AEDP": min(1.0, th * 0.6 + 0.2),
            "Polyvagal": min(1.0, (d + r) * 0.4 + 0.1),
            "EFT": min(1.0, (th + b) * 0.4 + 0.1),
        }

    def _compute_backchannel_register(self, dominant: str) -> None:
        mapping = {
            "delta": "empathic",
            "theta": "empathic",
            "alpha": "warm",
            "beta": "neutral",
            "gamma": "validating",
            "resistance": "empathic",
            "coherence": "warm",
            "signature": "neutral",
        }
        self._current_state.backchannel_register = mapping.get(dominant, "warm")

    def _compute_response_pacing(self, dominant: str) -> None:
        mapping = {
            "delta": "very_slow",
            "theta": "slow",
            "alpha": "measured",
            "beta": "normal",
            "gamma": "responsive",
            "resistance": "slow",
            "coherence": "measured",
            "signature": "normal",
        }
        self._current_state.response_pacing = mapping.get(dominant, "normal")

    def _compute_heartbeat(self, dominant: str) -> None:
        mapping = {
            "delta": 2000,
            "theta": 1500,
            "alpha": 1000,
            "beta": 800,
            "gamma": 500,
            "resistance": 1500,
            "coherence": 1000,
            "signature": 1000,
        }
        self._current_state.heartbeat_interval_ms = mapping.get(dominant, 1000)

    def _compute_prompt_injection(self, deviation: DeviationResult) -> None:
        dom = deviation.dominant_band
        lines = []

        band_descriptions = {
            "delta": "deep withdrawal or dissociation",
            "theta": "deep emotional processing",
            "alpha": "reflective, contemplative processing",
            "beta": "cognitive activation, possibly anxious",
            "gamma": "emotional breakthrough or heightened insight",
            "resistance": "vocal tension, guardedness",
            "coherence": "integrated, balanced emotional state",
            "signature": "stable personal vocal pattern",
        }

        pacing = {
            "delta": "Speak very slowly and gently.",
            "theta": "Speak slowly. Use experiential language.",
            "alpha": "Match their reflective pace.",
            "beta": "Ground them with steady, calm responses.",
            "gamma": "Follow their energy. Validate the breakthrough.",
            "resistance": "Be gentle. Don't push. Name what you notice.",
        }

        desc = band_descriptions.get(dom, "")
        pace = pacing.get(dom, "")

        if desc:
            lines.append(f"[Neural Mirror] The client is in {desc}.")
        if pace:
            lines.append(pace)

        if deviation.closest_emotion:
            lines.append(f"Detected emotional state: {deviation.closest_emotion}.")

        self._current_state.prompt_injection = " ".join(lines)

    def _compute_prompt_injection_heuristic(self, bands: Dict[str, float], dominant: str) -> None:
        lines = []

        desc_map = {
            "delta": "withdrawal or low energy",
            "theta": "deep emotional processing",
            "alpha": "reflective processing",
            "beta": "cognitive activation or anxiety",
            "gamma": "emotional breakthrough",
            "resistance": "vocal tension or guardedness",
        }

        pace_map = {
            "delta": "Speak very slowly and gently.",
            "theta": "Speak slowly. Use experiential language.",
            "alpha": "Match their reflective pace.",
            "beta": "Ground them with steady, calm responses.",
            "gamma": "Follow their energy. Validate the breakthrough.",
            "resistance": "Be gentle. Don't push.",
        }

        desc = desc_map.get(dominant, "")
        pace = pace_map.get(dominant, "")

        if desc:
            lines.append(f"[Neural Mirror - heuristic] The client shows signs of {desc}.")
        if pace:
            lines.append(pace)

        elevated = [b for b, v in bands.items() if v > 0.5 and b != dominant]
        if elevated:
            lines.append(f"Also elevated: {', '.join(elevated)}.")

        self._current_state.prompt_injection = " ".join(lines)

    def get_prompt_injection(self) -> str:
        return self._current_state.prompt_injection

    def get_technique_weights(self) -> Dict[str, float]:
        return self._current_state.technique_weights

    def get_backchannel_bias(self) -> Optional[str]:
        return self._current_state.backchannel_register

    def get_response_pacing(self) -> str:
        return self._current_state.response_pacing

    def get_state(self) -> MirrorState:
        return self._current_state

    def reset(self) -> None:
        self._current_state = MirrorState()
        self._session_pitch_samples.clear()
        self._session_rate_samples.clear()
        self._session_energy_samples.clear()
        self._session_jitter_samples.clear()
        self._session_pause_samples.clear()
        self._session_pitch_var_samples.clear()


# ---------------------------------------------------------------------------
# Phase 6: VirtualEEGInterpreter
# ---------------------------------------------------------------------------

class VirtualEEGInterpreter:
    """Interprets 32-dim latent vector as band energies, maps to Nevedal factors.

    A = (alpha + beta) / 2
    Aw = (theta + gamma) / 2
    I = (gamma + coherence) / 2
    R = max(0.01, resistance + (1 - alpha) * 0.5)
    EC = (A * Aw * I) / R
    """

    def extract_band_energies(self, latent: np.ndarray) -> Dict[str, float]:
        energies = {}
        for i, band_name in enumerate(BAND_NAMES):
            start = i * BAND_SIZE
            end = start + BAND_SIZE
            band = latent[start:end]
            energies[band_name] = float(np.mean(np.abs(band)))
        return energies

    def compute_nevedal_factors(self, latent: np.ndarray) -> Dict[str, float]:
        bands = self.extract_band_energies(latent)

        alpha = bands.get("alpha", 0.0)
        beta = bands.get("beta", 0.0)
        theta = bands.get("theta", 0.0)
        gamma = bands.get("gamma", 0.0)
        coherence = bands.get("coherence", 0.0)
        resistance = bands.get("resistance", 0.0)

        A = (alpha + beta) / 2
        Aw = (theta + gamma) / 2
        I = (gamma + coherence) / 2
        R = max(0.01, resistance + (1 - alpha) * 0.5)
        EC = (A * Aw * I) / R

        return {
            "A": round(A, 4),
            "Aw": round(Aw, 4),
            "I": round(I, 4),
            "R": round(R, 4),
            "EC": round(EC, 4),
            "band_energies": bands,
        }


# ---------------------------------------------------------------------------
# Phase 7: Crystal EEG Context
# ---------------------------------------------------------------------------

def build_crystal_eeg_context(
    latent: np.ndarray,
    deviation: Optional[DeviationResult] = None,
) -> Dict[str, Any]:
    """Build EEG context metadata for crystal storage."""
    interp = VirtualEEGInterpreter()
    factors = interp.compute_nevedal_factors(latent)
    bands = interp.extract_band_energies(latent)

    dominant = max(bands, key=bands.get) if bands else ""

    context = {
        "latent_vector": latent.tolist(),
        "band_energies": bands,
        "dominant_band": dominant,
        "nevedal_factors": factors,
    }

    if deviation:
        context["band_deviations"] = deviation.band_deviations
        context["closest_emotion"] = deviation.closest_emotion
        context["mahalanobis_distance"] = deviation.mahalanobis_distance

    return context


# ---------------------------------------------------------------------------
# Phase 8: Cross-Session Trajectory Analysis
# ---------------------------------------------------------------------------

class SessionTrajectoryAnalyzer:
    """Analyzes latent vector trajectories within and across sessions.

    Detects tunneling events (sudden resistance drop + gamma rise)
    and tracks long-term therapeutic progression.
    """

    def __init__(self):
        self._current_latents: List[Tuple[float, np.ndarray]] = []
        self._tunneling_events: List[Dict[str, Any]] = []

    def add_latent(self, timestamp: float, latent: np.ndarray) -> None:
        self._current_latents.append((timestamp, latent.copy()))

    def detect_tunneling(self) -> Optional[Dict[str, Any]]:
        """Check for tunneling events in the current session.

        A tunneling event is detected when:
        - Resistance drops by > TUNNEL_RESISTANCE_DROP (0.5) in a 30s window
        - AND gamma rises by > TUNNEL_GAMMA_RISE (0.4) in the same window
        - AND alpha and beta remain below TUNNEL_INTERMEDIATE_CAP (0.3)
        """
        if len(self._current_latents) < 2:
            return None

        interp = VirtualEEGInterpreter()
        now_ts, now_latent = self._current_latents[-1]
        now_bands = interp.extract_band_energies(now_latent)

        for ts, latent in reversed(self._current_latents[:-1]):
            if now_ts - ts > TUNNEL_WINDOW_SECONDS:
                break

            then_bands = interp.extract_band_energies(latent)

            resistance_drop = then_bands.get("resistance", 0) - now_bands.get("resistance", 0)
            gamma_rise = now_bands.get("gamma", 0) - then_bands.get("gamma", 0)
            alpha_ok = now_bands.get("alpha", 0) < TUNNEL_INTERMEDIATE_CAP
            beta_ok = now_bands.get("beta", 0) < TUNNEL_INTERMEDIATE_CAP

            if (resistance_drop >= TUNNEL_RESISTANCE_DROP
                    and gamma_rise >= TUNNEL_GAMMA_RISE
                    and alpha_ok and beta_ok):
                event = {
                    "type": "tunneling",
                    "timestamp": now_ts,
                    "window_start": ts,
                    "resistance_drop": resistance_drop,
                    "gamma_rise": gamma_rise,
                    "alpha": now_bands.get("alpha", 0),
                    "beta": now_bands.get("beta", 0),
                }
                self._tunneling_events.append(event)
                logger.info(
                    "TUNNELING EVENT detected: resistance -%.2f, gamma +%.2f (window=%.1fs)",
                    resistance_drop, gamma_rise, now_ts - ts,
                )
                return event

        return None

    def get_session_summary(self) -> Dict[str, Any]:
        if not self._current_latents:
            return {}

        interp = VirtualEEGInterpreter()
        all_latents = [l for _, l in self._current_latents]
        mean_latent = np.mean(np.stack(all_latents), axis=0)
        factors = interp.compute_nevedal_factors(mean_latent)

        return {
            "n_samples": len(self._current_latents),
            "mean_nevedal_factors": factors,
            "tunneling_events": self._tunneling_events,
            "duration_s": (self._current_latents[-1][0] - self._current_latents[0][0])
            if len(self._current_latents) > 1
            else 0.0,
        }

    def reset(self) -> None:
        self._current_latents.clear()
        self._tunneling_events.clear()


# ---------------------------------------------------------------------------
# Prompt Injection Budget Allocator
# ---------------------------------------------------------------------------

class ContextBudgetAllocator:
    """Enforces the 900-token total injection budget across 4 sources.

    Priority order (first survives truncation):
    1. Crystal context (max 300 tokens)
    2. Neural Mirror context (max 200 tokens)
    3. Helix injection (max 200 tokens)
    4. User memory context (max 200 tokens)
    """

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return len(text.split()) * 4 // 3 + 1

    @staticmethod
    def _truncate_to_tokens(text: str, max_tokens: int) -> str:
        words = text.split()
        approx_word_count = max_tokens * 3 // 4
        if len(words) <= approx_word_count:
            return text
        return " ".join(words[:approx_word_count]) + "..."

    def allocate(
        self,
        crystal_context: str = "",
        neural_mirror_context: str = "",
        helix_injection: str = "",
        user_memory_context: str = "",
    ) -> Dict[str, str]:
        return {
            "crystal_context": self._truncate_to_tokens(crystal_context, CRYSTAL_CONTEXT_BUDGET),
            "neural_mirror_context": self._truncate_to_tokens(neural_mirror_context, NEURAL_MIRROR_BUDGET),
            "helix_injection": self._truncate_to_tokens(helix_injection, HELIX_INJECTION_BUDGET),
            "user_memory_context": self._truncate_to_tokens(user_memory_context, USER_MEMORY_BUDGET),
        }


# ---------------------------------------------------------------------------
# Top-level session helper
# ---------------------------------------------------------------------------

class NeuralMirrorSession:
    """Convenience wrapper that orchestrates all phases for a single voice session.

    Initialize once per call. Feed audio chunks. Get prompt injection + state.
    """

    def __init__(self, user_id: str, session_id: str, sample_rate: int = 8000):
        self.user_id = user_id
        self.session_id = session_id

        self.feature_extractor = VoiceFeatureExtractor(sample_rate=sample_rate)
        self.baseline_capturer = EmotionalBaselineCapturer(sample_rate=sample_rate)
        self.autoencoder = VoiceEEGAutoencoder()
        self.fingerprint = NeuralFingerprint(user_id)
        self.mirror = NeuralMirror()
        self.trajectory = SessionTrajectoryAnalyzer()
        self.budget_allocator = ContextBudgetAllocator()

        self._audio_accumulator: List[bytes] = []
        self._accumulated_bytes = 0
        self._process_interval_bytes = sample_rate * 2  # ~1 second of 16-bit mono
        self._last_process_time = 0.0

    def load_fingerprint(self, data: Dict[str, Any]) -> None:
        self.fingerprint = NeuralFingerprint.from_dict(data)

    def load_autoencoder_weights(self, data: bytes) -> bool:
        success = self.autoencoder.load_weights_from_bytes(data)
        if success:
            self.mirror.set_autoencoder_trained(True)
        return success

    def on_audio_chunk(self, chunk: bytes) -> Optional[MirrorState]:
        """Feed an audio chunk. Returns MirrorState if processing triggered."""
        self.baseline_capturer.add_audio(chunk)
        self._audio_accumulator.append(chunk)
        self._accumulated_bytes += len(chunk)

        if self._accumulated_bytes < self._process_interval_bytes:
            return None

        audio_segment = b"".join(self._audio_accumulator)
        self._audio_accumulator.clear()
        self._accumulated_bytes = 0

        return self.process_segment(audio_segment)

    def process_segment(self, audio_bytes: bytes) -> MirrorState:
        """Process an audio segment through the full mirror pipeline."""
        features = self.feature_extractor.extract(audio_bytes)
        now = time.time()

        # Always update mirror from features (heuristic mode from day 1)
        state = self.mirror.update_from_features(features)

        # If autoencoder is trained, also run the full latent path
        feature_vec = features.to_vector()
        latent = self.autoencoder.encode(feature_vec)

        if latent is not None:
            self.fingerprint.add_sample(latent)
            self.trajectory.add_latent(now, latent)

            if self.fingerprint.calibrated:
                deviation = self.fingerprint.compute_deviation(latent)
                state = self.mirror.update_from_deviation(deviation)
                self.trajectory.detect_tunneling()

        # Check for baseline capture
        self.baseline_capturer.check_and_capture(
            features, self.user_id, self.session_id,
        )

        self._last_process_time = now
        return state

    def get_prompt_injection(self) -> str:
        return self.mirror.get_prompt_injection()

    def get_technique_weights(self) -> Dict[str, float]:
        return self.mirror.get_technique_weights()

    def get_backchannel_bias(self) -> Optional[str]:
        return self.mirror.get_backchannel_bias()

    def get_crystal_eeg_context(self) -> Dict[str, Any]:
        """Get EEG context for crystal storage."""
        if not self.trajectory._current_latents:
            return {}
        _, latest_latent = self.trajectory._current_latents[-1]
        deviation = None
        if self.fingerprint.calibrated:
            deviation = self.fingerprint.compute_deviation(latest_latent)
        return build_crystal_eeg_context(latest_latent, deviation)

    def finalize(self) -> Dict[str, Any]:
        """Finalize session and return summary data for storage."""
        summary = self.trajectory.get_session_summary()
        summary["fingerprint"] = self.fingerprint.to_dict()
        summary["mirror_final_state"] = {
            "dominant_band": self.mirror._current_state.dominant_band,
            "technique_weights": self.mirror._current_state.technique_weights,
            "band_energies": self.mirror._current_state.band_energies,
        }
        return summary
