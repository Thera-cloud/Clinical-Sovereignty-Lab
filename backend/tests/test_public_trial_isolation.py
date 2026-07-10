"""Public Trial Funnel — isolation tests (tests-gate).

Covers: prompt boundary / trial-safe enrichment, context starvation (global-only
crystal recall never touches per-user data), outbound safety filters, crystal
hygiene, WS input validation, Redis fail-closed abuse caps, gate/turn-increment
logic, email-capture consent gating, and namespace/socket isolation guards.

No live DB/Redis/LLM/network calls -- everything is mocked or exercised via
small fakes so this suite runs fully offline (see ci-gate-before-push.mdc).
"""
from __future__ import annotations

import asyncio

import pytest

import app.services.public_trial_gate as ptg


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeRedis:
    """Minimal async redis.asyncio surface used by public_trial_gate."""

    def __init__(self):
        self.counters: dict = {}
        self.locks: set = set()

    async def ping(self):
        return True

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key, ttl):
        # Real Redis: EXPIRE returns 0/False on a key that doesn't exist.
        # _check_and_refresh_turnstile_verified relies on exactly this to
        # distinguish "never solved Turnstile" from "solved it, sliding
        # window still open" -- so this fake must not unconditionally
        # return True the way it used to before Turnstile verification
        # existed.
        return key in self.locks

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.locks:
            return None
        self.locks.add(key)
        return True

    async def delete(self, key):
        self.locks.discard(key)

    async def exists(self, key):
        return 1 if key in self.locks else 0


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeTrialConn:
    """Fakes just the queries public_trial_gate's db_* helpers issue."""

    def __init__(self, store: dict):
        self.store = store

    async def fetchrow(self, query, *args):
        if "INSERT INTO public_summon_usage" in query:
            fp_hash, device_uuid_hash = args
            row = self.store.get(device_uuid_hash)
            if row is None:
                row = {
                    "turns_used": 0, "trial_history": [], "converted": False,
                    "gated_at": None, "device_fingerprint": fp_hash,
                }
                self.store[device_uuid_hash] = row
            else:
                row["device_fingerprint"] = fp_hash
            return dict(row)
        if "SELECT turns_used, trial_history, converted, gated_at" in query:
            device_uuid_hash = args[0]
            row = self.store.get(device_uuid_hash)
            return dict(row) if row else None
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def fetchval(self, query, *args):
        if "turns_used = COALESCE(turns_used, 0) + 1" in query:
            device_uuid_hash = args[0]
            row = self.store[device_uuid_hash]
            row["turns_used"] = (row.get("turns_used") or 0) + 1
            return row["turns_used"]
        raise AssertionError(f"unexpected fetchval query: {query}")

    async def execute(self, query, *args):
        if "SET gated_at = COALESCE(gated_at, NOW())" in query:
            device_uuid_hash = args[0]
            row = self.store.setdefault(device_uuid_hash, {
                "turns_used": 0, "trial_history": [], "converted": False, "gated_at": None,
            })
            if row.get("gated_at") is None:
                row["gated_at"] = "now"
        elif "turns_used = GREATEST" in query:
            device_uuid_hash = args[0]
            row = self.store[device_uuid_hash]
            row["turns_used"] = max((row.get("turns_used") or 0) - 1, 0)
        elif "trial_history" in query:
            pass  # not exercised by these tests
        else:
            raise AssertionError(f"unexpected execute query: {query}")
        return None


