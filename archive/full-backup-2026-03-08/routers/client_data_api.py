"""
Client Data API — REST endpoints for client sub-screens.
Replaces WebSocket-based data fetching that fails on mobile Safari.
Covers: Memory Search, Family Members, Coach Info.
"""

import json
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import get_current_user_id
from app.services.api_server import get_current_user as _require_auth

logger = logging.getLogger("client_data_api")

router = APIRouter(prefix="/api/client", tags=["client_data"], dependencies=[Depends(_require_auth)])

_DATA_ROOT = Path(os.environ.get("DATA_DIR", "/app/data"))
_VAULT_ROOT = _DATA_ROOT / "Vaults"


def _memory_path(hw_id: str, role: str = "CLIENT") -> Path:
    """Path to memory.json. JSON is backup only — PostgreSQL conversation_history is primary."""
    folder = "Clients"
    if role == "COACH":
        folder = "Coaches"
    elif role == "ADMIN":
        folder = "Admin"
    return _VAULT_ROOT / folder / hw_id / "memory.json"


@router.get("/health-check")
async def client_health_check(
    hw_id: str = "",
    request: Request = None,
):
    """
    Login-time sync verification: vault folders, conversation history readiness.
    Called by Flutter immediately after WebSocket login_success.
    Returns: vault_ready, memory_ready, needs_backfill.
    No hard block on login — verification only.
    """
    if not hw_id or not hw_id.strip():
        return {"vault_ready": False, "memory_ready": False, "needs_backfill": False,
                "server_entry_count": 0, "last_server_entry_at": None}
    hw_id = hw_id.strip()
    vault_ready = False
    memory_ready = False
    needs_backfill = False
    server_entry_count = 0
    last_server_entry_at = None

    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT COUNT(*) AS cnt,
                              MAX(created_at) AS last_at
                       FROM conversation_history WHERE user_id = $1""",
                    hw_id,
                )
                server_entry_count = (row["cnt"] or 0) if row else 0
                memory_ready = server_entry_count >= 1
                if row and row["last_at"]:
                    last_server_entry_at = row["last_at"].isoformat()

                from app.services.vault.vault_operations import VaultOperations
                vault_ops = VaultOperations(db_pool)
                folders = await vault_ops.get_folder_tree(hw_id)
                vault_ready = len(folders) > 0
                if not vault_ready:
                    urow = await conn.fetchrow(
                        "SELECT tier, profile_data FROM users WHERE hardware_id = $1",
                        hw_id,
                    )
                    tier = "STANDARD"
                    if urow:
                        pd = urow["profile_data"] or {}
                        if isinstance(pd, dict):
                            tier = pd.get("tier") or pd.get("subscription_plan") or "STANDARD"
                    await vault_ops.create_default_folders(hw_id, tier)
                    folders = await vault_ops.get_folder_tree(hw_id)
                    vault_ready = len(folders) > 0
            if not memory_ready:
                mem_path = _memory_path(hw_id)
                if mem_path.exists():
                    try:
                        raw = mem_path.read_text()
                        entries = json.loads(raw) if raw.strip() else []
                        needs_backfill = len(entries) > 0
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("client_health_check failed: %s", e)

    return {
        "vault_ready": vault_ready,
        "memory_ready": memory_ready,
        "needs_backfill": needs_backfill,
        "server_entry_count": server_entry_count,
        "last_server_entry_at": last_server_entry_at,
    }


@router.post("/history/push")
async def push_device_history(request: Request):
    """
    Accept conversation history entries from the client device.
    Deduplicates via (user_id, created_at, left(user_text, 100)).
    Max 200 entries per request to prevent timeouts.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    hw_id = (body.get("hw_id") or "").strip()
    entries = body.get("entries") or []
    if not hw_id:
        raise HTTPException(400, "hw_id required")
    if not entries:
        return {"inserted": 0, "skipped": 0}
    if len(entries) > 200:
        entries = entries[:200]

    inserted = 0
    skipped = 0
    async with db_pool.acquire() as conn:
        for e in entries:
            user_text = (e.get("user_text") or "").strip()
            ai_text = (e.get("ai_text") or "").strip()
            created_at = e.get("created_at")
            session_id = e.get("session_id") or ""
            if not user_text or not ai_text or not created_at:
                skipped += 1
                continue
            try:
                result = await conn.execute(
                    """INSERT INTO conversation_history
                       (user_id, session_id, user_text, ai_text,
                        word_count_user, word_count_ai, created_at)
                       SELECT $1, $2, $3, $4, $5, $6, $7::timestamptz
                       WHERE NOT EXISTS (
                         SELECT 1 FROM conversation_history
                         WHERE user_id = $1
                           AND created_at = $7::timestamptz
                           AND LEFT(user_text, 100) = LEFT($3, 100)
                       )""",
                    hw_id, session_id, user_text, ai_text,
                    len(user_text.split()), len(ai_text.split()),
                    created_at,
                )
                if result and "INSERT 0 1" in result:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning("history/push insert failed: %s", exc)
                skipped += 1

    logger.info("history/push %s: inserted=%d skipped=%d", hw_id, inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


@router.post("/history/integrity")
async def history_integrity_check(request: Request):
    """Compare device vs server conversation history counts for sync."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    hw_id = (body.get("hw_id") or "").strip()
    local_count = int(body.get("local_count", 0))
    last_entry_at = body.get("last_entry_at")
    if not hw_id:
        raise HTTPException(400, "hw_id required")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*)::int as cnt, MAX(created_at) as last_at "
            "FROM conversation_history WHERE user_id = $1",
            hw_id,
        )
    server_count = row["cnt"] if row else 0
    last_server_at = row["last_at"].isoformat() if row and row["last_at"] else None

    device_ahead = max(0, local_count - server_count)
    server_ahead = max(0, server_count - local_count)

    return {
        "server_count": server_count,
        "last_server_entry_at": last_server_at,
        "local_count": local_count,
        "device_ahead": device_ahead,
        "server_ahead": server_ahead,
        "in_sync": device_ahead == 0 and server_ahead == 0,
    }


@router.get("/history/pull")
async def pull_server_history(
    hw_id: str = "",
    after: str = "",
    limit: int = 200,
    request: Request = None,
):
    """Return conversation history entries from server that the device may be missing.
    `after` is an ISO timestamp; returns entries created after that time."""
    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    hw_id = hw_id.strip()
    if not hw_id:
        raise HTTPException(400, "hw_id required")
    limit = min(limit, 500)

    async with db_pool.acquire() as conn:
        if after:
            rows = await conn.fetch(
                "SELECT session_id, user_text, ai_text, created_at "
                "FROM conversation_history "
                "WHERE user_id = $1 AND created_at > $2::timestamptz "
                "ORDER BY created_at ASC LIMIT $3",
                hw_id, after, limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT session_id, user_text, ai_text, created_at "
                "FROM conversation_history "
                "WHERE user_id = $1 "
                "ORDER BY created_at ASC LIMIT $2",
                hw_id, limit,
            )

    from app.services.pii_cipher import decrypt_pii
    entries = []
    for r in rows:
        u = r["user_text"] or ""
        a = r["ai_text"] or ""
        try:
            u = decrypt_pii(u)
        except Exception:
            pass
        try:
            a = decrypt_pii(a)
        except Exception:
            pass
        entries.append({
            "session_id": r["session_id"] or "",
            "user_text": u,
            "ai_text": a,
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
        })

    return {
        "hw_id": hw_id,
        "count": len(entries),
        "entries": entries,
    }


@router.get("/history/range")
async def history_by_range(
    hw_id: str = "",
    range: str = "today",
    limit: int = 200,
    request: Request = None,
):
    """Return conversation entries for a time window (today/week/month/all).
    Includes photo annotations from vault_item_annotations if available."""
    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    hw_id = hw_id.strip()
    if not hw_id:
        raise HTTPException(400, "hw_id required")
    limit = min(limit, 1000)

    interval_map = {
        "today": "1 day",
        "week": "7 days",
        "month": "30 days",
        "quarter": "90 days",
        "year": "365 days",
    }
    interval = interval_map.get(range)

    async with db_pool.acquire() as conn:
        if interval:
            rows = await conn.fetch(
                "SELECT session_id, user_text, ai_text, created_at "
                "FROM conversation_history "
                "WHERE user_id = $1 AND created_at >= NOW() - $2::interval "
                "ORDER BY created_at DESC LIMIT $3",
                hw_id, interval, limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT session_id, user_text, ai_text, created_at "
                "FROM conversation_history "
                "WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                hw_id, limit,
            )

        photo_annotations = []
        try:
            tbl_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'vault_item_annotations')"
            )
            if tbl_exists:
                if interval:
                    photo_annotations = await conn.fetch(
                        "SELECT a.vault_item_id, a.annotation_type, a.content, a.created_at "
                        "FROM vault_item_annotations a "
                        "JOIN vault_items v ON v.id = a.vault_item_id "
                        "WHERE v.user_id = $1 AND a.created_at >= NOW() - $2::interval "
                        "ORDER BY a.created_at DESC LIMIT 50",
                        hw_id, interval,
                    )
                else:
                    photo_annotations = await conn.fetch(
                        "SELECT a.vault_item_id, a.annotation_type, a.content, a.created_at "
                        "FROM vault_item_annotations a "
                        "JOIN vault_items v ON v.id = a.vault_item_id "
                        "WHERE v.user_id = $1 ORDER BY a.created_at DESC LIMIT 50",
                        hw_id,
                    )
        except Exception:
            pass

    from app.services.pii_cipher import decrypt_pii
    entries = []
    for r in rows:
        u = r["user_text"] or ""
        a = r["ai_text"] or ""
        try:
            u = decrypt_pii(u)
        except Exception:
            pass
        try:
            a = decrypt_pii(a)
        except Exception:
            pass
        entries.append({
            "session_id": r["session_id"] or "",
            "user_text": u,
            "ai_text": a,
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
        })

    annotations = []
    for pa in photo_annotations:
        annotations.append({
            "vault_item_id": str(pa["vault_item_id"]) if pa["vault_item_id"] else "",
            "type": pa["annotation_type"] or "",
            "content": pa["content"] or "",
            "created_at": pa["created_at"].isoformat() if pa["created_at"] else "",
        })

    return {
        "hw_id": hw_id,
        "range": range,
        "count": len(entries),
        "entries": entries,
        "photo_annotations": annotations,
    }


@router.get("/memory/search/{hw_id}")
async def memory_search(
    hw_id: str,
    q: str = "",
    limit: int = 30,
    request: Request = None,
):
    """
    Unified search across conversation_history, vault_items, and
    vault_item_annotations. Returns matches with source tags,
    previews, and relevance scores. PostgreSQL-first, JSON fallback
    for conversation data.
    """
    query = q.strip().lower()
    if not query:
        return {"query": "", "total_matches": 0, "results": [], "sources_searched": []}

    limit = min(limit, 50)
    matches = []
    sources_searched = []

    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            from app.services.pii_cipher import decrypt_pii
        except ImportError:
            decrypt_pii = lambda x: x

        # --- 1. conversation_history (PG FTS) ---
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT user_text, ai_text, session_id, created_at,
                           ts_rank(to_tsvector('english', user_text || ' ' || ai_text),
                                   plainto_tsquery('english', $2::text)) AS rank
                    FROM conversation_history
                    WHERE user_id = $1
                      AND to_tsvector('english', user_text || ' ' || ai_text) @@ plainto_tsquery('english', $2::text)
                    ORDER BY rank DESC NULLS LAST, created_at DESC
                    LIMIT $3
                    """,
                    hw_id,
                    query,
                    limit,
                )
                for r in rows:
                    user_raw = decrypt_pii(r["user_text"] or "")
                    ai_raw = decrypt_pii(r["ai_text"] or "")
                    ts = r["created_at"].isoformat() if r["created_at"] else ""
                    matches.append({
                        "source": "conversation",
                        "timestamp": ts,
                        "session_id": r["session_id"],
                        "session_date": ts[:10] if ts else "",
                        "user_preview": user_raw[:200] + ("..." if len(user_raw) > 200 else ""),
                        "ai_preview": ai_raw[:200] + ("..." if len(ai_raw) > 200 else ""),
                        "user_full": user_raw,
                        "ai_full": ai_raw,
                        "relevance": float(r["rank"]) if r["rank"] else 0,
                    })
                sources_searched.append("conversation_history")
        except Exception as e:
            logger.warning("memory_search conversation_history failed: %s", e)

        # --- 2. vault_items (search_vector + filename) ---
        try:
            async with db_pool.acquire() as conn:
                vault_rows = await conn.fetch(
                    """
                    SELECT id, filename, display_name, mime_type, themes,
                           extracted_text_preview, created_at,
                           ts_rank(search_vector, plainto_tsquery('english', $2::text)) AS rank
                    FROM vault_items
                    WHERE member_id = $1
                      AND (
                        search_vector @@ plainto_tsquery('english', $2::text)
                        OR LOWER(filename) LIKE '%' || LOWER($2::text) || '%'
                        OR LOWER(display_name) LIKE '%' || LOWER($2::text) || '%'
                      )
                    ORDER BY rank DESC NULLS LAST, created_at DESC
                    LIMIT $3
                    """,
                    hw_id,
                    query,
                    limit,
                )
                for r in vault_rows:
                    fname = r["display_name"] or r["filename"] or "unnamed"
                    ts = r["created_at"].isoformat() if r["created_at"] else ""
                    themes_str = ""
                    if r["themes"]:
                        try:
                            _th = r["themes"] if isinstance(r["themes"], list) else json.loads(r["themes"])
                            themes_str = ", ".join(str(t) for t in _th[:5])
                        except Exception:
                            pass
                    matches.append({
                        "source": "vault_item",
                        "timestamp": ts,
                        "session_date": ts[:10] if ts else "",
                        "vault_item_id": str(r["id"]),
                        "filename": fname,
                        "mime_type": r["mime_type"] or "",
                        "themes": themes_str,
                        "user_preview": f"[Vault: {fname}]",
                        "ai_preview": (r["extracted_text_preview"] or "")[:200],
                        "relevance": float(r["rank"]) if r["rank"] else 0.1,
                    })
                sources_searched.append("vault_items")
        except Exception as e:
            logger.warning("memory_search vault_items failed: %s", e)

        # --- 3. vault_item_annotations (photo analyses) ---
        try:
            async with db_pool.acquire() as conn:
                ann_rows = await conn.fetch(
                    """
                    SELECT a.id, a.vault_item_id, a.annotation_type, a.content,
                           a.created_at, vi.filename, vi.display_name
                    FROM vault_item_annotations a
                    LEFT JOIN vault_items vi ON a.vault_item_id = vi.id
                    WHERE a.user_id = $1
                      AND (
                        to_tsvector('english', a.content) @@ plainto_tsquery('english', $2::text)
                        OR LOWER(a.content) LIKE '%' || LOWER($2::text) || '%'
                      )
                    ORDER BY a.created_at DESC
                    LIMIT $3
                    """,
                    hw_id,
                    query,
                    limit,
                )
                for r in ann_rows:
                    fname = r["display_name"] or r["filename"] or "photo"
                    ts = r["created_at"].isoformat() if r["created_at"] else ""
                    matches.append({
                        "source": "vault_annotation",
                        "timestamp": ts,
                        "session_date": ts[:10] if ts else "",
                        "vault_item_id": str(r["vault_item_id"]),
                        "filename": fname,
                        "annotation_type": r["annotation_type"],
                        "user_preview": f"[Photo Analysis: {fname}]",
                        "ai_preview": (r["content"] or "")[:200],
                        "relevance": 0.5,
                    })
                sources_searched.append("vault_item_annotations")
        except Exception as e:
            logger.warning("memory_search vault_item_annotations failed: %s", e)

        # --- 4. Vectorize semantic search (enriches FTS results) ---
        try:
            from app.services.vectorize_service import semantic_search_all, is_vectorize_configured
            if is_vectorize_configured():
                semantic_results = await semantic_search_all(query, hw_id, top_k=limit)
                seen_ids = {m.get("session_id", "") + m.get("vault_item_id", "") for m in matches if m.get("session_id") or m.get("vault_item_id")}
                for src, hits in semantic_results.items():
                    for hit in hits:
                        meta = hit.get("metadata", {})
                        score = hit.get("score", 0)
                        preview = meta.get("preview", "")
                        dedup_key = meta.get("session_id", "") + meta.get("item_id", "") + meta.get("entry_id", "")
                        if dedup_key and dedup_key in seen_ids:
                            continue
                        if dedup_key:
                            seen_ids.add(dedup_key)
                        matches.append({
                            "source": meta.get("source", src),
                            "timestamp": meta.get("timestamp", ""),
                            "session_id": meta.get("session_id", ""),
                            "session_date": meta.get("timestamp", "")[:10] if meta.get("timestamp") else "",
                            "user_preview": preview[:200] if preview else "",
                            "ai_preview": "",
                            "filename": meta.get("filename", ""),
                            "vault_item_id": meta.get("vault_item_id", meta.get("item_id", "")),
                            "annotation_type": meta.get("annotation_type", ""),
                            "relevance": float(score),
                            "search_type": "semantic",
                        })
                sources_searched.append("vectorize_semantic")
        except Exception as e:
            logger.warning("memory_search vectorize semantic failed: %s", e)

        if matches:
            matches.sort(key=lambda x: x.get("relevance", 0), reverse=True)
            return {
                "query": query,
                "total_matches": len(matches),
                "results": matches[:limit],
                "sources_searched": sources_searched,
            }

    # JSON fallback (conversation data only)
    mem_path = _memory_path(hw_id)
    if not mem_path.exists():
        return {"query": query, "total_matches": 0, "results": [], "sources_searched": ["json_file"]}

    try:
        raw = mem_path.read_text()
        all_entries = json.loads(raw) if raw.strip() else []
    except Exception:
        raise HTTPException(500, "Failed to read memory")

    json_matches = []
    for idx, entry in enumerate(all_entries):
        user_text = (entry.get("user") or "").lower()
        ai_text = (entry.get("ai") or "").lower()
        if query in user_text or query in ai_text:
            user_raw = entry.get("user", "")
            ai_raw = entry.get("ai", "")
            ts = entry.get("timestamp", "")
            json_matches.append({
                "source": "conversation",
                "timestamp": ts,
                "session_id": entry.get("session_id"),
                "session_date": ts[:10] if ts else "",
                "user_preview": user_raw[:200] + ("..." if len(user_raw) > 200 else ""),
                "ai_preview": ai_raw[:200] + ("..." if len(ai_raw) > 200 else ""),
                "user_full": user_raw,
                "ai_full": ai_raw,
            })

    json_matches.reverse()
    return {
        "query": query,
        "total_matches": len(json_matches),
        "results": json_matches[:limit],
        "sources_searched": ["json_file"],
    }


