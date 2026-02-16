"""
HIVE DEFENSE PROTOCOL — Tripwire Network (Phase 8C, Third Cord)
Active traps embedded in synthetic data that confirm attacker presence.

Tripwires are planted inside mirror containment zones as synthetic
artefacts that appear indistinguishable from real data.  When an
attacker interacts with them, the tripwire triggers — providing
irrefutable proof that the attacker is inside the mirror and enabling
immediate DEFCON escalation.

Tripwire Types
--------------
1. **Synthetic emails** — addresses that trigger a callback on external
   DNS/SMTP lookup.  If the attacker tries to contact a "member" using
   one of these addresses, the lookup hits our monitoring endpoint.
2. **Synthetic credentials** — username/password pairs that, when used,
   connect to a secondary honeypot system instead of the real
   infrastructure.  Any authentication attempt with these credentials
   is proof of mirror compromise.
3. **Synthetic Nevedal scores** — C_emo values containing mathematical
   signatures (specific digit patterns) that only the real Nevedal
   Engine can verify.  If an attacker exports or publishes these
   scores, the pattern identifies them as synthetic.

Events
------
* ``hive.tripwire.activated`` — a tripwire was triggered
* ``hive.tripwire.credential_used`` — synthetic credential was used

Patent-Pending — Claim 51
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.models.hive_defense import (
    CanaryCredential,
    DefconLevel,
    TripwireActivation,
)

logger = logging.getLogger("hive.tripwire_network")


# =============================================================================
# CONSTANTS
# =============================================================================

# Tripwire types
class TripwireType(str, Enum):
    """Types of tripwires that can be deployed."""
    SYNTHETIC_EMAIL = "synthetic_email"
    SYNTHETIC_CREDENTIAL = "synthetic_credential"
    SYNTHETIC_NEVEDAL_SCORE = "synthetic_nevedal_score"
    SYNTHETIC_API_KEY = "synthetic_api_key"
    SYNTHETIC_DB_RECORD = "synthetic_db_record"


class TripwireState(str, Enum):
    """Current state of a deployed tripwire."""
    PLANTED = "planted"
    ACTIVE = "active"
    TRIGGERED = "triggered"
    DECOMMISSIONED = "decommissioned"


# Nevedal score signature: a specific digit pattern at decimal places 7-10
# that only appears in synthetic scores (never in real C_emo output).
NEVEDAL_SIGNATURE_MARKER = "7392"
NEVEDAL_SIGNATURE_POSITION = 7  # Starting decimal position


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Tripwire:
    """
    A single tripwire deployed in a containment zone.

    Attributes
    ----------
    tripwire_id : UUID
        Unique identifier.
    tripwire_type : TripwireType
        Category of tripwire.
    containment_zone : str
        The zone this tripwire is planted in.
    state : TripwireState
        Current lifecycle state.
    bait_data : dict
        The synthetic artefact planted as bait.
    verification_hash : str
        Hash used to verify a trigger is genuine.
    planted_at : datetime
        When this tripwire was deployed.
    triggered_at : datetime or None
        When the tripwire was triggered (None if not yet).
    trigger_evidence : dict
        Evidence collected when triggered.
    """
    tripwire_id: UUID = field(default_factory=uuid4)
    tripwire_type: TripwireType = TripwireType.SYNTHETIC_EMAIL
    containment_zone: str = ""
    state: TripwireState = TripwireState.PLANTED
    bait_data: Dict[str, Any] = field(default_factory=dict)
    verification_hash: str = ""
    planted_at: datetime = field(default_factory=datetime.utcnow)
    triggered_at: Optional[datetime] = None
    trigger_evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize tripwire state."""
        return {
            "tripwire_id": str(self.tripwire_id),
            "tripwire_type": self.tripwire_type.value,
            "containment_zone": self.containment_zone,
            "state": self.state.value,
            "planted_at": self.planted_at.isoformat(),
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "has_evidence": bool(self.trigger_evidence),
        }


@dataclass
class TripwireDeploymentResult:
    """
    Result of deploying tripwires into a containment zone.

    Attributes
    ----------
    containment_zone : str
        The zone where tripwires were deployed.
    tripwires_planted : int
        Total number of tripwires deployed.
    tripwire_ids : list[UUID]
        IDs of all deployed tripwires.
    types_deployed : dict[str, int]
        Count of each tripwire type deployed.
    deployed_at : datetime
        When the deployment completed.
    """
    containment_zone: str = ""
    tripwires_planted: int = 0
    tripwire_ids: List[UUID] = field(default_factory=list)
    types_deployed: Dict[str, int] = field(default_factory=dict)
    deployed_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# TRIPWIRE NETWORK
