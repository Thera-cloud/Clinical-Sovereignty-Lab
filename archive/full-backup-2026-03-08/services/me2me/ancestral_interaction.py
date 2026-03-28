"""
Me-2-Me Platinum — Ancestral Interaction Engine
Manages visitor sessions with Me-2-Me avatars.
Includes grief monitoring and session management.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.me2me.constants import (
    AVATAR_GRIEF_COOLDOWN_MINUTES,
    AVATAR_GRIEF_LEVEL_THRESHOLD,
    AVATAR_MAX_SESSION_DURATION_MINUTES,
    ETHICAL_BOUNDARIES,
)

logger = logging.getLogger("me2me.ancestral_interaction")


class AncestralInteractionEngine:
    """
    Manages visitor sessions with Me-2-Me avatars.
    Handles session lifecycle, grief monitoring, and ethical boundaries.
    """

    def __init__(self, avatar_service=None, consent_service=None, db_pool=None):
        self._avatar = avatar_service
        self._consent = consent_service
        self._db = db_pool
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    async def start_session(
        self,
        avatar_id: str,
        visitor_id: str,
        visitor_relationship: str = "",
    ) -> Dict[str, Any]:
        """Start a visitor session with a Me-2-Me avatar."""
        from uuid import uuid4
        session_id = str(uuid4())

        session = {
            "session_id": session_id,
            "avatar_id": avatar_id,
            "visitor_id": visitor_id,
            "visitor_relationship": visitor_relationship,
            "started_at": datetime.utcnow(),
            "messages": [],
            "grief_level": 0.0,
            "grief_cooldown_triggered": False,
            "interaction_count": 0,
        }
        self._active_sessions[session_id] = session

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_visitor_sessions
                        (session_id, avatar_id, visitor_id, visitor_relationship)
                        VALUES ($1, $2, $3, $4)""",
                        session_id, avatar_id, visitor_id, visitor_relationship,
                    )
            except Exception as e:
                logger.error("Session start persistence failed: %s", e)

        # Opening message
        opening = (
            f"Hello. I'm glad you're here. Just so you know — I'm an AI "
            f"representation, not the person themselves. But I carry their words, "
            f"their humor, and the way they saw the world. "
            f"What would you like to talk about?"
        )

        session["messages"].append({
            "role": "avatar",
            "content": opening,
            "timestamp": datetime.utcnow().isoformat(),
        })

        logger.info("Visitor session started: session=%s avatar=%s visitor=%s",
                     session_id, avatar_id, visitor_id)

        return {"session_id": session_id, "opening": opening}

    async def send_message(
        self, session_id: str, message: str
    ) -> Optional[Dict[str, Any]]:
        """Send a message to the avatar in an active session."""
        session = self._active_sessions.get(session_id)
        if not session:
            return None

        # Check session duration
        elapsed = (datetime.utcnow() - session["started_at"]).total_seconds() / 60
        if elapsed > AVATAR_MAX_SESSION_DURATION_MINUTES:
            return await self._end_session_timeout(session)

        # Check interaction limit
        max_interactions = ETHICAL_BOUNDARIES.get("max_consecutive_interactions", 10)
        if session["interaction_count"] >= max_interactions:
            return {
                "response": (
                    "We've been talking for a while. It might be good to take a break "
                    "and let this conversation settle. I'll be here whenever you're ready to come back."
                ),
                "session_ended": True,
                "reason": "interaction_limit",
            }

        # Check grief cooldown
        if session.get("grief_cooldown_triggered"):
            return {
                "response": (
                    "I think it would be good to take a moment. This is important "
                    "and emotional, and it's okay to step away. I'll be here."
                ),
                "grief_cooldown": True,
            }

        # Record visitor message
        session["messages"].append({
            "role": "visitor",
            "content": message,
            "timestamp": datetime.utcnow().isoformat(),
        })
        session["interaction_count"] += 1

        # Generate avatar response
        if self._avatar:
            result = await self._avatar.generate_response(
                avatar_id=session["avatar_id"],
                visitor_id=session["visitor_id"],
                visitor_message=message,
                session_context={"relationship": session.get("visitor_relationship", "")},
            )
            if result:
                session["messages"].append({
                    "role": "avatar",
                    "content": result["response"],
                    "timestamp": datetime.utcnow().isoformat(),
                })
                session["grief_level"] = result.get("grief_level", 0.0)

                if result.get("grief_cooldown"):
                    session["grief_cooldown_triggered"] = True

                return result

        return {"response": "I'm having trouble finding the right words.", "grief_level": 0.0}

    async def end_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """End a visitor session."""
        session = self._active_sessions.pop(session_id, None)
        if not session:
            return None

        duration = int((datetime.utcnow() - session["started_at"]).total_seconds())

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """UPDATE me2me_visitor_sessions SET
                            ended_at = NOW(),
                            messages = $1,
                            grief_level = $2,
                            grief_cooldown_triggered = $3,
                            duration_seconds = $4
                        WHERE session_id = $5""",
                        str(session["messages"]),
                        session["grief_level"],
                        session.get("grief_cooldown_triggered", False),
                        duration,
                        session_id,
                    )
            except Exception as e:
                logger.error("Session end persistence failed: %s", e)

        logger.info(
            "Visitor session ended: session=%s duration=%ds messages=%d grief=%.2f",
            session_id, duration, len(session["messages"]), session["grief_level"],
        )
        return {"session_id": session_id, "duration_seconds": duration}

    async def _end_session_timeout(self, session: Dict) -> Dict[str, Any]:
        """End a session due to timeout."""
        session_id = session["session_id"]
        await self.end_session(session_id)
        return {
            "response": (
                "We've been talking for a while, and I think it's a good time "
                "to pause. Take care of yourself. I'll always be here."
            ),
            "session_ended": True,
            "reason": "timeout",
        }
