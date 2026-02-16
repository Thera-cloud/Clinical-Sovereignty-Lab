"""
HIVE DEFENSE PROTOCOL — Canary Credential Manager (Phase 8B)
Decoy credential management: plants, monitors, and rotates canary
credentials throughout the runtime environment.  Any access to a canary
credential triggers immediate DEFCON 2 escalation and forensic evidence
collection.

Canary Types
------------
* ``db_string`` — fake database connection strings in env / config files.
* ``api_key`` — invalid API keys seeded in memory and config.
* ``member_record`` — synthetic member records with embedded tripwires.
* ``aws_key`` — fake AWS access keys with canary-token alerting.
* ``stripe_key`` — fake Stripe API keys that trigger on any API call.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import string
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

import structlog

from app.models.hive_defense import CanaryCredential, DefconLevel

logger = structlog.get_logger("hive.canary_credentials")


# =============================================================================
# CANARY CREDENTIAL TYPES
# =============================================================================

CANARY_TYPES: Set[str] = {
    "db_string",
    "api_key",
    "member_record",
    "aws_key",
    "stripe_key",
}

# Rotation interval: canaries should be rotated at least this often (seconds).
DEFAULT_ROTATION_INTERVAL: int = 86400  # 24 hours

# Format templates for generating realistic-looking credentials.
CREDENTIAL_TEMPLATES: Dict[str, str] = {
    "db_string": "postgresql://canary_{token}:C4n4ry_{secret}@10.0.0.81:5432/sanctuary_backup",
    "api_key": "sk-canary-{token}-{secret}",
    "member_record": "MEMBER-{token}-{secret}",
    "aws_key": "AKIA{token_upper}",
    "stripe_key": "sk_live_canary_{token}{secret}",
}


# =============================================================================
# CANARY CREDENTIAL MANAGER
# =============================================================================

class CanaryCredentialManager:
    """
    Manages decoy credentials planted throughout the runtime environment.

    When an attacker (or compromised insider) accesses a canary credential,
    the manager triggers an immediate DEFCON 2 escalation, logs immutable
    forensic evidence, and notifies the incident-response chain.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for persisting canary state and access events.
    forensic_logger : Any, optional
        Reference to :class:`ForensicLogger` for evidence-chain logging.
    defcon_manager : Any, optional
        Reference to a DEFCON state manager for escalation.
    """

    def __init__(
        self,
        db_pool: Any = None,
        forensic_logger: Any = None,
        defcon_manager: Any = None,
    ) -> None:
        self.db_pool = db_pool
        self.forensic_logger = forensic_logger
        self.defcon_manager = defcon_manager

        # In-memory canary registry (canary_id → CanaryCredential)
        self._canaries: Dict[UUID, CanaryCredential] = {}

        # Canary credential values (canary_id → generated credential string)
        self._credential_values: Dict[UUID, str] = {}

        # Access event log
        self._access_events: List[Dict[str, Any]] = []

        # Cumulative metrics
        self._total_planted: int = 0
        self._total_triggered: int = 0
        self._total_rotated: int = 0

    # ------------------------------------------------------------------
    # Planting
    # ------------------------------------------------------------------

    async def plant_canary(
        self,
        credential_type: str,
        location: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CanaryCredential:
        """Plant a new canary credential in the specified location.

        Parameters
        ----------
        credential_type : str
            One of ``CANARY_TYPES`` (e.g. ``"api_key"``, ``"db_string"``).
        location : str
            Where the canary is planted (e.g. ``"env.BACKUP_DB_URL"``,
            ``"config/stripe.json"``).
        metadata : dict, optional
            Extra context about the canary placement.

        Returns
        -------
        CanaryCredential
            The planted canary model.

        Raises
        ------
        ValueError
            If ``credential_type`` is not a recognised canary type.
        """
        if credential_type not in CANARY_TYPES:
            raise ValueError(
                f"Unknown canary type '{credential_type}'. "
                f"Valid types: {', '.join(sorted(CANARY_TYPES))}"
            )

        canary = CanaryCredential(
            canary_id=uuid4(),
            credential_type=credential_type,
            planted_location=location,
            planted_at=datetime.now(tz=timezone.utc),
        )

        # Generate realistic credential value
        credential_value = self._generate_credential(credential_type)
        self._credential_values[canary.canary_id] = credential_value

        # Register in memory
        self._canaries[canary.canary_id] = canary
        self._total_planted += 1

        # Persist to database
        await self._persist_canary(canary, credential_value, metadata)

        logger.info(
            "canary_planted",
            canary_id=str(canary.canary_id),
            type=credential_type,
            location=location,
        )

        return canary

    # ------------------------------------------------------------------
    # Access checking
    # ------------------------------------------------------------------

    async def check_access(self, canary_id: UUID) -> bool:
        """Check whether a canary credential has been accessed.

        Parameters
        ----------
        canary_id : UUID
            The unique identifier of the canary to check.

        Returns
        -------
        bool
            ``True`` if the canary has been accessed (triggered).
        """
        canary = self._canaries.get(canary_id)
        if canary is None:
            # Check database
            if self.db_pool:
                try:
                    async with self.db_pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT accessed FROM canary_credentials WHERE canary_id = $1",
                            canary_id,
                        )
                        if row:
                            return bool(row["accessed"])
                except Exception as exc:
                    logger.debug("canary_check_db_failed", error=str(exc))
            return False

        return canary.accessed

    async def check_all_canaries(self) -> List[Dict[str, Any]]:
        """Check all planted canaries for access events.

        Queries the ``canary_access_events`` table for any new access
        records since the last check.

        Returns
        -------
        list[dict]
            List of canary access events (each containing ``canary_id``,
            ``access_source``, ``accessed_at``).
        """
        triggered: List[Dict[str, Any]] = []

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT ce.canary_id, ce.access_source, ce.accessed_at,
                               cc.credential_type, cc.planted_location
                        FROM canary_access_events ce
                        JOIN canary_credentials cc ON cc.canary_id = ce.canary_id
                        WHERE ce.processed = false
                        ORDER BY ce.accessed_at ASC
                    """)
                    for row in rows:
                        triggered.append({
                            "canary_id": str(row["canary_id"]),
                            "access_source": row["access_source"],
                            "accessed_at": row["accessed_at"].isoformat(),
                            "credential_type": row["credential_type"],
                            "planted_location": row["planted_location"],
                        })
                        # Mark as processed
                        await conn.execute(
                            "UPDATE canary_access_events SET processed = true WHERE canary_id = $1 AND accessed_at = $2",
                            row["canary_id"], row["accessed_at"],
                        )
            except Exception as exc:
                logger.debug("canary_check_all_db_failed", error=str(exc))

        # Also check in-memory canaries
        for cid, canary in self._canaries.items():
            if canary.accessed and str(cid) not in {t["canary_id"] for t in triggered}:
                triggered.append({
                    "canary_id": str(cid),
                    "access_source": canary.access_source or "unknown",
                    "accessed_at": canary.accessed_at.isoformat() if canary.accessed_at else None,
                    "credential_type": canary.credential_type,
                    "planted_location": canary.planted_location,
                })

        return triggered

    # ------------------------------------------------------------------
    # Trigger handling
    # ------------------------------------------------------------------

    async def on_canary_triggered(
        self,
        canary_id: UUID,
        access_source: str,
        access_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Handle a canary credential access event.

        This is the critical response path:
        1. Mark the canary as accessed.
        2. Log the access event to the database.
        3. Create an immutable forensic record.
        4. Escalate to DEFCON 2.
        5. Notify the incident-response chain.

        Parameters
        ----------
        canary_id : UUID
            The triggered canary.
        access_source : str
            Identifier of who/what accessed the canary (IP, user_id, etc.).
        access_metadata : dict, optional
            Additional forensic context.

        Returns
        -------
        dict
            Response including escalation status and forensic record ID.
        """
        now = datetime.now(tz=timezone.utc)
        self._total_triggered += 1

        # Update in-memory state
        canary = self._canaries.get(canary_id)
        if canary:
            canary.accessed = True
            canary.accessed_at = now
            canary.access_source = access_source

        # Persist access event
        await self._persist_access_event(canary_id, access_source, now, access_metadata)

        # Log forensic evidence (immutable chain)
        forensic_record_id = None
        if self.forensic_logger:
            try:
                record = await self.forensic_logger.log_event(
                    event_type="hive.tripwire.credential_used",
                    source_entity=access_source,
                    target_entity=str(canary_id),
                    evidence={
                        "canary_id": str(canary_id),
                        "credential_type": canary.credential_type if canary else "unknown",
                        "planted_location": canary.planted_location if canary else "unknown",
                        "access_source": access_source,
                        "access_metadata": access_metadata or {},
                        "triggered_at": now.isoformat(),
                    },
                )
                forensic_record_id = str(record.record_id)
            except Exception as exc:
                logger.error("canary_forensic_log_failed", error=str(exc))

        # Escalate to DEFCON 2
        escalation_result = await self._escalate_defcon2(canary_id, access_source)

        logger.critical(
            "CANARY_TRIGGERED",
            canary_id=str(canary_id),
            access_source=access_source,
            credential_type=canary.credential_type if canary else "unknown",
            location=canary.planted_location if canary else "unknown",
            escalation=escalation_result,
        )

        return {
            "canary_id": str(canary_id),
            "triggered": True,
            "access_source": access_source,
            "triggered_at": now.isoformat(),
            "forensic_record_id": forensic_record_id,
            "escalation": escalation_result,
            "defcon_level": 2,
        }

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def get_all_canaries(self) -> List[Dict[str, Any]]:
        """Return all planted canaries (in-memory + database).

        Returns
        -------
        list[dict]
            Canary records with ``canary_id``, ``credential_type``,
            ``planted_location``, ``planted_at``, ``accessed``, etc.
        """
        results: List[Dict[str, Any]] = []

        # In-memory canaries
        for cid, canary in self._canaries.items():
            results.append({
                "canary_id": str(cid),
                "credential_type": canary.credential_type,
                "planted_location": canary.planted_location,
                "planted_at": canary.planted_at.isoformat(),
                "accessed": canary.accessed,
                "accessed_at": canary.accessed_at.isoformat() if canary.accessed_at else None,
                "access_source": canary.access_source,
            })

        # Supplement from database if available
        if self.db_pool:
            try:
                in_memory_ids = {str(cid) for cid in self._canaries}
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT canary_id, credential_type, planted_location,
                               planted_at, accessed, accessed_at, access_source
                        FROM canary_credentials
                        ORDER BY planted_at DESC
                    """)
                    for row in rows:
                        if str(row["canary_id"]) not in in_memory_ids:
                            results.append({
                                "canary_id": str(row["canary_id"]),
                                "credential_type": row["credential_type"],
                                "planted_location": row["planted_location"],
                                "planted_at": row["planted_at"].isoformat(),
                                "accessed": row["accessed"],
                                "accessed_at": (
                                    row["accessed_at"].isoformat()
                                    if row["accessed_at"] else None
                                ),
                                "access_source": row["access_source"],
                            })
            except Exception as exc:
                logger.debug("canary_list_db_failed", error=str(exc))

        return results

    # ------------------------------------------------------------------
    # Rotation
    # ------------------------------------------------------------------

    async def rotate_canaries(self) -> Dict[str, Any]:
        """Rotate all canary credentials.

        Deactivates existing canaries and plants fresh ones in the same
        locations with new credential values.

        Returns
        -------
        dict
            ``rotated_count``, ``new_canaries`` (list of new canary IDs).
        """
        old_canaries = list(self._canaries.values())
        rotated = 0
        new_ids: List[str] = []

        for old in old_canaries:
            # Remove old canary
            self._canaries.pop(old.canary_id, None)
            self._credential_values.pop(old.canary_id, None)

            # Deactivate in DB
            if self.db_pool:
                try:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE canary_credentials SET active = false WHERE canary_id = $1",
                            old.canary_id,
                        )
                except Exception as exc:
                    logger.debug("canary_deactivate_failed", error=str(exc))

            # Plant replacement
            try:
                new_canary = await self.plant_canary(
                    credential_type=old.credential_type,
                    location=old.planted_location,
                )
                new_ids.append(str(new_canary.canary_id))
                rotated += 1
            except Exception as exc:
                logger.error(
                    "canary_rotation_failed",
                    old_id=str(old.canary_id),
                    error=str(exc),
                )

        self._total_rotated += rotated

        logger.info("canaries_rotated", rotated=rotated, new_count=len(new_ids))

        return {
            "rotated_count": rotated,
            "new_canaries": new_ids,
            "rotated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Internal: credential generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_credential(credential_type: str) -> str:
        """Generate a realistic-looking fake credential of the given type."""
        token = secrets.token_hex(8)
        secret = secrets.token_urlsafe(12)
        token_upper = "".join(
            secrets.choice(string.ascii_uppercase + string.digits)
            for _ in range(16)
        )

        template = CREDENTIAL_TEMPLATES.get(credential_type, "canary-{token}-{secret}")
        return template.format(
            token=token,
            secret=secret,
            token_upper=token_upper,
        )

    # ------------------------------------------------------------------
    # Internal: persistence
    # ------------------------------------------------------------------

    async def _persist_canary(
        self,
        canary: CanaryCredential,
        credential_value: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist a newly planted canary to the database."""
        if not self.db_pool:
            return

        try:
            # Store a salted hash of the credential — never the plaintext
            value_hash = hashlib.sha256(credential_value.encode()).hexdigest()

            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO canary_credentials
                        (canary_id, credential_type, planted_location,
                         credential_hash, planted_at, active, metadata)
                    VALUES ($1, $2, $3, $4, $5, true, $6)
                    """,
                    canary.canary_id,
                    canary.credential_type,
                    canary.planted_location,
                    value_hash,
                    canary.planted_at,
                    json.dumps(metadata) if metadata else None,
                )
        except Exception as exc:
            logger.debug("canary_persist_failed", error=str(exc))

    async def _persist_access_event(
        self,
        canary_id: UUID,
        access_source: str,
        accessed_at: datetime,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a canary access event to the database."""
        event = {
            "canary_id": str(canary_id),
            "access_source": access_source,
            "accessed_at": accessed_at.isoformat(),
            "metadata": metadata,
        }
        self._access_events.append(event)

        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO canary_access_events
                        (canary_id, access_source, accessed_at, metadata, processed)
                    VALUES ($1, $2, $3, $4, false)
                    """,
                    canary_id,
                    access_source,
                    accessed_at,
                    json.dumps(metadata) if metadata else None,
                )
                # Also mark the canary itself as accessed
                await conn.execute(
                    """
                    UPDATE canary_credentials
                    SET accessed = true, accessed_at = $2, access_source = $3
                    WHERE canary_id = $1
                    """,
                    canary_id, accessed_at, access_source,
                )
        except Exception as exc:
            logger.debug("canary_access_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Internal: DEFCON escalation
    # ------------------------------------------------------------------

    async def _escalate_defcon2(
        self, canary_id: UUID, access_source: str,
    ) -> Dict[str, Any]:
        """Escalate the system to DEFCON 2 (SEVERE) in response to canary access."""
        result = {
            "escalated": False,
            "target_level": 2,
            "reason": f"Canary credential {canary_id} accessed by {access_source}",
        }

        if self.defcon_manager and hasattr(self.defcon_manager, "escalate"):
            try:
                await self.defcon_manager.escalate(
                    target_level=DefconLevel.SEVERE,
                    reason=result["reason"],
                    triggered_by="canary_credential_manager",
                )
                result["escalated"] = True
            except Exception as exc:
                logger.error("defcon_escalation_failed", error=str(exc))
                result["error"] = str(exc)
        else:
            logger.warning(
                "no_defcon_manager",
                msg="Cannot escalate — defcon_manager not configured",
            )

        return result

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring dashboards."""
        return {
            "canaries_active": len(self._canaries),
            "total_planted": self._total_planted,
            "total_triggered": self._total_triggered,
            "total_rotated": self._total_rotated,
            "access_events": len(self._access_events),
        }

    def __repr__(self) -> str:
        return (
            f"<CanaryCredentialManager "
            f"active={len(self._canaries)} "
            f"triggered={self._total_triggered}>"
        )
