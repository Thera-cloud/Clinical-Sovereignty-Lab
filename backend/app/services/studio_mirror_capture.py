"""Mirror Capture — 7 parts on coach_voice_recordings. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("studio_mirror")

MIRROR_CAPTURE_PARTS: List[Dict[str, Any]] = [
    {
        "index": 1,
        "kind": "mirror_1_voice",
        "title": "Voice Foundation",
        "prompt": "Read a short passage in your natural speaking voice. This is the clone reference only if you later sign likeness consent.",
    },
    {
        "index": 2,
        "kind": "mirror_2_range",
        "title": "Emotional Range",
        "prompt": "Tell a 60-second story that moves from warmth to firmness and back. Do not perform — speak as you would on air.",
    },
    {
        "index": 3,
        "kind": "mirror_3_speech",
        "title": "Natural Speech",
        "prompt": "How do you greet a guarded guest? What do you refuse to say in public? What phrase do people hear when they feel stuck?",
    },
    {
        "index": 4,
        "kind": "mirror_4_personality",
        "title": "Personality Interview",
        "prompt": "Name your values, boundaries, signature phrases, and the jokes you will never make on this show.",
    },
    {
        "index": 5,
        "kind": "mirror_5_show",
        "title": "Show Behavior",
        "prompt": "When do you toss to Little Nate? How long do you let silence sit? How do you recover a rambling caller?",
    },
    {
        "index": 6,
        "kind": "mirror_6_writing",
        "title": "Writing Capture",
        "prompt": "Dictate how you open a newsletter, develop the middle, and close with one invitation.",
    },
    {
        "index": 7,
        "kind": "mirror_7_donot",
        "title": "Do-Not List",
        "prompt": "List words, claims, and postures Little Nate must never use in your voice.",
    },
]


def part_by_index(n: int) -> Optional[Dict[str, Any]]:
    for p in MIRROR_CAPTURE_PARTS:
        if p["index"] == int(n):
            return p
    return None


async def status(db_pool, coach_id: str) -> Dict[str, Any]:
    done: Dict[int, Dict[str, Any]] = {}
    clone_consent = False
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT capture_part_index, capture_kind, clone_consent, created_at
                FROM coach_voice_recordings
                WHERE coach_id = $1 AND capture_kind IS NOT NULL
                ORDER BY created_at DESC
                """,
                coach_id,
            )
            for r in rows:
                idx = r["capture_part_index"]
                if idx is None:
                    continue
                if int(idx) not in done:
                    done[int(idx)] = {
                        "kind": r["capture_kind"],
                        "clone_consent": bool(r["clone_consent"]),
                    }
            model = await conn.fetchrow(
                "SELECT clone_consent FROM studio_coach_models WHERE coach_id = $1",
                coach_id,
            )
            if model:
                clone_consent = bool(model["clone_consent"])
    parts = []
    for p in MIRROR_CAPTURE_PARTS:
        rec = done.get(p["index"])
        parts.append({**p, "complete": rec is not None})
    return {
        "ok": True,
        "parts": parts,
        "complete_count": sum(1 for p in parts if p["complete"]),
        "clone_consent": clone_consent,
        "label": "AI co-host and knowledge companion",
    }


async def record_clone_consent(db_pool, coach_id: str, signed: bool) -> Dict[str, Any]:
    if not signed:
        return {"ok": False, "reason": "signature required", "code": 422}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_coach_models (coach_id, clone_consent, clone_consent_at, updated_at)
            VALUES ($1, TRUE, NOW(), NOW())
            ON CONFLICT (coach_id) DO UPDATE SET
              clone_consent = TRUE,
              clone_consent_at = NOW(),
              updated_at = NOW()
            """,
            coach_id,
        )
    return {"ok": True, "clone_consent": True}


async def finalize(db_pool, coach_id: str) -> Dict[str, Any]:
    from app.services.coach_voice_profile_service import (
        load_profile_and_transcript,
        upsert_voice_profile,
    )
    from app.services.voice_campaign_ingest import decrypt_recording_transcript

    snap = await status(db_pool, coach_id)
    transcript_parts: List[str] = []
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT capture_part_index, capture_kind, transcript_ciphertext, client_id, subject
                FROM coach_voice_recordings
                WHERE coach_id = $1 AND capture_kind IS NOT NULL
                ORDER BY capture_part_index ASC
                """,
                coach_id,
            )
        for r in rows:
            text = await decrypt_recording_transcript(
                db_pool,
                ciphertext=r["transcript_ciphertext"] or "",
                client_id=r["client_id"] or "",
                subject=r["subject"] or "coach",
            )
            if text:
                transcript_parts.append(f"[Part {r['capture_part_index']}] {text}")
    blob = "\n\n".join(transcript_parts)
    style = {}
    if blob:
        style = await upsert_voice_profile(db_pool, coach_id, blob)
    else:
        style, _ = await load_profile_and_transcript(db_pool, coach_id)
    if db_pool and style:
        await _push_style_to_shows(db_pool, coach_id, style)
        await _push_show_behavior(db_pool, coach_id, style)
    return {
        "ok": True,
        "summary": {
            "tone": style.get("tone"),
            "cadence": style.get("cadence"),
            "phrases": (style.get("phrases") or [])[:6],
            "do_not_say": style.get("do_not_say") or [],
            "presence_style": style.get("presence_style") or "",
        },
        "complete_count": snap.get("complete_count"),
        "parts": snap.get("parts"),
    }


async def _push_style_to_shows(db_pool, coach_id: str, style: Dict[str, Any]) -> None:
    from app.services.studio_invariants import filter_style_layer
    import json

    cleaned, _ = filter_style_layer(style)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE studio_shows
            SET persona_style_layer = $2::jsonb, updated_at = NOW()
            WHERE coach_id = $1
            """,
            coach_id,
            json.dumps(cleaned),
        )


async def _push_show_behavior(db_pool, coach_id: str, style: Dict[str, Any]) -> None:
    import json

    toss = style.get("toss_phrases") or style.get("phrases") or []
    if not isinstance(toss, list):
        toss = []
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_coach_models (coach_id, toss_cues, pacing, updated_at)
            VALUES ($1, $2::jsonb, $3::jsonb, NOW())
            ON CONFLICT (coach_id) DO UPDATE SET
              toss_cues = EXCLUDED.toss_cues,
              pacing = EXCLUDED.pacing,
              updated_at = NOW()
            """,
            coach_id,
            json.dumps(toss[:16]),
            json.dumps({"cadence": style.get("cadence") or "measured"}),
        )
