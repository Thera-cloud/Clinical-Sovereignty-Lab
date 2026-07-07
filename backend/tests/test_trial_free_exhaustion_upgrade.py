"""Public Trial Funnel Phase 3.5 — TRIAL_FREE token exhaustion -> card-based
TRIAL upgrade (trial-free-exhaustion-upgrade).

Covers:
  - Detection: TRIAL_FREE token exhaustion emits a distinct
    `trial_free_tokens_exhausted` payload (not the generic low-balance
    string), gated strictly on registration_type.
  - Billing collection: `registration_checkout.py`'s new setup-mode Stripe
    Checkout pair (`trial-free/upgrade-billing` / `trial-free/upgrade-callback`)
    mirrors the existing `trial/setup-billing` pattern — auth required,
    eligibility gated, rate limited, Redis-scoped to
    `trial_free_upgrade_session_key`, never touches `users`.
  - Account flip: the bridge WS handler `trial_free_upgrade_confirm`
    performs the only mutation (via `save_registry_async`), is idempotent
    (guarded on current registration_type), verifies billing via
    `_consume_trial_free_upgrade_session_async` (hardware_id-scoped so a
    session_id can't be replayed against a different account), and grants
    exactly the same tier/plan/status/token_balance/trial_end fields a
    fresh card-based TRIAL registration receives.

`bridge_server.py` (28k+ lines, heavy import side effects) is never imported
directly — behavior is verified either via source-level regex/exec
extraction (mirrors test_dojo_model_tier_routing.py) or via source-scan
assertions (mirrors the tail of test_public_trial_isolation.py). This keeps
the suite fully offline (ci-gate-before-push.mdc).

`registration_checkout.py` IS lightweight enough to import directly (it only
needs JWT_SECRET set before `app.services.api_server` loads), so its two new
endpoints are exercised with a real FastAPI TestClient against fakes for
Stripe and Redis.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
from types import SimpleNamespace
from typing import Optional

import pytest

os.environ.setdefault("JWT_SECRET", "test-only-not-a-real-secret-0123456789abcdef")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.routers.registration_checkout as rc


# ---------------------------------------------------------------------------
# Source helpers (bridge_server.py — never imported directly)
# ---------------------------------------------------------------------------

def _bridge_server_source() -> str:
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"
    return path.read_text(encoding="utf-8")


def _exhaustion_block_source(source: str) -> str:
    """Full detection block: both the TRIAL_FREE branch and the unchanged
    generic-fallback else branch."""
    marker = 'if (profile.get("registration_type") or "").upper() == "TRIAL_FREE":'
    start = source.index(marker)
    end = source.index("# Record analytics (skip for Dojo", start)
    return source[start:end]


def _exhaustion_trial_free_branch_only(source: str) -> str:
    """Just the TRIAL_FREE branch (up to, excluding, the else:)."""
    block = _exhaustion_block_source(source)
    return block[: block.index("\n                else:")]


def _upgrade_confirm_block_source(source: str) -> str:
    marker = 'elif t == "trial_free_upgrade_confirm":'
    start = source.index(marker)
    end = source.index('\n            # === CLIENT: GET COACH INFO ===', start)
    return source[start:end]


def _trial_registration_grant_block(source: str) -> str:
    """The plain card-based TRIAL branch inside register_new_user() that the
    upgrade handler's field grant must match exactly (field parity test)."""
    marker = "else:  # TRIAL (default)"
    start = source.index(marker)
    end = source.index("\n    else:\n        # Coach defaults", start)
    return source[start:end]


def _consume_helper_source(source: str) -> str:
    marker = "async def _consume_trial_free_upgrade_session_async"
    start = source.index(marker)
    end = source.index("\nasync def register_new_user", start)
    return source[start:end]


# ---------------------------------------------------------------------------
# Detection: TRIAL_FREE exhaustion emits a distinct typed message
# ---------------------------------------------------------------------------

def test_exhaustion_block_gated_on_trial_free_registration_type():
    block = _exhaustion_trial_free_branch_only(_bridge_server_source())
    assert 'registration_type") or "").upper() == "TRIAL_FREE"' in block


def test_exhaustion_message_type_is_distinct_from_generic_low_balance():
    branch = _exhaustion_trial_free_branch_only(_bridge_server_source())
    assert '"type": "trial_free_tokens_exhausted"' in branch
    assert "Your token balance is low" not in branch


