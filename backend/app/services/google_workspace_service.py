"""Frozen googleSvc facade (plan v1.5.2 WS-A).

coachId / clientId = users.hardware_id.
TokenCipher decrypt of Google refresh tokens lives only in WS-A callers
(google_workspace_api + existing google_calendar_session_sync). This module
does not decrypt Google tokens in Seam 0 stubs.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("google_workspace_service")

ReplyCallback = Callable[[Dict[str, Any]], Awaitable[None]]


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


class VaultBlocked(Exception):
    """vault_sync is false — no Google call with client PII."""

    def __init__(self, message: str = "VaultBlocked"):
        super().__init__(message)
        self.code = "VaultBlocked"


class FlagOff(Exception):
    def __init__(self, flag: str):
        super().__init__(f"{flag} is off")
        self.flag = flag
        self.code = "temporarily_unavailable"


async def resolve_username(db_pool, hardware_id: str) -> Optional[str]:
    if not db_pool or not hardware_id:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username FROM workspace_identity WHERE hardware_id = $1 LIMIT 1",
            hardware_id,
        )
    return row["username"] if row else None


async def client_vault_sync(db_pool, client_hardware_id: str) -> bool:
    if not db_pool or not client_hardware_id:
        return False
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(vault_sync, false) AS vault_sync
            FROM users
            WHERE hardware_id = $1 AND role = 'CLIENT'
            LIMIT 1
            """,
            client_hardware_id,
        )
    return bool(row["vault_sync"]) if row else False


class _CalendarNS:
    def __init__(self, svc: "GoogleWorkspaceService"):
        self._svc = svc

    async def upsertSession(self, coachId: str, sessionId: str) -> Dict[str, Any]:
        return await self._svc.upsert_session(coachId, sessionId)

    async def removeSession(self, coachId: str, sessionId: str) -> Dict[str, Any]:
        return await self._svc.remove_session(coachId, sessionId)


class _GmailNS:
    def __init__(self, svc: "GoogleWorkspaceService"):
        self._svc = svc
        self._reply_cb: Optional[ReplyCallback] = None

    async def createDraft(self, coachId: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._svc.create_draft(coachId, payload)

    def onCampaignReply(self, callback: ReplyCallback) -> None:
        self._reply_cb = callback


class _DriveNS:
    def __init__(self, svc: "GoogleWorkspaceService"):
        self._svc = svc

    async def writeClientFile(self, coachId: str, clientId: str, **kwargs: Any) -> Dict[str, Any]:
        return await self._svc.write_client_file(coachId, clientId, **kwargs)


class GoogleWorkspaceService:
    """googleSvc — Seam 0 freeze. Writes gated by flags; encryption always on when drafting."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self.calendar = _CalendarNS(self)
        self.gmail = _GmailNS(self)
        self.drive = _DriveNS(self)

    async def status(self, coachId: str) -> Dict[str, Any]:
        pool = self.db_pool
        if not pool:
            return {
                "connected": False,
                "scopes": "",
                "revoked": False,
                "oauth_enabled": _flag_on("ENABLE_WS_OAUTH"),
            }
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT scopes, revoked_at
                FROM google_workspace_connection
                WHERE hardware_id = $1
                LIMIT 1
                """,
                coachId,
            )
        if not row:
            return {
                "connected": False,
                "scopes": "",
                "revoked": False,
                "oauth_enabled": _flag_on("ENABLE_WS_OAUTH"),
            }
        return {
            "connected": row["revoked_at"] is None,
            "scopes": row["scopes"] or "",
            "revoked": row["revoked_at"] is not None,
            "oauth_enabled": _flag_on("ENABLE_WS_OAUTH"),
        }

    async def upsert_session(self, coach_id: str, session_id: str) -> Dict[str, Any]:
        if not _flag_on("ENABLE_WS_CALENDAR_SYNC") and not _flag_on("ENABLE_WS_OAUTH"):
            return {"ok": False, "reason": "flag_off"}
        return {"ok": False, "reason": "seam1_pending", "coach_id": coach_id, "session_id": session_id}

    async def remove_session(self, coach_id: str, session_id: str) -> Dict[str, Any]:
        if not _flag_on("ENABLE_WS_CALENDAR_SYNC") and not _flag_on("ENABLE_WS_OAUTH"):
            return {"ok": False, "reason": "flag_off"}
        return {"ok": False, "reason": "seam1_pending", "coach_id": coach_id, "session_id": session_id}

    async def create_draft(self, coach_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not _flag_on("ENABLE_WS_GMAIL_DRAFTS"):
            raise FlagOff("ENABLE_WS_GMAIL_DRAFTS")
        client_id = (payload.get("client_id") or "").strip()
        if client_id and not await client_vault_sync(self.db_pool, client_id):
            raise VaultBlocked("createDraft blocked: vault_sync=false")
        # Seam 3 wires Gmail API; encrypt body now so first writes are wrapped.
        body = payload.get("body") or ""
        if client_id and body and self.db_pool:
            from app.services.client_envelope_cipher import encrypt_for_client
            cipher = await encrypt_for_client(self.db_pool, client_id, body.encode())
            return {"gmail_draft_id": None, "encrypted": True, "body_ciphertext": cipher}
        return {"gmail_draft_id": None, "encrypted": False, "reason": "seam3_pending"}

    async def write_client_file(self, coach_id: str, client_id: str, **kwargs: Any) -> Dict[str, Any]:
        if not _flag_on("ENABLE_WS_DRIVE_DELIVERY"):
            raise FlagOff("ENABLE_WS_DRIVE_DELIVERY")
        if not await client_vault_sync(self.db_pool, client_id):
            raise VaultBlocked("drive.writeClientFile blocked: vault_sync=false")
        return {"ok": False, "reason": "seam5_pending"}


def get_google_svc(db_pool=None) -> GoogleWorkspaceService:
    return GoogleWorkspaceService(db_pool=db_pool)
