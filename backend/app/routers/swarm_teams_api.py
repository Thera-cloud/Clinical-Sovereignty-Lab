"""
SOVEREIGN SWARM — Swarm Teams & Templates API Router
REST endpoints for Human-Swarm teams and Fibre templates:
  - Team CRUD (create, list, get, deactivate)
  - Fibre template management (list, create, spawn from template)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin

from app.models.fibre import FibreConfig, FibreType
from app.services.fibre_manager import FibreManager
from app.services.exceptions import FibreSpawnException


router = APIRouter(
    prefix="/api/swarm",
    tags=["Swarm Teams & Templates"],
    dependencies=[Depends(require_admin)],
)


# =============================================================================
# REQUEST MODELS
# =============================================================================


class FibreConfigInput(BaseModel):
    """Input for creating a fibre config."""

    fibre_type: str = Field(..., description="Fibre type (e.g. coach_support, foresight_analyst)")
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    domain_tags: List[str] = Field(default_factory=list)
    token_budget_per_hour: int = Field(default=10_000, ge=0)
    max_concurrent_tasks: int = Field(default=3, ge=1)
    wisdom_seed: Dict[str, Any] = Field(default_factory=dict)


class CreateTeamBody(BaseModel):
    """Body for creating a swarm team."""

    team_name: str = Field(..., min_length=1, max_length=128)
    human_id: str = Field(..., min_length=1)
    human_role: str = Field(..., min_length=1)
    fibre_configs: List[FibreConfigInput] = Field(..., min_length=1)


class CreateTemplateBody(BaseModel):
    """Body for creating a fibre template."""

    template_name: str = Field(..., min_length=1, max_length=128)
    fibre_type: str = Field(..., description="Fibre type")
    config: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class SpawnFromTemplateBody(BaseModel):
    """Body for spawning from a template."""

    overrides: Optional[Dict[str, Any]] = None
    spawn_reason: str = ""


# =============================================================================
# HELPERS
# =============================================================================


def _get_fibre_manager(request: Request) -> FibreManager:
    """Get FibreManager from app state."""
    mgr = getattr(request.app.state, "fibre_manager", None)
    if not mgr:
        raise HTTPException(status_code=503, detail="Sovereign Swarm not enabled")
    return mgr


def _serialize_team_row(row: Dict) -> Dict:
    """Convert row to JSON-serializable dict."""
    result = dict(row)
    for k, v in result.items():
        if isinstance(v, UUID):
            result[k] = str(v)
        elif isinstance(v, list) and v and isinstance(v[0], UUID):
            result[k] = [str(x) for x in v]
        elif hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    return result


# =============================================================================
# TEAM ENDPOINTS
# =============================================================================


@router.get("/teams")
async def list_teams(request: Request) -> List[Dict]:
    """
    List all swarm teams.
    Returns active teams by default; includes inactive when querying the DB.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT team_id, team_name, human_id, human_role, fibre_ids, active, metadata, created_at
            FROM swarm_teams
            ORDER BY created_at DESC
        """)
    return [_serialize_team_row(dict(r)) for r in rows]


@router.post("/teams")
async def create_team(request: Request, body: CreateTeamBody) -> Dict:
    """
    Create a new Human-Swarm team.
    Spawns Fibres per config and persists the team to swarm_teams.
    """
    mgr = _get_fibre_manager(request)
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    # Build FibreConfig list
    configs = []
    for fc in body.fibre_configs:
        try:
            fibre_type = FibreType(fc.fibre_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown fibre_type: {fc.fibre_type}. "
                       f"Available: {[t.value for t in FibreType]}",
            )
        config = FibreConfig(
            fibre_type=fibre_type,
            name=fc.name,
            description=fc.description,
            domain_tags=fc.domain_tags,
            token_budget_per_hour=fc.token_budget_per_hour,
            max_concurrent_tasks=fc.max_concurrent_tasks,
            wisdom_seed=fc.wisdom_seed,
        )
        configs.append(config)

    try:
        team = await mgr.create_team(
            team_name=body.team_name,
            human_id=body.human_id,
            human_role=body.human_role,
            fibre_configs=configs,
        )
    except FibreSpawnException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Persist to swarm_teams
    team_id = uuid4()
    fibre_ids = [UUID(fid) for fid in team.get("fibre_ids", [])]
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO swarm_teams (team_id, team_name, human_id, human_role, fibre_ids, active)
            VALUES ($1, $2, $3, $4, $5, TRUE)
        """, team_id, body.team_name, body.human_id, body.human_role, fibre_ids)

    return {
        "team_id": str(team_id),
        "team_name": body.team_name,
        "human_id": body.human_id,
        "human_role": body.human_role,
        "fibre_ids": team.get("fibre_ids", []),
        "fibre_count": team.get("fibre_count", 0),
        "created_at": team.get("created_at"),
    }


