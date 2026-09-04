"""Public Trial Funnel — Cloudflare Turnstile bot-abuse hardening (2026-07).

Covers the four leverage points closed in this hardening pass:

1. `public_trial_start` requires and verifies a Turnstile token before any
   trial row is created (fails closed: missing/invalid token -> a NEW device
   fingerprint gets `turnstile_required`, never a silent bypass).
2. `public_trial_chat` re-checks a sliding "device verified" window (set by
   #1) before any inference -- so a client can't skip straight to
   `public_trial_chat` and bypass the Turnstile challenge entirely. Crisis
   turns always bypass this check (never gate a suicide/self-harm
   disclosure behind a bot check).
3. The global per-HOUR cap (companion to the existing per-day cap) rejects a
   burst before it can drain the whole day's shared budget in minutes.
4. Exhausting a global cap (daily or hourly) fires an admin alert exactly
   once per dedup window, not once per rejected request.

No live DB/Redis/LLM/network calls -- everything is mocked or exercised via
small fakes so this suite runs fully offline (see ci-gate-before-push.mdc).
"""
from __future__ import annotations

import pytest

import app.services.public_trial_gate as ptg


# ---------------------------------------------------------------------------
# Fakes (self-contained; mirrors test_public_trial_isolation.py's fakes so
# this file has no cross-file import coupling)
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
        # window still open".
        return key in self.locks

    async def ttl(self, key):
        # Only consulted by _incr_with_cap on the cap-exceeded branch, to
        # build an honest "try again in N minutes" phrase. Exact value isn't
        # asserted by these tests -- any positive int exercises that path.
        return 300 if key in self.counters else -1

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
            fp_hash, device_uuid_hash = args[0], args[1]
            ip_hash = args[2] if len(args) > 2 else None
            row = self.store.get(device_uuid_hash)
            if row is None:
                row = {
                    "turns_used": 0, "trial_history": [], "converted": False,
                    "gated_at": None, "device_fingerprint": fp_hash,
                    "ip_hash": ip_hash,
                }
                self.store[device_uuid_hash] = row
            else:
                row["device_fingerprint"] = fp_hash
                if ip_hash:
                    row["ip_hash"] = ip_hash
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
            if len(args) > 1 and args[1]:
                row["ip_hash"] = args[1]
            return row["turns_used"]
        raise AssertionError(f"unexpected fetchval query: {query}")

    async def execute(self, query, *args):
        if "trial_history" in query:
            device_uuid_hash = args[-1]
            self.store.setdefault(device_uuid_hash, {
                "turns_used": 0, "trial_history": [], "converted": False, "gated_at": None,
            })
            return None
        raise AssertionError(f"unexpected execute query: {query}")


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


def _fake_redis_ctx(monkeypatch, redis: _FakeRedis):
    async def _fake_get_redis():
        return redis
    monkeypatch.setattr(ptg, "_get_redis", _fake_get_redis)


# ---------------------------------------------------------------------------
# verify_turnstile_token — the single call site, gated by the feature flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_turnstile_token_bypasses_check_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", False)
    # Even an empty/garbage token passes -- the flag is the single source of
    # truth for whether verification runs at all (local dev without
    # TURNSTILE_SECRET_KEY configured, or a test not exercising this path).
    assert await ptg.verify_turnstile_token("", "1.2.3.4") is True
    assert await ptg.verify_turnstile_token("garbage", "1.2.3.4") is True


@pytest.mark.asyncio
async def test_verify_turnstile_token_delegates_to_turnstile_service_when_enabled(monkeypatch):
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)
    calls = []

    async def _fake_verify(token, remote_ip=None):
        calls.append((token, remote_ip))
        return token == "good-token"

    monkeypatch.setattr("app.services.turnstile.verify_turnstile", _fake_verify)

    assert await ptg.verify_turnstile_token("good-token", "9.9.9.9") is True
    assert await ptg.verify_turnstile_token("bad-token", "9.9.9.9") is False
    assert calls == [("good-token", "9.9.9.9"), ("bad-token", "9.9.9.9")]


