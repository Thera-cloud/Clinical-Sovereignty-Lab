"""
Coach FOLDER API — File storage & auto-populated folder hierarchy

Endpoints for managing coach folders (personal, client, family, group, company)
and uploading/downloading files within them.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services.api_server import get_current_user, require_coach

logger = logging.getLogger("nate.folder_api")

router = APIRouter(
    prefix="/api/coach/folders",
    tags=["coach-folders"],
    dependencies=[Depends(require_coach)],
)


class CreateFolderRequest(BaseModel):
    folder_type: str = "personal"
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    parent_id: Optional[str] = None


class UploadFileRequest(BaseModel):
    folder_id: str
    filename: str
    file_type: Optional[str] = None
    azure_blob_url: Optional[str] = None


@router.get("")
async def list_folders(request: Request, user: Dict = Depends(require_coach)):
    """List all folders for the current coach, auto-populating from assigned clients."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        await _auto_populate_folders(conn, coach_id)
        rows = await conn.fetch(
            """SELECT id, coach_id, folder_type, parent_id, entity_id, entity_name, created_at
               FROM coach_folders WHERE coach_id = $1 ORDER BY folder_type, entity_name""",
            coach_id,
        )

    folders = []
    for r in rows:
        folders.append({
            "id": str(r["id"]),
            "coach_id": r["coach_id"],
            "folder_type": r["folder_type"],
            "parent_id": str(r["parent_id"]) if r["parent_id"] else None,
            "entity_id": r["entity_id"],
            "entity_name": r["entity_name"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"folders": folders, "count": len(folders)}


@router.get("/{folder_id}/files")
async def list_files(folder_id: str, request: Request, user: Dict = Depends(require_coach)):
    """List files in a folder."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        folder = await conn.fetchrow(
            "SELECT id FROM coach_folders WHERE id = $1::uuid AND coach_id = $2", folder_id, coach_id
        )
        if not folder:
            raise HTTPException(404, "Folder not found")

        rows = await conn.fetch(
            """SELECT id, filename, file_type,
                      COALESCE(azure_blob_url, storage_url) AS azure_blob_url,
                      file_size_bytes, uploaded_by, metadata, created_at
               FROM coach_folder_files WHERE folder_id = $1::uuid ORDER BY created_at DESC""",
            folder_id,
        )

    files = []
    for r in rows:
        files.append({
            "id": str(r["id"]),
            "filename": r["filename"],
            "file_type": r["file_type"],
            "azure_blob_url": r["azure_blob_url"],
            "file_size_bytes": r["file_size_bytes"],
            "uploaded_by": r["uploaded_by"],
            "metadata": r["metadata"] if r["metadata"] else {},
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"files": files, "count": len(files)}


@router.post("/create")
async def create_folder(req: CreateFolderRequest, request: Request, user: Dict = Depends(require_coach)):
    """Create a custom folder."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO coach_folders (coach_id, folder_type, parent_id, entity_id, entity_name)
               VALUES ($1, $2, $3::uuid, $4, $5) RETURNING id""",
            coach_id, req.folder_type,
            req.parent_id, req.entity_id, req.entity_name,
        )

    return {"id": str(row["id"]), "status": "created"}


@router.post("/upload-metadata")
async def upload_file_metadata(req: UploadFileRequest, request: Request, user: Dict = Depends(require_coach)):
    """Record file metadata (blob URL already uploaded to Azure)."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        folder = await conn.fetchrow(
            "SELECT id FROM coach_folders WHERE id = $1::uuid AND coach_id = $2", req.folder_id, coach_id
        )
        if not folder:
            raise HTTPException(404, "Folder not found")

        row = await conn.fetchrow(
            """INSERT INTO coach_folder_files (folder_id, filename, file_type, azure_blob_url, storage_url, uploaded_by)
               VALUES ($1::uuid, $2, $3, $4, $4, $5) RETURNING id""",
            req.folder_id, req.filename, req.file_type, req.azure_blob_url, coach_id,
        )

    return {"id": str(row["id"]), "status": "uploaded"}


UPLOAD_DIR = Path(os.environ.get("COACH_UPLOAD_DIR", "/app/data/coach_uploads"))
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".md", ".csv", ".xls", ".xlsx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp3", ".mp4", ".m4a", ".wav",
    ".zip", ".json",
}


