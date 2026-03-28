"""
HIVE DEFENSE PROTOCOL — Attacker Topology Mirror (Phase 8E)
Mirrors attacker's network topology: latency, routing, and packet structure.

The Topology Mirror learns the attacker's network infrastructure from
Penetrator intelligence and generates responses with timing, routing, and
packet characteristics that match what the attacker's C&C expects to see
from its own agents.

Hop counts, TTLs, packet sizes, and response timing are all calibrated to
the attacker's infrastructure so that passive network analysis by the
attacker reveals nothing anomalous.

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("hive.topology_mirror")


# =============================================================================
# ATTACKER TOPOLOGY MIRROR
# =============================================================================

class AttackerTopologyMirror:
    """
    Mirrors the attacker's network topology for response realism.

    Generates responses that match the attacker's expected network
    characteristics: latency distributions, hop counts, TTL values,
    packet sizing, and route paths.

    Attributes
    ----------
    topology_spec : dict
        Learned network topology from Penetrator intelligence.
    latency_model : dict
        Latency distribution parameters (min, max, mean, std).
    hop_model : dict
        Hop count parameters per route.
    ttl_baseline : int
        Base TTL value observed in attacker traffic.

    Usage
    -----
    ::

        mirror = AttackerTopologyMirror(topology_spec={
            "latency_ms": {"min": 12, "max": 45, "mean": 22, "std": 8},
            "hop_count": {"min": 3, "max": 7, "typical": 5},
            "ttl": 128,
            "mtu": 1500,
            ...
        })
        response = await mirror.reflect(attacker_command)
    """

    def __init__(self, topology_spec: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialise the Topology Mirror from Penetrator intelligence.

        Parameters
        ----------
        topology_spec:
            Network topology specification extracted by the Penetrator.
            Contains latency distributions, hop counts, TTL baselines,
            route paths, MTU values, and packet structure templates.
        """
        self.topology_spec: Dict[str, Any] = topology_spec or {}

        # Latency model — how long responses take in the attacker's network
        self.latency_model: Dict[str, float] = self.topology_spec.get(
            "latency_ms", {"min": 10.0, "max": 80.0, "mean": 30.0, "std": 15.0}
        )

        # Hop count model
        self.hop_model: Dict[str, int] = self.topology_spec.get(
            "hop_count", {"min": 2, "max": 8, "typical": 4}
        )

        # TTL baseline
        self.ttl_baseline: int = self.topology_spec.get("ttl", 64)

        # MTU / packet size
        self._mtu: int = self.topology_spec.get("mtu", 1500)
        self._typical_packet_size: int = self.topology_spec.get(
            "typical_packet_size", 512
        )

        # Known route paths
        self._route_paths: List[List[str]] = self.topology_spec.get(
            "route_paths", []
        )

        # Response timing jitter range (milliseconds)
        self._jitter_ms: float = self.topology_spec.get("jitter_ms", 5.0)

        # Node addresses in the attacker's topology
        self._known_nodes: List[str] = self.topology_spec.get(
            "known_nodes", []
        )

        # Metrics
        self._reflections: int = 0

        logger.info(
            "AttackerTopologyMirror initialised: latency_mean=%.1fms "
            "hops_typical=%d ttl=%d known_nodes=%d routes=%d",
            self.latency_model.get("mean", 0),
            self.hop_model.get("typical", 0),
            self.ttl_baseline,
            len(self._known_nodes),
            len(self._route_paths),
        )

    # ------------------------------------------------------------------
    # Core reflection
    # ------------------------------------------------------------------

    async def reflect(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a topology-level reflection of the attacker's command.

        Returns response metadata that matches the attacker's network
        characteristics: realistic latency, correct hop count, matching
        TTL, and plausible route path.

        Parameters
        ----------
        command:
            The intercepted attacker command.

        Returns
        -------
        dict
            A response with network topology characteristics matching the
            attacker's infrastructure.
        """
        self._reflections += 1

        # Simulate realistic network latency
        latency_ms = self._generate_latency()
        await self._simulate_latency(latency_ms)

        # Generate topology-realistic response metadata
        hop_count = self._generate_hop_count()
        ttl = self._compute_ttl(hop_count)
        packet_size = self._generate_packet_size(command)
        route_path = self._select_route_path(command)

        response: Dict[str, Any] = {
            "latency_ms": round(latency_ms, 2),
            "hop_count": hop_count,
            "ttl": ttl,
            "packet_size": packet_size,
            "mtu": self._mtu,
            "route_path": route_path,
            "source_node": self._select_source_node(command),
            "response_time_ns": time.time_ns(),
            "network_jitter_ms": round(
                random.uniform(0, self._jitter_ms), 2
            ),
        }

        logger.debug(
            "TopologyMirror reflected: latency=%.1fms hops=%d ttl=%d "
            "packet_size=%d",
            latency_ms,
            hop_count,
            ttl,
            packet_size,
        )

        return response

    # ------------------------------------------------------------------
    # Topology learning
    # ------------------------------------------------------------------

    def update_topology_spec(self, updates: Dict[str, Any]) -> None:
        """
        Update the topology specification with new intelligence.

        Called by the RecursiveProjection when new network patterns are
        learned from intercepted commands.

        Parameters
        ----------
        updates:
            Dictionary of topology specification updates to merge.
        """
        self.topology_spec.update(updates)

        if "latency_ms" in updates:
            self.latency_model.update(updates["latency_ms"])
        if "hop_count" in updates:
            self.hop_model.update(updates["hop_count"])
        if "ttl" in updates:
            self.ttl_baseline = updates["ttl"]
        if "mtu" in updates:
            self._mtu = updates["mtu"]
        if "typical_packet_size" in updates:
            self._typical_packet_size = updates["typical_packet_size"]
        if "route_paths" in updates:
            for path in updates["route_paths"]:
                if path not in self._route_paths:
                    self._route_paths.append(path)
        if "known_nodes" in updates:
            for node in updates["known_nodes"]:
                if node not in self._known_nodes:
                    self._known_nodes.append(node)
        if "jitter_ms" in updates:
            self._jitter_ms = updates["jitter_ms"]

        logger.debug(
            "TopologyMirror spec updated: %d keys", len(updates)
        )

    # ------------------------------------------------------------------
    # Internal topology simulation
    # ------------------------------------------------------------------

    def _generate_latency(self) -> float:
        """
        Generate a realistic latency value from the attacker's observed
        latency distribution.

        Uses a clamped Gaussian distribution centered on the observed
        mean with the observed standard deviation.
        """
        mean = self.latency_model.get("mean", 30.0)
        std = self.latency_model.get("std", 15.0)
        min_lat = self.latency_model.get("min", 5.0)
        max_lat = self.latency_model.get("max", 200.0)

        latency = random.gauss(mean, std)
        return max(min_lat, min(max_lat, latency))

    async def _simulate_latency(self, latency_ms: float) -> None:
        """
        Introduce actual delay to match the attacker's expected response
        timing.  This prevents the attacker from detecting the mirror
        through timing analysis.

        Parameters
        ----------
        latency_ms:
            Target latency in milliseconds.
        """
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000.0)

    def _generate_hop_count(self) -> int:
        """Generate a realistic hop count from the attacker's topology."""
        min_hops = self.hop_model.get("min", 2)
        max_hops = self.hop_model.get("max", 8)
        typical = self.hop_model.get("typical", 4)

        # Weighted toward the typical value
        if random.random() < 0.7:
            return typical
        return random.randint(min_hops, max_hops)

    def _compute_ttl(self, hop_count: int) -> int:
        """
        Compute the expected TTL value after traversing the given
        number of hops.

        The TTL starts at the attacker's baseline and decrements by
        the hop count.
        """
        return max(1, self.ttl_baseline - hop_count)

    def _generate_packet_size(self, command: Dict[str, Any]) -> int:
        """
        Generate a realistic packet size based on command type and the
        attacker's typical packet sizes.
        """
        cmd_type = command.get("type", "")
        base_size = self._typical_packet_size

        # Adjust based on command type
        if cmd_type in ("exfil", "data_extract"):
            # Data exfiltration responses are larger
            base_size = min(self._mtu, base_size * 3)
        elif cmd_type in ("beacon", "heartbeat"):
            # Heartbeats are small
            base_size = max(64, base_size // 4)
        elif cmd_type in ("scan", "recon"):
            # Scan results are medium
            base_size = min(self._mtu, int(base_size * 1.5))

        # Add realistic variance
        variance = int(base_size * 0.1)
        return max(64, base_size + random.randint(-variance, variance))

    def _select_route_path(self, command: Dict[str, Any]) -> List[str]:
        """
        Select an appropriate route path from the attacker's known routes.

        Falls back to generating a synthetic path if no routes are known.
        """
        if self._route_paths:
            return random.choice(self._route_paths)

        # Generate a synthetic path from known nodes
        if self._known_nodes and len(self._known_nodes) >= 2:
            hop_count = self._generate_hop_count()
            path_length = min(hop_count, len(self._known_nodes))
            return random.sample(self._known_nodes, path_length)

        return []

    def _select_source_node(self, command: Dict[str, Any]) -> str:
        """
        Select a plausible source node for the response based on the
        command's target.
        """
        target = command.get("target", "")

        # If target matches a known node, use it
        if target in self._known_nodes:
            return target

        # Use a random known node
        if self._known_nodes:
            return random.choice(self._known_nodes)

        return "agent-node"

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "latency_mean_ms": self.latency_model.get("mean", 0),
            "hop_count_typical": self.hop_model.get("typical", 0),
            "ttl_baseline": self.ttl_baseline,
            "mtu": self._mtu,
            "known_nodes": len(self._known_nodes),
            "route_paths": len(self._route_paths),
            "reflections": self._reflections,
        }

    def __repr__(self) -> str:
        return (
            f"<AttackerTopologyMirror "
            f"latency_mean={self.latency_model.get('mean', 0):.1f}ms "
            f"hops={self.hop_model.get('typical', 0)} "
            f"reflections={self._reflections}>"
        )
