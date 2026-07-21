"""
QUANTUM-CRYSTAL-ARCH: Cycle → short stacked skill plans + check-ins/follow-ups.

Wires CycleDetectionEngine signals into client chat as optional micro-plans
(grounding, mindfulness, CBT/DBT/ACT-informed), with commitment-based follow-ups.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.cycle_skill_plan")

# Template IDs (migration 260)
_TPL_DBT = "a1000001-0001-4000-8000-000000000001"
_TPL_CBT = "a1000001-0001-4000-8000-000000000002"
_TPL_ACT = "a1000001-0001-4000-8000-000000000003"
_TPL_DEAR = "a1000001-0001-4000-8000-000000000004"
_TPL_GROUND = "a1000001-0001-4000-8000-000000000005"

# Domain → (template_id, modality, succession_template_id for stacking)
# Prefer grounding/mindful first when body activation is likely, then stack skills.
_DOMAIN_TEMPLATE: Dict[str, Tuple[str, str, Optional[str]]] = {
    "emotional_state": (
        _TPL_GROUND,  # grounding + mindful
        "grounding",
        _TPL_DBT,  # then DBT distress
    ),
    "coping": (
        _TPL_GROUND,
        "grounding",
        _TPL_CBT,
    ),
    "addiction": (
        _TPL_GROUND,
        "grounding",
        _TPL_ACT,
    ),
    "porn_addiction": (
        _TPL_GROUND,
        "grounding",
        _TPL_ACT,
    ),
    "financial": (
        _TPL_CBT,
        "CBT",
        _TPL_GROUND,  # stabilize after cognitive work
    ),
    "group_dynamics": (
        _TPL_GROUND,
        "grounding",
        _TPL_DEAR,
    ),
    "sexual_desire": (
        _TPL_GROUND,
        "mindfulness",
        _TPL_ACT,
    ),
    "cultural": (
        _TPL_GROUND,
        "mindfulness",
        _TPL_ACT,
    ),
    "legacy": (
        _TPL_GROUND,
        "grounding",
        _TPL_CBT,
    ),
}

# Domains that must never auto-suggest skills (crisis / legal risk)
_SKIP_AUTO_DOMAINS = frozenset({"harm_risk", "criminal_intent", "economic", "code_learning"})

_ACCEPT_RE = re.compile(
    r"\b(yes|yeah|yep|ok|okay|sure|let'?s try|i'?ll (try|practice)|sounds good|"
    r"i want (to )?(try|practice)|start (that|this)|i'?m in)\b",
    re.I,
)
_ADVANCE_RE = re.compile(
    r"\b(i (did|practiced|finished|completed)|did the (stop|tipp|practice|step|"
    r"grounding|5-4-3-2-1|mindful)|"
    r"tried (it|the)|worked on (step|the practice)|check[- ]?in:?)\b",
    re.I,
)
_DECLINE_RE = re.compile(
    r"\b(not now|no thanks|don'?t want|skip (that|this)|no plan|stop (suggesting|offering))\b",
    re.I,
)

_MIN_CONFIDENCE = float(os.getenv("CYCLE_SKILL_MIN_CONFIDENCE", "0.55"))
_CHECKIN_HOURS = int(os.getenv("CYCLE_SKILL_CHECKIN_HOURS", "48"))


def cycle_skill_plans_enabled() -> bool:
    return os.getenv("ENABLE_CYCLE_SKILL_PLANS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _identity_clause() -> str:
    return """
                user_id IN (
                    SELECT x FROM unnest(ARRAY[
                        $1::text,
                        (SELECT username FROM users WHERE hardware_id = $1 LIMIT 1),
                        (SELECT hardware_id FROM users WHERE username = $1 LIMIT 1)
                    ]) AS t(x)
                    WHERE x IS NOT NULL AND x <> ''
                )
    """


async def _resolve_username(db_pool: Any, identity: str) -> str:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username FROM users
                WHERE username = $1 OR hardware_id = $1
                LIMIT 1
                """,
                identity,
            )
        return (row["username"] if row else identity) or identity
    except Exception:
        return identity


async def _has_proactive_consent(db_pool: Any, identity: str) -> bool:
    try:
        from app.services.nate_commitment_service import get_proactive_consent

        c = await get_proactive_consent(db_pool, identity)
        return bool(c.get("proactive_presence_consent"))
    except Exception:
        return False


