"""
Sovereign Vault — REST API Router (B2/B9).
Endpoints for vault folders, items, uploads, search, stats, export.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services.vault.vault_operations import VaultOperations
from app.services.vault.auto_filer import AutoFiler
from app.services.vault.file_processor import FileProcessor
from app.services.vault.blob_manager import VaultBlobManager


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class CreateFolderBody(BaseModel):
    """Body for create folder."""
    name: str = Field(..., min_length=1, max_length=64)
    parent_id: Optional[str] = None
    icon: str = Field(default="📁", max_length=10)
    color: Optional[str] = Field(default=None, max_length=7)


class UpdateFolderBody(BaseModel):
    """Body for PATCH folder."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    icon: Optional[str] = Field(default=None, max_length=10)
    color: Optional[str] = Field(default=None, max_length=7)


class MoveItemBody(BaseModel):
    """Body for move item."""
    target_folder_id: str = Field(...)


# =============================================================================
# ROUTER FACTORY
# =============================================================================


def create_vault_router(db_pool) -> APIRouter:
    """Create FastAPI router for vault endpoints. Requires db_pool at creation time."""
    router = APIRouter(prefix="/api/v1", tags=["vault"])

    # Simple per-user rate limiter for uploads (10 uploads per minute)
    _upload_timestamps: dict[str, list[float]] = defaultdict(list)
    UPLOAD_RATE_LIMIT = 10  # max uploads per window
    UPLOAD_RATE_WINDOW = 60  # seconds

    def _check_upload_rate(member_id: str):
        now = time.time()
        timestamps = _upload_timestamps[member_id]
        # Remove timestamps outside the window
        _upload_timestamps[member_id] = [t for t in timestamps if now - t < UPLOAD_RATE_WINDOW]
        if len(_upload_timestamps[member_id]) >= UPLOAD_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Upload rate limit exceeded. Max {UPLOAD_RATE_LIMIT} uploads per minute.",
            )
        _upload_timestamps[member_id].append(now)

    vault_ops = VaultOperations(db_pool)
    auto_filer = AutoFiler(db_pool)
    file_processor = FileProcessor()
    blob_manager = VaultBlobManager()

    async def get_member_id_and_tier(
        authenticated_user_id: str = Depends(get_current_user),
    ) -> tuple[str, str]:
        """Resolve member_id and tier from the authenticated user.
        Falls back to the raw user ID with STANDARD tier if no DB record exists
        (e.g. users who register through the bridge/WebSocket and don't yet
        have a row in the PostgreSQL users table).
        """
        try:
            row = await db_pool.fetchrow(
                "SELECT id, tier FROM users WHERE id::text = $1 OR username = $1",
                authenticated_user_id
            )
        except Exception:
            row = None
        if row:
            member_id = str(row["id"])
            tier = (row["tier"] or "STANDARD") if row.get("tier") else "STANDARD"
        else:
            member_id = authenticated_user_id
            tier = "STANDARD"
        return member_id, tier

    # -------------------------------------------------------------------------
    # UPLOAD (separate from vault prefix per spec)
    # -------------------------------------------------------------------------

    @router.post("/upload")
    async def upload_file(
        request: Request,
        file: UploadFile = File(...),
        message: Optional[str] = Form(None),
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Multipart file upload. Validate, process, store, return upload_id."""
        member_id, tier = auth

        # Check Content-Length before reading to prevent memory exhaustion
        content_length = request.headers.get("content-length")
        if content_length:
            max_bytes = 200 * 1024 * 1024  # 200MB absolute max (TOP_TIER limit)
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum upload size is {max_bytes // (1024*1024)}MB",
                )

        _check_upload_rate(member_id)

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")

        try:
            mime_type = file_processor.validate_mime(content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Get current usage for size validation
        stats = await vault_ops.get_vault_stats(member_id, tier)
        try:
            file_processor.validate_size(
                len(content), mime_type, tier, stats["total_size_bytes"]
            )
        except ValueError as e:
            raise HTTPException(status_code=413, detail=str(e))

        processed = file_processor.process(
            file.filename or "upload", content, mime_type
        )

        upload_id = str(uuid.uuid4())
        blob_path = blob_manager.store_quarantine(upload_id, content, mime_type)

        # Ensure default folders exist
        folders = await vault_ops.get_folder_tree(member_id)
        if not folders:
            await vault_ops.create_default_folders(member_id, tier)

        # Pick default folder: Uploads (we'll auto-file after add_item)
        uploads_root = None
        for f in await vault_ops.get_folder_tree(member_id):
            if f["name"] == "Uploads" and f["parent_id"] is None:
                uploads_root = f["id"]
                break
        if not uploads_root:
            raise HTTPException(status_code=500, detail="Uploads folder not found; create default folders first")

        # Add item with quarantine path (temporary); auto-filer will move to correct subfolder
        item = await vault_ops.add_item(
            member_id=member_id,
            folder_id=uploads_root,
            content_type="upload_document" if "document" in processed.type else "upload_image",
            display_name=file.filename or "Upload",
            blob_path=blob_path,
            thumbnail_path=None,
            size_bytes=processed.size_bytes,
            mime_type=mime_type,
            extracted_text_preview=processed.preview[:500] if processed.preview else None,
            page_count=processed.page_count,
            dimensions=processed.dimensions,
        )

        await auto_filer.file_upload(member_id, mime_type, item["id"])

        return {
            "upload_id": upload_id,
            "item_id": item["id"],
            "display_name": item["display_name"],
            "size_bytes": item["size_bytes"],
            "mime_type": mime_type,
        }

    # -------------------------------------------------------------------------
    # VAULT FOLDERS
    # -------------------------------------------------------------------------

    @router.get("/vault/folders")
    async def get_folders(
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Get folder tree."""
        member_id, _ = auth
        return await vault_ops.get_folder_tree(member_id)

    @router.post("/vault/folders")
    async def create_folder(
        body: CreateFolderBody,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Create folder."""
        member_id, tier = auth
        try:
            return await vault_ops.create_folder(
                member_id, body.name, body.parent_id, body.icon, body.color, tier
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.patch("/vault/folders/{folder_id}")
    async def update_folder(
        folder_id: str,
        body: UpdateFolderBody,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Update folder (rename, icon, color)."""
        member_id, _ = auth
        if body.name is None and body.icon is None and body.color is None:
            row = await db_pool.fetchrow(
                "SELECT * FROM vault_folders WHERE id = $1::uuid AND member_id = $2",
                folder_id, member_id
            )
            if not row:
                raise HTTPException(status_code=404, detail="Folder not found")
            return {
                "id": str(row["id"]),
                "member_id": row["member_id"],
                "name": row["name"],
                "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
                "icon": row["icon"],
                "color": row["color"],
                "is_system": row["is_system"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "item_count": row["item_count"] or 0,
                "sort_order": row["sort_order"] or 0,
            }
        try:
            return await vault_ops.update_folder(
                member_id, folder_id,
                name=body.name, icon=body.icon, color=body.color,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.delete("/vault/folders/{folder_id}")
    async def delete_folder(
        folder_id: str,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Delete folder (moves contents to parent). Cannot delete system folders."""
        member_id, _ = auth
        try:
            return await vault_ops.delete_folder(member_id, folder_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/vault/folders/{folder_id}/items")
    async def list_folder_items(
        folder_id: str,
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        sort: str = Query("date_desc"),
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """List items in folder (paginated)."""
        member_id, _ = auth
        return await vault_ops.get_folder_items(
            member_id, folder_id, page=page, per_page=per_page, sort=sort
        )

    # -------------------------------------------------------------------------
    # VAULT ITEMS
    # -------------------------------------------------------------------------

    @router.get("/vault/items/{item_id}")
    async def get_item(
        item_id: str,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Get item with signed blob URL."""
        member_id, _ = auth
        item = await vault_ops.get_item(member_id, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        blob_path = item.get("blob_path")
        signed_url = None
        if blob_path:
            try:
                signed_url = blob_manager.get_signed_url(blob_path)
            except ValueError:
                signed_url = None  # Invalid path (e.g. path traversal attempt)
        return {**item, "blob_url": signed_url}

    @router.post("/vault/items/{item_id}/move")
    async def move_item(
        item_id: str,
        body: MoveItemBody,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Move item to target folder."""
        member_id, _ = auth
        try:
            return await vault_ops.move_item(member_id, item_id, body.target_folder_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/vault/items/{item_id}/star")
    async def star_item(
        item_id: str,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Toggle starred status."""
        member_id, _ = auth
        try:
            return await vault_ops.star_item(member_id, item_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/vault/items/{item_id}/save")
    async def save_item(
        item_id: str,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Convert 24hr TTL item to permanent (clear ttl_seconds)."""
        member_id, _ = auth
        row = await db_pool.fetchrow(
            "SELECT * FROM vault_items WHERE id = $1::uuid AND member_id = $2",
            item_id, member_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        if not row.get("ttl_seconds"):
            return {"id": item_id, "ttl_seconds": None, "message": "Already permanent"}
        await db_pool.execute(
            "UPDATE vault_items SET ttl_seconds = NULL WHERE id = $1::uuid AND member_id = $2",
            item_id, member_id
        )
        return {"id": item_id, "ttl_seconds": None, "message": "Saved permanently"}

    @router.delete("/vault/items/{item_id}")
    async def delete_item(
        item_id: str,
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Delete item."""
        member_id, _ = auth
        try:
            return await vault_ops.delete_item(member_id, item_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # -------------------------------------------------------------------------
    # SEARCH & STATS
    # -------------------------------------------------------------------------

    @router.get("/vault/search")
    async def search_vault(
        q: str = Query(..., alias="q"),
        type: Optional[str] = Query(None, alias="type"),
        folder: Optional[str] = Query(None, alias="folder"),
        max_results: int = Query(20, ge=1, le=100),
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Full-text search."""
        member_id, _ = auth
        return await vault_ops.search_vault(
            member_id, q, folder_id=folder, content_type=type, max_results=max_results
        )

    @router.get("/vault/stats")
    async def get_vault_stats(
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Get vault stats (storage, limits, breakdown)."""
        member_id, tier = auth
        return await vault_ops.get_vault_stats(member_id, tier)

    @router.post("/vault/export")
    async def start_vault_export(
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Start vault export (placeholder — returns export job id)."""
        member_id, _ = auth
        export_id = str(uuid.uuid4())
        return {
            "export_id": export_id,
            "status": "queued",
            "message": "Vault export job queued. Poll /api/v1/vault/export/{export_id} for status.",
        }

    # -------------------------------------------------------------------------
    # CHAT HISTORY IMPORT (Transfer Crystal + Vault Items)
    # -------------------------------------------------------------------------

    # Import rate limiting: max 3 per user per hour
    _import_timestamps: dict[str, list[float]] = defaultdict(list)
    IMPORT_RATE_LIMIT = 3
    IMPORT_RATE_WINDOW = 3600  # 1 hour
    # Concurrency guard: 1 import at a time per user
    _import_in_progress: set[str] = set()

    def _check_import_rate(member_id: str):
        now = time.time()
        timestamps = _import_timestamps[member_id]
        _import_timestamps[member_id] = [t for t in timestamps if now - t < IMPORT_RATE_WINDOW]
        if len(_import_timestamps[member_id]) >= IMPORT_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Import rate limit exceeded. Max 3 imports per hour.",
            )
        if member_id in _import_in_progress:
            raise HTTPException(
                status_code=429,
                detail="An import is already in progress. Please wait.",
            )
        _import_timestamps[member_id].append(now)

    @router.post("/vault/import")
    async def import_chat_history(
        request: Request,
        file: UploadFile = File(...),
        source: str = Form("auto"),
        auth: tuple = Depends(get_member_id_and_tier),
    ):
        """Import AI chat history: creates browseable vault items + Transfer Crystal.

        Accepts ZIP (ChatGPT export) or JSON (Claude, Gemini, Replika exports).
        Auto-detects source platform if source="auto".

        Returns crystal summary + vault import statistics.
        """
        member_id, tier = auth

        # Content-Length check (Section 9d)
        content_length = request.headers.get("content-length")
        if content_length:
            max_bytes = 200 * 1024 * 1024
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="IMPORT_FILE_TOO_LARGE",
                )

        _check_import_rate(member_id)
        _import_in_progress.add(member_id)

        try:
            # Read file (with hard cap)
            content = await file.read(200 * 1024 * 1024 + 1)
            if len(content) > 200 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="IMPORT_FILE_TOO_LARGE")
            if not content:
                raise HTTPException(status_code=400, detail="IMPORT_EMPTY_FILE")

            # Auto-detect source
            from app.services.vault.transfer_crystal import TransferCrystalBuilder
            builder = TransferCrystalBuilder(db_pool)

            if source == "auto":
                source = builder.detect_source(file.filename or "", content)
                if source == "unknown":
                    raise HTTPException(
                        status_code=400,
                        detail="IMPORT_FORMAT_UNSUPPORTED",
                    )

            # Run the full pipeline (parse -> vault import -> crystal)
            try:
                result = await builder.build(
                    member_id=member_id,
                    source=source,
                    raw_data=content,
                    content_sentinel_scan=True,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail="IMPORT_FAILED")
            except Exception as e:
                import logging
                logging.getLogger("vault.import").exception("Import pipeline error")
                raise HTTPException(status_code=500, detail="IMPORT_FAILED")

            return {
                "status": "success",
                "source": source,
                "crystal": result.get("crystal"),
                "stats": result.get("stats"),
                "vault_import": result.get("vault_import"),
            }

        finally:
            _import_in_progress.discard(member_id)

    return router
