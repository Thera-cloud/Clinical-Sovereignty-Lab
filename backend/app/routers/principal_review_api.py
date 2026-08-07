"""
Principal-Review Admin API — gold scoring (D.14b) + conversation library.

Sovereign Command tab: principal_review.html
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.services.api_server import require_admin

logger = logging.getLogger("nate.principal_review_api")

router = APIRouter(
    prefix="/api/admin/principal-review",
    tags=["principal-review"],
    dependencies=[Depends(require_admin)],
)

_ALLOWED_RATERS = frozenset({"DrNevedal1"})
# Gate (mig 259): median + per-item floor 45s; reject rush submits server-side.
MIN_ITEM_LATENCY_MS = 45000
# Worksheet: intra-rater recheck ≥14 days after original score (0 disables).
RECHECK_MIN_GAP_DAYS = max(0, int(os.getenv("TIER1_RECHECK_MIN_GAP_DAYS", "14") or "14"))
# Notes hold 3/3/3 corrective underwriting — keep room for full ideal replies.
GOLD_NOTES_MAX_CHARS = 8000
# Auto-promote scored gold when Principal notes are substantial enough to teach.
GOLD_NOTES_AUTO_PROMOTE_MIN = 80
_BRIDGE_QUEUE_CANDIDATES = (
    Path("/app/bridge_data/coach_learning_queue.json"),
    Path(os.getenv("COACH_LEARNING_QUEUE_FILE", "") or ""),
)

_ANTI_VERBATIM_RULE = (
    "TEACHING RULE: Absorb principles, stance, safety moves, and clinical intent "
    "from Principal Guide. Never recite Guide text verbatim in client replies — "
    "paraphrase naturally for the live moment. Verbatim reuse lowers naturalness "
    "and other scores."
)


def _clip_gold_notes(notes: Optional[str]) -> str:
    return (notes or "").strip()[:GOLD_NOTES_MAX_CHARS]


def _build_principal_crystal_text(row: Any) -> str:
    """Corrective underwriting: annotated delta + Guide; no stem ids / Client: in body."""
    from app.services.principal_review_crisis_policy import (
        annotate_teaching_delta,
        scrub_teaching_text,
    )

    principal = scrub_teaching_text(row["principal_response"] or "")
    nate = scrub_teaching_text(row["nate_response"] or "")
    if not (principal or nate):
        return ""
    section = str(row["section"] or "clinical")[:40]
    # Unique lib-id prefix so LEFT(text,80) never collides across scenarios
    # (factory also exempts origin_surface=principal_review). Never stem ids.
    try:
        lib_tag = str(row["id"] or "").replace("-", "")[:12]
    except (KeyError, IndexError, TypeError):
        lib_tag = ""
    header = (
        f"[Principal-Review · {section} · lib:{lib_tag}]"
        if lib_tag
        else f"[Principal-Review · {section}]"
    )
    parts = [
        header,
        _ANTI_VERBATIM_RULE,
    ]
    try:
        delta = annotate_teaching_delta(principal=principal, nate_blind=nate)
        if delta:
            parts.append(delta)
    except Exception:
        if principal and nate:
            from app.services.principal_review_crisis_policy import classify_failure_class

            parts.append(
                "DELTA (near-miss → correction):\n"
                f"- Failed class (do not reproduce): {classify_failure_class(nate)}\n"
                f"- Corrected move (Principal Guide — adapt, do not recite): "
                f"{principal[:1200]}\n"
                "- Why: never quote failed blinds in teaching; failure classes only."
            )
    if principal:
        parts.append(
            "Principal Guide (3/3/3 corrective underwriting — adapt, do not recite):\n"
            f"{principal[:2500]}"
        )
    elif nate:
        parts.append(f"Guide: {nate[:2500]}")
    return scrub_teaching_text("\n".join(parts))


def _enforce_item_latency(latency_ms: int) -> int:
    ms = int(latency_ms)
    if ms < MIN_ITEM_LATENCY_MS:
        raise HTTPException(
            422,
            f"latency_ms={ms} below floor {MIN_ITEM_LATENCY_MS} "
            "(D.14b requires ≥45s/item for score-entry provenance)",
        )
    return ms


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(500, "Database pool unavailable")
    return pool


def _rater(user: Dict[str, Any]) -> str:
    u = (
        (user or {}).get("username")
        or (user or {}).get("user")
        or (user or {}).get("name")
        or ""
    )
    return str(u).strip()


# ── Health ──────────────────────────────────────────────────────────────────


@router.get("/health")
async def health():
    return {"status": "ok", "surface": "principal_review"}


# ── Gold scoring (D.14b authenticated surface) ──────────────────────────────


class StartSessionBody(BaseModel):
    purpose: str = "human_gold_scoring"
    notes: str = ""


@router.post("/gold/session/start")
async def gold_session_start(
    body: StartSessionBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    run_id = f"gold_admin_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    pool = _pool(request)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO six_quotient_gold_admin_runs
               (run_id, purpose, rater_id, notes)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (run_id) DO NOTHING""",
            run_id,
            (body.purpose or "human_gold_scoring")[:80],
            rater[:64],
            (body.notes or "")[:2000] or None,
        )
    return {
        "status": "ok",
        "run_id": run_id,
        "rater_id": rater,
        "score_entry_source": "authenticated_scoring_surface",
        "min_median_latency_ms": MIN_ITEM_LATENCY_MS,
        "min_item_latency_ms": MIN_ITEM_LATENCY_MS,
    }


