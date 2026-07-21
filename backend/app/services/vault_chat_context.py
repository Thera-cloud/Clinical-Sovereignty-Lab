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
# Soft trigger for Google AI Mode / Gemini Apps MyActivity exports uploaded as vault docs
_AI_EXPORT_REF_RE = re.compile(
    r"\b(google\s+(ai|gemini|history)|ai\s+mode|myactivity|gemini\s+(history|chats?|export|apps?)|"
    r"downloaded?\s+(my\s+)?(ai|chat|gemini)|from\s+(my\s+)?google|"
    r"my\s+(google|gemini)\s+(chats?|history|export))\b",
    re.I,
)
_TEXT_TYPES = {"upload_document", "organized_document", "transfer_conversation"}
_AI_EXPORT_INJECT_CHARS = 50_000
_DEFAULT_INJECT_CHARS = 6_000
_CONTEXT_BUDGET = 24_000


def _member_ids(profile: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("hardware_id", "username", "id", "user_id"):
        value = str(profile.get(key) or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def _is_ai_export_row(row: Any) -> bool:
    name = ((row.get("display_name") if hasattr(row, "get") else row["display_name"]) or "").lower()
    preview = (row.get("extracted_text_preview") if hasattr(row, "get") else row["extracted_text_preview"]) or ""
    head = preview[:800]
    return (
        "myactivity" in name
        or "ai mode" in name
        or "google ai mode" in name
        or ("Your prompt:" in head and "Search" in head and "response:" in head)
        or head.lstrip().startswith("AI Mode")
    )


async def _read_blob_text(row: Any, *, max_chars: int = 50_000) -> str:
    blob_path = row.get("blob_path") if hasattr(row, "get") else row["blob_path"]
    mime_type = (row.get("mime_type") if hasattr(row, "get") else row["mime_type"]) or ""
    display_name = (row.get("display_name") if hasattr(row, "get") else row["display_name"]) or "vault_upload"
    if not blob_path:
        return ""
    try:
        from app.services.vault.blob_manager import VaultBlobManager
        from app.services.vault.file_processor import FileProcessor, _looks_like_ai_chat_export

        data = VaultBlobManager().read_blob(blob_path)
        if not data:
            return ""
        # Prefer raw decode for known AI Mode exports (bypass 50k PDF-oriented cap path)
        try:
            raw = data.decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        if raw and (_looks_like_ai_chat_export(raw) or _is_ai_export_row(row)):
            return raw[:max_chars].strip()
        mime = mime_type or "text/plain"
        processed = FileProcessor().process(display_name, data, mime)
        return ((processed.text or "")[:max_chars]).strip()
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
    upload_ref = bool(_UPLOAD_REF_RE.search(user_text))
    ai_export_ref = bool(_AI_EXPORT_REF_RE.search(user_text))
    rows = []
    try:
        if match:
            row = await db_pool.fetchrow(
                """SELECT id, display_name, content_type, extracted_text_preview,
                          blob_path, thumbnail_path, mime_type, size_bytes
                   FROM vault_items
                   WHERE id = $1::uuid AND member_id = ANY($2::text[])""",
                match.group(1), ids,
            )
            if row:
                rows = [row]
                user_text = user_text.replace(match.group(0), f"(referring to my vault item: {row['display_name'] or 'file'})").strip()
        elif upload_ref or ai_export_ref:
            rows = await db_pool.fetch(
                """SELECT id, display_name, content_type, extracted_text_preview,
                          blob_path, thumbnail_path, mime_type, size_bytes
                   FROM vault_items
                   WHERE member_id = ANY($1::text[])
                     AND (content_type = ANY($2::text[]) OR content_type LIKE 'upload_%')
                   ORDER BY COALESCE(uploaded_at, created_at) DESC
                   LIMIT 8""",
                ids, list(_TEXT_TYPES),
            )
            # Prefer AI export / transfer threads when user asked about Google/Gemini history
            if ai_export_ref and rows:
                ranked = sorted(
                    rows,
                    key=lambda r: (
                        0 if (r["content_type"] or "") == "transfer_conversation" else 1,
                        0 if _is_ai_export_row(r) else 1,
                    ),
                )
                rows = ranked[:5]
    except Exception as exc:
        print(f">>> [VAULT] Chat context query failed: {type(exc).__name__}: {exc}")
        return user_text, "", None

    if not rows:
        if upload_ref or ai_export_ref:
            # Gap 2 hardening: if the user references uploads but no vault rows
            # resolve, inject explicit context so Nate asks for a re-reference
            # instead of claiming no access.
            return (
                user_text,
                "[VAULT CONTEXT NOTE] The user referenced uploaded files, but no vault "
                "items were resolved for this turn. Do not claim you can never access "
                "uploads. Ask them to specify the file name or re-attach/share the item.",
                None,
            )
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
        try:
            size_bytes = int(row["size_bytes"] or 0)
        except (KeyError, TypeError, ValueError):
            size_bytes = 0
        ai_export = _is_ai_export_row(row) or content_type == "transfer_conversation"
        inject_n = _AI_EXPORT_INJECT_CHARS if ai_export else _DEFAULT_INJECT_CHARS

        # Truncated preview vs full blob (classic 500-char preview bug)
        preview_truncated = (
            bool(row["blob_path"])
            and size_bytes > 0
            and (len(text) < 40 or size_bytes > len(text) + 200)
        )
        if preview_truncated or (ai_export and len(text) < 2000 and row["blob_path"]):
            blob_text = await _read_blob_text(row, max_chars=inject_n)
            if blob_text and len(blob_text) > len(text):
                text = blob_text

        if text:
            label = "IMPORTED AI HISTORY" if ai_export else "VAULT DOCUMENT"
            note = ""
            if ai_export:
                note = (
                    "\n(Pre-Sanctuary export — Nate was NOT in these threads. "
                    "Cite as their Google/Gemini/AI Mode history.)"
                )
            parts.append(f"[{label}: {name}]{note}\n{text[:inject_n]}")

    if not parts:
        if rows:
            names = ", ".join((r["display_name"] or "file") for r in rows[:3])
            fallback = (
                "[VAULT CONTEXT NOTE] The user attached vault item(s): "
                f"{names}. Full text extraction was unavailable this turn. "
                "Acknowledge the attachment and invite them to describe what they need from it."
            )
            return user_text, fallback, image_data_url
        return user_text, "", image_data_url

    context = "\n[VAULT UPLOAD CONTEXT — use this when the user asks about uploaded files]\n"
    context += "\n\n".join(parts)[:_CONTEXT_BUDGET]
    context += "\n[END VAULT UPLOAD CONTEXT]"
    print(f">>> [VAULT] Injected chat upload context items={len(parts)} user={profile.get('username') or profile.get('hardware_id')}")
    return user_text, context, image_data_url
