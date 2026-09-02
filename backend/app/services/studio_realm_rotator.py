"""Rotating Thera-world realms behind Little Nate in the STUDIO live room.

Rotation is poll-driven rather than a scheduled agent. The live room asks for
the current realm; a new frame is generated only when a room is actually
polling. An empty studio generates nothing, so image spend stops with the show
instead of running 480 frames a day against a dark room.

Generation never blocks the poll: when the on-air frame ages past
REALM_ROTATE_SECONDS the request kicks off a background generate and returns
the frame that is still up. The next poll picks up the new realm and the
client plays the slide.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# One realm holds the screen for this long before the next one slides in.
REALM_ROTATE_SECONDS = 180

# The static plate shipped with the portrait page. This is realm zero, so the
# room has something on screen before the first generated frame lands.
BASELINE_REALM = {
    "frame_id": 0,
    "slug": "origin",
    "name": "Thera-World Origin",
    "blurb": "the origin chamber, gold light on black glass",
    "image_url": "thera_world_bg.jpg",
}

_STYLE = (
    "Digital broadcast backdrop for a late-night radio studio. "
    "Deep void black background, warm gold and muted teal light, "
    "soft volumetric haze, subtle scanline texture, cinematic depth. "
    "Wide establishing shot, no people, no faces, no text, no logos, "
    "no furniture in the center third — the center must stay open and dark "
    "so a host can be composited in front of it."
)

# Ordered rotation. Each realm is a place the show can broadcast from, with a
# name Little Nate can say out loud and a blurb he can react to.
REALMS: List[Dict[str, str]] = [
    {
        "slug": "glass_canyon",
        "name": "the Glass Canyon",
        "blurb": "a canyon of vertical glass walls with gold light falling between them",
        "prompt": "A vast canyon whose walls are sheer black glass, thin seams of gold light "
                  "falling down the cliff faces, floor lost in haze.",
    },
    {
        "slug": "tide_room",
        "name": "the Tide Room",
        "blurb": "a flooded hall where still black water mirrors the ceiling lights",
        "prompt": "A vast flooded hall, ankle-deep motionless black water mirroring a "
                  "ceiling of scattered warm gold lights, distant teal glow at the edges.",
    },
    {
        "slug": "lantern_field",
        "name": "the Lantern Field",
        "blurb": "an open plain of floating lanterns drifting in the dark",
        "prompt": "An open dark plain under a moonless sky, hundreds of small warm gold "
                  "lanterns floating at different heights, fading into teal mist.",
    },
    {
        "slug": "signal_tower",
        "name": "the Signal Tower",
        "blurb": "the top of a broadcast tower above a sea of low cloud",
        "prompt": "The upper platform of an immense broadcast tower rising above a sea of "
                  "low cloud at night, gold beacon light raking across teal haze.",
    },
    {
        "slug": "quiet_library",
        "name": "the Quiet Library",
        "blurb": "an endless dark library with gold reading lights far off",
        "prompt": "An endless library of black shelves receding into darkness, small warm "
                  "gold reading lamps glowing far down the aisles, dust in the air.",
    },
    {
        "slug": "salt_flats",
        "name": "the Salt Flats",
        "blurb": "cracked white flats under a huge dark sky",
        "prompt": "Cracked pale salt flats stretching to a flat horizon under an enormous "
                  "dark sky, a single band of gold light along the horizon line.",
    },
    {
        "slug": "engine_room",
        "name": "the Engine Room",
        "blurb": "a cathedral-sized machine hall breathing slow gold heat",
        "prompt": "A cathedral-sized machine hall of dark steel, slow gold heat glowing "
                  "from vents and seams, teal indicator lights in long rows, heavy haze.",
    },
    {
        "slug": "orchard_dark",
        "name": "the Night Orchard",
        "blurb": "rows of bare trees strung with small warm lights",
        "prompt": "Long rows of bare dark trees receding into fog, strung with small warm "
                  "gold bulbs, cool teal light pooling on the ground between rows.",
    },
    {
        "slug": "observatory",
        "name": "the Observatory",
        "blurb": "an open dome looking straight up into deep space",
        "prompt": "The interior of an open observatory dome at night, aperture split wide "
                  "to a dense starfield, gold instrument light along the curved walls.",
    },
    {
        "slug": "long_bridge",
        "name": "the Long Bridge",
        "blurb": "a suspension bridge running out into fog with no far shore",
        "prompt": "A long suspension bridge running straight out into thick night fog with "
                  "no visible far shore, gold deck lights receding, teal mist beyond.",
    },
]

_BY_SLUG = {r["slug"]: r for r in REALMS}

# Sessions with a generate in flight. Guards against a burst of polls all
# firing their own image call for the same rotation window.
_INFLIGHT: set[str] = set()

# session_id -> {frame dict, "at": monotonic seconds}
_CACHE: Dict[str, Dict[str, Any]] = {}

# Detached generate tasks are only referenced by the event loop, so hold them
# here until they finish or the GC can collect them mid-flight.
_TASKS: set[Any] = set()


def image_media_type(raw: bytes) -> str:
    """Sniff the frame format. The generator picks its own encoder per provider."""
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def next_slug(prev_slug: str) -> str:
    """Walk the catalog in order so a show tours realms instead of repeating."""
    slugs = [r["slug"] for r in REALMS]
    if prev_slug not in slugs:
        return slugs[0]
    return slugs[(slugs.index(prev_slug) + 1) % len(slugs)]


def realm_prompt(slug: str) -> str:
    realm = _BY_SLUG.get(slug) or REALMS[0]
    return f"{realm['prompt']} {_STYLE}"


def _frame_to_dict(row: Any, session_id: str) -> Dict[str, Any]:
    return {
        "frame_id": int(row["id"]),
        "slug": row["slug"],
        "name": row["name"],
        "blurb": row["blurb"] or "",
        "image_url": f"/api/studio/sessions/{session_id}/realm/{int(row['id'])}",
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
    }


async def _latest_frame(db_pool, session_id: str) -> Optional[Any]:
    if db_pool is None:
        return None
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT id, slug, name, blurb, r2_key, created_at
                FROM studio_realm_frames
                WHERE session_id = $1::uuid AND r2_key <> ''
                ORDER BY created_at DESC
                LIMIT 1
                """,
                session_id,
            )
    except Exception as exc:
        logger.warning("studio realm: latest frame lookup failed: %s", exc)
        return None


