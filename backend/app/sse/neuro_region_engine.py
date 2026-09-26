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

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.sse.neuro_scoring import (
    AGE_GATE_EXCLUDE,
    EXPLORE_REGEN_CAP,
    all_domain_health,
    blend_scores,
    compose_walk_addendum,
    explore_pointer_key,
    image_change_line,
    merge_alias_ids,
    neuro_health,
    neuro_metadata_for_stems,
    pair_champion,
    resolve_panel_region,
    roll_coliseum_floor,
    scores_from_theme_counts,
    select_neuro_biome,
    should_replace_today_panel,
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


async def resolve_journey_aliases(db_pool, *raw_ids: str) -> List[str]:
    """hardware_id + username for any identifier, so pick and still share one journey."""
    seed = merge_alias_ids(*raw_ids)
    if not seed:
        return []
    if not db_pool:
        return seed
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hardware_id, username FROM users "
                "WHERE hardware_id = ANY($1::text[]) OR username = ANY($1::text[]) "
                "LIMIT 1", seed)
        if row:
            return merge_alias_ids(row["hardware_id"], row["username"], *seed)
    except Exception as e:
        logger.warning("resolve_journey_aliases failed: %s", e)
    return seed


async def canonical_journey_user_id(db_pool, aliases: List[str]) -> str:
    """Prefer the journey row that already has panels."""
    ids = [a for a in aliases if a]
    if not ids:
        return ""
    if not db_pool:
        return ids[0]
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT user_id FROM sse_user_journeys WHERE user_id = ANY($1::text[]) "
                "ORDER BY last_panel_at DESC NULLS LAST, panels_generated DESC NULLS LAST "
                "LIMIT 1", ids)
        return str(row) if row else ids[0]
    except Exception:
        return ids[0]


async def _last_panel_region(user_id: str, db_pool, *, before_today: bool = False) -> str:
    try:
        aliases = await resolve_journey_aliases(db_pool, user_id)
        async with db_pool.acquire() as conn:
            if before_today:
                r = await conn.fetchval(
                    "SELECT region FROM sse_panel_log WHERE user_id = ANY($1::text[]) "
                    "AND panel_type = 'journey' AND generated_at::date < CURRENT_DATE "
                    "ORDER BY generated_at DESC LIMIT 1", aliases)
            else:
                r = await conn.fetchval(
                    "SELECT region FROM sse_panel_log WHERE user_id = ANY($1::text[]) "
                    "AND panel_type = 'journey' "
                    "ORDER BY generated_at DESC LIMIT 1", aliases)
        return r or REGION_ORIGIN
    except Exception:
        return REGION_ORIGIN


async def _recent_neuro_biomes(user_id: str, db_pool, n: int = 3) -> List[str]:
    """Recent Neuro places, so the next panel walks a different doorway."""
    try:
        from app.sse.thera_world_regions import NEURO_BIOMES
        async with db_pool.acquire() as conn:
            aliases = await resolve_journey_aliases(db_pool, user_id)
            rows = await conn.fetch(
                "SELECT biome FROM sse_panel_log WHERE user_id = ANY($1::text[]) "
                "AND biome = ANY($2::text[]) "
                "ORDER BY generated_at DESC LIMIT $3",
                aliases, list(NEURO_BIOMES), n)
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
            aliases = await resolve_journey_aliases(db_pool, user_id)
            rows = await conn.fetch(
                "SELECT neuro_champion FROM sse_panel_log WHERE user_id = ANY($1::text[]) "
                "AND region = 'neuro' "
                "AND neuro_champion IS NOT NULL ORDER BY generated_at DESC LIMIT $2", aliases, n)
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
    replace_today: bool = False,
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
    last_region = await _last_panel_region(user_id, db_pool, before_today=replace_today)
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
    structure = BIOME_TO_STRUCTURE.get(biome_id) or ""
    if structure:
        metadata["change_line"] = image_change_line(scores, structure)
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


