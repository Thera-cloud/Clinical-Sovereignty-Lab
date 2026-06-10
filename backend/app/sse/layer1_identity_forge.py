"""SSE Layer 1 — Identity Forge.

10-turn intake conversation orchestrator. Extracts structured identity
data and crystallizes key fields for Little Nate's memory.
"""
from __future__ import annotations

import hashlib, json, logging, os, re, uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

INTAKE_PROMPTS = [
    (1, "opening",
     "Hi {name}. I'm Little Nate. Before we begin, I want to take "
     "a few minutes to get to know you — not through a form, but "
     "through a conversation. That's how I work. Is that okay?"),
    (2, "presenting_concern",
     "What brought you here today? You don't have to have the "
     "right words. Just say what's true."),
    (3, "identity_self",
     "Tell me a little about yourself — not your job, not your "
     "roles. Just you. Who are you?"),
    (4, "world",
     "What does your world look like right now? The people in it, "
     "what you carry, what feels heavy."),
    (5, "roots",
     "Where do you come from? Not just geographically — I mean "
     "the people, the culture, the faith or the absence of it, "
     "the things that shaped how you see yourself."),
    (6, "wound",
     "Every person who comes here carries something. What's "
     "yours? You don't have to name it perfectly. Just point "
     "toward it."),
    (7, "strength",
     "And what do you carry that's yours — not the weight, "
     "but the strength? What in you has kept you going?"),
    (8, "identity_forge",
     "One more thing, and this might sound different. If your "
     "healing journey was a story, and you were the main "
     "character — how would you describe yourself? Not who "
     "you are to other people. Who you are in the story. "
     "What you look like. What you carry. What makes you you."),
    (9, "spiritual",
     "Last one. Faith, spirit, God, the universe — where do "
     "you stand with that? There's no wrong answer here."),
    (10, "hope",
     "What are you hoping for? If something could actually "
     "change — what would it be?"),
]


AGE_GATED_INTAKE_OVERRIDES = {
    "child": {
        2: "What's been on your mind lately? Anything at school, at home, or with friends that feels hard?",
        3: "If you could pick three words to describe yourself, what would they be?",
        5: "Tell me about the people you live with. Who matters to you?",
        6: "Sometimes kids carry something that feels heavy. Is there something like that for you?",
        8: "If you were a character in a story, what would you look like? What powers would you have?",
    },
    "adolescent": {
        2: "What's going on right now that made you decide to talk to someone?",
        6: "Everyone carries something. What's the thing you don't usually talk about?",
        8: "If your healing was a game or a story, who would your character be? Describe them.",
    },
}


def get_intake_prompt(turn: int, user_name: str, age_tier: str = "adult") -> str:
    overrides = AGE_GATED_INTAKE_OVERRIDES.get(age_tier, {})
    if turn in overrides:
        return overrides[turn].replace("{name}", user_name)
    for num, _, text in INTAKE_PROMPTS:
        if num == turn:
            return text.replace("{name}", user_name)
    return ""


def _keyword_fallback_extraction(conversation: list) -> dict:
    """Extract intake fields directly from conversation turns when LLM fails."""
    user_turns = [m["content"] for m in conversation if m.get("role") == "user"]
    data: dict = {}
    if len(user_turns) >= 2:
        data["presenting_concern"] = user_turns[1][:300]
    if len(user_turns) >= 5:
        text = user_turns[4].lower()
        data["cultural_context"] = user_turns[4][:200]
        if any(w in text for w in ("god", "jesus", "christ", "church", "pray", "bible", "faith")):
            data["spiritual_framework"] = "christian"
        elif any(w in text for w in ("universe", "energy", "spirit", "meditation")):
            data["spiritual_framework"] = "spiritual"
        else:
            data["spiritual_framework"] = "other"
    if len(user_turns) >= 6:
        data["wound_indicator"] = user_turns[5][:300]
    if len(user_turns) >= 7:
        data["strength_indicator"] = user_turns[6][:300]
    if len(user_turns) >= 8:
        data["character_visual"] = user_turns[7][:300]
        vis = user_turns[7].lower()
        for hint in ("warrior", "sage", "healer", "guardian", "explorer", "seraph"):
            if hint in vis:
                data["archetype_hint"] = hint
                break
        data.setdefault("archetype_hint", "explorer")
    if len(user_turns) >= 9:
        stext = user_turns[8].lower()
        if any(w in stext for w in ("god", "jesus", "christ", "church", "pray", "bible")):
            data.setdefault("spiritual_framework", "christian")
    if len(user_turns) >= 10:
        data["language_notes"] = user_turns[9][:200]
    return data


async def _generate_archetype_image(user_id: str, data: dict, db_pool) -> str | None:
    """Generate archetype image from character_visual + archetype_hint, store in R2."""
    char_vis = data.get("character_visual", "")
    archetype = data.get("archetype_hint", "explorer")
    if not char_vis:
        return None
    try:
        from app.sse.infrastructure.grok_imagine_client import generate_image
        from app.sse.infrastructure.r2_storage import store_image
        prompt = (f"{char_vis[:200]}, standing at the edge of a dark misty forest, "
                  f"{archetype} archetype, painterly style, muted warm palette with golden light accents, "
                  f"no text, no words, no lettering")
        image_bytes = await generate_image(prompt)
        r2_key = f"sse/archetype/{user_id}/archetype.png"
        r2_url = await store_image(image_bytes, r2_key)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_identity_forge SET archetype_image_url = $1 WHERE user_id = $2",
                r2_url, user_id)
            await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = "
                "jsonb_set(COALESCE(journey_metadata, '{}'), '{archetype_image_url}', to_jsonb($1::text)) "
                "WHERE user_id = $2", r2_url, user_id)
        return r2_url
    except Exception as e:
        logger.warning("Archetype image generation failed for %s: %s", user_id, e)
        return None


