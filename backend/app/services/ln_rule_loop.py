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

_DEFAULT_SOFT_CONDITION = {"fired_new": False}
_DEFAULT_SOFT_ACTION = {"type": "suppress_soft_followup"}


def _rule_key_for(gate_class: str) -> str:
    return f"soft_gate.{gate_class}.followup_suppress"


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
    """Active + sandbox (sandbox is shadow-only at apply time)."""
    return await _list_rules(db_pool, statuses=("active", "sandbox"))


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


async def ensure_soft_rule_drafted(db_pool: Any, gate_class: str) -> None:
    """Auto-draft+sandbox a default follow-up suppress rule if none exists."""
    if not rule_loop_enabled() or not db_pool or not is_soft_gate_class(gate_class):
        return
    key = _rule_key_for(gate_class)
    try:
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                """
                SELECT 1 FROM ln_rule_store
                WHERE rule_key = $1
                  AND status IN ('draft', 'sandbox', 'active')
                LIMIT 1
                """,
                key,
            )
        if exists:
            return
        rid = await draft_rule(
            db_pool,
            rule_key=key,
            condition={"gate_class": gate_class, **_DEFAULT_SOFT_CONDITION},
            action=dict(_DEFAULT_SOFT_ACTION),
            created_by="ln_rule_loop",
            notes="auto-draft from soft-gate fire",
        )
        if rid is None:
            return
        ver = await _latest_version(db_pool, key)
        if ver is not None:
            await move_to_sandbox(db_pool, rule_key=key, version=ver)
            logger.info("L4 auto-draft sandbox %s v%s", key, ver)
    except Exception as e:
        logger.warning("ensure_soft_rule_drafted: %s", e)


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
            return
        if sandbox and not active:
            shadows = await _shadow_fire_count(
                db_pool, sandbox["rule_key"], int(sandbox["version"]),
            )
            promote_ok = (
                shadows >= _SHADOW_PROMOTE_MIN
                or (n >= _PROMOTE_MIN_N and conf >= _PROMOTE_FLOOR)
            )
            if promote_ok:
                ok = await promote_rule(
                    db_pool,
                    rule_key=sandbox["rule_key"],
                    version=int(sandbox["version"]),
                )
                if ok:
                    logger.info(
                        "L4 promote %s v%s conf=%.2f n=%d shadows=%d",
                        sandbox["rule_key"], sandbox["version"], conf, n, shadows,
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
            await _audit(
                db_pool,
                rule_key=rule["rule_key"],
                version=int(rule["version"]),
                action="shadow_fire",
                detail=f"class={gate_class} fired_new={fired_new} conf={match_conf:.2f} would={atype}",
            )
            await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
            continue
        await _audit(
            db_pool,
            rule_key=rule["rule_key"],
            version=int(rule["version"]),
            action="fire",
            detail=f"class={gate_class} fired_new={fired_new} conf={match_conf:.2f} action={atype}",
        )
        if atype == "suppress_soft_followup" and not fired_new:
            await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
            return None
    await maybe_lifecycle_from_gate_confidence(db_pool, gate_class)
    return gate_result
