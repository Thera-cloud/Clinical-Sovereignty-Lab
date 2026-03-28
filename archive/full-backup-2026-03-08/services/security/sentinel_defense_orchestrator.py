"""
SENTINEL DEFENSE ORCHESTRATOR — Central Coordinator

Wires the Sentinel freeze event to all Hive Defense systems:

1. SASE ban (persistent IP blocklist)
2. DEFCON escalation (SEVERE for freeze, ELEVATED for warning)
3. Mirror Shell containment (House of Mirrors — Patent Claim 30)
4. Freeze history forensic logging
5. Threat Dropbox auto-hunt submission
6. DEFCON Recon Report (full HTML email)
7. Live mirror timer (SMS updates to Nathan every 5min)
8. Projected Helix proposal (if mirror trap active > 10min)
9. Graduated response at warning thresholds

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("hive.sentinel_orchestrator")

MIRROR_TIMER_INTERVAL_SEC = 300  # 5 minutes
HELIX_PROPOSE_AFTER_SEC = 600   # 10 minutes of active trapping


class SentinelDefenseOrchestrator:
    """
    Central coordinator that reacts to Sentinel events (warnings, freezes)
    and activates the appropriate Hive Defense subsystems.
    """

    def __init__(
        self,
        db_pool=None,
        sase_controller=None,
        defcon_controller=None,
        mirror_shell=None,
        notification_system=None,
        admin_contact_shield=None,
        recon_reporter=None,
    ):
        self._db_pool = db_pool
        self._sase = sase_controller
        self._defcon = defcon_controller
        self._mirror_shell = mirror_shell
        self._ns = notification_system
        self._shield = admin_contact_shield
        self._recon = recon_reporter

        self._active_mirror_tasks: Dict[str, asyncio.Task] = {}
        self._active_freeze_ids: Dict[str, int] = {}

        logger.info("SentinelDefenseOrchestrator initialized")

    async def on_sentinel_freeze(
        self,
        *,
        uid: str,
        ip: str,
        user_agent: str = "",
        score: int,
        reasons: List[str],
        auth_method: str = "password",
        frozen_at: datetime,
    ) -> Dict[str, Any]:
        """
        Full freeze response — activated when Sentinel score crosses freeze threshold.
        Orchestrates: ban, DEFCON, mirror, log, recon, timer.
        """
        actions_taken = []
        freeze_id = None
        namespace_id = None
        trap_id = None

        # 1. Persistent IP ban via SASE
        try:
            if self._sase:
                self._sase.add_to_blocklist(ip, f"Sentinel freeze score={score}")
                actions_taken.append("ip_banned_sase")
            if self._db_pool:
                await self._persist_ban(ip, f"Sentinel freeze score={score}", score)
                actions_taken.append("ip_banned_persistent")
        except Exception as e:
            logger.warning("Orchestrator: SASE ban failed: %s", e)

        # 2. DEFCON escalation to SEVERE
        try:
            if self._defcon:
                await self._defcon.escalate(
                    self._defcon._state.level.__class__(2),  # SEVERE
                    f"Sentinel FREEZE: IP {ip}, score {score}, reasons: {', '.join(reasons[:3])}",
                )
                actions_taken.append("defcon_escalated_severe")
        except Exception as e:
            logger.warning("Orchestrator: DEFCON escalation failed: %s", e)

        # 3. Mirror Shell containment — trap in House of Mirrors
        try:
            if self._mirror_shell:
                ns_mgr = getattr(self._mirror_shell, "namespace_manager", None)
                if ns_mgr:
                    ns = await ns_mgr.create_namespace(
                        entity_identifier=ip,
                        seed_data={
                            "ip": ip,
                            "user_agent": user_agent,
                            "score": score,
                            "reasons": reasons,
                        },
                    )
                    namespace_id = str(ns.namespace_id) if hasattr(ns, "namespace_id") else str(uuid4())
                    trap_id = str(uuid4())
                    actions_taken.append("mirror_namespace_created")
                    actions_taken.append("house_of_mirrors_deployed")
        except Exception as e:
            logger.warning("Orchestrator: Mirror Shell containment failed: %s", e)

        # 4. Forensic log to sentinel_freeze_history
        try:
            if self._db_pool:
                import json
                async with self._db_pool.acquire() as conn:
                    freeze_id = await conn.fetchval(
                        """INSERT INTO sentinel_freeze_history
                           (ip, uid, user_agent, sentinel_score, reasons, actions_taken,
                            defcon_level, mirror_namespace_id, trap_id, frozen_at)
                           VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10)
                           RETURNING id""",
                        ip, uid, user_agent, score,
                        json.dumps(reasons), json.dumps(actions_taken),
                        2, namespace_id, trap_id, frozen_at,
                    )
                    actions_taken.append(f"freeze_logged_id={freeze_id}")
                    self._active_freeze_ids[ip] = freeze_id
        except Exception as e:
            logger.warning("Orchestrator: freeze history logging failed: %s", e)

        # 5. Auto-submit to Threat Dropbox
        try:
            if self._db_pool:
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO threat_dropbox_hunts
                           (hunt_text, submitted_by, status, created_at)
                           VALUES ($1, $2, 'pending', NOW())
                           ON CONFLICT DO NOTHING""",
                        f"SENTINEL FREEZE: IP={ip} Score={score} Reasons={'; '.join(reasons)}",
                        "sentinel_auto",
                    )
                    actions_taken.append("threat_dropbox_submitted")
        except Exception as e:
            logger.warning("Orchestrator: Threat Dropbox submission failed: %s", e)

        # 6. Send DEFCON Recon Report
        try:
            if self._recon and freeze_id:
                alert_emails = self._shield._alert_emails if self._shield else ["support@sovereignsanctuary.net"]
                await self._recon.generate_and_send(
                    freeze_id=freeze_id,
                    ip=ip,
                    uid=uid,
                    user_agent=user_agent,
                    sentinel_score=score,
                    reasons=reasons,
                    frozen_at=frozen_at,
                    defcon_level=2,
                    mirror_namespace_id=namespace_id,
                    trap_id=trap_id,
                    actions_taken=actions_taken,
                    alert_emails=alert_emails,
                )
                actions_taken.append("recon_report_sent")
        except Exception as e:
            logger.warning("Orchestrator: Recon report failed: %s", e)

        # 7. Defense alert via AdminContactShield
        try:
            if self._shield:
                await self._shield.alert_admin(
                    f"SENTINEL FREEZE — Score {score}",
                    f"IP: {ip}\nReasons: {', '.join(reasons[:3])}\n"
                    f"House of Mirrors: {'DEPLOYED' if namespace_id else 'FAILED'}\n"
                    f"DEFCON: SEVERE",
                )
                actions_taken.append("admin_alerted")
        except Exception as e:
            logger.warning("Orchestrator: Admin alert failed: %s", e)

        # 8. Start live mirror timer task (SMS every 5min)
        if namespace_id and freeze_id:
            task = asyncio.create_task(
                self._mirror_timer_loop(ip=ip, freeze_id=freeze_id, score=score)
            )
            self._active_mirror_tasks[ip] = task

        logger.warning(
            "SENTINEL DEFENSE ORCHESTRATED: IP=%s score=%d actions=%s",
            ip, score, actions_taken,
        )

        return {
            "freeze_id": freeze_id,
            "ip": ip,
            "score": score,
            "actions_taken": actions_taken,
            "namespace_id": namespace_id,
            "trap_id": trap_id,
        }

    async def on_sentinel_warning(
        self,
        *,
        uid: str,
        ip: str,
        score: int,
        reasons: List[str],
    ) -> None:
        """Graduated response at warning threshold (score >= 50, < freeze)."""
        # Escalate DEFCON to ELEVATED
        try:
            if self._defcon:
                await self._defcon.escalate(
                    self._defcon._state.level.__class__(4),  # ELEVATED
                    f"Sentinel WARNING: IP {ip}, score {score}",
                )
        except Exception as e:
            logger.warning("Orchestrator: DEFCON warning escalation failed: %s", e)

        # Alert admin
        try:
            if self._shield:
                await self._shield.alert_admin(
                    f"SENTINEL WARNING — Score {score}",
                    f"IP: {ip}\nReasons: {', '.join(reasons[:3])}\n"
                    f"Session continues under observation.",
                )
        except Exception as e:
            logger.warning("Orchestrator: Warning alert failed: %s", e)

    async def on_attacker_disengage(self, ip: str) -> None:
        """Called when attacker disconnects or trap is deactivated."""
        freeze_id = self._active_freeze_ids.pop(ip, None)

        task = self._active_mirror_tasks.pop(ip, None)
        if task and not task.done():
            task.cancel()

        if freeze_id and self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sentinel_freeze_history SET disengaged_at = NOW() WHERE id = $1",
                        freeze_id,
                    )
            except Exception as e:
                logger.warning("Orchestrator: disengage update failed: %s", e)

        # Send final disengagement SMS
        if self._shield and self._shield._alert_phone:
            try:
                if self._ns:
                    await self._ns.send_sms(
                        self._shield._alert_phone,
                        f"[SANCTUARY] Attacker disengaged. IP: {ip}. "
                        f"Mirror trap deactivated. System safe.",
                    )
            except Exception as e:
                logger.warning("Orchestrator: disengage SMS failed: %s", e)

        logger.info("Attacker disengaged: IP=%s freeze_id=%s", ip, freeze_id)

    async def _mirror_timer_loop(self, *, ip: str, freeze_id: int, score: int) -> None:
        """Send SMS updates to Nathan every 5 minutes during active mirror trap."""
        start = time.monotonic()
        update_count = 0

        while True:
            try:
                await asyncio.sleep(MIRROR_TIMER_INTERVAL_SEC)
            except asyncio.CancelledError:
                return

            update_count += 1
            elapsed_min = int((time.monotonic() - start) / 60)

            interactions = 0
            if self._db_pool:
                try:
                    async with self._db_pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT interactions_mirrored FROM sentinel_freeze_history WHERE id = $1",
                            freeze_id,
                        )
                        if row:
                            interactions = row["interactions_mirrored"] or 0
                except Exception:
                    pass

            sms_body = (
                f"[MIRROR TRAP ACTIVE] {elapsed_min}min\n"
                f"IP: {ip} | Score: {score}\n"
                f"Interactions mirrored: {interactions}\n"
                f"Reply STATUS for details"
            )

            if self._shield and self._shield._alert_phone and self._ns:
                try:
                    await self._ns.send_sms(self._shield._alert_phone, sms_body)
                except Exception as e:
                    logger.warning("Orchestrator: mirror timer SMS failed: %s", e)

            # After 10 min of trapping, propose Helix if not already proposed
            if elapsed_min >= 10 and update_count == 2:
                await self._propose_helix(ip=ip, freeze_id=freeze_id, score=score)

    async def _propose_helix(self, *, ip: str, freeze_id: int, score: int) -> None:
        """Propose a Projected Helix deployment — requires Nathan's approval."""
        if not self._db_pool:
            return

        approval_code = secrets.token_hex(4).upper()

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO helix_authorization
                       (approval_code, attacker_ip, sentinel_score, freeze_history_id,
                        proposed_at, expires_at)
                       VALUES ($1, $2, $3, $4, NOW(), NOW() + INTERVAL '30 minutes')""",
                    approval_code, ip, score, freeze_id,
                )
        except Exception as e:
            logger.warning("Orchestrator: Helix proposal DB insert failed: %s", e)
            return

        # Send approval request via both email and SMS
        approval_url = f"https://api.sovereignsanctuary.net/api/hive-defense/v4/projection/approve/{approval_code}"
        deny_url = f"https://api.sovereignsanctuary.net/api/hive-defense/v4/projection/deny/{approval_code}"

        if self._shield and self._shield._alert_phone and self._ns:
            try:
                await self._ns.send_sms(
                    self._shield._alert_phone,
                    f"[HELIX AUTHORIZATION]\n"
                    f"Attacker IP: {ip} | Score: {score}\n"
                    f"Mirror trap active 10+ min.\n"
                    f"Reply APPROVE {approval_code} to deploy Projected Helix\n"
                    f"Reply DENY {approval_code} to decline\n"
                    f"Expires in 30 min.",
                )
                if self._db_pool:
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE helix_authorization SET notification_sent_sms = TRUE "
                            "WHERE approval_code = $1",
                            approval_code,
                        )
            except Exception as e:
                logger.warning("Orchestrator: Helix SMS failed: %s", e)

        if self._shield and self._shield._alert_emails and self._ns:
            html = f"""
            <div style="font-family:'DM Sans',sans-serif;background:#050505;color:#E8D5A3;padding:32px;max-width:600px;margin:auto;">
                <h1 style="color:#EF4444;text-align:center;">PROJECTED HELIX AUTHORIZATION</h1>
                <p style="color:#ccc;text-align:center;">Attacker trapped in House of Mirrors for 10+ minutes.</p>
                <table style="width:100%;border-collapse:collapse;margin:16px 0;">
                    <tr><td style="color:#999;padding:4px;">Attacker IP</td>
                        <td style="color:#EF4444;font-weight:bold;">{ip}</td></tr>
                    <tr><td style="color:#999;padding:4px;">Sentinel Score</td>
                        <td style="color:#EF4444;">{score}</td></tr>
                    <tr><td style="color:#999;padding:4px;">Code</td>
                        <td style="color:#C9A962;font-weight:bold;">{approval_code}</td></tr>
                </table>
                <div style="text-align:center;margin:24px 0;">
                    <a href="{approval_url}" style="background:#EF4444;color:white;padding:12px 32px;
                       text-decoration:none;border-radius:6px;font-weight:bold;margin:8px;">
                        APPROVE HELIX
                    </a>
                    <a href="{deny_url}" style="background:#333;color:#ccc;padding:12px 32px;
                       text-decoration:none;border-radius:6px;font-weight:bold;margin:8px;">
                        DENY
                    </a>
                </div>
                <p style="color:#666;text-align:center;font-size:12px;">
                    This authorization expires in 30 minutes.<br>
                    Patent-Pending — Claims 53-56
                </p>
            </div>
            """
            for email in self._shield._alert_emails:
                try:
                    await self._ns._send_email(
                        to_email=email,
                        subject=f"[HELIX AUTH] Approve Projected Helix — IP {ip} — Code {approval_code}",
                        content=html,
                        notification_type="helix_authorization",
                    )
                    if self._db_pool:
                        async with self._db_pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE helix_authorization SET notification_sent_email = TRUE "
                                "WHERE approval_code = $1",
                                approval_code,
                            )
                except Exception as e:
                    logger.warning("Orchestrator: Helix email failed: %s", e)

        logger.warning("HELIX AUTHORIZATION PROPOSED: code=%s ip=%s", approval_code, ip)

    async def _persist_ban(self, ip: str, reason: str, score: int, banned_by: str = "sentinel") -> None:
        """Persist an IP ban to sentinel_banned_ips."""
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO sentinel_banned_ips (ip, reason, sentinel_score, banned_by)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (ip) DO UPDATE SET
                           reason = EXCLUDED.reason,
                           sentinel_score = GREATEST(sentinel_banned_ips.sentinel_score, EXCLUDED.sentinel_score),
                           banned_by = EXCLUDED.banned_by,
                           active = TRUE,
                           banned_at = NOW()""",
                    ip, reason, score, banned_by,
                )
        except Exception as e:
            logger.warning("Orchestrator: persist ban failed: %s", e)

    async def deploy_helix_containment(self, ip: str, reason: str) -> str:
        """
        HELIX House of Mirrors: Ban IP, add to SASE blocklist, and create Mirror Trap.
        Future traffic from this IP is routed to the decoy (House of Mirrors).
        """
        await self._persist_ban(ip, reason, 100, banned_by="helix")
        if self._sase:
            self._sase.add_to_blocklist(ip, f"HELIX: {reason}")
        namespace_id = await self._route_to_mirror(ip)
        logger.warning("HELIX containment deployed: ip=%s reason=%s namespace=%s", ip, reason[:80], namespace_id)
        return namespace_id

    async def check_preconnect_ban(self, ip: str) -> Optional[str]:
        """
        Pre-connection check: returns a mirror namespace ID if IP is banned
        (route to House of Mirrors instead of hard-blocking).
        Returns None if IP is clean.
        """
        if self._sase and ip in self._sase._dynamic_blocklist:
            return await self._route_to_mirror(ip)

        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT ip FROM sentinel_banned_ips WHERE ip = $1 AND active = TRUE",
                        ip,
                    )
                    if row:
                        if self._sase:
                            self._sase.add_to_blocklist(ip, "persistent ban")
                        return await self._route_to_mirror(ip)
            except Exception as e:
                logger.warning("Orchestrator: preconnect check failed: %s", e)

        return None

    async def _route_to_mirror(self, ip: str) -> str:
        """Create a mirror namespace for a returning banned IP."""
        namespace_id = str(uuid4())
        if self._mirror_shell:
            try:
                ns_mgr = getattr(self._mirror_shell, "namespace_manager", None)
                if ns_mgr:
                    ns = await ns_mgr.create_namespace(
                        entity_identifier=ip,
                        seed_data={"ip": ip, "returning_attacker": True},
                    )
                    namespace_id = str(ns.namespace_id) if hasattr(ns, "namespace_id") else namespace_id
            except Exception as e:
                logger.warning("Orchestrator: mirror routing failed: %s", e)
        return namespace_id

    async def load_persistent_bans(self) -> int:
        """Load persistent bans from DB into SASE blocklist on startup."""
        if not self._db_pool or not self._sase:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT ip FROM sentinel_banned_ips WHERE active = TRUE"
                )
                for row in rows:
                    self._sase.add_to_blocklist(row["ip"], "persistent ban (startup)")
                loaded = len(rows)
                if loaded:
                    logger.info("Loaded %d persistent IP bans into SASE blocklist", loaded)
                return loaded
        except Exception as e:
            logger.warning("Orchestrator: load persistent bans failed: %s", e)
            return 0

    async def handle_helix_approval(self, approval_code: str, channel: str = "email") -> Dict[str, Any]:
        """Process Helix approval (from email link or SMS reply)."""
        if not self._db_pool:
            return {"status": "error", "message": "No database"}

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM helix_authorization WHERE approval_code = $1 AND status = 'PENDING'",
                    approval_code,
                )
                if not row:
                    return {"status": "error", "message": "Invalid or expired code"}

                if row["expires_at"] < datetime.now(timezone.utc):
                    await conn.execute(
                        "UPDATE helix_authorization SET status = 'EXPIRED' WHERE approval_code = $1",
                        approval_code,
                    )
                    return {"status": "error", "message": "Authorization expired"}

                await conn.execute(
                    "UPDATE helix_authorization SET status = 'APPROVED', decided_at = NOW(), "
                    "decided_by = $1 WHERE approval_code = $2",
                    channel, approval_code,
                )

            logger.warning("HELIX APPROVED: code=%s channel=%s ip=%s",
                           approval_code, channel, row["attacker_ip"])

            return {
                "status": "approved",
                "attacker_ip": row["attacker_ip"],
                "approval_code": approval_code,
            }
        except Exception as e:
            logger.warning("Orchestrator: Helix approval failed: %s", e)
            return {"status": "error", "message": str(e)}

    async def handle_helix_denial(self, approval_code: str, channel: str = "email") -> Dict[str, Any]:
        """Process Helix denial."""
        if not self._db_pool:
            return {"status": "error", "message": "No database"}

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE helix_authorization SET status = 'DENIED', decided_at = NOW(), "
                    "decided_by = $1 WHERE approval_code = $2 AND status = 'PENDING'",
                    channel, approval_code,
                )
            logger.info("HELIX DENIED: code=%s channel=%s", approval_code, channel)
            return {"status": "denied", "approval_code": approval_code}
        except Exception as e:
            logger.warning("Orchestrator: Helix denial failed: %s", e)
            return {"status": "error", "message": str(e)}
