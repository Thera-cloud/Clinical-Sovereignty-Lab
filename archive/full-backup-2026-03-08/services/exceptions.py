"""
SOVEREIGN SWARM — Exception Hierarchy
Full exception taxonomy for the Sovereign Swarm Intelligence Framework.
Every subsystem raises from a common root so callers can catch at any granularity.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID


# =============================================================================
# ROOT
# =============================================================================

class SovereignException(Exception):
    """Base exception for all Sovereign Swarm operations."""

    def __init__(self, message: str = "", details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


# =============================================================================
# SECURITY DOMAIN
# =============================================================================

class SecurityException(SovereignException):
    """Base for all security-related exceptions."""
    pass


class EthicalViolationException(SecurityException):
    """A Fibre attempted to violate the Frozen Ethical Core."""

    def __init__(self, fibre_id: Optional[UUID] = None, violation: str = "", **kwargs):
        self.fibre_id = fibre_id
        self.violation = violation
        super().__init__(
            message=f"Ethical violation by Fibre {fibre_id}: {violation}",
            details={"fibre_id": str(fibre_id), "violation": violation, **kwargs},
        )


class IdentityException(SecurityException):
    """Ed25519 identity verification failure."""

    def __init__(self, entity_id: Optional[UUID] = None, reason: str = "", **kwargs):
        self.entity_id = entity_id
        super().__init__(
            message=f"Identity verification failed for {entity_id}: {reason}",
            details={"entity_id": str(entity_id), "reason": reason, **kwargs},
        )


class QuarantineException(SecurityException):
    """A Fibre has been quarantined due to anomalous behavior."""

    def __init__(self, fibre_id: Optional[UUID] = None, reason: str = "", **kwargs):
        self.fibre_id = fibre_id
        super().__init__(
            message=f"Fibre {fibre_id} quarantined: {reason}",
            details={"fibre_id": str(fibre_id), "reason": reason, **kwargs},
        )


class PromptInjectionException(SecurityException):
    """Detected prompt injection attack in input data."""

    def __init__(self, source: str = "", pattern: str = "", **kwargs):
        super().__init__(
            message=f"Prompt injection detected from {source}",
            details={"source": source, "pattern": pattern, **kwargs},
        )


# =============================================================================
# FIBRE DOMAIN
# =============================================================================

class FibreException(SovereignException):
    """Base for Fibre lifecycle/operation errors."""
    pass


class FibreSpawnException(FibreException):
    """Failed to spawn a new Fibre."""
    pass


class FibrePruneException(FibreException):
    """Failed to prune a Fibre."""
    pass


class FibreBudgetExceededException(FibreException):
    """Fibre has exceeded its token budget."""

    def __init__(self, fibre_id: Optional[UUID] = None, budget: int = 0, used: int = 0, **kwargs):
        self.fibre_id = fibre_id
        super().__init__(
            message=f"Fibre {fibre_id} exceeded budget: {used}/{budget} tokens",
            details={"fibre_id": str(fibre_id), "budget": budget, "used": used, **kwargs},
        )


class FibreAlignmentDriftException(FibreException):
    """Fibre alignment scores have drifted below acceptable thresholds."""

    def __init__(self, fibre_id: Optional[UUID] = None, scores: Optional[Dict[str, float]] = None, **kwargs):
        self.fibre_id = fibre_id
        super().__init__(
            message=f"Fibre {fibre_id} alignment drift detected",
            details={"fibre_id": str(fibre_id), "scores": scores or {}, **kwargs},
        )


# =============================================================================
# MESH DOMAIN
# =============================================================================

class MeshException(SovereignException):
    """Base for Wisdom Mesh communication errors."""
    pass


class MeshDeliveryException(MeshException):
    """Failed to deliver a message on the Wisdom Mesh."""
    pass


class MeshConvergenceException(MeshException):
    """Error during convergence detection."""
    pass


class MeshBandwidthException(MeshException):
    """Mesh bandwidth limits exceeded."""
    pass


# =============================================================================
# COHERENCE DOMAIN
# =============================================================================

class CoherenceException(SovereignException):
    """Base for coherence measurement errors."""
    pass


class InsufficientDataException(CoherenceException):
    """Not enough data to compute coherence at the requested layer."""

    def __init__(self, layer: str = "", required: int = 0, available: int = 0, **kwargs):
        super().__init__(
            message=f"Insufficient data for {layer} layer: {available}/{required}",
            details={"layer": layer, "required": required, "available": available, **kwargs},
        )


# =============================================================================
# STRATEGY DOMAIN
# =============================================================================

class StrategyException(SovereignException):
    """Base for strategic memory / approval protocol errors."""
    pass


class ProposalNotFoundException(StrategyException):
    """Requested strategy proposal not found."""
    pass


class ApprovalTimeoutException(StrategyException):
    """Approval window expired without a response."""
    pass


class AutoExecuteBlockedException(StrategyException):
    """Auto-execute was blocked because risk is too high."""
    pass


# =============================================================================
# FORESIGHT DOMAIN
# =============================================================================

class ForesightException(SovereignException):
    """Base for foresight engine errors."""
    pass


class PredictionFailedException(ForesightException):
    """Time-series prediction could not be computed."""
    pass


# =============================================================================
# LEGACY VAULT DOMAIN
# =============================================================================

class LegacyVaultException(SovereignException):
    """Base for transgenerational pattern engine / Legacy Vault errors."""
    pass


class ConsentWithdrawnException(LegacyVaultException):
    """A family member has withdrawn consent; data must be excluded."""

    def __init__(self, user_id: Optional[int] = None, family_id: Optional[int] = None, **kwargs):
        super().__init__(
            message=f"Consent withdrawn by user {user_id} in family {family_id}",
            details={"user_id": user_id, "family_id": family_id, **kwargs},
        )
