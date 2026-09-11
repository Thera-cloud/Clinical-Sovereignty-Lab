"""ThriveCoachAgent — life-coach cadence for the growth phases. QUANTUM-CRYSTAL-ARCH.

Background agent (30-min tick, same shape as ``nate_checkin_agent``). Email
only (user decision). Four jobs per tick, each idempotent and independently
guarded:

1. **Practice reminders** — ``client_focus_areas`` rows past ``next_due_at``.
   One email per practice per due window; logged to ``thrive_reminders``.
2. **Goal checkpoints** — active ``nate_commitments`` goals: 7-day checkpoint
   nudges and a due-in-3-days heads-up.
3. **Weekly recap** — once per client per 7 days when they hold any active
   practice or goal: streaks, completions, goal progress, one core question.
4. **Phase evaluation** — ``phase_resolver.evaluate`` at most once per 24 h
   per recently-active client (auto-promotion + coach notify live there).

Respects: safe_silence_mode (active) → no email; ``checkin_snooze_until``;
``notification_prefs.email == false``; missing email → in-app nudge only.
Flag: ``ENABLE_GROWTH_PHASE`` (agent runs but sends nothing when off).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.services.thrive import practice_catalog as pc
from app.services.thrive import practice_tracker as pt
from app.services.thrive import phase_resolver as pr
from app.services.thrive import growth_phase as gp

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30 * 60
STAGGER_DELAY = int(os.getenv("THRIVE_AGENT_STAGGER_S", "205"))
APP_LINK = os.getenv("THRIVE_DEEP_LINK", "https://app.sovereignsanctuary.net")
REPLY_TO = "thrive@reply.sovereignsanctuary.net"
MAX_EMAILS_PER_TICK = int(os.getenv("THRIVE_MAX_EMAILS_PER_TICK", "60"))
MAX_EVALS_PER_TICK = int(os.getenv("THRIVE_MAX_EVALS_PER_TICK", "40"))
QUIET_HOURS = (22, 7)  # local: no reminder email between 22:00 and 07:00

# Client-facing one-liners per phase (never the internal ln_register text).
CLIENT_VOICE = {
    gp.STABILIZE: "steadying the ground under your feet, one day at a time.",
    gp.PROCESS: "staying close to what's real for you, at your pace.",
    gp.CONSOLIDATE: "gathering what you've learned and letting it settle into who you are now.",
    gp.THRIVE: "building what you want from here — goals, strengths, the good you're already making.",
    gp.GENERATIVE: "using what you've lived through to shape your life and the people you care about.",
}

CORE_QUESTIONS = (
    "What do you want to build now?",
    "Which goal matters most this week?",
    "What have you already completed that you haven't given yourself credit for?",
    "What is one thing you can complete today?",
)


def _enabled() -> bool:
    return os.getenv("ENABLE_GROWTH_PHASE", "false").lower() in ("1", "true", "yes")


def _json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


class ThriveCoachAgent:
    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notification_system = notification_system
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_tick_at: Optional[datetime] = None
        self.last_tick_stats: Dict[str, int] = {}

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ThriveCoachAgent started (every 30min, stagger %ds, enabled=%s)", STAGGER_DELAY, _enabled())

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ThriveCoachAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("ThriveCoachAgent tick failed: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def tick(self) -> Dict[str, int]:
        stats = {"practice_reminders": 0, "goal_nudges": 0, "recaps": 0, "evaluations": 0, "promotions": 0, "skipped": 0}
        if not self.db_pool:
            return stats
        budget = {"emails": MAX_EMAILS_PER_TICK}
        for job in (self._practice_reminders, self._goal_checkpoints, self._weekly_recaps, self._phase_evaluations):
            try:
                await job(stats, budget)
            except Exception as e:
                logger.warning("ThriveCoachAgent: %s failed: %s", job.__name__, e)
        self.last_tick_at = datetime.now(timezone.utc)
        self.last_tick_stats = stats
        if any(stats.values()):
            logger.info("ThriveCoachAgent tick: %s", stats)
        return stats

    # ── recipient resolution + gates ───────────────────────────────────

    async def _recipient(self, username: str) -> Optional[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, hardware_id, profile_data, role FROM users WHERE username = $1", username
            )
        if not row or row["role"] != "CLIENT":
            return None
        prof = _json(row["profile_data"])
        email = (prof.get("email") or "").strip()
        tz = prof.get("timezone") or prof.get("time_zone") or "UTC"
        now = datetime.now(timezone.utc)
        blocked = None
        ss = _json(prof.get("safe_silence_mode_state"))
        if ss.get("state") == "active":
            blocked = "safe_silence"
        snooze = prof.get("checkin_snooze_until")
        if snooze:
            try:
                sdt = datetime.fromisoformat(str(snooze).replace("Z", "+00:00"))
                if sdt.tzinfo is None:
                    sdt = sdt.replace(tzinfo=timezone.utc)
                if now < sdt:
                    blocked = blocked or "snoozed"
            except Exception:
                pass
        prefs = _json(prof.get("notification_prefs"))
        if prefs.get("email") is False or prefs.get("thrive_email") is False:
            blocked = blocked or "email_opt_out"
        try:
            local_hour = now.astimezone(ZoneInfo(tz)).hour
        except Exception:
            local_hour = now.hour
        quiet = local_hour >= QUIET_HOURS[0] or local_hour < QUIET_HOURS[1]
        return {
            "id": row["id"], "hardware_id": row["hardware_id"], "email": email,
            "name": (prof.get("name") or username).split()[0], "tz": tz, "blocked": blocked, "quiet": quiet,
            "local_hour": local_hour,
        }

    async def _already_sent(self, username: str, reminder_type: str, *, hours: int, practice_key: Optional[str] = None,
                            commitment_id: Optional[str] = None) -> bool:
        async with self.db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM thrive_reminders
                WHERE username = $1 AND reminder_type = $2 AND sent_at >= NOW() - ($3 || ' hours')::interval
                  AND ($4::text IS NULL OR practice_key = $4)
                  AND ($5::uuid IS NULL OR commitment_id = $5::uuid)
                """,
                username, reminder_type, str(hours), practice_key, commitment_id,
            )
        return bool(n)

    async def _send(self, username: str, rcpt: Dict[str, Any], *, reminder_type: str, subject: str, html: str,
                    practice_key: Optional[str] = None, commitment_id: Optional[str] = None,
                    nudge_title: Optional[str] = None, nudge_body: Optional[str] = None,
                    metadata: Optional[Dict[str, Any]] = None, budget: Optional[Dict[str, int]] = None) -> Optional[str]:
        """Email (if allowed) + in-app nudge + thrive_reminders row. Returns channel."""
        channel = None
        if _enabled() and rcpt["email"] and not rcpt["blocked"] and self.notification_system and (budget is None or budget["emails"] > 0):
            try:
                ok = await self.notification_system._send_email(
                    rcpt["email"], subject, html, notification_type=f"thrive_{reminder_type}", reply_to=REPLY_TO,
                )
                if ok:
                    channel = "email"
                    if budget is not None:
                        budget["emails"] -= 1
            except Exception as e:
                logger.warning("ThriveCoachAgent: email failed for %s: %s", username, e)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO nate_nudges (user_id, nudge_type, title, content, metadata, scheduled_at)
                    VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
                    """,
                    rcpt["id"], f"thrive_{reminder_type}", (nudge_title or subject)[:256],
                    nudge_body or subject, json.dumps({"practice_key": practice_key, "commitment_id": commitment_id}),
                )
                await conn.execute(
                    """
                    INSERT INTO thrive_reminders (username, practice_key, commitment_id, reminder_type, channel, subject, metadata)
                    VALUES ($1, $2, $3::uuid, $4, $5, $6, $7::jsonb)
                    """,
                    username, practice_key, commitment_id, reminder_type, channel or ("blocked:" + (rcpt["blocked"] or "no_email")),
                    subject[:256], json.dumps(metadata or {}, default=str),
                )
        except Exception as e:
            logger.warning("ThriveCoachAgent: reminder log failed for %s: %s", username, e)
        return channel

    # ── job 1: practice reminders ──────────────────────────────────────

    async def _practice_reminders(self, stats: Dict[str, int], budget: Dict[str, int]) -> None:
        due = await pt.due_practices(self.db_pool, min_gap_hours=20)
        for row in due:
            rcpt = await self._recipient(row.username)
            if not rcpt:
                continue
            if rcpt["quiet"] and row.time_of_day != "late_night":
                stats["skipped"] += 1
                continue
            practice = pc.PRACTICES.get(row.practice_key)
            if not practice:
                continue
            subject = practice.reminder_subject
            streak_line = f"You're on a {row.streak}-day streak — {self._streak_word(row.streak)}." if row.streak >= 2 else ""
            html = self._email(
                rcpt["name"],
                [
                    practice.reminder_line,
                    streak_line,
                    "Reply to this email with what came up — I'll keep it in your record so we can build on it next time we talk.",
                ],
                cta="Open Sovereign Sanctuary",
                tag=f"[#tgt:{practice.key}]",
            )
            await self._send(
                row.username, rcpt, reminder_type="practice_due", subject=f"{subject} {self._tag(practice.key)}",
                html=html, practice_key=practice.key,
                nudge_title=practice.label, nudge_body=practice.reminder_line,
                metadata={"streak": row.streak, "cadence": row.cadence}, budget=budget,
            )
            await pt.mark_reminded(self.db_pool, row.username, row.practice_key)
            stats["practice_reminders"] += 1
            if row.streak in (7, 21, 30, 60, 100) and not await self._already_sent(row.username, "streak_celebration", hours=48, practice_key=row.practice_key):
                await self._send(
                    row.username, rcpt, reminder_type="streak_celebration",
                    subject=f"{row.streak} days of {practice.label} — that's you",
                    html=self._email(rcpt["name"], [
                        f"{row.streak} days in a row of {practice.label}. Nobody did that for you — you built it.",
                        "What has it changed, even a little? Reply and tell me; I'd love to hear it in your words.",
                    ], cta="Open Sovereign Sanctuary"),
                    practice_key=practice.key, metadata={"streak": row.streak}, budget=budget,
                )

    # ── job 2: goal checkpoints ────────────────────────────────────────

    async def _goal_checkpoints(self, stats: Dict[str, int], budget: Dict[str, int]) -> None:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, commitment_text, focus_area, target_date, started_at, created_at,
                       progress_pct, last_touched_at
                FROM nate_commitments
                WHERE status = 'active' AND coached_by IS NOT NULL
                  AND commitment_type IN ('practice_goal', 'milestone', 'custom')
                ORDER BY target_date NULLS LAST
                LIMIT 300
                """
            )
        now = datetime.now(timezone.utc)
        for r in rows:
            username = r["user_id"]
            gid = str(r["id"])
            target = r["target_date"]
            started = r["started_at"] or r["created_at"]
            due_soon = target and timedelta(0) <= (target - now) <= timedelta(days=3)
            checkpoint = (now - started) >= timedelta(days=7) and (
                r["last_touched_at"] is None or (now - r["last_touched_at"]) >= timedelta(days=7)
            )
            if not (due_soon or checkpoint):
                continue
            rtype = "goal_due" if due_soon else "goal_checkpoint"
            if await self._already_sent(username, rtype, hours=72 if due_soon else 24 * 6, commitment_id=gid):
                continue
            rcpt = await self._recipient(username)
            if not rcpt or rcpt["quiet"]:
                stats["skipped"] += 1
                continue
            pct = float(r["progress_pct"] or 0)
            if due_soon:
                lines = [
                    f"Your goal — “{r['commitment_text']}” — comes due {target.strftime('%A, %b %-d')}.",
                    f"You're at {pct:.0f}%. " + ("Close it out — what's the last piece?" if pct >= 60 else "What can you complete today that moves it?"),
                ]
                subject = f"3 days left: {r['commitment_text'][:48]}"
            else:
                q = CORE_QUESTIONS[int(now.timestamp() // 86400) % len(CORE_QUESTIONS)]
                lines = [
                    f"Weekly checkpoint on “{r['commitment_text']}” — you're at {pct:.0f}%.",
                    q,
                    "Reply with a number 0–100 for where you honestly are, and one sentence on what's next.",
                ]
                subject = f"Checkpoint: {r['commitment_text'][:48]}"
            await self._send(
                username, rcpt, reminder_type=rtype, subject=f"{subject} {self._tag('goal:' + gid[:8])}",
                html=self._email(rcpt["name"], lines, cta="Open Sovereign Sanctuary"),
                commitment_id=gid, nudge_title="Goal checkpoint", nudge_body=lines[0],
                metadata={"progress_pct": pct}, budget=budget,
            )
            stats["goal_nudges"] += 1

    # ── job 3: weekly recap ────────────────────────────────────────────

    async def _weekly_recaps(self, stats: Dict[str, int], budget: Dict[str, int]) -> None:
        async with self.db_pool.acquire() as conn:
            users = await conn.fetch(
                """
                SELECT DISTINCT username FROM (
                    SELECT username FROM client_focus_areas WHERE active
                    UNION
                    SELECT user_id AS username FROM nate_commitments WHERE status = 'active' AND coached_by IS NOT NULL
                ) u
                WHERE NOT EXISTS (
                    SELECT 1 FROM thrive_reminders t
                    WHERE t.username = u.username AND t.reminder_type = 'weekly_recap'
                      AND t.sent_at >= NOW() - interval '6 days 20 hours'
                )
                LIMIT 100
                """
            )
        for u in users:
            username = u["username"]
            rcpt = await self._recipient(username)
            if not rcpt:
                continue
            # Recap lands Sunday–Monday local, daytime.
            local_wd = datetime.now(timezone.utc).astimezone(ZoneInfo(rcpt["tz"]) if rcpt["tz"] else timezone.utc).weekday()
            if local_wd not in (6, 0) or rcpt["quiet"]:
                continue
            fs = await pt.focus_state(self.db_pool, username)
            async with self.db_pool.acquire() as conn:
                completions = await conn.fetchval(
                    "SELECT COUNT(*) FROM client_practice_log WHERE username = $1 AND completed_at >= NOW() - interval '7 days'",
                    username,
                )
            phase = await pr.get_phase(self.db_pool, username)
            fw = gp.framework_for(phase.phase)
            lines = [f"Your week, {rcpt['name']}:"]
            if fs["areas"]:
                lines.append(f"{completions} practice{'s' if completions != 1 else ''} completed; best streak {fs['best_streak']} days.")
            for g in fs["goals_active"][:3]:
                tr = " — on track" if g.get("on_track") else (" — needs a push" if g.get("on_track") is False else "")
                lines.append(f"Goal: {g['text']} ({g['progress_pct']:.0f}%){tr}")
            for g in fs["goals_completed"][:2]:
                lines.append(f"Completed: {g['text']}.")
            _voice = CLIENT_VOICE.get(phase.phase, "")
            lines.append(f"Where we are: {fw.label} — {_voice}")
            lines.append(CORE_QUESTIONS[2] + " " + CORE_QUESTIONS[0])
            await self._send(
                username, rcpt, reminder_type="weekly_recap", subject=f"Your week with Little Nate {self._tag('recap')}",
                html=self._email(rcpt["name"], lines[1:], cta="Open Sovereign Sanctuary", heading=lines[0]),
                nudge_title="Your weekly recap", nudge_body=lines[1] if len(lines) > 1 else lines[0],
                metadata={"completions": completions, "phase": phase.phase}, budget=budget,
            )
            stats["recaps"] += 1

    # ── job 4: phase evaluation ────────────────────────────────────────

    async def _phase_evaluations(self, stats: Dict[str, int], budget: Dict[str, int]) -> None:
        if not _enabled():
            return
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.username, u.hardware_id
                FROM users u
                LEFT JOIN client_growth_phase g ON g.username = u.username
                WHERE u.role = 'CLIENT'
                  AND (g.last_evaluated IS NULL OR g.last_evaluated < NOW() - interval '24 hours')
                  AND EXISTS (
                      SELECT 1 FROM conversation_history ch
                      WHERE (ch.user_id = u.username OR ch.user_id = u.hardware_id)
                        AND ch.created_at >= NOW() - interval '14 days'
                  )
                ORDER BY g.last_evaluated NULLS FIRST
                LIMIT $1
                """,
                MAX_EVALS_PER_TICK,
            )
        notifier = self._coach_email_notifier()
        for r in rows:
            try:
                state, transition, _sig = await pr.evaluate(
                    self.db_pool, r["username"], hardware_id=r["hardware_id"], notifier=notifier,
                )
                stats["evaluations"] += 1
                if transition:
                    stats["promotions"] += 1
                    await self._phase_email(r["username"], transition, budget)
            except Exception as e:
                logger.warning("ThriveCoachAgent: evaluate failed for %s: %s", r["username"], e)

    def _coach_email_notifier(self):
        ns = self.notification_system

        async def _notify(coach_username: str, subject: str, body: str, meta: Dict[str, Any]) -> None:
            email = (meta or {}).get("coach_email")
            if not (ns and email):
                return
            html = f"<div style=\"font-family:'DM Sans',sans-serif;color:#e2e8f0;line-height:1.6\"><p>{body}</p>" \
                   f"<p>Open Coach Command to review the phase badge, override if needed, and see the client's goal trajectories.</p></div>"
            await ns._send_email(email, subject, html, notification_type="thrive_phase_promoted")

        return _notify

    async def _phase_email(self, username: str, t: pr.Transition, budget: Dict[str, int]) -> None:
        rcpt = await self._recipient(username)
        if not rcpt:
            return
        fw = gp.framework_for(t.to_phase)
        forward = gp.PHASE_INDEX.get(t.to_phase, 0) > gp.PHASE_INDEX.get(t.from_phase, 0)
        _voice = CLIENT_VOICE.get(t.to_phase, "")
        if forward:
            lines = [
                f"I've been watching how you talk about your life lately — and something has shifted. You're carrying less and building more.",
                f"So I'm shifting with you. Our conversations will lean into {fw.label.lower()}: {_voice}",
                "If anything old surfaces and you want to go back into it, just say so — I'll be right there with you.",
                CORE_QUESTIONS[0],
            ]
            subject = "Something has shifted — and I'm shifting with you"
        else:
            lines = [
                "I've noticed the last stretch has been heavier. That isn't going backwards — it's the work asking for a little more room.",
                f"I'll slow the pace and stay closer to what's here: {_voice}",
                "Whenever you're ready, I'm here.",
            ]
            subject = "Making a little more room"
        await self._send(
            username, rcpt, reminder_type="phase_promoted", subject=f"{subject} {self._tag('phase')}",
            html=self._email(rcpt["name"], lines, cta="Talk with Little Nate"),
            nudge_title=subject, nudge_body=lines[0], metadata={"from": t.from_phase, "to": t.to_phase}, budget=budget,
        )

    # ── email rendering ────────────────────────────────────────────────

    @staticmethod
    def _tag(key: str) -> str:
        return f"[#tgt:{key}]"

    @staticmethod
    def _streak_word(n: int) -> str:
        if n >= 30:
            return "that's a way of life now"
        if n >= 14:
            return "this is becoming who you are"
        if n >= 7:
            return "a full week of showing up"
        return "keep it alive"

    @staticmethod
    def _email(name: str, lines: List[str], *, cta: str, tag: str = "", heading: Optional[str] = None) -> str:
        body = "".join(f"<p>{ln}</p>" for ln in lines if ln)
        head = f"<p>{heading}</p>" if heading else f"<p>Hi {name},</p>"
        return f"""
        <div style="font-family: 'DM Sans', sans-serif; color: #e2e8f0; line-height: 1.6;">
            {head}
            {body}
            <p style="text-align: center; margin: 24px 0;">
                <a href="{APP_LINK}"
                   style="background: linear-gradient(135deg, #C9A962, #8B7355);
                          color: #050505; padding: 14px 32px; border-radius: 8px;
                          text-decoration: none; font-weight: 600; font-size: 16px;">
                    {cta}
                </a>
            </p>
            <p style="color:#8B7355;font-size:13px;">Reply to this email and I'll keep it. Reply “pause” to rest reminders for a week. {tag}</p>
            <p>With you,<br>Little Nate</p>
        </div>
        """
