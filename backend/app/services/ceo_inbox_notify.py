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

from app.ceo_notify_policy import ceo_external_notify_enabled
from app.services.ceo_brief_schema import (
    default_decision_fields,
    format_decision_summary_block,
    normalize_decision_fields,
    payload_has_decision_brief,
)

logger = logging.getLogger("nate.ceo_inbox_notify")

CEO_NOTIFY_EMAIL = os.getenv(
    "CEO_NOTIFY_EMAIL", "admin_nevedalnj@sovereignsanctuary.net"
).strip()
CEO_NOTIFY_SMS = os.getenv(
    "CEO_NOTIFY_SMS",
    os.getenv("ADMIN_ALERT_PHONE", "+15865243969"),
).strip() or "+15865243969"

_SUBJECT_CEO_RE = re.compile(r"\[#ceo([0-9a-fA-F]{6,12})\]", re.IGNORECASE)

# Plain-English maps so CEO emails never rely on opaque codes alone.
_TRUST_CATEGORY_EN = {
    "ENDPOINT_DOWN": (
        "One or more audited API checks did not return a healthy response "
        "(timeout, 5xx, or empty payload the auditor treats as failed)."
    ),
    "DATA_PIPELINE": (
        "A trust baseline count or data-shape check does not match what the "
        "auditor expected (often after adding/removing endpoints)."
    ),
    "AUTH_FAILURE": (
        "The auditor could not authenticate (missing/expired token or role gate)."
    ),
    "GATE_BYPASS": (
        "A tier or feature gate did not enforce access the way the auditor expects."
    ),
    "WS_TIMEOUT": (
        "A WebSocket handshake or flow the auditor probes timed out or failed."
    ),
    "L2_ISSUE": (
        "A response payload failed structural (L2) validation even if HTTP looked OK."
    ),
    "AI_UNREACHABLE": (
        "Azure/OpenAI or another AI dependency the auditor checks is unreachable."
    ),
    "PREFLIGHT_FAIL": (
        "A Trust Enforcer pre-flight check failed (audit token, test accounts, "
        "admin MFA, Azure env, or Redis)."
    ),
    "DEFENSE_DEGRADED": (
        "A Hive Defense / security subsystem check reported degraded or offline."
    ),
}