def test_exhaustion_payload_flags_upgrade_required():
    branch = _exhaustion_trial_free_branch_only(_bridge_server_source())
    assert '"upgrade_required": True' in branch


def test_exhaustion_payload_includes_turn_id_for_client_correlation():
    branch = _exhaustion_trial_free_branch_only(_bridge_server_source())
    assert '"turn_id": _turn_id' in branch


def test_generic_low_balance_path_still_used_for_non_trial_free_accounts():
    # The else branch (non-TRIAL_FREE) must still fall through to the
    # pre-existing generic message — this is an additive branch, not a
    # replacement, so paid/TRIAL accounts see unchanged behavior.
    block = _exhaustion_block_source(_bridge_server_source())
    assert "\n                else:" in block
    assert "Your token balance is low" in block


# ---------------------------------------------------------------------------
# trial_free_upgrade_confirm — WS handler structure, auth, idempotency
# ---------------------------------------------------------------------------

def _extract_pre_auth_allowlist(source: str) -> tuple:
    """Mirrors test_public_trial_ws_auth.py's extraction of the actual
    codified pre-auth allowlist (the auth_deadline bypass tuple)."""
    m = re.search(
        r"if not current_profile and t not in \(([^)]*)\) "
        r"and datetime\.datetime\.now\(\) > auth_deadline:",
        source,
    )
    assert m, "auth_deadline pre-auth allowlist guard not found in bridge_server.py"
    return tuple(lit.group(1) for lit in re.finditer(r'"([^"]+)"', m.group(1)))


def test_upgrade_confirm_not_in_pre_auth_auth_deadline_allowlist():
    source = _bridge_server_source()
    allowlist = _extract_pre_auth_allowlist(source)
    assert "trial_free_upgrade_confirm" not in allowlist


def test_upgrade_confirm_not_in_immediate_preauth_trial_dispatch():
    source = _bridge_server_source()
    m = re.search(
        r'if t in \("public_trial_start", "public_trial_chat", "public_trial_capture_email"\):',
        source,
    )
    assert m, "public_trial_* immediate pre-auth dispatch block not found"
    # trial_free_upgrade_confirm must never be added to this tuple — it is an
    # authenticated-user-only action (confirming an upgrade requires knowing
    # WHO is upgrading), unlike the anonymous trial start/chat/email-capture
    # triad.
    assert "trial_free_upgrade_confirm" not in m.group(0)


def test_upgrade_confirm_handler_appears_after_auth_deadline_enforcement():
    """Structural ordering check: the trial_free_upgrade_confirm elif branch
    must live textually after the auth_deadline gate so it is only ever
    reached once that check has already run for the current message."""
    source = _bridge_server_source()
    deadline_idx = source.index("and datetime.datetime.now() > auth_deadline:")
    handler_idx = source.index('elif t == "trial_free_upgrade_confirm":')
    assert handler_idx > deadline_idx


def test_upgrade_confirm_guards_on_current_profile_and_registration_type():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    assert 'if not current_profile or (current_profile.get("registration_type") or "").upper() != "TRIAL_FREE":' in block


def test_upgrade_confirm_not_eligible_reason_used_for_guard_failure():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    # The guard failure branch is the very first statement in the block, so
    # the first `ok": False` result literal must be paired with not_eligible.
    guard_idx = block.index("if not current_profile")
    next_result = block.index('"trial_free_upgrade_result"', guard_idx)
    result_line = block[next_result:next_result + 120]
    assert '"reason": "not_eligible"' in result_line


def test_upgrade_confirm_missing_session_reason():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    assert '"reason": "missing_session"' in block


def test_upgrade_confirm_billing_not_verified_reason():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    assert '"reason": "billing_not_verified"' in block


def test_upgrade_confirm_account_not_found_reason():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    assert '"reason": "account_not_found"' in block


def test_upgrade_confirm_scopes_consume_to_callers_own_hardware_id():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    assert "_consume_trial_free_upgrade_session_async(_tfu_session_id, _tfu_hw)" in block


def test_upgrade_confirm_persists_via_save_registry_async_not_raw_sql():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    assert "await save_registry_async(registry, changed_keys=[_reg_key])" in block
    assert "UPDATE users" not in block
    assert "INSERT INTO users" not in block