@router.post("/upload")
async def upload_file(
    request: Request,
    folder_id: str = Form(...),
    file: UploadFile = File(...),
    user: Dict = Depends(require_coach),
):
    """Upload a file to a coach folder."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        folder = await conn.fetchrow(
            "SELECT id FROM coach_folders WHERE id = $1::uuid AND coach_id = $2",
            folder_id, coach_id,
        )
        if not folder:
            raise HTTPException(404, "Folder not found or not yours")

    filename = file.filename or "unnamed"
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type '{ext}' not allowed")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File exceeds {MAX_UPLOAD_SIZE // (1024*1024)}MB limit")

    file_id = str(uuid.uuid4())
    safe_filename = f"{file_id}{ext}"
    folder_path = UPLOAD_DIR / coach_id
    folder_path.mkdir(parents=True, exist_ok=True)
    file_path = folder_path / safe_filename

    file_path.write_bytes(content)
    logger.info(f"Coach {coach_id} uploaded {filename} ({len(content)} bytes) to folder {folder_id}")

    mime = file.content_type or "application/octet-stream"
    file_type = "pdf" if "pdf" in mime else "image" if "image" in mime else "spreadsheet" if "sheet" in mime or "xls" in ext else "document"

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO coach_folder_files
               (folder_id, filename, file_type, azure_blob_url, storage_url, file_size_bytes, uploaded_by, metadata)
               VALUES ($1::uuid, $2, $3, $4, $4, $5, $6, $7) RETURNING id, created_at""",
            folder_id, filename, file_type,
            str(file_path), len(content), coach_id,
            json.dumps({"original_name": filename, "mime": mime}),
        )

    return {
        "id": str(row["id"]),
        "filename": filename,
        "file_type": file_type,
        "file_size_bytes": len(content),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "status": "uploaded",
    }


def _parse_file_metadata(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _extract_preview_text(filename: str, file_type: str, meta: dict, location: Optional[str]) -> tuple[str, str]:
    """Return (content, format) for in-app review — never exposes raw download."""
    for key in ("markdown", "summary_preview", "extracted_text", "text"):
        val = (meta.get(key) or "").strip()
        if val:
            fmt = "markdown" if key in ("markdown", "summary_preview") else "text"
            return val, fmt

    if not location:
        return "", ""

    from app.services.blob_storage import download_bytes

    storage_kind = "local" if str(location).startswith("/") else "auto"
    raw = download_bytes(location=location, storage_kind=storage_kind)
    if not raw:
        return "", ""

    name = (filename or "").lower()
    ftype = (file_type or "").lower()
    if name.endswith(".pdf") or "pdf" in ftype:
        try:
            from io import BytesIO
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw))
            parts = []
            for page in reader.pages[:40]:
                text = (page.extract_text() or "").strip()
                if text:
                    parts.append(text)
            if parts:
                return "\n\n".join(parts), "text"
        except Exception as e:
            logger.warning("PDF preview extract failed: %s", e)

    if name.endswith((".txt", ".md", ".csv")) or "text" in ftype:
        try:
            return raw.decode("utf-8", errors="replace"), "text"
        except Exception:
            pass

    return "", ""


