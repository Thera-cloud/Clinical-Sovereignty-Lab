"""View Brief overlay: PostgreSQL conversation_history + prior session summaries.

Coach Command View Brief historically read vault ``memory.json`` only.
This module merges ``conversation_history`` (keyed by ``users.username``,
with hardware_id as a fallback for legacy rows) and prior coaching-session
summaries. Payment identifiers never enter the brief.

# QUANTUM-CRYSTAL-ARCH — S7 View Brief overlay
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("nate.presession_brief_overlay")

PAYMENT_SECRET_KEYS = frozenset(
    {
        "stripe_payment_intent_id",
        "stripe_payment_intent",
        "payment_intent_id",
        "payment_intent",
        "client_secret",
        "stripe_client_secret",
    }
)

# last_session on REST briefs is a full coaching_sessions row + flattened
# session_data. View Brief only needs clinical leftovers — not money or host URLs.
LAST_SESSION_KEEP = frozenset(
    {
        "session_id",
        "status",
        "scheduled_start",
        "scheduled_end",
        "actual_start",
        "actual_end",
        "nate_summary",
        "homework_assigned",
        "topics_covered",
        "mood_at_start",
        "mood_at_end",
        "client_name",
        "session_type",
    }
)


def overlay_enabled() -> bool:
    return os.getenv("ENABLE_BRIEF_PG_OVERLAY", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def strip_payment_secrets(obj: Any) -> Any:
    """Drop Stripe payment-intent fields from any nested brief payload."""
    if isinstance(obj, dict):
        return {
            k: strip_payment_secrets(v)
            for k, v in obj.items()
            if k not in PAYMENT_SECRET_KEYS
        }
    if isinstance(obj, list):
        return [strip_payment_secrets(v) for v in obj]
    return obj


def sanitize_last_session(raw: Any) -> Optional[Dict[str, Any]]:
    """Allowlist clinical last-session fields. Drops session_data / Stripe / URLs."""
    if not isinstance(raw, dict):
        return None
    kept = {k: raw.get(k) for k in LAST_SESSION_KEEP if k in raw}
    return strip_payment_secrets(kept)


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _iso_ts(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def sanitize_conversation_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """Map vault or PG row to ConversationLogView shape. No payment keys."""
    if not isinstance(raw, dict):
        return None
    user = (raw.get("user") or raw.get("user_text") or raw.get("preview") or "").strip()
    ai = (
        raw.get("ai")
        or raw.get("ai_text")
        or raw.get("nate")
        or raw.get("response")
        or raw.get("assistant")
        or ""
    ).strip()
    if not user and not ai:
        return None
    ts = raw.get("timestamp") or raw.get("created_at") or ""
    sid = raw.get("session_id") or ""
    return {
        "timestamp": _iso_ts(ts) if not isinstance(ts, str) else ts,
        "session_id": str(sid) if sid else "",
        "user": user,
        "ai": ai,
        "word_count_user": int(raw.get("word_count_user") or 0),
        "word_count_ai": int(raw.get("word_count_ai") or 0),
    }


def _dedupe_key(entry: Dict[str, Any]) -> str:
    ts = (entry.get("timestamp") or "")[:19]
    user = (entry.get("user") or "")[:80]
    return f"{ts}|{user}"


def merge_conversation_turns(
    vault_entries: Iterable[Any],
    pg_entries: Iterable[Dict[str, Any]],
    *,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """PG is source of truth; vault fills gaps. Newest-last, capped at ``limit``."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for src in (pg_entries, vault_entries):
        for raw in src:
            entry = sanitize_conversation_entry(raw) if isinstance(raw, dict) else None
            if not entry:
                continue
            key = _dedupe_key(entry)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)
    merged.sort(key=lambda e: (e.get("timestamp") or "", e.get("session_id") or ""))
    if len(merged) > limit:
        merged = merged[-limit:]
    return merged


