"""SSE Layer 6 — Imagination Engine.

Orchestrates image generation for a complete story plot from Stage 1.
Uses trained Flux+LoRA when a Studio project is linked; otherwise Grok Imagine
with subset visual_style_anchor.
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


def _cast_keys(preset_id: str | None) -> list[str]:
    if not preset_id:
        return []
    try:
        from app.sse.trailer_generator import preset_character_keys
        return list(preset_character_keys(preset_id) or [])
    except Exception:
        return []


async def _process_panel(
    panel: dict[str, Any],
    storyboard_id: str,
    style_anchor: str = "",
    trained_loras: dict[str, Any] | None = None,
    cast_keys: list[str] | None = None,
    preset_id: str | None = None,
) -> dict[str, Any]:
    """Generate and store image for a single panel."""
    phase_id = panel.get("phase_id", "unknown")
    suffix = panel.get("core_character_suffix", "")
    trained_loras = trained_loras or {}
    cast_keys = cast_keys or []

    # Thera-World bedrock: require manifestation suffix. Custom subsets may use style/LoRA only.
    if not suffix and not style_anchor and not trained_loras:
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

    image_bytes: bytes | None = None
    engine = "grok_imagine"

    relevant = {
        k: v for k, v in trained_loras.items()
        if isinstance(v, dict) and v.get("lora_url") and (not cast_keys or k in cast_keys)
    }
    if not relevant and trained_loras:
        # Use all trained LoRAs for the linked project when cast keys unknown
        relevant = {
            k: v for k, v in trained_loras.items()
            if isinstance(v, dict) and v.get("lora_url")
        }

    if relevant:
        try:
            from app.sse.infrastructure.replicate_client import generate_with_loras
            from app.sse.trailer_generator import _build_lora_prompt

            chars = list(relevant.keys())
            lora_prompt = _build_lora_prompt(
                prompt, chars, trained_loras, scene_num=0, preset_id=preset_id,
            )
            lora_urls = [info["lora_url"] for info in relevant.values()]
            urls = await generate_with_loras(
                lora_prompt, lora_urls, width=1024, height=576, character_keys=chars,
            )
            if urls:
                async with __import__("aiohttp").ClientSession() as sess:
                    async with sess.get(urls[0]) as resp:
                        if resp.status == 200:
                            image_bytes = await resp.read()
                            engine = "flux_lora"
                            prompt = lora_prompt
        except Exception as e:
            logger.warning("imagination_engine: LoRA gen failed, falling back to Grok: %s", e)

    if image_bytes is None:
        image_bytes = await grok_imagine_client.generate_image(prompt)

    content_hash = hashlib.sha256(image_bytes).hexdigest()[:8]
    key = f"sse/staging/{storyboard_id}/{phase_id}/{content_hash}.png"

    r2_url = await r2_storage.store_image(image_bytes, key)

    return {
        "phase_id": phase_id,
        "r2_url": r2_url,
        "prompt_used": prompt,
        "engine": engine,
        "panel_tone": panel.get("panel_tone", "action_sequence"),
    }


async def generate_story_imagery(
    story_plot: dict[str, Any],
    preset_id: str | None = None,
    project_id: str | None = None,
    db_pool=None,
) -> dict[str, Any]:
    """Generate images for all panels in a story plot.

    When project_id is set (or story_plot.studio_project_id), uses trained LoRAs
    from that Studio project when available. If unset, resolves latest Studio
    project for the subset preset_id via db_pool.
    """
    storyboard_id = story_plot.get("id", "unknown")
    panels = story_plot.get("panels", [])
    pid = preset_id or story_plot.get("preset_id")
    if isinstance(pid, str):
        pid = pid.strip() or None
    else:
        pid = None
    style_anchor = _style_anchor_text(pid)
    cast_keys = _cast_keys(pid)

    proj = project_id or story_plot.get("studio_project_id") or story_plot.get("project_id")
    if not proj and pid and db_pool:
        try:
            from app.sse.studio_service import find_latest_project_for_preset
            proj = await find_latest_project_for_preset(pid, db_pool)
        except Exception as e:
            logger.warning("imagination_engine: preset→project resolve failed: %s", e)
    trained_loras: dict[str, Any] = {}
    if proj:
        try:
            from app.sse.trailer_generator import _load_trained_loras
            trained_loras = await _load_trained_loras(str(proj), preset_id=pid) or {}
        except Exception as e:
            logger.warning("imagination_engine: trained LoRA load failed: %s", e)

    results: list[dict[str, Any]] = []
    generated = 0
    failed = 0
    lora_used = 0

    for batch_start in range(0, len(panels), _BATCH_SIZE):
        batch = panels[batch_start : batch_start + _BATCH_SIZE]
        tasks = [
            _process_panel(
                p, storyboard_id,
                style_anchor=style_anchor,
                trained_loras=trained_loras,
                cast_keys=cast_keys,
                preset_id=pid,
            )
            for p in batch
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                phase_id = batch[i].get("phase_id", "unknown")
                logger.error("imagination_engine: panel %s failed: %s", phase_id, result)
                results.append({"phase_id": phase_id, "error": str(result)})
                failed += 1
            elif "error" in result:
                results.append(result)
                failed += 1
            else:
                results.append(result)
                generated += 1
                if result.get("engine") == "flux_lora":
                    lora_used += 1

        if batch_start + _BATCH_SIZE < len(panels):
            await asyncio.sleep(_BATCH_DELAY_S)

    return {
        "storyboard_id": storyboard_id,
        "preset_id": pid,
        "project_id": proj,
        "panels_generated": generated,
        "panels_failed": failed,
        "lora_panels": lora_used,
        "estimated_cost": f"${generated * _COST_PER_IMAGE:.2f}",
        "results": results,
    }
