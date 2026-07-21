"""Offline smoke tests for Coach Command wiring fixes (Jul 2026)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_bridge_mesh_engine_helper_at_module_scope():
    src = (REPO / "backend/app/websocket/bridge_server.py").read_text()
    assert "def _resolve_bridge_mesh_engine(db_pool):" in src
    assert src.count("_resolve_bridge_mesh_engine(db_pool)") >= 10
    # Must not still look up FastAPI app.state for mesh
    assert "coaching_mesh_engine', None) if _app else None" not in src
    ast.parse(src)


def test_bridge_w9_accepts_flutter_aliases():
    src = (REPO / "backend/app/websocket/bridge_server.py").read_text()
    assert '("street", "address_street")' in src
    assert '("certified", "certification")' in src
    assert '"w9_data": coach_data.get("w9_data")' in src


def test_hierarchy_rest_invite_pending_admin():
    src = (REPO / "backend/app/routers/coach_hierarchy_api.py").read_text()
    assert "VALUES ($1, $2, 'pending_admin')" in src


def test_flutter_coach_command_critical_wiring():
    src = (REPO / "mobile/lib/updated_screens.dart").read_text()
    assert "widget.currentUserProfile['token'] = _authToken" in src
    assert "_tabController.animateTo(3); // BRIEFINGS" in src
    assert "c['hardware_id'] ?? c['client_id'] ?? c['id']" in src
    assert '"address_street": streetCtrl.text.trim()' in src
    assert '"certification": true' in src
    assert "CoachQuickBooksTab" in src
    assert "highRisk.toString()" in src
    assert "sessionsToday.toString()" in src
    assert "SESSION FOCUS" in src


def test_coaching_mesh_uses_token_auth():
    src = (REPO / "mobile/lib/screens/coaching_mesh_screen.dart").read_text()
    assert "'type': 'auth'" in src
    assert "password_hash" not in src
    assert "auth_success" in src
    assert "_wsAuthed" in src
