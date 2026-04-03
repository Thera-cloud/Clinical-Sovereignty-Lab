"""
Therapeutic Identity Inference Engine — Phase 8: Institutional Deployment.

Multi-tenant architecture for deploying Little Nate across institutions:
clinics, schools, prisons, corporate wellness, group therapy.

Each tenant gets: separate Twilio number, deployment_context-aware identity
weights, tenant-scoped data isolation (RLS), age-appropriate configuration,
and environment-specific consent chains.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.institutional")

DEPLOYMENT_CONTEXTS = {
    "default": {
        "description": "Individual therapy (default)",
        "requires_consent": True,
        "voice_enrollment_enabled": True,
        "mandatory_reporting_enabled": True,
        "min_age": 18,
        "monitored": False,
        "corrections_mode": False,
    },
    "clinic": {
        "description": "Clinical practice or counseling center",
        "requires_consent": True,
        "voice_enrollment_enabled": True,
        "mandatory_reporting_enabled": True,
        "min_age": 13,
        "monitored": False,
        "corrections_mode": False,
    },
    "school": {
        "description": "K-12 or university counseling",
        "requires_consent": True,
        "voice_enrollment_enabled": True,
        "mandatory_reporting_enabled": True,
        "min_age": 6,
        "monitored": False,
        "corrections_mode": False,
        "coppa_required": True,
        "ferpa_required": True,
    },
    "prison": {
        "description": "Correctional facility counseling",
        "requires_consent": True,
        "voice_enrollment_enabled": True,
        "mandatory_reporting_enabled": True,
        "min_age": 18,
        "monitored": True,
        "corrections_mode": True,
        "call_recording_disclosure": True,
    },
    "corporate": {
        "description": "Corporate wellness / EAP",
        "requires_consent": True,
        "voice_enrollment_enabled": False,
        "mandatory_reporting_enabled": True,
        "min_age": 18,
        "monitored": False,
        "corrections_mode": False,
    },
    "group": {
        "description": "Group therapy / AA-style meetings",
        "requires_consent": True,
        "voice_enrollment_enabled": True,
        "mandatory_reporting_enabled": True,
        "min_age": 13,
        "monitored": False,
        "corrections_mode": False,
        "multi_speaker": True,
    },
    "family": {
        "description": "Family therapy sessions",
        "requires_consent": True,
        "voice_enrollment_enabled": True,
        "mandatory_reporting_enabled": True,
        "min_age": 6,
        "monitored": False,
        "corrections_mode": False,
        "multi_speaker": True,
    },
}


@dataclass
class InstitutionalTenant:
    """Configuration for a single institutional deployment."""
    tenant_id: str
    name: str
    deployment_context: str
    twilio_number: Optional[str] = None
    admin_email: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    consent_version: str = "v1.0"
    created_at: float = field(default_factory=time.time)
    active: bool = True

    @property
    def context_config(self) -> Dict[str, Any]:
        base = DEPLOYMENT_CONTEXTS.get(self.deployment_context, DEPLOYMENT_CONTEXTS["default"])
        merged = dict(base)
        merged.update(self.config)
        return merged

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "deployment_context": self.deployment_context,
            "twilio_number": self.twilio_number,
            "admin_email": self.admin_email,
            "config": self.config,
            "consent_version": self.consent_version,
            "active": self.active,
        }


@dataclass
class ConsentRecord:
    """Records a user's consent for voice enrollment and identity features."""
    user_id: str
    tenant_id: str
    consent_type: str  # voice_enrollment, identity_inference, data_retention
    granted: bool = False
    consent_method: str = "sms_magic_link"  # sms_magic_link, in_app, parental, vouched
    consent_source: Optional[str] = None
    parent_user_id: Optional[str] = None
    granted_at: Optional[float] = None
    expires_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "consent_type": self.consent_type,
            "granted": self.granted,
            "consent_method": self.consent_method,
            "consent_source": self.consent_source,
            "parent_user_id": self.parent_user_id,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
        }


