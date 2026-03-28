"""
Voice Router — tier-based routing for Little Nate's voice pipeline.

LittleNate-1.X refactored pipeline:
  Premium path (Sovereign Circle):
    Client audio → LittleNate Realtime WS → [sovereign STT + Helix inference + coherence TTS]
    Falls back to Azure OpenAI Realtime WS if sovereign unavailable.

  Standard path (all other tiers):
    Client audio → Sovereign Whisper STT → text
                      → LittleNateInference (Helix + LLM) → response text
                          → Edge TTS (coherence-modulated) → MP3 audio → Client
    Falls back to Azure Whisper + Grok chat if sovereign pipeline unavailable.

The router is a request-response service (not a background agent).
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
    Routes voice interactions through the sovereign LittleNate-1.X pipeline
    with automatic fallback to Azure/Grok when sovereign is unavailable.
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
        Full voice pipeline: audio in -> text response + audio out.
        Routes through LittleNateInference when available,
        falls back to legacy Grok/Azure pipeline otherwise.
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

        felt_sense = "grounded"
        inference = getattr(self._app_state, "littlenate_inference", None) if self._app_state else None
        if inference and hasattr(inference, '_last_felt_sense'):
            felt_sense = getattr(inference, '_last_felt_sense', 'grounded')

        audio_bytes = await self._tts(response_text, voice=voice, felt_sense=felt_sense)
        audio_b64 = base64.b64encode(audio_bytes).decode() if audio_bytes else None

        return {
            "transcript": transcript,
            "response_text": response_text,
            "audio_base64": audio_b64,
            "audio_content_type": "audio/mp3",
            "pipeline": "sovereign" if inference else "cheap",
        }

    async def process_text_to_speech(
        self,
        text: str,
        *,
        tier: str = "STANDARD",
        voice: Optional[str] = None,
        tts_provider: str = "",
    ) -> Optional[bytes]:
        """
        Text-only TTS with user preference routing.

        tts_provider overrides tier-based routing:
          "edge_tts"        → Edge TTS directly
          "sovereign_xtts"  → XTTS-v2 voice clone
          "azure_premium"   → Azure gpt-4o-mini-tts
          ""                → tier-based (premium tier → Azure, otherwise → sovereign chain)
        """
        if tts_provider == "edge_tts":
            try:
                from app.services.edge_tts_service import synthesize as edge_synth
                result = await edge_synth(text, voice=voice or "nate_warm")
                if result:
                    return result
            except Exception as e:
                _logger.warning("Edge TTS user-requested failed (%s), trying chain", e)

        if tts_provider == "sovereign_xtts":
            try:
                from app.services.sovereign_tts import synthesize as xtts_synth
                result = await xtts_synth(text, voice_id=voice)
                if result:
                    return result
            except Exception as e:
                _logger.warning("Sovereign XTTS user-requested failed (%s), trying chain", e)

        if tts_provider == "azure_premium":
            return await self._tts_premium(text, voice=voice)

        if self.is_premium(tier):
            return await self._tts_premium(text, voice=voice)
        return await self._tts(text, voice=voice)

    async def process_speech_to_text(
        self,
        audio_data: bytes,
        *,
        content_type: str = "audio/webm",
    ) -> Optional[str]:
        """STT: sovereign Whisper first, Azure Whisper fallback."""
        return await self._stt(audio_data, content_type=content_type)

    # ── STT (Voice Pool → Sovereign Whisper → Azure Whisper fallback) ───────

    async def _stt(
        self, audio_data: bytes, content_type: str = "audio/webm"
    ) -> Optional[str]:
        pool = getattr(self._app_state, "voice_pool", None) if self._app_state else None
        if pool:
            try:
                status = pool.get_pool_status()
                stt_status = status.get("stt_pool", {})
                has_remote = any(
                    n.get("endpoint") != "local" and n.get("healthy")
                    for n in stt_status.get("nodes", [])
                )
                if has_remote:
                    result = await pool.submit_stt_job(audio_data)
                    if result and result.get("status") == "queued":
                        _logger.info("STT job queued on node %s", result.get("node"))
            except Exception as e:
                _logger.warning("Voice pool STT dispatch failed (%s), using local", e)

        try:
            from app.services.sovereign_whisper import transcribe
            result = await transcribe(audio_data)
            return result.get("text", "").strip() or None
        except Exception as e:
            _logger.warning("Sovereign STT failed (%s), falling back to Azure Whisper", e)

        try:
            from app.services.whisper_stt import transcribe as azure_transcribe
            return await azure_transcribe(audio_data, content_type=content_type)
        except Exception as e:
            _logger.warning("Azure Whisper STT also failed: %s", e)
            return None

    # ── Chat (LittleNateInference → Grok fallback) ───────────────────────────

    async def _chat(
        self,
        user_text: str,
        *,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        inference = getattr(self._app_state, "littlenate_inference", None) if self._app_state else None
        if inference:
            try:
                result = await inference.generate(
                    prompt=user_text,
                    system=system_prompt or "",
                    user_id=user_id or "anonymous",
                    domain="clinical",
                    tier="clinical",
                    max_tokens=300,
                )
                if result.text:
                    return result.text
            except Exception as e:
                _logger.warning("LittleNateInference failed (%s), falling back to Grok", e)

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

    # ── TTS (Voice Pool → Sovereign XTTS → Edge TTS → Workers AI fallback) ─

    async def _tts(
        self,
        text: str,
        voice: Optional[str] = None,
        felt_sense: str = "grounded",
        client_biometrics: Optional[Dict] = None,
    ) -> Optional[bytes]:
        pool = getattr(self._app_state, "voice_pool", None) if self._app_state else None
        if pool:
            try:
                status = pool.get_pool_status()
                tts_status = status.get("tts_pool", {})
                has_remote = any(
                    n.get("endpoint") != "local" and n.get("healthy")
                    for n in tts_status.get("nodes", [])
                )
                if has_remote:
                    result = await pool.submit_tts_job(text, voice_id=voice or "default")
                    if result and result.get("status") == "queued":
                        _logger.info("TTS job queued on node %s", result.get("node"))
            except Exception as e:
                _logger.warning("Voice pool TTS dispatch failed (%s), using local", e)

        # Tier 1: Sovereign XTTS-v2 with RISSC voice cloning
        try:
            from app.services.sovereign_tts import synthesize as xtts_synthesize
            from app.services.rissc_voice import get_rissc_params, rissc_to_dict
            rissc = get_rissc_params(felt_sense, client_biometrics)
            audio = await xtts_synthesize(
                text,
                rissc_params=rissc_to_dict(rissc),
                speed=rissc.speed,
                temperature=rissc.temperature,
                top_p=rissc.top_p,
                top_k=rissc.top_k,
                repetition_penalty=rissc.repetition_penalty,
            )
            if audio:
                return audio
        except ImportError:
            pass
        except Exception as e:
            _logger.warning("Sovereign XTTS+RISSC failed (%s), trying Edge TTS", e)

        # Tier 2: Edge TTS (Microsoft free)
        try:
            from app.services.edge_tts_service import synthesize, get_coherence_params
            try:
                from app.services.rissc_voice import get_rissc_params, rissc_to_edge_tts
                rissc = get_rissc_params(felt_sense, client_biometrics)
                edge_params = rissc_to_edge_tts(rissc)
            except ImportError:
                edge_params = get_coherence_params(felt_sense=felt_sense, voice_override=voice)
            audio = await synthesize(
                text,
                voice=edge_params.get("voice") or voice,
                rate=edge_params.get("rate", "+0%"),
                pitch=edge_params.get("pitch", "+0Hz"),
            )
            if audio:
                return audio
        except ImportError:
            pass
        except Exception as e:
            _logger.warning("Edge TTS failed (%s), trying Workers AI TTS", e)

        # Tier 3: Workers AI TTS ($0 — included in Workers Paid plan)
        return await self._tts_workers_ai(text)

    async def _tts_workers_ai(self, text: str) -> Optional[bytes]:
        """Free TTS via Cloudflare Workers AI — last-resort fallback."""
        cf_account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        cf_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        if not cf_account or not cf_token:
            return None

        url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/run/@cf/myshell-ai/melotts"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {cf_token}",
                        "Content-Type": "application/json",
                    },
                    json={"text": text[:500], "language": "EN"},
                )

            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "audio" in content_type or "octet-stream" in content_type:
                    return resp.content
                data = resp.json()
                audio_data = data.get("result", {}).get("audio")
                if audio_data:
                    import base64 as b64mod
                    return b64mod.b64decode(audio_data)

            _logger.warning("Workers AI TTS failed: HTTP %d", resp.status_code)
            return None
        except Exception as e:
            _logger.warning("Workers AI TTS error: %s", e)
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
