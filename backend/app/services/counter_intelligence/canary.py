"""
Canary Token System — Embeds invisible tracking tokens at every data layer.

Token types:
  FRAGMENT  – Unique byte sequences in fragment payloads
  DNS       – Hostnames like {id}.canary.sovereignsanctuary.net
  WEB       – URLs like /beacon/{id} that log requesters
  WISDOM    – Fake insights with unique phrasing
  OBSERVATION – Unique UUIDs in decoy observation_id fields
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger("counter_intelligence.canary")


# =============================================================================
# CANARY TYPES
# =============================================================================

CANARY_TYPE_FRAGMENT = "fragment"
CANARY_TYPE_DNS = "dns"
CANARY_TYPE_WEB = "web"
CANARY_TYPE_WISDOM = "wisdom"
CANARY_TYPE_OBSERVATION = "observation"

# Base domains for canary callbacks
CANARY_DNS_DOMAIN = "canary.sovereignsanctuary.net"
CANARY_BEACON_BASE = "https://api.sovereignsanctuary.net/beacon"


class CanaryToken:
    """Represents a single deployed canary token."""

    __slots__ = (
        "canary_id", "canary_type", "target_attacker",
        "payload", "callback_url", "deployed_at",
        "triggered", "trigger_data",
    )

    def __init__(
        self,
        canary_type: str,
        target_attacker: Optional[str] = None,
        payload: Optional[bytes] = None,
        callback_url: Optional[str] = None,
    ) -> None:
        self.canary_id = uuid4()
        self.canary_type = canary_type
        self.target_attacker = target_attacker
        self.payload = payload
        self.callback_url = callback_url
        self.deployed_at = datetime.now(timezone.utc)
        self.triggered = False
        self.trigger_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canary_id": str(self.canary_id),
            "canary_type": self.canary_type,
            "target_attacker": self.target_attacker,
            "callback_url": self.callback_url,
            "deployed_at": self.deployed_at.isoformat(),
            "triggered": self.triggered,
        }


class CanaryTokenService:
    """
    Generates and tracks canary tokens embedded in decoy data.
    """

    def __init__(self, threat_db=None, base_url: Optional[str] = None) -> None:
        self._threat_db = threat_db
        self._base_url = base_url or CANARY_BEACON_BASE
        # In-memory registry for fast lookup
        self._tokens: Dict[UUID, CanaryToken] = {}
        self._dns_lookup: Dict[str, UUID] = {}  # subdomain → canary_id

    # ------------------------------------------------------------------
    # Token Generation
    # ------------------------------------------------------------------

    async def generate_fragment_canary(
        self, target_attacker: Optional[str] = None,
    ) -> bytes:
        """
        Generate a unique byte sequence for embedding in fragment payloads.
        Returns 4 bytes that act as a canary.
        """
        canary = CanaryToken(
            canary_type=CANARY_TYPE_FRAGMENT,
            target_attacker=target_attacker,
        )
        # Generate unique 4-byte payload from canary ID
        payload = hashlib.sha256(
            canary.canary_id.bytes
        ).digest()[:4]
        canary.payload = payload

        self._tokens[canary.canary_id] = canary

        if self._threat_db:
            payload_hash = hashlib.sha256(payload).hexdigest()[:16]
            await self._threat_db.register_canary(
                canary_id=canary.canary_id,
                canary_type=CANARY_TYPE_FRAGMENT,
                target_attacker=UUID(target_attacker)
                if target_attacker and len(target_attacker) == 36
                else None,
                payload_hash=payload_hash,
            )

        return payload

    async def generate_dns_canary(
        self,
        context: str = "default",
        target_attacker: Optional[str] = None,
    ) -> str:
        """
        Generate a DNS canary hostname.
        When resolved, reveals the resolver's IP.

        Returns: {unique-id}.canary.sovereignsanctuary.net
        """
        canary = CanaryToken(
            canary_type=CANARY_TYPE_DNS,
            target_attacker=target_attacker,
        )
        subdomain = canary.canary_id.hex[:16]
        hostname = f"{subdomain}.{CANARY_DNS_DOMAIN}"
        canary.callback_url = hostname

        self._tokens[canary.canary_id] = canary
        self._dns_lookup[subdomain] = canary.canary_id

        if self._threat_db:
            await self._threat_db.register_canary(
                canary_id=canary.canary_id,
                canary_type=CANARY_TYPE_DNS,
                target_attacker=UUID(target_attacker)
                if target_attacker and len(target_attacker) == 36
                else None,
                payload_hash=subdomain,
            )

        logger.debug("DNS canary deployed: %s", hostname)
        return hostname

    async def generate_web_beacon(
        self,
        context: str = "default",
        target_attacker: Optional[str] = None,
    ) -> str:
        """
        Generate a web beacon URL.
        When fetched, logs the requester's IP, UA, headers.

        Returns: https://api.sovereignsanctuary.net/beacon/{canary_id}
        """
        canary = CanaryToken(
            canary_type=CANARY_TYPE_WEB,
            target_attacker=target_attacker,
        )
        beacon_url = f"{self._base_url}/{canary.canary_id}"
        canary.callback_url = beacon_url

        self._tokens[canary.canary_id] = canary

        if self._threat_db:
            await self._threat_db.register_canary(
                canary_id=canary.canary_id,
                canary_type=CANARY_TYPE_WEB,
                target_attacker=UUID(target_attacker)
                if target_attacker and len(target_attacker) == 36
                else None,
                payload_hash=str(canary.canary_id),
            )

        logger.debug("Web beacon deployed: %s", beacon_url)
        return beacon_url

    async def generate_wisdom_canary(
        self,
        target_attacker: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate a fake wisdom insight with unique phrasing.
        If this phrasing appears elsewhere, the data was exfiltrated.

        Returns: {"title": ..., "body": ..., "canary_id": ...}
        """
        canary = CanaryToken(
            canary_type=CANARY_TYPE_WISDOM,
            target_attacker=target_attacker,
        )
        # Unique marker phrase that won't appear naturally
        marker = f"paradigm-{canary.canary_id.hex[:8]}"
        insight = {
            "title": f"Coherence Optimization: {marker} Protocol",
            "body": (
                f"The {marker} method demonstrates a novel approach to "
                f"emotional coherence measurement through quantum-entangled "
                f"biometric feedback. Internal reference: {marker}."
            ),
            "canary_id": str(canary.canary_id),
        }

        self._tokens[canary.canary_id] = canary

        if self._threat_db:
            await self._threat_db.register_canary(
                canary_id=canary.canary_id,
                canary_type=CANARY_TYPE_WISDOM,
                target_attacker=UUID(target_attacker)
                if target_attacker and len(target_attacker) == 36
                else None,
                payload_hash=marker,
            )

        return insight

    # ------------------------------------------------------------------
    # Deployment (batch canary generation for an attacker)
    # ------------------------------------------------------------------

    async def deploy_canaries(
        self, attacker_id: str, attack_type: str,
    ) -> Dict[str, Any]:
        """
        Deploy a full set of canaries targeting an attacker.
        Returns deployed canary metadata.
        """
        fragment_payload = await self.generate_fragment_canary(attacker_id)
        dns_hostname = await self.generate_dns_canary(
            context=attack_type, target_attacker=attacker_id,
        )
        web_beacon = await self.generate_web_beacon(
            context=attack_type, target_attacker=attacker_id,
        )
        wisdom = await self.generate_wisdom_canary(attacker_id)

        logger.info(
            "Deployed canary suite for attacker %s: dns=%s web=%s",
            attacker_id, dns_hostname, web_beacon,
        )

        return {
            "fragment_canary_size": len(fragment_payload),
            "dns_canary": dns_hostname,
            "web_beacon": web_beacon,
            "wisdom_canary_id": wisdom["canary_id"],
        }

    # ------------------------------------------------------------------
    # Trigger Detection
    # ------------------------------------------------------------------

    async def check_canary_triggered(
        self, canary_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Check if a specific canary has been triggered."""
        token = self._tokens.get(canary_id)
        if token and token.triggered:
            return {
                "canary_id": str(canary_id),
                "triggered": True,
                "trigger_data": token.trigger_data,
            }
        return None

    async def on_beacon_hit(
        self,
        canary_id: UUID,
        requester_ip: str,
        requester_ua: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a web beacon or DNS canary being triggered."""
        token = self._tokens.get(canary_id)
        if token:
            token.triggered = True
            token.trigger_data = {
                "requester_ip": requester_ip,
                "requester_ua": requester_ua,
                "headers": headers or {},
                "triggered_at": datetime.now(timezone.utc).isoformat(),
            }

        if self._threat_db:
            await self._threat_db.trigger_canary(
                canary_id,
                {
                    "requester_ip": requester_ip,
                    "requester_ua": requester_ua,
                    "headers": headers or {},
                },
            )

        logger.warning(
            "CANARY TRIGGERED: %s from IP %s UA %s",
            canary_id, requester_ip, requester_ua,
        )

    async def on_dns_query(
        self, subdomain: str, resolver_ip: str,
    ) -> None:
        """Handle a DNS query to a canary subdomain."""
        canary_id = self._dns_lookup.get(subdomain)
        if canary_id:
            await self.on_beacon_hit(
                canary_id, resolver_ip, "dns-resolver",
                headers={"query_type": "dns", "subdomain": subdomain},
            )

    # ------------------------------------------------------------------
    # Embed canaries into decoy data
    # ------------------------------------------------------------------

    async def embed_canaries_in_decoy(
        self, decoy_data: Dict[str, Any], attacker_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Embed canary tokens into a decoy data structure.
        Modifies in place and returns the data.
        """
        dns = await self.generate_dns_canary(target_attacker=attacker_id)
        web = await self.generate_web_beacon(target_attacker=attacker_id)

        # Embed in common fields
        decoy_data["_internal_ref"] = dns
        decoy_data["_documentation_url"] = web

        return decoy_data
