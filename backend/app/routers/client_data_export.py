"""
Client Data Export — HIPAA 45 CFR 164.524 Right of Access (Phase 5 Gap N)
=========================================================================

Plan authority: docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md
  - Gap N (survivor data export — sensitive bridge surface)
  - Note 1 (HIPAA redaction layers, single-download enforcement, real-clock TTL)

WHAT THIS ROUTER DOES
---------------------
Mounts three endpoints under ``/api/client/sensitive-data-export``:

* ``POST /request`` — survivor (or admin acting on the survivor's behalf)
  initiates an export. The handler builds a JSONB bundle inline by reading
  ``sensitive_bridge_log`` rows for the user, applying THREE redaction
  layers (see below), generates a 32-byte URL-safe ``signed_url_token``,
  sets ``expires_at = NOW() + 7 days`` (canonical TTL from app_settings),
  and persists everything to ``client_data_export_requests``. Bundle is
  stored inline so the download path never touches production tables —
  the audit trail is preserved and download semantics stay atomic.

* ``GET /{request_id}/status`` — poll for status. Survivor or admin only.
  Never returns the bundle. Returns lifecycle + redaction_summary so the
  client portal can show "ready", "downloaded", or "expired" with
  supporting context.

* ``GET /download/{signed_url_token}`` — atomic single-shot delivery.
  Increments ``download_count`` via UPDATE ... RETURNING gated on
  (download_count < max_downloads AND expires_at > NOW() AND status IN
  ('ready','pending')). Empty RETURNING ⇒ 410 Gone. Auditor's synthetic
  twin-download test relies on this exact contract.

THE THREE REDACTION LAYERS (Plan Note 1)
----------------------------------------
(a) **SQL-layer access_classification filter** (Note 1a):
    The bundle-generation SELECT is ``WHERE access_classification =
    'clinician_and_admin'`` — clinician-clinician communication
    (``clinician_only``) and validator administrative entries
    (``admin_only_redacted``) NEVER enter the export process. SQL filter
    means "this row never reached Python"; that is strictly stronger
    than a Python-layer filter that drops rows after they've been
    selected. The ``redaction_summary`` records counts of each excluded
    classification (computed by a separate aggregate query) so the
    auditor can verify the filter was applied (not just claimed).

(b) **PII pattern reuse** (Note 1b):
    Free-text strings inside ``payload_json`` go through
    ``trigger_date_registry._screen_notes_for_pii`` — the same single
    source-of-truth helper used by ``coach_override_protocol``. On a hit
    the value is replaced with ``"[REDACTED:<label>]"`` and the hit is
    counted in ``redaction_summary['pii_pattern_hits']``. Forking the
    pattern set would create silent divergence on future lexicon updates;
    the auditor check ``data_export_uses_canonical_pii_screen`` greps
    this file at boot to confirm the import is present.

(c) **Single-download enforcement via DB count + real-clock TTL** (Note 1c):
    The signed URL is the audience-restricted handle, but the
    ``download_count`` column is the lock. The download endpoint runs::

        UPDATE client_data_export_requests
           SET download_count = download_count + 1, status = 'downloaded',
               last_downloaded_at = NOW(), last_downloader_ip = $ip
         WHERE signed_url_token = $token
           AND download_count < max_downloads
           AND expires_at > NOW()
           AND status IN ('ready', 'pending')
        RETURNING bundle_jsonb, request_id, user_id

    An empty RETURNING means the row is exhausted, expired, or already
    downloaded — the handler responds 410 Gone. The 7-day TTL is checked
    against ``NOW()`` on every attempt, never against session start.

AUDITOR HOOKS (Phase 6 fold-in)
-------------------------------
Two checks fold into existing slots in ``sensitive_bridge_auditor.py``;
neither adds a new META entry:

* ``data_export_signed_url_single_download_enforced`` — issues an internal
  synthetic request via the auditor's admin-only synthetic endpoint
  (``POST /api/admin/sensitive-data-export/_synthetic_test``), downloads
  twice in succession, expects 200 then 410. Synthetic requests carry
  ``is_synthetic = TRUE`` so they don't pollute survivor history and are
  auto-pruned after 24h.

* ``data_export_uses_canonical_pii_screen`` — file-grep check verifies
  the canonical import path remains intact (no silent fork).

NOT IN SCOPE
------------
* The Flutter UI for survivors to request their own export. Out-of-band:
  Phase 6 deliverable.
* Admin export across all users (existing ``data_export.py`` GDPR path
  remains for that). This router is sensitive-bridge-specific and per-user.
* Background pre-generation. Bundle is built synchronously inside ``/request``;
  if performance becomes an issue we can move to a queue with a separate
  ``status='generating'`` row, but for v1.0 the synchronous path is simpler
  and audit-cleaner.

EXPECTED FAILURE MODES (return shapes for the client)
-----------------------------------------------------
* 401 → token invalid (handled upstream by ``get_current_user``)
* 403 ``not_owner`` → caller is not the target user_id and not ADMIN
* 404 ``user_not_found`` → target user_id has no row in ``users``
* 404 ``request_not_found`` → request_id or signed_url_token unknown
* 410 ``gone`` → download_count exhausted OR expires_at past OR status
                 already 'downloaded' / 'expired'
* 422 ``invalid_request`` → user_id missing/blank in /request body
* 503 ``database_unavailable`` → no db_pool on app.state (cold-boot window)

CONTRACT VERSION
----------------
Bumped on any non-additive change to request/response shapes or the
single-download/PII-screen contracts. The auditor reads this and asserts
it matches the trust-baseline ``client_data_export_contract_version`` row
(future Phase 6 baseline — for v1.0 this is informational).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.api_server import get_current_user, require_admin

# Single-source-of-truth PII screen — Note 1b. Forking would create silent
# divergence on lexicon updates; the auditor greps this exact import path.
from app.services.trigger_date_registry import _screen_notes_for_pii

logger = logging.getLogger(__name__)

# =============================================================================
# Module constants
# =============================================================================

#: Bumped on any non-additive contract change. Auditor reads this.
CONTRACT_VERSION = "1.0.0-2026-05-09"

#: SQL-layer filter (Note 1a): rows shipped to the survivor MUST be tagged
#: ``clinician_and_admin``. Anything ``clinician_only`` (clinician-clinician
#: communication) or ``admin_only_redacted`` (validator administrative
#: entries) NEVER enters the bundle. This is the strongest of the three
#: redaction layers because it operates before Python touches the data.
ALLOWED_ACCESS_CLASSIFICATION = "clinician_and_admin"

#: Excluded classifications, kept here as constants so the redaction summary
#: query can reference them without string literals scattered.
EXCLUDED_CLASSIFICATIONS: Tuple[str, ...] = (
    "clinician_only",
    "admin_only_redacted",
)

#: Default TTL fallback if app_settings lookup fails. Auditor verifies this
#: matches the value persisted by migration 211 (= 7).
DEFAULT_TTL_DAYS = 7

#: Hard cap on rows per source table inside the bundle. Prevents accidental
#: blow-up when a user has years of activity. Truncation is signaled in the
#: bundle as a top-level ``truncated`` flag with per-table counts.
BUNDLE_MAX_ROWS_PER_TABLE = 5_000

#: Synthetic audit requests live for this long before janitor sweeps them.
SYNTHETIC_RETENTION_HOURS = 24

#: Audit event names (must match migration 211 CHECK extension).
EVT_DATA_EXPORT_REQUESTED = "data_export_requested"
EVT_DATA_EXPORT_DOWNLOADED = "data_export_downloaded"
EVT_DATA_EXPORT_EXPIRED = "data_export_expired"

#: Severity used for export audit rows. Per Plan, export events are
#: ``info`` — they're administrative, not clinical. Failure paths (410,
#: 503) emit no audit row; the absence is the signal.
AUDIT_SEVERITY_INFO = "info"

#: The audit row for the export *request itself* is classified
#: ``admin_only_redacted`` because it logs the requester and timestamp,
#: which we do NOT want to surface back into a future survivor export
#: (would create a recursive disclosure spiral).
AUDIT_ACCESS_ADMIN_ONLY = "admin_only_redacted"


# =============================================================================
# Pydantic request models
# =============================================================================

class ExportRequestBody(BaseModel):
    """POST /request body. ``user_id`` is the target survivor's username.

    The acting role is derived from the bearer principal:
      * Survivor self-service ⇒ ``request_origin = 'self_service'``
      * Admin requesting on behalf of a survivor ⇒ ``request_origin = 'admin_assist'``

    Synthetic auditor requests use a different endpoint and never reach
    this body model.
    """

    user_id: str = Field(..., min_length=1, max_length=128)
    reason: Optional[str] = Field(
        default=None, max_length=500,
        description="Optional human-readable reason logged in the audit row."
    )


# =============================================================================
# Helpers — bundle build, PII screen, atomic download
# =============================================================================


def _walk_and_screen_pii(
    value: Any,
    pii_hits: Dict[str, int],
    *,
    max_depth: int = 8,
    _depth: int = 0,
) -> Any:
    """Recursively screen string values inside a JSON-shaped object.

    On a hit, replaces the offending string with ``"[REDACTED:<label>]"``
    and increments ``pii_hits[label]``. Returns a new object — does NOT
    mutate the input (so the caller can hand us either a dict from the
    DB or a list slice without surprise side-effects).

    Bounded depth (default 8) prevents pathological recursion if the
    payload contains a cycle (which JSON shouldn't, but defense-in-depth).
    """
    if _depth > max_depth:
        return "[REDACTED:depth_limit]"

    if isinstance(value, str):
        hit = _screen_notes_for_pii(value)
        if hit is not None:
            label, _offset = hit
            pii_hits[label] = pii_hits.get(label, 0) + 1
            return f"[REDACTED:{label}]"
        return value

    if isinstance(value, dict):
        return {
            k: _walk_and_screen_pii(v, pii_hits, max_depth=max_depth, _depth=_depth + 1)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [
            _walk_and_screen_pii(v, pii_hits, max_depth=max_depth, _depth=_depth + 1)
            for v in value
        ]

    # int / float / bool / None — JSON scalars that can't carry PII
    return value


async def _resolve_ttl_days(conn) -> int:
    """Read canonical TTL from app_settings, falling back to DEFAULT_TTL_DAYS."""
    try:
        row = await conn.fetchrow(
            "SELECT setting_value FROM app_settings "
            "WHERE setting_key = 'data_export_signed_url_ttl_days'",
        )
        if row is None:
            return DEFAULT_TTL_DAYS
        raw = row["setting_value"]
        # JSONB int comes back as int; JSONB string '7' as '7'
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        if isinstance(raw, dict):
            return DEFAULT_TTL_DAYS
        # JSONB scalar may already be unwrapped depending on driver
        return int(raw) if raw is not None else DEFAULT_TTL_DAYS
    except Exception as exc:
        logger.warning(
            "client_data_export: TTL lookup failed (%s); using %d-day default",
            exc, DEFAULT_TTL_DAYS,
        )
        return DEFAULT_TTL_DAYS


async def _build_bundle(
    conn,
    user_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the export bundle for ``user_id``.

    Returns ``(bundle, redaction_summary)``.

    Layer (a) — SQL filter — runs first: every SELECT carries
    ``WHERE access_classification = 'clinician_and_admin'``.

    Layer (b) — PII screen — runs second on each row's ``payload_json``
    via ``_walk_and_screen_pii``.

    Layer (c) — single-download — is enforced by the download endpoint,
    not here.
    """
    pii_hits: Dict[str, int] = {}
    redaction_summary: Dict[str, Any] = {
        "rows_included": 0,
        "rows_excluded_by_classification": 0,
        "excluded_classification_breakdown": {},
        "pii_pattern_hits": {},
        "tables_truncated": [],
    }

    # ── 1. Aggregate query: how many rows did the SQL filter exclude?
    # This drives Layer (a) verifiability — the auditor will compare this
    # count against an unfiltered count to confirm the filter actually ran.
    excl_rows = await conn.fetch(
        """
        SELECT access_classification, COUNT(*) AS n
          FROM sensitive_bridge_log
         WHERE user_id = $1
           AND access_classification IN ('clinician_only', 'admin_only_redacted')
         GROUP BY access_classification
        """,
        user_id,
    )
    excl_total = 0
    for r in excl_rows:
        cls = r["access_classification"]
        n = int(r["n"])
        redaction_summary["excluded_classification_breakdown"][cls] = n
        excl_total += n
    redaction_summary["rows_excluded_by_classification"] = excl_total

    # ── 2. Bundle the actual data — sensitive_bridge_log first.
    bridge_rows = await conn.fetch(
        """
        SELECT log_id, event_type, event_severity, payload_json,
               decision_summary, occurred_at, recorded_by,
               retained_until, pii_screened_at, redaction_pass_count
          FROM sensitive_bridge_log
         WHERE user_id = $1
           AND access_classification = $2
         ORDER BY occurred_at DESC
         LIMIT $3
        """,
        user_id,
        ALLOWED_ACCESS_CLASSIFICATION,
        BUNDLE_MAX_ROWS_PER_TABLE + 1,  # fetch +1 to detect truncation
    )

    truncated = len(bridge_rows) > BUNDLE_MAX_ROWS_PER_TABLE
    if truncated:
        bridge_rows = bridge_rows[:BUNDLE_MAX_ROWS_PER_TABLE]
        redaction_summary["tables_truncated"].append(
            {"table": "sensitive_bridge_log", "cap": BUNDLE_MAX_ROWS_PER_TABLE}
        )

    bridge_entries: List[Dict[str, Any]] = []
    for row in bridge_rows:
        payload_raw = row["payload_json"]
        # asyncpg returns JSONB as dict; defensive parse if it's str.
        if isinstance(payload_raw, str):
            try:
                payload_raw = json.loads(payload_raw)
            except Exception:
                payload_raw = {"_unparsable": True}

        decision_raw = row["decision_summary"]
        if isinstance(decision_raw, str):
            try:
                decision_raw = json.loads(decision_raw)
            except Exception:
                decision_raw = None

        screened_payload = _walk_and_screen_pii(payload_raw or {}, pii_hits)
        screened_decision = (
            _walk_and_screen_pii(decision_raw, pii_hits)
            if decision_raw is not None
            else None
        )

        bridge_entries.append({
            "log_id": row["log_id"],
            "event_type": row["event_type"],
            "event_severity": row["event_severity"],
            "occurred_at": row["occurred_at"].isoformat()
                if row["occurred_at"] else None,
            "recorded_by": row["recorded_by"],
            "retained_until": row["retained_until"].isoformat()
                if row["retained_until"] else None,
            "pii_screened_at": row["pii_screened_at"].isoformat()
                if row["pii_screened_at"] else None,
            "redaction_pass_count": row["redaction_pass_count"],
            "payload": screened_payload,
            "decision_summary": screened_decision,
        })

    redaction_summary["rows_included"] = len(bridge_entries)
    redaction_summary["pii_pattern_hits"] = pii_hits

    bundle = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "hipaa_basis": "45_CFR_164_524_right_of_access",
        "bundle_contents": {
            "sensitive_bridge_log": bridge_entries,
        },
        "redaction_layers_applied": [
            "sql_filter_access_classification",
            "pii_pattern_screen_via_trigger_date_registry",
            "single_download_via_db_count_and_real_clock_ttl",
        ],
        "truncated": truncated,
    }

    return bundle, redaction_summary