def _frame_age_seconds(row: Any) -> float:
    created = row["created_at"] if row else None
    if created is None:
        return 1e9
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return max(0.0, (now - created).total_seconds())
    except Exception:
        return 1e9


async def _generate_frame(db_pool, session_id: str, slug: str) -> None:
    """Generate one realm image, store it in R2, and record the frame."""
    realm = _BY_SLUG.get(slug) or REALMS[0]
    try:
        from app.sse.infrastructure.grok_imagine_client import generate_image

        raw = await generate_image(realm_prompt(slug), size="1024x1024")
        if not raw:
            logger.warning("studio realm: empty image for %s", slug)
            return

        ctype = image_media_type(raw)
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(ctype, "bin")
        key = f"studio_realms/{slug}/{int(time.time())}.{ext}"
        try:
            from app.services.r2_storage import upload_bytes_async

            await upload_bytes_async(key=key, content=raw, content_type=ctype)
        except Exception as exc:
            logger.warning("studio realm: R2 upload failed for %s: %s", key, exc)
            return

        if db_pool is None:
            return
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO studio_realm_frames
                    (session_id, slug, name, blurb, r2_key, byte_size, provider)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
                """,
                session_id,
                slug,
                realm["name"],
                realm["blurb"],
                key,
                len(raw),
                "grok-imagine-image",
            )
        logger.info("studio realm: %s ready for session %s (%d bytes)", slug, session_id, len(raw))
    except Exception as exc:
        logger.warning("studio realm: generate failed for %s: %s", slug, exc)
    finally:
        _INFLIGHT.discard(session_id)
        _CACHE.pop(session_id, None)


async def current_realm(db_pool, session_id: str) -> Dict[str, Any]:
    """Return the realm on air, scheduling the next one when this one is stale.

    Called on a short client poll, so it stays cheap: a cached answer inside
    the rotation window, one DB read otherwise, and image generation only ever
    as a detached task.
    """
    sid = str(session_id)
    cached = _CACHE.get(sid)
    if cached and (time.monotonic() - float(cached.get("at") or 0)) < 15:
        return dict(cached["frame"])

    row = await _latest_frame(db_pool, sid)
    frame = _frame_to_dict(row, sid) if row else dict(BASELINE_REALM)
    age = _frame_age_seconds(row) if row else 1e9

    if age >= REALM_ROTATE_SECONDS and sid not in _INFLIGHT:
        _INFLIGHT.add(sid)
        prev = row["slug"] if row else BASELINE_REALM["slug"]
        task = asyncio.create_task(_generate_frame(db_pool, sid, next_slug(prev)))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)

    frame["rotate_seconds"] = REALM_ROTATE_SECONDS
    frame["next_in"] = max(0, int(REALM_ROTATE_SECONDS - age)) if row else 0
    _CACHE[sid] = {"frame": dict(frame), "at": time.monotonic()}
    return frame


async def realm_image_bytes(db_pool, session_id: str, frame_id: int) -> Optional[bytes]:
    """Fetch one stored realm frame from R2 for same-session playback."""
    if db_pool is None:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT r2_key FROM studio_realm_frames
                WHERE id = $1 AND session_id = $2::uuid
                """,
                int(frame_id),
                str(session_id),
            )
    except Exception as exc:
        logger.warning("studio realm: frame lookup failed: %s", exc)
        return None
    key = (row["r2_key"] if row else "") or ""
    if not key:
        return None
    try:
        from app.services.r2_storage import download_bytes_async

        return await download_bytes_async(key=key)
    except Exception as exc:
        logger.warning("studio realm: R2 download failed for %s: %s", key, exc)
        return None
