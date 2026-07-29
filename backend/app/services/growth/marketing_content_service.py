"""CRUD + status transitions for marketing_content + CEO enqueue.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.growth.content")

ALLOWED_TYPES = frozenset({"blog", "email_drip", "outreach", "directory_page"})
TERMINAL_OK = frozenset({"approved", "scheduled", "published"})


class MarketingContentService:
    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def create(
        self,
        *,
        content_type: str,
        title: str,
        draft_body: str = "",
        platform: str = "",
        audience: str = "general",
        slug: Optional[str] = None,
        keyword_cluster: Optional[str] = None,
        generation_meta: Optional[Dict[str, Any]] = None,
        created_by: str = "system",
        submit_for_review: bool = False,
    ) -> Dict[str, Any]:
        if content_type not in ALLOWED_TYPES:
            raise ValueError(f"invalid content_type: {content_type}")
        platform = platform or content_type
        status = "pending_review" if submit_for_review else "draft"
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO marketing_content (
                    content_type, platform, audience, title, slug, draft_body,
                    status, keyword_cluster, generation_meta, created_by
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10)
                RETURNING *
                """,
                content_type,
                platform,
                audience,
                title,
                slug,
                draft_body,
                status,
                keyword_cluster,
                json.dumps(generation_meta or {}),
                created_by,
            )
            await self._audit(conn, row["id"], "create", created_by, {"status": status})
        item = dict(row)
        if status == "pending_review":
            await self.enqueue_ceo_review(item)
        return self._serialize(item)

    async def get(self, content_id: int) -> Optional[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM marketing_content WHERE id = $1", int(content_id)
            )
        return self._serialize(dict(row)) if row else None

    async def list(
        self,
        *,
        status: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses = ["TRUE"]
        args: List[Any] = []
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        if content_type:
            args.append(content_type)
            clauses.append(f"content_type = ${len(args)}")
        args.append(min(max(limit, 1), 200))
        sql = f"""
            SELECT * FROM marketing_content
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            LIMIT ${len(args)}
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [self._serialize(dict(r)) for r in rows]

    async def submit_for_review(
        self, content_id: int, *, actor: str = "system"
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE marketing_content
                SET status = 'pending_review', updated_at = NOW()
                WHERE id = $1 AND status IN ('draft', 'rejected')
                RETURNING *
                """,
                int(content_id),
            )
            if not row:
                raise ValueError("content not found or not submittable")
            await self._audit(conn, row["id"], "submit_review", actor, {})
        item = dict(row)
        await self.enqueue_ceo_review(item)
        return self._serialize(item)

    async def apply_ceo_decision(
        self,
        content_id: int,
        *,
        decision: str,
        actor: str = "ceo",
        note: str = "",
        scheduled_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        decision_u = (decision or "").strip().upper()
        if decision_u == "APPROVE":
            return await self.approve(
                content_id, actor=actor, scheduled_at=scheduled_at
            )
        if decision_u == "REJECT":
            return await self.reject(content_id, actor=actor, note=note)
        if decision_u == "REWRITE":
            return await self.request_rewrite(content_id, actor=actor, note=note)
        if decision_u == "DELAY":
            return await self.delay(content_id, actor=actor, scheduled_at=scheduled_at)
        if decision_u == "RETRACT":
            return await self.unpublish(content_id, actor=actor)
        raise ValueError(f"unsupported decision: {decision}")

    async def approve(
        self,
        content_id: int,
        *,
        actor: str = "ceo",
        scheduled_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        when = scheduled_at or datetime.now(timezone.utc)
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE marketing_content
                SET status = 'scheduled',
                    approved_by = $2,
                    approved_at = NOW(),
                    scheduled_at = $3,
                    updated_at = NOW()
                WHERE id = $1 AND status = 'pending_review'
                RETURNING *
                """,
                int(content_id),
                actor,
                when,
            )
            if not row:
                # Idempotent: already approved/scheduled
                existing = await conn.fetchrow(
                    "SELECT * FROM marketing_content WHERE id = $1", int(content_id)
                )
                if existing and existing["status"] in TERMINAL_OK:
                    return self._serialize(dict(existing))
                raise ValueError("content not pending_review")
            await self._audit(
                conn, row["id"], "approve", actor, {"scheduled_at": when.isoformat()}
            )
        item = self._serialize(dict(row))
        # Blog: attempt immediate publish when schedule is now/past
        if item.get("content_type") == "blog" and when <= datetime.now(timezone.utc):
            try:
                item = await self.publish(int(content_id), actor=actor)
            except Exception as e:
                logger.warning("auto-publish after approve failed: %s", e)
        return item

    async def reject(
        self, content_id: int, *, actor: str = "ceo", note: str = ""
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE marketing_content
                SET status = 'rejected', review_note = $2, updated_at = NOW()
                WHERE id = $1 AND status = 'pending_review'
                RETURNING *
                """,
                int(content_id),
                (note or "")[:2000],
            )
            if not row:
                raise ValueError("content not pending_review")
            await self._audit(conn, row["id"], "reject", actor, {"note": note[:500]})
        return self._serialize(dict(row))

    async def request_rewrite(
        self, content_id: int, *, actor: str = "ceo", note: str = ""
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            orig = await conn.fetchrow(
                "SELECT * FROM marketing_content WHERE id = $1", int(content_id)
            )
            if not orig:
                raise ValueError("content not found")
            await conn.execute(
                """
                UPDATE marketing_content
                SET status = 'superseded', review_note = $2, updated_at = NOW()
                WHERE id = $1
                """,
                int(content_id),
                (note or "REWRITE requested")[:2000],
            )
            row = await conn.fetchrow(
                """
                INSERT INTO marketing_content (
                    content_type, platform, audience, title, slug, draft_body,
                    status, keyword_cluster, revision_of, review_note,
                    generation_meta, created_by, prompt_version
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,'draft',$7,$8,$9,$10::jsonb,$11,$12
                ) RETURNING *
                """,
                orig["content_type"],
                orig["platform"],
                orig["audience"],
                orig["title"],
                None,  # new slug on resubmit
                orig["draft_body"],
                orig["keyword_cluster"],
                int(content_id),
                (note or "")[:2000],
                json.dumps(dict(orig.get("generation_meta") or {})),
                actor,
                orig.get("prompt_version"),
            )
            await self._audit(
                conn,
                row["id"],
                "rewrite",
                actor,
                {"revision_of": int(content_id), "note": note[:500]},
            )
        return self._serialize(dict(row))

    async def delay(
        self,
        content_id: int,
        *,
        actor: str = "ceo",
        scheduled_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not scheduled_at:
            raise ValueError("DELAY requires scheduled_at")
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE marketing_content
                SET status = 'pending_review',
                    scheduled_at = $2,
                    updated_at = NOW()
                WHERE id = $1 AND status IN ('pending_review', 'approved', 'scheduled')
                RETURNING *
                """,
                int(content_id),
                scheduled_at,
            )
            if not row:
                raise ValueError("content not delayable")
            await self._audit(
                conn,
                row["id"],
                "delay",
                actor,
                {"scheduled_at": scheduled_at.isoformat()},
            )
        return self._serialize(dict(row))

    async def publish(self, content_id: int, *, actor: str = "system") -> Dict[str, Any]:
        from app.services.growth.blog_publisher import (
            regenerate_sitemap,
            write_article_local,
        )

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM marketing_content WHERE id = $1", int(content_id)
            )
            if not row:
                raise ValueError("content not found")
            if row["content_type"] != "blog":
                # Non-blog: mark published without static write
                updated = await conn.fetchrow(
                    """
                    UPDATE marketing_content
                    SET status = 'published', published_at = NOW(), updated_at = NOW()
                    WHERE id = $1 AND status IN ('approved', 'scheduled')
                    RETURNING *
                    """,
                    int(content_id),
                )
                if not updated:
                    raise ValueError("not schedulable for publish")
                await self._audit(conn, content_id, "publish", actor, {})
                return self._serialize(dict(updated))

            result = write_article_local(
                title=row["title"],
                draft_body=row["draft_body"],
                slug=row["slug"],
            )
            regenerate_sitemap()
            updated = await conn.fetchrow(
                """
                UPDATE marketing_content
                SET status = 'published',
                    published_at = NOW(),
                    slug = $2,
                    html_body = $3,
                    public_path = $4,
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                int(content_id),
                result["slug"],
                result["html_body"],
                result["public_path"],
            )
            await self._audit(
                conn, content_id, "publish", actor, {"path": result["public_path"]}
            )
        return self._serialize(dict(updated))

    async def unpublish(
        self, content_id: int, *, actor: str = "ceo"
    ) -> Dict[str, Any]:
        from app.services.growth.blog_publisher import (
            regenerate_sitemap,
            unpublish_local,
        )

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM marketing_content WHERE id = $1", int(content_id)
            )
            if not row:
                raise ValueError("content not found")
            if row["slug"]:
                unpublish_local(row["slug"])
                regenerate_sitemap()
            updated = await conn.fetchrow(
                """
                UPDATE marketing_content
                SET status = 'unpublished', unpublished_at = NOW(), updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                int(content_id),
            )
            await self._audit(conn, content_id, "unpublish", actor, {})
            # Flag SkyEye children for takedown review
            try:
                await conn.execute(
                    """
                    UPDATE skyeye_content_queue
                    SET status = 'pending_review',
                        error_message = COALESCE(error_message, '') || ' [parent unpublished]'
                    WHERE parent_marketing_content_id = $1
                      AND status IN ('approved', 'scheduled', 'queued', 'pending')
                    """,
                    int(content_id),
                )
            except Exception as e:
                logger.warning("skyeye child flag on unpublish: %s", e)
        return self._serialize(dict(updated))

    async def enqueue_ceo_review(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Build brief + enqueue YELLOW CEO inbox item."""
        try:
            from app.services.growth.ceo_review_brief import build_growth_ceo_payload
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo
        except Exception as e:
            logger.warning("ceo enqueue imports failed: %s", e)
            return {"status": "error", "error": str(e)[:200]}

        content_id = int(item["id"])
        payload = await build_growth_ceo_payload(self.db_pool, item)
        title = f"Growth review: {item.get('content_type')} — {(item.get('title') or '')[:80]}"
        result = enqueue_ceo(
            risk=RISK_YELLOW,
            title=title,
            detail=(item.get("draft_body") or "")[:400],
            origin="growth",
            task_id=f"mc-{content_id}",
            payload=payload,
            dedup_ttl_s=1800,
        )
        return result

    async def spend_summary(self, *, month: Optional[str] = None) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            if month:
                rows = await conn.fetch(
                    """
                    SELECT category, SUM(amount_usd)::float AS total
                    FROM growth_spend_ledger
                    WHERE date_trunc('month', month) = date_trunc('month', $1::date)
                    GROUP BY category
                    """,
                    month,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT category, SUM(amount_usd)::float AS total
                    FROM growth_spend_ledger
                    WHERE date_trunc('month', month) = date_trunc('month', CURRENT_DATE)
                    GROUP BY category
                    """
                )
        by_cat = {r["category"]: r["total"] for r in rows}
        return {
            "month": month or "current",
            "by_category": by_cat,
            "total_usd": round(sum(by_cat.values()), 4),
        }

    async def get_growth_config(self) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM growth_config")
        out = {}
        for r in rows:
            val = r["value"]
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
            out[r["key"]] = val
        return out

    async def set_growth_config(
        self, key: str, value: Dict[str, Any], *, updated_by: str
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO growth_config (key, value, updated_by, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
                """,
                key,
                json.dumps(value),
                updated_by,
            )
        return {"key": key, "value": value, "updated_by": updated_by}

    async def _audit(
        self, conn, content_id: int, action: str, actor: str, detail: Dict[str, Any]
    ) -> None:
        try:
            await conn.execute(
                """
                INSERT INTO marketing_audit_log (content_id, action, actor, detail)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                int(content_id),
                action,
                actor,
                json.dumps(detail or {}),
            )
        except Exception as e:
            logger.warning("audit log failed: %s", e)

    @staticmethod
    def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for k, v in list(out.items()):
            if hasattr(v, "isoformat"):
                out[k] = v.isoformat()
            elif isinstance(v, (bytes, memoryview)):
                out[k] = bytes(v).decode("utf-8", errors="replace")
        for jk in ("generation_meta", "performance", "brand_checklist"):
            if isinstance(out.get(jk), str):
                try:
                    out[jk] = json.loads(out[jk])
                except Exception:
                    pass
        return out
