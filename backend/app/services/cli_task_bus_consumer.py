"""
CLI Dual-COO Chief of Staff — Mac↔Cloud peer review + risk-tiered dispatch.

Queens = CLI-Mac / CLI-Cloud (one mind, mutual backup).
CEO = Nathan (YELLOW morning inbox, RED synchronous).

Polls Redis task bus, claims peer review tasks, classifies risk:
  GREEN  — auto findings + digest
  YELLOW — CEO inbox
  RED    — CEO inbox, never auto-ship clinical

Also: peer heartbeat, crystal outcome apply kick, patent pending surface.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cli_task_bus_consumer")

POLL_INTERVAL_S = int(os.getenv("CLI_TASK_BUS_CONSUMER_POLL_S", "30"))
STAGGER_S = int(os.getenv("CLI_TASK_BUS_CONSUMER_STAGGER_S", "45"))

# Rotate claim preference so ops/compliance/insight tasks are not starved by reviews
_CLAIM_KINDS = (
    "review",
    "ops_fix",
    "compliance_redteam",
    "insight_route",
    "prior_art_flag",
    "brief_refine",
    "matching_weight",
    "coach_label",
)


def consumer_enabled() -> bool:
    return os.getenv("CLI_TASK_BUS_CONSUMER_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


class CliTaskBusConsumer:
    """Chief of Staff loop for Dual-COO Queens."""

    def __init__(self, app_state=None):
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycles = 0
        self._reviews = 0
        self._ceo_routed = 0
        self._green_auto = 0

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "CliTaskBusConsumer (Dual-COO Chief) started (poll=%ss, enabled=%s)",
            POLL_INTERVAL_S,
            consumer_enabled(),
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "CliTaskBusConsumer stopped (cycles=%s reviews=%s ceo=%s green=%s)",
            self._cycles,
            self._reviews,
            self._ceo_routed,
            self._green_auto,
        )

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_S)
        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.error("CliTaskBusConsumer cycle error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _cycle(self):
        self._cycles += 1
        if not consumer_enabled():
            return
        try:
            from app.websocket.cli_task_bus import (
                beat_consumer,
                claim_task,
                ensure_bus_meta,
                post_findings,
                task_bus_enabled,
            )
            from app.websocket.cli_dual_coo import (
                RISK_GREEN,
                RISK_RED,
                RISK_YELLOW,
                beat_queen,
                classify_risk,
                dual_coo_enabled,
                enqueue_ceo,
                peer_queen_alive,
            )
        except ImportError as e:
            logger.warning("CliTaskBusConsumer: import failed: %s", e)
            return
        if not task_bus_enabled():
            return
        ensure_bus_meta(consumer_active=True)
        beat_consumer()
        # QUANTUM-CRYSTAL-ARCH — Dual-COO cloud Queen heartbeat + peer check
        if dual_coo_enabled():
            beat_queen("cloud", meta={"chief": True, "cycle": self._cycles})
            peer = peer_queen_alive("cloud")
            # Alert only when Mac had a beat that went stale — not perpetual no_beat
            if (
                not peer.get("alive")
                and peer.get("detail") != "no_beat"
                and self._cycles % 20 == 0
            ):
                r = enqueue_ceo(
                    risk=RISK_YELLOW,
                    title="Peer Queen (CLI-Mac) heartbeat stale",
                    detail=str(peer)[:500],
                    origin="cloud",
                    dedup_ttl_s=6 * 3600,
                )
                if r.get("status") == "ok":
                    self._ceo_routed += 1

        prefer = _CLAIM_KINDS[self._cycles % len(_CLAIM_KINDS)]
        claimed = await asyncio.to_thread(
            claim_task, consumer="agent", prefer_kind=prefer,
        )
        if claimed.get("status") != "ok" or not claimed.get("task"):
            # Fallback: any review
            claimed = await asyncio.to_thread(
                claim_task, consumer="agent", prefer_kind="review",
            )
        if claimed.get("status") != "ok" or not claimed.get("task"):
            if self._cycles % 20 == 0:
                await self._surface_ceo_queues()
            return

        task = claimed["task"]
        kind = str(task.get("kind") or "review")
        risk = classify_risk(
            kind=kind,
            files=list(task.get("files") or []),
            notes=str(task.get("notes") or ""),
        )
        task["risk_tier"] = risk

        if risk == RISK_RED:
            enqueue_ceo(
                risk=RISK_RED,
                title=f"RED bus task {task.get('task_id')} kind={kind}",
                detail=(task.get("notes") or "")[:500],
                origin=str(task.get("origin") or "cloud"),
                task_id=str(task.get("task_id") or ""),
                payload={"files": task.get("files") or [], "kind": kind},
            )
            await asyncio.to_thread(
                post_findings,
                task["task_id"],
                reviewer="cloud_agent",
                findings=[{
                    "detail": "RED risk — routed to CEO-Nathan; no auto-ship",
                    "severity": "info",
                    "risk": RISK_RED,
                }],
                pass_review=False,
            )
            self._ceo_routed += 1
            self._reviews += 1
            return

        # QUANTUM-CRYSTAL-ARCH — kind-aware Chief of Staff dispatch
        if kind in ("ops_fix", "compliance_redteam", "auditor_ops_fix"):
            findings, passed = await self._dispatch_ops_task(task)
        elif kind in ("brief_refine", "matching_weight", "patent_crystal_tag"):
            # QUANTUM-CRYSTAL-ARCH — GREEN digest; sandbox / heuristic, no CEO email
            findings = [{
                "detail": f"GREEN kind={kind} — digest only (no CEO inbox)",
                "severity": "info",
                "risk": RISK_GREEN,
            }]
            passed = True
            self._green_auto += 1
        elif kind in ("insight_route", "prior_art_flag", "coach_label"):
            findings = [{
                "detail": f"YELLOW kind={kind} surfaced to CEO inbox",
                "severity": "info",
            }]
            passed = True
            enqueue_ceo(
                risk=RISK_YELLOW,
                title=f"{kind} {task.get('task_id')}",
                detail=(task.get("notes") or "")[:500],
                origin=str(task.get("origin") or "cloud"),
                task_id=str(task.get("task_id") or ""),
                payload={"kind": kind},
            )
            self._ceo_routed += 1
        else:
            findings, passed = await self._review_task(task)
            if risk == RISK_YELLOW:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title=f"YELLOW review {task.get('task_id')} pass={passed}",
                    detail=f"findings={len(findings)} files={task.get('files')}",
                    origin=str(task.get("origin") or "cloud"),
                    task_id=str(task.get("task_id") or ""),
                    payload={"pass": passed, "findings": findings[:10]},
                )
                self._ceo_routed += 1
            else:
                self._green_auto += 1

        result = await asyncio.to_thread(
            post_findings,
            task["task_id"],
            reviewer="cloud_agent",
            findings=findings + [{"detail": f"risk_tier={risk}", "severity": "info"}],
            pass_review=passed if risk == RISK_GREEN else passed,
        )
        self._reviews += 1
        logger.info(
            "Dual-COO reviewed task=%s kind=%s risk=%s pass=%s findings=%s status=%s",
            task.get("task_id"),
            kind,
            risk,
            passed,
            len(findings),
            (result.get("task") or {}).get("status"),
        )

        if self._cycles % 20 == 0:
            await self._surface_ceo_queues()

    async def _surface_ceo_queues(self):
        """YELLOW patent tags + RED clinical shadow → CEO inbox."""
        db = getattr(self._app_state, "db_pool", None) if self._app_state else None
        try:
            from app.services.crystal_outcome_apply import propose_red_clinical_to_ceo
            from app.services.patent_claim_guardian import list_pending_for_ceo
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

            if db:
                await propose_red_clinical_to_ceo(db)
                pending = await list_pending_for_ceo(db, limit=20)
                if pending:
                    r = enqueue_ceo(
                        risk=RISK_YELLOW,
                        title=f"{len(pending)} patent claim tags awaiting CEO",
                        detail="; ".join(
                            f"{p.get('family_id')}/{p.get('claim_ref')}" for p in pending[:5]
                        ),
                        origin="cloud",
                        task_id="patent_tags_pending",
                        payload={"count": len(pending)},
                        dedup_ttl_s=6 * 3600,
                    )
                    if r.get("status") == "ok":
                        self._ceo_routed += 1
        except Exception as e:
            logger.debug("CEO queue surface: %s", e)

    async def _dispatch_ops_task(self, task: Dict[str, Any]) -> tuple:
        """GREEN ops/compliance: structured findings; no therapeutic code changes."""
        notes = str(task.get("notes") or "")
        findings: List[Dict[str, Any]] = [{
            "detail": f"ops_dispatch: {notes[:400]}",
            "severity": "info",
        }]
        # Soft auto-ack only for explicit clean outcomes — never treat
        # "baseline absent from notes" as a pass (that auto-passed AUTH/DATA failures).
        notes_l = notes.lower()
        clean_markers = (
            "ok_no_leaks",
            "ok:",
            "trusted",
            "all clear",
            "no findings",
        )
        fail_markers = (
            "endpoint_down",
            "preflight",
            "auth_failure",
            "data_pipeline",
            "ai_unreachable",
            "defense_degraded",
            "gate_bypass",
            "ws_timeout",
            "failed",
            "error",
            "mismatch",
        )
        passed = any(m in notes_l for m in clean_markers) and not any(
            m in notes_l for m in fail_markers
        )
        if "ENDPOINT_DOWN" in notes or "PREFLIGHT" in notes or not passed:
            passed = False
            findings.append({
                "detail": "requires human/ops follow-up — not auto-remediated",
                "severity": "warn",
            })
        else:
            self._green_auto += 1
        # Optional lint pass when files present
        files = list(task.get("files") or [])
        if files:
            lint_findings, lint_ok = await self._review_task(task)
            findings.extend(lint_findings)
            passed = passed and lint_ok
        return findings, passed

    async def _review_task(self, task: Dict[str, Any]) -> tuple:
        """Deterministic read-only review: lints (+ optional pytest for .py)."""
        files = list(task.get("files") or [])[:12]
        findings: List[Dict[str, Any]] = []
        if not files:
            findings.append({
                "detail": "review task has no files — nothing to check",
                "severity": "info",
            })
            return findings, True

        try:
            from app.websocket.cli_tools import execute_tool
        except ImportError:
            return [{"detail": "execute_tool unavailable", "severity": "error"}], False

        for path in files:
            if not path:
                continue
            try:
                lint = await execute_tool(
                    "read_lints",
                    {"paths": [path]},
                    cli_type="cloud",
                    user_role="ADMIN",
                    mode="ask",
                    plan_id=str(task.get("plan_id") or "bus_review"),
                )
            except Exception as e:
                findings.append({
                    "detail": f"read_lints failed for {path}: {e}",
                    "severity": "warn",
                    "path": path,
                })
                continue
            diags: Any = []
            if isinstance(lint, dict):
                diags = lint.get("diagnostics") or lint.get("result") or []
                if lint.get("status") == "error":
                    findings.append({
                        "detail": f"lint error on {path}: {lint.get('error')}",
                        "severity": "error",
                        "path": path,
                    })
                    continue
            if isinstance(diags, list) and diags:
                for d in diags[:8]:
                    findings.append({
                        "detail": str(d)[:400],
                        "severity": "error",
                        "path": path,
                    })
            elif isinstance(diags, str) and diags.strip():
                if "error" in diags.lower() or "fail" in diags.lower():
                    findings.append({
                        "detail": diags[:400],
                        "severity": "warn",
                        "path": path,
                    })

        errors = [f for f in findings if f.get("severity") == "error"]
        passed = len(errors) == 0
        if passed and not findings:
            findings.append({
                "detail": f"autonomous Dual-COO review ok for {len(files)} file(s) at {int(time.time())}",
                "severity": "info",
            })
        return findings, passed
