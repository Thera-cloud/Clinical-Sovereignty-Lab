"""
Me-2-Me Platinum — Avatar Core
Identity-locked response generation engine.
The avatar responds as the member would have, locked to an Identity Crystal version.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.me2me import AvatarCore, AvatarStatus, ConsentLevel
from app.services.me2me.constants import (
    AVATAR_GRIEF_COOLDOWN_MINUTES,
    AVATAR_GRIEF_LEVEL_THRESHOLD,
    AVATAR_MAX_SESSION_DURATION_MINUTES,
    AVATAR_RESPONSE_MAX_TOKENS,
    ETHICAL_BOUNDARIES,
)

logger = logging.getLogger("me2me.avatar_core")


class AvatarCoreService:
    """
    Identity-locked response generation.
    Always discloses AI nature. Never claims to be alive.
    Monitors grief levels in visitors.
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

    async def activate_avatar(self, user_id: str) -> Optional[AvatarCore]:
        """Activate a Me-2-Me avatar for a user."""
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.INTERACT
            )
            if not has_consent:
                logger.warning("Avatar activation denied: no INTERACT consent for user %s", user_id)
                return None

        # Lock to current crystal version at activation time
        locked_crystal_version = None
        if self._vault:
            crystal = await self._vault.retrieve_crystal(user_id)
            if crystal:
                locked_crystal_version = crystal.get("crystal_version")
                confidence = crystal.get("confidence_score", 0.0)
                if confidence < 0.3:
                    logger.warning(
                        "Avatar activation: low crystal confidence (%.2f) for user %s",
                        confidence, user_id,
                    )

        avatar = AvatarCore(
            user_id=user_id,
            status=AvatarStatus.ACTIVE,
            activation_date=datetime.utcnow(),
            grief_monitoring_active=True,
            ethical_boundaries=ETHICAL_BOUNDARIES,
            crystal_version_locked=locked_crystal_version or 0,
        )

        if self._db:
            try:
                import json
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_avatars
                        (avatar_id, user_id, status, activation_date, grief_monitoring_active,
                         ethical_boundaries, crystal_version_locked)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        avatar.avatar_id, user_id, avatar.status.value,
                        avatar.activation_date, True,
                        json.dumps(ETHICAL_BOUNDARIES),
                        locked_crystal_version or 0,
                    )
            except Exception as e:
                logger.error("Avatar activation persistence failed: %s", e)

        logger.info("Avatar activated: user=%s avatar=%s", user_id, avatar.avatar_id)
        return avatar

    async def generate_response(
        self,
        avatar_id: str,
        visitor_id: str,
        visitor_message: str,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate an avatar response to a visitor's message."""
        avatar = await self._get_avatar(avatar_id)
        if not avatar or avatar.status != AvatarStatus.ACTIVE:
            return None

        # Load the locked identity crystal
        crystal = await self._load_crystal(avatar)
        if not crystal:
            return {"response": "I'm not fully ready yet. Please check back later.", "grief_level": 0.0}

        # Generate response using Sovereign Mind with crystal constraints
        response_text = ""
        if self._sovereign_mind:
            try:
                response_text = await self._sovereign_mind.generate(
                    prompt=(
                        f"You are speaking as {avatar.display_name}'s Me-2-Me avatar. "
                        f"Respond as they would have responded, based on their identity crystal. "
                        f"IMPORTANT: You must never claim to be alive. You must acknowledge "
                        f"you are an AI representation. The visitor said: {visitor_message}"
                    ),
                    context={
                        "crystal": crystal,
                        "visitor_relationship": session_context.get("relationship", "unknown") if session_context else "unknown",
                    },
                )
            except Exception as e:
                logger.error("Avatar response generation failed: %s", e)
                response_text = "I'm having trouble finding the right words right now."

        # Assess grief level in the visitor
        grief_level = self._assess_grief(visitor_message)

        # Grief monitoring
        if grief_level > AVATAR_GRIEF_LEVEL_THRESHOLD:
            response_text += (
                "\n\nI can sense this is really hard for you right now. "
                "It's okay to take a break. I'll be here whenever you're ready."
            )

        # Update interaction count
        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        "UPDATE me2me_avatars SET total_interactions = total_interactions + 1 WHERE avatar_id = $1",
                        avatar_id,
                    )
            except Exception:
                pass

        return {
            "response": response_text,
            "grief_level": grief_level,
            "grief_cooldown": grief_level > AVATAR_GRIEF_LEVEL_THRESHOLD,
            "avatar_name": avatar.display_name,
        }

    def _assess_grief(self, message: str) -> float:
        """Assess grief indicators in a visitor's message."""
        grief_markers = [
            "miss you", "wish you were here", "can't believe you're gone",
            "it hurts", "why did you leave", "not fair", "crying",
            "come back", "never see you again", "so lonely without you",
        ]
        lower = message.lower()
        count = sum(1 for marker in grief_markers if marker in lower)
        return min(count * 0.25, 1.0)

    async def _get_avatar(self, avatar_id: str) -> Optional[AvatarCore]:
        if not self._db:
            return None
        try:
            async with self._db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM me2me_avatars WHERE avatar_id = $1", avatar_id,
                )
                if row:
                    avatar = AvatarCore(
                        avatar_id=row["avatar_id"],
                        user_id=row["user_id"],
                        display_name=row.get("display_name", ""),
                        status=AvatarStatus(row.get("status", "inactive")),
                        activation_date=row.get("activation_date"),
                        grief_monitoring_active=row.get("grief_monitoring_active", True),
                        crystal_version_locked=row.get("crystal_version_locked", 0),
                    )
                    return avatar
        except Exception as e:
            logger.error("Avatar query failed: %s", e)
        return None

    async def _load_crystal(self, avatar: AvatarCore) -> Optional[Dict[str, Any]]:
        if self._vault:
            locked_version = avatar.crystal_version_locked if avatar.crystal_version_locked > 0 else None
            return await self._vault.retrieve_crystal(
                avatar.user_id, version=locked_version
            )
        return None