async def fetch_user_cycle_signals(
    db_pool: Any,
    user_id: str,
    *,
    min_confidence: float = _MIN_CONFIDENCE,
) -> List[Dict[str, Any]]:
    if not db_pool or not user_id:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT domain, detected_period_days AS period_days,
                       amplitude, confidence, detected_at
                FROM cycle_detections
                WHERE {_identity_clause().strip()}
                  AND confidence >= $2
                  AND detected_at > NOW() - INTERVAL '30 days'
                  AND domain <> ALL($3::text[])
                ORDER BY confidence DESC
                LIMIT 5
                """,
                user_id,
                min_confidence,
                list(_SKIP_AUTO_DOMAINS),
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("cycle_skill_plan: fetch cycles failed: %s", e)
        return []


async def _get_plan_row(
    db_pool: Any,
    user_id: str,
    *,
    statuses: Tuple[str, ...] = ("suggested", "active"),
) -> Optional[Dict[str, Any]]:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, title, total_steps, current_step, step_definitions,
                       status, source, cycle_domain, modality, parent_plan_id,
                       next_checkin_at
                FROM nate_therapeutic_plans
                WHERE {_identity_clause().strip()}
                  AND status = ANY($2::text[])
                ORDER BY
                    CASE status WHEN 'active' THEN 0 WHEN 'suggested' THEN 1 ELSE 2 END,
                    started_at DESC
                LIMIT 1
                """,
                user_id,
                list(statuses),
            )
        return dict(row) if row else None
    except Exception as e:
        logger.warning("cycle_skill_plan: get plan failed: %s", e)
        return None


def _step_payload(steps: Any, step_num: int) -> Dict[str, Any]:
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except Exception:
            steps = []
    if not isinstance(steps, list):
        return {}
    for s in steps:
        if isinstance(s, dict) and int(s.get("step_number") or 0) == step_num:
            return s
    if 0 < step_num <= len(steps) and isinstance(steps[step_num - 1], dict):
        return steps[step_num - 1]
    return {}


async def build_cycle_skill_plan_context(db_pool: Any, user_id: str) -> str:
    """Prompt block: cycle signals + suggested/active micro-plan guidance."""
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return ""

    cycles = await fetch_user_cycle_signals(db_pool, user_id)
    plan = await _get_plan_row(db_pool, user_id)
    parts: List[str] = []

    if cycles:
        top = cycles[0]
        domain = top.get("domain") or "pattern"
        conf = float(top.get("confidence") or 0)
        parts.append(
            f"CYCLE SIGNAL: Recent {domain.replace('_', ' ')} pattern "
            f"(confidence {conf:.2f}). Prefer one short practice (grounding, mindful "
            f"noticing, or a CBT/DBT/ACT skill) over generic advice if the client is "
            f"open — body/ground first when activated; never a curriculum dump."
        )
        if len(cycles) > 1:
            others = ", ".join(
                f"{c.get('domain', '?')}({float(c.get('confidence') or 0):.2f})"
                for c in cycles[1:3]
            )
            parts.append(f"Other recent cycle signals: {others}.")

    if plan:
        step = _step_payload(plan.get("step_definitions"), int(plan.get("current_step") or 1))
        practice = step.get("practice") or step.get("theme") or "this week's practice"
        theme = step.get("theme") or ""
        status = plan.get("status")
        modality = plan.get("modality") or step.get("modality") or ""
        if status == "suggested":
            parts.append(
                f"SKILLS PRACTICE SUGGESTION ({modality or 'skills'}, not yet accepted): "
                f"\"{plan.get('title')}\" — step 1 focus: {theme}. "
                f"Offer once, warmly, as optional practice: {practice} "
                f"Ask if they want to try it — do NOT label it as a treatment program or dump a reading list. "
                f"If they decline, drop it. If they accept, treat it as active."
            )
        else:
            parts.append(
                f"ACTIVE SKILLS PRACTICE: Step {plan.get('current_step')} of "
                f"{plan.get('total_steps')} — {plan.get('title')}. "
                f"Focus: {theme}. Practice: {practice} "
                f"Check in on last practice briefly; if they completed it, acknowledge and "
                f"offer the next step only. Keep offers short (2–4 sentences)."
            )
            check = step.get("check_in")
            if check:
                parts.append(f"CHECK-IN PROMPT (use if natural): {check}")
    elif cycles:
        domain = cycles[0].get("domain") or ""
        mapping = _DOMAIN_TEMPLATE.get(str(domain))
        if mapping:
            _, modality, _ = mapping
            parts.append(
                f"No active skills practice yet. You may offer ONE short "
                f"{modality}-informed practice matched to the {domain.replace('_', ' ')} "
                f"pattern — invite collaboration; never prescribe a multi-week syllabus."
            )

    if not parts:
        return ""
    return "CYCLE SKILL PLAN CONTEXT:\n" + "\n".join(parts)


