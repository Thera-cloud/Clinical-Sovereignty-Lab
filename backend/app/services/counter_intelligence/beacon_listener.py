"""
Exfiltration Beacon Listener — Monitors for retrieval seed activations
and canary token triggers.

Listening channels:
  DNS   – Queries to *.seed.sovereignsanctuary.net / *.canary.sovereignsanctuary.net
  HTTP  – GET /beacon/{canary_id} returns 1x1 transparent pixel, logs everything
  WS    – Seeds that attempt WebSocket connection for richer data

All activations are correlated back to the attacker profile via seed/canary ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger("counter_intelligence.beacon_listener")

# 1x1 transparent GIF (43 bytes)
TRANSPARENT_PIXEL = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00"
    b"\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
    b"\x44\x01\x00\x3b"
)


class BeaconActivation:
    """Records a single beacon/seed activation event."""

    __slots__ = (
        "activation_id", "canary_or_seed_id", "activation_type",
        "requester_ip", "requester_ua", "headers",
        "timestamp", "resolved_attacker_id",
    )

    def __init__(
        self,
        canary_or_seed_id: UUID,
        activation_type: str,
        requester_ip: str,
        requester_ua: str = "",
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        from uuid import uuid4

        self.activation_id = uuid4()
        self.canary_or_seed_id = canary_or_seed_id
        self.activation_type = activation_type
        self.requester_ip = requester_ip
        self.requester_ua = requester_ua
        self.headers = headers or {}
        self.timestamp = datetime.now(timezone.utc)
        self.resolved_attacker_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activation_id": str(self.activation_id),
            "canary_or_seed_id": str(self.canary_or_seed_id),
            "activation_type": self.activation_type,
            "requester_ip": self.requester_ip,
            "requester_ua": self.requester_ua,
            "headers": self.headers,
            "timestamp": self.timestamp.isoformat(),
            "resolved_attacker_id": self.resolved_attacker_id,
        }


class BeaconListener:
    """
    Central listener for all beacon/seed activations.
    Correlates activations back to attacker profiles.
    """

    def __init__(
        self,
        threat_db=None,
        canary_service=None,
        seed_crafter=None,
        reverse_mapper=None,
    ) -> None:
        self._threat_db = threat_db
        self._canary = canary_service
        self._seed_crafter = seed_crafter
        self._reverse_mapper = reverse_mapper
        self._activations: List[BeaconActivation] = []

    # ------------------------------------------------------------------
    # HTTP Beacon Handler
    # ------------------------------------------------------------------

    async def on_http_beacon(
        self,
        canary_id: str,
        requester_ip: str,
        requester_ua: str = "",
        headers: Optional[Dict[str, str]] = None,
    ) -> bytes:
        """
        Handle an HTTP beacon hit.
        Returns a 1x1 transparent GIF to the requester.
        Logs everything about the request.
        """
        try:
            beacon_uuid = UUID(canary_id)
        except (ValueError, AttributeError):
            logger.warning("Invalid beacon ID: %s", canary_id)
            return TRANSPARENT_PIXEL

        activation = BeaconActivation(
            canary_or_seed_id=beacon_uuid,
            activation_type="http_beacon",
            requester_ip=requester_ip,
            requester_ua=requester_ua,
            headers=headers,
        )
        self._activations.append(activation)

        # Notify canary service
        if self._canary:
            await self._canary.on_beacon_hit(
                beacon_uuid, requester_ip, requester_ua, headers,
            )

        # Notify seed crafter
        if self._seed_crafter:
            await self._seed_crafter.on_seed_activated(
                beacon_uuid,
                {
                    "type": "http_beacon",
                    "ip": requester_ip,
                    "ua": requester_ua,
                    "headers": headers or {},
                    "timestamp": activation.timestamp.isoformat(),
                },
            )

        # Feed to reverse mapper
        if self._reverse_mapper:
            await self._reverse_mapper.ingest_activation(activation)

        logger.warning(
            "HTTP BEACON HIT: %s from IP=%s UA=%s",
            canary_id, requester_ip, requester_ua,
        )

        return TRANSPARENT_PIXEL

    # ------------------------------------------------------------------
    # DNS Beacon Handler
    # ------------------------------------------------------------------

    async def on_dns_query(
        self, subdomain: str, resolver_ip: str,
    ) -> None:
        """
        Handle a DNS canary query.
        Called when a DNS query to *.canary.sovereignsanctuary.net or
        *.seed.sovereignsanctuary.net is detected.
        """
        # Try to resolve subdomain to a canary/seed ID
        if self._canary:
            await self._canary.on_dns_query(subdomain, resolver_ip)

        activation = BeaconActivation(
            canary_or_seed_id=UUID(int=0),  # Will be resolved later
            activation_type="dns_query",
            requester_ip=resolver_ip,
            requester_ua="dns-resolver",
            headers={"subdomain": subdomain},
        )
        self._activations.append(activation)

        # Feed to reverse mapper
        if self._reverse_mapper:
            await self._reverse_mapper.ingest_activation(activation)

        logger.warning(
            "DNS BEACON HIT: %s from resolver %s",
            subdomain, resolver_ip,
        )

    # ------------------------------------------------------------------
    # Intelligence Correlation
    # ------------------------------------------------------------------

    async def correlate_intelligence(
        self, attacker_id: str,
    ) -> Dict[str, Any]:
        """
        Correlate all beacon activations for a specific attacker.
        Returns aggregated intelligence.
        """
        related = [
            a for a in self._activations
            if a.resolved_attacker_id == attacker_id
        ]

        unique_ips = set()
        unique_uas = set()
        activation_types = set()

        for a in related:
            unique_ips.add(a.requester_ip)
            unique_uas.add(a.requester_ua)
            activation_types.add(a.activation_type)

        return {
            "attacker_id": attacker_id,
            "total_activations": len(related),
            "unique_ips": list(unique_ips),
            "unique_user_agents": list(unique_uas),
            "activation_types": list(activation_types),
            "activations": [a.to_dict() for a in related[-20:]],
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_activations": len(self._activations),
            "recent_activations": [
                a.to_dict() for a in self._activations[-10:]
            ],
        }