# ---------------------------------------------------------------------------
# prepare_public_trial_start — the single highest-leverage gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prepare_public_trial_start_requires_token_when_enabled(monkeypatch):
    pool = _FakeTrialPool()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)

    out = await ptg.prepare_public_trial_start(
        {"device_fingerprint": "uuid-no-token"}, "1.2.3.4", "ua",
    )

    assert out == {"type": "turnstile_required"}
    # No DB row was created -- a rejected challenge must never lazily start
    # a trial session.
    assert pool.store == {}


@pytest.mark.asyncio
async def test_prepare_public_trial_start_rejects_invalid_token(monkeypatch):
    pool = _FakeTrialPool()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)

    async def _reject(token, ip):
        return False
    monkeypatch.setattr(ptg, "verify_turnstile_token", _reject)

    out = await ptg.prepare_public_trial_start(
        {"device_fingerprint": "uuid-bad-token", "turnstile_token": "whatever"}, "1.2.3.4", "ua",
    )

    assert out == {"type": "turnstile_required"}
    assert pool.store == {}


@pytest.mark.asyncio
async def test_prepare_public_trial_start_accepts_valid_token_and_marks_device_verified(monkeypatch):
    pool = _FakeTrialPool()
    redis = _FakeRedis()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)
    _fake_redis_ctx(monkeypatch, redis)

    async def _accept(token, ip):
        return token == "solved-challenge"
    monkeypatch.setattr(ptg, "verify_turnstile_token", _accept)

    out = await ptg.prepare_public_trial_start(
        {"device_fingerprint": "uuid-good-token", "turnstile_token": "solved-challenge"}, "1.2.3.4", "ua",
    )

    assert out["type"] == "trial_state"
    assert out["turns_used"] == 0
    assert out["turns_limit"] == ptg.TRIAL_TURN_LIMIT

    # The trial row was created...
    device_uuid_hash = ptg.compute_device_uuid_hash("uuid-good-token")
    assert device_uuid_hash in pool.store

    # ...and the sliding verification window was opened in Redis so the next
    # public_trial_chat turn doesn't get re-challenged.
    from app.services.trial_signup_redis_keys import public_trial_verified_key
    assert public_trial_verified_key(device_uuid_hash) in redis.locks


# ---------------------------------------------------------------------------
# prepare_public_trial_turn — the sliding-window re-check that closes the
# "skip straight to public_trial_chat" bypass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prepare_public_trial_turn_requires_verified_device_when_unverified(monkeypatch):
    pool = _FakeTrialPool()
    redis = _FakeRedis()  # never marked verified
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)
    _fake_redis_ctx(monkeypatch, redis)

    async def _no_crisis(text):
        return []
    monkeypatch.setattr(ptg, "check_crisis", _no_crisis)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-unverified", "text": "hello"}, "1.2.3.4", "ua",
    )

    assert ctx.ok is False
    assert ctx.payload == {"type": "turnstile_required"}
    # The turn was never counted -- a device that skipped the challenge gets
    # re-challenged, not a free (uncounted) inference.
    device_uuid_hash = ptg.compute_device_uuid_hash("uuid-unverified")
    assert pool.store.get(device_uuid_hash, {}).get("turns_used", 0) == 0


@pytest.mark.asyncio
async def test_prepare_public_trial_turn_proceeds_when_device_already_verified(monkeypatch):
    pool = _FakeTrialPool()
    redis = _FakeRedis()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)
    _fake_redis_ctx(monkeypatch, redis)

    # Simulate a device that already solved Turnstile at public_trial_start.
    device_uuid_hash = ptg.compute_device_uuid_hash("uuid-verified")
    from app.services.trial_signup_redis_keys import public_trial_verified_key
    redis.locks.add(public_trial_verified_key(device_uuid_hash))

    async def _no_crisis(text):
        return []
    monkeypatch.setattr(ptg, "check_crisis", _no_crisis)

    async def _allow(*a, **kw):
        return ptg.AbuseCheckResult(True, "", True)
    monkeypatch.setattr(ptg, "check_turn_abuse_caps", _allow)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-verified", "text": "hello there"}, "1.2.3.4", "ua",
    )

    assert ctx.ok is True
    assert ctx.payload is None
    assert ctx.turns_used == 1


