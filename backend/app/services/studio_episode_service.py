"""Episode review gates — INV-3 human publish. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from app.services.studio_invariants import (
    episode_can_approve,
    episode_can_publish,
    override_requires_admin,
)

logger = logging.getLogger("studio_episode")


async def get_episode(db_pool, episode_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.*, s.coach_id, s.name AS show_name
            FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
        flags = []
        if row:
            flags = await conn.fetch(
                """
                SELECT id, severity, category, detail, status
                FROM studio_compliance_flags WHERE episode_id = $1::uuid
                """,
                episode_id,
            )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {"ok": True, "episode": _ep(row), "flags": [_flag(f) for f in flags]}


async def approve_episode(db_pool, episode_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.state, s.coach_id,
              (SELECT COUNT(*) FROM studio_compliance_flags f
                WHERE f.episode_id = e.id AND f.status = 'open') AS open_flags
            FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
        if not row:
            return {"ok": False, "reason": "not_found", "code": 404}
        open_n = int(row["open_flags"] or 0)
        if open_n > 0:
            return {"ok": False, "reason": "open_compliance_flags", "code": 409}
        if not episode_can_approve(row["state"], open_n):
            return {"ok": False, "reason": "not_in_review", "code": 409}
        await conn.execute(
            """
            UPDATE studio_episodes
            SET state = 'approved', approved_by = $2, approved_at = NOW(), updated_at = NOW()
            WHERE id = $1::uuid
            """,
            episode_id,
            coach_id,
        )
    return {"ok": True, "state": "approved"}


async def publish_episode(db_pool, episode_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.state FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
        if not row:
            return {"ok": False, "reason": "not_found", "code": 404}
        if not episode_can_publish(row["state"]):
            return {"ok": False, "reason": "not_approved", "code": 409}
        await conn.execute(
            """
            UPDATE studio_episodes
            SET state = 'published', published_at = NOW(),
                rss_guid = COALESCE(rss_guid, $1::text), updated_at = NOW()
            WHERE id = $2::uuid
            """,
            f"studio-{episode_id}",
            episode_id,
        )
        show_id = await conn.fetchval(
            "SELECT show_id FROM studio_episodes WHERE id = $1::uuid",
            episode_id,
        )
        if show_id:
            await conn.execute(
                """
                UPDATE studio_shows SET live_unlocked = TRUE, updated_at = NOW()
                WHERE id = $1::uuid
                  AND (
                    SELECT COUNT(*) FROM studio_episodes e
                    WHERE e.show_id = studio_shows.id AND e.state = 'published'
                      AND NOT EXISTS (
                        SELECT 1 FROM studio_compliance_flags f
                        WHERE f.episode_id = e.id AND f.status = 'open'
                      )
                  ) >= 1
                """,
                show_id,
            )
    if show_id:
        await extract_learning(db_pool, str(show_id))
    return {"ok": True, "state": "published"}


async def reject_episode(db_pool, episode_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE studio_episodes e
            SET state = 'rejected', updated_at = NOW()
            FROM studio_shows s
            WHERE e.id = $1::uuid AND e.show_id = s.id AND s.coach_id = $2
              AND e.state = 'in_review'
            RETURNING e.id
            """,
            episode_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {"ok": True, "state": "rejected"}


