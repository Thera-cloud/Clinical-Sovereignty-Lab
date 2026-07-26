"""SSE Layer 6 — Imagination Engine.

Orchestrates image generation for a complete story plot from Stage 1.
For each panel, calls Grok Imagine with the pre-built prompt (which already
includes the core character suffix from the BEDROCK RULE) and stores the
result in R2.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from app.sse.infrastructure import grok_imagine_client, r2_storage

logger = logging.getLogger(__name__)

_BATCH_SIZE = 5
_BATCH_DELAY_S = 2.0
_COST_PER_IMAGE = 0.05


def _style_anchor_text(preset_id: str | None) -> str:
    if not preset_id:
        return ""
    try:
        from app.sse.trailer_generator import _fuse_visual_style_anchor, _load_preset_document

        doc = _load_preset_document(preset_id)
        return _fuse_visual_style_anchor(doc)
    except Exception as e:
        logger.warning("imagination_engine: style anchor load failed for %s: %s", preset_id, e)
        return ""


async def _process_panel(
    panel: dict[str, Any],
    storyboard_id: str,
    style_anchor: str = "",
) -> dict[str, Any]:
    """Generate and store image for a single panel."""
    phase_id = panel.get("phase_id", "unknown")
    suffix = panel.get("core_character_suffix", "")

    # Thera-World bedrock: require manifestation suffix. Custom subsets may use style anchor only.
    if not suffix and not style_anchor:
        logger.warning(
            "imagination_engine: panel %s missing core_character_suffix — skipping (bedrock rule)",
            phase_id,
        )
        return {"phase_id": phase_id, "error": "missing core_character_suffix"}

    prompt = panel.get("grok_imagine_prompt", "")
    if not prompt:
        return {"phase_id": phase_id, "error": "empty grok_imagine_prompt"}

    if style_anchor and style_anchor not in prompt:
        prompt = f"{prompt}, {style_anchor}"

    _NO_TEXT = "no text, no words, no lettering, no calligraphy, no writing on image"
    if _NO_TEXT not in prompt:
        prompt = f"{prompt}, {_NO_TEXT}"

    image_bytes = await grok_imagine_client.generate_image(prompt)

    content_hash = hashlib.sha256(image_bytes).hexdigest()[:8]
    key = f"sse/staging/{storyboard_id}/{phase_id}/{content_hash}.png"

    r2_url = await r2_storage.store_image(image_bytes, key)

    return {
        "phase_id": phase_id,
        "r2_url": r2_url,
        "prompt_used": prompt,
        "panel_tone": panel.get("panel_tone", "action_sequence"),
    }


async def generate_story_imagery(
    story_plot: dict[str, Any],
    preset_id: str | None = None,
) -> dict[str, Any]:
    """Generate images for all panels in a story plot.

    Processes panels in batches of 5 with rate-limiting between batches.
    Failures on individual panels are logged and included in results
    without halting the pipeline.

    preset_id selects a Studio subset generator (visual_style_anchor). Thera-World
    is the default bedrock subset when unset and story_plot has no preset_id.
    """
    storyboard_id = story_plot.get("id", "unknown")
    panels = story_plot.get("panels", [])
    pid = preset_id or story_plot.get("preset_id")
    style_anchor = _style_anchor_text(pid if isinstance(pid, str) else None)

    results: list[dict[str, Any]] = []
    generated = 0
    failed = 0

    for batch_start in range(0, len(panels), _BATCH_SIZE):
        batch = panels[batch_start : batch_start + _BATCH_SIZE]
        tasks = [_process_panel(p, storyboard_id, style_anchor=style_anchor) for p in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                phase_id = batch[i].get("phase_id", "unknown")
                logger.error(
                    "imagination_engine: panel %s failed: %s", phase_id, result
                )
                results.append({"phase_id": phase_id, "error": str(result)})
                failed += 1
            elif "error" in result:
                results.append(result)
                failed += 1
            else:
                results.append(result)
                generated += 1

        if batch_start + _BATCH_SIZE < len(panels):
            await asyncio.sleep(_BATCH_DELAY_S)

    return {
        "storyboard_id": storyboard_id,
        "preset_id": pid,
        "panels_generated": generated,
        "panels_failed": failed,
        "estimated_cost": f"${generated * _COST_PER_IMAGE:.2f}",
        "results": results,
    }
