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
                SELECT capture_part_index, capture_kind, clone_consent, created_at,
                       (audio_ciphertext IS NOT NULL AND audio_ciphertext != '') AS has_audio,
                       (transcript_ciphertext IS NOT NULL AND transcript_ciphertext != '') AS has_transcript
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
                        "has_audio": bool(r["has_audio"]),
                        "has_transcript": bool(r["has_transcript"]),
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
        parts.append({
            **p,
            "complete": rec is not None,
            "has_audio": bool(rec and rec.get("has_audio")),
            "has_transcript": bool(rec and rec.get("has_transcript")),
        })
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


EDITABLE_STRINGS = (
    "tone",
    "cadence",
    "presence_style",
    "preface_style",
    "introduction_style",
    "body_style",
    "climax_style",
    "conclusion_style",
    "stance",
    "assistant_stance",
)
EDITABLE_LISTS = (
    "phrases",
    "do_not_say",
    "toss_phrases",
    "signature_frameworks",
    "topics",
)
BOOTH_KINDS = {
    "newsletter_open": "Write the opening two sentences of a newsletter in this coach's voice.",
    "toss": "Write one line this coach would use to toss to Little Nate on air.",
    "caller_recovery": "Write how this coach recovers a rambling caller in three sentences.",
    "free": "Respond in this coach's voice to the prompt.",
}


