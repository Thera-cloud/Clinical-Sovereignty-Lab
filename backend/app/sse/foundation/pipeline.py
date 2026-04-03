"""
SSE Stage 1 — Foundation Pipeline

Orchestrates the full Stage 1 flow: hash → provenance → parse → extract → generate.
Returns a complete story_plot JSON with delivery config and cost estimate.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from . import (
    document_parser,
    ip_provenance,
    narrative_extractor,
    story_plot_generator,
)

logger = logging.getLogger(__name__)


async def run_pipeline(
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    uploader_id: str,
    db_pool=None,
) -> dict[str, Any]:
    source_hash = hashlib.sha256(file_bytes).hexdigest()

    provenance_id = await ip_provenance.create_record(
        filename=filename,
        uploader_id=uploader_id,
        source_hash=source_hash,
        db_pool=db_pool,
    )

    parse_result = await document_parser.parse(file_bytes, mime_type, filename)

    if "error" in parse_result:
        await ip_provenance.update_status(provenance_id, "failed_ocr_required")
        return {
            "provenance_id": provenance_id,
            "error": parse_result,
        }

    narrative = await narrative_extractor.extract(
        parse_result["raw_text"],
        filename,
    )

    output = await story_plot_generator.generate(narrative)

    story_plot_id = output["story_plot"].get("id", "")
    await ip_provenance.update_status(
        provenance_id,
        "complete",
        story_plot_id=story_plot_id,
    )

    return {
        "provenance_id": provenance_id,
        "parse_result": parse_result,
        "story_plot": output["story_plot"],
        "delivery_config": output["delivery_config"],
        "estimated_cost": output["estimated_cost"],
    }
