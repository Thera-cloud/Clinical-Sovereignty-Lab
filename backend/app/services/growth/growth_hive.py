"""Dual-COO hive for Adaptive Growth task kinds.

Mirrors newsletter_hive: daily enqueue + execute handlers for Queens.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.growth import growth_engine_enabled

logger = logging.getLogger("nate.growth.hive")

FACTORY_DIGEST_MIN = int(os.getenv("FACTORY_CEO_DIGEST_MIN", "3"))


def hive_enabled() -> bool:
    return growth_engine_enabled()


async def run_growth_hive_patrol(db_pool) -> Dict[str, Any]:
    if not hive_enabled() or not db_pool:
        return {"ok": False, "skipped": True}
    enqueued = enqueue_growth_tasks()
    try:
        from app.websocket.cli_task_bus import GROWTH_TASK_KINDS, task_bus_enabled
    except Exception:
        GROWTH_TASK_KINDS = frozenset()
        task_bus_enabled = lambda: False  # noqa: E731
    if task_bus_enabled() and enqueued.get("ok"):
        return {"ok": True, "enqueued": enqueued, "local": "deferred_to_cli"}
    results: List[Dict[str, Any]] = []
    for kind in sorted(GROWTH_TASK_KINDS):
        try:
            out = await execute_growth_kind(db_pool, kind)
            results.append({"kind": kind, **out})
        except Exception as e:
            logger.warning("growth hive kind %s failed: %s", kind, e)
            results.append({"kind": kind, "ok": False, "error": str(e)[:200]})
    return {"ok": True, "enqueued": enqueued, "results": results}


def enqueue_growth_tasks() -> Dict[str, Any]:
    """Publish each growth kind onto CLI bus once per UTC day (deduped)."""
    try:
        from app.websocket.cli_task_bus import (
            GROWTH_TASK_KINDS,
            publish_task,
            task_bus_enabled,
            _redis,
            _prefix,
            _env,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    if not task_bus_enabled():
        return {"ok": False, "skipped": "bus_off"}
    if not hive_enabled():
        return {"ok": False, "skipped": "growth_off"}
    c = _redis()
    if not c:
        return {"ok": False, "skipped": "redis"}
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    published = 0
    skipped = 0
    for kind in sorted(GROWTH_TASK_KINDS):
        dkey = f"{_prefix()}:{_env()}:growth:hive_enq:{day}:{kind}"
        try:
            if c.set(dkey, "1", nx=True, ex=22 * 3600) is None:
                skipped += 1
                continue
            r = publish_task(
                origin="cloud",
                kind=kind,
                notes=f"Growth hive patrol {day}",
                status="queued",
            )
            if r.get("status") == "ok":
                published += 1
            else:
                skipped += 1
                try:
                    c.delete(dkey)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("enqueue %s: %s", kind, e)
            skipped += 1
    return {"ok": True, "published": published, "skipped": skipped}


async def execute_growth_kind(db_pool, kind: str) -> Dict[str, Any]:
    return await _dispatch_kind(db_pool, kind)


async def _dispatch_kind(db_pool, kind: str) -> Dict[str, Any]:
    if kind == "growth_policy_cross_review":
        return await _policy_cross_review(db_pool)
    if kind == "growth_weekly_digest":
        return await _weekly_digest(db_pool)
    if kind == "growth_segment_propose":
        return await _segment_propose(db_pool)
    if kind == "growth_experiment_conclude":
        return await _experiment_conclude(db_pool)
    return {"ok": False, "error": "unknown_kind"}


async def _policy_cross_review(db_pool) -> Dict[str, Any]:
    """Surface YELLOW policies for peer+CEO GREEN activate (never auto-GREEN)."""
    from app.services.growth.authority_map import list_policies
    from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo, peer_queen_alive

    yellow = await list_policies(db_pool, stance="YELLOW")
    peer_ok = False
    try:
        from app.websocket.cli_dual_coo import cloud_sole_failover_active

        mac = peer_queen_alive("cloud")  # checks Mac beat
        # Solo cloud failover counts as peer gate satisfied (Mac offline)
        peer_ok = bool(mac.get("alive") or cloud_sole_failover_active())
    except Exception:
        try:
            peer_ok = bool(peer_queen_alive("cloud").get("alive"))
        except Exception:
            peer_ok = False
    if not yellow:
        return {"ok": True, "action": "noop", "yellow": 0, "peer_alive": peer_ok}
    routed = 0
    for p in yellow[:5]:
        key = p.get("policy_key") or ""
        body_preview = (p.get("body") or "")[:400]
        enqueue_ceo(
            risk=RISK_YELLOW,
            title=f"Growth policy activate: {key}",
            detail=f"YELLOW policy awaiting GREEN. Peer Queen alive={peer_ok}.\n{body_preview}",
            origin="growth",
            task_id=f"gpol-{key}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            payload={
                "kind": "growth_policy_activate",
                "policy_key": key,
                "peer_pass": peer_ok,
                "ceo_summary": f"Activate marketing policy {key} to GREEN?",
                "what_happened": (
                    f"Policy `{key}` is YELLOW. Peer Queen alive={peer_ok}. "
                    "Factory/outreach only consume GREEN bodies."
                ),
                "ask_of_ceo": "Reply APPROVE to set stance=GREEN (requires peer_pass=true).",
                "apply": {"action": "activate_green", "policy_key": key},
            },
            dedup_ttl_s=20 * 3600,
        )
        routed += 1
    return {"ok": True, "action": "ceo_routed", "count": routed, "peer_alive": peer_ok}


async def _weekly_digest(db_pool) -> Dict[str, Any]:
    """Resurface pending_review >7d + spend/themes/BWAS summary (no auto-approve)."""
    from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

    stale: List[Dict[str, Any]] = []
    themes: List[str] = []
    spend_total = 0.0
    bwas_top: List[str] = []
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content_type, title, created_at
            FROM marketing_content
            WHERE status = 'pending_review'
              AND created_at < NOW() - INTERVAL '7 days'
            ORDER BY created_at ASC
            LIMIT 40
            """
        )
        for r in rows:
            stale.append(
                {
                    "id": r["id"],
                    "content_type": r["content_type"],
                    "title": (r["title"] or "")[:120],
                }
            )
        try:
            trows = await conn.fetch(
                """
                SELECT theme, SUM(count_bucket)::int AS total
                FROM try_theme_weekly
                WHERE week_bucket >= CURRENT_DATE - 28
                  AND theme <> 'ops_only'
                GROUP BY theme ORDER BY total DESC LIMIT 8
                """
            )
            themes = [f"{r['theme']}={r['total']}" for r in trows]
        except Exception:
            pass
        try:
            srow = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(amount_usd),0)::float AS total
                FROM growth_spend_ledger
                WHERE date_trunc('month', month) = date_trunc('month', CURRENT_DATE)
                """
            )
            spend_total = float((srow or {}).get("total") or 0)
        except Exception:
            pass
        try:
            brows = await conn.fetch(
                """
                SELECT content_kind, SUM(score)::float AS s
                FROM bwas_weekly
                WHERE week_bucket >= CURRENT_DATE - 28
                GROUP BY content_kind ORDER BY s DESC NULLS LAST LIMIT 5
                """
            )
            bwas_top = [f"{r['content_kind']}={round(r['s'] or 0, 2)}" for r in brows]
        except Exception:
            pass

    lines = [
        f"Stale pending_review (>7d): {len(stale)}",
        f"Month spend (source=growth_spend_ledger): ${spend_total:.2f}",
        f"try themes (source=try_theme_weekly): {', '.join(themes) or '—'}",
        f"BWAS top (source=bwas_weekly): {', '.join(bwas_top) or '—'}",
        "",
        "Stale items (open dashboard; reply APPROVE/REJECT per content email or ACK this digest):",
    ]
    if not stale:
        return {
            "ok": True,
            "stale": 0,
            "refreshed": 0,
            "spend_usd": spend_total,
            "action": "noop_no_stale",
        }
    for s in stale[:25]:
        lines.append(f"  #{s['id']} [{s['content_type']}] {s['title']}")
    detail = "\n".join(lines)
    enqueue_ceo(
        risk=RISK_YELLOW,
        title=f"Growth weekly digest — {len(stale)} stale reviews",
        detail=detail[:1800],
        origin="growth",
        task_id="growth_weekly_digest",
        payload={
            "kind": "growth_weekly_digest",
            "stale_ids": [s["id"] for s in stale],
            "ceo_summary": "Weekly growth digest (ACK dismisses; no auto-publish).",
            "what_happened": detail[:1500],
            "ask_of_ceo": "ACK/DISMISS clears inbox only. Approve each content via its own review email or dashboard.",
            "metrics": {
                "stale_count": {"value": len(stale), "source": "measured"},
                "spend_usd": {"value": spend_total, "source": "growth_spend_ledger"},
            },
        },
        dedup_ttl_s=20 * 3600,
    )
    # Re-fire per-content CEO notify for stale items (fresh tokens)
    refreshed = 0
    if stale:
        from app.services.growth.marketing_content_service import MarketingContentService

        svc = MarketingContentService(db_pool)
        for s in stale[:15]:
            try:
                item = await svc.get(int(s["id"]))
                if item:
                    await svc.enqueue_ceo_review(item)
                    refreshed += 1
            except Exception as e:
                logger.warning("stale re-notify %s: %s", s["id"], e)
    return {
        "ok": True,
        "stale": len(stale),
        "refreshed": refreshed,
        "spend_usd": spend_total,
    }


async def _segment_propose(db_pool) -> Dict[str, Any]:
    """Propose ICP/theme segment into growth_config as YELLOW draft via CEO."""
    from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

    buckets: List[str] = []
    async with db_pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT specialty, COUNT(*)::int AS n
                FROM buyer_leads
                WHERE specialty IS NOT NULL AND specialty <> ''
                GROUP BY specialty ORDER BY n DESC LIMIT 8
                """
            )
            buckets = [f"{r['specialty']} n={r['n']}" for r in rows]
        except Exception:
            pass
        try:
            trows = await conn.fetch(
                """
                SELECT theme, SUM(count_bucket)::int AS total
                FROM try_theme_weekly
                WHERE week_bucket >= CURRENT_DATE - 28 AND theme <> 'ops_only'
                GROUP BY theme ORDER BY total DESC LIMIT 5
                """
            )
            for r in trows:
                buckets.append(f"theme:{r['theme']}={r['total']}")
        except Exception:
            pass
    if not buckets:
        return {"ok": True, "action": "noop"}
    proposal = {
        "segments": buckets[:12],
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "status": "yellow_draft",
    }
    enqueue_ceo(
        risk=RISK_YELLOW,
        title="Growth segment propose",
        detail="Proposed segments (ICP + try themes):\n" + "\n".join(buckets[:12]),
        origin="growth",
        task_id="growth_segment_propose",
        payload={
            "kind": "growth_segment_propose",
            "proposal": proposal,
            "ceo_summary": "Approve to store segment proposal in growth_config.",
            "ask_of_ceo": "Reply APPROVE to save YELLOW segment draft; REJECT to discard.",
            "apply": {"action": "store_segment_draft"},
        },
        dedup_ttl_s=20 * 3600,
    )
    return {"ok": True, "action": "ceo_routed", "buckets": len(buckets)}


