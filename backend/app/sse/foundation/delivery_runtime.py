"""SSE Stage 5 — Delivery Runtime.

Core generation functions for daily panels, weekly clips, monthly recaps,
and gap recovery. Called by SSEOrchestrator.

LoRA-personalized generation uses replicate_client (Replicate Flux).
grok_imagine_client is retained for video animation (image-to-video)
and non-personalized recovery/summary panels only.
"""
from __future__ import annotations
import asyncio, hashlib, json, logging, uuid
import aiohttp
from datetime import date, datetime, timedelta, timezone
from typing import Any
from app.sse.infrastructure import grok_imagine_client as grok, r2_storage
from app.sse.infrastructure import replicate_client as replicate
from app.sse.adapters.lora_resolver import get_lora_ref
from app.sse.foundation import vault_integration as vault

logger = logging.getLogger(__name__)
_BATCH, _COST_CAP = 10, 50.0
_IMG_COST_GROK, _VID_COST = 0.07, 0.25
_IMG_COST_REPLICATE = 0.04
_IMG_COST = _IMG_COST_REPLICATE


async def _log(c, sid, uid, gtype, url, prompt, score, cost, status, err=None):
    await c.execute(
        "INSERT INTO sse_delivery_generation_log "
        "(log_id,storyboard_id,user_id,generation_type,r2_url,prompt_used,"
        "score,cost,status,error_message) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
        str(uuid.uuid4()), sid, uid, gtype, url, prompt, score, cost, status, err)


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
                lora_ref = await get_lora_ref(uid, db_pool)
                if not lora_ref:
                    await _log(c, sid, uid, "daily_panel", "", "", 0, 0,
                               "skipped", "No active LoRA — generation skipped")
                    fail += 1; continue
                prompt = f"{phase} panel, {style} tone, therapeutic visual"
                h = hashlib.md5(prompt.encode()).hexdigest()[:12]
                key = f"stories/{uid}/daily_panel/{today}/{h}.png"
                try:
                    urls = await replicate.generate_with_loras(
                        prompt, lora_urls=[lora_ref], lora_scales=[0.8])
                    if not urls:
                        raise RuntimeError("Replicate returned no images")
                    img_url = urls[0]
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(img_url) as resp:
                            img = await resp.read()
                    url = await r2_storage.store_image(img, key)
                    await _log(c, sid, uid, "daily_panel", url, prompt, 1.0,
                               _IMG_COST_REPLICATE, "success")
                    logger.info("[COST] daily_panel %s: $%.4f (replicate)", uid, _IMG_COST_REPLICATE)
                    try: await vault.register_panel_in_vault(uid, url, phase, sid, "daily_panel", style, db_pool)
                    except Exception: logger.warning("Vault reg failed for %s/%s", sid, uid)
                    gen += 1; cost += _IMG_COST_REPLICATE
                except Exception as e:
                    await _log(c, sid, uid, "daily_panel", "", prompt, 0, 0, "failed", str(e)[:300])
                    fail += 1
    return {"storyboard_id": sid, "users_processed": len(users),
            "panels_generated": gen, "panels_failed": fail, "cost": cost}


async def generate_weekly_clips(sid: str, db_pool) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    if (now.day - 1) // 7 + 1 >= 4:
        return {"storyboard_id": sid, "clips_generated": 0,
                "clips_failed": 0, "substitutions": 0, "cost": 0}
    gen = fail = subs = 0; cost = 0.0
    ws = (now - timedelta(days=7)).date()
    we = now.date()
    async with db_pool.acquire() as c:
        users = await c.fetch(
            "SELECT user_id,current_phase FROM sse_enrolled_users "
            "WHERE storyboard_id=$1 AND status='active'", sid)
        for u in users:
            uid = u["user_id"]
            lora_ref = await get_lora_ref(uid, db_pool)
            if not lora_ref:
                await _log(c, sid, uid, "weekly_clip", "", "", 0, 0,
                           "skipped", "No active LoRA — generation skipped")
                fail += 1; continue
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
                    await _log(c, sid, uid, "weekly_clip", url, prompt, 1.0, _VID_COST, "success")
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
    gen = fb = 0; cost = 0.0; ms = date.today().replace(day=1)
    async with db_pool.acquire() as c:
        users = await c.fetch(
            "SELECT user_id FROM sse_enrolled_users "
            "WHERE storyboard_id=$1 AND status='active'", sid)
        for u in users:
            uid = u["user_id"]
            lora_ref = await get_lora_ref(uid, db_pool)
            if not lora_ref:
                await _log(c, sid, uid, "monthly_recap", "", "", 0, 0,
                           "skipped", "No active LoRA — generation skipped")
                fb += 1; continue
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
            prompt = "Monthly therapeutic recap — three-act structure"
            try:
                recap_imgs = await replicate.generate_with_loras(
                    prompt, lora_urls=[lora_ref], lora_scales=[0.8])
                if not recap_imgs:
                    raise RuntimeError("Replicate returned no images for recap")
                source_img_url = recap_imgs[0]
                logger.info("[COST] monthly_recap image %s: $%.4f (replicate)", uid, _IMG_COST_REPLICATE)
                vid_id = await grok.generate_video(prompt, source_img_url)
                r = await _poll_video(vid_id)
                recap_cost = _IMG_COST_REPLICATE + _VID_COST * 3
                if r["status"] == "completed" and r.get("url"):
                    url = await r2_storage.store_video(
                        r["url"], f"stories/{uid}/monthly_recap/{ms}/{vid_id}.mp4")
                    await _log(c, sid, uid, "monthly_recap", url, prompt,
                               1.0, recap_cost, "success")
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
    """Generate content from a UCD CreativeDirective.

    Routes to the appropriate generation pipeline based on the
    directive's selected_modality. Returns dict with generation_id.
    """
    gen_id = str(uuid.uuid4())
    modality = directive.get("selected_modality", "panel")
    moment_class = directive.get("moment_class", "INTEGRATION")
    coherence_ctx = directive.get("coherence_context", "")

    prompt = (
        f"Therapeutic {modality} for moment: {moment_class}. "
        f"Coherence context: {coherence_ctx[:300]}"
    )

    try:
        if modality in ("panel", "journal_prompt"):
            img_bytes = await grok.generate_image(prompt)
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
                "creative_directive) "
                "VALUES ($1, 'ucd', $2, $3, $4, $5, 0.5, $6, 'ok', $7, $8, $9)",
                gen_id, user_id, modality, r2_url, prompt[:500],
                _IMG_COST if modality == "panel" else 0.0,
                directive.get("directive_id"),
                moment_class,
                json.dumps(directive, default=str),
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
            async with db_pool.acquire() as c:
                await _log(c, "ucd", user_id, "daily_panel", fb_url,
                           fallback_prompt, 0.5, _IMG_COST, "fallback",
                           f"UCD {modality} failed: {str(e)[:200]}")
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
