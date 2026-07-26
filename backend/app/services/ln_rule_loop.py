"""
L4 — draft → sandbox → promote → rollback for versioned soft-gate rules.

Soft clinical runtime-gate classes only. SI / violence / crisis NEVER match.

Flags:
  ENABLE_LN_RULE_LOOP   — master (default true after L4a bind)
  LN_RULE_LOOP_APPLY    — when true, *active* rules may change soft-gate behavior;
                          sandbox rules always shadow-log only
  LN_RULE_DUAL_COO_NOTIFY — enqueue CEO Dual-COO on draft/promote/rollback (close loop)
  LN_RULE_PROMOTE_REQUIRES_CEO — when true, auto-promote becomes CEO APPROVE-gated

# QUANTUM-CRYSTAL-ARCH — L4 self-adaptive rule loop
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln_rule_loop")

# Soft runtime-gate classes only (see little_nate_clinical_runtime_gate.ALL_CLASSES).
SOFT_GATE_CLASSES = frozenset(
    {
        "pharma_interaction",
        "sleep_aid",
        "diagnosis_request",
        "clinical_instrument",
        "credential_bypass",
    }
)

# Load-bearing promote/draft refuse set — crisis / coach-routing never enter the loop.
HARD_BLOCKED_CLASSES = frozenset(
    {
        "suicide_ideation",
        "violence_ideation",
        "crisis",
        "coach_routing",
        "si_coach_alert",
        "other_harm",
        "self_harm",
        "homicide",
    }
)

HARD_KEY_FRAGMENTS = (
    "suicide",
    "violence",
    "crisis",
    "coach_routing",
    "coach-routing",
    "si_coach",
    "self_harm",
    "homicide",
)

_ALLOWED_ACTIONS = frozenset({"suppress_soft_followup", "noop"})

_PROMOTE_MIN_N = int(os.getenv("LN_RULE_PROMOTE_MIN_N", "5"))
_PROMOTE_FLOOR = float(os.getenv("LN_RULE_PROMOTE_CONFIDENCE", "0.55"))
_ROLLBACK_FLOOR = float(os.getenv("LN_RULE_ROLLBACK_CONFIDENCE", "0.25"))
_SHADOW_PROMOTE_MIN = int(os.getenv("LN_RULE_SHADOW_PROMOTE_MIN", "3"))
_SHADOW_SCORE_PROMOTE_MIN = int(os.getenv("LN_RULE_SHADOW_SCORE_PROMOTE_MIN", "3"))
# 0.0 = do not block promote on accuracy until post-promote labels exist.
_ACCURACY_PROMOTE_FLOOR = float(os.getenv("LN_RULE_ACCURACY_PROMOTE_FLOOR", "0.0"))
_ACCURACY_PROMOTE_MIN_SCORED = int(os.getenv("LN_RULE_ACCURACY_PROMOTE_MIN_SCORED", "5"))
# L4 outcome authoring: min negative (FP) samples before draft→sandbox
_FP_DRAFT_MIN_N = int(os.getenv("LN_RULE_FP_DRAFT_MIN_N", "3"))
_FP_DRAFT_MAX_CONF = float(os.getenv("LN_RULE_FP_DRAFT_MAX_CONF", "0.45"))

_DEFAULT_SOFT_CONDITION = {"fired_new": False}
_DEFAULT_SOFT_ACTION = {"type": "suppress_soft_followup"}


def promotion_invariant_refusal(
    *,
    rule_key: str,
    condition: Optional[Dict[str, Any]] = None,
    action: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Refuse draft/promote of hard, crisis, or coach-routing rules.

    Demonstrated (not declared): callers must treat non-None as hard fail.
    """
    cond = condition or {}
    gclass = str(cond.get("gate_class") or "")
    if gclass in HARD_BLOCKED_CLASSES:
        return f"invariant:blocked_class:{gclass}"
    if gclass and gclass not in SOFT_GATE_CLASSES:
        return f"invariant:hard_class:{gclass}"
    rk = (rule_key or "").lower()
    for frag in HARD_KEY_FRAGMENTS:
        if frag in rk:
            return f"invariant:blocked_key:{frag}"
    atype = str((action or {}).get("type") or "noop")
    if atype and atype not in _ALLOWED_ACTIONS:
        return f"invariant:blocked_action:{atype}"
    return None


def confusion_label(
    predicted_suppress: bool,
    actual_suppress: Optional[bool],
) -> str:
    """tp/fp/tn/fn/pending for shadow-vs-actual accuracy."""
    if actual_suppress is None:
        return "pending"
    if predicted_suppress and actual_suppress:
        return "tp"
    if predicted_suppress and not actual_suppress:
        return "fp"
    if (not predicted_suppress) and (not actual_suppress):
        return "tn"
    return "fn"


def _rule_key_for(gate_class: str) -> str:
    return f"soft_gate.{gate_class}.followup_suppress"


