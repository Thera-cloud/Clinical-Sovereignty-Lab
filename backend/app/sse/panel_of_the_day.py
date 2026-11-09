"""Panel-of-the-day resolver — one answer across both Thera-World pipelines.

Two pipelines mint client imagery:

* ``sse_panel_log`` — Thera-World *journey* stills (``panel_type='journey'``),
  minted by the layer-0 orchestrator / explore-region walk.
* ``sse_delivery_generation_log`` — storyboard *daily panels*
  (``generation_type='daily_panel'``), minted by the delivery runtime for every
  active ``sse_enrolled_users`` row.

Welcome recap, entry greeting, and the chat panel fallback previously read only
the journey table, so a client whose journey stills had stopped (symbol-safety
gate, paused imagery, alias drift) kept seeing — and Little Nate kept narrating —
a months-old scene while a fresh daily panel sat unused.

Resolution order (UTC calendar day):

1. journey still minted today
2. daily panel minted today
3. newest of the two, flagged ``is_stale`` when older than ``STALE_AFTER_DAYS``
4. ``None``

The pure chooser is separated from the SQL so it can be unit-tested offline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

STALE_AFTER_DAYS = 2.0

SOURCE_JOURNEY = "journey"
SOURCE_DELIVERY = "delivery"

_JOURNEY_SQL = """
    SELECT panel_id::text AS panel_id, panel_type, r2_url, narrative_text, biome,
           character_manifest, panel_tone, crystal_domains_used, generated_at,
           panel_metadata, COALESCE(region, 'origin') AS region
    FROM sse_panel_log
    WHERE user_id = ANY($1::text[])
      AND panel_type = 'journey'
      AND r2_url IS NOT NULL AND r2_url != ''
    ORDER BY generated_at DESC NULLS LAST
    LIMIT 1
"""

_DELIVERY_SQL = """
    SELECT log_id::text AS panel_id, generation_type, r2_url,
           COALESCE(NULLIF(btrim(client_narrative_text), ''), '') AS client_narrative_text,
           storyboard_id, generated_at
    FROM sse_delivery_generation_log
    WHERE user_id = ANY($1::text[])
      AND generation_type = 'daily_panel'
      AND status = 'success'
      AND r2_url IS NOT NULL AND r2_url != ''
    ORDER BY generated_at DESC NULLS LAST
    LIMIT 1
"""


def _as_utc(dt: Any) -> Optional[datetime]:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_days(dt: Optional[datetime], now: datetime) -> Optional[float]:
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 86400.0, 2)


def storyboard_title(storyboard_id: str) -> str:
    """Client-safe chapter title from a storyboard id (``the_father_and_broken_sons``)."""
    return (storyboard_id or "").replace("_", " ").strip().title()


def normalize_journey_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Shape a ``sse_panel_log`` journey row into the shared panel dict."""
    return {
        "panel_id": str(row.get("panel_id") or ""),
        "source_type": SOURCE_JOURNEY,
        "panel_type": row.get("panel_type") or "journey",
        "r2_url": row.get("r2_url") or "",
        "narrative_text": row.get("narrative_text") or "",
        "biome": row.get("biome") or "",
        "character_manifest": row.get("character_manifest") or "",
        "panel_tone": row.get("panel_tone") or "",
        "crystal_domains_used": row.get("crystal_domains_used"),
        "generated_at": _as_utc(row.get("generated_at")),
        "panel_metadata": row.get("panel_metadata"),
        "region": row.get("region") or "origin",
        "storyboard_id": "",
    }


