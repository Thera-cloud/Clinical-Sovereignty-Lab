"""CEO Inbox → email/SMS notify + reply execution.

YELLOW: email to admin_nevedalnj@sovereignsanctuary.net
RED:    email + SMS to ADMIN_ALERT_PHONE / CEO_NOTIFY_SMS (586-524-3969)

Replies via approve@reply.sovereignsanctuary.net (or SMS) use:
  ACK / DISMISS — remove from CEO inbox (no clinical apply)
  APPROVE       — ack + apply payload actions when present
  REJECT / HOLD — ack (dismiss) without apply

# QUANTUM-CRYSTAL-ARCH — Dual-COO CEO remote inbox
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger("nate.ceo_inbox_notify")

CEO_NOTIFY_EMAIL = os.getenv(
    "CEO_NOTIFY_EMAIL", "admin_nevedalnj@sovereignsanctuary.net"
).strip()
CEO_NOTIFY_SMS = os.getenv(
    "CEO_NOTIFY_SMS",
    os.getenv("ADMIN_ALERT_PHONE", "+15865243969"),
).strip() or "+15865243969"

_SUBJECT_CEO_RE = re.compile(r"\[#ceo([0-9a-fA-F]{6,12})\]", re.IGNORECASE)


def ceo_short_id(item_id: str) -> str:
    """Last hex-ish segment of inbox id for subject token."""
    raw = (item_id or "").strip()
    if not raw:
        return ""
    tail = raw.split("-")[-1] if "-" in raw else raw
    return re.sub(r"[^0-9a-fA-F]", "", tail)[:8] or raw[-8:]


def extract_ceo_short_from_text(subject: str = "", body: str = "") -> Optional[str]:
    blob = f"{subject or ''}\n{body or ''}"
    m = _SUBJECT_CEO_RE.search(blob)
    if m:
        return m.group(1).lower()
    return None


def schedule_ceo_inbox_notify(item: Dict[str, Any]) -> None:
    """Fire-and-forget from sync enqueue_ceo when an event loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("ceo_inbox_notify: no running loop — skip notify")
        return
    loop.create_task(_safe_notify(item))


async def _safe_notify(item: Dict[str, Any]) -> None:
    try:
        await notify_ceo_inbox_item(item)
    except Exception as e:
        logger.warning("ceo_inbox_notify failed: %s", e)


async def notify_ceo_inbox_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Create strategy_proposals row + email (+ SMS if RED)."""
    from app.services.approval_protocol import ApprovalProtocolService

    risk = str(item.get("risk") or "YELLOW").upper()
    if risk not in ("YELLOW", "RED"):
        return {"status": "skipped", "reason": "not_ceo_tier"}

    db_pool = _resolve_db_pool()
    if not db_pool:
        return {"status": "error", "error": "no_db_pool"}

    protocol = ApprovalProtocolService(db_pool)
    proposal = await _insert_ceo_proposal(db_pool, item)
    if not proposal:
        return {"status": "error", "error": "insert_failed"}

    pid = proposal.get("proposal_id")
    email_id = await protocol.send_email_notification(
        proposal, to_email=CEO_NOTIFY_EMAIL
    )
    sms_sid = None
    if risk == "RED":
        sms_sid = await protocol.send_sms_notification(
            proposal, to_number=CEO_NOTIFY_SMS
        )

    if pid:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE strategy_proposals
                    SET status = 'pending_approval', updated_at = NOW(),
                        metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb
                    WHERE proposal_id = $1
                    """,
                    pid,
                    json.dumps({
                        "notification_email_id": email_id,
                        "notification_sms_sid": sms_sid,
                        "notified_at": datetime.utcnow().isoformat(),
                        "ceo_notify_email": CEO_NOTIFY_EMAIL,
                        "ceo_notify_sms": CEO_NOTIFY_SMS if risk == "RED" else None,
                    }),
                )
        except Exception as e:
            logger.warning("ceo_inbox_notify metadata update: %s", e)

    return {
        "status": "ok",
        "proposal_id": str(pid) if pid else "",
        "email_sent": email_id is not None,
        "sms_sent": sms_sid is not None,
        "risk": risk,
    }


