"""
Coach-Story Bridge — coaching judgment → SSE / Thera-World calibration.

Resolves assigned coach, recent session notes, and per-client overrides
for narrative generation (see thera_world_engine.compose_journey_narrative).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CoachStoryBridge:
    def __init__(self, db_pool):
        self.db = db_pool

    async def get_coaching_calibration(self, client_user_id: str) -> Dict[str, Any]:
        """
        Get coaching overrides and recent notes that affect story generation for this client.

        ``client_user_id`` is the same identifier Thera-World uses (hardware_id or username).
        """
        if not self.db or not (client_user_id or "").strip():
            return {"has_coach": False, "overrides": {}}

        coach_id = await self._get_coach_for_client(client_user_id)
        if not coach_id:
            return {"has_coach": False, "overrides": {}}

        notes = await self._get_recent_notes(coach_id, client_user_id)
        overrides = await self._get_active_overrides(coach_id, client_user_id)

        return {
            "has_coach": True,
            "coach_id": coach_id,
            "recent_notes": notes,
            "overrides": overrides,
            "coach_recommended_focus": overrides.get("focus_domain"),
            "coach_pacing_override": overrides.get("pacing"),
            "coach_hold_active": bool(overrides.get("clinical_hold", False)),
        }

    async def _get_coach_for_client(self, client_id: str) -> Optional[str]:
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT coach_id FROM coach_assignments
                    WHERE entity_type = 'client' AND entity_id = $1
                    ORDER BY is_primary DESC NULLS LAST, assigned_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    client_id,
                )
                if row and row["coach_id"]:
                    return str(row["coach_id"]).strip()

                row2 = await conn.fetchrow(
                    """
                    SELECT COALESCE(
                        NULLIF(TRIM(profile_data->>'assigned_coach'), ''),
                        NULLIF(TRIM(profile_data->>'coach_id'), ''),
                        NULLIF(TRIM(profile_data->>'assigned_coach_id'), '')
                    ) AS cid
                    FROM users
                    WHERE hardware_id = $1 OR username = $1
                    LIMIT 1
                    """,
                    client_id,
                )
                if row2 and row2["cid"]:
                    return str(row2["cid"]).strip()
        except Exception as e:
            logger.warning("CoachStoryBridge._get_coach_for_client: %s", e)
        return None

    async def _get_recent_notes(self, coach_id: str, client_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self.db:
            return out
        try:
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT coach_notes, notes, created_at, updated_at
                    FROM coaching_sessions
                    WHERE client_id = $1 AND coach_id = $2
                      AND (
                          NULLIF(TRIM(COALESCE(coach_notes, '')), '') IS NOT NULL
                          OR NULLIF(TRIM(COALESCE(notes, '')), '') IS NOT NULL
                      )
                    ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST
                    LIMIT 5
                    """,
                    client_id,
                    coach_id,
                )
                for r in rows:
                    snippet = (r["coach_notes"] or r["notes"] or "").strip()
                    if not snippet:
                        continue
                    ts = r["updated_at"] or r["created_at"]
                    out.append({
                        "text": snippet[:500],
                        "source": "coaching_session",
                        "at": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    })

                coach_uuid = await conn.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                    coach_id,
                )
                client_uuid = await conn.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                    client_id,
                )
                if coach_uuid and client_uuid:
                    try:
                        rows2 = await conn.fetch(
                            """
                            SELECT COALESCE(NULLIF(TRIM(redacted_content), ''), content) AS body,
                                   status, created_at
                            FROM coach_notes
                            WHERE coach_id = $1 AND client_id = $2
                            ORDER BY created_at DESC
                            LIMIT 3
                            """,
                            coach_uuid,
                            client_uuid,
                        )
                        for r2 in rows2:
                            body = (r2["body"] or "").strip()
                            if not body:
                                continue
                            ts2 = r2["created_at"]
                            out.append({
                                "text": body[:500],
                                "source": "coach_notes",
                                "status": r2.get("status"),
                                "at": ts2.isoformat() if hasattr(ts2, "isoformat") else str(ts2),
                            })
                    except Exception as _cn_err:
                        logger.debug("CoachStoryBridge coach_notes optional query: %s", _cn_err)

                out.sort(key=lambda x: x.get("at") or "", reverse=True)
                return out[:5]
        except Exception as e:
            logger.warning("CoachStoryBridge._get_recent_notes: %s", e)
        return out

    async def _get_active_overrides(self, coach_id: str, client_id: str) -> Dict[str, Any]:
        if not self.db:
            return {}
        try:
            from app.services.coach_override_protocol import filter_active_overrides

            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT focus_domain, pacing, clinical_hold, mission_priority, notes, updated_at,
                           expires_at, focus_domain_expires_at
                    FROM coach_client_overrides
                    WHERE coach_user_id = $1 AND client_user_id = $2
                    """,
                    coach_id,
                    client_id,
                )
                if not row:
                    return {}
                return filter_active_overrides(row)
        except Exception as e:
            logger.warning("CoachStoryBridge._get_active_overrides: %s", e)
        return {}
