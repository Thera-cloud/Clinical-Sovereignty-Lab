"""
Sovereign Vault — Tier Entitlements (Locked Pricing Model v3)

This is the single source of truth for what each tier can access in the vault.
"""

from enum import Enum
from typing import Dict, Any

class VaultTier(str, Enum):
    THRESHOLD = "TRIAL"        # Trial users
    INNER_CHAMBER = "STANDARD" # $49/mo (founding: $39)
    SOVEREIGN_CIRCLE = "TOP_TIER"  # $149/mo (founding: $119)

VAULT_ENTITLEMENTS: Dict[str, Dict[str, Any]] = {
    "TRIAL": {
        "vault_enabled": False,
        "upload_enabled": True,  # Can upload in chat but items are temporary
        "storage_limit_bytes": 0,  # No persistent storage
        "folder_limit": 0,
        "file_ttl_seconds": 86400,  # 24hr auto-delete
        "max_upload_mb": 25,
        "text_injection": True,
        "image_injection": False,
        "text_truncate_chars": 5000,
        "transfer_crystal": False,
        "vault_search": False,
        "annotations": False,
        "dream_journal": False,
        "vault_export": False,
        "proactive_suggestions": False,
        "timeline_view": False,
        "side_by_side": False,
        "legacy_letters": False,
        "voice_over_image": False,
        "nevedal_reports": 0,
        "foresight_reports": 0,
        "archivist_chapters": 0,
        "me2me_avatar_hours": 0,
    },
    "STANDARD": {
        "vault_enabled": True,
        "upload_enabled": True,
        "storage_limit_bytes": 1 * 1024 * 1024 * 1024,  # 1 GB
        "folder_limit": 10,  # custom folders (system folders don't count)
        "file_ttl_seconds": 0,  # permanent
        "max_upload_mb": 25,
        "text_injection": True,
        "image_injection": True,  # low-res
        "text_truncate_chars": 8000,
        "transfer_crystal": True,
        "vault_search": True,
        "annotations": True,
        "dream_journal": True,
        "vault_export": True,
        "proactive_suggestions": False,
        "timeline_view": False,
        "side_by_side": False,
        "legacy_letters": False,
        "voice_over_image": False,
        "nevedal_types": 2,
        "nevedal_reports_per_month": 2,
        "foresight_reports_per_month": 4,
        "archivist_chapters": 0,
        "me2me_avatar_hours": 0,
    },
    "TOP_TIER": {
        "vault_enabled": True,
        "upload_enabled": True,
        "storage_limit_bytes": 50 * 1024 * 1024 * 1024,  # 50 GB
        "folder_limit": -1,  # unlimited
        "file_ttl_seconds": 0,  # permanent
        "max_upload_mb": 200,
        "text_injection": True,
        "image_injection": True,  # high-res
        "text_truncate_chars": 50000,
        "transfer_crystal": True,
        "vault_search": True,
        "annotations": True,
        "dream_journal": True,
        "vault_export": True,
        "proactive_suggestions": True,
        "timeline_view": True,
        "side_by_side": True,
        "legacy_letters": True,
        "voice_over_image": True,
        "nevedal_types": 5,
        "nevedal_reports_per_month": 8,
        "foresight_reports_per_month": -1,  # unlimited
        "archivist_chapters_per_month": 10,
        "me2me_avatar_hours_per_month": 10,
        "pattern_engine": True,
        "realtime_voice": True,
    },
}


def get_entitlements(tier: str) -> dict:
    """Get vault entitlements for a tier. Falls back to TRIAL if unknown."""
    return VAULT_ENTITLEMENTS.get(tier, VAULT_ENTITLEMENTS["TRIAL"])


def check_feature(tier: str, feature: str) -> bool:
    """Check if a specific feature is enabled for a tier."""
    ent = get_entitlements(tier)
    return bool(ent.get(feature, False))


def get_storage_limit(tier: str) -> int:
    """Get storage limit in bytes for a tier."""
    return get_entitlements(tier)["storage_limit_bytes"]


def get_folder_limit(tier: str) -> int:
    """Get custom folder limit for a tier (-1 = unlimited)."""
    return get_entitlements(tier)["folder_limit"]


def get_text_truncate(tier: str) -> int:
    """Get text injection truncation limit in chars."""
    return get_entitlements(tier)["text_truncate_chars"]
