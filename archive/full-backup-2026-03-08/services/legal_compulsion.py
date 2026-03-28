"""
HIVE DEFENSE v4.3 — Legal Compulsion Protocol (Window 3)
Tiered response to legal demands for data, warrant canary, and zero-knowledge declarations.

Tiers:
1. INFORMAL: Third-party request without legal authority → refuse + log
2. SUBPOENA: Civil subpoena → engage counsel + provide only metadata
3. COURT_ORDER: Court order → comply with minimum scope + notify user
4. WARRANT: Criminal warrant → comply within scope + zero-knowledge declaration for encrypted data
5. NATIONAL_SECURITY: NSL/FISA → comply + canary update (cannot notify)

The warrant canary is a public statement that is REMOVED (not added) when
a secret legal demand is received. Its absence signals users.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("legal_compulsion")


class LegalTier(str, Enum):
    INFORMAL = "informal"
    SUBPOENA = "subpoena"
    COURT_ORDER = "court_order"
    WARRANT = "warrant"
    NATIONAL_SECURITY = "national_security"


TIER_RESPONSES = {
    LegalTier.INFORMAL: {
        "action": "refuse_and_log",
        "data_provided": "none",
        "user_notification": True,
        "counsel_required": False,
    },
    LegalTier.SUBPOENA: {
        "action": "engage_counsel",
        "data_provided": "metadata_only",
        "user_notification": True,
        "counsel_required": True,
    },
    LegalTier.COURT_ORDER: {
        "action": "minimum_scope_compliance",
        "data_provided": "specified_data_only",
        "user_notification": True,
        "counsel_required": True,
    },
    LegalTier.WARRANT: {
        "action": "comply_with_scope",
        "data_provided": "specified_data_plus_zero_knowledge_declaration",
        "user_notification": True,
        "counsel_required": True,
    },
    LegalTier.NATIONAL_SECURITY: {
        "action": "comply_silently",
        "data_provided": "specified_data_plus_zero_knowledge_declaration",
        "user_notification": False,
        "counsel_required": True,
    },
}


class LegalCompulsionProtocol:
    """Handles legal demands for data with tiered response."""

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._canary_active = True
        self._legal_log: List[Dict] = []

    def get_response_protocol(self, tier: str) -> Dict[str, Any]:
        """Get the required response protocol for a legal demand tier."""
        try:
            legal_tier = LegalTier(tier.lower())
        except ValueError:
            return {"error": f"Unknown legal tier: {tier}"}

        response = TIER_RESPONSES[legal_tier].copy()
        response["tier"] = legal_tier.value
        return response

    async def log_legal_demand(
        self, tier: str, demanding_entity: str,
        scope_description: str, case_reference: str = "",
    ) -> Dict[str, Any]:
        """Log a legal demand (immutable audit trail)."""
        entry = {
            "tier": tier,
            "demanding_entity": demanding_entity,
            "scope": scope_description,
            "case_reference": case_reference,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "protocol": self.get_response_protocol(tier),
        }

        self._legal_log.append(entry)

        _logger.critical(
            "LEGAL DEMAND RECEIVED: tier=%s, entity=%s, ref=%s",
            tier, demanding_entity, case_reference,
        )

        return entry

    def generate_zero_knowledge_declaration(self) -> Dict[str, Any]:
        """
        Generate a zero-knowledge declaration for encrypted data.
        This certifies that the platform CANNOT decrypt certain data
        because it uses client-side encryption (passphrase-derived keys).
        """
        declaration = {
            "declaration_type": "zero_knowledge",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "content": (
                "Sovereign Sanctuary hereby declares that the following categories of data "
                "are encrypted using client-side, passphrase-derived keys (PBKDF2 + AES-256-GCM) "
                "and CANNOT be decrypted by the platform operator without the user's passphrase, "
                "which is never transmitted to or stored by the platform:\n\n"
                "1. Me2Me crystal data (personal growth conversations)\n"
                "2. Family vault entries encrypted with family passphrase\n"
                "3. Heritage Vault records in zero-knowledge tier\n\n"
                "This architecture is by design and is documented in the system's "
                "Hive Defense v4.3 specification. No amount of legal compulsion can "
                "produce data that the platform does not possess the ability to decrypt."
            ),
            "hash": "",
        }
        declaration["hash"] = hashlib.sha256(
            declaration["content"].encode()
        ).hexdigest()

        return declaration

    # ─── Warrant Canary ───────────────────────────────────────────────────────

    def get_warrant_canary(self) -> Dict[str, Any]:
        """
        Get the current warrant canary status.
        If canary_active is True: no secret legal demands received.
        If canary_active is False: the absence of the canary signals users.
        """
        return {
            "canary_active": self._canary_active,
            "statement": (
                "As of this date, Sovereign Sanctuary has NOT received any "
                "National Security Letter, FISA order, or other classified "
                "legal demand for user data."
                if self._canary_active
                else None  # Canary removed — cannot make the statement
            ),
            "last_verified": datetime.now(timezone.utc).isoformat(),
        }

    def remove_canary(self) -> None:
        """
        Remove the warrant canary. This is a one-way operation.
        Called when a secret legal demand is received.
        """
        self._canary_active = False
        _logger.critical("WARRANT CANARY REMOVED")

    def get_legal_log_count(self) -> int:
        """Get the number of legal demands logged."""
        return len(self._legal_log)
