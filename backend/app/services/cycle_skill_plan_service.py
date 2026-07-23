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

# QUANTUM-CRYSTAL-ARCH: practice-intent accept only (no bare ok/sure/alright/why not)
_ACCEPT_RE = re.compile(
    r"\b("
    r"let'?s try(?:\s+(it|that|this|the (practice|skill|step|exercise)))?(?:\s*[.!]|\s*$)|"
    r"let'?s do (it|that|this)|"
    r"let'?s practice|"
    r"i'?ll (try|do) (it|that|this)|"
    r"i'?ll practice|"
    r"(?:yes|yeah|yep|yup|ok|okay|alright|all right|sure)[,!]?\s+"
    r"(?:let'?s|i'?ll|i want|sounds good|go ahead|try (it|that)|practice|do (it|that)|"
    r"i'?m (?:in|willing))|"
    r"i want (to )?(try|practice)|"
    r"i'?m willing|"
    r"count me in|"
    r"i'?m in[,!]?\s*(?:for (that|this|it)|let'?s|to try)|"
    r"go ahead[,!]?\s*(?:and )?(?:let'?s|i'?ll|try|with (that|this|it))|"
    r"start (that|this) (practice|step|skill|plan)|"
    r"sure[,!]?\s+(let'?s|i'?ll|sounds|ok|okay)|"
    r"i'?m sure (i want|let'?s|i'?ll)"
    r")\b",
    re.I,
)
_ACCEPT_SHORT_RE = re.compile(
    r"^(yes|yeah|yep|yup|go ahead|i'?m in|count me in|i'?m willing)[.!]?$",
    re.I,
)
_ACCEPT_BLOCK_RE = re.compile(
    r"\b(not\s+sure|unsure|don'?t know why|why (would|are|did) you|"
    r"glitch(?:ing)?|buggy|bug\b|broken|not working|big nate|"
    r"i'?m in a (bad|dark|rough|hard)|it'?s okay i'?m)\b",
    re.I,
)
# QUANTUM-CRYSTAL-ARCH: advance only on practice evidence (not "I tried to call mom")
_ADVANCE_RE = re.compile(
    r"\b("
    r"i (did|practiced|finished|completed) (the )?(stop|tipp|practice|step|"
    r"grounding|5-4-3-2-1|mindful|dear|thought|skill)|"
    r"i practiced (today|it|the)|"
    r"did the (stop|tipp|practice|step|grounding|5-4-3-2-1|mindful|skill)|"
    r"tried (it|the (practice|step|grounding|exercise|skill))|"
    r"worked on (step|the practice)|"
    r"(the )?(practice|step|grounding|exercise|skill) (helped|worked)|"
    r"that (practice|step|exercise|skill) (helped|worked)|"
    r"i used (the|that) (skill|practice|stop|tipp|grounding)"
    r")\b"
    r"|things\s+seen\s*:"
    r"|things\s+felt\s*:"
    r"|things\s+heard\s*:"
    r"|things\s+(?:smelt|smelled)\s*:"
    r"|things?\s+tasted\s*:"
    r"|\b5\s*[-–]?\s*4\s*[-–]?\s*3\s*[-–]?\s*2\s*[-–]?\s*1\b",
    re.I,
)
_DECLINE_RE = re.compile(
    r"\b(not now|no thanks|don'?t want|skip (that|this)|no plan|stop (suggesting|offering)|"
    r"maybe later|not interested|stop (that|this|pushing))\b|"
    r"^(no|nah)[.!]?\s*$|"
    r"\b(no|nah)[,!]?\s+(thanks|thank you|not now|i don'?t|i do not)\b",
    re.I,
)
# Skip forced skill teach when client is on imagery/tech meta, not practice
_SKILL_META_SKIP_RE = re.compile(
    r"\b(glitch(?:ing)?|buggy|bug\b|broken|not working|big nate|"
    r"picture of me|this picture|image (looks|seems|is)|looks? (like )?a female|"
    r"why (would|are|did) you (ask|say)|i'?m not sure why)\b",
    re.I,
)


def _client_accepts_plan(text: str) -> bool:
    """True only for clear practice opt-in — never soft ack or 'I'm not sure…'."""
    t = (text or "").strip()
    if not t or _ACCEPT_BLOCK_RE.search(t):
        return False
    if _ACCEPT_SHORT_RE.match(t):
        return True
    return bool(_ACCEPT_RE.search(t))


def _client_advances_plan(text: str) -> bool:
    return bool(_ADVANCE_RE.search(text or ""))

_MIN_CONFIDENCE = float(os.getenv("CYCLE_SKILL_MIN_CONFIDENCE", "0.55"))
_CHECKIN_HOURS = int(os.getenv("CYCLE_SKILL_CHECKIN_HOURS", "48"))
# QUANTUM-CRYSTAL-ARCH: no same-turn curriculum stack after completion
_STACK_COOLDOWN_HOURS = int(os.getenv("CYCLE_SKILL_STACK_COOLDOWN_HOURS", "48"))
_EMAILABLE_EVENTS = frozenset(
    {"suggested", "activated", "advanced", "checkin_due", "completed"}
)
# Coaches also see declines (client opted out of an offered practice).
_COACH_EMAILABLE_EVENTS = _EMAILABLE_EVENTS | {"declined"}


