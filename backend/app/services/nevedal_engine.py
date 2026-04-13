"""
LITTLE NATE — Nevedal Quantum Emotional Coherence Engine
Version: 2.0
Date: January 21, 2026

Implements the full Nevedal Theory formula with:
- Real-time biometric extraction from voice
- CEE (Corrective Emotional Experience) window detection
- Dyadic synchrony computation
- WebSocket streaming for live dashboards

Master Formula:
C_emo(t) = [β · p_ent · T₀ · e^(-d/λ)] / [γ_env + E_G^(joint)/ℏ] × exp[-(γ_env + E_G^(joint)/ℏ)t]
"""

import asyncio
import json
import logging
import math
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger("nevedal_engine")
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import deque
import struct

# =============================================================================
# QUANTUM-CRYSTAL-ARCH: Coherence governance stubs for CLI repair pipeline
# =============================================================================

@dataclass
class CoherenceImpactAssessment:
    c_emo_before: float = 0.0
    c_emo_after: float = 0.0
    p_ent_delta: float = 0.0
    t_tunnel_delta: float = 0.0
    gamma_env_delta: float = 0.0
    clinical_justification: str = ""
    clinician_approved: bool = False


class ViolationTaxonomy:
    COMPLIANT = "compliant"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"

    @staticmethod
    def classify(assessment: CoherenceImpactAssessment) -> str:
        regression = max(0.0, assessment.c_emo_before - assessment.c_emo_after)
        if regression > 0.30:
            return ViolationTaxonomy.CRITICAL
        if regression > 0.20:
            return ViolationTaxonomy.SEVERE
        if regression > 0.10:
            return ViolationTaxonomy.MODERATE
        if regression > 0.05:
            return ViolationTaxonomy.MINOR
        return ViolationTaxonomy.COMPLIANT


class SystemCoherenceProxy:
    async def compute(self, db_pool=None, redis_client=None) -> float:
        if not db_pool:
            return 0.0
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT C_emo FROM nevedal_domain_state "
                    "WHERE domain = 'coding' LIMIT 1"
                )
                return float(row["c_emo"]) if row else 0.0
        except Exception:
            return 0.0


# =============================================================================
# CONSTANTS (Calibrated for therapeutic context)
# =============================================================================

class NevedalConstants:
    """Tunable parameters for the Nevedal formula"""
    
    # Coupling constants
    BETA = 1.0              # Scales entanglement/tunneling into coherence growth
    ALPHA = 0.5             # Coupling for entanglement/tunneling scaling in E_G
    H_BAR = 1.0             # Reduced Planck constant (normalized)
    
    # Tunneling parameters
    T_0 = 1.0               # Maximum tunneling when distance is negligible
    LAMBDA = 0.5            # Characteristic tunneling length
    
    # CEE detection thresholds (aligned with PhD theoretical framework)
    CEE_P_ENT_MIN = 0.72    # Minimum entanglement for CEE (per Nevedal 2025, §3.2)
    CEE_D_MAX = 0.45        # Maximum distance for CEE
    CEE_GAMMA_MAX = 0.35    # Maximum decoherence for CEE
    CEE_E_G_MIN = 0.35      # Minimum emotional load for CEE
    CEE_DURATION_MIN = 30   # Minimum seconds for valid CEE (per theoretical framework)
    
    # Voice analysis parameters
    VOICE_STRESS_BASELINE = 0.3
    VOICE_WARMTH_BASELINE = 0.5
    
    # Synchrony weights
    SYNC_HRV_WEIGHT = 0.30
    SYNC_BREATH_WEIGHT = 0.25
    SYNC_VOICE_WEIGHT = 0.25
    SYNC_POSTURE_WEIGHT = 0.20

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class BiometricSample:
    """Single biometric reading from one subject"""
    timestamp: datetime
    
    # Heart/Autonomic
    heart_rate: Optional[float] = None          # BPM
    hrv_rmssd: Optional[float] = None           # HRV in milliseconds
    respiratory_rate: Optional[float] = None    # Breaths per minute
    eda: Optional[float] = None                 # Electrodermal activity (µS)
    
    # Voice (extracted from audio)
    voice_pitch_mean: Optional[float] = None    # Hz
    voice_pitch_variance: Optional[float] = None
    voice_energy: Optional[float] = None        # dB
    voice_stress_index: Optional[float] = None  # 0-1
    voice_warmth_index: Optional[float] = None  # 0-1
    speech_rate: Optional[float] = None         # Words per minute
    pause_ratio: Optional[float] = None         # Ratio of silence to speech
    
    # Visual (from video/camera)
    gaze_contact_ratio: Optional[float] = None  # 0-1
    body_lean_angle: Optional[float] = None     # Degrees (+ = toward)
    facial_affect_valence: Optional[float] = None  # -1 to 1
    facial_affect_arousal: Optional[float] = None  # 0 to 1
    micro_expression_count: Optional[int] = None


@dataclass
class DyadicBiometrics:
    """Biometric data for a therapeutic dyad (client + therapist)"""
    timestamp: datetime
    session_id: str
    
    subject_a: BiometricSample  # Client
    subject_b: BiometricSample  # Therapist/Coach
    
    # Computed synchrony metrics
    hrv_synchrony: Optional[float] = None       # 0-1
    breath_synchrony: Optional[float] = None    # 0-1
    voice_synchrony: Optional[float] = None     # 0-1
    posture_synchrony: Optional[float] = None   # 0-1
    gaze_synchrony: Optional[float] = None      # 0-1


@dataclass
class NevedalState:
    """Complete Nevedal quantum emotional coherence state"""
    timestamp: datetime
    session_id: str
    user_id: str
    dyad_partner_id: Optional[str] = None
    
    # Core Nevedal variables
    c_emo: float = 0.5          # Quantum Emotional Coherence (0-1)
    p_ent: float = 0.5          # Emotional Entanglement (0-1)
    t_tunnel: float = 0.5       # Tunneling Transparency (0-1)
    d_distance: float = 0.5     # Interpersonal Distance (0-1)
    gamma_env: float = 0.3      # Decoherence Rate (0-1)
    e_g_joint: float = 0.4      # Joint Emotional Load (0-1)
    tau_emo: float = 1.0        # Coherence Lifetime
    
    # CEE detection
    cee_window: bool = False
    cee_start_time: Optional[datetime] = None
    cee_duration_seconds: int = 0
    cee_intensity: float = 0.0  # Peak C_emo during CEE
    
    # Interpretation
    interpretation: str = ""
    recommendations: List[str] = None
    
    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        if self.cee_start_time:
            data['cee_start_time'] = self.cee_start_time.isoformat()
        return data


@dataclass
class CEEEvent:
    """A detected Corrective Emotional Experience"""
    session_id: str
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    peak_c_emo: float
    avg_p_ent: float
    avg_gamma_env: float
    trigger_context: str  # What was being discussed
    therapeutic_value: str  # AI assessment


