"""Growth-phase resolver — QUANTUM-CRYSTAL-ARCH.

Single owner of ``client_growth_phase`` (migration 434). Three entry points:

* ``get_phase(db_pool, user_id)`` — cheap, cached (60 s), used on every turn
  by the bridge to pick LN's register and to gate the boundary guard.
* ``note_turn(db_pool, user_id, user_text, crisis=…)`` — turn-time sub-state
  transitions only: a client in a coaching phase who asks to work something
  through flips to ``working_through`` (TTL 72 h); any CRISIS trip flips to
  ``crisis_hold`` (TTL 48 h). Expired sub-states clear here too.
* ``evaluate(db_pool, user_id)`` — the slow path (healing-cycle composite).
  Run by the thrive agent on its cycle, never per turn. Auto-promotes one step
  after ``promote_streak`` consecutive evaluations above ``promote_score`` and
  ``min_days_in_phase``; demotes one step on a sustained low score. Every move
  is written to ``client_growth_phase_history`` and the assigned coach gets an
  in-app nudge (+ optional email via the injected notifier).

Identity: canonical ``users.username`` via ``_identity_resolver`` — never
hardware_id (sensitive-bridge rule).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from app.services._identity_resolver import resolve_username
from app.services.thrive import growth_phase as gp
from app.services.thrive.healing_cycle import HealingSignal, compute_healing_signal

logger = logging.getLogger(__name__)

ENABLE_GROWTH_PHASE = os.getenv("ENABLE_GROWTH_PHASE", "false").lower() in ("1", "true", "yes")

_CACHE_TTL_S = 60.0
_cache: Dict[str, tuple[float, "PhaseState"]] = {}

NotifyFn = Callable[[str, str, str, Dict[str, Any]], Awaitable[None]]
"""(coach_username, subject, body, meta) -> None"""


@dataclass
class PhaseState:
    username: str
    phase: str = gp.DEFAULT_PHASE
    sub_state: Optional[str] = None
    sub_state_until: Optional[datetime] = None
    phase_since: Optional[datetime] = None
    healing_score: Optional[float] = None
    score_streak: int = 0
    coach_override: bool = False
    set_by: str = "auto"
    persisted: bool = False

    @property
    def effective(self) -> str:
        return gp.effective_phase(self.phase, self.sub_state)

    @property
    def coaching(self) -> bool:
        return gp.is_coaching_phase(self.phase, self.sub_state)

    def days_in_phase(self, now: Optional[datetime] = None) -> float:
        if not self.phase_since:
            return 0.0
        now = now or datetime.now(timezone.utc)
        return max(0.0, (now - self.phase_since).total_seconds() / 86400.0)

    def to_profile_dict(self) -> Dict[str, Any]:
        """Shape stashed on the in-memory bridge profile as ``profile['growth_phase']``."""
        return {
            "phase": self.phase,
            "sub_state": self.sub_state,
            "effective": self.effective,
            "coaching": self.coaching,
            "since": self.phase_since.isoformat() if self.phase_since else None,
            "score": self.healing_score,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("sub_state_until", "phase_since"):
            if d.get(k):
                d[k] = d[k].isoformat()
        d["effective"] = self.effective
        d["coaching"] = self.coaching
        return d


@dataclass
class Transition:
    username: str
    from_phase: str
    to_phase: str
    from_sub_state: Optional[str]
    to_sub_state: Optional[str]
    reason: str
    healing_score: Optional[float]
    evidence: Dict[str, Any]
    set_by: str = "auto"
    coach_notified: bool = False


def _policy() -> gp.TransitionPolicy:
    p = gp.TransitionPolicy()
    for fld, env in (
        ("promote_score", "GROWTH_PROMOTE_SCORE"),
        ("demote_score", "GROWTH_DEMOTE_SCORE"),
    ):
        v = os.getenv(env)
        if v:
            try:
                setattr(p, fld, float(v))
            except ValueError:
                pass
    for fld, env in (
        ("promote_streak", "GROWTH_PROMOTE_STREAK"),
        ("min_days_in_phase", "GROWTH_MIN_DAYS_IN_PHASE"),
        ("working_through_ttl_hours", "GROWTH_WORKING_THROUGH_TTL_H"),
        ("crisis_hold_ttl_hours", "GROWTH_CRISIS_HOLD_TTL_H"),
    ):
        v = os.getenv(env)
        if v:
            try:
                setattr(p, fld, int(v))
            except ValueError:
                pass
    return p


def _row_to_state(username: str, row: Any) -> PhaseState:
    if not row:
        return PhaseState(username=username)
    return PhaseState(
        username=username,
        phase=row["phase"] or gp.DEFAULT_PHASE,
        sub_state=row["sub_state"],
        sub_state_until=row["sub_state_until"],
        phase_since=row["phase_since"],
        healing_score=float(row["healing_score"]) if row["healing_score"] is not None else None,
        score_streak=int(row["score_streak"] or 0),
        coach_override=bool(row["coach_override"]),
        set_by=row["set_by"] or "auto",
        persisted=True,
    )


def _clear_expired(state: PhaseState, now: datetime) -> bool:
    if state.sub_state and state.sub_state_until and state.sub_state_until <= now:
        state.sub_state = None
        state.sub_state_until = None
        return True
    return False


def invalidate(username: str) -> None:
    _cache.pop(username, None)


# ── read ───────────────────────────────────────────────────────────────────

async def get_phase(db_pool: Any, user_id: str, *, use_cache: bool = True) -> PhaseState:
    """Return the client's phase state. Never raises; defaults to PROCESS."""
    username = await resolve_username(db_pool, user_id) or (user_id or "")
    if not username:
        return PhaseState(username="")
    now_m = time.monotonic()
    if use_cache:
        hit = _cache.get(username)
        if hit and now_m - hit[0] < _CACHE_TTL_S:
            return hit[1]
    state = PhaseState(username=username)
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM client_growth_phase WHERE username = $1", username
                )
            state = _row_to_state(username, row)
            if _clear_expired(state, datetime.now(timezone.utc)):
                await _persist(db_pool, state)
        except Exception as e:
            logger.debug("phase_resolver: get_phase failed for %s: %s", username, e)
    _cache[username] = (now_m, state)
    return state


