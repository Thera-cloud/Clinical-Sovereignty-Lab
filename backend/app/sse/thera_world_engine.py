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

# Each domain keeps a canonical Thera-World character but carries its own visual
# manifestation so two users (or two days) sharing a character still get distinct imagery.
CRYSTAL_TO_CHARACTER: Dict[str, Tuple[str, str]] = {
    "attachment": ("Mirror", "with two faint reflections in still water that drift apart and return to each other, suggesting bonds tested and held"),
    "love": ("Mirror", "with warm light catching a reflection in still water, two silhouettes mirrored close together"),
    "trust": ("Mirror", "with a rope bridge reflected in calm water below, each plank distinct, suggesting careful steps across"),
    "codependency": ("Mirror", "with intertwined vines reflected in water, one vine slowly turning toward its own patch of light"),
    "anxiety": ("Serpent", "with restless ripples disturbing the water's edge and a serpentine shadow circling the periphery, never striking"),
    "shame": ("Serpent", "with a subtle serpentine shadow at the edge of the frame, coiled but watchful"),
    "deception": ("Serpent", "with a forked path half-hidden in undergrowth, a serpentine shape woven through the branches above"),
    "anger": ("Serpent", "with heat shimmer rising off stone and a coiled serpentine silhouette backlit by ember light"),
    "fear": ("Serpent", "with long shadows stretching toward the figure and a watchful serpentine form at the treeline, distant"),
    "control": ("Serpent", "with hedges trimmed into rigid walls beginning to overgrow at the edges, a serpent shape tracing the straightest line"),
    "resentment": ("Serpent", "with old roots buckling a stone path and a serpentine shadow resting in the cracks"),
    "guilt": ("Pride/Shame", "with contrasting light and shadow splitting the scene, one side warm and one side cold"),
    "trauma": ("Pride/Shame", "with a fractured landscape knitting itself together at the seam where warm and cold light meet"),
    "perfectionism": ("Pride/Shame", "with one half of the scene immaculately ordered and the other half wild and alive, the figure standing at the boundary"),
    "identity": ("Reflection", "with a mirror or reflective surface showing a slightly different version of the subject"),
    "self-worth": ("Reflection", "with a polished stone surface reflecting the figure taller and steadier than they hold themselves"),
    "grief": ("Reflection", "with an empty bench beside still water, light falling gently on the space where someone once sat"),
    "loss": ("Reflection", "with a lantern left burning at the path's edge and a single set of footprints trailing into soft mist"),
    "abandonment": ("Reflection", "with a door left ajar in an empty doorframe standing alone in the field, warm light visible through the gap"),
    "boundaries": ("Reflection", "with a low stone wall under construction beside the path, each stone placed deliberately, a gate left open"),
    "rejection": ("Reflection", "with a window glimpsed from outside, and the figure's reflection in it looking back kindly"),
    "faith": ("Holy Spirit", "with gentle light streaming from an unseen source above, warm and golden"),
    "hope": ("Holy Spirit", "with a thin seam of dawn light widening along the horizon line, unmistakable against the dark"),
    "depression": ("Holy Spirit", "with a thin seam of golden light breaking through heavy gray cloud cover, distant but constant"),
    "spiritual": ("Holy Spirit", "with motes of golden light drifting upward like slow embers, gathering above the path"),
    "forgiveness": ("Holy Spirit", "with rain just ended, every surface washed and glistening, soft light pooling in the puddles"),
    "wonder": ("Curiosity", "with an open door or pathway visible in the background, inviting exploration"),
    "growth": ("Curiosity", "with new green shoots breaking through old stone, and a winding path climbing gently upward"),
    "discovery": ("Curiosity", "with a half-uncovered carving or artifact catching the light, brushes and tools resting nearby"),
    "loneliness": ("Curiosity", "with a distant campfire visible through the trees, smoke rising, the path toward it clear"),
    "vulnerability": ("Curiosity", "with a cloak set down on a stone and the figure standing lighter without it, the air mild"),
}

_DEFAULT_CHARACTER = ("Mirror", "with a faint reflection visible in still water nearby, suggesting hidden depth")

