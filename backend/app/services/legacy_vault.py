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
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID, uuid4

from app.services.exceptions import (
    ConsentWithdrawnException,
    LegacyVaultException,
)


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
        except Exception:
            pass

        return profile

    # =========================================================================
    # STORAGE HELPERS
    # =========================================================================

    async def _store_vault_entry(
        self, entry_type: str, family_id, data: Dict
    ) -> None:
        """Store an entry in the Legacy Vault (PostgreSQL JSONB + optional blob)."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO legacy_vault_entries
                        (entry_type, family_id, data, created_at)
                    VALUES ($1, $2, $3, NOW())
                """, entry_type, family_id, json.dumps(data, default=str))
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
        except Exception:
            return []