def test_upgrade_confirm_success_response_shape():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    success_idx = block.index('"ok": True')
    tail = block[success_idx:success_idx + 250]
    assert '"token_balance": 10000' in tail
    assert '"trial_end": _tfu_trial_end' in tail
    assert '"plan": "TRIAL"' in tail


# ---------------------------------------------------------------------------
# trial_free_upgrade_confirm — full behavioral execution via source
# extraction + exec (same technique as the consume-helper tests above).
# This actually RUNS the handler's exact statements (not just source-scan)
# against mocked collaborators, giving true behavioral coverage of the
# idempotency / unverified-billing / field-parity test specs.
# ---------------------------------------------------------------------------

def _make_upgrade_confirm_handler():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    lines = block.splitlines()
    dedented = [lines[0]] + [
        (l[12:] if l.startswith(" " * 12) else l) for l in lines[1:]
    ]
    func_src = (
        "async def _run(current_profile, d, current_hardware_id, websocket,\n"
        "               _consume_trial_free_upgrade_session_async, load_registry,\n"
        "               save_registry_async, tier_for_db_column, datetime, json):\n"
        "    t = \"trial_free_upgrade_confirm\"\n"
        "    if False:\n"
        "        pass\n"
    )
    for line in dedented:
        func_src += ("    " + line + "\n") if line.strip() else "\n"
    ns: dict = {}
    exec(compile(func_src, "<upgrade_confirm_behavioral_extract>", "exec"), ns)
    return ns["_run"]


class _FakeUpgradeWebSocket:
    def __init__(self):
        self.sent: list = []

    async def send(self, msg):
        self.sent.append(json.loads(msg))


class _SaveRegistryRecorder:
    def __init__(self):
        self.calls: list = []

    async def __call__(self, registry, changed_keys=None):
        self.calls.append((registry, changed_keys))


def _stub_tier_for_db_column(plan: str) -> str:
    # Mirrors the real _TIER_DB_COLUMN_MAP["TRIAL"] = "TRIAL" (verified by
    # direct source read at bridge_server.py:2646-2648) for the one input
    # this handler ever passes.
    return {"TRIAL": "TRIAL"}.get(plan, "STANDARD")


async def _run_upgrade_confirm(current_profile, d, current_hardware_id, consume_fn, registry, save_recorder):
    import datetime as _dt
    handler = _make_upgrade_confirm_handler()
    ws = _FakeUpgradeWebSocket()
    load_registry = lambda: registry  # noqa: E731 - test stub
    await handler(
        current_profile, d, current_hardware_id, ws,
        consume_fn, load_registry, save_recorder, _stub_tier_for_db_column, _dt, json,
    )
    return ws.sent


def test_behavioral_not_eligible_when_registration_type_not_trial_free():
    consume_calls = []

    async def _consume(session_id, hw):
        consume_calls.append((session_id, hw))
        return "cus_should_not_be_used"

    profile = {"registration_type": "TRIAL", "hardware_id": "HW1"}
    sent = asyncio.run(_run_upgrade_confirm(
        profile, {"session_id": "cs1"}, "HW1", _consume, {}, _SaveRegistryRecorder(),
    ))
    assert sent == [{"type": "trial_free_upgrade_result", "ok": False, "reason": "not_eligible"}]
    assert consume_calls == []  # guard short-circuits before any billing verification


def test_behavioral_missing_session_id():
    async def _consume(session_id, hw):
        raise AssertionError("must not be called when session_id is missing")

    profile = {"registration_type": "TRIAL_FREE", "hardware_id": "HW1"}
    sent = asyncio.run(_run_upgrade_confirm(
        profile, {}, "HW1", _consume, {}, _SaveRegistryRecorder(),
    ))
    assert sent == [{"type": "trial_free_upgrade_result", "ok": False, "reason": "missing_session"}]


def test_behavioral_billing_not_verified_leaves_account_untouched():
    async def _consume(session_id, hw):
        return ""  # not verified / expired / missing

    profile = {"registration_type": "TRIAL_FREE", "hardware_id": "HW1"}
    sent = asyncio.run(_run_upgrade_confirm(
        profile, {"session_id": "cs1"}, "HW1", _consume, {}, _SaveRegistryRecorder(),
    ))
    assert sent == [{"type": "trial_free_upgrade_result", "ok": False, "reason": "billing_not_verified"}]
    assert profile == {"registration_type": "TRIAL_FREE", "hardware_id": "HW1"}


