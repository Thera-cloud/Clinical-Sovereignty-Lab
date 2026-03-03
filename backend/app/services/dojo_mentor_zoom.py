"""
LITTLE NATE — DOJO Mentor Zoom Integration
Creates Zoom meetings with audio streaming for real-time mentor coaching.
Bridges Zoom audio to Azure OpenAI Realtime for transcription, then
routes transcripts to the DojoMentorEngine for mentor response generation.
"""

import os
import json
import asyncio
import logging
from typing import Dict, Optional, List

import httpx

logger = logging.getLogger("nate.dojo_mentor_zoom")

ZOOM_API_BASE = "https://api.zoom.us/v2"
ZOOM_ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "")
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")


class DojoMentorZoom:
    """Manages Zoom meetings for DOJO-mentored coaching sessions."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._access_token: Optional[str] = None
        self._token_expires: float = 0
        self._active_sessions: Dict[str, dict] = {}

    async def _ensure_token(self):
        """Get or refresh Zoom OAuth token (Server-to-Server)."""
        import time
        if self._access_token and time.time() < self._token_expires - 60:
            return

        if not ZOOM_ACCOUNT_ID or not ZOOM_CLIENT_ID:
            logger.warning("Zoom credentials not configured")
            return

        import base64
        credentials = base64.b64encode(
            f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode()
        ).decode()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://zoom.us/oauth/token",
                params={"grant_type": "account_credentials", "account_id": ZOOM_ACCOUNT_ID},
                headers={"Authorization": f"Basic {credentials}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._access_token = data["access_token"]
                self._token_expires = time.time() + data.get("expires_in", 3600)
            else:
                logger.error("Zoom token refresh failed: %s", resp.text)

    async def create_mentored_meeting(
        self,
        coach_user_id: str,
        topic: str = "Coaching Session",
        session_mode: str = "coach_client",
        active_dojos: List[str] = None,
    ) -> Dict:
        """Create a Zoom meeting for a DOJO-mentored session."""
        await self._ensure_token()
        if not self._access_token:
            return {"error": "Zoom not configured"}

        dojo_labels = {
            "therapist": "Clinical",
            "judge": "Legal",
            "business": "Business",
            "mcat": "Medical",
            "cnc": "Manufacturing",
            "teacher": "Education",
            "project_pm": "Project Management",
        }
        dojo_suffix = ""
        if active_dojos:
            labels = [dojo_labels.get(d, d.title()) for d in active_dojos[:3]]
            dojo_suffix = f" ({' + '.join(labels)} Mentored)"

        meeting_config = {
            "topic": f"{topic}{dojo_suffix}",
            "type": 1,
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False,
                "mute_upon_entry": False,
                "waiting_room": True,
                "audio": "both",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{ZOOM_API_BASE}/users/me/meetings",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    json=meeting_config,
                )
                if resp.status_code in (200, 201):
                    meeting = resp.json()
                    return {
                        "meeting_id": str(meeting.get("id", "")),
                        "join_url": meeting.get("join_url", ""),
                        "start_url": meeting.get("start_url", ""),
                        "password": meeting.get("password", ""),
                        "topic": meeting.get("topic", ""),
                    }
                else:
                    logger.error("Zoom meeting creation failed: %s", resp.text)
                    return {"error": f"Zoom API error: {resp.status_code}"}
        except Exception as e:
            logger.error("Zoom meeting creation exception: %s", e)
            return {"error": str(e)}

    async def start_mentor_session(
        self,
        session_id: str,
        coach_user_id: str,
        client_user_id: Optional[str],
        session_mode: str,
        active_dojos: List[str],
        meeting_data: Dict,
    ):
        """Initialize a mentored session — stores state and starts audio bridge."""
        self._active_sessions[session_id] = {
            "coach_user_id": coach_user_id,
            "client_user_id": client_user_id,
            "session_mode": session_mode,
            "active_dojos": active_dojos,
            "meeting_id": meeting_data.get("meeting_id"),
            "transcript_buffer": [],
            "mentoring_active": True,
        }

        mentor_engine = getattr(self.app_state, "dojo_mentor_engine", None)
        if mentor_engine:
            await mentor_engine.start_session(
                session_id=session_id,
                coach_user_id=coach_user_id,
                client_user_id=client_user_id,
                session_mode=session_mode,
                active_dojos=active_dojos,
                zoom_meeting_id=meeting_data.get("meeting_id"),
            )

        logger.info(
            "DOJO mentor session started: session=%s coach=%s mode=%s dojos=%s",
            session_id, coach_user_id, session_mode, active_dojos,
        )

    async def process_transcript_chunk(
        self,
        session_id: str,
        transcript: str,
        coach_question: Optional[str] = None,
    ) -> Optional[str]:
        """Process a transcript chunk and generate a mentor response."""
        session = self._active_sessions.get(session_id)
        if not session or not session.get("mentoring_active"):
            return None

        session["transcript_buffer"].append(transcript)

        mentor_engine = getattr(self.app_state, "dojo_mentor_engine", None)
        if not mentor_engine:
            return None

        client_context = {}
        if session.get("client_user_id"):
            client_context = await mentor_engine.get_client_context(session["client_user_id"])

        response = await mentor_engine.generate_mentor_response(
            active_dojos=session["active_dojos"],
            client_context=client_context,
            session_mode=session["session_mode"],
            transcript_chunk=transcript,
            coach_question=coach_question,
        )

        if response:
            dojo_lens = session["active_dojos"][0] if session["active_dojos"] else "general"
            interaction_type = "answer" if coach_question else "observation"
            await mentor_engine.record_interaction(
                session_id=session_id,
                interaction_type=interaction_type,
                content=response,
                dojo_lens=dojo_lens,
                coach_question=coach_question,
            )

        return response

    async def toggle_dojo(self, session_id: str, dojo: str, active: bool):
        """Toggle a DOJO lens on/off during a live session."""
        session = self._active_sessions.get(session_id)
        if not session:
            return

        if active and dojo not in session["active_dojos"]:
            session["active_dojos"].append(dojo)
        elif not active and dojo in session["active_dojos"]:
            session["active_dojos"].remove(dojo)

        logger.info("DOJO toggled: session=%s dojo=%s active=%s dojos=%s",
                     session_id, dojo, active, session["active_dojos"])

    async def end_mentor_session(self, session_id: str):
        """End a mentored session."""
        session = self._active_sessions.pop(session_id, None)
        if not session:
            return

        mentor_engine = getattr(self.app_state, "dojo_mentor_engine", None)
        if mentor_engine:
            await mentor_engine.end_session(session_id)

        logger.info("DOJO mentor session ended: session=%s", session_id)