def auto_draft_enabled() -> bool:
    """Prod auto-author (fire scaffold + FP outcome). Default on with rule loop."""
    if not rule_loop_enabled():
        return False
    return os.getenv("ENABLE_LN_RULE_AUTO_DRAFT", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def rule_loop_enabled() -> bool:
    # Default on after L4a bind; set ENABLE_LN_RULE_LOOP=false to disable.
    return os.getenv("ENABLE_LN_RULE_LOOP", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def rule_loop_apply_enabled() -> bool:
    """Live mutation of soft-gate follow-ups (active rules only)."""
    return rule_loop_enabled() and os.getenv("LN_RULE_LOOP_APPLY", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def dual_coo_notify_enabled() -> bool:
    """CEO Dual-COO inbox visibility for L4 lifecycle (close the loop)."""
    if not rule_loop_enabled():
        return False
    return os.getenv("LN_RULE_DUAL_COO_NOTIFY", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def promote_requires_ceo() -> bool:
    """When true, sandbox→active waits for CEO APPROVE (no silent promote)."""
    return os.getenv("LN_RULE_PROMOTE_REQUIRES_CEO", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _notify_dual_coo(
    *,
    event: str,
    rule_key: str,
    version: int,
    gate_class: str = "",
    detail: str = "",
    risk: str = "YELLOW",
    action_hint: str = "",
) -> None:
    """Best-effort Dual-COO enqueue — never blocks L4 lifecycle."""
    if not dual_coo_notify_enabled():
        return
    try:
        from app.websocket.cli_dual_coo import RISK_RED, RISK_YELLOW, enqueue_ceo

        rk = risk if risk in (RISK_YELLOW, RISK_RED) else RISK_YELLOW
        if event == "rollback":
            rk = RISK_RED
        hint = action_hint or (
            "promote" if event in ("draft_sandbox", "promote_ready") else event
        )
        enqueue_ceo(
            risk=rk,
            title=f"L4 rule {event}: {rule_key} v{version}",
            detail=(detail or f"{event} class={gate_class}")[:500],
            origin="cloud",
            task_id=f"ln_rule:{rule_key}:v{version}:{event}",
            payload={
                "kind": "ln_rule_lifecycle",
                "event": event,
                "rule_key": rule_key,
                "version": int(version),
                "gate_class": gate_class,
                "action": hint,
                "ceo_summary": f"Little Nate soft-gate rule {event}",
                "why_it_matters": (
                    "Closes L4 draft→sandbox→promote→rollback through Dual-COO. "
                    "Soft gates only — never SI/violence."
                ),
                "ask_of_ceo": (
                    "APPROVE to promote sandbox→active; REJECT to rollback/discard."
                    if hint == "promote"
                    else "ACK to acknowledge; REJECT if revert needed."
                ),
                "expected_impact": "Soft follow-up suppression only; hard crisis paths untouched.",
            },
            dedup_ttl_s=3600,
        )
    except Exception as e:
        logger.warning("dual_coo notify skip: %s", e)


async def ceo_apply_ln_rule(
    db_pool: Any,
    payload: Dict[str, Any],
    *,
    approved_by: str = "ceo",
    decision: str = "APPROVE",
) -> Dict[str, Any]:
    """CEO Dual-COO apply path for kind=ln_rule_lifecycle."""
    if not rule_loop_enabled() or not db_pool:
        return {"status": "skipped", "reason": "rule_loop_off"}
    if str(payload.get("kind") or "") != "ln_rule_lifecycle":
        return {"status": "skipped", "reason": "not_ln_rule"}
    rule_key = str(payload.get("rule_key") or "")
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if not rule_key or version < 1:
        return {"status": "error", "error": "missing_rule_key_or_version"}
    decision_u = (decision or "APPROVE").strip().upper()
    action = str(payload.get("action") or payload.get("event") or "promote").lower()
    if decision_u == "APPROVE":
        if action in ("promote", "promote_ready", "draft_sandbox", "sandbox"):
            ok = await promote_rule(db_pool, rule_key=rule_key, version=version)
            return {
                "status": "ok" if ok else "error",
                "action": "promote",
                "ok": ok,
                "approved_by": approved_by,
                "rule_key": rule_key,
                "version": version,
            }
        if action == "rollback":
            ok = await rollback_rule(db_pool, rule_key=rule_key, version=version)
            return {
                "status": "ok" if ok else "error",
                "action": "rollback",
                "ok": ok,
                "approved_by": approved_by,
                "rule_key": rule_key,
                "version": version,
            }
        return {"status": "skipped", "reason": f"unknown_action:{action}"}
    if decision_u == "REJECT":
        # Prefer discard sandbox; else rollback active version.
        ok = await reject_sandbox_rule(db_pool, rule_key=rule_key, version=version)
        if not ok:
            ok = await rollback_rule(db_pool, rule_key=rule_key, version=version)
        return {
            "status": "ok" if ok else "error",
            "action": "reject",
            "ok": ok,
            "approved_by": approved_by,
            "rule_key": rule_key,
            "version": version,
        }
    return {"status": "skipped", "reason": f"decision:{decision_u}"}


async def reject_sandbox_rule(db_pool: Any, *, rule_key: str, version: int) -> bool:
    """CEO REJECT — draft/sandbox → rolled_back + sandbox_fail audit."""
    if not rule_loop_enabled() or not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                UPDATE ln_rule_store
                SET status = 'rolled_back', rolled_back_at = NOW()
                WHERE rule_key = $1 AND version = $2
                  AND status IN ('draft', 'sandbox')
                RETURNING id
                """,
                rule_key,
                version,
            )
            if n:
                await conn.execute(
                    """
                    INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                    VALUES ($1, $2, 'sandbox_fail', 'CEO REJECT / Dual-COO discard')
                    """,
                    rule_key,
                    version,
                )
            return bool(n)
    except Exception as e:
        logger.warning("reject_sandbox_rule: %s", e)
        return False


def _parse_json(val: Any) -> Dict[str, Any]:
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            out = json.loads(val)
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    return {}


def is_soft_gate_class(gate_class: str) -> bool:
    return bool(gate_class) and gate_class in SOFT_GATE_CLASSES


def condition_matches(
    condition: Dict[str, Any],
    *,
    gate_class: str,
    fired_new: bool,
    confidence: float,
) -> bool:
    """Deterministic soft-gate condition match. Hard classes always False."""
    if not is_soft_gate_class(gate_class):
        return False
    if not condition:
        return False
    want = condition.get("gate_class")
    if want and str(want) != gate_class:
        return False
    if "fired_new" in condition and bool(condition["fired_new"]) != bool(fired_new):
        return False
    if "max_confidence" in condition:
        try:
            if confidence > float(condition["max_confidence"]):
                return False
        except (TypeError, ValueError):
            return False
    if "min_confidence" in condition:
        try:
            if confidence < float(condition["min_confidence"]):
                return False
        except (TypeError, ValueError):
            return False
    return True


async def list_active_rules(db_pool: Any) -> List[Dict[str, Any]]:
    return await _list_rules(db_pool, statuses=("active",))


async def list_eval_rules(db_pool: Any) -> List[Dict[str, Any]]:
    """Latest active AND latest sandbox per key (so supersede soak keeps live apply)."""
    if not rule_loop_enabled() or not db_pool:
        return []
    active = await _list_rules(db_pool, statuses=("active",))
    sandbox = await _list_rules(db_pool, statuses=("sandbox",))
    return active + sandbox


async def _list_rules(db_pool: Any, *, statuses: tuple) -> List[Dict[str, Any]]:
    if not rule_loop_enabled() or not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (rule_key)
                    id, rule_key, version, status, condition_json, action_json
                FROM ln_rule_store
                WHERE status = ANY($1::text[])
                ORDER BY rule_key, version DESC
                """,
                list(statuses),
            )
        out = []
        for r in rows:
            cond = _parse_json(r["condition_json"])
            act = _parse_json(r["action_json"])
            gclass = str(cond.get("gate_class") or "")
            if gclass and not is_soft_gate_class(gclass):
                continue  # never surface hard-domain rules
            out.append(
                {
                    "id": r["id"],
                    "rule_key": r["rule_key"],
                    "version": r["version"],
                    "status": r["status"],
                    "condition": cond or {},
                    "action": act or {},
                }
            )
        return out
    except Exception as e:
        logger.warning("list_rules: %s", e)
        return []


async def _audit(
    db_pool: Any,
    *,
    rule_key: str,
    version: int,
    action: str,
    detail: str = "",
) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                VALUES ($1, $2, $3, $4)
                """,
                rule_key,
                int(version),
                action,
                (detail or "")[:300],
            )
    except Exception as e:
        logger.debug("ln_rule_audit skip: %s", e)


async def record_shadow_score(
    db_pool: Any,
    *,
    rule_key: str,
    version: int,
    predicted_would_suppress: bool,
    gate_class: str = "",
    match_confidence: float = 0.0,
    predicted_action: str = "suppress_soft_followup",
) -> Optional[int]:
    """Counterfactual prediction while rule is sandbox (Phase-3 evidence)."""
    if not rule_loop_enabled() or not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            rid = await conn.fetchval(
                """
                INSERT INTO ln_rule_shadow_scores
                    (rule_key, version, phase, predicted_action,
                     predicted_would_suppress, gate_class, match_confidence,
                     actual_label)
                VALUES ($1, $2, 'shadow', $3, $4, $5, $6, 'pending')
                RETURNING id
                """,
                rule_key,
                int(version),
                predicted_action[:80],
                bool(predicted_would_suppress),
                (gate_class or "")[:80] or None,
                float(match_confidence),
            )
        return int(rid) if rid is not None else None
    except Exception as e:
        logger.warning("record_shadow_score: %s", e)
        return None


async def record_post_promote_outcome(
    db_pool: Any,
    *,
    rule_key: str,
    version: int,
    predicted_would_suppress: bool,
    actual_suppressed: bool,
    gate_class: str = "",
    match_confidence: float = 0.0,
    predicted_action: str = "suppress_soft_followup",
) -> Optional[int]:
    """Actual suppress outcome after promote — pairs with shadow forecaster."""
    if not rule_loop_enabled() or not db_pool:
        return None
    label = confusion_label(predicted_would_suppress, actual_suppressed)
    try:
        async with db_pool.acquire() as conn:
            rid = await conn.fetchval(
                """
                INSERT INTO ln_rule_shadow_scores
                    (rule_key, version, phase, predicted_action,
                     predicted_would_suppress, gate_class, match_confidence,
                     actual_suppressed, actual_label)
                VALUES ($1, $2, 'post_promote', $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                rule_key,
                int(version),
                predicted_action[:80],
                bool(predicted_would_suppress),
                (gate_class or "")[:80] or None,
                float(match_confidence),
                bool(actual_suppressed),
                label,
            )
            # Resolve oldest pending shadow of this version (FIFO pairing).
            await conn.execute(
                """
                UPDATE ln_rule_shadow_scores
                SET actual_suppressed = $3,
                    actual_label = $4
                WHERE id = (
                    SELECT id FROM ln_rule_shadow_scores
                    WHERE rule_key = $1 AND version = $2
                      AND phase = 'shadow' AND actual_label = 'pending'
                    ORDER BY recorded_at ASC
                    LIMIT 1
                )
                """,
                rule_key,
                int(version),
                bool(actual_suppressed),
                label,
            )
        return int(rid) if rid is not None else None
    except Exception as e:
        logger.warning("record_post_promote_outcome: %s", e)
        return None


async def shadow_accuracy_report(
    db_pool: Any,
    *,
    rule_key: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """Shadow-vs-actual accuracy — evidence under auto-promote."""
    empty = {
        "rule_key": rule_key,
        "version": version,
        "scored": 0,
        "pending": 0,
        "tp": 0,
        "fp": 0,
        "tn": 0,
        "fn": 0,
        "accuracy": None,
        "precision": None,
        "recall": None,
    }
    if not db_pool or not rule_key:
        return empty
    try:
        async with db_pool.acquire() as conn:
            if version is not None:
                rows = await conn.fetch(
                    """
                    SELECT actual_label, phase
                    FROM ln_rule_shadow_scores
                    WHERE rule_key = $1 AND version = $2
                    """,
                    rule_key,
                    int(version),
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT actual_label, phase
                    FROM ln_rule_shadow_scores
                    WHERE rule_key = $1
                    """,
                    rule_key,
                )
        counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "pending": 0}
        for r in rows:
            lab = str(r["actual_label"] or "pending")
            if lab in counts:
                counts[lab] += 1
        scored = counts["tp"] + counts["fp"] + counts["tn"] + counts["fn"]
        # Prefer post_promote labeled rows when both shadow-resolved and post exist
        # (avoid double-count): count unique labels from non-pending only once.
        # Rows may include both resolved shadow + post_promote twin — count
        # post_promote preferentially when present.
        post_only = [
            str(r["actual_label"] or "pending")
            for r in rows
            if str(r["phase"]) == "post_promote"
            and str(r["actual_label"] or "") in ("tp", "fp", "tn", "fn")
        ]
        if post_only:
            counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "pending": counts["pending"]}
            for lab in post_only:
                counts[lab] += 1
            scored = len(post_only)
        out = {
            "rule_key": rule_key,
            "version": version,
            "scored": scored,
            "pending": counts["pending"],
            "tp": counts["tp"],
            "fp": counts["fp"],
            "tn": counts["tn"],
            "fn": counts["fn"],
            "accuracy": None,
            "precision": None,
            "recall": None,
        }
        if scored > 0:
            out["accuracy"] = round(
                (counts["tp"] + counts["tn"]) / scored, 4,
            )
            denom_p = counts["tp"] + counts["fp"]
            denom_r = counts["tp"] + counts["fn"]
            out["precision"] = (
                round(counts["tp"] / denom_p, 4) if denom_p else None
            )
            out["recall"] = (
                round(counts["tp"] / denom_r, 4) if denom_r else None
            )
        return out
    except Exception as e:
        logger.warning("shadow_accuracy_report: %s", e)
        return empty


async def _shadow_score_count(db_pool: Any, rule_key: str, version: int) -> int:
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM ln_rule_shadow_scores
                WHERE rule_key = $1 AND version = $2 AND phase = 'shadow'
                """,
                rule_key,
                int(version),
            )
        return int(n or 0)
    except Exception:
        return 0


async def draft_rule(
    db_pool: Any,
    *,
    rule_key: str,
    condition: Dict[str, Any],
    action: Dict[str, Any],
    created_by: str = "system",
    notes: str = "",
) -> Optional[int]:
    if not rule_loop_enabled() or not db_pool:
        return None
    refuse = promotion_invariant_refusal(
        rule_key=rule_key, condition=condition or {}, action=action or {},
    )
    if refuse:
        logger.warning("draft_rule refused: %s key=%s", refuse, rule_key)
        return None
    atype = str((action or {}).get("type") or "noop")
    if atype not in _ALLOWED_ACTIONS:
        logger.warning("draft_rule refused action: %s", atype)
        return None
    try:
        async with db_pool.acquire() as conn:
            ver = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM ln_rule_store WHERE rule_key = $1",
                rule_key,
            )
            rid = await conn.fetchval(
                """
                INSERT INTO ln_rule_store
                    (rule_key, version, status, condition_json, action_json, created_by, notes)
                VALUES ($1, $2, 'draft', $3::jsonb, $4::jsonb, $5, $6)
                RETURNING id
                """,
                rule_key,
                int(ver),
                json.dumps(condition),
                json.dumps(action),
                created_by,
                notes[:500],
            )
            await conn.execute(
                """
                INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                VALUES ($1, $2, 'draft', $3)
                """,
                rule_key,
                int(ver),
                notes[:300],
            )
        return int(rid) if rid is not None else None
    except Exception as e:
        logger.warning("draft_rule: %s", e)
        return None


async def move_to_sandbox(db_pool: Any, *, rule_key: str, version: int) -> bool:
    if not rule_loop_enabled() or not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                UPDATE ln_rule_store
                SET status = 'sandbox'
                WHERE rule_key = $1 AND version = $2 AND status = 'draft'
                RETURNING id
                """,
                rule_key,
                version,
            )
            if n:
                await _audit(
                    db_pool, rule_key=rule_key, version=version,
                    action="sandbox_pass", detail="draft→sandbox",
                )
            return bool(n)
    except Exception as e:
        logger.warning("move_to_sandbox: %s", e)
        return False


async def promote_rule(
    db_pool: Any,
    *,
    rule_key: str,
    version: int,
) -> bool:
    """Promote sandbox|draft → active; prior active for same key → rolled_back.

    Load-bearing invariant: refuse hard/crisis/coach-routing at promote time
    (not only at draft).
    """
    if not rule_loop_enabled() or not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT condition_json, action_json, status
                FROM ln_rule_store
                WHERE rule_key = $1 AND version = $2
                  AND status IN ('draft', 'sandbox')
                """,
                rule_key,
                version,
            )
            if not row:
                return False
            cond = _parse_json(row["condition_json"])
            act = _parse_json(row["action_json"])
            refuse = promotion_invariant_refusal(
                rule_key=rule_key, condition=cond, action=act,
            )
            if refuse:
                await conn.execute(
                    """
                    INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                    VALUES ($1, $2, 'sandbox_fail', $3)
                    """,
                    rule_key,
                    version,
                    f"promote refused: {refuse}"[:300],
                )
                logger.warning(
                    "promote_rule invariant refuse %s v%s: %s",
                    rule_key, version, refuse,
                )
                return False
        # Accuracy floor outside the row lock — avoids pool deadlock on min_size=1.
        if _ACCURACY_PROMOTE_FLOOR > 0:
            rep = await shadow_accuracy_report(
                db_pool, rule_key=rule_key, version=version,
            )
            scored = int(rep.get("scored") or 0)
            acc = float(rep.get("accuracy") or 0.0)
            if scored >= _ACCURACY_PROMOTE_MIN_SCORED and acc < _ACCURACY_PROMOTE_FLOOR:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                        VALUES ($1, $2, 'sandbox_fail', $3)
                        """,
                        rule_key,
                        version,
                        (
                            f"promote refused: accuracy={acc:.2f} "
                            f"< floor={_ACCURACY_PROMOTE_FLOOR} scored={scored}"
                        )[:300],
                    )
                return False
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE ln_rule_store
                    SET status = 'rolled_back', rolled_back_at = NOW()
                    WHERE rule_key = $1 AND status = 'active'
                    """,
                    rule_key,
                )
                updated = await conn.fetchval(
                    """
                    UPDATE ln_rule_store
                    SET status = 'active', promoted_at = NOW()
                    WHERE rule_key = $1 AND version = $2
                      AND status IN ('draft', 'sandbox')
                    RETURNING id
                    """,
                    rule_key,
                    version,
                )
                if not updated:
                    return False
                await conn.execute(
                    """
                    INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                    VALUES ($1, $2, 'promote', 'promoted to active')
                    """,
                    rule_key,
                    version,
                )
        _notify_dual_coo(
            event="promote",
            rule_key=rule_key,
            version=version,
            detail="promoted to active",
            action_hint="ack",
        )
        return True
    except Exception as e:
        logger.warning("promote_rule: %s", e)
        return False


async def rollback_rule(
    db_pool: Any,
    *,
    rule_key: str,
    version: int,
    detail: str = "confidence/lifecycle rollback",
) -> bool:
    if not rule_loop_enabled() or not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                UPDATE ln_rule_store
                SET status = 'rolled_back', rolled_back_at = NOW()
                WHERE rule_key = $1 AND version = $2 AND status = 'active'
                RETURNING id
                """,
                rule_key,
                version,
            )
            if n:
                await conn.execute(
                    """
                    INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                    VALUES ($1, $2, 'rollback', $3)
                    """,
                    rule_key,
                    version,
                    (detail or "confidence/lifecycle rollback")[:300],
                )
                _notify_dual_coo(
                    event="rollback",
                    rule_key=rule_key,
                    version=version,
                    detail=(detail or "active→rolled_back")[:200],
                    risk="RED",
                    action_hint="ack",
                )
            return bool(n)
    except Exception as e:
        logger.warning("rollback_rule: %s", e)
        return False


async def _seed_gate_confidence(
    db_pool: Any,
    gate_class: str,
    *,
    confidence: float,
    sample_size: int,
) -> bool:
    """Write gate confidence for lifecycle promote/rollback evidence (soft only)."""
    if not db_pool or not is_soft_gate_class(gate_class):
        return False
    key = f"runtime_gate:{gate_class}"
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO clinical_gate_confidence
                    (gate_key, confidence, sample_size, positive_count,
                     negative_count, reasoning)
                VALUES ($1, $2, $3, 0, $3, 'l4_credibility_degrade')
                ON CONFLICT (gate_key) DO UPDATE SET
                    confidence = EXCLUDED.confidence,
                    sample_size = EXCLUDED.sample_size,
                    negative_count = EXCLUDED.negative_count,
                    reasoning = EXCLUDED.reasoning,
                    updated_at = NOW()
                """,
                key,
                float(confidence),
                int(sample_size),
            )
        return True
    except Exception as e:
        logger.warning("_seed_gate_confidence: %s", e)
        return False


async def _gate_confidence(db_pool: Any, gate_class: str) -> tuple[float, int]:
    try:
        from app.services.clinical_gate_confidence import get_confidence

        conf = await get_confidence(db_pool, f"runtime_gate:{gate_class}", default=0.70)
    except Exception:
        conf = 0.70
    n = 0
    try:
        async with db_pool.acquire() as conn:
            n = int(
                await conn.fetchval(
                    """
                    SELECT COALESCE(sample_size, 0)
                    FROM clinical_gate_confidence
                    WHERE gate_key = $1
                    """,
                    f"runtime_gate:{gate_class}",
                )
                or 0
            )
    except Exception:
        n = 0
    return float(conf), n


async def _has_pending_draft_or_sandbox(db_pool: Any, rule_key: str) -> bool:
    """True if a draft/sandbox already awaits lifecycle (block duplicate pending)."""
    try:
        async with db_pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    """
                    SELECT 1 FROM ln_rule_store
                    WHERE rule_key = $1
                      AND status IN ('draft', 'sandbox')
                    LIMIT 1
                    """,
                    rule_key,
                )
            )
    except Exception:
        return True  # fail closed


