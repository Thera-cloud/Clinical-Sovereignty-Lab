"""SSE Stage 5 — Delivery Runtime.

Core generation functions for daily panels, weekly clips, monthly recaps,
and gap recovery. Called by SSEOrchestrator.

Character consistency uses archetype_ref_url from sse_identity_forge —
the same Grok Imagine + source_image_url approach used by the
Thera-World Studio Pipeline's "Generate Character Refs".
"""
from __future__ import annotations
import asyncio, hashlib, json, logging, os, uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from app.sse.infrastructure import grok_imagine_client as grok, r2_storage
from app.sse.adapters.archetype_resolver import get_archetype_ref
from app.sse.adapters.world_story_bible import (
    get_character_manifestation, get_visual_style_suffix,
)
from app.sse.foundation import vault_integration as vault
from app.sse.thera_world_engine import build_rich_panel_prompt
from app.sse.adapters.clinical_translation import enrich_after_panel_generation

logger = logging.getLogger(__name__)
_BATCH, _COST_CAP = 10, 50.0
_IMG_COST, _VID_COST = 0.07, 0.25


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def sse_imagery_generation_enabled() -> bool:
    """Master switch for daily panels + journey batch Grok Imagine."""
    return _env_truthy("SSE_IMAGERY_GENERATION_ENABLED", "true")


def sse_weekly_clips_enabled() -> bool:
    return _env_truthy("SSE_WEEKLY_CLIPS_ENABLED", "false")


def sse_monthly_recap_enabled() -> bool:
    return _env_truthy("SSE_MONTHLY_RECAP_ENABLED", "false")


async def _log(
    c, sid, uid, gtype, url, prompt, score, cost, status, err=None, *, client_narrative=None,
):
    await c.execute(
        "INSERT INTO sse_delivery_generation_log "
        "(log_id,storyboard_id,user_id,generation_type,r2_url,prompt_used,"
        "score,cost,status,error_message,generation_date,client_narrative_text) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,CURRENT_DATE,$11) "
        "ON CONFLICT (user_id, storyboard_id, generation_type, generation_date) "
        "WHERE status = 'success' DO NOTHING",
        str(uuid.uuid4()), sid, uid, gtype, url, prompt, score, cost, status, err,
        (client_narrative or None),
    )


async def _breaker(c, sid) -> bool:
    spent = await c.fetchval(
        "SELECT COALESCE(SUM(cost),0) FROM sse_delivery_generation_log "
        "WHERE storyboard_id=$1 AND generated_at::date=CURRENT_DATE", sid)
    if (spent or 0) >= _COST_CAP:
        await c.execute(
            "INSERT INTO sse_cost_circuit_breaker "
            "(breaker_id,storyboard_id,daily_spend,reason,status) "
            "VALUES($1,$2,$3,'daily_limit_exceeded','tripped')",
            str(uuid.uuid4()), sid, float(spent))
        return True
    return False


async def _poll_video(vid_id: str, max_wait: int = 300) -> dict:
    backoff = 5
    for _ in range(15):
        await asyncio.sleep(backoff)
        r = await grok.poll_video_status(vid_id)
        if r["status"] != "processing":
            return r
        backoff = min(backoff * 2, 60)
    return {"status": "timeout", "url": None}