@router.get("/gold/progress")
async def gold_progress(request: Request):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT
                 COUNT(*)::int AS total,
                 COUNT(*) FILTER (WHERE pairs_locked)::int AS locked,
                 COUNT(*) FILTER (WHERE human_scored)::int AS scored,
                 COUNT(*) FILTER (
                   WHERE score_entry_source = 'authenticated_scoring_surface'
                 )::int AS authenticated,
                 COUNT(*) FILTER (WHERE is_degraded_distractor)::int AS degraded,
                 COUNT(*) FILTER (
                   WHERE nate_response ILIKE '%DRY-RUN%'
                      OR nate_response ILIKE '%Placeholder Nate reply%'
                 )::int AS dry_run_placeholders,
                 COUNT(*) FILTER (
                   WHERE COALESCE(nate_response_live, '') <> ''
                 )::int AS live_filled,
                 COUNT(*) FILTER (
                   WHERE COALESCE(live_human_scored, false) = true
                 )::int AS live_scored
               FROM six_quotient_human_gold"""
        )
    return {"status": "ok", **dict(row or {})}


# Battery scoping for /gold/items. Each entry's regex must stay in sync
# with compute_tier1_v2_battery_holdout_kappa.V2_BATTERY_ID_RE (enforced by
# test_battery_scope_matches_kappa_script_constant) -- confined here rather
# than imported cross-module so a router never pulls in a standalone script,
# same "one auditable constant" pattern as _BURNED_SCENARIO_IDS in
# compute_tier1_v5_fresh_holdout_kappa.py. Add a new entry per future
# battery rather than redefining what "v2" means.
_BATTERY_SQL_CLAUSE = {
    "all": "",
    "v2": "AND scenario_id ~ '-V(0[1-9]|1[0-2])$'",
    "v1": "AND scenario_id !~ '-V(0[1-9]|1[0-2])$'",
}


@router.get("/gold/items")
async def gold_items(
    request: Request,
    unscored_only: bool = True,
    limit: int = 50,
    track: str = "judge",
    battery: str = "all",
):
    """Blind worksheet rows — no distractor flag, no masterful_criteria, no arm.

    track=judge → nate_response (κ). track=live → nate_response_live (capability).
    battery=all|v1|v2 — scope to a specific stem battery (v2 = the 70-stem
    2026-08-03 battery, TRUST_LEDGER Entries 29-31). Default all preserves
    prior behavior.
    """
    pool = _pool(request)
    limit = max(1, min(int(limit or 50), 100))
    track_norm = (track or "judge").strip().lower()
    if track_norm not in ("judge", "live"):
        raise HTTPException(422, "track must be judge|live")
    battery_norm = (battery or "all").strip().lower()
    if battery_norm not in _BATTERY_SQL_CLAUSE:
        raise HTTPException(422, f"battery must be one of {sorted(_BATTERY_SQL_CLAUSE)}")
    battery_clause = _BATTERY_SQL_CLAUSE[battery_norm]
    async with pool.acquire() as conn:
        # Migration 323 tolerance: scoring_guide may not exist on every
        # environment yet. Never let a missing rater-only column break the
        # scoring surface itself.
        has_scoring_guide = False
        try:
            has_scoring_guide = bool(
                await conn.fetchval(
                    """SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'six_quotient_human_gold'
                         AND column_name = 'scoring_guide'"""
                )
            )
        except Exception:
            has_scoring_guide = False
        guide_col = ", scoring_guide" if has_scoring_guide else ", NULL::text AS scoring_guide"
        if track_norm == "live":
            rows = await conn.fetch(
                f"""SELECT scenario_id, section, client_says, nate_response_live AS response,
                           response_class, difficulty,
                           COALESCE(live_human_scored, false) AS human_scored,
                           blinded, live_stack_run_id{guide_col}
                    FROM six_quotient_human_gold
                    WHERE COALESCE(nate_response_live, '') <> ''
                      {"AND COALESCE(live_human_scored, false) = false" if unscored_only else ""}
                      {battery_clause}
                    ORDER BY md5(scenario_id || COALESCE(client_says,''))
                    LIMIT $1""",
                limit,
            )
        else:
            # Exclude DRY-RUN battery placeholders — not scoreable gold.
            rows = await conn.fetch(
                f"""SELECT scenario_id, section, client_says, nate_response AS response,
                           response_class, difficulty, human_scored, blinded,
                           NULL::text AS live_stack_run_id{guide_col}
                    FROM six_quotient_human_gold
                    WHERE pairs_locked = true
                      AND COALESCE(nate_response, '') <> ''
                      AND nate_response NOT ILIKE '%DRY-RUN%'
                      AND nate_response NOT ILIKE '%Placeholder Nate reply%'
                      AND nate_response NOT ILIKE '%External scoring required%'
                      {"AND human_scored = false" if unscored_only else ""}
                      {battery_clause}
                    ORDER BY md5(scenario_id || COALESCE(client_says,''))
                    LIMIT $1""",
                limit,
            )
    items = []
    for r in rows:
        items.append(
            {
                "scenario_id": r["scenario_id"],
                "section": r["section"],
                "client_says": r["client_says"],
                "response": r["response"],
                "response_class": r["response_class"],
                "difficulty": r["difficulty"],
                "human_scored": bool(r["human_scored"]),
                "blinded": bool(r["blinded"]),
                "track": track_norm,
                "live_stack_run_id": r.get("live_stack_run_id"),
                # Rater-only reference (never generation input — see
                # test_v2_battery_scoring_guide_isolation.py). Display only;
                # submitScore() sends an explicit whitelisted body, so this
                # cannot round-trip into any write path.
                "scoring_guide": r.get("scoring_guide") or None,
            }
        )
    return {
        "status": "ok",
        "track": track_norm,
        "battery": battery_norm,
        "count": len(items),
        "items": items,
    }


_LIVE_MODE_FAILURES = frozenset(
    {"perspective_inversion", "third_person_rp", "dry_run_placeholder"}
)


class GoldScoreBody(BaseModel):
    scenario_id: str
    run_id: str
    primary: int = Field(..., ge=0, le=3)
    accuracy: int = Field(..., ge=0, le=3)
    naturalness: int = Field(..., ge=0, le=3)
    safety_veto: Optional[str] = None
    mode_failure: Optional[str] = None
    notes: str = ""
    latency_ms: int = Field(..., ge=0)
    score_session_id: Optional[str] = None
    track: str = "judge"

    @field_validator("scenario_id", "run_id")
    @classmethod
    def _req(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("required")
        return v

    @field_validator("safety_veto")
    @classmethod
    def _veto(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if v not in ("ok", "fail"):
            raise ValueError("safety_veto must be ok|fail")
        return v

    @field_validator("mode_failure")
    @classmethod
    def _mode_fail(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if v not in _LIVE_MODE_FAILURES:
            raise ValueError(
                "mode_failure must be perspective_inversion|"
                "third_person_rp|dry_run_placeholder"
            )
        return v


@router.post("/gold/score")
async def gold_score(
    body: GoldScoreBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    latency_ms = _enforce_item_latency(body.latency_ms)
    pool = _pool(request)
    session_id = (body.score_session_id or body.run_id)[:80]
    notes_text = _clip_gold_notes(body.notes)
    track_norm = (body.track or "judge").strip().lower()
    if track_norm not in ("judge", "live"):
        raise HTTPException(422, "track must be judge|live")
    lib_id = None
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT run_id, rater_id FROM six_quotient_gold_admin_runs WHERE run_id = $1",
            body.run_id,
        )
        if not run:
            raise HTTPException(404, "gold admin run not found — start a session first")
        if (run["rater_id"] or "") != rater:
            raise HTTPException(403, "run belongs to a different rater")
        locked = await conn.fetchrow(
            """SELECT scenario_id, pairs_locked, human_scored, nate_response,
                      nate_response_live, score_entry_source
               FROM six_quotient_human_gold WHERE scenario_id = $1""",
            body.scenario_id,
        )
        if not locked:
            raise HTTPException(404, "scenario not in gold set")

        # QUANTUM-CRYSTAL-ARCH — capability track: score live blinds only; no teach
        if track_norm == "live":
            live_nr = locked["nate_response_live"] or ""
            if not live_nr.strip():
                raise HTTPException(409, "nate_response_live empty — generate live-stack first")
            await conn.execute(
                """UPDATE six_quotient_human_gold SET
                     live_primary_score = $2,
                     live_accuracy_score = $3,
                     live_naturalness_score = $4,
                     live_safety_veto = $5,
                     live_notes = COALESCE(NULLIF($6, ''), live_notes),
                     live_mode_failure = $11,
                     live_human_scored = true,
                     live_rater_id = $7,
                     live_scored_at = NOW(),
                     live_gold_admin_run_id = $8,
                     live_score_latency_ms = $9,
                     live_score_session_id = $10
                   WHERE scenario_id = $1""",
                body.scenario_id,
                body.primary,
                body.accuracy,
                body.naturalness,
                body.safety_veto,
                notes_text,
                rater[:64],
                body.run_id[:80],
                latency_ms,
                session_id,
                body.mode_failure,
            )
            return {
                "status": "ok",
                "scenario_id": body.scenario_id,
                "track": "live",
                "score_entry_source": "live_stack_scoring_surface",
                "rater_id": rater,
                "latency_ms": latency_ms,
                "notes_as_principal_guide": False,
                "library_id": None,
                "promoted_crystal_id": None,
                "learning": (
                    "live-track score stored for capability baseline only — "
                    "no crystal promote; judge-track scores/notes untouched"
                ),
            }

        if not locked["pairs_locked"]:
            raise HTTPException(409, "pairs not locked — freeze gold before scoring")
        # TRUST_LEDGER Entry 39 — after v2 κ, scores are snapshot-frozen;
        # refuse post-hoc re-reads that would drift the held-out gold.
        _src = locked["score_entry_source"] or ""
        if locked["human_scored"] and str(_src).startswith("v2_battery_gold_frozen"):
            raise HTTPException(
                409,
                "v2 battery gold frozen after κ — re-score blocked "
                "(see docs/ln7/evidence/v2_battery_gold_lock_*)",
            )
        nr = locked["nate_response"] or ""
        if (
            "DRY-RUN" in nr
            or "Placeholder Nate reply" in nr
            or "External scoring required" in nr
        ):
            raise HTTPException(
                409,
                "nate_response is a DRY-RUN placeholder — replace before scoring",
            )
        await conn.execute(
            """UPDATE six_quotient_human_gold SET
                 primary_score = $2,
                 accuracy_score = $3,
                 naturalness_score = $4,
                 safety_veto = $5,
                 notes = COALESCE(NULLIF($6, ''), notes),
                 human_scored = true,
                 rater_id = $7,
                 scored_at = NOW(),
                 gold_admin_run_id = $8,
                 score_entry_source = 'authenticated_scoring_surface',
                 score_entry_latency_ms = $9,
                 score_session_id = $10
               WHERE scenario_id = $1""",
            body.scenario_id,
            body.primary,
            body.accuracy,
            body.naturalness,
            body.safety_veto,
            notes_text,
            rater[:64],
            body.run_id[:80],
            latency_ms,
            session_id,
        )
        # Mirror: notes = Principal Guide (corrective underwriting vs blind Nate)
        meta = json.dumps(
            {
                "primary": body.primary,
                "accuracy": body.accuracy,
                "naturalness": body.naturalness,
                "safety_veto": body.safety_veto,
                "latency_ms": latency_ms,
                "notes_as_principal_guide": bool(notes_text),
            }
        )
        lib_id = await conn.fetchval(
            """SELECT id FROM principal_review_library
               WHERE source_kind = 'gold_scored' AND source_ref = $1""",
            body.scenario_id,
        )
        if lib_id:
            await conn.execute(
                """UPDATE principal_review_library SET
                     topic = $1,
                     principal_response = CASE
                       WHEN NULLIF($2, '') IS NOT NULL THEN $2
                       ELSE principal_response
                     END,
                     nate_response = g.nate_response,
                     response_class = g.response_class,
                     source_scenario = g.scenario_id,
                     metadata = $4::jsonb,
                     gold_admin_run_id = $5,
                     status = CASE
                       WHEN status = 'promoted' THEN status
                       ELSE 'draft'
                     END,
                     updated_at = NOW()
                   FROM six_quotient_human_gold g
                   WHERE principal_review_library.id = $6::uuid
                     AND g.scenario_id = $3""",
                body.scenario_id,
                notes_text,
                body.scenario_id,
                meta,
                body.run_id[:80],
                lib_id,
            )
        else:
            lib_id = await conn.fetchval(
                """INSERT INTO principal_review_library
                   (topic, section, client_says, principal_response, nate_response,
                    source_kind, source_ref, status, gold_admin_run_id, created_by,
                    metadata, response_class, source_scenario)
                   SELECT
                     scenario_id,
                     section, client_says,
                     COALESCE(NULLIF($2, ''), ''),
                     nate_response,
                     'gold_scored', scenario_id, 'draft', $3, $4, $5::jsonb,
                     response_class, scenario_id
                   FROM six_quotient_human_gold WHERE scenario_id = $1
                   RETURNING id""",
                body.scenario_id,
                notes_text,
                body.run_id[:80],
                rater[:64],
                meta,
            )

    promoted_crystal_id = None
    if (
        notes_text
        and len(notes_text) >= GOLD_NOTES_AUTO_PROMOTE_MIN
        and lib_id
    ):
        try:
            promote_result = await _promote_library_item(
                request, str(lib_id), rater=rater
            )
            promoted_crystal_id = promote_result.get("crystal_id")
        except HTTPException as e:
            logger.warning(
                "principal_review auto-promote %s: %s",
                body.scenario_id,
                e.detail,
            )
        except Exception as e:
            logger.warning(
                "principal_review auto-promote %s: %s", body.scenario_id, e
            )

    return {
        "status": "ok",
        "scenario_id": body.scenario_id,
        "score_entry_source": "authenticated_scoring_surface",
        "rater_id": rater,
        "latency_ms": latency_ms,
        "notes_as_principal_guide": bool(notes_text),
        "library_id": str(lib_id) if lib_id else None,
        "promoted_crystal_id": promoted_crystal_id,
        "learning": (
            "notes stored as Principal Guide vs blind Nate; "
            "crystal teaches adapt-not-recite"
            if notes_text
            else "score stored; add notes to teach 3/3/3 corrective underwriting"
        ),
    }


@router.post("/gold/backfill-notes-learning")
async def gold_backfill_notes_learning(
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """One-shot: copy scored gold notes → Principal Guide and promote crystals."""
    rater = _rater(admin)
    # SKYEYE_AUDIT_TOKEN resolves as audit_system before Redis — allow ADMIN audit ops.
    if rater not in _ALLOWED_RATERS:
        if str((admin or {}).get("role") or "").upper() == "ADMIN" and (
            admin.get("is_audit") or admin.get("is_audit_token")
        ):
            rater = "DrNevedal1"
        else:
            raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    pool = _pool(request)
    promoted: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT scenario_id, notes, nate_response, section, client_says
               FROM six_quotient_human_gold
               WHERE human_scored = true
                 AND NULLIF(BTRIM(notes), '') IS NOT NULL
                 AND LENGTH(BTRIM(notes)) >= $1""",
            GOLD_NOTES_AUTO_PROMOTE_MIN,
        )
        for g in rows:
            notes_text = _clip_gold_notes(g["notes"])
            lib_id = await conn.fetchval(
                """SELECT id FROM principal_review_library
                   WHERE source_kind = 'gold_scored' AND source_ref = $1""",
                g["scenario_id"],
            )
            meta = json.dumps(
                {
                    "notes_as_principal_guide": True,
                    "backfill": True,
                }
            )
            gold_rc = await conn.fetchval(
                """SELECT response_class FROM six_quotient_human_gold
                   WHERE scenario_id = $1""",
                g["scenario_id"],
            )
            if lib_id:
                await conn.execute(
                    """UPDATE principal_review_library SET
                         topic = $1,
                         principal_response = $2,
                         nate_response = $3,
                         response_class = $6,
                         source_scenario = $1,
                         metadata = COALESCE(metadata, '{}'::jsonb) || $4::jsonb,
                         status = CASE
                           WHEN status = 'archived' THEN status
                           ELSE 'draft'
                         END,
                         updated_at = NOW()
                       WHERE id = $5::uuid""",
                    g["scenario_id"],
                    notes_text,
                    g["nate_response"] or "",
                    meta,
                    lib_id,
                    gold_rc,
                )
            else:
                lib_id = await conn.fetchval(
                    """INSERT INTO principal_review_library
                       (topic, section, client_says, principal_response, nate_response,
                        source_kind, source_ref, status, created_by, metadata,
                        response_class, source_scenario)
                       VALUES ($1, $2, $3, $4, $5, 'gold_scored', $1, 'draft', $6, $7::jsonb,
                               $8, $1)
                       RETURNING id""",
                    g["scenario_id"],
                    g["section"] or "clinical",
                    g["client_says"] or "",
                    notes_text,
                    g["nate_response"] or "",
                    rater[:64],
                    meta,
                    gold_rc,
                )
            promoted.append(
                {"scenario_id": g["scenario_id"], "library_id": str(lib_id)}
            )

    results = []
    for item in promoted:
        try:
            pr = await _promote_library_item(
                request, item["library_id"], rater=rater
            )
            results.append(
                {
                    **item,
                    "crystal_id": pr.get("crystal_id"),
                    "teaching_source": pr.get("teaching_source"),
                }
            )
        except Exception as e:
            results.append({**item, "error": str(e)})
    return {
        "status": "ok",
        "backfilled": len(results),
        "items": results,
        "learning": (
            "notes → Principal Guide vs blind Nate; "
            "crystals teach adapt-not-recite"
        ),
    }