class InstitutionalDeploymentManager:
    """
    Manages multi-tenant institutional deployments.

    Provides tenant-scoped configuration, consent chain management,
    and deployment context resolution for identity inference.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._tenants: Dict[str, InstitutionalTenant] = {}

    async def load_tenant(self, tenant_id: str) -> Optional[InstitutionalTenant]:
        if tenant_id in self._tenants:
            return self._tenants[tenant_id]

        if not self._db:
            return None

        try:
            import json
            row = await self._db.fetchrow(
                "SELECT * FROM institutional_tenants WHERE tenant_id = $1",
                tenant_id,
            )
            if row:
                tenant = InstitutionalTenant(
                    tenant_id=row["tenant_id"],
                    name=row["name"],
                    deployment_context=row["deployment_context"],
                    twilio_number=row.get("twilio_number"),
                    admin_email=row.get("admin_email"),
                    config=json.loads(row["config"]) if row.get("config") else {},
                    consent_version=row.get("consent_version", "v1.0"),
                    active=row.get("active", True),
                )
                self._tenants[tenant_id] = tenant
                return tenant
        except Exception as e:
            logger.warning("InstitutionalDeployment: load tenant %s failed: %s", tenant_id, e)

        return None

    async def resolve_by_phone(self, phone: str) -> Optional[InstitutionalTenant]:
        """Resolve tenant by incoming Twilio phone number."""
        for t in self._tenants.values():
            if t.twilio_number == phone:
                return t

        if self._db:
            try:
                row = await self._db.fetchrow(
                    "SELECT tenant_id FROM institutional_tenants WHERE twilio_number = $1",
                    phone,
                )
                if row:
                    return await self.load_tenant(row["tenant_id"])
            except Exception as e:
                logger.warning("InstitutionalDeployment: phone resolve failed: %s", e)

        return None

    async def check_consent(
        self, user_id: str, tenant_id: str, consent_type: str,
    ) -> bool:
        """Check if a user has active consent for a specific feature."""
        if not self._db:
            return False

        try:
            row = await self._db.fetchrow(
                """SELECT granted FROM consent_records
                   WHERE user_id = $1 AND tenant_id = $2 AND consent_type = $3
                   AND granted = true
                   AND (expires_at IS NULL OR expires_at > NOW())""",
                user_id, tenant_id, consent_type,
            )
            return bool(row)
        except Exception as e:
            logger.warning("InstitutionalDeployment: consent check failed: %s", e)
            return False

    async def record_consent(self, record: ConsentRecord) -> bool:
        """Store a consent record."""
        if not self._db:
            return False

        try:
            await self._db.execute(
                """INSERT INTO consent_records
                   (user_id, tenant_id, consent_type, granted, consent_method,
                    consent_source, parent_user_id, granted_at, expires_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8)
                   ON CONFLICT (user_id, tenant_id, consent_type) DO UPDATE SET
                     granted = $4, consent_method = $5, consent_source = $6,
                     parent_user_id = $7, granted_at = NOW(), expires_at = $8""",
                record.user_id, record.tenant_id, record.consent_type,
                record.granted, record.consent_method, record.consent_source,
                record.parent_user_id, record.expires_at,
            )
            return True
        except Exception as e:
            logger.warning("InstitutionalDeployment: consent record failed: %s", e)
            return False

    def get_age_config(self, deployment_context: str, user_age: Optional[int]) -> Dict[str, Any]:
        """
        Get age-appropriate configuration for a user.
        Handles COPPA (<13), adolescent (13-17), and adult (18+) tiers.
        """
        config = DEPLOYMENT_CONTEXTS.get(deployment_context, DEPLOYMENT_CONTEXTS["default"])
        result = {
            "requires_parental_consent": False,
            "age_tier": "adult",
            "language_complexity": "full",
            "voice_enrollment_allowed": config.get("voice_enrollment_enabled", True),
            "wider_acceptance_threshold": False,
        }

        if user_age is None:
            return result

        if user_age < 13:
            result["requires_parental_consent"] = True
            result["age_tier"] = "child"
            result["language_complexity"] = "simplified"
            result["wider_acceptance_threshold"] = True
        elif user_age < 18:
            result["age_tier"] = "adolescent"
            result["language_complexity"] = "moderate"
            result["wider_acceptance_threshold"] = True
            if config.get("coppa_required"):
                result["requires_parental_consent"] = True

        return result

    def get_corrections_config(self, deployment_context: str) -> Dict[str, Any]:
        """Get corrections-specific configuration."""
        config = DEPLOYMENT_CONTEXTS.get(deployment_context, DEPLOYMENT_CONTEXTS["default"])
        return {
            "corrections_mode": config.get("corrections_mode", False),
            "monitored": config.get("monitored", False),
            "call_recording_disclosure": config.get("call_recording_disclosure", False),
            "present_focused": config.get("corrections_mode", False),
            "confidentiality_disclaimer": config.get("corrections_mode", False),
        }
