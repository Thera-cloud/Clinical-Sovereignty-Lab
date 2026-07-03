"""
Training Ground ILM engine — QUANTUM-CRYSTAL-ARCH

Standalone coaching feature: consent, council CRUD, Inner Team dialogue, safety freeze.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.services.coaching_boundary_guard import TIER_COPY, evaluate as guard_evaluate
from app.services.training_ground_chat_context import build_training_ground_context
from app.services.training_ground_part_store import (
    CONSENT_VERSION,
    has_active_consent,
    insert_ilm_part,
)

logger = logging.getLogger("training_ground")

ENABLE_TRAINING_GROUND: bool = os.getenv(
    "ENABLE_TRAINING_GROUND", "false"
).lower() in ("true", "1", "yes")

LOG_PREFIX = ">>> [TRAINING_GROUND]"

CONSENT_TEXT = (
    "Training Ground is coaching support — not clinical therapy. "
    "Your coach can see council members you name and any safety freezes. "
    "Your mapping persists until you request erasure. "
    "Grounded in Schwartz (IFS mapping), Schulz von Thun (inner dialogue), "
    "and Jungian council language — Inner Leadership Mapping is Sovereign Sanctuary's integrative synthesis."
)

STATES = frozenset({
    "CONSENT", "AWARENESS", "COUNCIL_FORMATION", "SKILL_INTEGRATION",
    "TEAM_DIALOGUE", "SELF_ALIGNMENT", "FROZEN_SAFETY", "CLOSED",
})


def _log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrainingGroundEngine:
    def __init__(
        self,
        db_pool: Any,
        *,
        resolve_username_fn: Optional[Callable] = None,
        inference_fn: Optional[Callable] = None,
    ):
        self.db_pool = db_pool
        self._resolve_username = resolve_username_fn or self._default_resolve
        self._inference_fn = inference_fn

    async def _default_resolve(self, identifier: str) -> Optional[str]:
        from app.services._identity_resolver import resolve_username

        return await resolve_username(self.db_pool, identifier)

    async def handle_ws_message(
        self,
        msg_type: str,
        data: Dict[str, Any],
        ws: Any,
        profile: Dict[str, Any],
    ) -> None:
        if not ENABLE_TRAINING_GROUND:
            await self._send(ws, {"type": "ilm_error", "message": "feature_disabled"})
            return

        handlers = {
            "ilm_get_state": self._handle_get_state,
            "ilm_consent_ack": self._handle_consent_ack,
            "ilm_propose_member": self._handle_propose_member,
            "ilm_set_relationship": self._handle_set_relationship,
            "ilm_dialogue_turn": self._handle_dialogue_turn,
            "ilm_self_alignment": self._handle_self_alignment,
            "ilm_forward_to_coach": self._handle_forward_to_coach,
            "ilm_exit": self._handle_exit,
        }
        handler = handlers.get(msg_type)
        if not handler:
            await self._send(ws, {"type": "ilm_error", "message": "unknown_type"})
            return
        try:
            await handler(data, ws, profile)
        except Exception as exc:
            _log(f"handler {msg_type} error: {exc}")
            await self._send(ws, {"type": "ilm_error", "message": "internal_error"})

    async def _send(self, ws: Any, payload: Dict[str, Any]) -> None:
        await ws.send(json.dumps(payload))

    async def _username(self, profile: Dict[str, Any]) -> Optional[str]:
        raw = profile.get("username") or profile.get("hardware_id") or ""
        return await self._resolve_username(str(raw))

    async def _get_or_create_session(self, conn: Any, username: str) -> Dict[str, Any]:
        row = await conn.fetchrow(
            """
            SELECT id, state, exercise_mode, council_snapshot
              FROM training_ground_session
             WHERE user_id = $1 AND closed_at IS NULL
             ORDER BY created_at DESC
             LIMIT 1
            """,
            username,
        )
        if row:
            return dict(row)
        sid = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO training_ground_session (id, user_id, state)
            VALUES ($1, $2, 'CONSENT')
            """,
            sid,
            username,
        )
        return {"id": sid, "state": "CONSENT", "exercise_mode": None, "council_snapshot": []}

    async def _emit_event(
        self,
        conn: Any,
        session_id: Any,
        username: str,
        event_type: str,
        detail: Dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            INSERT INTO training_ground_event (session_id, user_id, event_type, detail)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            session_id,
            username,
            event_type,
            json.dumps(detail),
        )

    async def _council_rows(self, conn: Any, username: str) -> List[Any]:
        return await conn.fetch(
            """
            SELECT id, part_name, ilm_archetype_base, ifs_role, coaching_status,
                   activation_score, thera_world_template_id, description
              FROM user_parts_registry
             WHERE user_id = $1 AND origin = 'training_ground' AND is_active = TRUE
             ORDER BY part_name
            """,
            username,
        )

    async def _handle_get_state(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        if not username:
            await self._send(ws, {"type": "ilm_error", "message": "user_unresolved"})
            return

        async with self.db_pool.acquire() as conn:
            session = await self._get_or_create_session(conn, username)
            consent_row = await conn.fetchrow(
                """
                SELECT consented_at FROM training_ground_consent
                 WHERE user_id = $1 AND consent_version = $2 AND revoked_at IS NULL
                """,
                username,
                CONSENT_VERSION,
            )
            council = await self._council_rows(conn, username)

        await self._send(
            ws,
            {
                "type": "ilm_state",
                "session_id": str(session["id"]),
                "state": session["state"],
                "consent_required": consent_row is None,
                "consent_text": CONSENT_TEXT,
                "consent_version": CONSENT_VERSION,
                "council": [dict(c) for c in council],
            },
        )

    async def _handle_consent_ack(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        if not username:
            await self._send(ws, {"type": "ilm_error", "message": "user_unresolved"})
            return

        if not bool(data.get("accepted")):
            await self._send(ws, {"type": "ilm_consent_result", "accepted": False})
            return

        flags = (
            bool(data.get("acknowledged_non_clinical")),
            bool(data.get("acknowledged_coach_visibility")),
            bool(data.get("acknowledged_persistence")),
        )
        if not all(flags):
            await self._send(
                ws,
                {"type": "ilm_consent_result", "accepted": False, "reason": "all_required"},
            )
            return

        async with self.db_pool.acquire() as conn:
            session = await self._get_or_create_session(conn, username)
            await conn.execute(
                """
                INSERT INTO training_ground_consent (
                    user_id, consent_version,
                    acknowledged_non_clinical, acknowledged_coach_visibility,
                    acknowledged_persistence
                ) VALUES ($1, $2, TRUE, TRUE, TRUE)
                ON CONFLICT (user_id, consent_version) DO UPDATE
                   SET revoked_at = NULL,
                       acknowledged_non_clinical = TRUE,
                       acknowledged_coach_visibility = TRUE,
                       acknowledged_persistence = TRUE,
                       consented_at = NOW()
                """,
                username,
                CONSENT_VERSION,
            )
            await conn.execute(
                """
                UPDATE training_ground_session
                   SET state = 'AWARENESS', updated_at = NOW()
                 WHERE id = $1 AND state = 'CONSENT'
                """,
                session["id"],
            )
            await self._emit_event(
                conn, session["id"], username, "consent_ack", {"version": CONSENT_VERSION}
            )

        await self._send(ws, {"type": "ilm_consent_result", "accepted": True})

    async def _handle_propose_member(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        if not username:
            await self._send(ws, {"type": "ilm_error", "message": "user_unresolved"})
            return

        part_name = (data.get("part_name") or "").strip()
        if not part_name:
            await self._send(ws, {"type": "ilm_error", "message": "part_name_required"})
            return

        async with self.db_pool.acquire() as conn:
            result = await insert_ilm_part(
                conn,
                username=username,
                part_name=part_name,
                part_category=data.get("part_category") or "protector",
                description=data.get("description"),
                ilm_archetype_base=data.get("ilm_archetype_base"),
                ifs_role=data.get("ifs_role"),
                thera_world_template_id=data.get("thera_world_template_id"),
                activation_score=int(data.get("activation_score") or 0),
                created_by=username,
            )
            if not result.get("ok"):
                await self._send(ws, {"type": "ilm_propose_result", "ok": False, **result})
                return
            session = await self._get_or_create_session(conn, username)
            await conn.execute(
                """
                UPDATE training_ground_session
                   SET state = 'COUNCIL_FORMATION', updated_at = NOW()
                 WHERE id = $1 AND state IN ('AWARENESS', 'COUNCIL_FORMATION')
                """,
                session["id"],
            )
            await self._emit_event(
                conn,
                session["id"],
                username,
                "council_proposed",
                {"part_id": result["id"], "part_name": part_name},
            )

        await self._send(
            ws,
            {
                "type": "ilm_propose_result",
                "ok": True,
                "part_id": result["id"],
                "coaching_status": result["coaching_status"],
            },
        )

    async def _handle_set_relationship(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        if not username:
            await self._send(ws, {"type": "ilm_error", "message": "user_unresolved"})
            return

        if not await self._with_consent(username, ws):
            return

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_part_relationships (
                    user_id, source_part_id, target_part_id,
                    relationship_type, conflict_intensity, updated_at
                ) VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (user_id, source_part_id, target_part_id, relationship_type)
                DO UPDATE SET conflict_intensity = EXCLUDED.conflict_intensity,
                              updated_at = NOW()
                """,
                username,
                int(data.get("source_part_id")),
                int(data.get("target_part_id")),
                (data.get("relationship_type") or "conflict").strip(),
                max(0, min(10, int(data.get("conflict_intensity") or 0))),
            )

        await self._send(ws, {"type": "ilm_relationship_saved", "ok": True})

    async def _with_consent(self, username: str, ws: Any) -> bool:
        async with self.db_pool.acquire() as conn:
            if not await has_active_consent(conn, username):
                await self._send(ws, {"type": "ilm_error", "message": "consent_required"})
                return False
        return True

    async def _count_approved_parts(self, conn: Any, username: str) -> int:
        val = await conn.fetchval(
            """
            SELECT COUNT(*) FROM user_parts_registry
             WHERE user_id = $1 AND origin = 'training_ground'
               AND is_active = TRUE AND coaching_status = 'APPROVED'
            """,
            username,
        )
        return int(val or 0)

    async def _freeze_safety(
        self,
        conn: Any,
        *,
        session_id: Any,
        username: str,
        user_text: str,
        guard_result: Any,
    ) -> Dict[str, Any]:
        tier = guard_result.trip_class or "HYPO"
        summary = user_text[:500] if tier != "CRISIS" else None
        user_turn = user_text if tier == "CRISIS" else None
        payload = {
            "trigger_class": guard_result.trigger_class,
            "matched_labels": guard_result.matched_labels,
            "summary": summary,
            "label": "Training Ground — coaching boundary",
        }

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE training_ground_session
                   SET state = 'FROZEN_SAFETY', updated_at = NOW()
                 WHERE id = $1
                """,
                session_id,
            )
            await self._emit_event(
                conn,
                session_id,
                username,
                "safety_freeze",
                {"ticket_tier": tier, "trigger_class": guard_result.trigger_class},
            )
            ticket_id = await conn.fetchval(
                """
                INSERT INTO training_ground_progression_tickets (
                    session_id, user_id, ticket_tier, priority,
                    auto_generated, status, origin,
                    trigger_class, user_turn_text, payload_json
                ) VALUES (
                    $1, $2, $3, $4,
                    TRUE, 'open', 'training_ground',
                    $5, $6, $7::jsonb
                )
                RETURNING id
                """,
                session_id,
                username,
                tier,
                guard_result.priority,
                guard_result.trigger_class,
                user_turn,
                json.dumps(payload),
            )
            try:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (type, content, platform, created_at)
                    VALUES ('training_ground_crisis_freeze', $1, 'training_ground', NOW())
                    """,
                    json.dumps(
                        {
                            "user_id": username,
                            "ticket_id": str(ticket_id),
                            "ticket_tier": tier,
                            "trigger_class": guard_result.trigger_class,
                        }
                    ),
                )
            except Exception as exc:
                _log(f"skyeye_activity optional insert failed: {exc}")

        return {
            "ticket_id": str(ticket_id),
            "ticket_tier": tier,
            "state": "FROZEN_SAFETY",
            "message": TIER_COPY.get(tier, TIER_COPY["HYPO"]),
            "show_crisis_resources": guard_result.show_crisis_resources,
        }

    async def _handle_dialogue_turn(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        user_text = (data.get("text") or data.get("content") or "").strip()
        if not username or not user_text:
            await self._send(ws, {"type": "ilm_error", "message": "text_required"})
            return

        exercise_mode = data.get("exercise_mode") or "hearing"

        async with self.db_pool.acquire() as conn:
            if not await has_active_consent(conn, username):
                await self._send(ws, {"type": "ilm_error", "message": "consent_required"})
                return

            session = await self._get_or_create_session(conn, username)
            session_id = session["id"]
            if session["state"] == "FROZEN_SAFETY":
                await self._emit_event(
                    conn,
                    session_id,
                    username,
                    "dialogue_blocked",
                    {
                        "reason": "frozen_safety",
                        "exercise_mode": exercise_mode,
                        "user_preview": user_text[:300],
                    },
                )
                await self._send(
                    ws,
                    {"type": "ilm_dialogue_blocked", "reason": "frozen_safety", "state": "FROZEN_SAFETY"},
                )
                return

            guard = guard_evaluate(user_text)
            if guard.tripped:
                freeze = await self._freeze_safety(
                    conn,
                    session_id=session_id,
                    username=username,
                    user_text=user_text,
                    guard_result=guard,
                )
                await self._send(ws, {"type": "ilm_safety_freeze", **freeze})
                return

            if await self._count_approved_parts(conn, username) < 1:
                await self._emit_event(
                    conn,
                    session_id,
                    username,
                    "dialogue_blocked",
                    {
                        "reason": "pending_approval",
                        "exercise_mode": exercise_mode,
                        "user_preview": user_text[:300],
                    },
                )
                await self._send(
                    ws,
                    {
                        "type": "ilm_dialogue_blocked",
                        "reason": "pending_approval",
                        "message": "At least one council member must be coach-approved before dialogue exercises.",
                    },
                )
                return

            hold_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM user_parts_registry
                 WHERE user_id = $1 AND origin = 'training_ground'
                   AND is_active = TRUE AND coaching_status = 'HOLD'
                """,
                username,
            )
            if hold_count and int(hold_count) > 0:
                skill_text = (
                    "Your coach placed a hold on part of your council. "
                    "Let's practice stabilization skills before deeper dialogue."
                )
                await conn.execute(
                    """
                    UPDATE training_ground_session
                       SET state = 'SKILL_INTEGRATION', exercise_mode = $2, updated_at = NOW()
                     WHERE id = $1
                    """,
                    session_id,
                    exercise_mode,
                )
                await self._emit_event(
                    conn,
                    session_id,
                    username,
                    "dialogue_turn",
                    {
                        "outcome": "skill_integration",
                        "exercise_mode": exercise_mode,
                        "user_preview": user_text[:300],
                        "reply_len": len(skill_text),
                        "llm_used": False,
                    },
                )
                await self._send(
                    ws,
                    {
                        "type": "ilm_dialogue_response",
                        "state": "SKILL_INTEGRATION",
                        "text": skill_text,
                        "llm_used": False,
                    },
                )
                return

            await conn.execute(
                """
                UPDATE training_ground_session
                   SET state = 'TEAM_DIALOGUE', exercise_mode = $2, updated_at = NOW()
                 WHERE id = $1
                """,
                session_id,
                exercise_mode,
            )

        ctx = await build_training_ground_context(
            self.db_pool, username, exercise_mode=exercise_mode
        )
        reply, llm_used = await self._generate_reply(username, user_text, ctx)
        await self._maybe_crystallize(username, user_text, reply)

        async with self.db_pool.acquire() as conn:
            await self._emit_event(
                conn,
                session_id,
                username,
                "dialogue_turn",
                {
                    "outcome": "team_dialogue",
                    "exercise_mode": exercise_mode,
                    "user_preview": user_text[:300],
                    "reply_len": len(reply),
                    "llm_used": llm_used,
                },
            )

        await self._send(
            ws,
            {
                "type": "ilm_dialogue_response",
                "state": "TEAM_DIALOGUE",
                "text": reply,
                "llm_used": llm_used,
            },
        )

    async def _generate_reply(
        self, username: str, user_text: str, context: str
    ) -> tuple:
        fallback = (
            "I hear a part of you speaking. Let's stay with mapping and dialogue — "
            "what is this part trying to protect?"
        )
        if self._inference_fn:
            try:
                reply = await self._inference_fn(username, user_text, context)
                if reply and str(reply).strip():
                    return str(reply).strip(), True
            except Exception as exc:
                _log(f"inference failed: {exc}")
        return fallback, False

    async def _maybe_crystallize(self, username: str, user_text: str, reply: str) -> None:
        try:
            from app.websocket.crystal_recall_bridge import crystallize_from_conversation

            asyncio.create_task(
                crystallize_from_conversation(
                    self.db_pool,
                    username,
                    user_text,
                    reply,
                    user_name=username,
                    domain="coaching",
                    min_score=3,
                    origin_surface="training_ground",
                )
            )
        except Exception:
            pass

    async def _handle_self_alignment(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        statement = (data.get("statement") or "").strip()
        if not username or not statement:
            await self._send(ws, {"type": "ilm_error", "message": "statement_required"})
            return

        async with self.db_pool.acquire() as conn:
            session = await self._get_or_create_session(conn, username)
            await conn.execute(
                """
                UPDATE training_ground_session
                   SET state = 'SELF_ALIGNMENT', updated_at = NOW()
                 WHERE id = $1
                """,
                session["id"],
            )
            await self._emit_event(
                conn, session["id"], username, "self_alignment", {"statement_len": len(statement)}
            )

        await self._send(ws, {"type": "ilm_self_alignment_saved", "ok": True})

    async def _handle_forward_to_coach(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        if not username:
            await self._send(ws, {"type": "ilm_error", "message": "user_unresolved"})
            return

        note = (data.get("note") or "").strip()
        async with self.db_pool.acquire() as conn:
            session = await self._get_or_create_session(conn, username)
            ticket_id = await conn.fetchval(
                """
                INSERT INTO training_ground_progression_tickets (
                    session_id, user_id, ticket_tier, priority,
                    auto_generated, status, origin, payload_json
                ) VALUES (
                    $1, $2, 'MANUAL_FORWARD', 3,
                    FALSE, 'open', 'training_ground', $3::jsonb
                )
                RETURNING id
                """,
                session["id"],
                username,
                json.dumps({"note": note, "label": "Training Ground — coaching boundary"}),
            )

        await self._send(
            ws, {"type": "ilm_forward_result", "ok": True, "ticket_id": str(ticket_id)}
        )

    async def _handle_exit(
        self, data: Dict[str, Any], ws: Any, profile: Dict[str, Any]
    ) -> None:
        username = await self._username(profile)
        if not username:
            return

        session_id = data.get("session_id")
        async with self.db_pool.acquire() as conn:
            if session_id:
                await conn.execute(
                    """
                    UPDATE training_ground_session
                       SET state = 'CLOSED', closed_at = NOW(), updated_at = NOW()
                     WHERE id = $1 AND user_id = $2
                    """,
                    uuid.UUID(str(session_id)),
                    username,
                )
            else:
                await conn.execute(
                    """
                    UPDATE training_ground_session
                       SET state = 'CLOSED', closed_at = NOW(), updated_at = NOW()
                     WHERE user_id = $1 AND closed_at IS NULL
                    """,
                    username,
                )

        await self._send(ws, {"type": "ilm_exit_ack", "ok": True})
