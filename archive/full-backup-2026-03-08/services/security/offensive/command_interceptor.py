"""
HIVE DEFENSE PROTOCOL — Command Interceptor (Phase 8E)
Outbound command interception at PROTOCOL level.

The Command Interceptor identifies and captures attacker traffic by
protocol signature — not at the network level.  This ensures:
* **Zero collateral damage** — only the attacker's specific channels
  are affected.  Legitimate hive traffic passes through untouched.
* **Multi-channel support** — multiple simultaneous attacker channels
  can be registered and intercepted independently.
* **Protocol-level precision** — traffic is identified by the attacker's
  unique protocol fingerprint, not by IP address or port.

Patent-Pending — Claim 56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.command_interceptor")


# =============================================================================
# CHANNEL SPECIFICATION
# =============================================================================

class ChannelSpec:
    """
    Specification for a registered attacker communication channel.

    Attributes
    ----------
    channel_id : UUID
        Unique identifier for this channel.
    protocol_signature : str
        The protocol fingerprint that identifies traffic on this channel.
    protocol_markers : list[str]
        Ordered list of byte-level or string markers that identify the
        attacker's protocol in raw data.
    active : bool
        Whether this channel is currently being intercepted.
    """

    def __init__(
        self,
        protocol_signature: str,
        protocol_markers: Optional[List[str]] = None,
        *,
        channel_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.channel_id: UUID = channel_id or uuid4()
        self.protocol_signature: str = protocol_signature
        self.protocol_markers: List[str] = protocol_markers or []
        self.active: bool = True
        self.metadata: Dict[str, Any] = metadata or {}

        # Stats
        self.registered_at: datetime = datetime.utcnow()
        self.intercept_count: int = 0
        self.last_intercept_at: Optional[datetime] = None

    def matches(self, raw_data: Any) -> bool:
        """
        Determine whether raw data matches this channel's protocol signature.

        Parameters
        ----------
        raw_data:
            The raw data to inspect.  Can be ``str``, ``bytes``, or ``dict``.

        Returns
        -------
        bool
            ``True`` if the data matches this channel's protocol fingerprint.
        """
        data_str = self._normalize(raw_data)

        # Check signature match
        if self.protocol_signature and self.protocol_signature in data_str:
            return True

        # Check ordered markers
        if self.protocol_markers:
            last_pos = 0
            for marker in self.protocol_markers:
                pos = data_str.find(marker, last_pos)
                if pos == -1:
                    return False
                last_pos = pos + len(marker)
            return True

        return False

    @staticmethod
    def _normalize(raw_data: Any) -> str:
        """Normalise raw data to a string for pattern matching."""
        if isinstance(raw_data, bytes):
            try:
                return raw_data.decode("utf-8", errors="replace")
            except Exception:
                return raw_data.hex()
        elif isinstance(raw_data, dict):
            return str(raw_data)
        return str(raw_data)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a dictionary."""
        return {
            "channel_id": str(self.channel_id),
            "protocol_signature": self.protocol_signature,
            "protocol_markers": self.protocol_markers,
            "active": self.active,
            "registered_at": self.registered_at.isoformat(),
            "intercept_count": self.intercept_count,
            "last_intercept_at": (
                self.last_intercept_at.isoformat()
                if self.last_intercept_at
                else None
            ),
            "metadata": self.metadata,
        }


# =============================================================================
# COMMAND INTERCEPTOR — Patent Claim 56
# =============================================================================

