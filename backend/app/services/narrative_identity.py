"""
Therapeutic Identity Inference Engine — Phase 3: Narrative Identity Profile.

Builds identity from therapeutic content: recurring themes, attachment style,
known stories, relationship patterns, and emotional vocabulary.
Uses crystal history as the primary data source.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("nate.narrative_identity")

ATTACHMENT_INDICATORS = {
    "anxious": [
        "afraid you'll leave", "are you still there", "don't abandon me",
        "need reassurance", "clingy", "can't be alone", "constantly checking",
        "fear of rejection", "jealous", "possessive",
    ],
    "avoidant": [
        "don't need anyone", "i'm fine alone", "too close", "suffocating",
        "need space", "independent", "walls up", "don't trust", "keep distance",
        "commitment", "trapped",
    ],
    "disorganized": [
        "push and pull", "want you close but", "hot and cold",
        "love and hate", "scared of intimacy", "chaos", "unpredictable",
        "don't know what i want", "sabotage",
    ],
    "secure": [
        "trust", "safe with", "comfortable", "open up", "vulnerable",
        "connected", "balanced", "mutual", "healthy boundary",
    ],
}

THEME_CATEGORIES = {
    "abandonment": ["left me", "abandoned", "walked away", "disappeared", "ghosted", "alone"],
    "control": ["can't control", "out of control", "controlling", "powerless", "helpless", "trapped"],
    "shame": ["ashamed", "worthless", "not good enough", "embarrassed", "humiliated", "defective"],
    "betrayal": ["betrayed", "lied to", "cheated", "stabbed in the back", "broken trust"],
    "loss": ["lost", "grief", "died", "gone", "miss them", "funeral", "death"],
    "identity": ["don't know who i am", "lost myself", "identity", "who am i", "purpose"],
    "rage": ["furious", "rage", "hate", "want to hurt", "anger", "explode"],
    "safety": ["unsafe", "danger", "threat", "scared", "hypervigilant", "can't relax"],
}


@dataclass
class NarrativeProfile:
    """Therapeutic narrative identity for one user."""
    user_id: str
    attachment_scores: Dict[str, float] = field(default_factory=lambda: {
        "anxious": 0.0, "avoidant": 0.0, "disorganized": 0.0, "secure": 0.0,
    })
    dominant_attachment: str = "unknown"
    recurring_themes: Dict[str, float] = field(default_factory=dict)
    known_stories: List[Dict[str, Any]] = field(default_factory=list)
    emotional_vocabulary: Dict[str, int] = field(default_factory=dict)
    relationship_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    metaphor_preferences: List[str] = field(default_factory=list)
    deflection_patterns: List[str] = field(default_factory=list)
    session_count: int = 0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "attachment_scores": self.attachment_scores,
            "dominant_attachment": self.dominant_attachment,
            "recurring_themes": self.recurring_themes,
            "known_stories": self.known_stories[-20:],
            "emotional_vocabulary": dict(
                sorted(self.emotional_vocabulary.items(), key=lambda x: x[1], reverse=True)[:50]
            ),
            "relationship_map": self.relationship_map,
            "metaphor_preferences": self.metaphor_preferences[-10:],
            "deflection_patterns": self.deflection_patterns[-10:],
            "session_count": self.session_count,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NarrativeProfile":
        p = cls(user_id=d.get("user_id", ""))
        p.attachment_scores = d.get("attachment_scores", p.attachment_scores)
        p.dominant_attachment = d.get("dominant_attachment", "unknown")
        p.recurring_themes = d.get("recurring_themes", {})
        p.known_stories = d.get("known_stories", [])
        p.emotional_vocabulary = d.get("emotional_vocabulary", {})
        p.relationship_map = d.get("relationship_map", {})
        p.metaphor_preferences = d.get("metaphor_preferences", [])
        p.deflection_patterns = d.get("deflection_patterns", [])
        p.session_count = d.get("session_count", 0)
        p.updated_at = d.get("updated_at", 0.0)
        return p


class NarrativeIdentityEngine:
    """
    Builds narrative identity profiles from crystals and conversation history.

    The "blindfolded therapist" uses narrative identity to distinguish speakers
    even when voice characteristics are similar (e.g., siblings, twins).
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._profiles: Dict[str, NarrativeProfile] = {}

    async def load_profile(self, user_id: str) -> NarrativeProfile:
        if user_id in self._profiles:
            return self._profiles[user_id]

        profile = NarrativeProfile(user_id=user_id)
        if self._db:
            try:
                import json
                row = await self._db.fetchrow(
                    """SELECT themes, attachment_style, known_stories,
                              relationship_patterns, emotional_vocabulary,
                              turn_count, last_updated
                       FROM narrative_identity_profiles WHERE user_id = $1""",
                    user_id,
                )
                if row:
                    def _parse(val):
                        if val is None:
                            return None
                        if isinstance(val, str):
                            return json.loads(val)
                        return val

                    themes = _parse(row["themes"])
                    if isinstance(themes, dict):
                        profile.recurring_themes = themes
                    profile.dominant_attachment = row["attachment_style"] or "unknown"
                    if profile.dominant_attachment != "unknown":
                        profile.attachment_scores[profile.dominant_attachment] = 0.5
                    stories = _parse(row["known_stories"])
                    if isinstance(stories, list):
                        profile.known_stories = stories
                    evocab = _parse(row["emotional_vocabulary"])
                    if isinstance(evocab, dict):
                        profile.emotional_vocabulary = evocab
                    rel = _parse(row["relationship_patterns"])
                    if isinstance(rel, list):
                        for item in rel:
                            if isinstance(item, dict) and "name" in item:
                                profile.relationship_map[item["name"]] = item
                    profile.session_count = row["turn_count"] or 0
            except Exception as e:
                logger.warning("NarrativeIdentity: load failed for %s: %s", user_id, e)

        self._profiles[user_id] = profile
        return profile

    def analyze_turn(self, user_id: str, text: str) -> Dict[str, Any]:
        """Analyze a single conversation turn for narrative identity features."""
        profile = self._profiles.get(user_id)
        if not profile:
            profile = NarrativeProfile(user_id=user_id)
            self._profiles[user_id] = profile

        text_lower = text.lower()
        results: Dict[str, Any] = {}

        for style, indicators in ATTACHMENT_INDICATORS.items():
            hits = sum(1 for ind in indicators if ind in text_lower)
            if hits > 0:
                alpha = 0.05
                profile.attachment_scores[style] = (
                    profile.attachment_scores.get(style, 0.0) * (1 - alpha)
                    + min(hits * 0.2, 1.0) * alpha
                )

        max_style = max(profile.attachment_scores, key=profile.attachment_scores.get)
        if profile.attachment_scores[max_style] > 0.1:
            profile.dominant_attachment = max_style
            results["attachment_signal"] = max_style

        for theme, keywords in THEME_CATEGORIES.items():
            hits = sum(1 for kw in keywords if kw in text_lower)
            if hits > 0:
                old = profile.recurring_themes.get(theme, 0.0)
                profile.recurring_themes[theme] = old * 0.95 + hits * 0.05
                results.setdefault("themes_detected", []).append(theme)

        emotion_words = re.findall(
            r"\b(angry|sad|scared|happy|anxious|depressed|frustrated|lonely|"
            r"hopeless|overwhelmed|numb|guilty|ashamed|confused|hurt|"
            r"resentful|betrayed|jealous|grateful|proud|relieved)\b",
            text_lower,
        )
        for ew in emotion_words:
            profile.emotional_vocabulary[ew] = profile.emotional_vocabulary.get(ew, 0) + 1

        name_refs = re.findall(
            r"\b(?:my\s+)?(mother|father|mom|dad|wife|husband|partner|"
            r"sister|brother|daughter|son|boss|friend|therapist|ex)\b",
            text_lower,
        )
        for ref in name_refs:
            if ref not in profile.relationship_map:
                profile.relationship_map[ref] = {
                    "mention_count": 0,
                    "sentiment_sum": 0.0,
                    "themes": [],
                }
            profile.relationship_map[ref]["mention_count"] += 1

        if len(text) > 150 and any(kw in text_lower for kw in (
            "remember when", "there was this time", "back when",
            "it all started", "the story is", "what happened was",
        )):
            story_hash = hash(text_lower[:100])
            is_new = not any(s.get("hash") == story_hash for s in profile.known_stories)
            if is_new:
                detected_themes = [
                    t for t, kws in THEME_CATEGORIES.items()
                    if any(kw in text_lower for kw in kws)
                ]
                profile.known_stories.append({
                    "hash": story_hash,
                    "snippet": text[:200],
                    "themes": detected_themes,
                    "timestamp": time.time(),
                })
                results["new_story_detected"] = True

        profile.updated_at = time.time()
        return results

    def compare_profiles(
        self, current: NarrativeProfile, stored: NarrativeProfile,
    ) -> float:
        """
        Compare narrative profiles for identity matching.
        Weights: attachment 0.25, themes 0.30, vocabulary 0.25, relationships 0.20.
        """
        if stored.session_count < 3:
            return 0.0

        attach_sim = 1.0 - sum(
            abs(current.attachment_scores.get(s, 0) - stored.attachment_scores.get(s, 0))
            for s in ("anxious", "avoidant", "disorganized", "secure")
        ) / 4.0

        all_themes = set(current.recurring_themes) | set(stored.recurring_themes)
        if all_themes:
            theme_sim = 1.0 - sum(
                abs(current.recurring_themes.get(t, 0) - stored.recurring_themes.get(t, 0))
                for t in all_themes
            ) / max(len(all_themes), 1)
        else:
            theme_sim = 0.5

        common_vocab = set(current.emotional_vocabulary) & set(stored.emotional_vocabulary)
        all_vocab = set(current.emotional_vocabulary) | set(stored.emotional_vocabulary)
        vocab_sim = len(common_vocab) / max(len(all_vocab), 1) if all_vocab else 0.5

        common_rels = set(current.relationship_map) & set(stored.relationship_map)
        all_rels = set(current.relationship_map) | set(stored.relationship_map)
        rel_sim = len(common_rels) / max(len(all_rels), 1) if all_rels else 0.5

        return float(
            max(0, attach_sim) * 0.25
            + max(0, theme_sim) * 0.30
            + vocab_sim * 0.25
            + rel_sim * 0.20
        )

    async def persist(self, user_id: str) -> None:
        profile = self._profiles.get(user_id)
        if not profile or not self._db:
            return
        try:
            import json
            themes_json = json.dumps(profile.recurring_themes)
            stories_json = json.dumps(profile.known_stories[-20:])
            evocab_json = json.dumps(profile.emotional_vocabulary)
            rel_json = json.dumps(list(profile.relationship_map.values())[-20:])
            await self._db.execute(
                """INSERT INTO narrative_identity_profiles
                       (user_id, themes, attachment_style, known_stories,
                        relationship_patterns, emotional_vocabulary,
                        turn_count, last_updated)
                   VALUES ($1, $2::jsonb, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, NOW())
                   ON CONFLICT (user_id, tenant_id) DO UPDATE SET
                     themes = EXCLUDED.themes,
                     attachment_style = EXCLUDED.attachment_style,
                     known_stories = EXCLUDED.known_stories,
                     relationship_patterns = EXCLUDED.relationship_patterns,
                     emotional_vocabulary = EXCLUDED.emotional_vocabulary,
                     turn_count = EXCLUDED.turn_count,
                     last_updated = NOW()""",
                user_id, themes_json, profile.dominant_attachment,
                stories_json, rel_json, evocab_json,
                profile.session_count,
            )
        except Exception as e:
            logger.warning("NarrativeIdentity: persist failed for %s: %s", user_id, e)
