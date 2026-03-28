"""
HIVE DEFENSE PROTOCOL — Differential Privacy (Phase 8C, Third Cord)
Noise injection for forensic watermarking of exported therapeutic data.

All exported or displayed member data includes a subtle ±5% random
perturbation on statistical aggregates and numerical values.  Names
are preserved (coaches need them for clinical work), but every
numerical field receives session-unique noise.

The perturbation pattern is deterministic per session — the same
session ID always produces the same noise pattern.  This creates a
forensic watermark: if the data is exfiltrated and published, the
unique perturbation pattern traces back to the specific viewing
session that leaked it.

Properties
----------
1. **Clinical value preserved** — 5% noise does not affect clinical
   judgment.  Coherence scores of 0.72 vs 0.68 are clinically
   equivalent.
2. **Forensic traceability** — each session's perturbation pattern is
   unique and verifiable.  Given exfiltrated data and a session ID,
   we can confirm whether the data came from that session.
3. **No steganography** — the watermark is not hidden information
   embedded in the data; it IS the data.  The noise pattern is the
   watermark, requiring no special encoding or decoding.
4. **Plausible deniability** — noise is small enough that individual
   perturbed values cannot be definitively distinguished from
   measurement variance.  Only the correlated pattern across
   multiple values provides forensic certainty.

Patent-Pending — Claim 55
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from uuid import UUID, uuid4

logger = logging.getLogger("hive.differential_privacy")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default noise magnitude as a fraction of value
DEFAULT_NOISE_FRACTION = 0.05  # ±5%

# HMAC key length for noise generation
NOISE_KEY_LENGTH = 32

# Minimum number of fields needed to detect pattern with confidence
MIN_FIELDS_FOR_DETECTION = 5

# Detection correlation threshold
DETECTION_CORRELATION_THRESHOLD = 0.85

# Fields that should NEVER be perturbed (clinical identity)
EXEMPT_FIELDS = frozenset({
    "name",
    "first_name",
    "last_name",
    "display_name",
    "email",
    "phone",
    "date_of_birth",
    "member_id",
    "coach_id",
    "session_id",
    "user_id",
    "family_id",
    "ring_id",
    "created_at",
    "updated_at",
    "timestamp",
})


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class NoiseProfile:
    """
    The noise pattern applied to a specific session's data export.

    Attributes
    ----------
    session_id : str
        The viewing session that generated this noise profile.
    noise_seed : bytes
        Deterministic seed derived from session ID and master key.
    field_perturbations : dict[str, float]
        Field name → perturbation factor applied.
    noise_fraction : float
        Maximum noise magnitude as a fraction of value.
    fields_perturbed : int
        Number of numeric fields that received noise.
    created_at : datetime
        When this profile was generated.
    """
    session_id: str = ""
    noise_seed: bytes = b""
    field_perturbations: Dict[str, float] = field(default_factory=dict)
    noise_fraction: float = DEFAULT_NOISE_FRACTION
    fields_perturbed: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DetectionResult:
    """
    Result of attempting to match exfiltrated data to a viewing session.

    Attributes
    ----------
    session_id : str
        The session ID being tested.
    match : bool
        Whether the data's noise pattern matches this session.
    correlation : float
        Pearson correlation between observed and expected perturbations.
    fields_compared : int
        Number of fields used in the comparison.
    confidence : str
        Confidence level: "high", "medium", "low", "no_match".
    details : dict
        Additional analysis details.
    """
    session_id: str = ""
    match: bool = False
    correlation: float = 0.0
    fields_compared: int = 0
    confidence: str = "no_match"
    details: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# DIFFERENTIAL PRIVACY ENGINE
# =============================================================================

class DifferentialPrivacy:
    """
    Noise injection engine for forensic watermarking of therapeutic data.

    Applies session-unique ±5% perturbation to numerical fields in
    exported data, creating a forensic watermark that traces leaked
    data back to the viewing session.

    Parameters
    ----------
    noise_fraction : float
        Maximum noise magnitude as fraction of value (default 0.05).
    master_key : bytes or None
        Master HMAC key for deterministic noise generation.
        If None, a random key is generated.

    Usage
    -----
    ::

        dp = DifferentialPrivacy()

        # Apply noise to data for a specific session
        noisy_data = await dp.apply_noise(data, session_id="sess_abc123")

        # Later: verify if leaked data came from a specific session
        result = await dp.detect_noise_pattern(leaked_data, session_id="sess_abc123")
    """

    def __init__(
        self,
        *,
        noise_fraction: float = DEFAULT_NOISE_FRACTION,
        master_key: Optional[bytes] = None,
    ) -> None:
        self._noise_fraction = noise_fraction
        self._master_key = master_key or os.urandom(NOISE_KEY_LENGTH)

        # Noise profile registry: session_id → NoiseProfile
        self._profiles: Dict[str, NoiseProfile] = {}

        # Original data cache for detection: session_id → original_data_hash
        self._original_hashes: Dict[str, Dict[str, float]] = {}

        # Concurrency
        self._lock = asyncio.Lock()

        # Stats
        self._total_applications: int = 0
        self._total_detections: int = 0
        self._total_matches: int = 0

        logger.info(
            "DifferentialPrivacy initialised — noise=±%.1f%%, "
            "key_length=%d, exempt_fields=%d",
            self._noise_fraction * 100,
            len(self._master_key),
            len(EXEMPT_FIELDS),
        )

    # --------------------------------------------------------------------- #
    # NOISE APPLICATION
    # --------------------------------------------------------------------- #

    async def apply_noise(
        self,
        data: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Apply session-unique noise to exported data.

        Numerical fields receive a deterministic ±5% perturbation based
        on the session ID.  Non-numeric fields and exempt fields (names,
        IDs, timestamps) are passed through unchanged.

        Parameters
        ----------
        data : dict
            The data to perturb.  Can be nested (dicts within dicts).
        session_id : str
            The viewing session ID.  Same session always produces the
            same perturbation pattern.

        Returns
        -------
        dict
            Perturbed data with forensic watermark.
        """
        # Generate deterministic noise seed from session ID
        noise_seed = self._generate_noise_seed(session_id)

        # Track perturbations for this session
        perturbations: Dict[str, float] = {}
        original_values: Dict[str, float] = {}

        # Apply noise recursively
        noisy_data = self._perturb_dict(
            data=data,
            noise_seed=noise_seed,
            path_prefix="",
            perturbations=perturbations,
            original_values=original_values,
        )

        # Store the profile
        profile = NoiseProfile(
            session_id=session_id,
            noise_seed=noise_seed,
            field_perturbations=perturbations,
            noise_fraction=self._noise_fraction,
            fields_perturbed=len(perturbations),
        )

        async with self._lock:
            self._profiles[session_id] = profile
            self._original_hashes[session_id] = original_values
            self._total_applications += 1

        logger.info(
            "Noise applied — session='%s', %d fields perturbed (±%.1f%%)",
            session_id,
            len(perturbations),
            self._noise_fraction * 100,
        )

        return noisy_data

    def _perturb_dict(
        self,
        data: Dict[str, Any],
        noise_seed: bytes,
        path_prefix: str,
        perturbations: Dict[str, float],
        original_values: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Recursively perturb numeric values in a dictionary.

        Parameters
        ----------
        data : dict
            Data to perturb.
        noise_seed : bytes
            Deterministic seed for noise generation.
        path_prefix : str
            Dot-delimited path prefix for nested field tracking.
        perturbations : dict
            Accumulator for perturbation factors applied.
        original_values : dict
            Accumulator for original values before perturbation.

        Returns
        -------
        dict
            Perturbed copy of the data.
        """
        result: Dict[str, Any] = {}

        for key, value in data.items():
            field_path = f"{path_prefix}.{key}" if path_prefix else key

            # Skip exempt fields
            if key.lower() in EXEMPT_FIELDS:
                result[key] = value
                continue

            if isinstance(value, dict):
                # Recurse into nested dicts
                result[key] = self._perturb_dict(
                    value, noise_seed, field_path,
                    perturbations, original_values,
                )
            elif isinstance(value, list):
                # Perturb numeric items in lists
                result[key] = self._perturb_list(
                    value, noise_seed, field_path,
                    perturbations, original_values,
                )
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                # Apply noise to numeric values
                perturbation = self._compute_perturbation(
                    noise_seed, field_path
                )
                original_values[field_path] = float(value)

                if isinstance(value, int):
                    noisy_value = int(round(value * (1.0 + perturbation)))
                else:
                    noisy_value = value * (1.0 + perturbation)
                    # Preserve reasonable precision
                    noisy_value = round(noisy_value, 6)

                result[key] = noisy_value
                perturbations[field_path] = perturbation
            else:
                # Pass through non-numeric values unchanged
                result[key] = value

        return result

    def _perturb_list(
        self,
        data: List[Any],
        noise_seed: bytes,
        path_prefix: str,
        perturbations: Dict[str, float],
        original_values: Dict[str, float],
    ) -> List[Any]:
        """
        Perturb numeric items within a list.

        Parameters
        ----------
        data : list
            List to perturb.
        noise_seed : bytes
            Deterministic seed.
        path_prefix : str
            Field path prefix.
        perturbations : dict
            Perturbation accumulator.
        original_values : dict
            Original value accumulator.

        Returns
        -------
        list
            Perturbed copy of the list.
        """
        result: List[Any] = []

        for idx, item in enumerate(data):
            item_path = f"{path_prefix}[{idx}]"

            if isinstance(item, dict):
                result.append(self._perturb_dict(
                    item, noise_seed, item_path,
                    perturbations, original_values,
                ))
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                perturbation = self._compute_perturbation(
                    noise_seed, item_path
                )
                original_values[item_path] = float(item)

                if isinstance(item, int):
                    noisy = int(round(item * (1.0 + perturbation)))
                else:
                    noisy = round(item * (1.0 + perturbation), 6)

                result.append(noisy)
                perturbations[item_path] = perturbation
            else:
                result.append(item)

        return result

    # --------------------------------------------------------------------- #
    # NOISE GENERATION (DETERMINISTIC)
    # --------------------------------------------------------------------- #

    def _generate_noise_seed(self, session_id: str) -> bytes:
        """
        Generate a deterministic noise seed from a session ID.

        The same session ID always produces the same seed (and therefore
        the same perturbation pattern).

        Parameters
        ----------
        session_id : str
            The viewing session identifier.

        Returns
        -------
        bytes
            32-byte deterministic seed.
        """
        return hmac.new(
            self._master_key,
            session_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    def _compute_perturbation(
        self,
        noise_seed: bytes,
        field_path: str,
    ) -> float:
        """
        Compute the perturbation factor for a specific field.

        The perturbation is deterministic: same seed + same field path
        always produces the same factor.

        Parameters
        ----------
        noise_seed : bytes
            Session-derived seed.
        field_path : str
            Dot-delimited field path.

        Returns
        -------
        float
            Perturbation factor in [-noise_fraction, +noise_fraction].
        """
        # HMAC the field path with the noise seed
        field_mac = hmac.new(
            noise_seed,
            field_path.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        # Extract a uniform value in [0, 1) from the first 8 bytes
        raw = struct.unpack("Q", field_mac[:8])[0]
        unit = raw / (2**64)  # [0, 1)

        # Map to [-noise_fraction, +noise_fraction]
        perturbation = (unit * 2.0 - 1.0) * self._noise_fraction

        return perturbation

    # --------------------------------------------------------------------- #
    # NOISE DETECTION (FORENSIC WATERMARK VERIFICATION)
    # --------------------------------------------------------------------- #

    async def detect_noise_pattern(
        self,
        data: Dict[str, Any],
        session_id: str,
    ) -> DetectionResult:
        """
        Verify whether data's noise pattern matches a specific session.

        Computes the expected perturbation pattern for the given session
        ID and compares it against the observed values.  A high
        correlation indicates the data was exported during that session.

        Parameters
        ----------
        data : dict
            The potentially exfiltrated data.
        session_id : str
            The session ID to test against.

        Returns
        -------
        DetectionResult
            Whether the data matches this session's watermark.
        """
        # Get original values for this session
        async with self._lock:
            original_values = self._original_hashes.get(session_id)

        if not original_values:
            logger.warning(
                "No original values stored for session '%s' — "
                "cannot perform detection",
                session_id,
            )
            return DetectionResult(
                session_id=session_id,
                match=False,
                confidence="no_data",
                details={"reason": "No original values for this session"},
            )

        # Generate the expected noise pattern
        noise_seed = self._generate_noise_seed(session_id)

        # Extract observed values from the data
        observed_values: Dict[str, float] = {}
        self._extract_numeric_values(data, "", observed_values)

        # Compare observed perturbations against expected
        expected_perturbations: List[float] = []
        observed_perturbations: List[float] = []
        fields_compared = 0

        for field_path, original in original_values.items():
            if field_path not in observed_values:
                continue
            if original == 0:
                continue  # Skip zero-division cases

            observed = observed_values[field_path]
            observed_pct = (observed - original) / original

            expected_pct = self._compute_perturbation(noise_seed, field_path)

            expected_perturbations.append(expected_pct)
            observed_perturbations.append(observed_pct)
            fields_compared += 1

        if fields_compared < MIN_FIELDS_FOR_DETECTION:
            return DetectionResult(
                session_id=session_id,
                match=False,
                fields_compared=fields_compared,
                confidence="insufficient_data",
                details={
                    "reason": (
                        f"Only {fields_compared} comparable fields "
                        f"(need {MIN_FIELDS_FOR_DETECTION})"
                    ),
                },
            )

        # Compute Pearson correlation
        correlation = self._pearson_correlation(
            expected_perturbations,
            observed_perturbations,
        )

        # Determine match
        match = correlation >= DETECTION_CORRELATION_THRESHOLD

        # Classify confidence
        if correlation >= 0.95:
            confidence = "high"
        elif correlation >= DETECTION_CORRELATION_THRESHOLD:
            confidence = "medium"
        elif correlation >= 0.50:
            confidence = "low"
        else:
            confidence = "no_match"

        result = DetectionResult(
            session_id=session_id,
            match=match,
            correlation=round(correlation, 6),
            fields_compared=fields_compared,
            confidence=confidence,
            details={
                "threshold": DETECTION_CORRELATION_THRESHOLD,
                "noise_fraction": self._noise_fraction,
            },
        )

        async with self._lock:
            self._total_detections += 1
            if match:
                self._total_matches += 1

        if match:
            logger.warning(
                "WATERMARK MATCH — session='%s', correlation=%.4f, "
                "fields=%d, confidence=%s",
                session_id,
                correlation,
                fields_compared,
                confidence,
            )
        else:
            logger.debug(
                "No watermark match — session='%s', correlation=%.4f",
                session_id,
                correlation,
            )

        return result

    def _extract_numeric_values(
        self,
        data: Dict[str, Any],
        path_prefix: str,
        accumulator: Dict[str, float],
    ) -> None:
        """
        Recursively extract numeric values from a dict with field paths.

        Parameters
        ----------
        data : dict
            Data to extract from.
        path_prefix : str
            Current path prefix.
        accumulator : dict
            Output: field_path → numeric value.
        """
        for key, value in data.items():
            field_path = f"{path_prefix}.{key}" if path_prefix else key

            if key.lower() in EXEMPT_FIELDS:
                continue

            if isinstance(value, dict):
                self._extract_numeric_values(value, field_path, accumulator)
            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    item_path = f"{field_path}[{idx}]"
                    if isinstance(item, dict):
                        self._extract_numeric_values(
                            item, item_path, accumulator
                        )
                    elif isinstance(item, (int, float)) and not isinstance(item, bool):
                        accumulator[item_path] = float(item)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                accumulator[field_path] = float(value)

    @staticmethod
    def _pearson_correlation(
        x: Sequence[float],
        y: Sequence[float],
    ) -> float:
        """
        Compute Pearson correlation coefficient between two sequences.

        Parameters
        ----------
        x : sequence of float
            First sequence.
        y : sequence of float
            Second sequence (same length as x).

        Returns
        -------
        float
            Pearson r in [-1, 1].  Returns 0.0 if computation fails.
        """
        n = len(x)
        if n < 2 or n != len(y):
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        denom_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

        if denom_x < 1e-15 or denom_y < 1e-15:
            return 0.0

        return numerator / (denom_x * denom_y)

    # --------------------------------------------------------------------- #
    # PROFILE ACCESS
    # --------------------------------------------------------------------- #

    async def get_noise_profile(
        self,
        session_id: str,
    ) -> Optional[NoiseProfile]:
        """Return the noise profile for a session, or None."""
        async with self._lock:
            return self._profiles.get(session_id)

    async def get_all_sessions(self) -> List[str]:
        """Return all session IDs with stored noise profiles."""
        async with self._lock:
            return list(self._profiles.keys())

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of differential privacy engine."""
        return {
            "total_applications": self._total_applications,
            "total_detections": self._total_detections,
            "total_matches": self._total_matches,
            "stored_profiles": len(self._profiles),
            "noise_fraction_pct": round(self._noise_fraction * 100, 1),
            "exempt_fields": len(EXEMPT_FIELDS),
            "detection_threshold": DETECTION_CORRELATION_THRESHOLD,
            "min_fields_for_detection": MIN_FIELDS_FOR_DETECTION,
        }

    def __repr__(self) -> str:
        return (
            f"<DifferentialPrivacy noise=±{self._noise_fraction * 100:.1f}% "
            f"applications={self._total_applications} "
            f"detections={self._total_detections} "
            f"matches={self._total_matches}>"
        )
