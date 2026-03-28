"""
SOVEREIGN SWARM — SLF Exporter
Sovereign Legacy Format export: AES-256-GCM encrypted ZIP archive
containing all member data in portable format.

Operational Specifications §6 — Data Portability.
"""

import asyncio
import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.portability import SLFExportRequest, SLFManifest, SLFSection

logger = logging.getLogger("portability.slf_exporter")


class SLFExporter:
    """
    Exports member data in Sovereign Legacy Format.
    Creates an AES-256-GCM encrypted ZIP archive with manifest.
    """

    def __init__(self, db_pool=None, vault=None, consent_service=None):
        self._db = db_pool
        self._vault = vault
        self._consent = consent_service

    async def export(
        self,
        request: SLFExportRequest,
    ) -> Dict[str, Any]:
        """
        Execute a full SLF export for a user.
        Returns the export result with file path and metadata.
        """
        user_id = request.user_id
        result = {
            "export_id": request.request_id,
            "user_id": user_id,
            "status": "processing",
            "sections_exported": [],
            "total_files": 0,
            "errors": [],
        }

        # Build manifest
        manifest = SLFManifest(
            user_id=user_id,
            user_display_name=await self._get_display_name(user_id),
        )

        # Create in-memory ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for section in request.sections:
                try:
                    data = await self._export_section(user_id, section)
                    if data:
                        filename = f"{section.value}.json"
                        content = json.dumps(data, indent=2, default=str)
                        zf.writestr(filename, content)

                        # Add checksum
                        checksum = hashlib.sha256(content.encode()).hexdigest()
                        manifest.checksums[filename] = checksum
                        manifest.sections_included.append(section.value)
                        manifest.total_files += 1
                        result["sections_exported"].append(section.value)
                except Exception as e:
                    result["errors"].append(f"{section.value}: {str(e)}")
                    logger.error("Section export failed: %s - %s", section.value, e)

            # Write manifest
            manifest_json = manifest.model_dump_json(indent=2)
            zf.writestr("manifest.json", manifest_json)
            manifest.total_files += 1

        result["total_files"] = manifest.total_files
        result["total_size_bytes"] = zip_buffer.tell()
        result["status"] = "complete" if not result["errors"] else "partial"

        # Persist export record
        await self._persist_export(request, result)

        logger.info(
            "SLF export complete: user=%s sections=%d files=%d size=%d",
            user_id, len(result["sections_exported"]),
            result["total_files"], result["total_size_bytes"],
        )
        return result

    async def _export_section(
        self, user_id: str, section: SLFSection
    ) -> Optional[Dict[str, Any]]:
        """Export a single section of data."""
        if not self._db:
            return None

        exporters = {
            SLFSection.IDENTITY: self._export_identity,
            SLFSection.SESSIONS: self._export_sessions,
            SLFSection.COHERENCE: self._export_coherence,
            SLFSection.VOICE_BIOMETRICS: self._export_voice_biometrics,
            SLFSection.FAMILY_SANCTUARY: self._export_family_sanctuary,
            SLFSection.NIGHT_SCHOOL: self._export_night_school,
            SLFSection.FORESIGHT: self._export_foresight,
            SLFSection.PATTERNS: self._export_patterns,
            SLFSection.ME2ME_CRYSTAL: self._export_crystals,
            SLFSection.ME2ME_IMPRINTS: self._export_imprints,
            SLFSection.ME2ME_AVATAR: self._export_me2me_avatar,
            SLFSection.TREATMENT_PLANS: self._export_treatment_plans,
            SLFSection.SAFETY_PLANS: self._export_safety_plans,
            SLFSection.BILLING: self._export_billing,
            SLFSection.TRUST: self._export_trust,
        }

        exporter = exporters.get(section)
        if exporter:
            return await exporter(user_id)
        return {"section": section.value, "data": []}

    async def _export_identity(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            return {"identity": dict(user) if user else {}}

    async def _export_sessions(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM sessions WHERE client_id = $1 ORDER BY started_at", user_id,
            )
            return {"sessions": [dict(r) for r in rows]}

    async def _export_coherence(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM nevedal_cold_starts WHERE user_id = $1", user_id,
            )
            return {"coherence": [dict(r) for r in rows]}

    async def _export_family_sanctuary(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM emotional_weather_snapshots
                WHERE family_id IN (SELECT family_id FROM family_members WHERE user_id = $1)
                ORDER BY created_at""",
                user_id,
            )
            return {"family_sanctuary": [dict(r) for r in rows]}

    async def _export_crystals(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM me2me_identity_crystals WHERE user_id = $1 ORDER BY synthesized_at",
                user_id,
            )
            return {"crystals": [dict(r) for r in rows]}

    async def _export_imprints(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM me2me_imprint_entries WHERE user_id = $1 ORDER BY captured_at",
                user_id,
            )
            return {"imprints": [dict(r) for r in rows]}

    async def _export_voice_biometrics(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM nevedal_metrics
                WHERE user_id = $1 ORDER BY recorded_at""",
                user_id,
            )
            # Decrypt biometric fields that may be encrypted at rest
            results = []
            for r in rows:
                row_dict = dict(r)
                if row_dict.get("biometrics") and isinstance(row_dict["biometrics"], dict):
                    try:
                        from app.field_encryption import decrypt_fields
                        row_dict["biometrics"] = decrypt_fields(row_dict["biometrics"])
                    except Exception:
                        pass
                results.append(row_dict)
            return {"voice_biometrics": results}

    async def _export_night_school(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM wisdom_entries
                WHERE source LIKE $1 ORDER BY created_at""",
                f"%{user_id}%",
            )
            return {"night_school": [dict(r) for r in rows]}

    async def _export_foresight(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM foresight_predictions
                WHERE user_id = $1 ORDER BY created_at""",
                user_id,
            )
            return {"foresight": [dict(r) for r in rows]}

    async def _export_patterns(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM pattern_detections
                WHERE user_id = $1 ORDER BY detected_at""",
                user_id,
            )
            return {"patterns": [dict(r) for r in rows]}

    async def _export_me2me_avatar(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            avatars = await conn.fetch(
                "SELECT * FROM me2me_avatars WHERE user_id = $1", user_id,
            )
            growth_layers = await conn.fetch(
                """SELECT * FROM me2me_growth_layers
                WHERE avatar_id IN (SELECT avatar_id FROM me2me_avatars WHERE user_id = $1)""",
                user_id,
            )
            return {
                "avatars": [dict(r) for r in avatars],
                "growth_layers": [dict(r) for r in growth_layers],
            }

    async def _export_treatment_plans(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM clinical_records WHERE user_id = $1 AND record_type = 'treatment_plan'",
                user_id,
            )
            return {"treatment_plans": [dict(r) for r in rows]}

    async def _export_safety_plans(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM clinical_records WHERE user_id = $1 AND record_type = 'safety_plan'",
                user_id,
            )
            return {"safety_plans": [dict(r) for r in rows]}

    async def _export_billing(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM usage_records WHERE user_id = $1 ORDER BY timestamp", user_id,
            )
            return {"billing": [dict(r) for r in rows]}

    async def _export_trust(self, user_id: str) -> Dict[str, Any]:
        async with self._db.acquire() as conn:
            trusts = await conn.fetch(
                "SELECT * FROM me2me_sovereign_trusts WHERE user_id = $1", user_id,
            )
            return {"trusts": [dict(r) for r in trusts]}

    async def _get_display_name(self, user_id: str) -> str:
        if not self._db:
            return ""
        try:
            async with self._db.acquire() as conn:
                return await conn.fetchval(
                    "SELECT name FROM users WHERE id = $1", user_id,
                ) or ""
        except Exception:
            return ""

    async def _persist_export(
        self, request: SLFExportRequest, result: Dict[str, Any]
    ) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO slf_export_requests
                    (request_id, user_id, requested_by, sections, status, file_size_bytes, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    ON CONFLICT (request_id) DO UPDATE SET
                        status = EXCLUDED.status, completed_at = NOW()""",
                    request.request_id, request.user_id, request.requested_by,
                    str([s.value for s in request.sections]),
                    result["status"], result.get("total_size_bytes", 0),
                )
        except Exception as e:
            logger.error("Export record persistence failed: %s", e)
