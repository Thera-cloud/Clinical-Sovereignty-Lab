"""Nightly PRE6 fuel gauge — trainable organic rows, ETA, latch emails.

Counts aligned with PRE6 (outcome_envelope ci_pack shadows), not raw outcomes.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ln7_fuel_gauge")

PRE6_TARGET = 300
APPROACH_AT = 240
STALL_DAYS = 10

# QUANTUM-CRYSTAL-ARCH — PRE6 fuel = organic G1 ci_pack domains only.
# Telemetry / governance / Goodhart shadow samples must never stall-alert as fuel.
PRIMARY_FUEL_DOMAINS = frozenset({"coding", "general"})
NON_FUEL_DOMAIN_TAGS = frozenset(
    {
        "goodhart_shadow",
        "verify_e2_e4",
        "e4_prod",
        "governance",
        "marketing",
        "crisis_si",
    }
)


def is_pre6_fuel_domain(domain: str, trainable: int = 0) -> bool:
    """True only for domains that count toward PRE6 organic fuel."""
    d = (domain or "").strip() or "general"
    if d in NON_FUEL_DOMAIN_TAGS:
        return False
    if d in PRIMARY_FUEL_DOMAINS:
        return True
    # Future train domains that actually produce ci_pack rows
    return int(trainable or 0) > 0


async def _already_sent(conn, domain: str, kind: str) -> bool:
    row = await conn.fetchval(
        """
        SELECT 1 FROM ln7_fuel_notifications
        WHERE domain_tag = $1 AND kind = $2
        """,
        domain,
        kind,
    )
    return bool(row)


async def _mark_sent(conn, domain: str, kind: str, detail: str) -> None:
    await conn.execute(
        """
        INSERT INTO ln7_fuel_notifications (domain_tag, kind, detail)
        VALUES ($1, $2, $3)
        ON CONFLICT (domain_tag, kind) DO UPDATE
        SET sent_at = NOW(), detail = EXCLUDED.detail
        """,
        domain,
        kind,
        detail[:500],
    )


def _notify(title: str, detail: str, *, domain: str = "coding") -> None:
    """CEO inbox: APPROVE runs allowlisted fuel volume burst (Phase A)."""
    try:
        from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

        enqueue_ceo(
            risk=RISK_YELLOW,
            title=title[:200],
            detail=detail[:800],
            origin="ln7_fuel_gauge",
            dedup_ttl_s=12 * 3600,
            payload={
                "kind": "ln7_fuel_volume_burst",
                "domain": domain,
                "ask_of_ceo": (
                    f"APPROVE to run a PRE6 fuel volume burst for {domain} "
                    "(ci_pack shadow forks + gauge; 12h cooldown). "
                    "ACK/REJECT to clear without running."
                ),
                "apply": {"digest": True, "limit": 0},
            },
        )
    except Exception as e:
        logger.warning("fuel notify failed: %s", e)


async def _domain_counts(conn) -> List[Dict[str, Any]]:
    """Trainable = organic G1 ci_pack shadow rows (PRE6 definition).

    Excludes non-fuel domain_tags (Goodhart shadow samples, E2/E4 probes, etc.)
    even when they write outcome_envelope rows with a different oracle shape.
    """
    rows = await conn.fetch(
        """
        SELECT COALESCE(NULLIF(TRIM(domain_tag), ''), 'general') AS domain_tag,
               COUNT(*) FILTER (
                 WHERE shadow_outcome IS NOT NULL
                   AND COALESCE(shadow_outcome->>'oracle', '') IN ('ci_pack', 'ci_pack_cycle')
                   AND (shadow_outcome->>'passed') IS NOT NULL
               )::int AS trainable,
               COUNT(*) FILTER (
                 WHERE shadow_outcome IS NOT NULL
                   AND COALESCE(shadow_outcome->>'oracle', '') IN ('ci_pack', 'ci_pack_cycle')
                   AND (shadow_outcome->>'passed') IS NOT NULL
               )::int AS total
        FROM outcome_envelope
        GROUP BY 1
        ORDER BY 1
        """
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        tag = str(d.get("domain_tag") or "general")
        trainable = int(d.get("trainable") or 0)
        if not is_pre6_fuel_domain(tag, trainable):
            continue
        out.append(d)
    # Always surface primary fuel domains even at zero so ETA/stall stay honest
    seen = {str(d["domain_tag"]) for d in out}
    for primary in sorted(PRIMARY_FUEL_DOMAINS):
        if primary not in seen:
            out.append({"domain_tag": primary, "trainable": 0, "total": 0})
    out.sort(key=lambda x: str(x["domain_tag"]))
    return out


async def _slope_eta(
    conn, domain: str, trainable: int
) -> Tuple[float, Optional[int], int]:
    """Slope = rows_added_in_window / days_tracked (not blind /7)."""
    since = date.today() - timedelta(days=7)
    snaps = await conn.fetch(
        """
        SELECT snap_date, trainable
        FROM ln7_fuel_snapshots
        WHERE domain_tag = $1 AND snap_date >= $2
        ORDER BY snap_date ASC
        """,
        domain,
        since,
    )
    days_tracked = min(len({r["snap_date"] for r in snaps}), 7) if snaps else 0
    if days_tracked <= 0:
        return 0.0, None, 0
    first = int(snaps[0]["trainable"] or 0)
    last = int(snaps[-1]["trainable"] or 0)
    # Include today's in-memory count as end of window
    end = max(last, trainable)
    added = max(0, end - first)
    slope = added / float(days_tracked)
    eta = math.ceil((PRE6_TARGET - trainable) / slope) if slope > 0 and trainable < PRE6_TARGET else None
    if trainable >= PRE6_TARGET:
        eta = 0
    return slope, eta, days_tracked


async def _stall_days(conn, domain: str, trainable: int) -> int:
    rows = await conn.fetch(
        """
        SELECT snap_date, trainable
        FROM ln7_fuel_snapshots
        WHERE domain_tag = $1
        ORDER BY snap_date DESC
        LIMIT 15
        """,
        domain,
    )
    if not rows:
        return 0
    flat = 0
    for r in rows:
        if int(r["trainable"] or 0) == trainable:
            flat += 1
        else:
            break
    return flat


async def _prior_trainable(conn, domain: str, today: date) -> Optional[int]:
    """Most recent snapshot trainable before today (progress baseline)."""
    val = await conn.fetchval(
        """
        SELECT trainable FROM ln7_fuel_snapshots
        WHERE domain_tag = $1 AND snap_date < $2
        ORDER BY snap_date DESC
        LIMIT 1
        """,
        domain,
        today,
    )
    return int(val) if val is not None else None


async def _clear_stall_on_progress(
    conn, domain: str, trainable: int, prior: Optional[int]
) -> bool:
    """Drop stall latch when trainable increases so a later flat window can re-alert.

    QUANTUM-CRYSTAL-ARCH — latch is one-shot until progress; stale latches from
    pre-jump counts (e.g. coding 1→53) must not silence a future real stall.
    """
    row = await conn.fetchrow(
        """
        SELECT detail FROM ln7_fuel_notifications
        WHERE domain_tag = $1 AND kind = 'stall'
        """,
        domain,
    )
    if not row:
        return False
    detail = str(row.get("detail") or "")
    m = re.search(r":\s*(\d+)\s*/", detail)
    latched_n = int(m.group(1)) if m else None
    progressed = (prior is not None and trainable > prior) or (
        latched_n is not None and trainable > latched_n
    )
    if not progressed:
        return False
    deleted = await conn.fetchval(
        """
        DELETE FROM ln7_fuel_notifications
        WHERE domain_tag = $1 AND kind = 'stall'
        RETURNING 1
        """,
        domain,
    )
    return bool(deleted)


async def run_fuel_gauge_cycle(db_pool) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    today = date.today()
    digest: List[str] = []
    actions: List[str] = []
    async with db_pool.acquire() as conn:
        domains = await _domain_counts(conn)
        if not domains:
            domains = [{"domain_tag": "general", "trainable": 0, "total": 0}]
        for d in domains:
            domain = str(d["domain_tag"])
            trainable = int(d["trainable"] or 0)
            total = int(d["total"] or 0)
            if not is_pre6_fuel_domain(domain, trainable):
                continue
            prior = await _prior_trainable(conn, domain, today)
            await conn.execute(
                """
                INSERT INTO ln7_fuel_snapshots (snap_date, domain_tag, trainable, total)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (snap_date, domain_tag) DO UPDATE
                SET trainable = EXCLUDED.trainable, total = EXCLUDED.total
                """,
                today,
                domain,
                trainable,
                total,
            )
            if await _clear_stall_on_progress(conn, domain, trainable, prior):
                actions.append(f"stall_cleared:{domain}")
                logger.info(
                    "LN7 fuel | cleared stall latch %s (%s → %s)",
                    domain,
                    prior,
                    trainable,
                )
            slope, eta, days_tracked = await _slope_eta(conn, domain, trainable)
            eta_s = f"{eta}d" if eta is not None else "n/a"
            line = (
                f"{domain}: {trainable}/{PRE6_TARGET} trainable, "
                f"+{slope:.1f}/day (n={days_tracked}d), ETA ~{eta_s}"
            )
            digest.append(line)
            logger.info("LN7 fuel | %s", line)

            if trainable >= APPROACH_AT and trainable < PRE6_TARGET:
                if not await _already_sent(conn, domain, "approach"):
                    title = f"[FUEL 80%] {domain} at {trainable}/{PRE6_TARGET}"
                    detail = (
                        f"{line}. Preflight checklist: host-contract on main, "
                        "binary audit, LN7_BURST_ALLOW_PAID=1 only after unlock."
                    )
                    _notify(title, detail, domain=domain)
                    await _mark_sent(conn, domain, "approach", detail)
                    actions.append(f"approach:{domain}")

            if trainable >= PRE6_TARGET:
                if not await _already_sent(conn, domain, "crossed"):
                    title = f"[PRE6 GATE UNLOCKED] {domain} = {trainable} trainable rows"
                    detail = (
                        f"{line}. LN7_BURST_ALLOW_PAID=1 may now be requested. "
                        "Does NOT auto-dispatch bakeoff — enqueue ln7_bakeoff manually."
                    )
                    _notify(title, detail, domain=domain)
                    await _mark_sent(conn, domain, "crossed", detail)
                    try:
                        await conn.execute(
                            """
                            INSERT INTO skyeye_activity (type, content, platform)
                            VALUES ('g1_domain_threshold', $1, 'ln7')
                            """,
                            f"domain={domain} trainable={trainable}"[:500],
                        )
                    except Exception:
                        pass
                    actions.append(f"crossed:{domain}")

            stall = await _stall_days(conn, domain, trainable)
            if slope <= 0.0 and stall >= STALL_DAYS and trainable < PRE6_TARGET:
                if not await _already_sent(conn, domain, "stall"):
                    title = f"[FUEL STALLED] {domain} flat at {trainable} for {stall}d"
                    detail = f"{line}. Queens patch volume low — check shadow_fork / hive_burst."
                    _notify(title, detail, domain=domain)
                    await _mark_sent(conn, domain, "stall", detail)
                    actions.append(f"stall:{domain}")

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "digest": digest,
        "actions": actions,
    }