async def _load_template(db_pool: Any, template_id: str) -> Optional[Dict[str, Any]]:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, title, total_steps, step_definitions
                FROM plan_templates WHERE id = $1::uuid
                """,
                template_id,
            )
        return dict(row) if row else None
    except Exception as e:
        logger.warning("cycle_skill_plan: load template failed: %s", e)
        return None


async def _insert_suggested_plan(
    db_pool: Any,
    *,
    user_id: str,
    template: Dict[str, Any],
    domain: str,
    modality: str,
    parent_plan_id: Optional[str] = None,
) -> Optional[str]:
    steps = template.get("step_definitions")
    if isinstance(steps, str):
        steps = json.loads(steps)
    checkin_at = datetime.now(timezone.utc) + timedelta(hours=_CHECKIN_HOURS)
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO nate_therapeutic_plans
                    (user_id, coach_id, template_id, title, total_steps,
                     current_step, step_definitions, status, source,
                     cycle_domain, modality, parent_plan_id, next_checkin_at)
                VALUES ($1, NULL, $2::uuid, $3, $4, 1, $5::jsonb, 'suggested',
                        'cycle_skill', $6, $7, $8::uuid, $9)
                RETURNING id
                """,
                user_id,
                str(template["id"]),
                template["title"],
                int(template["total_steps"]),
                json.dumps(steps),
                domain,
                modality,
                parent_plan_id,
                checkin_at,
            )
        return str(row["id"]) if row else None
    except Exception as e:
        logger.warning("cycle_skill_plan: insert suggested plan failed: %s", e)
        return None


async def _schedule_followup_commitment(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
) -> None:
    step = _step_payload(plan.get("step_definitions"), int(plan.get("current_step") or 1))
    theme = step.get("theme") or plan.get("title") or "skills practice"
    check = step.get("check_in") or f"How did \"{theme}\" go?"
    target = datetime.now(timezone.utc) + timedelta(hours=_CHECKIN_HOURS)
    text = (
        f"Skills practice check-in (step {plan.get('current_step')}/"
        f"{plan.get('total_steps')} — {plan.get('title')}): {check}"
    )
    try:
        async with db_pool.acquire() as conn:
            # Avoid duplicate active cycle-skill commitments for same plan step
            existing = await conn.fetchval(
                """
                SELECT id FROM nate_commitments
                WHERE user_id = $1 AND status = 'active'
                  AND source = 'cycle_skill_plan'
                  AND commitment_text LIKE $2
                LIMIT 1
                """,
                user_id,
                f"%step {plan.get('current_step')}/%",
            )
            if existing:
                return
            await conn.execute(
                """
                INSERT INTO nate_commitments
                    (user_id, commitment_text, commitment_type, target_date,
                     recurrence, sensitivity, source, status)
                VALUES ($1, $2, 'practice_goal', $3, 'once', 'routine',
                        'cycle_skill_plan', 'active')
                """,
                user_id,
                text[:800],
                target,
            )
        # Stamp next_checkin_at on plan
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nate_therapeutic_plans
                SET next_checkin_at = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                str(plan["id"]),
                target,
            )
    except Exception as e:
        logger.warning("cycle_skill_plan: follow-up commitment failed: %s", e)


