"""Coach voice/video campaign ingest. Encrypt on write. Never publish here (Seam 5)."""

from __future__ import annotations

import base64
import logging
import os
import uuid
from typing import Any, Dict, Optional

from app.services.google_workspace_service import FlagOff, VaultBlocked, client_vault_sync

logger = logging.getLogger("voice_campaign_ingest")

AUDIO_MAX = 15 * 1024 * 1024
VIDEO_MAX = 20 * 1024 * 1024
ALLOWED_AUDIO = frozenset(
    {"audio/wav", "audio/mpeg", "audio/mp3", "audio/m4a", "audio/ogg", "audio/webm", "audio/mp4"}
)
ALLOWED_VIDEO = frozenset({"video/mp4", "video/quicktime", "video/webm"})


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def encrypt_coach_bytes(data: bytes) -> str:
    """Coach-scoped media — KEK Fernet, not a client DEK (NG18)."""
    try:
        from app.services.client_envelope_cipher import _kek

        return _kek().encrypt(data or b"").decode()
    except Exception:
        from app.services.skyeye_platform_base import TokenCipher

        return TokenCipher.get().encrypt(base64.b64encode(data or b"").decode())


def decrypt_coach_bytes(ciphertext: str) -> bytes:
    try:
        from app.services.client_envelope_cipher import _kek

        return _kek().decrypt((ciphertext or "").encode())
    except Exception:
        from app.services.skyeye_platform_base import TokenCipher

        raw = TokenCipher.get().decrypt(ciphertext or "")
        try:
            return base64.b64decode(raw)
        except Exception:
            return raw.encode() if isinstance(raw, str) else raw


async def decrypt_recording_transcript(
    db_pool,
    *,
    ciphertext: str,
    client_id: str,
    subject: str,
) -> str:
    if not ciphertext:
        return ""
    if (subject or "client") == "client" and client_id:
        from app.services.client_envelope_cipher import decrypt_for_client

        return (await decrypt_for_client(db_pool, client_id, ciphertext)).decode(
            "utf-8", errors="replace"
        )
    return decrypt_coach_bytes(ciphertext).decode("utf-8", errors="replace")


async def _transcribe(media: bytes, content_type: str) -> str:
    try:
        from app.services.whisper_stt import transcribe

        text = await transcribe(media, content_type=content_type or "audio/webm")
        return (text or "").strip()
    except Exception as exc:
        logger.warning("campaign STT failed: %s", exc)
        return ""


async def store_voice_recording(
    db_pool,
    coach_id: str,
    client_id: str,
    audio_bytes: bytes,
    *,
    transcript: str = "",
    media_kind: str = "audio",
    content_type: str = "",
) -> Dict[str, Any]:
    """R2 prefix coach_voice_campaigns/. Envelope-encrypt bytes. No LinkedIn/Gmail send."""
    if not _flag_on("ENABLE_VOICE_CAMPAIGN"):
        raise FlagOff("ENABLE_VOICE_CAMPAIGN")
    coach_id = (coach_id or "").strip()
    client_id = (client_id or "").strip()
    kind = (media_kind or "audio").strip().lower()
    if kind not in ("audio", "video"):
        raise ValueError("media_kind must be audio or video")
    if kind == "video" and not _flag_on("ENABLE_COACH_VIDEO_INGEST"):
        raise FlagOff("ENABLE_COACH_VIDEO_INGEST")
    blob = audio_bytes or b""
    limit = VIDEO_MAX if kind == "video" else AUDIO_MAX
    if len(blob) > limit:
        raise ValueError(f"{kind} over {limit // (1024 * 1024)} MB")
    ctype = (content_type or ("video/mp4" if kind == "video" else "audio/webm")).strip()
    if kind == "video" and ctype not in ALLOWED_VIDEO:
        raise ValueError("unsupported video type")
    if kind == "audio" and ctype and ctype not in ALLOWED_AUDIO:
        raise ValueError("unsupported audio type")

    subject = "client" if client_id else "coach"
    if subject == "client":
        if not await client_vault_sync(db_pool, client_id):
            raise VaultBlocked("voice ingest blocked: vault_sync=false")
        from app.services.client_envelope_cipher import encrypt_for_client

        cipher = await encrypt_for_client(db_pool, client_id, blob)
        tx_cipher: Optional[str] = None
        text = (transcript or "").strip() or await _transcribe(blob, ctype)
        if text:
            tx_cipher = await encrypt_for_client(db_pool, client_id, text.encode())
    else:
        cipher = encrypt_coach_bytes(blob)
        tx_cipher = None
        text = (transcript or "").strip() or await _transcribe(blob, ctype)
        if text:
            tx_cipher = encrypt_coach_bytes(text.encode())

    rec_id = str(uuid.uuid4())
    ext = "mp4" if kind == "video" else "enc"
    r2_key = f"coach_voice_campaigns/{coach_id}/{rec_id}.{ext}"
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO coach_voice_recordings
                  (id, coach_id, client_id, r2_key, audio_ciphertext, transcript_ciphertext,
                   media_kind, subject)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
                """,
                rec_id,
                coach_id,
                client_id or None,
                r2_key,
                cipher,
                tx_cipher,
                kind,
                subject,
            )
    if text:
        try:
            from app.services.coach_voice_profile_service import upsert_voice_profile

            await upsert_voice_profile(db_pool, coach_id, text, recording_id=rec_id)
        except Exception as exc:
            logger.warning("voice profile upsert skipped: %s", exc)
    return {
        "ok": True,
        "id": rec_id,
        "r2_key": r2_key,
        "published": False,
        "media_kind": kind,
        "subject": subject,
        "transcribed": bool(text),
    }