@router.get("/files/{file_id}/preview")
async def preview_file(file_id: str, request: Request, user: Dict = Depends(require_coach)):
    """In-app review content only — no file attachment (coaches must not save client data locally)."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT f.filename, f.file_type, f.metadata, f.created_at,
                      COALESCE(f.azure_blob_url, f.storage_url) AS storage_url
               FROM coach_folder_files f
               JOIN coach_folders d ON f.folder_id = d.id
               WHERE f.id = $1::uuid AND d.coach_id = $2""",
            file_id,
            coach_id,
        )
    if not row:
        raise HTTPException(404, "File not found")

    meta = _parse_file_metadata(row["metadata"])
    content, fmt = _extract_preview_text(
        row["filename"] or "",
        row["file_type"] or "",
        meta,
        row["storage_url"],
    )
    if not content.strip():
        raise HTTPException(404, "No in-app preview available for this file")

    return {
        "filename": row["filename"],
        "format": fmt,
        "content": content,
        "review_only": True,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@router.get("/files/{file_id}/download")
async def download_file(file_id: str, request: Request, user: Dict = Depends(require_coach)):
    """Download a file from a coach folder."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT f.filename, COALESCE(f.azure_blob_url, f.storage_url) AS azure_blob_url, f.metadata
               FROM coach_folder_files f
               JOIN coach_folders d ON f.folder_id = d.id
               WHERE f.id = $1::uuid AND d.coach_id = $2""",
            file_id, coach_id,
        )
    if not row:
        raise HTTPException(404, "File not found")

    file_path = Path(row["azure_blob_url"]) if row["azure_blob_url"] else None
    if not file_path or not file_path.exists():
        raise HTTPException(404, "File data not found on disk")

    meta = row["metadata"] if row["metadata"] else {}
    mime = meta.get("mime", "application/octet-stream") if isinstance(meta, dict) else "application/octet-stream"
    return FileResponse(str(file_path), filename=row["filename"], media_type=mime)


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request, user: Dict = Depends(require_coach)):
    """Delete a file from a folder."""
    db = getattr(request.app.state, "db_pool", None)
    if not db:
        raise HTTPException(503, "Database unavailable")

    coach_id = user.get("hardware_id", user.get("username", ""))

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COALESCE(f.azure_blob_url, f.storage_url) AS azure_blob_url FROM coach_folder_files f
               JOIN coach_folders d ON f.folder_id = d.id
               WHERE f.id = $1::uuid AND d.coach_id = $2""",
            file_id, coach_id,
        )
        if not row:
            raise HTTPException(404, "File not found")

        await conn.execute("DELETE FROM coach_folder_files WHERE id = $1::uuid", file_id)

    if row["azure_blob_url"]:
        try:
            fp = Path(row["azure_blob_url"])
            if fp.exists():
                fp.unlink()
        except Exception as e:
            logger.warning("Failed to delete file from disk: %s", e)

    return {"status": "deleted"}


@router.get("/health")
async def folder_health(request: Request):
    """Health check."""
    return {"status": "ok", "service": "coach_folders"}


async def _auto_populate_folders(conn, coach_id: str):
    """Auto-populate folder hierarchy from assigned clients, families, groups."""
    existing = await conn.fetch(
        "SELECT entity_id, folder_type FROM coach_folders WHERE coach_id = $1", coach_id
    )
    existing_set = {(r["entity_id"], r["folder_type"]) for r in existing}

    if (coach_id, "personal") not in existing_set:
        await conn.execute(
            """INSERT INTO coach_folders (coach_id, folder_type, entity_id, entity_name)
               VALUES ($1, 'personal', $1, 'My Files') ON CONFLICT DO NOTHING""",
            coach_id,
        )

    clients = await conn.fetch(
        """SELECT username, profile_data->>'name' as name, profile_data->>'family_id' as family_id
           FROM users WHERE role = 'CLIENT'
           AND (profile_data->>'coach_id' = $1
                OR profile_data->>'assigned_coach_id' = $1
                OR profile_data->>'assigned_coach' = $1)""",
        coach_id,
    )

    for c in clients:
        cid = c["username"]
        cname = c["name"] or cid
        if (cid, "client") not in existing_set:
            await conn.execute(
                """INSERT INTO coach_folders (coach_id, folder_type, entity_id, entity_name)
                   VALUES ($1, 'client', $2, $3) ON CONFLICT DO NOTHING""",
                coach_id, cid, cname,
            )

    families = await conn.fetch(
        """SELECT DISTINCT profile_data->>'family_id' as fid,
                  profile_data->>'family_role' as frole,
                  profile_data->>'name' as name
           FROM users WHERE role = 'CLIENT'
           AND profile_data->>'family_id' IS NOT NULL
           AND (profile_data->>'coach_id' = $1
                OR profile_data->>'assigned_coach_id' = $1)""",
        coach_id,
    )
    seen_families = set()
    for f in families:
        fid = f["fid"]
        if fid and fid not in seen_families:
            seen_families.add(fid)
            fname = f["name"] or fid
            if (fid, "family") not in existing_set:
                await conn.execute(
                    """INSERT INTO coach_folders (coach_id, folder_type, entity_id, entity_name)
                       VALUES ($1, 'family', $2, $3) ON CONFLICT DO NOTHING""",
                    coach_id, fid, f"{fname} Family",
                )
