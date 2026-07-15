"""Journey Recap / Thera-World trailer: transcript → scene summaries → render → stitch (≤2 min)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

import aiohttp

from app.sse.infrastructure import r2_storage

logger = logging.getLogger(__name__)

DEFAULT_TARGET_DURATION = 30
DEFAULT_SEGMENT_COUNT = 4
MIN_RECAP_DURATION = 15
MAX_RECAP_DURATION = 600
MAX_TRAILER_DURATION = 120
TRAILER_CLIP_ROUND_DROP_MAX = 4
TARGET_SEGMENT_SECONDS = 7.5
MIN_SEGMENT_COUNT = 3
MAX_SEGMENT_COUNT = 16
# Long-source reliability: Whisper ffmpeg slices + hierarchical LLM compress.
WHISPER_CHUNK_SECONDS = 60
WHISPER_SINGLE_SHOT_MAX_SECONDS = 45
TRAILER_TRANSCRIPT_DIRECT_MAX_CHARS = 7000
TRAILER_TRANSCRIPT_MAP_CHUNK_CHARS = 4500
TRAILER_MAP_SUMMARY_CHARS = 500
STUDIO_READY_STATUSES = frozenset(
    {"aligning", "rendering", "clips_ready", "stitching", "complete"},
)
STUDIO_PIPELINE_DONE_STATUSES = frozenset({"complete", "failed"})
FEATURE_FLAG = "ENABLE_JOURNEY_RECAP_VIDEO"
INGEST_MODE_AUDIO = "audio_driven"
INGEST_MODE_PANEL = "panel_aligned"


def normalize_ingest_mode(mode: Optional[str]) -> str:
    """Validate video ingest mode from Studio UI."""
    m = (mode or INGEST_MODE_AUDIO).strip().lower()
    if m in (INGEST_MODE_PANEL, "panels", "journey_panels", "panel"):
        return INGEST_MODE_PANEL
    return INGEST_MODE_AUDIO


def feature_enabled() -> bool:
    return os.getenv(FEATURE_FLAG, "false").strip().lower() in ("1", "true", "yes")


def _json_safe(val: Any) -> Any:
    """Make asyncpg rows JSON-serializable (datetime → ISO strings)."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, dict):
        return {k: _json_safe(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_json_safe(v) for v in val]
    return val


async def resolve_recap_user_id(conn, user_id: str) -> str:
    """Map login username to hardware_id when SSE panels are stored there."""
    uid = (user_id or "").strip()
    if not uid:
        return uid
    row = await conn.fetchrow(
        """
        SELECT username, hardware_id
        FROM users
        WHERE LOWER(username) = LOWER($1) OR hardware_id = $1
        LIMIT 1
        """,
        uid,
    )
    if row and row.get("hardware_id"):
        return str(row["hardware_id"]).strip()
    return uid


_R2_BUCKET = os.getenv("R2_BUCKET_NAME", os.getenv("R2_DEFAULT_BUCKET", "nate-vault")).strip()
_R2_CDN_BASE = os.getenv("R2_CDN_BASE_URL", "https://vault.sovereign-sanctuary.com").rstrip("/")
_PANEL_URL_TTL = int(os.getenv("JOURNEY_RECAP_PANEL_URL_TTL", "604800"))  # 7 days for Studio previews


def _r2_key_from_url(url: Optional[str]) -> Optional[str]:
    """Extract object key from presigned R2 URL or CDN URL."""
    if not url:
        return None
    base = str(url).split("?", 1)[0].strip()
    if not base:
        return None
    marker = f"/{_R2_BUCKET}/"
    if marker in base:
        return base.split(marker, 1)[1]
    if _R2_CDN_BASE and base.startswith(f"{_R2_CDN_BASE}/"):
        return base[len(_R2_CDN_BASE) + 1 :]
    if base.startswith("mock://r2-not-configured/"):
        return base.split("mock://r2-not-configured/", 1)[1]
    return None


def refresh_panel_r2_url(
    url: Optional[str],
    *,
    expires_in: Optional[int] = None,
    r2_key: Optional[str] = None,
) -> Optional[str]:
    """Re-sign Thera-World panel URLs — sse_panel_log stores 24h presigned URLs that expire."""
    key = (r2_key or "").strip() or _r2_key_from_url(url)
    if not key:
        return url
    ttl = expires_in if expires_in is not None else _PANEL_URL_TTL
    try:
        fresh = r2_storage.presigned_url(key, expires_in=ttl)
        if fresh:
            return fresh
    except Exception as exc:
        logger.warning("refresh_panel_r2_url failed for %s: %s", key, exc)
    return url


def _refresh_panels_r2_urls(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for panel in panels:
        row = dict(panel)
        raw = row.get("r2_url")
        if raw:
            row["r2_key"] = _r2_key_from_url(raw)
            row["r2_url"] = refresh_panel_r2_url(raw)
        refreshed.append(row)
    return refreshed


def segment_duration(target_duration: int, segment_count: int) -> float:
    if segment_count < 1:
        segment_count = DEFAULT_SEGMENT_COUNT
    return round(float(target_duration) / float(segment_count), 3)


def ffprobe_media_duration_seconds(path: str) -> float | None:
    """Return media duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as exc:
        logger.warning("ffprobe duration failed for %s: %s", path, exc)
    return None


def plan_segments_for_duration(duration_seconds: float) -> tuple[int, int]:
    """Legacy helper — prefer plan_trailer_segment_durations for audio-driven ingest."""
    target, durations = plan_trailer_segment_durations(duration_seconds)
    return target, len(durations)


def plan_trailer_segment_durations(source_duration_seconds: float) -> tuple[int, list[int]]:
    """
    Plan ordered trailer clip lengths (10s or 30s grid, max 2 minutes).

    Source > 60s uses 30s blocks; otherwise 10s blocks. Trailing 1–4s are dropped;
    5–9s tail becomes a short final clip (e.g. 95s → 30+30+30+5).
    """
    src = float(source_duration_seconds or DEFAULT_TARGET_DURATION)
    if src < 1:
        src = float(DEFAULT_TARGET_DURATION)
    block = 30 if src > 60 else 10
    raw_target = min(MAX_TRAILER_DURATION, max(MIN_RECAP_DURATION, int(round(src))))
    segments: list[int] = []
    remaining = raw_target
    while remaining >= block:
        segments.append(block)
        remaining -= block
    if remaining == 0:
        pass
    elif 1 <= remaining <= TRAILER_CLIP_ROUND_DROP_MAX:
        pass
    elif remaining >= 5:
        if block == 30:
            if remaining < 10:
                segments.append(remaining)
            else:
                segments.append(10)
                tail = remaining - 10
                if tail == 0:
                    pass
                elif 1 <= tail <= TRAILER_CLIP_ROUND_DROP_MAX:
                    pass
                elif tail >= 5:
                    segments.append(tail)
        else:
            segments.append(remaining)
    if not segments:
        segments = [min(block, raw_target) if raw_target > 0 else block]
    return sum(segments), segments


def _apply_segment_durations_to_alignments(
    alignments: list[dict[str, Any]],
    segment_durations: list[int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, seg in enumerate(alignments):
        row = dict(seg)
        if idx < len(segment_durations):
            row["duration_seconds"] = segment_durations[idx]
        out.append(row)
    return out


def build_story_beat_narrative(
    excerpt: str,
    archetype_hint: str,
    idx: int,
    total: int,
) -> str:
    hint = (archetype_hint or "sovereign traveler").strip()
    beat = (excerpt or "").strip()
    if not beat:
        return f"The {hint} moves through a Thera-World landscape (beat {idx + 1} of {total})."
    return f"The {hint} in a Thera-World scene reflecting the client's words: {beat[:320]}"


def build_story_visual_theme(archetype_hint: str, narrative: str = "") -> str:
    from app.sse.adapters.world_story_bible import get_visual_style_suffix

    parts = ["audio-driven story beat illustration"]
    style = get_visual_style_suffix(archetype_hint)
    if style:
        parts.append(style)
    if narrative:
        parts.append(narrative[:220])
    return " — ".join(parts)


def heuristic_story_beat_alignments(
    transcript: str,
    *,
    segment_count: int,
    archetype_hint: str = "",
    segment_durations: Optional[list[int]] = None,
) -> list[dict[str, Any]]:
    """Split transcript into story beats with visual prompts (no journey panels)."""
    if segment_durations:
        segment_count = len(segment_durations)
    excerpts = split_transcript_segments(transcript, segment_count)
    alignments: list[dict[str, Any]] = []
    for idx, excerpt in enumerate(excerpts):
        narrative = build_story_beat_narrative(excerpt, archetype_hint, idx, segment_count)
        row: dict[str, Any] = {
            "segment_index": idx,
            "transcript_excerpt": excerpt,
            "panel_id": None,
            "panel_type": "story_beat",
            "r2_key": None,
            "r2_url": None,
            "narrative_text": narrative,
            "biome": "whisperwood",
            "panel_tone": "reflective",
            "ingest_mode": "audio_driven",
            "panel_visual_theme": build_story_visual_theme(archetype_hint, narrative),
        }
        if segment_durations and idx < len(segment_durations):
            row["duration_seconds"] = segment_durations[idx]
        alignments.append(row)
    return alignments


async def align_transcript_to_trailer_beats(
    transcript: str,
    *,
    segment_durations: list[int],
    source_duration_seconds: float,
    archetype_hint: str = "",
) -> list[dict[str, Any]]:
    """Summarize full transcript into ordered trailer scenes (movie-trailer pacing, ≤2 min)."""
    transcript = (transcript or "").strip()
    segment_count = len(segment_durations)
    if not transcript or segment_count < 1:
        return heuristic_story_beat_alignments(
            transcript,
            segment_count=max(segment_count, 1),
            archetype_hint=archetype_hint,
            segment_durations=segment_durations or None,
        )
    # Length-independent: compress before Workers AI so 30+ min sources still trailerize.
    working = await compress_transcript_for_trailer(
        transcript,
        source_duration_seconds=source_duration_seconds,
        archetype_hint=archetype_hint,
    )
    total_trailer = sum(segment_durations)
    dur_desc = ", ".join(f"{d}s" for d in segment_durations)
    try:
        from app.sse import studio_service

        prompt = (
            f"Client conversation ({source_duration_seconds:.0f}s source, compressed for trailer). "
            f"Create a Thera-World anime-style MOVIE TRAILER summary for archetype "
            f"{archetype_hint or 'traveler'}.\n"
            f"Output exactly {segment_count} scenes in story order with clip durations: {dur_desc} "
            f"(total {total_trailer}s max). Capture the ENTIRE conversation arc — key emotional "
            f"turns, insights, and resolution — not a literal slice per timecode.\n"
            f"Each scene needs a vivid visual description and the spoken essence in dialogue.\n\n"
            f"{working}"
        )
        result = await studio_service.break_into_scenes(prompt)
        scenes = result.get("scenes") or []
        # Prefer full transcript for dialogue fallbacks so compression does not wipe client words.
        excerpts = split_transcript_segments(transcript, segment_count)
        alignments: list[dict[str, Any]] = []
        for idx in range(segment_count):
            scene = scenes[idx] if idx < len(scenes) else {}
            excerpt = (scene.get("dialogue") or "").strip() or (
                excerpts[idx] if idx < len(excerpts) else ""
            )
            narrative = (scene.get("description") or "").strip() or build_story_beat_narrative(
                excerpt, archetype_hint, idx, segment_count,
            )
            mood = (scene.get("mood") or "reflective").strip()
            alignments.append(
                {
                    "segment_index": idx,
                    "transcript_excerpt": excerpt,
                    "panel_id": None,
                    "panel_type": "story_beat",
                    "r2_key": None,
                    "r2_url": None,
                    "narrative_text": narrative,
                    "biome": "whisperwood",
                    "panel_tone": mood,
                    "ingest_mode": "audio_driven",
                    "panel_visual_theme": build_story_visual_theme(archetype_hint, narrative),
                    "duration_seconds": segment_durations[idx],
                }
            )
        return alignments
    except Exception as exc:
        logger.warning("align_transcript_to_trailer_beats LLM fallback: %s", exc)
        return heuristic_story_beat_alignments(
            transcript,
            segment_count=segment_count,
            archetype_hint=archetype_hint,
            segment_durations=segment_durations,
        )


async def align_transcript_to_story_beats(
    transcript: str,
    *,
    segment_count: int,
    archetype_hint: str = "",
) -> list[dict[str, Any]]:
    """Break transcript into cinematic beats with AI visual descriptions (no panel DB)."""
    transcript = (transcript or "").strip()
    if not transcript:
        return heuristic_story_beat_alignments(
            transcript, segment_count=segment_count, archetype_hint=archetype_hint,
        )
    try:
        from app.sse import studio_service

        prompt = (
            f"Client journey transcript for Thera-World recap ({archetype_hint or 'traveler'} archetype).\n"
            f"Create exactly {segment_count} scenes that follow the story in order.\n"
            f"Each scene duration should be about {TARGET_SEGMENT_SECONDS:.0f} seconds when stitched.\n\n"
            f"{transcript}"
        )
        result = await studio_service.break_into_scenes(prompt)
        scenes = result.get("scenes") or []
        excerpts = split_transcript_segments(transcript, segment_count)
        alignments: list[dict[str, Any]] = []
        for idx in range(segment_count):
            scene = scenes[idx] if idx < len(scenes) else {}
            excerpt = (scene.get("dialogue") or "").strip() or (
                excerpts[idx] if idx < len(excerpts) else ""
            )
            narrative = (scene.get("description") or "").strip() or build_story_beat_narrative(
                excerpt, archetype_hint, idx, segment_count,
            )
            mood = (scene.get("mood") or "reflective").strip()
            alignments.append(
                {
                    "segment_index": idx,
                    "transcript_excerpt": excerpt,
                    "panel_id": None,
                    "panel_type": "story_beat",
                    "r2_key": None,
                    "r2_url": None,
                    "narrative_text": narrative,
                    "biome": "whisperwood",
                    "panel_tone": mood,
                    "ingest_mode": "audio_driven",
                    "panel_visual_theme": build_story_visual_theme(archetype_hint, narrative),
                }
            )
        return alignments
    except Exception as exc:
        logger.warning("align_transcript_to_story_beats LLM fallback: %s", exc)
        return heuristic_story_beat_alignments(
            transcript, segment_count=segment_count, archetype_hint=archetype_hint,
        )


async def ensure_segment_still_image(
    segment: dict[str, Any],
    *,
    user_id: str,
    job_id: str,
    archetype_hint: str,
    archetype_image_url: Optional[str] = None,
) -> dict[str, Any]:
    """Generate one Grok still at render time when ingest skipped images."""
    row = dict(segment)
    if row.get("r2_url"):
        return row
    narrative = (row.get("narrative_text") or row.get("transcript_excerpt") or "").strip()
    if not narrative:
        return row
    from app.sse.adapters.world_story_bible import get_visual_style_suffix
    from app.sse.infrastructure.grok_imagine_client import GROK_IMAGINE_LOCK, generate_image

    idx = int(row.get("segment_index", 0))
    style = get_visual_style_suffix(archetype_hint)
    prompt = (
        f"Thera-World therapeutic fantasy illustration. {style} "
        f"Cinematic scene illustrating: {narrative[:400]}. "
        "Painterly gouache, muted warm sovereign sanctuary palette, emotionally grounded, "
        "no text, no logos, no watermarks."
    )
    try:
        async with GROK_IMAGINE_LOCK:
            image_bytes = await generate_image(
                prompt,
                source_image_url=(archetype_image_url or "").strip() or None,
            )
        key = f"sse/journey-recap/{user_id}/{job_id}/beat_{idx:02d}.png"
        url = await r2_storage.store_image(image_bytes, key)
        row["r2_key"] = key
        row["r2_url"] = url
        row["generated_image"] = True
    except Exception as exc:
        logger.warning(
            "render-time still failed job=%s seg=%s: %s", job_id, idx, exc,
        )
    return row


async def generate_story_beat_images(
    alignments: list[dict[str, Any]],
    *,
    user_id: str,
    job_id: str,
    archetype_hint: str,
    archetype_image_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Generate Grok stills for each story beat (audio-driven ingest)."""
    if os.getenv("JOURNEY_RECAP_SKIP_INGEST_IMAGES", "").strip().lower() in ("1", "true", "yes"):
        return alignments

    from app.sse.adapters.world_story_bible import get_visual_style_suffix
    from app.sse.infrastructure.grok_imagine_client import GROK_IMAGINE_LOCK, generate_image

    style = get_visual_style_suffix(archetype_hint)
    updated: list[dict[str, Any]] = []
    for seg in alignments:
        row = dict(seg)
        idx = int(row.get("segment_index", len(updated)))
        narrative = (row.get("narrative_text") or row.get("transcript_excerpt") or "").strip()
        if not narrative:
            updated.append(row)
            continue
        prompt = (
            f"Thera-World therapeutic fantasy illustration. {style} "
            f"Cinematic scene illustrating: {narrative[:400]}. "
            "Painterly gouache, muted warm sovereign sanctuary palette, emotionally grounded, "
            "no text, no logos, no watermarks."
        )
        try:
            async with GROK_IMAGINE_LOCK:
                image_bytes = await generate_image(
                    prompt,
                    source_image_url=(archetype_image_url or "").strip() or None,
                )
            key = f"sse/journey-recap/{user_id}/{job_id}/beat_{idx:02d}.png"
            url = await r2_storage.store_image(image_bytes, key)
            row["r2_key"] = key
            row["r2_url"] = url
            row["generated_image"] = True
        except Exception as exc:
            logger.warning(
                "story beat image gen failed job=%s seg=%s: %s", job_id, idx, exc,
            )
        updated.append(row)
    return updated


def split_transcript_segments(transcript: str, segment_count: int = DEFAULT_SEGMENT_COUNT) -> list[str]:
    """Split transcript into *segment_count* roughly equal chunks on sentence boundaries."""
    text = (transcript or "").strip()
    if not text:
        return [""] * segment_count
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        words = text.split()
        if len(words) <= segment_count:
            return words + [""] * (segment_count - len(words))
        chunk = max(1, len(words) // segment_count)
        return [" ".join(words[i : i + chunk]) for i in range(0, len(words), chunk)][:segment_count]
    per = max(1, len(sentences) // segment_count)
    chunks: list[str] = []
    for i in range(0, len(sentences), per):
        chunks.append(" ".join(sentences[i : i + per]))
    while len(chunks) < segment_count:
        chunks.append("")
    return chunks[:segment_count]


def _token_set(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Z']{3,}", text or "")}


def score_panel_for_excerpt(panel: dict[str, Any], excerpt: str) -> float:
    narrative = panel.get("narrative_text") or panel.get("client_narrative_text") or ""
    panel_tokens = _token_set(narrative)
    excerpt_tokens = _token_set(excerpt)
    if not excerpt_tokens:
        return 0.0
    overlap = len(panel_tokens & excerpt_tokens)
    return overlap / max(len(excerpt_tokens), 1)


def align_transcript_to_panels(
    transcript: str,
    panels: list[dict[str, Any]],
    *,
    segment_count: int = DEFAULT_SEGMENT_COUNT,
    manual_alignments: Optional[list[dict[str, Any]]] = None,
    archetype_hint: str = "",
) -> list[dict[str, Any]]:
    """Map transcript beats to journey panels (manual override or narrative overlap)."""
    excerpts = split_transcript_segments(transcript, segment_count)
    panel_by_id = {str(p.get("id") or p.get("panel_id") or ""): p for p in panels}
    manual_by_idx: dict[int, dict[str, Any]] = {}
    if manual_alignments:
        for row in manual_alignments:
            idx = int(row.get("segment_index", row.get("index", -1)))
            if idx >= 0:
                manual_by_idx[idx] = row

    used_panel_ids: set[str] = set()
    segments: list[dict[str, Any]] = []
    for idx, excerpt in enumerate(excerpts):
        manual = manual_by_idx.get(idx)
        panel: Optional[dict[str, Any]] = None
        if manual and manual.get("panel_id"):
            panel = panel_by_id.get(str(manual["panel_id"]))
        if panel is None and panels:
            journeys = [p for p in panels if str(p.get("panel_type", "")).lower() == "journey"]
            dailies = [p for p in panels if str(p.get("panel_type", "")).lower() == "daily_panel"]
            if idx == 0 and journeys:
                pool = journeys
            elif idx > 0 and dailies:
                pool = dailies
            else:
                pool = panels
            ranked = sorted(
                pool,
                key=lambda p: score_panel_for_excerpt(p, excerpt),
                reverse=True,
            )
            for candidate in ranked:
                cid = str(candidate.get("id") or candidate.get("panel_id") or "")
                if cid and cid not in used_panel_ids:
                    panel = candidate
                    break
            if panel is None and ranked:
                panel = ranked[min(idx, len(ranked) - 1)]
        pid = str(panel.get("id") or panel.get("panel_id") or "") if panel else ""
        if pid:
            used_panel_ids.add(pid)
        segments.append(
            {
                "segment_index": idx,
                "transcript_excerpt": (manual or {}).get("transcript_excerpt") or excerpt,
                "panel_id": pid,
                "panel_type": (panel or {}).get("panel_type"),
                "r2_key": _r2_key_from_url((panel or {}).get("r2_url")),
                "r2_url": refresh_panel_r2_url((panel or {}).get("r2_url")),
                "narrative_text": (panel or {}).get("narrative_text"),
                "biome": (panel or {}).get("biome"),
                "panel_tone": (panel or {}).get("panel_tone"),
                "character_manifest": (panel or {}).get("character_manifest"),
                "prompt_used": (panel or {}).get("prompt_used"),
                "generated_at": (panel or {}).get("generated_at"),
                "panel_visual_theme": build_panel_visual_theme(
                    panel or {}, archetype_hint=archetype_hint,
                ),
            }
        )
    return segments


_PANEL_TONE_MOTION: dict[str, str] = {
    "meditative": "soft diffusion, stillness with micro-movement",
    "action_sequence": "purposeful forward motion, dynamic but painterly",
    "threshold_pathway": "liminal glow at path edge, threshold light pulse",
    "restoration_sands": "warm amber restoration glow, gentle drift",
    "revelation": "reveal light bloom, clarity deepening",
    "reflective": "contemplative drift, mirror-soft highlights",
}


def build_panel_visual_theme(
    panel: dict[str, Any],
    *,
    archetype_hint: str = "",
) -> str:
    """Fuse archetype + panel metadata into the same art-direction base as daily/journey panels."""
    from app.sse.adapters.world_story_bible import get_visual_style_suffix

    parts: list[str] = []
    ptype = str(panel.get("panel_type") or "").strip()
    if ptype:
        parts.append(f"Thera-World {ptype.replace('_', ' ')} panel")
    arch_style = get_visual_style_suffix(archetype_hint)
    if arch_style:
        parts.append(arch_style)
    tone = str(panel.get("panel_tone") or "").strip().lower()
    if tone and tone in _PANEL_TONE_MOTION:
        parts.append(_PANEL_TONE_MOTION[tone])
    biome = str(panel.get("biome") or "").strip()
    if biome and not biome.replace("-", "").isdigit():
        parts.append(f"{biome} biome")
    manifest = str(panel.get("character_manifest") or "").strip()
    if manifest:
        parts.append(f"character manifestation: {manifest[:120]}")
    prompt_used = str(panel.get("prompt_used") or "").strip()
    if prompt_used:
        parts.append(f"match panel art direction: {prompt_used[:280]}")
    return " — ".join(p for p in parts if p)


def build_motion_prompt(
    *,
    archetype_hint: str,
    narrative: str,
    biome: str,
    transcript_excerpt: str,
    chat_snippets: list[str],
    panel: Optional[dict[str, Any]] = None,
    visual_theme: str = "",
) -> str:
    hint = (archetype_hint or "sovereign traveler").strip()
    theme = (visual_theme or "").strip()
    is_story_beat = panel and str(panel.get("panel_type") or "").lower() == "story_beat"
    if not theme and panel and not is_story_beat:
        theme = build_panel_visual_theme(panel, archetype_hint=hint)
    narrative_part = (narrative or transcript_excerpt or "")[:200].strip()
    chat_part = ""
    if chat_snippets:
        chat_part = f" Reflecting client dialogue: {chat_snippets[0][:120]}."
    if is_story_beat:
        style_lock = (
            f"Thera-World painterly cinematic motion, {f'{biome} biome, ' if biome else ''}"
            f"protagonist as {hint}, archetype locked in every frame"
        )
        if theme:
            style_lock += f", {theme}"
        style_lock += ". "
        footer = (
            "No text overlays, no logos, gentle camera drift. "
            "Match the generated story illustration style."
        )
    elif theme:
        style_lock = (
            f"VISUAL LOCK — preserve exact palette, line weight, and composition of the source panel. "
            f"{theme}. "
        )
        footer = "No text overlays, no logos, gentle camera drift. Do not change art style away from source panel."
    else:
        style_lock = (
            f"Thera-World painterly cinematic motion, {f'{biome} biome, ' if biome else ''}"
            f"protagonist as {hint}, archetype locked in every frame, "
        )
        footer = "No text overlays, no logos, gentle camera drift. Do not change art style away from source panel."
    return f"{style_lock}subtle emotional movement matching the story: {narrative_part}.{chat_part} {footer}"


async def fetch_user_panels(conn, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    ids = [user_id]
    rows_j = await conn.fetch(
        """
        SELECT panel_id::text AS id, panel_type, r2_url, narrative_text, biome,
               character_manifest, panel_tone, prompt_used, generated_at
        FROM sse_panel_log
        WHERE user_id = ANY($1::text[]) AND r2_url IS NOT NULL AND r2_url != ''
        ORDER BY generated_at DESC LIMIT $2
        """,
        ids,
        limit,
    )
    rows_w = await conn.fetch(
        """
        SELECT log_id::text AS id, generation_type::text AS panel_type, r2_url,
               COALESCE(NULLIF(btrim(client_narrative_text), ''), 'Sovereign Journey moment') AS narrative_text,
               storyboard_id::text AS biome, prompt_used, generated_at,
               'reflective'::text AS panel_tone
        FROM sse_delivery_generation_log
        WHERE user_id = ANY($1::text[]) AND r2_url IS NOT NULL AND r2_url != ''
        ORDER BY generated_at DESC LIMIT $2
        """,
        ids,
        limit,
    )
    merged = sorted([dict(r) for r in rows_j] + [dict(r) for r in rows_w],
                    key=lambda x: x.get("generated_at") or "", reverse=True)
    return _refresh_panels_r2_urls(merged[:limit])


async def fetch_archetype(conn, user_id: str) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT archetype_hint, archetype_image_url
        FROM sse_identity_forge
        WHERE user_id = ANY($1::text[])
        LIMIT 1
        """,
        [user_id],
    )
    return dict(row) if row else {}


async def fetch_ask_nate_captures(
    conn,
    user_id: str,
    panel_id: str,
    generated_at,
    *,
    limit: int = 3,
) -> list[dict[str, str]]:
    """Pull Ask Nate chat lines near a panel timestamp or referencing the panel."""
    if not user_id:
        return []
    window_start = None
    window_end = None
    if generated_at:
        window_start = generated_at - timedelta(hours=48)
        window_end = generated_at + timedelta(hours=48)
    rows = await conn.fetch(
        """
        SELECT user_text, ai_text, created_at
        FROM conversation_history
        WHERE user_id = $1
          AND (
            ($2::timestamptz IS NULL)
            OR (created_at BETWEEN $2 AND $3)
          )
        ORDER BY created_at DESC
        LIMIT 40
        """,
        user_id,
        window_start,
        window_end,
    )
    captures: list[dict[str, str]] = []
    panel_ref = panel_id or ""
    for row in rows:
        ut = (row["user_text"] or "").strip()
        at = (row["ai_text"] or "").strip()
        blob = f"{ut} {at}"
        if panel_ref and panel_ref not in blob and "[SSE PANEL" not in blob.upper():
            if window_start is None:
                continue
        if ut:
            captures.append({"role": "client", "text": ut[:500]})
        if at:
            captures.append({"role": "nate", "text": at[:500]})
        if len(captures) >= limit:
            break
    return captures


async def _download_url_to_path(url: str, dest: str) -> bool:
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                if resp.status != 200:
                    return False
                data = await resp.read()
        with open(dest, "wb") as f:
            f.write(data)
        return len(data) > 500
    except Exception as e:
        logger.warning("[JOURNEY-RECAP] download failed %s: %s", url[:80], e)
        return False


async def _render_segment_clip(
    segment: dict[str, Any],
    motion_prompt: str,
    archetype_url: Optional[str],
    duration: float,
    work_dir: str,
    *,
    user_id: str = "",
    job_id: str = "",
    ken_burns_only: bool = False,
) -> dict[str, Any]:
    idx = segment["segment_index"]
    out_path = os.path.join(work_dir, f"segment_{idx:02d}.mp4")
    meta: dict[str, Any] = {
        "segment_index": idx,
        "panel_id": segment.get("panel_id"),
        "status": "failed",
        "local_path": out_path,
        "motion_prompt": motion_prompt,
        "duration_seconds": duration,
    }
    image_url = segment.get("r2_url") or archetype_url
    if not image_url:
        meta["error"] = "no_panel_image"
        return meta

    from app.sse.trailer_generator import _generate_video_from_image, _ken_burns_fallback

    source_for_grok = image_url
    if not ken_burns_only:
        meta["grok_attempted"] = True
        grok_result = await _generate_video_from_image(source_for_grok, motion_prompt)
        if grok_result and grok_result.get("video_url"):
            ok = await _download_url_to_path(grok_result["video_url"], out_path)
            if ok:
                meta["status"] = "grok"
                meta["cost"] = grok_result.get("cost", 4.0)
            else:
                meta["grok_error"] = "grok_download_failed"
        else:
            meta["grok_error"] = "grok_timeout_or_api_error"

    if meta["status"] == "failed" and not os.path.exists(out_path):
        kb_ok = await _ken_burns_fallback(image_url, out_path, duration=duration)
        if kb_ok and os.path.exists(out_path):
            meta["status"] = "ken_burns"
            meta["cost"] = 0
            meta["fallback_reason"] = meta.get("grok_error") or "ken_burns_only"

    if meta.get("status") not in ("grok", "ken_burns"):
        meta["error"] = "render_failed"
        return meta

    if user_id and job_id and os.path.exists(out_path):
        try:
            with open(out_path, "rb") as f:
                blob = f.read()
            r2_key = f"sse/journey-recap/{user_id}/{job_id}/seg_{idx:02d}.mp4"
            meta["video_url"] = await r2_storage.store_bytes(blob, r2_key, "video/mp4")
            meta["r2_key"] = r2_key
        except Exception as e:
            logger.warning("[JOURNEY-RECAP] segment R2 upload failed: %s", e)
    return meta


def _ffmpeg_trim_clip(src: str, dst: str, duration: float) -> bool:
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-t", str(duration),
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
        dst,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        return r.returncode == 0 and os.path.exists(dst)
    except Exception as e:
        logger.warning("[JOURNEY-RECAP] trim failed: %s", e)
        return False


def _ffmpeg_concat_clips(clip_paths: list[str], output_path: str) -> bool:
    if not clip_paths:
        return False
    list_path = output_path + ".txt"
    with open(list_path, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", output_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        return r.returncode == 0 and os.path.exists(output_path)
    except Exception as e:
        logger.warning("[JOURNEY-RECAP] concat failed: %s", e)
        return False


def _ffmpeg_mux_audio(video_path: str, audio_path: str, output_path: str, duration: float) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-t", str(duration),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        return r.returncode == 0 and os.path.exists(output_path)
    except Exception as e:
        logger.warning("[JOURNEY-RECAP] mux failed: %s", e)
        return False


async def _resolve_clip_to_local(meta: dict[str, Any], work_dir: str, idx: int) -> Optional[str]:
    key = meta.get("r2_key")
    if key:
        data = await r2_storage.download_bytes(key)
        if data:
            path = os.path.join(work_dir, f"dl_{idx:02d}.mp4")
            with open(path, "wb") as f:
                f.write(data)
            return path
    url = meta.get("video_url")
    if url:
        path = os.path.join(work_dir, f"dl_{idx:02d}.mp4")
        if await _download_url_to_path(url, path):
            return path
    return None


async def stitch_recap_video(
    clip_metas: list[dict[str, Any]],
    *,
    audio_local_path: Optional[str],
    target_duration: int = DEFAULT_TARGET_DURATION,
    segment_count: int = DEFAULT_SEGMENT_COUNT,
    segment_durations: Optional[list[int]] = None,
    mux_client_audio: bool = True,
) -> tuple[Optional[bytes], list[str]]:
    """Trim segments, concat, optionally mux client audio. Returns (mp4_bytes, errors)."""
    default_seg_dur = segment_duration(target_duration, segment_count)
    work_dir = tempfile.mkdtemp(prefix="journey_recap_stitch_")
    errors: list[str] = []
    trimmed: list[str] = []
    try:
        for meta in sorted(clip_metas, key=lambda m: m.get("segment_index", 0)):
            idx = meta.get("segment_index", 0)
            dur = meta.get("duration_seconds")
            if dur is None and segment_durations and idx < len(segment_durations):
                dur = segment_durations[idx]
            if dur is None:
                dur = default_seg_dur
            dur = float(dur)
            src = meta.get("local_path")
            if not src or not os.path.exists(src):
                src = await _resolve_clip_to_local(meta, work_dir, idx)
            if not src or not os.path.exists(src):
                errors.append(f"segment {idx}: missing clip")
                continue
            meta["local_path"] = src
            dst = os.path.join(work_dir, f"trim_{meta['segment_index']:02d}.mp4")
            if not _ffmpeg_trim_clip(src, dst, dur):
                errors.append(f"segment {meta.get('segment_index')}: trim failed")
                continue
            trimmed.append(dst)

        if not trimmed:
            return None, errors or ["no_clips"]

        concat_out = os.path.join(work_dir, "concat.mp4")
        if not _ffmpeg_concat_clips(trimmed, concat_out):
            return None, errors + ["concat_failed"]

        final_path = concat_out
        if mux_client_audio and audio_local_path and os.path.exists(audio_local_path):
            mux_out = os.path.join(work_dir, "final_mux.mp4")
            if _ffmpeg_mux_audio(concat_out, audio_local_path, mux_out, target_duration):
                final_path = mux_out
            else:
                errors.append("audio_mux_failed_using_silent_video")
                trim_cmd = [
                    "ffmpeg", "-y", "-i", concat_out, "-t", str(target_duration),
                    "-c", "copy", mux_out,
                ]
                subprocess.run(trim_cmd, capture_output=True, timeout=60)
                if os.path.exists(mux_out):
                    final_path = mux_out
        else:
            capped = os.path.join(work_dir, "final_cap.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-i", concat_out, "-t", str(target_duration), "-c", "copy", capped],
                capture_output=True,
                timeout=60,
            )
            if os.path.exists(capped):
                final_path = capped

        with open(final_path, "rb") as f:
            return f.read(), errors
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def _set_job_status(conn, job_id: str, status: str, **fields: Any) -> None:
    """Update job status and optional scalar/jsonb columns."""
    sets = ["status = $2", "updated_at = NOW()"]
    args: list[Any] = [uuid.UUID(job_id), status]
    n = 3
    jsonb_cols = {"panel_alignments", "chat_captures", "segment_clips"}
    for key, val in fields.items():
        if key in jsonb_cols:
            sets.append(f"{key} = ${n}::jsonb")
        else:
            sets.append(f"{key} = ${n}")
        args.append(val)
        n += 1
    await conn.execute(
        f"UPDATE sse_journey_recap_jobs SET {', '.join(sets)} WHERE job_id = $1::uuid",
        *args,
    )


async def run_journey_recap_job(db_pool, job_id: str) -> None:
    """Full pipeline: align → render Grok/Ken Burns clips → stitch 30s output."""
    if not feature_enabled():
        async with db_pool.acquire() as conn:
            await _set_job_status(
                conn, job_id, "failed",
                error_message=f"{FEATURE_FLAG} is disabled",
            )
        return

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
            uuid.UUID(job_id),
        )
    if not row:
        return

    job = dict(row)
    user_id = job["user_id"]
    target_duration = int(job.get("target_duration_seconds") or DEFAULT_TARGET_DURATION)
    segment_count = int(job.get("segment_count") or DEFAULT_SEGMENT_COUNT)
    seg_dur = segment_duration(target_duration, segment_count)
    work_dir = tempfile.mkdtemp(prefix=f"journey_recap_{job_id[:8]}_")

    try:
        async with db_pool.acquire() as conn:
            await _set_job_status(conn, job_id, "aligning")
            panels = await fetch_user_panels(conn, user_id)
            archetype = await fetch_archetype(conn, user_id)
            manual = job.get("panel_alignments")
            if isinstance(manual, str):
                manual = json.loads(manual)
            segments = align_transcript_to_panels(
                job["transcript_text"],
                panels,
                segment_count=segment_count,
                manual_alignments=manual if manual else None,
                archetype_hint=archetype.get("archetype_hint") or "",
            )
            chat_captures: list[dict[str, Any]] = []
            for seg in segments:
                caps = await fetch_ask_nate_captures(
                    conn, user_id, seg.get("panel_id", ""), seg.get("generated_at"),
                )
                chat_captures.append(
                    {"segment_index": seg["segment_index"], "panel_id": seg.get("panel_id"), "messages": caps}
                )
            await _set_job_status(
                conn, job_id, "rendering",
                panel_alignments=segments,
                chat_captures=chat_captures,
                archetype_hint=archetype.get("archetype_hint"),
                archetype_image_url=archetype.get("archetype_image_url"),
            )

        archetype_hint = archetype.get("archetype_hint") or ""
        archetype_url = archetype.get("archetype_image_url")
        clip_metas: list[dict[str, Any]] = []

        chat_by_idx = {c["segment_index"]: c.get("messages") or [] for c in chat_captures}
        for seg in segments:
            snippets = [m.get("text", "") for m in chat_by_idx.get(seg["segment_index"], []) if m.get("text")]
            motion = build_motion_prompt(
                archetype_hint=archetype_hint,
                narrative=seg.get("narrative_text") or "",
                biome=seg.get("biome") or "",
                transcript_excerpt=seg.get("transcript_excerpt") or "",
                chat_snippets=snippets,
                panel=seg,
                visual_theme=seg.get("panel_visual_theme") or "",
            )
            meta = await _render_segment_clip(
                seg, motion, archetype_url, seg_dur, work_dir,
                user_id=user_id, job_id=job_id,
            )
            clip_metas.append(meta)

        async with db_pool.acquire() as conn:
            await _set_job_status(conn, job_id, "stitching", segment_clips=clip_metas)

        audio_path = None
        audio_key = job.get("audio_r2_key")
        if audio_key:
            audio_bytes = await r2_storage.download_bytes(audio_key)
            if audio_bytes:
                audio_path = os.path.join(work_dir, "client_audio")
                ext = ".m4a" if "m4a" in (job.get("audio_r2_url") or "") else ".mp3"
                audio_path += ext
                with open(audio_path, "wb") as f:
                    f.write(audio_bytes)

        mp4_bytes, stitch_errors = await stitch_recap_video(
            clip_metas,
            audio_local_path=audio_path,
            target_duration=target_duration,
            segment_count=segment_count,
        )
        if not mp4_bytes:
            raise RuntimeError("; ".join(stitch_errors) or "stitch produced no output")

        out_key = f"sse/journey-recap/{user_id}/{job_id}.mp4"
        out_url = await r2_storage.store_bytes(mp4_bytes, out_key, "video/mp4")

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sse_journey_recap_jobs SET
                    status = 'complete',
                    output_r2_key = $2,
                    output_r2_url = $3,
                    segment_clips = $4::jsonb,
                    error_message = $5,
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE job_id = $1::uuid
                """,
                uuid.UUID(job_id),
                out_key,
                out_url,
                json.dumps(_json_safe(clip_metas)),
                "; ".join(stitch_errors) if stitch_errors else None,
            )
        logger.info("[JOURNEY-RECAP] job %s complete → %s", job_id, out_key)
    except Exception as e:
        logger.exception("[JOURNEY-RECAP] job %s failed: %s", job_id, e)
        async with db_pool.acquire() as conn:
            await _set_job_status(conn, job_id, "failed", error_message=str(e)[:2000])
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def _extract_audio_from_video(video_path: str, out_wav: str) -> bool:
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        out_wav,
    ]
    try:
        # Long sources can take several minutes to demux; length must not fail extract.
        r = subprocess.run(cmd, capture_output=True, timeout=1800)
        return r.returncode == 0 and os.path.exists(out_wav)
    except Exception as e:
        logger.warning("[JOURNEY-RECAP] audio extract failed: %s", e)
        return False


def estimate_duration_from_transcript(transcript: str) -> float:
    """Estimate spoken duration (~150 wpm) so pasted transcripts get trailer length planning."""
    words = len((transcript or "").split())
    seconds = words / 2.5
    return max(float(DEFAULT_TARGET_DURATION), min(seconds, 7200.0))


def _split_text_chunks(text: str, max_chars: int) -> list[str]:
    """Split long text on sentence boundaries for map-reduce summarization."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()] or [text]
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for sent in sentences:
        add = len(sent) + (1 if cur else 0)
        if cur and cur_len + add > max_chars:
            chunks.append(" ".join(cur))
            cur = [sent]
            cur_len = len(sent)
        else:
            cur.append(sent)
            cur_len += add
    if cur:
        chunks.append(" ".join(cur))
    return chunks


async def compress_transcript_for_trailer(
    transcript: str,
    *,
    source_duration_seconds: float,
    archetype_hint: str = "",
) -> str:
    """
    Map-reduce compress long transcripts so length does not break Workers AI context.
    Short transcripts pass through unchanged.
    """
    text = (transcript or "").strip()
    if not text:
        return ""
    if len(text) <= TRAILER_TRANSCRIPT_DIRECT_MAX_CHARS:
        return text

    from app.sse import studio_service

    parts = _split_text_chunks(text, TRAILER_TRANSCRIPT_MAP_CHUNK_CHARS)
    summaries: list[str] = []
    for i, part in enumerate(parts):
        system = (
            "You compress therapy/client conversation excerpts into tight arc notes. "
            f"Return plain text under {TRAILER_MAP_SUMMARY_CHARS} characters. "
            "Preserve emotional turns, decisions, and resolution cues. No preamble."
        )
        user = (
            f"Part {i + 1}/{len(parts)} of a {source_duration_seconds:.0f}s conversation "
            f"(archetype {archetype_hint or 'traveler'}):\n\n{part}"
        )
        try:
            raw = await studio_service._call_workers_ai(system, user)
            summary = (raw or "").strip()
            if summary:
                summaries.append(summary[: TRAILER_MAP_SUMMARY_CHARS + 80])
            else:
                summaries.append(part[:TRAILER_MAP_SUMMARY_CHARS])
        except Exception as exc:
            logger.warning("compress_transcript_for_trailer part %d failed: %s", i, exc)
            summaries.append(part[:TRAILER_MAP_SUMMARY_CHARS])

    compressed = "\n\n".join(
        f"[Arc beat {i + 1}]\n{s}" for i, s in enumerate(summaries) if s
    )
    if len(compressed) <= TRAILER_TRANSCRIPT_DIRECT_MAX_CHARS:
        return compressed

    # Second pass if still huge (very long sessions).
    system2 = (
        "Merge these arc-beat notes into one ordered conversation summary under 3500 "
        "characters for a movie-trailer rewrite. Keep emotional peaks and ending."
    )
    try:
        raw2 = await studio_service._call_workers_ai(system2, compressed[:12000])
        merged = (raw2 or "").strip()
        if merged:
            return merged[:4000]
    except Exception as exc:
        logger.warning("compress_transcript_for_trailer reduce failed: %s", exc)
    return compressed[:4000]


async def _transcribe_wav_time_slices(wav_path: str, duration: float) -> str:
    """ffmpeg time-slice long WAV (byte-splitting breaks WAV headers)."""
    from app.services.whisper_stt import transcribe

    chunk_s = float(WHISPER_CHUNK_SECONDS)
    total = max(float(duration), 1.0)
    texts: list[str] = []
    offset = 0.0
    slice_idx = 0
    work = tempfile.mkdtemp(prefix="whisper_slices_")
    try:
        while offset < total - 0.25:
            slice_path = os.path.join(work, f"slice_{slice_idx:04d}.wav")
            remaining = total - offset
            length = min(chunk_s, remaining)
            cmd = [
                "ffmpeg", "-y", "-ss", f"{offset:.3f}", "-t", f"{length:.3f}",
                "-i", wav_path,
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                slice_path,
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=120)
                if r.returncode != 0 or not os.path.isfile(slice_path):
                    logger.warning(
                        "[JOURNEY-RECAP] whisper slice %d ffmpeg failed offset=%.1f",
                        slice_idx, offset,
                    )
                    offset += chunk_s
                    slice_idx += 1
                    continue
                with open(slice_path, "rb") as f:
                    data = f.read()
                piece = await transcribe(data, content_type="audio/wav")
                if piece and piece.strip():
                    texts.append(piece.strip())
            except Exception as exc:
                logger.warning(
                    "[JOURNEY-RECAP] whisper slice %d failed: %s", slice_idx, exc,
                )
            offset += chunk_s
            slice_idx += 1
            # Avoid hammering Azure Whisper on very long sources.
            if offset < total:
                await asyncio.sleep(0.35)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return " ".join(texts).strip()


async def _transcribe_audio_wav(wav_path: str) -> str:
    """Transcribe any-length WAV; long files use ffmpeg time slices."""
    from app.services.whisper_stt import transcribe

    duration = ffprobe_media_duration_seconds(wav_path) or 0.0
    if duration > WHISPER_SINGLE_SHOT_MAX_SECONDS:
        logger.info(
            "[JOURNEY-RECAP] chunked STT duration=%.1fs path=%s",
            duration, wav_path,
        )
        return await _transcribe_wav_time_slices(wav_path, duration)

    with open(wav_path, "rb") as f:
        data = f.read()
    result = await transcribe(data, content_type="audio/wav")
    return (result or "").strip()


def _build_studio_script_text(
    alignments: list[dict[str, Any]],
    *,
    archetype_hint: str,
    segment_count: int = DEFAULT_SEGMENT_COUNT,
    target_duration: int = DEFAULT_TARGET_DURATION,
) -> str:
    audio_driven = any(
        str(seg.get("ingest_mode") or "") == "audio_driven"
        or str(seg.get("panel_type") or "").lower() == "story_beat"
        for seg in alignments
    )
    mode = "audio-driven trailer beats" if audio_driven else "journey panels"
    lines = [
        f"Thera-World Trailer — client archetype: {archetype_hint or 'unknown'}",
        f"Target length: {target_duration}s max ({segment_count} scenes, {mode})",
        "",
    ]
    for seg in alignments:
        n = int(seg.get("segment_index", 0)) + 1
        title = seg.get("panel_type") or f"Panel {n}"
        lines.append(f"Scene {n}: {title}")
        lines.append(seg.get("transcript_excerpt") or seg.get("narrative_text") or "")
        lines.append("")
    return "\n".join(lines).strip()


def _alignments_to_studio_scenes(
    alignments: list[dict[str, Any]],
    chat_captures: list[dict[str, Any]],
    *,
    job_id: str,
    archetype_hint: str,
    seg_dur: float,
) -> list[dict[str, Any]]:
    chat_by_idx = {c["segment_index"]: c.get("messages") or [] for c in chat_captures}
    scenes: list[dict[str, Any]] = []
    for seg in alignments:
        idx = int(seg.get("segment_index", len(scenes)))
        snippets = [m.get("text", "") for m in chat_by_idx.get(idx, []) if m.get("text")]
        visual_theme = seg.get("panel_visual_theme") or build_panel_visual_theme(
            seg, archetype_hint=archetype_hint,
        )
        motion = build_motion_prompt(
            archetype_hint=archetype_hint,
            narrative=seg.get("narrative_text") or "",
            biome=seg.get("biome") or "",
            transcript_excerpt=seg.get("transcript_excerpt") or "",
            chat_snippets=snippets,
            panel=seg,
            visual_theme=visual_theme,
        )
        scene_num = idx + 1
        is_story = str(seg.get("panel_type") or "").lower() == "story_beat"
        dur = float(seg.get("duration_seconds") or seg_dur)
        scenes.append({
            "scene": scene_num,
            "title": f"Story Beat {scene_num}" if is_story else (seg.get("panel_type") or f"Journey Panel {scene_num}"),
            "description": (seg.get("narrative_text") or "")[:400],
            "dialogue": seg.get("transcript_excerpt") or "",
            "duration": dur,
            "mood": seg.get("panel_tone") or "reflective",
            "image_url": seg.get("r2_url"),
            "source_image_url": seg.get("r2_url"),
            "panel_id": seg.get("panel_id"),
            "panel_type": seg.get("panel_type"),
            "panel_visual_theme": visual_theme,
            "recap_job_id": job_id,
            "recap_segment_index": idx,
            "motion_prompt": motion,
            "characters": [archetype_hint] if archetype_hint else [],
            "video_status": "pending",
        })
    return scenes


def _studio_ingest_work_dir(job_id: str) -> str:
    """Persistent dir for async video ingest (survives until worker finishes)."""
    base = os.getenv("JOURNEY_RECAP_INGEST_DIR", "/app/data/sse_studio_ingest")
    path = os.path.join(base, str(job_id))
    os.makedirs(path, exist_ok=True)
    return path


def _parse_json_field(val: Any, default: Any) -> Any:
    if val is None:
        return default
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return val


def _infer_ingest_mode_from_alignments(alignments: list[dict[str, Any]]) -> str:
    for seg in alignments or []:
        if str(seg.get("panel_type") or "").lower() == "story_beat":
            return INGEST_MODE_AUDIO
        if str(seg.get("ingest_mode") or "") == INGEST_MODE_AUDIO:
            return INGEST_MODE_AUDIO
    return INGEST_MODE_PANEL


def build_studio_result_from_job(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Build Studio ingest payload from a recap job row."""
    status = (row.get("status") or "").strip()
    alignments = _parse_json_field(row.get("panel_alignments"), [])
    if status not in STUDIO_READY_STATUSES or not alignments:
        return None
    transcript = (row.get("transcript_text") or "").strip()
    if not transcript or transcript.startswith("(processing"):
        return None

    chat_captures = _parse_json_field(row.get("chat_captures"), [])
    clips = _parse_json_field(row.get("segment_clips"), [])
    clip_by_idx = {
        int(c.get("segment_index", -1)): c
        for c in clips
        if isinstance(c, dict) and c.get("segment_index") is not None
    }
    job_id = str(row.get("job_id"))
    archetype_hint = (row.get("archetype_hint") or "").strip()
    target_duration = int(row.get("target_duration_seconds") or DEFAULT_TARGET_DURATION)
    segment_count = int(row.get("segment_count") or DEFAULT_SEGMENT_COUNT)
    seg_dur = segment_duration(target_duration, segment_count)
    ingest_mode = _infer_ingest_mode_from_alignments(alignments)

    scenes = _alignments_to_studio_scenes(
        alignments, chat_captures,
        job_id=job_id, archetype_hint=archetype_hint, seg_dur=seg_dur,
    )
    for scene in scenes:
        idx = int(scene.get("recap_segment_index", scene.get("scene", 1) - 1))
        clip = clip_by_idx.get(idx)
        if clip:
            if clip.get("video_url"):
                scene["video_url"] = clip.get("video_url")
                scene["video_status"] = clip.get("status", "complete")
            elif clip.get("status") == "failed":
                scene["video_status"] = "failed"
    script_text = _build_studio_script_text(
        alignments,
        archetype_hint=archetype_hint,
        segment_count=segment_count,
        target_duration=target_duration,
    )
    panel_count = 0
    if ingest_mode == INGEST_MODE_PANEL:
        panel_count = len({seg.get("panel_id") for seg in alignments if seg.get("panel_id")})

    result: dict[str, Any] = {
        "job_id": job_id,
        "user_id": row.get("user_id"),
        "transcript": transcript,
        "audio_url": row.get("audio_r2_url"),
        "archetype": archetype_hint,
        "script": script_text,
        "scenes": scenes,
        "panel_count": panel_count,
        "target_duration_seconds": target_duration,
        "segment_count": segment_count,
        "ingest_mode": ingest_mode,
        "job_status": status,
    }
    if row.get("output_r2_url"):
        result["output_url"] = row.get("output_r2_url")
    return result


async def _complete_studio_ingest_from_transcript(
    db_pool,
    *,
    user_id: str,
    transcript: str,
    audio_r2_key: Optional[str] = None,
    audio_r2_url: Optional[str] = None,
    existing_job_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create recap job, align panels, and return Studio script + scenes."""
    user_id = user_id.strip()
    transcript = (transcript or "").strip()
    if len(transcript) < 20:
        raise RuntimeError("Transcript too short (minimum 20 characters)")

    segment_count = DEFAULT_SEGMENT_COUNT
    target_duration = DEFAULT_TARGET_DURATION
    seg_dur = segment_duration(target_duration, segment_count)

    if existing_job_id:
        job_id = existing_job_id
        async with db_pool.acquire() as conn:
            user_id = await resolve_recap_user_id(conn, user_id)
            await conn.execute(
                """
                UPDATE sse_journey_recap_jobs SET
                    transcript_text = $2,
                    target_duration_seconds = $3,
                    segment_count = $4,
                    updated_at = NOW()
                WHERE job_id = $1::uuid
                """,
                uuid.UUID(job_id),
                transcript,
                target_duration,
                segment_count,
            )
    else:
        async with db_pool.acquire() as conn:
            user_id = await resolve_recap_user_id(conn, user_id)
            row = await conn.fetchrow(
                """
                INSERT INTO sse_journey_recap_jobs (
                    user_id, transcript_text, target_duration_seconds, segment_count, status
                ) VALUES ($1, $2, $3, $4, 'pending')
                RETURNING job_id::text
                """,
                user_id,
                transcript,
                target_duration,
                segment_count,
            )
        job_id = row["job_id"]

    async with db_pool.acquire() as conn:
        panels = await fetch_user_panels(conn, user_id)
        if not panels:
            raise RuntimeError("No journey panels found for this client")
        archetype_row = await fetch_archetype(conn, user_id)
        archetype_hint = (archetype_row.get("archetype_hint") or "").strip()
        alignments = align_transcript_to_panels(
            transcript, panels, segment_count=segment_count,
            archetype_hint=archetype_hint,
        )
        chat_captures: list[dict[str, Any]] = []
        for seg in alignments:
            caps = await fetch_ask_nate_captures(
                conn, user_id, seg.get("panel_id", ""), seg.get("generated_at"),
            )
            chat_captures.append(
                {"segment_index": seg["segment_index"], "panel_id": seg.get("panel_id"), "messages": caps}
            )
        await conn.execute(
            """
            UPDATE sse_journey_recap_jobs SET
                audio_r2_key = $2,
                audio_r2_url = $3,
                panel_alignments = $4::jsonb,
                chat_captures = $5::jsonb,
                archetype_hint = $6,
                archetype_image_url = $7,
                status = 'aligning',
                updated_at = NOW()
            WHERE job_id = $1::uuid
            """,
            uuid.UUID(job_id),
            audio_r2_key,
            audio_r2_url,
            json.dumps(_json_safe(alignments)),
            json.dumps(_json_safe(chat_captures)),
            archetype_hint or None,
            archetype_row.get("archetype_image_url"),
        )

    scenes = _alignments_to_studio_scenes(
        alignments, chat_captures,
        job_id=job_id, archetype_hint=archetype_hint, seg_dur=seg_dur,
    )
    script_text = _build_studio_script_text(
        alignments,
        archetype_hint=archetype_hint,
        segment_count=segment_count,
        target_duration=target_duration,
    )

    return {
        "job_id": job_id,
        "user_id": user_id,
        "transcript": transcript,
        "audio_url": audio_r2_url,
        "archetype": archetype_hint,
        "script": script_text,
        "scenes": scenes,
        "panel_count": len(panels),
        "target_duration_seconds": target_duration,
        "segment_count": segment_count,
        "ingest_mode": "panel_aligned",
    }


async def _complete_studio_ingest_audio_driven(
    db_pool,
    *,
    user_id: str,
    transcript: str,
    video_duration_seconds: float,
    audio_r2_key: Optional[str] = None,
    audio_r2_url: Optional[str] = None,
    existing_job_id: Optional[str] = None,
) -> dict[str, Any]:
    """Video upload path: story beats from transcript/audio, no journey panel grab."""
    user_id = user_id.strip()
    transcript = (transcript or "").strip()
    if len(transcript) < 20:
        raise RuntimeError("Transcript too short (minimum 20 characters)")

    target_duration, segment_durations = plan_trailer_segment_durations(video_duration_seconds)
    segment_count = len(segment_durations)
    seg_dur = segment_duration(target_duration, segment_count)

    if existing_job_id:
        job_id = existing_job_id
        async with db_pool.acquire() as conn:
            user_id = await resolve_recap_user_id(conn, user_id)
            await conn.execute(
                """
                UPDATE sse_journey_recap_jobs SET
                    transcript_text = $2,
                    target_duration_seconds = $3,
                    segment_count = $4,
                    updated_at = NOW()
                WHERE job_id = $1::uuid
                """,
                uuid.UUID(job_id),
                transcript,
                target_duration,
                segment_count,
            )
    else:
        async with db_pool.acquire() as conn:
            user_id = await resolve_recap_user_id(conn, user_id)
            row = await conn.fetchrow(
                """
                INSERT INTO sse_journey_recap_jobs (
                    user_id, transcript_text, target_duration_seconds, segment_count, status
                ) VALUES ($1, $2, $3, $4, 'pending')
                RETURNING job_id::text
                """,
                user_id,
                transcript,
                target_duration,
                segment_count,
            )
        job_id = row["job_id"]

    async with db_pool.acquire() as conn:
        archetype_row = await fetch_archetype(conn, user_id)
        archetype_hint = (archetype_row.get("archetype_hint") or "").strip()
        archetype_url = archetype_row.get("archetype_image_url")
        alignments = await align_transcript_to_trailer_beats(
            transcript,
            segment_durations=segment_durations,
            source_duration_seconds=video_duration_seconds,
            archetype_hint=archetype_hint,
        )
        chat_captures: list[dict[str, Any]] = [
            {"segment_index": seg["segment_index"], "panel_id": None, "messages": []}
            for seg in alignments
        ]
        await conn.execute(
            """
            UPDATE sse_journey_recap_jobs SET
                audio_r2_key = $2,
                audio_r2_url = $3,
                panel_alignments = $4::jsonb,
                chat_captures = $5::jsonb,
                archetype_hint = $6,
                archetype_image_url = $7,
                status = 'aligning',
                updated_at = NOW()
            WHERE job_id = $1::uuid
            """,
            uuid.UUID(job_id),
            audio_r2_key,
            audio_r2_url,
            json.dumps(_json_safe(alignments)),
            json.dumps(_json_safe(chat_captures)),
            archetype_hint or None,
            archetype_url,
        )

    scenes = _alignments_to_studio_scenes(
        alignments, chat_captures,
        job_id=job_id, archetype_hint=archetype_hint, seg_dur=seg_dur,
    )
    script_text = _build_studio_script_text(
        alignments,
        archetype_hint=archetype_hint,
        segment_count=segment_count,
        target_duration=target_duration,
    )

    return {
        "job_id": job_id,
        "user_id": user_id,
        "transcript": transcript,
        "audio_url": audio_r2_url,
        "archetype": archetype_hint,
        "script": script_text,
        "scenes": scenes,
        "panel_count": 0,
        "target_duration_seconds": target_duration,
        "segment_count": segment_count,
        "ingest_mode": "audio_driven",
        "job_status": "aligning",
        "video_duration_seconds": round(video_duration_seconds, 2),
        "segment_durations": segment_durations,
        "trailer_mode": True,
    }


async def ingest_studio_transcript(
    db_pool,
    *,
    user_id: str,
    transcript: str,
    ingest_mode: str = INGEST_MODE_AUDIO,
    source_duration_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """Paste transcript → trailer beats (audio_driven) or panel-aligned 30s recap.

    Audio-driven returns alignments immediately; caller should queue
    ``run_trailer_auto_pipeline`` as a BackgroundTask so Studio can poll to complete.
    """
    if not feature_enabled():
        raise RuntimeError("Journey recap video is disabled (ENABLE_JOURNEY_RECAP_VIDEO)")
    mode = normalize_ingest_mode(ingest_mode)
    if mode == INGEST_MODE_PANEL:
        return await _complete_studio_ingest_from_transcript(
            db_pool, user_id=user_id, transcript=transcript,
        )
    duration = float(source_duration_seconds or 0) or estimate_duration_from_transcript(transcript)
    result = await _complete_studio_ingest_audio_driven(
        db_pool,
        user_id=user_id,
        transcript=transcript,
        video_duration_seconds=duration,
    )
    result["async_pipeline"] = True
    result["message"] = (
        "Transcript aligned into ≤2 min trailer scenes — render + stitch queued."
    )
    return result


async def enqueue_studio_video_ingest(
    db_pool,
    *,
    user_id: str,
    video_bytes: bytes,
    filename: str = "upload.mp4",
    ingest_mode: str = INGEST_MODE_AUDIO,
) -> dict[str, Any]:
    """Accept upload quickly; processing continues in run_studio_video_ingest_task."""
    if not feature_enabled():
        raise RuntimeError("Journey recap video is disabled (ENABLE_JOURNEY_RECAP_VIDEO)")

    mode = normalize_ingest_mode(ingest_mode)
    job_id = str(uuid.uuid4())
    work_dir = _studio_ingest_work_dir(job_id)
    ext = os.path.splitext(filename or "upload.mp4")[1] or ".mp4"
    video_path = os.path.join(work_dir, f"source{ext}")
    with open(video_path, "wb") as f:
        f.write(video_bytes)

    duration = ffprobe_media_duration_seconds(video_path)
    if not duration or duration < 1:
        duration = float(DEFAULT_TARGET_DURATION)

    if mode == INGEST_MODE_PANEL:
        target_duration = DEFAULT_TARGET_DURATION
        segment_count = DEFAULT_SEGMENT_COUNT
    else:
        target_duration, segment_durations = plan_trailer_segment_durations(duration)
        segment_count = len(segment_durations)

    async with db_pool.acquire() as conn:
        resolved_uid = await resolve_recap_user_id(conn, user_id.strip())
        await conn.execute(
            """
            INSERT INTO sse_journey_recap_jobs (
                job_id, user_id, transcript_text, target_duration_seconds, segment_count, status
            ) VALUES ($1::uuid, $2, $3, $4, $5, 'pending')
            """,
            uuid.UUID(job_id),
            resolved_uid,
            "(processing upload…)",
            target_duration,
            segment_count,
        )

    return {
        "job_id": job_id,
        "user_id": resolved_uid,
        "status": "pending",
        "async": True,
        "ingest_mode": mode,
        "target_duration_seconds": target_duration,
        "segment_count": segment_count,
        "video_duration_seconds": round(duration, 2),
        "message": (
            "Video queued — transcribing and building up to 2 min Thera-World trailer scenes "
            "(render + stitch run automatically)."
        ),
    }


async def _mark_studio_ingest_failed(db_pool, job_id: str, message: str) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sse_journey_recap_jobs SET
                status = 'failed',
                error_message = $2,
                updated_at = NOW()
            WHERE job_id = $1::uuid
            """,
            uuid.UUID(job_id),
            (message or "Ingest failed")[:2000],
        )


async def run_studio_video_ingest_task(
    db_pool,
    *,
    job_id: str,
    ingest_mode: str,
    filename: str = "upload.mp4",
) -> None:
    """Background worker: extract audio, transcribe, align, generate beat images."""
    mode = normalize_ingest_mode(ingest_mode)
    work_dir = _studio_ingest_work_dir(job_id)
    try:
        ext = os.path.splitext(filename or "upload.mp4")[1] or ".mp4"
        video_path = os.path.join(work_dir, f"source{ext}")
        if not os.path.isfile(video_path):
            raise RuntimeError("Uploaded video file missing on server")

        wav_path = os.path.join(work_dir, "audio.wav")
        if not await _extract_audio_from_video(video_path, wav_path):
            raise RuntimeError("Could not extract audio from video (ffmpeg)")

        with open(wav_path, "rb") as f:
            audio_bytes = f.read()

        transcript = await _transcribe_audio_wav(wav_path)
        if not transcript.strip():
            raise RuntimeError("Transcription returned empty text")

        duration = ffprobe_media_duration_seconds(video_path) or ffprobe_media_duration_seconds(wav_path)
        if not duration or duration < 1:
            duration = float(DEFAULT_TARGET_DURATION)

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
                uuid.UUID(job_id),
            )
        if not row:
            raise RuntimeError("Recap job not found")
        resolved_uid = str(row["user_id"])

        if mode == INGEST_MODE_PANEL:
            job_payload = await _complete_studio_ingest_from_transcript(
                db_pool,
                user_id=resolved_uid,
                transcript=transcript,
                existing_job_id=job_id,
            )
            job_payload["ingest_mode"] = INGEST_MODE_PANEL
            job_payload["video_duration_seconds"] = round(duration, 2)
        else:
            job_payload = await _complete_studio_ingest_audio_driven(
                db_pool,
                user_id=resolved_uid,
                transcript=transcript,
                video_duration_seconds=duration,
                existing_job_id=job_id,
            )

        audio_key = f"sse/journey-recap/{resolved_uid}/{job_id}/source_audio.wav"
        audio_url = await r2_storage.store_bytes(audio_bytes, audio_key, "audio/wav")

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sse_journey_recap_jobs SET
                    audio_r2_key = $2,
                    audio_r2_url = $3,
                    updated_at = NOW()
                WHERE job_id = $1::uuid
                """,
                uuid.UUID(job_id),
                audio_key,
                audio_url,
            )
        logger.info("[JOURNEY-RECAP] Studio video ingest complete job_id=%s mode=%s", job_id, mode)
        if mode == INGEST_MODE_AUDIO:
            await run_trailer_auto_pipeline(db_pool, job_id)
    except Exception as exc:
        logger.exception("[JOURNEY-RECAP] Studio video ingest failed job_id=%s", job_id)
        await _mark_studio_ingest_failed(db_pool, job_id, str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _clip_is_usable(meta: dict[str, Any]) -> bool:
    return bool(meta and (meta.get("video_url") or meta.get("r2_key")))


def _usable_clip_count(clips: Any) -> int:
    if not clips or not isinstance(clips, list):
        return 0
    return sum(1 for c in clips if _clip_is_usable(c))


async def ensure_recap_clips_for_stitch(
    db_pool,
    job_id: str,
    *,
    ken_burns_only: bool = True,
) -> list[dict[str, Any]]:
    """Render any missing segment clips before stitch (Ken Burns by default for fast path)."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT panel_alignments, segment_clips, segment_count
            FROM sse_journey_recap_jobs WHERE job_id = $1::uuid
            """,
            uuid.UUID(job_id),
        )
    if not row:
        raise ValueError("Job not found")

    alignments = row["panel_alignments"]
    if isinstance(alignments, str):
        alignments = json.loads(alignments)
    if not isinstance(alignments, list) or not alignments:
        raise RuntimeError("Job has no panel alignments — run ingest first")

    clips = row["segment_clips"]
    if isinstance(clips, str):
        clips = json.loads(clips)
    if not isinstance(clips, list):
        clips = []

    need = int(row.get("segment_count") or len(alignments) or DEFAULT_SEGMENT_COUNT)
    usable_idx = {
        c.get("segment_index")
        for c in clips
        if _clip_is_usable(c) and c.get("segment_index") is not None
    }
    missing = [i for i in range(len(alignments)) if i not in usable_idx]
    if not missing and _usable_clip_count(clips) >= need:
        return clips

    for idx in missing:
        await render_recap_segment(db_pool, job_id, idx, ken_burns_only=ken_burns_only)

    async with db_pool.acquire() as conn:
        row2 = await conn.fetchrow(
            "SELECT segment_clips FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
            uuid.UUID(job_id),
        )
    clips = row2["segment_clips"] if row2 else []
    if isinstance(clips, str):
        clips = json.loads(clips)
    if _usable_clip_count(clips) < 1:
        raise RuntimeError("Segment clip render failed — try Render All Scene Clips in Scenes tab")
    return clips if isinstance(clips, list) else []


async def render_recap_segment(
    db_pool,
    job_id: str,
    segment_index: int,
    *,
    ken_burns_only: bool = False,
) -> dict[str, Any]:
    """Render one recap segment (Grok or Ken Burns) and persist clip metadata."""
    if not feature_enabled():
        raise RuntimeError("Journey recap video is disabled")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, panel_alignments, chat_captures,
                   archetype_hint, archetype_image_url,
                   target_duration_seconds, segment_count
            FROM sse_journey_recap_jobs WHERE job_id = $1::uuid
            """,
            uuid.UUID(job_id),
        )
    if not row:
        raise ValueError("Job not found")

    user_id = row["user_id"]
    alignments = row["panel_alignments"]
    if isinstance(alignments, str):
        alignments = json.loads(alignments)
    chat_captures = row["chat_captures"]
    if isinstance(chat_captures, str):
        chat_captures = json.loads(chat_captures)
    if not isinstance(alignments, list) or not alignments:
        raise RuntimeError("Job has no panel alignments — run ingest first")

    if segment_index < 0 or segment_index >= len(alignments):
        raise ValueError(f"Invalid segment index {segment_index}")

    target_duration = int(row.get("target_duration_seconds") or DEFAULT_TARGET_DURATION)
    segment_count = int(row.get("segment_count") or DEFAULT_SEGMENT_COUNT)

    seg = dict(alignments[segment_index])
    seg_dur = float(
        seg.get("duration_seconds") or segment_duration(target_duration, segment_count),
    )
    seg["r2_url"] = refresh_panel_r2_url(seg.get("r2_url"), r2_key=seg.get("r2_key"))
    chat_by_idx = {c["segment_index"]: c.get("messages") or [] for c in (chat_captures or [])}
    snippets = [m.get("text", "") for m in chat_by_idx.get(segment_index, []) if m.get("text")]
    archetype_hint = (row.get("archetype_hint") or "").strip()
    motion = build_motion_prompt(
        archetype_hint=archetype_hint,
        narrative=seg.get("narrative_text") or "",
        biome=seg.get("biome") or "",
        transcript_excerpt=seg.get("transcript_excerpt") or "",
        chat_snippets=snippets,
        panel=seg,
        visual_theme=seg.get("panel_visual_theme") or "",
    )
    archetype_url = row.get("archetype_image_url")

    if str(seg.get("panel_type") or "").lower() == "story_beat" and not seg.get("r2_url"):
        seg = await ensure_segment_still_image(
            seg,
            user_id=user_id,
            job_id=job_id,
            archetype_hint=archetype_hint,
            archetype_image_url=archetype_url,
        )

    work_dir = tempfile.mkdtemp(prefix="sse_recap_seg_")
    try:
        meta = await _render_segment_clip(
            seg, motion, archetype_url, seg_dur, work_dir,
            user_id=user_id, job_id=job_id,
            ken_burns_only=ken_burns_only,
        )
        meta["motion_prompt"] = motion
        if meta.get("video_url"):
            meta["video_status"] = meta.get("status", "complete")

        async with db_pool.acquire() as conn:
            job_row = await conn.fetchrow(
                "SELECT segment_clips FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
                uuid.UUID(job_id),
            )
            clips = job_row["segment_clips"] if job_row else []
            if isinstance(clips, str):
                clips = json.loads(clips)
            if not isinstance(clips, list):
                clips = []
            while len(clips) <= segment_index:
                clips.append({})
            clips[segment_index] = meta
            await conn.execute(
                """
                UPDATE sse_journey_recap_jobs SET
                    segment_clips = $2::jsonb,
                    status = 'rendering',
                    updated_at = NOW()
                WHERE job_id = $1::uuid
                """,
                uuid.UUID(job_id),
                json.dumps(_json_safe(clips)),
            )
        return meta
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def render_all_recap_segments(db_pool, job_id: str) -> list[dict[str, Any]]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT panel_alignments FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
            uuid.UUID(job_id),
        )
    if not row:
        raise ValueError("Job not found")
    alignments = row["panel_alignments"]
    if isinstance(alignments, str):
        alignments = json.loads(alignments)
    results: list[dict[str, Any]] = []
    n = len(alignments or [])
    for idx in range(n):
        if idx > 0:
            await asyncio.sleep(8)
        try:
            results.append(await render_recap_segment(db_pool, job_id, idx))
        except Exception as e:
            logger.warning("[JOURNEY-RECAP] segment %d failed job=%s: %s", idx, job_id, e)
            results.append({"segment_index": idx, "status": "failed", "error": str(e)})
    grok_n = sum(1 for r in results if r.get("status") == "grok")
    kb_n = sum(1 for r in results if r.get("status") == "ken_burns")
    fail_n = sum(1 for r in results if r.get("status") not in ("grok", "ken_burns"))
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sse_journey_recap_jobs SET
                status = 'clips_ready',
                updated_at = NOW()
            WHERE job_id = $1::uuid
            """,
            uuid.UUID(job_id),
        )
    logger.info(
        "[JOURNEY-RECAP] render-all job %s done: grok=%d ken_burns=%d failed=%d",
        job_id, grok_n, kb_n, fail_n,
    )
    return results


async def run_trailer_auto_pipeline(db_pool, job_id: str) -> None:
    """After audio-driven ingest: render all scenes then stitch (no client audio mux)."""
    if os.getenv("JOURNEY_RECAP_AUTO_RENDER_STITCH", "true").strip().lower() not in (
        "1", "true", "yes",
    ):
        return
    try:
        async with db_pool.acquire() as conn:
            await _set_job_status(conn, job_id, "rendering")
        await render_all_recap_segments(db_pool, job_id)
        await stitch_recap_job_only(db_pool, job_id, mux_client_audio=False)
        logger.info("[JOURNEY-RECAP] Auto trailer pipeline complete job_id=%s", job_id)
    except Exception as exc:
        logger.exception("[JOURNEY-RECAP] Auto trailer pipeline failed job_id=%s", job_id)
        async with db_pool.acquire() as conn:
            await _set_job_status(
                conn,
                job_id,
                "failed",
                error_message=f"auto_pipeline: {str(exc)[:1800]}",
            )


async def stitch_recap_job_only(
    db_pool,
    job_id: str,
    *,
    mux_client_audio: Optional[bool] = None,
) -> dict[str, Any]:
    """Stitch existing segment clips into final recap (trailer: silent, no client audio)."""
    if not feature_enabled():
        raise RuntimeError("Journey recap video is disabled")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, audio_r2_key, audio_r2_url, segment_clips,
                   target_duration_seconds, segment_count, panel_alignments
            FROM sse_journey_recap_jobs WHERE job_id = $1::uuid
            """,
            uuid.UUID(job_id),
        )
    if not row:
        raise ValueError("Job not found")

    alignments = row["panel_alignments"]
    if isinstance(alignments, str):
        alignments = json.loads(alignments)
    ingest_mode = _infer_ingest_mode_from_alignments(
        alignments if isinstance(alignments, list) else [],
    )
    if mux_client_audio is None:
        mux_client_audio = ingest_mode == INGEST_MODE_PANEL

    user_id = row["user_id"]
    clips = row["segment_clips"]
    if isinstance(clips, str):
        clips = json.loads(clips)
    need = int(row.get("segment_count") or DEFAULT_SEGMENT_COUNT)
    if _usable_clip_count(clips) < need:
        clips = await ensure_recap_clips_for_stitch(db_pool, job_id, ken_burns_only=True)
    if not clips or _usable_clip_count(clips) < 1:
        raise RuntimeError(
            "No segment clips rendered yet — click Render All Scene Clips, "
            "or retry stitch to auto-build Ken Burns clips from panel stills"
        )

    work_dir = tempfile.mkdtemp(prefix="sse_recap_stitch_")
    try:
        audio_path = None
        if mux_client_audio:
            audio_key = row["audio_r2_key"]
            if audio_key:
                data = await r2_storage.download_bytes(audio_key)
                if data:
                    audio_path = os.path.join(work_dir, "full_audio.wav")
                    with open(audio_path, "wb") as f:
                        f.write(data)

        target_duration = int(row.get("target_duration_seconds") or DEFAULT_TARGET_DURATION)
        segment_count = int(row.get("segment_count") or DEFAULT_SEGMENT_COUNT)
        segment_durations: Optional[list[int]] = None
        if isinstance(alignments, list) and alignments:
            durs = [
                int(a.get("duration_seconds"))
                for a in alignments
                if a.get("duration_seconds") is not None
            ]
            if len(durs) == len(alignments):
                segment_durations = durs

        mp4_bytes, stitch_errors = await stitch_recap_video(
            clips,
            audio_local_path=audio_path,
            target_duration=target_duration,
            segment_count=segment_count,
            segment_durations=segment_durations,
            mux_client_audio=mux_client_audio,
        )
        if not mp4_bytes:
            raise RuntimeError("; ".join(stitch_errors) or "Stitch failed")

        out_key = f"sse/journey-recap/{user_id}/{job_id}/recap_final.mp4"
        out_url = await r2_storage.store_bytes(mp4_bytes, out_key, "video/mp4")

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sse_journey_recap_jobs SET
                    status = 'complete',
                    output_r2_key = $2,
                    output_r2_url = $3,
                    error_message = $4,
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE job_id = $1::uuid
                """,
                uuid.UUID(job_id),
                out_key,
                out_url,
                "; ".join(stitch_errors) if stitch_errors else None,
            )
        return {"output_url": out_url, "output_r2_key": out_key, "errors": stitch_errors}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
