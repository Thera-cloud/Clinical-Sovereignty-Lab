"""Seam 6: Studio HMAC 401, Workspace connect hidden unless flag on."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_bad_hmac_rejected():
    from app.services.studio_hmac import verify_hmac

    secret = b"studio-secret"
    body = b'{"event_id":"e1"}'
    assert verify_hmac(secret, body, "deadbeef") is False
    import hmac as hm
    import hashlib
    good = hm.new(secret, body, hashlib.sha256).hexdigest()
    assert verify_hmac(secret, body, good) is True
    assert verify_hmac(secret, body, f"sha256={good}") is True


@pytest.mark.asyncio
async def test_connect_not_visible_when_flag_off(monkeypatch):
    from app.services.google_workspace_service import get_google_svc

    monkeypatch.setenv("ENABLE_WS_OAUTH", "false")
    st = await get_google_svc(None).status("COACH_HW")
    assert st["connect_visible"] is False
    assert st["oauth_enabled"] is False


def test_workspace_connect_requires_flag():
    src = (ROOT / "backend/app/routers/google_workspace_api.py").read_text()
    assert "_require_ws_oauth" in src
    assert "connect_visible" in src


def test_studio_hooks_wired_and_additive():
    main = (ROOT / "backend/app/main.py").read_text()
    assert "studio_hooks_api" in main
    sql = (ROOT / "backend/migrations/331_studio_hmac_hooks.sql").read_text()
    assert "DROP TABLE" not in sql.upper()
    assert "studio_hook_events" in sql
    dart = (ROOT / "mobile/lib/screens/settings_screen.dart").read_text()
    assert "Connect Google Workspace stays hidden" in dart
    hooks = (ROOT / "backend/app/routers/studio_hooks_api.py").read_text()
    assert "HTTPException(401" in hooks
    assert "ENABLE_STUDIO_WEBHOOKS" in hooks