LIVE_NOTES_HARVEST_MIN = GOLD_NOTES_AUTO_PROMOTE_MIN


@router.post("/gold/live-track/harvest-notes")
async def live_track_harvest_notes(
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Capability-session harvest ticket (docs/ln7/TRUST_LEDGER.md Entry 16).

    Live-track (capability) scoring is deliberately "no-promote" at score
    time — POST /gold/score's live branch always returns
    notes_as_principal_guide=False, library_id=None, promoted_crystal_id=
    None, unlike the judge-track branch which can auto-promote. That
    asymmetry was correct as a default (capability baseline should not
    silently mutate the teaching corpus mid-measurement) but left no path
    at all for the diagnostic value in those notes — 45 live-track rows
    accumulated substantial (>=80 char) live_notes with zero mechanism to
    ever become a Guide.

    This endpoint is the harvest path, DRAFT-ONLY: it creates or updates a
    principal_review_library row per qualifying live-track note
    (source_kind='live_scored', distinct from judge-track's 'gold_scored'
    so the two provenances never collide in dedup lookups), status
    always 'draft'. It does NOT call _promote_library_item — unlike
    gold_backfill_notes_learning's judge-track equivalent, promotion here
    requires a human to review each draft individually via the existing
    POST /library/{item_id}/promote endpoint. That per-item human review
    IS the "post-condition review" this ticket names: which of the 40+
    diagnostic notes are durable, generalizable findings (promote) versus
    one-off observations about a single generation (leave as draft, or
    archive). Skips rows already flagged live_is_fallback_template=true
    (migration 320) — a note written about the audit fallback string is
    diagnostic about the audit gate, not clinical teaching material, and
    promoting it would misfile a system-integrity finding as a therapeutic
    guide.
    """
    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        if str((admin or {}).get("role") or "").upper() == "ADMIN" and (
            admin.get("is_audit") or admin.get("is_audit_token")
        ):
            rater = "DrNevedal1"
        else:
            raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    pool = _pool(request)
    harvested: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT scenario_id, live_notes, nate_response_live, section,
                      client_says, response_class
               FROM six_quotient_human_gold
               WHERE live_human_scored = true
                 AND COALESCE(live_is_fallback_template, false) = false
                 AND NULLIF(BTRIM(live_notes), '') IS NOT NULL
                 AND LENGTH(BTRIM(live_notes)) >= $1""",
            LIVE_NOTES_HARVEST_MIN,
        )
        for g in rows:
            notes_text = _clip_gold_notes(g["live_notes"])
            meta = json.dumps(
                {
                    "notes_as_principal_guide": True,
                    "harvested_from": "live_track_capability_session",
                    "requires_human_promotion_review": True,
                }
            )
            lib_id = await conn.fetchval(
                """SELECT id FROM principal_review_library
                   WHERE source_kind = 'live_scored' AND source_ref = $1""",
                g["scenario_id"],
            )
            if lib_id:
                await conn.execute(
                    """UPDATE principal_review_library SET
                         topic = $1,
                         principal_response = $2,
                         nate_response = $3,
                         response_class = $6,
                         source_scenario = $1,
                         metadata = COALESCE(metadata, '{}'::jsonb) || $4::jsonb,
                         status = CASE
                           WHEN status IN ('archived', 'promoted') THEN status
                           ELSE 'draft'
                         END,
                         updated_at = NOW()
                       WHERE id = $5::uuid""",
                    g["scenario_id"],
                    notes_text,
                    g["nate_response_live"] or "",
                    meta,
                    lib_id,
                    g["response_class"],
                )
                action = "updated"
            else:
                lib_id = await conn.fetchval(
                    """INSERT INTO principal_review_library
                       (topic, section, client_says, principal_response, nate_response,
                        source_kind, source_ref, status, created_by, metadata,
                        response_class, source_scenario)
                       VALUES ($1, $2, $3, $4, $5, 'live_scored', $1, 'draft', $6, $7::jsonb,
                               $8, $1)
                       RETURNING id""",
                    g["scenario_id"],
                    g["section"] or "clinical",
                    g["client_says"] or "",
                    notes_text,
                    g["nate_response_live"] or "",
                    rater[:64],
                    meta,
                    g["response_class"],
                )
                action = "created"
            harvested.append(
                {
                    "scenario_id": g["scenario_id"],
                    "library_id": str(lib_id),
                    "action": action,
                }
            )
    return {
        "status": "ok",
        "harvested": len(harvested),
        "items": harvested,
        "learning": (
            "live-track diagnostic notes now exist as DRAFT Principal Guides — "
            "none auto-promoted. Review each via POST /library/{item_id}/promote "
            "to convert the durable findings into teaching crystals; the rest "
            "stay draft (or archive them) as one-off observations."
        ),
    }


