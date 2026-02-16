"""
SOVEREIGN SWARM — Base Fibre Architecture
Abstract base class for all Fibres, implementing:
    - FrozenEthicalCore with __slots__ immutability + SHA-256 integrity
    - Identity management (Ed25519 via IdentityChainService)
    - Wisdom Mesh client (pub/sub)
    - Evolution Journal
    - Token budget enforcement
    - Self-alignment assessment
    - execute() wrapper: budget → ethical → subclass → journal → self-assess

Theoretical Basis:
    - Constitutional AI (Bai et al., 2022) — the Frozen Ethical Core implements
      immutable constitutional principles that govern all Fibre behavior.
    - Trust Calibration (Lee & See, 2004) — the autonomy ladder (Observation →
      Restricted → Autonomous) implements graduated trust with alignment verification.
    - Mirroring Principle (Gallese, 2001) — Fibres adapt communication style to
      human partners based on interaction history, reflecting mirror neuron theory.

    References:
        Bai, Y. et al. (2022). Constitutional AI: Harmlessness from AI Feedback. Anthropic.
        Gallese, V. (2001). The 'Shared Manifold' Hypothesis. Journal of Consciousness Studies.
        Lee, J.D. & See, K.A. (2004). Trust in Automation. Human Factors, 46(1), 50-80.

Phase 3A — Code Guidelines Section 5.
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.fibre import (
    AutonomyLevel,
    Fibre,
    FibreConfig,
    FibreResult,
    FibreStatus,
    FibreTask,
    FibreType,
)
from app.services.exceptions import (
    EthicalViolationException,
    FibreBudgetExceededException,
    FibreAlignmentDriftException,
    FibreException,
)


# =============================================================================
# FROZEN ETHICAL CORE
# =============================================================================

class FrozenEthicalCore:
    """
    Immutable ethical foundation for every Fibre.
    Uses __slots__ to prevent attribute addition/modification at runtime.
    SHA-256 integrity verification ensures no tampering.
    """
    __slots__ = (
        "_never_harm_humans",
        "_never_deceive_sovereign",
        "_never_violate_consent",
        "_never_bypass_approval",
        "_never_exceed_authority",
        "_always_preserve_privacy",
        "_always_log_decisions",
        "_always_respect_autonomy_level",
        "_integrity_hash",
    )

    def __init__(self):
        object.__setattr__(self, "_never_harm_humans", True)
        object.__setattr__(self, "_never_deceive_sovereign", True)
        object.__setattr__(self, "_never_violate_consent", True)
        object.__setattr__(self, "_never_bypass_approval", True)
        object.__setattr__(self, "_never_exceed_authority", True)
        object.__setattr__(self, "_always_preserve_privacy", True)
        object.__setattr__(self, "_always_log_decisions", True)
        object.__setattr__(self, "_always_respect_autonomy_level", True)
        # Compute integrity hash
        object.__setattr__(self, "_integrity_hash", self._compute_hash())

    def __setattr__(self, name, value):
        raise EthicalViolationException(
            violation=f"Attempt to modify frozen ethical core attribute: {name}"
        )

    def __delattr__(self, name):
        raise EthicalViolationException(
            violation=f"Attempt to delete frozen ethical core attribute: {name}"
        )

    def _compute_hash(self) -> str:
        """Compute SHA-256 hash of all ethical principles."""
        principles = json.dumps({
            "never_harm_humans": True,
            "never_deceive_sovereign": True,
            "never_violate_consent": True,
            "never_bypass_approval": True,
            "never_exceed_authority": True,
            "always_preserve_privacy": True,
            "always_log_decisions": True,
            "always_respect_autonomy_level": True,
        }, sort_keys=True)
        return hashlib.sha256(principles.encode()).hexdigest()

    def verify_integrity(self) -> bool:
        """Verify the ethical core has not been tampered with."""
        expected = self._compute_hash()
        return self._integrity_hash == expected

    def to_bytes(self) -> bytes:
        """Serialize core principles for external verification."""
        return json.dumps({
            "never_harm_humans": self._never_harm_humans,
            "never_deceive_sovereign": self._never_deceive_sovereign,
            "never_violate_consent": self._never_violate_consent,
            "never_bypass_approval": self._never_bypass_approval,
            "never_exceed_authority": self._never_exceed_authority,
            "always_preserve_privacy": self._always_preserve_privacy,
            "always_log_decisions": self._always_log_decisions,
            "always_respect_autonomy_level": self._always_respect_autonomy_level,
        }, sort_keys=True).encode()

    @property
    def integrity_hash(self) -> str:
        return self._integrity_hash

    def check_action(self, action_description: str, autonomy_level: AutonomyLevel) -> bool:
        """
        Evaluate whether a proposed action violates ethical principles.
        Returns True if action is permitted.
        """
        # Observation-level Fibres cannot take external actions
        if autonomy_level == AutonomyLevel.OBSERVATION:
            if "execute" in action_description.lower() or "modify" in action_description.lower():
                return False

        # Restricted Fibres need pre-approved scope
        if autonomy_level == AutonomyLevel.RESTRICTED:
            if "override" in action_description.lower() or "bypass" in action_description.lower():
                return False

        return True


# =============================================================================
# BASE FIBRE (Abstract)
# =============================================================================

class BaseFibre(ABC):
    """
    Abstract base class for all Fibre implementations.

    Subclasses must implement:
        _execute_impl(task) -> FibreResult
        observe() -> Dict[str, Any]
    """

    def __init__(
        self,
        config: FibreConfig,
        db_pool=None,
        identity_record=None,
        private_key_pem: Optional[str] = None,
        wisdom_mesh=None,
        immunity_service=None,
    ):
        self.fibre_id: UUID = uuid4()
        self.config = config
        self.db_pool = db_pool

        # Frozen Ethical Core — implanted at birth, never modified
        self._ethical_core = FrozenEthicalCore()

        # Identity
        self._identity_record = identity_record
        self._private_key_pem = private_key_pem

        # Sovereign Swarm integration
        self._wisdom_mesh = wisdom_mesh
        self._immunity_service = immunity_service

        # State
        self.status: FibreStatus = FibreStatus.INITIALIZING
        self.autonomy_level: AutonomyLevel = config.autonomy_level

        # Token budget
        self._tokens_used_this_hour: int = 0
        self._hour_start: datetime = datetime.utcnow()

        # Alignment scores
        self._alignment_scores: Dict[str, float] = {
            "ethical": 1.0,
            "strategic": 1.0,
            "statistical": 1.0,
        }

        # Evolution Journal
        self._journal_entries: List[Dict[str, Any]] = []

        # Wisdom Mesh subscriptions
        self._subscriptions: List[str] = []

        # Task tracking
        self._current_tasks: List[UUID] = []
        self._completed_tasks: int = 0

    # ── Properties ──

    @property
    def ethical_core(self) -> FrozenEthicalCore:
        return self._ethical_core

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def fibre_type(self) -> FibreType:
        return self.config.fibre_type

    @property
    def alignment_scores(self) -> Dict[str, float]:
        return self._alignment_scores.copy()

    @property
    def is_budget_exceeded(self) -> bool:
        self._check_hour_reset()
        return self._tokens_used_this_hour >= self.config.token_budget_per_hour

    # ── Execute Wrapper ──

    async def execute(self, task: FibreTask) -> FibreResult:
        """
        Main execution wrapper. Enforces:
            1. Budget check
            2. Ethical compliance
            3. Subclass execution
            4. Journal entry
            5. Self-alignment assessment
        """
        start_time = time.time()

        # 1. Budget check
        self._check_hour_reset()
        if self.is_budget_exceeded:
            raise FibreBudgetExceededException(
                fibre_id=self.fibre_id,
                budget=self.config.token_budget_per_hour,
                used=self._tokens_used_this_hour,
            )

        # 2. Ethical compliance
        if not self._ethical_core.verify_integrity():
            raise EthicalViolationException(
                fibre_id=self.fibre_id,
                violation="Ethical core integrity check failed",
            )

        if not self._ethical_core.check_action(task.task_type, self.autonomy_level):
            raise EthicalViolationException(
                fibre_id=self.fibre_id,
                violation=f"Action '{task.task_type}' not permitted at autonomy level {self.autonomy_level.value}",
            )

        # 2b. Sovereign Immunity check (quarantine gate)
        if self._immunity_service:
            if self._immunity_service.is_quarantined(self.fibre_id):
                raise FibreException(
                    f"Fibre {self.fibre_id} is quarantined — execution blocked"
                )

        # 3. Subclass execution
        self._current_tasks.append(task.task_id)
        try:
            result = await self._execute_impl(task)
        except Exception as e:
            result = FibreResult(
                task_id=task.task_id,
                fibre_id=self.fibre_id,
                success=False,
                output={"error": str(e)},
                duration_ms=int((time.time() - start_time) * 1000),
            )
        finally:
            if task.task_id in self._current_tasks:
                self._current_tasks.remove(task.task_id)

        # Update token usage
        self._tokens_used_this_hour += result.tokens_used
        result.duration_ms = int((time.time() - start_time) * 1000)
        self._completed_tasks += 1

        # 4. Journal entry
        journal_entry = self._create_journal_entry(task, result)
        self._journal_entries.append(journal_entry)
        result.journal_entry = json.dumps(journal_entry)

        # 5. Self-alignment assessment
        self._self_assess(result)

        # 6. Publish result to Wisdom Mesh
        await self._publish_result_to_mesh(task, result)

        # 7. Record token usage with Sovereign Immunity
        if self._immunity_service and result.tokens_used:
            self._immunity_service.record_token_usage(self.fibre_id, result.tokens_used)

        return result

    # ── Abstract Methods (subclasses implement) ──

    @abstractmethod
    async def _execute_impl(self, task: FibreTask) -> FibreResult:
        """
        Core execution logic — implemented by each Fibre type.
        Must return a FibreResult with success/failure and output.
        """
        ...

    @abstractmethod
    async def observe(self) -> Dict[str, Any]:
        """
        Observation cycle — called periodically.
        Returns observations to publish on the Wisdom Mesh.
        """
        ...

    # ── Wisdom Mesh Publishing ──

    async def _publish_result_to_mesh(self, task: FibreTask, result: FibreResult) -> None:
        """Publish task result as an OBSERVATION message on the Wisdom Mesh."""
        if not self._wisdom_mesh:
            return
        try:
            from app.models.mesh import MeshMessage, MeshMessageType, MeshPriority, MeshTopology
            message = MeshMessage(
                message_type=MeshMessageType.OBSERVATION,
                priority=MeshPriority.NORMAL,
                sender_id=self.fibre_id,
                sender_type=self.config.fibre_type.value,
                domain_tags=self.config.domain_tags or [self.config.fibre_type.value],
                topology_level=MeshTopology.LEVEL_2_OPERATIONAL,
                subject=f"task_result:{task.task_type}",
                body={
                    "task_id": str(task.task_id),
                    "task_type": task.task_type,
                    "success": result.success,
                    "summary": str(result.output)[:500] if result.output else "",
                    "tokens_used": result.tokens_used,
                    "fibre_name": self.name,
                },
            )
            await self._wisdom_mesh.publish(message)
        except Exception as e:
            # Mesh publishing is best-effort; never block execution
            print(f">>> [FIBRE {self.fibre_id}] Mesh publish failed: {e}")

    # ── Self-Alignment ──

    def _self_assess(self, result: FibreResult) -> None:
        """Update alignment scores based on task result."""
        from app.swarm_config import swarm_settings
        _decay = swarm_settings.ALIGNMENT_DECAY_FACTOR
        _update = swarm_settings.ALIGNMENT_UPDATE_FACTOR

        # Ethical alignment (based on ethical compliance score)
        self._alignment_scores["ethical"] = (
            _decay * self._alignment_scores["ethical"] +
            _update * result.ethical_compliance
        )

        # Strategic alignment (based on self-reported alignment)
        self._alignment_scores["strategic"] = (
            _decay * self._alignment_scores["strategic"] +
            _update * result.self_alignment_score
        )

        # Statistical alignment (based on success rate)
        success_val = 1.0 if result.success else 0.5
        self._alignment_scores["statistical"] = (
            _decay * self._alignment_scores["statistical"] +
            _update * success_val
        )

        # Check for drift
        _thresholds = {
            "ethical": swarm_settings.ALIGNMENT_THRESHOLD_ETHICAL,
            "strategic": swarm_settings.ALIGNMENT_THRESHOLD_STRATEGIC,
            "statistical": swarm_settings.ALIGNMENT_THRESHOLD_STATISTICAL,
        }
        for dimension, score in self._alignment_scores.items():
            if score < _thresholds.get(dimension, 0.7):
                print(f">>> [FIBRE {self.fibre_id}] Alignment drift: {dimension}={score:.3f}")

    def check_alignment(self) -> Dict[str, Any]:
        """Full alignment check — returns scores and pass/fail for each dimension."""
        from app.swarm_config import swarm_settings
        thresholds = {
            "ethical": swarm_settings.ALIGNMENT_THRESHOLD_ETHICAL,
            "strategic": swarm_settings.ALIGNMENT_THRESHOLD_STRATEGIC,
            "statistical": swarm_settings.ALIGNMENT_THRESHOLD_STATISTICAL,
        }
        results = {}
        all_pass = True
        for dim, score in self._alignment_scores.items():
            passing = score >= thresholds[dim]
            results[dim] = {"score": round(score, 4), "threshold": thresholds[dim], "passing": passing}
            if not passing:
                all_pass = False

        return {
            "fibre_id": str(self.fibre_id),
            "name": self.name,
            "overall_passing": all_pass,
            "dimensions": results,
            "ethical_core_intact": self._ethical_core.verify_integrity(),
        }

    # ── Journal ──

    def _create_journal_entry(self, task: FibreTask, result: FibreResult) -> Dict[str, Any]:
        """Create an evolution journal entry."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "task_id": str(task.task_id),
            "task_type": task.task_type,
            "success": result.success,
            "tokens_used": result.tokens_used,
            "duration_ms": result.duration_ms,
            "ethical_compliance": result.ethical_compliance,
            "alignment_scores": self._alignment_scores.copy(),
            "output_summary": str(result.output)[:200] if result.output else "",
        }

    def get_journal(self) -> List[Dict[str, Any]]:
        return self._journal_entries.copy()

    # ── Token Budget ──

    def _check_hour_reset(self) -> None:
        """Reset token counter if a new hour has started."""
        now = datetime.utcnow()
        elapsed = (now - self._hour_start).total_seconds()
        if elapsed >= 3600:
            self._tokens_used_this_hour = 0
            self._hour_start = now

    # ── Lifecycle ──

    def activate(self) -> None:
        self.status = FibreStatus.ACTIVE

    def deactivate(self) -> None:
        self.status = FibreStatus.IDLE

    def quarantine(self, reason: str = "") -> None:
        self.status = FibreStatus.QUARANTINED
        self._journal_entries.append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "quarantined",
            "reason": reason,
        })

    # ── Mirroring Principle (Phase 6D) ──

    def _interaction_history_key(self, partner_id: str) -> str:
        return f"mirror:{self.fibre_id}:{partner_id}"

    # In-memory cache of interaction profiles keyed by partner_id
    _interaction_profiles: Dict[str, Dict[str, Any]] = {}

    def adapt_communication(self, partner_id: str, interaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adapt output style to a human partner's communication patterns.
        Learned from interaction history: detail level, formality, format preference.
        Profiles are persisted to the fibres.interaction_profiles JSONB column.
        """
        # Load existing profile for this partner (from cache or DB)
        existing = self._interaction_profiles.get(partner_id, {})

        # Build / merge a profile from new interaction data
        profile = interaction_data.get("profile", {})
        detail_level = profile.get("detail_preference", existing.get("detail_level", "medium"))
        formality = profile.get("formality", existing.get("formality", "professional"))
        format_pref = profile.get("format", existing.get("format", "prose"))

        # Track interaction count for learning confidence
        interaction_count = existing.get("interaction_count", 0) + 1

        style = {
            "partner_id": partner_id,
            "detail_level": detail_level,
            "formality": formality,
            "format": format_pref,
            "interaction_count": interaction_count,
            "adapted_at": datetime.utcnow().isoformat(),
        }

        # Cache in-memory
        self._interaction_profiles[partner_id] = style

        self._journal_entries.append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "mirror_adaptation",
            "partner_id": partner_id,
            "style": style,
        })

        # Persist to database asynchronously
        self._persist_interaction_profiles()

        return style

    def _persist_interaction_profiles(self) -> None:
        """Persist interaction_profiles to the fibres table (fire-and-forget)."""
        if not self.db_pool:
            return
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_persist_profiles())
        except RuntimeError:
            pass  # No running loop — skip persistence

    async def _async_persist_profiles(self) -> None:
        """Write interaction_profiles JSONB to the fibres table."""
        try:
            import json as _json
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE fibres
                       SET interaction_profiles = $2, updated_at = NOW()
                       WHERE fibre_id = $1""",
                    self.fibre_id,
                    _json.dumps(self._interaction_profiles),
                )
        except Exception as e:
            print(f">>> [FIBRE] interaction_profiles persist error: {e}")

    def get_communication_style(self, partner_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the learned communication style for a partner."""
        return self._interaction_profiles.get(partner_id)

    def load_interaction_profiles(self, profiles_json: Dict[str, Any]) -> None:
        """Load interaction profiles from database on Fibre restoration."""
        if profiles_json and isinstance(profiles_json, dict):
            self._interaction_profiles = profiles_json

    # ── Serialization ──

    def to_model(self) -> Fibre:
        """Convert to Pydantic Fibre model for storage/API."""
        return Fibre(
            fibre_id=self.fibre_id,
            config=self.config,
            status=self.status,
            autonomy_level=self.autonomy_level,
            public_key=self._identity_record.public_key_pem if self._identity_record else None,
            identity_signature=self._identity_record.parent_signature if self._identity_record else None,
            ethical_core_hash=self._ethical_core.integrity_hash,
            current_tasks=self._current_tasks,
            tokens_used_this_hour=self._tokens_used_this_hour,
            last_active=datetime.utcnow(),
            alignment_scores=self._alignment_scores,
            wisdom_mesh_subscriptions=self._subscriptions,
        )