async def _experiment_conclude(db_pool) -> Dict[str, Any]:
    """GREEN: conclude A/B tests meeting min_sample; set verdict (no auto-winner)."""
    concluded = 0
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, test_name, status,
                   COALESCE(min_sample, 50) AS min_sample,
                   hypothesis,
                   COALESCE(variant_a_impressions,0)
                     + COALESCE(variant_b_impressions,0) AS impressions
            FROM content_ab_tests
            WHERE status = 'running'
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        for r in rows:
            min_s = int(r["min_sample"] or 50)
            sample = int(r["impressions"] or 0)
            if sample < min_s:
                try:
                    sample = int(
                        await conn.fetchval(
                            """
                            SELECT COUNT(*)::int FROM growth_attribution_links
                            WHERE utm_campaign = $1
                            """,
                            f"ab-{r['id']}",
                        )
                        or 0
                    )
                except Exception:
                    pass
            if sample < min_s:
                continue
            await conn.execute(
                """
                UPDATE content_ab_tests
                SET verdict = $2,
                    status = 'completed',
                    winner = COALESCE(winner, 'inconclusive'),
                    completed_at = NOW()
                WHERE id = $1 AND status = 'running'
                """,
                r["id"],
                f"sample_met n={sample} (winner TBD — CEO/dashboard)",
            )
            concluded += 1
    return {"ok": True, "concluded": concluded}


