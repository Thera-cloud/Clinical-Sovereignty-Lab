"""LN7 Close Sentinel — daily percent digest (read-only reporter).

CONSTITUTION (verbatim): Sentinel is read-only and reports state; it never
advances state. Any code path where the sentinel's output feeds a promotion,
flag, or θ write is a constitution violation and gets rejected in review
regardless of convenience.

Writes ONLY: ln7_close_digest_snapshots + outcome_envelope(source=close_sentinel)
+ optional SendGrid digest email. Never flips flags, never writes θ, never
touches therapeutic_controller.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.ln7_close_percent_engine import (
    ItemScore,
    overall_weighted,
    score_all,
)

logger = logging.getLogger("nate.ln7_close_sentinel")

DIGEST_EMAIL = os.getenv("LN7_CLOSE_SENTINEL_EMAIL", "support@sovereignsanctuary.net")
YELLOW_CC = os.getenv("LN7_CLOSE_SENTINEL_YELLOW_CC", "").strip()
YELLOW_DAYS = 3
FLAG_KEY = "LN7_CLOSE_SENTINEL_ENABLED"
ENVELOPE_SOURCE = "close_sentinel"

OWNER_LABEL = {
    "clinician": "YOU",
    "cursor": "CURSOR",
    "ceo": "CEO",
    "calendar": "CALENDAR",
    "external": "EXTERNAL",
    "queens": "QUEENS",
}


def compose_digest(
    scores: List[ItemScore],
    *,
    day_index: int,
    prev_overall: Optional[float],
    prev_items: Optional[Dict[str, Any]] = None,
    alerts: Optional[List[str]] = None,
) -> Tuple[str, Optional[float], List[Dict[str, str]], List[str]]:
    """Pure digest composer — fixed format from ship spec."""
    alerts = list(alerts or [])
    overall = overall_weighted(scores)
    arrow = ""
    if overall is not None and prev_overall is not None:
        d = overall - prev_overall
        if abs(d) >= 0.05:
            arrow = f" ({'▲' if d > 0 else '▼'}{abs(d):.0f})"
    overall_s = f"{overall:.0f}%" if overall is not None else "UNKNOWN"

    def _line(ids: List[str]) -> str:
        parts = []
        by = {s.item_id: s for s in scores}
        for iid in ids:
            s = by.get(iid)
            if not s:
                continue
            mark = ""
            if prev_items and iid in prev_items:
                old = prev_items[iid]
                old_pct = old.get("pct")
                if s.pct is not None and old_pct is not None and s.pct > float(old_pct) + 0.05:
                    mark = "▲"
                elif s.pct is not None and old_pct is not None and s.pct < float(old_pct) - 0.05:
                    mark = "▼"
            parts.append(f"{iid} {s.display}{mark}")
        return " · ".join(parts)

    close_ids = ["#9", "#10", "#16", "#14a", "R4", "W"]
    crank_ids = ["#1", "#2", "#4", "#5", "#6", "#8", "#11", "#12"]
    human_ids = ["#3", "#7", "#13", "#15", "#17"]

    # Residuals collapsed for CLOSE line per spec "resid 60"
    resid = [s for s in scores if s.item_id in ("R4", "W")]
    resid_known = [s.pct for s in resid if s.pct is not None]
    resid_disp = (
        str(int(round(sum(resid_known) / len(resid_known))))
        if resid_known
        else "UNKNOWN"
    )
    close_main = _line(["#9", "#10", "#16", "#14a"])
    close_line = f"CLOSE  {close_main} · resid {resid_disp}"
    crank_line = f"CRANK  {_line(crank_ids)}"
    human_line = f"HUMAN  {_line(human_ids)}"

    blocked: List[Dict[str, str]] = []
    for s in scores:
        if s.blocked_hint and s.blocked_owner and s.blocked_owner != "queens":
            blocked.append(
                {
                    "owner": s.blocked_owner,
                    "item_id": s.item_id,
                    "hint": s.blocked_hint,
                }
            )
    # Critical path: lowest pilot-path pct with a human owner first
    priority = {"clinician": 0, "cursor": 1, "ceo": 2, "calendar": 3, "external": 4}
    blocked.sort(key=lambda b: (priority.get(b["owner"], 9), b["item_id"]))

    by_owner: Dict[str, List[str]] = {}
    for b in blocked:
        by_owner.setdefault(b["owner"], []).append(b["hint"])

    def _blocked_line(owner_key: str) -> str:
        label = OWNER_LABEL.get(owner_key, owner_key.upper())
        hints = by_owner.get(owner_key) or []
        if not hints:
            return f"BLOCKED ON {label}: none"
        # Dedup preserve order
        seen = []
        for h in hints:
            if h not in seen:
                seen.append(h)
        return f"BLOCKED ON {label}: {'; '.join(seen[:3])}"

    alert_s = "none" if not alerts else "; ".join(alerts[:5])
    deltas = []
    for s in scores:
        if s.delta_note:
            deltas.append(f"{s.item_id} {s.delta_note}")
        if prev_items and s.item_id in (prev_items or {}):
            old = prev_items[s.item_id]
            if s.pct is not None and old.get("pct") is not None:
                if abs(s.pct - float(old["pct"])) >= 0.5:
                    uri = s.evidence_uri or "no-uri"
                    deltas.append(f"{s.item_id} {old.get('display')}→{s.display} ({uri})")
    delta_s = "; ".join(deltas[:6]) if deltas else "none"

    body = "\n".join(
        [
            f"LN7 CLOSE — Day {day_index} — Overall {overall_s}{arrow}",
            "──────────────────────────────────────",
            close_line,
            crank_line,
            human_line,
            "──────────────────────────────────────",
            _blocked_line("clinician"),
            _blocked_line("cursor"),
            _blocked_line("ceo"),
            f"ALERTS: {alert_s}",
            f"Δ since yesterday: {delta_s}",
            "",
            "Governance: the sentinel makes completion visible, not true —",
            "numbers are only as honest as the evidence predicates.",
        ]
    )
    return body, overall, blocked, alerts


async def run_close_digest(
    db_pool,
    *,
    notification_system=None,
    inject_veto_miss: bool = False,
    force_send: bool = False,
) -> Dict[str, Any]:
    """Score + persist digest + email. Never advances system state."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}

    async with db_pool.acquire() as conn:
        scores, alerts = await score_all(conn, inject_veto_miss=inject_veto_miss)
        prev = await conn.fetchrow(
            """SELECT day_index, overall_pct, items_json, created_at
               FROM ln7_close_digest_snapshots
               ORDER BY created_at DESC LIMIT 1"""
        )
        day_index = int(prev["day_index"]) + 1 if prev else 1
        prev_overall = float(prev["overall_pct"]) if prev and prev["overall_pct"] is not None else None
        prev_items = {}
        if prev and prev["items_json"]:
            raw = prev["items_json"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, list):
                for it in raw:
                    if isinstance(it, dict) and it.get("item_id"):
                        prev_items[it["item_id"]] = it

        body, overall, blocked, alerts = compose_digest(
            scores,
            day_index=day_index,
            prev_overall=prev_overall,
            prev_items=prev_items,
            alerts=alerts,
        )
        yellow = day_index <= YELLOW_DAYS
        items_json = [
            {
                "item_id": s.item_id,
                "tier": s.tier,
                "pct": s.pct,
                "display": s.display,
                "evidence_uri": s.evidence_uri,
                "owner": s.owner,
                "weight": s.weight,
            }
            for s in scores
        ]
        evidence_refs = [
            {"item_id": s.item_id, "uri": s.evidence_uri}
            for s in scores
            if s.evidence_uri
        ]
        snap_id = await conn.fetchval(
            """INSERT INTO ln7_close_digest_snapshots
               (day_index, overall_pct, digest_text, items_json, blocked_json,
                alerts_json, evidence_refs, yellow_verify)
               VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7::jsonb,$8)
               RETURNING id""",
            day_index,
            overall,
            body,
            json.dumps(items_json),
            json.dumps(blocked),
            json.dumps(alerts),
            json.dumps(evidence_refs),
            yellow,
        )

    # Envelope write — digest record only (source tag)
    try:
        from app.services.ln7_outcome_envelope import write_envelope

        await write_envelope(
            db_pool,
            loop_name="close_sentinel",
            event_kind="daily_digest",
            domain_tag="governance",
            source_node=ENVELOPE_SOURCE,
            attribution={"source": ENVELOPE_SOURCE, "snapshot_id": str(snap_id)},
            metrics={
                "overall_pct": overall,
                "day_index": day_index,
                "yellow_verify": yellow,
                "item_count": len(scores),
            },
            provenance={"constitution": "read_only_reporter"},
        )
    except Exception as e:
        logger.warning("close_sentinel: envelope write failed: %s", e)

    emailed = False
    subject = f"{'YELLOW — ' if yellow else ''}LN7 CLOSE — Day {day_index} — Overall {overall if overall is not None else 'UNKNOWN'}%"
    recipients = [DIGEST_EMAIL]
    if yellow and YELLOW_CC and YELLOW_CC not in recipients:
        recipients.append(YELLOW_CC)

    if notification_system and hasattr(notification_system, "_send_email"):
        for to in recipients:
            try:
                await notification_system._send_email(to, subject, body, "ln7_close_digest")
                emailed = True
            except TypeError:
                try:
                    await notification_system._send_email(to, subject, body)
                    emailed = True
                except Exception as e:
                    logger.warning("close_sentinel: email to %s failed: %s", to, e)
            except Exception as e:
                logger.warning("close_sentinel: email to %s failed: %s", to, e)
    else:
        logger.info("LN7 CLOSE digest (no mailer):\n%s", body)

    # skyeye_activity append for audit trail (read-visible)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO skyeye_activity (type, content, platform)
                   VALUES ('ln7_close_digest_sent', $1, 'close_sentinel')""",
                subject + "\n" + body[:4000],
            )
    except Exception as e:
        logger.warning("close_sentinel: activity log failed: %s", e)

    return {
        "ok": True,
        "day_index": day_index,
        "overall": overall,
        "yellow": yellow,
        "emailed": emailed,
        "snapshot_id": str(snap_id),
        "alerts": alerts,
        "digest": body,
    }


class Ln7CloseSentinel:
    """Daily loop. Flag-gated. Read-only for system state."""

    def __init__(self, db_pool, notification_system=None, interval_seconds: int = 86400):
        self.db_pool = db_pool
        self.notification_system = notification_system
        self.interval = interval_seconds
        self._task = None
        self._running = False
        self._last_day: Optional[str] = None

    async def start(self):
        import asyncio

        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        import asyncio

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _enabled(self) -> bool:
        from app.services.ln7_feature_flags import flag_enabled

        return await flag_enabled(self.db_pool, FLAG_KEY, default=False)

    async def _run_loop(self):
        import asyncio

        await asyncio.sleep(240)  # stagger after other LN7 agents
        while self._running:
            try:
                if await self._enabled():
                    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if self._last_day != day:
                        await run_close_digest(
                            self.db_pool,
                            notification_system=self.notification_system,
                        )
                        self._last_day = day
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Ln7CloseSentinel cycle failed: %s", e)
            await asyncio.sleep(min(self.interval, 3600))  # poll hourly; send once/day


async def maybe_start_close_sentinel(app_state, db_pool) -> Any:
    """Boot helper — always registers a handle; starts loop only when flag on."""
    notify = getattr(app_state, "notification_system", None)
    agent = Ln7CloseSentinel(db_pool, notification_system=notify)
    app_state.ln7_close_sentinel = agent
    from app.services.ln7_feature_flags import flag_enabled

    if await flag_enabled(db_pool, FLAG_KEY, default=False):
        await agent.start()
        logger.info("Ln7CloseSentinel started (flag on)")
    else:
        logger.info("Ln7CloseSentinel registered (flag off — idle)")
    return agent