def rebuild_conversation_topics(turns: List[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
    topics: List[Dict[str, Any]] = []
    for m in turns[-n:]:
        u = (m.get("user") or "").strip()
        a = (m.get("ai") or "").strip()
        snippet = u if len(u) >= 12 else (u or a)[:240]
        if not snippet.strip():
            continue
        clipped = snippet[:400]
        if len(snippet) > 400:
            clipped += "..."
        topics.append({
            "timestamp": m.get("timestamp") or "",
            "topic_summary": clipped,
        })
    return topics


def session_summary_from_row(row: Any) -> Optional[Dict[str, Any]]:
    nate = (_row_get(row, "nate_summary") or "").strip()
    notes = (_row_get(row, "session_notes") or "").strip()
    zoom = (_row_get(row, "zoom_summary") or "").strip()
    summary = nate or zoom or notes
    if not summary:
        return None
    occurred = _row_get(row, "occurred_at")
    return {
        "session_id": str(_row_get(row, "session_id") or ""),
        "occurred_at": _iso_ts(occurred),
        "summary": summary[:800],
        "source": "nate_summary" if nate else ("zoom" if zoom else "session_notes"),
    }


async def _history_user_ids(
    db_pool: Any,
    client_id: str,
    client_profile: Optional[Dict[str, Any]],
) -> List[str]:
    """conversation_history.user_id is username; include hardware_id for legacy rows."""
    ids: List[str] = []
    profile = client_profile or {}
    username = (profile.get("username") or "").strip()
    hardware_id = (profile.get("hardware_id") or client_id or "").strip()
    try:
        from app.services._identity_resolver import resolve_username

        resolved = await resolve_username(db_pool, (client_id or "").strip())
        if resolved:
            ids.append(resolved.strip())
    except Exception as e:
        logger.warning("presession overlay: resolve_username failed: %s", e)
    for candidate in (username, hardware_id, (client_id or "").strip()):
        if candidate and candidate not in ids:
            ids.append(candidate)
    return ids


def _jsonish(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None
    return None


async def load_thera_world_scene(conn: Any, user_ids: List[str]) -> Dict[str, Any]:
    """Latest SSE panel + journey/quest/mission for this client. Empty dict if none."""
    ids = [i for i in (user_ids or []) if i]
    if not conn or not ids:
        return {}
    scene: Dict[str, Any] = {}
    try:
        row = await conn.fetchrow(
            """
            SELECT biome, character_manifest,
                   LEFT(COALESCE(narrative_text, ''), 500) AS narrative_text,
                   panel_tone, crystal_domains_used
              FROM sse_panel_log
             WHERE user_id = ANY($1::text[])
             ORDER BY generated_at DESC NULLS LAST
             LIMIT 1
            """,
            ids,
        )
        if row:
            biome = _row_get(row, "biome")
            character = _row_get(row, "character_manifest")
            narrative = _row_get(row, "narrative_text")
            tone = _row_get(row, "panel_tone")
            if isinstance(biome, str) and biome.strip():
                scene["biome"] = biome.strip()
            if isinstance(character, str) and character.strip():
                scene["character"] = character.strip()
                scene["character_manifest"] = character.strip()
            if isinstance(narrative, str) and narrative.strip():
                scene["narrative"] = narrative.strip()
            if isinstance(tone, str) and tone.strip():
                scene["tone"] = tone.strip()
            domains = _jsonish(_row_get(row, "crystal_domains_used"))
            if domains:
                scene["crystal_domains"] = domains
    except Exception as e:
        logger.debug("presession overlay: sse_panel_log scene: %s", e)
    try:
        journey = await conn.fetchrow(
            """
            SELECT current_biome, dominant_character, last_panel_summary,
                   last_panel_npcs, therapeutic_arc
              FROM sse_user_journeys
             WHERE user_id = ANY($1::text[])
             ORDER BY last_panel_at DESC NULLS LAST
             LIMIT 1
            """,
            ids,
        )
        if journey:
            if not scene.get("biome"):
                biome = _row_get(journey, "current_biome")
                if isinstance(biome, str) and biome.strip():
                    scene["biome"] = biome.strip()
            if not scene.get("character"):
                character = _row_get(journey, "dominant_character")
                if isinstance(character, str) and character.strip():
                    scene["character"] = character.strip()
            if not scene.get("narrative"):
                summary = _row_get(journey, "last_panel_summary")
                if isinstance(summary, str) and summary.strip():
                    scene["narrative"] = summary.strip()
                    scene["last_panel_summary"] = summary.strip()
            npcs = _jsonish(_row_get(journey, "last_panel_npcs"))
            if npcs:
                scene["npcs"] = npcs
            arc = _row_get(journey, "therapeutic_arc")
            if isinstance(arc, str) and arc.strip():
                scene["therapeutic_arc"] = arc.strip()
    except Exception as e:
        logger.debug("presession overlay: sse_user_journeys scene: %s", e)
    try:
        quest = await conn.fetchrow(
            """
            SELECT goal, goal_domain
              FROM sse_quests
             WHERE user_id = ANY($1::text[]) AND status = 'active'
             ORDER BY started_at DESC
             LIMIT 1
            """,
            ids,
        )
        if quest:
            goal = _row_get(quest, "goal")
            if isinstance(goal, str) and goal.strip():
                scene["quest"] = goal.strip()
                scene["goal"] = goal.strip()
    except Exception as e:
        logger.debug("presession overlay: sse_quests scene: %s", e)
    try:
        mission = await conn.fetchrow(
            """
            SELECT relationship_target, relationship_type
              FROM sse_missions
             WHERE user_id = ANY($1::text[]) AND status = 'active'
             ORDER BY started_at DESC
             LIMIT 1
            """,
            ids,
        )
        if mission:
            target = _row_get(mission, "relationship_target")
            if isinstance(target, str) and target.strip():
                scene["mission"] = target.strip()
                scene["relationship_target"] = target.strip()
    except Exception as e:
        logger.debug("presession overlay: sse_missions scene: %s", e)
    if not scene.get("narrative"):
        try:
            drow = await conn.fetchrow(
                """
                SELECT LEFT(COALESCE(NULLIF(btrim(client_narrative_text), ''), ''), 500)
                           AS client_narrative_text
                  FROM sse_delivery_generation_log
                 WHERE user_id = ANY($1::text[])
                   AND COALESCE(status, 'success') = 'success'
                   AND COALESCE(NULLIF(btrim(client_narrative_text), ''), '') <> ''
                 ORDER BY generated_at DESC
                 LIMIT 1
                """,
                ids,
            )
            nar = _row_get(drow, "client_narrative_text") if drow else None
            if isinstance(nar, str) and nar.strip():
                scene["narrative"] = nar.strip()
        except Exception as e:
            logger.debug("presession overlay: delivery narrative: %s", e)
    return scene


async def enrich_dual_coo_insights(
    db_pool: Any,
    client_id: str,
    brief: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach queued Dual-COO coach_insight_briefs. Broadcast stays queued."""
    out = dict(brief or {})
    if not db_pool or not (client_id or "").strip():
        return out
    try:
        from app.services.rls_context import set_rls_admin

        set_rls_admin()
        async with db_pool.acquire() as conn:
            id_row = await conn.fetchrow(
                """
                SELECT id::text AS uid, username, hardware_id
                FROM users
                WHERE hardware_id = $1 OR username = $1 OR id::text = $1
                LIMIT 1
                """,
                (client_id or "").strip(),
            )
            match_ids = [client_id]
            if id_row:
                for key in ("uid", "username", "hardware_id"):
                    val = id_row.get(key)
                    if val and str(val) not in match_ids:
                        match_ids.append(str(val))
            rows = await conn.fetch(
                """
                SELECT id, source, title, body, created_at, client_user_id
                FROM coach_insight_briefs
                WHERE status = 'queued'
                  AND (
                      client_user_id = 'broadcast'
                      OR client_user_id = ANY($1::text[])
                  )
                ORDER BY created_at DESC
                LIMIT 8
                """,
                match_ids,
            )
            if rows:
                out["dual_coo_insights"] = [
                    {
                        "id": r["id"],
                        "source": r["source"],
                        "title": r["title"],
                        "body": (r["body"] or "")[:800],
                        "created_at": r["created_at"].isoformat()
                        if r["created_at"] else None,
                    }
                    for r in rows
                ]
                targeted = [
                    r["id"]
                    for r in rows
                    if str(r["client_user_id"] or "") != "broadcast"
                ]
                if targeted:
                    await conn.execute(
                        """
                        UPDATE coach_insight_briefs
                        SET status = 'delivered', delivered_at = NOW()
                        WHERE id = ANY($1::bigint[])
                        """,
                        targeted,
                    )
    except Exception as e:
        logger.debug("presession dual_coo insights: %s", e)
    return out


async def overlay_presession_brief(
    db_pool: Any,
    client_id: str,
    client_profile: Optional[Dict[str, Any]],
    brief: Dict[str, Any],
    *,
    limit: int = 25,
) -> Dict[str, Any]:
    """Merge PG conversation + session summaries onto an existing View Brief dict."""
    out = dict(brief or {})
    vault = list(out.get("recent_conversations") or [])
    client_block = out.get("client")
    if isinstance(client_block, dict) and "last_session" in client_block:
        client_block = dict(client_block)
        client_block["last_session"] = sanitize_last_session(client_block.get("last_session"))
        out["client"] = client_block
    if not overlay_enabled() or not db_pool:
        out["recent_conversations"] = merge_conversation_turns(vault, [], limit=limit)
        try:
            from app.services.session_prep_composer import (
                compose_session_prep_points,
                compose_panel_prep_points,
            )

            out["session_prep_points"] = compose_session_prep_points(out)
            out["panel_prep_points"] = compose_panel_prep_points(out)
        except Exception as e:
            logger.warning("presession overlay: session_prep_points failed: %s", e)
        return strip_payment_secrets(out)
    pg_turns: List[Dict[str, Any]] = []
    summaries: List[Dict[str, Any]] = []
    try:
        user_ids = await _history_user_ids(db_pool, client_id, client_profile)
        hardware_id = ((client_profile or {}).get("hardware_id") or client_id or "").strip()
        async with db_pool.acquire() as conn:
            if user_ids:
                rows = await conn.fetch(
                    """
                    SELECT session_id, user_text, ai_text,
                           word_count_user, word_count_ai, created_at
                      FROM conversation_history
                     WHERE user_id = ANY($1::text[])
                       AND (
                           LENGTH(COALESCE(user_text, '')) > 0
                           OR LENGTH(COALESCE(ai_text, '')) > 0
                       )
                     ORDER BY created_at DESC
                     LIMIT $2
                    """,
                    user_ids,
                    max(limit, 40),
                )
                for row in reversed(list(rows or [])):
                    pg_turns.append({
                        "timestamp": _iso_ts(_row_get(row, "created_at")),
                        "session_id": _row_get(row, "session_id") or "",
                        "user": (_row_get(row, "user_text") or "").strip(),
                        "ai": (_row_get(row, "ai_text") or "").strip(),
                        "word_count_user": int(_row_get(row, "word_count_user") or 0),
                        "word_count_ai": int(_row_get(row, "word_count_ai") or 0),
                    })
            session_keys = list(user_ids)
            for extra in (hardware_id, (client_id or "").strip()):
                if extra and extra not in session_keys:
                    session_keys.append(extra)
            if session_keys:
                sum_rows = await conn.fetch(
                    """
                    SELECT session_id,
                           COALESCE(actual_end, scheduled_at, scheduled_start) AS occurred_at,
                           LEFT(COALESCE(nate_summary, ''), 800) AS nate_summary,
                           LEFT(COALESCE(session_notes, ''), 400) AS session_notes,
                           LEFT(COALESCE(session_data->>'zoom_ai_summary_text', ''), 800)
                               AS zoom_summary
                      FROM coaching_sessions
                     WHERE client_id = ANY($1::text[])
                       AND (
                           COALESCE(nate_summary, '') <> ''
                           OR COALESCE(session_notes, '') <> ''
                           OR COALESCE(session_data->>'zoom_ai_summary_text', '') <> ''
                       )
                     ORDER BY COALESCE(actual_end, scheduled_at, scheduled_start)
                              DESC NULLS LAST
                     LIMIT 8
                    """,
                    session_keys,
                )
                for row in sum_rows or []:
                    parsed = session_summary_from_row(row)
                    if parsed:
                        summaries.append(parsed)
            try:
                phase_ids = list(user_ids)
                uname = ((client_profile or {}).get("username") or "").strip()
                if uname and uname not in phase_ids:
                    phase_ids.insert(0, uname)
                for uid in phase_ids:
                    if not uid:
                        continue
                    phase_row = await conn.fetchrow(
                        "SELECT phase, sub_state FROM client_growth_phase WHERE username = $1",
                        uid,
                    )
                    phase = None
                    sub = None
                    if phase_row is not None:
                        try:
                            phase = phase_row["phase"]
                            sub = phase_row["sub_state"]
                        except (KeyError, TypeError, IndexError):
                            phase = None
                    if isinstance(phase, str) and phase.strip():
                        out["growth_phase"] = {
                            "phase": phase.strip().lower(),
                            "sub_state": (
                                sub.strip().lower()
                                if isinstance(sub, str) and sub
                                else None
                            ),
                        }
                        break
            except Exception as e:
                logger.debug("presession overlay: growth_phase: %s", e)
            try:
                scene_ids = list(user_ids)
                uname = ((client_profile or {}).get("username") or "").strip()
                hw = ((client_profile or {}).get("hardware_id") or client_id or "").strip()
                for extra in (uname, hw, (client_id or "").strip()):
                    if extra and extra not in scene_ids:
                        scene_ids.append(extra)
                scene = await load_thera_world_scene(conn, scene_ids)
                if scene:
                    out["thera_world_scene"] = scene
            except Exception as e:
                logger.debug("presession overlay: thera_world_scene: %s", e)
    except Exception as e:
        logger.warning("presession overlay: PG merge failed: %s", e)

    merged = merge_conversation_turns(vault, pg_turns, limit=limit)
    out["recent_conversations"] = merged
    if merged and not out.get("recent_conversation_topics"):
        out["recent_conversation_topics"] = rebuild_conversation_topics(merged)
    if summaries:
        out["prior_session_summaries"] = summaries
    try:
        from app.services.session_prep_composer import (
            compose_session_prep_points,
            compose_panel_prep_points,
        )

        out["session_prep_points"] = compose_session_prep_points(out)
        out["panel_prep_points"] = compose_panel_prep_points(out)
    except Exception as e:
        logger.warning("presession overlay: session_prep_points failed: %s", e)
    return strip_payment_secrets(out)