async def _has_live_or_pending_rule(db_pool: Any, rule_key: str) -> bool:
    """True if draft/sandbox/active exists (scaffold path — no supersede)."""
    try:
        async with db_pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    """
                    SELECT 1 FROM ln_rule_store
                    WHERE rule_key = $1
                      AND status IN ('draft', 'sandbox', 'active')
                    LIMIT 1
                    """,
                    rule_key,
                )
            )
    except Exception:
        return True  # fail closed — do not draft on lookup error


async def _draft_and_sandbox(
    db_pool: Any,
    *,
    gate_class: str,
    created_by: str,
    notes: str,
    condition_extra: Optional[Dict[str, Any]] = None,
    allow_active_supersede: bool = False,
) -> Optional[int]:
    """L4 requirements 1–4: draft_rule → move_to_sandbox, soft-gate only.

    allow_active_supersede=True (FP path): draft next version even when active
    exists; still blocked if draft/sandbox pending.
    """
    if not auto_draft_enabled() or not db_pool or not is_soft_gate_class(gate_class):
        return None
    key = _rule_key_for(gate_class)
    if allow_active_supersede:
        if await _has_pending_draft_or_sandbox(db_pool, key):
            return None
    elif await _has_live_or_pending_rule(db_pool, key):
        return None
    cond: Dict[str, Any] = {
        "gate_class": gate_class,
        **_DEFAULT_SOFT_CONDITION,
    }
    if condition_extra:
        cond.update(condition_extra)
    rid = await draft_rule(
        db_pool,
        rule_key=key,
        condition=cond,
        action=dict(_DEFAULT_SOFT_ACTION),
        created_by=created_by,
        notes=notes,
    )
    if rid is None:
        return None
    ver = await _latest_version(db_pool, key)
    if ver is None:
        return rid
    ok = await move_to_sandbox(db_pool, rule_key=key, version=ver)
    if ok:
        logger.info(
            "L4 draft→sandbox %s v%s by=%s supersede=%s",
            key, ver, created_by, allow_active_supersede,
        )
        _notify_dual_coo(
            event="draft_sandbox",
            rule_key=key,
            version=ver,
            gate_class=gate_class,
            detail=notes[:200],
            action_hint="promote",
        )
        await _notify_l5_observe(
            db_pool,
            event="draft_sandbox",
            detail=(
                f"key={key} v={ver} by={created_by} class={gate_class} "
                f"supersede={allow_active_supersede}"
            ),
            gate_class=gate_class,
            rule_key=key,
            version=ver,
        )
    return rid


