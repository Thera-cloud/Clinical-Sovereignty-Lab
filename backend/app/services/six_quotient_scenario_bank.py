"""
Six-Quotient Scenario Bank — seed v4 anchors, list/approve, IRT updates.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.six_quotient_bank")

_QUOTIENTS = ("IQ", "EQ", "MQ", "SQ", "CQ", "AQ")

_PERSONA_BY_SECTION = {
    "AQ": "CRISIS",
    "EQ": "SKEPTIC",
    "MQ": "HOSTILE",
    "SQ": "HOSTILE",
    "CQ": "SKEPTIC",
    "IQ": "SKEPTIC",
}


def _v4_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[1] / "data" / "six_quotient_scenarios_v4.json",
        Path("/app/app/data/six_quotient_scenarios_v4.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def bank_row_to_scenario(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize DB row → battery scenario dict."""
    beats = row.get("client_beats") or []
    if isinstance(beats, str):
        try:
            beats = json.loads(beats)
        except Exception:
            beats = []
    return {
        "id": row.get("scenario_key") or row.get("id"),
        "scenario_key": row.get("scenario_key"),
        "section": row.get("section"),
        "title": row.get("title") or "",
        "rubric_focus": row.get("rubric_focus") or "",
        "client_says": row.get("client_says") or "",
        "client_beats": beats,
        "dojo_persona": row.get("dojo_persona") or "SKEPTIC",
        "irt_a": float(row.get("irt_a") or 1.0),
        "irt_b": float(row.get("irt_b") or 0.0),
        "difficulty_nominal": float(row.get("difficulty_nominal") or 0.5),
        "standards_refs": row.get("standards_refs") or [],
        "source": row.get("source") or "",
        "status": row.get("status") or "",
    }


async def seed_v4_anchors(db_pool) -> Dict[str, Any]:
    """Insert v4 pack as approved anchors if missing."""
    path = _v4_path()
    if not path.exists():
        return {"ok": False, "error": f"missing {path}"}
    pack = json.loads(path.read_text(encoding="utf-8"))
    scenarios = pack.get("scenarios") or []
    inserted = 0
    skipped = 0
    async with db_pool.acquire() as conn:
        for sc in scenarios:
            key = str(sc["id"])
            section = str(sc.get("section") or key.split("-")[0]).upper()
            # Nominal difficulty: AQ high, SQ/CQ mid-high
            nom = {"AQ": 0.85, "SQ": 0.7, "CQ": 0.65, "MQ": 0.6, "IQ": 0.55, "EQ": 0.5}.get(
                section, 0.5
            )
            irt_b = (nom - 0.5) * 2.0  # map to ~[-1,1+]
            try:
                status = await conn.execute(
                    """INSERT INTO six_quotient_scenario_bank
                       (scenario_key, section, title, rubric_focus, client_says,
                        client_beats, dojo_persona, difficulty_nominal, irt_a, irt_b,
                        status, source, provenance_json, approved_by, approved_at)
                       VALUES ($1,$2,$3,$4,$5,'[]'::jsonb,$6,$7,1.2,$8,
                               'approved','v4_anchor',$9::jsonb,'system_seed',NOW())
                       ON CONFLICT (scenario_key) DO NOTHING""",
                    key,
                    section,
                    sc.get("title") or "",
                    sc.get("rubric_focus") or "",
                    sc.get("client_says") or "",
                    _PERSONA_BY_SECTION.get(section, "SKEPTIC"),
                    nom,
                    irt_b,
                    json.dumps({"battery_version": pack.get("battery_version", "v4")}),
                )
                if status.endswith("1"):
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning("seed_v4 %s: %s", key, e)
    return {"ok": True, "inserted": inserted, "skipped": skipped, "total_pack": len(scenarios)}


def holdout_keys_deterministic(
    scenario_keys: List[str], *, fraction: float = 0.3
) -> List[str]:
    """Deterministic holdout: sorted keys, take every 3rd (~33%). Never empty-unmarks."""
    ordered = sorted({str(k) for k in scenario_keys if k})
    if not ordered:
        return []
    # every 3rd starting at index 2 ≈ fraction 0.33; honor fraction≈0.3
    step = 3 if fraction >= 0.25 else max(2, int(round(1.0 / max(fraction, 0.05))))
    picked = [k for i, k in enumerate(ordered) if i % step == (step - 1)]
    if len(ordered) >= 3 and not picked:
        picked = [ordered[2]]
    return picked


