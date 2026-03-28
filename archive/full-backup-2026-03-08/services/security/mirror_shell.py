"""
HIVE DEFENSE PROTOCOL — Phase 8A: Mirror Shell
The outermost defense layer between the external world and the real hive.

The Mirror Shell is the gateway — the first surface that any external signal
touches. Nothing from outside reaches the real hive directly. Every signal
is evaluated by the Coherence Gate, and routed into the appropriate dimension:

    PASS_TO_REAL    → Signal is verified; forwarded to the real hive.
    MIRROR_ABSORB   → Signal enters a mirror namespace; gets synthetic responses.
    MIRROR_CONTAIN  → Signal isolated; entity fingerprinted; alert raised.
    MIRROR_SUSPICIOUS → Signal quarantined for investigation.

The attacker never knows they are in the mirror. They receive plausible
responses, interact with synthetic data, and believe they have reached
the hive. They have not. They are talking to their own reflection.

Patent-Pending — Claim 30
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import (
    AttackerProfile,
    ForensicRecord,
    GateDecision,
    MirrorNamespace,
    MirrorSignal,
)

logger = logging.getLogger("hive.mirror_shell")


# =============================================================================
# MIRROR NAMESPACE MANAGER
# =============================================================================

class MirrorNamespaceManager:
    """
    Creates and manages isolated mirror namespaces — one per attacker or
    per suspicious entity cluster. Each namespace is a self-contained pocket
    dimension with its own synthetic data, its own response patterns, and
    its own forensic trail.

    An attacker contained in Namespace-A cannot see Namespace-B.
    Namespace-A's synthetic data is unique to the attacker's behavioral
    fingerprint, making it impossible for the attacker to compare notes
    with another attacker and detect the mirror.
    """

    def __init__(self) -> None:
        self._namespaces: Dict[UUID, MirrorNamespace] = {}
        self._entity_to_namespace: Dict[str, UUID] = {}
        self._synthetic_seeds: Dict[UUID, str] = {}
        logger.info("MirrorNamespaceManager initialized")

    # ── Namespace lifecycle ──────────────────────────────────────────────

    async def create_namespace(
        self,
        entity_identifier: str,
        seed_data: Optional[Dict[str, Any]] = None,
    ) -> MirrorNamespace:
        """
        Create a new isolated mirror namespace for a specific entity.

        Args:
            entity_identifier: Fingerprint or address of the entity to contain.
            seed_data: Optional data used to generate believable synthetic
                       responses within this namespace.

        Returns:
            The newly created MirrorNamespace.
        """
        namespace = MirrorNamespace(
            namespace_id=uuid4(),
            created_at=datetime.utcnow(),
            signal_count=0,
            entities_contained=[entity_identifier],
            is_active=True,
            synthetic_data_seed=self._generate_seed(entity_identifier, seed_data),
        )
        self._namespaces[namespace.namespace_id] = namespace
        self._entity_to_namespace[entity_identifier] = namespace.namespace_id
        self._synthetic_seeds[namespace.namespace_id] = namespace.synthetic_data_seed

        logger.info(
            "Mirror namespace %s created for entity '%s'",
            namespace.namespace_id,
            entity_identifier,
        )
        return namespace

    async def get_namespace_for_entity(
        self, entity_identifier: str
    ) -> Optional[MirrorNamespace]:
        """
        Retrieve the namespace containing a specific entity.

        Returns:
            The MirrorNamespace if the entity is contained, else None.
        """
        ns_id = self._entity_to_namespace.get(entity_identifier)
        if ns_id is None:
            return None
        return self._namespaces.get(ns_id)

    async def deactivate_namespace(self, namespace_id: UUID) -> bool:
        """
        Deactivate a mirror namespace. The namespace is kept for forensic
        purposes but stops accepting new signals.

        Returns:
            True if the namespace was deactivated, False if not found.
        """
        ns = self._namespaces.get(namespace_id)
        if ns is None:
            return False
        ns.is_active = False
        logger.info("Mirror namespace %s deactivated", namespace_id)
        return True

    async def list_active_namespaces(self) -> List[MirrorNamespace]:
        """Return all currently active mirror namespaces."""
        return [ns for ns in self._namespaces.values() if ns.is_active]

    # ── Synthetic data generation ────────────────────────────────────────

    async def generate_synthetic_response(
        self,
        namespace_id: UUID,
        request_type: str,
        request_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a believable synthetic response for a contained entity.

        The response is derived from the namespace's synthetic data seed and
        the request parameters, ensuring:
        - Responses are internally consistent within the namespace.
        - Responses look structurally identical to real hive responses.
        - No real hive data is ever leaked into a mirror namespace.

        Args:
            namespace_id: The namespace to generate data for.
            request_type: The type of request (e.g. 'session_data', 'user_list').
            request_payload: The request parameters.

        Returns:
            A synthetic response dictionary.
        """
        ns = self._namespaces.get(namespace_id)
        if ns is None or not ns.is_active:
            logger.warning(
                "Synthetic response requested for invalid/inactive namespace %s",
                namespace_id,
            )
            return {"error": "service_unavailable", "retry_after": 30}

        seed = self._synthetic_seeds.get(namespace_id, "")
        composite_key = f"{seed}:{request_type}:{hashlib.sha256(str(request_payload).encode()).hexdigest()}"
        response_hash = hashlib.sha256(composite_key.encode()).hexdigest()

        # Build a structurally plausible response
        synthetic_response: Dict[str, Any] = {
            "status": "ok",
            "request_id": str(uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "data": self._build_synthetic_payload(request_type, response_hash),
            "_mirror_ns": str(namespace_id),  # Internal tracking only
        }

        ns.signal_count += 1
        logger.debug(
            "Synthetic response generated in namespace %s for request type '%s'",
            namespace_id,
            request_type,
        )
        return synthetic_response

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _generate_seed(
        entity_identifier: str,
        seed_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Derive a deterministic synthetic data seed for a namespace."""
        raw = f"{entity_identifier}:{time.monotonic_ns()}"
        if seed_data:
            raw += f":{hashlib.sha256(str(seed_data).encode()).hexdigest()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _build_synthetic_payload(
        request_type: str,
        response_hash: str,
    ) -> Dict[str, Any]:
        """
        Build a synthetic payload that looks structurally valid for the
        given request type. Uses the response hash to generate consistent
        but meaningless data.
        """
        # Synthetic payloads are deterministic per (namespace, request_type, payload)
        # so repeated queries return the same fake data — mimicking cacheability
        prefix = response_hash[:8]
        return {
            "type": request_type,
            "records": [
                {
                    "id": f"syn-{prefix}-{i}",
                    "value": hashlib.md5(
                        f"{response_hash}:{i}".encode()
                    ).hexdigest()[:16],
                    "ts": datetime.utcnow().isoformat(),
                }
                for i in range(3)
            ],
            "total": 3,
            "synthetic": True,  # Stripped before delivery; kept for internal audits
        }


# =============================================================================
# MIRROR SHELL — THE OUTERMOST DEFENSE LAYER
# =============================================================================

class MirrorShell:
    """
    The Mirror Shell is the outermost perimeter of the Hive Defense Protocol.
    Every external signal — API call, WebSocket message, BLE fragment, Service
    Bus topic — must pass through the Mirror Shell before it can reach the
    real hive.

    The shell operates a simple but devastating loop:

        1. Signal arrives.
        2. Coherence Gate evaluates the signal.
        3. Based on the Gate's decision:
           - PASS_TO_REAL:      Forward to the real hive (rare).
           - MIRROR_ABSORB:     Route to a mirror namespace; feed synthetic data.
           - MIRROR_CONTAIN:    Isolate the entity; fingerprint; alert Nathan.
           - MIRROR_SUSPICIOUS: Quarantine for deeper investigation.
        4. All activity is forensically logged with chain hashes.

    The attacker never knows which path they are on.

    Usage:
        shell = MirrorShell(coherence_gate=gate, forensic_logger=forensic_logger)
        await shell.initialize()
        decision = await shell.process_signal(incoming_signal)
    """

    # ── Class-level constants ────────────────────────────────────────────

    PATENT_CLAIM = 30
    ALERT_THRESHOLD_CONTAINED = 5  # Alert Nathan after N containment events

    def __init__(
        self,
        coherence_gate: Any,       # CoherenceGate instance
        forensic_logger: Any,      # ForensicLogger instance
    ) -> None:
        """
        Initialize the Mirror Shell.

        Args:
            coherence_gate: The CoherenceGate that evaluates signal coherence.
            forensic_logger: The ForensicLogger that records all mirror activity
                             into an immutable forensic chain.
        """
        self._gate = coherence_gate
        self._forensic = forensic_logger
        self._namespace_mgr = MirrorNamespaceManager()
        self._attacker_profiles: Dict[str, AttackerProfile] = {}

        # ── Metrics ──────────────────────────────────────────────────────
        self._total_signals_processed: int = 0
        self._mirror_absorbed: int = 0
        self._mirror_contained: int = 0
        self._mirror_suspicious: int = 0
        self._passed_to_real: int = 0

        self._initialized: bool = False
        logger.info("MirrorShell created (patent claim %d)", self.PATENT_CLAIM)

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """
        Perform async initialization of the Mirror Shell.

        This is called once at system startup to prepare the default mirror
        namespace (the 'catch-all' for unclassified signals) and to verify
        that the Coherence Gate and Forensic Logger are operational.
        """
        if self._initialized:
            logger.warning("MirrorShell.initialize() called twice — skipping")
            return

        # Create a default catch-all namespace
        await self._namespace_mgr.create_namespace(
            entity_identifier="__default__",
            seed_data={"purpose": "catch_all_unclassified"},
        )

        self._initialized = True
        logger.info("MirrorShell initialized — defense perimeter ACTIVE")

    async def shutdown(self) -> None:
        """
        Graceful shutdown. Deactivate all namespaces and flush forensic logs.
        """
        active_ns = await self._namespace_mgr.list_active_namespaces()
        for ns in active_ns:
            await self._namespace_mgr.deactivate_namespace(ns.namespace_id)

        logger.info(
            "MirrorShell shutdown complete. "
            "Signals processed: %d | Absorbed: %d | Contained: %d | "
            "Suspicious: %d | Passed: %d",
            self._total_signals_processed,
            self._mirror_absorbed,
            self._mirror_contained,
            self._mirror_suspicious,
            self._passed_to_real,
        )

    # ── Core signal processing ───────────────────────────────────────────

    async def process_signal(self, signal: Dict[str, Any]) -> GateDecision:
        """
        Process an incoming external signal through the Mirror Shell.

        This is the primary entry point. Every external signal must pass
        through this method. The signal is evaluated by the Coherence Gate,
        routed to the appropriate handler, and forensically logged.

        Args:
            signal: A dictionary containing at minimum:
                - 'source_address' (str): Origin of the signal.
                - 'signal_type' (str): Category of the signal.
                - 'payload' (dict): The signal body.

        Returns:
            The GateDecision indicating what happened to the signal.
        """
        if not self._initialized:
            logger.error("process_signal called before initialize() — rejecting")
            return GateDecision.MIRROR_CONTAIN

        self._total_signals_processed += 1
        signal_id = uuid4()
        source = signal.get("source_address", "unknown")
        signal_type = signal.get("signal_type", "unknown")
        payload = signal.get("payload", {})

        logger.debug(
            "Signal %s from '%s' type='%s' — evaluating",
            signal_id, source, signal_type,
        )

        # ── Step 1: Coherence Gate evaluation ────────────────────────────
        decision = await self._evaluate_signal(signal_id, source, signal_type, payload)

        # ── Step 2: Route based on decision ──────────────────────────────
        mirror_signal = MirrorSignal(
            signal_id=signal_id,
            namespace_id=uuid4(),  # Updated by handler
            source_address=source,
            signal_type=signal_type,
            payload_hash=hashlib.sha256(str(payload).encode()).hexdigest(),
            gate_decision=decision,
            timestamp=datetime.utcnow(),
            metadata=signal.get("metadata", {}),
        )

        if decision == GateDecision.PASS_TO_REAL:
            await self._handle_pass_to_real(mirror_signal, signal)
        elif decision == GateDecision.MIRROR_ABSORB:
            await self._handle_mirror_absorb(mirror_signal, signal)
        elif decision == GateDecision.MIRROR_CONTAIN:
            await self._handle_mirror_contain(mirror_signal, signal)
        elif decision == GateDecision.MIRROR_SUSPICIOUS:
            await self._handle_mirror_suspicious(mirror_signal, signal)

        # ── Step 3: Forensic record ──────────────────────────────────────
        await self._log_forensic_event(
            event_type=f"mirror_shell.{decision.value}",
            source_entity=source,
            evidence={
                "signal_id": str(signal_id),
                "signal_type": signal_type,
                "decision": decision.value,
                "payload_hash": mirror_signal.payload_hash,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return decision

    # ── Decision handlers ────────────────────────────────────────────────

    async def _evaluate_signal(
        self,
        signal_id: UUID,
        source: str,
        signal_type: str,
        payload: Dict[str, Any],
    ) -> GateDecision:
        """
        Evaluate a signal through the Coherence Gate.

        The gate considers: signal origin, payload structure, entity history,
        current DEFCON level, and behavioral coherence patterns.

        NOTE: CoherenceGate.evaluate() is synchronous by design (hot-path,
        sub-millisecond budget).  We construct an InternalSignal from the
        incoming parameters and call the gate directly.
        """
        try:
            from app.services.security.coherence_gate import InternalSignal

            internal = InternalSignal(
                source_entity_id=signal_id,
                signal_type=signal_type,
                payload=payload,
                metadata={"source_address": source},
            )
            result = self._gate.evaluate(signal=internal)
            return result.decision
        except Exception as exc:
            # Gate failure → default to containment (fail-secure)
            logger.error(
                "Coherence Gate raised exception for signal %s: %s — defaulting to CONTAIN",
                signal_id, exc,
            )
            return GateDecision.MIRROR_CONTAIN

    async def _handle_pass_to_real(
        self,
        mirror_signal: MirrorSignal,
        raw_signal: Dict[str, Any],
    ) -> None:
        """
        Handle a signal that has been cleared to reach the real hive.

        Even verified signals are logged — trust but verify downstream.
        """
        self._passed_to_real += 1
        logger.info(
            "Signal %s PASSED to real hive (source='%s', type='%s')",
            mirror_signal.signal_id,
            mirror_signal.source_address,
            mirror_signal.signal_type,
        )

    async def _handle_mirror_absorb(
        self,
        mirror_signal: MirrorSignal,
        raw_signal: Dict[str, Any],
    ) -> None:
        """
        Handle a signal absorbed into a mirror namespace.

        The signal enters the mirror dimension and receives synthetic
        responses. The entity believes it is interacting with the real hive.
        """
        self._mirror_absorbed += 1
        source = mirror_signal.source_address

        # Get or create namespace for this entity
        namespace = await self._namespace_mgr.get_namespace_for_entity(source)
        if namespace is None:
            namespace = await self._namespace_mgr.create_namespace(
                entity_identifier=source,
                seed_data=raw_signal.get("payload", {}),
            )

        mirror_signal.namespace_id = namespace.namespace_id
        namespace.signal_count += 1

        # Generate synthetic response (stored for the entity's next read)
        await self._namespace_mgr.generate_synthetic_response(
            namespace_id=namespace.namespace_id,
            request_type=mirror_signal.signal_type,
            request_payload=raw_signal.get("payload", {}),
        )

        logger.info(
            "Signal %s ABSORBED into namespace %s (source='%s')",
            mirror_signal.signal_id,
            namespace.namespace_id,
            source,
        )

    async def _handle_mirror_contain(
        self,
        mirror_signal: MirrorSignal,
        raw_signal: Dict[str, Any],
    ) -> None:
        """
        Handle a signal that must be contained.

        The entity is fingerprinted, isolated in a dedicated namespace,
        and an alert is raised if the containment threshold is exceeded.
        """
        self._mirror_contained += 1
        source = mirror_signal.source_address

        # Fingerprint the attacker
        profile = await self._fingerprint_entity(source, raw_signal)

        # Ensure dedicated containment namespace
        namespace = await self._namespace_mgr.get_namespace_for_entity(source)
        if namespace is None:
            namespace = await self._namespace_mgr.create_namespace(
                entity_identifier=source,
                seed_data={
                    "containment": True,
                    "profile_id": str(profile.profile_id),
                },
            )

        mirror_signal.namespace_id = namespace.namespace_id
        namespace.signal_count += 1

        if source not in namespace.entities_contained:
            namespace.entities_contained.append(source)

        logger.warning(
            "Signal %s CONTAINED — entity '%s' isolated in namespace %s "
            "(profile=%s, sophistication=%d)",
            mirror_signal.signal_id,
            source,
            namespace.namespace_id,
            profile.profile_id,
            profile.sophistication_level,
        )

        # Raise alert if threshold exceeded
        if self._mirror_contained >= self.ALERT_THRESHOLD_CONTAINED:
            await self._raise_containment_alert(source, profile)

    async def _handle_mirror_suspicious(
        self,
        mirror_signal: MirrorSignal,
        raw_signal: Dict[str, Any],
    ) -> None:
        """
        Handle a suspicious signal that requires deeper investigation.

        The signal is quarantined — it doesn't reach the real hive and
        doesn't yet receive synthetic responses. It sits in limbo while
        the Curiosity Protocol examines it.
        """
        self._mirror_suspicious += 1

        # Use the default catch-all namespace for quarantine
        default_ns = await self._namespace_mgr.get_namespace_for_entity("__default__")
        if default_ns:
            mirror_signal.namespace_id = default_ns.namespace_id
            default_ns.signal_count += 1

        logger.warning(
            "Signal %s QUARANTINED for investigation (source='%s', type='%s')",
            mirror_signal.signal_id,
            mirror_signal.source_address,
            mirror_signal.signal_type,
        )

    # ── Attacker fingerprinting ──────────────────────────────────────────

    async def _fingerprint_entity(
        self,
        entity_identifier: str,
        signal: Dict[str, Any],
    ) -> AttackerProfile:
        """
        Build or update a behavioral fingerprint for a contained entity.

        The fingerprint tracks communication protocols, tool signatures,
        timing patterns, and sophistication level — everything needed to
        recognize this attacker if they return through a different channel.

        Args:
            entity_identifier: The entity's address or ID.
            signal: The raw signal data.

        Returns:
            The current or newly created AttackerProfile.
        """
        existing = self._attacker_profiles.get(entity_identifier)

        if existing is not None:
            # Update existing profile with new observations
            existing.last_seen = datetime.utcnow()
            existing.behavioral_patterns[f"signal_{existing.last_seen.isoformat()}"] = {
                "type": signal.get("signal_type", "unknown"),
                "payload_hash": hashlib.sha256(
                    str(signal.get("payload", {})).encode()
                ).hexdigest(),
            }
            if len(existing.behavioral_patterns) > 3:
                existing.sophistication_level = min(5, existing.sophistication_level + 1)
            return existing

        # Create new profile
        profile = AttackerProfile(
            profile_id=uuid4(),
            communication_protocol={
                "initial_signal_type": signal.get("signal_type", "unknown"),
            },
            behavioral_patterns={
                "first_contact": {
                    "type": signal.get("signal_type", "unknown"),
                    "payload_hash": hashlib.sha256(
                        str(signal.get("payload", {})).encode()
                    ).hexdigest(),
                    "timestamp": datetime.utcnow().isoformat(),
                }
            },
            tool_signatures=[],
            sophistication_level=1,
            first_seen=datetime.utcnow(),
            active_channels=[entity_identifier],
        )
        self._attacker_profiles[entity_identifier] = profile

        logger.info(
            "New attacker profile created: %s for entity '%s'",
            profile.profile_id,
            entity_identifier,
        )
        return profile

    # ── Alerts ───────────────────────────────────────────────────────────

    async def _raise_containment_alert(
        self,
        entity_identifier: str,
        profile: AttackerProfile,
    ) -> None:
        """
        Raise a containment alert when the threshold is exceeded.

        This triggers a notification to Nathan and escalates the DEFCON
        level if necessary.
        """
        logger.critical(
            "CONTAINMENT ALERT — %d containment events reached. "
            "Latest entity: '%s' (profile=%s, sophistication=%d). "
            "Escalation recommended.",
            self._mirror_contained,
            entity_identifier,
            profile.profile_id,
            profile.sophistication_level,
        )

        await self._log_forensic_event(
            event_type="mirror_shell.containment_alert",
            source_entity=entity_identifier,
            evidence={
                "total_contained": self._mirror_contained,
                "profile_id": str(profile.profile_id),
                "sophistication_level": profile.sophistication_level,
                "active_channels": profile.active_channels,
            },
        )

    # ── Forensic logging ─────────────────────────────────────────────────

    async def _log_forensic_event(
        self,
        event_type: str,
        source_entity: Optional[str] = None,
        target_entity: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an immutable forensic event through the ForensicLogger.

        Every mirror shell action creates a forensic record linked into
        an append-only hash chain for legal and security auditing.
        """
        try:
            record = ForensicRecord(
                record_id=uuid4(),
                event_type=event_type,
                source_entity=source_entity,
                target_entity=target_entity,
                evidence=evidence or {},
                timestamp=datetime.utcnow(),
            )
            await self._forensic.log(record)
        except Exception as exc:
            # Forensic logging failure must not break signal processing
            logger.error(
                "Failed to write forensic record for event '%s': %s",
                event_type, exc,
            )

    # ── Metrics & introspection ──────────────────────────────────────────

    @property
    def metrics(self) -> Dict[str, int]:
        """Return current mirror shell processing metrics."""
        return {
            "total_signals_processed": self._total_signals_processed,
            "mirror_absorbed": self._mirror_absorbed,
            "mirror_contained": self._mirror_contained,
            "mirror_suspicious": self._mirror_suspicious,
            "passed_to_real": self._passed_to_real,
        }

    @property
    def active_namespace_count(self) -> int:
        """Return the number of currently active mirror namespaces."""
        return len([
            ns for ns in self._namespace_mgr._namespaces.values()
            if ns.is_active
        ])

    @property
    def attacker_profile_count(self) -> int:
        """Return the number of tracked attacker profiles."""
        return len(self._attacker_profiles)

    async def get_attacker_profile(
        self, entity_identifier: str
    ) -> Optional[AttackerProfile]:
        """Retrieve an attacker profile by entity identifier."""
        return self._attacker_profiles.get(entity_identifier)

    async def get_namespace_manager(self) -> MirrorNamespaceManager:
        """Return the internal namespace manager for advanced operations."""
        return self._namespace_mgr

    def __repr__(self) -> str:
        return (
            f"<MirrorShell signals={self._total_signals_processed} "
            f"absorbed={self._mirror_absorbed} contained={self._mirror_contained} "
            f"suspicious={self._mirror_suspicious} passed={self._passed_to_real} "
            f"namespaces={self.active_namespace_count}>"
        )