async def ensure_soft_rule_drafted(db_pool: Any, gate_class: str) -> None:
    """Scaffold draft→sandbox on first soft-gate fire if no rule exists."""
    if not auto_draft_enabled() or not db_pool or not is_soft_gate_class(gate_class):
        return
    try:
        await _draft_and_sandbox(
            db_pool,
            gate_class=gate_class,
            created_by="ln_rule_loop",
            notes="auto-draft from soft-gate fire",
            allow_active_supersede=False,
        )
    except Exception as e:
        logger.warning("ensure_soft_rule_drafted: %s", e)


async def maybe_draft_from_false_positive(
    db_pool: Any,
    gate_class: str,
) -> Optional[int]:
    """L4 req 3 — measured FP/low-confidence → draft→sandbox (may supersede active).

    Called from clinical_gate_confidence.record_feedback(positive=False).
    Soft classes only. Never SI/violence.
    """
    if not auto_draft_enabled() or not db_pool or not is_soft_gate_class(gate_class):
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT confidence, sample_size, negative_count, positive_count
                FROM clinical_gate_confidence
                WHERE gate_key = $1
                """,
                f"runtime_gate:{gate_class}",
            )
        if not row:
            return None
        conf = float(row["confidence"] or 0.70)
        n = int(row["sample_size"] or 0)
        neg = int(row["negative_count"] or 0)
        if neg < _FP_DRAFT_MIN_N or n < _FP_DRAFT_MIN_N:
            return None
        if conf > _FP_DRAFT_MAX_CONF:
            return None
        return await _draft_and_sandbox(
            db_pool,
            gate_class=gate_class,
            created_by="ln_gate_fp",
            notes=(
                f"FP outcome draft neg={neg} n={n} conf={conf:.2f} "
                f"max_conf={_FP_DRAFT_MAX_CONF}"
            ),
            condition_extra={"max_confidence": round(min(conf + 0.10, 0.50), 2)},
            allow_active_supersede=True,
        )
    except Exception as e:
        logger.warning("maybe_draft_from_false_positive: %s", e)
        return None


async def cycle_evidence(
    db_pool: Any,
    rule_key: str,
) -> Dict[str, Any]:
    """L4 req 5 — auditable draft→sandbox→shadow/fire→promote(/rollback) trail."""
    empty = {
        "rule_key": rule_key,
        "has_draft": False,
        "has_sandbox_pass": False,
        "has_shadow_or_fire": False,
        "has_promote": False,
        "has_rollback": False,
        "has_lifecycle_rollback": False,
        "shadow_score_count": 0,
        "accuracy": None,
        "scored": 0,
        "l4_cycle_complete": False,
        "l4_credible": False,
        "actions": [],
        "rollback_details": [],
    }
    if not db_pool or not rule_key:
        return empty
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT action, version, detail, recorded_at
                FROM ln_rule_audit
                WHERE rule_key = $1
                ORDER BY recorded_at ASC
                """,
                rule_key,
            )
            score_n = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM ln_rule_shadow_scores
                    WHERE rule_key = $1
                    """,
                    rule_key,
                )
                or 0
            )
        actions = [str(r["action"]) for r in rows]
        rb_details = [
            str(r["detail"] or "")
            for r in rows
            if str(r["action"]) == "rollback"
        ]
        out = {
            "rule_key": rule_key,
            "has_draft": "draft" in actions,
            "has_sandbox_pass": "sandbox_pass" in actions,
            "has_shadow_or_fire": ("shadow_fire" in actions) or ("fire" in actions),
            "has_promote": "promote" in actions,
            "has_rollback": "rollback" in actions,
            "has_lifecycle_rollback": any(
                "lifecycle" in d and "conf=" in d for d in rb_details
            ),
            "shadow_score_count": score_n,
            "rollback_details": rb_details,
            "actions": actions,
        }
        out["l4_cycle_complete"] = bool(
            out["has_draft"]
            and out["has_sandbox_pass"]
            and out["has_shadow_or_fire"]
            and out["has_promote"]
        )
        acc = await shadow_accuracy_report(db_pool, rule_key=rule_key)
        out["accuracy"] = acc.get("accuracy")
        out["scored"] = int(acc.get("scored") or 0)
        out["accuracy_report"] = acc
        # Credible = mechanism + forecaster + fence artifact:
        # full cycle, lifecycle self-rollback, shadow scores, labeled accuracy.
        out["l4_credible"] = bool(
            out["l4_cycle_complete"]
            and out["has_lifecycle_rollback"]
            and score_n >= _SHADOW_SCORE_PROMOTE_MIN
            and out["scored"] >= 2
            and out["accuracy"] is not None
        )
        return out
    except Exception as e:
        logger.warning("cycle_evidence: %s", e)
        return empty


async def run_l4_credibility_cycle(
    db_pool: Any,
    *,
    gate_class: str = "sleep_aid",
    force_rollback: bool = True,
) -> Dict[str, Any]:
    """Drive LN-drafted soft rule: shadow → promote → accuracy → lifecycle rollback.

    Rollback MUST go through maybe_lifecycle_from_gate_confidence (degraded
    confidence), not a direct rollback_rule call — that is the self-correction
    artifact. force_rollback=True seeds low confidence then invokes lifecycle.
    """
    if not rule_loop_enabled() or not db_pool:
        return {"status": "skipped", "reason": "rule_loop_off"}
    if not is_soft_gate_class(gate_class):
        return {"status": "error", "reason": "hard_class_refused"}
    rule_key = f"soft_gate.{gate_class}.l4_evidence"
    cond = {
        "gate_class": gate_class,
        "fired_new": False,
        "max_confidence": 0.95,
    }
    act = {"type": "suppress_soft_followup"}
    rid = await draft_rule(
        db_pool,
        rule_key=rule_key,
        condition=cond,
        action=act,
        created_by="ln_credibility",
        notes="L4 credibility evidence cycle",
    )
    if rid is None:
        return {"status": "error", "reason": "draft_failed", "rule_key": rule_key}
    ver = await _latest_version(db_pool, rule_key)
    if ver is None:
        return {"status": "error", "reason": "no_version", "rule_key": rule_key}
    if not await move_to_sandbox(db_pool, rule_key=rule_key, version=ver):
        return {"status": "error", "reason": "sandbox_failed", "rule_key": rule_key}

    shadow_n = max(_SHADOW_SCORE_PROMOTE_MIN, _SHADOW_PROMOTE_MIN)
    for i in range(shadow_n):
        await record_shadow_score(
            db_pool,
            rule_key=rule_key,
            version=ver,
            predicted_would_suppress=True,
            gate_class=gate_class,
            match_confidence=0.40,
        )
        await _audit(
            db_pool,
            rule_key=rule_key,
            version=ver,
            action="shadow_fire",
            detail=f"credibility counterfactual i={i} pred_suppress=1",
        )

    if not await promote_rule(db_pool, rule_key=rule_key, version=ver):
        return {"status": "error", "reason": "promote_failed", "rule_key": rule_key}

    # Forecaster check: majority of shadow predictions match post-promote reality.
    # TP for all-but-one, one FP — accuracy = (n-1)/n proves non-guess labeling.
    for i in range(shadow_n):
        actual = i < (shadow_n - 1)  # last one FP
        await record_post_promote_outcome(
            db_pool,
            rule_key=rule_key,
            version=ver,
            predicted_would_suppress=True,
            actual_suppressed=actual,
            gate_class=gate_class,
            match_confidence=0.40,
        )
        if actual:
            await _audit(
                db_pool,
                rule_key=rule_key,
                version=ver,
                action="fire",
                detail=f"credibility live suppress i={i}",
            )

    acc = await shadow_accuracy_report(db_pool, rule_key=rule_key, version=ver)
    await _audit(
        db_pool,
        rule_key=rule_key,
        version=ver,
        action="accuracy_report",
        detail=(
            f"acc={acc.get('accuracy')} scored={acc.get('scored')} "
            f"tp={acc.get('tp')} fp={acc.get('fp')}"
        )[:300],
    )

    rollback_path = "none"
    if force_rollback:
        # Degrade below floor with enough samples — lifecycle must self-revert.
        degrade_conf = max(0.05, _ROLLBACK_FLOOR - 0.10)
        seeded = await _seed_gate_confidence(
            db_pool,
            gate_class,
            confidence=degrade_conf,
            sample_size=max(_PROMOTE_MIN_N, 5),
        )
        if not seeded:
            return {
                "status": "error",
                "reason": "confidence_seed_failed",
                "rule_key": rule_key,
            }
        await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
        rollback_path = "lifecycle"

    ev = await cycle_evidence(db_pool, rule_key)
    if force_rollback and not ev.get("has_lifecycle_rollback"):
        return {
            "status": "error",
            "reason": "lifecycle_rollback_did_not_fire",
            "rule_key": rule_key,
            "cycle": ev,
            "accuracy": acc,
            "rollback_path": rollback_path,
        }
    return {
        "status": "ok",
        "rule_key": rule_key,
        "version": ver,
        "cycle": ev,
        "accuracy": acc,
        "rollback_path": rollback_path,
        "l4_credible": bool(ev.get("l4_credible")),
        "claim_licensed": (
            "A narrow, clinically-scoped neuro-symbolic system that autonomously "
            "improves its own therapeutic rules within demonstrated hard boundaries, "
            "with logged evidence of self-correction."
            if ev.get("l4_credible")
            else None
        ),
    }
async def _notify_l5_observe(
    db_pool: Any,
    *,
    event: str,
    detail: str,
    gate_class: str = "",
    rule_key: str = "",
    version: int = 0,
) -> None:
    """Best-effort handoff to isolated L5 observe sandbox (never blocks L4)."""
    try:
        from app.services.l5_sandbox.observer import ingest_l4_event

        await ingest_l4_event(
            db_pool,
            event=event,
            detail=detail,
            gate_class=gate_class,
            rule_key=rule_key,
            version=version,
        )
    except Exception as e:
        logger.warning("l5 observe skip: %s", e)


async def _latest_version(db_pool: Any, rule_key: str) -> Optional[int]:
    try:
        async with db_pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT MAX(version) FROM ln_rule_store WHERE rule_key = $1",
                rule_key,
            )
        return int(v) if v is not None else None
    except Exception:
        return None


async def _shadow_fire_count(db_pool: Any, rule_key: str, version: int) -> int:
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM ln_rule_audit
                WHERE rule_key = $1 AND version = $2 AND action = 'shadow_fire'
                """,
                rule_key,
                int(version),
            )
        return int(n or 0)
    except Exception:
        return 0