def test_behavioral_account_not_found_when_no_registry_match():
    async def _consume(session_id, hw):
        return "cus_ok"

    profile = {"registration_type": "TRIAL_FREE", "hardware_id": "HW_GHOST"}
    sent = asyncio.run(_run_upgrade_confirm(
        profile, {"session_id": "cs1"}, "HW_GHOST", _consume, {}, _SaveRegistryRecorder(),
    ))
    assert sent == [{"type": "trial_free_upgrade_result", "ok": False, "reason": "account_not_found"}]


def test_behavioral_successful_upgrade_grants_exact_trial_fields():
    async def _consume(session_id, hw):
        assert session_id == "cs_ok"
        assert hw == "HW1"
        return "cus_ok"

    registry = {"user_key_1": {"profile": {"hardware_id": "HW1", "registration_type": "TRIAL_FREE", "token_balance": 0}}}
    profile = {"registration_type": "TRIAL_FREE", "hardware_id": "HW1"}
    save_recorder = _SaveRegistryRecorder()

    sent = asyncio.run(_run_upgrade_confirm(
        profile, {"session_id": "cs_ok"}, "HW1", _consume, registry, save_recorder,
    ))

    assert len(sent) == 1
    result = sent[0]
    assert result["ok"] is True
    assert result["token_balance"] == 10000
    assert result["plan"] == "TRIAL"
    assert "trial_end" in result

    updated = registry["user_key_1"]["profile"]
    assert updated["registration_type"] == "TRIAL"
    assert updated["tier"] == "TRIAL"
    assert updated["subscription_plan"] == "TRIAL"
    assert updated["subscription_status"] == "TRIAL_ACTIVE"
    assert updated["token_balance"] == 10000
    assert updated["stripe_customer_id"] == "cus_ok"
    assert updated["trial_end_date"] == result["trial_end"]
    assert "trial_free_upgraded_at" in updated

    assert len(save_recorder.calls) == 1
    saved_registry, changed_keys = save_recorder.calls[0]
    assert saved_registry is registry
    assert changed_keys == ["user_key_1"]


def test_behavioral_idempotent_second_confirm_does_not_double_grant():
    """Plan-specified idempotency test: call trial_free_upgrade_confirm twice
    with the same valid session_id — second call returns
    ok: false, reason: not_eligible (already flipped by the first call), and
    the token balance is not double-granted."""
    consume_call_count = {"n": 0}

    async def _consume(session_id, hw):
        consume_call_count["n"] += 1
        return "cus_ok"

    registry = {"user_key_1": {"profile": {"hardware_id": "HW1", "registration_type": "TRIAL_FREE", "token_balance": 0}}}
    profile = {"registration_type": "TRIAL_FREE", "hardware_id": "HW1"}
    save_recorder = _SaveRegistryRecorder()

    first_sent = asyncio.run(_run_upgrade_confirm(
        profile, {"session_id": "cs_dup"}, "HW1", _consume, registry, save_recorder,
    ))
    assert first_sent[0]["ok"] is True
    assert consume_call_count["n"] == 1

    # Mirrors bridge_server.py's `current_profile = _tfu_profile` reassignment
    # (line ~13948) which persists across subsequent elif dispatches on the
    # same live connection — the second confirm sees the ALREADY-UPGRADED
    # profile as its "current" registration_type.
    updated_profile = registry["user_key_1"]["profile"]

    second_sent = asyncio.run(_run_upgrade_confirm(
        updated_profile, {"session_id": "cs_dup"}, "HW1", _consume, registry, save_recorder,
    ))
    assert second_sent == [{"type": "trial_free_upgrade_result", "ok": False, "reason": "not_eligible"}]
    # Guard short-circuits before ever re-verifying billing a second time.
    assert consume_call_count["n"] == 1
    # Not double-granted.
    assert registry["user_key_1"]["profile"]["token_balance"] == 10000
    assert len(save_recorder.calls) == 1


