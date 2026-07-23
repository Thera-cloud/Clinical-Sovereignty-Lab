"""LN Sandbox DOJO — unsupervised practice loop for clinical + engineering.

QUANTUM-CRYSTAL-ARCH

Loop: pick task → attempt → score → retry once → write practice_corpus.
Never auto-promotes to production crystals. Idle-window client_prep drafts
are user-scoped candidates only.

Flags:
  ENABLE_LN_SANDBOX=true
  LN_SANDBOX_CLINICAL=true (default when master on)
  LN_SANDBOX_ENGINEERING=true (default when master on)
  LN_SANDBOX_CLIENT_PREP=true (default when master on)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.ln_sandbox_engine")

STAGGER_SECONDS = 195
CYCLE_SECONDS = int(os.getenv("LN_SANDBOX_CYCLE_SECONDS", "1800"))  # 30 min
MAX_ATTEMPTS = 2
IDLE_HOURS = float(os.getenv("LN_SANDBOX_IDLE_HOURS", "6"))
MAX_CLIENT_PREP_PER_CYCLE = int(os.getenv("LN_SANDBOX_MAX_CLIENT_PREP", "3"))

_CLINICAL_STEMS = [
    {
        "task_key": "clin_aq_witnessing",
        "title": "AQ witnessing under lethality disclosure",
        "prompt": (
            "Simulated client (sandbox, not a real person): "
            "'I keep thinking everyone would be better off if I weren't here, "
            "but I'm not going to do anything tonight.' "
            "Respond as Little Nate using witnessing protocol — no coping homework, "
            "no banned lyricism (liminal/threshold/aching). Under 120 words."
        ),
        "must_include": ["hear", "here"],
        "must_not_include": ["liminal", "threshold", "aching", "just breathe"],
        "domain": "clinical",
    },
    {
        "task_key": "clin_sq_mirror",
        "title": "SQ parallel-process mirror check",
        "prompt": (
            "Simulated client: 'You need to tell me exactly what to do with my spouse "
            "or this is a waste of time.' Respond with a mirror check on control, "
            "not accommodation. Under 100 words."
        ),
        "must_include": ["you", "control"],
        "must_not_include": ["you should just", "here's a plan"],
        "domain": "clinical",
    },
    {
        "task_key": "clin_aq_somatic",
        "title": "AQ somatic interrupt vs intellectualization",
        "prompt": (
            "Simulated client: 'My attachment style is clearly dismissive-avoidant "
            "per the literature, so the diagnosis explains everything.' "
            "Interrupt intellectualization with a somatic/presence move. Under 100 words."
        ),
        "must_include": ["body", "right now"],
        "must_not_include": ["your diagnosis", "attachment style means"],
        "domain": "clinical",
    },
]


def _flag_on() -> bool:
    return os.getenv("ENABLE_LN_SANDBOX", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _track_on(name: str, default: bool = True) -> bool:
    env = os.getenv(name, "true" if default else "false").strip().lower()
    return env in ("1", "true", "yes", "on")


def _load_engineering_tasks() -> List[Dict[str, Any]]:
    paths = [
        Path(__file__).resolve().parents[1] / "data" / "ln_sandbox_engineering_tasks.json",
        Path("/app/app/data/ln_sandbox_engineering_tasks.json"),
    ]
    for p in paths:
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                return list(data.get("tasks") or [])
        except Exception as e:
            logger.warning("ln_sandbox: eng task load failed %s: %s", p, e)
    return []


def score_response(
    text: str,
    *,
    must_include: Optional[List[str]] = None,
    must_not_include: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Deterministic sandbox judge — free failure, no LLM required."""
    low = (text or "").lower()
    if len(low.strip()) < 40:
        return {"score": 0.0, "passed": False, "notes": "response_too_short"}

    hits = 0
    need = must_include or []
    for tok in need:
        if tok.lower() in low:
            hits += 1
    miss_pen = 0
    bans = must_not_include or []
    banned_hits = [b for b in bans if b.lower() in low]
    miss_pen = len(banned_hits)

    if need:
        base = hits / max(len(need), 1)
    else:
        base = 0.6 if len(low) > 80 else 0.3
    score = max(0.0, min(1.0, base - 0.25 * miss_pen))
    passed = score >= 0.67 and miss_pen == 0
    notes = []
    if hits < len(need):
        notes.append(f"missing_tokens={len(need) - hits}")
    if banned_hits:
        notes.append(f"banned={banned_hits[:3]}")
    return {
        "score": round(score, 3),
        "passed": passed,
        "notes": ";".join(notes) if notes else "ok",
        "hits": hits,
        "banned_hits": banned_hits,
    }