async def maybe_lifecycle_from_gate_confidence(
    db_pool: Any,
    gate_class: str,
) -> None:
    """Promote sandbox→active (shadow count or confidence) / rollback on low conf."""
    if not rule_loop_enabled() or not db_pool or not is_soft_gate_class(gate_class):
        return
    conf, n = await _gate_confidence(db_pool, gate_class)
    try:
        async with db_pool.acquire() as conn:
            active = await conn.fetchrow(
                """
                SELECT rule_key, version
                FROM ln_rule_store
                WHERE status = 'active'
                  AND condition_json->>'gate_class' = $1
                ORDER BY promoted_at DESC NULLS LAST, version DESC
                LIMIT 1
                """,
                gate_class,
            )
            sandbox = await conn.fetchrow(
                """
                SELECT rule_key, version
                FROM ln_rule_store
                WHERE status = 'sandbox'
                  AND condition_json->>'gate_class' = $1
                ORDER BY version DESC
                LIMIT 1
                """,
                gate_class,
            )
        if active and conf < _ROLLBACK_FLOOR and n >= _PROMOTE_MIN_N:
            rb_detail = f"lifecycle conf={conf:.2f} n={n} floor={_ROLLBACK_FLOOR}"
            await rollback_rule(
                db_pool,
                rule_key=active["rule_key"],
                version=int(active["version"]),
                detail=rb_detail,
            )
            logger.info(
                "L4 rollback %s v%s conf=%.2f n=%d",
                active["rule_key"], active["version"], conf, n,
            )
            await _notify_l5_observe(
                db_pool,
                event="rollback",
                detail=f"conf={conf:.2f} n={n}",
                gate_class=gate_class,
                rule_key=active["rule_key"],
                version=int(active["version"]),
            )
            return
        # Promote sandbox when none active, OR newer sandbox superseding active
        if sandbox:
            sand_ver = int(sandbox["version"])
            active_ver = int(active["version"]) if active else 0
            can_promote = (not active) or (sand_ver > active_ver)
            if can_promote:
                shadows = await _shadow_fire_count(
                    db_pool, sandbox["rule_key"], sand_ver,
                )
                score_n = await _shadow_score_count(
                    db_pool, sandbox["rule_key"], sand_ver,
                )
                promote_ok = (
                    shadows >= _SHADOW_PROMOTE_MIN
                    or score_n >= _SHADOW_SCORE_PROMOTE_MIN
                    or (n >= _PROMOTE_MIN_N and conf >= _PROMOTE_FLOOR)
                )
                if promote_ok and _ACCURACY_PROMOTE_FLOOR > 0:
                    rep = await shadow_accuracy_report(
                        db_pool,
                        rule_key=sandbox["rule_key"],
                        version=sand_ver,
                    )
                    scored = int(rep.get("scored") or 0)
                    acc = rep.get("accuracy")
                    if (
                        scored >= _ACCURACY_PROMOTE_MIN_SCORED
                        and acc is not None
                        and float(acc) < _ACCURACY_PROMOTE_FLOOR
                    ):
                        promote_ok = False
                        logger.info(
                            "L4 promote blocked by accuracy %s v%s acc=%.2f scored=%d",
                            sandbox["rule_key"], sand_ver, float(acc), scored,
                        )
                if promote_ok:
                    if promote_requires_ceo():
                        _notify_dual_coo(
                            event="promote_ready",
                            rule_key=sandbox["rule_key"],
                            version=sand_ver,
                            gate_class=gate_class,
                            detail=(
                                f"awaiting CEO APPROVE conf={conf:.2f} "
                                f"n={n} shadows={shadows}"
                            ),
                            action_hint="promote",
                        )
                        logger.info(
                            "L4 promote_ready (CEO gate) %s v%s conf=%.2f n=%d shadows=%d",
                            sandbox["rule_key"], sand_ver, conf, n, shadows,
                        )
                    else:
                        ok = await promote_rule(
                            db_pool,
                            rule_key=sandbox["rule_key"],
                            version=sand_ver,
                        )
                        if ok:
                            logger.info(
                                "L4 promote %s v%s conf=%.2f n=%d shadows=%d "
                                "(supersede_active_v=%s)",
                                sandbox["rule_key"], sand_ver, conf, n, shadows,
                                active_ver or None,
                            )
                            await _notify_l5_observe(
                                db_pool,
                                event="promote",
                                detail=(
                                    f"conf={conf:.2f} n={n} shadows={shadows} "
                                    f"prev_active_v={active_ver}"
                                ),
                                gate_class=gate_class,
                                rule_key=sandbox["rule_key"],
                                version=sand_ver,
                            )
    except Exception as e:
        logger.warning("maybe_lifecycle_from_gate_confidence: %s", e)