def _therapeutic_plans_flag_on() -> bool:
    return os.getenv("ENABLE_THERAPEUTIC_PLANS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def cycle_skill_emails_enabled() -> bool:
    """Client progress emails (default on when skill or coach treatment plans enabled)."""
    raw = os.getenv("CYCLE_SKILL_EMAILS", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return cycle_skill_plans_enabled() or _therapeutic_plans_flag_on()


def cycle_skill_coach_emails_enabled() -> bool:
    """Coach notifications for client skill/treatment plan progress."""
    raw = os.getenv("CYCLE_SKILL_COACH_EMAILS", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return cycle_skill_plans_enabled() or _therapeutic_plans_flag_on()

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
        'called "stop"',
        "called stop",
        '"stop"',
        " stop ",
        "stopping",
        "take a step back",
        "taking a step",
        "tipp",
        "urge-surf",
        "urge surf",
        "dear man",
        "opposite action",
        "describe without",
        "facts-only",
        "facts only",
        "facts-only sentence",
        "express (feeling)",
        "clear ask",
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
            r"\b(let'?s (try|do)|try this|the practice|step back|write|list 2|"
            r"name one|say or write|role-play|notice 5|catch one|optional .+ practice)\b",
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
        # QUANTUM-CRYSTAL-ARCH: suggested = optional one-liner; never script without accept
        return (
            f"SKILL FIDELITY LOCK ({mod}) — OPTIONAL OFFER (not yet accepted):\n"
            f"1) Stay with the client's stated need/topic first. Reflect and respond to "
            f"WHAT THEY SAID — do not conjecture a skill they did not ask for.\n"
            f"2) Do NOT teach, script, or walk through a practice this turn unless they "
            f"clearly ask for a skill/tool OR clearly accept "
            f"(yes let's try / I'll practice / sure, let's). Soft ok/alright is NOT accept.\n"
            f"3) Only if they ask for help coping OR the topic clearly invites a tool: "
            f"offer ONE short optional {mod} line (skill \"{must}\", \"{theme}\" / \"{title}\") "
            f"— max one sentence, as a question, not a lesson:\n"
            f"\"{practice}\"\n"
            f"4) Never re-pitch every turn. Prefer connection over curriculum.\n"
            f"FORBIDDEN: {forbid}\n"
            f"If you name a practice, it must be {mod} ({must}), not a different school."
        )
    return (
        f"SKILL FIDELITY LOCK ({mod}) — ACTIVE PRACTICE step {step_num}/{total_steps}:\n"
        f"Title: \"{title}\". Focus: {theme}. Skill: {must}.\n"
        f"AGREED PRACTICE (only when they engage it): \"{practice}\"\n"
        f"Default: answer their current need. Teach/check the AGREED PRACTICE only when "
        f"they bring up the skill, report practice, or ask for the next step — "
        f"never hijack unrelated turns with a technique dump.\n"
        f"If they completed the last step, briefly acknowledge, then offer the next "
        f"practice only if they want to continue (or celebrate completion).\n"
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
    sources: Optional[Tuple[str, ...]] = ("cycle_skill",),
) -> Optional[Dict[str, Any]]:
    """Fetch plan row. Default sources=cycle_skill so coach plans never suppress skills."""
    try:
        async with db_pool.acquire() as conn:
            if sources is None:
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
            else:
                row = await conn.fetchrow(
                    f"""
                    SELECT id, title, total_steps, current_step, step_definitions,
                           status, source, cycle_domain, modality, parent_plan_id,
                           next_checkin_at
                    FROM nate_therapeutic_plans
                    WHERE {_identity_clause().strip()}
                      AND status = ANY($2::text[])
                      AND source = ANY($3::text[])
                    ORDER BY
                        CASE status WHEN 'active' THEN 0 WHEN 'suggested' THEN 1 ELSE 2 END,
                        started_at DESC
                    LIMIT 1
                    """,
                    user_id,
                    list(statuses),
                    list(sources),
                )
        return dict(row) if row else None
    except Exception as e:
        logger.warning("cycle_skill_plan: get plan failed: %s", e)
        return None


def _checkin_due(plan: Dict[str, Any]) -> bool:
    nca = plan.get("next_checkin_at")
    if not nca:
        return False
    if getattr(nca, "tzinfo", None) is None:
        nca = nca.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= nca


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


async def _recent_completion_cooldown(db_pool: Any, username: str) -> bool:
    """True while inside post-complete stack window (blocks cycle re-suggest)."""
    hours = max(1, min(int(_STACK_COOLDOWN_HOURS), 336))
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchval(
                f"""
                SELECT id FROM nate_therapeutic_plans
                WHERE {_identity_clause().strip()}
                  AND source = 'cycle_skill'
                  AND status = 'completed'
                  AND COALESCE(completed_at, updated_at)
                      > NOW() - INTERVAL '{hours} hours'
                LIMIT 1
                """,
                username,
            )
        return bool(row)
    except Exception:
        return False


def _pending_stack_from_log(adaptation_log: Any) -> Optional[Dict[str, Any]]:
    """Latest pending_stack event from adaptation_log JSON list."""
    if not adaptation_log:
        return None
    events = adaptation_log
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except Exception:
            return None
    if not isinstance(events, list):
        return None
    for ev in reversed(events):
        if isinstance(ev, dict) and ev.get("event") == "pending_stack":
            return ev
    return None


async def _maybe_release_pending_stack(
    db_pool: Any, username: str
) -> Optional[Dict[str, Any]]:
    """
    After STACK_COOLDOWN, offer the succession template once.
    Same-turn stacking after completion is forbidden (curriculum conveyor).
    """
    if not db_pool or not username:
        return None
    if await _get_plan_row(db_pool, username):
        return None
    if await _recent_decline_cooldown(db_pool, username):
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, adaptation_log, cycle_domain, modality, completed_at, updated_at
                FROM nate_therapeutic_plans
                WHERE {_identity_clause().strip()}
                  AND source = 'cycle_skill'
                  AND status = 'completed'
                ORDER BY COALESCE(completed_at, updated_at) DESC
                LIMIT 1
                """,
                username,
            )
        if not row:
            return None
        pending = _pending_stack_from_log(row.get("adaptation_log"))
        if not pending:
            return None
        offer_after = pending.get("offer_after")
        if offer_after:
            try:
                oa = datetime.fromisoformat(str(offer_after).replace("Z", "+00:00"))
                if oa.tzinfo is None:
                    oa = oa.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) < oa:
                    return None
            except Exception:
                return None
        else:
            # Fallback: honor stack cooldown from completed_at
            done = row.get("completed_at") or row.get("updated_at")
            if done:
                if getattr(done, "tzinfo", None) is None:
                    done = done.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - done).total_seconds() / 3600.0
                if age_h < _STACK_COOLDOWN_HOURS:
                    return None
        tpl_id = pending.get("template_id")
        if not tpl_id:
            return None
        tpl = await _load_template(db_pool, str(tpl_id))
        if not tpl:
            return None
        domain = str(pending.get("domain") or row.get("cycle_domain") or "")
        modality = str(pending.get("modality") or row.get("modality") or "skills")
        parent_id = str(pending.get("parent_plan_id") or row["id"])
        new_id = await _insert_suggested_plan(
            db_pool,
            user_id=username,
            template=tpl,
            domain=domain,
            modality=modality,
            parent_plan_id=parent_id,
        )
        if not new_id:
            return None
        # Clear pending_stack so we don't re-offer
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE nate_therapeutic_plans
                    SET adaptation_log = adaptation_log || $2::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    str(row["id"]),
                    json.dumps(
                        [
                            {
                                "event": "pending_stack_released",
                                "new_plan_id": new_id,
                                "at": datetime.now(timezone.utc).isoformat(),
                            }
                        ]
                    ),
                )
        except Exception as e:
            logger.warning("cycle_skill_plan: clear pending_stack failed: %s", e)
        stacked = await _get_plan_row(db_pool, username)
        if stacked:
            await _log_skill_learning(
                db_pool,
                user_id=username,
                plan=stacked,
                event="suggested",
                detail=f"stacked_after_cooldown={parent_id}",
            )
        logger.info(
            "cycle_skill_plan: released pending stack %s after %s",
            new_id,
            parent_id,
        )
        return {"ok": True, "action": "stacked_after_cooldown", "plan_id": new_id}
    except Exception as e:
        logger.warning("cycle_skill_plan: pending stack release failed: %s", e)
        return None


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
    # QUANTUM-CRYSTAL-ARCH: after complete, wait stack cooldown (no conveyor)
    released = await _maybe_release_pending_stack(db_pool, username)
    if released:
        return released
    if await _recent_completion_cooldown(db_pool, username):
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
    plan = await _get_plan_row(db_pool, username)
    if plan:
        await _log_skill_learning(
            db_pool,
            user_id=username,
            plan=plan,
            event="suggested",
            detail=f"domain={domain}",
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
            f"CYCLE SIGNAL (background only): Recent {domain.replace('_', ' ')} pattern "
            f"(confidence {conf:.2f}). Use for context — do NOT lead with a technique. "
            f"If a SKILL FIDELITY LOCK is present, still answer the client's need first; "
            f"never dump grounding/coping tips or a multi-week curriculum unprompted."
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
                if _checkin_due(plan):
                    parts.append(
                        "CHECK-IN AVAILABLE (only if they mention the practice, ask "
                        "how they're doing with it, or clearly want structure — "
                        f"otherwise stay on their topic): {check}"
                    )
                else:
                    parts.append(
                        f"CHECK-IN PROMPT (only if natural to their topic): {check}"
                    )
            parts.append(
                "If the client already completed this step (e.g. listed things "
                "seen/felt/heard/smelled/tasted, or said they practiced), "
                "ACKNOWLEDGE completion and move on — do NOT re-teach the same "
                "5-4-3-2-1 / practice. If they report a glitch, bug, wrong image, "
                "or ask about Big Nate / system issues, answer that meta concern "
                "directly and do NOT append a skills practice block."
            )
    elif cycles:
        domain = cycles[0].get("domain") or ""
        mapping = _DOMAIN_TEMPLATE.get(str(domain))
        if mapping:
            _, modality, _ = mapping
            parts.append(
                f"No plan row yet. Do not invent a practice. Only if they ask for a "
                f"skill/tool: one short {modality}-informed line for "
                f"{str(domain).replace('_', ' ')} — not generic grounding unless "
                f"modality is grounding/mindfulness."
            )

    if not parts:
        return ""
    return "CYCLE SKILL PLAN CONTEXT:\n" + "\n".join(parts)


async def build_family_skill_plan_context(db_pool: Any, family_profiles: list) -> str:
    """QUANTUM-CRYSTAL-ARCH: per-member skill-plan blocks for Family Sanctuary."""
    parts: List[str] = []
    for fp in family_profiles or []:
        hw = (fp or {}).get("hardware_id") or ""
        if not hw:
            continue
        sk = await build_cycle_skill_plan_context(db_pool, hw)
        if sk:
            parts.append(f"[{(fp or {}).get('name', 'Member')}]\n{sk}")
    return "\n\n".join(parts)


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


async def _stamp_next_checkin(db_pool: Any, plan_id: str, target: datetime) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nate_therapeutic_plans
                SET next_checkin_at = $2, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                plan_id,
                target,
            )
    except Exception as e:
        logger.warning("cycle_skill_plan: stamp next_checkin failed: %s", e)


async def _schedule_followup_commitment(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
) -> None:
    """Always stamp next_checkin_at; write nate_commitments only with proactive consent."""
    step = _step_payload(plan.get("step_definitions"), int(plan.get("current_step") or 1))
    theme = step.get("theme") or plan.get("title") or "skills practice"
    check = step.get("check_in") or f"How did \"{theme}\" go?"
    target = datetime.now(timezone.utc) + timedelta(hours=_CHECKIN_HOURS)
    text = (
        f"Skills practice check-in (step {plan.get('current_step')}/"
        f"{plan.get('total_steps')} — {plan.get('title')}): {check}"
    )
    plan_id = str(plan["id"])
    await _stamp_next_checkin(db_pool, plan_id, target)
    plan["next_checkin_at"] = target
    if not await _has_proactive_consent(db_pool, user_id):
        return
    try:
        async with db_pool.acquire() as conn:
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
    except Exception as e:
        logger.warning("cycle_skill_plan: follow-up commitment failed: %s", e)


def build_skill_plan_email_copy(
    *,
    event: str,
    name: str,
    plan: Dict[str, Any],
) -> Tuple[str, str]:
    """Subject + HTML body for client plan/progress emails."""
    step = _step_payload(
        plan.get("step_definitions"), int(plan.get("current_step") or 1)
    )
    title = str(plan.get("title") or "skills practice")
    modality = str(plan.get("modality") or step.get("modality") or "skills")
    theme = str(step.get("theme") or "")
    practice = str(step.get("practice") or theme or "your practice")
    cur = int(plan.get("current_step") or 1)
    total = int(plan.get("total_steps") or 1)
    who = (name or "friend").strip() or "friend"
    app_url = os.getenv("APP_URL", "https://app.sovereignsanctuary.net").rstrip("/")

    headlines = {
        "suggested": f"{who}, Nate has a short skills practice for you",
        "activated": f"{who}, you're starting: {title}",
        "advanced": f"{who}, progress on {title} — step {cur} of {total}",
        "checkin_due": f"{who}, gentle check-in on your skills practice",
        "completed": f"{who}, you completed {title}",
    }
    bodies = {
        "suggested": (
            f"Based on a pattern Nate noticed, there's an optional "
            f"<strong>{modality}</strong> practice: <em>{title}</em>. "
            f"This week's focus: {theme or practice}. "
            f"Open the app and say yes if you want to try it — no pressure."
        ),
        "activated": (
            f"You're on step {cur} of {total} for <em>{title}</em> ({modality}). "
            f"Practice: {practice} "
            f"When you've tried it, tell Nate in chat — he'll track your progress."
        ),
        "advanced": (
            f"Nice work. You're now on step {cur} of {total} for <em>{title}</em>. "
            f"Next focus: {theme or practice}. "
            f"Keep it small — one practice is enough."
        ),
        "checkin_due": (
            f"How did <em>{title}</em> go? "
            f"{step.get('check_in') or 'What did you notice when you practiced?'} "
            f"Reply in the Sanctuary app when you have a moment."
        ),
        "completed": (
            f"You finished <em>{title}</em>. That matters. "
            f"Nate may offer a short stacked follow-up practice next — "
            f"only if it still fits. Celebrate this step."
        ),
    }
    subject = headlines.get(event, f"{who}, update on your skills practice")
    body = bodies.get(event, f"Update on <em>{title}</em> (step {cur}/{total}).")
    html = f"""<!DOCTYPE html>
<html><body style="font-family:Georgia,serif;background:#050505;color:#F5F5F5;padding:32px;">
<div style="max-width:600px;margin:auto;background:#111;border:1px solid #1A1A1A;padding:32px;border-radius:4px;">
  <div style="color:#C9A962;letter-spacing:3px;font-size:14px;margin-bottom:24px;">SANCTUARY</div>
  <h1 style="font-weight:300;font-size:24px;color:#F5F5F5;">{subject}</h1>
  <p style="color:#9A9A9A;line-height:1.8;">{body}</p>
  <p style="margin-top:28px;">
    <a href="{app_url}" style="display:inline-block;background:#C9A962;color:#050505;text-decoration:none;padding:12px 28px;font-size:13px;letter-spacing:1px;">Open Sanctuary</a>
  </p>
  <p style="color:#5A5A5A;font-size:12px;margin-top:32px;">Little Nate · skills practice updates · Sovereign Sanctuary</p>
</div></body></html>"""
    return subject, html


async def _resolve_client_email(
    db_pool: Any, user_id: str
) -> Tuple[Optional[str], str]:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username, profile_data
                FROM users
                WHERE username = $1 OR hardware_id = $1
                LIMIT 1
                """,
                user_id,
            )
        if not row:
            return None, ""
        pd = row.get("profile_data") or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        if not isinstance(pd, dict):
            pd = {}
        if pd.get("email_opt_out") is True:
            return None, ""
        preferred = str(pd.get("preferred_contact") or "email").strip().lower()
        if preferred in ("sms", "none", "off"):
            return None, ""
        email = (pd.get("email") or "").strip()
        name = (pd.get("name") or row.get("username") or "").strip()
        return (email or None), name
    except Exception as e:
        logger.warning("cycle_skill_plan: resolve email failed: %s", e)
        return None, ""


async def _recently_emailed(
    db_pool: Any,
    plan_id: str,
    event: str,
    *,
    hours: int = 12,
    marker_prefix: str = "email_sent",
) -> bool:
    if not plan_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT adaptation_log FROM nate_therapeutic_plans
                WHERE id = $1::uuid
                """,
                plan_id,
            )
        if not row:
            return False
        log = row.get("adaptation_log") or []
        if isinstance(log, str):
            try:
                log = json.loads(log)
            except Exception:
                log = []
        if not isinstance(log, list):
            return False
        marker = f"{marker_prefix}:{event}"
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        for entry in reversed(log[-40:]):
            if not isinstance(entry, dict):
                continue
            if entry.get("event") != marker:
                continue
            at_raw = entry.get("at") or ""
            try:
                at = datetime.fromisoformat(str(at_raw).replace("Z", "+00:00"))
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                if at >= cutoff:
                    return True
            except Exception:
                return True
        return False
    except Exception:
        return False


async def _stamp_email_marker(
    db_pool: Any, plan_id: str, marker: str
) -> None:
    if not plan_id:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nate_therapeutic_plans
                SET adaptation_log = adaptation_log || $2::jsonb,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                plan_id,
                json.dumps(
                    [
                        {
                            "event": marker,
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                ),
            )
    except Exception:
        pass


async def _resolve_assigned_coach_username(
    db_pool: Any, client_user_id: str
) -> Optional[str]:
    """Resolve coach username from client profile (assigned_coach / coach_id)."""
    if not db_pool or not client_user_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username, profile_data
                FROM users
                WHERE username = $1 OR hardware_id = $1
                LIMIT 1
                """,
                client_user_id,
            )
        if not row:
            return None
        pd = row.get("profile_data") or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        if not isinstance(pd, dict):
            pd = {}
        for key in ("assigned_coach", "coach_username"):
            v = pd.get(key)
            if v and str(v).strip():
                return str(v).strip()
        cid = pd.get("coach_id") or pd.get("assigned_coach_id")
        if not cid:
            return None
        hw = str(cid).strip()
        async with db_pool.acquire() as conn:
            r2 = await conn.fetchrow(
                """
                SELECT username FROM users
                WHERE (hardware_id = $1 OR username = $1)
                  AND role IN ('COACH', 'ADMIN')
                LIMIT 1
                """,
                hw,
            )
        if r2 and r2.get("username"):
            return str(r2["username"]).strip()
    except Exception as e:
        logger.warning("cycle_skill_plan: resolve coach failed: %s", e)
    return None


def build_coach_skill_plan_copy(
    *,
    event: str,
    client_name: str,
    client_username: str,
    plan: Dict[str, Any],
) -> Tuple[str, str]:
    """Subject + plain body for coach plan/progress notifications."""
    title = str(plan.get("title") or "skills practice")
    modality = str(plan.get("modality") or "skills")
    domain = str(plan.get("cycle_domain") or "").replace("_", " ")
    cur = int(plan.get("current_step") or 1)
    total = int(plan.get("total_steps") or 1)
    who = (client_name or client_username or "Client").strip()
    handle = (client_username or "").strip()
    label = f"{who} ({handle})" if handle and handle != who else who
    coach_url = os.getenv(
        "COACH_APP_URL", "https://coach.sovereignsanctuary.net"
    ).rstrip("/")

    subjects = {
        "suggested": f"Plan offered: {label} — {title}",
        "activated": f"Plan started: {label} — {title}",
        "advanced": f"Plan progress: {label} — step {cur}/{total}",
        "checkin_due": f"Check-in due: {label} — {title}",
        "completed": f"Plan completed: {label} — {title}",
        "declined": f"Plan declined: {label} — {title}",
    }
    bodies = {
        "suggested": (
            f"Little Nate offered {label} an optional {modality} practice "
            f"({title}"
            + (f", cycle: {domain}" if domain else "")
            + "). Status: suggested — awaiting client acceptance."
        ),
        "activated": (
            f"{label} accepted {title} ({modality}). "
            f"Now on step {cur} of {total}."
        ),
        "advanced": (
            f"{label} advanced on {title} ({modality}) to step {cur} of {total}."
        ),
        "checkin_due": (
            f"A skills check-in is due for {label} on {title} "
            f"(step {cur}/{total}). Nate will ask in chat; review if helpful."
        ),
        "completed": (
            f"{label} completed {title} ({modality}). "
            f"A stacked follow-up may be offered next."
        ),
        "declined": (
            f"{label} declined the offered practice {title} ({modality}). "
            f"No further auto-offers until cooldown ends."
        ),
    }
    subject = subjects.get(event, f"Treatment plan update: {label}")
    body = bodies.get(event, f"Update on {title} for {label} (step {cur}/{total}).")
    body = f"{body}\n\nOpen Coach Portal: {coach_url}"
    return subject, body


async def notify_coach_skill_plan(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
    event: str,
) -> bool:
    """In-app + email coach on client skill/treatment plan progress."""
    if event not in _COACH_EMAILABLE_EVENTS:
        return False
    if not cycle_skill_coach_emails_enabled() or not db_pool or not user_id:
        return False
    plan_id = str(plan.get("id") or "")
    if await _recently_emailed(
        db_pool, plan_id, event, marker_prefix="coach_email_sent"
    ):
        return False
    coach_username = await _resolve_assigned_coach_username(db_pool, user_id)
    if not coach_username:
        return False
    _, client_name = await _resolve_client_email(db_pool, user_id)
    # Name resolution may return None email when client opted out of email —
    # still resolve display name from profile for coach copy.
    if not client_name:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT username, profile_data->>'name' AS name
                    FROM users
                    WHERE username = $1 OR hardware_id = $1
                    LIMIT 1
                    """,
                    user_id,
                )
            if row:
                client_name = (row.get("name") or row.get("username") or "").strip()
                user_id = str(row.get("username") or user_id)
        except Exception:
            pass
    subject, message = build_coach_skill_plan_copy(
        event=event,
        client_name=client_name or user_id,
        client_username=user_id,
        plan=plan,
    )
    ok_any = False
    try:
        from app.services.coach_notifications import notify_coach

        result = await notify_coach(
            db_pool,
            coach_username,
            {
                "urgency": "medium",
                "subject": subject[:200],
                "message": message[:4000],
                "payload": {
                    "alert_type": "cycle_skill_plan",
                    "event": event,
                    "client_username": user_id,
                    "plan_id": plan_id,
                    "modality": plan.get("modality"),
                    "title": plan.get("title"),
                },
            },
        )
        ok_any = bool(result.get("sent", {}).get("in_app"))
    except Exception as e:
        logger.warning("cycle_skill_plan: coach in-app notify failed: %s", e)

    # notify_coach only emails on critical — send plan emails explicitly.
    try:
        from app.services.coach_notifications import (
            _lookup_coach_contact,
            _send_sendgrid_simple,
        )

        _phone, coach_email = await _lookup_coach_contact(db_pool, coach_username)
        if coach_email and "@" in coach_email and os.getenv("SENDGRID_API_KEY"):
            if await _send_sendgrid_simple(coach_email, subject[:200], message):
                ok_any = True
                logger.info(
                    "cycle_skill_plan: coach emailed %s event=%s plan=%s",
                    coach_username,
                    event,
                    plan_id[:8] if plan_id else "",
                )
    except Exception as e:
        logger.warning("cycle_skill_plan: coach email failed: %s", e)

    if ok_any and plan_id:
        await _stamp_email_marker(db_pool, plan_id, f"coach_email_sent:{event}")
    return ok_any


def schedule_coach_skill_plan_notify(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
    event: str,
) -> None:
    if not cycle_skill_coach_emails_enabled() or event not in _COACH_EMAILABLE_EVENTS:
        return
    try:
        import asyncio

        asyncio.create_task(
            notify_coach_skill_plan(
                db_pool, user_id=user_id, plan=plan, event=event
            )
        )
    except Exception:
        pass


async def notify_client_skill_plan_email(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
    event: str,
) -> bool:
    """Email the client on plan offer / progress (SendGrid). Debounced per event."""
    if event not in _EMAILABLE_EVENTS:
        return False
    if not cycle_skill_emails_enabled() or not db_pool or not user_id:
        return False
    plan_id = str(plan.get("id") or "")
    if await _recently_emailed(db_pool, plan_id, event):
        return False
    email, name = await _resolve_client_email(db_pool, user_id)
    if not email or "@" not in email:
        return False
    subject, html = build_skill_plan_email_copy(event=event, name=name, plan=plan)
    api_key = (os.getenv("SENDGRID_API_KEY") or "").strip()
    if not api_key:
        logger.warning("cycle_skill_plan: email skipped — SENDGRID_API_KEY unset")
        return False
    from_email = os.getenv("FROM_EMAIL", "support@sovereignsanctuary.net")
    from_name = os.getenv("FROM_NAME", "Little Nate")
    try:
        import aiohttp

        payload = {
            "personalizations": [{"to": [{"email": email}]}],
            "from": {"email": from_email, "name": from_name},
            "subject": subject[:200],
            "content": [{"type": "text/html", "value": html}],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                ok = resp.status in (200, 202)
        if ok and plan_id:
            await _stamp_email_marker(db_pool, plan_id, f"email_sent:{event}")
            logger.info(
                "cycle_skill_plan: emailed %s event=%s plan=%s",
                email[:3] + "***",
                event,
                plan_id[:8],
            )
        return ok
    except Exception as e:
        logger.warning("cycle_skill_plan: email send failed: %s", e)
        return False


def schedule_client_skill_plan_email(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
    event: str,
) -> None:
    if not cycle_skill_emails_enabled() or event not in _EMAILABLE_EVENTS:
        return
    try:
        import asyncio

        asyncio.create_task(
            notify_client_skill_plan_email(
                db_pool, user_id=user_id, plan=plan, event=event
            )
        )
    except Exception:
        pass


async def _log_skill_learning(
    db_pool: Any,
    *,
    user_id: str,
    plan: Dict[str, Any],
    event: str,
    detail: str = "",
) -> None:
    """Learning hook: adaptation_log + skyeye_activity + client/coach notify."""
    plan_id = str(plan.get("id") or "")
    entry = {
        "event": event,
        "modality": plan.get("modality"),
        "cycle_domain": plan.get("cycle_domain"),
        "step": plan.get("current_step"),
        "detail": (detail or "")[:240],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        if plan_id:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE nate_therapeutic_plans
                    SET adaptation_log = adaptation_log || $2::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    plan_id,
                    json.dumps([entry]),
                )
    except Exception as e:
        logger.warning("cycle_skill_plan: adaptation_log failed: %s", e)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO skyeye_activity (type, content, platform, created_at)
                VALUES (
                    'cycle_skill_learning',
                    $1::text,
                    'cycle_skill',
                    NOW()
                )
                """,
                json.dumps(
                    {
                        "user_id": user_id,
                        "plan_id": plan_id,
                        **entry,
                    }
                )[:2000],
            )
    except Exception:
        pass
    schedule_client_skill_plan_email(
        db_pool, user_id=user_id, plan=plan, event=event
    )
    schedule_coach_skill_plan_notify(
        db_pool, user_id=user_id, plan=plan, event=event
    )


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

        # Complete — queue succession for after STACK_COOLDOWN (no same-turn stack)
        domain = plan.get("cycle_domain") or ""
        mapping = _DOMAIN_TEMPLATE.get(str(domain))
        next_tpl_id = mapping[2] if mapping else None
        offer_after = (
            datetime.now(timezone.utc) + timedelta(hours=_STACK_COOLDOWN_HOURS)
        ).isoformat()
        complete_events: List[Dict[str, Any]] = [
            {
                "event": "completed",
                "at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        if next_tpl_id:
            modality = mapping[1] if mapping else "skills"
            tpl = await _load_template(db_pool, next_tpl_id)
            if tpl:
                title_l = (tpl.get("title") or "").lower()
                if "ground" in title_l or "mindful" in title_l:
                    modality = "grounding"
                elif "cbt" in title_l:
                    modality = "CBT"
                elif "act" in title_l:
                    modality = "ACT"
                elif "dbt" in title_l:
                    modality = "DBT"
                complete_events.append(
                    {
                        "event": "pending_stack",
                        "template_id": next_tpl_id,
                        "domain": str(domain),
                        "modality": modality,
                        "parent_plan_id": plan_id,
                        "offer_after": offer_after,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                logger.info(
                    "cycle_skill_plan: queued pending_stack %s after %s (offer_after=%s)",
                    next_tpl_id,
                    plan_id,
                    offer_after,
                )
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
                json.dumps(complete_events),
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
        await _log_skill_learning(
            db_pool, user_id=username, plan=plan, event="declined", detail=text[:120]
        )
        return {"ok": True, "action": "declined", "plan_id": str(plan["id"])}

    if plan and plan.get("status") == "suggested" and _client_accepts_plan(text):
        await _activate_plan(db_pool, str(plan["id"]))
        plan["status"] = "active"
        await _schedule_followup_commitment(db_pool, user_id=username, plan=plan)
        await _log_skill_learning(
            db_pool, user_id=username, plan=plan, event="activated", detail=text[:120]
        )
        return {"ok": True, "action": "activated", "plan_id": str(plan["id"])}

    # QUANTUM-CRYSTAL-ARCH: practice evidence on suggested = activate only (no skip-ahead)
    if plan and plan.get("status") == "suggested" and _client_advances_plan(text):
        await _activate_plan(db_pool, str(plan["id"]))
        plan["status"] = "active"
        await _schedule_followup_commitment(db_pool, user_id=username, plan=plan)
        await _log_skill_learning(
            db_pool, user_id=username, plan=plan, event="activated",
            detail=f"practice_evidence:{text[:100]}",
        )
        return {"ok": True, "action": "activated", "plan_id": str(plan["id"])}

    # Advance/complete only after the plan is active (accepted or practice-evidence activate)
    if plan and plan.get("status") == "active" and _client_advances_plan(text):
        cur = int(plan.get("current_step") or 1)
        total = int(plan.get("total_steps") or 1)
        completing = cur >= total
        await _advance_or_stack(db_pool, user_id=username, plan=plan)
        if completing:
            plan["status"] = "completed"
        event = "completed" if completing else "advanced"
        await _log_skill_learning(
            db_pool, user_id=username, plan=plan, event=event, detail=text[:120]
        )
        return {
            "ok": True,
            "action": "completed" if completing else "advanced",
            "plan_id": str(plan["id"]),
        }

    if plan:
        # Due check-in: always re-stamp; commitment row only if consent
        if _checkin_due(plan):
            await _schedule_followup_commitment(
                db_pool, user_id=username, plan=plan
            )
            await _log_skill_learning(
                db_pool,
                user_id=username,
                plan=plan,
                event="checkin_due",
                detail="in_chat_or_commitment",
            )
            return {
                "ok": True,
                "action": "checkin_scheduled",
                "plan_id": str(plan["id"]),
            }
        return {"ok": True, "action": "has_plan", "plan_id": str(plan["id"])}

    # Fallback if pre-turn ensure missed (race / no plan context path)
    if await _recent_decline_cooldown(db_pool, username):
        return {"ok": True, "action": "cooldown"}
    released = await _maybe_release_pending_stack(db_pool, username)
    if released:
        return released
    if await _recent_completion_cooldown(db_pool, username):
        return {"ok": True, "action": "stack_cooldown"}
    created = await ensure_suggested_plan_from_cycles(db_pool, username)
    if created:
        return created
    return out


def schedule_cycle_skill_plan_tick(
    db_pool: Any,
    *,
    user_id: str,
    user_text: str,
    on_done: Any = None,
) -> None:
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return
    try:
        import asyncio

        async def _run() -> None:
            result = await maybe_tick_cycle_skill_plan(
                db_pool, user_id=user_id, user_text=user_text or ""
            )
            if on_done is not None:
                try:
                    maybe = on_done(result)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception as e:
                    logger.warning("cycle_skill_plan: on_done failed: %s", e)

        asyncio.create_task(_run())
    except Exception:
        pass


def schedule_skill_plan_post_turn(
    db_pool: Any,
    *,
    user_id: str,
    user_text: str,
    nate_response: str,
    user_name: str = "",
    on_done: Any = None,
    origin_surface: str = "cycle_skill",
) -> None:
    """Crystallize + tick after any chat surface (main / sanctuary / private)."""
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return
    try:
        import asyncio

        asyncio.create_task(
            crystallize_skill_plan_turn(
                db_pool,
                user_id=user_id,
                user_text=user_text or "",
                nate_response=nate_response or "",
                user_name=user_name or "",
                origin_surface=origin_surface,
            )
        )
        schedule_cycle_skill_plan_tick(
            db_pool, user_id=user_id, user_text=user_text or "", on_done=on_done
        )
    except Exception:
        pass


async def push_skill_plan_ws_update(
    sockets: Any,
    uid: str,
    db_pool: Any,
    user_id: str,
    ctx: Any = None,
) -> None:
    """Send cycle_skill_plan_update to open sockets for uid."""
    st = await build_client_skill_plan_status(db_pool, user_id)
    if not st or not sockets or uid not in sockets:
        return
    for _ws in list(sockets.get(uid, [])):
        if ctx is not None and getattr(_ws, "_eviction_context", "main") != ctx:
            continue
        try:
            await _ws.send(json.dumps({"type": "cycle_skill_plan_update", **st}))
        except Exception:
            try:
                sockets[uid].discard(_ws)
            except Exception:
                pass


def schedule_skill_plan_post_turn_with_ws(
    db_pool: Any,
    *,
    sockets: Any,
    uid: str,
    user_id: str,
    user_text: str,
    nate_response: str,
    user_name: str = "",
    ctx: Any = None,
    origin_surface: str = "bridge_chat",
) -> None:
    """Post-turn skill plan + Flutter WS status (keeps bridge call sites tiny)."""

    async def _on_done(_r: Any) -> None:
        await push_skill_plan_ws_update(sockets, uid, db_pool, user_id, ctx)

    schedule_skill_plan_post_turn(
        db_pool,
        user_id=user_id,
        user_text=user_text,
        nate_response=nate_response,
        user_name=user_name,
        on_done=_on_done,
        origin_surface=origin_surface,
    )


async def augment_recall_query_for_skill_plan(
    db_pool: Any, user_id: str, base_query: str
) -> str:
    """Bias crystal recall only for ACTIVE accepted plans (not suggested offers)."""
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return base_query or ""
    plan = await _get_plan_row(db_pool, user_id)
    if not plan or str(plan.get("status") or "") != "active":
        return base_query or ""
    step = _step_payload(
        plan.get("step_definitions"), int(plan.get("current_step") or 1)
    )
    # Light bias: modality + skill name only — not full practice script
    bits = [
        (base_query or "").strip(),
        str(plan.get("modality") or ""),
        str(step.get("skill") or "").replace("_", " "),
    ]
    return " ".join(b for b in bits if b).strip()[:500]


async def crystallize_skill_plan_turn(
    db_pool: Any,
    *,
    user_id: str,
    user_text: str,
    nate_response: str,
    user_name: str = "",
    origin_surface: str = "cycle_skill",
) -> Optional[str]:
    """Tag skill-plan turns into crystals (origin_surface=cycle_skill) for memory loop."""
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return None
    plan = await _get_plan_row(db_pool, user_id)
    if not plan:
        return None
    step = _step_payload(
        plan.get("step_definitions"), int(plan.get("current_step") or 1)
    )
    modality = plan.get("modality") or step.get("modality") or "skills"
    skill = str(step.get("skill") or "").replace("_", " ")
    tagged = (
        f"[cycle_skill {modality} step {plan.get('current_step')}/{plan.get('total_steps')}"
        f" {skill}] {(user_text or '').strip()}"
    )
    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation
    except ImportError:
        try:
            from crystal_recall_bridge import crystallize_from_conversation  # type: ignore
        except ImportError:
            return None
    try:
        return await crystallize_from_conversation(
            db_pool,
            user_id,
            tagged,
            nate_response or "",
            user_name=user_name,
            domain="clinical",
            min_score=3,
            origin_surface=origin_surface,
        )
    except Exception as e:
        logger.warning("cycle_skill_plan: crystallize turn failed: %s", e)
        return None


async def build_client_skill_plan_status(
    db_pool: Any, user_id: str
) -> Optional[Dict[str, Any]]:
    """Compact status for Flutter / coach UI (WebSocket cycle_skill_plan_update)."""
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return None
    plan = await _get_plan_row(db_pool, user_id)
    if not plan:
        return None
    step = _step_payload(
        plan.get("step_definitions"), int(plan.get("current_step") or 1)
    )
    return {
        "plan_id": str(plan["id"]),
        "title": plan.get("title"),
        "status": plan.get("status"),
        "source": plan.get("source"),
        "modality": plan.get("modality") or step.get("modality"),
        "cycle_domain": plan.get("cycle_domain"),
        "current_step": plan.get("current_step"),
        "total_steps": plan.get("total_steps"),
        "theme": step.get("theme"),
        "skill": step.get("skill"),
        "practice": step.get("practice"),
        "check_in": step.get("check_in"),
        "checkin_due": _checkin_due(plan),
    }


def compose_skill_teach_block(
    *,
    modality: str,
    skill: str,
    practice: str,
    accepting: bool,
) -> str:
    """Deterministic client-facing teach paragraph (Clinical-AGI floor)."""
    mod = _norm_modality(modality)
    skill_label = (skill or _skill_must_include({"skill": skill}, mod)).replace("_", " ")
    practice = (practice or "").strip()
    if accepting:
        return (
            f"Since you're willing — let's do this {mod} move ({skill_label}) now: "
            f"{practice}"
        )
    return (
        f"If it fits, here's one optional {mod} practice ({skill_label}): "
        f"{practice} Want to try that?"
    )


async def apply_skill_fidelity_guard(
    db_pool: Any,
    user_id: str,
    user_text: str,
    response: str,
    *,
    min_score: int = 4,
) -> str:
    """
    Post-LLM guarantee: if spoken reply drifts off-modality / doesn't teach,
    append (or correct) a deterministic practice block so clients get a real skill.
    """
    if not cycle_skill_plans_enabled() or not db_pool or not user_id:
        return response or ""
    text = response or ""
    username = await _resolve_username(db_pool, user_id)
    plan = await _get_plan_row(db_pool, username)
    if not plan:
        # Pre-turn suggest may have raced; try once more for cycle-driven first offer
        await ensure_suggested_plan_from_cycles(db_pool, username)
        plan = await _get_plan_row(db_pool, username)
    if not plan:
        return text

    step = _step_payload(
        plan.get("step_definitions"), int(plan.get("current_step") or 1)
    )
    modality = str(plan.get("modality") or step.get("modality") or "")
    skill = str(step.get("skill") or "")
    practice = str(step.get("practice") or step.get("theme") or "").strip()
    if not practice:
        return text

    accepting = _client_accepts_plan(user_text or "")
    advancing = _client_advances_plan(user_text or "")
    status = str(plan.get("status") or "")
    # QUANTUM-CRYSTAL-ARCH: never force practice onto glitch/image/meta turns
    if _SKILL_META_SKIP_RE.search(user_text or "") and not accepting:
        return text
    # Suggested without clear accept: never post-LLM append (prompt may still offer)
    if status == "suggested" and not accepting and not advancing:
        return text
    # Active without accept/advance this turn: do not hijack with teach block
    if status == "active" and not accepting and not advancing:
        return text

    score = score_skill_offer_fidelity(
        text, modality=modality, skill=skill, practice=practice
    )
    mod = _norm_modality(modality)
    grounding_wrong = bool(_GROUNDING_ATTRACTOR_RE.search(text)) and mod in (
        "CBT",
        "DBT",
        "ACT",
    )
    practice_l = practice.lower()
    core_ok = False
    if skill:
        core_ok = skill.lower().replace("_", " ") in text.lower() or skill.lower() in text.lower()
    if not core_ok:
        core_ok = any(
            m in text.lower()
            for m in _MODALITY_MARKERS.get(mod, ())[:6]
        )
    if practice_l[:32] and practice_l[:32] in text.lower():
        core_ok = True

    # QUANTUM-CRYSTAL-ARCH: never append next-step teach on suggested (activate-only path)
    if advancing and status == "active":
        if score >= 3 and core_ok:
            return text
        return (
            f"{text.rstrip()}\n\n"
            f"For the next step ({skill.replace('_', ' ') or mod}): {practice}"
        ).strip()
    if advancing and status == "suggested":
        return text

    # Clear accept: enforce on-modality teach (Clinical-AGI floor)
    need = 5 if accepting else min_score
    if accepting and score >= need and core_ok and not grounding_wrong:
        return text
    if not accepting:
        return text

    block = compose_skill_teach_block(
        modality=modality,
        skill=skill,
        practice=practice,
        accepting=accepting,
    )

    if grounding_wrong and (score <= 2 or not core_ok):
        return (
            "I hear that this has been looping and you want something usable. "
            f"{block}"
        ).strip()

    if practice_l[:48] in text.lower() and core_ok and score >= need:
        return text
    return f"{text.rstrip()}\n\n{block}".strip()
