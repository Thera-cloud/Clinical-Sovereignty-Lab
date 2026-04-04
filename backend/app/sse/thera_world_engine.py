"""SSE Thera-World Engine — lifelong autonomous journey generation.

Generates daily journey panels for every active client using crystal memory,
biome progression, and character manifestation. Independent of workbook enrollment.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CRYSTAL_TO_CHARACTER: Dict[str, Tuple[str, str]] = {
    "attachment": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "love": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "trust": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "anxiety": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "loss": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "abandonment": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "codependency": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "depression": ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth"),
    "shame": ("Serpent", "with a subtle serpentine shadow at the edge of the frame, coiled but watchful"),
    "deception": ("Serpent", "with a subtle serpentine shadow at the edge of the frame, coiled but watchful"),
    "anger": ("Serpent", "with a subtle serpentine shadow at the edge of the frame, coiled but watchful"),
    "fear": ("Serpent", "with a subtle serpentine shadow at the edge of the frame, coiled but watchful"),
    "control": ("Serpent", "with a subtle serpentine shadow at the edge of the frame, coiled but watchful"),
    "resentment": ("Serpent", "with a subtle serpentine shadow at the edge of the frame, coiled but watchful"),
    "guilt": ("Pride/Shame", "with contrasting light and shadow splitting the scene, one side warm and one side cold"),
    "trauma": ("Pride/Shame", "with contrasting light and shadow splitting the scene, one side warm and one side cold"),
    "perfectionism": ("Pride/Shame", "with contrasting light and shadow splitting the scene, one side warm and one side cold"),
    "identity": ("Reflection", "with a mirror or reflective surface showing a slightly different version of the subject"),
    "self-worth": ("Reflection", "with a mirror or reflective surface showing a slightly different version of the subject"),
    "grief": ("Reflection", "with a mirror or reflective surface showing a slightly different version of the subject"),
    "boundaries": ("Reflection", "with a mirror or reflective surface showing a slightly different version of the subject"),
    "rejection": ("Reflection", "with a mirror or reflective surface showing a slightly different version of the subject"),
    "faith": ("Holy Spirit", "with gentle light streaming from an unseen source above, warm and golden"),
    "hope": ("Holy Spirit", "with gentle light streaming from an unseen source above, warm and golden"),
    "spiritual": ("Holy Spirit", "with gentle light streaming from an unseen source above, warm and golden"),
    "forgiveness": ("Holy Spirit", "with gentle light streaming from an unseen source above, warm and golden"),
    "wonder": ("Curiosity", "with an open door or pathway visible in the background, inviting exploration"),
    "growth": ("Curiosity", "with an open door or pathway visible in the background, inviting exploration"),
    "discovery": ("Curiosity", "with an open door or pathway visible in the background, inviting exploration"),
    "loneliness": ("Curiosity", "with an open door or pathway visible in the background, inviting exploration"),
    "vulnerability": ("Curiosity", "with an open door or pathway visible in the background, inviting exploration"),
}

_DEFAULT_CHARACTER = ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth")

BIOME_THRESHOLDS = [
    {"biome": "dark_forest", "min_sessions": 0, "min_crystals": 0,
     "description": "Dense fog, lantern light, shadows, isolation but mystery and the promise of discovery"},
    {"biome": "fortress_plains", "min_sessions": 6, "min_crystals": 20,
     "description": "Open plains dotted with towers and fortresses, defense and vigilance, vastness of possibility beyond the walls"},
    {"biome": "river_valley", "min_sessions": 16, "min_crystals": 60,
     "description": "Gentle valley with a crystal river, healing trees line the banks, meadows of wildflowers, first experiences of safety"},
    {"biome": "crystal_mountains", "min_sessions": 31, "min_crystals": 150,
     "description": "Mountains that glow from within, caves full of crystals, each crystal a validated truth"},
    {"biome": "open_sky", "min_sessions": 61, "min_crystals": 400,
     "description": "Boundless sky, the character standing freely, integration and wholeness achieved"},
]

_profile_cache: Dict[str, Tuple[float, Dict]] = {}
_CACHE_TTL = 3600


async def get_or_create_journey(user_id: str, db_pool) -> dict:
    """Get existing journey or create one for a new user."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sse_user_journeys WHERE user_id = $1", user_id)
        if row:
            return dict(row)
        jid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO sse_user_journeys (journey_id, user_id) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO NOTHING", jid, user_id)
        await conn.execute(
            "INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail) "
            "VALUES ($1, 'journey_started', 'Journey Started', $2)",
            user_id, f"User {user_id} began their Thera-World journey")
        row = await conn.fetchrow(
            "SELECT * FROM sse_user_journeys WHERE user_id = $1", user_id)
        return dict(row) if row else {"user_id": user_id, "current_biome": "dark_forest"}


