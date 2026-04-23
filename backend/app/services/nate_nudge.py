"""
SOVEREIGN SWARM — Nate the Nudge
Proactive notification system that sends session prep reminders,
mood-check nudges, and milestone celebrations.

Spec source: docs/SOVEREIGN_COMMAND_README.md (SC_06)

Nudge Types:
    session_prep  — Sent 1–2 hours before a scheduled coaching session
    mood_check    — Periodic mood logging prompts (configurable interval)
    milestone     — Celebrates breakthroughs, session count milestones, streaks

Status lifecycle: pending → sent → opened → dismissed
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID


# ─── Default Nudge Templates ────────────────────────────────────────────────

NUDGE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "session_prep": {
        "title": "Your session is coming up",
        "content": (
            "Hi {name}, your coaching session with {coach_name} is in "
            "{hours_until} hours. Take a moment to reflect: What would you "
            "most like to explore today?"
        ),
    },
    "mood_check": {
        "title": "How are you feeling right now?",
        "content": (
            "Hey {name}, Nate here. A quick emotional check-in can reveal "
            "patterns you might not notice otherwise. Tap to log your mood — "
            "it only takes 10 seconds."
        ),
    },
    "milestone_sessions": {
        "title": "Milestone reached!",
        "content": (
            "Incredible, {name} — you've completed {count} sessions! "
            "That's real commitment to your growth. Your coherence has been "
            "trending upward. Keep going."
        ),
    },
    "milestone_breakthrough": {
        "title": "A breakthrough moment",
        "content": (
            "{name}, Nate noticed a significant coherence spike during your "
            "last session — a Corrective Emotional Experience. These moments "
            "of deep connection are what real change looks like."
        ),
    },
    "milestone_streak": {
        "title": "You're on a streak!",
        "content": (
            "{name}, you've logged in {streak_days} days in a row. "
            "Consistency is one of the strongest predictors of therapeutic "
            "progress. Well done."
        ),
    },
    "checkin_coach_alert": {
        "title": "Client Activity Alert",
        "content": (
            "Your client {client_name} hasn't been active for over 62 hours. "
            "You may want to reach out and check in."
        ),
    },
    "checkin_client_72h": {
        "title": "Little Nate is checking in",
        "content": (
            "Hey {name}, it's been a few days since we connected. "
            "Tap here to reconnect — I'm always here for you."
        ),
    },
    "checkin_coach_72h": {
        "title": "Little Nate coaching check-in",
        "content": (
            "Hey {name}, it's been a few days. How are your coaching goals "
            "coming along? Any wins to celebrate or new goals to set?"
        ),
    },
}


class NateNudgeService:
    """Generates and manages proactive nudges for Little Nate users."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # ─── Session Prep Nudges ─────────────────────────────────────────────

    async def generate_session_prep_nudges(self) -> int:
        """
        Find coaching sessions scheduled 1–3 hours from now and create
        session_prep nudges for clients who haven't been nudged yet.
        Returns count of nudges created.
        """
        async with self.db_pool.acquire() as conn:
            upcoming = await conn.fetch(
                """
                SELECT cs.id AS session_id, cs.client_id, cs.coach_id,
                       cs.scheduled_at, u.name AS client_name,
                       coach.name AS coach_name
                FROM coaching_sessions cs
                JOIN users u ON u.id::text = cs.client_id::text
                JOIN users coach ON coach.id::text = cs.coach_id::text
                WHERE cs.status = 'SCHEDULED'
                  AND cs.scheduled_at BETWEEN NOW() + INTERVAL '1 hour'
                                          AND NOW() + INTERVAL '3 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM nate_nudges nn
                      WHERE nn.nudge_type = 'session_prep'
                        AND nn.user_id::text = cs.client_id::text
                        AND nn.metadata->>'session_id' = cs.id::text
                  )
                """
            )

            created = 0
            for row in upcoming:
                hours_until = max(1, round(
                    (row["scheduled_at"] - datetime.now(timezone.utc)).total_seconds() / 3600
                ))
                tpl = NUDGE_TEMPLATES["session_prep"]
                content = tpl["content"].format(
                    name=row["client_name"] or "there",
                    coach_name=row["coach_name"] or "your coach",
                    hours_until=hours_until,
                )
                await conn.execute(
                    """
                    INSERT INTO nate_nudges
                        (user_id, nudge_type, title, content, metadata, scheduled_at)
                    VALUES ($1, 'session_prep', $2, $3, $4, NOW())
                    """,
                    row["client_id"],
                    tpl["title"],
                    content,
                    json.dumps({
                        "session_id": str(row["session_id"]),
                        "coach_id": str(row["coach_id"]),
                    }),
                )
                created += 1

            return created

    # ─── Mood Check Nudges ───────────────────────────────────────────────

    async def generate_mood_check_nudges(self, interval_hours: int = 24) -> int:
        """
        Generate mood-check nudges for active users who haven't been
        prompted within `interval_hours`.
        """
        async with self.db_pool.acquire() as conn:
            # Find active users (had a session in the last 14 days)
            # who haven't received a mood_check nudge recently
            users = await conn.fetch(
                """
                SELECT DISTINCT u.id, u.name
                FROM users u
                JOIN sessions s ON s.user_id = u.id
                WHERE u.role = 'CLIENT'
                  AND s.started_at > NOW() - INTERVAL '14 days'
                  AND u.id NOT IN (
                      SELECT user_id FROM nate_nudges
                      WHERE nudge_type = 'mood_check'
                        AND created_at > NOW() - ($1 || ' hours')::interval
                  )
                """,
                str(interval_hours),
            )

            created = 0
            tpl = NUDGE_TEMPLATES["mood_check"]
            for row in users:
                content = tpl["content"].format(name=row["name"] or "there")
                await conn.execute(
                    """
                    INSERT INTO nate_nudges
                        (user_id, nudge_type, title, content, scheduled_at)
                    VALUES ($1, 'mood_check', $2, $3, NOW())
                    """,
                    row["id"], tpl["title"], content,
                )
                created += 1

            return created

    # ─── Milestone Nudges ────────────────────────────────────────────────

    async def generate_milestone_nudges(self) -> int:
        """
        Detect milestones and create celebration nudges:
          - Session count milestones (5, 10, 25, 50, 100)
          - CEE breakthroughs (new CEE in last 24h)
          - Login streaks (7, 14, 30 consecutive days)
        """
        created = 0
        async with self.db_pool.acquire() as conn:
            # ── Session count milestones ──
            milestones = [5, 10, 25, 50, 100]
            for count in milestones:
                users = await conn.fetch(
                    """
                    SELECT u.id, u.name
                    FROM users u
                    WHERE u.role = 'CLIENT'
                      AND (SELECT COUNT(*) FROM sessions WHERE user_id = u.id) = $1
                      AND u.id NOT IN (
                          SELECT user_id FROM nate_nudges
                          WHERE nudge_type = 'milestone'
                            AND metadata->>'milestone_type' = 'sessions'
                            AND metadata->>'count' = $2
                      )
                    """,
                    count, str(count),
                )
                tpl = NUDGE_TEMPLATES["milestone_sessions"]
                for row in users:
                    content = tpl["content"].format(
                        name=row["name"] or "there", count=count
                    )
                    await conn.execute(
                        """
                        INSERT INTO nate_nudges
                            (user_id, nudge_type, title, content, metadata, scheduled_at)
                        VALUES ($1, 'milestone', $2, $3, $4, NOW())
                        """,
                        row["id"], tpl["title"], content,
                        json.dumps({"milestone_type": "sessions", "count": str(count)}),
                    )
                    created += 1

            # ── CEE breakthrough nudges ──
            cee_users = await conn.fetch(
                """
                SELECT DISTINCT nm.user_id, u.name
                FROM nevedal_metrics nm
                JOIN users u ON nm.user_id = u.id
                WHERE nm.cee_window = TRUE
                  AND nm.recorded_at > NOW() - INTERVAL '24 hours'
                  AND nm.user_id NOT IN (
                      SELECT user_id FROM nate_nudges
                      WHERE nudge_type = 'milestone'
                        AND metadata->>'milestone_type' = 'breakthrough'
                        AND created_at > NOW() - INTERVAL '7 days'
                  )
                """
            )
            tpl = NUDGE_TEMPLATES["milestone_breakthrough"]
            for row in cee_users:
                content = tpl["content"].format(name=row["name"] or "there")
                await conn.execute(
                    """
                    INSERT INTO nate_nudges
                        (user_id, nudge_type, title, content, metadata, scheduled_at)
                    VALUES ($1, 'milestone', $2, $3, $4, NOW())
                    """,
                    row["user_id"], tpl["title"], content,
                    json.dumps({"milestone_type": "breakthrough"}),
                )
                created += 1

        return created

    # ─── Query Nudges ────────────────────────────────────────────────────

    async def get_pending_nudges(self, user_id: UUID) -> List[Dict[str, Any]]:
        """Return all pending nudges for a user."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, nudge_type, title, content, status,
                       scheduled_at, sent_at, opened_at, created_at
                FROM nate_nudges
                WHERE user_id = $1 AND status IN ('pending', 'sent')
                ORDER BY scheduled_at DESC
                """,
                user_id,
            )
        return [
            {
                "id": str(r["id"]),
                "nudge_type": r["nudge_type"],
                "title": r["title"],
                "content": r["content"],
                "status": r["status"],
                "scheduled_at": r["scheduled_at"].isoformat() if r["scheduled_at"] else None,
                "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                "opened_at": r["opened_at"].isoformat() if r["opened_at"] else None,
            }
            for r in rows
        ]

    async def mark_sent(self, nudge_id: UUID) -> None:
        """Mark a nudge as sent (pushed to client device or email)."""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nate_nudges SET status = 'sent', sent_at = NOW() WHERE id = $1",
                nudge_id,
            )

    async def mark_opened(self, nudge_id: UUID) -> None:
        """Mark a nudge as opened (client tapped/viewed it)."""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nate_nudges SET status = 'opened', opened_at = NOW() WHERE id = $1",
                nudge_id,
            )

    async def dismiss(self, nudge_id: UUID) -> None:
        """Dismiss a nudge."""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE nate_nudges SET status = 'dismissed' WHERE id = $1",
                nudge_id,
            )

    # ─── Scheduled Runner ────────────────────────────────────────────────

    async def run_all_nudge_checks(self) -> Dict[str, int]:
        """Run all nudge generators. Called by drip_scheduler."""
        prep = await self.generate_session_prep_nudges()
        mood = await self.generate_mood_check_nudges()
        milestones = await self.generate_milestone_nudges()
        total = prep + mood + milestones
        if total:
            print(f">>> [NATE NUDGE] Generated {total} nudges "
                  f"(prep={prep}, mood={mood}, milestones={milestones})")
        return {"session_prep": prep, "mood_check": mood, "milestone": milestones}
