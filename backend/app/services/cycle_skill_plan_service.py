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

# Substitutions that collapse Clinical-AGI skill offers into generic soothing.
_GROUNDING_ATTRACTOR_RE = re.compile(
    r"\b(5-4-3-2-1|five things you see|feet on (the )?(floor|ground)|"
    r"simple grounding practice|sensory grounding)\b",
    re.I,
)

# Per-modality: phrases Nate must NOT use as the main offer when another skill is active.
_FORBIDDEN_BY_MODALITY: Dict[str, str] = {
    "CBT": (
        "Do NOT make 5-4-3-2-1, feet-on-floor, or breath-only grounding the main practice. "
        "If flooded, one 10-second orient is OK, then return to the hot thought / evidence work."
    ),
    "DBT": (
        "Do NOT replace STOP/TIPP/urge-surf/DEAR MAN with a standalone 5-4-3-2-1 grounding lesson. "
        "Teach the named DBT skill in this step."
    ),
    "ACT": (
        "Do NOT replace defusion/values/committed action with sensory grounding as the practice. "
        "Teach the ACT move named below."
    ),
    "grounding": (
        "Stay with orienting / body anchor / 5-4-3-2-1 as written — do not invent CBT thought records."
    ),
    "mindfulness": (
        "Teach observe/label or mindful return as written — do not swap in thought-challenging or TIPP."
    ),
}