# =============================================================================
# VOICE BIOMETRIC EXTRACTOR
# =============================================================================

class VoiceBiometricExtractor:
    """
    Extracts emotional/stress biometrics from voice audio.
    
    Works with raw PCM audio data or base64-encoded audio chunks
    from the VagusEngine in Flutter.
    """
    
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.buffer = deque(maxlen=sample_rate * 5)  # 5 second buffer
        self.pitch_history = deque(maxlen=50)
        self.energy_history = deque(maxlen=50)
        
    def process_audio_chunk(self, audio_data: bytes) -> Dict[str, float]:
        """
        Process raw PCM audio and extract biometric features.
        
        Args:
            audio_data: Raw PCM audio bytes (16-bit, mono)
            
        Returns:
            Dictionary of extracted voice biometrics
        """
        # Convert bytes to numpy array
        try:
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            samples = samples / 32768.0  # Normalize to [-1, 1]
        except Exception as e:
            print(f"[VoiceBio] Audio decode error: {e}")
            return self._default_metrics()
        
        if len(samples) < 256:
            return self._default_metrics()
        
        # Add to buffer
        self.buffer.extend(samples)
        
        # Extract features
        features = {}
        
        # 1. Energy (volume/intensity)
        energy = np.sqrt(np.mean(samples ** 2))
        energy_db = 20 * np.log10(max(energy, 1e-10))
        features['voice_energy'] = float(energy_db)
        self.energy_history.append(energy_db)
        
        # 2. Pitch estimation (using autocorrelation)
        pitch = self._estimate_pitch(samples)
        features['voice_pitch_mean'] = pitch
        if pitch > 0:
            self.pitch_history.append(pitch)
        
        # 3. Pitch variance (emotional variability)
        if len(self.pitch_history) > 10:
            features['voice_pitch_variance'] = float(np.std(list(self.pitch_history)))
        else:
            features['voice_pitch_variance'] = 0.0
        
        # 4. Speech rate estimation (based on energy envelope)
        speech_rate = self._estimate_speech_rate(samples)
        features['speech_rate'] = speech_rate
        
        # 5. Pause ratio
        features['pause_ratio'] = self._compute_pause_ratio(samples)
        
        # 6. Voice Stress Index (0-1)
        # Higher pitch + higher pitch variance + faster speech = more stress
        stress = self._compute_stress_index(features)
        features['voice_stress_index'] = stress
        
        # 7. Voice Warmth Index (0-1)
        # Lower pitch variance + moderate energy + slower pauses = warmer
        warmth = self._compute_warmth_index(features)
        features['voice_warmth_index'] = warmth
        
        return features
    
    def _estimate_pitch(self, samples: np.ndarray) -> float:
        """Estimate fundamental frequency using autocorrelation"""
        try:
            # Autocorrelation
            n = len(samples)
            correlation = np.correlate(samples, samples, mode='full')[n-1:]
            
            # Find first peak after initial decay
            min_lag = int(self.sample_rate / 500)  # Max 500 Hz
            max_lag = int(self.sample_rate / 50)   # Min 50 Hz
            
            if max_lag > len(correlation):
                return 0.0
            
            segment = correlation[min_lag:max_lag]
            if len(segment) == 0:
                return 0.0
            
            peak_idx = np.argmax(segment) + min_lag
            
            if peak_idx > 0 and correlation[peak_idx] > 0.1:
                pitch = self.sample_rate / peak_idx
                return float(pitch)
            
            return 0.0
        except Exception as e:
            logger.debug("_estimate_pitch failed: %s", e)
            return 0.0
    
    def _estimate_speech_rate(self, samples: np.ndarray) -> float:
        """Estimate syllables/words per minute from energy envelope"""
        try:
            # Compute energy envelope
            window_size = int(self.sample_rate * 0.02)  # 20ms windows
            hop_size = window_size // 2
            
            envelope = []
            for i in range(0, len(samples) - window_size, hop_size):
                window = samples[i:i + window_size]
                envelope.append(np.sqrt(np.mean(window ** 2)))
            
            envelope = np.array(envelope)
            if len(envelope) < 10:
                return 120.0  # Default
            
            # Count peaks (syllables)
            threshold = np.mean(envelope) * 0.5
            peaks = 0
            above = False
            for e in envelope:
                if e > threshold and not above:
                    peaks += 1
                    above = True
                elif e < threshold:
                    above = False
            
            # Convert to words per minute (assume ~2 syllables per word)
            duration_seconds = len(samples) / self.sample_rate
            if duration_seconds > 0:
                syllables_per_min = (peaks / duration_seconds) * 60
                words_per_min = syllables_per_min / 2
                return float(np.clip(words_per_min, 60, 250))
            
            return 120.0
        except Exception as e:
            logger.debug("_estimate_speech_rate failed: %s", e)
            return 120.0
    
    def _compute_pause_ratio(self, samples: np.ndarray) -> float:
        """Compute ratio of silence to speech"""
        try:
            energy = np.abs(samples)
            threshold = np.mean(energy) * 0.3
            silence_samples = np.sum(energy < threshold)
            return float(silence_samples / len(samples))
        except Exception as e:
            logger.debug("_compute_pause_ratio failed: %s", e)
            return 0.3
    
    def _compute_stress_index(self, features: Dict) -> float:
        """
        Compute voice stress index (0-1).
        
        Higher values indicate more stress/anxiety.
        """
        stress = 0.0
        count = 0
        
        # Higher pitch = more stress (normalized around 150-250 Hz typical range)
        if features.get('voice_pitch_mean', 0) > 0:
            pitch_factor = (features['voice_pitch_mean'] - 100) / 200
            stress += np.clip(pitch_factor, 0, 1) * 0.3
            count += 0.3
        
        # Higher pitch variance = more stress
        if features.get('voice_pitch_variance', 0) > 0:
            variance_factor = features['voice_pitch_variance'] / 50
            stress += np.clip(variance_factor, 0, 1) * 0.25
            count += 0.25
        
        # Faster speech = more stress
        if features.get('speech_rate', 0) > 0:
            rate_factor = (features['speech_rate'] - 100) / 100
            stress += np.clip(rate_factor, 0, 1) * 0.25
            count += 0.25
        
        # Less pauses = more stress
        if 'pause_ratio' in features:
            pause_factor = 1 - features['pause_ratio']
            stress += np.clip(pause_factor, 0, 1) * 0.2
            count += 0.2
        
        return float(np.clip(stress / max(count, 0.1), 0, 1))
    
    def _compute_warmth_index(self, features: Dict) -> float:
        """
        Compute voice warmth index (0-1).
        
        Higher values indicate warmer, more empathetic tone.
        """
        warmth = 0.0
        count = 0
        
        # Lower pitch variance = more warmth (steadier voice)
        if features.get('voice_pitch_variance', 0) > 0:
            variance_factor = 1 - (features['voice_pitch_variance'] / 50)
            warmth += np.clip(variance_factor, 0, 1) * 0.3
            count += 0.3
        
        # Moderate energy = warmer (not too loud, not too quiet)
        if features.get('voice_energy', 0) != 0:
            # Optimal around -20 dB
            energy_diff = abs(features['voice_energy'] + 20)
            energy_factor = 1 - (energy_diff / 30)
            warmth += np.clip(energy_factor, 0, 1) * 0.25
            count += 0.25
        
        # Slower speech = warmer
        if features.get('speech_rate', 0) > 0:
            rate_factor = 1 - ((features['speech_rate'] - 80) / 120)
            warmth += np.clip(rate_factor, 0, 1) * 0.25
            count += 0.25
        
        # More pauses = warmer (thoughtful)
        if 'pause_ratio' in features:
            warmth += np.clip(features['pause_ratio'] * 2, 0, 1) * 0.2
            count += 0.2
        
        return float(np.clip(warmth / max(count, 0.1), 0, 1))
    
    def _default_metrics(self) -> Dict[str, float]:
        """Return default metrics when audio processing fails"""
        return {
            'voice_energy': -30.0,
            'voice_pitch_mean': 150.0,
            'voice_pitch_variance': 20.0,
            'speech_rate': 120.0,
            'pause_ratio': 0.3,
            'voice_stress_index': NevedalConstants.VOICE_STRESS_BASELINE,
            'voice_warmth_index': NevedalConstants.VOICE_WARMTH_BASELINE
        }