async def get_therapeutic_profile(user_id: str, db_pool) -> dict:
    """Pull therapeutic state for panel generation with in-memory caching."""
    now = time.time()
    if user_id in _profile_cache:
        ts, cached = _profile_cache[user_id]
        if now - ts < _CACHE_TTL:
            return cached

    profile: Dict[str, Any] = {"crystal_count": 0, "top_domains": [], "recent_crystals": [],
                                "session_count": 0, "active_quests": [], "active_missions": []}
    try:
        async with db_pool.acquire() as conn:
            uid = await conn.fetchval(
                "SELECT id FROM users WHERE username = $1", user_id)

            if uid:
                profile["crystal_count"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND superseded_by IS NULL", uid) or 0

                domains = await conn.fetch(
                    "SELECT domain, COUNT(*) as cnt FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND superseded_by IS NULL "
                    "GROUP BY domain ORDER BY cnt DESC LIMIT 5", uid)
                profile["top_domains"] = [r["domain"] for r in domains if r["domain"]]

                recent = await conn.fetch(
                    "SELECT crystal_text FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND superseded_by IS NULL "
                    "ORDER BY created_at DESC LIMIT 5", uid)
                profile["recent_crystals"] = [r["crystal_text"][:200] for r in recent if r["crystal_text"]]

            profile["session_count"] = await conn.fetchval(
                "SELECT COUNT(DISTINCT created_at::date) FROM conversation_history "
                "WHERE user_id = $1", user_id) or 0

            quests = await conn.fetch(
                "SELECT quest_id, goal, goal_domain FROM sse_quests "
                "WHERE user_id = $1 AND status = 'active'", user_id)
            profile["active_quests"] = [dict(q) for q in quests]

            missions = await conn.fetch(
                "SELECT mission_id, relationship_target, relationship_type FROM sse_missions "
                "WHERE user_id = $1 AND status = 'active'", user_id)
            profile["active_missions"] = [dict(m) for m in missions]
    except Exception as e:
        logger.warning("get_therapeutic_profile failed for %s: %s", user_id, e)

    _profile_cache[user_id] = (now, profile)
    return profile


async def check_biome_transition(user_id: str, profile: dict, journey: dict, db_pool) -> bool:
    """Check if therapeutic progress warrants a biome transition."""
    sessions = profile.get("session_count", 0)
    crystals = profile.get("crystal_count", 0)
    current = journey.get("current_biome", "dark_forest")

    target_biome = "dark_forest"
    for b in BIOME_THRESHOLDS:
        if sessions >= b["min_sessions"] and crystals >= b["min_crystals"]:
            target_biome = b["biome"]

    if target_biome == current:
        return False

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET current_biome = $1 WHERE user_id = $2",
                target_biome, user_id)
            await conn.execute(
                "INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail, metadata) "
                "VALUES ($1, 'biome_transition', 'Biome Transition', $2, $3)",
                user_id, f"{current} → {target_biome}",
                json.dumps({"old_biome": current, "new_biome": target_biome,
                            "sessions": sessions, "crystals": crystals}))
    except Exception as e:
        logger.warning("check_biome_transition update failed for %s: %s", user_id, e)
        return False
    return True


