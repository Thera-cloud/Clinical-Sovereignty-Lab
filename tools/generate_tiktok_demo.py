#!/usr/bin/env python3
"""
TikTok Developer Review Demo Video Generator
=============================================
Generates a professional MP4 demo video with AI voice narration (echo voice)
showing the full Sovereign Sanctuary onboarding flow followed by the
end-to-end TikTok integration, for submission to TikTok's developer app review.

Usage:
    pip install moviepy
    python tools/generate_tiktok_demo.py

Output:
    tools/tiktok_demo.mp4
"""

import os
import sys
import math
import struct
import tempfile
import time
from pathlib import Path
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1920, 1080
FPS = 30
FADE_FRAMES = 15  # 0.5s fade at 30fps

# Design system colours
BG_VOID = (5, 5, 5)
BG_CHAMBER = (10, 10, 10)
BG_ELEVATED = (17, 17, 17)
GOLD = (201, 169, 98)
GOLD_BRIGHT = (232, 213, 163)
GOLD_DIM = (139, 115, 85)
CYAN = (78, 205, 196)
PURPLE = (157, 78, 221)
RED = (239, 68, 68)
WHITE = (255, 255, 255)
GRAY = (160, 160, 160)
DARK_GRAY = (80, 80, 80)
CARD_BG = (20, 20, 20)
CARD_BORDER = (40, 40, 40)

# Paths
SCRIPT_DIR = Path(__file__).parent
AUDIO_DIR = SCRIPT_DIR / "audio"
OUTPUT_PATH = SCRIPT_DIR / "tiktok_demo.mp4"

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
def load_dotenv_manual(path: str) -> dict:
    """Minimal .env loader — no dependency needed."""
    env = {}
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

# Find .env
_env_path = SCRIPT_DIR.parent / ".env"
_env = load_dotenv_manual(str(_env_path))