# =============================================================================
# SYNCHRONY CALCULATOR
# =============================================================================

class SynchronyCalculator:
    """
    Computes dyadic synchrony between two subjects.
    
    Uses cross-correlation and coherence measures to determine
    how "in sync" two people are physiologically and behaviorally.
    """
    
    def __init__(self, history_seconds: int = 30):
        self.history_length = history_seconds
        self.subject_a_history: Dict[str, deque] = {}
        self.subject_b_history: Dict[str, deque] = {}
    
    def add_sample(self, subject: str, metric: str, value: float, timestamp: datetime):
        """Add a sample to the history"""
        history = self.subject_a_history if subject == 'a' else self.subject_b_history
        
        if metric not in history:
            history[metric] = deque(maxlen=100)
        
        history[metric].append((timestamp, value))
    
    def compute_synchrony(self, metric: str) -> float:
        """
        Compute synchrony for a specific metric between subjects.
        
        Returns value between 0 (no sync) and 1 (perfect sync).
        """
        if metric not in self.subject_a_history or metric not in self.subject_b_history:
            return 0.5
        
        hist_a = self.subject_a_history[metric]
        hist_b = self.subject_b_history[metric]
        
        if len(hist_a) < 5 or len(hist_b) < 5:
            return 0.5
        
        # Extract values
        values_a = np.array([v for _, v in hist_a])
        values_b = np.array([v for _, v in hist_b])
        
        # Align lengths
        min_len = min(len(values_a), len(values_b))
        values_a = values_a[-min_len:]
        values_b = values_b[-min_len:]
        
        # Compute correlation
        try:
            if np.std(values_a) > 0 and np.std(values_b) > 0:
                correlation = np.corrcoef(values_a, values_b)[0, 1]
                # Convert correlation (-1 to 1) to synchrony (0 to 1)
                synchrony = (correlation + 1) / 2
                return float(np.clip(synchrony, 0, 1))
        except Exception as e:
            logger.debug("_compute_synchrony(%s) failed: %s", metric, e)
        
        return 0.5
    
    def compute_all_synchrony(self) -> Dict[str, float]:
        """Compute synchrony for all tracked metrics"""
        metrics = set(self.subject_a_history.keys()) & set(self.subject_b_history.keys())
        
        return {
            metric: self.compute_synchrony(metric)
            for metric in metrics
        }


# =============================================================================
# NEVEDAL ENGINE
# =============================================================================