# ── write helpers ──────────────────────────────────────────────────────────

async def _persist(db_pool: Any, state: PhaseState) -> None:
    if not db_pool or not state.username:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO client_growth_phase
                    (username, phase, sub_state, sub_state_until, phase_since,
                     healing_score, score_streak, coach_override, set_by, last_evaluated, updated_at)
                VALUES ($1, $2, $3, $4, COALESCE($5, NOW()), $6, $7, $8, $9, NOW(), NOW())
                ON CONFLICT (username) DO UPDATE SET
                    phase = EXCLUDED.phase,
                    sub_state = EXCLUDED.sub_state,
                    sub_state_until = EXCLUDED.sub_state_until,
                    phase_since = EXCLUDED.phase_since,
                    healing_score = EXCLUDED.healing_score,
                    score_streak = EXCLUDED.score_streak,
                    coach_override = EXCLUDED.coach_override,
                    set_by = EXCLUDED.set_by,
                    last_evaluated = NOW(),
                    updated_at = NOW()
                """,
                state.username, state.phase, state.sub_state, state.sub_state_until,
                state.phase_since, state.healing_score, state.score_streak,
                state.coach_override, state.set_by,
            )
        state.persisted = True
        invalidate(state.username)
    except Exception as e:
        logger.warning("phase_resolver: persist failed for %s: %s", state.username, e)


async def _record_history(db_pool: Any, t: Transition) -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO client_growth_phase_history
                    (username, from_phase, to_phase, from_sub_state, to_sub_state,
                     reason, healing_score, evidence, set_by, coach_notified)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
                """,
                t.username, t.from_phase, t.to_phase, t.from_sub_state, t.to_sub_state,
                t.reason, t.healing_score, json.dumps(t.evidence, default=str), t.set_by, t.coach_notified,
            )
    except Exception as e:
        logger.warning("phase_resolver: history insert failed for %s: %s", t.username, e)


