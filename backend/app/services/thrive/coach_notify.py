"""Coach email notifier for growth-phase promotions — QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

from typing import Any, Dict, Optional


def make_email_notifier(notification_system: Any):
    """Return the NotifyFn used by phase_resolver.evaluate."""

    async def _notify(coach_username: str, subject: str, body: str, meta: Dict[str, Any]) -> None:
        email = (meta or {}).get("coach_email")
        if not (notification_system and email):
            return
        html = (
            f"<div style=\"font-family:'DM Sans',sans-serif;color:#e2e8f0;line-height:1.6\">"
            f"<p>{body}</p>"
            f"<p>Open Coach Command to review the phase badge, override if needed, "
            f"and see the client's goal trajectories.</p></div>"
        )
        await notification_system._send_email(
            email, subject, html, notification_type="thrive_phase_promoted",
        )

    return _notify


async def pending_promotions(db_pool: Any, coach_username: str, *, limit: int = 20) -> list:
    if not db_pool or not coach_username:
        return []
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id::text AS id, n.title, n.content, n.status, n.metadata, n.scheduled_at
            FROM nate_nudges n
            JOIN users c ON c.id = n.user_id
            WHERE c.username = $1
              AND n.nudge_type = 'client_phase_promoted'
              AND n.status IN ('pending', 'sent')
            ORDER BY n.scheduled_at DESC
            LIMIT $2
            """,
            coach_username, limit,
        )
    out = []
    for r in rows:
        d = dict(r)
        meta = d.get("metadata")
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        d["metadata"] = meta or {}
        d["client"] = (d["metadata"] or {}).get("client")
        if d.get("scheduled_at"):
            d["scheduled_at"] = d["scheduled_at"].isoformat()
        out.append(d)
    return out
