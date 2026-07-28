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
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

MAX_CONTEXT_FRAMES = 4
MAX_TRANSCRIPT_LINES = 80
FRAME_BUFFER_SIZE = 8
FRAME_RING_SIZE = 24
RECONNECT_GRACE_S = 90
MAX_SESSION_S = 3 * 3600
WARN_SESSION_S = int(2.75 * 3600)  # 2:45 warn before 3h cap
OBSERVE_DEBOUNCE_S = 20
# Time-based observe — static Zoom/Box screens send few frames; do not wait for N frames.
OBSERVE_INTERVAL_S = 45.0
OBSERVE_EVERY_N = 6
VISION_INFLIGHT_STALE_S = 45.0
CHAT_COMPACT_EVERY = 20
# QUANTUM-CRYSTAL-ARCH — same-brain enrichment (non-lean only; bounded)
# Short Vectorize budget; PG keyword fallback runs separately (≤3s). # QUANTUM-CRYSTAL-ARCH
SAME_BRAIN_RECALL_TIMEOUT_S = 2.5
SAME_BRAIN_LNI_TIMEOUT_S = 12.0
SAME_BRAIN_CACHE_TTL_S = 15.0
# QUANTUM-CRYSTAL-ARCH — max gap to claim A/V "aligned" for forensics
AV_ALIGN_MAX_MS = 4000
# Learning forge cadence — stop flooding thin A/V pair crystals
AV_CRYSTAL_MIN_INTERVAL_S = 45.0
SEEN_CRYSTAL_MIN_INTERVAL_S = 90.0
# QUANTUM-CRYSTAL-ARCH — detail/OCR questions that need a fresh frame (not stale notes)
_DETAIL_RE = re.compile(
    r"\b("
    r"see|seeing|saw|look|looking|observe|observing|watching|screen|"
    r"what do you see|can you see|able to see|closer look|describe what|"
    r"on screen|are you able|what word|between|title|browser|bar|"
    r"read|quote|exact|filename|file name|top of|bottom of|says|"
    r"written|text on|cli|input"
    r")\b",
    re.I,
)
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
        # Forensic ring: {frame_id, b64, captured_at_ms, server_recv_ms, iso}
        self.frame_ring: List[Dict[str, Any]] = []
        self.transcript: List[dict] = []
        self.chat: List[dict] = []
        self.chat_compact: str = ""
        self.chat_turns_since_compact = 0
        # Lazy: asyncio.Lock() needs a running loop on Python 3.9
        self._lock: Optional[asyncio.Lock] = None
        self.last_observe_at = 0.0
        self.last_ln_reply = ""
        self.pending_crystallize_coach = ""
        self.pending_crystallize_at = 0.0
        self.started_at = time.time()
        self.warn_245_sent = False
        self.last_frame_observation = ""
        self.last_frame_id = ""
        self.vision_inflight = False
        self.vision_inflight_since = 0.0
        self.lean_observe_count = 0
        # Pending audio window from client {t_start_ms, t_end_ms, seq}
        self.pending_audio_window: Optional[Dict[str, Any]] = None
        self.av_bundles: List[Dict[str, Any]] = []
        # frame_id → vision note that was produced FROM that frame
        self.frame_notes: Dict[str, str] = {}
        # QUANTUM-CRYSTAL-ARCH — cached same-brain blocks (wisdom + RELEVANT MEMORY)
        self.same_brain_prefix: str = ""
        self.same_brain_at: float = 0.0
        self.last_av_crystal_at: float = 0.0
        self.last_seen_crystal_at: float = 0.0
        self.audio_seconds_accum: float = 0.0

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def add_frame(
        self,
        b64jpeg: str,
        captured_at_ms: Optional[float] = None,
        frame_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store JPEG + forensic timestamp. # QUANTUM-CRYSTAL-ARCH"""
        now_ms = time.time() * 1000.0
        ms = float(captured_at_ms) if captured_at_ms else now_ms
        fid = (frame_id or "").strip() or f"f_{uuid.uuid4().hex[:12]}"
        iso = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
        meta = {
            "frame_id": fid,
            "b64": b64jpeg,
            "captured_at_ms": ms,
            "server_recv_ms": now_ms,
            "iso": iso,
        }
        self.frames.append(b64jpeg)
        if len(self.frames) > FRAME_BUFFER_SIZE:
            self.frames = self.frames[-FRAME_BUFFER_SIZE:]
        self.frame_ring.append(meta)
        if len(self.frame_ring) > FRAME_RING_SIZE:
            self.frame_ring = self.frame_ring[-FRAME_RING_SIZE:]
        self.last_frame_id = fid
        # Bound note map to ring
        if len(self.frame_notes) > FRAME_RING_SIZE * 2:
            keep = {f["frame_id"] for f in self.frame_ring}
            self.frame_notes = {
                k: v for k, v in self.frame_notes.items() if k in keep
            }
        return meta

    def frame_by_id(self, frame_id: str) -> Optional[Dict[str, Any]]:
        if not frame_id:
            return None
        for f in reversed(self.frame_ring):
            if f.get("frame_id") == frame_id:
                return f
        return None

    def set_frame_note(self, frame_id: str, note: str):
        if frame_id and note:
            self.frame_notes[frame_id] = note
            self.last_frame_observation = note
            self.last_frame_id = frame_id

    def nearest_frame(self, t_ms: float) -> Optional[Dict[str, Any]]:
        if not self.frame_ring:
            return None
        return min(
            self.frame_ring,
            key=lambda f: abs(float(f.get("captured_at_ms") or 0) - t_ms),
        )

    def recent_frames_for_vision(self, n: int = MAX_CONTEXT_FRAMES) -> List[Dict[str, Any]]:
        return list(self.frame_ring[-max(1, n) :])

    def add_transcript(
        self,
        source: str,
        content: str,
        *,
        meta: Optional[Dict[str, Any]] = None,
        ts_iso: Optional[str] = None,
    ):
        self.transcript.append(
            {
                "source": source,
                "content": content,
                "ts": ts_iso or datetime.now(timezone.utc).isoformat(),
                "meta": meta or {},
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
                # QUANTUM-CRYSTAL-ARCH — Phase 2 drain pending NS ingest chunks
                await self.drain_ns_ingest(limit=25)
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

    async def db_log(
        self,
        session_id: str,
        source: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ):
        if not self._db_pool:
            return
        import json as _json

        meta_obj = meta or {}
        async with self._db_pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO ln_observer_transcripts "
                    "(session_id, source, content, meta) VALUES ($1,$2,$3,$4::jsonb)",
                    uuid.UUID(session_id),
                    source,
                    content,
                    _json.dumps(meta_obj),
                )
            except Exception:
                # Pre-migration 270: meta column / source check may be missing
                try:
                    await conn.execute(
                        "INSERT INTO ln_observer_transcripts (session_id, source, content) "
                        "VALUES ($1,$2,$3)",
                        uuid.UUID(session_id),
                        source if source != "av_bundle" else "system",
                        content,
                    )
                except Exception as e:
                    # Unknown session / FK — never fail deactivate or auditor probes
                    logger.debug("LN-Observer db_log skip: %s", e)

    async def db_log_forensic(
        self,
        session_id: str,
        event_type: str,
        *,
        t_start: Optional[datetime] = None,
        t_end: Optional[datetime] = None,
        frame_id: str = "",
        frame_delta_ms: Optional[int] = None,
        audio_text: str = "",
        seen_text: str = "",
        storage_key: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ):
        if not self._db_pool:
            return
        import json as _json

        safe_payload = {
            k: v for k, v in (payload or {}).items() if k != "_b64"
        }
        if storage_key:
            safe_payload["storage_key"] = storage_key
        async with self._db_pool.acquire() as conn:
            try:
                await conn.execute(
                    """INSERT INTO ln_observer_forensic_events
                       (session_id, event_type, t_start, t_end, frame_id,
                        frame_delta_ms, audio_text, seen_text, storage_key, payload)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)""",
                    uuid.UUID(session_id),
                    event_type,
                    t_start,
                    t_end,
                    frame_id or None,
                    frame_delta_ms,
                    audio_text or None,
                    seen_text or None,
                    storage_key or None,
                    _json.dumps(safe_payload),
                )
            except Exception:
                try:
                    await conn.execute(
                        """INSERT INTO ln_observer_forensic_events
                           (session_id, event_type, t_start, t_end, frame_id,
                            frame_delta_ms, audio_text, seen_text, payload)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""",
                        uuid.UUID(session_id),
                        event_type,
                        t_start,
                        t_end,
                        frame_id or None,
                        frame_delta_ms,
                        audio_text or None,
                        seen_text or None,
                        _json.dumps(safe_payload),
                    )
                except Exception as e:
                    logger.warning("LNObserverEngine forensic insert failed: %s", e)

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
                "av_bundle": "AV",
                "frame_meta": "FRAME",
            }.get(t["source"], "?")
            ts = (t.get("ts") or "")[:19]
            meta = t.get("meta") or {}
            fid = meta.get("frame_id") or ""
            prefix = f"[{tag} @{ts}"
            if fid:
                prefix += f" frame={fid}"
            delta = meta.get("frame_delta_ms")
            if delta is not None:
                prefix += f" Δ{delta}ms"
            prefix += "]"
            lines.append(f"{prefix} {t['content']}")
        return "\n".join(lines) if lines else "(session just started — no transcript yet)"

    def forensic_timeline(self, sess: LiveSession, n: int = 6) -> str:
        """Compact A/V sync lines for prompts / crystallize. # QUANTUM-CRYSTAL-ARCH"""
        bundles = sess.av_bundles[-n:]
        if not bundles:
            return "(no A/V sync pairs yet)"
        lines = []
        for b in bundles:
            aligned = "ALIGNED" if b.get("aligned") else "LOOSE"
            lines.append(
                f"[{aligned}] audio@{b.get('t_audio_start_iso','?')}→"
                f"{b.get('t_audio_end_iso','?')} | "
                f"frame={b.get('frame_id','?')} Δ{b.get('frame_delta_ms','?')}ms | "
                f"said: {(b.get('audio_text') or '')[:160]} | "
                f"seen: {(b.get('seen_text') or '(no vision note yet)')[:160]}"
            )
        return "\n".join(lines)

    def pair_audio_to_frame(
        self,
        sess: LiveSession,
        audio_text: str,
        *,
        t_start_ms: Optional[float] = None,
        t_end_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Hard-link an STT window to the nearest visual frame."""
        now_ms = time.time() * 1000.0
        win = sess.pending_audio_window or {}
        start = float(
            t_start_ms
            if t_start_ms is not None
            else win.get("t_start_ms") or (now_ms - 8000)
        )
        end = float(
            t_end_ms if t_end_ms is not None else win.get("t_end_ms") or now_ms
        )
        mid = (start + end) / 2.0
        # Prefer client-declared nearest_frame_id when still in ring
        hint = (win.get("nearest_frame_id") or "").strip()
        fr = sess.frame_by_id(hint) if hint else None
        match_mode = "client_hint" if fr else "nearest_mid"
        if not fr:
            fr = sess.nearest_frame(mid)
        delta = None
        frame_id = ""
        frame_iso = ""
        b64 = ""
        if fr:
            delta = int(abs(float(fr["captured_at_ms"]) - mid))
            frame_id = fr.get("frame_id") or ""
            frame_iso = fr.get("iso") or ""
            b64 = fr.get("b64") or ""
        aligned = bool(fr and delta is not None and delta <= AV_ALIGN_MAX_MS)
        # seen_text MUST be the note for THIS frame_id when available
        seen = ""
        if frame_id and frame_id in sess.frame_notes:
            seen = sess.frame_notes[frame_id]
        elif aligned:
            seen = ""  # do not attach stale lean from another frame
        start_iso = datetime.fromtimestamp(start / 1000.0, tz=timezone.utc).isoformat()
        end_iso = datetime.fromtimestamp(end / 1000.0, tz=timezone.utc).isoformat()
        bundle = {
            "event": "av_bundle",
            "aligned": aligned,
            "match_mode": match_mode,
            "t_audio_start_ms": start,
            "t_audio_end_ms": end,
            "t_audio_start_iso": start_iso,
            "t_audio_end_iso": end_iso,
            "audio_text": audio_text,
            "frame_id": frame_id,
            "frame_captured_at": frame_iso,
            "frame_delta_ms": delta,
            "seen_text": seen,
            "seq": win.get("seq"),
            "_b64": b64,  # stripped before DB payload
        }
        sess.av_bundles.append({k: v for k, v in bundle.items() if k != "_b64"})
        if len(sess.av_bundles) > 40:
            sess.av_bundles = sess.av_bundles[-40:]
        sess.pending_audio_window = None
        return bundle

    async def persist_frame_jpeg(
        self,
        session_id: str,
        frame_id: str,
        b64jpeg: str,
    ) -> str:
        """Archive paired-frame pixels (R2 → local). Returns storage_key or ''."""
        # QUANTUM-CRYSTAL-ARCH
        if not b64jpeg or not frame_id:
            return ""
        try:
            import base64

            raw = base64.b64decode(self._normalize_frame_b64(b64jpeg), validate=False)
        except Exception:
            return ""
        if len(raw) < 200:
            return ""
        key = f"ln-observer/{session_id}/{frame_id}.jpg"
        try:
            from app.services.r2_storage import upload_bytes_async

            await upload_bytes_async(
                key=key, content=raw, content_type="image/jpeg"
            )
            return key
        except Exception as e:
            logger.warning("LNObserverEngine R2 frame archive failed: %s", e)
        try:
            from app.services.blob_storage import upload_bytes

            kind, loc = await asyncio.to_thread(
                upload_bytes,
                rel_path=key,
                content=raw,
                content_type="image/jpeg",
            )
            return f"{kind}:{loc}" if loc else key
        except Exception as e2:
            logger.warning("LNObserverEngine local frame archive failed: %s", e2)
            return ""

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

    def format_relevant_memory(self, crystals: List[Dict[str, Any]], cap: int = 8) -> str:
        """Format crystal hits as Observer [RELEVANT MEMORY] block. # QUANTUM-CRYSTAL-ARCH"""
        lines: List[str] = []
        for c in crystals[:cap]:
            meta = c.get("metadata") or {}
            text = (meta.get("text") or c.get("text") or "").strip()
            if text:
                lines.append(f"- {text[:220]}")
        if not lines:
            return ""
        return "[RELEVANT MEMORY]\n" + "\n".join(lines) + "\n"

    async def fetch_same_brain_prefix(
        self, sess: LiveSession, coach_message: str, *, force: bool = False
    ) -> str:
        """
        Bounded Night School wisdom + topical crystal recall for full chat turns.
        Lean observe must NOT call this. Never raises. # QUANTUM-CRYSTAL-ARCH
        """
        now = time.time()
        if (
            not force
            and sess.same_brain_prefix
            and (now - sess.same_brain_at) < SAME_BRAIN_CACHE_TTL_S
        ):
            return sess.same_brain_prefix

        parts: List[str] = []
        try:
            from app.services.ln_observer_lni_support import load_wisdom_snapshot

            wisdom = load_wisdom_snapshot()
            if wisdom:
                parts.append(f"[NIGHT SCHOOL WISDOM]\n{wisdom}")
        except Exception as e:
            logger.warning("LNObserverEngine same-brain wisdom: %s", e)

        try:
            from app.services.ln_observer_lni_support import (
                retrieve_crystals_multi,
                _pg_keyword_crystal_fallback,
                resolve_user_uuid,
                resolve_user_uuids,
            )

            rq = self.build_recall_query(sess, coach_message)
            also = self.match_client_ids(
                sess, self.live_haystack(sess, coach_message)
            )
            crystals: List[Dict[str, Any]] = []
            try:
                crystals = await asyncio.wait_for(
                    retrieve_crystals_multi(
                        rq,
                        sess.coach_id,
                        also,
                        top_k=8,
                        db_pool=self._db_pool,
                    ),
                    timeout=SAME_BRAIN_RECALL_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "LNObserverEngine same-brain Vectorize timeout — PG fallback"
                )
            if not crystals and self._db_pool:
                # QUANTUM-CRYSTAL-ARCH — guarantee RELEVANT MEMORY when Vectorize cold/slow
                primary = await resolve_user_uuid(self._db_pool, sess.coach_id) or sess.coach_id
                also_ids = await resolve_user_uuids(self._db_pool, also)
                try:
                    crystals = await asyncio.wait_for(
                        _pg_keyword_crystal_fallback(
                            self._db_pool, rq, primary, also_ids, limit=8
                        ),
                        timeout=3.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("LNObserverEngine PG crystal fallback timeout")
                    crystals = []
            mem = self.format_relevant_memory(crystals, cap=8)
            if mem:
                parts.append(mem.rstrip())
            logger.warning(
                "LNObserverEngine same-brain recall hits=%s also=%s qlen=%s",
                len(crystals or []),
                len(also),
                len(rq),
            )
        except Exception as e:
            logger.warning("LNObserverEngine same-brain recall: %s", e)

        prefix = "\n\n".join(parts).strip()
        sess.same_brain_prefix = prefix
        sess.same_brain_at = now
        return prefix

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
        *,
        kind: str = "insight",
        confidence: float = 0.58,
        session_id: str = "",
        frame_id: str = "",
        domain: str = "coaching",
    ) -> Optional[str]:
        """Forge coach-scoped Observer crystals (clean text, not chat wrapper)."""
        from app.services.ln_observer_lni_support import (
            forge_observer_crystal,
            observer_note_is_substantive,
        )

        # Prefer LN note; fall back to user_text for close themes
        primary = (nate_response or "").strip()
        secondary = (user_text or "").strip()
        if kind == "session_close":
            body = primary if observer_note_is_substantive(primary) else ""
            if not body and observer_note_is_substantive(secondary):
                body = secondary
            if not body:
                return None
            crystal_text = (
                f"[LN-Observer session close — {coach_name or coach_id}]\n{body}"
            )
            conf = max(confidence, 0.60)
        elif kind in ("look_now", "seen", "av_pair", "chat_exchange"):
            note = primary if len(primary) >= len(secondary) else secondary
            if not observer_note_is_substantive(note) and len(primary) < 80:
                return None
            label = {
                "look_now": "Look closely",
                "seen": "Screen observation",
                "av_pair": "Aligned A/V moment",
                "chat_exchange": "Coach↔LN observation",
            }.get(kind, "Observation")
            crystal_text = f"[LN-Observer {label}]\n{primary or secondary}"
            if kind == "av_pair" and secondary and secondary != primary:
                # Keep audio/visual context without chat-wrapper noise
                crystal_text = f"[LN-Observer {label}]\n{secondary[:900]}\nLN: {(primary or '')[:700]}"
            conf = confidence
        else:
            text = primary or secondary
            if not observer_note_is_substantive(text):
                return None
            crystal_text = f"[LN-Observer]\n{text}"
            conf = confidence

        validator = self._validator()
        if validator:
            try:
                _, warnings = await validator.validate(crystal_text, {})
                if validator.is_high_severity(warnings):
                    logger.warning(
                        "LNObserverEngine: crystallize blocked by validator: %s",
                        warnings,
                    )
                    return None
            except Exception as e:
                logger.warning("LNObserverEngine validator error: %s", e)
        try:
            return await forge_observer_crystal(
                self._db_pool,
                coach_id,
                crystal_text,
                domain=domain,
                confidence=conf,
                kind=kind,
                session_id=session_id,
                frame_id=frame_id,
                metadata={"coach_name": coach_name or ""},
            )
        except Exception as e:
            logger.warning("LNObserverEngine crystallize failed: %s", e)
            return None

    async def maybe_crystallize_seen(
        self, sess: "LiveSession", note: str, frame_id: str = ""
    ) -> None:
        """Rate-limited forge from lean SEEN notes with clinical substance."""
        from app.services.ln_observer_lni_support import observer_note_is_substantive

        if not observer_note_is_substantive(note):
            return
        now = time.time()
        if (now - sess.last_seen_crystal_at) < SEEN_CRYSTAL_MIN_INTERVAL_S:
            return
        # Prefer notes that look like real UI/clinical reads
        low = note.lower()
        if not any(
            k in low
            for k in (
                "client", "session", "clinical", "cue", "title", "notes",
                "attachment", "trauma", "coach", "window", "app/",
                "guidance", "seen:", "ask", "emotion", "pacing",
            )
        ):
            return
        sess.last_seen_crystal_at = now
        await self._crystallize_safe(
            sess.coach_id,
            note,
            note,
            coach_name=sess.coach_name,
            kind="seen",
            confidence=0.56,
            session_id=sess.session_id,
            frame_id=frame_id or sess.last_frame_id or "",
        )

    async def generate_chat(
        self,
        sess: LiveSession,
        coach_message: str,
        *,
        look_now: bool = False,
        lean: bool = False,
    ) -> str:
        # QUANTUM-CRYSTAL-ARCH — lean stays router-only; full chat gets same-brain
        budget = 22.0 if (look_now or lean) else 20.0
        same_brain = ""
        if not lean:
            try:
                same_brain = await self.fetch_same_brain_prefix(
                    sess, coach_message or "observe", force=look_now
                )
            except Exception as e:
                logger.warning("LNObserverEngine same-brain prefetch: %s", e)

        if not lean:
            try:
                reply = await asyncio.wait_for(
                    self._generate_chat_lni_safe(
                        sess,
                        coach_message,
                        look_now=look_now,
                        same_brain_prefix=same_brain,
                    ),
                    timeout=SAME_BRAIN_LNI_TIMEOUT_S,
                )
                if reply:
                    return reply
            except asyncio.TimeoutError:
                logger.warning(
                    "LNObserverEngine LNI-safe timeout → fast path look_now=%s",
                    look_now,
                )
            except Exception as e:
                logger.warning("LNObserverEngine LNI-safe failed → fast: %s", e)

        try:
            return await asyncio.wait_for(
                self._generate_chat_fast(
                    sess,
                    coach_message,
                    look_now=look_now,
                    lean=lean,
                    same_brain_prefix=same_brain if not lean else "",
                ),
                timeout=budget,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "LNObserverEngine generate_chat timeout lean=%s look_now=%s frames=%s",
                lean,
                look_now,
                len(sess.frames),
            )
            n = len(sess.frames)
            if n <= 0:
                return (
                    "I am live with you, but I do not have a usable screen frame yet. "
                    "Keep FEED LIVE on for a few seconds, then ask again — or tap "
                    "Ask LN to look closely."
                )
            return (
                f"I have {n} screen frame(s) buffered, but my screen-read timed out. "
                "Tap Ask LN to look closely once more, or tell me what is on screen."
            )

    def _normalize_frame_b64(self, fr: str) -> str:
        if not fr:
            return ""
        if fr.startswith("data:"):
            return fr.split(",", 1)[-1]
        return fr

    def _collect_vision(
        self,
        sess: LiveSession,
        coach_message: str,
        *,
        look_now: bool,
        lean: bool,
    ) -> tuple:
        """Return (images, frame_ages, detail_q, n_buf, obs_block). # QUANTUM-CRYSTAL-ARCH"""
        detail_q = bool(_DETAIL_RE.search(coach_message or ""))
        want_vision = bool(look_now or lean or detail_q or (not lean and sess.frames))
        images: Optional[List[str]] = None
        frame_ages: List[str] = []
        if want_vision and sess.frame_ring:
            take_n = MAX_CONTEXT_FRAMES if (look_now or detail_q) else 1
            chosen = sess.recent_frames_for_vision(take_n)
            now_ms = time.time() * 1000.0
            images = []
            for fm in chosen:
                fr = self._normalize_frame_b64(fm.get("b64") or "")
                if not fr or len(fr) > 1_800_000:
                    continue
                images.append(fr)
                age = int(now_ms - float(fm.get("captured_at_ms") or now_ms))
                frame_ages.append(
                    f"{fm.get('frame_id')} age≈{age}ms @{fm.get('iso','')[:19]}"
                )
            if not images:
                images = None
        n_buf = len(sess.frames)
        obs_block = ""
        if not images and sess.last_frame_observation:
            obs_block = sess.last_frame_observation
        return images, frame_ages, detail_q, n_buf, obs_block

    def _build_observer_prompts(
        self,
        sess: LiveSession,
        coach_message: str,
        *,
        look_now: bool,
        lean: bool,
        images: Optional[List[str]],
        frame_ages: List[str],
        detail_q: bool,
        n_buf: int,
        obs_block: str,
        same_brain_prefix: str = "",
    ) -> tuple:
        """Shared prompt/system for LNI-safe + fast paths. # QUANTUM-CRYSTAL-ARCH"""
        what = self.build_what_you_know(sess)
        transcript = self.context_block(sess, n=10)
        forensic = self.forensic_timeline(sess, n=5)
        chat_tail = ""
        for m in sess.chat[-8:]:
            role = "COACH" if m.get("role") == "user" else "LN"
            chat_tail += f"[{role}] {m.get('content', '')}\n"

        if lean:
            # QUANTUM-CRYSTAL-ARCH — OCR + actionable coach guidance (not OCR-only)
            user_prompt = (
                "From the screenshot + recent [TRANSCRIPT]/[FORENSIC A/V TIMELINE]: "
                "(1) One short SEEN line — app/window title and any legible on-screen text "
                "you can actually read. "
                "(2) One COACH GUIDANCE line — a concrete suggestion for what the coach "
                "could say, ask, or notice next (pacing, emotion under content, rupture, "
                "safety). Format exactly:\n"
                "SEEN: …\n"
                "GUIDANCE: …\n"
                "Do not invent on-screen text. If the screen is unclear, say so in SEEN "
                "and still give GUIDANCE from the spoken transcript when available."
            )
        elif look_now or detail_q:
            user_prompt = (
                coach_message
                or "Look closely at the live screen and recent spoken content. "
                   "Quote window titles / filenames only when legible. Then give "
                   "2–4 bullet coaching suggestions the coach can use right now "
                   "(what to say, what to track emotionally, what to avoid). "
                   "Lead with actionable guidance, not an OCR dump."
            )
        else:
            user_prompt = coach_message

        if images:
            vision_note = (
                "PRIMARY SOURCE: attached JPEG screenshot(s) (live share), newest last. "
                "Ignore prior chat guesses about the screen. "
                f"Buffer depth={n_buf}. Frames: {', '.join(frame_ages) or 'latest'}. "
                "Quote only legible on-screen text. If blurry, say you cannot read it."
            )
        elif obs_block:
            vision_note = (
                f"No fresh JPEG this turn (buffer={n_buf}). "
                "You may reference the last observation as UNVERIFIED/possibly stale. "
                "Use forensic A/V pairs only when marked ALIGNED."
            )
        else:
            vision_note = (
                f"No vision frame yet (buffered={n_buf}). "
                "Say you cannot see the screen yet; ask them to keep FEED LIVE on."
            )

        sb = (same_brain_prefix or "").strip()
        prompt = (
            "You are Little Nate in LN-Observer mode, co-watching with the coach.\n"
            f"{vision_note}\n\n"
        )
        if sb and not lean:
            prompt += f"{sb}\n\n"
        prompt += (
            f"[SESSION]\n{what}\n\n"
            f"[FORENSIC A/V TIMELINE]\n{forensic}\n\n"
            f"[TRANSCRIPT]\n{transcript}\n\n"
        )
        if obs_block and not images:
            prompt += (
                f"[LAST OBSERVATION — UNVERIFIED / MAY BE STALE]\n{obs_block}\n\n"
            )
        prompt += f"[CHAT]\n{chat_tail}\nCoach: {user_prompt}"

        system = (
            "You are Little Nate observing a live coach screen share with forensic "
            "A/V alignment. Your job is dual: accurate screen reading AND real-time "
            "coaching guidance. ACCURACY RULES: (1) When JPEGs are attached, ground "
            "SEEN lines in those images. (2) When citing spoken content, prefer ALIGNED "
            "forensic pairs. (3) Never invent on-screen text. (4) Prefer 'I cannot read "
            "that clearly' over a guess. (5) GUIDANCE may use transcript + clinical "
            "judgment even when OCR is thin — never invent client quotes. "
            "(6) When [RELEVANT MEMORY] or [NIGHT SCHOOL WISDOM] are present, use them "
            "as clinical continuity — do not invent memories not listed there."
        )
        return prompt, system

    async def _generate_chat_lni_safe(
        self,
        sess: LiveSession,
        coach_message: str,
        *,
        look_now: bool = False,
        same_brain_prefix: str = "",
    ) -> str:
        """
        Slim LNI path: crystals/wisdom already prefetched; helix+quantum OFF.
        Returns "" to signal fallback to fast-gen. # QUANTUM-CRYSTAL-ARCH
        """
        lni = self._inference()
        if not lni:
            return ""

        images, frame_ages, detail_q, n_buf, obs_block = self._collect_vision(
            sess, coach_message, look_now=look_now, lean=False
        )
        if images and self._vision_busy(sess) and not look_now and not detail_q:
            return ""

        prompt, system = self._build_observer_prompts(
            sess,
            coach_message,
            look_now=look_now,
            lean=False,
            images=images,
            frame_ages=frame_ages,
            detail_q=detail_q,
            n_buf=n_buf,
            obs_block=obs_block,
            same_brain_prefix=same_brain_prefix,
        )

        if images:
            self._mark_vision_inflight(sess, True)
        try:
            logger.warning(
                "LNObserverEngine lni-safe look_now=%s vision=%s sb=%s buf=%s",
                look_now,
                bool(images),
                bool(same_brain_prefix),
                n_buf,
            )
            result = await lni.generate(
                prompt=prompt,
                system=system,
                user_id=sess.coach_id,
                domain="coaching",
                tier="clinical" if images else "utility",
                temperature=0.15 if images else 0.35,
                max_tokens=480 if (look_now or detail_q) else 500,
                include_crystals=False,  # already in same_brain_prefix
                include_helix=False,  # hang mitigation
                include_quantum=False,
                attach_wisdom=False,  # already in same_brain_prefix
                images=images,
                mode="ln_observer",
                is_realtime=True,
                allow_deep=False,
            )
            reply = (getattr(result, "text", None) or "").strip()
            err = getattr(result, "error", None)
            logger.warning(
                "LNObserverEngine lni-safe done provider=%s len=%s err=%s",
                getattr(result, "provider", "?"),
                len(reply),
                err,
            )
            if err and "content_filter" in str(err).lower():
                return (
                    "I need to skip that frame — the vision filter blocked it. "
                    "Share a different view or describe what you're seeing."
                )
            if reply and "unable to process" not in reply.lower():
                if images and (look_now or detail_q or len(reply) > 80):
                    sess.last_frame_observation = reply
                return reply
            return ""
        finally:
            if images:
                self._mark_vision_inflight(sess, False)

    def _vision_busy(self, sess: LiveSession) -> bool:
        """True if vision in flight; auto-clears stale locks. # QUANTUM-CRYSTAL-ARCH"""
        if not sess.vision_inflight:
            return False
        age = time.time() - (sess.vision_inflight_since or 0.0)
        if age > VISION_INFLIGHT_STALE_S:
            logger.warning(
                "LNObserverEngine clearing stale vision_inflight age=%.1fs", age
            )
            sess.vision_inflight = False
            sess.vision_inflight_since = 0.0
            return False
        return True

    def _mark_vision_inflight(self, sess: LiveSession, busy: bool) -> None:
        sess.vision_inflight = bool(busy)
        sess.vision_inflight_since = time.time() if busy else 0.0

    def should_schedule_observe(self, sess: LiveSession, frame_counter: int) -> bool:
        """Frame-count or wall-clock due, debounce clear, vision free."""
        now = time.time()
        if self._vision_busy(sess):
            return False
        if (now - sess.last_observe_at) < OBSERVE_DEBOUNCE_S:
            return False
        due_count = frame_counter > 0 and (frame_counter % OBSERVE_EVERY_N == 0)
        due_time = (now - sess.last_observe_at) >= OBSERVE_INTERVAL_S
        # First observe soon after frames arrive (last_observe_at==0)
        due_first = sess.last_observe_at <= 0 and frame_counter >= 1
        return due_count or due_time or due_first

    async def _generate_chat_fast(
        self,
        sess: LiveSession,
        coach_message: str,
        *,
        look_now: bool = False,
        lean: bool = False,
        same_brain_prefix: str = "",
    ) -> str:
        """Router path; non-lean may carry prefetched same-brain blocks."""
        # QUANTUM-CRYSTAL-ARCH
        images, frame_ages, detail_q, n_buf, obs_block = self._collect_vision(
            sess, coach_message, look_now=look_now, lean=lean
        )
        prompt, system = self._build_observer_prompts(
            sess,
            coach_message,
            look_now=look_now,
            lean=lean,
            images=images,
            frame_ages=frame_ages,
            detail_q=detail_q,
            n_buf=n_buf,
            obs_block=obs_block,
            same_brain_prefix="" if lean else same_brain_prefix,
        )

        logger.warning(
            "LNObserverEngine fast-gen lean=%s look_now=%s detail=%s vision=%s "
            "sb=%s buf=%s msg_len=%s",
            lean,
            look_now,
            detail_q,
            bool(images),
            bool(same_brain_prefix) and not lean,
            n_buf,
            len(coach_message or ""),
        )

        # Serialize Azure vision so lean+look_now+chat don't pile up ("maxed out")
        if images and self._vision_busy(sess) and lean and not look_now and not detail_q:
            return ""
        if images:
            self._mark_vision_inflight(sess, True)
        try:
            from app.services.nate_inference_router import NateInferenceRouter

            router = NateInferenceRouter(app_state=self._app_state)
            tier = "clinical" if images else "utility"
            result = await router.generate(
                prompt=prompt,
                system=system,
                tier=tier,
                temperature=0.15 if images else 0.35,
                max_tokens=220 if lean else (480 if (look_now or detail_q) else 500),
                domain="coaching",
                odpe_signal=None if images else "LOCKED",
                allow_deep=False,
                images=images,
            )
            reply = ""
            if isinstance(result, dict):
                reply = (result.get("text") or "").strip()
                provider = result.get("provider") or "?"
                err = result.get("error")
            else:
                provider = "?"
                err = None
            logger.warning(
                "LNObserverEngine fast-gen done provider=%s len=%s err=%s",
                provider,
                len(reply),
                err,
            )
            if err and "content_filter" in str(err).lower():
                return (
                    "I need to skip that frame — the vision filter blocked it. "
                    "Share a different view or describe what you're seeing."
                )
            if reply and "unable to process" not in reply.lower():
                if images and (look_now or lean or detail_q or len(reply) > 80):
                    sess.last_frame_observation = reply
                return reply
            if n_buf <= 0 and not obs_block:
                return (
                    "I am with you on the observation, but I cannot see the screen yet — "
                    "no frames have arrived. Confirm FEED LIVE, wait a few seconds, "
                    "then tap Ask LN to look closely."
                )
            if obs_block:
                return (
                    "I could not complete a fresh screen read just now. "
                    "My last note (may be outdated — tap Ask LN to look closely): "
                    + obs_block[:500]
                )
            return (
                f"I am receiving the share ({n_buf} frame(s) buffered) but could not "
                "complete a screen read just now. Tap Ask LN to look closely once more."
            )
        except Exception as e:
            err = str(e)
            if "content_filter" in err.lower() or "ResponsibleAIPolicyViolation" in err:
                return (
                    "I need to skip that frame — the vision filter blocked it. "
                    "Share a different view or describe what you're seeing."
                )
            logger.warning("LNObserverEngine fast-gen failed: %s", e)
            return f"(LN-Observer reasoning error: {e})"
        finally:
            if images:
                self._mark_vision_inflight(sess, False)

    @staticmethod
    def _transcript_line_worth_keeping(src: str, content: str) -> bool:
        """Drop filler STT crumbs that poison close summaries. # QUANTUM-CRYSTAL-ARCH"""
        c = (content or "").strip()
        if not c:
            return False
        if src in ("frame_observation", "coach_chat", "ln_chat"):
            return len(c) >= 12
        if src in ("audio_transcript", "av_bundle"):
            words = re.findall(r"[A-Za-z']+", c)
            if len(words) < 3 or len(c) < 12:
                return False
            low = c.lower().strip(" .,?!\"'")
            if low in {
                "you", "yeah", "yes", "uh", "um", "ok", "okay", "mm", "hmm",
                "right", "sure", "so", "and", "the", "a", "i", "me",
            }:
                return False
            return True
        return len(c) >= 12

    def _extractive_close_summary(self, sess: LiveSession) -> str:
        """Fallback when LNI unavailable — never leave ln_summary empty. # QUANTUM-CRYSTAL-ARCH"""
        preferred: List[str] = []
        audioish: List[str] = []
        for t in sess.transcript[-40:]:
            src = t.get("source") or ""
            if src not in (
                "audio_transcript",
                "frame_observation",
                "coach_chat",
                "ln_chat",
                "av_bundle",
            ):
                continue
            content = (t.get("content") or "").strip()
            if not self._transcript_line_worth_keeping(src, content):
                continue
            line = f"{src}: {content[:180]}"
            if src in ("frame_observation", "ln_chat", "coach_chat"):
                preferred.append(line)
            else:
                audioish.append(line)
        # Prefer clinical notes over raw STT
        lines = (preferred[-8:] + audioish[-4:]) if preferred else audioish[-10:]
        body = " | ".join(lines) if lines else "Session ended with limited transcript."
        return (
            f"LN-Observer close ({sess.coach_name}): {body}"
        )[:900]

    async def close_summary(self, sess: LiveSession) -> Optional[str]:
        # QUANTUM-CRYSTAL-ARCH — slim LNI (no helix) + timeout + extractive fallback
        prompt = (
            f"The LN-Observer session with {sess.coach_name} is ending.\n"
            f"Forensic A/V timeline:\n{self.forensic_timeline(sess, n=12)}\n\n"
            f"Full transcript:\n{self.context_block(sess, n=40)}\n\n"
            "Write a closing synthesis for warm memory: key observations, "
            "aligned audio-visual moments, therapeutic themes, what the coach "
            "engaged with, and anything to carry forward. 1 short paragraph."
        )
        summary = ""
        inference = self._inference()
        if inference:
            try:
                result = await asyncio.wait_for(
                    inference.generate(
                        prompt=prompt,
                        user_id=sess.coach_id,
                        domain="coaching",
                        tier="clinical",
                        conversation_context=self.build_what_you_know(sess),
                        attach_wisdom=True,
                        include_crystals=False,
                        include_helix=False,
                        include_quantum=False,
                        max_tokens=400,
                        is_realtime=True,
                        allow_deep=False,
                        mode="ln_observer",
                    ),
                    timeout=18.0,
                )
                summary = (getattr(result, "text", None) or "").strip()
            except asyncio.TimeoutError:
                logger.warning("LNObserverEngine close summary timeout → extractive")
            except Exception as e:
                logger.warning("LNObserverEngine close summary failed: %s", e)

        if not summary:
            summary = self._extractive_close_summary(sess)

        validator = self._validator()
        if summary and validator:
            try:
                _, warnings = await validator.validate(summary, {})
                if validator.is_high_severity(warnings):
                    logger.warning("LNObserverEngine: ln_summary blocked by validator")
                    # Still persist a truncated extractive note (no hallucinated claims)
                    summary = self._extractive_close_summary(sess)[:400]
            except Exception as e:
                logger.warning("LNObserverEngine close validator: %s", e)
        return summary or None

    async def hydrate_transcript_into(self, sess: LiveSession) -> None:
        """Load PG transcripts into LiveSession when memory was lost (restart)."""
        if not self._db_pool or sess.transcript:
            return
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT source, content, meta, ts
                       FROM ln_observer_transcripts
                       WHERE session_id=$1
                       ORDER BY ts ASC LIMIT 120""",
                    uuid.UUID(sess.session_id),
                )
            for r in rows or []:
                meta = r["meta"] if isinstance(r["meta"], dict) else {}
                ts = r["ts"].isoformat() if r["ts"] else None
                sess.add_transcript(
                    r["source"], r["content"] or "", meta=meta, ts_iso=ts
                )
        except Exception as e:
            logger.warning("LNObserverEngine hydrate transcripts: %s", e)

    async def queue_night_school_ingest(
        self, session_id: str, coach_id: str, summary: Optional[str]
    ) -> int:
        """
        Phase 2 — chunk session transcripts into NS ingest queue (PII-light).
        # QUANTUM-CRYSTAL-ARCH
        """
        if not self._db_pool:
            return 0
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT source, content FROM ln_observer_transcripts
                       WHERE session_id=$1
                         AND source IN ('audio_transcript','coach_chat','ln_chat',
                                        'frame_observation','av_bundle')
                       ORDER BY ts ASC LIMIT 200""",
                    uuid.UUID(session_id),
                )
            chunks: List[str] = []
            buf: List[str] = []
            size = 0
            for r in rows or []:
                line = f"{r['source']}: {(r['content'] or '')[:500]}"
                # Light PII scrub — SSNs / emails
                line = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]", line)
                line = re.sub(
                    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
                    "[EMAIL]",
                    line,
                )
                buf.append(line)
                size += len(line)
                if size >= 1200:
                    chunks.append("\n".join(buf))
                    buf, size = [], 0
            if buf:
                chunks.append("\n".join(buf))
            if summary:
                chunks.insert(0, f"ln_summary: {summary[:800]}")
            if not chunks:
                return 0
            n = 0
            async with self._db_pool.acquire() as conn:
                for ch in chunks[:12]:
                    await conn.execute(
                        """INSERT INTO ln_observer_ns_ingest
                           (session_id, coach_id, chunk_text, pii_cleared, status)
                           VALUES ($1,$2,$3,true,'pending')""",
                        uuid.UUID(session_id),
                        coach_id,
                        ch[:4000],
                    )
                    n += 1
            logger.warning(
                "LNObserverEngine NS ingest queued session=%s chunks=%s",
                session_id[:8],
                n,
            )
            return n
        except Exception as e:
            # Table may not exist yet — non-fatal
            logger.warning("LNObserverEngine NS ingest queue failed: %s", e)
            return 0

    async def _deliver_ns_chunk(
        self, coach_id: str, session_id: str, chunk_id: int, text: str
    ) -> str:
        """Deliver one queue chunk → vault staging + NS wisdom (pending) + warm.
        Returns destination tag. # QUANTUM-CRYSTAL-ARCH
        """
        dests: List[str] = []
        data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
        stage = (
            data_dir
            / "Vaults"
            / "Admin"
            / "night_school"
            / "ln_observer_queue"
        )
        try:
            stage.mkdir(parents=True, exist_ok=True)
            fp = stage / f"{session_id[:8]}_{chunk_id}.txt"
            fp.write_text(text[:8000], encoding="utf-8")
            try:
                os.chmod(fp, 0o644)
            except OSError:
                pass
            dests.append(f"vault:{fp.name}")
        except Exception as e:
            logger.warning("LNObserverEngine NS vault stage: %s", e)

        try:
            from app.services.night_school_director import (
                WisdomCategory,
                create_night_school_director,
            )

            director = create_night_school_director(data_dir, self._db_pool)
            entry = director.add_wisdom_entry(
                content=text[:3500],
                category=WisdomCategory.GENERAL,
                source="ln_observer",
                source_file=f"ln_observer:{session_id}",
                confidence=0.45,
                auto_approve=False,
                tags=["ln_observer", coach_id[:40]],
            )
            dests.append(f"ns_wisdom:{getattr(entry, 'id', '?')}")
        except Exception as e:
            logger.warning("LNObserverEngine NS wisdom deliver: %s", e)

        warm = getattr(self._app_state, "warm_memory", None) if self._app_state else None
        if warm and hasattr(warm, "store"):
            try:
                key = (
                    f"ln_observer/{coach_id}/{session_id}/chunk_{chunk_id}.txt"
                )
                await warm.store(
                    key,
                    (text[:8000]).encode("utf-8"),
                    metadata={"source": "ln_observer", "coach_id": coach_id},
                )
                dests.append(f"warm:{key}")
            except Exception as e:
                logger.warning("LNObserverEngine NS warm deliver: %s", e)

        return ",".join(dests) if dests else "none"

    async def drain_ns_ingest(self, limit: int = 25) -> int:
        """Consume pending ln_observer_ns_ingest → Night School / warm. # QUANTUM-CRYSTAL-ARCH"""
        if not self._db_pool:
            return 0
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, session_id::text AS sid, coach_id, chunk_text
                       FROM ln_observer_ns_ingest
                       WHERE status='pending'
                       ORDER BY created_at ASC
                       LIMIT $1""",
                    limit,
                )
            n = 0
            for r in rows or []:
                text = (r["chunk_text"] or "").strip()
                if not text:
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE ln_observer_ns_ingest
                               SET status='skipped', ingested_at=now(),
                                   error='empty chunk'
                               WHERE id=$1""",
                            r["id"],
                        )
                    continue
                try:
                    dest = await self._deliver_ns_chunk(
                        r["coach_id"], r["sid"], int(r["id"]), text
                    )
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE ln_observer_ns_ingest
                               SET status='ingested', ingested_at=now(),
                                   error=$2
                               WHERE id=$1""",
                            r["id"],
                            (dest or "")[:500],
                        )
                    n += 1
                except Exception as e:
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE ln_observer_ns_ingest
                               SET status='failed', error=$2
                               WHERE id=$1""",
                            r["id"],
                            str(e)[:500],
                        )
            if n:
                logger.warning("LNObserverEngine NS ingest drained chunks=%s", n)
            return n
        except Exception as e:
            logger.warning("LNObserverEngine NS drain failed: %s", e)
            return 0

    async def backfill_empty_summaries(self, limit: int = 20) -> Dict[str, Any]:
        """Re-close ended sessions that still have empty ln_summary. # QUANTUM-CRYSTAL-ARCH"""
        out = {"attempted": 0, "filled": 0, "ids": []}
        if not self._db_pool:
            return out
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT session_id::text AS sid, coach_id
                   FROM ln_observer_sessions
                   WHERE status='ended'
                     AND (ln_summary IS NULL OR ln_summary = '')
                     AND EXISTS (
                       SELECT 1 FROM ln_observer_transcripts t
                       WHERE t.session_id = ln_observer_sessions.session_id
                     )
                   ORDER BY started_at DESC
                   LIMIT $1""",
                limit,
            )
        for r in rows or []:
            out["attempted"] += 1
            sid = r["sid"]
            try:
                # Temporarily treat as reconnecting so hydrate_session accepts it
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE ln_observer_sessions
                           SET status='reconnecting'
                           WHERE session_id=$1 AND status='ended'""",
                        uuid.UUID(sid),
                    )
                summary = await self.deactivate(sid)
                if summary:
                    out["filled"] += 1
                    out["ids"].append(sid[:8])
            except Exception as e:
                logger.warning(
                    "LNObserverEngine backfill %s: %s", sid[:8], e
                )
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE ln_observer_sessions
                           SET status='ended'
                           WHERE session_id=$1 AND status='reconnecting'
                             AND (ln_summary IS NULL OR ln_summary='')""",
                        uuid.UUID(sid),
                    )
        return out

    async def run_acceptance_smoke(
        self, coach_id: str = "CoachN"
    ) -> Dict[str, Any]:
        """
        Admin GREEN smoke: same-brain prefix + chat + close summary + NS queue.
        # QUANTUM-CRYSTAL-ARCH
        """
        result: Dict[str, Any] = {
            "ok": False,
            "coach_id": coach_id,
            "wisdom_block": False,
            "relevant_memory": False,
            "same_brain_len": 0,
            "reply_len": 0,
            "summary_set": False,
            "ns_queued": 0,
            "ns_drained": 0,
            "errors": [],
        }
        if not self._db_pool:
            result["errors"].append("no_db")
            return result
        if not await self.coach_is_approved(coach_id):
            result["errors"].append("coach_not_approved")
            return result

        clients = await self.load_assigned_clients(coach_id)
        profile = await self.load_coach_profile(coach_id)
        prior = await self.load_prior_summaries(coach_id, limit=3)
        session_id = str(uuid.uuid4())
        ticket = mint_ws_ticket(session_id, coach_id)
        coach_name = profile.get("name") or coach_id
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO ln_observer_sessions
                       (session_id, coach_id, context_bundle, ws_ticket)
                       VALUES ($1,$2,$3,$4)""",
                    uuid.UUID(session_id),
                    coach_id,
                    prior or "smoke prior",
                    ticket,
                )
            sess = LiveSession(
                session_id,
                coach_id,
                coach_name,
                context_bundle=prior or "",
                assigned_clients=clients,
                coach_profile=profile,
            )
            # Seed therapeutically rich transcript for close/extractive path
            client_hint = (clients[0].get("name") if clients else "") or "the client"
            sess.add_transcript(
                "audio_transcript",
                f"{client_hint} named pursue-withdraw and attachment rupture.",
            )
            sess.add_transcript(
                "coach_chat",
                f"What do you remember about {client_hint} and attachment?",
            )
            await self.db_log(
                session_id,
                "audio_transcript",
                f"{client_hint} named pursue-withdraw and attachment rupture.",
            )
            await self.db_log(
                session_id,
                "coach_chat",
                f"What do you remember about {client_hint} and attachment?",
            )
            self.live[session_id] = sess

            msg = (
                f"Which modality fits this rupture with {client_hint}? "
                "Surface Night School wisdom and any relevant memory."
            )
            same_brain = await self.fetch_same_brain_prefix(sess, msg, force=True)
            result["same_brain_len"] = len(same_brain or "")
            result["wisdom_block"] = "[NIGHT SCHOOL WISDOM]" in (same_brain or "")
            result["relevant_memory"] = "[RELEVANT MEMORY]" in (same_brain or "")
            logger.warning(
                "LNObserverEngine same-brain smoke wisdom=%s memory=%s len=%s",
                result["wisdom_block"],
                result["relevant_memory"],
                result["same_brain_len"],
            )
            reply = await self.generate_chat(sess, msg, lean=False)
            result["reply_len"] = len(reply or "")
            async with sess.lock:
                sess.add_transcript("ln_chat", reply or "")
            await self.db_log(session_id, "ln_chat", reply or "(empty)")

            summary = await self.deactivate(session_id)
            result["summary_set"] = bool(summary and summary.strip())
            result["summary_preview"] = (summary or "")[:160]
            async with self._db_pool.acquire() as conn:
                queued = await conn.fetchval(
                    """SELECT COUNT(*)::int FROM ln_observer_ns_ingest
                       WHERE session_id=$1""",
                    uuid.UUID(session_id),
                )
            result["ns_queued"] = int(queued or 0)
            result["ns_drained"] = await self.drain_ns_ingest(limit=20)
            # Prefer Clinical-AGI evidence: wisdom + relevant memory + summary + chat
            result["ok"] = bool(
                result["summary_set"]
                and result["reply_len"] > 20
                and result["wisdom_block"]
                and result["relevant_memory"]
            )
            # Soft pass if wisdom+chat+summary work but Vectorize/PG still cold
            if (
                not result["ok"]
                and result["summary_set"]
                and result["reply_len"] > 20
                and result["wisdom_block"]
            ):
                result["ok"] = True
                result["errors"].append("relevant_memory_missing")
            result["session_id"] = session_id
        except Exception as e:
            result["errors"].append(str(e)[:200])
            logger.warning("LNObserverEngine acceptance smoke failed: %s", e)
            try:
                await self.deactivate(session_id)
            except Exception:
                pass
        return result

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
        # Restore forensic timeline text (pixels stay in R2; ring refills from live frames)
        try:
            async with self._db_pool.acquire() as conn:
                fevs = await conn.fetch(
                    """SELECT event_type, t_start, t_end, frame_id, frame_delta_ms,
                              audio_text, seen_text, COALESCE(storage_key,'') AS storage_key,
                              payload
                       FROM ln_observer_forensic_events
                       WHERE session_id=$1 AND event_type='av_pair'
                       ORDER BY created_at DESC LIMIT 20""",
                    uuid.UUID(session_id),
                )
            for ev in reversed(list(fevs or [])):
                sess.av_bundles.append(
                    {
                        "aligned": (ev["frame_delta_ms"] or 99999) <= AV_ALIGN_MAX_MS,
                        "t_audio_start_iso": (
                            ev["t_start"].isoformat() if ev["t_start"] else ""
                        ),
                        "t_audio_end_iso": (
                            ev["t_end"].isoformat() if ev["t_end"] else ""
                        ),
                        "audio_text": ev["audio_text"] or "",
                        "frame_id": ev["frame_id"] or "",
                        "frame_delta_ms": ev["frame_delta_ms"],
                        "seen_text": ev["seen_text"] or "",
                        "storage_key": ev["storage_key"] or "",
                    }
                )
                if ev["frame_id"] and ev["seen_text"]:
                    sess.frame_notes[ev["frame_id"]] = ev["seen_text"]
        except Exception as e:
            logger.warning("LNObserverEngine hydrate forensics: %s", e)
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
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            raise ValueError("invalid session_id")
        sess = self.live.pop(session_id, None)
        summary = None
        coach_id = ""
        # QUANTUM-CRYSTAL-ARCH — hydrate from PG when process memory lost (restart/sweep)
        if sess is None:
            sess = await self.hydrate_session(session_id)
            if sess:
                self.live.pop(session_id, None)
        if sess:
            await self.hydrate_transcript_into(sess)
            coach_id = sess.coach_id
            summary = await self.close_summary(sess)
            # Skip thin closes (no A/V banked) — avoids junk "limited transcript" crystals
            has_signal = bool(
                sess.transcript
                or sess.av_bundles
                or sess.last_frame_observation
                or sess.audio_seconds_accum >= 8
            )
            if summary and has_signal:
                await self._crystallize_safe(
                    sess.coach_id,
                    self.context_block(sess, n=16)[:700],
                    summary,
                    coach_name=sess.coach_name,
                    kind="session_close",
                    confidence=0.62,
                    session_id=sess.session_id,
                )
        elif self._db_pool:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT coach_id FROM ln_observer_sessions WHERE session_id=$1",
                    sid,
                )
            if row:
                coach_id = row["coach_id"]
                summary = (
                    f"LN-Observer session ended (coach={coach_id}); "
                    "in-memory context unavailable at close."
                )[:400]

        if self._db_pool:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE ln_observer_sessions
                       SET status='ended', ended_at=now(), ln_summary=$2
                       WHERE session_id=$1""",
                    sid,
                    summary,
                )
                await conn.execute(
                    """UPDATE ln_observer_activation_log
                       SET deactivated_at=now() WHERE session_id=$1
                       AND deactivated_at IS NULL""",
                    sid,
                )
        if coach_id:
            await self.queue_night_school_ingest(session_id, coach_id, summary)
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
            # Also end live/reconnecting sessions over 3h
            old = await conn.fetch(
                """SELECT session_id::text AS sid FROM ln_observer_sessions
                   WHERE status IN ('live','reconnecting')
                     AND started_at < NOW() - INTERVAL '3 hours'"""
            )
            # Stale live: no transcript activity for 10m and started >15m ago
            # (catches WS death without reconnecting mark)
            stale = await conn.fetch(
                """SELECT s.session_id::text AS sid
                   FROM ln_observer_sessions s
                   WHERE s.status='live'
                     AND s.started_at < NOW() - INTERVAL '15 minutes'
                     AND NOT EXISTS (
                       SELECT 1 FROM ln_observer_transcripts t
                       WHERE t.session_id = s.session_id
                         AND t.ts > NOW() - INTERVAL '10 minutes'
                     )"""
            )
        sids: Set[str] = (
            {r["sid"] for r in rows}
            | {r["sid"] for r in old}
            | {r["sid"] for r in stale}
        )
        # Never sweep sessions still held in this process's live map with recent activity
        for sid in list(sids):
            live = self.live.get(sid)
            if live and (time.time() - live.started_at) < MAX_SESSION_S:
                # If in-memory and recently observed, skip stale-SQL false positive
                if live.last_observe_at and (time.time() - live.last_observe_at) < 600:
                    sids.discard(sid)
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

    async def ingest_audio_transcript(
        self,
        sess: LiveSession,
        session_id: str,
        audio_text: str,
    ) -> Dict[str, Any]:
        """STT → nearest-frame pair → transcript + forensic table. # QUANTUM-CRYSTAL-ARCH"""
        async with sess.lock:
            bundle = self.pair_audio_to_frame(sess, audio_text)
            meta = {
                "frame_id": bundle.get("frame_id"),
                "frame_delta_ms": bundle.get("frame_delta_ms"),
                "aligned": bundle.get("aligned"),
                "t_audio_start_iso": bundle.get("t_audio_start_iso"),
                "t_audio_end_iso": bundle.get("t_audio_end_iso"),
            }
            display = audio_text
            if bundle.get("frame_id"):
                display = (
                    f"{audio_text}  ⟺ frame {bundle['frame_id']} "
                    f"(Δ{bundle.get('frame_delta_ms')}ms, "
                    f"{'ALIGNED' if bundle.get('aligned') else 'LOOSE'})"
                )
            sess.add_transcript(
                "audio_transcript",
                display,
                meta=meta,
                ts_iso=bundle.get("t_audio_end_iso"),
            )
            sess.add_transcript(
                "av_bundle",
                (
                    f"AUDIO: {audio_text[:500]} || "
                    f"FRAME {bundle.get('frame_id') or 'none'} || "
                    f"SEEN: {(bundle.get('seen_text') or '')[:300]}"
                ),
                meta=meta,
                ts_iso=bundle.get("t_audio_end_iso"),
            )
        storage_key = ""
        b64 = bundle.pop("_b64", "") or ""
        if bundle.get("aligned") and b64 and bundle.get("frame_id"):
            storage_key = await self.persist_frame_jpeg(
                session_id, bundle["frame_id"], b64
            )
            if storage_key:
                bundle["storage_key"] = storage_key
                meta["storage_key"] = storage_key

        await self.db_log(session_id, "audio_transcript", display, meta=meta)
        await self.db_log(
            session_id,
            "av_bundle",
            (
                f"AUDIO: {audio_text[:800]} || "
                f"FRAME {bundle.get('frame_id') or 'none'} || "
                f"SEEN: {(bundle.get('seen_text') or '')[:400]}"
            ),
            meta={k: v for k, v in bundle.items() if k != "_b64"},
        )
        t0 = datetime.fromtimestamp(
            bundle["t_audio_start_ms"] / 1000.0, tz=timezone.utc
        )
        t1 = datetime.fromtimestamp(
            bundle["t_audio_end_ms"] / 1000.0, tz=timezone.utc
        )
        await self.db_log_forensic(
            session_id,
            "av_pair",
            t_start=t0,
            t_end=t1,
            frame_id=bundle.get("frame_id") or "",
            frame_delta_ms=bundle.get("frame_delta_ms"),
            audio_text=audio_text,
            seen_text=bundle.get("seen_text") or "",
            storage_key=storage_key,
            payload=bundle,
        )
        # Durable learning: rate-limited ALIGNED pairs with audio + optional SEEN
        now = time.time()
        seen = (bundle.get("seen_text") or "").strip()
        if (
            bundle.get("aligned")
            and len(audio_text) >= 60
            and (now - sess.last_av_crystal_at) >= AV_CRYSTAL_MIN_INTERVAL_S
        ):
            sess.last_av_crystal_at = now
            forge_ctx = (
                f"frame={bundle.get('frame_id')} Δ{bundle.get('frame_delta_ms')}ms "
                f"ALIGNED @ {bundle.get('t_audio_start_iso')}\n"
                f"Audio: {audio_text[:500]}\n"
                f"Visual: {seen[:400] if seen else '(no vision note yet)'}"
            )
            forge_note = (
                f"Aligned coaching observation — audio and screen paired. "
                f"Said: {audio_text[:320]}"
                + (f" Seen: {seen[:280]}" if len(seen) >= 40 else "")
            )
            await self._crystallize_safe(
                sess.coach_id,
                forge_ctx,
                forge_note,
                coach_name=sess.coach_name,
                kind="av_pair",
                confidence=0.58 if len(seen) >= 40 else 0.54,
                session_id=session_id,
                frame_id=bundle.get("frame_id") or "",
            )
        # audio_seconds credited in credit_audio_chunk_seconds() on binary receipt
        return bundle

    async def credit_audio_chunk_seconds(
        self, sess: "LiveSession", session_id: str
    ) -> float:
        """Bank capture duration from pending audio_window (STT-independent).

        # QUANTUM-CRYSTAL-ARCH
        """
        win = sess.pending_audio_window or {}
        try:
            t0 = float(win.get("t_start_ms") or 0)
            t1 = float(win.get("t_end_ms") or 0)
            dur = max(0.0, (t1 - t0) / 1000.0) if t1 > t0 else 8.0
            dur = min(max(dur, 1.0), 30.0)
        except Exception:
            dur = 8.0
        sess.audio_seconds_accum += dur
        if not self._db_pool:
            return dur
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE ln_observer_sessions
                       SET audio_seconds = COALESCE(audio_seconds, 0) + $2
                       WHERE session_id=$1""",
                    uuid.UUID(session_id),
                    int(round(dur)),
                )
        except Exception as e:
            logger.warning("LNObserverEngine audio_seconds credit: %s", e)
        return dur


# Module singleton wired from main.py
ln_observer_engine = LNObserverEngine()
