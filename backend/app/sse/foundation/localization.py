"""SSE Stage 8 — Localization pipeline.

Translation for SSE narrative text. Supported: en, es, fr, pt, de.
English is the default — others translated on demand via Grok.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SUPPORTED_LOCALES = {"en", "es", "fr", "pt", "de"}


def extract_localizable_text(story_plot: dict) -> dict[str, Any]:
    """Extract human-readable panel text fields needing translation."""
    strings: dict[str, str] = {}
    for panel in story_plot.get("panels", []):
        pid = panel.get("phase_id", panel.get("id", ""))
        scene = panel.get("scene_description", "")
        if scene:
            strings[f"{pid}_scene"] = scene

        prompt = panel.get("grok_imagine_prompt", "")
        suffix = panel.get("core_character_suffix", "")
        if prompt and suffix and prompt.endswith(suffix):
            prompt = prompt[: -len(suffix)].rstrip(", ").strip()
        if prompt:
            strings[f"{pid}_prompt_text"] = prompt

    return {
        "storyboard_id": story_plot.get("storyboard_id", story_plot.get("id", "")),
        "source_locale": "en",
        "strings": strings,
    }


async def translate_story_plot(
    story_plot: dict, target_locale: str, db_pool
) -> dict[str, Any]:
    """Translate story_plot panel text to target_locale. Caches in DB."""
    if target_locale not in SUPPORTED_LOCALES or target_locale == "en":
        return story_plot

    extracted = extract_localizable_text(story_plot)
    sid = extracted["storyboard_id"]

    if db_pool:
        try:
            async with db_pool.acquire() as c:
                cached = await c.fetchval(
                    "SELECT strings FROM sse_locale_strings "
                    "WHERE storyboard_id=$1 AND locale=$2", sid, target_locale)
                if cached:
                    return _apply_translations(
                        story_plot, json.loads(cached) if isinstance(cached, str) else cached)
        except Exception as e:
            logger.warning("localization: cache lookup failed: %s", e)

    grok_url = os.getenv("NATE_CHAT_URL", "")
    grok_key = os.getenv("NATE_CHAT_KEY", "")
    grok_model = os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")
    if not grok_url or not grok_key:
        logger.warning("localization: NATE_CHAT_URL/KEY not set — skipping translation")
        return story_plot

    sys_prompt = (
        f"Translate the following JSON values to {target_locale}. "
        "Return JSON only — same keys, translated values. "
        "Preserve therapeutic meaning. Do not translate proper nouns."
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{grok_url}/chat/completions",
                headers={"Authorization": f"Bearer {grok_key}", "Content-Type": "application/json"},
                json={"model": grok_model, "temperature": 0.3,
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": json.dumps(extracted["strings"])}]},
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            translated = json.loads(content.strip().strip("`").removeprefix("json").strip())
    except Exception as e:
        logger.warning("localization: Grok translation failed: %s", e)
        return story_plot

    if db_pool:
        try:
            async with db_pool.acquire() as c:
                await c.execute(
                    "INSERT INTO sse_locale_strings (locale_id,storyboard_id,locale,strings) "
                    "VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(storyboard_id,locale) DO UPDATE "
                    "SET strings=EXCLUDED.strings, translated_at=NOW()",
                    str(uuid.uuid4()), sid, target_locale, json.dumps(translated))
        except Exception as e:
            logger.warning("localization: cache store failed: %s", e)

    return _apply_translations(story_plot, translated)


async def get_locale_story_plot(
    storyboard_id: str, locale: str, db_pool
) -> dict[str, Any] | None:
    """Retrieve cached translated strings for a locale."""
    if not db_pool or locale == "en":
        return None
    try:
        async with db_pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT strings FROM sse_locale_strings "
                "WHERE storyboard_id=$1 AND locale=$2", storyboard_id, locale)
        if row:
            return json.loads(row["strings"]) if isinstance(row["strings"], str) else dict(row["strings"])
    except Exception as e:
        logger.warning("localization: get_locale failed: %s", e)
    return None


def _apply_translations(story_plot: dict, translations: dict) -> dict:
    """Replace panel text fields with translations."""
    result = copy.deepcopy(story_plot)
    for panel in result.get("panels", []):
        pid = panel.get("phase_id", panel.get("id", ""))
        scene_key = f"{pid}_scene"
        if scene_key in translations:
            panel["scene_description"] = translations[scene_key]
        prompt_key = f"{pid}_prompt_text"
        if prompt_key in translations:
            suffix = panel.get("core_character_suffix", "")
            panel["grok_imagine_prompt"] = translations[prompt_key] + (f", {suffix}" if suffix else "")
    return result