async def _activate_plan(db_pool: Any, plan_id: str) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nate_therapeutic_plans
                SET status = 'active', updated_at = NOW(),
                    adaptation_log = adaptation_log || $2::jsonb
                WHERE id = $1::uuid AND status = 'suggested'
                """,
                plan_id,
                json.dumps(
                    [
                        {
                            "event": "client_accepted",
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                ),
            )
    except Exception as e:
        logger.warning("cycle_skill_plan: activate failed: %s", e)


async def _decline_plan(db_pool: Any, plan_id: str) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nate_therapeutic_plans
                SET status = 'abandoned', updated_at = NOW(),
                    adaptation_log = adaptation_log || $2::jsonb
                WHERE id = $1::uuid AND status IN ('suggested', 'active')
                """,
                plan_id,
                json.dumps(
                    [
                        {
                            "event": "client_declined",
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                ),
            )
    except Exception as e:
        logger.warning("cycle_skill_plan: decline failed: %s", e)


async def _advance_or_stack(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
) -> None:
    cur = int(plan.get("current_step") or 1)
    total = int(plan.get("total_steps") or 1)
    plan_id = str(plan["id"])
    try:
        if cur < total:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE nate_therapeutic_plans
                    SET current_step = $2,
                        adaptation_log = adaptation_log || $3::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    plan_id,
                    cur + 1,
                    json.dumps(
                        [
                            {
                                "event": "step_advanced_client",
                                "from_step": cur,
                                "to_step": cur + 1,
                                "at": datetime.now(timezone.utc).isoformat(),
                            }
                        ]
                    ),
                )
            plan["current_step"] = cur + 1
            await _schedule_followup_commitment(db_pool, user_id=user_id, plan=plan)
            return

        # Complete + stack next template if mapped
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nate_therapeutic_plans
                SET status = 'completed', completed_at = NOW(),
                    current_step = total_steps, updated_at = NOW(),
                    adaptation_log = adaptation_log || $2::jsonb
                WHERE id = $1::uuid
                """,
                plan_id,
                json.dumps(
                    [
                        {
                            "event": "completed",
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                ),
            )
        domain = plan.get("cycle_domain") or ""
        mapping = _DOMAIN_TEMPLATE.get(str(domain))
        next_tpl_id = mapping[2] if mapping else None
        if next_tpl_id:
            tpl = await _load_template(db_pool, next_tpl_id)
            if tpl:
                modality = mapping[1] if mapping else "skills"
                # Prefer modality from next template title
                title_l = (tpl.get("title") or "").lower()
                if "ground" in title_l or "mindful" in title_l:
                    modality = "grounding"
                elif "cbt" in title_l:
                    modality = "CBT"
                elif "act" in title_l:
                    modality = "ACT"
                elif "dbt" in title_l:
                    modality = "DBT"
                new_id = await _insert_suggested_plan(
                    db_pool,
                    user_id=user_id,
                    template=tpl,
                    domain=str(domain),
                    modality=modality,
                    parent_plan_id=plan_id,
                )
                if new_id:
                    logger.info(
                        "cycle_skill_plan: stacked next plan %s after %s",
                        new_id,
                        plan_id,
                    )
    except Exception as e:
        logger.warning("cycle_skill_plan: advance/stack failed: %s", e)


async def maybe_tick_cycle_skill_plan(
    db_pool: Any,
    *,
    user_id: str,
    user_text: str,
) -> Dict[str, Any]:
    """
    Post-turn: create suggested plan from cycles; accept/decline/advance;
    schedule commitment check-ins when consent allows.
    """
    out: Dict[str, Any] = {"ok": False, "action": "noop"}
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return out

    text = user_text or ""
    username = await _resolve_username(db_pool, user_id)
    plan = await _get_plan_row(db_pool, username)

    if plan and _DECLINE_RE.search(text):
        await _decline_plan(db_pool, str(plan["id"]))
        return {"ok": True, "action": "declined", "plan_id": str(plan["id"])}

    if plan and plan.get("status") == "suggested" and _ACCEPT_RE.search(text):
        await _activate_plan(db_pool, str(plan["id"]))
        plan["status"] = "active"
        if await _has_proactive_consent(db_pool, username):
            await _schedule_followup_commitment(
                db_pool, user_id=username, plan=plan
            )
        return {"ok": True, "action": "activated", "plan_id": str(plan["id"])}

    if plan and plan.get("status") == "active" and _ADVANCE_RE.search(text):
        await _advance_or_stack(db_pool, user_id=username, plan=plan)
        return {"ok": True, "action": "advanced", "plan_id": str(plan["id"])}

    if plan:
        # Due check-in: refresh commitment if next_checkin_at passed
        nca = plan.get("next_checkin_at")
        if nca and await _has_proactive_consent(db_pool, username):
            if getattr(nca, "tzinfo", None) is None:
                nca = nca.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= nca:
                await _schedule_followup_commitment(
                    db_pool, user_id=username, plan=plan
                )
                out = {"ok": True, "action": "checkin_scheduled", "plan_id": str(plan["id"])}
        return out if out.get("action") != "noop" else {"ok": True, "action": "has_plan"}

    # No plan — maybe suggest from strongest cycle (cooldown after decline)
    try:
        async with db_pool.acquire() as conn:
            recent_decline = await conn.fetchval(
                f"""
                SELECT id FROM nate_therapeutic_plans
                WHERE {_identity_clause().strip()}
                  AND source = 'cycle_skill'
                  AND status = 'abandoned'
                  AND updated_at > NOW() - INTERVAL '7 days'
                LIMIT 1
                """,
                username,
            )
        if recent_decline:
            return {"ok": True, "action": "cooldown"}
    except Exception:
        pass

    cycles = await fetch_user_cycle_signals(db_pool, username)
    if not cycles:
        return out
    domain = str(cycles[0].get("domain") or "")
    mapping = _DOMAIN_TEMPLATE.get(domain)
    if not mapping:
        return out
    tpl_id, modality, _ = mapping
    tpl = await _load_template(db_pool, tpl_id)
    if not tpl:
        return out
    new_id = await _insert_suggested_plan(
        db_pool,
        user_id=username,
        template=tpl,
        domain=domain,
        modality=modality,
        parent_plan_id=None,
    )
    if not new_id:
        return out
    return {
        "ok": True,
        "action": "suggested",
        "plan_id": new_id,
        "domain": domain,
        "modality": modality,
    }


def schedule_cycle_skill_plan_tick(
    db_pool: Any,
    *,
    user_id: str,
    user_text: str,
) -> None:
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return
    try:
        import asyncio

        asyncio.create_task(
            maybe_tick_cycle_skill_plan(
                db_pool, user_id=user_id, user_text=user_text or ""
            )
        )
    except Exception:
        pass