@pytest.mark.asyncio
async def test_prepare_public_trial_turn_crisis_bypasses_verification_even_when_unverified(monkeypatch):
    """A suicide/self-harm disclosure must never be met with a bot check --
    consistent with it already bypassing the turn limit and abuse caps."""
    pool = _FakeTrialPool()
    redis = _FakeRedis()  # never marked verified
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)
    _fake_redis_ctx(monkeypatch, redis)

    async def _crisis(text):
        return ["kill myself"]
    monkeypatch.setattr(ptg, "check_crisis", _crisis)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-crisis-unverified", "text": "I want to kill myself"}, "1.2.3.4", "ua",
    )

    assert ctx.ok is True
    assert ctx.is_crisis is True
    assert ctx.payload is None


@pytest.mark.asyncio
async def test_prepare_public_trial_turn_reverifies_after_sliding_window_expires(monkeypatch):
    """A device that solved Turnstile over an hour ago (sliding window
    lapsed) must be re-challenged, not grandfathered in forever."""
    pool = _FakeTrialPool()
    redis = _FakeRedis()
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_TURNSTILE_ENABLED", True)
    _fake_redis_ctx(monkeypatch, redis)
    # Key never existed / already expired out of the fake's `locks` set --
    # _FakeRedis.expire() returns False for exactly this case.

    async def _no_crisis(text):
        return []
    monkeypatch.setattr(ptg, "check_crisis", _no_crisis)

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-expired-window", "text": "hello"}, "1.2.3.4", "ua",
    )

    assert ctx.ok is False
    assert ctx.payload == {"type": "turnstile_required"}


# ---------------------------------------------------------------------------
# Global per-HOUR cap — bounds how much of the daily budget one burst drains
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_turn_abuse_caps_enforces_global_hourly_cap(monkeypatch):
    redis = _FakeRedis()
    _fake_redis_ctx(monkeypatch, redis)
    monkeypatch.setattr(ptg, "MAX_TRIAL_TURNS_PER_HOUR", 2)
    # Keep every other cap far out of reach so only the hourly cap can fire.
    monkeypatch.setattr(ptg, "_IP_DAILY_CAP", 1000)
    monkeypatch.setattr(ptg, "MAX_TRIAL_TURNS_PER_DAY", 1000)
    monkeypatch.setattr(ptg, "_FP_HOURLY_CAP", 1000)

    alert_calls = []

    async def _fake_alert(cap_kind):
        alert_calls.append(cap_kind)
    monkeypatch.setattr(ptg, "_alert_global_cap_depleted", _fake_alert)

    # Distinct IPs/fingerprints so per-IP and per-fp caps never trip --
    # isolates the assertion to the shared global-hourly counter.
    r1 = await ptg.check_turn_abuse_caps("1.1.1.1", "fp-a")
    r2 = await ptg.check_turn_abuse_caps("2.2.2.2", "fp-b")
    r3 = await ptg.check_turn_abuse_caps("3.3.3.3", "fp-c")

    assert r1.allowed is True
    assert r2.allowed is True
    assert r3.allowed is False
    assert r3.reason == "global_hourly_cap"
    assert alert_calls == ["global_hourly_cap"]


