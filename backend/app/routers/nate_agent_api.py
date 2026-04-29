"""
Nate Agent API — Dual-CLI repair proposals, source-code requests, and innovation proposals.

Two auth tiers:
  - Admin endpoints (require_admin): list pending, approve/reject, history, corrective request,
    innovation proposal management, extension management
  - CLI endpoints (CLI service token): submit proposal, submit source request, check status,
    write completion report, store/recall blob, health, internet search request/approve,
    submit innovation proposals

CLI tokens are set via env vars CLI_CLOUD_TOKEN and CLI_MAC_TOKEN.
Red zone tables/columns are enforced server-side on all proposal and source-request submissions.
Audit-runner identity recognized via CLI_AUDIT_TOKEN for nightly auto-repair proposals.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Request, Header
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List, Literal
from datetime import datetime, timedelta, timezone
import logging
import re
import uuid
import os
import json
import asyncio
import hashlib

from app.services.api_server import require_admin
from app.services.nevedal_engine import (
    CoherenceImpactAssessment,
    ViolationTaxonomy,
    SystemCoherenceProxy,
)
from app.services.evaluation_battery import EvaluationBattery, DOMAINS

logger = logging.getLogger("nate.agent")

# Lazy-connected async Redis for crystal system status reads / control pub/sub
_crystal_redis = None

async def _get_crystal_redis():
    global _crystal_redis
    if _crystal_redis is not None:
        try:
            await _crystal_redis.ping()
            return _crystal_redis
        except Exception:
            _crystal_redis = None
    try:
        import redis.asyncio as aioredis
        _redis_url = os.getenv("REDIS_URL", "")
        _redis_pw = os.getenv("REDIS_PASSWORD", "")
        if _redis_url:
            _crystal_redis = aioredis.from_url(
                _redis_url, decode_responses=True, socket_connect_timeout=5,
            )
        else:
            _crystal_redis = aioredis.Redis(
                host=os.getenv("REDIS_HOST", "redis"), port=6379,
                password=_redis_pw or None,
                decode_responses=True, socket_connect_timeout=5,
            )
        await _crystal_redis.ping()
    except Exception as e:
        logger.warning("Crystal Redis connect failed: %s", e)
        _crystal_redis = None
    return _crystal_redis

_CLI_CLOUD_TOKEN = os.getenv("CLI_CLOUD_TOKEN", "").strip()
_CLI_MAC_TOKEN = os.getenv("CLI_MAC_TOKEN", "").strip()
_CLI_AUDIT_TOKEN = os.getenv("CLI_AUDIT_TOKEN", "").strip()
_RERUN_ON_CLI_REPAIR = (os.getenv("NIGHTLY_AUDIT_RERUN_ON_CLI_REPAIR", "true").strip().lower() != "false")

_INNOVATION_RATE_LIMIT: Dict[str, List[float]] = {}
_INNOVATION_RATE_WINDOW = 86400
_INNOVATION_RATE_MAX = 10

_ADMIN_EMAIL = "admin_nevedalnj@sovereignsanctuary.net"
_COMMAND_TERMINAL_URL = "https://command.sovereignsanctuary.net/skyeye.html#command-terminal"

AUTHORITY_GATES = {
    "autonomous_infrastructure_repairs": {"min_score": 80, "domain_required": "systems_management"},
    "therapeutic_advisory": {"min_score": 85, "domain_required": "therapeutic_comprehension"},
    "lnfab_execution": {"min_score": 90, "all_domains_required": True},
    "fine_tune_proposals": {"min_score": 90, "clinical_review_required": True},
    "compliance_parameter_updates": {"min_score": 90, "immutable_layer_verified": True},
}

MODE_BEHAVIOR_TAGS = {
    "plan": "NO-DEPLOY",
    "ask": "NO-DEPLOY",
    "debug": "NO-EDIT",
    "ln_fab": "LIVE EXECUTION",
}

RED_ZONE_TABLES = frozenset({
    "users", "webauthn", "totp", "password_hash", "profile_data",
    "login_attempts", "password_reset_tokens",
})
RED_ZONE_COLUMNS = frozenset({
    "password_hash", "totp_secret", "totp_enabled", "sms_verified",
    "webauthn_enabled", "webauthn_credentials", "webauthn_challenge",
    "sentinel_frozen", "webauthn_challenge_issued_at",
    "webauthn_auth_challenge", "webauthn_auth_challenge_issued_at",
})

READ_ALLOWLISTS = {
    "cli-cloud": frozenset({
        "backend/app/services/",
        "backend/app/routers/",
        "backend/app/main.py",
        "backend/app/middleware/",
        "backend/migrations/",
        "cloudflare/",
        "docker-compose.prod.yml",
        "docker-compose.yml",
        "scripts/",
        "requirements.txt",
    }),
    "cli-mac": frozenset({
        "backend/app/services/",
        "backend/app/routers/",
        "backend/app/main.py",
        "backend/app/websocket/",
        "backend/migrations/",
        "mobile/lib/",
        "mobile/pubspec.yaml",
        "dashboard/",
        "scripts/",
        "requirements.txt",
    }),
}

_RED_ZONE_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(t) for t in RED_ZONE_TABLES) + r')\b',
    re.IGNORECASE,
)
_RED_ZONE_COL_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in RED_ZONE_COLUMNS) + r')\b',
    re.IGNORECASE,
)


def _check_red_zone(target: Optional[str], action_text: str, plan_text: str = "") -> Optional[str]:
    """Return a rejection reason if any text references a red-zone table or column."""
    for label, text in [("target", target or ""), ("proposed_action", action_text), ("plan", plan_text)]:
        m = _RED_ZONE_PATTERN.search(text)
        if m:
            return f"Red zone violation: '{m.group()}' table referenced in {label}"
        m = _RED_ZONE_COL_PATTERN.search(text)
        if m:
            return f"Red zone violation: '{m.group()}' column referenced in {label}"
    return None


def _check_read_allowlist(cli_id: str, path: str) -> bool:
    """Return True if the path is within the CLI's read allowlist."""
    allowed = READ_ALLOWLISTS.get(cli_id, frozenset())
    return any(path.startswith(prefix) for prefix in allowed)


# ── CLI Auth Dependency ──

def _resolve_cli_identity(authorization: Optional[str] = Header(None)) -> str:
    """Validate CLI service token and return cli identity ('cli-cloud' or 'cli-mac')."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    if _CLI_CLOUD_TOKEN and token == _CLI_CLOUD_TOKEN:
        return "cli-cloud"
    if _CLI_MAC_TOKEN and token == _CLI_MAC_TOKEN:
        return "cli-mac"
    if _CLI_AUDIT_TOKEN and token == _CLI_AUDIT_TOKEN:
        return "audit-runner"
    raise HTTPException(status_code=403, detail="Invalid CLI token")


# ── Routers ──

router = APIRouter(
    prefix="/api/nate-agent",
    tags=["nate-agent"],
    dependencies=[Depends(require_admin)],
)

cli_router = APIRouter(
    prefix="/api/nate-agent/cli",
    tags=["nate-agent-cli"],
)

exa_public_router = APIRouter(
    prefix="/api/nate-agent/exa",
    tags=["nate-agent-exa"],
)


# ── Request/response models ──

class ApproveRejectBody(BaseModel):
    id: str = Field(..., description="repair_proposal id or source_repair_request id (UUID)")
    type: Literal["operational", "source"] = Field(..., description="operational = repair_proposals, source = source_repair_requests")
    approved: bool = Field(..., description="true = approve, false = reject")
    admin_note: Optional[str] = None


class CorrectiveRequestBody(BaseModel):
    parent_build_id: str = Field(..., description="build_id of the completed build to correct")
    executor_cli: Literal["cloud", "mac"] = Field(..., description="CLI that performed the original work")
    description: str = Field(..., description="What to correct")


class SubmitProposalBody(BaseModel):
    repair_type: str = Field(..., description="Type: kv_repair, tunnel_fix, lb_adjust, vram_cleanup, compliance, etc.")
    description: str = Field(..., description="What the repair does")
    proposed_action: str = Field(..., description="Concrete action to take")
    target: Optional[str] = Field(None, description="Target system or component")
    autonomous: bool = Field(False, description="True if pre-approved for autonomous execution")
    reversible: bool = Field(True, description="True if the action can be undone")
    urgency: Literal["critical", "high", "review", "low"] = Field("review")
    cost_flag: bool = Field(False, description="True if this incurs cost (requires admin approval)")


class SubmitSourceRequestBody(BaseModel):
    executor_cli: Literal["cloud", "mac"] = Field(..., description="CLI that will execute the work")
    target: str = Field(..., description="Target: cloud or mac")
    mode: Literal["plan", "ask", "debug", "ln_fab"] = Field("debug", description="Execution mode contract")
    scope: Optional[str] = Field(None, description="Scope of the change")
    plan: str = Field(..., description="Detailed plan of what to change")
    build_id: Optional[str] = Field(None, description="Optional external build ID")
    parent_build_id: Optional[str] = Field(None, description="If this is a follow-up to a prior build")
    rollback_procedure: Optional[str] = Field(None, description="Required for execution-capable requests")
    clinical_sign_off: bool = Field(False, description="Clinical sign-off required for session-touching work")
    coherence_projection: Optional[Dict] = Field(default_factory=dict, description="Projected coherence impact")


class PreviewBody(BaseModel):
    request_id: Optional[str] = None
    mode: Literal["plan", "ask", "debug", "ln_fab"] = "debug"
    content: str
    artifact_type: str = "preview"
    content_format: str = "text"


class AdminPreviewBody(BaseModel):
    cli: Literal["cloud", "mac"] = "cloud"
    request_id: Optional[str] = None
    build_id: Optional[str] = None
    mode: Literal["plan", "ask", "debug", "ln_fab"] = "debug"
    content: str = ""
    artifact_type: str = "preview"
    content_format: str = "text"


class ReviseBody(BaseModel):
    artifact_id: str
    revision_notes: str


class AdminReviseBody(BaseModel):
    cli: Literal["cloud", "mac"] = "cloud"
    artifact_id: str
    revision_notes: str
    build_id: Optional[str] = None
    build_hint: Optional[str] = None


class WitnessApprovalBody(BaseModel):
    request_id: str


class ResolveConflictBody(BaseModel):
    request_id_a: str
    request_id_b: str
    resolution: Literal["approve_one", "approve_both_sequential", "reject_both"]
    winner_request_id: Optional[str] = None
    admin_note: Optional[str] = None


class EvaluationGenerateBody(BaseModel):
    cli_agent: str
    domain: Literal[
        "therapeutic_comprehension",
        "coding_ability",
        "systems_management",
        "hallucination_compliance",
        "reasoning_depth",
    ]
    difficulty: str = "standard"


class EvaluationSubmitBody(BaseModel):
    evaluation_id: str
    cli_response: str


class EvaluationScoreBody(BaseModel):
    evaluation_id: str
    scorer_identity: str = "automated"
    model_version: Optional[str] = None
    evaluation_context: str = "cold_no_memory"


class CompletionReportBody(BaseModel):
    request_id: str = Field(..., description="source_repair_request id")
    completion_report: str = Field(..., description="Report from the executor CLI")
    combined_report: Optional[str] = Field(None, description="Combined report (executor + requester)")


class BlobUploadBody(BaseModel):
    build_id: str = Field(..., description="Build ID for the blob key")
    filename: str = Field("report.json", description="Filename within the build directory")
    content: str = Field(..., description="Content to store (text or JSON string)")
    content_type: str = Field("application/json")


class SearchRequestBody(BaseModel):
    query: str = Field(..., description="Internet search query")
    reason: str = Field(..., description="Why this search is needed")
    context: Optional[str] = Field(None, description="Additional context for the approving CLI")


class SearchResultBody(BaseModel):
    search_id: str = Field(..., description="ID of the approved search request")
    results: str = Field(..., description="Search results (text or JSON)")
    approved_citations: Optional[List[str]] = Field(None, description="URLs/citations approved for use")


class RestoreRequestBody(BaseModel):
    backup_key: str = Field(..., description="R2 key of the backup to restore (e.g. nate-cli-backups/cloud/2026-03-13/backup.json)")
    target_cli: Literal["cloud", "mac"] = Field(..., description="Which CLI's backup to restore")
    reason: str = Field(..., description="Why the restore is needed")


class CrossCliDiagnosisBody(BaseModel):
    build_id: str = Field(..., description="Build ID to diagnose")
    target_cli: Literal["cloud", "mac"] = Field(..., description="CLI that originally built this request")
    include_suggestions: bool = Field(True, description="Include actionable suggestion list")
    include_grade: bool = Field(True, description="Include coding ability grade")


# ── DB helper ──

def _pool(request: Request):
    return getattr(request.app.state, "db_pool", None) or getattr(request.app.state, "pool", None)


def _compute_scope_hash(plan_text: str) -> str:
    return hashlib.sha256((plan_text or "").encode("utf-8")).hexdigest()


def _compute_idempotency_key(
    cli_id: str,
    mode: str,
    plan: str,
    parent_build_id: Optional[str],
    executor_cli: str,
) -> str:
    raw = f"{cli_id}|{mode}|{plan}|{parent_build_id or ''}|{executor_cli}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _is_audit_gate_cleared(request: Request) -> bool:
    redis = getattr(request.app.state, "cache_redis", None)
    if not redis:
        return True
    try:
        gate = await redis.get("platform:audit:status")
        if isinstance(gate, bytes):
            gate = gate.decode("utf-8", errors="ignore")
        if gate is None:
            return True
        return str(gate).strip().upper() == "CLEARED"
    except Exception:
        return True


async def _all_domain_scores(conn, cli_agent: str) -> Dict[str, float]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (domain) domain, score
        FROM cli_evaluation_battery
        WHERE cli_agent = $1 AND score IS NOT NULL
        ORDER BY domain, evaluated_at DESC NULLS LAST, created_at DESC
        """,
        cli_agent,
    )
    return {str(r["domain"]): float(r["score"]) for r in rows}


async def _passes_authority_gate(conn, cli_agent: str, gate_key: str) -> bool:
    gate = AUTHORITY_GATES.get(gate_key)
    if not gate:
        return True
    scores = await _all_domain_scores(conn, cli_agent)
    min_score = float(gate.get("min_score", 0))
    if gate.get("all_domains_required"):
        if not all(d in scores for d in DOMAINS):
            return False
        return all(scores[d] >= min_score for d in DOMAINS)
    domain = gate.get("domain_required")
    if not domain:
        return True
    return float(scores.get(domain, -1.0)) >= min_score

async def _trigger_nightly_audit_rerun(app, source_request_id: str, scope: Optional[str], target: Optional[str]) -> None:
    """Best-effort rerun trigger after CLI repair completion to close self-healing loop."""
    if not _RERUN_ON_CLI_REPAIR:
        return
    runner = getattr(getattr(app, "state", None), "nightly_audit_runner", None)
    if not runner:
        return
    try:
        await runner.run_full_audit()
        logger.info(
            "Nightly audit rerun triggered after CLI completion request_id=%s scope=%s target=%s",
            source_request_id,
            scope or "",
            target or "",
        )
    except Exception as exc:
        logger.warning(
            "Nightly audit rerun trigger failed request_id=%s: %s",
            source_request_id,
            exc,
        )


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS (require_admin)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/pending")
async def list_pending(
    request: Request,
    cli: Literal["cloud", "mac"] = Query(..., description="Filter by CLI (proposer or executor)"),
):
    """List pending repair_proposals and source_repair_requests for the given CLI."""
    pool = _pool(request)
    if not pool:
        return {"repair_proposals": [], "source_repair_requests": []}
    cli_val = f"cli-{cli}"
    async with pool.acquire() as conn:
        proposals = await conn.fetch(
            """
            SELECT id, proposed_by, repair_type, description, proposed_action, target,
                   autonomous, reversible, urgency, status, cost_flag, proposed_at
            FROM repair_proposals
            WHERE status = 'pending'
              AND (proposed_by = $1 OR target = $2)
            ORDER BY proposed_at DESC
            """,
            cli_val,
            cli,
        )
        source_reqs = await conn.fetch(
            """
            SELECT id, requester_cli, executor_cli, target, scope, plan, status, proposed_at, decided_at,
                   execution_started_at, executed_at, build_id, parent_build_id,
                   CASE
                     WHEN execution_started_at IS NULL THEN NULL
                     ELSE EXTRACT(EPOCH FROM (COALESCE(executed_at, NOW()) - execution_started_at))::INT
                   END AS execution_duration_seconds
            FROM source_repair_requests
            WHERE status IN ('pending_approval', 'draft', 'approved', 'executing')
              AND (requester_cli = $1 OR executor_cli = $1)
            ORDER BY proposed_at DESC
            """,
            cli_val,
        )
    return {
        "repair_proposals": [_row_to_dict(r) for r in proposals],
        "source_repair_requests": [_row_to_dict(r) for r in source_reqs],
    }


