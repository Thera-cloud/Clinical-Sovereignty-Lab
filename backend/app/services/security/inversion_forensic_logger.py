"""
HIVE DEFENSE PROTOCOL v3.1 — Inversion Forensic Logger (Phase 8D)
Specialized forensic capture for triangular mirror inversion spaces.

While the main ``ForensicLogger`` maintains the global immutable evidence
chain, this specialized logger focuses exclusively on interactions within
inverted spaces — capturing every attacker interaction, response, wall
reflection, and tripwire activation inside triangular mirror spaces.

Key Capabilities:
    - **Per-space logging** — each InvertedSpace has its own interaction
      log with full wall-level detail.
    - **Behavioral profiling** — builds attacker behavioral models from
      observed triangle activity patterns.
    - **Space reports** — generates comprehensive forensic reports for
      individual inversion spaces.
    - **Chain integration** — forwards critical events to the global
      ForensicLogger for hash-chain immutability.

Patent-Pending — Claims 50-51 (sub-component)
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

logger = logging.getLogger("hive.inversion_forensic")


# =============================================================================
# INTERACTION LOG ENTRY
# =============================================================================

class InversionLogEntry:
    """
    A single forensic log entry for an interaction inside an inverted space.

    Attributes
    ----------
    entry_id : str
        Unique identifier for this entry.
    space_id : UUID
        The inverted space this interaction occurred in.
    timestamp : datetime
        When the interaction was logged.
    interaction : dict
        The attacker's raw interaction payload.
    response : dict
        The blended response returned to the attacker.
    wall_reflections : dict
        Individual wall outputs (A, B, C) and cross-reflection details.
    chain_hash : str
        SHA-256 hash linking this entry to the previous one in the
        space's local chain.
    """

    __slots__ = (
        "entry_id",
        "space_id",
        "timestamp",
        "interaction",
        "response",
        "wall_reflections",
        "chain_hash",
        "previous_hash",
    )

    def __init__(
        self,
        space_id: UUID,
        interaction: Dict[str, Any],
        response: Dict[str, Any],
        wall_reflections: Dict[str, Any],
        previous_hash: str = "",
    ) -> None:
        self.entry_id: str = uuid4().hex[:16]
        self.space_id: UUID = space_id
        self.timestamp: datetime = datetime.utcnow()
        self.interaction: Dict[str, Any] = interaction
        self.response: Dict[str, Any] = response
        self.wall_reflections: Dict[str, Any] = wall_reflections
        self.previous_hash: str = previous_hash
        self.chain_hash: str = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute the chain hash linking to the previous entry."""
        data = (
            f"{self.entry_id}:{self.space_id}:"
            f"{self.timestamp.isoformat()}:{self.previous_hash}"
        )
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses and persistence."""
        return {
            "entry_id": self.entry_id,
            "space_id": str(self.space_id),
            "timestamp": self.timestamp.isoformat(),
            "interaction": self.interaction,
            "response": self.response,
            "wall_reflections": self.wall_reflections,
            "chain_hash": self.chain_hash[:16],
        }


# =============================================================================
# ATTACKER BEHAVIORAL MODEL
# =============================================================================

class AttackerBehavioralModel:
    """
    Behavioral model built from observed interactions inside a triangle.

    Tracks:
        - Interaction type frequencies
        - Timing patterns (intervals between interactions)
        - Keyword frequencies in payloads
        - Tripwire activation patterns
        - Probe strategies detected
    """

    def __init__(self, space_id: UUID) -> None:
        self.space_id: UUID = space_id
        self.created_at: datetime = datetime.utcnow()
        self.last_updated: datetime = self.created_at

        # Type frequency map
        self.type_frequencies: Dict[str, int] = defaultdict(int)

        # Timing intervals (seconds between consecutive interactions)
        self.timing_intervals: List[float] = []
        self._last_interaction_time: Optional[datetime] = None

        # Keyword extraction
        self.keyword_frequencies: Dict[str, int] = defaultdict(int)

        # Tripwire patterns
        self.tripwire_types_triggered: Dict[str, int] = defaultdict(int)

        # Strategy classification
        self.detected_strategies: List[str] = []

        # Metrics
        self.total_interactions: int = 0

    def update(
        self,
        interaction: Dict[str, Any],
        tripwires: Optional[List[str]] = None,
    ) -> None:
        """Update the model with a new interaction."""
        self.total_interactions += 1
        self.last_updated = datetime.utcnow()

        # Track type frequency
        itype = interaction.get("type", "unknown")
        self.type_frequencies[itype] += 1

        # Track timing
        now = datetime.utcnow()
        if self._last_interaction_time:
            interval = (now - self._last_interaction_time).total_seconds()
            self.timing_intervals.append(interval)
        self._last_interaction_time = now

        # Extract keywords
        for key in interaction:
            self.keyword_frequencies[str(key)] += 1
            value = str(interaction[key]).lower()
            for word in value.split():
                if len(word) > 3:
                    self.keyword_frequencies[word] += 1

        # Track tripwires
        if tripwires:
            for tw in tripwires:
                self.tripwire_types_triggered[tw] += 1

        # Detect strategies
        self._detect_strategies()

    def _detect_strategies(self) -> None:
        """Detect attacker strategies from accumulated patterns."""
        strategies: Set[str] = set()

        # Enumeration strategy — many different types in sequence
        if len(self.type_frequencies) > 5 and self.total_interactions < 30:
            strategies.add("rapid_enumeration")

        # Timing analysis — very consistent intervals
        if len(self.timing_intervals) >= 5:
            mean = sum(self.timing_intervals[-5:]) / 5
            variance = sum(
                (x - mean) ** 2 for x in self.timing_intervals[-5:]
            ) / 5
            if variance < 0.01 and mean > 0:
                strategies.add("automated_probing")

        # Tripwire awareness — stops after tripwire activation
        if (
            sum(self.tripwire_types_triggered.values()) > 0
            and self.total_interactions > 10
            and len(self.timing_intervals) >= 2
            and self.timing_intervals[-1] > self.timing_intervals[-2] * 3
        ):
            strategies.add("tripwire_awareness")

        # Focused probing — heavy repetition of one type
        if self.type_frequencies:
            max_freq = max(self.type_frequencies.values())
            if max_freq > self.total_interactions * 0.6:
                strategies.add("focused_probing")

        self.detected_strategies = sorted(strategies)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the behavioral model."""
        return {
            "space_id": str(self.space_id),
            "total_interactions": self.total_interactions,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "type_frequencies": dict(self.type_frequencies),
            "timing_stats": self._timing_stats(),
            "top_keywords": dict(
                sorted(
                    self.keyword_frequencies.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:20]
            ),
            "tripwire_patterns": dict(self.tripwire_types_triggered),
            "detected_strategies": self.detected_strategies,
        }

    def _timing_stats(self) -> Dict[str, Any]:
        """Compute timing statistics."""
        if not self.timing_intervals:
            return {"count": 0}

        intervals = self.timing_intervals
        return {
            "count": len(intervals),
            "mean_sec": round(sum(intervals) / len(intervals), 3),
            "min_sec": round(min(intervals), 3),
            "max_sec": round(max(intervals), 3),
        }


