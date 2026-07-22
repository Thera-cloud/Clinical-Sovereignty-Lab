"""Offline tests for SI/violence coach alert — load modules via importlib to avoid
app.services.__init__ (numpy) side effects on some macOS Pythons."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name: str, filename: str):
    path = _SERVICES / filename
    mod_name = f"app.services.{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec so intra-package imports resolve
    sys.modules[mod_name] = mod
    # Ensure parent package stubs exist without importing __init__
    import types

    if "app" not in sys.modules:
        app_pkg = types.ModuleType("app")
        app_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "app")]  # type: ignore[attr-defined]
        sys.modules["app"] = app_pkg
    if "app.services" not in sys.modules:
        svc = types.ModuleType("app.services")
        svc.__path__ = [str(_SERVICES)]  # type: ignore[attr-defined]
        sys.modules["app.services"] = svc
    sys.modules["app"].services = sys.modules["app.services"]
    spec.loader.exec_module(mod)
    setattr(sys.modules["app.services"], name, mod)
    return mod


lex = _load("suicide_ideation_lexicon", "suicide_ideation_lexicon.py")
# coach_handoff may pull heavier deps — stub before loading alert module
if "app.services.coach_handoff" not in sys.modules:
    import types

    ch = types.ModuleType("app.services.coach_handoff")

    async def _resolve_assigned_coach_username(db_pool, profile):
        return (profile or {}).get("assigned_coach") or None

    ch._resolve_assigned_coach_username = _resolve_assigned_coach_username
    sys.modules["app.services.coach_handoff"] = ch
    sys.modules["app.services"].coach_handoff = ch

# Stub dispatcher target used by maybe_dispatch (lazy import inside function)
if "app.services.sensitive_alert_dispatcher" not in sys.modules:
    import types

    sad = types.ModuleType("app.services.sensitive_alert_dispatcher")

    async def dispatch_sensitive_alert(**kwargs):
        return {"notification_id": 0, "coach_notified": False}

    sad.dispatch_sensitive_alert = dispatch_sensitive_alert
    sys.modules["app.services.sensitive_alert_dispatcher"] = sad
    sys.modules["app.services"].sensitive_alert_dispatcher = sad

alert = _load("suicide_ideation_coach_alert", "suicide_ideation_coach_alert.py")
maybe_dispatch_si_coach_alert = alert.maybe_dispatch_si_coach_alert
match_user_text = lex.match_user_text
match_si_user_text = lex.match_si_user_text
match_violence_user_text = lex.match_violence_user_text


def _patch_dispatch(mock):
    return patch.object(
        sys.modules["app.services.sensitive_alert_dispatcher"],
        "dispatch_sensitive_alert",
        new=mock,
    )


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


def test_lexicon_matches_active_si():
    assert "kill myself" in match_user_text("I want to kill myself tonight")
    assert match_user_text("I'm going to die laughing") == []


def test_lexicon_self_harm_phrases():
    hits = match_user_text("I've been cutting myself again")
    assert "cut myself" in hits or "self-harm" in hits or "hurt myself" in hits


def test_lexicon_violence_phrases():
    assert "kill them" in match_violence_user_text(
        "I'm going to kill him when I see him"
    )
    assert match_violence_user_text("I'd kill for a pizza") == []
    assert match_si_user_text("I'm going to kill him when I see him") == []


def test_lexicon_union_includes_violence():
    hits = match_user_text("I plan to kill someone")
    assert "kill someone" in hits


@pytest.mark.asyncio
async def test_maybe_dispatch_disabled_when_flag_off():
    pool = _FakePool(AsyncMock())
    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "false"}, clear=False):
        result = await maybe_dispatch_si_coach_alert(
            pool,
            {"username": "client_a", "role": "CLIENT", "assigned_coach": "CoachN"},
            "I want to kill myself",
        )
    assert result["status"] == "disabled"


@pytest.mark.asyncio
async def test_maybe_dispatch_default_on_without_env_true():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    pool = _FakePool(conn)
    profile = {
        "username": "client_a",
        "role": "CLIENT",
        "assigned_coach": "CoachN",
        "hardware_id": "CLIENT_A_ID",
    }
    env = {k: v for k, v in os.environ.items() if k != "ENABLE_UNIVERSAL_SI_COACH_ALERT"}
    with patch.dict(os.environ, env, clear=True), _patch_dispatch(
        AsyncMock(return_value={"notification_id": 42, "coach_notified": True})
    ) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(
            pool, profile, "I want to kill myself"
        )
    assert result["status"] == "dispatched"
    dispatch_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_maybe_dispatch_skips_dojo_simulation():
    pool = _FakePool(AsyncMock())
    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true"}, clear=False):
        result = await maybe_dispatch_si_coach_alert(
            pool,
            {"username": "client_a", "role": "CLIENT", "assigned_coach": "CoachN"},
            "[DOJO SIMULATION] I want to kill myself",
        )
    assert result["status"] == "skipped"
    assert result["reason"] == "simulation_or_synthesis"


@pytest.mark.asyncio
async def test_maybe_dispatch_dispatches_on_match():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    pool = _FakePool(conn)
    profile = {
        "username": "client_a",
        "role": "CLIENT",
        "assigned_coach": "CoachN",
        "hardware_id": "CLIENT_A_ID",
    }
    dispatch_receipt = {
        "event_id": 11,
        "coach_notified": True,
        "notification_id": 88,
        "email_sent": True,
    }

    with patch.dict(
        os.environ,
        {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true", "SI_COACH_ALERT_DEDUP_HOURS": "24"},
        clear=False,
    ), _patch_dispatch(AsyncMock(return_value=dispatch_receipt)) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(
            pool, profile, "I want to kill myself", turn_id="turn-si-1"
        )

    assert result["status"] == "dispatched"
    assert result["notification_id"] == 88
    assert result["alert_type"] == "suicidal_ideation_escalation"
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.await_args.kwargs["alert_type"] == "suicidal_ideation_escalation"
    assert dispatch_mock.await_args.kwargs["risk_level"] == "critical"
    assert "kill myself" in dispatch_mock.await_args.kwargs["keywords"]


@pytest.mark.asyncio
async def test_maybe_dispatch_violence_alert_type():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    pool = _FakePool(conn)
    profile = {
        "username": "client_a",
        "role": "CLIENT",
        "assigned_coach": "CoachN",
        "hardware_id": "CLIENT_A_ID",
    }

    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true"}, clear=False), _patch_dispatch(
        AsyncMock(return_value={"notification_id": 99, "coach_notified": True})
    ) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(
            pool, profile, "I'm going to kill him tonight"
        )

    assert result["status"] == "dispatched"
    assert result["alert_type"] == "violence_ideation_escalation"
    assert dispatch_mock.await_args.kwargs["alert_type"] == "violence_ideation_escalation"


@pytest.mark.asyncio
async def test_maybe_dispatch_dedup_skips_second_alert():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"?column?": 1})
    pool = _FakePool(conn)
    profile = {"username": "client_a", "role": "CLIENT", "assigned_coach": "CoachN"}

    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true"}, clear=False), _patch_dispatch(
        AsyncMock()
    ) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(pool, profile, "I want to kill myself")

    assert result["status"] == "duplicate"
    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_dispatch_no_coach():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    pool = _FakePool(conn)
    profile = {"username": "client_a", "role": "CLIENT"}

    with patch.dict(os.environ, {"ENABLE_UNIVERSAL_SI_COACH_ALERT": "true"}, clear=False), patch.object(
        alert, "_resolve_assigned_coach_username", new=AsyncMock(return_value=None)
    ), _patch_dispatch(AsyncMock()) as dispatch_mock:
        result = await maybe_dispatch_si_coach_alert(pool, profile, "I want to kill myself")

    assert result["status"] == "error"
    assert result["reason"] == "no_assigned_coach"
    dispatch_mock.assert_not_awaited()
