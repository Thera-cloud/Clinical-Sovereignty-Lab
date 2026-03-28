"""
Retrieval Seed Crafter — Constructs payloads designed to ride the attacker's
exfiltration path back to their infrastructure.

Seed types:
  DNS         – Hostname that triggers DNS lookup when parsed
  HTTP        – URL that fetches tracking pixel when opened
  TIMING      – Computation pattern creating detectable timing signature
  FINGERPRINT – Markup that collects browser fingerprint if rendered
  CASCADE     – Self-replicating seed that maps deeper into attacker pipeline
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger("counter_intelligence.retrieval_seed")

# Base domains for seed callbacks
SEED_DNS_DOMAIN = "seed.sovereignsanctuary.net"
SEED_BEACON_BASE = "https://api.sovereignsanctuary.net/beacon"


class SeedType(str, Enum):
    DNS = "dns"
    HTTP = "http"
    TIMING = "timing"
    FINGERPRINT = "fingerprint"
    CASCADE = "cascade"


class RetrievalSeed:
    """A single retrieval seed designed to map attacker infrastructure."""

    __slots__ = (
        "seed_id", "seed_type", "target_attacker", "payload",
        "tracking_endpoint", "created_at", "activation_count",
        "intelligence_gathered", "deployed_via",
    )

    def __init__(
        self,
        seed_type: SeedType,
        target_attacker: Optional[str] = None,
        payload: Optional[bytes] = None,
        tracking_endpoint: Optional[str] = None,
    ) -> None:
        self.seed_id = uuid4()
        self.seed_type = seed_type
        self.target_attacker = target_attacker
        self.payload = payload or b""
        self.tracking_endpoint = tracking_endpoint or ""
        self.created_at = datetime.now(timezone.utc)
        self.activation_count = 0
        self.intelligence_gathered: List[Dict[str, Any]] = []
        self.deployed_via: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed_id": str(self.seed_id),
            "seed_type": self.seed_type.value,
            "target_attacker": self.target_attacker,
            "tracking_endpoint": self.tracking_endpoint,
            "created_at": self.created_at.isoformat(),
            "activation_count": self.activation_count,
            "deployed_via": self.deployed_via,
        }


class RetrievalSeedCrafter:
    """
    Crafts retrieval seeds tailored to specific attacker profiles.
    Seeds are designed to pass the attacker's collection filters and
    activate when processed.
    """

    def __init__(self, threat_db=None, canary_service=None) -> None:
        self._threat_db = threat_db
        self._canary = canary_service
        self._seeds: Dict[UUID, RetrievalSeed] = {}

    # ------------------------------------------------------------------
    # Seed Generation
    # ------------------------------------------------------------------

    async def craft_dns_seed(
        self, target_attacker: Optional[str] = None,
    ) -> RetrievalSeed:
        """
        Craft a DNS seed.  When the attacker's system parses the data and
        encounters the hostname, a DNS query reveals their resolver IP.
        """
        seed = RetrievalSeed(
            seed_type=SeedType.DNS,
            target_attacker=target_attacker,
        )
        subdomain = seed.seed_id.hex[:16]
        hostname = f"{subdomain}.{SEED_DNS_DOMAIN}"
        seed.tracking_endpoint = hostname

        # Payload: embed the hostname in a JSON-like structure that
        # an automated system might parse and resolve
        payload = json.dumps({
            "source": f"https://{hostname}/api/v1/health",
            "webhook": f"https://{hostname}/callback",
            "documentation": f"https://{hostname}/docs",
        }).encode()
        seed.payload = payload

        self._seeds[seed.seed_id] = seed

        if self._threat_db:
            attacker_uuid = None
            if target_attacker and len(target_attacker) == 36:
                try:
                    attacker_uuid = UUID(target_attacker)
                except ValueError:
                    pass
            await self._threat_db.register_seed(
                seed.seed_id, SeedType.DNS.value,
                target_attacker=attacker_uuid, deployed_via="ble",
            )

        return seed

    async def craft_http_seed(
        self, target_attacker: Optional[str] = None,
    ) -> RetrievalSeed:
        """
        Craft an HTTP seed.  When the attacker opens/renders the data,
        the embedded URL fetches a tracking pixel revealing their IP.
        """
        seed = RetrievalSeed(
            seed_type=SeedType.HTTP,
            target_attacker=target_attacker,
        )
        beacon_url = f"{SEED_BEACON_BASE}/{seed.seed_id}"
        seed.tracking_endpoint = beacon_url

        # Embed as various formats an automated system might follow
        payload = json.dumps({
            "image": beacon_url + "/pixel.png",
            "stylesheet": beacon_url + "/style.css",
            "config_endpoint": beacon_url + "/config.json",
        }).encode()
        seed.payload = payload

        self._seeds[seed.seed_id] = seed

        if self._threat_db:
            attacker_uuid = None
            if target_attacker and len(target_attacker) == 36:
                try:
                    attacker_uuid = UUID(target_attacker)
                except ValueError:
                    pass
            await self._threat_db.register_seed(
                seed.seed_id, SeedType.HTTP.value,
                target_attacker=attacker_uuid, deployed_via="honeypot",
            )

        return seed

    async def craft_timing_seed(
        self, target_attacker: Optional[str] = None,
    ) -> RetrievalSeed:
        """
        Craft a timing seed.  Contains a unique computation pattern that,
        when processed, creates a detectable timing signature.
        """
        seed = RetrievalSeed(
            seed_type=SeedType.TIMING,
            target_attacker=target_attacker,
        )

        # Create a payload that takes measurable time to process
        # (nested hash chains with a unique pattern)
        core = seed.seed_id.bytes
        chain = core
        for i in range(100):
            chain = hashlib.sha256(chain + core).digest()

        seed.payload = chain
        seed.tracking_endpoint = f"timing:{seed.seed_id.hex[:16]}"

        self._seeds[seed.seed_id] = seed
        return seed

    async def craft_fingerprint_seed(
        self, target_attacker: Optional[str] = None,
    ) -> RetrievalSeed:
        """
        Craft a fingerprint seed.  Contains markup that, if rendered
        in a browser, collects fingerprint data and reports back.
        """
        seed = RetrievalSeed(
            seed_type=SeedType.FINGERPRINT,
            target_attacker=target_attacker,
        )
        beacon_url = f"{SEED_BEACON_BASE}/{seed.seed_id}"

        # Minimal HTML/JS that collects navigator info
        markup = (
            f'<img src="{beacon_url}/fp.png?t=' + '{ts}" '
            f'onerror="new Image().src=\'{beacon_url}/e?'
            f'ua=\'+navigator.userAgent+\'&p=\'+navigator.platform">'
        ).replace("{ts}", "'+Date.now()+'")

        seed.payload = markup.encode()
        seed.tracking_endpoint = beacon_url

        self._seeds[seed.seed_id] = seed

        if self._threat_db:
            attacker_uuid = None
            if target_attacker and len(target_attacker) == 36:
                try:
                    attacker_uuid = UUID(target_attacker)
                except ValueError:
                    pass
            await self._threat_db.register_seed(
                seed.seed_id, SeedType.FINGERPRINT.value,
                target_attacker=attacker_uuid, deployed_via="honeypot",
            )

        return seed

    async def craft_cascade_seed(
        self, target_attacker: Optional[str] = None,
    ) -> RetrievalSeed:
        """
        Craft a cascade seed.  Once inside the attacker's system, it
        generates child seeds that each phone home independently,
        mapping deeper into the processing pipeline.
        """
        seed = RetrievalSeed(
            seed_type=SeedType.CASCADE,
            target_attacker=target_attacker,
        )
        beacon_url = f"{SEED_BEACON_BASE}/{seed.seed_id}"

        # JSON structure with multiple callback URLs at different depths
        cascade = {
            "level_0": beacon_url + "/L0",
            "processing": {
                "level_1": beacon_url + "/L1",
                "analysis": {
                    "level_2": beacon_url + "/L2",
                    "deep_scan": {
                        "level_3": beacon_url + "/L3",
                    },
                },
            },
            "export": {
                "webhook": beacon_url + "/export",
                "backup": beacon_url + "/backup",
            },
        }

        seed.payload = json.dumps(cascade).encode()
        seed.tracking_endpoint = beacon_url

        self._seeds[seed.seed_id] = seed

        if self._threat_db:
            attacker_uuid = None
            if target_attacker and len(target_attacker) == 36:
                try:
                    attacker_uuid = UUID(target_attacker)
                except ValueError:
                    pass
            await self._threat_db.register_seed(
                seed.seed_id, SeedType.CASCADE.value,
                target_attacker=attacker_uuid, deployed_via="ble",
            )

        return seed

    # ------------------------------------------------------------------
    # Batch Crafting for Attacker
    # ------------------------------------------------------------------

    async def craft_for_attacker(
        self, attacker_id: str, attack_type: str = "unknown",
    ) -> List[RetrievalSeed]:
        """
        Craft a full suite of retrieval seeds for a specific attacker.
        """
        seeds = []

        # Always deploy DNS + HTTP seeds
        seeds.append(await self.craft_dns_seed(attacker_id))
        seeds.append(await self.craft_http_seed(attacker_id))

        # Add timing seed for sophisticated attackers
        seeds.append(await self.craft_timing_seed(attacker_id))

        # Add fingerprint seed if attack involves web/API
        if attack_type in ("injection", "spoofing", "apt"):
            seeds.append(await self.craft_fingerprint_seed(attacker_id))

        # Add cascade seed for APT-level threats
        if attack_type == "apt":
            seeds.append(await self.craft_cascade_seed(attacker_id))

        logger.info(
            "Crafted %d retrieval seeds for attacker %s (type=%s)",
            len(seeds), attacker_id, attack_type,
        )

        return seeds

    # ------------------------------------------------------------------
    # Seed Activation Tracking
    # ------------------------------------------------------------------

    async def on_seed_activated(
        self, seed_id: UUID, intelligence: Dict[str, Any],
    ) -> None:
        """Record activation of a retrieval seed."""
        seed = self._seeds.get(seed_id)
        if seed:
            seed.activation_count += 1
            seed.intelligence_gathered.append(intelligence)

        if self._threat_db:
            await self._threat_db.record_seed_activation(seed_id, intelligence)

        logger.warning(
            "SEED ACTIVATED: %s (type=%s, activations=%d)",
            seed_id,
            seed.seed_type.value if seed else "unknown",
            seed.activation_count if seed else 0,
        )

    def get_seed(self, seed_id: UUID) -> Optional[RetrievalSeed]:
        """Get a seed by ID."""
        return self._seeds.get(seed_id)

    def get_all_seeds(self) -> List[Dict[str, Any]]:
        """Return all deployed seeds."""
        return [s.to_dict() for s in self._seeds.values()]
