"""
Quakete API — Layer 8 Swarm Solidarity Endpoints
Patent Claim 26: Quakete Collisionless Solidarity Protocol.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.api_server import require_admin

router = APIRouter(
    prefix="/api/quakete",
    tags=["Quakete Solidarity"],
    dependencies=[Depends(require_admin)],
)
logger = structlog.get_logger(__name__)


@router.get("/status")
async def quakete_status():
    """Lightweight health-check for architecture diagrams."""
    return {"status": "active", "service": "quakete_solidarity"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_ring_manager(request: Request) -> Optional[Any]:
    """Get CosmicRingManager from app state."""
    return getattr(request.app.state, "cosmic_ring_manager", None) or getattr(
        request.app.state, "quakete_ring_manager", None
    )


def _get_trail_map(request: Request) -> Optional[Any]:
    """Get FibreTrailMap from app state."""
    return getattr(request.app.state, "trail_map", None) or getattr(
        request.app.state, "quakete_trail_map", None
    )


def _get_transfer_service(request: Request) -> Optional[Any]:
    """Get QuaketeTransferService from app state."""
    return getattr(request.app.state, "quakete_transfer_service", None)


def _get_quakete_metrics(request: Request) -> Optional[Any]:
    """Get QuaketeMetrics from app state."""
    return getattr(request.app.state, "quakete_metrics", None)


def _get_particle_beam_generator(request: Request) -> Optional[Any]:
    """Get ParticleBeamGenerator from app state."""
    return getattr(request.app.state, "particle_beam_generator", None)


def _get_memorial_service(request: Request) -> Optional[Any]:
    """Get MemorialService from app state."""
    return getattr(request.app.state, "memorial_service", None)


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/rings")
async def list_cosmic_rings(request: Request) -> List[Dict[str, Any]]:
    """
    List all Cosmic Relational Rings.
    Returns ring_id, cords (fibre summaries), state, coherence, quakete_events.
    """
    ring_manager = _get_ring_manager(request)
    if not ring_manager:
        logger.warning("quakete_ring_manager_not_available")
        return []

    rings: List[Dict[str, Any]] = []
    all_rings = getattr(ring_manager, "all_rings", None) or getattr(ring_manager, "_rings", {})
    if isinstance(all_rings, dict):
        all_rings = list(all_rings.values())

    for ring in all_rings or []:
        cords = []
        for cord in (ring.all_cords() if hasattr(ring, "all_cords") else []):
            cords.append({
                "fibre_id": cord.fibre_id,
                "fibre_type": cord.fibre_type,
                "current_health": cord.current_health,
                "current_mode": cord.current_mode.value if hasattr(cord.current_mode, "value") else str(cord.current_mode),
            })
        rings.append({
            "ring_id": ring.ring_id,
            "cords": cords,
            "state": ring.ring_state.value if hasattr(ring.ring_state, "value") else str(ring.ring_state),
            "coherence": getattr(ring, "ring_coherence", 0.0),
            "quakete_events": getattr(ring, "quakete_events", 0),
        })

    return rings


@router.get("/rings/{ring_id}")
async def get_ring_detail(request: Request, ring_id: str) -> Dict[str, Any]:
    """
    Get full details for a specific Cosmic Relational Ring.
    """
    ring_manager = _get_ring_manager(request)
    if not ring_manager:
        logger.warning("quakete_ring_manager_not_available")
        raise HTTPException(status_code=503, detail="Quakete subsystem not initialized")

    ring = ring_manager.get_ring(ring_id) if hasattr(ring_manager, "get_ring") else None
    if not ring:
        raise HTTPException(status_code=404, detail="Ring not found")

    cords = []
    for cord in ring.all_cords():
        cords.append({
            "fibre_id": cord.fibre_id,
            "fibre_type": cord.fibre_type,
            "current_health": cord.current_health,
            "current_mode": cord.current_mode.value if hasattr(cord.current_mode, "value") else str(cord.current_mode),
            "quaketes_donated": cord.quaketes_donated,
            "quaketes_received": cord.quaketes_received,
            "last_trail_at": cord.last_trail_at.isoformat() if cord.last_trail_at else None,
            "mission_summary": cord.mission_summary,
            "observation_queue_depth": cord.observation_queue_depth,
        })

    return {
        "ring_id": ring.ring_id,
        "cords": cords,
        "state": ring.ring_state.value if hasattr(ring.ring_state, "value") else str(ring.ring_state),
        "coherence": ring.ring_coherence,
        "quakete_events": ring.quakete_events,
        "formed_at": ring.formed_at.isoformat() if hasattr(ring, "formed_at") and ring.formed_at else None,
    }


@router.get("/trail-map")
async def get_trail_map(request: Request) -> Dict[str, Any]:
    """
    Get current trail map (swarm health).
    Returns total_fibres, healthy, requesting, donating, critical, silent, avg_health.
    """
    trail_map = _get_trail_map(request)
    if not trail_map:
        logger.warning("quakete_trail_map_not_available")
        return {
            "total_fibres": 0,
            "healthy": 0,
            "requesting": 0,
            "donating": 0,
            "critical": 0,
            "silent": 0,
            "avg_health": 0.0,
            "_message": "Quakete subsystem not initialized",
        }

    health = trail_map.get_swarm_health()
    return health


@router.get("/trail-map/{fibre_id}")
async def get_fibre_trail_history(
    request: Request,
    fibre_id: str,
    limit: int = Query(10, ge=1, le=100),
) -> Dict[str, Any]:
    """
    Get trail history for a specific fibre.
    Returns last N trail emissions.
    """
    trail_map = _get_trail_map(request)
    if not trail_map:
        raise HTTPException(status_code=503, detail="Quakete subsystem not initialized")

    history = getattr(trail_map, "_trail_history", {})
    fibre_history = history.get(fibre_id, [])
    trails = fibre_history[-limit:] if fibre_history else []

    serialized = []
    for t in trails:
        if hasattr(t, "model_dump"):
            d = t.model_dump(mode="json")
        else:
            d = {"emitted_at": getattr(t, "emitted_at", None)}
            if d["emitted_at"] and hasattr(d["emitted_at"], "isoformat"):
                d["emitted_at"] = d["emitted_at"].isoformat()
        serialized.append(d)

    return {"fibre_id": fibre_id, "trails": serialized, "count": len(serialized)}


@router.get("/transfers")
async def list_quakete_transfers(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    """
    List recent Quakete transfers.
    Returns list of transfer results (from metrics or transfer history).
    """
    metrics = _get_quakete_metrics(request)
    if not metrics:
        logger.warning("quakete_metrics_not_available")
        return []

    summary = metrics.get_summary() if hasattr(metrics, "get_summary") else {}
    transfers = []
    if "recent_transfers" in summary:
        transfers = summary["recent_transfers"][:limit]
    else:
        total = summary.get("total_transfers", 0)
        successful = summary.get("successful_transfers", 0)
        if total > 0:
            transfers.append({
                "total_transfers": total,
                "successful_transfers": successful,
                "total_ions": summary.get("total_ions", 0),
                "total_energy": summary.get("total_energy", 0.0),
                "_aggregate": True,
            })

    return transfers


@router.get("/beams")
async def list_active_beams(request: Request) -> List[Dict[str, Any]]:
    """
    List active particle beams with remaining energy.
    """
    beam_gen = _get_particle_beam_generator(request)
    if not beam_gen:
        logger.warning("particle_beam_generator_not_available")
        return []

    beams: List[Dict[str, Any]] = []
    active = getattr(beam_gen, "_active_beams", {})
    now = datetime.utcnow()

    for target_id, beam in active.items():
        remaining = beam.energy_at(now) if hasattr(beam, "energy_at") else (beam.current_energy or beam.initial_energy)
        beams.append({
            "target_fibre_id": target_id,
            "beam_id": getattr(beam, "beam_id", target_id),
            "initial_energy": beam.initial_energy,
            "remaining_energy": remaining,
            "created_at": beam.created_at.isoformat() if hasattr(beam.created_at, "isoformat") else str(beam.created_at),
            "affected_endpoints": getattr(beam, "affected_endpoints", []),
            "fragments_accelerated": getattr(beam, "fragments_accelerated", 0),
            "observations_delivered": getattr(beam, "observations_delivered", 0),
        })

    return beams


@router.get("/memorials")
async def list_fibre_memorials(request: Request) -> List[Dict[str, Any]]:
    """
    List fibre memorials (lost Fibres whose wisdom is carried by Ring partners).
    """
    memorial_svc = _get_memorial_service(request)
    if not memorial_svc:
        logger.warning("memorial_service_not_available")
        return []

    memorials: List[Dict[str, Any]] = []
    stored = getattr(memorial_svc, "_memorials", {})
    for fid, m in stored.items():
        memorials.append({
            "memorial_id": str(m.memorial_id) if hasattr(m, "memorial_id") else fid,
            "lost_fibre_id": m.lost_fibre_id,
            "lost_fibre_type": m.lost_fibre_type,
            "lost_at": m.lost_at.isoformat() if hasattr(m.lost_at, "isoformat") else str(m.lost_at),
            "last_known_health": m.last_known_health,
            "pending_observations": m.pending_observations,
            "quaketes_received_before_loss": m.quaketes_received_before_loss,
            "carried_by": m.carried_by,
        })

    return memorials


@router.get("/health")
async def quakete_health(request: Request) -> Dict[str, Any]:
    """
    Overall Quakete subsystem health.
    Returns status, total_rings, healthy_rings, distressed_rings,
    active_transfers, active_beams, memorials_count.
    """
    ring_manager = _get_ring_manager(request)
    trail_map = _get_trail_map(request)
    metrics = _get_quakete_metrics(request)
    beam_gen = _get_particle_beam_generator(request)
    memorial_svc = _get_memorial_service(request)

    if not any([ring_manager, trail_map, metrics]):
        return {
            "status": "uninitialized",
            "total_rings": 0,
            "healthy_rings": 0,
            "distressed_rings": 0,
            "active_transfers": 0,
            "active_beams": 0,
            "memorials_count": 0,
            "message": "Quakete subsystem not initialized",
        }

    total_rings = 0
    healthy_rings = 0
    distressed_rings = 0
    if ring_manager:
        all_rings = getattr(ring_manager, "all_rings", None) or getattr(ring_manager, "_rings", {})
        if isinstance(all_rings, dict):
            all_rings = list(all_rings.values())
        total_rings = len(all_rings or [])
        for r in all_rings or []:
            state = getattr(r, "ring_state", None)
            state_val = state.value if hasattr(state, "value") else str(state) if state else ""
            if state_val in ("healthy", "supporting"):
                healthy_rings += 1
            elif state_val in ("strained", "distressed", "rescue", "broken"):
                distressed_rings += 1

    active_beams = 0
    if beam_gen:
        active_beams = getattr(beam_gen, "active_beam_count", len(getattr(beam_gen, "_active_beams", {})))

    memorials_count = 0
    if memorial_svc:
        memorials_count = getattr(memorial_svc, "total_memorials", len(getattr(memorial_svc, "_memorials", {})))

    active_transfers = 0
    if metrics:
        summary = metrics.get_summary() if hasattr(metrics, "get_summary") else {}
        active_transfers = summary.get("total_transfers", 0)

    return {
        "status": "healthy" if total_rings > 0 or active_beams > 0 else "degraded",
        "total_rings": total_rings,
        "healthy_rings": healthy_rings,
        "distressed_rings": distressed_rings,
        "active_transfers": active_transfers,
        "active_beams": active_beams,
        "memorials_count": memorials_count,
    }


@router.post("/trigger-transfer/{fibre_id}")
async def trigger_quakete_transfer(
    request: Request,
    fibre_id: str,
) -> Dict[str, Any]:
    """
    Manually trigger Quakete transfer for a fibre (admin-only).
    Returns transfer result.
    """
    transfer_svc = _get_transfer_service(request)
    if not transfer_svc:
        logger.warning("quakete_transfer_service_not_available")
        raise HTTPException(status_code=503, detail="Quakete transfer service not available")

    try:
        result = await transfer_svc.execute_transfer(fibre_id)
        return {
            "success": result.success,
            "reason": result.reason,
            "ions_transferred": result.ions_transferred,
            "total_energy": result.total_energy,
            "ring_coherence_after": result.ring_coherence_after,
            "recipient_predicted_recovery_seconds": result.recipient_predicted_recovery_seconds,
            "acceleration": result.acceleration.model_dump() if result.acceleration else None,
        }
    except Exception as e:
        logger.exception("quakete_trigger_transfer_failed", fibre_id=fibre_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ─── Phase 7: Mobile Trail Emission ─────────────────────────────────────────


class TrailEmissionRequest(BaseModel):
    """Trail emission from a mobile Fibre."""
    fibre_id: str
    coherence: float = 0.0
    energy: float = 0.0
    mood_valence: float = 0.0
    mode: Optional[str] = None


@router.post("/trail-emission")
async def submit_trail_emission(
    request: Request,
    body: TrailEmissionRequest,
) -> Dict[str, Any]:
    """
    Submit a trail emission from a mobile Fibre.
    Updates the trail map and triggers any needed Quakete responses.
    """
    trail_map = _get_trail_map(request)
    if not trail_map:
        raise HTTPException(status_code=503, detail="Trail map not available")

    try:
        from app.models.quakete import FibreTrailEmission
        emission = FibreTrailEmission(
            fibre_id=body.fibre_id,
            fibre_type=body.mode or "mobile",
            resonance_frequency=body.coherence,
            communication_health=min(1.0, max(0.0, body.energy)),
        )
        trail_map.update(emission)

        # Check if this fibre needs a Quakete transfer
        transfer_svc = _get_transfer_service(request)
        needs_transfer = False
        if transfer_svc and body.coherence < 0.3:
            try:
                needs_transfer = True
                logger.info(
                    "quakete_low_coherence_detected",
                    fibre_id=body.fibre_id,
                    coherence=body.coherence,
                )
            except Exception:
                pass

        return {
            "status": "recorded",
            "fibre_id": body.fibre_id,
            "coherence": body.coherence,
            "needs_transfer": needs_transfer,
        }
    except Exception as e:
        logger.exception("trail_emission_failed", fibre_id=body.fibre_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