async def handle_ceo_decision(
    *,
    db_pool,
    proposal: Dict[str, Any],
    decision: str,
    channel: str = "email",
    approver: str = "",
) -> Dict[str, Any]:
    """After ApprovalProtocol records ACK/APPROVE/REJECT/HOLD for a CEO item."""
    from app.websocket.cli_dual_coo import ack_ceo_inbox

    meta = proposal.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not meta.get("ceo_inbox"):
        return {"status": "skipped", "reason": "not_ceo_inbox"}

    item_id = str(meta.get("ceo_inbox_item_id") or "")
    payload = meta.get("ceo_payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    ack_result = {"status": "skipped"}
    if item_id and decision in ("ACK", "APPROVE", "REJECT", "HOLD"):
        ack_result = ack_ceo_inbox(item_id=item_id)

    apply_result: Dict[str, Any] = {}
    if decision == "APPROVE" and db_pool:
        apply_result = await _apply_ceo_payload(
            db_pool, payload, approved_by=approver or "email_ceo"
        )

    return {
        "status": "ok",
        "decision": decision,
        "channel": channel,
        "inbox_ack": ack_result,
        "apply": apply_result,
        "ceo_inbox_item_id": item_id,
    }


async def _apply_ceo_payload(
    db_pool, payload: Dict[str, Any], *, approved_by: str
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    shadow_ids = payload.get("shadow_ids") or payload.get("shadow_id")
    if shadow_ids is not None:
        if isinstance(shadow_ids, (int, str)):
            shadow_ids = [int(shadow_ids)]
        try:
            from app.services.crystal_outcome_apply import ceo_apply_clinical_shadows

            out["clinical"] = await ceo_apply_clinical_shadows(
                db_pool, list(shadow_ids), approved_by=approved_by
            )
        except Exception as e:
            out["clinical_error"] = str(e)[:200]

    tag_ids = payload.get("tag_ids") or payload.get("patent_tag_ids")
    if tag_ids:
        try:
            from app.services.patent_claim_guardian import ceo_approve_tags

            out["patents"] = await ceo_approve_tags(
                db_pool, list(tag_ids), reviewed_by=approved_by
            )
        except Exception as e:
            out["patents_error"] = str(e)[:200]
    return out


async def _insert_ceo_proposal(db_pool, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    risk = str(item.get("risk") or "YELLOW").upper()
    pg_risk = "high" if risk == "RED" else "medium"
    title = (item.get("title") or "CEO inbox item")[:280]
    if len(title) < 10:
        title = f"CEO {risk}: {title}".ljust(10)[:280]
    detail = (item.get("detail") or "")[:1800]
    short = ceo_short_id(str(item.get("id") or ""))
    # Subject token uses [#ceoSHORT] — also embed in title for recovery
    title_with_token = f"{title} [#ceo{short}]"[:300]

    meta = {
        "ceo_inbox": True,
        "ceo_inbox_item_id": item.get("id"),
        "ceo_short_id": short,
        "ceo_payload": item.get("payload") or {},
        "ceo_origin": item.get("origin"),
        "ceo_task_id": item.get("task_id"),
        "ceo_risk": risk,
        "details": {
            "objective": f"CEO Dual-COO inbox item ({risk}): {title}",
            "reasoning": detail or "Surfaced by Dual-COO for CEO review.",
            "action_steps": [
                "Reply ACK to dismiss from inbox",
                "Reply APPROVE to dismiss and apply linked actions (if any)",
                "Reply REJECT or HOLD to dismiss without apply",
            ],
            "expected_impact": "Clears CEO inbox and optionally applies RED clinical/patent actions.",
            "rollback": "No automatic reverse — re-open via Sovereign Command CEO Inbox if needed.",
        },
    }
    description = (
        f"{detail}\n\n"
        f"Inbox ID: {item.get('id')}\n"
        f"Origin: {item.get('origin')} · task: {item.get('task_id')}\n"
        f"Reply ACK / APPROVE / REJECT / HOLD to {ApprovalProtocolService_REPLY_TO()}\n"
    )
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO strategy_proposals
                    (title, description, action_type, proposed_by, risk, status,
                     execution_payload, rollback_payload, auto_execute_after, metadata)
                VALUES ($1, $2, $3, $4, $5, 'pending_approval', $6, $7, NULL, $8)
                RETURNING *
                """,
                title_with_token,
                description[:4000],
                "ceo_inbox_review",
                "dual_coo",
                pg_risk,
                json.dumps({"ceo_inbox_item_id": item.get("id")}),
                json.dumps({"description": "Dismiss only — no auto reverse"}),
                json.dumps(meta),
            )
            return dict(row) if row else None
    except Exception as e:
        logger.warning("ceo_inbox_notify insert proposal: %s", e)
        return None


def ApprovalProtocolService_REPLY_TO() -> str:
    return "approve@reply.sovereignsanctuary.net"


def _resolve_db_pool():
    try:
        import app.main as main_mod

        app = getattr(main_mod, "app", None)
        if app is not None:
            pool = getattr(app.state, "db_pool", None)
            if pool is not None:
                return pool
    except Exception:
        pass
    return None


async def resolve_ceo_proposal_by_short(db_pool, short_id: str) -> Optional[UUID]:
    """Match metadata.ceo_short_id or title [#ceo…] token."""
    if not db_pool or not short_id:
        return None
    sid = short_id.lower().strip()
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT proposal_id FROM strategy_proposals
                WHERE status IN ('proposed', 'pending_approval', 'approved')
                  AND (
                    metadata->>'ceo_short_id' = $1
                    OR title ILIKE $2
                  )
                ORDER BY created_at DESC
                LIMIT 1
                """,
                sid,
                f"%[#ceo{sid}]%",
            )
            return row["proposal_id"] if row else None
    except Exception as e:
        logger.warning("resolve_ceo_proposal_by_short: %s", e)
        return None
