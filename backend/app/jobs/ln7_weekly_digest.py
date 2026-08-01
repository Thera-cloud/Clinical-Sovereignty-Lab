"""Weekly LN7 flywheel digest (E6) — report only, no CEO inbox item.

Summarizes the trailing 7 days across the outcome_envelope ledger: event
counts by loop_name/event_kind, confounded rate (E5), envelope signature
presence (E4), cross-loop attribution coverage (E2), active reverse-suppress
patterns (E8), and flywheel_anomaly counts by kind (E7). Sent once per ISO
week via notification_system._send_email if available, else logged only.
This function never writes to ceo_inbox and never blocks a promote/gate
decision — it is pure reporting.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_weekly_digest")

DIGEST_EMAIL = "support@sovereignsanctuary.net"
WINDOW_DAYS = 7


def iso_week(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    cal = now.isocalendar()
    return f"{cal[0]}-W{cal[1]:02d}"


def build_digest_text(
    *,
    loop_counts: List[Dict[str, Any]],
    confounded_total: int,
    total_events: int,
    sig_present: int,
    attribution_present: int,
    suppress_active: List[Dict[str, Any]],
    anomaly_counts: List[Dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> str:
    """Pure formatter — no DB/IO, so it is unit-testable without a db_pool."""
    lines: List[str] = [
        "LN7 Flywheel Weekly Digest — report only, no action required",
        f"Window: {window_start.date().isoformat()} to {window_end.date().isoformat()} (UTC)",
        "",
        f"Total outcome_envelope events: {total_events}",
    ]
    if total_events:
        conf_pct = 100.0 * confounded_total / total_events
        sig_pct = 100.0 * sig_present / total_events
        attr_pct = 100.0 * attribution_present / total_events
        lines.append(f"Confounded (E5): {confounded_total} ({conf_pct:.1f}%)")
        lines.append(
            f"Signed rows present (E4, presence-only — not cryptographically "
            f"re-verified here): {sig_present} ({sig_pct:.1f}%)"
        )
        lines.append(f"Rows with cross-loop attribution (E2): {attribution_present} ({attr_pct:.1f}%)")
    else:
        lines.append("No events recorded in window.")
    lines.append("")
    lines.append("By loop / event kind:")
    if loop_counts:
        for row in loop_counts:
            lines.append(
                f"  {row.get('loop_name', 'unknown')} / {row.get('event_kind', 'unknown')}: "
                f"{row.get('n', 0)} (confounded={row.get('confounded_n', 0)}, "
                f"cost=${float(row.get('cost_usd', 0) or 0):.2f})"
            )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"Active reverse-suppress patterns (E8): {len(suppress_active)}")
    for row in suppress_active[:20]:
        lines.append(f"  {row.get('pattern_key')} until {row.get('until_ts')} — {row.get('reason', '')}")
    lines.append("")
    lines.append("Flywheel anomalies this week (E7, flywheel_anomaly bus):")
    if anomaly_counts:
        for row in anomaly_counts:
            lines.append(f"  {row.get('kind', 'unknown')}: {row.get('n', 0)}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


async def _already_sent_this_week(conn, week_id: str) -> bool:
    row = await conn.fetchval(
        """
        SELECT 1 FROM skyeye_activity
        WHERE type = 'ln7_weekly_digest_sent' AND content = $1
          AND created_at > NOW() - INTERVAL '9 days'
        """,
        week_id,
    )
    return bool(row)


async def _mark_sent(conn, week_id: str) -> None:
    await conn.execute(
        """
        INSERT INTO skyeye_activity (platform, type, content)
        VALUES ('ln7', 'ln7_weekly_digest_sent', $1)
        """,
        week_id,
    )


async def _fetch_loop_counts(conn, since: datetime) -> List[Dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT loop_name, event_kind,
               COUNT(*)::int AS n,
               COUNT(*) FILTER (WHERE confounded)::int AS confounded_n,
               COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM outcome_envelope
        WHERE created_at >= $1
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        since,
    )
    return [dict(r) for r in rows]


async def _fetch_totals(conn, since: datetime) -> Dict[str, int]:
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*)::int AS total,
            COUNT(*) FILTER (WHERE confounded)::int AS confounded_n,
            COUNT(*) FILTER (
                WHERE attribution_json IS NOT NULL AND attribution_json != '{}'::jsonb
            )::int AS attr_n
        FROM outcome_envelope
        WHERE created_at >= $1
        """,
        since,
    )
    return dict(row) if row else {"total": 0, "confounded_n": 0, "attr_n": 0}