@router.get("/memory/semantic-search/{hw_id}")
async def semantic_memory_search(
    hw_id: str,
    q: str = "",
    limit: int = 20,
    index: str = "all",
    request: Request = None,
):
    """
    Pure semantic search across all Vectorize indexes.
    Finds conceptually related content even without keyword matches.
    """
    query = q.strip()
    if not query:
        return {"query": "", "total_matches": 0, "results": [], "search_type": "semantic"}

    limit = min(limit, 50)
    try:
        from app.services.vectorize_service import (
            semantic_search, semantic_search_all, is_vectorize_configured, INDEX_NAMES,
        )
        if not is_vectorize_configured():
            return {"query": query, "total_matches": 0, "results": [], "search_type": "semantic",
                    "error": "Vectorize not configured"}

        if index == "all":
            all_results = await semantic_search_all(query, hw_id, top_k=limit)
            combined = []
            for src, hits in all_results.items():
                for hit in hits:
                    meta = hit.get("metadata", {})
                    combined.append({
                        "source": meta.get("source", src),
                        "score": hit.get("score", 0),
                        "preview": meta.get("preview", ""),
                        "timestamp": meta.get("timestamp", ""),
                        "session_id": meta.get("session_id", ""),
                        "filename": meta.get("filename", ""),
                        "vault_item_id": meta.get("item_id", meta.get("vault_item_id", "")),
                        "insight_type": meta.get("insight_type", ""),
                        "annotation_type": meta.get("annotation_type", ""),
                    })
            combined.sort(key=lambda x: x.get("score", 0), reverse=True)
            return {
                "query": query,
                "total_matches": len(combined),
                "results": combined[:limit],
                "search_type": "semantic",
            }
        else:
            idx_name = INDEX_NAMES.get(index)
            if not idx_name:
                return {"query": query, "total_matches": 0, "results": [],
                        "error": f"Unknown index: {index}"}
            hits = await semantic_search(query, idx_name, hw_id, top_k=limit)
            results = []
            for hit in hits:
                meta = hit.get("metadata", {})
                results.append({
                    "source": meta.get("source", index),
                    "score": hit.get("score", 0),
                    "preview": meta.get("preview", ""),
                    "timestamp": meta.get("timestamp", ""),
                    "metadata": meta,
                })
            return {
                "query": query,
                "total_matches": len(results),
                "results": results[:limit],
                "search_type": "semantic",
                "index": index,
            }
    except Exception as e:
        logger.warning("semantic_memory_search failed: %s", e)
        return {"query": query, "total_matches": 0, "results": [], "search_type": "semantic",
                "error": str(e)}