async def determine_character(profile: dict) -> Tuple[str, str]:
    """Map dominant crystal domains to core character manifestation."""
    for domain in profile.get("top_domains", []):
        key = domain.lower().strip()
        if key in CRYSTAL_TO_CHARACTER:
            return CRYSTAL_TO_CHARACTER[key]
    return _DEFAULT_CHARACTER


async def compose_journey_narrative(
    profile: dict, journey: dict, biome: dict, character: Tuple[str, str], db_pool
) -> dict:
    """Use LLM to compose a scene narrative. Falls back to template on failure."""
    import httpx

    char_name, grok_suffix = character
    biome_name = biome["biome"]
    biome_desc = biome["description"]
    crystal_summaries = "; ".join(profile.get("recent_crystals", [])[:3]) or "beginning their journey"
    quest_goal = profile["active_quests"][0]["goal"] if profile.get("active_quests") else "none"
    mission_target = profile["active_missions"][0]["relationship_target"] if profile.get("active_missions") else "none"
    arc = journey.get("therapeutic_arc", "exploration")

    fallback = {
        "narrative_text": f"In the {biome_name.replace('_', ' ')}, the {char_name} watches and waits. The path forward is becoming clearer.",
        "image_prompt": f"{biome_desc}, a solitary figure in the landscape, {grok_suffix}, painterly style, muted warm palette",
        "panel_tone": "meditative",
    }

    url = os.getenv("NATE_CHAT_URL", "")
    key = os.getenv("XAI_API_KEY", "") or os.getenv("NATE_CHAT_KEY", "")
    model = os.getenv("NATE_CHAT_MODEL", "grok-3-mini")
    if not url or not key:
        return fallback

    sys_prompt = (
        "You are a therapeutic narrative composer for the Sovereign Story Engine. "
        "Generate a short scene description (2-3 sentences) and a Grok Imagine image prompt "
        "for a user's daily story panel.\n\n"
        f"User's current biome: {biome_name} — {biome_desc}\n"
        f"Core character present: {char_name}\n"
        f"Recent therapeutic themes: {crystal_summaries}\n"
        f"Active quest: {quest_goal}\n"
        f"Active mission: {mission_target}\n"
        f"Therapeutic arc: {arc}\n\n"
        "The scene should:\n"
        "- Reflect where the user is therapeutically (not literally — metaphorically)\n"
        "- Include the core character manifestation naturally in the landscape\n"
        "- Feel like a chapter in an ongoing story, not a standalone image\n"
        "- Be hopeful without being dismissive of pain\n\n"
        "Return JSON only, no markdown:\n"
        '{"narrative_text": "2-3 sentence scene description the user reads", '
        '"image_prompt": "detailed Grok Imagine prompt, painterly style, muted warm palette", '
        '"panel_tone": "one of: meditative, action_sequence, threshold_pathway, restoration_sands, revelation"}'
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "max_tokens": 400, "temperature": 0.7,
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": "Generate today's journey panel."}]})
            raw = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                result = json.loads(m.group())
                result["image_prompt"] = result.get("image_prompt", fallback["image_prompt"])
                result["image_prompt"] += f", {grok_suffix}"
                result["image_prompt"] += ", no text, no words, no lettering, no calligraphy, no writing on image"
                result.setdefault("narrative_text", fallback["narrative_text"])
                result.setdefault("panel_tone", fallback["panel_tone"])
                return result
    except Exception as e:
        logger.warning("compose_journey_narrative LLM failed for journey, using fallback: %s", e)

    return fallback


async def generate_journey_panel(user_id: str, db_pool) -> dict:
    """Full pipeline: profile → biome → character → narrative → image → R2 → log."""
    from app.sse.infrastructure.grok_imagine_client import generate_image
    from app.sse.infrastructure.r2_storage import store_image

    journey = await get_or_create_journey(user_id, db_pool)
    profile = await get_therapeutic_profile(user_id, db_pool)
    await check_biome_transition(user_id, profile, journey, db_pool)

    journey_fresh = None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sse_user_journeys WHERE user_id = $1", user_id)
            if row:
                journey_fresh = dict(row)
    except Exception:
        pass
    if journey_fresh:
        journey = journey_fresh

    current_biome_name = journey.get("current_biome", "dark_forest")
    biome = next((b for b in BIOME_THRESHOLDS if b["biome"] == current_biome_name), BIOME_THRESHOLDS[0])
    character = await determine_character(profile)
    narrative = await compose_journey_narrative(profile, journey, biome, character, db_pool)

    image_bytes = await generate_image(narrative["image_prompt"])
    content_hash = hashlib.sha256(image_bytes).hexdigest()[:12]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r2_key = f"sse/journey/{user_id}/{today}/{content_hash}.png"
    r2_url = await store_image(image_bytes, r2_key)

    panel_id = str(uuid.uuid4())
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sse_panel_log "
                "(panel_id, user_id, panel_type, source_id, source_type, r2_url, prompt_used, "
                "biome, character_manifest, narrative_text, panel_tone, crystal_domains_used) "
                "VALUES ($1,$2,'journey',$3,'thera_world',$4,$5,$6,$7,$8,$9,$10::jsonb)",
                panel_id, user_id, journey.get("journey_id"), r2_url,
                narrative["image_prompt"][:500], current_biome_name, character[0],
                narrative["narrative_text"], narrative["panel_tone"],
                json.dumps(profile.get("top_domains", [])))
            await conn.execute(
                "UPDATE sse_user_journeys SET last_panel_at = NOW(), "
                "panels_generated = panels_generated + 1, dominant_character = $1 "
                "WHERE user_id = $2", character[0], user_id)
    except Exception as e:
        logger.warning("generate_journey_panel DB write failed for %s: %s", user_id, e)

    return {"panel_id": panel_id, "r2_url": r2_url, "biome": current_biome_name,
            "character": character[0], "narrative": narrative["narrative_text"],
            "panel_tone": narrative["panel_tone"]}


