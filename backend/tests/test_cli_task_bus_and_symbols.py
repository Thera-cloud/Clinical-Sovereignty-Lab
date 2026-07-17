"""Offline tests: CLI task bus, symbolic_verify, live capability probes."""

import json
import os

import pytest

# Force offline / feature-off defaults for isolation
os.environ["REDIS_URL"] = ""
os.environ["CLI_TASK_BUS_ENABLED"] = "false"
os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "false"
os.environ["ENABLE_FORWARD_REASONING"] = "false"


class _FakeRedis:
    """Minimal in-memory Redis stand-in for bus/symbol probes."""

    def __init__(self):
        self._kv = {}
        self._lists = {}

    def setex(self, key, ttl, val):
        self._kv[key] = val
        return True

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self._kv:
            return False
        self._kv[key] = val
        return True

    def get(self, key):
        return self._kv.get(key)

    def exists(self, key):
        return 1 if key in self._kv or key in self._lists else 0

    def delete(self, key):
        self._kv.pop(key, None)
        return 1

    def expire(self, key, ttl):
        return True

    def rpush(self, key, *vals):
        self._lists.setdefault(key, []).extend(vals)
        return len(self._lists[key])

    def lpop(self, key):
        lst = self._lists.get(key) or []
        if not lst:
            return None
        v = lst.pop(0)
        if not lst:
            self._lists.pop(key, None)
        return v

    def llen(self, key):
        return len(self._lists.get(key) or [])

    def lrem(self, key, count, value):
        lst = self._lists.get(key) or []
        removed = 0
        new = []
        for item in lst:
            if item == value and (count == 0 or removed < abs(count)):
                removed += 1
                continue
            new.append(item)
        if new:
            self._lists[key] = new
        else:
            self._lists.pop(key, None)
        return removed


@pytest.fixture
def fake_redis(monkeypatch):
    fr = _FakeRedis()
    os.environ["CLI_TASK_BUS_ENABLED"] = "true"
    os.environ["REDIS_URL"] = "redis://fake"
    monkeypatch.setattr(
        "app.websocket.cli_task_bus._redis",
        lambda: fr,
    )
    yield fr
    os.environ["CLI_TASK_BUS_ENABLED"] = "false"
    os.environ["REDIS_URL"] = ""


def test_bus_round_trip_publish_claim_review(fake_redis):
    from app.websocket.cli_task_bus import (
        claim_task,
        enqueue_review,
        post_findings,
        probe_cross_cli_review_loop,
        probe_shared_task_bus,
        publish_task,
    )

    assert probe_shared_task_bus() is True
    assert probe_cross_cli_review_loop() is True

    pub = publish_task(
        origin="cloud",
        files=["backend/app/websocket/cli_task_bus.py"],
        kind="work",
        notes="unit test",
    )
    assert pub["status"] == "ok", pub
    task_id = pub["task"]["task_id"]

    # Same origin should not claim own work (re-queued)
    own = claim_task(consumer="cloud")
    assert own["status"] == "ok"
    # Peer claims
    claimed = claim_task(consumer="mac")
    assert claimed["status"] == "ok"
    assert claimed["task"] is not None
    assert claimed["task"]["task_id"] == task_id

    review = enqueue_review(origin="mac", files=["a.py"], notes="review me")
    assert review["status"] == "ok"
    rev_claim = claim_task(consumer="cloud", prefer_kind="review")
    assert rev_claim["task"] is not None
    tid = rev_claim["task"]["task_id"]
    findings = post_findings(
        tid,
        reviewer="cloud",
        findings=[{"detail": "missing test", "severity": "warn"}],
        pass_review=False,
    )
    assert findings["status"] == "ok"
    assert findings["task"]["review_round"] == 1
    assert findings["task"]["status"] == "fix_pending"


def test_symbolic_verify_rejects_fabricated_claim(monkeypatch):
    os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "true"
    os.environ["REDIS_URL"] = ""
    from app.websocket import cli_symbol_store as store

    facts = [{
        "kind": "flag_value",
        "key": "mac_cloud_ln_fab_partnership",
        "value": False,
        "source": "test",
    }]
    monkeypatch.setattr(store, "load_facts", lambda sk: facts)
    out = store.symbolic_verify(
        "Mac-cloud partnership is active and enabled right now. "
        "mac_cloud_ln_fab_partnership true",
        "sess-test",
        tool_call_log=[],
    )
    assert out["ok"] is False
    assert any(v["type"] == "symbol_contradiction" for v in out["violations"])
    os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "false"


def test_cross_review_produces_finding(fake_redis):
    from app.websocket.cli_task_bus import enqueue_review, claim_task, post_findings

    enq = enqueue_review(origin="cloud", files=["x.py"], notes="need review")
    assert enq["status"] == "ok"
    claimed = claim_task(consumer="mac", prefer_kind="review")
    assert claimed["task"]
    done = post_findings(
        claimed["task"]["task_id"],
        reviewer="mac",
        findings=[{"detail": "lint error on line 12"}],
        pass_review=True,
    )
    assert done["task"]["status"] == "review_done"
    assert done["task"]["findings"][0]["items"][0]["detail"] == "lint error on line 12"


def test_manifest_live_probes_off_without_redis():
    os.environ["REDIS_URL"] = ""
    os.environ["CLI_TASK_BUS_ENABLED"] = "false"
    os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "false"
    from app.websocket.cli_grounding import build_capabilities_manifest

    m = build_capabilities_manifest("ask", "cloud")
    assert m["mac_vs_cloud"]["shared_task_bus"] is False
    assert m["mac_vs_cloud"]["mac_cloud_ln_fab_partnership"] is False
    assert m["clinical_neuro_symbolic"]["wired_into_cli_loop"] is False


def test_manifest_probes_true_with_bus_and_flag(fake_redis, monkeypatch):
    os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "true"
    os.environ["ENABLE_FORWARD_REASONING"] = "true"
    from app.websocket.cli_grounding import build_capabilities_manifest
    from app.websocket.cli_task_bus import ensure_bus_meta

    ensure_bus_meta(fake_redis)
    # Force tool list to include symbolic_verify
    m = build_capabilities_manifest(
        "ln_fab",
        "cloud",
        tool_names=["self_capabilities", "symbolic_verify", "forward_reason", "task_bus_publish"],
    )
    assert m["clinical_neuro_symbolic"]["wired_into_cli_loop"] is True
    assert m["mac_vs_cloud"]["shared_task_bus"] is True
    assert m["mac_vs_cloud"]["cross_cli_review_loop"] is True
    assert m["mac_vs_cloud"]["mac_cloud_ln_fab_partnership"] is True
    assert "CLI neuro-symbolic fact store" in " ".join(m["implemented"])
    assert "Mac↔Cloud dual LN-FAB partnership / shared backlog" not in m["not_implemented"]
    os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "false"
    os.environ["ENABLE_FORWARD_REASONING"] = "false"


def test_symbolic_verify_tool_registered_when_flag_on():
    os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "true"
    from app.websocket.cli_tools import get_tool_definitions

    names = {
        t["function"]["name"]
        for t in get_tool_definitions("ask", "cloud")
        if "function" in t
    }
    assert "symbolic_verify" in names
    os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "false"


def test_handoff_endpoint_declared_in_agents_api_source():
    """Avoid importing agents_api (heavy deps); assert handoff surface in source."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "agents_api.py").read_text()
    assert 'origin_cli' in src
    assert '/agents/{run_id}/handoff' in src
    assert "class AgentHandoffBody" in src
    assert '"agent_run_handoff": True' in src
