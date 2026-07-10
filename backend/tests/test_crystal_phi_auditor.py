"""Standing recurring auditor: crystal_phi_auditor.py.

Background (2026-07-09 incident, part 4): crystal_phi_guard.py closes the
WRITE path (test_crystal_phi_guard.py) and the recall-side allowlist closes
the READ path for scope='global' specifically
(test_admin_only_scope_isolation.py). Neither protects against a name being
added to the roster AFTER a crystal was already written, a future write
path this project doesn't yet guard, or a crystal that orphans into the
ownerless (user_id IS NULL) pool under a scope value other than 'global'.

This suite covers CrystalPhiAuditor (backend/app/services/crystal_phi_auditor.py):
a standing background sweep of the entire ownerless crystal pool against the
live client-name roster, on a recurring schedule, independent of any single
write site -- "audit the failure class continuously" instead of "patch
scopes one at a time" per the incident follow-up.

See ci-gate-before-push.mdc for the offline-only test contract -- these
tests use an in-memory fake asyncpg pool, no real Postgres connection.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import crystal_phi_guard as guard_mod
from app.services.crystal_phi_auditor import CrystalPhiAuditor

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_APP = _REPO_ROOT / "backend" / "app"


# ── Fake asyncpg pool/connection harness ──

class _FakeConn:
    def __init__(self, roster_rows=None, crystal_rows=None):
        self.roster_rows = roster_rows or []
        self.crystal_rows = crystal_rows or []
        self.fetch_calls: list[str] = []
        self.executed: list[tuple] = []

    async def fetch(self, query, *args):
        self.fetch_calls.append(query)
        if "profile_data->>'name'" in query:
            return self.roster_rows
        return self.crystal_rows

    async def fetchrow(self, query, *args):
        return None

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return None


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


@pytest.fixture(autouse=True)
def _reset_roster_cache():
    """CrystalPhiAuditor calls refresh_client_name_roster(force=True) every
    cycle, which mutates the module-global cache in crystal_phi_guard. Reset
    it around every test so tests can't leak roster state into each other."""
    original = guard_mod._ROSTER_CACHE
    original_ts = guard_mod._ROSTER_LAST_REFRESH
    guard_mod._ROSTER_CACHE = set()
    guard_mod._ROSTER_LAST_REFRESH = 0.0
    yield
    guard_mod._ROSTER_CACHE = original
    guard_mod._ROSTER_LAST_REFRESH = original_ts


def _row(id_, text, scope, origin_surface=None, domain="general"):
    return {
        "id": id_,
        "crystal_text": text,
        "scope": scope,
        "origin_surface": origin_surface,
        "domain": domain,
    }


# ── _cycle: the core sweep ──

def test_cycle_quarantines_crystal_containing_live_client_name():
    conn = _FakeConn(
        roster_rows=[{"name": "John D."}],
        crystal_rows=[
            _row(181990, "[Session Insight] ... John D. ... progress this week", "archived"),
            _row(999999, "Generic aggregate research finding, no names.", "global"),
        ],
    )
    pool = _FakePool(conn)
    auditor = CrystalPhiAuditor(pool, interval_seconds=99999)

    asyncio.run(auditor._cycle())

    update_calls = [c for c in conn.executed if "UPDATE nate_intelligence_crystals" in c[0]]
    assert len(update_calls) == 1, "only the name-matching crystal should be quarantined"
    assert update_calls[0][1] == (181990,)

    summary = auditor.last_cycle_summary
    assert summary["scanned"] == 2
    assert summary["name_matches"] == 1
    assert summary["quarantined"] == 1


def test_cycle_writes_immutable_audit_log_entry_without_phi_text():
    conn = _FakeConn(
        roster_rows=[{"name": "John D."}],
        crystal_rows=[_row(355292, "John D., I sense curiosity in your words.", "global",
                           origin_surface="unknown", domain="clinical")],
    )
    pool = _FakePool(conn)
    auditor = CrystalPhiAuditor(pool, interval_seconds=99999)

    asyncio.run(auditor._cycle())

    audit_calls = [c for c in conn.executed if "INSERT INTO audit_log" in c[0]]
    assert len(audit_calls) == 1
    query, args = audit_calls[0]
    assert "SECURITY" in query
    # args order: admin_id placeholder is a literal NULL in the SQL, not a
    # bound param -- the two bound params are target_name and description.
    target_name, description = args
    assert target_name == "355292"
    # The description must identify the crystal by id/scope/metadata only --
    # never repeat the client's name or any crystal_text back out into a
    # log row (that would just relocate the PHI exposure).
    assert "John D." not in description
    assert "355292" in description


def test_cycle_flags_non_global_orphan_scope_without_quarantining():
    # Ownerless, not global-pool-eligible, no name match: the structural
    # "orphan" pattern found in the 2026-07-09 audit (a scope='user:<id>'
    # crystal with user_id IS NULL). Cannot leak via the recall allowlist,
    # so it is reported as scope-hygiene debt, not auto-archived.
    conn = _FakeConn(
        roster_rows=[{"name": "John D."}],
        crystal_rows=[_row(4242, "Some orphaned personal disclosure text.", "user:CLIENT_X_ID")],
    )
    pool = _FakePool(conn)
    auditor = CrystalPhiAuditor(pool, interval_seconds=99999)

    asyncio.run(auditor._cycle())

    update_calls = [c for c in conn.executed if "UPDATE nate_intelligence_crystals" in c[0]]
    assert len(update_calls) == 0
    assert auditor.last_cycle_summary["scope_drift_orphans"] == 1
    assert auditor.last_cycle_summary["quarantined"] == 0


