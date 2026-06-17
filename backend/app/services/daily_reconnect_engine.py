"""
Daily Reconnect Ritual engine — QUANTUM-CRYSTAL-ARCH

Nate-fronted connection ritual; coach/inference machinery is safety-floor only.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("daily_reconnect")

ENABLE_DAILY_RECONNECT: bool = os.getenv(
    "ENABLE_DAILY_RECONNECT", "false"
).lower() in ("true", "1", "yes")

LOG_PREFIX = ">>> [RECONNECT]"

STATES = frozenset({
    "CONSENT_CHECKPOINT", "ACTIVE", "SOFT_DEESCALATION", "PAUSED",
    "WRAP_UP", "OFFER_FS", "ENTER_FS", "COOLDOWN_SETUP", "PRIVATE_PROCESSING",
    "WARNING_STATE", "CRISIS_BYPASS", "CLOSED",
})

PROMPT_KINDS: List[Tuple[str, str]] = [
    ("appreciation", "Share one thing you appreciate about your partner today."),
    ("today", "What's one thing from today you'd like them to know?"),
    ("feeling_need", "What are you feeling, and what do you need?"),
    ("request", "What's one small request that would help you feel more connected?"),
]

# Self-reflection phase — follows partner prompts; never loops back to appreciation.
REFLECTION_PROMPT_KINDS: List[Tuple[str, str]] = [
    ("self_present", "What are you noticing in yourself right now — without trying to fix anything?"),
    ("self_need", "What do you need from yourself to feel a little steadier tonight?"),
    ("self_carry", "What felt meaningful to you in what you shared today?"),
]

COUPLE_DISCUSSION_MESSAGE = (
    "Take a few minutes together — not to solve anything, just to talk about "
    "what you each shared. What landed for you? What do you want your partner to know?"
)

ROLLING_N = 4
TEMP_RISE_THRESHOLD = 0.55
TEMP_SPIKE_DELTA = 0.25
SOFT_MAX_TURNS = 2
MAX_SOFT_INCIDENTS = 2
COOLDOWN_CHOICES = (1, 2, 3, 4, 12)
WARNING_HOURS = 48

def _prompt_count() -> int:
    return len(PROMPT_KINDS) + len(REFLECTION_PROMPT_KINDS)


def _resolve_prompt(index: int) -> Tuple[str, str, str]:
    """Return (kind, text, phase) for a prompt index; phase = connection|reflection|complete."""
    if index < len(PROMPT_KINDS):
        kind, text = PROMPT_KINDS[index]
        return kind, text, "connection"
    ri = index - len(PROMPT_KINDS)
    if ri < len(REFLECTION_PROMPT_KINDS):
        kind, text = REFLECTION_PROMPT_KINDS[ri]
        return kind, text, "reflection"
    return "", "", "complete"


CONSENT_TEXT = (
    "Before you begin: this exchange is monitored. Little Nate may characterize "
    "connection patterns for your coach, and the platform team may review sessions "
    "for safety and quality. Do you acknowledge and wish to continue?"
)


def _log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _age_from_dob(dob_raw: Any) -> Optional[int]:
    if not dob_raw:
        return None
    s = str(dob_raw).strip()
    if not s:
        return None
    parsed: Optional[date] = None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            parsed = datetime.strptime(s[:10], fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = date.fromisoformat(s[:10])
        except ValueError:
            return None
    today = date.today()
    age = today.year - parsed.year - (
        (today.month, today.day) < (parsed.month, parsed.day)
    )
    if age < 0 or age > 125:
        return None
    return age


def _parse_jsonb(val: Any) -> Dict[str, Any]:
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val) or {}
        except json.JSONDecodeError:
            return {}
    return {}


@dataclass
class _RollingState:
    temps: List[float] = field(default_factory=list)
    distress_markers: int = 0
    monotonic_rises: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "temps": self.temps[-ROLLING_N:],
            "distress_markers": self.distress_markers,
            "monotonic_rises": self.monotonic_rises,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "_RollingState":
        return cls(
            temps=list(data.get("temps") or [])[-ROLLING_N:],
            distress_markers=int(data.get("distress_markers") or 0),
            monotonic_rises=int(data.get("monotonic_rises") or 0),
        )


class DailyReconnectEngine:
    """State machine + WS dispatch for Daily Reconnect."""

    def __init__(
        self,
        db_pool: Any,
        sanctuary_engine: Any = None,
        *,
        tier_gate_fn: Optional[Callable[[Dict], bool]] = None,
        load_registry_fn: Optional[Callable[[], Dict]] = None,
        generate_group_coaching_fn: Optional[Callable] = None,
        cortex: Any = None,
    ):
        self.db_pool = db_pool
        self.sanctuary_engine = sanctuary_engine
        self._tier_gate = tier_gate_fn
        self._load_registry = load_registry_fn or (lambda: {})
        self._generate_group_coaching = generate_group_coaching_fn
        self._cortex = cortex
        self._ws_registry: Dict[str, Dict[str, Any]] = {}
        self._session_states: Dict[str, Any] = {}

    async def handle_ws_message(
        self,
        msg_type: str,
        data: Dict[str, Any],
        websocket: Any,
        profile: Dict[str, Any],
    ) -> None:
        if not ENABLE_DAILY_RECONNECT:
            await self._send(websocket, {
                "type": "reconnect_error",
                "message": "feature_disabled",
            })
            await self._emit_event(None, profile.get("family_id"), "flag_off_skip", {})
            return

        if self._tier_gate and not self._tier_gate(profile):
            await self._send(websocket, {
                "type": "reconnect_error",
                "message": "FAMILY_SANCTUARY_UPGRADE_REQUIRED",
                "detail": "Daily Reconnect requires Sovereign Circle.",
            })
            return

        handlers = {
            "reconnect_get_or_create": self._handle_get_or_create,
            "reconnect_join": self._handle_join,
            "reconnect_consent_ack": self._handle_consent_ack,
            "reconnect_turn": self._handle_turn,
            "reconnect_fs_offer_response": self._handle_fs_offer_response,
            "reconnect_finish": self._handle_finish,
            "reconnect_cooldown_choice": self._handle_cooldown_choice,
            "reconnect_reenter": self._handle_reenter,
            "reconnect_exit": self._handle_exit,
        }
        fn = handlers.get(msg_type)
        if not fn:
            await self._send(websocket, {"type": "reconnect_error", "message": "unknown_type"})
            return
        await fn(data, websocket, profile)

    async def _handle_get_or_create(
        self, data: Dict, websocket: Any, profile: Dict
    ) -> None:
        family_id = profile.get("family_id")
        if not family_id:
            await self._send(websocket, {"type": "reconnect_error", "message": "no_family"})
            return

        username = await self._resolve_user(profile)
        if not username:
            await self._send(websocket, {"type": "reconnect_error", "message": "identity_unresolved"})
            return

        block = await self._join_eligibility(profile, username)
        if block:
            await self._send(websocket, {"type": "reconnect_error", **block})
            return

        session = await self._get_active_session(family_id)
        warm_return = False
        if not session:
            session = await self._create_session(family_id, profile)
        else:
            warm_return = await self._maybe_warm_return(session, username)

        sid = str(session["id"])
        await self._maybe_heal_stuck_session(sid)
        session = await self._load_session(sid) or session
        await self._upsert_participant(sid, username, profile)
        self._register_ws(sid, username, websocket)

        # Self-heal: if state is stuck at CONSENT_CHECKPOINT but all present
        # participants already have consent_ack_at (re-enter / race / legacy
        # row), auto-transition to ACTIVE so the ritual can proceed.
        if session.get("state") == "CONSENT_CHECKPOINT" and await self._all_present_consented(sid):
            await self._transition(sid, "ACTIVE", "auto_heal_all_consented")
            await self._increment_reconnect_count(sid)
            order = session.get("turn_order") or []
            if isinstance(order, str):
                try:
                    order = json.loads(order)
                except Exception:
                    order = []
            first_user = order[0] if order else username
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE daily_reconnect_session
                    SET current_turn_user_id = $2, updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    sid, first_user,
                )
            session = await self._load_session(sid) or session

        if self.sanctuary_engine and not session.get("sanctuary_id"):
            sanctuary_id = await self._ensure_sanctuary_room(family_id, profile)
            if sanctuary_id:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE daily_reconnect_session SET sanctuary_id = $1, updated_at = NOW() WHERE id = $2::uuid",
                        sanctuary_id, sid,
                    )
                session["sanctuary_id"] = sanctuary_id

        if session.get("sanctuary_id") and self.sanctuary_engine:
            try:
                hw = profile.get("hardware_id") or username
                await self.sanctuary_engine.add_or_reconnect_member(
                    sanctuary_id=session["sanctuary_id"],
                    user_id=hw,
                    user_name=profile.get("name") or username,
                    websocket=websocket,
                    user_family_id=family_id,
                )
            except Exception as e:
                _log(f"sanctuary room attach failed: {e}")

        payload = await self._session_payload(session, username, warm_return=warm_return)
        await self._send(websocket, {"type": "reconnect_state", **payload})
        await self._broadcast(sid, {"type": "reconnect_member_joined", "user_id": username}, exclude=username)

    async def _handle_join(self, data: Dict, websocket: Any, profile: Dict) -> None:
        await self._handle_get_or_create(data, websocket, profile)

    async def _handle_consent_ack(self, data: Dict, websocket: Any, profile: Dict) -> None:
        accepted = bool(data.get("accepted", True))
        username = await self._resolve_user(profile)
        session_id = data.get("session_id") or ""
        if not username or not session_id:
            await self._send(websocket, {"type": "reconnect_error", "message": "missing_fields"})
            return

        if not accepted:
            await self._emit_event(session_id, profile.get("family_id"), "consent_decline", {"user_id": username})
            await self._send(websocket, {"type": "reconnect_consent_result", "accepted": False})
            return

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daily_reconnect_participant
                SET consent_ack_at = NOW()
                WHERE session_id = $1::uuid AND user_id = $2
                """,
                session_id, username,
            )
        await self._emit_event(session_id, profile.get("family_id"), "consent_ack", {"user_id": username})

        session = await self._load_session(session_id)
        if session and await self._all_present_consented(session_id):
            if session["state"] == "CONSENT_CHECKPOINT":
                await self._transition(session_id, "ACTIVE", "all_consented")
                await self._increment_reconnect_count(session_id)
                order = session.get("turn_order") or []
                if isinstance(order, str):
                    order = json.loads(order)
                first_user = order[0] if order else username
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE daily_reconnect_session
                        SET current_turn_user_id = $2, updated_at = NOW()
                        WHERE id = $1::uuid
                        """,
                        session_id, first_user,
                    )
            session = await self._load_session(session_id)

        payload = await self._session_payload(session or {}, username)
        await self._send(websocket, {"type": "reconnect_consent_result", "accepted": True, **payload})

    async def _handle_turn(self, data: Dict, websocket: Any, profile: Dict) -> None:
        session_id = data.get("session_id") or ""
        content = (data.get("content") or "").strip()
        username = await self._resolve_user(profile)
        if not username or not session_id or not content:
            await self._send(websocket, {"type": "reconnect_error", "message": "missing_turn_fields"})
            return

        session = await self._load_session(session_id)
        if not session:
            await self._send(websocket, {"type": "reconnect_error", "message": "session_not_found"})
            return

        if session["state"] == "CONSENT_CHECKPOINT":
            await self._send(websocket, {"type": "reconnect_error", "message": "consent_required"})
            return

        if session["state"] in ("CLOSED", "CRISIS_BYPASS", "ENTER_FS"):
            await self._send(websocket, {"type": "reconnect_error", "message": "session_not_active"})
            return

        # STOPGAP trigger — replace with Layer-0 cluster detector (DECISION-3)
        crisis = await self._check_crisis_stopgap(profile, content, session)
        if crisis:
            await self._enter_crisis_bypass(session_id, profile, content, crisis)
            payload = await self._session_payload(await self._load_session(session_id), username)
            await self._broadcast(session_id, {"type": "reconnect_crisis_bypass", **payload})
            return

        if session["state"] not in ("ACTIVE", "SOFT_DEESCALATION"):
            await self._send(websocket, {"type": "reconnect_error", "message": f"wrong_state_{session['state']}"})
            return

        if session.get("current_turn_user_id") != username:
            await self._send(websocket, {"type": "reconnect_error", "message": "not_your_turn"})
            return

        prompt_index = int(session.get("current_prompt_index") or 0)
        if prompt_index >= _prompt_count():
            await self._send(websocket, {"type": "reconnect_error", "message": "ritual_complete"})
            return

        kind, _, _phase = _resolve_prompt(prompt_index)
        temp, temp_detail = self._score_temperature(content, session_id, username)

        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO daily_reconnect_turn
                        (session_id, user_id, prompt_index, prompt_kind, content, temperature, temperature_detail)
                    VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    session_id, username, prompt_index, kind, content, temp,
                    json.dumps(temp_detail),
                )
            except Exception as e:
                if "unique" in str(e).lower():
                    await self._send(websocket, {"type": "reconnect_error", "message": "turn_already_locked"})
                    return
                raise

        rolling = self._update_rolling(session_id, temp, temp_detail)
        temp_rise = self._temp_rise(temp, temp_detail, rolling)
        cooled, cooled_reason = self._eval_cooled(temp, temp_detail, rolling, session)

        await self._emit_event(session_id, session.get("family_id"), "turn_recorded", {
            "user_id": username,
            "prompt_index": prompt_index,
            "temperature": temp,
            "temp_detail": temp_detail,
            "rolling": rolling.to_dict(),
            "temp_rise": temp_rise,
            "cooled": cooled,
            "cooled_reason": cooled_reason,
        })

        new_state = session["state"]
        if temp_rise and session["state"] == "ACTIVE":
            new_state = "SOFT_DEESCALATION"
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE daily_reconnect_session
                    SET soft_incident_count = soft_incident_count + 1,
                        soft_turns_in_incident = 0,
                        rolling_escalation = $2::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    session_id, json.dumps(rolling.to_dict()),
                )
            await self._transition(session_id, "SOFT_DEESCALATION", "temp_rise")
            await self._write_inference_safety_floor(session_id, {
                "connection_indicator": min(10, max(1, int(temp * 10))),
                "attachment_hypothesis": "escalation_observed",
                "position": "safety_floor",
                "trigger": "temp_rise",
            })
        elif session["state"] == "SOFT_DEESCALATION":
            soft_turns = int(session.get("soft_turns_in_incident") or 0) + 1
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE daily_reconnect_session
                    SET soft_turns_in_incident = $2,
                        rolling_escalation = $3::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    session_id, soft_turns, json.dumps(rolling.to_dict()),
                )
            incident_count = int(session.get("soft_incident_count") or 0)
            if incident_count >= MAX_SOFT_INCIDENTS:
                new_state = "PAUSED"
                await self._transition(session_id, "PAUSED", "repeated_soft_incidents")
            elif not cooled or soft_turns > SOFT_MAX_TURNS:
                new_state = "PAUSED"
                await self._transition(session_id, "PAUSED", "not_cooled" if not cooled else "soft_turns_exceeded")
            elif cooled and soft_turns <= SOFT_MAX_TURNS:
                new_state = "ACTIVE"
                await self._transition(session_id, "ACTIVE", "cooled")

        await self._advance_turn_order(session_id)
        session = await self._load_session(session_id)
        nate_msg = self._nate_facilitation_message(session, username, temp_rise, cooled)
        payload = await self._session_payload(session, username)
        payload["nate_message"] = nate_msg
        await self._broadcast(session_id, {"type": "reconnect_turn_ack", **payload})
        if session.get("state") == "WRAP_UP":
            wrap_payload = await self._session_payload(session, username)
            wrap_payload["nate_message"] = COUPLE_DISCUSSION_MESSAGE
            await self._broadcast(session_id, {"type": "reconnect_wrap_up", **wrap_payload})

    async def _handle_finish(self, data: Dict, websocket: Any, profile: Dict) -> None:
        session_id = data.get("session_id") or ""
        username = await self._resolve_user(profile)
        session = await self._load_session(session_id)
        if not session or session.get("state") != "WRAP_UP":
            await self._send(websocket, {"type": "reconnect_error", "message": "not_in_wrap_up"})
            return
        await self._transition(session_id, "CLOSED", "wrap_up_done")
        payload = await self._session_payload(await self._load_session(session_id) or session, username or "")
        await self._broadcast(session_id, {"type": "reconnect_finished", **payload})

    async def _handle_fs_offer_response(self, data: Dict, websocket: Any, profile: Dict) -> None:
        session_id = data.get("session_id") or ""
        accepted = bool(data.get("accepted"))
        session = await self._load_session(session_id)
        if not session or session["state"] not in ("OFFER_FS", "WRAP_UP"):
            await self._send(websocket, {"type": "reconnect_error", "message": "not_in_offer_fs"})
            return
        if accepted:
            if session["state"] == "WRAP_UP":
                await self._transition(session_id, "OFFER_FS", "wrap_up_to_sanctuary")
            await self._transition(session_id, "ENTER_FS", "fs_accepted")
            if session.get("sanctuary_id"):
                try:
                    if self._generate_group_coaching:
                        await self._generate_group_coaching(session, profile)
                    else:
                        await self._handoff_enter_fs_coaching(session, profile)
                except Exception as e:
                    _log(f"ENTER_FS handoff error: {e}")
        else:
            if session["state"] == "WRAP_UP":
                await self._transition(session_id, "CLOSED", "wrap_up_sanctuary_declined")
            else:
                await self._transition(session_id, "COOLDOWN_SETUP", "fs_declined")
        payload = await self._session_payload(await self._load_session(session_id), await self._resolve_user(profile))
        await self._broadcast(session_id, {"type": "reconnect_fs_response", **payload})

    async def _handoff_enter_fs_coaching(self, session: Dict, profile: Dict) -> None:
        """ENTER_FS → sanctuary group coaching via bridge cortex (QUANTUM-CRYSTAL-ARCH)."""
        if not self.sanctuary_engine or not self._cortex:
            _log("ENTER_FS handoff skipped: missing sanctuary_engine or cortex")
            return
        sanctuary_id = session.get("sanctuary_id")
        if not sanctuary_id:
            return
        sanctuaries = self.sanctuary_engine.data.get("active_sanctuaries", {})
        sanctuary_data = sanctuaries.get(sanctuary_id) or {"sanctuary_id": sanctuary_id}

        def _prof_by_hw(hid: str) -> Dict[str, Any]:
            for _, v in (self._load_registry() or {}).items():
                p = v.get("profile", {})
                if p.get("hardware_id") == hid:
                    return dict(p)
            return {"hardware_id": hid, "name": hid}

        member_profiles: List[Dict[str, Any]] = []
        for m in self.sanctuary_engine.get_member_list(sanctuary_id):
            hid = m.get("user_id")
            if not hid:
                continue
            mp = _prof_by_hw(hid)
            mp["sanctuary_role"] = m.get("role", "MEMBER")
            mp["metrics"] = self._cortex.metrics.load_metrics(mp)
            mp["memory"] = self._cortex.mem.recall(mp, limit=5) or ""
            member_profiles.append(mp)

        turns = await self.get_locked_turns(str(session.get("id") or ""))
        recent_messages = [
            {
                "sender_id": t.get("user_id"),
                "sender_name": t.get("user_id"),
                "content": t.get("content", ""),
                "user_id": t.get("user_id"),
            }
            for t in turns
        ]
        if not recent_messages:
            recent_messages = sanctuary_data.get("messages", [])[-15:]

        for target in member_profiles:
            hid = target.get("hardware_id")
            if not hid:
                continue
            others = [p for p in member_profiles if p.get("hardware_id") != hid]
            suggestion = await self._cortex.generate_group_coaching_response(
                target_member=target,
                other_members=others,
                recent_messages=recent_messages,
                sanctuary_data=sanctuary_data,
            )
            user_ws = self.sanctuary_engine.get_member_websocket(sanctuary_id, hid)
            round_obj = (self.sanctuary_engine.get_session(sanctuary_id) or {}).get("group_coaching_round") or {}
            total_charges = float(
                (self.sanctuary_engine.get_session(sanctuary_id) or {})
                .get("billing", {})
                .get("total_charges", 0.0)
            )
            round_obj.setdefault("suggestions", {})[hid] = {
                "suggested_text": suggestion.get("suggested_response", ""),
                "rationale": suggestion.get("rationale", ""),
                "target_audience": suggestion.get("target_audience", "the family"),
                "emotional_tone": suggestion.get("emotional_tone", "supportive"),
                "total_charges": total_charges,
            }
            round_obj.setdefault("delivered_to", {})[hid] = bool(user_ws)
            if sanctuary_id in sanctuaries:
                sanctuaries[sanctuary_id]["group_coaching_round"] = round_obj
                self.sanctuary_engine._save()
            if user_ws:
                await user_ws.send(json.dumps({
                    "type": "sanctuary_suggested_response",
                    "sanctuary_id": sanctuary_id,
                    **round_obj["suggestions"][hid],
                }))
        _log(f"ENTER_FS handoff complete sanctuary={sanctuary_id}")

    async def _handle_cooldown_choice(self, data: Dict, websocket: Any, profile: Dict) -> None:
        session_id = data.get("session_id") or ""
        hours = int(data.get("hours") or 0)
        if hours not in COOLDOWN_CHOICES:
            await self._send(websocket, {"type": "reconnect_error", "message": "invalid_cooldown_hours"})
            return
        username = await self._resolve_user(profile)
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daily_reconnect_participant
                SET cooldown_choice_hours = $3
                WHERE session_id = $1::uuid AND user_id = $2
                """,
                session_id, username, hours,
            )
            rows = await conn.fetch(
                """
                SELECT cooldown_choice_hours FROM daily_reconnect_participant
                WHERE session_id = $1::uuid AND left_at IS NULL AND cooldown_choice_hours IS NOT NULL
                """,
                session_id,
            )
        max_hours = max((r["cooldown_choice_hours"] for r in rows), default=hours)
        lock_until = _utcnow() + timedelta(hours=max_hours)
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daily_reconnect_session
                SET cooldown_hours = $2, cooldown_lock_until = $3, state = 'PRIVATE_PROCESSING', updated_at = NOW()
                WHERE id = $1::uuid
                """,
                session_id, max_hours, lock_until,
            )
        await self._emit_event(session_id, profile.get("family_id"), "cooldown_started", {
            "hours": max_hours,
            "lock_until": lock_until.isoformat(),
            "trigger_kind": "keyword_stopgap",
            "note": "highest_risk_surface_until_cluster_detector",
        })
        payload = await self._session_payload(await self._load_session(session_id), username)
        await self._broadcast(session_id, {"type": "reconnect_cooldown_started", **payload})

    async def _handle_reenter(self, data: Dict, websocket: Any, profile: Dict) -> None:
        session_id = data.get("session_id") or ""
        session = await self._load_session(session_id)
        if not session:
            await self._send(websocket, {"type": "reconnect_error", "message": "session_not_found"})
            return
        lock = session.get("cooldown_lock_until")
        if lock and lock > _utcnow():
            await self._send(websocket, {"type": "reconnect_error", "message": "cooldown_active"})
            return
        if session["state"] == "WARNING_STATE":
            warn = session.get("warning_until")
            if warn and warn > _utcnow():
                await self._send(websocket, {"type": "reconnect_error", "message": "warning_period"})
                return
        await self._transition(session_id, "CONSENT_CHECKPOINT", "reenter")
        await self._handle_get_or_create(data, websocket, profile)

    async def _handle_exit(self, data: Dict, websocket: Any, profile: Dict) -> None:
        session_id = data.get("session_id") or ""
        username = await self._resolve_user(profile)
        if session_id and username:
            self._unregister_ws(session_id, username)
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE daily_reconnect_participant SET left_at = NOW()
                    WHERE session_id = $1::uuid AND user_id = $2
                    """,
                    session_id, username,
                )
        await self._send(websocket, {"type": "reconnect_exit_ok"})

    # ── Eligibility & safeguarding (correction E) ─────────────────────────

    async def _join_eligibility(self, profile: Dict, username: str) -> Optional[Dict]:
        role = (profile.get("family_role") or profile.get("role_in_family") or "").upper()
        if role == "DEPENDENT":
            await self._emit_event(None, profile.get("family_id"), "blocked_dependent_role", {"user_id": username})
            return {"message": "dependent_blocked", "detail": "Daily Reconnect is for adult family members."}

        if profile.get("is_minor") is True:
            await self._emit_event(None, profile.get("family_id"), "blocked_minor_by_age", {"user_id": username, "via": "is_minor_flag"})
            return {"message": "minor_blocked", "detail": "Daily Reconnect is for adults only."}

        dob = profile.get("dob") or (profile.get("profile_data") or {}).get("dob") if isinstance(profile.get("profile_data"), dict) else profile.get("dob")
        if not dob:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data, is_minor FROM users WHERE username = $1",
                    username,
                )
            if row:
                pd = row["profile_data"]
                if isinstance(pd, str):
                    try:
                        pd = json.loads(pd)
                    except json.JSONDecodeError:
                        pd = {}
                dob = (pd or {}).get("dob")
                if row.get("is_minor"):
                    await self._emit_event(None, profile.get("family_id"), "blocked_minor_by_age", {"user_id": username, "via": "db_is_minor"})
                    return {"message": "minor_blocked", "detail": "Daily Reconnect is for adults only."}

        age = _age_from_dob(dob)
        if age is None:
            await self._emit_event(None, profile.get("family_id"), "blocked_minor_by_age", {"user_id": username, "via": "missing_dob"})
            return {"message": "dob_required", "detail": "We need a verified date of birth to join Daily Reconnect."}
        if age < 18:
            await self._emit_event(None, profile.get("family_id"), "blocked_minor_by_age", {"user_id": username, "age": age})
            return {"message": "minor_blocked", "detail": "Daily Reconnect is for adults only."}
        return None

    async def _resolve_user(self, profile: Dict) -> Optional[str]:
        from app.services._identity_resolver import resolve_username

        ident = profile.get("username") or profile.get("hardware_id") or profile.get("user_id")
        if not ident:
            return None
        if profile.get("username"):
            return str(profile["username"])
        return await resolve_username(self.db_pool, str(ident))

    # ── Temperature & rolling escalation (correction B) ───────────────────

    def _score_temperature(
        self, content: str, session_id: str, username: str
    ) -> Tuple[float, Dict[str, Any]]:
        detail: Dict[str, Any] = {"confidence": "medium"}
        score = 0.2
        lower = content.lower()
        esc_keywords = [
            "angry", "furious", "hate", "frustrated", "upset", "scared",
            "hopeless", "worthless", "hurt", "stuck", "overwhelmed",
            "anxious", "panicking", "desperate", "helpless", "alone",
            "burden", "withdraw", "nothing matters",
        ]
        hits = sum(1 for kw in esc_keywords if kw in lower)
        if hits:
            score += min(0.15 * hits, 0.45)
            detail["escalation_hits"] = hits

        try:
            from app.services.little_nate_adaptive import SessionState, detect_distress

            st = self._session_states.setdefault(session_id, SessionState())
            if detect_distress(st, content):
                score = max(score, 0.7)
                detail["distress_detected"] = True
        except Exception as e:
            detail["distress_error"] = str(e)
            detail["confidence"] = "low"

        try:
            from app.services.therapeutic_controller import _detect_state_from_text

            affect = _detect_state_from_text(content)
            if affect:
                detail["affect"] = affect
                if affect in ("distressed", "activated", "escalating"):
                    score = max(score, 0.6)
        except Exception as e:
            detail["affect_error"] = str(e)
            if detail.get("confidence") != "low":
                detail["confidence"] = "low"

        if detail.get("confidence") == "low" or (
            detail.get("distress_detected") and not detail.get("escalation_hits")
        ):
            detail["ambiguous"] = True

        return min(score, 1.0), detail

    def _update_rolling(self, session_id: str, temp: float, detail: Dict) -> _RollingState:
        rolling = _RollingState.from_dict(
            getattr(self, "_rolling_cache", {}).get(session_id, {})
        )
        prev = rolling.temps[-1] if rolling.temps else None
        rolling.temps.append(temp)
        rolling.temps = rolling.temps[-ROLLING_N:]
        if prev is not None and temp > prev + 0.05:
            rolling.monotonic_rises += 1
        if detail.get("escalation_hits") or detail.get("distress_detected"):
            rolling.distress_markers += 1
        if not hasattr(self, "_rolling_cache"):
            self._rolling_cache = {}
        self._rolling_cache[session_id] = rolling.to_dict()
        return rolling

    def _temp_rise(self, temp: float, detail: Dict, rolling: _RollingState) -> bool:
        if temp >= TEMP_RISE_THRESHOLD + TEMP_SPIKE_DELTA:
            return True
        if len(rolling.temps) >= 3 and rolling.monotonic_rises >= 2:
            if rolling.temps[-1] > rolling.temps[0] + 0.15:
                return True
        if rolling.distress_markers >= 3 and temp >= TEMP_RISE_THRESHOLD:
            return True
        return False

    def _eval_cooled(
        self, temp: float, detail: Dict, rolling: _RollingState, session: Dict
    ) -> Tuple[bool, str]:
        if detail.get("ambiguous"):
            return False, "ambiguous"
        if temp >= TEMP_RISE_THRESHOLD:
            return False, "above_threshold"
        if rolling.monotonic_rises >= 2 and len(rolling.temps) >= 2:
            if rolling.temps[-1] >= rolling.temps[-2]:
                return False, "rolling_climbing"
        if detail.get("escalation_hits", 0) > 0:
            return False, "escalation_markers"
        return True, "cooled"

    # ── Crisis (correction A — STOPGAP) ───────────────────────────────────

    async def _check_crisis_stopgap(
        self, profile: Dict, content: str, session: Dict
    ) -> Optional[Dict]:
        matched: List[str] = []
        try:
            from app.services.suicide_ideation_lexicon import match_user_text

            matched = match_user_text(content) or []
        except Exception:
            pass
        distress = False
        try:
            from app.services.little_nate_adaptive import SessionState, detect_distress

            st = self._session_states.setdefault(str(session["id"]), SessionState())
            distress = detect_distress(st, content)
        except Exception:
            pass
        if matched or distress:
            return {
                "trigger_kind": "keyword_stopgap",
                "matched": matched,
                "distress": distress,
            }
        return None

    async def _enter_crisis_bypass(
        self, session_id: str, profile: Dict, content: str, crisis: Dict
    ) -> None:
        await self._transition(session_id, "CRISIS_BYPASS", "crisis_stopgap")
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE daily_reconnect_session SET crisis_bypass_at = NOW() WHERE id = $1::uuid",
                session_id,
            )
        try:
            from app.services.suicide_ideation_coach_alert import maybe_dispatch_si_coach_alert

            await maybe_dispatch_si_coach_alert(
                self.db_pool, profile, content, turn_id=session_id,
            )
        except Exception as e:
            _log(f"crisis dispatch error: {e}")
        await self._emit_event(session_id, profile.get("family_id"), "crisis_bypass", crisis)

    # ── Reward / miss encouragement (REWARD-1/2) ──────────────────────────

    async def _maybe_warm_return(self, session: Dict, username: str) -> bool:
        last = session.get("last_reconnect_at")
        if not last:
            return False
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last.replace("Z", "+00:00"))
            except ValueError:
                return False
        gap = _utcnow() - last
        if gap.total_seconds() < 86400:
            return False
        await self._emit_event(str(session["id"]), session.get("family_id"), "warm_return", {
            "user_id": username,
            "gap_hours": round(gap.total_seconds() / 3600, 1),
        })
        return True

    def _nate_facilitation_message(
        self, session: Dict, username: str, temp_rise: bool, cooled: bool
    ) -> str:
        tone = self._encouragement_tone(session, username)
        if temp_rise:
            return tone.pick(
                anxious="I'm here with you. Take a breath — you don't have to solve anything right now.",
                avoidant="No rush. We can slow down and keep this gentle.",
                default="Let's pause together for a moment. You're still connected.",
            )
        if session.get("state") == "PAUSED":
            return tone.pick(
                anxious="You're still in this together. Would you like a little space, or to continue with support?",
                avoidant="Whenever you're ready, we can pick up — no pressure.",
                default="Take the space you need. Showing up again counts just as much.",
            )
        if session.get("state") == "WRAP_UP":
            return tone.pick(
                anxious="You've shared a lot today. Take a few minutes together — talk about what landed.",
                avoidant="When you're ready, sit with each other and reflect on what you shared.",
                default=COUPLE_DISCUSSION_MESSAGE,
            )
        return tone.pick(
            anxious="Thank you for sharing. I'm right here with you.",
            avoidant="Thanks for being here. One step at a time.",
            default="Thank you for sharing.",
        )

    def _reward_expression(self, warm_return: bool = False) -> str:
        """Presence-based encouragement — no streak or quantity framing (REWARD-1)."""
        if warm_return:
            return "Welcome back — showing up again counts just as much as showing up daily."
        return (
            "You keep choosing to show up for each other. "
            "That presence matters more than perfection."
        )

    def _encouragement_tone(self, session: Dict, username: str) -> "_TonePicker":
        # Gentle-by-default; adapt only on confident read (REWARD-2)
        basis = _parse_jsonb(session.get("rolling_escalation"))
        if basis.get("attachment_read_confidence") == "high":
            leaning = basis.get("attachment_leaning", "default")
            if leaning in ("anxious", "avoidant"):
                return _TonePicker(leaning)
        return _TonePicker("default")

    def miss_encouragement_message(self, total_reconnects: int) -> str:
        """No-guilt re-invitation when members have been away (REWARD-2)."""
        _ = total_reconnects  # tracked internally; not surfaced as quantity pressure
        base = "Whenever you're ready, the door's open."
        if total_reconnects > 0:
            return (
                f"{base} Your connection here is still waiting — "
                "showing up again counts just as much."
            )
        return base

    # ── Inference (safety floor only — not v1 spine) ──────────────────────

    async def _write_inference_safety_floor(
        self, session_id: str, basis: Dict[str, Any]
    ) -> None:
        """Coach-only row; not surfaced to members in routine use."""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_reconnect_inference
                    (session_id, connection_indicator, attachment_hypothesis, position, basis_json)
                VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
                """,
                session_id,
                basis.get("connection_indicator", 5),
                basis.get("attachment_hypothesis", "observed_signal"),
                basis.get("position", "unknown"),
                json.dumps(basis),
            )

    # ── Session lifecycle ─────────────────────────────────────────────────

    async def _create_session(self, family_id: str, profile: Dict) -> Dict:
        turn_order = await self._build_turn_order(family_id)
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO daily_reconnect_session
                    (family_id, state, turn_order)
                VALUES ($1, 'CONSENT_CHECKPOINT', $2::jsonb)
                RETURNING *
                """,
                family_id, json.dumps(turn_order),
            )
        session = dict(row)
        await self._emit_event(str(session["id"]), family_id, "session_created", {})
        _log(f"created session {session['id']} family={family_id}")
        return session

    async def _get_active_session(self, family_id: str) -> Optional[Dict]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM daily_reconnect_session
                WHERE family_id = $1 AND closed_at IS NULL
                  AND state NOT IN ('CLOSED', 'CRISIS_BYPASS')
                ORDER BY created_at DESC LIMIT 1
                """,
                family_id,
            )
        return dict(row) if row else None

    async def _load_session(self, session_id: str) -> Optional[Dict]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM daily_reconnect_session WHERE id = $1::uuid",
                session_id,
            )
        return dict(row) if row else None

    async def _transition(self, session_id: str, new_state: str, reason: str) -> None:
        if new_state not in STATES:
            return
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daily_reconnect_session
                SET state = $2, updated_at = NOW(),
                    closed_at = CASE WHEN $2 IN ('CLOSED', 'CRISIS_BYPASS') THEN NOW() ELSE closed_at END
                WHERE id = $1::uuid
                """,
                session_id, new_state,
            )
        session = await self._load_session(session_id)
        await self._emit_event(session_id, (session or {}).get("family_id"), "state_transition", {
            "to": new_state,
            "reason": reason,
        })
        if new_state == "PAUSED":
            await self._transition(session_id, "OFFER_FS", "auto_offer_after_pause")

    async def _increment_reconnect_count(self, session_id: str) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daily_reconnect_session
                SET total_reconnects = total_reconnects + 1,
                    last_reconnect_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                session_id,
            )
        session = await self._load_session(session_id)
        await self._emit_event(session_id, (session or {}).get("family_id"), "total_reconnects", {
            "total_reconnects": int((session or {}).get("total_reconnects") or 0),
        })

    async def _upsert_participant(self, session_id: str, username: str, profile: Dict) -> None:
        role = profile.get("family_role") or profile.get("role_in_family") or "MEMBER"
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_reconnect_participant (session_id, user_id, family_role)
                VALUES ($1::uuid, $2, $3)
                ON CONFLICT (session_id, user_id) DO UPDATE SET
                    family_role = EXCLUDED.family_role,
                    left_at = NULL,
                    joined_at = NOW()
                """,
                session_id, username, role,
            )

    async def _all_present_consented(self, session_id: str) -> bool:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, consent_ack_at FROM daily_reconnect_participant
                WHERE session_id = $1::uuid AND left_at IS NULL
                """,
                session_id,
            )
        if len(rows) < 2:
            return False
        return all(r["consent_ack_at"] for r in rows)

    async def _build_turn_order(self, family_id: str) -> List[str]:
        registry = self._load_registry()
        usernames: List[str] = []
        for _k, entry in (registry or {}).items():
            if isinstance(_k, str) and _k.startswith("_"):
                continue
            prof = (entry or {}).get("profile") or entry or {}
            if prof.get("family_id") != family_id:
                continue
            role = (prof.get("family_role") or "").upper()
            if role == "DEPENDENT":
                continue
            un = prof.get("username") or prof.get("hardware_id")
            if un:
                usernames.append(str(un))
        return usernames[:8]

    async def _advance_turn_order(self, session_id: str) -> None:
        session = await self._load_session(session_id)
        if not session:
            return
        order = session.get("turn_order") or []
        if isinstance(order, str):
            order = json.loads(order)
        idx = int(session.get("current_prompt_index") or 0) + 1
        user_idx = 0
        if order:
            cur = session.get("current_turn_user_id")
            try:
                user_idx = (order.index(cur) + 1) % len(order) if cur in order else 0
            except ValueError:
                user_idx = 0
        if idx >= _prompt_count():
            await self._complete_ritual(session_id)
            return
        next_user = order[user_idx] if order else None
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daily_reconnect_session
                SET current_prompt_index = $2,
                    current_turn_user_id = $3,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                session_id, idx, next_user,
            )

    async def _complete_ritual(self, session_id: str) -> None:
        await self._transition(session_id, "WRAP_UP", "all_prompts_done")
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE daily_reconnect_session
                SET current_turn_user_id = NULL, updated_at = NOW()
                WHERE id = $1::uuid
                """,
                session_id,
            )

    async def _maybe_heal_stuck_session(self, session_id: str) -> None:
        """Advance sessions stuck repeating connection prompts after all four are answered."""
        session = await self._load_session(session_id)
        if not session or session.get("state") not in ("ACTIVE", "SOFT_DEESCALATION"):
            return
        turns = await self.get_locked_turns(session_id)
        if not turns:
            return
        indices = {int(t.get("prompt_index") or 0) for t in turns}
        cur = int(session.get("current_prompt_index") or 0)
        conn_done = all(i in indices for i in range(len(PROMPT_KINDS)))
        if conn_done and cur < len(PROMPT_KINDS):
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE daily_reconnect_session
                    SET current_prompt_index = $2, updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    session_id, len(PROMPT_KINDS),
                )
            return
        if cur >= _prompt_count() or len(turns) >= _prompt_count():
            await self._complete_ritual(session_id)

    async def _ensure_sanctuary_room(self, family_id: str, profile: Dict) -> Optional[str]:
        if not self.sanctuary_engine:
            return None
        existing = self.sanctuary_engine.get_active_sanctuary_for_family(family_id)
        if existing:
            return existing.get("sanctuary_id")
        try:
            hw = profile.get("hardware_id") or profile.get("username")
            return await self.sanctuary_engine.create_sanctuary(
                family_id=family_id,
                head_of_household_id=hw,
                invited_members=[],
                initial_topic="Daily Reconnect",
                consent_data={"signature": "daily_reconnect", "ip_address": ""},
            )
        except Exception as e:
            _log(f"create_sanctuary failed: {e}")
            return None

    async def _session_payload(
        self, session: Dict, username: str, warm_return: bool = False
    ) -> Dict[str, Any]:
        if not session:
            return {}
        sid = str(session["id"])
        prompt_index = int(session.get("current_prompt_index") or 0)
        kind, prompt_text, phase = _resolve_prompt(prompt_index)
        ritual_complete = session.get("state") == "WRAP_UP"
        async with self.db_pool.acquire() as conn:
            parts = await conn.fetch(
                """
                SELECT user_id, consent_ack_at, family_role FROM daily_reconnect_participant
                WHERE session_id = $1::uuid AND left_at IS NULL
                """,
                sid,
            )
        in_checkpoint = session.get("state") == "CONSENT_CHECKPOINT"
        any_unconsented = any(not p["consent_ack_at"] for p in parts)
        viewer_unconsented = any(
            (p["user_id"] == username and not p["consent_ack_at"]) for p in parts
        )
        # consent_required = True whenever the current viewer still owes consent
        # for an active CONSENT_CHECKPOINT, OR anyone in a 2+ session hasn't
        # acknowledged yet. Keeps the consent UI visible until the ritual moves on.
        consent_required = bool(
            in_checkpoint and (viewer_unconsented or any_unconsented or len(parts) < 2)
        )
        turns_raw = await self.get_locked_turns(sid)
        turns = []
        for t in turns_raw:
            pi = int(t.get("prompt_index") or 0)
            turn_kind, turn_prompt, turn_phase = _resolve_prompt(pi)
            turns.append(
                {
                    "user_id": t["user_id"],
                    "content": t["content"],
                    "prompt_index": pi,
                    "prompt_kind": t.get("prompt_kind") or turn_kind,
                    "prompt_text": turn_prompt,
                    "prompt_phase": turn_phase,
                    "created_at": (
                        t["created_at"].isoformat() if t.get("created_at") else None
                    ),
                }
            )
        all_prompt_defs = list(PROMPT_KINDS) + list(REFLECTION_PROMPT_KINDS)
        return {
            "session_id": sid,
            "state": session.get("state"),
            "sanctuary_id": session.get("sanctuary_id"),
            "consent_text": CONSENT_TEXT,
            "consent_required": consent_required,
            "participants": [
                {"user_id": p["user_id"], "consented": bool(p["consent_ack_at"])} for p in parts
            ],
            "total_reconnects": int(session.get("total_reconnects") or 0),
            "current_prompt_index": prompt_index,
            "prompt_kind": kind,
            "prompt_text": prompt_text,
            "prompt_phase": phase,
            "prompts": [
                {
                    "index": i,
                    "kind": k,
                    "text": txt,
                    "phase": "connection" if i < len(PROMPT_KINDS) else "reflection",
                }
                for i, (k, txt) in enumerate(all_prompt_defs)
            ],
            "ritual_complete": ritual_complete,
            "couple_discussion_message": (
                COUPLE_DISCUSSION_MESSAGE if ritual_complete else None
            ),
            "reward_message": self._reward_expression(warm_return),
            "current_turn_user_id": session.get("current_turn_user_id"),
            "turns": turns,
            "warm_return": warm_return,
            "warm_return_message": (
                "Welcome back — showing up again counts just as much as showing up daily."
                if warm_return else None
            ),
            "miss_encouragement": self.miss_encouragement_message(int(session.get("total_reconnects") or 0)),
            "cooldown_lock_until": (
                session["cooldown_lock_until"].isoformat()
                if session.get("cooldown_lock_until") else None
            ),
        }

    async def get_locked_turns(self, session_id: str, min_len: int = 0) -> List[Dict]:
        """Grounding reads — actual locked rows only (spec §8.3)."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM daily_reconnect_turn
                WHERE session_id = $1::uuid
                  AND char_length(content) >= $2
                ORDER BY created_at ASC
                """,
                session_id, min_len,
            )
        return [dict(r) for r in rows]

    # ── Telemetry ─────────────────────────────────────────────────────────

    async def _emit_event(
        self,
        session_id: Optional[str],
        family_id: Optional[str],
        event_type: str,
        detail: Dict,
    ) -> None:
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO daily_reconnect_event (session_id, family_id, event_type, detail)
                    VALUES ($1::uuid, $2, $3, $4::jsonb)
                    """,
                    session_id, family_id, event_type, json.dumps(detail),
                )
        except Exception as e:
            logger.warning("reconnect event insert failed: %s", e)
        _log(f"event {event_type} session={session_id} detail={detail}")

    # ── WebSocket registry ────────────────────────────────────────────────

    def _register_ws(self, session_id: str, username: str, ws: Any) -> None:
        self._ws_registry.setdefault(session_id, {})[username] = ws

    def _unregister_ws(self, session_id: str, username: str) -> None:
        self._ws_registry.get(session_id, {}).pop(username, None)

    async def _send(self, ws: Any, payload: Dict) -> None:
        try:
            await ws.send(json.dumps(payload, default=str))
        except Exception as e:
            _log(f"send failed: {e}")

    async def _broadcast(
        self, session_id: str, payload: Dict, exclude: Optional[str] = None
    ) -> None:
        for uid, ws in list(self._ws_registry.get(session_id, {}).items()):
            if exclude and uid == exclude:
                continue
            await self._send(ws, payload)


class _TonePicker:
    def __init__(self, leaning: str):
        self.leaning = leaning

    def pick(self, *, anxious: str, avoidant: str, default: str) -> str:
        if self.leaning == "anxious":
            return anxious
        if self.leaning == "avoidant":
            return avoidant
        return default
