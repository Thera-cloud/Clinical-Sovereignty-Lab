"""§15.8 Workspace Vault-consent records. Versioned; hardware_id only."""

from __future__ import annotations

from typing import Any, Dict, Optional

WORKSPACE_CONSENT_VERSION = "workspace_vault_v1"


async def record_workspace_consent(
    db_pool,
    *,
    coach_id: str,
    client_id: Optional[str] = None,
    document_ref: str = "GOOGLE_WS_OAUTH",
    version: str = WORKSPACE_CONSENT_VERSION,
) -> Optional[Dict[str, Any]]:
    hw = (coach_id or "").strip()
    if not hw or db_pool is None:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO consent_records (coach_id, client_id, version, document_ref)
            VALUES ($1, $2, $3, $4)
            RETURNING id, coach_id, client_id, version, document_ref, recorded_at
            """,
            hw,
            (client_id or "").strip() or None,
            version,
            (document_ref or "GOOGLE_WS_OAUTH")[:200],
        )
    return dict(row) if row else None
