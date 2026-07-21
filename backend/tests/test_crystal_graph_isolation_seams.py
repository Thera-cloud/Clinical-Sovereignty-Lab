"""Phase 5d crystal graph isolation seam tests — offline (all adversarial gates)."""

from __future__ import annotations

import os

import pytest

from app.services.crystal_graph_isolation import (
    audit_graph_traversal_isolation,
    crystal_graph_enabled,
    enforce_traversal_scope,
    fetch_graph_surfaced_crystal_ids,
    scope_allows_recall,
)


@pytest.fixture(autouse=True)
def _reset_flag():
    prev = os.environ.get("ENABLE_CRYSTAL_GRAPH")
    yield
    if prev is None:
        os.environ.pop("ENABLE_CRYSTAL_GRAPH", None)
    else:
        os.environ["ENABLE_CRYSTAL_GRAPH"] = prev


def test_key_traversal_enforces_per_user_scope():
    """Gate Key: requester cannot traverse another user's crystal."""
    crystal = {"scope": "user", "user_id": "uuid-other-user"}
    assert enforce_traversal_scope(crystal, "client_a") is False
    own = {"scope": "user", "user_id": "client_a"}
    assert enforce_traversal_scope(own, "client_a") is True


def test_lifecycle_phi_auditor_gated_on_graph_flag():
    """Gate Lifecycle: graph-surfaced PHI scan only when ENABLE_CRYSTAL_GRAPH on."""
    # Documented in crystal_phi_auditor.py — flag gate mirrors this helper.
    os.environ["ENABLE_CRYSTAL_GRAPH"] = "false"
    assert crystal_graph_enabled() is False
    os.environ["ENABLE_CRYSTAL_GRAPH"] = "true"
    assert crystal_graph_enabled() is True


def test_surface_graph_flag_independent_of_l3_opt_in():
    """Gate Surface: ENABLE_CRYSTAL_GRAPH is its own env flag (not L3 consent)."""
    os.environ["ENABLE_CRYSTAL_GRAPH"] = "false"
    assert crystal_graph_enabled() is False
    # L3 / helix opt-in vars must not enable graph
    os.environ["ENABLE_NOETIC_HELIX"] = "true"
    os.environ["ENABLE_QUANTUM_CRYSTAL"] = "true"
    assert crystal_graph_enabled() is False
    os.environ.pop("ENABLE_NOETIC_HELIX", None)
    os.environ.pop("ENABLE_QUANTUM_CRYSTAL", None)


@pytest.mark.asyncio
async def test_seam_isolation_audit_reports_cross_boundary():
    """Gate Seam: audit report lists scope_isolation violations."""

    class _Conn:
        async def fetchrow(self, sql, *args):
            return {
                "id": "11111111-1111-1111-1111-111111111111",
                "scope": "admin_only",
                "user_id": None,
                "crystal_text": "secret",
            }

        async def fetch(self, sql, *args):
            return []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    report = await audit_graph_traversal_isolation(
        _Pool(),
        seed_crystal_ids=["seed-hash"],
        requester_user_id="client1",
        max_hops=1,
    )
    assert report["violations"]
    assert report["violations"][0]["reason"] == "scope_isolation"
    assert report["blocked_edges"] >= 1


@pytest.mark.asyncio
async def test_time_readonly_audit_safe_with_flag_off():
    """Gate Time: audit runs with ENABLE_CRYSTAL_GRAPH=false (no writes)."""
    os.environ["ENABLE_CRYSTAL_GRAPH"] = "false"
    assert crystal_graph_enabled() is False

    class _Conn:
        async def fetchrow(self, sql, *args):
            return {
                "id": "22222222-2222-2222-2222-222222222222",
                "scope": "global",
                "user_id": None,
                "crystal_text": "ok",
            }

        async def fetch(self, sql, *args):
            return []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    report = await audit_graph_traversal_isolation(
        _Pool(),
        seed_crystal_ids=["g1"],
        requester_user_id="client1",
        max_hops=1,
    )
    assert "error" not in report or not report.get("error")
    assert report["visited"] >= 1
    assert report["violations"] == []


@pytest.mark.asyncio
async def test_fetch_graph_surfaced_ids_empty_without_pool():
    assert await fetch_graph_surfaced_crystal_ids(None) == []


def test_cross_user_owned_crystal_blocked():
    crystal = {"scope": "global", "user_id": "uuid-other-user"}
    assert enforce_traversal_scope(crystal, "client_a") is False


def test_admin_only_scope_blocked():
    assert scope_allows_recall("admin_only", None, "client1") is False


def test_user_scope_requires_matching_requester():
    assert scope_allows_recall("user:client_a", None, "client_a") is True
    assert scope_allows_recall("user:client_a", None, "client_b") is False


def test_plain_user_scope_allowed_when_owner_unknown():
    """DB personal crystals use scope='user'; verifier passes owner=None."""
    assert scope_allows_recall("user", None, "client1") is True
    assert scope_allows_recall("user", "uuid-a", "uuid-a") is True
    assert scope_allows_recall("user", "uuid-a", "uuid-b") is False


def test_global_ownerless_allowed():
    assert scope_allows_recall("global", None, "client1") is True
    assert scope_allows_recall("global", "some-owner", "client1") is False


@pytest.mark.asyncio
async def test_live_retrieve_constellation_blocks_cross_user():
    """Live path: retrieve_constellation must not return another user's crystal."""
    from app.services.crystal_graph import CrystalGraph, CrystalNode

    g = CrystalGraph(db_pool=None)
    own = CrystalNode({
        "id": "a", "crystal_text": "anxiety coping breath", "domain": "clinical",
        "confidence": 0.9, "content_hash": "h1", "scope": "user", "user_id": "client_a",
    })
    other = CrystalNode({
        "id": "b", "crystal_text": "anxiety coping breath", "domain": "clinical",
        "confidence": 0.95, "content_hash": "h2", "scope": "user", "user_id": "client_b",
    })
    g._nodes = {own.id: own, other.id: other}
    g._adj = {own.id: {other.id: 0.5}, other.id: {own.id: 0.5}}
    g._last_rebuild = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    results = await g.retrieve_constellation(
        "anxiety coping breath", max_depth=2, max_results=10, requester_user_id="client_a",
    )
    assert results
    assert all(r.get("user_id") == "client_a" for r in results)
    assert not any(r.get("user_id") == "client_b" for r in results)


@pytest.mark.asyncio
async def test_entanglement_get_neighbors_requires_requester():
    """EntanglementGraph fails closed without requester_user_id."""
    from app.services.quantum_crystal_orchestrator import EntanglementGraph

    class _Conn:
        async def fetch(self, *a, **k):
            return [{"src": "a", "dst": "b", "edge_type": "x", "strength": 0.5, "depth": 1}]

        async def fetchrow(self, *a, **k):
            return {"scope": "user", "user_id": "other"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    g = EntanglementGraph(db_pool=_Pool())
    assert await g.get_neighbors("abcdefghijklmnop") == []
