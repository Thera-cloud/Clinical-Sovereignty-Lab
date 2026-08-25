"""Smoke tests for the cohort enrollment API.

Uses a FastAPI TestClient with an in-process stub asyncpg pool. The stub
tracks enrollment_codes, enrollment_redemptions, and users so the tests can
assert the full transactional path (verify → redeem → increment uses →
stamp users.program_id) without touching a real DB.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
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
        if "FROM enrollment_codes WHERE code = $1" in q:
            code = args[0]
            row = self._state["codes"].get(code)
            return dict(row) if row else None
        if "FROM users WHERE username = $1" in q and "program_id" in q:
            username = args[0]
            u = self._state["users"].get(username)
            if not u:
                return None
            return {"id": u["id"], "program_id": u["program_id"]}
        if "FROM enrollment_codes WHERE id = $1" in q and "revoked_at" in q:
            code_id = args[0]
            for c in self._state["codes"].values():
                if str(c["id"]) == str(code_id):
                    return {"revoked_at": c.get("revoked_at")}
            return None
        raise AssertionError(f"unexpected fetchrow: {q[:160]}")

    async def fetch(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "FROM enrollment_codes" in q and "ORDER BY created_at" in q:
            return [dict(c) for c in self._state["codes"].values()]
        raise AssertionError(f"unexpected fetch: {q[:160]}")

    async def execute(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "INSERT INTO enrollment_redemptions" in q:
            code_id, user_id, username, program_id, src_ip, ua = args
            key = (str(code_id), str(user_id))
            if key in self._state["redemptions"]:
                raise RuntimeError(
                    "duplicate key value violates unique constraint "
                    '"enrollment_redemptions_unique"'
                )
            self._state["redemptions"][key] = {
                "code_id": code_id,
                "user_id": user_id,
                "username": username,
                "program_id": program_id,
                "source_ip": src_ip,
                "user_agent": ua,
            }
            return "INSERT 0 1"
        if "UPDATE enrollment_codes SET uses" in q:
            code_id = args[0]
            for c in self._state["codes"].values():
                if str(c["id"]) == str(code_id):
                    c["uses"] = c.get("uses", 0) + 1
                    return "UPDATE 1"
            return "UPDATE 0"
        if "UPDATE users SET program_id" in q:
            program_id, user_id = args
            for u in self._state["users"].values():
                if str(u["id"]) == str(user_id):
                    u["program_id"] = program_id
                    return "UPDATE 1"
            return "UPDATE 0"
        if "UPDATE enrollment_codes SET revoked_at" in q:
            code_id = args[0]
            for c in self._state["codes"].values():
                if str(c["id"]) == str(code_id):
                    c["revoked_at"] = datetime.now(timezone.utc)
                    return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected execute: {q[:160]}")


class _FakePool:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    @asynccontextmanager
    async def acquire(self):
        yield _FakeConn(self._state)


# --------------------------------------------------------------------------- #
# App builder                                                                 #
# --------------------------------------------------------------------------- #


def _seed_state(**overrides) -> Dict[str, Any]:
    user_id = uuid.uuid4()
    code_id = uuid.uuid4()
    state: Dict[str, Any] = {
        "users": {
            "alice": {
                "id": user_id,
                "username": "alice",
                "program_id": None,
            },
        },
        "codes": {
            "BEE-2026-ABC": {
                "id": code_id,
                "code": "BEE-2026-ABC",
                "program_id": "bee_hiv_plus",
                "max_uses": None,
                "uses": 0,
                "expires_at": None,
                "revoked_at": None,
                "created_by": "DrNevedal1",
                "notes": None,
                "created_at": datetime.now(timezone.utc),
            }
        },
        "redemptions": {},
    }
    state.update(overrides)
    return state


def _build_app(state: Dict[str, Any], principal: Dict[str, Any]):
    """Mount enrollment router with stubbed auth + db_pool."""
    import importlib

    from app.routers import enrollment_api

    importlib.reload(enrollment_api)  # ensure fresh env flag read

    async def _user_dep():
        return principal

    async def _admin_dep():
        return {**principal, "role": "ADMIN"}

    app = FastAPI()
    app.dependency_overrides[enrollment_api.get_current_user] = _user_dep
    app.dependency_overrides[enrollment_api.require_admin] = _admin_dep
    app.include_router(enrollment_api.router)
    app.state.db_pool = _FakePool(state)
    return app


# --------------------------------------------------------------------------- #
# Tests: feature flag                                                         #
# --------------------------------------------------------------------------- #


def test_flag_off_returns_503(monkeypatch):
    monkeypatch.delenv("ENABLE_ENROLLMENT_API", raising=False)
    state = _seed_state()
    principal = {"username": "alice", "role": "CLIENT"}
    app = _build_app(state, principal)
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 503
    r = client.get("/api/enrollment/status")
    assert r.status_code == 503


def test_flag_on_allows_status(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    principal = {"username": "alice", "role": "CLIENT"}
    app = _build_app(state, principal)
    client = TestClient(app)

    r = client.get("/api/enrollment/status")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert body["program_id"] is None


# --------------------------------------------------------------------------- #
# Tests: redemption happy path + guards                                       #
# --------------------------------------------------------------------------- #


def test_redeem_happy_path(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    principal = {"username": "alice", "role": "CLIENT"}
    app = _build_app(state, principal)
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "enrolled"
    assert body["program_id"] == "bee_hiv_plus"

    # DB side-effects
    assert state["users"]["alice"]["program_id"] == "bee_hiv_plus"
    assert state["codes"]["BEE-2026-ABC"]["uses"] == 1
    assert len(state["redemptions"]) == 1


def test_redeem_unknown_code(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    app = _build_app(state, {"username": "alice", "role": "CLIENT"})
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "NOPE"})
    assert r.status_code == 404


def test_redeem_revoked_code(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    state["codes"]["BEE-2026-ABC"]["revoked_at"] = datetime.now(timezone.utc)
    app = _build_app(state, {"username": "alice", "role": "CLIENT"})
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 410


def test_redeem_expired_code(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    state["codes"]["BEE-2026-ABC"]["expires_at"] = datetime.now(
        timezone.utc
    ) - timedelta(minutes=1)
    app = _build_app(state, {"username": "alice", "role": "CLIENT"})
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 410


def test_redeem_exhausted_code(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    state["codes"]["BEE-2026-ABC"]["max_uses"] = 1
    state["codes"]["BEE-2026-ABC"]["uses"] = 1
    app = _build_app(state, {"username": "alice", "role": "CLIENT"})
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 410


def test_redeem_unknown_cohort_500(monkeypatch):
    """Codes minted with an unknown program_id must fail closed at redeem."""
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    state["codes"]["BEE-2026-ABC"]["program_id"] = "ghost_cohort"
    app = _build_app(state, {"username": "alice", "role": "CLIENT"})
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 500


def test_redeem_already_enrolled_409(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    state["users"]["alice"]["program_id"] = "bee_hiv_plus"
    app = _build_app(state, {"username": "alice", "role": "CLIENT"})
    client = TestClient(app)

    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["code"] == "ALREADY_ENROLLED"
    assert body["current_program_id"] == "bee_hiv_plus"


def test_redeem_duplicate_by_same_user_409(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    principal = {"username": "alice", "role": "CLIENT"}
    app = _build_app(state, principal)
    client = TestClient(app)

    r1 = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r1.status_code == 200

    # Clear program_id so the duplicate check triggers on the unique constraint,
    # not on the already-enrolled path (this simulates admin nulling program_id
    # while leaving the redemption row intact — a state we still want to reject).
    state["users"]["alice"]["program_id"] = None

    r2 = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r2.status_code == 409


# --------------------------------------------------------------------------- #
# Tests: admin endpoints                                                      #
# --------------------------------------------------------------------------- #


def test_admin_create_code_unknown_cohort_400(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state: Dict[str, Any] = {"users": {}, "codes": {}, "redemptions": {}}
    principal = {"username": "DrNevedal1", "role": "ADMIN"}
    app = _build_app(state, principal)
    client = TestClient(app)

    r = client.post(
        "/api/enrollment/codes",
        json={"code": "GHOST-1", "program_id": "not_a_cohort"},
    )
    assert r.status_code == 400


def test_admin_revoke_flow(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    code_id = str(state["codes"]["BEE-2026-ABC"]["id"])
    principal = {"username": "DrNevedal1", "role": "ADMIN"}
    app = _build_app(state, principal)
    client = TestClient(app)

    r1 = client.post(f"/api/enrollment/codes/{code_id}/revoke")
    assert r1.status_code == 200
    assert state["codes"]["BEE-2026-ABC"]["revoked_at"] is not None

    r2 = client.post(f"/api/enrollment/codes/{code_id}/revoke")
    assert r2.status_code == 409  # already revoked


def test_admin_list_codes(monkeypatch):
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    principal = {"username": "DrNevedal1", "role": "ADMIN"}
    app = _build_app(state, principal)
    client = TestClient(app)

    r = client.get("/api/enrollment/codes")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["codes"][0]["code"] == "BEE-2026-ABC"
    assert body["codes"][0]["program_id"] == "bee_hiv_plus"


# --------------------------------------------------------------------------- #
# Tests: redeem rate limiting                                                 #
# --------------------------------------------------------------------------- #


def test_redeem_rate_limit_blocks_6th_attempt(monkeypatch):
    """5 attempts/60s per (IP, username). 6th must be 429."""
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")
    state = _seed_state()
    principal = {"username": "alice", "role": "CLIENT"}
    app = _build_app(state, principal)
    client = TestClient(app)

    # First 5 attempts with an unknown code → 404 (rate check runs before DB
    # lookup so this exercises the limiter, not code-validation logic).
    for i in range(5):
        r = client.post("/api/enrollment/redeem", json={"code": f"NOPE-{i}"})
        assert r.status_code == 404, f"attempt {i+1}: {r.status_code} {r.text}"

    # 6th attempt: over budget → 429 regardless of code validity.
    r = client.post("/api/enrollment/redeem", json={"code": "BEE-2026-ABC"})
    assert r.status_code == 429, r.text
    assert "try again" in r.json()["detail"].lower()

    # State must NOT show a redemption or program_id write.
    assert state["users"]["alice"]["program_id"] is None
    assert len(state["redemptions"]) == 0


def test_redeem_rate_limit_isolates_users(monkeypatch):
    """A different username on the same client host has its own budget."""
    monkeypatch.setenv("ENABLE_ENROLLMENT_API", "true")

    # Alice: burn through her budget.
    state_a = _seed_state()
    state_a["users"]["bob"] = {
        "id": uuid.uuid4(),
        "username": "bob",
        "program_id": None,
    }
    app_a = _build_app(state_a, {"username": "alice", "role": "CLIENT"})
    client_a = TestClient(app_a)
    for i in range(6):
        client_a.post("/api/enrollment/redeem", json={"code": f"NOPE-{i}"})
    over = client_a.post("/api/enrollment/redeem", json={"code": "STILL-NOPE"})
    assert over.status_code == 429, "alice should now be rate-limited"

    # Bob (different username) on the same app must still be allowed. We reload
    # the router module via _build_app to fake a fresh process for Bob only if
    # we wanted cross-process isolation, but here we want the SAME limiter
    # state and verify the key includes username.
    from app.routers import enrollment_api

    app_a.dependency_overrides[enrollment_api.get_current_user] = (
        lambda: {"username": "bob", "role": "CLIENT"}
    )
    r_bob = client_a.post("/api/enrollment/redeem", json={"code": "NOPE-BOB"})
    assert r_bob.status_code == 404, r_bob.text


def test_redeem_sql_casts_program_id_for_asyncpg():
    """asyncpg rejects $1 used as both text column and to_jsonb($1::text)."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "routers" / "enrollment_api.py"
    text = src.read_text()
    assert "program_id = $1::text" in text
    assert "to_jsonb($1::text)" in text
