"""AlphaLN Slice 3 — Shadow observer (Loop A seed).

Background agent that periodically reads recent replies from
`conversation_history` (READ-ONLY) and writes de-identified scoring rows to
`alphaln_shadow_observations`.

Key invariants (see cursor rule alphaln-twin-isolation.mdc):

- **Never writes** to `conversation_history`, `nate_intelligence_crystals`,
  or any production table. Only writes to `alphaln_shadow_observations`.
- **Never stores raw usernames.** Every observation row uses a stable HMAC
  pseudonym derived from ``ALPHALN_OBSERVER_SALT`` (env; process-scoped
  fallback).
- **Dark-shipped**: agent loop is created, but if
  ``ENABLE_ALPHALN_SHADOW_OBSERVER`` is off, ``_tick`` returns immediately
  with a ``flag_off`` status. No DB reads happen when the flag is off.

Scoring is intentionally a heuristic v1 (length + question-mark + reflective
opener). We are seeding the ledger with cheap signal so Slice 4 (console) has
something to display; a real twin scoring model can replace ``_score_reply``
without changing the schema.

Loop close (shadow only): each enabled tick dedups by ``reply_hash``, writes
opinion rows, then stores a rolling pulse on ``app_state.alphaln_shadow_pulse``
and ``last_tick``. Dual-COO Queens / L5 *read* that pulse — this module never
calls ``beat_queen`` (would clobber the Chief heartbeat) and never writes
``l5_observe_event``, ``outcome_envelope``, crystals, or ``conversation_history``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.alphaln_shadow_observer")

_ENV_FLAG = "ENABLE_ALPHALN_SHADOW_OBSERVER"
_ENV_SALT = "ALPHALN_OBSERVER_SALT"

# Cycle: every 5 min when enabled; long sleep otherwise so an empty process
# doesn't spin.
CYCLE_SECONDS_ON = 300
CYCLE_SECONDS_OFF = 900
BATCH_LIMIT = 25       # rows scored per tick
LOOKBACK_MIN = 10      # look at replies newer than this


def is_enabled() -> bool:
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def pulse_from_app_state(app_state: Any) -> Dict[str, Any]:
    """Read-only pulse for Queens / L5 / LN7. Never a write path."""
    raw = getattr(app_state, "alphaln_shadow_pulse", None) if app_state else None
    return dict(raw) if isinstance(raw, dict) else {}


def _stable_salt() -> bytes:
    """Env-provided salt if set; otherwise a per-process random fallback.

    The process-scoped fallback means pseudonyms are stable within one boot,
    but not across boots. That's a deliberate choice: it makes replayed
    observations from the same session cluster together in the console
    without leaking cross-boot linkage to anyone who might dump the table.
    """
    v = (os.getenv(_ENV_SALT) or "").strip()
    if v:
        return v.encode("utf-8")
    # cache on the function object so repeated calls return the same salt.
    cached = getattr(_stable_salt, "_cached", None)
    if cached is None:
        cached = secrets.token_bytes(16)
        _stable_salt._cached = cached  # type: ignore[attr-defined]
    return cached


def _pseudonym(user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    mac = hmac.new(_stable_salt(), user_id.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:16]


def _reply_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def _score_reply(text: str) -> Dict[str, Any]:
    """Heuristic v1 scoring. Cheap, boring, and honest about being a stub.

    Dimensions (0..1 each), averaged into ``score``:
      * length_ok   — reply is neither a one-liner nor a wall of text
      * inquiry     — contains at least one open-ended '?'
      * reflective  — starts with a reflective/validating stem
    """
    t = (text or "").strip()
    ln = len(t)
    length_ok = 1.0 if 60 <= ln <= 1200 else (0.4 if ln > 0 else 0.0)
    inquiry = 1.0 if "?" in t else 0.0
    reflective_stems = (
        "it sounds like", "what i'm hearing", "let's stay with",
        "i notice", "i can hear", "that lands as",
    )
    low = t.lower()
    reflective = 1.0 if any(low.startswith(s) for s in reflective_stems) else 0.0
    score = round((length_ok + inquiry + reflective) / 3.0, 3)
    return {
        "score": score,
        "dims": {
            "length_ok": length_ok,
            "inquiry": inquiry,
            "reflective": reflective,
        },
        "score_method": "heuristic_v1",
    }


class AlphaLNShadowObserver:
    """Background agent — start/stop/_tick pattern (matches bakeoff agent)."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.last_tick: Optional[Dict[str, Any]] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "AlphaLNShadowObserver started (enabled=%s, cycle=%ss)",
            is_enabled(), CYCLE_SECONDS_ON if is_enabled() else CYCLE_SECONDS_OFF,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        # Small initial stagger so we don't spike DB right at startup.
        await asyncio.sleep(45)
        while self._running:
            try:
                self.last_tick = await self._tick()
            except Exception as exc:
                logger.warning("alphaln shadow observer tick error: %s", exc)
                self.last_tick = {"ok": False, "error": str(exc)[:200]}
            await asyncio.sleep(CYCLE_SECONDS_ON if is_enabled() else CYCLE_SECONDS_OFF)

    def _store_pulse(self, pulse: Dict[str, Any]) -> None:
        """Queens/LN7/L5 read this; AlphaLN does not write their tables."""
        if self.app_state is None:
            return
        try:
            self.app_state.alphaln_shadow_pulse = pulse
        except Exception:
            pass

    async def _rolling_stats(self, conn, new_scores: List[float]) -> Dict[str, Any]:
        mean_24h = None
        n_24h = 0
        try:
            row = await conn.fetchrow(
                """SELECT AVG(score)::float AS mean_s, COUNT(*)::int AS n
                     FROM alphaln_shadow_observations
                    WHERE observed_at > NOW() - INTERVAL '24 hours'
                      AND source_table = 'conversation_history'
                      AND score IS NOT NULL""",
            )
            if row:
                mean_24h = row["mean_s"]
                n_24h = int(row["n"] or 0)
        except Exception as exc:
            logger.debug("alphaln rolling stats skip: %s", exc)
        tick_mean = (
            round(sum(new_scores) / len(new_scores), 3) if new_scores else None
        )
        return {
            "tick_mean": tick_mean,
            "mean_24h": round(float(mean_24h), 3) if mean_24h is not None else None,
            "n_24h": n_24h,
        }

    async def _tick(self) -> Dict[str, Any]:
        if not is_enabled():
            pulse = {
                "ok": True,
                "status": "flag_off",
                "written": 0,
                "skipped": 0,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            self._store_pulse(pulse)
            return pulse
        if self.db_pool is None:
            return {"ok": False, "status": "no_db", "written": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MIN)
        written = 0
        skipped = 0
        new_scores: List[float] = []
        stats: Dict[str, Any] = {}
        async with self.db_pool.acquire() as conn:
            seen_rows = await conn.fetch(
                """SELECT reply_hash FROM alphaln_shadow_observations
                    WHERE observed_at > $1
                      AND source_table = 'conversation_history'""",
                cutoff,
            )
            seen = {r["reply_hash"] for r in seen_rows}
            rows = await conn.fetch(
                """SELECT id, user_id, ai_text, created_at
                     FROM conversation_history
                    WHERE created_at > $1
                      AND ai_text IS NOT NULL
                      AND LENGTH(ai_text) > 0
                    ORDER BY created_at DESC
                    LIMIT $2""",
                cutoff, BATCH_LIMIT,
            )
            for r in rows:
                ai_text = r["ai_text"] or ""
                rh = _reply_hash(ai_text)
                if rh in seen:
                    skipped += 1
                    continue
                s = _score_reply(ai_text)
                await conn.execute(
                    """INSERT INTO alphaln_shadow_observations
                           (source_table, source_row_id, user_pseudonym,
                            reply_hash, reply_len, score, score_method, dims)
                         VALUES ('conversation_history', $1, $2, $3, $4, $5, $6, $7)""",
                    str(r["id"]),
                    _pseudonym(r["user_id"]),
                    rh,
                    len(ai_text),
                    s["score"],
                    s["score_method"],
                    json.dumps(s["dims"] or {}),
                )
                seen.add(rh)
                new_scores.append(float(s["score"]))
                written += 1
            stats = await self._rolling_stats(conn, new_scores)
        pulse = {
            "ok": True,
            "status": "wrote" if written else "idle",
            "written": written,
            "skipped": skipped,
            "at": datetime.now(timezone.utc).isoformat(),
            **stats,
        }
        self._store_pulse(pulse)
        return pulse