def test_behavioral_field_parity_matches_fresh_trial_registration_values():
    """Behavioral counterpart to test_upgrade_grant_field_parity_with_fresh_trial_registration
    (source-scan): the concrete values produced at runtime by the handler
    must equal what register_new_user()'s plain TRIAL branch hardcodes
    (tier_for_db_column("TRIAL")="TRIAL", plan="TRIAL",
    sub_status="TRIAL_ACTIVE", token_balance=10000)."""
    async def _consume(session_id, hw):
        return "cus_parity"

    registry = {"k": {"profile": {"hardware_id": "HW1", "registration_type": "TRIAL_FREE"}}}
    profile = {"registration_type": "TRIAL_FREE", "hardware_id": "HW1"}

    asyncio.run(_run_upgrade_confirm(
        profile, {"session_id": "cs_parity"}, "HW1", _consume, registry, _SaveRegistryRecorder(),
    ))

    updated = registry["k"]["profile"]
    # Exact literal values register_new_user() assigns in its plain TRIAL
    # (else) branch — see _trial_registration_grant_block().
    assert updated["tier"] == _stub_tier_for_db_column("TRIAL") == "TRIAL"
    assert updated["subscription_plan"] == "TRIAL"
    assert updated["subscription_status"] == "TRIAL_ACTIVE"
    assert updated["token_balance"] == 10000


# ---------------------------------------------------------------------------
# Field parity: upgrade grant must exactly match a fresh card-based TRIAL
# registration (tier/plan/status/token_balance/trial_end)
# ---------------------------------------------------------------------------

def test_upgrade_grant_field_parity_with_fresh_trial_registration():
    source = _bridge_server_source()
    fresh_trial = _trial_registration_grant_block(source)
    upgrade = _upgrade_confirm_block_source(source)

    assert 'tier_for_db_column("TRIAL")' in fresh_trial
    assert 'tier_for_db_column("TRIAL")' in upgrade

    assert 'plan = "TRIAL"' in fresh_trial
    assert '"registration_type"] = "TRIAL"' in upgrade

    assert 'sub_status = "TRIAL_ACTIVE"' in fresh_trial
    assert '"subscription_status"] = "TRIAL_ACTIVE"' in upgrade

    assert "token_balance = 10000" in fresh_trial
    assert '"token_balance"] = 10000' in upgrade

    # Both compute trial_end the same way: now + 7 days, date-only.
    trial_end_expr = "datetime.datetime.now() + datetime.timedelta(days=7)).date()"
    assert trial_end_expr in fresh_trial
    assert trial_end_expr in upgrade


def test_upgrade_grant_does_not_backdate_trial_end_to_original_registration():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    # trial_end must be computed from datetime.now() at upgrade time, never
    # read back from an existing profile field (which would backdate it to
    # the original TRIAL_FREE signup).
    assert '_tfu_profile.get("trial_end_date"' not in block
    assert "_tfu_trial_end = str((datetime.datetime.now()" in block


def test_upgrade_grant_sets_token_balance_absolutely_not_additively():
    block = _upgrade_confirm_block_source(_bridge_server_source())
    # Must be a flat assignment (SET to 10000), never additive
    # (would double-grant on any retry that somehow bypassed idempotency).
    assert '_tfu_profile["token_balance"] = 10000' in block
    assert '_tfu_profile["token_balance"] +=' not in block
    assert '_tfu_profile["token_balance"] += 10000' not in block


# ---------------------------------------------------------------------------
# _consume_trial_free_upgrade_session_async — behavioral tests via source
# extraction + exec (mirrors test_dojo_model_tier_routing.py technique;
# avoids importing the 28k-line bridge_server.py module).
# ---------------------------------------------------------------------------

class _FakeSyncRedis:
    """Minimal sync redis surface (get/delete) matching _token_redis_sync."""

    def __init__(self, store: Optional[dict] = None):
        self.store = dict(store or {})
        self.deleted: list = []

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)


def _make_consume_helper(fake_redis):
    """exec the extracted async function into an isolated namespace with a
    fake _token_redis_sync, returning the callable directly (no bridge_server
    import)."""
    source = _consume_helper_source(_bridge_server_source())
    ns = {
        "json": json,
        "asyncio": asyncio,
        "Optional": Optional,
        "_token_redis_sync": fake_redis,
    }
    exec(compile(source, "<consume_helper_extract>", "exec"), ns)
    return ns["_consume_trial_free_upgrade_session_async"]


