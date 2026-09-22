"""Neuro region — DB-touching glue between neuro_scoring and generate_journey_panel.

QUANTUM-CRYSTAL-ARCH — additive. `generate_journey_panel` calls
`resolve_neuro_panel_context()` once; when it returns None the Origin path runs
byte-for-byte as before. When it returns a context, the SAME chat → crystals →
narrative → Grok Imagine → R2 → sse_panel_log pipeline fills the day's slot with a
Neuro place + champion instead of an Origin biome + core character.

Also owns the crystal metadata stamp (`ensure_neuro_metadata`) so
crystal_recall_bridge.py (protected) is never modified: existing
domain=clinical crystals gain metadata.neuro_stems / neuro_structures /
neuro_pole_hint lazily, bounded per run.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.sse.neuro_scoring import (
    all_domain_health,
    blend_scores,
    neuro_health,
    neuro_metadata_for_stems,
    pair_champion,
    resolve_panel_region,
    roll_coliseum_floor,
    AGE_GATE_EXCLUDE,
    scores_from_theme_counts,
    select_neuro_biome,
    visiting_figures,
)
from app.sse.thera_world_regions import (
    BIOME_TO_STRUCTURE,
    COLISEUM_FLOOR_VISUAL,
    REGION_NEURO,
    REGION_ORIGIN,
    neuro_biome_spec,
)

logger = logging.getLogger(__name__)

_STAMP_BATCH = 40  # crystals stamped per panel run (bounded, lazy backfill)


def _loads(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return v


async def _resolve_uid(user_id: str, db_pool) -> Optional[str]:
    try:
        async with db_pool.acquire() as conn:
            uid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1", user_id)
        return str(uid) if uid else None
    except Exception as e:
        logger.warning("neuro uid resolve failed for %s: %s", user_id, e)
        return None


async def ensure_neuro_metadata(user_id: str, db_pool, limit: int = _STAMP_BATCH) -> int:
    """Stamp neuro_* metadata on this user's clinical crystals that lack it.

    Uses the engine's existing stem miner on each crystal_text; domain slug is
    untouched. Returns the number of crystals stamped.
    """
    from app.sse.thera_world_engine import _mine_themes_from_texts

    uid = await _resolve_uid(user_id, db_pool)
    if not uid:
        return 0
    stamped = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, crystal_text FROM nate_intelligence_crystals "
                "WHERE user_id = $1 AND superseded_by IS NULL "
                "AND (metadata IS NULL OR NOT (metadata ? 'neuro_stems')) "
                "ORDER BY created_at DESC LIMIT $2", uid, int(limit))
            for r in rows:
                text = r["crystal_text"] or ""
                stems = [s for s, c in _mine_themes_from_texts([text]).items() if c > 0]
                meta = neuro_metadata_for_stems(stems)
                await conn.execute(
                    "UPDATE nate_intelligence_crystals SET metadata = "
                    "COALESCE(metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
                    json.dumps(meta), r["id"])
                stamped += 1
    except Exception as e:
        logger.warning("ensure_neuro_metadata failed for %s: %s", user_id, e)
    return stamped


async def _last_panel_region(user_id: str, db_pool) -> str:
    try:
        async with db_pool.acquire() as conn:
            r = await conn.fetchval(
                "SELECT region FROM sse_panel_log WHERE user_id = $1 AND panel_type = 'journey' "
                "ORDER BY generated_at DESC LIMIT 1", user_id)
        return r or REGION_ORIGIN
    except Exception:
        return REGION_ORIGIN


async def _recent_neuro_biomes(user_id: str, db_pool, n: int = 3) -> List[str]:
    """Recent Neuro places, so the next panel walks a different doorway."""
    try:
        from app.sse.thera_world_regions import NEURO_BIOMES
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT biome FROM sse_panel_log WHERE user_id = $1 AND biome = ANY($2::text[]) "
                "ORDER BY generated_at DESC LIMIT $3",
                user_id, list(NEURO_BIOMES), n)
        seen: List[str] = []
        for r in rows:
            b = r["biome"]
            if b and b not in seen:
                seen.append(b)
        return seen
    except Exception:
        return []


async def _recent_neuro_champions(user_id: str, db_pool, n: int = 3) -> List[str]:
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT neuro_champion FROM sse_panel_log WHERE user_id = $1 AND region = 'neuro' "
                "AND neuro_champion IS NOT NULL ORDER BY generated_at DESC LIMIT $2", user_id, n)
        return [r["neuro_champion"] for r in rows if r["neuro_champion"]]
    except Exception:
        return []


def _champion_to_npc(c: Dict[str, Any]) -> Dict[str, str]:
    return {
        "name": c.get("name", ""),
        "role": c.get("role", ""),
        "visual_prompt_fragment": c.get("visual_prompt_fragment", ""),
        "neuro": "1",
    }


async def _stamped_theme_counts(user_id: str, db_pool) -> Dict[str, int]:
    """Read neuro_stems already stamped on crystals. Older than the live 150-text window still counts."""
    uid = await _resolve_uid(user_id, db_pool)
    if not uid:
        return {}
    counts: Dict[str, int] = {}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT metadata FROM nate_intelligence_crystals "
                "WHERE user_id = $1 AND superseded_by IS NULL AND metadata ? 'neuro_stems' "
                "ORDER BY created_at DESC LIMIT 200", uid)
        for r in rows:
            meta = _loads(r["metadata"]) or {}
            if not isinstance(meta, dict):
                continue
            for stem in meta.get("neuro_stems") or []:
                key = str(stem)
                counts[key] = counts.get(key, 0) + 1
    except Exception as e:
        logger.warning("stamped neuro stem read failed for %s: %s", user_id, e)
    return counts


async def compute_neuro_scores(user_id: str, profile: Dict[str, Any], journey: Dict[str, Any], db_pool) -> Dict[str, float]:
    """Rolling 12-vector. Live theme_counts and stamped crystal metadata share one vector.

    Per stem, the stronger count wins so the same crystal is not double-counted.
    """
    merged: Dict[str, int] = {}
    for src in (await _stamped_theme_counts(user_id, db_pool), profile.get("theme_counts") or {}):
        for k, v in (src or {}).items():
            try:
                n = int(v or 0)
            except (TypeError, ValueError):
                n = 0
            if n > merged.get(str(k), 0):
                merged[str(k)] = n
    fresh = scores_from_theme_counts(merged)
    prev = _loads(journey.get("neuro_scores")) or None
    if not isinstance(prev, dict) or not prev:
        prev = None
    return blend_scores(prev, fresh)


async def resolve_neuro_panel_context(
    user_id: str,
    profile: Dict[str, Any],
    journey: Dict[str, Any],
    db_pool,
    *,
    age_gated: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return None → Origin panel today. Otherwise a context dict:

        biome       {"biome": <neuro place id>, "description": ...}
        character   (champion_name, visual_prompt_fragment)
        npcs        [visiting figures as npc dicts]
        champion    full champion row
        scores      rolling 12-vector (engine-only)
        floor_id    Coliseum floor roll or None
        metadata    panel_metadata payload
    """
    # Lazy crystal stamp — bounded, never blocks the panel on failure.
    try:
        await ensure_neuro_metadata(user_id, db_pool)
    except Exception as e:
        logger.warning("neuro metadata stamp skipped for %s: %s", user_id, e)

    scores = await compute_neuro_scores(user_id, profile, journey, db_pool)
    last_region = await _last_panel_region(user_id, db_pool)
    region = resolve_panel_region(journey, scores, last_region=last_region)

    # Persist the score even on Origin days — this is the unlock row and the coach signal.
    try:
        # Journey row only. The score-log row is written once, with the panel id, on outcome.
        await _persist_scores(user_id, scores, None, None, None, db_pool, write_log=False)
    except Exception as e:
        logger.warning("neuro score persist failed for %s: %s", user_id, e)

    if region != REGION_NEURO:
        return None

    recent_places = await _recent_neuro_biomes(user_id, db_pool, n=3)
    biome_id = select_neuro_biome(scores, avoid=recent_places)
    spec = neuro_biome_spec(biome_id)
    if not spec:
        return None
    exclude = AGE_GATE_EXCLUDE if age_gated else ()
    skip = await _recent_neuro_champions(user_id, db_pool, n=2)
    champion = pair_champion(scores, biome_id, skip_names=skip, exclude_names=exclude)
    if not champion:
        return None
    visitors = visiting_figures(scores, biome_id, k=2, exclude_names=exclude)

    desc = spec.get("bright_description") if age_gated else spec.get("description")
    desc = desc or spec.get("description") or spec.get("display_name", biome_id)
    healing = spec.get("healing_visual") or ""
    if healing and healing not in desc:
        desc = f"{desc}. {healing}"
    floor_id = None
    if biome_id == "coliseum_of_ascendance":
        floor_id = roll_coliseum_floor(seed=f"{user_id}:{datetime.now(timezone.utc).date()}")
        desc = f"{desc}, {COLISEUM_FLOOR_VISUAL.get(floor_id, '')}".rstrip(", ")

    metadata = {
        "region": REGION_NEURO,
        "place_label": spec.get("display_name", biome_id),
        "floor_id": floor_id,
        "healing_visual": healing,
        "visitors": [v.get("name") for v in visitors],
        "champion_purpose": champion.get("purpose", ""),
        "age_gated": bool(age_gated),
    }
    return {
        "biome": {"biome": biome_id, "description": desc, "healing_visual": healing},
        "character": (champion.get("name", ""), champion.get("visual_prompt_fragment", "")),
        "npcs": [_champion_to_npc(v) for v in visitors],
        "champion": champion,
        "scores": scores,
        "floor_id": floor_id,
        "metadata": metadata,
    }


