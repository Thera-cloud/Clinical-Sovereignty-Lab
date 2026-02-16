"""
HIVE DEFENSE PROTOCOL — Mesh Isolation (Phase 8A)
Containment perimeter formation for compromised entities.

When the Curiosity Protocol reaches ALARM, Mesh Isolation executes the
physical containment of the compromised entity.  This module manages:

    1. **Entity Isolation** — Partitions the mesh segment around the
       compromised entity, severing all data and communication channels.
    2. **Defensive Perimeter** — Ring partners form a protective boundary,
       monitoring the isolation zone boundary for escape attempts.
    3. **Data Quarantine** — All data originating from or accessed by the
       compromised entity is quarantined for forensic review.
    4. **Containment Zones** — Logical zones that can be created, expanded,
       merged, or deactivated as the investigation progresses.
    5. **Release Protocol** — Isolation can only be lifted by explicit
       human authorization, preserving chain of custody.

Hive Event Topics:
    - hive.isolation.mesh_partitioned — Containment perimeter is active
    - hive.isolation.entity_quarantined — Compromised entity isolated

Patent-Pending — Claim 30
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.models.hive_defense import (
    ForensicRecord,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class IsolationStatus(str, Enum):
    """Current state of an entity's mesh isolation."""
    ACTIVE = "active"               # Entity is fully isolated
    PERIMETER_FORMED = "perimeter"  # Defensive perimeter active, monitoring
    QUARANTINED = "quarantined"     # Data quarantine in effect
    PARTIAL = "partial"             # Some channels severed, others monitored
    RELEASED = "released"           # Isolation lifted by authorized human
    NONE = "none"                   # No isolation


class ContainmentZoneStatus(str, Enum):
    """Lifecycle state of a containment zone."""
    CREATING = "creating"
    ACTIVE = "active"
    EXPANDING = "expanding"
    MERGED = "merged"
    DEACTIVATING = "deactivating"
    DEACTIVATED = "deactivated"


# =============================================================================
# CONTAINMENT ZONE
# =============================================================================

class ContainmentZone:
    """
    A logical containment zone within the mesh.

    Containment zones are created when entities are isolated and define the
    boundary within which the compromised entity (and potentially its
    immediate neighbors) are contained.  Zones can expand if the compromise
    spreads, and can be merged when multiple isolations are related.

    Attributes:
        zone_id: Unique identifier for this containment zone.
        status: Current lifecycle status.
        isolated_entities: Set of entity UUIDs within this zone.
        perimeter_entities: Set of entity UUIDs forming the defensive boundary.
        quarantined_data_keys: Set of data keys quarantined in this zone.
        created_at: Timestamp of zone creation.
        created_by: Identifier of the system or human that triggered creation.
        metadata: Additional context about the zone.
    """

    __slots__ = (
        "zone_id",
        "status",
        "isolated_entities",
        "perimeter_entities",
        "quarantined_data_keys",
        "created_at",
        "created_by",
        "deactivated_at",
        "deactivated_by",
        "metadata",
    )

    def __init__(
        self,
        zone_id: Optional[UUID] = None,
        created_by: str = "curiosity_protocol",
    ) -> None:
        self.zone_id: UUID = zone_id or uuid4()
        self.status: ContainmentZoneStatus = ContainmentZoneStatus.CREATING
        self.isolated_entities: Set[UUID] = set()
        self.perimeter_entities: Set[UUID] = set()
        self.quarantined_data_keys: Set[str] = set()
        self.created_at: datetime = datetime.utcnow()
        self.created_by: str = created_by
        self.deactivated_at: Optional[datetime] = None
        self.deactivated_by: Optional[str] = None
        self.metadata: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the containment zone for API responses."""
        return {
            "zone_id": str(self.zone_id),
            "status": self.status.value,
            "isolated_entities": [str(e) for e in self.isolated_entities],
            "perimeter_entities": [str(e) for e in self.perimeter_entities],
            "quarantined_data_keys": list(self.quarantined_data_keys),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "deactivated_at": (
                self.deactivated_at.isoformat() if self.deactivated_at else None
            ),
            "deactivated_by": self.deactivated_by,
            "metadata": self.metadata,
        }


# =============================================================================
# ISOLATION RECORD (per-entity)
# =============================================================================

class EntityIsolationRecord:
    """
    Tracks the isolation state and history for a single entity.

    Maintains the current status, the containment zone the entity belongs
    to, the reason for isolation, and the full audit trail of status changes.
    """

    __slots__ = (
        "entity_id",
        "status",
        "zone_id",
        "reason",
        "isolated_at",
        "released_at",
        "released_by",
        "perimeter_active",
        "data_quarantined",
        "audit_trail",
    )

    def __init__(self, entity_id: UUID, reason: str = "") -> None:
        self.entity_id: UUID = entity_id
        self.status: IsolationStatus = IsolationStatus.NONE
        self.zone_id: Optional[UUID] = None
        self.reason: str = reason
        self.isolated_at: Optional[datetime] = None
        self.released_at: Optional[datetime] = None
        self.released_by: Optional[str] = None
        self.perimeter_active: bool = False
        self.data_quarantined: bool = False
        self.audit_trail: List[Dict[str, Any]] = []

    def _record_audit(self, action: str, details: str = "") -> None:
        """Append an entry to the audit trail."""
        self.audit_trail.append({
            "action": action,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the isolation record for API responses."""
        return {
            "entity_id": str(self.entity_id),
            "status": self.status.value,
            "zone_id": str(self.zone_id) if self.zone_id else None,
            "reason": self.reason,
            "isolated_at": (
                self.isolated_at.isoformat() if self.isolated_at else None
            ),
            "released_at": (
                self.released_at.isoformat() if self.released_at else None
            ),
            "released_by": self.released_by,
            "perimeter_active": self.perimeter_active,
            "data_quarantined": self.data_quarantined,
            "audit_trail_length": len(self.audit_trail),
        }