# Patent Section 7: recurring NPCs forged from crystal clusters. A domain with a
# meaningful cluster of crystals (>= _NPC_CLUSTER_MIN) manifests a persistent named
# companion who recurs across panels, giving relational patterns a face in the story.
_NPC_CLUSTER_MIN = 3
DOMAIN_TO_NPC: Dict[str, Dict[str, str]] = {
    "attachment": {"name": "The Weaver", "role": "weaves and mends the threads that connect", "visual_prompt_fragment": "a quiet weaver figure in the middle distance, threading luminous strands between trees"},
    "love": {"name": "The Hearthkeeper", "role": "tends the fire that warms without burning", "visual_prompt_fragment": "a hearthkeeper tending a small steady fire near the path, warm light on their hands"},
    "trust": {"name": "The Bridgewright", "role": "builds crossings one plank at a time", "visual_prompt_fragment": "a bridgewright testing each plank of a rope bridge, patient and unhurried"},
    "codependency": {"name": "The Gardener", "role": "teaches what grows best with room of its own", "visual_prompt_fragment": "a gardener gently separating intertwined vines, giving each its own trellis"},
    "anxiety": {"name": "The Stillwater Monk", "role": "shows how to let ripples settle", "visual_prompt_fragment": "a calm robed figure seated by the water's edge, the surface stilling around them"},
    "shame": {"name": "The Veiled Pilgrim", "role": "walks beside without judgment", "visual_prompt_fragment": "a gentle veiled pilgrim walking a few steps behind, head inclined kindly"},
    "deception": {"name": "The Cartographer", "role": "redraws maps until they tell the truth", "visual_prompt_fragment": "a cartographer at a field table, correcting an old map by lantern light"},
    "anger": {"name": "The Forgemaster", "role": "turns heat into something useful", "visual_prompt_fragment": "a forgemaster shaping glowing metal with measured strikes, sparks rising calm"},
    "fear": {"name": "The Torchbearer", "role": "carries light a few steps ahead", "visual_prompt_fragment": "a torchbearer holding steady flame at the edge of the dark, waiting without rushing"},
    "control": {"name": "The Falconer", "role": "practices the art of release and return", "visual_prompt_fragment": "a falconer with arm raised, bird lifting away free and circling back by choice"},
    "resentment": {"name": "The Root Tender", "role": "loosens what old roots have buckled", "visual_prompt_fragment": "a figure kneeling at a buckled stone path, patiently easing roots from the cracks"},
    "guilt": {"name": "The Scalekeeper", "role": "weighs what was carried too long", "visual_prompt_fragment": "a scalekeeper at a small stand of brass scales, setting heavy stones down one by one"},
    "trauma": {"name": "The Mender", "role": "stitches torn places with gold", "visual_prompt_fragment": "a mender repairing torn cloth with golden thread, the seams becoming the beauty"},
    "perfectionism": {"name": "The Stonecutter", "role": "leaves the rough edge that makes it real", "visual_prompt_fragment": "a stonecutter stepping back from nearly finished work, choosing to leave one wild edge"},
    "identity": {"name": "The Maskmaker", "role": "helps set down faces that no longer fit", "visual_prompt_fragment": "a maskmaker's stall with masks resting unworn, the craftsman offering an open hand"},
    "self-worth": {"name": "The Goldsmith", "role": "sees the worth beneath the tarnish", "visual_prompt_fragment": "a goldsmith polishing a small overlooked piece until it catches the light"},
    "grief": {"name": "The Lantern Keeper", "role": "keeps a light burning for what was loved", "visual_prompt_fragment": "an elderly lantern keeper tending a flame at the path's edge, unhurried and kind"},
    "loss": {"name": "The Ferryman", "role": "carries travelers across what cannot be walked", "visual_prompt_fragment": "a quiet ferryman waiting at the bank with a steady lantern on the prow"},
    "abandonment": {"name": "The Innkeeper", "role": "keeps a door that is never locked", "visual_prompt_fragment": "an innkeeper standing in a lit doorway, a place kept ready at the table inside"},
    "boundaries": {"name": "The Wallwright", "role": "builds walls with gates in them", "visual_prompt_fragment": "a wallwright placing stones deliberately, leaving a generous open gate"},
    "rejection": {"name": "The Gatekeeper", "role": "knows which doors were never the right ones", "visual_prompt_fragment": "a kind gatekeeper closing one door while gesturing toward an open road"},
    "faith": {"name": "The Pilgrim Elder", "role": "walks the long road with certainty of step", "visual_prompt_fragment": "an elder pilgrim with a worn staff, walking steadily toward distant light"},
    "hope": {"name": "The Dawnsinger", "role": "calls the first light over the ridge", "visual_prompt_fragment": "a distant figure on a ridge facing the first seam of dawn, arms loose and open"},
    "depression": {"name": "The Ember Carrier", "role": "keeps one coal alive through the gray", "visual_prompt_fragment": "a cloaked figure cupping a single glowing ember, sheltering it against the wind"},
    "spiritual": {"name": "The Star Reader", "role": "finds direction in what is above", "visual_prompt_fragment": "a star reader with an upturned face, charting by points of light overhead"},
    "forgiveness": {"name": "The Rainmaker", "role": "brings the rain that washes the road", "visual_prompt_fragment": "a rainmaker standing in just-ended rain, every surface washed and glistening"},
    "wonder": {"name": "The Wandering Scholar", "role": "asks the questions that open doors", "visual_prompt_fragment": "a wandering scholar pausing at a half-open door, journal in hand, delighted"},
    "growth": {"name": "The Orchard Keeper", "role": "tends what takes seasons to bear fruit", "visual_prompt_fragment": "an orchard keeper pruning young trees on a gentle slope, new shoots everywhere"},
    "discovery": {"name": "The Archivist", "role": "uncovers what was always there", "visual_prompt_fragment": "an archivist brushing earth from a half-uncovered carving, tools laid out neatly"},
    "loneliness": {"name": "The Fire Tender", "role": "keeps a camp where company is welcome", "visual_prompt_fragment": "a fire tender feeding a campfire visible through the trees, a second seat left open"},
    "vulnerability": {"name": "The Cloakless Traveler", "role": "walks lighter for what was set down", "visual_prompt_fragment": "a traveler walking without their cloak, garment folded on a stone behind them, air mild"},
}