@pytest.mark.asyncio
async def test_check_turn_abuse_caps_hourly_cap_fires_before_fp_hourly_cap(monkeypatch):
    """The global hourly cap check runs before the per-fp hourly cap, so a
    single fingerprint hammering the shared budget is caught by the global
    signal (and alerts) rather than silently absorbed as a personal-cap hit."""
    redis = _FakeRedis()
    _fake_redis_ctx(monkeypatch, redis)
    monkeypatch.setattr(ptg, "MAX_TRIAL_TURNS_PER_HOUR", 1)
    monkeypatch.setattr(ptg, "_IP_DAILY_CAP", 1000)
    monkeypatch.setattr(ptg, "MAX_TRIAL_TURNS_PER_DAY", 1000)
    monkeypatch.setattr(ptg, "_FP_HOURLY_CAP", 1000)

    async def _fake_alert(cap_kind):
        pass
    monkeypatch.setattr(ptg, "_alert_global_cap_depleted", _fake_alert)

    r1 = await ptg.check_turn_abuse_caps("1.2.3.4", "same-fp")
    r2 = await ptg.check_turn_abuse_caps("1.2.3.4", "same-fp")

    assert r1.allowed is True
    assert r2.allowed is False
    assert r2.reason == "global_hourly_cap"


# ---------------------------------------------------------------------------
# Global cap depletion alert — real-time signal, deduped per window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_global_cap_depleted_sends_email_once_per_window(monkeypatch):
    redis = _FakeRedis()
    _fake_redis_ctx(monkeypatch, redis)

    sent = []

    async def _fake_send_crisis_alert(self, to_email, client_name, alert_type, details):
        sent.append((client_name, alert_type))
        return True

    monkeypatch.setattr(
        "app.services.notifications_service.EmailService.send_crisis_alert",
        _fake_send_crisis_alert,
    )

    await ptg._alert_global_cap_depleted("global_hourly_cap")
    await ptg._alert_global_cap_depleted("global_hourly_cap")
    await ptg._alert_global_cap_depleted("global_hourly_cap")

    # A sustained flood of rejected requests against an exhausted cap must
    # not become a flood of admin emails -- SETNX dedup means exactly one
    # alert fires for this cap_kind within the dedup window.
    assert sent == [("Public Trial Funnel", "TRIAL_GLOBAL_HOURLY_CAP_EXHAUSTED")]


@pytest.mark.asyncio
async def test_alert_global_cap_depleted_dedupes_independently_per_cap_kind(monkeypatch):
    redis = _FakeRedis()
    _fake_redis_ctx(monkeypatch, redis)

    sent = []

    async def _fake_send_crisis_alert(self, to_email, client_name, alert_type, details):
        sent.append(alert_type)
        return True

    monkeypatch.setattr(
        "app.services.notifications_service.EmailService.send_crisis_alert",
        _fake_send_crisis_alert,
    )

    await ptg._alert_global_cap_depleted("global_hourly_cap")
    await ptg._alert_global_cap_depleted("global_daily_cap")

    # Different cap kinds are independent signals -- both alerts land.
    assert sent == ["TRIAL_GLOBAL_HOURLY_CAP_EXHAUSTED", "TRIAL_GLOBAL_DAILY_CAP_EXHAUSTED"]


@pytest.mark.asyncio
async def test_alert_global_cap_depleted_never_raises_on_redis_dedup_set_failure(monkeypatch):
    """Alerting must not be able to break the abuse-cap check path it's
    called from -- a Redis error on the dedup SETNX degrades to "no alert",
    not a crash of the request the caller is trying to reject."""
    class _BrokenRedis(_FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            raise RuntimeError("redis unreachable")

    _fake_redis_ctx(monkeypatch, _BrokenRedis())

    # Should not raise.
    await ptg._alert_global_cap_depleted("global_daily_cap")


@pytest.mark.asyncio
async def test_alert_global_cap_depleted_never_raises_on_email_failure(monkeypatch):
    redis = _FakeRedis()
    _fake_redis_ctx(monkeypatch, redis)

    async def _broken_send(self, *a, **kw):
        raise RuntimeError("sendgrid down")

    monkeypatch.setattr(
        "app.services.notifications_service.EmailService.send_crisis_alert",
        _broken_send,
    )

    # Should not raise even though the email send itself blows up.
    await ptg._alert_global_cap_depleted("global_hourly_cap")