def test_cycle_matches_regardless_of_current_scope_value():
    # The auditor must not special-case scope=='global' the way the
    # write-time guard does -- it sweeps ALL ownerless rows regardless of
    # current scope, because the whole point is catching crystals that
    # slipped through under any scope (admin_only, a stale/legacy value,
    # etc.), not just the one the write-time guard already covers.
    conn = _FakeConn(
        roster_rows=[{"name": "Lisa West"}],
        crystal_rows=[_row(500, "Lisa West called about her session.", "admin_only")],
    )
    pool = _FakePool(conn)
    auditor = CrystalPhiAuditor(pool, interval_seconds=99999)

    asyncio.run(auditor._cycle())

    update_calls = [c for c in conn.executed if "UPDATE nate_intelligence_crystals" in c[0]]
    assert len(update_calls) == 1
    assert update_calls[0][1] == (500,)


def test_cycle_scans_already_archived_are_excluded_from_query():
    # Static check on the fetch query itself: already-archived rows should
    # not even be pulled back for re-scanning every cycle (they're already
    # quarantined; re-scanning them forever wastes the sweep budget as the
    # table grows).
    conn = _FakeConn(roster_rows=[], crystal_rows=[])
    pool = _FakePool(conn)
    auditor = CrystalPhiAuditor(pool, interval_seconds=99999)

    asyncio.run(auditor._cycle())

    crystal_fetch_queries = [q for q in conn.fetch_calls if "nate_intelligence_crystals" in q]
    assert len(crystal_fetch_queries) == 1
    assert "user_id IS NULL" in crystal_fetch_queries[0]
    assert "archived" in crystal_fetch_queries[0]


def test_cycle_is_noop_and_does_not_raise_when_db_pool_missing():
    auditor = CrystalPhiAuditor(None, interval_seconds=99999)
    asyncio.run(auditor._cycle())  # must not raise
    assert auditor.last_cycle_summary == {}


def test_cycle_with_no_matches_quarantines_nothing():
    conn = _FakeConn(
        roster_rows=[{"name": "John D."}],
        crystal_rows=[_row(1, "De-identified aggregate: 30 sessions, avg C_emo=0.25.", "global")],
    )
    pool = _FakePool(conn)
    auditor = CrystalPhiAuditor(pool, interval_seconds=99999)

    asyncio.run(auditor._cycle())

    assert auditor.last_cycle_summary["name_matches"] == 0
    assert auditor.last_cycle_summary["quarantined"] == 0
    assert not any("UPDATE nate_intelligence_crystals" in c[0] for c in conn.executed)


# ── Alerting: must never leak PHI into the alert channel, must degrade safely ──

def test_alert_is_skipped_gracefully_without_notification_system():
    auditor = CrystalPhiAuditor(_FakePool(_FakeConn()), interval_seconds=99999,
                                 notification_system=None, admin_email="")
    # Must not raise even though there's no notification channel configured.
    asyncio.run(auditor._alert([{"id": 1, "prior_scope": "global",
                                  "origin_surface": None, "domain": "general"}], {}))


def test_alert_email_body_never_includes_crystal_text_or_client_name():
    calls = []

    class _FakeNotify:
        async def _send_email(self, to, subject, body, notification_type=""):
            calls.append((to, subject, body))

    auditor = CrystalPhiAuditor(_FakePool(_FakeConn()), interval_seconds=99999,
                                 notification_system=_FakeNotify(),
                                 admin_email="admin@example.com")
    asyncio.run(auditor._alert(
        [{"id": 181990, "prior_scope": "archived", "origin_surface": None, "domain": "clinical"}],
        {"quarantined": 1},
    ))

    assert len(calls) == 1
    _, _, body = calls[0]
    assert "181990" in body
    assert "John D." not in body  # never echo a name into the alert body


# ── Quarantine SQL: archive, never delete ──

def test_quarantine_sql_uses_update_never_delete():
    src = (_BACKEND_APP / "services" / "crystal_phi_auditor.py").read_text()
    fn_idx = src.index("async def _quarantine(")
    next_fn_idx = src.index("\n    async def ", fn_idx + 10)
    body = src[fn_idx:next_fn_idx]
    assert "UPDATE nate_intelligence_crystals" in body
    assert "SET scope = 'archived'" in body
    assert "DELETE" not in body, (
        "Quarantine must archive, never delete -- "
        "crystal-intelligence-integrity.mdc: 'Never DELETE FROM "
        "nate_intelligence_crystals -- always archive.'"
    )


# ── Static wiring checks: registered in main.py + digest coverage ──

def test_registered_in_main_service_checks_and_shutdown():
    src = (_BACKEND_APP / "main.py").read_text()
    assert '"crystal_phi_auditor", _crystal_phi_auditor is not None' in src, (
        "CrystalPhiAuditor must be counted in the _service_checks health "
        "denominator (service-health-49-49.mdc)."
    )
    assert "app.state.crystal_phi_auditor = _crystal_phi_auditor" in src
    assert "await _crystal_phi_auditor.start()" in src
    shutdown_idx = src.index('getattr(app.state, "crystal_phi_auditor", None)')
    shutdown_section = src[shutdown_idx:shutdown_idx + 300]
    assert ".stop()" in shutdown_section, (
        "CrystalPhiAuditor must be stopped in the lifespan shutdown block "
        "to avoid an orphaned asyncio task (self-learning-agent-governance.mdc rule 7)."
    )


def test_registered_in_agent_status_digest():
    src = (_BACKEND_APP / "services" / "agent_status_digest.py").read_text()
    assert 'getattr(self.app, "crystal_phi_auditor", None)' in src, (
        "Every agent registered on app.state must appear in "
        "agent_status_digest.py per agent-digest-coverage.mdc, or it is "
        "invisible to the 3x-daily system health email."
    )
    assert '"crystal_phi_audit_cycle"' in src
