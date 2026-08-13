"""AC30 staging drill: destroy test-client DEK while erasure UI stays off.

ENABLE_CLINICAL_ERASURE remains false. Only hardware_id prefix AC30_.
Legal holds block the drill. Crystals are anonymized, not deleted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.services.coach_credential_service import has_active_legal_hold
from app.services.google_workspace_service import FlagOff

AC30_CLIENT_PREFIX = "AC30_"

# Counsel placeholder until O6. Values are not operational.
RETENTION_MATRIX = {
    "status": "placeholder_until_counsel",
    "session_notes_days": None,
    "voice_recordings_days": None,
    "crystals": "anonymize_on_erasure_not_delete",
}


class Ac30Refused(PermissionError):
    """Drill refused: wrong client prefix or legal hold."""


async def run_ac30_drill(db_pool, client_id: str) -> Dict[str, Any]:
    hw = (client_id or "").strip()
    if not hw.startswith(AC30_CLIENT_PREFIX):
        raise Ac30Refused("AC30 drill only for AC30_ test clients")
    if await has_active_legal_hold(db_pool, hw):
        raise Ac30Refused("legal hold active")
    destroyed = 0
    anonymized = 0
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE client_data_keys
            SET destroyed_at = $2
            WHERE client_id = $1 AND destroyed_at IS NULL
            """,
            hw,
            datetime.now(timezone.utc),
        )
        try:
            destroyed = int(str(result).split()[-1])
        except (ValueError, IndexError):
            destroyed = 0
        result2 = await conn.execute(
            """
            UPDATE nate_intelligence_crystals
            SET crystal_text = '[anonymized]',
                source_type = COALESCE(source_type, 'ac30') || ':anonymized'
            WHERE user_id IN (SELECT id FROM users WHERE hardware_id = $1)
              AND COALESCE(scope, '') <> 'archived'
            """,
            hw,
        )
        try:
            anonymized = int(str(result2).split()[-1])
        except (ValueError, IndexError):
            anonymized = 0
    return {
        "ok": True,
        "client_id": hw,
        "keys_destroyed": destroyed,
        "crystals_anonymized": anonymized,
        "erasure_ui": False,
        "enable_clinical_erasure": False,
        "retention_matrix": RETENTION_MATRIX,
    }


def erasure_ui_allowed() -> None:
    """Prod request UI stays off until O6. Raise if someone wires a button."""
    import os

    if os.getenv("ENABLE_CLINICAL_ERASURE", "false").strip().lower() not in ("1", "true", "yes"):
        raise FlagOff("ENABLE_CLINICAL_ERASURE")
