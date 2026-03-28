"""
SOVEREIGN SWARM — Coherence API Router
REST endpoints for the 5-layer coherence engine, The Pulse dashboard,
and Family Sanctuary emotional weather longitudinal data.
Phase 2C.  Includes client-facing /report/{hw_id} for the Coherence Dashboard.
"""

import json
import logging
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional

from app.auth import get_current_user_id
from app.services.api_server import require_admin, get_current_user

logger = logging.getLogger("coherence_api")

router = APIRouter(prefix="/api/coherence", tags=["coherence"])

_DATA_ROOT = Path(os.environ.get("DATA_DIR", "/app/data"))
_VAULT_ROOT = _DATA_ROOT / "Vaults" / "Clients"


def _get_db_pool(request: Request):
    """Get database pool from app state."""
    return request.app.state.db_pool


@router.get("/pulse", dependencies=[Depends(require_admin)])
async def get_pulse(request: Request):
    """
    Aggregated Pulse dashboard data:
    global coherence index, layer scores, trending themes, gap analysis, alerts.
    """
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        snapshot = await engine.generate_pulse_snapshot()
        return {
            "global_coherence_index": snapshot.global_coherence_index,
            "layer_scores": snapshot.layer_scores,
            "trending_themes": snapshot.trending_themes,
            "gap_analysis": snapshot.gap_analysis.model_dump() if snapshot.gap_analysis else None,
            "active_alerts": snapshot.active_alerts,
            "notable_changes": snapshot.notable_changes,
            "generated_at": snapshot.generated_at.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pulse generation error: {e}")


@router.get("/layer/{layer}", dependencies=[Depends(require_admin)])
async def get_layer_detail(layer: str, request: Request):
    """Detailed coherence data for a specific layer."""
    from app.services.coherence_engine import CoherenceEngine
    from app.models.coherence import CoherenceLayer

    valid_layers = [l.value for l in CoherenceLayer]
    if layer not in valid_layers:
        raise HTTPException(status_code=400, detail=f"Invalid layer. Choose from: {valid_layers}")

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT measurement_id, score, confidence, components,
                       delta_24h, delta_7d, sample_size, measured_at
                FROM coherence_measurements
                WHERE layer = $1
                ORDER BY measured_at DESC
                LIMIT 50
            """, layer)

            measurements = []
            for r in rows:
                measurements.append({
                    "measurement_id": str(r["measurement_id"]),
                    "score": r["score"],
                    "confidence": r["confidence"],
                    "components": r["components"] if isinstance(r["components"], dict)
                                  else __import__("json").loads(r["components"]) if r["components"] else {},
                    "delta_24h": r["delta_24h"],
                    "delta_7d": r["delta_7d"],
                    "sample_size": r["sample_size"],
                    "measured_at": r["measured_at"].isoformat(),
                })

            return {
                "layer": layer,
                "measurements": measurements,
                "count": len(measurements),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Layer query error: {e}")


@router.get("/gap", dependencies=[Depends(require_admin)])
async def get_gap_analysis(request: Request):
    """Inside/outside coherence gap analysis."""
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        gap = await engine.compute_gap_analysis()
        return gap.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gap analysis error: {e}")


@router.get("/individual/{user_id}")
async def measure_individual(user_id: UUID, request: Request, current_user: str = Depends(get_current_user_id)):
    """Measure individual coherence for a specific user. Requires authentication; user must be requesting their own data."""
    if current_user != str(user_id):
        raise HTTPException(status_code=403, detail="Access denied: you can only view your own coherence data")

    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        measurement = await engine.measure_individual(user_id)
        return measurement.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Individual coherence error: {e}")


@router.get("/family/{family_id}")
async def measure_family(family_id: UUID, request: Request, current_user: str = Depends(get_current_user_id)):
    """Measure family system coherence. Requires authentication; user must belong to the family."""
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    # Verify family membership
    try:
        async with db_pool.acquire() as conn:
            member = await conn.fetchval(
                "SELECT 1 FROM family_members WHERE family_id = $1 AND user_id = $2::uuid LIMIT 1",
                family_id, current_user,
            )
            if not member:
                raise HTTPException(status_code=403, detail="Access denied: you are not a member of this family")
    except HTTPException:
        raise
    except Exception:
        pass  # Table may not exist yet; allow through

    try:
        measurement = await engine.measure_family(family_id)
        return measurement.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Family coherence error: {e}")


@router.get("/briefing", dependencies=[Depends(require_admin)])
async def get_coherence_briefing(request: Request):
    """Generate or retrieve the latest coherence briefing."""
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        briefing = await engine.generate_briefing()
        return briefing
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Briefing error: {e}")


@router.get("/report/{hw_id}", dependencies=[Depends(get_current_user)])
async def get_client_coherence_report(
    hw_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """
    Client-facing Coherence Dashboard report.
    Returns current metrics, trend history, CEE experiences, drift periods,
    reply therapy state, mood history.
    Primary source: PostgreSQL nevedal_metrics. Fallback: JSON file.
    Auth: Any authenticated user. Clients may only view their own report.
    """
    caller_role = user.get("role", "")
    caller_hw = user.get("hardware_id", "")
    if caller_role == "CLIENT" and caller_hw != hw_id:
        raise HTTPException(status_code=403, detail="Access denied: you may only view your own coherence report")
    db_pool = _get_db_pool(request)

    # Try PostgreSQL first
    pg_history = []
    pg_current = {}
    if db_pool:
        try:
            pg_history, pg_current = await _load_coherence_from_pg(
                db_pool, hw_id, date_from, date_to
            )
        except Exception:
            pass

    if pg_history:
        return _build_report_from_pg(pg_history, pg_current, date_from, date_to)

    # Fallback to JSON file if PostgreSQL returned nothing
    metrics_path = _VAULT_ROOT / hw_id / "metrics.json"
    if not metrics_path.exists():
        return {
            "current": {}, "trends": {}, "history": [],
            "cee_experiences": [], "drift_periods": [],
            "reply_therapy": {}, "mood_history": [], "cee_total": 0,
        }

    try:
        raw = metrics_path.read_text()
        metrics = json.loads(raw) if raw.strip() else {}
    except Exception:
        raise HTTPException(500, "Failed to read metrics")

    ns = metrics.get("nevedal_state", {})
    history = metrics.get("history", [])
    mood_hist = ns.get("mood_history", [])

    if date_from or date_to:
        filtered = []
        for h in history:
            ts = h.get("timestamp", "")
            if ts:
                d = ts[:10]
                if date_from and d < date_from:
                    continue
                if date_to and d > date_to:
                    continue
            filtered.append(h)
        history = filtered

    cemo_vals = [h["C_emo"] for h in history if isinstance(h.get("C_emo"), (int, float))]
    gap_vals = [h["GAP"] for h in history if isinstance(h.get("GAP"), (int, float))]
    quantum_vals = [h["Quantum"] for h in history if isinstance(h.get("Quantum"), (int, float))]

    def _trend(vals):
        if len(vals) < 4:
            return "not_enough_data"
        half = len(vals) // 2
        first = sum(vals[:half]) / half
        second = sum(vals[half:]) / (len(vals) - half)
        if second > first + 0.03:
            return "improving"
        elif second < first - 0.03:
            return "declining"
        return "stable"

    cee_count = sum(1 for h in history if isinstance(h.get("C_emo"), (int, float)) and h["C_emo"] >= 0.75)

    cee_exp = ns.get("cee_experiences", [])
    if not isinstance(cee_exp, list):
        cee_exp = []
    if date_from or date_to:
        cee_filtered = []
        for ce in cee_exp:
            if isinstance(ce, dict):
                ce_d = ce.get("timestamp", "")[:10]
                if date_from and ce_d < date_from:
                    continue
                if date_to and ce_d > date_to:
                    continue
                cee_filtered.append(ce)
        cee_exp = cee_filtered

    drift = ns.get("drift_periods", [])
    if not isinstance(drift, list):
        drift = []

    reply_raw = ns.get("reply_therapy", {})
    reply_summary = {}
    if isinstance(reply_raw, dict):
        reply_summary = {
            "active_theme": reply_raw.get("active_reply_theme"),
            "completed_count": len(reply_raw.get("completed_replies", [])),
            "themes": {},
        }
        for theme, data in reply_raw.get("themes", {}).items():
            if isinstance(data, dict):
                reply_summary["themes"][theme] = {
                    "mismatch": data.get("mismatch_count", 0),
                    "reconsolidation": data.get("reconsolidation_count", 0),
                    "evocative": data.get("evocative_recall_count", 0),
                    "threshold_met": data.get("threshold_met", False),
                    "reply_completed": data.get("reply_completed", False),
                }

    return {
        "current": {
            "C_emo": ns.get("C_emo", 0),
            "GAP": ns.get("GAP", 0),
            "Quantum": ns.get("Quantum", 0),
            "mood": ns.get("mood_current", "neutral"),
            "mood_trend": ns.get("mood_trend", "stable"),
            "session_count": ns.get("session_count", 0),
            "anxiety": ns.get("anxiety_level", 0),
            "engagement": ns.get("engagement", 0),
            "risk_level": ns.get("risk_level", "LOW"),
            "breakthrough_count": ns.get("breakthrough_count", 0),
        },
        "trends": {
            "C_emo": {
                "values": [round(v, 3) for v in cemo_vals[-50:]],
                "timestamps": [h.get("timestamp", "") for h in history if isinstance(h.get("C_emo"), (int, float))][-50:],
                "average": round(sum(cemo_vals) / len(cemo_vals), 3) if cemo_vals else 0,
                "peak": round(max(cemo_vals), 3) if cemo_vals else 0,
                "low": round(min(cemo_vals), 3) if cemo_vals else 0,
                "trend": _trend(cemo_vals),
                "data_points": len(cemo_vals),
            },
            "GAP": {
                "values": [round(v, 3) for v in gap_vals[-50:]],
                "average": round(sum(gap_vals) / len(gap_vals), 3) if gap_vals else 0,
                "trend": _trend(gap_vals),
            },
            "Quantum": {
                "values": [round(v, 3) for v in quantum_vals[-50:]],
                "average": round(sum(quantum_vals) / len(quantum_vals), 3) if quantum_vals else 0,
                "trend": _trend(quantum_vals),
            },
        },
        "cee_total": cee_count,
        "cee_experiences": [
            {
                "timestamp": ce.get("timestamp", ""),
                "c_emo_before": ce.get("c_emo_before", 0),
                "c_emo_after": ce.get("c_emo_after", 0),
                "delta": ce.get("delta", 0),
                "mood_before": ce.get("mood_before", ""),
                "mood_after": ce.get("mood_after", ""),
            }
            for ce in cee_exp[-30:]
            if isinstance(ce, dict)
        ],
        "drift_periods": [
            {
                "left_at": dp.get("left_at", ""),
                "returned_at": dp.get("returned_at", ""),
                "gap_days": dp.get("gap_days", 0),
                "explored": dp.get("explored", False),
            }
            for dp in drift
            if isinstance(dp, dict)
        ],
        "reply_therapy": reply_summary,
        "mood_history": mood_hist[-30:],
        "history": [
            {
                "timestamp": h.get("timestamp", ""),
                "C_emo": round(h.get("C_emo", 0), 3) if isinstance(h.get("C_emo"), (int, float)) else 0,
                "GAP": round(h.get("GAP", 0), 3) if isinstance(h.get("GAP"), (int, float)) else 0,
                "Quantum": round(h.get("Quantum", 0), 3) if isinstance(h.get("Quantum"), (int, float)) else 0,
                "mood": h.get("mood", ""),
            }
            for h in history[-50:]
        ],
    }


# ─── PostgreSQL Coherence Helpers ────────────────────────────────────────────

async def _load_coherence_from_pg(db_pool, hw_id: str, date_from, date_to):
    """Load coherence history from nevedal_metrics via PostgreSQL."""
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
            hw_id,
        )
        if not user_row:
            return [], {}

        user_id = user_row["id"]

        date_clause = ""
        params = [user_id]
        idx = 2
        if date_from:
            date_clause += f" AND recorded_at >= ${idx}::date"
            params.append(date_from)
            idx += 1
        if date_to:
            date_clause += f" AND recorded_at <= (${idx}::date + INTERVAL '1 day')"
            params.append(date_to)
            idx += 1

        rows = await conn.fetch(
            f"""SELECT c_emo, p_ent, t_tunnel, gamma_env, e_g_joint,
                       tau_emo, cee_window, cee_duration_seconds,
                       biometrics, recorded_at
                FROM nevedal_metrics
                WHERE user_id = $1 {date_clause}
                ORDER BY recorded_at ASC
                LIMIT 500""",
            *params,
        )

        history = []
        for r in rows:
            c_emo = float(r["c_emo"]) if r["c_emo"] is not None else 0.0
            p_ent = float(r["p_ent"]) if r["p_ent"] is not None else 0.0
            gamma = float(r["gamma_env"]) if r["gamma_env"] is not None else 0.0
            gap = abs(c_emo - gamma) if gamma else 0.0
            quantum = (c_emo + p_ent) / 2.0 if (c_emo or p_ent) else 0.0

            bio = r["biometrics"] or {}
            if isinstance(bio, str):
                try:
                    bio = json.loads(bio)
                except Exception:
                    bio = {}

            history.append({
                "timestamp": r["recorded_at"].isoformat() if r["recorded_at"] else "",
                "C_emo": round(c_emo, 5),
                "GAP": round(gap, 5),
                "Quantum": round(quantum, 5),
                "p_ent": round(p_ent, 5),
                "cee_window": bool(r["cee_window"]),
                "mood": bio.get("mood", ""),
            })

        current = {}
        if history:
            latest = history[-1]
            current = {
                "C_emo": latest["C_emo"],
                "GAP": latest["GAP"],
                "Quantum": latest["Quantum"],
            }

        return history, current


# ─── Emotional Weather Longitudinal Endpoints ────────────────────────────────


@router.get("/weather/family/{family_id}", dependencies=[Depends(require_admin)])
async def get_family_weather_history(
    family_id: str,
    request: Request,
    days: int = 90,
    limit: int = 500,
):
    """
    Longitudinal emotional weather data for a family.
    Returns time-series of system_coherence, system_volatility, CEE windows,
    bridge/isolated members, and per-session summaries across all Sanctuary sessions.
    """
    db_pool = _get_db_pool(request)
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, sanctuary_id, family_id,
                       member_states, dyad_coherence,
                       system_coherence, system_volatility,
                       cee_window_open, bridge_member, isolated_member,
                       created_at
                FROM emotional_weather_snapshots
                WHERE family_id = $1
                  AND created_at > NOW() - ($2::int * INTERVAL '1 day')
                ORDER BY created_at ASC
                LIMIT $3
            """, family_id, days, limit)

            snapshots = []
            for r in rows:
                member_states = r["member_states"] or {}
                if isinstance(member_states, str):
                    try:
                        member_states = json.loads(member_states)
                    except Exception:
                        member_states = {}

                dyad_data = r["dyad_coherence"] or {}
                if isinstance(dyad_data, str):
                    try:
                        dyad_data = json.loads(dyad_data)
                    except Exception:
                        dyad_data = {}

                snapshots.append({
                    "id": r["id"],
                    "sanctuary_id": r["sanctuary_id"],
                    "timestamp": r["created_at"].isoformat() if r["created_at"] else "",
                    "system_coherence": float(r["system_coherence"] or 0),
                    "system_volatility": float(r["system_volatility"] or 0),
                    "cee_window_open": bool(r["cee_window_open"]),
                    "bridge_member": r["bridge_member"],
                    "isolated_member": r["isolated_member"],
                    "member_count": len(member_states),
                    "dyad_count": len(dyad_data),
                    "member_states": member_states,
                    "dyad_coherence": dyad_data,
                })

            # Aggregate session-level summaries
            sessions = {}
            for s in snapshots:
                sid = s["sanctuary_id"]
                if sid not in sessions:
                    sessions[sid] = {
                        "sanctuary_id": sid,
                        "snapshot_count": 0,
                        "first_snapshot": s["timestamp"],
                        "last_snapshot": s["timestamp"],
                        "coherence_values": [],
                        "volatility_values": [],
                        "cee_window_count": 0,
                        "bridge_members": {},
                        "isolated_members": {},
                    }
                sess = sessions[sid]
                sess["snapshot_count"] += 1
                sess["last_snapshot"] = s["timestamp"]
                sess["coherence_values"].append(s["system_coherence"])
                sess["volatility_values"].append(s["system_volatility"])
                if s["cee_window_open"]:
                    sess["cee_window_count"] += 1
                if s["bridge_member"]:
                    sess["bridge_members"][s["bridge_member"]] = sess["bridge_members"].get(s["bridge_member"], 0) + 1
                if s["isolated_member"]:
                    sess["isolated_members"][s["isolated_member"]] = sess["isolated_members"].get(s["isolated_member"], 0) + 1

            session_summaries = []
            for sess in sessions.values():
                coh_vals = sess["coherence_values"]
                vol_vals = sess["volatility_values"]
                session_summaries.append({
                    "sanctuary_id": sess["sanctuary_id"],
                    "snapshot_count": sess["snapshot_count"],
                    "first_snapshot": sess["first_snapshot"],
                    "last_snapshot": sess["last_snapshot"],
                    "avg_coherence": round(sum(coh_vals) / len(coh_vals), 4) if coh_vals else 0,
                    "peak_coherence": round(max(coh_vals), 4) if coh_vals else 0,
                    "avg_volatility": round(sum(vol_vals) / len(vol_vals), 4) if vol_vals else 0,
                    "cee_window_count": sess["cee_window_count"],
                    "primary_bridge": max(sess["bridge_members"], key=sess["bridge_members"].get) if sess["bridge_members"] else None,
                    "primary_isolated": max(sess["isolated_members"], key=sess["isolated_members"].get) if sess["isolated_members"] else None,
                })

            # Longitudinal trend
            all_coherence = [s["system_coherence"] for s in snapshots]
            trend = "not_enough_data"
            if len(all_coherence) >= 4:
                half = len(all_coherence) // 2
                first_half = sum(all_coherence[:half]) / half
                second_half = sum(all_coherence[half:]) / (len(all_coherence) - half)
                if second_half > first_half + 0.03:
                    trend = "improving"
                elif second_half < first_half - 0.03:
                    trend = "declining"
                else:
                    trend = "stable"

            return {
                "family_id": family_id,
                "days": days,
                "total_snapshots": len(snapshots),
                "total_sessions": len(session_summaries),
                "trend": trend,
                "session_summaries": session_summaries,
                "time_series": {
                    "timestamps": [s["timestamp"] for s in snapshots],
                    "system_coherence": [s["system_coherence"] for s in snapshots],
                    "system_volatility": [s["system_volatility"] for s in snapshots],
                    "cee_windows": [s["cee_window_open"] for s in snapshots],
                },
            }

    except Exception as e:
        logger.warning("weather/family/%s: query failed: %s", family_id, e)
        raise HTTPException(status_code=500, detail=f"Weather history error: {e}")