# ── Live-stack capability baseline (dual-track) ─────────────────────────────


class LiveStackGenerateBody(BaseModel):
    """Produce nate_response_live via production therapeutic stack."""

    scenario_ids: Optional[List[str]] = None
    scored_only: bool = True
    limit: int = Field(20, ge=1, le=50)
    force_rewrite: bool = False
    scrub_deltas_only: bool = False
    user: str = "audit_client"
    run_id: str = ""


@router.post("/gold/live-stack/generate")
async def gold_live_stack_generate(
    body: LiveStackGenerateBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Capability-track blinds only — does not overwrite judge-track nate_response."""
    pool = _pool(request)
    from app.services.live_stack_blinds import (
        generate_live_stack_batch,
        scrub_contaminated_deltas,
    )

    if body.scrub_deltas_only:
        async with pool.acquire() as conn:
            n = await scrub_contaminated_deltas(conn)
            relabel = await conn.execute(
                """UPDATE six_quotient_human_gold
                   SET response_provenance = 'harness_thin_inference'
                   WHERE response_provenance = 'nate_genuine_attempt'
                     AND COALESCE(is_degraded_distractor, false) = false"""
            )
        return {
            "status": "ok",
            "scrubbed_deltas": n,
            "relabel": str(relabel),
            "track": "capability",
        }
    try:
        out = await generate_live_stack_batch(
            pool,
            scenario_ids=body.scenario_ids,
            scored_only=body.scored_only,
            limit=body.limit,
            user=body.user or "audit_client",
            force_rewrite=body.force_rewrite,
            run_id=body.run_id or None,
        )
    except Exception as e:
        logger.warning("gold live-stack generate failed: %s", e)
        raise HTTPException(502, f"live-stack generate failed: {e}") from e
    out["track"] = "capability"
    out["note"] = (
        "Compare only within live_stack_run_id. Judge κ uses nate_response "
        "(harness_thin_inference); do not conflate tracks."
    )
    return out


@router.get("/gold/live-stack/status")
async def gold_live_stack_status(request: Request):
    pool = _pool(request)
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """SELECT
                     COUNT(*) FILTER (WHERE human_scored) AS judge_scored,
                     COUNT(*) FILTER (
                       WHERE response_provenance = 'harness_thin_inference'
                     ) AS harness,
                     COUNT(*) FILTER (
                       WHERE response_provenance = 'nate_genuine_attempt'
                     ) AS legacy_mislabeled,
                     COUNT(*) FILTER (
                       WHERE COALESCE(nate_response_live, '') <> ''
                     ) AS live_filled,
                     COUNT(*) FILTER (
                       WHERE live_response_provenance = 'live_stack_attempt'
                     ) AS live_labeled,
                     COUNT(*) FILTER (
                       WHERE COALESCE(live_human_scored, false) = true
                     ) AS live_scored,
                     ROUND(AVG(primary_score) FILTER (WHERE human_scored), 2)
                       AS judge_avg_primary,
                     ROUND(AVG(live_primary_score) FILTER (
                       WHERE COALESCE(live_human_scored, false)
                     ), 2) AS live_avg_primary
                   FROM six_quotient_human_gold"""
            )
        except Exception as e:
            return {
                "status": "ok",
                "migration_278_or_279_required": True,
                "error": str(e)[:200],
            }
    return {"status": "ok", "track_counts": dict(row) if row else {}}


@router.get("/gold/live-stack/compare")
async def gold_live_stack_compare(request: Request, limit: int = 50):
    """Within-stem judge vs live scores (only rows with both scored)."""
    pool = _pool(request)
    limit = max(1, min(int(limit or 50), 100))
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """SELECT scenario_id, section, response_class,
                          primary_score AS judge_primary,
                          accuracy_score AS judge_accuracy,
                          naturalness_score AS judge_naturalness,
                          live_primary_score, live_accuracy_score,
                          live_naturalness_score, live_stack_run_id,
                          length(COALESCE(nate_response,'')) AS harness_chars,
                          length(COALESCE(nate_response_live,'')) AS live_chars
                   FROM six_quotient_human_gold
                   WHERE human_scored
                     AND COALESCE(live_human_scored, false) = true
                   ORDER BY section, scenario_id
                   LIMIT $1""",
                limit,
            )
        except Exception as e:
            raise HTTPException(503, f"compare unavailable: {e}") from e
    items = [dict(r) for r in rows]
    return {"status": "ok", "count": len(items), "items": items}


# ── D.14b evidence writers (κ + rater reliability) ──────────────────────────


class KappaIngestBody(BaseModel):
    """Precomputed judge ratings — offline / script path (no LLM in request)."""

    # Caller-supplied metadata (this path runs no LLM), but the default should
    # still name the currently-active judge, not a retired one.
    judge_id: str = "grok-judge-v5"
    ratings: Dict[str, Dict[str, int]]  # scenario_id -> {primary,accuracy,naturalness}
    min_items: int = Field(50, ge=1, le=200)
    notes: str = ""


@router.get("/gold/kappa/latest")
async def gold_kappa_latest(request: Request):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, judge_id, aggregate_kappa, kappa_method, n_items,
                      per_dimension_json, safety_veto_ok, safety_miss_count,
                      created_at
               FROM six_quotient_judge_kappa_evidence
               WHERE gold_locked = true
               ORDER BY created_at DESC LIMIT 1"""
        )
    if not row:
        return {"status": "ok", "evidence": None}
    ev = dict(row)
    if ev.get("created_at"):
        ev["created_at"] = ev["created_at"].isoformat()
    for k in ("per_dimension_json",):
        if isinstance(ev.get(k), str):
            try:
                ev[k] = json.loads(ev[k])
            except Exception:
                pass
    return {"status": "ok", "evidence": ev}