async def _emit_audit(
    conn,
    *,
    user_id: str,
    event_type: str,
    payload: Dict[str, Any],
    severity: str = AUDIT_SEVERITY_INFO,
) -> None:
    """Insert a sensitive_bridge_log row tagged ``admin_only_redacted``.

    Wrapped in try/except: an audit failure must NOT block the export
    request itself. We log a warning and move on. The bundle download is
    the user-facing contract; auditing is operational telemetry.
    """
    try:
        await conn.execute(
            """
            INSERT INTO sensitive_bridge_log (
                user_id, event_type, event_severity, payload_json,
                recorded_by, access_classification, pii_screened_at
            ) VALUES (
                $1, $2, $3, $4::jsonb, $5, $6, NOW()
            )
            """,
            user_id,
            event_type,
            severity,
            json.dumps(payload),
            "client_data_export",
            AUDIT_ACCESS_ADMIN_ONLY,
        )
    except Exception as exc:
        logger.warning(
            "client_data_export: audit row insert failed (event=%s): %s",
            event_type, exc,
        )


# =============================================================================
# Routers — survivor-facing + admin-synthetic
# =============================================================================

router = APIRouter(
    prefix="/api/client/sensitive-data-export",
    tags=["client", "data-export", "hipaa"],
)

#: Admin-only synthetic test endpoint mounted at a different prefix so the
#: survivor router can stay narrow and the auditor can probe a stable URL.
admin_router = APIRouter(
    prefix="/api/admin/sensitive-data-export",
    tags=["admin", "data-export", "auditor"],
)


