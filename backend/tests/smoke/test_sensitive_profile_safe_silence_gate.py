"""Smoke test for Phase 4b two-step safe_silence_mode gate.

Exercises three contracts WITHOUT a real database:

  1. safe_silence_two_step_gate_same_session_blocked
       → same JWT proposes + approves → 409 same_session_violation
  2. safe_silence_codeword_precondition_enforced
       → zero active codewords + approve → 409 requires_codeword
  3. happy path: different JWT + 1 active codeword → 200 active

Uses FastAPI TestClient with an in-process stub asyncpg pool. The stub
records every UPDATE/INSERT so the test can assert the JSONB transition.

Run: pytest backend/tests/smoke/test_sensitive_profile_safe_silence_gate.py -v
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Force JWT_SECRET so app.services.api_server import succeeds inside the
# test process without leaking secrets into the test fixture.
os.environ.setdefault("JWT_SECRET", "test-secret-" + uuid.uuid4().hex)
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://localhost")


# -----------------------------------------------------------------------------
# Fake asyncpg pool / connection
# -----------------------------------------------------------------------------


class _FakeConn:
    """Minimal asyncpg.Connection stand-in: records calls + returns canned rows."""

    def __init__(self, state: Dict[str, Any]):
        self._state = state

    async def fetchrow(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "FROM users WHERE username = $1" in q:
            user_id = args[0]
            user = self._state["users"].get(user_id)
            if user is None:
                return None
            return {"profile_data": user["profile_data"]}
        raise AssertionError(f"unexpected fetchrow: {q[:120]}")

    async def fetchval(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "COUNT(*) FROM user_safety_codewords" in q:
            user_id = args[0]
            return self._state["codeword_counts"].get(user_id, 0)
        if "COUNT(*) FROM coach_client_overrides" in q:
            return 1  # always assigned for tests
        raise AssertionError(f"unexpected fetchval: {q[:120]}")

    async def execute(self, query: str, *args, **kwargs):
        q = " ".join(query.split())
        if "UPDATE users" in q and "safe_silence_mode_state" in q:
            user_id = args[0]
            new_jsonb = json.loads(args[1]) if len(args) > 1 else {}
            user = self._state["users"][user_id]
            user["profile_data"]["safe_silence_mode_state"] = new_jsonb
            self._state["audit_writes"].append(
                {"user_id": user_id, "new_state": new_jsonb}
            )
            return "UPDATE 1"
        if "INSERT INTO sensitive_bridge_log" in q:
            self._state["audit_log"].append({"query": "log_insert", "args": args})
            return "INSERT 0 1"
        # Other queries are no-ops in this stub.
        return ""


class _FakePool:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    @asynccontextmanager
    async def acquire(self):
        yield _FakeConn(self._state)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


def _seed_state(active_codewords: int = 1) -> Dict[str, Any]:
    user_id = "test_user_42"
    return {
        "users": {
            user_id: {
                "profile_data": {
                    "role": "CLIENT",
                    "safe_silence_mode_state": {
                        "state": "inactive",
                        "proposer_id": None,
                        "approver_id": None,
                        "proposed_at": None,
                        "approved_at": None,
                        "expires_at": None,
                        "expiry_warning_sent_at": None,
                        "auto_revert_eligible_at": None,
                        "codeword_precondition_met": False,
                        "reason_redacted": None,
                    },
                }
            },
            "coach_alpha": {"profile_data": {"role": "COACH"}},
            "admin_root": {"profile_data": {"role": "ADMIN"}},
        },
        "codeword_counts": {user_id: active_codewords},
        "audit_writes": [],
        "audit_log": [],
        "_user_id": user_id,
    }


def _build_app(state: Dict[str, Any], coach_principal: Dict, admin_principal: Dict):
    """Mount the router with stubbed auth dependencies + db_pool."""
    from app.routers import sensitive_profile_api as api

    app = FastAPI()

    # Override the auth deps to return the principal we want for each test.
    async def _coach_dep(user_id: str):
        return {**coach_principal, "_target_user_id": user_id}

    async def _admin_dep():
        return admin_principal

    app.dependency_overrides[api.require_clinician_for_user] = _coach_dep
    app.dependency_overrides[api.require_admin_with_session_token] = _admin_dep

    app.include_router(api.coach_router)
    app.include_router(api.admin_router)
    app.state.db_pool = _FakePool(state)
    return app


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


def test_propose_then_approve_same_session_blocked():
    """Risk #19: same JWT proposes and approves → 409 same_session_violation."""
    state = _seed_state(active_codewords=1)
    user_id = state["_user_id"]
    same_token_hash = "deadbeef" * 8  # SHA-256 hex length, identical for both
    coach_p = {
        "username": "coach_alpha",
        "role": "COACH",
        "_token_session_hash": same_token_hash,
    }
    admin_p = {
        "username": "admin_root",
        "role": "ADMIN",
        "_token_session_hash": same_token_hash,
    }
    app = _build_app(state, coach_p, admin_p)
    client = TestClient(app)

    # Step 1: propose.
    r1 = client.post(
        f"/api/coach/sensitive-profile/{user_id}/safe-silence/propose",
        json={"reason_redacted": "client requested silence after re-traumatization"},
    )
    assert r1.status_code == 200, r1.text
    proposal_id = r1.json()["proposal_id"]
    assert proposal_id, "propose must return proposal_id"
    sss = state["users"][user_id]["profile_data"]["safe_silence_mode_state"]
    assert sss["state"] == "pending_approval"
    assert sss["proposer_token_hash"] == same_token_hash

    # Step 2: approve from same session → must 409.
    r2 = client.post(
        f"/api/admin/sensitive-profile/{user_id}/safe-silence/approve",
        json={"proposal_id": proposal_id},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["reason"] == "same_session_violation"

    # State must remain pending_approval — the gate did NOT flip.
    sss_after = state["users"][user_id]["profile_data"]["safe_silence_mode_state"]
    assert sss_after["state"] == "pending_approval"


def test_approve_without_codeword_blocked():
    """Codeword precondition: zero active codewords → 409 requires_codeword."""
    state = _seed_state(active_codewords=0)  # zero codewords
    user_id = state["_user_id"]
    coach_token = "aa" * 32
    admin_token = "bb" * 32  # different session
    coach_p = {
        "username": "coach_alpha",
        "role": "COACH",
        "_token_session_hash": coach_token,
    }
    admin_p = {
        "username": "admin_root",
        "role": "ADMIN",
        "_token_session_hash": admin_token,
    }
    app = _build_app(state, coach_p, admin_p)
    client = TestClient(app)

    r1 = client.post(
        f"/api/coach/sensitive-profile/{user_id}/safe-silence/propose",
        json={"reason_redacted": "needs silence window"},
    )
    assert r1.status_code == 200, r1.text
    proposal_id = r1.json()["proposal_id"]

    r2 = client.post(
        f"/api/admin/sensitive-profile/{user_id}/safe-silence/approve",
        json={"proposal_id": proposal_id},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["reason"] == "requires_codeword"

    # Crucially: state must NOT be 'active' — codeword check fired BEFORE flip.
    sss_after = state["users"][user_id]["profile_data"]["safe_silence_mode_state"]
    assert sss_after["state"] == "pending_approval", (
        "codeword precondition must run BEFORE state flip; otherwise "
        "user is silenced without a safety net"
    )


def test_happy_path_propose_then_approve_different_session_with_codeword():
    """Different sessions + 1 active codeword → 200, state='active', proposer_token_hash wiped."""
    state = _seed_state(active_codewords=1)
    user_id = state["_user_id"]
    coach_token = "cc" * 32
    admin_token = "dd" * 32
    coach_p = {
        "username": "coach_alpha",
        "role": "COACH",
        "_token_session_hash": coach_token,
    }
    admin_p = {
        "username": "admin_root",
        "role": "ADMIN",
        "_token_session_hash": admin_token,
    }
    app = _build_app(state, coach_p, admin_p)
    client = TestClient(app)

    r1 = client.post(
        f"/api/coach/sensitive-profile/{user_id}/safe-silence/propose",
        json={"reason_redacted": "post-court-date silence per safety plan"},
    )
    assert r1.status_code == 200, r1.text
    proposal_id = r1.json()["proposal_id"]

    r2 = client.post(
        f"/api/admin/sensitive-profile/{user_id}/safe-silence/approve",
        json={
            "proposal_id": proposal_id,
            "approver_note_redacted": "supervising clinician concurs",
        },
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["state"] == "active"
    assert body["expires_at"]
    assert body["approval_ttl_days"] == 30

    sss_after = state["users"][user_id]["profile_data"]["safe_silence_mode_state"]
    assert sss_after["state"] == "active"
    assert sss_after["codeword_precondition_met"] is True
    # Proposer token hash must be WIPED so a leak of the row cannot replay.
    assert sss_after.get("proposer_token_hash") is None
    assert sss_after["approver_id"] == "admin_root"


def test_approve_without_pending_proposal_blocked():
    """No proposal → 409 stale_state."""
    state = _seed_state(active_codewords=1)
    user_id = state["_user_id"]
    coach_p = {
        "username": "coach_alpha",
        "role": "COACH",
        "_token_session_hash": "ee" * 32,
    }
    admin_p = {
        "username": "admin_root",
        "role": "ADMIN",
        "_token_session_hash": "ff" * 32,
    }
    app = _build_app(state, coach_p, admin_p)
    client = TestClient(app)

    r = client.post(
        f"/api/admin/sensitive-profile/{user_id}/safe-silence/approve",
        json={"proposal_id": str(uuid.uuid4())},
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["reason"] == "stale_state"


if __name__ == "__main__":
    # Allow direct invocation: python3 -m backend.tests.smoke.test_sensitive_profile_safe_silence_gate
    test_propose_then_approve_same_session_blocked()
    print("[1/4] same_session_violation: BLOCKED ✅")
    test_approve_without_codeword_blocked()
    print("[2/4] requires_codeword: BLOCKED ✅")
    test_happy_path_propose_then_approve_different_session_with_codeword()
    print("[3/4] happy path: ACTIVE ✅")
    test_approve_without_pending_proposal_blocked()
    print("[4/4] stale_state: BLOCKED ✅")
    print("\nALL_GATES_PASS")
