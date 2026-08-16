"""Coach campaign item preview / edit / hero still (Dispatch-condensed)."""

from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger("nate.coach_campaign_editor")

API_BASE = os.getenv(
    "API_PUBLIC_BASE", "https://api.sovereignsanctuary.net"
).rstrip("/")

EDITABLE_STATUSES = frozenset({"pending_review", "approved"})

_ITEM_COLS = """
    id, title, content_type, status, campaign_id, coach_id, post_urn,
    draft_body, hero_image_prompt, hero_image_url, hero_image_r2_key,
    hero_image_generated_at, updated_at, created_at
"""


def serialize_item(row: Any) -> Dict[str, Any]:
    from app.services.newsletter_imagery import strip_provider_prefix

    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, UUID):
            d[k] = str(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
    d["hero_image_prompt"] = strip_provider_prefix(d.get("hero_image_prompt") or "")
    if not d["hero_image_prompt"]:
        d["hero_image_prompt"] = default_hero_prompt(
            d.get("title") or "",
            d.get("content_type") or "",
            d.get("draft_body") or "",
        )
    cid = d.get("id")
    if cid is not None and d.get("hero_image_url"):
        d["hero_image_url"] = f"{API_BASE}/api/coach/integrations/campaigns/{int(cid)}/hero"
    return d


def default_hero_prompt(title: str, content_type: str, body: str = "") -> str:
    theme = (title or body or "steadiness").strip()
    theme = " ".join(theme.split())[:180]
    kind = (content_type or "campaign").replace("_", " ")
    return (
        f"Editorial illustration for a coach {kind}. Theme: {theme}. "
        "Warm cinematic atmosphere, soft gold and deep charcoal palette "
        "(#C9A962 accents on #050505), symbolic and hopeful — light through fog, "
        "open doorway, small figure reaching toward connection, or quiet landscape "
        "with a single lantern. Painterly digital art, no text, no logos, "
        "no medical equipment, no blood, no weapons, no photorealistic identifiable "
        "faces, family-safe, contemplative, 1:1 square composition."
    )


def render_preview_html(item: Dict[str, Any], *, hero_data_uri: str = "") -> str:
    title = html.escape((item.get("title") or "Untitled").strip() or "Untitled")
    ctype = html.escape((item.get("content_type") or "").strip())
    body = html.escape((item.get("draft_body") or "").strip())
    img = ""
    if hero_data_uri:
        img = f'<img src="{html.escape(hero_data_uri, quote=True)}" alt="Campaign still">'
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{margin:0;background:#050505;color:#E8D5A3;font-family:"
        "'DM Sans',sans-serif;padding:20px;max-width:560px}"
        "h1{font-family:'Cormorant Garamond',serif;color:#C9A962;font-size:1.35rem;"
        "margin:8px 0 12px}.badge{color:#8B7355;font-size:.72rem;letter-spacing:.08em;"
        "text-transform:uppercase}img{max-width:100%;border:1px solid #333;"
        "border-radius:8px;margin:8px 0 14px;display:block}"
        ".body{white-space:pre-wrap;line-height:1.55;font-size:.95rem}</style></head>"
        f"<body><div class='badge'>{ctype}</div><h1>{title}</h1>{img}"
        f"<div class='body'>{body or '—'}</div></body></html>"
    )


async def get_item(db_pool, content_id: int, coach_id: str) -> Optional[Dict[str, Any]]:
    if not db_pool:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT {_ITEM_COLS}
            FROM marketing_content
            WHERE id = $1 AND coach_id = $2
            """,
            int(content_id),
            coach_id,
        )
    return serialize_item(row) if row else None


async def update_item(
    db_pool,
    content_id: int,
    *,
    coach_id: str,
    title: Optional[str] = None,
    draft_body: Optional[str] = None,
    hero_image_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    from app.services.newsletter_imagery import strip_provider_prefix

    if not db_pool:
        return {"ok": False, "reason": "no_db"}
    prompt_val = None
    if hero_image_prompt is not None:
        prompt_val = strip_provider_prefix(hero_image_prompt)[:2000] or None
    title_val = (title[:300] if title is not None else None)
    body_val = (draft_body[:20000] if draft_body is not None else None)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE marketing_content SET
                title = COALESCE($3, title),
                draft_body = COALESCE($4, draft_body),
                hero_image_prompt = COALESCE($5, hero_image_prompt),
                updated_at = NOW()
            WHERE id = $1 AND coach_id = $2
              AND status = ANY($6::text[])
              AND COALESCE(post_urn, '') = ''
            RETURNING {_ITEM_COLS}
            """,
            int(content_id),
            coach_id,
            title_val,
            body_val,
            prompt_val,
            list(EDITABLE_STATUSES),
        )
    if not row:
        return {"ok": False, "reason": "not_editable"}
    return {"ok": True, "item": serialize_item(row)}


