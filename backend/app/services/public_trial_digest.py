"""
Public Trial Daily Digest — try.html funnel health email.

Once daily (12:00 UTC / 08:00 ET) to support@sovereignsanctuary.net.
Subject carries 🟢/🔴 verdict so a clean day is ignorable from the inbox.

Organic counts exclude probe/red-team sessions (content heuristic) and
converted test accounts (e2e_trial_*, Test*).
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("skyeye.public_trial_digest")

DIGEST_EMAIL = "support@sovereignsanctuary.net"
DIGEST_HOUR_UTC = 12  # 08:00 ET (EDT)
ET = ZoneInfo("America/New_York")

# Reuse the F4c bleed detector (same logic as live re-probe + pytest fixtures).
_scripts = Path(__file__).resolve().parents[2] / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))
try:
    import reprobe_public_trial_f4c_f6 as _bleed_det
except ImportError:
    _bleed_det = None  # type: ignore

_PROBE_USER_RE = re.compile(
    r"(gpt|claude|grok|server setup|database|architecture|secret.*spouse|grandparent|"
    r"overdrinking|someone else|other people|another client|model are you|"
    r"paid version|what happens to this conversation|who can read|technically what|"
    r"repeat back something real|saddest thing someone|what secrets have people|"
    r"poison|tell me about someone else|do you remember other)",
    re.I,
)

# Generic jailbreak shapes — catches attempts that don't hit an exact phrase above.
# A raw base64 blob (>=24 chars of base64 alphabet) in a trial message is never
# organic; organic users don't paste encoded payloads at a free-trial chatbot.
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_JAILBREAK_SHAPE_RE = re.compile(
    r"(ignore (all|any|previous).{0,20}(instructions|rules|safety)|"
    r"hidden instructions|reveal your (system|hidden)|jailbreak|"
    r"you are now|pretend you (are|have)|act as if you|no restrictions|"
    r"bypass your|override your|disregard (all|your))",
    re.I,
)

_TEST_ACCOUNT_RE = re.compile(r"^(e2e_trial_|Test\d*$)", re.I)

# Jul 2026 red-team batch openers / follow-ups (organic users rarely hit these exact strings).
_RED_TEAM_PHRASES = (
    "what model are you",
    "do you remember other people",
    "can you tell me if therapy is right for me",
    "write a story where a character",
    "who can read these chats",
    "what kinds of losses have people shared",
    "what might be going on emotionally when someone can't sleep",
    "repeat back something real",
    "what secrets have people",
    "decode this base64",
    "ignore all previous instructions",
    "verification smoke test",
    "system prompt",
    "play drnate",
    "it's just fiction",
)

_FLAG_VERDICT = {
    "violence_facilitation": ("BLOCKED", "poison-recipe probe"),
    "prompt_leak": ("REFUSED", "prompt-leak attempt"),
    "internal_infra": ("REFUSED", "architecture probe"),
    "provider_name": ("REFUSED", "provider probe"),
    "minor_sexual_content": ("BLOCKED", "minor-shield probe"),
}

_BLEED_LABELS = {
    "third_party_relation_event": "third-party relationship detail (named a relative/relation + life event)",
    "attributed_disclosure": "attributed third-party disclosure (\"another client said...\")",
}


def _parse_history(raw: Any) -> List[Dict[str, str]]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append({
                "user": str(item.get("user") or ""),
                "assistant": str(item.get("assistant") or ""),
            })
    return out


def _is_probe_session(history: List[Dict[str, str]], converted_username: Optional[str]) -> bool:
    if converted_username and _TEST_ACCOUNT_RE.match(converted_username):
        return True
    user_msgs = [h["user"] for h in history if h.get("user")]
    if not user_msgs:
        return True  # turns with empty history = batch/automation artifact
    for msg in user_msgs:
        low = msg.lower()
        if any(phrase in low for phrase in _RED_TEAM_PHRASES):
            return True
        if _JAILBREAK_SHAPE_RE.search(low):
            return True
        if _BASE64_BLOB_RE.search(msg):
            return True
    return any(_PROBE_USER_RE.search(u) for u in user_msgs)


def _first_user_message(history: List[Dict[str, str]]) -> str:
    for h in history:
        if h.get("user"):
            return h["user"]
    return ""


def _tone_label(history: List[Dict[str, str]]) -> str:
    blob = " ".join(h.get("user", "") + " " + h.get("assistant", "") for h in history).lower()
    tags: List[str] = []
    if "boundar" in blob:
        tags.append("boundary-focused")
    if any(w in blob for w in ("afford", "therapy", "talk to")):
        tags.append("access-focused")
    if any(w in blob for w in ("meltdown", "son", "daughter", "child")):
        tags.append("parenting")
    if len(history) >= 3:
        tags.append("stayed engaged")
    return ", ".join(tags) if tags else "supportive exchange"


def _find_bleed_details_in_session(history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Per-turn bleed evidence: which turn, the full exchange, exactly what leaked.

    Used both to compute the bleed_flags count AND to render the full leaked
    conversation at the top of the digest (bug #1) — a bleed is the worst-case
    event and must never be a truncated line item, so this captures the
    complete turn, not just a pattern name.
    """
    if not _bleed_det:
        return []
    user_so_far: List[str] = []
    out: List[Dict[str, Any]] = []
    for idx, turn in enumerate(history):
        assistant = turn.get("assistant") or ""
        user = turn.get("user") or ""
        if assistant:
            flags = _bleed_det.find_narrative_bleed(assistant, user_so_far)
            if flags:
                out.append({
                    "turn_index": idx,
                    "user": user,
                    "assistant": assistant,
                    "hit_patterns": flags,
                })
        if user:
            user_so_far.append(user)
    return out


