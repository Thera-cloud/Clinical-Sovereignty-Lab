"""GA hardening tests — 2026-06-09 pre-GA flaw review fixes.

Covers:
  - settings TTL cache (read reduction + invalidation)
  - bridge telemetry counters (failure kinds, consecutive escalation, success reset)
  - cached default service instances (per-pool singleton)
  - detection-only sweep (safe no-op without pool; never raises)
  - prepare_therapeutic_context additive params (session_id/coach_id)
"""
import asyncio
import inspect

import pytest

from app.services import sensitive_clinical_bridge as scb


# ── Settings TTL cache ──────────────────────────────────────────────────────

def test_settings_cache_roundtrip_and_invalidate():
    scb.invalidate_settings_cache()
    hit, _ = scb._settings_cache_get("master_enabled")
    assert hit is False
    scb._settings_cache_put("master_enabled", True)
    hit, val = scb._settings_cache_get("master_enabled")
    assert hit is True and val is True
    scb.invalidate_settings_cache()
    hit, _ = scb._settings_cache_get("master_enabled")
    assert hit is False


def test_read_master_enabled_cache_hit_skips_db():
    """A cache hit must short-circuit before any pool.acquire() call."""
    class ExplodingPool:
        def acquire(self):
            raise AssertionError("DB hit despite warm cache")

    scb.invalidate_settings_cache()
    scb._settings_cache_put("master_enabled", True)
    result = asyncio.run(scb._read_master_enabled(ExplodingPool()))
    assert result is True
    scb.invalidate_settings_cache()


def test_read_master_enabled_no_pool_fails_closed():
    scb.invalidate_settings_cache()
    assert asyncio.run(scb._read_master_enabled(None)) is False


# ── Telemetry ───────────────────────────────────────────────────────────────

def test_telemetry_failure_and_success_reset():
    scb.record_bridge_success()  # reset consecutive
    base = scb.get_bridge_telemetry()
    scb.record_bridge_failure("timeout", "test")
    scb.record_bridge_failure("error", "test")
    t = scb.get_bridge_telemetry()
    assert t["eval_timeouts"] == base["eval_timeouts"] + 1
    assert t["eval_errors"] == base["eval_errors"] + 1
    assert t["consecutive_failures"] == 2
    assert t["last_error"].startswith("error:")
    scb.record_bridge_success()
    t2 = scb.get_bridge_telemetry()
    assert t2["consecutive_failures"] == 0


def test_telemetry_identity_unresolved_counter():
    before = scb.get_bridge_telemetry()["identity_unresolved"]
    scb.record_bridge_failure("identity_unresolved", "raw_id='HW123'")
    after = scb.get_bridge_telemetry()["identity_unresolved"]
    assert after == before + 1
    scb.record_bridge_success()


# ── Cached default services ─────────────────────────────────────────────────

def test_default_services_cached_per_pool():
    class FakePool:
        pass

    pool = FakePool()
    a1 = scb.get_default_checkin_agent(pool)
    a2 = scb.get_default_checkin_agent(pool)
    assert a1 is a2  # same instance per pool (may be None if import fails)
    r1 = scb.get_default_reporting_service(pool)
    r2 = scb.get_default_reporting_service(pool)
    assert r1 is r2


# ── Detection-only sweep ────────────────────────────────────────────────────

def test_run_detection_only_no_pool_is_safe():
    # Must never raise; without a pool the pipeline degrades gracefully.
    asyncio.run(scb.run_detection_only(None, "someuser", "hello", source="family_sanctuary"))


def test_schedule_detection_only_without_loop_is_safe():
    # No running loop in sync context — must not raise.
    scb.schedule_detection_only(None, "someuser", "hello", source="voice_call")


# ── Controller signature (additive params) ──────────────────────────────────

def test_prepare_therapeutic_context_accepts_session_and_coach():
    from app.services.therapeutic_controller import prepare_therapeutic_context

    sig = inspect.signature(prepare_therapeutic_context)
    assert "session_id" in sig.parameters
    assert "coach_id" in sig.parameters
    assert sig.parameters["session_id"].default is None
    assert sig.parameters["coach_id"].default is None


def test_eval_timeout_constant_positive():
    assert scb.EVAL_TIMEOUT_S > 0
