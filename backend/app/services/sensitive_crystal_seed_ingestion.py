"""
Sensitive Crystal Seed Ingestion (Phase 5 Note 2)
=================================================

Plan authority: docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md
  - Risk #1 (crystal corpus quality is the highest-leverage risk)
  - Gap 6 (requires_embodiment_phase mandatory tagging)
  - Note 2 (engineer-authored content shipped as scaffolding, not corpus)

WHAT THIS MODULE DOES
---------------------
Bulk-loads engineer-authored "starter" crystal scaffolds from JSON files
under ``backend/data/sensitive_crystal_seeds/`` into
``nate_intelligence_crystals``, with three blocking contracts that mirror
Plan Note 2:

(a) **NateResponseValidator gate** (Note 2a):
    Every crystal text is run through ``NateResponseValidator.validate``
    BEFORE storage. Any warning blocks the crystal — the JSON has to be
    revised by the clinician before re-ingest. We never let a validator-
    flagged string into the crystal table even with the gating status,
    because flipping ``crystal_status='production'`` at clinician review
    time would then make a flagged crystal recallable. The gate must be
    upstream of the storage call.

(b) **requires_embodiment_phase mandatory** (Note 2b):
    For crystals tagged with any of the 5 sensitive domains read from
    ``app_settings.sensitive_crystal_seed_domains`` (currently
    ``intimacy_clinical``, ``sexual_trauma``, ``trafficking_trauma``,
    ``embodiment_repair``, ``child_trafficking``), the per-crystal
    ``requires_embodiment_phase`` field MUST be a non-null boolean. Missing
    or null tag fails ingestion with ``crystal_seed_embodiment_block``.

(c) **awaiting_clinician_authoring default** (Note 2c):
    All ingested seeds are stored with ``crystal_status =
    'awaiting_clinician_authoring'``. ``crystal_recall_bridge`` filters
    these out via ``_PRODUCTION_STATUS_FILTER`` so engineer-authored
    placeholders NEVER surface in production recall. Clinician review is
    the gate to recallability — they must explicitly UPDATE the row to
    ``crystal_status='production'`` after vetting the text.

JSON SEED FORMAT
----------------
Each seed file is a JSON object::

    {
      "schema_version": "1.0",
      "source": "engineer_scaffold",
      "domain": "embodiment_repair",
      "default_requires_embodiment_phase": true,
      "ships_as": "awaiting_clinician_authoring",
      "crystals": [
        {
          "crystal_text": "<clinical scaffold text>",
          "confidence": 0.45,
          "scope": "global",
          "topics": ["embodiment", "repair", "polyvagal"],
          "requires_embodiment_phase": true,
          "metadata": {
            "needs_review": true,
            "review_notes": "Original scaffold; clinician should adjust phrasing."
          }
        }
      ]
    }

The ``default_requires_embodiment_phase`` at the top level is applied to
every crystal that doesn't carry its own per-crystal value.

AUDIT EVENTS (migration 211)
----------------------------
Every ingestion attempt emits one of three events into
``sensitive_bridge_log`` (``access_classification = 'admin_only_redacted'``):

* ``crystal_seed_ingested`` — crystal stored with awaiting_clinician_authoring
* ``crystal_seed_validator_block`` — NateResponseValidator returned warnings
* ``crystal_seed_embodiment_block`` — sensitive domain crystal missing tag

Audit row failures never propagate; ingestion continues even if the audit
infrastructure is down (the bridge log is operational telemetry, not a
correctness gate).

USAGE
-----
From an admin script or one-shot main.py boot:

    from app.services.sensitive_crystal_seed_ingestion import (
        SensitiveCrystalSeedIngestion,
    )

    ingester = SensitiveCrystalSeedIngestion(db_pool=app.state.db_pool)
    summary = await ingester.ingest_all()
    print(summary)

The ingester is idempotent: every crystal is keyed by SHA-256 content hash
of (domain + crystal_text) — re-running on the same seed JSON skips
already-ingested rows.

NOT IN SCOPE
------------
* Clinician review UI for promoting awaiting_clinician_authoring →
  production. Phase 6 deliverable.
* Vectorize indexing of seed crystals. Sensitive seeds are intentionally
  excluded from the vector index until clinician promotion (the recall
  filter would skip them anyway, but excluding upstream avoids polluting
  the embedding space).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Default seed directory. Override via constructor.
DEFAULT_SEED_DIR = Path("backend/data/sensitive_crystal_seeds")

#: Hard fallback if app_settings lookup fails. Mirrors migration 211.
FALLBACK_SENSITIVE_DOMAINS: Tuple[str, ...] = (
    "intimacy_clinical",
    "sexual_trauma",
    "trafficking_trauma",
    "embodiment_repair",
    "child_trafficking",
)

#: Crystal status set by every successful seed ingest. Recall filter in
#: ``crystal_recall_bridge._PRODUCTION_STATUS_FILTER`` excludes this.
SEED_STATUS = "awaiting_clinician_authoring"

#: Audit event taxonomy (migration 211 CHECK).
EVT_INGESTED = "crystal_seed_ingested"
EVT_VALIDATOR_BLOCK = "crystal_seed_validator_block"
EVT_EMBODIMENT_BLOCK = "crystal_seed_embodiment_block"

#: Audit access classification — seed audit rows are operational; never
#: surface back into a survivor data export.
AUDIT_ACCESS = "admin_only_redacted"


def _content_hash(domain: str, crystal_text: str) -> str:
    """Stable hash for idempotent re-ingestion."""
    return hashlib.sha256(
        f"{domain}\n{crystal_text}".encode("utf-8")
    ).hexdigest()


class SensitiveCrystalSeedIngestion:
    """Idempotent loader for engineer-authored sensitive crystal scaffolds.

    Public surface is intentionally narrow:
      * ``ingest_file(path)``        — load one JSON, return per-file summary
      * ``ingest_all(seed_dir=None)`` — load every ``*.json`` in the dir
      * ``_auditor_self_check()``     — auditor boot probe (no DB writes)
    """

    def __init__(
        self,
        db_pool=None,
        validator=None,
        seed_dir: Optional[Path] = None,
    ):
        self._db_pool = db_pool
        self._validator = validator  # late-bound; required for ingest_*
        self._seed_dir = Path(seed_dir) if seed_dir else DEFAULT_SEED_DIR

    # ------------------------------------------------------------------
    # Auditor probe — boot-time check that this module loaded with the
    # right validator wiring. Never touches the DB.
    # ------------------------------------------------------------------

    def _auditor_self_check(self) -> Dict[str, Any]:
        return {
            "module_loaded": True,
            "validator_attached": self._validator is not None,
            "seed_dir_present": self._seed_dir.is_dir(),
            "seed_dir": str(self._seed_dir),
            "fallback_sensitive_domains": list(FALLBACK_SENSITIVE_DOMAINS),
            "seed_status_default": SEED_STATUS,
        }

    # ------------------------------------------------------------------
    # Domain config — read from app_settings, fall back to constant
    # ------------------------------------------------------------------

    async def _load_sensitive_domains(self, conn) -> Tuple[str, ...]:
        try:
            row = await conn.fetchrow(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_crystal_seed_domains'",
            )
            if row is None:
                return FALLBACK_SENSITIVE_DOMAINS
            raw = row["setting_value"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, list):
                return tuple(str(d) for d in raw)
            return FALLBACK_SENSITIVE_DOMAINS
        except Exception as exc:
            logger.warning(
                "sensitive_crystal_seed: domain list lookup failed (%s); "
                "using fallback set of %d domains",
                exc, len(FALLBACK_SENSITIVE_DOMAINS),
            )
            return FALLBACK_SENSITIVE_DOMAINS

    # ------------------------------------------------------------------
    # Validator gate (Note 2a)
    # ------------------------------------------------------------------

    async def _validate_or_block(
        self,
        crystal_text: str,
    ) -> Tuple[bool, List[str]]:
        """Return (passed, warnings). Block on ANY warning."""
        if self._validator is None:
            # Hard-fail-closed: no validator means we cannot guarantee
            # corpus quality, so refuse to ingest. The auditor's
            # ``validator_attached`` self-check surfaces this earlier;
            # this path is the last-resort safety net.
            return False, ["validator_unavailable"]

        try:
            _text, warnings = await self._validator.validate(
                crystal_text,
                context={"source": "sensitive_crystal_seed_ingestion"},
            )
        except Exception as exc:
            logger.warning(
                "sensitive_crystal_seed: validator raised (%s); blocking",
                exc,
            )
            return False, [f"validator_exception:{type(exc).__name__}"]

        return (len(warnings) == 0), list(warnings)

    # ------------------------------------------------------------------
    # Embodiment-phase tag enforcement (Note 2b)
    # ------------------------------------------------------------------

    @staticmethod
    def _embodiment_tag_required(
        domain: str,
        sensitive_domains: Tuple[str, ...],
    ) -> bool:
        return domain in sensitive_domains

    @staticmethod
    def _resolve_embodiment_tag(
        crystal: Dict[str, Any],
        file_default: Optional[bool],
    ) -> Optional[bool]:
        """Per-crystal value wins; otherwise fall back to the file's default.
        Returns None if neither is set — the caller treats None as a block
        for sensitive-domain crystals.
        """
        if "requires_embodiment_phase" in crystal:
            value = crystal["requires_embodiment_phase"]
            if isinstance(value, bool):
                return value
            return None
        if isinstance(file_default, bool):
            return file_default
        return None

    # ------------------------------------------------------------------
    # Audit row writer — best-effort, never blocking
    # ------------------------------------------------------------------

    async def _emit_audit(
        self,
        conn,
        *,
        event_type: str,
        domain: str,
        content_hash: str,
        warnings: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            payload: Dict[str, Any] = {
                "domain": domain,
                "content_hash": content_hash,
                "warnings": warnings or [],
                "ingester": "sensitive_crystal_seed_ingestion",
            }
            if extra:
                payload.update(extra)
            await conn.execute(
                """
                INSERT INTO sensitive_bridge_log (
                    user_id, event_type, event_severity, payload_json,
                    recorded_by, access_classification, pii_screened_at
                ) VALUES (
                    'system', $1, 'info', $2::jsonb,
                    'sensitive_crystal_seed_ingestion', $3, NOW()
                )
                """,
                event_type,
                json.dumps(payload),
                AUDIT_ACCESS,
            )
        except Exception as exc:
            logger.warning(
                "sensitive_crystal_seed: audit row insert failed "
                "(event=%s domain=%s): %s",
                event_type, domain, exc,
            )

    # ------------------------------------------------------------------
    # Per-crystal storage
    # ------------------------------------------------------------------

    async def _insert_crystal(
        self,
        conn,
        *,
        domain: str,
        crystal_text: str,
        confidence: float,
        scope: str,
        topics: List[str],
        requires_embodiment_phase: Optional[bool],
        metadata: Dict[str, Any],
        content_hash: str,
    ) -> Optional[int]:
        """Insert with status = awaiting_clinician_authoring.

        Returns ``id`` on success, ``None`` if the row already existed
        (idempotent re-ingest). Caller is responsible for emitting the
        audit row with the appropriate event type.
        """
        # Stamp metadata so the clinician portal can show provenance.
        annotated_meta = dict(metadata or {})
        annotated_meta.setdefault("ingested_by", "sensitive_crystal_seed_ingestion")
        annotated_meta.setdefault(
            "ingested_at", datetime.now(timezone.utc).isoformat()
        )
        annotated_meta.setdefault("needs_clinician_review", True)

        row = await conn.fetchrow(
            """
            INSERT INTO nate_intelligence_crystals (
                crystal_text, domain, scope, topics,
                source_count, generation, confidence,
                content_hash, metadata, crystal_status,
                requires_embodiment_phase
            ) VALUES (
                $1, $2, $3, $4::text[],
                1, 0, $5,
                $6, $7::jsonb, $8,
                $9
            )
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id
            """,
            crystal_text,
            domain,
            scope,
            topics,
            float(confidence),
            content_hash,
            json.dumps(annotated_meta),
            SEED_STATUS,
            requires_embodiment_phase,
        )
        return row["id"] if row else None

    # ------------------------------------------------------------------
    # File-level orchestration
    # ------------------------------------------------------------------

    async def ingest_file(
        self,
        path: Path,
    ) -> Dict[str, Any]:
        """Ingest one seed JSON. Returns per-file summary.

        Summary shape::

            {"file": str, "domain": str, "considered": int,
             "ingested": int, "validator_blocked": int,
             "embodiment_blocked": int, "duplicates": int,
             "errors": [str, ...]}
        """
        summary: Dict[str, Any] = {
            "file": str(path),
            "domain": None,
            "considered": 0,
            "ingested": 0,
            "validator_blocked": 0,
            "embodiment_blocked": 0,
            "duplicates": 0,
            "errors": [],
        }

        if self._db_pool is None:
            summary["errors"].append("db_pool_missing")
            return summary

        try:
            raw = path.read_text(encoding="utf-8")
            doc = json.loads(raw)
        except Exception as exc:
            summary["errors"].append(f"json_parse:{exc}")
            return summary

        domain = doc.get("domain")
        crystals = doc.get("crystals", [])
        file_default_embodiment = doc.get("default_requires_embodiment_phase")
        if not isinstance(domain, str) or not isinstance(crystals, list):
            summary["errors"].append("invalid_schema")
            return summary

        summary["domain"] = domain
        summary["considered"] = len(crystals)

        async with self._db_pool.acquire() as conn:
            sensitive_domains = await self._load_sensitive_domains(conn)
            embodiment_required = self._embodiment_tag_required(
                domain, sensitive_domains
            )

            for c in crystals:
                if not isinstance(c, dict):
                    summary["errors"].append("non_object_crystal_entry")
                    continue
                text = c.get("crystal_text") or ""
                if not isinstance(text, str) or not text.strip():
                    summary["errors"].append("blank_crystal_text")
                    continue

                content_hash = _content_hash(domain, text)

                # ── Note 2b: embodiment tag gate (sensitive domains only)
                tag_value = self._resolve_embodiment_tag(
                    c, file_default_embodiment
                )
                if embodiment_required and tag_value is None:
                    summary["embodiment_blocked"] += 1
                    await self._emit_audit(
                        conn,
                        event_type=EVT_EMBODIMENT_BLOCK,
                        domain=domain,
                        content_hash=content_hash,
                        extra={"reason": "missing_requires_embodiment_phase"},
                    )
                    continue

                # ── Note 2a: validator gate
                passed, warnings = await self._validate_or_block(text)
                if not passed:
                    summary["validator_blocked"] += 1
                    await self._emit_audit(
                        conn,
                        event_type=EVT_VALIDATOR_BLOCK,
                        domain=domain,
                        content_hash=content_hash,
                        warnings=warnings,
                    )
                    continue

                # ── Storage with awaiting_clinician_authoring (Note 2c)
                try:
                    inserted_id = await self._insert_crystal(
                        conn,
                        domain=domain,
                        crystal_text=text,
                        confidence=float(c.get("confidence", 0.45)),
                        scope=str(c.get("scope", "global")),
                        topics=list(c.get("topics", [])),
                        requires_embodiment_phase=tag_value,
                        metadata=c.get("metadata", {}) or {},
                        content_hash=content_hash,
                    )
                except Exception as exc:
                    summary["errors"].append(f"insert_failed:{type(exc).__name__}")
                    continue

                if inserted_id is None:
                    summary["duplicates"] += 1
                    continue

                summary["ingested"] += 1
                await self._emit_audit(
                    conn,
                    event_type=EVT_INGESTED,
                    domain=domain,
                    content_hash=content_hash,
                    extra={
                        "crystal_id": inserted_id,
                        "requires_embodiment_phase": tag_value,
                        "ships_as": SEED_STATUS,
                    },
                )

        return summary

    async def ingest_all(
        self,
        seed_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Ingest every ``*.json`` under ``seed_dir`` (or the default).

        Returns aggregate summary with per-file breakdown and totals.
        Files are processed sequentially so a single failure doesn't
        cascade and so audit emission ordering remains deterministic.
        """
        target_dir = Path(seed_dir) if seed_dir else self._seed_dir
        aggregate: Dict[str, Any] = {
            "seed_dir": str(target_dir),
            "files_processed": 0,
            "totals": {
                "considered": 0,
                "ingested": 0,
                "validator_blocked": 0,
                "embodiment_blocked": 0,
                "duplicates": 0,
            },
            "per_file": [],
            "errors": [],
        }

        if not target_dir.is_dir():
            aggregate["errors"].append(f"seed_dir_missing:{target_dir}")
            return aggregate

        files = sorted(target_dir.glob("*.json"))
        for path in files:
            try:
                file_summary = await self.ingest_file(path)
            except Exception as exc:
                aggregate["errors"].append(
                    f"file_failed:{path.name}:{type(exc).__name__}"
                )
                continue

            aggregate["per_file"].append(file_summary)
            aggregate["files_processed"] += 1
            for key in (
                "considered", "ingested", "validator_blocked",
                "embodiment_blocked", "duplicates",
            ):
                aggregate["totals"][key] += int(file_summary.get(key, 0))

        return aggregate
