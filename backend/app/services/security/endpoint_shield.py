"""
HIVE DEFENSE v4.4 — Endpoint Shield
Layer 5 of Castle Defense architecture.

Real-time protection for client/coach devices via the WebSocket bridge:
  - Ransomware signature detection (high-entropy payloads)
  - Keylogger pattern detection (rapid identical requests, clipboard data)
  - Malicious download URL blocking in AI responses
  - File upload payload inspection via ContentSentinel

Patent-Pending — Claims 30-56
(c) 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("hive.endpoint_shield")

MALICIOUS_URL_PATTERNS = [
    re.compile(r"bit\.ly/", re.I),
    re.compile(r"tinyurl\.com/", re.I),
    re.compile(r"t\.co/", re.I),
    re.compile(r"goo\.gl/", re.I),
    re.compile(r"\.(exe|bat|cmd|msi|scr|pif|com|vbs|js|wsf|wsh)\b", re.I),
    re.compile(r"\.php\?.*=http", re.I),
    re.compile(r"data:text/html", re.I),
    re.compile(r"javascript:", re.I),
]

KNOWN_MALICIOUS_DOMAINS = frozenset({
    "interioraccentservices.com",
    "pythondefinance.com",
    "marnjemce.com",
})

RANSOMWARE_EXTENSIONS = frozenset({
    ".encrypted", ".locked", ".crypto", ".crypt",
    ".locky", ".cerber", ".zepto", ".odin",
    ".thor", ".aesir", ".zzzzz", ".osiris",
})

KEYLOGGER_RAPID_THRESHOLD = 10
KEYLOGGER_WINDOW_SEC = 5.0
ENTROPY_THRESHOLD = 7.5


@dataclass
class ShieldVerdict:
    """Endpoint shield evaluation result."""
    safe: bool = True
    threat_type: str = ""
    threat_score: float = 0.0
    details: str = ""
    blocked_urls: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "safe": self.safe,
            "threat_type": self.threat_type,
            "threat_score": round(self.threat_score, 3),
            "details": self.details,
            "blocked_urls": self.blocked_urls,
            "flags": self.flags,
        }


class EndpointShield:
    """
    Real-time endpoint protection for client/coach WebSocket sessions.
    """

    def __init__(self):
        self._user_payload_history: Dict[str, List[dict]] = defaultdict(list)
        self._blocked_count = 0
        self._scanned_count = 0
        self._started_at = time.time()
        logger.info("Endpoint Shield initialized")

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "scanned_payloads": self._scanned_count,
            "blocked_threats": self._blocked_count,
            "uptime_hours": round((time.time() - self._started_at) / 3600, 1),
            "tracked_users": len(self._user_payload_history),
        }

    def _compute_entropy(self, data: bytes) -> float:
        """Compute Shannon entropy of binary data (bits per byte)."""
        if not data:
            return 0.0
        freq = [0] * 256
        for byte in data:
            freq[byte] += 1
        length = len(data)
        entropy = 0.0
        for count in freq:
            if count > 0:
                p = count / length
                entropy -= p * math.log2(p)
        return entropy

    def _check_ransomware(self, data: bytes, filename: str = "") -> Optional[str]:
        """Detect ransomware indicators in file uploads."""
        if filename:
            for ext in RANSOMWARE_EXTENSIONS:
                if filename.lower().endswith(ext):
                    return f"Ransomware extension detected: {ext}"
        if len(data) > 1024:
            entropy = self._compute_entropy(data)
            if entropy > ENTROPY_THRESHOLD:
                return f"High entropy ({entropy:.2f} bits/byte) -- possible encrypted/ransomware payload"
        return None

    def _check_keylogger(self, user_id: str, payload: str) -> Optional[str]:
        """Detect keylogger patterns (rapid identical or sequential submissions)."""
        now = time.time()
        history = self._user_payload_history[user_id]
        entry = {"payload_hash": hash(payload), "timestamp": now, "length": len(payload)}
        history.append(entry)
        history[:] = [h for h in history if h["timestamp"] > now - 30]

        recent = [h for h in history if h["timestamp"] > now - KEYLOGGER_WINDOW_SEC]
        if len(recent) >= KEYLOGGER_RAPID_THRESHOLD:
            identical = sum(1 for h in recent if h["payload_hash"] == entry["payload_hash"])
            if identical >= KEYLOGGER_RAPID_THRESHOLD:
                return f"Keylogger pattern: {identical} identical payloads in {KEYLOGGER_WINDOW_SEC}s"

        if len(payload) > 5000 and not payload.startswith("{"):
            return "Clipboard dump pattern: large non-JSON payload"
        return None

    def scan_urls_in_text(self, text: str) -> List[str]:
        """Scan text for malicious URLs and return blocked ones."""
        blocked = []
        for domain in KNOWN_MALICIOUS_DOMAINS:
            if domain in text.lower():
                blocked.append(domain)
        urls = re.findall(r'https?://[^\s<>"\')\]]+', text, re.I)
        for url in urls:
            for pattern in MALICIOUS_URL_PATTERNS:
                if pattern.search(url):
                    blocked.append(url)
                    break
        return list(set(blocked))

    def sanitize_ai_response(self, response_text: str) -> tuple:
        """Scan AI response for malicious URLs before sending to client."""
        blocked = self.scan_urls_in_text(response_text)
        sanitized = response_text
        for url in blocked:
            sanitized = sanitized.replace(url, "[BLOCKED -- malicious URL removed]")
        return sanitized, blocked

    async def evaluate_payload(
        self,
        user_id: str,
        payload: str,
        payload_bytes: Optional[bytes] = None,
        filename: str = "",
        direction: str = "inbound",
    ) -> ShieldVerdict:
        """Evaluate a WebSocket payload for endpoint threats."""
        self._scanned_count += 1
        verdict = ShieldVerdict()

        if payload_bytes:
            ransom_result = self._check_ransomware(payload_bytes, filename)
            if ransom_result:
                verdict.safe = False
                verdict.threat_type = "ransomware"
                verdict.threat_score = 0.9
                verdict.details = ransom_result
                verdict.flags.append("ransomware_indicator")
                self._blocked_count += 1
                logger.warning("Endpoint Shield BLOCK: user=%s threat=ransomware", user_id)
                return verdict

        if direction == "inbound" and payload:
            keylog_result = self._check_keylogger(user_id, payload)
            if keylog_result:
                verdict.safe = False
                verdict.threat_type = "keylogger"
                verdict.threat_score = 0.7
                verdict.details = keylog_result
                verdict.flags.append("keylogger_pattern")
                self._blocked_count += 1
                logger.warning("Endpoint Shield BLOCK: user=%s threat=keylogger", user_id)
                return verdict

        if direction == "outbound" and payload:
            blocked_urls = self.scan_urls_in_text(payload)
            if blocked_urls:
                verdict.blocked_urls = blocked_urls
                verdict.flags.append("malicious_urls_removed")
                verdict.threat_score = 0.5
                logger.info("Endpoint Shield: removed %d malicious URLs for user=%s",
                          len(blocked_urls), user_id)

        return verdict


_shield_instance: Optional[EndpointShield] = None


def get_endpoint_shield() -> EndpointShield:
    global _shield_instance
    if _shield_instance is None:
        _shield_instance = EndpointShield()
    return _shield_instance