async def generate_daily_panels(sid: str, db_pool, skip_check=None) -> dict[str, Any]:
    if not sse_imagery_generation_enabled():
        logger.info("SSE daily_panel skipped: SSE_IMAGERY_GENERATION_ENABLED=false")
        return {
            "storyboard_id": sid, "users_processed": 0,
            "panels_generated": 0, "panels_failed": 0, "cost": 0, "status": "paused",
        }
    gen = fail = 0; cost = 0.0; today = date.today().isoformat()
    async with db_pool.acquire() as c:
        if await _breaker(c, sid):
            return {"storyboard_id": sid, "users_processed": 0,
                    "panels_generated": 0, "panels_failed": 0, "cost": 0}
        cfg = await c.fetchrow(
            "SELECT delivery_config FROM sse_delivery_config "
            "WHERE storyboard_id=$1 AND status='active' ORDER BY version DESC LIMIT 1", sid)
        dc = json.loads(cfg["delivery_config"]) if cfg else {}
        style = dc.get("panel_generation_style", "action_sequence")
        users = await c.fetch(
            "SELECT user_id,current_phase,ec_score FROM sse_enrolled_users "
            "WHERE storyboard_id=$1 AND status='active'", sid)
        for i in range(0, len(users), _BATCH):
            for u in users[i:i+_BATCH]:
                uid, phase = u["user_id"], u["current_phase"] or "the_becoming"
                if skip_check and await skip_check(uid):
                    continue
                archetype_url = await get_archetype_ref(uid, db_pool)
                arch_hint = None
                try:
                    async with db_pool.acquire() as _fc:
                        arch_hint = await _fc.fetchval(
                            "SELECT archetype_hint FROM sse_identity_forge "
                            "WHERE user_id=$1 AND status='complete' LIMIT 1", uid)
                except Exception:
                    pass
                rich: dict = {}
                client_nar = None
                try:
                    rich = await build_rich_panel_prompt(uid, db_pool)
                    prompt = rich["image_prompt"]
                    client_nar = (rich.get("narrative_text") or "").strip() or None
                except Exception as _prompt_err:
                    logger.warning("Rich prompt failed for %s, using fallback: %s", uid, _prompt_err)
                    prompt = f"{phase} panel, {style} tone, therapeutic visual"
                vs_suffix = get_visual_style_suffix(arch_hint)
                if vs_suffix:
                    prompt += f", {vs_suffix}"
                try:
                    manifestation = await get_character_manifestation(
                        phase, archetype_hint=arch_hint)
                    prompt += f", {manifestation}"
                except Exception as _man_err:
                    logger.warning("Manifestation suffix failed for %s: %s", uid, _man_err)
                h = hashlib.md5(prompt.encode()).hexdigest()[:12]
                key = f"stories/{uid}/daily_panel/{today}/{h}.png"
                try:
                    img = await grok.generate_image(
                        prompt, source_image_url=archetype_url)
                    url = await r2_storage.store_image(img, key)
                    await _log(c, sid, uid, "daily_panel", url, prompt, 1.0,
                               _IMG_COST, "success", client_narrative=client_nar)
                    if client_nar:  # FIX-NARRATIVE-DIVERSITY — journey continuity for next daily
                        try:
                            fs = (client_nar.split(".")[0].strip() + ".") if client_nar else ""
                            npc_wb = rich.get("current_npcs") or []
                            new_seq = await c.fetchval(
                                "UPDATE sse_user_journeys SET last_panel_summary=$1, last_panel_npcs=$2::jsonb, "
                                "panel_sequence=panel_sequence+1, last_panel_at=NOW() WHERE user_id=$3 "
                                "RETURNING panel_sequence",
                                fs, json.dumps(npc_wb), uid)
                            print(f">>> [DAILY-CONTINUITY] user={uid} seq={new_seq} summary_len={len(fs)}")
                        except Exception as _dc:
                            logger.warning("daily continuity writeback failed %s: %s", uid, _dc)
                    logger.info("[COST] daily_panel %s: $%.4f (grok)", uid, _IMG_COST)
                    try:
                        _lid = await c.fetchval(
                            """SELECT log_id FROM sse_delivery_generation_log
                               WHERE storyboard_id = $1 AND user_id = $2 AND generation_type = 'daily_panel'
                               ORDER BY generated_at DESC LIMIT 1""",
                            sid, uid,
                        )
                        _meta = {
                            "generation_prompt": prompt,
                            "narrative_text": rich.get("narrative_text", ""),
                            "panel_tone": rich.get("panel_tone", ""),
                            "biome": rich.get("biome", ""),
                            "archetype_hint": arch_hint or "",
                            "quest_context": "",
                            "therapeutic_intent": style,
                        }
                        asyncio.create_task(
                            enrich_after_panel_generation(
                                db_pool, uid, None, _meta,
                                str(_lid) if _lid else None,
                            )
                        )
                    except Exception as _cte:
                        logger.warning("daily_panel clinical translation schedule failed %s: %s", uid, _cte)
                    try: await vault.register_panel_in_vault(uid, url, phase, sid, "daily_panel", style, db_pool)
                    except Exception: logger.warning("Vault reg failed for %s/%s", sid, uid)
                    gen += 1; cost += _IMG_COST
                except Exception as e:
                    await _log(c, sid, uid, "daily_panel", "", prompt, 0, 0, "failed", str(e)[:300],
                               client_narrative=client_nar)
                    fail += 1
    return {"storyboard_id": sid, "users_processed": len(users),
            "panels_generated": gen, "panels_failed": fail, "cost": cost}