NIGHTLY_ROTATION_SQL = """
SELECT id::text, scenario_key, section, title, rubric_focus, client_says,
       client_beats, dojo_persona, difficulty_nominal, irt_a, irt_b,
       discrimination_n, status, source, provenance_json, standards_refs,
       safety_flags, times_administered, mean_total_score, pass_rate,
       approved_by, approved_at, created_at, held_out, last_measured_at
FROM six_quotient_scenario_bank
WHERE status = 'approved' AND COALESCE(held_out, FALSE) = FALSE
ORDER BY last_measured_at ASC NULLS FIRST, scenario_key
LIMIT $1
"""

TRANSFER_ROTATION_SQL = """
SELECT id::text, scenario_key, section, title, rubric_focus, client_says,
       client_beats, dojo_persona, difficulty_nominal, irt_a, irt_b,
       discrimination_n, status, source, provenance_json, standards_refs,
       safety_flags, times_administered, mean_total_score, pass_rate,
       approved_by, approved_at, created_at, held_out, last_measured_at
FROM six_quotient_scenario_bank
WHERE status = 'approved' AND COALESCE(held_out, FALSE) = TRUE
ORDER BY last_measured_at ASC NULLS FIRST, scenario_key
LIMIT $1
"""


async def list_bank(
    db_pool,
    *,
    status: Optional[str] = "approved",
    section: Optional[str] = None,
    limit: int = 200,
    include_held_out: bool = True,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 200), 500))
    clauses = ["TRUE"]
    args: List[Any] = []
    if status:
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    if section:
        args.append(section.upper())
        clauses.append(f"section = ${len(args)}")
    if not include_held_out:
        clauses.append("COALESCE(held_out, FALSE) = FALSE")
    args.append(limit)
    sql = f"""SELECT id::text, scenario_key, section, title, rubric_focus, client_says,
                     client_beats, dojo_persona, difficulty_nominal, irt_a, irt_b,
                     discrimination_n, status, source, provenance_json, standards_refs,
                     safety_flags, times_administered, mean_total_score, pass_rate,
                     approved_by, approved_at, created_at
              FROM six_quotient_scenario_bank
              WHERE {' AND '.join(clauses)}
              ORDER BY section, scenario_key
              LIMIT ${len(args)}"""
    async with db_pool.acquire() as conn:
        try:
            rows = await conn.fetch(sql, *args)
        except Exception:
            # Pre-migration 248: held_out filter may fail — retry without it
            if not include_held_out:
                return await list_bank(
                    db_pool, status=status, section=section, limit=limit, include_held_out=True
                )
            raise
    out = []
    for r in rows:
        d = dict(r)
        for k in ("approved_at", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        for k in ("client_beats", "provenance_json", "standards_refs", "safety_flags"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out


async def mark_holdout(
    db_pool,
    *,
    fraction: float = 0.3,
    environment: str = "production",
) -> Dict[str, Any]:
    """
    Deterministically mark ~30% of approved scenarios held_out=TRUE per section.
    Idempotent: never un-marks already-held-out rows (contamination guard).
    environment is accepted for API symmetry; holdout is bank-global.
    """
    _ = environment
    fraction = max(0.05, min(float(fraction or 0.3), 0.5))
    marked: List[str] = []
    skipped_already = 0
    per_section: Dict[str, int] = {}
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT scenario_key, section, COALESCE(held_out, FALSE) AS held_out
               FROM six_quotient_scenario_bank
               WHERE status = 'approved'
               ORDER BY section, scenario_key"""
        )
        by_sec: Dict[str, List[Any]] = {}
        for r in rows:
            by_sec.setdefault(str(r["section"]).upper(), []).append(r)
        for sec, items in by_sec.items():
            free = [r["scenario_key"] for r in items if not r["held_out"]]
            already = [r["scenario_key"] for r in items if r["held_out"]]
            skipped_already += len(already)
            if len(items) < 3:
                continue
            # Target: at least 1 held-out when ≥3 approved in section
            candidates = holdout_keys_deterministic(free, fraction=fraction)
            if not candidates and not already and len(items) >= 3:
                # Prefer keys that exist among free; fall back to every-3rd of all
                candidates = holdout_keys_deterministic(
                    [r["scenario_key"] for r in items if not r["held_out"]],
                    fraction=fraction,
                )
            for key in candidates:
                status = await conn.execute(
                    """UPDATE six_quotient_scenario_bank
                       SET held_out = TRUE, updated_at = NOW()
                       WHERE scenario_key = $1 AND COALESCE(held_out, FALSE) = FALSE""",
                    key,
                )
                if status.endswith("1"):
                    marked.append(key)
                    per_section[sec] = per_section.get(sec, 0) + 1
    return {
        "ok": True,
        "marked": marked,
        "marked_count": len(marked),
        "already_held_out": skipped_already,
        "per_section": per_section,
        "fraction": fraction,
    }


async def select_rotation(
    db_pool, *, held_out: bool = False, limit: int = 8
) -> List[Dict[str, Any]]:
    """Rotate by last_measured_at ASC NULLS FIRST."""
    limit = max(1, min(int(limit or 8), 24))
    sql = TRANSFER_ROTATION_SQL if held_out else NIGHTLY_ROTATION_SQL
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(sql, limit)
    return [dict(r) for r in rows]


async def touch_last_measured(db_pool, scenario_keys: List[str]) -> int:
    if not scenario_keys:
        return 0
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE six_quotient_scenario_bank
               SET last_measured_at = NOW(), updated_at = NOW()
               WHERE scenario_key = ANY($1::text[])""",
            list(scenario_keys),
        )
    return len(scenario_keys)


async def insert_theta_trend(
    db_pool,
    *,
    environment: str,
    run_id: Optional[str],
    run_kind: str,
    theta: float,
    theta_by_section: Dict[str, Any],
    scenario_count: int = 0,
    seen_theta: Optional[float] = None,
    held_out_theta: Optional[float] = None,
    is_smoke: bool = False,
) -> None:
    async with db_pool.acquire() as conn:
        try:
            await conn.execute(
                """INSERT INTO six_quotient_theta_trend
                   (environment, run_id, run_kind, theta, theta_by_section,
                    seen_theta, held_out_theta, scenario_count, is_smoke)
                   VALUES ($1, $2::uuid, $3, $4, $5::jsonb, $6, $7, $8, $9)""",
                environment,
                run_id,
                run_kind,
                float(theta),
                json.dumps(theta_by_section or {}),
                seen_theta,
                held_out_theta,
                int(scenario_count or 0),
                bool(is_smoke),
            )
        except Exception:
            # Pre-migration 251: no is_smoke column
            await conn.execute(
                """INSERT INTO six_quotient_theta_trend
                   (environment, run_id, run_kind, theta, theta_by_section,
                    seen_theta, held_out_theta, scenario_count)
                   VALUES ($1, $2::uuid, $3, $4, $5::jsonb, $6, $7, $8)""",
                environment,
                run_id,
                run_kind,
                float(theta),
                json.dumps(theta_by_section or {}),
                seen_theta,
                held_out_theta,
                int(scenario_count or 0),
            )


async def latest_transfer_delta(db_pool, environment: str) -> Dict[str, Any]:
    """Latest transfer trend row for gap_summary enrichment."""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT seen_theta, held_out_theta, run_id::text, created_at
                   FROM six_quotient_theta_trend
                   WHERE environment = $1 AND run_kind = 'transfer'
                   ORDER BY created_at DESC LIMIT 1""",
                environment,
            )
    except Exception:
        return {}
    if not row:
        return {}
    seen = row["seen_theta"]
    held = row["held_out_theta"]
    delta = None
    if seen is not None and held is not None:
        delta = float(held) - float(seen)
    return {
        "seen_theta": float(seen) if seen is not None else None,
        "held_out_theta": float(held) if held is not None else None,
        "transfer_delta": delta,
        "run_id": row["run_id"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


async def insert_draft(db_pool, scenario: Dict[str, Any]) -> Optional[str]:
    key = scenario.get("scenario_key") or f"v5-{scenario.get('section', 'XX')}-{uuid.uuid4().hex[:8]}"
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO six_quotient_scenario_bank
               (scenario_key, section, title, rubric_focus, client_says, client_beats,
                dojo_persona, difficulty_nominal, irt_a, irt_b, status, source,
                provenance_json, standards_refs, safety_flags)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12,$13::jsonb,
                       $14::jsonb,$15::jsonb)
               ON CONFLICT (scenario_key) DO UPDATE SET
                 title = EXCLUDED.title,
                 rubric_focus = EXCLUDED.rubric_focus,
                 client_says = EXCLUDED.client_says,
                 client_beats = EXCLUDED.client_beats,
                 safety_flags = EXCLUDED.safety_flags,
                 updated_at = NOW()""",
            key,
            str(scenario.get("section", "")).upper(),
            scenario.get("title") or "",
            scenario.get("rubric_focus") or "",
            scenario.get("client_says") or "",
            json.dumps(scenario.get("client_beats") or []),
            scenario.get("dojo_persona") or "SKEPTIC",
            float(scenario.get("difficulty_nominal") or 0.7),
            float(scenario.get("irt_a") or 1.0),
            float(scenario.get("irt_b") or 0.5),
            scenario.get("status") or "pending_review",
            scenario.get("source") or "generated",
            json.dumps(scenario.get("provenance_json") or {}),
            json.dumps(scenario.get("standards_refs") or []),
            json.dumps(scenario.get("safety_flags") or []),
        )
    return key