async def set_explore_region(user_ids: List[str], region: str, db_pool) -> str:
    """Store the client's story-path pick on every matching journey row."""
    from app.sse.thera_world_regions import EXPLORE_WANDER, REGION_NEURO, REGION_ORIGIN
    choice = (region or "").strip().lower()
    if choice not in (EXPLORE_WANDER, REGION_ORIGIN, REGION_NEURO):
        choice = EXPLORE_WANDER
    ids = await resolve_journey_aliases(db_pool, *[i for i in (user_ids or []) if i])
    if not ids or not db_pool:
        return choice
    try:
        async with db_pool.acquire() as conn:
            status = await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = "
                "jsonb_set(COALESCE(journey_metadata, '{}'::jsonb), '{explore_region}', to_jsonb($1::text), true) "
                "WHERE user_id = ANY($2::text[])",
                choice, ids)
        updated = 0
        try:
            updated = int(str(status).split()[-1])
        except Exception:
            updated = 0
        if updated == 0:
            from app.sse.thera_world_engine import get_or_create_journey
            canon = await canonical_journey_user_id(db_pool, ids)
            await get_or_create_journey(canon, db_pool)
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE sse_user_journeys SET journey_metadata = "
                    "jsonb_set(COALESCE(journey_metadata, '{}'::jsonb), '{explore_region}', to_jsonb($1::text), true) "
                    "WHERE user_id = $2",
                    choice, canon)
    except Exception as e:
        logger.warning("set_explore_region failed: %s", e)
    return choice


async def read_explore_region(user_ids: List[str], db_pool) -> str:
    from app.sse.neuro_scoring import explore_region_choice
    from app.sse.thera_world_regions import EXPLORE_WANDER
    ids = await resolve_journey_aliases(db_pool, *[i for i in (user_ids or []) if i])
    if not ids or not db_pool:
        return EXPLORE_WANDER
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT journey_metadata FROM sse_user_journeys WHERE user_id = ANY($1::text[]) "
                "ORDER BY last_panel_at DESC NULLS LAST LIMIT 1",
                ids)
        if not row:
            return EXPLORE_WANDER
        return explore_region_choice({"journey_metadata": row["journey_metadata"]})
    except Exception as e:
        logger.warning("read_explore_region failed: %s", e)
        return EXPLORE_WANDER


async def neuro_chat_addendum(db_pool, user_id: str) -> str:
    """Walk the chosen stream + growth map. Empty only when flag is off."""
    from app.sse.neuro_scoring import compose_growth_navigation, neuro_enabled, normalize_poles
    if not neuro_enabled() or not db_pool or not user_id:
        return ""
    aliases = await resolve_journey_aliases(db_pool, user_id)
    pick = await read_explore_region(aliases, db_pool)
    last_region = REGION_ORIGIN
    biome = ""
    character = ""
    narrative = ""
    raw = None
    try:
        async with db_pool.acquire() as conn:
            j = await conn.fetchrow(
                "SELECT neuro_scores, journey_metadata FROM sse_user_journeys "
                "WHERE user_id = ANY($1::text[]) ORDER BY last_panel_at DESC NULLS LAST LIMIT 1",
                aliases)
            p = await conn.fetchrow(
                "SELECT region, biome, character_manifest, narrative_text FROM sse_panel_log "
                "WHERE user_id = ANY($1::text[]) AND panel_type = 'journey' "
                "ORDER BY generated_at DESC LIMIT 1", aliases)
        if j:
            raw = j["neuro_scores"]
        if p:
            last_region = p["region"] or REGION_ORIGIN
            biome = p["biome"] or ""
            character = p["character_manifest"] or ""
            narrative = p["narrative_text"] or ""
    except Exception as e:
        logger.warning("neuro chat map skipped for %s: %s", user_id, e)
        return compose_walk_addendum(pick, last_region)
    walk = compose_walk_addendum(pick, last_region, biome, character, narrative)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
    scores = normalize_poles(raw if isinstance(raw, dict) else {})
    if not any(abs(v) >= 0.2 for v in scores.values()):
        return walk
    return walk + "\n\n" + compose_growth_navigation(scores)


async def record_origin_panel_outcome(user_id: str, db_pool) -> None:
    """Keep current_region honest when the Origin path ran (column is additive)."""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET current_region = 'origin' WHERE user_id = $1 "
                "AND current_region IS DISTINCT FROM 'origin'", user_id)
    except Exception as e:
        logger.debug("record_origin_panel_outcome skipped for %s: %s", user_id, e)


_explore_walk_tasks: Dict[str, asyncio.Task] = {}


async def _patch_journey_meta(db_pool, aliases: List[str], patch: Dict[str, Any]) -> None:
    if not db_pool or not aliases or not patch:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = "
                "COALESCE(journey_metadata, '{}'::jsonb) || $1::jsonb "
                "WHERE user_id = ANY($2::text[])",
                json.dumps(patch), aliases)
    except Exception as e:
        logger.warning("_patch_journey_meta failed: %s", e)