# Therapeutic themes are mined from crystal TEXT because the crystal `domain`
# column only holds the 7 canonical domains (clinical, coaching, marketing...).
# The themes that drive character/NPC manifestation live in the crystal language.
_THEME_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "attachment": ("attachment", "clinging", "pursue-withdraw", "pursuer", "withdraw"),
    "love": ("love", "loving", "affection", "intimacy"),
    "trust": ("trust", "distrust", "betray"),
    "codependency": ("codependen", "enmesh"),
    "anxiety": ("anxiety", "anxious", "worry", "panic", "overwhelm"),
    "shame": ("shame", "ashamed", "humiliat", "worthless"),
    "deception": ("deceiv", "deception", "dishonest", "gaslight", "lying"),
    "anger": ("anger", "angry", "rage", "furious"),
    "fear": ("fear", "afraid", "scared", "terrified"),
    "control": ("control", "controlling", "micromanag"),
    "resentment": ("resent", "bitter"),
    "guilt": ("guilt", "guilty", "regret"),
    "trauma": ("trauma", "ptsd", "flashback", "triggered"),
    "perfectionism": ("perfection", "never good enough", "high standard"),
    "identity": ("identity", "who i am", "true self", "authentic self"),
    "self-worth": ("self-worth", "self worth", "self-esteem", "not enough", "unworthy"),
    "grief": ("grief", "grieving", "mourn"),
    "loss": ("loss", "lost someone", "passed away", "death of"),
    "abandonment": ("abandon", "left me", "walked out"),
    "boundaries": ("boundar", "say no", "people-pleas", "people pleas"),
    "rejection": ("reject", "excluded", "unwanted"),
    "faith": ("faith", "god", "prayer", "spiritual practice"),
    "hope": ("hope", "hopeful", "optimis"),
    "depression": ("depress", "hopeless", "numb", "empty inside"),
    "spiritual": ("spiritual", "soul", "sacred", "divine"),
    "forgiveness": ("forgiv",),
    "wonder": ("wonder", "curious", "curiosity", "awe"),
    "growth": ("growth", "growing", "progress", "breakthrough", "healing"),
    "discovery": ("discover", "insight", "realiz", "uncover"),
    "loneliness": ("lonel", "isolat", "alone"),
    "vulnerability": ("vulnerab", "opening up", "letting in"),
}


def _mine_themes_from_texts(texts: List[str]) -> Dict[str, int]:
    """Count therapeutic theme occurrences across crystal texts (substring stems)."""
    counts: Dict[str, int] = {}
    for raw in texts:
        t = (raw or "").lower()
        if not t:
            continue
        for theme, stems in _THEME_KEYWORDS.items():
            if any(s in t for s in stems):
                counts[theme] = counts.get(theme, 0) + 1
    return counts


# Patent FIG. 39: archetype visual evolution stages — the protagonist's reference
# image is regenerated at each biome transition so the character visibly transforms.
_BIOME_ARCHETYPE_STAGE: Dict[str, Tuple[str, str]] = {
    "dark_forest": ("early", "guarded and weathered, wrapped in a worn travel cloak, carrying a dim lantern, face half in shadow but eyes alert"),
    "fortress_plains": ("early-mid", "standing straighter, cloak mended and shoulders squared, a watchful steadiness replacing fear"),
    "river_valley": ("mid", "armor and heavy layers loosened and partly set aside, posture open, color returning to their garments, light on their face"),
    "crystal_mountains": ("late-mid", "carrying soft crystalline light in their hands, old scars visible but worn without shame, expression settled"),
    "open_sky": ("late", "unburdened and radiant, cloak flowing free, standing tall under open light, fully themselves"),
}

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


async def _enrich_profile_coaching_calibration(profile: dict, user_id: str, db_pool) -> None:
    """Attach Coach-Story Bridge calibration for Thera-World narrative (additive)."""
    if not db_pool:
        profile["_coaching_calibration"] = {"has_coach": False, "overrides": {}}
        return
    try:
        from app.sse.adapters.coach_story_bridge import CoachStoryBridge

        bridge = CoachStoryBridge(db_pool)
        profile["_coaching_calibration"] = await bridge.get_coaching_calibration(user_id)
    except Exception as e:
        logger.warning("TheraWorld: coaching calibration failed for %s: %s", user_id, e)
        profile["_coaching_calibration"] = {"has_coach": False, "overrides": {}}


async def _enrich_profile_assessment_calibration(profile: dict, user_id: str, db_pool) -> None:
    """Attach Assessment Bridge calibration for Thera-World narrative (additive)."""
    if not db_pool:
        profile["_assessment_calibration"] = {"has_assessments": False}
        return
    try:
        from app.sse.adapters.assessment_bridge import AssessmentBridge

        ab = AssessmentBridge(db_pool)
        profile["_assessment_calibration"] = await ab.get_assessment_calibration(user_id)
    except Exception as e:
        logger.warning("TheraWorld: assessment calibration failed for %s: %s", user_id, e)
        profile["_assessment_calibration"] = {"has_assessments": False}


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
                                "domain_counts": {}, "theme_counts": {}, "top_themes": [],
                                "session_count": 0,
                                "active_quests": [], "active_missions": []}
    try:
        async with db_pool.acquire() as conn:
            urow = await conn.fetchrow(
                "SELECT id, username, hardware_id FROM users "
                "WHERE hardware_id = $1 OR username = $1 LIMIT 1", user_id)
            uid = urow["id"] if urow else None

            if uid:
                profile["crystal_count"] = await conn.fetchval(
                    "SELECT COUNT(*) FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND superseded_by IS NULL", uid) or 0

                domains = await conn.fetch(
                    "SELECT domain, COUNT(*) as cnt FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND superseded_by IS NULL "
                    "GROUP BY domain ORDER BY cnt DESC LIMIT 5", uid)
                profile["top_domains"] = [r["domain"] for r in domains if r["domain"]]
                profile["domain_counts"] = {r["domain"]: r["cnt"] for r in domains if r["domain"]}

                recent = await conn.fetch(
                    "SELECT crystal_text FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND superseded_by IS NULL "
                    "ORDER BY created_at DESC LIMIT 5", uid)
                profile["recent_crystals"] = [r["crystal_text"][:200] for r in recent if r["crystal_text"]]

                # Mine therapeutic THEMES from crystal text — the domain column only
                # holds canonical domains (clinical/coaching/...), but character and
                # NPC manifestation are keyed by themes (shame, grief, attachment...).
                theme_rows = await conn.fetch(
                    "SELECT crystal_text FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND superseded_by IS NULL "
                    "ORDER BY created_at DESC LIMIT 150", uid)
                theme_counts = _mine_themes_from_texts(
                    [r["crystal_text"] for r in theme_rows if r["crystal_text"]])
                profile["theme_counts"] = theme_counts
                profile["top_themes"] = [t for t, _ in sorted(
                    theme_counts.items(), key=lambda kv: kv[1], reverse=True)[:6]]

            # conversation_history.user_id stores usernames for voice/chat sessions,
            # but callers pass hardware_id — match on every known identifier.
            _idents = [user_id]
            if urow:
                for _k in ("username", "hardware_id"):
                    _v = urow[_k]
                    if _v and _v not in _idents:
                        _idents.append(_v)
            profile["session_count"] = await conn.fetchval(
                "SELECT COUNT(DISTINCT created_at::date) FROM conversation_history "
                "WHERE user_id = ANY($1::text[])", _idents) or 0

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


