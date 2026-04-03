"""SSE Stage 8 — Layer 8 Mission Fibre.

Locale-aware rendering layer — wraps localization.py for delivery pipeline use.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_panel_for_locale(
    storyboard_id: str, phase_id: str, user_locale: str, db_pool
) -> dict[str, Any]:
    """Get panel content for a user's locale, falling back to English."""
    if user_locale and user_locale != "en":
        try:
            from app.sse.foundation.localization import get_locale_story_plot
            translations = await get_locale_story_plot(storyboard_id, user_locale, db_pool)
            if translations:
                scene_key = f"{phase_id}_scene"
                prompt_key = f"{phase_id}_prompt_text"
                if scene_key in translations:
                    return {
                        "phase_id": phase_id,
                        "scene_description": translations[scene_key],
                        "grok_imagine_prompt": translations.get(prompt_key, ""),
                        "locale": user_locale,
                    }
        except Exception as e:
            logger.warning("mission_fibre: locale lookup failed: %s", e)

    if not db_pool:
        return {"phase_id": phase_id, "locale": "en"}
    try:
        async with db_pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT delivery_config FROM sse_delivery_config "
                "WHERE storyboard_id=$1 AND status='active' ORDER BY version DESC LIMIT 1",
                storyboard_id)
        if row:
            cfg = json.loads(row["delivery_config"]) if isinstance(row["delivery_config"], str) else row["delivery_config"]
            for panel in cfg.get("panels", []):
                if panel.get("phase_id") == phase_id or panel.get("id") == phase_id:
                    panel["locale"] = "en"
                    return panel
    except Exception as e:
        logger.warning("mission_fibre: English fallback failed: %s", e)

    return {"phase_id": phase_id, "locale": "en"}


async def register_user_locale(user_id: str, locale: str, db_pool) -> None:
    """Store user locale preference — upsert."""
    if not db_pool or not user_id:
        return
    try:
        async with db_pool.acquire() as c:
            await c.execute(
                "INSERT INTO sse_user_locale (user_id, locale, updated_at) "
                "VALUES($1, $2, NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET locale=EXCLUDED.locale, updated_at=NOW()",
                user_id, locale or "en")
    except Exception as e:
        logger.warning("mission_fibre: register locale failed: %s", e)