class CommandInterceptor:
    """
    Outbound command interception at PROTOCOL level.

    Identifies attacker traffic by protocol signature and intercepts
    commands on registered channels — with zero collateral damage to
    legitimate hive operations.

    Supports multiple simultaneous attacker channels, each identified
    by a unique protocol fingerprint.

    Attributes
    ----------
    channels : dict[UUID, ChannelSpec]
        Registered attacker communication channels.
    total_intercepted : int
        Total commands intercepted across all channels.

    Usage
    -----
    ::

        interceptor = CommandInterceptor()
        interceptor.register_channel(ChannelSpec(
            protocol_signature="X-CNC-v2",
            protocol_markers=["BEGIN_CMD", "END_CMD"],
        ))
        is_attack = interceptor.is_attacker_traffic(raw_data)
        if is_attack:
            command, channel_id = await interceptor.intercept(raw_data)
    """

    def __init__(self) -> None:
        """Initialise the Command Interceptor with no registered channels."""
        self.channels: Dict[UUID, ChannelSpec] = {}

        # Global metrics
        self.total_intercepted: int = 0
        self.total_inspected: int = 0
        self.total_passed: int = 0

        # Interception log (recent)
        self._interception_log: List[Dict[str, Any]] = []
        self._max_log_size: int = 10000

        logger.info("CommandInterceptor initialised — zero channels registered")

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def register_channel(self, channel_spec: ChannelSpec) -> UUID:
        """
        Register an attacker communication channel for interception.

        Parameters
        ----------
        channel_spec:
            The channel specification describing the attacker's protocol.

        Returns
        -------
        UUID
            The channel ID (same as ``channel_spec.channel_id``).
        """
        self.channels[channel_spec.channel_id] = channel_spec

        logger.warning(
            "CommandInterceptor registered channel: id=%s "
            "signature='%s' markers=%d",
            channel_spec.channel_id,
            channel_spec.protocol_signature[:40],
            len(channel_spec.protocol_markers),
        )

        return channel_spec.channel_id

    def deregister_channel(self, channel_id: UUID) -> bool:
        """
        Deregister an attacker channel (stop interception).

        Parameters
        ----------
        channel_id:
            The channel to deregister.

        Returns
        -------
        bool
            ``True`` if the channel was found and removed.
        """
        if channel_id in self.channels:
            channel = self.channels.pop(channel_id)
            channel.active = False

            logger.warning(
                "CommandInterceptor deregistered channel: id=%s "
                "intercept_count=%d",
                channel_id,
                channel.intercept_count,
            )
            return True

        logger.warning(
            "CommandInterceptor deregister failed: channel %s not found",
            channel_id,
        )
        return False

    # ------------------------------------------------------------------
    # Traffic identification
    # ------------------------------------------------------------------

    def is_attacker_traffic(self, raw_data: Any) -> bool:
        """
        Identify whether raw data is attacker traffic by protocol signature.

        Checks all registered active channels.  Returns ``True`` on the
        first match.

        Parameters
        ----------
        raw_data:
            Raw data to inspect.

        Returns
        -------
        bool
            ``True`` if the data matches any registered attacker channel.
        """
        self.total_inspected += 1

        for channel in self.channels.values():
            if channel.active and channel.matches(raw_data):
                return True

        self.total_passed += 1
        return False

    def identify_channel(self, raw_data: Any) -> Optional[UUID]:
        """
        Identify which registered channel the raw data belongs to.

        Parameters
        ----------
        raw_data:
            Raw data to inspect.

        Returns
        -------
        UUID or None
            The channel ID if a match is found, otherwise ``None``.
        """
        for channel in self.channels.values():
            if channel.active and channel.matches(raw_data):
                return channel.channel_id
        return None

    # ------------------------------------------------------------------
    # Command interception
    # ------------------------------------------------------------------

    async def intercept(
        self,
        raw_data: Any,
    ) -> Tuple[Dict[str, Any], Optional[UUID]]:
        """
        Intercept an outbound command from the attacker.

        Identifies the channel, parses the command, updates metrics, and
        returns the parsed command with the originating channel ID.

        Parameters
        ----------
        raw_data:
            The raw outbound data to intercept.

        Returns
        -------
        tuple[dict, UUID | None]
            A 2-tuple of (intercepted_command, channel_id).  If the data
            does not match any channel, channel_id is ``None`` and the
            command dict contains only the raw data.
        """
        intercept_time = datetime.utcnow()

        # Identify the channel
        channel_id = self.identify_channel(raw_data)

        if channel_id is None:
            # Not attacker traffic — return unparsed
            return (
                {
                    "raw": str(raw_data)[:1024],
                    "intercepted": False,
                    "timestamp": intercept_time.isoformat(),
                },
                None,
            )

        channel = self.channels[channel_id]
        channel.intercept_count += 1
        channel.last_intercept_at = intercept_time
        self.total_intercepted += 1

        # Parse the raw data into a command structure
        command = self._parse_command(raw_data, channel)

        # Log the interception
        log_entry = {
            "intercept_number": self.total_intercepted,
            "channel_id": str(channel_id),
            "command_type": command.get("type", "unknown"),
            "command_hash": hashlib.sha256(
                str(raw_data).encode()
            ).hexdigest()[:16],
            "timestamp": intercept_time.isoformat(),
        }
        self._add_to_log(log_entry)

        logger.info(
            "CommandInterceptor intercepted command #%d on channel %s: "
            "type=%s",
            self.total_intercepted,
            channel_id,
            command.get("type", "unknown"),
        )

        return command, channel_id

    # ------------------------------------------------------------------
    # Command parsing
    # ------------------------------------------------------------------

    def _parse_command(
        self,
        raw_data: Any,
        channel: ChannelSpec,
    ) -> Dict[str, Any]:
        """
        Parse raw data into a structured command dictionary.

        Parameters
        ----------
        raw_data:
            The raw intercepted data.
        channel:
            The channel spec for context.

        Returns
        -------
        dict
            A structured command dictionary.
        """
        command: Dict[str, Any] = {
            "intercepted": True,
            "channel_id": str(channel.channel_id),
            "raw_hash": hashlib.sha256(
                str(raw_data).encode()
            ).hexdigest(),
            "timestamp": datetime.utcnow().isoformat(),
        }

        if isinstance(raw_data, dict):
            # Already structured — merge directly
            command.update(raw_data)
        elif isinstance(raw_data, (str, bytes)):
            data_str = (
                raw_data.decode("utf-8", errors="replace")
                if isinstance(raw_data, bytes)
                else raw_data
            )
            command["raw_payload"] = data_str[:4096]
            command["payload_length"] = len(data_str)
            # Attempt basic parsing
            command["type"] = self._infer_command_type(data_str, channel)
        else:
            command["raw_payload"] = str(raw_data)[:4096]
            command["type"] = "unknown"

        return command

    def _infer_command_type(
        self,
        data_str: str,
        channel: ChannelSpec,
    ) -> str:
        """
        Attempt to infer the command type from raw string data.

        Uses protocol markers and common command keywords.
        """
        data_lower = data_str.lower()
        type_keywords = {
            "exfil": ["exfil", "extract", "harvest", "dump"],
            "lateral": ["lateral", "pivot", "move", "spread"],
            "persist": ["persist", "implant", "install"],
            "scan": ["scan", "recon", "enumerate", "discover"],
            "beacon": ["beacon", "heartbeat", "checkin", "alive"],
            "execute": ["execute", "run", "shell", "cmd"],
        }

        for cmd_type, keywords in type_keywords.items():
            for keyword in keywords:
                if keyword in data_lower:
                    return cmd_type

        return "unknown"

    # ------------------------------------------------------------------
    # Interception log
    # ------------------------------------------------------------------

    def _add_to_log(self, entry: Dict[str, Any]) -> None:
        """Add an entry to the interception log, enforcing max size."""
        self._interception_log.append(entry)
        if len(self._interception_log) > self._max_log_size:
            self._interception_log = self._interception_log[
                -self._max_log_size :
            ]

    def get_interception_log(
        self,
        limit: int = 100,
        channel_id: Optional[UUID] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent interception log entries.

        Parameters
        ----------
        limit:
            Maximum entries to return.
        channel_id:
            Optional filter by channel.

        Returns
        -------
        list[dict]
            Recent interception log entries, newest first.
        """
        entries = self._interception_log
        if channel_id:
            cid = str(channel_id)
            entries = [e for e in entries if e.get("channel_id") == cid]
        return list(reversed(entries[-limit:]))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def active_channels(self) -> int:
        """Number of currently active channels."""
        return sum(1 for c in self.channels.values() if c.active)

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "active_channels": self.active_channels,
            "total_channels": len(self.channels),
            "total_intercepted": self.total_intercepted,
            "total_inspected": self.total_inspected,
            "total_passed": self.total_passed,
            "interception_rate": (
                round(self.total_intercepted / max(1, self.total_inspected), 4)
            ),
            "channels": {
                str(cid): ch.to_dict()
                for cid, ch in self.channels.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"<CommandInterceptor channels={self.active_channels} "
            f"intercepted={self.total_intercepted} "
            f"inspected={self.total_inspected}>"
        )
