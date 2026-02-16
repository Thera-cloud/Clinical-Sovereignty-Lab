"""
HIVE DEFENSE v4.0 — Transit Guardian
Data-in-motion classification and inspection for all API traffic.

- Classifies every data transit by source/dest/payload/sensitivity
- Enforces ALLOWED_SENSITIVE_DESTINATIONS matrix
- Blocks unexpected outbound sensitive data
- Immutable audit trail for crown jewel transits
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .mirror_prediction import DataClassification, CROWN_JEWELS

_logger = logging.getLogger("transit_guardian")


# ─── Allowed Sensitive Destinations ──────────────────────────────────────────

ALLOWED_SENSITIVE_DESTINATIONS: Dict[str, Set[str]] = {
    # Only these destinations may receive sensitive/crown-jewel data
    "stripe_api": {"payment_method", "stripe_customer_id", "commission_data"},
    "sendgrid": {"member_email"},
    "twilio": {"member_phone"},
    "member_device": {
        "session_transcript", "coherence_data", "nevedal_metrics",
        "me2me_crystals", "legacy_vault_data",
    },
    "coach_device": {
        "coach_notes", "session_transcript", "coherence_data",
    },
    "azure_openai": set(),  # No PII should go to AI — anonymization proxy handles this
    "internal_db": set(),   # DB writes are handled by field encryption
}


class TransitDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class TransitVerdict(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    FLAG = "flag"
    ELEVATE = "elevate"


class TransitGuardian:
    """Inspects and classifies all data in motion."""

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._transit_log: List[Dict] = []
        self._blocked_count = 0

    async def inspect_transit(
        self,
        direction: str,
        source: str,
        destination: str,
        endpoint: str,
        payload_keys: List[str],
        payload_size_bytes: int = 0,
        user_id: str = "",
    ) -> Dict[str, Any]:
        """
        Inspect a data transit event.
        Returns {"verdict": str, "classification": str, "blocked_fields": [...], "reason": str}.
        """
        # Classify payload sensitivity
        classification = DataClassification.PUBLIC
        sensitive_fields: List[str] = []
        crown_jewel_fields: List[str] = []

        for key in payload_keys:
            field_class = CROWN_JEWELS.get(key, DataClassification.INTERNAL)
            if field_class == DataClassification.CROWN_JEWEL:
                crown_jewel_fields.append(key)
                classification = DataClassification.CROWN_JEWEL
            elif field_class == DataClassification.SENSITIVE:
                sensitive_fields.append(key)
                if classification != DataClassification.CROWN_JEWEL:
                    classification = DataClassification.SENSITIVE

        # Check if destination is allowed for this data
        blocked_fields: List[str] = []
        dest_key = self._normalize_destination(destination)
        allowed_data = ALLOWED_SENSITIVE_DESTINATIONS.get(dest_key, set())

        for field in crown_jewel_fields + sensitive_fields:
            if field not in allowed_data and dest_key not in ("internal_db",):
                blocked_fields.append(field)

        # Determine verdict
        if blocked_fields:
            verdict = TransitVerdict.BLOCK
            reason = f"Sensitive data ({len(blocked_fields)} fields) not allowed to {dest_key}"
            self._blocked_count += 1
            _logger.warning(
                "TRANSIT BLOCKED: %s -> %s, %d sensitive fields blocked",
                source[:20], dest_key, len(blocked_fields),
            )
        elif crown_jewel_fields:
            verdict = TransitVerdict.ELEVATE
            reason = f"Crown jewel transit to {dest_key} (allowed, elevated logging)"
        elif sensitive_fields:
            verdict = TransitVerdict.FLAG
            reason = f"Sensitive transit to {dest_key} (flagged)"
        else:
            verdict = TransitVerdict.ALLOW
            reason = "clean"

        result = {
            "verdict": verdict.value,
            "direction": direction,
            "source": source[:30],
            "destination": dest_key,
            "endpoint": endpoint,
            "classification": classification.value,
            "sensitive_fields": sensitive_fields,
            "crown_jewel_fields": crown_jewel_fields,
            "blocked_fields": blocked_fields,
            "payload_size_bytes": payload_size_bytes,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Log crown jewel transits immutably
        if classification == DataClassification.CROWN_JEWEL:
            await self._log_crown_jewel_transit(result, user_id)

        return result

    def _normalize_destination(self, destination: str) -> str:
        """Normalize a destination string to a known category."""
        dest_lower = destination.lower()
        if "stripe" in dest_lower:
            return "stripe_api"
        if "sendgrid" in dest_lower or "email" in dest_lower:
            return "sendgrid"
        if "twilio" in dest_lower or "sms" in dest_lower:
            return "twilio"
        if "openai" in dest_lower or "azure" in dest_lower or "claude" in dest_lower:
            return "azure_openai"
        if "member" in dest_lower or "client" in dest_lower:
            return "member_device"
        if "coach" in dest_lower:
            return "coach_device"
        if "postgres" in dest_lower or "redis" in dest_lower or "db" in dest_lower:
            return "internal_db"
        return "unknown"

    async def _log_crown_jewel_transit(self, result: Dict, user_id: str) -> None:
        """Immutable audit log for crown jewel data transits."""
        _logger.info(
            "CROWN JEWEL TRANSIT: %s -> %s, endpoint=%s, fields=%s",
            result["source"], result["destination"],
            result["endpoint"], result["crown_jewel_fields"],
        )
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO webhook_events_v2
                   (event_id, provider, event_type, payload_hash, processing_result, created_at)
                   VALUES ($1, 'transit_guardian', $2, $3, $4, NOW())
                   ON CONFLICT (event_id) DO NOTHING""",
                f"transit_{hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:16]}",
                f"crown_jewel_transit_{result['endpoint']}",
                hashlib.sha256(json.dumps(result["crown_jewel_fields"]).encode()).hexdigest()[:32],
                result["verdict"],
            )
        except Exception as exc:
            _logger.error("Crown jewel transit log error: %s", exc)

    # ─── Push Notification PII Inspection (v4.3) ────────────────────────────────

    # PII patterns that must never appear in push notification payloads
    _PII_PATTERNS = [
        (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), "ssn"),
        (re.compile(r'\b\d{9}\b'), "ssn_compact"),
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), "email"),
        (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), "phone"),
        (re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'), "credit_card"),
        (re.compile(r'\b(?:session|transcript|therapy|diagnosis)\b', re.IGNORECASE), "clinical_keyword"),
    ]

    async def inspect_push_notification(
        self,
        title: str,
        body: str,
        user_id: str = "",
        destination: str = "push_notification",
    ) -> Dict[str, Any]:
        """
        Inspect a push notification payload for PII leakage before sending.
        Push notifications are visible on lock screens and notification centers,
        making PII exposure especially dangerous.

        Returns: {"safe": bool, "pii_found": [...], "scrubbed_title": str, "scrubbed_body": str}
        """
        pii_found: List[Dict[str, str]] = []
        scrubbed_title = title
        scrubbed_body = body

        for text_label, text in [("title", title), ("body", body)]:
            for pattern, pii_type in self._PII_PATTERNS:
                matches = pattern.findall(text)
                if matches:
                    for match in matches:
                        pii_found.append({
                            "field": text_label,
                            "type": pii_type,
                            "preview": match[:4] + "***" if len(match) > 4 else "***",
                        })

        # Scrub PII from the notification text
        for pattern, pii_type in self._PII_PATTERNS:
            if pii_type == "clinical_keyword":
                continue  # Don't scrub keywords, just flag them
            scrubbed_title = pattern.sub("[REDACTED]", scrubbed_title)
            scrubbed_body = pattern.sub("[REDACTED]", scrubbed_body)

        safe = len(pii_found) == 0

        if not safe:
            _logger.warning(
                "PUSH NOTIFICATION PII DETECTED: %d items for user %s — %s",
                len(pii_found), user_id[:8] if user_id else "?",
                [p["type"] for p in pii_found],
            )
            # Log the transit violation
            await self.inspect_transit(
                direction="outbound",
                source="notification_service",
                destination=destination,
                endpoint="push_notification",
                payload_keys=[p["type"] for p in pii_found],
                payload_size_bytes=len(title) + len(body),
                user_id=user_id,
            )

        return {
            "safe": safe,
            "pii_found": pii_found,
            "scrubbed_title": scrubbed_title,
            "scrubbed_body": scrubbed_body,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get transit guardian statistics."""
        return {
            "blocked_transits": self._blocked_count,
            "allowed_destinations": list(ALLOWED_SENSITIVE_DESTINATIONS.keys()),
        }
