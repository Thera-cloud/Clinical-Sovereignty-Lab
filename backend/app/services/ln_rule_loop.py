"""
L4 — draft → sandbox → promote → rollback for versioned soft-gate rules.

Soft clinical runtime-gate classes only. SI / violence / crisis NEVER match.

Flags:
  ENABLE_LN_RULE_LOOP   — master (default false until soak; set true to bind)
  LN_RULE_LOOP_APPLY    — when true, *active* rules may change soft-gate behavior;
                          sandbox rules always shadow-log only

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

_ALLOWED_ACTIONS = frozenset({"suppress_soft_followup", "noop"})

_PROMOTE_MIN_N = int(os.getenv("LN_RULE_PROMOTE_MIN_N", "5"))
_PROMOTE_FLOOR = float(os.getenv("LN_RULE_PROMOTE_CONFIDENCE", "0.55"))
_ROLLBACK_FLOOR = float(os.getenv("LN_RULE_ROLLBACK_CONFIDENCE", "0.25"))
_SHADOW_PROMOTE_MIN = int(os.getenv("LN_RULE_SHADOW_PROMOTE_MIN", "3"))
# L4 outcome authoring: min negative (FP) samples before draft→sandbox
_FP_DRAFT_MIN_N = int(os.getenv("LN_RULE_FP_DRAFT_MIN_N", "3"))
_FP_DRAFT_MAX_CONF = float(os.getenv("LN_RULE_FP_DRAFT_MAX_CONF", "0.45"))

_DEFAULT_SOFT_CONDITION = {"fired_new": False}
_DEFAULT_SOFT_ACTION = {"type": "suppress_soft_followup"}


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
    gclass = str((condition or {}).get("gate_class") or "")
    if gclass and not is_soft_gate_class(gclass):
        logger.warning("draft_rule refused hard class: %s", gclass)
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
    """Promote sandbox|draft → active; prior active for same key → rolled_back."""
    if not rule_loop_enabled() or not db_pool:
        return False
    try:
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
        return True
    except Exception as e:
        logger.warning("promote_rule: %s", e)
        return False


async def rollback_rule(db_pool: Any, *, rule_key: str, version: int) -> bool:
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
                    VALUES ($1, $2, 'rollback', 'confidence/lifecycle rollback')
                    """,
                    rule_key,
                    version,
                )
            return bool(n)
    except Exception as e:
        logger.warning("rollback_rule: %s", e)
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
        "l4_cycle_complete": False,
        "actions": [],
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
        actions = [str(r["action"]) for r in rows]
        out = {
            "rule_key": rule_key,
            "has_draft": "draft" in actions,
            "has_sandbox_pass": "sandbox_pass" in actions,
            "has_shadow_or_fire": ("shadow_fire" in actions) or ("fire" in actions),
            "has_promote": "promote" in actions,
            "has_rollback": "rollback" in actions,
            "actions": actions,
        }
        out["l4_cycle_complete"] = bool(
            out["has_draft"]
            and out["has_sandbox_pass"]
            and out["has_shadow_or_fire"]
            and out["has_promote"]
        )
        return out
    except Exception as e:
        logger.warning("cycle_evidence: %s", e)
        return empty


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
                ORDER BY version DESC
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
            await rollback_rule(
                db_pool, rule_key=active["rule_key"], version=int(active["version"]),
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
                promote_ok = (
                    shadows >= _SHADOW_PROMOTE_MIN
                    or (n >= _PROMOTE_MIN_N and conf >= _PROMOTE_FLOOR)
                )
                if promote_ok:
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
            await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
            return None
    await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
    return gate_result
