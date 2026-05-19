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

