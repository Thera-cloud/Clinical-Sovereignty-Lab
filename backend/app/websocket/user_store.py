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

# Resolve families.family_code onto registry profiles when users.family_id is set (FK wins).
_USER_FROM_ROW = """
SELECT u.*, f.family_code AS resolved_family_code
FROM users u
LEFT JOIN families f ON f.id = u.family_id
"""


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
            rows = await conn.fetch(_USER_FROM_ROW + """
                WHERE u.deleted_at IS NULL
                ORDER BY u.created_at
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
            row = await conn.fetchrow(
                _USER_FROM_ROW + " WHERE u.username = $1 AND u.deleted_at IS NULL",
                username,
            )
        if not row:
            return None
        _, entry = self._row_to_entry(row)
        return entry

    async def get_by_hardware_id(self, hw_id: str) -> Optional[Dict]:
        """Fetch a single user by hardware_id."""
        if not self.is_ready:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                _USER_FROM_ROW + " WHERE u.hardware_id = $1 AND u.deleted_at IS NULL",
                hw_id,
            )
        if not row:
            return None
        _, entry = self._row_to_entry(row)
        return entry

    async def get_by_role(self, role: str) -> Dict[str, Any]:
        """Get all users of a specific role."""
        if not self.is_ready:
            return {}
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                _USER_FROM_ROW + " WHERE u.role = $1 AND u.deleted_at IS NULL",
                role,
            )
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
            raw_tier = (profile.get("tier") or profile.get("subscription_plan") or "STANDARD").upper()
            _TIER_ALIAS = {
                "SOVEREIGN_CIRCLE": "TOP_TIER", "SOVEREIGN": "TOP_TIER", "TOP": "TOP_TIER",
                "INNER_CHAMBER": "STANDARD", "INNER": "STANDARD", "THRESHOLD": "TRIAL",
                "COACH_ONLY": "STANDARD", "FAMILY_MEMBER": "STANDARD",
                "FAMILY_DEPENDENT": "DEPENDENT",
            }
            tier = _TIER_ALIAS.get(raw_tier, raw_tier)
            allowed_tiers = {"MASTER", "SUPERVISOR", "TOP", "TOP_TIER", "STANDARD", "TRIAL", "DEPENDENT"}
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

            family_id_str = profile.get("family_id", "")

            # Extract numeric fields that have dedicated PG columns
            token_balance = profile.get("token_balance")
            if token_balance is not None:
                try:
                    token_balance = int(token_balance)
                except (ValueError, TypeError):
                    token_balance = None

            def _pi(val, default=None):
                if val is None:
                    return default
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return default

            purch_bal = _pi(profile.get("purchased_token_balance"), 0) or 0
            sub_bal = _pi(profile.get("subscription_token_balance"), None)
            if sub_bal is None and token_balance is not None:
                sub_bal = max(0, int(token_balance) - purch_bal)
            elif sub_bal is None:
                sub_bal = 0
            if token_balance is None:
                token_balance = sub_bal + purch_bal

            login_count = profile.get("login_count")
            if login_count is not None:
                try:
                    login_count = int(login_count)
                except (ValueError, TypeError):
                    login_count = None

            # Store the full profile as JSONB for all the extra fields
            profile_data = json.dumps(profile, default=str)

            phone_col = profile.get("phone")
            if phone_col is not None:
                phone_col = str(phone_col).strip() or None
            tz_col = str(profile.get("timezone") or "UTC").strip() or "UTC"
            tz_src_col = str(profile.get("timezone_source") or "default_utc").strip() or "default_utc"

            async with self.pool.acquire() as conn:
                # Resolve family code (e.g. "FAM_1834DACF") to families.id UUID
                family_uuid = None
                if family_id_str:
                    family_uuid = await conn.fetchval(
                        "SELECT id FROM families WHERE family_code = $1",
                        family_id_str,
                    )

                await conn.execute("""
                    INSERT INTO users (
                        username, password_hash, role, tier, name, email,
                        hardware_id, consent_version, subscription_status,
                        family_id, profile_data, token_balance,
                        subscription_token_balance, purchased_token_balance,
                        login_count,
                        phone, timezone, timezone_source,
                        updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb,
                              COALESCE($12, 0), COALESCE($13, 0), COALESCE($14, 0),
                              COALESCE($15, 0),
                              $16, $17, $18,
                              NOW())
                    ON CONFLICT (username) DO UPDATE SET
                        -- SOVEREIGN-VOICE 2026-04-28: never let bridge cache overwrite a
                        -- DB-set password_hash with empty/null. Mitigates bridge-cache
                        -- clobber risk when admin/reset paths or external SQL update creds.
                        -- Note: stale-but-non-empty cache values can still overwrite; always
                        -- restart nate_bridge after any external password_hash UPDATE.
                        password_hash = COALESCE(NULLIF(EXCLUDED.password_hash, ''), users.password_hash),
                        role = EXCLUDED.role,
                        tier = COALESCE(users.tier, EXCLUDED.tier),
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        hardware_id = EXCLUDED.hardware_id,
                        consent_version = COALESCE(EXCLUDED.consent_version, users.consent_version),
                        subscription_status = COALESCE(users.subscription_status, EXCLUDED.subscription_status),
                        family_id = COALESCE(EXCLUDED.family_id, users.family_id),
                        profile_data = COALESCE(EXCLUDED.profile_data::jsonb, '{}'::jsonb)
                            || COALESCE(
                                (SELECT jsonb_object_agg(key, value)
                                 FROM jsonb_each(COALESCE(users.profile_data, '{}'::jsonb))
                                 WHERE key = ANY(ARRAY[
                                     'token_balance',
                                     'totp_enabled', 'totp_secret',
                                     'sms_verified', 'sms_phone', 'admin_verify_phone',
                                     'webauthn_enabled', 'webauthn_credentials',
                                     'webauthn_challenge', 'webauthn_challenge_issued_at',
                                     'webauthn_auth_challenge', 'webauthn_auth_challenge_issued_at',
                                     'sentinel_frozen',
                                     'checkin_snooze_until',
                                     'import_batch_id', 'import_source',
                                     'subscription_plan', 'subscription_status',
                                     'account_status', 'force_password_reset',
                                     'deletion_requested_at',
                                     'certification_status', 'coach_verified',
                                     'coaching_fee', 'w9_submitted', 'w9_data',
                                     'stripe_customer_id',
                                     'free_month_start', 'free_month_end',
                                     'token_usage_today', 'token_usage_month',
                                     'last_token_reset',
                                     'qb_connected', 'qb_realm_id',
                                     'subscription_token_balance', 'purchased_token_balance'
                                 ])),
                                '{}'::jsonb
                            ),
                        token_balance = COALESCE(users.token_balance, EXCLUDED.token_balance, 0),
                        subscription_token_balance = COALESCE(
                            users.subscription_token_balance, EXCLUDED.subscription_token_balance, 0
                        ),
                        purchased_token_balance = COALESCE(
                            users.purchased_token_balance, EXCLUDED.purchased_token_balance, 0
                        ),
                        login_count = COALESCE(EXCLUDED.login_count, users.login_count),
                        phone = COALESCE(NULLIF(EXCLUDED.phone, ''), users.phone),
                        timezone = CASE
                          WHEN EXCLUDED.timezone_source = 'user_explicit' THEN EXCLUDED.timezone
                          WHEN users.timezone_source = 'user_explicit' THEN users.timezone
                          ELSE COALESCE(NULLIF(EXCLUDED.timezone, ''), users.timezone, 'UTC')
                        END,
                        timezone_source = CASE
                          WHEN EXCLUDED.timezone_source = 'user_explicit' THEN 'user_explicit'
                          WHEN users.timezone_source = 'user_explicit' THEN 'user_explicit'
                          ELSE COALESCE(NULLIF(EXCLUDED.timezone_source, ''), users.timezone_source, 'default_utc')
                        END,
                        timezone_updated_at = CASE
                          WHEN EXCLUDED.timezone IS DISTINCT FROM users.timezone
                            OR EXCLUDED.timezone_source IS DISTINCT FROM users.timezone_source
                          THEN NOW()
                          ELSE COALESCE(users.timezone_updated_at, NOW())
                        END,
                        updated_at = NOW()
                """, username, password_hash, role, tier, name, email or None,
                    hardware_id, consent_version, sub_status, family_uuid, profile_data,
                    token_balance, sub_bal, purch_bal, login_count,
                    phone_col, tz_col, tz_src_col)
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

    async def upsert_single(self, registry_key: str, entry: Dict[str, Any]) -> bool:
        """Upsert a single user entry. Use for targeted writes (registration, password change)."""
        if not self.is_ready:
            return False
        return await self.upsert_user(registry_key, entry)

    # -------------------------------------------------------------------------
    # Sync helpers: schedule background writes
    # -------------------------------------------------------------------------

    def schedule_sync(self, registry: Dict[str, Any], changed_keys: List[str] = None):
        """
        Schedule a fire-and-forget async write to PostgreSQL.
        If changed_keys is provided, only those users are written (O(k) instead of O(n)).
        """
        try:
            loop = asyncio.get_running_loop()
            if changed_keys:
                loop.create_task(self._background_sync_keys(registry, changed_keys))
            else:
                loop.create_task(self._background_sync(registry))
        except RuntimeError:
            pass

    async def _background_sync_keys(self, registry: Dict[str, Any], keys: List[str]):
        """Write only the specified registry keys to PostgreSQL."""
        try:
            written = 0
            for key in keys:
                entry = registry.get(key)
                if entry and isinstance(entry, dict):
                    if entry.get("credentials") or entry.get("profile"):
                        if await self.upsert_user(key, entry):
                            written += 1
            if written:
                logger.debug("[UserStore] Targeted sync: %d/%d keys written", written, len(keys))
        except Exception as e:
            logger.warning("[UserStore] Targeted sync failed: %s", e)

    async def _background_sync(self, registry: Dict[str, Any]):
        """Full registry sync — used only for initial load and shutdown."""
        try:
            await self.save_all(registry)
        except Exception as e:
            logger.warning("[UserStore] Background sync failed: %s", e)

    async def reload_user(self, username: str) -> Optional[Tuple[str, Dict]]:
        """Reload a single user from PostgreSQL. Returns (registry_key, entry) or None."""
        if not self.is_ready:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    _USER_FROM_ROW + " WHERE u.username = $1 AND u.deleted_at IS NULL",
                    username,
                )
            if row:
                key, entry = self._row_to_entry(row)
                return (key, entry)
        except Exception as e:
            logger.warning("[UserStore] reload_user failed for %s: %s", username, e)
        return None

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
        profile["username"] = username
        profile["role"] = row["role"] or profile.get("role", "CLIENT")
        profile["name"] = row["name"] or profile.get("name", username)
        _raw_email = row["email"] or profile.get("email", "")
        if _raw_email and isinstance(_raw_email, str) and _raw_email.startswith("gAAAAA"):
            try:
                from app.services.pii_cipher import decrypt_pii
                _raw_email = decrypt_pii(_raw_email) or _raw_email
            except Exception:
                pass
        profile["email"] = _raw_email
        profile["hardware_id"] = row["hardware_id"] or profile.get("hardware_id", "")
        profile["consent_version"] = row["consent_version"] or profile.get("consent_version", "")
        profile["subscription_status"] = row["subscription_status"] or profile.get("subscription_status", "ACTIVE")

        # Family Sanctuary / registry: honor FK → canonical family_code for websocket handlers.
        rfam = row.get("resolved_family_code")
        if rfam:
            profile["family_id"] = rfam

        # Overlay additional indexed columns when present in the row
        if row.get("tier"):
            profile["tier"] = row["tier"]
        if row.get("phone"):
            profile["phone"] = row["phone"]
        tz_r = row.get("timezone")
        if tz_r:
            profile["timezone"] = tz_r
        tzs_r = row.get("timezone_source")
        if tzs_r:
            profile["timezone_source"] = tzs_r
        if row.get("dob"):
            profile["dob"] = str(row["dob"])
        if row.get("specialties"):
            profile["specialties"] = list(row["specialties"])
        if row.get("coaching_style"):
            profile["coaching_style"] = row["coaching_style"]

        # Numeric / timestamp columns — overlay only if the DB value is set
        if row.get("token_balance") is not None:
            profile["token_balance"] = row["token_balance"]
        if row.get("subscription_token_balance") is not None:
            profile["subscription_token_balance"] = row["subscription_token_balance"]
        if row.get("purchased_token_balance") is not None:
            profile["purchased_token_balance"] = row["purchased_token_balance"]
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
