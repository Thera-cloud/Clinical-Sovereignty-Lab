"""
Me-2-Me Platinum — Identity Crystallizer
Monthly synthesis of all accumulated imprints into an Identity Crystal.
The crystal captures personality, language, humor, values, and patterns.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.me2me import (
    ConsentLevel,
    HumorProfile,
    IdentityCrystal,
    LanguageSignature,
    PersonalityProfile,
)
from app.services.me2me.constants import (
    CRYSTAL_CONFIDENCE_MINIMUM,
    CRYSTAL_MIN_IMPRINTS,
    CRYSTAL_MIN_SESSIONS,
)

logger = logging.getLogger("me2me.identity_crystallizer")


class IdentityCrystallizer:
    """
    Synthesizes accumulated imprints into an Identity Crystal.
    Runs monthly (configurable). Requires PRESERVE consent level.
    """

    def __init__(
        self,
        consent_service=None,
        vault=None,
        sovereign_mind=None,
        db_pool=None,
    ):
        self._consent = consent_service
        self._vault = vault
        self._sovereign_mind = sovereign_mind
        self._db = db_pool

    async def synthesize(self, user_id: str) -> Optional[IdentityCrystal]:
        """Synthesize a new Identity Crystal from accumulated imprints."""
        # Check consent
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.PRESERVE
            )
            if not has_consent:
                logger.info("Crystal synthesis skipped: no PRESERVE consent for user %s", user_id)
                return None

        # Get data points
        imprints = await self._load_unprocessed_imprints(user_id)
        session_count = await self._get_session_count(user_id)

        if len(imprints) < CRYSTAL_MIN_IMPRINTS:
            logger.info("Not enough imprints for crystal: user=%s count=%d", user_id, len(imprints))
            return None

        # Get current crystal version
        current_version = await self._get_latest_version(user_id)
        new_version = current_version + 1

        # Synthesize components
        personality = await self._synthesize_personality(imprints)
        language = await self._synthesize_language(imprints)
        humor = await self._synthesize_humor(imprints)
        values = self._extract_values(imprints)
        themes = self._extract_life_themes(imprints)

        # Compute confidence
        confidence = min(
            len(imprints) / (CRYSTAL_MIN_IMPRINTS * 3),
            session_count / (CRYSTAL_MIN_SESSIONS * 3),
            1.0,
        )

        crystal = IdentityCrystal(
            user_id=user_id,
            crystal_version=new_version,
            personality=personality,
            language=language,
            humor=humor,
            core_values=values,
            life_themes=themes,
            confidence_score=confidence,
            data_points_used=len(imprints),
            sessions_analyzed=session_count,
        )

        # Generate narrative using Sovereign Mind
        if self._sovereign_mind and confidence >= CRYSTAL_CONFIDENCE_MINIMUM:
            try:
                narrative = await self._sovereign_mind.generate(
                    prompt="Synthesize a growth narrative for this identity crystal",
                    context={
                        "personality": personality.model_dump(),
                        "values": values,
                        "themes": themes,
                        "sessions": session_count,
                    },
                )
                crystal.growth_narrative = narrative or ""
            except Exception as e:
                logger.warning("Narrative generation failed: %s", e)

        # Store in vault
        if self._vault:
            await self._vault.store_crystal(user_id, crystal.model_dump())

        # Mark imprints as processed
        await self._mark_processed(user_id, [i["entry_id"] for i in imprints])

        logger.info(
            "Identity crystal synthesized: user=%s version=%d confidence=%.2f data_points=%d",
            user_id, new_version, confidence, len(imprints),
        )
        return crystal

    # -------------------------------------------------------------------------
    # SYNTHESIS COMPONENTS
    # -------------------------------------------------------------------------

    async def _synthesize_personality(
        self, imprints: List[Dict]
    ) -> PersonalityProfile:
        """Synthesize personality profile from imprints."""
        profile = PersonalityProfile()
        emotion_counts = {}
        for imp in imprints:
            for emotion in imp.get("emotions", []):
                emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1

        # Map emotions to Big Five dimensions
        total = max(sum(emotion_counts.values()), 1)
        profile.neuroticism = min(
            (emotion_counts.get("anxiety", 0) + emotion_counts.get("sadness", 0)) / total * 2, 1.0
        )
        profile.extraversion = min(
            (emotion_counts.get("joy", 0) + emotion_counts.get("excitement", 0)) / total * 2, 1.0
        )
        profile.agreeableness = min(
            (emotion_counts.get("gratitude", 0) + emotion_counts.get("compassion", 0)) / total * 2, 1.0
        )
        profile.openness = min(len(set(
            t for imp in imprints for t in imp.get("themes", [])
        )) / 20, 1.0)

        return profile

    async def _synthesize_language(
        self, imprints: List[Dict]
    ) -> LanguageSignature:
        """Synthesize language signature from imprints."""
        sig = LanguageSignature()

        all_words: List[str] = []
        phrase_counts: Dict[str, int] = {}
        total_sentence_lengths: List[int] = []

        for imp in imprints:
            content = imp.get("content", imp.get("content_hash", ""))
            if not content or len(content) < 5:
                continue

            words = content.split()
            all_words.extend(words)

            # Track average word length → vocabulary complexity
            word_lengths = [len(w.strip(".,!?;:\"'")) for w in words if len(w) > 1]
            if word_lengths:
                total_sentence_lengths.append(sum(word_lengths) / len(word_lengths))

            # Track recurring 2-3 word phrases
            for n in (2, 3):
                for i in range(len(words) - n + 1):
                    phrase = " ".join(words[i:i + n]).lower().strip(".,!?;:\"'")
                    if len(phrase) > 4:
                        phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1

        # Average word length → sentence complexity (0-1 scale)
        if total_sentence_lengths:
            avg_word_len = sum(total_sentence_lengths) / len(total_sentence_lengths)
            sig.sentence_complexity = min(avg_word_len / 8.0, 1.0)

        # Average words per utterance → formality / verbosity indicator
        if all_words:
            avg_utterance_len = len(all_words) / max(len(imprints), 1)
            # Map utterance length to formality preference (0-1)
            sig.formality_preference = round(min(avg_utterance_len / 50, 1.0), 2)

        # Signature phrases (recurring phrases with count > 2) → favorite_phrases
        sig.favorite_phrases = sorted(
            [p for p, c in phrase_counts.items() if c >= 2],
            key=lambda p: phrase_counts[p],
            reverse=True,
        )[:20]

        # Vocabulary diversity (unique / total ratio) → emotional_vocabulary_range
        if all_words:
            unique = set(w.lower() for w in all_words)
            sig.emotional_vocabulary_range = round(len(unique) / len(all_words), 4)

        return sig

    async def _synthesize_humor(
        self, imprints: List[Dict]
    ) -> HumorProfile:
        """Synthesize humor profile from imprints."""
        profile = HumorProfile()

        # Humor marker patterns
        humor_markers = {
            "self_deprecating": ["haha about me", "i'm such a", "i'm the worst at", "laugh at myself"],
            "observational": ["have you noticed", "isn't it funny how", "the irony is"],
            "dark": ["might as well laugh", "if i didn't laugh", "comedy and tragedy"],
            "playful": ["haha", "lol", "lmao", "just kidding", "joking", "😂"],
            "sarcastic": ["oh great", "wonderful", "just my luck", "yeah right", "totally"],
        }

        marker_counts: Dict[str, int] = {}
        total_humor_instances = 0

        for imp in imprints:
            content = (imp.get("content", imp.get("content_hash", "")) or "").lower()
            for style, markers in humor_markers.items():
                for marker in markers:
                    if marker in content:
                        marker_counts[style] = marker_counts.get(style, 0) + 1
                        total_humor_instances += 1

        if total_humor_instances > 0:
            sarcasm_count = marker_counts.get("sarcastic", 0)
            self_dep_count = marker_counts.get("self_deprecating", 0)
            profile.sarcasm_frequency = round(sarcasm_count / max(total_humor_instances, 1), 2)
            profile.self_deprecation_level = round(self_dep_count / max(total_humor_instances, 1), 2)
            # Dominant humor style
            if marker_counts:
                dominant = max(marker_counts, key=marker_counts.get)
                profile.humor_style = dominant
            # Topic preferences from humor triggers
            profile.topic_preferences = list(marker_counts.keys())
            profile.humor_triggers = [
                m for style_markers in humor_markers.values()
                for m in style_markers
                if any(m in (imp.get("content", imp.get("content_hash", "")) or "").lower() for imp in imprints)
            ][:10]

        return profile

    def _extract_values(self, imprints: List[Dict]) -> List[str]:
        """Extract core values from imprint themes."""
        theme_counts = {}
        for imp in imprints:
            for theme in imp.get("themes", []):
                theme_counts[theme] = theme_counts.get(theme, 0) + 1
        sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        return [t for t, _ in sorted_themes[:10]]

    def _extract_life_themes(self, imprints: List[Dict]) -> List[str]:
        """Extract recurring life themes."""
        themes = set()
        for imp in imprints:
            themes.update(imp.get("themes", []))
        return list(themes)[:15]

    # -------------------------------------------------------------------------
    # DATA ACCESS
    # -------------------------------------------------------------------------

    async def _load_unprocessed_imprints(self, user_id: str) -> List[Dict]:
        if not self._db:
            return []
        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT entry_id, content, themes, emotions, c_emo_at_capture, gamma_at_capture, content_hash
                    FROM me2me_imprint_entries
                    WHERE user_id = $1 AND processed = FALSE
                    ORDER BY captured_at ASC""",
                    user_id,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Imprint loading failed: %s", e)
            return []

    async def _get_session_count(self, user_id: str) -> int:
        if not self._db:
            return 0
        try:
            async with self._db.acquire() as conn:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM sessions WHERE client_id = $1", user_id,
                ) or 0
        except Exception:
            return 0

    async def _get_latest_version(self, user_id: str) -> int:
        if not self._db:
            return 0
        try:
            async with self._db.acquire() as conn:
                return await conn.fetchval(
                    """SELECT COALESCE(MAX(crystal_version), 0) FROM me2me_identity_crystals
                    WHERE user_id = $1""",
                    user_id,
                ) or 0
        except Exception:
            return 0

    async def _mark_processed(self, user_id: str, entry_ids: List[str]) -> None:
        if not self._db or not entry_ids:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    "UPDATE me2me_imprint_entries SET processed = TRUE WHERE entry_id = ANY($1)",
                    entry_ids,
                )
        except Exception as e:
            logger.error("Marking processed failed: %s", e)