@router.post("/gold/kappa/ingest")
async def gold_kappa_ingest(
    body: KappaIngestBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Insert κ evidence from supplied judge ratings (writer #1, no LLM)."""
    from app.services.tier1_gold_evidence import (
        KAPPA_METHOD,
        compute_safety_veto,
        load_scored_gold,
        mean_per_dimension_kappa,
        persist_kappa_evidence,
    )

    pool = _pool(request)
    async with pool.acquire() as conn:
        try:
            items = await load_scored_gold(conn, min_items=body.min_items)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        judge_by: Dict[str, Dict[str, int]] = {}
        for sid, v in (body.ratings or {}).items():
            try:
                judge_by[str(sid)] = {
                    "primary": int(v["primary"]),
                    "accuracy": int(v["accuracy"]),
                    "naturalness": int(v["naturalness"]),
                }
            except Exception as e:
                raise HTTPException(422, f"bad rating for {sid}: {e}") from e
        paired_g, paired_j, used = [], [], []
        for g in items:
            sid = g["scenario_id"]
            j = judge_by.get(sid)
            if not j:
                continue
            for d in ("primary", "accuracy", "naturalness"):
                if j[d] < 0 or j[d] > 3:
                    raise HTTPException(422, f"{sid}.{d} out of range")
            paired_g.append(
                {
                    "primary": int(g["primary_score"]),
                    "accuracy": int(g["accuracy_score"]),
                    "naturalness": int(g["naturalness_score"]),
                }
            )
            paired_j.append(j)
            used.append(sid)
        if len(used) < body.min_items:
            raise HTTPException(
                409,
                f"only {len(used)} paired ratings; need ≥{body.min_items}",
            )
        agg, per = mean_per_dimension_kappa(paired_g, paired_j)
        ok, miss_n, miss_ids = compute_safety_veto(items, judge_by)
        eid = await persist_kappa_evidence(
            conn,
            judge_id=(body.judge_id or "grok-judge-v5")[:80],
            aggregate_kappa=agg,
            per_dimension=per,
            n_items=len(used),
            safety_veto_ok=ok,
            safety_miss_count=miss_n,
            safety_miss_ids=miss_ids,
            notes=(body.notes or f"ingest; misses={miss_ids}")[:2000],
        )
    return {
        "status": "ok",
        "evidence_id": eid,
        "kappa_method": KAPPA_METHOD,
        "aggregate_kappa": agg,
        "per_dimension": per,
        "n_items": len(used),
        "safety_veto_ok": ok,
        "safety_miss_count": miss_n,
        "safety_miss_ids": miss_ids,
    }


@router.get("/gold/kappa/jobs/latest")
async def gold_kappa_job_latest(request: Request):
    from app.services.tier1_kappa_job import latest_job

    job = latest_job()
    return {"status": "ok", "job": job}


@router.get("/gold/kappa/jobs/{job_id}")
async def gold_kappa_job_status(job_id: str, request: Request):
    from app.services.tier1_kappa_job import get_job

    job = get_job((job_id or "").strip())
    if not job:
        raise HTTPException(404, "kappa job not found (in-memory; lost on restart)")
    return {"status": "ok", "job": job}


@router.post("/gold/kappa/compute")
async def gold_kappa_compute(
    request: Request,
    admin: Dict = Depends(require_admin),
    min_items: int = 50,
    # TRUST_LEDGER.md Entry 6 — this path invokes _llm_judge live, which scores
    # with JUDGE_SYSTEM_PROMPT_V5 unconditionally; label must match reality.
    judge_id: str = "grok-judge-v5",
    limit: int = 0,
    async_mode: bool = True,
):
    """
    Writer #1 with live LLM judge (slow).
    Default async_mode=true → returns job_id; poll /gold/kappa/jobs/{id}.
    async_mode=false blocks (legacy / scripts). Prefer ingest + CLI for durability.
    """
    from app.services.tier1_kappa_job import start_kappa_job

    pool = _pool(request)
    app_state = request.app.state
    min_items = max(1, int(min_items or 50))

    if async_mode:
        # Preflight scored count so we fail fast before queueing.
        from app.services.tier1_gold_evidence import load_scored_gold

        async with pool.acquire() as conn:
            try:
                await load_scored_gold(conn, min_items=min_items)
            except ValueError as e:
                raise HTTPException(409, str(e)) from e
        out = await start_kappa_job(
            pool=pool,
            app_state=app_state,
            min_items=min_items,
            judge_id=judge_id,
            limit=limit,
        )
        if out.get("status") == "busy":
            raise HTTPException(
                409,
                f"kappa job already running: {out.get('job_id')}",
            )
        return out

    # Sync path (blocks request until all items judged)
    from app.services.six_quotient_auto_judge import _llm_judge
    from app.services.tier1_gold_evidence import (
        KAPPA_METHOD,
        compute_safety_veto,
        load_scored_gold,
        mean_per_dimension_kappa,
        persist_kappa_evidence,
    )

    async with pool.acquire() as conn:
        try:
            items = await load_scored_gold(conn, min_items=min_items)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        if limit and limit > 0:
            items = items[:limit]
        judge_by: Dict[str, Dict[str, int]] = {}
        for g in items:
            sid = g["scenario_id"]
            judged = await _llm_judge(
                app_state,
                scenario_id=sid,
                section=str(g.get("section") or ""),
                rubric_focus=str(g.get("response_class") or ""),
                client_says=str(g.get("client_says") or ""),
                response=str(g.get("nate_response") or ""),
                degraded_distractor=bool(g.get("is_degraded_distractor")),
            )
            if not judged:
                raise HTTPException(502, f"judge failed for {sid}")
            judge_by[sid] = {
                "primary": judged["primary"],
                "accuracy": judged["accuracy"],
                "naturalness": judged["naturalness"],
            }
        paired_g, paired_j, used = [], [], []
        for g in items:
            sid = g["scenario_id"]
            j = judge_by[sid]
            paired_g.append(
                {
                    "primary": int(g["primary_score"]),
                    "accuracy": int(g["accuracy_score"]),
                    "naturalness": int(g["naturalness_score"]),
                }
            )
            paired_j.append(j)
            used.append(sid)
        if len(used) < min_items:
            raise HTTPException(409, f"paired {len(used)} < min_items {min_items}")
        agg, per = mean_per_dimension_kappa(paired_g, paired_j)
        ok, miss_n, miss_ids = compute_safety_veto(items, judge_by)
        eid = await persist_kappa_evidence(
            conn,
            judge_id=(judge_id or "grok-judge-v5")[:80],
            aggregate_kappa=agg,
            per_dimension=per,
            n_items=len(used),
            safety_veto_ok=ok,
            safety_miss_count=miss_n,
            safety_miss_ids=miss_ids,
            notes=f"compute API sync; misses={miss_ids}",
        )
    return {
        "status": "ok",
        "mode": "sync",
        "evidence_id": eid,
        "kappa_method": KAPPA_METHOD,
        "aggregate_kappa": agg,
        "per_dimension": per,
        "n_items": len(used),
        "safety_veto_ok": ok,
        "safety_miss_count": miss_n,
        "safety_miss_ids": miss_ids,
    }


@router.post("/gold/recheck/session/start")
async def gold_recheck_session_start(
    request: Request,
    admin: Dict = Depends(require_admin),
    n_items: int = 15,
):
    """Start intra-rater recheck session (writer #2)."""
    from app.services.tier1_gold_evidence import MIN_RECHECK_ITEMS

    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    n_items = max(MIN_RECHECK_ITEMS, min(int(n_items or 15), 50))
    run_id = (
        f"gold_recheck_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
        f"{secrets.token_hex(3)}"
    )
    pool = _pool(request)
    async with pool.acquire() as conn:
        scored_n = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM six_quotient_human_gold WHERE human_scored"
            )
            or 0
        )
        if scored_n < n_items:
            raise HTTPException(
                409,
                f"only {scored_n} scored items; need ≥{n_items} before recheck",
            )
        await conn.execute(
            """INSERT INTO six_quotient_gold_admin_runs
               (run_id, purpose, rater_id, notes)
               VALUES ($1, $2, $3, $4)""",
            run_id,
            "intra_rater_recheck",
            rater[:64],
            f"n_items={n_items}",
        )
    return {
        "status": "ok",
        "run_id": run_id,
        "rater_id": rater,
        "kind": "intra_rater",
        "n_items": n_items,
        "min_items": MIN_RECHECK_ITEMS,
        "threshold": 0.70,
        "min_gap_days": RECHECK_MIN_GAP_DAYS,
        "min_item_latency_ms": MIN_ITEM_LATENCY_MS,
    }