AZURE_API_KEY = _env.get("AZURE_API_KEY", os.environ.get("AZURE_API_KEY", ""))
AZURE_ENDPOINT = _env.get("AZURE_OPENAI_ENDPOINT", os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
MINI_TTS_DEPLOYMENT = _env.get("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")

if not AZURE_API_KEY or not AZURE_ENDPOINT:
    print("ERROR: AZURE_API_KEY and AZURE_OPENAI_ENDPOINT must be set in .env")
    sys.exit(1)

# Ensure endpoint has no protocol prefix
AZURE_ENDPOINT = AZURE_ENDPOINT.replace("https://", "").replace("http://", "").rstrip("/")

MINI_TTS_URL = (
    f"https://{AZURE_ENDPOINT}/openai/deployments/{MINI_TTS_DEPLOYMENT}"
    f"/audio/speech?api-version=2025-01-01-preview"
)

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load best available sans-serif font."""
    candidates = []
    if bold:
        candidates = [
            "/System/Library/Fonts/HelveticaNeue.ttc",  # index 1 = Bold
            "/Library/Fonts/Arial Bold.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    for path in candidates:
        try:
            idx = 1 if bold and path.endswith(".ttc") else 0
            return ImageFont.truetype(path, size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def _load_serif(size: int) -> ImageFont.FreeTypeFont:
    """Load best serif / display font for headings."""
    try:
        return ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", size, index=0)
    except Exception:
        return _load_font(size, bold=True)


FONT_TITLE = _load_serif(72)
FONT_HEADING = _load_font(48, bold=True)
FONT_SUBHEADING = _load_font(36, bold=True)
FONT_BODY = _load_font(28)
FONT_SMALL = _load_font(22)
FONT_LABEL = _load_font(18)
FONT_BIG_TITLE = _load_serif(96)

# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _new_frame() -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), BG_VOID)


def _center_text(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.FreeTypeFont, fill=GOLD):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (WIDTH - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill=CARD_BG, outline=CARD_BORDER):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline)


def _draw_orb(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color=CYAN):
    """Draw a glowing orb."""
    for i in range(r, 0, -2):
        alpha_frac = i / r
        c = tuple(int(color[j] * (1 - alpha_frac) + BG_VOID[j] * alpha_frac) for j in range(3))
        draw.ellipse([cx - i, cy - i, cx + i, cy + i], fill=c)
    # bright core
    core = r // 3
    draw.ellipse([cx - core, cy - core, cx + core, cy + core], fill=WHITE)


def _draw_button(draw: ImageDraw.ImageDraw, cx: int, cy: int, text: str, color=GOLD, w=280, h=50):
    x0, y0 = cx - w // 2, cy - h // 2
    draw.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=h // 2, fill=None, outline=color, width=2)
    bbox = draw.textbbox((0, 0), text, font=FONT_SMALL)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2), text, font=FONT_SMALL, fill=color)


def _draw_chat_bubble(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, is_nate: bool, w=600):
    """Draw a chat message bubble."""
    h = 60
    color = CYAN if is_nate else GOLD_DIM
    bg = (20, 40, 38) if is_nate else (30, 25, 15)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=bg, outline=color)
    label = "Nate" if is_nate else "You"
    draw.text((x + 15, y + 8), label, font=FONT_LABEL, fill=color)
    draw.text((x + 15, y + 30), text, font=FONT_SMALL, fill=WHITE)


def _draw_waveform(draw: ImageDraw.ImageDraw, cx: int, cy: int, w: int, h: int, color=CYAN):
    """Draw a simple audio waveform."""
    bars = 40
    bar_w = w // bars
    for i in range(bars):
        x = cx - w // 2 + i * bar_w
        # Sine-based height variation
        bar_h = int(h * 0.3 + h * 0.7 * abs(math.sin(i * 0.3)))
        draw.rectangle([x, cy - bar_h // 2, x + bar_w - 2, cy + bar_h // 2], fill=color)


def _draw_gauge(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, value: float, label: str):
    """Draw a semi-circular gauge."""
    # Background arc
    for angle in range(-180, 1):
        rad = math.radians(angle)
        x = cx + int(r * math.cos(rad))
        y = cy + int(r * math.sin(rad))
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=DARK_GRAY)
    # Value arc
    end_angle = -180 + int(180 * value)
    for angle in range(-180, end_angle):
        rad = math.radians(angle)
        x = cx + int(r * math.cos(rad))
        y = cy + int(r * math.sin(rad))
        color = CYAN if value > 0.5 else GOLD
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=color)
    # Label
    _center_text(draw, f"{int(value * 100)}%", cy - 30, FONT_HEADING, fill=CYAN)
    _center_text(draw, label, cy + 20, FONT_SMALL, fill=GRAY)


def _draw_tier_card(draw: ImageDraw.ImageDraw, x: int, y: int, name: str, price: str, features: list, highlight=False):
    w, h = 380, 340
    border = GOLD if highlight else CARD_BORDER
    fill = (25, 22, 12) if highlight else CARD_BG
    draw.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=fill, outline=border, width=2 if highlight else 1)
    # Name
    bbox = draw.textbbox((0, 0), name, font=FONT_SUBHEADING)
    tw = bbox[2] - bbox[0]
    draw.text((x + (w - tw) // 2, y + 20), name, font=FONT_SUBHEADING, fill=GOLD_BRIGHT if highlight else GOLD)
    # Price
    bbox = draw.textbbox((0, 0), price, font=FONT_HEADING)
    tw = bbox[2] - bbox[0]
    draw.text((x + (w - tw) // 2, y + 70), price, font=FONT_HEADING, fill=WHITE)
    # Features
    for i, feat in enumerate(features):
        draw.text((x + 30, y + 130 + i * 32), f"  {feat}", font=FONT_SMALL, fill=GRAY)


def _draw_platform_card(draw: ImageDraw.ImageDraw, x: int, y: int, name: str, icon: str,
                         connected: bool = False, stats: dict = None):
    w, h = 240, 180
    border = (0, 180, 0) if connected else CARD_BORDER
    draw.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=CARD_BG, outline=border, width=2 if connected else 1)
    # Icon placeholder
    draw.text((x + 20, y + 15), icon, font=FONT_HEADING, fill=WHITE)
    draw.text((x + 70, y + 20), name, font=FONT_SUBHEADING, fill=WHITE)
    # Status dot
    dot_color = (0, 200, 0) if connected else DARK_GRAY
    draw.ellipse([x + w - 30, y + 15, x + w - 15, y + 30], fill=dot_color)
    if stats:
        sy = y + 75
        for k, v in stats.items():
            draw.text((x + 20, sy), f"{k}: {v}", font=FONT_LABEL, fill=GRAY)
            sy += 24
    elif not connected:
        _draw_button(draw, x + w // 2, y + 120, "Connect", color=GOLD, w=140, h=36)


def _draw_status_dot(draw: ImageDraw.ImageDraw, x: int, y: int, color, r=8):
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


# ---------------------------------------------------------------------------
# Slide renderers (16 slides)
# ---------------------------------------------------------------------------

def slide_01_title() -> Image.Image:
    """Title card."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)
    # Shield icon (simple)
    cx, cy = WIDTH // 2, 320
    # Shield shape
    pts = [(cx, cy - 80), (cx + 70, cy - 50), (cx + 60, cy + 40), (cx, cy + 80),
           (cx - 60, cy + 40), (cx - 70, cy - 50)]
    draw.polygon(pts, fill=GOLD_DIM, outline=GOLD)
    draw.polygon(pts, outline=GOLD, width=2)
    # Inner shield detail
    inner = [(cx, cy - 50), (cx + 40, cy - 30), (cx + 35, cy + 20), (cx, cy + 50),
             (cx - 35, cy + 20), (cx - 40, cy - 30)]
    draw.polygon(inner, fill=None, outline=GOLD_BRIGHT, width=1)

    _center_text(draw, "SOVEREIGN SANCTUARY", 440, FONT_BIG_TITLE, fill=GOLD)
    _center_text(draw, "AI-Powered Therapeutic Platform", 560, FONT_HEADING, fill=GRAY)
    _center_text(draw, "Powered by Little Nate", 630, FONT_BODY, fill=CYAN)

    # URL at bottom
    _center_text(draw, "app.sovereignsanctuary.net", 900, FONT_BODY, fill=GOLD_DIM)

    # Subtle line
    draw.line([(WIDTH // 2 - 200, 850), (WIDTH // 2 + 200, 850)], fill=GOLD_DIM, width=1)
    return img


def slide_02_welcome_gate() -> Image.Image:
    """Welcome Gate with Nate orb."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    # Nate orb
    _draw_orb(draw, WIDTH // 2, 340, 100, CYAN)

    _center_text(draw, "LITTLE NATE", 470, FONT_HEADING, fill=CYAN)
    _center_text(draw, "Welcome to the Sanctuary", 540, FONT_TITLE, fill=GOLD)
    _center_text(draw, "Your journey toward emotional coherence begins here.", 640, FONT_BODY, fill=GRAY)

    _draw_button(draw, WIDTH // 2, 740, "BEGIN TOUR", color=GOLD, w=260, h=52)
    _draw_button(draw, WIDTH // 2, 810, "Skip tutorial", color=DARK_GRAY, w=200, h=40)
    return img


def slide_03_chat() -> Image.Image:
    """Chat with Nate."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Step 1: Chat with Nate", 80, FONT_TITLE, fill=GOLD)

    # Phone frame
    px, py = WIDTH // 2 - 220, 170
    pw, ph = 440, 720
    draw.rounded_rectangle([px, py, px + pw, py + ph], radius=30, fill=BG_CHAMBER, outline=CARD_BORDER, width=2)

    # Chat header
    draw.rounded_rectangle([px + 10, py + 10, px + pw - 10, py + 60], radius=12, fill=BG_ELEVATED)
    _draw_orb(draw, px + 40, py + 35, 15, CYAN)
    draw.text((px + 65, py + 22), "Little Nate", font=FONT_SUBHEADING, fill=CYAN)

    # Chat bubbles
    _draw_chat_bubble(draw, px + 30, py + 90, "I've been feeling anxious about work...", False, w=380)
    _draw_chat_bubble(draw, px + 30, py + 170, "I hear you. Let's explore that together.", True, w=380)
    _draw_chat_bubble(draw, px + 30, py + 250, "It feels overwhelming sometimes.", False, w=380)
    _draw_chat_bubble(draw, px + 30, py + 330, "That feeling is valid. What does overwhelm", True, w=380)
    _draw_chat_bubble(draw, px + 30, py + 410, "look like for you right now?", True, w=380)

    # Input bar
    draw.rounded_rectangle([px + 15, py + ph - 60, px + pw - 15, py + ph - 15],
                           radius=20, fill=BG_ELEVATED, outline=CARD_BORDER)
    draw.text((px + 35, py + ph - 48), "Type a message...", font=FONT_SMALL, fill=DARK_GRAY)

    # Side description
    draw.text((WIDTH // 2 + 280, 300), "Secure, encrypted", font=FONT_SUBHEADING, fill=GOLD)
    draw.text((WIDTH // 2 + 280, 350), "therapeutic conversations", font=FONT_BODY, fill=GRAY)
    draw.text((WIDTH // 2 + 280, 420), "Clinically informed AI", font=FONT_SUBHEADING, fill=GOLD)
    draw.text((WIDTH // 2 + 280, 470), "with emotional awareness", font=FONT_BODY, fill=GRAY)
    draw.text((WIDTH // 2 + 280, 540), "24/7 availability", font=FONT_SUBHEADING, fill=GOLD)
    draw.text((WIDTH // 2 + 280, 590), "whenever you need support", font=FONT_BODY, fill=GRAY)
    return img


def slide_04_voice() -> Image.Image:
    """Voice Mode."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Step 2: Voice Mode", 80, FONT_TITLE, fill=GOLD)

    # Microphone icon (circle + rectangle)
    cx, cy = WIDTH // 2, 400
    draw.rounded_rectangle([cx - 30, cy - 80, cx + 30, cy + 20], radius=30, fill=CYAN, outline=WHITE, width=2)
    draw.arc([cx - 50, cy - 40, cx + 50, cy + 40], 0, 180, fill=WHITE, width=3)
    draw.line([(cx, cy + 40), (cx, cy + 70)], fill=WHITE, width=3)
    draw.line([(cx - 30, cy + 70), (cx + 30, cy + 70)], fill=WHITE, width=3)

    # Waveform
    _draw_waveform(draw, cx, cy + 150, 600, 80, CYAN)

    _center_text(draw, "Real-Time Voice Sessions", 600, FONT_HEADING, fill=WHITE)
    _center_text(draw, "with Emotional Analysis", 660, FONT_HEADING, fill=CYAN)
    _center_text(draw, "Powered by Azure OpenAI Realtime API", 730, FONT_BODY, fill=GRAY)

    # Feature pills
    pills = ["Pitch Analysis", "Speech Rate", "Pause Detection", "Energy Tracking"]
    pill_y = 810
    total_w = len(pills) * 220
    start_x = (WIDTH - total_w) // 2
    for i, pill in enumerate(pills):
        px = start_x + i * 220
        draw.rounded_rectangle([px, pill_y, px + 200, pill_y + 40], radius=20, fill=None, outline=CYAN, width=1)
        bbox = draw.textbbox((0, 0), pill, font=FONT_LABEL)
        tw = bbox[2] - bbox[0]
        draw.text((px + (200 - tw) // 2, pill_y + 10), pill, font=FONT_LABEL, fill=CYAN)
    return img


def slide_05_metrics() -> Image.Image:
    """Emotional Metrics."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Step 3: Emotional Metrics", 80, FONT_TITLE, fill=GOLD)

    # Main gauge
    _draw_gauge(draw, WIDTH // 2, 450, 160, 0.73, "Emotional Coherence")

    _center_text(draw, "Nevedal Coherence Engine", 620, FONT_HEADING, fill=GOLD)
    _center_text(draw, "Tracking your therapeutic growth over time", 680, FONT_BODY, fill=GRAY)

    # Mini metric cards
    metrics = [
        ("Engagement", "87%", CYAN),
        ("Resilience", "64%", GOLD),
        ("Self-Awareness", "91%", PURPLE),
    ]
    card_w, card_h = 300, 100
    total = len(metrics) * (card_w + 40)
    sx = (WIDTH - total) // 2
    for i, (name, val, color) in enumerate(metrics):
        x = sx + i * (card_w + 40)
        y = 780
        _rounded_rect(draw, (x, y, x + card_w, y + card_h), 12)
        draw.text((x + 20, y + 15), name, font=FONT_SMALL, fill=GRAY)
        draw.text((x + 20, y + 50), val, font=FONT_HEADING, fill=color)
    return img


def slide_06_avatar() -> Image.Image:
    """Avatar Mode."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Step 4: Avatar Mode", 80, FONT_TITLE, fill=GOLD)

    # Avatar representation - large orb with personality
    cx, cy = WIDTH // 2, 420
    _draw_orb(draw, cx, cy, 140, PURPLE)

    # Emotion rings
    for i, (r, c) in enumerate([(180, CYAN), (210, GOLD_DIM), (240, PURPLE)]):
        step = 5
        for angle in range(0, 360, step):
            if (angle // step + i) % 3 != 0:
                continue
            rad = math.radians(angle)
            x = cx + int(r * math.cos(rad))
            y = cy + int(r * math.sin(rad))
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=c)

    _center_text(draw, "Visual Companion Presence", 650, FONT_HEADING, fill=WHITE)
    _center_text(draw, "Nate adapts his expression to match the session's emotional tone", 720, FONT_BODY, fill=GRAY)
    return img


def slide_07_family() -> Image.Image:
    """Family Sanctuary."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Step 5: Family Sanctuary", 80, FONT_TITLE, fill=GOLD)

    # Family tree representation
    cx, cy = WIDTH // 2, 380
    # Parent node
    _draw_orb(draw, cx, cy - 60, 40, GOLD)
    draw.text((cx - 30, cy - 15), "Parent", font=FONT_LABEL, fill=GOLD)

    # Children nodes
    positions = [(cx - 200, cy + 100), (cx, cy + 100), (cx + 200, cy + 100)]
    labels = ["Child 1", "Child 2", "Coach"]
    colors = [CYAN, CYAN, PURPLE]
    for (px, py), label, color in zip(positions, labels, colors):
        # Connecting line
        draw.line([(cx, cy + 10), (px, py - 30)], fill=DARK_GRAY, width=2)
        _draw_orb(draw, px, py, 30, color)
        bbox = draw.textbbox((0, 0), label, font=FONT_LABEL)
        tw = bbox[2] - bbox[0]
        draw.text((px - tw // 2, py + 35), label, font=FONT_LABEL, fill=color)

    _center_text(draw, "Connected Care for the Whole Family", 580, FONT_HEADING, fill=WHITE)
    _center_text(draw, "Individual privacy preserved within shared therapeutic space", 650, FONT_BODY, fill=GRAY)

    # Feature list
    features = [
        "Shared progress insights for guardians",
        "Independent sessions for each family member",
        "Coach oversight with privacy boundaries",
    ]
    for i, f in enumerate(features):
        draw.text((WIDTH // 2 - 250, 740 + i * 40), f"  {f}", font=FONT_BODY, fill=GRAY)
    return img


def slide_08_tiers() -> Image.Image:
    """Tier Selection."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Step 6: Choose Your Path", 60, FONT_TITLE, fill=GOLD)

    _draw_tier_card(draw, 150, 180, "THRESHOLD", "Free Trial", [
        "Chat with Nate",
        "Basic voice sessions",
        "Emotional check-ins",
        "7-day full access",
    ])

    _draw_tier_card(draw, 770, 180, "INNER CHAMBER", "$49/mo", [
        "Unlimited chat & voice",
        "Full emotional metrics",
        "Avatar mode",
        "Family Sanctuary",
        "Priority support",
    ], highlight=True)

    _draw_tier_card(draw, 1390, 180, "SOVEREIGN CIRCLE", "$149/mo", [
        "Everything in Inner Chamber",
        "Live coaching sessions",
        "Advanced analytics",
        "Night School access",
        "Dedicated coach pairing",
    ])

    _center_text(draw, "Every journey begins with a single step", 920, FONT_BODY, fill=GOLD_DIM)
    return img


def slide_09_skyeye_dashboard() -> Image.Image:
    """SkyEye Dashboard - TikTok connection."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "SkyEye Social Media Command Center", 40, FONT_TITLE, fill=GOLD)

    # Platform grid
    platforms = [
        ("TikTok", "TT", False, None),
        ("YouTube", "YT", True, {"Subscribers": "Growing", "Videos": "3"}),
        ("Instagram", "IG", False, None),
        ("Facebook", "FB", False, None),
        ("Reddit", "RD", False, None),
        ("LinkedIn", "LI", False, None),
        ("Pinterest", "PI", False, None),
    ]

    cols = 4
    card_w, card_h = 240, 180
    gap = 30
    total_row_w = cols * card_w + (cols - 1) * gap
    sx = (WIDTH - total_row_w) // 2

    for i, (name, icon, connected, stats) in enumerate(platforms):
        col = i % cols
        row = i // cols
        x = sx + col * (card_w + gap)
        y = 140 + row * (card_h + gap)
        # Highlight TikTok
        if name == "TikTok":
            draw.rounded_rectangle([x - 4, y - 4, x + card_w + 4, y + card_h + 4],
                                   radius=14, fill=None, outline=GOLD, width=3)
        _draw_platform_card(draw, x, y, name, icon, connected, stats)

    # Arrow pointing to TikTok
    draw.text((sx - 20, 140 + card_h + 20), ">>>  Click Connect to begin TikTok OAuth", font=FONT_BODY, fill=GOLD)

    _center_text(draw, "Manage all 7 platforms from one dashboard", 920, FONT_BODY, fill=GRAY)
    return img


def slide_10_oauth() -> Image.Image:
    """TikTok OAuth authorization flow."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "TikTok OAuth Authorization", 60, FONT_TITLE, fill=GOLD)

    # Mock TikTok auth screen
    cx = WIDTH // 2
    bx, by = cx - 300, 160
    bw, bh = 600, 700

    # TikTok-style dark card
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=20, fill=(22, 22, 22), outline=(50, 50, 50), width=2)

    # TikTok logo area
    draw.rounded_rectangle([cx - 40, by + 30, cx + 40, by + 90], radius=12, fill=(0, 0, 0), outline=WHITE)
    draw.text((cx - 25, by + 42), "TT", font=FONT_HEADING, fill=WHITE)

    draw.text((bx + 100, by + 110), "Sovereign Sanctuary wants to", font=FONT_BODY, fill=WHITE)
    draw.text((bx + 100, by + 145), "access your TikTok account", font=FONT_BODY, fill=WHITE)

    # Scopes list
    scopes = [
        ("user.info.basic", "View your profile info"),
        ("video.publish", "Publish videos on your behalf"),
        ("video.list", "View your video list"),
        ("comment.list", "Read comments on your videos"),
        ("comment.list.manage", "Manage and reply to comments"),
    ]
    sy = by + 210
    for scope, desc in scopes:
        # Checkmark
        draw.text((bx + 40, sy), "[OK]", font=FONT_LABEL, fill=(0, 200, 0))
        draw.text((bx + 90, sy), scope, font=FONT_SUBHEADING, fill=WHITE)
        draw.text((bx + 90, sy + 28), desc, font=FONT_SMALL, fill=GRAY)
        sy += 70

    # Authorize button
    draw.rounded_rectangle([bx + 80, by + bh - 100, bx + bw - 80, by + bh - 45],
                           radius=25, fill=(254, 44, 85), outline=None)
    bbox = draw.textbbox((0, 0), "Authorize App", font=FONT_SUBHEADING)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, by + bh - 92), "Authorize App", font=FONT_SUBHEADING, fill=WHITE)

    return img


def slide_11_connected() -> Image.Image:
    """TikTok connected with stats."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "TikTok Connected", 60, FONT_TITLE, fill=(0, 200, 0))

    # Large connected card
    cx = WIDTH // 2
    _rounded_rect(draw, (cx - 400, 170, cx + 400, 650), 20, fill=CARD_BG, outline=(0, 180, 0))

    # TikTok header
    draw.text((cx - 360, 200), "TT", font=FONT_BIG_TITLE, fill=WHITE)
    draw.text((cx - 240, 230), "TikTok", font=FONT_TITLE, fill=WHITE)
    _draw_status_dot(draw, cx + 340, 240, (0, 220, 0), r=12)
    draw.text((cx + 200, 260), "Connected", font=FONT_SMALL, fill=(0, 200, 0))

    # Stats grid
    stats = [
        ("Followers", "0", CYAN),
        ("Engagement", "0%", GOLD),
        ("Videos", "0", PURPLE),
        ("Likes", "0", RED),
    ]
    sy = 350
    for i, (label, val, color) in enumerate(stats):
        x = cx - 350 + (i % 2) * 380
        y = sy + (i // 2) * 120
        _rounded_rect(draw, (x, y, x + 340, y + 100), 12)
        draw.text((x + 20, y + 15), label, font=FONT_SMALL, fill=GRAY)
        draw.text((x + 20, y + 45), val, font=FONT_HEADING, fill=color)

    # Mode selector
    _center_text(draw, "Control Mode", 700, FONT_SUBHEADING, fill=GRAY)
    modes = ["Full Autonomy", "Approval Required", "Observation Only"]
    mode_x = cx - 450
    for i, mode in enumerate(modes):
        mx = mode_x + i * 310
        selected = i == 1
        color = GOLD if selected else DARK_GRAY
        draw.rounded_rectangle([mx, 750, mx + 290, 800], radius=20,
                               fill=(25, 22, 12) if selected else BG_ELEVATED, outline=color)
        bbox = draw.textbbox((0, 0), mode, font=FONT_SMALL)
        tw = bbox[2] - bbox[0]
        draw.text((mx + (290 - tw) // 2, 765), mode, font=FONT_SMALL, fill=color)

    _center_text(draw, "Real-time stats pulled from TikTok API", 920, FONT_BODY, fill=GRAY)
    return img


def slide_12_content_creation() -> Image.Image:
    """AI content generation for TikTok."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "AI Content Generation", 60, FONT_TITLE, fill=GOLD)

    # Generator panel
    _rounded_rect(draw, (100, 160, WIDTH - 100, 900), 20)

    # Platform selector
    draw.text((140, 190), "Platform:", font=FONT_BODY, fill=GRAY)
    draw.rounded_rectangle([300, 180, 540, 225], radius=8, fill=BG_ELEVATED, outline=GOLD)
    draw.text((320, 188), "TikTok", font=FONT_BODY, fill=WHITE)

    # Topic input
    draw.text((140, 260), "Topic:", font=FONT_BODY, fill=GRAY)
    draw.rounded_rectangle([300, 250, 900, 295], radius=8, fill=BG_ELEVATED, outline=CARD_BORDER)
    draw.text((320, 258), "Managing anxiety through small daily wins", font=FONT_BODY, fill=WHITE)

    # Generated content preview
    draw.text((140, 340), "Generated Content:", font=FONT_BODY, fill=GOLD)
    _rounded_rect(draw, (140, 380, WIDTH - 140, 620), 12, fill=BG_ELEVATED)

    content_lines = [
        "Small wins build big resilience.",
        "",
        "Today I want to talk about something",
        "that changed everything for me:",
        "celebrating the tiny victories.",
        "",
        "That morning coffee you made?",
        "That walk you took? Those count.",
    ]
    for i, line in enumerate(content_lines):
        draw.text((180, 400 + i * 28), line, font=FONT_BODY, fill=WHITE)

    # TikTok voice specs
    draw.text((140, 660), "TikTok Voice Profile:", font=FONT_SUBHEADING, fill=CYAN)
    specs = [
        "Tone: casual, punchy, visual-first",
        "Max length: 150 characters",
        "Style: hook in first line, emoji-light",
    ]
    for i, s in enumerate(specs):
        draw.text((160, 710 + i * 32), s, font=FONT_BODY, fill=GRAY)

    # Generate button
    draw.rounded_rectangle([WIDTH - 500, 820, WIDTH - 140, 870], radius=25, fill=CYAN)
    draw.text((WIDTH - 420, 832), "Generate with AI", font=FONT_SUBHEADING, fill=BG_VOID)

    return img


def slide_13_content_queue() -> Image.Image:
    """Content queue with draft TikTok post."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Content Review Queue", 60, FONT_TITLE, fill=GOLD)

    # Queue table header
    headers = ["Status", "Platform", "Content Preview", "Scheduled", "Actions"]
    widths = [120, 120, 700, 200, 340]
    hx = 120
    hy = 160
    for h, w in zip(headers, widths):
        draw.text((hx + 10, hy), h, font=FONT_SMALL, fill=GOLD)
        hx += w
    draw.line([(120, hy + 30), (WIDTH - 120, hy + 30)], fill=CARD_BORDER, width=1)

    # Queue rows
    rows = [
        ("DRAFT", "TT", "Small wins build big resilience. Today I want to...", "Not set", True),
        ("SCHEDULED", "YT", "Community post: 3 breathing techniques for anxiety", "Feb 14, 9am", False),
        ("POSTED", "YT", "How the Nevedal Coherence Engine works", "Feb 12, 2pm", False),
    ]
    for i, (status, plat, preview, sched, highlight) in enumerate(rows):
        ry = hy + 50 + i * 90
        if highlight:
            draw.rounded_rectangle([115, ry - 5, WIDTH - 115, ry + 75], radius=8,
                                   fill=(25, 22, 12), outline=GOLD, width=1)
        rx = 120
        # Status pill
        status_colors = {"DRAFT": GOLD, "SCHEDULED": CYAN, "POSTED": (0, 200, 0)}
        sc = status_colors.get(status, GRAY)
        draw.rounded_rectangle([rx + 5, ry + 10, rx + 100, ry + 40], radius=12, fill=None, outline=sc)
        draw.text((rx + 15, ry + 14), status, font=FONT_LABEL, fill=sc)
        rx += 120
        # Platform
        draw.text((rx + 10, ry + 15), plat, font=FONT_BODY, fill=WHITE)
        rx += 120
        # Preview
        draw.text((rx + 10, ry + 15), preview[:70], font=FONT_SMALL, fill=WHITE)
        rx += 700
        # Scheduled
        draw.text((rx + 10, ry + 15), sched, font=FONT_SMALL, fill=GRAY)
        rx += 200
        # Actions
        if status == "DRAFT":
            draw.rounded_rectangle([rx, ry + 5, rx + 100, ry + 40], radius=8, fill=(0, 150, 0))
            draw.text((rx + 12, ry + 10), "Approve", font=FONT_SMALL, fill=WHITE)
            draw.rounded_rectangle([rx + 115, ry + 5, rx + 230, ry + 40], radius=8, fill=None, outline=CYAN)
            draw.text((rx + 125, ry + 10), "Schedule", font=FONT_SMALL, fill=CYAN)

    # Admin note
    _center_text(draw, "Administrators approve all content before it goes live", 850, FONT_BODY, fill=GRAY)
    return img


def slide_14_publishing() -> Image.Image:
    """Post published to TikTok."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Published to TikTok", 60, FONT_TITLE, fill=(0, 200, 0))

    # Success card
    cx = WIDTH // 2
    _rounded_rect(draw, (cx - 400, 170, cx + 400, 750), 20, fill=CARD_BG, outline=(0, 180, 0))

    # Checkmark
    draw.ellipse([cx - 50, 200, cx + 50, 300], fill=(0, 150, 0))
    draw.text((cx - 20, 218), "OK", font=FONT_HEADING, fill=WHITE)

    draw.text((cx - 350, 340), "Post Details", font=FONT_HEADING, fill=WHITE)
    details = [
        ("Platform", "TikTok"),
        ("Content", "Small wins build big resilience..."),
        ("Type", "Video (PULL_FROM_URL)"),
        ("Privacy", "PUBLIC_TO_EVERYONE"),
        ("Duet", "Enabled"),
        ("Comments", "Enabled"),
        ("Stitch", "Enabled"),
        ("External Post ID", "tt_7483920184756..."),
        ("AIGC Label", "Applied (TikTok policy compliant)"),
    ]
    for i, (k, v) in enumerate(details):
        y = 400 + i * 36
        draw.text((cx - 350, y), k + ":", font=FONT_BODY, fill=GRAY)
        color = (0, 200, 0) if k == "AIGC Label" else WHITE
        draw.text((cx - 50, y), v, font=FONT_BODY, fill=color)

    # Compliance note
    _rounded_rect(draw, (cx - 380, 680, cx + 380, 730), 8, fill=(20, 30, 20), outline=(0, 150, 0))
    _center_text(draw, "AIGC disclosure applied per TikTok AI content policy", 692, FONT_SMALL, fill=(0, 200, 0))

    _center_text(draw, "Content posted via TikTok Content Posting API v2", 900, FONT_BODY, fill=GRAY)
    return img


def slide_15_moderation() -> Image.Image:
    """Comment moderation panel."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    _center_text(draw, "Inbound Moderation & Safety", 60, FONT_TITLE, fill=GOLD)

    # Two-column layout
    left_x, right_x = 80, WIDTH // 2 + 40
    panel_w = WIDTH // 2 - 120

    # Left: Comment monitoring
    _rounded_rect(draw, (left_x, 150, left_x + panel_w, 600), 16)
    draw.text((left_x + 20, 170), "Comment Monitor", font=FONT_SUBHEADING, fill=CYAN)

    comments = [
        ("@user123", "This is amazing! Love this content", (0, 200, 0), "Safe"),
        ("@bot_acct", "Check my profile for free followers!!", RED, "Bot detected"),
        ("@troll99", "[hostile content blocked]", RED, "Cyberbullying"),
        ("@real_fan", "Can you make more of these?", (0, 200, 0), "Safe"),
    ]
    cy = 220
    for handle, text, color, status in comments:
        draw.text((left_x + 20, cy), handle, font=FONT_SMALL, fill=color)
        draw.text((left_x + 150, cy), text[:45], font=FONT_SMALL, fill=WHITE if color != RED else RED)
        draw.text((left_x + panel_w - 160, cy), status, font=FONT_LABEL, fill=color)
        cy += 60
        draw.line([(left_x + 20, cy - 15), (left_x + panel_w - 20, cy - 15)], fill=CARD_BORDER)

    # Right: Safety systems
    _rounded_rect(draw, (right_x, 150, right_x + panel_w, 600), 16)
    draw.text((right_x + 20, 170), "Safety Systems", font=FONT_SUBHEADING, fill=GOLD)

    systems = [
        ("Bot Detection", "ML-based scoring (account age, pattern, timing)", CYAN),
        ("Cyberbullying Filter", "Hostile content auto-blocked + logged", RED),
        ("Influencer Detection", "High-follower accounts get special handling", PURPLE),
        ("Prompt Injection Guard", "Jailbreak/manipulation attempts blocked", RED),
        ("Enforcement Ladder", "Delete -> Hide -> Escalate to admin", GOLD),
        ("AIGC Compliance", "AI content labeled per TikTok policy", (0, 200, 0)),
    ]
    sy = 230
    for name, desc, color in systems:
        _draw_status_dot(draw, right_x + 30, sy + 8, color, r=6)
        draw.text((right_x + 50, sy), name, font=FONT_BODY, fill=WHITE)
        draw.text((right_x + 50, sy + 28), desc, font=FONT_SMALL, fill=GRAY)
        sy += 62

    # Daily stats bar
    _rounded_rect(draw, (80, 640, WIDTH - 80, 900), 16)
    draw.text((120, 660), "Daily Moderation Summary", font=FONT_SUBHEADING, fill=GOLD)

    stat_items = [
        ("Comments Scanned", "247", CYAN),
        ("Bots Blocked", "12", RED),
        ("Threats Neutralized", "3", RED),
        ("Safe Engagements", "232", (0, 200, 0)),
        ("Avg Response Time", "< 2 min", GOLD),
    ]
    sx = 120
    for label, val, color in stat_items:
        draw.text((sx, 720), val, font=FONT_HEADING, fill=color)
        draw.text((sx, 775), label, font=FONT_SMALL, fill=GRAY)
        sx += 330
    return img


def slide_16_end() -> Image.Image:
    """End card."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    # Shield (same as title)
    cx, cy = WIDTH // 2, 300
    pts = [(cx, cy - 80), (cx + 70, cy - 50), (cx + 60, cy + 40), (cx, cy + 80),
           (cx - 60, cy + 40), (cx - 70, cy - 50)]
    draw.polygon(pts, fill=GOLD_DIM, outline=GOLD)

    _center_text(draw, "SOVEREIGN SANCTUARY", 420, FONT_BIG_TITLE, fill=GOLD)
    _center_text(draw, "x  TikTok", 540, FONT_TITLE, fill=WHITE)

    draw.line([(WIDTH // 2 - 200, 640), (WIDTH // 2 + 200, 640)], fill=GOLD_DIM, width=1)

    _center_text(draw, "Building a safer, more connected", 680, FONT_HEADING, fill=GRAY)
    _center_text(draw, "therapeutic community", 740, FONT_HEADING, fill=GRAY)

    _center_text(draw, "app.sovereignsanctuary.net", 850, FONT_BODY, fill=GOLD)
    _center_text(draw, "contact@sovereignsanctuary.net", 900, FONT_SMALL, fill=GRAY)
    return img


# ---------------------------------------------------------------------------
# Narration scripts
# ---------------------------------------------------------------------------
NARRATIONS = [
    # 1 - Title
    "Welcome to Sovereign Sanctuary. An AI-powered therapeutic platform, powered by Little Nate.",
    # 2 - Welcome Gate
    "When users first open the app, they're greeted by Little Nate, their AI therapy companion. This is the welcome gate where the guided tour begins.",
    # 3 - Chat
    "Users can chat with Nate through a secure text interface. Every conversation is private, encrypted, and clinically informed.",
    # 4 - Voice
    "Nate also offers real-time voice sessions with emotional analysis, powered by Azure OpenAI's realtime voice API.",
    # 5 - Metrics
    "The Nevedal Coherence Engine tracks emotional growth over time, providing users with meaningful insights into their therapeutic journey.",
    # 6 - Avatar
    "Avatar mode gives Nate a visual presence, creating a more immersive companion experience.",
    # 7 - Family
    "Family Sanctuary connects the whole family in a shared therapeutic space, with individual privacy preserved.",
    # 8 - Tiers
    "Users choose their tier, from the free Threshold trial, to Inner Chamber, to the premium Sovereign Circle.",
    # 9 - SkyEye
    "Now let's look at the TikTok integration. From the SkyEye dashboard, administrators connect Little Nate to TikTok.",
    # 10 - OAuth
    "The OAuth flow requests specific scopes: user info, video publishing, and comment management. Users authorize securely through TikTok's own consent screen.",
    # 11 - Connected
    "Once connected, the dashboard shows live stats, followers, engagement rate, and post count, all pulled from the TikTok API.",
    # 12 - Content Creation
    "Little Nate generates TikTok-optimized content using AI. Short, punchy, visual-first. Matching TikTok's native voice while staying clinically appropriate.",
    # 13 - Queue
    "Generated content enters a review queue. Administrators can approve, edit, schedule, or reject posts before they go live.",
    # 14 - Publishing
    "Approved content is published through TikTok's Content Posting API with proper AIGC disclosure labels, as required by TikTok policy.",
    # 15 - Moderation
    "Inbound comments are monitored in real-time. Bot detection, cyberbullying filters, and an enforcement ladder keep the community safe.",
    # 16 - End
    "Sovereign Sanctuary and TikTok. Building a safer, more connected therapeutic community. Visit app.sovereignsanctuary.net.",
]

# ---------------------------------------------------------------------------
# TTS Generation
# ---------------------------------------------------------------------------

def generate_tts(text: str, output_path: Path) -> float:
    """Generate TTS audio via Azure OpenAI Mini TTS and return duration in seconds."""
    print(f"  Generating TTS: {output_path.name} ...")
    headers = {
        "api-key": AZURE_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "model": MINI_TTS_DEPLOYMENT,
        "input": text,
        "voice": "echo",
        "response_format": "mp3",
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(MINI_TTS_URL, headers=headers, json=body)
        if resp.status_code != 200:
            print(f"  ERROR: TTS returned {resp.status_code}: {resp.text[:200]}")
            # Create 3 seconds of silence as fallback
            return _create_silence(output_path, 3.0)
        output_path.write_bytes(resp.content)

    # Get duration using moviepy
    from moviepy import AudioFileClip
    clip = AudioFileClip(str(output_path))
    dur = clip.duration
    clip.close()
    print(f"  Audio duration: {dur:.1f}s")
    return dur


def _create_silence(output_path: Path, duration: float) -> float:
    """Create a silent MP3 file as fallback."""
    # Use moviepy to create silence
    import numpy as np
    from moviepy import AudioClip
    silence = AudioClip(lambda t: [0, 0], duration=duration, fps=44100)
    silence = silence.with_fps(44100)
    silence.write_audiofile(str(output_path), codec="libmp3lame", verbose=False, logger=None)
    silence.close()
    return duration


# ---------------------------------------------------------------------------
# Video assembly
# ---------------------------------------------------------------------------

def generate_video():
    """Main entry point: generate all slides, TTS, and assemble MP4."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    # --- Slide renderers ---
    slide_funcs = [
        slide_01_title, slide_02_welcome_gate, slide_03_chat, slide_04_voice,
        slide_05_metrics, slide_06_avatar, slide_07_family, slide_08_tiers,
        slide_09_skyeye_dashboard, slide_10_oauth, slide_11_connected,
        slide_12_content_creation, slide_13_content_queue, slide_14_publishing,
        slide_15_moderation, slide_16_end,
    ]

    # --- Step 1: Generate TTS for all slides ---
    print("\n=== Generating TTS narration (echo voice) ===")
    audio_paths = []
    audio_durations = []
    for i, narration in enumerate(NARRATIONS):
        audio_path = AUDIO_DIR / f"slide_{i + 1:02d}.mp3"
        if audio_path.exists():
            # Re-use existing
            from moviepy import AudioFileClip
            clip = AudioFileClip(str(audio_path))
            dur = clip.duration
            clip.close()
            print(f"  Reusing {audio_path.name} ({dur:.1f}s)")
        else:
            dur = generate_tts(narration, audio_path)
        audio_paths.append(audio_path)
        audio_durations.append(dur)

    # --- Step 2: Render slide frames ---
    print("\n=== Rendering slide frames ===")
    slides = []
    for i, func in enumerate(slide_funcs):
        print(f"  Rendering slide {i + 1}/{len(slide_funcs)}: {func.__doc__}")
        img = func()
        slides.append(img)

    # --- Step 3: Assemble video with moviepy ---
    print("\n=== Assembling video ===")
    import numpy as np
    from moviepy import (
        ImageClip,
        AudioFileClip,
        concatenate_videoclips,
        concatenate_audioclips,
        CompositeAudioClip,
    )

    video_clips = []
    audio_clips = []

    for i, (slide_img, dur) in enumerate(zip(slides, audio_durations)):
        # Add 0.5s padding after audio
        slide_dur = dur + 0.5

        # Convert PIL to numpy
        frame = np.array(slide_img)

        # Create image clip
        clip = ImageClip(frame, duration=slide_dur)

        # Add fade in/out (0.5s each)
        clip = clip.with_effects([
            # We'll do manual fade via crossfade in concatenation
        ])

        video_clips.append(clip)

        # Audio clip
        audio_clip = AudioFileClip(str(audio_paths[i]))
        audio_clips.append(audio_clip)

    # Concatenate video with crossfade
    # Simple approach: concatenate with padding="none" and handle transitions
    final_video = concatenate_videoclips(video_clips, method="compose")

    # Concatenate audio with small gaps
    # Build audio track with proper timing offsets
    timed_audio_clips = []
    current_time = 0.0
    for i, (a_clip, dur) in enumerate(zip(audio_clips, audio_durations)):
        timed_clip = a_clip.with_start(current_time)
        timed_audio_clips.append(timed_clip)
        current_time += dur + 0.5  # match the slide duration

    combined_audio = CompositeAudioClip(timed_audio_clips)
    final_video = final_video.with_audio(combined_audio)

    # --- Step 4: Write output ---
    print(f"\n=== Writing MP4 to {OUTPUT_PATH} ===")
    final_video.write_videofile(
        str(OUTPUT_PATH),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
        logger="bar",
    )

    # Cleanup
    final_video.close()
    for c in audio_clips:
        c.close()

    print(f"\n=== DONE! Video saved to: {OUTPUT_PATH} ===")
    print(f"    Duration: {sum(d + 0.5 for d in audio_durations):.1f}s")
    print(f"    Resolution: {WIDTH}x{HEIGHT}")
    print(f"    Upload this file to TikTok's developer portal.")


if __name__ == "__main__":
    generate_video()
