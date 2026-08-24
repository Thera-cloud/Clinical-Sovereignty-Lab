"""Slice B — cohort-aware retention dry-run tests.

Exercises ``DatabaseMaintenanceAgent._retention_dry_run_report`` with
an in-memory fake asyncpg pool. Verifies:

- Dry-run flag wins over enforcement (safety-first priority).
- Cohort users get the strict 30-day window regardless of global policy.
- Non-cohort users use the global policy when set, are skipped when
  the policy is "forever".
- Pre-414 schema (no ``users.program_id`` column) degrades gracefully
  to a non-cohort-only count.
- The dry-run path issues zero writes (no DELETE, no INSERT).
- The regular enforcement path (dry-run OFF, enforcement ON) is not
  entered by the dry-run branch — proved by the write-recorder.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from typing import Any


# --------------------------------------------------------------------------- #
# Fake asyncpg pool                                                            #
# --------------------------------------------------------------------------- #


class _FakeRow(dict):
    """asyncpg Records support both mapping and index access; the agent
    uses mapping style (``row["c"]``) so a plain dict is sufficient."""


class _FakeTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, state: dict):
        self.state = state

    def transaction(self):
        return _FakeTxn()

    def _stale_rows(self, sql_norm: str, args):
        days = int(args[0])
        for table in ("conversation_history", "nevedal_metrics"):
            if f"FROM {table}" not in sql_norm:
                continue
            rows = self.state["rows"][table]
            if "NOT (" in sql_norm:
                ids = set(args[1])
                matched = [
                    r for r in rows
                    if r["user_id"] not in ids and r["age_days"] > days
                ]
            elif "user_id = ANY" in sql_norm:
                ids = set(args[1])
                matched = [
                    r for r in rows
                    if r["user_id"] in ids and r["age_days"] > days
                ]
            else:
                matched = [r for r in rows if r["age_days"] > days]
            return [
                _FakeRow(
                    row_id=f"{table}:{r['user_id']}:{r['age_days']}",
                    user_id=r["user_id"],
                )
                for r in matched
            ]
        return None

    async def fetch(self, sql: str, *args):
        self.state["queries"].append(("fetch", sql, args))
        sql_norm = " ".join(sql.split())
        if "FROM users WHERE program_id" in sql_norm:
            if self.state.get("no_program_id_column"):
                raise Exception('column "program_id" does not exist')
            program_id = args[0]
            return [
                _FakeRow(
                    username=u["username"],
                    hardware_id=u["hardware_id"],
                    uid=u["uid"],
                )
                for u in self.state["users"]
                if u["program_id"] == program_id
            ]
        if "AS row_id" in sql_norm:
            selected = self._stale_rows(sql_norm, args)
            if selected is not None:
                return selected
        raise AssertionError(f"unexpected fetch: {sql_norm[:80]}")

    async def fetchrow(self, sql: str, *args):
        self.state["queries"].append(("fetchrow", sql, args))
        sql_norm = " ".join(sql.split())
        # COUNT queries: parse table, cohort-in vs cohort-not vs global.
        for table in ("conversation_history", "nevedal_metrics"):
            if f"FROM {table}" in sql_norm and "SELECT COUNT(*)" in sql_norm:
                days = int(args[0])
                cutoff_days = days  # older than N days == age > N days
                if "user_id = ANY" in sql_norm and "NOT" not in sql_norm:
                    ids = set(args[1])
                    c = sum(
                        1
                        for r in self.state["rows"][table]
                        if r["user_id"] in ids and r["age_days"] > cutoff_days
                    )
                    return _FakeRow(c=c)
                if "NOT (" in sql_norm and "user_id = ANY" in sql_norm:
                    ids = set(args[1])
                    c = sum(
                        1
                        for r in self.state["rows"][table]
                        if r["user_id"] not in ids and r["age_days"] > cutoff_days
                    )
                    return _FakeRow(c=c)
                # global-only (no cohort ids)
                c = sum(
                    1
                    for r in self.state["rows"][table]
                    if r["age_days"] > cutoff_days
                )
                return _FakeRow(c=c)
        raise AssertionError(f"unexpected fetchrow: {sql_norm[:80]}")

    async def execute(self, sql: str, *args):
        self.state["writes"].append(("execute", sql, args))
        if not self.state.get("allow_writes"):
            raise AssertionError(
                f"dry-run path must not execute writes: {sql[:80]}"
            )
        return "DELETE 0"

    async def executemany(self, sql: str, seq):
        self.state["writes"].append(("executemany", sql, seq))
        if not self.state.get("allow_writes"):
            raise AssertionError(
                f"dry-run path must not executemany: {sql[:80]}"
            )
        return "INSERT 0"


class _FakePoolCtx:
    def __init__(self, conn: _FakeConn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, state: dict):
        self.state = state

    def acquire(self):
        return _FakePoolCtx(_FakeConn(self.state))


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _reload_retention_policy(env: dict):
    for flag in ("ENABLE_RETENTION_ENFORCEMENT", "ENABLE_RETENTION_DRYRUN"):
        if flag not in env:
            os.environ.pop(flag, None)
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    if "app.services.retention_policy" in sys.modules:
        del sys.modules["app.services.retention_policy"]
    import app.services.retention_policy as mod
    return importlib.reload(mod)


def _make_agent(state: dict):
    from app.services.db_maintenance_agent import DatabaseMaintenanceAgent
    pool = _FakePool(state)
    return DatabaseMaintenanceAgent(pool)


def _seed_state():
    """Seed a small dataset.

    - user 'bee1' is in the bee_hiv_plus cohort
    - user 'joe' is not in any cohort
    - conversation_history rows: 2 bee1 rows (35d, 5d), 2 joe rows (400d, 30d)
    - nevedal_metrics rows: 1 bee1 (40d), 1 joe (10d)
    """
    return {
        "users": [
            {
                "program_id": "bee_hiv_plus",
                "username": "bee1",
                "hardware_id": "HW_BEE1",
                "uid": "11111111-1111-1111-1111-111111111111",
            },
            {
                "program_id": None,
                "username": "joe",
                "hardware_id": "HW_JOE",
                "uid": "22222222-2222-2222-2222-222222222222",
            },
        ],
        "rows": {
            "conversation_history": [
                {"user_id": "bee1", "age_days": 35},
                {"user_id": "bee1", "age_days": 5},
                {"user_id": "joe", "age_days": 400},
                {"user_id": "joe", "age_days": 30},
            ],
            "nevedal_metrics": [
                {"user_id": "HW_BEE1", "age_days": 40},
                {"user_id": "HW_JOE", "age_days": 10},
            ],
        },
        "queries": [],
        "writes": [],
        "no_program_id_column": False,
    }


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


def test_dryrun_wins_over_enforcement(tmp_path):
    """Both flags on → dry-run branch, zero writes."""
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_ENFORCEMENT": "true",
            "ENABLE_RETENTION_DRYRUN": "true",
        }
    )
    state = _seed_state()
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert result.get("dryrun") is True
    assert result["deleted"] == 0
    assert state["writes"] == []


def test_dryrun_off_returns_disabled_when_enforcement_off(tmp_path):
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_ENFORCEMENT": None,
            "ENABLE_RETENTION_DRYRUN": None,
        }
    )
    state = _seed_state()
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert "disabled" in result["summary"]
    assert result["deleted"] == 0
    assert state["writes"] == []


def test_cohort_uses_30d_when_global_is_forever(tmp_path):
    """Global forever → non-cohort would_delete == 0; cohort gets 30d.

    Cohort user 'bee1' has one row aged 35d in conversation_history
    (crosses 30d) and one row aged 40d in nevedal_metrics (crosses 30d).
    """
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_DRYRUN": "true",
        }
    )
    state = _seed_state()
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert result["dryrun"] is True
    assert result["policy_global_days"] is None
    assert result["policy_strict_days"] == 30

    ch = result["per_table"]["conversation_history"]
    assert ch["cohort_would"] == 1  # bee1 35d
    assert ch["noncohort_would"] == 0  # global=forever
    assert ch["would_delete"] == 1

    nm = result["per_table"]["nevedal_metrics"]
    assert nm["cohort_would"] == 1  # HW_BEE1 40d
    assert nm["noncohort_would"] == 0
    assert nm["would_delete"] == 1

    assert result["would_delete"] == 2
    assert state["writes"] == []


def test_cohort_and_noncohort_when_global_1year(tmp_path):
    """Global 1yr (365d) + cohort 30d. Non-cohort rows only count when
    they exceed the global window."""
    import json
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "1_year"})
    )
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_DRYRUN": "true",
        }
    )
    state = _seed_state()
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert result["policy_global_days"] == 365
    ch = result["per_table"]["conversation_history"]
    # cohort: bee1 35d > 30d → 1
    assert ch["cohort_would"] == 1
    # non-cohort: joe 400d > 365d → 1; joe 30d not stale → 0
    assert ch["noncohort_would"] == 1
    assert ch["would_delete"] == 2
    nm = result["per_table"]["nevedal_metrics"]
    # cohort: HW_BEE1 40d > 30d → 1
    assert nm["cohort_would"] == 1
    # non-cohort: HW_JOE 10d < 365d → 0
    assert nm["noncohort_would"] == 0
    assert result["would_delete"] == 3
    assert state["writes"] == []


def test_cohort_takes_min_when_global_shorter(tmp_path):
    """If admin set 30d globally, cohort still uses 30d (min(30,30)=30)."""
    import json
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "30_days"})
    )
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_DRYRUN": "true",
        }
    )
    state = _seed_state()
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert result["policy_global_days"] == 30
    ch = result["per_table"]["conversation_history"]
    # bee1 35d > 30d → cohort=1
    # joe 400d > 30d, joe 30d NOT > 30d → noncohort=1
    assert ch["cohort_would"] == 1
    assert ch["noncohort_would"] == 1
    assert state["writes"] == []


def test_pre_414_schema_degrades_to_noncohort_only(tmp_path):
    """When the users.program_id column doesn't exist yet, cohort
    identification fails softly and we fall back to non-cohort-only
    (global) counts. Never crashes."""
    import json
    (tmp_path / "admin_settings.json").write_text(
        json.dumps({"memory_retention_policy": "1_year"})
    )
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_DRYRUN": "true",
        }
    )
    state = _seed_state()
    state["no_program_id_column"] = True
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert result["dryrun"] is True
    assert result["cohort_id_count"] == 0
    ch = result["per_table"]["conversation_history"]
    # cohort: 0 (no cohort ids resolved)
    assert ch["cohort_would"] == 0
    # non-cohort: all rows evaluated against global 365d → only joe 400d qualifies
    assert ch["noncohort_would"] == 1
    assert ch["would_delete"] == 1
    assert state["writes"] == []


def test_dryrun_report_shape(tmp_path):
    """Contract: consumers rely on these keys."""
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_DRYRUN": "true",
        }
    )
    state = _seed_state()
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    for key in (
        "summary", "dryrun", "would_delete", "deleted", "per_table",
        "policy_global_days", "policy_strict_days", "cohort_id_count",
    ):
        assert key in result, f"missing key: {key}"
    assert result["deleted"] == 0
    assert result["dryrun"] is True
    assert "DRY-RUN" in result["summary"]
    for tbl in ("conversation_history", "nevedal_metrics"):
        assert tbl in result["per_table"]


def test_dryrun_issues_zero_deletes(tmp_path):
    """Belt-and-suspenders: the FakeConn.execute() assertion ensures no
    DELETE ever runs, but also assert the writes recorder stays empty
    across a full pass."""
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_DRYRUN": "true",
        }
    )
    state = _seed_state()
    agent = _make_agent(state)
    asyncio.run(agent._enforce_retention_policy())
    assert state["writes"] == [], (
        f"dry-run path must not write; got: {state['writes']}"
    )
    # And we must have issued at least one COUNT query per table.
    fetchrow_sqls = [q[1] for q in state["queries"] if q[0] == "fetchrow"]
    assert any("conversation_history" in s for s in fetchrow_sqls)
    assert any("nevedal_metrics" in s for s in fetchrow_sqls)


def test_enforcement_forever_deletes_only_cohort(tmp_path):
    """Global forever + enforcement ON: delete Bee 30d rows only, never joe."""
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_ENFORCEMENT": "true",
            "ENABLE_RETENTION_DRYRUN": None,
        }
    )
    state = _seed_state()
    state["allow_writes"] = True
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert result.get("dryrun") is not True
    assert result["deleted"] == 2
    assert result["per_table"]["conversation_history"] == 1  # bee1 35d
    assert result["per_table"]["nevedal_metrics"] == 1  # HW_BEE1 40d
    deleted_users = []
    for kind, sql, payload in state["writes"]:
        if kind == "executemany":
            deleted_users.extend(row[0] for row in payload)
    assert "bee1" in deleted_users
    assert "HW_BEE1" in deleted_users
    assert "joe" not in deleted_users
    assert "HW_JOE" not in deleted_users


def test_enforcement_no_cohort_forever_is_zero(tmp_path):
    """No program_id column + forever → 0 deletes (do not wipe everyone)."""
    _reload_retention_policy(
        {
            "DATA_DIR": str(tmp_path),
            "ENABLE_RETENTION_ENFORCEMENT": "true",
            "ENABLE_RETENTION_DRYRUN": None,
        }
    )
    state = _seed_state()
    state["no_program_id_column"] = True
    state["allow_writes"] = True
    agent = _make_agent(state)
    result = asyncio.run(agent._enforce_retention_policy())
    assert result["deleted"] == 0
    assert all(n == 0 for n in result["per_table"].values())
    assert state["writes"] == []
