"""
HIVE DEFENSE PROTOCOL v3.0 — Remote Wipe Service (Phase 8C)
Device loss response with Azure AD conditional access integration.

When a shard holder's device is lost or stolen, this service provides
immediate response capabilities:

1. Full disk encryption enforcement verification — ensures all enrolled
   devices have encryption enabled BEFORE they are authorized.
2. Remote wipe via Azure AD conditional access — immediately revokes
   access tokens and initiates device wipe.
3. Automatic shard rotation — any holder whose device is lost has their
   shard regenerated and redistributed.

HSM Key Safety:
    Azure Key Vault HSM keys are stored in FIPS 140-2 Level 3 hardware
    security modules.  These keys CANNOT be extracted — even with physical
    access to the HSM.  A device wipe protects the shard holder's *local*
    key material (device unlock PIN, cached tokens, local shard copy).

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger("hive.remote_wipe")


# =============================================================================
# ENUMS
# =============================================================================

class DeviceStatus(str, Enum):
    """Device enrollment status."""
    ENROLLED = "enrolled"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    LOST = "lost"
    WIPED = "wiped"
    DECOMMISSIONED = "decommissioned"


class WipeStatus(str, Enum):
    """Remote wipe operation status."""
    PENDING = "pending"
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CONFIRMED = "confirmed"


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class DeviceRecord:
    """An enrolled device tracked by the remote wipe service."""

    device_id: str = ""
    holder_id: str = ""
    device_name: str = ""
    platform: str = ""                  # ios, android, windows, macos, linux
    azure_device_id: Optional[str] = None
    enrolled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: Optional[datetime] = None
    status: DeviceStatus = DeviceStatus.ENROLLED
    disk_encrypted: bool = False
    encryption_verified_at: Optional[datetime] = None
    fips_compliant: bool = False


@dataclass
class WipeOperation:
    """A remote wipe operation record."""

    operation_id: UUID = field(default_factory=uuid4)
    device_id: str = ""
    holder_id: str = ""
    reason: str = ""
    status: WipeStatus = WipeStatus.PENDING
    initiated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    shard_rotated: bool = False
    azure_response: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# REMOTE WIPE SERVICE
# =============================================================================

class RemoteWipe:
    """
    Device loss response service with Azure AD conditional access integration.

    Manages device enrollment, monitors encryption compliance, and provides
    immediate remote wipe + shard rotation capabilities when a device is
    reported lost or compromised.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for device registry persistence.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None`` for
        broadcasting wipe events to the hive event bus.
    azure_client : Any, optional
        Azure AD / Intune management client for issuing conditional
        access policies and wipe commands.
    key_sharding_service : Any, optional
        Reference to the KeyShardingService for shard rotation after
        a device is wiped.
    defcon_controller : Any, optional
        Reference to the DefconController for escalation on device loss.

    Usage
    -----
    ::

        wipe_service = RemoteWipe(
            db_pool=pool,
            azure_client=azure,
            key_sharding_service=sharding,
        )

        # Enroll a device
        await wipe_service.register_device("device_001", "holder_alpha")

        # Device lost!
        await wipe_service.on_device_lost("device_001")
    """

    def __init__(
        self,
        db_pool: Any = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        azure_client: Any = None,
        key_sharding_service: Any = None,
        defcon_controller: Any = None,
    ) -> None:
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._azure_client = azure_client
        self._key_sharding_service = key_sharding_service
        self._defcon_controller = defcon_controller

        # Device registry (device_id -> DeviceRecord)
        self._devices: Dict[str, DeviceRecord] = {}

        # Wipe operations history
        self._wipe_operations: List[WipeOperation] = []

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        # Metrics
        self._total_enrolled: int = 0
        self._total_wiped: int = 0
        self._total_shard_rotations: int = 0

        logger.info("RemoteWipe service initialized")

    # ------------------------------------------------------------------
    # Device Registration
    # ------------------------------------------------------------------

    async def register_device(
        self,
        device_id: str,
        holder_id: str,
        device_name: str = "",
        platform: str = "",
        azure_device_id: Optional[str] = None,
    ) -> DeviceRecord:
        """
        Register a device in the remote wipe registry.

        Before a device is registered, this method verifies that full
        disk encryption is enabled.  Unencrypted devices are rejected.

        Parameters
        ----------
        device_id : str
            Unique identifier for the device.
        holder_id : str
            The shard holder who owns this device.
        device_name : str, optional
            Human-readable device name.
        platform : str, optional
            Device platform (ios, android, windows, macos, linux).
        azure_device_id : str, optional
            Azure AD device ID for conditional access integration.

        Returns
        -------
        DeviceRecord
            The registered device record.

        Raises
        ------
        ValueError
            If disk encryption is not enabled or cannot be verified.
        """
        # Verify disk encryption
        encryption_status = await self._verify_disk_encryption(
            device_id, platform, azure_device_id
        )

        if not encryption_status["encrypted"]:
            logger.error(
                "device_registration_rejected device=%s reason=no_disk_encryption",
                device_id,
            )
            raise ValueError(
                f"Device {device_id} does not have full disk encryption enabled. "
                f"Enrollment denied — all shard holder devices MUST be encrypted."
            )

        record = DeviceRecord(
            device_id=device_id,
            holder_id=holder_id,
            device_name=device_name,
            platform=platform,
            azure_device_id=azure_device_id,
            status=DeviceStatus.ACTIVE,
            disk_encrypted=True,
            encryption_verified_at=datetime.now(timezone.utc),
            fips_compliant=encryption_status.get("fips_compliant", False),
        )

        async with self._lock:
            self._devices[device_id] = record
            self._total_enrolled += 1

        await self._persist_device(record)

        logger.info(
            "device_registered device=%s holder=%s platform=%s encrypted=True",
            device_id,
            holder_id,
            platform,
        )

        return record

    # ------------------------------------------------------------------
    # Remote Wipe
    # ------------------------------------------------------------------

    async def trigger_wipe(
        self,
        device_id: str,
        reason: str,
    ) -> WipeOperation:
        """
        Initiate a remote wipe on a registered device.

        This method:
        1. Revokes all active tokens for the device via Azure AD.
        2. Issues a remote wipe command via Azure Intune / conditional access.
        3. Marks the device as WIPED in the registry.

        Parameters
        ----------
        device_id : str
            The device to wipe.
        reason : str
            Reason for the wipe (e.g., "device_lost", "holder_compromised").

        Returns
        -------
        WipeOperation
            The wipe operation record with status.
        """
        device = self._devices.get(device_id)
        if not device:
            logger.error("wipe_failed device=%s reason=not_registered", device_id)
            raise ValueError(f"Device {device_id} is not registered")

        operation = WipeOperation(
            device_id=device_id,
            holder_id=device.holder_id,
            reason=reason,
        )

        logger.critical(
            "REMOTE_WIPE_INITIATED device=%s holder=%s reason=%s",
            device_id,
            device.holder_id,
            reason,
        )

        # Step 1: Revoke tokens via Azure AD
        await self._revoke_tokens(device, operation)

        # Step 2: Issue wipe command
        await self._issue_wipe_command(device, operation)

        # Step 3: Update device status
        async with self._lock:
            device.status = DeviceStatus.WIPED
            self._total_wiped += 1

        # Store operation
        self._wipe_operations.append(operation)
        await self._persist_wipe_operation(operation)

        # Broadcast event
        await self._broadcast_event(
            "hive.device.wiped",
            {
                "operation_id": str(operation.operation_id),
                "device_id": device_id,
                "holder_id": device.holder_id,
                "reason": reason,
                "status": operation.status.value,
            },
        )

        return operation

    # ------------------------------------------------------------------
    # Device Lost Response
    # ------------------------------------------------------------------

    async def on_device_lost(self, device_id: str) -> Dict[str, Any]:
        """
        Full response when a device is reported lost.

        Executes:
        1. Immediate remote wipe of the device.
        2. Shard rotation for the holder — their shard is regenerated
           and redistributed to a new device.
        3. DEFCON escalation if appropriate.

        Parameters
        ----------
        device_id : str
            The lost device identifier.

        Returns
        -------
        dict
            Summary of all actions taken.
        """
        device = self._devices.get(device_id)
        if not device:
            logger.error("device_lost_handler_failed device=%s reason=not_registered", device_id)
            return {"error": f"Device {device_id} not registered"}

        logger.critical(
            "DEVICE_LOST_REPORTED device=%s holder=%s",
            device_id,
            device.holder_id,
        )

        result: Dict[str, Any] = {
            "device_id": device_id,
            "holder_id": device.holder_id,
            "actions": [],
        }

        # Action 1: Immediate wipe
        try:
            wipe_op = await self.trigger_wipe(device_id, reason="device_lost")
            result["wipe_status"] = wipe_op.status.value
            result["actions"].append("remote_wipe_initiated")
        except Exception as exc:
            logger.error("device_lost_wipe_failed device=%s error=%s", device_id, exc)
            result["wipe_error"] = str(exc)

        # Action 2: Shard rotation
        try:
            if self._key_sharding_service:
                if hasattr(self._key_sharding_service, "rotate_holder_shard"):
                    await self._key_sharding_service.rotate_holder_shard(
                        holder_id=device.holder_id,
                        reason=f"device_lost:{device_id}",
                    )
                    self._total_shard_rotations += 1
                    result["shard_rotated"] = True
                    result["actions"].append("shard_rotation_complete")
            else:
                logger.critical(
                    "MANUAL_SHARD_ROTATION_REQUIRED for holder %s",
                    device.holder_id,
                )
                result["shard_rotated"] = False
        except Exception as exc:
            logger.error(
                "device_lost_shard_rotation_failed holder=%s error=%s",
                device.holder_id,
                exc,
            )
            result["shard_rotation_error"] = str(exc)

        # Action 3: DEFCON escalation (ELEVATED — single device loss)
        try:
            if self._defcon_controller and hasattr(self._defcon_controller, "escalate"):
                from app.models.hive_defense import DefconLevel
                await self._defcon_controller.escalate(
                    DefconLevel.ELEVATED,
                    f"Device lost: {device_id} (holder: {device.holder_id})",
                )
                result["defcon_escalated"] = True
                result["actions"].append("defcon_elevated")
        except Exception as exc:
            logger.error("device_lost_defcon_failed error=%s", exc)

        # Mark device as LOST
        async with self._lock:
            device.status = DeviceStatus.LOST

        logger.critical(
            "DEVICE_LOST_RESPONSE_COMPLETE device=%s actions=%s",
            device_id,
            result["actions"],
        )

        return result

    # ------------------------------------------------------------------
    # Encryption Verification
    # ------------------------------------------------------------------

    async def _verify_disk_encryption(
        self,
        device_id: str,
        platform: str,
        azure_device_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Verify that a device has full disk encryption enabled.

        Uses Azure AD / Intune compliance data when available, otherwise
        returns a conservative default.

        Returns
        -------
        dict
            ``encrypted`` (bool), ``method`` (str), ``fips_compliant`` (bool).
        """
        if self._azure_client and azure_device_id:
            try:
                if hasattr(self._azure_client, "get_device_compliance"):
                    compliance = await self._azure_client.get_device_compliance(
                        azure_device_id
                    )
                    return {
                        "encrypted": compliance.get("disk_encrypted", False),
                        "method": compliance.get("encryption_method", "unknown"),
                        "fips_compliant": compliance.get("fips_140_2", False),
                    }
            except Exception as exc:
                logger.warning(
                    "azure_encryption_check_failed device=%s error=%s",
                    device_id,
                    exc,
                )

        # Without Azure integration, we require manual attestation
        # Default to False — device must prove encryption
        logger.warning(
            "encryption_check_unavailable device=%s platform=%s "
            "— manual verification required",
            device_id,
            platform,
        )
        return {"encrypted": False, "method": "unverified", "fips_compliant": False}

    # ------------------------------------------------------------------
    # Azure AD Integration
    # ------------------------------------------------------------------

    async def _revoke_tokens(
        self,
        device: DeviceRecord,
        operation: WipeOperation,
    ) -> None:
        """Revoke all active OAuth tokens for the device via Azure AD."""
        if not self._azure_client:
            logger.warning("token_revocation_skipped reason=no_azure_client")
            return

        try:
            if hasattr(self._azure_client, "revoke_device_tokens"):
                await self._azure_client.revoke_device_tokens(
                    device_id=device.azure_device_id or device.device_id,
                )
                logger.info("tokens_revoked device=%s", device.device_id)
        except Exception as exc:
            logger.error(
                "token_revocation_failed device=%s error=%s",
                device.device_id,
                exc,
            )

    async def _issue_wipe_command(
        self,
        device: DeviceRecord,
        operation: WipeOperation,
    ) -> None:
        """Issue a remote wipe command via Azure Intune conditional access."""
        if not self._azure_client:
            operation.status = WipeStatus.PENDING
            logger.warning(
                "wipe_command_pending reason=no_azure_client device=%s",
                device.device_id,
            )
            return

        try:
            if hasattr(self._azure_client, "wipe_device"):
                response = await self._azure_client.wipe_device(
                    device_id=device.azure_device_id or device.device_id,
                    wipe_type="full",  # full wipe, not selective
                )
                operation.azure_response = response or {}
                operation.status = WipeStatus.INITIATED
                logger.info(
                    "wipe_command_issued device=%s status=initiated",
                    device.device_id,
                )
            else:
                operation.status = WipeStatus.PENDING
        except Exception as exc:
            operation.status = WipeStatus.FAILED
            logger.error(
                "wipe_command_failed device=%s error=%s",
                device.device_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_device(self, record: DeviceRecord) -> None:
        """Persist a device record to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_devices (
                        device_id, holder_id, device_name, platform,
                        azure_device_id, enrolled_at, status,
                        disk_encrypted, encryption_verified_at, fips_compliant
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (device_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        disk_encrypted = EXCLUDED.disk_encrypted,
                        encryption_verified_at = EXCLUDED.encryption_verified_at
                    """,
                    record.device_id,
                    record.holder_id,
                    record.device_name,
                    record.platform,
                    record.azure_device_id,
                    record.enrolled_at,
                    record.status.value,
                    record.disk_encrypted,
                    record.encryption_verified_at,
                    record.fips_compliant,
                )
        except Exception as exc:
            logger.error("device_persist_failed error=%s", exc)

    async def _persist_wipe_operation(self, operation: WipeOperation) -> None:
        """Persist a wipe operation to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_wipe_operations (
                        operation_id, device_id, holder_id, reason,
                        status, initiated_at, completed_at, shard_rotated
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    operation.operation_id,
                    operation.device_id,
                    operation.holder_id,
                    operation.reason,
                    operation.status.value,
                    operation.initiated_at,
                    operation.completed_at,
                    operation.shard_rotated,
                )
        except Exception as exc:
            logger.error("wipe_operation_persist_failed error=%s", exc)

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
                logger.error("wipe_event_broadcast_failed topic=%s error=%s", topic, exc)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_devices_for_holder(self, holder_id: str) -> List[DeviceRecord]:
        """Return all devices registered to a specific shard holder."""
        return [d for d in self._devices.values() if d.holder_id == holder_id]

    def get_device(self, device_id: str) -> Optional[DeviceRecord]:
        """Return a device record by ID."""
        return self._devices.get(device_id)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        status_counts: Dict[str, int] = {}
        for device in self._devices.values():
            status_counts[device.status.value] = status_counts.get(device.status.value, 0) + 1

        return {
            "total_enrolled": self._total_enrolled,
            "total_wiped": self._total_wiped,
            "total_shard_rotations": self._total_shard_rotations,
            "active_devices": len(self._devices),
            "status_breakdown": status_counts,
            "wipe_operations": len(self._wipe_operations),
        }

    def __repr__(self) -> str:
        return (
            f"<RemoteWipe devices={len(self._devices)} "
            f"wiped={self._total_wiped} "
            f"rotations={self._total_shard_rotations}>"
        )
