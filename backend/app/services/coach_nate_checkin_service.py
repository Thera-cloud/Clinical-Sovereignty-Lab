"""Coach-requested Little Nate outbound check-in + callback verify.

# SOVEREIGN-VOICE
Billing defaults to platform (free for coaches) until
COACH_NATE_CHECKIN_BILLING_ENABLED=true.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.coach_nate_checkin")

ENABLE_COACH_NATE_CHECKIN = os.getenv(
    "ENABLE_COACH_NATE_CHECKIN", "true"
).strip().lower() in ("1", "true", "yes", "on")
BILLING_ENABLED = os.getenv(
    "COACH_NATE_CHECKIN_BILLING_ENABLED", "false"
).strip().lower() in ("1", "true", "yes", "on")
VOICE_RECHECK_S = int(os.getenv("COACH_NATE_CHECKIN_VOICE_RECHECK_S", "300"))
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
PUBLIC_API = os.getenv(
    "PUBLIC_API_BASE", "https://api.sovereignsanctuary.net"
).rstrip("/")
CHECKIN_TWIML = os.getenv(
    "TWILIO_CHECKIN_TWIML_URL",
    f"{PUBLIC_API}/api/calls/nate-checkin-twiml",
)
MEDIA_STREAM = os.getenv(
    "TWILIO_MEDIA_STREAM_URL",
    "wss://api.sovereignsanctuary.net/ws/nate-media-stream",
)
VERIFY_SID = os.getenv("TWILIO_VERIFY_SID", "")
COST_CENTS_PER_MIN = int(os.getenv("COACH_NATE_CHECKIN_COST_CENTS_PER_MIN", "5"))


def feature_enabled() -> bool:
    return ENABLE_COACH_NATE_CHECKIN


def billing_enabled() -> bool:
    return BILLING_ENABLED


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def normalize_e164(phone: str) -> str:
    d = _digits(phone)
    if not d:
        return ""
    if len(d) == 10:
        return f"+1{d}"
    if len(d) == 11 and d.startswith("1"):
        return f"+{d}"
    if phone.strip().startswith("+"):
        return f"+{d}"
    return f"+{d}"


COLD_PHI_RULES = """
IDENTITY & CONFIDENTIALITY (MANDATORY):
- Do NOT discuss clinical history, vault contents, crystals, family details,
  diagnoses, or sensitive profile data until confidential_unlocked is true.
- Until verified: warm check-in only — how they are, invite to talk, offer callback.
- If verification fails or voice match drops: return to reflection-only mode;
  use only what was said on THIS call as context. Never invent prior history.
- On callback: warm welcome; if ANI matches phone on file, soft-trust after confirm
  name; otherwise ask who is calling and trigger OTP before any private detail.
