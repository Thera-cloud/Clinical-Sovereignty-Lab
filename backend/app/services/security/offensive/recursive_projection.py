"""
HIVE DEFENSE PROTOCOL — Recursive Projection (Phase 8E)
Self-improving mirror: the attacker trains us to deceive them better.

Each intercepted command improves the attacker behavioral model.  Mirror
accuracy starts at 0.7, improves by 0.005 per interaction, and caps at
0.99.  Over time the mirror converges until it can anticipate attacker
commands *before* they're sent.

The attacker is unknowingly training the mirror to deceive them better
with every command they issue.

Patent-Pending — Claim 54
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.models.hive_defense import (
    AttackerProfile,
    RecursiveLearningState,
)

logger = logging.getLogger("hive.recursive_projection")


# =============================================================================
# TUNABLES
# =============================================================================

INITIAL_ACCURACY: float = 0.7
ACCURACY_INCREMENT: float = 0.005
MAX_ACCURACY: float = 0.99
HIGH_CONVERGENCE_THRESHOLD: float = 0.95


# =============================================================================
# RECURSIVE PROJECTION — Patent Claim 54
# =============================================================================

class RecursiveProjection:
    """
    Self-improving mirror that learns from each intercepted attacker command.

    Every interaction refines the attacker behavioral model.  The three
    mirror walls (protocol, topology, behavior) are updated in-place as
    the model improves, producing increasingly convincing reflections.

    Convergence is tracked via ``model_accuracy`` — when it reaches
    ``HIGH_CONVERGENCE_THRESHOLD`` (0.95), the mirror can often predict
    what the attacker expects to see *before* the command arrives.

    Attributes
    ----------
    deployment_id : UUID
        The parent ProjectedHelix deployment.
    learning_state : RecursiveLearningState
        Persistent state model tracking accuracy, version, and history size.
    interaction_history : list[dict]
        Complete record of all processed interactions for forensic analysis.

    Usage
    -----
    ::

        rp = RecursiveProjection(
            deployment_id=helix.deployment_id,
            protocol_mirror=helix.protocol_mirror,
            topology_mirror=helix.topology_mirror,
            behavior_mirror=helix.behavior_mirror,
            attacker_profile=profile,
        )
        response = await rp.process_and_learn(command)
        prediction = await rp.predict_expectation(next_command)
    """

    def __init__(
        self,
        deployment_id: UUID,
        protocol_mirror: Any,
        topology_mirror: Any,
        behavior_mirror: Any,
        attacker_profile: Optional[AttackerProfile] = None,
    ) -> None:
        """
        Initialise the Recursive Projection.

        Parameters
        ----------
        deployment_id:
            The parent Projected Helix deployment UUID.
        protocol_mirror:
            Reference to the :class:`AttackerProtocolMirror` instance.
        topology_mirror:
            Reference to the :class:`AttackerTopologyMirror` instance.
        behavior_mirror:
            Reference to the :class:`AttackerBehaviorMirror` instance.
        attacker_profile:
            Initial attacker profile from Penetrator intelligence.
        """
        self.deployment_id: UUID = deployment_id

        # Mirror wall references (updated in-place)
        self._protocol_mirror = protocol_mirror
        self._topology_mirror = topology_mirror
        self._behavior_mirror = behavior_mirror

        # Attacker profile (evolves with learning)
        self._attacker_profile: AttackerProfile = attacker_profile or AttackerProfile()

        # Learning state
        self.learning_state: RecursiveLearningState = RecursiveLearningState(
            deployment_id=deployment_id,
            attacker_model_version=0,
            model_accuracy=INITIAL_ACCURACY,
            interaction_history_size=0,
            protocol_patterns_learned=0,
        )

        # Full interaction history for forensic analysis
        self.interaction_history: List[Dict[str, Any]] = []

        # Pattern accumulators for model refinement
        self._protocol_patterns: Dict[str, int] = {}
        self._topology_patterns: Dict[str, int] = {}
        self._behavior_patterns: Dict[str, int] = {}
        self._command_sequence: List[str] = []
        self._timing_history: List[float] = []

        # Prediction state
        self._prediction_cache: Dict[str, Dict[str, Any]] = {}

        logger.info(
            "RecursiveProjection initialised: deployment=%s "
            "initial_accuracy=%.3f",
            deployment_id,
            INITIAL_ACCURACY,
        )

    # ------------------------------------------------------------------
    # Core learning loop — Patent Claim 54
    # ------------------------------------------------------------------

    async def process_and_learn(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process an intercepted command and update the attacker model.

        Each call:
        1. Generates a blended mirror response from all three walls.
        2. Extracts new patterns from the command.
        3. Updates the attacker behavioral model.
        4. Increments mirror accuracy (capped at 0.99).
        5. Pushes updated intelligence to all three mirror walls.

        Parameters
        ----------
        command:
            The intercepted attacker command.

        Returns
        -------
        dict
            A model update summary containing the new accuracy and any
            patterns learned.
        """
        interaction_start = time.monotonic()

        # 1. Extract patterns from this command
        patterns = self._extract_patterns(command)

        # 2. Update the attacker behavioral model
        self._update_model(command, patterns)

        # 3. Increment accuracy
        old_accuracy = self.learning_state.model_accuracy
        self.learning_state.model_accuracy = min(
            MAX_ACCURACY,
            self.learning_state.model_accuracy + ACCURACY_INCREMENT,
        )
        self.learning_state.attacker_model_version += 1
        self.learning_state.interaction_history_size += 1
        self.learning_state.last_model_update = datetime.utcnow()

        # 4. Push updated intelligence to mirror walls
        await self._propagate_to_mirrors(patterns)

        # 5. Record in interaction history
        elapsed_ms = (time.monotonic() - interaction_start) * 1000
        interaction_record = {
            "interaction_number": self.learning_state.interaction_history_size,
            "command_type": command.get("type", "unknown"),
            "patterns_extracted": len(patterns),
            "accuracy_before": round(old_accuracy, 4),
            "accuracy_after": round(self.learning_state.model_accuracy, 4),
            "model_version": self.learning_state.attacker_model_version,
            "processing_time_ms": round(elapsed_ms, 2),
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.interaction_history.append(interaction_record)

        # 6. Track command sequence for prediction
        self._command_sequence.append(command.get("type", "unknown"))
        self._timing_history.append(time.monotonic())

        # 7. Check convergence
        if (
            self.learning_state.model_accuracy >= HIGH_CONVERGENCE_THRESHOLD
            and old_accuracy < HIGH_CONVERGENCE_THRESHOLD
        ):
            logger.warning(
                "RecursiveProjection %s reached HIGH CONVERGENCE: "
                "accuracy=%.3f after %d interactions",
                self.deployment_id,
                self.learning_state.model_accuracy,
                self.learning_state.interaction_history_size,
            )

        logger.info(
            "RecursiveProjection learned from interaction #%d: "
            "accuracy %.3f → %.3f (version=%d, patterns=%d)",
            self.learning_state.interaction_history_size,
            old_accuracy,
            self.learning_state.model_accuracy,
            self.learning_state.attacker_model_version,
            len(patterns),
        )

        return interaction_record

    # ------------------------------------------------------------------
    # Prediction — anticipate commands before they're sent
    # ------------------------------------------------------------------

    async def predict_expectation(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Predict what the attacker expects to see in response to this command.

        Uses the accumulated behavioral model to generate the response the
        attacker's C&C is most likely to accept.  At high convergence
        (accuracy >= 0.95), predictions are reliable enough to pre-generate
        responses.

        Parameters
        ----------
        command:
            The attacker command to predict a response for.

        Returns
        -------
        dict
            A prediction containing the expected response, confidence
            level, and the basis for the prediction.
        """
        cmd_type = command.get("type", "unknown")

        # Build prediction from accumulated patterns
        protocol_prediction = self._predict_protocol_expectation(command)
        topology_prediction = self._predict_topology_expectation(command)
        behavior_prediction = self._predict_behavior_expectation(command)

        # Combine with confidence weighting
        confidence = self.learning_state.model_accuracy
        prediction: Dict[str, Any] = {
            "command_type": cmd_type,
            "confidence": round(confidence, 4),
            "converged": confidence >= HIGH_CONVERGENCE_THRESHOLD,
            "predicted_response": {
                "protocol": protocol_prediction,
                "topology": topology_prediction,
                "behavior": behavior_prediction,
            },
            "prediction_basis": {
                "interactions_analyzed": self.learning_state.interaction_history_size,
                "protocol_patterns": len(self._protocol_patterns),
                "topology_patterns": len(self._topology_patterns),
                "behavior_patterns": len(self._behavior_patterns),
                "command_sequence_length": len(self._command_sequence),
            },
            "model_version": self.learning_state.attacker_model_version,
            "predicted_at": datetime.utcnow().isoformat(),
        }

        # Cache prediction for rapid response
        self._prediction_cache[cmd_type] = prediction

        logger.debug(
            "RecursiveProjection prediction: type=%s confidence=%.3f "
            "converged=%s",
            cmd_type,
            confidence,
            prediction["converged"],
        )

        return prediction

    # ------------------------------------------------------------------
    # Model refinement (called by worker)
    # ------------------------------------------------------------------

    async def refine_model(self) -> Dict[str, Any]:
        """
        Perform a deeper model refinement pass using all accumulated
        interactions.

        This is called periodically by the RecursiveLearningWorker to
        perform more thorough analysis than the per-interaction learning.

        Returns
        -------
        dict
            Refinement results including new patterns discovered and
            current accuracy.
        """
        if not self.interaction_history:
            return {
                "refined": False,
                "reason": "no_interactions",
                "accuracy": self.learning_state.model_accuracy,
            }

        refinement_start = time.monotonic()

        # Analyze command sequence for temporal patterns
        temporal_patterns = self._analyze_temporal_patterns()

        # Analyze command type frequencies
        type_frequencies = self._analyze_type_frequencies()

        # Update protocol patterns from frequency analysis
        new_protocol_patterns = 0
        for cmd_type, freq in type_frequencies.items():
            pattern_key = f"cmd_freq:{cmd_type}"
            if pattern_key not in self._protocol_patterns:
                self._protocol_patterns[pattern_key] = freq
                new_protocol_patterns += 1
            else:
                self._protocol_patterns[pattern_key] = freq

        # Update learning state
        self.learning_state.protocol_patterns_learned = len(
            self._protocol_patterns
        )

        elapsed_ms = (time.monotonic() - refinement_start) * 1000

        result = {
            "refined": True,
            "model_version": self.learning_state.attacker_model_version,
            "accuracy": self.learning_state.model_accuracy,
            "interactions_analyzed": len(self.interaction_history),
            "temporal_patterns": len(temporal_patterns),
            "type_frequencies": type_frequencies,
            "new_protocol_patterns": new_protocol_patterns,
            "total_protocol_patterns": len(self._protocol_patterns),
            "refinement_time_ms": round(elapsed_ms, 2),
        }

        logger.info(
            "RecursiveProjection model refined: version=%d accuracy=%.3f "
            "temporal_patterns=%d new_protocol=%d",
            self.learning_state.attacker_model_version,
            self.learning_state.model_accuracy,
            len(temporal_patterns),
            new_protocol_patterns,
        )

        return result

    # ------------------------------------------------------------------
    # Pattern extraction
    # ------------------------------------------------------------------

    def _extract_patterns(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract learnable patterns from an intercepted command.

        Analyses protocol format, network metadata, and behavioral cues
        to identify patterns that can improve the mirror accuracy.
        """
        patterns: Dict[str, Any] = {
            "protocol": {},
            "topology": {},
            "behavior": {},
        }

        # Protocol patterns
        if "correlation_id" in command:
            cid = str(command["correlation_id"])
            pattern_key = f"cid_format:{len(cid)}"
            self._protocol_patterns[pattern_key] = (
                self._protocol_patterns.get(pattern_key, 0) + 1
            )
            patterns["protocol"]["correlation_id_length"] = len(cid)

        if "sequence_number" in command:
            seq = command["sequence_number"]
            if self._command_sequence:
                # Track sequence increments
                pattern_key = f"seq_increment"
                patterns["protocol"]["sequence_number"] = seq

        if "auth_token" in command:
            token = str(command["auth_token"])
            pattern_key = f"token_format:{len(token)}"
            self._protocol_patterns[pattern_key] = (
                self._protocol_patterns.get(pattern_key, 0) + 1
            )
            patterns["protocol"]["token_length"] = len(token)

        if "protocol_version" in command:
            patterns["protocol"]["protocol_version"] = command["protocol_version"]

        # Topology patterns
        if "source_ip" in command:
            patterns["topology"]["source_ip"] = command["source_ip"]
        if "ttl" in command:
            patterns["topology"]["ttl"] = command["ttl"]
            pattern_key = f"ttl:{command['ttl']}"
            self._topology_patterns[pattern_key] = (
                self._topology_patterns.get(pattern_key, 0) + 1
            )
        if "hop_count" in command:
            patterns["topology"]["hop_count"] = command["hop_count"]

        # Behavior patterns
        cmd_type = command.get("type", "unknown")
        pattern_key = f"cmd_type:{cmd_type}"
        self._behavior_patterns[pattern_key] = (
            self._behavior_patterns.get(pattern_key, 0) + 1
        )
        patterns["behavior"]["command_type"] = cmd_type

        if "agent_id" in command:
            patterns["behavior"]["agent_id"] = command["agent_id"]
            agent_key = f"agent:{command['agent_id']}"
            self._behavior_patterns[agent_key] = (
                self._behavior_patterns.get(agent_key, 0) + 1
            )

        return patterns

    # ------------------------------------------------------------------
    # Model updates
    # ------------------------------------------------------------------

    def _update_model(
        self,
        command: Dict[str, Any],
        patterns: Dict[str, Any],
    ) -> None:
        """
        Update the attacker behavioral model with extracted patterns.

        This directly modifies the :class:`AttackerProfile` to reflect
        newly learned intelligence.
        """
        # Update communication protocol
        proto_patterns = patterns.get("protocol", {})
        if proto_patterns:
            self._attacker_profile.communication_protocol.update(proto_patterns)

        # Update network topology
        topo_patterns = patterns.get("topology", {})
        if topo_patterns:
            self._attacker_profile.network_topology.update(topo_patterns)

        # Update behavioral patterns
        behav_patterns = patterns.get("behavior", {})
        if behav_patterns:
            self._attacker_profile.behavioral_patterns.update(behav_patterns)

        # Update expected responses from prediction cache
        cmd_type = command.get("type", "unknown")
        if cmd_type in self._prediction_cache:
            self._attacker_profile.expected_responses[cmd_type] = (
                self._prediction_cache[cmd_type]
            )

        # Update last seen
        self._attacker_profile.last_seen = datetime.utcnow()

    async def _propagate_to_mirrors(
        self,
        patterns: Dict[str, Any],
    ) -> None:
        """
        Push updated intelligence to all three mirror walls.

        Each mirror receives the patterns relevant to its domain so that
        future reflections incorporate the latest learning.
        """
        proto_patterns = patterns.get("protocol", {})
        if proto_patterns and hasattr(self._protocol_mirror, "update_protocol_spec"):
            self._protocol_mirror.update_protocol_spec(proto_patterns)

        topo_patterns = patterns.get("topology", {})
        if topo_patterns and hasattr(self._topology_mirror, "update_topology_spec"):
            self._topology_mirror.update_topology_spec(topo_patterns)

        behav_patterns = patterns.get("behavior", {})
        if behav_patterns and hasattr(self._behavior_mirror, "update_behavioral_profile"):
            self._behavior_mirror.update_behavioral_profile(behav_patterns)

    # ------------------------------------------------------------------
    # Prediction internals
    # ------------------------------------------------------------------

    def _predict_protocol_expectation(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Predict the protocol-level response the attacker expects."""
        return {
            "expected_status": "success",
            "expected_correlation": command.get("correlation_id"),
            "expected_version": self._attacker_profile.communication_protocol.get(
                "protocol_version", "1.0"
            ),
        }

    def _predict_topology_expectation(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Predict the network topology characteristics the attacker expects."""
        topo = self._attacker_profile.network_topology
        return {
            "expected_latency_ms": topo.get("latency_ms", {}).get("mean", 30),
            "expected_hops": topo.get("hop_count", {}).get("typical", 4),
            "expected_ttl": topo.get("ttl", 64),
        }

    def _predict_behavior_expectation(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Predict the behavioral response the attacker expects."""
        return {
            "expected_style": self._attacker_profile.behavioral_patterns.get(
                "communication_style", "structured"
            ),
            "expected_agent_status": "active",
            "expected_data_format": self._attacker_profile.behavioral_patterns.get(
                "data_format", "json"
            ),
        }

    # ------------------------------------------------------------------
    # Temporal analysis
    # ------------------------------------------------------------------

    def _analyze_temporal_patterns(self) -> List[Dict[str, Any]]:
        """
        Analyze the timing between commands to identify temporal patterns.

        Returns
        -------
        list[dict]
            Identified temporal patterns (e.g. periodic beacons, burst
            activity windows).
        """
        if len(self._timing_history) < 3:
            return []

        patterns: List[Dict[str, Any]] = []
        intervals = []

        for i in range(1, len(self._timing_history)):
            interval = self._timing_history[i] - self._timing_history[i - 1]
            intervals.append(interval)

        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            min_interval = min(intervals)
            max_interval = max(intervals)

            patterns.append({
                "type": "interval_distribution",
                "avg_seconds": round(avg_interval, 3),
                "min_seconds": round(min_interval, 3),
                "max_seconds": round(max_interval, 3),
                "sample_size": len(intervals),
            })

            # Detect periodicity
            if max_interval > 0 and (max_interval - min_interval) / max_interval < 0.2:
                patterns.append({
                    "type": "periodic_beacon",
                    "period_seconds": round(avg_interval, 3),
                    "confidence": round(
                        1.0 - (max_interval - min_interval) / max_interval, 3
                    ),
                })

        return patterns

    def _analyze_type_frequencies(self) -> Dict[str, int]:
        """
        Analyze command type frequencies in the interaction history.

        Returns
        -------
        dict[str, int]
            Command type → occurrence count.
        """
        frequencies: Dict[str, int] = {}
        for cmd_type in self._command_sequence:
            frequencies[cmd_type] = frequencies.get(cmd_type, 0) + 1
        return frequencies

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "deployment_id": str(self.deployment_id),
            "model_version": self.learning_state.attacker_model_version,
            "model_accuracy": round(self.learning_state.model_accuracy, 4),
            "interaction_count": self.learning_state.interaction_history_size,
            "protocol_patterns": len(self._protocol_patterns),
            "topology_patterns": len(self._topology_patterns),
            "behavior_patterns": len(self._behavior_patterns),
            "command_sequence_length": len(self._command_sequence),
            "converged": (
                self.learning_state.model_accuracy >= HIGH_CONVERGENCE_THRESHOLD
            ),
            "prediction_cache_size": len(self._prediction_cache),
        }

    def __repr__(self) -> str:
        return (
            f"<RecursiveProjection deployment={self.deployment_id} "
            f"accuracy={self.learning_state.model_accuracy:.3f} "
            f"version={self.learning_state.attacker_model_version} "
            f"interactions={self.learning_state.interaction_history_size}>"
        )