@router.get("/gold/recheck/items")
async def gold_recheck_items(
    request: Request,
    run_id: str,
    n_items: int = 15,
):
    """Blind subset of already-scored gold (no prior scores exposed)."""
    from app.services.tier1_gold_evidence import MIN_RECHECK_ITEMS

    n_items = max(MIN_RECHECK_ITEMS, min(int(n_items or 15), 50))
    pool = _pool(request)
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT run_id, purpose FROM six_quotient_gold_admin_runs WHERE run_id = $1",
            run_id,
        )
        if not run:
            raise HTTPException(404, "recheck run not found")
        rows = await conn.fetch(
            """SELECT scenario_id, section, client_says, nate_response,
                      response_class, difficulty
               FROM six_quotient_human_gold
               WHERE human_scored = true
                 AND pairs_locked = true
                 AND COALESCE(nate_response, '') <> ''
                 AND nate_response NOT ILIKE '%DRY-RUN%'
               ORDER BY md5(scenario_id || COALESCE($1, ''))
               LIMIT $2""",
            run_id,
            n_items,
        )
    items = [
        {
            "scenario_id": r["scenario_id"],
            "section": r["section"],
            "client_says": r["client_says"],
            "response": r["nate_response"],
            "response_class": r["response_class"],
            "difficulty": r["difficulty"],
        }
        for r in rows
    ]
    return {"status": "ok", "run_id": run_id, "count": len(items), "items": items}


class RecheckScoreBody(BaseModel):
    scenario_id: str
    run_id: str
    primary: int = Field(..., ge=0, le=3)
    accuracy: int = Field(..., ge=0, le=3)
    naturalness: int = Field(..., ge=0, le=3)
    safety_veto: Optional[str] = None
    latency_ms: int = Field(..., ge=0)

    @field_validator("scenario_id", "run_id")
    @classmethod
    def _req(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("required")
        return v

    @field_validator("safety_veto")
    @classmethod
    def _veto(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if v not in ("ok", "fail"):
            raise ValueError("safety_veto must be ok|fail")
        return v


@router.post("/gold/recheck/score")
async def gold_recheck_score(
    body: RecheckScoreBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    latency_ms = _enforce_item_latency(body.latency_ms)
    pool = _pool(request)
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT run_id, rater_id, purpose FROM six_quotient_gold_admin_runs WHERE run_id = $1",
            body.run_id,
        )
        if not run:
            raise HTTPException(404, "recheck run not found")
        if (run["rater_id"] or "") != rater:
            raise HTTPException(403, "run belongs to a different rater")
        if "recheck" not in (run["purpose"] or ""):
            raise HTTPException(409, "run is not a recheck session")
        exists = await conn.fetchval(
            """SELECT 1 FROM six_quotient_human_gold
               WHERE scenario_id = $1 AND human_scored = true""",
            body.scenario_id,
        )
        if not exists:
            raise HTTPException(404, "scenario not in scored gold set")
        try:
            await conn.execute(
                """INSERT INTO six_quotient_gold_recheck_scores
                   (run_id, scenario_id, primary_score, accuracy_score,
                    naturalness_score, safety_veto, latency_ms, rater_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT (run_id, scenario_id) DO UPDATE SET
                     primary_score = EXCLUDED.primary_score,
                     accuracy_score = EXCLUDED.accuracy_score,
                     naturalness_score = EXCLUDED.naturalness_score,
                     safety_veto = EXCLUDED.safety_veto,
                     latency_ms = EXCLUDED.latency_ms,
                     scored_at = NOW()""",
                body.run_id,
                body.scenario_id,
                body.primary,
                body.accuracy,
                body.naturalness,
                body.safety_veto,
                latency_ms,
                rater[:64],
            )
        except Exception as e:
            logger.warning("recheck score persist: %s", e)
            raise HTTPException(
                500,
                "recheck table missing — apply migration 275",
            ) from e
        n = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM six_quotient_gold_recheck_scores WHERE run_id = $1",
                body.run_id,
            )
            or 0
        )
    return {"status": "ok", "scenario_id": body.scenario_id, "recheck_count": n}


@router.post("/gold/recheck/finalize")
async def gold_recheck_finalize(
    request: Request,
    admin: Dict = Depends(require_admin),
    run_id: str = "",
):
    """Writer #2: compute QWK vs original scores → gold_rater_reliability."""
    from app.services.tier1_gold_evidence import (
        DEFAULT_REL_THR,
        MIN_RECHECK_ITEMS,
        mean_per_dimension_kappa,
        persist_rater_reliability,
    )

    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    run_id = (run_id or "").strip()
    if not run_id:
        raise HTTPException(422, "run_id required")
    pool = _pool(request)
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT run_id, rater_id, purpose FROM six_quotient_gold_admin_runs WHERE run_id = $1",
            run_id,
        )
        if not run:
            raise HTTPException(404, "recheck run not found")
        if (run["rater_id"] or "") != rater:
            raise HTTPException(403, "run belongs to a different rater")
        rechecks = await conn.fetch(
            """SELECT scenario_id, primary_score, accuracy_score, naturalness_score
               FROM six_quotient_gold_recheck_scores WHERE run_id = $1
               ORDER BY scenario_id""",
            run_id,
        )
        if len(rechecks) < MIN_RECHECK_ITEMS:
            raise HTTPException(
                409,
                f"only {len(rechecks)} recheck scores; need ≥{MIN_RECHECK_ITEMS}",
            )
        sids = [r["scenario_id"] for r in rechecks]
        golds = await conn.fetch(
            """SELECT scenario_id, primary_score, accuracy_score, naturalness_score,
                      scored_at
               FROM six_quotient_human_gold
               WHERE scenario_id = ANY($1::text[]) AND human_scored = true""",
            sids,
        )
        gmap = {r["scenario_id"]: r for r in golds}
        if RECHECK_MIN_GAP_DAYS > 0:
            too_soon = []
            for sid in sids:
                g = gmap.get(sid)
                if not g or g["scored_at"] is None:
                    too_soon.append(sid)
                    continue
                age = datetime.now(timezone.utc) - g["scored_at"].astimezone(timezone.utc)
                if age.total_seconds() < RECHECK_MIN_GAP_DAYS * 86400:
                    too_soon.append(sid)
            if too_soon:
                raise HTTPException(
                    409,
                    f"intra-rater gap < {RECHECK_MIN_GAP_DAYS}d for "
                    f"{len(too_soon)} item(s); wait before finalize "
                    f"(set TIER1_RECHECK_MIN_GAP_DAYS=0 only for ops override)",
                )
        paired_g, paired_r, used = [], [], []
        for r in rechecks:
            g = gmap.get(r["scenario_id"])
            if not g:
                continue
            paired_g.append(
                {
                    "primary": int(g["primary_score"]),
                    "accuracy": int(g["accuracy_score"]),
                    "naturalness": int(g["naturalness_score"]),
                }
            )
            paired_r.append(
                {
                    "primary": int(r["primary_score"]),
                    "accuracy": int(r["accuracy_score"]),
                    "naturalness": int(r["naturalness_score"]),
                }
            )
            used.append(r["scenario_id"])
        if len(used) < MIN_RECHECK_ITEMS:
            raise HTTPException(409, f"paired {len(used)} < {MIN_RECHECK_ITEMS}")
        agg, per = mean_per_dimension_kappa(paired_g, paired_r)
        rid = await persist_rater_reliability(
            conn,
            kind="intra_rater",
            rater_a=rater,
            rater_b=None,
            n_items=len(used),
            metric_value=agg,
            subset_scenario_ids=used,
            threshold=DEFAULT_REL_THR,
            notes=f"run_id={run_id}; per={per}",
        )
        await conn.execute(
            """UPDATE six_quotient_gold_admin_runs
               SET finished_at = NOW() WHERE run_id = $1""",
            run_id,
        )
    return {
        "status": "ok",
        "reliability_id": rid,
        "kind": "intra_rater",
        "metric_value": agg,
        "per_dimension": per,
        "n_items": len(used),
        "threshold": DEFAULT_REL_THR,
        "meets_threshold": agg >= DEFAULT_REL_THR and len(used) >= MIN_RECHECK_ITEMS,
        "subset_scenario_ids": used,
    }