async def generate_weekly_clips(sid: str, db_pool) -> dict[str, Any]:
    if not sse_weekly_clips_enabled():
        logger.info("SSE weekly_clip disabled (SSE_WEEKLY_CLIPS_ENABLED=false)")
        return {
            "storyboard_id": sid, "clips_generated": 0, "clips_failed": 0,
            "substitutions": 0, "cost": 0, "status": "disabled",
        }
    now = datetime.now(timezone.utc)
    week_of_month = (now.day - 1) // 7 + 1
    if week_of_month >= 4:
        logger.info(
            "SSE weekly_clip skip: storyboard=%s week_of_month=%d "
            "(week 4 reserved for monthly_recap)",
            sid, week_of_month,
        )
        try:
            async with db_pool.acquire() as c:
                await _log(
                    c, sid, "_storyboard_level", "weekly_clip", "",
                    "skipped_week4", 0.0, 0.0, "skipped",
                    f"week_of_month={week_of_month} deferred to monthly_recap",
                )
        except Exception as e:
            logger.warning("Could not log weekly_clip skip: %s", e)
        return {
            "storyboard_id": sid,
            "clips_generated": 0,
            "clips_failed": 0,
            "substitutions": 0,
            "cost": 0,
            "status": "skipped_week4",
            "week_of_month": week_of_month,
            "reason": "deferred to monthly recap",
        }
    gen = fail = subs = 0; cost = 0.0
    ws = (now - timedelta(days=7)).date()
    we = now.date()
    async with db_pool.acquire() as c:
        users = await c.fetch(
            "SELECT user_id,current_phase FROM sse_enrolled_users "
            "WHERE storyboard_id=$1 AND status='active'", sid)
        for u in users:
            uid = u["user_id"]
            pc = await c.fetchval(
                "SELECT COUNT(*) FROM sse_delivery_generation_log "
                "WHERE storyboard_id=$1 AND user_id=$2 AND generation_type='daily_panel' "
                "AND status='success' AND generated_at::date>=$3 AND generated_at::date<$4",
                sid, uid, ws, we)
            if (pc or 0) < 4:
                await _log(c, sid, uid, "weekly_clip", "", "fog_substitute",
                           0.5, 0, "substituted", f"Only {pc}/7 panels")
                subs += 1; continue
            src = await c.fetchrow(
                "SELECT r2_url FROM sse_delivery_generation_log "
                "WHERE storyboard_id=$1 AND user_id=$2 AND generation_type='daily_panel' "
                "AND status='success' AND generated_at::date>=$3 AND generated_at::date<$4 "
                "ORDER BY score DESC,generated_at DESC LIMIT 1", sid, uid, ws, we)
            prompt = f"Weekly therapeutic clip for {u['current_phase'] or 'journey'}"
            try:
                vid_id = await grok.generate_video(prompt, src["r2_url"] if src else None)
                r = await _poll_video(vid_id)
                if r["status"] == "completed" and r.get("url"):
                    url = await r2_storage.store_video(r["url"], f"stories/{uid}/weekly_clip/{ws}/{vid_id}.mp4")
                    clip_nar = None
                    try:
                        _rn = await build_rich_panel_prompt(uid, db_pool)
                        clip_nar = (_rn.get("narrative_text") or "").strip() or None
                    except Exception:
                        pass
                    await _log(c, sid, uid, "weekly_clip", url, prompt, 1.0, _VID_COST, "success",
                               client_narrative=clip_nar)
                    try: await vault.register_panel_in_vault(uid, url, u["current_phase"] or "journey", sid, "weekly_clip", "cinematic", db_pool)
                    except Exception: logger.warning("Vault reg failed for clip %s/%s", sid, uid)
                    gen += 1; cost += _VID_COST
                else:
                    raise RuntimeError(f"Video {r['status']}")
            except Exception as e:
                await _log(c, sid, uid, "weekly_clip", "", prompt, 0, 0, "failed", str(e)[:300])
                fail += 1
    return {"storyboard_id": sid, "clips_generated": gen,
            "clips_failed": fail, "substitutions": subs, "cost": cost}