async def _persist_scores(
    user_id: str,
    scores: Dict[str, float],
    biome_id: Optional[str],
    champion: Optional[str],
    panel_id: Optional[str],
    db_pool,
    *,
    write_log: bool = True,
) -> None:
    hd = all_domain_health(scores)
    h = neuro_health(scores)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE sse_user_journeys SET neuro_scores = $1::jsonb, neuro_last_scored_at = NOW() "
            "WHERE user_id = $2", json.dumps(scores), user_id)
        if not write_log:
            return
        await conn.execute(
            "INSERT INTO sse_neuro_score_log (user_id, scores, h_d, h, selected_biome, champion, panel_id, source) "
            "VALUES ($1, $2::jsonb, $3::jsonb, $4, $5, $6, $7::uuid, $8)",
            user_id, json.dumps(scores), json.dumps(hd), round(h, 4),
            biome_id or select_neuro_biome(scores), champion, panel_id, "theme_counts")


async def record_neuro_panel_outcome(
    user_id: str,
    panel_id: str,
    ctx: Dict[str, Any],
    db_pool,
) -> None:
    """After the Origin-shaped INSERT succeeds, tag the row + journey as Neuro."""
    biome_id = ctx["biome"]["biome"]
    champion = ctx["champion"]
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_panel_log SET region = 'neuro', neuro_domain = $1, neuro_champion = $2, "
                "panel_metadata = COALESCE(panel_metadata, '{}'::jsonb) || $3::jsonb "
                "WHERE panel_id = $4::uuid",
                BIOME_TO_STRUCTURE.get(biome_id), champion.get("name"),
                json.dumps(ctx.get("metadata") or {}), panel_id)
            await conn.execute(
                "UPDATE sse_user_journeys SET current_region = 'neuro', neuro_biome = $1 WHERE user_id = $2",
                biome_id, user_id)
        await _persist_scores(user_id, ctx["scores"], biome_id, champion.get("name"), panel_id, db_pool)
    except Exception as e:
        logger.warning("record_neuro_panel_outcome failed for %s: %s", user_id, e)


async def record_origin_panel_outcome(user_id: str, db_pool) -> None:
    """Keep current_region honest when the Origin path ran (column is additive)."""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET current_region = 'origin' WHERE user_id = $1 "
                "AND current_region IS DISTINCT FROM 'origin'", user_id)
    except Exception as e:
        logger.debug("record_origin_panel_outcome skipped for %s: %s", user_id, e)