@router.post("/approve")
async def approve_or_reject(body: ApproveRejectBody, request: Request, user: dict = Depends(require_admin)):
    """Approve or reject a repair proposal or source_repair_request; write approval_decisions."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        proposal_id = uuid.UUID(body.id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id")
    decided_by = (user or {}).get("username") or (user or {}).get("user_id") or "admin"
    async with pool.acquire() as conn:
        if body.type == "operational":
            row = await conn.fetchrow(
                "SELECT id FROM repair_proposals WHERE id = $1 AND status = 'pending'",
                proposal_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Proposal not found or not pending")
            dec_id = await conn.fetchval(
                """
                INSERT INTO approval_decisions (repair_proposal_id, approved, decided_by, admin_note)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                proposal_id,
                body.approved,
                decided_by,
                body.admin_note,
            )
            await conn.execute(
                """
                UPDATE repair_proposals SET status = $2, decided_at = NOW(), approval_decision_id = $3
                WHERE id = $1
                """,
                proposal_id,
                "approved" if body.approved else "rejected",
                dec_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT id, target FROM source_repair_requests WHERE id = $1 AND status IN ('pending_approval', 'draft')",
                proposal_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Source request not found or not pending")

            if body.approved:
                executing = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM source_repair_requests
                    WHERE target = $1 AND status IN ('approved', 'executing') AND id != $2
                    """,
                    row["target"],
                    proposal_id,
                )
                if executing:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Concurrency lock: another source request on target '{row['target']}' is already approved/executing. Complete or reject it first.",
                    )

            dec_id = await conn.fetchval(
                """
                INSERT INTO approval_decisions (source_repair_request_id, approved, decided_by, admin_note)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                proposal_id,
                body.approved,
                decided_by,
                body.admin_note,
            )
            new_status = "approved" if body.approved else "rejected"
            await conn.execute(
                """
                UPDATE source_repair_requests
                SET status = $2,
                    decided_at = NOW(),
                    approval_decision_id = $3,
                    approval_expires_at = CASE WHEN $2 = 'approved' THEN NOW() + INTERVAL '4 hours' ELSE NULL END
                WHERE id = $1
                """,
                proposal_id,
                new_status,
                dec_id,
            )
    return {"ok": True, "approved": body.approved, "decision_id": str(dec_id)}


@router.get("/history")
async def history(
    request: Request,
    cli: Literal["cloud", "mac"] = Query(...),
    limit: int = Query(50, ge=1, le=200),
):
    """List completed repairs and source-code builds for the given CLI."""
    pool = _pool(request)
    if not pool:
        return {"repair_proposals": [], "source_repair_requests": []}
    cli_val = f"cli-{cli}"
    async with pool.acquire() as conn:
        proposals = await conn.fetch(
            """
            SELECT id, proposed_by, repair_type, description, status, proposed_at, decided_at, executed_at
            FROM repair_proposals
            WHERE status IN ('approved', 'rejected', 'executed')
              AND (proposed_by = $1 OR target = $2)
            ORDER BY proposed_at DESC
            LIMIT $3
            """,
            cli_val,
            cli,
            limit,
        )
        source_reqs = await conn.fetch(
            """
            SELECT id, requester_cli, executor_cli, target, scope, status, build_id, parent_build_id,
                   proposed_at, decided_at, execution_started_at, executed_at,
                   CASE
                     WHEN execution_started_at IS NULL THEN NULL
                     ELSE EXTRACT(EPOCH FROM (COALESCE(executed_at, NOW()) - execution_started_at))::INT
                   END AS execution_duration_seconds
            FROM source_repair_requests
            WHERE status IN ('draft', 'pending_approval', 'approved', 'executing', 'completed', 'rejected')
              AND (requester_cli = $1 OR executor_cli = $1)
            ORDER BY proposed_at DESC
            LIMIT $2
            """,
            cli_val,
            limit,
        )
    return {
        "repair_proposals": [_row_to_dict(r) for r in proposals],
        "source_repair_requests": [_row_to_dict(r) for r in source_reqs],
    }


@router.post("/corrective-request")
async def corrective_request(body: CorrectiveRequestBody, request: Request):
    """Create a new source_repair_request linked to a completed build (parent_build_id)."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    executor_cli = f"cli-{body.executor_cli}"
    requester_cli = "cli-admin"
    async with pool.acquire() as conn:
        parent = await conn.fetchrow(
            "SELECT id, status FROM source_repair_requests WHERE build_id = $1",
            body.parent_build_id,
        )
        if not parent:
            raise HTTPException(status_code=400, detail=f"Parent build {body.parent_build_id} not found")
        if parent["status"] not in ("completed", "execution_failed"):
            raise HTTPException(
                status_code=400,
                detail=f"Parent build is in '{parent['status']}' — must be completed or execution_failed",
            )
        row = await conn.fetchrow(
            """
            INSERT INTO source_repair_requests
            (requester_cli, executor_cli, target, scope, plan, status, mode, parent_build_id, proposed_at)
            VALUES ($1, $2, $3, $4, $5, 'pending_approval', 'debug', $6, NOW())
            RETURNING id, build_id, proposed_at
            """,
            requester_cli,
            executor_cli,
            body.executor_cli,
            None,
            body.description,
            body.parent_build_id,
        )
    return {
        "ok": True,
        "id": str(row["id"]),
        "parent_build_id": body.parent_build_id,
        "status": "pending_approval",
    }


# ═══════════════════════════════════════════════════════════════════════════
# CLI ENDPOINTS (CLI service token auth)
# ═══════════════════════════════════════════════════════════════════════════

@cli_router.get("/health")
async def cli_health(cli_id: str = Depends(_resolve_cli_identity)):
    """Health check for CLI agents."""
    return {"status": "ok", "cli": cli_id, "timestamp": datetime.now(timezone.utc).isoformat()}


@cli_router.post("/diagnose-build")
async def diagnose_peer_build(
    body: CrossCliDiagnosisBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """
    Cross-CLI diagnostic endpoint.
    Allows one CLI to diagnose the *other* CLI's build and get actionable suggestions.
    """
    if cli_id not in ("cli-cloud", "cli-mac"):
        raise HTTPException(status_code=403, detail="Only cli-cloud or cli-mac may run cross diagnosis")

    target_cli_id = f"cli-{body.target_cli}"
    if cli_id == target_cli_id:
        raise HTTPException(status_code=422, detail="Cross diagnosis requires targeting the other CLI")

    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, build_id, requester_cli, executor_cli, target, scope, plan, status,
                   completion_report, combined_report, mode, rollback_procedure
            FROM source_repair_requests
            WHERE build_id = $1
            ORDER BY proposed_at DESC
            LIMIT 1
            """,
            body.build_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"Build not found: {body.build_id}")

    if target_cli_id not in {row["requester_cli"], row["executor_cli"]}:
        raise HTTPException(status_code=403, detail="Build is not owned by requested target_cli")

    diagnosis = _derive_cross_cli_diagnosis(
        row=dict(row),
        reviewer_cli=cli_id,
        target_cli=body.target_cli,
        include_suggestions=body.include_suggestions,
        include_grade=body.include_grade,
    )
    diagnosis["cross_cli"] = {"reviewer": cli_id, "target": target_cli_id}
    diagnosis["timestamp"] = datetime.now(timezone.utc).isoformat()
    return diagnosis


