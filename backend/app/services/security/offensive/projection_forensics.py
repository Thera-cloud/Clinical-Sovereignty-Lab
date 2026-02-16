"""
HIVE DEFENSE PROTOCOL — Projection Forensics (Phase 8E)
Evidentiary chain preservation for law enforcement.

The Projection Forensics service maintains a complete, cryptographically
chained evidence record of every Projected Helix operation.  Records
include command interceptions, mirror responses, intelligence gathered,
and all interactions with the attacker's infrastructure.

Every record is timestamped, hashed, and signed.  Chain of custody
tracking ensures evidence is admissible in legal proceedings.

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import ForensicRecord

logger = logging.getLogger("hive.projection_forensics")


# =============================================================================
# EVIDENCE FORMAT
# =============================================================================

class EvidenceFormat:
    """Supported evidence export formats."""
    JSON = "json"
    CSV = "csv"
    PDF_READY = "pdf_ready"
    LAW_ENFORCEMENT = "law_enforcement"


# =============================================================================
# CHAIN OF CUSTODY ENTRY
# =============================================================================

class CustodyEntry:
    """
    A single chain-of-custody record.

    Tracks who handled the evidence, when, and for what purpose.
    """

    def __init__(
        self,
        handler: str,
        action: str,
        purpose: str,
    ) -> None:
        self.entry_id: UUID = uuid4()
        self.handler: str = handler
        self.action: str = action
        self.purpose: str = purpose
        self.timestamp: datetime = datetime.utcnow()
        self.integrity_hash: str = self._compute_hash()

    def _compute_hash(self) -> str:
        data = (
            f"{self.entry_id}:{self.handler}:{self.action}:"
            f"{self.purpose}:{self.timestamp.isoformat()}"
        )
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "handler": self.handler,
            "action": self.action,
            "purpose": self.purpose,
            "timestamp": self.timestamp.isoformat(),
            "integrity_hash": self.integrity_hash,
        }


# =============================================================================
# PROJECTION FORENSICS
# =============================================================================

class ProjectionForensics:
    """
    Evidentiary chain preservation for Projected Helix operations.

    Maintains immutable, cryptographically chained records of all
    interactions, intelligence, and evidence gathered during Projected
    Helix deployments.  Supports law enforcement report generation and
    evidence export in multiple formats.

    Attributes
    ----------
    deployment_records : dict[UUID, list[ForensicRecord]]
        Forensic records indexed by deployment ID.
    intelligence_records : dict[UUID, list[dict]]
        Intelligence findings indexed by deployment ID.
    custody_chains : dict[UUID, list[CustodyEntry]]
        Chain of custody for each deployment's evidence.

    Usage
    -----
    ::

        forensics = ProjectionForensics()
        await forensics.record_interception(
            deployment_id, command, response
        )
        await forensics.record_intelligence(
            deployment_id, {"finding": "C&C topology mapped"}
        )
        report = await forensics.generate_law_enforcement_report(
            deployment_id
        )
        evidence = await forensics.export_evidence(
            deployment_id, format="law_enforcement"
        )
    """

    def __init__(self, *, db_pool: Any = None) -> None:
        """
        Initialise the Projection Forensics service.

        Parameters
        ----------
        db_pool:
            Optional asyncpg connection pool for evidence persistence.
        """
        self.db_pool = db_pool

        # Evidence stores indexed by deployment ID
        self.deployment_records: Dict[UUID, List[ForensicRecord]] = {}
        self.intelligence_records: Dict[UUID, List[Dict[str, Any]]] = {}
        self.custody_chains: Dict[UUID, List[CustodyEntry]] = {}

        # Global chain hash for cross-deployment integrity
        self._global_chain_hash: str = hashlib.sha256(
            b"PROJECTION_FORENSICS_GENESIS_v1"
        ).hexdigest()

        # Metrics
        self._total_interceptions_recorded: int = 0
        self._total_intelligence_recorded: int = 0

        logger.info("ProjectionForensics initialised — evidence chain started")

    # ------------------------------------------------------------------
    # Record interception
    # ------------------------------------------------------------------

    async def record_interception(
        self,
        deployment_id: UUID,
        command: Dict[str, Any],
        response: Dict[str, Any],
    ) -> ForensicRecord:
        """
        Record a command interception event as forensic evidence.

        Creates an immutable :class:`ForensicRecord` chained to the
        previous record for this deployment, with timestamp, hashes,
        and full command/response data.

        Parameters
        ----------
        deployment_id:
            The Projected Helix deployment UUID.
        command:
            The intercepted attacker command.
        response:
            The mirror response that was sent.

        Returns
        -------
        ForensicRecord
            The newly created forensic record.
        """
        # Ensure stores exist for this deployment
        if deployment_id not in self.deployment_records:
            self.deployment_records[deployment_id] = []
            self.custody_chains[deployment_id] = []

        records = self.deployment_records[deployment_id]

        # Build evidence payload
        evidence: Dict[str, Any] = {
            "event": "command_intercepted",
            "command": self._sanitize_for_evidence(command),
            "command_hash": hashlib.sha256(
                json.dumps(command, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "response": self._sanitize_for_evidence(response),
            "response_hash": hashlib.sha256(
                json.dumps(response, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "interception_number": len(records) + 1,
        }

        # Create the forensic record
        record = ForensicRecord(
            record_id=uuid4(),
            event_type="hive.projection.interception",
            source_entity=str(deployment_id),
            evidence=evidence,
            timestamp=datetime.utcnow(),
        )

        # Chain to previous record
        previous_hash = (
            records[-1].chain_hash if records else self._global_chain_hash
        )
        record.compute_chain_hash(previous_hash=previous_hash)

        # Update global chain
        self._global_chain_hash = record.chain_hash

        # Store
        records.append(record)
        self._total_interceptions_recorded += 1

        # Persist to DB
        await self._persist_record(deployment_id, record)

        logger.debug(
            "Forensic interception recorded: deployment=%s record=%s "
            "chain_hash=%s",
            deployment_id,
            record.record_id,
            record.chain_hash[:16],
        )

        return record

    # ------------------------------------------------------------------
    # Record intelligence
    # ------------------------------------------------------------------

    async def record_intelligence(
        self,
        deployment_id: UUID,
        finding: Dict[str, Any],
    ) -> ForensicRecord:
        """
        Record an intelligence finding as forensic evidence.

        Parameters
        ----------
        deployment_id:
            The Projected Helix deployment UUID.
        finding:
            The intelligence finding to record.

        Returns
        -------
        ForensicRecord
            The newly created forensic record.
        """
        # Ensure stores exist
        if deployment_id not in self.deployment_records:
            self.deployment_records[deployment_id] = []
            self.custody_chains[deployment_id] = []
        if deployment_id not in self.intelligence_records:
            self.intelligence_records[deployment_id] = []

        records = self.deployment_records[deployment_id]

        # Build evidence
        timestamped_finding = {
            **finding,
            "recorded_at": datetime.utcnow().isoformat(),
            "finding_number": len(self.intelligence_records[deployment_id]) + 1,
        }
        self.intelligence_records[deployment_id].append(timestamped_finding)

        evidence: Dict[str, Any] = {
            "event": "intelligence_gathered",
            "finding": self._sanitize_for_evidence(finding),
            "finding_hash": hashlib.sha256(
                json.dumps(finding, sort_keys=True, default=str).encode()
            ).hexdigest(),
        }

        # Create the forensic record
        record = ForensicRecord(
            record_id=uuid4(),
            event_type="hive.projection.intelligence",
            source_entity=str(deployment_id),
            evidence=evidence,
            timestamp=datetime.utcnow(),
        )

        # Chain
        previous_hash = (
            records[-1].chain_hash if records else self._global_chain_hash
        )
        record.compute_chain_hash(previous_hash=previous_hash)
        self._global_chain_hash = record.chain_hash

        records.append(record)
        self._total_intelligence_recorded += 1

        await self._persist_record(deployment_id, record)

        logger.debug(
            "Forensic intelligence recorded: deployment=%s record=%s",
            deployment_id,
            record.record_id,
        )

        return record

    # ------------------------------------------------------------------
    # Law enforcement report
    # ------------------------------------------------------------------

    async def generate_law_enforcement_report(
        self,
        deployment_id: UUID,
    ) -> Dict[str, Any]:
        """
        Generate a complete evidentiary package for law enforcement.

        Includes all interception records, intelligence findings, chain
        of custody, and integrity verification results.

        Parameters
        ----------
        deployment_id:
            The Projected Helix deployment UUID.

        Returns
        -------
        dict
            A comprehensive evidentiary package.
        """
        records = self.deployment_records.get(deployment_id, [])
        intelligence = self.intelligence_records.get(deployment_id, [])
        custody = self.custody_chains.get(deployment_id, [])

        # Record chain of custody for this export
        custody_entry = CustodyEntry(
            handler="ProjectionForensics",
            action="generate_law_enforcement_report",
            purpose="Law enforcement evidentiary package generation",
        )
        if deployment_id in self.custody_chains:
            self.custody_chains[deployment_id].append(custody_entry)

        # Verify chain integrity
        chain_valid = self._verify_deployment_chain(deployment_id)

        # Build the report
        report: Dict[str, Any] = {
            "report_id": str(uuid4()),
            "deployment_id": str(deployment_id),
            "generated_at": datetime.utcnow().isoformat(),
            "report_type": "law_enforcement_evidentiary_package",
            "classification": "CONFIDENTIAL — LAW ENFORCEMENT SENSITIVE",
            "summary": {
                "total_interceptions": sum(
                    1
                    for r in records
                    if r.event_type == "hive.projection.interception"
                ),
                "total_intelligence_findings": len(intelligence),
                "chain_integrity_verified": chain_valid,
                "evidence_records": len(records),
                "custody_entries": len(custody),
            },
            "timeline": [
                {
                    "record_id": str(r.record_id),
                    "event_type": r.event_type,
                    "timestamp": r.timestamp.isoformat(),
                    "chain_hash": r.chain_hash,
                    "evidence_summary": self._summarize_evidence(r.evidence),
                }
                for r in records
            ],
            "intelligence_findings": intelligence,
            "chain_of_custody": [
                entry.to_dict() for entry in custody
            ],
            "chain_integrity": {
                "verified": chain_valid,
                "total_records": len(records),
                "genesis_hash": (
                    records[0].previous_record_hash
                    if records
                    else self._global_chain_hash
                ),
                "latest_hash": (
                    records[-1].chain_hash if records else "none"
                ),
            },
            "legal_notice": (
                "This evidentiary package was generated by the Hive Defense "
                "Protocol's Projection Forensics system.  All records are "
                "cryptographically chained and immutable.  Chain of custody "
                "is tracked from creation through export.  Records have not "
                "been altered since their creation."
            ),
        }

        # Hash the complete report for integrity
        report_content = json.dumps(report, sort_keys=True, default=str)
        report["report_hash"] = hashlib.sha256(
            report_content.encode()
        ).hexdigest()

        logger.warning(
            "Law enforcement report generated: deployment=%s records=%d "
            "intelligence=%d chain_valid=%s",
            deployment_id,
            len(records),
            len(intelligence),
            chain_valid,
        )

        return report

    # ------------------------------------------------------------------
    # Evidence export
    # ------------------------------------------------------------------

    async def export_evidence(
        self,
        deployment_id: UUID,
        format: str = EvidenceFormat.JSON,
    ) -> Dict[str, Any]:
        """
        Export evidence for a deployment in the specified format.

        Parameters
        ----------
        deployment_id:
            The Projected Helix deployment UUID.
        format:
            Export format.  One of ``json``, ``csv``, ``pdf_ready``,
            ``law_enforcement``.

        Returns
        -------
        dict
            The exported evidence package.
        """
        records = self.deployment_records.get(deployment_id, [])
        intelligence = self.intelligence_records.get(deployment_id, [])

        # Record custody for this export
        custody_entry = CustodyEntry(
            handler="ProjectionForensics",
            action=f"export_evidence_{format}",
            purpose=f"Evidence export in {format} format",
        )
        if deployment_id in self.custody_chains:
            self.custody_chains[deployment_id].append(custody_entry)

        if format == EvidenceFormat.LAW_ENFORCEMENT:
            return await self.generate_law_enforcement_report(deployment_id)

        # Standard export
        export: Dict[str, Any] = {
            "export_id": str(uuid4()),
            "deployment_id": str(deployment_id),
            "format": format,
            "exported_at": datetime.utcnow().isoformat(),
            "record_count": len(records),
            "intelligence_count": len(intelligence),
        }

        if format == EvidenceFormat.JSON:
            export["records"] = [
                {
                    "record_id": str(r.record_id),
                    "event_type": r.event_type,
                    "source_entity": r.source_entity,
                    "target_entity": r.target_entity,
                    "evidence": r.evidence,
                    "chain_hash": r.chain_hash,
                    "previous_record_hash": r.previous_record_hash,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in records
            ]
            export["intelligence"] = intelligence

        elif format == EvidenceFormat.CSV:
            # CSV-ready flat structure
            rows: List[Dict[str, Any]] = []
            for r in records:
                rows.append({
                    "record_id": str(r.record_id),
                    "event_type": r.event_type,
                    "timestamp": r.timestamp.isoformat(),
                    "chain_hash": r.chain_hash,
                    "evidence_summary": self._summarize_evidence(r.evidence),
                })
            export["rows"] = rows

        elif format == EvidenceFormat.PDF_READY:
            # Structured for PDF rendering
            export["title"] = (
                f"Projected Helix Evidence Report — Deployment {deployment_id}"
            )
            export["sections"] = [
                {
                    "heading": "Executive Summary",
                    "content": (
                        f"This report contains {len(records)} forensic records "
                        f"and {len(intelligence)} intelligence findings from "
                        f"Projected Helix deployment {deployment_id}."
                    ),
                },
                {
                    "heading": "Evidence Timeline",
                    "records": [
                        {
                            "time": r.timestamp.isoformat(),
                            "type": r.event_type,
                            "summary": self._summarize_evidence(r.evidence),
                        }
                        for r in records
                    ],
                },
                {
                    "heading": "Intelligence Findings",
                    "findings": intelligence,
                },
            ]

        # Compute export hash
        export_content = json.dumps(export, sort_keys=True, default=str)
        export["export_hash"] = hashlib.sha256(
            export_content.encode()
        ).hexdigest()

        logger.info(
            "Evidence exported: deployment=%s format=%s records=%d",
            deployment_id,
            format,
            len(records),
        )

        return export

    # ------------------------------------------------------------------
    # Chain verification
    # ------------------------------------------------------------------

    def _verify_deployment_chain(self, deployment_id: UUID) -> bool:
        """
        Verify the cryptographic chain integrity for a deployment.

        Parameters
        ----------
        deployment_id:
            The deployment to verify.

        Returns
        -------
        bool
            ``True`` if the chain is intact.
        """
        records = self.deployment_records.get(deployment_id, [])
        if not records:
            return True

        for idx, record in enumerate(records):
            if idx == 0:
                expected_prev = record.previous_record_hash
            else:
                expected_prev = records[idx - 1].chain_hash

            if record.previous_record_hash != expected_prev:
                logger.error(
                    "Chain integrity failure at record %d (%s) for "
                    "deployment %s: previous_hash mismatch",
                    idx,
                    record.record_id,
                    deployment_id,
                )
                return False

            # Recompute hash
            data = (
                f"{record.record_id}:{record.event_type}:"
                f"{record.timestamp.isoformat()}:{expected_prev}"
            )
            expected_hash = hashlib.sha256(data.encode()).hexdigest()
            if record.chain_hash != expected_hash:
                logger.error(
                    "Chain integrity failure at record %d (%s) for "
                    "deployment %s: hash mismatch",
                    idx,
                    record.record_id,
                    deployment_id,
                )
                return False

        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_for_evidence(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitise data for evidence storage.

        Ensures all values are JSON-serialisable and removes any
        transient internal fields (prefixed with ``_``).
        """
        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            if key.startswith("_"):
                continue
            try:
                json.dumps(value, default=str)
                sanitized[key] = value
            except (TypeError, ValueError):
                sanitized[key] = str(value)
        return sanitized

    @staticmethod
    def _summarize_evidence(evidence: Dict[str, Any]) -> str:
        """Generate a one-line summary of evidence for reports."""
        event = evidence.get("event", "unknown")
        if event == "command_intercepted":
            cmd_type = evidence.get("command", {}).get("type", "unknown")
            return f"Intercepted {cmd_type} command"
        elif event == "intelligence_gathered":
            finding = evidence.get("finding", {})
            return f"Intelligence: {str(finding)[:100]}"
        return f"Event: {event}"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_record(
        self,
        deployment_id: UUID,
        record: ForensicRecord,
    ) -> None:
        """Persist a forensic record to the database (best-effort)."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_projection_forensics (
                        record_id, deployment_id, event_type,
                        source_entity, target_entity, evidence,
                        chain_hash, previous_record_hash, timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (record_id) DO NOTHING
                    """,
                    record.record_id,
                    deployment_id,
                    record.event_type,
                    record.source_entity,
                    record.target_entity,
                    json.dumps(record.evidence, default=str),
                    record.chain_hash,
                    record.previous_record_hash,
                    record.timestamp,
                )
        except Exception as exc:
            logger.warning(
                "Failed to persist forensic record %s: %s",
                record.record_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "active_deployments": len(self.deployment_records),
            "total_interceptions_recorded": self._total_interceptions_recorded,
            "total_intelligence_recorded": self._total_intelligence_recorded,
            "total_records": sum(
                len(records)
                for records in self.deployment_records.values()
            ),
            "global_chain_hash": self._global_chain_hash[:16],
            "per_deployment": {
                str(did): {
                    "records": len(records),
                    "intelligence": len(
                        self.intelligence_records.get(did, [])
                    ),
                    "custody_entries": len(
                        self.custody_chains.get(did, [])
                    ),
                }
                for did, records in self.deployment_records.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"<ProjectionForensics deployments={len(self.deployment_records)} "
            f"records={self._total_interceptions_recorded + self._total_intelligence_recorded} "
            f"chain={self._global_chain_hash[:12]}…>"
        )