async def determine_character(profile: dict, panel_sequence: int = 0) -> Tuple[str, str]:
    """Map dominant crystal domains to core character manifestation.

    Rotates through ALL matched domains by panel_sequence so a user whose
    top domain never changes still sees different manifestations day to day.
    """
    matches: List[Tuple[str, str]] = []
    # Themes mined from crystal text are the primary key; canonical domains fallback
    for key_src in (profile.get("top_themes", []), profile.get("top_domains", [])):
        for domain in key_src:
            key = domain.lower().strip()
            if key in CRYSTAL_TO_CHARACTER and CRYSTAL_TO_CHARACTER[key] not in matches:
                matches.append(CRYSTAL_TO_CHARACTER[key])
    if not matches:
        return _DEFAULT_CHARACTER
    return matches[panel_sequence % len(matches)]


async def _get_archetype_identity(user_id: str, journey: dict, db_pool) -> Dict[str, str]:
    """Resolve the user's archetype (hint + visual + ref image) for narrative/image use.

    Prefers journey_metadata; falls back to sse_identity_forge (with username
    fallback) and backfills journey_metadata so future panels skip the lookup.
    """
    jmeta = journey.get("journey_metadata") or {}
    if isinstance(jmeta, str):
        try:
            jmeta = json.loads(jmeta)
        except Exception:
            jmeta = {}
    ident = {
        "archetype_hint": jmeta.get("archetype_hint") or "",
        "character_visual": jmeta.get("character_visual") or "",
        "archetype_image_url": jmeta.get("archetype_image_url") or "",
    }
    if ident["archetype_hint"] and ident["character_visual"]:
        return ident
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT archetype_hint, character_visual, archetype_image_url "
                "FROM sse_identity_forge WHERE user_id = $1 "
                "OR user_id = (SELECT hardware_id FROM users WHERE username = $1 LIMIT 1) "
                "OR user_id = (SELECT username FROM users WHERE hardware_id = $1 LIMIT 1) "
                "LIMIT 1", user_id)
            if row:
                ident["archetype_hint"] = ident["archetype_hint"] or (row["archetype_hint"] or "")
                ident["character_visual"] = ident["character_visual"] or (row["character_visual"] or "")
                ident["archetype_image_url"] = ident["archetype_image_url"] or (row["archetype_image_url"] or "")
                if ident["archetype_hint"] or ident["character_visual"]:
                    await conn.execute(
                        "UPDATE sse_user_journeys SET journey_metadata = "
                        "COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb WHERE user_id = $2",
                        json.dumps({k: v for k, v in ident.items() if v}), user_id)
    except Exception as e:
        logger.warning("TheraWorld: archetype identity lookup failed for %s: %s", user_id, e)
    return ident


async def _fetch_deep_crystal_context(user_id: str, profile: dict, db_pool) -> str:
    """PATENT FIG.37 — Crystal Bridge deep recall (vector + reinforcement path).

    Goes beyond the 5 most recent crystals: semantic recall over the user's FULL
    crystal history, seeded with the day's dominant therapeutic themes. Uses
    recall_crystals_for_context so recalled crystals get reinforcement
    (recall_count / last_recalled_at / confidence nudge) instead of silently decaying.
    """
    if profile.get("data_richness") in ("empty", "thin"):
        return ""
    try:
        from app.websocket.crystal_recall_bridge import recall_crystals_for_context as _recall
    except ImportError:
        return ""
    try:
        query_text = " ".join(profile.get("top_themes", [])[:3] or profile.get("top_domains", [])[:3])
        ctx = await _recall(db_pool, user_id, max_results=6,
                            source="sse_journey", query_text=query_text)
        return (ctx or "")[:1500]
    except Exception as e:
        logger.warning("TheraWorld: deep crystal recall failed for %s: %s", user_id, e)
        return ""


_CHAPTER_SUMMARY_REFRESH_DAYS = 7
_CHAPTER_SUMMARY_MIN_PANELS = 5


