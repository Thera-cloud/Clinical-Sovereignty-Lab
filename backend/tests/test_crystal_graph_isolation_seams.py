"""Phase 5d crystal graph isolation seam tests — offline."""

import pytest

from app.services.crystal_graph_isolation import (
    enforce_traversal_scope,
    scope_allows_recall,
)


def test_cross_user_owned_crystal_blocked():
    crystal = {"scope": "global", "user_id": "uuid-other-user"}
    assert enforce_traversal_scope(crystal, "client_a") is False


def test_admin_only_scope_blocked():
    assert scope_allows_recall("admin_only", None, "client1") is False


def test_user_scope_requires_matching_requester():
    assert scope_allows_recall("user:client_a", None, "client_a") is True
    assert scope_allows_recall("user:client_a", None, "client_b") is False


def test_global_ownerless_allowed():
    assert scope_allows_recall("global", None, "client1") is True
    assert scope_allows_recall("global", "some-owner", "client1") is False
