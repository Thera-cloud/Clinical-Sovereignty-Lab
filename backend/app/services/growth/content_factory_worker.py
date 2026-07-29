"""Content factory: keyword_queue → blog draft → brand check → CEO review → SkyEye kids.

Phase 2b: demand_prior refresh + demand_themes in prompt. ENABLE_CONTENT_FACTORY gate.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.services.growth import content_factory_enabled
from app.services.growth.brand_checklist import run_brand_checklist
from app.services.growth.keyword_queue import KeywordQueueService
from app.services.growth.marketing_content_service import MarketingContentService
from app.services.growth.skyeye_handoff import enqueue_social_children
from app.services.growth.studio_budget import factory_generation_mode

logger = logging.getLogger("nate.growth.factory")

PROMPT_VERSION = "growth_factory_blog_v2"

_SYSTEM = """You write Sovereign Sanctuary blog drafts for coaches/clients.
Hard rules:
- No diagnosis, cure, guaranteed outcome, or fabricated statistics.
- No AGI claims. No PHI. No quotes from try.html or anonymous trial users.
- Crisis language only with 988; never describe methods.
- End with a short YMYL footer: not a substitute for professional care; 988 if in crisis.
- Warm, precise, non-hype. Avoid words: liminal, threshold, aching.
- Return markdown with a title line as '# Title' then body.
"""


class ContentFactoryWorker:
    def __init__(self, db_pool, *, redis=None, app_state=None, interval_s: int = 900):
        self.db_pool = db_pool
        self.redis = redis
        self.app_state = app_state
        self.interval_s = interval_s
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.keywords = KeywordQueueService(db_pool)
        self.content = MarketingContentService(db_pool)

    async def start(self) -> None:
        if not content_factory_enabled():
            logger.info("ContentFactoryWorker not started (ENABLE_CONTENT_FACTORY=false)")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("ContentFactoryWorker started (interval=%ss)", self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.warning("ContentFactoryWorker tick failed: %s", e)
            await asyncio.sleep(self.interval_s)

    async def _batch_size(self) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM growth_config WHERE key = 'factory_batch_size'"
                )
            if row and isinstance(row["value"], dict):
                return max(1, min(10, int(row["value"].get("n", 2))))
        except Exception:
            pass
        return 2

    async def _social_platforms(self) -> List[str]:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM growth_config WHERE key = 'factory_social_platforms'"
                )
            if row:
                val = row["value"]
                if isinstance(val, list):
                    return [str(x) for x in val]
                if isinstance(val, str):
                    return list(json.loads(val))
        except Exception:
            pass
        return ["x", "linkedin"]

    async def _generate_article(
        self, keyword: Dict[str, Any], *, demand_themes: Optional[List[str]] = None
    ) -> Dict[str, str]:
        kw = keyword.get("keyword") or "coaching"
        audience = keyword.get("audience") or "general"
        themes = [t for t in (demand_themes or []) if t and t != "ops_only"][:8]
        theme_line = ", ".join(themes) if themes else "(none — insufficient try theme history)"
        user_prompt = (
            f"Keyword: {kw}\nAudience: {audience}\nCluster: {keyword.get('cluster') or kw}\n"
            f"demand_themes (slugs only, anonymized try demand): {theme_line}\n"
            f"demand_prior: {keyword.get('demand_prior', 1.0)}\n"
            "Write a 600–900 word educational blog post. Include the YMYL footer. "
            "Use demand_themes only as topic gravity — never quote trial users."
        )
        text = ""
        model = "template_fallback"
        try:
            from app.services.growth.authority_map import get_factory_system_prompt
            from app.services.nate_inference_router import NateInferenceRouter

            system = await get_factory_system_prompt(self.db_pool, _SYSTEM)
            router = NateInferenceRouter(app_state=self.app_state)
            result = await router.generate(
                prompt=user_prompt,
                system=system,
                domain="marketing",
                max_tokens=1800,
            )
            if isinstance(result, dict):
                text = (result.get("text") or result.get("content") or "").strip()
                model = result.get("provider") or result.get("model") or "router"
            elif isinstance(result, str):
                text = result.strip()
                model = "router"
        except Exception as e:
            logger.warning("factory inference failed, using template: %s", e)

        if not text or len(text) < 120:
            title = f"Presence and practice: {kw}"
            body = (
                f"## Why {kw} matters\n\n"
                f"Coaches and clients keep returning to {kw} because care work "
                "asks for steadiness more than slogans. The aim is clarity, not cure.\n\n"
                "## Practical stance\n\n"
                "Name what is happening. Slow the pace. Keep the relationship in view. "
                "Avoid diagnosing. Offer structure without pretending certainty.\n\n"
                "## Closing\n\n"
                "Small honest moves compound. That is enough for today.\n\n"
                "---\n"
                "*This article is educational and not a substitute for professional care. "
                "If you or someone you love is in crisis, call or text 988.*"
            )
            model = "template_fallback"
            return {"title": title, "body": body, "model": model}

        title = f"Notes on {kw}"
        body = text
        if text.lstrip().startswith("#"):
            first, _, rest = text.lstrip().partition("\n")
            title = first.lstrip("# ").strip() or title
            body = rest.strip()
        if "988" not in body and "not a substitute" not in body.lower():
            body += (
                "\n\n---\n"
                "*This article is educational and not a substitute for professional care. "
                "If you or someone you love is in crisis, call or text 988.*"
            )
        return {"title": title[:200], "body": body, "model": model}

    async def tick(self) -> Dict[str, Any]:
        if not content_factory_enabled():
            return {"skipped": True, "reason": "ENABLE_CONTENT_FACTORY=false"}

        mode_info = await factory_generation_mode(self.db_pool, self.redis)
        batch = await self._batch_size()
        # QUANTUM-CRYSTAL-ARCH — Phase 2b: refresh demand before claim
        try:
            await self.keywords.refresh_demand_priors(limit=100)
        except Exception as e:
            logger.warning("factory demand refresh skipped: %s", e)
        from app.services.growth.demand_prior import top_demand_themes

        demand_themes = await top_demand_themes(self.db_pool, limit=8)
        claimed = await self.keywords.claim_next(limit=batch)
        results: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        platforms = await self._social_platforms()
        from app.services.growth.growth_hive import FACTORY_DIGEST_MIN

        # Batch ≥N → one digest email; suppress per-item CEO (blog only)
        use_digest = len(claimed) >= FACTORY_DIGEST_MIN

        for kw in claimed:
            kid = int(kw["id"])
            try:
                gen = await self._generate_article(kw, demand_themes=demand_themes)
                checklist = run_brand_checklist(gen["title"], gen["body"])
                if not checklist.get("passed"):
                    await self.keywords.mark(
                        kid,
                        status="blocked",
                        notes="brand_checklist:" + ",".join(checklist.get("fails") or []),
                    )
                    results.append(
                        {
                            "keyword_id": kid,
                            "status": "blocked",
                            "fails": checklist.get("fails"),
                        }
                    )
                    continue

                item = await self.content.create(
                    content_type="blog",
                    title=gen["title"],
                    draft_body=gen["body"],
                    platform="blog",
                    audience=kw.get("audience") or "general",
                    keyword_cluster=kw.get("cluster") or kw.get("keyword"),
                    keyword_id=kid,
                    generation_meta={
                        "prompt_version": PROMPT_VERSION,
                        "model": gen.get("model"),
                        "keyword_id": kid,
                        "demand_themes": demand_themes,
                        "priority_inputs": {
                            "volume_norm": kw.get("volume_norm"),
                            "intent": kw.get("intent"),
                            "audience_value": kw.get("audience_value"),
                            "buyer_prior": kw.get("buyer_prior"),
                            "demand_prior": kw.get("demand_prior"),
                            "priority_score": kw.get("priority_score"),
                        },
                        "studio_mode": mode_info.get("mode"),
                        "media_allowed": mode_info.get("media_allowed"),
                    },
                    brand_checklist=checklist,
                    created_by="content_factory",
                    submit_for_review=True,
                    notify_ceo=not use_digest,
                )
                cid = int(item["id"])
                kids = await enqueue_social_children(
                    self.db_pool,
                    parent_content_id=cid,
                    title=gen["title"],
                    body=gen["body"],
                    platforms=platforms,
                )
                await self.keywords.mark(kid, status="done", last_content_id=cid)
                pending_items.append(item)
                results.append(
                    {
                        "keyword_id": kid,
                        "content_id": cid,
                        "status": "pending_review",
                        "skyeye_children": kids,
                    }
                )
            except Exception as e:
                logger.warning("factory keyword %s failed: %s", kid, e)
                await self.keywords.mark(kid, status="queued", notes=f"retry:{e}")
                results.append({"keyword_id": kid, "status": "error", "error": str(e)})

        digest = None
        if use_digest and pending_items:
            try:
                from app.services.growth.growth_hive import enqueue_factory_digest

                digest = await enqueue_factory_digest(self.db_pool, pending_items)
            except Exception as e:
                logger.warning("factory digest failed, falling back per-item: %s", e)
                for it in pending_items:
                    try:
                        await self.content.enqueue_ceo_review(it)
                    except Exception:
                        pass

        return {
            "claimed": len(claimed),
            "results": results,
            "studio": mode_info,
            "ceo_digest": digest,
        }