@router.get("/weather/session/{sanctuary_id}", dependencies=[Depends(require_admin)])
async def get_session_weather_timeline(sanctuary_id: str, request: Request):
    """
    Full emotional weather timeline for a single Sanctuary session.
    Returns all snapshots with member-level detail for deep analysis.
    """
    db_pool = _get_db_pool(request)
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, sanctuary_id, family_id,
                       member_states, dyad_coherence,
                       system_coherence, system_volatility,
                       cee_window_open, bridge_member, isolated_member,
                       created_at
                FROM emotional_weather_snapshots
                WHERE sanctuary_id = $1
                ORDER BY created_at ASC
            """, sanctuary_id)

            snapshots = []
            for r in rows:
                member_states = r["member_states"] or {}
                if isinstance(member_states, str):
                    try:
                        member_states = json.loads(member_states)
                    except Exception:
                        member_states = {}

                dyad_data = r["dyad_coherence"] or {}
                if isinstance(dyad_data, str):
                    try:
                        dyad_data = json.loads(dyad_data)
                    except Exception:
                        dyad_data = {}

                snapshots.append({
                    "id": r["id"],
                    "timestamp": r["created_at"].isoformat() if r["created_at"] else "",
                    "system_coherence": float(r["system_coherence"] or 0),
                    "system_volatility": float(r["system_volatility"] or 0),
                    "cee_window_open": bool(r["cee_window_open"]),
                    "bridge_member": r["bridge_member"],
                    "isolated_member": r["isolated_member"],
                    "member_states": member_states,
                    "dyad_coherence": dyad_data,
                })

            return {
                "sanctuary_id": sanctuary_id,
                "family_id": rows[0]["family_id"] if rows else None,
                "snapshot_count": len(snapshots),
                "snapshots": snapshots,
            }

    except Exception as e:
        logger.warning("weather/session/%s: query failed: %s", sanctuary_id, e)
        raise HTTPException(status_code=500, detail=f"Session weather error: {e}")


@router.get("/weather/summary", dependencies=[Depends(require_admin)])
async def get_weather_summary(request: Request, days: int = 90):
    """
    Aggregate weather summary across all families for the Nevedal Lab overview.
    Returns per-family average coherence, volatility, and CEE frequency.
    """
    db_pool = _get_db_pool(request)
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT family_id,
                       COUNT(*) as snapshot_count,
                       COUNT(DISTINCT sanctuary_id) as session_count,
                       AVG(system_coherence) as avg_coherence,
                       AVG(system_volatility) as avg_volatility,
                       SUM(CASE WHEN cee_window_open THEN 1 ELSE 0 END) as cee_count,
                       MIN(created_at) as first_snapshot,
                       MAX(created_at) as last_snapshot
                FROM emotional_weather_snapshots
                WHERE created_at > NOW() - ($1::int * INTERVAL '1 day')
                GROUP BY family_id
                ORDER BY avg_coherence DESC
            """, days)

            families = []
            for r in rows:
                families.append({
                    "family_id": r["family_id"],
                    "session_count": r["session_count"],
                    "snapshot_count": r["snapshot_count"],
                    "avg_coherence": round(float(r["avg_coherence"] or 0), 4),
                    "avg_volatility": round(float(r["avg_volatility"] or 0), 4),
                    "cee_frequency": round(r["cee_count"] / max(r["snapshot_count"], 1), 3),
                    "first_snapshot": r["first_snapshot"].isoformat() if r["first_snapshot"] else None,
                    "last_snapshot": r["last_snapshot"].isoformat() if r["last_snapshot"] else None,
                })

            total_coh = [f["avg_coherence"] for f in families if f["avg_coherence"] > 0]

            return {
                "days": days,
                "family_count": len(families),
                "platform_avg_coherence": round(sum(total_coh) / len(total_coh), 4) if total_coh else 0,
                "families": families,
            }

    except Exception as e:
        logger.warning("weather/summary: query failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Weather summary error: {e}")