async def _today_panel(db_pool, aliases: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """region, panel_id, r2_url for today's latest journey still."""
    if not db_pool or not aliases:
        return None, None, None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT region, panel_id::text AS panel_id, r2_url FROM sse_panel_log "
                "WHERE user_id = ANY($1::text[]) AND panel_type = 'journey' "
                "AND generated_at::date = CURRENT_DATE "
                "ORDER BY generated_at DESC LIMIT 1", aliases)
        if not row:
            return None, None, None
        return row["region"], row["panel_id"], row["r2_url"]
    except Exception:
        return None, None, None


async def broadcast_explore_pointer(user_id: str, db_pool, extra: Optional[Dict[str, Any]] = None) -> None:
    """Write sse/journey/{id}/explore_region.json so R2 carries the live walk + still."""
    from app.sse.thera_world_regions import explore_region_choices
    aliases = await resolve_journey_aliases(db_pool, user_id)
    status = await explore_region_status(aliases, db_pool)
    if extra:
        status.update(extra)
    body = json.dumps(status, default=str).encode("utf-8")
    try:
        from app.sse.infrastructure.r2_storage import store_bytes
        for alias in aliases or [user_id]:
            if not alias:
                continue
            await store_bytes(body, explore_pointer_key(alias), "application/json")
    except Exception as e:
        logger.warning("broadcast_explore_pointer failed for %s: %s", user_id, e)


async def after_panel_landed(user_id: str, db_pool, panel: Dict[str, Any]) -> None:
    """Vault + R2 pointer after a journey still lands. Never raises to the caller."""
    aliases = await resolve_journey_aliases(db_pool, user_id)
    r2_url = (panel or {}).get("r2_url") or ""
    if r2_url:
        try:
            from app.sse.foundation.vault_integration import register_panel_in_vault
            await register_panel_in_vault(
                user_id, r2_url,
                (panel.get("biome") or "journey"),
                "thera_world",
                "neuro_panel" if panel.get("region") == REGION_NEURO else "daily_panel",
                panel.get("panel_tone") or "meditative",
                db_pool,
                extra={
                    "region": panel.get("region") or REGION_ORIGIN,
                    "character": panel.get("character") or "",
                    "panel_id": panel.get("panel_id") or "",
                },
            )
        except Exception as e:
            logger.warning("vault register after panel failed for %s: %s", user_id, e)
    await _patch_journey_meta(db_pool, aliases, {
        "explore_generating": False,
        "explore_intended": panel.get("region") or "",
    })
    await broadcast_explore_pointer(user_id, db_pool, {
        "last_panel_region": panel.get("region"),
        "last_panel_id": panel.get("panel_id"),
        "last_panel_url": r2_url,
        "last_panel_biome": panel.get("biome"),
        "last_panel_character": panel.get("character"),
        "generating": False,
    })


async def explore_region_status(user_ids: List[str], db_pool) -> Dict[str, Any]:
    from app.sse.thera_world_regions import explore_region_choices
    aliases = await resolve_journey_aliases(db_pool, *[i for i in (user_ids or []) if i])
    selected = await read_explore_region(aliases, db_pool)
    generating = False
    intended = ""
    last_region = REGION_ORIGIN
    last_id = None
    last_url = None
    last_biome = ""
    last_character = ""
    try:
        async with db_pool.acquire() as conn:
            j = await conn.fetchrow(
                "SELECT journey_metadata FROM sse_user_journeys "
                "WHERE user_id = ANY($1::text[]) ORDER BY last_panel_at DESC NULLS LAST LIMIT 1",
                aliases)
            p = await conn.fetchrow(
                "SELECT region, panel_id::text AS panel_id, r2_url, biome, character_manifest "
                "FROM sse_panel_log WHERE user_id = ANY($1::text[]) AND panel_type = 'journey' "
                "ORDER BY generated_at DESC LIMIT 1", aliases)
        meta = (j["journey_metadata"] if j else None) or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if isinstance(meta, dict):
            generating = bool(meta.get("explore_generating"))
            intended = str(meta.get("explore_intended") or "")
        if p:
            last_region = p["region"] or REGION_ORIGIN
            last_id = p["panel_id"]
            last_url = p["r2_url"]
            last_biome = p["biome"] or ""
            last_character = p["character_manifest"] or ""
    except Exception as e:
        logger.warning("explore_region_status failed: %s", e)
    return {
        "selected": selected,
        "explore_region": selected,
        "regions": explore_region_choices(),
        "generating": generating,
        "intended_region": intended,
        "last_panel_region": last_region,
        "last_panel_id": last_id,
        "last_panel_url": last_url,
        "last_panel_biome": last_biome,
        "last_panel_character": last_character,
    }