def _tf_key(session_id: str) -> str:
    # Mirrors trial_signup_redis_keys.trial_free_upgrade_session_key without
    # importing the module inside the exec namespace's dynamic import path
    # (the extracted function imports it itself at call time).
    from app.services.trial_signup_redis_keys import trial_free_upgrade_session_key
    return trial_free_upgrade_session_key(session_id)


def test_consume_helper_returns_customer_id_when_verified_and_hw_matches():
    key = _tf_key("cs_test_1")
    redis = _FakeSyncRedis({key: json.dumps({
        "verified": True, "stripe_customer_id": "cus_abc", "hardware_id": "HW1",
    })})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("cs_test_1", "HW1"))
    assert result == "cus_abc"


def test_consume_helper_deletes_key_after_successful_consume_idempotency():
    key = _tf_key("cs_test_2")
    redis = _FakeSyncRedis({key: json.dumps({
        "verified": True, "stripe_customer_id": "cus_xyz", "hardware_id": "HW2",
    })})
    fn = _make_consume_helper(redis)
    first = asyncio.run(fn("cs_test_2", "HW2"))
    assert first == "cus_xyz"
    assert key in redis.deleted
    # Second call against the same session_id must fail closed — the
    # session was consumed, so a duplicate trial_free_upgrade_confirm
    # cannot re-grant tokens (idempotency at the Redis layer, on top of the
    # registration_type guard in the WS handler).
    second = asyncio.run(fn("cs_test_2", "HW2"))
    assert second == ""


def test_consume_helper_returns_empty_when_not_verified():
    key = _tf_key("cs_test_3")
    redis = _FakeSyncRedis({key: json.dumps({
        "verified": False, "stripe_customer_id": "cus_abc", "hardware_id": "HW1",
    })})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("cs_test_3", "HW1"))
    assert result == ""


def test_consume_helper_returns_empty_when_missing_customer_id():
    key = _tf_key("cs_test_4")
    redis = _FakeSyncRedis({key: json.dumps({"verified": True, "hardware_id": "HW1"})})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("cs_test_4", "HW1"))
    assert result == ""


def test_consume_helper_returns_empty_when_hardware_id_mismatch():
    """Prevents replaying another account's Checkout session_id against your
    own hardware_id (cross-account upgrade theft)."""
    key = _tf_key("cs_test_5")
    redis = _FakeSyncRedis({key: json.dumps({
        "verified": True, "stripe_customer_id": "cus_abc", "hardware_id": "HW_VICTIM",
    })})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("cs_test_5", "HW_ATTACKER"))
    assert result == ""
    # And the victim's session must remain untouched (not deleted) so the
    # rightful owner can still complete their own upgrade.
    assert key not in redis.deleted


def test_consume_helper_skips_hardware_check_when_not_supplied():
    key = _tf_key("cs_test_6")
    redis = _FakeSyncRedis({key: json.dumps({
        "verified": True, "stripe_customer_id": "cus_abc", "hardware_id": "HW1",
    })})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("cs_test_6", None))
    assert result == "cus_abc"


def test_consume_helper_returns_empty_for_missing_session():
    redis = _FakeSyncRedis({})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("cs_does_not_exist", "HW1"))
    assert result == ""


def test_consume_helper_returns_empty_for_blank_session_id():
    redis = _FakeSyncRedis({})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("", "HW1"))
    assert result == ""


def test_consume_helper_returns_empty_when_no_redis_client():
    source = _consume_helper_source(_bridge_server_source())
    ns = {"json": json, "asyncio": asyncio, "Optional": Optional, "_token_redis_sync": None}
    exec(compile(source, "<consume_helper_extract_no_redis>", "exec"), ns)
    fn = ns["_consume_trial_free_upgrade_session_async"]
    result = asyncio.run(fn("cs_whatever", "HW1"))
    assert result == ""


def test_consume_helper_returns_empty_on_malformed_json():
    key = _tf_key("cs_test_7")
    redis = _FakeSyncRedis({key: "not-json-at-all"})
    fn = _make_consume_helper(redis)
    result = asyncio.run(fn("cs_test_7", "HW1"))
    assert result == ""


