"""SSE Quest & Mission Engine — crystal-informed NPC generation and story arcs.

Mines crystal history to generate archetypal NPC characters for quests/missions.
NPCs are metaphorical and never literal representations of real people.

# TODO Phase 3: Crystal confidence levels affecting narrative intensity
# TODO Phase 3: Cross-domain crystal co-occurrence for complex NPCs
# TODO Phase 3: Quest/mission history endpoints
"""
from __future__ import annotations

import json, logging, os, re, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GOAL_TO_DOMAINS: Dict[str, List[str]] = {
    "confidence": ["self-worth", "identity", "shame", "performance"],
    "anxiety": ["anxiety", "fear", "control", "attachment"],
    "anger": ["anger", "resentment", "boundaries", "control"],
    "relationship": ["attachment", "trust", "abandonment", "codependency"],
    "grief": ["grief", "loss", "abandonment"],
    "forgiveness": ["forgiveness", "resentment", "anger"],
    "depression": ["depression", "loss", "loneliness", "self-worth"],
    "boundaries": ["boundaries", "control", "codependency", "identity"],
    "trauma": ["trauma", "fear", "shame", "abandonment"],
    "self-esteem": ["self-worth", "identity", "shame", "rejection"],
}

DOMAIN_TO_PATTERN: Dict[str, str] = {
    "shame": "shadow_self", "anger": "shadow_self", "fear": "shadow_self",
    "control": "architect", "perfectionism": "architect", "codependency": "architect",
    "grief": "tide", "loss": "tide", "abandonment": "wanderer",
    "trust": "guardian", "attachment": "guardian", "love": "guardian",
    "identity": "reflection", "self-worth": "reflection", "rejection": "reflection",
    "faith": "flame_keeper", "hope": "flame_keeper", "forgiveness": "flame_keeper",
    "trauma": "echo", "resentment": "echo", "deception": "echo",
    "vulnerability": "seeker", "growth": "seeker", "loneliness": "seeker",
    "confidence": "reflection", "anxiety": "shadow_self", "patience": "tide",
    "boundaries": "architect", "relationship": "guardian", "connection": "seeker",
}

TEMPLATE_NPCS: Dict[str, Dict[str, str]] = {
    "shadow_self": {"name": "The Shadow", "description": "A dark silhouette that mirrors the traveler's movements",
                    "initial_form": "Lurking at the edge of perception", "transformed_form": "Standing beside the traveler as an ally",
                    "visual_prompt_fragment": "a dark silhouette at the edge of the scene, watchful"},
    "architect": {"name": "The Architect", "description": "A figure building walls around everything, calling it protection",
                  "initial_form": "Obsessively stacking stones into barriers", "transformed_form": "Building bridges instead of walls",
                  "visual_prompt_fragment": "a cloaked figure stacking stones into a half-built wall"},
    "tide": {"name": "The Tide", "description": "A presence that rises and falls, sometimes gentle, sometimes overwhelming",
             "initial_form": "Crashing against the shore with no rhythm", "transformed_form": "Flowing gently, carrying rather than crushing",
             "visual_prompt_fragment": "luminous water rising at the edges of the scene"},
    "wanderer": {"name": "The Wanderer", "description": "A figure seen at the edge of every scene, never staying",
                 "initial_form": "Always walking away, back turned", "transformed_form": "Pausing, turning to face the traveler",
                 "visual_prompt_fragment": "a distant figure at the horizon, walking away"},
    "guardian": {"name": "The Silent Guardian", "description": "A figure who watches but never speaks",
                 "initial_form": "Standing motionless, arms crossed, blocking the path", "transformed_form": "Stepping aside, offering a hand",
                 "visual_prompt_fragment": "a tall sentinel figure standing guard in the mist"},
    "reflection": {"name": "The Mirror Walker", "description": "A being that shows a slightly different version of the traveler",
                   "initial_form": "Distorting the traveler's image in reflective surfaces", "transformed_form": "Showing the traveler as they truly are",
                   "visual_prompt_fragment": "a reflective pool showing a different figure than the one standing above it"},
    "flame_keeper": {"name": "The Flame Keeper", "description": "Warmth that appears in moments of freeze",
                     "initial_form": "A flickering candle in the darkness, barely visible", "transformed_form": "A steady hearth fire, warm and inviting",
                     "visual_prompt_fragment": "a warm golden glow emanating from cupped hands in the darkness"},
    "echo": {"name": "The Echo", "description": "A voice that distorts the traveler's words",
             "initial_form": "Repeating painful words louder and louder", "transformed_form": "Becoming harmony, adding depth to the traveler's voice",
             "visual_prompt_fragment": "ripples of sound visible in the air, distorting the scene"},
    "seeker": {"name": "The Seeker", "description": "A curious presence drawn to unexplored paths",
               "initial_form": "Pointing toward doors that feel dangerous", "transformed_form": "Walking alongside, sharing the discovery",
               "visual_prompt_fragment": "a small luminous figure peering through an open doorway"},
}