# =============================================================================
# INVERSION FORENSIC LOGGER
# =============================================================================

class InversionForensicLogger:
    """
    Specialized forensic logger for triangular mirror inversion spaces.

    Maintains per-space interaction chains, builds behavioral models,
    and generates comprehensive forensic reports.

    Parameters
    ----------
    global_forensic_logger : object, optional
        The main ``ForensicLogger`` instance.  Critical events are
        forwarded to the global chain for hash-linked immutability.
    db_pool : object, optional
        asyncpg connection pool for persistence.

    Usage
    -----
    ::

        logger = InversionForensicLogger(
            global_forensic_logger=forensic_logger,
            db_pool=pool,
        )
        await logger.log_interaction(space_id, interaction, response, walls)
        report = await logger.get_space_report(space_id)
        model = logger.build_attacker_model(space_id)
    """

    def __init__(
        self,
        global_forensic_logger=None,
        db_pool=None,
    ) -> None:
        self._global_logger = global_forensic_logger
        self._db_pool = db_pool

        # Per-space interaction chains
        self._space_chains: Dict[UUID, List[InversionLogEntry]] = {}

        # Per-space latest hash (for chain linking)
        self._space_latest_hash: Dict[UUID, str] = {}

        # Per-space behavioral models
        self._behavioral_models: Dict[UUID, AttackerBehavioralModel] = {}

        # Lock for thread-safe appends
        self._lock: asyncio.Lock = asyncio.Lock()

        # Metrics
        self._total_logged: int = 0

        logger.info(">>> [INVERSION_FORENSIC] Logger initialized")

    # ─── Core Logging ────────────────────────────────────────────────────

    async def log_interaction(
        self,
        space_id: UUID,
        interaction: Dict[str, Any],
        response: Dict[str, Any],
        wall_reflections: Dict[str, Any],
    ) -> InversionLogEntry:
        """
        Log an interaction within a triangular mirror space.

        Creates a chain-linked ``InversionLogEntry``, updates the
        behavioral model, and optionally forwards to the global
        forensic chain.

        Parameters
        ----------
        space_id : UUID
            The inverted space the interaction occurred in.
        interaction : dict
            The attacker's raw interaction payload.
        response : dict
            The blended response returned to the attacker.
        wall_reflections : dict
            Per-wall reflection details (A, B, C).

        Returns
        -------
        InversionLogEntry
            The newly created forensic entry.
        """
        async with self._lock:
            # Get or initialize the chain for this space
            if space_id not in self._space_chains:
                self._space_chains[space_id] = []
                self._space_latest_hash[space_id] = self._genesis_hash(
                    space_id
                )

            previous_hash = self._space_latest_hash[space_id]

            # Create the entry
            entry = InversionLogEntry(
                space_id=space_id,
                interaction=interaction,
                response=response,
                wall_reflections=wall_reflections,
                previous_hash=previous_hash,
            )

            # Append and update latest hash
            self._space_chains[space_id].append(entry)
            self._space_latest_hash[space_id] = entry.chain_hash
            self._total_logged += 1

        # Update behavioral model (outside lock)
        model = self._get_or_create_model(space_id)
        tripwires = wall_reflections.get("tripwires", [])
        model.update(interaction, tripwires)

        # Forward critical events to global forensic chain
        if self._global_logger and self._should_forward(space_id, interaction):
            try:
                await self._global_logger.log_event(
                    event_type="hive.triangle.interaction",
                    source_entity=str(space_id),
                    evidence={
                        "interaction_count": len(
                            self._space_chains.get(space_id, [])
                        ),
                        "interaction_type": interaction.get("type", "unknown"),
                        "tripwires": tripwires,
                    },
                )
            except Exception as exc:
                logger.error(
                    ">>> [INVERSION_FORENSIC] Global forward failed: %s", exc
                )

        # Persist to DB (best effort)
        await self._persist_entry(entry)

        logger.debug(
            ">>> [INVERSION_FORENSIC] Space %s — entry #%d logged "
            "(hash=%s)",
            space_id,
            len(self._space_chains.get(space_id, [])),
            entry.chain_hash[:12],
        )

        return entry

    # ─── Space Report ────────────────────────────────────────────────────

    async def get_space_report(self, space_id: UUID) -> Dict[str, Any]:
        """
        Generate a comprehensive forensic report for a specific
        inversion space.

        Parameters
        ----------
        space_id : UUID
            The inverted space to report on.

        Returns
        -------
        dict
            Comprehensive report including timeline, behavioral model,
            chain integrity, and key interactions.
        """
        chain = self._space_chains.get(space_id, [])
        model = self._behavioral_models.get(space_id)

        # Chain integrity check
        chain_valid = self._verify_space_chain(space_id)

        # Key interactions (first 5, last 5, any tripwire events)
        key_interactions = self._extract_key_interactions(chain)

        return {
            "space_id": str(space_id),
            "total_interactions": len(chain),
            "chain_integrity": "valid" if chain_valid else "BROKEN",
            "chain_length": len(chain),
            "first_interaction": (
                chain[0].timestamp.isoformat() if chain else None
            ),
            "last_interaction": (
                chain[-1].timestamp.isoformat() if chain else None
            ),
            "duration_seconds": (
                (chain[-1].timestamp - chain[0].timestamp).total_seconds()
                if len(chain) >= 2
                else 0.0
            ),
            "behavioral_model": model.to_dict() if model else None,
            "key_interactions": key_interactions,
            "latest_chain_hash": self._space_latest_hash.get(
                space_id, ""
            )[:16],
        }

    # ─── Attacker Model ──────────────────────────────────────────────────

    def build_attacker_model(self, space_id: UUID) -> Dict[str, Any]:
        """
        Build or return the behavioral model for a specific space.

        Parameters
        ----------
        space_id : UUID
            The inverted space to model.

        Returns
        -------
        dict
            Serialized behavioral model with detected strategies,
            timing patterns, and interaction frequencies.
        """
        model = self._behavioral_models.get(space_id)
        if model:
            return model.to_dict()

        return {
            "space_id": str(space_id),
            "total_interactions": 0,
            "message": "No interactions recorded for this space",
        }

    # ─── Chain Verification ──────────────────────────────────────────────

    def _verify_space_chain(self, space_id: UUID) -> bool:
        """
        Verify the hash-chain integrity of a space's interaction log.
        """
        chain = self._space_chains.get(space_id, [])
        if not chain:
            return True

        expected_prev = self._genesis_hash(space_id)
        for entry in chain:
            if entry.previous_hash != expected_prev:
                logger.error(
                    ">>> [INVERSION_FORENSIC] Chain break in space %s "
                    "at entry %s",
                    space_id,
                    entry.entry_id,
                )
                return False
            expected_prev = entry.chain_hash

        return True

    # ─── Key Interaction Extraction ──────────────────────────────────────

    @staticmethod
    def _extract_key_interactions(
        chain: List[InversionLogEntry],
    ) -> List[Dict[str, Any]]:
        """
        Extract key interactions for the report — first 5, last 5,
        and any interactions that triggered tripwires.
        """
        if not chain:
            return []

        key: List[Dict[str, Any]] = []

        # First 5
        for entry in chain[:5]:
            key.append({
                "position": "first_5",
                "entry_id": entry.entry_id,
                "timestamp": entry.timestamp.isoformat(),
                "type": entry.interaction.get("type", "unknown"),
            })

        # Last 5 (if chain > 10 to avoid overlap)
        if len(chain) > 10:
            for entry in chain[-5:]:
                key.append({
                    "position": "last_5",
                    "entry_id": entry.entry_id,
                    "timestamp": entry.timestamp.isoformat(),
                    "type": entry.interaction.get("type", "unknown"),
                })

        # Tripwire events
        for entry in chain:
            tripwires = entry.wall_reflections.get("tripwires", [])
            if tripwires:
                key.append({
                    "position": "tripwire_event",
                    "entry_id": entry.entry_id,
                    "timestamp": entry.timestamp.isoformat(),
                    "tripwires": tripwires,
                })

        return key

    # ─── Internal Helpers ────────────────────────────────────────────────

    def _get_or_create_model(self, space_id: UUID) -> AttackerBehavioralModel:
        """Get or create a behavioral model for a space."""
        if space_id not in self._behavioral_models:
            self._behavioral_models[space_id] = AttackerBehavioralModel(
                space_id
            )
        return self._behavioral_models[space_id]

    def _should_forward(
        self, space_id: UUID, interaction: Dict[str, Any]
    ) -> bool:
        """
        Determine whether this interaction should be forwarded to the
        global forensic chain.

        Forwards on:
            - First interaction in a space
            - Every 100th interaction
            - Tripwire activations (handled in wall_reflections)
        """
        chain = self._space_chains.get(space_id, [])
        count = len(chain)
        return count == 1 or count % 100 == 0

    @staticmethod
    def _genesis_hash(space_id: UUID) -> str:
        """Compute the genesis hash for a space's local chain."""
        seed = f"INVERSION_GENESIS:{space_id}"
        return hashlib.sha256(seed.encode()).hexdigest()

    # ─── Persistence ─────────────────────────────────────────────────────

    async def _persist_entry(self, entry: InversionLogEntry) -> None:
        """Persist a log entry to the database (best effort)."""
        if not self._db_pool:
            return
        try:
            import json
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_inversion_logs
                        (entry_id, space_id, timestamp, interaction,
                         response, wall_reflections, chain_hash,
                         previous_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (entry_id) DO NOTHING
                    """,
                    entry.entry_id,
                    entry.space_id,
                    entry.timestamp,
                    json.dumps(entry.interaction, default=str),
                    json.dumps(entry.response, default=str),
                    json.dumps(entry.wall_reflections, default=str),
                    entry.chain_hash,
                    entry.previous_hash,
                )
        except Exception as exc:
            logger.debug(
                ">>> [INVERSION_FORENSIC] Entry persist failed: %s", exc
            )

    # ─── Diagnostics ─────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Logger diagnostic metrics."""
        return {
            "total_logged": self._total_logged,
            "tracked_spaces": len(self._space_chains),
            "behavioral_models": len(self._behavioral_models),
            "spaces_with_entries": {
                str(sid): len(chain)
                for sid, chain in self._space_chains.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"<InversionForensicLogger "
            f"logged={self._total_logged} "
            f"spaces={len(self._space_chains)}>"
        )
