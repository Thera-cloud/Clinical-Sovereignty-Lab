"""Neuroscience Foundations Ingestion — crystallizes the neuroscience knowledge JSON
into nate_intelligence_crystals as global, high-confidence reference knowledge.

Pattern follows backend/app/sse/workbook_ingestion.py (high-confidence global crystals)
but targets the actual production schema (id SERIAL PK, content_hash UNIQUE,
metadata JSONB, topics text[]).

Idempotent: re-running yields created=0 because content_hash collisions are skipped
via ON CONFLICT (content_hash) DO NOTHING.
"""

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CRYSTALS_PATH = Path(__file__).resolve().parents[3] / "docs" / "NEUROSCIENCE_KNOWLEDGE_CRYSTALS_2026-05-07.json"

_CONFIDENCE_MAP = {
    "evidenced": 0.92,
    "emerging": 0.75,
    "design_philosophy": 0.60,
}


async def ingest_neuroscience_crystals(db_pool, source_path: Path | None = None) -> dict:
    """Read the neuroscience crystals JSON and store each as a global crystal.

    Returns: {"path": str, "processed": int, "created": int, "skipped": int}
    """
    path = source_path or _CRYSTALS_PATH
    if not path.exists():
        return {"error": f"crystals JSON not found: {path}", "processed": 0, "created": 0, "skipped": 0}

    payload = json.loads(path.read_text())
    crystals = payload.get("crystals") if isinstance(payload, dict) else payload
    if not isinstance(crystals, list):
        return {"error": "JSON has no 'crystals' list", "processed": 0, "created": 0, "skipped": 0}

    processed = 0
    created = 0
    skipped = 0

    async with db_pool.acquire() as conn:
        for entry in crystals:
            text = (entry.get("crystal_text") or "").strip()
            if not text:
                continue
            processed += 1

            content_hash = hashlib.sha256(text.encode()).hexdigest()
            confidence_label = entry.get("confidence", "design_philosophy")
            confidence = _CONFIDENCE_MAP.get(confidence_label, 0.60)
            tags = entry.get("tags") or []
            topics = [t for t in tags if isinstance(t, str)][:16]

            metadata = {
                "source_crystal_id": entry.get("crystal_id"),
                "category": entry.get("category"),
                "scientific_basis": entry.get("scientific_basis"),
                "code_reference": entry.get("code_reference"),
                "applies_to_features": entry.get("applies_to_features") or [],
                "confidence_label": confidence_label,
                "ingestion_source": "NEUROSCIENCE_KNOWLEDGE_CRYSTALS_2026-05-07.json",
            }

            row = await conn.fetchrow(
                "INSERT INTO nate_intelligence_crystals "
                "(crystal_text, domain, scope, confidence, source_count, generation, "
                " content_hash, topics, metadata, created_at, updated_at) "
                "VALUES ($1, 'neuroscience_foundations', 'global', $2, 1, 0, "
                " $3, $4::text[], $5::jsonb, NOW(), NOW()) "
                "ON CONFLICT (content_hash) DO NOTHING RETURNING id",
                text, confidence, content_hash, topics, json.dumps(metadata))

            if row:
                created += 1
            else:
                skipped += 1

    logger.info("neuroscience_ingestion: processed=%d created=%d skipped=%d",
                processed, created, skipped)
    return {
        "path": str(path),
        "processed": processed,
        "created": created,
        "skipped": skipped,
    }
