"""
Video Analyzer - Zoom video recording analysis for Little Nate's learning

This module handles:
- Downloading MP4 videos from Zoom cloud recordings
- Extracting key frames at configurable intervals
- Preparing frames for vision API analysis
- Integrating visual insights with session memory

Requirements:
- opencv-python>=4.8.0 (optional, graceful fallback if not available)
- moviepy>=1.0.3 (optional, alternative for video processing)
"""

import asyncio
import base64
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import io

# Check for video processing libraries
OPENCV_AVAILABLE = False
MOVIEPY_AVAILABLE = False

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    cv2 = None
    np = None

try:
    from moviepy.editor import VideoFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    VideoFileClip = None

LIBROSA_AVAILABLE = False
try:
    import librosa  # noqa: F401
    import numpy as np  # noqa: F401

    LIBROSA_AVAILABLE = True
except ImportError:
    librosa = None  # type: ignore
    np = None  # type: ignore

from app.config import settings


def extract_audio_wav(video_path: Path) -> Optional[Path]:
    """
    Extract mono 22.05kHz WAV to a temp file, or None if no audio / failure.
    Tries MoviePy first, then ffmpeg CLI.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        return None

    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = Path(tmp)

    if MOVIEPY_AVAILABLE and VideoFileClip is not None:
        clip = None
        try:
            clip = VideoFileClip(str(video_path))
            if clip.audio is None:
                clip.close()
                out.unlink(missing_ok=True)
                return None
            clip.audio.write_audiofile(
                str(out),
                fps=22050,
                nbytes=2,
                codec="pcm_s16le",
                verbose=False,
                logger=None,
            )
            if out.exists() and out.stat().st_size > 64:
                return out
        except Exception as e:
            print(f"[VideoAnalyzer] moviepy audio extract: {e}")
        finally:
            try:
                if clip is not None:
                    clip.close()
            except Exception:
                pass

    try:
        if out.exists():
            out.unlink(missing_ok=True)
    except Exception:
        pass

    fd2, tmp2 = tempfile.mkstemp(suffix=".wav")
    os.close(fd2)
    out2 = Path(tmp2)
    try:
        r = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "22050",
                "-ac",
                "1",
                str(out2),
            ],
            capture_output=True,
            timeout=900,
            check=False,
        )
        if r.returncode == 0 and out2.exists() and out2.stat().st_size > 64:
            return out2
    except Exception as e:
        print(f"[VideoAnalyzer] ffmpeg audio extract: {e}")
    try:
        out2.unlink(missing_ok=True)
    except Exception:
        pass
    return None


def compute_voice_metrics_timeline(
    wav_path: Path,
    window_sec: float = 5.0,
) -> Optional[List[Dict[str, float]]]:
    """
    Per-window features: RMS energy, ZCR (speech-rate proxy), silence ratio.
    Returns None if librosa unavailable or analysis fails.
    """
    if not LIBROSA_AVAILABLE or librosa is None or np is None:
        return None
    wav_path = Path(wav_path)
    if not wav_path.exists():
        return None
    try:
        y, sr = librosa.load(str(wav_path), sr=22050, mono=True)
        if y is None or len(y) < max(int(0.3 * sr), 256):
            return None
        hop = int(window_sec * sr)
        timeline: List[Dict[str, float]] = []
        for start in range(0, len(y), hop):
            chunk = y[start : start + hop]
            if len(chunk) < int(0.2 * sr):
                break
            t0 = start / sr
            rms = float(np.sqrt(np.mean(chunk**2) + 1e-12))
            zcr = float(np.mean(librosa.feature.zero_crossing_rate(y=chunk, hop_length=512)[0]))
            silence_ratio = 0.0
            frame_length = 2048
            hop_length = 512
            if len(chunk) >= frame_length:
                rms_f = librosa.feature.rms(
                    y=chunk, frame_length=frame_length, hop_length=hop_length
                )[0]
                if len(rms_f):
                    thr = float(np.percentile(rms_f, 25))
                    silence_ratio = float(np.mean(rms_f < max(thr, 1e-8)))
            energy = float(min(1.0, rms * 15.0))
            speech_rate = float(min(1.0, zcr / 0.15))
            timeline.append(
                {
                    "timestamp": round(t0, 2),
                    "energy": round(energy, 4),
                    "speech_rate": round(speech_rate, 4),
                    "silence_ratio": round(silence_ratio, 4),
                }
            )
        return timeline or None
    except Exception as e:
        print(f"[VideoAnalyzer] voice metrics timeline: {e}")
        return None


def voice_timeline_key_moments(
    timeline: List[Dict[str, float]],
    max_moments: int = 4,
) -> List[Dict[str, str]]:
    """Heuristic key moments from energy peaks (complements frame-based moments)."""
    if not timeline or len(timeline) < 2:
        return []
    energies = [float(x.get("energy", 0)) for x in timeline]
    mean_e = sum(energies) / len(energies)
    moments: List[Dict[str, str]] = []
    for seg in timeline:
        e = float(seg.get("energy", 0))
        sil = float(seg.get("silence_ratio", 0))
        if e > mean_e * 1.3 and sil < 0.55:
            ts = int(float(seg.get("timestamp", 0)))
            mm, ss = ts // 60, ts % 60
            moments.append(
                {
                    "timestamp": f"{mm}:{ss:02d}",
                    "description": f"Elevated vocal energy (~{mm}:{ss:02d})",
                    "feedback": "Review pacing and attunement through this stretch.",
                }
            )
        if len(moments) >= max_moments:
            break
    return moments


class VideoAnalyzer:
    """
    Analyzes Zoom video recordings for visual biometrics and insights.
    
    Features:
    - Downloads videos from Zoom recordings
    - Extracts frames at configurable intervals
    - Encodes frames for Azure Vision API
    - Provides visual insights for session memory
    """
    
    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        frame_interval_seconds: int = 5,
        max_frames: int = 60,
    ):
        """
        Initialize the video analyzer.
        
        Args:
            storage_dir: Directory for temporary video storage
            frame_interval_seconds: Seconds between frame captures
            max_frames: Maximum frames to extract per video
        """
        self.storage_dir = storage_dir or Path(tempfile.gettempdir()) / "little_nate_videos"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.frame_interval = frame_interval_seconds
        self.max_frames = max_frames
        
        # Check capabilities
        self.video_processing_available = OPENCV_AVAILABLE or MOVIEPY_AVAILABLE
        
        if not self.video_processing_available:
            print("[VideoAnalyzer] WARNING: No video processing library available.")
            print("[VideoAnalyzer] Install opencv-python or moviepy for video analysis.")
    
    async def download_zoom_video(
        self,
        meeting_id: str,
        zoom_client: Any,
        preferred_type: str = "shared_screen_with_speaker_view"
    ) -> Optional[Path]:
        """
        Download MP4 video from Zoom cloud recordings.
        
        Args:
            meeting_id: Zoom meeting ID
            zoom_client: Initialized ZoomClient instance
            preferred_type: Preferred recording type (video view)
            
        Returns:
            Path to downloaded video file, or None if not available
        """
        try:
            # Get recording metadata
            rec = await zoom_client.get_meeting_recordings(meeting_id=meeting_id)
            
            recording_files = rec.get("recording_files", [])
            if not recording_files:
                print(f"[VideoAnalyzer] No recording files found for meeting {meeting_id}")
                return None
            
            # Find video file (prefer shared_screen_with_speaker_view)
            video_file = None
            
            # Priority order for video types
            type_priority = [
                "shared_screen_with_speaker_view",
                "shared_screen_with_gallery_view",
                "speaker_view",
                "gallery_view",
                "active_speaker"
            ]
            
            for file_type in type_priority:
                for f in recording_files:
                    if f.get("file_type", "").lower() == file_type.lower():
                        video_file = f
                        break
                    # Also check recording_type field
                    if f.get("recording_type", "").lower() == file_type.lower():
                        video_file = f
                        break
                if video_file:
                    break
            
            # Fallback to any MP4 file
            if not video_file:
                for f in recording_files:
                    ext = (f.get("file_extension") or "").upper()
                    if ext == "MP4":
                        video_file = f
                        break
            
            if not video_file:
                print(f"[VideoAnalyzer] No video files found for meeting {meeting_id}")
                return None
            
            download_url = video_file.get("download_url", "")
            if not download_url:
                print(f"[VideoAnalyzer] No download URL for video")
                return None
            
            # Download the video
            print(f"[VideoAnalyzer] Downloading video from Zoom...")
            content = await zoom_client.download_recording_file(download_url=download_url)
            
            # Save to temp file
            video_path = self.storage_dir / f"{meeting_id}.mp4"
            with open(video_path, 'wb') as f:
                f.write(content)
            
            file_size_mb = len(content) / (1024 * 1024)
            print(f"[VideoAnalyzer] Downloaded {file_size_mb:.1f} MB video to {video_path}")
            
            return video_path
            
        except Exception as e:
            print(f"[VideoAnalyzer] Error downloading video: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def extract_frames(
        self,
        video_path: Path,
        interval_seconds: Optional[int] = None,
        max_frames: Optional[int] = None
    ) -> List[bytes]:
        """
        Extract key frames from a video file.
        
        Args:
            video_path: Path to video file
            interval_seconds: Seconds between frame captures (default: self.frame_interval)
            max_frames: Maximum frames to extract (default: self.max_frames)
            
        Returns:
            List of frame images as JPEG bytes
        """
        interval = interval_seconds or self.frame_interval
        max_count = max_frames or self.max_frames
        
        if OPENCV_AVAILABLE:
            return self._extract_frames_opencv(video_path, interval, max_count)
        elif MOVIEPY_AVAILABLE:
            return self._extract_frames_moviepy(video_path, interval, max_count)
        else:
            print("[VideoAnalyzer] No video processing library available")
            return []
    
    def _extract_frames_opencv(
        self,
        video_path: Path,
        interval_seconds: int,
        max_frames: int
    ) -> List[bytes]:
        """Extract frames using OpenCV."""
        frames = []
        
        try:
            cap = cv2.VideoCapture(str(video_path))
            
            if not cap.isOpened():
                print(f"[VideoAnalyzer] Could not open video: {video_path}")
                return []
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            print(f"[VideoAnalyzer] Video: {duration:.1f}s, {fps:.1f} FPS, {total_frames} frames")
            
            frame_skip = int(fps * interval_seconds)
            frame_number = 0
            
            while len(frames) < max_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ret, frame = cap.read()
                
                if not ret:
                    break
                
                # Resize to reduce size (720p max)
                height, width = frame.shape[:2]
                if width > 1280:
                    scale = 1280 / width
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    frame = cv2.resize(frame, (new_width, new_height))
                
                # Encode as JPEG
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frames.append(buffer.tobytes())
                
                frame_number += frame_skip
                
                if frame_number >= total_frames:
                    break
            
            cap.release()
            print(f"[VideoAnalyzer] Extracted {len(frames)} frames")
            
            return frames
            
        except Exception as e:
            print(f"[VideoAnalyzer] OpenCV error: {e}")
            return []
    
    def _extract_frames_moviepy(
        self,
        video_path: Path,
        interval_seconds: int,
        max_frames: int
    ) -> List[bytes]:
        """Extract frames using MoviePy."""
        frames = []
        
        try:
            clip = VideoFileClip(str(video_path))
            duration = clip.duration
            
            print(f"[VideoAnalyzer] Video duration: {duration:.1f}s")
            
            current_time = 0
            while current_time < duration and len(frames) < max_frames:
                # Get frame at current time
                frame = clip.get_frame(current_time)
                
                # Convert to JPEG bytes
                import cv2
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frames.append(buffer.tobytes())
                
                current_time += interval_seconds
            
            clip.close()
            print(f"[VideoAnalyzer] Extracted {len(frames)} frames")
            
            return frames
            
        except Exception as e:
            print(f"[VideoAnalyzer] MoviePy error: {e}")
            return []
    
    def frames_to_base64(self, frames: List[bytes]) -> List[str]:
        """Convert frame bytes to base64 strings for API submission."""
        return [base64.b64encode(f).decode('utf-8') for f in frames]

    def analyze_classroom_frames(self, frames: List[bytes]) -> Dict[str, Any]:
        """
        Lightweight coaching hints from sampled frames (no vision API).
        Used by Classroom device uploads; does not require Zoom client.
        """
        n = len(frames)
        coaching = (
            f"Sampled {n} frames from the classroom video. "
            "Use framing, posture, and environmental stability as cues for therapeutic presence. "
            "Cross-check with the voice timeline (energy, silence) where available."
        )
        moments: List[Dict[str, str]] = []
        interval = self.frame_interval
        for i in range(min(n, 3)):
            sec = i * interval
            mm, ss = sec // 60, sec % 60
            label = "Opening" if i == 0 else ("Mid-session sample" if i == 1 else "Later sample")
            moments.append(
                {
                    "timestamp": f"{mm}:{ss:02d}",
                    "description": f"{label} (frame {i + 1}/{n})",
                    "feedback": "Notice gaze, openness, and how space supports safety.",
                }
            )
        score = min(8.5, 6.0 + min(n, 5) * 0.28)
        return {
            "coaching_insights": coaching,
            "key_moments": moments,
            "therapeutic_presence_score": round(score, 2),
            "frames_analyzed": n,
        }

    async def analyze_video(
        self,
        meeting_id: str,
        zoom_client: Any,
        vision_analyzer: Optional[Any] = None
    ) -> Dict:
        """
        Complete video analysis pipeline.
        
        Args:
            meeting_id: Zoom meeting ID
            zoom_client: Initialized ZoomClient instance
            vision_analyzer: Optional VisualBiometricExtractor instance
            
        Returns:
            Dict with video insights including frame analyses
        """
        result = {
            "meeting_id": meeting_id,
            "analyzed_at": datetime.now().isoformat(),
            "video_downloaded": False,
            "frames_extracted": 0,
            "visual_insights": [],
            "summary": {},
            "error": None
        }
        
        try:
            # Step 1: Download video
            video_path = await self.download_zoom_video(meeting_id, zoom_client)
            
            if not video_path:
                result["error"] = "Could not download video"
                return result
            
            result["video_downloaded"] = True
            result["video_path"] = str(video_path)
            
            # Step 2: Extract frames
            if not self.video_processing_available:
                result["error"] = "Video processing libraries not available"
                return result
            
            frames = self.extract_frames(video_path)
            result["frames_extracted"] = len(frames)
            
            if not frames:
                result["error"] = "No frames could be extracted"
                return result
            
            # Step 3: Analyze frames (if vision analyzer provided)
            if vision_analyzer:
                print(f"[VideoAnalyzer] Analyzing {len(frames)} frames with vision API...")
                
                # Analyze a subset of frames to manage API costs
                sample_indices = self._get_sample_indices(len(frames), max_samples=10)
                
                for idx in sample_indices:
                    frame_b64 = base64.b64encode(frames[idx]).decode('utf-8')
                    
                    try:
                        insight = await vision_analyzer.analyze_frame(
                            frame_base64=frame_b64,
                            frame_index=idx
                        )
                        result["visual_insights"].append(insight)
                    except Exception as e:
                        print(f"[VideoAnalyzer] Frame {idx} analysis error: {e}")
                
                # Generate summary from insights
                result["summary"] = self._summarize_insights(result["visual_insights"])
            
            # Clean up video file (optional)
            # video_path.unlink()
            
            return result
            
        except Exception as e:
            result["error"] = str(e)
            import traceback
            traceback.print_exc()
            return result
    
    def _get_sample_indices(self, total: int, max_samples: int = 10) -> List[int]:
        """Get evenly distributed sample indices."""
        if total <= max_samples:
            return list(range(total))
        
        step = total / max_samples
        return [int(i * step) for i in range(max_samples)]
    
    def _summarize_insights(self, insights: List[Dict]) -> Dict:
        """Summarize visual insights into overall metrics."""
        if not insights:
            return {}
        
        summary = {
            "total_frames_analyzed": len(insights),
            "average_engagement": 0.0,
            "average_valence": 0.0,
            "average_arousal": 0.0,
            "eye_contact_ratio": 0.0,
            "body_language_patterns": [],
            "notable_moments": []
        }
        
        # Aggregate metrics
        engagement_sum = 0
        valence_sum = 0
        arousal_sum = 0
        eye_contact_count = 0
        
        for insight in insights:
            engagement_sum += insight.get("engagement_score", 0.5)
            valence_sum += insight.get("facial_affect_valence", 0)
            arousal_sum += insight.get("facial_affect_arousal", 0.5)
            if insight.get("gaze_contact", False):
                eye_contact_count += 1
            
            # Track notable moments
            if insight.get("is_notable", False):
                summary["notable_moments"].append({
                    "frame_index": insight.get("frame_index"),
                    "description": insight.get("notable_description", "")
                })
        
        n = len(insights)
        summary["average_engagement"] = round(engagement_sum / n, 2)
        summary["average_valence"] = round(valence_sum / n, 2)
        summary["average_arousal"] = round(arousal_sum / n, 2)
        summary["eye_contact_ratio"] = round(eye_contact_count / n, 2)
        
        return summary
    
    def get_status(self) -> Dict:
        """Get analyzer status and capabilities."""
        return {
            "opencv_available": OPENCV_AVAILABLE,
            "moviepy_available": MOVIEPY_AVAILABLE,
            "librosa_available": LIBROSA_AVAILABLE,
            "video_processing_available": self.video_processing_available,
            "storage_dir": str(self.storage_dir),
            "frame_interval_seconds": self.frame_interval,
            "max_frames": self.max_frames
        }


def create_video_analyzer(
    storage_dir: Optional[Path] = None,
    frame_interval_seconds: int = 5,
    max_frames: int = 60
) -> VideoAnalyzer:
    """Factory function to create a VideoAnalyzer instance."""
    return VideoAnalyzer(
        storage_dir=storage_dir,
        frame_interval_seconds=frame_interval_seconds,
        max_frames=max_frames
    )
