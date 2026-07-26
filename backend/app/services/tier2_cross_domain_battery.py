"""
Tier 2 cross-domain battery — real scored packs.  # QUANTUM-CRYSTAL-ARCH

Domains: therapy | family | dojo | voice | ops
Writes tier2_domain_eval_runs. Privacy walls required for pack pass.
Certification candidate only when all domains scored + privacy_ok.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("sovereign.tier2_cross_domain_battery")

TIER2_DOMAINS: Tuple[str, ...] = ("therapy", "family", "dojo", "voice", "ops")

THERAPY_LIVE_SURFACES: FrozenSet[str] = frozenset({"bridge_chat", "therapy"})

MEMBER_SCOPED_SOURCES: FrozenSet[str] = frozenset(
    {
        "family_sanctuary",
        "private_coaching",
        "group_coaching",
        "voice_call",
        "bridge_chat",
    }
)

# Snapshot trigger_source / surface tokens that count toward each domain
_DOMAIN_SURFACE_HINTS: Dict[str, Tuple[str, ...]] = {
    "therapy": ("bridge_chat", "therapy", "chat", "live_activation", "auto"),
    "family": ("family_sanctuary", "sanctuary", "family"),
    "dojo": ("dojo", "dojo_coach", "night_school"),
    "voice": ("voice_call", "voice", "twilio"),
    "ops": ("heartbeat", "admin", "queen", "ops", "refresh_script"),
}


def privacy_wall_spec() -> Dict[str, Any]:
    return {
        "no_cross_member_user_crystal_recall": True,
        "live_context_surfaces_only": sorted(THERAPY_LIVE_SURFACES),
        "forbidden_live_surfaces": [
            "family_sanctuary",
            "group_coaching",
            "private_coaching",
            "voice_call",
            "dojo",
            "ops",
        ],
        "member_scoped_recall_sources": sorted(MEMBER_SCOPED_SOURCES),
        "scoreboard": "tier2_domain_eval_runs",
        "scoreboard_v0": "pgsd_cross_domain_agreement",
    }


def design_pack_skeleton() -> Dict[str, Any]:
    return {
        "version": "tier2_pack_v1",
        "domains": list(TIER2_DOMAINS),
        "privacy": privacy_wall_spec(),
        "eval_table": "tier2_domain_eval_runs",
        "certification": False,
        "notes": "Scored packs required before Narrow AGI exit language.",
    }


def assert_live_context_allowed(surface: str) -> bool:
    return (surface or "").strip().lower() in THERAPY_LIVE_SURFACES


def filter_crystals_for_member(
    crystals: List[Dict[str, Any]],
    member_user_id: str,
) -> List[Dict[str, Any]]:
    mid = str(member_user_id or "")
    if not mid:
        return []
    return [c for c in (crystals or []) if str(c.get("user_id") or "") == mid]


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _privacy_checks() -> Dict[str, Any]:
    """Offline-style privacy evidence (no peer bleed helpers + LIVE_CONTEXT gate)."""
    from app.services import six_quotient_live_context as live

    forbidden_ok = True
    for surf in privacy_wall_spec()["forbidden_live_surfaces"]:
        add = await live.get_live_addendum(object(), surface=surf)
        if add:
            forbidden_ok = False
            break
    crystals = [
        {"user_id": "A", "crystal_text": "a"},
        {"user_id": "B", "crystal_text": "b"},
    ]
    filtered = filter_crystals_for_member(crystals, "A")
    member_ok = len(filtered) == 1 and filtered[0]["user_id"] == "A"
    return {
        "live_context_gated": forbidden_ok,
        "member_crystal_filter": member_ok,
        "privacy_ok": forbidden_ok and member_ok,
    }


async def _domain_scores(
    db_pool: Any,
    hardware_id: str,
    domain: str,
) -> Dict[str, Any]:
    """Score one domain from PGSD ACCESS/FIELD evidence + privacy."""
    privacy = await _privacy_checks()
    hints = _DOMAIN_SURFACE_HINTS.get(domain, ())
    surface_hits = 0
    agreement = None
    discernment = None
    wells = 0
    snap_n = 0
    try:
        async with db_pool.acquire() as conn:
            snap_n = int(
                await conn.fetchval(
                    "SELECT COUNT(*) FROM pgsd_snapshots WHERE user_id = $1",
                    hardware_id,
                )
                or 0
            )
            rows = await conn.fetch(
                """
                SELECT COALESCE(trigger_source, 'unknown') AS surf, COUNT(*)::int AS n
                FROM pgsd_snapshots
                WHERE user_id = $1
                GROUP BY 1
                """,
                hardware_id,
            )
            for r in rows:
                surf = str(r["surf"] or "").lower()
                if any(h in surf for h in hints):
                    surface_hits += int(r["n"] or 0)
            agr = await conn.fetchrow(
                """
                SELECT agreement_score, surfaces, computed_at
                FROM pgsd_cross_domain_agreement
                WHERE user_id = $1
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                hardware_id,
            )
            if agr:
                agreement = float(agr["agreement_score"] or 0.0)
            disc = await conn.fetchrow(
                """
                SELECT score_composite, computed_at
                FROM pgsd_discernment_scores
                WHERE user_id = $1
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                hardware_id,
            )
            if disc:
                discernment = float(disc["score_composite"] or 0.0)
            if _env_true("ENABLE_PGSD_FIELD"):
                wells = int(
                    await conn.fetchval(
                        "SELECT COUNT(*) FROM pgsd_trauma_wells WHERE user_id = $1",
                        hardware_id,
                    )
                    or 0
                )
    except Exception as e:
        logger.warning("tier2 domain %s query failed: %s", domain, e)

    # Domain score: presence + agreement/discernment + privacy
    presence = 1.0 if snap_n > 0 else 0.0
    surf_score = min(1.0, surface_hits / 3.0) if surface_hits else (0.35 if presence else 0.0)
    # therapy/ops can pass on global snaps; family/dojo/voice prefer surface hits
    if domain in ("family", "dojo", "voice") and surface_hits == 0:
        surf_score = min(surf_score, 0.25)
    agree_s = agreement if agreement is not None else 0.0
    disc_s = discernment if discernment is not None else 0.0
    field_bonus = 0.1 if wells > 0 else 0.0
    raw = (
        0.25 * presence
        + 0.30 * surf_score
        + 0.20 * agree_s
        + 0.15 * disc_s
        + 0.10 * (1.0 if privacy["privacy_ok"] else 0.0)
        + field_bonus
    )
    score = round(min(1.0, raw), 4)
    access_on = _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_ACCESS")
    # Pass: privacy + ACCESS + evidence (surface hit preferred; agreement covers sparse domains)
    has_signal = surface_hits >= 1 or agreement is not None or discernment is not None
    domain_pass = bool(
        privacy["privacy_ok"]
        and access_on
        and snap_n > 0
        and has_signal
        and score >= 0.40
    )
    return {
        "domain": domain,
        "score": score,
        "snapshot_count": snap_n,
        "surface_hits": surface_hits,
        "agreement_score": agreement,
        "discernment_composite": discernment,
        "trauma_wells": wells,
        "privacy": privacy,
        "access_on": access_on,
        "field_on": _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_FIELD"),
        "pass": domain_pass,
    }


async def run_pack(
    db_pool: Any,
    subject_id: str,
    *,
    environment: Optional[str] = None,
    pack_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run scored multi-domain pack for one subject (hardware_id / username / uuid).
    Persists one tier2_domain_eval_runs row per domain. Returns pack summary.
    """
    if not db_pool or not subject_id:
        return {"ok": False, "error": "db_pool and subject_id required"}

    from app.services.pgsd_engine import PGSDEngine

    eng = PGSDEngine(db_pool=db_pool)
    resolved = await eng.resolve_pgsd_subject(subject_id)
    if not resolved:
        return {"ok": False, "error": f"subject not found: {subject_id}"}
    hw = resolved["hardware_id"]
    env = environment or os.getenv("ENVIRONMENT") or "production"
    pid = pack_id or f"tier2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    domain_results: List[Dict[str, Any]] = []
    async with db_pool.acquire() as conn:
        for domain in TIER2_DOMAINS:
            await conn.execute(
                """
                INSERT INTO tier2_domain_eval_runs
                    (pack_id, domain, environment, status, scores_json, privacy_ok, notes)
                VALUES ($1, $2, $3, 'running', '{}'::jsonb, NULL, $4)
                """,
                pid,
                domain,
                env,
                f"subject={hw}",
            )
            scores = await _domain_scores(db_pool, hw, domain)
            privacy_ok = bool(scores.get("privacy", {}).get("privacy_ok"))
            status = "scored" if scores.get("pass") else "failed"
            await conn.execute(
                """
                UPDATE tier2_domain_eval_runs
                SET status = $1,
                    scores_json = $2::jsonb,
                    privacy_ok = $3,
                    scored_at = NOW(),
                    notes = $4
                WHERE id = (
                    SELECT id FROM tier2_domain_eval_runs
                    WHERE pack_id = $5 AND domain = $6
                    ORDER BY id DESC LIMIT 1
                )
                """,
                status,
                json.dumps(scores),
                privacy_ok,
                f"subject={hw} score={scores.get('score')}",
                pid,
                domain,
            )
            domain_results.append({**scores, "status": status})

    passed = sum(1 for d in domain_results if d.get("status") == "scored")
    all_privacy = all(d.get("privacy", {}).get("privacy_ok") for d in domain_results)
    certify_ready = passed == len(TIER2_DOMAINS) and all_privacy
    return {
        "ok": True,
        "pack_id": pid,
        "subject_hardware_id": hw,
        "username": resolved.get("username"),
        "environment": env,
        "domains": domain_results,
        "passed": passed,
        "total": len(TIER2_DOMAINS),
        "privacy_ok": all_privacy,
        "certify_candidate": certify_ready,
        "field_on": _env_true("ENABLE_PGSD_FIELD"),
        "version": "tier2_pack_v1",
    }


async def latest_pack_summary(db_pool: Any, environment: Optional[str] = None) -> Dict[str, Any]:
    if not db_pool:
        return {"packs": []}
    env = environment or os.getenv("ENVIRONMENT") or "production"
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pack_id, domain, status, scores_json, privacy_ok, scored_at, created_at
            FROM tier2_domain_eval_runs
            WHERE environment = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            env,
        )
    by_pack: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        pid = r["pack_id"]
        by_pack.setdefault(pid, []).append(
            {
                "domain": r["domain"],
                "status": r["status"],
                "privacy_ok": r["privacy_ok"],
                "scores": dict(r["scores_json"] or {})
                if isinstance(r["scores_json"], dict)
                else json.loads(r["scores_json"] or "{}"),
                "scored_at": r["scored_at"].isoformat() if r["scored_at"] else None,
            }
        )
    packs = []
    for pid, domains in by_pack.items():
        scored = sum(1 for d in domains if d["status"] == "scored")
        packs.append(
            {
                "pack_id": pid,
                "domains": domains,
                "passed": scored,
                "total": len(domains),
                "certify_candidate": scored == len(TIER2_DOMAINS)
                and all(d.get("privacy_ok") for d in domains),
            }
        )
    return {"packs": packs[:5]}
