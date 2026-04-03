"""
Voice Edge API — Backend endpoints for the nate-voice-edge Cloudflare Worker.

These routes proxy STT/TTS through the VoiceRouter which handles provider
fallback chains (pool → sovereign → edge → workers AI) internally.
"""

import logging
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("voice_edge_api")

router = APIRouter(prefix="/api/voice", tags=["voice-edge"])


@router.post("/stt")
async def edge_stt(request: Request):
    """Accept raw audio, run through VoiceRouter STT chain, return transcript."""
    audio_data = await request.body()
    if len(audio_data) < 100:
        return JSONResponse({"error": "Audio too short"}, status_code=400)

    content_type = request.headers.get("content-type", "audio/webm")

    voice_router = getattr(request.app.state, "voice_router", None)
    if not voice_router:
        return JSONResponse({"error": "Voice router unavailable"}, status_code=503)

    try:
        transcript = await voice_router.process_speech_to_text(
            audio_data, content_type=content_type
        )
        return {"text": transcript or "", "status": "ok"}
    except Exception as e:
        logger.warning("Edge STT failed: %s", e)
        return JSONResponse({"error": "STT processing failed"}, status_code=502)


@router.post("/tts")
async def edge_tts(request: Request):
    """Accept JSON with text field, run through VoiceRouter TTS chain, return audio."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Text required"}, status_code=400)

    voice = body.get("voice")
    tier = body.get("tier", "STANDARD")

    voice_router = getattr(request.app.state, "voice_router", None)
    if not voice_router:
        return JSONResponse({"error": "Voice router unavailable"}, status_code=503)

    try:
        audio_bytes = await voice_router.process_text_to_speech(
            text, tier=tier, voice=voice
        )
        if audio_bytes:
            return Response(
                content=audio_bytes,
                media_type="audio/mp3",
                headers={"X-Voice-Provider": "sovereign_pipeline"},
            )
        return JSONResponse({"error": "TTS produced no audio"}, status_code=502)
    except Exception as e:
        logger.warning("Edge TTS failed: %s", e)
        return JSONResponse({"error": "TTS processing failed"}, status_code=502)


@router.get("/edge/health")
async def voice_edge_health(request: Request):
    """Voice pipeline health for edge worker provider probing."""
    voice_router = getattr(request.app.state, "voice_router", None)
    pool = getattr(request.app.state, "voice_pool", None)

    result = {
        "status": "ok",
        "voice_router": voice_router is not None,
    }

    if pool:
        result["pool"] = pool.get_pool_status()

    return result