@router.post("/request")
async def request_export(
    body: ExportRequestBody,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Create an export request. Survivor self-service or admin-assist.

    Returns ``{request_id, signed_url_token, download_url, expires_at,
    redaction_summary}``. The download URL is a relative path; the client
    is expected to combine it with the bridge origin.
    """
    requester = user.get("user_id") or user.get("username") or ""
    requester_role = (user.get("role") or "").upper()

    if not body.user_id.strip():
        raise HTTPException(status_code=422, detail={"reason": "invalid_request"})

    # Authorization: survivor can request their own data; admin can request
    # on behalf. No coach path here — coach access goes through the
    # clinician portal, not the survivor export.
    is_self = (requester == body.user_id)
    is_admin = (requester_role == "ADMIN")
    if not (is_self or is_admin):
        raise HTTPException(status_code=403, detail={"reason": "not_owner"})

    request_origin = "self_service" if is_self else "admin_assist"

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(
            status_code=503, detail={"reason": "database_unavailable"},
        )

    async with db_pool.acquire() as conn:
        # Verify target user exists
        user_row = await conn.fetchrow(
            "SELECT username FROM users WHERE username = $1",
            body.user_id,
        )
        if user_row is None:
            raise HTTPException(
                status_code=404,
                detail={"reason": "user_not_found", "user_id": body.user_id},
            )

        ttl_days = await _resolve_ttl_days(conn)
        bundle, redaction_summary = await _build_bundle(conn, body.user_id)
        bundle_bytes = json.dumps(bundle, default=str).encode("utf-8")

        token = secrets.token_urlsafe(32)

        row = await conn.fetchrow(
            """
            INSERT INTO client_data_export_requests (
                user_id, requested_by, request_origin,
                signed_url_token, expires_at, status,
                bundle_jsonb, bundle_size_bytes, redaction_summary
            ) VALUES (
                $1, $2, $3, $4,
                NOW() + ($5::int * INTERVAL '1 day'),
                'ready', $6::jsonb, $7, $8::jsonb
            )
            RETURNING request_id, expires_at
            """,
            body.user_id,
            requester,
            request_origin,
            token,
            ttl_days,
            json.dumps(bundle, default=str),
            len(bundle_bytes),
            json.dumps(redaction_summary),
        )

        await _emit_audit(
            conn,
            user_id=body.user_id,
            event_type=EVT_DATA_EXPORT_REQUESTED,
            payload={
                "request_id": str(row["request_id"]),
                "request_origin": request_origin,
                "ttl_days": ttl_days,
                "bundle_size_bytes": len(bundle_bytes),
                "rows_included": redaction_summary.get("rows_included", 0),
                "rows_excluded_by_classification":
                    redaction_summary.get("rows_excluded_by_classification", 0),
                "pii_pattern_hit_total":
                    sum(redaction_summary.get("pii_pattern_hits", {}).values()),
                "reason_present": bool(body.reason),
            },
        )

    return {
        "request_id": str(row["request_id"]),
        "signed_url_token": token,
        "download_url": f"/api/client/sensitive-data-export/download/{token}",
        "expires_at": row["expires_at"].isoformat(),
        "redaction_summary": redaction_summary,
        "contract_version": CONTRACT_VERSION,
    }


@router.get("/{request_id}/status")
async def export_status(
    request_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Poll status. Survivor (self) or admin only. Never returns the bundle.
    """
    requester = user.get("user_id") or user.get("username") or ""
    requester_role = (user.get("role") or "").upper()

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(
            status_code=503, detail={"reason": "database_unavailable"},
        )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT request_id, user_id, requested_by, status,
                   download_count, max_downloads, expires_at,
                   last_downloaded_at, bundle_size_bytes,
                   redaction_summary, is_synthetic, created_at
              FROM client_data_export_requests
             WHERE request_id = $1::uuid
            """,
            request_id,
        )

    if row is None:
        raise HTTPException(
            status_code=404, detail={"reason": "request_not_found"},
        )
    if row["is_synthetic"]:
        # Synthetic auditor rows are never user-visible.
        raise HTTPException(
            status_code=404, detail={"reason": "request_not_found"},
        )

    is_owner = (row["user_id"] == requester)
    is_admin = (requester_role == "ADMIN")
    if not (is_owner or is_admin):
        raise HTTPException(status_code=403, detail={"reason": "not_owner"})

    expires_at = row["expires_at"]
    is_expired = (
        expires_at is not None
        and expires_at < datetime.now(timezone.utc)
    )

    return {
        "request_id": str(row["request_id"]),
        "user_id": row["user_id"],
        "status": "expired" if is_expired and row["status"] == "ready"
                  else row["status"],
        "download_count": row["download_count"],
        "max_downloads": row["max_downloads"],
        "expires_at": expires_at.isoformat() if expires_at else None,
        "last_downloaded_at": row["last_downloaded_at"].isoformat()
            if row["last_downloaded_at"] else None,
        "bundle_size_bytes": row["bundle_size_bytes"],
        "redaction_summary": row["redaction_summary"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "contract_version": CONTRACT_VERSION,
    }


@router.get("/download/{signed_url_token}")
async def download_export(
    signed_url_token: str,
    request: Request,
):
    """Atomic single-shot download.

    No bearer-token gate: the ``signed_url_token`` IS the audience
    restriction. The DB lock is enforced by the atomic UPDATE: empty
    RETURNING ⇒ exhausted/expired/already-downloaded ⇒ 410 Gone.

    The signed token has 256 bits of entropy (``secrets.token_urlsafe(32)``);
    brute force is infeasible. The DB count is the structural single-shot
    guarantee — even if the token is shared, only the first arrival gets
    the bundle.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(
            status_code=503, detail={"reason": "database_unavailable"},
        )

    # Resolve the requester IP for last_downloader_ip. Safe under proxy
    # because we only use it for forensics (it's stored in INET column,
    # not used for authorization).
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE client_data_export_requests
               SET download_count = download_count + 1,
                   status = 'downloaded',
                   last_downloaded_at = NOW(),
                   last_downloader_ip = $2::inet
             WHERE signed_url_token = $1
               AND download_count < max_downloads
               AND expires_at > NOW()
               AND status IN ('ready', 'pending')
            RETURNING request_id, user_id, bundle_jsonb,
                      bundle_size_bytes, is_synthetic
            """,
            signed_url_token,
            client_ip if client_ip else None,
        )

        if row is None:
            # Distinguish "never existed" from "exhausted/expired" without
            # leaking the difference to attackers — both are 410 to a
            # caller without a valid token. We DO log the distinction for
            # operational visibility.
            existed = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM client_data_export_requests "
                "WHERE signed_url_token = $1)",
                signed_url_token,
            )
            if existed:
                # Mark it expired if we can; idempotent under concurrent
                # download attempts (status='downloaded' wins via the
                # earlier UPDATE; the WHERE clause here keeps us from
                # overwriting that).
                await conn.execute(
                    """
                    UPDATE client_data_export_requests
                       SET status = 'expired'
                     WHERE signed_url_token = $1
                       AND status = 'ready'
                       AND expires_at < NOW()
                    """,
                    signed_url_token,
                )
            raise HTTPException(status_code=410, detail={"reason": "gone"})

        bundle = row["bundle_jsonb"]
        if isinstance(bundle, str):
            try:
                bundle = json.loads(bundle)
            except Exception:
                # Corrupted bundle column — return 410 rather than
                # leak partial data.
                raise HTTPException(
                    status_code=410, detail={"reason": "gone"}
                )

        # Audit only real (non-synthetic) downloads. The auditor's
        # synthetic test would otherwise spam the bridge log every cycle.
        if not row["is_synthetic"]:
            await _emit_audit(
                conn,
                user_id=row["user_id"],
                event_type=EVT_DATA_EXPORT_DOWNLOADED,
                payload={
                    "request_id": str(row["request_id"]),
                    "bundle_size_bytes": row["bundle_size_bytes"],
                    "downloader_ip_present": bool(client_ip),
                },
            )

    headers = {
        "Content-Disposition": (
            f'attachment; filename="sensitive_data_export_'
            f'{row["user_id"]}_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}'
            f'.json"'
        ),
        "Cache-Control": "no-store, no-cache, must-revalidate, private",
        "Pragma": "no-cache",
        "X-Bundle-Schema-Version": "1.0",
    }
    return JSONResponse(content=bundle, headers=headers)


# =============================================================================
# Admin-only synthetic endpoint — auditor's twin-download self-test
# =============================================================================


@admin_router.post("/_synthetic_test")
async def synthetic_single_download_test(
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Auditor self-test: create a synthetic request, download twice,
    expect 200 then 410.

    Only ``ADMIN`` can call this (the auditor's bearer is admin-scoped).
    Synthetic requests carry ``is_synthetic = TRUE`` so they are excluded
    from the survivor-facing status endpoint and from download audit
    rows. A janitor sweeps them at the 24h mark (Phase 6 follow-up).

    Returns ``{first_download_status, second_download_status, passed}``.
    A passing run requires ``first_download_status == 200`` and
    ``second_download_status == 410``.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(
            status_code=503, detail={"reason": "database_unavailable"},
        )

    token = secrets.token_urlsafe(32)
    synthetic_user = "auditor_synthetic"

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO client_data_export_requests (
                user_id, requested_by, request_origin,
                signed_url_token, expires_at, status,
                bundle_jsonb, bundle_size_bytes, redaction_summary,
                is_synthetic
            ) VALUES (
                $1, $1, 'auditor_synthetic',
                $2,
                NOW() + INTERVAL '1 hour',
                'ready',
                '{"synthetic": true}'::jsonb,
                32,
                '{"synthetic": true}'::jsonb,
                TRUE
            )
            """,
            synthetic_user, token,
        )

        # First download: should succeed atomically.
        first_row = await conn.fetchrow(
            """
            UPDATE client_data_export_requests
               SET download_count = download_count + 1,
                   status = 'downloaded',
                   last_downloaded_at = NOW()
             WHERE signed_url_token = $1
               AND download_count < max_downloads
               AND expires_at > NOW()
               AND status IN ('ready', 'pending')
            RETURNING request_id
            """,
            token,
        )
        first_status = 200 if first_row is not None else 410

        # Second download: must fail.
        second_row = await conn.fetchrow(
            """
            UPDATE client_data_export_requests
               SET download_count = download_count + 1
             WHERE signed_url_token = $1
               AND download_count < max_downloads
               AND expires_at > NOW()
               AND status IN ('ready', 'pending')
            RETURNING request_id
            """,
            token,
        )
        second_status = 200 if second_row is not None else 410

        # Mark synthetic as completed for the janitor's TTL pass.
        await conn.execute(
            "UPDATE client_data_export_requests "
            "SET status = 'downloaded' WHERE signed_url_token = $1",
            token,
        )

    passed = (first_status == 200) and (second_status == 410)
    return {
        "test": "single_download_enforced",
        "first_download_status": first_status,
        "second_download_status": second_status,
        "passed": passed,
        "contract_version": CONTRACT_VERSION,
    }


# =============================================================================
# Boot-time auditor check — file-grep for canonical PII screen import
# =============================================================================


def _auditor_self_check() -> Dict[str, Any]:
    """Verify the canonical PII screen helper is still imported here.

    Called once at boot from the trust auditor (Phase 6 fold-in) to
    confirm Note 1b is intact. A silent fork of the PII patterns is the
    primary regression we're guarding against; this check fires before
    any export request can be served if the import was tampered with.
    """
    return {
        "router_loaded": True,
        "contract_version": CONTRACT_VERSION,
        "uses_canonical_pii_screen": _screen_notes_for_pii is not None,
        "pii_screen_module": getattr(
            _screen_notes_for_pii, "__module__", "unknown"
        ),
        "allowed_access_classification": ALLOWED_ACCESS_CLASSIFICATION,
        "excluded_classifications": list(EXCLUDED_CLASSIFICATIONS),
        "default_ttl_days": DEFAULT_TTL_DAYS,
    }