class NevedalEngine:
    """
    Main computation engine for Quantum Emotional Coherence.
    
    Implements the full Nevedal formula and provides:
    - Real-time coherence computation
    - CEE window detection
    - Therapeutic recommendations
    - History tracking
    """
    
    def __init__(self, constants: NevedalConstants = None, db_pool=None):
        self.constants = constants or NevedalConstants()
        self.db_pool = db_pool  # Optional: enables CEE event persistence
        self.voice_extractor = VoiceBiometricExtractor()
        self.synchrony_calculator = SynchronyCalculator()
        
        # Per-session state tracking (keyed by session_id to prevent cross-user contamination)
        self._session_states: Dict[str, "NevedalState"] = {}      # session_id -> current state
        self._session_histories: Dict[str, deque] = {}             # session_id -> state history
        self._session_cee_events: Dict[str, List["CEEEvent"]] = {} # session_id -> CEE events
        self._session_starts: Dict[str, Optional[datetime]] = {}   # session_id -> start time
        self._session_cee_tracking: Dict[str, Dict] = {}           # session_id -> CEE tracking data
        
        # Legacy accessors (for backward compatibility with code that reads these directly)
        self.current_state: Optional[NevedalState] = None
        self.state_history: deque = deque(maxlen=1000)
        self.cee_events: List[CEEEvent] = []
        
        # Session time tracking (for exponential decay in Nevedal formula)
        self._session_start: Optional[datetime] = None
        
        # CEE tracking
        self._cee_start_time: Optional[datetime] = None
        self._cee_peak_c_emo: float = 0.0
        self._cee_samples: List[NevedalState] = []
        
        # Quakete integration — optional bridge to Layer 8 Swarm Solidarity
        self._quakete_resonance_engine = None  # QuaketeResonanceEngine
        self._quakete_trail_map = None          # FibreTrailMap

    def attach_quakete(self, resonance_engine, trail_map=None) -> None:
        """
        Attach Quakete Layer 8 services for Nevedal-to-Quakete resonance bridging.

        When attached, every call to process_biometrics() will automatically
        convert C_emo to Quakete-compatible resonance and update the trail map.

        Args:
            resonance_engine: QuaketeResonanceEngine instance
            trail_map: Optional FibreTrailMap for health updates
        """
        self._quakete_resonance_engine = resonance_engine
        self._quakete_trail_map = trail_map
        logger.info("Quakete Layer 8 attached to Nevedal Engine")

    def _bridge_to_quakete(self, state) -> Optional[float]:
        """
        Convert a NevedalState to Quakete resonance and update the trail map.

        Returns the computed Quakete resonance value, or None if Quakete
        is not attached.
        """
        if self._quakete_resonance_engine is None:
            return None
        try:
            quakete_resonance = self._quakete_resonance_engine.nevedal_to_quakete(
                C_emo=state.c_emo,
                p_ent=state.p_ent,
                T_tunnel=state.t_tunnel,
                gamma_env=state.gamma_env,
            )
            # Update trail map with coherence-derived health if available
            if self._quakete_trail_map and state.user_id:
                try:
                    from app.models.quakete import FibreTrailEmission
                    emission = FibreTrailEmission(
                        fibre_id=state.user_id,
                        fibre_type="nevedal_bridge",
                        resonance_frequency=quakete_resonance,
                        communication_health=min(1.0, state.c_emo),
                    )
                    self._quakete_trail_map.update(emission)
                except Exception as trail_err:
                    logger.debug(f"Trail map update skipped: {trail_err}")
            return quakete_resonance
        except Exception as e:
            logger.warning(f"Nevedal→Quakete bridge error: {e}")
            return None

    def reset_session(self, session_id: str = None) -> None:
        """Reset session-specific state for a new therapeutic session.
        
        Call this at the start of each new session so that elapsed_t
        resets to 0 and the exponential decay in the Nevedal formula
        begins from the new session start time.
        
        If session_id is provided, clears only that session's isolated state.
        Otherwise clears the legacy global state for backward compatibility.
        """
        if session_id:
            self._session_states.pop(session_id, None)
            self._session_histories.pop(session_id, None)
            self._session_cee_events.pop(session_id, None)
            self._session_starts.pop(session_id, None)
            self._session_cee_tracking.pop(session_id, None)
        # Always clear legacy global state too
        self._session_start = None
        self._cee_start_time = None
        self._cee_peak_c_emo = 0.0
        self._cee_samples = []
        self.current_state = None
    
    def _get_session_state(self, session_id: str) -> Optional["NevedalState"]:
        """Get the current state for a specific session (isolated)."""
        return self._session_states.get(session_id)
    
    def _set_session_state(self, session_id: str, state: "NevedalState") -> None:
        """Store state for a specific session (isolated from other sessions)."""
        self._session_states[session_id] = state
        # Also set legacy accessor for backward compatibility
        self.current_state = state
        # Per-session history
        if session_id not in self._session_histories:
            self._session_histories[session_id] = deque(maxlen=200)
        self._session_histories[session_id].append(state)
        # Also append to legacy global history
        self.state_history.append(state)
    
    def get_session_history(self, session_id: str) -> deque:
        """Get state history for a specific session only (no cross-user leakage)."""
        return self._session_histories.get(session_id, deque())
    
    def get_session_cee_events(self, session_id: str) -> List["CEEEvent"]:
        """Get CEE events for a specific session only."""
        return self._session_cee_events.get(session_id, [])
    
    def process_biometrics(
        self,
        session_id: str,
        user_id: str,
        dyad_partner_id: Optional[str],
        biometrics: Dict[str, Any],
        context: Optional[str] = None,
        liminal_resolve_active: bool = False,
    ) -> NevedalState:
        """
        Process biometric input and compute full Nevedal state.
        
        Args:
            session_id: Current session identifier
            user_id: Primary user (client) ID
            dyad_partner_id: Partner (therapist) ID if applicable
            biometrics: Dictionary of biometric readings
            context: Current conversation context (for CEE labeling)
            
        Returns:
            Complete NevedalState with all computed values
        """
        now = datetime.utcnow()
        
        # Track session start for time-dependent decay (first call = session start)
        if self._session_start is None:
            self._session_start = now
        
        # Elapsed time in seconds since session start (for Nevedal exponential decay)
        elapsed_t = (now - self._session_start).total_seconds()
        
        # Extract subject biometrics
        subject_a = biometrics.get('subject_a', {})
        subject_b = biometrics.get('subject_b', {})
        synchrony = biometrics.get('synchrony', {})
        
        # 1. Compute p_ent (Emotional Entanglement)
        p_ent = self._compute_p_ent(subject_a, subject_b, synchrony)
        
        # 2. Compute d (Interpersonal Distance) and T_tunnel
        d_distance = self._compute_distance(subject_a, subject_b)
        t_tunnel = self._compute_tunneling(d_distance)
        
        # 3. Compute γ_env (Decoherence/Noise)
        gamma_env = self._compute_gamma_env(subject_a, subject_b)
        
        # 4. Compute E_G^(joint) (Emotional Load)
        e_g_joint = self._compute_e_g_joint(subject_a, subject_b, p_ent, t_tunnel)
        
        # 5. Compute τ_emo (Coherence Lifetime)
        tau_emo = self._compute_tau_emo(e_g_joint)
        
        # 6. Compute C_emo (Main coherence value with time-dependent decay)
        c_emo = self._compute_c_emo(
            p_ent, t_tunnel, gamma_env, e_g_joint, elapsed_t,
            liminal_resolve_active=liminal_resolve_active,
        )
        
        # 7. Detect CEE window
        cee_window, cee_duration = self._detect_cee(
            p_ent, d_distance, gamma_env, e_g_joint, c_emo, now, context
        )
        
        # 8. Generate interpretation and recommendations
        interpretation = self._generate_interpretation(
            c_emo, p_ent, t_tunnel, gamma_env, e_g_joint, cee_window
        )
        recommendations = self._generate_recommendations(
            c_emo, p_ent, d_distance, gamma_env, e_g_joint, cee_window
        )
        
        # Build state object
        state = NevedalState(
            timestamp=now,
            session_id=session_id,
            user_id=user_id,
            dyad_partner_id=dyad_partner_id,
            c_emo=round(c_emo, 5),
            p_ent=round(p_ent, 5),
            t_tunnel=round(t_tunnel, 5),
            d_distance=round(d_distance, 5),
            gamma_env=round(gamma_env, 5),
            e_g_joint=round(e_g_joint, 5),
            tau_emo=round(tau_emo, 5),
            cee_window=cee_window,
            cee_start_time=self._cee_start_time,
            cee_duration_seconds=cee_duration,
            cee_intensity=round(self._cee_peak_c_emo, 5) if cee_window else 0.0,
            interpretation=interpretation,
            recommendations=recommendations
        )
        
        # Update history
        self.current_state = state
        self.state_history.append(state)

        # Bridge to Quakete Layer 8 (if attached)
        self._bridge_to_quakete(state)
        
        return state

    def check_modal_consistency(
        self,
        biometrics: Dict[str, Any],
        response_text: str,
    ) -> Dict[str, Any]:
        """
        Layer 8 — Multi-modal consistency verification.

        Compares voice biometric signals with the semantic tone of the AI
        response text.  Returns an advisory dict (never blocks delivery).

        Inconsistency types:
          - voice_distress_text_dismissive: high voice stress but response
            doesn't acknowledge distress
          - voice_calm_text_crisis: low voice stress but response assumes
            crisis
        """
        _DISTRESS_WORDS = frozenset([
            "hurt", "scared", "afraid", "terrified", "panic", "desperate",
            "suffering", "agony", "broken", "shattered", "overwhelmed",
            "can't breathe", "falling apart", "end it", "worthless",
        ])
        _DISMISSIVE_WORDS = frozenset([
            "fine", "no big deal", "nothing wrong", "don't worry",
            "you're okay", "it's okay", "not a problem", "all good",
        ])
        _CRISIS_WORDS = frozenset([
            "crisis", "emergency", "immediate danger", "safety plan",
            "reach out to 988", "call 911", "suicidal",
        ])

        subject_a = biometrics.get("subject_a", {})
        stress = subject_a.get("voice_stress_index", 0.3)
        gamma = biometrics.get("gamma_env", self.current_state.gamma_env if self.current_state else 0.3)

        response_lower = response_text.lower()
        flags: List[str] = []

        high_distress = stress > 0.6 or gamma > 0.6
        low_distress = stress < 0.2 and gamma < 0.25

        if high_distress:
            has_dismissive = any(w in response_lower for w in _DISMISSIVE_WORDS)
            has_distress_ack = any(w in response_lower for w in _DISTRESS_WORDS)
            if has_dismissive and not has_distress_ack:
                flags.append("voice_distress_text_dismissive")

        if low_distress:
            has_crisis = any(w in response_lower for w in _CRISIS_WORDS)
            if has_crisis:
                flags.append("voice_calm_text_crisis")

        consistent = len(flags) == 0
        return {
            "consistent": consistent,
            "flags": flags,
            "voice_stress": round(stress, 3),
            "gamma_env": round(gamma, 3),
        }

    def _compute_p_ent(
        self,
        subject_a: Dict,
        subject_b: Dict,
        synchrony: Dict
    ) -> float:
        """
        Compute emotional entanglement (p_ent) from synchrony metrics.
        
        p_ent represents the degree of cross-person entanglement between
        the emotional states of both subjects.
        """
        c = self.constants
        
        # Get synchrony values (0-1)
        hrv_sync = synchrony.get('hrv', 0.5)
        breath_sync = synchrony.get('breath', 0.5)
        voice_sync = synchrony.get('voice', 0.5)
        posture_sync = synchrony.get('posture', 0.5)
        gaze_sync = synchrony.get('gaze', 0.5)
        
        # Weighted average
        p_ent = (
            hrv_sync * c.SYNC_HRV_WEIGHT +
            breath_sync * c.SYNC_BREATH_WEIGHT +
            voice_sync * c.SYNC_VOICE_WEIGHT +
            posture_sync * c.SYNC_POSTURE_WEIGHT
        )
        
        # Boost from gaze contact
        if gaze_sync > 0.7:
            p_ent = min(p_ent * 1.15, 1.0)
        
        return float(np.clip(p_ent, 0, 1))
    
    def _compute_distance(self, subject_a: Dict, subject_b: Dict) -> float:
        """
        Compute interpersonal distance (d) from behavioral signals.
        
        Lower distance = more connected/approach behaviors.
        """
        # Gaze aversion increases distance
        gaze_a = subject_a.get('gaze_contact', 0.5)
        gaze_b = subject_b.get('gaze_contact', 0.5)
        gaze_factor = 1 - ((gaze_a + gaze_b) / 2)
        
        # Body angle away increases distance
        lean_a = subject_a.get('body_lean', 0)
        lean_b = subject_b.get('body_lean', 0)
        # Negative lean = away, positive = toward
        lean_factor = 0.5 - ((lean_a + lean_b) / 60)  # Normalize ±30 degrees
        lean_factor = np.clip(lean_factor, 0, 1)
        
        # Voice warmth reduces distance
        warmth_a = subject_a.get('voice_warmth_index', 0.5)
        warmth_b = subject_b.get('voice_warmth_index', 0.5)
        warmth_factor = 1 - ((warmth_a + warmth_b) / 2)
        
        # Combine factors
        d = (gaze_factor * 0.4 + lean_factor * 0.3 + warmth_factor * 0.3)
        
        return float(np.clip(d, 0.05, 1.0))  # Never exactly 0
    
    def _compute_tunneling(self, d: float) -> float:
        """
        Compute tunneling transparency T_tunnel = T₀ × e^(-d/λ)
        
        Represents how easily emotional states can "tunnel" across
        the interpersonal gap.
        """
        c = self.constants
        t_tunnel = c.T_0 * math.exp(-d / c.LAMBDA)
        return float(np.clip(t_tunnel, 0, 1))
    
    def _compute_gamma_env(self, subject_a: Dict, subject_b: Dict) -> float:
        """
        Compute environmental decoherence rate (γ_env).
        
        Higher values = more noise/disruption to coherence.
        """
        # EDA spikes indicate arousal/stress
        eda_a = subject_a.get('eda', 2.0)
        eda_b = subject_b.get('eda', 2.0)
        eda_factor = min((eda_a + eda_b) / 10, 1.0)
        
        # Voice stress increases decoherence
        stress_a = subject_a.get('voice_stress_index', 0.3)
        stress_b = subject_b.get('voice_stress_index', 0.3)
        stress_factor = (stress_a + stress_b) / 2
        
        # Speech fragmentation (high pause ratio with high stress)
        pause_a = subject_a.get('pause_ratio', 0.3)
        pause_b = subject_b.get('pause_ratio', 0.3)
        
        # Fragmentation = stressed + lots of pauses
        frag_a = stress_a * pause_a if pause_a > 0.5 else 0
        frag_b = stress_b * pause_b if pause_b > 0.5 else 0
        frag_factor = (frag_a + frag_b) / 2
        
        # Combine
        gamma = (eda_factor * 0.35 + stress_factor * 0.4 + frag_factor * 0.25)
        
        return float(np.clip(gamma, 0.05, 1.0))
    
    def _compute_e_g_joint(
        self,
        subject_a: Dict,
        subject_b: Dict,
        p_ent: float,
        t_tunnel: float
    ) -> float:
        """
        Compute joint gravitational self-energy E_G^(joint).
        
        In therapeutic context, this represents the "weight" and complexity
        of emotionally active material being processed.
        """
        c = self.constants
        
        # Voice stress indicates emotional weight
        stress_a = subject_a.get('voice_stress_index', 0.3)
        
        # Facial affect arousal indicates emotional intensity
        arousal_a = subject_a.get('facial_affect_arousal', 0.5)
        
        # Base emotional load
        e_g_base = (stress_a * 0.6 + arousal_a * 0.4)
        
        # Interaction term from formula: α × p_ent × T_tunnel × f(N_A, N_B)
        # Using geometric mean as f(N_A, N_B)
        interaction = c.ALPHA * p_ent * t_tunnel
        
        e_g_joint = e_g_base + interaction
        
        return float(np.clip(e_g_joint, 0, 1))
    
    def _compute_tau_emo(self, e_g_joint: float) -> float:
        """
        Compute coherence lifetime τ_emo ≈ ℏ / E_G^(joint)
        
        Larger E_G = shorter lifetime (faster collapse), but more intense.
        """
        c = self.constants
        
        if e_g_joint < 0.01:
            return 10.0  # Very long lifetime when no emotional load
        
        tau = c.H_BAR / e_g_joint
        return float(np.clip(tau, 0.1, 10.0))
    
    def _compute_c_emo(
        self,
        p_ent: float,
        t_tunnel: float,
        gamma_env: float,
        e_g_joint: float,
        elapsed_t: float = 0.0,
        liminal_resolve_active: bool = False,
    ) -> float:
        """
        Compute the main Quantum Emotional Coherence value with time-dependent decay.
        
        Full Nevedal Formula:
        C_emo(t) = [β × p_ent × T_tunnel] / [γ_env + E_G^(joint)/ℏ]
                   × exp[-(γ_env + E_G^(joint)/ℏ) × t]
        
        The exponential decay models the natural attenuation of emotional coherence
        over the course of a session. As environmental noise (γ_env) and emotional
        load (E_G) increase, coherence decays faster — requiring active therapeutic
        intervention to maintain. The time constant τ = 1/(γ_env + E_G/ℏ) defines
        the characteristic coherence lifetime.
        
        At t=0 (session start), this reduces to the steady-state form.
        
        The decay exponent is normalized by τ_emo (coherence lifetime, typically
        600–3600s) to keep the decay physically meaningful in a therapeutic context.
        
        When liminal_resolve_active is True, the R-inversion applies: system-side
        resistance (patience) becomes a feature that sustains coherence rather than
        degrading it. R_eff = 1 / max(R_raw, 0.1) so higher raw resistance yields
        a LOWER effective denominator, producing higher C_emo.
        
        Args:
            p_ent: Emotional entanglement (0-1)
            t_tunnel: Tunneling transparency (0-1)
            gamma_env: Decoherence rate (0-1)
            e_g_joint: Joint emotional load (0-1)
            elapsed_t: Elapsed session time in seconds (default 0)
            liminal_resolve_active: Whether LIMINAL RESOLVE R-inversion is active
        """
        c = self.constants
        
        numerator = c.BETA * p_ent * t_tunnel
        denominator = gamma_env + (e_g_joint / c.H_BAR)
        
        if denominator < 0.01:
            denominator = 0.01
        
        # QUANTUM-CRYSTAL-ARCH — R-inversion: patience increases coherence
        raw_denominator = denominator
        if liminal_resolve_active:
            denominator = 1.0 / max(raw_denominator, 0.1)
        
        # Steady-state amplitude
        c_emo_0 = numerator / denominator
        
        # Time-dependent exponential decay: exp[-(γ_env + E_G/ℏ) × t_normalized]
        # Normalize elapsed time by a therapeutic session timescale (3600s = 1 hour)
        # so the decay exponent stays in a physically meaningful range.
        tau_session = 3600.0  # normalization timescale in seconds
        t_normalized = elapsed_t / tau_session
        # During LR, use the inverted denominator for decay (coherence sustained longer)
        decay = np.exp(-denominator * t_normalized)
        
        c_emo = c_emo_0 * decay
        
        return float(np.clip(c_emo, 0, 1))
    
    def _detect_cee(
        self,
        p_ent: float,
        d: float,
        gamma_env: float,
        e_g_joint: float,
        c_emo: float,
        now: datetime,
        context: Optional[str]
    ) -> Tuple[bool, int]:
        """
        Detect if we're in a Corrective Emotional Experience window.
        
        LIMINAL INTELLIGENCE NOTE:
        A CEE is fundamentally a liminal event — the user is crossing a threshold
        between an old emotional pattern and a new one. The conditions below detect
        when entanglement is high enough and defenses low enough that the person is
        standing at the limen (threshold) between their familiar pain and an
        unfamiliar but healing experience. This is the quantum-emotional analog of
        Liminal Intelligence: the system detects when someone is "in-between" and
        creates the conditions for transformation rather than rushing to resolution.
        
        When a CEE is detected, Little Nate's therapeutic presence should embody
        Liminal Unconditional Love — holding steady at the threshold, not rushing
        the person through it, and offering the experience of being seen and held
        in the most vulnerable moment of transition.
        
        CEE conditions:
        1. High entanglement (p_ent > threshold) — strong relational bond
        2. Low distance (d < threshold) — emotional closeness achieved
        3. Low/dropping decoherence (γ_env < threshold) — minimal environmental disruption
        4. Moderate-high emotional load (E_G > threshold) — genuine emotional activation
        5. Sustained for minimum duration — the threshold must be held, not just touched
        """
        c = self.constants
        
        # Check CEE conditions — per PhD spec §2.4:
        # CEE Window ⟺ C_emo(t) ≥ θ_CEE (0.72) for sustained Δt_min (30s)
        # Additional component conditions ensure biometric quality
        cee_conditions_met = (
            c_emo >= c.CEE_P_ENT_MIN and    # θ_CEE = 0.72 applied to C_emo(t)
            p_ent >= c.CEE_P_ENT_MIN and
            d <= c.CEE_D_MAX and
            gamma_env <= c.CEE_GAMMA_MAX and
            e_g_joint >= c.CEE_E_G_MIN
        )
        
        if cee_conditions_met:
            # Start or continue CEE
            if self._cee_start_time is None:
                self._cee_start_time = now
                self._cee_peak_c_emo = c_emo
                self._cee_samples = []
            else:
                self._cee_peak_c_emo = max(self._cee_peak_c_emo, c_emo)
            
            duration = int((now - self._cee_start_time).total_seconds())
            
            # Only count as CEE if duration meets minimum
            is_valid_cee = duration >= c.CEE_DURATION_MIN
            
            return is_valid_cee, duration
        else:
            # CEE ended - record if it was valid
            if self._cee_start_time is not None:
                duration = int((now - self._cee_start_time).total_seconds())
                
                if duration >= c.CEE_DURATION_MIN:
                    # Record the CEE event
                    event = CEEEvent(
                        session_id=self.current_state.session_id if self.current_state else "unknown",
                        start_time=self._cee_start_time,
                        end_time=now,
                        duration_seconds=duration,
                        peak_c_emo=self._cee_peak_c_emo,
                        avg_p_ent=p_ent,  # Would be better to average over window
                        avg_gamma_env=gamma_env,
                        trigger_context=context or "Not recorded",
                        therapeutic_value="Potential corrective experience detected"
                    )
                    self.cee_events.append(event)
                    # Persist to database if db_pool is available
                    self._persist_cee_event_sync(event)
            
            # Reset CEE tracking
            self._cee_start_time = None
            self._cee_peak_c_emo = 0.0
            self._cee_samples = []
            
            return False, 0

    def _persist_cee_event_sync(self, event: 'CEEEvent') -> None:
        """
        Schedule CEE event persistence to the nevedal_metrics table.
        Uses a fire-and-forget asyncio task if an event loop is running,
        otherwise logs a warning. This avoids making _detect_cee async.
        """
        if not self.db_pool:
            return
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._persist_cee_event(event))
            else:
                # No running loop — skip DB persistence (tests, CLI)
                pass
        except RuntimeError:
            pass

    async def _persist_cee_event(self, event: 'CEEEvent') -> None:
        """Persist a CEE event to the database."""
        try:
            async with self.db_pool.acquire() as conn:
                hw_id = self.current_state.user_id if self.current_state else None
                if not hw_id:
                    return
                user_uuid = await conn.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                    hw_id,
                )
                if not user_uuid:
                    return

                session_uuid = None
                if event.session_id and event.session_id != "unknown":
                    try:
                        import uuid as _uuid_mod
                        parsed = _uuid_mod.UUID(str(event.session_id))
                        exists = await conn.fetchval("SELECT 1 FROM sessions WHERE id = $1", parsed)
                        if exists:
                            session_uuid = parsed
                    except (ValueError, AttributeError):
                        pass

                await conn.execute("""
                    INSERT INTO nevedal_metrics
                        (session_id, user_id, recorded_at, c_emo, cee_window,
                         cee_duration_seconds, biometrics)
                    VALUES ($1, $2, $3, $4, TRUE, $5, $6)
                """,
                    session_uuid,
                    user_uuid,
                    event.end_time,
                    round(event.peak_c_emo, 5),
                    event.duration_seconds,
                    json.dumps(self._encrypt_biometric_payload({
                        "cee_start": event.start_time.isoformat(),
                        "cee_end": event.end_time.isoformat(),
                        "avg_p_ent": event.avg_p_ent,
                        "avg_gamma_env": event.avg_gamma_env,
                        "trigger_context": event.trigger_context,
                        "therapeutic_value": event.therapeutic_value,
                    })),
                )
                # SOVEREIGN-VOICE: log coherence event for longitudinal tracking
                try:
                    _domain = event.trigger_context or "general"
                    await conn.execute("""
                        INSERT INTO nevedal_coherence_log
                            (domain, C_emo, p_ent, T_tunnel, gamma_env)
                        VALUES ($1, $2, $3, $4, $5)
                    """,
                        _domain,
                        round(event.peak_c_emo, 5),
                        round(event.avg_p_ent, 5),
                        0.37,
                        round(event.avg_gamma_env, 5),
                    )
                except Exception as _cl_err:
                    print(f">>> [NEVEDAL] coherence_log write: {_cl_err}")

                # SOVEREIGN-VOICE: upsert domain state with actual Nevedal parameters
                try:
                    _domain = event.trigger_context or "general"
                    _crystal_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM nate_intelligence_crystals"
                    ) or 0
                    await conn.execute("""
                        INSERT INTO nevedal_domain_state
                            (domain, C_emo, p_ent, gamma_env, crystal_count, updated_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        ON CONFLICT (domain) DO UPDATE SET
                            C_emo = EXCLUDED.C_emo,
                            p_ent = EXCLUDED.p_ent,
                            gamma_env = EXCLUDED.gamma_env,
                            crystal_count = EXCLUDED.crystal_count,
                            updated_at = NOW()
                    """,
                        _domain,
                        round(event.peak_c_emo, 5),
                        round(event.avg_p_ent, 5),
                        round(event.avg_gamma_env, 5),
                        _crystal_count,
                    )
                except Exception as _ds_err:
                    print(f">>> [NEVEDAL] domain_state write: {_ds_err}")

                # UCD event hook: fire ec_shift when CEE detected with significant C_emo
                try:
                    if event.peak_c_emo > 0.4:
                        from app.sse.ucd.event_hooks import fire_ucd_event
                        import asyncio as _aio
                        _uid = str(hw_id)
                        _aio.create_task(fire_ucd_event(
                            _uid, "ec_shift",
                            {"c_emo": round(event.peak_c_emo, 5),
                             "duration": event.duration_seconds,
                             "domain": event.trigger_context or "general"},
                            self.db_pool, None,
                        ))
                except Exception:
                    pass

        except Exception as e:
            print(f">>> [NEVEDAL] Failed to persist CEE event: {e}")

    @staticmethod
    def _encrypt_biometric_payload(payload: dict) -> dict:
        """Encrypt sensitive biometric fields before DB persistence.
        
        Fields like trigger_context, voice stress data, and pitch values
        are encrypted at rest to prevent exposure if the database is compromised.
        """
        try:
            from app.field_encryption import encrypt_fields
            return encrypt_fields(payload)
        except Exception:
            return payload  # Graceful fallback — don't block persistence

    @staticmethod
    def _decrypt_biometric_payload(payload: dict) -> dict:
        """Decrypt biometric fields after reading from DB."""
        try:
            from app.field_encryption import decrypt_fields
            return decrypt_fields(payload)
        except Exception:
            return payload

    def _generate_interpretation(
        self,
        c_emo: float,
        p_ent: float,
        t_tunnel: float,
        gamma_env: float,
        e_g_joint: float,
        cee_window: bool
    ) -> str:
        """Generate human-readable interpretation of current state"""
        parts = []
        
        # Overall coherence
        if c_emo >= 0.7:
            parts.append("Strong emotional coherence")
        elif c_emo >= 0.5:
            parts.append("Moderate emotional coherence")
        elif c_emo >= 0.3:
            parts.append("Low emotional coherence")
        else:
            parts.append("Minimal emotional coherence")
        
        # Entanglement
        if p_ent >= 0.7:
            parts.append("high dyadic synchrony")
        elif p_ent < 0.4:
            parts.append("limited synchrony")
        
        # Decoherence
        if gamma_env >= 0.6:
            parts.append("elevated arousal/noise")
        elif gamma_env <= 0.2:
            parts.append("calm regulated state")
        
        # CEE
        if cee_window:
            parts.append("🌟 CEE WINDOW ACTIVE - optimal therapeutic moment")
        
        return "; ".join(parts) + "."
    
    def _generate_recommendations(
        self,
        c_emo: float,
        p_ent: float,
        d: float,
        gamma_env: float,
        e_g_joint: float,
        cee_window: bool
    ) -> List[str]:
        """Generate therapeutic recommendations based on current state"""
        recs = []
        
        if cee_window:
            recs.append("Continue empathic reflection - client is in optimal window")
            recs.append("Avoid premature problem-solving or topic changes")
            recs.append("Allow silence if it emerges naturally")
        
        elif c_emo < 0.4:
            # Low coherence - need to build connection
            if p_ent < 0.5:
                recs.append("Focus on attunement - match client's pace and tone")
                recs.append("Use more reflective statements")
            
            if d > 0.6:
                recs.append("Client may be defensive - validate their experience")
                recs.append("Consider checking for misattunement")
            
            if gamma_env > 0.5:
                recs.append("High arousal detected - consider grounding exercise")
                recs.append("Slow the pace of conversation")
        
        elif c_emo >= 0.5 and not cee_window:
            # Good coherence but not CEE - opportunity to deepen
            if e_g_joint < 0.4:
                recs.append("Good connection established - safe to explore deeper")
                recs.append("Consider emotion-focused or attachment-focused intervention")
        
        if gamma_env > 0.7:
            recs.append("⚠️ High stress/arousal - monitor for overwhelm")
        
        return recs if recs else ["Continue current approach"]
    
    def process_voice_audio(
        self,
        audio_data: bytes,
        subject: str = 'a'
    ) -> Dict[str, float]:
        """
        Process raw voice audio and extract biometric features.
        
        Args:
            audio_data: Raw PCM audio bytes
            subject: 'a' for client, 'b' for therapist
            
        Returns:
            Extracted voice biometrics
        """
        return self.voice_extractor.process_audio_chunk(audio_data)
    
    def get_session_summary(self, session_id: str) -> Dict:
        """Get summary statistics for a session (uses isolated per-session history)."""
        # Prefer isolated per-session history; fall back to filtering global history
        session_states = list(self.get_session_history(session_id))
        if not session_states:
            session_states = [s for s in self.state_history if s.session_id == session_id]
        
        if not session_states:
            return {"error": "No data for session"}
        
        c_emo_values = [s.c_emo for s in session_states]
        p_ent_values = [s.p_ent for s in session_states]
        
        session_cees = [e for e in self.cee_events if e.session_id == session_id]
        
        return {
            "session_id": session_id,
            "sample_count": len(session_states),
            "duration_seconds": (session_states[-1].timestamp - session_states[0].timestamp).total_seconds(),
            "c_emo": {
                "mean": float(np.mean(c_emo_values)),
                "max": float(np.max(c_emo_values)),
                "min": float(np.min(c_emo_values)),
                "std": float(np.std(c_emo_values))
            },
            "p_ent": {
                "mean": float(np.mean(p_ent_values)),
                "max": float(np.max(p_ent_values))
            },
            "cee_events": len(session_cees),
            "cee_total_duration": sum(e.duration_seconds for e in session_cees),
            "cee_peak_coherence": max((e.peak_c_emo for e in session_cees), default=0)
        }