async def add_cuts(
    db_pool, episode_id: str, coach_id: str, cuts: List[Any]
) -> Dict[str, Any]:
    if not cuts:
        return {"ok": False, "reason": "cuts required", "code": 422}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE studio_episodes e
            SET cuts_json = $3::jsonb, updated_at = NOW()
            FROM studio_shows s
            WHERE e.id = $1::uuid AND e.show_id = s.id AND s.coach_id = $2
            RETURNING e.id
            """,
            episode_id,
            coach_id,
            json.dumps(cuts),
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {"ok": True, "cuts": cuts}


async def resolve_flag(
    db_pool,
    episode_id: str,
    flag_id: str,
    coach_id: str,
    *,
    username: str,
    is_admin: bool,
    reason: str,
) -> Dict[str, Any]:
    reason = (reason or "").strip()
    if len(reason) < 8:
        return {"ok": False, "reason": "typed reason required", "code": 422}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        flag = await conn.fetchrow(
            """
            SELECT f.id, f.severity, f.status, f.episode_id
            FROM studio_compliance_flags f
            JOIN studio_episodes e ON e.id = f.episode_id
            JOIN studio_shows s ON s.id = e.show_id
            WHERE f.id = $1::uuid AND e.id = $2::uuid AND s.coach_id = $3
            """,
            flag_id,
            episode_id,
            coach_id,
        )
        if not flag:
            return {"ok": False, "reason": "not_found", "code": 404}
        if override_requires_admin(flag["severity"]) and not is_admin:
            return {"ok": False, "reason": "high_severity_needs_admin", "code": 403}
        await conn.execute(
            """
            UPDATE studio_compliance_flags SET status = 'overridden' WHERE id = $1::uuid
            """,
            flag_id,
        )
        await conn.execute(
            """
            INSERT INTO studio_compliance_flag_overrides
              (flag_id, episode_id, severity, reason, overridden_by)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            """,
            flag_id,
            episode_id,
            flag["severity"],
            reason,
            username,
        )
    return {"ok": True, "status": "overridden"}


async def list_episodes(db_pool, show_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "episodes": [], "code": 503}
    async with db_pool.acquire() as conn:
        show = await conn.fetchrow(
            "SELECT id FROM studio_shows WHERE id = $1::uuid AND coach_id = $2",
            show_id,
            coach_id,
        )
        if not show:
            return {"ok": False, "reason": "not_found", "code": 404}
        rows = await conn.fetch(
            """
            SELECT e.id, e.state, e.title, e.created_at,
                   e.media_r2_key, e.media_cut_r2_key, e.youtube_video_id,
                   COALESCE(sess.media_ready, FALSE) AS media_ready,
              (SELECT COUNT(*) FROM studio_compliance_flags f
                WHERE f.episode_id = e.id AND f.status = 'open') AS open_flags
            FROM studio_episodes e
            LEFT JOIN studio_sessions sess ON sess.id = e.session_id
            WHERE e.show_id = $1::uuid
            ORDER BY e.created_at DESC
            LIMIT 40
            """,
            show_id,
        )
    return {
        "ok": True,
        "episodes": [
            {
                "id": str(r["id"]),
                "state": r["state"],
                "title": r["title"],
                "open_flags": int(r["open_flags"] or 0),
                "media_r2_key": r.get("media_r2_key") or "",
                "media_cut_r2_key": r.get("media_cut_r2_key") or "",
                "media_ready": bool(r.get("media_ready")),
                "youtube_video_id": r.get("youtube_video_id") or "",
            }
            for r in rows
        ],
    }


async def create_from_session(db_pool, session_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        sess = await conn.fetchrow(
            """
            SELECT s.id, s.show_id, sh.name, s.media_r2_key, s.media_ready
            FROM studio_sessions s
            JOIN studio_shows sh ON sh.id = s.show_id
            WHERE s.id = $1::uuid AND sh.coach_id = $2
            """,
            session_id,
            coach_id,
        )
        if not sess:
            return {"ok": False, "reason": "not_found", "code": 404}
        existing = await conn.fetchrow(
            "SELECT id FROM studio_episodes WHERE session_id = $1::uuid LIMIT 1",
            session_id,
        )
        if existing:
            return {"ok": True, "episode_id": str(existing["id"]), "existing": True}
        transcript = await _speaker_transcript(conn, session_id)
        media_key = (sess.get("media_r2_key") or "").strip()
        if not media_key:
            from app.services.studio_livekit import session_media_r2_key

            candidate = session_media_r2_key(session_id)
            try:
                from app.services.r2_storage import head_object

                if candidate and head_object(key=candidate):
                    media_key = candidate
            except Exception:
                media_key = ""
        ep = await conn.fetchrow(
            """
            INSERT INTO studio_episodes
              (show_id, session_id, state, title, transcript_json,
               media_r2_key, media_master_r2_key)
            VALUES ($1::uuid, $2::uuid, 'in_review', $3, $4::jsonb, $5, $5)
            RETURNING id
            """,
            sess["show_id"],
            session_id,
            f"{sess['name']} session",
            json.dumps(transcript),
            media_key or None,
        )
    from app.services.studio_compliance import run_pass

    flags = await run_pass(db_pool, str(ep["id"]))
    return {"ok": True, "episode_id": str(ep["id"]), "compliance": flags}


async def regenerate_segment(
    db_pool, episode_id: str, coach_id: str, segment_id: str, coach_note: str
) -> Dict[str, Any]:
    note = (coach_note or "").strip()
    if not note:
        return {"ok": False, "reason": "coach_note required", "code": 422}
    from app.services.studio_invariants import LN_COHOST_LABEL, inv6_blocks

    if inv6_blocks(note):
        return {"ok": False, "reason": "INV-6 blocked in coach note", "code": 422}
    text = f"{LN_COHOST_LABEL} rewrite ({segment_id}): {note}"
    provider = "template"
    if db_pool:
        try:
            from app.services.nate_inference_router import NateInferenceRouter

            out = await NateInferenceRouter().generate(
                prompt=(
                    f"Rewrite this educational show segment. Coach note: {note}. "
                    f"Speak as {LN_COHOST_LABEL}."
                ),
                system=(
                    f"You are {LN_COHOST_LABEL}. Never use clinical, therapy, diagnose, "
                    "treatment, prescribe, or assess your case."
                ),
                domain="general",
                max_tokens=400,
            )
            gen = (out.get("text") or "").strip()
            if gen:
                text = gen
                provider = out.get("provider") or "router"
        except Exception as exc:
            logger.warning("studio regen inference skipped: %s", exc)
    if inv6_blocks(text):
        return {"ok": False, "reason": "INV-6 blocked generated text", "code": 422}
    if not db_pool:
        return {"ok": True, "text": text, "dry": True, "provider": provider}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
        if not row:
            return {"ok": False, "reason": "not_found", "code": 404}
        seg = {
            "speaker": "cohost_ai",
            "segment_id": segment_id,
            "text": text,
            "source": "regenerate",
        }
        await conn.execute(
            """
            UPDATE studio_episodes
            SET transcript_json = COALESCE(transcript_json, '[]'::jsonb) || $2::jsonb,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            episode_id,
            json.dumps([seg]),
        )
    return {"ok": True, "text": text, "segment_id": segment_id, "provider": provider}