async def analyze_crystal_depth(
    user_id: str,
    goal_or_target: str,
    db_pool,
    priority_goal_keys: Optional[List[str]] = None,
) -> dict:
    """Mine crystal history for patterns related to the quest/mission topic."""
    domains: set = set()
    goal_lower = (goal_or_target or "").lower()
    for keyword, domain_list in GOAL_TO_DOMAINS.items():
        if keyword in goal_lower:
            domains.update(domain_list)
    for pk in priority_goal_keys or []:
        if pk in GOAL_TO_DOMAINS:
            domains.update(GOAL_TO_DOMAINS[pk])
    if not domains:
        domains = {w for w in goal_lower.split() if len(w) > 3}

    clusters: List[Dict[str, Any]] = []
    goal_domain = ""
    try:
        async with db_pool.acquire() as conn:
            uid = await conn.fetchval("SELECT id FROM users WHERE username = $1", user_id)
            if not uid:
                return {"clusters": [], "goal_domain": ""}
            domain_list = list(domains)
            rows = await conn.fetch(
                "SELECT domain, crystal_text FROM nate_intelligence_crystals "
                "WHERE user_id = $1 AND superseded_by IS NULL AND domain = ANY($2)",
                uid, domain_list)
            by_domain: Dict[str, list] = {}
            for r in rows:
                d = r["domain"]
                by_domain.setdefault(d, []).append(r["crystal_text"] or "")
            for d, texts in by_domain.items():
                if len(texts) >= 5:
                    pattern = DOMAIN_TO_PATTERN.get(d, "seeker")
                    clusters.append({"domain": d, "crystal_count": len(texts),
                                     "pattern": pattern, "sample_texts": [t[:150] for t in texts[:3]]})
                    if not goal_domain:
                        goal_domain = d
    except Exception as e:
        logger.warning("analyze_crystal_depth failed for %s: %s", user_id, e)
    return {"clusters": clusters, "goal_domain": goal_domain}


async def generate_npcs_from_crystals(clusters: list) -> list:
    """Transform crystal clusters into story NPCs via single batch LLM call."""
    if not clusters:
        return []
    from app.sse.llm_fallback import chat_completion_with_fallback

    cluster_desc = "\n".join(
        f"- Domain: {c['domain']}, pattern: {c['pattern']}, "
        f"crystal samples: {'; '.join(c.get('sample_texts', [])[:2])}"
        for c in clusters)
    sys_prompt = (
        "Generate mythical/archetypal NPC characters for a therapeutic story. "
        "Each character represents a psychological pattern without literally depicting any real person. "
        "Return a JSON array (no markdown) with one NPC per cluster:\n"
        f"{cluster_desc}\n\n"
        "Each NPC: {\"name\": \"The ...\", \"description\": \"1-2 sentences\", "
        "\"initial_form\": \"how they first appear\", \"transformed_form\": \"how they change when healing occurs\", "
        "\"visual_prompt_fragment\": \"short image prompt fragment for Grok Imagine\"}"
    )
    try:
        raw = await chat_completion_with_fallback(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "Generate NPCs for all clusters."}],
            max_tokens=600)
        if raw:
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
    except Exception as e:
        logger.warning("generate_npcs_from_crystals LLM failed: %s", e)
    return [TEMPLATE_NPCS.get(c["pattern"], TEMPLATE_NPCS["seeker"]) for c in clusters]


