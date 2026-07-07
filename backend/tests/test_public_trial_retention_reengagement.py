"""Public Trial Funnel -- retention purge + re-engagement follow-up tests.

Covers the plan's `security-trial-retention-purge` and
`trial-email-reengagement` todos:

- GET /api/public-trial/unsubscribe is read-only (bot/scanner prefetch safe)
- POST /api/public-trial/unsubscribe is the only path that mutates
  `unsubscribed_at`, and unsubscribing must NOT block the Phase 3
  `trial_token` merge (unsubscribe = "stop emailing me", not "forget our
  conversation")
- The one-time follow-up email cycle: sent at most once per lead, gated on
  unconverted + not-unsubscribed + delay-elapsed + not-expired + has-email
- db_maintenance_agent's three new purge methods: trial_history cleared,
  flagged-turn text nulled, and lead emails nulled, each past their own
  retention window and never touching rows inside the window

No live DB/Redis/network calls -- everything is mocked or exercised via
small in-memory fakes so this suite runs fully offline (see
ci-gate-before-push.mdc).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("JWT_SECRET", "test-only-not-a-real-secret-0123456789abcdef")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.public_trial_gate as ptg
import app.services.public_trial_conversion as ptc
import app.routers.public_trial_api as pta
from app.services.db_maintenance_agent import DatabaseMaintenanceAgent


def _now():
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Shared in-memory "public_trial_leads" fake, reused across the merge /
# unsubscribe / follow-up tests below.
# ---------------------------------------------------------------------------

class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeTxnCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeLeadsConn:
    """Backs public_trial_leads + public_summon_usage for merge/unsubscribe/
    follow-up tests. Query dispatch is substring-based, mirroring the real
    SQL shapes in public_trial_gate.py / public_trial_conversion.py."""

    def __init__(self, leads: dict, summon: dict):
        self.leads = leads          # token_hash -> lead dict
        self.summon = summon        # device_uuid_hash -> summon dict
        self.mutate_calls: list = []

    def transaction(self):
        return _FakeTxnCtx()

    async def fetchrow(self, query, *args):
        if "SELECT email, expires_at, unsubscribed_at FROM public_trial_leads" in query:
            token_hash = args[0]
            lead = self.leads.get(token_hash)
            if not lead:
                return None
            return {
                "email": lead["email"],
                "expires_at": lead["expires_at"],
                "unsubscribed_at": lead["unsubscribed_at"],
            }
        if "SELECT device_uuid_hash FROM public_trial_leads" in query:
            token_hash, = args
            lead = self.leads.get(token_hash)
            if not lead or lead["expires_at"] <= _now():
                return None
            return {"device_uuid_hash": lead["device_uuid_hash"]}
        if "SELECT trial_history FROM public_summon_usage" in query:
            device_uuid_hash, = args
            row = self.summon.get(device_uuid_hash)
            if not row:
                return None
            return {"trial_history": row["trial_history"]}
        return None

    async def fetch(self, query, *args):
        if "public_trial_leads" in query and "follow_up_sent_at IS NULL" in query:
            now = _now()
            out = []
            for lead in self.leads.values():
                if lead["converted"]:
                    continue
                if lead["unsubscribed_at"] is not None:
                    continue
                if lead["follow_up_sent_at"] is not None:
                    continue
                if lead["email"] is None:
                    continue
                if lead["email_sent_at"] is None or lead["email_sent_at"] >= now - timedelta(days=3):
                    continue
                if lead["expires_at"] <= now:
                    continue
                out.append({"id": lead["id"], "email": lead["email"]})
            return out
        return []

    async def execute(self, query, *args):
        self.mutate_calls.append(query)
        if "UPDATE public_trial_leads SET unsubscribed_at = NOW()" in query:
            token_hash, = args
            lead = self.leads.get(token_hash)
            if lead and lead["unsubscribed_at"] is None:
                lead["unsubscribed_at"] = _now()
                return "UPDATE 1"
            return "UPDATE 0"
        if "UPDATE public_trial_leads SET converted = TRUE" in query:
            new_username, token_hash = args
            lead = self.leads.get(token_hash)
            if lead:
                lead["converted"] = True
                lead["converted_username"] = new_username
                lead["converted_at"] = _now()
            return "UPDATE 1"
        if "UPDATE public_trial_leads SET token_hash" in query and "follow_up_sent_at = NOW()" in query:
            new_token_hash, lead_id = args
            for lead in self.leads.values():
                if lead["id"] == lead_id and lead["follow_up_sent_at"] is None:
                    old_hash = lead["token_hash"]
                    lead["token_hash"] = new_token_hash
                    lead["follow_up_sent_at"] = _now()
                    self.leads[new_token_hash] = lead
                    if old_hash != new_token_hash:
                        self.leads.pop(old_hash, None)
                    return "UPDATE 1"
            return "UPDATE 0"
        if "INSERT INTO conversation_history" in query:
            return "INSERT 0 1"
        if "UPDATE public_summon_usage" in query and "SET converted = TRUE" in query:
            new_username, device_uuid_hash = args
            row = self.summon.get(device_uuid_hash)
            if row:
                row["converted"] = True
                row["converted_username"] = new_username
                row["trial_history"] = []
            return "UPDATE 1"
        return "UPDATE 0"


class _FakeLeadsPool:
    def __init__(self, conn: _FakeLeadsConn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


@pytest.fixture(autouse=True)
def _reset_module_state():
    ptg._DB_POOL = None
    yield
    ptg._DB_POOL = None


def _make_lead(token_hash, device_uuid_hash="duh_1", email="user@example.com",
                converted=False, unsubscribed_at=None, follow_up_sent_at=None,
                email_sent_at=None, expires_at=None, lead_id=1):
    return {
        "id": lead_id,
        "token_hash": token_hash,
        "device_uuid_hash": device_uuid_hash,
        "email": email,
        "converted": converted,
        "converted_username": None,
        "converted_at": None,
        "unsubscribed_at": unsubscribed_at,
        "follow_up_sent_at": follow_up_sent_at,
        "email_sent_at": email_sent_at or (_now() - timedelta(days=10)),
        "expires_at": expires_at or (_now() + timedelta(days=20)),
    }


# ---------------------------------------------------------------------------
# 1) GET /api/public-trial/unsubscribe is read-only (bot/scanner prefetch)
# ---------------------------------------------------------------------------

@pytest.fixture
def unsub_app():
    app = FastAPI()
    app.include_router(pta.router)
    return app, TestClient(app)


def test_unsubscribe_get_renders_confirm_page_and_never_mutates(unsub_app, monkeypatch):
    app, client = unsub_app
    pta._rate_hits.clear()

    calls = {"lookup": 0, "confirm": 0}

    async def _fake_lookup(token):
        calls["lookup"] += 1
        assert token == "raw-token-abc"
        return {"email": "someone@example.com", "expired": False, "already_unsubscribed": False}

    async def _fake_confirm(token):
        # A bot/scanner issuing a bare GET must NEVER reach this.
        calls["confirm"] += 1
        return True

    monkeypatch.setattr(pta, "lookup_unsubscribe_token", _fake_lookup)
    monkeypatch.setattr(pta, "confirm_unsubscribe", _fake_confirm)

    resp = client.get("/api/public-trial/unsubscribe", params={"token": "raw-token-abc"})

    assert resp.status_code == 200
    assert "Stop these emails?" in resp.text
    assert calls["lookup"] == 1
    assert calls["confirm"] == 0, "GET must never call the mutating confirm path"


def test_unsubscribe_get_masks_email_and_hides_raw_address(unsub_app, monkeypatch):
    app, client = unsub_app
    pta._rate_hits.clear()

    async def _fake_lookup(token):
        return {"email": "johnathan@example.com", "expired": False, "already_unsubscribed": False}

    monkeypatch.setattr(pta, "lookup_unsubscribe_token", _fake_lookup)

    resp = client.get("/api/public-trial/unsubscribe", params={"token": "tok"})
    assert "johnathan@example.com" not in resp.text
    assert "j*******n@example.com" in resp.text


def test_unsubscribe_get_invalid_token_returns_generic_page_no_enumeration(unsub_app, monkeypatch):
    app, client = unsub_app
    pta._rate_hits.clear()

    async def _fake_lookup(token):
        return None

    monkeypatch.setattr(pta, "lookup_unsubscribe_token", _fake_lookup)

    resp = client.get("/api/public-trial/unsubscribe", params={"token": "bogus"})
    assert resp.status_code == 404
    assert "no longer valid" in resp.text
    assert "@" not in resp.text


def test_unsubscribe_post_sets_unsubscribed_at(unsub_app, monkeypatch):
    app, client = unsub_app
    pta._rate_hits.clear()

    calls = {"confirm": 0}

    async def _fake_confirm(token):
        calls["confirm"] += 1
        assert token == "raw-token-abc"
        return True

    monkeypatch.setattr(pta, "confirm_unsubscribe", _fake_confirm)

    resp = client.post("/api/public-trial/unsubscribe", data={"token": "raw-token-abc"})
    assert resp.status_code == 200
    assert "You're unsubscribed" in resp.text
    assert calls["confirm"] == 1


# ---------------------------------------------------------------------------
# 2) Unsubscribe does NOT block the trial_token merge (real gate + conversion
#    functions, in-memory fake DB -- exercises the actual production code).
# ---------------------------------------------------------------------------

def test_confirm_unsubscribe_then_trial_token_merge_still_succeeds():
    token_hash = _hash("raw-token-xyz")
    leads = {token_hash: _make_lead(token_hash, device_uuid_hash="duh_merge")}
    summon = {
        "duh_merge": {
            "trial_history": [{"user": "hi", "assistant": "hello"}],
            "converted": False,
        }
    }
    conn = _FakeLeadsConn(leads, summon)
    pool = _FakeLeadsPool(conn)
    ptg.bootstrap(pool)

    # Step 1: user unsubscribes via the POST endpoint's underlying function.
    unsub_ok = asyncio.run(ptg.confirm_unsubscribe("raw-token-xyz"))
    assert unsub_ok is True
    assert leads[token_hash]["unsubscribed_at"] is not None

    # Step 2: they later register using the SAME trial_token (original email
    # or the follow-up they already had) -- merge must still succeed.
    result = asyncio.run(
        ptc.try_merge_trial_data(pool, device_fingerprint=None,
                                  trial_token="raw-token-xyz", new_username="newuser1")
    )
    assert result["merged"] is True
    assert result["via"] == "trial_token"
    assert leads[token_hash]["converted"] is True
    assert leads[token_hash]["converted_username"] == "newuser1"
    assert summon["duh_merge"]["converted"] is True
    assert summon["duh_merge"]["trial_history"] == []


def test_merge_lookup_query_does_not_filter_on_unsubscribed_at():
    """Static guard: the SQL powering the trial_token match must not gate on
    unsubscribed_at in its WHERE clause (plan section 452)."""
    import inspect
    source = inspect.getsource(ptc.try_merge_trial_data)
    start = source.index("SELECT device_uuid_hash FROM public_trial_leads")
    end = source.index(")", start)
    where_clause = source[start:end]
    assert "unsubscribed_at" not in where_clause
    assert "expires_at" in where_clause


# ---------------------------------------------------------------------------
# 3) Follow-up cycle: at most one send per lead, correctly gated.
# ---------------------------------------------------------------------------

def test_followup_cycle_sends_only_eligible_leads(monkeypatch):
    eligible_hash = _hash("eligible-token")
    already_sent_hash = _hash("already-sent-token")
    unsubscribed_hash = _hash("unsub-token")
    too_recent_hash = _hash("too-recent-token")
    expired_hash = _hash("expired-token")
    no_email_hash = _hash("no-email-token")
    converted_hash = _hash("converted-token")

    leads = {
        eligible_hash: _make_lead(eligible_hash, lead_id=1),
        already_sent_hash: _make_lead(already_sent_hash, lead_id=2,
                                       follow_up_sent_at=_now() - timedelta(days=1)),
        unsubscribed_hash: _make_lead(unsubscribed_hash, lead_id=3,
                                       unsubscribed_at=_now() - timedelta(days=1)),
        too_recent_hash: _make_lead(too_recent_hash, lead_id=4,
                                     email_sent_at=_now() - timedelta(hours=1)),
        expired_hash: _make_lead(expired_hash, lead_id=5,
                                  expires_at=_now() - timedelta(days=1)),
        no_email_hash: _make_lead(no_email_hash, lead_id=6, email=None),
        converted_hash: _make_lead(converted_hash, lead_id=7, converted=True),
    }
    conn = _FakeLeadsConn(leads, {})
    pool = _FakeLeadsPool(conn)
    ptg.bootstrap(pool)

    sent_to = []

    async def _fake_send(to_email, signup_url, unsubscribe_url):
        sent_to.append(to_email)
        return True

    monkeypatch.setattr(ptg, "_send_trial_followup_email", _fake_send)

    sent_count = asyncio.run(ptg.run_trial_followup_cycle())

    assert sent_count == 1
    assert sent_to == ["user@example.com"]
    # The eligible lead's row now has follow_up_sent_at set (found under its
    # rotated token_hash since _upsert-style rotation reuses the same row).
    updated = [l for l in leads.values() if l["id"] == 1][0]
    assert updated["follow_up_sent_at"] is not None


def test_followup_cycle_never_sends_twice_for_same_lead(monkeypatch):
    token_hash = _hash("solo-token")
    leads = {token_hash: _make_lead(token_hash, lead_id=42)}
    conn = _FakeLeadsConn(leads, {})
    pool = _FakeLeadsPool(conn)
    ptg.bootstrap(pool)

    async def _fake_send(to_email, signup_url, unsubscribe_url):
        return True

    monkeypatch.setattr(ptg, "_send_trial_followup_email", _fake_send)

    first = asyncio.run(ptg.run_trial_followup_cycle())
    second = asyncio.run(ptg.run_trial_followup_cycle())

    assert first == 1
    assert second == 0


def test_followup_cycle_does_not_commit_rotation_on_send_failure(monkeypatch):
    token_hash = _hash("fail-send-token")
    leads = {token_hash: _make_lead(token_hash, lead_id=99)}
    conn = _FakeLeadsConn(leads, {})
    pool = _FakeLeadsPool(conn)
    ptg.bootstrap(pool)

    async def _fake_send_fail(to_email, signup_url, unsubscribe_url):
        return False

    monkeypatch.setattr(ptg, "_send_trial_followup_email", _fake_send_fail)

    sent_count = asyncio.run(ptg.run_trial_followup_cycle())

    assert sent_count == 0
    assert leads[token_hash]["follow_up_sent_at"] is None
    # Original token must still be valid -- a SendGrid outage never
    # invalidates the link the user might still click from the first email.
    assert token_hash in leads


# ---------------------------------------------------------------------------
# 4) db_maintenance_agent retention purges.
# ---------------------------------------------------------------------------

class _FakeMaintConn:
    """Records every executed query/args and returns a scripted 'UPDATE n'
    tag so DatabaseMaintenanceAgent's int(result.split()[-1]) parsing works."""

    def __init__(self, tag_by_substring: dict):
        self.tag_by_substring = tag_by_substring
        self.calls: list = []

    async def execute(self, query, *args):
        self.calls.append((query, args))
        for substring, tag in self.tag_by_substring.items():
            if substring in query:
                return tag
        return "UPDATE 0"

    async def fetchrow(self, query, *args):
        return None

    async def fetch(self, query, *args):
        return []


