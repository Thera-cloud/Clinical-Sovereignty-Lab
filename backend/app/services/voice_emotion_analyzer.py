"""
Voice Emotion Analyzer - Detect emotion from session audio.

Analyzes audio in fixed segments and produces an emotion timeline
that can be aligned with a transcript so coaches see WHAT was said
and HOW it was said.

Two modes (auto-selected, never raises on missing libs):
  1. "transformer": ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition
                    via transformers + torchaudio (CPU). Detects:
                    angry, sad, fear, happy, neutral, disgust, surprise, calm.
  2. "librosa":     Lightweight feature-based fallback using librosa
                    (energy, zero-crossing-rate, spectral centroid, MFCC).

Usage:
    analyzer = VoiceEmotionAnalyzer()
    if analyzer.available:
        result = await analyzer.analyze_audio("/tmp/session.wav", segment_seconds=10)
        aligned = analyzer.align_with_transcript(result["emotion_timeline"], vtt_entries)
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from typing import Any, Dict, List, Optional


# Module-level capability gates (cheap probes; do NOT load models here)
_HAS_TRANSFORMERS = False
_HAS_TORCHAUDIO = False
_HAS_LIBROSA = False
try:
    import transformers as _t  # noqa: F401
    _HAS_TRANSFORMERS = True
except Exception:
    pass
try:
    import torchaudio as _ta  # noqa: F401
    _HAS_TORCHAUDIO = True
except Exception:
    pass
try:
    import librosa as _lr  # noqa: F401
    _HAS_LIBROSA = True
except Exception:
    pass


def _force_librosa_only() -> bool:
    """
    GREEN cannot afford to load wav2vec2 (~1.5 GB) inside the FastAPI
    container. When VOICE_EMOTION_FORCE_LIBROSA=1 (set by docker-compose
    on the GREEN node, or by classroom_remote_dispatch when no ORANGE
    voice endpoint is configured), the analyzer never enters transformer
    mode — it stays in librosa rule-based mode regardless of capability.
    See `.cursor/rules/three-node-sync-discipline.mdc` for routing.
    """
    flag = (os.getenv("VOICE_EMOTION_FORCE_LIBROSA", "") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


# Normalize labels emitted by the upstream wav2vec2 model.
_LABEL_ALIASES = {
    "ang": "angry",
    "anger": "angry",
    "sad": "sad",
    "sadness": "sad",
    "hap": "happy",
    "happiness": "happy",
    "joy": "happy",
    "fea": "fear",
    "fearful": "fear",
    "neu": "neutral",
    "neutral": "neutral",
    "dis": "disgust",
    "sur": "surprise",
    "surprised": "surprise",
    "cal": "calm",
}


def _normalize_label(label: str) -> str:
    if not label:
        return "neutral"
    key = str(label).strip().lower()
    return _LABEL_ALIASES.get(key, key)


class VoiceEmotionAnalyzer:
    """
    Analyzes voice for emotional content using either a pre-trained
    wav2vec2 transformer model or a librosa rule-based fallback.

    The transformer model is lazy-loaded on first analyze call so module
    import stays cheap and the backend never blocks at startup.
    """

    TRANSFORMER_MODEL_ID = (
        "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"
    )

    def __init__(self):
        self._model = None
        self._model_load_attempted = False
        if _force_librosa_only():
            self._mode = "librosa" if _HAS_LIBROSA else None
        elif _HAS_TRANSFORMERS and _HAS_TORCHAUDIO:
            self._mode = "transformer"
        elif _HAS_LIBROSA:
            self._mode = "librosa"
        else:
            self._mode = None

    @property
    def available(self) -> bool:
        return self._mode is not None

    @property
    def mode(self) -> Optional[str]:
        return self._mode

    def _load_transformer(self) -> bool:
        """Lazy-load wav2vec2 pipeline. Falls back to librosa on failure."""
        if self._model is not None:
            return True
        if self._model_load_attempted:
            return self._model is not None
        self._model_load_attempted = True
        try:
            from transformers import pipeline
            self._model = pipeline(
                "audio-classification",
                model=self.TRANSFORMER_MODEL_ID,
                device=-1,  # CPU
            )
            return True
        except Exception as e:
            print(f"[VoiceEmotion] transformer load failed, falling back: {e}")
            self._model = None
            if _HAS_LIBROSA:
                self._mode = "librosa"
            else:
                self._mode = None
            return False

    async def analyze_audio(
        self,
        audio_path: str,
        segment_seconds: int = 10,
    ) -> Dict[str, Any]:
        """
        Analyze audio file in fixed segments. Returns timeline + summary.
        Heavy work is offloaded to a worker thread to avoid blocking the
        asyncio loop.
        """
        if not self.available:
            return {"error": "no voice analysis available"}

        if self._mode == "transformer":
            if not self._load_transformer():
                if self._mode != "librosa":
                    return {"error": "voice analysis init failed"}
            else:
                return await asyncio.to_thread(
                    self._analyze_transformer_sync, audio_path, segment_seconds
                )

        if self._mode == "librosa":
            return await asyncio.to_thread(
                self._analyze_librosa_sync, audio_path, segment_seconds
            )

        return {"error": "no voice analysis available"}

    # ---------------- Transformer mode ----------------

    def _analyze_transformer_sync(
        self, audio_path: str, seg_sec: int
    ) -> Dict[str, Any]:
        # Audio I/O strategy:
        #   torchaudio 2.x dropped its native loaders and now requires
        #   `torchcodec`, which has fragile ARM64 wheels (see ORANGE
        #   deployment Apr 2026). librosa.load is the portable path and
        #   produces exactly the float32 numpy array the transformers
        #   pipeline wants — no torch tensors needed for inference.
        try:
            import numpy as np  # noqa: F401
        except Exception as e:
            return {"error": f"numpy unavailable: {e}"}

        sr = 16000  # wav2vec2 expects 16 kHz mono
        waveform_np = None

        try:
            import librosa
            waveform_np, sr = librosa.load(audio_path, sr=sr, mono=True)
        except Exception as librosa_err:
            try:
                import torchaudio
                import torchaudio.transforms as T
                waveform, native_sr = torchaudio.load(audio_path)
                if native_sr != sr:
                    waveform = T.Resample(native_sr, sr)(waveform)
                if waveform.dim() > 1 and waveform.shape[0] > 1:
                    waveform = waveform.mean(dim=0)
                else:
                    waveform = waveform.squeeze(0)
                waveform_np = waveform.numpy()
            except Exception as torch_err:
                return {
                    "error": (
                        f"audio load failed (librosa: {librosa_err}; "
                        f"torchaudio: {torch_err})"
                    )
                }

        if waveform_np is None or waveform_np.size == 0:
            return {"error": "audio load returned empty waveform"}

        segment_samples = max(1, int(seg_sec * sr))
        total_samples = int(waveform_np.shape[0])

        timeline: List[Dict[str, Any]] = []
        for start in range(0, total_samples, segment_samples):
            end = min(start + segment_samples, total_samples)
            segment = waveform_np[start:end]

            if len(segment) < sr:  # skip < 1s tail
                continue

            try:
                results = self._model(
                    {"raw": segment, "sampling_rate": sr}, top_k=3
                )
            except Exception:
                # Some pipeline versions accept the array directly.
                try:
                    results = self._model(segment, top_k=3)
                except Exception as e:
                    print(f"[VoiceEmotion] inference failed @ {start/sr:.1f}s: {e}")
                    continue

            if not results:
                continue

            primary = _normalize_label(results[0].get("label", "neutral"))
            timeline.append({
                "timestamp": round(start / sr, 1),
                "duration": round((end - start) / sr, 1),
                "primary_emotion": primary,
                "confidence": round(float(results[0].get("score", 0.0)), 3),
                "all_emotions": {
                    _normalize_label(r.get("label", "")):
                        round(float(r.get("score", 0.0)), 3)
                    for r in results
                },
            })

        return self._build_result(timeline, mode="transformer")

    # ---------------- Librosa fallback ----------------

    def _analyze_librosa_sync(
        self, audio_path: str, seg_sec: int
    ) -> Dict[str, Any]:
        try:
            import librosa
            import numpy as np
        except Exception as e:
            return {"error": f"librosa unavailable: {e}"}

        try:
            y, sr = librosa.load(audio_path, sr=22050, mono=True)
        except Exception as e:
            return {"error": f"audio load failed: {e}"}

        segment_samples = max(1, int(seg_sec * sr))
        timeline: List[Dict[str, Any]] = []

        for start in range(0, len(y), segment_samples):
            end = min(start + segment_samples, len(y))
            segment = y[start:end]
            if len(segment) < sr:
                continue

            try:
                rms = float(np.mean(librosa.feature.rms(y=segment)))
                zcr = float(np.mean(
                    librosa.feature.zero_crossing_rate(segment)
                ))
                centroid = float(np.mean(
                    librosa.feature.spectral_centroid(y=segment, sr=sr)
                ))
                mfcc = librosa.feature.mfcc(y=segment, sr=sr, n_mfcc=13)
                mfcc_mean = [float(m) for m in np.mean(mfcc, axis=1)]
            except Exception as e:
                print(f"[VoiceEmotion] librosa feature error @ {start/sr:.1f}s: {e}")
                continue

            emotion = self._infer_from_features(rms, zcr, centroid, mfcc_mean)
            timeline.append({
                "timestamp": round(start / sr, 1),
                "duration": round((end - start) / sr, 1),
                "primary_emotion": emotion,
                "confidence": 0.5,  # rule-based = lower confidence
                "features": {
                    "energy": round(rms, 4),
                    "speech_rate_proxy": round(zcr, 4),
                    "pitch_proxy": round(centroid, 1),
                },
            })

        return self._build_result(timeline, mode="librosa_rules")

    @staticmethod
    def _infer_from_features(
        rms: float, zcr: float, centroid: float, mfcc: List[float]
    ) -> str:
        if rms < 0.01:
            return "silence"
        if rms > 0.10 and centroid > 3000:
            return "angry"
        if rms < 0.03 and centroid < 1500:
            return "sad"
        if zcr > 0.15 and rms > 0.05:
            return "fear"
        if rms > 0.05 and 2000 < centroid < 3000:
            return "happy"
        return "neutral"

    # ---------------- Result aggregation ----------------

    @staticmethod
    def _build_result(
        timeline: List[Dict[str, Any]],
        mode: str,
    ) -> Dict[str, Any]:
        if not timeline:
            return {
                "segments_analyzed": 0,
                "emotion_timeline": [],
                "emotion_distribution": {},
                "dominant_emotion": "neutral",
                "emotional_shifts": [],
                "shift_count": 0,
                "patterns": [],
                "analysis_mode": mode,
            }

        emotions = [
            t["primary_emotion"] for t in timeline
            if t["primary_emotion"] != "silence"
        ]
        counts = Counter(emotions)
        dominant = counts.most_common(1)[0][0] if counts else "neutral"

        shifts: List[Dict[str, Any]] = []
        for i in range(1, len(timeline)):
            prev = timeline[i - 1]["primary_emotion"]
            curr = timeline[i]["primary_emotion"]
            if prev != curr and prev != "silence" and curr != "silence":
                shifts.append({
                    "timestamp": timeline[i]["timestamp"],
                    "from": prev,
                    "to": curr,
                })

        total = max(1, len(emotions))
        patterns: List[str] = []
        if counts.get("sad", 0) / total > 0.3:
            patterns.append("sustained sadness detected in voice")
        if counts.get("fear", 0) / total > 0.25:
            patterns.append("recurring fear/anxiety markers in speech")
        if counts.get("angry", 0) / total > 0.2:
            patterns.append("anger expression in vocal tone")
        if counts.get("disgust", 0) / total > 0.15:
            patterns.append("disgust register present in voice")
        if len(shifts) > len(timeline) * 0.4:
            patterns.append(
                "high emotional volatility — rapid shifts between states"
            )

        return {
            "segments_analyzed": len(timeline),
            "emotion_timeline": timeline,
            "emotion_distribution": dict(counts),
            "dominant_emotion": dominant,
            "emotional_shifts": shifts,
            "shift_count": len(shifts),
            "patterns": patterns,
            "analysis_mode": mode,
        }

    # ---------------- Transcript alignment ----------------

    @staticmethod
    def align_with_transcript(
        timeline: List[Dict[str, Any]],
        vtt_entries: List[Any],
    ) -> List[Dict[str, Any]]:
        """
        Build aligned (text, voice_emotion) entries.

        For each transcript entry, find the emotion segment whose window
        contains the midpoint of the utterance. This surfaces incongruence
        — e.g. text says "I'm fine" while voice reads "sad".

        vtt_entries: iterable of objects with .start_time, .end_time,
                     .speaker, .text (matches VTTEntry dataclass) OR dicts
                     with the same keys.
        """
        if not timeline or not vtt_entries:
            return []

        def _seg_for(ts: float) -> Optional[Dict[str, Any]]:
            for seg in timeline:
                start = float(seg.get("timestamp", 0.0))
                end = start + float(seg.get("duration", 0.0))
                if start <= ts < end:
                    return seg
            return None

        aligned: List[Dict[str, Any]] = []
        for e in vtt_entries:
            if hasattr(e, "start_time"):
                start = float(e.start_time)
                end = float(e.end_time)
                speaker = e.speaker
                text = e.text
            elif isinstance(e, dict):
                start = float(e.get("start_time", 0.0))
                end = float(e.get("end_time", start))
                speaker = e.get("speaker", "Unknown")
                text = e.get("text", "")
            else:
                continue

            mid = (start + end) / 2.0
            seg = _seg_for(mid) or _seg_for(start)
            if not seg:
                continue

            aligned.append({
                "timestamp": round(start, 1),
                "speaker": speaker,
                "text": text,
                "voice_emotion": seg.get("primary_emotion", "neutral"),
                "confidence": seg.get("confidence", 0.0),
            })

        return aligned