async def create_quest(user_id: str, goal: str, db_pool, crystal_analysis: dict = None) -> dict:
    """Create a quest from user's stated goal, enriched with crystal depth."""
    priority_keys: List[str] = []
    try:
        from app.sse.adapters.assessment_bridge import AssessmentBridge

        ab = AssessmentBridge(db_pool)
        acal = await ab.get_assessment_calibration(user_id)
        if acal.get("has_assessments"):
            priority_keys = ab.quest_goal_keywords_for_priorities(acal.get("domain_priorities") or [])
    except Exception as _ab_err:
        logger.debug("create_quest assessment weighting skipped: %s", _ab_err)

    if not crystal_analysis:
        goal_for_depth = goal
        if priority_keys:
            goal_for_depth = f"{goal} {' '.join(priority_keys)}".strip()
        crystal_analysis = await analyze_crystal_depth(
            user_id, goal_for_depth, db_pool, priority_goal_keys=priority_keys or None,
        )
    npcs = await generate_npcs_from_crystals(crystal_analysis.get("clusters", []))
    quest_id = str(uuid.uuid4())
    progress = [{"timestamp": datetime.now(timezone.utc).isoformat(), "event": "quest_created",
                 "npcs": npcs, "initial_crystal_count": sum(c["crystal_count"] for c in crystal_analysis.get("clusters", []))}]
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sse_quests (quest_id, user_id, goal, goal_domain, progress_notes) "
                "VALUES ($1, $2, $3, $4, $5::jsonb)",
                quest_id, user_id, goal, crystal_analysis.get("goal_domain", ""),
                json.dumps(progress))
            await conn.execute(
                "INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail) "
                "VALUES ($1, 'quest_created', 'Quest Created', $2)",
                user_id, f"Goal: {goal}")
    except Exception as e:
        logger.warning("create_quest DB write failed for %s: %s", user_id, e)
    return {"quest_id": quest_id, "goal": goal, "goal_domain": crystal_analysis.get("goal_domain", ""),
            "npcs": npcs, "clusters": crystal_analysis.get("clusters", [])}


async def create_mission(user_id: str, relationship_target: str, relationship_type: str,
                         db_pool, crystal_analysis: dict = None) -> dict:
    """Create a mission for relational work, enriched with crystal depth."""
    priority_keys: List[str] = []
    try:
        from app.sse.adapters.assessment_bridge import AssessmentBridge

        ab = AssessmentBridge(db_pool)
        acal = await ab.get_assessment_calibration(user_id)
        if acal.get("has_assessments"):
            priority_keys = ab.quest_goal_keywords_for_priorities(acal.get("domain_priorities") or [])
    except Exception as _ab_err:
        logger.debug("create_mission assessment weighting skipped: %s", _ab_err)

    if not crystal_analysis:
        tgt = relationship_target
        if priority_keys:
            tgt = f"{relationship_target} {' '.join(priority_keys)}".strip()
        crystal_analysis = await analyze_crystal_depth(
            user_id, tgt, db_pool, priority_goal_keys=priority_keys or None,
        )
    npcs = await generate_npcs_from_crystals(crystal_analysis.get("clusters", []))
    mission_id = str(uuid.uuid4())
    progress = [{"timestamp": datetime.now(timezone.utc).isoformat(), "event": "mission_created",
                 "npcs": npcs, "initial_crystal_count": sum(c["crystal_count"] for c in crystal_analysis.get("clusters", []))}]
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sse_missions (mission_id, user_id, relationship_target, relationship_type, progress_notes) "
                "VALUES ($1, $2, $3, $4, $5::jsonb)",
                mission_id, user_id, relationship_target, relationship_type, json.dumps(progress))
            await conn.execute(
                "INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail) "
                "VALUES ($1, 'mission_created', 'Mission Created', $2)",
                user_id, f"Target: {relationship_target} ({relationship_type})")
    except Exception as e:
        logger.warning("create_mission DB write failed for %s: %s", user_id, e)
    return {"mission_id": mission_id, "relationship_target": relationship_target,
            "relationship_type": relationship_type, "npcs": npcs}


