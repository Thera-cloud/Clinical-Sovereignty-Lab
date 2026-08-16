"""Coach interview → style profile. Never writes client DEKs."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("coach_voice_profile")

INTERVIEW_PROMPTS = [
    "How do you greet a client who is guarded?",
    "What do you refuse to say in public copy?",
    "How do you encourage an assistant coach after a hard session?",
    "What phrase do clients hear from you when they feel stuck?",
]


def heuristic_style(transcript: str) -> Dict[str, Any]:
    text = (transcript or "").strip()
    words = re.findall(r"[A-Za-z']+", text)
    lower = [w.lower() for w in words]
    first = sum(1 for w in lower if w in ("i", "i'm", "im", "we", "my", "our"))
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()][:4]
    caps = sorted({w for w in words if len(w) > 3 and w[0].isupper()})[:8]
    return {
        "tone": "warm" if first >= 8 else "direct",
        "cadence": "measured",
        "topics": caps,
        "phrases": sentences,
        "assistant_stance": "encourage without diagnosing",
        "source": "heuristic",
        "version": 1,
    }


def merge_style(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    def _list(key: str) -> List[str]:
        seen = []
        for src in (old.get(key) or [], new.get(key) or []):
            if not isinstance(src, list):
                continue
            for item in src:
                s = str(item).strip()
                if s and s not in seen:
                    seen.append(s)
        return seen[:16]

    version = int(old.get("version") or 1) + 1
    return {
        "tone": new.get("tone") or old.get("tone") or "direct",
        "cadence": new.get("cadence") or old.get("cadence") or "measured",
        "topics": _list("topics"),
        "phrases": _list("phrases"),
        "stance": new.get("stance") or old.get("stance") or "",
        "assistant_stance": new.get("assistant_stance")
        or old.get("assistant_stance")
        or "encourage without diagnosing",
        "source": "merged",
        "version": version,
    }


async def _validate_text(text: str) -> List[str]:
    try:
        from app.services.nate_response_validator import NateResponseValidator

        _cleaned, warnings = await NateResponseValidator().validate(text or "", {})
        return list(warnings or [])
    except Exception as exc:
        logger.warning("style validator skipped: %s", exc)
        return []


async def extract_style_via_ln(transcript: str) -> Optional[Dict[str, Any]]:
    text = (transcript or "").strip()
    if len(text) < 40:
        return None
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter()
        result = await router.generate(
            prompt=(
                "Extract this coach's speaking style as JSON only with keys "
                "tone, cadence, topics (array), phrases (array of short quotes), "
                "stance, assistant_stance.\n\n"
                f"{text[:6000]}"
            ),
            system="Return valid JSON only. No markdown.",
            domain="coaching",
            max_tokens=400,
            temperature=0.3,
        )
        raw = ""
        if isinstance(result, dict):
            raw = (result.get("text") or result.get("content") or "").strip()
        elif isinstance(result, str):
            raw = result.strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start : end + 1])
        if not isinstance(data, dict):
            return None
        warnings = await _validate_text(json.dumps(data))
        if any("hallucination_pattern" in w or "unverified" in w for w in warnings):
            logger.warning("LN style extract failed validation: %s", warnings[:4])
            return None
        data["source"] = "ln"
        data["version"] = 1
        return data
    except Exception as exc:
        logger.warning("coach voice profile LN extract failed: %s", exc)
        return None


async def upsert_voice_profile(
    db_pool,
    coach_id: str,
    transcript: str,
    *,
    recording_id: Optional[str] = None,
) -> Dict[str, Any]:
    incoming = await extract_style_via_ln(transcript) or heuristic_style(transcript)
    style = incoming
    if db_pool:
        async with db_pool.acquire() as conn:
            prev = await conn.fetchrow(
                "SELECT style_json FROM coach_voice_profile WHERE coach_id = $1",
                coach_id,
            )
            old: Dict[str, Any] = {}
            if prev and prev.get("style_json"):
                raw = prev["style_json"]
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = {}
                if isinstance(raw, dict) and raw:
                    old = raw
                    style = merge_style(old, incoming)
            notes = (style.get("tone") or "") + " · " + ", ".join(style.get("topics") or [])
            await conn.execute(
                """
                INSERT INTO coach_voice_profile (coach_id, notes, style_json, source_recording_id, updated_at)
                VALUES ($1, $2, $3::jsonb, $4::uuid, NOW())
                ON CONFLICT (coach_id) DO UPDATE SET
                  notes = EXCLUDED.notes,
                  style_json = EXCLUDED.style_json,
                  source_recording_id = COALESCE(EXCLUDED.source_recording_id, coach_voice_profile.source_recording_id),
                  updated_at = NOW()
                """,
                coach_id,
                notes[:2000],
                json.dumps(style),
                recording_id,
            )
    await _maybe_crystallize(db_pool, coach_id, transcript, style)
    return style


async def load_profile_and_transcript(
    db_pool, coach_id: str
) -> Tuple[Dict[str, Any], str]:
    profile: Dict[str, Any] = {}
    transcript = ""
    if not db_pool:
        return profile, transcript
    async with db_pool.acquire() as conn:
        prow = await conn.fetchrow(
            """
            SELECT notes, style_json FROM coach_voice_profile WHERE coach_id = $1
            """,
            coach_id,
        )
        if prow:
            raw = prow.get("style_json") if hasattr(prow, "get") else None
            raw = raw or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            profile = dict(raw) if isinstance(raw, dict) else {}
            notes = prow.get("notes") if hasattr(prow, "get") else None
            if notes and not profile:
                profile = {"notes": notes}
        row = await conn.fetchrow(
            """
            SELECT id, client_id, subject, transcript_ciphertext
            FROM coach_voice_recordings
            WHERE coach_id = $1
              AND subject = 'coach'
              AND transcript_ciphertext IS NOT NULL
              AND transcript_ciphertext != ''
            ORDER BY created_at DESC
            LIMIT 1
            """,
            coach_id,
        )
    if row and row.get("transcript_ciphertext"):
        from app.services.voice_campaign_ingest import decrypt_recording_transcript

        transcript = await decrypt_recording_transcript(
            db_pool,
            ciphertext=row["transcript_ciphertext"],
            client_id="",
            subject="coach",
        )
    return profile, transcript


async def _maybe_crystallize(db_pool, coach_id: str, transcript: str, style: Dict[str, Any]) -> None:
    snippet = (transcript or "").strip()
    if len(snippet) < 40:
        return
    wrote = False
    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation

        hid = await crystallize_from_conversation(
            db_pool,
            coach_id,
            snippet[:1500],
            f"Coach style: {style.get('tone')} {style.get('assistant_stance') or style.get('stance') or ''}",
            user_name=coach_id,
            domain="coaching",
            min_score=1,
            origin_surface="coach_voice_interview",
        )
        wrote = bool(hid)
    except Exception as exc:
        logger.warning("coach voice crystallize via bridge: %s", exc)
    if not wrote:
        await _write_style_crystal(db_pool, coach_id, snippet, style)


async def _write_style_crystal(
    db_pool, coach_id: str, snippet: str, style: Dict[str, Any]
) -> None:
    if not db_pool:
        return
    crystal_text = (
        f"{coach_id} coach-interview style: tone={style.get('tone')}; "
        f"topics={', '.join((style.get('topics') or [])[:6])}; "
        f"said: \"{snippet[:300].strip()}\""
    )
    content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()
    try:
        async with db_pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                coach_id,
            )
            if not user_uuid:
                logger.warning("style crystal skipped — unresolved coach_id")
                return
            await conn.execute(
                """
                INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, user_id, origin_surface)
                VALUES ($1, 'coaching', 'user', '{}'::text[], 1, 0, 0.50, $2, $3, 'coach_voice_interview')
                ON CONFLICT (content_hash) DO NOTHING
                """,
                crystal_text,
                content_hash,
                user_uuid,
            )
        try:
            from app.services.vectorize_service import index_wisdom, is_vectorize_configured

            if is_vectorize_configured():
                await index_wisdom(
                    user_id=str(user_uuid),
                    wisdom_id=f"crystal_{content_hash[:16]}",
                    insight_type="crystal_coaching",
                    content=crystal_text,
                    source="coach_voice_interview",
                    domain="coaching",
                )
        except Exception:
            pass
    except Exception as exc:
        logger.warning("direct style crystal failed: %s", exc)


async def crystallize_approved_draft(
    db_pool, coach_id: str, title: str, body: str, audience: str
) -> None:
    text = f"{title}\n{(body or '').strip()}"
    if len(text) < 40:
        return
    await _write_style_crystal(
        db_pool,
        coach_id,
        text[:800],
        {
            "tone": "approved-draft",
            "topics": [audience or "clients"],
            "assistant_stance": "",
        },
    )
