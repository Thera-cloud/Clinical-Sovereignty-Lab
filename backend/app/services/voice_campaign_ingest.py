"""Coach voice/video campaign ingest. Encrypt on write. Never publish here (Seam 5)."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional

from app.services.client_envelope_cipher import EnvelopeUnavailable
from app.services.google_workspace_service import FlagOff, VaultBlocked, client_vault_sync

logger = logging.getLogger("voice_campaign_ingest")

AUDIO_MAX = 15 * 1024 * 1024
VIDEO_MAX = 40 * 1024 * 1024
ALLOWED_AUDIO = frozenset(
    {"audio/wav", "audio/mpeg", "audio/mp3", "audio/m4a", "audio/ogg", "audio/webm", "audio/mp4"}
)
ALLOWED_VIDEO = frozenset({"video/mp4", "video/quicktime", "video/webm"})


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def video_ingest_allowed() -> bool:
    raw = os.getenv("ENABLE_COACH_VIDEO_INGEST", "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return _flag_on("ENABLE_VOICE_CAMPAIGN")


def encrypt_coach_bytes(data: bytes) -> str:
    """Coach-scoped media — KEK Fernet only. No TokenCipher plaintext fallback."""
    from app.services.client_envelope_cipher import _kek

    return _kek().encrypt(data or b"").decode()


def decrypt_coach_bytes(ciphertext: str) -> bytes:
    from app.services.client_envelope_cipher import _kek

    try:
        return _kek().decrypt((ciphertext or "").encode())
    except Exception:
        from app.services.skyeye_platform_base import TokenCipher
        import base64

        raw = TokenCipher.get().decrypt(ciphertext or "")
        try:
            return base64.b64decode(raw)
        except Exception:
            return raw.encode() if isinstance(raw, str) else (raw or b"")


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


def _stt_url() -> str:
    url = (os.getenv("COACH_CAMPAIGN_STT_URL") or "").strip()
    if url:
        return url
    base = (os.getenv("CLASSROOM_VOICE_REMOTE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/transcribe"
    return ""


async def _transcribe_remote(media: bytes, content_type: str) -> str:
    """Optional ORANGE/local Whisper HTTP. Never loads weights on GREEN."""
    url = _stt_url()
    if not url or not media:
        return ""
    try:
        import httpx

        headers = {}
        token = (os.getenv("CLASSROOM_REMOTE_AUTH_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        filename = "audio.wav" if "wav" in (content_type or "") else "audio.webm"
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                files={"file": (filename, media, content_type or "application/octet-stream")},
            )
        if resp.status_code >= 400:
            return ""
        data = resp.json()
        if isinstance(data, dict):
            return str(data.get("text") or data.get("transcript") or "").strip()
    except Exception as exc:
        logger.warning("campaign remote STT skipped: %s", exc)
    return ""


async def _transcribe(media: bytes, content_type: str) -> str:
    if not media or len(media) < 100:
        return ""
    remote = await _transcribe_remote(media, content_type)
    if remote:
        return remote
    try:
        from app.services.whisper_stt import transcribe, transcribe_chunked

        ctypes = [content_type or "audio/webm"]
        if (content_type or "").startswith("video/"):
            ctypes.extend(["video/mp4", "audio/mp4", "audio/webm"])
        seen = []
        for ct in ctypes:
            if ct in seen:
                continue
            seen.append(ct)
            text = await transcribe(media, content_type=ct)
            if text and text.strip():
                return text.strip()
        if len(media) > 2 * 1024 * 1024:
            text = await transcribe_chunked(
                media, content_type=content_type or "audio/wav"
            )
            return (text or "").strip()
    except Exception as exc:
        logger.warning("campaign STT failed: %s", exc)
    return ""


async def _put_r2(key: str, payload: bytes) -> bool:
    try:
        from app.services.r2_storage import is_r2_configured, upload_bytes_async

        if not is_r2_configured():
            return False
        await upload_bytes_async(key=key, content=payload, content_type="application/octet-stream")
        return True
    except Exception as exc:
        logger.warning("campaign R2 put skipped: %s", exc)
        return False


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
    if kind == "video" and not video_ingest_allowed():
        raise FlagOff("ENABLE_COACH_VIDEO_INGEST")
    blob = audio_bytes or b""
    text = (transcript or "").strip()
    if not blob and len(text) < 40:
        raise ValueError("media or transcript (40+ chars) required")
    limit = VIDEO_MAX if kind == "video" else AUDIO_MAX
    if blob and len(blob) > limit:
        raise ValueError(f"{kind} over {limit // (1024 * 1024)} MB — paste transcript instead")
    ctype = (content_type or ("video/mp4" if kind == "video" else "audio/webm")).strip()
    if blob:
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
        if not text and blob:
            text = await _transcribe(blob, ctype)
        tx_cipher: Optional[str] = None
        if text:
            tx_cipher = await encrypt_for_client(db_pool, client_id, text.encode())
    else:
        try:
            cipher = encrypt_coach_bytes(blob)
        except EnvelopeUnavailable as exc:
            raise ValueError("coach envelope unavailable") from exc
        if not text and blob:
            text = await _transcribe(blob, ctype)
        tx_cipher = None
        if text:
            tx_cipher = encrypt_coach_bytes(text.encode())

    rec_id = str(uuid.uuid4())
    ext = "mp4" if kind == "video" else "enc"
    r2_key = f"coach_voice_campaigns/{coach_id}/{rec_id}.{ext}"
    r2_ok = await _put_r2(r2_key, (cipher or "").encode())
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
    bios: Dict[str, Any] = {}
    if blob and subject == "coach":
        try:
            from app.services.coach_voice_biometrics import extract_campaign_biometrics

            bios = extract_campaign_biometrics(blob, ctype) or {}
        except Exception as exc:
            logger.warning("campaign biometrics skipped: %s", exc)
            bios = {}
        if kind == "video":
            try:
                from app.services.coach_voice_biometrics import extract_visual_presence

                visual = extract_visual_presence(blob) or {}
                if visual:
                    bios = {**bios, **visual}
            except Exception as exc:
                logger.warning("campaign visual presence skipped: %s", exc)
    if text and subject == "coach":
        try:
            from app.services.coach_voice_profile_service import upsert_voice_profile

            await upsert_voice_profile(
                db_pool, coach_id, text, recording_id=rec_id, biometrics=bios
            )
        except Exception as exc:
            logger.warning("voice profile upsert skipped: %s", exc)
    preview = text[:400] if text else ""
    return {
        "ok": True,
        "id": rec_id,
        "r2_key": r2_key,
        "r2_stored": r2_ok,
        "published": False,
        "media_kind": kind,
        "subject": subject,
        "transcribed": bool(text),
        "transcript_preview": preview,
        "biometrics": bool(bios.get("voice_biometrics")),
        "presence_style": bios.get("presence_style") or "",
    }


async def attach_transcript(
    db_pool,
    coach_id: str,
    recording_id: str,
    transcript: str,
) -> Dict[str, Any]:
    text = (transcript or "").strip()
    if len(text) < 40:
        raise ValueError("transcript must be 40+ characters")
    coach_id = (coach_id or "").strip()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, client_id, subject FROM coach_voice_recordings
            WHERE id = $1::uuid AND coach_id = $2
            """,
            recording_id,
            coach_id,
        )
    if not row:
        raise ValueError("recording not found")
    subject = row["subject"] or "client"
    client_id = row["client_id"] or ""
    if subject == "client" and client_id:
        from app.services.client_envelope_cipher import encrypt_for_client

        tx_cipher = await encrypt_for_client(db_pool, client_id, text.encode())
    else:
        tx_cipher = encrypt_coach_bytes(text.encode())
        subject = "coach"
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE coach_voice_recordings
            SET transcript_ciphertext = $1
            WHERE id = $2::uuid AND coach_id = $3
            """,
            tx_cipher,
            recording_id,
            coach_id,
        )
    if subject == "coach":
        from app.services.coach_voice_profile_service import upsert_voice_profile

        await upsert_voice_profile(db_pool, coach_id, text, recording_id=recording_id)
    return {"ok": True, "id": recording_id, "transcribed": True, "transcript_preview": text[:400]}