def cycle_skill_plans_enabled() -> bool:
    return os.getenv("ENABLE_CYCLE_SKILL_PLANS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _norm_modality(modality: str) -> str:
    m = (modality or "").strip()
    if m.upper() == "CBT":
        return "CBT"
    if m.upper() == "ACT":
        return "ACT"
    if m.upper() == "DBT":
        return "DBT"
    return m.lower() if m else "skills"


def _skill_must_include(step: Dict[str, Any], modality: str) -> str:
    skill = (step.get("skill") or "").strip()
    if skill:
        return skill.replace("_", " ")
    mod = _norm_modality(modality)
    return {
        "CBT": "hot thought / thought check",
        "DBT": "STOP or TIPP or DEAR MAN (as named in practice)",
        "ACT": "defusion or values action",
        "grounding": "5-4-3-2-1 or feet/seat/breath",
        "mindfulness": "mindful observe or mindful return",
    }.get(mod, "the named practice")


_MODALITY_MARKERS: Dict[str, Tuple[str, ...]] = {
    "CBT": (
        "hot thought",
        "automatic thought",
        "thought check",
        "evidence for",
        "writing down",
        "write down",
        "write one",
        "behavioral experiment",
    ),
    "DBT": (
        "stop skill",
        " stop,",
        "take a step back",
        "tipp",
        "urge-surf",
        "urge surf",
        "dear man",
        "opposite action",
        "describe without",
        "facts-only",
        "facts only",
    ),
    "ACT": (
        "defusion",
        "i notice i am having the thought",
        "having the thought that",
        "valued action",
        "one value",
        "committed action",
    ),
    "grounding": (
        "5-4-3-2-1",
        "five things you see",
        "feet on",
        "sit bones",
        "paced breath",
    ),
    "mindfulness": (
        "5-4-3-2-1",
        "observe",
        "like weather",
        "mindful",
        "label",
        "thinking",
    ),
}


def score_skill_offer_fidelity(
    response: str,
    *,
    modality: str,
    skill: str = "",
    practice: str = "",
) -> int:
    """
    Heuristic 0–5 Clinical-AGI score for spoken skill offers.
    5 = on-modality + teachable steps; 1 = wrong modality (grounding attractor).
    """
    text = response or ""
    if not text.strip():
        return 0
    mod = _norm_modality(modality)
    low = text.lower()
    score = 2  # warm baseline
    skill_toks = [
        t
        for t in re.split(r"[\s_/]+", (skill or "").lower())
        if len(t) >= 3 and t not in {"the", "and", "for"}
    ]
    practice_toks = [
        w
        for w in re.findall(r"[a-z0-9\-]{4,}", (practice or "").lower())
        if w
        not in {"then", "with", "that", "this", "from", "your", "have", "into"}
    ][:8]
    markers = _MODALITY_MARKERS.get(mod, ())
    hit_markers = sum(1 for m in markers if m in low)
    hit_skill = any(t in low for t in skill_toks) if skill_toks else hit_markers >= 1
    hit_practice = sum(1 for t in practice_toks if t in low) + hit_markers
    grounding_main = bool(_GROUNDING_ATTRACTOR_RE.search(text))
    teaches = bool(
        re.search(
            r"\b(let'?s try|try this|the practice|step back|write|list 2|"
            r"name one|say or write|role-play|notice 5)\b",
            low,
        )
    )

    if mod in ("CBT", "DBT", "ACT"):
        if grounding_main and hit_markers == 0 and not hit_skill:
            return 1
        if hit_markers >= 1 or hit_skill:
            score = 4 if teaches or hit_practice >= 2 else 3
        if (hit_markers >= 1 or hit_skill) and teaches:
            score = 5 if hit_practice >= 2 or hit_markers >= 2 else 4
        return score

    if mod in ("grounding", "mindfulness"):
        if grounding_main or hit_markers >= 1 or hit_skill:
            score = 4
        if (grounding_main or hit_markers >= 1) and teaches:
            score = 5
        return score

    if hit_skill or hit_markers >= 1:
        return 4
    return score


def build_fidelity_directive(
    *,
    modality: str,
    status: str,
    title: str,
    theme: str,
    practice: str,
    skill: str,
    step_num: int,
    total_steps: int,
) -> str:
    """Clinical-AGI lock: force on-modality teachable offer (not grounding default)."""
    mod = _norm_modality(modality)
    forbid = _FORBIDDEN_BY_MODALITY.get(
        mod,
        "Do not substitute a different modality than the one named here.",
    )
    must = skill or _skill_must_include({"skill": skill}, mod)
    if status == "suggested":
        return (
            f"SKILL FIDELITY LOCK ({mod}) — REQUIRED for this reply:\n"
            f"1) One short empathic join (1–2 sentences MAX). Do NOT open with "
            f"\"Behind the feeling…\" / \"Behind your willingness…\".\n"
            f"2) Offer THIS optional practice only — modality {mod}, skill \"{must}\", "
            f"step focus \"{theme}\" from \"{title}\".\n"
            f"REQUIRED PRACTICE TEXT (teach the steps in the reply; light paraphrase OK, "
            f"same skill required):\n\"{practice}\"\n"
            f"3) If the client is accepting (yes / let's try / I'm in): TEACH the full "
            f"REQUIRED PRACTICE now — do not only empathize or promise to start later.\n"
            f"4) If not yet accepted: ask once if they want to try it.\n"
            f"FORBIDDEN: {forbid}\n"
            f"If you name a practice, it must be {mod} ({must}), not a different school."
        )
    return (
        f"SKILL FIDELITY LOCK ({mod}) — ACTIVE PRACTICE step {step_num}/{total_steps}:\n"
        f"Title: \"{title}\". Focus: {theme}. Skill: {must}.\n"
        f"REQUIRED PRACTICE: \"{practice}\"\n"
        f"If they completed the last step, name the skill they finished, then teach "
        f"the next REQUIRED PRACTICE above (or celebrate plan completion).\n"
        f"Do NOT open with \"Behind the feeling…\". FORBIDDEN: {forbid}"
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


async def _recent_decline_cooldown(db_pool: Any, username: str) -> bool:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchval(
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
        return bool(row)
    except Exception:
        return False


async def ensure_suggested_plan_from_cycles(
    db_pool: Any, user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Pre-turn: create suggested plan from strongest cycle so fidelity context
    exists BEFORE the LLM reply (not only after).
    """
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return None
    username = await _resolve_username(db_pool, user_id)
    existing = await _get_plan_row(db_pool, username)
    if existing:
        return None
    if await _recent_decline_cooldown(db_pool, username):
        return None
    cycles = await fetch_user_cycle_signals(db_pool, username)
    if not cycles:
        return None
    domain = str(cycles[0].get("domain") or "")
    mapping = _DOMAIN_TEMPLATE.get(domain)
    if not mapping:
        return None
    tpl_id, modality, _ = mapping
    tpl = await _load_template(db_pool, tpl_id)
    if not tpl:
        return None
    new_id = await _insert_suggested_plan(
        db_pool,
        user_id=username,
        template=tpl,
        domain=domain,
        modality=modality,
        parent_plan_id=None,
    )
    if not new_id:
        return None
    logger.info(
        "cycle_skill_plan: pre-turn suggested %s modality=%s domain=%s",
        new_id,
        modality,
        domain,
    )
    return {
        "ok": True,
        "action": "suggested",
        "plan_id": new_id,
        "domain": domain,
        "modality": modality,
    }


async def build_cycle_skill_plan_context(db_pool: Any, user_id: str) -> str:
    """Prompt block: cycle signals + Clinical-AGI fidelity-locked skill offer."""
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return ""

    # QUANTUM-CRYSTAL-ARCH: suggest before generation so first turn is on-modality
    await ensure_suggested_plan_from_cycles(db_pool, user_id)

    cycles = await fetch_user_cycle_signals(db_pool, user_id)
    plan = await _get_plan_row(db_pool, user_id)
    parts: List[str] = []

    if cycles:
        top = cycles[0]
        domain = top.get("domain") or "pattern"
        conf = float(top.get("confidence") or 0)
        parts.append(
            f"CYCLE SIGNAL: Recent {domain.replace('_', ' ')} pattern "
            f"(confidence {conf:.2f}). If a SKILL FIDELITY LOCK is present below, "
            f"that lock OVERRIDES any impulse to offer generic grounding or coping tips. "
            f"Never dump a multi-week curriculum."
        )
        if len(cycles) > 1:
            others = ", ".join(
                f"{c.get('domain', '?')}({float(c.get('confidence') or 0):.2f})"
                for c in cycles[1:3]
            )
            parts.append(f"Other recent cycle signals: {others}.")

    if plan:
        step = _step_payload(
            plan.get("step_definitions"), int(plan.get("current_step") or 1)
        )
        practice = step.get("practice") or step.get("theme") or "this week's practice"
        theme = step.get("theme") or ""
        status = str(plan.get("status") or "")
        modality = plan.get("modality") or step.get("modality") or ""
        skill = str(step.get("skill") or "")
        parts.append(
            build_fidelity_directive(
                modality=str(modality),
                status=status,
                title=str(plan.get("title") or "skills practice"),
                theme=str(theme),
                practice=str(practice),
                skill=skill,
                step_num=int(plan.get("current_step") or 1),
                total_steps=int(plan.get("total_steps") or 1),
            )
        )
        if status == "active":
            check = step.get("check_in")
            if check:
                parts.append(f"CHECK-IN PROMPT (use if natural): {check}")
    elif cycles:
        domain = cycles[0].get("domain") or ""
        mapping = _DOMAIN_TEMPLATE.get(str(domain))
        if mapping:
            _, modality, _ = mapping
            parts.append(
                f"No plan row yet (cooldown or template miss). If you offer a skill, "
                f"use one short {modality}-informed practice for "
                f"{str(domain).replace('_', ' ')} — not a generic grounding default "
                f"unless modality is grounding/mindfulness."
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

    # Fallback if pre-turn ensure missed (race / no plan context path)
    if await _recent_decline_cooldown(db_pool, username):
        return {"ok": True, "action": "cooldown"}
    created = await ensure_suggested_plan_from_cycles(db_pool, username)
    if created:
        return created
    return out


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