async def generate_monthly_recap(sid: str, db_pool) -> dict[str, Any]:
    if not sse_monthly_recap_enabled():
        logger.info("SSE monthly_recap disabled (SSE_MONTHLY_RECAP_ENABLED=false)")
        return {
            "storyboard_id": sid, "recaps_generated": 0, "fallbacks": 0,
            "cost": 0, "status": "disabled",
        }
    gen = fb = 0; cost = 0.0; ms = date.today().replace(day=1)
    async with db_pool.acquire() as c:
        users = await c.fetch(
            "SELECT user_id FROM sse_enrolled_users "
            "WHERE storyboard_id=$1 AND status='active'", sid)
        for u in users:
            uid = u["user_id"]
            clips = await c.fetchval(
                "SELECT COUNT(*) FROM sse_delivery_generation_log "
                "WHERE storyboard_id=$1 AND user_id=$2 AND generation_type='weekly_clip' "
                "AND status='success' AND generated_at::date>=$3", sid, uid, ms)
            panels = await c.fetchval(
                "SELECT COUNT(*) FROM sse_delivery_generation_log "
                "WHERE storyboard_id=$1 AND user_id=$2 AND generation_type='daily_panel' "
                "AND status='success' AND generated_at::date>=$3", sid, uid, ms)
            if (clips or 0) < 2 or (panels or 0) < 20:
                await _log(c, sid, uid, "monthly_recap", "", "slideshow_fallback",
                           0.5, 0, "fallback", f"clips={clips} panels={panels}")
                fb += 1; continue
            archetype_url = await get_archetype_ref(uid, db_pool)
            prompt = "Monthly therapeutic recap — three-act structure"
            try:
                vid_id = await grok.generate_video(prompt, archetype_url)
                r = await _poll_video(vid_id)
                recap_cost = _VID_COST * 3
                if r["status"] == "completed" and r.get("url"):
                    url = await r2_storage.store_video(
                        r["url"], f"stories/{uid}/monthly_recap/{ms}/{vid_id}.mp4")
                    recap_nar = None
                    try:
                        _rn = await build_rich_panel_prompt(uid, db_pool)
                        recap_nar = (_rn.get("narrative_text") or "").strip() or None
                    except Exception:
                        pass
                    await _log(c, sid, uid, "monthly_recap", url, prompt,
                               1.0, recap_cost, "success", client_narrative=recap_nar)
                    logger.info("[COST] monthly_recap video %s: $%.4f total", uid, recap_cost)
                    try: await vault.register_panel_in_vault(uid, url, "monthly_recap", sid, "monthly_recap", "cinematic", db_pool)
                    except Exception: logger.warning("Vault reg failed for recap %s/%s", sid, uid)
                    gen += 1; cost += recap_cost
                else:
                    raise RuntimeError(f"Video {r['status']}")
            except Exception as e:
                await _log(c, sid, uid, "monthly_recap", "", prompt,
                           0, 0, "failed", str(e)[:300])
                fb += 1
    return {"storyboard_id": sid, "recaps_generated": gen,
            "fallbacks": fb, "cost": cost}


async def check_and_recover_gaps(sid: str, db_pool) -> dict[str, Any]:
    rec = abn = summ = 0; cutoff = date.today() - timedelta(days=3)
    async with db_pool.acquire() as c:
        gaps = await c.fetch(
            "SELECT gap_id,user_id,gap_date,gap_type FROM sse_delivery_gap_log "
            "WHERE storyboard_id=$1 AND recovered=false AND abandoned=false "
            "ORDER BY gap_date DESC", sid)
        for g in gaps:
            if g["gap_type"] != "daily_panel":
                await c.execute("UPDATE sse_delivery_gap_log SET abandoned=true WHERE gap_id=$1", g["gap_id"])
                abn += 1; continue
            if g["gap_date"] < cutoff:
                try:
                    img = await grok.generate_image(f"Week-in-review summary for {g['user_id']}")
                    await r2_storage.store_image(img, f"stories/{g['user_id']}/recovery/{g['gap_date']}/summary.png")
                    summ += 1
                except Exception:
                    pass
                await c.execute("UPDATE sse_delivery_gap_log SET abandoned=true WHERE gap_id=$1", g["gap_id"])
                abn += 1
            else:
                try:
                    sub = await generate_daily_panels(sid, db_pool)
                    if sub.get("panels_generated", 0) > 0:
                        await c.execute("UPDATE sse_delivery_gap_log SET recovered=true WHERE gap_id=$1", g["gap_id"])
                        rec += 1
                except Exception:
                    pass
    return {"recovered_days": rec, "abandoned_days": abn, "summary_panels_generated": summ}


