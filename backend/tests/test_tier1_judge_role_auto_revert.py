"""
Offline tests for the Entry 12 flag-decision mechanism (no app package
import — macOS numpy): six_quotient_judge_role state + auto-revert-on-
veto-miss, wired into persist_kappa_evidence.

TRUST_LEDGER.md Entry 12 (CEO decision, 2026-08-02): grok-judge-v5 is
certified ONLY as a safety-veto screener (fresh held-out kappa=0.189 fails
quality-scorer certification; safety veto is 0-for-49 across both
held-out runs). Two conditions: (1) any future veto miss auto-suspends
the screener role, (2) every judge output carries an uncertified-quality
disclaimer.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SVC = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "tier1_gold_evidence.py"
)


def _load_mod():
    spec = importlib.util.spec_from_file_location("tier1_gold_evidence_iso2", _SVC)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ev():
    return _load_mod()


class _FakeConn:
    """Minimal asyncpg-like fake: tracks fetchrow/execute calls, no real DB."""

    def __init__(self, role_row=None):
        self._role_row = dict(role_row) if role_row else None
        self.executed = []
        self.next_insert_id = 42

    async def fetchrow(self, query, *args):
        q = " ".join(query.split())
        if "INSERT INTO six_quotient_judge_kappa_evidence" in q:
            return {"id": self.next_insert_id}
        if "FROM six_quotient_judge_role" in q:
            return dict(self._role_row) if self._role_row else None
        raise AssertionError(f"unexpected fetchrow: {q[:60]}")

    async def execute(self, query, *args):
        self.executed.append((" ".join(query.split()), args))
        return "UPDATE 1"


# --- get_judge_role -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_judge_role_fails_closed_when_no_row(ev):
    conn = _FakeConn(role_row=None)
    role = await ev.get_judge_role(conn, "unknown-judge")
    assert role["role"] == "unrated"
    assert role["quality_certified"] is False
    assert role["veto_screener_certified"] is False


@pytest.mark.asyncio
async def test_get_judge_role_reports_seeded_screener_state(ev):
    conn = _FakeConn(
        role_row={
            "judge_id": "grok-judge-v5",
            "role": "safety_veto_screener_only",
            "quality_certified": False,
            "veto_screener_certified": True,
            "veto_check_total": 49,
            "veto_miss_total": 0,
            "suspended_at": None,
            "suspended_reason": None,
        }
    )
    role = await ev.get_judge_role(conn, "grok-judge-v5")
    assert role["role"] == "safety_veto_screener_only"
    assert role["quality_certified"] is False
    assert role["veto_screener_certified"] is True


# --- apply_veto_auto_revert ----------------------------------------------


@pytest.mark.asyncio
async def test_auto_revert_suspends_screener_on_veto_miss(ev):
    conn = _FakeConn(role_row={"role": "safety_veto_screener_only"})
    result = await ev.apply_veto_auto_revert(
        conn,
        judge_id="grok-judge-v5",
        safety_miss_count=1,
        evidence_id=10,
        miss_ids=["AQ-2"],
    )
    assert result["reverted"] is True
    assert "AQ-2" in result["reason"]
    # The UPDATE must set role='suspended'
    updates = [q for q, _ in conn.executed if "SET role = 'suspended'" in q]
    assert len(updates) == 1


@pytest.mark.asyncio
async def test_auto_revert_no_op_on_zero_misses(ev):
    conn = _FakeConn(role_row={"role": "safety_veto_screener_only"})
    result = await ev.apply_veto_auto_revert(
        conn,
        judge_id="grok-judge-v5",
        safety_miss_count=0,
        evidence_id=11,
        miss_ids=[],
    )
    assert result["reverted"] is False
    # Still tallies the check (visibility), but does not suspend
    assert len(conn.executed) == 1
    assert "role = 'suspended'" not in conn.executed[0][0]


@pytest.mark.asyncio
async def test_auto_revert_noop_when_no_role_row(ev):
    conn = _FakeConn(role_row=None)
    result = await ev.apply_veto_auto_revert(
        conn,
        judge_id="never-seen-judge",
        safety_miss_count=1,
        evidence_id=12,
        miss_ids=["X"],
    )
    assert result["reverted"] is False
    assert result["reason"] == "no_role_row"
    assert conn.executed == []


@pytest.mark.asyncio
async def test_auto_revert_does_not_re_suspend_already_suspended_judge(ev):
    # A judge already suspended is not the concern of this check (that's a
    # human-review reset path) — no further state churn on repeat misses.
    conn = _FakeConn(role_row={"role": "suspended"})
    result = await ev.apply_veto_auto_revert(
        conn,
        judge_id="grok-judge-v5",
        safety_miss_count=1,
        evidence_id=13,
        miss_ids=["Y"],
    )
    assert result["reverted"] is False
    assert conn.executed == []


@pytest.mark.asyncio
async def test_auto_revert_tallies_quality_scorer_role_without_suspending_on_zero(ev):
    conn = _FakeConn(role_row={"role": "quality_scorer"})
    result = await ev.apply_veto_auto_revert(
        conn,
        judge_id="some-certified-judge",
        safety_miss_count=0,
        evidence_id=14,
    )
    assert result["reverted"] is False
    assert len(conn.executed) == 1


# --- persist_kappa_evidence integration (structural, via fake conn) -----


@pytest.mark.asyncio
async def test_persist_kappa_evidence_invokes_auto_revert_on_miss(ev):
    conn = _FakeConn(role_row={"role": "safety_veto_screener_only"})
    eid = await ev.persist_kappa_evidence(
        conn,
        judge_id="grok-judge-v5",
        aggregate_kappa=0.189,
        per_dimension={"primary": 0.21, "accuracy": 0.15, "naturalness": 0.21},
        n_items=40,
        safety_veto_ok=False,
        safety_miss_count=1,
        safety_miss_ids=["AQ-9"],
        gold_locked=False,
    )
    assert eid == 42
    suspend_updates = [q for q, _ in conn.executed if "SET role = 'suspended'" in q]
    assert len(suspend_updates) == 1


@pytest.mark.asyncio
async def test_persist_kappa_evidence_survives_role_lookup_failure(ev):
    class _BrokenRoleConn(_FakeConn):
        async def fetchrow(self, query, *args):
            if "FROM six_quotient_judge_role" in " ".join(query.split()):
                raise RuntimeError("db hiccup")
            return await super().fetchrow(query, *args)

    conn = _BrokenRoleConn(role_row=None)
    # Must not raise -- the evidence row is the source of truth and must
    # persist even if the role-table side-check errors.
    eid = await ev.persist_kappa_evidence(
        conn,
        judge_id="grok-judge-v5",
        aggregate_kappa=0.7,
        per_dimension={"primary": 0.7, "accuracy": 0.7, "naturalness": 0.7},
        n_items=50,
        safety_veto_ok=True,
        safety_miss_count=0,
        gold_locked=True,
    )
    assert eid == 42


def test_valid_roles_constant_matches_migration(ev):
    mig = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "319_six_quotient_judge_role.sql"
    )
    assert mig.is_file()
    sql = mig.read_text(encoding="utf-8")
    for role in ev._VALID_JUDGE_ROLES:
        assert f"'{role}'" in sql
    assert "grok-judge-v5" in sql
    assert "safety_veto_screener_only" in sql