# =============================================================================
# MESH ISOLATION SERVICE
# =============================================================================

class MeshIsolation:
    """
    Containment perimeter formation for compromised hive entities.

    Manages the lifecycle of mesh isolation — from initial entity partition
    through defensive perimeter formation, data quarantine, and eventual
    release.  All actions are logged to the forensic chain for immutable
    evidence preservation.

    Integration points:
        - CuriosityProtocol — triggers isolation at ALARM level
        - ForensicLogger    — preserves evidence chain for all actions
        - Hive event bus    — publishes isolation events
        - Database          — persists isolation state and audit trail

    Usage::

        isolation = MeshIsolation(
            db_pool=pool,
            forensic_logger=forensic_log,
        )
        await isolation.isolate_entity(entity_id, "Three-Cord failure")
        await isolation.form_defensive_perimeter(entity_id)
        await isolation.quarantine_data(entity_id)

        # Later, after investigation:
        await isolation.release_isolation(entity_id, authorized_by="nate")

    Patent-Pending — Claim 30.
    """

    def __init__(
        self,
        db_pool=None,
        forensic_logger=None,
        event_bus=None,
    ) -> None:
        """
        Initialize the Mesh Isolation service.

        Args:
            db_pool: asyncpg connection pool for persistence.
            forensic_logger: ForensicLogger instance for evidence chain.
            event_bus: Hive event bus for publishing isolation events.
        """
        self.db_pool = db_pool
        self._forensic_logger = forensic_logger
        self._event_bus = event_bus

        # In-memory tracking
        self._isolation_records: Dict[UUID, EntityIsolationRecord] = {}
        self._containment_zones: Dict[UUID, ContainmentZone] = {}

        # Reverse index: entity_id → zone_id
        self._entity_zone_map: Dict[UUID, UUID] = {}

        logger.info(">>> [ISOLATION] Mesh Isolation service initialized")

    # =========================================================================
    # ENTITY ISOLATION
    # =========================================================================

    async def isolate_entity(
        self, entity_id: UUID, reason: str
    ) -> Dict[str, Any]:
        """
        Partition the mesh segment around a compromised entity.

        This is the primary isolation entry point.  It:
            1. Creates or retrieves the entity's isolation record.
            2. Creates a new containment zone for the entity.
            3. Severs all mesh communication channels for the entity.
            4. Marks the entity as quarantined in the database.
            5. Logs forensic evidence and fires hive events.

        Args:
            entity_id: UUID of the entity to isolate.
            reason: Human-readable reason for the isolation.

        Returns:
            Dictionary with isolation details and zone information.
        """
        now = datetime.utcnow()

        # Get or create isolation record
        record = self._get_or_create_record(entity_id, reason)
        record.status = IsolationStatus.ACTIVE
        record.isolated_at = now
        record.reason = reason
        record._record_audit("isolated", reason)

        # Create containment zone
        zone = self._create_containment_zone(entity_id, reason)
        record.zone_id = zone.zone_id

        # Sever mesh channels in database
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Mark entity as isolated in fibres table
                    await conn.execute("""
                        UPDATE fibres
                        SET status = 'isolated',
                            isolated_at = $2,
                            isolation_reason = $3,
                            updated_at = NOW()
                        WHERE fibre_id = $1
                    """, entity_id, now, reason)

                    # Block all mesh message routing to/from entity
                    await conn.execute("""
                        INSERT INTO mesh_blocks
                            (entity_id, block_type, reason, zone_id)
                        VALUES ($1, 'full_isolation', $2, $3)
                        ON CONFLICT (entity_id, block_type)
                        DO UPDATE SET
                            reason = EXCLUDED.reason,
                            zone_id = EXCLUDED.zone_id,
                            updated_at = NOW()
                    """, entity_id, reason, zone.zone_id)

                    # Persist isolation record
                    await conn.execute("""
                        INSERT INTO isolation_records
                            (entity_id, zone_id, status, reason, isolated_at)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (entity_id)
                        DO UPDATE SET
                            zone_id = EXCLUDED.zone_id,
                            status = EXCLUDED.status,
                            reason = EXCLUDED.reason,
                            isolated_at = EXCLUDED.isolated_at,
                            updated_at = NOW()
                    """, entity_id, zone.zone_id,
                        IsolationStatus.ACTIVE.value, reason, now)

            except Exception as exc:
                logger.error(
                    ">>> [ISOLATION] DB isolation failed for %s: %s",
                    entity_id, exc,
                )

        # Forensic evidence
        await self._log_forensic(
            event_type="mesh_isolation_activated",
            source_entity=str(entity_id),
            evidence={
                "reason": reason,
                "zone_id": str(zone.zone_id),
                "status": IsolationStatus.ACTIVE.value,
            },
        )

        # Fire hive event
        await self._fire_event(
            "hive.isolation.mesh_partitioned",
            entity_id,
            {
                "reason": reason,
                "zone_id": str(zone.zone_id),
                "action": "entity_isolated",
            },
        )

        logger.warning(
            ">>> [ISOLATION] Entity %s ISOLATED — zone %s — %s",
            entity_id, zone.zone_id, reason,
        )

        return {
            "entity_id": str(entity_id),
            "status": IsolationStatus.ACTIVE.value,
            "zone_id": str(zone.zone_id),
            "reason": reason,
            "isolated_at": now.isoformat(),
        }

    # =========================================================================
    # DEFENSIVE PERIMETER
    # =========================================================================

    async def form_defensive_perimeter(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Form a defensive perimeter around the isolated entity.

        Ring partners adjacent to the compromised entity are enlisted to
        monitor the containment zone boundary.  They watch for:
            - Escape attempts (data exfiltration from the zone)
            - Lateral movement (compromise spreading to neighbors)
            - Communication probes (the entity testing for open channels)

        Args:
            entity_id: UUID of the isolated entity.

        Returns:
            Dictionary with perimeter details and enlisted partners.
        """
        record = self._isolation_records.get(entity_id)
        if not record or record.status == IsolationStatus.NONE:
            logger.warning(
                ">>> [ISOLATION] Cannot form perimeter — %s is not isolated",
                entity_id,
            )
            return {
                "entity_id": str(entity_id),
                "error": "Entity is not currently isolated",
            }

        zone = self._containment_zones.get(record.zone_id) if record.zone_id else None
        perimeter_partners: List[str] = []

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Find ring partners (adjacent entities in the mesh)
                    partners = await conn.fetch("""
                        SELECT member_id FROM ring_membership
                        WHERE ring_id = (
                            SELECT ring_id FROM ring_membership
                            WHERE member_id = $1
                            LIMIT 1
                        )
                        AND member_id != $1
                    """, entity_id)

                    for partner in partners:
                        partner_id = partner["member_id"]
                        perimeter_partners.append(str(partner_id))

                        # Assign perimeter duty
                        await conn.execute("""
                            INSERT INTO perimeter_assignments
                                (entity_id, zone_id, watching_entity_id, assigned_at)
                            VALUES ($1, $2, $3, NOW())
                            ON CONFLICT (entity_id, zone_id)
                            DO UPDATE SET
                                watching_entity_id = EXCLUDED.watching_entity_id,
                                updated_at = NOW()
                        """, partner_id,
                            record.zone_id or uuid4(),
                            entity_id)

                        # Add to zone's perimeter set
                        if zone:
                            zone.perimeter_entities.add(partner_id)

            except Exception as exc:
                logger.error(
                    ">>> [ISOLATION] Perimeter formation DB error: %s", exc,
                )

        record.perimeter_active = True
        record.status = IsolationStatus.PERIMETER_FORMED
        record._record_audit(
            "perimeter_formed",
            f"{len(perimeter_partners)} partners enlisted",
        )

        # Forensic evidence
        await self._log_forensic(
            event_type="defensive_perimeter_formed",
            source_entity=str(entity_id),
            evidence={
                "zone_id": str(record.zone_id) if record.zone_id else None,
                "perimeter_partners": perimeter_partners,
                "partner_count": len(perimeter_partners),
            },
        )

        logger.info(
            ">>> [ISOLATION] Defensive perimeter formed for %s — %d partners",
            entity_id, len(perimeter_partners),
        )

        return {
            "entity_id": str(entity_id),
            "status": IsolationStatus.PERIMETER_FORMED.value,
            "zone_id": str(record.zone_id) if record.zone_id else None,
            "perimeter_partners": perimeter_partners,
            "partner_count": len(perimeter_partners),
        }

    # =========================================================================
    # DATA QUARANTINE
    # =========================================================================

    async def quarantine_data(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Quarantine all data associated with the compromised entity.

        Moves all data authored by, accessed by, or referencing the entity
        into a quarantine zone for forensic review.  This includes:
            - Mesh messages sent by the entity
            - Journal entries and evolution records
            - Conclusions and observations produced by the entity
            - Any shared resources the entity contributed to

        Args:
            entity_id: UUID of the entity whose data should be quarantined.

        Returns:
            Dictionary with quarantine details and affected data counts.
        """
        record = self._isolation_records.get(entity_id)
        if not record:
            record = self._get_or_create_record(entity_id, "data_quarantine")

        quarantine_counts = {
            "messages": 0,
            "journal_entries": 0,
            "conclusions": 0,
            "shared_resources": 0,
        }

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Quarantine mesh messages
                    result = await conn.execute("""
                        UPDATE mesh_messages
                        SET quarantined = TRUE,
                            quarantined_at = NOW(),
                            quarantine_zone_id = $2
                        WHERE sender_id = $1
                          AND quarantined = FALSE
                    """, entity_id, record.zone_id or uuid4())
                    quarantine_counts["messages"] = _extract_count(result)

                    # Quarantine journal entries
                    result = await conn.execute("""
                        UPDATE fibre_journal
                        SET quarantined = TRUE,
                            quarantined_at = NOW()
                        WHERE fibre_id = $1
                          AND quarantined = FALSE
                    """, entity_id)
                    quarantine_counts["journal_entries"] = _extract_count(result)

                    # Quarantine conclusions/observations
                    result = await conn.execute("""
                        UPDATE fibre_conclusions
                        SET quarantined = TRUE,
                            quarantined_at = NOW()
                        WHERE fibre_id = $1
                          AND quarantined = FALSE
                    """, entity_id)
                    quarantine_counts["conclusions"] = _extract_count(result)

                    # Quarantine shared resource contributions
                    result = await conn.execute("""
                        UPDATE shared_resources
                        SET quarantined = TRUE,
                            quarantined_at = NOW()
                        WHERE contributed_by = $1
                          AND quarantined = FALSE
                    """, entity_id)
                    quarantine_counts["shared_resources"] = _extract_count(result)

                    # Update isolation record in DB
                    await conn.execute("""
                        UPDATE isolation_records
                        SET data_quarantined = TRUE,
                            quarantine_counts = $2,
                            updated_at = NOW()
                        WHERE entity_id = $1
                    """, entity_id, json.dumps(quarantine_counts))

            except Exception as exc:
                logger.error(
                    ">>> [ISOLATION] Data quarantine DB error for %s: %s",
                    entity_id, exc,
                )

        record.data_quarantined = True
        record.status = IsolationStatus.QUARANTINED
        record._record_audit(
            "data_quarantined",
            f"Quarantined: {json.dumps(quarantine_counts)}",
        )

        # Track quarantined data keys in the zone
        zone = self._containment_zones.get(record.zone_id) if record.zone_id else None
        if zone:
            for category, count in quarantine_counts.items():
                if count > 0:
                    zone.quarantined_data_keys.add(
                        f"{entity_id}:{category}"
                    )

        # Forensic evidence
        await self._log_forensic(
            event_type="data_quarantined",
            source_entity=str(entity_id),
            evidence={
                "quarantine_counts": quarantine_counts,
                "zone_id": str(record.zone_id) if record.zone_id else None,
            },
        )

        # Fire hive event
        await self._fire_event(
            "hive.isolation.entity_quarantined",
            entity_id,
            {
                "quarantine_counts": quarantine_counts,
                "zone_id": str(record.zone_id) if record.zone_id else None,
            },
        )

        total = sum(quarantine_counts.values())
        logger.warning(
            ">>> [ISOLATION] Data quarantined for %s — %d items across %d categories",
            entity_id, total, sum(1 for v in quarantine_counts.values() if v > 0),
        )

        return {
            "entity_id": str(entity_id),
            "status": IsolationStatus.QUARANTINED.value,
            "quarantine_counts": quarantine_counts,
            "total_items": total,
            "zone_id": str(record.zone_id) if record.zone_id else None,
        }

    # =========================================================================
    # STATUS QUERY
    # =========================================================================

    def get_isolation_status(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Return the current isolation state for an entity.

        Args:
            entity_id: UUID of the entity to query.

        Returns:
            Dictionary with isolation status, zone info, and audit summary.
        """
        record = self._isolation_records.get(entity_id)
        if not record:
            return {
                "entity_id": str(entity_id),
                "status": IsolationStatus.NONE.value,
                "isolated": False,
            }

        result = record.to_dict()

        # Attach zone details if available
        if record.zone_id and record.zone_id in self._containment_zones:
            zone = self._containment_zones[record.zone_id]
            result["zone"] = zone.to_dict()

        result["isolated"] = record.status not in (
            IsolationStatus.NONE,
            IsolationStatus.RELEASED,
        )

        return result

    async def get_isolation_status_from_db(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Query the database for the entity's persisted isolation state.

        Useful when in-memory state may not be current (e.g., after restart
        before full state restoration).

        Args:
            entity_id: UUID of the entity to query.

        Returns:
            Dictionary with persisted isolation details.
        """
        if not self.db_pool:
            return self.get_isolation_status(entity_id)

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT entity_id, zone_id, status, reason,
                           isolated_at, released_at, released_by,
                           data_quarantined, quarantine_counts
                    FROM isolation_records
                    WHERE entity_id = $1
                """, entity_id)

            if not row:
                return {
                    "entity_id": str(entity_id),
                    "status": IsolationStatus.NONE.value,
                    "isolated": False,
                }

            return {
                "entity_id": str(row["entity_id"]),
                "zone_id": str(row["zone_id"]) if row["zone_id"] else None,
                "status": row["status"],
                "reason": row["reason"],
                "isolated_at": (
                    row["isolated_at"].isoformat() if row["isolated_at"] else None
                ),
                "released_at": (
                    row["released_at"].isoformat() if row["released_at"] else None
                ),
                "released_by": row["released_by"],
                "data_quarantined": row["data_quarantined"],
                "quarantine_counts": (
                    json.loads(row["quarantine_counts"])
                    if row["quarantine_counts"]
                    else {}
                ),
                "isolated": row["status"] not in (
                    IsolationStatus.NONE.value,
                    IsolationStatus.RELEASED.value,
                ),
            }

        except Exception as exc:
            logger.error(
                ">>> [ISOLATION] DB status query failed for %s: %s",
                entity_id, exc,
            )
            return self.get_isolation_status(entity_id)

    # =========================================================================
    # RELEASE ISOLATION
    # =========================================================================

    async def release_isolation(
        self, entity_id: UUID, authorized_by: str
    ) -> Dict[str, Any]:
        """
        Release an entity from mesh isolation.

        **Requires explicit human authorization.**  This is a security-critical
        operation that restores the entity's mesh communication channels
        and deactivates the containment zone.

        The release process:
            1. Validates that the entity is currently isolated.
            2. Records the human authorization in the audit trail.
            3. Removes mesh communication blocks.
            4. Restores entity status to 'active' in the database.
            5. Deactivates the containment zone.
            6. Logs forensic evidence of the release.
            7. Fires hive event for system-wide notification.

        Note: Quarantined data remains in quarantine after release.  Data
        must be separately reviewed and restored by an authorized human.

        Args:
            entity_id: UUID of the entity to release.
            authorized_by: Identifier of the human authorizing the release.
                Must be a recognized administrator or Big Nate.

        Returns:
            Dictionary with release details and audit confirmation.
        """
        record = self._isolation_records.get(entity_id)
        if not record or record.status in (
            IsolationStatus.NONE, IsolationStatus.RELEASED
        ):
            logger.warning(
                ">>> [ISOLATION] Cannot release %s — not currently isolated",
                entity_id,
            )
            return {
                "entity_id": str(entity_id),
                "error": "Entity is not currently isolated",
                "status": record.status.value if record else IsolationStatus.NONE.value,
            }

        if not authorized_by:
            logger.error(
                ">>> [ISOLATION] Release rejected for %s — no authorization provided",
                entity_id,
            )
            return {
                "entity_id": str(entity_id),
                "error": "Human authorization required to release isolation",
            }

        now = datetime.utcnow()
        old_status = record.status

        # Update record
        record.status = IsolationStatus.RELEASED
        record.released_at = now
        record.released_by = authorized_by
        record.perimeter_active = False
        record._record_audit(
            "released",
            f"Authorized by {authorized_by}",
        )

        # Database operations
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Restore entity status
                    await conn.execute("""
                        UPDATE fibres
                        SET status = 'active',
                            isolated_at = NULL,
                            isolation_reason = NULL,
                            updated_at = NOW()
                        WHERE fibre_id = $1
                    """, entity_id)

                    # Remove mesh blocks
                    await conn.execute("""
                        DELETE FROM mesh_blocks
                        WHERE entity_id = $1
                    """, entity_id)

                    # Remove perimeter assignments
                    if record.zone_id:
                        await conn.execute("""
                            DELETE FROM perimeter_assignments
                            WHERE zone_id = $1
                        """, record.zone_id)

                    # Update isolation record
                    await conn.execute("""
                        UPDATE isolation_records
                        SET status = $2,
                            released_at = $3,
                            released_by = $4,
                            updated_at = NOW()
                        WHERE entity_id = $1
                    """, entity_id,
                        IsolationStatus.RELEASED.value,
                        now, authorized_by)

            except Exception as exc:
                logger.error(
                    ">>> [ISOLATION] Release DB error for %s: %s",
                    entity_id, exc,
                )

        # Deactivate containment zone
        if record.zone_id:
            await self.deactivate_zone(record.zone_id, authorized_by)

        # Forensic evidence
        await self._log_forensic(
            event_type="isolation_released",
            source_entity=str(entity_id),
            evidence={
                "authorized_by": authorized_by,
                "previous_status": old_status.value,
                "zone_id": str(record.zone_id) if record.zone_id else None,
                "data_still_quarantined": record.data_quarantined,
            },
        )

        # Fire all-clear event
        await self._fire_event(
            "hive.defense.all_clear",
            entity_id,
            {
                "authorized_by": authorized_by,
                "zone_id": str(record.zone_id) if record.zone_id else None,
                "action": "isolation_released",
            },
        )

        logger.info(
            ">>> [ISOLATION] Entity %s RELEASED by %s (was %s)",
            entity_id, authorized_by, old_status.value,
        )

        return {
            "entity_id": str(entity_id),
            "status": IsolationStatus.RELEASED.value,
            "authorized_by": authorized_by,
            "released_at": now.isoformat(),
            "previous_status": old_status.value,
            "data_still_quarantined": record.data_quarantined,
            "zone_id": str(record.zone_id) if record.zone_id else None,
        }

    # =========================================================================
    # CONTAINMENT ZONE MANAGEMENT
    # =========================================================================

    def _create_containment_zone(
        self, entity_id: UUID, reason: str
    ) -> ContainmentZone:
        """
        Create a new containment zone for an isolated entity.

        Args:
            entity_id: UUID of the entity triggering zone creation.
            reason: Reason for zone creation.

        Returns:
            The newly created ContainmentZone.
        """
        zone = ContainmentZone(created_by="curiosity_protocol")
        zone.isolated_entities.add(entity_id)
        zone.status = ContainmentZoneStatus.ACTIVE
        zone.metadata["trigger_reason"] = reason
        zone.metadata["trigger_entity"] = str(entity_id)

        self._containment_zones[zone.zone_id] = zone
        self._entity_zone_map[entity_id] = zone.zone_id

        logger.info(
            ">>> [ISOLATION] Containment zone %s created for entity %s",
            zone.zone_id, entity_id,
        )
        return zone

    async def expand_zone(
        self, zone_id: UUID, additional_entity_id: UUID, reason: str = ""
    ) -> Dict[str, Any]:
        """
        Expand a containment zone to include an additional entity.

        Used when the compromise is found to have spread to a neighboring
        entity.  The zone boundary expands to encompass the new entity
        and its perimeter is updated.

        Args:
            zone_id: UUID of the zone to expand.
            additional_entity_id: UUID of the entity to add.
            reason: Reason for expansion.

        Returns:
            Dictionary with updated zone details.
        """
        zone = self._containment_zones.get(zone_id)
        if not zone:
            return {"error": f"Zone {zone_id} not found"}

        if zone.status in (
            ContainmentZoneStatus.DEACTIVATING,
            ContainmentZoneStatus.DEACTIVATED,
        ):
            return {"error": f"Zone {zone_id} is {zone.status.value}"}

        old_status = zone.status
        zone.status = ContainmentZoneStatus.EXPANDING
        zone.isolated_entities.add(additional_entity_id)
        self._entity_zone_map[additional_entity_id] = zone_id

        # Isolate the additional entity
        await self.isolate_entity(additional_entity_id, reason or "Zone expansion")

        zone.status = ContainmentZoneStatus.ACTIVE
        zone.metadata[f"expanded_{datetime.utcnow().isoformat()}"] = {
            "added_entity": str(additional_entity_id),
            "reason": reason,
        }

        await self._log_forensic(
            event_type="containment_zone_expanded",
            source_entity=str(additional_entity_id),
            evidence={
                "zone_id": str(zone_id),
                "total_isolated": len(zone.isolated_entities),
                "reason": reason,
            },
        )

        logger.warning(
            ">>> [ISOLATION] Zone %s expanded — now contains %d entities",
            zone_id, len(zone.isolated_entities),
        )

        return zone.to_dict()

    async def merge_zones(
        self, zone_id_a: UUID, zone_id_b: UUID, reason: str = ""
    ) -> Dict[str, Any]:
        """
        Merge two containment zones into one.

        Used when two separate isolations are determined to be part of the
        same incident.  Zone B is absorbed into Zone A.

        Args:
            zone_id_a: UUID of the primary zone (absorber).
            zone_id_b: UUID of the secondary zone (absorbed).
            reason: Reason for the merge.

        Returns:
            Dictionary with the merged zone details.
        """
        zone_a = self._containment_zones.get(zone_id_a)
        zone_b = self._containment_zones.get(zone_id_b)

        if not zone_a or not zone_b:
            missing = []
            if not zone_a:
                missing.append(str(zone_id_a))
            if not zone_b:
                missing.append(str(zone_id_b))
            return {"error": f"Zone(s) not found: {', '.join(missing)}"}

        # Absorb zone B into zone A
        zone_a.isolated_entities.update(zone_b.isolated_entities)
        zone_a.perimeter_entities.update(zone_b.perimeter_entities)
        zone_a.quarantined_data_keys.update(zone_b.quarantined_data_keys)
        zone_a.metadata[f"merged_{datetime.utcnow().isoformat()}"] = {
            "absorbed_zone": str(zone_id_b),
            "reason": reason,
        }

        # Update entity→zone mappings
        for eid in zone_b.isolated_entities:
            self._entity_zone_map[eid] = zone_id_a

        # Mark zone B as merged
        zone_b.status = ContainmentZoneStatus.MERGED
        zone_b.metadata["merged_into"] = str(zone_id_a)

        await self._log_forensic(
            event_type="containment_zones_merged",
            source_entity=str(zone_id_a),
            target_entity=str(zone_id_b),
            evidence={
                "primary_zone": str(zone_id_a),
                "absorbed_zone": str(zone_id_b),
                "total_isolated": len(zone_a.isolated_entities),
                "reason": reason,
            },
        )

        logger.info(
            ">>> [ISOLATION] Zones merged: %s absorbed %s — %d total entities",
            zone_id_a, zone_id_b, len(zone_a.isolated_entities),
        )

        return zone_a.to_dict()

    async def deactivate_zone(
        self, zone_id: UUID, authorized_by: str
    ) -> Dict[str, Any]:
        """
        Deactivate a containment zone after the incident is resolved.

        Args:
            zone_id: UUID of the zone to deactivate.
            authorized_by: Identifier of the authorizing human.

        Returns:
            Dictionary with deactivation details.
        """
        zone = self._containment_zones.get(zone_id)
        if not zone:
            return {"error": f"Zone {zone_id} not found"}

        zone.status = ContainmentZoneStatus.DEACTIVATING
        zone.deactivated_at = datetime.utcnow()
        zone.deactivated_by = authorized_by

        # Clear perimeter assignments
        zone.perimeter_entities.clear()

        zone.status = ContainmentZoneStatus.DEACTIVATED

        await self._log_forensic(
            event_type="containment_zone_deactivated",
            source_entity=str(zone_id),
            evidence={
                "authorized_by": authorized_by,
                "entities_were_isolated": [
                    str(e) for e in zone.isolated_entities
                ],
            },
        )

        logger.info(
            ">>> [ISOLATION] Zone %s deactivated by %s",
            zone_id, authorized_by,
        )

        return zone.to_dict()

    def list_active_zones(self) -> List[Dict[str, Any]]:
        """
        List all currently active containment zones.

        Returns:
            List of serialized zone dictionaries.
        """
        return [
            zone.to_dict()
            for zone in self._containment_zones.values()
            if zone.status in (
                ContainmentZoneStatus.ACTIVE,
                ContainmentZoneStatus.EXPANDING,
            )
        ]

    def get_zone(self, zone_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Retrieve details for a specific containment zone.

        Args:
            zone_id: UUID of the zone to query.

        Returns:
            Serialized zone dictionary, or None if not found.
        """
        zone = self._containment_zones.get(zone_id)
        return zone.to_dict() if zone else None

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _get_or_create_record(
        self, entity_id: UUID, reason: str = ""
    ) -> EntityIsolationRecord:
        """
        Retrieve or create an isolation record for the entity.

        Args:
            entity_id: UUID of the entity.
            reason: Initial reason (used only on creation).

        Returns:
            EntityIsolationRecord for the entity.
        """
        if entity_id not in self._isolation_records:
            self._isolation_records[entity_id] = EntityIsolationRecord(
                entity_id, reason
            )
        return self._isolation_records[entity_id]

    async def _log_forensic(
        self,
        event_type: str,
        source_entity: str,
        evidence: Dict[str, Any],
        target_entity: Optional[str] = None,
    ) -> None:
        """
        Log an event to the forensic evidence chain.

        Delegates to the ForensicLogger if available, otherwise falls back
        to database direct-write.

        Args:
            event_type: Type classification for the forensic event.
            source_entity: String identifier of the source entity.
            evidence: Structured evidence payload.
            target_entity: Optional target entity identifier.
        """
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type=event_type,
                    source_entity=source_entity,
                    target_entity=target_entity,
                    evidence=evidence,
                )
                return
            except Exception as exc:
                logger.error(
                    ">>> [ISOLATION] Forensic logger error: %s", exc,
                )

        # Fallback: direct DB write
        if self.db_pool:
            try:
                record = ForensicRecord(
                    event_type=event_type,
                    source_entity=source_entity,
                    target_entity=target_entity,
                    evidence=evidence,
                )
                record.compute_chain_hash()

                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO forensic_records
                            (record_id, event_type, source_entity,
                             target_entity, evidence, chain_hash,
                             previous_record_hash, timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                        record.record_id,
                        record.event_type,
                        record.source_entity,
                        record.target_entity,
                        json.dumps(record.evidence),
                        record.chain_hash,
                        record.previous_record_hash,
                        record.timestamp,
                    )
            except Exception as exc:
                logger.error(
                    ">>> [ISOLATION] Forensic DB fallback error: %s", exc,
                )

    async def _fire_event(
        self,
        topic: str,
        entity_id: UUID,
        payload: Dict[str, Any],
    ) -> None:
        """
        Publish an event to the hive event bus.

        Args:
            topic: Event topic string (from HIVE_EVENT_TOPICS).
            entity_id: UUID of the affected entity.
            payload: Event payload dictionary.
        """
        event_data = {
            "topic": topic,
            "entity_id": str(entity_id),
            "timestamp": datetime.utcnow().isoformat(),
            **payload,
        }

        # Publish to event bus
        if self._event_bus:
            try:
                await self._event_bus.publish(topic, event_data)
            except Exception as exc:
                logger.error(
                    ">>> [ISOLATION] Event bus publish error: %s", exc,
                )

        # Persist to hive_events table
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO hive_events (topic, entity_id, payload)
                        VALUES ($1, $2, $3)
                    """, topic, entity_id, json.dumps(event_data))
            except Exception as exc:
                logger.warning(
                    ">>> [ISOLATION] Event persist error: %s", exc,
                )

    # =========================================================================
    # STATE RESTORATION
    # =========================================================================

    async def load_persisted_state(self) -> int:
        """
        Load all persisted isolation states from the database on startup.

        Restores in-memory isolation records and containment zones so that
        active isolations are enforced across restarts.

        Returns:
            Number of active isolation records restored.
        """
        if not self.db_pool:
            return 0

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT entity_id, zone_id, status, reason,
                           isolated_at, released_at, released_by,
                           data_quarantined
                    FROM isolation_records
                    WHERE status NOT IN ('none', 'released')
                """)

            restored = 0
            for row in rows:
                entity_id = row["entity_id"]
                record = self._get_or_create_record(entity_id, row["reason"] or "")
                record.status = IsolationStatus(row["status"])
                record.zone_id = row["zone_id"]
                record.isolated_at = row["isolated_at"]
                record.released_at = row["released_at"]
                record.released_by = row["released_by"]
                record.data_quarantined = bool(row["data_quarantined"])
                record.perimeter_active = record.status in (
                    IsolationStatus.ACTIVE,
                    IsolationStatus.PERIMETER_FORMED,
                )

                # Recreate containment zone stub
                if record.zone_id and record.zone_id not in self._containment_zones:
                    zone = ContainmentZone(
                        zone_id=record.zone_id,
                        created_by="restored",
                    )
                    zone.status = ContainmentZoneStatus.ACTIVE
                    zone.isolated_entities.add(entity_id)
                    self._containment_zones[record.zone_id] = zone
                elif record.zone_id:
                    self._containment_zones[record.zone_id].isolated_entities.add(
                        entity_id
                    )

                if record.zone_id:
                    self._entity_zone_map[entity_id] = record.zone_id

                restored += 1

            logger.info(
                ">>> [ISOLATION] Restored %d active isolation records", restored,
            )
            return restored

        except Exception as exc:
            logger.error(
                ">>> [ISOLATION] State restoration failed: %s", exc,
            )
            return 0

    # =========================================================================
    # BULK QUERIES
    # =========================================================================

    def get_all_isolated_entities(self) -> List[Dict[str, Any]]:
        """
        Return all currently isolated entities.

        Returns:
            List of serialized isolation records for entities that are
            currently in an active isolation state.
        """
        return [
            record.to_dict()
            for record in self._isolation_records.values()
            if record.status not in (
                IsolationStatus.NONE,
                IsolationStatus.RELEASED,
            )
        ]

    def is_isolated(self, entity_id: UUID) -> bool:
        """
        Quick check whether an entity is currently isolated.

        Args:
            entity_id: UUID of the entity to check.

        Returns:
            True if the entity is in an active isolation state.
        """
        record = self._isolation_records.get(entity_id)
        if not record:
            return False
        return record.status not in (
            IsolationStatus.NONE,
            IsolationStatus.RELEASED,
        )


# =============================================================================
# UTILITY
# =============================================================================

def _extract_count(result: str) -> int:
    """
    Extract row count from asyncpg command result string.

    asyncpg returns strings like 'UPDATE 5' or 'DELETE 3'.  This extracts
    the trailing integer.

    Args:
        result: asyncpg command result string.

    Returns:
        Integer count, or 0 if parsing fails.
    """
    try:
        parts = result.split()
        if len(parts) >= 2:
            return int(parts[-1])
    except (ValueError, AttributeError, IndexError):
        pass
    return 0
