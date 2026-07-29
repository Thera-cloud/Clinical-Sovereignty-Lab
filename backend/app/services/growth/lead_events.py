"""Record anonymized lead_events + growth_attribution_links (no PII).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.growth.lead_events")

_STAGES = frozenset(
    {
        "impression",
        "engage",
        "click",
        "quiz_start",
        "quiz_complete",
        "signup",
        "active_client",
    }
)
_KINDS = frozenset(
    {"marketing", "skyeye", "directory", "quiz", "try", "outreach"}
)
_PII_META_KEYS = frozenset(
    {
        "email",
        "phone",
        "name",
        "device_id",
        "hardware_id",
        "ip",
        "utterance",
        "quote",
        "body",
        "message",
    }
)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")


def _clean_meta(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (meta or {}).items():
        key = str(k).lower()
        if key in _PII_META_KEYS:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            if isinstance(v, str) and len(v) > 200:
                v = v[:200]
            out[key] = v
    return out


async def ensure_attribution_link(
    db_pool,
    *,
    content_kind: str,
    content_id: int,
    provider_slug: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    keyword_id: Optional[int] = None,
) -> Optional[int]:
    if content_kind not in _KINDS or not content_id:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO growth_attribution_links (
                content_kind, content_id, keyword_id, utm_campaign, provider_slug
            ) VALUES ($1,$2,$3,$4,$5)
            RETURNING id
            """,
            content_kind,
            int(content_id),
            keyword_id,
            (utm_campaign or "")[:120] or None,
            (provider_slug or "")[:80] or None,
        )
    return int(row["id"]) if row else None


async def record_lead_event(
    db_pool,
    *,
    stage: str,
    content_kind: Optional[str] = None,
    content_id: Optional[int] = None,
    provider_slug: Optional[str] = None,
    audience: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    source: str = "beacon",
    meta: Optional[Dict[str, Any]] = None,
    attribution_link_id: Optional[int] = None,
) -> Dict[str, Any]:
    stage = (stage or "").strip().lower()
    if stage not in _STAGES:
        raise ValueError(f"invalid stage: {stage}")
    kind = (content_kind or "").strip().lower() or None
    if kind and kind not in _KINDS:
        raise ValueError(f"invalid content_kind: {kind}")
    slug = (provider_slug or "").strip().lower() or None
    if slug and not _SLUG_RE.match(slug):
        slug = re.sub(r"[^a-z0-9-]", "", slug)[:80] or None

    link_id = attribution_link_id
    if link_id is None and kind and content_id:
        try:
            link_id = await ensure_attribution_link(
                db_pool,
                content_kind=kind,
                content_id=int(content_id),
                provider_slug=slug,
                utm_campaign=utm_campaign,
            )
        except Exception as e:
            logger.warning("attribution link create failed: %s", e)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO lead_events (
                stage, content_kind, content_id, attribution_link_id,
                provider_slug, audience, utm_campaign, source, meta
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
            RETURNING id, created_at
            """,
            stage,
            kind,
            int(content_id) if content_id else None,
            link_id,
            slug,
            (audience or "")[:80] or None,
            (utm_campaign or "")[:120] or None,
            (source or "beacon")[:80],
            json.dumps(_clean_meta(meta)),
        )
    return {
        "ok": True,
        "id": int(row["id"]),
        "stage": stage,
        "attribution_link_id": link_id,
    }
