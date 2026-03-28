"""
Sovereign Vault — Auto-file uploads to correct subfolders.

AutoFiler: Moves newly uploaded items to Documents or Photos subfolder
based on content type.
"""

from __future__ import annotations

from typing import Optional

import asyncpg


class AutoFiler:
    """Moves vault items to the correct subfolder (Documents/Photos) based on content type."""

    def __init__(self, db_pool: asyncpg.Pool):
        self.db = db_pool

    async def file_upload(self, member_id: str, mime_type: str, item_id: str) -> Optional[str]:
        """
        Move the item to the correct subfolder under Uploads.
        - image/* -> Photos
        - else -> Documents

        Returns the target folder_id, or None if no move was needed/possible.
        """
        subfolder_name = "Photos" if (mime_type or "").startswith("image/") else "Documents"

        async with self.db.acquire() as conn:
            # Find Uploads root
            uploads_row = await conn.fetchrow(
                """SELECT id FROM vault_folders
                   WHERE member_id = $1 AND name = 'Uploads' AND parent_id IS NULL""",
                member_id
            )
            if not uploads_row:
                return None

            uploads_id = uploads_row["id"]

            # Find Documents or Photos subfolder
            subfolder_row = await conn.fetchrow(
                """SELECT id FROM vault_folders
                   WHERE member_id = $1 AND name = $2 AND parent_id = $3""",
                member_id, subfolder_name, uploads_id
            )
            if not subfolder_row:
                return None

            target_folder_id = str(subfolder_row["id"])

            # Move item
            await conn.execute(
                """UPDATE vault_items SET folder_id = $1::uuid, moved_at = NOW()
                   WHERE id = $2::uuid AND member_id = $3""",
                target_folder_id, item_id, member_id
            )

            return target_folder_id