def sniff_audio_type(blob: bytes) -> str:
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
        return "audio/wav"
    if blob[:4] == b"OggS":
        return "audio/ogg"
    if blob[:3] == b"ID3" or (
        len(blob) > 2 and blob[0] == 0xFF and blob[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if len(blob) > 8 and blob[4:8] == b"ftyp":
        return "audio/mp4"
    return "audio/webm"


def review_fields(style: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in EDITABLE_STRINGS:
        out[key] = str((style or {}).get(key) or "")
    for key in EDITABLE_LISTS:
        raw = (style or {}).get(key) or []
        if not isinstance(raw, list):
            raw = [raw]
        out[key] = [str(x).strip() for x in raw if str(x).strip()][:16]
    return out


async def _latest_part_row(db_pool, coach_id: str, n: int):
    if not db_pool or not part_by_index(n):
        return None
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT id, audio_ciphertext, transcript_ciphertext, client_id, subject
            FROM coach_voice_recordings
            WHERE coach_id = $1 AND capture_part_index = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            coach_id,
            int(n),
        )


async def part_transcript(db_pool, coach_id: str, n: int) -> Dict[str, Any]:
    from app.services.voice_campaign_ingest import decrypt_recording_transcript

    row = await _latest_part_row(db_pool, coach_id, n)
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    text = await decrypt_recording_transcript(
        db_pool,
        ciphertext=row["transcript_ciphertext"] or "",
        client_id=row["client_id"] or "",
        subject=row["subject"] or "coach",
    )
    return {
        "ok": True,
        "index": int(n),
        "title": (part_by_index(n) or {}).get("title"),
        "transcript": text or "",
    }


async def part_audio(db_pool, coach_id: str, n: int) -> Dict[str, Any]:
    from app.services.voice_campaign_ingest import decrypt_coach_bytes

    row = await _latest_part_row(db_pool, coach_id, n)
    if not row or not row["audio_ciphertext"]:
        return {"ok": False, "reason": "not_found", "code": 404}
    blob = decrypt_coach_bytes(row["audio_ciphertext"] or "")
    if not blob:
        return {"ok": False, "reason": "empty_audio", "code": 404}
    return {
        "ok": True,
        "index": int(n),
        "bytes": blob,
        "content_type": sniff_audio_type(blob),
    }


async def persona_review(db_pool, coach_id: str) -> Dict[str, Any]:
    from app.services.coach_voice_profile_service import load_profile_and_transcript

    snap = await status(db_pool, coach_id)
    style, _ = await load_profile_and_transcript(db_pool, coach_id)
    show_id = None
    if db_pool:
        async with db_pool.acquire() as conn:
            show = await conn.fetchrow(
                """
                SELECT id, persona_style_layer FROM studio_shows
                WHERE coach_id = $1 ORDER BY updated_at DESC NULLS LAST LIMIT 1
                """,
                coach_id,
            )
            if show:
                show_id = str(show["id"])
                layer = show["persona_style_layer"] or {}
                if isinstance(layer, str):
                    import json
                    try:
                        layer = json.loads(layer)
                    except Exception:
                        layer = {}
                if isinstance(layer, dict) and layer:
                    from app.services.coach_voice_profile_service import merge_style
                    style = merge_style(style or {}, layer)
    return {
        "ok": True,
        "show_id": show_id,
        "style": review_fields(style or {}),
        "editable": {"strings": list(EDITABLE_STRINGS), "lists": list(EDITABLE_LISTS)},
        "complete_count": snap.get("complete_count"),
        "clone_consent": snap.get("clone_consent"),
    }


async def persist_persona(
    db_pool, coach_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    from app.services.coach_voice_profile_service import (
        load_profile_and_transcript,
        merge_style,
    )
    from app.services.studio_invariants import filter_style_layer
    import json

    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    cleaned, rejected = filter_style_layer(payload or {})
    locked = [
        k
        for k in rejected
        if str(k).startswith("_guardrail_") or str(k).startswith("_vertical_")
    ]
    if locked:
        return {
            "ok": False,
            "reason": "INV-5 locked keys rejected",
            "rejected": locked,
            "code": 422,
        }
    old, _ = await load_profile_and_transcript(db_pool, coach_id)
    style = merge_style(old or {}, cleaned)
    notes = (style.get("tone") or "") + " · " + ", ".join(style.get("topics") or [])
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO coach_voice_profile (coach_id, notes, style_json, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW())
            ON CONFLICT (coach_id) DO UPDATE SET
              notes = EXCLUDED.notes,
              style_json = EXCLUDED.style_json,
              updated_at = NOW()
            """,
            coach_id,
            notes[:2000],
            json.dumps(style),
        )
    await _push_style_to_shows(db_pool, coach_id, style)
    await _push_show_behavior(db_pool, coach_id, style)
    return {"ok": True, "style": review_fields(style)}


async def finalize(
    db_pool, coach_id: str, coach_note: str = ""
) -> Dict[str, Any]:
    from app.services.coach_voice_profile_service import (
        extract_do_not_lines,
        extract_toss_lines,
        load_profile_and_transcript,
        merge_style,
        style_diff,
        upsert_voice_profile,
    )
    from app.services.voice_campaign_ingest import decrypt_recording_transcript

    snap = await status(db_pool, coach_id)
    old_style, _ = await load_profile_and_transcript(db_pool, coach_id)
    transcript_parts: List[str] = []
    part7 = ""
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
        seen_idx = set()
        for r in rows:
            idx = r["capture_part_index"]
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            text = await decrypt_recording_transcript(
                db_pool,
                ciphertext=r["transcript_ciphertext"] or "",
                client_id=r["client_id"] or "",
                subject=r["subject"] or "coach",
            )
            if text:
                transcript_parts.append(f"[Part {idx}] {text}")
                if int(idx or 0) == 7:
                    part7 = text
    note = (coach_note or "").strip()[:2000]
    if note:
        transcript_parts.append(f"[Coach correction] {note}")
    blob = "\n\n".join(transcript_parts)
    style = {}
    if blob:
        style = await upsert_voice_profile(db_pool, coach_id, blob)
    else:
        style, _ = await load_profile_and_transcript(db_pool, coach_id)
    extra = {
        "do_not_say": extract_do_not_lines(part7, all_lines=bool(part7)),
        "toss_phrases": extract_toss_lines(blob),
    }
    if note:
        extra["do_not_say"] = extra["do_not_say"] + extract_do_not_lines(note)
    style = merge_style(style or {}, extra)
    if db_pool and style:
        await persist_persona(db_pool, coach_id, style)
    diff = style_diff(old_style or {}, style or {})
    return {
        "ok": True,
        "summary": {
            "tone": style.get("tone"),
            "cadence": style.get("cadence"),
            "phrases": (style.get("phrases") or [])[:6],
            "do_not_say": style.get("do_not_say") or [],
            "toss_phrases": style.get("toss_phrases") or [],
            "presence_style": style.get("presence_style") or "",
        },
        "style": review_fields(style or {}),
        "diff": diff,
        "coach_note": note,
        "complete_count": snap.get("complete_count"),
        "parts": snap.get("parts"),
    }


async def apply_persona_ops(
    db_pool, coach_id: str, ops: List[Dict[str, Any]]
) -> Dict[str, Any]:
    from app.services.coach_voice_profile_service import (
        apply_style_ops,
        load_profile_and_transcript,
    )

    old, _ = await load_profile_and_transcript(db_pool, coach_id)
    style = apply_style_ops(old or {}, ops)
    return await persist_persona(db_pool, coach_id, style)


async def booth_reply(
    db_pool, coach_id: str, kind: str, text: str
) -> Dict[str, Any]:
    from app.services.coach_voice_profile_service import load_profile_and_transcript

    kind = (kind or "free").strip()
    if kind not in BOOTH_KINDS:
        return {"ok": False, "reason": "unknown booth kind", "code": 422}
    prompt = (text or "").strip()[:2000]
    if kind == "free" and len(prompt) < 8:
        return {"ok": False, "reason": "prompt required", "code": 422}
    style, _ = await load_profile_and_transcript(db_pool, coach_id)
    fields = review_fields(style or {})
    instruction = BOOTH_KINDS[kind]
    system = (
        "You write as this coach for a private likeness check. Not therapy. "
        "Never use items in do_not_say. Stay in their tone and cadence.\n"
        f"Style: {fields}"
    )
    user_prompt = f"{instruction}\n\nCoach prompt: {prompt or '(none — use style only)'}"
    reply = ""
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        result = await NateInferenceRouter().generate(
            prompt=user_prompt,
            system=system,
            domain="marketing",
            max_tokens=280,
            temperature=0.5,
        )
        if isinstance(result, dict):
            reply = str(result.get("text") or result.get("content") or "").strip()
    except Exception as exc:
        logger.warning("booth generate failed: %s", exc)
    if not reply:
        reply = _booth_fallback(fields, kind, prompt)
    return {
        "ok": True,
        "kind": kind,
        "prompt": prompt,
        "reply": reply,
        "style_used": {
            "tone": fields.get("tone"),
            "cadence": fields.get("cadence"),
            "phrases": (fields.get("phrases") or [])[:4],
            "do_not_say": fields.get("do_not_say") or [],
        },
        "public": False,
    }


def _booth_fallback(fields: Dict[str, Any], kind: str, prompt: str) -> str:
    phrase = ((fields.get("phrases") or ["Let's stay with what matters."])[0])
    if kind == "toss":
        toss = (fields.get("toss_phrases") or ["Nate, take this with them."])[0]
        return toss
    if kind == "newsletter_open":
        return f"{fields.get('preface_style') or phrase} {prompt or ''}".strip()
    return f"{phrase} {prompt}".strip()


async def booth_feedback(
    db_pool,
    coach_id: str,
    verdict: str,
    note: str = "",
    reply: str = "",
) -> Dict[str, Any]:
    from app.services.coach_voice_profile_service import (
        apply_style_ops,
        extract_do_not_lines,
        load_profile_and_transcript,
    )

    verdict = (verdict or "").strip()
    if verdict not in ("like_me", "not_me", "too_soft"):
        return {"ok": False, "reason": "verdict must be like_me, not_me, or too_soft", "code": 422}
    old, _ = await load_profile_and_transcript(db_pool, coach_id)
    ops: List[Dict[str, Any]] = []
    note = (note or "").strip()[:240]
    clip = ""
    if reply:
        clip = reply.strip().split(".")[0].strip()[:160]
    if verdict == "like_me" and clip:
        ops.append({"key": "phrases", "op": "add", "value": clip})
    elif verdict == "not_me":
        bans = extract_do_not_lines(note, all_lines=bool(note)) or ([note] if note else [])
        if not bans and clip:
            bans = [clip]
        for item in bans[:6]:
            ops.append({"key": "do_not_say", "op": "add", "value": item})
    elif verdict == "too_soft":
        ops.append({"key": "tone", "op": "set", "value": "direct"})
        ops.append({"key": "cadence", "op": "set", "value": "brisk"})
        if note:
            ops.append({"key": "do_not_say", "op": "add", "value": note})
    style = apply_style_ops(old or {}, ops)
    saved = await persist_persona(db_pool, coach_id, style)
    saved["verdict"] = verdict
    saved["applied"] = ops
    return saved


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