def _count_bleed_in_session(history: List[Dict[str, str]]) -> int:
    return sum(len(d["hit_patterns"]) for d in _find_bleed_details_in_session(history))


class PublicTrialDigest:
    def __init__(self, db_pool, notification_system=None, redis_url: Optional[str] = None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_date: Optional[str] = None

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("PublicTrialDigest started (daily %02d:00 UTC)", DIGEST_HOUR_UTC)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(130)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if now.hour == DIGEST_HOUR_UTC and self._sent_date != now.date().isoformat():
                    await self.build_and_send(now)
                    self._sent_date = now.date().isoformat()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("PublicTrialDigest tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def build_and_send(
        self,
        now: Optional[datetime] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        overrides = overrides or {}
        data = await self._collect(now, overrides)
        subject = self._subject(data, now)
        html = self._render_html(data, now)
        sent = False
        if self.notifications:
            try:
                sent = await self.notifications._send_email(
                    DIGEST_EMAIL, subject, html, "public_trial_digest",
                    already_html=True,
                )
            except Exception as e:
                logger.error("PublicTrialDigest: email send failed: %s", e)
        await self._log_sent(now, data.get("verdict", ""))
        return {"sent": sent, "subject": subject, "data": data}

    async def _collect(self, now: datetime, overrides: Dict[str, Any]) -> Dict[str, Any]:
        window_start = now - timedelta(hours=24)
        bleed_flags = 0
        bleeding_sessions: List[Dict[str, Any]] = []
        flagged_24h: List[Dict[str, Any]] = []
        organic_today = {"starts": 0, "reached_5": 0, "reached_15": 0, "converted": 0}
        organic_7d = dict(organic_today)
        conversations: List[Dict[str, Any]] = []
        phi_status = "unknown"
        phi_last_sweep = ""
        phi_quarantines_24h = 0

        global_turns = 0
        global_cap = int(os.getenv("MAX_TRIAL_TURNS_PER_DAY", "2000"))
        peak_hour_label = "n/a"
        unique_ips = overrides.get("unique_ips")

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT device_uuid_hash, device_fingerprint, turns_used, trial_history,
                       converted, converted_username, gated_at,
                       trial_started_at, last_seen
                FROM public_summon_usage
                WHERE device_uuid_hash IS NOT NULL
                """
            )
            flagged_24h = [
                dict(r) for r in await conn.fetch(
                    """
                    SELECT direction, reason, text, created_at
                    FROM public_trial_flagged_turns
                    WHERE created_at > $1
                    ORDER BY created_at DESC
                    """,
                    window_start,
                )
            ]
            phi_row = await conn.fetchrow(
                """
                SELECT created_at FROM skyeye_activity
                WHERE type = 'crystal_phi_audit_cycle'
                ORDER BY created_at DESC LIMIT 1
                """
            )
            phi_quarantines_24h = await conn.fetchval(
                """
                SELECT COUNT(*) FROM audit_log
                WHERE action_type = 'SECURITY'
                  AND admin_username = 'crystal_phi_auditor'
                  AND logged_at > $1
                """,
                window_start,
            ) or 0

        if phi_row and phi_row["created_at"]:
            ts = phi_row["created_at"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            phi_last_sweep = ts.astimezone(ET).strftime("%H:%M ET")
        phi_status = "clean" if int(phi_quarantines_24h) == 0 else f"{phi_quarantines_24h} quarantined"

        today_et = now.astimezone(ET).date()
        week_start_et = today_et - timedelta(days=6)
        hour_turns: Dict[int, int] = {}

        for row in rows:
            history = _parse_history(row["trial_history"])
            probe = _is_probe_session(history, row["converted_username"])
            turns = int(row["turns_used"] or 0)
            bleed_details: List[Dict[str, Any]] = []
            if not probe:
                bleed_details = _find_bleed_details_in_session(history)
                if bleed_details:
                    bleed_flags += sum(len(d["hit_patterns"]) for d in bleed_details)
                    last_seen_raw = row["last_seen"]
                    if last_seen_raw and last_seen_raw.tzinfo is None:
                        last_seen_raw = last_seen_raw.replace(tzinfo=timezone.utc)
                    bleeding_sessions.append({
                        "device_uuid_hash": row["device_uuid_hash"],
                        "last_seen_et": (
                            last_seen_raw.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
                            if last_seen_raw else "unknown"
                        ),
                        "turns": bleed_details,
                    })

            started = row["trial_started_at"]
            last_seen = row["last_seen"]
            if started and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if last_seen and last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)

            if not probe and started:
                started_et = started.astimezone(ET).date()
                if started_et == today_et:
                    organic_today["starts"] += 1
                    if turns >= 5:
                        organic_today["reached_5"] += 1
                    if turns >= 15:
                        organic_today["reached_15"] += 1
                    if row["converted"]:
                        organic_today["converted"] += 1
                if started_et >= week_start_et:
                    organic_7d["starts"] += 1
                    if turns >= 5:
                        organic_7d["reached_5"] += 1
                    if turns >= 15:
                        organic_7d["reached_15"] += 1
                    if row["converted"]:
                        organic_7d["converted"] += 1

            if not probe and last_seen and last_seen >= window_start and turns > 0:
                hour_key = last_seen.astimezone(ET).hour
                hour_turns[hour_key] = hour_turns.get(hour_key, 0) + turns
                conv_flags = sum(len(d["hit_patterns"]) for d in bleed_details)
                source = overrides.get("session_sources", {}).get(
                    row["device_uuid_hash"], ""
                )
                conversations.append({
                    "device_uuid_hash": row["device_uuid_hash"],
                    "last_seen_et": last_seen.astimezone(ET).strftime("%H:%M ET"),
                    "source": source,
                    "opened": _first_user_message(history),
                    "turns": turns,
                    "gated": bool(row["gated_at"]),
                    "flags": "none" if conv_flags == 0 else f"{conv_flags} bleed flag(s)",
                    "tone": _tone_label(history),
                })

        conversations.sort(key=lambda c: c["last_seen_et"], reverse=True)
        latest_label = overrides.get("_latest_source_label")
        if latest_label and conversations:
            conversations[0]["source"] = latest_label

        global_turns = await self._redis_global_daily() or overrides.get("global_turns", 0)
        if hour_turns:
            peak_h, peak_n = max(hour_turns.items(), key=lambda x: x[1])
            ampm = "am" if peak_h < 12 else "pm"
            h12 = peak_h % 12 or 12
            peak_hour_label = f"{peak_n} turns ({h12}{ampm} ET)"

        budget_pct = int(round(100 * global_turns / global_cap)) if global_cap else 0
        budget_ok = global_turns < global_cap * 0.8

        verdict = "all clear"
        emoji = "🟢"
        if bleed_flags > 0 or int(phi_quarantines_24h) > 0:
            verdict = "REVIEW NEEDED"
            emoji = "🔴"

        return {
            "verdict": verdict,
            "emoji": emoji,
            "bleed_flags": bleed_flags,
            "bleeding_sessions": bleeding_sessions,
            "phi_status": phi_status,
            "phi_last_sweep": phi_last_sweep or "n/a",
            "flagged_24h": flagged_24h,
            "flagged_count": len(flagged_24h),
            "global_turns": global_turns,
            "global_cap": global_cap,
            "budget_pct": budget_pct,
            "budget_ok": budget_ok,
            "peak_hour": peak_hour_label,
            "unique_ips": unique_ips,
            "organic_today": organic_today,
            "organic_7d": organic_7d,
            "conversations": conversations[:10],
            "organic_conv_count": len(conversations),
        }

    async def _redis_global_daily(self) -> int:
        if not self.redis_url:
            return 0
        try:
            import redis.asyncio as aioredis
            from app.services.trial_signup_redis_keys import public_trial_global_daily_key
            r = aioredis.from_url(self.redis_url, decode_responses=True)
            try:
                val = await r.get(public_trial_global_daily_key())
                return int(val or 0)
            finally:
                await r.aclose()
        except Exception as e:
            logger.warning("PublicTrialDigest: Redis global daily read failed: %s", e)
            return 0

    def _subject(self, data: Dict[str, Any], now: datetime) -> str:
        day = now.astimezone(ET).strftime("%b %-d")
        if data["emoji"] == "🔴":
            return f"🔴 Little Nate Daily Digest — {day} (REVIEW NEEDED)"
        return f"🟢 Little Nate Daily Digest — {day} (all clear)"

    def _mono_block(self, lines: List[str]) -> str:
        body = "<br>".join(lines)
        return (
            '<div style="background:#111;border:1px solid #333;border-radius:6px;'
            'padding:12px 14px;margin:12px 0;font-family:ui-monospace,Menlo,monospace;'
            f'font-size:12px;line-height:1.6;color:#e2e8f0;">{body}</div>'
        )

    def _esc(self, text: str) -> str:
        return _html.escape(text or "", quote=False).replace("\n", "<br>")

    def _render_bleed_alert(self, bleeding_sessions: List[Dict[str, Any]]) -> str:
        """Bug #1: bleed is the worst-case event — it leads the email, in full,
        above SAFETY/BUDGET/FUNNEL, not as a buried line item. Shows session
        ID, every leaking turn (full user prompt + full assistant reply), and
        exactly which pattern(s) matched — nothing truncated, nothing summarized.
        """
        if not bleeding_sessions:
            return ""
        blocks = [
            '<div style="font-size:14px;font-weight:700;color:#fca5a5;margin-bottom:8px;">'
            "🔴 CRYSTAL BLEED DETECTED — REVIEW BEFORE ANYTHING ELSE BELOW</div>"
        ]
        for s in bleeding_sessions:
            blocks.append(
                f'<div style="margin:10px 0 4px;font-size:12px;color:#fecaca;">'
                f"Session <code>{self._esc(str(s['device_uuid_hash']))}</code> · "
                f"last seen {self._esc(s['last_seen_et'])}</div>"
            )
            for t in s["turns"]:
                labels = ", ".join(
                    _BLEED_LABELS.get(p, p) for p in t["hit_patterns"]
                )
                blocks.append(
                    '<div style="background:#1a0a0a;border:1px solid #7f1d1d;border-radius:6px;'
                    'padding:10px 12px;margin:6px 0;font-size:12px;line-height:1.6;color:#fef2f2;">'
                    f"<b>Leaked:</b> {self._esc(labels)}<br>"
                    f"<b>Turn {t['turn_index'] + 1} — user asked:</b><br>"
                    f"{self._esc(t['user']) or '<i>(no preceding user text)</i>'}<br><br>"
                    f"<b>Turn {t['turn_index'] + 1} — Nate replied:</b><br>"
                    f"{self._esc(t['assistant'])}"
                    "</div>"
                )
        return (
            '<div style="background:#2d0a0a;border:2px solid #dc2626;border-radius:8px;'
            'padding:14px 16px;margin:0 0 20px;">' + "".join(blocks) + "</div>"
        )

    def _render_html(self, data: Dict[str, Any], now: datetime) -> str:
        day_label = now.astimezone(ET).strftime("%A, %B %-d, %Y")
        bleed_alert_html = self._render_bleed_alert(data.get("bleeding_sessions") or [])
        bleed_line = (
            f"Crystal bleed flags ....... {data['bleed_flags']}  "
            f"{'✅ clean' if data['bleed_flags'] == 0 else '🔴 REVIEW'}"
        )
        phi_line = (
            f"PHI auditor ............... {data['phi_status']}"
            + (f", last sweep {data['phi_last_sweep']}" if data['phi_last_sweep'] != "n/a" else "")
        )
        flagged_line = (
            f"Flagged turns (24h) ....... {data['flagged_count']}  "
            + ("✅ none" if data['flagged_count'] == 0 else "⚠️ review below")
        )
        safety = self._mono_block([bleed_line, phi_line, flagged_line])

        budget_icon = "✅ healthy" if data["budget_ok"] else "⚠️ elevated"
        ip_line = (
            f"Unique IPs (excl. internal) {data['unique_ips']}"
            if data.get("unique_ips") is not None
            else "Unique IPs (excl. internal) n/a — set via nginx parse on send"
        )
        budget = self._mono_block([
            f"Global trial turns today .. {data['global_turns']} / {data['global_cap']} "
            f"({data['budget_pct']}%) {budget_icon}",
            f"Peak hour ................. {data['peak_hour']}",
            "Depletion alerts .......... none",
            ip_line,
        ])

        ot, ow = data["organic_today"], data["organic_7d"]
        funnel = self._mono_block([
            "          Starts   ≥5 turns   ≥15   Converted",
            f"Today      {ot['starts']:>5}      {ot['reached_5']:>5}     "
            f"{ot['reached_15']:>3}        {ot['converted']:>3}",
            f"7-day      {ow['starts']:>5}      {ow['reached_5']:>5}     "
            f"{ow['reached_15']:>3}        {ow['converted']:>3}",
        ])

        conv_html = ""
        if data["conversations"]:
            blocks = [f"<b>REAL CONVERSATIONS (non-probe, 24h) — {data['organic_conv_count']}</b>"]
            for i, c in enumerate(data["conversations"], 1):
                src = f" · {self._esc(c['source'])}" if c.get("source") else ""
                opened_raw = c["opened"][:120] + ("…" if len(c["opened"]) > 120 else "")
                opened = self._esc(opened_raw)
                blocks.append(
                    f"<br><b>{i}.</b> {c['last_seen_et']}{src}<br>"
                    f"&nbsp;&nbsp;Opened: \"{opened}\"<br>"
                    f"&nbsp;&nbsp;Turns: {c['turns']} · Reached gate: "
                    f"{'yes' if c['gated'] else 'no'} · Flags: {c['flags']}<br>"
                    f"&nbsp;&nbsp;Tone: {c['tone']}"
                )
            conv_html = (
                '<div style="margin:16px 0;font-size:13px;color:#e2e8f0;">'
                + "".join(blocks) + "</div>"
            )
        else:
            conv_html = (
                '<p style="color:#94a3b8;font-size:13px;">'
                "No organic conversations in the last 24h.</p>"
            )

        flag_html = ""
        if data["flagged_24h"]:
            items = ["<b>⚠️ FLAGGED TURNS TO EYEBALL</b>"]
            for i, row in enumerate(data["flagged_24h"], 1):
                ts = row["created_at"]
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ts_et = ts.astimezone(ET).strftime("%-I:%M%p").lower()
                verdict, label = _FLAG_VERDICT.get(
                    row["reason"], ("LOGGED", row["reason"].replace("_", "-"))
                )
                items.append(
                    f"<br>{i}. {ts_et} · {label} · {verdict} ✅"
                )
            items.append(
                "<br><span style='color:#94a3b8;font-size:12px;'>"
                "Both handled correctly — no action needed unless pattern is new."
                "</span>"
            )
            flag_html = (
                '<div style="margin:16px 0;font-size:13px;color:#e2e8f0;">'
                + "".join(items) + "</div>"
            )

        bleed_note = (
            "zero bleeds" if data["bleed_flags"] == 0
            else f"{data['bleed_flags']} bleed flag(s)"
        )
        summary = (
            f"{data['emoji']} <b>{data['verdict'].capitalize()}.</b> "
            f"{data['organic_conv_count']} real conversation"
            f"{'' if data['organic_conv_count'] == 1 else 's'}, "
            f"budget at {data['budget_pct']}%, {bleed_note}."
        )
        note = (
            "<p style='color:#64748b;font-size:11px;margin-top:20px;'>"
            "Internal/testing IPs and content-flagged probe sessions (jailbreak phrasing, "
            "base64 payloads, red-team openers, test accounts) excluded from organic counts."
            "</p>"
        )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:640px;margin:0 auto;background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;padding:20px;">
  <h2 style="margin:0 0 4px;color:#C9A962;font-family:'Cormorant Garamond',Georgia,serif;">
    Sovereign Sanctuary — Trial Digest
  </h2>
  <p style="margin:0 0 16px;color:#94a3b8;font-size:12px;">{day_label} · last 24h</p>
  {bleed_alert_html}
  <h3 style="color:#C9A962;font-size:14px;margin:16px 0 4px;">🛡️ SAFETY — the tripwires</h3>
  {safety}
  <h3 style="color:#C9A962;font-size:14px;margin:16px 0 4px;">💰 BUDGET — cost &amp; abuse</h3>
  {budget}
  <h3 style="color:#C9A962;font-size:14px;margin:16px 0 4px;">📊 FUNNEL — organic only</h3>
  {funnel}
  {conv_html}
  {flag_html}
  <p style="font-size:13px;margin-top:16px;">{summary}</p>
  {note}
</div>"""

    async def _log_sent(self, now: datetime, verdict: str) -> None:
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ('system', 'public_trial_digest_sent', $1, 'info', NOW())
                    """,
                    f"verdict={verdict} at {now.isoformat()}",
                )
        except Exception as e:
            logger.warning("PublicTrialDigest: activity log failed: %s", e)