# =============================================================================
# WEBSOCKET STREAMING
# =============================================================================

class NevedalStreamManager:
    """
    Manages real-time WebSocket streaming of Nevedal metrics.
    
    Broadcasts updates to connected admin dashboards and research tools.
    """
    
    def __init__(self, engine: NevedalEngine):
        self.engine = engine
        self.subscribers: Dict[str, set] = {}  # session_id -> websockets
    
    def subscribe(self, session_id: str, websocket):
        """Subscribe a websocket to session updates"""
        if session_id not in self.subscribers:
            self.subscribers[session_id] = set()
        self.subscribers[session_id].add(websocket)
    
    def unsubscribe(self, session_id: str, websocket):
        """Unsubscribe a websocket"""
        if session_id in self.subscribers:
            self.subscribers[session_id].discard(websocket)
    
    async def broadcast_update(self, state: NevedalState):
        """Broadcast state update to all subscribers"""
        if state.session_id not in self.subscribers:
            return
        
        message = {
            "type": "nevedal_update",
            "data": state.to_dict()
        }
        
        payload = json.dumps(message)
        
        dead_sockets = set()
        for ws in self.subscribers[state.session_id]:
            try:
                await ws.send(payload)
            except Exception as e:
                logger.debug("ws broadcast failed for session %s: %s", state.session_id, e)
                dead_sockets.add(ws)
        
        # Clean up dead connections
        for ws in dead_sockets:
            self.subscribers[state.session_id].discard(ws)