# =============================================================================

class TripwireNetwork:
    """
    Active trap network embedded in mirror containment zones.

    Deploys synthetic artefacts (emails, credentials, Nevedal scores)
    that trigger alarms when an attacker interacts with them, providing
    irrefutable proof of containment and enabling DEFCON escalation.

    Parameters
    ----------
    nevedal_signature : str
        The digit pattern used to watermark synthetic Nevedal scores
        (default "7392").
    tripwires_per_zone : int
        Number of tripwires to deploy per containment zone (default 12).

    Usage
    -----
    ::

        network = TripwireNetwork()

        # Deploy tripwires into a containment zone
        result = await network.deploy_tripwires("mirror-zone-alpha")

        # Check if a specific tripwire was triggered
        triggered = await network.check_tripwire(tripwire_id)

        # Handle a trigger event
        await network.on_tripwire_triggered(tripwire_id, evidence)
    """

    def __init__(
        self,
        *,
        nevedal_signature: str = NEVEDAL_SIGNATURE_MARKER,
        tripwires_per_zone: int = 12,
    ) -> None:
        self._nevedal_signature = nevedal_signature
        self._tripwires_per_zone = tripwires_per_zone

        # Tripwire storage: tripwire_id → Tripwire
        self._tripwires: Dict[UUID, Tripwire] = {}
        # Zone index: containment_zone → set of tripwire_ids
        self._zone_index: Dict[str, Set[UUID]] = {}

        # Event callback registry
        self._event_callbacks: List[Any] = []

        # Forensic event log
        self._event_log: List[Dict[str, Any]] = []

        # Concurrency
        self._lock = asyncio.Lock()

        # Stats
        self._total_deployed: int = 0
        self._total_triggered: int = 0

        logger.info(
            "TripwireNetwork initialised — %d tripwires/zone, "
            "Nevedal signature='%s'",
            self._tripwires_per_zone,
            self._nevedal_signature,
        )

    # --------------------------------------------------------------------- #
    # TRIPWIRE DEPLOYMENT
    # --------------------------------------------------------------------- #

    async def deploy_tripwires(
        self,
        containment_zone: str,
        count: Optional[int] = None,
    ) -> TripwireDeploymentResult:
        """
        Deploy a full set of tripwires into a containment zone.

        A balanced mix of tripwire types is planted: synthetic emails,
        credentials, and Nevedal scores distributed to maximize
        coverage.

        Parameters
        ----------
        containment_zone : str
            Identifier of the containment zone to plant tripwires in.
        count : int or None
            Number of tripwires to deploy.  If None, uses the configured
            default (``tripwires_per_zone``).

        Returns
        -------
        TripwireDeploymentResult
            Summary of the deployment.
        """
        total = count or self._tripwires_per_zone
        tripwires: List[Tripwire] = []
        type_counts: Dict[str, int] = {}

        # Balanced distribution across types
        types = list(TripwireType)
        for i in range(total):
            tw_type = types[i % len(types)]
            tripwire = await self._create_tripwire(tw_type, containment_zone)
            tripwires.append(tripwire)
            type_counts[tw_type.value] = type_counts.get(tw_type.value, 0) + 1

        # Register all tripwires
        async with self._lock:
            if containment_zone not in self._zone_index:
                self._zone_index[containment_zone] = set()

            for tw in tripwires:
                tw.state = TripwireState.ACTIVE
                self._tripwires[tw.tripwire_id] = tw
                self._zone_index[containment_zone].add(tw.tripwire_id)
                self._total_deployed += 1

        result = TripwireDeploymentResult(
            containment_zone=containment_zone,
            tripwires_planted=total,
            tripwire_ids=[tw.tripwire_id for tw in tripwires],
            types_deployed=type_counts,
        )

        self._event_log.append({
            "event": "hive.tripwire.deployed",
            "containment_zone": containment_zone,
            "count": total,
            "types": type_counts,
            "timestamp": datetime.utcnow().isoformat(),
        })

        logger.info(
            "Deployed %d tripwires into zone '%s' — types: %s",
            total,
            containment_zone,
            type_counts,
        )

        return result

    async def _create_tripwire(
        self,
        tw_type: TripwireType,
        containment_zone: str,
    ) -> Tripwire:
        """
        Create a single tripwire of the specified type.

        Generates type-appropriate bait data and a verification hash.

        Parameters
        ----------
        tw_type : TripwireType
            The type of tripwire to create.
        containment_zone : str
            The zone where it will be deployed.

        Returns
        -------
        Tripwire
        """
        tripwire_id = uuid4()

        # Generate type-specific bait data
        if tw_type == TripwireType.SYNTHETIC_EMAIL:
            bait_data = self._generate_synthetic_email(tripwire_id)
        elif tw_type == TripwireType.SYNTHETIC_CREDENTIAL:
            bait_data = self._generate_synthetic_credential(tripwire_id)
        elif tw_type == TripwireType.SYNTHETIC_NEVEDAL_SCORE:
            bait_data = self._generate_synthetic_nevedal_score(tripwire_id)
        elif tw_type == TripwireType.SYNTHETIC_API_KEY:
            bait_data = self._generate_synthetic_api_key(tripwire_id)
        elif tw_type == TripwireType.SYNTHETIC_DB_RECORD:
            bait_data = self._generate_synthetic_db_record(tripwire_id)
        else:
            bait_data = {"type": tw_type.value}

        # Verification hash — proves trigger authenticity
        verification_material = (
            f"{tripwire_id}:{tw_type.value}:{containment_zone}"
        )
        verification_hash = hashlib.sha256(
            verification_material.encode()
        ).hexdigest()

        return Tripwire(
            tripwire_id=tripwire_id,
            tripwire_type=tw_type,
            containment_zone=containment_zone,
            bait_data=bait_data,
            verification_hash=verification_hash,
        )

    # --------------------------------------------------------------------- #
    # BAIT DATA GENERATORS
    # --------------------------------------------------------------------- #

    @staticmethod
    def _generate_synthetic_email(tripwire_id: UUID) -> Dict[str, Any]:
        """
        Generate a synthetic email address that triggers on external lookup.

        The address uses a domain we control for DNS monitoring.
        Any MX/SMTP lookup against this domain triggers the tripwire.
        """
        # Generate a plausible-looking local part
        hash_bytes = hashlib.sha256(tripwire_id.bytes).hexdigest()[:8]
        first_names = ["sarah", "michael", "jennifer", "david", "emily", "james"]
        last_names = ["martinez", "chen", "thompson", "patel", "williams", "brown"]

        idx1 = struct.unpack("B", os.urandom(1))[0]
        idx2 = struct.unpack("B", os.urandom(1))[0]
        first = first_names[idx1 % len(first_names)]
        last = last_names[idx2 % len(last_names)]

        # The monitoring subdomain encodes the tripwire ID
        email = f"{first}.{last}@members.sanctuary-verify.net"
        callback_subdomain = f"tw-{hash_bytes}.sanctuary-verify.net"

        return {
            "email": email,
            "display_name": f"{first.title()} {last.title()}",
            "callback_subdomain": callback_subdomain,
            "tripwire_id_encoded": hash_bytes,
        }

    @staticmethod
    def _generate_synthetic_credential(tripwire_id: UUID) -> Dict[str, Any]:
        """
        Generate a synthetic credential pair that connects to a secondary
        honeypot when used.
        """
        hash_hex = hashlib.sha256(tripwire_id.bytes).hexdigest()

        username = f"svc_{hash_hex[:8]}"
        # Password looks like a real service credential
        password_material = os.urandom(24)
        password = hashlib.sha256(password_material).hexdigest()[:32]

        return {
            "username": username,
            "password_hash": hashlib.sha256(password.encode()).hexdigest(),
            "password_prefix": password[:4] + "****",
            "target_service": "sanctuary-internal-api",
            "honeypot_endpoint": f"https://honeypot.sanctuary-verify.net/auth",
            "tripwire_id_encoded": hash_hex[:12],
        }

    def _generate_synthetic_nevedal_score(
        self,
        tripwire_id: UUID,
    ) -> Dict[str, Any]:
        """
        Generate a synthetic Nevedal C_emo score with a mathematical
        signature that only the real engine can verify.

        The signature is embedded at a specific decimal position within
        the score value, making it invisible to casual inspection but
        detectable by the verification algorithm.
        """
        # Generate a plausible C_emo value (typically 0.0 to 1.0)
        raw_bytes = os.urandom(8)
        raw_value = struct.unpack("d", raw_bytes)[0]
        # Normalize to plausible range
        base_score = abs(raw_value) % 1.0

        # Embed the signature at the target decimal position
        score_str = f"{base_score:.15f}"
        digits = list(score_str)
        # Find the decimal point position
        dot_pos = digits.index(".")
        sig_start = dot_pos + 1 + NEVEDAL_SIGNATURE_POSITION

        # Inject signature digits
        for i, char in enumerate(self._nevedal_signature):
            if sig_start + i < len(digits):
                digits[sig_start + i] = char

        signed_score = float("".join(digits))

        return {
            "c_emo_score": signed_score,
            "coherence_window_ms": 15000,
            "measurement_type": "voice_biometric",
            "signature_embedded": True,
            "signature_position": NEVEDAL_SIGNATURE_POSITION,
            "tripwire_id_encoded": hashlib.sha256(
                tripwire_id.bytes
            ).hexdigest()[:12],
        }

    @staticmethod
    def _generate_synthetic_api_key(tripwire_id: UUID) -> Dict[str, Any]:
        """Generate a synthetic API key that triggers on use."""
        hash_hex = hashlib.sha256(tripwire_id.bytes).hexdigest()
        key = f"sk_live_{hash_hex[:32]}"

        return {
            "api_key_prefix": key[:12] + "****",
            "key_hash": hashlib.sha256(key.encode()).hexdigest(),
            "service": "sanctuary-ai-bridge",
            "permissions": ["read:sessions", "write:notes"],
            "tripwire_id_encoded": hash_hex[:12],
        }

    @staticmethod
    def _generate_synthetic_db_record(tripwire_id: UUID) -> Dict[str, Any]:
        """Generate a synthetic database record with traceable markers."""
        hash_hex = hashlib.sha256(tripwire_id.bytes).hexdigest()

        return {
            "record_type": "member_profile",
            "synthetic_member_id": f"mem_{hash_hex[:10]}",
            "display_name": "Synthetic Member",
            "tier": "inner_chamber",
            "created_at": datetime.utcnow().isoformat(),
            "tripwire_id_encoded": hash_hex[:12],
        }

    # --------------------------------------------------------------------- #
    # TRIPWIRE CHECKING
    # --------------------------------------------------------------------- #

    async def check_tripwire(self, tripwire_id: UUID) -> bool:
        """
        Check whether a specific tripwire has been triggered.

        Parameters
        ----------
        tripwire_id : UUID
            The tripwire to check.

        Returns
        -------
        bool
            True if the tripwire has been triggered.

        Raises
        ------
        KeyError
            If no tripwire with the given ID exists.
        """
        async with self._lock:
            tw = self._tripwires.get(tripwire_id)
            if tw is None:
                raise KeyError(f"Tripwire {tripwire_id} not found.")
            return tw.state == TripwireState.TRIGGERED

    async def get_tripwire(self, tripwire_id: UUID) -> Optional[Tripwire]:
        """Return a tripwire by ID, or None if not found."""
        async with self._lock:
            return self._tripwires.get(tripwire_id)

    # --------------------------------------------------------------------- #
    # TRIPWIRE TRIGGER HANDLING
    # --------------------------------------------------------------------- #

    async def on_tripwire_triggered(
        self,
        tripwire_id: UUID,
        evidence: Dict[str, Any],
    ) -> TripwireActivation:
        """
        Handle a tripwire trigger event.

        Records the evidence, marks the tripwire as triggered, logs
        the forensic event, and initiates DEFCON escalation.

        Parameters
        ----------
        tripwire_id : UUID
            The triggered tripwire.
        evidence : dict
            Evidence collected at trigger time (source IP, timestamp,
            request details, etc.).

        Returns
        -------
        TripwireActivation
            The activation record.

        Raises
        ------
        KeyError
            If no tripwire with the given ID exists.
        """
        async with self._lock:
            tw = self._tripwires.get(tripwire_id)
            if tw is None:
                raise KeyError(f"Tripwire {tripwire_id} not found.")

            # Mark as triggered
            tw.state = TripwireState.TRIGGERED
            tw.triggered_at = datetime.utcnow()
            tw.trigger_evidence = evidence
            self._total_triggered += 1

        # Create activation record
        activation = TripwireActivation(
            tripwire_id=tripwire_id,
            tripwire_type=tw.tripwire_type.value,
            containment_zone=tw.containment_zone,
            triggered_by=evidence.get("source", "unknown"),
            evidence={
                "tripwire_type": tw.tripwire_type.value,
                "containment_zone": tw.containment_zone,
                "bait_type": tw.tripwire_type.value,
                "trigger_evidence": evidence,
                "verification_hash": tw.verification_hash,
            },
        )

        # Determine the appropriate event type
        if tw.tripwire_type == TripwireType.SYNTHETIC_CREDENTIAL:
            event_type = "hive.tripwire.credential_used"
        else:
            event_type = "hive.tripwire.activated"

        self._event_log.append({
            "event": event_type,
            "tripwire_id": str(tripwire_id),
            "tripwire_type": tw.tripwire_type.value,
            "containment_zone": tw.containment_zone,
            "evidence": evidence,
            "timestamp": datetime.utcnow().isoformat(),
        })

        logger.critical(
            "TRIPWIRE TRIGGERED — type=%s, zone='%s', id=%s — "
            "attacker confirmed in mirror — DEFCON escalation required",
            tw.tripwire_type.value,
            tw.containment_zone,
            tripwire_id,
        )

        return activation

    # --------------------------------------------------------------------- #
    # NEVEDAL SCORE VERIFICATION
    # --------------------------------------------------------------------- #

    def verify_nevedal_score(self, c_emo_score: float) -> bool:
        """
        Verify whether a Nevedal C_emo score contains the synthetic
        signature pattern.

        This allows identification of exfiltrated synthetic scores
        even if the attacker publishes them externally.

        Parameters
        ----------
        c_emo_score : float
            The C_emo score value to verify.

        Returns
        -------
        bool
            True if the score contains the synthetic signature (i.e.
            it is from the mirror, not the real system).
        """
        score_str = f"{c_emo_score:.15f}"
        dot_pos = score_str.index(".")
        sig_start = dot_pos + 1 + NEVEDAL_SIGNATURE_POSITION
        sig_end = sig_start + len(self._nevedal_signature)

        if sig_end > len(score_str):
            return False

        extracted = score_str[sig_start:sig_end]
        return extracted == self._nevedal_signature

    # --------------------------------------------------------------------- #
    # ZONE MANAGEMENT
    # --------------------------------------------------------------------- #

    async def get_zone_tripwires(
        self,
        containment_zone: str,
    ) -> List[Tripwire]:
        """Return all tripwires deployed in a specific zone."""
        async with self._lock:
            ids = self._zone_index.get(containment_zone, set())
            return [
                self._tripwires[tid]
                for tid in ids
                if tid in self._tripwires
            ]

    async def get_triggered_tripwires(
        self,
        containment_zone: Optional[str] = None,
    ) -> List[Tripwire]:
        """
        Return all triggered tripwires, optionally filtered by zone.

        Parameters
        ----------
        containment_zone : str or None
            If provided, filter to this zone only.

        Returns
        -------
        list[Tripwire]
        """
        async with self._lock:
            if containment_zone:
                ids = self._zone_index.get(containment_zone, set())
                candidates = [
                    self._tripwires[tid]
                    for tid in ids
                    if tid in self._tripwires
                ]
            else:
                candidates = list(self._tripwires.values())

            return [
                tw for tw in candidates
                if tw.state == TripwireState.TRIGGERED
            ]

    async def decommission_zone(self, containment_zone: str) -> int:
        """
        Decommission all tripwires in a zone.

        Returns
        -------
        int
            Number of tripwires decommissioned.
        """
        async with self._lock:
            ids = self._zone_index.pop(containment_zone, set())
            count = 0
            for tid in ids:
                tw = self._tripwires.get(tid)
                if tw:
                    tw.state = TripwireState.DECOMMISSIONED
                    count += 1

        logger.info(
            "Decommissioned %d tripwires from zone '%s'",
            count,
            containment_zone,
        )
        return count

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of tripwire network state."""
        active_count = sum(
            1 for tw in self._tripwires.values()
            if tw.state == TripwireState.ACTIVE
        )
        triggered_count = sum(
            1 for tw in self._tripwires.values()
            if tw.state == TripwireState.TRIGGERED
        )
        return {
            "total_deployed": self._total_deployed,
            "total_triggered": self._total_triggered,
            "active_tripwires": active_count,
            "triggered_tripwires": triggered_count,
            "zones_monitored": len(self._zone_index),
            "tripwires_per_zone": self._tripwires_per_zone,
            "nevedal_signature": self._nevedal_signature,
        }

    def __repr__(self) -> str:
        return (
            f"<TripwireNetwork deployed={self._total_deployed} "
            f"triggered={self._total_triggered} "
            f"zones={len(self._zone_index)}>"
        )
