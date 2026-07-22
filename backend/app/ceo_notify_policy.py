"""CEO inbox external notify policy — staging must not email production inboxes.

# QUANTUM-CRYSTAL-ARCH — Dual-COO staging isolation
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def ceo_external_notify_enabled() -> bool:
    """Whether SendGrid/Twilio CEO proposal emails may leave the container."""
    explicit = os.getenv("ENABLE_CEO_INBOX_EXTERNAL_NOTIFY", "").strip().lower()
    if explicit in ("true", "1", "yes", "on"):
        return True
    if explicit in ("false", "0", "no", "off"):
        return False
    env = os.getenv("ENVIRONMENT", "production").strip().lower()
    return env not in ("staging", "test")


def resolve_ceo_notify_email(proposal: Optional[Dict[str, Any]] = None) -> str:
    """Destination for CEO proposal / escalation emails."""
    if proposal:
        meta = proposal.get("metadata")
        if isinstance(meta, str):
            try:
                import json

                meta = json.loads(meta)
            except Exception:
                meta = {}
        if isinstance(meta, dict):
            stored = (meta.get("ceo_notify_email") or "").strip()
            if stored:
                return stored
    return (
        os.getenv("CEO_NOTIFY_EMAIL", "admin_nevedalnj@sovereignsanctuary.net").strip()
        or "admin_nevedalnj@sovereignsanctuary.net"
    )
