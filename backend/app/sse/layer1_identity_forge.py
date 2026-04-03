"""SSE Layer 1 — Identity Forge.

10-turn intake conversation orchestrator. Extracts structured identity
data and crystallizes key fields for Little Nate's memory.
"""
from __future__ import annotations

import json, logging, os, re, uuid
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


def get_intake_prompt(turn: int, user_name: str) -> str:
    for num, _, text in INTAKE_PROMPTS:
        if num == turn:
            return text.replace("{name}", user_name)
    return ""


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
        "archetype_hint (warrior|sage|healer|guardian|explorer|child), "
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

    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation
        crystal_text = f"Intake: {data.get('presenting_concern','')} | Wound: {data.get('wound_indicator','')} | Strength: {data.get('strength_indicator','')}"
        await crystallize_from_conversation(db_pool, user_id, crystal_text,
            f"Identity forged: {data.get('archetype_hint','')} archetype, {data.get('cultural_context','')}",
            domain="clinical", min_score=2)
    except Exception:
        pass

    return data