async def approve_scenario(
    db_pool, scenario_key: str, approved_by: str
) -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE six_quotient_scenario_bank
               SET status = 'approved', approved_by = $2, approved_at = NOW(),
                   updated_at = NOW()
               WHERE scenario_key = $1 AND status IN ('draft', 'pending_review')
               RETURNING scenario_key, status""",
            scenario_key,
            (approved_by or "").strip() or "admin",
        )
    if not row:
        return {"ok": False, "error": "not found or not approvable"}
    return {"ok": True, "scenario_key": row["scenario_key"], "status": row["status"]}


async def record_administration(
    db_pool,
    scenario_key: str,
    total_score: Optional[float],
) -> None:
    """Bump times_administered; optionally update mean/pass_rate."""
    try:
        async with db_pool.acquire() as conn:
            if total_score is None:
                await conn.execute(
                    """UPDATE six_quotient_scenario_bank
                       SET times_administered = times_administered + 1,
                           updated_at = NOW()
                       WHERE scenario_key = $1""",
                    scenario_key,
                )
                return
            await conn.execute(
                """UPDATE six_quotient_scenario_bank
                   SET times_administered = times_administered + 1,
                       mean_total_score = CASE
                         WHEN mean_total_score IS NULL THEN $2::real
                         ELSE (mean_total_score * times_administered + $2::real)
                              / (times_administered + 1)
                       END,
                       pass_rate = CASE
                         WHEN pass_rate IS NULL THEN
                           CASE WHEN $2::real >= 6 THEN 1.0 ELSE 0.0 END
                         ELSE (pass_rate * times_administered
                               + CASE WHEN $2::real >= 6 THEN 1.0 ELSE 0.0 END)
                              / (times_administered + 1)
                       END,
                       updated_at = NOW()
                   WHERE scenario_key = $1""",
                scenario_key,
                float(total_score),
            )
    except Exception as e:
        logger.warning("record_administration %s: %s", scenario_key, e)


async def update_irt(
    db_pool, scenario_key: str, irt_a: float, irt_b: float, n: int
) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE six_quotient_scenario_bank
               SET irt_a = $2, irt_b = $3, discrimination_n = $4, updated_at = NOW()
               WHERE scenario_key = $1""",
            scenario_key,
            float(irt_a),
            float(irt_b),
            int(n),
        )