@router.get("/teams/{team_id}")
async def get_team_detail(request: Request, team_id: UUID) -> Dict:
    """Get full team detail by team_id."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT team_id, team_name, human_id, human_role, fibre_ids, active, metadata, created_at, updated_at
            FROM swarm_teams
            WHERE team_id = $1
        """, team_id)

    if not row:
        raise HTTPException(status_code=404, detail="Team not found")

    return _serialize_team_row(dict(row))


@router.delete("/teams/{team_id}")
async def deactivate_team(request: Request, team_id: UUID) -> Dict:
    """Deactivate a team. Sets active=FALSE; team remains in storage for audit."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE swarm_teams
            SET active = FALSE, updated_at = NOW()
            WHERE team_id = $1
        """, team_id)

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Team not found")

    return {"deactivated": True, "team_id": str(team_id)}


# =============================================================================
# TEMPLATE ENDPOINTS
# =============================================================================


@router.get("/templates")
async def list_templates(request: Request) -> Dict[str, Any]:
    """
    List fibre templates from both in-memory (FibreManager) and DB (fibre_templates).
    Merges sources; DB entries may not be spawnable until registered.
    """
    mgr = _get_fibre_manager(request)
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    # In-memory templates
    in_memory = FibreManager.get_templates()
    result = {
        "in_memory": {
            name: config.model_dump() if hasattr(config, "model_dump") else str(config)
            for name, config in in_memory.items()
        },
        "database": [],
    }

    # DB templates
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT template_name, fibre_type, config, description, usage_count
            FROM fibre_templates
            ORDER BY template_name
        """)
        for r in rows:
            config = r["config"]
            if isinstance(config, str):
                config = json.loads(config) if config else {}
            result["database"].append({
                "template_name": r["template_name"],
                "fibre_type": r["fibre_type"],
                "config": config,
                "description": r["description"] or "",
                "usage_count": r["usage_count"] or 0,
            })

    return result


@router.post("/templates")
async def create_template(request: Request, body: CreateTemplateBody) -> Dict:
    """
    Create a fibre template.
    Inserts into fibre_templates and registers with FibreManager for immediate spawn.
    """
    mgr = _get_fibre_manager(request)
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        fibre_type = FibreType(body.fibre_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fibre_type: {body.fibre_type}. Available: {[t.value for t in FibreType]}",
        )

    # Build FibreConfig for registration
    config_dict = body.config.copy()
    config_dict.setdefault("fibre_type", body.fibre_type)
    config_dict.setdefault("name", body.template_name)
    config_dict.setdefault("description", body.description)
    config = FibreConfig(
        fibre_type=fibre_type,
        name=config_dict.get("name", body.template_name),
        description=config_dict.get("description", body.description),
        domain_tags=config_dict.get("domain_tags", []),
        token_budget_per_hour=config_dict.get("token_budget_per_hour", 10_000),
        max_concurrent_tasks=config_dict.get("max_concurrent_tasks", 3),
        wisdom_seed=config_dict.get("wisdom_seed", {}),
    )

    # Insert into DB (ensure JSON-serializable config)
    config_json = json.dumps(config.model_dump(), default=str)

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO fibre_templates (template_name, fibre_type, config, description)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (template_name) DO UPDATE SET
                fibre_type = EXCLUDED.fibre_type,
                config = EXCLUDED.config,
                description = EXCLUDED.description,
                updated_at = NOW()
        """, body.template_name, body.fibre_type, config_json, body.description)

    # Register with FibreManager for spawn_from_template
    FibreManager.register_template(body.template_name, config)

    return {
        "template_name": body.template_name,
        "fibre_type": body.fibre_type,
        "status": "created",
    }


@router.post("/templates/{template_name}/spawn")
async def spawn_from_template(
    request: Request,
    template_name: str,
    body: SpawnFromTemplateBody,
) -> Dict:
    """
    Spawn a Fibre from a pre-configured template.
    Supports optional overrides (e.g. name, domain_tags).
    """
    mgr = _get_fibre_manager(request)

    try:
        fibre = await mgr.spawn_from_template(
            template_name=template_name,
            overrides=body.overrides,
            spawn_reason=body.spawn_reason or f"From template: {template_name}",
        )
        return {
            "status": "spawned",
            "fibre_id": str(fibre.fibre_id),
            "name": fibre.name,
            "type": fibre.fibre_type.value,
        }
    except FibreSpawnException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
