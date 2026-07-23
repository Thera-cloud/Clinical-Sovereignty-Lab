"""
LN-Observer engine — capture/STT/buffer, littlenate_inference, crystallize, sweep.
# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

MAX_CONTEXT_FRAMES = 4
MAX_TRANSCRIPT_LINES = 60
FRAME_BUFFER_SIZE = 6
RECONNECT_GRACE_S = 90
MAX_SESSION_S = 3 * 3600
WARN_SESSION_S = int(2.75 * 3600)  # 2:45 warn before 3h cap
OBSERVE_DEBOUNCE_S = 20
CHAT_COMPACT_EVERY = 20
ACK_TEXT_V1 = (
    "By activating LN-Observer, the coach accepts full responsibility for the "
    "activation and for all content shared to the observation feed. Sovereign "
    "Sanctuary logs the activating coach and timestamp as the record of activation."
)


def _ticket_secret() -> bytes:
    return (
        os.environ.get("LN_OBSERVER_WS_SECRET")
        or os.environ.get("JWT_SECRET")
        or "ln-observer-dev"
    ).encode()


def mint_ws_ticket(session_id: str, coach_id: str, ttl_s: int = 3600) -> str:
    exp = int(time.time()) + ttl_s
    msg = f"{session_id}:{coach_id}:{exp}".encode()
    sig = hmac.new(_ticket_secret(), msg, hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{sig}"


def verify_ws_ticket(session_id: str, coach_id: str, ticket: str) -> bool:
    try:
        exp_s, sig = ticket.split(".", 1)
        exp = int(exp_s)
        if exp < int(time.time()):
            return False
        msg = f"{session_id}:{coach_id}:{exp}".encode()
        expected = hmac.new(_ticket_secret(), msg, hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


class LiveSession:
    def __init__(
        self,
        session_id: str,
        coach_id: str,
        coach_name: str,
        context_bundle: str = "",
        assigned_clients: Optional[List[Dict[str, str]]] = None,
        coach_profile: Optional[Dict[str, str]] = None,
        activation_memory: str = "",
    ):
        self.session_id = session_id
        self.coach_id = coach_id
        self.coach_name = coach_name
        self.context_bundle = context_bundle or ""
        self.assigned_clients = assigned_clients or []
        self.coach_profile = coach_profile or {}
        self.activation_memory = activation_memory or ""
        self.frames: List[str] = []
        self.transcript: List[dict] = []
        self.chat: List[dict] = []
        self.chat_compact: str = ""
        self.chat_turns_since_compact = 0
        self.lock = asyncio.Lock()
        self.last_observe_at = 0.0
        self.last_ln_reply = ""
        self.pending_crystallize_coach = ""
        self.pending_crystallize_at = 0.0
        self.started_at = time.time()
        self.warn_245_sent = False

    def add_frame(self, b64jpeg: str):
        self.frames.append(b64jpeg)
        if len(self.frames) > FRAME_BUFFER_SIZE:
            self.frames = self.frames[-FRAME_BUFFER_SIZE:]

    def add_transcript(self, source: str, content: str):
        self.transcript.append(
            {
                "source": source,
                "content": content,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(self.transcript) > MAX_TRANSCRIPT_LINES:
            self.transcript = self.transcript[-MAX_TRANSCRIPT_LINES:]


class LNObserverEngine:
    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self.live: Dict[str, LiveSession] = {}
        self._sweep_task: Optional[asyncio.Task] = None
        self._running = False

    def bind(self, db_pool=None, app_state=None):
        if db_pool is not None:
            self._db_pool = db_pool
        if app_state is not None:
            self._app_state = app_state

    async def start(self):
        if self._running:
            return
        self._running = True
        self._sweep_task = asyncio.create_task(self._sweep_loop())
        logger.info("LNObserverEngine: sweep loop started")

    async def stop(self):
        self._running = False
        if self._sweep_task:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None

    async def _sweep_loop(self):
        while self._running:
            try:
                await asyncio.sleep(60)
                await self.sweep_orphans()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("LNObserverEngine sweep error: %s", e)

    async def coach_is_approved(self, coach_id: str) -> bool:
        if not self._db_pool:
            return False
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM ln_observer_approvals WHERE coach_id=$1",
                coach_id,
            )
        return bool(row and row["status"] == "approved")

    async def db_log(self, session_id: str, source: str, content: str):
        if not self._db_pool:
            return
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO ln_observer_transcripts (session_id, source, content) "
                "VALUES ($1,$2,$3)",
                uuid.UUID(session_id),
                source,
                content,
            )

    async def load_prior_summaries(self, coach_id: str, limit: int = 5) -> str:
        if not self._db_pool:
            return ""
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT ln_summary, started_at FROM ln_observer_sessions
                   WHERE coach_id=$1 AND ln_summary IS NOT NULL AND ln_summary != ''
                   ORDER BY started_at DESC LIMIT $2""",
                coach_id,
                limit,
            )
        if not rows:
            return ""
        parts = []
        for r in rows:
            ts = r["started_at"].isoformat() if r["started_at"] else ""
            parts.append(f"[{ts}] {r['ln_summary'][:600]}")
        return "\n".join(parts)

    async def load_assigned_clients(self, coach_id: str) -> List[Dict[str, str]]:
        if not self._db_pool:
            return []
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT username, profile_data->>'name' AS name
                       FROM users
                       WHERE role='CLIENT'
                         AND (
                           profile_data->>'coach_id' = $1
                           OR profile_data->>'assigned_coach_id' = $1
                           OR profile_data->>'assigned_coach' = $1
                           OR username = $1
                         )
                       LIMIT 40""",
                    coach_id,
                )
            return [
                {"username": r["username"], "name": r["name"] or r["username"]}
                for r in rows
            ]
        except Exception as e:
            logger.warning("LNObserverEngine assigned clients: %s", e)
            return []

    async def load_coach_profile(self, coach_id: str) -> Dict[str, str]:
        if not self._db_pool:
            return {}
        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT tier,
                              profile_data->>'name' AS name,
                              profile_data->>'specialties' AS specialties,
                              profile_data->>'specialty' AS specialty,
                              profile_data->>'dojo' AS dojo,
                              profile_data->>'bio' AS bio
                       FROM users
                       WHERE username=$1 OR hardware_id=$1 LIMIT 1""",
                    coach_id,
                )
            if not row:
                return {}
            specs = row["specialties"] or row["specialty"] or ""
            return {
                "name": row["name"] or coach_id,
                "tier": row["tier"] or "",
                "specialties": specs or "",
                "dojo": row["dojo"] or "",
                "bio": (row["bio"] or "")[:400],
            }
        except Exception as e:
            logger.warning("LNObserverEngine coach profile: %s", e)
            return {}

    async def build_activation_prefetch(
        self, coach_id: str, clients: List[Dict[str, str]], prior: str, profile: Dict[str, str],
    ) -> str:
        """Non-empty semantic prefetch for activation briefing (Gap 2)."""
        chunks = [
            profile.get("specialties") or "",
            profile.get("dojo") or "",
            profile.get("tier") or "",
            " ".join(c.get("name", "") for c in clients[:8]),
            prior[:800] if prior else "coaching observation therapeutic themes",
        ]
        query = " ".join(x for x in chunks if x).strip() or "clinical coaching observation"
        try:
            from app.services.ln_observer_lni_support import retrieve_crystals_multi
            crystals = await retrieve_crystals_multi(
                query, coach_id, top_k=6, db_pool=self._db_pool,
            )
            lines = []
            for c in crystals[:6]:
                text = c.get("metadata", {}).get("text", c.get("text", ""))
                if text:
                    lines.append(f"- {text[:180]}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("LNObserverEngine activation prefetch: %s", e)
            return ""

    def build_what_you_know(self, sess: LiveSession) -> str:
        parts = ["[WHAT YOU ALREADY KNOW]"]
        parts.append(f"Coach: {sess.coach_name} ({sess.coach_id})")
        prof = sess.coach_profile or {}
        if prof.get("tier"):
            parts.append(f"Tier: {prof['tier']}")
        if prof.get("specialties"):
            parts.append(f"Specialties: {prof['specialties']}")
        if prof.get("dojo"):
            parts.append(f"DOJO: {prof['dojo']}")
        if prof.get("bio"):
            parts.append(f"Profile notes: {prof['bio']}")
        if sess.assigned_clients:
            names = ", ".join(
                f"{c['name']} (@{c['username']})" for c in sess.assigned_clients[:12]
            )
            parts.append(f"Assigned clients: {names}")
        if sess.context_bundle:
            parts.append("Prior Observer sessions:\n" + sess.context_bundle)
        if sess.activation_memory:
            parts.append("Activation memory prefetch:\n" + sess.activation_memory)
        if sess.chat_compact:
            parts.append("Earlier chat (compacted):\n" + sess.chat_compact)
        return "\n".join(parts)

    def context_block(self, sess: LiveSession, n: int = 12) -> str:
        lines = []
        for t in sess.transcript[-n:]:
            tag = {
                "audio_transcript": "AUDIO",
                "frame_observation": "SEEN",
                "coach_chat": "COACH",
                "ln_chat": "LN",
                "system": "SYS",
            }.get(t["source"], "?")
            lines.append(f"[{tag}] {t['content']}")
        return "\n".join(lines) if lines else "(session just started — no transcript yet)"

    def live_haystack(self, sess: LiveSession, coach_message: str = "") -> str:
        """Live coach/transcript text only — used for Gap 7 client matching (not roster stuffing)."""
        parts = [coach_message or "", self.context_block(sess, n=12)]
        for m in sess.chat[-8:]:
            parts.append(m.get("content", ""))
        return " ".join(parts)

    def build_recall_query(self, sess: LiveSession, coach_message: str) -> str:
        chunks = [coach_message]
        chunks.append(self.context_block(sess, n=10))
        for t in reversed(sess.transcript):
            if t["source"] == "frame_observation":
                chunks.append(t["content"])
                break
        # Roster enriches semantic query (Gap 2) but match_client_ids uses live_haystack only
        for c in sess.assigned_clients[:8]:
            chunks.append(c.get("name", ""))
            chunks.append(c.get("username", ""))
        text = " ".join(chunks)
        proper = re.findall(r"\b[A-Z][a-z]{2,}\b", text)
        if proper:
            chunks.append(" ".join(proper[:12]))
        return " ".join(x for x in chunks if x)[:2000]

    def match_client_ids(self, sess: LiveSession, haystack: str) -> List[str]:
        """Match assigned clients only when name/username appears in live text (Gap 7)."""
        q = (haystack or "").lower()
        matched: List[str] = []
        for c in sess.assigned_clients:
            uname = (c.get("username") or "").lower()
            name = (c.get("name") or "").lower()
            if uname and uname in q:
                matched.append(c["username"])
            elif name and len(name) >= 3 and name in q:
                matched.append(c["username"])
            if len(matched) >= 3:
                break
        return matched

    def maybe_compact_chat(self, sess: LiveSession) -> None:
        """Compact chat every ~20 exchanges into standing notes (token budget)."""
        sess.chat_turns_since_compact += 1
        if sess.chat_turns_since_compact < CHAT_COMPACT_EVERY:
            return
        if len(sess.chat) < 8:
            return
        older = sess.chat[:-8]
        if not older:
            return
        lines = []
        for m in older:
            role = "COACH" if m.get("role") == "user" else "LN"
            lines.append(f"[{role}] {(m.get('content') or '')[:160]}")
        blob = "\n".join(lines)
        if sess.chat_compact:
            sess.chat_compact = (sess.chat_compact + "\n" + blob)[-2400:]
        else:
            sess.chat_compact = blob[-2400:]
        sess.chat = sess.chat[-8:]
        sess.chat_turns_since_compact = 0

    def session_time_warn(self, sess: LiveSession) -> Optional[str]:
        """Return warn text once at 2:45; None otherwise."""
        elapsed = time.time() - sess.started_at
        if elapsed >= MAX_SESSION_S:
            return "session_max"
        if elapsed >= WARN_SESSION_S and not sess.warn_245_sent:
            sess.warn_245_sent = True
            return (
                "LN-Observer session approaches the 3-hour maximum "
                "(~15 minutes remaining). Plan to wrap up or start a new session."
            )
        return None

    def _inference(self):
        return getattr(self._app_state, "littlenate_inference", None) if self._app_state else None

    def _validator(self):
        if not self._app_state:
            return None
        v = getattr(self._app_state, "nate_response_validator", None)
        if v:
            return v
        try:
            from app.services.nate_response_validator import NateResponseValidator
            return NateResponseValidator()
        except Exception:
            return None

    async def _crystallize_safe(
        self,
        coach_id: str,
        user_text: str,
        nate_response: str,
        coach_name: str = "",
        min_score: int = 3,
    ) -> Optional[str]:
        text = (nate_response or "").strip()
        if len(text) < 40:
            return None
        validator = self._validator()
        if validator:
            try:
                _, warnings = await validator.validate(text, {})
                if validator.is_high_severity(warnings):
                    logger.warning(
                        "LNObserverEngine: crystallize blocked by validator: %s",
                        warnings,
                    )
                    return None
            except Exception as e:
                logger.warning("LNObserverEngine validator error: %s", e)
        try:
            from app.websocket.crystal_recall_bridge import crystallize_from_conversation
            return await crystallize_from_conversation(
                self._db_pool,
                coach_id,
                user_text or text[:200],
                text,
                user_name=coach_name,
                domain="coaching",
                min_score=min_score,
                origin_surface="ln_observer",
            )
        except Exception as e:
            logger.warning("LNObserverEngine crystallize failed: %s", e)
            return None

    async def generate_chat(
        self,
        sess: LiveSession,
        coach_message: str,
        *,
        look_now: bool = False,
        lean: bool = False,
    ) -> str:
        inference = self._inference()
        if not inference:
            return "Little Nate inference is not available right now."

        recall_query = self.build_recall_query(sess, coach_message)
        also_ids = self.match_client_ids(sess, self.live_haystack(sess, coach_message))
        what = self.build_what_you_know(sess)
        transcript = self.context_block(sess, n=12)
        chat_tail = ""
        for m in sess.chat[-12:]:
            role = "COACH" if m.get("role") == "user" else "LN"
            chat_tail += f"[{role}] {m.get('content', '')}\n"
        conversation_context = (
            f"{what}\n\n[ROLLING TRANSCRIPT]\n{transcript}\n\n[CHAT]\n{chat_tail}"
        )
        n_frames = 4 if look_now else (1 if lean else 3)
        images = sess.frames[-n_frames:] if sess.frames else None

        try:
            result = await inference.generate(
                prompt=coach_message if not lean else (
                    "Internal observation pass (not chat): in 1-2 sentences, note what is "
                    "on screen now and anything clinically noteworthy. Be terse."
                ),
                user_id=sess.coach_id,
                domain="coaching",
                tier="clinical",
                conversation_context=conversation_context,
                recall_query=None if lean else recall_query,
                recall_also_user_ids=None if lean else (also_ids or None),
                recall_top_k=8,
                images=images,
                mode="lean" if lean else "full",
                attach_wisdom=not lean,
                include_crystals=not lean,
                include_helix=not lean,
                include_quantum=not lean,
                max_tokens=120 if lean else (800 if not look_now else 900),
                is_realtime=True,
            )
            reply = (result.text or "").strip()
            if getattr(result, "error", None) and "content_filter" in str(result.error).lower():
                return (
                    "I need to skip that frame — the vision filter blocked it. "
                    "Share a different view or describe what you're seeing."
                )
            return reply or "(no response)"
        except Exception as e:
            err = str(e)
            if "content_filter" in err.lower() or "ResponsibleAIPolicyViolation" in err:
                return (
                    "I need to skip that frame — the vision filter blocked it. "
                    "Share a different view or describe what you're seeing."
                )
            logger.warning("LNObserverEngine generate failed: %s", e)
            return f"(LN-Observer reasoning error: {e})"

    async def close_summary(self, sess: LiveSession) -> Optional[str]:
        inference = self._inference()
        if not inference:
            return None
        prompt = (
            f"The LN-Observer session with {sess.coach_name} is ending. Full transcript:\n"
            f"{self.context_block(sess, n=40)}\n\n"
            "Write a closing synthesis for warm memory: key observations, therapeutic "
            "themes, what the coach engaged with, and anything to carry forward. "
            "1 short paragraph."
        )
        try:
            result = await inference.generate(
                prompt=prompt,
                user_id=sess.coach_id,
                domain="coaching",
                tier="clinical",
                conversation_context=self.build_what_you_know(sess),
                attach_wisdom=True,
                include_crystals=True,
                max_tokens=400,
                is_realtime=False,
                allow_deep=True,
            )
            summary = (result.text or "").strip()
            validator = self._validator()
            if summary and validator:
                _, warnings = await validator.validate(summary, {})
                if validator.is_high_severity(warnings):
                    logger.warning("LNObserverEngine: ln_summary blocked by validator")
                    return None
            return summary or None
        except Exception as e:
            logger.warning("LNObserverEngine close summary failed: %s", e)
            return None

    async def hydrate_session(self, session_id: str) -> Optional[LiveSession]:
        if session_id in self.live:
            return self.live[session_id]
        if not self._db_pool:
            return None
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT session_id, coach_id, status, context_bundle, ws_ticket
                   FROM ln_observer_sessions WHERE session_id=$1""",
                uuid.UUID(session_id),
            )
        if not row or row["status"] not in ("live", "reconnecting"):
            return None
        coach_id = row["coach_id"]
        coach_name = coach_id
        async with self._db_pool.acquire() as conn:
            u = await conn.fetchrow(
                "SELECT profile_data->>'name' AS name FROM users "
                "WHERE username=$1 OR hardware_id=$1 LIMIT 1",
                coach_id,
            )
            if u and u["name"]:
                coach_name = u["name"]
        clients = await self.load_assigned_clients(coach_id)
        profile = await self.load_coach_profile(coach_id)
        sess = LiveSession(
            session_id,
            coach_id,
            coach_name,
            context_bundle=row["context_bundle"] or "",
            assigned_clients=clients,
            coach_profile=profile,
        )
        self.live[session_id] = sess
        return sess

    async def mark_reconnecting(self, session_id: str):
        if not self._db_pool:
            return
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE ln_observer_sessions
                   SET status='reconnecting', disconnected_at=now()
                   WHERE session_id=$1 AND status='live'""",
                uuid.UUID(session_id),
            )

    async def mark_live_again(self, session_id: str):
        if not self._db_pool:
            return
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE ln_observer_sessions
                   SET status='live', disconnected_at=NULL
                   WHERE session_id=$1 AND status='reconnecting'""",
                uuid.UUID(session_id),
            )

    async def deactivate(self, session_id: str) -> Optional[str]:
        sess = self.live.pop(session_id, None)
        summary = None
        if sess:
            summary = await self.close_summary(sess)
            if summary:
                close_user = (
                    f"LN-Observer session close with {sess.coach_name}. "
                    f"Themes from session: {self.context_block(sess, n=20)[:500]}"
                )
                await self._crystallize_safe(
                    sess.coach_id,
                    close_user,
                    summary,
                    coach_name=sess.coach_name,
                    min_score=2,
                )
        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE ln_observer_sessions
                       SET status='ended', ended_at=now(), ln_summary=$2
                       WHERE session_id=$1""",
                    uuid.UUID(session_id),
                    summary,
                )
                await conn.execute(
                    """UPDATE ln_observer_activation_log
                       SET deactivated_at=now() WHERE session_id=$1
                       AND deactivated_at IS NULL""",
                    uuid.UUID(session_id),
                )
        await self.db_log(session_id, "system", "LN-Observer deactivated.")
        return summary

    async def sweep_orphans(self):
        if not self._db_pool:
            return
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT session_id::text AS sid FROM ln_observer_sessions
                   WHERE status='reconnecting'
                     AND disconnected_at < NOW() - INTERVAL '90 seconds'"""
            )
            # Also end live sessions over 3h
            old = await conn.fetch(
                """SELECT session_id::text AS sid FROM ln_observer_sessions
                   WHERE status IN ('live','reconnecting')
                     AND started_at < NOW() - INTERVAL '3 hours'"""
            )
        sids: Set[str] = {r["sid"] for r in rows} | {r["sid"] for r in old}
        for sid in sids:
            try:
                await self.deactivate(sid)
                logger.info("LNObserverEngine: swept orphan session %s", sid[:8])
            except Exception as e:
                logger.warning("LNObserverEngine sweep deactivate %s: %s", sid[:8], e)

    async def transcribe_audio(self, webm_bytes: bytes) -> str:
        try:
            from app.services.whisper_stt import transcribe
            text = await transcribe(webm_bytes, content_type="audio/webm")
            return (text or "").strip()
        except Exception as e:
            logger.warning("LNObserverEngine STT failed: %s", e)
            return ""


# Module singleton wired from main.py
ln_observer_engine = LNObserverEngine()