def normalize_delivery_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Shape a ``sse_delivery_generation_log`` daily panel into the shared panel dict.

    ``biome`` carries the storyboard id — the same convention the journey feed
    (``/journey/panels``) and the tagged chat lookup already use for delivery rows.
    """
    narrative = (row.get("client_narrative_text") or "").strip()
    try:
        from app.services.sse_panel_chat_context import _infer_character_from_narrative
        character = _infer_character_from_narrative(narrative)
    except Exception:
        character = "Mirror"
    return {
        "panel_id": str(row.get("panel_id") or row.get("log_id") or ""),
        "source_type": SOURCE_DELIVERY,
        "panel_type": row.get("generation_type") or "daily_panel",
        "r2_url": row.get("r2_url") or "",
        "narrative_text": narrative,
        "biome": row.get("storyboard_id") or "",
        "character_manifest": character,
        "panel_tone": row.get("generation_type") or "daily_panel",
        "crystal_domains_used": None,
        "generated_at": _as_utc(row.get("generated_at")),
        "panel_metadata": None,
        "region": "origin",
        "storyboard_id": row.get("storyboard_id") or "",
    }


def choose_panel_of_the_day(
    journey: Optional[Mapping[str, Any]],
    delivery: Optional[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Pure chooser. ``journey``/``delivery`` are the newest row of each pipeline
    (already normalized or raw DB rows). Returns the shared panel dict with
    ``is_today`` / ``is_stale`` / ``age_days`` or ``None`` when neither exists."""
    now = _as_utc(now) or datetime.now(timezone.utc)
    today = now.date()

    j = None
    if journey:
        j = dict(journey) if journey.get("source_type") == SOURCE_JOURNEY else normalize_journey_row(journey)
        if not j.get("r2_url"):
            j = None
    d = None
    if delivery:
        d = dict(delivery) if delivery.get("source_type") == SOURCE_DELIVERY else normalize_delivery_row(delivery)
        if not d.get("r2_url"):
            d = None

    def _finish(p: dict[str, Any]) -> dict[str, Any]:
        gen = p.get("generated_at")
        age = _age_days(gen, now)
        p["age_days"] = age
        p["is_today"] = bool(gen and gen.date() == today)
        p["is_stale"] = bool(age is not None and age > STALE_AFTER_DAYS) if gen else True
        return p

    if j and j.get("generated_at") and j["generated_at"].date() == today:
        return _finish(j)
    if d and d.get("generated_at") and d["generated_at"].date() == today:
        return _finish(d)
    candidates = [p for p in (j, d) if p]
    if not candidates:
        return None
    candidates.sort(
        key=lambda p: p.get("generated_at") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return _finish(candidates[0])


async def resolve_panel_of_the_day(db, ids: list[str], *, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Async resolver. ``db`` is an asyncpg pool or connection (both expose ``fetchrow``)."""
    if db is None or not ids:
        return None
    journey = delivery = None
    try:
        journey = await db.fetchrow(_JOURNEY_SQL, ids)
    except Exception as exc:
        print(f">>> [PANEL-OF-DAY] journey lookup skipped: {type(exc).__name__}: {exc}")
    try:
        delivery = await db.fetchrow(_DELIVERY_SQL, ids)
    except Exception as exc:
        print(f">>> [PANEL-OF-DAY] delivery lookup skipped: {type(exc).__name__}: {exc}")
    return choose_panel_of_the_day(
        dict(journey) if journey else None,
        dict(delivery) if delivery else None,
        now=now,
    )


async def fetch_panel_row_by_id(db, panel_id: str, ids: list[str]) -> Optional[dict[str, Any]]:
    """Resolve one panel id across both pipelines (``panel_id`` or delivery ``log_id``)."""
    if db is None or not panel_id or not ids:
        return None
    try:
        row = await db.fetchrow(
            """
            SELECT panel_id::text AS panel_id, panel_type, r2_url, narrative_text, biome,
                   character_manifest, panel_tone, crystal_domains_used, generated_at,
                   panel_metadata, COALESCE(region, 'origin') AS region
            FROM sse_panel_log
            WHERE panel_id = $1::uuid AND user_id = ANY($2::text[])
            """,
            panel_id,
            ids,
        )
        if row:
            return normalize_journey_row(dict(row))
    except Exception as exc:
        print(f">>> [PANEL-OF-DAY] panel_id lookup skipped: {type(exc).__name__}: {exc}")
    try:
        drow = await db.fetchrow(
            """
            SELECT log_id::text AS panel_id, generation_type, r2_url,
                   COALESCE(NULLIF(btrim(client_narrative_text), ''), '') AS client_narrative_text,
                   storyboard_id, generated_at
            FROM sse_delivery_generation_log
            WHERE log_id = $1::uuid AND user_id = ANY($2::text[])
            """,
            panel_id,
            ids,
        )
        if drow:
            return normalize_delivery_row(dict(drow))
    except Exception as exc:
        print(f">>> [PANEL-OF-DAY] log_id lookup skipped: {type(exc).__name__}: {exc}")
    return None