async def _coach_for(db_pool: Any, username: str) -> Optional[Dict[str, Any]]:
    """Assigned coach (username, id, email, display) via coach_id / assigned_coach."""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT c.username, c.id, c.profile_data->>'email' AS email,
                       c.profile_data->>'name' AS name
                FROM users u
                JOIN users c ON (
                    c.hardware_id = COALESCE(u.profile_data->>'coach_id', u.profile_data->>'assigned_coach_id')
                    OR c.username = u.profile_data->>'assigned_coach'
                ) AND c.role = 'COACH'
                WHERE u.username = $1
                LIMIT 1
                """,
                username,
            )
            return dict(row) if row else None
    except Exception as e:
        logger.debug("phase_resolver: coach lookup failed for %s: %s", username, e)
        return None


async def _notify_coach(db_pool: Any, t: Transition, notifier: Optional[NotifyFn]) -> bool:
    coach = await _coach_for(db_pool, t.username)
    if not coach:
        return False
    fw = gp.framework_for(t.to_phase)
    title = f"Little Nate moved {t.username} → {fw.label}"
    body = (
        f"{t.username}: {t.from_phase} → {t.to_phase}. Reason: {t.reason}. "
        f"Healing-cycle score {t.healing_score if t.healing_score is not None else 'n/a'}. "
        f"Coach focus now: {fw.coach_focus}"
    )
    ok = False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nate_nudges (user_id, nudge_type, title, content, metadata, scheduled_at)
                VALUES ($1, 'client_phase_promoted', $2, $3, $4::jsonb, NOW())
                """,
                coach["id"], title[:256], body,
                json.dumps({"client": t.username, "from": t.from_phase, "to": t.to_phase,
                            "score": t.healing_score}),
            )
            await conn.execute(
                """
                INSERT INTO skyeye_activity (type, content, platform, created_at)
                VALUES ('growth_phase_transition', $1, 'thrive', NOW())
                """,
                json.dumps({"client": t.username, "coach": coach["username"], "from": t.from_phase,
                            "to": t.to_phase, "reason": t.reason, "score": t.healing_score}),
            )
        ok = True
    except Exception as e:
        logger.warning("phase_resolver: coach nudge failed: %s", e)
    if notifier:
        try:
            await notifier(coach["username"], title, body, {"coach_email": coach.get("email"), "client": t.username})
            ok = True
        except Exception as e:
            logger.warning("phase_resolver: coach notifier failed: %s", e)
    return ok


# ── turn-time sub-state transitions ────────────────────────────────────────

