"""Per-client envelope encryption for Workspace §0.4 stores.

Uses CLIENT_ENVELOPE_KEK only. Do not import TokenCipher or
SKYEYE_TOKEN_ENCRYPTION_KEY (pii_cipher already shares that key).

Encrypt: email_drafts bodies, client voice R2 bytes, Drive bytes, wrapped DEKs.
Do not encrypt coaching_sessions Schedule display fields.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("client_envelope_cipher")

try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover
    Fernet = None  # type: ignore

_KEK_ENV = "CLIENT_ENVELOPE_KEK"


class EnvelopeUnavailable(RuntimeError):
    """KEK missing or cryptography not installed — fail closed on write."""


class KeyDestroyed(RuntimeError):
    """Client DEK has destroyed_at set."""


class ErasureDisabled(RuntimeError):
    """Key destruction requires ENABLE_CLINICAL_ERASURE."""


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def _kek() -> Any:
    if Fernet is None:
        raise EnvelopeUnavailable("cryptography package not installed")
    raw = (os.getenv(_KEK_ENV) or "").strip()
    if not raw:
        raise EnvelopeUnavailable(f"{_KEK_ENV} is not set")
    if raw == os.getenv("SKYEYE_TOKEN_ENCRYPTION_KEY", ""):
        raise EnvelopeUnavailable(f"{_KEK_ENV} must not equal SKYEYE_TOKEN_ENCRYPTION_KEY")
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception as exc:
        raise EnvelopeUnavailable(f"invalid {_KEK_ENV}: {exc}") from exc


def generate_dek() -> bytes:
    if Fernet is None:
        raise EnvelopeUnavailable("cryptography package not installed")
    return Fernet.generate_key()


def wrap_dek(dek: bytes) -> str:
    return _kek().encrypt(dek).decode()


def unwrap_dek(wrapped: str) -> bytes:
    return _kek().decrypt(wrapped.encode())


def encrypt_with_dek(dek: bytes, plaintext: bytes) -> str:
    if not isinstance(plaintext, (bytes, bytearray)):
        plaintext = str(plaintext).encode()
    return Fernet(dek).encrypt(bytes(plaintext)).decode()


def decrypt_with_dek(dek: bytes, ciphertext: str) -> bytes:
    return Fernet(dek).decrypt(ciphertext.encode())


async def get_or_create_active_dek(db_pool, client_id: str) -> bytes:
    """Load live DEK for client_id (hardware_id) or mint one. Write-path always on."""
    if not client_id:
        raise ValueError("client_id (hardware_id) required")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT dek_id, wrapped_dek, destroyed_at
            FROM client_data_keys
            WHERE client_id = $1 AND destroyed_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            client_id,
        )
        if row:
            if row["destroyed_at"] is not None:
                raise KeyDestroyed(client_id)
            return unwrap_dek(row["wrapped_dek"])
        dek = generate_dek()
        wrapped = wrap_dek(dek)
        await conn.execute(
            """
            INSERT INTO client_data_keys (client_id, wrapped_dek)
            VALUES ($1, $2)
            """,
            client_id,
            wrapped,
        )
        return dek


async def encrypt_for_client(db_pool, client_id: str, plaintext: bytes) -> str:
    dek = await get_or_create_active_dek(db_pool, client_id)
    return encrypt_with_dek(dek, plaintext)


async def decrypt_for_client(db_pool, client_id: str, ciphertext: str) -> bytes:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT wrapped_dek, destroyed_at
            FROM client_data_keys
            WHERE client_id = $1 AND destroyed_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            client_id,
        )
    if not row:
        raise KeyDestroyed(client_id)
    if row["destroyed_at"] is not None:
        raise KeyDestroyed(client_id)
    return decrypt_with_dek(unwrap_dek(row["wrapped_dek"]), ciphertext)


async def destroy_client_keys(db_pool, client_id: str) -> int:
    """Schema exists; workflow OFF until ENABLE_CLINICAL_ERASURE."""
    if not _flag_on("ENABLE_CLINICAL_ERASURE"):
        raise ErasureDisabled("ENABLE_CLINICAL_ERASURE is off — key destruction blocked")
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE client_data_keys
            SET destroyed_at = $2
            WHERE client_id = $1 AND destroyed_at IS NULL
            """,
            client_id,
            datetime.now(timezone.utc),
        )
    # asyncpg returns "UPDATE N"
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0