async def _get_chapter_summary(user_id: str, journey: dict, profile: dict, db_pool) -> str:
    """Rolling long-arc 'chapter summary' stored in journey_metadata (refreshed weekly).

    Gives the narrative composer true long-term memory of the user's whole story
    arc instead of only yesterday's one-sentence summary.
    """
    jmeta = journey.get("journey_metadata") or {}
    if isinstance(jmeta, str):
        try:
            jmeta = json.loads(jmeta)
        except Exception:
            jmeta = {}
    existing = jmeta.get("chapter_summary") or ""
    stamp = jmeta.get("chapter_summary_at") or ""
    if existing and stamp:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
            if age.days < _CHAPTER_SUMMARY_REFRESH_DAYS:
                return existing
        except Exception:
            pass

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT narrative_text, biome, character_manifest FROM sse_panel_log "
                "WHERE user_id = $1 AND narrative_text IS NOT NULL AND btrim(narrative_text) <> '' "
                "ORDER BY generated_at DESC LIMIT 14", user_id)
    except Exception as e:
        logger.warning("TheraWorld: chapter summary panel fetch failed for %s: %s", user_id, e)
        return existing

    if len(rows) < _CHAPTER_SUMMARY_MIN_PANELS:
        return existing

    panels_text = "\n".join(
        f"- [{r['biome'] or '?'}/{r['character_manifest'] or '?'}] {r['narrative_text'][:180]}"
        for r in reversed(rows))
    domains = ", ".join(profile.get("top_domains", [])[:5]) or "unknown"
    try:
        from app.sse.llm_fallback import chat_completion_with_fallback as _llm
        raw = await _llm([
            {"role": "system", "content": (
                "You summarize a therapeutic story journey. Given the last 14 daily story panels "
                "(oldest first) and the traveler's dominant therapeutic themes, write a 3-4 sentence "
                "'story so far' chapter summary in second person ('you'). Capture the ARC: where the "
                "journey began, what has shifted, what remains unresolved, and what the story is moving "
                "toward. No preamble, no markdown — just the summary sentences.")},
            {"role": "user", "content": f"Dominant themes: {domains}\n\nRecent panels:\n{panels_text}"},
        ], max_tokens=220, temperature=0.5)
    except Exception as e:
        logger.warning("TheraWorld: chapter summary LLM failed for %s: %s", user_id, e)
        return existing

    summary = (raw or "").strip()
    if not summary:
        return existing
    summary = summary[:900]
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = "
                "COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb WHERE user_id = $2",
                json.dumps({"chapter_summary": summary,
                            "chapter_summary_at": datetime.now(timezone.utc).isoformat()}),
                user_id)
    except Exception as e:
        logger.warning("TheraWorld: chapter summary persist failed for %s: %s", user_id, e)
    return summary


async def _evolve_archetype_stage(user_id: str, new_biome: str, arch_ident: dict, db_pool) -> Optional[str]:
    """PATENT FIG.39 — regenerate the archetype reference image at a biome transition.

    The protagonist visibly transforms (early → mid → late stages) as the client
    progresses. Uses i2i from the current reference for visual continuity; the new
    stage image becomes the i2i reference for all subsequent daily panels.
    """
    stage, stage_desc = _BIOME_ARCHETYPE_STAGE.get(new_biome, ("mid", ""))
    jm = arch_ident or {}
    base_url = jm.get("archetype_image_url") or None
    visual = (jm.get("character_visual") or "").strip()
    hint = (jm.get("archetype_hint") or "").strip()
    if not (visual or hint or base_url):
        return None  # nothing to evolve — no forged archetype yet
    try:
        from app.sse.infrastructure.grok_imagine_client import generate_image
        from app.sse.infrastructure.r2_storage import store_image

        subject = visual[:200] if visual else (f"a {hint} archetype character" if hint else "the journeying protagonist")
        prompt = (
            f"Character portrait of {subject}, now {stage_desc}, "
            "same person as the reference but visibly evolved, full figure, centered, "
            "painterly style, muted warm palette, soft atmospheric background, "
            "no text, no words, no lettering, no writing on image")
        image_bytes = await generate_image(prompt, source_image_url=base_url)
        content_hash = hashlib.sha256(image_bytes).hexdigest()[:12]
        r2_key = f"sse/archetype/{user_id}/{new_biome}_{content_hash}.png"
        new_url = await store_image(image_bytes, r2_key)
        if not new_url:
            return None
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = "
                "COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb WHERE user_id = $2",
                json.dumps({"archetype_image_url": new_url, "archetype_stage": stage,
                            "archetype_stage_biome": new_biome}), user_id)
            await conn.execute(
                "INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail, metadata) "
                "VALUES ($1, 'archetype_evolution', 'Archetype Evolved', $2, $3)",
                user_id, f"Archetype advanced to {stage} stage ({new_biome})",
                json.dumps({"stage": stage, "biome": new_biome, "image_url": new_url}))
        logger.info("TheraWorld: archetype evolved to %s stage for %s (%s)", stage, user_id, new_biome)
        return new_url
    except Exception as e:
        logger.warning("TheraWorld: archetype stage evolution failed for %s: %s", user_id, e)
        return None


async def _derive_crystal_npcs(user_id: str, profile: dict, journey: dict, db_pool,
                               panel_sequence: int = 0, max_npcs: int = 2) -> List[dict]:
    """PATENT Section 7 — forge recurring NPCs from crystal domain clusters.

    Domains with >= _NPC_CLUSTER_MIN crystals manifest persistent named companions.
    The registry lives in journey_metadata.npc_registry so the same NPC recurs across
    panels (continuity), rotated by panel_sequence for day-to-day variety.
    """
    # Themes mined from crystal text are the cluster source (domain column only
    # holds canonical domains); domain_counts kept as fallback for legacy data.
    counts: Dict[str, int] = dict(profile.get("theme_counts") or {})
    for d, c in (profile.get("domain_counts") or {}).items():
        counts.setdefault(d, c)
    eligible = [t for t, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                if c >= _NPC_CLUSTER_MIN and t.lower().strip() in DOMAIN_TO_NPC][:6]
    if not eligible:
        return []

    jmeta = journey.get("journey_metadata") or {}
    if isinstance(jmeta, str):
        try:
            jmeta = json.loads(jmeta)
        except Exception:
            jmeta = {}
    registry: Dict[str, dict] = jmeta.get("npc_registry") or {}

    changed = False
    for domain in eligible:
        key = domain.lower().strip()
        if key not in registry:
            npc = dict(DOMAIN_TO_NPC[key])
            npc["domain"] = key
            npc["appearances"] = 0
            registry[key] = npc
            changed = True

    # Rotate which registry NPCs appear today so companions take turns
    ordered = [registry[d.lower().strip()] for d in eligible if d.lower().strip() in registry]
    if not ordered:
        return []
    start = panel_sequence % len(ordered)
    todays = [ordered[(start + i) % len(ordered)] for i in range(min(max_npcs, len(ordered)))]
    for npc in todays:
        npc["appearances"] = int(npc.get("appearances", 0)) + 1
        changed = True

    if changed:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE sse_user_journeys SET journey_metadata = "
                    "COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb WHERE user_id = $2",
                    json.dumps({"npc_registry": registry}), user_id)
        except Exception as e:
            logger.warning("TheraWorld: NPC registry persist failed for %s: %s", user_id, e)
    return todays


