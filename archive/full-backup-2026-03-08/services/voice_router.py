"""
Voice Router — tier-based routing for Little Nate's voice pipeline.

Premium path (Sovereign Circle):
  Client audio → Azure OpenAI Realtime WS → [STT + LLM + TTS all-in-one] → Client audio
  Latency: <1s, highest quality, ~$0.06/min

Cheap path (Threshold, Inner Chamber, Standard):
  Client audio → Azure Whisper STT (nate-whisper) → text
                    → Grok/GPT Chat Completions → response text
                        → Edge TTS (free) → MP3 audio → Client
  Latency: 2-4s, good quality, ~$0.001/interaction

The router is a request-response service (not a background agent).
It receives audio or text, determines the user's tier, and routes
through the appropriate pipeline.
"""

import asyncio
import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

from app.services.nate_ai_config import (
    NATE_CHAT_URL,
    nate_chat_headers,
    nate_chat_payload,
)

_logger = logging.getLogger("voice_router")

PREMIUM_TIERS = frozenset({
    "TOP_TIER",
    "SOVEREIGN_CIRCLE",
})


class VoiceRouter:
    """
    Routes voice interactions through cheap or premium pipelines
    based on user subscription tier.
    """

    def __init__(self, db_pool=None, app_state=None):
        self._db = db_pool
        self._app_state = app_state

    def is_premium(self, tier: str) -> bool:
        return (tier or "").upper() in PREMIUM_TIERS

    async def process_voice_message(
        self,
        audio_data: bytes,
        *,
        user_id: str,
        tier: str = "STANDARD",
        content_type: str = "audio/webm",
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list] = None,
        voice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full voice pipeline: audio in → text response + audio out.

        Returns:
            {
                "transcript": str,       # what the user said
                "response_text": str,     # Nate's text response
                "audio_base64": str,      # base64 MP3 of Nate speaking
                "audio_content_type": str,
                "pipeline": str,          # "cheap" or "premium"
            }
        """
        if self.is_premium(tier):
            return {
                "transcript": None,
                "response_text": None,
                "audio_base64": None,
                "audio_content_type": None,
                "pipeline": "premium",
                "action": "use_realtime_ws",
            }

        transcript = await self._stt(audio_data, content_type=content_type)
        if not transcript:
            return {
                "transcript": None,
                "response_text": "I didn't catch that. Could you try again?",
                "audio_base64": None,
                "audio_content_type": "audio/mp3",
                "pipeline": "cheap",
            }

        response_text = await self._chat(
            transcript,
            system_prompt=system_prompt,
            conversation_history=conversation_history,
            user_id=user_id,
        )
        if not response_text:
            response_text = "I'm here with you. Let me think about that for a moment."

        audio_bytes = await self._tts(response_text, voice=voice)
        audio_b64 = base64.b64encode(audio_bytes).decode() if audio_bytes else None

        return {
            "transcript": transcript,
            "response_text": response_text,
            "audio_base64": audio_b64,
            "audio_content_type": "audio/mp3",
            "pipeline": "cheap",
        }

    async def process_text_to_speech(
        self,
        text: str,
        *,
        tier: str = "STANDARD",
        voice: Optional[str] = None,
    ) -> Optional[bytes]:
        """
        Text-only TTS: route to Edge TTS (cheap) or Azure TTS (premium).
        Returns raw audio bytes (MP3).
        """
        if self.is_premium(tier):
            return await self._tts_premium(text, voice=voice)
        return await self._tts(text, voice=voice)

    async def process_speech_to_text(
        self,
        audio_data: bytes,
        *,
        content_type: str = "audio/webm",
    ) -> Optional[str]:
        """STT only — always uses Azure Whisper (cheap for all tiers)."""
        return await self._stt(audio_data, content_type=content_type)

    # ── STT (Azure Whisper — cheap) ──────────────────────────────────────────

    async def _stt(
        self, audio_data: bytes, content_type: str = "audio/webm"
    ) -> Optional[str]:
        try:
            from app.services.whisper_stt import transcribe
            return await transcribe(audio_data, content_type=content_type)
        except ImportError:
            _logger.warning("whisper_stt module not available")
            return None
        except Exception as e:
            _logger.warning("STT failed: %s", e)
            return None

    # ── Chat (Grok via Azure AI — already cheap) ─────────────────────────────

    async def _chat(
        self,
        user_text: str,
        *,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        if not system_prompt:
            system_prompt = (
                "You are Little Nate, a warm, insightful AI therapy companion. "
                "You speak with gentle wisdom. Keep responses concise (2-3 sentences) "
                "since they will be spoken aloud."
            )

        messages = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            messages.extend(conversation_history[-6:])

        messages.append({"role": "user", "content": user_text})

        payload = nate_chat_payload(
            messages=messages,
            max_tokens=300,
            user_id=user_id,
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    NATE_CHAT_URL,
                    headers=nate_chat_headers(),
                    json=payload,
                )

            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()

            _logger.warning("Chat failed: HTTP %d", resp.status_code)
            return None

        except Exception as e:
            _logger.warning("Chat error: %s", e)
            return None

    # ── TTS cheap (Edge TTS — free) ──────────────────────────────────────────

    async def _tts(
        self, text: str, voice: Optional[str] = None
    ) -> Optional[bytes]:
        try:
            from app.services.edge_tts_service import synthesize
            return await synthesize(text, voice=voice)
        except ImportError:
            _logger.warning("edge_tts_service not available — install edge-tts")
            return None
        except Exception as e:
            _logger.warning("Edge TTS failed: %s", e)
            return None

    # ── TTS premium (Azure gpt-4o-mini-tts) ──────────────────────────────────

    async def _tts_premium(
        self, text: str, voice: Optional[str] = None
    ) -> Optional[bytes]:
        endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
        deployment = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")
        api_key = os.getenv("AZURE_API_KEY", "")

        if not all([endpoint, deployment, api_key]):
            _logger.warning("Azure TTS not configured, falling back to Edge TTS")
            return await self._tts(text, voice=voice)

        url = (
            f"https://{endpoint}/openai/deployments/{deployment}"
            f"/audio/speech?api-version=2024-12-17"
        )

        tts_voice = voice or "echo"
        payload = {
            "model": deployment,
            "input": text,
            "voice": tts_voice,
            "response_format": "mp3",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )

            if resp.status_code == 200:
                return resp.content

            _logger.warning("Azure TTS failed: HTTP %d — %s", resp.status_code, resp.text[:200])
            return await self._tts(text, voice=voice)

        except Exception as e:
            _logger.warning("Azure TTS error: %s, falling back to Edge TTS", e)
            return await self._tts(text, voice=voice)
