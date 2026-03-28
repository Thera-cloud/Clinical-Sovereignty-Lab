"""
SOVEREIGN SWARM — Legacy Vault
Transgenerational pattern storage and family emotional inheritance maps.

Components:
    - Family Emotional Inheritance Map
    - Pattern Interruption Record
    - Legacy Transformation Tracking
    - Generational Consent Framework

Phase 4B — Code Guidelines Section VI.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID, uuid4

from app.services.exceptions import (
    ConsentWithdrawnException,
    LegacyVaultException,
)

logger = logging.getLogger(__name__)


class LegacyVault:
    """
    Stores and manages transgenerational family data with
    full consent management and transformation tracking.
    """

    def __init__(self, db_pool, blob_storage=None):
        self.db_pool = db_pool
        self.blob_storage = blob_storage
        self._consent_cache: Dict[Any, Dict[Any, bool]] = {}  # family_id -> {user_id: consent}

    # =========================================================================
    # CONSENT FRAMEWORK
    # =========================================================================

    async def grant_consent(self, user_id, family_id) -> Dict:
        """Grant consent for transgenerational analysis."""
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO legacy_vault_consent (user_id, family_id, consented)
                VALUES ($1, $2, TRUE)
                ON CONFLICT (user_id, family_id) DO UPDATE SET consented = TRUE, updated_at = NOW()
            """, user_id, family_id)

        # Update cache
        if family_id not in self._consent_cache:
            self._consent_cache[family_id] = {}
        self._consent_cache[family_id][user_id] = True

        return {"user_id": user_id, "family_id": family_id, "consented": True}

    async def withdraw_consent(self, user_id, family_id) -> Dict:
        """
        Withdraw consent — data from this member must be excluded
        from all transgenerational analyses.
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO legacy_vault_consent (user_id, family_id, consented)
                VALUES ($1, $2, FALSE)
                ON CONFLICT (user_id, family_id) DO UPDATE SET consented = FALSE, updated_at = NOW()
            """, user_id, family_id)

        if family_id in self._consent_cache:
            self._consent_cache[family_id][user_id] = False

        return {"user_id": user_id, "family_id": family_id, "consented": False}

    async def get_consented_members(self, family_id) -> List:
        """Get list of family members who have granted consent."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id FROM legacy_vault_consent
                WHERE family_id = $1 AND consented = TRUE
            """, family_id)
            return [r["user_id"] for r in rows]

    async def check_consent(self, user_id, family_id) -> bool:
        """Check if a user has consented to transgenerational analysis."""
        if family_id in self._consent_cache:
            if user_id in self._consent_cache[family_id]:
                return self._consent_cache[family_id][user_id]

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT consented FROM legacy_vault_consent
                WHERE user_id = $1 AND family_id = $2
            """, user_id, family_id)
            consented = row["consented"] if row else False

            if family_id not in self._consent_cache:
                self._consent_cache[family_id] = {}
            self._consent_cache[family_id][user_id] = consented

            return consented

    # =========================================================================
    # FAMILY EMOTIONAL INHERITANCE MAP
    # =========================================================================

    async def create_inheritance_map(self, family_id) -> Dict[str, Any]:
        """
        Create a visual/data representation of emotional pattern flow
        across family members, respecting consent boundaries.
        """
        consented = await self.get_consented_members(family_id)

        if len(consented) < 2:
            return {
                "family_id": family_id,
                "status": "insufficient_consent",
                "consented_members": len(consented),
                "required": 2,
            }

        # Get pattern analysis from pattern engine
        from app.services.pattern_engine import TransgenerationalPatternEngine
        engine = TransgenerationalPatternEngine(self.db_pool)

        # Only include consented members' data
        themes = await engine.analyze_emotional_themes(family_id)

        # Filter to consented members only
        filtered_themes = {}
        for theme, member_ids in themes.get("shared_themes", {}).items():
            filtered_ids = [uid for uid in member_ids if str(uid) in [str(c) for c in consented]]
            if len(filtered_ids) >= 2:
                filtered_themes[theme] = filtered_ids

        inheritance_map = {
            "map_id": str(uuid4()),
            "family_id": family_id,
            "consented_members": consented,
            "shared_emotional_patterns": filtered_themes,
            "theme_correlation": themes.get("theme_correlation", 0),
            "generation_flow": [],  # populated when generation data available
            "created_at": datetime.utcnow().isoformat(),
        }

        # Store in vault
        await self._store_vault_entry("inheritance_map", family_id, inheritance_map)

        return inheritance_map

    # =========================================================================
    # PATTERN INTERRUPTION RECORD
    # =========================================================================

    async def record_pattern_interruption(
        self, family_id, user_id,
        pattern_name: str,
        interruption_description: str,
        outcome: str = "in_progress",
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Record where therapeutic intervention successfully interrupted
        a transgenerational pattern.
        """
        if not await self.check_consent(user_id, family_id):
            raise ConsentWithdrawnException(user_id=user_id, family_id=family_id)

        record = {
            "record_id": str(uuid4()),
            "family_id": family_id,
            "user_id": user_id,
            "pattern_name": pattern_name,
            "interruption_description": interruption_description,
            "outcome": outcome,
            "metadata": metadata or {},
            "recorded_at": datetime.utcnow().isoformat(),
        }

        await self._store_vault_entry("pattern_interruption", family_id, record)
        return record

    async def get_pattern_interruptions(self, family_id) -> List[Dict]:
        """Get all pattern interruption records for a family."""
        return await self._get_vault_entries("pattern_interruption", family_id)

    # =========================================================================
    # LEGACY TRANSFORMATION TRACKING
    # =========================================================================

    async def track_transformation(
        self, family_id,
        description: str,
        coherence_before: float,
        coherence_after: float,
        members_involved: List,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Track a long-term family coherence transformation."""
        # Filter to consented members
        consented = await self.get_consented_members(family_id)
        involved = [m for m in members_involved if m in consented]

        transformation = {
            "transformation_id": str(uuid4()),
            "family_id": family_id,
            "description": description,
            "coherence_before": coherence_before,
            "coherence_after": coherence_after,
            "improvement": round(coherence_after - coherence_before, 4),
            "members_involved": involved,
            "tracked_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }

        await self._store_vault_entry("transformation", family_id, transformation)
        return transformation

    async def get_transformation_history(self, family_id) -> List[Dict]:
        """Get transformation history for a family."""
        return await self._get_vault_entries("transformation", family_id)

    # =========================================================================
    # FAMILY COHERENCE PROFILE
    # =========================================================================

    async def get_family_profile(self, family_id) -> Dict[str, Any]:
        """
        Complete family coherence profile including inheritance maps,
        pattern interruptions, and transformation history.
        """
        profile = {
            "family_id": family_id,
            "generated_at": datetime.utcnow().isoformat(),
        }

        try:
            profile["inheritance_map"] = await self.create_inheritance_map(family_id)
        except Exception as e:
            profile["inheritance_map"] = {"error": str(e)}

        try:
            profile["pattern_interruptions"] = await self.get_pattern_interruptions(family_id)
        except Exception as e:
            profile["pattern_interruptions"] = {"error": str(e)}

        try:
            profile["transformations"] = await self.get_transformation_history(family_id)
        except Exception as e:
            profile["transformations"] = {"error": str(e)}

        # Current coherence
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT score, components, measured_at
                    FROM coherence_measurements
                    WHERE layer = 'family' AND family_id = $1
                    ORDER BY measured_at DESC LIMIT 1
                """, family_id)
                if row:
                    profile["current_coherence"] = {
                        "score": float(row["score"]),
                        "measured_at": row["measured_at"].isoformat(),
                    }
        except Exception as e:
            logger.debug("DB query for current coherence: %s", e)

        return profile

    # =========================================================================
    # STORAGE HELPERS
    # =========================================================================

    # Storage tier limits in bytes (matching billing.py / standing_orders_seed.json)
    _STORAGE_LIMITS_BYTES = {
        "TOP_TIER": 50 * 1024 * 1024 * 1024,   # 50 GB
        "SOVEREIGN_CIRCLE": 50 * 1024 * 1024 * 1024,
        "STANDARD": 1 * 1024 * 1024 * 1024,    # 1 GB
        "INNER_CHAMBER": 1 * 1024 * 1024 * 1024,
        # TRIAL / COACH_ONLY: 0 (no vault access)
    }

    async def _get_family_vault_usage_bytes(self, family_id) -> int:
        """Get total vault storage used by a family (estimated from JSON data size)."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchval("""
                    SELECT COALESCE(SUM(octet_length(data::text)), 0)
                    FROM legacy_vault_entries
                    WHERE family_id = $1
                """, family_id)
                return int(result or 0)
        except Exception as e:
            logger.debug("Vault usage query failed: %s", e)
            return 0

    async def _get_family_head_plan(self, family_id) -> str:
        """Look up the subscription plan of the family head (or any TOP_TIER member)."""
        try:
            # Try registry-based lookup first (file-based user store)
            import json as _json
            from pathlib import Path
            from app.config import settings as _s
            reg_path = Path(_s.DATA_DIR) / "user_registry.json"
            if reg_path.is_file():
                registry = _json.loads(reg_path.read_text())
                best_plan = ""
                for _k, entry in registry.items():
                    prof = entry.get("profile", {})
                    if prof.get("family_id") == str(family_id):
                        plan = (prof.get("subscription_plan") or "").upper()
                        if plan in ("TOP_TIER", "SOVEREIGN_CIRCLE"):
                            return plan
                        if plan == "STANDARD" and best_plan != "TOP_TIER":
                            best_plan = plan
                return best_plan
        except Exception as e:
            logger.debug("Family head plan lookup failed: %s", e)
        return ""

    async def _store_vault_entry(
        self, entry_type: str, family_id, data: Dict
    ) -> None:
        """Store an entry in the Legacy Vault (PostgreSQL JSONB + optional blob).
        Enforces per-tier storage limits: STANDARD 1 GB, TOP_TIER 50 GB."""

        # --- Storage limit enforcement ---
        plan = await self._get_family_head_plan(family_id)
        limit = self._STORAGE_LIMITS_BYTES.get(plan, 0)
        if limit > 0:
            current_usage = await self._get_family_vault_usage_bytes(family_id)
            entry_size = len(json.dumps(data, default=str).encode("utf-8"))
            if current_usage + entry_size > limit:
                limit_gb = limit / (1024 ** 3)
                usage_gb = current_usage / (1024 ** 3)
                raise LegacyVaultException(
                    f"Legacy Vault storage limit exceeded. "
                    f"Plan: {plan} ({limit_gb:.0f} GB limit). "
                    f"Current usage: {usage_gb:.2f} GB. "
                    f"Upgrade to Sovereign Circle for 50 GB."
                )
        elif not plan or plan in ("TRIAL", "COACH_ONLY"):
            raise LegacyVaultException(
                "Legacy Vault storage requires Inner Chamber or Sovereign Circle subscription."
            )

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO legacy_vault_entries
                        (entry_type, family_id, data, created_at)
                    VALUES ($1, $2, $3, NOW())
                """, entry_type, family_id, json.dumps(data, default=str))
        except LegacyVaultException:
            raise
        except Exception as e:
            print(f">>> [LEGACY VAULT] Storage error: {e}"
                  f" (ensure migration 009_legacy_vault.sql has been applied)")

    async def _get_vault_entries(
        self, entry_type: str, family_id
    ) -> List[Dict]:
        """Retrieve entries from the Legacy Vault."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT data, created_at
                    FROM legacy_vault_entries
                    WHERE entry_type = $1 AND family_id = $2
                    ORDER BY created_at DESC
                """, entry_type, family_id)
                return [json.loads(r["data"]) if isinstance(r["data"], str) else r["data"] for r in rows]
        except Exception as e:
            logger.debug("DB query vault entries by type: %s", e)
            return []

    async def get_vault_entries(
        self, family_id, entry_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve vault entries for a family.
        If entry_type is None, returns entries of all types.
        """
        try:
            async with self.db_pool.acquire() as conn:
                if entry_type:
                    rows = await conn.fetch("""
                        SELECT entry_type, data, created_at
                        FROM legacy_vault_entries
                        WHERE family_id = $1 AND entry_type = $2
                        ORDER BY created_at DESC
                    """, family_id, entry_type)
                else:
                    rows = await conn.fetch("""
                        SELECT entry_type, data, created_at
                        FROM legacy_vault_entries
                        WHERE family_id = $1
                        ORDER BY created_at DESC
                    """, family_id)
                result = []
                for r in rows:
                    data = r["data"]
                    if isinstance(data, str):
                        data = json.loads(data)
                    result.append({
                        "entry_type": r["entry_type"],
                        "data": data,
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    })
                return result
        except Exception as e:
            logger.debug("DB query full vault entries list: %s", e)
            return []

    async def get_inheritance_map(self, family_id) -> Dict[str, Any]:
        """Get or create the latest inheritance map for a family."""
        return await self.create_inheritance_map(family_id)

    async def check_family_consent(self, family_id) -> Dict[str, Any]:
        """Check consent status for all family members."""
        consented = await self.get_consented_members(family_id)
        return {
            "family_id": str(family_id),
            "consented_members": [str(u) for u in consented],
            "consent_count": len(consented),
        }

    # =========================================================================
    # DATA SOVEREIGNTY API (PhD Spec §11.4)
    # =========================================================================

    async def access_all_data(self, user_id) -> Dict[str, Any]:
        """
        Right of Access — return all data the system holds on this user.
        Includes sessions, insights, coherence measurements, vault entries,
        nudges, and consent records.
        """
        async with self.db_pool.acquire() as conn:
            sessions = await conn.fetch(
                "SELECT session_id, started_at, ended_at, summary FROM sessions WHERE user_id = $1 ORDER BY started_at DESC",
                user_id,
            )
            insights = await conn.fetch(
                "SELECT insight_id, insight_text, strength, growth_area, created_at FROM nate_insights WHERE user_id = $1 ORDER BY created_at DESC",
                user_id,
            )
            coherence = await conn.fetch(
                "SELECT layer, score, measured_at FROM coherence_measurements WHERE user_id = $1 ORDER BY measured_at DESC LIMIT 500",
                user_id,
            )
            nudges = await conn.fetch(
                "SELECT nudge_type, title, content, created_at, status FROM nate_nudges WHERE user_id = $1 ORDER BY created_at DESC",
                user_id,
            )
            consent_rows = await conn.fetch(
                "SELECT family_id, consented, data_types, updated_at FROM legacy_vault_consent WHERE user_id = $1",
                user_id,
            )

        return {
            "user_id": str(user_id),
            "sessions": [dict(r) for r in sessions],
            "insights": [dict(r) for r in insights],
            "coherence_measurements": [dict(r) for r in coherence],
            "nudges": [dict(r) for r in nudges],
            "consent_records": [dict(r) for r in consent_rows],
            "exported_at": datetime.utcnow().isoformat(),
        }

    async def correct_data(
        self, user_id, table: str, record_id, corrections: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Right of Rectification — allow user to correct inaccurate data.
        Only allowed on user-facing tables: nate_insights, users (name/email).
        """
        ALLOWED_TABLES = {
            "nate_insights": {"columns": ["insight_text", "strength", "growth_area"], "id_col": "insight_id"},
            "users": {"columns": ["name", "email"], "id_col": "id"},
        }
        if table not in ALLOWED_TABLES:
            raise LegacyVaultException(f"Corrections not allowed on table '{table}'")

        spec = ALLOWED_TABLES[table]
        set_clauses = []
        params = []
        idx = 1
        for col, val in corrections.items():
            if col in spec["columns"]:
                set_clauses.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
            else:
                raise LegacyVaultException(f"Column '{col}' not correctable on '{table}'")

        if not set_clauses:
            return {"status": "no_corrections"}

        params.append(record_id)
        params.append(user_id)

        async with self.db_pool.acquire() as conn:
            result = await conn.execute(f"""
                UPDATE {table}
                SET {', '.join(set_clauses)}, updated_at = NOW()
                WHERE {spec['id_col']} = ${idx} AND user_id = ${idx + 1}
            """, *params)

            # Audit trail
            await conn.execute("""
                INSERT INTO audit_log (action_type, target_id, description, ip_address)
                VALUES ('DATA_CORRECTION', $1, $2, '0.0.0.0'::inet)
            """, user_id, f"Corrected {table}.{list(corrections.keys())} on record {record_id}")

        return {"status": "corrected", "table": table, "record_id": str(record_id), "fields": list(corrections.keys())}

    async def restrict_sharing(self, user_id, family_id, restricted: bool = True) -> Dict[str, Any]:
        """
        Right to Restrict Processing — prevent data from being used
        in transgenerational analysis without full withdrawal.
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO legacy_vault_consent (user_id, family_id, consented, sharing_restricted)
                VALUES ($1, $2, TRUE, $3)
                ON CONFLICT (user_id, family_id)
                DO UPDATE SET sharing_restricted = $3, updated_at = NOW()
            """, user_id, family_id, restricted)

        return {
            "user_id": str(user_id),
            "family_id": str(family_id),
            "sharing_restricted": restricted,
        }

    async def export_portable(self, user_id) -> Dict[str, Any]:
        """
        Right to Data Portability — export all user data in a portable
        JSON format that can be transferred to another system.
        """
        data = await self.access_all_data(user_id)

        # Add user profile
        async with self.db_pool.acquire() as conn:
            profile = await conn.fetchrow(
                "SELECT name, email, role, tier, family_id, created_at FROM users WHERE id = $1",
                user_id,
            )
            if profile:
                data["profile"] = dict(profile)

            # Add vault entries for all families
            family_id = profile["family_id"] if profile else None
            if family_id:
                entries = await self.get_vault_entries(family_id)
                data["legacy_vault_entries"] = entries

        data["export_format"] = "sovereign_sanctuary_v1"
        data["portable"] = True
        return data

    async def minimize_data(self, user_id, retain_months: int = 6) -> Dict[str, Any]:
        """
        Data Minimization — delete data older than retain_months while
        keeping aggregated coherence summaries intact.
        """
        from datetime import timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=retain_months * 30)
        deleted = {}

        async with self.db_pool.acquire() as conn:
            # Delete old session transcripts (keep session metadata)
            r = await conn.execute("""
                UPDATE sessions SET transcript = NULL
                WHERE user_id = $1 AND started_at < $2 AND transcript IS NOT NULL
            """, user_id, cutoff)
            deleted["session_transcripts_cleared"] = r.split()[-1] if r else "0"

            # Delete old raw coherence measurements (keep monthly averages via briefings)
            r = await conn.execute("""
                DELETE FROM coherence_measurements
                WHERE user_id = $1 AND measured_at < $2
            """, user_id, cutoff)
            deleted["coherence_measurements_deleted"] = r.split()[-1] if r else "0"

            # Delete old nudges that were dismissed or opened
            r = await conn.execute("""
                DELETE FROM nate_nudges
                WHERE user_id = $1 AND created_at < $2 AND status IN ('dismissed', 'opened')
            """, user_id, cutoff)
            deleted["old_nudges_deleted"] = r.split()[-1] if r else "0"

            # Audit
            await conn.execute("""
                INSERT INTO audit_log (action_type, target_id, description, ip_address)
                VALUES ('DATA_MINIMIZATION', $1, $2, '0.0.0.0'::inet)
            """, user_id, f"Minimized data older than {retain_months} months")

        return {
            "user_id": str(user_id),
            "cutoff": cutoff.isoformat(),
            "retain_months": retain_months,
            "deleted": deleted,
        }

    # =========================================================================
    # ENHANCED GENERATIONAL CONSENT (PhD Spec §11.3)
    # =========================================================================

    async def grant_granular_consent(
        self, user_id, family_id,
        data_types: Optional[List[str]] = None,
        is_minor: bool = False,
        guardian_id=None,
    ) -> Dict[str, Any]:
        """
        Grant consent with per-data-type granularity and minor/guardian support.

        data_types: list of allowed data types, e.g.
            ["emotional_themes", "coping_mechanisms", "coherence_scores",
             "session_transcripts", "trigger_patterns"]
            None = all types consented

        is_minor: if True, guardian_id must be provided
        guardian_id: the adult user who provides assent on behalf of the minor
        """
        if is_minor and not guardian_id:
            raise LegacyVaultException(
                "Minor consent requires a guardian_id for assent"
            )

        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO legacy_vault_consent
                    (user_id, family_id, consented, data_types, is_minor, guardian_id)
                VALUES ($1, $2, TRUE, $3, $4, $5)
                ON CONFLICT (user_id, family_id) DO UPDATE SET
                    consented = TRUE,
                    data_types = $3,
                    is_minor = $4,
                    guardian_id = $5,
                    updated_at = NOW()
            """, user_id, family_id,
                 json.dumps(data_types) if data_types else None,
                 is_minor,
                 guardian_id,
            )

        # Update cache
        if family_id not in self._consent_cache:
            self._consent_cache[family_id] = {}
        self._consent_cache[family_id][user_id] = True

        return {
            "user_id": str(user_id),
            "family_id": str(family_id),
            "consented": True,
            "data_types": data_types or "all",
            "is_minor": is_minor,
            "guardian_id": str(guardian_id) if guardian_id else None,
        }

    async def check_data_type_consent(
        self, user_id, family_id, data_type: str
    ) -> bool:
        """
        Check if a specific data type is consented for this user.
        Returns True if consent is granted for the specific type or for all types.
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT consented, data_types, sharing_restricted
                FROM legacy_vault_consent
                WHERE user_id = $1 AND family_id = $2
            """, user_id, family_id)

        if not row or not row["consented"]:
            return False
        if row.get("sharing_restricted"):
            return False
        dt = row.get("data_types")
        if dt is None:
            return True  # All types consented
        try:
            allowed = json.loads(dt) if isinstance(dt, str) else dt
            return data_type in allowed
        except Exception:
            return True  # If parsing fails, default to full consent

    async def get_family_multi_party_consent(self, family_id) -> Dict[str, Any]:
        """
        Multi-party consent status: shows each member's consent scope,
        data types, and minor/guardian relationships.
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT lvc.user_id, u.name, lvc.consented, lvc.data_types,
                       lvc.is_minor, lvc.guardian_id, lvc.sharing_restricted,
                       lvc.updated_at
                FROM legacy_vault_consent lvc
                JOIN users u ON u.id = lvc.user_id
                WHERE lvc.family_id = $1
            """, family_id)

        members = []
        for r in rows:
            dt = r.get("data_types")
            if dt and isinstance(dt, str):
                try:
                    dt = json.loads(dt)
                except Exception:
                    dt = None
            members.append({
                "user_id": str(r["user_id"]),
                "name": r["name"],
                "consented": r["consented"],
                "data_types": dt or "all",
                "is_minor": r.get("is_minor", False),
                "guardian_id": str(r["guardian_id"]) if r.get("guardian_id") else None,
                "sharing_restricted": r.get("sharing_restricted", False),
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
            })

        # Determine overall family consent status
        all_consented = all(m["consented"] for m in members) if members else False
        minors = [m for m in members if m["is_minor"]]
        minors_with_guardian = [m for m in minors if m["guardian_id"]]

        return {
            "family_id": str(family_id),
            "members": members,
            "total_members": len(members),
            "all_consented": all_consented,
            "minors_count": len(minors),
            "minors_with_guardian_assent": len(minors_with_guardian),
            "any_sharing_restricted": any(m["sharing_restricted"] for m in members),
        }
