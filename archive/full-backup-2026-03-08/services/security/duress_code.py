"""
HIVE DEFENSE PROTOCOL v3.0 — Duress Code Manager (Phase 8C)
Silent coercion detection for key shard holders.

Patent-Pending — Claim 46
    "A method for detecting coerced key reconstruction, comprising:
     (a) assignment of a personal duress code to each shard holder,
     (b) silent detection during key reconstruction when the duress code
         is used in place of or alongside the normal authentication,
     (c) continuation of the reconstruction ceremony with apparent success
         while simultaneously triggering: immediate key rotation, DEFCON 1
         escalation, alerting all other shard holders, and forensic capture
         of the entire reconstruction session."

Each shard holder registers a personal duress code — a phrase, PIN, or
biometric variant that, when used during key reconstruction, signals that
the holder is acting under coercion.

CRITICAL BEHAVIOR:
    When a duress code is detected, the system APPEARS to work normally
    from the perspective of the coercer.  Behind the scenes, four actions
    fire simultaneously:

    1. IMMEDIATE KEY ROTATION — the compromised key material is rotated
       before the coerced reconstruction can be used.
    2. DEFCON 1 ESCALATION — the entire hive enters maximum lockdown.
    3. ALERT TO ALL OTHER SHARD HOLDERS — every other holder is notified
       via secondary channels (SMS + encrypted email).
    4. FORENSIC CAPTURE — complete session recording of the reconstruction
       ceremony, including all network metadata, timing, and inputs.

Event: ``hive.duress.code_received``

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.duress_code")


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class DuressCodeRegistration:
    """Registration record for a shard holder's duress code."""

    holder_id: str
    code_hash: str              # bcrypt or argon2id hash — NEVER plaintext
    salt: str                   # unique per-holder salt
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_verified_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class DuressEvent:
    """Forensic record of a duress code activation."""

    event_id: UUID = field(default_factory=uuid4)
    holder_id: str = ""
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_capture: Dict[str, Any] = field(default_factory=dict)
    key_rotation_initiated: bool = False
    defcon_escalated: bool = False
    holders_alerted: List[str] = field(default_factory=list)
    forensic_hash: str = ""


# =============================================================================
# DURESS CODE MANAGER
# =============================================================================