@router.post("/memory/image-search/{hw_id}")
async def image_based_memory_search(
    hw_id: str,
    request: Request,
):
    """
    Image-to-image semantic search via Workers AI Vision LLM.
    Accepts a base64-encoded JPEG image and finds similar photos in the vault
    by describing the image and searching the nate-annotations Vectorize index.

    Body: {"image_b64": str, "top_k": int (optional, default 10)}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    image_b64 = (body.get("image_b64") or "").strip()
    if not image_b64:
        raise HTTPException(400, "image_b64 required")

    import base64
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 image data")

    top_k = min(int(body.get("top_k", 10)), 30)

    try:
        from app.services.vectorize_service import image_to_image_search, is_vectorize_configured
        if not is_vectorize_configured():
            return {"query": "image", "total_matches": 0, "results": [],
                    "search_type": "image_semantic", "error": "Vectorize not configured"}

        matches = await image_to_image_search(
            image_bytes=image_bytes,
            user_id=hw_id,
            top_k=top_k,
        )

        results = []
        for hit in matches:
            meta = hit.get("metadata", {})
            results.append({
                "source": "vault_annotation",
                "score": hit.get("score", 0),
                "vault_item_id": meta.get("vault_item_id", ""),
                "filename": meta.get("filename", ""),
                "annotation_type": meta.get("annotation_type", ""),
                "preview": meta.get("preview", ""),
                "timestamp": meta.get("timestamp", ""),
            })

        return {
            "query": "image_similarity",
            "total_matches": len(results),
            "results": results,
            "search_type": "image_semantic",
        }
    except Exception as e:
        logger.warning("image_based_memory_search failed: %s", e)
        return {"query": "image", "total_matches": 0, "results": [],
                "search_type": "image_semantic", "error": str(e)}


@router.get("/memory/sessions/{hw_id}")
async def memory_sessions(
    hw_id: str,
    request: Request = None,
):
    """Return memory entries grouped by session/date as story chapters.
    PostgreSQL-first (conversation_history), JSON fallback."""
    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_text, ai_text, session_id, created_at "
                    "FROM conversation_history WHERE user_id = $1 ORDER BY created_at ASC",
                    hw_id,
                )
                from app.services.pii_cipher import decrypt_pii
                sessions: OrderedDict = OrderedDict()
                for r in rows:
                    key = r["session_id"] or (r["created_at"].isoformat()[:10] if r["created_at"] else "unknown")
                    if not key:
                        key = "unknown"
                    if key not in sessions:
                        sessions[key] = []
                    ts = r["created_at"].isoformat() if r["created_at"] else ""
                    sessions[key].append({
                        "timestamp": ts,
                        "user": decrypt_pii(r["user_text"] or ""),
                        "ai": decrypt_pii(r["ai_text"] or ""),
                    })

                result = []
                for key, entries in sessions.items():
                    first_ts = entries[0]["timestamp"] if entries else ""
                    last_ts = entries[-1]["timestamp"] if entries else ""
                    first_user = (entries[0].get("user", "") or "")[:120] if entries else ""
                    result.append({
                        "session_key": key,
                        "date": first_ts[:10] if first_ts else key,
                        "first_timestamp": first_ts,
                        "last_timestamp": last_ts,
                        "entry_count": len(entries),
                        "preview": first_user + ("..." if len(first_user) >= 120 else ""),
                        "entries": [
                            {"timestamp": e["timestamp"], "user": e["user"], "ai": e["ai"]}
                            for e in entries
                        ],
                    })

                result.reverse()
                return {"sessions": result, "total_sessions": len(result)}
        except Exception as e:
            logger.warning("memory_sessions PG lookup failed, falling back to JSON: %s", e)

    # JSON fallback
    mem_path = _memory_path(hw_id)
    if not mem_path.exists():
        return {"sessions": [], "total_sessions": 0}

    try:
        raw = mem_path.read_text()
        all_entries = json.loads(raw) if raw.strip() else []
    except Exception:
        raise HTTPException(500, "Failed to read memory")

    sessions = OrderedDict()
    for entry in all_entries:
        key = entry.get("session_id") or entry.get("timestamp", "")[:10]
        if not key:
            key = "unknown"
        if key not in sessions:
            sessions[key] = []
        sessions[key].append(entry)

    result = []
    for key, entries in sessions.items():
        first_ts = entries[0].get("timestamp", "") if entries else ""
        last_ts = entries[-1].get("timestamp", "") if entries else ""
        first_user = (entries[0].get("user", "") or "")[:120] if entries else ""
        result.append({
            "session_key": key,
            "date": first_ts[:10] if first_ts else key,
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "entry_count": len(entries),
            "preview": first_user + ("..." if len(first_user) >= 120 else ""),
            "entries": [
                {
                    "timestamp": e.get("timestamp", ""),
                    "user": e.get("user", ""),
                    "ai": e.get("ai", ""),
                }
                for e in entries
            ],
        })

    result.reverse()
    return {"sessions": result, "total_sessions": len(result)}


@router.get("/family/members/{hw_id}")
async def get_family_members(
    hw_id: str,
    request: Request = None,
):
    """
    Get family members and pending invites for a client's family.
    PG-first: queries the users table for family_id match.
    Falls back to JSON registry if db_pool is unavailable.
    Excludes ADMIN-role accounts from the member list.
    """
    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                target = await conn.fetchrow(
                    "SELECT family_id, profile_data FROM users "
                    "WHERE hardware_id = $1 AND deleted_at IS NULL",
                    hw_id,
                )
                if not target or not target["family_id"]:
                    return {"family_id": None, "members": [], "pending_invites": []}

                family_id = str(target["family_id"])
                members_rows = await conn.fetch(
                    "SELECT hardware_id, role, profile_data FROM users "
                    "WHERE family_id = $1 AND deleted_at IS NULL AND role != 'ADMIN'",
                    target["family_id"],
                )
                members = []
                for r in members_rows:
                    pd = r["profile_data"] or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    members.append({
                        "id": r["hardware_id"],
                        "name": pd.get("name"),
                        "email": pd.get("email", ""),
                        "phone": pd.get("phone", ""),
                        "role": r["role"],
                        "family_role": pd.get("family_role", ""),
                        "tier": pd.get("tier"),
                        "is_minor": pd.get("is_minor", False),
                        "guardian_id": pd.get("guardian_id", ""),
                    })

                # Pending invites still come from JSON registry (no PG table for invites)
                pending_invites = []
                registry = _load_registry()
                for token, invite in registry.get("_family_invites", {}).items():
                    if invite.get("family_id") == family_id:
                        pending_invites.append({
                            "token": token,
                            "name": invite.get("invitee_name", ""),
                            "contact": invite.get("invitee_contact", ""),
                            "role": invite.get("role", ""),
                            "status": "pending",
                            "created_at": invite.get("created_at", ""),
                        })

                return {
                    "family_id": family_id,
                    "members": members,
                    "pending_invites": pending_invites,
                }
        except Exception as e:
            logger.warning("get_family_members PG lookup failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = _load_registry()
    if not registry:
        return {"family_id": None, "members": [], "pending_invites": []}

    target_profile = None
    for k, v in registry.items():
        if k.startswith("_"):
            continue
        p = v.get("profile", {})
        if p.get("hardware_id") == hw_id:
            target_profile = p
            break

    if not target_profile:
        return {"family_id": None, "members": [], "pending_invites": []}

    family_id = target_profile.get("family_id")
    if not family_id:
        return {"family_id": None, "members": [], "pending_invites": []}

    members = []
    for k, v in registry.items():
        if k.startswith("_"):
            continue
        p = v.get("profile", {})
        if p.get("family_id") == family_id and p.get("role") != "ADMIN":
            members.append({
                "id": p.get("hardware_id"),
                "name": p.get("name"),
                "email": p.get("email", ""),
                "phone": p.get("phone", ""),
                "role": p.get("role"),
                "family_role": p.get("family_role", ""),
                "tier": p.get("tier"),
                "is_minor": p.get("is_minor", False),
                "guardian_id": p.get("guardian_id", ""),
            })

    pending_invites = []
    for token, invite in registry.get("_family_invites", {}).items():
        if invite.get("family_id") == family_id:
            pending_invites.append({
                "token": token,
                "name": invite.get("invitee_name", ""),
                "contact": invite.get("invitee_contact", ""),
                "role": invite.get("role", ""),
                "status": "pending",
                "created_at": invite.get("created_at", ""),
            })

    return {
        "family_id": family_id,
        "members": members,
        "pending_invites": pending_invites,
    }


@router.get("/coach-info/{coach_id}")
async def get_coach_info(
    coach_id: str,
    request: Request = None,
):
    """
    Get basic info about an assigned coach (name, email, specializations).
    PG-first: queries the users table by hardware_id + role=COACH.
    Falls back to JSON registry if db_pool is unavailable.
    """
    if not coach_id or coach_id.strip() == "":
        return {"coach_id": "", "coach_name": "Not Assigned", "specializations": []}

    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users "
                    "WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL",
                    coach_id,
                )
                if row:
                    pd = row["profile_data"] or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    return {
                        "coach_id": coach_id,
                        "coach_name": pd.get("name") or pd.get("display_name") or "Coach",
                        "coach_email": pd.get("email") or "",
                        "specializations": pd.get("specializations") or [],
                        "coaching_fee": pd.get("coaching_fee") or 0,
                        "zoom_link": pd.get("zoom_link") or "",
                    }
        except Exception as e:
            logger.warning("get_coach_info PG lookup failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = _load_registry()
    coach_name = "Coach"
    coach_email = ""
    specializations = []
    coaching_fee = 0
    zoom_link = ""

    for _k, v in registry.items():
        if _k.startswith("_"):
            continue
        p = v.get("profile", {})
        if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
            coach_name = p.get("name") or p.get("display_name") or "Coach"
            coach_email = p.get("email") or ""
            specializations = p.get("specializations") or []
            coaching_fee = p.get("coaching_fee") or 0
            zoom_link = p.get("zoom_link") or ""
            break

    return {
        "coach_id": coach_id,
        "coach_name": coach_name,
        "coach_email": coach_email,
        "specializations": specializations,
        "coaching_fee": coaching_fee,
        "zoom_link": zoom_link,
    }


@router.get("/vectorize/health")
async def vectorize_pipeline_health(request: Request):
    """Vectorize pipeline health check — embedding, index reachability, push integrity."""
    try:
        from app.services.vectorize_service import (
            is_vectorize_configured, verify_push_pipeline, verify_retrieval_quality,
        )
        if not is_vectorize_configured():
            return {"status": "unconfigured", "message": "Vectorize env vars not set"}

        push = await verify_push_pipeline(user_id="audit_client")
        retrieval = await verify_retrieval_quality(user_id="audit_client")

        all_push_ok = push.get("embed_ok") and push.get("upsert_ok")
        all_retrieval_ok = all(r.get("reachable") for r in retrieval.values())

        return {
            "status": "healthy" if all_push_ok and all_retrieval_ok else "degraded",
            "push_pipeline": push,
            "retrieval_quality": retrieval,
        }
    except Exception as e:
        logger.warning("vectorize health check failed: %s", e)
        return {"status": "error", "message": str(e)}


@router.get("/checkin-reply")
async def get_checkin_reply(
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """Return the latest unread Little Nate check-in follow-up for the logged-in client."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, message, created_at
                   FROM client_nate_messages
                   WHERE user_id = $1 AND read_at IS NULL
                   ORDER BY created_at DESC
                   LIMIT 1""",
                user_id,
            )
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "message": row["message"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
    except Exception as e:
        logger.warning("checkin-reply fetch failed: %s", e)
        return None


@router.post("/checkin-reply/{msg_id}/read")
async def mark_checkin_reply_read(
    msg_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """Mark a Little Nate check-in reply as read."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(500, "Database unavailable")
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE client_nate_messages
                   SET read_at = NOW()
                   WHERE id = $1::uuid AND user_id = $2 AND read_at IS NULL""",
                msg_id,
                user_id,
            )
        if result == "UPDATE 0":
            raise HTTPException(404, "Message not found or already read")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("checkin-reply mark read failed: %s", e)
        raise HTTPException(500, "Update failed")


def _load_registry() -> dict:
    """Load user registry from JSON backup. Matches bridge load_registry()."""
    paths = [
        _DATA_ROOT / "bridge" / "user_registry.json",
        _DATA_ROOT / "user_registry.json",
        Path("/app/data/user_registry.json"),
    ]
    for p in paths:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                continue
    return {}
