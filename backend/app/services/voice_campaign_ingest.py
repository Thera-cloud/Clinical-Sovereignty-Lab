"""Coach voice campaign ingest. Encrypt on write. Never publish here (Seam 5)."""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict

from app.services.google_workspace_service import FlagOff, VaultBlocked, client_vault_sync


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def store_voice_recording(
    db_pool,
    coach_id: str,
    client_id: str,
    audio_bytes: bytes,
    *,
    transcript: str = "",
) -> Dict[str, Any]:
    """R2 prefix coach_voice_campaigns/. Envelope-encrypt bytes. No LinkedIn/Gmail send."""
    if not _flag_on("ENABLE_VOICE_CAMPAIGN"):
        raise FlagOff("ENABLE_VOICE_CAMPAIGN")
    coach_id = (coach_id or "").strip()
    client_id = (client_id or "").strip()
    if not client_id:
        raise ValueError("client_id required")
    if not await client_vault_sync(db_pool, client_id):
        raise VaultBlocked("voice ingest blocked: vault_sync=false")
    from app.services.client_envelope_cipher import encrypt_for_client

    cipher = await encrypt_for_client(db_pool, client_id, audio_bytes or b"")
    rec_id = str(uuid.uuid4())
    r2_key = f"coach_voice_campaigns/{coach_id}/{rec_id}.enc"
    tx_cipher = None
    if transcript:
        tx_cipher = await encrypt_for_client(db_pool, client_id, transcript.encode())
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO coach_voice_recordings
                  (id, coach_id, client_id, r2_key, audio_ciphertext, transcript_ciphertext)
                VALUES ($1::uuid, $2, $3, $4, $5, $6)
                """,
                rec_id, coach_id, client_id, r2_key, cipher, tx_cipher,
            )
    return {"ok": True, "id": rec_id, "r2_key": r2_key, "published": False}
