"""Practice / org libraries on canonical R2. Soft-delete only. ENABLE_PRACTICE_LIBRARIES."""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from app.services.client_envelope_cipher import _kek
from app.services.google_workspace_service import FlagOff

R2_PREFIX = "practice_libraries"
ORG_PREFIX = "org_library"
_FAIL_THRESHOLD = 3
_r2_failures = 0


class CircuitOpen(RuntimeError):
    """R2 uploads paused after consecutive failures. Rows are not dropped."""


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def _require() -> None:
    if not _flag_on("ENABLE_PRACTICE_LIBRARIES"):
        raise FlagOff("ENABLE_PRACTICE_LIBRARIES")


def reset_circuit() -> None:
    global _r2_failures
    _r2_failures = 0


def _encrypt_bytes(payload: bytes) -> bytes:
    return _kek().encrypt(payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode())


def _upload(key: str, content: bytes) -> str:
    global _r2_failures
    from app.services.r2_storage import is_r2_configured, upload_bytes

    if _r2_failures >= _FAIL_THRESHOLD:
        raise CircuitOpen("R2 circuit open")
    if not is_r2_configured():
        _r2_failures += 1
        if _r2_failures >= _FAIL_THRESHOLD:
            raise CircuitOpen("R2 circuit open")
        raise RuntimeError("R2 not configured")
    try:
        upload_bytes(key=key, content=content, content_type="application/octet-stream")
        _r2_failures = 0
        return key
    except Exception:
        _r2_failures += 1
        if _r2_failures >= _FAIL_THRESHOLD:
            raise CircuitOpen("R2 circuit open")
        raise


async def put_template(
    db_pool,
    coach_id: str,
    *,
    title: str,
    body: bytes,
) -> Dict[str, Any]:
    _require()
    coach_id = (coach_id or "").strip()
    if not coach_id:
        raise ValueError("coach_id (hardware_id) required")
    blob_id = str(uuid.uuid4())
    key = f"{R2_PREFIX}/{coach_id}/{blob_id}.enc"
    ciphertext = _encrypt_bytes(body or b"")
    r2_key = None
    try:
        r2_key = _upload(key, ciphertext)
    except CircuitOpen:
        raise
    except Exception:
        r2_key = None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO practice_templates (coach_id, title, body)
            VALUES ($1, $2, $3)
            RETURNING id, coach_id, title, deleted_at
            """,
            coach_id,
            (title or "template").strip()[:200],
            r2_key or key,
        )
    return dict(row)


async def put_org_item(
    db_pool,
    org_id: str,
    *,
    title: str,
    body: bytes,
) -> Dict[str, Any]:
    _require()
    org_id = (org_id or "").strip()
    blob_id = str(uuid.uuid4())
    key = f"{ORG_PREFIX}/{org_id}/{blob_id}.enc"
    ciphertext = _encrypt_bytes(body or b"")
    r2_key = key
    try:
        _upload(key, ciphertext)
    except CircuitOpen:
        raise
    except Exception:
        pass
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO org_library (org_id, title, r2_key)
            VALUES ($1, $2, $3)
            RETURNING id, org_id, title, r2_key, deleted_at
            """,
            org_id,
            (title or "item").strip()[:200],
            r2_key,
        )
    return dict(row)


async def soft_delete_template(db_pool, template_id: str, coach_id: str) -> None:
    _require()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE practice_templates
            SET deleted_at = NOW()
            WHERE id = $1::uuid AND coach_id = $2 AND deleted_at IS NULL
            """,
            template_id,
            coach_id,
        )


async def list_templates(db_pool, coach_id: str) -> List[Dict[str, Any]]:
    _require()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, coach_id, title, body, deleted_at, created_at
            FROM practice_templates
            WHERE coach_id = $1 AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT 50
            """,
            coach_id,
        )
    return [dict(r) for r in rows]
