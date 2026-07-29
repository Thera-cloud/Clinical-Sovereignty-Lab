"""CEO email brief for growth_content_review — proofs, reasoning, real-only metrics.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.growth.ceo_brief")

COHORT_MIN_N = 5


async def build_growth_ceo_payload(db_pool, item: Dict[str, Any]) -> Dict[str, Any]:
    content_id = int(item["id"])
    from app.services.growth.preview_links import (
        build_dashboard_deep_link,
        build_preview_url,
    )

    preview = (item.get("draft_body") or "")[:400]
    proof_url = build_preview_url(content_id)
    dash_url = build_dashboard_deep_link(content_id)
    metrics = await fetch_real_metrics(db_pool, item)
    reasoning = await build_reasoning_block(db_pool, item)

    metrics_lines = format_metrics_lines(metrics)
    what_happened = (
        f"{item.get('content_type')} draft ready for review.\n"
        f"Title: {item.get('title')}\n"
        f"Audience: {item.get('audience')} | Platform: {item.get('platform')}\n\n"
        f"Preview (first 400 chars):\n{preview}\n\n"
        f"Proof (signed, 72h): {proof_url}\n"
        f"Dashboard: {dash_url}"
    )
    why = (
        "Reasoning (DB inputs only):\n"
        + reasoning
        + "\n\nMetrics (real-only; never model forecasts):\n"
        + "\n".join(metrics_lines)
    )
    ask = (
        "Reply APPROVE to schedule/publish, REJECT to decline, "
        "REWRITE <note> for a revision draft, DELAY +3d (or ISO date) to reschedule, "
        "ACK to dismiss inbox only."
    )
    return {
        "kind": "growth_content_review",
        "content_id": content_id,
        "ceo_summary": f"Review growth {item.get('content_type')}: {(item.get('title') or '')[:100]}",
        "what_happened": what_happened,
        "why_it_matters": why,
        "ask_of_ceo": ask,
        "action_steps": [
            ask,
            "Open the signed proof URL to read the full draft.",
            "APPROVE applies schedule (blog may publish immediately).",
        ],
        "what_it_should_do": [
            "Let you approve/reject/rewrite growth content from email like Dual-COO items.",
            "Show content proof + DB reasoning + measured/cohort metrics only.",
        ],
        "what_it_should_not_be": [
            "Not an LLM-invented performance forecast.",
            "Not auto-publish without your APPROVE.",
        ],
        "bottom_line": "APPROVE schedules; REJECT declines; REWRITE creates a revision draft.",
        "expected_impact": "On APPROVE: content → scheduled (blog may publish). On REJECT: rejected.",
        "proof_url": proof_url,
        "dashboard_url": dash_url,
        "metrics": metrics,
        "apply": {"action": "schedule", "content_id": content_id},
    }


async def build_reasoning_block(db_pool, item: Dict[str, Any]) -> str:
    lines: List[str] = []
    meta = item.get("generation_meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if item.get("keyword_cluster"):
        lines.append(f"keyword_cluster={item['keyword_cluster']}")
    if item.get("prompt_version"):
        lines.append(f"prompt_version={item['prompt_version']}")
    if meta.get("model"):
        lines.append(f"model={meta['model']}")
    if meta.get("cost_usd") is not None:
        lines.append(f"cost_usd={meta['cost_usd']} (recorded)")
    # Priority formula inputs if stored
    pri = meta.get("priority_inputs") if isinstance(meta.get("priority_inputs"), dict) else {}
    for k in ("volume_norm", "intent", "audience_value", "buyer_prior", "demand_prior"):
        if k in pri:
            lines.append(f"priority.{k}={pri[k]} (source=db)")
    # Brand checklist
    checklist = item.get("brand_checklist") or {}
    if isinstance(checklist, str):
        try:
            checklist = json.loads(checklist)
        except Exception:
            checklist = {}
    if checklist:
        fails = [k for k, v in checklist.items() if v in (False, "fail", "FAIL")]
        lines.append(
            f"brand_checklist={'PASS' if not fails else 'FAIL:' + ','.join(fails)}"
        )
    if item.get("review_note"):
        lines.append(f"prior_review_note={str(item['review_note'])[:200]}")
    # try theme counts (aggregate only)
    try:
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'try_theme_weekly'
                )
                """
            )
            if exists:
                rows = await conn.fetch(
                    """
                    SELECT theme, SUM(count_bucket)::int AS c
                    FROM try_theme_weekly
                    WHERE week_bucket >= date_trunc('week', NOW() - INTERVAL '28 days')
                    GROUP BY theme ORDER BY c DESC LIMIT 5
                    """
                )
                if rows:
                    lines.append(
                        "try_theme_weekly_top28d="
                        + ", ".join(f"{r['theme']}:{r['c']}" for r in rows)
                        + " (source=try_theme_weekly)"
                    )
    except Exception as e:
        logger.debug("try_theme reasoning skip: %s", e)
    return "\n".join(lines) if lines else "No stored priority/theme inputs yet (source=unavailable)."


