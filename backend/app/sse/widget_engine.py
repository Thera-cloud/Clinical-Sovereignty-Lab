"""SSE Widget Engine — daily home screen widget content selection.

Determines what content to show on the user's home screen widget based on
their therapeutic state, crystal intelligence, active quests/missions,
and spiritual framework. No LLM calls — all content is pre-computed or
template-based for fast background refresh.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_BIOME_COLORS: Dict[str, str] = {
    "dark_forest": "#1a2332",
    "fortress_plains": "#2d3a1e",
    "river_valley": "#1e3a3a",
    "crystal_mountains": "#2a1e3a",
    "open_sky": "#1e2a3a",
}

_CRISIS_KEYWORDS = {"crisis", "shutdown", "dissociation", "suicidal", "self-harm", "destabilized"}

_POWER_WORDS = [
    "Breathe", "Enough", "Worthy", "Present", "Brave",
    "Held", "Safe", "Seen", "Whole", "Free",
    "Strong", "Rooted", "Calm", "Loved", "Anchored",
    "Resilient", "Gentle", "Open", "Steady", "Alive",
]

_DEVOTIONALS = [
    ("He heals the brokenhearted and binds up their wounds.", "Psalm 147:3"),
    ("Come to me, all who are weary and burdened, and I will give you rest.", "Matthew 11:28"),
    ("The Lord is close to the brokenhearted.", "Psalm 34:18"),
    ("Be still, and know that I am God.", "Psalm 46:10"),
    ("I can do all things through Christ who strengthens me.", "Philippians 4:13"),
    ("Cast all your anxiety on him because he cares for you.", "1 Peter 5:7"),
    ("The Lord is my shepherd; I shall not want.", "Psalm 23:1"),
    ("For I know the plans I have for you, declares the Lord.", "Jeremiah 29:11"),
    ("God is our refuge and strength, an ever-present help in trouble.", "Psalm 46:1"),
    ("Do not fear, for I am with you.", "Isaiah 41:10"),
    ("Peace I leave with you; my peace I give you.", "John 14:27"),
    ("The Lord your God is with you, the Mighty Warrior who saves.", "Zephaniah 3:17"),
    ("Trust in the Lord with all your heart.", "Proverbs 3:5"),
    ("He gives strength to the weary.", "Isaiah 40:29"),
    ("My grace is sufficient for you.", "2 Corinthians 12:9"),
    ("The light shines in the darkness, and the darkness has not overcome it.", "John 1:5"),
    ("You are fearfully and wonderfully made.", "Psalm 139:14"),
    ("Weeping may stay for the night, but rejoicing comes in the morning.", "Psalm 30:5"),
    ("I will never leave you nor forsake you.", "Hebrews 13:5"),
    ("In all things God works for the good of those who love him.", "Romans 8:28"),
    ("The truth will set you free.", "John 8:32"),
    ("Create in me a clean heart, O God.", "Psalm 51:10"),
    ("He restores my soul.", "Psalm 23:3"),
    ("The Lord is gracious and compassionate, slow to anger and rich in love.", "Psalm 145:8"),
    ("When I am afraid, I put my trust in you.", "Psalm 56:3"),
    ("Be strong and courageous. Do not be afraid.", "Joshua 1:9"),
    ("He has made everything beautiful in its time.", "Ecclesiastes 3:11"),
    ("Even the darkness is not dark to you.", "Psalm 139:12"),
    ("You hem me in behind and before, and you lay your hand upon me.", "Psalm 139:5"),
    ("The steadfast love of the Lord never ceases.", "Lamentations 3:22"),
]

_SECULAR_WISDOM = [
    ("The wound is the place where the Light enters you.", "Rumi"),
    ("Vulnerability is not weakness. It is our most accurate measure of courage.", "Brené Brown"),
    ("He who has a why to live can bear almost any how.", "Viktor Frankl"),
    ("There is no greater agony than bearing an untold story inside you.", "Maya Angelou"),
    ("The only way out is through.", "Robert Frost"),
    ("What we resist, persists.", "Carl Jung"),
    ("You are not a drop in the ocean. You are the entire ocean in a drop.", "Rumi"),
    ("Between stimulus and response there is a space.", "Viktor Frankl"),
    ("Owning our story is the bravest thing we will ever do.", "Brené Brown"),
    ("Out of your vulnerabilities will come your strength.", "Sigmund Freud"),
    ("The curious paradox is that when I accept myself, then I can change.", "Carl Rogers"),
    ("In the middle of difficulty lies opportunity.", "Albert Einstein"),
    ("You do not just wake up and become the butterfly. Growth is a process.", "Rupi Kaur"),
    ("Nothing ever goes away until it teaches us what we need to know.", "Pema Chödrön"),
    ("We are not meant to stay wounded. We are supposed to move through our tragedies.", "Clarissa Pinkola Estés"),
    ("Your task is not to seek for love, but to find all the barriers you have built against it.", "Rumi"),
    ("The privilege of a lifetime is to become who you truly are.", "Carl Jung"),
    ("Every morning we are born again. What we do today matters most.", "Buddha"),
    ("You have been criticizing yourself for years and it hasn't worked. Try approving of yourself.", "Louise Hay"),
    ("When we are no longer able to change a situation, we are challenged to change ourselves.", "Viktor Frankl"),
    ("No mud, no lotus.", "Thich Nhat Hanh"),
    ("The cave you fear to enter holds the treasure you seek.", "Joseph Campbell"),
    ("What lies behind us and what lies before us are tiny matters compared to what lies within us.", "Ralph Waldo Emerson"),
    ("The most common way people give up their power is by thinking they don't have any.", "Alice Walker"),
    ("Courage is not the absence of fear but the judgment that something is more important.", "Ambrose Redmoon"),
    ("Not until we are lost do we begin to understand ourselves.", "Henry David Thoreau"),
    ("You are allowed to be both a masterpiece and a work in progress.", "Sophia Bush"),
    ("Stars can't shine without darkness.", "D.H. Sidebottom"),
    ("The only person you are destined to become is the person you decide to be.", "Ralph Waldo Emerson"),
    ("This too shall pass.", "Persian Proverb"),
]


async def get_widget_content(user_id: str, db_pool) -> Dict[str, Any]:
    """Determine today's widget content based on therapeutic state."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    three_days_ago = now - timedelta(days=3)

    biome = "dark_forest"
    spiritual = None
    latest_panel_url = None
    latest_panel_narrative = None

    try:
        async with db_pool.acquire() as conn:
            # Current biome
            jrow = await conn.fetchrow(
                "SELECT current_biome FROM sse_user_journeys WHERE user_id=$1", user_id)
            if jrow:
                biome = jrow["current_biome"] or "dark_forest"

            # Spiritual framework
            irow = await conn.fetchrow(
                "SELECT spiritual_framework FROM sse_identity_forge WHERE user_id=$1", user_id)
            if irow:
                spiritual = irow["spiritual_framework"]

            # 1. Biome transition today
            alert = await conn.fetchrow(
                "SELECT content FROM sse_admin_alerts WHERE user_id=$1 AND alert_type='biome_transition' AND created_at >= $2",
                user_id, today_start)
            if alert:
                return _content("milestone", biome, primary="You've entered a new biome.",
                                secondary=biome.replace("_", " ").title(), action="open_journey")

            # 2. Quest completed today
            cq = await conn.fetchrow(
                "SELECT title FROM sse_quests WHERE user_id=$1 AND status='completed' AND completed_at >= $2",
                user_id, today_start)
            if cq:
                return _content("milestone", biome, primary=f"Quest complete: {cq['title']}",
                                secondary="Your growth is real.", action="open_quest")

            # 3. Crisis crystal in last 24h
            crisis = await conn.fetchrow(
                "SELECT crystal_text FROM nate_intelligence_crystals WHERE user_id=$1 AND domain='clinical' AND confidence >= 0.8 AND created_at >= $2 ORDER BY confidence DESC LIMIT 1",
                user_id, now - timedelta(hours=24))
            if crisis and any(kw in (crisis["crystal_text"] or "").lower() for kw in _CRISIS_KEYWORDS):
                return _content("encouragement", biome,
                                primary="You're not alone in this. Reach out when you're ready.",
                                secondary="Little Nate is here.", action="open_chat")

            # 4. Active quest (30% chance goal)
            aq = await conn.fetchrow(
                "SELECT id, title FROM sse_quests WHERE user_id=$1 AND status='active' ORDER BY started_at DESC LIMIT 1", user_id)
            if aq and random.random() < 0.3:
                return _content("goal", biome, primary=aq["title"],
                                secondary="Keep going.", action="open_quest",
                                action_id=str(aq["id"]))

            # 5. Active mission + no session in 3+ days
            am = await conn.fetchrow(
                "SELECT id, title FROM sse_missions WHERE user_id=$1 AND status='active' ORDER BY started_at DESC LIMIT 1", user_id)
            if am:
                last_sess = await conn.fetchval(
                    "SELECT MAX(created_at) FROM conversation_history WHERE user_id=$1", user_id)
                if not last_sess or last_sess < three_days_ago:
                    return _content("mission_reminder", biome, primary=am["title"],
                                    secondary="Your mission awaits.", action="open_chat",
                                    action_id=str(am["id"]))

            # 6. Meaningful session yesterday (high-confidence crystal)
            yesterday = today_start - timedelta(days=1)
            reflection = await conn.fetchrow(
                "SELECT crystal_text FROM nate_intelligence_crystals WHERE user_id=$1 AND confidence >= 0.7 AND created_at BETWEEN $2 AND $3 ORDER BY confidence DESC LIMIT 1",
                user_id, yesterday, today_start)
            if reflection and reflection["crystal_text"]:
                text = reflection["crystal_text"]
                snippet = text[:120] + "…" if len(text) > 120 else text
                return _content("reflection", biome, primary=snippet,
                                secondary="From yesterday's session", action="open_chat")

            # 7. No check-in in 3+ days
            last_checkin = await conn.fetchval(
                "SELECT MAX(created_at) FROM sse_panel_log WHERE user_id=$1 AND panel_type='checkin'", user_id)
            if not last_checkin or last_checkin < three_days_ago:
                return _content("check_in", biome, primary="How are you today?",
                                secondary="Tap to check in with Little Nate", action="open_checkin")

            # 8/9. Faith / secular wisdom (20% chance)
            if spiritual == "christian" and random.random() < 0.2:
                verse, source = random.choice(_DEVOTIONALS)
                return _content("devotional", biome, primary=verse,
                                secondary=source, action="open_chat")
            if spiritual in ("spiritual", "other", "secular") and random.random() < 0.2:
                quote, author = random.choice(_SECULAR_WISDOM)
                return _content("secular_wisdom", biome, primary=quote,
                                secondary=f"— {author}", action="open_chat")

            # 10. Default: journey panel or power word
            panel = await conn.fetchrow(
                "SELECT panel_id, r2_url, narrative_text FROM sse_panel_log WHERE user_id=$1 AND r2_url IS NOT NULL ORDER BY created_at DESC LIMIT 1", user_id)
            if panel and panel["r2_url"]:
                narr = panel["narrative_text"] or ""
                snippet = narr[:100] + "…" if len(narr) > 100 else narr
                return _content("journey_panel", biome, primary=snippet or "Your journey continues.",
                                secondary=biome.replace("_", " ").title(),
                                image_url=panel["r2_url"], action="open_journey",
                                action_id=str(panel["panel_id"]))

    except Exception as e:
        logger.warning("widget_engine: failed to query for user %s: %s", user_id, e)

    # Absolute fallback: power word
    word = random.choice(_POWER_WORDS)
    return _content("single_word", biome, primary=word, action="open_chat")


def _content(content_type: str, biome: str, *, primary: str,
             secondary: Optional[str] = None, image_url: Optional[str] = None,
             action: str = "open_chat", action_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "type": content_type,
        "image_url": image_url,
        "primary_text": primary,
        "secondary_text": secondary,
        "action": action,
        "action_id": action_id,
        "background_color": _BIOME_COLORS.get(biome, "#1a2332"),
    }