async def _fetch_recent_delivery_narratives(user_id: str, db_pool) -> List[str]:  # FIX-NARRATIVE-DIVERSITY
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT client_narrative_text FROM sse_delivery_generation_log WHERE user_id=$1 "
                "AND client_narrative_text IS NOT NULL AND btrim(client_narrative_text)<>'' "
                "AND generated_at > NOW() - INTERVAL '14 days' ORDER BY generated_at DESC LIMIT 7",
                user_id)
            return [r["client_narrative_text"] for r in rows]
    except Exception as e:
        logger.warning("TheraWorld: recent narratives fetch failed %s: %s", user_id, e)
        return []


async def compose_journey_narrative(
    profile: dict, journey: dict, biome: dict, character: Tuple[str, str], db_pool,
    last_panel_summary: str = "", last_panel_npcs: list = None, panel_sequence: int = 0,
    user_id: str = "", recent_narratives: Optional[List[str]] = None,
    archetype_hint: str = "", character_visual: str = "",
    deep_crystal_context: str = "", chapter_summary: str = "",
    todays_npcs: Optional[List[dict]] = None,
) -> dict:
    """Use LLM to compose a scene narrative. Falls back to template on failure."""
    import httpx

    char_name, grok_suffix = character
    rr = recent_narratives or []  # FIX-NARRATIVE-DIVERSITY
    anti_repeat = ""
    if rr:
        lst = "\n".join((f"- {t[:200]}..." if len(t) > 200 else f"- {t}") for t in rr)
        anti_repeat = (
            "RECENT NARRATIVES (last 7 panels — do NOT repeat themes or phrases):\n" + lst + "\n\n"
            "Your new narrative MUST:\n"
            "- NOT repeat metaphors, imagery, or phrases from above\n"
            "- NOT restate the same insight or theme\n"
            "- Approach the moment from a different angle\n"
            "- If the client is in a similar emotional space as recent days, find a "
            "different lens, sensation, or detail to reflect on\n\n")
        print(f">>> [ANTI-REPEAT] user={user_id} recent_count={len(rr)} chars_in_context={len(anti_repeat)}")
    biome_name = biome["biome"]
    biome_desc = biome["description"]
    crystal_summaries = "; ".join(profile.get("recent_crystals", [])[:3]) or "beginning their journey"
    quest_goal = profile["active_quests"][0]["goal"] if profile.get("active_quests") else "none"
    mission_target = profile["active_missions"][0]["relationship_target"] if profile.get("active_missions") else "none"
    quest_goal_eff = quest_goal
    mission_target_eff = mission_target
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

    # Archetype protagonist block — the user's own character leads the story
    protagonist_block = ""
    _protag_desc = ""
    if archetype_hint or character_visual:
        _protag_desc = f"a {archetype_hint or 'journeying'} archetype"
        if character_visual:
            _protag_desc += f" — {character_visual[:200]}"
        protagonist_block = (
            f"THE PROTAGONIST (the user's own forged character): {_protag_desc}.\n"
            "The protagonist is the central figure of every scene — this is THEIR adventure. "
            "Write narrative_text in a way that places the protagonist in the scene (second person 'you' "
            "addressing them as this character), and the image_prompt MUST describe the protagonist "
            "as the main figure using the visual description above, not a generic solitary figure.\n"
        )

    fallback = {
        "narrative_text": f"In the {biome_name.replace('_', ' ')}, the {char_name} watches and waits. The path forward is becoming clearer.",
        "image_prompt": f"{biome_desc}, {_protag_desc or 'a solitary figure'} in the landscape, {grok_suffix}, painterly style, muted warm palette",
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

    # FIX #4: long-arc chapter summary — the story remembers where it has been
    chapter_block = ""
    if chapter_summary:
        chapter_block = (
            f"THE STORY SO FAR (chapter summary of the journey to date): {chapter_summary}\n"
            "Today's scene is the next beat in this larger arc — let it build on what came "
            "before rather than restarting.\n"
        )

    # FIX #4: deep crystal recall — themes from the user's full history, not just last 5
    deep_crystal_block = ""
    if deep_crystal_context:
        deep_crystal_block = (
            "DEEPER MEMORY (themes recalled from the user's full therapeutic history):\n"
            f"{deep_crystal_context[:900]}\n"
            "Weave one of these older threads into today's scene as a returning echo or motif.\n"
        )

    # FIX #6: recurring NPC companions forged from crystal clusters
    npc_block = ""
    if todays_npcs:
        npc_lines = "\n".join(
            f"- {n['name']} ({n['role']}): {n['visual_prompt_fragment']}"
            for n in todays_npcs if n.get("name")
        )
        npc_block = (
            "RECURRING COMPANIONS (these named figures travel with the protagonist and MUST "
            "appear in both narrative_text and image_prompt today):\n"
            f"{npc_lines}\n"
            "Refer to them by name in the narrative. They are familiar presences, not strangers.\n"
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

    cal = profile.get("_coaching_calibration") or {}
    coach_block = ""
    panel_tone_hold_hint = ""
    if cal.get("has_coach"):
        rn = cal.get("recent_notes") or []
        snippets = "; ".join(
            (n.get("text") or "")[:120] for n in rn[:3] if (n.get("text") or "").strip()
        )
        if snippets:
            coach_block += f"Coach clinical notes (recent): {snippets}\n"
        focus = cal.get("coach_recommended_focus")
        if focus:
            coach_block += (
                f"COACH PRIORITY DOMAIN: {focus} — weight narrative and imagery toward this therapeutic theme.\n"
            )
        pacing = (cal.get("coach_pacing_override") or "normal") or "normal"
        if pacing == "slow":
            coach_block += (
                "COACH PACING: slow — soften urgency; no high-intensity action; contemplative, gradual unfolding.\n"
            )
        elif pacing == "fast":
            coach_block += (
                "COACH PACING: fast — allow clearer forward motion and momentum in the landscape (still therapeutic).\n"
            )
        if cal.get("coach_hold_active"):
            coach_block += (
                "CLINICAL HOLD (coach): Visual and narrative \"rest\" or soft fog — stillness, safety, no calls to "
                "action. Do not frame quests, missions, or heroic tasks. Prefer gentle presence and recovery.\n"
            )
            quest_goal_eff = "none (clinical hold — no action-oriented missions)"
            mission_target_eff = "none (clinical hold)"
            panel_tone_hold_hint = (
                " Clinical hold is ON: choose panel_tone meditative or restoration_sands only — not action_sequence.\n"
            )

    as_cal = profile.get("_assessment_calibration") or {}
    assessment_block = ""
    if as_cal.get("has_assessments"):
        dp = as_cal.get("domain_priorities") or []
        rq = as_cal.get("recommended_quest_types") or []
        risks = as_cal.get("risk_areas") or []
        if dp:
            assessment_block += (
                f"ASSESSMENT DOMAIN PRIORITIES (weight narrative toward these metaphors): {', '.join(dp)}.\n"
            )
        if rq:
            assessment_block += (
                f"Preferred quest / mission thematic keywords for this user: {', '.join(rq)}. "
                "When referencing growth tasks, favor these tones over generic challenge.\n"
            )
        if risks:
            avoid = []
            if "acute_anxiety" in risks or "acute_shame" in risks:
                avoid.append("intense threat, humiliation, or harsh judgment imagery")
            if "severe_low_mood" in risks:
                avoid.append("hopeless void or isolation without warmth or presence")
            if "attachment_distress" in risks:
                avoid.append("abandonment, rejection, or being left behind as the emotional punchline")
            if "safety_concern_language" in risks:
                avoid.append("any imagery of self-harm, suicide, or lethal hopelessness")
            if avoid:
                assessment_block += (
                    "ASSESSMENT RISK FLAGS — soften or omit triggers: "
                    + "; ".join(avoid)
                    + ". Keep the scene containing, paced, and non-activating.\n"
                )
        if "acute_anxiety" in risks and not cal.get("coach_hold_active"):
            panel_tone_hold_hint += (
                " Assessment suggests high anxiety: prefer meditative or restoration_sands over action_sequence.\n"
            )

    sys_prompt = (
        "You are a therapeutic narrative composer for the Sovereign Story Engine. "
        "Generate a short scene description (2-3 sentences) and a Grok Imagine image prompt "
        "for a user's daily story panel.\n\n"
        f"{age_gate_block}"
        f"{protagonist_block}"
        f"User's current biome: {biome_name} — {biome_desc}\n"
        f"Core character present: {char_name}\n"
        f"{richness_guidance.get(richness, richness_guidance['moderate'])}"
        f"{coach_block}"
        f"{assessment_block}"
        f"Active quest: {quest_goal_eff}\n"
        f"Active mission: {mission_target_eff}\n"
        f"Therapeutic arc: {arc}\n"
        f"{family_block}"
        f"{chapter_block}"
        f"{deep_crystal_block}"
        f"{npc_block}"
        f"{anti_repeat}"
        f"{continuity_block}\n"
        "The scene should:\n"
        "- Reflect where the user is therapeutically (not literally — metaphorically)\n"
        "- Include the core character manifestation naturally in the landscape\n"
        "- Feel like a chapter in an ongoing story, not a standalone image\n"
        "- Be hopeful without being dismissive of pain\n\n"
        "Return JSON only, no markdown:\n"
        f"{panel_tone_hold_hint}"
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
            # FIX #6: guarantee recurring NPCs appear visually even if the LLM omitted them
            for _npc in (todays_npcs or []):
                frag = _npc.get("visual_prompt_fragment", "")
                name_l = (_npc.get("name") or "").lower()
                if frag and name_l and name_l not in result["image_prompt"].lower():
                    result["image_prompt"] += f", {frag}"
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

    last_summary = journey.get("last_panel_summary", "") or ""
    last_npcs = journey.get("last_panel_npcs") or []
    if isinstance(last_npcs, str):
        last_npcs = json.loads(last_npcs)
    panel_seq = journey.get("panel_sequence", 0) or 0
    character = await determine_character(profile, panel_sequence=panel_seq)

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

    await _enrich_profile_coaching_calibration(profile, user_id, db_pool)
    await _enrich_profile_assessment_calibration(profile, user_id, db_pool)

    arch_ident = await _get_archetype_identity(user_id, journey, db_pool)
    arch_hint = arch_ident.get("archetype_hint", "")

    # FIX #4/#6: deep crystal recall, chapter summary, recurring NPCs (preview path)
    deep_ctx = await _fetch_deep_crystal_context(user_id, profile, db_pool)
    chapter = await _get_chapter_summary(user_id, journey, profile, db_pool)
    crystal_npcs = await _derive_crystal_npcs(user_id, profile, journey, db_pool, panel_sequence=panel_seq)

    recent_nar = await _fetch_recent_delivery_narratives(user_id, db_pool)  # FIX-NARRATIVE-DIVERSITY
    narrative = await compose_journey_narrative(
        profile, journey, biome, character, db_pool,
        last_panel_summary=last_summary, last_panel_npcs=last_npcs,
        panel_sequence=panel_seq, user_id=user_id, recent_narratives=recent_nar,
        archetype_hint=arch_hint, character_visual=arch_ident.get("character_visual", ""),
        deep_crystal_context=deep_ctx, chapter_summary=chapter,
        todays_npcs=crystal_npcs)

    image_prompt = narrative.get("image_prompt", "")
    if not image_prompt:
        image_prompt = f"{biome['description']}, a solitary figure, {character[1]}, painterly style"

    if arch_hint:
        image_prompt = image_prompt.replace("a solitary figure", f"a {arch_hint} figure, the protagonist")

    current_npcs: list = list(crystal_npcs)
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
        "current_npcs": current_npcs[:5],
    }


async def generate_journey_panel(user_id: str, db_pool) -> dict:
    """Full pipeline: profile → biome → character → narrative → image → R2 → log."""
    from app.sse.foundation.delivery_runtime import sse_imagery_generation_enabled
    if not sse_imagery_generation_enabled():
        return {"skipped": True, "reason": "sse_imagery_paused"}
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

    last_summary = journey.get("last_panel_summary", "") or ""
    last_npcs = journey.get("last_panel_npcs") or []
    if isinstance(last_npcs, str):
        last_npcs = json.loads(last_npcs)
    panel_seq = journey.get("panel_sequence", 0) or 0
    if transitioned:
        panel_seq = 0
    character = await determine_character(profile, panel_sequence=panel_seq)

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

    await _enrich_profile_coaching_calibration(profile, user_id, db_pool)
    await _enrich_profile_assessment_calibration(profile, user_id, db_pool)

    arch_ident = await _get_archetype_identity(user_id, journey, db_pool)
    arch_hint = arch_ident.get("archetype_hint", "")

    # FIX #5: at a biome transition, evolve the archetype reference image (FIG.39)
    if transitioned:
        try:
            evolved_url = await _evolve_archetype_stage(user_id, current_biome_name, arch_ident, db_pool)
            if evolved_url:
                arch_ident["archetype_image_url"] = evolved_url
        except Exception as _evo_err:
            logger.warning("Archetype evolution failed for %s: %s", user_id, _evo_err)

    # FIX #4: deep crystal recall + rolling chapter summary (long-arc memory)
    deep_ctx = await _fetch_deep_crystal_context(user_id, profile, db_pool)
    chapter = await _get_chapter_summary(user_id, journey, profile, db_pool)
    # FIX #6: recurring NPCs forged from crystal domain clusters
    crystal_npcs = await _derive_crystal_npcs(user_id, profile, journey, db_pool, panel_sequence=panel_seq)

    recent_nar = await _fetch_recent_delivery_narratives(user_id, db_pool)  # FIX-NARRATIVE-DIVERSITY
    narrative = await compose_journey_narrative(
        profile, journey, biome, character, db_pool,
        last_panel_summary=last_summary, last_panel_npcs=last_npcs,
        panel_sequence=panel_seq, user_id=user_id, recent_narratives=recent_nar,
        archetype_hint=arch_hint, character_visual=arch_ident.get("character_visual", ""),
        deep_crystal_context=deep_ctx, chapter_summary=chapter,
        todays_npcs=crystal_npcs)

    image_prompt = narrative.get("image_prompt", "")
    if not image_prompt:
        image_prompt = f"{biome['description']}, a solitary figure, {character[1]}, painterly style"

    # Archetype protagonist reference
    jmeta = journey.get("journey_metadata") or {}
    if isinstance(jmeta, str):
        jmeta = json.loads(jmeta)
    if arch_hint:
        image_prompt = image_prompt.replace("a solitary figure", f"a {arch_hint} figure, the protagonist")

    # Blend recurring crystal NPCs (FIX #6) + active quest/mission NPCs into image
    current_npcs: list = list(crystal_npcs)
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
        if frag and frag.lower() not in image_prompt.lower():
            image_prompt += f", {frag}"

    image_prompt += ", no text, no words, no lettering, no calligraphy, no writing on image"
    image_prompt += f", {character[1]}"

    archetype_ref_url = arch_ident.get("archetype_image_url") or None
    if not archetype_ref_url:
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
    _panel_saved = False
    if not r2_url:
        logger.warning(
            "SSE journey panel inserted with NULL r2_url: user_id=%s journey_id=%s biome=%s character_manifest=%s "
            "(image generation and reserve fallback both failed)",
            user_id,
            journey.get("journey_id"),
            current_biome_name,
            character[0],
        )
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
                json.dumps({
                    "domains": profile.get("top_domains", []),
                    "themes": profile.get("top_themes", []),
                }))
            _panel_saved = True
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

    if _panel_saved and db_pool:
        try:
            _qctx = ""
            if profile.get("active_quests"):
                _qctx = str(profile["active_quests"][0].get("goal") or "")[:500]
            from app.sse.adapters.clinical_translation import enrich_after_panel_generation

            await enrich_after_panel_generation(
                db_pool,
                user_id,
                panel_id,
                {
                    "generation_prompt": image_prompt,
                    "narrative_text": nar_text,
                    "panel_tone": narrative.get("panel_tone", "meditative"),
                    "biome": current_biome_name,
                    "archetype_hint": arch_hint or "",
                    "quest_context": _qctx,
                    "therapeutic_intent": journey.get("therapeutic_arc", "exploration"),
                },
                None,
            )
        except Exception as _ct_err:
            logger.warning("generate_journey_panel clinical translation failed for %s: %s", user_id, _ct_err)

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
