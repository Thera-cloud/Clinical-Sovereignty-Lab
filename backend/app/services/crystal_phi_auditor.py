"""
LITTLE NATE — Crystal PHI Auditor

Standing recurring background agent. Closes the failure class found in the
2026-07-09 incident (see
docs/INCIDENT_MEMO_CRYSTAL_SCOPE_PHI_EXPOSURE_2026-07-09.md) on the READ
side, on a schedule, independent of any single write path.

Why this exists in addition to the write-time guard
-----------------------------------------------------
crystal_phi_guard.py (write-time) blocks NEW scope='global' writes that
contain a live client/coach name at the moment of writing. That closes the
*creation* path for one scope value. It does not protect against:

  - a name being added to the roster AFTER a crystal was already written
    (the roster is a live TTL cache; a client who signs up today doesn't
    retroactively get their name checked against yesterday's crystals)
  - a crystal written through a code path this project doesn't yet
    guard (a future admin tool, a manual SQL insert, a bulk import)
  - a crystal that orphans into the ownerless (user_id IS NULL) pool under
    ANY scope value at all -- not just 'global' -- because of a resolution
    bug elsewhere. This is exactly the structural pattern the 2026-07-09
    audit found: a scope='user:<id>' crystal with user_id IS NULL.

This auditor re-scans the ENTIRE ownerless (user_id IS NULL) crystal pool on
every cycle against the live client-name roster and AUTO-QUARANTINES
(archives) any match -- regardless of what scope value it currently
carries. This is deliberately "audit the failure class continuously"
instead of "patch scopes one at a time," per the incident follow-up.

Auto-quarantine, not auto-delete
-----------------------------------
Matches are archived (scope='archived'), never deleted -- per
crystal-intelligence-integrity.mdc ("Never DELETE FROM
nate_intelligence_crystals -- always archive"). This preserves the data for
audit/legal review while removing it from the recall-eligible global pool
(crystal_recall_bridge.py's allowlist already means an 'archived' crystal
was never recall-eligible in the first place -- this closes the belt as
well as the suspenders).

Immutable audit trail
-----------------------------------
Every quarantine action is ALSO logged to the immutable `audit_log` table
(action_type='SECURITY', which has a DB-level trigger blocking UPDATE/DELETE)
so a permanent, tamper-evident record survives even if skyeye_activity rows
are later pruned by db_maintenance_agent's 90-day retention policy. No
client name or crystal text is ever written into audit_log or the alert
email -- only crystal id, prior scope, origin_surface, and domain.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.services.crystal_phi_guard import (
    refresh_client_name_roster,
    text_contains_client_name,
)

logger = logging.getLogger("skyeye.crystal_phi_auditor")

# Runaway-memory guard only. The ownerless (user_id IS NULL) pool is a small
# fraction of the full crystal table -- most crystals are user-owned -- so
# this cap is not expected to bind in normal operation.
_SCAN_BATCH_LIMIT = 5000


class CrystalPhiAuditor:
    """Standing background agent: sweeps the ownerless crystal pool against
    the live client-name roster and auto-quarantines matches."""

    def __init__(self, db_pool, interval_seconds: int = 21600,
                 notification_system=None, admin_email: str = ""):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self.notifications = notification_system
        self.admin_email = admin_email
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_cycle_summary: dict = {}

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("CrystalPhiAuditor started (interval=%ds)", self.interval)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CrystalPhiAuditor stopped")

    async def _run_loop(self):
        # Stagger only needs to avoid colliding with startup DB-pool churn --
        # this auditor is independent of the trust-enforcer 5-300s audit
        # window (see auditor-endpoint-sync.mdc); it does not participate in
        # that rollup.
        await asyncio.sleep(150)
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("CrystalPhiAuditor cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _cycle(self):
        if not self.db_pool:
            return
        await refresh_client_name_roster(self.db_pool, force=True)

        rows = await self._fetch_ownerless_crystals()
        matches = []
        scope_drift_count = 0

        for row in rows:
            text = row["crystal_text"] or ""
            scope = row["scope"] or ""
            matched_name = text_contains_client_name(text)
            if matched_name:
                matches.append({
                    "id": row["id"],
                    "prior_scope": scope,
                    "origin_surface": row["origin_surface"],
                    "domain": row["domain"],
                })
            elif scope != "global":
                # Ownerless, not global-pool-eligible, and no name match --
                # the "orphan" pattern (e.g. a mis-resolved
                # scope='user:<id>' crystal). Cannot leak through the
                # recall-side allowlist (crystal-recall-crystallization-wiring.mdc
                # / test_admin_only_scope_isolation.py), but it is dead-weight
                # scope-hygiene debt worth surfacing rather than silently
                # ignoring -- reported only, not auto-archived, since it is
                # not a confirmed PHI finding.
                scope_drift_count += 1

        quarantined = 0
        for m in matches:
            ok = await self._quarantine(m["id"])
            if ok:
                quarantined += 1
                await self._write_audit_log_entry(m)

        summary = {
            "scanned": len(rows),
            "name_matches": len(matches),
            "quarantined": quarantined,
            "scope_drift_orphans": scope_drift_count,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self.last_cycle_summary = summary

        severity = "critical" if matches else "info"
        content = (
            f"Scanned {summary['scanned']} ownerless crystals. "
            f"{summary['name_matches']} live-client-name match(es) found, "
            f"{summary['quarantined']} auto-quarantined. "
            f"{summary['scope_drift_orphans']} non-global orphaned-scope "
            f"crystal(s) flagged for hygiene review (unreachable via recall "
            f"allowlist, not PHI-confirmed)."
        )
        await self._log_activity("crystal_phi_audit_cycle", content, severity)
        logger.info("CrystalPhiAuditor: %s", content)

        if matches:
            await self._alert(matches, summary)

        # QUANTUM-CRYSTAL-ARCH: graph-surfaced crystals — ownerless + live-name PHI (Phase 5d)
        if os.getenv("ENABLE_CRYSTAL_GRAPH", "false").lower() not in ("1", "true", "yes"):
            return
        try:
            from app.services.crystal_graph_isolation import fetch_graph_surfaced_crystal_ids

            graph_ids = await fetch_graph_surfaced_crystal_ids(self.db_pool, limit=100)
            graph_matches = 0
            for gid in graph_ids:
                row = await self._fetch_crystal_by_id(gid)
                if not row:
                    continue
                if row["user_id"] is not None:
                    continue
                if text_contains_client_name(row["crystal_text"] or ""):
                    graph_matches += 1
                    if await self._quarantine(gid):
                        await self._write_audit_log_entry({
                            "id": gid,
                            "prior_scope": row["scope"],
                            "origin_surface": row.get("origin_surface"),
                            "domain": row.get("domain"),
                        })
            summary["graph_surfaced_scanned"] = len(graph_ids)
            summary["graph_surfaced_quarantined"] = graph_matches
        except Exception as e:
            logger.warning("CrystalPhiAuditor: graph-surfaced scan skipped: %s", e)

    async def _fetch_crystal_by_id(self, crystal_id: int):
        try:
            async with self.db_pool.acquire() as conn:
                return await conn.fetchrow(
                    """
                    SELECT id, crystal_text, scope, origin_surface, domain, user_id
                    FROM nate_intelligence_crystals WHERE id = $1
                    """,
                    crystal_id,
                )
        except Exception:
            return None

    async def _fetch_ownerless_crystals(self):
        try:
            async with self.db_pool.acquire() as conn:
                return await conn.fetch(
                    """
                    SELECT id, crystal_text, scope, origin_surface, domain
                    FROM nate_intelligence_crystals
                    WHERE user_id IS NULL
                      AND scope IS DISTINCT FROM 'archived'
                    ORDER BY id
                    LIMIT $1
                    """,
                    _SCAN_BATCH_LIMIT,
                )
        except Exception as e:
            logger.error("CrystalPhiAuditor: scan query failed: %s", e)
            return []

    async def _quarantine(self, crystal_id: int) -> bool:
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE nate_intelligence_crystals
                    SET scope = 'archived',
                        metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                            'phi_auto_quarantined', true,
                            'phi_auto_quarantined_at', NOW()::text,
                            'phi_auto_quarantine_reason', 'live_client_name_match'
                        )
                    WHERE id = $1 AND scope IS DISTINCT FROM 'archived'
                    """,
                    crystal_id,
                )
            return True
        except Exception as e:
            logger.error("CrystalPhiAuditor: quarantine failed for crystal %s: %s",
                          crystal_id, e)
            return False

    async def _write_audit_log_entry(self, match: dict):
        # audit_log has a DB trigger (audit_log_immutable) blocking UPDATE/
        # DELETE -- this is the permanent record. No PHI (no client name, no
        # crystal_text) is ever written here.
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_log
                        (admin_id, admin_username, admin_role, action_type,
                         target_type, target_name, description, compliance_flags)
                    VALUES
                        (NULL, 'crystal_phi_auditor', 'SYSTEM', 'SECURITY',
                         'nate_intelligence_crystal', $1, $2, ARRAY['PHI', 'AUTO_QUARANTINE'])
                    """,
                    str(match["id"]),
                    (
                        f"Auto-quarantined crystal id={match['id']} (prior scope="
                        f"{match['prior_scope']!r}, origin_surface={match['origin_surface']!r}, "
                        f"domain={match['domain']!r}) -- crystal_text contained a live "
                        f"client/coach name while user_id IS NULL. See "
                        f"docs/INCIDENT_MEMO_CRYSTAL_SCOPE_PHI_EXPOSURE_2026-07-09.md."
                    ),
                )
        except Exception as e:
            logger.error("CrystalPhiAuditor: audit_log write failed for crystal %s: %s",
                          match["id"], e)

    async def _log_activity(self, activity_type: str, content: str, severity: str):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ('system', $1, $2, $3, NOW())
                    """,
                    activity_type, content, severity,
                )
        except Exception:
            pass

    async def _alert(self, matches: list, summary: dict):
        if not self.notifications or not self.admin_email:
            logger.warning(
                "CrystalPhiAuditor: %d PHI match(es) auto-quarantined but no "
                "notification_system/admin_email configured -- alert NOT sent",
                len(matches),
            )
            return
        ids = ", ".join(str(m["id"]) for m in matches[:20])
        more = "" if len(matches) <= 20 else f" (+{len(matches) - 20} more)"
        body = (
            f"<p><strong>Crystal PHI Auditor</strong> auto-quarantined "
            f"{len(matches)} crystal(s) containing a live client/coach name "
            f"while ownerless (user_id IS NULL).</p>"
            f"<p>Crystal IDs: {ids}{more}</p>"
            f"<p>All matches were archived (never deleted) and logged to the "
            f"immutable audit_log table. No client names or crystal text are "
            f"included in this email -- review via SQL against "
            f"nate_intelligence_crystals and audit_log for full detail.</p>"
            f"<p>See docs/INCIDENT_MEMO_CRYSTAL_SCOPE_PHI_EXPOSURE_2026-07-09.md "
            f"for the incident this auditor exists to prevent from recurring.</p>"
        )
        try:
            await self.notifications._send_email(
                self.admin_email,
                f"Crystal PHI Auditor — {len(matches)} auto-quarantined",
                body,
                notification_type="security",
            )
        except Exception as e:
            logger.error("CrystalPhiAuditor: alert email failed: %s", e)
