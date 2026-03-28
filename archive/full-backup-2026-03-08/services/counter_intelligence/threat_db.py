"""
Threat Intelligence Database — Persistent storage for attacker profiles,
attack events, canary tokens, retrieval seeds, and counter-measure logs.

Uses PostgreSQL via asyncpg for durability.  Falls back to in-memory-only
operation if no db_pool is provided.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.services.counter_intelligence.orchestrator import ThreatLevel

logger = logging.getLogger("counter_intelligence.threat_db")


class ThreatIntelligenceDB:
    """Persistence layer for counter-intelligence data."""

    def __init__(self, db_pool=None) -> None:
        self.db_pool = db_pool

    # ------------------------------------------------------------------
    # Attacker Profiles
    # ------------------------------------------------------------------

    async def upsert_profile(self, profile) -> None:
        """Insert or update an attacker profile from an AttackerProfile object."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO attacker_profiles
                        (profile_id, first_seen, last_seen, threat_level,
                         ble_fingerprint, network_fingerprint,
                         behavioral_fingerprint, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'active')
                    ON CONFLICT (profile_id) DO UPDATE SET
                        last_seen = EXCLUDED.last_seen,
                        threat_level = EXCLUDED.threat_level,
                        ble_fingerprint = EXCLUDED.ble_fingerprint,
                        network_fingerprint = EXCLUDED.network_fingerprint,
                        behavioral_fingerprint = EXCLUDED.behavioral_fingerprint
                """,
                    profile.profile_id,
                    profile.first_seen,
                    profile.last_seen,
                    profile.threat_level.name.lower(),
                    json.dumps({
                        "addresses": list(profile.ble_addresses),
                        "ad_pattern_hash": profile.ad_pattern_hash,
                    }),
                    json.dumps({
                        "ip_addresses": list(profile.ip_addresses),
                        "tls_fingerprints": list(profile.tls_fingerprints),
                        "user_agents": list(profile.user_agents),
                    }),
                    json.dumps({
                        "attack_methods": list(profile.attack_methods),
                        "signature_guesses": profile.signature_guesses[-50:],
                        "target_fibres": list(profile.target_fibres),
                        "total_events": profile.total_events,
                    }),
                )
        except Exception as e:
            logger.error("Failed to upsert profile: %s", e)

    async def get_profile(self, profile_id: UUID) -> Optional[Dict[str, Any]]:
        """Load a profile from DB."""
        if not self.db_pool:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM attacker_profiles WHERE profile_id = $1",
                    profile_id,
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error("Failed to get profile: %s", e)
            return None

    async def list_active_profiles(
        self, limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List active threat profiles, ordered by last_seen desc."""
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM attacker_profiles
                    WHERE status = 'active'
                    ORDER BY last_seen DESC
                    LIMIT $1
                """, limit)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to list profiles: %s", e)
            return []

    async def update_threat_level(
        self, profile_id: UUID, level: ThreatLevel,
    ) -> None:
        """Update the threat level for a profile."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE attacker_profiles
                    SET threat_level = $2, last_seen = NOW()
                    WHERE profile_id = $1
                """, profile_id, level.name.lower())
        except Exception as e:
            logger.error("Failed to update threat level: %s", e)

    # ------------------------------------------------------------------
    # Attack Events
    # ------------------------------------------------------------------

    async def log_event(
        self,
        profile_id: UUID,
        event_type: str,
        event_data: Dict[str, Any],
        source_layer: str = "unknown",
        target_fibre_id: Optional[str] = None,
    ) -> UUID:
        """Log a single attack event."""
        event_id = uuid4()
        if not self.db_pool:
            return event_id
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO attack_events
                        (event_id, profile_id, event_type, event_data,
                         source_layer, target_fibre_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """,
                    event_id, profile_id, event_type,
                    json.dumps(event_data, default=str),
                    source_layer, target_fibre_id,
                )
        except Exception as e:
            logger.error("Failed to log event: %s", e)
        return event_id

    async def get_events_for_profile(
        self, profile_id: UUID, limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch events for a specific attacker profile."""
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM attack_events
                    WHERE profile_id = $1
                    ORDER BY occurred_at DESC
                    LIMIT $2
                """, profile_id, limit)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get events: %s", e)
            return []

    # ------------------------------------------------------------------
    # Canary Tokens
    # ------------------------------------------------------------------

    async def register_canary(
        self,
        canary_id: UUID,
        canary_type: str,
        target_attacker: Optional[UUID] = None,
        payload_hash: Optional[str] = None,
    ) -> None:
        """Register a new canary token."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO canary_tokens
                        (canary_id, canary_type, target_attacker, payload_hash)
                    VALUES ($1, $2, $3, $4)
                """, canary_id, canary_type, target_attacker, payload_hash)
        except Exception as e:
            logger.error("Failed to register canary: %s", e)

    async def trigger_canary(
        self, canary_id: UUID, trigger_data: Dict[str, Any],
    ) -> None:
        """Record a canary token being triggered."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE canary_tokens
                    SET triggered_at = NOW(), trigger_data = $2
                    WHERE canary_id = $1
                """, canary_id, json.dumps(trigger_data, default=str))
        except Exception as e:
            logger.error("Failed to trigger canary: %s", e)

    # ------------------------------------------------------------------
    # Retrieval Seeds
    # ------------------------------------------------------------------

    async def register_seed(
        self,
        seed_id: UUID,
        seed_type: str,
        target_attacker: Optional[UUID] = None,
        deployed_via: str = "unknown",
    ) -> None:
        """Register a deployed retrieval seed."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO retrieval_seeds
                        (seed_id, seed_type, target_attacker, deployed_via)
                    VALUES ($1, $2, $3, $4)
                """, seed_id, seed_type, target_attacker, deployed_via)
        except Exception as e:
            logger.error("Failed to register seed: %s", e)

    async def record_seed_activation(
        self, seed_id: UUID, intelligence: Dict[str, Any],
    ) -> None:
        """Record a retrieval seed being activated (phoned home)."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE retrieval_seeds
                    SET activation_count = activation_count + 1,
                        last_activation = NOW(),
                        intelligence = COALESCE(intelligence, '[]'::jsonb) || $2::jsonb
                    WHERE seed_id = $1
                """, seed_id, json.dumps([intelligence], default=str))
        except Exception as e:
            logger.error("Failed to record seed activation: %s", e)

    # ------------------------------------------------------------------
    # Counter-Measure Log
    # ------------------------------------------------------------------

    async def log_counter_measure(
        self,
        attacker_id: UUID,
        measure_type: str,
        result: Optional[Dict[str, Any]] = None,
        effectiveness_score: Optional[float] = None,
    ) -> UUID:
        """Log a counter-measure deployment."""
        log_id = uuid4()
        if not self.db_pool:
            return log_id
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO counter_measure_log
                        (log_id, attacker_id, measure_type,
                         effectiveness_score, result)
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    log_id, attacker_id, measure_type,
                    effectiveness_score,
                    json.dumps(result or {}, default=str),
                )
        except Exception as e:
            logger.error("Failed to log counter-measure: %s", e)
        return log_id

    # ------------------------------------------------------------------
    # Aggregate Queries
    # ------------------------------------------------------------------

    async def get_threat_summary(self) -> Dict[str, Any]:
        """High-level summary for the admin dashboard."""
        if not self.db_pool:
            return {"active_threats": 0, "events_24h": 0, "canaries_triggered": 0}
        try:
            async with self.db_pool.acquire() as conn:
                active = await conn.fetchval(
                    "SELECT COUNT(*) FROM attacker_profiles WHERE status = 'active'"
                )
                events_24h = await conn.fetchval("""
                    SELECT COUNT(*) FROM attack_events
                    WHERE occurred_at > NOW() - INTERVAL '24 hours'
                """)
                canaries = await conn.fetchval(
                    "SELECT COUNT(*) FROM canary_tokens WHERE triggered_at IS NOT NULL"
                )
                return {
                    "active_threats": active or 0,
                    "events_24h": events_24h or 0,
                    "canaries_triggered": canaries or 0,
                }
        except Exception as e:
            logger.error("Failed to get threat summary: %s", e)
            return {"active_threats": 0, "events_24h": 0, "canaries_triggered": 0}
