"""
HIVE DEFENSE — DEFCON Recon Report Generator

Compiles comprehensive attack intelligence into a structured HTML email
sent to support@sovereignsanctuary.net on every Sentinel freeze event.

Report sections (Where/What/When/Who/How/How Many):
    - Attack timeline with all escalation events
    - Attacker IP geolocation and fingerprint
    - Session actions and anomaly scores
    - Mirroring trap status and duration
    - Ghost Swarm intelligence gathered
    - DEFCON level and system posture

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.recon_reporter")


class DefconReconReporter:
    """Generates and sends DEFCON Recon Reports on Sentinel freeze events."""

    def __init__(self, db_pool=None, notification_system=None):
        self._db_pool = db_pool
        self._ns = notification_system

    async def generate_and_send(
        self,
        *,
        freeze_id: int,
        ip: str,
        uid: str,
        user_agent: str,
        sentinel_score: int,
        reasons: List[str],
        frozen_at: datetime,
        defcon_level: int,
        mirror_namespace_id: Optional[str] = None,
        trap_id: Optional[str] = None,
        actions_taken: Optional[List[str]] = None,
        alert_emails: Optional[List[str]] = None,
    ) -> bool:
        """Build and send a full recon report. Returns True on success."""
        if not self._ns:
            logger.warning("DefconReconReporter: no notification system, cannot send report")
            return False

        attacker_profile = await self._build_attacker_profile(ip, user_agent, uid)
        timeline = await self._build_timeline(ip, uid, frozen_at)
        mirror_intel = await self._get_mirror_intel(freeze_id)

        html = self._render_html(
            freeze_id=freeze_id,
            ip=ip,
            uid=uid,
            user_agent=user_agent,
            sentinel_score=sentinel_score,
            reasons=reasons,
            frozen_at=frozen_at,
            defcon_level=defcon_level,
            attacker_profile=attacker_profile,
            timeline=timeline,
            mirror_intel=mirror_intel,
            actions_taken=actions_taken or [],
            mirror_namespace_id=mirror_namespace_id,
            trap_id=trap_id,
        )

        emails = alert_emails or ["support@sovereignsanctuary.net"]
        for email in emails:
            try:
                await self._ns._send_email(
                    to_email=email,
                    subject=f"[DEFCON RECON] Sentinel Freeze — IP {ip} — Score {sentinel_score}",
                    content=html,
                    notification_type="defcon_recon_report",
                )
            except Exception as e:
                logger.warning("DefconReconReporter: email to %s failed: %s", email, e)
                return False

        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sentinel_freeze_history SET recon_report_sent = TRUE WHERE id = $1",
                        freeze_id,
                    )
            except Exception as e:
                logger.warning("DefconReconReporter: DB update failed: %s", e)

        logger.info("DEFCON Recon Report sent for freeze #%d (IP: %s)", freeze_id, ip)
        return True

    async def _build_attacker_profile(self, ip: str, user_agent: str, uid: str) -> Dict[str, Any]:
        profile: Dict[str, Any] = {
            "ip": ip,
            "user_agent": user_agent,
            "uid": uid,
        }
        if not self._db_pool:
            return profile

        try:
            async with self._db_pool.acquire() as conn:
                prior = await conn.fetch(
                    "SELECT frozen_at, sentinel_score, reasons FROM sentinel_freeze_history "
                    "WHERE ip = $1 ORDER BY frozen_at DESC LIMIT 10",
                    ip,
                )
                profile["prior_freeze_count"] = len(prior)
                profile["prior_freezes"] = [
                    {"at": r["frozen_at"].isoformat(), "score": r["sentinel_score"]}
                    for r in prior[:5]
                ]

                ban_row = await conn.fetchrow(
                    "SELECT banned_at, reason FROM sentinel_banned_ips WHERE ip = $1 AND active = TRUE",
                    ip,
                )
                if ban_row:
                    profile["banned"] = True
                    profile["ban_reason"] = ban_row["reason"]
                    profile["banned_at"] = ban_row["banned_at"].isoformat()
        except Exception as e:
            logger.warning("DefconReconReporter: attacker profile query failed: %s", e)

        return profile

    async def _build_timeline(self, ip: str, uid: str, frozen_at: datetime) -> List[Dict[str, Any]]:
        timeline: List[Dict[str, Any]] = []
        if not self._db_pool:
            return timeline

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT action_type, description, ip_address, created_at "
                    "FROM audit_log WHERE ip_address::text = $1 "
                    "AND created_at >= $2 - INTERVAL '1 hour' "
                    "ORDER BY created_at ASC LIMIT 100",
                    ip, frozen_at,
                )
                for r in rows:
                    timeline.append({
                        "action": r["action_type"],
                        "detail": r["description"][:200] if r["description"] else "",
                        "at": r["created_at"].isoformat(),
                    })
        except Exception as e:
            logger.warning("DefconReconReporter: timeline query failed: %s", e)

        return timeline

    async def _get_mirror_intel(self, freeze_id: int) -> Dict[str, Any]:
        intel: Dict[str, Any] = {}
        if not self._db_pool:
            return intel

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT mirror_namespace_id, trap_id, interactions_mirrored, "
                    "disengaged_at, actions_taken FROM sentinel_freeze_history WHERE id = $1",
                    freeze_id,
                )
                if row:
                    intel["namespace_id"] = row["mirror_namespace_id"]
                    intel["trap_id"] = row["trap_id"]
                    intel["interactions_mirrored"] = row["interactions_mirrored"] or 0
                    intel["disengaged_at"] = row["disengaged_at"].isoformat() if row["disengaged_at"] else None
                    intel["actions_taken"] = row["actions_taken"] or []
        except Exception as e:
            logger.warning("DefconReconReporter: mirror intel query failed: %s", e)

        return intel

    def _render_html(self, **ctx) -> str:
        reasons_html = "".join(f"<li>{r}</li>" for r in ctx["reasons"])
        actions_html = "".join(f"<li>{a}</li>" for a in ctx["actions_taken"])

        timeline_rows = ""
        for ev in ctx.get("timeline", []):
            timeline_rows += (
                f'<tr><td style="color:#999;padding:4px 8px;">{ev["at"]}</td>'
                f'<td style="color:#E8D5A3;padding:4px 8px;">{ev["action"]}</td>'
                f'<td style="color:#ccc;padding:4px 8px;">{ev["detail"]}</td></tr>'
            )

        ap = ctx.get("attacker_profile", {})
        prior_count = ap.get("prior_freeze_count", 0)
        prior_html = ""
        for pf in ap.get("prior_freezes", []):
            prior_html += f'<li>Score {pf["score"]} at {pf["at"]}</li>'

        mi = ctx.get("mirror_intel", {})
        mirror_section = ""
        if mi.get("trap_id"):
            mirror_section = f"""
            <h3 style="color:#4ECDC4;">House of Mirrors Status</h3>
            <table style="border-collapse:collapse;width:100%;">
                <tr><td style="color:#999;padding:4px;">Namespace</td>
                    <td style="color:#E8D5A3;">{mi.get('namespace_id', 'N/A')}</td></tr>
                <tr><td style="color:#999;padding:4px;">Trap ID</td>
                    <td style="color:#E8D5A3;">{mi.get('trap_id', 'N/A')}</td></tr>
                <tr><td style="color:#999;padding:4px;">Interactions Mirrored</td>
                    <td style="color:#E8D5A3;">{mi.get('interactions_mirrored', 0)}</td></tr>
                <tr><td style="color:#999;padding:4px;">Disengaged At</td>
                    <td style="color:#E8D5A3;">{mi.get('disengaged_at', 'Still Active')}</td></tr>
            </table>"""

        defcon_colors = {1: "#FF0000", 2: "#FF4444", 3: "#FF8800", 4: "#FFD700", 5: "#22C55E"}
        defcon_names = {1: "CRITICAL", 2: "SEVERE", 3: "SUBSTANTIAL", 4: "ELEVATED", 5: "PEACE"}
        dl = ctx["defcon_level"]

        return f"""
        <div style="font-family:'DM Sans',sans-serif;background:#050505;color:#E8D5A3;padding:32px;max-width:800px;margin:auto;">
            <div style="text-align:center;margin-bottom:24px;">
                <h1 style="color:#C9A962;margin:0;font-family:'Cormorant Garamond',serif;">
                    DEFCON RECON REPORT
                </h1>
                <p style="color:#EF4444;font-size:20px;font-weight:bold;margin:8px 0;">
                    Sentinel Freeze #{ctx['freeze_id']}
                </p>
                <span style="background:{defcon_colors.get(dl, '#666')};color:#050505;padding:6px 16px;
                       border-radius:4px;font-weight:bold;">
                    DEFCON {defcon_names.get(dl, 'UNKNOWN')}
                </span>
            </div>

            <hr style="border-color:#333;">

            <h2 style="color:#C9A962;">WHO — Attacker Profile</h2>
            <table style="border-collapse:collapse;width:100%;">
                <tr><td style="color:#999;padding:4px 8px;">IP Address</td>
                    <td style="color:#EF4444;font-weight:bold;">{ctx['ip']}</td></tr>
                <tr><td style="color:#999;padding:4px 8px;">User Agent</td>
                    <td style="color:#ccc;font-size:12px;">{ctx['user_agent'][:120]}</td></tr>
                <tr><td style="color:#999;padding:4px 8px;">Session UID</td>
                    <td style="color:#ccc;">{ctx['uid']}</td></tr>
                <tr><td style="color:#999;padding:4px 8px;">Prior Freezes</td>
                    <td style="color:{'#EF4444' if prior_count > 0 else '#22C55E'};">
                        {prior_count} previous freeze(s)</td></tr>
                <tr><td style="color:#999;padding:4px 8px;">Currently Banned</td>
                    <td style="color:{'#EF4444' if ap.get('banned') else '#22C55E'};">
                        {'YES — ' + ap.get('ban_reason', '') if ap.get('banned') else 'NO'}</td></tr>
            </table>
            {f'<p style="color:#999;margin-top:8px;">Prior freeze history:</p><ul style="color:#ccc;">{prior_html}</ul>' if prior_html else ''}

            <hr style="border-color:#333;">

            <h2 style="color:#C9A962;">WHEN — Freeze Timestamp</h2>
            <p style="font-size:18px;color:#E8D5A3;">{ctx['frozen_at'].isoformat()} UTC</p>

            <hr style="border-color:#333;">

            <h2 style="color:#C9A962;">WHAT — Sentinel Score &amp; Reasons</h2>
            <p style="font-size:24px;color:#EF4444;font-weight:bold;">Score: {ctx['sentinel_score']}</p>
            <ul style="color:#ccc;">{reasons_html}</ul>

            <hr style="border-color:#333;">

            <h2 style="color:#C9A962;">HOW — Attack Timeline</h2>
            {'<table style="border-collapse:collapse;width:100%;"><thead><tr><th style="color:#666;text-align:left;padding:4px 8px;">Time</th><th style="color:#666;text-align:left;padding:4px 8px;">Action</th><th style="color:#666;text-align:left;padding:4px 8px;">Detail</th></tr></thead><tbody>' + timeline_rows + '</tbody></table>' if timeline_rows else '<p style="color:#666;">No audit log entries found for this IP in the preceding hour.</p>'}

            <hr style="border-color:#333;">

            <h2 style="color:#C9A962;">WHERE — Actions Taken</h2>
            <ul style="color:#ccc;">{actions_html if actions_html else '<li>Sentinel freeze + session disconnect</li>'}</ul>

            {mirror_section}

            <hr style="border-color:#333;">

            <div style="text-align:center;padding:16px;margin-top:16px;">
                <p style="color:#666;font-size:12px;">
                    Sovereign Sanctuary Defense System — Patent-Pending Claims 30-56<br>
                    © 2026 Clinical Sovereignty Lab. All rights reserved.
                </p>
            </div>
        </div>
        """
