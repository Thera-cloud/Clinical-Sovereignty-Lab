"""
Reverse Mapper — Assembles all intelligence from beacon activations,
seed callbacks, canary triggers, and fingerprint data into a unified
AttackerInfrastructureMap.

The map reveals:
  - Physical BLE locations (RSSI triangulation)
  - Network infrastructure (IPs, DNS resolvers)
  - Processing pipeline (delay analysis, stage estimation)
  - Temporal patterns (active hours, campaign duration)
  - Automation level (manual vs fully automated)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

logger = logging.getLogger("counter_intelligence.reverse_mapper")


class GeoLocation:
    """Estimated geographic location from IP geolocation."""

    __slots__ = ("ip", "city", "country", "lat", "lon", "confidence")

    def __init__(
        self,
        ip: str,
        city: str = "unknown",
        country: str = "unknown",
        lat: float = 0.0,
        lon: float = 0.0,
        confidence: float = 0.0,
    ) -> None:
        self.ip = ip
        self.city = city
        self.country = country
        self.lat = lat
        self.lon = lon
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ip": self.ip,
            "city": self.city,
            "country": self.country,
            "lat": self.lat,
            "lon": self.lon,
            "confidence": self.confidence,
        }


class BLELocationEstimate:
    """Estimated physical location from BLE RSSI triangulation."""

    __slots__ = ("device_id", "rssi", "estimated_distance_m", "timestamp")

    def __init__(
        self, device_id: str, rssi: int, timestamp: float,
    ) -> None:
        self.device_id = device_id
        self.rssi = rssi
        self.timestamp = timestamp
        # Rough distance estimate from RSSI (free-space path loss model)
        # d = 10^((TxPower - RSSI) / (10 * n))
        # Assuming TxPower=-59 dBm, n=2 (free space)
        tx_power = -59
        n = 2.0
        self.estimated_distance_m = round(
            10 ** ((tx_power - rssi) / (10 * n)), 1
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "rssi": self.rssi,
            "estimated_distance_m": self.estimated_distance_m,
            "timestamp": self.timestamp,
        }


class AttackerInfrastructureMap:
    """
    Complete map of an attacker's infrastructure assembled from
    all intelligence sources.
    """

    def __init__(self, attacker_id: str) -> None:
        self.attacker_id = attacker_id
        self.last_updated = datetime.now(timezone.utc)

        # Physical presence
        self.ble_locations: List[BLELocationEstimate] = []
        self.physical_proximity_history: List[Tuple[float, float]] = []

        # Network infrastructure
        self.ip_addresses: Set[str] = set()
        self.dns_resolvers: Set[str] = set()
        self.geographic_estimates: List[GeoLocation] = []

        # Processing pipeline analysis
        self.processing_delays: List[float] = []  # seconds
        self.pipeline_stages: int = 0
        self.automation_level: float = 0.0

        # Temporal patterns
        self.active_hours: Dict[int, int] = defaultdict(int)  # hour → count
        self.first_activity: Optional[datetime] = None
        self.last_activity: Optional[datetime] = None

        # Seed/canary activation tracking
        self.seed_activations: int = 0
        self.canary_triggers: int = 0

    @property
    def campaign_duration(self) -> Optional[timedelta]:
        if self.first_activity and self.last_activity:
            return self.last_activity - self.first_activity
        return None

    @property
    def avg_processing_delay(self) -> float:
        if self.processing_delays:
            return sum(self.processing_delays) / len(self.processing_delays)
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attacker_id": self.attacker_id,
            "last_updated": self.last_updated.isoformat(),
            "physical": {
                "ble_locations": [l.to_dict() for l in self.ble_locations[-10:]],
                "proximity_history_count": len(self.physical_proximity_history),
            },
            "network": {
                "ip_addresses": list(self.ip_addresses),
                "dns_resolvers": list(self.dns_resolvers),
                "geographic_estimates": [
                    g.to_dict() for g in self.geographic_estimates
                ],
            },
            "pipeline": {
                "avg_processing_delay_s": round(self.avg_processing_delay, 2),
                "pipeline_stages": self.pipeline_stages,
                "automation_level": round(self.automation_level, 2),
            },
            "temporal": {
                "active_hours": dict(self.active_hours),
                "campaign_duration_hours": (
                    self.campaign_duration.total_seconds() / 3600
                    if self.campaign_duration else 0
                ),
                "first_activity": (
                    self.first_activity.isoformat()
                    if self.first_activity else None
                ),
                "last_activity": (
                    self.last_activity.isoformat()
                    if self.last_activity else None
                ),
            },
            "counters": {
                "seed_activations": self.seed_activations,
                "canary_triggers": self.canary_triggers,
            },
        }


class ReverseMapper:
    """
    Assembles AttackerInfrastructureMaps from all intelligence sources.
    """

    def __init__(self, threat_db=None, fingerprinter=None) -> None:
        self._threat_db = threat_db
        self._fingerprinter = fingerprinter
        self._maps: Dict[str, AttackerInfrastructureMap] = {}

    # ------------------------------------------------------------------
    # Intelligence Ingestion
    # ------------------------------------------------------------------

    async def ingest_activation(self, activation) -> None:
        """
        Ingest a beacon/seed activation and update the infrastructure map.
        """
        # Resolve to attacker ID via fingerprinter
        attacker_id = getattr(activation, "resolved_attacker_id", None)
        if not attacker_id:
            # Try to resolve via IP correlation
            attacker_id = await self._resolve_attacker(
                activation.requester_ip
            )
            if attacker_id:
                activation.resolved_attacker_id = attacker_id

        if not attacker_id:
            logger.debug(
                "Could not resolve attacker for activation from %s",
                activation.requester_ip,
            )
            return

        infra_map = self._get_or_create_map(attacker_id)
        now = datetime.now(timezone.utc)

        # Update network infrastructure
        infra_map.ip_addresses.add(activation.requester_ip)
        if activation.activation_type == "dns_query":
            infra_map.dns_resolvers.add(activation.requester_ip)

        # Update temporal patterns
        hour = now.hour
        infra_map.active_hours[hour] += 1
        if not infra_map.first_activity:
            infra_map.first_activity = now
        infra_map.last_activity = now

        # Update counters
        if activation.activation_type in ("http_beacon", "dns_query"):
            infra_map.canary_triggers += 1
        else:
            infra_map.seed_activations += 1

        # Estimate automation level from response timing
        if len(infra_map.active_hours) > 12:
            # Active across many hours = likely automated
            infra_map.automation_level = min(
                1.0, len(infra_map.active_hours) / 24.0
            )

        infra_map.last_updated = now

        logger.info(
            "Updated infrastructure map for attacker %s: %d IPs, %d resolvers",
            attacker_id,
            len(infra_map.ip_addresses),
            len(infra_map.dns_resolvers),
        )

    async def ingest_ble_rssi(
        self,
        attacker_id: str,
        device_id: str,
        rssi: int,
        timestamp: float,
    ) -> None:
        """Ingest BLE RSSI data for physical proximity mapping."""
        infra_map = self._get_or_create_map(attacker_id)
        location = BLELocationEstimate(device_id, rssi, timestamp)
        infra_map.ble_locations.append(location)

        # Keep last 100 measurements
        if len(infra_map.ble_locations) > 100:
            infra_map.ble_locations = infra_map.ble_locations[-50:]

        infra_map.physical_proximity_history.append(
            (timestamp, location.estimated_distance_m)
        )

    # ------------------------------------------------------------------
    # Map Retrieval
    # ------------------------------------------------------------------

    async def get_map(self, attacker_id: str) -> Optional[Dict[str, Any]]:
        """Get the infrastructure map for an attacker."""
        infra_map = self._maps.get(attacker_id)
        if infra_map:
            return infra_map.to_dict()

        # Try to rebuild from fingerprinter data
        if self._fingerprinter:
            profile = await self._fingerprinter.get_profile(
                UUID(attacker_id) if len(attacker_id) == 36 else None
            )
            if profile:
                infra_map = self._get_or_create_map(attacker_id)
                infra_map.ip_addresses.update(
                    profile.get("ip_addresses", [])
                )
                return infra_map.to_dict()

        return None

    def get_all_maps(self) -> List[Dict[str, Any]]:
        """Return all infrastructure maps."""
        return [m.to_dict() for m in self._maps.values()]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create_map(
        self, attacker_id: str,
    ) -> AttackerInfrastructureMap:
        if attacker_id not in self._maps:
            self._maps[attacker_id] = AttackerInfrastructureMap(attacker_id)
        return self._maps[attacker_id]

    async def _resolve_attacker(self, ip: str) -> Optional[str]:
        """Try to resolve an IP to a known attacker profile ID."""
        if self._fingerprinter:
            pid = self._fingerprinter._ip_to_profile.get(ip)
            if pid:
                return str(pid)
        return None