"""


def build_coach_checkin_prompt(
    *,
    client_name: str,
    coach_name: str,
    opening_line: str,
    confidential_unlocked: bool,
    verified: bool,
    is_callback: bool,
    number_match: bool = False,
) -> str:
    first = (client_name or "there").split()[0]
    mode = "CALLBACK" if is_callback else "OUTBOUND CHECK-IN"
    # SOVEREIGN-VOICE — matching dialed/ANI number counts as identity for memory
    unlock = "UNLOCKED" if (confidential_unlocked and verified) or number_match else "LOCKED"
    parts = [
        f"You are Little Nate on a phone {mode} at a coach's request.",
        f"Client first name: {first}. Coach: {coach_name or 'their coach'}.",
        f"Confidential memory access: {unlock}.",
        "",
        "OPENING:",
        f'- Prefer: "{opening_line}"' if opening_line else f"- Warm hello for {first}.",
        "",
        "BEHAVIOR:",
        "- This is a coach-requested check-in, not a cold sales call.",
        "- Keep turns short (1–3 sentences). No clinical jargon aloud.",
        "- If busy: respect and offer the callback number / app.",
        "- If distressed: hold gently; do not dump history while LOCKED.",
        "",
        "ABSOLUTE VOICE RULES (NEVER BREAK):",
        "- NEVER narrate reasoning aloud.",
        "- NEVER use clinical jargon with the caller.",
    ]
    if unlock == "UNLOCKED":
        parts.extend(
            [
                "",
                "NUMBER MATCH / MEMORY:",
                "- The phone number on this call matches the client's number on file "
                "(outbound dial to their number, or inbound ANI match).",
                "- Treat them as that client for memory and understanding.",
                "- Memory and hybrid continuity MAY be used warmly; still speak plainly.",
                "- If HYBRID RESUME or PRIOR SESSION MEMORY is present below, weigh those "
                "threads and let the caller choose what to continue.",
            ]
        )
    else:
        parts.extend(["", COLD_PHI_RULES])
    return "\n".join(parts)


class CoachNateCheckinService:
    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state

    async def _event(self, task_id: int, event_type: str, detail: Optional[dict] = None):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO coach_nate_checkin_events (task_id, event_type, detail)
                    VALUES ($1, $2, $3::jsonb)
                    """,
                    task_id,
                    event_type[:64],
                    json.dumps(detail or {}),
                )
        except Exception as e:
            logger.warning("checkin event log failed: %s", e)

    async def _update(self, task_id: int, **fields):
        if not self.db_pool or not fields:
            return
        cols = []
        vals: List[Any] = [task_id]
        i = 2
        for k, v in fields.items():
            cols.append(f"{k} = ${i}")
            vals.append(v)
            i += 1
        cols.append("updated_at = NOW()")
        sql = f"UPDATE coach_nate_checkin_tasks SET {', '.join(cols)} WHERE id = $1"
        async with self.db_pool.acquire() as conn:
            await conn.execute(sql, *vals)

    async def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        if not self.db_pool:
            return None
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM coach_nate_checkin_tasks WHERE id = $1", task_id
            )
        return dict(row) if row else None

    async def list_for_coach(
        self, coach_username: str, *, limit: int = 40
    ) -> List[Dict[str, Any]]:
        if not self.db_pool:
            return []
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM coach_nate_checkin_tasks
                WHERE coach_username = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                coach_username,
                limit,
            )
        return [dict(r) for r in rows]

    async def resolve_client(
        self, client_username: str, coach_username: str
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username, hardware_id, role, profile_data,
                       profile_data->>'name' AS name,
                       COALESCE(profile_data->>'phone', profile_data->>'phone_number') AS phone,
                       COALESCE(profile_data->>'coach_id', '') AS coach_id,
                       COALESCE(profile_data->>'assigned_coach', '') AS assigned_coach
                FROM users
                WHERE LOWER(username) = LOWER($1) AND role = 'CLIENT'
                LIMIT 1
                """,
                client_username,
            )
        if not row:
            return {"error": "client_not_found"}
        assigned = (row["assigned_coach"] or "").lower()
        if assigned and assigned != coach_username.lower() and coach_username.lower() != "drnevedal1":
            # soft allow if coach_id matches later; still require phone
            pass
        phone = normalize_e164(row["phone"] or "")
        if not phone:
            return {"error": "no_phone_on_file"}
        return {
            "username": row["username"],
            "hardware_id": row["hardware_id"],
            "name": row["name"] or row["username"],
            "phone": phone,
            "profile": row["profile_data"] if isinstance(row["profile_data"], dict) else {},
        }

    async def create_and_dial(
        self,
        *,
        coach_username: str,
        client_username: str,
        intent: str = "coach_checkin",
        note: str = "",
    ) -> Dict[str, Any]:
        if not feature_enabled():
            return {"status": "error", "error": "feature_disabled"}
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
            return {"status": "error", "error": "twilio_not_configured"}

        client = await self.resolve_client(client_username, coach_username)
        if client.get("error"):
            return {"status": "error", "error": client["error"]}

        # Billing preflight when flag on (platform absorbs when off)
        billed_to = "coach" if billing_enabled() else "platform"
        if billing_enabled():
            ok = await self._coach_has_credit(coach_username)
            if not ok:
                return {"status": "error", "error": "coach_insufficient_balance"}

        from app.services.nate_outbound_call import (
            prepare_checkin_context,
            generate_voicemail_audio,
        )

        ctx = await prepare_checkin_context(
            username=client["username"],
            phone=client["phone"],
            db_pool=self.db_pool,
            reason="coach_requested_checkin",
        )
        ctx.name = client["name"]

        call_id = uuid.uuid4()
        async with self.db_pool.acquire() as conn:
            task_id = await conn.fetchval(
                """
                INSERT INTO coach_nate_checkin_tasks (
                    coach_username, client_username, client_hardware_id,
                    client_phone_e164, status, intent, call_id, opening_line,
                    billed_to, metadata, verified, verify_method, confidential_unlocked
                ) VALUES ($1,$2,$3,$4,'queued',$5,$6,$7,$8,$9::jsonb,TRUE,'outbound_dialed',TRUE)
                RETURNING id
                """,
                coach_username,
                client["username"],
                client.get("hardware_id"),
                client["phone"],
                intent[:64],
                call_id,
                ctx.opening_line,
                billed_to,
                json.dumps({"note": (note or "")[:500]}),
            )

        await self._event(task_id, "created", {"coach": coach_username})

        # SOVEREIGN-VOICE — outbound dial to number-on-file = number match → memory OK
        warm_prompt = build_coach_checkin_prompt(
            client_name=client["name"],
            coach_name=coach_username,
            opening_line=ctx.opening_line,
            confidential_unlocked=True,
            verified=True,
            is_callback=False,
            number_match=True,
        )
        call_context = {
            "call_id": str(call_id),
            "username": client["username"],
            "name": client["name"],
            "phone": client["phone"],
            "to_number": client["phone"],
            "reason": "coach_requested_checkin",
            "is_nate_initiated": True,
            "coach_checkin_task_id": int(task_id),
            "coach_username": coach_username,
            "confidential_unlocked": True,
            "verified": True,
            "number_match": True,
            "verify_method": "outbound_dialed",
            "system_prompt": warm_prompt,
            "opening_line": ctx.opening_line,
        }
        await self._redis_set_json(f"nate:call_context:{call_id}", call_context, 3600)
        await self._redis_set_json(
            f"nate:coach_checkin_callback:{_digits(client['phone'])}",
            {"task_id": int(task_id), "call_id": str(call_id)},
            86400,
        )

        try:
            from twilio.rest import Client

            twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            status_url = f"{PUBLIC_API}/api/calls/nate-checkin-status?task_id={task_id}"
            twiml_url = f"{CHECKIN_TWIML}?call_id={call_id}&task_id={task_id}"
            call = twilio.calls.create(
                to=client["phone"],
                from_=TWILIO_PHONE_NUMBER,
                url=twiml_url,
                status_callback=status_url,
                status_callback_event=[
                    "initiated",
                    "ringing",
                    "answered",
                    "completed",
                    "busy",
                    "failed",
                    "no-answer",
                ],
                status_callback_method="POST",
                machine_detection="Enable",
                machine_detection_timeout=5,
            )
        except Exception as e:
            logger.warning("Twilio dial failed: %s", e)
            await self._update(
                task_id, status="failed", outcome="dial_failed", error_detail=str(e)[:300]
            )
            await self._event(task_id, "dial_failed", {"error": str(e)[:200]})
            await self._notify_coach(
                coach_username,
                task_id,
                "failed",
                f"Little Nate could not dial {client['name']}: {e}",
            )
            return {"status": "error", "error": "dial_failed", "task_id": task_id}

        await self._update(
            task_id, status="dialing", outbound_call_sid=call.sid
        )
        await self._event(task_id, "dialing", {"sid": call.sid})
        # Pre-synth voicemail audio optional (stored path skipped — Polly Say used)
        try:
            await generate_voicemail_audio(ctx)
        except Exception:
            pass

        return {
            "status": "ok",
            "task_id": int(task_id),
            "call_id": str(call_id),
            "call_sid": call.sid,
            "billed_to": billed_to,
            "billing_enabled": billing_enabled(),
            "client_phone_last4": client["phone"][-4:],
        }

    async def _coach_has_credit(self, coach_username: str) -> bool:
        """Placeholder wallet — always True until coach prepaid pool ships."""
        if not billing_enabled():
            return True
        # Future: check coach voice prepaid / org balance
        async with self.db_pool.acquire() as conn:
            bal = await conn.fetchval(
                """
                SELECT COALESCE((profile_data->>'coach_checkin_credit_cents')::int, 0)
                FROM users WHERE LOWER(username) = LOWER($1) AND role = 'COACH'
                LIMIT 1
                """,
                coach_username,
            )
        # Require prepaid credit when billing flag is on (no soft-open)
        return int(bal or 0) > 0

    async def apply_billing(self, task_id: int, duration_s: int) -> Dict[str, Any]:
        task = await self.get_task(task_id)
        if not task:
            return {"status": "skipped", "reason": "no_task"}
        minutes = max(1, (int(duration_s) + 59) // 60)
        cost = minutes * COST_CENTS_PER_MIN
        billed_to = "coach" if billing_enabled() else "platform"
        charged = False
        if billing_enabled() and billed_to == "coach":
            # Soft ledger only — no hard debit until credit wallet is live
            charged = False
        await self._update(
            task_id,
            billable_seconds=int(duration_s),
            twilio_cost_est_cents=cost,
            billed_to=billed_to,
            billing_charged=charged,
        )
        await self._event(
            task_id,
            "billing",
            {"seconds": duration_s, "cents": cost, "billed_to": billed_to, "charged": charged},
        )
        return {"status": "ok", "billed_to": billed_to, "cents": cost, "charged": charged}

    async def handle_status(
        self,
        *,
        task_id: int,
        call_sid: str,
        call_status: str,
        call_duration: str = "0",
        answered_by: str = "",
    ) -> Dict[str, Any]:
        task = await self.get_task(task_id)
        if not task:
            return {"status": "skipped", "reason": "no_task"}

        st = (call_status or "").lower()
        answered_by = (answered_by or "").lower()
        coach = task["coach_username"]
        name = task["client_username"]

        if st == "ringing":
            await self._update(task_id, status="ringing")
            return {"status": "ok"}

        if st == "in-progress" or st == "answered":
            await self._update(
                task_id,
                status="answered",
                answered_at=datetime.now(timezone.utc),
                outbound_call_sid=call_sid or task.get("outbound_call_sid"),
            )
            await self._event(task_id, "answered", {"answered_by": answered_by})
            return {"status": "ok"}

        if st in ("no-answer", "busy", "failed") or answered_by.startswith("machine"):
            await self._mark_voicemail(task_id, call_sid, reason=st or answered_by)
            await self._notify_coach(
                coach,
                task_id,
                "voicemail_left",
                f"Little Nate left a check-in message for {name} (or could not reach them). "
                f"Callback number: {TWILIO_PHONE_NUMBER}.",
            )
            return {"status": "ok", "outcome": "voicemail_left"}

        if st == "completed":
            dur = int(call_duration or 0)
            await self.apply_billing(task_id, dur)
            # If never answered and short, treat as VM path already handled
            if not task.get("answered_at") and dur < 5:
                if task.get("status") != "voicemail_left":
                    await self._mark_voicemail(task_id, call_sid, reason="completed_short")
                    await self._notify_coach(
                        coach,
                        task_id,
                        "voicemail_left",
                        f"Little Nate could not reach {name}; message / SMS fallback sent. "
                        f"Callback: {TWILIO_PHONE_NUMBER}.",
                    )
            else:
                await self._update(
                    task_id,
                    status="completed",
                    outcome=task.get("outcome") or "answered_talk",
                    completed_at=datetime.now(timezone.utc),
                )
                await self._notify_coach(
                    coach,
                    task_id,
                    "completed",
                    f"Little Nate finished the check-in with {name} "
                    f"(verified={bool(task.get('verified'))}, "
                    f"duration≈{dur}s).",
                )
            return {"status": "ok"}

        return {"status": "ok", "ignored": st}

    async def _mark_voicemail(self, task_id: int, call_sid: str, reason: str):
        await self._update(
            task_id,
            status="voicemail_left",
            outcome="voicemail_left",
            voicemail_left_at=datetime.now(timezone.utc),
            outbound_call_sid=call_sid or None,
            error_detail=(reason or "")[:200],
        )
        await self._event(task_id, "voicemail_left", {"reason": reason})
        task = await self.get_task(task_id)
        if task:
            await self._sms_callback_invite(task)

    async def _sms_callback_invite(self, task: Dict[str, Any]):
        phone = task.get("client_phone_e164") or ""
        if not phone:
            return
        first = (task.get("client_username") or "there").split()[0]
        body = (
            f"Hey {first}, it's Little Nate. Your coach asked me to check in. "
            f"I tried calling — please call me back at {TWILIO_PHONE_NUMBER} "
            f"when you can, or open the app. I'll verify it's you before we go deep."
        )
        try:
            from twilio.rest import Client

            Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
                to=phone, from_=TWILIO_PHONE_NUMBER, body=body
            )
            await self._event(int(task["id"]), "sms_callback_invite", {})
        except Exception as e:
            logger.warning("SMS callback invite failed: %s", e)

    async def resolve_inbound_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Match callback ANI to an open coach check-in task."""
        dig = _digits(phone)
        if not dig:
            return None
        cached = await self._redis_get_json(f"nate:coach_checkin_callback:{dig}")
        task_id = None
        if cached:
            task_id = int(cached.get("task_id") or 0) or None
        if not task_id and self.db_pool:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id FROM coach_nate_checkin_tasks
                    WHERE regexp_replace(client_phone_e164, '\\D', '', 'g') LIKE '%' || $1
                      AND status IN ('voicemail_left','callback_pending','answered','in_progress','dialing','ringing')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    dig[-10:],
                )
                if row:
                    task_id = int(row["id"])
        if not task_id:
            return None
        task = await self.get_task(task_id)
        if not task:
            return None
        # SOVEREIGN-VOICE — matching inbound ANI = number match → memory OK
        await self._update(
            task_id,
            status="callback_in_progress",
            verify_method="ani",
            verified=True,
            confidential_unlocked=True,
        )
        await self._event(task_id, "callback_ani_match", {"phone_last4": dig[-4:]})
        task = await self.get_task(task_id) or task
        await self._refresh_call_context_unlock(task)
        return task

    async def send_otp(self, task_id: int) -> Dict[str, Any]:
        task = await self.get_task(task_id)
        if not task:
            return {"status": "error", "error": "not_found"}
        phone = task.get("client_phone_e164") or ""
        if not phone or not VERIFY_SID:
            return {"status": "error", "error": "verify_unavailable"}
        try:
            from twilio.rest import Client

            Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).verify.v2.services(
                VERIFY_SID
            ).verifications.create(to=phone, channel="sms")
            await self._event(task_id, "otp_sent", {})
            return {"status": "ok"}
        except Exception as e:
            logger.warning("OTP send failed: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    async def confirm_otp(self, task_id: int, code: str) -> Dict[str, Any]:
        task = await self.get_task(task_id)
        if not task:
            return {"status": "error", "error": "not_found"}
        phone = task.get("client_phone_e164") or ""
        if not phone or not VERIFY_SID:
            return {"status": "error", "error": "verify_unavailable"}
        try:
            from twilio.rest import Client

            check = (
                Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                .verify.v2.services(VERIFY_SID)
                .verification_checks.create(to=phone, code=code)
            )
            if check.status != "approved":
                await self._event(task_id, "otp_failed", {})
                return {"status": "error", "error": "invalid_code"}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

        await self._update(
            task_id,
            verified=True,
            verify_method="otp",
            confidential_unlocked=True,
        )
        await self._event(task_id, "otp_verified", {})
        await self._refresh_call_context_unlock(task)
        await self._notify_coach(
            task["coach_username"],
            task_id,
            "verified",
            f"{task['client_username']} verified via SMS code on the check-in call.",
        )
        return {"status": "ok", "confidential_unlocked": True}

    async def unlock_after_voice_match(
        self, task_id: int, *, score: float, ok: bool
    ) -> Dict[str, Any]:
        task = await self.get_task(task_id)
        if not task:
            return {"status": "error", "error": "not_found"}
        now = datetime.now(timezone.utc)
        await self._update(
            task_id,
            voice_match_ok=ok,
            last_voice_check_at=now,
        )
        await self._event(
            task_id, "voice_recheck", {"score": score, "ok": ok}
        )
        if ok:
            # Voice alone + ANI soft-unlock; OTP still preferred for first unlock
            if task.get("verified") or task.get("verify_method") == "ani":
                await self._update(
                    task_id,
                    verified=True,
                    verify_method=task.get("verify_method") or "voiceprint",
                    confidential_unlocked=True,
                )
                await self._refresh_call_context_unlock(await self.get_task(task_id))
            return {"status": "ok", "ok": True}
        # Mismatch — lock confidential + send OTP
        await self._update(task_id, confidential_unlocked=False, verified=False)
        await self._refresh_call_context_unlock(await self.get_task(task_id), force_lock=True)
        await self.send_otp(task_id)
        await self._notify_coach(
            task["coach_username"],
            task_id,
            "voice_mismatch",
            f"Voice recheck failed for {task['client_username']}; "
            "Little Nate locked confidential content and sent a verification code.",
        )
        return {"status": "ok", "ok": False, "otp_sent": True}

    async def _refresh_call_context_unlock(
        self, task: Optional[Dict[str, Any]], force_lock: bool = False
    ):
        if not task:
            return
        cid = task.get("call_id")
        if not cid:
            return
        key = f"nate:call_context:{cid}"
        ctx = await self._redis_get_json(key) or {}
        unlocked = False if force_lock else bool(task.get("confidential_unlocked"))
        verified = False if force_lock else bool(task.get("verified"))
        ctx["confidential_unlocked"] = unlocked
        ctx["verified"] = verified
        ctx["number_match"] = unlocked or verified
        ctx["coach_checkin_task_id"] = int(task["id"])
        if task.get("client_phone_e164"):
            ctx["phone"] = task["client_phone_e164"]
            ctx["to_number"] = task["client_phone_e164"]
        ctx["system_prompt"] = build_coach_checkin_prompt(
            client_name=task.get("client_username") or "",
            coach_name=task.get("coach_username") or "",
            opening_line=task.get("opening_line") or "",
            confidential_unlocked=unlocked,
            verified=verified,
            is_callback=True,
            number_match=bool(unlocked or verified),
        )
        await self._redis_set_json(key, ctx, 3600)

    async def pipeline_bootstrap_prompt(self, ctx: Dict[str, Any]) -> Optional[str]:
        """Called from voice pipeline — return cold/warm prompt for coach check-in."""
        tid = ctx.get("coach_checkin_task_id")
        if not tid:
            return None
        task = await self.get_task(int(tid))
        if not task:
            return ctx.get("system_prompt")
        number_match = bool(
            ctx.get("number_match")
            or task.get("verify_method") in ("ani", "outbound_dialed", "voiceprint")
            or (task.get("confidential_unlocked") and task.get("verified"))
        )
        prompt = build_coach_checkin_prompt(
            client_name=ctx.get("name") or task.get("client_username") or "",
            coach_name=task.get("coach_username") or "",
            opening_line=task.get("opening_line") or ctx.get("opening_line") or "",
            confidential_unlocked=bool(task.get("confidential_unlocked")),
            verified=bool(task.get("verified")),
            is_callback=bool(ctx.get("is_callback")),
            number_match=number_match,
        )
        # SOVEREIGN-VOICE — inject hybrid + prior memory when number matches
        if number_match and self.db_pool:
            uname = (
                ctx.get("username")
                or task.get("client_username")
                or ""
            ).strip()
            if uname:
                try:
                    from app.services.twilio_grok_xtts_pipeline import (
                        _build_grounded_voice_prompt,
                    )

                    # Grounded prompt includes hybrid resume + recent chat/crystals
                    grounded, _ = await _build_grounded_voice_prompt(uname, self.db_pool)
                    if grounded:
                        prompt = f"{prompt}\n\n{grounded}"
                except Exception as e:
                    logger.warning("checkin memory inject failed: %s", e)
        return prompt

    async def maybe_start_voice_recheck(
        self, ctx: Dict[str, Any], call_sid: str, db_pool
    ) -> None:
        tid = ctx.get("coach_checkin_task_id")
        if not tid or not call_sid:
            return
        import asyncio

        asyncio.create_task(self._voice_recheck_loop(int(tid), call_sid, db_pool))

    async def _voice_recheck_loop(self, task_id: int, call_sid: str, db_pool):
        import asyncio

        await asyncio.sleep(max(60, VOICE_RECHECK_S))
        while True:
            task = await self.get_task(task_id)
            if not task or task.get("status") in ("completed", "failed", "cancelled"):
                return
            ok, score = await self._score_voice_match(task, call_sid, db_pool)
            await self.unlock_after_voice_match(task_id, score=score, ok=ok)
            await asyncio.sleep(max(60, VOICE_RECHECK_S))

    async def _score_voice_match(
        self, task: Dict[str, Any], call_sid: str, db_pool
    ) -> tuple:
        """Compare live greeting session vs enrollment; default ok if no profile."""
        try:
            from app.services.voice_enrollment_service import VoiceEnrollmentService

            svc = VoiceEnrollmentService(db_pool=db_pool)
            uid = task.get("client_username") or ""
            profile = await svc.load_profile(uid)
            if not profile.greeting_signatures:
                return True, 1.0  # no enrollment yet — do not block
            if call_sid not in getattr(svc, "_active_sessions", {}):
                svc.start_session(uid, call_sid)
            matches = svc.match_greeting(call_sid, [profile])
            if not matches:
                return True, 0.5
            best = float(matches[0].get("confidence") or matches[0].get("score") or 0)
            return best >= 0.55, best
        except Exception as e:
            logger.warning("voice recheck score failed: %s", e)
            return True, 0.0

    async def _notify_coach(
        self, coach_username: str, task_id: int, outcome: str, message: str
    ):
        try:
            from app.services.coach_notifications import notify_coach

            await notify_coach(
                self.db_pool,
                coach_username,
                {
                    "urgency": "medium" if outcome != "failed" else "high",
                    "subject": f"Nate check-in: {outcome}",
                    "message": message,
                    "payload": {
                        "source": "coach_nate_checkin",
                        "task_id": task_id,
                        "outcome": outcome,
                    },
                },
            )
            await self._event(task_id, "coach_notified", {"outcome": outcome})
        except Exception as e:
            logger.warning("coach notify failed: %s", e)

    async def _redis_set_json(self, key: str, data: dict, ttl: int):
        try:
            from app.services.api_server import _get_auth_redis

            redis = await _get_auth_redis()
            if redis:
                await redis.setex(key, ttl, json.dumps(data, default=str))
        except Exception as e:
            logger.debug("redis set %s: %s", key, e)

    async def _redis_get_json(self, key: str) -> Optional[dict]:
        try:
            from app.services.api_server import _get_auth_redis

            redis = await _get_auth_redis()
            if not redis:
                return None
            raw = await redis.get(key)
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode()
            return json.loads(raw)
        except Exception:
            return None


def twiml_connect_stream(
    call_id: str,
    task_id: int,
    *,
    answered_by: str = "",
    username: str = "",
    phone: str = "",
) -> str:
    """Build TwiML: machine → Say VM; human → media stream."""
    ab = (answered_by or "").lower()
    if ab.startswith("machine") or ab == "fax":
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">Hi, this is Little Nate calling to check in at your coach's request.
  Please call me back at {TWILIO_PHONE_NUMBER} when you can. Take care.</Say>
  <Hangup/>
</Response>"""
    # Escape XML attr values minimally
    def _x(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
        )

    u = _x(username)
    p = _x(phone)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{MEDIA_STREAM}">
      <Parameter name="call_id" value="{_x(call_id)}" />
      <Parameter name="coach_checkin_task_id" value="{int(task_id) if task_id else 0}" />
      <Parameter name="is_nate_initiated" value="true" />
      <Parameter name="username" value="{u}" />
      <Parameter name="phone" value="{p}" />
      <Parameter name="to_number" value="{p}" />
      <Parameter name="number_match" value="true" />
    </Stream>
  </Connect>
</Response>"""
