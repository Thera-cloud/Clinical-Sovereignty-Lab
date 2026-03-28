"""
SDH (Septuplicate-Dodecahedron-Helix) Context Compressor.

Core innovation: takes raw context data and helix/ODPE output, applies dodecahedron
12-face topological filtering, and produces a condensed ~800-1024 token context block.

Each face validates against its 5 pentagonal neighbors (dodecahedron adjacency).
A face signal is validated if at least 2 of its 5 neighbors have non-zero confidence.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── 12 Dodecahedron Faces (cognitive dimensions) ─────────────────────────────
# Face IDs 1-12 per spec; each face has exactly 5 neighbors (dodecahedron topology)

FACE_DIMENSIONS: Dict[int, str] = {
    1: "Emotional",      # C_emo, voice biometrics, affect keywords
    2: "Relational",     # Family context, coach relationship, attachment
    3: "Temporal",       # Session frequency, time patterns, duration
    4: "Contextual",     # Current situation triggers, environment
    5: "Somatic",        # Physical manifestation patterns from biometrics
    6: "Behavioral",     # Coping strategies, action patterns from history
    7: "Cognitive",      # Thought patterns, schemas from crystals
    8: "Developmental",  # Growth trajectory from longitudinal data
    9: "Systemic",       # Family/group dynamics from family context
    10: "Cultural",      # Values, identity context from profile
    11: "Historical",    # Past conversation references, compressed history
    12: "Coherence",     # C_emo trajectory, ODPE oscillation state
}

# Dodecahedron face adjacency: each face (1-12) has exactly 5 neighbors
# Derived from standard dodecahedral graph; 1-indexed to match FACE_DIMENSIONS
DODECAHEDRON_ADJACENCY: Dict[int, List[int]] = {
    1: [2, 3, 4, 5, 6],
    2: [1, 3, 7, 11, 12],
    3: [1, 2, 4, 8, 12],
    4: [1, 3, 5, 8, 9],
    5: [1, 4, 6, 9, 10],
    6: [1, 2, 5, 7, 10],
    7: [2, 6, 8, 11, 12],
    8: [3, 4, 7, 9, 11],
    9: [4, 5, 8, 10, 11],
    10: [5, 6, 9, 11, 12],
    11: [2, 7, 9, 10, 12],
    12: [2, 3, 7, 8, 10],
}

# Keys in raw_context to check per face (extraction hints)
FACE_INPUT_KEYS: Dict[int, List[str]] = {
    1: ["c_emo", "affect", "emotion", "biometrics", "voice_biometrics", "emotional"],
    2: ["family", "relational", "coach_relationship", "attachment", "assigned_coach"],
    3: ["session_frequency", "time_patterns", "duration", "temporal"],
    4: ["situation", "triggers", "environment", "contextual"],
    5: ["somatic", "physical", "biometrics", "physical_manifestation"],
    6: ["coping", "actions", "behavioral", "patterns", "action_patterns"],
    7: ["crystals", "wisdom", "thought_patterns", "cognitive", "schemas"],
    8: ["developmental", "growth", "trajectory", "longitudinal"],
    9: ["family_dynamics", "systemic", "group", "group_dynamics"],
    10: ["values", "identity", "cultural", "cultural_context"],
    11: ["conversation", "history", "past_sessions", "compressed_history"],
    12: ["c_emo_trajectory", "coherence", "odpe", "oscillation"],
}

# Model-aware budgets (from Qwen2.5 plan)
MODEL_BUDGETS: Dict[str, tuple] = {
    "llama3.1:8b": (350, 500),           # 8B: aggressive compression
    "llama3.1:8b-instruct-q4_K_M": (350, 500),
    "qwen2.5:14b": (500, 700),           # 14B: moderate compression
    "qwen2.5:14b-instruct-q4_K_M": (500, 700),
    "qwen2.5:32b": (700, 1000),          # 32B: minimal compression
    "qwen2.5:32b-instruct-q4_K_M": (700, 1000),
    "default": (500, 800),
}


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class FaceSignal:
    """Extracted signal for a single dodecahedron face."""
    face_id: int
    dimension: str
    content: str
    confidence: float  # 0.0–1.0
    token_count: int


@dataclass
class SDHContextBlock:
    """Compressed context block output from SDH compressor."""
    compressed_context: str
    face_confidences: Dict[int, float]
    compression_ratio: float
    odpe_signal: str
    inference_tier: str
    conversation_state_hash: str
    timestamp: float
    target_model: str = "llama3.1:8b"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SDHContextBlock":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── SDH Context Compressor ───────────────────────────────────────────────────

class SDHContextCompressor:
    """
    12-face dodecahedron topological context compressor.
    Extracts, validates (5-neighbor corroboration), and condenses context.
    """

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: words × 1.3."""
        if not text or not text.strip():
            return 0
        words = len(text.split())
        return max(1, int(words * 1.3))

    def _extract_face_signals(
        self,
        face_id: int,
        raw_context: Dict[str, Any],
        helix_result: Any,
        profile: Dict,
        conversation_history: List[Dict],
    ) -> FaceSignal:
        """Extract relevant content for a single face from raw context."""
        dimension = FACE_DIMENSIONS.get(face_id, "unknown")
        content_parts: List[str] = []
        confidence = 0.0

        keys = FACE_INPUT_KEYS.get(face_id, [])
        for key in keys:
            val = raw_context.get(key) or profile.get(key)
            if val is None:
                continue
            text = str(val).strip()
            if text:
                # Limit per-field length for condensation
                content_parts.append(text[:400])
                # Confidence increases with content length and specificity
                confidence = min(1.0, confidence + 0.15 + len(text) / 500.0)

        # Face 1 (Emotional): also pull C_emo and ODPE from helix
        if face_id == 1 and helix_result:
            c_emo = getattr(helix_result, "c_emo_value", None)
            if c_emo is not None:
                content_parts.append(f"C_emo={float(c_emo):.3f}")
                confidence = min(1.0, confidence + 0.2)
            odpe = _get_odpe(helix_result)
            if odpe:
                sig = _odpe_get(odpe, "signal")
                if sig:
                    content_parts.append(f"ODPE={sig}")
                    confidence = min(1.0, confidence + 0.1)

        # Face 12 (Coherence): ODPE state, amplitudes
        if face_id == 12 and helix_result:
            odpe = _get_odpe(helix_result)
            if odpe:
                sig = _odpe_get(odpe, "signal")
                dodec = _odpe_get(odpe, "dodec_amplitude", 0.0)
                icosi = _odpe_get(odpe, "icosi_amplitude", 0.0)
                content_parts.append(f"signal={sig} dodec={dodec:.2f} icosi={icosi:.2f}")
                confidence = min(1.0, confidence + 0.3)

        # Face 2 (Relational): profile coach/family
        if face_id == 2:
            coach = profile.get("assigned_coach") or profile.get("coach_id")
            family_id = profile.get("family_id")
            if coach:
                content_parts.append(f"coach={coach}")
                confidence = min(1.0, confidence + 0.15)
            if family_id:
                content_parts.append(f"family_id={family_id}")
                confidence = min(1.0, confidence + 0.1)

        # Face 11 (Historical): compress recent conversation
        if face_id == 11 and conversation_history:
            recent = conversation_history[-5:]
            for entry in recent:
                msg = entry.get("message") or entry.get("user_text") or ""
                if msg:
                    content_parts.append(str(msg)[:120])
            if recent:
                confidence = min(1.0, confidence + 0.2)

        content = " | ".join(content_parts) if content_parts else ""
        token_count = self._estimate_tokens(content)
        if content and confidence == 0:
            confidence = min(1.0, 0.2 + token_count / 300.0)

        return FaceSignal(
            face_id=face_id,
            dimension=dimension,
            content=content,
            confidence=confidence,
            token_count=token_count,
        )

    def _validate_neighbors(
        self, face_signals: Dict[int, FaceSignal]
    ) -> Dict[int, FaceSignal]:
        """
        5-neighbor validation: a face signal is validated if at least 2 of its
        5 neighbors also have non-zero confidence (corroborating evidence).
        Returns only validated faces with confidence preserved.
        """
        validated: Dict[int, FaceSignal] = {}
        for face_id, signal in face_signals.items():
            if signal.confidence <= 0 or not signal.content.strip():
                validated[face_id] = FaceSignal(
                    face_id=face_id,
                    dimension=signal.dimension,
                    content="",
                    confidence=0.0,
                    token_count=0,
                )
                continue

            neighbors = DODECAHEDRON_ADJACENCY.get(face_id, [])
            corroborating = sum(
                1 for n in neighbors
                if face_signals.get(n) and face_signals[n].confidence > 0
            )
            if corroborating >= 2:
                validated[face_id] = signal
            else:
                validated[face_id] = FaceSignal(
                    face_id=face_id,
                    dimension=signal.dimension,
                    content="",
                    confidence=0.0,
                    token_count=0,
                )
        return validated

    def _condense(
        self, validated: Dict[int, FaceSignal], target_tokens: int
    ) -> str:
        """
        Sort validated faces by confidence descending, allocate tokens proportionally,
        concatenate with [FACE_NAME] headers, truncate to target budget.
        """
        ranked = sorted(
            [s for s in validated.values() if s.content],
            key=lambda s: s.confidence,
            reverse=True,
        )
        if not ranked:
            return ""

        total_conf = sum(s.confidence for s in ranked)
        if total_conf <= 0:
            return ""

        sections: List[str] = []
        tokens_used = 0
        for sig in ranked:
            share = sig.confidence / total_conf
            budget = int(target_tokens * share)
            budget = max(20, min(budget, sig.token_count + 10))
            if tokens_used + budget > target_tokens:
                remaining = target_tokens - tokens_used
                if remaining > 15:
                    max_words = max(1, int(remaining / 1.3))
                    words = sig.content.split()[:max_words]
                    excerpt = " ".join(words)
                    sections.append(f"[{sig.dimension.upper()}] {excerpt}")
                break
            words = sig.content.split()
            token_limit = max(1, int((budget - 10) / 1.3))  # reserve for [HEADER], words→tokens
            excerpt = " ".join(words[:token_limit]) if words else ""
            sections.append(f"[{sig.dimension.upper()}] {excerpt}")
            tokens_used += self._estimate_tokens(sections[-1])

        result = "\n".join(sections)
        while self._estimate_tokens(result) > target_tokens and len(sections) > 1:
            sections.pop()
            result = "\n".join(sections)
        return result

    async def compress(
        self,
        user_id: str,
        helix_result: Any,
        raw_context: Dict[str, Any],
        conversation_history: List[Dict],
        profile: Dict,
        target_tokens: int = 800,
        target_model: str = "llama3.1:8b",
    ) -> SDHContextBlock:
        """
        Compress raw context through 12-face dodecahedron topology.
        Returns validated, condensed context block.
        """
        start = time.monotonic()

        budget = MODEL_BUDGETS.get(target_model, MODEL_BUDGETS["default"])
        effective_target = max(budget[0], min(target_tokens, budget[1]))

        face_signals: Dict[int, FaceSignal] = {}
        for face_id in range(1, 13):
            face_signals[face_id] = self._extract_face_signals(
                face_id, raw_context, helix_result, profile, conversation_history
            )

        validated = self._validate_neighbors(face_signals)
        compressed = self._condense(validated, effective_target)

        odpe_signal = "PROVISIONAL"
        inference_tier = "clinical"
        rec_tokens = effective_target
        if helix_result:
            rec_tokens = getattr(helix_result, "recommended_context_tokens", rec_tokens) or rec_tokens
            odpe = _get_odpe(helix_result)
            if odpe:
                sig = _odpe_get(odpe, "signal")
                if sig:
                    odpe_signal = sig if isinstance(sig, str) else getattr(sig, "value", str(sig))
                inference_tier = _odpe_get(odpe, "recommended_inference_tier", inference_tier) or inference_tier

        input_tokens = sum(
            self._estimate_tokens(str(v))
            for v in raw_context.values()
            if v is not None and isinstance(v, (str, list, dict))
        )
        input_tokens += sum(
            self._estimate_tokens(str(h.get("message", h.get("user_text", ""))))
            for h in conversation_history[:20]
        )
        output_tokens = self._estimate_tokens(compressed)
        ratio = input_tokens / max(output_tokens, 1)

        state_hash = self._compute_state_hash(user_id, conversation_history)

        elapsed = time.monotonic() - start
        logger.debug(
            "SDH compress: %d -> %d tokens (%.1fx) in %.0fms",
            input_tokens, output_tokens, ratio, elapsed * 1000,
        )

        return SDHContextBlock(
            compressed_context=compressed,
            face_confidences={fid: s.confidence for fid, s in validated.items()},
            compression_ratio=ratio,
            odpe_signal=odpe_signal,
            inference_tier=inference_tier,
            conversation_state_hash=state_hash,
            timestamp=time.time(),
            target_model=target_model,
        )

    def _compute_state_hash(
        self, user_id: str, conversation_history: List[Dict]
    ) -> str:
        """Compute hash for cache keying."""
        last_msg = ""
        if conversation_history:
            entry = conversation_history[-1]
            last_msg = str(entry.get("message", entry.get("user_text", "")))
        raw = f"{user_id}:{last_msg}:{len(conversation_history)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _compute_state_hash_static(user_id: str, user_text: str) -> str:
        """Lightweight hash for prefetch hit checking (no conversation list needed)."""
        raw = f"{user_id}:{user_text}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_odpe(helix_result: Any) -> Any:
    """Extract odpe_result from helix; handle both dict and object."""
    odpe = getattr(helix_result, "odpe_result", None)
    if odpe is None:
        return None
    return odpe


def _odpe_get(odpe: Any, key: str, default: Any = None) -> Any:
    """Get value from odpe_result whether it's a dict or object."""
    if odpe is None:
        return default
    if isinstance(odpe, dict):
        return odpe.get(key, default)
    return getattr(odpe, key, default)
