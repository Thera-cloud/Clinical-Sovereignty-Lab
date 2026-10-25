import importlib.util
import os
import sys

import pytest


_SERVICES = os.path.join(
    os.path.dirname(__file__), "..", "app", "services"
)


def _load(name: str, filename: str):
    path = os.path.join(_SERVICES, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_vault = _load("vault_chat_context_test", "vault_chat_context.py")
build_vault_chat_context = _vault.build_vault_chat_context


class _FakeDB:
    def __init__(self, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    async def fetch(self, *_args, **_kwargs):
        return self._rows

    async def fetchrow(self, *_args, **_kwargs):
        return self._row


@pytest.mark.asyncio
async def test_upload_reference_with_no_rows_injects_note():
    db = _FakeDB(rows=[])
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "Can you use my uploaded documents for this?"
    new_text, ctx, img = await build_vault_chat_context(db, profile, text)
    assert new_text == text
    assert "VAULT CONTEXT NOTE" in ctx
    assert "Do not claim you can never access uploads" in ctx
    assert img is None


@pytest.mark.asyncio
async def test_explicit_vault_ref_injects_document_context():
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "display_name": "notes.pdf",
        "content_type": "upload_document",
        "extracted_text_preview": "Important clinical notes for this week.",
        "blob_path": None,
        "thumbnail_path": None,
        "mime_type": None,
    }
    db = _FakeDB(row=row)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "Can you summarize this? [Vault:11111111-1111-1111-1111-111111111111]"
    new_text, ctx, _img = await build_vault_chat_context(db, profile, text)
    assert "(referring to my vault item: notes.pdf)" in new_text
    assert "[VAULT DOCUMENT: notes.pdf]" in ctx
    assert "Important clinical notes for this week." in ctx


@pytest.mark.asyncio
async def test_matched_row_without_text_gets_fallback_note():
    row = {
        "id": "22222222-2222-2222-2222-222222222222",
        "display_name": "scan.pdf",
        "content_type": "upload_document",
        "extracted_text_preview": "",
        "blob_path": "/quarantine/x",
        "thumbnail_path": None,
        "mime_type": "application/pdf",
    }
    db = _FakeDB(row=row)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "Review [Vault:22222222-2222-2222-2222-222222222222]"
    _new_text, ctx, _img = await build_vault_chat_context(db, profile, text)
    assert "VAULT CONTEXT NOTE" in ctx
    assert "scan.pdf" in ctx
    assert "unavailable" in ctx.lower()


@pytest.mark.asyncio
async def test_vault_sse_panel_row_attaches_vision(monkeypatch):
    async def fake_img(_row):
        return "data:image/jpeg;base64,xyz"

    monkeypatch.setattr(_vault, "_read_image_data_url", fake_img)
    row = {
        "id": "33333333-3333-3333-3333-333333333333",
        "display_name": "neuro_panel: aerolith_cloud_city",
        "content_type": "sse_panel",
        "extracted_text_preview": "",
        "blob_path": "https://example.r2.cloudflarestorage.com/nate-vault/sse/journey/x.png",
        "thumbnail_path": None,
        "mime_type": "image/png",
        "size_bytes": 12000,
    }
    db = _FakeDB(row=row)
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    text = "Look at this photo [Vault:33333333-3333-3333-3333-333333333333]"
    _new, ctx, img = await build_vault_chat_context(db, profile, text)
    assert img == "data:image/jpeg;base64,xyz"
    assert "VAULT IMAGE: neuro_panel: aerolith_cloud_city" in ctx
    assert "pixels" in ctx


@pytest.mark.asyncio
async def test_untagged_photo_prefers_upload_over_sse_panel(monkeypatch):
    async def fake_img(row):
        name = row["display_name"]
        if name.startswith("IMG_"):
            return "data:image/jpeg;base64,upload"
        return None

    monkeypatch.setattr(_vault, "_read_image_data_url", fake_img)
    panel = {
        "id": "11111111-1111-1111-1111-111111111111",
        "display_name": "neuro_panel: cloudstone",
        "content_type": "sse_panel",
        "extracted_text_preview": "",
        "blob_path": "https://example/nate-vault/sse/a.png",
        "thumbnail_path": None,
        "mime_type": "image/png",
        "size_bytes": 12000,
    }
    upload = {
        "id": "22222222-2222-2222-2222-222222222222",
        "display_name": "IMG_9560.jpeg",
        "content_type": "upload_image",
        "extracted_text_preview": "",
        "blob_path": "/app/data/archives/quarantine/photo",
        "thumbnail_path": None,
        "mime_type": "image/jpeg",
        "size_bytes": 4788570,
    }
    db = _FakeDB(rows=[panel, upload])
    profile = {"hardware_id": "CLIENT_1_ID", "username": "client1"}
    _new, ctx, img = await build_vault_chat_context(
        db, profile, "look at this photo I uploaded"
    )
    assert img == "data:image/jpeg;base64,upload"
    assert "IMG_9560.jpeg" in ctx
    assert "IMAGE MISSING" not in ctx


def test_upload_ref_matches_photo_language():
    assert _vault._UPLOAD_REF_RE.search("can you look at this photo I uploaded")
    assert _vault._row_is_image({
        "content_type": "sse_panel",
        "mime_type": "image/png",
        "display_name": "panel.png",
        "blob_path": "https://x/nate-vault/sse/a.png",
    })