class _FakeMaintPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


def test_purge_trial_history_targets_only_unconverted_stale_rows():
    conn = _FakeMaintConn({"UPDATE public_summon_usage": "UPDATE 7"})
    agent = DatabaseMaintenanceAgent(_FakeMaintPool(conn))

    result = asyncio.run(agent._purge_trial_history())

    assert result == 7
    query, args = conn.calls[0]
    assert "SET trial_history = '[]'::jsonb" in query
    assert "converted = FALSE" in query
    assert "trial_started_at < NOW() - INTERVAL '30 days'" in query


def test_purge_flagged_turn_text_nulls_text_only():
    conn = _FakeMaintConn({"UPDATE public_trial_flagged_turns": "UPDATE 3"})
    agent = DatabaseMaintenanceAgent(_FakeMaintPool(conn))

    result = asyncio.run(agent._purge_flagged_turn_text())

    assert result == 3
    query, _ = conn.calls[0]
    assert "SET text = NULL" in query
    assert "INTERVAL '30 days'" in query
    assert "fp_hash" not in query  # only `text` is touched, everything else survives


def test_purge_trial_lead_emails_ignores_converted_status():
    conn = _FakeMaintConn({"UPDATE public_trial_leads": "UPDATE 5"})
    agent = DatabaseMaintenanceAgent(_FakeMaintPool(conn))

    result = asyncio.run(agent._purge_trial_lead_emails())

    assert result == 5
    query, _ = conn.calls[0]
    assert "SET email = NULL" in query
    assert "INTERVAL '45 days'" in query
    # Plan requires this purge regardless of converted status -- the query
    # must not add a `converted` filter.
    assert "converted" not in query


