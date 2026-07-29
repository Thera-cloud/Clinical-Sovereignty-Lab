"""buyer_leads CRUD, ICP scoring, enrichment, GDPR erasure.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.services.growth.enrichment import enrich_lead
from app.services.growth.icp_score import score_lead

logger = logging.getLogger("nate.growth.buyer_leads")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class BuyerLeadsService:
    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def _icp_config(self, conn) -> Dict[str, Any]:
        rows = await conn.fetch(
            "SELECT key, value FROM growth_config WHERE key LIKE 'icp_%'"
        )
        cfg: Dict[str, Any] = {}
        for r in rows:
            cfg[r["key"]] = r["value"]
        return cfg

    async def is_suppressed(self, email_norm: str) -> bool:
        async with self.db_pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    "SELECT 1 FROM outreach_suppression WHERE email_norm = $1",
                    email_norm,
                )
            )

    async def upsert_lead(
        self,
        *,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company: Optional[str] = None,
        title: Optional[str] = None,
        npi: Optional[str] = None,
        specialty: Optional[str] = None,
        state: Optional[str] = None,
        source: str = "manual",
        run_enrichment: bool = False,
    ) -> Dict[str, Any]:
        email_norm = normalize_email(email)
        if not _EMAIL_RE.match(email_norm):
            raise ValueError("invalid email")
        if await self.is_suppressed(email_norm):
            raise ValueError("email_suppressed")

        async with self.db_pool.acquire() as conn:
            cfg = await self._icp_config(conn)
            weights = cfg.get("icp_weights") if isinstance(cfg.get("icp_weights"), dict) else None
            titles = cfg.get("icp_title_keywords")
            specs = cfg.get("icp_specialty_keywords")
            if isinstance(titles, str):
                titles = json.loads(titles)
            if isinstance(specs, str):
                specs = json.loads(specs)
            score = score_lead(
                title=title or "",
                specialty=specialty or "",
                state=state or "",
                npi=npi or "",
                weights=weights,
                title_keywords=list(titles) if isinstance(titles, list) else None,
                specialty_keywords=list(specs) if isinstance(specs, list) else None,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO buyer_leads (
                    email, email_norm, first_name, last_name, company, title,
                    npi, specialty, state, source, icp_score, status
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'new')
                ON CONFLICT (email_norm) DO UPDATE SET
                    first_name = COALESCE(EXCLUDED.first_name, buyer_leads.first_name),
                    last_name = COALESCE(EXCLUDED.last_name, buyer_leads.last_name),
                    company = COALESCE(EXCLUDED.company, buyer_leads.company),
                    title = COALESCE(EXCLUDED.title, buyer_leads.title),
                    npi = COALESCE(EXCLUDED.npi, buyer_leads.npi),
                    specialty = COALESCE(EXCLUDED.specialty, buyer_leads.specialty),
                    state = COALESCE(EXCLUDED.state, buyer_leads.state),
                    source = EXCLUDED.source,
                    icp_score = EXCLUDED.icp_score,
                    status = CASE
                        WHEN buyer_leads.status IN ('erased', 'suppressed') THEN buyer_leads.status
                        ELSE 'new'
                    END,
                    updated_at = NOW()
                RETURNING *
                """,
                email.strip(),
                email_norm,
                first_name,
                last_name,
                company,
                title,
                npi,
                specialty,
                state,
                source,
                score,
            )
        item = self._serialize(dict(row))
        if run_enrichment and item.get("status") not in ("erased", "suppressed"):
            item = await self.enrich(int(item["id"]))
        return item

    async def ingest_npi_batch(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        ok = 0
        errors: List[Dict[str, Any]] = []
        for i, r in enumerate(rows[:500]):
            try:
                await self.upsert_lead(
                    email=str(r.get("email") or ""),
                    first_name=r.get("first_name"),
                    last_name=r.get("last_name"),
                    company=r.get("company"),
                    title=r.get("title"),
                    npi=str(r.get("npi") or "") or None,
                    specialty=r.get("specialty"),
                    state=r.get("state"),
                    source="npi_ingest",
                    run_enrichment=False,
                )
                ok += 1
            except Exception as e:
                errors.append({"index": i, "error": str(e)[:200]})
        return {"ok": ok, "errors": errors[:50], "error_count": len(errors)}

    async def enrich(self, lead_id: int) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM buyer_leads WHERE id = $1", int(lead_id)
            )
            if not row:
                raise ValueError("lead not found")
            if row["status"] in ("erased", "suppressed"):
                raise ValueError("lead not enrichable")
            result = await enrich_lead(dict(row))
            for run in result["runs"]:
                await conn.execute(
                    """
                    INSERT INTO enrichment_runs (lead_id, vendor, status, cost_usd, detail)
                    VALUES ($1,$2,$3,$4,$5::jsonb)
                    """,
                    int(lead_id),
                    run["vendor"],
                    run["status"],
                    float(run.get("cost_usd") or 0),
                    json.dumps(run.get("detail") or {}),
                )
                cost = float(run.get("cost_usd") or 0)
                if cost > 0:
                    await conn.execute(
                        """
                        INSERT INTO growth_spend_ledger (month, category, amount_usd, detail)
                        VALUES ($1::date, 'enrichment', $2, $3::jsonb)
                        """,
                        date.today().replace(day=1),
                        cost,
                        json.dumps({"lead_id": lead_id, "vendor": run["vendor"]}),
                    )
            updated = await conn.fetchrow(
                """
                UPDATE buyer_leads
                SET enrichment = $2::jsonb,
                    status = CASE WHEN status = 'new' THEN 'enriched' ELSE status END,
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                int(lead_id),
                json.dumps(result["enrichment"]),
            )
        return self._serialize(dict(updated))

    async def list(
        self, *, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        clauses = ["TRUE"]
        args: List[Any] = []
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        args.append(min(max(limit, 1), 200))
        sql = f"""
            SELECT * FROM buyer_leads
            WHERE {' AND '.join(clauses)}
            ORDER BY icp_score DESC, updated_at DESC
            LIMIT ${len(args)}
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [self._serialize(dict(r)) for r in rows]

    async def ready_leads(self, *, limit: int = 50, min_score: float = 0.3) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT b.* FROM buyer_leads b
                WHERE b.status IN ('new', 'enriched', 'ready')
                  AND b.icp_score >= $1
                  AND NOT EXISTS (
                      SELECT 1 FROM outreach_suppression s
                      WHERE s.email_norm = b.email_norm
                  )
                ORDER BY b.icp_score DESC
                LIMIT $2
                """,
                float(min_score),
                min(max(limit, 1), 200),
            )
        return [self._serialize(dict(r)) for r in rows]

    async def gdpr_erase(self, email: str, *, actor: str = "admin") -> Dict[str, Any]:
        email_norm = normalize_email(email)
        if not email_norm:
            raise ValueError("email required")
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO outreach_suppression (email_norm, reason, source, permanent)
                VALUES ($1, 'gdpr_erasure', $2, TRUE)
                ON CONFLICT (email_norm) DO UPDATE SET
                    reason = 'gdpr_erasure',
                    permanent = TRUE,
                    source = EXCLUDED.source
                """,
                email_norm,
                actor,
            )
            row = await conn.fetchrow(
                """
                UPDATE buyer_leads
                SET email = 'erased+' || id::text || '@invalid.local',
                    email_norm = 'erased+' || id::text || '@invalid.local',
                    first_name = NULL,
                    last_name = NULL,
                    company = NULL,
                    title = NULL,
                    npi = NULL,
                    specialty = NULL,
                    state = NULL,
                    enrichment = '{}'::jsonb,
                    instantly_lead_id = NULL,
                    status = 'erased',
                    updated_at = NOW()
                WHERE email_norm = $1
                RETURNING id
                """,
                email_norm,
            )
            await conn.execute(
                """
                UPDATE landing_captures
                SET email_norm = 'erased@invalid.local',
                    name = NULL,
                    org = NULL,
                    meta = jsonb_build_object('erased', true)
                WHERE email_norm = $1
                """,
                email_norm,
            )
        return {
            "status": "erased",
            "email_norm": email_norm,
            "lead_id": int(row["id"]) if row else None,
            "suppressed": True,
        }

    async def enqueue_reply(
        self, *, email: str, body: str, lead_id: Optional[int] = None
    ) -> Dict[str, Any]:
        from app.services.growth.reply_classifier import classify_reply

        email_norm = normalize_email(email)
        cls = classify_reply(body)
        async with self.db_pool.acquire() as conn:
            if cls["classification"] == "unsubscribe":
                await conn.execute(
                    """
                    INSERT INTO outreach_suppression (email_norm, reason, source, permanent)
                    VALUES ($1, 'unsubscribe_reply', 'reply_classifier', TRUE)
                    ON CONFLICT (email_norm) DO NOTHING
                    """,
                    email_norm,
                )
                if lead_id:
                    await conn.execute(
                        "UPDATE buyer_leads SET status = 'suppressed', updated_at = NOW() WHERE id = $1",
                        int(lead_id),
                    )
            row = await conn.fetchrow(
                """
                INSERT INTO outreach_reply_queue (
                    lead_id, email_norm, body, classification, status, meta
                ) VALUES ($1,$2,$3,$4,'pending',$5::jsonb)
                RETURNING *
                """,
                lead_id,
                email_norm,
                (body or "")[:8000],
                cls["classification"],
                json.dumps({"reason": cls.get("reason")}),
            )
        return self._serialize(dict(row))

    async def list_replies(
        self, *, status: str = "pending", limit: int = 50
    ) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM outreach_reply_queue
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                status,
                min(max(limit, 1), 200),
            )
        return [self._serialize(dict(r)) for r in rows]

    @staticmethod
    def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for k, v in list(out.items()):
            if isinstance(v, Decimal):
                out[k] = float(v)
            elif hasattr(v, "isoformat"):
                out[k] = v.isoformat()
        return out
