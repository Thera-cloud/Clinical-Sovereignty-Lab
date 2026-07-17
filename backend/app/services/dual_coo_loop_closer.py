"""
Dual-COO Loop Closer — wires medium-term + strategic close-the-loop cycles.

Cycles (feature-flagged):
  1) Coach-label → crystal feedback (+ CEO YELLOW/RED for corrections)
  2) PMB / Nevedal / SkyEye → coach_insight_briefs (insight_route YELLOW)
  3) Compliance red-team → GREEN bus tasks
  4) Prior-art sweep → patent_claim_map + prior_art_sweep_log
  5) Second-order learning proposals (matching/brief refine YELLOW)
  6) Peer Queen failover flag when Mac heartbeat stale

# QUANTUM-CRYSTAL-ARCH — close the Dual-COO loops
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dual_coo_loop_closer")

POLL_S = int(os.getenv("DUAL_COO_LOOP_CLOSER_POLL_S", "300"))
STAGGER_S = int(os.getenv("DUAL_COO_LOOP_CLOSER_STAGGER_S", "90"))

_CORRECTION_RE = re.compile(
    r"\b(incorrect|wrong|do not|don't|nate was|false|override|correct this|"
    r"never say|stop saying|misremember)\b",
    re.I,
)


def closer_enabled() -> bool:
    return os.getenv("DUAL_COO_LOOP_CLOSER_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


class DualCooLoopCloser:
    """Periodic close-the-loop agent for Dual-COO / CEO governance."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycles = 0
        self._stats = {
            "coach_labels": 0,
            "briefs": 0,
            "compliance": 0,
            "prior_art": 0,
            "second_order": 0,
            "failover": 0,
        }

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "DualCooLoopCloser started (enabled=%s poll=%ss)",
            closer_enabled(),
            POLL_S,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DualCooLoopCloser stopped cycles=%s stats=%s", self._cycles, self._stats)

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_S)
        while self._running:
            try:
                if closer_enabled():
                    await self.run_cycle()
            except Exception as e:
                logger.error("DualCooLoopCloser cycle error: %s", e)
            await asyncio.sleep(max(60, POLL_S))

    async def run_cycle(self) -> Dict[str, Any]:
        self._cycles += 1
        out: Dict[str, Any] = {}
        out["coach"] = await self._cycle_coach_labels()
        out["briefs"] = await self._cycle_insight_briefs()
        if self._cycles % 2 == 0:
            out["compliance"] = await self._cycle_compliance_redteam()
        if self._cycles % 3 == 0:
            out["prior_art"] = await self._cycle_prior_art()
        if self._cycles % 4 == 0:
            out["second_order"] = await self._cycle_second_order()
        if self._cycles % 3 == 0:
            out["attribution"] = await self._cycle_attribution_density()
        out["failover"] = await self._cycle_peer_failover()
        return out

    async def _log_event(self, kind: str, risk: str, detail: str, payload: Optional[dict] = None):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO dual_coo_loop_events (kind, risk_class, detail, payload)
                    VALUES ($1, $2, $3, $4::jsonb)
                    """,
                    kind[:64],
                    risk[:16],
                    (detail or "")[:2000],
                    json.dumps(payload or {}, default=str),
                )
        except Exception as e:
            logger.debug("dual_coo_loop_events insert: %s", e)

    def _watermark_get(self, name: str) -> float:
        """Redis watermark (unix ts) for incremental cycles."""
        try:
            from app.websocket.cli_dual_coo import _env, _prefix, _redis

            c = _redis()
            if not c:
                return 0.0
            raw = c.get(f"{_prefix()}:{_env()}:cli:loop_wm:{name}")
            return float(raw) if raw else 0.0
        except Exception:
            return 0.0

    def _watermark_set(self, name: str, ts: float) -> None:
        try:
            from app.websocket.cli_dual_coo import _env, _prefix, _redis

            c = _redis()
            if c:
                c.setex(
                    f"{_prefix()}:{_env()}:cli:loop_wm:{name}",
                    14 * 86400,
                    str(ts),
                )
        except Exception:
            pass

    # ── 1) Coach-label → crystal feedback ───────────────────────────────
    async def _cycle_coach_labels(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "skipped"}
        n = 0
        try:
            from app.websocket.crystal_recall_bridge import crystallize_coach_observation
            from app.websocket.cli_dual_coo import RISK_RED, enqueue_ceo

            # Incremental: only rows newer than watermark (fallback: 2× poll window)
            wm = self._watermark_get("coach_labels")
            since = time.strftime(
                "%Y-%m-%d %H:%M:%S+00",
                time.gmtime(wm if wm > 0 else time.time() - max(600, POLL_S * 2)),
            )
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT coach_user_id, client_user_id, notes, clinical_hold,
                           focus_domain, pacing, updated_at
                    FROM coach_client_overrides
                    WHERE updated_at > $1::timestamptz
                      AND notes IS NOT NULL AND LENGTH(TRIM(notes)) > 8
                    ORDER BY updated_at ASC
                    LIMIT 40
                    """,
                    since,
                )
            max_ts = wm
            for row in rows:
                notes = (row["notes"] or "").strip()
                if not notes:
                    continue
                # Crystal path enqueues CEO for corrections once (new crystal only).
                # Loop closer only surfaces clinical_hold here (avoid double-enqueue).
                await crystallize_coach_observation(
                    self.db_pool,
                    str(row["coach_user_id"] or ""),
                    str(row["client_user_id"] or ""),
                    notes,
                    domain="clinical",
                    observation_type="coach_override",
                )
                if bool(row["clinical_hold"]):
                    enqueue_ceo(
                        risk=RISK_RED,
                        title="Coach clinical_hold override",
                        detail=notes[:500],
                        origin="cloud",
                        task_id=f"hold:{row['coach_user_id']}:{row['client_user_id']}",
                        payload={
                            "client": str(row["client_user_id"])[:80],
                            "coach": str(row["coach_user_id"])[:80],
                            "focus_domain": row["focus_domain"],
                            "pacing": row["pacing"],
                        },
                        dedup_ttl_s=86400,
                    )
                n += 1
                try:
                    ut = row["updated_at"]
                    if ut is not None:
                        max_ts = max(max_ts, float(ut.timestamp()))
                except Exception:
                    pass
            if max_ts > wm:
                self._watermark_set("coach_labels", max_ts)
            self._stats["coach_labels"] += n
            if n:
                await self._log_event("coach_label", "YELLOW", f"processed={n}")
            return {"status": "ok", "processed": n}
        except Exception as e:
            logger.warning("coach_label cycle: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 2) Insight routing → coach briefs ───────────────────────────────
    async def _cycle_insight_briefs(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "skipped"}
        created = 0
        try:
            from app.websocket.cli_task_bus import publish_task, task_bus_enabled
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

            insights: List[Dict[str, Any]] = []
            async with self.db_pool.acquire() as conn:
                # Liminal presence (language_drift / field_response) — not skyeye_activity
                try:
                    lim = await conn.fetch(
                        """
                        SELECT id, agent, signal, score, detail, created_at
                        FROM liminal_presence_analysis
                        WHERE created_at > NOW() - INTERVAL '48 hours'
                          AND agent IN ('language_drift', 'field_response')
                          AND UPPER(signal) IN ('YELLOW', 'RED')
                        ORDER BY created_at DESC
                        LIMIT 15
                        """
                    )
                    for r in lim:
                        insights.append({
                            "source": "skyeye",
                            "client_user_id": "broadcast",
                            "title": f"Liminal {r['agent']}: {r['signal']}",
                            "body": (
                                f"score={r['score']} at {r['created_at']}. "
                                f"{str(r['detail'] or '')[:1200]}"
                            ),
                            "dedupe_key": f"liminal:{r['id']}",
                        })
                except Exception as e:
                    logger.debug("liminal insight pull: %s", e)

                # Voice correction events (real skyeye_activity type)
                try:
                    sky = await conn.fetch(
                        """
                        SELECT id, type, content, created_at
                        FROM skyeye_activity
                        WHERE created_at > NOW() - INTERVAL '48 hours'
                          AND type = 'voice_correction_applied'
                        ORDER BY created_at DESC
                        LIMIT 10
                        """
                    )
                    for r in sky:
                        insights.append({
                            "source": "skyeye",
                            "client_user_id": "broadcast",
                            "title": f"SkyEye: {r['type']}",
                            "body": str(r["content"] or "")[:1500],
                            "dedupe_key": f"skyeye:{r['id']}",
                        })
                except Exception as e:
                    logger.debug("skyeye insight pull: %s", e)

                # Nevedal family weather (actual schema: family-level snapshots)
                try:
                    nev = await conn.fetch(
                        """
                        SELECT id, family_id, sanctuary_id, system_coherence,
                               system_volatility, cee_window_open, isolated_member,
                               created_at
                        FROM emotional_weather_snapshots
                        WHERE created_at > NOW() - INTERVAL '48 hours'
                        ORDER BY created_at DESC
                        LIMIT 15
                        """
                    )
                    for r in nev:
                        insights.append({
                            "source": "nevedal",
                            "client_user_id": "broadcast",
                            "title": (
                                f"Family weather fam={str(r['family_id'] or '')[:12]} "
                                f"C={float(r['system_coherence'] or 0):.2f}"
                            ),
                            "body": (
                                f"sanctuary={r['sanctuary_id']} volatility="
                                f"{r['system_volatility']} cee_open={r['cee_window_open']} "
                                f"isolated={r['isolated_member']} at {r['created_at']}. "
                                "Pre-session orientation only; do not diagnose from this alone."
                            ),
                            "dedupe_key": f"weather:{r['id']}",
                        })
                except Exception as e:
                    logger.debug("nevedal insight pull: %s", e)

                # PMB report requests — never scan skyeye for '%shame%' / '%pmb%' audits
                try:
                    pmb = await conn.fetch(
                        """
                        SELECT id, client_username, client_hardware_id, urgency,
                               urgency_reason, status, requested_at
                        FROM pmb_report_requests
                        WHERE requested_at > NOW() - INTERVAL '72 hours'
                          AND (
                              UPPER(COALESCE(urgency, '')) IN ('HIGH', 'CRITICAL', 'URGENT')
                              OR status IN ('pending', 'requested', 'in_review')
                          )
                        ORDER BY requested_at DESC
                        LIMIT 10
                        """
                    )
                    for r in pmb:
                        client_ref = (
                            str(r["client_hardware_id"] or "")
                            or str(r["client_username"] or "")
                            or "broadcast"
                        )
                        insights.append({
                            "source": "pmb",
                            "client_user_id": client_ref[:200],
                            "title": (
                                f"PMB report {r['status']}: "
                                f"{r['client_username'] or 'client'}"
                            ),
                            "body": (
                                f"urgency={r['urgency']} reason="
                                f"{str(r['urgency_reason'] or '')[:400]} "
                                f"requested_at={r['requested_at']}"
                            ),
                            "dedupe_key": f"pmb:{r['id']}",
                        })
                except Exception as e:
                    logger.debug("pmb insight pull: %s", e)

                for item in insights[:25]:
                    dkey = str(item.get("dedupe_key") or item["title"])[:120]
                    exists = await conn.fetchval(
                        """
                        SELECT 1 FROM coach_insight_briefs
                        WHERE metadata->>'dedupe_key' = $1
                          AND created_at > NOW() - INTERVAL '36 hours'
                        LIMIT 1
                        """,
                        dkey,
                    )
                    if exists:
                        continue
                    # Fallback title+source+body prefix for older rows without dedupe_key
                    exists2 = await conn.fetchval(
                        """
                        SELECT 1 FROM coach_insight_briefs
                        WHERE source = $1 AND title = $2
                          AND LEFT(COALESCE(body, ''), 80) = LEFT($3::text, 80)
                          AND created_at > NOW() - INTERVAL '36 hours'
                        LIMIT 1
                        """,
                        item["source"],
                        item["title"][:300],
                        item["body"][:80],
                    )
                    if exists2:
                        continue
                    task_id = ""
                    if task_bus_enabled():
                        pub = publish_task(
                            origin="cloud",
                            kind="insight_route",
                            status="queued",
                            notes=f"{item['source']}: {item['title'][:200]}",
                            plan_id="insight_route",
                        )
                        task_id = str((pub.get("task") or {}).get("task_id") or "")
                    await conn.execute(
                        """
                        INSERT INTO coach_insight_briefs
                            (client_user_id, source, title, body, risk_class, status, task_id, metadata)
                        VALUES ($1, $2, $3, $4, 'YELLOW', 'queued', $5, $6::jsonb)
                        """,
                        str(item.get("client_user_id") or "broadcast")[:200],
                        item["source"][:64],
                        item["title"][:300],
                        item["body"][:4000],
                        task_id,
                        json.dumps(
                            {"cycle": self._cycles, "dedupe_key": dkey},
                            default=str,
                        ),
                    )
                    created += 1

            if created:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title=f"{created} coach insight briefs queued",
                    detail="PMB/Nevedal/Liminal → coach_insight_briefs",
                    origin="cloud",
                    payload={"count": created},
                    dedup_ttl_s=1800,
                )
                await self._log_event("insight_route", "YELLOW", f"created={created}")
            self._stats["briefs"] += created
            return {"status": "ok", "created": created}
        except Exception as e:
            logger.warning("insight_briefs cycle: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 3) Compliance red-team (GREEN bus) ──────────────────────────────
    async def _cycle_compliance_redteam(self) -> Dict[str, Any]:
        findings: List[str] = []
        try:
            from app.websocket.cli_task_bus import publish_task, task_bus_enabled

            if self.db_pool:
                async with self.db_pool.acquire() as conn:
                    # Privacy wall: crystals must not mix user_ids in same row incorrectly
                    # Privacy wall audit: user-scoped rows must have an owner.
                    leak = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM nate_intelligence_crystals
                        WHERE scope = 'user'
                          AND COALESCE(user_id::text, '') = ''
                          AND created_at > NOW() - INTERVAL '7 days'
                        """
                    )
                    if int(leak or 0) > 0:
                        findings.append(f"user-scoped crystals missing user_id: {leak}")
                    # Sensitive bridge enrollment must use username FK pattern (non-empty)
                    try:
                        orphans = await conn.fetchval(
                            """
                            SELECT COUNT(*) FROM sensitive_bridge_enrollment e
                            WHERE NOT EXISTS (
                                SELECT 1 FROM users u WHERE u.username = e.user_id
                            )
                            """
                        )
                        if int(orphans or 0) > 0:
                            findings.append(f"sensitive_bridge_enrollment orphans: {orphans}")
                    except Exception:
                        pass

            notes = (
                "compliance_redteam privacy_wall "
                + ("; ".join(findings) if findings else "ok_no_leaks")
            )
            if task_bus_enabled():
                publish_task(
                    origin="cloud",
                    kind="compliance_redteam",
                    status="queued",
                    notes=notes[:2000],
                    plan_id="compliance_redteam",
                    files=["backend/app/websocket/crystal_recall_bridge.py"],
                )
            await self._log_event(
                "compliance_redteam",
                "GREEN",
                notes[:500],
                {"findings": findings},
            )
            self._stats["compliance"] += 1
            return {"status": "ok", "findings": findings}
        except Exception as e:
            logger.warning("compliance_redteam: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 4) Prior-art sweep ──────────────────────────────────────────────
    async def _cycle_prior_art(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "skipped"}
        proposed = 0
        swept = 0
        try:
            from app.services.google_patents_ingest import (
                ingest_patent_crystal_sweep,
                portfolio_coverage_seed,
            )
            from app.services.patent_claim_guardian import sweep_patent_crystals

            proposed = await sweep_patent_crystals(self.db_pool, limit=25)
            async with self.db_pool.acquire() as conn:
                crystals = await conn.fetch(
                    """
                    SELECT id, LEFT(crystal_text, 200) AS snippet
                    FROM nate_intelligence_crystals
                    WHERE LOWER(COALESCE(domain, '')) = 'patent'
                      AND superseded_by IS NULL
                    ORDER BY confidence DESC NULLS LAST, created_at DESC
                    LIMIT 5
                    """
                )
            for row in crystals:
                r = await ingest_patent_crystal_sweep(
                    self.db_pool,
                    crystal_id=int(row["id"]),
                    snippet=str(row["snippet"] or ""),
                )
                if r.get("status") == "ok":
                    swept += 1
            proposed += await portfolio_coverage_seed(self.db_pool)

            self._stats["prior_art"] += proposed + swept
            await self._log_event(
                "prior_art_flag", "YELLOW",
                f"proposed={proposed} swept={swept}",
            )
            return {"status": "ok", "proposed": proposed, "swept": swept}
        except Exception as e:
            logger.warning("prior_art cycle: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 5) Second-order learning (YELLOW proposals) ─────────────────────
    async def _cycle_second_order(self) -> Dict[str, Any]:
        try:
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo
            from app.websocket.cli_task_bus import publish_task, task_bus_enabled

            detail = (
                "COO proposal: refine matching weights / pre-session brief templates "
                "from recent coach_insight_briefs. Mac sandbox-test only; "
                "production clinical unchanged until CEO RED sign-off."
            )
            if task_bus_enabled():
                publish_task(
                    origin="cloud",
                    kind="brief_refine",
                    status="queued",
                    notes=detail,
                    plan_id="second_order_learning",
                )
                publish_task(
                    origin="cloud",
                    kind="matching_weight",
                    status="queued",
                    notes="Propose coach-client matching weight tweak (sandbox only)",
                    plan_id="second_order_learning",
                )
            enqueue_ceo(
                risk=RISK_YELLOW,
                title="Second-order learning: matching/brief refine proposals",
                detail=detail,
                origin="cloud",
                payload={"sandbox_only": True},
                dedup_ttl_s=12 * 3600,
            )
            await self._log_event("brief_refine", "YELLOW", detail[:500])
            self._stats["second_order"] += 1
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def _probe_mac_agent_and_beat(self) -> Dict[str, Any]:
        """If Mac agent HTTP health is up, write Redis Queen beat for Mac."""
        url = (os.getenv("MAC_AGENT_URL") or "").strip()
        token = (os.getenv("MAC_AGENT_TOKEN") or "").strip()
        if not url:
            return {"probed": False, "reason": "MAC_AGENT_URL empty"}
        try:
            import aiohttp
            from app.websocket.cli_dual_coo import beat_queen

            headers = {"Authorization": f"Bearer {token}"} if token else {}
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{url.rstrip('/')}/health", headers=headers,
                ) as resp:
                    if resp.status != 200:
                        return {"probed": True, "alive": False, "code": resp.status}
            beat_queen("mac", meta={"via": "cloud_probe", "cycle": self._cycles})
            return {"probed": True, "alive": True, "beat": True}
        except Exception as e:
            return {"probed": True, "alive": False, "error": str(e)[:200]}

    async def _cycle_attribution_density(self) -> Dict[str, Any]:
        """Report crystal attribution coverage (ENABLE_CRYSTAL_ATTRIBUTION path)."""
        if not self.db_pool:
            return {"status": "skipped"}
        try:
            async with self.db_pool.acquire() as conn:
                total = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM conversation_history
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    """
                )
                attributed = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM conversation_history
                    WHERE created_at > NOW() - INTERVAL '7 days'
                      AND metadata ? 'crystal_ids'
                      AND jsonb_typeof(metadata->'crystal_ids') = 'array'
                      AND jsonb_array_length(metadata->'crystal_ids') > 0
                    """
                )
            t = int(total or 0)
            a = int(attributed or 0)
            pct = round(100.0 * a / t, 1) if t else 0.0
            await self._log_event(
                "attribution_density", "GREEN",
                f"attributed={a}/{t} ({pct}%)",
                {"attributed": a, "total": t, "pct": pct},
            )
            if t >= 20 and pct < 5.0 and self._cycles % 12 == 0:
                from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title="Crystal attribution density low",
                    detail=(
                        f"Only {pct}% of last-7d conversation_history rows carry "
                        "metadata.crystal_ids — confirm ENABLE_CRYSTAL_ATTRIBUTION "
                        "on bridge+backend and recall wiring."
                    ),
                    origin="cloud",
                    payload={"attributed": a, "total": t, "pct": pct},
                    dedup_ttl_s=24 * 3600,
                )
            return {"status": "ok", "attributed": a, "total": t, "pct": pct}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    # ── 6) Peer Queen failover ──────────────────────────────────────────
    async def _cycle_peer_failover(self) -> Dict[str, Any]:
        try:
            from app.websocket.cli_dual_coo import (
                RISK_YELLOW,
                enqueue_ceo,
                peer_queen_alive,
                set_cloud_sole_failover,
            )

            # Cloud probes Mac agent and writes Mac Queen beat when reachable
            probe = await self._probe_mac_agent_and_beat()
            peer = peer_queen_alive("cloud", max_age_s=300.0)
            if peer.get("alive"):
                set_cloud_sole_failover(False)
                return {
                    "status": "ok", "mode": "dual", "peer": peer, "probe": probe,
                }
            # no_beat = Mac never online this window (optional Queen) — soft sole
            detail = str(peer.get("detail") or peer.get("error") or "")
            if detail == "no_beat" and not probe.get("alive"):
                set_cloud_sole_failover(True)
                await self._log_event(
                    "peer_failover", "YELLOW",
                    "mac_optional_no_beat", {"peer": peer, "probe": probe},
                )
                return {
                    "status": "ok",
                    "mode": "cloud_sole_optional",
                    "peer": peer,
                    "probe": probe,
                }
            set_cloud_sole_failover(True)
            if self._cycles % 6 == 0:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title="Cloud sole-COO failover active (Mac heartbeat stale)",
                    detail=str({"peer": peer, "probe": probe})[:500],
                    origin="cloud",
                    payload={"peer": peer, "probe": probe},
                    dedup_ttl_s=6 * 3600,
                )
                self._stats["failover"] += 1
            await self._log_event(
                "peer_failover", "YELLOW", str(peer)[:500],
                {"peer": peer, "probe": probe},
            )
            return {
                "status": "ok", "mode": "cloud_sole", "peer": peer, "probe": probe,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}
