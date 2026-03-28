"""
ZEFCP API — Layer 1 Physical Transport Endpoints
Patent Claim 25: Zero-Energy Parasitic BLE Communication.
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.api_server import require_admin

router = APIRouter(
    prefix="/api/zefcp",
    tags=["ZEFCP Transport"],
    dependencies=[Depends(require_admin)],
)
logger = structlog.get_logger(__name__)


# ─── Request Models ─────────────────────────────────────────────────────────

class ZEFCPConfigUpdate(BaseModel):
    """Config updates for an endpoint."""
    endpoint_id: str
    config: Dict[str, Any] = {}


class ZEFCPProvisionRequest(BaseModel):
    """NFC provisioning request payload."""
    device_id: str
    domain_tags: List[str] = []


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_metrics_store(request: Request) -> Optional[Any]:
    """Get ZEFCP metrics store from app state (dict endpoint_id -> ZEFCPMetrics)."""
    return getattr(request.app.state, "zefcp_metrics_store", None)


def _get_assembly_buffers(request: Request) -> Optional[Any]:
    """Get ZEFCP fragment/assembly buffers from app state (dict endpoint_id -> FragmentBuffer)."""
    return getattr(request.app.state, "zefcp_assembly_buffers", None)


def _get_endpoints_registry(request: Request) -> Optional[Any]:
    """Get registered ZEFCP endpoints from app state."""
    return getattr(request.app.state, "zefcp_endpoints", None)


def _get_config_store(request: Request) -> Optional[Any]:
    """Get ZEFCP transport config store from app state."""
    return getattr(request.app.state, "zefcp_config_store", None)


def _get_nfc_provisioner(request: Request) -> Optional[Any]:
    """Get NFC provisioner from app state."""
    return getattr(request.app.state, "zefcp_nfc_provisioner", None)


# ─── Stub Helpers ───────────────────────────────────────────────────────────

def _stub_transport_metrics(endpoint_id: str) -> Dict[str, Any]:
    """Return stub TransportMetrics when service not initialized."""
    now = datetime.now(timezone.utc)
    return {
        "endpoint_id": endpoint_id,
        "period_start": now.isoformat(),
        "period_end": now.isoformat(),
        "total_ble_pdus_scanned": 0,
        "signature_matches": 0,
        "crc_validated": 0,
        "false_positives_discarded": 0,
        "valid_fragments_detected": 0,
        "observations_completed": 0,
        "observations_expired": 0,
        "avg_assembly_time_seconds": 0.0,
        "avg_fragments_per_observation": 0.0,
        "avg_fragment_loss_rate": 0.0,
        "_stub": True,
        "_message": "ZEFCP subsystem not initialized",
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/metrics")
async def get_transport_metrics(
    request: Request,
    endpoint_id: str = Query(..., description="Spider Web endpoint identifier"),
) -> Dict[str, Any]:
    """
    Get transport metrics for a single endpoint.
    Returns TransportMetrics dict. Stub when ZEFCP not initialized.
    """
    metrics_store = _get_metrics_store(request)
    if not metrics_store:
        logger.warning("zefcp_metrics_not_available", endpoint_id=endpoint_id)
        return _stub_transport_metrics(endpoint_id)

    metrics_obj = metrics_store.get(endpoint_id) if isinstance(metrics_store, dict) else None
    if not metrics_obj:
        logger.debug("zefcp_metrics_endpoint_unknown", endpoint_id=endpoint_id)
        return _stub_transport_metrics(endpoint_id)

    now = datetime.now(timezone.utc)
    period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    m = metrics_obj.get_metrics(period_start, now)
    return m.model_dump(mode="json")


@router.get("/metrics/all")
async def get_all_transport_metrics(request: Request) -> List[Dict[str, Any]]:
    """
    Get transport metrics across all ZEFCP endpoints.
    Returns list of TransportMetrics dicts.
    """
    metrics_store = _get_metrics_store(request)
    if not metrics_store:
        logger.warning("zefcp_metrics_store_not_available")
        return []

    results: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if isinstance(metrics_store, dict):
        for ep_id, metrics_obj in metrics_store.items():
            try:
                m = metrics_obj.get_metrics(period_start, now)
                results.append(m.model_dump(mode="json"))
            except Exception as e:
                logger.warning("zefcp_metrics_fetch_failed", endpoint_id=ep_id, error=str(e))
                results.append(_stub_transport_metrics(ep_id))

    return results


@router.get("/assemblies")
async def get_active_assemblies(
    request: Request,
    endpoint_id: Optional[str] = Query(None, description="Filter by endpoint"),
) -> Dict[str, Any]:
    """
    Get active fragment assemblies (pending observations).
    Returns pending_count and list of assembly summaries.
    """
    buffers = _get_assembly_buffers(request)
    if not buffers:
        logger.warning("zefcp_assemblies_not_available")
        return {"pending_count": 0, "assemblies": [], "_message": "ZEFCP subsystem not initialized"}

    assemblies: List[Dict[str, Any]] = []
    total_pending = 0

    if isinstance(buffers, dict):
        for ep_id, buf in buffers.items():
            if endpoint_id is not None and ep_id != endpoint_id:
                continue
            if not hasattr(buf, "pending"):
                continue
            now = time.time()
            for key, slot in buf.pending.items():
                total_pending += 1
                age_seconds = now - slot.last_fragment_at if hasattr(slot, "last_fragment_at") else 0.0
                assemblies.append({
                    "key": key,
                    "total": slot.total_fragments if hasattr(slot, "total_fragments") else 0,
                    "received": len(slot.received_sequences) if hasattr(slot, "received_sequences") else 0,
                    "age_seconds": round(age_seconds, 2),
                    "endpoint_id": ep_id,
                })

    return {"pending_count": total_pending, "assemblies": assemblies}


@router.get("/endpoints")
async def list_endpoints(request: Request) -> List[Dict[str, Any]]:
    """
    List registered ZEFCP Spider Web endpoints.
    Returns endpoint_id, environment, avg_density, last_active.
    """
    registry = _get_endpoints_registry(request)
    if not registry:
        logger.warning("zefcp_endpoints_not_available")
        return []

    endpoints: List[Dict[str, Any]] = []
    if isinstance(registry, list):
        for ep in registry:
            if isinstance(ep, dict):
                endpoints.append(ep)
            else:
                endpoints.append({
                    "endpoint_id": getattr(ep, "endpoint_id", str(ep)),
                    "environment": getattr(ep, "environment", "unknown"),
                    "avg_density": getattr(ep, "avg_density", 0.0),
                    "last_active": getattr(ep, "last_active", None),
                })
    elif isinstance(registry, dict):
        for ep_id, ep_data in registry.items():
            data = ep_data if isinstance(ep_data, dict) else {}
            endpoints.append({
                "endpoint_id": ep_id,
                "environment": data.get("environment", "unknown"),
                "avg_density": data.get("avg_density", 0.0),
                "last_active": data.get("last_active"),
            })

    return endpoints


@router.post("/config")
async def update_transport_config(
    request: Request,
    body: ZEFCPConfigUpdate,
) -> Dict[str, Any]:
    """
    Update transport config for an endpoint.
    Returns updated config.
    """
    config_store = _get_config_store(request)
    if not config_store:
        logger.warning("zefcp_config_store_not_available")
        raise HTTPException(status_code=503, detail="ZEFCP subsystem not initialized")

    if not isinstance(config_store, dict):
        raise HTTPException(status_code=503, detail="ZEFCP config store not available")

    ep_id = body.endpoint_id
    current = config_store.get(ep_id)
    if current is None:
        from app.models.zefcp import BLETransportConfig
        current = BLETransportConfig()

    updates = body.config
    if isinstance(current, dict):
        merged = {**current, **updates}
        config_store[ep_id] = merged
        return {"endpoint_id": ep_id, "config": merged}
    else:
        merged = current.model_copy(update=updates)
        config_store[ep_id] = merged
        return {"endpoint_id": ep_id, "config": merged.model_dump()}


@router.get("/health")
async def zefcp_health(request: Request) -> Dict[str, Any]:
    """
    ZEFCP subsystem health.
    Returns status, total_endpoints, active_endpoints, observations_last_hour, avg_fragment_loss.
    """
    registry = _get_endpoints_registry(request)
    metrics_store = _get_metrics_store(request)

    if not registry and not metrics_store:
        return {
            "status": "uninitialized",
            "total_endpoints": 0,
            "active_endpoints": 0,
            "observations_last_hour": 0,
            "avg_fragment_loss": 0.0,
            "message": "ZEFCP subsystem not initialized",
        }

    total = 0
    if isinstance(registry, list):
        total = len(registry)
    elif isinstance(registry, dict):
        total = len(registry)

    obs_hour = 0
    avg_loss = 0.0
    if metrics_store and isinstance(metrics_store, dict):
        for m in metrics_store.values():
            if hasattr(m, "_counters"):
                obs_hour += m._counters.get("observations_completed", 0)
            if hasattr(m, "_assembly_loss_rates") and m._assembly_loss_rates:
                avg_loss = sum(m._assembly_loss_rates) / len(m._assembly_loss_rates)

    return {
        "status": "healthy" if total > 0 else "degraded",
        "total_endpoints": total,
        "active_endpoints": total,  # Simplified; could track last-seen
        "observations_last_hour": obs_hour,
        "avg_fragment_loss": round(avg_loss, 4),
    }


@router.post("/provision")
async def trigger_nfc_provisioning(
    request: Request,
    body: ZEFCPProvisionRequest,
) -> Dict[str, Any]:
    """
    Trigger NFC provisioning for a device.
    Returns provisioning payload summary (no secrets).
    """
    provisioner = _get_nfc_provisioner(request)
    if not provisioner:
        logger.warning("zefcp_nfc_provisioner_not_available")
        raise HTTPException(status_code=503, detail="ZEFCP NFC provisioning not available")

    try:
        payload = await provisioner.provision_device(
            device_id=body.device_id,
            domain_tags=body.domain_tags or None,
        )
        return {
            "device_id": payload.device_id,
            "assigned_domain_tags": payload.assigned_domain_tags,
            "transport_config": payload.transport_config.model_dump() if payload.transport_config else {},
            "mesh_endpoint_config_keys": list(payload.mesh_endpoint_config.keys()) if payload.mesh_endpoint_config else [],
            "payload_size_bytes": len(payload.swarm_secret_encrypted) + len(payload.identity_signature),
            "message": "Provisioning payload generated; transfer via NFC tap.",
        }
    except Exception as e:
        logger.exception("zefcp_provision_failed", device_id=body.device_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ─── Phase 7: Mobile Fragment Ingestion ──────────────────────────────────────


class FragmentIngestRequest(BaseModel):
    """Fragment uploaded from a mobile device."""
    fragment_id: str
    observation_id: str
    sequence_number: int
    total_fragments: int
    payload_b64: str  # Base64-encoded fragment payload
    endpoint_id: Optional[str] = None
    signature_b64: Optional[str] = None


class CapacityQueryRequest(BaseModel):
    """Capacity query from a mobile device."""
    endpoint_id: Optional[str] = None
    max_fragment_size: Optional[int] = None


@router.post("/fragments")
async def ingest_fragment(
    request: Request,
    body: FragmentIngestRequest,
) -> Dict[str, Any]:
    """
    Ingest a BLE fragment captured by a mobile device.
    The fragment is added to the assembly buffer for reconstruction.
    """
    buffers = getattr(request.app.state, "zefcp_assembly_buffers", None)
    if not buffers:
        raise HTTPException(status_code=503, detail="ZEFCP assembly buffers not available")

    endpoint_id = body.endpoint_id or "primary"
    buffer = buffers.get(endpoint_id)
    if not buffer:
        raise HTTPException(status_code=404, detail=f"No buffer for endpoint: {endpoint_id}")

    try:
        import base64
        from app.models.zefcp import MicroFragment

        raw_payload = base64.b64decode(body.payload_b64)
        sig_byte = raw_payload[0] if raw_payload else 0

        # Build a MicroFragment from the request body
        fragment = MicroFragment(
            signature=sig_byte,
            sequence=body.sequence_number,
            total=body.total_fragments,
            observation_id=hash(body.observation_id) & 0xFF,
            payload=raw_payload,
            checksum=raw_payload[-1] if raw_payload else 0,
        )

        # Ingest into fragment buffer (async) — returns assembled observation or None
        status = "received"
        try:
            result = await buffer.ingest(fragment)
            if result is not None:
                status = "assembled"
        except Exception:
            status = "buffered"

        # Record metric
        metrics_store = getattr(request.app.state, "zefcp_metrics_store", {})
        metric = metrics_store.get(endpoint_id)
        if metric:
            try:
                metric.record_detection(True)
            except Exception:
                pass

        return {
            "status": status,
            "fragment_id": body.fragment_id,
            "observation_id": body.observation_id,
            "endpoint_id": endpoint_id,
        }
    except Exception as e:
        logger.exception("zefcp_fragment_ingest_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/capacity")
async def query_capacity(
    request: Request,
    body: CapacityQueryRequest,
) -> Dict[str, Any]:
    """
    Query the current ZEFCP transport capacity for a given endpoint.
    Returns fragment budget, queue depth, and estimated throughput.
    """
    endpoint_id = body.endpoint_id or "primary"
    buffers = getattr(request.app.state, "zefcp_assembly_buffers", None)
    metrics_store = getattr(request.app.state, "zefcp_metrics_store", {})

    buffer = buffers.get(endpoint_id) if buffers else None
    metric = metrics_store.get(endpoint_id) if metrics_store else None

    pending_count = 0
    if buffer and hasattr(buffer, '_pending'):
        pending_count = len(buffer._pending)

    total_detected = 0
    if metric and hasattr(metric, '_total_detected'):
        total_detected = metric._total_detected

    return {
        "endpoint_id": endpoint_id,
        "pending_assemblies": pending_count,
        "total_fragments_detected": total_detected,
        "max_fragment_size": body.max_fragment_size or 27,
        "available": buffer is not None,
    }


@router.get("/embed-queue/{fibre_id}")
async def get_embed_queue(
    request: Request,
    fibre_id: str,
    max_fragments: int = Query(10, ge=1, le=100),
) -> Dict[str, Any]:
    """
    Get fragments queued for outbound BLE embedding by a mobile Fibre.
    Returns up to max_fragments that the device should advertise.
    """
    # The embed queue is managed via the swarm relay or a local queue
    # For now, return an empty queue that mobile devices will poll
    return {
        "fibre_id": fibre_id,
        "fragments": [],
        "count": 0,
        "message": "No fragments queued for embedding",
    }
