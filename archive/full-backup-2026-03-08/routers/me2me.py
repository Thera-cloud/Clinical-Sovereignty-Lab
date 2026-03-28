"""
SOVEREIGN SWARM — Me-2-Me REST/WebSocket API
Endpoints for consent management, avatar interaction,
and legacy vault operations.

All endpoints require TOP_TIER (Sovereign Circle) subscription.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import get_current_user_id

logger = logging.getLogger("routers.me2me")

router = APIRouter(
    prefix="/api/me2me",
    tags=["me2me"],
    dependencies=[Depends(get_current_user_id)],
)


# =============================================================================
# TIER GATING — Me2Me requires TOP_TIER subscription
# =============================================================================

def _load_registry() -> Dict:
    """Load user registry for tier checks."""
    from app.config import settings as _s
    reg_path = Path(_s.DATA_DIR) / "user_registry.json"
    if reg_path.is_file():
        try:
            return json.loads(reg_path.read_text())
        except Exception:
            pass
    return {}


async def _require_top_tier(user_id: str, request: Request = None) -> None:
    """Verify the user has TOP_TIER (Sovereign Circle) subscription.
    PG-first with JSON fallback. Raises HTTP 403 if not."""
    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT tier, profile_data FROM users "
                    "WHERE hardware_id = $1 AND deleted_at IS NULL",
                    user_id,
                )
                if row:
                    plan = (row["tier"] or "").upper()
                    pd = row.get("profile_data") or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    if not plan:
                        plan = (pd.get("subscription_plan") or "").upper()
                    if plan in ("TOP_TIER", "SOVEREIGN_CIRCLE"):
                        return
                    raise HTTPException(
                        403,
                        "Me2Me features require Sovereign Circle (TOP_TIER) subscription. "
                        f"Current plan: {plan or 'TRIAL'}",
                    )
                raise HTTPException(404, "User not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("_require_top_tier PG check failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = _load_registry()
    for _k, entry in registry.items():
        profile = entry.get("profile", {})
        if profile.get("hardware_id") == user_id:
            plan = (profile.get("subscription_plan") or "").upper()
            if plan in ("TOP_TIER", "SOVEREIGN_CIRCLE"):
                return
            raise HTTPException(
                403,
                "Me2Me features require Sovereign Circle (TOP_TIER) subscription. "
                f"Current plan: {plan or 'TRIAL'}",
            )
    raise HTTPException(404, "User not found")


# =============================================================================
# REQUEST MODELS
# =============================================================================

class ConsentRequest(BaseModel):
    user_id: str
    level: str  # observe, preserve, interact
    witness_signature: Optional[str] = None


class RevokeConsentRequest(BaseModel):
    user_id: str


class VisitorSessionRequest(BaseModel):
    avatar_id: str
    visitor_id: str
    visitor_relationship: str = ""


class VisitorMessageRequest(BaseModel):
    session_id: str
    message: str


class GrowthLayerRequest(BaseModel):
    avatar_id: str
    knowledge_source: str
    knowledge_type: str = "general"
    content: str


class MigrationRequest(BaseModel):
    user_id: str
    trigger: str = "manual"
    guardian_id: Optional[str] = None


# =============================================================================
# CONSENT ENDPOINTS
# =============================================================================

@router.post("/consent/grant")
async def grant_consent(req: ConsentRequest, request: Request):
    """Grant Me-2-Me consent at the specified level."""
    await _require_top_tier(req.user_id, request)
    consent_service = getattr(request.app.state, "me2me_consent", None)
    if not consent_service:
        raise HTTPException(503, "Me-2-Me consent service not available")

    from app.models.me2me import ConsentLevel
    try:
        level = ConsentLevel(req.level)
    except ValueError:
        raise HTTPException(400, f"Invalid consent level: {req.level}")

    record = await consent_service.grant_consent(
        user_id=req.user_id,
        level=level,
        witness_signature=req.witness_signature,
    )
    return {"status": "granted", "consent_id": record.consent_id, "level": record.level.value}


@router.post("/consent/revoke")
async def revoke_consent(req: RevokeConsentRequest, request: Request):
    """Revoke all Me-2-Me consent."""
    await _require_top_tier(req.user_id, request)
    consent_service = getattr(request.app.state, "me2me_consent", None)
    if not consent_service:
        raise HTTPException(503, "Me-2-Me consent service not available")

    record = await consent_service.revoke_consent(req.user_id)
    return {"status": "revoked", "user_id": req.user_id}


@router.get("/consent/{user_id}")
async def get_consent(user_id: str, request: Request):
    """Get current consent status."""
    await _require_top_tier(user_id, request)
    consent_service = getattr(request.app.state, "me2me_consent", None)
    if not consent_service:
        raise HTTPException(503, "Me-2-Me consent service not available")

    record = await consent_service.get_consent(user_id)
    if not record:
        return {"user_id": user_id, "status": "none"}
    return {
        "user_id": user_id,
        "level": record.level.value,
        "status": record.status.value,
        "granted_at": record.granted_at.isoformat() if record.granted_at else None,
        "renewal_due": record.renewal_due.isoformat() if record.renewal_due else None,
    }


# =============================================================================
# AVATAR ENDPOINTS
# =============================================================================

@router.post("/session/start")
async def start_visitor_session(req: VisitorSessionRequest, request: Request):
    """Start a visitor session with a Me-2-Me avatar."""
    await _require_top_tier(req.visitor_id, request)
    interaction = getattr(request.app.state, "ancestral_interaction", None)
    if not interaction:
        raise HTTPException(503, "Me-2-Me interaction service not available")

    result = await interaction.start_session(
        avatar_id=req.avatar_id,
        visitor_id=req.visitor_id,
        visitor_relationship=req.visitor_relationship,
    )
    return result


@router.post("/session/message")
async def send_visitor_message(req: VisitorMessageRequest, request: Request):
    """Send a message in an active visitor session."""
    interaction = getattr(request.app.state, "ancestral_interaction", None)
    if not interaction:
        raise HTTPException(503, "Me-2-Me interaction service not available")

    result = await interaction.send_message(req.session_id, req.message)
    if not result:
        raise HTTPException(404, "Session not found or expired")
    return result


@router.post("/session/{session_id}/end")
async def end_visitor_session(session_id: str, request: Request):
    """End a visitor session."""
    interaction = getattr(request.app.state, "ancestral_interaction", None)
    if not interaction:
        raise HTTPException(503, "Me-2-Me interaction service not available")

    result = await interaction.end_session(session_id)
    if not result:
        raise HTTPException(404, "Session not found")
    return result


# =============================================================================
# GROWTH ENGINE ENDPOINTS
# =============================================================================

@router.post("/growth/add")
async def add_growth_layer(req: GrowthLayerRequest, request: Request):
    """Add a post-mortem knowledge layer to an avatar. Requires TOP_TIER."""
    await _require_top_tier(req.avatar_id, request)
    growth = getattr(request.app.state, "growth_engine", None)
    if not growth:
        raise HTTPException(503, "Me-2-Me growth engine not available")

    layer = await growth.add_knowledge(
        avatar_id=req.avatar_id,
        knowledge_source=req.knowledge_source,
        knowledge_type=req.knowledge_type,
        content=req.content,
    )
    return {"layer_id": layer.layer_id, "type": layer.knowledge_type}


# =============================================================================
# MIGRATION ENDPOINTS
# =============================================================================

@router.post("/migration/initiate")
async def initiate_migration(req: MigrationRequest, request: Request):
    """Initiate the organic-to-inorganic migration process."""
    await _require_top_tier(req.user_id, request)
    migration = getattr(request.app.state, "migration_service", None)
    if not migration:
        raise HTTPException(503, "Me-2-Me migration service not available")

    record = await migration.initiate_migration(
        user_id=req.user_id,
        trigger=req.trigger,
        guardian_id=req.guardian_id,
    )
    if not record:
        raise HTTPException(403, "Migration denied — check consent level")
    return {
        "migration_id": record.migration_id,
        "phase": record.phase.value,
        "readiness": record.avatar_readiness_score,
    }


@router.post("/migration/{migration_id}/advance")
async def advance_migration(migration_id: str, request: Request):
    """Advance to the next migration phase."""
    migration = getattr(request.app.state, "migration_service", None)
    if not migration:
        raise HTTPException(503, "Me-2-Me migration service not available")

    record = await migration.advance_phase(migration_id)
    if not record:
        raise HTTPException(404, "Migration not found")
    return {"migration_id": record.migration_id, "phase": record.phase.value}


# =============================================================================
# AVATAR ACTIVATION + CRYSTAL RETRIEVAL
# =============================================================================

@router.post("/avatar/{user_id}/activate")
async def activate_avatar(user_id: str, request: Request):
    """Activate a Me-2-Me avatar for a user."""
    await _require_top_tier(user_id, request)
    avatar = getattr(request.app.state, "avatar_core", None)
    if not avatar:
        raise HTTPException(503, "Avatar service not available")

    result = await avatar.activate_avatar(user_id)
    if not result:
        raise HTTPException(404, "Avatar not found or activation failed")
    return {"status": "activated", "user_id": user_id}


@router.get("/crystal/{user_id}")
async def get_crystal(user_id: str, request: Request, version: Optional[int] = None):
    """Get the latest (or specific version) identity crystal for a user."""
    await _require_top_tier(user_id, request)
    db = request.app.state.db_pool
    if not db:
        raise HTTPException(503, "Database not available")

    try:
        async with db.acquire() as conn:
            if version:
                row = await conn.fetchrow(
                    "SELECT * FROM me2me_identity_crystals WHERE user_id = $1 AND crystal_version = $2",
                    user_id, version,
                )
            else:
                row = await conn.fetchrow(
                    """SELECT * FROM me2me_identity_crystals
                    WHERE user_id = $1 ORDER BY crystal_version DESC LIMIT 1""",
                    user_id,
                )
            if not row:
                raise HTTPException(404, "Crystal not found")
            return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Crystal retrieval failed: {e}")


@router.get("/crystal/{user_id}/versions")
async def list_crystal_versions(user_id: str, request: Request):
    """List all crystal versions for a user."""
    await _require_top_tier(user_id, request)
    db = request.app.state.db_pool
    try:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT crystal_id, crystal_version, confidence_score, synthesized_at
                FROM me2me_identity_crystals WHERE user_id = $1
                ORDER BY crystal_version DESC""",
                user_id,
            )
            return {"crystals": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(500, f"Crystal listing failed: {e}")


# =============================================================================
# VAULT INTEGRITY
# =============================================================================

@router.get("/vault/{user_id}/integrity")
async def check_vault_integrity(user_id: str, request: Request):
    """Check Me-2-Me vault integrity for a user."""
    await _require_top_tier(user_id, request)
    vault = getattr(request.app.state, "me2me_vault", None)
    if not vault:
        raise HTTPException(503, "Me-2-Me vault service not available")

    integrity = await vault.check_integrity(user_id)
    return {"user_id": user_id, "integrity": integrity}


# =============================================================================
# FAMILY FABRIC CRUD
# =============================================================================

class FabricCreateRequest(BaseModel):
    family_id: str
    member_avatars: Dict[str, str]


class SharedMemoryRequest(BaseModel):
    memory: Dict[str, Any]


@router.post("/fabric/create")
async def create_fabric(req: FabricCreateRequest, request: Request):
    """Create a new family fabric. Requires TOP_TIER for at least one member."""
    for avatar_user_id in req.member_avatars.values():
        try:
            await _require_top_tier(avatar_user_id, request)
            break
        except HTTPException:
            continue
    else:
        raise HTTPException(403, "Family fabric requires at least one Sovereign Circle member")
    fabric_svc = getattr(request.app.state, "family_fabric", None)
    if not fabric_svc:
        raise HTTPException(503, "Family fabric service not available")

    fabric = await fabric_svc.create_fabric(req.family_id, req.member_avatars)
    return {"fabric_id": fabric.fabric_id, "family_id": fabric.family_id}


@router.get("/fabric/{family_id}")
async def get_fabric(family_id: str, request: Request):
    """Get a family fabric by family ID."""
    fabric_svc = getattr(request.app.state, "family_fabric", None)
    if not fabric_svc:
        raise HTTPException(503, "Family fabric service not available")

    fabric = await fabric_svc.get_fabric(family_id)
    if not fabric:
        raise HTTPException(404, "Family fabric not found")
    return fabric.model_dump()


@router.post("/fabric/{fabric_id}/memory")
async def add_shared_memory(fabric_id: str, req: SharedMemoryRequest, request: Request):
    """Add a shared memory to a family fabric."""
    fabric_svc = getattr(request.app.state, "family_fabric", None)
    if not fabric_svc:
        raise HTTPException(503, "Family fabric service not available")

    ok = await fabric_svc.add_shared_memory(fabric_id, req.memory)
    if not ok:
        raise HTTPException(500, "Failed to add shared memory")
    return {"status": "added", "fabric_id": fabric_id}


# =============================================================================
# TRUST CRUD
# =============================================================================

class TrustCreateRequest(BaseModel):
    user_id: str
    trust_type: str = "standard"


@router.post("/trust/create")
async def create_trust(req: TrustCreateRequest, request: Request):
    """Create a Sovereign Legacy Trust."""
    await _require_top_tier(req.user_id, request)
    trust_mgr = getattr(request.app.state, "trust_manager", None)
    if not trust_mgr:
        raise HTTPException(503, "Trust manager not available")

    trust = await trust_mgr.create_trust(req.user_id, trust_type=req.trust_type)
    if not trust:
        raise HTTPException(403, "Trust creation denied — check consent level")
    return {"trust_id": trust.trust_id, "user_id": req.user_id}


@router.get("/trust/{user_id}")
async def get_trust(user_id: str, request: Request):
    """Get the Sovereign Legacy Trust for a user."""
    await _require_top_tier(user_id, request)
    trust_mgr = getattr(request.app.state, "trust_manager", None)
    if not trust_mgr:
        raise HTTPException(503, "Trust manager not available")

    trust = await trust_mgr.get_trust(user_id)
    if not trust:
        raise HTTPException(404, "Trust not found")
    return trust.model_dump()


# =============================================================================
# GROWTH LAYERS
# =============================================================================

@router.get("/growth/{avatar_id}/layers")
async def get_growth_layers(avatar_id: str, request: Request):
    """Get all growth layers for an avatar."""
    await _require_top_tier(avatar_id, request)
    db = request.app.state.db_pool
    try:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM me2me_growth_layers
                WHERE avatar_id = $1 ORDER BY added_at DESC""",
                avatar_id,
            )
            return {"layers": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(500, f"Growth layers retrieval failed: {e}")


# =============================================================================
# HEALTH + LEGACY EXPORT
# =============================================================================

@router.get("/health")
async def me2me_health(request: Request):
    """Health check for Me2Me subsystem."""
    services = {}
    for svc_name in ("me2me_consent", "me2me_vault", "imprint_accumulator",
                     "identity_crystallizer", "avatar_core", "family_fabric",
                     "trust_manager"):
        services[svc_name] = getattr(request.app.state, svc_name, None) is not None
    return {"status": "ok", "services": services}


@router.get("/export/{hw_id}")
async def export_legacy(hw_id: str, request: Request):
    """Export a client's full Me2Me legacy: memory, imprints, crystals, and story data."""
    await _require_top_tier(hw_id, request)
    db = getattr(request.app.state, "db_pool", None)

    bundle: Dict[str, Any] = {
        "exported_at": datetime.utcnow().isoformat(),
        "hardware_id": hw_id,
        "memory_entries": [],
        "imprints": [],
        "crystals": [],
        "story_sessions": [],
    }

    # Memory entries from PostgreSQL (primary) with JSON fallback
    try:
        _me2me_db = getattr(request.app.state, "db_pool", None)
        if _me2me_db:
            async with _me2me_db.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_text, ai_text, session_id, created_at "
                    "FROM conversation_history WHERE user_id = $1 "
                    "ORDER BY created_at ASC", hw_id)
            bundle["memory_entries"] = [
                {"user": r["user_text"], "ai": r["ai_text"],
                 "session_id": r["session_id"],
                 "timestamp": str(r["created_at"])}
                for r in rows
            ]
        else:
            data_dir = Path(getattr(request.app.state, "storage_root", "/app/data"))
            mem_path = data_dir / "Clients" / hw_id / "memory.json"
            if not mem_path.exists():
                mem_path = Path("/app/data/Clients") / hw_id / "memory.json"
            if mem_path.exists():
                raw = mem_path.read_text()
                bundle["memory_entries"] = json.loads(raw) if raw.strip() else []
    except Exception as e:
        logger.warning("export_legacy: memory read failed: %s", e)

    if db:
        # Imprints from PG
        try:
            rows = await db.fetch(
                "SELECT * FROM me2me_imprint_entries WHERE user_id = $1 ORDER BY captured_at",
                hw_id,
            )
            bundle["imprints"] = [
                {k: (str(v) if isinstance(v, datetime) else v) for k, v in dict(r).items()}
                for r in rows
            ]
        except Exception as e:
            logger.warning("export_legacy: imprints query failed: %s", e)

        # Identity crystals from PG
        try:
            rows = await db.fetch(
                "SELECT * FROM me2me_identity_crystals WHERE user_id = $1 ORDER BY synthesized_at",
                hw_id,
            )
            bundle["crystals"] = [
                {k: (str(v) if isinstance(v, datetime) else v) for k, v in dict(r).items()}
                for r in rows
            ]
        except Exception as e:
            logger.warning("export_legacy: crystals query failed: %s", e)

    # Story sessions (grouped memory entries)
    from collections import OrderedDict
    sessions_map: OrderedDict = OrderedDict()
    for entry in bundle["memory_entries"]:
        key = entry.get("session_id") or entry.get("timestamp", "")[:10]
        if key not in sessions_map:
            sessions_map[key] = []
        sessions_map[key].append(entry)
    for key, entries in sessions_map.items():
        bundle["story_sessions"].append({
            "session_key": key,
            "date": entries[0].get("timestamp", "")[:10] if entries else key,
            "entry_count": len(entries),
        })

    bundle["total_memory_entries"] = len(bundle["memory_entries"])
    bundle["total_imprints"] = len(bundle["imprints"])
    bundle["total_crystals"] = len(bundle["crystals"])
    bundle["total_story_sessions"] = len(bundle["story_sessions"])

    return bundle
