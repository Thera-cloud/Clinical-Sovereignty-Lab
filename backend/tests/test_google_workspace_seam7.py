"""Seam 7: effective_scope, additive crystal domains, newsletter topics."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _FakeConn:
    def __init__(self):
        self.calls = []
        self.hierarchy = []
        self.clients = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        if "coach_hierarchy" in sql:
            return self.hierarchy
        if "FROM users" in sql:
            return self.clients
        if "coach_client_tasks" in sql and "SELECT" in sql:
            return []
        return []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        if "nate_intelligence_crystals" in sql and "COUNT" in sql:
            return {"marketing": 40, "clinical": 5}
        return {"id": "task-1", "coach_id": args[0] if args else "", "client_id": args[1] if len(args) > 1 else "", "assignee_id": args[2] if len(args) > 2 else "", "title": args[3] if len(args) > 3 else "", "status": "open"}

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self):
        self.conn = _FakeConn()

    def acquire(self):
        return _Acquire(self.conn)


def test_additive_domains_and_therapeutic_alias():
    from app.services.crystal_domains import (
        ADDITIVE_DOMAINS,
        BUDGET_ALLOWLIST,
        CANONICAL_SEVEN,
        marketing_crowds_clinical,
        normalize_domain,
        pad_domain_rows,
    )

    assert "clinical" in CANONICAL_SEVEN
    assert "therapeutic" not in CANONICAL_SEVEN
    assert ADDITIVE_DOMAINS == {"product", "coding", "operational"}
    assert ADDITIVE_DOMAINS <= BUDGET_ALLOWLIST
    assert normalize_domain("therapeutic") == "clinical"
    assert normalize_domain("product") == "product"
    assert marketing_crowds_clinical({"marketing": 40, "clinical": 5}) is True
    assert marketing_crowds_clinical({"marketing": 4, "clinical": 20}) is False
    rows = pad_domain_rows([{"domain": "clinical", "crystal_count": 3}])
    domains = {r["domain"] for r in rows}
    assert {"clinical", "marketing", "product", "coding", "operational"} <= domains
    clinical = next(r for r in rows if r["domain"] == "clinical")
    product = next(r for r in rows if r["domain"] == "product")
    assert clinical["crystal_count"] == 3
    assert product["crystal_count"] == 0


def test_four_file_ng15_sync():
    cryst = (ROOT / "backend/app/services/nate_memory_crystallizer.py").read_text()
    agents = (ROOT / "backend/app/services/nate_agent_template.py").read_text()
    analytics = (ROOT / "backend/app/services/r2_analytics_service.py").read_text()
    rule = (ROOT / ".cursor/rules/crystal-intelligence-integrity.mdc").read_text()
    for blob in (cryst, agents, rule):
        assert "product" in blob
        assert "operational" in blob
        assert "coding" in blob
    assert "pad_domain_rows" in analytics
    assert "BUDGET_ALLOWLIST" in analytics
    assert "therapeutic" in cryst
    assert "crowd" in rule
    assert "role='master_coach'" not in (ROOT / "backend/app/services/effective_scope.py").read_text()
    api = (ROOT / "backend/app/routers/google_workspace_api.py").read_text()
    assert "/supervision" in api
    assert "ENABLE_SUPERVISION_VIEW" in api


@pytest.mark.asyncio
async def test_scope_own_clients_only_when_supervision_off(monkeypatch):
    from app.services.effective_scope import effective_scope

    monkeypatch.setenv("ENABLE_SUPERVISION_VIEW", "false")
    pool = _FakePool()
    pool.conn.clients = [{"hardware_id": "CLIENT_A"}]
    pool.conn.hierarchy = [{"assistant_id": "COACH_ASST"}]
    out = await effective_scope(pool, "COACH_MASTER")
    assert out["coach_ids"] == ["COACH_MASTER"]
    assert out["assistants"] == []
    assert out["is_master"] is False
    assert out["client_hardware_ids"] == ["CLIENT_A"]
    assert out["supervision_visible"] is False
    sqls = [c[1] for c in pool.conn.calls]
    assert not any("coach_hierarchy" in s for s in sqls)


@pytest.mark.asyncio
async def test_master_scope_includes_assistant_clients(monkeypatch):
    from app.services.effective_scope import client_in_scope, effective_scope

    monkeypatch.setenv("ENABLE_SUPERVISION_VIEW", "true")
    pool = _FakePool()
    pool.conn.hierarchy = [{"assistant_id": "COACH_ASST"}]
    pool.conn.clients = [{"hardware_id": "CLIENT_M"}, {"hardware_id": "CLIENT_A"}]
    out = await effective_scope(pool, "COACH_MASTER")
    assert out["is_master"] is True
    assert "COACH_ASST" in out["coach_ids"]
    assert set(out["client_hardware_ids"]) == {"CLIENT_M", "CLIENT_A"}
    assert await client_in_scope(pool, "COACH_MASTER", "CLIENT_A") is True
    assert await client_in_scope(pool, "COACH_MASTER", "CLIENT_X") is False
    audits = [c for c in pool.conn.calls if c[0] == "execute" and "supervision_access_audit" in c[1]]
    assert audits


@pytest.mark.asyncio
async def test_task_create_rejects_out_of_scope(monkeypatch):
    from app.services.coach_task_service import create_task
    from app.services.google_workspace_service import FlagOff

    monkeypatch.setenv("ENABLE_COACH_TASKS", "false")
    pool = _FakePool()
    with pytest.raises(FlagOff):
        await create_task(pool, "COACH_HW", client_id="CLIENT_A", title="Call")

    monkeypatch.setenv("ENABLE_COACH_TASKS", "true")
    monkeypatch.setenv("ENABLE_SUPERVISION_VIEW", "false")
    pool.conn.clients = [{"hardware_id": "CLIENT_A"}]
    with pytest.raises(PermissionError):
        await create_task(pool, "COACH_HW", client_id="CLIENT_B", title="Call")
    row = await create_task(pool, "COACH_HW", client_id="CLIENT_A", title="Breathwork")
    assert row["client_id"] == "CLIENT_A"
    assert row["assignee_id"] == "COACH_HW"


@pytest.mark.asyncio
async def test_newsletter_topics_and_source_type(monkeypatch):
    from app.services.google_workspace_service import FlagOff
    from app.services.newsletter_service import record_topics, stamp_source_crystal

    monkeypatch.setenv("ENABLE_COACH_NEWSLETTER", "false")
    pool = _FakePool()
    with pytest.raises(FlagOff):
        await record_topics(pool, ["presence"])

    monkeypatch.setenv("ENABLE_COACH_NEWSLETTER", "true")
    n = await record_topics(pool, ["presence", " "])
    assert n == 1
    digest = await stamp_source_crystal(pool, text="Issue 1")
    assert digest
    inserts = [c for c in pool.conn.calls if c[0] == "execute"]
    assert any("content_topics" in c[1] for c in inserts)
    crystal = next(c for c in inserts if "nate_intelligence_crystals" in c[1])
    assert "source_type" in crystal[1]
    assert "newsletter" in crystal[2]


@pytest.mark.asyncio
async def test_marketing_budget_blocks_harvest(monkeypatch):
    from app.services.crystal_domains import allow_harvest

    pool = _FakePool()
    assert await allow_harvest(pool, "clinical") is True
    assert await allow_harvest(pool, "marketing") is False