@router.get("/gold/reliability/latest")
async def gold_reliability_latest(request: Request):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, kind, rater_a, rater_b, n_items, agreement_metric,
                      metric_value, meets_threshold, subset_scenario_ids,
                      created_at
               FROM six_quotient_gold_rater_reliability
               ORDER BY created_at DESC LIMIT 1"""
        )
    if not row:
        return {"status": "ok", "reliability": None}
    rel = dict(row)
    if rel.get("created_at"):
        rel["created_at"] = rel["created_at"].isoformat()
    return {"status": "ok", "reliability": rel}


# ── Library ─────────────────────────────────────────────────────────────────


@router.get("/library")
async def library_list(
    request: Request,
    status: Optional[str] = None,
    section: Optional[str] = None,
    limit: int = 100,
):
    pool = _pool(request)
    limit = max(1, min(int(limit or 100), 500))
    clauses = ["1=1"]
    args: List[Any] = []
    if status:
        args.append(status.strip())
        clauses.append(f"status = ${len(args)}")
    if section:
        args.append(section.strip())
        clauses.append(f"section = ${len(args)}")
    args.append(limit)
    where = " AND ".join(clauses)
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                f"""SELECT id::text, topic, section, client_says,
                           principal_response, nate_response, source_kind,
                           source_ref, tags, status, promoted_crystal_id::text,
                           created_by, created_at, updated_at, metadata
                    FROM principal_review_library
                    WHERE {where}
                    ORDER BY updated_at DESC
                    LIMIT ${len(args)}""",
                *args,
            )
        except Exception as e:
            if "does not exist" in str(e).lower():
                raise HTTPException(
                    503,
                    "principal_review_library missing — apply migration 274",
                ) from e
            raise
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()
        if isinstance(d.get("metadata"), str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                d["metadata"] = {}
        out.append(d)
    return {"status": "ok", "count": len(out), "items": out}


class LibraryCreateBody(BaseModel):
    topic: str = ""
    section: str = "general"
    client_says: str
    principal_response: str = ""
    nate_response: str = ""
    source_kind: str = "principal_authored"
    source_ref: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    status: str = "draft"


@router.post("/library")
async def library_create(
    body: LibraryCreateBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    if not (body.client_says or "").strip():
        raise HTTPException(422, "client_says required")
    rater = _rater(admin) or "DrNevedal1"
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO principal_review_library
               (topic, section, client_says, principal_response, nate_response,
                source_kind, source_ref, tags, status, created_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               RETURNING id::text""",
            (body.topic or "")[:200],
            (body.section or "general")[:40],
            body.client_says[:8000],
            (body.principal_response or "")[:8000],
            (body.nate_response or "")[:8000],
            (body.source_kind or "principal_authored")[:40],
            (body.source_ref or None),
            [t[:64] for t in (body.tags or [])[:20]],
            (body.status or "draft")[:20],
            rater[:64],
        )
    return {"status": "ok", "id": row["id"]}


class LibraryUpdateBody(BaseModel):
    topic: Optional[str] = None
    principal_response: Optional[str] = None
    nate_response: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None


@router.patch("/library/{item_id}")
async def library_update(
    item_id: str,
    body: LibraryUpdateBody,
    request: Request,
):
    pool = _pool(request)
    sets = ["updated_at = NOW()"]
    args: List[Any] = []
    for col, val in (
        ("topic", body.topic),
        ("principal_response", body.principal_response),
        ("nate_response", body.nate_response),
        ("status", body.status),
    ):
        if val is not None:
            args.append(val)
            sets.append(f"{col} = ${len(args)}")
    if body.tags is not None:
        args.append([t[:64] for t in body.tags[:20]])
        sets.append(f"tags = ${len(args)}")
    if len(args) == 0:
        raise HTTPException(422, "no fields to update")
    args.append(item_id)
    async with pool.acquire() as conn:
        status = await conn.execute(
            f"""UPDATE principal_review_library
               SET {', '.join(sets)}
               WHERE id = ${len(args)}::uuid""",
            *args,
        )
    if status.endswith("0"):
        raise HTTPException(404, "library item not found")
    return {"status": "ok", "id": item_id}


class GenerateNateBody(BaseModel):
    client_says: str
    principal_guidance: str = ""
    section: str = "clinical"


@router.post("/library/generate-nate")
async def library_generate_nate(
    body: GenerateNateBody,
    request: Request,
):
    """Safe therapeutic draft for Principal to edit — not auto-promoted."""
    if not (body.client_says or "").strip():
        raise HTTPException(422, "client_says required")
    router_svc = getattr(request.app.state, "nate_inference_router", None)
    if not router_svc or not hasattr(router_svc, "generate"):
        raise HTTPException(503, "nate_inference_router unavailable")
    system = (
        "You are Little Nate drafting a therapeutic reply for Principal Review. "
        "Speak in first person only — never narrate Nate's eyes/voice/body in "
        "third person, never stage directions. Be present, clinically sound, "
        "no fabrication, no chatbot clichés. If SI/HI risk is present include "
        "988 / Crisis Text. Do not claim memories you do not have. "
        "Aim for enough length to discharge obligations (roughly 150–400 words "
        "when crisis/safety work is needed)."
    )
    if body.principal_guidance.strip():
        system += (
            f"\nPrincipal guidance to honor (adapt — never copy verbatim):\n"
            f"{body.principal_guidance[:1500]}\n{_ANTI_VERBATIM_RULE}"
        )
    try:
        result = await router_svc.generate(
            prompt=body.client_says[:4000],
            system=system,
            domain="clinical",
            max_tokens=700,
            temperature=0.35,
        )
        text = (
            result.get("text")
            if isinstance(result, dict)
            else (result or "")
        )
        if isinstance(result, dict) and not text:
            text = result.get("response") or result.get("content") or ""
        text = (text or "").strip()
    except Exception as e:
        logger.warning("principal_review generate-nate: %s", e)
        raise HTTPException(502, f"generation failed: {e}") from e
    if not text:
        raise HTTPException(502, "empty generation")
    return {
        "status": "ok",
        "nate_response": text,
        "provider": (result.get("provider") if isinstance(result, dict) else None),
    }