def _build_report_from_pg(history, current, date_from, date_to):
    """Build coherence report response from PostgreSQL data."""
    cemo_vals = [h["C_emo"] for h in history if h["C_emo"] is not None]
    gap_vals = [h["GAP"] for h in history if h["GAP"] is not None]
    quantum_vals = [h["Quantum"] for h in history if h["Quantum"] is not None]

    def _trend(vals):
        if len(vals) < 4:
            return "not_enough_data"
        half = len(vals) // 2
        first = sum(vals[:half]) / half
        second = sum(vals[half:]) / (len(vals) - half)
        if second > first + 0.03:
            return "improving"
        elif second < first - 0.03:
            return "declining"
        return "stable"

    cee_count = sum(1 for h in history if h.get("cee_window"))

    cee_experiences = []
    for i, h in enumerate(history):
        if h.get("cee_window") and i > 0:
            cee_experiences.append({
                "timestamp": h["timestamp"],
                "c_emo_before": history[i - 1]["C_emo"],
                "c_emo_after": h["C_emo"],
                "delta": round(h["C_emo"] - history[i - 1]["C_emo"], 5),
                "mood_before": history[i - 1].get("mood", ""),
                "mood_after": h.get("mood", ""),
            })

    drift_periods = []
    for i in range(1, len(history)):
        try:
            from datetime import datetime as dt
            prev_ts = dt.fromisoformat(history[i - 1]["timestamp"].replace("Z", "+00:00"))
            curr_ts = dt.fromisoformat(history[i]["timestamp"].replace("Z", "+00:00"))
            gap_days = (curr_ts - prev_ts).days
            if gap_days >= 3:
                drift_periods.append({
                    "left_at": history[i - 1]["timestamp"],
                    "returned_at": history[i]["timestamp"],
                    "gap_days": gap_days,
                    "explored": False,
                })
        except Exception:
            pass

    mood_history = [
        {"mood": h.get("mood", "neutral"), "timestamp": h["timestamp"]}
        for h in history if h.get("mood")
    ][-30:]

    return {
        "current": {
            "C_emo": current.get("C_emo", 0),
            "GAP": current.get("GAP", 0),
            "Quantum": current.get("Quantum", 0),
            "mood": "neutral",
            "mood_trend": _trend([m.get("C_emo", 0) for m in history[-10:]]) if len(history) >= 4 else "stable",
            "session_count": len(history),
            "anxiety": 0,
            "engagement": 0,
            "risk_level": "LOW",
            "breakthrough_count": cee_count,
        },
        "trends": {
            "C_emo": {
                "values": [round(v, 3) for v in cemo_vals[-50:]],
                "timestamps": [h["timestamp"] for h in history if h.get("C_emo") is not None][-50:],
                "average": round(sum(cemo_vals) / len(cemo_vals), 3) if cemo_vals else 0,
                "peak": round(max(cemo_vals), 3) if cemo_vals else 0,
                "low": round(min(cemo_vals), 3) if cemo_vals else 0,
                "trend": _trend(cemo_vals),
                "data_points": len(cemo_vals),
            },
            "GAP": {
                "values": [round(v, 3) for v in gap_vals[-50:]],
                "average": round(sum(gap_vals) / len(gap_vals), 3) if gap_vals else 0,
                "trend": _trend(gap_vals),
            },
            "Quantum": {
                "values": [round(v, 3) for v in quantum_vals[-50:]],
                "average": round(sum(quantum_vals) / len(quantum_vals), 3) if quantum_vals else 0,
                "trend": _trend(quantum_vals),
            },
        },
        "cee_total": cee_count,
        "cee_experiences": cee_experiences[-30:],
        "drift_periods": drift_periods,
        "reply_therapy": {},
        "mood_history": mood_history,
        "history": [
            {
                "timestamp": h["timestamp"],
                "C_emo": round(h["C_emo"], 3),
                "GAP": round(h["GAP"], 3),
                "Quantum": round(h["Quantum"], 3),
                "mood": h.get("mood", ""),
            }
            for h in history[-50:]
        ],
    }