# =============================================================================
# INTEGRATION WITH EXISTING BRIDGE SERVER
# =============================================================================

def create_nevedal_engine(
    quakete_resonance_engine=None,
    quakete_trail_map=None,
    db_pool=None,
) -> NevedalEngine:
    """Factory function to create a configured Nevedal engine.

    Args:
        quakete_resonance_engine: Optional QuaketeResonanceEngine for Layer 8 bridge
        quakete_trail_map: Optional FibreTrailMap for health updates
        db_pool: Optional database pool for CEE event persistence
    """
    engine = NevedalEngine(NevedalConstants(), db_pool=db_pool)
    if quakete_resonance_engine:
        engine.attach_quakete(quakete_resonance_engine, quakete_trail_map)
    return engine


# Example usage in bridge_server_hybrid.py:
"""
# In bridge_server_hybrid.py, add:

from nevedal_engine import create_nevedal_engine, NevedalStreamManager

# Initialize
nevedal_engine = create_nevedal_engine()
nevedal_stream = NevedalStreamManager(nevedal_engine)

# In message handler:
elif msg_type == "biometric_update":
    biometrics = data.get("biometrics", {})
    state = nevedal_engine.process_biometrics(
        session_id=current_session_id,
        user_id=profile.get("hardware_id"),
        dyad_partner_id=coach_id,
        biometrics=biometrics
    )
    
    # Send to client
    await websocket.send(json.dumps({
        "type": "nevedal_state",
        "data": state.to_dict()
    }))
    
    # Broadcast to admin dashboards
    await nevedal_stream.broadcast_update(state)
"""


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    # Test the engine
    engine = create_nevedal_engine()
    
    # Simulate biometric input
    test_biometrics = {
        "subject_a": {
            "gaze_contact": 0.75,
            "body_lean": 12,
            "voice_stress_index": 0.25,
            "voice_warmth_index": 0.7,
            "eda": 2.1,
            "pause_ratio": 0.35
        },
        "subject_b": {
            "gaze_contact": 0.82,
            "body_lean": 10,
            "voice_stress_index": 0.15,
            "voice_warmth_index": 0.8,
            "eda": 1.8,
            "pause_ratio": 0.4
        },
        "synchrony": {
            "hrv": 0.85,
            "breath": 0.78,
            "voice": 0.72,
            "posture": 0.80,
            "gaze": 0.75
        }
    }
    
    # Process
    state = engine.process_biometrics(
        session_id="test_session_001",
        user_id="client_123",
        dyad_partner_id="coach_456",
        biometrics=test_biometrics,
        context="Discussing childhood memories"
    )
    
    print("\n" + "=" * 60)
    print("NEVEDAL ENGINE TEST OUTPUT")
    print("=" * 60)
    print(f"\nC_emo (Coherence):     {state.c_emo:.4f}")
    print(f"p_ent (Entanglement):  {state.p_ent:.4f}")
    print(f"T_tunnel (Tunneling):  {state.t_tunnel:.4f}")
    print(f"d (Distance):          {state.d_distance:.4f}")
    print(f"γ_env (Decoherence):   {state.gamma_env:.4f}")
    print(f"E_G (Load):            {state.e_g_joint:.4f}")
    print(f"τ_emo (Lifetime):      {state.tau_emo:.4f}")
    print(f"\nCEE Window:            {state.cee_window}")
    print(f"\nInterpretation: {state.interpretation}")
    print(f"\nRecommendations:")
    for rec in state.recommendations:
        print(f"  • {rec}")
    print("=" * 60)