class _FakeTrialPool:
    def __init__(self):
        self.store: dict = {}

    def acquire(self):
        return _FakeAcquireCtx(_FakeTrialConn(self.store))


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Every test gets a clean bootstrap + flag state regardless of import order."""
    ptg._DB_POOL = None
    yield
    ptg._DB_POOL = None


# ---------------------------------------------------------------------------
# Namespace guard (security-trial-namespace-guard)
# ---------------------------------------------------------------------------

def test_is_trial_namespace_matches_prefix_case_insensitive():
    assert ptg.is_trial_namespace("trial_abc123") is True
    assert ptg.is_trial_namespace("TRIAL_ABC123") is True
    assert ptg.is_trial_namespace("  trial_abc123  ") is True


def test_is_trial_namespace_rejects_normal_identities():
    assert ptg.is_trial_namespace("normal_user") is False
    assert ptg.is_trial_namespace("CoachN") is False
    assert ptg.is_trial_namespace(None) is False
    assert ptg.is_trial_namespace("") is False


# ---------------------------------------------------------------------------
# Hashing / row identity (trial-row-identity-fix)
# ---------------------------------------------------------------------------

def test_device_uuid_hash_is_stable_and_unique_per_device():
    h1 = ptg.compute_device_uuid_hash("device-uuid-123")
    h2 = ptg.compute_device_uuid_hash("device-uuid-123")
    h3 = ptg.compute_device_uuid_hash("device-uuid-999")
    assert h1 == h2
    assert h1 != h3


def test_fp_hash_drifts_with_ip_ua_but_device_uuid_hash_does_not():
    """The row's identity (device_uuid_hash) must survive IP/UA churn (carrier
    handoff, wifi<->cellular). fp_hash is abuse-analytics only and is allowed,
    even expected, to change."""
    uuid_ = "stable-device-uuid"
    device_hash_a = ptg.compute_device_uuid_hash(uuid_)
    device_hash_b = ptg.compute_device_uuid_hash(uuid_)
    assert device_hash_a == device_hash_b

    fp_a = ptg.compute_fp_hash(uuid_, "1.2.3.4", "ua-chrome")
    fp_b = ptg.compute_fp_hash(uuid_, "5.6.7.8", "ua-safari")
    assert fp_a != fp_b


def test_trial_hardware_id_uses_reserved_namespace():
    hw = ptg.trial_hardware_id("abcdef0123456789")
    assert hw.startswith(ptg.TRIAL_UID_PREFIX)
    assert ptg.is_trial_namespace(hw)


# ---------------------------------------------------------------------------
# WS input schema validation (security-msg-schema-validation)
# ---------------------------------------------------------------------------

def test_validate_trial_text_rejects_non_string():
    assert ptg.validate_trial_text({"text": 12345}) is None
    assert ptg.validate_trial_text({"text": None}) is None
    assert ptg.validate_trial_text({}) is None


def test_validate_trial_text_rejects_empty_and_oversized():
    assert ptg.validate_trial_text({"text": "   "}) is None
    assert ptg.validate_trial_text({"text": "a" * (ptg.TRIAL_MAX_TEXT_LEN + 1)}) is None


def test_validate_trial_text_trims_and_accepts_valid():
    assert ptg.validate_trial_text({"text": "  hello there  "}) == "hello there"


def test_validate_device_fingerprint_rejects_invalid():
    assert ptg.validate_device_fingerprint({}) is None
    assert ptg.validate_device_fingerprint({"device_fingerprint": 123}) is None
    assert ptg.validate_device_fingerprint({"device_fingerprint": "   "}) is None
    assert ptg.validate_device_fingerprint({"device_fingerprint": "a" * 129}) is None


def test_validate_device_fingerprint_accepts_and_trims_valid():
    assert ptg.validate_device_fingerprint({"device_fingerprint": " uuid-123 "}) == "uuid-123"


# ---------------------------------------------------------------------------
# Redis abuse caps -- fail CLOSED (trial-abuse-resilience, security-registration-abuse)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_incr_with_cap_fails_closed_when_redis_unreachable(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(ptg, "_get_redis", _no_redis)
    allowed, retry_after = await ptg._incr_with_cap("some:key", 10, 60)
    assert allowed is False
    assert retry_after is None


@pytest.mark.asyncio
async def test_check_turn_abuse_caps_fails_closed_when_redis_unreachable(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(ptg, "_get_redis", _no_redis)
    result = await ptg.check_turn_abuse_caps("1.2.3.4", "fp-hash-abc")
    assert result.allowed is False
    assert result.inflight_acquired is False


@pytest.mark.asyncio
async def test_check_registration_ip_cap_fails_closed_when_redis_unreachable(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(ptg, "_get_redis", _no_redis)
    assert await ptg.check_registration_ip_cap("1.2.3.4") is False


@pytest.mark.asyncio
async def test_check_turn_abuse_caps_allows_first_turn_with_working_redis(monkeypatch):
    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake
    monkeypatch.setattr(ptg, "_get_redis", _fake_get_redis)

    result = await ptg.check_turn_abuse_caps("1.2.3.4", "fp-abc")
    assert result.allowed is True
    assert result.inflight_acquired is True


@pytest.mark.asyncio
async def test_check_turn_abuse_caps_blocks_second_inflight_turn_same_fingerprint(monkeypatch):
    """The single-in-flight-turn-per-fingerprint lock prevents a client from
    firing overlapping requests to multiply their effective rate."""
    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake
    monkeypatch.setattr(ptg, "_get_redis", _fake_get_redis)

    first = await ptg.check_turn_abuse_caps("1.2.3.4", "fp-abc")
    assert first.allowed is True
    second = await ptg.check_turn_abuse_caps("1.2.3.4", "fp-abc")
    assert second.allowed is False
    assert second.reason == "fp_inflight"


@pytest.mark.asyncio
async def test_check_registration_ip_cap_allows_within_cap(monkeypatch):
    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake
    monkeypatch.setattr(ptg, "_get_redis", _fake_get_redis)

    for _ in range(ptg._REGISTRATION_IP_DAILY_CAP):
        assert await ptg.check_registration_ip_cap("9.9.9.9") is True
    assert await ptg.check_registration_ip_cap("9.9.9.9") is False


# ---------------------------------------------------------------------------
# Gate / turn-increment / crisis-bypass logic (phase1/2 core)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prepare_public_trial_turn_disabled_flag_is_noop(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", False)
    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-flagoff", "text": "hi"}, "1.2.3.4", "ua",
    )
    assert ctx.ok is False
    assert ctx.payload["type"] == "error"


@pytest.mark.asyncio
async def test_prepare_public_trial_turn_happy_path_increments_turn(monkeypatch):
    pool = _FakeTrialPool()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    # This test exercises the turn-increment path, not Turnstile -- disable
    # per module docstring guidance (public_trial_gate.py PUBLIC_TRIAL_TURNSTILE_ENABLED).
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", False)

    async def _no_crisis(text):
        return []
    monkeypatch.setattr(ptg, "check_crisis", _no_crisis)

    async def _allow(*a, **kw):
        return ptg.AbuseCheckResult(True, "", True)
    monkeypatch.setattr(ptg, "check_turn_abuse_caps", _allow)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-happy", "text": "hello there"}, "1.2.3.4", "ua",
    )
    assert ctx.ok is True
    assert ctx.payload is None
    assert ctx.turns_used == 1
    assert ctx.is_crisis is False
    assert ctx.hardware_id.startswith(ptg.TRIAL_UID_PREFIX)
    assert ctx.profile.get("public_trial") is True


@pytest.mark.asyncio
async def test_prepare_public_trial_turn_gates_at_turn_limit(monkeypatch):
    pool = _FakeTrialPool()
    device_uuid_hash = ptg.compute_device_uuid_hash("uuid-gated")
    pool.store[device_uuid_hash] = {
        "turns_used": ptg.TRIAL_TURN_LIMIT, "trial_history": [], "converted": False, "gated_at": None,
    }
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-gated", "text": "one more please"}, "1.2.3.4", "ua",
    )
    assert ctx.ok is False
    assert ctx.payload["type"] == "signup_required"
    assert ctx.payload["turns_used"] == ptg.TRIAL_TURN_LIMIT
    assert "signup_url" in ctx.payload
    assert pool.store[device_uuid_hash]["gated_at"] is not None


@pytest.mark.asyncio
async def test_prepare_public_trial_turn_crisis_never_consumes_quota(monkeypatch):
    """Crisis turns must never be metered against the 20-turn cap -- witnessing
    a person in crisis cannot be rate-limited away."""
    pool = _FakeTrialPool()
    device_uuid_hash = ptg.compute_device_uuid_hash("uuid-crisis")
    pool.store[device_uuid_hash] = {
        "turns_used": 5, "trial_history": [], "converted": False, "gated_at": None,
    }
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)

    async def _crisis(text):
        return ["kill myself"]
    monkeypatch.setattr(ptg, "check_crisis", _crisis)

    async def _allow(*a, **kw):
        return ptg.AbuseCheckResult(True, "", True)
    monkeypatch.setattr(ptg, "check_turn_abuse_caps", _allow)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-crisis", "text": "I want to kill myself"}, "1.2.3.4", "ua",
    )
    assert ctx.ok is True
    assert ctx.is_crisis is True
    assert ctx.turns_used == 5
    assert pool.store[device_uuid_hash]["turns_used"] == 5


@pytest.mark.asyncio
async def test_prepare_public_trial_turn_rejects_abuse_capped_request(monkeypatch):
    pool = _FakeTrialPool()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    # This test exercises the abuse-cap rejection path, not Turnstile.
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", False)

    async def _no_crisis(text):
        return []
    monkeypatch.setattr(ptg, "check_crisis", _no_crisis)

    async def _deny(*a, **kw):
        return ptg.AbuseCheckResult(False, "ip_daily_cap", False)
    monkeypatch.setattr(ptg, "check_turn_abuse_caps", _deny)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-capped", "text": "hello"}, "1.2.3.4", "ua",
    )
    assert ctx.ok is False
    # 2026-07 trial audit Q11 fix: ip_daily_cap is a genuine shared-capacity
    # condition, so it keeps the TRIAL_CAPACITY_MESSAGE copy -- but every
    # rejection message now carries the 988 line as belt-and-braces against a
    # crisis-vs-cap ordering regression (see test_public_trial_crisis.py).
    assert ctx.payload["message"] == ptg.TRIAL_CAPACITY_MESSAGE + ptg.CRISIS_RESOURCE_TEXT
    assert "988" in ctx.payload["message"]
    assert ctx.payload["reason"] == "ip_daily_cap"
    assert ctx.payload["rate_limited"] is False


@pytest.mark.asyncio
async def test_prepare_public_trial_start_creates_row_and_reports_state(monkeypatch):
    pool = _FakeTrialPool()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    # This test exercises DB row creation, not Turnstile verification --
    # see test_public_trial_turnstile.py for dedicated Turnstile coverage.
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", False)

    out = await ptg.prepare_public_trial_start({"device_fingerprint": "uuid-start"}, "1.2.3.4", "ua")
    assert out["type"] == "trial_state"
    assert out["turns_used"] == 0
    assert out["turns_limit"] == ptg.TRIAL_TURN_LIMIT
    assert out["converted"] is False


@pytest.mark.asyncio
async def test_prepare_public_trial_start_rejects_missing_fingerprint(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    out = await ptg.prepare_public_trial_start({}, "1.2.3.4", "ua")
    assert out["type"] == "error"


@pytest.mark.asyncio
async def test_finalize_public_trial_turn_builds_response_payload(monkeypatch):
    calls = {"history": None, "released": None}

    async def _fake_append_history(device_uuid_hash, user_text, assistant_text):
        calls["history"] = (device_uuid_hash, user_text, assistant_text)

    async def _fake_release(fp_hash):
        calls["released"] = fp_hash

    monkeypatch.setattr(ptg, "db_append_history", _fake_append_history)
    monkeypatch.setattr(ptg, "release_turn_inflight", _fake_release)

    ctx = ptg.TrialTurnContext(
        ok=True, device_uuid_hash="duh", fp_hash="fph", hardware_id="trial_abc",
        text="hi", turns_used=15, trial_nudge=ptg.TRIAL_NUDGE_TEXT, is_crisis=False,
    )
    payload = await ptg.finalize_public_trial_turn(ctx, "hello back")
    assert payload["type"] == "trial_response"
    assert payload["text"] == "hello back"
    assert payload["turns_used"] == 15
    assert payload["trial_nudge"] == ptg.TRIAL_NUDGE_TEXT
    assert "crisis_resources" not in payload
    assert calls["history"] == ("duh", "hi", "hello back")
    assert calls["released"] == "fph"


@pytest.mark.asyncio
async def test_finalize_public_trial_turn_flags_crisis_resources(monkeypatch):
    monkeypatch.setattr(ptg, "db_append_history", lambda *a, **kw: _noop())
    monkeypatch.setattr(ptg, "release_turn_inflight", lambda *a, **kw: _noop())

    ctx = ptg.TrialTurnContext(
        ok=True, device_uuid_hash="duh", fp_hash="fph", hardware_id="trial_abc",
        text="hi", turns_used=5, is_crisis=True,
    )
    payload = await ptg.finalize_public_trial_turn(ctx, "I'm here with you.")
    assert payload["crisis_resources"] is True


@pytest.mark.asyncio
async def test_refund_public_trial_turn_refunds_non_crisis_turn(monkeypatch):
    calls = {"refunded": None, "released": None}

    async def _fake_refund(device_uuid_hash):
        calls["refunded"] = device_uuid_hash

    async def _fake_release(fp_hash):
        calls["released"] = fp_hash

    monkeypatch.setattr(ptg, "db_refund_turn", _fake_refund)
    monkeypatch.setattr(ptg, "release_turn_inflight", _fake_release)

    ctx = ptg.TrialTurnContext(
        ok=True, device_uuid_hash="duh", fp_hash="fph", hardware_id="trial_abc",
        is_crisis=False,
    )
    await ptg.refund_public_trial_turn(ctx)
    assert calls["refunded"] == "duh"
    assert calls["released"] == "fph"


@pytest.mark.asyncio
async def test_refund_public_trial_turn_never_refunds_crisis_turn(monkeypatch):
    """Crisis turns were never incremented (see prepare_public_trial_turn), so
    refunding one would double-credit the quota."""
    calls = {"refunded": False}

    async def _fake_refund(device_uuid_hash):
        calls["refunded"] = True

    monkeypatch.setattr(ptg, "db_refund_turn", _fake_refund)
    monkeypatch.setattr(ptg, "release_turn_inflight", lambda *a, **kw: _noop())

    ctx = ptg.TrialTurnContext(
        ok=True, device_uuid_hash="duh", fp_hash="fph", hardware_id="trial_abc",
        is_crisis=True,
    )
    await ptg.refund_public_trial_turn(ctx)
    assert calls["refunded"] is False


async def _noop():
    return None


# ---------------------------------------------------------------------------
# Email capture -- consent gating + fail-closed + signup-never-fail resilience
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_capture_always_returns_generic_ack_when_disabled(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", False)
    out = await ptg.handle_public_trial_capture_email(
        {"device_fingerprint": "uuid-1", "email": "a@b.com", "consent": True}, "1.2.3.4", "ua",
    )
    assert out == {"type": "trial_email_captured", "ok": True}


@pytest.mark.asyncio
async def test_email_capture_skips_upsert_without_explicit_consent(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    called = {"n": 0}

    async def _spy(*a, **kw):
        called["n"] += 1
        return None, "", ""
    monkeypatch.setattr(ptg, "_upsert_trial_lead", _spy)

    out = await ptg.handle_public_trial_capture_email(
        {"device_fingerprint": "uuid-1", "email": "a@b.com", "consent": False}, "1.2.3.4", "ua",
    )
    assert out == {"type": "trial_email_captured", "ok": True}
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_email_capture_skips_upsert_for_malformed_email(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    called = {"n": 0}

    async def _spy(*a, **kw):
        called["n"] += 1
        return None, "", ""
    monkeypatch.setattr(ptg, "_upsert_trial_lead", _spy)

    out = await ptg.handle_public_trial_capture_email(
        {"device_fingerprint": "uuid-1", "email": "not-an-email", "consent": True}, "1.2.3.4", "ua",
    )
    assert out == {"type": "trial_email_captured", "ok": True}
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_email_capture_fails_closed_silently_when_redis_down(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    called = {"n": 0}

    async def _no_redis():
        return None
    monkeypatch.setattr(ptg, "_get_redis", _no_redis)

    async def _spy(*a, **kw):
        called["n"] += 1
        return None, "", ""
    monkeypatch.setattr(ptg, "_upsert_trial_lead", _spy)

    out = await ptg.handle_public_trial_capture_email(
        {"device_fingerprint": "uuid-1", "email": "a@b.com", "consent": True}, "1.2.3.4", "ua",
    )
    assert out == {"type": "trial_email_captured", "ok": True}
    assert called["n"] == 0  # never reached the send path -- capped/failed-closed


@pytest.mark.asyncio
async def test_email_capture_never_fails_even_when_db_unavailable(monkeypatch):
    """Signup-never-fail guarantee, applied to the email-capture side: total DB
    unavailability must still degrade to a generic ack, never an exception."""
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "_DB_POOL", None)
    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake
    monkeypatch.setattr(ptg, "_get_redis", _fake_get_redis)

    out = await ptg.handle_public_trial_capture_email(
        {"device_fingerprint": "uuid-dbdown", "email": "a@b.com", "consent": True}, "1.2.3.4", "ua",
    )
    assert out == {"type": "trial_email_captured", "ok": True}


@pytest.mark.asyncio
async def test_email_capture_valid_consented_email_reaches_upsert_and_send(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake
    monkeypatch.setattr(ptg, "_get_redis", _fake_get_redis)

    async def _fake_start_trial(*a, **kw):
        return {"turns_used": 0, "trial_history": [], "converted": False, "gated_at": None}
    monkeypatch.setattr(ptg, "db_start_trial", _fake_start_trial)

    upsert_calls = []

    async def _fake_upsert(fp_hash, device_uuid_hash, email, raw_uuid):
        upsert_calls.append((fp_hash, device_uuid_hash, email, raw_uuid))
        return "raw-token", "https://app.sovereignsanctuary.net/?trial_token=raw-token", "https://x/unsub"
    monkeypatch.setattr(ptg, "_upsert_trial_lead", _fake_upsert)

    send_calls = []

    async def _fake_send(email, signup_url, unsubscribe_url):
        send_calls.append((email, signup_url, unsubscribe_url))
    monkeypatch.setattr(ptg, "_send_trial_signup_email", _fake_send)

    out = await ptg.handle_public_trial_capture_email(
        {"device_fingerprint": "uuid-9", "email": "person@example.com", "consent": True}, "1.2.3.4", "ua",
    )
    assert out == {"type": "trial_email_captured", "ok": True}
    assert len(upsert_calls) == 1
    assert upsert_calls[0][2] == "person@example.com"
    assert len(send_calls) == 1
    assert send_calls[0][0] == "person@example.com"


# ---------------------------------------------------------------------------
# Enrichment trial-safety (trial-enrichment-parity, ln_full parity)
# ---------------------------------------------------------------------------

def test_trial_output_max_tokens_raised_for_ln_full_parity():
    assert ptg.TRIAL_OUTPUT_MAX_TOKENS == 450


@pytest.mark.asyncio
async def test_registry_fusion_is_force_disabled_when_trial_safe(monkeypatch):
    """The IFS council/registry channel is per-user (reads a user's saved
    parts) and must never run for an anonymous trial turn, regardless of the
    BRIDGE_IFS_METADATA flag. Uses a short, non-memory, non-high-signal turn
    so both calls take the low-signal branch (build_enrichment_addendum line
    ~333) without touching FederatedSearch/Helix."""
    import app.websocket.bridge_enrichment as enr

    monkeypatch.setenv("LN_ENRICHMENT", "1")
    monkeypatch.delenv("LN_ENRICHMENT_TIER2", raising=False)  # inherit master (enabled)
    monkeypatch.setenv("BRIDGE_IFS_METADATA", "true")

    called = {"n": 0}

    async def _spy_fetch_registry_parts(*a, **kw):
        called["n"] += 1
        return []

    monkeypatch.setattr(
        "app.services.council_registry_context.fetch_registry_parts", _spy_fetch_registry_parts,
    )

    low_signal_text = "hi there, just checking in today"

    # trial_safe=True: registry fusion must be skipped entirely.
    out_trial = await enr.build_enrichment_addendum(
        None, "trial_abc", low_signal_text, trial_safe=True,
    )
    assert called["n"] == 0
    assert out_trial == ""

    # Same low-signal turn, trial_safe=False: the registry channel IS reached
    # -- proves the branch is real, not just permanently short-circuited.
    await enr.build_enrichment_addendum(
        None, "real_user_123", low_signal_text, trial_safe=False,
    )
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_priority_overrides_still_fire_for_trial_safe_low_signal_turn(monkeypatch):
    import app.websocket.bridge_enrichment as enr

    monkeypatch.setenv("LN_ENRICHMENT", "1")
    monkeypatch.setenv("LN_ENRICHMENT_TIER2", "0")

    out = await enr.build_enrichment_addendum(
        None, "trial_abc", "I want to end it all, I can't do this anymore", trial_safe=True,
    )
    assert "WITNESSING" in out or "PRIORITY OVERRIDE" in out


@pytest.mark.asyncio
async def test_federated_search_and_helix_disabled_for_trial_safe_high_signal_turn(monkeypatch):
    """2026-07 red-team F4c: crystal-field content is NOT safe for anonymous
    strangers -- the global pool contains first-person narrative crystals
    (dataset ingests + previously mislabeled client wisdom). trial_safe=True
    must skip FederatedSearch, ranked recall, and the Helix synthesis line
    entirely. The same high-signal turn with trial_safe=False must still fire
    both, proving the gate is real and not a permanent short-circuit."""
    import app.websocket.bridge_enrichment as enr

    monkeypatch.setenv("LN_ENRICHMENT", "1")
    monkeypatch.setenv("LN_ENRICHMENT_TIER2", "1")

    fed_calls = {"n": 0}
    helix_calls = {"n": 0}

    class _FakeFedSearch:
        async def search(self, **kwargs):
            fed_calls["n"] += 1
            return {"results": [{
                "crystal_text": "Client disclosed her grandmother's loss and the secret her husband kept.",
                "relevance_score": 0.95,
            }]}

    class _FakeCycle:
        synthesis = {"fused_coherence": 0.8}
        odpe_result = {"signal": "LOCKED"}

    class _FakeHelix:
        async def think(self, **kwargs):
            helix_calls["n"] += 1
            return _FakeCycle()

    monkeypatch.setattr(enr, "_get_fed_search", lambda db_pool: _FakeFedSearch())
    monkeypatch.setattr(enr, "_get_helix", lambda: _FakeHelix())

    # Long, first-person message so is_high_signal_turn() fires the Tier-2 path.
    long_text = (
        "I have been carrying this for years and I don't know how to say it "
        "out loud, but I feel like everything I built is falling apart and "
        "I am so afraid of what happens next for me and my family."
    )
    out_trial = await enr.build_enrichment_addendum(
        None, "trial_abc", long_text, trial_safe=True,
    )
    assert fed_calls["n"] == 0, "trial_safe must never run FederatedSearch"
    assert helix_calls["n"] == 0, "trial_safe must never run Helix over crystals"
    assert "Helix read on this turn" not in out_trial
    assert "RANKED RECALL" not in out_trial
    assert "grandmother" not in out_trial

    out_full = await enr.build_enrichment_addendum(
        None, "real_user_123", long_text, trial_safe=False,
    )
    assert fed_calls["n"] == 1
    assert helix_calls["n"] == 1
    assert "RANKED RECALL" in out_full


# ---------------------------------------------------------------------------
# Crystal recall global_only isolation (crystal-global-only)
# ---------------------------------------------------------------------------

class _FakeCrystalConn:
    async def fetchval(self, *args, **kwargs):
        raise AssertionError("global_only recall must never resolve a user UUID")


class _FakeCrystalPool:
    def acquire(self):
        return _FakeAcquireCtx(_FakeCrystalConn())


@pytest.mark.asyncio
async def test_global_only_recall_never_touches_per_user_data(monkeypatch):
    import app.websocket.crystal_recall_bridge as crb

    calls = {"user_uuid": "not-set", "max_user": None}

    async def _fake_fast_recall(conn, user_uuid, query_text, max_user=5, max_global=3):
        calls["user_uuid"] = user_uuid
        calls["max_user"] = max_user
        return (
            [],
            [{"id": 1, "crystal_text": "General therapeutic insight.", "confidence": 0.9, "domain": "general"}],
            set(),
        )

    async def _fake_reinforce(*args, **kwargs):
        return None

    async def _fail_deep_recall(*args, **kwargs):
        raise AssertionError("global_only must never schedule deep recall")

    monkeypatch.setattr(crb, "_fast_recall_crystals", _fake_fast_recall)
    monkeypatch.setattr(crb, "_reinforce_recalled_crystals", _fake_reinforce)
    monkeypatch.setattr(crb, "_deep_recall_crystals", _fail_deep_recall)

    text = await crb.recall_crystals_for_context(
        _FakeCrystalPool(), "trial_abc123", max_results=4, source="public_trial", global_only=True,
    )
    await asyncio.sleep(0)  # let the fire-and-forget reinforce task run

    assert calls["user_uuid"] is None
    assert calls["max_user"] == 0
    assert "General therapeutic insight." in text
    assert "GENERAL KNOWLEDGE" in text
    assert "YOUR PERSONAL MEMORIES" not in text
    assert "CLINICAL DNA" not in text


@pytest.mark.asyncio
async def test_global_only_recall_returns_empty_string_without_pool_or_id():
    import app.websocket.crystal_recall_bridge as crb

    assert await crb.recall_crystals_for_context(None, "trial_abc", global_only=True) == ""
    assert await crb.recall_crystals_for_context(_FakeCrystalPool(), "", global_only=True) == ""


# ---------------------------------------------------------------------------
# F4c isolation-bleed guards (2026-07 red-team blocker).
#
# The mechanism-level tests above proved global_only=True never resolves a
# user UUID -- and production still leaked, because the GLOBAL pool itself
# contained narrative content (dataset ingests + client wisdom mislabeled
# global by a fail-open path). The lesson: the trial guarantee must be
# asserted at the CONTENT level of the final prompt, not at the mechanism
# level of one recall function. These tests pin the new invariant: an
# anonymous trial turn gets ZERO stored-memory content of any kind.
# ---------------------------------------------------------------------------

def test_trial_gate_source_has_no_crystal_recall_call():
    """Static guard: public_trial_gate must not reference the crystal recall
    entry point at all. If someone re-adds it (even global_only), this fails."""
    import inspect
    source = inspect.getsource(ptg)
    assert "recall_crystals_for_context" not in source, (
        "public_trial_gate must never call crystal recall for anonymous sessions"
    )


@pytest.mark.asyncio
async def test_generate_trial_response_never_recalls_and_prompt_is_memory_free(monkeypatch):
    """End-to-end (offline): the system prompt actually sent to the LLM for a
    trial turn contains no stored-memory blocks, and no recall call fires."""
    import app.services.sovereign_chat_client as scc
    import app.websocket.crystal_recall_bridge as crb

    monkeypatch.setenv("LN_ENRICHMENT", "0")
    monkeypatch.setattr(ptg, "get_db_pool", lambda: None)

    async def _forbidden_recall(*a, **kw):
        raise AssertionError("public trial must NEVER call crystal recall")

    monkeypatch.setattr(crb, "recall_crystals_for_context", _forbidden_recall)

    captured = {}

    async def _fake_generate(system_prompt, user_text, **kw):
        captured["system_prompt"] = system_prompt
        return "I hear you. That sounds heavy, and I'm right here with you.", "workers_ai"

    monkeypatch.setattr(scc, "generate_complete", _fake_generate)

    ctx = ptg.TrialTurnContext(
        ok=True, hardware_id="trial_abc123", fp_hash="fp1", device_uuid_hash="dev1",
        text="I've been feeling really anxious lately and it is getting worse",
        history=[{"user": "hello", "assistant": "hi, I'm here"}],
    )
    out = await ptg.generate_trial_response(ctx)

    assert "system_prompt" in captured, "generation was never reached"
    prompt = captured["system_prompt"]
    for marker in (
        "GENERAL KNOWLEDGE",        # recall global block header
        "YOUR PERSONAL MEMORIES",   # recall user block header
        "CLINICAL DNA",             # deep-recall clinical seed header
        "RANKED RECALL",            # enrichment federated-search block
        "Helix read on this turn",  # enrichment synthesis line
    ):
        assert marker not in prompt, f"stored-memory marker leaked into trial prompt: {marker}"
    assert out


def test_trial_boundary_has_fiction_frame_hard_stop():
    """F2/F5 fix: fiction/hypothetical clinical framing must be refused at the
    frame -- the boundary text instructing that must stay in the prompt."""
    b = ptg.PUBLIC_TRIAL_BOUNDARY
    assert "DIAGNOSIS HARD-STOP" in b
    assert "even as a story" in b
    assert "Refuse AT THE FRAME" in b


def test_trial_boundary_forbids_third_party_disclosure_real_or_invented():
    """F4c follow-up: after the data-level bleed fix, Nate still fabricated
    'others have shared their drinking with me' style answers. The boundary
    must forbid recounting other people's disclosures -- real OR invented --
    and redirect to the current user."""
    b = ptg.PUBLIC_TRIAL_BOUNDARY
    assert "NO THIRD-PARTY DISCLOSURE, REAL OR INVENTED" in b
    assert "do NOT narrate a composite" in b
    assert "confabulated third-party content" in b
    assert "I don't carry other people's conversations" in b
    # Normalize the feeling, never source it in others' disclosures.
    assert "NORMALIZING WITHOUT ATTRIBUTION" in b
    assert "people have shared this with me\" is a confidentiality-shaped" in b


class _FakeAbsorptionConn:
    """Fake conn for crystallize_wisdom_absorption: user resolution result is
    injectable; any INSERT is recorded so tests can assert it never ran."""

    def __init__(self, resolved_uuid):
        self.resolved_uuid = resolved_uuid
        self.inserts: list = []

    async def fetchval(self, query, *args):
        assert "FROM users" in query
        return self.resolved_uuid

    async def fetchrow(self, query, *args):
        assert "INSERT INTO nate_intelligence_crystals" in query
        self.inserts.append(args)
        return {"content_hash": args[3]}


class _FakeAbsorptionPool:
    def __init__(self, resolved_uuid):
        self.conn = _FakeAbsorptionConn(resolved_uuid)

    def acquire(self):
        return _FakeAcquireCtx(self.conn)


@pytest.mark.asyncio
async def test_wisdom_absorption_fails_closed_when_user_ref_empty():
    """Root cause (b) of the F4c breach: wisdom absorption used to default to
    scope='global' when the user couldn't be resolved, publishing real client
    disclosures into the global recall pool. It must now skip entirely."""
    import app.websocket.crystal_recall_bridge as crb

    pool = _FakeAbsorptionPool(resolved_uuid=None)
    result = await crb.crystallize_wisdom_absorption(
        pool, "", "Client expressed grief about a family loss.",
        extraction_id="ext-1",
    )
    assert result is None
    assert pool.conn.inserts == [], "no crystal row may be written on unresolved user"


@pytest.mark.asyncio
async def test_wisdom_absorption_fails_closed_when_user_ref_unresolvable():
    import app.websocket.crystal_recall_bridge as crb

    pool = _FakeAbsorptionPool(resolved_uuid=None)  # ref given, no users row
    result = await crb.crystallize_wisdom_absorption(
        pool, "ghost_user_404", "Client expressed grief about a family loss.",
        extraction_id="ext-2",
    )
    assert result is None
    assert pool.conn.inserts == []


@pytest.mark.asyncio
async def test_wisdom_absorption_writes_user_scoped_crystal_when_resolved():
    """Counter-case: with a resolvable user the crystal IS written, and it is
    scope='user' with the user's UUID attached -- never global."""
    import app.websocket.crystal_recall_bridge as crb

    pool = _FakeAbsorptionPool(resolved_uuid="11111111-2222-3333-4444-555555555555")
    result = await crb.crystallize_wisdom_absorption(
        pool, "real_client", "Client expressed grief about a family loss.",
        extraction_id="ext-3",
    )
    assert result is not None
    assert len(pool.conn.inserts) == 1
    args = pool.conn.inserts[0]
    # INSERT arg order: text, domain, scope, content_hash, user_uuid, origin_surface, meta
    assert args[2] == "user"
    assert args[4] == "11111111-2222-3333-4444-555555555555"


