"""Push approved outreach marketing_content → Instantly (+ spend + caps).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.growth import outreach_engine_enabled
from app.services.growth.buyer_leads import BuyerLeadsService
from app.services.growth.instantly_client import InstantlyClient
from app.services.growth.sender_guard import validate_outreach_sender_domains

logger = logging.getLogger("nate.growth.outreach_pub")


async def _get_json_config(conn, key: str, default: Dict[str, Any]) -> Dict[str, Any]:
    row = await conn.fetchrow("SELECT value FROM growth_config WHERE key = $1", key)
    if not row:
        return dict(default)
    val = row["value"]
    return dict(val) if isinstance(val, dict) else dict(default)


async def _circuit_tripped(conn) -> bool:
    cfg = await _get_json_config(
        conn,
        "outreach_circuit_breaker",
        {"fail_threshold": 3, "cooldown_minutes": 60},
    )
    threshold = int(cfg.get("fail_threshold") or 3)
    cooldown = int(cfg.get("cooldown_minutes") or 60)
    fails = await conn.fetchval(
        """
        SELECT COUNT(*) FROM marketing_audit_log
        WHERE action = 'outreach_push_fail'
          AND created_at > NOW() - ($1::text || ' minutes')::interval
        """,
        str(cooldown),
    )
    return int(fails or 0) >= threshold


async def _daily_counts(conn) -> Dict[str, int]:
    leads = await conn.fetchval(
        """
        SELECT COUNT(*) FROM buyer_leads
        WHERE status = 'sent' AND updated_at::date = CURRENT_DATE
        """
    )
    campaigns = await conn.fetchval(
        """
        SELECT COUNT(*) FROM marketing_audit_log
        WHERE action = 'outreach_push_ok'
          AND created_at::date = CURRENT_DATE
        """
    )
    return {"leads": int(leads or 0), "campaigns": int(campaigns or 0)}


def _sequence_from_body(title: str, draft_body: str) -> List[Dict[str, Any]]:
    """Split draft on --- into Instantly email steps (subject from title/first line)."""
    parts = [p.strip() for p in (draft_body or "").split("\n---\n") if p.strip()]
    if not parts:
        parts = [(draft_body or "Hello {{firstName}},").strip()]
    steps: List[Dict[str, Any]] = []
    for i, part in enumerate(parts[:5]):
        subject = title if i == 0 else f"Re: {title}"
        first = part.split("\n", 1)[0]
        if first.lower().startswith("subject:"):
            subject = first.split(":", 1)[1].strip() or subject
            part = part.split("\n", 1)[1] if "\n" in part else ""
        steps.append(
            {
                "type": "email",
                "delay": 0 if i == 0 else 2,
                "variants": [
                    {
                        "subject": subject[:200],
                        "body": part[:8000],
                    }
                ],
            }
        )
    return steps


async def push_outreach_sequence(
    db_pool,
    content_row: Dict[str, Any],
    *,
    actor: str = "system",
    lead_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Create Instantly campaign from outreach content + attach ready leads."""
    if not outreach_engine_enabled():
        return {"ok": False, "error": "ENABLE_OUTREACH_ENGINE=false", "degraded": True}

    ok_sender, sender_msg = validate_outreach_sender_domains()
    if not ok_sender:
        return {"ok": False, "error": sender_msg, "degraded": True}

    client = InstantlyClient()
    if not client.configured:
        return {
            "ok": False,
            "error": "INSTANTLY_API_KEY missing — outreach degraded",
            "degraded": True,
        }

    health = await client.health()
    if not health.get("ok"):
        return {
            "ok": False,
            "error": f"instantly_unhealthy:{health.get('status')}",
            "degraded": True,
            "health": health,
        }

    content_id = int(content_row["id"])
    title = content_row.get("title") or f"Outreach {content_id}"
    body = content_row.get("draft_body") or ""

    async with db_pool.acquire() as conn:
        if await _circuit_tripped(conn):
            return {"ok": False, "error": "circuit_breaker_open", "degraded": True}
        caps = await _get_json_config(
            conn, "outreach_daily_cap", {"max_leads": 50, "max_campaigns": 3}
        )
        counts = await _daily_counts(conn)
        if counts["campaigns"] >= int(caps.get("max_campaigns") or 3):
            return {"ok": False, "error": "daily_campaign_cap", "counts": counts}

    steps = _sequence_from_body(title, body)
    created = await client.create_campaign(
        name=f"SS-{content_id}-{title}"[:100],
        sequence_steps=steps,
        daily_limit=min(30, int(caps.get("max_leads") or 50)),
    )
    if not created.get("ok"):
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO marketing_audit_log (content_id, action, actor, detail)
                VALUES ($1, 'outreach_push_fail', $2, $3::jsonb)
                """,
                content_id,
                actor,
                json.dumps({"error": created.get("error"), "stage": "create_campaign"}),
            )
        return {"ok": False, "error": created.get("error"), "degraded": True}

    data = created.get("data") or {}
    campaign_id = data.get("id") or data.get("campaign_id")
    if not campaign_id:
        return {"ok": False, "error": "no_campaign_id_in_response", "raw": data}

    leads_svc = BuyerLeadsService(db_pool)
    remaining = int(caps.get("max_leads") or 50) - counts["leads"]
    take = min(remaining, lead_limit or 25)
    if take <= 0:
        return {"ok": False, "error": "daily_lead_cap", "counts": counts}

    leads = await leads_svc.ready_leads(limit=take)
    attached = 0
    errors: List[str] = []
    for lead in leads:
        # Optional verify — non-fatal
        try:
            await client.verify_email(lead["email"])
        except Exception:
            pass
        add = await client.add_lead(
            email=lead["email"],
            campaign_id=str(campaign_id),
            first_name=lead.get("first_name"),
            last_name=lead.get("last_name"),
            company_name=lead.get("company"),
            personalization=(body[:400] if body else None),
        )
        async with db_pool.acquire() as conn:
            if add.get("ok"):
                lead_data = add.get("data") or {}
                await conn.execute(
                    """
                    UPDATE buyer_leads
                    SET status = 'sent',
                        instantly_lead_id = $2,
                        campaign_content_id = $3,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    int(lead["id"]),
                    str(lead_data.get("id") or lead_data.get("lead_id") or ""),
                    content_id,
                )
                attached += 1
            else:
                errors.append(str(add.get("error") or "add_failed")[:120])
                await conn.execute(
                    """
                    UPDATE buyer_leads
                    SET status = 'error', last_error = $2, updated_at = NOW()
                    WHERE id = $1
                    """,
                    int(lead["id"]),
                    str(add.get("error") or "add_failed")[:500],
                )

    activate = await client.activate_campaign(str(campaign_id))
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO growth_spend_ledger (month, category, amount_usd, detail)
            VALUES ($1::date, 'instantly', 0, $2::jsonb)
            """,
            date.today().replace(day=1),
            json.dumps(
                {
                    "content_id": content_id,
                    "campaign_id": campaign_id,
                    "leads_attached": attached,
                    "note": "usage tracked; dollar amount filled when Instantly invoice synced",
                }
            ),
        )
        await conn.execute(
            """
            INSERT INTO marketing_audit_log (content_id, action, actor, detail)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            content_id,
            "outreach_push_ok" if attached or activate.get("ok") else "outreach_push_fail",
            actor,
            json.dumps(
                {
                    "campaign_id": campaign_id,
                    "attached": attached,
                    "activate": activate.get("ok"),
                    "errors": errors[:10],
                }
            ),
        )
        meta = dict(content_row.get("generation_meta") or {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        meta["instantly_campaign_id"] = campaign_id
        meta["leads_attached"] = attached
        await conn.execute(
            """
            UPDATE marketing_content
            SET generation_meta = $2::jsonb, updated_at = NOW()
            WHERE id = $1
            """,
            content_id,
            json.dumps(meta),
        )

    return {
        "ok": True,
        "campaign_id": campaign_id,
        "leads_attached": attached,
        "activate_ok": bool(activate.get("ok")),
        "errors": errors[:10],
    }
