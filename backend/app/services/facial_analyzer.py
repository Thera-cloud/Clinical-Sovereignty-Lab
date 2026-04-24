"""
Facial Analyzer — Classroom video session facial expression / body language

Uses MediaPipe FaceMesh (468 landmarks + iris) on sampled frames from an
uploaded session video to estimate:

- gaze direction (direct / averted / down)
- expression indicators (brow raise, brow furrow, smile, lip press,
  eye squeeze, jaw drop)
- emotional inference (engaged, anxious, distressed, withdrawn,
  surprised, attentive, neutral)
- head pose proxy (pitch / yaw)

All processing runs in a worker thread so it never blocks the FastAPI
event loop. Module is import-safe even when opencv / mediapipe are not
installed (Dockerfile rebuild required to enable analysis).

Dependencies (declared in backend/requirements.txt):
- opencv-python-headless==4.9.0.80
- mediapipe==0.10.11

PII / clinical safety:
- Operates only on locally-stored uploaded session video frames.
- Returns aggregate / numeric indicators only — no face images,
  no embeddings, no identity inference.
- Output is therapeutic context only and must be combined with the
  coach's clinical judgment.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FacialAnalyzer:
    """
    Analyzes facial expressions and body language from video frames using
    MediaPipe. Heavy CPU work runs in a thread executor so callers can
    `await analyze_video_frames(...)` from an async context safely.
    """

    def __init__(self) -> None:
        self._available: bool = False
        self.cv2: Any = None
        self.mp: Any = None
        self.face_mesh: Any = None
        try:
            import cv2  # type: ignore
            import mediapipe as mp  # type: ignore

            self.cv2 = cv2
            self.mp = mp
            # refine_landmarks=True is required for iris landmarks (468/473)
            # used for gaze estimation.
            self.face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=2,
                refine_landmarks=True,
                min_detection_confidence=0.5,
            )
            self._available = True
        except ImportError as e:
            logger.info(
                "FacialAnalyzer disabled (opencv/mediapipe not installed): %s",
                e,
            )
        except Exception as e:
            logger.warning("FacialAnalyzer init failed: %s", e)

    @property
    def available(self) -> bool:
        return self._available

    async def analyze_video_frames(
        self,
        video_path: str,
        sample_interval_seconds: int = 5,
    ) -> Dict[str, Any]:
        """
        Sample frames from the video at the given interval (seconds) and
        analyze facial landmarks at each sample. Returns the structured
        analysis described in the module docstring.
        """
        if not self._available:
            return {
                "error": "facial analysis not available",
                "frames_analyzed": 0,
                "duration_seconds": 0.0,
                "emotional_timeline": [],
                "summary": {},
            }

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                self._process_video_sync,
                video_path,
                sample_interval_seconds,
            )
        except Exception as e:
            logger.warning("FacialAnalyzer.analyze_video_frames failed: %s", e)
            return {
                "error": f"facial analysis error: {e}",
                "frames_analyzed": 0,
                "duration_seconds": 0.0,
                "emotional_timeline": [],
                "summary": {},
            }

    # ------------------------------------------------------------------
    # Synchronous worker — runs in thread executor
    # ------------------------------------------------------------------

    def _process_video_sync(
        self,
        video_path: str,
        interval: int,
    ) -> Dict[str, Any]:
        cap = self.cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return {
                "error": f"could not open video: {video_path}",
                "frames_analyzed": 0,
                "duration_seconds": 0.0,
                "emotional_timeline": [],
                "summary": {},
            }

        fps = cap.get(self.cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / fps if fps > 0 else 0.0
        frame_skip = max(1, int(fps * max(1, interval)))

        timeline: List[Dict[str, Any]] = []
        frame_idx = 0
        max_samples = 240  # safety cap (~20 min @ 5s sampling)

        try:
            while cap.isOpened() and len(timeline) < max_samples:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % frame_skip == 0:
                    timestamp = frame_idx / fps if fps > 0 else float(frame_idx)
                    result = self._analyze_single_frame(frame)
                    result["timestamp"] = round(timestamp, 1)
                    timeline.append(result)
                frame_idx += 1
        finally:
            cap.release()

        summary = self._compute_summary(timeline)

        return {
            "frames_analyzed": len(timeline),
            "duration_seconds": round(duration, 1),
            "emotional_timeline": timeline,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Per-frame analysis
    # ------------------------------------------------------------------

    def _analyze_single_frame(self, frame: Any) -> Dict[str, Any]:
        try:
            rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb)
        except Exception as e:
            logger.debug("face_mesh.process failed: %s", e)
            return self._empty_frame_result()

        if not results.multi_face_landmarks:
            return self._empty_frame_result()

        landmarks = results.multi_face_landmarks[0]
        h, w = frame.shape[:2]

        indicators = self._compute_expression_indicators(landmarks, h, w)
        gaze = self._estimate_gaze(landmarks, h, w)
        head_pose = self._estimate_head_pose(landmarks, h, w)
        emotion = self._infer_emotion(indicators, gaze)

        return {
            "face_detected": True,
            "gaze_direction": gaze,
            "expression_indicators": indicators,
            "emotional_inference": emotion,
            "head_pose": head_pose,
        }

    @staticmethod
    def _empty_frame_result() -> Dict[str, Any]:
        return {
            "face_detected": False,
            "gaze_direction": "unknown",
            "expression_indicators": {},
            "emotional_inference": "no_face",
            "head_pose": {},
        }

    def _compute_expression_indicators(
        self,
        landmarks: Any,
        h: int,
        w: int,
    ) -> Dict[str, float]:
        lm = landmarks.landmark

        def dist(a: int, b: int) -> float:
            return ((lm[a].x - lm[b].x) ** 2 + (lm[a].y - lm[b].y) ** 2) ** 0.5

        try:
            # Brow vs eye (raise / furrow): 70(L brow) vs 159(L eye top),
            # 300(R brow) vs 386(R eye top)
            brow_eye_dist = (dist(70, 159) + dist(300, 386)) / 2
            mouth_width = dist(61, 291)
            lip_thickness = dist(13, 14)
            eye_aperture = dist(159, 145)
            face_width = dist(234, 454)  # ear-to-ear
            if face_width < 0.001:
                face_width = 0.1

            return {
                "brow_raise": min(1.0, max(0.0, (brow_eye_dist / face_width - 0.15) * 10)),
                "smile": min(1.0, max(0.0, (mouth_width / face_width - 0.25) * 5)),
                "lip_press": min(1.0, max(0.0, (0.05 - lip_thickness / face_width) * 20)),
                "eye_squeeze": min(1.0, max(0.0, (0.04 - eye_aperture / face_width) * 25)),
                "jaw_drop": min(1.0, max(0.0, (lip_thickness / face_width - 0.06) * 15)),
                "brow_furrow": min(1.0, max(0.0, (0.18 - brow_eye_dist / face_width) * 10)),
            }
        except (IndexError, AttributeError) as e:
            logger.debug("expression indicator calc failed: %s", e)
            return {}

    def _estimate_gaze(self, landmarks: Any, h: int, w: int) -> str:
        lm = landmarks.landmark
        try:
            # Left eye: inner 133, outer 33, iris center 468 (refine_landmarks)
            left_inner = lm[133].x
            left_outer = lm[33].x
            left_iris_x = lm[468].x

            denom = left_inner - left_outer
            if abs(denom) < 1e-4:
                return "unknown"
            left_ratio = (left_iris_x - left_outer) / denom

            if left_ratio < 0.35:
                return "averted_right"
            if left_ratio > 0.65:
                return "averted_left"

            eye_top = lm[159].y
            eye_bottom = lm[145].y
            iris_y = lm[468].y
            vdenom = eye_bottom - eye_top
            if abs(vdenom) < 1e-4:
                return "direct"
            vert_ratio = (iris_y - eye_top) / vdenom

            if vert_ratio > 0.7:
                return "down"
            return "direct"
        except (IndexError, AttributeError):
            return "unknown"

    def _estimate_head_pose(
        self,
        landmarks: Any,
        h: int,
        w: int,
    ) -> Dict[str, float]:
        lm = landmarks.landmark
        try:
            nose = lm[1]
            left_ear = lm[234]
            right_ear = lm[454]
            forehead = lm[10]
            chin = lm[152]

            face_center_x = (left_ear.x + right_ear.x) / 2
            face_center_y = (forehead.y + chin.y) / 2

            yaw = round((nose.x - face_center_x) * 100, 1)
            pitch = round((nose.y - face_center_y) * 100, 1)
            return {"pitch": pitch, "yaw": yaw, "roll": 0.0}
        except (IndexError, AttributeError):
            return {}

    @staticmethod
    def _infer_emotion(indicators: Dict[str, float], gaze: str) -> str:
        if not indicators:
            return "neutral"

        smile = indicators.get("smile", 0.0)
        brow_furrow = indicators.get("brow_furrow", 0.0)
        lip_press = indicators.get("lip_press", 0.0)
        eye_squeeze = indicators.get("eye_squeeze", 0.0)
        brow_raise = indicators.get("brow_raise", 0.0)

        if smile > 0.5 and gaze == "direct":
            return "engaged"
        if brow_furrow > 0.5 and lip_press > 0.3:
            return "distressed"
        if gaze in ("down", "averted_left", "averted_right") and lip_press > 0.3:
            return "withdrawn"
        if brow_raise > 0.5 and eye_squeeze < 0.2:
            return "surprised"
        if brow_furrow > 0.3 and eye_squeeze > 0.3:
            return "anxious"
        if smile < 0.2 and gaze == "direct":
            return "attentive"
        return "neutral"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _compute_summary(self, timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not timeline:
            return {}

        detected = [t for t in timeline if t.get("face_detected")]
        if not detected:
            return {
                "frames_with_face": 0,
                "frames_total": len(timeline),
                "potential_indicators": [],
            }

        emotions = [t.get("emotional_inference", "neutral") for t in detected]
        gazes = [t.get("gaze_direction", "unknown") for t in detected]

        averted = sum(
            1 for g in gazes if g in ("averted_left", "averted_right", "down")
        )
        aversion_ratio = averted / len(detected)

        potential_indicators: List[str] = []
        if aversion_ratio > 0.4:
            potential_indicators.append(
                "elevated gaze aversion — possible shame or avoidance"
            )

        anxious_count = emotions.count("anxious") + emotions.count("distressed")
        if anxious_count / len(detected) > 0.3:
            potential_indicators.append("frequent anxiety/distress markers")

        withdrawn_count = emotions.count("withdrawn")
        if withdrawn_count / len(detected) > 0.25:
            potential_indicators.append(
                "withdrawal pattern — possible freeze response"
            )

        emotion_counts = Counter(emotions)
        dominant = (
            emotion_counts.most_common(1)[0][0] if emotion_counts else "neutral"
        )

        smiles = [
            t.get("expression_indicators", {}).get("smile", 0.0)
            for t in detected
            if t.get("expression_indicators")
        ]
        variability = (max(smiles) - min(smiles)) if smiles else 0.0

        engaged_count = sum(
            1 for e in emotions if e in ("engaged", "attentive")
        )

        return {
            "frames_with_face": len(detected),
            "frames_total": len(timeline),
            "avg_engagement": round(engaged_count / len(detected), 2),
            "gaze_aversion_ratio": round(aversion_ratio, 2),
            "expression_variability": round(variability, 2),
            "dominant_expression": dominant,
            "potential_indicators": potential_indicators,
        }


def create_facial_analyzer() -> FacialAnalyzer:
    """Factory used by classroom_analyzer to lazily construct the analyzer."""
    return FacialAnalyzer()
