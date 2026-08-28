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

_DO_NOT_MARKERS = (
    "never",
    "do not",
    "don't",
    "dont ",
    "must not",
    "won't",
    "cannot say",
    "do-not",
    "forbid",
)
_TOSS_MARKERS = ("toss", "over to nate", "little nate", "take it nate")

STYLE_LIST_KEYS = (
    "phrases",
    "do_not_say",
    "toss_phrases",
    "signature_frameworks",
    "topics",
    "word_patterns",
)
STYLE_STR_KEYS = (
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


def extract_do_not_lines(text: str, *, all_lines: bool = False) -> List[str]:
    found: List[str] = []
    for raw in re.split(r"[\n;]+", text or ""):
        line = raw.strip().strip("-•*")
        if len(line) < 2:
            continue
        low = line.lower()
        if all_lines or any(m in low for m in _DO_NOT_MARKERS):
            if line not in found:
                found.append(line[:160])
        if len(found) >= 16:
            break
    return found


def extract_toss_lines(text: str) -> List[str]:
    found: List[str] = []
    for raw in re.split(r"[\n.]+", text or ""):
        line = raw.strip()
        if len(line) < 4:
            continue
        if any(m in line.lower() for m in _TOSS_MARKERS):
            if line not in found:
                found.append(line[:160])
        if len(found) >= 16:
            break
    return found


def style_diff(old: Dict[str, Any], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    old = old or {}
    new = new or {}
    for key in STYLE_LIST_KEYS:
        prev = {str(x).strip() for x in (old.get(key) or []) if str(x).strip()}
        nxt = {str(x).strip() for x in (new.get(key) or []) if str(x).strip()}
        for val in sorted(nxt - prev):
            changes.append({"key": key, "op": "add", "value": val})
        for val in sorted(prev - nxt):
            changes.append({"key": key, "op": "remove", "value": val})
    for key in STYLE_STR_KEYS:
        prev = str(old.get(key) or "").strip()
        nxt = str(new.get(key) or "").strip()
        if nxt and nxt != prev:
            changes.append({"key": key, "op": "set", "value": nxt, "previous": prev})
    return changes


def apply_style_ops(style: Dict[str, Any], ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(style or {})
    for raw in ops or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        op = str(raw.get("op") or "").strip()
        val = raw.get("value")
        if not key:
            continue
        if op == "set":
            out[key] = val
            continue
        lst = [str(x).strip() for x in (out.get(key) or []) if str(x).strip()]
        item = str(val or "").strip()
        if not item:
            continue
        if op == "add" and item not in lst:
            lst.append(item)
        elif op == "remove":
            lst = [x for x in lst if x != item]
        out[key] = lst[:16]
    return out


def heuristic_style(transcript: str) -> Dict[str, Any]:
    text = (transcript or "").strip()
    words = re.findall(r"[A-Za-z']+", text)
    lower = [w.lower() for w in words]
    first = sum(1 for w in lower if w in ("i", "i'm", "im", "we", "my", "our"))
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    caps = sorted({w for w in words if len(w) > 3 and w[0].isupper()})[:8]
    opener = sentences[0] if sentences else ""
    closer = sentences[-1] if len(sentences) > 1 else opener
    return {
        "tone": "warm" if first >= 8 else "direct",
        "cadence": "measured",
        "topics": caps,
        "phrases": sentences[:6],
        "word_patterns": [w for w in caps if len(w) > 4][:8],
        "preface_style": "short presence-first greeting" if first else "direct greeting",
        "introduction_style": opener[:180] or "name the feeling, then one question",
        "body_style": "concrete, one idea per paragraph",
        "climax_style": "one pointed invitation, not a lecture",
        "conclusion_style": closer[:180] or "leave the door open",
        "assistant_stance": "encourage without diagnosing",
        "do_not_say": extract_do_not_lines(text),
        "toss_phrases": extract_toss_lines(text),
        "signature_frameworks": [],
        "source": "heuristic",
        "version": 1,
    }


_PRESENCE_RANK = {"voice_biometrics": 3, "visual": 2, "transcript": 1}


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

    def _str(key: str, fallback: str = "") -> str:
        return str(new.get(key) or old.get(key) or fallback).strip()

    def _bios() -> Dict[str, Any]:
        for src in (new.get("voice_biometrics"), old.get("voice_biometrics")):
            if isinstance(src, dict) and src:
                return {
                    str(k): v
                    for k, v in src.items()
                    if isinstance(v, (int, float, str))
                }
        return {}

    new_src = str(new.get("presence_source") or "")
    old_src = str(old.get("presence_source") or "")
    keep_old_presence = (
        _PRESENCE_RANK.get(old_src, 0) > _PRESENCE_RANK.get(new_src, 0)
        and bool(old.get("presence_style"))
    )
    presence_style = (
        str(old.get("presence_style") or "").strip()
        if keep_old_presence
        else _str("presence_style")
    )
    presence_source = old_src if keep_old_presence else _str("presence_source")
    cadence = (
        str(old.get("cadence") or "measured").strip()
        if keep_old_presence
        else _str("cadence", "measured")
    )
    version = int(old.get("version") or 1) + 1
    bios = _bios()
    return {
        "tone": _str("tone", "direct"),
        "cadence": cadence,
        "topics": _list("topics"),
        "phrases": _list("phrases"),
        "word_patterns": _list("word_patterns"),
        "preface_style": _str("preface_style"),
        "introduction_style": _str("introduction_style"),
        "body_style": _str("body_style"),
        "climax_style": _str("climax_style"),
        "conclusion_style": _str("conclusion_style"),
        "presence_style": presence_style,
        "presence_source": presence_source,
        "visual_presence": _str("visual_presence"),
        "voice_biometrics": bios,
        "clone_voice_id": _str("clone_voice_id"),
        "stance": _str("stance"),
        "assistant_stance": _str("assistant_stance", "encourage without diagnosing"),
        "do_not_say": _list("do_not_say"),
        "toss_phrases": _list("toss_phrases"),
        "signature_frameworks": _list("signature_frameworks"),
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
                "Extract this coach's speaking and writing style as JSON only with keys "
                "tone, cadence, topics (array), phrases (array of short quotes), "
                "word_patterns (array of recurring words or stems), "
                "preface_style (how they open / greet), "
                "introduction_style (how they introduce a topic), "
                "body_style (how they develop the middle), "
                "climax_style (how they land the turn or invitation), "
                "conclusion_style (how they close), "
                "stance, assistant_stance, "
                "do_not_say (array of words/phrases they forbid), "
                "toss_phrases (array of on-air toss lines to Little Nate), "
                "signature_frameworks (array of named methods they use).\n\n"
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
        merged = merge_style(heuristic_style(text), data)
        merged["source"] = "ln"
        return merged
    except Exception as exc:
        logger.warning("coach voice profile LN extract failed: %s", exc)
        return None


async def upsert_voice_profile(
    db_pool,
    coach_id: str,
    transcript: str,
    *,
    recording_id: Optional[str] = None,
    biometrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    incoming = await extract_style_via_ln(transcript) or heuristic_style(transcript)
    if not incoming.get("presence_style"):
        from app.services.coach_voice_biometrics import presence_from_transcript

        incoming = merge_style(incoming, presence_from_transcript(transcript))
    if biometrics:
        incoming = merge_style(incoming, biometrics)
        incoming["source"] = incoming.get("source") or "ln"
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


async def backfill_presence(db_pool, coach_id: str) -> Dict[str, Any]:
    """Merge acoustic/transcript presence from the latest coach-self recording."""
    coach_id = (coach_id or "").strip()
    profile, transcript = await load_profile_and_transcript(db_pool, coach_id)
    if (
        profile.get("presence_source") == "voice_biometrics"
        and profile.get("presence_style")
    ):
        return {
            "ok": True,
            "skipped": "already_acoustic",
            "presence_style": profile.get("presence_style"),
        }
    bios: Dict[str, Any] = {}
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT audio_ciphertext FROM coach_voice_recordings
                WHERE coach_id = $1 AND subject = 'coach'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                coach_id,
            )
        if row and row.get("audio_ciphertext"):
            from app.services.voice_campaign_ingest import decrypt_coach_bytes
            from app.services.coach_voice_biometrics import extract_campaign_biometrics
            from app.services.biometrics_consent import is_biometrics_disabled

            blob = decrypt_coach_bytes(row["audio_ciphertext"])
            if blob and len(blob) >= 512:
                _bio_disabled = await is_biometrics_disabled(coach_id, db_pool)
                bios = extract_campaign_biometrics(blob, is_disabled=_bio_disabled) or {}
    if not transcript and not bios:
        return {"ok": False, "reason": "no_source"}
    filler = "Coach spoken presence captured from a stored interview recording."
    style = await upsert_voice_profile(
        db_pool, coach_id, transcript or filler, biometrics=bios or None
    )
    return {
        "ok": True,
        "presence_style": style.get("presence_style") or "",
        "presence_source": style.get("presence_source") or "",
    }


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
        f"cadence={style.get('cadence')}; "
        f"preface={style.get('preface_style')}; "
        f"intro={style.get('introduction_style')}; "
        f"body={style.get('body_style')}; "
        f"climax={style.get('climax_style')}; "
        f"close={style.get('conclusion_style')}; "
        f"presence={style.get('presence_style')}; "
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