def _regen_count_today(meta: Any) -> int:
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        return 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if str(meta.get("explore_regen_on") or "") != today:
        return 0
    try:
        return int(meta.get("explore_regen_count") or 0)
    except (TypeError, ValueError):
        return 0


async def apply_explore_region_choice(user_ids: List[str], region: str, db_pool) -> Dict[str, Any]:
    """Persist the chip, then mint today's still if it is the other stream."""
    from app.sse.neuro_scoring import normalize_poles
    aliases = await resolve_journey_aliases(db_pool, *[i for i in (user_ids or []) if i])
    canon = await canonical_journey_user_id(db_pool, aliases)
    choice = await set_explore_region(aliases, region, db_pool)
    status = await explore_region_status(aliases, db_pool)
    today_region, today_id, today_url = await _today_panel(db_pool, aliases)
    last_before = await _last_panel_region(canon, db_pool, before_today=True)
    journey: Dict[str, Any] = {}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sse_user_journeys WHERE user_id = ANY($1::text[]) "
                "ORDER BY last_panel_at DESC NULLS LAST LIMIT 1", aliases)
        if row:
            journey = dict(row)
    except Exception as e:
        logger.warning("apply_explore_region journey load failed: %s", e)
    journey["journey_metadata"] = journey.get("journey_metadata") or {}
    if isinstance(journey["journey_metadata"], str):
        try:
            journey["journey_metadata"] = json.loads(journey["journey_metadata"])
        except Exception:
            journey["journey_metadata"] = {}
    if isinstance(journey["journey_metadata"], dict):
        journey["journey_metadata"]["explore_region"] = choice
    scores = normalize_poles(_loads(journey.get("neuro_scores")) or {})
    intended = resolve_panel_region(journey, scores, last_region=last_before)
    out = {
        **status,
        "selected": choice,
        "explore_region": choice,
        "intended_region": intended,
        "generated": False,
        "generating": False,
        "reason": "already_matched",
        "panel_id": today_id,
        "r2_url": today_url,
        "region": today_region or REGION_ORIGIN,
    }
    if not should_replace_today_panel(today_region, intended):
        await broadcast_explore_pointer(canon, db_pool)
        return out
    cap = _regen_count_today(journey.get("journey_metadata"))
    if cap >= EXPLORE_REGEN_CAP:
        out["reason"] = "regen_cap"
        await broadcast_explore_pointer(canon, db_pool)
        return out
    existing = _explore_walk_tasks.get(canon)
    if existing and not existing.done():
        out["generating"] = True
        out["reason"] = "in_flight"
        return out
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await _patch_journey_meta(db_pool, aliases, {
        "explore_generating": True,
        "explore_intended": intended,
        "explore_region": choice,
        "explore_regen_on": today,
        "explore_regen_count": cap + 1,
    })
    out["generating"] = True
    out["reason"] = "walking"
    task = asyncio.create_task(_walk_chosen_region(canon, db_pool), name=f"thera-walk-{canon[:24]}")
    _explore_walk_tasks[canon] = task
    return out


async def _walk_chosen_region(user_id: str, db_pool) -> None:
    try:
        from app.sse.thera_world_engine import generate_journey_panel
        result = await generate_journey_panel(user_id, db_pool, replace_today=True)
        if isinstance(result, dict) and not result.get("skipped"):
            logger.info(
                "Thera walk still minted user=%s region=%s biome=%s",
                user_id, result.get("region"), result.get("biome"))
    except Exception as e:
        logger.warning("Thera walk still failed for %s: %s", user_id, e)
    finally:
        try:
            aliases = await resolve_journey_aliases(db_pool, user_id)
            await _patch_journey_meta(db_pool, aliases, {"explore_generating": False})
            await broadcast_explore_pointer(user_id, db_pool)
        except Exception:
            pass
        _explore_walk_tasks.pop(user_id, None)
