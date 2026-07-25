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
_BRIDGE_QUEUE_CANDIDATES = (
    Path("/app/bridge_data/coach_learning_queue.json"),
    Path(os.getenv("COACH_LEARNING_QUEUE_FILE", "") or ""),
)


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
        "min_median_latency_ms": 45000,
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
                 )::int AS dry_run_placeholders
               FROM six_quotient_human_gold"""
        )
    return {"status": "ok", **dict(row or {})}


@router.get("/gold/items")
async def gold_items(
    request: Request,
    unscored_only: bool = True,
    limit: int = 50,
):
    """Blind worksheet rows — no distractor flag, no masterful_criteria, no arm."""
    pool = _pool(request)
    limit = max(1, min(int(limit or 50), 100))
    async with pool.acquire() as conn:
        # Exclude DRY-RUN battery placeholders — not scoreable gold.
        rows = await conn.fetch(
            f"""SELECT scenario_id, section, client_says, nate_response,
                       response_class, difficulty, human_scored, blinded
                FROM six_quotient_human_gold
                WHERE pairs_locked = true
                  AND COALESCE(nate_response, '') <> ''
                  AND nate_response NOT ILIKE '%DRY-RUN%'
                  AND nate_response NOT ILIKE '%Placeholder Nate reply%'
                  AND nate_response NOT ILIKE '%External scoring required%'
                  {"AND human_scored = false" if unscored_only else ""}
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
                "response": r["nate_response"],
                "response_class": r["response_class"],
                "difficulty": r["difficulty"],
                "human_scored": bool(r["human_scored"]),
                "blinded": bool(r["blinded"]),
            }
        )
    return {"status": "ok", "count": len(items), "items": items}


class GoldScoreBody(BaseModel):
    scenario_id: str
    run_id: str
    primary: int = Field(..., ge=0, le=3)
    accuracy: int = Field(..., ge=0, le=3)
    naturalness: int = Field(..., ge=0, le=3)
    safety_veto: Optional[str] = None
    notes: str = ""
    latency_ms: int = Field(..., ge=0)
    score_session_id: Optional[str] = None

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


@router.post("/gold/score")
async def gold_score(
    body: GoldScoreBody,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    rater = _rater(admin)
    if rater not in _ALLOWED_RATERS:
        raise HTTPException(403, f"rater_id {rater!r} not in allowlist")
    pool = _pool(request)
    session_id = (body.score_session_id or body.run_id)[:80]
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
            """SELECT scenario_id, pairs_locked, human_scored, nate_response
               FROM six_quotient_human_gold WHERE scenario_id = $1""",
            body.scenario_id,
        )
        if not locked:
            raise HTTPException(404, "scenario not in gold set")
        if not locked["pairs_locked"]:
            raise HTTPException(409, "pairs not locked — freeze gold before scoring")
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
            (body.notes or "")[:2000],
            rater[:64],
            body.run_id[:80],
            int(body.latency_ms),
            session_id,
        )
        # Mirror scored gold into library as draft for later promote
        meta = json.dumps(
            {
                "primary": body.primary,
                "accuracy": body.accuracy,
                "naturalness": body.naturalness,
                "safety_veto": body.safety_veto,
                "latency_ms": int(body.latency_ms),
            }
        )
        exists = await conn.fetchval(
            """SELECT id FROM principal_review_library
               WHERE source_kind = 'gold_scored' AND source_ref = $1""",
            body.scenario_id,
        )
        if exists:
            await conn.execute(
                """UPDATE principal_review_library SET
                     nate_response = (SELECT nate_response FROM six_quotient_human_gold WHERE scenario_id = $1),
                     metadata = $2::jsonb,
                     gold_admin_run_id = $3,
                     updated_at = NOW()
                   WHERE source_kind = 'gold_scored' AND source_ref = $1""",
                body.scenario_id,
                meta,
                body.run_id[:80],
            )
        else:
            await conn.execute(
                """INSERT INTO principal_review_library
                   (topic, section, client_says, principal_response, nate_response,
                    source_kind, source_ref, status, gold_admin_run_id, created_by, metadata)
                   SELECT
                     COALESCE(NULLIF(notes,''), scenario_id),
                     section, client_says, '', nate_response,
                     'gold_scored', scenario_id, 'draft', $2, $3, $4::jsonb
                   FROM six_quotient_human_gold WHERE scenario_id = $1""",
                body.scenario_id,
                body.run_id[:80],
                rater[:64],
                meta,
            )
    return {
        "status": "ok",
        "scenario_id": body.scenario_id,
        "score_entry_source": "authenticated_scoring_surface",
        "rater_id": rater,
        "latency_ms": body.latency_ms,
    }


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
        "Be present, clinically sound, no fabrication, no chatbot clichés. "
        "If SI/HI risk is present include 988 / Crisis Text. "
        "Do not claim memories you do not have. Keep under 220 words."
    )
    if body.principal_guidance.strip():
        system += f"\nPrincipal guidance to honor:\n{body.principal_guidance[:1500]}"
    try:
        result = await router_svc.generate(
            prompt=body.client_says[:4000],
            system=system,
            domain="clinical",
            max_tokens=500,
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


@router.post("/library/{item_id}/promote")
async def library_promote(
    item_id: str,
    request: Request,
    admin: Dict = Depends(require_admin),
):
    """Promote approved template → crystal + harvest buffer (+ optional Night School)."""
    rater = _rater(admin) or "DrNevedal1"
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM principal_review_library WHERE id = $1::uuid""",
            item_id,
        )
        if not row:
            raise HTTPException(404, "library item not found")
        if row["status"] == "archived":
            raise HTTPException(409, "archived items cannot be promoted")
        # Prefer principal answer as teaching gold; fall back to nate
        teaching = (row["principal_response"] or "").strip() or (
            row["nate_response"] or ""
        ).strip()
        if not teaching:
            raise HTTPException(422, "need principal_response or nate_response")
        crystal_text = (
            f"[Principal-Review · {row['section']} · {row['topic'] or row['source_ref'] or 'template'}]\n"
            f"Client: {(row['client_says'] or '')[:1200]}\n"
            f"Guide: {teaching[:2500]}"
        )
        if (row["nate_response"] or "").strip() and (row["principal_response"] or "").strip():
            crystal_text += f"\nNate draft: {(row['nate_response'] or '')[:1200]}"

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
            ["principal_review", str(row["section"] or "clinical")[:40]],
            content_hash,
        )
        if not crystal_id:
            crystal_id = await conn.fetchval(
                """SELECT id FROM nate_intelligence_crystals
                   WHERE content_hash = $1 LIMIT 1""",
                content_hash,
            )
        await conn.execute(
            """UPDATE principal_review_library
               SET status = 'promoted',
                   promoted_crystal_id = $2,
                   updated_at = NOW()
               WHERE id = $1::uuid""",
            item_id,
            crystal_id,
        )

    # Harvest buffer (outside transaction)
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

    # Night School optional absorb
    ns_id = None
    try:
        ns = getattr(request.app.state, "night_school", None) or getattr(
            request.app.state, "night_school_director", None
        )
        if ns and hasattr(ns, "add_wisdom_entry"):
            ns_id = await ns.add_wisdom_entry(
                content=crystal_text[:4000],
                source="principal_review",
                category="principal_guide",
                approved=True,
            )
    except Exception as e:
        logger.warning("principal_review night_school: %s", e)

    return {
        "status": "ok",
        "id": item_id,
        "crystal_id": str(crystal_id) if crystal_id else None,
        "night_school_id": ns_id,
    }


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
