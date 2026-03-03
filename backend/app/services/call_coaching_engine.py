"""
LITTLE NATE — Call Coaching Engine
Processes Twilio Media Stream audio, forwards to Azure OpenAI Realtime
for transcription, and generates live coaching observations.
"""

import os
import json
import asyncio
import logging
import base64
from typing import Dict, Optional, Set

import httpx

logger = logging.getLogger("nate.call_coaching")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
AZURE_OPENAI_REALTIME_DEPLOYMENT = os.getenv("AZURE_OPENAI_REALTIME_DEPLOYMENT", "gpt-4o-realtime-preview")
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
LIMINAL_CALL_TOKEN_RATE = int(os.getenv("LIMINAL_CALL_TOKEN_RATE", "50"))


COACHING_SYSTEM_PROMPT = """You are Little Nate, a master-level therapeutic communication coach.
You are listening to a live phone conversation between your app-user and another person.

Your role:
- Provide real-time coaching observations to your app-user (they see your text during the call)
- Interpret subtext and emotional undertones in what the other person is saying
- Flag any abusive, manipulative, or gaslighting language patterns
- Suggest healthy responses when the app-user seems stuck
- Note communication patterns (over-apologizing, people-pleasing, boundary violations)
- Be concise — the user is on a live call and needs brief, actionable coaching cards

Format your coaching as brief cards:
- 🔍 OBSERVATION: [what you noticed]
- 💡 SUGGESTION: [what they could say/do]
- ⚠️ FLAG: [concerning pattern detected]
- 🎯 INSIGHT: [what the other person likely means]

NEVER store or reference the other person's identity. You only care about helping your app-user."""