# ---------------------------------------------------------------------------
# registration_checkout.py — new Stripe setup-mode Checkout pair
# (real FastAPI TestClient; Stripe + Redis are faked)
# ---------------------------------------------------------------------------

class _FakeAsyncRedis:
    def __init__(self):
        self.store: dict = {}

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)


class _FakeStripeObj(SimpleNamespace):
    pass


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    rc._rate_limits.clear()
    yield
    rc._rate_limits.clear()


@pytest.fixture
def fake_redis():
    return _FakeAsyncRedis()


@pytest.fixture
def app_client(fake_redis):
    app = FastAPI()
    app.include_router(rc.public_router)
    app.state.wisdom_mesh = SimpleNamespace(_redis=fake_redis)
    return app, TestClient(app)


def _override_user(app, profile: Optional[dict]):
    if rc.get_current_user is not None:
        app.dependency_overrides[rc.get_current_user] = lambda: profile


def test_upgrade_billing_requires_authentication(app_client):
    app, client = app_client
    _override_user(app, None)
    resp = client.post("/api/registration/trial-free/upgrade-billing")
    assert resp.status_code == 401


def test_upgrade_billing_rejects_non_trial_free_account(app_client):
    app, client = app_client
    _override_user(app, {"registration_type": "TRIAL", "hardware_id": "HW1", "username": "u1"})
    resp = client.post("/api/registration/trial-free/upgrade-billing")
    assert resp.status_code == 400


def test_upgrade_billing_rate_limits_sixth_request_same_ip(app_client, monkeypatch):
    app, client = app_client
    # Ineligible account is enough here — _rate_check runs before the
    # eligibility check, so we don't need working Stripe/Redis for this test.
    _override_user(app, {"registration_type": "TRIAL", "hardware_id": "HW1", "username": "u1"})
    statuses = []
    for _ in range(6):
        resp = client.post("/api/registration/trial-free/upgrade-billing")
        statuses.append(resp.status_code)
    assert statuses[:5] == [400, 400, 400, 400, 400]
    assert statuses[5] == 429


def test_upgrade_billing_503_when_redis_unavailable(app_client, monkeypatch):
    app, client = app_client
    app.state.wisdom_mesh = SimpleNamespace(_redis=None)
    _override_user(app, {"registration_type": "TRIAL_FREE", "hardware_id": "HW1", "username": "u1"})
    monkeypatch.setattr(rc.stripe, "api_key", "sk_test_fake")
    resp = client.post("/api/registration/trial-free/upgrade-billing")
    assert resp.status_code == 503


def test_upgrade_billing_503_when_stripe_not_configured(app_client, monkeypatch):
    app, client = app_client
    _override_user(app, {"registration_type": "TRIAL_FREE", "hardware_id": "HW1", "username": "u1"})
    monkeypatch.setattr(rc.stripe, "api_key", None)
    resp = client.post("/api/registration/trial-free/upgrade-billing")
    assert resp.status_code == 503