async def fetch_real_metrics(db_pool, item: Dict[str, Any]) -> Dict[str, Any]:
    """Measured if published; else cohort median 28d with n≥5; else insufficient_history."""
    out: Dict[str, Any] = {
        "measured": {"source": "unavailable", "value": None},
        "cohort_median_28d": {"source": "unavailable", "value": None, "n": 0},
        "funnel_demand": {"source": "unavailable", "value": None},
    }
    perf = item.get("performance") or {}
    if isinstance(perf, str):
        try:
            perf = json.loads(perf)
        except Exception:
            perf = {}
    status = item.get("status")
    if status == "published" and perf:
        out["measured"] = {
            "source": "measured",
            "value": {
                "impressions": perf.get("impressions"),
                "clicks": perf.get("clicks"),
                "captures": perf.get("captures"),
                "bwas": perf.get("bwas"),
            },
        }
    # Cohort baseline
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT performance
                FROM marketing_content
                WHERE content_type = $1
                  AND platform = $2
                  AND audience = $3
                  AND status = 'published'
                  AND published_at >= NOW() - INTERVAL '28 days'
                  AND id <> $4
                """,
                item.get("content_type"),
                item.get("platform"),
                item.get("audience"),
                int(item["id"]),
            )
        n = len(rows)
        if n < COHORT_MIN_N:
            out["cohort_median_28d"] = {
                "source": "insufficient_history",
                "value": None,
                "n": n,
            }
        else:
            clicks = []
            imps = []
            for r in rows:
                p = r["performance"] or {}
                if isinstance(p, str):
                    try:
                        p = json.loads(p)
                    except Exception:
                        p = {}
                if p.get("clicks") is not None:
                    clicks.append(float(p["clicks"]))
                if p.get("impressions") is not None:
                    imps.append(float(p["impressions"]))
            out["cohort_median_28d"] = {
                "source": "cohort_median_28d",
                "n": n,
                "value": {
                    "clicks": _median(clicks),
                    "impressions": _median(imps),
                },
            }
    except Exception as e:
        logger.debug("cohort metrics skip: %s", e)
        out["cohort_median_28d"] = {
            "source": "unavailable",
            "value": None,
            "n": 0,
            "error": str(e)[:120],
        }
    return out


def format_metrics_lines(metrics: Dict[str, Any]) -> List[str]:
    lines = []
    m = metrics.get("measured") or {}
    if m.get("source") == "measured" and m.get("value"):
        v = m["value"]
        lines.append(
            f"Measured: impressions={v.get('impressions')} clicks={v.get('clicks')} "
            f"captures={v.get('captures')} bwas={v.get('bwas')} (source=measured)"
        )
    else:
        lines.append("Measured: — (source=unavailable)")

    c = metrics.get("cohort_median_28d") or {}
    if c.get("source") == "cohort_median_28d" and c.get("value"):
        v = c["value"]
        lines.append(
            f"Cohort baseline 28d: median_clicks={v.get('clicks')} "
            f"median_impressions={v.get('impressions')} "
            f"(source=cohort_median_28d n={c.get('n')})"
        )
    elif c.get("source") == "insufficient_history":
        lines.append(
            f"Cohort baseline 28d: insufficient_history (source=insufficient_history n={c.get('n', 0)})"
        )
    else:
        lines.append("Cohort baseline 28d: — (source=unavailable)")
    return lines


def _median(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0
