"""Coach interview → style profile. Never writes client DEKs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("coach_voice_profile")


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
        "source": "heuristic",
    }


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
                "tone, cadence, topics (array), phrases (array of short quotes), stance.\n\n"
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
        data["source"] = "ln"
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
    style = await extract_style_via_ln(transcript) or heuristic_style(transcript)
    notes = (style.get("tone") or "") + " · " + ", ".join(style.get("topics") or [])
    if db_pool:
        async with db_pool.acquire() as conn:
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
            WHERE coach_id = $1 AND transcript_ciphertext IS NOT NULL
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
            client_id=row.get("client_id") or "",
            subject=row.get("subject") or "client",
        )
    return profile, transcript


async def _maybe_crystallize(db_pool, coach_id: str, transcript: str, style: Dict[str, Any]) -> None:
    snippet = (transcript or "").strip()
    if len(snippet) < 80:
        return
    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation
    except ImportError:
        return
    if not crystallize_from_conversation or not db_pool:
        return
    try:
        await crystallize_from_conversation(
            db_pool,
            coach_id,
            snippet[:1500],
            json.dumps({"style": style.get("tone"), "topics": style.get("topics")}),
            user_name=coach_id,
            domain="coaching",
            min_score=3,
            source="coach_voice_interview",
        )
    except TypeError:
        try:
            await crystallize_from_conversation(
                db_pool,
                coach_id,
                snippet[:1500],
                "",
                user_name=coach_id,
                domain="coaching",
                min_score=3,
            )
        except Exception as exc:
            logger.warning("coach voice crystallize failed: %s", exc)
    except Exception as exc:
        logger.warning("coach voice crystallize failed: %s", exc)