async def _fetch_sig_coverage(conn, since: datetime) -> int:
    """Isolated from _fetch_totals so a pre-migration-315 DB (no `sig` column
    yet) still yields totals/confounded/attribution stats via graceful
    per-query degrade in run_weekly_digest_cycle."""
    val = await conn.fetchval(
        """
        SELECT COUNT(*) FILTER (WHERE sig IS NOT NULL)::int
        FROM outcome_envelope
        WHERE created_at >= $1
        """,
        since,
    )
    return int(val or 0)


async def _fetch_suppress_active(conn) -> List[Dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT pattern_key, until_ts, reason
        FROM ln7_suppress_patterns
        WHERE until_ts > NOW()
        ORDER BY until_ts DESC
        """
    )
    return [dict(r) for r in rows]


async def _fetch_anomaly_counts(conn, since: datetime) -> List[Dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT COALESCE(metadata->>'kind', 'unknown') AS kind, COUNT(*)::int AS n
        FROM skyeye_activity
        WHERE type = 'flywheel_anomaly' AND created_at >= $1
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        since,
    )
    return [dict(r) for r in rows]


async def run_weekly_digest_cycle(db_pool, notification_system=None) -> Dict[str, Any]:
    """Report-only weekly summary. Never raises to the caller's scheduler
    loop on a single missing table/column — each fetch degrades independently."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    now = datetime.now(timezone.utc)
    week_id = iso_week(now)
    since = now - timedelta(days=WINDOW_DAYS)

    async with db_pool.acquire() as conn:
        try:
            if await _already_sent_this_week(conn, week_id):
                return {"ok": True, "skipped": "already_sent", "week": week_id}
        except Exception as e:
            logger.warning("weekly digest: dedup check failed: %s", e)

        try:
            loop_counts = await _fetch_loop_counts(conn, since)
        except Exception as e:
            logger.warning("weekly digest: loop counts failed: %s", e)
            loop_counts = []
        try:
            totals = await _fetch_totals(conn, since)
        except Exception as e:
            logger.warning("weekly digest: totals failed: %s", e)
            totals = {"total": 0, "confounded_n": 0, "attr_n": 0}
        try:
            sig_present = await _fetch_sig_coverage(conn, since)
        except Exception as e:
            logger.warning("weekly digest: sig coverage failed (pre-mig-315?): %s", e)
            sig_present = 0
        try:
            suppress_active = await _fetch_suppress_active(conn)
        except Exception as e:
            logger.warning("weekly digest: suppress fetch failed: %s", e)
            suppress_active = []
        try:
            anomaly_counts = await _fetch_anomaly_counts(conn, since)
        except Exception as e:
            logger.warning("weekly digest: anomaly fetch failed: %s", e)
            anomaly_counts = []

        body = build_digest_text(
            loop_counts=loop_counts,
            confounded_total=int(totals.get("confounded_n", 0) or 0),
            total_events=int(totals.get("total", 0) or 0),
            sig_present=sig_present,
            attribution_present=int(totals.get("attr_n", 0) or 0),
            suppress_active=suppress_active,
            anomaly_counts=anomaly_counts,
            window_start=since,
            window_end=now,
        )

        emailed = False
        if notification_system and hasattr(notification_system, "_send_email"):
            try:
                await notification_system._send_email(
                    DIGEST_EMAIL,
                    f"LN7 Flywheel Weekly Digest — {week_id}",
                    body,
                )
                emailed = True
            except Exception as e:
                logger.warning("weekly digest: email send failed: %s", e)
        else:
            logger.info("LN7 weekly digest (%s):\n%s", week_id, body)

        try:
            await _mark_sent(conn, week_id)
        except Exception as e:
            logger.warning("weekly digest: mark sent failed: %s", e)

    return {"ok": True, "week": week_id, "emailed": emailed, "events": totals.get("total", 0)}