def test_send_trial_followups_delegates_to_public_trial_gate(monkeypatch):
    conn = _FakeMaintConn({})
    agent = DatabaseMaintenanceAgent(_FakeMaintPool(conn))

    calls = {"n": 0}

    async def _fake_cycle():
        calls["n"] += 1
        return 2

    monkeypatch.setattr(ptg, "run_trial_followup_cycle", _fake_cycle)

    result = asyncio.run(agent._send_trial_followups())

    assert result == 2
    assert calls["n"] == 1


def test_send_trial_followups_never_raises_on_failure(monkeypatch):
    conn = _FakeMaintConn({})
    agent = DatabaseMaintenanceAgent(_FakeMaintPool(conn))

    async def _boom():
        raise RuntimeError("sendgrid down")

    monkeypatch.setattr(ptg, "run_trial_followup_cycle", _boom)

    result = asyncio.run(agent._send_trial_followups())
    assert result == 0


def test_cycle_invokes_all_four_new_trial_retention_steps(monkeypatch):
    """Wiring regression guard: `_cycle` must call all four new methods
    every run, not just on first deploy."""
    conn = _FakeMaintConn({})
    agent = DatabaseMaintenanceAgent(_FakeMaintPool(conn))

    called = {"history": 0, "flagged": 0, "emails": 0, "followups": 0}

    def _mk(name):
        async def _fn():
            called[name] += 1
            return 0
        return _fn

    agent._purge_trial_history = _mk("history")
    agent._purge_flagged_turn_text = _mk("flagged")
    agent._purge_trial_lead_emails = _mk("emails")
    agent._send_trial_followups = _mk("followups")

    asyncio.run(agent._cycle())

    assert called == {"history": 1, "flagged": 1, "emails": 1, "followups": 1}
