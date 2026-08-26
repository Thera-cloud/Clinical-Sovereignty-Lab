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
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.alphaln_shadow_observer")

_ENV_FLAG = "ENABLE_ALPHALN_SHADOW_OBSERVER"
_ENV_SALT = "ALPHALN_OBSERVER_SALT"
_ENV_SCORER = "ALPHALN_SCORER_MODE"

# Cycle: every 5 min when enabled; long sleep otherwise so an empty process
# doesn't spin.
CYCLE_SECONDS_ON = 300
CYCLE_SECONDS_OFF = 900
BATCH_LIMIT = 25       # rows scored per tick
LOOKBACK_MIN = 10      # look at replies newer than this


def is_enabled() -> bool:
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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


def _scorer_mode() -> str:
    return (os.getenv(_ENV_SCORER) or "heuristic_v1").strip().lower()


async def _score_reply_maybe_validated(text: str) -> Dict[str, Any]:
    """Heuristic by default; validated instruments when ALPHALN_SCORER_MODE=validated."""
    if _scorer_mode() != "validated":
        return _score_reply(text)
    try:
        from app.services.alphaln_validated_scorer import score_validated_bundle

        bundle = await score_validated_bundle(text)
        dims = bundle.get("dims") or {}
        return {
            "score": float(bundle.get("score") or 0.0),
            "dims": dims,
            "score_method": str(bundle.get("score_method") or "heuristic_v1"),
            "notes": str(bundle.get("notes") or ""),
            "metadata": {
                "item_scores": bundle.get("item_scores") or [],
                "srs": (bundle.get("srs") or {}).get("score"),
                "phq9_delta": (bundle.get("phq9") or {}).get("score"),
            },
        }
    except Exception as exc:
        logger.warning("alphaln validated scorer failed; heuristic fallback: %s", exc)
        return _score_reply(text)


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

    async def _tick(self) -> Dict[str, Any]:
        if not is_enabled():
            return {"ok": True, "status": "flag_off", "written": 0}
        if self.db_pool is None:
            return {"ok": False, "status": "no_db", "written": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MIN)
        written = 0
        async with self.db_pool.acquire() as conn:
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
                s = await _score_reply_maybe_validated(ai_text)
                await conn.execute(
                    """INSERT INTO alphaln_shadow_observations
                           (source_table, source_row_id, user_pseudonym,
                            reply_hash, reply_len, score, score_method, dims,
                            notes, metadata)
                         VALUES ('conversation_history', $1, $2, $3, $4, $5, $6, $7,
                                 $8, $9)""",
                    str(r["id"]),
                    _pseudonym(r["user_id"]),
                    _reply_hash(ai_text),
                    len(ai_text),
                    s["score"],
                    s["score_method"],
                    json.dumps(s.get("dims") or {}),
                    s.get("notes"),
                    json.dumps(s.get("metadata") or {}),
                )
                written += 1
        return {"ok": True, "status": "wrote", "written": written}