async def extract_learning(db_pool, show_id: str) -> None:
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_show_learning (show_id, kind, payload_deidentified)
            VALUES ($1::uuid, 'publish', '{"source":"episode"}'::jsonb)
            """,
            show_id,
        )


def rss_xml(show: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
    title = escape(str(show.get("name") or "Sovereign Studio"))
    desc = escape(str(show.get("description") or LN_safe_desc()))
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        f"<title>{title}</title>",
        f"<description>{desc}</description>",
        "<language>en-us</language>",
    ]
    for it in items:
        parts.append("<item>")
        parts.append(f"<title>{escape(str(it.get('title') or 'Episode'))}</title>")
        parts.append(f"<guid>{escape(str(it.get('rss_guid') or it.get('id') or ''))}</guid>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return "\n".join(parts)


def LN_safe_desc() -> str:
    from app.services.studio_invariants import LN_COHOST_LABEL

    return f"Show with {LN_COHOST_LABEL}"


async def _speaker_transcript(conn, session_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        legs = await conn.fetch(
            """
            SELECT id, role, label, utterances_json
            FROM session_legs WHERE session_id = $1::uuid ORDER BY created_at
            """,
            session_id,
        )
    except Exception:
        legs = await conn.fetch(
            """
            SELECT id, role, label FROM session_legs
            WHERE session_id = $1::uuid ORDER BY created_at
            """,
            session_id,
        )
    for leg in legs:
        uttered = leg.get("utterances_json") if hasattr(leg, "get") else None
        if isinstance(uttered, str):
            try:
                uttered = json.loads(uttered)
            except Exception:
                uttered = []
        if isinstance(uttered, list) and uttered:
            for u in uttered:
                if isinstance(u, dict):
                    out.append(
                        {
                            "speaker": leg["role"],
                            "label": leg.get("label"),
                            "leg_id": str(leg["id"]),
                            "text": u.get("text") or "",
                        }
                    )
        else:
            out.append(
                {
                    "speaker": leg["role"],
                    "label": leg.get("label"),
                    "leg_id": str(leg["id"]),
                    "text": "",
                }
            )
    topics = await conn.fetch(
        """
        SELECT t.topic_deidentified
        FROM caller_topics t
        JOIN show_callers c ON c.id = t.caller_id
        WHERE c.session_id = $1::uuid
        ORDER BY t.created_at
        """,
        session_id,
    )
    for t in topics:
        out.append(
            {
                "speaker": "guest",
                "text": t["topic_deidentified"],
                "source": "topic",
            }
        )
    return out


def _ep(row) -> Dict[str, Any]:
    transcript = row.get("transcript_json")
    if isinstance(transcript, str):
        try:
            transcript = json.loads(transcript)
        except Exception:
            transcript = []
    cuts = row.get("cuts_json")
    if isinstance(cuts, str):
        try:
            cuts = json.loads(cuts)
        except Exception:
            cuts = []
    return {
        "id": str(row["id"]),
        "show_id": str(row["show_id"]),
        "state": row["state"],
        "title": row.get("title"),
        "approved_by": row.get("approved_by"),
        "transcript": transcript if isinstance(transcript, list) else [],
        "media_r2_key": row.get("media_r2_key") or "",
        "media_master_r2_key": row.get("media_master_r2_key") or "",
        "media_cut_r2_key": row.get("media_cut_r2_key") or "",
        "youtube_video_id": row.get("youtube_video_id") or "",
        "cuts": cuts if isinstance(cuts, list) else [],
    }


def _flag(row) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "severity": row["severity"],
        "category": row["category"],
        "detail": row.get("detail"),
        "status": row["status"],
    }
