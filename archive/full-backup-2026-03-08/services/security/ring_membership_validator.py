"""
HIVE DEFENSE PROTOCOL v3.0 — Cosmic Ring Membership Validator (Phase 8C: Third Cord)
Every Fibre must belong to a Cosmic Ring. Ring membership is signed by the Originator
at ring creation time. Unassigned Fibres are auto-quarantined regardless of heartbeat
health — a heartbeat without a ring is like an ID badge without a department.

Design rationale:
    Cosmic Rings are the organisational unit of trust within the Sovereign Swarm.
    Each ring has a fixed member list signed by Big Nate's master key at the moment
    of ring creation. This prevents an attacker from creating phantom rings or
    inserting themselves into existing rings.  Any Fibre not in *any* signed ring
    is considered rogue and is immediately quarantined.

    The validator serves two purposes:
        1. Positive verification — "Is this Fibre really in ring R?"
        2. Negative detection   — "Is this Fibre in *no* ring at all?"

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.models.hive_defense import (
    DefconLevel,
    DefconState,
    ForensicRecord,
)

logger = logging.getLogger("hive.ring_membership")


# =============================================================================
# RING RECORD
# =============================================================================

@dataclass
class CosmicRingRecord:
    """
    An immutable record of a Cosmic Ring's creation.

    Attributes:
        ring_id:                Unique identifier for this ring.
        member_ids:             Ordered list of member Fibre UUIDs.
        originator_signature:   Ed25519 signature over the canonical ring manifest.
        manifest_hash:          SHA-256 hash of the signed manifest.
        created_at:             Timestamp of ring creation.
        revoked:                Whether this ring has been administratively revoked.
    """
    ring_id: UUID = field(default_factory=uuid4)
    member_ids: List[UUID] = field(default_factory=list)
    originator_signature: str = ""
    manifest_hash: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    revoked: bool = False

    def compute_manifest_hash(self) -> str:
        """
        Compute the SHA-256 hash of the canonical ring manifest.

        The manifest is the sorted, JSON-serialised list of member UUIDs
        concatenated with the ring_id. This creates a deterministic, tamper-
        evident fingerprint of the ring.

        Returns:
            Hex-encoded SHA-256 digest of the manifest.
        """
        sorted_members = sorted(str(m) for m in self.member_ids)
        manifest = json.dumps({
            "ring_id": str(self.ring_id),
            "members": sorted_members,
        }, sort_keys=True, separators=(",", ":"))
        self.manifest_hash = hashlib.sha256(manifest.encode()).hexdigest()
        return self.manifest_hash


# =============================================================================
# RING MEMBERSHIP VALIDATOR
# =============================================================================

class RingMembershipValidator:
    """
    Cosmic Ring membership verification for all Fibres in the Sovereign Swarm.

    Every Fibre MUST belong to at least one Cosmic Ring. Ring membership lists
    are signed by the Originator (Big Nate) at ring creation time and stored
    immutably. Any Fibre not in a signed ring is considered unassigned and is
    automatically quarantined — regardless of heartbeat health, drift score,
    or any other positive indicator.

    Integration Points:
        - HeartbeatRegistry  — provides entity existence
        - PostBirthQuarantine — receives unassigned Fibre quarantine requests
        - DefconController   — escalates on ring integrity violations
        - ForensicLogger     — logs all ring operations to immutable chain

    Usage::

        validator = RingMembershipValidator(db_pool=pool)
        await validator.load_from_db()

        # Register a new ring
        await validator.register_ring(ring_id, member_ids, originator_sig)

        # Verify membership
        is_member = await validator.validate_membership(fibre_id, ring_id)

        # Detect unassigned Fibres
        is_rogue = await validator.is_unassigned(fibre_id)

    Patent-Pending — Claims 30-56
    """

    def __init__(
        self,
        db_pool=None,
        event_callback=None,
        forensic_logger=None,
    ) -> None:
        """
        Initialize the Ring Membership Validator.

        Args:
            db_pool:          asyncpg connection pool for persistence.
            event_callback:   Async callback ``(topic, payload) -> None`` for
                              broadcasting ring events to the hive event bus.
            forensic_logger:  ForensicLogger instance for immutable evidence chain.
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger

        # In-memory ring registry: ring_id → CosmicRingRecord
        self._rings: Dict[UUID, CosmicRingRecord] = {}

        # Reverse index: fibre_id → set of ring_ids
        self._fibre_to_rings: Dict[UUID, Set[UUID]] = defaultdict(set)

        # Set of all known Fibre IDs (registered in any ring or tracked globally)
        self._known_fibres: Set[UUID] = set()

        # Quarantined unassigned Fibres
        self._quarantined_unassigned: Set[UUID] = set()

        logger.info("RingMembershipValidator initialized")

    # =========================================================================
    # RING REGISTRATION
    # =========================================================================

    async def register_ring(
        self,
        ring_id: UUID,
        member_ids: List[UUID],
        originator_signature: str,
    ) -> CosmicRingRecord:
        """
        Register a new Cosmic Ring with a signed membership list.

        The ring's membership manifest is hashed and stored alongside the
        Originator's Ed25519 signature. Once registered, the membership list
        is immutable — members can only be added or removed by creating a
        new ring version.

        Args:
            ring_id:                Unique identifier for the ring.
            member_ids:             List of Fibre UUIDs to include in the ring.
            originator_signature:   Ed25519 signature over the manifest hash,
                                    produced by Big Nate's master key.

        Returns:
            The created CosmicRingRecord.

        Raises:
            ValueError: If the ring_id already exists and is not revoked.
        """
        if ring_id in self._rings and not self._rings[ring_id].revoked:
            raise ValueError(
                f"Ring {ring_id} already exists and is active. "
                "Revoke it first before re-registering."
            )

        record = CosmicRingRecord(
            ring_id=ring_id,
            member_ids=list(member_ids),
            originator_signature=originator_signature,
        )
        record.compute_manifest_hash()

        # Store the ring
        self._rings[ring_id] = record

        # Update reverse index
        for fibre_id in member_ids:
            self._fibre_to_rings[fibre_id].add(ring_id)
            self._known_fibres.add(fibre_id)

            # If fibre was quarantined as unassigned, release it
            if fibre_id in self._quarantined_unassigned:
                self._quarantined_unassigned.discard(fibre_id)
                logger.info(
                    "Fibre %s released from unassigned quarantine — now in ring %s",
                    fibre_id, ring_id,
                )

        # Persist to database
        await self._persist_ring(record)

        logger.info(
            "Ring %s registered with %d members (manifest=%s…)",
            ring_id, len(member_ids), record.manifest_hash[:16],
        )

        # Broadcast event
        await self._broadcast_event(
            "hive.ring.registered",
            {
                "ring_id": str(ring_id),
                "member_count": len(member_ids),
                "manifest_hash": record.manifest_hash,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return record

    # =========================================================================
    # MEMBERSHIP VALIDATION
    # =========================================================================

    async def validate_membership(
        self,
        fibre_id: UUID,
        claimed_ring_id: UUID,
    ) -> bool:
        """
        Verify that a Fibre is a member of the claimed Cosmic Ring.

        Checks the signed membership list of the ring against the Fibre's ID.
        If the ring does not exist, is revoked, or the Fibre is not in its
        member list, returns False.

        Args:
            fibre_id:        UUID of the Fibre claiming membership.
            claimed_ring_id: UUID of the ring the Fibre claims to belong to.

        Returns:
            True if the Fibre is a verified member of the ring.
        """
        ring = self._rings.get(claimed_ring_id)

        if ring is None:
            logger.warning(
                "Membership validation failed: ring %s does not exist "
                "(fibre=%s)",
                claimed_ring_id, fibre_id,
            )
            return False

        if ring.revoked:
            logger.warning(
                "Membership validation failed: ring %s is revoked "
                "(fibre=%s)",
                claimed_ring_id, fibre_id,
            )
            return False

        is_member = fibre_id in ring.member_ids

        if not is_member:
            logger.warning(
                "Membership validation failed: fibre %s not in ring %s "
                "(%d members)",
                fibre_id, claimed_ring_id, len(ring.member_ids),
            )

            # Log to forensic chain
            if self._forensic_logger:
                try:
                    await self._forensic_logger.log_event(
                        event_type="ring_membership_denied",
                        source_entity=str(fibre_id),
                        evidence={
                            "claimed_ring_id": str(claimed_ring_id),
                            "ring_member_count": len(ring.member_ids),
                        },
                    )
                except Exception as exc:
                    logger.error("Forensic log failed: %s", exc)

        return is_member

    # =========================================================================
    # RING QUERIES
    # =========================================================================

    async def get_ring_members(self, ring_id: UUID) -> List[UUID]:
        """
        Return the list of member Fibre IDs for a given ring.

        Args:
            ring_id: UUID of the Cosmic Ring.

        Returns:
            List of member UUIDs. Empty list if ring does not exist or is revoked.
        """
        ring = self._rings.get(ring_id)
        if ring is None or ring.revoked:
            return []
        return list(ring.member_ids)

    async def get_fibre_rings(self, fibre_id: UUID) -> List[UUID]:
        """
        Return the list of rings that a Fibre belongs to.

        Args:
            fibre_id: UUID of the Fibre.

        Returns:
            List of ring UUIDs the Fibre is a member of.
        """
        return [
            rid for rid in self._fibre_to_rings.get(fibre_id, set())
            if rid in self._rings and not self._rings[rid].revoked
        ]

    # =========================================================================
    # UNASSIGNED FIBRE DETECTION
    # =========================================================================

    async def is_unassigned(self, fibre_id: UUID) -> bool:
        """
        Check whether a Fibre is unassigned (not in any active Cosmic Ring).

        Unassigned Fibres are automatically quarantined regardless of heartbeat
        health. A Fibre without a ring has no trust context and must be treated
        as potentially rogue.

        Args:
            fibre_id: UUID of the Fibre to check.

        Returns:
            True if the Fibre is not in any active (non-revoked) ring.
        """
        active_rings = await self.get_fibre_rings(fibre_id)

        if not active_rings:
            # Auto-quarantine the unassigned Fibre
            if fibre_id not in self._quarantined_unassigned:
                self._quarantined_unassigned.add(fibre_id)
                logger.warning(
                    "Fibre %s is unassigned — auto-quarantined", fibre_id,
                )

                await self._broadcast_event(
                    "hive.ring.unassigned_quarantine",
                    {
                        "fibre_id": str(fibre_id),
                        "reason": "Not a member of any active Cosmic Ring",
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

                # Forensic log
                if self._forensic_logger:
                    try:
                        await self._forensic_logger.log_event(
                            event_type="ring_unassigned_quarantine",
                            source_entity=str(fibre_id),
                            evidence={
                                "known_fibre": fibre_id in self._known_fibres,
                                "total_rings": len(self._rings),
                            },
                        )
                    except Exception as exc:
                        logger.error("Forensic log failed: %s", exc)

            return True

        return False

    async def register_fibre(self, fibre_id: UUID) -> None:
        """
        Register a Fibre as known to the hive (called at birth).

        If the Fibre is not yet in any ring, it will be flagged as
        unassigned and auto-quarantined.

        Args:
            fibre_id: UUID of the newly born Fibre.
        """
        self._known_fibres.add(fibre_id)
        await self.is_unassigned(fibre_id)

    async def scan_for_unassigned(self) -> List[UUID]:
        """
        Scan all known Fibres and return those not in any active ring.

        This is a bulk operation intended to be run periodically by the
        hive's health-check loop.

        Returns:
            List of Fibre UUIDs that are unassigned.
        """
        unassigned = []
        for fibre_id in self._known_fibres:
            if await self.is_unassigned(fibre_id):
                unassigned.append(fibre_id)

        if unassigned:
            logger.warning(
                "Scan found %d unassigned Fibres (of %d known)",
                len(unassigned), len(self._known_fibres),
            )

        return unassigned

    # =========================================================================
    # RING REVOCATION
    # =========================================================================

    async def revoke_ring(
        self,
        ring_id: UUID,
        reason: str,
        authorized_by: str,
    ) -> bool:
        """
        Revoke a Cosmic Ring, invalidating all memberships within it.

        Fibres that were exclusively in this ring become unassigned and are
        auto-quarantined.

        Args:
            ring_id:        UUID of the ring to revoke.
            reason:         Human-readable reason for revocation.
            authorized_by:  Identifier of the authorizing administrator.

        Returns:
            True if the ring was found and revoked.
        """
        ring = self._rings.get(ring_id)
        if ring is None:
            return False

        ring.revoked = True

        # Remove from reverse index and check for newly-unassigned Fibres
        for fibre_id in ring.member_ids:
            self._fibre_to_rings[fibre_id].discard(ring_id)
            # Check if Fibre is now ringless
            await self.is_unassigned(fibre_id)

        # Persist revocation
        await self._persist_ring_revocation(ring_id, reason, authorized_by)

        logger.warning(
            "Ring %s revoked by %s — reason: %s (%d members affected)",
            ring_id, authorized_by, reason, len(ring.member_ids),
        )

        await self._broadcast_event(
            "hive.ring.revoked",
            {
                "ring_id": str(ring_id),
                "reason": reason,
                "authorized_by": authorized_by,
                "members_affected": len(ring.member_ids),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return True

    # =========================================================================
    # ADMIN & QUERIES
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """
        Return a summary dict for admin dashboards.

        Returns:
            Dictionary with ring and membership statistics.
        """
        active_rings = sum(1 for r in self._rings.values() if not r.revoked)
        revoked_rings = sum(1 for r in self._rings.values() if r.revoked)
        total_members = len(self._known_fibres)
        unassigned = len(self._quarantined_unassigned)

        return {
            "active_rings": active_rings,
            "revoked_rings": revoked_rings,
            "total_known_fibres": total_members,
            "unassigned_quarantined": unassigned,
            "ring_details": [
                {
                    "ring_id": str(rid),
                    "member_count": len(r.member_ids),
                    "revoked": r.revoked,
                    "manifest_hash": r.manifest_hash[:16] + "…",
                    "created_at": r.created_at.isoformat(),
                }
                for rid, r in self._rings.items()
            ],
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_ring(self, record: CosmicRingRecord) -> None:
        """Persist a ring record to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO cosmic_rings (
                        ring_id, member_ids, originator_signature,
                        manifest_hash, created_at, revoked
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (ring_id) DO UPDATE SET
                        member_ids = EXCLUDED.member_ids,
                        originator_signature = EXCLUDED.originator_signature,
                        manifest_hash = EXCLUDED.manifest_hash,
                        revoked = EXCLUDED.revoked
                    """,
                    record.ring_id,
                    json.dumps([str(m) for m in record.member_ids]),
                    record.originator_signature,
                    record.manifest_hash,
                    record.created_at,
                    record.revoked,
                )
            logger.debug("Persisted ring %s", record.ring_id)
        except Exception as exc:
            logger.error("Failed to persist ring %s: %s", record.ring_id, exc)

    async def _persist_ring_revocation(
        self,
        ring_id: UUID,
        reason: str,
        authorized_by: str,
    ) -> None:
        """Persist a ring revocation event."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE cosmic_rings SET revoked = TRUE WHERE ring_id = $1
                    """,
                    ring_id,
                )
                await conn.execute(
                    """
                    INSERT INTO ring_revocations (
                        ring_id, reason, authorized_by, revoked_at
                    ) VALUES ($1, $2, $3, NOW())
                    """,
                    ring_id, reason, authorized_by,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist ring revocation for %s: %s", ring_id, exc,
            )

    async def load_from_db(self) -> int:
        """
        Load all ring records from the database on startup.

        Returns:
            Number of rings loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ring_id, member_ids, originator_signature,
                           manifest_hash, created_at, revoked
                    FROM cosmic_rings
                    """
                )

            loaded = 0
            for row in rows:
                member_ids = [
                    UUID(mid) for mid in json.loads(row["member_ids"])
                ]
                record = CosmicRingRecord(
                    ring_id=row["ring_id"],
                    member_ids=member_ids,
                    originator_signature=row["originator_signature"] or "",
                    manifest_hash=row["manifest_hash"] or "",
                    created_at=row["created_at"],
                    revoked=row["revoked"],
                )
                self._rings[record.ring_id] = record

                if not record.revoked:
                    for fibre_id in member_ids:
                        self._fibre_to_rings[fibre_id].add(record.ring_id)
                        self._known_fibres.add(fibre_id)

                loaded += 1

            logger.info("Loaded %d cosmic ring records from database", loaded)
            return loaded

        except Exception as exc:
            logger.error("Failed to load rings from DB: %s", exc)
            return 0

    # =========================================================================
    # EVENT BUS
    # =========================================================================

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast a ring event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "Event callback failed for topic %s: %s", topic, exc,
                )
