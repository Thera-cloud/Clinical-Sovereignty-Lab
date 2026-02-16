"""
SOVEREIGN SWARM — Night School RAG Indexer
Indexes parsed content for Retrieval-Augmented Generation.

Operational Specifications §3.3 — RAG Indexing.
"""

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("night_school.rag_indexer")


class RAGIndexer:
    """
    Indexes parsed clinical content for RAG retrieval.
    Chunks content, generates embeddings, and stores in the vector index.
    """

    def __init__(self, db_pool=None, embedding_service=None):
        self._db = db_pool
        self._embedding = embedding_service
        self._index: Dict[str, Dict[str, Any]] = {}

    async def index_content(
        self,
        parsed: Dict[str, Any],
        modalities: List[str] = None,
        source: str = "",
    ) -> Dict[str, Any]:
        """Index parsed content into the RAG store."""
        index_id = str(uuid4())
        chunks_indexed = 0

        for section in parsed.get("sections", []):
            content = section.get("content", "")
            if not content.strip():
                continue

            # Chunk the content
            chunks = self._chunk_text(content, max_tokens=500)
            for chunk in chunks:
                chunk_id = hashlib.sha256(chunk.encode()).hexdigest()[:16]
                entry = {
                    "chunk_id": chunk_id,
                    "index_id": index_id,
                    "source": source,
                    "section_title": section.get("title", ""),
                    "content": chunk,
                    "modalities": modalities or [],
                    "indexed_at": datetime.utcnow().isoformat(),
                }

                # Generate embedding if service available
                if self._embedding:
                    try:
                        embedding = await self._embedding.embed(chunk)
                        entry["embedding"] = embedding
                    except Exception as e:
                        logger.warning("Embedding generation failed: %s", e)

                self._index[chunk_id] = entry
                chunks_indexed += 1

        # Persist to database
        await self._persist_index(index_id, chunks_indexed, source)

        logger.info(
            "RAG indexed: source=%s chunks=%d index_id=%s",
            source, chunks_indexed, index_id,
        )
        return {"index_id": index_id, "chunks_indexed": chunks_indexed}

    async def search(
        self,
        query: str,
        modalities: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search the RAG index for relevant content."""
        results = []

        # Simple keyword search (in production, use vector similarity)
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for chunk_id, entry in self._index.items():
            # Modality filter
            if modalities:
                if not any(m in entry.get("modalities", []) for m in modalities):
                    continue

            content_lower = entry["content"].lower()
            match_count = sum(1 for w in query_words if w in content_lower)

            if match_count > 0:
                results.append({
                    **entry,
                    "relevance_score": match_count / max(len(query_words), 1),
                })

        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[:top_k]

    def _chunk_text(self, text: str, max_tokens: int = 500) -> List[str]:
        """Split text into chunks at sentence boundaries."""
        sentences = text.replace("\n", " ").split(". ")
        chunks = []
        current = []
        current_len = 0

        for sentence in sentences:
            words = len(sentence.split())
            if current_len + words > max_tokens and current:
                chunks.append(". ".join(current) + ".")
                current = []
                current_len = 0
            current.append(sentence)
            current_len += words

        if current:
            chunks.append(". ".join(current))

        return chunks

    async def _persist_index(
        self, index_id: str, chunks: int, source: str
    ) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO night_school_indexes (index_id, source, chunks_indexed, created_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT DO NOTHING
                    """,
                    index_id, source, chunks,
                )
        except Exception:
            pass
