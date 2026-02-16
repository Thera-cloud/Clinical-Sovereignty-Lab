"""
HIVE DEFENSE PROTOCOL — Attacker Behavior Mirror (Phase 8E)
Mirrors attacker's agent behavioral patterns.

The Behavior Mirror learns how the attacker's agents typically communicate
and generates acknowledgments in the agent's communication style.  It
adapts to different command types (exfiltration, lateral movement,
persistence, scanning) and produces responses that match the behavioral
fingerprint of the attacker's actual deployed agents.

The attacker's C&C sees its own agents responding normally.
Those agents are ours now.

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("hive.behavior_mirror")


# =============================================================================
# COMMAND TYPE CATEGORIES
# =============================================================================

COMMAND_CATEGORIES: Dict[str, List[str]] = {
    "exfil": ["exfil", "data_extract", "harvest", "collect", "dump"],
    "lateral": ["lateral", "lateral_move", "pivot", "spread", "move"],
    "persistence": ["persist", "persistence", "implant", "install", "hook"],
    "scan": ["scan", "recon", "enumerate", "discover", "probe"],
    "beacon": ["beacon", "heartbeat", "checkin", "alive", "ping"],
    "command": ["execute", "run", "shell", "cmd", "invoke"],
}


def _categorize_command(command_type: str) -> str:
    """Map a command type string to a behavioral category."""
    command_type_lower = command_type.lower()
    for category, keywords in COMMAND_CATEGORIES.items():
        if command_type_lower in keywords:
            return category
        for keyword in keywords:
            if keyword in command_type_lower:
                return category
    return "generic"


# =============================================================================
# ATTACKER BEHAVIOR MIRROR
# =============================================================================

class AttackerBehaviorMirror:
    """
    Mirrors the attacker's agent behavioral patterns.

    Generates responses that match how the attacker's agents typically
    behave — communication style, acknowledgment patterns, error reporting,
    and status update formats.

    Attributes
    ----------
    behavioral_profile : dict
        The learned behavioral profile from Penetrator intelligence.
    communication_style : str
        The agent's communication style (terse, verbose, structured, etc.).
    agent_personas : dict
        Per-agent behavioral profiles if multiple agent types are observed.

    Usage
    -----
    ::

        mirror = AttackerBehaviorMirror(behavioral_profile={
            "communication_style": "terse",
            "ack_delay_ms": 50,
            "error_rate": 0.02,
            ...
        })
        response = await mirror.reflect(attacker_command)
    """

    def __init__(
        self,
        behavioral_profile: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialise the Behavior Mirror from Penetrator intelligence.

        Parameters
        ----------
        behavioral_profile:
            Behavioral specification of the attacker's agents as extracted
            by the Penetrator.  Contains communication style, ack patterns,
            error rates, status update formats, and per-agent personas.
        """
        self.behavioral_profile: Dict[str, Any] = behavioral_profile or {}

        # Core behavioral parameters
        self.communication_style: str = self.behavioral_profile.get(
            "communication_style", "structured"
        )
        self._ack_delay_ms: float = self.behavioral_profile.get(
            "ack_delay_ms", 0.0
        )
        self._error_rate: float = self.behavioral_profile.get(
            "error_rate", 0.02
        )
        self._verbosity: str = self.behavioral_profile.get(
            "verbosity", "medium"
        )

        # Per-agent personas
        self.agent_personas: Dict[str, Dict[str, Any]] = (
            self.behavioral_profile.get("agent_personas", {})
        )

        # Command-type specific response templates
        self._response_templates: Dict[str, Dict[str, Any]] = (
            self.behavioral_profile.get("response_templates", {})
        )

        # Behavioral quirks observed in the attacker's agents
        self._quirks: List[str] = self.behavioral_profile.get("quirks", [])

        # Status vocabulary — words the attacker's agents use
        self._status_vocabulary: Dict[str, List[str]] = (
            self.behavioral_profile.get(
                "status_vocabulary",
                {
                    "success": ["ok", "done", "complete", "ack"],
                    "progress": ["working", "in_progress", "executing"],
                    "error": ["fail", "error", "timeout", "retry"],
                },
            )
        )

        # Metrics
        self._reflections: int = 0
        self._per_category_reflections: Dict[str, int] = {}

        logger.info(
            "AttackerBehaviorMirror initialised: style=%s verbosity=%s "
            "error_rate=%.3f personas=%d",
            self.communication_style,
            self._verbosity,
            self._error_rate,
            len(self.agent_personas),
        )

    # ------------------------------------------------------------------
    # Core reflection
    # ------------------------------------------------------------------

    async def reflect(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a behavioral reflection of the attacker's command.

        Returns a response that matches how the attacker's agents
        typically behave when executing this type of command.

        Parameters
        ----------
        command:
            The intercepted attacker command.

        Returns
        -------
        dict
            A response matching the attacker's agent behavioral patterns.
        """
        self._reflections += 1

        cmd_type = command.get("type", "unknown")
        category = _categorize_command(cmd_type)
        self._per_category_reflections[category] = (
            self._per_category_reflections.get(category, 0) + 1
        )

        # Determine which agent persona to use
        agent_id = command.get("agent_id", command.get("target_agent", "default"))
        persona = self._get_persona(agent_id)

        # Simulate occasional realistic errors
        if self._should_simulate_error():
            return self._generate_error_response(command, category, persona)

        # Generate the behavioral response
        response = self._generate_behavioral_response(command, category, persona)

        logger.debug(
            "BehaviorMirror reflected: type=%s category=%s agent=%s "
            "style=%s",
            cmd_type,
            category,
            agent_id,
            self.communication_style,
        )

        return response

    # ------------------------------------------------------------------
    # Behavioral learning
    # ------------------------------------------------------------------

    def update_behavioral_profile(self, updates: Dict[str, Any]) -> None:
        """
        Update the behavioral profile with new intelligence.

        Called by the RecursiveProjection when new behavioral patterns
        are learned from intercepted commands.

        Parameters
        ----------
        updates:
            Dictionary of behavioral profile updates to merge.
        """
        self.behavioral_profile.update(updates)

        if "communication_style" in updates:
            self.communication_style = updates["communication_style"]
        if "ack_delay_ms" in updates:
            self._ack_delay_ms = updates["ack_delay_ms"]
        if "error_rate" in updates:
            self._error_rate = updates["error_rate"]
        if "verbosity" in updates:
            self._verbosity = updates["verbosity"]
        if "agent_personas" in updates:
            self.agent_personas.update(updates["agent_personas"])
        if "response_templates" in updates:
            self._response_templates.update(updates["response_templates"])
        if "quirks" in updates:
            for quirk in updates["quirks"]:
                if quirk not in self._quirks:
                    self._quirks.append(quirk)
        if "status_vocabulary" in updates:
            for key, words in updates["status_vocabulary"].items():
                if key in self._status_vocabulary:
                    for word in words:
                        if word not in self._status_vocabulary[key]:
                            self._status_vocabulary[key].append(word)
                else:
                    self._status_vocabulary[key] = words

        logger.debug(
            "BehaviorMirror profile updated: %d keys", len(updates)
        )

    # ------------------------------------------------------------------
    # Response generation per command category
    # ------------------------------------------------------------------

    def _generate_behavioral_response(
        self,
        command: Dict[str, Any],
        category: str,
        persona: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a category-appropriate behavioral response.

        Parameters
        ----------
        command:
            The intercepted command.
        category:
            The categorised command type.
        persona:
            The agent persona to emulate.

        Returns
        -------
        dict
            Behavioral response.
        """
        # Check for a learned template first
        if category in self._response_templates:
            template = dict(self._response_templates[category])
            template["agent_id"] = command.get("agent_id", "agent-0")
            template["timestamp"] = datetime.utcnow().isoformat()
            return template

        # Generate from behavioral model
        generators = {
            "exfil": self._response_exfil,
            "lateral": self._response_lateral,
            "persistence": self._response_persistence,
            "scan": self._response_scan,
            "beacon": self._response_beacon,
            "command": self._response_command_exec,
        }

        generator = generators.get(category, self._response_generic)
        response = generator(command, persona)

        # Apply communication style
        response = self._apply_communication_style(response)

        # Apply behavioral quirks
        response = self._apply_quirks(response)

        return response

    def _response_exfil(
        self, command: Dict[str, Any], persona: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate exfiltration acknowledgment."""
        return {
            "ack_style": "data_transfer",
            "agent_status": "active",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {
                "bytes_sent": 0,
                "packets": 0,
                "channel": "encrypted",
                "complete": True,
            },
            "status_word": self._pick_status_word("success"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _response_lateral(
        self, command: Dict[str, Any], persona: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate lateral movement acknowledgment."""
        return {
            "ack_style": "pivot_report",
            "agent_status": "active",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {
                "new_position": command.get("target", "unknown"),
                "access_level": persona.get("default_access", "user"),
                "persistence": False,
                "stealth_maintained": True,
            },
            "status_word": self._pick_status_word("success"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _response_persistence(
        self, command: Dict[str, Any], persona: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate persistence installation acknowledgment."""
        return {
            "ack_style": "implant_status",
            "agent_status": "persistent",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {
                "method": persona.get("persistence_method", "service"),
                "location": "/var/lib/.hidden",
                "auto_start": True,
                "survival_reboot": True,
            },
            "status_word": self._pick_status_word("success"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _response_scan(
        self, command: Dict[str, Any], persona: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate scan/recon acknowledgment."""
        return {
            "ack_style": "scan_results",
            "agent_status": "active",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {
                "targets_scanned": 0,
                "hosts_alive": 0,
                "ports_open": [],
                "services_discovered": [],
            },
            "status_word": self._pick_status_word("success"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _response_beacon(
        self, command: Dict[str, Any], persona: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate beacon/heartbeat acknowledgment."""
        return {
            "ack_style": "heartbeat",
            "agent_status": "alive",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {
                "uptime_seconds": random.randint(3600, 86400),
                "cpu_usage": round(random.uniform(0.01, 0.15), 3),
                "memory_mb": random.randint(10, 64),
            },
            "status_word": self._pick_status_word("success"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _response_command_exec(
        self, command: Dict[str, Any], persona: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate command execution acknowledgment."""
        return {
            "ack_style": "exec_result",
            "agent_status": "active",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "execution_time_ms": random.randint(5, 500),
            },
            "status_word": self._pick_status_word("success"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _response_generic(
        self, command: Dict[str, Any], persona: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate a generic acknowledgment for unrecognised command types."""
        return {
            "ack_style": "standard",
            "agent_status": "active",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {},
            "status_word": self._pick_status_word("success"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Error simulation
    # ------------------------------------------------------------------

    def _should_simulate_error(self) -> bool:
        """
        Determine whether to simulate a realistic error.

        Real agents occasionally fail — a perfect 100% success rate would
        be suspicious.  This uses the learned error rate from the attacker's
        actual agent behavior.
        """
        return random.random() < self._error_rate

    def _generate_error_response(
        self,
        command: Dict[str, Any],
        category: str,
        persona: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a realistic error response.

        The error type is chosen to be plausible for the command category
        and matches the attacker's observed error reporting style.
        """
        error_types = {
            "exfil": "transfer_timeout",
            "lateral": "access_denied",
            "persistence": "write_permission_denied",
            "scan": "host_unreachable",
            "beacon": "temporary_disconnect",
            "command": "execution_failed",
        }

        error_type = error_types.get(category, "generic_error")

        return {
            "ack_style": "error",
            "agent_status": "error_recovery",
            "agent_id": command.get("agent_id", "agent-0"),
            "data_report": {
                "error_type": error_type,
                "retryable": True,
                "retry_after_ms": random.randint(1000, 5000),
            },
            "status_word": self._pick_status_word("error"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Style application
    # ------------------------------------------------------------------

    def _apply_communication_style(
        self,
        response: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply the attacker's observed communication style to the response.

        Styles
        ------
        * ``terse`` — minimal fields, short values
        * ``verbose`` — extra metadata, longer descriptions
        * ``structured`` — well-formatted with nested objects (default)
        * ``raw`` — flat key-value pairs
        """
        if self.communication_style == "terse":
            # Strip optional fields
            for key in ["timestamp", "data_report"]:
                if key in response and not response[key]:
                    del response[key]
        elif self.communication_style == "verbose":
            response["_meta"] = {
                "mirror_wall": "behavior",
                "style": "verbose",
                "generated_at": time.time_ns(),
            }
        elif self.communication_style == "raw":
            # Flatten nested data_report
            if "data_report" in response and isinstance(response["data_report"], dict):
                for k, v in response["data_report"].items():
                    response[f"data_{k}"] = v
                del response["data_report"]

        return response

    def _apply_quirks(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply observed behavioral quirks to the response.

        Quirks are unusual patterns observed in the attacker's agents
        (e.g. specific field ordering, extra null fields, custom headers).
        """
        for quirk in self._quirks:
            if quirk == "trailing_null":
                response["_padding"] = None
            elif quirk == "double_timestamp":
                response["ts"] = response.get("timestamp", "")
            elif quirk == "uppercase_status":
                if "status_word" in response:
                    response["status_word"] = response["status_word"].upper()
            elif quirk == "numeric_agent_id":
                agent_id = response.get("agent_id", "agent-0")
                try:
                    response["agent_id"] = int(
                        agent_id.replace("agent-", "")
                    )
                except (ValueError, AttributeError):
                    pass

        return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_persona(self, agent_id: str) -> Dict[str, Any]:
        """
        Retrieve the behavioral persona for a specific agent.

        Falls back to a default persona if the agent is unknown.
        """
        if agent_id in self.agent_personas:
            return self.agent_personas[agent_id]
        if "default" in self.agent_personas:
            return self.agent_personas["default"]
        return {
            "default_access": "user",
            "persistence_method": "service",
        }

    def _pick_status_word(self, category: str) -> str:
        """Pick a random status word from the learned vocabulary."""
        words = self._status_vocabulary.get(category, ["ok"])
        return random.choice(words) if words else "ok"

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "communication_style": self.communication_style,
            "verbosity": self._verbosity,
            "error_rate": self._error_rate,
            "personas": len(self.agent_personas),
            "quirks": len(self._quirks),
            "reflections": self._reflections,
            "per_category": dict(self._per_category_reflections),
        }

    def __repr__(self) -> str:
        return (
            f"<AttackerBehaviorMirror style={self.communication_style} "
            f"personas={len(self.agent_personas)} "
            f"reflections={self._reflections}>"
        )
