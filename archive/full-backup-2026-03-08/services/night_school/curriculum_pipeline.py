"""
SOVEREIGN SWARM — Night School Curriculum Pipeline
Manages the end-to-end content ingestion pipeline:
intake → parse → modality select → RAG index → approval → absorption.

Operational Specifications §3 — Night School Curriculum Ingestion.
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("night_school.curriculum_pipeline")


class CurriculumPipeline:
    """
    Orchestrates Night School content ingestion from raw materials
    through parsing, modality tagging, RAG indexing, and approval.
    """

    def __init__(
        self,
        content_parser=None,
        modality_selector=None,
        rag_indexer=None,
        approval_service=None,
        sovereign_mind=None,
        db_pool=None,
    ):
        self._parser = content_parser
        self._modality = modality_selector
        self._rag = rag_indexer
        self._approval = approval_service
        self._sovereign_mind = sovereign_mind
        self._db = db_pool

    async def ingest_content(
        self,
        source_name: str,
        content_type: str,
        raw_content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a piece of content through the full pipeline.
        Returns the ingestion result with status and extracted data.
        """
        content_hash = hashlib.sha256(raw_content.encode()).hexdigest()[:16]

        result = {
            "content_hash": content_hash,
            "source": source_name,
            "type": content_type,
            "status": "processing",
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Step 1: Parse content
        parsed = None
        if self._parser:
            try:
                parsed = await self._parser.parse(
                    raw_content, content_type=content_type
                )
                result["parsed_sections"] = len(parsed.get("sections", []))
                result["protocols_found"] = len(parsed.get("protocols", []))
                result["techniques_found"] = len(parsed.get("techniques", []))
                result["research_found"] = len(parsed.get("research", []))
            except Exception as e:
                logger.error("Content parsing failed: %s", e)
                result["status"] = "parse_error"
                result["error"] = str(e)
                return result

        # Step 2: Modality selection
        modalities = []
        if self._modality and parsed:
            try:
                modalities = await self._modality.select_modalities(parsed)
                result["assigned_modalities"] = modalities
            except Exception as e:
                logger.warning("Modality selection failed: %s", e)

        # Step 3: RAG indexing
        if self._rag and parsed:
            try:
                index_result = await self._rag.index_content(
                    parsed, modalities=modalities, source=source_name
                )
                result["indexed_chunks"] = index_result.get("chunks_indexed", 0)
                result["index_id"] = index_result.get("index_id")
            except Exception as e:
                logger.warning("RAG indexing failed: %s", e)

        # Step 4: Submit for approval
        if self._approval:
            try:
                approval = await self._approval.submit_for_review(
                    content_hash=content_hash,
                    source=source_name,
                    content_type=content_type,
                    summary=parsed.get("summary", "") if parsed else "",
                    modalities=modalities,
                )
                result["approval_id"] = approval.get("approval_id")
                result["status"] = "pending_approval"
            except Exception as e:
                logger.warning("Approval submission failed: %s", e)
                result["status"] = "indexed_unapproved"
        else:
            result["status"] = "indexed"

        # Persist
        await self._persist_ingestion(result)

        logger.info(
            "Content ingested: source=%s type=%s status=%s",
            source_name, content_type, result["status"],
        )
        return result

    async def approve_content(self, content_hash: str) -> bool:
        """Approve ingested content for absorption by Sovereign Mind."""
        if self._sovereign_mind:
            try:
                await self._sovereign_mind.absorb_knowledge(content_hash)
                return True
            except Exception as e:
                logger.error("Knowledge absorption failed: %s", e)
        return False

    async def _persist_ingestion(self, result: Dict[str, Any]) -> None:
        """Persist ingestion result."""
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO night_school_ingestions (
                        content_hash, source, content_type, status, metadata
                    ) VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (content_hash) DO UPDATE SET
                        status = EXCLUDED.status
                    """,
                    result["content_hash"], result["source"],
                    result["type"], result["status"], str(result),
                )
        except Exception:
            pass
