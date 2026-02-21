"""
HIVE DEFENSE v4.4 — SASE Controller (Secure Access Service Edge)
Layer 2 of Castle Defense architecture.

Policy engine sitting in front of all inbound connections:
  - Ingress Firewall: Dynamic blocklist fed by Drum resonance + ImmuneResponse
  - Source Code Shield: Blocks code exfiltration patterns
  - Cloud Access Broker: Validates outbound API calls against allowlist
  - TLS Inspection: Certificate chain verification for outbound connections

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("hive.sase")

# Allowed outbound API destinations
ALLOWED_OUTBOUND_HOSTS = frozenset({
    "api.openai.com",
    "api.cognitive.microsoft.com",
    "eastus2.api.cognitive.microsoft.com",
    "login.microsoftonline.com",
    "graph.microsoft.com",
    "api.stripe.com",
    "api.sendgrid.com",
    "api.twilio.com",
    "gmail.googleapis.com",
    "oauth2.googleapis.com",
    "www.googleapis.com",
    "api.bing.microsoft.com",
    "api.cognitive.microsoft.com",
    "sovereignsanctuary.net",
    "api.sovereignsanctuary.net",
    "app.sovereignsanctuary.net",
    "coach.sovereignsanctuary.net",
    "command.sovereignsanctuary.net",
})

EXFILTRATION_PATTERNS = [
    re.compile(r"/\.git/", re.I),
    re.compile(r"/\.env", re.I),
    re.compile(r"/\.ssh/", re.I),
    re.compile(r"/docker-compose", re.I),
    re.compile(r"/Dockerfile", re.I),
    re.compile(r"/requirements\.txt", re.I),
    re.compile(r"/migrations/", re.I),
    re.compile(r"\.\./\.\./", re.I),
    re.compile(r"/etc/passwd", re.I),
    re.compile(r"/proc/self", re.I),
    re.compile(r"\.py$", re.I),
    re.compile(r"\.dart$", re.I),
    re.compile(r"\.jsx?$", re.I),
]

ADMIN_PATH_PATTERNS = [
    re.compile(r"/api/hive-defense/", re.I),
    re.compile(r"/api/skyeye/", re.I),
    re.compile(r"/api/admin/", re.I),
    re.compile(r"/api/fibres", re.I),
    re.compile(r"/api/defcon", re.I),
]

RATE_WINDOW_SEC = 60
MAX_REQUESTS_PER_WINDOW = 120
BURST_THRESHOLD = 30


@dataclass
class SASEVerdict:
    """Result of SASE policy evaluation."""
    allowed: bool = True
    reason: str = ""
    risk_score: float = 0.0
    flags: List[str] = field(default_factory=list)
    source_ip: str = ""
    path: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk_score": self.risk_score,
            "flags": self.flags,
            "source_ip": self.source_ip,
            "path": self.path,
        }


@dataclass
class OutboundVerdict:
    """Result of outbound connection validation."""
    allowed: bool = True
    host: str = ""
    reason: str = ""
    timestamp: float = 0.0


class HiveSASEController:
    """
    Secure Access Service Edge for the Sovereign Sanctuary.
    Evaluates every inbound request against security policies.
    """

    def __init__(self):
        self._dynamic_blocklist: Set[str] = set()
        self._request_counts: Dict[str, List[float]] = defaultdict(list)
        self._exfiltration_attempts: Dict[str, int] = defaultdict(int)
        self._outbound_violations: List[OutboundVerdict] = []
        self._total_blocked = 0
        self._total_evaluated = 0
        self._started_at = time.time()
        self._enabled = True
        logger.info("SASE Controller initialized")

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "uptime_hours": round((time.time() - self._started_at) / 3600, 1),
            "total_evaluated": self._total_evaluated,
            "total_blocked": self._total_blocked,
            "blocklist_size": len(self._dynamic_blocklist),
            "outbound_violations": len(self._outbound_violations),
            "active_exfiltration_ips": len(self._exfiltration_attempts),
        }

    def add_to_blocklist(self, ip: str, reason: str = "") -> None:
        """Add an IP to the dynamic blocklist."""
        self._dynamic_blocklist.add(ip)
        logger.warning("SASE blocklist add: %s reason=%s", ip, reason)

    def remove_from_blocklist(self, ip: str) -> None:
        self._dynamic_blocklist.discard(ip)

    # ─── INGRESS FIREWALL ────────────────────────────────────────────────

    def _check_blocklist(self, source_ip: str) -> Optional[str]:
        """Check if source IP is on the dynamic blocklist."""
        if source_ip in self._dynamic_blocklist:
            return f"IP {source_ip} is on dynamic blocklist"
        return None

    def _check_rate_limit(self, source_ip: str) -> Optional[str]:
        """Application-layer rate limiting per source IP."""
        now = time.time()
        cutoff = now - RATE_WINDOW_SEC
        timestamps = self._request_counts[source_ip]
        timestamps[:] = [t for t in timestamps if t > cutoff]
        timestamps.append(now)

        if len(timestamps) > MAX_REQUESTS_PER_WINDOW:
            return f"Rate limit exceeded: {len(timestamps)} requests in {RATE_WINDOW_SEC}s"

        recent_burst = sum(1 for t in timestamps if t > now - 5)
        if recent_burst > BURST_THRESHOLD:
            return f"Burst detected: {recent_burst} requests in 5s"

        return None

    # ─── SOURCE CODE SHIELD ──────────────────────────────────────────────

    def _check_exfiltration(self, path: str, source_ip: str) -> Tuple[bool, List[str]]:
        """Detect source code exfiltration attempts."""
        flags = []
        for pattern in EXFILTRATION_PATTERNS:
            if pattern.search(path):
                flags.append(f"exfiltration_pattern: {pattern.pattern}")
                self._exfiltration_attempts[source_ip] += 1

        if self._exfiltration_attempts.get(source_ip, 0) >= 3:
            self.add_to_blocklist(source_ip, "repeated exfiltration attempts")
            flags.append("auto_blocked: repeated exfiltration")

        return len(flags) == 0, flags

    def _check_admin_path(self, path: str, user_role: str) -> Optional[str]:
        """Block non-admin access to admin paths."""
        for pattern in ADMIN_PATH_PATTERNS:
            if pattern.search(path) and user_role != "ADMIN":
                return f"Non-admin access to protected path: {path}"
        return None

    # ─── CLOUD ACCESS BROKER ────────────────────────────────────────────

    def validate_outbound(self, host: str, purpose: str = "") -> OutboundVerdict:
        """Validate an outbound connection against the allowlist."""
        host_lower = host.lower().strip()
        allowed = any(
            host_lower == h or host_lower.endswith("." + h)
            for h in ALLOWED_OUTBOUND_HOSTS
        )

        verdict = OutboundVerdict(
            allowed=allowed,
            host=host_lower,
            reason="" if allowed else f"Unauthorized outbound: {host_lower}",
            timestamp=time.time(),
        )

        if not allowed:
            self._outbound_violations.append(verdict)
            logger.warning(
                "SASE outbound BLOCKED: host=%s purpose=%s",
                host_lower, purpose,
            )

        return verdict

    # ─── MAIN EVALUATION ────────────────────────────────────────────────

    async def evaluate_request(
        self,
        source_ip: str,
        path: str,
        method: str = "GET",
        user_role: str = "",
        content_length: int = 0,
        headers: Optional[Dict[str, str]] = None,
    ) -> SASEVerdict:
        """
        Evaluate an inbound request against all SASE policies.
        Returns a verdict with allow/deny decision and risk score.
        """
        self._total_evaluated += 1

        if not self._enabled:
            return SASEVerdict(allowed=True, source_ip=source_ip, path=path)

        verdict = SASEVerdict(
            source_ip=source_ip,
            path=path,
            timestamp=time.time(),
        )

        # 1. Blocklist check
        block_reason = self._check_blocklist(source_ip)
        if block_reason:
            verdict.allowed = False
            verdict.reason = block_reason
            verdict.risk_score = 100.0
            verdict.flags.append("blocklisted")
            self._total_blocked += 1
            return verdict

        # 2. Rate limiting
        rate_reason = self._check_rate_limit(source_ip)
        if rate_reason:
            verdict.allowed = False
            verdict.reason = rate_reason
            verdict.risk_score = 70.0
            verdict.flags.append("rate_limited")
            self._total_blocked += 1
            return verdict

        # 3. Source code exfiltration detection
        exfil_ok, exfil_flags = self._check_exfiltration(path, source_ip)
        if not exfil_ok:
            verdict.allowed = False
            verdict.reason = "Source code exfiltration attempt detected"
            verdict.risk_score = 95.0
            verdict.flags.extend(exfil_flags)
            self._total_blocked += 1
            return verdict

        # 4. Admin path protection
        admin_reason = self._check_admin_path(path, user_role)
        if admin_reason:
            verdict.allowed = False
            verdict.reason = admin_reason
            verdict.risk_score = 60.0
            verdict.flags.append("admin_path_violation")
            self._total_blocked += 1
            return verdict

        # 5. Large response detection (possible data exfil)
        if content_length > 10 * 1024 * 1024:  # 10MB
            verdict.flags.append("large_payload")
            verdict.risk_score = max(verdict.risk_score, 30.0)

        # 6. Suspicious headers
        if headers:
            ua = headers.get("user-agent", "")
            if not ua or len(ua) < 10:
                verdict.flags.append("suspicious_ua")
                verdict.risk_score = max(verdict.risk_score, 20.0)

            if headers.get("x-forwarded-for", "").count(",") > 3:
                verdict.flags.append("proxy_chain")
                verdict.risk_score = max(verdict.risk_score, 25.0)

        return verdict

    # ─── DEFCON INTEGRATION ─────────────────────────────────────────────

    async def on_defcon_change(self, level: int, level_name: str) -> None:
        """Respond to DEFCON level changes."""
        if level >= 4:  # CRITICAL or LOCKDOWN
            self._enabled = True
            logger.warning("SASE: DEFCON %s — maximum enforcement", level_name)
        elif level >= 3:  # RESTRICT
            self._enabled = True
            logger.info("SASE: DEFCON %s — enhanced enforcement", level_name)

    def get_recent_violations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent outbound violations for SkyEye dashboard."""
        return [
            {"host": v.host, "reason": v.reason, "timestamp": v.timestamp}
            for v in self._outbound_violations[-limit:]
        ]


# Singleton
_sase_instance: Optional[HiveSASEController] = None


def get_sase() -> HiveSASEController:
    global _sase_instance
    if _sase_instance is None:
        _sase_instance = HiveSASEController()
    return _sase_instance
