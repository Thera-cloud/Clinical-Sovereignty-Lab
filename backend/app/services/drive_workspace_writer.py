"""Drive write for vault_sync clients. Encrypt bytes; never upload when blocked."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.services.google_workspace_service import FlagOff, VaultBlocked, client_vault_sync

DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def drive_create_file(access_token: str, name: str, ciphertext: str) -> Optional[str]:
    import aiohttp

    boundary = "natewsboundary"
    name = "".join(c for c in (name or "vault.bin") if c.isalnum() or c in "._- ")[:120] or "vault.bin"
    meta = f'{{"name": "{name}", "mimeType": "application/octet-stream"}}'
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
        f"{ciphertext}\r\n"
        f"--{boundary}--"
    ).encode()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            DRIVE_UPLOAD,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            data=body,
        ) as resp:
            if resp.status not in (200, 201):
                return None
            data = await resp.json(content_type=None)
            return data.get("id")


async def write_client_file(
    db_pool,
    coach_id: str,
    client_id: str,
    *,
    filename: str = "vault.bin",
    content: bytes = b"",
    access_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_WS_DRIVE_DELIVERY"):
        raise FlagOff("ENABLE_WS_DRIVE_DELIVERY")
    client_id = (client_id or "").strip()
    if not await client_vault_sync(db_pool, client_id):
        raise VaultBlocked("drive.writeClientFile blocked: vault_sync=false")
    from app.services.client_envelope_cipher import encrypt_for_client

    cipher = await encrypt_for_client(db_pool, client_id, content or b"")
    drive_id = None
    if access_token:
        drive_id = await drive_create_file(access_token, filename, cipher)
    return {
        "ok": True,
        "encrypted": True,
        "drive_file_id": drive_id,
        "coach_id": coach_id,
    }