class DuressCodeManager:
    """
    Silent coercion detection system for shard holders.

    Each shard holder registers a personal duress code (hashed, never stored
    in plaintext).  During key reconstruction ceremonies, all holder inputs
    are verified against both their normal credentials AND their duress code.
    If the duress code matches, the system silently executes the full duress
    response protocol while presenting normal behavior to any observer.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for persisting registrations and events.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None`` for
        broadcasting duress events to the hive event bus.
    defcon_controller : Any, optional
        Reference to the DefconController for DEFCON 1 escalation.
    key_rotation_service : Any, optional
        Reference to the key rotation service for immediate key rotation.
    notification_service : Any, optional
        Reference to the notification service for alerting shard holders.
    forensic_logger : Any, optional
        Reference to the ForensicLogger for evidence-chain recording.

    Usage
    -----
    ::

        manager = DuressCodeManager(
            db_pool=pool,
            defcon_controller=defcon,
            key_rotation_service=key_service,
        )

        # Registration
        await manager.register_duress_code("holder_alpha", code_hash)

        # During reconstruction ceremony
        is_duress, is_valid = await manager.verify_code("holder_alpha", submitted_code)
        if is_duress:
            # Response already triggered silently
            pass
    """

    def __init__(
        self,
        db_pool: Any = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        defcon_controller: Any = None,
        key_rotation_service: Any = None,
        notification_service: Any = None,
        forensic_logger: Any = None,
    ) -> None:
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._defcon_controller = defcon_controller
        self._key_rotation_service = key_rotation_service
        self._notification_service = notification_service
        self._forensic_logger = forensic_logger

        # In-memory registry (holder_id -> DuressCodeRegistration)
        self._registrations: Dict[str, DuressCodeRegistration] = {}

        # Event history
        self._events: List[DuressEvent] = []

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        logger.info("DuressCodeManager initialized")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_duress_code(
        self,
        holder_id: str,
        code_hash: str,
    ) -> bool:
        """
        Register or update a shard holder's duress code.

        The code MUST be pre-hashed by the caller using argon2id or bcrypt.
        This method NEVER accepts or stores plaintext duress codes.

        Parameters
        ----------
        holder_id : str
            Unique identifier for the shard holder.
        code_hash : str
            Pre-computed hash of the holder's chosen duress code.
            Acceptable formats: argon2id hash string, bcrypt hash string,
            or a hex-encoded PBKDF2-HMAC-SHA256 output.

        Returns
        -------
        bool
            True if registration succeeded.
        """
        if not code_hash or len(code_hash) < 32:
            logger.error(
                "duress_registration_rejected holder=%s reason=hash_too_short",
                holder_id,
            )
            return False

        # Generate a unique salt for this holder
        salt = os.urandom(32).hex()

        # Double-hash with salt for storage (defense in depth)
        storage_hash = self._derive_storage_hash(code_hash, salt)

        registration = DuressCodeRegistration(
            holder_id=holder_id,
            code_hash=storage_hash,
            salt=salt,
        )

        async with self._lock:
            self._registrations[holder_id] = registration

        # Persist to database
        await self._persist_registration(registration)

        logger.info(
            "duress_code_registered holder=%s (hash stored, never plaintext)",
            holder_id,
        )
        return True

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    async def verify_code(
        self,
        holder_id: str,
        code: str,
    ) -> Tuple[bool, bool]:
        """
        Verify an input against a shard holder's registered duress code.

        This method uses constant-time comparison to prevent timing attacks.
        If the code IS a duress code, the full duress response is triggered
        SILENTLY — the return indicates duress but the caller should present
        normal behavior to the observer.

        Parameters
        ----------
        holder_id : str
            Shard holder identifier.
        code : str
            The code submitted during the reconstruction ceremony.
            This will be hashed and compared against the stored hash.

        Returns
        -------
        tuple[bool, bool]
            ``(is_duress, is_valid)`` where:
            - ``is_duress``: True if the submitted code matches the duress code.
            - ``is_valid``: True if the holder exists and the code matched.
        """
        registration = self._registrations.get(holder_id)
        if not registration or not registration.is_active:
            logger.warning(
                "duress_verify_failed holder=%s reason=not_registered",
                holder_id,
            )
            return (False, False)

        # Hash the submitted code with the holder's salt
        submitted_hash = self._derive_storage_hash(
            self._hash_input(code),
            registration.salt,
        )

        # Constant-time comparison
        is_match = hmac.compare_digest(
            submitted_hash.encode(),
            registration.code_hash.encode(),
        )

        if is_match:
            # DURESS CODE DETECTED — trigger response silently
            logger.critical(
                "DURESS_CODE_RECEIVED holder=%s — triggering silent response",
                holder_id,
            )
            # Fire response in background — do NOT await blocking operations
            # that would reveal timing differences to the coercer
            asyncio.create_task(self.trigger_duress_response(holder_id))

            return (True, True)

        # Not a duress code — this is a normal (potentially wrong) input
        return (False, False)

    # ------------------------------------------------------------------
    # Duress Response
    # ------------------------------------------------------------------

    async def trigger_duress_response(self, holder_id: str) -> DuressEvent:
        """
        Execute the full duress response protocol.

        Fires all four actions concurrently:
        1. Immediate key rotation
        2. DEFCON 1 escalation
        3. Alert all other shard holders
        4. Forensic capture of reconstruction session

        This method is designed to complete as quickly as possible while
        the coerced ceremony continues to appear normal.

        Parameters
        ----------
        holder_id : str
            The shard holder who triggered the duress code.

        Returns
        -------
        DuressEvent
            Complete record of the duress response actions.
        """
        event = DuressEvent(holder_id=holder_id)

        logger.critical(
            "DURESS_RESPONSE_INITIATED holder=%s event_id=%s",
            holder_id,
            event.event_id,
        )

        # Execute all four actions concurrently
        results = await asyncio.gather(
            self._action_rotate_keys(holder_id, event),
            self._action_escalate_defcon(holder_id, event),
            self._action_alert_holders(holder_id, event),
            self._action_forensic_capture(holder_id, event),
            return_exceptions=True,
        )

        # Log any failures (but NEVER abort — all actions are critical)
        for i, result in enumerate(results):
            action_names = [
                "key_rotation",
                "defcon_escalation",
                "holder_alerting",
                "forensic_capture",
            ]
            if isinstance(result, Exception):
                logger.error(
                    "duress_action_failed action=%s holder=%s error=%s",
                    action_names[i],
                    holder_id,
                    str(result),
                )

        # Compute forensic hash of the entire event
        event.forensic_hash = self._compute_event_hash(event)

        # Store event
        self._events.append(event)
        await self._persist_event(event)

        # Broadcast to hive event bus
        await self._broadcast_event(
            "hive.duress.code_received",
            {
                "event_id": str(event.event_id),
                "holder_id": holder_id,
                "triggered_at": event.triggered_at.isoformat(),
                "key_rotation_initiated": event.key_rotation_initiated,
                "defcon_escalated": event.defcon_escalated,
                "holders_alerted": event.holders_alerted,
                "forensic_hash": event.forensic_hash,
            },
        )

        logger.critical(
            "DURESS_RESPONSE_COMPLETE holder=%s event_id=%s "
            "key_rotated=%s defcon=%s holders_alerted=%d",
            holder_id,
            event.event_id,
            event.key_rotation_initiated,
            event.defcon_escalated,
            len(event.holders_alerted),
        )

        # Admin Contact Shield: EMERGENCY SMS on duress code activation
        try:
            from app.services.security.admin_contact_shield import get_shield
            await get_shield().alert_admin(
                "EMERGENCY: DURESS CODE ACTIVATED",
                f"Shard holder {holder_id} triggered duress response. "
                f"Keys rotated: {event.key_rotation_initiated}. "
                f"DEFCON 1 escalated: {event.defcon_escalated}. "
                f"DO NOT participate in any ceremony until all-clear."
            )
        except Exception:
            pass

        return event

    # ------------------------------------------------------------------
    # Action 1: Key Rotation
    # ------------------------------------------------------------------

    async def _action_rotate_keys(
        self,
        holder_id: str,
        event: DuressEvent,
    ) -> None:
        """Immediately rotate all key material to invalidate compromised shards."""
        if self._key_rotation_service:
            try:
                if hasattr(self._key_rotation_service, "emergency_rotate"):
                    await self._key_rotation_service.emergency_rotate(
                        reason=f"duress_code_from_{holder_id}",
                        triggered_by="duress_code_manager",
                    )
                event.key_rotation_initiated = True
                logger.info("duress_key_rotation_complete holder=%s", holder_id)
            except Exception as exc:
                logger.error(
                    "duress_key_rotation_failed holder=%s error=%s",
                    holder_id,
                    exc,
                )
        else:
            # If no rotation service, log that manual rotation is required
            logger.critical(
                "MANUAL_KEY_ROTATION_REQUIRED — no key_rotation_service configured"
            )
            event.key_rotation_initiated = False

    # ------------------------------------------------------------------
    # Action 2: DEFCON 1 Escalation
    # ------------------------------------------------------------------

    async def _action_escalate_defcon(
        self,
        holder_id: str,
        event: DuressEvent,
    ) -> None:
        """Escalate to DEFCON 1 (CRITICAL) — full hive lockdown."""
        if self._defcon_controller:
            try:
                if hasattr(self._defcon_controller, "escalate"):
                    from app.models.hive_defense import DefconLevel
                    await self._defcon_controller.escalate(
                        DefconLevel.CRITICAL,
                        f"Duress code received from shard holder {holder_id}",
                    )
                event.defcon_escalated = True
                logger.info("duress_defcon_escalated holder=%s level=CRITICAL", holder_id)
            except Exception as exc:
                logger.error(
                    "duress_defcon_escalation_failed holder=%s error=%s",
                    holder_id,
                    exc,
                )
        else:
            logger.critical("DEFCON_ESCALATION_REQUIRED — no defcon_controller configured")
            event.defcon_escalated = False

    # ------------------------------------------------------------------
    # Action 3: Alert All Other Shard Holders
    # ------------------------------------------------------------------

    async def _action_alert_holders(
        self,
        holder_id: str,
        event: DuressEvent,
    ) -> None:
        """Alert all shard holders EXCEPT the one under duress."""
        other_holders = [
            hid for hid in self._registrations.keys()
            if hid != holder_id and self._registrations[hid].is_active
        ]

        if not other_holders:
            logger.warning("duress_no_other_holders_to_alert holder=%s", holder_id)
            return

        if self._notification_service:
            try:
                for other_id in other_holders:
                    if hasattr(self._notification_service, "send_emergency_alert"):
                        await self._notification_service.send_emergency_alert(
                            recipient_id=other_id,
                            alert_type="duress_code_activated",
                            message=(
                                f"EMERGENCY: Shard holder {holder_id} has activated "
                                f"their duress code. Key reconstruction ceremony may "
                                f"be compromised. DO NOT participate in any ceremony "
                                f"until all-clear is confirmed by Nathan."
                            ),
                            channels=["sms", "encrypted_email"],
                        )
                    event.holders_alerted.append(other_id)

                logger.info(
                    "duress_holders_alerted holder=%s alerted=%s",
                    holder_id,
                    event.holders_alerted,
                )
            except Exception as exc:
                logger.error(
                    "duress_holder_alerting_failed holder=%s error=%s",
                    holder_id,
                    exc,
                )
        else:
            logger.critical(
                "HOLDER_ALERTING_REQUIRED — no notification_service configured"
            )

    # ------------------------------------------------------------------
    # Action 4: Forensic Capture
    # ------------------------------------------------------------------

    async def _action_forensic_capture(
        self,
        holder_id: str,
        event: DuressEvent,
    ) -> None:
        """Capture full forensic record of the reconstruction session."""
        session_data = {
            "holder_id": holder_id,
            "event_id": str(event.event_id),
            "triggered_at": event.triggered_at.isoformat(),
            "capture_timestamp": datetime.now(timezone.utc).isoformat(),
            "system_time_ns": time.monotonic_ns(),
        }

        if self._forensic_logger:
            try:
                if hasattr(self._forensic_logger, "record_event"):
                    await self._forensic_logger.record_event(
                        event_type="duress_code_activation",
                        source_entity=holder_id,
                        evidence=session_data,
                    )
                event.session_capture = session_data
                logger.info("duress_forensic_capture_complete holder=%s", holder_id)
            except Exception as exc:
                logger.error(
                    "duress_forensic_capture_failed holder=%s error=%s",
                    holder_id,
                    exc,
                )
        else:
            # Store in event even without forensic logger
            event.session_capture = session_data
            logger.info(
                "duress_forensic_capture_stored_locally holder=%s",
                holder_id,
            )

    # ------------------------------------------------------------------
    # Cryptographic Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_input(plaintext: str) -> str:
        """
        Hash a plaintext duress code input for comparison.

        Uses SHA-256 as an intermediate step; the storage hash adds
        per-holder salt via HMAC.
        """
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

    @staticmethod
    def _derive_storage_hash(code_hash: str, salt: str) -> str:
        """
        Derive the storage hash from a code hash and per-holder salt.

        Uses HMAC-SHA256 with the salt as key and the code hash as message.
        """
        return hmac.new(
            key=salt.encode("utf-8"),
            msg=code_hash.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _compute_event_hash(event: DuressEvent) -> str:
        """Compute a forensic hash of the entire duress event."""
        material = (
            f"{event.event_id}:{event.holder_id}:"
            f"{event.triggered_at.isoformat()}:"
            f"{event.key_rotation_initiated}:"
            f"{event.defcon_escalated}:"
            f"{','.join(sorted(event.holders_alerted))}"
        )
        return hashlib.sha256(material.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_registration(self, reg: DuressCodeRegistration) -> None:
        """Persist a duress code registration to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_duress_codes (
                        holder_id, code_hash, salt, registered_at, is_active
                    ) VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (holder_id) DO UPDATE SET
                        code_hash = EXCLUDED.code_hash,
                        salt = EXCLUDED.salt,
                        registered_at = EXCLUDED.registered_at,
                        is_active = EXCLUDED.is_active
                    """,
                    reg.holder_id,
                    reg.code_hash,
                    reg.salt,
                    reg.registered_at,
                    reg.is_active,
                )
        except Exception as exc:
            logger.error("duress_registration_persist_failed error=%s", exc)

    async def _persist_event(self, event: DuressEvent) -> None:
        """Persist a duress event to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_duress_events (
                        event_id, holder_id, triggered_at,
                        key_rotation_initiated, defcon_escalated,
                        holders_alerted, forensic_hash
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    event.event_id,
                    event.holder_id,
                    event.triggered_at,
                    event.key_rotation_initiated,
                    event.defcon_escalated,
                    event.holders_alerted,
                    event.forensic_hash,
                )
        except Exception as exc:
            logger.error("duress_event_persist_failed error=%s", exc)

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast an event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "duress_event_broadcast_failed topic=%s error=%s",
                    topic,
                    exc,
                )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def registered_holders(self) -> List[str]:
        """List of holder IDs with active duress code registrations."""
        return [
            hid for hid, reg in self._registrations.items()
            if reg.is_active
        ]

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "registered_holders": len(self._registrations),
            "active_holders": len(self.registered_holders),
            "total_events": len(self._events),
        }

    def __repr__(self) -> str:
        return (
            f"<DuressCodeManager holders={len(self._registrations)} "
            f"events={len(self._events)}>"
        )