async def extract_intake_data(conversation: list, db_pool, user_id: str) -> dict:
    """Call Grok to extract structured identity data from the 10-turn intake."""
    import httpx
    url = os.getenv("NATE_CHAT_URL", "")
    key = os.getenv("XAI_API_KEY", "") or os.getenv("NATE_CHAT_KEY", "")
    model = os.getenv("NATE_CHAT_MODEL", "grok-3-mini")

    conv_text = "\n".join(f"{'Nate' if m.get('role')=='assistant' else 'User'}: {m.get('content','')}"
                          for m in conversation)
    sys_prompt = (
        "Extract identity and clinical data from this intake conversation. "
        "Return JSON only with these keys: character_visual, cultural_context, "
        "spiritual_framework (christian|secular|spiritual|other), "
        "archetype_hint (warrior|sage|healer|guardian|explorer|seraph|custom), "
        "presenting_concern, wound_indicator, strength_indicator, "
        "recommended_storyboard, clinical_eligibility_estimate (0.0-1.0), "
        "safety_flags (array), language_notes."
    )
    data = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "max_tokens": 600, "temperature": 0.3,
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": conv_text}]})
            raw = r.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}
    except Exception as e:
        logger.warning("Identity extraction failed: %s", e)

    if not data.get("character_visual"):
        logger.warning("LLM extraction returned empty for %s — falling back to keyword extraction", user_id)
        fallback = _keyword_fallback_extraction(conversation)
        for k, v in fallback.items():
            data.setdefault(k, v)

    pc = data.get("presenting_concern", "").lower()
    if any(w in pc for w in ("father", "son", "shame", "man", "legacy")):
        data["recommended_storyboard"] = "storyboard_the_father_broken_sons_v1.0"
    elif any(w in pc for w in ("parts", "alters", "trauma", "dissoc", "broken")):
        data["recommended_storyboard"] = "storyboard_he_came_for_every_part_v1.0"
    else:
        data.setdefault("recommended_storyboard", "storyboard_you_can_walk_in_it_beloved_v1.0")

    cols = "forge_id,user_id,character_visual,cultural_context,spiritual_framework,archetype_hint,presenting_concern,wound_indicator,strength_indicator,recommended_storyboard,clinical_eligibility_estimate,safety_flags,language_notes,conversation_history,status,completed_at"
    upd = ",".join(f"{c}=EXCLUDED.{c}" for c in cols.split(",")[2:-2])
    vals = [str(uuid.uuid4()), user_id, data.get("character_visual"), data.get("cultural_context"),
            data.get("spiritual_framework"), data.get("archetype_hint"), data.get("presenting_concern"),
            data.get("wound_indicator"), data.get("strength_indicator"), data.get("recommended_storyboard"),
            data.get("clinical_eligibility_estimate", 0.5), json.dumps(data.get("safety_flags", [])),
            data.get("language_notes"), json.dumps(conversation)]
    ph = ",".join(f"${i+1}" for i in range(len(vals)))
    async with db_pool.acquire() as conn:
        await conn.execute(f"INSERT INTO sse_identity_forge ({cols}) VALUES({ph},'complete',NOW()) ON CONFLICT(user_id) DO UPDATE SET {upd},status='complete',completed_at=NOW()", *vals)
        # Propagate archetype identity to the journey so the Thera-World engine
        # weaves the user's character into every panel (narrative + image).
        try:
            _arch_meta = {k: v for k, v in {
                "archetype_hint": data.get("archetype_hint"),
                "character_visual": (data.get("character_visual") or "")[:300],
            }.items() if v}
            if _arch_meta:
                await conn.execute(
                    "UPDATE sse_user_journeys SET journey_metadata = "
                    "COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb WHERE user_id = $2",
                    json.dumps(_arch_meta), user_id)
        except Exception as _jm_err:
            logger.warning("Journey metadata archetype propagation failed for %s: %s", user_id, _jm_err)

    if not data.get("archetype_hint"):
        logger.error("INTAKE EXTRACTION FAILED for %s — archetype_hint is NULL after LLM + fallback", user_id)
    if not data.get("character_visual"):
        logger.error("INTAKE EXTRACTION FAILED for %s — character_visual is NULL after LLM + fallback", user_id)

    archetype_url = await _generate_archetype_image(user_id, data, db_pool)
    if archetype_url:
        data["archetype_image_url"] = archetype_url

    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation
        crystal_text = f"Intake: {data.get('presenting_concern','')} | Wound: {data.get('wound_indicator','')} | Strength: {data.get('strength_indicator','')}"
        await crystallize_from_conversation(db_pool, user_id, crystal_text,
            f"Identity forged: {data.get('archetype_hint','')} archetype, {data.get('cultural_context','')}",
            domain="clinical", min_score=2)
    except Exception:
        pass

    return data