async def enqueue_factory_digest(
    db_pool, items: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """One CEO email for a factory batch of blog drafts (never outreach/directory)."""
    if len(items) < FACTORY_DIGEST_MIN:
        return None
    from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

    lines = []
    ids = []
    for it in items:
        cid = int(it.get("id") or it.get("content_id") or 0)
        if not cid:
            continue
        ids.append(cid)
        lines.append(f"#{cid} {(it.get('title') or '')[:100]}")
    if not ids:
        return None
    detail = (
        f"Factory batch: {len(ids)} blog drafts pending review.\n"
        + "\n".join(lines[:30])
        + "\n\nOpen marketing_engine.html Themes/Queue. "
        "Reply APPROVE_ALL only applies to these blog IDs (not outreach/directory)."
    )
    return enqueue_ceo(
        risk=RISK_YELLOW,
        title=f"Growth factory digest — {len(ids)} drafts",
        detail=detail[:1800],
        origin="growth",
        task_id=f"gfact-{ids[0]}-{len(ids)}",
        payload={
            "kind": "growth_factory_digest",
            "content_ids": ids,
            "ceo_summary": f"Review {len(ids)} factory blog drafts.",
            "ask_of_ceo": "APPROVE_ALL schedules all listed blogs; or open each in dashboard.",
            "apply": {"action": "approve_all", "content_ids": ids},
        },
        dedup_ttl_s=3600,
    )
