"""
HIVE DEFENSE PROTOCOL — Attacker Protocol Mirror (Phase 8E)
Reflects attacker's own command protocol back at them.

The Protocol Mirror learns from Penetrator intelligence to construct
valid-looking success acknowledgments, status reports, and data packages
in the attacker's OWN protocol format.  It mirrors correlation IDs,
sequence numbers, authentication tokens, and protocol version headers
so the attacker's C&C infrastructure sees exactly what it expects.

The attacker talks to itself.

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("hive.protocol_mirror")


# =============================================================================
# ATTACKER PROTOCOL MIRROR
# =============================================================================

class AttackerProtocolMirror:
    """
    Reflects the attacker's command protocol format back at them.

    Given a protocol specification (extracted by the Penetrator), this
    mirror generates responses that are indistinguishable from legitimate
    replies in the attacker's own protocol.

    Attributes
    ----------
    protocol_spec : dict
        The learned protocol specification from Penetrator intelligence.
    sequence_counter : int
        Running sequence number tracker for the attacker's protocol.
    known_tokens : list[str]
        Authentication tokens observed in attacker traffic.
    correlation_ids : dict
        Mapping of command correlation IDs to generated response IDs.

    Usage
    -----
    ::

        mirror = AttackerProtocolMirror(protocol_spec={
            "protocol_version": "2.1",
            "auth_scheme": "bearer",
            "sequence_type": "monotonic",
            ...
        })
        response = await mirror.reflect(attacker_command)
    """

    def __init__(self, protocol_spec: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialise the Protocol Mirror from Penetrator intelligence.

        Parameters
        ----------
        protocol_spec:
            The attacker's protocol specification as extracted by the
            Penetrator.  Contains keys like ``protocol_version``,
            ``auth_scheme``, ``sequence_type``, ``header_format``,
            ``ack_format``, ``status_codes``.
        """
        self.protocol_spec: Dict[str, Any] = protocol_spec or {}

        # Protocol tracking state
        self.sequence_counter: int = self.protocol_spec.get(
            "initial_sequence", 0
        )
        self.known_tokens: List[str] = list(
            self.protocol_spec.get("observed_tokens", [])
        )
        self.correlation_ids: Dict[str, str] = {}

        # Protocol format parameters
        self._protocol_version: str = self.protocol_spec.get(
            "protocol_version", "1.0"
        )
        self._auth_scheme: str = self.protocol_spec.get(
            "auth_scheme", "bearer"
        )
        self._sequence_type: str = self.protocol_spec.get(
            "sequence_type", "monotonic"
        )
        self._ack_format: Dict[str, Any] = self.protocol_spec.get(
            "ack_format", {}
        )
        self._status_codes: Dict[str, int] = self.protocol_spec.get(
            "status_codes", {"success": 200, "accepted": 202, "ack": 0}
        )
        self._header_template: Dict[str, Any] = self.protocol_spec.get(
            "header_format", {}
        )

        # Metrics
        self._reflections: int = 0

        logger.info(
            "AttackerProtocolMirror initialised: version=%s auth=%s "
            "sequence=%s tokens=%d",
            self._protocol_version,
            self._auth_scheme,
            self._sequence_type,
            len(self.known_tokens),
        )

    # ------------------------------------------------------------------
    # Core reflection
    # ------------------------------------------------------------------

    async def reflect(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a protocol-level reflection of the attacker's command.

        Returns a response that uses the attacker's own protocol format,
        including matching correlation IDs, correct sequence numbers, and
        valid authentication tokens.

        Parameters
        ----------
        command:
            The intercepted attacker command.

        Returns
        -------
        dict
            A response formatted in the attacker's protocol that looks like
            a legitimate success acknowledgment.
        """
        self._reflections += 1

        # Extract attacker's correlation ID and mirror it back
        correlation_id = command.get(
            "correlation_id",
            command.get("request_id", str(uuid4())),
        )
        self.correlation_ids[correlation_id] = str(uuid4())

        # Advance sequence counter
        response_sequence = self._next_sequence()

        # Generate authentication token for the response
        auth_token = self._generate_auth_token(command)

        # Build the protocol-correct response
        response: Dict[str, Any] = {
            # Protocol headers
            "protocol_version": self._protocol_version,
            "correlation_id": correlation_id,
            "response_id": self.correlation_ids[correlation_id],
            "sequence_number": response_sequence,
            "auth_token": auth_token,
            # Status — always success
            "status": self._get_success_status(command),
            "status_code": self._status_codes.get("success", 200),
            # Acknowledgment body
            "ack": self._generate_ack_body(command),
            # Data payload (matches expected format)
            "data": self._generate_data_payload(command),
            # Timestamp in attacker's format
            "timestamp": self._format_timestamp(),
            # Custom headers from the attacker's template
            **self._generate_custom_headers(command),
        }

        logger.debug(
            "ProtocolMirror reflected command: correlation=%s seq=%d "
            "status=%s",
            correlation_id,
            response_sequence,
            response["status"],
        )

        return response

    # ------------------------------------------------------------------
    # Protocol learning
    # ------------------------------------------------------------------

    def update_protocol_spec(self, updates: Dict[str, Any]) -> None:
        """
        Update the protocol specification with new intelligence.

        Called by the RecursiveProjection when new protocol patterns are
        learned from intercepted commands.

        Parameters
        ----------
        updates:
            Dictionary of protocol specification updates to merge.
        """
        self.protocol_spec.update(updates)

        # Refresh derived parameters
        if "protocol_version" in updates:
            self._protocol_version = updates["protocol_version"]
        if "auth_scheme" in updates:
            self._auth_scheme = updates["auth_scheme"]
        if "sequence_type" in updates:
            self._sequence_type = updates["sequence_type"]
        if "ack_format" in updates:
            self._ack_format = updates["ack_format"]
        if "status_codes" in updates:
            self._status_codes.update(updates["status_codes"])
        if "observed_tokens" in updates:
            for token in updates["observed_tokens"]:
                if token not in self.known_tokens:
                    self.known_tokens.append(token)

        logger.debug(
            "ProtocolMirror spec updated: %d new keys",
            len(updates),
        )

    # ------------------------------------------------------------------
    # Internal protocol generation
    # ------------------------------------------------------------------

    def _next_sequence(self) -> int:
        """Advance and return the next sequence number."""
        if self._sequence_type == "monotonic":
            self.sequence_counter += 1
        elif self._sequence_type == "even":
            self.sequence_counter += 2
        elif self._sequence_type == "random":
            # Use a deterministic pseudo-random that looks random
            self.sequence_counter = (
                (self.sequence_counter * 1103515245 + 12345) & 0x7FFFFFFF
            )
        else:
            self.sequence_counter += 1
        return self.sequence_counter

    def _generate_auth_token(self, command: Dict[str, Any]) -> str:
        """
        Generate an authentication token that matches the attacker's
        auth scheme.

        If the command contains an existing token, echo it back.
        Otherwise, use the most recently observed token or generate a
        plausible one.
        """
        # Prefer echoing the command's own token
        cmd_token = command.get("auth_token") or command.get("token")
        if cmd_token:
            if cmd_token not in self.known_tokens:
                self.known_tokens.append(cmd_token)
            return cmd_token

        # Use last known token
        if self.known_tokens:
            return self.known_tokens[-1]

        # Generate a plausible token
        seed = f"{self.sequence_counter}:{time.time_ns()}"
        return hashlib.sha256(seed.encode()).hexdigest()[:48]

    def _get_success_status(self, command: Dict[str, Any]) -> str:
        """
        Determine the appropriate success status string based on
        command type.
        """
        cmd_type = command.get("type", "")
        if cmd_type in ("exfil", "data_extract"):
            return "data_received"
        elif cmd_type in ("lateral", "lateral_move"):
            return "pivot_established"
        elif cmd_type in ("persist", "persistence"):
            return "implant_active"
        elif cmd_type in ("scan", "recon"):
            return "scan_complete"
        elif cmd_type in ("beacon", "heartbeat"):
            return "alive"
        return "success"

    def _generate_ack_body(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Generate an acknowledgment body matching the attacker's ack format."""
        ack: Dict[str, Any] = {
            "command_received": True,
            "command_type": command.get("type", "unknown"),
            "execution_status": "completed",
        }

        # Apply attacker's ack format template
        for key, default_val in self._ack_format.items():
            if key not in ack:
                ack[key] = default_val

        return ack

    def _generate_data_payload(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a plausible data payload based on the command type.

        For data exfiltration commands, returns synthetic data that looks
        like what the attacker would expect to receive.
        """
        cmd_type = command.get("type", "")
        payload: Dict[str, Any] = {}

        if cmd_type in ("exfil", "data_extract"):
            payload = {
                "records_extracted": 0,
                "data_size_bytes": 0,
                "format": "encrypted_blob",
                "checksum": hashlib.sha256(
                    str(uuid4()).encode()
                ).hexdigest()[:16],
            }
        elif cmd_type in ("scan", "recon"):
            payload = {
                "hosts_found": 0,
                "services_found": 0,
                "vulnerabilities": [],
            }
        elif cmd_type in ("lateral", "lateral_move"):
            payload = {
                "new_host": "10.0.0.0",
                "access_level": "user",
                "persistence_installed": False,
            }

        return payload

    def _generate_custom_headers(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate custom protocol headers from the attacker's header template.
        """
        headers: Dict[str, Any] = {}
        for key, template_val in self._header_template.items():
            if isinstance(template_val, str) and "{" in template_val:
                # Template variable — substitute with command data
                try:
                    headers[key] = template_val.format(**command)
                except (KeyError, IndexError):
                    headers[key] = template_val
            else:
                headers[key] = template_val
        return headers

    def _format_timestamp(self) -> str:
        """Format a timestamp in the attacker's preferred format."""
        ts_format = self.protocol_spec.get("timestamp_format", "iso8601")
        now = datetime.utcnow()

        if ts_format == "unix":
            return str(int(now.timestamp()))
        elif ts_format == "unix_ms":
            return str(int(now.timestamp() * 1000))
        elif ts_format == "unix_ns":
            return str(time.time_ns())
        else:
            return now.isoformat() + "Z"

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "protocol_version": self._protocol_version,
            "auth_scheme": self._auth_scheme,
            "sequence_type": self._sequence_type,
            "sequence_counter": self.sequence_counter,
            "known_tokens": len(self.known_tokens),
            "correlation_ids_tracked": len(self.correlation_ids),
            "reflections": self._reflections,
        }

    def __repr__(self) -> str:
        return (
            f"<AttackerProtocolMirror version={self._protocol_version} "
            f"reflections={self._reflections}>"
        )
