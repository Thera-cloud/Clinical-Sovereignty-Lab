"""
HIVE DEFENSE PROTOCOL — Attacker Behavioral Model (Phase 8E)
Comprehensive behavioral model built from Penetrator intelligence + recursive learning.

Tracks the attacker's complete operational profile: working hours, timezone,
response patterns, escalation triggers, team structure, tools, and targets.
Provides predictive capabilities for anticipating the attacker's next moves.

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import AttackerProfile

logger = logging.getLogger("hive.attacker_model")


# =============================================================================
# ATTACKER BEHAVIORAL MODEL
# =============================================================================

class AttackerBehavioralModel:
    """
    Comprehensive behavioral model of an attacker.

    Built from initial Penetrator intelligence and continuously refined
    through recursive learning as the Projected Helix intercepts commands.

    Tracks multiple dimensions of attacker behaviour:
    * **Temporal** — working hours, timezone, activity windows
    * **Operational** — command frequency, tool usage, target selection
    * **Communicative** — protocol patterns, response expectations, escalation
    * **Structural** — team size estimates, role differentiation, coordination

    Attributes
    ----------
    model_id : UUID
        Unique identifier for this model instance.
    attacker_profile : AttackerProfile
        The underlying Pydantic profile model.
    accuracy : float
        Current model accuracy estimate (0.0–1.0).
    total_ingested : int
        Total commands ingested for learning.

    Usage
    -----
    ::

        model = AttackerBehavioralModel(attacker_profile=profile)
        model.ingest(command, context={"source": "helix-42"})
        prediction = model.predict_expected_response(command)
        accuracy = model.get_model_accuracy()
        profile = model.get_operational_profile()
    """

    def __init__(
        self,
        attacker_profile: Optional[AttackerProfile] = None,
        *,
        model_id: Optional[UUID] = None,
    ) -> None:
        """
        Initialise the Attacker Behavioral Model.

        Parameters
        ----------
        attacker_profile:
            Initial attacker profile from Penetrator intelligence.
        model_id:
            Optional override for the model UUID.
        """
        self.model_id: UUID = model_id or uuid4()
        self.attacker_profile: AttackerProfile = attacker_profile or AttackerProfile()

        # Accuracy tracking
        self.accuracy: float = 0.7
        self.total_ingested: int = 0

        # ----- Temporal tracking -----
        self._command_timestamps: List[datetime] = []
        self._hour_distribution: Dict[int, int] = defaultdict(int)
        self._day_distribution: Dict[int, int] = defaultdict(int)
        self._timezone_votes: Dict[str, int] = defaultdict(int)

        # ----- Operational tracking -----
        self._command_types: Dict[str, int] = defaultdict(int)
        self._tool_usage: Dict[str, int] = defaultdict(int)
        self._target_frequency: Dict[str, int] = defaultdict(int)
        self._command_sequences: List[str] = []

        # ----- Response pattern tracking -----
        self._response_latencies: List[float] = []
        self._escalation_triggers: List[Dict[str, Any]] = []
        self._response_expectations: Dict[str, Dict[str, Any]] = {}

        # ----- Team structure tracking -----
        self._agent_ids_seen: set = set()
        self._agent_command_map: Dict[str, List[str]] = defaultdict(list)
        self._coordination_patterns: List[Dict[str, Any]] = []

        logger.info(
            "AttackerBehavioralModel initialised: model=%s "
            "initial_accuracy=%.3f",
            self.model_id,
            self.accuracy,
        )

    # ------------------------------------------------------------------
    # Learning — ingest commands
    # ------------------------------------------------------------------

    def ingest(
        self,
        command: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Learn from an intercepted command.

        Updates all model dimensions (temporal, operational, communicative,
        structural) based on the command and its context.

        Parameters
        ----------
        command:
            The intercepted attacker command.
        context:
            Optional context metadata (source helix, channel, etc.).

        Returns
        -------
        dict
            A learning summary with updated metrics.
        """
        self.total_ingested += 1
        context = context or {}
        now = datetime.utcnow()

        # Temporal learning
        self._learn_temporal(command, now)

        # Operational learning
        self._learn_operational(command)

        # Response pattern learning
        self._learn_response_patterns(command, context)

        # Team structure learning
        self._learn_team_structure(command)

        # Update accuracy
        self._update_accuracy()

        # Update the underlying profile
        self._sync_to_profile()

        logger.debug(
            "AttackerModel ingested command #%d: type=%s accuracy=%.3f",
            self.total_ingested,
            command.get("type", "unknown"),
            self.accuracy,
        )

        return {
            "ingested_count": self.total_ingested,
            "accuracy": round(self.accuracy, 4),
            "command_type": command.get("type", "unknown"),
            "unique_agents": len(self._agent_ids_seen),
            "command_types_known": len(self._command_types),
        }

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_expected_response(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Predict what the attacker expects to see in response to this command.

        Uses accumulated pattern knowledge to generate the most likely
        expected response structure, timing, and content.

        Parameters
        ----------
        command:
            The command to predict a response for.

        Returns
        -------
        dict
            Prediction containing expected response characteristics and
            confidence.
        """
        cmd_type = command.get("type", "unknown")
        confidence = self.accuracy

        # Check for learned response expectations
        if cmd_type in self._response_expectations:
            learned = self._response_expectations[cmd_type]
            return {
                "command_type": cmd_type,
                "confidence": round(confidence, 4),
                "expected_response": learned,
                "basis": "learned_from_history",
                "sample_size": self._command_types.get(cmd_type, 0),
            }

        # Generate prediction from patterns
        expected_latency = (
            statistics.mean(self._response_latencies)
            if self._response_latencies
            else 30.0
        )

        return {
            "command_type": cmd_type,
            "confidence": round(confidence, 4),
            "expected_response": {
                "status": "success",
                "expected_latency_ms": round(expected_latency, 2),
                "expected_data_format": self._infer_data_format(cmd_type),
                "expected_ack_style": self._infer_ack_style(cmd_type),
            },
            "basis": "pattern_inference",
            "sample_size": self._command_types.get(cmd_type, 0),
        }

    # ------------------------------------------------------------------
    # Accuracy
    # ------------------------------------------------------------------

    def get_model_accuracy(self) -> float:
        """
        Return the current model accuracy estimate.

        Accuracy is a composite score reflecting the breadth and depth of
        intelligence gathered:
        * Temporal coverage (working hours, timezone)
        * Operational coverage (command types, tools)
        * Response pattern coverage
        * Team structure knowledge

        Returns
        -------
        float
            Accuracy estimate between 0.0 and 1.0.
        """
        return round(self.accuracy, 4)

    def _update_accuracy(self) -> None:
        """
        Recalculate model accuracy based on accumulated intelligence.

        Accuracy grows with data but has diminishing returns.
        """
        # Base accuracy grows with ingestion count
        base = min(0.99, 0.7 + (self.total_ingested * 0.005))

        # Bonus for diversity of intelligence
        temporal_score = min(0.1, len(self._command_timestamps) * 0.001)
        operational_score = min(0.1, len(self._command_types) * 0.01)
        structural_score = min(0.05, len(self._agent_ids_seen) * 0.01)

        self.accuracy = min(0.99, base + temporal_score + operational_score + structural_score)

    # ------------------------------------------------------------------
    # Operational profile
    # ------------------------------------------------------------------

    def get_operational_profile(self) -> Dict[str, Any]:
        """
        Return the attacker's complete operational profile.

        Includes their playbook, tools, targets, team structure, working
        patterns, and escalation triggers.

        Returns
        -------
        dict
            Complete operational profile.
        """
        return {
            "model_id": str(self.model_id),
            "accuracy": round(self.accuracy, 4),
            "total_commands_analyzed": self.total_ingested,
            "playbook": {
                "command_types": dict(self._command_types),
                "command_sequence_length": len(self._command_sequences),
                "most_common_commands": self._get_top_n(self._command_types, 5),
            },
            "tools": {
                "observed_tools": dict(self._tool_usage),
                "tool_count": len(self._tool_usage),
                "sophistication_level": self.attacker_profile.sophistication_level,
            },
            "targets": {
                "targeted_assets": dict(self._target_frequency),
                "target_count": len(self._target_frequency),
                "most_targeted": self._get_top_n(self._target_frequency, 5),
            },
            "team_structure": {
                "unique_agents": len(self._agent_ids_seen),
                "agent_ids": list(self._agent_ids_seen),
                "agent_specializations": self._infer_agent_specializations(),
                "coordination_events": len(self._coordination_patterns),
            },
            "temporal_profile": {
                "working_hours": self._estimate_working_hours(),
                "timezone_estimate": self._estimate_timezone(),
                "active_days": dict(self._day_distribution),
                "hour_distribution": dict(self._hour_distribution),
                "total_activity_windows": len(self._command_timestamps),
            },
            "response_patterns": {
                "avg_latency_ms": (
                    round(statistics.mean(self._response_latencies), 2)
                    if self._response_latencies
                    else None
                ),
                "escalation_triggers": len(self._escalation_triggers),
            },
        }

    # ------------------------------------------------------------------
    # Internal learning methods
    # ------------------------------------------------------------------

    def _learn_temporal(self, command: Dict[str, Any], now: datetime) -> None:
        """Learn temporal patterns from command timing."""
        self._command_timestamps.append(now)
        self._hour_distribution[now.hour] += 1
        self._day_distribution[now.weekday()] += 1

        # Timezone estimation from command metadata
        if "timezone" in command:
            tz = command["timezone"]
            self._timezone_votes[tz] += 1
        elif "timestamp" in command:
            # Attempt to infer timezone from timestamp offset
            try:
                cmd_ts = command["timestamp"]
                if isinstance(cmd_ts, str) and ("+" in cmd_ts or "-" in cmd_ts[-6:]):
                    offset = cmd_ts[-6:]
                    self._timezone_votes[offset] += 1
            except Exception:
                pass

    def _learn_operational(self, command: Dict[str, Any]) -> None:
        """Learn operational patterns from command content."""
        cmd_type = command.get("type", "unknown")
        self._command_types[cmd_type] += 1
        self._command_sequences.append(cmd_type)

        # Tool usage
        tool = command.get("tool") or command.get("tool_signature")
        if tool:
            self._tool_usage[str(tool)] += 1

        # Target tracking
        target = command.get("target") or command.get("target_asset")
        if target:
            self._target_frequency[str(target)] += 1

    def _learn_response_patterns(
        self,
        command: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        """Learn response pattern expectations."""
        # Track latency if available in context
        latency = context.get("response_latency_ms")
        if latency is not None:
            self._response_latencies.append(float(latency))

        # Track escalation triggers
        if command.get("priority") in ("high", "urgent", "critical"):
            self._escalation_triggers.append({
                "command_type": command.get("type"),
                "priority": command["priority"],
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Update response expectations per command type
        cmd_type = command.get("type", "unknown")
        if "expected_response" in command:
            self._response_expectations[cmd_type] = command["expected_response"]

    def _learn_team_structure(self, command: Dict[str, Any]) -> None:
        """Learn team structure from agent IDs and coordination patterns."""
        agent_id = command.get("agent_id") or command.get("source_agent")
        if agent_id:
            self._agent_ids_seen.add(str(agent_id))
            cmd_type = command.get("type", "unknown")
            self._agent_command_map[str(agent_id)].append(cmd_type)

        # Detect coordination (multiple agents referenced in one command)
        agents_in_command = []
        for key in ("agent_id", "source_agent", "target_agent", "team"):
            if key in command:
                val = command[key]
                if isinstance(val, list):
                    agents_in_command.extend(str(v) for v in val)
                elif val:
                    agents_in_command.append(str(val))

        if len(agents_in_command) > 1:
            self._coordination_patterns.append({
                "agents": agents_in_command,
                "command_type": command.get("type"),
                "timestamp": datetime.utcnow().isoformat(),
            })

    # ------------------------------------------------------------------
    # Profile sync
    # ------------------------------------------------------------------

    def _sync_to_profile(self) -> None:
        """Synchronise accumulated intelligence back to the AttackerProfile."""
        self.attacker_profile.working_hours = self._estimate_working_hours()
        self.attacker_profile.timezone_estimate = self._estimate_timezone()
        self.attacker_profile.last_seen = datetime.utcnow()
        self.attacker_profile.active_channels = list(self._agent_ids_seen)

        # Update tool signatures
        for tool in self._tool_usage:
            if tool not in self.attacker_profile.tool_signatures:
                self.attacker_profile.tool_signatures.append(tool)

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------

    def _estimate_working_hours(self) -> Optional[str]:
        """Estimate the attacker's working hours from temporal distribution."""
        if not self._hour_distribution:
            return None

        # Find the most active 8-hour window
        hours = sorted(self._hour_distribution.items(), key=lambda x: -x[1])
        if not hours:
            return None

        peak_hours = [h for h, _ in hours[:8]]
        if peak_hours:
            start = min(peak_hours)
            end = max(peak_hours)
            return f"{start:02d}:00-{end:02d}:00 UTC"
        return None

    def _estimate_timezone(self) -> Optional[str]:
        """Estimate the attacker's timezone from collected votes."""
        if not self._timezone_votes:
            return None
        return max(self._timezone_votes, key=self._timezone_votes.get)

    def _infer_agent_specializations(self) -> Dict[str, str]:
        """
        Infer what each agent specialises in based on command patterns.

        Returns
        -------
        dict[str, str]
            Agent ID → inferred specialization.
        """
        specializations: Dict[str, str] = {}
        for agent_id, commands in self._agent_command_map.items():
            if not commands:
                continue
            # Most frequent command type for this agent
            freq: Dict[str, int] = defaultdict(int)
            for cmd in commands:
                freq[cmd] += 1
            most_common = max(freq, key=freq.get)
            specializations[agent_id] = most_common
        return specializations

    def _infer_data_format(self, cmd_type: str) -> str:
        """Infer expected data format for a command type."""
        format_map = {
            "exfil": "encrypted_blob",
            "scan": "host_list",
            "lateral": "pivot_report",
            "persist": "status_flag",
            "beacon": "health_report",
        }
        return format_map.get(cmd_type, "json")

    def _infer_ack_style(self, cmd_type: str) -> str:
        """Infer expected acknowledgment style for a command type."""
        style_map = {
            "exfil": "data_transfer",
            "scan": "scan_results",
            "lateral": "pivot_report",
            "persist": "implant_status",
            "beacon": "heartbeat",
        }
        return style_map.get(cmd_type, "standard")

    @staticmethod
    def _get_top_n(
        freq_map: Dict[str, int],
        n: int,
    ) -> List[Tuple[str, int]]:
        """Return the top N items by frequency."""
        return sorted(freq_map.items(), key=lambda x: -x[1])[:n]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "model_id": str(self.model_id),
            "accuracy": round(self.accuracy, 4),
            "total_ingested": self.total_ingested,
            "unique_command_types": len(self._command_types),
            "unique_agents": len(self._agent_ids_seen),
            "unique_tools": len(self._tool_usage),
            "unique_targets": len(self._target_frequency),
            "temporal_samples": len(self._command_timestamps),
            "escalation_triggers": len(self._escalation_triggers),
        }

    def __repr__(self) -> str:
        return (
            f"<AttackerBehavioralModel model={self.model_id} "
            f"accuracy={self.accuracy:.3f} "
            f"ingested={self.total_ingested} "
            f"agents={len(self._agent_ids_seen)}>"
        )
