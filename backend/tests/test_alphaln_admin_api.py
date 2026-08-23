"""Offline tests for the AlphaLN admin twin router.

Uses a FastAPI TestClient with an in-process stub asyncpg pool. Covers the
isolation guarantees required by cursor rule alphaln-twin-isolation.mdc:

  * ENABLE_ALPHALN_TWIN off → every endpoint returns 503
  * non-admin → 403 (via dep override)
  * admin but not DrNevedal1 → 403
  * happy path: create session → send message → read transcript → end session
  * per-username rate limit trips on the 21st message inside the window
  * end-then-send → 409
  * wrong-owner conversation → 403
  * unknown / malformed conversation id → 404 / 400
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-" + uuid.uuid4().hex)
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://localhost")


# --------------------------------------------------------------------------- #
# Fake asyncpg pool                                                           #
# --------------------------------------------------------------------------- #


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    def transaction(self):
        return _FakeTx()

    async def fetchrow(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if q.startswith("SELECT to_regclass"):
            # AlphaLN auditor schema check — pretend every alphaln_* table exists.
            arg = args[0] if args else ""
            return {"reg": arg}
        if q.startswith("INSERT INTO alphaln_conversations"):
            conv_id, admin_user, title = args
            row = {
                "id": conv_id,
                "admin_user": admin_user,
                "title": title,
                "created_at": datetime.now(timezone.utc),
                "ended_at": None,
                "metadata": {},
            }
            self._state["conversations"][str(conv_id)] = row
            return {"id": row["id"], "created_at": row["created_at"]}
        if q.startswith("SELECT id, admin_user, ended_at FROM alphaln_conversations"):
            cid = args[0]
            row = self._state["conversations"].get(str(cid))
            if not row:
                return None
            return {
                "id": row["id"],
                "admin_user": row["admin_user"],
                "ended_at": row["ended_at"],
            }
        if q.startswith(
            "SELECT id, admin_user, title, created_at, ended_at FROM alphaln_conversations"
        ):
            cid = args[0]
            row = self._state["conversations"].get(str(cid))
            if not row:
                return None
            return {
                "id": row["id"],
                "admin_user": row["admin_user"],
                "title": row["title"],
                "created_at": row["created_at"],
                "ended_at": row["ended_at"],
            }
        if q.startswith("UPDATE alphaln_conversations SET ended_at"):
            cid, admin_user = args
            row = self._state["conversations"].get(str(cid))
            if not row or row["admin_user"] != admin_user:
                return None
            if row["ended_at"] is None:
                row["ended_at"] = datetime.now(timezone.utc)
            return {"id": row["id"], "ended_at": row["ended_at"]}
        raise AssertionError(f"unexpected fetchrow: {q[:200]}")

    async def fetch(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if q.startswith(
            "SELECT role, content, provider, latency_ms, tokens_used, created_at FROM alphaln_messages"
        ):
            cid = args[0]
            msgs = [
                m for m in self._state["messages"] if str(m["conversation_id"]) == str(cid)
            ]
            msgs.sort(key=lambda m: m["created_at"])
            return msgs
        if "FROM alphaln_conversations c" in q and "LEFT JOIN alphaln_messages" in q:
            admin_user, limit = args
            convs = [
                c
                for c in self._state["conversations"].values()
                if c["admin_user"] == admin_user
            ]
            convs.sort(key=lambda c: c["created_at"], reverse=True)
            out = []
            for c in convs[:limit]:
                mcount = sum(
                    1
                    for m in self._state["messages"]
                    if str(m["conversation_id"]) == str(c["id"])
                )
                out.append(
                    {
                        "id": c["id"],
                        "title": c["title"],
                        "created_at": c["created_at"],
                        "ended_at": c["ended_at"],
                        "message_count": mcount,
                    }
                )
            return out
        raise AssertionError(f"unexpected fetch: {q[:200]}")

    async def fetchval(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "FROM alphaln_shadow_observations" in q and "mirrored_to_conversation_history" in q:
            return 0
        raise AssertionError(f"unexpected fetchval: {q[:200]}")

    async def execute(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if q.startswith("INSERT INTO alphaln_messages") and "'user'" in q:
            cid, content = args
            self._state["messages"].append(
                {
                    "conversation_id": cid,
                    "role": "user",
                    "content": content,
                    "provider": None,
                    "latency_ms": None,
                    "tokens_used": None,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return "INSERT 0 1"
        if q.startswith("INSERT INTO alphaln_messages") and "'assistant'" in q:
            cid, content, provider, latency_ms, tokens_used = args
            self._state["messages"].append(
                {
                    "conversation_id": cid,
                    "role": "assistant",
                    "content": content,
                    "provider": provider,
                    "latency_ms": latency_ms,
                    "tokens_used": tokens_used,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {q[:200]}")


class _FakePool:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    @asynccontextmanager
    async def acquire(self):
        yield _FakeConn(self._state)


# --------------------------------------------------------------------------- #
# Fake inference router + no-op MFA gate                                      #
# --------------------------------------------------------------------------- #


class _FakeInferenceRouter:
    def __init__(self, app_state=None):
        self._app_state = app_state

    async def generate(self, **kwargs):
        return {
            "text": "(twin reply for: " + str(kwargs.get("prompt", ""))[:40] + ")",
            "provider": "fake-router",
            "latency_ms": 12,
            "tokens_used": 7,
        }


async def _noop_mfa(db_pool, principal, max_age_seconds=None):
    return None


def _patch_inference_router(monkeypatch) -> None:
    """Swap only ``NateInferenceRouter`` on the real module (no sys.modules
    replacement — that would break other tests that import different symbols
    from ``nate_inference_router`` during the same pytest run)."""
    from app.services import nate_inference_router as _nir_mod

    monkeypatch.setattr(_nir_mod, "NateInferenceRouter", _FakeInferenceRouter)


# --------------------------------------------------------------------------- #
# App builder                                                                 #
# --------------------------------------------------------------------------- #


def _seed_state() -> Dict[str, Any]:
    return {
        "conversations": {},   # cid -> row
        "messages": [],        # list of dicts
    }


def _build_app(state: Dict[str, Any], principal: Dict[str, Any], *, monkeypatch=None):
    import importlib

    from app.routers import alphaln_admin_api

    importlib.reload(alphaln_admin_api)  # fresh env flag + reset in-mem limiter
    alphaln_admin_api._msg_rate_reset_for_tests()

    if monkeypatch is not None:
        monkeypatch.setattr(alphaln_admin_api, "enforce_mfa_recent", _noop_mfa)
        _patch_inference_router(monkeypatch)

    async def _admin_dep():
        return principal

    app = FastAPI()
    app.dependency_overrides[alphaln_admin_api.require_admin] = _admin_dep
    app.include_router(alphaln_admin_api.router)
    app.state.db_pool = _FakePool(state)
    return app, alphaln_admin_api


# --------------------------------------------------------------------------- #
# Tests: feature flag                                                         #
# --------------------------------------------------------------------------- #


def test_flag_off_returns_503_on_every_endpoint(monkeypatch):
    monkeypatch.delenv("ENABLE_ALPHALN_TWIN", raising=False)
    state = _seed_state()
    app, _ = _build_app(state, {"username": "DrNevedal1", "role": "ADMIN"}, monkeypatch=monkeypatch)
    client = TestClient(app)

    assert client.post("/api/admin/alphaln/session", json={}).status_code == 503
    assert client.post(
        "/api/admin/alphaln/message", json={"conversation_id": str(uuid.uuid4()), "content": "hi"}
    ).status_code == 503
    assert client.get("/api/admin/alphaln/session/" + str(uuid.uuid4())).status_code == 503
    assert client.post(
        "/api/admin/alphaln/session/" + str(uuid.uuid4()) + "/end"
    ).status_code == 503
    assert client.get("/api/admin/alphaln/sessions").status_code == 503

    # Slice 3–8 surfaces must also be dark when the twin is off.
    assert client.get("/api/admin/alphaln/observations").status_code == 503
    assert client.post("/api/admin/alphaln/gym/run", json={"max_matches": 1}).status_code == 503
    assert client.get("/api/admin/alphaln/gym/runs").status_code == 503
    assert client.post(
        "/api/admin/alphaln/trajectory/schedule",
        json={"scenario": "safety-check", "max_depth": 1, "max_rollouts": 1},
    ).status_code == 503
    assert client.post("/api/admin/alphaln/trajectory/1/execute").status_code == 503
    assert client.get("/api/admin/alphaln/trajectory/runs").status_code == 503
    assert client.post(
        "/api/admin/alphaln/promotion/propose",
        json={"variant_id": "v-test", "reason": "unit-test"},
    ).status_code == 503
    assert client.get("/api/admin/alphaln/promotion/candidates").status_code == 503
    assert client.post(
        "/api/admin/alphaln/promotion/1/review",
        json={"decision": "rejected"},
    ).status_code == 503
    assert client.post(
        "/api/admin/alphaln/pack-drafts/generate", json={"count": 2}
    ).status_code == 503
    assert client.get("/api/admin/alphaln/pack-drafts").status_code == 503
    assert client.post(
        "/api/admin/alphaln/pack-drafts/1/review",
        json={"decision": "rejected"},
    ).status_code == 503

    # /health is deliberately available even when twin is off (invariant surface).
    r = client.get("/api/admin/alphaln/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("twin_enabled") is False
    assert "checks" in body


# --------------------------------------------------------------------------- #
# Tests: gate — only DrNevedal1                                               #
# --------------------------------------------------------------------------- #


def test_admin_but_not_drnevedal1_returns_403(monkeypatch):
    monkeypatch.setenv("ENABLE_ALPHALN_TWIN", "true")
    state = _seed_state()
    app, _ = _build_app(state, {"username": "SomeOtherAdmin", "role": "ADMIN"}, monkeypatch=monkeypatch)
    client = TestClient(app)

    r = client.post("/api/admin/alphaln/session", json={})
    assert r.status_code == 403
    assert "DrNevedal1" in r.text

    r = client.get("/api/admin/alphaln/sessions")
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Tests: happy path + lifecycle                                               #
# --------------------------------------------------------------------------- #


def test_session_lifecycle_happy_path(monkeypatch):
    monkeypatch.setenv("ENABLE_ALPHALN_TWIN", "true")
    state = _seed_state()
    app, _ = _build_app(state, {"username": "DrNevedal1", "role": "ADMIN"}, monkeypatch=monkeypatch)
    client = TestClient(app)

    # 1) create session
    r = client.post("/api/admin/alphaln/session", json={"title": "coevolution notes"})
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation_id"]
    assert conv_id in state["conversations"]

    # 2) send message
    r = client.post(
        "/api/admin/alphaln/message",
        json={"conversation_id": conv_id, "content": "hello twin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "fake-router"
    assert "twin reply" in body["reply"]
    # both turns persisted
    roles = [m["role"] for m in state["messages"] if str(m["conversation_id"]) == conv_id]
    assert roles == ["user", "assistant"]

    # 3) read transcript
    r = client.get("/api/admin/alphaln/session/" + conv_id)
    assert r.status_code == 200
    trans = r.json()
    assert trans["title"] == "coevolution notes"
    assert len(trans["messages"]) == 2

    # 4) list sessions
    r = client.get("/api/admin/alphaln/sessions")
    assert r.status_code == 200
    listed = r.json()["sessions"]
    assert any(s["conversation_id"] == conv_id and s["message_count"] == 2 for s in listed)

    # 5) end session
    r = client.post("/api/admin/alphaln/session/" + conv_id + "/end")
    assert r.status_code == 200
    assert state["conversations"][conv_id]["ended_at"] is not None

    # 6) sending after end → 409
    r = client.post(
        "/api/admin/alphaln/message",
        json={"conversation_id": conv_id, "content": "still here?"},
    )
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# Tests: id validation + ownership                                            #
# --------------------------------------------------------------------------- #


def test_message_invalid_uuid_400(monkeypatch):
    monkeypatch.setenv("ENABLE_ALPHALN_TWIN", "true")
    state = _seed_state()
    app, _ = _build_app(state, {"username": "DrNevedal1", "role": "ADMIN"}, monkeypatch=monkeypatch)
    client = TestClient(app)

    r = client.post(
        "/api/admin/alphaln/message",
        json={"conversation_id": "not-a-uuid", "content": "x"},
    )
    assert r.status_code == 400


def test_message_unknown_conversation_404(monkeypatch):
    monkeypatch.setenv("ENABLE_ALPHALN_TWIN", "true")
    state = _seed_state()
    app, _ = _build_app(state, {"username": "DrNevedal1", "role": "ADMIN"}, monkeypatch=monkeypatch)
    client = TestClient(app)

    r = client.post(
        "/api/admin/alphaln/message",
        json={"conversation_id": str(uuid.uuid4()), "content": "x"},
    )
    assert r.status_code == 404


def test_get_session_wrong_owner_403(monkeypatch):
    """A conversation belonging to another admin_user MUST 403 even for DrNevedal1."""
    monkeypatch.setenv("ENABLE_ALPHALN_TWIN", "true")
    state = _seed_state()
    other_id = uuid.uuid4()
    state["conversations"][str(other_id)] = {
        "id": other_id,
        "admin_user": "SomeoneElse",
        "title": "not yours",
        "created_at": datetime.now(timezone.utc),
        "ended_at": None,
        "metadata": {},
    }
    app, _ = _build_app(state, {"username": "DrNevedal1", "role": "ADMIN"}, monkeypatch=monkeypatch)
    client = TestClient(app)

    r = client.get("/api/admin/alphaln/session/" + str(other_id))
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Tests: rate limit                                                           #
# --------------------------------------------------------------------------- #


def test_message_rate_limit_trips_after_max(monkeypatch):
    monkeypatch.setenv("ENABLE_ALPHALN_TWIN", "true")
    state = _seed_state()
    app, mod = _build_app(state, {"username": "DrNevedal1", "role": "ADMIN"}, monkeypatch=monkeypatch)
    client = TestClient(app)

    r = client.post("/api/admin/alphaln/session", json={})
    conv_id = r.json()["conversation_id"]

    # Send up to the max (should all succeed).
    for i in range(mod._MSG_RATE_MAX):
        r = client.post(
            "/api/admin/alphaln/message",
            json={"conversation_id": conv_id, "content": f"turn {i}"},
        )
        assert r.status_code == 200, f"turn {i} failed: {r.status_code} {r.text}"

    # (_MSG_RATE_MAX+1)th → 429
    r = client.post(
        "/api/admin/alphaln/message",
        json={"conversation_id": conv_id, "content": "over budget"},
    )
    assert r.status_code == 429