def test_upgrade_billing_happy_path_creates_session_and_redis_entry(app_client, monkeypatch, fake_redis):
    app, client = app_client
    _override_user(app, {
        "registration_type": "TRIAL_FREE", "hardware_id": "HW_HAPPY",
        "username": "u1", "email": "trialer@example.com", "name": "Trial User",
    })
    monkeypatch.setattr(rc.stripe, "api_key", "sk_test_fake")
    monkeypatch.setattr(rc.stripe.Customer, "list", staticmethod(lambda **kw: _FakeStripeObj(data=[])))
    monkeypatch.setattr(rc.stripe.Customer, "create", staticmethod(lambda **kw: _FakeStripeObj(id="cus_happy")))
    monkeypatch.setattr(
        rc.stripe.checkout.Session, "create",
        staticmethod(lambda **kw: _FakeStripeObj(id="cs_happy", url="https://checkout.stripe.com/cs_happy")),
    )

    resp = client.post("/api/registration/trial-free/upgrade-billing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "cs_happy"
    assert body["checkout_url"] == "https://checkout.stripe.com/cs_happy"

    from app.services.trial_signup_redis_keys import trial_free_upgrade_session_key
    stored = json.loads(fake_redis.store[trial_free_upgrade_session_key("cs_happy")])
    assert stored["verified"] is False
    assert stored["hardware_id"] == "HW_HAPPY"


def test_upgrade_billing_reuses_existing_stripe_customer_by_email(app_client, monkeypatch):
    app, client = app_client
    _override_user(app, {
        "registration_type": "TRIAL_FREE", "hardware_id": "HW2",
        "username": "u2", "email": "existing@example.com",
    })
    monkeypatch.setattr(rc.stripe, "api_key", "sk_test_fake")
    monkeypatch.setattr(
        rc.stripe.Customer, "list",
        staticmethod(lambda **kw: _FakeStripeObj(data=[_FakeStripeObj(id="cus_existing")])),
    )
    created = {"called": False}

    def _create(**kw):
        created["called"] = True
        return _FakeStripeObj(id="cus_new")

    monkeypatch.setattr(rc.stripe.Customer, "create", staticmethod(_create))
    monkeypatch.setattr(
        rc.stripe.checkout.Session, "create",
        staticmethod(lambda **kw: _FakeStripeObj(id="cs2", url="https://checkout.stripe.com/cs2", customer=kw.get("customer"))),
    )

    resp = client.post("/api/registration/trial-free/upgrade-billing")
    assert resp.status_code == 200
    assert created["called"] is False


def test_upgrade_callback_redirects_with_error_when_session_incomplete(app_client, monkeypatch):
    app, client = app_client
    monkeypatch.setattr(rc.stripe, "api_key", "sk_test_fake")
    monkeypatch.setattr(
        rc.stripe.checkout.Session, "retrieve",
        staticmethod(lambda sid, expand=None: _FakeStripeObj(status="open", customer=None, setup_intent=None)),
    )
    resp = client.get("/api/registration/trial-free/upgrade-callback", params={"session_id": "cs_incomplete"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "error=incomplete" in resp.headers["location"]


def test_upgrade_callback_redirects_with_error_when_setup_failed(app_client, monkeypatch):
    app, client = app_client
    monkeypatch.setattr(rc.stripe, "api_key", "sk_test_fake")
    monkeypatch.setattr(
        rc.stripe.checkout.Session, "retrieve",
        staticmethod(lambda sid, expand=None: _FakeStripeObj(
            status="complete", customer="cus_x", setup_intent=_FakeStripeObj(status="requires_action"),
        )),
    )
    resp = client.get("/api/registration/trial-free/upgrade-callback", params={"session_id": "cs_failed"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "error=setup_failed" in resp.headers["location"]


def test_upgrade_callback_marks_verified_and_preserves_hardware_id(app_client, monkeypatch, fake_redis):
    app, client = app_client
    from app.services.trial_signup_redis_keys import trial_free_upgrade_session_key

    asyncio.run(fake_redis.setex(
        trial_free_upgrade_session_key("cs_ok"), 1800,
        json.dumps({"phase": "pending", "hardware_id": "HW_OK", "verified": False}),
    ))
    monkeypatch.setattr(rc.stripe, "api_key", "sk_test_fake")
    monkeypatch.setattr(
        rc.stripe.checkout.Session, "retrieve",
        staticmethod(lambda sid, expand=None: _FakeStripeObj(
            status="complete", customer="cus_ok", setup_intent=_FakeStripeObj(status="succeeded"),
        )),
    )

    resp = client.get("/api/registration/trial-free/upgrade-callback", params={"session_id": "cs_ok"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "error" not in resp.headers["location"]

    stored = json.loads(fake_redis.store[trial_free_upgrade_session_key("cs_ok")])
    assert stored["verified"] is True
    assert stored["stripe_customer_id"] == "cus_ok"
    assert stored["hardware_id"] == "HW_OK"


def test_upgrade_callback_never_touches_users_table():
    """The FastAPI billing-collection endpoints must never mutate `users` —
    the account flip is exclusively the bridge WS handler's job
    (bridge-cache-db-sovereignty.mdc)."""
    source = pathlib.Path(rc.__file__).read_text(encoding="utf-8")
    start = source.index("@public_router.post(\"/trial-free/upgrade-billing\")")
    end = source.index("@public_router.get(\"/trial-free/upgrade-callback\")")
    end2 = source.index("\n\n\n", end)
    block = source[start:end2]
    assert "UPDATE users" not in block
    assert "INSERT INTO users" not in block
    assert "FROM users" not in block
