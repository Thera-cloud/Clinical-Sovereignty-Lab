"""
Multi-Modal Fusion Engine — combine text sentiment, voice emotion, and
facial expression into a unified emotional state per moment.

Fuses three modality timelines by timestamp, surfaces incongruence
moments (verbal/nonverbal disagreement), computes session arc, and
extracts therapeutically significant clinical flags.

PII / clinical safety:
- Operates only on already-extracted aggregate signals
  (no raw audio, no face images, no embeddings).
- All output is therapeutic context only — must be combined with the
  coach's clinical judgment.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_TEXT_POSITIVE = {"positive", "happy", "fine", "calm", "engaged", "ok", "okay"}
_TEXT_NEGATIVE = {"negative", "sad", "angry", "fearful", "anxious", "ashamed"}

_NEGATIVE_VOICE = {"sad", "angry", "anxious", "fearful", "fear", "disgust"}
_AVERTED_GAZE = {"averted_left", "averted_right", "down"}
_WITHDRAWN_STATES = {"withdrawn", "avoidant", "distressed"}


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class MultiModalFusionEngine:
    """
    Combines text, voice, and facial signals into a unified emotional
    state assessment per moment.
    """

    def fuse_session_analysis(
        self,
        transcript_segments: List[Dict[str, Any]],
        voice_timeline: List[Dict[str, Any]],
        facial_timeline: List[Dict[str, Any]],
        alignment_tolerance_seconds: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Align all three modalities by timestamp and produce a unified
        emotional state per moment.
        """
        unified_timeline: List[Dict[str, Any]] = []

        for text_seg in transcript_segments or []:
            ts = _to_float(text_seg.get("timestamp", 0))

            voice = self._find_nearest(
                voice_timeline, ts, alignment_tolerance_seconds
            )
            facial = self._find_nearest(
                facial_timeline, ts, alignment_tolerance_seconds
            )

            unified = {
                "timestamp": ts,
                "speaker": text_seg.get("speaker", ""),
                "text": text_seg.get("text", ""),
                "text_sentiment": text_seg.get("sentiment", "neutral"),
                "voice_emotion": (
                    voice.get("primary_emotion", "unknown")
                    if voice else "unknown"
                ),
                "voice_confidence": (
                    _to_float(voice.get("confidence", 0))
                    if voice else 0.0
                ),
                "facial_emotion": (
                    facial.get("emotional_inference", "unknown")
                    if facial else "unknown"
                ),
                "gaze": (
                    facial.get("gaze_direction", "unknown")
                    if facial else "unknown"
                ),
                "unified_state": self._compute_unified_state(
                    text_seg, voice, facial
                ),
                "incongruence": self._detect_incongruence(
                    text_seg, voice, facial
                ),
            }
            unified_timeline.append(unified)

        return {
            "unified_timeline": unified_timeline,
            "incongruence_moments": [
                u for u in unified_timeline if u["incongruence"]
            ],
            "session_arc": self._compute_session_arc(unified_timeline),
            "clinical_flags": self._extract_clinical_flags(unified_timeline),
            "modalities_present": {
                "text": bool(transcript_segments),
                "voice": bool(voice_timeline),
                "facial": bool(facial_timeline),
            },
        }

    # ------------------------------------------------------------------
    # Alignment
    # ------------------------------------------------------------------

    @staticmethod
    def _find_nearest(
        timeline: List[Dict[str, Any]],
        target_ts: float,
        tolerance: float,
    ) -> Optional[Dict[str, Any]]:
        if not timeline:
            return None
        best: Optional[Dict[str, Any]] = None
        best_delta = tolerance
        for seg in timeline:
            seg_ts = _to_float(seg.get("timestamp", 0))
            delta = abs(seg_ts - target_ts)
            if delta <= best_delta:
                best = seg
                best_delta = delta
        return best

    # ------------------------------------------------------------------
    # Unified state + incongruence
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_unified_state(
        text: Dict[str, Any],
        voice: Optional[Dict[str, Any]],
        facial: Optional[Dict[str, Any]],
    ) -> str:
        """
        Weighted fusion. Voice (~0.40) is most reliable for emotion,
        facial (~0.35) second, text (~0.25) least reliable for emotion
        (but most reliable for content).
        """
        states: List[str] = []
        if voice:
            ve = str(voice.get("primary_emotion", "")).strip().lower()
            if ve and ve not in ("silence", "unknown", "neutral"):
                # voice carries higher weight → counted twice
                states.append(ve)
                states.append(ve)
        if facial:
            fe = str(facial.get("emotional_inference", "")).strip().lower()
            if fe and fe not in ("no_face", "unknown", "neutral"):
                states.append(fe)
                states.append(fe)
        text_sent = str(text.get("sentiment", "")).strip().lower()
        if text_sent and text_sent not in ("unknown", ""):
            states.append(text_sent)

        if not states:
            return text_sent or "neutral"
        return Counter(states).most_common(1)[0][0]

    @staticmethod
    def _detect_incongruence(
        text: Dict[str, Any],
        voice: Optional[Dict[str, Any]],
        facial: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Detect when modalities disagree — therapeutically significant.

        Example: "I'm fine" (positive text) + sad voice + averted gaze
        = incongruence = clinical flag.
        """
        text_sent = str(text.get("sentiment", "")).strip().lower()
        text_positive = text_sent in _TEXT_POSITIVE
        voice_emotion = (
            str(voice.get("primary_emotion", "")).strip().lower()
            if voice else ""
        )
        voice_negative = voice_emotion in _NEGATIVE_VOICE
        gaze = (
            str(facial.get("gaze_direction", "")).strip().lower()
            if facial else ""
        )
        gaze_averted = gaze in _AVERTED_GAZE

        if text_positive and (voice_negative or gaze_averted):
            return {
                "type": "positive_text_negative_nonverbal",
                "text": text.get("text", ""),
                "voice": voice_emotion or None,
                "gaze": gaze or None,
                "clinical_note": (
                    "Client verbally reports well-being but nonverbal "
                    "signals suggest distress"
                ),
            }
        return None

    # ------------------------------------------------------------------
    # Session arc + flags
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_session_arc(
        timeline: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if len(timeline) < 3:
            return {"arc": "insufficient_data"}

        third = max(1, len(timeline) // 3)
        opening = timeline[:third]
        middle = timeline[third:2 * third]
        closing = timeline[2 * third:]

        def dominant(segment: List[Dict[str, Any]]) -> str:
            states = [t.get("unified_state", "neutral") for t in segment]
            c = Counter(states)
            return c.most_common(1)[0][0] if c else "neutral"

        op = dominant(opening)
        mi = dominant(middle)
        cl = dominant(closing)
        return {
            "opening": op,
            "middle": mi,
            "closing": cl,
            "arc_description": f"{op} → {mi} → {cl}",
        }

    @staticmethod
    def _extract_clinical_flags(
        timeline: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        flags: List[Dict[str, Any]] = []
        if not timeline:
            return flags

        incongruent = [t for t in timeline if t.get("incongruence")]
        if len(incongruent) > 2:
            flags.append({
                "flag": "REPEATED_INCONGRUENCE",
                "count": len(incongruent),
                "clinical_note": (
                    "Client shows repeated disconnect between verbal and "
                    "nonverbal expression — possible masking, shame, or "
                    "alexithymia"
                ),
                "severity": "medium" if len(incongruent) < 5 else "high",
            })

        withdrawn = [
            t for t in timeline
            if str(t.get("unified_state", "")).lower() in _WITHDRAWN_STATES
        ]
        if len(withdrawn) > len(timeline) * 0.3:
            flags.append({
                "flag": "SUSTAINED_WITHDRAWAL",
                "ratio": round(len(withdrawn) / len(timeline), 2),
                "clinical_note": (
                    "Client shows sustained withdrawal pattern — possible "
                    "dissociation or freeze response"
                ),
                "severity": "high",
            })

        gaze_averted = [
            t for t in timeline
            if str(t.get("gaze", "")).lower() in _AVERTED_GAZE
        ]
        if len(gaze_averted) > len(timeline) * 0.5:
            flags.append({
                "flag": "PERSISTENT_GAZE_AVERSION",
                "ratio": round(len(gaze_averted) / len(timeline), 2),
                "clinical_note": (
                    "Persistent gaze aversion may indicate shame, guilt, "
                    "or difficulty with attachment"
                ),
                "severity": "medium",
            })

        return flags


# ----------------------------------------------------------------------
# Helper: build transcript segments with rough sentiment from VTT
# ----------------------------------------------------------------------

_POS_LEXICON = {
    "fine", "good", "great", "happy", "ok", "okay", "well", "calm",
    "better", "love", "thanks", "grateful", "hopeful", "joy", "safe",
    "proud", "excited", "peaceful",
}
_NEG_LEXICON = {
    "sad", "angry", "anxious", "scared", "afraid", "hurt", "ashamed",
    "guilt", "guilty", "tired", "exhausted", "broken", "lost", "alone",
    "stuck", "hate", "depressed", "hopeless", "worthless", "numb",
    "trapped", "confused", "overwhelmed",
}


def quick_sentiment(text: str) -> str:
    """Lightweight bag-of-words sentiment used when no NLP model is wired."""
    if not text:
        return "neutral"
    tokens = {w.strip(".,!?;:'\"()").lower() for w in text.split()}
    pos_hits = len(tokens & _POS_LEXICON)
    neg_hits = len(tokens & _NEG_LEXICON)
    if pos_hits and pos_hits >= neg_hits + 1:
        return "positive"
    if neg_hits and neg_hits >= pos_hits + 1:
        return "negative"
    return "neutral"


def transcript_segments_from_vtt(
    vtt_entries: List[Any],
    client_speaker_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Convert parsed VTT entries (objects with start_time/end_time/speaker/text
    or dicts with same keys) into transcript_segments suitable for
    MultiModalFusionEngine. Emits a quick lexicon-based sentiment.

    If client_speaker_hint is provided, only that speaker's utterances are
    kept (common case: we want to fuse the *client's* signal, not the coach).
    """
    segments: List[Dict[str, Any]] = []
    for e in vtt_entries or []:
        if hasattr(e, "start_time"):
            start = _to_float(getattr(e, "start_time", 0))
            end = _to_float(getattr(e, "end_time", start))
            speaker = str(getattr(e, "speaker", "") or "")
            text = str(getattr(e, "text", "") or "")
        elif isinstance(e, dict):
            start = _to_float(e.get("start_time", e.get("timestamp", 0)))
            end = _to_float(e.get("end_time", start))
            speaker = str(e.get("speaker", "") or "")
            text = str(e.get("text", "") or "")
        else:
            continue
        if client_speaker_hint and speaker:
            if client_speaker_hint.lower() not in speaker.lower():
                continue
        if not text.strip():
            continue
        midpoint = (start + end) / 2.0 if end >= start else start
        segments.append({
            "timestamp": round(midpoint, 1),
            "start_time": round(start, 1),
            "end_time": round(end, 1),
            "speaker": speaker,
            "text": text,
            "sentiment": quick_sentiment(text),
        })
    return segments


def create_multimodal_fusion_engine() -> MultiModalFusionEngine:
    """Factory used by classroom_analyzer."""
    return MultiModalFusionEngine()
