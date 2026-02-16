"""
LITTLE NATE — PostgreSQL User Store
=====================================
Replaces the JSON-file-based user_registry.json with a PostgreSQL-backed
in-memory cache. The familiar dict format is preserved so existing handlers
need zero changes.

NOTE: user_registry.json is a legacy data source being migrated to PostgreSQL.
All new user operations should go through UserStore (this module).
The JSON file should be deprecated and removed once migration is complete.

Architecture:
  - On startup, all users are loaded from PostgreSQL into an in-memory dict
    (same shape as the old JSON registry).
  - load_registry() returns this dict (sync, fast, no I/O).
  - save_registry() updates the in-memory dict AND schedules an async
    PostgreSQL write (fire-and-forget).
  - Since asyncio is single-threaded, there are no concurrent-modification
    races on the in-memory dict (unlike the old JSON file approach).
  - PostgreSQL is the durable backing store; JSON is written as a backup.
"""

import asyncio
import datetime
import json
import logging
import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
logger = logging.getLogger(__name__)


class UserStore:
    """Async PostgreSQL-backed user store that maintains registry dict compatibility."""

    def __init__(self, pool, json_path: Optional[Path] = None):
        """
        Args:
            pool: asyncpg connection pool (can be None for JSON-only mode).
            json_path: Path to user_registry.json for backup writes.
        """
        self.pool = pool
        self.json_path = json_path
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready and self.pool is not None

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    async def initialize(self) -> Dict[str, Any]:
        """
        Load all users from PostgreSQL into the registry dict format.
        Returns the dict. Call once at startup.
        """
        if not self.pool:
            self._ready = False
            return {}

        try:
            await self._ensure_schema()
            registry = await self._load_all_from_pg()
            self._ready = True
            logger.info(f"[UserStore] Loaded {len(registry)} users from PostgreSQL")
            return registry
        except Exception as e:
            logger.warning(f"[UserStore] Initialization failed: {e}")
            traceback.print_exc()
            self._ready = False
            return {}

    async def _ensure_schema(self):
        """Add profile_data JSONB column if it doesn't exist yet."""
        async with self.pool.acquire() as conn:
            # Check if profile_data column exists
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'profile_data'
                )
            """)
            if not exists:
                await conn.execute("""
                    ALTER TABLE users ADD COLUMN profile_data JSONB DEFAULT '{}'::jsonb
                """)
                logger.info("[UserStore] Added profile_data JSONB column to users table")

            # Ensure commonly-queried columns have indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_hardware_id ON users (hardware_id);
                CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
                CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
                CREATE INDEX IF NOT EXISTS idx_users_family_id ON users (family_id);
            """)

    # -------------------------------------------------------------------------
    # Read operations
    # -------------------------------------------------------------------------

    async def _load_all_from_pg(self) -> Dict[str, Any]:
        """Load all users from PostgreSQL and return in registry dict format."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM users
                WHERE deleted_at IS NULL
                ORDER BY created_at
            """)

        registry = {}
        for row in rows:
            key, entry = self._row_to_entry(row)
            if key:
                registry[key] = entry
        return registry

    async def get_by_username(self, username: str) -> Optional[Dict]:
        """Fetch a single user by username."""
        if not self.is_ready:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM users
                WHERE username = $1 AND deleted_at IS NULL
            """, username)
        if not row:
            return None
        _, entry = self._row_to_entry(row)
        return entry

    async def get_by_hardware_id(self, hw_id: str) -> Optional[Dict]:
        """Fetch a single user by hardware_id."""
        if not self.is_ready:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM users
                WHERE hardware_id = $1 AND deleted_at IS NULL
            """, hw_id)
        if not row:
            return None
        _, entry = self._row_to_entry(row)
        return entry

    async def get_by_role(self, role: str) -> Dict[str, Any]:
        """Get all users of a specific role."""
        if not self.is_ready:
            return {}
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM users
                WHERE role = $1 AND deleted_at IS NULL
            """, role)
        result = {}
        for row in rows:
            key, entry = self._row_to_entry(row)
            if key:
                result[key] = entry
        return result

    # -------------------------------------------------------------------------
    # Write operations
    # -------------------------------------------------------------------------

    async def upsert_user(
        self,
        registry_key: str,
        entry: Dict[str, Any],
        caller_role: str = None,
    ) -> bool:
        """Insert or update a single user from registry entry format. caller_role required for authorization."""
        # Authorization: only ADMIN can create/modify users
        if caller_role and caller_role != "ADMIN":
            logger.warning(f"[UserStore] Unauthorized upsert attempt by {caller_role}")
            return False

        creds = entry.get("credentials", {}) or {}
        profile = entry.get("profile", {}) or {}
        username = creds.get("username", registry_key)
        role = profile.get("role", "CLIENT")

        # Validate username
        if not username or len(username) > 100:
            logger.warning(f"[UserStore] Invalid username length: {len(username) if username else 0}")
            return False

        # Validate email if present
        email = profile.get("email", "") if isinstance(profile, dict) else ""
        if email and not EMAIL_RE.match(email):
            logger.warning("[UserStore] Invalid email format")
            return False

        # Validate role
        valid_roles = {"CLIENT", "COACH", "ADMIN"}
        if role and role.upper() not in valid_roles:
            logger.warning(f"[UserStore] Invalid role: {role}")
            return False

        if not self.is_ready:
            return False

        try:
            username = creds.get("username", registry_key)
            password_hash = creds.get("password", "")

            # Extract indexed columns from profile
            role = profile.get("role", "CLIENT")
            tier = (profile.get("tier") or profile.get("subscription_plan") or "STANDARD").upper()
            # Normalize tier to allowed values
            allowed_tiers = {"MASTER", "SUPERVISOR", "TOP", "STANDARD", "TRIAL", "DEPENDENT"}
            if tier not in allowed_tiers:
                tier = "STANDARD"
            name = profile.get("name", username)
            email = profile.get("email", "")
            hardware_id = profile.get("hardware_id", "")
            consent_version = profile.get("consent_version", "")

            # Normalize subscription_status
            sub_status = (profile.get("subscription_status") or "ACTIVE").upper()
            allowed_statuses = {
                "ACTIVE", "TRIAL_ACTIVE", "PENDING_VERIFICATION",
                "FAMILY_PLAN_ACTIVE", "SUSPENDED", "CANCELLED"
            }
            if sub_status not in allowed_statuses:
                sub_status = "ACTIVE"

            # Family ID: the JSON stores string like "FAM_1834DACF", not a UUID.
            # Store as NULL in the FK column, keep the string in profile_data.
            family_id_str = profile.get("family_id", "")

            # Store the full profile as JSONB for all the extra fields
            profile_data = json.dumps(profile, default=str)

            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (
                        username, password_hash, role, tier, name, email,
                        hardware_id, consent_version, subscription_status,
                        profile_data, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
                    ON CONFLICT (username) DO UPDATE SET
                        password_hash = EXCLUDED.password_hash,
                        role = EXCLUDED.role,
                        tier = EXCLUDED.tier,
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        hardware_id = EXCLUDED.hardware_id,
                        consent_version = EXCLUDED.consent_version,
                        subscription_status = EXCLUDED.subscription_status,
                        profile_data = EXCLUDED.profile_data,
                        updated_at = NOW()
                """, username, password_hash, role, tier, name, email or None,
                    hardware_id, consent_version, sub_status, profile_data)
            return True
        except Exception as e:
            logger.warning(f"[UserStore] upsert_user failed for {registry_key}: {e}")
            traceback.print_exc()
            return False

    async def save_all(self, registry: Dict[str, Any]) -> int:
        """
        Bulk upsert all users from a registry dict.
        Returns number of users successfully saved.
        """
        if not self.is_ready:
            return 0

        saved = 0
        for key, entry in registry.items():
            # Skip non-user entries (like _coach_invites, _settings, etc.)
            if key.startswith("_"):
                continue
            if not isinstance(entry, dict):
                continue
            # Must have either credentials or profile
            if not entry.get("credentials") and not entry.get("profile"):
                continue
            if await self.upsert_user(key, entry):
                saved += 1
        return saved

    async def delete_user(self, username: str, caller_role: str = None) -> bool:
        """Soft-delete a user by username."""
        if caller_role and caller_role != "ADMIN":
            logger.warning(f"[UserStore] Unauthorized delete attempt by {caller_role}")
            return False
        if not self.is_ready:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE users SET deleted_at = NOW(), updated_at = NOW()
                    WHERE username = $1
                """, username)
            return True
        except Exception as e:
            logger.warning(f"[UserStore] delete_user failed for {username}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Sync helper: schedule a background write
    # -------------------------------------------------------------------------

    def schedule_sync(self, registry: Dict[str, Any]):
        """
        Schedule a fire-and-forget async write of the registry to PostgreSQL.
        Safe to call from sync context within the asyncio event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._background_sync(registry))
        except RuntimeError:
            pass  # No running loop — skip PG write

    async def _background_sync(self, registry: Dict[str, Any]):
        """Background task to sync registry to PostgreSQL."""
        try:
            await self.save_all(registry)
        except Exception as e:
            logger.warning(f"[UserStore] Background sync failed: {e}")

    # -------------------------------------------------------------------------
    # Format conversion
    # -------------------------------------------------------------------------

    def _row_to_entry(self, row) -> Tuple[str, Dict[str, Any]]:
        """
        Convert a PostgreSQL row to registry entry format:
          {
            "credentials": {"username": "...", "password": "..."},
            "profile": { ... all profile fields ... }
          }
        """
        if not row:
            return "", {}

        username = row["username"]
        password_hash = row["password_hash"] or ""

        # Start with profile_data JSONB (has all the extra fields)
        profile_data = row.get("profile_data")
        if isinstance(profile_data, str):
            if len(profile_data) > 1_000_000:  # 1MB limit (WS-M14)
                logger.warning(f"[UserStore] Profile data too large: {len(profile_data)} bytes")
                profile = {}
            else:
                try:
                    profile = json.loads(profile_data)
                except (json.JSONDecodeError, TypeError):
                    profile = {}
        elif isinstance(profile_data, dict):
            profile = dict(profile_data)
        else:
            profile = {}

        # Overlay indexed columns (these are the source of truth over profile_data)
        profile["role"] = row["role"] or profile.get("role", "CLIENT")
        profile["name"] = row["name"] or profile.get("name", username)
        profile["email"] = row["email"] or profile.get("email", "")
        profile["hardware_id"] = row["hardware_id"] or profile.get("hardware_id", "")
        profile["consent_version"] = row["consent_version"] or profile.get("consent_version", "")
        profile["subscription_status"] = row["subscription_status"] or profile.get("subscription_status", "ACTIVE")

        # Overlay additional indexed columns when present in the row
        if row.get("tier"):
            profile["tier"] = row["tier"]
        if row.get("phone"):
            profile["phone"] = row["phone"]
        if row.get("dob"):
            profile["dob"] = str(row["dob"])
        if row.get("specialties"):
            profile["specialties"] = list(row["specialties"])
        if row.get("coaching_style"):
            profile["coaching_style"] = row["coaching_style"]

        # Numeric / timestamp columns — overlay only if the DB value is set
        if row.get("token_balance") is not None:
            profile["token_balance"] = row["token_balance"]
        if row.get("login_count") is not None:
            profile["login_count"] = row["login_count"]
        if row.get("last_login"):
            profile["last_login"] = str(row["last_login"])

        # Build the registry key (matches old JSON key format)
        role = profile.get("role", "CLIENT").lower()
        registry_key = f"{role}_{username}" if not username.startswith(f"{role}_") else username

        entry = {
            "credentials": {
                "username": username,
                "password": password_hash,
            },
            "profile": profile,
        }

        return registry_key, entry