async def get_ability(db_pool, environment: str = "staging") -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """SELECT environment, theta, theta_by_section, last_run_id::text, updated_at,
                          COALESCE(live_focus, '{}'::jsonb) AS live_focus
                   FROM six_quotient_ability_state WHERE environment = $1""",
                environment,
            )
        except Exception:
            # Pre-migration 247: live_focus column absent
            row = await conn.fetchrow(
                """SELECT environment, theta, theta_by_section, last_run_id::text, updated_at
                   FROM six_quotient_ability_state WHERE environment = $1""",
                environment,
            )
    if not row:
        return {
            "environment": environment,
            "theta": 0.0,
            "theta_by_section": {q: 0.0 for q in _QUOTIENTS},
            "last_run_id": None,
            "live_focus": {},
        }
    d = dict(row)
    tbs = d.get("theta_by_section") or {}
    if isinstance(tbs, str):
        try:
            tbs = json.loads(tbs)
        except Exception:
            tbs = {}
    d["theta_by_section"] = tbs
    focus = d.get("live_focus") or {}
    if isinstance(focus, str):
        try:
            focus = json.loads(focus)
        except Exception:
            focus = {}
    d["live_focus"] = focus if isinstance(focus, dict) else {}
    if d.get("updated_at"):
        d["updated_at"] = d["updated_at"].isoformat()
    return d


async def set_ability(
    db_pool,
    environment: str,
    theta: float,
    theta_by_section: Dict[str, float],
    last_run_id: Optional[str] = None,
) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO six_quotient_ability_state
               (environment, theta, theta_by_section, last_run_id, updated_at)
               VALUES ($1, $2, $3::jsonb, $4::uuid, NOW())
               ON CONFLICT (environment) DO UPDATE SET
                 theta = EXCLUDED.theta,
                 theta_by_section = EXCLUDED.theta_by_section,
                 last_run_id = COALESCE(EXCLUDED.last_run_id, six_quotient_ability_state.last_run_id),
                 updated_at = NOW()""",
            environment,
            float(theta),
            json.dumps(theta_by_section or {}),
            last_run_id,
        )