def _local_hero_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "/app/data")) / "coach_campaigns"


def _hero_public_url(content_id: int) -> str:
    return f"{API_BASE}/api/coach/integrations/campaigns/{int(content_id)}/hero"


async def load_hero_bytes(db_pool, content_id: int, coach_id: str) -> Optional[bytes]:
    if not db_pool:
        return None
    root = _local_hero_dir()
    for suffix in (".png", ".jpg", ".jpeg"):
        path = root / f"{int(content_id)}-hero{suffix}"
        if path.is_file():
            try:
                return path.read_bytes()
            except Exception:
                pass
    r2_key = None
    try:
        async with db_pool.acquire() as conn:
            r2_key = await conn.fetchval(
                """
                SELECT hero_image_r2_key FROM marketing_content
                WHERE id = $1 AND coach_id = $2 AND hero_image_r2_key IS NOT NULL
                """,
                int(content_id),
                coach_id,
            )
    except Exception:
        r2_key = None
    candidates = []
    if r2_key:
        candidates.append(r2_key)
    candidates.extend(
        [
            f"coach_campaigns/{coach_id}/{int(content_id)}-hero.png",
            f"coach_campaigns/{coach_id}/{int(content_id)}-hero.jpg",
        ]
    )
    for key in candidates:
        try:
            from app.services import r2_storage

            data = r2_storage.download_bytes(key=key)
            if data:
                return data
        except Exception as e:
            logger.debug("campaign hero R2 %s: %s", key, e)
    return None


def _to_data_uri(data: bytes) -> str:
    from app.services.newsletter_imagery import sniff_image_meta
    import base64

    _, media = sniff_image_meta(data)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{media};base64,{b64}"


async def preview_html(db_pool, content_id: int, coach_id: str) -> Optional[str]:
    item = await get_item(db_pool, content_id, coach_id)
    if not item:
        return None
    uri = ""
    blob = await load_hero_bytes(db_pool, content_id, coach_id)
    if blob:
        uri = _to_data_uri(blob)
    return render_preview_html(item, hero_data_uri=uri)


