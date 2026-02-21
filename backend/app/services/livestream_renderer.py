"""
LITTLE NATE — Livestream Renderer
Generates video frames with the Little Nate avatar and streams via FFmpeg
to multiple RTMP endpoints simultaneously.

Specs matched to X Producer recommendations:
- 1920x1080 (1080p)
- 30 fps
- H.264/AVC, 9 Mbps video bitrate
- AAC 44100 Hz, 128 kbps, stereo
- Keyframe interval: 3 seconds

Phase 1: Static avatar image with text overlays (question + response)
Phase 2: Spline 3D avatar with lip-sync (when Blender model is ready)
"""

import asyncio
import logging
import os
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("skyeye.livestream.renderer")

AVATAR_IMAGE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "assets", "little_nate_avatar.png"
)

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
FPS = 30
KEYFRAME_INTERVAL = 3

BG_COLOR = (5, 5, 5)
GOLD = (201, 169, 98)
WHITE = (240, 240, 240)
MUTED = (120, 120, 120)
PANEL_BG = (17, 17, 17)
CYAN = (78, 205, 196)
GREEN = (0, 255, 136)
PURPLE = (157, 78, 221)


class StreamHealthStatus:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"
    CONNECTING = "connecting"
    PREFLIGHT = "preflight"


class LivestreamRenderer:
    """Manages FFmpeg RTMP output with avatar frames and connection verification."""

    def __init__(self, rtmp_keys: Dict[str, str],
                 on_health_change: Optional[Callable] = None):
        self.rtmp_keys = rtmp_keys
        self._ffmpeg_proc: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._frame_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._on_health_change = on_health_change

        self._current_expression = "neutral"
        self._current_question = ""
        self._current_viewer = ""
        self._current_response = ""
        self._is_speaking = False
        self._avatar_image = None

        self._health = StreamHealthStatus.CONNECTING
        self._frames_sent = 0
        self._last_frame_time = 0.0
        self._connection_confirmed = False
        self._ffmpeg_stderr_lines: List[str] = []
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3

    @property
    def health(self) -> str:
        return self._health

    @property
    def is_connected(self) -> bool:
        return self._connection_confirmed

    @property
    def frames_sent(self) -> int:
        return self._frames_sent

    async def preflight_check(self) -> bool:
        """Push test frames to RTMP and verify the platform acknowledges receipt.
        Returns True if connection is confirmed, False if it failed."""
        self._health = StreamHealthStatus.PREFLIGHT
        logger.info("Starting pre-flight connection check...")

        rtmp_targets = list(self.rtmp_keys.values())
        if not rtmp_targets:
            logger.error("No RTMP targets for pre-flight")
            return False

        cmd = self._build_ffmpeg_cmd(rtmp_targets)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("FFmpeg not found — cannot verify connection")
            return False

        try:
            from PIL import Image
            test_frame = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BG_COLOR)
            frame_bytes = test_frame.tobytes()
        except ImportError:
            frame_bytes = bytes(BG_COLOR) * (FRAME_WIDTH * FRAME_HEIGHT)

        connected = False
        stderr_output = []

        async def read_stderr():
            nonlocal connected
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                stderr_output.append(text)
                if any(kw in text.lower() for kw in [
                    "output #0", "stream #0", "video:", "muxing overhead",
                    "frame=", "fps=", "size="
                ]):
                    connected = True

        stderr_reader = asyncio.create_task(read_stderr())

        try:
            for i in range(90):
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(frame_bytes)
                    await proc.stdin.drain()
                await asyncio.sleep(1.0 / FPS)

                if connected:
                    logger.info(f"Pre-flight CONFIRMED after {i + 1} frames")
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass

        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:
            pass

        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()

        stderr_reader.cancel()

        if not connected and stderr_output:
            for line in stderr_output[-10:]:
                if "error" in line.lower() or "refused" in line.lower():
                    logger.error(f"Pre-flight FAILED: {line}")

        if connected:
            logger.info("Pre-flight check PASSED — platform is receiving frames")
            self._connection_confirmed = True
        else:
            logger.error("Pre-flight check FAILED — platform did not acknowledge")
            self._connection_confirmed = False

        return connected

    async def start(self) -> bool:
        """Start the RTMP stream. Returns True if connected successfully."""
        self._running = True
        self._load_avatar()
        self._frames_sent = 0
        self._connection_confirmed = False
        self._health = StreamHealthStatus.CONNECTING

        rtmp_targets = list(self.rtmp_keys.values())
        if not rtmp_targets:
            logger.warning("No RTMP keys provided, renderer in preview mode")
            return False

        cmd = self._build_ffmpeg_cmd(rtmp_targets)

        try:
            self._ffmpeg_proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("FFmpeg not found — install ffmpeg to enable streaming")
            self._health = StreamHealthStatus.DEAD
            return False
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {e}")
            self._health = StreamHealthStatus.DEAD
            return False

        self._stderr_task = asyncio.create_task(self._monitor_stderr())
        self._frame_task = asyncio.create_task(self._frame_loop())
        self._health_task = asyncio.create_task(self._health_monitor_loop())

        await asyncio.sleep(3)

        if self._ffmpeg_proc.returncode is not None:
            logger.error(f"FFmpeg exited immediately with code {self._ffmpeg_proc.returncode}")
            self._health = StreamHealthStatus.DEAD
            return False

        self._health = StreamHealthStatus.HEALTHY
        self._connection_confirmed = True
        logger.info(f"RTMP stream started to {len(rtmp_targets)} targets")
        return True

    async def stop(self):
        self._running = False
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
        if self._frame_task and not self._frame_task.done():
            self._frame_task.cancel()
        if self._ffmpeg_proc and self._ffmpeg_proc.stdin:
            try:
                self._ffmpeg_proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._ffmpeg_proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._ffmpeg_proc.kill()
        self._health = StreamHealthStatus.DEAD
        logger.info(f"RTMP stream stopped. {self._frames_sent} total frames sent.")

    def _build_ffmpeg_cmd(self, rtmp_targets: List[str]) -> List[str]:
        tee_targets = "|".join(f"[f=flv]{url}" for url in rtmp_targets)

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
            "-r", str(FPS),
            "-i", "-",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-b:v", "9000k",
            "-maxrate", "9000k",
            "-bufsize", "18000k",
            "-pix_fmt", "yuv420p",
            "-g", str(FPS * KEYFRAME_INTERVAL),
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-ac", "2",
            "-shortest",
        ]

        if len(rtmp_targets) == 1:
            cmd.extend(["-f", "flv", rtmp_targets[0]])
        else:
            cmd.extend(["-f", "tee", "-map", "0:v", "-map", "1:a", tee_targets])

        return cmd

    async def _monitor_stderr(self):
        """Read FFmpeg stderr for connection status and errors."""
        try:
            while self._running and self._ffmpeg_proc:
                line = await self._ffmpeg_proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                self._ffmpeg_stderr_lines.append(text)
                if len(self._ffmpeg_stderr_lines) > 200:
                    self._ffmpeg_stderr_lines = self._ffmpeg_stderr_lines[-100:]

                if any(kw in text.lower() for kw in ["output #0", "stream #0", "video:"]):
                    if not self._connection_confirmed:
                        self._connection_confirmed = True
                        logger.info("RTMP connection confirmed by FFmpeg output")

                if any(kw in text.lower() for kw in [
                    "connection refused", "connection timed out",
                    "broken pipe", "i/o error", "error writing",
                ]):
                    logger.error(f"FFmpeg stream error: {text}")
                    self._health = StreamHealthStatus.DEGRADED

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Stderr monitor error: {e}")

    async def _health_monitor_loop(self):
        """Check stream health every 10 seconds."""
        try:
            while self._running:
                await asyncio.sleep(10)

                if not self._ffmpeg_proc or self._ffmpeg_proc.returncode is not None:
                    logger.error("FFmpeg process died")
                    self._health = StreamHealthStatus.DEAD

                    if self._on_health_change:
                        await self._on_health_change(StreamHealthStatus.DEAD)

                    if self._reconnect_attempts < self._max_reconnect_attempts:
                        self._reconnect_attempts += 1
                        logger.info(
                            f"Attempting reconnect {self._reconnect_attempts}"
                            f"/{self._max_reconnect_attempts}..."
                        )
                        await asyncio.sleep(5)
                        success = await self.start()
                        if success:
                            logger.info("Reconnection successful")
                            self._health = StreamHealthStatus.HEALTHY
                            if self._on_health_change:
                                await self._on_health_change(StreamHealthStatus.HEALTHY)
                        else:
                            logger.error("Reconnection failed")
                    else:
                        logger.error("Max reconnect attempts reached")
                        if self._on_health_change:
                            await self._on_health_change("max_reconnect_failed")
                        break

                elif time.time() - self._last_frame_time > 5.0 and self._frames_sent > 0:
                    logger.warning("No frames sent in 5 seconds — stream may be stalled")
                    self._health = StreamHealthStatus.DEGRADED

                else:
                    if self._health == StreamHealthStatus.DEGRADED:
                        self._health = StreamHealthStatus.HEALTHY
                        logger.info("Stream health recovered")

        except asyncio.CancelledError:
            pass

    def _load_avatar(self):
        try:
            from PIL import Image
            if os.path.exists(AVATAR_IMAGE_PATH):
                img = Image.open(AVATAR_IMAGE_PATH).convert("RGB")
                self._avatar_image = img.resize((450, 450))
                logger.info("Avatar image loaded (450x450 for 1080p)")
            else:
                logger.warning(f"Avatar image not found at {AVATAR_IMAGE_PATH}")
        except ImportError:
            logger.warning("Pillow not installed — using solid color avatar placeholder")
        except Exception as e:
            logger.error(f"Failed to load avatar: {e}")

    async def _frame_loop(self):
        frame_interval = 1.0 / FPS
        while self._running:
            try:
                frame = self._render_frame()
                if self._ffmpeg_proc and self._ffmpeg_proc.stdin:
                    self._ffmpeg_proc.stdin.write(frame)
                    await self._ffmpeg_proc.stdin.drain()
                    self._frames_sent += 1
                    self._last_frame_time = time.time()
            except (BrokenPipeError, ConnectionResetError):
                logger.error("FFmpeg pipe broken")
                self._health = StreamHealthStatus.DEAD
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Frame render error: {e}")
            await asyncio.sleep(frame_interval)

    def _render_frame(self) -> bytes:
        try:
            from PIL import Image, ImageDraw, ImageFont
            return self._render_pil_frame(Image, ImageDraw, ImageFont)
        except ImportError:
            return self._render_raw_frame()

    def _render_pil_frame(self, Image, ImageDraw, ImageFont) -> bytes:
        frame = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(frame)

        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except (OSError, IOError):
            font_title = ImageFont.load_default()
            font_large = font_title
            font_medium = font_title
            font_small = font_title

        cx = FRAME_WIDTH // 2

        if self._avatar_image:
            avatar_x = cx - 225
            frame.paste(self._avatar_image, (avatar_x, 50))
        else:
            draw.ellipse([cx - 120, 70, cx + 120, 310], fill=(30, 30, 30), outline=GOLD, width=2)

        draw.text((cx, 520), "Little Nate", fill=GOLD, font=font_title, anchor="mt")

        expression_text = self._current_expression.upper()
        dot_color = {
            "neutral": MUTED, "attentive": CYAN,
            "thoughtful": PURPLE, "warm": GOLD,
            "empathetic": CYAN, "encouraging": GREEN,
            "curious": PURPLE, "calming": CYAN,
        }.get(self._current_expression, GOLD)

        draw.ellipse([cx - 80, 570, cx - 66, 584], fill=dot_color)
        draw.text((cx - 60, 567), expression_text, fill=MUTED, font=font_small)

        draw.line([(100, 610), (FRAME_WIDTH - 100, 610)], fill=(40, 40, 40), width=1)

        if self._current_question:
            q_y = 630
            draw.rounded_rectangle(
                [80, q_y, FRAME_WIDTH - 80, q_y + 100],
                radius=12, fill=PANEL_BG, outline=(50, 50, 50), width=1,
            )
            draw.text((110, q_y + 10), f"@{self._current_viewer}", fill=GOLD, font=font_small)
            q_text = self._current_question[:150]
            if len(self._current_question) > 150:
                q_text += "..."
            lines = self._wrap_text(q_text, 85)
            y = q_y + 38
            for line in lines[:2]:
                draw.text((110, y), line, fill=WHITE, font=font_medium)
                y += 30

        if self._current_response:
            r_y = 750
            draw.rounded_rectangle(
                [80, r_y, FRAME_WIDTH - 80, FRAME_HEIGHT - 50],
                radius=12, fill=(10, 15, 10), outline=(0, 100, 68), width=1,
            )
            draw.text((110, r_y + 10), "Little Nate:", fill=GREEN, font=font_small)
            lines = self._wrap_text(self._current_response, 85)
            y = r_y + 38
            for line in lines[:7]:
                draw.text((110, y), line, fill=WHITE, font=font_medium)
                y += 30

        draw.text(
            (FRAME_WIDTH - 40, FRAME_HEIGHT - 28),
            "sovereignsanctuary.net",
            fill=MUTED, font=font_small, anchor="rb",
        )

        live_dot_alpha = int((time.time() * 2) % 2)
        if live_dot_alpha:
            draw.ellipse([40, 28, 58, 46], fill=(239, 68, 68))
        draw.text((66, 26), "LIVE", fill=(239, 68, 68), font=font_small)

        return frame.tobytes()

    def _render_raw_frame(self) -> bytes:
        return bytes(BG_COLOR) * (FRAME_WIDTH * FRAME_HEIGHT)

    def _wrap_text(self, text: str, max_chars: int) -> List[str]:
        words = text.split()
        lines = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > max_chars:
                lines.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            lines.append(current)
        return lines

    async def show_question(self, viewer: str, question: str):
        self._current_viewer = viewer
        self._current_question = question
        self._current_response = ""

    async def send_speech(self, text: str, expression: str = "warm"):
        self._current_response = text
        self._current_expression = expression
        self._is_speaking = True
        words = len(text.split())
        speak_duration = max(3, words * 0.4)
        await asyncio.sleep(speak_duration)
        self._is_speaking = False

    async def set_expression(self, expression: str):
        self._current_expression = expression

    async def set_idle(self):
        self._is_speaking = False
        self._current_question = ""
        self._current_viewer = ""
        self._current_response = ""
        self._current_expression = "neutral"