def _matches(patterns, text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


async def note_turn(
    db_pool: Any,
    user_id: str,
    user_text: str,
    *,
    crisis: bool = False,
) -> PhaseState:
    """Apply working_through / crisis_hold rules for this turn. Cheap; cached read."""
    state = await get_phase(db_pool, user_id)
    if not state.username or not ENABLE_GROWTH_PHASE:
        return state
    pol = _policy()
    now = datetime.now(timezone.utc)
    text = user_text or ""
    changed = False
    reason = None

    if crisis and state.sub_state != gp.SUB_CRISIS_HOLD:
        state.sub_state, reason = gp.SUB_CRISIS_HOLD, "crisis_signal"
        state.sub_state_until = now + timedelta(hours=pol.crisis_hold_ttl_hours)
        changed = True
    elif crisis:
        state.sub_state_until = now + timedelta(hours=pol.crisis_hold_ttl_hours)
        changed = True
    elif (
        state.sub_state is None
        and (gp.is_coaching_phase(state.phase) or gp.is_consolidating(state.phase))
        and _matches(gp.WORK_THROUGH_REQUEST, text)
    ):
        state.sub_state, reason = gp.SUB_WORKING_THROUGH, "client_asked_to_work_through"
        state.sub_state_until = now + timedelta(hours=pol.working_through_ttl_hours)
        changed = True
    elif state.sub_state == gp.SUB_WORKING_THROUGH and _matches(gp.FORWARD_DECLARATION, text):
        # Client closed the loop themselves — release early.
        prev = state.sub_state
        state.sub_state, state.sub_state_until = None, None
        changed, reason = True, "client_declared_forward"
        await _record_history(db_pool, Transition(
            state.username, state.phase, state.phase, prev, None, reason, state.healing_score, {"text_head": text[:120]},
        ))

    if changed:
        await _persist(db_pool, state)
        if reason and reason != "client_declared_forward":
            await _record_history(db_pool, Transition(
                state.username, state.phase, state.phase, None, state.sub_state, reason,
                state.healing_score, {"text_head": text[:120], "crisis": crisis},
            ))
        _cache[state.username] = (time.monotonic(), state)

    # LN-led strengths interview: tally first-person strengths while coaching/consolidating,
    # never during crisis_hold or working_through. Fire-and-forget; failures are logged inside.
    if (
        not crisis
        and state.sub_state is None
        and (gp.is_coaching_phase(state.phase) or gp.is_consolidating(state.phase))
        and len(text) >= 12
    ):
        try:
            from app.services.thrive.strengths_interview import observe_turn as _observe_strengths
            asyncio.create_task(_observe_strengths(db_pool, state.username, text))
        except Exception as e:
            logger.debug("phase_resolver: strengths observe skipped: %s", e)
    return state


# ── slow path: evaluate + auto-promote ─────────────────────────────────────

async def evaluate(
    db_pool: Any,
    user_id: str,
    *,
    hardware_id: Optional[str] = None,
    notifier: Optional[NotifyFn] = None,
    policy: Optional[gp.TransitionPolicy] = None,
) -> tuple[PhaseState, Optional[Transition], HealingSignal]:
    """Compute the healing-cycle signal and move the phase if warranted."""
    pol = policy or _policy()
    state = await get_phase(db_pool, user_id, use_cache=False)
    signal = await compute_healing_signal(db_pool, state.username, hardware_id=hardware_id, days=pol.promote_window_days)
    if not state.username:
        return state, None, signal
    now = datetime.now(timezone.utc)
    transition: Optional[Transition] = None

    # Cold start: a client who has been in PROCESS for months should not be held
    # another min_days_in_phase just because the phase row was created today.
    if state.phase == gp.DEFAULT_PHASE and state.set_by == "auto" and not state.coach_override and db_pool:
        try:
            async with db_pool.acquire() as conn:
                moved = await conn.fetchval(
                    "SELECT COUNT(*) FROM client_growth_phase_history WHERE username = $1", state.username
                )
                first = None
                if not moved:
                    first = await conn.fetchval(
                        "SELECT MIN(created_at) FROM conversation_history WHERE user_id = $1 OR user_id = $2",
                        state.username, hardware_id or state.username,
                    )
            if first:
                state.phase_since = first if first.tzinfo else first.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.debug("phase_resolver: tenure lookup failed for %s: %s", state.username, e)

    # Language-only evidence is enough to promote when the window is dense and
    # wound-free (coherence/pmb/cycles/behaviour only accrue after the client
    # has practice and metric history). Otherwise require two components.
    _lang = (signal.evidence or {}).get("language") or {}
    _lang_strong = (
        signal.components.get("language") is not None
        and int(_lang.get("n") or 0) >= 30
        and int(_lang.get("wound") or 0) + int(_lang.get("asks") or 0) == 0
        and float(signal.score or 0) >= pol.promote_score + 0.10
    )
    _enough_evidence = len(signal.available) >= 2 or _lang_strong

    if signal.score is not None:
        state.healing_score = signal.score
        if signal.score >= pol.promote_score:
            state.score_streak = state.score_streak + 1 if state.score_streak >= 0 else 1
        elif signal.score <= pol.demote_score:
            state.score_streak = state.score_streak - 1 if state.score_streak <= 0 else -1
        else:
            state.score_streak = 0

        if state.coach_override:
            pass  # coach pinned the phase — score tracked, no auto move
        elif (
            state.score_streak >= pol.promote_streak
            and state.days_in_phase(now) >= pol.min_days_in_phase
            and state.sub_state is None
            and gp.next_phase(state.phase)
            and _enough_evidence
        ):
            to = gp.next_phase(state.phase)
            transition = Transition(
                state.username, state.phase, to, state.sub_state, None,
                f"healing_cycle {signal.score:.2f} ≥ {pol.promote_score} for {state.score_streak} evaluations",
                signal.score, signal.to_dict(),
            )
        elif (
            state.score_streak <= -pol.promote_streak
            and gp.prev_phase(state.phase)
            and gp.PHASE_INDEX[state.phase] >= gp.PHASE_INDEX[gp.CONSOLIDATE]
            and len(signal.available) >= 2
        ):
            to = gp.prev_phase(state.phase)
            transition = Transition(
                state.username, state.phase, to, state.sub_state, None,
                f"healing_cycle {signal.score:.2f} ≤ {pol.demote_score} for {abs(state.score_streak)} evaluations",
                signal.score, signal.to_dict(),
            )

    if transition:
        state.phase = transition.to_phase
        state.phase_since = now
        state.score_streak = 0
        state.set_by = "auto"
        if pol.notify_coach_on_promote:
            transition.coach_notified = await _notify_coach(db_pool, transition, notifier)
        await _record_history(db_pool, transition)
        logger.info("phase_resolver: %s %s → %s (%s)", state.username, transition.from_phase, transition.to_phase, transition.reason)

    await _persist(db_pool, state)
    return state, transition, signal


# ── coach override ─────────────────────────────────────────────────────────

async def set_phase(
    db_pool: Any,
    user_id: str,
    phase: str,
    *,
    set_by: str,
    reason: str = "coach_override",
    pin: bool = True,
    sub_state: Optional[str] = None,
) -> PhaseState:
    if phase not in gp.PHASE_INDEX:
        raise ValueError(f"unknown phase {phase!r}")
    if sub_state not in (None, gp.SUB_WORKING_THROUGH, gp.SUB_CRISIS_HOLD):
        raise ValueError(f"unknown sub_state {sub_state!r}")
    state = await get_phase(db_pool, user_id, use_cache=False)
    if not state.username:
        return state
    t = Transition(state.username, state.phase, phase, state.sub_state, sub_state, reason, state.healing_score,
                   {"manual": True}, set_by=set_by)
    now = datetime.now(timezone.utc)
    if phase != state.phase:
        state.phase_since = now
    state.phase = phase
    state.sub_state = sub_state
    state.sub_state_until = (now + timedelta(hours=72)) if sub_state else None
    state.coach_override = pin
    state.set_by = set_by
    state.score_streak = 0
    await _persist(db_pool, state)
    await _record_history(db_pool, t)
    return state


async def release_override(db_pool: Any, user_id: str, *, set_by: str) -> PhaseState:
    state = await get_phase(db_pool, user_id, use_cache=False)
    if state.username and state.coach_override:
        state.coach_override = False
        state.set_by = set_by
        await _persist(db_pool, state)
        await _record_history(db_pool, Transition(
            state.username, state.phase, state.phase, state.sub_state, state.sub_state,
            "coach_released_override", state.healing_score, {}, set_by=set_by,
        ))
    return state
