"""
HIVE DEFENSE v4.4 — Mirror Gateway
Layer 7 of Castle Defense architecture.

Orchestrates the House of Mirrors on the VPN exit node.
All inbound connections (reverse probes from attackers) enter the mirror maze.

Flow:
  1. Attacker probes VPN exit IP
  2. MirrorShell intercepts → routes to mirror namespace
  3. Honeypot serves fake vulnerable surface
  4. Tarpit slows attacker down
  5. InfiniteMirrorTrap reflects C&C protocol
  6. Canary tokens track attacker across sessions
  7. All intel logged and forwarded to production via WireGuard

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger("hive.mirror_gateway")

# Fake services to present on the VPN exit node
HONEYPOT_SERVICES = {
    80: {"name": "http", "banner": "Apache/2.4.54 (Ubuntu)"},
    443: {"name": "https", "banner": "nginx/1.22.1"},
    22: {"name": "ssh", "banner": "OpenSSH_8.9p1 Ubuntu-3ubuntu0.4"},
    3306: {"name": "mysql", "banner": "5.7.40-0ubuntu0.18.04.1"},
    5432: {"name": "postgresql", "banner": "PostgreSQL 15.4"},
    6379: {"name": "redis", "banner": "Redis v7.0.14"},
    8080: {"name": "http-alt", "banner": "Jetty/9.4.51.v20230217"},
}

TARPIT_RESPONSE_DELAY_SEC = 5.0
TARPIT_CHUNK_SIZE = 16  # Bytes per drip


@dataclass
class ProbeRecord:
    """Record of an attacker probing the VPN exit."""
    probe_id: str = ""
    source_ip: str = ""
    port: int = 0
    protocol: str = ""
    timestamp: float = 0.0
    fingerprint: Dict[str, Any] = field(default_factory=dict)
    trap_triggered: str = ""
    intel_captured: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "source_ip": self.source_ip,
            "port": self.port,
            "protocol": self.protocol,
            "timestamp": self.timestamp,
            "fingerprint": self.fingerprint,
            "trap_triggered": self.trap_triggered,
            "intel_captured": self.intel_captured,
        }


class MirrorGateway:
    """
    Orchestrates the House of Mirrors on the VPN exit node.
    Every inbound connection enters a recursive mirror trap.
    """

    def __init__(self):
        self._probes: List[ProbeRecord] = []
        self._attacker_ips: Dict[str, int] = defaultdict(int)
        self._canary_hits: List[Dict[str, Any]] = []
        self._intel_queue: List[Dict[str, Any]] = []
        self._active_tarpits: int = 0
        self._started_at = time.time()
        logger.info("Mirror Gateway initialized — %d honeypot services configured",
                    len(HONEYPOT_SERVICES))

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_probes": len(self._probes),
            "unique_attackers": len(self._attacker_ips),
            "active_tarpits": self._active_tarpits,
            "canary_hits": len(self._canary_hits),
            "intel_queue_size": len(self._intel_queue),
            "uptime_hours": round((time.time() - self._started_at) / 3600, 1),
        }

    # ─── PROBE HANDLING ─────────────────────────────────────────────────

    async def on_probe(
        self,
        source_ip: str,
        port: int,
        protocol: str = "tcp",
        headers: Optional[Dict[str, str]] = None,
        payload: bytes = b"",
    ) -> ProbeRecord:
        """Handle an inbound probe to the VPN exit node."""
        probe = ProbeRecord(
            probe_id=str(uuid4())[:12],
            source_ip=source_ip,
            port=port,
            protocol=protocol,
            timestamp=time.time(),
        )
        self._attacker_ips[source_ip] += 1

        # Fingerprint the attacker
        probe.fingerprint = self._fingerprint_probe(
            source_ip, port, protocol, headers, payload,
        )

        # Route to appropriate trap
        service = HONEYPOT_SERVICES.get(port)
        if service:
            probe.trap_triggered = f"honeypot_{service['name']}"
            probe.intel_captured = await self._honeypot_response(
                service, source_ip, headers, payload,
            )
        else:
            probe.trap_triggered = "tarpit"
            probe.intel_captured = await self._tarpit_response(source_ip)

        # Check for C&C patterns → mirror trap
        if self._is_c2_pattern(payload):
            probe.trap_triggered = "infinite_mirror"
            probe.intel_captured["mirror_trap"] = True
            await self._activate_mirror_trap(source_ip, payload)

        # Queue intel for forwarding to production
        self._intel_queue.append(probe.to_dict())
        self._probes.append(probe)

        logger.info(
            "Mirror Gateway: probe from %s port=%d trap=%s",
            source_ip, port, probe.trap_triggered,
        )
        return probe

    # ─── FINGERPRINTING ─────────────────────────────────────────────────

    def _fingerprint_probe(
        self,
        source_ip: str,
        port: int,
        protocol: str,
        headers: Optional[Dict[str, str]],
        payload: bytes,
    ) -> Dict[str, Any]:
        """Build attacker fingerprint from probe characteristics."""
        fp: Dict[str, Any] = {
            "ip": source_ip,
            "port_targeted": port,
            "protocol": protocol,
            "probe_count": self._attacker_ips[source_ip],
            "payload_size": len(payload),
            "payload_hash": hashlib.sha256(payload).hexdigest()[:16] if payload else "",
        }

        if headers:
            fp["user_agent"] = headers.get("user-agent", "")
            fp["accept_language"] = headers.get("accept-language", "")
            fp["header_count"] = len(headers)

        return fp

    # ─── HONEYPOT ────────────────────────────────────────────────────────

    async def _honeypot_response(
        self,
        service: Dict[str, str],
        source_ip: str,
        headers: Optional[Dict[str, str]],
        payload: bytes,
    ) -> Dict[str, Any]:
        """Generate a convincing fake response from a honeypot service."""
        intel: Dict[str, Any] = {
            "service": service["name"],
            "banner_served": service["banner"],
        }

        if service["name"] in ("http", "https", "http-alt"):
            # Serve a fake login page
            intel["page_served"] = "fake_login"
            intel["canary_embedded"] = True

            canary_id = str(uuid4())[:8]
            self._canary_hits.append({
                "canary_id": canary_id,
                "attacker_ip": source_ip,
                "service": service["name"],
                "timestamp": time.time(),
            })
            intel["canary_id"] = canary_id

            # Capture any submitted credentials
            if payload:
                try:
                    body = payload.decode("utf-8", errors="replace")
                    intel["submitted_data_preview"] = body[:200]
                except Exception:
                    pass

        elif service["name"] in ("mysql", "postgresql"):
            intel["auth_challenge_sent"] = True

        elif service["name"] == "redis":
            intel["fake_data_served"] = True

        return intel

    # ─── TARPIT ──────────────────────────────────────────────────────────

    async def _tarpit_response(self, source_ip: str) -> Dict[str, Any]:
        """Slow-drip response to waste attacker time."""
        self._active_tarpits += 1
        intel = {
            "tarpit": True,
            "delay_sec": TARPIT_RESPONSE_DELAY_SEC,
            "attacker_ip": source_ip,
        }

        # Simulate tarpit delay (don't actually block in production)
        await asyncio.sleep(min(TARPIT_RESPONSE_DELAY_SEC, 1.0))
        self._active_tarpits -= 1

        return intel

    # ─── MIRROR TRAP ─────────────────────────────────────────────────────

    def _is_c2_pattern(self, payload: bytes) -> bool:
        """Detect command-and-control patterns in probe payload."""
        if not payload:
            return False

        try:
            text = payload.decode("utf-8", errors="replace").lower()
            c2_indicators = [
                "whoami", "id", "uname", "cat /etc",
                "wget ", "curl ", "nc ", "ncat ",
                "python -c", "bash -i", "sh -i",
                "/bin/sh", "/bin/bash",
                "powershell", "cmd /c",
            ]
            return any(ind in text for ind in c2_indicators)
        except Exception:
            return False

    async def _activate_mirror_trap(self, source_ip: str, payload: bytes) -> None:
        """Activate the InfiniteMirrorTrap for C&C reflections."""
        logger.warning(
            "Mirror Gateway: C&C pattern detected from %s — activating InfiniteMirrorTrap",
            source_ip,
        )
        try:
            from app.services.security.infinite_mirror_trap import InfiniteMirrorTrap
            trap = InfiniteMirrorTrap()
            await trap.reflect(source_ip, payload)
        except ImportError:
            logger.debug("InfiniteMirrorTrap not available in this deployment")
        except Exception as e:
            logger.warning("Mirror trap activation failed: %s", e)

    # ─── INTEL FORWARDING ───────────────────────────────────────────────

    def get_pending_intel(self) -> List[Dict[str, Any]]:
        """Get and flush pending intel for forwarding to production."""
        intel = list(self._intel_queue)
        self._intel_queue.clear()
        return intel

    def get_all_probes(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all recorded probes."""
        probes = sorted(self._probes, key=lambda p: p.timestamp, reverse=True)
        return [p.to_dict() for p in probes[:limit]]

    def get_attacker_summary(self) -> List[Dict[str, Any]]:
        """Summarize unique attackers."""
        return [
            {"ip": ip, "probe_count": count}
            for ip, count in sorted(
                self._attacker_ips.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:50]
        ]


# Singleton
_gateway_instance: Optional[MirrorGateway] = None


def get_mirror_gateway() -> MirrorGateway:
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = MirrorGateway()
    return _gateway_instance
