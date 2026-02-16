"""
Sovereign Vault — Folder and item operations (B4).
VaultOperations: CRUD for folders, items, search, stats, activity logging.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

import asyncpg

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _validate_uuid(val: str, name: str = "id") -> None:
    """Validate UUID format to prevent injection."""
    if not val or not _UUID_PATTERN.match(str(val)):
        raise ValueError(f"Invalid {name} format")


# Tier storage limits (bytes) — matches file_processor.py
TIER_LIMITS_BYTES = {
    "threshold": 1 * 1024 * 1024 * 1024,  # 1 GB
    "inner_chamber": 10 * 1024 * 1024 * 1024,  # 10 GB
    "sovereign_circle": 50 * 1024 * 1024 * 1024,  # 50 GB
    "standard": 10 * 1024 * 1024 * 1024,
    "top_tier": 50 * 1024 * 1024 * 1024,
    "top": 50 * 1024 * 1024 * 1024,
}
DEFAULT_STORAGE_LIMIT = TIER_LIMITS_BYTES["inner_chamber"]

# Custom folder limits: IC = 10, SC/TOP = unlimited
FOLDER_LIMITS = {"standard": 10, "inner_chamber": 10, "top_tier": 999999, "top": 999999, "sovereign_circle": 999999}

# Allowed sort parameters for vault items (strict validation to prevent SQL injection)
ALLOWED_SORTS = {
    "date_desc": "created_at DESC",
    "date_asc": "created_at ASC",
    "name_asc": "display_name ASC",
    "name_desc": "display_name DESC",
    "size_desc": "size_bytes DESC",
}
DEFAULT_FOLDER_LIMIT = 10

# Default folder structure when member upgrades to Inner Chamber or above
DEFAULT_FOLDERS = [
    {"name": "Conversations", "icon": "💬", "children": [
        {"name": "Starred", "icon": "⭐"},
    ]},
    {"name": "Uploads", "icon": "📎", "children": [
        {"name": "Photos", "icon": "📸"},
        {"name": "Documents", "icon": "📄"},
        {"name": "Transfer History", "icon": "🔄"},
    ]},
    {"name": "Reports", "icon": "📊", "children": [
        {"name": "Nevedal Reports", "icon": "🧬"},
        {"name": "Foresight Forecasts", "icon": "🔮"},
        {"name": "Coherence Snapshots", "icon": "🌡️"},
    ]},
    {"name": "Chapters", "icon": "📖"},  # TOP_TIER only
    {"name": "Family", "icon": "👨‍👩‍👧‍👦"},
]


def _tier_to_limit_key(tier: str) -> str:
    t = (tier or "standard").lower().replace(" ", "_")
    if t in ("top", "top_tier", "sovereign_circle"):
        return "sovereign_circle"
    return "inner_chamber"


def _row_to_folder(row: asyncpg.Record) -> dict:
    return {
        "id": str(row["id"]),
        "member_id": row["member_id"],
        "name": row["name"],
        "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
        "icon": row["icon"] or "📁",
        "color": row["color"],
        "is_system": row["is_system"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "item_count": row["item_count"] or 0,
        "sort_order": row["sort_order"] or 0,
    }


def _row_to_item(row: asyncpg.Record) -> dict:
    return {
        "id": str(row["id"]),
        "member_id": row["member_id"],
        "folder_id": str(row["folder_id"]) if row["folder_id"] else None,
        "content_type": row["content_type"],
        "filename": row["filename"],
        "display_name": row["display_name"],
        "blob_path": row["blob_path"],
        "thumbnail_path": row["thumbnail_path"],
        "size_bytes": row["size_bytes"] or 0,
        "mime_type": row["mime_type"],
        "extracted_text_preview": row["extracted_text_preview"],
        "page_count": row["page_count"],
        "dimensions": row["dimensions"],
        "session_id": row["session_id"],
        "coherence_at_creation": row["coherence_at_creation"],
        "themes": row["themes"] if row.get("themes") else [],
        "content_hash": row["content_hash"] if row.get("content_hash") else None,
        "starred": row["starred"] or False,
        "ttl_seconds": row["ttl_seconds"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
    }


class VaultOperations:
    """CRUD for vault folders and items, search, stats, activity."""

    def __init__(self, db_pool: asyncpg.Pool):
        self.db = db_pool

    # -------------------------------------------------------------------------
    # FOLDER OPERATIONS
    # -------------------------------------------------------------------------

    async def create_default_folders(self, member_id: str, tier: str = "STANDARD") -> None:
        """Create the default folder structure when a member upgrades to Inner Chamber or above."""
        include_chapters = tier and str(tier).upper() in ("TOP_TIER", "TOP", "SOVEREIGN_CIRCLE")

        async with self.db.acquire() as conn:
            for entry in DEFAULT_FOLDERS:
                if entry["name"] == "Chapters" and not include_chapters:
                    continue
                parent_row = await conn.fetchrow(
                    """INSERT INTO vault_folders (member_id, name, icon, is_system, sort_order)
                       VALUES ($1, $2, $3, TRUE, 0)
                       RETURNING id""",
                    member_id, entry["name"], entry["icon"]
                )
                parent_id = parent_row["id"]
                for i, child in enumerate(entry.get("children", [])):
                    await conn.execute(
                        """INSERT INTO vault_folders (member_id, name, parent_id, icon, is_system, sort_order)
                           VALUES ($1, $2, $3, $4, TRUE, $5)""",
                        member_id, child["name"], parent_id, child["icon"], i
                    )

    async def create_folder(
        self,
        member_id: str,
        name: str,
        parent_id: Optional[str] = None,
        icon: str = "📁",
        color: Optional[str] = None,
        tier: str = "STANDARD",
    ) -> dict:
        """Create custom folder. Validate name, check tier limits. Return folder dict."""
        name = (name or "").strip()
        if not name or len(name) > 64:
            raise ValueError("Folder name must be 1-64 characters")
        if "/" in name or "\\" in name:
            raise ValueError("Folder name cannot contain / or \\")

        limit_key = _tier_to_limit_key(tier)
        folder_limit = FOLDER_LIMITS.get(limit_key, DEFAULT_FOLDER_LIMIT)

        async with self.db.acquire() as conn:
            async with conn.transaction():
                custom_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM vault_folders WHERE member_id = $1 AND is_system = FALSE FOR UPDATE""",
                    member_id
                )
                if folder_limit > 0 and custom_count >= folder_limit:
                    raise ValueError(f"Folder limit reached ({folder_limit} custom folders)")

                row = await conn.fetchrow(
                    """INSERT INTO vault_folders (member_id, name, parent_id, icon, color, is_system)
                       VALUES ($1, $2, $3::uuid, $4, $5, FALSE)
                       RETURNING *""",
                    member_id, name, parent_id, icon, color
                )
                return _row_to_folder(row)

    async def rename_folder(self, member_id: str, folder_id: str, new_name: str) -> dict:
        """Rename a folder."""
        return await self.update_folder(member_id, folder_id, name=new_name)

    async def update_folder(
        self,
        member_id: str,
        folder_id: str,
        name: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
    ) -> dict:
        """Update folder name, icon, or color."""
        _validate_uuid(folder_id, "folder_id")
        if name is not None:
            name = (name or "").strip()
            if not name or len(name) > 64:
                raise ValueError("Folder name must be 1-64 characters")
            if "/" in name or "\\" in name:
                raise ValueError("Folder name cannot contain / or \\")

        async with self.db.acquire() as conn:
            updates = []
            params = []
            idx = 1
            if name is not None:
                updates.append(f"name = ${idx}")
                params.append(name)
                idx += 1
            if icon is not None:
                updates.append(f"icon = ${idx}")
                params.append(icon)
                idx += 1
            if color is not None:
                updates.append(f"color = ${idx}")
                params.append(color)
                idx += 1
            if not updates:
                row = await conn.fetchrow(
                    "SELECT * FROM vault_folders WHERE id = $1::uuid AND member_id = $2",
                    folder_id, member_id
                )
                if not row:
                    raise ValueError("Folder not found")
                return _row_to_folder(row)
            updates.append("updated_at = NOW()")
            params.extend([folder_id, member_id])
            where_idx = idx + 1
            row = await conn.fetchrow(
                f"""UPDATE vault_folders SET {", ".join(updates)}
                   WHERE id = ${idx}::uuid AND member_id = ${where_idx}
                   RETURNING *""",
                *params
            )
            if not row:
                raise ValueError("Folder not found")
            return _row_to_folder(row)

    async def delete_folder(self, member_id: str, folder_id: str) -> dict:
        """Move contents to parent folder, then delete. Cannot delete system folders."""
        _validate_uuid(folder_id, "folder_id")
        async with self.db.acquire() as conn:
            async with conn.transaction():
                folder = await conn.fetchrow(
                    "SELECT * FROM vault_folders WHERE id = $1::uuid AND member_id = $2",
                    folder_id, member_id
                )
                if not folder:
                    raise ValueError("Folder not found")
                if folder["is_system"]:
                    raise ValueError("Cannot delete system folders")

                parent_id = folder["parent_id"]
                # Move all items to parent
                await conn.execute(
                    "UPDATE vault_items SET folder_id = $1, moved_at = NOW() WHERE folder_id = $2::uuid",
                    parent_id, folder_id
                )
                # Move child folders to parent
                await conn.execute(
                    "UPDATE vault_folders SET parent_id = $1 WHERE parent_id = $2::uuid",
                    parent_id, folder_id
                )
                await conn.execute("DELETE FROM vault_folders WHERE id = $1::uuid", folder_id)
                await self.log_activity(conn, member_id, "folder_deleted", folder_id=folder_id)
                return {"deleted": folder_id}

    async def get_folder_tree(self, member_id: str) -> list:
        """Return full folder tree for member (flat list with parent_id for client-side tree building)."""
        rows = await self.db.fetch(
            """SELECT * FROM vault_folders WHERE member_id = $1 ORDER BY sort_order, name""",
            member_id
        )
        return [_row_to_folder(r) for r in rows]

    # -------------------------------------------------------------------------
    # ITEM OPERATIONS
    # -------------------------------------------------------------------------

    async def add_item(
        self,
        member_id: str,
        folder_id: str,
        content_type: str,
        display_name: str,
        blob_path: str,
        thumbnail_path: Optional[str] = None,
        size_bytes: int = 0,
        mime_type: Optional[str] = None,
        extracted_text_preview: Optional[str] = None,
        page_count: Optional[int] = None,
        dimensions: Optional[dict] = None,
        session_id: Optional[str] = None,
        coherence_at_creation: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
        themes: Optional[list] = None,
        content_hash: Optional[str] = None,
    ) -> dict:
        """Add vault item."""
        import json as _json
        themes_json = _json.dumps(themes) if themes else "[]"
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO vault_items
                   (member_id, folder_id, content_type, display_name, blob_path, thumbnail_path,
                    size_bytes, mime_type, extracted_text_preview, page_count, dimensions,
                    session_id, coherence_at_creation, ttl_seconds, themes, content_hash, uploaded_at)
                   VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, $15::jsonb, $16, NOW())
                   RETURNING *""",
                member_id, folder_id, content_type, display_name, blob_path, thumbnail_path,
                size_bytes, mime_type, extracted_text_preview or None, page_count,
                dimensions if dimensions is not None else None, session_id, coherence_at_creation,
                ttl_seconds, themes_json, content_hash,
            )
            item = _row_to_item(row)
            await self.log_activity(conn, member_id, "item_added", item_id=str(row["id"]))
            return item

    async def move_item(self, member_id: str, item_id: str, target_folder_id: str) -> dict:
        """Move item (metadata only)."""
        _validate_uuid(item_id, "item_id")
        _validate_uuid(target_folder_id, "target_folder_id")
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE vault_items SET folder_id = $1::uuid, moved_at = NOW()
                   WHERE id = $2::uuid AND member_id = $3
                   RETURNING *""",
                target_folder_id, item_id, member_id
            )
            if not row:
                raise ValueError("Item not found")
            await self.log_activity(conn, member_id, "item_moved", item_id=item_id, metadata={"target_folder_id": target_folder_id})
            return _row_to_item(row)

    async def star_item(self, member_id: str, item_id: str) -> dict:
        """Toggle starred status."""
        _validate_uuid(item_id, "item_id")
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE vault_items SET starred = NOT COALESCE(starred, FALSE)
                   WHERE id = $1::uuid AND member_id = $2
                   RETURNING *""",
                item_id, member_id
            )
            if not row:
                raise ValueError("Item not found")
            await self.log_activity(conn, member_id, "item_starred", item_id=item_id, metadata={"starred": row["starred"]})
            return _row_to_item(row)

    async def update_item_content(
        self,
        member_id: str,
        item_id: str,
        extracted_text_preview: Optional[str] = None,
        blob_path: Optional[str] = None,
        display_name: Optional[str] = None,
        size_bytes: Optional[int] = None,
        themes: Optional[list] = None,
        content_hash: Optional[str] = None,
    ) -> dict:
        """Update item content (for organization saves, rewrites, etc.)."""
        import json as _json
        _validate_uuid(item_id, "item_id")
        async with self.db.acquire() as conn:
            # Build dynamic SET clause
            sets = []
            params: list = []
            idx = 1

            if extracted_text_preview is not None:
                sets.append(f"extracted_text_preview = ${idx}")
                params.append(extracted_text_preview)
                idx += 1
            if blob_path is not None:
                sets.append(f"blob_path = ${idx}")
                params.append(blob_path)
                idx += 1
            if display_name is not None:
                sets.append(f"display_name = ${idx}")
                params.append(display_name)
                idx += 1
            if size_bytes is not None:
                sets.append(f"size_bytes = ${idx}")
                params.append(size_bytes)
                idx += 1
            if themes is not None:
                sets.append(f"themes = ${idx}::jsonb")
                params.append(_json.dumps(themes))
                idx += 1
            if content_hash is not None:
                sets.append(f"content_hash = ${idx}")
                params.append(content_hash)
                idx += 1

            if not sets:
                raise ValueError("No fields to update")

            # Add member_id and item_id for WHERE clause
            params.append(item_id)
            item_idx = idx
            idx += 1
            params.append(member_id)
            member_idx = idx

            sql = f"""UPDATE vault_items SET {', '.join(sets)}
                      WHERE id = ${item_idx}::uuid AND member_id = ${member_idx}
                      RETURNING *"""
            row = await conn.fetchrow(sql, *params)
            if not row:
                raise ValueError("Item not found")
            await self.log_activity(
                conn, member_id, "item_content_updated", item_id=item_id,
                metadata={"fields_updated": [s.split(" = ")[0] for s in sets]},
            )
            return _row_to_item(row)

    async def delete_item(self, member_id: str, item_id: str) -> dict:
        """Delete vault item."""
        _validate_uuid(item_id, "item_id")
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM vault_items WHERE id = $1::uuid AND member_id = $2",
                item_id, member_id
            )
            if not row:
                raise ValueError("Item not found")
            await conn.execute("DELETE FROM vault_items WHERE id = $1::uuid", item_id)
            await self.log_activity(conn, member_id, "item_deleted", item_id=item_id)
            return {"deleted": item_id}

    async def get_folder_items(
        self,
        member_id: str,
        folder_id: str,
        page: int = 1,
        per_page: int = 20,
        sort: str = "date_desc",
    ) -> dict:
        """List items in folder with pagination."""
        _validate_uuid(folder_id, "folder_id")
        order = ALLOWED_SORTS.get(sort)
        if not order:
            raise ValueError(
                f"Invalid sort parameter: {sort}. "
                f"Allowed: {', '.join(ALLOWED_SORTS.keys())}"
            )
        offset = max(0, (page - 1) * per_page)

        async with self.db.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM vault_items WHERE member_id = $1 AND folder_id = $2::uuid",
                member_id, folder_id
            )
            rows = await conn.fetch(
                f"""SELECT * FROM vault_items WHERE member_id = $1 AND folder_id = $2::uuid
                    ORDER BY {order}
                    OFFSET $3 LIMIT $4""",
                member_id, folder_id, offset, per_page
            )
        items = [_row_to_item(r) for r in rows]
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if total else 0,
        }

    async def get_item(self, member_id: str, item_id: str) -> Optional[dict]:
        """Get vault item by ID."""
        _validate_uuid(item_id, "item_id")
        row = await self.db.fetchrow(
            "SELECT * FROM vault_items WHERE id = $1::uuid AND member_id = $2",
            item_id, member_id
        )
        return _row_to_item(row) if row else None

    # -------------------------------------------------------------------------
    # SEARCH
    # -------------------------------------------------------------------------

    async def search_vault(
        self,
        member_id: str,
        query: str,
        folder_id: Optional[str] = None,
        content_type: Optional[str] = None,
        max_results: int = 20,
    ) -> list:
        """Full-text search using PostgreSQL tsvector/tsquery."""
        q = (query or "").strip()
        if not q:
            return []
        if len(q) > 256:
            q = q[:256]

        async with self.db.acquire() as conn:
            conditions = ["member_id = $1", "search_vector @@ plainto_tsquery('english', $2)"]
            params: list = [member_id, q]
            if folder_id:
                _validate_uuid(folder_id, "folder_id")
                conditions.append(f"folder_id = ${len(params) + 1}::uuid")
                params.append(folder_id)
            if content_type:
                conditions.append(f"content_type = ${len(params) + 1}")
                params.append(content_type)
            params.append(max_results)
            limit_idx = len(params)

            sql = f"""
                SELECT * FROM vault_items
                WHERE {" AND ".join(conditions)}
                ORDER BY ts_rank(search_vector, plainto_tsquery('english', $2)) DESC
                LIMIT ${limit_idx}
            """
            rows = await conn.fetch(sql, *params)
        return [_row_to_item(r) for r in rows]

    # -------------------------------------------------------------------------
    # STATS
    # -------------------------------------------------------------------------

    async def get_vault_stats(self, member_id: str, tier: str = "STANDARD") -> dict:
        """Return VaultStats: total_items, total_size_bytes, storage_limit_bytes, etc."""
        limit_key = _tier_to_limit_key(tier)
        storage_limit = TIER_LIMITS_BYTES.get(limit_key, DEFAULT_STORAGE_LIMIT)
        folder_limit = FOLDER_LIMITS.get(limit_key, DEFAULT_FOLDER_LIMIT)

        async with self.db.acquire() as conn:
            total_items = await conn.fetchval(
                "SELECT COUNT(*) FROM vault_items WHERE member_id = $1",
                member_id
            ) or 0
            total_size = await conn.fetchval(
                "SELECT COALESCE(SUM(size_bytes), 0)::bigint FROM vault_items WHERE member_id = $1",
                member_id
            ) or 0
            folder_count = await conn.fetchval(
                "SELECT COUNT(*) FROM vault_folders WHERE member_id = $1",
                member_id
            ) or 0
            breakdown_rows = await conn.fetch(
                """SELECT content_type, COUNT(*) as cnt, COALESCE(SUM(size_bytes), 0)::bigint as sz
                   FROM vault_items WHERE member_id = $1 GROUP BY content_type""",
                member_id
            )

        breakdown = {r["content_type"]: {"count": r["cnt"], "size_bytes": r["sz"]} for r in breakdown_rows}
        usage_percent = (total_size / storage_limit * 100) if storage_limit > 0 else 0.0

        return {
            "total_items": total_items,
            "total_size_bytes": total_size,
            "storage_limit_bytes": storage_limit,
            "usage_percent": round(usage_percent, 2),
            "folder_count": folder_count,
            "folder_limit": folder_limit,
            "breakdown": breakdown,
        }

    # -------------------------------------------------------------------------
    # ACTIVITY LOGGING
    # -------------------------------------------------------------------------

    async def log_activity(
        self,
        conn_or_pool,
        member_id: str,
        action: str,
        item_id: Optional[str] = None,
        folder_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Log vault activity (pass conn for same-transaction, or pool for new conn)."""
        if hasattr(conn_or_pool, "execute"):
            conn = conn_or_pool
        else:
            conn = await conn_or_pool.acquire()
            try:
                await self._log_activity_impl(conn, member_id, action, item_id, folder_id, metadata or {})
            finally:
                conn_or_pool.release(conn)
            return
        await self._log_activity_impl(conn, member_id, action, item_id, folder_id, metadata or {})

    async def _log_activity_impl(
        self, conn, member_id: str, action: str,
        item_id: Optional[str], folder_id: Optional[str], metadata: dict
    ) -> None:
        import json
        await conn.execute(
            """INSERT INTO vault_activity (member_id, action, item_id, folder_id, metadata)
               VALUES ($1, $2, $3::uuid, $4::uuid, $5::jsonb)""",
            member_id, action, item_id, folder_id, json.dumps(metadata or {}),
        )
