"""
SOVEREIGN SWARM — Deadman Switch Service
Monitors user activity and triggers alerts when silence exceeds thresholds.

Spec source: docs/SOVEREIGN_COMMAND_README.md (SC_07)

When a client with elevated risk goes silent (no sessions, no mood logs,
no logins) beyond a configurable threshold, the system:
    1. Creates an urgent notification for the assigned coach
    2. Sends an email alert to the clinical team
    3. Logs the event in the audit trail

Activity sources checked (clients):
    - sessions (started_at)
    - nate_nudges (opened_at)
    - audit_log (logged_at)
    - users.last_nate_message_at (Little Nate conversations)

Additional monitors:
    - Coach accounts: assigned clients but no sessions in 14 days
    - Suspicious accounts: created 7+ days ago, logged in, zero engagement
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
COACH_SESSION_GAP_DAYS = 14               # Alert if coach has 0 sessions in this window
COACH_ALERT_COOLDOWN_DAYS = 7             # Don't re-alert coach within this window
SUSPICIOUS_ACCOUNT_AGE_DAYS = 7           # Account must be older than this to flag
SUSPICIOUS_ALERT_COOLDOWN_DAYS = 14       # Don't re-alert for same suspicious account


class DeadmanSwitchService:
    """Monitors user silence and fires alerts when thresholds are exceeded."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # ─── Client Silence Monitor ──────────────────────────────────────────────

    async def check_all_clients(self) -> Dict[str, Any]:
        """
        Scan all active clients for silence.
        Only monitors clients with at least one session OR one Nate message
        (minimum engagement filter — prevents false positives on abandoned accounts).
        Returns summary of alerts generated.
        """
        alerts_generated = 0
        clients_checked = 0
        skipped_no_engagement = 0

        async with self.db_pool.acquire() as conn:
            # Get active clients who have SOME engagement
            # (at least one session OR at least one Nate message)
            clients = await conn.fetch(
                """
                SELECT u.id, u.name, u.email, u.family_id,
                       u.last_nate_message_at,
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
                  AND u.deleted_at IS NULL
                  AND (
                      EXISTS (SELECT 1 FROM sessions WHERE user_id = u.id)
                      OR u.last_nate_message_at IS NOT NULL
                  )
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

                # Check latest activity across all sources (including Nate messages)
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
                last_nate_msg = client["last_nate_message_at"]

                # Determine most recent activity (4 sources now)
                activities = [
                    ts for ts in [last_session, last_nudge_open, last_audit, last_nate_msg]
                    if ts
                ]
                if not activities:
                    skipped_no_engagement += 1
                    continue
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

                        # Admin Contact Shield: SMS for HIGH/CRITICAL risk silence
                        if risk_level in ("HIGH", "CRITICAL"):
                            try:
                                from app.services.security.admin_contact_shield import get_shield
                                await get_shield().alert_admin(
                                    f"DEADMAN: {risk_level} risk client silent {silence_hours}h",
                                    f"Client '{client['name'] or 'unnamed'}' (risk: {risk_level}) "
                                    f"silent for {silence_hours} hours. Last active: {last_active.isoformat()}."
                                )
                            except Exception:
                                pass

        return {
            "clients_checked": clients_checked,
            "skipped_no_engagement": skipped_no_engagement,
            "alerts_generated": alerts_generated,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── Coach Session Monitor ───────────────────────────────────────────────

    async def check_coaches_without_sessions(self) -> Dict[str, Any]:
        """
        Find coaches who have assigned clients but no COACH sessions
        created or scheduled in the last COACH_SESSION_GAP_DAYS days.
        Alerts admin via nate_nudges so Big Nate can act.
        """
        alerts_generated = 0
        coaches_checked = 0

        window = datetime.now(timezone.utc) - timedelta(days=COACH_SESSION_GAP_DAYS)
        cooldown = datetime.now(timezone.utc) - timedelta(days=COACH_ALERT_COOLDOWN_DAYS)

        async with self.db_pool.acquire() as conn:
            # Find coaches who appear as assigned_coach for at least one client
            coaches = await conn.fetch(
                """
                SELECT DISTINCT u_coach.id   AS coach_id,
                       u_coach.name          AS coach_name,
                       COUNT(u_client.id)    AS assigned_count
                FROM users u_coach
                JOIN users u_client
                  ON u_client.assigned_coach = u_coach.id
                 AND u_client.role = 'CLIENT'
                 AND u_client.deleted_at IS NULL
                WHERE u_coach.role = 'COACH'
                  AND u_coach.deleted_at IS NULL
                GROUP BY u_coach.id, u_coach.name
                """
            )

            for coach in coaches:
                coaches_checked += 1
                coach_id = coach["coach_id"]
                coach_name = coach["coach_name"] or "Coach"
                assigned_count = coach["assigned_count"]

                # Check if ANY coach-type session exists for this coach's clients
                recent_session = await conn.fetchval(
                    """
                    SELECT 1 FROM sessions s
                    JOIN users u_client ON u_client.id = s.user_id
                    WHERE u_client.assigned_coach = $1
                      AND s.session_type = 'COACH'
                      AND s.started_at > $2
                    LIMIT 1
                    """,
                    coach_id, window,
                )

                if recent_session:
                    continue

                # No sessions — check cooldown
                recent_alert = await conn.fetchval(
                    """SELECT id FROM nate_nudges
                       WHERE user_id = $1
                         AND nudge_type = 'coach_no_sessions_alert'
                         AND created_at > $2""",
                    coach_id, cooldown,
                )

                if not recent_alert:
                    alert_title = f"[Coach Gap] {coach_name} — 0 sessions in {COACH_SESSION_GAP_DAYS}d"
                    alert_content = (
                        f"Coach {coach_name} has {assigned_count} assigned client(s) "
                        f"but zero COACH sessions in the last {COACH_SESSION_GAP_DAYS} days. "
                        f"Please audit this coach's engagement."
                    )
                    alert_metadata = json.dumps({
                        "alert_type": "coach_no_sessions",
                        "coach_id": str(coach_id),
                        "coach_name": coach_name,
                        "assigned_clients": assigned_count,
                        "window_days": COACH_SESSION_GAP_DAYS,
                    })

                    # Alert on the coach's own nudge feed
                    await conn.execute(
                        """INSERT INTO nate_nudges
                            (user_id, nudge_type, title, content, metadata, scheduled_at, status)
                        VALUES ($1, 'coach_no_sessions_alert', $2, $3, $4, NOW(), 'pending')""",
                        coach_id, alert_title, alert_content, alert_metadata,
                    )

                    # Log to audit
                    await conn.execute(
                        """INSERT INTO audit_log
                            (action_type, target_id, description, ip_address)
                        VALUES ('COACH_SESSION_GAP', $1, $2, '0.0.0.0'::inet)""",
                        coach_id,
                        f"Coach {coach_name} has {assigned_count} clients but 0 "
                        f"sessions in {COACH_SESSION_GAP_DAYS}d",
                    )

                    alerts_generated += 1

        return {
            "coaches_checked": coaches_checked,
            "alerts_generated": alerts_generated,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── Suspicious / Probe Account Detection ───────────────────────────────

    async def check_suspicious_accounts(self) -> Dict[str, Any]:
        """
        Detect accounts that were created 7+ days ago and logged in at least
        once but have ZERO engagement (no sessions, no Nate messages).
        These could be abandoned registrations or hacker probe accounts.
        """
        flagged = 0

        age_cutoff = datetime.now(timezone.utc) - timedelta(days=SUSPICIOUS_ACCOUNT_AGE_DAYS)
        cooldown = datetime.now(timezone.utc) - timedelta(days=SUSPICIOUS_ALERT_COOLDOWN_DAYS)

        async with self.db_pool.acquire() as conn:
            suspects = await conn.fetch(
                """
                SELECT u.id, u.name, u.email, u.created_at, u.last_login
                FROM users u
                WHERE u.role = 'CLIENT'
                  AND u.deleted_at IS NULL
                  AND u.created_at < $1
                  AND u.last_login IS NOT NULL
                  AND u.last_nate_message_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM sessions WHERE user_id = u.id
                  )
                """,
                age_cutoff,
            )

            for suspect in suspects:
                user_id = suspect["id"]
                name = suspect["name"] or "Unknown"

                # Check cooldown
                recent_flag = await conn.fetchval(
                    """SELECT id FROM audit_log
                       WHERE action_type = 'SUSPICIOUS_INACTIVE_ACCOUNT'
                         AND target_id = $1
                         AND logged_at > $2""",
                    user_id, cooldown,
                )

                if recent_flag:
                    continue

                days_old = (datetime.now(timezone.utc) - suspect["created_at"]).days

                # Log to audit
                await conn.execute(
                    """INSERT INTO audit_log
                        (action_type, target_id, description, ip_address)
                    VALUES ('SUSPICIOUS_INACTIVE_ACCOUNT', $1, $2, '0.0.0.0'::inet)""",
                    user_id,
                    f"Suspicious: {name} created {days_old}d ago, logged in "
                    f"but zero sessions and zero Nate messages",
                )

                # Alert admin via nudge
                await conn.execute(
                    """INSERT INTO nate_nudges
                        (user_id, nudge_type, title, content, metadata, scheduled_at, status)
                    VALUES ($1, 'suspicious_account_alert', $2, $3, $4, NOW(), 'pending')""",
                    user_id,
                    f"[Suspicious] {name} — {days_old}d old, zero engagement",
                    f"Account '{name}' ({suspect['email'] or 'no email'}) was created "
                    f"{days_old} days ago and has logged in but shows zero sessions "
                    f"and zero Nate messages. This may be an abandoned registration "
                    f"or a probe account. Please review.",
                    json.dumps({
                        "alert_type": "suspicious_inactive",
                        "user_id": str(user_id),
                        "name": name,
                        "email": suspect["email"],
                        "days_old": days_old,
                        "last_login": suspect["last_login"].isoformat() if suspect["last_login"] else None,
                    }),
                )

                flagged += 1

        return {
            "flagged": flagged,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── Dashboard Query ─────────────────────────────────────────────────────

    async def get_silent_clients(self, threshold_hours: int = None) -> List[Dict[str, Any]]:
        """Return a list of currently silent clients (for dashboard).
        Includes last_nate_message_at in activity calculation."""
        if threshold_hours is None:
            threshold_hours = DEFAULT_SILENCE_THRESHOLD_HOURS

        threshold_time = datetime.now(timezone.utc) - timedelta(hours=threshold_hours)
        silent = []

        async with self.db_pool.acquire() as conn:
            clients = await conn.fetch(
                """
                SELECT u.id, u.name, u.email, u.last_nate_message_at, sub.last_active
                FROM users u
                JOIN LATERAL (
                    SELECT GREATEST(
                        (SELECT MAX(started_at) FROM sessions WHERE user_id = u.id),
                        (SELECT MAX(opened_at) FROM nate_nudges WHERE user_id = u.id),
                        u.last_nate_message_at
                    ) AS last_active
                ) sub ON TRUE
                WHERE u.role = 'CLIENT'
                  AND u.deleted_at IS NULL
                  AND (sub.last_active < $1 OR sub.last_active IS NULL)
                  AND (
                      EXISTS (SELECT 1 FROM sessions WHERE user_id = u.id)
                      OR u.last_nate_message_at IS NOT NULL
                  )
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
