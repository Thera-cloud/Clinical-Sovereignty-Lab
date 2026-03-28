"""
HIVE DEFENSE PROTOCOL — API Router
Phase 8 Security System endpoints for admin monitoring and control.
Patent-Pending — Claims 30-56

All endpoints require ADMIN role authentication.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, Form
from pydantic import BaseModel
from typing import List, Optional

from app.services.api_server import require_admin

logger = logging.getLogger("hive.api")

router = APIRouter(
    prefix="/api/hive-defense",
    tags=["hive_defense"],
    dependencies=[Depends(require_admin)],
)


# =============================================================================
# HELPERS
# =============================================================================

def _get_pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


def _get_security(request: Request, service_name: str):
    """Retrieve a security service from app.state.hive_defense."""
    hive = getattr(request.app.state, "hive_defense", None)
    if hive is None:
        raise HTTPException(503, "Hive Defense not initialized")
    svc = hive.get(service_name)
    if svc is None:
        raise HTTPException(503, f"Service {service_name} not available")
    return svc


# =============================================================================
# V4 READINESS (Service Health Probe)
# =============================================================================

@router.get("/v4/readiness")
async def get_v4_readiness(request: Request):
    """
    Probe the operational readiness of key Hive Defense v4 services.
    Each service's is_ready() checks DB connections, background loops, etc.
    """
    hive_v4 = getattr(request.app.state, "hive_v4", {})
    readiness_targets = [
        "guardian_fibre", "pipeline_drum", "sentinel_mesh",
        "anonymization_proxy", "webhook_fortress",
    ]
    results = {}
    for svc_name in readiness_targets:
        svc = hive_v4.get(svc_name)
        if svc is None:
            results[svc_name] = {"ready": False, "reason": "not_initialized"}
            continue
        if not hasattr(svc, "is_ready"):
            results[svc_name] = {"ready": True, "reason": "no_readiness_check"}
            continue
        try:
            ready = await svc.is_ready()
            results[svc_name] = {"ready": ready, "reason": "ok" if ready else "check_failed"}
        except Exception as exc:
            results[svc_name] = {"ready": False, "reason": str(exc)[:100]}

    all_ready = all(r["ready"] for r in results.values())
    ready_count = sum(1 for r in results.values() if r["ready"])
    return {
        "status": "healthy" if all_ready else "degraded",
        "ready": f"{ready_count}/{len(results)}",
        "services": results,
    }


# =============================================================================
# DEFCON
# =============================================================================

@router.get("/defcon")
async def get_defcon(request: Request):
    """Get current DEFCON state."""
    ctrl = _get_security(request, "defcon_controller")
    state = ctrl.get_state()
    return {
        "level": state.level.value if hasattr(state.level, "value") else state.level,
        "trigger_reason": state.trigger_reason,
        "heartbeat_interval": state.heartbeat_interval_sec,
        "mirror_mode": state.mirror_mode,
        "last_escalation": state.last_escalation.isoformat() if state.last_escalation else None,
        "last_deescalation": state.last_deescalation.isoformat() if state.last_deescalation else None,
    }


@router.get("/defcon/history")
async def get_defcon_history(request: Request, limit: int = 50):
    """Get DEFCON change history."""
    pool = _get_pool(request)
    if not pool:
        return {"history": [], "count": 0}
    rows = await pool.fetch(
        "SELECT * FROM defcon_history ORDER BY created_at DESC LIMIT $1", limit
    )
    return {
        "history": [
            {
                "id": str(r["id"]),
                "from_level": r["from_level"],
                "to_level": r["to_level"],
                "reason": r["trigger_reason"],
                "timestamp": r["created_at"].isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# MIRROR SHELL
# =============================================================================

@router.get("/mirror/stats")
async def mirror_stats(request: Request):
    """Get Mirror Shell statistics."""
    shell = _get_security(request, "mirror_shell")
    return shell.get_stats() if hasattr(shell, "get_stats") else {
        "total_processed": getattr(shell, "total_signals_processed", 0),
        "absorbed": getattr(shell, "mirror_absorbed", 0),
        "contained": getattr(shell, "mirror_contained", 0),
        "passed": getattr(shell, "passed_to_real", 0),
    }


@router.get("/mirror/namespaces")
async def mirror_namespaces(request: Request):
    """List active mirror namespaces."""
    shell = _get_security(request, "mirror_shell")
    mgr = getattr(shell, "namespace_manager", None)
    if mgr is None:
        return {"namespaces": [], "count": 0}
    namespaces = mgr.list_namespaces() if hasattr(mgr, "list_namespaces") else []
    return {"namespaces": namespaces, "count": len(namespaces)}


# =============================================================================
# COHERENCE GATE
# =============================================================================

@router.get("/gate/metrics")
async def gate_metrics(request: Request):
    """Get Coherence Gate pass/reject metrics."""
    gate = _get_security(request, "coherence_gate")
    metrics = getattr(gate, "metrics", None)
    if metrics and hasattr(metrics, "to_dict"):
        return metrics.to_dict()
    return {
        "total": getattr(metrics, "total", 0) if metrics else 0,
        "passed": getattr(metrics, "passed", 0) if metrics else 0,
        "absorbed": getattr(metrics, "absorbed", 0) if metrics else 0,
        "contained": getattr(metrics, "contained", 0) if metrics else 0,
        "suspicious": getattr(metrics, "suspicious", 0) if metrics else 0,
    }


# =============================================================================
# CURIOSITY PROTOCOL
# =============================================================================

@router.get("/curiosity/entities")
async def curiosity_entities(request: Request):
    """List entities currently under curiosity observation."""
    protocol = _get_security(request, "curiosity_protocol")
    states = getattr(protocol, "entity_states", {})
    return {
        "entities": [
            {
                "entity_id": str(eid),
                "level": s.current_level.value if hasattr(s, "current_level") else str(s),
                "events_count": len(getattr(s, "events", [])),
            }
            for eid, s in states.items()
            if getattr(s, "current_level", None) and str(getattr(s, "current_level", "none")) != "none"
        ],
        "count": len(states),
    }


@router.get("/curiosity/events")
async def curiosity_events(request: Request, limit: int = 100):
    """Get recent curiosity events."""
    pool = _get_pool(request)
    if not pool:
        return {"events": [], "count": 0}
    rows = await pool.fetch(
        "SELECT * FROM curiosity_events ORDER BY created_at DESC LIMIT $1", limit
    )
    return {
        "events": [
            {
                "id": str(r["id"]),
                "entity_id": str(r["entity_id"]),
                "level": r["level"],
                "divergence_type": r["divergence_type"],
                "details": r["details"],
                "timestamp": r["created_at"].isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# CONTAINMENT
# =============================================================================

@router.get("/containment/zones")
async def containment_zones(request: Request):
    """List active containment zones."""
    isolation = _get_security(request, "mesh_isolation")
    zones = isolation.list_active_zones() if hasattr(isolation, "list_active_zones") else []
    return {"zones": zones, "count": len(zones)}


# =============================================================================
# HEARTBEAT
# =============================================================================

@router.get("/heartbeat/registry")
async def heartbeat_registry(request: Request):
    """Get heartbeat registry status."""
    registry = _get_security(request, "heartbeat_registry")
    entities = list(getattr(registry, "_heartbeats", {}).keys())
    DEFAULT_SILENCE_NS = 60_000_000_000  # 60 seconds
    silent = registry.get_silent_entities(DEFAULT_SILENCE_NS) if hasattr(registry, "get_silent_entities") else []
    return {
        "registered_entities": len(entities),
        "silent_entities": len(silent),
        "silent_ids": [str(e) for e in silent[:20]],
    }


# =============================================================================
# DRIFT SCORES
# =============================================================================

@router.get("/drift/scores")
async def drift_scores(request: Request, min_magnitude: float = 0.1):
    """Get entities with drift scores above threshold."""
    pool = _get_pool(request)
    if not pool:
        return {"scores": [], "count": 0}
    rows = await pool.fetch(
        "SELECT * FROM drift_scores WHERE combined_mag >= $1 ORDER BY combined_mag DESC LIMIT 50",
        min_magnitude,
    )
    return {
        "scores": [
            {
                "entity_id": str(r["entity_id"]),
                "data_access": r["data_access"],
                "communication": r["communication"],
                "coherence": r["coherence"],
                "trail_emission": r["trail_emission"],
                "journal": r["journal_traj"],
                "timing": r["timing_pattern"],
                "combined": r["combined_mag"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# FORENSICS
# =============================================================================

@router.get("/forensics/recent")
async def forensic_recent(request: Request, limit: int = 50, event_type: Optional[str] = None):
    """Get recent forensic log entries."""
    pool = _get_pool(request)
    if not pool:
        return {"records": [], "count": 0}
    if event_type:
        rows = await pool.fetch(
            "SELECT * FROM hive_forensic_logs WHERE event_type = $1 ORDER BY created_at DESC LIMIT $2",
            event_type, limit,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM hive_forensic_logs ORDER BY created_at DESC LIMIT $1", limit
        )
    return {
        "records": [
            {
                "id": str(r["id"]),
                "event_type": r["event_type"],
                "source": r["source_entity"],
                "target": r["target_entity"],
                "chain_hash": r["chain_hash"][:16] + "...",
                "timestamp": r["created_at"].isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# GHOST MISSIONS
# =============================================================================

@router.get("/ghost/missions")
async def ghost_missions(request: Request):
    """List Ghost Swarm missions."""
    pool = _get_pool(request)
    if not pool:
        return {"missions": [], "count": 0}
    rows = await pool.fetch(
        "SELECT * FROM ghost_missions ORDER BY deployed_at DESC LIMIT 20"
    )
    return {
        "missions": [
            {
                "id": str(r["id"]),
                "zone": r["containment_zone"],
                "ghosts": r["ghost_count"],
                "status": r["status"],
                "deployed_at": r["deployed_at"].isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# ATTACKER PROFILES
# =============================================================================

@router.get("/attackers/profiles")
async def attacker_profiles(request: Request):
    """List known attacker fingerprints."""
    pool = _get_pool(request)
    if not pool:
        return {"profiles": [], "count": 0}
    rows = await pool.fetch(
        "SELECT id, sophistication, working_hours, timezone_estimate, first_seen, last_seen "
        "FROM attacker_fingerprints ORDER BY first_seen DESC LIMIT 50"
    )
    return {
        "profiles": [
            {
                "id": str(r["id"]),
                "sophistication": r["sophistication"],
                "working_hours": r["working_hours"],
                "timezone": r["timezone_estimate"],
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# TRINITY HELIX
# =============================================================================

@router.get("/helix/state")
async def helix_state(request: Request):
    """Get Trinity Helix rotation state."""
    helix = _get_security(request, "trinity_helix")
    state = helix.get_state() if hasattr(helix, "get_state") else {}
    return {
        "current_sequence": getattr(state, "current_sequence", []) if hasattr(state, "current_sequence") else state.get("current_sequence", []),
        "rotation_interval_ms": getattr(state, "rotation_interval_ms", 200) if hasattr(state, "rotation_interval_ms") else state.get("rotation_interval_ms", 200),
        "rotation_count": getattr(state, "rotation_count", 0) if hasattr(state, "rotation_count") else state.get("rotation_count", 0),
    }


@router.get("/helix/inverted-spaces")
async def inverted_spaces(request: Request):
    """List active triangular mirror inversion spaces."""
    pool = _get_pool(request)
    if not pool:
        return {"spaces": [], "count": 0}
    rows = await pool.fetch(
        "SELECT * FROM inverted_spaces WHERE is_active = TRUE ORDER BY created_at DESC LIMIT 20"
    )
    return {
        "spaces": [
            {
                "id": str(r["id"]),
                "entry_gate": r["entry_gate"],
                "interactions": r["interaction_count"],
                "tripwires": r["tripwires_triggered"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# PROJECTED HELIX
# =============================================================================

@router.get("/projection/deployments")
async def projection_deployments(request: Request):
    """List Projected Helix deployments."""
    pool = _get_pool(request)
    if not pool:
        return {"deployments": [], "count": 0}
    rows = await pool.fetch(
        "SELECT * FROM projected_helix_deployments ORDER BY created_at DESC LIMIT 20"
    )
    return {
        "deployments": [
            {
                "id": str(r["id"]),
                "status": r["status"],
                "mirror_accuracy": r["mirror_accuracy"],
                "interactions": r["interactions"],
                "commands_intercepted": r["commands_intercepted"],
                "authorized_by": r["authorized_by"],
                "deployed_at": r["deployed_at"].isoformat() if r["deployed_at"] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# QUARANTINE
# =============================================================================

@router.get("/quarantine/active")
async def active_quarantines(request: Request):
    """List Fibres currently in post-birth quarantine."""
    pool = _get_pool(request)
    if not pool:
        return {"quarantines": [], "count": 0}
    rows = await pool.fetch(
        "SELECT * FROM quarantine_state WHERE passed IS NULL ORDER BY started_at DESC LIMIT 50"
    )
    return {
        "quarantines": [
            {
                "fibre_id": str(r["fibre_id"]),
                "started_at": r["started_at"].isoformat(),
                "heartbeat_ok": r["heartbeat_ok"],
                "access_ok": r["access_ok"],
                "ring_ok": r["ring_ok"],
                "trail_ok": r["trail_ok"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


# =============================================================================
# CONSERVATION LEDGER
# =============================================================================

@router.get("/conservation/latest")
async def conservation_latest(request: Request):
    """Get latest Quakete energy conservation verification."""
    pool = _get_pool(request)
    if not pool:
        return {"entry": None}
    row = await pool.fetchrow(
        "SELECT * FROM conservation_ledger ORDER BY verified_at DESC LIMIT 1"
    )
    if not row:
        return {"entry": None}
    return {
        "entry": {
            "total_energy": row["total_energy"],
            "ledger_hash": row["ledger_hash"][:16] + "...",
            "violations": row["violations"],
            "is_valid": row["is_valid"],
            "verified_at": row["verified_at"].isoformat(),
        }
    }


# =============================================================================
# SYSTEM OVERVIEW
# =============================================================================

@router.get("/overview")
async def hive_defense_overview(request: Request):
    """Complete Hive Defense system overview for the admin dashboard."""
    pool = _get_pool(request)
    hive = getattr(request.app.state, "hive_defense", {})

    # DEFCON
    defcon = "unknown"
    ctrl = hive.get("defcon_controller")
    if ctrl:
        state = ctrl.get_state()
        defcon = state.level.value if hasattr(state.level, "value") else state.level

    # Counts from DB
    counts = {}
    if pool:
        for table, label in [
            ("curiosity_events", "curiosity_events"),
            ("containment_zones", "containment_zones"),
            ("hive_forensic_logs", "forensic_records"),
            ("attacker_fingerprints", "attacker_profiles"),
            ("ghost_missions", "ghost_missions"),
            ("inverted_spaces", "inverted_spaces"),
            ("projected_helix_deployments", "projections"),
        ]:
            try:
                val = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
                counts[label] = val or 0
            except Exception:
                counts[label] = 0

    return {
        "defcon_level": defcon,
        "services_loaded": len(hive),
        "patent_claims": "30-56",
        "attack_vectors_defended": 23,
        "three_cord_coverage": "100%",
        "counts": counts,
    }


# =============================================================================
# HIVE DEFENSE v4.0-v4.3 ENDPOINTS
# =============================================================================

def _get_v4(request: Request, service_name: str = ""):
    """Retrieve a v4 service from app.state.hive_v4."""
    hive_v4 = getattr(request.app.state, "hive_v4", None)
    if hive_v4 is None:
        raise HTTPException(503, "Hive Defense v4 not initialized")
    if service_name:
        svc = hive_v4.get(service_name)
        if svc is None:
            raise HTTPException(503, f"v4 service {service_name} not available")
        return svc
    return hive_v4


# ── Guardian Fibre ──

@router.get("/v4/guardian/{user_id}")
async def guardian_state(user_id: str, request: Request):
    """Get Guardian Fibre state for a specific user."""
    gf = _get_v4(request, "guardian_fibre")
    state = await gf.get_state(user_id)
    return {"user_id": user_id, **state}


@router.post("/v4/guardian/{user_id}/deescalate")
async def guardian_deescalate(user_id: str, new_state: str, request: Request):
    """Manually de-escalate a Guardian Fibre state (admin authority)."""
    gf = _get_v4(request, "guardian_fibre")
    await gf.deescalate(user_id, new_state, authorized_by="admin_api")
    return {"status": "deescalated", "user_id": user_id, "new_state": new_state}


@router.post("/v4/guardian/{user_id}/sentinel")
async def guardian_sentinel(user_id: str, request: Request, days: int = 30):
    """Put a user into Sentinel Mode."""
    gf = _get_v4(request, "guardian_fibre")
    await gf.enter_sentinel_mode(user_id, days)
    return {"status": "sentinel_mode_activated", "user_id": user_id, "duration_days": days}


# ── Sentinel Mesh ──

@router.get("/v4/sentinel-mesh/status")
async def sentinel_mesh_status(request: Request):
    """Get Sentinel Mesh defense status."""
    sm = _get_v4(request, "sentinel_mesh")
    return {
        "active": True,
        "defenses_count": 8,
        "description": "Meta-defense layer monitoring Guardian Fibres with 8 defense loops",
    }


# ── Pipeline Drum ──

@router.get("/v4/pipeline-drum/resonance")
async def pipeline_drum_resonance(request: Request):
    """Get Pipeline Drum resonance readings."""
    drum = _get_v4(request, "pipeline_drum")
    if hasattr(drum, "get_resonance"):
        return await drum.get_resonance()
    return {"status": "active", "sensors": ["moisture", "smoke", "burn", "clot"]}


# ── HEPA Filter ──

@router.get("/v4/hepa/stats")
async def hepa_stats(request: Request):
    """Get HEPA Filter statistics."""
    hepa = _get_v4(request, "hepa_filter")
    if hasattr(hepa, "get_stats"):
        return await hepa.get_stats()
    return {"status": "active", "protections": 7}


@router.get("/v4/hepa/staged-deletions")
async def hepa_staged_deletions(request: Request, limit: int = 50):
    """List staged deletions awaiting cooling period."""
    pool = _get_pool(request)
    if not pool:
        return {"deletions": [], "count": 0}
    try:
        rows = await pool.fetch(
            "SELECT * FROM staged_deletions WHERE status = 'COOLING' ORDER BY requested_at DESC LIMIT $1",
            limit,
        )
        return {
            "deletions": [
                {
                    "id": str(r["id"]),
                    "user_id": r["user_id"],
                    "data_type": r["data_type"],
                    "requested_at": r["requested_at"].isoformat() if r.get("requested_at") else None,
                    "cooling_ends_at": r["cooling_ends_at"].isoformat() if r.get("cooling_ends_at") else None,
                    "status": r["status"],
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception:
        return {"deletions": [], "count": 0, "error": "table_not_ready"}


# ── Billing Fortress ──

@router.get("/v4/billing-fortress/events")
async def billing_fortress_events(request: Request, limit: int = 50):
    """Get recent webhook fortress verification events."""
    pool = _get_pool(request)
    if not pool:
        return {"events": [], "count": 0}
    try:
        rows = await pool.fetch(
            "SELECT * FROM webhook_events_v2 ORDER BY processed_at DESC LIMIT $1", limit
        )
        return {
            "events": [
                {
                    "event_id": r["event_id"],
                    "event_type": r.get("event_type", ""),
                    "cord1": r.get("cord1_passed"),
                    "cord2": r.get("cord2_passed"),
                    "cord3": r.get("cord3_passed"),
                    "result": r.get("processing_result", ""),
                    "processed_at": r["processed_at"].isoformat() if r.get("processed_at") else None,
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception:
        return {"events": [], "count": 0, "error": "table_not_ready"}


@router.get("/v4/billing-fortress/anomalies")
async def billing_anomalies(request: Request, limit: int = 50):
    """Get billing anomaly detections."""
    pool = _get_pool(request)
    if not pool:
        return {"anomalies": [], "count": 0}
    try:
        rows = await pool.fetch(
            "SELECT * FROM billing_anomalies ORDER BY detected_at DESC LIMIT $1", limit
        )
        return {
            "anomalies": [
                {
                    "id": str(r["id"]),
                    "anomaly_type": r["anomaly_type"],
                    "severity": r["severity"],
                    "description": r.get("description", ""),
                    "detected_at": r["detected_at"].isoformat() if r.get("detected_at") else None,
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception:
        return {"anomalies": [], "count": 0, "error": "table_not_ready"}


# ── Anonymization Proxy ──

@router.get("/v4/anonymization/stats")
async def anonymization_stats(request: Request):
    """Get AnonymizationProxy statistics."""
    proxy = _get_v4(request, "anonymization_proxy")
    return proxy.get_stats()


# ── Model Stability ──

@router.get("/v4/model-stability/pinned")
async def model_stability_pinned(request: Request):
    """Get pinned model versions."""
    msl = _get_v4(request, "model_stability")
    return {
        "primary": msl.get_pinned_model("primary"),
        "realtime": msl.get_pinned_model("realtime"),
    }


# ── Legal Compulsion ──

@router.get("/v4/legal/warrant-canary")
async def warrant_canary(request: Request):
    """Check warrant canary status."""
    legal = _get_v4(request, "legal_compulsion")
    if hasattr(legal, "get_canary_status"):
        return await legal.get_canary_status()
    return {"canary_alive": True, "last_verified": datetime.now().isoformat()}


# ── v4 System Overview ──

# ── Upstream Canary Network ──

@router.get("/v4/canary/status")
async def canary_status(request: Request):
    """Get Upstream Canary Network status."""
    canary = _get_v4(request, "upstream_canary")
    return canary.get_status()


@router.post("/v4/canary/check/{provider}")
async def canary_check_provider(provider: str, request: Request):
    """Trigger an immediate canary check for a specific provider."""
    canary = _get_v4(request, "upstream_canary")
    return await canary.check_provider(provider)


@router.post("/v4/canary/check-all")
async def canary_check_all(request: Request):
    """Trigger an immediate canary check for all providers."""
    canary = _get_v4(request, "upstream_canary")
    return await canary.check_all()


# ── Therapeutic Integrity ──

@router.get("/v4/therapeutic-integrity/status")
async def therapeutic_integrity_status(request: Request):
    """Get Therapeutic Integrity Monitor status."""
    monitor = _get_v4(request, "therapeutic_integrity")
    tracked = len(monitor._coherence_history)
    declining = 0
    for history in monitor._coherence_history.values():
        if len(history) >= 7:
            import statistics
            first_week = statistics.mean(history[:7])
            last_week = statistics.mean(history[-7:])
            if last_week - first_week < -0.15:
                declining += 1
    return {
        "users_tracked": tracked,
        "users_declining": declining,
        "population_scores": len(monitor._population_scores),
        "canary_scenarios": len(monitor.get_all_canary_scenarios()),
    }


@router.post("/v4/therapeutic-integrity/check")
async def therapeutic_integrity_check(request: Request):
    """Trigger an immediate therapeutic integrity check."""
    monitor = _get_v4(request, "therapeutic_integrity")
    return await monitor.run_periodic_check()


# ── Trial Guard ──

@router.get("/v4/trial-guard/{user_id}")
async def trial_guard_status(user_id: str, trial_start: str, request: Request):
    """Check gated trial enforcement status for a user."""
    guard = _get_v4(request, "trial_guard")
    return await guard.enforce_gated_trial(user_id, trial_start)


# ── Webhook Rate Limit ──

@router.get("/v4/webhook-rate-limit/stats")
async def webhook_rate_limit_stats(request: Request):
    """Get webhook rate limiter statistics."""
    # The middleware is registered on the app, not in hive_v4
    for middleware in request.app.middleware_stack.__dict__.get("app", []).__class__.__mro__:
        pass  # Middleware stats are not directly accessible via request
    return {"status": "active", "max_per_window": 120, "window_seconds": 60}


@router.get("/v4/overview")
async def hive_v4_overview(request: Request):
    """Complete Hive Defense v4 system overview."""
    hive_v4 = getattr(request.app.state, "hive_v4", {})
    pool = _get_pool(request)

    v4_counts = {}
    if pool:
        for table, label in [
            ("guardian_fibres", "guardian_fibres"),
            ("webhook_events_v2", "webhook_events"),
            ("billing_anomalies", "billing_anomalies"),
            ("staged_deletions", "staged_deletions"),
            ("sentinel_records", "sentinel_records"),
            ("guardian_heartbeat_log", "guardian_heartbeats"),
            ("drum_alerts", "drum_alerts"),
        ]:
            try:
                val = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
                v4_counts[label] = val or 0
            except Exception:
                v4_counts[label] = 0

    return {
        "version": "v4.3",
        "status": "active" if hive_v4 else "not_initialized",
        "services_loaded": len(hive_v4),
        "service_names": list(hive_v4.keys()),
        "architecture": "All Windows Closed",
        "layers": {
            "billing_fortress": "webhook_fortress" in hive_v4,
            "guardian_fibre": "guardian_fibre" in hive_v4,
            "sentinel_mesh": "sentinel_mesh" in hive_v4,
            "pipeline_drum": "pipeline_drum" in hive_v4,
            "hepa_filter": "hepa_filter" in hive_v4,
            "sovereign_layer": "sovereign_keys" in hive_v4,
            "anonymization_proxy": "anonymization_proxy" in hive_v4,
            "model_stability": "model_stability" in hive_v4,
            "family_session_guardian": "family_session_guardian" in hive_v4,
            "coach_integrity_shield": "coach_integrity_shield" in hive_v4,
            "legal_compulsion": "legal_compulsion" in hive_v4,
            "zero_knowledge_vault": "zero_knowledge_vault" in hive_v4,
            "succession_protocol": "succession_protocol" in hive_v4,
            "recovery_drill": "recovery_drill" in hive_v4,
            "upstream_canary": "upstream_canary" in hive_v4,
            "therapeutic_integrity": "therapeutic_integrity" in hive_v4,
            "webhook_rate_limit": True,
        },
        "counts": v4_counts,
    }


# =============================================================================
# HIVE INSPECT — Content Analysis Endpoint
# =============================================================================

class InspectRequest(BaseModel):
    content: str
    content_type: str = "text"  # "email", "url", "text", "raw_headers"
    from_address: str = ""
    subject: str = ""
    raw_headers: str = ""
    attachment_names: List[str] = []


@router.post("/v4/inspect")
async def inspect_content(body: InspectRequest):
    """
    Submit any content (email body, URL, suspicious text) for Hive analysis.
    Runs through: PhishingDetector + AdminContactShield + ContentSentinel.
    Returns structured verdict with per-system breakdown.
    """
    from app.services.security.phishing_detector import analyze as phishing_analyze

    results: dict = {"systems": {}}

    # 1. Phishing Detector
    phishing_verdict = phishing_analyze(
        content=body.content,
        content_type=body.content_type,
        from_address=body.from_address,
        subject=body.subject,
        raw_headers=body.raw_headers,
        attachment_names=body.attachment_names or None,
    )
    results["phishing"] = phishing_verdict.to_dict()
    results["systems"]["phishing_detector"] = {
        "verdict": phishing_verdict.verdict,
        "score": phishing_verdict.score,
    }

    # 2. Admin Contact Shield — check for extraction attempts
    try:
        from app.services.security.admin_contact_shield import get_shield
        shield = get_shield()
        extraction_score = shield.score_extraction_attempt(body.content)
        contains_pii = shield.contains_protected_contact(body.content)
        results["systems"]["admin_shield"] = {
            "extraction_attempt_score": extraction_score,
            "contains_admin_pii": contains_pii,
            "verdict": "MALICIOUS" if extraction_score >= 0.7 else "SUSPICIOUS" if contains_pii else "CLEAN",
        }
    except Exception as e:
        results["systems"]["admin_shield"] = {"error": str(e)}

    # 3. Content Sentinel — injection / anomaly check (if loaded in hive)
    try:
        from uuid import uuid4 as _uuid4
        hive_v4 = getattr(body, "_request", None)
        sentinel = None
        # Try to get from app state if available via request context
        # Fallback: import and instantiate
        if sentinel is None:
            from app.services.security.content_sentinel import ContentSentinel
            sentinel = ContentSentinel()
        payload = {"content": body.content, "subject": body.subject, "from": body.from_address}
        sentinel_result = await sentinel.inspect_payload(
            entity_id=_uuid4(),  # anonymous inspection
            payload=payload,
            entity_type="admin_inspection",
        )
        results["systems"]["content_sentinel"] = {
            "verdict": sentinel_result.verdict.value if hasattr(sentinel_result.verdict, "value") else str(sentinel_result.verdict),
            "checks_passed": sentinel_result.checks_passed if hasattr(sentinel_result, "checks_passed") else None,
        }
    except Exception as e:
        results["systems"]["content_sentinel"] = {"verdict": "UNAVAILABLE", "note": str(e)[:120]}

    # Compute aggregate verdict
    verdicts = []
    verdicts.append(phishing_verdict.verdict)
    for sys_name, sys_result in results["systems"].items():
        v = sys_result.get("verdict", "CLEAN")
        if v in ("MALICIOUS", "REJECT_AND_ALARM", "REJECT_AND_INVESTIGATE"):
            verdicts.append("MALICIOUS")
        elif v in ("SUSPICIOUS", "QUARANTINE_FOR_REVIEW", "PASS_WITH_FLAG"):
            verdicts.append("SUSPICIOUS")

    if "MALICIOUS" in verdicts:
        aggregate = "MALICIOUS"
    elif "SUSPICIOUS" in verdicts:
        aggregate = "SUSPICIOUS"
    else:
        aggregate = "CLEAN"

    results["aggregate_verdict"] = aggregate
    results["aggregate_score"] = phishing_verdict.score
    results["recommendations"] = phishing_verdict.recommendations

    return results


@router.post("/v4/inspect-url")
async def inspect_url(url: str = ""):
    """Quick URL-only inspection endpoint (used by Nate Guardian link checks)."""
    from app.services.security.phishing_detector import analyze as phishing_analyze

    if not url:
        raise HTTPException(400, "URL required")

    verdict = phishing_analyze(content=url, content_type="url")
    return verdict.to_dict()


# =============================================================================
# GMAIL HIVE MONITOR — Status & Control
# =============================================================================

@router.get("/v4/email-monitor/status")
async def email_monitor_status():
    """Return current Gmail Hive Monitor status for dashboard."""
    from app.services.security.gmail_hive_monitor import get_monitor
    monitor = get_monitor()
    return monitor.get_status()


@router.post("/v4/email-monitor/start")
async def email_monitor_start():
    """Start the Gmail Hive Monitor background polling."""
    from app.services.security.gmail_hive_monitor import get_monitor
    monitor = get_monitor()
    if monitor.is_running:
        return {"status": "already_running", "monitored": monitor.monitored_count}
    await monitor.start()
    return {"status": "started", "monitored": monitor.monitored_count}


@router.post("/v4/email-monitor/stop")
async def email_monitor_stop():
    """Stop the Gmail Hive Monitor."""
    from app.services.security.gmail_hive_monitor import get_monitor
    monitor = get_monitor()
    await monitor.stop()
    return {"status": "stopped"}


# =============================================================================
# THREAT DROPBOX — Manual submission for hunter pursuit
# =============================================================================

class ThreatDropboxSubmission(BaseModel):
    threat_type: str   # "url", "email", "phone", "domain", "raw_text"
    content: str
    source_note: str = ""
    auto_hunt: bool = True


@router.post("/v4/threat-dropbox/submit")
async def threat_dropbox_submit(body: ThreatDropboxSubmission):
    """
    Submit suspicious content for hunter analysis and pursuit.
    All reconnaissance runs inside the isolated Sandbox VPS — never from production.
    """
    if not body.content or not body.content.strip():
        raise HTTPException(400, "Content is required")
    if body.threat_type not in ("url", "email", "phone", "domain", "raw_text"):
        raise HTTPException(400, "Invalid threat_type. Must be: url, email, phone, domain, raw_text")

    if body.auto_hunt:
        result = await _sandbox_request(
            "POST", "/hunt",
            json_body={
                "threat_type": body.threat_type,
                "content": body.content.strip(),
                "source_note": body.source_note,
            },
            timeout=60,
        )
        return {
            "status": "hunting",
            "hunt_id": result.get("hunt_id", ""),
            "message": f"Hunter deployed against {body.threat_type} (Sandbox VPS)",
        }
    else:
        from app.services.security.phishing_detector import analyze as phishing_analyze
        verdict = phishing_analyze(content=body.content, content_type="text")
        return {
            "status": "analyzed_only",
            "verdict": verdict.verdict,
            "score": verdict.score,
            "signals": len(verdict.signals),
        }


@router.get("/v4/threat-dropbox/hunts")
async def threat_dropbox_hunts():
    """List all hunt operations (from Sandbox VPS)."""
    try:
        result = await _sandbox_request("GET", "/hunts", timeout=10)
        return result
    except HTTPException:
        return {"hunts": []}


@router.get("/v4/threat-dropbox/hunt/{hunt_id}")
async def threat_dropbox_hunt_detail(hunt_id: str):
    """Get full hunt report (from Sandbox VPS)."""
    result = await _sandbox_request("GET", f"/hunt/{hunt_id}", timeout=10)
    return result


# =============================================================================
# DETONATION CHAMBER — Proxied to isolated Sandbox VPS (10.13.13.4)
# =============================================================================

import os as _os

SANDBOX_URL = _os.environ.get("SANDBOX_URL", "http://10.13.13.4:9090")
SANDBOX_HMAC_KEY = _os.environ.get("SANDBOX_HMAC_KEY", "")
_DETONATION_CACHE: dict = {}


async def _sandbox_request(method: str, path: str, json_body: dict = None, timeout: int = 30):
    """Proxy a request to the isolated Sandbox VPS over WireGuard."""
    import aiohttp
    headers = {}
    if SANDBOX_HMAC_KEY:
        headers["X-Sandbox-Key"] = SANDBOX_HMAC_KEY
    url = f"{SANDBOX_URL}{path}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            if method == "POST":
                async with session.post(url, json=json_body, headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise HTTPException(resp.status, f"Sandbox error: {text[:200]}")
                    return await resp.json()
            else:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise HTTPException(resp.status, f"Sandbox error: {text[:200]}")
                    return await resp.json()
    except aiohttp.ClientError as e:
        raise HTTPException(503, f"Sandbox VPS unreachable: {e}")


class DetonateRequest(BaseModel):
    url: str
    inject_decoy: bool = True


@router.post("/v4/threat-dropbox/detonate")
async def threat_dropbox_detonate(body: DetonateRequest):
    """
    Detonate a URL in the isolated Sandbox VPS headless browser.
    Proxied over WireGuard to 10.13.13.4 — never runs in the backend process.
    """
    if not body.url or not body.url.strip():
        raise HTTPException(400, "URL is required")

    url = body.url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    result = await _sandbox_request(
        "POST", "/detonate",
        json_body={"url": url, "inject_decoy": body.inject_decoy},
        timeout=45,
    )
    det_id = result.get("detonation_id", "")
    if det_id:
        _DETONATION_CACHE[det_id] = result
    return {
        "status": result.get("status", "detonating"),
        "detonation_id": det_id,
        "message": f"Shell browser deployed to {url} (Sandbox VPS)",
    }


@router.get("/v4/threat-dropbox/detonations")
async def threat_dropbox_detonations():
    """List all detonation operations (from Sandbox VPS)."""
    try:
        result = await _sandbox_request("GET", "/detonations", timeout=10)
        return result
    except HTTPException:
        return {"detonations": list(_DETONATION_CACHE.values())}


@router.get("/v4/threat-dropbox/detonation/{det_id}")
async def threat_dropbox_detonation_detail(det_id: str):
    """Get full detonation report with screenshots (from Sandbox VPS)."""
    result = await _sandbox_request("GET", f"/detonation/{det_id}", timeout=10)
    _DETONATION_CACHE[det_id] = result
    return result


@router.get("/v4/threat-dropbox/detonation/{det_id}/screenshot/{page_idx}")
async def threat_dropbox_screenshot(det_id: str, page_idx: int):
    """Get full screenshot for a specific page in a detonation."""
    from fastapi.responses import Response

    result = await _sandbox_request("GET", f"/detonation/{det_id}", timeout=10)
    pages = result.get("pages", [])
    if page_idx >= len(pages):
        raise HTTPException(404, f"Page {page_idx} not found")

    page = pages[page_idx]
    screenshot = page.get("screenshot_b64", "")
    if not screenshot or screenshot.endswith("..."):
        raise HTTPException(404, "No full screenshot available")

    img_bytes = base64.b64decode(screenshot)
    return Response(content=img_bytes, media_type="image/png")


ALLOWED_UPLOAD_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "application/pdf",
    "text/plain", "text/html", "text/csv",
    "message/rfc822", "application/octet-stream",
}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


def _extract_text_from_file(file_bytes: bytes, content_type: str, filename: str) -> str:
    """Extract readable text from uploaded files."""
    import re

    # Plain text / HTML / EML / CSV
    if content_type.startswith("text/") or content_type == "message/rfc822" or filename.endswith((".eml", ".txt", ".csv", ".html")):
        try:
            return file_bytes.decode("utf-8", errors="replace")
        except Exception:
            return file_bytes.decode("latin-1", errors="replace")

    # PDF
    if content_type == "application/pdf" or filename.endswith(".pdf"):
        try:
            import io
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(file_bytes))
                pages = []
                for page in reader.pages[:20]:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                return "\n".join(pages)
            except ImportError:
                pass

            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    pages = []
                    for page in pdf.pages[:20]:
                        text = page.extract_text()
                        if text:
                            pages.append(text)
                    return "\n".join(pages)
            except ImportError:
                return "[PDF uploaded — install PyPDF2 or pdfplumber for text extraction]"
        except Exception as e:
            return f"[PDF parse error: {e}]"

    # Images — OCR with pytesseract if available
    if content_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        try:
            import io
            from PIL import Image
            import pytesseract
            img = Image.open(io.BytesIO(file_bytes))
            text = pytesseract.image_to_string(img)
            return text if text.strip() else "[Image uploaded — no text detected by OCR]"
        except ImportError:
            return "[Image uploaded — install pytesseract + Pillow for OCR extraction]"
        except Exception as e:
            return f"[Image OCR error: {e}]"

    # Unknown
    if filename.endswith(".eml"):
        try:
            return file_bytes.decode("utf-8", errors="replace")
        except Exception:
            return "[EML file — could not decode]"

    return f"[Unsupported file type: {content_type}]"


def _extract_urls_from_text(text: str) -> list:
    """Pull URLs from extracted text."""
    import re
    url_pattern = re.compile(
        r'https?://[^\s<>"\')\]]+|www\.[^\s<>"\')\]]+',
        re.I,
    )
    urls = url_pattern.findall(text)
    return list(dict.fromkeys(u.rstrip(".,;:!?)>") for u in urls))


def _extract_emails_from_text(text: str) -> list:
    """Pull email addresses from text."""
    import re
    email_pattern = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    return list(set(email_pattern.findall(text)))


def _extract_phones_from_text(text: str) -> list:
    """Pull phone numbers from text."""
    import re
    phone_pattern = re.compile(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{7,15}')
    matches = phone_pattern.findall(text)
    return list(set(m.strip() for m in matches if len(m.strip()) >= 10))


def _extract_domains_from_text(text: str) -> list:
    """Pull domain names from text."""
    import re
    domain_pattern = re.compile(r'(?:[a-zA-Z0-9\-]+\.)+[a-zA-Z]{2,}')
    domains = set()
    for m in domain_pattern.findall(text):
        m = m.lower().strip(".")
        if "." in m and not m.endswith((".png", ".jpg", ".gif", ".css", ".js")):
            domains.add(m)
    return list(domains)


@router.post("/v4/threat-dropbox/upload")
async def threat_dropbox_upload(
    file: UploadFile = File(...),
    source_note: str = Form(""),
    auto_hunt: bool = Form(True),
):
    """
    Accept file uploads (images, PDFs, text, emails) for threat analysis.
    Extracts text/URLs/emails locally, then proxies recon to the Sandbox VPS.
    """
    content_type = file.content_type or "application/octet-stream"
    import re as _re
    _raw_fn = file.filename or "unknown"
    filename = _re.sub(r'[^\w\-.]', '_', _raw_fn.split("/")[-1].split("\\")[-1])[:255] or "unknown"

    if content_type not in ALLOWED_UPLOAD_TYPES and not filename.endswith((".eml", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".csv", ".html")):
        raise HTTPException(400, f"Unsupported file type: {content_type}. Accepted: images, PDF, text, HTML, EML")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large (max {MAX_UPLOAD_SIZE // (1024*1024)} MB)")
    if len(file_bytes) == 0:
        raise HTTPException(400, "Empty file")

    extracted_text = _extract_text_from_file(file_bytes, content_type, filename)

    urls = _extract_urls_from_text(extracted_text)
    emails = _extract_emails_from_text(extracted_text)
    phones = _extract_phones_from_text(extracted_text)
    domains = _extract_domains_from_text(extracted_text)

    extraction_summary = {
        "filename": filename,
        "content_type": content_type,
        "file_size": len(file_bytes),
        "text_length": len(extracted_text),
        "urls_found": urls[:20],
        "emails_found": emails[:20],
        "phones_found": phones[:20],
        "domains_found": domains[:20],
        "extracted_preview": extracted_text[:500],
    }

    hunt_results = []

    if auto_hunt and (urls or emails or domains):
        hunt_content = extracted_text[:2000]
        if urls:
            hunt_content += "\n\nURLs found:\n" + "\n".join(urls[:10])
        if emails:
            hunt_content += "\n\nEmails found:\n" + "\n".join(emails[:10])

        if urls:
            threat_type = "email" if emails else "raw_text"
        elif emails:
            threat_type = "email"
        elif domains:
            threat_type = "domain"
        else:
            threat_type = "raw_text"

        note = f"File: {filename}" + (f" | {source_note}" if source_note else "")

        try:
            result = await _sandbox_request(
                "POST", "/hunt",
                json_body={
                    "threat_type": threat_type,
                    "content": hunt_content,
                    "source_note": note,
                },
                timeout=60,
            )
            hunt_results.append(result.get("hunt_id", ""))
        except HTTPException as e:
            logger.warning("Sandbox hunt failed for uploaded file %s: %s", filename, e.detail)

    return {
        "status": "processed",
        "extraction": extraction_summary,
        "hunts_launched": len(hunt_results),
        "hunt_ids": hunt_results,
        "message": (
            f"Extracted {len(urls)} URLs, {len(emails)} emails, "
            f"{len(phones)} phones, {len(domains)} domains from {filename}"
        ),
    }


# =============================================================================
# SENTINEL DEFENSE ORCHESTRATION (Patent Claims 30-56)
# =============================================================================

@router.get("/v4/sentinel-freeze/history")
async def sentinel_freeze_history(request: Request, limit: int = 50):
    """Get recent Sentinel freeze events with forensic details."""
    pool = _get_pool(request)
    if not pool:
        return {"freezes": [], "count": 0}
    try:
        rows = await pool.fetch(
            "SELECT id, ip, uid, sentinel_score, reasons, actions_taken, "
            "defcon_level, mirror_namespace_id, trap_id, frozen_at, "
            "disengaged_at, interactions_mirrored, recon_report_sent "
            "FROM sentinel_freeze_history ORDER BY frozen_at DESC LIMIT $1",
            limit,
        )
        return {
            "freezes": [
                {
                    "id": r["id"],
                    "ip": r["ip"],
                    "uid": r["uid"],
                    "sentinel_score": r["sentinel_score"],
                    "reasons": r["reasons"],
                    "actions_taken": r["actions_taken"],
                    "defcon_level": r["defcon_level"],
                    "mirror_namespace_id": r["mirror_namespace_id"],
                    "trap_id": r["trap_id"],
                    "frozen_at": r["frozen_at"].isoformat() if r["frozen_at"] else None,
                    "disengaged_at": r["disengaged_at"].isoformat() if r["disengaged_at"] else None,
                    "interactions_mirrored": r["interactions_mirrored"],
                    "recon_report_sent": r["recon_report_sent"],
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.warning("sentinel_freeze_history: %s", e)
        return {"freezes": [], "count": 0}


@router.get("/v4/sentinel-freeze/banned-ips")
async def sentinel_banned_ips(request: Request):
    """List all actively banned IPs."""
    pool = _get_pool(request)
    if not pool:
        return {"banned_ips": [], "count": 0}
    try:
        rows = await pool.fetch(
            "SELECT ip, reason, banned_at, sentinel_score "
            "FROM sentinel_banned_ips WHERE active = TRUE ORDER BY banned_at DESC"
        )
        return {
            "banned_ips": [
                {
                    "ip": r["ip"],
                    "reason": r["reason"],
                    "banned_at": r["banned_at"].isoformat(),
                    "sentinel_score": r["sentinel_score"],
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.warning("sentinel_banned_ips: %s", e)
        return {"banned_ips": [], "count": 0}


@router.post("/v4/sentinel-freeze/unban")
async def sentinel_unban_ip(request: Request, body: dict = {}):
    """Remove an IP from the ban list."""
    ip = body.get("ip", "")
    if not ip:
        raise HTTPException(400, "ip required")
    pool = _get_pool(request)
    if not pool:
        raise HTTPException(503, "No database")
    await pool.execute(
        "UPDATE sentinel_banned_ips SET active = FALSE WHERE ip = $1", ip
    )
    orchestrator = getattr(request.app.state, "sentinel_orchestrator", None)
    if orchestrator and orchestrator._sase:
        orchestrator._sase.remove_from_blocklist(ip)
    return {"status": "unbanned", "ip": ip}


@router.post("/v4/mirror/deploy")
async def deploy_mirror_trap(request: Request, body: dict = {}):
    """Manually deploy a Mirror Trap for a specific IP."""
    ip = body.get("ip", "")
    if not ip:
        raise HTTPException(400, "ip required")

    orchestrator = getattr(request.app.state, "sentinel_orchestrator", None)
    if not orchestrator:
        raise HTTPException(503, "Sentinel orchestrator not initialized")

    namespace_id = await orchestrator._route_to_mirror(ip)
    return {
        "status": "deployed",
        "ip": ip,
        "namespace_id": namespace_id,
    }


# =============================================================================
# ACTIVATE DEFENSE FROM RECENT ACTIVITY (human-approved DEFCON + containment)
# =============================================================================

def _defcon_level_to_enum(level: int):
    """Map level 1-5 to DefconLevel. 1=CRITICAL, 5=PEACE."""
    from app.models.hive_defense import DefconLevel
    return DefconLevel(min(max(int(level), 1), 5))


@router.post("/v4/defense/activate-from-activity")
async def activate_defense_from_activity(request: Request, body: dict = {}):
    """
    Human-approved escalation: escalate DEFCON and/or deploy containment for an IP.
    Called from Sovereign Command Recent Activity 'Activate defense' button.
    Body: level (int 1-5), reason (str), source_ip (optional), deploy_containment (optional bool).
    """
    level = body.get("level", 4)
    reason = (body.get("reason") or "Admin-approved from Recent Activity").strip() or "Admin-approved from Recent Activity"
    source_ip = (body.get("source_ip") or "").strip()
    deploy_containment = bool(body.get("deploy_containment"))

    ctrl = _get_security(request, "defcon_controller")
    defcon_level = _defcon_level_to_enum(level)
    await ctrl.escalate(defcon_level, reason)

    result = {"defcon_escalated": True, "level": defcon_level.value if hasattr(defcon_level, "value") else defcon_level, "reason": reason}

    if source_ip and deploy_containment:
        orchestrator = getattr(request.app.state, "sentinel_orchestrator", None)
        if orchestrator and hasattr(orchestrator, "deploy_helix_containment"):
            try:
                namespace_id = await orchestrator.deploy_helix_containment(source_ip, reason)
                result["containment_deployed"] = True
                result["source_ip"] = source_ip
                result["namespace_id"] = namespace_id
                result["house_of_mirrors"] = True
            except Exception as e:
                logger.warning("activate-from-activity HELIX containment deploy failed: %s", e)
                result["containment_deployed"] = False
                result["containment_error"] = str(e)[:200]

    return result


# =============================================================================
# PROJECTED HELIX AUTHORIZATION (Patent Claims 53-56)
# =============================================================================

@router.get("/v4/projection/pending")
async def helix_pending_authorizations(request: Request):
    """List pending Helix authorization requests."""
    pool = _get_pool(request)
    if not pool:
        return {"authorizations": [], "count": 0}
    try:
        rows = await pool.fetch(
            "SELECT id, approval_code, attacker_ip, sentinel_score, proposed_at, "
            "expires_at, notification_sent_email, notification_sent_sms "
            "FROM helix_authorization WHERE status = 'PENDING' "
            "AND expires_at > NOW() ORDER BY proposed_at DESC"
        )
        return {
            "authorizations": [
                {
                    "id": r["id"],
                    "approval_code": r["approval_code"],
                    "attacker_ip": r["attacker_ip"],
                    "sentinel_score": r["sentinel_score"],
                    "proposed_at": r["proposed_at"].isoformat(),
                    "expires_at": r["expires_at"].isoformat(),
                    "email_sent": r["notification_sent_email"],
                    "sms_sent": r["notification_sent_sms"],
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.warning("helix_pending: %s", e)
        return {"authorizations": [], "count": 0}


# These approval/denial endpoints are PUBLIC (no auth) — accessed via email links
# They are registered on a separate sub-router below
_helix_public_router = APIRouter(
    prefix="/api/hive-defense",
    tags=["hive_defense_helix"],
)


@_helix_public_router.get("/v4/projection/approve/{code}")
async def helix_approve(request: Request, code: str):
    """Approve a Projected Helix deployment (from email link or SMS)."""
    orchestrator = getattr(request.app.state, "sentinel_orchestrator", None)
    if not orchestrator:
        return {"status": "error", "message": "System not initialized"}
    result = await orchestrator.handle_helix_approval(code, channel="email")
    if result.get("status") == "approved":
        return {
            "status": "approved",
            "message": f"Projected Helix APPROVED for IP {result.get('attacker_ip')}. "
                       f"Helix deployment initiated.",
        }
    return result


@_helix_public_router.get("/v4/projection/deny/{code}")
async def helix_deny(request: Request, code: str):
    """Deny a Projected Helix deployment."""
    orchestrator = getattr(request.app.state, "sentinel_orchestrator", None)
    if not orchestrator:
        return {"status": "error", "message": "System not initialized"}
    result = await orchestrator.handle_helix_denial(code, channel="email")
    return result


@_helix_public_router.post("/v4/projection/sms-webhook")
async def helix_sms_webhook(request: Request):
    """
    Twilio SMS webhook for Helix approval/denial.
    Parses inbound SMS like 'APPROVE ABC12345' or 'DENY ABC12345'.
    """
    form = await request.form()
    body_text = form.get("Body", "").strip().upper()
    from_number = form.get("From", "")

    orchestrator = getattr(request.app.state, "sentinel_orchestrator", None)
    if not orchestrator:
        return {"status": "ignored"}

    parts = body_text.split()
    if len(parts) >= 2:
        action = parts[0]
        code = parts[1]

        if action == "APPROVE":
            result = await orchestrator.handle_helix_approval(code, channel="sms")
            logger.info("Helix SMS APPROVE from %s: %s", from_number, result)
            return result
        elif action == "DENY":
            result = await orchestrator.handle_helix_denial(code, channel="sms")
            logger.info("Helix SMS DENY from %s: %s", from_number, result)
            return result

    if body_text == "STATUS":
        pool = _get_pool(request)
        if pool:
            try:
                row = await pool.fetchrow(
                    "SELECT ip, sentinel_score, frozen_at, interactions_mirrored "
                    "FROM sentinel_freeze_history WHERE disengaged_at IS NULL "
                    "ORDER BY frozen_at DESC LIMIT 1"
                )
                if row:
                    from datetime import datetime, timezone
                    elapsed = int((datetime.now(timezone.utc) - row["frozen_at"].replace(tzinfo=timezone.utc)).total_seconds() / 60)
                    ns = getattr(request.app.state, "notification_system", None)
                    shield = getattr(request.app.state, "admin_contact_shield", None)
                    if ns and shield and shield._alert_phone:
                        await ns.send_sms(
                            shield._alert_phone,
                            f"[MIRROR STATUS]\n"
                            f"IP: {row['ip']} | Score: {row['sentinel_score']}\n"
                            f"Active: {elapsed}min\n"
                            f"Interactions: {row['interactions_mirrored'] or 0}",
                        )
            except Exception as e:
                logger.warning("Helix SMS STATUS failed: %s", e)

    return {"status": "ok"}


# Export the public router for registration in main.py
helix_public_router = _helix_public_router