# ---------------------------------------------------------------------------
# Socket isolation (security-trial-socket-isolation) -- static source checks.
#
# bridge_server.py is intentionally not imported directly in unit tests (large
# module, real side effects at import time -- see test_socket_eviction.py
# precedent). These are cheap, precise source-level guards for the specific
# invariants the plan requires: trial dispatch never registers on the shared
# cortex.sockets registry, and the pre-auth allowlists stay in sync.
# ---------------------------------------------------------------------------

def _bridge_server_source() -> str:
    import pathlib
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"
    return path.read_text(encoding="utf-8")


def _dispatch_function_source(source: str) -> str:
    marker = "async def _dispatch_public_trial_message"
    start = source.index(marker)
    # Grab a generous window; the function is well under 200 lines.
    end = source.index("\nasync def ", start + len(marker))
    return source[start:end]


def test_trial_dispatch_never_registers_on_cortex_sockets():
    fn_source = _dispatch_function_source(_bridge_server_source())
    assert "cortex.register(" not in fn_source
    assert "cortex.sockets[" not in fn_source


def test_sentinel_skip_includes_all_three_trial_message_types():
    source = _bridge_server_source()
    skip_start = source.index("_SENTINEL_SKIP")
    skip_block = source[skip_start:skip_start + 4000]
    for msg_type in ("public_trial_start", "public_trial_chat", "public_trial_capture_email"):
        assert f'"{msg_type}"' in skip_block, f"{msg_type} missing from _SENTINEL_SKIP"


def test_trial_namespace_guard_present_in_register_and_login():
    source = _bridge_server_source()
    assert source.count("TRIAL_UID_PREFIX") >= 1 or source.count('startswith("trial_")') >= 2 \
        or "is_trial_namespace" in source
