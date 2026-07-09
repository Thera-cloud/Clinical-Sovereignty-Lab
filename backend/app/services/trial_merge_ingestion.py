"""Post-merge trial history ingestion — vault, crystals, digest (QUANTUM-CRYSTAL-ARCH).

Fired only from ``public_trial_conversion.try_merge_trial_data`` after successful
``conversation_history`` insert. Never blocks registration; failures log WARNING.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ORDINAL_FIRST_RE = re.compile(
    r"\b(first|earliest|beginning|oldest|initial)\b", re.I,
)
_ORDINAL_LAST_RE = re.compile(
    r"\b(last|latest|newest|final)\b", re.I,
)

_DIGEST_SYSTEM = (
    "Summarize this anonymous trial therapy conversation in 800 characters or fewer. "
    "Capture emotional themes, presenting concerns, and what the client sought. "
    "No preamble or labels — summary text only."
)


def ingestion_enabled() -> bool:
    return (os.getenv("TRIAL_MERGE_INGESTION_ENABLED", "1") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def digest_prompt_enabled() -> bool:
    return (os.getenv("TRIAL_CONTEXT_DIGEST_ENABLED", "1") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def detect_ordinal_recall_intent(query_text: str) -> Optional[str]:
    """Return ``first`` or ``last`` when the user asks for ordinal recall."""
    if not query_text or len(query_text) < 8:
        return None
    lower = query_text.lower()
    if _ORDINAL_FIRST_RE.search(query_text):
        return "first"
    if _ORDINAL_LAST_RE.search(query_text) and re.search(
        r"\b(question|message|thing i said|thing you said|words?)\b", lower,
    ):
        return "last"
    return None


def schedule_trial_merge_ingestion(
    db_pool,
    *,
    username: str,
    valid_pairs: List[Tuple[str, str]],
    session_id: str,
    matched_via: str = "",
) -> None:
    """Fire-and-forget background ingestion after trial merge."""
    if not ingestion_enabled() or not db_pool or not username or not valid_pairs:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _run_trial_merge_ingestion(
                db_pool,
                username=username,
                valid_pairs=valid_pairs,
                session_id=session_id,
                matched_via=matched_via,
            )
        )
    except RuntimeError:
        pass
    except Exception as exc:
        logger.warning("trial_merge_ingestion: schedule failed for %s: %s", username, exc)


async def build_trial_context_prompt_block(
    db_pool, username: str, profile: Dict[str, Any],
) -> str:
    """Inject TRIAL CONTEXT digest for the first 10 post-signup turns (flag-gated)."""
    if not digest_prompt_enabled() or not username:
        return ""
    digest = _profile_digest(profile)
    if not digest:
        return ""
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                post_cnt = await conn.fetchval(
                    "SELECT COUNT(*) FROM conversation_history "
                    "WHERE user_id = $1 "
                    "AND COALESCE(metadata->>'source', '') != 'public_trial_merge' "
                    "AND LENGTH(COALESCE(user_text, '')) > 0",
                    username,
                )
            if (post_cnt or 0) >= 10:
                return ""
        except Exception as exc:
            logger.warning("trial_merge_ingestion: post-signup turn count failed: %s", exc)
    return (
        f"TRIAL CONTEXT:\n{digest[:800]}\n"
        "Note: Summarizes the user's anonymous trial chat before signup."
    )


def _profile_digest(profile: Dict[str, Any]) -> str:
    pd = profile.get("profile_data") or {}
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            pd = {}
    if not isinstance(pd, dict):
        pd = {}
    return (pd.get("trial_context_digest") or profile.get("trial_context_digest") or "").strip()


def _vault_memory_path(hardware_id: str, role: str) -> Path:
    data_dir = os.getenv("DATA_DIR", "/app/data")
    folder = "Clients"
    if role == "COACH":
        folder = "Coaches"
    elif role == "ADMIN":
        folder = "Admin"
    return Path(data_dir) / "Vaults" / folder / hardware_id / "memory.json"


def _append_vault_memory(
    hardware_id: str,
    role: str,
    user_text: str,
    ai_text: str,
    session_id: str,
    metadata: Optional[dict] = None,
) -> None:
    path = _vault_memory_path(hardware_id, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    hist: list = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                hist = json.load(f)
        except Exception:
            hist = []
    entry = {
        "timestamp": str(datetime.utcnow()),
        "session_id": session_id,
        "user": user_text,
        "ai": ai_text,
        "word_count_user": len((user_text or "").split()),
        "word_count_ai": len((ai_text or "").split()),
    }
    if metadata:
        entry.update(metadata)
    hist.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist[-1000:], f, indent=2)


async def fetch_pg_history_for_chat(
    db_pool, username: str, hardware_id: str, limit: int = 10,
) -> str:
    """PG history block for chat prompt (priority trial-merge fill when total <= 40)."""
    if not db_pool:
        return ""
    try:
        async with db_pool.acquire() as conn:
            _ids = [username]
            if hardware_id and hardware_id != username:
                _ids.append(hardware_id)
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM conversation_history "
                "WHERE user_id = ANY($1) AND LENGTH(user_text) > 15",
                _ids,
            )
            if (total or 0) <= 40:
                merge_n = await conn.fetchval(
                    "SELECT COUNT(*) FROM conversation_history WHERE user_id = ANY($1) "
                    "AND LENGTH(user_text) > 15 AND metadata->>'source' = 'public_trial_merge'",
                    _ids,
                )
                merge_reserve = min(5, merge_n or 0)
                merge_rows = []
                if merge_reserve:
                    merge_rows = await conn.fetch(
                        "SELECT user_text, ai_text, created_at, id FROM conversation_history "
                        "WHERE user_id = ANY($1) AND LENGTH(user_text) > 15 "
                        "AND metadata->>'source' = 'public_trial_merge' "
                        "ORDER BY created_at ASC, id ASC LIMIT $2",
                        _ids, merge_reserve,
                    )
                merge_ids = [r["id"] for r in merge_rows]
                remaining = limit - len(merge_rows)
                if merge_ids:
                    recent_rows = await conn.fetch(
                        "SELECT user_text, ai_text, created_at, id FROM conversation_history "
                        "WHERE user_id = ANY($1) AND LENGTH(user_text) > 15 "
                        "AND id != ALL($3::bigint[]) "
                        "ORDER BY created_at DESC, id DESC LIMIT $2",
                        _ids, remaining, merge_ids,
                    )
                else:
                    recent_rows = await conn.fetch(
                        "SELECT user_text, ai_text, created_at, id FROM conversation_history "
                        "WHERE user_id = ANY($1) AND LENGTH(user_text) > 15 "
                        "ORDER BY created_at DESC, id DESC LIMIT $2",
                        _ids, remaining,
                    )
                rows = list(merge_rows) + list(recent_rows)
                rows.sort(key=lambda r: (r["created_at"], r.get("id", 0)))
            else:
                rows = await conn.fetch(
                    "SELECT user_text, ai_text, created_at FROM conversation_history "
                    "WHERE user_id = ANY($1) AND LENGTH(user_text) > 15 "
                    "ORDER BY created_at DESC, id DESC LIMIT $2",
                    _ids, limit,
                )
            if not rows:
                return ""
            parts = []
            for r in reversed(rows):
                u = (r["user_text"] or "")[:200]
                a = (r["ai_text"] or "")[:200]
                ts = r["created_at"].strftime("%b %d") if r["created_at"] else ""
                if u:
                    parts.append(f"[{ts}] Client: {u}")
                if a:
                    parts.append(f"[{ts}] Nate: {a}")
            if parts:
                return "PRIOR SESSION HISTORY (chat + voice calls):\n" + "\n".join(parts)
            return ""
    except Exception as exc:
        logger.warning("trial_merge_ingestion: fetch_pg_history failed: %s", exc)
        return ""


async def search_conversation_history_ch(
    db_pool,
    username: str,
    hardware_id: str,
    query_text: str,
    search_terms: str,
    max_results: int = 12,
) -> Optional[str]:
    """Conversation_history leg of chat deep search (ordinal or FTS)."""
    if not db_pool:
        return None
    try:
        _ids = [username]
        if hardware_id and hardware_id != username:
            _ids.append(hardware_id)
        ordinal = detect_ordinal_recall_intent(query_text)
        async with db_pool.acquire() as conn:
            if ordinal == "first":
                rows = await conn.fetch(
                    "SELECT user_text, ai_text, created_at, session_id "
                    "FROM conversation_history WHERE user_id = ANY($1) "
                    "AND LENGTH(user_text) > 15 "
                    "ORDER BY created_at ASC, id ASC LIMIT $2",
                    _ids, max_results,
                )
            elif ordinal == "last":
                rows = await conn.fetch(
                    "SELECT user_text, ai_text, created_at, session_id "
                    "FROM conversation_history WHERE user_id = ANY($1) "
                    "AND LENGTH(user_text) > 15 "
                    "ORDER BY created_at DESC, id DESC LIMIT $2",
                    _ids, max_results,
                )
            else:
                rows = await conn.fetch(
                    "SELECT user_text, ai_text, created_at, session_id, "
                    "ts_rank(to_tsvector('english', COALESCE(user_text,'') || ' ' || COALESCE(ai_text,'')), "
                    "        plainto_tsquery('english', $2)) AS rank "
                    "FROM conversation_history WHERE user_id = ANY($1) "
                    "AND to_tsvector('english', COALESCE(user_text,'') || ' ' || COALESCE(ai_text,'')) "
                    "    @@ plainto_tsquery('english', $2) "
                    "ORDER BY rank DESC, created_at DESC LIMIT $3",
                    _ids, search_terms, max_results,
                )
        if not rows:
            return None
        p = []
        for r in rows:
            ts = r["created_at"].strftime("%b %d %I:%M%p") if r["created_at"] else ""
            u = (r["user_text"] or "")[:250]
            a = (r["ai_text"] or "")[:250]
            entry = f"[{ts}]"
            if u:
                entry += f" {username}: {u}"
            if a:
                entry += f" | Nate: {a}"
            p.append(entry)
        return f"CONVERSATION HISTORY MATCHES ({len(rows)} found):\n" + "\n".join(p)
    except Exception as exc:
        logger.warning("trial_merge_ingestion: ch deep search failed: %s", exc)
        return None


async def backfill_trial_merge_ingestion(db_pool, username: str) -> bool:
    """Re-ingest from existing ``public_trial_merge`` rows (e.g. Test6 post-deploy)."""
    if not ingestion_enabled() or not db_pool or not username:
        return False
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_text, ai_text, session_id, metadata "
                "FROM conversation_history WHERE user_id = $1 "
                "AND metadata->>'source' = 'public_trial_merge' "
                "ORDER BY created_at ASC, id ASC",
                username,
            )
        if not rows:
            return False
        pairs = [(r["user_text"] or "", r["ai_text"] or "") for r in rows]
        session_id = rows[0]["session_id"] or f"trial_backfill_{username}"
        via = ""
        try:
            meta = rows[0]["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            via = (meta or {}).get("via") or ""
        except Exception:
            pass
        await _run_trial_merge_ingestion(
            db_pool,
            username=username,
            valid_pairs=pairs,
            session_id=session_id,
            matched_via=via,
        )
        return True
    except Exception as exc:
        logger.warning("trial_merge_ingestion: backfill failed for %s: %s", username, exc)
        return False


async def _run_trial_merge_ingestion(
    db_pool,
    *,
    username: str,
    valid_pairs: List[Tuple[str, str]],
    session_id: str,
    matched_via: str,
) -> None:
    try:
        from app.websocket.crystal_recall_bridge import (
            crystallize_from_conversation,
            crystallize_session_summary,
        )
    except ImportError as exc:
        logger.warning("trial_merge_ingestion: crystal bridge unavailable: %s", exc)
        return

    hardware_id = ""
    user_name = ""
    role = "CLIENT"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hardware_id, role, profile_data->>'name' AS name "
                "FROM users WHERE username = $1",
                username,
            )
            if row:
                hardware_id = row["hardware_id"] or username
                user_name = row["name"] or ""
                role = row["role"] or "CLIENT"
    except Exception as exc:
        logger.warning("trial_merge_ingestion: user lookup failed for %s: %s", username, exc)
        hardware_id = username

    _meta = {"source": "trial_merge", "via": matched_via}
    for user_text, ai_text in valid_pairs:
        if not user_text and not ai_text:
            continue
        try:
            await asyncio.to_thread(
                _append_vault_memory,
                hardware_id,
                role,
                user_text,
                ai_text,
                session_id,
                _meta,
            )
        except Exception as exc:
            logger.warning("trial_merge_ingestion: vault memorize failed for %s: %s", username, exc)
        try:
            if user_text:
                await crystallize_from_conversation(
                    db_pool,
                    hardware_id,
                    user_text,
                    ai_text,
                    user_name=user_name,
                    domain="clinical",
                    min_score=3,
                    origin_surface="trial_merge",
                )
        except Exception as exc:
            logger.warning("trial_merge_ingestion: per-turn crystal failed for %s: %s", username, exc)

    turns = [{"user_text": u, "ai_text": a} for u, a in valid_pairs if u or a]
    try:
        await crystallize_session_summary(
            db_pool,
            hardware_id,
            turns,
            user_name=user_name,
            origin_surface="trial_merge",
            session_id=session_id,
        )
    except Exception as exc:
        logger.warning("trial_merge_ingestion: session summary failed for %s: %s", username, exc)

    if digest_prompt_enabled():
        try:
            digest = await _generate_trial_digest(valid_pairs)
            if digest:
                await _persist_trial_digest(
                    db_pool, username=username, hardware_id=hardware_id,
                    digest=digest, user_name=user_name,
                )
        except Exception as exc:
            logger.warning("trial_merge_ingestion: digest failed for %s: %s", username, exc)


async def _generate_trial_digest(valid_pairs: List[Tuple[str, str]]) -> str:
    lines = []
    for user_text, ai_text in valid_pairs[:25]:
        if user_text:
            lines.append(f"Client: {user_text[:400]}")
        if ai_text:
            lines.append(f"Nate: {ai_text[:300]}")
    if not lines:
        return ""
    prompt = "\n".join(lines)
    try:
        from app.services.nate_inference_router import NateInferenceRouter, TIER_UTILITY
        router = NateInferenceRouter(app_state=None)
        result = await asyncio.wait_for(
            router.generate(
                prompt=prompt,
                system=_DIGEST_SYSTEM,
                tier=TIER_UTILITY,
                temperature=0.2,
                max_tokens=220,
                domain="clinical",
                odpe_signal="LOCKED",
            ),
            timeout=float(os.getenv("TRIAL_DIGEST_TIMEOUT_S", "8")),
        )
        text = ((result or {}).get("text") or "").strip()
        return text[:800] if text else ""
    except Exception as exc:
        logger.warning("trial_merge_ingestion: LLM digest failed: %s", exc)
        fallback = " ".join(u for u, _ in valid_pairs if u)[:800]
        return fallback.strip()


async def _persist_trial_digest(
    db_pool,
    *,
    username: str,
    hardware_id: str,
    digest: str,
    user_name: str,
) -> None:
    digest = (digest or "")[:800]
    if not digest:
        return
    name_tag = user_name or username
    crystal_text = f"TRIAL CONTEXT DIGEST ({name_tag}): {digest}"
    content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()
    meta = json.dumps({"source": "trial_merge", "digest": True})
    async with db_pool.acquire() as conn:
        user_uuid = await conn.fetchval(
            "SELECT id FROM users WHERE username = $1", username,
        )
        await conn.execute(
            """INSERT INTO nate_intelligence_crystals
                (crystal_text, domain, scope, topics, source_count,
                 generation, confidence, content_hash, user_id, origin_surface, metadata)
            VALUES ($1, 'clinical', 'user', '{}'::text[], 1, 0, 0.85, $2, $3, 'trial_merge', $4::jsonb)
            ON CONFLICT (content_hash) DO NOTHING""",
            crystal_text, content_hash, user_uuid, meta,
        )
        await conn.execute(
            """UPDATE users SET profile_data = jsonb_set(
                COALESCE(profile_data, '{}'::jsonb),
                '{trial_context_digest}',
                to_jsonb($2::text)
            ) WHERE username = $1""",
            username, digest,
        )
