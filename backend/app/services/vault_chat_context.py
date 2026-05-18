"""Vault context retrieval for Little Nate chat.

Turns explicit [Vault:<uuid>] references and natural upload-reference prompts
into bounded prompt context. Keeps bridge_server.py edits small and auditable.
"""

from __future__ import annotations

import re
from typing import Any


_VAULT_REF_RE = re.compile(r"\[Vault:([a-fA-F0-9\-]+)\]")
_UPLOAD_REF_RE = re.compile(
    r"\b(uploaded?\s+(files?|documents?|docs?)|my\s+(uploaded\s+)?(files?|documents?|docs?)|"
    r"using\s+the\s+uploaded|based\s+on\s+my\s+(files?|documents?|docs?)|from\s+my\s+vault|"
    r"vault\s+(files?|documents?|docs?))\b",
    re.I,
)
_TEXT_TYPES = {"upload_document", "organized_document", "transfer_conversation"}


def _member_ids(profile: dict[str, Any]) -> list[str]:
    ids = []
    for key in ("hardware_id", "username"):
        value = str(profile.get(key) or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


async def _read_blob_text(row: Any) -> str:
    blob_path = row.get("blob_path") if hasattr(row, "get") else row["blob_path"]
    mime_type = (row.get("mime_type") if hasattr(row, "get") else row["mime_type"]) or ""
    if not blob_path or not mime_type:
        return ""
    try:
        from app.services.vault.blob_manager import VaultBlobManager
        from app.services.vault.file_processor import FileProcessor

        data = VaultBlobManager().read_blob(blob_path)
        if not data:
            return ""
        processed = FileProcessor().process(row["display_name"] or "vault_upload", data, mime_type)
        return (processed.text or "").strip()
    except Exception as exc:
        print(f">>> [VAULT] Blob text extraction skipped: {type(exc).__name__}: {exc}")
        return ""


async def build_vault_chat_context(db_pool, profile: dict[str, Any], user_text: str) -> tuple[str, str, str | None]:
    """Return (updated_user_text, vault_context, image_data_url)."""
    if not db_pool or not profile or not user_text:
        return user_text, "", None

    ids = _member_ids(profile)
    if not ids:
        return user_text, "", None

    match = _VAULT_REF_RE.search(user_text)
    rows = []
    try:
        if match:
            row = await db_pool.fetchrow(
                """SELECT id, display_name, content_type, extracted_text_preview,
                          blob_path, thumbnail_path, mime_type
                   FROM vault_items
                   WHERE id = $1::uuid AND member_id = ANY($2::text[])""",
                match.group(1), ids,
            )
            if row:
                rows = [row]
                user_text = user_text.replace(match.group(0), f"(referring to my vault item: {row['display_name'] or 'file'})").strip()
        elif _UPLOAD_REF_RE.search(user_text):
            rows = await db_pool.fetch(
                """SELECT id, display_name, content_type, extracted_text_preview,
                          blob_path, thumbnail_path, mime_type
                   FROM vault_items
                   WHERE member_id = ANY($1::text[])
                     AND (content_type = ANY($2::text[]) OR content_type LIKE 'upload_%')
                   ORDER BY COALESCE(uploaded_at, created_at) DESC
                   LIMIT 5""",
                ids, list(_TEXT_TYPES),
            )
    except Exception as exc:
        print(f">>> [VAULT] Chat context query failed: {type(exc).__name__}: {exc}")
        return user_text, "", None

    if not rows:
        return user_text, "", None

    parts = []
    image_data_url = None
    for row in rows:
        name = row["display_name"] or "uploaded file"
        content_type = (row["content_type"] or "").lower()
        if "image" in content_type and image_data_url is None:
            try:
                from app.services.vault.blob_manager import VaultBlobManager
                import base64

                blob_path = row["thumbnail_path"] or row["blob_path"]
                data = VaultBlobManager().read_blob(blob_path) if blob_path else b""
                if data:
                    mime = row["mime_type"] or "image/jpeg"
                    image_data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
                    parts.append(f"[VAULT IMAGE: {name}] The image is attached as a vision block.")
            except Exception as exc:
                print(f">>> [VAULT] Image context skipped: {type(exc).__name__}: {exc}")
            continue

        text = (row["extracted_text_preview"] or "").strip()
        blob_text = await _read_blob_text(row)
        if blob_text:
            text = blob_text
        if text:
            parts.append(f"[VAULT DOCUMENT: {name}]\n{text[:6000]}")

    if not parts:
        return user_text, "", image_data_url

    context = "\n[VAULT UPLOAD CONTEXT — use this when the user asks about uploaded files]\n"
    context += "\n\n".join(parts)[:12000]
    context += "\n[END VAULT UPLOAD CONTEXT]"
    print(f">>> [VAULT] Injected chat upload context items={len(parts)} user={profile.get('username') or profile.get('hardware_id')}")
    return user_text, context, image_data_url