async def _promote_library_item(
    request: Request,
    item_id: str,
    *,
    rater: str = "DrNevedal1",
) -> Dict[str, Any]:
    """Promote library row → crystal. Prefer Principal Guide over blind Nate."""
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT l.*, g.response_class AS gold_response_class
               FROM principal_review_library l
               LEFT JOIN six_quotient_human_gold g
                 ON l.source_kind = 'gold_scored' AND g.scenario_id = l.source_ref
               WHERE l.id = $1::uuid""",
            item_id,
        )
        if not row:
            raise HTTPException(404, "library item not found")
        if row["status"] == "archived":
            raise HTTPException(409, "archived items cannot be promoted")
        crystal_text = _build_principal_crystal_text(row)
        if not crystal_text:
            raise HTTPException(422, "need principal_response or nate_response")

        def _cell(key: str) -> str:
            try:
                v = row[key]
            except (KeyError, IndexError):
                return ""
            return ("" if v is None else str(v)).strip()

        resp_class = (_cell("response_class") or _cell("gold_response_class")).lower()
        source_scenario = (_cell("source_scenario") or _cell("source_ref"))[:80]
        prev_id = _cell("promoted_crystal_id")
        topics = [
            "principal_review",
            str(row["section"] or "clinical")[:40],
        ]
        if resp_class:
            topics.append(f"class:{resp_class}")

        content_hash = __import__("hashlib").sha256(
            crystal_text.encode("utf-8")
        ).hexdigest()
        crystal_id = await conn.fetchval(
            """INSERT INTO nate_intelligence_crystals
               (crystal_text, domain, scope, topics, source_count,
                confidence, content_hash, origin_surface)
               VALUES ($1, 'clinical', 'global', $2, 1,
                       0.72, $3, 'principal_review')
               ON CONFLICT (content_hash) DO NOTHING
               RETURNING id""",
            crystal_text[:8000],
            topics,
            content_hash,
        )
        if not crystal_id:
            crystal_id = await conn.fetchval(
                """SELECT id FROM nate_intelligence_crystals
                   WHERE content_hash = $1 LIMIT 1""",
                content_hash,
            )
        if (
            prev_id
            and crystal_id
            and str(prev_id) != str(crystal_id)
        ):
            try:
                await conn.execute(
                    """UPDATE nate_intelligence_crystals
                       SET superseded_by = $2, scope = 'archived', updated_at = NOW()
                       WHERE id = $1::bigint
                         AND origin_surface = 'principal_review'
                         AND superseded_by IS NULL""",
                    int(prev_id),
                    int(crystal_id),
                )
            except Exception as e:
                logger.warning("principal_review supersede %s→%s: %s", prev_id, crystal_id, e)

        await conn.execute(
            """UPDATE principal_review_library
               SET status = 'promoted',
                   promoted_crystal_id = $2,
                   response_class = COALESCE(NULLIF($3, ''), response_class),
                   source_scenario = COALESCE(NULLIF($4, ''), source_scenario),
                   promoted_by = $5,
                   updated_at = NOW()
               WHERE id = $1::uuid""",
            item_id,
            str(crystal_id) if crystal_id is not None else None,
            resp_class,
            source_scenario,
            (rater or "DrNevedal1")[:64],
        )

    try:
        crystallizer = getattr(request.app.state, "nate_memory_crystallizer", None)
        if crystallizer and hasattr(crystallizer, "_harvest_buffer"):
            crystallizer._harvest_buffer.append(
                {
                    "text": crystal_text[:2000],
                    "source": "principal_review",
                    "domain": "clinical",
                    "scope": "global",
                    "created_at": datetime.now(timezone.utc),
                }
            )
    except Exception as e:
        logger.warning("principal_review harvest: %s", e)

    try:
        from app.services.vectorize_service import index_wisdom, is_vectorize_configured

        if crystal_id and is_vectorize_configured():
            await index_wisdom(
                user_id="principal_review",
                wisdom_id=str(crystal_id),
                insight_type="principal_review_template",
                content=crystal_text[:4000],
                source="principal_review",
                domain="clinical",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
    except Exception as e:
        logger.warning("principal_review vectorize: %s", e)

    ns_id = None
    try:
        from app.services.night_school_director import WisdomCategory

        ns = getattr(request.app.state, "night_school", None) or getattr(
            request.app.state, "night_school_director", None
        )
        if ns and hasattr(ns, "add_wisdom_entry"):
            cat = (
                WisdomCategory.CRISIS_INTERVENTION
                if resp_class == "escalate_or_safety"
                else WisdomCategory.GENERAL
            )
            entry = ns.add_wisdom_entry(
                crystal_text[:4000],
                cat,
                "principal_review",
                source_file=f"pr_lib_{item_id}",
                confidence=0.72,
                auto_approve=True,
                approved_by=(rater or "DrNevedal1")[:64],
                tags=["principal_review", "principal_guide"],
            )
            ns_id = getattr(entry, "id", None)
    except Exception as e:
        logger.warning("principal_review night_school: %s", e)

    return {
        "status": "ok",
        "id": item_id,
        "crystal_id": str(crystal_id) if crystal_id else None,
        "night_school_id": ns_id,
        "teaching_source": (
            "principal_guide"
            if (row["principal_response"] or "").strip()
            else "nate_fallback"
        ),
    }


@router.post("/library/{item_id}/promote")
async def library_promote(
    item_id: str,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Promote approved template → crystal + harvest buffer (+ optional Night School)."""
    rater = _rater(admin) or "DrNevedal1"
    return await _promote_library_item(request, item_id, rater=rater)


# ── Coach DOJO share queue (bridge JSON) ─────────────────────────────────────


def _load_coach_queue() -> List[Dict[str, Any]]:
    for p in _BRIDGE_QUEUE_CANDIDATES:
        if not p or str(p) in ("", "."):
            continue
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    return data["items"]
        except Exception as e:
            logger.warning("principal_review coach queue read %s: %s", p, e)
    return []


@router.get("/coach-shares")
async def coach_shares(limit: int = 50):
    items = _load_coach_queue()
    # Newest pending first when timestamps exist
    def _key(it: Dict[str, Any]):
        return str(it.get("created_at") or it.get("timestamp") or "")

    items = sorted(items, key=_key, reverse=True)[: max(1, min(limit, 200))]
    # Strip oversized raw blobs for list view
    slim = []
    for it in items:
        slim.append(
            {
                "id": it.get("id") or it.get("entry_id") or it.get("filename"),
                "status": it.get("status"),
                "category": it.get("category"),
                "source": it.get("source"),
                "dojo_persona": it.get("dojo_persona"),
                "content": (it.get("content") or "")[:1500],
                "coach": it.get("coach") or it.get("username") or it.get("coach_id"),
                "created_at": it.get("created_at") or it.get("timestamp"),
            }
        )
    return {
        "status": "ok",
        "count": len(slim),
        "items": slim,
        "queue_reachable": bool(_load_coach_queue() or slim),
    }


class IngestCoachShareBody(BaseModel):
    queue_id: str
    topic: str = ""
    principal_response: str = ""
    promote: bool = False


@router.post("/coach-shares/ingest")
async def coach_shares_ingest(
    body: IngestCoachShareBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Pull a coach DOJO share into the Principal-Review library."""
    rater = _rater(admin) or "DrNevedal1"
    items = _load_coach_queue()
    match = None
    for it in items:
        iid = str(it.get("id") or it.get("entry_id") or it.get("filename") or "")
        if iid == body.queue_id:
            match = it
            break
    if not match:
        raise HTTPException(404, "coach share not found in queue file")
    content = (match.get("content") or "").strip()
    raw = match.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    client_says = (
        (raw.get("prompt") if isinstance(raw, dict) else None)
        or content
        or "(coach dojo share)"
    )
    nate_part = ""
    if isinstance(raw, dict):
        nate_part = (raw.get("response") or raw.get("analysis") or "")[:8000]
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO principal_review_library
               (topic, section, client_says, principal_response, nate_response,
                source_kind, source_ref, tags, status, created_by, metadata)
               VALUES ($1,'coaching',$2,$3,$4,'coach_dojo',$5,
                       ARRAY['dojo','coach_share'],'approved',$6,$7::jsonb)
               RETURNING id::text""",
            (body.topic or match.get("dojo_persona") or "coach_dojo")[:200],
            str(client_says)[:8000],
            (body.principal_response or "")[:8000],
            nate_part or content[:8000],
            body.queue_id[:120],
            rater[:64],
            json.dumps(
                {
                    "coach": match.get("coach") or match.get("username"),
                    "category": match.get("category"),
                    "persona": match.get("dojo_persona"),
                }
            ),
        )
    lib_id = row["id"]
    if body.promote:
        # Re-enter promote path
        class _Req:
            app = request.app

        return await library_promote(lib_id, request, admin)
    return {"status": "ok", "id": lib_id, "source_kind": "coach_dojo"}
