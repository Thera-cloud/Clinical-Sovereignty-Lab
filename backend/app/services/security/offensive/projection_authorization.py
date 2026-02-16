"""
HIVE DEFENSE PROTOCOL — Projection Authorization (Phase 8E)
NEVER automated. Nathan must explicitly approve each deployment.

The Projection Authorization service enforces the absolute requirement
that every Projected Helix deployment must be explicitly authorized by
Nathan (or a designated authority) before activation.  No automated
system, AI agent, or Fibre can bypass this gate.

Complete audit trail of all authorization decisions is maintained with
cryptographic integrity for legal and forensic purposes.

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import (
    AttackerProfile,
    PenetratorReport,
    ProjectionStatus,
)

logger = logging.getLogger("hive.projection_authorization")


# =============================================================================
# AUTHORIZATION STATUS
# =============================================================================

class AuthorizationStatus(str, Enum):
    """Authorization request state."""
    PENDING = "pending"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"


# =============================================================================
# DESIGNATED AUTHORITIES
# =============================================================================

# Only these identifiers can authorize Projected Helix deployments.
# In production this is loaded from a secure configuration store.
DESIGNATED_AUTHORITIES: List[str] = [
    "nathan",
    "nathan.nevedal",
    "nate",
]


# =============================================================================
# AUTHORIZATION REQUEST
# =============================================================================

class AuthorizationRequest:
    """
    A single authorization request for a Projected Helix deployment.

    Attributes
    ----------
    request_id : UUID
        Unique identifier for this request.
    target_profile : AttackerProfile
        The attacker profile the projection targets.
    penetrator_report : PenetratorReport
        The Penetrator intelligence supporting the request.
    justification : str
        Human-readable justification for the deployment.
    status : AuthorizationStatus
        Current status of the request.
    """

    def __init__(
        self,
        target_profile: AttackerProfile,
        penetrator_report: PenetratorReport,
        justification: str,
        *,
        request_id: Optional[UUID] = None,
    ) -> None:
        self.request_id: UUID = request_id or uuid4()
        self.target_profile: AttackerProfile = target_profile
        self.penetrator_report: PenetratorReport = penetrator_report
        self.justification: str = justification
        self.status: AuthorizationStatus = AuthorizationStatus.PENDING

        # Decision metadata
        self.requested_at: datetime = datetime.utcnow()
        self.decided_at: Optional[datetime] = None
        self.decided_by: Optional[str] = None
        self.denial_reason: Optional[str] = None
        self.deployment_id: Optional[UUID] = None

        # Integrity hash
        self._request_hash: str = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute an integrity hash for this request."""
        data = (
            f"{self.request_id}:"
            f"{self.target_profile.profile_id}:"
            f"{self.penetrator_report.mission_id}:"
            f"{self.justification}:"
            f"{self.requested_at.isoformat()}"
        )
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a dictionary."""
        return {
            "request_id": str(self.request_id),
            "target_profile_id": str(self.target_profile.profile_id),
            "penetrator_mission_id": str(self.penetrator_report.mission_id),
            "justification": self.justification,
            "status": self.status.value,
            "requested_at": self.requested_at.isoformat(),
            "decided_at": (
                self.decided_at.isoformat() if self.decided_at else None
            ),
            "decided_by": self.decided_by,
            "denial_reason": self.denial_reason,
            "deployment_id": (
                str(self.deployment_id) if self.deployment_id else None
            ),
            "request_hash": self._request_hash,
        }


# =============================================================================
# PROJECTION AUTHORIZATION
# =============================================================================

class ProjectionAuthorization:
    """
    Authorization gate for Projected Helix deployments.

    NEVER automated.  Every deployment requires explicit human
    authorization from Nathan or a designated authority.

    Maintains a complete, immutable audit trail of all authorization
    decisions with cryptographic integrity hashes.

    Attributes
    ----------
    requests : dict[UUID, AuthorizationRequest]
        All authorization requests, keyed by request ID.
    authorized_deployments : dict[UUID, UUID]
        Mapping of deployment_id → request_id for authorized deployments.
    audit_trail : list[dict]
        Immutable chronological record of all authorization decisions.

    Usage
    -----
    ::

        auth = ProjectionAuthorization()
        request = await auth.request_authorization(
            target_profile=profile,
            penetrator_report=report,
            justification="C&C identified at 203.0.113.42, ..."
        )
        # Nathan reviews and approves:
        deployment = await auth.authorize(
            request_id=request.request_id,
            authorized_by="nathan",
            passphrase="sacred-passphrase-here",
        )
        # Check authorization:
        is_auth = auth.is_authorized(deployment_id)
    """

    def __init__(
        self,
        *,
        passphrase_hash: Optional[str] = None,
        db_pool: Any = None,
    ) -> None:
        """
        Initialise the Projection Authorization service.

        Parameters
        ----------
        passphrase_hash:
            SHA-256 hash of the authorization passphrase.  If not provided,
            a default development passphrase hash is used.
        db_pool:
            Optional asyncpg pool for persistence.
        """
        # Passphrase verification
        self._passphrase_hash: str = passphrase_hash or hashlib.sha256(
            b"SOVEREIGN_HELIX_AUTH_DEV"
        ).hexdigest()

        self.db_pool = db_pool

        # Request registry
        self.requests: Dict[UUID, AuthorizationRequest] = {}

        # Authorization mapping: deployment_id → request_id
        self.authorized_deployments: Dict[UUID, UUID] = {}

        # Immutable audit trail
        self.audit_trail: List[Dict[str, Any]] = []

        logger.info(
            "ProjectionAuthorization initialised — ZERO automated "
            "deployments permitted"
        )

    # ------------------------------------------------------------------
    # Request authorization
    # ------------------------------------------------------------------

    async def request_authorization(
        self,
        target_profile: AttackerProfile,
        penetrator_report: PenetratorReport,
        justification: str,
    ) -> AuthorizationRequest:
        """
        Submit a request for Projected Helix deployment authorization.

        Parameters
        ----------
        target_profile:
            The attacker profile the projection would target.
        penetrator_report:
            The Penetrator intelligence supporting the request.
        justification:
            Human-readable justification for the deployment.

        Returns
        -------
        AuthorizationRequest
            The pending authorization request.
        """
        request = AuthorizationRequest(
            target_profile=target_profile,
            penetrator_report=penetrator_report,
            justification=justification,
        )

        self.requests[request.request_id] = request

        # Audit trail entry
        self._add_audit_entry(
            action="authorization_requested",
            request_id=request.request_id,
            details={
                "target_profile_id": str(target_profile.profile_id),
                "penetrator_mission_id": str(penetrator_report.mission_id),
                "justification": justification[:500],
                "cnc_addresses": penetrator_report.cnc_addresses,
            },
        )

        # Persist to DB if available
        await self._persist_request(request)

        logger.warning(
            "AUTHORIZATION REQUESTED: request=%s target=%s "
            "mission=%s — AWAITING HUMAN APPROVAL",
            request.request_id,
            target_profile.profile_id,
            penetrator_report.mission_id,
        )

        return request

    # ------------------------------------------------------------------
    # Authorize
    # ------------------------------------------------------------------

    async def authorize(
        self,
        request_id: UUID,
        authorized_by: str,
        passphrase: str,
    ) -> Dict[str, Any]:
        """
        Authorize a Projected Helix deployment.

        Parameters
        ----------
        request_id:
            The authorization request to approve.
        authorized_by:
            Identifier of the person authorizing (must be a designated
            authority).
        passphrase:
            The sacred authorization passphrase.

        Returns
        -------
        dict
            Authorization result with deployment_id if approved.

        Raises
        ------
        ValueError
            If the request is not found, the authority is invalid, or the
            passphrase is incorrect.
        """
        # Validate request exists
        if request_id not in self.requests:
            raise ValueError(f"Authorization request {request_id} not found")

        request = self.requests[request_id]

        # Validate request is still pending
        if request.status != AuthorizationStatus.PENDING:
            raise ValueError(
                f"Request {request_id} is already {request.status.value}"
            )

        # Validate authorized_by is a designated authority
        if not self._is_designated_authority(authorized_by):
            self._add_audit_entry(
                action="authorization_rejected_invalid_authority",
                request_id=request_id,
                details={
                    "attempted_by": authorized_by,
                    "reason": "Not a designated authority",
                },
            )
            logger.critical(
                "AUTHORIZATION REJECTED: unauthorized person '%s' "
                "attempted to authorize request %s",
                authorized_by,
                request_id,
            )
            raise ValueError(
                f"'{authorized_by}' is not a designated authority"
            )

        # Validate passphrase
        if not self._verify_passphrase(passphrase):
            self._add_audit_entry(
                action="authorization_rejected_bad_passphrase",
                request_id=request_id,
                details={
                    "attempted_by": authorized_by,
                    "reason": "Invalid passphrase",
                },
            )
            logger.critical(
                "AUTHORIZATION REJECTED: invalid passphrase from '%s' "
                "for request %s",
                authorized_by,
                request_id,
            )
            raise ValueError("Invalid authorization passphrase")

        # Approve the request
        deployment_id = uuid4()
        request.status = AuthorizationStatus.AUTHORIZED
        request.decided_at = datetime.utcnow()
        request.decided_by = authorized_by
        request.deployment_id = deployment_id

        self.authorized_deployments[deployment_id] = request_id

        # Audit trail
        self._add_audit_entry(
            action="authorization_granted",
            request_id=request_id,
            details={
                "authorized_by": authorized_by,
                "deployment_id": str(deployment_id),
                "target_profile_id": str(request.target_profile.profile_id),
            },
        )

        # Persist
        await self._persist_request(request)

        logger.warning(
            "AUTHORIZATION GRANTED: request=%s deployment=%s "
            "authorized_by=%s",
            request_id,
            deployment_id,
            authorized_by,
        )

        return {
            "authorized": True,
            "request_id": str(request_id),
            "deployment_id": str(deployment_id),
            "authorized_by": authorized_by,
            "authorized_at": request.decided_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Deny
    # ------------------------------------------------------------------

    async def deny(
        self,
        request_id: UUID,
        reason: str,
        denied_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deny a Projected Helix deployment request.

        Parameters
        ----------
        request_id:
            The authorization request to deny.
        reason:
            Reason for denial.
        denied_by:
            Who denied the request (optional).

        Returns
        -------
        dict
            Denial result.

        Raises
        ------
        ValueError
            If the request is not found or not pending.
        """
        if request_id not in self.requests:
            raise ValueError(f"Authorization request {request_id} not found")

        request = self.requests[request_id]

        if request.status != AuthorizationStatus.PENDING:
            raise ValueError(
                f"Request {request_id} is already {request.status.value}"
            )

        request.status = AuthorizationStatus.DENIED
        request.decided_at = datetime.utcnow()
        request.decided_by = denied_by
        request.denial_reason = reason

        # Audit trail
        self._add_audit_entry(
            action="authorization_denied",
            request_id=request_id,
            details={
                "denied_by": denied_by or "unknown",
                "reason": reason,
            },
        )

        # Persist
        await self._persist_request(request)

        logger.warning(
            "AUTHORIZATION DENIED: request=%s reason='%s' denied_by=%s",
            request_id,
            reason,
            denied_by or "unknown",
        )

        return {
            "authorized": False,
            "request_id": str(request_id),
            "reason": reason,
            "denied_by": denied_by,
            "denied_at": request.decided_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Authorization check
    # ------------------------------------------------------------------

    def is_authorized(self, deployment_id: UUID) -> bool:
        """
        Check whether a deployment is authorized.

        Parameters
        ----------
        deployment_id:
            The deployment UUID to check.

        Returns
        -------
        bool
            ``True`` if the deployment has been explicitly authorized and
            the authorization has not been revoked.
        """
        if deployment_id not in self.authorized_deployments:
            return False

        request_id = self.authorized_deployments[deployment_id]
        request = self.requests.get(request_id)
        if not request:
            return False

        return request.status == AuthorizationStatus.AUTHORIZED

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    async def revoke(
        self,
        deployment_id: UUID,
        reason: str,
        revoked_by: str,
    ) -> Dict[str, Any]:
        """
        Revoke authorization for an active deployment.

        Parameters
        ----------
        deployment_id:
            The deployment to revoke authorization for.
        reason:
            Reason for revocation.
        revoked_by:
            Who revoked the authorization.

        Returns
        -------
        dict
            Revocation result.
        """
        if deployment_id not in self.authorized_deployments:
            raise ValueError(
                f"Deployment {deployment_id} has no authorization record"
            )

        request_id = self.authorized_deployments[deployment_id]
        request = self.requests.get(request_id)
        if not request:
            raise ValueError(f"Authorization request {request_id} not found")

        request.status = AuthorizationStatus.REVOKED

        # Audit trail
        self._add_audit_entry(
            action="authorization_revoked",
            request_id=request_id,
            details={
                "deployment_id": str(deployment_id),
                "revoked_by": revoked_by,
                "reason": reason,
            },
        )

        logger.warning(
            "AUTHORIZATION REVOKED: deployment=%s request=%s "
            "revoked_by=%s reason='%s'",
            deployment_id,
            request_id,
            revoked_by,
            reason,
        )

        return {
            "revoked": True,
            "deployment_id": str(deployment_id),
            "request_id": str(request_id),
            "revoked_by": revoked_by,
            "reason": reason,
            "revoked_at": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Authority verification
    # ------------------------------------------------------------------

    @staticmethod
    def _is_designated_authority(identity: str) -> bool:
        """
        Verify that the given identity is a designated authority.

        Parameters
        ----------
        identity:
            The claimed identity to verify.

        Returns
        -------
        bool
            ``True`` if the identity is in the designated authorities list.
        """
        return identity.lower().strip() in DESIGNATED_AUTHORITIES

    def _verify_passphrase(self, passphrase: str) -> bool:
        """
        Verify the authorization passphrase.

        Parameters
        ----------
        passphrase:
            The passphrase to verify.

        Returns
        -------
        bool
            ``True`` if the passphrase hash matches.
        """
        provided_hash = hashlib.sha256(passphrase.encode()).hexdigest()
        return provided_hash == self._passphrase_hash

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def _add_audit_entry(
        self,
        action: str,
        request_id: UUID,
        details: Dict[str, Any],
    ) -> None:
        """
        Add an immutable entry to the audit trail.

        Parameters
        ----------
        action:
            The action being recorded.
        request_id:
            The related authorization request.
        details:
            Action-specific details.
        """
        entry: Dict[str, Any] = {
            "entry_id": str(uuid4()),
            "action": action,
            "request_id": str(request_id),
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Chain hash for immutability
        previous_hash = (
            self.audit_trail[-1].get("chain_hash", "")
            if self.audit_trail
            else ""
        )
        chain_data = f"{entry['entry_id']}:{action}:{entry['timestamp']}:{previous_hash}"
        entry["chain_hash"] = hashlib.sha256(chain_data.encode()).hexdigest()

        self.audit_trail.append(entry)

    def get_audit_trail(
        self,
        request_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the audit trail, optionally filtered by request.

        Parameters
        ----------
        request_id:
            Optional filter by request ID.
        limit:
            Maximum entries to return.

        Returns
        -------
        list[dict]
            Audit trail entries, newest first.
        """
        entries = self.audit_trail
        if request_id:
            rid = str(request_id)
            entries = [e for e in entries if e.get("request_id") == rid]
        return list(reversed(entries[-limit:]))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_request(self, request: AuthorizationRequest) -> None:
        """Persist an authorization request to the database (best-effort)."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_projection_authorizations (
                        request_id, target_profile_id, penetrator_mission_id,
                        justification, status, requested_at, decided_at,
                        decided_by, denial_reason, deployment_id, request_hash
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (request_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        decided_at = EXCLUDED.decided_at,
                        decided_by = EXCLUDED.decided_by,
                        denial_reason = EXCLUDED.denial_reason,
                        deployment_id = EXCLUDED.deployment_id
                    """,
                    request.request_id,
                    request.target_profile.profile_id,
                    request.penetrator_report.mission_id,
                    request.justification,
                    request.status.value,
                    request.requested_at,
                    request.decided_at,
                    request.decided_by,
                    request.denial_reason,
                    request.deployment_id,
                    request._request_hash,
                )
        except Exception as exc:
            logger.warning(
                "Failed to persist authorization request %s: %s",
                request.request_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Number of pending authorization requests."""
        return sum(
            1
            for r in self.requests.values()
            if r.status == AuthorizationStatus.PENDING
        )

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        status_counts: Dict[str, int] = {}
        for r in self.requests.values():
            status_counts[r.status.value] = (
                status_counts.get(r.status.value, 0) + 1
            )

        return {
            "total_requests": len(self.requests),
            "pending": self.pending_count,
            "authorized_deployments": len(self.authorized_deployments),
            "status_breakdown": status_counts,
            "audit_trail_length": len(self.audit_trail),
        }

    def __repr__(self) -> str:
        return (
            f"<ProjectionAuthorization requests={len(self.requests)} "
            f"pending={self.pending_count} "
            f"authorized={len(self.authorized_deployments)}>"
        )