async def compose_quest_panel(user_id: str, quest: dict, profile: dict,
                              journey: dict, db_pool) -> dict:
    """Generate a quest-specific panel that weaves NPCs into the biome."""
    from app.sse.thera_world_engine import BIOME_THRESHOLDS, determine_character
    biome_name = journey.get("current_biome", "dark_forest")
    biome = next((b for b in BIOME_THRESHOLDS if b["biome"] == biome_name), BIOME_THRESHOLDS[0])
    character = await determine_character(profile)
    progress = quest.get("progress_notes", [])
    if isinstance(progress, str):
        progress = json.loads(progress)
    npcs = progress[0].get("npcs", []) if progress else []
    npc_frags = ", ".join(n.get("visual_prompt_fragment", "") for n in npcs[:3] if n.get("visual_prompt_fragment"))
    fallback = {
        "narrative_text": f"In the {biome_name.replace('_', ' ')}, the quest for {quest.get('goal', 'growth')} continues.",
        "image_prompt": f"{biome['description']}, a solitary figure, {character[1]}, {npc_frags}, painterly style, muted warm palette, no text",
        "panel_tone": "action_sequence",
    }
    return fallback  # TODO Phase 3: LLM-composed quest panels with arc awareness


async def compose_mission_panel(user_id: str, mission: dict, profile: dict,
                                journey: dict, db_pool) -> dict:
    """Generate a mission-specific panel for relational work."""
    from app.sse.thera_world_engine import BIOME_THRESHOLDS, determine_character
    biome_name = journey.get("current_biome", "dark_forest")
    biome = next((b for b in BIOME_THRESHOLDS if b["biome"] == biome_name), BIOME_THRESHOLDS[0])
    character = await determine_character(profile)
    fallback = {
        "narrative_text": f"In the {biome_name.replace('_', ' ')}, the relational journey with {mission.get('relationship_target', 'a loved one')} deepens.",
        "image_prompt": f"{biome['description']}, two distant figures in the landscape, {character[1]}, painterly style, muted warm palette, no text",
        "panel_tone": "meditative",
    }
    return fallback  # TODO Phase 3: LLM-composed mission panels


async def update_quest_progress(quest_id: str, new_crystal_summaries: list, db_pool) -> dict:
    """Append progress and check for arc advancement. Wire point: Phase 2B."""
    # TODO Phase 2B: Wire into crystal pipeline when new crystals are created in quest domain
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sse_quests WHERE quest_id = $1", quest_id)
            if not row:
                return {"error": "quest not found"}
            progress = json.loads(row["progress_notes"]) if isinstance(row["progress_notes"], str) else (row["progress_notes"] or [])
            entry = {"timestamp": datetime.now(timezone.utc).isoformat(),
                     "event": "crystals_added", "crystals": new_crystal_summaries[:5]}
            initial_count = progress[0].get("initial_crystal_count", 0) if progress else 0
            total_added = sum(len(p.get("crystals", [])) for p in progress if p.get("event") == "crystals_added")
            total_added += len(new_crystal_summaries)
            days_active = (datetime.now(timezone.utc) - row["started_at"].replace(tzinfo=timezone.utc)).days if row["started_at"] else 0
            if days_active >= 7 and initial_count > 0 and total_added >= initial_count * 0.5:
                entry["climax_ready"] = True
            progress.append(entry)
            await conn.execute(
                "UPDATE sse_quests SET progress_notes = $1::jsonb WHERE quest_id = $2",
                json.dumps(progress), quest_id)
            return {"quest_id": quest_id, "progress_count": len(progress),
                    "climax_ready": entry.get("climax_ready", False)}
    except Exception as e:
        logger.warning("update_quest_progress failed for %s: %s", quest_id, e)
        return {"error": str(e)}
