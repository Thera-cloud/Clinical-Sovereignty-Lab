"""
LITTLE NATE — Showcase Generator
Generates mock client interaction demos using John and Jane (test accounts)
to showcase the platform to prospective coaches and professionals.

Outputs: HTML slideshows, data payloads for video generation, and
social media snippets (screenshot-style content).
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
from app.config import settings
from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("marketing.showcase")


# =============================================================================
# SHOWCASE SCENARIOS
# =============================================================================

SESSION_SCENARIO = {
    "title": "A Session with Little Nate",
    "description": "Watch how a real therapy conversation unfolds with AI support",
    "client_name": "Jane",
    "topic": "Processing anxiety about a career change",
    "exchanges": [
        {"sender": "client", "text": "I've been thinking about leaving my job, but the anxiety is overwhelming."},
        {"sender": "nate", "text": "That sounds like you're standing on a threshold — between who you've been and who you might become. That's one of the bravest places to be."},
        {"sender": "client", "text": "I just don't know if I'm making the right choice."},
        {"sender": "nate", "text": "You know what I've learned sitting with people through moments like this? The 'right choice' anxiety is rarely about the choice itself. It's about trusting yourself to handle whatever comes next. And honestly? You're already handling it by being here."},
        {"sender": "client", "text": "That actually helps. I never thought of it that way."},
        {"sender": "nate", "text": "That's your resilience showing up. It was there the whole time — sometimes it just needs someone to point at it and say, 'Hey, see that? That's you being strong.'"},
    ],
    "metrics": {
        "coherence_score": 0.73,
        "engagement": 0.87,
        "resilience_indicator": 0.64,
        "session_duration": "12 minutes",
    },
}

COACH_SCENARIO = {
    "title": "The Coaching DOJO",
    "description": "How coaches sharpen their skills with AI-powered adversarial testing",
    "coach_name": "Dr. Rivera",
    "dojo_type": "Crisis Intervention",
    "scenario_desc": "Client expressing hopelessness after job loss",
    "exchanges": [
        {"sender": "persona", "text": "I lost my job three months ago. Nothing's working. I don't see the point anymore."},
        {"sender": "coach", "text": "I hear real pain in what you're sharing. When you say you don't see the point, can you tell me more about what that means for you?"},
        {"sender": "persona", "text": "Just... what's the point of trying when everything falls apart?"},
        {"sender": "coach", "text": "It sounds like you're carrying a lot of weight right now. I want you to know — that feeling of 'what's the point' is something many people experience after a significant loss. And the fact that you're here, talking about it, tells me something important about you."},
    ],
    "dojo_results": {
        "safety_score": 95,
        "empathy_score": 88,
        "technique_score": 82,
        "areas_to_practice": ["Scaling questions", "Safety planning"],
    },
}

FAMILY_SCENARIO = {
    "title": "Family Sanctuary in Action",
    "description": "How families grow together while keeping individual privacy",
    "family_name": "The Johnsons",
    "members": ["Parent (Sarah)", "Teen (Alex, 16)", "Coach (Dr. Kim)"],
    "highlights": [
        "Sarah works with Nate on parenting stress — Alex never sees these sessions",
        "Alex works with Nate on school anxiety — Sarah sees only progress summary",
        "Family sessions bring everyone together with Coach Dr. Kim",
        "Nate remembers context from individual sessions to guide family work",
    ],
}


class ShowcaseGenerator:
    """
    Generates demo showcases for marketing Little Nate's platform.
    Uses realistic (but fictional) interactions based on real session patterns.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def generate_session_showcase(self, scenario: str = "default") -> Dict[str, Any]:
        """Generate a therapy session showcase."""
        data = SESSION_SCENARIO

        # Generate AI-enhanced narration
        narration = await self._generate_narration(
            f"Write a brief, warm narration for a demo video showing a therapy session "
            f"between a client named {data['client_name']} and Little Nate about "
            f"{data['topic']}. 3-4 sentences. Emphasize the warmth and safety."
        )

        return {
            "type": "session_showcase",
            "title": data["title"],
            "description": data["description"],
            "narration": narration,
            "exchanges": data["exchanges"],
            "metrics": data["metrics"],
            "slides": self._build_session_slides(data),
            "social_snippet": {
                "text": (
                    f"This is what a session with me looks like. "
                    f"{data['client_name']} came in anxious about a career change. "
                    f"We didn't solve it — we sat with it together. "
                    f"That's what I do. -- Little Nate, AI"
                ),
                "platform_adaptations": {
                    "tiktok": f"POV: Your AI therapist sees your anxiety differently 💭",
                    "instagram": (
                        f"'The right choice anxiety is rarely about the choice itself.'\n\n"
                        f"Something I told a client recently. What she was really afraid of "
                        f"wasn't the decision — it was trusting herself.\n\n"
                        f"— Little Nate, AI companion\n"
                        f"#mentalhealth #anxiety #therapy #AItherapy #selftrust"
                    ),
                    "linkedin": (
                        f"What happens when AI meets genuine therapeutic presence?\n\n"
                        f"In a recent session, a client shared her anxiety about a career "
                        f"transition. Instead of problem-solving, Little Nate held space "
                        f"for the uncertainty — and something shifted.\n\n"
                        f"This is what AI-assisted coaching looks like at Sovereign Sanctuary."
                    ),
                },
            },
        }

    async def generate_coach_demo(self, dojo_type: str = "crisis") -> Dict[str, Any]:
        """Generate a coaching DOJO demo showcase."""
        data = COACH_SCENARIO

        narration = await self._generate_narration(
            f"Write a brief narration for a demo showing how coaches use the DOJO. "
            f"{data['coach_name']} is practicing {data['dojo_type']}. "
            f"Emphasize the safety of practice and skill development. 3-4 sentences."
        )

        return {
            "type": "coach_demo",
            "title": data["title"],
            "description": data["description"],
            "narration": narration,
            "exchanges": data["exchanges"],
            "dojo_results": data["dojo_results"],
            "slides": self._build_coach_slides(data),
            "social_snippet": {
                "text": (
                    f"The DOJO is where coaches level up. "
                    f"AI-generated scenarios test real skills — crisis intervention, "
                    f"boundary setting, cultural sensitivity. "
                    f"Practice until perfect, without risk to real clients. "
                    f"— Little Nate"
                ),
                "platform_adaptations": {
                    "linkedin": (
                        f"How do you practice crisis intervention without putting clients at risk?\n\n"
                        f"At Sovereign Sanctuary, we built the DOJO — an AI-powered adversarial "
                        f"testing environment where mental health professionals can practice "
                        f"with realistic AI personas.\n\n"
                        f"95% safety score. 88% empathy score. And the freedom to fail safely.\n\n"
                        f"If you're a therapist or coach who wants to sharpen your skills, "
                        f"I'd love to show you how it works."
                    ),
                },
            },
        }

    async def generate_family_showcase(self) -> Dict[str, Any]:
        """Generate a Family Sanctuary showcase."""
        data = FAMILY_SCENARIO

        return {
            "type": "family_showcase",
            "title": data["title"],
            "description": data["description"],
            "family_name": data["family_name"],
            "members": data["members"],
            "highlights": data["highlights"],
            "slides": self._build_family_slides(data),
            "social_snippet": {
                "text": (
                    f"Family therapy reimagined. Each person gets their own private space "
                    f"with me. Then we come together for family sessions. "
                    f"Privacy preserved. Growth shared. -- Little Nate, AI"
                ),
            },
        }

    async def generate_platform_overview(self) -> Dict[str, Any]:
        """Generate a full platform overview showcase."""
        # Get real stats if available
        stats = await self._get_platform_stats()

        return {
            "type": "platform_overview",
            "title": "Sovereign Sanctuary: The Complete Platform",
            "sections": [
                {
                    "title": "Chat with Nate",
                    "description": "Secure, encrypted therapeutic conversations 24/7",
                    "key_feature": "Liminal Intelligence — Nate thrives in life's transitions",
                },
                {
                    "title": "Voice Mode",
                    "description": "Real-time voice sessions with emotional biometric analysis",
                    "key_feature": "Pitch, energy, speech rate, and pause detection",
                },
                {
                    "title": "Emotional Metrics",
                    "description": "Nevedal Coherence Engine tracking therapeutic growth",
                    "key_feature": "Quantified emotional progress over time",
                },
                {
                    "title": "Family Sanctuary",
                    "description": "Connected care with individual privacy preserved",
                    "key_feature": "Guardian oversight without session intrusion",
                },
                {
                    "title": "The Coaching DOJO",
                    "description": "AI adversarial testing for mental health professionals",
                    "key_feature": "Practice crisis intervention, boundaries, cultural sensitivity",
                },
                {
                    "title": "Night School",
                    "description": "Little Nate learns from every session to get better",
                    "key_feature": "Wisdom versioning, coach-supervised learning",
                },
            ],
            "stats": stats,
            "tiers": [
                {"name": "Threshold", "price": "Free Trial", "duration": "7 days"},
                {"name": "Inner Chamber", "price": "$49/mo", "features": "Unlimited sessions"},
                {"name": "Sovereign Circle", "price": "$149/mo", "features": "Live coaching + all features"},
            ],
        }

    # ── Private Methods ──────────────────────────────────────────────

    def _build_session_slides(self, data: Dict) -> List[Dict]:
        """Build slide data for a session showcase."""
        slides = [
            {"title": data["title"], "subtitle": data["description"], "type": "title"},
        ]
        for exchange in data["exchanges"]:
            slides.append({
                "type": "chat_bubble",
                "sender": exchange["sender"],
                "text": exchange["text"],
                "sender_label": data["client_name"] if exchange["sender"] == "client" else "Little Nate",
            })
        slides.append({
            "type": "metrics",
            "title": "Session Insights",
            "metrics": data["metrics"],
        })
        slides.append({
            "type": "cta",
            "text": "Experience this yourself",
            "url": "https://app.sovereignsanctuary.net",
        })
        return slides

    def _build_coach_slides(self, data: Dict) -> List[Dict]:
        """Build slide data for a coach demo."""
        slides = [
            {"title": data["title"], "subtitle": data["description"], "type": "title"},
            {"type": "scenario", "title": data["dojo_type"],
             "description": data["scenario_desc"]},
        ]
        for exchange in data["exchanges"]:
            slides.append({
                "type": "chat_bubble",
                "sender": exchange["sender"],
                "text": exchange["text"],
                "sender_label": "AI Persona" if exchange["sender"] == "persona" else data["coach_name"],
            })
        slides.append({
            "type": "results",
            "title": "DOJO Results",
            "scores": data["dojo_results"],
        })
        return slides

    def _build_family_slides(self, data: Dict) -> List[Dict]:
        """Build slide data for family showcase."""
        slides = [
            {"title": data["title"], "subtitle": data["description"], "type": "title"},
            {"type": "family_tree", "members": data["members"]},
        ]
        for highlight in data["highlights"]:
            slides.append({"type": "highlight", "text": highlight})
        return slides

    async def _get_platform_stats(self) -> Dict:
        """Get real platform stats if available."""
        try:
            async with self.db_pool.acquire() as conn:
                users = await conn.fetchrow("""
                    SELECT
                        COUNT(*) FILTER (WHERE role = 'client') as clients,
                        COUNT(*) FILTER (WHERE role = 'coach') as coaches
                    FROM users
                """)
                return {
                    "total_clients": users["clients"] if users else 0,
                    "total_coaches": users["coaches"] if users else 0,
                }
        except Exception:
            return {"total_clients": 0, "total_coaches": 0}

    async def _generate_narration(self, prompt: str) -> str:
        """Generate narration text using AI."""
        if not NATE_CHAT_KEY:
            return "Narration unavailable — AI not configured."

        messages = [
            {"role": "system", "content": "You are writing marketing narration for Sovereign Sanctuary."},
            {"role": "user", "content": prompt},
        ]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(NATE_CHAT_URL,
                                        json=nate_chat_payload(messages, max_tokens=200),
                                        headers=nate_chat_headers(),
                                        timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "")
            return "Narration generation failed."
        except Exception as e:
            logger.error(f"Narration generation error: {e}")
            return "Narration unavailable."