def _with_decision(
    *,
    objective: str,
    reasoning: str,
    steps: list,
    risk: str,
    expected_impact: str,
    rollback: str,
    decision: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach canonical decision sections + summary_block."""
    payload = payload if isinstance(payload, dict) else {}
    base = decision or default_decision_fields(risk)
    # Prefer payload overrides when present
    if payload.get("what_it_should_do") or payload.get("bottom_line"):
        base = normalize_decision_fields(
            what_it_should_do=payload.get("what_it_should_do") or base["what_it_should_do"],
            what_it_should_not_be=payload.get("what_it_should_not_be")
            or base["what_it_should_not_be"],
            bottom_line=payload.get("bottom_line") or base["bottom_line"],
        )
    return {
        "objective": objective[:600],
        "reasoning": reasoning[:1200],
        "action_steps": steps[:8],
        "expected_impact": expected_impact[:400],
        "rollback": rollback,
        "what_it_should_do": base["what_it_should_do"],
        "what_it_should_not_be": base["what_it_should_not_be"],
        "bottom_line": base["bottom_line"],
        "summary_block": format_decision_summary_block(
            objective=objective,
            what_it_should_do=base["what_it_should_do"],
            what_it_should_not_be=base["what_it_should_not_be"],
            bottom_line=base["bottom_line"],
            steps=steps,
            risk=risk,
        ),
    }


def build_ceo_review_brief(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build English objective + decision brief for CEO email + SMS + dashboard.

    Call sites may pass terse titles (codes, task ids). This expands them into
    what happened, what APPROVE should/should not mean, and bottom line.
    """
    risk = str(item.get("risk") or "YELLOW").upper()
    title = (item.get("title") or "CEO inbox item").strip()
    detail = (item.get("detail") or "").strip()
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    origin = str(item.get("origin") or "cloud")
    task_id = str(item.get("task_id") or "")
    title_l = title.lower()
    kind = str(payload.get("kind") or "")

    # LN7 revision candidate (promote / premature HOLD)
    if (
        kind == "ln7_revision_candidate"
        or "ln7 revision candidate" in title_l
        or (origin == "ln7" and "revision" in title_l and "activat" not in title_l)
    ):
        return _build_ln7_revision_brief(item, risk=risk, title=title, detail=detail, payload=payload)

    # QUANTUM-CRYSTAL-ARCH — Phase A: PRE6 fuel stall → volume burst on APPROVE
    if (
        kind == "ln7_fuel_volume_burst"
        or "fuel stalled" in title_l
        or "pre6 gate" in title_l
        or title_l.startswith("[fuel")
    ):
        domain = str(payload.get("domain") or "coding")
        ask = str(payload.get("ask_of_ceo") or "").strip()
        steps = [
            ask
            or (
                f"Reply APPROVE to run a PRE6 fuel volume burst for {domain} "
                "(ci_pack shadow forks + gauge; 12h cooldown)."
            ),
            "Reply ACK/REJECT to clear the inbox without running a burst.",
            "Paid bakeoff (LN7_BURST_ALLOW_PAID) is NOT started by this APPROVE.",
        ]
        decision = normalize_decision_fields(
            what_it_should_do=[
                f"Run allowlisted fuel volume burst for {domain} when you APPROVE.",
                "Return smoke + Dual-COO/LLM reflect in the confirmation email.",
            ],
            what_it_should_not_be=[
                "Not a paid bakeoff or MUST-sequence flip.",
                "Not open-ended Queens coding on APPROVE.",
            ],
            bottom_line=(
                f"APPROVE → fuel burst ({domain}, 12h cooldown); ACK/REJECT → clear only."
            ),
        )
        return _with_decision(
            objective=(
                f"PRE6 fuel alert for {domain}: trainable row volume needs attention. "
                f"{title}"
            )[:600],
            reasoning=(detail or "Fuel gauge escalated to CEO inbox.")[:1200],
            steps=steps[:8],
            risk=risk,
            expected_impact=(
                "APPROVE runs ci_pack shadow materialize + gauge; confirmation includes "
                "execution report. Cooldown blocks a second burst within 12h."
            )[:400],
            rollback="No reverse — new packs remain; re-run only after cooldown.",
            decision=decision,
            payload=payload,
        )

    # QUANTUM-CRYSTAL-ARCH — Adaptive Growth content review
    if kind == "growth_content_review":
        objective = str(
            payload.get("ceo_summary") or payload.get("what_happened") or title
        )[:600]
        reasoning = str(
            payload.get("why_it_matters") or payload.get("reasoning") or detail
        )[:1200]
        ask = str(payload.get("ask_of_ceo") or "").strip()
        steps = [s for s in (payload.get("action_steps") or []) if s]
        if ask and ask not in steps:
            steps = [ask] + steps
        if not steps:
            steps = [
                "Reply APPROVE to schedule/publish.",
                "Reply REJECT to decline.",
                "Reply REWRITE <note> for a revision draft.",
                "Reply DELAY +3d (or ISO date) to reschedule.",
            ]
        decision = normalize_decision_fields(
            what_it_should_do=payload.get("what_it_should_do")
            or [
                "Approve or rewrite growth content from email.",
                "Inspect signed proof URL before deciding.",
            ],
            what_it_should_not_be=payload.get("what_it_should_not_be")
            or [
                "Not an LLM performance forecast.",
                "Not auto-publish without APPROVE.",
            ],
            bottom_line=payload.get("bottom_line")
            or "APPROVE schedules; REJECT declines; REWRITE creates a revision.",
        )
        return _with_decision(
            objective=objective,
            reasoning=reasoning,
            steps=steps[:8],
            risk=risk,
            expected_impact=str(
                payload.get("expected_impact")
                or "APPROVE → scheduled/published; REJECT → rejected."
            )[:400],
            rollback="RETRACT via dashboard or reply RETRACT after publish.",
            decision=decision,
            payload=payload,
        )

    # Prefer caller-supplied brief fields when present (patent_reflect uses this path)
    if payload.get("ceo_summary") or payload.get("what_happened"):
        objective = str(
            payload.get("ceo_summary") or payload.get("what_happened") or title
        )[:600]
        reasoning = str(
            payload.get("why_it_matters")
            or payload.get("reasoning")
            or detail
            or "Escalated by Dual-COO for CEO review."
        )[:1200]
        ask = str(
            payload.get("ask_of_ceo")
            or payload.get("what_i_need")
            or ""
        ).strip()
        steps = [s for s in (payload.get("action_steps") or []) if s]
        if ask and ask not in steps:
            steps = [ask] + steps
        if not steps:
            steps = _default_reply_steps(risk)
        impact_default = (
            "Your decision routes Dual-COO to sandbox CLI or an IDE brief; "
            "filed patent claim docs are never auto-edited."
            if payload.get("kind") == "patent_reflect"
            else "Clears CEO inbox after your reply; linked apply runs only on APPROVE."
        )
        decision = normalize_decision_fields(
            what_it_should_do=payload.get("what_it_should_do")
            or [
                "Authorize Dual-COO follow-up / sandbox or IDE brief as described.",
                "Clear this CEO inbox item after your reply.",
            ],
            what_it_should_not_be=payload.get("what_it_should_not_be")
            or [
                "Not an automatic edit of filed patent claim documents.",
                "Not a silent production ship without your verb.",
            ],
            bottom_line=payload.get("bottom_line")
            or (
                "APPROVE only if you accept the proposed Dual-COO path; else REJECT/HOLD."
            ),
        )
        return _with_decision(
            objective=objective,
            reasoning=reasoning,
            steps=steps[:8],
            risk=risk,
            expected_impact=str(payload.get("expected_impact") or impact_default)[:400],
            rollback="No automatic reverse — re-open via Sovereign Command CEO Inbox if needed.",
            decision=decision,
            payload=payload,
        )

    cat = str(payload.get("category") or "").upper()
    auditor = str(payload.get("auditor") or "").strip()

    # Trust Enforcer escalations
    m = re.match(
        r"Trust\s+(YELLOW|RED):\s*(.+?)\s*\(([A-Z_]+)\)\s*$",
        title,
        re.IGNORECASE,
    )
    if m or "trust yellow" in title_l or "trust red" in title_l:
        if m:
            risk_word, auditor_name, cat = m.group(1).upper(), m.group(2).strip(), m.group(3).upper()
        else:
            risk_word, auditor_name = risk, auditor or "an auditor"
        cat_en = _TRUST_CATEGORY_EN.get(
            cat,
            f"Trust category code {cat or 'UNKNOWN'} — see detail below for the auditor message.",
        )
        who = auditor or auditor_name or "Trust auditor"
        objective = (
            f"{who} reported a {risk_word} trust problem"
            + (f" ({cat})" if cat else "")
            + ". This is not a Dual-COO learning task — it means a production "
            "trust check failed and needs your attention or acknowledgment."
        )
        reasoning = (
            f"What the code means: {cat_en}\n\n"
            f"Auditor message: {detail or '(no further detail provided)'}"
        )
        steps = [
            f"Open Sovereign Command → Trust / {who} and identify the failing check(s).",
            "Reply APPROVE to re-run that auditor (reprobe) + smoke/reflect, then clear inbox.",
            "Reply ACK/REJECT to clear without re-running the auditor.",
            "If still broken after reprobe, remediate via Dual-COO / ops — APPROVE does not patch code.",
        ]
        ask = str(payload.get("ask_of_ceo") or "").strip()
        if ask:
            steps = [ask] + steps
        decision = normalize_decision_fields(
            what_it_should_do=[
                "Re-run the named auditor on APPROVE and return a smoke/reflect report.",
                "Clear the CEO inbox item after your reply.",
            ],
            what_it_should_not_be=[
                "Not an automatic code/endpoint patch — reprobe only.",
                "Not a Dual-COO learning / patent task.",
            ],
            bottom_line=(
                f"{risk_word}: APPROVE → trust_reprobe ({who}); ACK/REJECT → clear only."
            ),
        )
        return _with_decision(
            objective=objective[:600],
            reasoning=reasoning[:1200],
            steps=steps[:8],
            risk=risk_word,
            expected_impact=(
                "APPROVE re-runs the auditor and emails an execution report (smoke + reflect). "
                "It does not auto-patch failing checks."
            ),
            rollback="No automatic reverse — re-open via Sovereign Command CEO Inbox if needed.",
            decision=decision,
            payload=payload,
        )

    # Six-Quotient battery
    if "six-quotient" in title_l or payload.get("kind", "").startswith("six_quotient"):
        q = payload.get("quotient") or "?"
        objective = (
            f"Six-Quotient Battery flagged quotient {q} for CEO review "
            f"({'regression — urgent' if risk == 'RED' else 'dip — candidate fix'})."
        )
        reasoning = (
            "External scores (or gap analysis vs baseline) show this quotient needs "
            "attention. Dual-COO will not change clinical prompts without your call.\n\n"
            f"Technical detail: {detail[:800] or '(see payload)'}"
        )
        steps = [
            "Review the Six-Quotient run / scorecard for this quotient.",
            "Reply APPROVE if you accept the finding and want growth crystals / Dual-COO follow-up to proceed as queued.",
            "Reply HOLD if you want the item parked without apply.",
        ]
        decision = normalize_decision_fields(
            what_it_should_do=[
                "Accept or park a Six-Quotient finding for Dual-COO / growth follow-up.",
            ],
            what_it_should_not_be=[
                "Not an automatic clinical prompt rewrite without your APPROVE path.",
            ],
            bottom_line=(
                "RED regression — decide now."
                if risk == "RED"
                else "YELLOW dip — APPROVE to proceed or HOLD to park."
            ),
        )
        return _with_decision(
            objective=objective[:600],
            reasoning=reasoning[:1200],
            steps=steps,
            risk=risk,
            expected_impact="Clears inbox; APPROVE may allow linked growth/enqueue paths already prepared.",
            rollback="No automatic reverse — re-open via Sovereign Command CEO Inbox if needed.",
            decision=decision,
            payload=payload,
        )

    # Clinical / coach hold
    if "clinical" in title_l or "clinical_hold" in title_l or risk == "RED" and "coach" in title_l:
        objective = (
            f"{title} — clinical or defense material requires CEO (Nathan) sign-off "
            "before apply; Dual-COO will not auto-ship."
        )
        reasoning = detail or "Sensitive clinical path escalated to RED."
        steps = [
            "Read the clinical/defense detail carefully.",
            "Reply APPROVE only if you authorize applying the linked shadow/actions.",
            "Reply REJECT or HOLD to dismiss without applying.",
        ]
        decision = normalize_decision_fields(
            what_it_should_do=[
                "Authorize applying linked clinical shadow / crystal actions on APPROVE.",
            ],
            what_it_should_not_be=[
                "Not a routine marketing or trust-baseline ack.",
                "Not auto-ship — Dual-COO waits for your verb.",
            ],
            bottom_line="APPROVE only if you authorize clinical apply; else REJECT/HOLD.",
        )
        return _with_decision(
            objective=objective[:600],
            reasoning=reasoning[:1200],
            steps=steps,
            risk=risk,
            expected_impact="APPROVE may apply linked clinical shadow / crystal actions.",
            rollback="No automatic reverse — re-open via Sovereign Command CEO Inbox if needed.",
            decision=decision,
            payload=payload,
        )

    # Generic fallback — still English-first
    objective = (
        f"CEO review requested ({risk}): {title}. "
        "Please decide whether to acknowledge, authorize apply, or reject."
    )
    reasoning = (
        f"{detail or 'No additional detail was attached.'}\n\n"
        f"Origin: {origin}"
        + (f" · task reference: {task_id}" if task_id else "")
        + ". Reference IDs are for tracing only — the ask is the decision above."
    )
    steps = _default_reply_steps(risk)
    decision = default_decision_fields(risk)
    return _with_decision(
        objective=objective[:600],
        reasoning=reasoning[:1200],
        steps=steps,
        risk=risk,
        expected_impact="Clears CEO inbox after your reply; linked apply runs only on APPROVE.",
        rollback="No automatic reverse — re-open via Sovereign Command CEO Inbox if needed.",
        decision=decision,
        payload=payload,
    )


def _build_ln7_revision_brief(
    item: Dict[str, Any],
    *,
    risk: str,
    title: str,
    detail: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    rid = str(
        payload.get("revision_id")
        or item.get("task_id")
        or ""
    ).strip()
    if not rid:
        m = re.search(r"(LN7-[0-9TZz:-]+)", title)
        rid = m.group(1) if m else "unknown"
    readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
    ready = bool(payload.get("ready") if "ready" in payload else readiness.get("ready"))
    checks = readiness.get("checks") if isinstance(readiness.get("checks"), dict) else {}
    checklist = str(payload.get("checklist") or readiness.get("reason") or detail or "")
    status = str(payload.get("status") or readiness.get("status") or checks.get("status") or "")
    base = str(payload.get("base_checkpoint") or readiness.get("base_checkpoint") or "")
    adapter = str(payload.get("adapter_path") or readiness.get("adapter_path") or "")
    peft = str(payload.get("peft_url") or readiness.get("peft_url") or "")
    pack_n = readiness.get("pack_n", checks.get("private_pack_n", "?"))
    canary = str(
        readiness.get("canary_status") or checks.get("canary_status") or "none"
    )

    lines = [
        f"Revision: {rid}",
        f"Status: {status or 'n/a'} · ready={ready}",
        f"Base: {base or 'n/a'}",
        f"Adapter: {adapter or '(missing)'}",
        f"PEFT: {peft or '(missing)'}",
        f"Private pack outcomes: n={pack_n}",
        f"Canary: {canary}",
        f"Checklist: {checklist[:400]}",
    ]
    objective = (
        f"LN7 revision candidate {rid} "
        + ("is READY for serving activate." if ready else "is PREMATURE — do not activate.")
    )
    reasoning = "\n".join(lines)

    if ready:
        decision = normalize_decision_fields(
            what_it_should_do=[
                "On APPROVE: flip Sanctuary CLI LN7 serving alias to this revision (activate_revision).",
                "Keep prior revision registered for rollback via re-activate.",
            ],
            what_it_should_not_be=[
                "Not clinical AGI / Tier-2 evidence.",
                "Not auto-clinical traffic; LN7 path stays non-clinical coding.",
                "APPROVE does not invent a missing adapter — readiness already verified PEFT smoke.",
            ],
            bottom_line=str(
                payload.get("bottom_line")
                or f"APPROVE to activate {rid} as default LN7 brain; REJECT/HOLD leaves shadow."
            ),
        )
        steps = [
            "Confirm private bakeoff + PEFT health match the checklist above.",
            "Reply APPROVE to activate this revision (serving flip).",
            "Reply REJECT or HOLD to leave incumbent serving / keep shadow.",
        ]
        impact = "APPROVE calls activate_revision for this candidate."
        risk_out = "RED"
    else:
        decision = normalize_decision_fields(
            what_it_should_do=[
                "Treat as informational HOLD: training/register completed but promote gate not met.",
                "Wait for private bakeoff + canary READY renotify before activating.",
            ],
            what_it_should_not_be=[
                "Not an activate ask — APPROVE will not flip serving while readiness.ready=false.",
                "Not AGI; not auto-clinical; missing adapter/PEFT/packs cannot be wished into existence.",
            ],
            bottom_line=str(
                payload.get("bottom_line")
                or f"HOLD — {rid} premature ({readiness.get('reason') or 'not ready'})."
            ),
        )
        steps = [
            "ACK or HOLD to clear noise, or leave pending until a READY renotify arrives.",
            "Do not APPROVE expecting activate — apply is gated on readiness.ready.",
            "Run private bakeoff / canary evaluate, then expect a second CEO ping with [READY].",
        ]
        impact = "No serving flip on APPROVE while premature."
        risk_out = risk if risk in ("YELLOW", "RED") else "YELLOW"

    return _with_decision(
        objective=objective[:600],
        reasoning=reasoning[:1200],
        steps=steps,
        risk=risk_out,
        expected_impact=impact,
        rollback="Rollback = re-activate prior revision_id via Command / API.",
        decision=decision,
        payload=payload,
    )


def _default_reply_steps(risk: str) -> list:
    return [
        "Reply ACK to dismiss from inbox (no apply).",
        "Reply APPROVE to dismiss and apply linked actions if any are attached.",
        "Reply REJECT or HOLD to dismiss without apply.",
        f"This is a {risk} item — "
        + (
            "RED also sends SMS; treat as synchronous CEO-only."
            if risk == "RED"
            else "YELLOW is morning-batch CEO review."
        ),
    ]


def _format_summary_block(
    objective: str,
    reasoning: str,
    steps: list,
    risk: str,
    *,
    what_it_should_do: Any = None,
    what_it_should_not_be: Any = None,
    bottom_line: str = "",
) -> str:
    """Legacy signature retained; emits canonical decision sections."""
    decision = normalize_decision_fields(
        what_it_should_do=what_it_should_do
        or ["See WHAT I NEED — authorize or dismiss this Dual-COO item."],
        what_it_should_not_be=what_it_should_not_be
        or ["Not an automatic production ship without your reply verb."],
        bottom_line=bottom_line
        or (reasoning[:240] if reasoning else f"{risk}: review and reply ACK/APPROVE/REJECT/HOLD."),
    )
    return format_decision_summary_block(
        objective=objective,
        what_it_should_do=decision["what_it_should_do"],
        what_it_should_not_be=decision["what_it_should_not_be"],
        bottom_line=decision["bottom_line"],
        steps=steps,
        risk=risk,
    )


def enrich_ceo_inbox_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy backfill decision brief onto a Redis inbox item for GET /inbox."""
    if not isinstance(item, dict):
        return item
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    if payload_has_decision_brief(payload) and isinstance(item.get("brief"), dict):
        return item
    from app.services.ceo_brief_schema import attach_ceo_brief_to_item

    return attach_ceo_brief_to_item(dict(item))


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
        return {"status": "skipped", "reason": "duplicate_or_insert_failed"}

    pid = proposal.get("proposal_id")
    email_id = None
    sms_sid = None
    if ceo_external_notify_enabled():
        email_id = await protocol.send_email_notification(
            proposal, to_email=CEO_NOTIFY_EMAIL
        )
        if risk == "RED":
            sms_sid = await protocol.send_sms_notification(
                proposal, to_number=CEO_NOTIFY_SMS
            )
    else:
        logger.info(
            "ceo_inbox_notify: external notify disabled (ENVIRONMENT=%s) — "
            "proposal %s recorded without email/SMS",
            os.getenv("ENVIRONMENT", "production"),
            pid,
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


async def decide_ceo_inbox_items(
    *,
    db_pool,
    decision: str,
    item_id: str = "",
    decide_all: bool = False,
    approver: str = "",
) -> Dict[str, Any]:
    """Dashboard path: ACK/APPROVE/REJECT/HOLD one Redis item or all.

    When a matching strategy_proposals row exists, routes through
    ApprovalProtocol.handle_inbound_reply (same as email buttons) so proposal
    status, audit trail, and APPROVE apply stay consistent.
    """
    from app.services.approval_protocol import ApprovalProtocolService
    from app.websocket.cli_dual_coo import ack_ceo_inbox, peek_ceo_inbox

    decision_u = (decision or "").strip().upper()
    if decision_u not in ("ACK", "APPROVE", "REJECT", "HOLD"):
        return {"status": "error", "error": "invalid_decision"}

    items = peek_ceo_inbox(100)
    if decide_all:
        targets = list(items)
    else:
        targets = [i for i in items if str(i.get("id") or "") == str(item_id)]
        if not targets:
            return {"status": "error", "error": "item_not_found", "processed": 0}

    results: list = []
    processed = 0
    if db_pool:
        protocol = ApprovalProtocolService(db_pool)
        for it in targets:
            iid = str(it.get("id") or "")
            if not iid:
                continue
            proposal_id = None
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT proposal_id FROM strategy_proposals
                        WHERE status IN ('proposed', 'pending_approval')
                          AND (
                            metadata->>'ceo_inbox_item_id' = $1
                            OR execution_payload->>'ceo_inbox_item_id' = $1
                          )
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        iid,
                    )
                    if row:
                        proposal_id = row["proposal_id"]
            except Exception as e:
                logger.warning("decide_ceo_inbox lookup %s: %s", iid, e)

            if proposal_id is not None:
                try:
                    reply = await protocol.handle_inbound_reply(
                        decision_u,
                        channel="dashboard",
                        proposal_id=proposal_id,
                        approver_identity=approver or "dashboard_ceo",
                    )
                    results.append({
                        "item_id": iid,
                        "proposal_id": str(proposal_id),
                        "decision": decision_u,
                        "reply": {
                            "decision": reply.get("decision"),
                            "error": reply.get("error"),
                        },
                    })
                    processed += 1
                    continue
                except Exception as e:
                    logger.warning("decide_ceo_inbox reply %s: %s", iid, e)

            # No pending proposal (or reply failed) — clear Redis + apply linked payload
            apply_result: Dict[str, Any] = {}
            payload = it.get("payload") if isinstance(it.get("payload"), dict) else {}
            if decision_u == "APPROVE" and db_pool and payload:
                apply_result = await _apply_ceo_payload(
                    db_pool, payload, approved_by=approver or "dashboard_ceo"
                )
            elif decision_u == "REJECT" and db_pool and payload:
                apply_result = await _reject_ceo_payload(
                    db_pool, payload, approved_by=approver or "dashboard_ceo"
                )
            ack = ack_ceo_inbox(item_id=iid)
            try:
                from app.websocket.cli_dual_coo import (
                    ceo_issue_fingerprint,
                    mark_ceo_issue_decided,
                )

                fp = str(it.get("issue_fp") or "")
                if not fp:
                    fp = ceo_issue_fingerprint(
                        title=str(it.get("title") or ""),
                        origin=str(it.get("origin") or ""),
                        task_id=str(it.get("task_id") or ""),
                        payload=payload,
                    )
                mark_ceo_issue_decided(fp)
            except Exception as e:
                logger.debug("ceo issue suppress inbox_only: %s", e)
            results.append({
                "item_id": iid,
                "proposal_id": None,
                "decision": decision_u,
                "inbox_only": True,
                "ack": ack,
                "apply": apply_result,
            })
            processed += 1
    else:
        if decide_all:
            ack = ack_ceo_inbox(ack_all=True)
            return {
                "status": "ok",
                "decision": decision_u,
                "processed": int(ack.get("acked") or 0),
                "results": [{"decide_all": True, "ack": ack}],
                "note": "no_db_pool — redis clear only",
            }
        ack = ack_ceo_inbox(item_id=item_id)
        return {
            "status": "ok",
            "decision": decision_u,
            "processed": int(ack.get("acked") or 0),
            "results": [{"item_id": item_id, "ack": ack}],
            "note": "no_db_pool — redis clear only",
        }

    return {
        "status": "ok",
        "decision": decision_u,
        "processed": processed,
        "results": results,
    }


async def handle_ceo_decision(
    *,
    db_pool,
    proposal: Dict[str, Any],
    decision: str,
    channel: str = "email",
    approver: str = "",
    modifier_text: Optional[str] = None,
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
    if item_id and decision in (
        "ACK",
        "APPROVE",
        "REJECT",
        "HOLD",
        "REWRITE",
        "DELAY",
        "RETRACT",
    ):
        ack_result = ack_ceo_inbox(item_id=item_id)
        try:
            from app.websocket.cli_dual_coo import (
                ceo_issue_fingerprint,
                mark_ceo_issue_decided,
            )

            fp = str(meta.get("ceo_issue_fp") or "")
            if not fp:
                fp = ceo_issue_fingerprint(
                    title=str(proposal.get("title") or ""),
                    origin=str(meta.get("ceo_origin") or ""),
                    task_id=str(meta.get("ceo_task_id") or ""),
                    payload=payload,
                )
            mark_ceo_issue_decided(fp)
        except Exception as e:
            logger.debug("ceo issue suppress: %s", e)

    apply_result: Dict[str, Any] = {}
    if decision == "APPROVE" and db_pool:
        apply_result = await _apply_ceo_payload(
            db_pool, payload, approved_by=approver or "email_ceo"
        )
    elif decision == "REJECT" and db_pool:
        apply_result = await _reject_ceo_payload(
            db_pool, payload, approved_by=approver or "email_ceo"
        )
    elif decision in ("REWRITE", "DELAY", "RETRACT") and db_pool:
        # QUANTUM-CRYSTAL-ARCH — growth content reply verbs
        if payload.get("kind") == "growth_content_review":
            apply_result = {
                "growth": await _apply_growth_content_decision(
                    db_pool,
                    payload,
                    approved_by=approver or "email_ceo",
                    decision=decision,
                    modifier_text=modifier_text,
                )
            }
        else:
            apply_result = await _apply_ceo_payload(
                db_pool,
                payload,
                approved_by=approver or "email_ceo",
                decision_override=decision,
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
    db_pool,
    payload: Dict[str, Any],
    *,
    approved_by: str,
    decision_override: Optional[str] = None,
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

    # QUANTUM-CRYSTAL-ARCH — self-dev APPROVE persists live focus + recallable crystals
    if payload.get("kind") == "six_quotient_self_dev":
        try:
            from app.services.six_quotient_live_context import apply_self_dev_focus

            out["six_quotient_self_dev"] = await apply_self_dev_focus(
                db_pool, payload, approved_by=approved_by
            )
        except Exception as e:
            out["six_quotient_self_dev_error"] = str(e)[:200]

    # QUANTUM-CRYSTAL-ARCH — L4 rule loop close: CEO APPROVE → promote/rollback
    if payload.get("kind") == "ln_rule_lifecycle":
        try:
            from app.services.ln_rule_loop import ceo_apply_ln_rule

            out["ln_rule"] = await ceo_apply_ln_rule(
                db_pool, payload, approved_by=approved_by, decision="APPROVE"
            )
        except Exception as e:
            out["ln_rule_error"] = str(e)[:200]

    # QUANTUM-CRYSTAL-ARCH — LN7 READY candidate: APPROVE → activate_revision
    if payload.get("kind") == "ln7_revision_candidate":
        apply = payload.get("apply") if isinstance(payload.get("apply"), dict) else {}
        readiness = (
            payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
        )
        ready = bool(
            payload.get("ready")
            if "ready" in payload
            else readiness.get("ready")
        )
        action = str(apply.get("action") or "").strip().lower()
        rid = str(
            apply.get("revision_id")
            or payload.get("revision_id")
            or ""
        ).strip()
        if not ready or action != "activate" or not rid:
            out["ln7_revision"] = {
                "ok": False,
                "skipped": True,
                "reason": "not_ready_or_no_activate",
                "ready": ready,
                "action": action,
                "revision_id": rid,
            }
        else:
            try:
                # QUANTUM-CRYSTAL-ARCH — W1: seed shadow_outcome before activate
                from app.services.ln7_flywheel_pipeline import ensure_shadow_for_revision
                from app.services.ln7_revision import activate_revision

                out["ln7_shadow"] = await ensure_shadow_for_revision(db_pool, rid)
                out["ln7_revision"] = await activate_revision(
                    db_pool,
                    rid,
                    promoted_by=approved_by or "ceo",
                    ceo_decision_id=str(
                        apply.get("ceo_decision_id") or payload.get("ceo_decision_id") or ""
                    )
                    or None,
                )
            except Exception as e:
                out["ln7_revision_error"] = str(e)[:200]

    # QUANTUM-CRYSTAL-ARCH — Adaptive Growth content review
    if payload.get("kind") == "growth_content_review":
        try:
            out["growth"] = await _apply_growth_content_decision(
                db_pool,
                payload,
                approved_by=approved_by,
                decision=decision_override or "APPROVE",
            )
        except Exception as e:
            out["growth_error"] = str(e)[:200]

    # QUANTUM-CRYSTAL-ARCH — peer+CEO GREEN policy activate
    if payload.get("kind") == "growth_policy_activate":
        try:
            from app.services.growth.authority_map import activate_policy_green

            key = str(
                payload.get("policy_key")
                or (payload.get("apply") or {}).get("policy_key")
                or ""
            )
            out["growth_policy"] = await activate_policy_green(
                db_pool,
                key,
                peer_pass=bool(payload.get("peer_pass")),
                ceo_approved=True,
            )
        except Exception as e:
            out["growth_policy_error"] = str(e)[:200]

    # QUANTUM-CRYSTAL-ARCH — segment draft → growth_config
    if payload.get("kind") == "growth_segment_propose":
        try:
            from app.services.growth.marketing_content_service import MarketingContentService

            proposal = payload.get("proposal") or {}
            svc = MarketingContentService(db_pool)
            out["growth_segment"] = await svc.set_growth_config(
                "segment_proposal_draft",
                proposal if isinstance(proposal, dict) else {"raw": proposal},
                updated_by=approved_by or "ceo",
            )
        except Exception as e:
            out["growth_segment_error"] = str(e)[:200]

    # QUANTUM-CRYSTAL-ARCH — factory digest APPROVE_ALL (blog IDs only)
    if payload.get("kind") == "growth_factory_digest":
        try:
            from app.services.growth.marketing_content_service import MarketingContentService

            ids = list(
                payload.get("content_ids")
                or (payload.get("apply") or {}).get("content_ids")
                or []
            )
            svc = MarketingContentService(db_pool)
            approved = []
            for cid in ids[:40]:
                try:
                    approved.append(
                        await svc.apply_ceo_decision(
                            int(cid), decision="APPROVE", actor=approved_by or "ceo"
                        )
                    )
                except Exception as ie:
                    approved.append({"id": cid, "error": str(ie)[:120]})
            out["growth_factory_digest"] = {"ok": True, "approved": len(approved), "items": approved}
        except Exception as e:
            out["growth_factory_digest_error"] = str(e)[:200]

    # growth_weekly_digest — ACK/APPROVE clears inbox only (no publish)
    if payload.get("kind") == "growth_weekly_digest":
        out["growth_weekly_digest"] = {"ok": True, "acked": True}

    # QUANTUM-CRYSTAL-ARCH — Phase A+B allowlisted remediations
    if payload.get("kind") in ("ln7_fuel_volume_burst", "trust_reprobe"):
        try:
            from app.services.ceo_remediation_apply import apply_ceo_remediation

            out["remediation"] = await apply_ceo_remediation(
                db_pool, payload, approved_by=approved_by
            )
        except Exception as e:
            out["remediation_error"] = str(e)[:200]
    return out


async def _apply_growth_content_decision(
    db_pool,
    payload: Dict[str, Any],
    *,
    approved_by: str,
    decision: str,
    modifier_text: Optional[str] = None,
) -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    from app.services.growth.marketing_content_service import MarketingContentService

    content_id = int(
        payload.get("content_id")
        or (payload.get("apply") or {}).get("content_id")
        or 0
    )
    if not content_id:
        return {"ok": False, "error": "missing content_id"}

    svc = MarketingContentService(db_pool)
    decision_u = (decision or "APPROVE").strip().upper()
    note = (modifier_text or "").strip()
    scheduled_at = None

    if decision_u == "DELAY":
        # Parse +Nd or ISO from modifier / apply
        raw = note or str((payload.get("apply") or {}).get("delay") or "")
        scheduled_at = _parse_delay_when(raw)
        if not scheduled_at:
            scheduled_at = datetime.now(timezone.utc) + timedelta(days=3)

    result = await svc.apply_ceo_decision(
        content_id,
        decision=decision_u,
        actor=approved_by or "ceo",
        note=note,
        scheduled_at=scheduled_at,
    )
    return {"ok": True, "content": result, "decision": decision_u}


def _parse_delay_when(raw: str):
    """Parse '+3d', '+12h', or ISO datetime. Returns aware UTC datetime or None."""
    from datetime import datetime, timedelta, timezone

    s = (raw or "").strip()
    if not s:
        return None
    m = re.match(r"^\+?(\d+)\s*([dh])$", s, re.IGNORECASE)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
        return datetime.now(timezone.utc) + delta
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def _reject_ceo_payload(
    db_pool, payload: Dict[str, Any], *, approved_by: str
) -> Dict[str, Any]:
    """CEO REJECT side-effects (L4 discard / rollback)."""
    out: Dict[str, Any] = {}
    if payload.get("kind") == "ln_rule_lifecycle":
        try:
            from app.services.ln_rule_loop import ceo_apply_ln_rule

            out["ln_rule"] = await ceo_apply_ln_rule(
                db_pool, payload, approved_by=approved_by, decision="REJECT"
            )
        except Exception as e:
            out["ln_rule_error"] = str(e)[:200]
    if payload.get("kind") == "growth_content_review":
        try:
            out["growth"] = await _apply_growth_content_decision(
                db_pool, payload, approved_by=approved_by, decision="REJECT"
            )
        except Exception as e:
            out["growth_error"] = str(e)[:200]
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

    brief = build_ceo_review_brief(item)
    try:
        from app.websocket.cli_dual_coo import ceo_issue_fingerprint

        issue_fp = str(item.get("issue_fp") or "") or ceo_issue_fingerprint(
            title=title,
            origin=str(item.get("origin") or ""),
            task_id=str(item.get("task_id") or ""),
            payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
        )
    except Exception:
        issue_fp = str(item.get("issue_fp") or "")
    meta = {
        "ceo_inbox": True,
        "ceo_inbox_item_id": item.get("id"),
        "ceo_short_id": short,
        "ceo_payload": item.get("payload") or {},
        "ceo_origin": item.get("origin"),
        "ceo_task_id": item.get("task_id"),
        "ceo_issue_fp": issue_fp,
        "ceo_risk": risk,
        "details": {
            "objective": brief["objective"],
            "reasoning": brief["reasoning"],
            "action_steps": brief["action_steps"],
            "expected_impact": brief["expected_impact"],
            "rollback": brief["rollback"],
            "what_it_should_do": brief.get("what_it_should_do") or [],
            "what_it_should_not_be": brief.get("what_it_should_not_be") or [],
            "bottom_line": brief.get("bottom_line") or "",
            "summary_block": brief.get("summary_block") or "",
        },
    }
    # Lead with English summary; technical refs last
    description = (
        f"{brief['summary_block']}\n"
        f"--- Technical / trace (optional) ---\n"
        f"Raw detail: {detail or '(none)'}\n"
        f"Inbox ID: {item.get('id')}\n"
        f"Origin: {item.get('origin')} · task: {item.get('task_id')}\n"
        f"Reply ACK / APPROVE / REJECT / HOLD to {ApprovalProtocolService_REPLY_TO()}\n"
    )
    try:
        async with db_pool.acquire() as conn:
            inbox_item_id = str(item.get("id") or "")
            if inbox_item_id:
                dup = await conn.fetchrow(
                    """
                    SELECT * FROM strategy_proposals
                    WHERE status = 'pending_approval'
                      AND metadata->>'ceo_inbox_item_id' = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    inbox_item_id,
                )
                if dup:
                    logger.info(
                        "ceo_inbox_notify: pending proposal exists for item %s",
                        inbox_item_id[:24],
                    )
                    return None
            if issue_fp:
                recent = await conn.fetchrow(
                    """
                    SELECT proposal_id, status FROM strategy_proposals
                    WHERE metadata->>'ceo_issue_fp' = $1
                      AND (
                        status IN ('pending_approval', 'proposed')
                        OR (
                          status IN ('approved', 'rejected')
                          AND COALESCE(updated_at, created_at)
                              > NOW() - INTERVAL '7 days'
                        )
                      )
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    issue_fp,
                )
                if recent:
                    logger.info(
                        "ceo_inbox_notify: skip issue_fp %s (status=%s)",
                        issue_fp,
                        recent["status"],
                    )
                    return None
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
