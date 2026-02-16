"""
HIVE DEFENSE v4.0 — Mirror Prediction Engine
Proactive defense that predicts attacker intent and deploys appropriate mirrors.

CROWN_JEWELS classification, endpoint dependency graph, and 4 mirror modes:
- Passive (CURIOUS): shadow session, replay request path
- Active (SUSPICIOUS): masked sensitive data fields
- Deep (ALARMED): realistic synthetic data
- Containment (HOSTILE): full Trinity Helix containment + forensics
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

_logger = logging.getLogger("mirror_prediction")


# ─── CROWN JEWELS Data Classification ────────────────────────────────────────

class DataClassification(str, Enum):
    """Data sensitivity classification levels."""
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    CROWN_JEWEL = "crown_jewel"


CROWN_JEWELS: Dict[str, DataClassification] = {
    # ── Member PII (7 categories) ──
    "member_email": DataClassification.CROWN_JEWEL,
    "member_phone": DataClassification.CROWN_JEWEL,
    "member_ssn": DataClassification.CROWN_JEWEL,
    "member_address": DataClassification.CROWN_JEWEL,
    "member_dob": DataClassification.CROWN_JEWEL,
    "member_full_name": DataClassification.CROWN_JEWEL,
    "member_encryption_shards": DataClassification.CROWN_JEWEL,

    # ── Financial — Member (6 categories) ──
    "stripe_customer_id": DataClassification.CROWN_JEWEL,
    "payment_method": DataClassification.CROWN_JEWEL,
    "payment_method_details": DataClassification.CROWN_JEWEL,
    "credit_card_number": DataClassification.CROWN_JEWEL,
    "billing_history": DataClassification.CROWN_JEWEL,
    "subscription_payment_token": DataClassification.CROWN_JEWEL,

    # ── Financial — Coach (6 categories) ──
    "bank_account": DataClassification.CROWN_JEWEL,
    "w9_data": DataClassification.CROWN_JEWEL,
    "coach_ssn": DataClassification.CROWN_JEWEL,
    "coach_bank_details": DataClassification.CROWN_JEWEL,
    "coach_1099_records": DataClassification.CROWN_JEWEL,
    "coach_tax_documents": DataClassification.CROWN_JEWEL,
    "commission_data": DataClassification.SENSITIVE,

    # ── Coach Sensitive (4 categories) ──
    "coach_license": DataClassification.CROWN_JEWEL,
    "coach_insurance": DataClassification.CROWN_JEWEL,
    "coach_notes": DataClassification.SENSITIVE,
    "coach_earnings": DataClassification.SENSITIVE,

    # ── Clinical (7 categories) ──
    "session_transcript": DataClassification.CROWN_JEWEL,
    "session_recordings": DataClassification.CROWN_JEWEL,
    "clinical_notes": DataClassification.CROWN_JEWEL,
    "diagnosis_data": DataClassification.CROWN_JEWEL,
    "safety_assessments": DataClassification.CROWN_JEWEL,
    "voice_biometrics": DataClassification.CROWN_JEWEL,
    "coherence_data": DataClassification.CROWN_JEWEL,
    "nevedal_metrics": DataClassification.CROWN_JEWEL,
    "crisis_data": DataClassification.CROWN_JEWEL,

    # ── Infrastructure (5 categories) ──
    "encryption_keys": DataClassification.CROWN_JEWEL,
    "jwt_secret": DataClassification.CROWN_JEWEL,
    "api_keys": DataClassification.CROWN_JEWEL,
    "database_credentials": DataClassification.CROWN_JEWEL,
    "database_connection_strings": DataClassification.CROWN_JEWEL,
    "stripe_secret_key": DataClassification.CROWN_JEWEL,
    "azure_credentials": DataClassification.CROWN_JEWEL,

    # ── Family (5 categories) ──
    "family_relationships": DataClassification.CROWN_JEWEL,
    "family_relationship_map": DataClassification.CROWN_JEWEL,
    "minor_data": DataClassification.CROWN_JEWEL,
    "custody_records": DataClassification.CROWN_JEWEL,
    "death_notification_data": DataClassification.CROWN_JEWEL,

    # ── Legacy & Vault (4 categories) ──
    "legacy_vault_data": DataClassification.CROWN_JEWEL,
    "me2me_crystals": DataClassification.CROWN_JEWEL,
    "heritage_vault": DataClassification.CROWN_JEWEL,
    "trust_endowment_records": DataClassification.CROWN_JEWEL,
}


# ─── Endpoint Dependency Graph ───────────────────────────────────────────────

ENDPOINT_GRAPH: Dict[str, Dict[str, Any]] = {
    "/api/sessions": {
        "data_accessed": ["session_transcript", "voice_biometrics", "coherence_data"],
        "leads_to": ["/api/sessions/{id}", "/api/sessions/{id}/biometrics"],
        "classification": DataClassification.CROWN_JEWEL,
    },
    "/api/billing": {
        "data_accessed": ["stripe_customer_id", "payment_method", "commission_data"],
        "leads_to": ["/api/billing/subscribe", "/api/billing/usage"],
        "classification": DataClassification.CROWN_JEWEL,
    },
    "/api/users": {
        "data_accessed": ["member_email", "member_phone"],
        "leads_to": ["/api/users/{id}", "/api/users/{id}/settings"],
        "classification": DataClassification.CROWN_JEWEL,
    },
    "/api/coach": {
        "data_accessed": ["coach_notes", "coach_earnings", "coach_license"],
        "leads_to": ["/api/coach/clients", "/api/coach/sessions"],
        "classification": DataClassification.SENSITIVE,
    },
    "/api/legacy-vault": {
        "data_accessed": ["legacy_vault_data", "heritage_vault"],
        "leads_to": ["/api/legacy-vault/{id}/entries"],
        "classification": DataClassification.CROWN_JEWEL,
    },
    "/api/me2me": {
        "data_accessed": ["me2me_crystals"],
        "leads_to": ["/api/me2me/crystals", "/api/me2me/conversations"],
        "classification": DataClassification.CROWN_JEWEL,
    },
    "/api/nevedal-reports": {
        "data_accessed": ["nevedal_metrics", "coherence_data"],
        "leads_to": [],
        "classification": DataClassification.CROWN_JEWEL,
    },
    "/api/night-school": {
        "data_accessed": ["coach_notes"],
        "leads_to": ["/api/night-school/wisdom", "/api/night-school/notes"],
        "classification": DataClassification.SENSITIVE,
    },
    "/api/admin": {
        "data_accessed": ["encryption_keys", "api_keys", "database_credentials"],
        "leads_to": ["/api/admin/users", "/api/admin/system"],
        "classification": DataClassification.CROWN_JEWEL,
    },
    "/api/family": {
        "data_accessed": ["family_relationships", "minor_data"],
        "leads_to": ["/api/family/members", "/api/family/settings"],
        "classification": DataClassification.CROWN_JEWEL,
    },
}


class MirrorMode(str, Enum):
    """Mirror deployment modes corresponding to curiosity states."""
    NONE = "none"           # DORMANT: no mirrors
    PASSIVE = "passive"     # CURIOUS: shadow session, replay path
    ACTIVE = "active"       # SUSPICIOUS: masked sensitive fields
    DEEP = "deep"           # ALARMED: realistic synthetic data
    CONTAINMENT = "containment"  # HOSTILE: full Trinity Helix


class MirrorPredictionEngine:
    """Predicts attacker intent and deploys appropriate mirror defenses."""

    def __init__(self):
        self._active_shadows: Dict[str, List[str]] = {}  # session_id -> [endpoints]
        self._request_paths: Dict[str, List[Dict]] = {}  # session_id -> path history

    def classify_endpoint(self, path: str) -> DataClassification:
        """Classify the data sensitivity of an endpoint."""
        # Exact match
        if path in ENDPOINT_GRAPH:
            return ENDPOINT_GRAPH[path]["classification"]

        # Prefix match (for parameterized routes)
        for ep, info in ENDPOINT_GRAPH.items():
            if path.startswith(ep.split("{")[0]):
                return info["classification"]

        return DataClassification.INTERNAL

    def predict_intent(self, session_id: str, current_path: str) -> Dict[str, Any]:
        """
        Forward-project the likely next requests based on endpoint dependency graph.
        Returns predicted paths and the data at risk.
        """
        if session_id not in self._request_paths:
            self._request_paths[session_id] = []

        self._request_paths[session_id].append({
            "path": current_path,
            "timestamp": time.time(),
        })

        # Find the graph node for this endpoint
        predicted_next: List[str] = []
        data_at_risk: Set[str] = set()

        for ep, info in ENDPOINT_GRAPH.items():
            if current_path.startswith(ep.split("{")[0]):
                predicted_next.extend(info.get("leads_to", []))
                data_at_risk.update(info.get("data_accessed", []))
                break

        # Also check what data is reachable within 2 hops
        for next_ep in predicted_next:
            for ep, info in ENDPOINT_GRAPH.items():
                if next_ep.startswith(ep.split("{")[0]):
                    data_at_risk.update(info.get("data_accessed", []))
                    break

        # Classify overall risk
        crown_jewels_at_risk = [d for d in data_at_risk if CROWN_JEWELS.get(d) == DataClassification.CROWN_JEWEL]

        return {
            "session_id": session_id,
            "current_path": current_path,
            "predicted_next": predicted_next,
            "data_at_risk": list(data_at_risk),
            "crown_jewels_at_risk": crown_jewels_at_risk,
            "risk_level": "critical" if crown_jewels_at_risk else "elevated" if data_at_risk else "normal",
        }

    def select_mirror_mode(self, guardian_state: str) -> MirrorMode:
        """Select the appropriate mirror mode based on guardian curiosity state."""
        state_to_mirror = {
            "DORMANT": MirrorMode.NONE,
            "CURIOUS": MirrorMode.PASSIVE,
            "SUSPICIOUS": MirrorMode.ACTIVE,
            "ALARMED": MirrorMode.DEEP,
            "HOSTILE": MirrorMode.CONTAINMENT,
        }
        return state_to_mirror.get(guardian_state, MirrorMode.NONE)

    def deploy_mirror(
        self, session_id: str, guardian_state: str, request_path: str,
    ) -> Dict[str, Any]:
        """
        Deploy appropriate mirror defense based on guardian state and request context.
        Returns mirror configuration for the request handler to apply.
        """
        mode = self.select_mirror_mode(guardian_state)
        prediction = self.predict_intent(session_id, request_path)
        classification = self.classify_endpoint(request_path)

        result = {
            "mirror_mode": mode.value,
            "classification": classification.value,
            "prediction": prediction,
            "actions": [],
        }

        if mode == MirrorMode.NONE:
            return result

        if mode == MirrorMode.PASSIVE:
            result["actions"] = [
                "shadow_session_started",
                "request_path_logged",
                "behavioral_capture_active",
            ]

        elif mode == MirrorMode.ACTIVE:
            result["actions"] = [
                "shadow_session_started",
                "sensitive_fields_masked",
                "rate_limit_tightened",
            ]
            # Identify which fields to mask
            result["masked_fields"] = [
                d for d in prediction["data_at_risk"]
                if CROWN_JEWELS.get(d) in (DataClassification.CROWN_JEWEL, DataClassification.SENSITIVE)
            ]

        elif mode == MirrorMode.DEEP:
            result["actions"] = [
                "shadow_session_started",
                "synthetic_data_served",
                "forensic_recording_active",
                "all_crown_jewels_hidden",
            ]
            result["synthetic_data"] = True

        elif mode == MirrorMode.CONTAINMENT:
            result["actions"] = [
                "trinity_helix_engaged",
                "full_forensic_capture",
                "session_contained",
                "admin_alerted",
                "all_data_access_blocked",
            ]
            result["containment"] = True

        return result

    def clear_session(self, session_id: str) -> None:
        """Clean up tracking data for a finished session."""
        self._request_paths.pop(session_id, None)
        self._active_shadows.pop(session_id, None)
