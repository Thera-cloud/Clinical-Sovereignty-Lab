"""
SOVEREIGN SWARM — Deadman Switch Service
Monitors user activity and triggers alerts when silence exceeds thresholds.

Spec source: docs/SOVEREIGN_COMMAND_README.md (SC_07)

When a client with elevated risk goes silent (no sessions, no mood logs,
no logins) beyond a configurable threshold, the system:
    1. Creates an urgent notification for the assigned coach
    2. Sends an email alert to the clinical team
    3. Logs the event in the audit trail

Activity sources checked:
    - sessions (started_at)
    - nate_nudges (opened_at)
    - audit_log (logged_at)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID


# ─── Default Thresholds ──────────────────────────────────────────────────────

DEFAULT_SILENCE_THRESHOLD_HOURS = 72       # 3 days of no activity
HIGH_RISK_THRESHOLD_HOURS = 48             # 2 days for HIGH/CRITICAL risk clients
ALERT_COOLDOWN_HOURS = 24                  # Don't re-alert within this window


class DeadmanSwitchService:
    """Monitors user silence and fires alerts when thresholds are exceeded."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def check_all_clients(self) -> Dict[str, Any]:
        """
        Scan all active clients for silence.
        Returns summary of alerts generated.
        """
        alerts_generated = 0
        clients_checked = 0

        async with self.db_pool.acquire() as conn:
            # Get active clients with their risk level
            clients = await conn.fetch(
                """
                SELECT u.id, u.name, u.email, u.family_id,
                       nm.risk_level
                FROM users u
                LEFT JOIN LATERAL (
                    SELECT COALESCE(
                        (biometrics::jsonb->>'risk_level'),
                        'LOW'
                    ) AS risk_level
                    FROM nevedal_metrics
                    WHERE user_id = u.id
                    ORDER BY recorded_at DESC
                    LIMIT 1
                ) nm ON TRUE
                WHERE u.role = 'CLIENT'
                """
            )

            for client in clients:
                clients_checked += 1
                user_id = client["id"]
                risk_level = client.get("risk_level") or "LOW"

                # Determine threshold based on risk level
                if risk_level in ("HIGH", "CRITICAL"):
                    threshold_hours = HIGH_RISK_THRESHOLD_HOURS
                else:
                    threshold_hours = DEFAULT_SILENCE_THRESHOLD_HOURS

                threshold_time = datetime.now(timezone.utc) - timedelta(hours=threshold_hours)

                # Check latest activity across sources
                last_session = await conn.fetchval(
                    "SELECT MAX(started_at) FROM sessions WHERE user_id = $1",
                    user_id,
                )
                last_nudge_open = await conn.fetchval(
                    "SELECT MAX(opened_at) FROM nate_nudges WHERE user_id = $1",
                    user_id,
                )
                last_audit = await conn.fetchval(
                    """SELECT MAX(logged_at) FROM audit_log
                       WHERE admin_id = $1 OR target_id = $1::text""",
                    user_id,
                )

                # Determine most recent activity
                activities = [ts for ts in [last_session, last_nudge_open, last_audit] if ts]
                if not activities:
                    continue  # No activity data at all — new user, skip
                last_active = max(activities)

                if last_active < threshold_time:
                    # Silence detected — check we haven't already alerted recently
                    cooldown_time = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_HOURS)
                    recent_alert = await conn.fetchval(
                        """SELECT id FROM nate_nudges
                           WHERE user_id = $1
                             AND nudge_type = 'deadman_alert'
                             AND created_at > $2""",
                        user_id, cooldown_time,
                    )

                    if not recent_alert:
                        silence_hours = int(
                            (datetime.now(timezone.utc) - last_active).total_seconds() / 3600
                        )

                        alert_title = f"Silence Alert: {client['name'] or 'Client'}"
                        alert_content = (
                            f"{client['name'] or 'A client'} has been silent for "
                            f"{silence_hours} hours (risk level: {risk_level}). "
                            f"Last activity: {last_active.isoformat()}"
                        )
                        alert_metadata = json.dumps({
                            "alert_type": "deadman_switch",
                            "silence_hours": silence_hours,
                            "risk_level": risk_level,
                            "last_active": last_active.isoformat(),
                        })

                        # Create alert nudge on the client record
                        await conn.execute(
                            """INSERT INTO nate_nudges
                                (user_id, nudge_type, title, content, metadata, scheduled_at, status)
                            VALUES ($1, 'deadman_alert', $2, $3, $4, NOW(), 'pending')""",
                            user_id, alert_title, alert_content, alert_metadata,
                        )

                        # Route alert to assigned coach (PhD spec §SC_07)
                        assigned_coach_id = await conn.fetchval(
                            """SELECT assigned_coach FROM users WHERE id = $1""",
                            user_id,
                        )
                        if assigned_coach_id:
                            coach_title = f"[Deadman] {client['name'] or 'Client'} — {silence_hours}h silence"
                            coach_content = (
                                f"Your client {client['name'] or '(unnamed)'} has been silent for "
                                f"{silence_hours} hours. Risk level: {risk_level}. "
                                f"Last activity: {last_active.isoformat()}. "
                                f"Please consider reaching out."
                            )
                            await conn.execute(
                                """INSERT INTO nate_nudges
                                    (user_id, nudge_type, title, content, metadata, scheduled_at, status)
                                VALUES ($1, 'deadman_coach_alert', $2, $3, $4, NOW(), 'pending')""",
                                assigned_coach_id, coach_title, coach_content,
                                json.dumps({
                                    "alert_type": "deadman_switch_coach",
                                    "client_id": str(user_id),
                                    "client_name": client["name"] or "Client",
                                    "silence_hours": silence_hours,
                                    "risk_level": risk_level,
                                    "last_active": last_active.isoformat(),
                                }),
                            )

                        # Log to audit
                        await conn.execute(
                            """INSERT INTO audit_log
                                (action_type, target_id, description, ip_address)
                            VALUES ('DEADMAN_ALERT', $1, $2, '0.0.0.0'::inet)""",
                            user_id,
                            f"Deadman Switch: {client['name'] or 'Client'} silent for "
                            f"{silence_hours}h (risk: {risk_level})"
                            f"{' → coach notified' if assigned_coach_id else ''}",
                        )

                        alerts_generated += 1

        return {
            "clients_checked": clients_checked,
            "alerts_generated": alerts_generated,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_silent_clients(self, threshold_hours: int = None) -> List[Dict[str, Any]]:
        """Return a list of currently silent clients (for dashboard)."""
        if threshold_hours is None:
            threshold_hours = DEFAULT_SILENCE_THRESHOLD_HOURS

        threshold_time = datetime.now(timezone.utc) - timedelta(hours=threshold_hours)
        silent = []

        async with self.db_pool.acquire() as conn:
            clients = await conn.fetch(
                """
                SELECT u.id, u.name, u.email, sub.last_active
                FROM users u
                JOIN LATERAL (
                    SELECT GREATEST(
                        (SELECT MAX(started_at) FROM sessions WHERE user_id = u.id),
                        (SELECT MAX(opened_at) FROM nate_nudges WHERE user_id = u.id)
                    ) AS last_active
                ) sub ON TRUE
                WHERE u.role = 'CLIENT'
                  AND (sub.last_active < $1 OR sub.last_active IS NULL)
                """,
                threshold_time,
            )
            for row in clients:
                last = row["last_active"]
                silence_hrs = int(
                    (datetime.now(timezone.utc) - last).total_seconds() / 3600
                ) if last else None
                silent.append({
                    "user_id": str(row["id"]),
                    "name": row["name"],
                    "last_active": last.isoformat() if last else None,
                    "silence_hours": silence_hrs,
                })

        return silent