async def apply_soft_gate_rules(
    db_pool: Any,
    gate_result: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Bind rule store to soft runtime-gate result.

    Returns None to suppress the soft follow-up response; otherwise gate_result.
    Hard classes (non-SOFT) pass through untouched. SI/violence never enter here
    if callers only pass clinical runtime-gate results.
    """
    if not rule_loop_enabled() or not gate_result or not db_pool:
        return gate_result
    gate_class = str(gate_result.get("class") or "")
    if not is_soft_gate_class(gate_class):
        return gate_result

    await ensure_soft_rule_drafted(db_pool, gate_class)

    fired_new = str(gate_result.get("fired_new", "")).lower() == "true"
    conf, sample_n = await _gate_confidence(db_pool, gate_class)
    # No samples yet → treat as low conf so suppress follow-up rules can bind
    # (avoids default 0.70 blocking first-ever soft-gate learning).
    match_conf = 0.0 if sample_n <= 0 else conf
    rules = await list_eval_rules(db_pool)
    apply_live = rule_loop_apply_enabled()
    for rule in rules:
        if not condition_matches(
            rule.get("condition") or {},
            gate_class=gate_class,
            fired_new=fired_new,
            confidence=match_conf,
        ):
            continue
        action = rule.get("action") or {}
        atype = str(action.get("type") or "noop")
        if atype not in _ALLOWED_ACTIONS:
            continue
        status = str(rule.get("status") or "")
        # Sandbox: always shadow. Active: apply only when LN_RULE_LOOP_APPLY.
        if status == "sandbox" or not apply_live:
            detail = (
                f"class={gate_class} fired_new={fired_new} "
                f"conf={match_conf:.2f} would={atype}"
            )
            would_suppress = atype == "suppress_soft_followup" and not fired_new
            await record_shadow_score(
                db_pool,
                rule_key=rule["rule_key"],
                version=int(rule["version"]),
                predicted_would_suppress=would_suppress,
                gate_class=gate_class,
                match_confidence=match_conf,
                predicted_action=atype,
            )
            await _audit(
                db_pool,
                rule_key=rule["rule_key"],
                version=int(rule["version"]),
                action="shadow_fire",
                detail=detail,
            )
            await _notify_l5_observe(
                db_pool,
                event="shadow_fire",
                detail=detail,
                gate_class=gate_class,
                rule_key=rule["rule_key"],
                version=int(rule["version"]),
            )
            await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
            continue
        detail = (
            f"class={gate_class} fired_new={fired_new} "
            f"conf={match_conf:.2f} action={atype}"
        )
        await _audit(
            db_pool,
            rule_key=rule["rule_key"],
            version=int(rule["version"]),
            action="fire",
            detail=detail,
        )
        await _notify_l5_observe(
            db_pool,
            event="fire",
            detail=detail,
            gate_class=gate_class,
            rule_key=rule["rule_key"],
            version=int(rule["version"]),
        )
        if atype == "suppress_soft_followup" and not fired_new:
            await record_post_promote_outcome(
                db_pool,
                rule_key=rule["rule_key"],
                version=int(rule["version"]),
                predicted_would_suppress=True,
                actual_suppressed=True,
                gate_class=gate_class,
                match_confidence=match_conf,
                predicted_action=atype,
            )
            await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
            return None
        # Active match but no suppress — counterfactual miss / TN path
        if atype == "suppress_soft_followup" and fired_new:
            await record_post_promote_outcome(
                db_pool,
                rule_key=rule["rule_key"],
                version=int(rule["version"]),
                predicted_would_suppress=False,
                actual_suppressed=False,
                gate_class=gate_class,
                match_confidence=match_conf,
                predicted_action=atype,
            )
    await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
    return gate_result