async def get_user_sse_status(user_id: str, db_pool) -> dict:
    """Full SSE status for admin monitor: journey + quests + missions + workbooks + panels."""
    status: Dict[str, Any] = {"user_id": user_id, "journey": None, "quests": [],
                               "missions": [], "workbooks": [], "recent_panels": []}
    try:
        async with db_pool.acquire() as conn:
            j = await conn.fetchrow("SELECT * FROM sse_user_journeys WHERE user_id = $1", user_id)
            if j:
                status["journey"] = dict(j)

            quests = await conn.fetch(
                "SELECT * FROM sse_quests WHERE user_id = $1 ORDER BY started_at DESC", user_id)
            status["quests"] = [dict(q) for q in quests]

            missions = await conn.fetch(
                "SELECT * FROM sse_missions WHERE user_id = $1 ORDER BY started_at DESC", user_id)
            status["missions"] = [dict(m) for m in missions]

            workbooks = await conn.fetch(
                "SELECT eu.storyboard_id, eu.status, eu.enrolled_at, "
                "ip.story_plot_json->>'title' AS storyboard_title "
                "FROM sse_enrolled_users eu "
                "LEFT JOIN sse_ip_provenance ip ON ip.story_plot_json->>'id' = eu.storyboard_id "
                "  AND ip.status = 'approved' "
                "WHERE eu.user_id = $1", user_id)
            status["workbooks"] = [dict(w) for w in workbooks]

            panels = await conn.fetch(
                "SELECT panel_id, panel_type, source_type, r2_url, biome, character_manifest, "
                "narrative_text, panel_tone, generated_at "
                "FROM sse_panel_log WHERE user_id = $1 ORDER BY generated_at DESC LIMIT 14", user_id)
            status["recent_panels"] = [dict(p) for p in panels]

            alerts = await conn.fetch(
                "SELECT alert_id, alert_type, title, detail, created_at, acknowledged "
                "FROM sse_admin_alerts WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10", user_id)
            status["alerts"] = [dict(a) for a in alerts]
    except Exception as e:
        logger.warning("get_user_sse_status failed for %s: %s", user_id, e)

    return status