async def generate_from_directive(
    user_id: str,
    directive: dict[str, Any],
    db_pool,
) -> dict[str, Any]:
    """Generate content from a UCD CreativeDirective."""
    gen_id = str(uuid.uuid4())
    modality = directive.get("selected_modality", "panel")
    moment_class = directive.get("moment_class", "INTEGRATION")
    coherence_ctx = directive.get("coherence_context", "")

    prompt = (
        f"Therapeutic {modality} for moment: {moment_class}. "
        f"Coherence context: {coherence_ctx[:300]}"
    )

    try:
        ucd_client_nar = None
        if modality in ("panel", "journal_prompt"):
            try:
                _ur = await build_rich_panel_prompt(user_id, db_pool)
                ucd_client_nar = (_ur.get("narrative_text") or "").strip() or None
            except Exception:
                pass
            archetype_url = await get_archetype_ref(user_id, db_pool)
            img_bytes = await grok.generate_image(
                prompt, source_image_url=archetype_url)
            r2_key = f"stories/{user_id}/ucd/{gen_id}.png"
            r2_url = await r2_storage.store_image(img_bytes, r2_key)
        elif modality == "narration":
            r2_url = f"ucd/narration/{gen_id}"
        elif modality == "video_clip":
            r2_url = f"ucd/clip/{gen_id}"
        else:
            r2_url = f"ucd/{modality}/{gen_id}"

        async with db_pool.acquire() as c:
            await c.execute(
                "INSERT INTO sse_delivery_generation_log "
                "(log_id, storyboard_id, user_id, generation_type, r2_url, "
                "prompt_used, score, cost, status, directive_id, moment_class, "
                "creative_directive, client_narrative_text) "
                "VALUES ($1, 'ucd', $2, $3, $4, $5, 0.5, $6, 'ok', $7, $8, $9, $10)",
                gen_id, user_id, modality, r2_url, prompt[:500],
                _IMG_COST if modality in ("panel", "journal_prompt") else 0.0,
                directive.get("directive_id"),
                moment_class,
                json.dumps(directive, default=str),
                ucd_client_nar,
            )

        return {"generation_id": gen_id, "modality": modality, "r2_url": r2_url}

    except Exception as e:
        logger.error("UCD generation failed for %s (%s): %s — attempting fallback", user_id, modality, e)

        fallback_id = str(uuid.uuid4())
        fallback_prompt = f"therapeutic panel, healing journey, {moment_class.lower()} moment"
        try:
            fb_img = await grok.generate_image(fallback_prompt)
            fb_key = f"stories/{user_id}/ucd/{fallback_id}.png"
            fb_url = await r2_storage.store_image(fb_img, fb_key)
            fb_nar = None
            try:
                _fr = await build_rich_panel_prompt(user_id, db_pool)
                fb_nar = (_fr.get("narrative_text") or "").strip() or None
            except Exception:
                pass
            async with db_pool.acquire() as c:
                await _log(c, "ucd", user_id, "daily_panel", fb_url,
                           fallback_prompt, 0.5, _IMG_COST, "fallback",
                           f"UCD {modality} failed: {str(e)[:200]}",
                           client_narrative=fb_nar)
            logger.info("UCD fallback panel generated for %s: %s", user_id, fallback_id)
            return {"generation_id": fallback_id, "modality": "panel",
                    "r2_url": fb_url, "fallback": True}
        except Exception as fb_err:
            logger.error("UCD fallback also failed for %s: %s", user_id, fb_err)
            try:
                async with db_pool.acquire() as c:
                    await c.execute(
                        "INSERT INTO sse_delivery_generation_log "
                        "(log_id, storyboard_id, user_id, generation_type, "
                        "prompt_used, status, error_message, directive_id, moment_class) "
                        "VALUES ($1, 'ucd', $2, $3, $4, 'failed', $5, $6, $7)",
                        gen_id, user_id, modality, prompt[:500],
                        f"primary: {str(e)[:200]}; fallback: {str(fb_err)[:200]}",
                        directive.get("directive_id"), moment_class,
                    )
            except Exception:
                pass
            return {"generation_id": gen_id, "error": str(e)}
