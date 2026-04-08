"""Night School Workbook Ingestion — crystallizes protocol workbooks into Nate's knowledge base."""

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_WORKBOOK_DIR = Path(__file__).resolve().parents[2] / "resources" / "therapeutic_library" / "protocol_workbooks"
_METADATA_PATH = _WORKBOOK_DIR / "metadata.json"


async def ingest_workbooks(db_pool) -> dict:
    """Read all protocol workbooks and store each as a high-confidence global crystal."""
    if not _METADATA_PATH.exists():
        return {"error": "metadata.json not found", "workbooks_processed": 0, "crystals_created": 0}

    meta = json.loads(_METADATA_PATH.read_text())
    workbooks = meta.get("workbooks", [])
    created = 0
    processed = 0

    async with db_pool.acquire() as conn:
        for wb in workbooks:
            fname = wb.get("filename", "")
            wb_id = wb.get("id", "")
            protocol = wb.get("protocol_name", wb_id)
            fpath = _WORKBOOK_DIR / fname
            if not fpath.exists():
                logger.warning("workbook_ingestion: file not found: %s", fname)
                continue

            text = fpath.read_text().strip()
            if not text:
                continue
            processed += 1

            # Split into individual principles (each line starting with -)
            entries = []
            header = ""
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("[Protocol:"):
                    header = line
                elif line.startswith("- "):
                    entries.append(line[2:].strip())

            if not entries:
                entries = [text]

            for entry in entries:
                crystal_text = f"[{protocol}] {entry}"
                content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()

                existing = await conn.fetchval(
                    "SELECT 1 FROM nate_intelligence_crystals WHERE content_hash = $1",
                    content_hash)
                if existing:
                    continue

                crystal_id = str(uuid.uuid4())
                domain = _map_domain(wb_id)
                await conn.execute(
                    "INSERT INTO nate_intelligence_crystals "
                    "(crystal_id, crystal_text, domain, confidence, scope, source_count, "
                    " content_hash, created_at) "
                    "VALUES ($1, $2, $3, 0.95, 'global', 1, $4, NOW())",
                    crystal_id, crystal_text, domain, content_hash)
                created += 1

    logger.info("workbook_ingestion: processed %d workbooks, created %d crystals", processed, created)
    return {"workbooks_processed": processed, "crystals_created": created}


def _map_domain(wb_id: str) -> str:
    """Map workbook IDs to crystal domains."""
    clinical = {"ifs", "eft", "aedp", "attachment_theory", "nicc", "polyvagal",
                "memory_reconsolidation", "rogers_person_centered"}
    if wb_id in clinical:
        return "clinical"
    if wb_id in ("divine_resonance",):
        return "culture"
    if wb_id in ("jung_analytical",):
        return "research"
    if wb_id in ("faggin_quantum",):
        return "research"
    return "clinical"
