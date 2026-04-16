"""SSE Thera-World Engine — lifelong autonomous journey generation.

Generates daily journey panels for every active client using crystal memory,
biome progression, and character manifestation. Independent of workbook enrollment.

# ---------- Phase 6: Family Sanctuary Story Integration ----------
# TODO: Couples — shared relational story space. Partner NPCs appear as
#   distant figures in each other's panels (never named, always archetypal).
# TODO: Dependents — age-gated biomes (brighter, gentler imagery).
#   Simplified intake. Adult trauma themes MUST NOT leak into child panels.
# TODO: Family coherence — family-level story thread when multiple members
#   are active. Shared biome events (storms, seasons) sync across members.
# TODO: Relational crystal linking — crystals from family therapy sessions
#   create cross-member NPC appearances (e.g. "The Bridge Builder").
# -----------------------------------------------------------------
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
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1", user_id)

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

    cc = profile.get("crystal_count", 0)
    sc = profile.get("session_count", 0)
    if cc >= 50 and sc >= 10:
        profile["data_richness"] = "rich"
    elif cc >= 10 and sc >= 3:
        profile["data_richness"] = "moderate"
    elif cc >= 1 or sc >= 1:
        profile["data_richness"] = "thin"
    else:
        profile["data_richness"] = "empty"

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
    profile: dict, journey: dict, biome: dict, character: Tuple[str, str], db_pool,
    last_panel_summary: str = "", last_panel_npcs: list = None, panel_sequence: int = 0,
    user_id: str = "",
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
    richness = profile.get("data_richness", "moderate")

    # For empty/thin users, pull intake themes as narrative source material
    intake_themes = ""
    if richness in ("empty", "thin") and user_id:
        try:
            async with db_pool.acquire() as conn:
                conv_hist = await conn.fetchval(
                    "SELECT conversation_history FROM sse_identity_forge WHERE user_id = $1", user_id)
            if conv_hist:
                turns = json.loads(conv_hist) if isinstance(conv_hist, str) else conv_hist
                user_turns = [m["content"] for m in turns if m.get("role") == "user"]
                intake_themes = "; ".join(t[:80] for t in user_turns[2:8] if t)
        except Exception as _intake_err:
            logger.warning("TheraWorld: intake theme extraction failed: %s", _intake_err)

    fallback = {
        "narrative_text": f"In the {biome_name.replace('_', ' ')}, the {char_name} watches and waits. The path forward is becoming clearer.",
        "image_prompt": f"{biome_desc}, a solitary figure in the landscape, {grok_suffix}, painterly style, muted warm palette",
        "panel_tone": "meditative",
    }

    from app.sse.llm_fallback import chat_completion_with_fallback as _llm_fallback
    from app.services.nate_ai_config import NATE_CHAT_URL as _cfg_url, NATE_CHAT_KEY as _cfg_key, NATE_CHAT_MODEL as _cfg_model
    url = _cfg_url
    key = _cfg_key
    model = _cfg_model
    if not url or not key:
        return fallback

    richness_guidance = {
        "rich": f"Recent therapeutic themes: {crystal_summaries}\n",
        "moderate": f"Recent therapeutic themes: {crystal_summaries}\n",
        "thin": f"User's intake themes (limited crystal data): {intake_themes or crystal_summaries}\nFocus on biome atmosphere with hints from these themes.\n",
        "empty": f"User's intake themes: {intake_themes or 'just beginning'}\nFocus on pure biome atmosphere, character exploration, world-building.\n",
    }

    npc_names = ", ".join(n.get("name", "") for n in (last_panel_npcs or []) if n.get("name"))
    continuity_block = (
        f"Previous scene: {last_panel_summary or 'This is the opening scene.'}\n"
        f"NPCs present last time: {npc_names or 'none yet'}\n"
        f"This is panel {panel_sequence + 1} in the {biome_name} biome.\n"
        "Generate the NEXT scene that continues from where we left off.\n"
    )

    # Phase 6: family context enrichment
    family_block = ""
    family_ctx = profile.get("_family_context") or {}
    if family_ctx.get("heritage_landmarks"):
        lms = "; ".join(l.get("visual", "")[:60] for l in family_ctx["heritage_landmarks"][:3])
        family_block += f"Heritage landmarks visible in the landscape: {lms}\n"
    if family_ctx.get("couples_overlap"):
        overlap = family_ctx["couples_overlap"]
        if overlap.get("shared_domains"):
            family_block += f"A distant figure (spouse archetype) is visible, connected through shared themes: {', '.join(overlap['shared_domains'][:3])}\n"
        if family_ctx.get("coherence_trend"):
            prox = "closer" if family_ctx["coherence_trend"] > 0 else "further away"
            family_block += f"The distant figure appears {prox} today.\n"
    if family_ctx.get("family_storm"):
        family_block += "Storm clouds gather across the landscape — a shared family tension is present.\n"
    if family_ctx.get("family_crystals"):
        fc = family_ctx["family_crystals"]
        if fc.get("family_group"):
            family_block += f"Shared family wisdom echoes: {fc['family_group'][0].get('text','')[:80]}\n"
    try:
        from app.sse.ble_co_traveler import get_co_traveler_prompt_addition
        family_block += await get_co_traveler_prompt_addition(user_id, db_pool)
    except Exception:
        pass
    age_gate_block = ""
    if family_ctx.get("age_gated"):
        tier = family_ctx.get("age_tier", "child")
        if tier == "child":
            age_gate_block = ("CRITICAL: This is a CHILD user. Use bright, gentle, adventure-focused imagery. "
                              "NO trauma, darkness, wounds, shame, or adult themes. Think Studio Ghibli.\n")
        elif tier == "adolescent":
            age_gate_block = ("This is an ADOLESCENT user. Use coming-of-age themes. Mild challenge is okay. "
                              "No explicit trauma, abuse, or self-harm imagery.\n")

    sys_prompt = (
        "You are a therapeutic narrative composer for the Sovereign Story Engine. "
        "Generate a short scene description (2-3 sentences) and a Grok Imagine image prompt "
        "for a user's daily story panel.\n\n"
        f"{age_gate_block}"
        f"User's current biome: {biome_name} — {biome_desc}\n"
        f"Core character present: {char_name}\n"
        f"{richness_guidance.get(richness, richness_guidance['moderate'])}"
        f"Active quest: {quest_goal}\n"
        f"Active mission: {mission_target}\n"
        f"Therapeutic arc: {arc}\n"
        f"{family_block}"
        f"{continuity_block}\n"
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

    _msgs = [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "Generate today's journey panel."}]

    raw = await _llm_fallback(_msgs, max_tokens=400, temperature=0.7)
    if raw:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            result = json.loads(m.group())
            result["image_prompt"] = result.get("image_prompt", fallback["image_prompt"])
            result["image_prompt"] += f", {grok_suffix}"
            result["image_prompt"] += ", no text, no words, no lettering, no calligraphy, no writing on image"
            result.setdefault("narrative_text", fallback["narrative_text"])
            result.setdefault("panel_tone", fallback["panel_tone"])
            return result
        else:
            logger.warning("SSE narrative: LLM returned non-JSON for %s. raw[:200]=%s", user_id, raw[:200])
    return fallback


async def build_rich_panel_prompt(user_id: str, db_pool) -> dict:
    """Build the rich image prompt and narrative without generating the image.

    Returns {"image_prompt": str, "narrative_text": str, "panel_tone": str,
             "biome": str, "character": str} for callers that handle their
    own image generation, R2 storage, and logging (e.g. delivery_runtime).
    """
    journey = await get_or_create_journey(user_id, db_pool)
    profile = await get_therapeutic_profile(user_id, db_pool)
    await check_biome_transition(user_id, profile, journey, db_pool)

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sse_user_journeys WHERE user_id = $1", user_id)
            if row:
                journey = dict(row)
    except Exception:
        pass

    current_biome_name = journey.get("current_biome", "dark_forest")
    biome = next((b for b in BIOME_THRESHOLDS if b["biome"] == current_biome_name), BIOME_THRESHOLDS[0])
    character = await determine_character(profile)

    last_summary = journey.get("last_panel_summary", "") or ""
    last_npcs = journey.get("last_panel_npcs") or []
    if isinstance(last_npcs, str):
        last_npcs = json.loads(last_npcs)
    panel_seq = journey.get("panel_sequence", 0) or 0

    # Phase 6: family context enrichment
    try:
        from app.sse.family_engine import (
            get_family_for_user, check_age_gate, get_heritage_landmarks,
            get_couples_crystal_overlap, detect_family_cycles, get_family_session_crystals,
        )
        fam = await get_family_for_user(user_id, db_pool)
        age_info = await check_age_gate(user_id, db_pool)
        fctx: Dict[str, Any] = {"age_gated": age_info.get("age_gated"), "age_tier": age_info.get("age_tier")}
        if fam:
            fctx["heritage_landmarks"] = await get_heritage_landmarks(user_id, db_pool)
            fctx["family_crystals"] = await get_family_session_crystals(user_id, fam["family_id"], db_pool)
            spouses = [m for m in fam.get("members", []) if m.get("relationship") == "spouse"]
            if spouses:
                fctx["couples_overlap"] = await get_couples_crystal_overlap(user_id, spouses[0]["user_id"], db_pool)
                async with db_pool.acquire() as conn:
                    trend = await conn.fetchval(
                        "SELECT growth_pct FROM nevedal_metrics WHERE user_id = "
                        "(SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1) "
                        "ORDER BY recorded_at DESC LIMIT 1", user_id)
                fctx["coherence_trend"] = float(trend) if trend else 0
            storms = await detect_family_cycles(fam["family_id"], db_pool)
            if storms:
                fctx["family_storm"] = True
        if age_info.get("age_gated"):
            from app.sse.family_engine import _BRIGHT_BIOME_MAP
            bname = _BRIGHT_BIOME_MAP.get(current_biome_name, current_biome_name)
            biome = {"biome": bname, "description": biome.get("description", "").replace("fog", "mist").replace("shadow", "shade")}
        profile["_family_context"] = fctx
    except Exception as _fam_err:
        logger.warning("build_rich_panel_prompt family enrichment failed for %s: %s", user_id, _fam_err)

    narrative = await compose_journey_narrative(
        profile, journey, biome, character, db_pool,
        last_panel_summary=last_summary, last_panel_npcs=last_npcs,
        panel_sequence=panel_seq, user_id=user_id)

    image_prompt = narrative.get("image_prompt", "")
    if not image_prompt:
        image_prompt = f"{biome['description']}, a solitary figure, {character[1]}, painterly style"

    jmeta = journey.get("journey_metadata") or {}
    if isinstance(jmeta, str):
        jmeta = json.loads(jmeta)
    arch_hint = jmeta.get("archetype_hint", "")
    if arch_hint:
        image_prompt = image_prompt.replace("a solitary figure", f"a {arch_hint} figure, the protagonist")

    current_npcs: list = []
    try:
        for q in profile.get("active_quests", []):
            pn = q.get("progress_notes", [])
            if isinstance(pn, str):
                pn = json.loads(pn)
            if pn and pn[0].get("npcs"):
                current_npcs.extend(pn[0]["npcs"][:2])
        for m in profile.get("active_missions", []):
            pn = m.get("progress_notes", [])
            if isinstance(pn, str):
                pn = json.loads(pn)
            if pn and pn[0].get("npcs"):
                current_npcs.extend(pn[0]["npcs"][:1])
    except Exception:
        pass
    for npc in current_npcs[:3]:
        frag = npc.get("visual_prompt_fragment", "")
        if frag:
            image_prompt += f", {frag}"

    image_prompt += ", no text, no words, no lettering, no calligraphy, no writing on image"
    image_prompt += f", {character[1]}"

    return {
        "image_prompt": image_prompt,
        "narrative_text": narrative.get("narrative_text", ""),
        "panel_tone": narrative.get("panel_tone", "meditative"),
        "biome": current_biome_name,
        "character": character[0],
    }


async def generate_journey_panel(user_id: str, db_pool) -> dict:
    """Full pipeline: profile → biome → character → narrative → image → R2 → log."""
    from app.sse.infrastructure.grok_imagine_client import generate_image
    from app.sse.infrastructure.r2_storage import store_image

    # One panel per day maximum — quest/mission panels count too
    try:
        async with db_pool.acquire() as conn:
            today_exists = await conn.fetchval(
                "SELECT panel_id FROM sse_panel_log WHERE user_id = $1 AND generated_at::date = CURRENT_DATE", user_id)
            if today_exists:
                return {"skipped": True, "reason": "panel_exists_today", "panel_id": str(today_exists)}
    except Exception as _dup_err:
        logger.warning("generate_journey_panel dedup check failed: %s", _dup_err)

    journey = await get_or_create_journey(user_id, db_pool)
    profile = await get_therapeutic_profile(user_id, db_pool)
    transitioned = await check_biome_transition(user_id, profile, journey, db_pool)

    journey_fresh = None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sse_user_journeys WHERE user_id = $1", user_id)
            if row:
                journey_fresh = dict(row)
    except Exception as _jf_err:
        logger.warning("generate_journey_panel journey refresh failed: %s", _jf_err)
    if journey_fresh:
        journey = journey_fresh

    current_biome_name = journey.get("current_biome", "dark_forest")
    biome = next((b for b in BIOME_THRESHOLDS if b["biome"] == current_biome_name), BIOME_THRESHOLDS[0])
    character = await determine_character(profile)

    last_summary = journey.get("last_panel_summary", "") or ""
    last_npcs = journey.get("last_panel_npcs") or []
    if isinstance(last_npcs, str):
        last_npcs = json.loads(last_npcs)
    panel_seq = journey.get("panel_sequence", 0) or 0
    if transitioned:
        panel_seq = 0

    # Phase 6: enrich profile with family context
    try:
        from app.sse.family_engine import (
            get_family_for_user, check_age_gate, get_heritage_landmarks,
            get_couples_crystal_overlap, detect_family_cycles, get_family_session_crystals,
        )
        fam = await get_family_for_user(user_id, db_pool)
        age_info = await check_age_gate(user_id, db_pool)
        fctx: Dict[str, Any] = {"age_gated": age_info.get("age_gated"), "age_tier": age_info.get("age_tier")}
        if fam:
            fctx["heritage_landmarks"] = await get_heritage_landmarks(user_id, db_pool)
            fctx["family_crystals"] = await get_family_session_crystals(user_id, fam["family_id"], db_pool)
            spouses = [m for m in fam.get("members", []) if m.get("relationship") == "spouse"]
            if spouses:
                fctx["couples_overlap"] = await get_couples_crystal_overlap(user_id, spouses[0]["user_id"], db_pool)
                # Coherence trend for proximity
                async with db_pool.acquire() as conn:
                    trend = await conn.fetchval(
                        "SELECT growth_pct FROM nevedal_metrics WHERE user_id = "
                        "(SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1) "
                        "ORDER BY recorded_at DESC LIMIT 1", user_id)
                fctx["coherence_trend"] = float(trend) if trend else 0
            storms = await detect_family_cycles(fam["family_id"], db_pool)
            if storms:
                fctx["family_storm"] = True
        if age_info.get("age_gated"):
            from app.sse.family_engine import _BRIGHT_BIOME_MAP
            biome_name = _BRIGHT_BIOME_MAP.get(current_biome_name, current_biome_name)
            biome = {"biome": biome_name, "description": biome.get("description", "").replace("fog", "mist").replace("shadow", "shade")}
        profile["_family_context"] = fctx
    except Exception as _fam_err:
        logger.warning("Phase 6 family enrichment failed for %s: %s", user_id, _fam_err)

    narrative = await compose_journey_narrative(
        profile, journey, biome, character, db_pool,
        last_panel_summary=last_summary, last_panel_npcs=last_npcs,
        panel_sequence=panel_seq, user_id=user_id)

    image_prompt = narrative.get("image_prompt", "")
    if not image_prompt:
        image_prompt = f"{biome['description']}, a solitary figure, {character[1]}, painterly style"

    # Archetype protagonist reference
    jmeta = journey.get("journey_metadata") or {}
    if isinstance(jmeta, str):
        jmeta = json.loads(jmeta)
    arch_hint = jmeta.get("archetype_hint", "")
    if arch_hint:
        image_prompt = image_prompt.replace("a solitary figure", f"a {arch_hint} figure, the protagonist")

    # Blend active quest/mission NPCs into image
    current_npcs: list = []
    try:
        for q in profile.get("active_quests", []):
            pn = q.get("progress_notes", [])
            if isinstance(pn, str):
                pn = json.loads(pn)
            if pn and pn[0].get("npcs"):
                current_npcs.extend(pn[0]["npcs"][:2])
        for m in profile.get("active_missions", []):
            pn = m.get("progress_notes", [])
            if isinstance(pn, str):
                pn = json.loads(pn)
            if pn and pn[0].get("npcs"):
                current_npcs.extend(pn[0]["npcs"][:1])
    except Exception as _npc_err:
        logger.warning("NPC enrichment failed: %s", _npc_err)
    for npc in current_npcs[:3]:
        frag = npc.get("visual_prompt_fragment", "")
        if frag:
            image_prompt += f", {frag}"

    image_prompt += ", no text, no words, no lettering, no calligraphy, no writing on image"
    image_prompt += f", {character[1]}"

    archetype_ref_url = None
    try:
        async with db_pool.acquire() as conn:
            archetype_ref_url = await conn.fetchval(
                "SELECT archetype_image_url FROM sse_identity_forge WHERE user_id = $1",
                user_id)
    except Exception as _arc_err:
        logger.warning("Archetype ref lookup failed for %s: %s", user_id, _arc_err)

    r2_url = None
    try:
        image_bytes = await generate_image(image_prompt, source_image_url=archetype_ref_url)
        content_hash = hashlib.sha256(image_bytes).hexdigest()[:12]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r2_key = f"sse/journey/{user_id}/{today}/{content_hash}.png"
        r2_url = await store_image(image_bytes, r2_key)
    except Exception as e:
        logger.warning("Journey image generation failed for %s: %s", user_id, e)
        # Reserve panel fallback
        reserves = jmeta.get("reserve_prompts") or []
        if reserves:
            try:
                ib = await generate_image(reserves[0])
                ih = hashlib.md5(reserves[0].encode()).hexdigest()[:12]
                r2_url = await store_image(ib, f"sse/journey/{user_id}/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}/{ih}.png")
            except Exception as _retry_err:
                logger.warning("Journey image retry failed for %s: %s", user_id, _retry_err)

    nar_text = narrative.get("narrative_text", "")
    new_summary = (nar_text.split(".")[0] + ".") if nar_text and "." in nar_text else nar_text[:100]

    panel_id = str(uuid.uuid4())
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sse_panel_log "
                "(panel_id, user_id, panel_type, source_id, source_type, r2_url, prompt_used, "
                "biome, character_manifest, narrative_text, panel_tone, crystal_domains_used) "
                "VALUES ($1,$2,'journey',$3,'thera_world',$4,$5,$6,$7,$8,$9,$10::jsonb) "
                "ON CONFLICT DO NOTHING",
                panel_id, user_id, journey.get("journey_id"), r2_url,
                image_prompt[:500], current_biome_name, character[0],
                nar_text, narrative.get("panel_tone", "meditative"),
                json.dumps(profile.get("top_domains", [])))
            await conn.execute(
                "UPDATE sse_user_journeys SET last_panel_at = NOW(), "
                "panels_generated = panels_generated + 1, dominant_character = $1, "
                "last_panel_summary = $2, last_panel_npcs = $3::jsonb, panel_sequence = $4 "
                "WHERE user_id = $5",
                character[0], new_summary,
                json.dumps(current_npcs[:5]), panel_seq + 1, user_id)
            # Store reserve prompts after first successful panel
            if r2_url and (journey.get("panels_generated") or 0) == 0:
                r1 = f"{biome['description']}, {character[1]}, peaceful dawn, painterly style, muted warm palette, no text"
                r2 = f"{biome['description']}, {character[1]}, twilight path forward, painterly style, muted warm palette, no text"
                await conn.execute(
                    "UPDATE sse_user_journeys SET journey_metadata = "
                    "jsonb_set(COALESCE(journey_metadata, '{}'), '{reserve_prompts}', $1::jsonb) "
                    "WHERE user_id = $2", json.dumps([r1, r2]), user_id)
    except Exception as e:
        logger.warning("generate_journey_panel DB write failed for %s: %s", user_id, e)

    return {"panel_id": panel_id, "r2_url": r2_url, "biome": current_biome_name,
            "character": character[0], "narrative": nar_text,
            "panel_tone": narrative.get("panel_tone", "meditative"), "transitioned": transitioned}


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

            # Crystal health + coherence enrichment
            try:
                uid_row = await conn.fetchrow(
                    "SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1", user_id)
                if uid_row:
                    _uuid = uid_row["id"]
                    crystal_stats = await conn.fetchrow(
                        "SELECT count(*) as total, "
                        "count(*) FILTER (WHERE confidence >= 0.8) as locked_count "
                        "FROM nate_intelligence_crystals WHERE user_id=$1", _uuid)
                    top_domains = await conn.fetch(
                        "SELECT domain, count(*) as cnt FROM nate_intelligence_crystals "
                        "WHERE user_id=$1 AND domain IS NOT NULL GROUP BY domain ORDER BY cnt DESC LIMIT 5", _uuid)
                    old_count = await conn.fetchval(
                        "SELECT count(*) FROM nate_intelligence_crystals "
                        "WHERE user_id=$1 AND created_at < now() - interval '30 days'", _uuid)
                    total = crystal_stats["total"] if crystal_stats else 0
                    trend = "gaining" if total > (old_count or 0) * 1.1 else ("declining" if total < (old_count or 0) * 0.9 else "stable")
                    status["crystal_health"] = {
                        "total": total, "locked": crystal_stats["locked_count"] if crystal_stats else 0,
                        "top_domains": [{"domain": d["domain"], "count": d["cnt"]} for d in top_domains],
                        "growth_trend": trend}
                    coherence = await conn.fetchrow(
                        "SELECT c_emo, p_ent, t_tunnel FROM nevedal_metrics "
                        "WHERE user_id=$1 ORDER BY recorded_at DESC LIMIT 1", _uuid)
                    if coherence:
                        status["coherence"] = dict(coherence)
            except Exception as _coh_err:
                logger.warning("get_user_sse_status coherence query failed: %s", _coh_err)

            # Identity forge data
            try:
                forge = await conn.fetchrow(
                    "SELECT archetype_hint, archetype_image_url, character_visual "
                    "FROM sse_identity_forge WHERE user_id=$1 OR user_id=(SELECT hardware_id FROM users WHERE username=$1 LIMIT 1)", user_id)
                if forge:
                    status["forge"] = dict(forge)
            except Exception as _forge_err:
                logger.warning("get_user_sse_status forge query failed: %s", _forge_err)
    except Exception as e:
        logger.warning("get_user_sse_status failed for %s: %s", user_id, e)

    return status


async def generate_age_transition_panel(user_id: str, db_pool) -> dict:
    """Special panel for a minor turning 18 — age gate lifted, journey unlocked."""
    from app.sse.infrastructure.grok_imagine_client import generate_image
    from app.sse.infrastructure.r2_storage import store_image
    prompt = ("A young person standing at the threshold of a great open gate, golden light "
              "streaming through, the landscape beyond vast and full of possibility, "
              "painterly style, warm palette, coming of age, no text, no words")
    narrative = ("Today you step through the gate. The world beyond is no longer filtered "
                 "— it is yours, fully. This is your sovereign journey now.")
    r2_url = None
    try:
        img = await generate_image(prompt)
        r2_key = f"sse/journey/{user_id}/age_transition.png"
        r2_url = await store_image(img, r2_key)
    except Exception as e:
        logger.warning("Age transition image failed for %s: %s", user_id, e)
    panel_id = str(uuid.uuid4())
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sse_panel_log (panel_id, user_id, panel_type, r2_url, narrative_text, panel_tone) "
                "VALUES ($1,$2,'age_transition',$3,$4,'revelation')", panel_id, user_id, r2_url, narrative)
    except Exception as e:
        logger.warning("Age transition panel DB write failed: %s", e)
    return {"panel_id": panel_id, "r2_url": r2_url, "narrative": narrative}
