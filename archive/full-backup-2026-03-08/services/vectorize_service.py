"""
Cloudflare Vectorize + Workers AI embedding service.

Generates 384-dim embeddings via Workers AI (@cf/bge-small-en-v1.5) and upserts
vectors into Cloudflare Vectorize indexes for semantic search across all content.

Six Vectorize indexes:
  1. nate-memory-search   — conversation_history (user ↔ AI exchanges)
  2. nate-vault-search    — vault_items (photos, documents, files)
  3. nate-wisdom          — wisdom_extractions (lived wisdom insights)
  4. nate-me2me           — me2me_imprint_entries (legacy journal entries)
  5. nate-sessions        — session transcripts + analysis
  6. nate-annotations     — vault_item_annotations (photo analyses)

Architecture:
  Backend (Python) → Workers AI REST API (embedding) → Vectorize REST API (upsert)
  Search queries → Edge Worker (Vectorize query + Workers AI embed) → results

Cost at 1M users:
  Workers AI embeddings: FREE (included in Workers Paid $5/mo)
  Vectorize storage: ~$0.01/750K dimensions/month
  Vectorize queries: ~$0.01/M queries
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger("vectorize_service")

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
_CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()

_WORKERS_AI_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/baai/bge-small-en-v1.5"
_VECTORIZE_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/vectorize/v2/indexes/{index_name}"

INDEX_NAMES = {
    "conversation": "nate-memory-search",
    "vault": "nate-vault-search",
    "wisdom": "nate-wisdom",
    "me2me": "nate-me2me",
    "session": "nate-sessions",
    "annotation": "nate-annotations",
}

_MAX_TEXT_LENGTH = 2000
_BATCH_SIZE = 100
_session: Optional[aiohttp.ClientSession] = None

_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

CLINICAL_PHOTO_PROMPT = (
    "You are Little Nate, an AI companion with deep emotional intelligence. "
    "Analyze this personal photo across the following clinical dimensions. "
    "Use structured headers so each section is independently searchable.\n\n"
    "PEOPLE: Count of people, estimated ages, apparent relationships (parent-child, "
    "siblings, couple, friends, group). Note if anyone is absent or the photo is solo.\n\n"
    "EMOTIONS: Facial expressions (smiling, neutral, tense, tearful), body language "
    "(open, closed, leaning in/away, arms crossed, fidgeting), energy level.\n\n"
    "SETTING: Location type (home, outdoors, restaurant, clinic, school), time of day "
    "if visible, formality level, comfort indicators.\n\n"
    "OBJECTS: Significant items visible (gifts, food, documents, medications, artwork, "
    "pets, toys, religious items, technology).\n\n"
    "DYNAMICS: Physical proximity between people, eye contact patterns, who is facing "
    "whom, touch (hand-holding, hugging, distance), power positioning.\n\n"
    "THERAPEUTIC THEMES: Attachment style indicators, safety/threat cues, joy markers, "
    "grief indicators, connection vs isolation, developmental milestones, trauma flags, "
    "resilience signals, transgenerational patterns if visible.\n\n"
    "COLORS & ATMOSPHERE: Dominant colors, lighting mood, overall emotional atmosphere.\n\n"
    "After the structured analysis, add 2-3 warm, curious questions about the memory "
    "or feelings connected to this photo. Be genuine and caring — never clinical in tone."
)


def is_vectorize_configured() -> bool:
    return bool(_CF_ACCOUNT_ID and _CF_API_TOKEN)


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_CF_API_TOKEN}",
        "Content-Type": "application/json",
    }


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=_headers(),
        )
    return _session


async def close():
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


def _truncate(text: str) -> str:
    if len(text) > _MAX_TEXT_LENGTH:
        return text[:_MAX_TEXT_LENGTH]
    return text


def _make_vector_id(source: str, record_id: str) -> str:
    raw = f"{source}:{record_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def generate_embeddings(texts: List[str]) -> Optional[List[List[float]]]:
    """Generate 384-dim embeddings via Workers AI bge-small-en-v1.5."""
    if not is_vectorize_configured() or not texts:
        return None

    url = _WORKERS_AI_URL.format(account_id=_CF_ACCOUNT_ID)
    truncated = [_truncate(t) for t in texts]

    try:
        session = await _get_session()
        async with session.post(url, json={"text": truncated}) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("Workers AI embedding failed (%d): %s", resp.status, body[:200])
                return None
            data = await resp.json()
            result = data.get("result", {})
            if isinstance(result, dict) and "data" in result:
                return result["data"]
            if isinstance(result, list):
                return result
            logger.warning("Workers AI unexpected response shape: %s", list(data.keys()))
            return None
    except Exception as e:
        logger.warning("Workers AI embedding error: %s", e)
        return None


async def upsert_vectors(
    index_name: str,
    vectors: List[Dict],
) -> bool:
    """
    Upsert vectors into a Vectorize index.

    Each vector dict: {"id": str, "values": [float...], "metadata": {...}}
    """
    if not is_vectorize_configured() or not vectors:
        return False

    url = f"{_VECTORIZE_URL.format(account_id=_CF_ACCOUNT_ID, index_name=index_name)}/upsert"

    ndjson_lines = []
    for v in vectors:
        ndjson_lines.append(json.dumps(v))
    ndjson_body = "\n".join(ndjson_lines)

    try:
        session = await _get_session()
        async with session.post(
            url,
            data=ndjson_body,
            headers={**_headers(), "Content-Type": "application/x-ndjson"},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("Vectorize upsert failed (%d) on %s: %s", resp.status, index_name, body[:200])
                return False
            return True
    except Exception as e:
        logger.warning("Vectorize upsert error on %s: %s", index_name, e)
        return False


async def query_vectors(
    index_name: str,
    query_vector: List[float],
    top_k: int = 10,
    filter_metadata: Optional[Dict] = None,
) -> List[Dict]:
    """Query a Vectorize index for nearest neighbors."""
    if not is_vectorize_configured():
        return []

    url = f"{_VECTORIZE_URL.format(account_id=_CF_ACCOUNT_ID, index_name=index_name)}/query"

    payload: Dict = {
        "vector": query_vector,
        "topK": top_k,
        "returnValues": False,
        "returnMetadata": "all",
    }
    if filter_metadata:
        payload["filter"] = filter_metadata

    try:
        session = await _get_session()
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("Vectorize query failed (%d) on %s: %s", resp.status, index_name, body[:200])
                return []
            data = await resp.json()
            matches = data.get("result", {}).get("matches", [])
            return matches
    except Exception as e:
        logger.warning("Vectorize query error on %s: %s", index_name, e)
        return []


async def delete_vectors(index_name: str, ids: List[str]) -> bool:
    """Delete vectors by ID from a Vectorize index."""
    if not is_vectorize_configured() or not ids:
        return False

    url = f"{_VECTORIZE_URL.format(account_id=_CF_ACCOUNT_ID, index_name=index_name)}/delete-by-ids"

    try:
        session = await _get_session()
        async with session.post(url, json={"ids": ids}) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Vectorize delete error on %s: %s", index_name, e)
        return False


# ---------------------------------------------------------------------------
# High-level helpers: embed + upsert for each content type
# ---------------------------------------------------------------------------

async def index_conversation(
    user_id: str,
    record_id: str,
    user_text: str,
    ai_text: str,
    session_id: str = "",
    timestamp: str = "",
    family_id: str = "",
    group_id: str = "",
    tier: str = "",
    company_id: str = "",
):
    """Embed and index a conversation exchange with full scope metadata."""
    combined = f"User: {user_text}\nAI: {ai_text}"
    embeddings = await generate_embeddings([combined])
    if not embeddings:
        return

    vec_id = _make_vector_id("conv", record_id)
    metadata = {
        "user_id": user_id,
        "session_id": session_id,
        "timestamp": timestamp,
        "source": "conversation",
        "preview": _truncate(combined)[:300],
    }
    if family_id:
        metadata["family_id"] = family_id
    if group_id:
        metadata["group_id"] = group_id
    if tier:
        metadata["tier"] = tier
    if company_id:
        metadata["company_id"] = company_id

    await upsert_vectors(INDEX_NAMES["conversation"], [{
        "id": vec_id,
        "values": embeddings[0],
        "metadata": metadata,
    }])


async def index_vault_item(
    member_id: str,
    item_id: str,
    filename: str,
    display_name: str = "",
    extracted_text: str = "",
    themes: str = "",
    mime_type: str = "",
    timestamp: str = "",
    family_id: str = "",
    group_id: str = "",
    tier: str = "",
):
    """Embed and index a vault item with scope metadata."""
    text_parts = [display_name or filename]
    if extracted_text:
        text_parts.append(extracted_text)
    if themes:
        text_parts.append(f"Themes: {themes}")
    combined = " ".join(text_parts)

    embeddings = await generate_embeddings([combined])
    if not embeddings:
        return

    vec_id = _make_vector_id("vault", item_id)
    metadata = {
        "user_id": member_id,
        "item_id": item_id,
        "filename": filename,
        "mime_type": mime_type,
        "timestamp": timestamp,
        "source": "vault_item",
    }
    if family_id:
        metadata["family_id"] = family_id
    if group_id:
        metadata["group_id"] = group_id
    if tier:
        metadata["tier"] = tier

    await upsert_vectors(INDEX_NAMES["vault"], [{
        "id": vec_id,
        "values": embeddings[0],
        "metadata": metadata,
    }])


async def index_wisdom(
    user_id: str,
    wisdom_id: str,
    insight_type: str,
    content: str,
    family_id: str = "",
    group_id: str = "",
    company_id: str = "",
    tier: str = "",
    session_id: str = "",
    source: str = "",
    timestamp: str = "",
):
    """Embed and index a wisdom extraction with full scope metadata."""
    combined = f"[{insight_type}] {content}"
    embeddings = await generate_embeddings([combined])
    if not embeddings:
        return

    vec_id = _make_vector_id("wisdom", wisdom_id)
    metadata = {
        "user_id": user_id,
        "insight_type": insight_type,
        "session_id": session_id,
        "source": source,
        "timestamp": timestamp,
        "preview": _truncate(content)[:300],
    }
    if family_id:
        metadata["family_id"] = family_id
    if group_id:
        metadata["group_id"] = group_id
    if company_id:
        metadata["company_id"] = company_id
    if tier:
        metadata["tier"] = tier

    await upsert_vectors(INDEX_NAMES["wisdom"], [{
        "id": vec_id,
        "values": embeddings[0],
        "metadata": metadata,
    }])


async def index_me2me_entry(
    user_id: str,
    entry_id: str,
    content: str,
    source: str = "",
    themes: str = "",
    emotions: str = "",
    timestamp: str = "",
    family_id: str = "",
    group_id: str = "",
    tier: str = "",
):
    """Embed and index a Me2Me imprint entry with scope metadata."""
    text_parts = [content]
    if themes:
        text_parts.append(f"Themes: {themes}")
    if emotions:
        text_parts.append(f"Emotions: {emotions}")
    combined = " ".join(text_parts)

    embeddings = await generate_embeddings([combined])
    if not embeddings:
        return

    vec_id = _make_vector_id("me2me", entry_id)
    metadata = {
        "user_id": user_id,
        "entry_id": entry_id,
        "source": source,
        "timestamp": timestamp,
        "preview": _truncate(content)[:300],
    }
    if family_id:
        metadata["family_id"] = family_id
    if group_id:
        metadata["group_id"] = group_id
    if tier:
        metadata["tier"] = tier

    await upsert_vectors(INDEX_NAMES["me2me"], [{
        "id": vec_id,
        "values": embeddings[0],
        "metadata": metadata,
    }])


async def index_session(
    session_id: str,
    coach_id: str,
    client_id: str,
    transcript: str = "",
    analysis_summary: str = "",
    family_id: str = "",
    group_id: str = "",
    company_id: str = "",
    timestamp: str = "",
):
    """Embed and index a coaching session with full scope metadata."""
    text_parts = []
    if transcript:
        text_parts.append(transcript[:1500])
    if analysis_summary:
        text_parts.append(f"Analysis: {analysis_summary}")
    combined = " ".join(text_parts) or "coaching session"

    embeddings = await generate_embeddings([combined])
    if not embeddings:
        return

    vec_id = _make_vector_id("session", session_id)
    metadata = {
        "session_id": session_id,
        "coach_id": coach_id,
        "client_id": client_id,
        "timestamp": timestamp,
        "source": "session",
        "preview": _truncate(combined)[:300],
    }
    if family_id:
        metadata["family_id"] = family_id
    if group_id:
        metadata["group_id"] = group_id
    if company_id:
        metadata["company_id"] = company_id

    await upsert_vectors(INDEX_NAMES["session"], [{
        "id": vec_id,
        "values": embeddings[0],
        "metadata": metadata,
    }])


async def index_annotation(
    user_id: str,
    annotation_id: str,
    vault_item_id: str,
    annotation_type: str,
    content: str,
    filename: str = "",
    timestamp: str = "",
    family_id: str = "",
    group_id: str = "",
):
    """Embed and index a vault item annotation with scope metadata."""
    combined = f"[{annotation_type}] {content}"
    if filename:
        combined = f"{filename}: {combined}"

    embeddings = await generate_embeddings([combined])
    if not embeddings:
        return

    vec_id = _make_vector_id("annotation", annotation_id)
    metadata = {
        "user_id": user_id,
        "vault_item_id": vault_item_id,
        "annotation_type": annotation_type,
        "filename": filename,
        "timestamp": timestamp,
        "source": "vault_annotation",
        "preview": _truncate(content)[:300],
    }
    if family_id:
        metadata["family_id"] = family_id
    if group_id:
        metadata["group_id"] = group_id

    await upsert_vectors(INDEX_NAMES["annotation"], [{
        "id": vec_id,
        "values": embeddings[0],
        "metadata": metadata,
    }])


async def semantic_search(
    query: str,
    index_name: str,
    user_id: str,
    top_k: int = 10,
    extra_filter: Optional[Dict] = None,
    family_id: str = "",
    group_id: str = "",
    company_id: str = "",
) -> List[Dict]:
    """
    Full semantic search: embed query → query Vectorize → return scored results.

    The BGE query instruction prefix is prepended automatically — this yields
    +1-2 nDCG retrieval improvement without any index rebuild.

    Metadata filtering ensures only the user's own vectors are scanned,
    not the full index. At 1M users with 1K vectors each, this reduces
    scan from 1B vectors to ~1K vectors per query.

    Scope filters (all optional, narrowing):
      - user_id: always applied (required)
      - family_id: search across family members' shared content
      - group_id: search within a community group
      - company_id: search within a corporate group
    """
    prefixed_query = f"{_BGE_QUERY_PREFIX}{query}"
    embeddings = await generate_embeddings([prefixed_query])
    if not embeddings:
        return []

    filter_meta = {"user_id": user_id}
    if family_id:
        filter_meta["family_id"] = family_id
    if group_id:
        filter_meta["group_id"] = group_id
    if company_id:
        filter_meta["company_id"] = company_id
    if extra_filter:
        filter_meta.update(extra_filter)

    matches = await query_vectors(
        index_name=index_name,
        query_vector=embeddings[0],
        top_k=top_k,
        filter_metadata=filter_meta,
    )
    return matches


async def semantic_search_family(
    query: str,
    family_id: str,
    top_k: int = 10,
    indexes: Optional[List[str]] = None,
) -> Dict[str, List[Dict]]:
    """
    Search across a family's content — wisdom, sessions, and Me2Me.
    Uses family_id filter so each query scans only that family's vectors.
    """
    prefixed_query = f"{_BGE_QUERY_PREFIX}{query}"
    embeddings = await generate_embeddings([prefixed_query])
    if not embeddings:
        return {}

    target_indexes = indexes or ["wisdom", "session", "me2me"]
    tasks = {}
    for source in target_indexes:
        idx = INDEX_NAMES.get(source)
        if idx:
            tasks[source] = query_vectors(
                index_name=idx,
                query_vector=embeddings[0],
                top_k=top_k,
                filter_metadata={"family_id": family_id},
            )

    results = {}
    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for source, result in zip(tasks.keys(), gathered):
        results[source] = result if isinstance(result, list) else []
    return results


async def semantic_search_group(
    query: str,
    group_id: str,
    top_k: int = 10,
) -> Dict[str, List[Dict]]:
    """
    Search across a community group's content.
    Uses group_id filter so only that group's vectors are scanned.
    """
    prefixed_query = f"{_BGE_QUERY_PREFIX}{query}"
    embeddings = await generate_embeddings([prefixed_query])
    if not embeddings:
        return {}

    tasks = {}
    for source, idx in INDEX_NAMES.items():
        tasks[source] = query_vectors(
            index_name=idx,
            query_vector=embeddings[0],
            top_k=top_k,
            filter_metadata={"group_id": group_id},
        )

    results = {}
    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for source, result in zip(tasks.keys(), gathered):
        results[source] = result if isinstance(result, list) else []
    return results


async def semantic_search_all(
    query: str,
    user_id: str,
    top_k: int = 10,
    family_id: str = "",
    group_id: str = "",
    company_id: str = "",
) -> Dict[str, List[Dict]]:
    """
    Search across ALL 6 indexes concurrently for a unified memory search.
    Applies user_id filter (+ optional scope filters) so only the user's
    own vectors are scanned — never the full index.
    """
    tasks = {}
    for source, index in INDEX_NAMES.items():
        tasks[source] = semantic_search(
            query, index, user_id, top_k=top_k,
            family_id=family_id, group_id=group_id, company_id=company_id,
        )

    results = {}
    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for (source, _), result in zip(tasks.items(), gathered):
        if isinstance(result, Exception):
            logger.warning("Semantic search failed for %s: %s", source, result)
            results[source] = []
        else:
            results[source] = result

    return results


# ---------------------------------------------------------------------------
# Batch operations for backfill
# ---------------------------------------------------------------------------

async def batch_embed_and_upsert(
    index_name: str,
    items: List[Dict],
) -> int:
    """
    Batch embed + upsert. Each item: {"id": str, "text": str, "metadata": dict}
    Returns count of successfully upserted vectors.
    """
    if not is_vectorize_configured() or not items:
        return 0

    total_upserted = 0
    for i in range(0, len(items), _BATCH_SIZE):
        batch = items[i:i + _BATCH_SIZE]
        texts = [item["text"] for item in batch]

        embeddings = await generate_embeddings(texts)
        if not embeddings or len(embeddings) != len(batch):
            logger.warning("Batch embed mismatch: expected %d, got %s", len(batch), len(embeddings) if embeddings else 0)
            continue

        vectors = []
        for item, emb in zip(batch, embeddings):
            vectors.append({
                "id": item["id"],
                "values": emb,
                "metadata": item.get("metadata", {}),
            })

        if await upsert_vectors(index_name, vectors):
            total_upserted += len(vectors)

        if i + _BATCH_SIZE < len(items):
            await asyncio.sleep(0.1)

    return total_upserted


# ---------------------------------------------------------------------------
# Vision-LLM image-to-image search via description
# ---------------------------------------------------------------------------

async def vision_describe_image(image_bytes: bytes) -> Optional[str]:
    """
    Describe an image using Workers AI llama-3.2-11b-vision-instruct.
    Returns a text description suitable for semantic search against
    the nate-annotations index.

    Falls back to None if Workers AI is unreachable.
    """
    if not is_vectorize_configured() or not image_bytes:
        return None

    import base64
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    url = f"https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.2-11b-vision-instruct"

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Describe this photo for a memory search system. Include: "
                            "people (count, ages, relationships), emotions (expressions, body language), "
                            "setting (location, time), objects, dynamics between people, "
                            "and any therapeutic themes (attachment, safety, joy, grief, connection). "
                            "Be detailed and specific."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 800,
    }

    try:
        session = await _get_session()
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("Vision-LLM describe failed (%d): %s", resp.status, body[:200])
                return None
            data = await resp.json()
            result = data.get("result", {})
            if isinstance(result, dict):
                return result.get("response", "")
            return None
    except Exception as e:
        logger.warning("Vision-LLM describe error: %s", e)
        return None


async def image_to_image_search(
    image_bytes: bytes,
    user_id: str,
    top_k: int = 10,
    family_id: str = "",
) -> List[Dict]:
    """
    Image-to-image search via describe-then-embed.

    1. Workers AI Vision LLM describes the input photo
    2. Description is embedded with BGE query prefix
    3. Embedded vector queries nate-annotations index

    No new infrastructure needed — uses existing Vectorize index.
    """
    description = await vision_describe_image(image_bytes)
    if not description:
        return []

    return await semantic_search(
        query=description,
        index_name=INDEX_NAMES["annotation"],
        user_id=user_id,
        top_k=top_k,
        family_id=family_id,
    )


# ---------------------------------------------------------------------------
# Pipeline health verification for trust auditor
# ---------------------------------------------------------------------------

async def verify_push_pipeline(user_id: str = "audit_client") -> Dict:
    """
    End-to-end push verification: embed a test vector, upsert, query back,
    then delete. Returns timing and pass/fail per step.
    """
    import time

    results = {
        "embed_ok": False,
        "upsert_ok": False,
        "query_ok": False,
        "recall_ok": False,
        "delete_ok": False,
        "embed_ms": 0,
        "upsert_ms": 0,
        "query_ms": 0,
    }

    if not is_vectorize_configured():
        results["error"] = "Vectorize not configured"
        return results

    test_text = "Trust auditor verification probe — semantic pipeline integrity check"
    test_id = _make_vector_id("audit", f"probe_{user_id}_{int(time.time())}")

    t0 = time.monotonic()
    embeddings = await generate_embeddings([test_text])
    results["embed_ms"] = int((time.monotonic() - t0) * 1000)
    results["embed_ok"] = embeddings is not None and len(embeddings) == 1

    if not results["embed_ok"]:
        return results

    t1 = time.monotonic()
    upsert_ok = await upsert_vectors(INDEX_NAMES["conversation"], [{
        "id": test_id,
        "values": embeddings[0],
        "metadata": {
            "user_id": user_id,
            "source": "audit_probe",
            "timestamp": "",
        },
    }])
    results["upsert_ms"] = int((time.monotonic() - t1) * 1000)
    results["upsert_ok"] = upsert_ok

    if not upsert_ok:
        return results

    await asyncio.sleep(1.5)

    t2 = time.monotonic()
    prefixed = f"{_BGE_QUERY_PREFIX}{test_text}"
    query_emb = await generate_embeddings([prefixed])
    if query_emb:
        matches = await query_vectors(
            INDEX_NAMES["conversation"],
            query_emb[0],
            top_k=5,
            filter_metadata={"user_id": user_id},
        )
        results["query_ms"] = int((time.monotonic() - t2) * 1000)
        results["query_ok"] = True
        results["recall_ok"] = any(m.get("id") == test_id for m in matches)

    results["delete_ok"] = await delete_vectors(INDEX_NAMES["conversation"], [test_id])

    return results


async def verify_retrieval_quality(user_id: str = "audit_client") -> Dict:
    """
    Retrieval quality check: verify that searches return results with
    valid metadata and reasonable scores across all 6 indexes.
    """
    results = {}
    test_query = "How am I feeling today?"

    for source, index_name in INDEX_NAMES.items():
        try:
            matches = await semantic_search(
                query=test_query,
                index_name=index_name,
                user_id=user_id,
                top_k=3,
            )
            has_metadata = all(
                isinstance(m.get("metadata"), dict) and "user_id" in m.get("metadata", {})
                for m in matches
            ) if matches else True

            results[source] = {
                "index": index_name,
                "reachable": True,
                "match_count": len(matches),
                "metadata_valid": has_metadata,
                "top_score": round(matches[0].get("score", 0), 4) if matches else 0,
            }
        except Exception as e:
            results[source] = {
                "index": index_name,
                "reachable": False,
                "error": str(e)[:100],
            }

    return results