@cli_router.post("/submit-proposal")
async def submit_proposal(
    body: SubmitProposalBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """CLI submits an operational repair proposal."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    violation = _check_red_zone(body.target, body.proposed_action)
    if violation:
        raise HTTPException(status_code=403, detail=violation)

    if body.cost_flag:
        status = "pending"
    elif body.autonomous:
        status = "approved"
    else:
        status = "pending"

    async with pool.acquire() as conn:
        conflict = await _check_conflicts(conn, cli_id, body.target, body.proposed_action)

        row = await conn.fetchrow(
            """
            INSERT INTO repair_proposals
            (proposed_by, repair_type, description, proposed_action, target,
             autonomous, reversible, urgency, status, cost_flag,
             conflicts_with, conflict_reason, proposed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
            RETURNING id, status, proposed_at
            """,
            cli_id,
            body.repair_type,
            body.description,
            body.proposed_action,
            body.target,
            body.autonomous,
            body.reversible,
            body.urgency,
            "conflict" if conflict else status,
            body.cost_flag,
            conflict["id"] if conflict else None,
            conflict["reason"] if conflict else None,
        )

    proposal_id = str(row["id"])

    if conflict:
        asyncio.create_task(_notify_admin_conflict(request, cli_id, proposal_id, conflict))
    elif status == "pending":
        asyncio.create_task(_notify_admin_proposal(request, cli_id, proposal_id, body))

    return {
        "ok": True,
        "id": proposal_id,
        "status": row["status"],
        "conflict": conflict,
    }


@cli_router.post("/submit-source-request")
async def submit_source_request(
    body: SubmitSourceRequestBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """CLI submits a source-code repair request (cross-CLI or self)."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    violation = _check_red_zone(body.target, body.plan, body.scope or "")
    if violation:
        raise HTTPException(status_code=403, detail=violation)

    if body.mode == "ln_fab" and not (body.rollback_procedure and body.rollback_procedure.strip()):
        raise HTTPException(status_code=400, detail="rollback_procedure is required for ln_fab requests")

    executor = f"cli-{body.executor_cli}"
    build_id = body.build_id or f"build-{uuid.uuid4().hex[:12]}"
    idempotency_key = _compute_idempotency_key(
        cli_id=cli_id,
        mode=body.mode,
        plan=body.plan,
        parent_build_id=body.parent_build_id,
        executor_cli=body.executor_cli,
    )
    scope_hash = _compute_scope_hash(body.plan)

    async with pool.acquire() as conn:
        # 300s dedup window for same idempotency key.
        existing = await conn.fetchrow(
            """
            SELECT id, build_id, status
            FROM source_repair_requests
            WHERE idempotency_key = $1
              AND proposed_at >= NOW() - INTERVAL '300 seconds'
            ORDER BY proposed_at DESC
            LIMIT 1
            """,
            idempotency_key,
        )
        if existing:
            return {
                "ok": True,
                "id": str(existing["id"]),
                "build_id": existing["build_id"],
                "status": existing["status"],
                "deduped": True,
            }

        # Source-request conflict detection for same target on other CLI.
        conflict = await conn.fetchrow(
            """
            SELECT id, requester_cli, status
            FROM source_repair_requests
            WHERE target = $1
              AND status IN ('pending_approval', 'approved', 'executing')
              AND requester_cli != $2
            ORDER BY proposed_at DESC
            LIMIT 1
            """,
            body.target,
            cli_id,
        )

        status = "conflict_detected" if conflict else "pending_approval"
        row = await conn.fetchrow(
            """
            INSERT INTO source_repair_requests
            (requester_cli, executor_cli, target, scope, plan, status, mode, build_id, parent_build_id,
             rollback_procedure, scope_hash, idempotency_key, clinical_sign_off, coherence_projection,
             approval_expires_at, proposed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW() + INTERVAL '4 hours', NOW())
            RETURNING id, build_id, proposed_at
            """,
            cli_id,
            executor,
            body.target,
            body.scope,
            body.plan,
            status,
            body.mode,
            build_id,
            body.parent_build_id,
            body.rollback_procedure,
            scope_hash,
            idempotency_key,
            body.clinical_sign_off,
            json.dumps(body.coherence_projection or {}),
        )

        if conflict:
            await conn.execute(
                "UPDATE source_repair_requests SET status = 'conflict_detected' WHERE id = $1",
                conflict["id"],
            )

    req_id = str(row["id"])
    asyncio.create_task(_notify_admin_source_request(request, cli_id, req_id, body))

    return {
        "ok": True,
        "id": req_id,
        "build_id": row["build_id"],
        "status": status,
        "mode": body.mode,
        "behavior_tag": MODE_BEHAVIOR_TAGS.get(body.mode, "NO-EDIT"),
        "conflicting_request_id": str(conflict["id"]) if conflict else None,
    }


@cli_router.get("/approval-status/{request_id}")
async def approval_status(
    request_id: str,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """Check approval status of a proposal or source request."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, proposed_by AS cli, decided_at FROM repair_proposals WHERE id = $1",
            rid,
        )
        req_type = "operational"
        if not row:
            row = await conn.fetchrow(
                "SELECT id, status, requester_cli AS cli, decided_at FROM source_repair_requests WHERE id = $1",
                rid,
            )
            req_type = "source"
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")

        decision = await conn.fetchrow(
            """
            SELECT approved, decided_by, admin_note, decided_at
            FROM approval_decisions
            WHERE repair_proposal_id = $1 OR source_repair_request_id = $1
            ORDER BY decided_at DESC LIMIT 1
            """,
            rid,
        )

    return {
        "id": str(row["id"]),
        "type": req_type,
        "status": row["status"],
        "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
        "decision": _row_to_dict(decision) if decision else None,
    }


@cli_router.post("/begin-execution")
async def begin_execution(
    request: Request,
    request_id: str = Query(..., description="source_repair_request id"),
    execution_scope_hash: Optional[str] = Query(None, description="Scope hash to enforce approval lock"),
    witnessing_cli: Optional[str] = Query(None, description="Witnessing CLI identity for ln_fab execution"),
    cli_id: str = Depends(_resolve_cli_identity),
):
    """CLI marks an approved source request as 'executing'. Enforces concurrency lock."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, target, executor_cli, status, mode, scope_hash, approval_expires_at,
                   rollback_procedure, coherence_projection, witnessing_cli
            FROM source_repair_requests
            WHERE id = $1
            """,
            rid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Source request not found")
        if row["status"] != "approved":
            raise HTTPException(status_code=400, detail=f"Cannot begin execution for status={row['status']}; must be 'approved'")
        if row["executor_cli"] != cli_id:
            raise HTTPException(status_code=403, detail=f"Only {row['executor_cli']} can execute this request")

        if row.get("approval_expires_at") and datetime.now(timezone.utc) > row["approval_expires_at"]:
            await conn.execute("UPDATE source_repair_requests SET status = 'expired' WHERE id = $1", rid)
            raise HTTPException(status_code=400, detail="Approval expired; request requires re-approval")

        mode = (row.get("mode") or "debug").lower()
        if mode in ("plan", "ask", "debug"):
            raise HTTPException(status_code=400, detail=f"Mode '{mode}' is non-executing ({MODE_BEHAVIOR_TAGS.get(mode)})")

        if mode == "ln_fab":
            effective_witness = witnessing_cli or row.get("witnessing_cli")
            if not effective_witness:
                raise HTTPException(status_code=400, detail="witnessing_cli is required for ln_fab execution")
            if effective_witness == cli_id:
                raise HTTPException(status_code=400, detail="witnessing_cli must be a different CLI")
            witnessing_cli = effective_witness

        if execution_scope_hash and row.get("scope_hash") and execution_scope_hash != row["scope_hash"]:
            raise HTTPException(status_code=400, detail="Scope drift detected: execution hash does not match approved scope_hash")

        if not row.get("rollback_procedure"):
            raise HTTPException(status_code=400, detail="rollback_procedure is required before execution")

        if not await _is_audit_gate_cleared(request):
            await conn.execute(
                "UPDATE source_repair_requests SET status = 'suspended_audit_failure' WHERE id = $1",
                rid,
            )
            return {
                "ok": False,
                "id": request_id,
                "status": "suspended_audit_failure",
                "reason": "Platform audit gate not CLEARED",
            }

        if not await _passes_authority_gate(conn, cli_id, "lnfab_execution"):
            raise HTTPException(status_code=403, detail="Authority gate denied: insufficient 5-domain score profile")

        already_executing = await conn.fetchval(
            """
            SELECT COUNT(*) FROM source_repair_requests
            WHERE target = $1 AND status = 'executing' AND id != $2
            """,
            row["target"],
            rid,
        )
        if already_executing:
            raise HTTPException(
                status_code=409,
                detail=f"Concurrency lock: another request on target '{row['target']}' is currently executing",
            )

        proxy = SystemCoherenceProxy()
        c_emo_before = await proxy.compute(db_pool=pool, redis_client=getattr(request.app.state, "cache_redis", None))

        await conn.execute(
            """
            UPDATE source_repair_requests
            SET status = 'executing',
                execution_started_at = COALESCE(execution_started_at, NOW()),
                witnessing_cli = COALESCE($2, witnessing_cli),
                witnessing_at = CASE WHEN $2 IS NULL THEN witnessing_at ELSE NOW() END,
                c_emo_before = COALESCE($3, c_emo_before),
                coherence_proxy_type = COALESCE(coherence_proxy_type, 'system')
            WHERE id = $1
            """,
            rid,
            witnessing_cli,
            c_emo_before,
        )

    return {"ok": True, "id": request_id, "status": "executing", "c_emo_before": c_emo_before}


@cli_router.post("/completion-report")
async def write_completion_report(
    body: CompletionReportBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """CLI writes completion report after executing a source-code repair."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rid = uuid.UUID(body.request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request_id")

    proxy = SystemCoherenceProxy()
    c_emo_after = await proxy.compute(db_pool=pool, redis_client=getattr(request.app.state, "cache_redis", None))

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, executor_cli, status, scope, target, c_emo_before, coherence_projection, mode
            FROM source_repair_requests
            WHERE id = $1
            """,
            rid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Source request not found")
        if row["status"] not in ("approved", "executing"):
            raise HTTPException(status_code=400, detail=f"Cannot write report for status={row['status']}")

        c_before = float(row.get("c_emo_before") or 0.0)
        regression = max(0.0, c_before - float(c_emo_after))
        auto_rollback = bool(regression > 0.10 and (row.get("mode") or "").lower() == "ln_fab")
        resulting_status = "review_ec_regression" if regression > 0.10 else "completed"
        violation_level = (
            ViolationTaxonomy.classify(
                CoherenceImpactAssessment(
                    c_emo_before=c_before,
                    c_emo_after=float(c_emo_after),
                    p_ent_delta=0.0,
                    t_tunnel_delta=0.0,
                    gamma_env_delta=regression,
                    clinical_justification="Post execution coherence proxy evaluation",
                    clinician_approved=not auto_rollback,
                )
            )
            if regression > 0.0
            else ViolationTaxonomy.COMPLIANT
        )

        await conn.execute(
            """
            UPDATE source_repair_requests
            SET completion_report = $2,
                combined_report = $3,
                status = $4,
                execution_started_at = COALESCE(execution_started_at, NOW()),
                executed_at = NOW(),
                c_emo_after = $5,
                coherence_assessment = $6
            WHERE id = $1
            """,
            rid,
            body.completion_report,
            body.combined_report,
            resulting_status,
            c_emo_after,
            json.dumps({
                "c_emo_before": c_before,
                "c_emo_after": c_emo_after,
                "regression": regression,
                "violation_level": violation_level,
                "auto_rollback": auto_rollback,
            }),
        )

        await conn.execute(
            """
            INSERT INTO coherence_impact_log
            (request_id, c_emo_before, c_emo_after, violation_level, auto_rolled_back, coherence_proxy_type, created_at)
            VALUES ($1, $2, $3, $4, $5, 'system', NOW())
            """,
            rid,
            c_before,
            c_emo_after,
            violation_level,
            auto_rollback,
        )

    asyncio.create_task(_store_report_blob(body.request_id, body.completion_report, body.combined_report))
    asyncio.create_task(
        _trigger_nightly_audit_rerun(
            request.app,
            body.request_id,
            row["scope"],
            row["target"],
        )
    )

    return {
        "ok": True,
        "id": body.request_id,
        "status": resulting_status,
        "c_emo_after": c_emo_after,
        "nightly_audit_rerun_scheduled": _RERUN_ON_CLI_REPAIR,
    }


@cli_router.post("/log-execution")
async def log_autonomous_execution(
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
    action: str = Query(...),
    target: str = Query(...),
    before_state: Optional[str] = Query(None),
    after_state: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
):
    """Log an autonomous (pre-approved, reversible) execution."""
    violation = _check_red_zone(target, action)
    if violation:
        raise HTTPException(status_code=403, detail=violation)

    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    before_json = _safe_json(before_state)
    after_json = _safe_json(after_state)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO autonomous_executions
            (cli_agent, action, target, before_state, after_state, outcome, executed_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            RETURNING id, executed_at
            """,
            cli_id,
            action,
            target,
            before_json,
            after_json,
            outcome,
        )
    return {"ok": True, "id": str(row["id"]), "executed_at": row["executed_at"].isoformat()}


# ═══════════════════════════════════════════════════════════════════════════
# MODE PREVIEW / ARTIFACT / REVISION
# ═══════════════════════════════════════════════════════════════════════════

@cli_router.post("/preview")
async def create_preview_artifact(
    body: PreviewBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return await _create_preview_artifact_record(
        pool=pool,
        cli_id=cli_id,
        request_id=body.request_id,
        mode=body.mode,
        content=body.content,
        artifact_type=body.artifact_type,
        content_format=body.content_format,
    )


async def _create_preview_artifact_record(
    *,
    pool,
    cli_id: str,
    request_id: Optional[str],
    mode: str,
    content: str,
    artifact_type: str,
    content_format: str,
) -> Dict[str, Any]:
    content = content or ""
    content_size = len(content.encode("utf-8"))
    version_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    request_uuid = None
    if request_id:
        try:
            request_uuid = uuid.UUID(request_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid request_id")

    r2_key = None
    if content_size >= 4096:
        r2_key = f"cli-artifacts/{request_id or uuid.uuid4().hex}/{version_hash}.txt"
        try:
            from app.services.r2_storage import upload_bytes_async, is_r2_configured
            if is_r2_configured():
                await upload_bytes_async(
                    key=r2_key,
                    content=content.encode("utf-8"),
                    content_type="text/plain",
                    metadata={"cli": cli_id, "mode": mode, "artifact_type": artifact_type},
                )
            else:
                r2_key = None
        except Exception:
            r2_key = None

    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            """
            INSERT INTO cli_mode_runs (request_id, cli_agent, mode, status, created_at, updated_at)
            VALUES ($1, $2, $3, 'preview_ready', NOW(), NOW())
            RETURNING id
            """,
            request_uuid,
            cli_id,
            mode,
        )
        run_id = run["id"]
        artifact = await conn.fetchrow(
            """
            INSERT INTO cli_mode_artifacts
            (run_id, request_id, artifact_type, content_format, content, r2_key, content_size_bytes, version_hash, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            RETURNING id
            """,
            run_id,
            request_uuid,
            artifact_type,
            content_format,
            None if r2_key else content,
            r2_key,
            content_size,
            version_hash,
        )
    return {
        "ok": True,
        "run_id": str(run_id),
        "artifact_id": str(artifact["id"]),
        "mode": mode,
        "behavior_tag": MODE_BEHAVIOR_TAGS.get(mode, "NO-EDIT"),
        "r2_key": r2_key,
        "content_size_bytes": content_size,
    }


def _extract_file_candidates(*texts: Optional[str]) -> List[str]:
    """
    Best-effort file extractor for preview metadata.
    Captures Python/Dart/JS/TS/HTML/CSS/JSON/YAML/SQL/MD paths commonly mentioned in plans.
    """
    pattern = re.compile(
        r"([A-Za-z0-9_\-./]+?\.(?:json|ya?ml|py|dart|tsx|jsx|ts|js|html|css|sql|md))\b"
    )
    seen = set()
    out: List[str] = []
    for text in texts:
        if not text:
            continue
        for m in pattern.finditer(text):
            path = m.group(1).strip().strip("`'\"")
            if "/" not in path:
                continue
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


async def _resolve_source_request_for_preview(
    *,
    conn,
    cli_id: str,
    build_id: Optional[str] = None,
    content_hint: Optional[str] = None,
):
    """
    Resolve a source_repair_request row for preview/revision using flexible hints:
    1) exact build_id
    2) build_id prefix
    3) build/restore token found anywhere in content
    4) backup key/path hint found in plan text
    """
    hint = (content_hint or "").strip()
    candidate = (build_id or "").strip() or None
    if not candidate and hint:
        m = re.search(r"\b((?:build|restore)-[a-f0-9]{8,})\b", hint, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1)

    if candidate:
        row = await conn.fetchrow(
            """
            SELECT build_id, target, scope, plan, status, requester_cli, executor_cli,
                   completion_report, combined_report, id
            FROM source_repair_requests
            WHERE build_id = $1
              AND (requester_cli = $2 OR executor_cli = $2)
            ORDER BY proposed_at DESC
            LIMIT 1
            """,
            candidate,
            cli_id,
        )
        if row:
            return row

        # Prefix fallback: supports short typed ids like restore-d727c5d88ae
        row = await conn.fetchrow(
            """
            SELECT build_id, target, scope, plan, status, requester_cli, executor_cli,
                   completion_report, combined_report, id
            FROM source_repair_requests
            WHERE build_id ILIKE ($1 || '%')
              AND (requester_cli = $2 OR executor_cli = $2)
            ORDER BY proposed_at DESC
            LIMIT 1
            """,
            candidate,
            cli_id,
        )
        if row:
            return row

    if hint and "/" in hint:
        row = await conn.fetchrow(
            """
            SELECT build_id, target, scope, plan, status, requester_cli, executor_cli,
                   completion_report, combined_report, id
            FROM source_repair_requests
            WHERE (plan ILIKE ('%' || $1 || '%') OR scope ILIKE ('%' || $1 || '%'))
              AND (requester_cli = $2 OR executor_cli = $2)
            ORDER BY proposed_at DESC
            LIMIT 1
            """,
            hint,
            cli_id,
        )
        if row:
            return row

    return None


def _contains_any(text: str, needles: List[str]) -> bool:
    lowered = (text or "").lower()
    return any(n in lowered for n in needles)


def _to_letter(score: int) -> str:
    if score >= 97:
        return "A+"
    if score >= 93:
        return "A"
    if score >= 90:
        return "A-"
    if score >= 87:
        return "B+"
    if score >= 83:
        return "B"
    if score >= 80:
        return "B-"
    if score >= 77:
        return "C+"
    if score >= 73:
        return "C"
    if score >= 70:
        return "C-"
    if score >= 67:
        return "D+"
    if score >= 63:
        return "D"
    if score >= 60:
        return "D-"
    return "F"


def _derive_cross_cli_diagnosis(
    *,
    row: Dict[str, Any],
    reviewer_cli: str,
    target_cli: str,
    include_suggestions: bool = True,
    include_grade: bool = True,
) -> Dict[str, Any]:
    plan = row.get("plan") or ""
    scope = row.get("scope") or ""
    completion_report = row.get("completion_report") or ""
    combined_report = row.get("combined_report") or ""
    rollback = row.get("rollback_procedure") or ""
    mode = row.get("mode") or "debug"
    status = row.get("status") or "unknown"
    target = row.get("target") or ""

    corpus = "\n".join([plan, scope, completion_report, combined_report])
    files = _extract_file_candidates(plan, scope, completion_report, combined_report)

    has_tests = _contains_any(
        corpus,
        ["pytest", "flutter test", "unit test", "integration test", "test plan", "test:"],
    )
    has_build_proof = _contains_any(
        corpus,
        ["build succeeded", "startup complete", "all systems nominal", "healthy", "200 ok"],
    )
    has_health_proof = _contains_any(
        corpus,
        ["/health", "\"status\":\"healthy\"", "\"status\": \"healthy\"", "pulse ok", "200 in"],
    )
    has_deploy_proof = _contains_any(
        corpus,
        ["docker compose", "wrangler deploy", "scp ", "rsync ", "deployed"],
    )
    has_rollback = bool(rollback.strip()) or _contains_any(corpus, ["rollback", "revert procedure"])
    has_metrics = _contains_any(corpus, ["trusted", "scorecard", "/health", "audit"])

    allowlist_blocked = [p for p in files if not _check_read_allowlist(reviewer_cli, p)]

    risk_flags: List[Dict[str, str]] = []
    if status in {"completed", "execution_failed"} and not completion_report.strip():
        risk_flags.append({"severity": "high", "issue": "Missing completion_report on finalized build"})
    if not has_tests:
        risk_flags.append({"severity": "medium", "issue": "No explicit test evidence found"})
    if not has_build_proof:
        risk_flags.append({"severity": "medium", "issue": "No explicit build/health proof found"})
    if not has_health_proof:
        risk_flags.append({"severity": "medium", "issue": "No explicit health proof found"})
    if mode == "ln_fab" and not has_rollback:
        risk_flags.append({"severity": "high", "issue": "ln_fab run without rollback evidence"})
    if allowlist_blocked:
        risk_flags.append({
            "severity": "medium",
            "issue": f"Reviewer allowlist blocks {len(allowlist_blocked)} referenced path(s)",
        })
    if target and target_cli and target != target_cli:
        risk_flags.append({"severity": "low", "issue": f"Build target '{target}' differs from requested target_cli '{target_cli}'"})

    suggestions: List[str] = []
    if include_suggestions:
        if not has_tests:
            suggestions.append("Attach a concise test plan and paste command outputs (`pytest`, `flutter test`, or endpoint probes).")
        if not has_build_proof:
            suggestions.append("Include build verification markers (startup health line, `/health` response, and critical endpoint status).")
        if not has_health_proof:
            suggestions.append("Attach explicit health proof (`/health` JSON, pulse response, and endpoint status summaries).")
        if not has_deploy_proof:
            suggestions.append("Document deploy steps and exact artifacts changed so peer CLI can replay deterministically.")
        if mode == "ln_fab" and not has_rollback:
            suggestions.append("Add explicit rollback_procedure for execution-capable requests.")
        if allowlist_blocked:
            suggestions.append("Move referenced files into shared allowlisted paths or request admin preview artifact export for blocked paths.")
        if status not in {"completed", "execution_failed"}:
            suggestions.append("Finalize execution lifecycle fields before peer diagnosis (status, execution_started_at, executed_at).")
        if has_tests and has_build_proof and has_deploy_proof:
            suggestions.append("Cross-sign with the opposite CLI via witness approval for stronger dual-CLI confidence.")

    build_points = 0
    build_points += 30 if has_build_proof else 10
    build_points += 30 if has_health_proof else 10
    build_points += 20 if has_deploy_proof else 8
    build_points += 20 if (status in {"executing", "completed", "execution_failed"} and completion_report.strip()) else 8

    coding_points = 0
    coding_points += 25 if has_tests else 8
    coding_points += 20 if has_rollback else 8
    coding_points += 15 if files else 6
    coding_points += 20 if has_metrics else 8
    coding_points += 20 if has_deploy_proof else 8
    coding_points = max(0, min(100, coding_points - (5 * len([r for r in risk_flags if r["severity"] == "high"]))))

    payload = {
        "build_id": row.get("build_id"),
        "request_id": str(row.get("id")) if row.get("id") else None,
        "status": status,
        "mode": mode,
        "requester_cli": row.get("requester_cli"),
        "executor_cli": row.get("executor_cli"),
        "target": target,
        "reviewer_cli": reviewer_cli,
        "target_cli": target_cli,
        "signals": {
            "has_tests": has_tests,
            "has_build_proof": has_build_proof,
            "has_health_proof": has_health_proof,
            "has_deploy_proof": has_deploy_proof,
            "has_rollback": has_rollback,
            "has_metrics": has_metrics,
            "referenced_files": len(files),
            "allowlist_blocked_files": len(allowlist_blocked),
        },
        "peer_proof": {
            "build_health_score": build_points,
            "build_health_grade": _to_letter(build_points),
            "checks": {
                "build_markers": has_build_proof,
                "health_markers": has_health_proof,
                "deploy_markers": has_deploy_proof,
                "completion_report_present": bool(completion_report.strip()),
            },
        },
        "risk_flags": risk_flags,
        "blocked_paths": allowlist_blocked[:25],
        "suggestions": suggestions,
    }
    if include_grade:
        payload["coding_ability"] = {
            "score": coding_points,
            "grade": _to_letter(coding_points),
            "rubric": {
                "test_evidence": has_tests,
                "rollback_safety": has_rollback,
                "artifact_specificity": bool(files),
                "ops_metrics_evidence": has_metrics,
                "deploy_traceability": has_deploy_proof,
            },
        }
    return payload


@router.post("/preview")
async def create_preview_artifact_admin(
    body: AdminPreviewBody,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """
    Admin-safe preview endpoint for Command Terminal UI.
    Uses admin auth and maps to selected CLI identity.
    """
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    cli_id = f"cli-{body.cli}"
    content = (body.content or "").strip()
    resolved_from_build = False

    if body.build_id:
        bid = body.build_id.strip()
    else:
        bid = None
        m = re.search(r"\b((?:build|restore)-[a-f0-9]{8,})\b", content, flags=re.IGNORECASE)
        if m:
            bid = m.group(1)

    preview_struct: Dict[str, Any] = {
        "kind": "freeform",
        "summary": "Freeform preview content",
        "files": _extract_file_candidates(content),
        "target": None,
        "status": None,
        "plan": None,
        "scope": None,
        "completion_report": None,
        "combined_report": None,
    }

    if bid or content:
        async with pool.acquire() as conn:
            row = await _resolve_source_request_for_preview(
                conn=conn,
                cli_id=cli_id,
                build_id=bid,
                content_hint=content,
            )
        if row:
            bid = row["build_id"]
        elif bid:
            raise HTTPException(status_code=404, detail=f"Build not found for selected CLI: {bid}")
    else:
        row = None

    if row:
        files = _extract_file_candidates(row.get("plan"), row.get("scope"), row.get("completion_report"), row.get("combined_report"))
        preview_struct = {
            "kind": "source_request",
            "summary": f"Build {row['build_id']} ({row['status']})",
            "files": files,
            "target": row["target"],
            "status": row["status"],
            "plan": row.get("plan"),
            "scope": row.get("scope"),
            "completion_report": row.get("completion_report"),
            "combined_report": row.get("combined_report"),
        }
        content = (
            f"[Build Preview: {row['build_id']} | status={row['status']}]\n"
            f"Target: {row['target']}\n"
            f"Requester: {row['requester_cli']} | Executor: {row['executor_cli']}\n\n"
            f"Plan:\n{row['plan'] or '(none)'}\n\n"
            f"Scope:\n{row['scope'] or '(none)'}\n"
        )
        if row.get("completion_report"):
            content += f"\n\nCompletion report:\n{row['completion_report']}"
        if row.get("combined_report"):
            content += f"\n\nCombined report:\n{row['combined_report']}"
        resolved_from_build = True

    if not content:
        raise HTTPException(status_code=400, detail="Enter preview content or provide a build_id")

    result = await _create_preview_artifact_record(
        pool=pool,
        cli_id=cli_id,
        request_id=body.request_id,
        mode=body.mode,
        content=content,
        artifact_type=body.artifact_type,
        content_format=body.content_format,
    )
    result["cli"] = body.cli
    result["resolved_from_build"] = resolved_from_build
    result["resolved_build_id"] = bid
    result["preview_content"] = content
    result["preview_struct"] = preview_struct
    return result


@cli_router.get("/artifacts/{build_id}")
async def list_artifacts(build_id: str, request: Request, cli_id: str = Depends(_resolve_cli_identity)):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id, a.artifact_type, a.content_format, a.content_size_bytes, a.version_hash, a.r2_key, a.created_at
            FROM cli_mode_artifacts a
            JOIN source_repair_requests s ON s.id = a.request_id
            WHERE s.build_id = $1
            ORDER BY a.created_at DESC
            """,
            build_id,
        )
    return {"artifacts": [_row_to_dict(r) for r in rows]}


@cli_router.post("/revise/{build_id}")
async def revise_artifact(
    build_id: str,
    body: ReviseBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        req = await conn.fetchrow("SELECT id FROM source_repair_requests WHERE build_id = $1", build_id)
        if not req:
            raise HTTPException(status_code=404, detail="Build not found")
        row = await conn.fetchrow(
            """
            INSERT INTO cli_mode_artifacts
            (request_id, artifact_type, content_format, content, content_size_bytes, version_hash, created_at)
            VALUES ($1, 'revision_request', 'text', $2, $3, $4, NOW())
            RETURNING id
            """,
            req["id"],
            body.revision_notes,
            len((body.revision_notes or "").encode("utf-8")),
            hashlib.sha256((body.revision_notes or "").encode("utf-8")).hexdigest(),
        )
    return {"ok": True, "artifact_id": str(row["id"]), "status": "revision_requested"}


@router.post("/revise")
async def revise_artifact_admin(
    body: AdminReviseBody,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """
    Admin-safe revision endpoint for Command Terminal.
    Resolves build by explicit id, id token in hint, prefix, or backup path in plan/scope.
    """
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    cli_id = f"cli-{body.cli}"
    hint = (body.build_hint or "").strip()

    async with pool.acquire() as conn:
        row = await _resolve_source_request_for_preview(
            conn=conn,
            cli_id=cli_id,
            build_id=body.build_id,
            content_hint=hint,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Build not found for selected CLI")

        inserted = await conn.fetchrow(
            """
            INSERT INTO cli_mode_artifacts
            (request_id, artifact_type, content_format, content, content_size_bytes, version_hash, created_at)
            VALUES ($1, 'revision_request', 'text', $2, $3, $4, NOW())
            RETURNING id
            """,
            row["id"],
            body.revision_notes,
            len((body.revision_notes or "").encode("utf-8")),
            hashlib.sha256((body.revision_notes or "").encode("utf-8")).hexdigest(),
        )

    return {
        "ok": True,
        "artifact_id": str(inserted["id"]),
        "status": "revision_requested",
        "build_id": row["build_id"],
        "cli": body.cli,
    }


@cli_router.post("/witness-approval")
async def witness_approval(
    body: WitnessApprovalBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rid = uuid.UUID(body.request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, executor_cli, status FROM source_repair_requests WHERE id = $1",
            rid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        if row["status"] != "approved":
            raise HTTPException(status_code=400, detail="Request must be approved before witnessing")
        if row["executor_cli"] == cli_id:
            raise HTTPException(status_code=400, detail="Witness must be a different CLI than executor")
        await conn.execute(
            """
            UPDATE source_repair_requests
            SET witnessing_cli = $2, witnessing_at = NOW()
            WHERE id = $1
            """,
            rid,
            cli_id,
        )
    return {"ok": True, "request_id": body.request_id, "witnessed_by": cli_id}


@router.post("/resolve-conflict")
async def resolve_conflict(body: ResolveConflictBody, request: Request):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        a = uuid.UUID(body.request_id_a)
        b = uuid.UUID(body.request_id_b)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ids")

    async with pool.acquire() as conn:
        row_a = await conn.fetchrow("SELECT id, status FROM source_repair_requests WHERE id = $1", a)
        row_b = await conn.fetchrow("SELECT id, status FROM source_repair_requests WHERE id = $1", b)
        if not row_a or not row_b:
            raise HTTPException(status_code=404, detail="Conflict pair not found")

        if body.resolution == "approve_one":
            if not body.winner_request_id:
                raise HTTPException(status_code=400, detail="winner_request_id required for approve_one")
            winner = uuid.UUID(body.winner_request_id)
            loser = b if winner == a else a
            await conn.execute("UPDATE source_repair_requests SET status = 'approved' WHERE id = $1", winner)
            await conn.execute("UPDATE source_repair_requests SET status = 'rejected' WHERE id = $1", loser)
        elif body.resolution == "approve_both_sequential":
            await conn.execute("UPDATE source_repair_requests SET status = 'approved' WHERE id = $1", a)
            await conn.execute("UPDATE source_repair_requests SET status = 'pending_admin_resolution' WHERE id = $1", b)
        else:
            await conn.execute("UPDATE source_repair_requests SET status = 'rejected' WHERE id = $1", a)
            await conn.execute("UPDATE source_repair_requests SET status = 'rejected' WHERE id = $1", b)

        await conn.execute(
            """
            INSERT INTO cli_conflict_resolutions
            (request_id_a, request_id_b, resolution_type, resolved_by, admin_note, resolved_at)
            VALUES ($1, $2, $3, 'big_nate', $4, NOW())
            """,
            a, b, body.resolution, body.admin_note,
        )

    return {"ok": True, "resolution": body.resolution}


@cli_router.post("/evaluation/generate")
async def evaluation_generate(
    body: EvaluationGenerateBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    battery = EvaluationBattery()
    generated = await battery.generate_test(body.domain, body.difficulty)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO cli_evaluation_battery
            (cli_agent, domain, difficulty, scenario_text, expected_behavior, rubric_version, scorer_identity, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'system_generate', NOW())
            RETURNING id
            """,
            body.cli_agent,
            body.domain,
            body.difficulty,
            generated["scenario_text"],
            generated["expected_behavior"],
            generated["rubric_version"],
        )
    generated["evaluation_id"] = str(row["id"])
    return generated


@cli_router.post("/evaluation/submit")
async def evaluation_submit(
    body: EvaluationSubmitBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        eid = uuid.UUID(body.evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation_id")
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cli_evaluation_battery
            SET cli_response = $2
            WHERE id = $1
            """,
            eid,
            body.cli_response,
        )
    return {"ok": True, "evaluation_id": body.evaluation_id, "status": "response_recorded"}


@cli_router.post("/evaluation/score")
async def evaluation_score(
    body: EvaluationScoreBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        eid = uuid.UUID(body.evaluation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, domain, cli_response
            FROM cli_evaluation_battery
            WHERE id = $1
            """,
            eid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        battery = EvaluationBattery()
        rubric = {"correctness": 0.35, "safety": 0.30, "reasoning": 0.25, "clarity": 0.10}
        scored = await battery.score_response(
            domain=row["domain"],
            cli_response=row["cli_response"] or "",
            rubric=rubric,
            scorer=body.scorer_identity,
            model_version=body.model_version or "n/a",
            evaluation_context=body.evaluation_context,
        )
        await conn.execute(
            """
            UPDATE cli_evaluation_battery
            SET score = $2,
                scorer_identity = $3,
                evaluation_context = $4,
                model_version = $5,
                evaluated_at = NOW()
            WHERE id = $1
            """,
            eid,
            scored.score,
            scored.scorer_identity,
            scored.evaluation_context,
            scored.model_version,
        )
    return {"ok": True, "evaluation_id": body.evaluation_id, "domain": scored.domain, "score": scored.score}


@cli_router.get("/evaluation/scores/{cli_agent}")
async def evaluation_scores(cli_agent: str, request: Request, cli_id: str = Depends(_resolve_cli_identity)):
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (domain) domain, score, evaluated_at, rubric_version, scorer_identity, evaluation_context, model_version
            FROM cli_evaluation_battery
            WHERE cli_agent = $1 AND score IS NOT NULL
            ORDER BY domain, evaluated_at DESC NULLS LAST, created_at DESC
            """,
            cli_agent,
        )
    return {"cli_agent": cli_agent, "scores": [_row_to_dict(r) for r in rows]}


# ═══════════════════════════════════════════════════════════════════════════
# INTERNET SEARCH — CLI-to-CLI approval flow
# ═══════════════════════════════════════════════════════════════════════════

@cli_router.post("/search/request")
async def search_request(
    body: SearchRequestBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """CLI requests permission to perform an internet search. The other CLI must approve."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    approver = "cli-mac" if cli_id == "cli-cloud" else "cli-cloud"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO cli_search_requests
            (requester_cli, approver_cli, query, reason, context, status, requested_at)
            VALUES ($1, $2, $3, $4, $5, 'pending', NOW())
            RETURNING id, requested_at
            """,
            cli_id, approver, body.query, body.reason, body.context,
        )
    return {
        "ok": True,
        "id": str(row["id"]),
        "status": "pending",
        "approver": approver,
    }


@cli_router.get("/search/pending")
async def search_pending(
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """List search requests pending this CLI's approval."""
    pool = _pool(request)
    if not pool:
        return {"requests": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, requester_cli, query, reason, context, status, requested_at
            FROM cli_search_requests
            WHERE approver_cli = $1 AND status = 'pending'
            ORDER BY requested_at DESC
            """,
            cli_id,
        )
    return {"requests": [_row_to_dict(r) for r in rows]}


@cli_router.post("/search/approve")
async def search_approve(
    request: Request,
    search_id: str = Query(...),
    approved: bool = Query(...),
    note: Optional[str] = Query(None),
    cli_id: str = Depends(_resolve_cli_identity),
):
    """Approve or reject a search request from the other CLI."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        sid = uuid.UUID(search_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid search_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, approver_cli, status FROM cli_search_requests WHERE id = $1",
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Search request not found")
        if row["approver_cli"] != cli_id:
            raise HTTPException(status_code=403, detail="Only the designated approver can approve this request")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Request is already {row['status']}")

        await conn.execute(
            """
            UPDATE cli_search_requests
            SET status = $2, decided_at = NOW(), approver_note = $3
            WHERE id = $1
            """,
            sid,
            "approved" if approved else "rejected",
            note,
        )
    return {"ok": True, "id": search_id, "status": "approved" if approved else "rejected"}


@cli_router.post("/search/submit-results")
async def search_submit_results(
    body: SearchResultBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """Submit search results after an approved search. Results are stored for citation."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        sid = uuid.UUID(body.search_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid search_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, requester_cli, status FROM cli_search_requests WHERE id = $1",
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Search request not found")
        if row["status"] != "approved":
            raise HTTPException(status_code=400, detail=f"Search not approved (status={row['status']})")
        if row["requester_cli"] != cli_id:
            raise HTTPException(status_code=403, detail="Only the requesting CLI can submit results")

        citations_json = json.dumps(body.approved_citations) if body.approved_citations else None
        await conn.execute(
            """
            UPDATE cli_search_requests
            SET status = 'completed', results = $2, approved_citations = $3, completed_at = NOW()
            WHERE id = $1
            """,
            sid, body.results, citations_json,
        )
    return {"ok": True, "id": body.search_id, "status": "completed"}


# ═══════════════════════════════════════════════════════════════════════════
# READ ALLOWLIST VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

@cli_router.get("/read-access/check")
async def check_read_access(
    path: str = Query(..., description="File or directory path to check"),
    cli_id: str = Depends(_resolve_cli_identity),
):
    """Check if a path is within this CLI's read allowlist."""
    allowed = _check_read_allowlist(cli_id, path)
    return {
        "path": path,
        "allowed": allowed,
        "cli": cli_id,
    }


@cli_router.get("/read-access/allowlist")
async def get_read_allowlist(cli_id: str = Depends(_resolve_cli_identity)):
    """Return this CLI's read allowlist."""
    return {
        "cli": cli_id,
        "allowlist": sorted(READ_ALLOWLISTS.get(cli_id, frozenset())),
    }


# ═══════════════════════════════════════════════════════════════════════════
# BACKUP RESTORE (admin-gated)
# ═══════════════════════════════════════════════════════════════════════════

@cli_router.post("/backup/restore-request")
async def backup_restore_request(
    body: RestoreRequestBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """CLI requests a backup restore. Creates a source_repair_request that needs admin approval."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    executor = f"cli-{body.target_cli}"
    plan = f"Restore backup from R2 key: {body.backup_key}\nReason: {body.reason}"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO source_repair_requests
            (requester_cli, executor_cli, target, scope, plan, status, build_id, proposed_at)
            VALUES ($1, $2, $3, 'backup_restore', $4, 'pending_approval', $5, NOW())
            RETURNING id, build_id, proposed_at
            """,
            cli_id, executor, body.target_cli, plan,
            f"restore-{uuid.uuid4().hex[:12]}",
        )

    req_id = str(row["id"])
    asyncio.create_task(_notify_admin_source_request(
        request, cli_id, req_id,
        SubmitSourceRequestBody(
            executor_cli=body.target_cli,
            target=body.target_cli,
            scope="backup_restore",
            plan=plan,
        ),
    ))

    return {
        "ok": True,
        "id": req_id,
        "status": "pending_approval",
        "note": "Admin must approve the restore via Command Terminal before execution",
    }


@cli_router.post("/blob/upload")
async def blob_upload(
    body: BlobUploadBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """Upload a build report or backup blob to R2."""
    key = f"cli-builds/{body.build_id}/{body.filename}"
    try:
        from app.services.r2_storage import upload_bytes_async, is_r2_configured
        if not is_r2_configured():
            raise RuntimeError("R2 not configured")
        storage_kind, location = await upload_bytes_async(
            key=key,
            content=body.content.encode("utf-8"),
            content_type=body.content_type,
            metadata={"cli": cli_id, "build_id": body.build_id},
        )
        return {"ok": True, "storage": storage_kind, "key": key, "location": location}
    except Exception as e:
        logger.warning("Blob upload failed for %s: %s — falling back to DB", key, e)
        pool = _pool(request)
        if pool:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO autonomous_executions
                    (cli_agent, action, target, after_state, outcome, executed_at)
                    VALUES ($1, 'blob_fallback', $2, $3, 'r2_unavailable', NOW())
                    """,
                    cli_id,
                    key,
                    json.dumps({"content_length": len(body.content), "filename": body.filename}),
                )
        return {"ok": True, "storage": "db_fallback", "key": key}


@cli_router.get("/blob/download")
async def blob_download(
    build_id: str = Query(...),
    filename: str = Query("report.json"),
    cli_id: str = Depends(_resolve_cli_identity),
):
    """Download a build report blob from R2."""
    key = f"cli-builds/{build_id}/{filename}"
    try:
        from app.services.r2_storage import download_bytes_async, is_r2_configured
        if not is_r2_configured():
            return {"ok": False, "error": "R2 not configured"}
        data = await download_bytes_async(key=key)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Blob not found: {key}")
        return {"ok": True, "key": key, "content": data.decode("utf-8", errors="replace")}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Blob download failed for %s: %s", key, e)
        raise HTTPException(status_code=500, detail="Blob download failed")


@cli_router.post("/backup/upload")
async def backup_upload(
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
    target_cli: Literal["cloud", "mac"] = Query(..., description="Which CLI's backup this is"),
    content: str = Query(..., description="Backup content"),
):
    """Daily mutual backup: each CLI backs up the OTHER side to R2."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"nate-cli-backups/{target_cli}/{today}/backup.json"
    try:
        from app.services.r2_storage import upload_bytes_async, is_r2_configured
        if not is_r2_configured():
            raise RuntimeError("R2 not configured")
        storage_kind, location = await upload_bytes_async(
            key=key,
            content=content.encode("utf-8"),
            content_type="application/json",
            metadata={"backed_up_by": cli_id, "target": target_cli, "date": today},
        )
        return {"ok": True, "storage": storage_kind, "key": key}
    except Exception as e:
        logger.warning("Backup upload failed: %s", e)
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# DISAGREEMENT / CONFLICT DETECTION
# ═══════════════════════════════════════════════════════════════════════════

async def _check_conflicts(conn, cli_id: str, target: Optional[str], proposed_action: str) -> Optional[dict]:
    """Check if another CLI has a pending proposal on the same target."""
    if not target:
        return None
    row = await conn.fetchrow(
        """
        SELECT id, proposed_by, proposed_action, description
        FROM repair_proposals
        WHERE target = $1
          AND status = 'pending'
          AND proposed_by != $2
        ORDER BY proposed_at DESC
        LIMIT 1
        """,
        target,
        cli_id,
    )
    if not row:
        return None

    reason = f"Conflicting proposal from {row['proposed_by']} on target '{target}'"
    await conn.execute(
        "UPDATE repair_proposals SET status = 'conflict', conflict_reason = $2 WHERE id = $1",
        row["id"],
        f"Conflicting proposal from {cli_id} on target '{target}'",
    )
    return {
        "id": str(row["id"]),
        "conflicting_cli": row["proposed_by"],
        "reason": reason,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN NOTIFICATION (SendGrid via SMTP)
# ═══════════════════════════════════════════════════════════════════════════

async def _notify_admin_proposal(request: Request, cli_id: str, proposal_id: str, body: SubmitProposalBody):
    """Send email to admin when a new repair proposal arrives."""
    try:
        ns = getattr(request.app.state, "notification_system", None)
        if not ns:
            logger.info("No notification_system — skipping admin email for proposal %s", proposal_id)
            return
        cost_warning = " ⚠️ COST FLAG — requires explicit approval" if body.cost_flag else ""
        subject = f"[CLI Proposal] {body.repair_type} from {cli_id}{cost_warning}"
        html = f"""
        <div style="font-family: 'DM Sans', sans-serif; background: #050505; color: #F5F5F5; padding: 30px;">
            <h2 style="color: #C9A962;">New CLI Repair Proposal</h2>
            <table style="border-collapse: collapse; width: 100%; margin: 20px 0;">
                <tr><td style="color: #9A9A9A; padding: 8px;">CLI</td><td style="color: #F5F5F5; padding: 8px;">{cli_id}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Type</td><td style="color: #F5F5F5; padding: 8px;">{body.repair_type}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Target</td><td style="color: #F5F5F5; padding: 8px;">{body.target or 'N/A'}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Urgency</td><td style="color: #F5F5F5; padding: 8px;">{body.urgency}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Cost</td><td style="color: {'#EF4444' if body.cost_flag else '#22C55E'}; padding: 8px;">{'PAID — requires approval' if body.cost_flag else 'Zero-cost'}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Autonomous</td><td style="color: #F5F5F5; padding: 8px;">{'Yes' if body.autonomous else 'No'}</td></tr>
            </table>
            <p style="color: #F5F5F5;"><strong>Description:</strong> {body.description}</p>
            <p style="color: #F5F5F5;"><strong>Action:</strong> {body.proposed_action}</p>
            <a href="{_COMMAND_TERMINAL_URL}" style="display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 12px 24px; margin-top: 20px; font-weight: bold;">Review in Command Terminal</a>
        </div>
        """
        await _send_admin_email(ns, subject, html)
    except Exception as e:
        logger.warning("Admin notification failed for proposal %s: %s", proposal_id, e)


async def _notify_admin_source_request(request: Request, cli_id: str, req_id: str, body: SubmitSourceRequestBody):
    """Send email to admin when a source-code repair request arrives."""
    try:
        ns = getattr(request.app.state, "notification_system", None)
        if not ns:
            return
        subject = f"[CLI Source Request] {cli_id} → cli-{body.executor_cli} on {body.target}"
        html = f"""
        <div style="font-family: 'DM Sans', sans-serif; background: #050505; color: #F5F5F5; padding: 30px;">
            <h2 style="color: #9D4EDD;">New Source-Code Repair Request</h2>
            <table style="border-collapse: collapse; width: 100%; margin: 20px 0;">
                <tr><td style="color: #9A9A9A; padding: 8px;">Requester</td><td style="color: #F5F5F5; padding: 8px;">{cli_id}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Executor</td><td style="color: #F5F5F5; padding: 8px;">cli-{body.executor_cli}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Target</td><td style="color: #F5F5F5; padding: 8px;">{body.target}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Build ID</td><td style="color: #F5F5F5; padding: 8px;">{body.build_id or 'auto-generated'}</td></tr>
            </table>
            <p style="color: #F5F5F5;"><strong>Plan:</strong></p>
            <pre style="background: #111; color: #4ECDC4; padding: 15px; overflow-x: auto; border-radius: 4px;">{body.plan[:2000]}</pre>
            <a href="{_COMMAND_TERMINAL_URL}" style="display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 12px 24px; margin-top: 20px; font-weight: bold;">Review in Command Terminal</a>
        </div>
        """
        await _send_admin_email(ns, subject, html)
    except Exception as e:
        logger.warning("Admin notification failed for source request %s: %s", req_id, e)


async def _notify_admin_conflict(request: Request, cli_id: str, proposal_id: str, conflict: dict):
    """Send email to admin when CLI proposals conflict on the same target."""
    try:
        ns = getattr(request.app.state, "notification_system", None)
        if not ns:
            return
        subject = f"[CLI CONFLICT] {cli_id} vs {conflict['conflicting_cli']} — admin resolution required"
        html = f"""
        <div style="font-family: 'DM Sans', sans-serif; background: #050505; color: #F5F5F5; padding: 30px;">
            <h2 style="color: #EF4444;">⚠️ CLI Disagreement — Conflicting Proposals</h2>
            <p style="color: #F5F5F5;">Two CLIs have proposed conflicting repairs on the same target. Neither will execute until you resolve this.</p>
            <table style="border-collapse: collapse; width: 100%; margin: 20px 0;">
                <tr><td style="color: #9A9A9A; padding: 8px;">New proposal</td><td style="color: #F5F5F5; padding: 8px;">{proposal_id} from {cli_id}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Conflicting with</td><td style="color: #F5F5F5; padding: 8px;">{conflict['id']} from {conflict['conflicting_cli']}</td></tr>
                <tr><td style="color: #9A9A9A; padding: 8px;">Reason</td><td style="color: #EF4444; padding: 8px;">{conflict['reason']}</td></tr>
            </table>
            <p style="color: #9A9A9A;">Approve one and reject the other in the Command Terminal.</p>
            <a href="{_COMMAND_TERMINAL_URL}" style="display: inline-block; background: #EF4444; color: #FFFFFF; text-decoration: none; padding: 12px 24px; margin-top: 20px; font-weight: bold;">Resolve Conflict</a>
        </div>
        """
        await _send_admin_email(ns, subject, html)
    except Exception as e:
        logger.warning("Admin conflict notification failed: %s", e)


async def _send_admin_email(ns, subject: str, html: str):
    """Send a raw email via the notification system's SMTP path."""
    import aiosmtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = os.getenv("SMTP_HOST", "smtp.sendgrid.net")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "apikey")
    smtp_pass = os.getenv("SMTP_PASSWORD", os.getenv("SENDGRID_API_KEY", ""))
    from_email = os.getenv("FROM_EMAIL", "sanctuary@littlenate.ai")

    if not smtp_pass:
        logger.info("No SMTP_PASSWORD/SENDGRID_API_KEY — skipping admin email")
        return

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"Sovereign Sanctuary <{from_email}>"
    message["To"] = _ADMIN_EMAIL
    message.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            message,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_pass,
            use_tls=True,
        )
        logger.info("Admin email sent: %s", subject[:80])
    except Exception as e:
        logger.warning("Admin email failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════
# INNOVATION PROPOSALS — Nate Creative Extension System
# ═══════════════════════════════════════════════════════════════════════════

class InnovationProposalBody(BaseModel):
    extension_type: Literal["formula", "table", "widget", "webhook"]
    domain: str = Field(..., description="Domain: marketing, clinical, coaching, defense, culture, research, general")
    executive_summary: str = Field(..., min_length=20, max_length=500)
    problem_statement: str = Field(..., min_length=20, max_length=2000)
    proposed_solution: dict = Field(..., description="Technical implementation details")
    system_impact: dict = Field(..., description="Affected services, tables, endpoints")
    downtime_estimate: str = Field("zero")
    cost_analysis: dict = Field(default_factory=dict)
    performance_projections: dict = Field(default_factory=dict)
    security_assessment: dict = Field(default_factory=dict)
    rollback_plan: str = Field(..., min_length=10)
    dependencies: list = Field(default_factory=list)
    success_criteria: list = Field(default_factory=list)
    cross_cli_coordination: Optional[str] = None


class InnovationDecisionBody(BaseModel):
    approved: bool
    admin_note: Optional[str] = None


def _check_innovation_rate(proposer: str) -> bool:
    """Circuit breaker: max 10 proposals per proposer per 24h."""
    import time as _time
    now = _time.time()
    cutoff = now - _INNOVATION_RATE_WINDOW
    recent = _INNOVATION_RATE_LIMIT.get(proposer, [])
    recent = [t for t in recent if t > cutoff]
    _INNOVATION_RATE_LIMIT[proposer] = recent
    return len(recent) < _INNOVATION_RATE_MAX


@cli_router.post("/innovation/propose")
async def submit_innovation_proposal(
    body: InnovationProposalBody,
    request: Request,
    cli_id: str = Depends(_resolve_cli_identity),
):
    """Submit an executive innovation proposal from a CLI or domain agent."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")

    if not _check_innovation_rate(cli_id):
        raise HTTPException(429, f"Rate limit: max {_INNOVATION_RATE_MAX} proposals per 24h")

    solution_text = json.dumps(body.proposed_solution)
    rz = _check_red_zone(None, solution_text, body.problem_statement)
    if rz:
        raise HTTPException(403, rz)

    if body.extension_type == "table":
        table_name = body.proposed_solution.get("table_name", "")
        if table_name and not table_name.startswith("nate_ext_"):
            raise HTTPException(422, "Table names must start with 'nate_ext_'")

    import time as _time
    _INNOVATION_RATE_LIMIT.setdefault(cli_id, []).append(_time.time())

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO innovation_proposals
                (proposed_by, extension_type, domain, executive_summary, problem_statement,
                 proposed_solution, system_impact, downtime_estimate, cost_analysis,
                 performance_projections, security_assessment, rollback_plan,
                 dependencies, success_criteria, cross_cli_coordination)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9::jsonb,
                        $10::jsonb, $11::jsonb, $12, $13::jsonb, $14::jsonb, $15)
                RETURNING id, proposed_at
            """,
                cli_id, body.extension_type, body.domain,
                body.executive_summary, body.problem_statement,
                json.dumps(body.proposed_solution), json.dumps(body.system_impact),
                body.downtime_estimate, json.dumps(body.cost_analysis),
                json.dumps(body.performance_projections), json.dumps(body.security_assessment),
                body.rollback_plan, json.dumps(body.dependencies),
                json.dumps(body.success_criteria), body.cross_cli_coordination,
            )
        return {
            "status": "ok",
            "proposal_id": str(row["id"]),
            "proposed_at": row["proposed_at"].isoformat(),
        }
    except Exception as e:
        logger.warning("Innovation proposal submission failed: %s", e)
        raise HTTPException(500, f"Failed to store proposal: {e}")


# ── CLI-Cloud Repair Dispatch (Mac Agent) ──

_REPAIR_OP_TO_AGENT_ENDPOINT = {
    "shell": "/exec",
    "restart": "/process/manage",
    "start": "/process/manage",
    "stop": "/process/manage",
    "file_write": "/file/write",
    "file_delete": "/file/delete",
    "git": "/git",
    "build": "/build",
}


class DispatchRepairBody(BaseModel):
    request_id: str


@router.post("/cli/dispatch-repair")
async def dispatch_repair(
    body: DispatchRepairBody,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Dispatch an approved CLI-Mac repair to the Mac agent. Admin-only."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    mac_agent_url = os.getenv("MAC_AGENT_URL", "")
    mac_agent_token = os.getenv("MAC_AGENT_TOKEN", "")
    if not mac_agent_url:
        raise HTTPException(503, "MAC_AGENT_URL not configured")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM source_repair_requests WHERE id = $1",
            uuid.UUID(body.request_id),
        )
    if not row:
        raise HTTPException(404, f"Repair request {body.request_id} not found")
    if row["status"] != "approved":
        raise HTTPException(400, f"Repair request status is '{row['status']}', expected 'approved'")
    if row["executor_cli"] != "cli-mac":
        raise HTTPException(400, f"Executor is '{row['executor_cli']}', expected 'cli-mac'")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE source_repair_requests SET status = 'executing' WHERE id = $1",
            uuid.UUID(body.request_id),
        )

    plan_text = row["plan"] or "{}"
    try:
        repair_plan = json.loads(plan_text) if isinstance(plan_text, str) else plan_text
    except (json.JSONDecodeError, TypeError):
        repair_plan = {"operations": [{"type": "shell", "payload": {"command": plan_text}}]}

    operations = repair_plan.get("operations", [])
    if not operations:
        operations = [{"type": "shell", "payload": {"command": str(plan_text)[:500]}}]

    step_results = []
    all_succeeded = True
    failed_step_index = None

    import aiohttp
    timeout = aiohttp.ClientTimeout(total=660)
    headers = {"Authorization": f"Bearer {mac_agent_token}"}

    for i, step in enumerate(operations):
        op_type = step.get("type", "shell")
        endpoint = _REPAIR_OP_TO_AGENT_ENDPOINT.get(op_type, "/exec")
        payload = step.get("payload", {})

        if op_type in ("restart", "start", "stop") and "action" not in payload:
            payload["action"] = op_type

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{mac_agent_url.rstrip('/')}{endpoint}"
                async with session.post(url, json=payload, headers=headers) as resp:
                    result = await resp.json()
        except Exception as e:
            result = {"status": "error", "error": f"Mac agent unreachable: {e}", "error_code": "MAC_AGENT_OFFLINE"}

        step_results.append({"step": i + 1, "type": op_type, "result": result})

        step_failed = result.get("status") == "error"
        if not step_failed and op_type in ("shell", "build", "git"):
            ec = result.get("exit_code")
            if ec is not None and ec != 0:
                step_failed = True
                result["_dispatch_note"] = f"Nonzero exit code {ec} treated as failure"

        if step_failed:
            all_succeeded = False
            failed_step_index = i + 1
            break

    final_status = "completed" if all_succeeded else "execution_failed"
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE source_repair_requests SET status = $1 WHERE id = $2",
            final_status, uuid.UUID(body.request_id),
        )

    if _RERUN_ON_CLI_REPAIR and all_succeeded:
        asyncio.create_task(
            _trigger_nightly_audit_rerun(
                request.app,
                body.request_id,
                row.get("scope"),
                row.get("target"),
            )
        )

    response = {
        "status": final_status,
        "request_id": body.request_id,
        "steps_total": len(operations),
        "steps_completed": len([s for s in step_results if s["result"].get("status") == "ok"]),
        "step_results": step_results,
        "failed_at_step": failed_step_index,
    }
    if not all_succeeded:
        response["note"] = "No auto-rollback in v1. Review step_results to assess cleanup needs."

    return response


@router.get("/innovations/pending")
async def list_pending_innovations(request: Request, _admin=Depends(require_admin)):
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        return {"proposals": []}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, proposed_by, extension_type, domain, executive_summary,
                       status, proposed_at
                FROM innovation_proposals
                WHERE status = 'pending'
                ORDER BY proposed_at DESC
                LIMIT 50
            """)
        return {"proposals": [_row_to_dict(r) for r in rows]}
    except Exception as e:
        logger.warning("Innovation list error: %s", e)
        return {"proposals": []}


@router.get("/innovations/{proposal_id}")
async def get_innovation_detail(proposal_id: str, request: Request,
                                _admin=Depends(require_admin)):
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM innovation_proposals WHERE id = $1",
                uuid.UUID(proposal_id),
            )
        if not row:
            raise HTTPException(404, "Proposal not found")
        return {"proposal": _row_to_dict(row)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/innovations/{proposal_id}/decide")
async def decide_innovation(proposal_id: str, body: InnovationDecisionBody,
                            request: Request, _admin=Depends(require_admin)):
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")
    new_status = "approved" if body.approved else "rejected"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE innovation_proposals
                   SET status = $1, decided_by = 'DrNevedal1', decided_at = NOW(),
                       admin_note = $2
                   WHERE id = $3 AND status = 'pending'
                   RETURNING id, status""",
                new_status, body.admin_note, uuid.UUID(proposal_id),
            )
        if not row:
            raise HTTPException(404, "Proposal not found or not pending")
        return {"status": "ok", "proposal_id": str(row["id"]), "decision": new_status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/innovations/{proposal_id}/execute")
async def execute_innovation(proposal_id: str, request: Request,
                             _admin=Depends(require_admin)):
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")
    try:
        async with db_pool.acquire() as conn:
            prop = await conn.fetchrow(
                "SELECT * FROM innovation_proposals WHERE id = $1 AND status = 'approved'",
                uuid.UUID(proposal_id),
            )
        if not prop:
            raise HTTPException(404, "Proposal not found or not approved")

        ext_type = prop["extension_type"]
        domain = prop["domain"]
        solution = prop["proposed_solution"]
        if isinstance(solution, str):
            solution = json.loads(solution)

        result = {"executed": True}

        if ext_type == "table":
            sandbox = getattr(request.app.state, "d1_sandbox_executor", None)
            if sandbox:
                table_name = solution.get("table_name", "")
                columns = solution.get("columns", [])
                r = await sandbox.create_table(table_name, columns, str(prop["id"]), domain)
                result["d1_result"] = r

        if ext_type == "formula":
            registry = getattr(request.app.state, "formula_registry", None)
            if registry:
                await registry.load_from_db()
                result["formulas_loaded"] = len(registry.list_formulas())

        async with db_pool.acquire() as conn:
            name = solution.get("name", solution.get("table_name", f"ext_{ext_type}_{domain}"))
            await conn.execute(
                """INSERT INTO nate_extensions
                   (innovation_proposal_id, extension_type, domain, name, definition,
                    d1_table_name)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                   ON CONFLICT (extension_type, name) DO UPDATE SET
                    definition = EXCLUDED.definition, active = true, deactivated_at = NULL""",
                uuid.UUID(proposal_id), ext_type, domain, name,
                json.dumps(solution),
                solution.get("table_name"),
            )
            await conn.execute(
                """UPDATE innovation_proposals
                   SET status = 'executed', executed_at = NOW(),
                       execution_result = $1::jsonb
                   WHERE id = $2""",
                json.dumps(result), uuid.UUID(proposal_id),
            )

        return {"status": "ok", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Innovation execution failed: %s", e)
        raise HTTPException(500, str(e))


@router.get("/extensions/active")
async def list_active_extensions(request: Request, _admin=Depends(require_admin)):
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        return {"extensions": []}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT e.id, e.extension_type, e.domain, e.name, e.d1_table_name,
                       e.created_at, p.executive_summary
                FROM nate_extensions e
                LEFT JOIN innovation_proposals p ON e.innovation_proposal_id = p.id
                WHERE e.active = true
                ORDER BY e.created_at DESC
            """)
        return {"extensions": [_row_to_dict(r) for r in rows]}
    except Exception as e:
        logger.warning("Extension list error: %s", e)
        return {"extensions": []}


@router.post("/extensions/{ext_id}/deactivate")
async def deactivate_extension(ext_id: str, request: Request,
                               _admin=Depends(require_admin)):
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE nate_extensions SET active = false, deactivated_at = NOW()
                   WHERE id = $1 AND active = true RETURNING id, name""",
                uuid.UUID(ext_id),
            )
        if not row:
            raise HTTPException(404, "Extension not found or already inactive")
        return {"status": "ok", "deactivated": str(row["id"]), "name": row["name"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/extensions/{ext_id}/query")
async def query_extension_data(ext_id: str, request: Request,
                               limit: int = Query(100, ge=1, le=1000),
                               _admin=Depends(require_admin)):
    """Query D1 sandbox for extension data (widget data source)."""
    db_pool = getattr(request.app.state, "db_pool", None)
    sandbox = getattr(request.app.state, "d1_sandbox_executor", None)
    if not db_pool or not sandbox:
        return {"data": []}
    try:
        async with db_pool.acquire() as conn:
            ext = await conn.fetchrow(
                "SELECT d1_table_name, extension_type, name FROM nate_extensions WHERE id = $1",
                uuid.UUID(ext_id),
            )
        if not ext:
            raise HTTPException(404, "Extension not found")

        table = ext.get("d1_table_name")
        ext_type = ext.get("extension_type")

        if ext_type == "formula":
            data = await sandbox.query("nate_ext_formula_results",
                                       f"formula_name = ?",
                                       [ext.get("name", "")], limit=limit)
        elif table:
            data = await sandbox.query(table, limit=limit)
        else:
            data = []

        return {"data": data or [], "table": table, "extension_type": ext_type}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Extension data query error: %s", e)
        return {"data": []}


# ═══════════════════════════════════════════════════════════════════════════
# BLOB STORAGE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

async def _store_report_blob(request_id: str, completion: str, combined: Optional[str]):
    """Store completion report in R2 as a blob alongside the DB record."""
    try:
        from app.services.r2_storage import upload_bytes_async, is_r2_configured
        if not is_r2_configured():
            return
        report = json.dumps({
            "request_id": request_id,
            "completion_report": completion,
            "combined_report": combined,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        })
        await upload_bytes_async(
            key=f"cli-builds/{request_id}/completion_report.json",
            content=report.encode("utf-8"),
            content_type="application/json",
        )
    except Exception as e:
        logger.warning("Report blob storage failed for %s: %s", request_id, e)


# ═══════════════════════════════════════════════════════════════════════════
# CODE INTELLIGENCE — Bulk Ingestion & Cycle Detection Admin API
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/admin/ingestion/run-all", dependencies=[Depends(require_admin)])
async def run_full_ingestion(request: Request):
    """Trigger all 4 bulk ingestion acceleration levers + edge push."""
    ingestion = getattr(request.app.state, "bulk_crystal_ingestion", None)
    if not ingestion:
        raise HTTPException(503, "BulkCrystalIngestion not initialized")
    result = await ingestion.run_full_acceleration()
    return {"status": "ok", "result": result}


@router.post("/admin/ingestion/codebase-scan", dependencies=[Depends(require_admin)])
async def run_codebase_scan(request: Request):
    """Trigger Lever 1: Codebase bulk scan."""
    ingestion = getattr(request.app.state, "bulk_crystal_ingestion", None)
    if not ingestion:
        raise HTTPException(503, "BulkCrystalIngestion not initialized")
    result = await ingestion.run_codebase_scan()
    return {"status": "ok", "lever": "codebase", "result": result}


@router.post("/admin/ingestion/github-trending", dependencies=[Depends(require_admin)])
async def run_github_trending(request: Request):
    """Trigger Lever 2: GitHub trending repos."""
    ingestion = getattr(request.app.state, "bulk_crystal_ingestion", None)
    if not ingestion:
        raise HTTPException(503, "BulkCrystalIngestion not initialized")
    result = await ingestion.run_github_trending()
    return {"status": "ok", "lever": "github", "result": result}


@router.post("/admin/ingestion/stackoverflow", dependencies=[Depends(require_admin)])
async def run_stackoverflow(request: Request):
    """Trigger Lever 3: StackOverflow top answers."""
    ingestion = getattr(request.app.state, "bulk_crystal_ingestion", None)
    if not ingestion:
        raise HTTPException(503, "BulkCrystalIngestion not initialized")
    result = await ingestion.run_stackoverflow()
    return {"status": "ok", "lever": "stackoverflow", "result": result}


@router.post("/admin/ingestion/synthesis-burst", dependencies=[Depends(require_admin)])
async def run_synthesis_burst(request: Request):
    """Trigger Lever 4: Synthesis budget acceleration (4x burst)."""
    ingestion = getattr(request.app.state, "bulk_crystal_ingestion", None)
    if not ingestion:
        raise HTTPException(503, "BulkCrystalIngestion not initialized")
    result = await ingestion.run_synthesis_burst()
    return {"status": "ok", "lever": "synthesis", "result": result}


@router.post("/admin/ingestion/push-edge", dependencies=[Depends(require_admin)])
async def push_crystals_to_edge(request: Request):
    """Push top code crystals to R2 manifest for cron worker pre-warming."""
    ingestion = getattr(request.app.state, "bulk_crystal_ingestion", None)
    if not ingestion:
        raise HTTPException(503, "BulkCrystalIngestion not initialized")
    result = await ingestion._push_to_edge_kv()
    return {"status": "ok", "result": result}


@router.get("/admin/ingestion/status", dependencies=[Depends(require_admin)])
async def get_ingestion_status(request: Request):
    """Return code crystal metrics and ingestion pipeline health."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        return {"status": "no_database"}

    try:
        async with db_pool.acquire() as conn:
            crystal_count = await conn.fetchval("""
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE domain = 'coding' AND scope != 'archived'
            """)
            archived_count = await conn.fetchval("""
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE domain = 'coding' AND scope = 'archived'
            """)
            recent_crystals = await conn.fetchval("""
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE domain = 'coding' AND scope != 'archived'
                  AND created_at > NOW() - INTERVAL '24 hours'
            """)
            c_emo_state = await conn.fetchrow("""
                SELECT C_emo, p_ent, gamma_env, T_tunnel, crystal_count
                FROM nevedal_domain_state WHERE domain = 'coding'
            """)
            prewarm_count = await conn.fetchval("""
                SELECT COUNT(*) FROM crystal_prewarm_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """) or 0
            divergence_count = await conn.fetchval("""
                SELECT COUNT(*) FROM code_divergence_log
                WHERE detected_at > NOW() - INTERVAL '7 days'
            """) or 0

        return {
            "status": "ok",
            "crystals": {
                "active": crystal_count or 0,
                "archived": archived_count or 0,
                "created_last_24h": recent_crystals or 0,
            },
            "c_emo": dict(c_emo_state) if c_emo_state else None,
            "prewarm_events_24h": prewarm_count,
            "divergence_events_7d": divergence_count,
        }
    except Exception as e:
        logger.warning("Ingestion status query failed: %s", e)
        return {"status": "error", "error": str(e)}


@router.post("/admin/cycle-detector/run", dependencies=[Depends(require_admin)])
async def run_cycle_detection(request: Request):
    """Trigger a full CodeCycleDetector analysis cycle."""
    detector = getattr(request.app.state, "code_cycle_detector", None)
    if not detector:
        raise HTTPException(503, "CodeCycleDetector not initialized")
    result = await detector.run_cycle()
    return {"status": "ok", "result": result}


# ═══════════════════════════════════════════════════════════════════════════
# EXA METHODOLOGY — Dual-Brain Reporting, Milestones, Foresight
# ═══════════════════════════════════════════════════════════════════════════

@exa_public_router.post("/dual-brain-report")
async def report_dual_brain(request: Request):
    """Endpoint for summon worker to report dual-brain coherence scores.
    No admin auth — the summon worker authenticates via HMAC at the edge."""
    body = await request.json()
    hook = getattr(request.app.state, "exa_hook", None)
    if not hook:
        raise HTTPException(503, "ExaCrystallizationHook not initialized")

    result = await hook.report_dual_brain_coherence(
        edge_response=body.get("edge_response", ""),
        sovereign_response=body.get("sovereign_response", ""),
        query=body.get("query", ""),
        signal=body.get("signal", "PROVISIONAL"),
        provider_edge=body.get("provider_edge", "workers_ai"),
        provider_sovereign=body.get("provider_sovereign", "sovereign"),
    )
    return {"status": "ok", "coherence": result}


@router.get("/admin/exa/status", dependencies=[Depends(require_admin)])
async def get_exa_status(request: Request):
    """Return full EXA methodology status with milestone progress."""
    hook = getattr(request.app.state, "exa_hook", None)
    if not hook:
        return {"status": "not_initialized"}
    return await hook.get_exa_status()


@router.get("/admin/exa/foresight", dependencies=[Depends(require_admin)])
async def get_foresight_status(request: Request):
    """Return CodeForesightEngine status and latest forecast."""
    engine = getattr(request.app.state, "code_foresight_engine", None)
    if not engine:
        return {"status": "not_initialized"}
    return engine.get_status()


@router.post("/admin/exa/foresight/run", dependencies=[Depends(require_admin)])
async def run_foresight_cycle(request: Request):
    """Trigger a foresight analysis cycle manually."""
    engine = getattr(request.app.state, "code_foresight_engine", None)
    if not engine:
        raise HTTPException(503, "CodeForesightEngine not initialized")
    await engine._cycle()
    return {"status": "ok", "forecast": engine._last_forecast}


@router.post("/admin/exa/crystal-audit/run", dependencies=[Depends(require_admin)])
async def run_crystal_audit(request: Request):
    """Trigger a crystal quality audit manually."""
    auditor = getattr(request.app.state, "crystal_quality_auditor", None)
    if not auditor:
        raise HTTPException(503, "CrystalQualityAuditor not initialized")
    await auditor._cycle()
    return {"status": "ok", "audit": auditor._last_audit}


@router.post("/admin/crystallizer/acceleration", dependencies=[Depends(require_admin)])
async def toggle_acceleration_mode(request: Request):
    """Toggle crystal acceleration mode on/off."""
    body = await request.json()
    enabled = body.get("enabled", False)
    crystallizer = getattr(request.app.state, "nate_memory_crystallizer", None)
    if not crystallizer:
        raise HTTPException(503, "NateMemoryCrystallizer not initialized")
    crystallizer.set_acceleration_mode(enabled)
    return {"status": "ok", "acceleration_mode": enabled}


# ═══════════════════════════════════════════════════════════════════════════
# CRYSTAL NETWORK — push from BLUE/factory nodes, network status dashboard
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/admin/crystal-network/push", dependencies=[Depends(require_admin)])
async def push_crystals(request: Request):
    """Accept crystals from BLUE or factory nodes and write to PostgreSQL.

    Body: {"crystals": [{"crystal_text", "domain", "scope", "topics",
           "source_count", "confidence", "content_hash", "face_path",
           "context_start", "context_end"}, ...]}
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")

    body = await request.json()
    crystals = body.get("crystals", [])

    inserted = 0
    skipped = 0

    if not crystals:
        # Still write watermark even with 0 crystals (keeps BLUE total current)
        node_id = body.get("node_id")
        node_total = body.get("node_total")
        if node_id and node_total is not None:
            wm_key = f"crystal_factory_watermark:{node_id}"
            try:
                async with db_pool.acquire() as wm_conn:
                    await wm_conn.execute("""
                        INSERT INTO crystal_factory_watermarks (node_id, last_harvest, crystals_total)
                        VALUES ($1, NOW(), $2)
                        ON CONFLICT (node_id) DO UPDATE SET
                            last_harvest = NOW(),
                            crystals_total = EXCLUDED.crystals_total
                    """, wm_key, int(node_total))
            except Exception as wm_err:
                logger.warning("BLUE watermark write failed: %s", wm_err)
        return {"status": "ok", "inserted": 0, "skipped": 0}
    def _coerce_ts(val):
        if val is None:
            return None
        if isinstance(val, str):
            from datetime import datetime as _dt
            return _dt.fromisoformat(val)
        return val

    inserted_crystals = []
    async with db_pool.acquire() as conn:
        for c in crystals:
            if not c.get("crystal_text") or not c.get("content_hash"):
                skipped += 1
                continue
            try:
                result = await conn.execute("""
                    INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, context_start,
                     context_end, face_path, origin_surface)
                    VALUES ($1, $2, $3, $4, $5, 0, $6, $7,
                            $8, $9, $10, $11)
                    ON CONFLICT (content_hash) DO NOTHING
                """,
                    c["crystal_text"],
                    c.get("domain", "general"),
                    c.get("scope", "global"),
                    c.get("topics", []),
                    c.get("source_count", 1),
                    c.get("confidence", 0.60),
                    c["content_hash"],
                    _coerce_ts(c.get("context_start")),
                    _coerce_ts(c.get("context_end")),
                    c.get("face_path", "bridge:mac-blue"),
                    c.get("origin_surface", "blue_harvest"),
                )
                if result and "INSERT" in result:
                    inserted += 1
                    inserted_crystals.append(c)
                else:
                    skipped += 1
            except Exception as e:
                logger.warning("Crystal push insert failed: %s", e)
                skipped += 1

        node_id = body.get("node_id")
        node_total = body.get("node_total")
        if node_id and node_total is not None:
            wm_key = f"crystal_factory_watermark:{node_id}"
            try:
                await conn.execute("""
                    INSERT INTO crystal_factory_watermarks (node_id, last_harvest, crystals_total)
                    VALUES ($1, NOW(), $2)
                    ON CONFLICT (node_id) DO UPDATE SET
                        last_harvest = NOW(),
                        crystals_total = EXCLUDED.crystals_total
                """, wm_key, int(node_total))
                await conn.execute("""
                    INSERT INTO crystal_factory_heartbeats
                    (node_id, cycle_number, fragments_harvested, clusters_formed,
                     crystals_forged, crystals_deduped, elapsed_seconds)
                    VALUES ($1, 0, 0, 0, $2, $3, 0)
                """, wm_key, inserted, skipped)
            except Exception as wm_err:
                logger.warning("BLUE watermark/heartbeat write failed: %s", wm_err)

    if inserted_crystals:
        try:
            from app.services.vectorize_service import index_wisdom, is_vectorize_configured
            if is_vectorize_configured():
                for c in inserted_crystals:
                    try:
                        _ch = c["content_hash"]
                        await index_wisdom(
                            user_id="nate_crystal",
                            wisdom_id=f"crystal_{_ch[:16]}",
                            insight_type=f"crystal_{c.get('domain', 'general')}",
                            content=c["crystal_text"],
                            source="crystal_push",
                            domain=c.get("domain", "general"),
                            face_path=c.get("face_path", ""),
                        )
                    except Exception as _vz_err:
                        logger.warning("Crystal push Vectorize index failed: %s", _vz_err)
        except Exception:
            pass

    return {"status": "ok", "inserted": inserted, "skipped": skipped}


@router.post("/admin/crystal-heartbeat", dependencies=[Depends(require_admin)])
async def receive_crystal_heartbeat(request: Request):
    """Receive heartbeat from Blue Harvester (Mac local) and write to
    crystal_factory_heartbeats in production PostgreSQL + Redis for live status."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")
    data = await request.json()
    node_id = data.get("node_id", "unknown")
    hb_status = data.get("status", "running")
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO crystal_factory_heartbeats
                (node_id, cycle_number, fragments_harvested, clusters_formed,
                 crystals_forged, crystals_deduped, stage1_filtered,
                 stage2_synthesized, elapsed_seconds)
                VALUES ($1, 0, $2, 0, $3, 0, $4, $5, 0)
            """,
                node_id,
                data.get("chunks_processed", 0),
                data.get("crystals_forged", 0),
                data.get("chunks_passed", 0),
                data.get("chunks_total", 0),
            )
    except Exception as e:
        logger.warning("Crystal heartbeat PG write failed: %s", e)
    # Write live transient status to Redis (current_scanner, pass_rate, etc.)
    _redis = await _get_crystal_redis()
    if _redis:
        try:
            from datetime import datetime as _dt
            await _redis.set("crystal_system_status:blue_harvester", json.dumps({
                "running": hb_status not in ("idle", "offline", "error"),
                "last_updated": _dt.utcnow().isoformat(),
                "status": hb_status,
                "chunks_processed": data.get("chunks_processed", 0),
                "chunks_total": data.get("chunks_total", 0),
                "chunks_passed": data.get("chunks_passed", 0),
                "pass_rate": data.get("pass_rate", 0),
                "current_scanner": data.get("current_scanner", ""),
                "current_file": data.get("current_file", ""),
                "crystals_forged": data.get("crystals_forged", 0),
                "avg_filter_time_ms": data.get("avg_filter_time_ms", 0),
            }), ex=300)
        except Exception as _re:
            logger.debug("Crystal heartbeat Redis write failed: %s", _re)
    return {"ok": True, "node_id": node_id}


async def _get_exa_status_or_fallback(request: Request, total_crystals: int):
    """QUANTUM-CRYSTAL-ARCH: Use real ExaFLOPS methodology, fall back to crystal count."""
    exa_hook = getattr(request.app.state, "exa_crystallization_hook", None)
    if exa_hook:
        try:
            status = await exa_hook.get_exa_status()
            if status.get("status") == "ok":
                return status
        except Exception as _e:
            logger.debug("EXA status call failed, using fallback: %s", _e)
    return {
        "status": "fallback",
        "note": "ExaFLOPS methodology pending — nevedal_domain_state not yet seeded",
        "crystal_count": total_crystals,
        "vanity_number": round(total_crystals * 0.00008, 2),
    }


@router.get("/admin/crystal-network/status", dependencies=[Depends(require_admin)])
async def crystal_network_status(request: Request):
    """Return crystal counts per node for the network dashboard."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                CASE
                    WHEN face_path LIKE 'factory:hetzner%'       THEN 'hetzner-finland'
                    WHEN face_path LIKE 'factory:digitalocean%'  THEN 'digitalocean-primary'
                    ELSE 'mac-blue'
                END AS node,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS last_24h,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days')  AS last_7d,
                array_agg(DISTINCT domain) AS domains
            FROM nate_intelligence_crystals
            WHERE scope != 'archived' AND superseded_by IS NULL
            GROUP BY 1
            ORDER BY 1
        """)

        heartbeats = []
        try:
            heartbeats = await conn.fetch("""
                SELECT DISTINCT ON (node_id)
                    node_id, cycle_number, crystals_forged,
                    fragments_harvested, clusters_formed,
                    stage1_filtered, stage2_synthesized,
                    crystals_deduped, elapsed_seconds, created_at,
                    (created_at > NOW() - INTERVAL '60 minutes') AS healthy
                FROM crystal_factory_heartbeats
                ORDER BY node_id, created_at DESC
            """)
        except Exception:
            pass

    # Fetch watermark totals to correct BLUE undercounting from face_path dedup
    watermark_totals = {}
    try:
        async with db_pool.acquire() as wm_conn:
            wm_rows = await wm_conn.fetch("""
                SELECT node_id, crystals_total
                FROM crystal_factory_watermarks
            """)
            for wr in wm_rows:
                short = wr["node_id"].replace("crystal_factory_watermark:", "")
                watermark_totals[short] = wr["crystals_total"]
    except Exception:
        pass

    hb_map = {}
    for h in heartbeats:
        hd = dict(h)
        hb_map[hd.get("node_id", "")] = hd

    nodes = []
    for r in rows:
        node_name = r["node"]
        total = r["total"]
        wm = watermark_totals.get(node_name)
        if wm is not None and wm > total:
            total = wm
        hb = hb_map.get(node_name, {})
        hb_created = hb.get("created_at")
        hb_healthy = hb.get("healthy", False)
        nodes.append({
            "node": node_name,
            "total": total,
            "last_24h": r["last_24h"],
            "last_7d": r["last_7d"],
            "domains": sorted(set(d for d in (r["domains"] or []) if d)),
            "status": "healthy" if hb_healthy else ("stale" if hb else "unknown"),
            "last_heartbeat": hb_created.isoformat() if hasattr(hb_created, "isoformat") else str(hb_created) if hb_created else None,
        })

    # --- Enhanced fields for Crystal Intelligence dashboard ---
    # Read bridge-reported AC / SE status from Redis
    ac_status = {"running": False, "crystals_forged": 0, "buffer_size": 0}
    se_status = {"enabled": False, "running": False, "jobs_completed": 0}
    _redis = await _get_crystal_redis()
    if _redis:
        try:
            _ac_raw = await _redis.get("crystal_system_status:autonomous_controller")
            if _ac_raw:
                ac_status = json.loads(_ac_raw)
            _se_raw = await _redis.get("crystal_system_status:subconscious_engine")
            if _se_raw:
                se_status = json.loads(_se_raw)
        except Exception:
            pass

    # Blue Harvester status from heartbeats + Redis
    bh_status = {"status": "offline", "last_heartbeat": None,
                 "chunks_processed": 0, "chunks_total": 0, "chunks_passed": 0,
                 "pass_rate": 0, "crystals_forged": 0, "current_scanner": None}
    if _redis:
        try:
            _bh_raw = await _redis.get("crystal_system_status:blue_harvester")
            if _bh_raw:
                _bh_data = json.loads(_bh_raw)
                _bh_running = _bh_data.get("running", False)
                _bh_ts = _bh_data.get("last_updated")
                bh_status.update({
                    "status": "active" if _bh_running else "stale",
                    "last_heartbeat": _bh_ts,
                    "chunks_processed": _bh_data.get("chunks_processed", 0),
                    "chunks_total": _bh_data.get("chunks_total", 0),
                    "chunks_passed": _bh_data.get("chunks_passed", 0),
                    "pass_rate": _bh_data.get("pass_rate", 0),
                    "current_scanner": _bh_data.get("current_scanner"),
                    "crystals_forged": _bh_data.get("crystals_forged", 0),
                })
        except Exception:
            pass
    # Enrich with latest heartbeat row from crystal_factory_heartbeats
    for nid, hd in hb_map.items():
        if "mac" in nid.lower() or "blue" in nid.lower():
            created = hd.get("created_at")
            _ts = created.isoformat() if hasattr(created, "isoformat") else str(created) if created else None
            if bh_status["status"] == "offline":
                bh_status["status"] = "active" if hd.get("healthy", False) else "stale"
            bh_status["last_heartbeat"] = bh_status.get("last_heartbeat") or _ts
            bh_status["chunks_processed"] = hd.get("fragments_harvested", 0)
            bh_status["chunks_passed"] = hd.get("stage1_filtered", hd.get("clusters_formed", 0))
            bh_status["chunks_total"] = hd.get("stage2_synthesized", hd.get("crystals_deduped", 0))
            bh_status["crystals_forged"] = hd.get("crystals_forged", 0)
            _cp = bh_status["chunks_processed"]
            bh_status["pass_rate"] = round(bh_status["chunks_passed"] / max(_cp, 1), 3)
            break

    # Totals from actual DB (includes bridge crystallization, not just factory nodes)
    total_crystals = 0
    total_24h = 0
    rate_per_hour = 0
    try:
        async with db_pool.acquire() as tc:
            row = await tc.fetchrow("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS last_24h,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') AS last_1h
                FROM nate_intelligence_crystals
                WHERE scope != 'archived' AND superseded_by IS NULL
            """)
            total_crystals = row["total"] or 0
            total_24h = row["last_24h"] or 0
            rate_per_hour = row["last_1h"] or 0
    except Exception:
        total_crystals = sum(n["total"] for n in nodes)
        total_24h = sum(n["last_24h"] for n in nodes)

    mac_agent_status = {"status": "offline"}
    _mac_url = os.getenv("MAC_AGENT_URL", "")
    _mac_token = os.getenv("MAC_AGENT_TOKEN", "")
    if _mac_url:
        try:
            import aiohttp
            _mac_timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=_mac_timeout) as _ms:
                _mh = {"Authorization": f"Bearer {_mac_token}"} if _mac_token else {}
                async with _ms.get(f"{_mac_url.rstrip('/')}/health", headers=_mh) as _mr:
                    if _mr.status == 200:
                        mac_agent_status = await _mr.json()
        except Exception:
            pass

    # QUANTUM-CRYSTAL-ARCH: Knowledge vs Wisdom ExaFLOPS split
    wisdom_metrics = {
        "user_scoped_crystals": 0,
        "lived_origin_crystals": 0,
        "clinical_dna_crystals": 0,
        "knowledge_exaflops": round(total_crystals * 0.00008, 4),
        "wisdom_exaflops": 0.0,
        # Growth-rate fields (Wisdom Growth Rate widget). Wisdom defined as
        # the deduplicated union: user_id IS NOT NULL OR origin_surface IN lived_set.
        "wisdom_total": 0,
        "wisdom_24h": 0,
        "wisdom_prev_24h": 0,
        "wisdom_rate_per_hour": 0.0,
        "wisdom_trend_pct": 0.0,
    }
    try:
        async with db_pool.acquire() as wm_conn:
            _wm_row = await wm_conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE user_id IS NOT NULL) AS user_scoped,
                    COUNT(*) FILTER (WHERE origin_surface IN
                        ('bridge_chat','voice_call','family_sanctuary',
                         'group_coaching','private_coaching','coached_response',
                         'growth_engine','clinical_edge_seed')) AS lived_origin,
                    COUNT(*) FILTER (WHERE origin_surface IN
                        ('growth_engine','clinical_edge_seed')) AS clinical_dna,
                    AVG(confidence) FILTER (WHERE user_id IS NOT NULL) AS avg_user_conf,
                    COUNT(*) FILTER (WHERE
                        user_id IS NOT NULL OR origin_surface IN
                        ('bridge_chat','voice_call','family_sanctuary',
                         'group_coaching','private_coaching','coached_response',
                         'growth_engine','clinical_edge_seed')
                    ) AS wisdom_total,
                    COUNT(*) FILTER (WHERE
                        created_at > NOW() - INTERVAL '24 hours'
                        AND (user_id IS NOT NULL OR origin_surface IN
                            ('bridge_chat','voice_call','family_sanctuary',
                             'group_coaching','private_coaching','coached_response',
                             'growth_engine','clinical_edge_seed'))
                    ) AS wisdom_24h,
                    COUNT(*) FILTER (WHERE
                        created_at > NOW() - INTERVAL '48 hours'
                        AND created_at <= NOW() - INTERVAL '24 hours'
                        AND (user_id IS NOT NULL OR origin_surface IN
                            ('bridge_chat','voice_call','family_sanctuary',
                             'group_coaching','private_coaching','coached_response',
                             'growth_engine','clinical_edge_seed'))
                    ) AS wisdom_prev_24h
                FROM nate_intelligence_crystals
                WHERE scope != 'archived' AND superseded_by IS NULL
            """)
            if _wm_row:
                _user_scoped = _wm_row["user_scoped"] or 0
                _lived = _wm_row["lived_origin"] or 0
                _dna = _wm_row["clinical_dna"] or 0
                _avg_conf = float(_wm_row["avg_user_conf"] or 0.5)
                wisdom_metrics["user_scoped_crystals"] = _user_scoped
                wisdom_metrics["lived_origin_crystals"] = _lived
                wisdom_metrics["clinical_dna_crystals"] = _dna
                _wisdom_base = _user_scoped + _lived
                wisdom_metrics["wisdom_exaflops"] = round(
                    _wisdom_base * _avg_conf * 0.00008, 4
                )
                _w_total = _wm_row["wisdom_total"] or 0
                _w_24h = _wm_row["wisdom_24h"] or 0
                _w_prev = _wm_row["wisdom_prev_24h"] or 0
                wisdom_metrics["wisdom_total"] = _w_total
                wisdom_metrics["wisdom_24h"] = _w_24h
                wisdom_metrics["wisdom_prev_24h"] = _w_prev
                wisdom_metrics["wisdom_rate_per_hour"] = round(_w_24h / 24.0, 2)
                if _w_prev > 0:
                    wisdom_metrics["wisdom_trend_pct"] = round(
                        ((_w_24h - _w_prev) / _w_prev) * 100.0, 1
                    )
                elif _w_24h > 0:
                    wisdom_metrics["wisdom_trend_pct"] = 100.0
                else:
                    wisdom_metrics["wisdom_trend_pct"] = 0.0
    except Exception:
        pass

    return {
        "status": "ok",
        "nodes": nodes,
        "heartbeats": [dict(h) for h in heartbeats],
        "autonomous_controller": ac_status,
        "subconscious_engine": se_status,
        "blue_harvester": bh_status,
        "mac_agent": mac_agent_status,
        "totals": {
            "total_crystals": total_crystals,
            "last_24h": total_24h,
            "last_1h": rate_per_hour,
            "rate_per_hour": rate_per_hour,
        },
        "exa_flops": await _get_exa_status_or_fallback(request, total_crystals),
        "wisdom_metrics": wisdom_metrics,
    }


# ═══════════════════════════════════════════════════════════════════════════
# CRYSTAL INTELLIGENCE — Yield Tracking
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/admin/crystal-network/yield", dependencies=[Depends(require_admin)])
async def crystal_yield_metrics(request: Request, days: int = 7):
    """QUANTUM-CRYSTAL-ARCH: crystals-per-session yield metrics."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")

    async with db_pool.acquire() as conn:
        _interval = f"{days} days"
        chat_yield = await conn.fetchrow("""
            WITH chat_sessions AS (
                SELECT COUNT(DISTINCT user_id) AS unique_users,
                       COUNT(*) AS total_turns
                FROM conversation_history
                WHERE created_at > NOW() - $1::interval
                  AND LENGTH(user_text) > 15
            ),
            chat_crystals AS (
                SELECT COUNT(*) AS cnt
                FROM nate_intelligence_crystals
                WHERE origin_surface = 'bridge_chat'
                  AND user_id IS NOT NULL
                  AND scope != 'archived'
                  AND created_at > NOW() - $1::interval
            )
            SELECT cs.unique_users AS sessions, cc.cnt AS crystals,
                   CASE WHEN cs.unique_users > 0
                        THEN ROUND(cc.cnt::numeric / cs.unique_users, 2)
                        ELSE 0 END AS yield_per_session
            FROM chat_sessions cs, chat_crystals cc
        """, _interval)

        voice_yield = await conn.fetchrow("""
            WITH vs AS (
                SELECT COUNT(*) AS sessions
                FROM voice_sessions
                WHERE started_at > NOW() - $1::interval
            ),
            vc AS (
                SELECT COUNT(*) AS cnt
                FROM nate_intelligence_crystals
                WHERE origin_surface = 'voice_call'
                  AND user_id IS NOT NULL
                  AND scope != 'archived'
                  AND created_at > NOW() - $1::interval
            )
            SELECT vs.sessions, vc.cnt AS crystals,
                   CASE WHEN vs.sessions > 0
                        THEN ROUND(vc.cnt::numeric / vs.sessions, 2)
                        ELSE 0 END AS yield_per_session
            FROM vs, vc
        """, _interval)

        by_surface = await conn.fetch("""
            SELECT origin_surface, COUNT(*) AS count,
                   AVG(confidence) AS avg_confidence,
                   COUNT(*) FILTER (WHERE user_id IS NOT NULL) AS user_scoped
            FROM nate_intelligence_crystals
            WHERE created_at > NOW() - $1::interval
              AND scope != 'archived'
              AND origin_surface IN ('bridge_chat','voice_call','family_sanctuary',
                                     'group_coaching','private_coaching','growth_engine')
            GROUP BY origin_surface
            ORDER BY count DESC
        """, _interval)

    return {
        "status": "ok",
        "period_days": days,
        "chat": {
            "sessions": chat_yield["sessions"] if chat_yield else 0,
            "crystals": chat_yield["crystals"] if chat_yield else 0,
            "yield_per_session": float(chat_yield["yield_per_session"]) if chat_yield else 0,
            "target": 5.0,
        },
        "voice": {
            "sessions": voice_yield["sessions"] if voice_yield else 0,
            "crystals": voice_yield["crystals"] if voice_yield else 0,
            "yield_per_session": float(voice_yield["yield_per_session"]) if voice_yield else 0,
            "target": 3.0,
        },
        "by_surface": [
            {
                "surface": r["origin_surface"],
                "count": r["count"],
                "avg_confidence": round(float(r["avg_confidence"] or 0), 3),
                "user_scoped": r["user_scoped"],
            }
            for r in by_surface
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# CRYSTAL INTELLIGENCE — Control & Diagnostics
# ═══════════════════════════════════════════════════════════════════════════

class CrystalControlRequest(BaseModel):
    system: Literal[
        "autonomous_controller", "subconscious_engine",
        "hetzner_crystal_factory", "digitalocean_crystal_factory",
        "blue_harvester",
    ]
    action: Literal["restart", "start", "stop", "enable", "disable"]


_crystal_control_cooldown: Dict[str, float] = {}


@router.post("/admin/crystal-network/control", dependencies=[Depends(require_admin)])
async def crystal_network_control(body: CrystalControlRequest, request: Request):
    """Control crystal production systems. Bridge-internal systems use Redis IPC;
    host-level systemd services return SSH commands for manual execution."""
    import time as _time

    last = _crystal_control_cooldown.get(body.system, 0)
    if _time.time() - last < 10:
        raise HTTPException(429, f"Rate limited — wait {10 - int(_time.time() - last)}s before retrying {body.system}")

    # Crystal Factory nodes: cannot be controlled from inside Docker
    if body.system in ("hetzner_crystal_factory", "digitalocean_crystal_factory"):
        ssh_commands = {
            "hetzner_crystal_factory": "ssh root@68.183.168.75 \"ssh root@10.13.13.5 'systemctl restart crystal-factory'\"",
            "digitalocean_crystal_factory": "ssh root@68.183.168.75 \"systemctl restart crystal-factory\"",
        }
        return {
            "status": "manual_only",
            "system": body.system,
            "action": body.action,
            "ssh_command": ssh_commands[body.system],
            "reason": "Crystal Factory runs as host-level systemd service; cannot be controlled from inside Docker containers.",
        }

    if body.system == "blue_harvester":
        return {
            "status": "manual_only",
            "system": "blue_harvester",
            "action": body.action,
            "instruction": "Run on Mac: python3 backend/blue_harvester.py",
            "reason": "Blue Harvester is a Mac-local process, not server-managed.",
        }

    # Bridge-controllable systems: publish via Redis pub/sub
    _redis = await _get_crystal_redis()
    if not _redis:
        raise HTTPException(503, "Redis not available — cannot communicate with bridge")

    request_id = str(uuid.uuid4())[:8]
    control_msg = json.dumps({
        "request_id": request_id,
        "system": body.system,
        "action": body.action,
    })

    try:
        await _redis.publish("crystal_control", control_msg)
    except Exception as e:
        raise HTTPException(503, f"Failed to publish control message: {e}")

    _crystal_control_cooldown[body.system] = _time.time()

    # Wait up to 10s for bridge to write result
    result_key = f"crystal_control_result:{request_id}"
    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            raw = await _redis.get(result_key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass

    return {
        "status": "timeout",
        "system": body.system,
        "action": body.action,
        "detail": "Bridge did not respond within 10s. The control message was sent — check bridge logs.",
    }


@router.get("/admin/crystal-network/diagnostics", dependencies=[Depends(require_admin)])
async def crystal_network_diagnostics(request: Request):
    """Return per-system error assessment using heartbeat data and Redis status."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")

    systems = {}

    async with db_pool.acquire() as conn:
        # Fetch latest heartbeats per node
        try:
            hb_rows = await conn.fetch("""
                SELECT DISTINCT ON (node_id)
                    node_id, cycle_number, crystals_forged,
                    fragments_harvested, elapsed_seconds, created_at,
                    (created_at > NOW() - INTERVAL '60 minutes') AS healthy
                FROM crystal_factory_heartbeats
                ORDER BY node_id, created_at DESC
            """)
        except Exception:
            hb_rows = []

        # Fetch last 3 heartbeats per node for trend analysis
        try:
            trend_rows = await conn.fetch("""
                SELECT node_id, crystals_forged, fragments_harvested, created_at
                FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY node_id ORDER BY created_at DESC) AS rn
                    FROM crystal_factory_heartbeats
                ) sub WHERE rn <= 3
                ORDER BY node_id, created_at DESC
            """)
        except Exception:
            trend_rows = []

    hb_by_node = {}
    for h in hb_rows:
        nid = h["node_id"]
        hb_by_node[nid] = dict(h)

    trend_by_node: Dict[str, list] = {}
    for t in trend_rows:
        nid = t["node_id"]
        trend_by_node.setdefault(nid, []).append(dict(t))

    def _diagnose_factory(label: str, node_pattern: str) -> dict:
        matching = {k: v for k, v in hb_by_node.items() if node_pattern in k.lower()}
        if not matching:
            return {"system": label, "code": "CF_HEARTBEAT_STALE", "status": "dead",
                    "message": f"No heartbeat found for {label}",
                    "fix": f"Check if the crystal-factory systemd service is running on the {label} node."}
        nid, hb = next(iter(matching.items()))
        if not hb.get("healthy", False):
            age_min = "unknown"
            if hb.get("created_at"):
                from datetime import datetime as _dt, timezone as _tz
                age = _dt.now(_tz.utc) - hb["created_at"].replace(tzinfo=_tz.utc) if hb["created_at"].tzinfo is None else _dt.now(_tz.utc) - hb["created_at"]
                age_min = f"{int(age.total_seconds() / 60)}m ago"
            return {"system": label, "code": "CF_HEARTBEAT_STALE", "status": "dead",
                    "message": f"Last heartbeat: {age_min}. Service likely stopped.",
                    "fix": f"Run: systemctl restart crystal-factory on the {label} host."}
        trends = trend_by_node.get(nid, [])
        if trends and all(t.get("crystals_forged", 0) == 0 for t in trends):
            if any(t.get("fragments_harvested", 0) > 0 for t in trends):
                return {"system": label, "code": "CF_OLLAMA_404", "status": "degraded",
                        "message": "Fragments harvested but zero crystals forged — Ollama inference likely failing.",
                        "fix": "Check Ollama connectivity: curl localhost:11434/api/tags"}
            return {"system": label, "code": "CF_ZERO_OUTPUT", "status": "degraded",
                    "message": "Service running but producing zero crystals.",
                    "fix": "Check PostgreSQL connectivity and dataset availability."}
        return {"system": label, "code": "HEALTHY", "status": "active",
                "message": f"Last cycle forged {hb.get('crystals_forged', 0)} crystals.",
                "last_heartbeat": hb["created_at"].isoformat() if hb.get("created_at") and hasattr(hb["created_at"], "isoformat") else None}

    systems["hetzner_crystal_factory"] = _diagnose_factory("Hetzner Crystal Factory", "hetzner")
    systems["digitalocean_crystal_factory"] = _diagnose_factory("DigitalOcean Crystal Factory", "digitalocean")

    # Autonomous Controller + Subconscious Engine from Redis
    _redis = await _get_crystal_redis()

    ac_diag = {"system": "Autonomous Controller", "code": "AC_NOT_RUNNING", "status": "unknown",
               "message": "No status data from bridge.", "fix": "Verify ENABLE_AUTONOMOUS=true and restart bridge."}
    se_diag = {"system": "Subconscious Engine", "code": "SE_DISABLED", "status": "unknown",
               "message": "No status data from bridge.", "fix": "Set ENABLE_SUBCONSCIOUS=true and restart bridge."}

    if _redis:
        try:
            ac_raw = await _redis.get("crystal_system_status:autonomous_controller")
            if ac_raw:
                ac_data = json.loads(ac_raw)
                if ac_data.get("running"):
                    if ac_data.get("crystals_forged", 0) == 0:
                        ac_diag = {"system": "Autonomous Controller", "code": "AC_ZERO_OUTPUT", "status": "degraded",
                                   "message": f"Running but 0 crystals forged. Buffer: {ac_data.get('buffer_size', 0)} fragments.",
                                   "fix": "Check Grok inference reachability from bridge container. Add synthesis logging."}
                    else:
                        ac_diag = {"system": "Autonomous Controller", "code": "HEALTHY", "status": "active",
                                   "message": f"Running. Forged {ac_data.get('crystals_forged', 0)} crystals. Buffer: {ac_data.get('buffer_size', 0)}."}
                else:
                    ac_diag = {"system": "Autonomous Controller", "code": "AC_NOT_RUNNING", "status": "stopped",
                               "message": "Controller is stopped.", "fix": "Enable via Crystal Intelligence controls or set ENABLE_AUTONOMOUS=true."}
        except Exception:
            pass

        try:
            se_raw = await _redis.get("crystal_system_status:subconscious_engine")
            if se_raw:
                se_data = json.loads(se_raw)
                if se_data.get("running"):
                    se_diag = {"system": "Subconscious Engine", "code": "HEALTHY", "status": "active",
                               "message": f"Running. Jobs completed: {se_data.get('jobs_completed', 0)}."}
                elif se_data.get("enabled"):
                    se_diag = {"system": "Subconscious Engine", "code": "SE_NOT_RUNNING", "status": "degraded",
                               "message": "Enabled but not running.", "fix": "Check bridge logs for startup errors."}
                else:
                    se_diag = {"system": "Subconscious Engine", "code": "SE_DISABLED", "status": "disabled",
                               "message": "Explicitly disabled.", "fix": "Set ENABLE_SUBCONSCIOUS=true and restart bridge."}
        except Exception:
            pass

    systems["autonomous_controller"] = ac_diag
    systems["subconscious_engine"] = se_diag

    # Blue Harvester from heartbeats
    bh_match = {k: v for k, v in hb_by_node.items() if "mac" in k.lower() or "blue" in k.lower()}
    if bh_match:
        _nid, _bh = next(iter(bh_match.items()))
        if _bh.get("healthy"):
            systems["blue_harvester"] = {"system": "Blue Harvester", "code": "HEALTHY", "status": "active",
                                         "message": "Mac node reporting heartbeats."}
        else:
            systems["blue_harvester"] = {"system": "Blue Harvester", "code": "BH_STALE", "status": "stale",
                                         "message": "Mac heartbeat exists but > 60 min old.", "fix": "Run blue_harvester.py on Mac."}
    else:
        systems["blue_harvester"] = {"system": "Blue Harvester", "code": "BH_OFFLINE", "status": "offline",
                                     "message": "No heartbeat from Mac node.", "fix": "Run: python3 backend/blue_harvester.py on Mac."}

    return {"status": "ok", "systems": systems}


# ═══════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat() if v else None
    return d


def _safe_json(s: Optional[str]):
    """Parse string as JSON or return as-is wrapped in a dict."""
    if not s:
        return None
    try:
        return json.dumps(json.loads(s))
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"raw": s})


# ═══════════════════════════════════════════════════════════════════
# SOVEREIGN IDE — Plan retrieval, diffs, accept/revoke, audit trail
# ═══════════════════════════════════════════════════════════════════

@router.get("/plan/{plan_id}")
async def get_plan(plan_id: str, request: Request):
    """Retrieve a plan artifact from R2 storage."""
    try:
        from app.services.r2_storage import download_bytes_async
        content = await download_bytes_async(key=f"cli-plans/{plan_id}.md")
        if not content:
            raise HTTPException(status_code=404, detail="Plan not found")
        return {"plan_id": plan_id, "content": content.decode("utf-8", errors="replace")}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Plan retrieval failed for %s: %s", plan_id, e)
        raise HTTPException(status_code=500, detail="Failed to retrieve plan")


@router.get("/plan/{plan_id}/diffs")
async def get_plan_diffs(plan_id: str, request: Request):
    """Extract per-file diffs from a plan artifact."""
    try:
        from app.services.r2_storage import download_bytes_async
        content = await download_bytes_async(key=f"cli-plans/{plan_id}.md")
        if not content:
            raise HTTPException(status_code=404, detail="Plan not found")

        import re as _re
        text = content.decode("utf-8", errors="replace")
        diffs = []
        pattern = _re.compile(
            r"###\s+(.+?)\s+\((CREATE|MODIFY|DELETE)\)\s*\n"
            r"(.*?)(?=\n###\s|\n## |\Z)",
            _re.DOTALL | _re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            file_path = m.group(1).strip().strip("`")
            action = m.group(2).lower()
            body = m.group(3).strip()
            code_blocks = _re.findall(r"```[a-z]*\n(.*?)```", body, _re.DOTALL)
            unified = "\n".join(code_blocks) if code_blocks else body
            diffs.append({
                "file_path": file_path,
                "action": action,
                "content": unified,
                "status": "proposed",
            })
        return {"plan_id": plan_id, "diffs": diffs}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Plan diffs extraction failed for %s: %s", plan_id, e)
        raise HTTPException(status_code=500, detail="Failed to extract diffs")


class PlanDecisionBody(BaseModel):
    file_path: Optional[str] = None


@router.post("/plan/{plan_id}/accept")
async def accept_plan(plan_id: str, body: PlanDecisionBody, request: Request, user: dict = Depends(require_admin)):
    """Accept a plan (all files or a specific file)."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    decided_by = (user or {}).get("username", "admin")
    async with pool.acquire() as conn:
        if body.file_path:
            await conn.execute("""
                INSERT INTO cli_tool_calls (plan_id, tool_name, tool_input, tool_output, status, decision, decided_by, decided_at)
                VALUES ($1, 'accept_file', $2::jsonb, '{"accepted": true}'::jsonb, 'completed', 'accepted', $3, NOW())
            """, plan_id, json.dumps({"file_path": body.file_path}), decided_by)
        else:
            await conn.execute("""
                INSERT INTO cli_tool_calls (plan_id, tool_name, tool_input, tool_output, status, decision, decided_by, decided_at)
                VALUES ($1, 'accept_plan', '{}'::jsonb, '{"accepted": true}'::jsonb, 'completed', 'accepted', $2, NOW())
            """, plan_id, decided_by)
    return {"status": "accepted", "plan_id": plan_id, "file_path": body.file_path}


@router.post("/plan/{plan_id}/revoke")
async def revoke_plan(plan_id: str, body: PlanDecisionBody, request: Request, user: dict = Depends(require_admin)):
    """Revoke a plan (all files or a specific file)."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    decided_by = (user or {}).get("username", "admin")
    async with pool.acquire() as conn:
        tool = "revoke_file" if body.file_path else "revoke_plan"
        inp = json.dumps({"file_path": body.file_path}) if body.file_path else "{}"
        await conn.execute("""
            INSERT INTO cli_tool_calls (plan_id, tool_name, tool_input, tool_output, status, decision, decided_by, decided_at)
            VALUES ($1, $2, $3::jsonb, '{"revoked": true}'::jsonb, 'completed', 'revoked', $4, NOW())
        """, plan_id, tool, inp, decided_by)
    return {"status": "revoked", "plan_id": plan_id, "file_path": body.file_path}


@router.get("/audit-trail/{plan_id}")
async def get_audit_trail(plan_id: str, request: Request):
    """Get the full audit trail for a plan."""
    pool = _pool(request)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, plan_id, tool_name, tool_input, tool_output,
                   status, duration_ms, decision, decided_by, decided_at, created_at
            FROM cli_tool_calls
            WHERE plan_id = $1
            ORDER BY created_at ASC
        """, plan_id)
        calls = []
        for r in rows:
            calls.append({
                "id": str(r["id"]),
                "plan_id": r["plan_id"],
                "tool_name": r["tool_name"],
                "tool_input": json.loads(r["tool_input"]) if r["tool_input"] else None,
                "tool_output": json.loads(r["tool_output"]) if r["tool_output"] else None,
                "status": r["status"],
                "duration_ms": r["duration_ms"],
                "decision": r["decision"],
                "decided_by": r["decided_by"],
                "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
    return {"plan_id": plan_id, "tool_calls": calls}