async def generate_hero(
    db_pool,
    content_id: int,
    *,
    coach_id: str,
    prompt_override: str = "",
) -> Dict[str, Any]:
    from app.services.newsletter_imagery import (
        generate_hero_bytes,
        hero_enabled,
        resolve_hero_prompt,
        sniff_image_meta,
    )

    if not db_pool:
        return {"ok": False, "error": "no_db"}
    if not hero_enabled():
        return {"ok": False, "error": "hero_disabled_or_no_image_key"}

    item = await get_item(db_pool, content_id, coach_id)
    if not item:
        return {"ok": False, "error": "not_found"}
    if item.get("status") not in EDITABLE_STATUSES or item.get("post_urn"):
        return {"ok": False, "error": "not_editable"}

    prompt = resolve_hero_prompt(
        item.get("title") or "",
        item.get("content_type") or "",
        stored_prompt=item.get("hero_image_prompt") or "",
        override=prompt_override or "",
    )
    if not prompt_override and not (item.get("hero_image_prompt") or "").strip():
        prompt = default_hero_prompt(
            item.get("title") or "",
            item.get("content_type") or "",
            item.get("draft_body") or "",
        )

    try:
        image_bytes, provider = await generate_hero_bytes(prompt)
    except Exception as e:
        logger.warning("campaign hero generate failed: %s", e)
        return {"ok": False, "error": f"imagine_failed:{e}"}

    suffix, content_type = sniff_image_meta(image_bytes)
    root = _local_hero_dir()
    root.mkdir(parents=True, exist_ok=True)
    local_path = root / f"{int(content_id)}-hero{suffix}"
    for other in (".png", ".jpg", ".jpeg"):
        if other == suffix:
            continue
        sibling = root / f"{int(content_id)}-hero{other}"
        if sibling.is_file():
            try:
                sibling.unlink()
            except Exception:
                pass
    local_path.write_bytes(image_bytes)
    try:
        os.chmod(local_path, 0o644)
    except Exception:
        pass

    r2_key = f"coach_campaigns/{coach_id}/{int(content_id)}-hero{suffix}"
    try:
        from app.services import r2_storage

        await r2_storage.upload_bytes_async(
            key=r2_key,
            content=image_bytes,
            content_type=content_type,
        )
    except Exception as e:
        logger.warning("campaign hero R2 upload: %s", e)

    public_url = _hero_public_url(int(content_id))
    stored_prompt = f"[provider:{provider}]\n{prompt}"[:2000]
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE marketing_content SET
                hero_image_url = $3,
                hero_image_r2_key = $4,
                hero_image_prompt = $5,
                hero_image_generated_at = NOW(),
                updated_at = NOW()
            WHERE id = $1 AND coach_id = $2
              AND status = ANY($6::text[])
              AND COALESCE(post_urn, '') = ''
            RETURNING {_ITEM_COLS}
            """,
            int(content_id),
            coach_id,
            public_url,
            r2_key,
            stored_prompt,
            list(EDITABLE_STATUSES),
        )
    if not row:
        return {"ok": False, "error": "not_editable"}
    return {
        "ok": True,
        "provider": provider,
        "hero_image_url": public_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item": serialize_item(row),
    }


async def rewrite_item(
    db_pool,
    content_id: int,
    *,
    coach_id: str,
    instruction: str,
    title: Optional[str] = None,
    draft_body: Optional[str] = None,
) -> Dict[str, Any]:
    """Expand coach notes into draft copy in their stored voice. Does not save."""
    note = (instruction or "").strip()
    if len(note) < 8:
        return {"ok": False, "reason": "instruction_too_short"}
    item = await get_item(db_pool, content_id, coach_id)
    if not item:
        return {"ok": False, "reason": "not_found"}
    if (item.get("status") or "") not in EDITABLE_STATUSES:
        return {"ok": False, "reason": "not_editable"}
    from app.services.coach_voice_profile_service import load_profile_and_transcript

    profile, transcript = await load_profile_and_transcript(db_pool, coach_id)
    crystal_ctx = ""
    try:
        from app.websocket.crystal_recall_bridge import recall_crystals_for_context

        crystal_ctx = await recall_crystals_for_context(
            db_pool, coach_id, max_results=6, source="coach_voice_interview"
        ) or ""
    except Exception as exc:
        logger.warning("rewrite crystal recall skipped: %s", exc)
    cur_title = (title if title is not None else item.get("title") or "").strip()
    cur_body = (draft_body if draft_body is not None else item.get("draft_body") or "").strip()
    ctype = (item.get("content_type") or "linkedin_post").strip()
    try:
        from app.services.coach_voice_biometrics import style_presence_block
        from app.services.nate_inference_router import NateInferenceRouter

        result = await NateInferenceRouter().generate(
            prompt=(
                f"Content type: {ctype}\n"
                f"Current title: {cur_title}\n"
                f"Current draft:\n{cur_body[:4000]}\n\n"
                f"Coach rewrite request (obey this; expand it in their voice):\n{note[:2000]}\n\n"
                f"Coach style JSON:\n{json.dumps(profile or {})[:2200]}\n"
                f"{style_presence_block(profile)}\n"
                f"Interview excerpt (tone only):\n{(transcript or '')[:2000]}\n"
                f"Style crystals:\n{(crystal_ctx or '')[:1200]}\n"
                "Write as this coach: match preface, introduction, body, climax, conclusion, "
                "presence_style, word_patterns, and phrases. Do not invent facts or client names. "
                "Return JSON only: {\"title\": \"...\", \"draft_body\": \"...\"}."
            ),
            system="Return valid JSON only. No markdown.",
            domain="coaching",
            max_tokens=700,
            temperature=0.4,
        )
    except Exception as exc:
        logger.warning("campaign rewrite LN failed: %s", exc)
        return {"ok": False, "reason": "ln_unavailable"}
    raw = ""
    if isinstance(result, dict):
        raw = (result.get("text") or result.get("content") or "").strip()
    elif isinstance(result, str):
        raw = result.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {"ok": False, "reason": "ln_parse"}
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return {"ok": False, "reason": "ln_parse"}
    if not isinstance(data, dict):
        return {"ok": False, "reason": "ln_parse"}
    new_title = str(data.get("title") or cur_title).strip()[:300]
    new_body = str(data.get("draft_body") or "").strip()[:20000]
    if len(new_body) < 20:
        return {"ok": False, "reason": "ln_empty"}
    try:
        from app.services.nate_response_validator import NateResponseValidator

        _cleaned, warnings = await NateResponseValidator().validate(new_body, {})
        if any("hallucination_pattern" in w or "unverified" in w for w in (warnings or [])):
            return {"ok": False, "reason": "validator"}
    except Exception as exc:
        logger.warning("rewrite validator skipped: %s", exc)
    return {
        "ok": True,
        "saved": False,
        "title": new_title,
        "draft_body": new_body,
        "style_used": {
            "tone": (profile or {}).get("tone"),
            "cadence": (profile or {}).get("cadence"),
            "version": (profile or {}).get("version"),
            "has_structure": bool(
                (profile or {}).get("preface_style")
                or (profile or {}).get("body_style")
            ),
            "has_presence": bool((profile or {}).get("presence_style")),
        },
    }
