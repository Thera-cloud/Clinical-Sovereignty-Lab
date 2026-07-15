"""Sovereign Sanctuary LinkedIn infographic brand system (Gemini reference images)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

# Canonical reference filenames under SKYEYE_LINKEDIN_BRAND_DIR
LOGO_REF = "logo_s_reference.png"
STYLE_LEADERSHIP_REF = "style_infographic_leadership.png"
STYLE_PRODUCT_REF = "style_infographic_product.png"

_DEFAULT_BRAND_DIR = (
    Path(__file__).resolve().parents[1] / "resources" / "skyeye" / "linkedin_brand"
)

_SIGNATURE_LINE = (
    "Nathaniel Nevedal reviewed + approved | by Little Nate, your AI companion"
)


def brand_dir() -> Path:
    raw = os.getenv("SKYEYE_LINKEDIN_BRAND_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_BRAND_DIR


def brand_refs_enabled() -> bool:
    return os.getenv("SKYEYE_LINKEDIN_BRAND_REFS", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def load_brand_reference_images() -> List[Tuple[bytes, str]]:
    """Logo + style guides for Gemini high-fidelity / layout reference."""
    if not brand_refs_enabled():
        return []
    base = brand_dir()
    refs: List[Tuple[bytes, str]] = []
    for name in (LOGO_REF, STYLE_LEADERSHIP_REF, STYLE_PRODUCT_REF):
        path = base / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        refs.append((data, mime))
    return refs


def _first_sentence(text: str, max_len: int = 120) -> str:
    chunk = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    chunk = re.sub(r"\s+", " ", chunk).strip()
    if len(chunk) > max_len:
        chunk = chunk[: max_len - 3].rsplit(" ", 1)[0] + "..."
    return chunk


def _takeaway_line(text: str) -> str:
    m = re.search(r"(?i)takeaway\s*:\s*(.+?)(?:\n\n|\nNathaniel|$)", text, re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip())[:220]
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    for p in reversed(paras):
        if "reviewed + approved" in p.lower():
            continue
        if len(p) > 40:
            return p[:220]
    return "Authentic leadership happens in the honest space between questions and answers."


def _callout_phrases(text: str) -> Tuple[str, str]:
    """Two short annotation lines beside the logo."""
    lower = text.lower()
    if "presence" in lower or "honest" in lower:
        return ("Silence is honest, not empty.", "Genuine presence.")
    if "ai" in lower or "companion" in lower:
        return ("Human oversight matters.", "AI with accountability.")
    return ("Show up honestly.", "Lead with presence.")


def _sidebar_title(text: str) -> str:
    lower = text.lower()
    if "ai" in lower or "emotional intelligence" in lower or " ei " in f" {lower} ":
        return "EI IN THE AGE OF AI"
    if "coach" in lower or "therapy" in lower:
        return "CLINICAL OVERSIGHT"
    return "SOVEREIGN SANCTUARY"


def extract_infographic_copy(post_text: str) -> dict:
    body = (post_text or "").strip()
    body_no_sig = re.sub(
        r"\n*Nathaniel[^\n]*reviewed \+ approved[^\n]*$",
        "",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    headline = _first_sentence(body_no_sig).upper()
    takeaway = _takeaway_line(body)
    c1, c2 = _callout_phrases(body_no_sig)
    return {
        "headline": headline,
        "takeaway": takeaway,
        "callout_1": c1,
        "callout_2": c2,
        "sidebar_title": _sidebar_title(body_no_sig),
        "footer": _SIGNATURE_LINE,
    }


def build_branded_image_prompt(
    post_text: str,
    *,
    lane: str = "",
    slot_key: str = "",
) -> str:
    """Prompt for 16:9 LinkedIn infographic matching Sovereign Sanctuary brand refs."""
    copy = extract_infographic_copy(post_text)
    lane_note = f"Campaign lane {lane}. " if lane else ""
    slot_note = f"Slot {slot_key}. " if slot_key else ""
    return (
        "Create a professional LinkedIn feed infographic in EXACTLY the visual system "
        "shown in the attached style reference images. "
        f"{lane_note}{slot_note}"
        "LAYOUT (adapt the vertical reference to a wide 16:9 landscape canvas): "
        "dark charcoal textured background with subtle gold corner accents; "
        "large centered 3D metallic gold-and-silver intertwined S logo (match logo reference exactly); "
        "thin white/gold callout lines from the logo to short phrases; "
        "elegant gold serif headline band across the top; "
        "left text panel with gold border and white body copy with gold keyword highlights; "
        "right sidebar panel with dark frame and gold title; "
        "horizontal gold takeaway bar above the footer; "
        "footer line with small LN microchip icon. "
        "Typography must be crisp and legible. "
        "Use this copy (paraphrase body from post theme if needed, keep structure): "
        f"HEADLINE: {copy['headline']} "
        f"CALLOUT 1: {copy['callout_1']} "
        f"CALLOUT 2: {copy['callout_2']} "
        f"SIDEBAR TITLE: {copy['sidebar_title']} "
        f"BODY THEME: {post_text[:500]} "
        f"TAKEAWAY BAR: Takeaway: {copy['takeaway']} "
        f"FOOTER: {copy['footer']} "
        "Do not use banned words: liminal, threshold, aching. "
        "Premium executive aesthetic — Sovereign Sanctuary / Little Nate brand."
    )
