"""
HIVE DEFENSE PROTOCOL — Recursive Containment (Phase 8C, Third Cord)
Nested containment shells with independent escape probabilities.

When an attacker breaches a containment boundary, they do not reach
freedom — they enter the next containment shell.  Minimum 3 shells
deep, each with independent infrastructure, independent escape
probability, and independent monitoring.

Shell Architecture
------------------
* Shell 0 (outermost) — the mirror dimension itself.  Attackers enter
  here when the Coherence Gate redirects non-verified traffic.
* Shell 1 — secondary containment, activated when an entity attempts to
  "escape" Shell 0.  Features different synthetic data, different timing
  fingerprints, and different tripwires.
* Shell 2 — tertiary containment.  Indistinguishable from Shell 1 to the
  attacker, but with unique network topology fingerprints (see
  :mod:`network_topology_fingerprint`) that prove the entity is still
  contained.
* Shell N — additional shells can be created dynamically.

Each shell is an isolated environment.  Counter-intelligence measures
(Ghost Swarm, Penetrators) can defeat Ghosts but cannot escape the
shell infrastructure itself — it's a property of the routing layer.

Escape Model
-----------
Each shell has an independent probability P_escape(shell_n).  An entity
that "escapes" shell N is immediately captured by shell N+1.  The
probability of reaching the real system = ∏(P_escape(i)) for all i,
which converges rapidly toward zero.

Patent-Pending — Claim 49
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

from app.models.hive_defense import DefconLevel, ForensicRecord

logger = logging.getLogger("hive.recursive_containment")


# =============================================================================
# CONSTANTS
# =============================================================================

# Minimum number of containment shells
MIN_SHELLS = 3

# Default per-shell escape probability (attacker's chance of escaping one shell)
# Actual value doesn't matter to security — escaping only enters the next shell.
DEFAULT_ESCAPE_PROBABILITY = 0.15

# Maximum shells that can exist simultaneously
MAX_SHELLS = 12


# =============================================================================
# DATA CLASSES
# =============================================================================

class ShellStatus(str, Enum):
    """Lifecycle state of a containment shell."""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    BREACHED = "breached"      # An entity escaped this shell (entered next)
    DECOMMISSIONED = "decommissioned"


@dataclass
class ContainmentShell:
    """
    A single containment shell in the recursive stack.

    Each shell is an independent containment environment with its own
    synthetic data seed, monitoring infrastructure, and escape probability.

    Attributes
    ----------
    shell_id : UUID
        Unique identifier for this shell.
    depth : int
        Shell depth (0 = outermost, N = innermost).
    parent_shell_id : UUID or None
        The shell that contains this one (None for depth 0).
    status : ShellStatus
        Current lifecycle state.
    escape_probability : float
        Independent probability of an entity escaping this shell.
    synthetic_seed : str
        Unique seed for generating this shell's synthetic data.
    entities_contained : set[str]
        Entity IDs currently held in this shell.
    escape_attempts : int
        Number of escape attempts observed.
    successful_escapes : int
        Number of entities that escaped (to the next shell).
    created_at : datetime
        When this shell was instantiated.
    fingerprint_salt : bytes
        Unique salt for this shell's network topology fingerprint.
    """
    shell_id: UUID = field(default_factory=uuid4)
    depth: int = 0
    parent_shell_id: Optional[UUID] = None
    status: ShellStatus = ShellStatus.INITIALIZING
    escape_probability: float = DEFAULT_ESCAPE_PROBABILITY
    synthetic_seed: str = ""
    entities_contained: Set[str] = field(default_factory=set)
    escape_attempts: int = 0
    successful_escapes: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    fingerprint_salt: bytes = field(default_factory=lambda: os.urandom(32))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize shell state for reporting."""
        return {
            "shell_id": str(self.shell_id),
            "depth": self.depth,
            "parent_shell_id": str(self.parent_shell_id) if self.parent_shell_id else None,
            "status": self.status.value,
            "escape_probability": self.escape_probability,
            "entities_contained": len(self.entities_contained),
            "escape_attempts": self.escape_attempts,
            "successful_escapes": self.successful_escapes,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class EscapeAttemptResult:
    """
    Result of an entity's escape attempt from a shell.

    Attributes
    ----------
    entity_id : str
        The entity that attempted escape.
    source_shell_id : UUID
        The shell they attempted to escape from.
    target_shell_id : UUID or None
        The shell they were captured by (None if escape failed).
    escaped : bool
        Whether the entity moved to the next shell.
    new_depth : int
        Entity's depth after the attempt.
    timestamp : datetime
        When the attempt was processed.
    """
    entity_id: str = ""
    source_shell_id: UUID = field(default_factory=uuid4)
    target_shell_id: Optional[UUID] = None
    escaped: bool = False
    new_depth: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# RECURSIVE CONTAINMENT ENGINE
# =============================================================================

class RecursiveContainment:
    """
    Nested containment shell manager.

    Creates and manages a stack of independent containment environments.
    Entities that "escape" one shell are immediately captured by the next,
    each with independent infrastructure and monitoring.

    Parameters
    ----------
    min_shells : int
        Minimum number of shells to maintain (default 3).
    default_escape_probability : float
        Per-shell escape probability (default 0.15).

    Usage
    -----
    ::

        containment = RecursiveContainment()
        await containment.initialize()

        # Place entity in outermost shell
        await containment.contain_entity("attacker-42")

        # Check depth
        depth = await containment.get_shell_depth("attacker-42")

        # Process escape attempt
        result = await containment.process_escape_attempt("attacker-42", shell_id)
    """

    def __init__(
        self,
        *,
        min_shells: int = MIN_SHELLS,
        default_escape_probability: float = DEFAULT_ESCAPE_PROBABILITY,
    ) -> None:
        self._min_shells = max(min_shells, MIN_SHELLS)
        self._default_escape_prob = default_escape_probability

        # Shell storage: depth → ContainmentShell
        self._shells_by_depth: Dict[int, ContainmentShell] = {}
        # Shell lookup: shell_id → ContainmentShell
        self._shells_by_id: Dict[UUID, ContainmentShell] = {}
        # Entity tracking: entity_id → current shell depth
        self._entity_depth: Dict[str, int] = {}

        # Forensic event log
        self._event_log: List[Dict[str, Any]] = []

        # Concurrency control
        self._lock = asyncio.Lock()

        # Initialized flag
        self._initialized = False

        logger.info(
            "RecursiveContainment created — min_shells=%d, escape_prob=%.2f",
            self._min_shells,
            self._default_escape_prob,
        )

    # --------------------------------------------------------------------- #
    # INITIALIZATION
    # --------------------------------------------------------------------- #

    async def initialize(self) -> List[ContainmentShell]:
        """
        Initialize the minimum shell stack.

        Creates ``min_shells`` nested containment environments, each with
        independent infrastructure parameters.

        Returns
        -------
        list[ContainmentShell]
            The initialized shell stack, ordered by depth.
        """
        async with self._lock:
            if self._initialized:
                logger.warning("RecursiveContainment already initialized.")
                return [
                    self._shells_by_depth[d]
                    for d in sorted(self._shells_by_depth.keys())
                ]

            parent_id: Optional[UUID] = None
            shells: List[ContainmentShell] = []

            for depth in range(self._min_shells):
                shell = await self._create_shell_internal(
                    depth=depth,
                    parent_shell_id=parent_id,
                )
                shells.append(shell)
                parent_id = shell.shell_id

            self._initialized = True

        logger.info(
            "RecursiveContainment initialized with %d shells.",
            len(shells),
        )
        return shells

    # --------------------------------------------------------------------- #
    # SHELL CREATION
    # --------------------------------------------------------------------- #

    async def create_shell(
        self,
        parent_shell_id: Optional[UUID] = None,
    ) -> ContainmentShell:
        """
        Create a new containment shell.

        If ``parent_shell_id`` is provided, the new shell is nested inside
        the parent.  If None, it is appended as the deepest shell.

        Parameters
        ----------
        parent_shell_id : UUID or None
            Parent shell to nest inside.  If None, the new shell becomes
            the innermost shell.

        Returns
        -------
        ContainmentShell
            The newly created shell.

        Raises
        ------
        ValueError
            If the maximum shell count is reached.
        """
        async with self._lock:
            current_count = len(self._shells_by_depth)
            if current_count >= MAX_SHELLS:
                raise ValueError(
                    f"Maximum shell count ({MAX_SHELLS}) reached — "
                    "cannot create more shells."
                )

            if parent_shell_id is not None:
                parent = self._shells_by_id.get(parent_shell_id)
                if parent is None:
                    raise ValueError(
                        f"Parent shell {parent_shell_id} not found."
                    )
                depth = parent.depth + 1
            else:
                # Append as deepest shell
                depth = max(self._shells_by_depth.keys(), default=-1) + 1

            shell = await self._create_shell_internal(
                depth=depth,
                parent_shell_id=parent_shell_id,
            )

        return shell

    async def _create_shell_internal(
        self,
        depth: int,
        parent_shell_id: Optional[UUID],
    ) -> ContainmentShell:
        """
        Internal shell creation (caller must hold the lock).

        Generates unique synthetic data seed and fingerprint salt for
        infrastructure isolation.

        Parameters
        ----------
        depth : int
            Shell depth level.
        parent_shell_id : UUID or None
            Parent shell ID.

        Returns
        -------
        ContainmentShell
        """
        # Generate unique synthetic seed from cryptographic randomness
        seed_material = os.urandom(32)
        synthetic_seed = hashlib.sha256(
            seed_material + struct.pack("!I", depth)
        ).hexdigest()

        # Decrease escape probability with depth (deeper = harder to escape)
        escape_prob = self._default_escape_prob * (0.8 ** depth)

        shell = ContainmentShell(
            depth=depth,
            parent_shell_id=parent_shell_id,
            status=ShellStatus.ACTIVE,
            escape_probability=escape_prob,
            synthetic_seed=synthetic_seed,
            fingerprint_salt=os.urandom(32),
        )

        self._shells_by_depth[depth] = shell
        self._shells_by_id[shell.shell_id] = shell

        event = {
            "event": "hive.containment.shell_created",
            "shell_id": str(shell.shell_id),
            "depth": depth,
            "parent": str(parent_shell_id) if parent_shell_id else None,
            "escape_probability": round(escape_prob, 4),
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._event_log.append(event)

        logger.info(
            "Shell created — id=%s, depth=%d, escape_prob=%.4f",
            shell.shell_id,
            depth,
            escape_prob,
        )

        return shell

    # --------------------------------------------------------------------- #
    # ENTITY CONTAINMENT
    # --------------------------------------------------------------------- #

    async def contain_entity(
        self,
        entity_id: str,
        target_depth: int = 0,
    ) -> ContainmentShell:
        """
        Place an entity into a containment shell.

        By default, entities enter Shell 0 (outermost).  A specific depth
        can be provided for direct placement.

        Parameters
        ----------
        entity_id : str
            The entity to contain.
        target_depth : int
            Shell depth to place the entity in (default 0).

        Returns
        -------
        ContainmentShell
            The shell the entity was placed in.

        Raises
        ------
        ValueError
            If the target depth doesn't exist.
        """
        async with self._lock:
            shell = self._shells_by_depth.get(target_depth)
            if shell is None:
                raise ValueError(
                    f"No shell at depth {target_depth}. "
                    f"Available depths: {sorted(self._shells_by_depth.keys())}"
                )

            shell.entities_contained.add(entity_id)
            self._entity_depth[entity_id] = target_depth

        logger.info(
            "Entity '%s' contained in shell depth=%d (id=%s)",
            entity_id,
            target_depth,
            shell.shell_id,
        )

        self._event_log.append({
            "event": "hive.containment.entity_placed",
            "entity_id": entity_id,
            "shell_id": str(shell.shell_id),
            "depth": target_depth,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return shell

    # --------------------------------------------------------------------- #
    # SHELL DEPTH QUERY
    # --------------------------------------------------------------------- #

    async def get_shell_depth(self, entity_id: str) -> int:
        """
        Return the current containment depth of an entity.

        Parameters
        ----------
        entity_id : str
            The entity to query.

        Returns
        -------
        int
            Shell depth (0 = outermost).  Returns -1 if entity is not
            contained.
        """
        async with self._lock:
            return self._entity_depth.get(entity_id, -1)

    async def get_entity_shell(self, entity_id: str) -> Optional[ContainmentShell]:
        """
        Return the containment shell an entity is currently in.

        Parameters
        ----------
        entity_id : str
            The entity to query.

        Returns
        -------
        ContainmentShell or None
            The current shell, or None if entity is not contained.
        """
        async with self._lock:
            depth = self._entity_depth.get(entity_id)
            if depth is None:
                return None
            return self._shells_by_depth.get(depth)

    # --------------------------------------------------------------------- #
    # ESCAPE ATTEMPT PROCESSING
    # --------------------------------------------------------------------- #

    async def process_escape_attempt(
        self,
        entity_id: str,
        shell_id: UUID,
    ) -> EscapeAttemptResult:
        """
        Process an entity's attempt to escape a containment shell.

        The escape attempt is evaluated against the shell's independent
        escape probability.  Regardless of outcome:
        - If the entity "escapes", it is captured by the next deeper shell.
        - If the entity fails to escape, it remains in the current shell.

        The entity NEVER reaches the real system — escaping only moves
        them deeper into containment.

        Parameters
        ----------
        entity_id : str
            The entity attempting escape.
        shell_id : UUID
            The shell the entity is attempting to escape from.

        Returns
        -------
        EscapeAttemptResult
            Details of the escape attempt and its outcome.

        Raises
        ------
        ValueError
            If the entity is not in the specified shell.
        """
        async with self._lock:
            shell = self._shells_by_id.get(shell_id)
            if shell is None:
                raise ValueError(f"Shell {shell_id} not found.")

            if entity_id not in shell.entities_contained:
                raise ValueError(
                    f"Entity '{entity_id}' is not in shell {shell_id} "
                    f"(depth {shell.depth})."
                )

            shell.escape_attempts += 1

            # Evaluate escape using cryptographic randomness
            escaped = self._evaluate_escape(shell.escape_probability)

            result = EscapeAttemptResult(
                entity_id=entity_id,
                source_shell_id=shell_id,
                escaped=escaped,
                new_depth=shell.depth,
            )

            if escaped:
                shell.successful_escapes += 1
                shell.entities_contained.discard(entity_id)

                # Ensure next shell exists
                next_depth = shell.depth + 1
                if next_depth not in self._shells_by_depth:
                    # Dynamically create the next shell
                    await self._create_shell_internal(
                        depth=next_depth,
                        parent_shell_id=shell_id,
                    )

                next_shell = self._shells_by_depth[next_depth]
                next_shell.entities_contained.add(entity_id)
                self._entity_depth[entity_id] = next_depth
                result.target_shell_id = next_shell.shell_id
                result.new_depth = next_depth

                shell.status = ShellStatus.BREACHED

                self._event_log.append({
                    "event": "hive.containment.shell_escaped",
                    "entity_id": entity_id,
                    "from_shell": str(shell_id),
                    "from_depth": shell.depth,
                    "to_shell": str(next_shell.shell_id),
                    "to_depth": next_depth,
                    "timestamp": datetime.utcnow().isoformat(),
                })

                logger.warning(
                    "Entity '%s' escaped shell depth=%d → captured by depth=%d",
                    entity_id,
                    shell.depth,
                    next_depth,
                )
            else:
                self._event_log.append({
                    "event": "hive.containment.escape_failed",
                    "entity_id": entity_id,
                    "shell_id": str(shell_id),
                    "depth": shell.depth,
                    "timestamp": datetime.utcnow().isoformat(),
                })

                logger.info(
                    "Entity '%s' failed to escape shell depth=%d "
                    "(attempt #%d)",
                    entity_id,
                    shell.depth,
                    shell.escape_attempts,
                )

        return result

    @staticmethod
    def _evaluate_escape(probability: float) -> bool:
        """
        Evaluate whether an escape attempt succeeds using cryptographic
        randomness.

        Parameters
        ----------
        probability : float
            The independent escape probability for this shell.

        Returns
        -------
        bool
            True if the entity escapes (moves to next shell).
        """
        random_bytes = os.urandom(8)
        value = struct.unpack("Q", random_bytes)[0]
        threshold = probability * (2**64)
        return value < threshold

    # --------------------------------------------------------------------- #
    # CUMULATIVE ESCAPE PROBABILITY
    # --------------------------------------------------------------------- #

    async def get_cumulative_escape_probability(self) -> float:
        """
        Calculate the probability of an entity escaping ALL shells to
        reach the real system.

        This is the product of all individual shell escape probabilities,
        which converges rapidly toward zero.

        Returns
        -------
        float
            Combined probability (typically astronomically small).
        """
        async with self._lock:
            probability = 1.0
            for depth in sorted(self._shells_by_depth.keys()):
                shell = self._shells_by_depth[depth]
                probability *= shell.escape_probability
            return probability

    # --------------------------------------------------------------------- #
    # SHELL INTROSPECTION
    # --------------------------------------------------------------------- #

    async def get_shell(self, shell_id: UUID) -> Optional[ContainmentShell]:
        """Return a shell by ID."""
        async with self._lock:
            return self._shells_by_id.get(shell_id)

    async def get_shell_at_depth(self, depth: int) -> Optional[ContainmentShell]:
        """Return the shell at a specific depth."""
        async with self._lock:
            return self._shells_by_depth.get(depth)

    async def get_all_shells(self) -> List[ContainmentShell]:
        """Return all shells ordered by depth."""
        async with self._lock:
            return [
                self._shells_by_depth[d]
                for d in sorted(self._shells_by_depth.keys())
            ]

    async def get_contained_entities(self) -> Dict[str, int]:
        """
        Return all contained entities and their current depths.

        Returns
        -------
        dict[str, int]
            entity_id → current depth.
        """
        async with self._lock:
            return dict(self._entity_depth)

    async def get_event_log(
        self,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return the most recent forensic events."""
        return self._event_log[-limit:]

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of the containment infrastructure."""
        total_entities = sum(
            len(s.entities_contained) for s in self._shells_by_depth.values()
        )
        total_escapes = sum(
            s.successful_escapes for s in self._shells_by_depth.values()
        )
        total_attempts = sum(
            s.escape_attempts for s in self._shells_by_depth.values()
        )
        return {
            "shell_count": len(self._shells_by_depth),
            "total_entities_contained": total_entities,
            "total_escape_attempts": total_attempts,
            "total_successful_escapes": total_escapes,
            "shells": [
                s.to_dict() for s in sorted(
                    self._shells_by_depth.values(),
                    key=lambda x: x.depth,
                )
            ],
            "initialized": self._initialized,
        }

    def __repr__(self) -> str:
        return (
            f"<RecursiveContainment shells={len(self._shells_by_depth)} "
            f"entities={len(self._entity_depth)} "
            f"initialized={self._initialized}>"
        )