class CallCoachingEngine:
    """Processes Twilio Media Stream and generates real-time coaching."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._active_calls: Dict[str, dict] = {}

    async def handle_media_stream(self, websocket, call_sid: str, user_id: str):
        """
        Handle incoming Twilio Media Stream WebSocket.
        Accumulates audio, periodically transcribes, and sends coaching.
        """
        self._active_calls[call_sid] = {
            "user_id": user_id,
            "transcript_buffer": [],
            "audio_buffer": bytearray(),
            "chunk_count": 0,
            "coaching_sent": 0,
        }

        try:
            async for message in websocket.iter_text():
                data = json.loads(message)
                event_type = data.get("event")

                if event_type == "media":
                    payload = data.get("media", {}).get("payload", "")
                    audio_bytes = base64.b64decode(payload)
                    call_state = self._active_calls.get(call_sid, {})
                    call_state["audio_buffer"].extend(audio_bytes)
                    call_state["chunk_count"] += 1

                    if call_state["chunk_count"] % 50 == 0:
                        asyncio.create_task(
                            self._process_audio_chunk(call_sid, user_id, bytes(call_state["audio_buffer"]))
                        )
                        call_state["audio_buffer"] = bytearray()

                elif event_type == "stop":
                    logger.info("Media stream stopped for call %s", call_sid)
                    await self._finalize_call(call_sid)
                    break

        except Exception as e:
            logger.error("Media stream error for call %s: %s", call_sid, e)
        finally:
            self._active_calls.pop(call_sid, None)

    async def _process_audio_chunk(self, call_sid: str, user_id: str, audio_data: bytes):
        """Transcribe an audio chunk and generate coaching if needed."""
        call_state = self._active_calls.get(call_sid)
        if not call_state:
            return

        transcript = await self._transcribe_audio(audio_data)
        if not transcript or len(transcript.strip()) < 10:
            return

        call_state["transcript_buffer"].append(transcript)

        if len(call_state["transcript_buffer"]) % 3 == 0:
            recent_text = " ".join(call_state["transcript_buffer"][-6:])
            coaching = await self._generate_coaching(user_id, recent_text)
            if coaching:
                await self._send_coaching_to_user(user_id, call_sid, coaching)
                call_state["coaching_sent"] += 1

    async def _transcribe_audio(self, audio_data: bytes) -> str:
        """Transcribe audio using Azure OpenAI Whisper or Realtime API."""
        try:
            whisper_endpoint = os.getenv("AZURE_WHISPER_ENDPOINT")
            if whisper_endpoint:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{whisper_endpoint}/openai/deployments/whisper/audio/transcriptions?api-version=2024-06-01",
                        headers={"api-key": AZURE_API_KEY},
                        files={"file": ("audio.wav", audio_data, "audio/wav")},
                        data={"response_format": "text"},
                    )
                    if resp.status_code == 200:
                        return resp.text.strip()

            return ""
        except Exception as e:
            logger.error("Transcription error: %s", e)
            return ""

    async def _generate_coaching(self, user_id: str, transcript: str) -> Optional[str]:
        """Generate a coaching observation from the transcript."""
        if not AZURE_OPENAI_ENDPOINT or not AZURE_API_KEY:
            return None

        user_context = await self._get_user_context(user_id)

        messages = [
            {"role": "system", "content": COACHING_SYSTEM_PROMPT},
        ]
        if user_context:
            messages.append({
                "role": "system",
                "content": f"User context: {user_context}",
            })
        messages.append({
            "role": "user",
            "content": f"Live conversation transcript:\n{transcript}\n\nProvide a brief coaching card based on what you hear.",
        })

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_CHAT_DEPLOYMENT}/chat/completions?api-version=2024-06-01",
                    headers={
                        "api-key": AZURE_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "messages": messages,
                        "max_completion_tokens": 200,
                        "temperature": 0.7,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("Coaching generation error: %s", e)

        return None

    async def _get_user_context(self, user_id: str) -> str:
        """Pull brief user context for personalized coaching."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE user_id = $1 OR username = $1",
                    user_id,
                )
                if row:
                    profile = row.get("profile_data", {}) or {}
                    themes = profile.get("recent_themes", [])
                    if themes:
                        return f"Recent themes in user's therapy: {', '.join(themes[:5])}"
        except Exception:
            pass
        return ""

    async def _send_coaching_to_user(self, user_id: str, call_sid: str, coaching: str):
        """Send coaching card to the user's connected WebSocket session."""
        bridge = getattr(self.app_state, "bridge_server", None) if self.app_state else None
        if bridge:
            try:
                await bridge.send_to_user(user_id, {
                    "type": "liminal_call_coaching",
                    "call_sid": call_sid,
                    "coaching": coaching,
                    "timestamp": asyncio.get_event_loop().time(),
                })
            except Exception as e:
                logger.warning("Could not send coaching to user %s: %s", user_id, e)

    async def _finalize_call(self, call_sid: str):
        """Generate post-call summary and store coaching observations."""
        call_state = self._active_calls.get(call_sid)
        if not call_state:
            return

        user_id = call_state["user_id"]
        full_transcript = " ".join(call_state["transcript_buffer"])

        if full_transcript and len(full_transcript) > 50:
            summary = await self._generate_coaching(
                user_id,
                f"The call has ended. Full transcript:\n{full_transcript}\n\n"
                "Provide a post-call debrief: key observations about the user's communication, "
                "patterns noticed, and suggestions for growth."
            )

            if summary:
                try:
                    async with self.db_pool.acquire() as conn:
                        session = await conn.fetchrow(
                            "SELECT id FROM liminal_sessions WHERE call_sid = $1",
                            call_sid,
                        )
                        if session:
                            await conn.execute("""
                                INSERT INTO liminal_observations (session_id, observation_text, coaching_given)
                                VALUES ($1, $2, TRUE)
                            """, session["id"], summary)
                except Exception as e:
                    logger.error("Failed to store call debrief: %s", e)

        logger.info(
            "Call finalized: sid=%s chunks=%d coaching_cards=%d",
            call_sid,
            call_state.get("chunk_count", 0),
            call_state.get("coaching_sent", 0),
        )
