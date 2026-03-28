"""
DB Encryption Middleware — pgcrypto SQL-Layer Key Injection

Patches asyncpg connection pools so that EVERY acquired connection
automatically executes:
    SET LOCAL app.pii_key = '<key>'

This activates the pgcrypto triggers defined in migration 105:
  - users (email_enc, name_enc, dob_enc)
  - conversation_history (user_text_enc, ai_text_enc)
  - nevedal_metrics (biometrics_enc)
  - coaching_sessions (session_notes_enc, coach_notes_enc, nate_summary_enc)
  - crisis_watchlist (trigger_context_enc, trigger_keyword_enc)
  - vault_items (content_enc)
  - login_attempts (identifier_enc)

Key source priority:
  1. PII_ENCRYPTION_KEY env var (dedicated key — preferred)
  2. FIELD_ENCRYPTION_KEY env var (existing biometric key — fallback)
  3. JWT_SECRET env var (last resort derivation)

Usage (called once at startup in main.py and bridge_server.py):
    from app.services.db_encryption_middleware import patch_pool_for_encryption
    patch_pool_for_encryption(pool)
"""

import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_PII_KEY: Optional[str] = None
_KEY_LOADED = False


def _resolve_key() -> Optional[str]:
    """Resolve the PII encryption key from environment, with fallback chain."""
    global _PII_KEY, _KEY_LOADED
    if _KEY_LOADED:
        return _PII_KEY

    _KEY_LOADED = True

    # Priority 1: dedicated pgcrypto key
    key = os.environ.get("PII_ENCRYPTION_KEY", "").strip()
    if key:
        _PII_KEY = key
        logger.info("[pgcrypto] PII_ENCRYPTION_KEY loaded (%d chars)", len(key))
        return _PII_KEY

    # Priority 2: existing field-level encryption key
    key = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
    if key:
        _PII_KEY = key
        logger.info("[pgcrypto] Using FIELD_ENCRYPTION_KEY as PII key (%d chars)", len(key))
        return _PII_KEY

    # Priority 3: derive from JWT_SECRET (weaker — logs prominent warning)
    jwt = os.environ.get("JWT_SECRET", "").strip()
    if jwt:
        derived = hashlib.sha256(f"pii-pgcrypto:{jwt}".encode()).hexdigest()
        _PII_KEY = derived
        logger.warning(
            "[pgcrypto] ⚠️  No PII_ENCRYPTION_KEY set — deriving from JWT_SECRET. "
            "Set PII_ENCRYPTION_KEY explicitly in .env for stronger key isolation."
        )
        return _PII_KEY

    logger.warning(
        "[pgcrypto] ❌ No encryption key available (PII_ENCRYPTION_KEY, "
        "FIELD_ENCRYPTION_KEY, JWT_SECRET all unset). "
        "SQL-layer pgcrypto encryption is DISABLED."
    )
    _PII_KEY = None
    return None


def is_encryption_active() -> bool:
    """Return True if a PII key is configured and pgcrypto triggers will fire."""
    return _resolve_key() is not None


def get_pii_key() -> Optional[str]:
    """Return the resolved PII encryption key, or None if unavailable."""
    return _resolve_key()


async def init_connection(conn):
    """
    asyncpg init callback — called for every NEW connection in the pool.
    Sets app.pii_key so pgcrypto triggers can encrypt/decrypt transparently.

    Pass this to asyncpg.create_pool(init=init_connection).
    SET (without LOCAL) is session-scoped, so it persists for the
    connection's entire lifetime in the pool — no per-acquire overhead.
    """
    key = _resolve_key()
    if key:
        await conn.execute(f"SET app.pii_key = '{key}'")


def patch_pool_for_encryption(pool) -> bool:
    """
    Set app.pii_key on all EXISTING connections in a pool.

    For new connections, use init=init_connection in create_pool().
    This function handles connections that were created before the
    init callback was wired in (e.g., pool created then middleware loaded).

    Returns True if a key is active.
    """
    key = _resolve_key()
    if not key:
        return False

    if pool is None:
        logger.warning("[pgcrypto] Cannot patch None pool")
        return False

    logger.info(
        "[pgcrypto] Encryption key loaded — new connections will have app.pii_key set via init callback"
    )
    return True


async def set_pii_key_on_connection(conn) -> bool:
    """
    Set app.pii_key on an individual connection (for use in raw connection scenarios).
    Returns True if key was set, False if no key available.
    """
    key = _resolve_key()
    if not key:
        return False
    try:
        await conn.execute(f"SET app.pii_key = '{key}'")
        return True
    except Exception as e:
        logger.warning("[pgcrypto] set_pii_key_on_connection failed: %s", e)
        return False