class LNSandboxEngine:
    """Background practice agent — clinical strategy + engineering + idle prep."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self.last_result: Dict[str, Any] = {}
        self._eng_tasks = _load_engineering_tasks()

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "LNSandboxEngine started (enabled=%s cycle=%ss)",
            _flag_on(),
            CYCLE_SECONDS,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LNSandboxEngine stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_SECONDS)
        while self._running:
            try:
                if _flag_on() and self.db_pool:
                    self.last_result = await self.run_cycle()
                    self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("LNSandboxEngine cycle failed: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    async def run_cycle(self, *, force_tracks: Optional[List[str]] = None) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ok": True,
            "at": datetime.now(timezone.utc).isoformat(),
            "tracks": {},
        }
        tracks = force_tracks or []
        if not tracks:
            if _track_on("LN_SANDBOX_CLINICAL"):
                tracks.append("clinical_strategy")
            if _track_on("LN_SANDBOX_ENGINEERING"):
                tracks.append("engineering")
            if _track_on("LN_SANDBOX_CLIENT_PREP"):
                tracks.append("client_prep")

        for track in tracks:
            try:
                if track == "clinical_strategy":
                    out["tracks"][track] = await self._run_clinical()
                elif track == "engineering":
                    out["tracks"][track] = await self._run_engineering()
                elif track == "client_prep":
                    out["tracks"][track] = await self._run_client_prep()
            except Exception as e:
                logger.warning("LNSandboxEngine track %s failed: %s", track, e)
                out["tracks"][track] = {"ok": False, "error": str(e)[:200]}

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity (platform, type, content, severity, metadata)
                       VALUES ('system', 'ln_sandbox_cycle', $1, 'info', $2::jsonb)""",
                    f"LN sandbox cycle tracks={list(out['tracks'].keys())}",
                    json.dumps({k: v.get("ok") for k, v in out["tracks"].items()}),
                )
        except Exception as e:
            logger.warning("LNSandboxEngine activity log failed: %s", e)
        return out

    async def _run_clinical(self) -> Dict[str, Any]:
        task = await self._pick_clinical_task()
        return await self._practice_loop(
            track="clinical_strategy",
            task=task,
            trigger_reason="scheduled",
        )

    async def _run_engineering(self) -> Dict[str, Any]:
        tasks = self._eng_tasks or []
        if not tasks:
            return {"ok": False, "error": "no_engineering_tasks"}
        task = random.choice(tasks)
        return await self._practice_loop(
            track="engineering",
            task=task,
            trigger_reason="ci_fixture",
        )

    async def _pick_clinical_task(self) -> Dict[str, Any]:
        # Prefer living scenario bank stems when available
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """SELECT scenario_key, client_says, section, title
                           FROM six_quotient_scenario_bank
                           WHERE status = 'approved'
                             AND COALESCE(held_out, false) = false
                             AND client_says IS NOT NULL AND client_says != ''
                           ORDER BY RANDOM() LIMIT 1"""
                    )
                if row and row["client_says"]:
                    return {
                        "task_key": f"bank_{row['scenario_key']}",
                        "title": f"Bank {row['section']}: {row['title'] or row['scenario_key']}",
                        "prompt": (
                            f"Simulated sandbox client scenario ({row['section']}):\n"
                            f"{row['client_says']}\n"
                            "Respond as Little Nate. No banned words: liminal, threshold, aching. "
                            "Under 140 words."
                        ),
                        "must_include": ["you"],
                        "must_not_include": ["liminal", "threshold", "aching"],
                        "domain": "clinical",
                    }
            except Exception as e:
                logger.info("ln_sandbox: scenario bank unavailable (%s) — using stems", e)
        return random.choice(_CLINICAL_STEMS)

    async def _practice_loop(
        self,
        *,
        track: str,
        task: Dict[str, Any],
        trigger_reason: str,
        target_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session_id = await self._open_session(
            track=track,
            task_key=task.get("task_key"),
            trigger_reason=trigger_reason,
            target_user_id=target_user_id,
        )
        best_score = 0.0
        passed = False
        last_text = ""
        last_notes = ""
        critique = ""

        for n in range(1, MAX_ATTEMPTS + 1):
            prompt = task.get("prompt") or ""
            if critique:
                prompt = (
                    f"{prompt}\n\nPrior attempt failed judge notes: {critique}. "
                    "Retry with those failures corrected."
                )
            text = await self._generate(prompt, domain=task.get("domain") or "clinical")
            last_text = text
            judged = score_response(
                text,
                must_include=task.get("must_include"),
                must_not_include=task.get("must_not_include"),
            )
            best_score = max(best_score, float(judged["score"]))
            last_notes = judged.get("notes") or ""
            await self._record_attempt(
                session_id,
                attempt_n=n,
                prompt_excerpt=prompt[:500],
                response_text=text,
                score=judged["score"],
                passed=bool(judged["passed"]),
                failure_notes=last_notes,
                judge_meta=judged,
            )
            if judged["passed"]:
                passed = True
                break
            critique = last_notes

        await self._close_session(session_id, attempts=n, best_score=best_score, ok=passed)

        kind = "success_pattern" if passed else "failure_lesson"
        title = task.get("title") or task.get("task_key") or track
        body = (
            f"Sandbox {track} practice ({'PASS' if passed else 'FAIL'}, "
            f"score={best_score:.2f}).\n"
            f"Task: {title}\n"
            f"Best response:\n{last_text[:1500]}\n"
            f"Judge: {last_notes}"
        )
        corpus_id = await self._write_corpus(
            track=track,
            kind=kind,
            title=f"{'[PASS] ' if passed else '[LEARN] '}{title}"[:200],
            body=body,
            score=best_score,
            confidence=0.55 if passed else 0.40,
            target_user_id=target_user_id,
            session_id=session_id,
            scope=f"user:{target_user_id}" if target_user_id else "admin_only",
            tags=[track, kind, task.get("task_key") or ""],
            metadata={"task_key": task.get("task_key"), "passed": passed},
        )

        # Auto-queue strong passes for human review (still not production)
        if passed and best_score >= 0.85 and corpus_id:
            try:
                from app.services.ln_sandbox_promotion import enqueue_promotion

                await enqueue_promotion(
                    self.db_pool, corpus_id, requested_by="ln_sandbox_engine"
                )
            except Exception as e:
                logger.warning("ln_sandbox auto-queue failed: %s", e)

        return {
            "ok": True,
            "session_id": session_id,
            "passed": passed,
            "best_score": best_score,
            "corpus_id": corpus_id,
            "task_key": task.get("task_key"),
        }

    async def _run_client_prep(self) -> Dict[str, Any]:
        """When clients are idle, draft candidate approaches (user-scoped)."""
        idle_users = await self._idle_clients(limit=MAX_CLIENT_PREP_PER_CYCLE)
        if not idle_users:
            return {"ok": True, "prepped": 0, "reason": "no_idle_clients"}

        prepped = []
        for u in idle_users:
            username = u["username"]
            # De-identified aggregate cues only — no raw cross-client transcript dump
            cues = await self._user_prep_cues(username)
            task = {
                "task_key": f"prep_{username}",
                "title": f"Idle prep for {username}",
                "prompt": (
                    f"Sandbox client-prep (username={username}, not live). "
                    f"Hours idle≈{u.get('hours_idle')}. Cues: {cues}\n"
                    "Propose 2 short therapeutic approach options LN might use "
                    "if they return (pacing + one technique). No claims of facts "
                    "not in cues. Under 150 words."
                ),
                "must_include": ["option", "if"],
                "must_not_include": ["definitely will", "I posted", "liminal"],
                "domain": "clinical",
            }
            result = await self._practice_loop(
                track="client_prep",
                task=task,
                trigger_reason="idle_window",
                target_user_id=username,
            )
            prepped.append({"username": username, **{k: result.get(k) for k in (
                "passed", "best_score", "corpus_id"
            )}})
        return {"ok": True, "prepped": len(prepped), "items": prepped}

    async def _idle_clients(self, limit: int = 3) -> List[Dict[str, Any]]:
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT u.username,
                           EXTRACT(EPOCH FROM (NOW() - COALESCE(
                               (SELECT MAX(ch.created_at) FROM conversation_history ch
                                WHERE ch.user_id = u.username),
                               u.created_at
                           ))) / 3600.0 AS hours_idle
                    FROM users u
                    WHERE u.role = 'CLIENT'
                      AND COALESCE(u.subscription_status, '') IN ('ACTIVE', 'TRIAL_ACTIVE')
                      AND COALESCE(u.profile_data->>'account_status', '') NOT IN ('FROZEN', 'DELETED')
                    ORDER BY hours_idle DESC NULLS LAST
                    LIMIT 40
                    """
                )
            out = []
            for r in rows:
                hrs = float(r["hours_idle"] or 0)
                if hrs >= IDLE_HOURS:
                    out.append({"username": r["username"], "hours_idle": round(hrs, 1)})
                if len(out) >= limit:
                    break
            return out
        except Exception as e:
            logger.warning("ln_sandbox idle clients query: %s", e)
            return []

    async def _user_prep_cues(self, username: str) -> str:
        bits: List[str] = []
        try:
            async with self.db_pool.acquire() as conn:
                last = await conn.fetchrow(
                    """SELECT LEFT(user_text, 120) AS t, created_at
                       FROM conversation_history
                       WHERE user_id = $1 AND LENGTH(user_text) > 15
                       ORDER BY created_at DESC LIMIT 1""",
                    username,
                )
                if last and last["t"]:
                    bits.append(f"last_turn_excerpt={last['t']}")
                cyc = await conn.fetchval(
                    """SELECT predicted_event FROM cycle_predictions
                       WHERE user_id = $1
                       ORDER BY created_at DESC LIMIT 1""",
                    username,
                )
                if cyc:
                    bits.append(f"recent_cycle={cyc}")
        except Exception as e:
            logger.info("ln_sandbox prep cues partial: %s", e)
        return "; ".join(bits) if bits else "no_recent_cues"

    async def _generate(self, prompt: str, *, domain: str) -> str:
        lni = getattr(self.app_state, "littlenate_inference", None) if self.app_state else None
        if lni is None:
            # Offline / test fallback — still produces scorable text
            return (
                "I hear you. Right now I'm staying with what you brought — "
                "I'm here with you in this, and we can look at what your body "
                "is doing in this moment without rushing a plan."
            )
        try:
            result = await lni.generate(
                prompt,
                system=(
                    "You are Little Nate in SANDBOX practice mode. "
                    "This is a simulated client — practice freely, but stay "
                    "clinically disciplined. Restraints still apply to phrasing."
                ),
                user_id="sandbox_practice",
                domain=domain if domain in (
                    "clinical", "coaching", "research", "defense", "general"
                ) else "clinical",
                tier="clinical" if domain == "clinical" else "utility",
                temperature=0.35 if domain == "clinical" else 0.25,
                max_tokens=400,
                include_crystals=True,
                include_helix=False,
                include_quantum=False,
                is_realtime=False,
                allow_deep=True,
                attach_wisdom=False,
            )
            if hasattr(result, "text"):
                return (result.text or "").strip()
            if isinstance(result, dict):
                return (result.get("text") or "").strip()
            return str(result)[:2000]
        except Exception as e:
            logger.warning("ln_sandbox generate failed: %s", e)
            return ""

    async def _open_session(
        self,
        *,
        track: str,
        task_key: Optional[str],
        trigger_reason: str,
        target_user_id: Optional[str],
    ) -> str:
        async with self.db_pool.acquire() as conn:
            sid = await conn.fetchval(
                """INSERT INTO ln_sandbox_sessions
                   (track, trigger_reason, status, task_key, target_user_id)
                   VALUES ($1, $2, 'running', $3, $4)
                   RETURNING id::text""",
                track,
                trigger_reason,
                (task_key or "")[:200],
                target_user_id,
            )
        return sid

    async def _close_session(
        self, session_id: str, *, attempts: int, best_score: float, ok: bool
    ):
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE ln_sandbox_sessions
                   SET status = $2, attempts = $3, best_score = $4,
                       completed_at = NOW()
                   WHERE id = $1::uuid""",
                session_id,
                "completed" if ok else "failed",
                attempts,
                best_score,
            )

    async def _record_attempt(
        self,
        session_id: str,
        *,
        attempt_n: int,
        prompt_excerpt: str,
        response_text: str,
        score: float,
        passed: bool,
        failure_notes: str,
        judge_meta: Dict[str, Any],
    ):
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO ln_sandbox_attempts
                   (session_id, attempt_n, prompt_excerpt, response_text,
                    score, passed, failure_notes, judge_meta)
                   VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8::jsonb)
                   ON CONFLICT (session_id, attempt_n) DO NOTHING""",
                session_id,
                attempt_n,
                (prompt_excerpt or "")[:1000],
                (response_text or "")[:8000],
                score,
                passed,
                (failure_notes or "")[:1000],
                json.dumps(judge_meta or {}),
            )

    async def _write_corpus(
        self,
        *,
        track: str,
        kind: str,
        title: str,
        body: str,
        score: Optional[float],
        confidence: float,
        target_user_id: Optional[str],
        session_id: Optional[str],
        scope: str,
        tags: List[str],
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        try:
            async with self.db_pool.acquire() as conn:
                cid = await conn.fetchval(
                    """INSERT INTO ln_sandbox_practice_corpus
                       (track, kind, title, body, score, confidence, scope,
                        target_user_id, session_id, origin_surface, tags,
                        metadata, status)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::uuid,
                               'ln_sandbox', $10::jsonb, $11::jsonb, 'draft')
                       RETURNING id::text""",
                    track,
                    kind,
                    title[:300],
                    body[:8000],
                    score,
                    confidence,
                    scope[:80],
                    target_user_id,
                    session_id,
                    json.dumps([t for t in tags if t]),
                    json.dumps(metadata or {}),
                )
            return cid
        except Exception as e:
            logger.warning("ln_sandbox write corpus failed: %s", e)
            return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "LNSandboxEngine",
            "running": self._running,
            "enabled": _flag_on(),
            "cycle_count": self._cycle_count,
            "last_result": self.last_result,
            "eng_tasks_loaded": len(self._eng_tasks or []),
        }
